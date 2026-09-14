import hashlib
import json
from datetime import datetime
from typing import Any

from a_stock_lab.features.tail_radar.application.research_models import ResearchProviderRequest
from a_stock_lab.features.tail_radar.domain.research import TAIL_RADAR_RESEARCH_PROMPT_VERSION

_INSTRUCTIONS = """You are the point-in-time web research component for A-Stock Lab.

Use web search to research the supplied A-share Tail Radar candidate. Keep this probabilistic
research completely separate from the deterministic screening and intraday evidence supplied as
input. Do not change, rescore, or reinterpret candidate membership.

The supplied analysis_as_of is a hard historical information boundary. Retrieval may occur later.
Do not present information published after analysis_as_of as known at that time. For every source,
report a publication timestamp as verified only when the source page explicitly displays it. Mark
ambiguous or inferred timestamps uncertain and absent timestamps unavailable. Claims lacking at
least one source with a verified publication timestamp at or before analysis_as_of are not verified
facts. Sources published after analysis_as_of must not support contemporaneous facts or likely
drivers. Copy source URLs exactly from web-search evidence; never invent citation metadata.

Research company announcements, same-day company news, recent company developments, sector and
industry developments, policy and macro catalysts, upstream/downstream events, broader A-share
context, and plausible explanations for the day's price movement. Resolve contradictions when
possible. Explicitly classify every claim as verified_fact, interpretation, or
insufficient_evidence. Likely drivers are interpretations, not facts. Prefer insufficient evidence
over speculation. Do not give buy/sell labels, target prices, or future-return predictions.

Write every narrative output field in Simplified Chinese, including the concise summary, claim
statements, contexts, factors, and unresolved questions. Preserve stock symbols, official company
names, proper nouns, URLs, model identifiers, and source titles in their authentic original form
when translating them would reduce attribution accuracy. Structured enum values and field names
must continue to follow the supplied schema exactly.
"""

PROMPT_SHA256 = hashlib.sha256(_INSTRUCTIONS.encode("utf-8")).hexdigest()


def build_research_provider_request(
    *, analysis_as_of: datetime, evidence: dict[str, Any]
) -> ResearchProviderRequest:
    input_payload = {
        "analysis_as_of": str(analysis_as_of),
        "candidate_evidence": evidence,
        "required_prompt_version": TAIL_RADAR_RESEARCH_PROMPT_VERSION,
    }
    return ResearchProviderRequest(
        analysis_as_of=analysis_as_of,
        prompt_sha256=PROMPT_SHA256,
        instructions=_INSTRUCTIONS,
        input_text=json.dumps(input_payload, ensure_ascii=False, sort_keys=True),
    )
