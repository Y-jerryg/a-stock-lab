import pytest

from a_stock_lab.shared.market_data.models import AShareBoard, AShareExchange
from a_stock_lab.shared.market_data.symbols import infer_a_share_board


@pytest.mark.parametrize(
    ("symbol", "exchange", "expected"),
    [
        ("600000", AShareExchange.SHANGHAI, AShareBoard.SHANGHAI_MAIN),
        ("688001", AShareExchange.SHANGHAI, AShareBoard.STAR),
        ("000001", AShareExchange.SHENZHEN, AShareBoard.SHENZHEN_MAIN),
        ("002001", AShareExchange.SHENZHEN, AShareBoard.SHENZHEN_MAIN),
        ("300001", AShareExchange.SHENZHEN, AShareBoard.CHINEXT),
        ("430001", AShareExchange.BEIJING, AShareBoard.BEIJING),
        ("920001", AShareExchange.BEIJING, AShareBoard.BEIJING),
        ("100001", None, None),
    ],
)
def test_infer_a_share_board_uses_only_stable_symbol_families(
    symbol: str,
    exchange: AShareExchange | None,
    expected: AShareBoard | None,
) -> None:
    assert infer_a_share_board(symbol, exchange) is expected
