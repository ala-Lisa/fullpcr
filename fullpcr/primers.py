"""Read and validate primers.tsv."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {"primer_id", "forward", "reverse", "min_length", "max_length"}


@dataclass(frozen=True)
class Primer:
    """A single primer pair record."""

    primer_id: str
    forward: str
    reverse: str
    min_length: int
    max_length: int


def read_primers(path: str | Path) -> list[Primer]:
    """Read primers from a TSV file and validate required columns.

    Args:
        path: Path to the primers.tsv file.

    Returns:
        List of Primer records.

    Raises:
        ValueError: If required columns are missing or data is invalid.
    """
    df = pd.read_csv(path, sep="\t", dtype=str)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"primers.tsv 缺少必填字段: {', '.join(sorted(missing))}。"
            f" 必填字段: {', '.join(sorted(REQUIRED_COLUMNS))}。"
        )

    primers = []
    for i, row in df.iterrows():
        try:
            min_len = int(row["min_length"])
            max_len = int(row["max_length"])
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"第 {i + 2} 行的 min_length 或 max_length 无法转为整数: "
                f"min_length={row['min_length']!r}, max_length={row['max_length']!r}"
            ) from exc

        if min_len <= 0:
            raise ValueError(
                f"第 {i + 2} 行 primer_id={row['primer_id']!r}: "
                f"min_length 必须 > 0，实际为 {min_len}。"
            )
        if max_len <= 0:
            raise ValueError(
                f"第 {i + 2} 行 primer_id={row['primer_id']!r}: "
                f"max_length 必须 > 0，实际为 {max_len}。"
            )
        if min_len > max_len:
            raise ValueError(
                f"第 {i + 2} 行 primer_id={row['primer_id']!r}: "
                f"min_length ({min_len}) 不能大于 max_length ({max_len})。"
            )

        primers.append(
            Primer(
                primer_id=str(row["primer_id"]),
                forward=str(row["forward"]),
                reverse=str(row["reverse"]),
                min_length=min_len,
                max_length=max_len,
            )
        )

    return primers
