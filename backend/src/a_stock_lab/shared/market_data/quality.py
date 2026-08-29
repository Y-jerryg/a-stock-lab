from collections import Counter

from a_stock_lab.shared.market_data.models import (
    NormalizationIssueCode,
    ProviderSnapshotBatch,
    SnapshotQualityReport,
    SnapshotQualityThresholds,
)


def _ratio(count: int, total: int) -> float:
    if total == 0:
        return 1.0 if count else 0.0
    return count / total


def evaluate_snapshot_quality(
    batch: ProviderSnapshotBatch,
    thresholds: SnapshotQualityThresholds,
) -> SnapshotQualityReport:
    symbol_counts = Counter(record.symbol for record in batch.records)
    duplicate_symbol_count = sum(count - 1 for count in symbol_counts.values() if count > 1)

    missing_symbol_rows = {
        issue.row_number
        for issue in batch.normalization_issues
        if issue.code == NormalizationIssueCode.MISSING_SYMBOL
    }
    invalid_price_from_normalization = {
        issue.row_number
        for issue in batch.normalization_issues
        if issue.code == NormalizationIssueCode.INVALID_NUMERIC_VALUE and issue.field == "price"
    }
    invalid_pct_change_from_normalization = {
        issue.row_number
        for issue in batch.normalization_issues
        if issue.code == NormalizationIssueCode.INVALID_NUMERIC_VALUE
        and issue.field == "pct_change"
    }
    malformed_rows = {issue.row_number for issue in batch.normalization_issues}

    invalid_price_count = len(invalid_price_from_normalization) + sum(
        record.price is not None and record.price <= 0 for record in batch.records
    )
    invalid_pct_change_count = len(invalid_pct_change_from_normalization) + sum(
        record.pct_change is not None and abs(record.pct_change) > thresholds.max_abs_pct_change
        for record in batch.records
    )

    missing_symbol_count = len(missing_symbol_rows)
    malformed_row_count = len(malformed_rows)
    normalized_record_count = len(batch.records)
    missing_symbol_ratio = _ratio(missing_symbol_count, batch.raw_record_count)
    invalid_price_ratio = _ratio(invalid_price_count, normalized_record_count)
    invalid_pct_change_ratio = _ratio(invalid_pct_change_count, normalized_record_count)
    malformed_row_ratio = _ratio(malformed_row_count, batch.raw_record_count)

    violations: list[str] = []
    if normalized_record_count < thresholds.min_record_count:
        violations.append("record_count_below_minimum")
    if duplicate_symbol_count > thresholds.max_duplicate_symbols:
        violations.append("duplicate_symbols_exceeded")
    if missing_symbol_ratio > thresholds.max_missing_symbol_ratio:
        violations.append("missing_symbol_ratio_exceeded")
    if invalid_price_ratio > thresholds.max_invalid_price_ratio:
        violations.append("invalid_price_ratio_exceeded")
    if invalid_pct_change_ratio > thresholds.max_invalid_pct_change_ratio:
        violations.append("invalid_pct_change_ratio_exceeded")
    if malformed_row_ratio > thresholds.max_malformed_row_ratio:
        violations.append("malformed_row_ratio_exceeded")

    return SnapshotQualityReport(
        passed=not violations,
        raw_record_count=batch.raw_record_count,
        normalized_record_count=normalized_record_count,
        duplicate_symbol_count=duplicate_symbol_count,
        missing_symbol_count=missing_symbol_count,
        invalid_price_count=invalid_price_count,
        invalid_pct_change_count=invalid_pct_change_count,
        malformed_row_count=malformed_row_count,
        missing_symbol_ratio=missing_symbol_ratio,
        invalid_price_ratio=invalid_price_ratio,
        invalid_pct_change_ratio=invalid_pct_change_ratio,
        malformed_row_ratio=malformed_row_ratio,
        thresholds=thresholds,
        violations=tuple(violations),
    )
