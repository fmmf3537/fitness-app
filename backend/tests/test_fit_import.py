"""V2-4 佳明 FIT/TCX 文件导入降级通道测试（PRD §6.2 失效降级 /import/fit）。

样本文件由测试内构造：
- FIT：最小合法二进制（14 字节头 + session 消息 + CRC）；
- TCX：TrainingCenterDatabase v2 XML。
"""
import json
import struct
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.models import GarminActivity, Workout
from tests.conftest import make_xunji_train

DAY = date(2026, 8, 5)
BJ = timezone(timedelta(hours=8))
# 样本活动：北京 18:00 - 19:00（UTC 10:00 - 11:00），力量训练
START_UTC = datetime(2026, 8, 5, 10, 0, 0, tzinfo=timezone.utc)
DURATION_S = 3600

# ---------- 样本文件构造 ----------

FIT_EPOCH = 631065600  # FIT 时间戳纪元 1989-12-31T00:00:00Z

_CRC_TABLE = (
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
)


def _crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def build_fit_bytes(*, start_utc=START_UTC, duration_s=DURATION_S, sport=10,
                    sub_sport=20, calories=300, avg_hr=120, max_hr=150) -> bytes:
    """构造最小合法 FIT：session 消息（global 18）含运动类型/起止/热量/心率。"""
    ts = int(start_utc.timestamp()) - FIT_EPOCH
    fields = [
        (253, 4, 0x86),  # timestamp uint32
        (2, 4, 0x86),    # start_time uint32
        (5, 1, 0x00),    # sport enum
        (6, 1, 0x00),    # sub_sport enum
        (7, 4, 0x86),    # total_elapsed_time uint32（scale 1000）
        (11, 2, 0x84),   # total_calories uint16
        (16, 1, 0x02),   # avg_heart_rate uint8
        (17, 1, 0x02),   # max_heart_rate uint8
    ]
    definition = bytes([0x40]) + struct.pack("<BBHB", 0, 0, 18, len(fields))
    definition += b"".join(bytes([num, size, btype]) for num, size, btype in fields)
    data = bytes([0x00]) + struct.pack(
        "<IIBBIHBB", ts, ts, sport, sub_sport, int(duration_s * 1000), calories, avg_hr, max_hr
    )
    records = definition + data
    header = struct.pack("<BBHI4s", 14, 0x10, 100, len(records), b".FIT")
    header += struct.pack("<H", _crc16(header))
    return header + records + struct.pack("<H", _crc16(header + records))


TCX_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Strength">
      <Id>2026-08-05T10:00:00.000Z</Id>
      <Lap StartTime="2026-08-05T10:00:00.000Z">
        <TotalTimeSeconds>3600.0</TotalTimeSeconds>
        <Calories>300</Calories>
        <AverageHeartRateBpm><Value>120</Value></AverageHeartRateBpm>
        <MaximumHeartRateBpm><Value>150</Value></MaximumHeartRateBpm>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""


# 小米运动健康 TCX 导出（V3-11 真实案例：creator="Mi Fitness"）：
# Lap 无 StartTime 属性、Activity/Id 是 ISO 时间戳、HeartRateBpm 裸值无 Value 子节点、
# Lap 有 DistanceMeters、无 MaximumHeartRateBpm
TCX_MI_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Running">
      <Id>2026-08-16T07:31:03.000Z</Id>
      <Lap>
        <TotalTimeSeconds>2376.0</TotalTimeSeconds>
        <DistanceMeters>5022.0</DistanceMeters>
        <Calories>350</Calories>
        <AverageHeartRateBpm>138</AverageHeartRateBpm>
        <Track>
          <Trackpoint><Time>2026-08-16T07:31:03.000Z</Time></Trackpoint>
          <Trackpoint><Time>2026-08-16T08:10:39.000Z</Time></Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""


@pytest.fixture
def fit_file(tmp_path) -> Path:
    p = tmp_path / "morning_strength.fit"
    p.write_bytes(build_fit_bytes())
    return p


@pytest.fixture
def tcx_file(tmp_path) -> Path:
    p = tmp_path / "morning_strength.tcx"
    p.write_text(TCX_SAMPLE, encoding="utf-8")
    return p


# ---------- FIT 解析与落库 ----------


def test_import_fit_persists_activity(session, fit_file):
    """FIT 导入：解析 session 字段并落库 garmin_activity（北京墙钟起止）。"""
    from app.adapters.garmin_adapter import import_fit_file

    result = import_fit_file(session, fit_file)
    row = result["activity"]

    assert row.id is not None
    assert row.activity_id.startswith("file_")
    assert row.activity_type == "strength_training"
    assert row.start_ts == datetime(2026, 8, 5, 18, 0, 0)
    assert row.end_ts == datetime(2026, 8, 5, 19, 0, 0)
    assert row.duration_s == DURATION_S
    assert row.calories == 300
    assert row.avg_hr == 120
    assert row.max_hr == 150
    raw = json.loads(row.raw_json)
    assert raw["source"] == "file_import"
    assert raw["format"] == "fit"


def test_import_tcx_persists_activity(session, tcx_file):
    """TCX 导入：Sport=Strength 映射 strength_training，字段与 FIT 路径一致。"""
    from app.adapters.garmin_adapter import import_fit_file

    result = import_fit_file(session, tcx_file)
    row = result["activity"]

    assert row.activity_type == "strength_training"
    assert row.start_ts == datetime(2026, 8, 5, 18, 0, 0)
    assert row.end_ts == datetime(2026, 8, 5, 19, 0, 0)
    assert row.duration_s == DURATION_S
    assert row.calories == 300
    assert row.avg_hr == 120
    assert row.max_hr == 150
    assert json.loads(row.raw_json)["format"] == "tcx"


# ---------- TCX 小米导出健壮性（V3-11） ----------


def test_parse_tcx_mi_fitness_style(tmp_path):
    """小米 TCX：StartTime 回退 Activity/Id；裸 HeartRateBpm 作 avg_hr；
    无 MaximumHeartRateBpm → max_hr None；DistanceMeters 入 distance_m。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "mi.tcx"
    p.write_text(TCX_MI_SAMPLE, encoding="utf-8")
    parsed = parse_activity_file(p)

    assert parsed["format"] == "tcx"
    assert parsed["activity_type"] == "running"
    assert parsed["start_ts"] == datetime(2026, 8, 16, 15, 31, 3)  # UTC+8
    assert parsed["duration_s"] == 2376
    assert parsed["calories"] == 350
    assert parsed["avg_hr"] == 138
    assert parsed["max_hr"] is None
    assert parsed["distance_m"] == 5022.0


def test_parse_tcx_mi_bare_heart_rate_bpm(tmp_path):
    """V3-11b 真实小米文件结构：Lap 级 <HeartRateBpm> 裸值（无 Average 前缀、
    无 Value 子节点）→ 识别为 avg_hr；max_hr 无数据源维持 None。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "mi_hr.tcx"
    p.write_text(
        TCX_MI_SAMPLE.replace(
            "<AverageHeartRateBpm>138</AverageHeartRateBpm>",
            "<HeartRateBpm>122</HeartRateBpm>",
        ),
        encoding="utf-8",
    )
    parsed = parse_activity_file(p)

    assert parsed["avg_hr"] == 122
    assert parsed["max_hr"] is None


def test_parse_tcx_start_time_fallback_trackpoint(tmp_path):
    """Lap 无 StartTime 且 Activity/Id 非时间戳 → 回退首个 Trackpoint/Time。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "tp.tcx"
    p.write_text(
        TCX_MI_SAMPLE.replace("<Id>2026-08-16T07:31:03.000Z</Id>", "<Id>mi-fitness-export</Id>"),
        encoding="utf-8",
    )
    parsed = parse_activity_file(p)

    assert parsed["start_ts"] == datetime(2026, 8, 16, 15, 31, 3)


def test_parse_tcx_without_any_start_time_rejected(tmp_path):
    """Lap@StartTime / Activity/Id / Trackpoint/Time 三者皆无 → FitImportError（422）。"""
    from app.adapters.garmin_adapter import FitImportError, parse_activity_file

    p = tmp_path / "notime.tcx"
    p.write_text(
        TCX_MI_SAMPLE.replace("<Id>2026-08-16T07:31:03.000Z</Id>", "")
        .replace("<Trackpoint><Time>2026-08-16T07:31:03.000Z</Time></Trackpoint>", "")
        .replace("<Trackpoint><Time>2026-08-16T08:10:39.000Z</Time></Trackpoint>", ""),
        encoding="utf-8",
    )
    with pytest.raises(FitImportError, match="开始时间"):
        parse_activity_file(p)


def test_parse_tcx_distance_meters_summed(tmp_path):
    """多个 Lap 的 DistanceMeters 求和为 distance_m；无则 None。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "laps.tcx"
    p.write_text(
        TCX_MI_SAMPLE.replace(
            "</Lap>",
            "</Lap><Lap><TotalTimeSeconds>600.0</TotalTimeSeconds>"
            "<DistanceMeters>1000.5</DistanceMeters></Lap>",
        ),
        encoding="utf-8",
    )
    parsed = parse_activity_file(p)
    assert parsed["distance_m"] == 6022.5
    assert parsed["duration_s"] == 2976

    q = tmp_path / "nodist.tcx"
    q.write_text(TCX_SAMPLE, encoding="utf-8")
    parsed_q = parse_activity_file(q)
    assert parsed_q["distance_m"] is None


def test_import_is_idempotent(session, fit_file):
    """同一文件重复导入按内容哈希 upsert，不产生重复记录。"""
    from app.adapters.garmin_adapter import import_fit_file

    first = import_fit_file(session, fit_file)["activity"]
    second = import_fit_file(session, fit_file)["activity"]

    assert first.activity_id == second.activity_id
    assert session.query(GarminActivity).count() == 1


def test_import_triggers_rematch(session, fit_file):
    """导入后触发该日重匹配：与同时间训记训练重叠 ≥60% → auto_matched。"""
    from app.adapters.garmin_adapter import import_fit_file

    train = make_xunji_train(session, DAY, localid="x1",
                             start=time(18, 0), end=time(19, 0))
    result = import_fit_file(session, fit_file)

    workout = session.query(Workout).filter(
        Workout.garmin_activity_id == result["activity"].id
    ).one()
    assert workout.match_status == "auto_matched"
    assert workout.xunji_train_id == train.id
    assert result["match"] is not None


def test_import_match_fn_injectable(session, fit_file):
    """match_fn 可注入（测试替换），默认走 matcher.match_day，参数为活动当天。"""
    from app.adapters.garmin_adapter import import_fit_file

    fake_match = Mock(return_value={"workouts": [], "candidates": []})
    import_fit_file(session, fit_file, match_fn=fake_match)
    fake_match.assert_called_once_with(session, DAY)


# ---------- 异常路径 ----------


def test_import_unsupported_extension(session, tmp_path):
    from app.adapters.garmin_adapter import FitImportError, import_fit_file

    p = tmp_path / "track.foo"
    p.write_text("<foo/>", encoding="utf-8")
    with pytest.raises(FitImportError, match="不支持"):
        import_fit_file(session, p)


def test_import_corrupt_fit(session, tmp_path):
    from app.adapters.garmin_adapter import FitImportError, import_fit_file

    p = tmp_path / "broken.fit"
    p.write_bytes(b"\x00\x01garbage-not-a-fit-file")
    with pytest.raises(FitImportError):
        import_fit_file(session, p)


def test_import_missing_file(session, tmp_path):
    from app.adapters.garmin_adapter import FitImportError, import_fit_file

    with pytest.raises(FitImportError):
        import_fit_file(session, tmp_path / "nope.fit")


# ---------- GarminClient 方法委托 ----------


def test_client_method_delegates(session, fit_file):
    """GarminClient.import_fit_file 委托模块级函数，无需登录即可用。"""
    from app.adapters.garmin_adapter import GarminClient

    client = GarminClient(session, email="u@example.com", password="pw", garth=Mock())
    result = client.import_fit_file(str(fit_file))
    assert result["activity"].activity_id.startswith("file_")
