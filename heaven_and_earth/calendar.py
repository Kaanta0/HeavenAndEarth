from __future__ import annotations

"""Persistent in-game calendar anchored to February 2nd, 993."""

import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .models import SECONDS_PER_TICK

if sys.version_info >= (3, 11):  # pragma: no cover - stdlib availability
    import tomllib  # type: ignore[attr-defined]
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[assignment]

import tomli_w


CALENDAR_START_DATE = date(993, 2, 2)


@dataclass
class GameCalendar:
    start_timestamp: int

    @staticmethod
    def _ordinal(day: int) -> str:
        if 10 <= day % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{day}{suffix}"

    def days_since_start(self, timestamp: int) -> int:
        return int((timestamp - self.start_timestamp) // SECONDS_PER_TICK)

    def date_for_timestamp(self, timestamp: int) -> date:
        return CALENDAR_START_DATE + timedelta(days=self.days_since_start(timestamp))

    def format_date(self, timestamp: int) -> str:
        current_date = self.date_for_timestamp(timestamp)
        return f"{current_date.strftime('%B')} {self._ordinal(current_date.day)}, {current_date.year}"

    def days_elapsed(self, start_timestamp: int, end_timestamp: int | None = None) -> float:
        end_timestamp = end_timestamp or int(time.time())
        return max(end_timestamp - start_timestamp, 0) / SECONDS_PER_TICK


class CalendarRepository:
    def __init__(self, data_dir: str = ".data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "calendar.toml"

    def load_or_create_start(self) -> int:
        if self.path.exists():
            content = self.path.read_text(encoding="utf-8")
            raw = tomllib.loads(content) if content.strip() else {}
            if "start_timestamp" in raw:
                return int(raw["start_timestamp"])
        start_timestamp = int(time.time())
        self.save_start(start_timestamp)
        return start_timestamp

    def save_start(self, start_timestamp: int) -> None:
        payload = {"start_timestamp": int(start_timestamp)}
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        tmp_path.replace(self.path)
