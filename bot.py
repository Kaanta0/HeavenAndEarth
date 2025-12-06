import logging
import os
import time
from pathlib import Path
from random import randint
from typing import Dict, List, Optional

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from heaven_and_earth.models import Player, REALM_ORDER
from heaven_and_earth.storage import PlayerRepository

logging.basicConfig(level=logging.INFO)
load_dotenv()


class PlayerService:
    def __init__(self) -> None:
        self.repo = PlayerRepository()
        self.players: Dict[int, Player] = {}

    def load(self) -> None:
        self.players = self.repo.load_all()

    def save(self) -> None:
        self.repo.save_all(self.players)

    def is_registered(self, user: discord.abc.User) -> bool:
        return user.id in self.players

    def register(self, user: discord.abc.User) -> Player:
        if self.is_registered(user):
            raise ValueError("Player already registered")
        player = self.repo.create_player(self.players, user.id, user.display_name)
        self.save()
        return player

    def get_player(self, user: discord.abc.User) -> Optional[Player]:
        return self.players.get(user.id)

    def apply_offline_ticks(self) -> List[str]:
        now = int(time.time())
        logs: List[str] = []
        for player in self.players.values():
            elapsed = max(now - player.last_tick_timestamp, 0)
            ticks = elapsed // 60
            if ticks:
                notes = player.apply_ticks(int(ticks))
                logs.extend([f"{player.name}: {note}" for note in notes])
        if logs:
            self.save()
        return logs

    def apply_live_tick(self) -> List[str]:
        logs: List[str] = []
        for player in self.players.values():
            notes = player.apply_ticks(1)
            logs.extend([f"{player.name}: {note}" for note in notes])
        self.save()
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
        discord.SelectOption(label="Journey", value="journey", description="Travel and time"),
    ],
    "cultivation": [
        discord.SelectOption(label="Breakthroughs", value="breakthroughs", description="Realm and stage progress"),
        discord.SelectOption(label="Rate", value="rate", description="Exp gain over time"),
    ],
}


class MainMenuView(discord.ui.View):
    def __init__(self, service: PlayerService):
        super().__init__(timeout=120)
        self.service = service

    @discord.ui.button(label="Profile", style=discord.ButtonStyle.primary)
    async def profile_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        player = self.service.get_player(interaction.user)
        if not player:
            await interaction.response.send_message(
                "You are not registered yet. Use /register to join the world.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=build_profile_embed(player, "overview", None),
            view=ProfileView(self.service, player),
            ephemeral=True,
        )

    @discord.ui.button(label="Travel", style=discord.ButtonStyle.success)
    async def travel_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        player = self.service.get_player(interaction.user)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Choose a destination",
                description="Step onto the path. Distance travelled is recorded even while cultivating.",
            ),
            view=TravelView(self.service, player),
            ephemeral=True,
        )


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
            embed=build_profile_embed(self.player, self.profile_view.current_tab, self.profile_view.current_subtab),
            view=self.profile_view,
        )


class SubTabSelect(discord.ui.Select):
    def __init__(self, view: "ProfileView", options: List[discord.SelectOption]):
        super().__init__(placeholder="Refine the view", options=options)
        self.profile_view = view

    async def callback(self, interaction: discord.Interaction):
        self.profile_view.current_subtab = self.values[0]
        await interaction.response.edit_message(
            embed=build_profile_embed(self.profile_view.player, self.profile_view.current_tab, self.profile_view.current_subtab),
            view=self.profile_view,
        )


class ProfileView(discord.ui.View):
    def __init__(self, service: PlayerService, player: Player):
        super().__init__(timeout=180)
        self.service = service
        self.player = player
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


class DestinationSelect(discord.ui.Select):
    def __init__(self, view: "TravelView"):
        options = [
            discord.SelectOption(label="Cloudy Ridge", value="Cloudy Ridge"),
            discord.SelectOption(label="Spirit River", value="Spirit River"),
            discord.SelectOption(label="Ancient Battlefield", value="Ancient Battlefield"),
            discord.SelectOption(label="Sect Library", value="Sect Library"),
        ]
        super().__init__(placeholder="Pick a destination", options=options)
        self.travel_view = view

    async def callback(self, interaction: discord.Interaction):
        self.travel_view.destination = self.values[0]
        await interaction.response.edit_message(embed=self.travel_view.status_embed(), view=self.travel_view)


class TravelView(discord.ui.View):
    def __init__(self, service: PlayerService, player: Player):
        super().__init__(timeout=120)
        self.service = service
        self.player = player
        self.destination: str = "Cloudy Ridge"
        self.add_item(DestinationSelect(self))

    def status_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Travelling",
            description=f"Destination: **{self.destination}**\nSteps taken: **{self.player.stats.steps_travelled}**",
        )
        embed.set_footer(text="Travel increases journey statistics.")
        return embed

    @discord.ui.button(label="Embark", style=discord.ButtonStyle.primary)
    async def embark(self, interaction: discord.Interaction, _: discord.ui.Button):
        distance = randint(10, 50)
        note = self.player.record_travel(distance, self.destination)
        self.service.save()
        embed = self.status_embed()
        embed.add_field(name="Journey", value=note, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)


def build_profile_embed(player: Player, tab: str, subtab: Optional[str]) -> discord.Embed:
    embed = discord.Embed(title=f"{player.name}'s Profile", colour=discord.Colour.blue())
    embed.set_footer(text="Cultivation advances every 60 seconds.")
    now = int(time.time())
    age_years = player.age_years(now)
    cultivation = player.cultivation
    if tab == "overview":
        embed.description = (
            f"Age: **{age_years:.2f}** years\n"
            f"Birthday: <t:{player.birthday}:D>\n"
            f"Cultivation: **{cultivation.stage.value} {cultivation.realm.value}**\n"
            f"Progress: {cultivation.exp:.0f}/{cultivation.required_exp():.0f} exp"
        )
    elif tab == "cultivation":
        ticks_needed = cultivation.ticks_until_breakthrough()
        embed.description = (
            f"Realm: **{cultivation.realm.value}**\n"
            f"Stage: **{cultivation.stage.value}**\n"
            f"Current exp: **{cultivation.exp:.1f}/{cultivation.required_exp():.1f}**\n"
            f"Rate: **{cultivation.cultivation_rate:.1f} exp/tick**"
        )
        if subtab == "breakthroughs":
            embed.add_field(name="Next tribulation", value=f"{ticks_needed:.1f} ticks until chance to break through.", inline=False)
            embed.add_field(name="Realms", value=", ".join(realm.value for realm in REALM_ORDER), inline=False)
        elif subtab == "rate":
            hours = ticks_needed / 60 if ticks_needed != float("inf") else float("inf")
            embed.add_field(name="Time until stage up", value=f"~{hours:.2f} hours at current rate." if hours != float("inf") else "Blocked; increase cultivation rate.", inline=False)
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
            embed.add_field(name="Steps travelled", value=str(stats.steps_travelled), inline=True)
    return embed


class HeavenAndEarthBot(commands.Bot):
    def __init__(self, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents, **kwargs)
        self.service = PlayerService()

    async def setup_hook(self) -> None:
        self.service.load()
        offline_logs = self.service.apply_offline_ticks()
        for note in offline_logs:
            logging.info("%s", note)
        self.tick_loop.start()
        await self.tree.sync()

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


bot = HeavenAndEarthBot()


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
        view=MainMenuView(bot.service),
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
    await interaction.response.send_message(
        embed=build_profile_embed(player, "overview", None),
        view=ProfileView(bot.service, player),
        ephemeral=True,
    )


@bot.tree.command(name="register", description="Register as a cultivator and begin tracking your journey")
async def register(interaction: discord.Interaction):
    if bot.service.is_registered(interaction.user):
        await interaction.response.send_message(
            "You are already registered. Use /main to open your menu.", ephemeral=True
        )
        return
    player = bot.service.register(interaction.user)
    await interaction.response.send_message(
        f"Welcome, {player.name}! Your cultivation journey has begun.", ephemeral=True
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
