import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from a_stock_lab.features.tail_radar import execution_cli
from a_stock_lab.shared.execution.models import RunStatus

SNAPSHOT_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeResult:
    def __init__(self) -> None:
        self.run = SimpleNamespace(status=RunStatus.SUCCEEDED)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {"disposition": "created", "run": {"run_id": "fixture"}}


def test_cli_executes_only_an_explicit_persisted_snapshot(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeService:
        def execute(self, *, snapshot_id: UUID) -> FakeResult:
            captured["snapshot_id"] = snapshot_id
            return FakeResult()

    monkeypatch.setattr(execution_cli, "get_settings", object)
    monkeypatch.setattr(
        execution_cli,
        "build_tail_radar_screening_service",
        lambda _: FakeService(),
    )

    exit_code = execution_cli.main(["execute", "--snapshot-id", str(SNAPSHOT_ID)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["snapshot_id"] == SNAPSHOT_ID
    assert payload["status"] == "succeeded"


def test_cli_requires_an_explicit_snapshot_id() -> None:
    with pytest.raises(SystemExit) as error:
        execution_cli.main(["execute"])

    assert error.value.code == 2
