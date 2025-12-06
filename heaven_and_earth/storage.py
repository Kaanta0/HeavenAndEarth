import dataclasses
import os
import sys
from pathlib import Path
from typing import Dict

import tomli_w

if sys.version_info >= (3, 11):  # pragma: no cover - runtime guard for stdlib availability
    import tomllib  # type: ignore[attr-defined]
else:  # pragma: no cover
    import tomli as tomllib

from .models import Player, World, Zone


class PlayerRepository:
    def __init__(self, data_dir: str = ".data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "players.toml"
        if not self.path.exists():
            self.path.write_text("[players]\n", encoding="utf-8")

    def load_all(self) -> Dict[int, Player]:
        content = self.path.read_text(encoding="utf-8")
        raw = tomllib.loads(content) if content.strip() else {}
        players_data = raw.get("players", {})
        return {int(k): Player.from_dict(v) for k, v in players_data.items()}

    def save_all(self, players: Dict[int, Player]) -> None:
        serialisable = {str(uid): player.to_dict() for uid, player in players.items()}
        payload = {"players": serialisable}
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        os.replace(tmp_path, self.path)

    def create_player(self, players: Dict[int, Player], user_id: int, user_name: str) -> Player:
        player = Player(user_id=user_id, name=user_name)
        players[user_id] = player
        return player


class WorldRepository:
    def __init__(self, data_dir: str = ".data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "worlds.toml"
        if not self.path.exists():
            self.path.write_text("[worlds]\n[zones]\n", encoding="utf-8")

    def load_all(self) -> tuple[Dict[str, World], Dict[str, Zone]]:
        content = self.path.read_text(encoding="utf-8")
        raw = tomllib.loads(content) if content.strip() else {}
        worlds_data = raw.get("worlds", {})
        zones_data = raw.get("zones", {})
        worlds = {wid: World(**data) for wid, data in worlds_data.items()}
        zones = {zid: Zone(**data) for zid, data in zones_data.items()}
        return worlds, zones

    def save_all(self, worlds: Dict[str, World], zones: Dict[str, Zone]) -> None:
        payload = {
            "worlds": {wid: dataclasses.asdict(world) for wid, world in worlds.items()},
            "zones": {zid: dataclasses.asdict(zone) for zid, zone in zones.items()},
        }
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        os.replace(tmp_path, self.path)
