"""V3-9 真实样本验收：用 素材/picooc-body-report-sample.jpg 跑一次 extract-from-image。

真实调用 Kimi 多模态（KIMI_API_KEY 从 .env 读取），打印识别结果 JSON 供逐项核对。
用法：python scripts/verify_body_image_sample.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.body_image import extract_from_image  # noqa: E402

SAMPLE = ROOT / "素材" / "picooc-body-report-sample.jpg"

# 期望对照表（图片逐项人工核对值）
EXPECTED = {
    "weight": 86.7,
    "bodyfat": 25.5,
    "visceral_fat": 13,
    "bmr": 1764,
    "muscle_ability": 3.0,
    "muscle_rate": 70.8,
    "water_rate": 51.9,
    "protein_rate": 18.9,
    "bone_mass": 3.2,
    "bmi": 29.3,
    "body_age": 44,
    "body_score": 72,
}


def main() -> int:
    data = extract_from_image(SAMPLE.read_bytes(), mime="image/jpeg")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    got = {m["type"]: m["value"] for m in data["metrics"]}
    print(f"\ndate: {data['date']}")
    print(f"{'指标':<14}{'识别':>8}{'期望':>8}  结果")
    ok = True
    for type_, expected in EXPECTED.items():
        actual = got.get(type_)
        match = actual is not None and abs(float(actual) - expected) < 1e-9
        ok = ok and match
        print(f"{type_:<14}{str(actual):>8}{expected:>8}  {'OK' if match else 'MISMATCH'}")
    missing = set(got) - set(EXPECTED)
    if missing:
        print(f"额外识别项: {sorted(missing)}")
    print(f"\n{'ALL MATCH' if ok and len(got) >= len(EXPECTED) else 'MISMATCH FOUND'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
