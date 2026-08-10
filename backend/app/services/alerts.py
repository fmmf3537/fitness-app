"""V2-4 健康检查告警推送（PRD §7 / US-1 AC2 告警延伸）。

规则：
- health_check 中同一数据源（garmin/xunji）连续失败 ≥ ALERT_THRESHOLD 次 → 推送告警；
- 告警文案含失败接口、错误摘要、建议操作（佳明 → 手动导出 FIT/TCX 上传降级通道）；
- 同故障 30 分钟冷却去重（以 job_run 中 job_name='alert' 的记录为依据），不重复轰炸；
- 通道配置化：Server酱（SERVERCHAN_SENDKEY）与 SMTP 邮件可独立启用，两者都配则双发；
- 告警自身的失败不向外抛，只落 job_run 日志。
"""
from __future__ import annotations

import json
import smtplib
from datetime import datetime, timedelta
from email.header import Header
from email.mime.text import MIMEText
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import JobRun

ALERT_THRESHOLD = 3
ALERT_COOLDOWN_MINUTES = 30
HEALTH_RUN_LOOKBACK = 20  # 评估时回看最近 N 次健康检查

SOURCE_LABELS = {"garmin": "佳明", "xunji": "训记"}
SOURCE_SUGGESTIONS = {
    "garmin": "建议操作：1) 检查 GARMIN_EMAIL/GARMIN_PASSWORD 与 token 缓存（~/.garminconnect）；"
              "2) 若接口持续失效，请从 Garmin Connect 手动导出 FIT/TCX 文件，"
              "在「文件导入」页上传（/import/fit 降级通道）。",
    "xunji": "建议操作：检查 XUNJI_API_KEY 是否过期（训记 App 内重新申请），"
             "并确认网络可达 trains.xunjiapp.cn。",
}


class AlertNotifier:
    """告警推送器：Server酱 + SMTP 双通道；post_fn/smtp_fn 可注入以便测试。"""

    def __init__(
        self,
        *,
        serverchan_sendkey: str = "",
        smtp_host: str = "",
        smtp_port: int = 465,
        smtp_user: str = "",
        smtp_pass: str = "",
        alert_email: str = "",
        post_fn: Callable[..., Any] | None = None,
        smtp_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._sendkey = serverchan_sendkey
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_pass = smtp_pass
        self._alert_email = alert_email
        self._post_fn = post_fn or self._default_post
        self._smtp_fn = smtp_fn or self._default_smtp

    @property
    def channels(self) -> list[str]:
        channels = []
        if self._sendkey:
            channels.append("serverchan")
        if self._smtp_host and self._alert_email:
            channels.append("smtp")
        return channels

    def send(self, title: str, content: str) -> dict:
        """逐通道发送，返回 {"sent": [...], "failed": {channel: error}}；单通道异常不影响其他通道。"""
        sent: list[str] = []
        failed: dict[str, str] = {}
        if "serverchan" in self.channels:
            try:
                self._post_fn(
                    f"https://sctapi.ftqq.com/{self._sendkey}.send",
                    data={"title": title, "desp": content},
                    timeout=10,
                )
                sent.append("serverchan")
            except Exception as exc:
                failed["serverchan"] = str(exc)
        if "smtp" in self.channels:
            try:
                self._smtp_fn(
                    host=self._smtp_host, port=self._smtp_port,
                    user=self._smtp_user, password=self._smtp_pass,
                    to=self._alert_email, title=title, content=content,
                )
                sent.append("smtp")
            except Exception as exc:
                failed["smtp"] = str(exc)
        return {"sent": sent, "failed": failed}

    @staticmethod
    def _default_post(url: str, *, data: dict, timeout: int) -> None:
        import httpx

        resp = httpx.post(url, data=data, timeout=timeout)
        resp.raise_for_status()

    @staticmethod
    def _default_smtp(*, host: str, port: int, user: str, password: str,
                      to: str, title: str, content: str) -> None:
        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = Header(title, "utf-8")
        msg["From"] = user
        msg["To"] = to
        with smtplib.SMTP_SSL(host, port, timeout=15) as server:
            if user and password:
                server.login(user, password)
            server.sendmail(user, [to], msg.as_string())


def notifier_from_settings() -> AlertNotifier:
    """按环境变量配置构造推送器（密钥只从环境变量读取）。"""
    s = get_settings()
    return AlertNotifier(
        serverchan_sendkey=s.serverchan_sendkey,
        smtp_host=s.smtp_host, smtp_port=s.smtp_port,
        smtp_user=s.smtp_user, smtp_pass=s.smtp_pass,
        alert_email=s.alert_email,
    )


def _consecutive_failures(runs: list[JobRun], source: str) -> tuple[int, str | None]:
    """从最新到最旧统计 source 的连续失败次数，返回 (次数, 最近一次错误摘要)。"""
    consecutive = 0
    latest_error: str | None = None
    for run in runs:
        try:
            detail = json.loads(run.detail_json or "{}")
        except json.JSONDecodeError:
            detail = {}
        failed_sources = detail.get("failed_sources") or []
        if source not in failed_sources:
            break
        consecutive += 1
        if latest_error is None:
            latest_error = _extract_source_error(run.error, source)
    return consecutive, latest_error


def _extract_source_error(error: str | None, source: str) -> str | None:
    """health_check 的 error 形如 'xunji: ...; garmin: ...'，提取对应源的分段。"""
    if not error:
        return None
    for segment in error.split("; "):
        if segment.startswith(f"{source}:"):
            return segment[len(source) + 1:].strip()[:300]
    return error[:300]


def _recently_alerted(session: Session, source: str, now: datetime) -> bool:
    """冷却判定：30 分钟内已向该源发过（status='sent'）告警则视为冷却中。"""
    cutoff = now - timedelta(minutes=ALERT_COOLDOWN_MINUTES)
    runs = (
        session.query(JobRun)
        .filter(JobRun.job_name == "alert", JobRun.status == "sent",
                JobRun.finished_at >= cutoff)
        .all()
    )
    for run in runs:
        try:
            detail = json.loads(run.detail_json or "{}")
        except json.JSONDecodeError:
            continue
        if detail.get("source") == source:
            return True
    return False


def evaluate_health_alerts(
    session: Session,
    *,
    notifier: AlertNotifier | None = None,
    now: datetime | None = None,
) -> dict:
    """评估健康检查历史并对达到阈值的故障源推送告警，返回 {"alerts": [...]}。"""
    now = now or datetime.now()
    notifier = notifier if notifier is not None else notifier_from_settings()
    runs = (
        session.query(JobRun)
        .filter(JobRun.job_name == "health_check")
        .order_by(JobRun.id.desc())
        .limit(HEALTH_RUN_LOOKBACK)
        .all()
    )

    alerts: list[dict] = []
    for source in ("xunji", "garmin"):
        consecutive, error_summary = _consecutive_failures(runs, source)
        if consecutive < ALERT_THRESHOLD or _recently_alerted(session, source, now):
            continue

        label = SOURCE_LABELS.get(source, source)
        title = f"【健身看板告警】{label}接口连续 {consecutive} 次失败"
        content = (
            f"失败接口：{source}（{label}）\n"
            f"错误摘要：{error_summary or '（无错误详情）'}\n"
            f"{SOURCE_SUGGESTIONS.get(source, '建议操作：检查对应凭据与网络。')}"
        )

        if not notifier.channels:
            status, error = "skipped", "未配置告警通道（SERVERCHAN_SENDKEY / SMTP）"
            send_result = {"sent": [], "failed": {}}
        else:
            send_result = notifier.send(title, content)
            if send_result["sent"]:
                status, error = "sent", None
            else:
                status = "failed"
                error = "; ".join(f"{c}: {e}" for c, e in send_result["failed"].items())

        run = JobRun(
            job_name="alert",
            started_at=now,
            finished_at=now,
            status=status,
            error=error,
            detail_json=json.dumps(
                {"source": source, "consecutive": consecutive,
                 "channels": send_result["sent"], "title": title},
                ensure_ascii=False,
            ),
        )
        session.add(run)
        session.commit()
        alerts.append({"source": source, "status": status, "consecutive": consecutive})
    return {"alerts": alerts}
