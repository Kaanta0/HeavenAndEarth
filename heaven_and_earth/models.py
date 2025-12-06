from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from random import random
from enum import Enum
from typing import Dict, List


class Realm(str, Enum):
    QI_CONDENSATION = "Qi Condensation"
    FOUNDATION_ESTABLISHMENT = "Foundation Establishment"
    CORE_FORMATION = "Core Formation"
    NASCENT_SOUL = "Nascent Soul"
    SOUL_TRANSFORMATION = "Soul Transformation"
    VOID_REFINEMENT = "Void Refinement"
    BODY_INTEGRATION = "Body Integration"
    GREAT_ASCENSION = "Great Ascension"


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


REALM_ORDER: List[Realm] = [
    Realm.QI_CONDENSATION,
    Realm.FOUNDATION_ESTABLISHMENT,
    Realm.CORE_FORMATION,
    Realm.NASCENT_SOUL,
    Realm.SOUL_TRANSFORMATION,
    Realm.VOID_REFINEMENT,
    Realm.BODY_INTEGRATION,
    Realm.GREAT_ASCENSION,
]


def default_timestamp() -> int:
    return int(time.time())


@dataclass
class CultivationProgress:
    realm: Realm = Realm.QI_CONDENSATION
    stage: Stage = Stage.INITIAL
    exp: float = 0.0
    cultivation_rate: float = 1.0  # percent per tick -> exp per tick

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
    item: str | None = None
    description: str | None = None


DEFAULT_SLOTS: Dict[str, EquipmentSlot] = {
    "weapon": EquipmentSlot(name="Weapon", item=None, description="Empty hand"),
    "armor": EquipmentSlot(name="Armor", item=None, description="Tattered robes"),
    "artifact": EquipmentSlot(name="Artifact", item=None, description="None"),
    "ring": EquipmentSlot(name="Ring", item=None, description="None"),
}


@dataclass
class Player:
    user_id: int
    name: str
    created_at: int = field(default_factory=default_timestamp)
    birthday: int = field(default_factory=default_timestamp)
    stats: PlayerStats = field(default_factory=PlayerStats)
    cultivation: CultivationProgress = field(default_factory=CultivationProgress)
    inventory: List[str] = field(default_factory=list)
    equipment: Dict[str, EquipmentSlot] = field(
        default_factory=lambda: {k: dataclasses.asdict(v) for k, v in DEFAULT_SLOTS.items()}
    )
    last_tick_timestamp: int = field(default_factory=default_timestamp)

    def age_years(self, now: int | None = None) -> float:
        now = now or int(time.time())
        return (now - self.birthday) / (60 * 60 * 24 * 365)

    def apply_ticks(self, ticks: int) -> List[str]:
        self.stats.hours_cultivated += ticks / 60
        logs = self.cultivation.add_exp(ticks)
        for note in logs:
            lowered = note.lower()
            if "tribulation" in lowered and "overcome" in lowered:
                self.stats.tribulations_survived += 1
        self.last_tick_timestamp += ticks * 60
        return logs

    def record_travel(self, distance: int, destination: str) -> str:
        self.stats.steps_travelled += distance
        return f"Travelled {distance} li toward {destination}."

    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(data: Dict) -> "Player":
        return Player(
            user_id=data["user_id"],
            name=data.get("name", "Unnamed"),
            created_at=data.get("created_at", default_timestamp()),
            birthday=data.get("birthday", default_timestamp()),
            stats=PlayerStats(**data.get("stats", {})),
            cultivation=CultivationProgress(**data.get("cultivation", {})),
            inventory=list(data.get("inventory", [])),
            equipment={k: EquipmentSlot(**v) for k, v in data.get("equipment", {}).items()}
            if data.get("equipment")
            else {k: dataclasses.asdict(v) for k, v in DEFAULT_SLOTS.items()},
            last_tick_timestamp=data.get("last_tick_timestamp", default_timestamp()),
        )
