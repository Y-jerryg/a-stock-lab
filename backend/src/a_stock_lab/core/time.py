from datetime import datetime
from zoneinfo import ZoneInfo

MARKET_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def now_in_market_timezone() -> datetime:
    """Return an aware timestamp in the canonical A-share market timezone."""
    return datetime.now(tz=MARKET_TIME_ZONE)


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def as_market_timezone(value: datetime) -> datetime:
    """Validate and normalize an aware timestamp to the canonical market timezone."""
    return require_aware(value).astimezone(MARKET_TIME_ZONE)
