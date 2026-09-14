import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, AuthenticationError, OpenAI

from a_stock_lab.core.time import MARKET_TIME_ZONE
from a_stock_lab.features.tail_radar.adapters.openai_research import (
    OpenAIResearchProvider,
    _OpenAIResearchOutput,
    _safe_openai_error_metadata,
)
from a_stock_lab.features.tail_radar.application.research_models import ResearchProviderRequest
from a_stock_lab.features.tail_radar.domain.errors import (
    ResearchProviderAPIError,
    ResearchProviderAuthenticationError,
    ResearchProviderInvalidResponseError,
    ResearchProviderTimeoutError,
    ResearchProviderUnavailableError,
)
from a_stock_lab.features.tail_radar.domain.research import (
    ProviderResearchClaim,
    ProviderSourceAssessment,
    PublicationTimestampStatus,
    ResearchClaimClassification,
    ResearchEvidenceQuality,
    TailRadarResearchProviderOutput,
)

AS_OF = datetime(2026, 8, 28, 14, 35, tzinfo=MARKET_TIME_ZONE)
RETRIEVED = datetime(2026, 8, 30, 10, 0, tzinfo=MARKET_TIME_ZONE)
SOURCE_URL = "https://example.test/announcement"


def test_error_metadata_handles_the_sdk_unwrapped_body() -> None:
    error = {"code": "invalid_json_schema", "param": "text.format.schema", "message": "secret"}
    assert _safe_openai_error_metadata(error) == ("invalid_json_schema", "text.format.schema")
    assert _safe_openai_error_metadata({"error": error}) == (
        "invalid_json_schema",
        "text.format.schema",
    )


def test_real_sdk_serializes_user_key_and_parses_structured_research_without_network() -> None:
    calls: list[dict[str, Any]] = []

    def handle(http_request: httpx.Request) -> httpx.Response:
        assert http_request.headers["authorization"] == "Bearer user-test-key"
        payload = json.loads(http_request.content)
        calls.append(payload)
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        assert payload["store"] is False
        assert "user-test-key" not in http_request.content.decode()
        raw = FakeResponse().model_dump(mode="json")
        raw["output"][0].update(id="search_test")
        raw["output"][1].update(id="msg_test", role="assistant", status="completed")
        raw["output"][1]["content"][0].update(text=provider_output().model_dump_json(), logprobs=[])
        raw["output"][1]["content"][0]["annotations"][0].update(start_index=0, end_index=1)
        return httpx.Response(
            200,
            json={
                **raw,
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "gpt-test",
                "parallel_tool_calls": False,
                "tool_choice": "required",
                "tools": payload["tools"],
            },
        )

    with OpenAI(
        api_key="user-test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        result = OpenAIResearchProvider(
            api_key="user-test-key",
            model="gpt-test",
            timeout_seconds=30,
            max_output_tokens=2000,
            max_web_search_calls=4,
            search_context_size="medium",
            client=client,
            clock=lambda: RETRIEVED,
        ).research(request())
    assert len(calls) == 1
    assert tuple(map(str, result.output.verified_facts[0].source_urls)) == (SOURCE_URL,)
    assert str(result.sources[0].url) == SOURCE_URL


def provider_output() -> TailRadarResearchProviderOutput:
    return TailRadarResearchProviderOutput(
        concise_summary="A verified announcement and one interpretation were found.",
        verified_facts=(
            ProviderResearchClaim(
                claim_id="fact-1",
                statement="The company published an announcement before the cutoff.",
                classification=ResearchClaimClassification.VERIFIED_FACT,
                source_urls=(SOURCE_URL,),
            ),
        ),
        likely_drivers=(),
        company_context=(),
        sector_context=(),
        market_context=(),
        positive_factors=(),
        risk_factors=(),
        unresolved_questions=(),
        evidence_quality=ResearchEvidenceQuality.HIGH,
        confidence=0.8,
        source_assessments=(
            ProviderSourceAssessment(
                url=SOURCE_URL,
                published_at=datetime(2026, 8, 28, 13, 0, tzinfo=MARKET_TIME_ZONE),
                publication_timestamp_status=PublicationTimestampStatus.VERIFIED,
                relationship_claim_ids=("fact-1",),
            ),
        ),
    )


class FakeResponse:
    output_parsed: TailRadarResearchProviderOutput | None = provider_output()
    status = "completed"
    model = "gpt-test-snapshot"
    id = "resp_test"
    usage = SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150)

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {
            "output": [
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "sources": [{"type": "url", "url": SOURCE_URL}],
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": SOURCE_URL,
                                    "title": "Company announcement",
                                }
                            ],
                        }
                    ],
                },
            ]
        }


class MissingStructuredOutputResponse(FakeResponse):
    output_parsed = None


class PartialResponse(FakeResponse):
    status = "incomplete"


class FakeResponses:
    def __init__(self, response: object) -> None:
        self.response = response
        self.kwargs: dict[str, Any] | None = None

    def parse(self, **kwargs: Any) -> object:
        self.kwargs = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeClient:
    def __init__(self, response: object) -> None:
        self.responses = FakeResponses(response)


def request() -> ResearchProviderRequest:
    return ResearchProviderRequest(
        analysis_as_of=AS_OF,
        prompt_sha256="a" * 64,
        instructions="Respect the point-in-time cutoff.",
        input_text='{"symbol":"600000"}',
    )


def test_openai_adapter_uses_responses_web_search_and_returns_real_sources() -> None:
    client = FakeClient(FakeResponse())
    provider = OpenAIResearchProvider(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=30,
        max_output_tokens=2_000,
        max_web_search_calls=4,
        search_context_size="medium",
        client=cast(OpenAI, client),
        clock=lambda: RETRIEVED,
    )

    result = provider.research(request())

    assert client.responses.kwargs is not None
    assert client.responses.kwargs["model"] == "gpt-test"
    assert client.responses.kwargs["tools"] == [
        {"type": "web_search", "search_context_size": "medium"}
    ]
    assert client.responses.kwargs["tool_choice"] == "required"
    assert client.responses.kwargs["include"] == ["web_search_call.action.sources"]
    assert client.responses.kwargs["store"] is False
    assert client.responses.kwargs["text_format"] is _OpenAIResearchOutput
    assert result.actual_model == "gpt-test-snapshot"
    assert result.response_id == "resp_test"
    assert result.sources[0].title == "Company announcement"
    assert result.token_usage.total_tokens == 150


def test_openai_wire_schema_avoids_unsupported_validation_keywords() -> None:
    schema = _OpenAIResearchOutput.model_json_schema()
    unsupported = {
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "maxLength",
        "maximum",
        "minLength",
        "minimum",
        "multipleOf",
        "pattern",
    }

    def find_keywords(value: object) -> set[str]:
        if isinstance(value, dict):
            return (set(value) & unsupported) | {
                keyword for child in value.values() for keyword in find_keywords(child)
            }
        if isinstance(value, list):
            return {keyword for child in value for keyword in find_keywords(child)}
        return set()

    assert find_keywords(schema) == set()


def test_openai_adapter_maps_timeout_without_a_retry_or_live_call() -> None:
    timeout = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    client = FakeClient(timeout)
    provider = OpenAIResearchProvider(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=30,
        max_output_tokens=2_000,
        max_web_search_calls=4,
        search_context_size="low",
        client=cast(OpenAI, client),
    )

    with pytest.raises(ResearchProviderTimeoutError, match="timed out"):
        provider.research(request())


def test_openai_adapter_maps_non_retryable_api_error_without_exposing_response_body() -> None:
    http_request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    error = APIStatusError(
        "upstream detail that must not escape",
        response=httpx.Response(400, request=http_request),
        body={"error": "sensitive upstream detail"},
    )
    provider = OpenAIResearchProvider(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=30,
        max_output_tokens=2_000,
        max_web_search_calls=4,
        search_context_size="low",
        client=cast(OpenAI, FakeClient(error)),
    )

    with pytest.raises(ResearchProviderAPIError, match="rejected the request") as captured:
        provider.research(request())

    assert "sensitive" not in str(captured.value)


def test_openai_adapter_maps_rejected_user_key_without_exposing_upstream_detail() -> None:
    http_request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    error = AuthenticationError(
        "secret upstream authentication detail",
        response=httpx.Response(401, request=http_request),
        body={"error": "secret upstream authentication detail"},
    )
    provider = OpenAIResearchProvider(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=30,
        max_output_tokens=2_000,
        max_web_search_calls=4,
        search_context_size="low",
        client=cast(OpenAI, FakeClient(error)),
    )

    with pytest.raises(ResearchProviderAuthenticationError, match="key was rejected") as captured:
        provider.research(request())

    assert "secret" not in str(captured.value)


def test_openai_adapter_maps_server_and_malformed_response_failures() -> None:
    http_request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    server_error = APIStatusError(
        "server detail",
        response=httpx.Response(503, request=http_request),
        body={"error": "upstream detail"},
    )
    unavailable_provider = OpenAIResearchProvider(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=30,
        max_output_tokens=2_000,
        max_web_search_calls=4,
        search_context_size="low",
        client=cast(OpenAI, FakeClient(server_error)),
    )
    malformed_provider = OpenAIResearchProvider(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=30,
        max_output_tokens=2_000,
        max_web_search_calls=4,
        search_context_size="low",
        client=cast(OpenAI, FakeClient(MissingStructuredOutputResponse())),
    )

    with pytest.raises(ResearchProviderUnavailableError, match="unavailable"):
        unavailable_provider.research(request())
    with pytest.raises(ResearchProviderInvalidResponseError, match="no structured output"):
        malformed_provider.research(request())


def test_openai_adapter_preserves_a_valid_partial_response_warning() -> None:
    provider = OpenAIResearchProvider(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=30,
        max_output_tokens=2_000,
        max_web_search_calls=4,
        search_context_size="medium",
        client=cast(OpenAI, FakeClient(PartialResponse())),
        clock=lambda: RETRIEVED,
    )

    result = provider.research(request())

    assert "response_status:incomplete" in result.warnings
