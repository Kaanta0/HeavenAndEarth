import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from heaven_and_earth.calendar import CalendarRepository, GameCalendar
from heaven_and_earth.models import (
    Player,
    REALM_ORDER,
    SECONDS_PER_TICK,
    TalentSheet,
    World,
    Zone,
    slugify,
)
from heaven_and_earth.storage import PlayerRepository, WorldRepository

logging.basicConfig(level=logging.INFO)
load_dotenv()


class WorldService:
    def __init__(self) -> None:
        self.repo = WorldRepository()
        self.worlds: Dict[str, World] = {}
        self.zones: Dict[str, Zone] = {}

    def load(self) -> None:
        self.worlds, self.zones = self.repo.load_all()

    def save(self) -> None:
        self.repo.save_all(self.worlds, self.zones)

    def beginning_world(self) -> World | None:
        return next((world for world in self.worlds.values() if world.beginning), None)

    def beginning_zone(self) -> Zone | None:
        return next((zone for zone in self.zones.values() if zone.beginning), None)

    def get_world(self, world_id: str | None) -> World | None:
        if not world_id:
            return None
        return self.worlds.get(world_id)

    def get_zone(self, zone_id: str | None) -> Zone | None:
        if not zone_id:
            return None
        return self.zones.get(zone_id)

    def find_zone_id(self, world_id: str, name: str) -> str | None:
        slug = slugify(name)
        candidate = f"{world_id}-{slug}"
        if candidate in self.zones:
            return candidate
        for zone_id, zone in self.zones.items():
            if zone.world_id == world_id and zone.name.lower() == name.lower():
                return zone_id
        return None

    def create_world(self, name: str, role_id: int, beginning: bool, time_flow: float) -> World:
        world_id = slugify(name)
        if world_id in self.worlds:
            raise ValueError("A world with that name already exists")
        if beginning and any(world.beginning for world in self.worlds.values()):
            raise ValueError("Only one beginning world can exist")
        world = World(
            id=world_id,
            name=name,
            current_location_role_id=role_id,
            beginning=beginning,
            time_flow=time_flow if time_flow > 0 else 1.0,
        )
        self.worlds[world_id] = world
        self.save()
        return world

    def create_zone(
        self,
        world_id: str,
        name: str,
        channel_id: int,
        role_id: int,
        x_size: int,
        y_size: int,
        beginning: bool,
        time_flow: float,
    ) -> Zone:
        if world_id not in self.worlds:
            raise ValueError("World not found")
        if beginning and not self.worlds[world_id].beginning:
            raise ValueError("Beginning zones must be placed in the beginning world")
        if beginning and any(zone.beginning for zone in self.zones.values()):
            raise ValueError("Only one beginning zone can exist")
        zone_id = f"{world_id}-{slugify(name)}"
        if zone_id in self.zones:
            raise ValueError("A zone with that name already exists in this world")
        zone = Zone(
            id=zone_id,
            world_id=world_id,
            name=name,
            channel_id=channel_id,
            current_location_role_id=role_id,
            x_size=max(1, x_size),
            y_size=max(1, y_size),
            beginning=beginning,
            time_flow=time_flow if time_flow > 0 else 1.0,
        )
        self.zones[zone_id] = zone
        self.save()
        return zone

    def delete_world(self, world_id: str, player_service: Optional["PlayerService"] = None) -> tuple[World, List[Zone]]:
        world = self.worlds.pop(world_id, None)
        if not world:
            raise ValueError("World not found")
        removed_zones = [zone for zone in self.zones.values() if zone.world_id == world_id]
        for zone in removed_zones:
            self.zones.pop(zone.id, None)
        if player_service:
            player_service.handle_world_deleted(world_id, [zone.id for zone in removed_zones])
        self.save()
        return world, removed_zones

    def delete_zone(self, zone_id: str, player_service: Optional["PlayerService"] = None) -> Zone:
        zone = self.zones.pop(zone_id, None)
        if not zone:
            raise ValueError("Zone not found")
        if player_service:
            player_service.handle_zone_deleted(zone_id)
        self.save()
        return zone

    def get_zones_for_world(self, world_id: str) -> List[Zone]:
        return [zone for zone in self.zones.values() if zone.world_id == world_id]

    def effective_time_flow(self, player: Player) -> float:
        world_flow = 1.0
        zone_flow = 1.0
        world = self.get_world(player.world_id)
        zone = self.get_zone(player.zone_id)
        if world:
            world_flow = max(world.time_flow, 0.0) or 1.0
        if zone:
            zone_flow = max(zone.time_flow, 0.0) or 1.0
        return world_flow * zone_flow

    def clamp_position(self, player: Player) -> None:
        zone = self.get_zone(player.zone_id)
        if not zone:
            player.position_x = 0
            player.position_y = 0
            return
        player.position_x = min(max(player.position_x, 0), max(zone.x_size - 1, 0))
        player.position_y = min(max(player.position_y, 0), max(zone.y_size - 1, 0))

    def find_world_id(self, name: str) -> str | None:
        slug = slugify(name)
        if slug in self.worlds:
            return slug
        for world_id, world in self.worlds.items():
            if world.name.lower() == name.lower():
                return world_id
        return None

class PlayerService:
    def __init__(self, world_service: WorldService) -> None:
        self.repo = PlayerRepository()
        self.players: Dict[int, Player] = {}
        self.world_service = world_service

    def load(self) -> None:
        self.players = self.repo.load_all()
        for player in self.players.values():
            self.world_service.clamp_position(player)

    def save(self) -> None:
        self.repo.save_all(self.players)

    def is_registered(self, user: discord.abc.User) -> bool:
        return user.id in self.players

    def assign_beginning_location(self, player: Player) -> None:
        world = self.world_service.beginning_world()
        zone = self.world_service.beginning_zone()
        if world and zone and zone.world_id == world.id:
            player.world_id = world.id
            player.zone_id = zone.id
            player.position_x = 0
            player.position_y = 0
            self.world_service.clamp_position(player)

    def ensure_location(self, player: Player) -> None:
        if not player.world_id or not player.zone_id:
            self.assign_beginning_location(player)
        self.world_service.clamp_position(player)

    def register(self, user: discord.abc.User) -> Player:
        if self.is_registered(user):
            raise ValueError("Player already registered")
        player = self.repo.create_player(self.players, user.id, user.display_name)
        self.assign_beginning_location(player)
        self.save()
        return player

    def get_player(self, user: discord.abc.User) -> Optional[Player]:
        return self.players.get(user.id)

    def handle_zone_deleted(self, zone_id: str) -> None:
        changed = False
        for player in self.players.values():
            if player.zone_id == zone_id:
                player.zone_id = None
                player.position_x = 0
                player.position_y = 0
                self.ensure_location(player)
                changed = True
        if changed:
            self.save()

    def handle_world_deleted(self, world_id: str, removed_zone_ids: List[str]) -> None:
        changed = False
        affected_zones = set(removed_zone_ids)
        for player in self.players.values():
            if player.world_id == world_id:
                player.world_id = None
                player.zone_id = None
                player.position_x = 0
                player.position_y = 0
                self.ensure_location(player)
                changed = True
            elif player.zone_id in affected_zones:
                player.zone_id = None
                player.position_x = 0
                player.position_y = 0
                self.ensure_location(player)
                changed = True
        if changed:
            self.save()

    def _apply_time_progression(self, player: Player, real_ticks: int, now: int) -> tuple[List[str], bool]:
        logs: List[str] = []
        changed = False
        total_ticks = player.tick_buffer + real_ticks * self.world_service.effective_time_flow(player)
        ticks_to_apply = int(total_ticks)
        if ticks_to_apply:
            notes = player.apply_ticks(int(ticks_to_apply))
            logs.extend([f"{player.name}: {note}" for note in notes])
            changed = True
        new_buffer = total_ticks - ticks_to_apply
        if new_buffer != player.tick_buffer:
            player.tick_buffer = new_buffer
            changed = True
        player.last_tick_timestamp += int(real_ticks * SECONDS_PER_TICK)
        changed = True
        if player.last_tick_timestamp > now:
            player.last_tick_timestamp = now
        return logs, changed

    def apply_offline_ticks(self) -> List[str]:
        now = int(time.time())
        logs: List[str] = []
        changed = False
        for player in self.players.values():
            elapsed = max(now - player.last_tick_timestamp, 0)
            real_ticks = elapsed // SECONDS_PER_TICK
            if real_ticks:
                notes, player_changed = self._apply_time_progression(player, int(real_ticks), now)
                logs.extend(notes)
                changed = changed or player_changed
        if logs or changed:
            self.save()
        return logs

    def apply_live_tick(self) -> List[str]:
        now = int(time.time())
        logs: List[str] = []
        changed = False
        for player in self.players.values():
            elapsed = max(now - player.last_tick_timestamp, 0)
            real_ticks = max(int(elapsed // SECONDS_PER_TICK), 1)
            notes, player_changed = self._apply_time_progression(player, real_ticks, now)
            logs.extend(notes)
            changed = changed or player_changed
        if logs or changed:
            self.save()
        else:
            self.repo.save_all(self.players)
        return logs


PROFILE_SUBTABS = {
    "skills": [
        discord.SelectOption(label="Combat Arts", value="combat", description="Sword, spear, and fist forms"),
        discord.SelectOption(label="Support Arts", value="support", description="Alchemy, talismans, formations"),
        discord.SelectOption(label="Movement", value="movement", description="Lightfoot and cloud-riding"),
    ],
    "inventory": [
        discord.SelectOption(label="Satchel", value="satchel", description="Everyday items"),
        discord.SelectOption(label="Treasures", value="treasures", description="Rare finds and loot"),
    ],
    "equipment": [
        discord.SelectOption(label="Weapon", value="weapon", description="Blades, staves, and bows"),
        discord.SelectOption(label="Armor", value="armor", description="Robes, mail, and qi-shields"),
        discord.SelectOption(label="Artifact", value="artifact", description="Mystic tools"),
        discord.SelectOption(label="Ring", value="ring", description="Spatial or spirit rings"),
        discord.SelectOption(label="All", value="all", description="Show every slot"),
    ],
    "statistics": [
        discord.SelectOption(label="Battle", value="battle", description="Combat records"),
        discord.SelectOption(label="Longevity", value="longevity", description="Age and lifespan"),
    ],
    "cultivation": [
        discord.SelectOption(label="Breakthroughs", value="breakthroughs", description="Realm and stage progress"),
        discord.SelectOption(label="Rate", value="rate", description="Exp gain over time"),
    ],
}


class MainMenuView(discord.ui.View):
    def __init__(self, service: PlayerService, world_service: WorldService, calendar: GameCalendar):
        super().__init__(timeout=120)
        self.service = service
        self.world_service = world_service
        self.calendar = calendar

    @discord.ui.button(label="Profile", style=discord.ButtonStyle.primary)
    async def profile_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        player = self.service.get_player(interaction.user)
        if not player:
            await interaction.response.send_message(
                "You are not registered yet. Use /register to join the world.", ephemeral=True
            )
            return
        avatar_url = interaction.user.display_avatar.url
        await interaction.response.send_message(
            embed=build_profile_embed(
                player, self.calendar, "overview", None, avatar_url, self.world_service
            ),
            view=ProfileView(self.service, self.world_service, self.calendar, player, avatar_url),
            ephemeral=True,
        )

    @discord.ui.button(label="Travel", style=discord.ButtonStyle.secondary)
    async def travel_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        player = self.service.get_player(interaction.user)
        if not player:
            await interaction.response.send_message(
                "You are not registered yet. Use /register to join the world.", ephemeral=True
            )
            return
        await send_travel_panel(interaction, player, self.service, self.world_service)


class TabSelect(discord.ui.Select):
    def __init__(self, player: Player, view: "ProfileView"):
        options = [
            discord.SelectOption(label="Overview", value="overview", description="Stats, age, cultivation"),
            discord.SelectOption(label="Cultivation", value="cultivation", description="Realms and tribulations"),
            discord.SelectOption(label="Skills", value="skills", description="Talents and arts"),
            discord.SelectOption(label="Inventory", value="inventory", description="Items carried"),
            discord.SelectOption(label="Equipment", value="equipment", description="Currently equipped gear"),
            discord.SelectOption(label="Statistics", value="statistics", description="Battle and cultivation logs"),
        ]
        super().__init__(placeholder="Choose a profile tab", options=options)
        self.player = player
        self.profile_view = view

    async def callback(self, interaction: discord.Interaction):
        self.profile_view.current_tab = self.values[0]
        self.profile_view.update_subtabs()
        await interaction.response.edit_message(
            embed=build_profile_embed(
                self.player,
                self.profile_view.calendar,
                self.profile_view.current_tab,
                self.profile_view.current_subtab,
                self.profile_view.avatar_url,
                self.profile_view.world_service,
            ),
            view=self.profile_view,
        )


class SubTabSelect(discord.ui.Select):
    def __init__(self, view: "ProfileView", options: List[discord.SelectOption]):
        super().__init__(placeholder="Refine the view", options=options)
        self.profile_view = view

    async def callback(self, interaction: discord.Interaction):
        self.profile_view.current_subtab = self.values[0]
        await interaction.response.edit_message(
            embed=build_profile_embed(
                self.profile_view.player,
                self.profile_view.calendar,
                self.profile_view.current_tab,
                self.profile_view.current_subtab,
                self.profile_view.avatar_url,
                self.profile_view.world_service,
            ),
            view=self.profile_view,
        )


class ProfileView(discord.ui.View):
    def __init__(
        self,
        service: PlayerService,
        world_service: WorldService,
        calendar: GameCalendar,
        player: Player,
        avatar_url: Optional[str] = None,
    ):
        super().__init__(timeout=180)
        self.service = service
        self.world_service = world_service
        self.calendar = calendar
        self.player = player
        self.avatar_url = avatar_url
        self.current_tab: str = "overview"
        self.current_subtab: Optional[str] = None
        self.tab_select = TabSelect(player, self)
        self.add_item(self.tab_select)
        self.update_subtabs()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.player.user_id

    async def on_timeout(self) -> None:
        self.clear_items()

    def update_subtabs(self) -> None:
        for child in list(self.children):
            if isinstance(child, SubTabSelect):
                self.remove_item(child)
        options = PROFILE_SUBTABS.get(self.current_tab)
        if options:
            option_values = [opt.value for opt in options]
            if self.current_subtab not in option_values:
                self.current_subtab = option_values[0]
            self.add_item(SubTabSelect(self, options))
        else:
            self.current_subtab = None


def build_profile_embed(
    player: Player,
    calendar: GameCalendar,
    tab: str,
    subtab: Optional[str],
    avatar_url: Optional[str] = None,
    world_service: Optional[WorldService] = None,
) -> discord.Embed:
    now = int(time.time())
    effective_flow = 1.0
    world_name = "Unknown world"
    zone_name = "Unknown zone"
    if world_service:
        effective_flow = max(world_service.effective_time_flow(player), 0.0) or 1.0
        world = world_service.get_world(player.world_id)
        zone = world_service.get_zone(player.zone_id)
        world_name = world.name if world else world_name
        zone_name = zone.name if zone else zone_name

    day_seconds = SECONDS_PER_TICK / effective_flow if effective_flow > 0 else SECONDS_PER_TICK

    embed = discord.Embed(title="**__PROFILE__**", colour=discord.Colour.yellow())
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    if day_seconds < 1:
        day_length_text = f"{day_seconds * 1000:.0f} milliseconds"
    else:
        day_length_text = f"{day_seconds:.0f} seconds"
    embed.set_footer(text=f"One in-game day passes every {day_length_text}.")
    age_years = player.age_years(calendar, now)
    lifespan_years = player.lifespan_years()
    remaining_life = player.remaining_lifespan_years(calendar, now)
    cultivation = player.cultivation
    if tab == "overview":
        bar_length = 20
        required_exp = cultivation.required_exp()
        ratio = cultivation.exp / required_exp if required_exp else 0.0
        clamped_ratio = max(0.0, min(ratio, 1.0))
        filled = int(clamped_ratio * bar_length)
        progress_percent = max(0.0, min(ratio * 100, 100.0))
        progress_bar = "▓" * filled + "░" * (bar_length - filled)
        embed.description = (
            "**__DATE AND LOCATION__**\n"
            f"{calendar.format_date(now)}\n"
            f"Currently at {world_name} | {zone_name}\n\n"
            "**__AGE AND LIFESPAN__**\n"
            f"Age: {age_years:.2f} years old\n"
            f"Lifespan: {remaining_life:.2f} years remaining of {lifespan_years:.0f}\n"
            f"Birthday: {calendar.format_date(player.birthday)}\n\n"
            "**__CULTIVATION__**\n"
            f"Realm: {cultivation.realm.value}\n"
            f"Stage: {cultivation.stage_label()}\n"
            f"Rate: {cultivation.cultivation_rate:.1f} qi/day\n\n"
            f"Progress: {cultivation.exp:.0f}/{required_exp:.0f} qi\n"
            f"{progress_bar} {progress_percent:.0f}%"
        )
        talents = player.talents
        effective_stats = player.effective_stats()
        sub_stats = player.sub_stats()
        def format_talent(label: str, value: float) -> str:
            return f"{label}: {value:.0f}% ({TalentSheet.quality(value)})"
        embed.add_field(
            name="Talents",
            value=(
                f"{format_talent('Physical Strength', talents.physical_strength)}\n"
                f"{format_talent('Constitution', talents.constitution)}\n"
                f"{format_talent('Agility', talents.agility)}\n"
                f"{format_talent('Spiritual Power', talents.spiritual_power)}\n"
                f"{format_talent('Perception', talents.perception)}"
            ),
            inline=False,
        )
        embed.add_field(
            name="Stats",
            value=(
                f"Physical Strength: {effective_stats.physical_strength:.1f}\n"
                f"Constitution: {effective_stats.constitution:.1f}\n"
                f"Agility: {effective_stats.agility:.1f}\n"
                f"Spiritual Power: {effective_stats.spiritual_power:.1f}\n"
                f"Perception: {effective_stats.perception:.1f}"
            ),
            inline=False,
        )
        embed.add_field(
            name="Sub-Stats",
            value=(
                f"HP: {sub_stats.hp:.0f}\n"
                f"Defense: {sub_stats.defense:.0f}\n"
                f"ATK Speed: {sub_stats.attack_speed:.0f}\n"
                f"Evasion: {sub_stats.evasion:.0f}"
            ),
            inline=False,
        )
    elif tab == "cultivation":
        ticks_needed = cultivation.ticks_until_breakthrough()
        embed.description = (
            f"Realm: **{cultivation.realm.value}**\n"
            f"Stage: **{cultivation.stage_label()}**\n"
            f"Current qi: **{cultivation.exp:.1f}/{cultivation.required_exp():.1f}**\n"
            f"Rate: **{cultivation.cultivation_rate:.1f} qi/day**"
        )
        if subtab == "breakthroughs":
            embed.add_field(name="Next tribulation", value=f"{ticks_needed:.1f} days until chance to break through.", inline=False)
            embed.add_field(name="Realms", value=", ".join(realm.value for realm in REALM_ORDER), inline=False)
        elif subtab == "rate":
            days = ticks_needed if ticks_needed != float("inf") else float("inf")
            embed.add_field(
                name="Time until stage up",
                value=(
                    f"~{days:.0f} days at current rate."
                    if days != float("inf")
                    else "Blocked; increase cultivation rate."
                ),
                inline=False,
            )
            embed.add_field(name="Tribulations survived", value=str(player.stats.tribulations_survived), inline=False)
    elif tab == "skills":
        sub = subtab or "combat"
        skill_notes = {
            "combat": "Sword intent, spear momentum, and fist force will be tracked here.",
            "support": "Alchemy cauldrons, talisman brushwork, and formation flags await scripting.",
            "movement": "Cloud-riding, shadow steps, and lightning leaps belong here.",
        }
        embed.description = skill_notes.get(sub, skill_notes["combat"])
    elif tab == "inventory":
        header = "Treasures" if subtab == "treasures" else "Satchel"
        if player.inventory:
            embed.add_field(name=header, value="\n".join(f"• {item}" for item in player.inventory), inline=False)
        else:
            embed.add_field(name=header, value="Your pouch is empty.", inline=False)
    elif tab == "equipment":
        slots = player.equipment.items() if subtab in (None, "all") else [(subtab, player.equipment.get(subtab))]
        for key, slot in slots:
            if slot is None:
                continue
            item_name = slot.get("item") if isinstance(slot, dict) else getattr(slot, "item", None)
            desc = slot.get("description") if isinstance(slot, dict) else getattr(slot, "description", "")
            embed.add_field(
                name=slot.get("name", key.title()) if isinstance(slot, dict) else getattr(slot, "name"),
                value=item_name or desc or "Empty",
                inline=False,
            )
    elif tab == "statistics":
        stats = player.stats
        if subtab == "battle":
            embed.add_field(name="Enemies defeated", value=str(stats.enemies_defeated), inline=True)
            embed.add_field(name="Tribulations survived", value=str(stats.tribulations_survived), inline=True)
        else:
            embed.add_field(name="Hours cultivating", value=f"{stats.hours_cultivated:.2f}", inline=True)
            embed.add_field(
                name="Lifespan remaining",
                value=f"{remaining_life:.2f}/{lifespan_years:.0f} years",
                inline=True,
            )
    return embed


def render_minimap(player: Player, zone: Zone) -> str:
    width = min(zone.x_size, 15)
    height = min(zone.y_size, 16)
    start_x = max(0, min(player.position_x - width // 2, max(zone.x_size - width, 0)))
    start_y = max(0, min(player.position_y - height // 2, max(zone.y_size - height, 0)))
    grid: List[str] = []
    for y in range(height):
        row = []
        for x in range(width):
            global_x = start_x + x
            global_y = start_y + y
            row.append("🧭" if (global_x, global_y) == (player.position_x, player.position_y) else "▫️")
        grid.append("".join(row))
    return "\n".join(grid)


def build_travel_embed(player: Player, world: World, zone: Zone, world_service: WorldService) -> discord.Embed:
    embed = discord.Embed(title="Travel", colour=discord.Colour.green())
    embed.add_field(name="World", value=world.name, inline=True)
    embed.add_field(name="Zone", value=zone.name, inline=True)
    embed.add_field(name="Coordinates", value=f"({player.position_x}, {player.position_y})", inline=False)
    embed.add_field(
        name="Time Flow",
        value=f"x{world_service.effective_time_flow(player):.2f} (world {world.time_flow}x, zone {zone.time_flow}x)",
        inline=False,
    )
    minimap = render_minimap(player, zone)
    embed.description = minimap
    return embed


class TravelView(discord.ui.View):
    def __init__(self, service: PlayerService, world_service: WorldService, player: Player):
        super().__init__(timeout=180)
        self.service = service
        self.world_service = world_service
        self.player = player

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.player.user_id

    async def on_timeout(self) -> None:
        self.clear_items()

    async def move(self, dx: int, dy: int, interaction: discord.Interaction) -> None:
        zone = self.world_service.get_zone(self.player.zone_id)
        world = self.world_service.get_world(self.player.world_id)
        if not zone or not world:
            await interaction.response.send_message("You are not in a valid location.", ephemeral=True)
            return
        self.player.position_x += dx
        self.player.position_y += dy
        self.world_service.clamp_position(self.player)
        self.player.stats.steps_travelled += abs(dx) + abs(dy)
        self.service.save()
        await interaction.response.edit_message(
            embed=build_travel_embed(self.player, world, zone, self.world_service), view=self
        )

    @discord.ui.button(label="↑", style=discord.ButtonStyle.primary)
    async def up(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.move(0, -1, interaction)

    @discord.ui.button(label="←", style=discord.ButtonStyle.secondary)
    async def left(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.move(-1, 0, interaction)

    @discord.ui.button(label="→", style=discord.ButtonStyle.secondary)
    async def right(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.move(1, 0, interaction)

    @discord.ui.button(label="↓", style=discord.ButtonStyle.primary)
    async def down(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.move(0, 1, interaction)



async def send_travel_panel(
    interaction: discord.Interaction, player: Player, service: PlayerService, world_service: WorldService
) -> None:
    service.ensure_location(player)
    world = world_service.get_world(player.world_id)
    zone = world_service.get_zone(player.zone_id)
    if not world or not zone:
        await interaction.response.send_message(
            "No valid location available. Create a beginning world and zone first.", ephemeral=True
        )
        return
    if interaction.channel_id != zone.channel_id:
        channel_hint = None
        if interaction.guild:
            channel = interaction.guild.get_channel(zone.channel_id)
            if channel:
                channel_hint = channel.mention
        await interaction.response.send_message(
            (
                f"Travel can only be used in your current zone channel{f' ({channel_hint})' if channel_hint else ''}."
            ),
            ephemeral=True,
        )
        return
    world_service.clamp_position(player)
    service.save()
    await interaction.response.send_message(
        embed=build_travel_embed(player, world, zone, world_service),
        view=TravelView(service, world_service, player),
        ephemeral=True,
    )


class HeavenAndEarthBot(commands.Bot):
    def __init__(self, *, sync_guild_id: Optional[int] = None, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents, **kwargs)
        self.calendar_repo = CalendarRepository()
        self.calendar = GameCalendar(self.calendar_repo.load_or_create_start())
        self.worlds = WorldService()
        self.service = PlayerService(self.worlds)
        self.sync_guild_id = sync_guild_id

    async def setup_hook(self) -> None:
        self.worlds.load()
        self.service.load()
        offline_logs = self.service.apply_offline_ticks()
        for note in offline_logs:
            logging.info("%s", note)
        self.tick_loop.start()
        if self.sync_guild_id:
            guild = discord.Object(id=self.sync_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Synced %s commands to guild %s", len(synced), self.sync_guild_id)
        else:
            synced = await self.tree.sync()
            logging.info("Synced %s global commands", len(synced))

    async def on_ready(self):
        logging.info("Logged in as %s", self.user)

    @tasks.loop(seconds=60)
    async def tick_loop(self):
        logs = self.service.apply_live_tick()
        if logs:
            for note in logs:
                logging.info(note)

    @tick_loop.before_loop
    async def before_tick_loop(self):
        await self.wait_until_ready()


sync_guild_id: Optional[int] = None
sync_guild_env = os.getenv("DISCORD_GUILD_ID")
if sync_guild_env:
    try:
        sync_guild_id = int(sync_guild_env)
    except ValueError:
        logging.warning("Invalid DISCORD_GUILD_ID provided; falling back to global command sync")

bot = HeavenAndEarthBot(sync_guild_id=sync_guild_id)


@bot.tree.command(name="main", description="Open the main menu for Heaven and Earth")
async def main_menu(interaction: discord.Interaction):
    player = bot.service.get_player(interaction.user)
    if not player:
        await interaction.response.send_message(
            "You are not registered yet. Use /register to begin cultivating.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        embed=discord.Embed(title="Heaven & Earth", description="Choose your path."),
        view=MainMenuView(bot.service, bot.worlds, bot.calendar),
        ephemeral=True,
    )


@bot.tree.command(name="profile", description="Show your cultivation profile")
async def profile(interaction: discord.Interaction):
    player = bot.service.get_player(interaction.user)
    if not player:
        await interaction.response.send_message(
            "You are not registered yet. Use /register to see your profile.", ephemeral=True
        )
        return
    avatar_url = interaction.user.display_avatar.url
    await interaction.response.send_message(
        embed=build_profile_embed(
            player, bot.calendar, "overview", None, avatar_url, bot.worlds
        ),
        view=ProfileView(bot.service, bot.worlds, bot.calendar, player, avatar_url),
        ephemeral=True,
    )


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(
    name="create_world",
    description="Create a world with its own location role and time flow",
)
async def create_world(
    interaction: discord.Interaction,
    name: str,
    current_location_role: discord.Role,
    beginning_world: bool,
    time_flow: Optional[float] = 1.0,
):
    try:
        world = bot.worlds.create_world(name, current_location_role.id, beginning_world, time_flow or 1.0)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    await interaction.response.send_message(
        f"World **{world.name}** created with role <@&{world.current_location_role_id}>. Time flow: x{world.time_flow}.",
        ephemeral=True,
    )


@create_world.autocomplete("name")
async def world_name_autocomplete(interaction: discord.Interaction, current: str):
    choices = []
    if current:
        slug = slugify(current)
        choices.append(app_commands.Choice(name=current, value=current))
        if slug != current:
            choices.append(app_commands.Choice(name=slug, value=slug))
    return choices[:25]


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(
    name="create_zone",
    description="Create a zone within an existing world",
)
async def create_zone(
    interaction: discord.Interaction,
    world_name: str,
    name: str,
    channel: discord.TextChannel,
    current_location_role: discord.Role,
    x_size: int,
    y_size: int,
    beginning_zone: bool,
    time_flow: Optional[float] = 1.0,
):
    world_id = bot.worlds.find_world_id(world_name)
    if not world_id:
        await interaction.response.send_message("World not found.", ephemeral=True)
        return
    try:
        zone = bot.worlds.create_zone(
            world_id,
            name,
            channel.id,
            current_location_role.id,
            x_size,
            y_size,
            beginning_zone,
            time_flow or 1.0,
        )
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    await interaction.response.send_message(
        (
            f"Zone **{zone.name}** created in **{bot.worlds.worlds[world_id].name}**. "
            f"Role: <@&{zone.current_location_role_id}> Channel: {channel.mention}. "
            f"Size: {zone.x_size}x{zone.y_size}. Time flow x{zone.time_flow}."
        ),
        ephemeral=True,
    )


@create_zone.autocomplete("world_name")
async def world_choice_autocomplete(interaction: discord.Interaction, current: str):
    matches = []
    for world in bot.worlds.worlds.values():
        if current.lower() in world.name.lower():
            matches.append(app_commands.Choice(name=world.name, value=world.name))
    return matches[:25]


@create_zone.autocomplete("name")
async def zone_name_autocomplete(_: discord.Interaction, current: str):
    return [app_commands.Choice(name=current, value=current)][:25]


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(
    name="delete_world",
    description="Delete a world and its zones",
)
async def delete_world(interaction: discord.Interaction, world_name: str):
    world_id = bot.worlds.find_world_id(world_name)
    if not world_id:
        await interaction.response.send_message("World not found.", ephemeral=True)
        return
    try:
        world, removed_zones = bot.worlds.delete_world(world_id, bot.service)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    zone_list = ", ".join(zone.name for zone in removed_zones) if removed_zones else "None"
    await interaction.response.send_message(
        f"World **{world.name}** deleted. Removed zones: {zone_list}.",
        ephemeral=True,
    )


@delete_world.autocomplete("world_name")
async def delete_world_autocomplete(interaction: discord.Interaction, current: str):
    matches = []
    for world in bot.worlds.worlds.values():
        if current.lower() in world.name.lower():
            matches.append(app_commands.Choice(name=world.name, value=world.name))
    return matches[:25]


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(
    name="delete_zone",
    description="Delete a zone from a world",
)
async def delete_zone(interaction: discord.Interaction, world_name: str, zone_name: str):
    world_id = bot.worlds.find_world_id(world_name)
    if not world_id:
        await interaction.response.send_message("World not found.", ephemeral=True)
        return
    zone_id = bot.worlds.find_zone_id(world_id, zone_name)
    if not zone_id:
        await interaction.response.send_message("Zone not found in that world.", ephemeral=True)
        return
    try:
        zone = bot.worlds.delete_zone(zone_id, bot.service)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    world = bot.worlds.worlds.get(world_id)
    world_display = world.name if world else world_name
    await interaction.response.send_message(
        f"Zone **{zone.name}** removed from **{world_display}**.",
        ephemeral=True,
    )


@delete_zone.autocomplete("world_name")
async def delete_zone_world_autocomplete(interaction: discord.Interaction, current: str):
    matches = []
    for world in bot.worlds.worlds.values():
        if current.lower() in world.name.lower():
            matches.append(app_commands.Choice(name=world.name, value=world.name))
    return matches[:25]


@delete_zone.autocomplete("zone_name")
async def delete_zone_autocomplete(interaction: discord.Interaction, current: str):
    world_name = interaction.namespace.world_name
    world_id = bot.worlds.find_world_id(world_name)
    if not world_id:
        return []
    matches = []
    for zone in bot.worlds.zones.values():
        if zone.world_id == world_id and current.lower() in zone.name.lower():
            matches.append(app_commands.Choice(name=zone.name, value=zone.name))
    return matches[:25]


@bot.tree.command(name="travel", description="Open the travel minimap")
async def travel(interaction: discord.Interaction):
    player = bot.service.get_player(interaction.user)
    if not player:
        await interaction.response.send_message(
            "You are not registered yet. Use /register to begin cultivating.", ephemeral=True
        )
        return
    await send_travel_panel(interaction, player, bot.service, bot.worlds)


@bot.tree.command(name="register", description="Register as a cultivator and begin tracking your journey")
async def register(interaction: discord.Interaction):
    if bot.service.is_registered(interaction.user):
        await interaction.response.send_message(
            "You are already registered. Use /main to open your menu.", ephemeral=True
        )
        return
    player = bot.service.register(interaction.user)
    await interaction.response.send_message(
        embed=discord.Embed(
            title="__**A NEW CULTIVATOR AWAKENS**__",
            description=(
                f"Welcome to the Nine Heavens, {interaction.user.mention} !\n"
                "Your destiny is now bound to the heavens. Embrace it or free yourself from it's grasp.\n\n"
                "Use **/main** to begin"
            ),
            colour=discord.Colour.green(),
        ),
        ephemeral=True,
    )


def run():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        config_path = Path("config.toml")
        if config_path.exists():
            import sys

            if sys.version_info >= (3, 11):  # pragma: no cover - stdlib availability
                import tomllib
            else:  # pragma: no cover
                import tomli as tomllib

            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            token = config.get("discord", {}).get("token")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required in environment, .env, or config.toml")
    bot.run(token)


if __name__ == "__main__":
    run()
