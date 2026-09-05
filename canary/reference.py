"""User-supplied numeric reference observations."""

import csv
import math
from pathlib import Path

type Series = list[tuple[float, float]]


def validate_reference(series: Series) -> None:
    previous = None
    for timestamp, value in series:
        if not math.isfinite(timestamp) or not math.isfinite(value):
            raise ValueError("reference timestamps and values must be finite")
        if previous is not None and timestamp <= previous:
            raise ValueError("reference timestamps must be strictly increasing")
        previous = timestamp


def read_reference(path: str | Path, value_column: str) -> Series:
    """Read timestamp and the named value column; ignore extra named columns."""
    if not value_column or value_column == "timestamp":
        raise ValueError("value column must be a nonempty name other than timestamp")
    series = []
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = next(reader, None)
            if (header is None or len(set(header)) != len(header)
                    or "timestamp" not in header or value_column not in header):
                raise ValueError(f"{path}: header requires unique timestamp and {value_column} columns")
            time_index, value_index = header.index("timestamp"), header.index(value_column)
            for row in reader:
                try:
                    if len(row) != len(header):
                        raise ValueError(f"expected {len(header)} columns, got {len(row)}")
                    try:
                        timestamp, value = float(row[time_index]), float(row[value_index])
                    except ValueError:
                        raise ValueError("timestamp and reference value must be finite numbers") from None
                    if not math.isfinite(timestamp) or not math.isfinite(value):
                        raise ValueError("timestamp and reference value must be finite numbers")
                    if series and timestamp <= series[-1][0]:
                        raise ValueError("reference timestamps must be strictly increasing")
                    series.append((timestamp, value))
                except ValueError as exc:
                    raise ValueError(f"{path}: line {reader.line_num}: {exc}") from exc
        except csv.Error as exc:
            raise ValueError(f"{path}: line {reader.line_num}: malformed CSV: {exc}") from exc
    return series
