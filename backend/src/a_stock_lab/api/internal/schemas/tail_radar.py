from typing import Literal

from pydantic import BaseModel


class TailRadarResearchRequest(BaseModel):
    confirmed: Literal[True]
    retry_failed: bool = False
