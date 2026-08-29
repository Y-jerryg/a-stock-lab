from a_stock_lab.features.tail_radar.application.queries import TailRadarQueryService
from a_stock_lab.features.tail_radar.factory import build_tail_radar_query_service


def get_tail_radar_query_service() -> TailRadarQueryService:
    return build_tail_radar_query_service()
