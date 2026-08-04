"""手动验证脚本（不入库版本控制测试套件）：真实凭据拉近 3 天佳明数据。

运行：cd backend; $env:GARMIN_EMAIL=...; $env:GARMIN_PASSWORD=...; python -m tests.manual_garmin_check
用完可删。仅用于 M3 真机冒烟。
"""
import json
import os
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base


def main():
    from app.adapters.garmin_adapter import GarminClient

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    client = GarminClient(session)
    today = date.today()
    for i in range(3):
        datestr = (today - timedelta(days=i)).isoformat()
        acts = client.sync_activities(datestr)
        daily = client.sync_daily(datestr)
        print(f"== {datestr} ==")
        for a in acts:
            print(f"  活动: {a.activity_id} {a.name} type={a.activity_type} "
                  f"start={a.start_ts} dur={a.duration_s}s cal={a.calories} hr={a.avg_hr}/{a.max_hr}")
        print(f"  健康: steps={daily.steps} rhr={daily.resting_hr} stress={daily.stress_avg} "
              f"bb={daily.body_battery_high}/{daily.body_battery_low} hrv={daily.hrv_status} "
              f"sleep={'有' if daily.sleep_json else '无'}")
        if daily.sleep_json:
            s = json.loads(daily.sleep_json)
            dto = (s or {}).get("dailySleepDTO") or {}
            print(f"        睡眠时长={dto.get('sleepTimeSeconds')}s")


if __name__ == "__main__":
    assert os.getenv("GARMIN_EMAIL") and os.getenv("GARMIN_PASSWORD"), "缺少佳明凭据环境变量"
    main()
