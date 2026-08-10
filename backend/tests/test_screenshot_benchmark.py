"""V2-3 基准测试：训记标准报表示例图字段识别准确率 ≥ 95%（真实视觉 API，默认跳过）。

运行方式：$env:RUN_VISION_INTEGRATION='1'; pytest -m integration tests/test_screenshot_benchmark.py
基准图：素材/训记分享报表示例.png（2026-08-03 背·二头·2，6 动作 22 组）

ground truth 逐字段比对口径：
- 顶层字段：datestr / title / calories / duration_s（±60s 容差）共 4 个；
- 动作名字段：6 个（按图中顺序）；
- 组次字段：每组 weight + reps，22 组共 44 个（哑铃动作按两侧重量之和比对）；
合计 54 个字段，准确率 = 正确数 / 54。
"""
import os
from pathlib import Path

import pytest

from app.services.screenshot import extract_from_image

SAMPLE_IMAGE = Path(__file__).resolve().parents[2] / "素材" / "训记分享报表示例.png"

EXPECTED = {
    "datestr": "2026-08-03",
    "title": "背·二头·2",
    "calories": 186,
    "duration_s": 47 * 60,  # 47 分钟
    "movements": [
        {"name": "宽距高位下拉", "sets": [(40, 10)] * 5},
        {"name": "V-bar下拉", "sets": [(35, 10)] * 4},
        {"name": "坐姿划船", "sets": [(35, 10)] * 4},
        {"name": "绳索弯举", "sets": [(15, 12)] * 3},
        {"name": "上斜哑铃弯举", "sets": [(10, 8), (15, 8), (12.5, 8)]},
        {"name": "集中弯举", "sets": [(10, 8), (15, 8), (12.5, 8)]},
    ],
}


def _field_report(data: dict) -> tuple[int, int, list[str]]:
    """逐字段比对，返回 (正确数, 总字段数, 错误描述列表)。"""
    correct = 0
    total = 0
    misses: list[str] = []

    def check(label, ok):
        nonlocal correct, total
        total += 1
        if ok:
            correct += 1
        else:
            misses.append(label)

    check("datestr", data.get("datestr") == EXPECTED["datestr"])
    check("title", data.get("title") == EXPECTED["title"])
    check("calories", data.get("calories") == EXPECTED["calories"])
    duration = data.get("duration_s")
    check("duration_s", duration is not None and abs(duration - EXPECTED["duration_s"]) <= 60)

    actual_movements = data.get("movements") or []
    for i, exp_mv in enumerate(EXPECTED["movements"]):
        mv = actual_movements[i] if i < len(actual_movements) else {}
        check(f"movements[{i}].name={exp_mv['name']}", mv.get("name") == exp_mv["name"])
        actual_sets = mv.get("sets") or []
        for j, (weight, reps) in enumerate(exp_mv["sets"]):
            s = actual_sets[j] if j < len(actual_sets) else {}
            check(
                f"{exp_mv['name']}[{j}].weight={weight}",
                s.get("weight") is not None and abs(float(s["weight"]) - weight) < 0.01,
            )
            check(f"{exp_mv['name']}[{j}].reps={reps}", s.get("reps") == reps)
    # 多识别出的动作/组对应的期望字段不存在，不计入分母（宽松口径，只考召回字段正确性）
    return correct, total, misses


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_VISION_INTEGRATION") != "1",
    reason="真实外呼 Kimi 视觉消耗额度，默认跳过；手动运行：$env:RUN_VISION_INTEGRATION='1'; pytest -m integration",
)
def test_benchmark_xunji_share_report(session):
    """字段识别准确率 ≥ 95%（PRD US-11 AC3）。"""
    assert SAMPLE_IMAGE.exists(), f"基准图不存在：{SAMPLE_IMAGE}"
    data = extract_from_image(SAMPLE_IMAGE.read_bytes(), session=session)

    correct, total, misses = _field_report(data)
    accuracy = correct / total
    print(f"\n字段识别准确率：{correct}/{total} = {accuracy:.1%}")
    if misses:
        print("未命中字段：")
        for m in misses:
            print(f"  - {m}")
    assert accuracy >= 0.95, f"准确率 {accuracy:.1%} < 95%，未命中：{misses}"
