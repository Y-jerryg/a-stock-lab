from datetime import date

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class TradingDay(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_date: date
    is_trading_day: bool
    provider: str = Field(min_length=1)
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)
