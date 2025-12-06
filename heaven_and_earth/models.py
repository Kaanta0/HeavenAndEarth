from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from random import random
from enum import Enum
from typing import Dict, List
import re


class Realm(str, Enum):
    QI_CONDENSATION = "Qi Condensation"


class Stage(str, Enum):
    INITIAL = "Initial"
    EARLY = "Early"
    MIDDLE = "Middle"
    LATE = "Late"
    PEAK = "Peak"


STAGE_ORDER: List[Stage] = [
    Stage.INITIAL,
    Stage.EARLY,
    Stage.MIDDLE,
    Stage.LATE,
    Stage.PEAK,
]


REALM_ORDER: List[Realm] = [Realm.QI_CONDENSATION]

SECONDS_PER_TICK = 60  # one real minute per tick
DAYS_PER_YEAR = 365
STARTING_AGE_YEARS = 10
REALM_LIFESPAN_YEARS: Dict[Realm, float] = {Realm.QI_CONDENSATION: 120}


def default_timestamp() -> int:
    return int(time.time())


def default_birthday() -> int:
    # Players begin at 10 years old; one tick (60 seconds) counts as one in-game day.
    return int(time.time()) - int(STARTING_AGE_YEARS * DAYS_PER_YEAR * SECONDS_PER_TICK)


@dataclass
class CultivationProgress:
    realm: Realm = Realm.QI_CONDENSATION
    stage: Stage = Stage.INITIAL
    exp: float = 0.0
    cultivation_rate: float = 1.0  # percent per tick -> exp per tick

    def __post_init__(self) -> None:
        if isinstance(self.realm, str):
            try:
                self.realm = Realm(self.realm)
            except ValueError:
                self.realm = Realm.QI_CONDENSATION
        if isinstance(self.stage, str):
            try:
                self.stage = Stage(self.stage)
            except ValueError:
                self.stage = Stage.INITIAL

    def ticks_until_breakthrough(self) -> float:
        remaining = max(self.required_exp() - self.exp, 0)
        if self.cultivation_rate <= 0:
            return float("inf")
        return remaining / self.cultivation_rate

    def required_exp(self) -> float:
        base = (REALM_ORDER.index(self.realm) + 1) * 100
        stage_multiplier = (STAGE_ORDER.index(self.stage) + 1)
        return base * stage_multiplier

    def add_exp(self, ticks: int) -> List[str]:
        log: List[str] = []
        self.exp += self.cultivation_rate * ticks
        while self.exp >= self.required_exp():
            self.exp -= self.required_exp()
            log.append(self.advance_stage())
        return log

    def advance_stage(self) -> str:
        current_stage_index = STAGE_ORDER.index(self.stage)
        if current_stage_index + 1 < len(STAGE_ORDER):
            self.stage = STAGE_ORDER[current_stage_index + 1]
            return f"Advanced to {self.stage.value} stage of {self.realm.value}."
        return self.breakthrough_realm()

    def breakthrough_realm(self) -> str:
        realm_index = REALM_ORDER.index(self.realm)
        if realm_index + 1 < len(REALM_ORDER):
            tribulation = HeavenlyTribulation(self.realm, REALM_ORDER[realm_index + 1])
            outcome = tribulation.resolve()
            self.realm = tribulation.target_realm
            self.stage = Stage.INITIAL
            return outcome
        self.stage = Stage.PEAK
        return "Reached the pinnacle; no further breakthroughs possible."


@dataclass
class HeavenlyTribulation:
    current_realm: Realm
    target_realm: Realm
    danger: float = 0.25

    def resolve(self) -> str:
        """Resolve a tribulation with a small chance of setback."""
        if random() < self.danger:
            return (
                f"Tribulation clouds scatter—close call! {self.target_realm.value} awaits; cultivation steadies for the next attempt."
            )
        return f"Heavenly tribulation overcome! Broke through to {self.target_realm.value}."


@dataclass
class PlayerStats:
    enemies_defeated: int = 0
    tribulations_survived: int = 0
    hours_cultivated: float = 0.0
    steps_travelled: int = 0


@dataclass
class EquipmentSlot:
    name: str
    item: str = ""
    description: str = ""


DEFAULT_SLOTS: Dict[str, EquipmentSlot] = {
    "weapon": EquipmentSlot(name="Weapon", item="", description="Empty hand"),
    "armor": EquipmentSlot(name="Armor", item="", description="Tattered robes"),
    "artifact": EquipmentSlot(name="Artifact", item="", description="None"),
    "ring": EquipmentSlot(name="Ring", item="", description="None"),
}


@dataclass
class Player:
    user_id: int
    name: str
    created_at: int = field(default_factory=default_timestamp)
    birthday: int = field(default_factory=default_birthday)
    stats: PlayerStats = field(default_factory=PlayerStats)
    cultivation: CultivationProgress = field(default_factory=CultivationProgress)
    inventory: List[str] = field(default_factory=list)
    equipment: Dict[str, EquipmentSlot] = field(
        default_factory=lambda: {k: dataclasses.asdict(v) for k, v in DEFAULT_SLOTS.items()}
    )
    last_tick_timestamp: int = field(default_factory=default_timestamp)
    world_id: str | None = None
    zone_id: str | None = None
    position_x: int = 0
    position_y: int = 0
    tick_buffer: float = 0.0

    def age_years(self, now: int | None = None) -> float:
        now = now or int(time.time())
        days_lived = max(now - self.birthday, 0) / SECONDS_PER_TICK
        return days_lived / DAYS_PER_YEAR

    def lifespan_years(self) -> float:
        return REALM_LIFESPAN_YEARS.get(self.cultivation.realm, REALM_LIFESPAN_YEARS[Realm.QI_CONDENSATION])

    def remaining_lifespan_years(self, now: int | None = None) -> float:
        return max(self.lifespan_years() - self.age_years(now), 0.0)

    def apply_ticks(self, ticks: int) -> List[str]:
        self.stats.hours_cultivated += ticks * 24
        logs = self.cultivation.add_exp(ticks)
        for note in logs:
            lowered = note.lower()
            if "tribulation" in lowered and "overcome" in lowered:
                self.stats.tribulations_survived += 1
        return logs

    def to_dict(self) -> Dict:
        data = dataclasses.asdict(self)
        for key in ("world_id", "zone_id"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @staticmethod
    def from_dict(data: Dict) -> "Player":
        return Player(
            user_id=data["user_id"],
            name=data.get("name", "Unnamed"),
            created_at=data.get("created_at", default_timestamp()),
            birthday=data.get("birthday", default_birthday()),
            stats=PlayerStats(**data.get("stats", {})),
            cultivation=CultivationProgress(**data.get("cultivation", {})),
            inventory=list(data.get("inventory", [])),
            equipment={k: EquipmentSlot(**v) for k, v in data.get("equipment", {}).items()}
            if data.get("equipment")
            else {k: dataclasses.asdict(v) for k, v in DEFAULT_SLOTS.items()},
            last_tick_timestamp=data.get("last_tick_timestamp", default_timestamp()),
            world_id=data.get("world_id"),
            zone_id=data.get("zone_id"),
            position_x=int(data.get("position_x", 0)),
            position_y=int(data.get("position_y", 0)),
            tick_buffer=float(data.get("tick_buffer", 0.0)),
        )


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "world"
@dataclass
class World:
    id: str
    name: str
    current_location_role_id: int
    beginning: bool = False
    time_flow: float = 1.0


@dataclass
class Zone:
    id: str
    world_id: str
    name: str
    channel_id: int
    current_location_role_id: int
    x_size: int
    y_size: int
    beginning: bool = False
    time_flow: float = 1.0

