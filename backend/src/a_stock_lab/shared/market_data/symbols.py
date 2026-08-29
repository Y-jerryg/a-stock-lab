from a_stock_lab.shared.market_data.models import AShareExchange


def infer_a_share_exchange(symbol: str) -> AShareExchange | None:
    """Infer the listing exchange only for established six-digit A-share code families."""
    if symbol.startswith("6"):
        return AShareExchange.SHANGHAI
    if symbol.startswith(("0", "3")):
        return AShareExchange.SHENZHEN
    if symbol.startswith(("4", "8", "92")):
        return AShareExchange.BEIJING
    return None
