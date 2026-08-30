class TailRadarError(Exception):
    """Base class for expected Tail Radar failures."""


class TailRadarSourceSnapshotNotFoundError(TailRadarError):
    """The requested snapshot is absent or is not a successful official snapshot."""


class TailRadarSnapshotIntegrityError(TailRadarError):
    """Persisted snapshot evidence does not agree with its registered manifest."""


class TailRadarPersistenceError(TailRadarError):
    """Tail Radar execution or query persistence failed."""


class TailRadarCommitUncertainError(TailRadarPersistenceError):
    """The client cannot safely determine whether Tail Radar persistence committed."""


class TailRadarCandidateNotFoundError(TailRadarError):
    """The requested persisted Tail Radar candidate does not exist."""


class TailRadarIntradayAnalysisError(TailRadarError):
    """The candidate intraday analysis could not be produced safely."""


class TailRadarIntradayAnalysisTimeError(TailRadarIntradayAnalysisError):
    """The requested intraday analysis timestamp is not valid for the candidate."""


class TailRadarResearchError(TailRadarError):
    """A Tail Radar web-research attempt could not be handled safely."""


class TailRadarResearchTimeError(TailRadarResearchError):
    """The requested research timestamp is invalid for the candidate."""


class TailRadarResearchConfigurationError(TailRadarResearchError):
    """Backend-only research provider configuration is incomplete."""


class ResearchProviderError(TailRadarResearchError):
    code = "research_provider_error"


class ResearchProviderTimeoutError(ResearchProviderError):
    code = "research_provider_timeout"


class ResearchProviderRateLimitError(ResearchProviderError):
    code = "research_provider_rate_limit"


class ResearchProviderUnavailableError(ResearchProviderError):
    code = "research_provider_unavailable"


class ResearchProviderAPIError(ResearchProviderError):
    code = "research_provider_api_error"


class ResearchProviderInvalidResponseError(ResearchProviderError):
    code = "research_provider_invalid_response"
