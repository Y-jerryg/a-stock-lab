import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.shared.execution.models import RunStatus
from a_stock_lab.shared.market_data import execution_cli


class FakeResult:
    def __init__(self) -> None:
        self.run = SimpleNamespace(status=RunStatus.SUCCEEDED)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {"disposition": "created", "run": {"run_id": "fixture"}, "manifest": {}}


def test_execute_at_requires_and_normalizes_an_aware_timestamp(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeEngine:
        def execute(self, *, intended_snapshot_time: datetime, force: bool) -> FakeResult:
            captured["intended_snapshot_time"] = intended_snapshot_time
            captured["force"] = force
            return FakeResult()

    monkeypatch.setattr(execution_cli, "get_settings", object)
    monkeypatch.setattr(execution_cli, "build_snapshot_execution_engine", lambda _: FakeEngine())

    exit_code = execution_cli.main(["execute-at", "2026-08-28T06:30:00Z", "--force"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "succeeded"
    assert captured["intended_snapshot_time"] == datetime(
        2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE
    )
    assert captured["force"] is True


def test_execute_at_rejects_a_timezone_naive_timestamp() -> None:
    with pytest.raises(SystemExit) as error:
        execution_cli.main(["execute-at", "2026-08-28T14:30:00"])

    assert error.value.code == 2
