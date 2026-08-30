from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
    RateLimitError,
)
from openai.types.responses import WebSearchToolParam
from pydantic import ValidationError

from a_stock_lab.core.time import as_market_timezone, now_in_market_timezone
from a_stock_lab.features.tail_radar.application.research_models import (
    ResearchProviderRequest,
    ResearchProviderResult,
    ResearchProviderSource,
    ResearchTokenUsage,
)
from a_stock_lab.features.tail_radar.domain.errors import (
    ResearchProviderAPIError,
    ResearchProviderInvalidResponseError,
    ResearchProviderRateLimitError,
    ResearchProviderTimeoutError,
    ResearchProviderUnavailableError,
)
from a_stock_lab.features.tail_radar.domain.research import (
    TailRadarResearchProviderOutput,
    canonical_source_url,
)

OPENAI_RESEARCH_PROVIDER_ID = "openai"


class OpenAIResearchProvider:
    """Backend-only OpenAI Responses API adapter with hosted web search."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        max_web_search_calls: int,
        search_context_size: Literal["low", "medium", "high"],
        client: OpenAI | None = None,
        clock: Callable[[], datetime] = now_in_market_timezone,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._max_web_search_calls = max_web_search_calls
        self._search_context_size = search_context_size
        self._client = client or OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._clock = clock

    @property
    def provider_id(self) -> str:
        return OPENAI_RESEARCH_PROVIDER_ID

    @property
    def model_id(self) -> str:
        return self._model

    def research(self, request: ResearchProviderRequest) -> ResearchProviderResult:
        tool = WebSearchToolParam(
            type="web_search",
            search_context_size=self._search_context_size,
        )
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=request.instructions,
                input=request.input_text,
                tools=[tool],
                tool_choice="required",
                include=["web_search_call.action.sources"],
                max_output_tokens=self._max_output_tokens,
                max_tool_calls=self._max_web_search_calls,
                parallel_tool_calls=False,
                prompt_cache_key=request.prompt_version,
                store=False,
                text_format=TailRadarResearchProviderOutput,
                timeout=self._timeout_seconds,
            )
        except RateLimitError as exc:
            raise ResearchProviderRateLimitError("OpenAI research rate limit was reached") from exc
        except APITimeoutError as exc:
            raise ResearchProviderTimeoutError("OpenAI research request timed out") from exc
        except APIConnectionError as exc:
            raise ResearchProviderUnavailableError(
                "OpenAI research service is unavailable"
            ) from exc
        except APIStatusError as exc:
            if exc.status_code == 408:
                raise ResearchProviderTimeoutError("OpenAI research request timed out") from exc
            if exc.status_code == 429:
                raise ResearchProviderRateLimitError(
                    "OpenAI research rate limit was reached"
                ) from exc
            if exc.status_code >= 500:
                raise ResearchProviderUnavailableError(
                    "OpenAI research API is unavailable"
                ) from exc
            raise ResearchProviderAPIError("OpenAI research API rejected the request") from exc
        except (
            APIResponseValidationError,
            ContentFilterFinishReasonError,
            LengthFinishReasonError,
        ) as exc:
            raise ResearchProviderInvalidResponseError(
                "OpenAI research response could not be completed safely"
            ) from exc
        except (ValidationError, ValueError, TypeError) as exc:
            raise ResearchProviderInvalidResponseError(
                "OpenAI research response could not be validated"
            ) from exc

        output = response.output_parsed
        if output is None:
            raise ResearchProviderInvalidResponseError(
                "OpenAI research response contained no structured output"
            )
        retrieved_at = as_market_timezone(self._clock())
        raw_response = response.model_dump(mode="json")
        sources, source_warnings = _extract_sources(raw_response, retrieved_at=retrieved_at)
        warnings = list(source_warnings)
        if response.status != "completed":
            warnings.append(f"response_status:{response.status or 'unknown'}")
        warnings.extend(_web_search_status_warnings(raw_response))
        usage = response.usage
        token_usage = ResearchTokenUsage(
            input_tokens=0 if usage is None else usage.input_tokens,
            output_tokens=0 if usage is None else usage.output_tokens,
            total_tokens=0 if usage is None else usage.total_tokens,
        )
        return ResearchProviderResult(
            provider=self.provider_id,
            requested_model=self._model,
            actual_model=response.model,
            response_id=response.id,
            retrieved_at=retrieved_at,
            output=output,
            sources=sources,
            token_usage=token_usage,
            warnings=tuple(dict.fromkeys(warnings)),
            provider_metadata={
                "api": "responses",
                "web_search_tool": "web_search",
                "search_context_size": self._search_context_size,
                "store": False,
            },
        )


def _extract_sources(
    raw_response: dict[str, Any], *, retrieved_at: datetime
) -> tuple[tuple[ResearchProviderSource, ...], tuple[str, ...]]:
    observations: dict[str, dict[str, str | None]] = {}
    warnings: list[str] = []
    output = raw_response.get("output")
    if not isinstance(output, list):
        return (), ("missing_response_output",)
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            action = item.get("action")
            if isinstance(action, dict):
                raw_sources = action.get("sources")
                if isinstance(raw_sources, list):
                    for source in raw_sources:
                        if isinstance(source, dict):
                            _record_source(observations, source.get("url"), title=None)
        if item.get("type") == "message":
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                annotations = part.get("annotations")
                if not isinstance(annotations, list):
                    continue
                for annotation in annotations:
                    if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
                        _record_source(
                            observations,
                            annotation.get("url"),
                            title=annotation.get("title"),
                        )
    sources: list[ResearchProviderSource] = []
    for observation in observations.values():
        try:
            sources.append(
                ResearchProviderSource(
                    url=observation["url"],
                    title=observation["title"],
                    retrieved_at=retrieved_at,
                )
            )
        except ValidationError:
            warnings.append("invalid_source_url_excluded")
    return tuple(sources), tuple(dict.fromkeys(warnings))


def _record_source(
    observations: dict[str, dict[str, str | None]],
    raw_url: object,
    *,
    title: object,
) -> None:
    if not isinstance(raw_url, str) or not raw_url.strip():
        return
    try:
        key = canonical_source_url(raw_url)
    except ValueError:
        return
    normalized_title = title.strip() if isinstance(title, str) and title.strip() else None
    existing = observations.setdefault(key, {"url": raw_url, "title": None})
    if normalized_title is not None:
        existing["title"] = normalized_title


def _web_search_status_warnings(raw_response: dict[str, Any]) -> tuple[str, ...]:
    output = raw_response.get("output")
    if not isinstance(output, list):
        return ()
    warnings: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        status = item.get("status")
        if status != "completed":
            warnings.append(f"web_search_status:{status or 'unknown'}")
    return tuple(dict.fromkeys(warnings))
