class TailRadarError(Exception):
    """Base class for expected Tail Radar failures."""


class TailRadarSourceSnapshotNotFoundError(TailRadarError):
    """The requested snapshot is absent or is not a successful official snapshot."""


class TailRadarSnapshotIntegrityError(TailRadarError):
    """Persisted snapshot evidence does not agree with its registered manifest."""


class TailRadarPersistenceError(TailRadarError):
    """Tail Radar execution or query persistence failed."""


class TailRadarCommitUncertainError(TailRadarPersistenceError):
    """The client cannot safely determine whether candidate persistence committed."""
