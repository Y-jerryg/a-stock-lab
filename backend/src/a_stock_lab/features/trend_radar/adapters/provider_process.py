"""Isolated AKShare calls: the parent enforces a hard process timeout on every request."""

import contextlib
import json
import sys
import traceback
from multiprocessing.connection import Connection

from a_stock_lab.features.trend_radar.adapters.diagnostics import redact


def serve(connection: Connection) -> None:
    """One interpreter handles many requests; Python imports AKShare only once."""
    try:
        while True:
            try:
                action, args = connection.recv()
            except EOFError:
                return
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    frame = fetch_frame(action, list(args))
                # Preserve the same JSON-compatible normalization as the one-shot protocol.
                rows = json.loads(json.dumps(frame.to_dict(orient="records"), default=str))
                connection.send({"rows": rows})
            except Exception as exc:
                connection.send({"error": error_details(exc)})
    finally:
        connection.close()


def error_details(exc: Exception) -> dict[str, str]:
    request = getattr(exc, "request", None)
    return {
        "exception_type": type(exc).__name__,
        "exception_message": redact(str(exc)),
        "url": redact(str(getattr(request, "url", ""))),
        "provider_traceback": redact(traceback.format_exc()),
    }


def fetch_frame(action: str, args: list[str]):  # type: ignore[no-untyped-def]
    import akshare as ak  # type: ignore[import-untyped]

    if action == "heat":
        return ak.stock_comment_em()
    if action == "universe":
        return ak.stock_info_a_code_name()
    if action == "calendar":
        return ak.tool_trade_date_hist_sina()
    if action == "bars":
        return ak.stock_zh_a_hist(
            symbol=args[0], period="daily", start_date=args[1], end_date=args[2], adjust="qfq"
        )
    if action == "bars-sina":
        symbol = args[0]
        prefix = (
            "sh"
            if symbol.startswith(("6", "9")) and not symbol.startswith("92")
            else ("sz" if symbol.startswith(("0", "3")) else "bj")
        )
        frame = ak.stock_zh_a_daily(
            symbol=prefix + symbol, start_date=args[1], end_date=args[2], adjust="qfq"
        ).rename(
            columns={
                "date": "日期",
                "open": "开盘",
                "high": "最高",
                "low": "最低",
                "close": "收盘",
                "volume": "成交量",
                "amount": "成交额",
            }
        )
        # Canonical volume remains lots, matching existing Eastmoney history; amount is yuan.
        frame["成交量"] = frame["成交量"] / 100
        return frame
    raise ValueError("unknown provider operation")


def main() -> None:
    action, *args = sys.argv[1:]
    try:
        with contextlib.redirect_stdout(sys.stderr):
            frame = fetch_frame(action, args)
        sys.stdout.write(
            json.dumps(frame.to_dict(orient="records"), default=str, ensure_ascii=True)
        )
    except Exception as exc:
        sys.stdout.write(
            json.dumps(
                {"error": error_details(exc)},
                ensure_ascii=True,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
