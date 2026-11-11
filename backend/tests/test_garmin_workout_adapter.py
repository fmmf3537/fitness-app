"""Garmin Workout 适配器测试：全部使用 fake client，零网络外呼。"""
from datetime import date

import pytest

from app.adapters.garmin_workout_adapter import (
    GarminWorkoutAdapter,
    GarminWorkoutAdapterError,
)


class HttpFailure(RuntimeError):
    def __init__(self, status, message="raw response may contain secret-token"):
        super().__init__(message)
        self.response = type("Response", (), {"status_code": status})()


class FakeClient:
    def __init__(self):
        self.calls = []
        self.upload_error = None
        self.get_errors = []
        self.update_errors = []
        self.login_calls = []
        self.pages = []

    def login(self, tokenstore=None):
        self.login_calls.append(tokenstore)
        return None, None

    def upload_workout(self, payload):
        self.calls.append(("upload", payload))
        if self.upload_error:
            raise self.upload_error
        return {"workoutId": 123}

    def get_workout_by_id(self, workout_id):
        self.calls.append(("get", workout_id))
        if self.get_errors:
            raise self.get_errors.pop(0)
        return {"workoutId": workout_id}

    def update_workout(self, workout_id, payload):
        self.calls.append(("update", workout_id, payload))
        if self.update_errors:
            raise self.update_errors.pop(0)
        return {"workoutId": workout_id}

    def schedule_workout(self, workout_id, day):
        self.calls.append(("schedule", workout_id, day))
        return {"workoutScheduleId": 456}

    def get_scheduled_workout_by_id(self, schedule_id):
        return {"workoutScheduleId": schedule_id}

    def get_scheduled_workouts_by_period(self, start, end):
        self.calls.append(("period", start, end))
        return [
            {"workoutScheduleId": 1, "calendarDate": start, "workout": {"workoutId": 123}},
            {"workoutScheduleId": 2, "calendarDate": start, "workout": {"workoutId": 999}},
            {"workoutScheduleId": 3, "calendarDate": "2026-11-13", "workout": {"workoutId": 123}},
        ]

    def get_workouts(self, start=0, limit=100):
        self.calls.append(("list", start, limit))
        return self.pages[start // limit]


def test_login_uses_cn_tokenstore_and_disables_library_retries(tmp_path):
    captured = {}

    class LoginClient(FakeClient):
        def __init__(self, email, password, **kwargs):
            super().__init__()
            captured.update(email=email, password=password, **kwargs)

        def login(self, tokenstore=None):
            captured["tokenstore"] = tokenstore
            return None, None

    tokenstore = tmp_path / "tokens" / "garmin.json"
    adapter = GarminWorkoutAdapter(
        email="user@example.com",
        password="secret",
        tokenstore=tokenstore,
        client_factory=LoginClient,
    )

    assert isinstance(adapter, GarminWorkoutAdapter)
    assert captured["is_cn"] is True
    assert captured["return_on_mfa"] is False
    assert captured["retry_attempts"] == 0
    assert captured["tokenstore"] == str(tokenstore)
    assert callable(captured["prompt_mfa"])


def test_mfa_stops_instead_of_prompting_or_retrying():
    class MFAClient(FakeClient):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.kwargs = kwargs

        def login(self, tokenstore=None):
            self.kwargs["prompt_mfa"]()

    with pytest.raises(GarminWorkoutAdapterError) as caught:
        GarminWorkoutAdapter(client_factory=MFAClient)
    assert caught.value.error_code == "GARMIN_MFA_REQUIRED"


def test_create_post_never_retries_and_error_is_sanitized():
    client = FakeClient()
    client.upload_error = HttpFailure(429)
    adapter = GarminWorkoutAdapter(client=client, sleep=lambda _: None)

    with pytest.raises(GarminWorkoutAdapterError) as caught:
        adapter.create_workout({"workoutName": "test"})

    assert caught.value.error_code == "GARMIN_RATE_LIMITED"
    assert "secret-token" not in caught.value.public_message
    assert len([call for call in client.calls if call[0] == "upload"]) == 1


def test_get_retries_rate_limit_once_and_update_reauthenticates_once():
    client = FakeClient()
    client.get_errors = [HttpFailure(429)]
    client.update_errors = [HttpFailure(401)]
    sleeps = []
    adapter = GarminWorkoutAdapter(client=client, sleep=sleeps.append)

    assert adapter.get_workout("123")["workoutId"] == "123"
    adapter.update_workout("123", {"workoutName": "updated"})

    assert len([call for call in client.calls if call[0] == "get"]) == 2
    assert len([call for call in client.calls if call[0] == "update"]) == 2
    assert len(client.login_calls) == 1
    assert 1.0 in sleeps


def test_throttle_applies_half_second_between_requests():
    client = FakeClient()
    now = [10.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    adapter = GarminWorkoutAdapter(
        client=client, sleep=sleep, monotonic=lambda: now[0]
    )
    adapter.get_workout("123")
    adapter.get_workout("123")
    assert sleeps == [0.5]


def test_source_key_reconciliation_paginates_and_matches_exactly():
    client = FakeClient()
    expected = "xunji-plan:v1:p:2026-11-12"
    client.pages = [
        [{"workoutId": index, "description": "unrelated"} for index in range(100)],
        [
            {"workoutId": 100, "description": f"source_key={expected}; managed_by=fitness-app"},
            {"workoutId": 101, "description": f"source_key={expected}-other"},
            {"workoutId": 102, "description": f"prefix source_key={expected}"},
        ],
    ]
    adapter = GarminWorkoutAdapter(client=client, sleep=lambda _: None)

    matches = adapter.find_workouts_by_source_key(expected)

    assert [row["workoutId"] for row in matches] == [100]
    assert [call[:3] for call in client.calls if call[0] == "list"] == [
        ("list", 0, 100), ("list", 100, 100)
    ]


def test_schedule_and_period_reconciliation_use_stable_ids():
    client = FakeClient()
    adapter = GarminWorkoutAdapter(client=client, sleep=lambda _: None)

    schedule_id = adapter.schedule_workout("123", date(2026, 11, 12))
    matches = adapter.find_schedules("123", "2026-11-12")

    assert schedule_id == "456"
    assert [row["workoutScheduleId"] for row in matches] == [1]
    assert adapter.get_schedule(schedule_id)["workoutScheduleId"] == "456"


def test_missing_response_id_is_explicit_error():
    client = FakeClient()
    client.upload_workout = lambda payload: {}
    adapter = GarminWorkoutAdapter(client=client, sleep=lambda _: None)
    with pytest.raises(GarminWorkoutAdapterError) as caught:
        adapter.create_workout({})
    assert caught.value.error_code == "GARMIN_INVALID_RESPONSE"


def test_reschedule_uses_existing_library_method_and_stable_schedule_id():
    client = FakeClient()
    calls = []
    client.reschedule_workout = lambda schedule_id, day: calls.append((schedule_id, day))
    adapter = GarminWorkoutAdapter(client=client, sleep=lambda _: None)

    adapter.reschedule_schedule("456", date(2026, 11, 13))

    assert calls == [("456", "2026-11-13")]
    assert not [call for call in client.calls if call[0] in {"upload", "schedule"}]
