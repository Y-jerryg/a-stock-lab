import json
import logging
import math
import subprocess
import sys
import time
import traceback
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError

from a_stock_lab.features.trend_radar.adapters.diagnostics import redact
from a_stock_lab.features.trend_radar.application.diagnostics import stock_context
from a_stock_lab.features.trend_radar.config import TrendSettings
from a_stock_lab.features.trend_radar.domain.models import Bar, Heat, ListedStock, TrendError

logger = logging.getLogger(__name__)
PROVIDERS = {
    "universe": ("exchange_a_share_list", "https://www.sse.com.cn/assortment/stock/list/share/"),
    "bars": ("eastmoney_daily_qfq", "https://push2his.eastmoney.com/api/qt/stock/kline/get"),
    "bars-sina": ("sina_daily_qfq", "https://finance.sina.com.cn/realstock/company/"),
    "heat": ("eastmoney_attention_index", "https://datacenter-web.eastmoney.com/api/data/v1/get"),
    "calendar": ("sina_calendar", "https://finance.sina.com.cn/realstock/company/klc_td_sh.txt"),
}


class AkShareTrendProvider:
    def __init__(self, settings: TrendSettings) -> None:
        self.settings = settings
        self._calendar: tuple[date, list[date]] | None = None
        self._primary_retry_at = 0.0

    def _fetch(self, action: str, *args: str) -> list[dict[str, Any]]:
        for attempt in range(self.settings.trend_provider_attempts):
            time.sleep(self.settings.trend_provider_pace_seconds + (2**attempt - 1))
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        "-m",
                        __package__ + ".provider_process",
                        action,
                        *args,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.settings.trend_provider_timeout_seconds,
                    check=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                rows = json.loads(result.stdout)
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise TrendError("provider_malformed_response")
                return rows
            except (subprocess.SubprocessError, OSError, ValueError) as exc:
                provider, endpoint = PROVIDERS[action]
                details: dict[str, object] = {
                    "provider": provider,
                    "url": endpoint,
                    "attempt": attempt + 1,
                    "exception_type": type(exc).__name__,
                    "exception_message": redact(str(exc)),
                    "provider_traceback": redact(traceback.format_exc()),
                }
                if isinstance(exc, subprocess.CalledProcessError) and exc.stdout:
                    try:
                        payload = json.loads(exc.stdout)
                        error = payload.get("error", {}) if isinstance(payload, dict) else {}
                        for key in (
                            "exception_type",
                            "exception_message",
                            "url",
                            "provider_traceback",
                        ):
                            if isinstance(error, dict) and error.get(key):
                                details[key] = redact(str(error[key]))
                    except (ValueError, TypeError):
                        pass
                logger.warning(
                    "trend_provider_attempt_failed",
                    extra={
                        **stock_context(),
                        **details,
                        "operation": action,
                        "error_code": "provider_error",
                        "max_attempts": self.settings.trend_provider_attempts,
                        "start_date": args[1] if len(args) > 1 else None,
                        "end_date": args[2] if len(args) > 2 else None,
                    },
                )
                if attempt + 1 == self.settings.trend_provider_attempts:
                    raise TrendError("provider_error", details=details) from None
        raise AssertionError("unreachable")

    def fetch_heat(self) -> list[Heat]:
        fetched_at = datetime.now(UTC)
        try:
            result = []
            unavailable_scores = 0
            for row in self._fetch("heat"):
                symbol = str(row["代码"]).zfill(6)
                # All recognized mainland A-share families, including ST and Beijing.
                if not symbol.startswith(
                    (
                        "000",
                        "001",
                        "002",
                        "003",
                        "300",
                        "301",
                        "600",
                        "601",
                        "603",
                        "605",
                        "688",
                        "689",
                        "4",
                        "8",
                        "920",
                    )
                ):
                    continue
                score = row["关注指数"]
                # Newly listed securities can have no attention observation yet. They are not
                # part of the available scored universe; never invent a score or rank for them.
                if score is None or (isinstance(score, float) and math.isnan(score)):
                    unavailable_scores += 1
                    continue
                result.append(
                    Heat(
                        symbol=symbol,
                        name=str(row["名称"]),
                        heat_score=float(score),
                        heat_source="eastmoney_attention_index",
                        data_date=date.fromisoformat(str(row["交易日"])[:10]),
                        fetched_at=fetched_at,
                    )
                )
            logging.getLogger(__name__).info(
                "trend_heat_fetched",
                extra={
                    "heat_count": len(result),
                    "unavailable_attention_count": unavailable_scores,
                    "provider": "eastmoney_attention_index",
                },
            )
            return result
        except (KeyError, ValueError, TypeError, ValidationError):
            raise TrendError("provider_malformed_heat") from None

    def fetch_universe(self) -> list[ListedStock]:
        """Exchange lists include Shanghai, Shenzhen and Beijing, independent of attention."""
        fetched_at = datetime.now(UTC)
        try:
            rows = [
                ListedStock(
                    symbol=str(row["code"]).zfill(6),
                    name=str(row["name"]),
                    fetched_at=fetched_at,
                )
                for row in self._fetch("universe")
            ]
        except (KeyError, ValueError, TypeError, ValidationError):
            raise TrendError("provider_malformed_universe") from None
        # Fail on partial/empty exchange listings instead of claiming a full-market scan.
        if len(rows) < 4000 or len({row.symbol for row in rows}) != len(rows):
            raise TrendError("incomplete_a_share_universe")
        if not all(
            any(row.symbol.startswith(prefix) for row in rows) for prefix in ("6", "0", "920")
        ):
            raise TrendError("incomplete_a_share_universe")
        return sorted(rows, key=lambda row: row.symbol)

    def fetch_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        fetched_at = datetime.now(UTC)
        args = (symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        source = "sina_daily_qfq"
        if time.monotonic() >= self._primary_retry_at:
            try:
                rows = self._fetch("bars", *args)
                source = "eastmoney_daily_qfq"
            except TrendError as exc:
                if exc.code != "provider_error":
                    raise
                self._primary_retry_at = time.monotonic() + 300
                logger.warning(
                    "trend_daily_provider_fallback",
                    extra={
                        **stock_context(),
                        "provider": "eastmoney_daily_qfq",
                        "fallback_provider": source,
                        "cooldown_seconds": 300,
                    },
                )
                rows = self._fetch("bars-sina", *args)
        else:
            rows = self._fetch("bars-sina", *args)
        try:
            return [
                Bar(
                    symbol=symbol,
                    trade_date=date.fromisoformat(str(row["日期"])[:10]),
                    open=float(row["开盘"]),
                    high=float(row["最高"]),
                    low=float(row["最低"]),
                    close=float(row["收盘"]),
                    volume=float(row["成交量"]),
                    amount=float(row["成交额"]),
                    source=source,
                    fetched_at=fetched_at,
                )
                for row in rows
            ]
        except (KeyError, ValueError, TypeError, ValidationError) as exc:
            raise TrendError(
                "provider_malformed_bars",
                details={
                    "provider": source,
                    "exception_type": type(exc).__name__,
                    "exception_message": redact(str(exc)),
                    "provider_traceback": redact(traceback.format_exc()),
                },
            ) from None

    def sessions(self, today: date) -> list[date]:
        if self._calendar and self._calendar[0] == today:
            return self._calendar[1]
        try:
            days = sorted(
                {date.fromisoformat(str(row["trade_date"])[:10]) for row in self._fetch("calendar")}
            )
        except (KeyError, ValueError, TypeError):
            raise TrendError("provider_malformed_calendar") from None
        if not days or today < days[0] or today > days[-1]:
            raise TrendError("calendar_out_of_range")
        self._calendar = (today, days)
        return days
