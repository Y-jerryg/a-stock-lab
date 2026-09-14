from a_stock_lab.shared.market_data.models import AShareBoard, AShareExchange


def infer_a_share_exchange(symbol: str) -> AShareExchange | None:
    """Infer the listing exchange only for established six-digit A-share code families."""
    if symbol.startswith("6"):
        return AShareExchange.SHANGHAI
    if symbol.startswith(("0", "3")):
        return AShareExchange.SHENZHEN
    if symbol.startswith(("4", "8", "92")):
        return AShareExchange.BEIJING
    return None


def infer_a_share_board(symbol: str, exchange: AShareExchange | None = None) -> AShareBoard | None:
    """Infer only stable exchange-board families from a normalized six-digit symbol."""
    resolved_exchange = exchange or infer_a_share_exchange(symbol)
    if resolved_exchange is AShareExchange.BEIJING:
        return AShareBoard.BEIJING
    if resolved_exchange is AShareExchange.SHANGHAI:
        if symbol.startswith(("688", "689")):
            return AShareBoard.STAR
        if symbol.startswith("6"):
            return AShareBoard.SHANGHAI_MAIN
    if resolved_exchange is AShareExchange.SHENZHEN:
        if symbol.startswith(("300", "301")):
            return AShareBoard.CHINEXT
        if symbol.startswith(("000", "001", "002", "003")):
            return AShareBoard.SHENZHEN_MAIN
    return None
