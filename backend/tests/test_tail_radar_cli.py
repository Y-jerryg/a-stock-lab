import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar import execution_cli
from a_stock_lab.shared.execution.models import RunStatus

SNAPSHOT_ID = UUID("11111111-1111-1111-1111-111111111111")
CANDIDATE_ID = UUID("22222222-2222-2222-2222-222222222222")
WORKFLOW_ID = UUID("33333333-3333-4333-8333-333333333333")


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


def test_cli_runs_intraday_analysis_only_with_explicit_candidate_and_as_of(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeAnalysisResult:
        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            return {"disposition": "created", "analysis": {"analysis_id": "fixture"}}

    class FakeIntradayService:
        def execute(self, *, candidate_id: UUID, analysis_as_of: datetime) -> FakeAnalysisResult:
            captured["candidate_id"] = candidate_id
            captured["analysis_as_of"] = analysis_as_of
            return FakeAnalysisResult()

    monkeypatch.setattr(execution_cli, "get_settings", object)
    monkeypatch.setattr(
        execution_cli,
        "build_tail_radar_intraday_analysis_service",
        lambda _: FakeIntradayService(),
    )

    exit_code = execution_cli.main(
        [
            "analyze-intraday",
            "--candidate-id",
            str(CANDIDATE_ID),
            "--analysis-as-of",
            "2026-08-28T14:35:00+08:00",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["candidate_id"] == CANDIDATE_ID
    assert captured["analysis_as_of"] == datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE)
    assert payload["status"] == "success"


def test_cli_rejects_naive_intraday_analysis_timestamp() -> None:
    with pytest.raises(SystemExit) as error:
        execution_cli.main(
            [
                "analyze-intraday",
                "--candidate-id",
                str(CANDIDATE_ID),
                "--analysis-as-of",
                "2026-08-28T14:35:00",
            ]
        )

    assert error.value.code == 2


def test_cli_runs_paid_research_only_with_explicit_candidate_as_of_and_force(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResearchResult:
        research = SimpleNamespace(status=SimpleNamespace(value="succeeded"))

        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            return {
                "disposition": "forced_created",
                "research": {"status": "succeeded"},
            }

    class FakeResearchService:
        def execute(
            self,
            *,
            candidate_id: UUID,
            analysis_as_of: datetime,
            force: bool,
        ) -> FakeResearchResult:
            captured.update(
                candidate_id=candidate_id,
                analysis_as_of=analysis_as_of,
                force=force,
            )
            return FakeResearchResult()

    monkeypatch.setattr(execution_cli, "get_settings", object)
    monkeypatch.setattr(
        execution_cli,
        "build_tail_radar_research_service",
        lambda _: FakeResearchService(),
    )

    exit_code = execution_cli.main(
        [
            "research",
            "--candidate-id",
            str(CANDIDATE_ID),
            "--analysis-as-of",
            "2026-08-28T14:35:00+08:00",
            "--force",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured == {
        "candidate_id": CANDIDATE_ID,
        "analysis_as_of": datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE),
        "force": True,
    }
    assert payload["research"]["status"] == "succeeded"


def test_cli_executes_and_resumes_complete_workflow_explicitly(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    class FakeWorkflowResult:
        workflow = SimpleNamespace(lifecycle=SimpleNamespace(value="succeeded"))

        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            return {"disposition": "created", "workflow": {"lifecycle": "succeeded"}}

    class FakeApplicationService:
        def execute(
            self,
            *,
            intended_snapshot_time: datetime,
            analysis_as_of: datetime | None,
        ) -> FakeWorkflowResult:
            captured.append(
                {
                    "operation": "execute",
                    "intended": intended_snapshot_time,
                    "analysis_as_of": analysis_as_of,
                }
            )
            return FakeWorkflowResult()

        def resume(self, *, workflow_run_id: UUID) -> FakeWorkflowResult:
            captured.append(
                {
                    "operation": "resume",
                    "workflow_run_id": workflow_run_id,
                }
            )
            return FakeWorkflowResult()

    monkeypatch.setattr(execution_cli, "get_settings", object)
    monkeypatch.setattr(
        execution_cli,
        "build_tail_radar_application_service",
        lambda _: FakeApplicationService(),
    )

    execute_code = execution_cli.main(
        [
            "workflow",
            "--intended-snapshot-time",
            "2026-08-28T14:30:00+08:00",
            "--analysis-as-of",
            "2026-08-28T14:35:00+08:00",
        ]
    )
    execute_payload = json.loads(capsys.readouterr().out)
    resume_code = execution_cli.main(
        [
            "resume",
            "--workflow-run-id",
            str(WORKFLOW_ID),
        ]
    )
    resume_payload = json.loads(capsys.readouterr().out)

    assert execute_code == 0
    assert resume_code == 0
    assert execute_payload["workflow"]["lifecycle"] == "succeeded"
    assert resume_payload["workflow"]["lifecycle"] == "succeeded"
    assert captured[0]["intended"] == datetime(2026, 8, 28, 14, 30, tzinfo=MARKET_TIME_ZONE)
    assert captured[1] == {
        "operation": "resume",
        "workflow_run_id": WORKFLOW_ID,
    }
