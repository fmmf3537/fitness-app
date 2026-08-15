"""V3-7 GPX/KML 文件导入测试（复用 FIT/TCX 导入管线，PRD §6.2 降级通道扩展）。

最小样本全部内联构造，stdlib xml.etree.ElementTree 解析（零新依赖）：
- GPX：1.1 命名空间带 gpxtpx 心率 / 无心率 / 1.0 命名空间；
- KML：gx:Track 正常 / LineString 无时间 → 422；
- 损坏 XML / 带 DOCTYPE 外部实体样本 → FitImportError。
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.models import GarminActivity

# ---------- 样本文件（内联最小样本） ----------

# GPX 1.1：两点轨迹，北京 18:00-18:15（UTC 10:00-10:15），带 gpxtpx 心率 120/150
GPX_WITH_HR = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/gpx/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <trk>
    <name>晨跑</name>
    <type>running</type>
    <trkseg>
      <trkpt lat="39.9042" lon="116.4074">
        <ele>50.0</ele>
        <time>2026-08-05T10:00:00Z</time>
        <extensions>
          <gpxtpx:TrackPointExtension>
            <gpxtpx:hr>120</gpxtpx:hr>
          </gpxtpx:TrackPointExtension>
        </extensions>
      </trkpt>
      <trkpt lat="39.9052" lon="116.4084">
        <ele>52.0</ele>
        <time>2026-08-05T10:15:00Z</time>
        <extensions>
          <gpxtpx:TrackPointExtension>
            <gpxtpx:hr>150</gpxtpx:hr>
          </gpxtpx:TrackPointExtension>
        </extensions>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""

# GPX 1.1 无心率扩展
GPX_NO_HR = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/gpx/1/1">
  <trk>
    <name>徒步</name>
    <type>hiking</type>
    <trkseg>
      <trkpt lat="39.9042" lon="116.4074">
        <time>2026-08-05T10:00:00Z</time>
      </trkpt>
      <trkpt lat="39.9052" lon="116.4084">
        <time>2026-08-05T10:15:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""

# GPX 1.0 命名空间，无 type/name → activity_type 默认 'other'
GPX_V10 = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.0" creator="test" xmlns="http://www.topografix.com/gpx/1/0">
  <trk>
    <trkseg>
      <trkpt lat="39.9042" lon="116.4074">
        <time>2026-08-05T10:00:00Z</time>
      </trkpt>
      <trkpt lat="39.9052" lon="116.4084">
        <time>2026-08-05T10:15:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""

# KML 2.2 + gx:Track：北京 18:00-18:30（UTC 10:00-10:30）
KML_TRACK = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <Placemark>
      <name>骑行</name>
      <gx:Track>
        <when>2026-08-05T10:00:00Z</when>
        <when>2026-08-05T10:30:00Z</when>
        <gx:coord>116.4074 39.9042 50</gx:coord>
        <gx:coord>116.4174 39.9042 50</gx:coord>
      </gx:Track>
    </Placemark>
  </Document>
</kml>
"""

# KML 仅 LineString（无时间戳）→ 无法确定运动日期
KML_LINESTRING = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>轨迹</name>
      <LineString>
        <coordinates>116.4074,39.9042,50 116.4174,39.9042,50</coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
"""

# 带 DOCTYPE 外部实体的恶意样本：stdlib ET 不解析外部实体，必须报错且不泄露内容
GPX_XXE = """<?xml version="1.0"?>
<!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file:///etc/hostname-XXE-SENTINEL">]>
<gpx xmlns="http://www.topografix.com/gpx/1/1">
  <trk>
    <name>&xxe;</name>
    <trkseg>
      <trkpt lat="39.9042" lon="116.4074">
        <time>2026-08-05T10:00:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""


@pytest.fixture
def gpx_file(tmp_path) -> Path:
    p = tmp_path / "morning_run.gpx"
    p.write_text(GPX_WITH_HR, encoding="utf-8")
    return p


# ---------- GPX 解析 ----------


def test_parse_gpx_with_hr(gpx_file):
    """GPX 1.1 + gpxtpx 心率：归一化字段齐全，距离用 haversine 累加（容忍 5%）。"""
    from app.adapters.garmin_adapter import parse_activity_file

    parsed = parse_activity_file(gpx_file)

    assert parsed["format"] == "gpx"
    assert parsed["activity_name"] == "晨跑"
    assert parsed["activity_type"] == "running"
    assert parsed["start_ts"] == datetime(2026, 8, 5, 18, 0, 0)
    assert parsed["duration_s"] == 900
    assert parsed["avg_hr"] == 135
    assert parsed["max_hr"] == 150
    assert parsed["calories"] is None
    # (39.9042,116.4074) → (39.9052,116.4084) haversine ≈ 140.1m
    assert abs(parsed["distance_m"] - 140.1) / 140.1 < 0.05


def test_parse_gpx_without_hr(tmp_path):
    """GPX 无心率扩展：avg_hr/max_hr 为 None。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "hike.gpx"
    p.write_text(GPX_NO_HR, encoding="utf-8")
    parsed = parse_activity_file(p)

    assert parsed["activity_type"] == "hiking"
    assert parsed["avg_hr"] is None
    assert parsed["max_hr"] is None
    assert parsed["duration_s"] == 900
    assert parsed["distance_m"] is not None


def test_parse_gpx_v10_namespace(tmp_path):
    """GPX 1.0 命名空间兼容；无 type/name 时 activity_type 默认 'other'。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "old.gpx"
    p.write_text(GPX_V10, encoding="utf-8")
    parsed = parse_activity_file(p)

    assert parsed["format"] == "gpx"
    assert parsed["activity_type"] == "other"
    assert parsed["activity_name"] is None
    assert parsed["start_ts"] == datetime(2026, 8, 5, 18, 0, 0)
    assert parsed["duration_s"] == 900


def test_parse_gpx_normalized_keys(tmp_path):
    """归一化 dict 与 TCX 路径同构：缺失字段一律给 None。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "old.gpx"
    p.write_text(GPX_V10, encoding="utf-8")
    parsed = parse_activity_file(p)

    for key in ("activity_name", "activity_type", "start_ts", "duration_s",
                "distance_m", "calories", "avg_hr", "max_hr"):
        assert key in parsed


# ---------- KML 解析 ----------


def test_parse_kml_gx_track(tmp_path):
    """KML gx:Track：when/gx:coord 一一对应；心率/热量 None，类型默认 'other'。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "ride.kml"
    p.write_text(KML_TRACK, encoding="utf-8")
    parsed = parse_activity_file(p)

    assert parsed["format"] == "kml"
    assert parsed["activity_name"] == "骑行"
    assert parsed["activity_type"] == "other"
    assert parsed["start_ts"] == datetime(2026, 8, 5, 18, 0, 0)
    assert parsed["duration_s"] == 1800
    assert parsed["avg_hr"] is None
    assert parsed["max_hr"] is None
    assert parsed["calories"] is None
    # (39.9042,116.4074) → (39.9042,116.4174) haversine ≈ 853.0m
    assert abs(parsed["distance_m"] - 853.0) / 853.0 < 0.05


def test_parse_kml_linestring_without_time_rejected(tmp_path):
    """KML 仅 LineString（无时间戳）→ FitImportError，提示导出含 gx:Track 的版本。"""
    from app.adapters.garmin_adapter import FitImportError, parse_activity_file

    p = tmp_path / "plain.kml"
    p.write_text(KML_LINESTRING, encoding="utf-8")
    with pytest.raises(FitImportError, match="缺少时间信息"):
        parse_activity_file(p)


# ---------- 安全与健壮 ----------


def test_parse_corrupt_xml_rejected(session, tmp_path):
    """损坏 XML → FitImportError（422 友好文案）。"""
    from app.adapters.garmin_adapter import FitImportError, import_fit_file

    p = tmp_path / "broken.gpx"
    p.write_text("<gpx><unclosed", encoding="utf-8")
    with pytest.raises(FitImportError, match="解析失败"):
        import_fit_file(session, p)

    q = tmp_path / "broken.kml"
    q.write_text("<kml><unclosed", encoding="utf-8")
    with pytest.raises(FitImportError, match="解析失败"):
        import_fit_file(session, q)


def test_parse_xxe_not_executed(session, tmp_path):
    """带 DOCTYPE 外部实体的样本：拒绝解析，外部引用不执行、内容不泄露。"""
    from app.adapters.garmin_adapter import FitImportError, import_fit_file

    p = tmp_path / "evil.gpx"
    p.write_text(GPX_XXE, encoding="utf-8")
    with pytest.raises(FitImportError) as exc_info:
        import_fit_file(session, p)
    assert "XXE-SENTINEL" not in str(exc_info.value)


# ---------- 复用 import_fit_file 既有链路 ----------


def test_import_gpx_persists_activity(session, gpx_file):
    """GPX 走既有落库链路：字段同构、activity_name 作活动名、match_fn 被调用。"""
    from app.adapters.garmin_adapter import import_fit_file

    fake_match = Mock(return_value={"workouts": [], "candidates": []})
    result = import_fit_file(session, gpx_file, match_fn=fake_match)
    row = result["activity"]

    assert row.id is not None
    assert row.activity_id.startswith("file_")
    assert row.name == "晨跑"
    assert row.activity_type == "running"
    assert row.start_ts == datetime(2026, 8, 5, 18, 0, 0)
    assert row.end_ts == datetime(2026, 8, 5, 18, 15, 0)
    assert row.duration_s == 900
    assert row.avg_hr == 135
    assert row.max_hr == 150
    raw = json.loads(row.raw_json)
    assert raw["format"] == "gpx"
    assert raw["parsed"]["distance_m"] is not None
    fake_match.assert_called_once_with(session, row.start_ts.date())


def test_import_gpx_idempotent(session, gpx_file):
    """同一 GPX 文件重复导入按内容哈希去重，不新建行。"""
    from app.adapters.garmin_adapter import import_fit_file

    fake_match = Mock(return_value={"workouts": [], "candidates": []})
    first = import_fit_file(session, gpx_file, match_fn=fake_match)["activity"]
    second = import_fit_file(session, gpx_file, match_fn=fake_match)["activity"]

    assert first.activity_id == second.activity_id
    assert session.query(GarminActivity).count() == 1


# ---------- 防御性分支补强 ----------


def test_parse_gpx_without_trk_rejected(tmp_path):
    """GPX 无 trk 轨迹 → FitImportError。"""
    from app.adapters.garmin_adapter import FitImportError, parse_activity_file

    p = tmp_path / "empty.gpx"
    p.write_text(
        '<gpx xmlns="http://www.topografix.com/gpx/1/1"><wpt lat="1" lon="1"/></gpx>',
        encoding="utf-8",
    )
    with pytest.raises(FitImportError, match="不含轨迹"):
        parse_activity_file(p)


def test_parse_gpx_trkpt_without_time_rejected(tmp_path):
    """GPX 轨迹点全部无 time → FitImportError（无法确定运动时间）。"""
    from app.adapters.garmin_adapter import FitImportError, parse_activity_file

    p = tmp_path / "notime.gpx"
    p.write_text(
        '<gpx xmlns="http://www.topografix.com/gpx/1/1"><trk><trkseg>'
        '<trkpt lat="39.9042" lon="116.4074"/>'
        '<trkpt lat="39.9052" lon="116.4084"/>'
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    with pytest.raises(FitImportError, match="时间"):
        parse_activity_file(p)


def test_parse_gpx_invalid_hr_ignored(tmp_path):
    """GPX 心率字段非数值时按无心率处理，不报错。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "badhr.gpx"
    p.write_text(
        '<gpx xmlns="http://www.topografix.com/gpx/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
        "<trk><trkseg>"
        '<trkpt lat="39.9042" lon="116.4074"><time>2026-08-05T10:00:00Z</time>'
        "<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>abc</gpxtpx:hr>"
        "</gpxtpx:TrackPointExtension></extensions></trkpt>"
        '<trkpt lat="39.9052" lon="116.4084"><time>2026-08-05T10:15:00Z</time></trkpt>'
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    parsed = parse_activity_file(p)
    assert parsed["avg_hr"] is None
    assert parsed["max_hr"] is None


def test_parse_kml_without_any_track_rejected(tmp_path):
    """KML 无 gx:Track 也无 LineString → FitImportError。"""
    from app.adapters.garmin_adapter import FitImportError, parse_activity_file

    p = tmp_path / "empty.kml"
    p.write_text(
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>',
        encoding="utf-8",
    )
    with pytest.raises(FitImportError, match="不含轨迹"):
        parse_activity_file(p)


def test_parse_kml_invalid_coord_skipped(tmp_path):
    """KML gx:coord 非数值行跳过，不报错。"""
    from app.adapters.garmin_adapter import parse_activity_file

    p = tmp_path / "badcoord.kml"
    p.write_text(
        '<kml xmlns="http://www.opengis.net/kml/2.2" '
        'xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><Placemark>'
        "<gx:Track>"
        "<when>2026-08-05T10:00:00Z</when><when>2026-08-05T10:30:00Z</when>"
        "<gx:coord>garbage</gx:coord>"
        "<gx:coord>116.4074 39.9042 50</gx:coord>"
        "<gx:coord>116.4174 39.9042 50</gx:coord>"
        "</gx:Track></Placemark></Document></kml>",
        encoding="utf-8",
    )
    parsed = parse_activity_file(p)
    assert parsed["duration_s"] == 1800
    assert abs(parsed["distance_m"] - 853.0) / 853.0 < 0.05
