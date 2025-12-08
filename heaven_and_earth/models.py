from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from random import random, uniform
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Dict, List
import re

if TYPE_CHECKING:  # pragma: no cover - imported only for type hints
    from .calendar import GameCalendar


class Realm(str, Enum):
    QI_CONDENSATION = "Qi Condensation"
    FOUNDATION_ESTABLISHMENT = "Foundation Establishment"


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


REALM_ORDER: List[Realm] = [Realm.QI_CONDENSATION, Realm.FOUNDATION_ESTABLISHMENT]

DAYS_PER_YEAR = 365
FOUNDATION_YEARS_TO_FILL = 5
FOUNDATION_FILL_TICKS = DAYS_PER_YEAR * FOUNDATION_YEARS_TO_FILL

SECONDS_PER_TICK = 60  # one real minute per tick
STARTING_AGE_YEARS = 10
REALM_LIFESPAN_YEARS: Dict[Realm, float] = {
    Realm.QI_CONDENSATION: 120,
    Realm.FOUNDATION_ESTABLISHMENT: 250,
}


class QiType(str, Enum):
    SPIRITUAL = "Spiritual Qi"
    YIN = "Yin Qi"
    YANG = "Yang Qi"

    @property
    def gathering_modifier(self) -> float:
        return 1.0


class QiQuality(str, Enum):
    FAINT = "Faint"
    THIN = "Thin"
    STEADY = "Steady"
    THICK = "Thick"
    CONDENSED = "Condensed"
    HIGHLY_CONCENTRATED = "Highly Concentrated"
    SUPERDENSE = "Superdense"
    EXTREMELY_DENSE = "Extremely dense"

    order: ClassVar[List["QiQuality"]] = [
        FAINT,
        THIN,
        STEADY,
        THICK,
        CONDENSED,
        HIGHLY_CONCENTRATED,
        SUPERDENSE,
        EXTREMELY_DENSE,
    ]

    @property
    def qi_per_day(self) -> float:
        rates = {
            QiQuality.FAINT: 1,
            QiQuality.THIN: 2,
            QiQuality.STEADY: 4,
            QiQuality.THICK: 8,
            QiQuality.CONDENSED: 16,
            QiQuality.HIGHLY_CONCENTRATED: 32,
            QiQuality.SUPERDENSE: 64,
            QiQuality.EXTREMELY_DENSE: 128,
        }
        return float(rates[self])

    def is_lower_than(self, other: "QiQuality") -> bool:
        return self.order.index(self) < self.order.index(other)


def default_timestamp() -> int:
    return int(time.time())


def default_birthday() -> int:
    # Players begin at 10 years old; one tick (60 seconds) counts as one in-game day.
    return int(time.time()) - int(STARTING_AGE_YEARS * DAYS_PER_YEAR * SECONDS_PER_TICK)


@dataclass
class CultivationProgress:
    realm: Realm = Realm.QI_CONDENSATION
    stage: Stage = Stage.INITIAL
    layer: int = 1
    exp: float = 0.0
    qi_type: QiType = QiType.SPIRITUAL
    qi_quality: QiQuality = QiQuality.FAINT
    cultivation_rate: float = 1.0  # percent per tick -> exp per tick
    foundation_progress: float = 0.0

    max_qi_layers: ClassVar[int] = 15

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
        try:
            self.layer = int(self.layer)
        except (TypeError, ValueError):
            self.layer = 1
        self.layer = min(max(self.layer, 1), self.max_qi_layers)
        if isinstance(self.qi_type, str):
            try:
                self.qi_type = QiType(self.qi_type)
            except ValueError:
                self.qi_type = QiType.SPIRITUAL
        if isinstance(self.qi_quality, str):
            try:
                self.qi_quality = QiQuality(self.qi_quality)
            except ValueError:
                self.qi_quality = QiQuality.FAINT
        try:
            self.foundation_progress = float(self.foundation_progress)
        except (TypeError, ValueError):
            self.foundation_progress = 0.0
        self.foundation_progress = min(max(self.foundation_progress, 0.0), 1.0)
        self._upgrade_qi_quality_for_layer()
        self.refresh_cultivation_rate()

    def refresh_cultivation_rate(self) -> None:
        self.cultivation_rate = self.qi_gathering_rate()

    def qi_gathering_rate(self) -> float:
        return self.qi_quality.qi_per_day * self.qi_type.gathering_modifier

    def _upgrade_qi_quality_for_layer(self) -> bool:
        if self.layer >= 6 and self.qi_quality.is_lower_than(QiQuality.THIN):
            self.qi_quality = QiQuality.THIN
            return True
        return False

    def ticks_until_breakthrough(self) -> float:
        if self.foundation_bar_active():
            remaining_ratio = max(1.0 - self.foundation_progress, 0.0)
            return remaining_ratio * FOUNDATION_FILL_TICKS
        if self.is_maxed_out():
            return float("inf")
        remaining = max(self.required_exp() - self.exp, 0)
        if self.cultivation_rate <= 0:
            return float("inf")
        return remaining / self.cultivation_rate

    def required_exp(self) -> float:
        base = (REALM_ORDER.index(self.realm) + 1) * 100
        layer_multiplier = max(self.layer, 1)
        stage_multiplier = (STAGE_ORDER.index(self.stage) + 1)
        return base * layer_multiplier * stage_multiplier

    def add_exp(self, ticks: int) -> List[str]:
        log: List[str] = []
        if self.is_maxed_out():
            self.exp = min(self.exp + self.cultivation_rate * ticks, self.required_exp())
            log.extend(self.update_foundation_progress(ticks))
            return log
        self.exp += self.cultivation_rate * ticks
        while self.exp >= self.required_exp():
            self.exp -= self.required_exp()
            log.append(self.advance_stage())
            if self.is_qi_condensation_cap():
                self.exp = min(self.exp, self.required_exp())
                break
            if self.is_maxed_out():
                self.exp = min(self.exp, self.required_exp())
                break
        log.extend(self.update_foundation_progress(ticks))
        return log

    def advance_stage(self) -> str:
        current_stage_index = STAGE_ORDER.index(self.stage)
        if current_stage_index + 1 < len(STAGE_ORDER):
            self.stage = STAGE_ORDER[current_stage_index + 1]
            return f"Advanced to {self.stage_label()} of {self.realm.value}."
        if self.realm == Realm.QI_CONDENSATION and self.layer < self.max_qi_layers:
            self.layer += 1
            self.stage = Stage.INITIAL
            return self._handle_layer_advance()
        if self.is_qi_condensation_cap():
            self.foundation_progress = max(self.foundation_progress, 0.0)
            return f"Reached {self.stage_label()} of {self.realm.value}. Foundation bar awakened."
        return self.breakthrough_realm()

    def _handle_layer_advance(self) -> str:
        if self._upgrade_qi_quality_for_layer():
            self.refresh_cultivation_rate()
            return (
                f"Advanced to {self.stage_label()} of {self.realm.value}. "
                f"Qi quality refined to {self.qi_quality.value} {self.qi_type.value}."
            )
        return f"Advanced to {self.stage_label()} of {self.realm.value}."

    def breakthrough_realm(self) -> str:
        realm_index = REALM_ORDER.index(self.realm)
        if realm_index + 1 < len(REALM_ORDER):
            tribulation = HeavenlyTribulation(self.realm, REALM_ORDER[realm_index + 1])
            outcome = tribulation.resolve()
            self.realm = tribulation.target_realm
            self.stage = Stage.INITIAL
            return outcome
        self.stage = Stage.PEAK
        if self.realm == Realm.QI_CONDENSATION:
            return f"Reached the pinnacle of {self.realm.value} (Peak {self.layer_ordinal()} layer)."
        return f"Reached the pinnacle of {self.realm.value} (Peak stage)."

    def layer_ordinal(self) -> str:
        suffix = "th"
        if not 10 <= self.layer % 100 <= 20:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(self.layer % 10, "th")
        return f"{self.layer}{suffix}"

    def stage_label(self) -> str:
        if self.realm == Realm.QI_CONDENSATION:
            return f"{self.stage.value} {self.layer_ordinal()} layer"
        return self.stage.value

    def is_maxed_out(self) -> bool:
        final_realm = REALM_ORDER[-1]
        if self.realm == final_realm:
            return self.stage == Stage.PEAK
        return False

    def is_qi_condensation_cap(self) -> bool:
        return self.realm == Realm.QI_CONDENSATION and self.layer >= self.max_qi_layers and self.stage == Stage.PEAK

    def foundation_bar_active(self) -> bool:
        return self.is_qi_condensation_cap()

    def update_foundation_progress(self, ticks: int) -> List[str]:
        if not self.foundation_bar_active():
            return []
        if self.foundation_progress >= 1.0:
            return []
        previous = self.foundation_progress
        increment = ticks / FOUNDATION_FILL_TICKS
        self.foundation_progress = min(1.0, self.foundation_progress + increment)
        if previous < 1.0 and self.foundation_progress >= 1.0:
            return ["Foundation bar complete—breakthrough chance has reached 100%."]
        return []

    def breakthrough_chance(self) -> float:
        if not self.foundation_bar_active():
            return 0.0
        base = 0.10
        bonus = 0.90 * self.foundation_progress
        return max(0.0, min(base + bonus, 1.0))

    def attempt_foundation_breakthrough(self) -> tuple[bool, str]:
        if not self.foundation_bar_active():
            return False, "You are not ready to break through yet."
        chance = self.breakthrough_chance()
        if random() <= chance:
            self.realm = Realm.FOUNDATION_ESTABLISHMENT
            self.stage = Stage.INITIAL
            self.layer = 1
            self.exp = 0.0
            self.foundation_progress = 0.0
            return True, "Breakthrough successful! You have reached Foundation Establishment."
        self.stage = Stage.LATE
        self.layer = self.max_qi_layers
        self.exp = 0.0
        self.foundation_progress = 0.0
        return False, "Breakthrough failed. Your foundation wavers; you return to Late 15th layer Qi Condensation."


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
class TalentSheet:
    physical_strength: float = 100.0
    constitution: float = 100.0
    agility: float = 100.0
    spiritual_power: float = 100.0
    perception: float = 100.0

    min_percent: ClassVar[float] = 50.0
    max_percent: ClassVar[float] = 125.0
    average_threshold: ClassVar[float] = 75.0
    genius_threshold: ClassVar[float] = 100.0

    def multiplier(self, value: float) -> float:
        return max(value, 0.0) / 100.0

    @classmethod
    def roll(cls) -> "TalentSheet":
        def roll_stat() -> float:
            return cls._clamp(uniform(cls.min_percent, cls.max_percent))

        return cls(
            physical_strength=roll_stat(),
            constitution=roll_stat(),
            agility=roll_stat(),
            spiritual_power=roll_stat(),
            perception=roll_stat(),
        )

    @classmethod
    def quality(cls, value: float) -> str:
        if value < cls.average_threshold:
            return "Trash"
        if value <= cls.genius_threshold:
            return "Average"
        return "Genius"

    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(cls.min_percent, min(value, cls.max_percent))


@dataclass
class CoreStats:
    physical_strength: float = 10.0
    constitution: float = 10.0
    agility: float = 10.0
    spiritual_power: float = 10.0
    perception: float = 10.0

    def effective(self, talents: TalentSheet) -> "CoreStats":
        return CoreStats(
            physical_strength=self.physical_strength * talents.multiplier(talents.physical_strength),
            constitution=self.constitution * talents.multiplier(talents.constitution),
            agility=self.agility * talents.multiplier(talents.agility),
            spiritual_power=self.spiritual_power * talents.multiplier(talents.spiritual_power),
            perception=self.perception * talents.multiplier(talents.perception),
        )


@dataclass
class SubStats:
    hp: float
    defense: float
    attack_speed: float
    evasion: float

    @staticmethod
    def from_effective(core: CoreStats) -> "SubStats":
        return SubStats(
            hp=core.constitution * 8,
            defense=core.constitution * 1.6,
            attack_speed=core.agility * 10,
            evasion=core.agility * 2,
        )


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
    core_stats: CoreStats = field(default_factory=CoreStats)
    talents: TalentSheet = field(default_factory=TalentSheet)
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

    def age_years(
        self, calendar: "GameCalendar", now: int | None = None, time_flow: float = 1.0
    ) -> float:
        now = now or int(time.time())
        days_lived = calendar.days_elapsed(self.birthday, now) * max(time_flow, 0.0)
        return days_lived / DAYS_PER_YEAR

    def effective_stats(self) -> CoreStats:
        return self.core_stats.effective(self.talents)

    def sub_stats(self) -> SubStats:
        return SubStats.from_effective(self.effective_stats())

    def lifespan_years(self) -> float:
        return REALM_LIFESPAN_YEARS.get(self.cultivation.realm, REALM_LIFESPAN_YEARS[Realm.QI_CONDENSATION])

    def remaining_lifespan_years(
        self, calendar: "GameCalendar", now: int | None = None, time_flow: float = 1.0
    ) -> float:
        return max(self.lifespan_years() - self.age_years(calendar, now, time_flow), 0.0)

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
            core_stats=CoreStats(**data.get("core_stats", {})),
            talents=TalentSheet(**data.get("talents", {})),
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

