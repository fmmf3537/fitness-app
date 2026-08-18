"""PRD §4 数据模型（共 11 张表，字段与 PRD SQL 一一对应）。"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Setting(Base):
    """用户配置（单用户，单行表）。"""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    garmin_token_store: Mapped[str | None] = mapped_column(Text)
    xunji_api_key_enc: Mapped[str | None] = mapped_column(Text)
    default_llm: Mapped[str | None] = mapped_column(String(50))
    llm_keys_json_enc: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class XunjiTrain(Base):
    """训记原始训练（按 datestr+localid 幂等）。"""

    __tablename__ = "xunji_train"
    __table_args__ = (UniqueConstraint("datestr", "localid", name="uq_xunji_train_datestr_localid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    datestr: Mapped[str] = mapped_column(String(10))
    localid: Mapped[str] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(200))
    start_ms: Mapped[int | None] = mapped_column(BigInteger)
    end_ms: Mapped[int | None] = mapped_column(BigInteger)
    note_json: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GarminActivity(Base):
    """佳明原始活动（按 activity_id 幂等）。"""

    __tablename__ = "garmin_activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[str] = mapped_column(String(64), unique=True)
    activity_type: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str | None] = mapped_column(String(200))
    start_ts: Mapped[datetime | None] = mapped_column(DateTime)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    calories: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GarminDaily(Base):
    """佳明每日健康（按日期幂等）。"""

    __tablename__ = "garmin_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True)
    steps: Mapped[int | None] = mapped_column(Integer)
    resting_hr: Mapped[int | None] = mapped_column(Integer)
    stress_avg: Mapped[int | None] = mapped_column(Integer)
    body_battery_high: Mapped[int | None] = mapped_column(Integer)
    body_battery_low: Mapped[int | None] = mapped_column(Integer)
    hrv_status: Mapped[str | None] = mapped_column(String(50))
    sleep_json: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BodyMetric(Base):
    """身体数据（手动录入，按 date+type 幂等）。"""

    __tablename__ = "body_metric"
    __table_args__ = (UniqueConstraint("date", "type", name="uq_body_metric_date_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(20))  # height / weight / bp_systolic / bp_diastolic / blood_glucose
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(10))  # cm / kg / mmHg / mmol/L
    synced_to_xunji: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Workout(Base):
    """融合训练档案（核心表）。"""

    __tablename__ = "workout"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    title: Mapped[str | None] = mapped_column(String(200))
    xunji_train_id: Mapped[int | None] = mapped_column(ForeignKey("xunji_train.id"))
    garmin_activity_id: Mapped[int | None] = mapped_column(ForeignKey("garmin_activity.id"))
    match_status: Mapped[str | None] = mapped_column(String(20))
    # auto_matched / manual_matched / xunji_only / garmin_only / pending
    tags: Mapped[str | None] = mapped_column(String(200))  # 佳明活动类型作标签（PRD §5.2）
    duration_s: Mapped[int | None] = mapped_column(Integer)  # 以佳明为准
    calories: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    movements_json: Mapped[str | None] = mapped_column(Text)  # 以训记为准
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MatchCandidate(Base):
    """待确认队列。"""

    __tablename__ = "match_candidate"

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int | None] = mapped_column(ForeignKey("workout.id"))
    xunji_train_id: Mapped[int | None] = mapped_column(ForeignKey("xunji_train.id"))
    garmin_activity_id: Mapped[int | None] = mapped_column(ForeignKey("garmin_activity.id"))
    reason: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / merged / split
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class XunjiPlan(Base):
    """训记官方计划缓存（只读）。"""

    __tablename__ = "xunji_plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_ref: Mapped[str | None] = mapped_column(String(100))
    plan_json: Mapped[str | None] = mapped_column(Text)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIReport(Base):
    """AI 报告。"""

    __tablename__ = "ai_report"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20))  # session_review / next_advice / weekly / monthly
    workout_id: Mapped[int | None] = mapped_column(ForeignKey("workout.id"))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    content_md: Mapped[str | None] = mapped_column(Text)
    # V3-4 评分体系（仅 session_review 使用；存量报告为 NULL）
    score: Mapped[int | None] = mapped_column(Integer)
    one_liner: Mapped[str | None] = mapped_column(String(200))
    subscores_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReportChatMessage(Base):
    """AI 报告追问对话消息（V3-8）。

    client_request_id 为幂等键：客户端每次发送生成 UUID，重试/重放时
    服务端直接返回已落库的消息对，不重复调 LLM。仅用户消息携带该键。
    """

    __tablename__ = "report_chat_message"
    __table_args__ = (
        UniqueConstraint(
            "client_request_id", name="uq_report_chat_message_client_request_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("ai_report.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(10))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    client_request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LLMCall(Base):
    """LLM 调用记账。"""

    __tablename__ = "llm_call"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    purpose: Mapped[str | None] = mapped_column(String(50))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BackfillProgress(Base):
    """历史导入进度（V1-2）：断点续传依据。

    source: xunji / garmin_activity / garmin_daily / fusion；
    date: ISO 日期或标记串（page:<offset> / all）；
    status: done / empty / failed（failed 会在下次运行重试）。
    """

    __tablename__ = "backfill_progress"
    __table_args__ = (UniqueConstraint("source", "date", name="uq_backfill_progress_source_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    date: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class JobRun(Base):
    """任务运行日志。"""

    __tablename__ = "job_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[str | None] = mapped_column(Text)
