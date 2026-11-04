"""Time axes (daily, pentad, dekad, monthly) and their chunking."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

# First day of each sub-monthly period: pentads end on day 5, 10, ..., 25 and the month's end;
# dekads on day 10, 20 and the month's end.
PERIOD_START_DAYS = {"pentad": (1, 6, 11, 16, 21, 26), "dekad": (1, 11, 21)}
AXIS_END = dt.date(2100, 12, 31)


@dataclass(frozen=True)
class Frequency:
    name: str  # "daily" | "pentad" | "dekad" | "monthly"
    start: dt.date
    time_chunk: int
    space_chunk: int
    # When set, each (time_chunk, space_chunk, space_chunk) block is a shard of these smaller chunks.
    inner_chunk: tuple[int, int, int] | None = None

    def zarr_layout(self) -> dict:
        """`chunks` (and `shards`) arguments for zarr.create_array."""
        block = (self.time_chunk, self.space_chunk, self.space_chunk)
        return {"chunks": self.inner_chunk, "shards": block} if self.inner_chunk else {"chunks": block}

    def layout_name(self) -> str:
        block = f"{self.time_chunk}x{self.space_chunk}x{self.space_chunk}"
        return f"shard{block}/{'x'.join(map(str, self.inner_chunk))}" if self.inner_chunk else block

    @cached_property
    def _axis(self) -> pd.DatetimeIndex:
        return self.dates(AXIS_END)

    def dates(self, end: dt.date) -> pd.DatetimeIndex:
        """Period start dates from `start` through `end` (inclusive)."""
        if self.name == "daily":
            return pd.date_range(self.start, end, freq="D")
        months = pd.date_range(self.start.replace(day=1), end, freq="MS")
        if self.name == "monthly":
            return months[months >= pd.Timestamp(self.start)]
        days = PERIOD_START_DAYS[self.name]
        out = pd.DatetimeIndex([m + pd.Timedelta(days=d - 1) for m in months for d in days])
        return out[(out >= pd.Timestamp(self.start)) & (out <= pd.Timestamp(end))]

    def ends(self, dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """Exclusive end of each period starting at `dates`."""
        if self.name == "daily":
            return dates + pd.Timedelta(days=1)
        if self.name == "monthly":
            return dates + pd.offsets.MonthBegin(1)
        days = PERIOD_START_DAYS[self.name]
        out = []
        for d in dates:
            i = days.index(d.day)
            out.append(d.replace(day=days[i + 1]) if i + 1 < len(days) else d + pd.offsets.MonthBegin(1))
        return pd.DatetimeIndex(out)

    def index_of(self, d: dt.date) -> int:
        """Index of the period containing date `d`."""
        return int(np.searchsorted(self._axis.values, np.datetime64(d), side="right")) - 1

    def chunk_dates(self, chunk_index: int) -> pd.DatetimeIndex:
        return self._axis[chunk_index * self.time_chunk : (chunk_index + 1) * self.time_chunk]

    def n_steps(self, end: dt.date) -> int:
        return len(self.dates(end))

    def chunk_indices(self, start: dt.date, end: dt.date) -> list[int]:
        """Time chunks overlapping [start, end]."""
        return list(range(self.index_of(start) // self.time_chunk, self.index_of(end) // self.time_chunk + 1))
