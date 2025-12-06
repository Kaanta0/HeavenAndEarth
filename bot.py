import logging
import os
import time
from typing import Dict, List

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from heaven_and_earth.models import Player
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

    def get_player(self, user: discord.abc.User) -> Player:
        return self.repo.get_or_create(self.players, user.id, user.display_name)

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


class MainMenuView(discord.ui.View):
    def __init__(self, service: PlayerService):
        super().__init__(timeout=120)
        self.service = service

    @discord.ui.button(label="Profile", style=discord.ButtonStyle.primary)
    async def profile_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        player = self.service.get_player(interaction.user)
        await interaction.response.send_message(embed=build_profile_embed(player, "overview"), view=ProfileView(self.service, player), ephemeral=True)

    @discord.ui.button(label="Travel", style=discord.ButtonStyle.success)
    async def travel_button(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "The roads wind through mountains and mystic rivers. Travel events will be added soon!",
            ephemeral=True,
        )


class TabSelect(discord.ui.Select):
    def __init__(self, player: Player):
        options = [
            discord.SelectOption(label="Overview", value="overview", description="Stats, age, cultivation"),
            discord.SelectOption(label="Skills", value="skills", description="Talents and arts"),
            discord.SelectOption(label="Inventory", value="inventory", description="Items carried"),
            discord.SelectOption(label="Equipment", value="equipment", description="Currently equipped gear"),
            discord.SelectOption(label="Statistics", value="statistics", description="Battle and cultivation logs"),
        ]
        super().__init__(placeholder="Choose a profile tab", options=options)
        self.player = player

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=build_profile_embed(self.player, self.values[0]), view=self.view)


class ProfileView(discord.ui.View):
    def __init__(self, service: PlayerService, player: Player):
        super().__init__(timeout=180)
        self.service = service
        self.player = player
        self.add_item(TabSelect(player))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.player.user_id

    async def on_timeout(self) -> None:
        self.clear_items()


def build_profile_embed(player: Player, tab: str) -> discord.Embed:
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
    elif tab == "skills":
        embed.description = "Skills system is ready for expansion. Placeholder techniques await your script."  # placeholder
    elif tab == "inventory":
        if player.inventory:
            embed.add_field(name="Inventory", value="\n".join(f"• {item}" for item in player.inventory), inline=False)
        else:
            embed.add_field(name="Inventory", value="Your pouch is empty.", inline=False)
    elif tab == "equipment":
        for key, slot in player.equipment.items():
            item_name = slot.get("item") if isinstance(slot, dict) else getattr(slot, "item", None)
            desc = slot.get("description") if isinstance(slot, dict) else getattr(slot, "description", "")
            embed.add_field(name=slot.get("name", key.title()) if isinstance(slot, dict) else getattr(slot, "name"), value=item_name or desc or "Empty", inline=False)
    elif tab == "statistics":
        stats = player.stats
        embed.add_field(name="Enemies defeated", value=str(stats.enemies_defeated), inline=True)
        embed.add_field(name="Tribulations survived", value=str(stats.tribulations_survived), inline=True)
        embed.add_field(name="Hours cultivating", value=f"{stats.hours_cultivated:.2f}", inline=True)
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
    bot.service.save()
    await interaction.response.send_message(
        embed=discord.Embed(title="Heaven & Earth", description="Choose your path."),
        view=MainMenuView(bot.service),
        ephemeral=True,
    )


@bot.tree.command(name="profile", description="Show your cultivation profile")
async def profile(interaction: discord.Interaction):
    player = bot.service.get_player(interaction.user)
    bot.service.save()
    await interaction.response.send_message(embed=build_profile_embed(player, "overview"), view=ProfileView(bot.service, player), ephemeral=True)


def run():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required in environment or .env file")
    bot.run(token)


if __name__ == "__main__":
    run()
