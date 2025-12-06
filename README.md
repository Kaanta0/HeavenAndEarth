# Heaven & Earth Discord RPG Bot

A xianxia cultivation-themed Discord RPG bot featuring automated time progression and rich profile views. This document explains gameplay features, commands, data storage, and how to run the bot.

## Features
- **Main menu**: `/main` opens an interactive view with a button for your profile.
- **Registration gate**: `/register` must be used once to create your character before other commands work.
- **Profile menu**: Tabbed embeds show overview, cultivation details, skills, inventory, equipment, and statistics. Sub-tabs refine each category (e.g., equipment slots, inventory sections, battle vs. longevity stats).
- **Tick-based progression**: Every 60 seconds is one in-game day (one tick). Cultivation experience and cultivation hours are applied automatically, both while the bot runs and for offline time.
- **Cultivation system**: Only the Qi Condensation realm remains; stages (Initial → Peak) advance automatically as experience accumulates. Realm breakthroughs beyond this are disabled.
- **Lifespan tracking**: Each realm grants a fixed lifespan and the profile displays remaining years based on your in-game age.
- **Persistent storage**: Player data is stored in TOML under `.data/players.toml`.

## Commands
- `/register`: Create your player profile. Required before using any other command.
- `/main`: Open the main menu. Buttons link to the profile view.
- `/profile`: Jump directly to your profile tabs and sub-tabs.

## Menus and Views
- **Main menu**: Entry point to the profile.
- **Profile tabs**:
  - *Overview*: Age (with birthday timestamp), remaining lifespan, current realm/stage, and cultivation progress.
  - *Cultivation*: Realms and stages with exp totals, ticks/time until breakthrough, and tribulation survivals.
  - *Skills*: Placeholder descriptions for combat/support/movement arts.
  - *Inventory*: Satchel and treasure sections.
  - *Equipment*: Weapon, armor, artifact, ring slots plus a combined "all" sub-tab.
  - *Statistics*: Battle stats (enemies defeated, tribulations survived) and longevity stats (hours cultivated, lifespan remaining).

## Tick System and Cultivation Flow
- **Tick cadence**: A background task runs every 60 seconds (one in-game day). Offline ticks are computed on startup using epoch timestamps so progress continues while the bot is offline.
- **Cultivation rate**: Default `1.0` exp per tick. Experience accumulates automatically; no manual input required.
- **Breakthroughs**: When required experience for a stage is exceeded, the player advances. Realm breakthroughs beyond Qi Condensation are blocked, so only stage advancements occur.

## Data and Configuration
- **Player data**: Stored at `.data/players.toml` (created automatically). Do not commit your live data; `.data/` is git-ignored.
- **Bot token**: Provide your Discord token in one of three ways:
  1. Environment variable `DISCORD_TOKEN`.
  2. `.env` file with `DISCORD_TOKEN=...` (dotenv is loaded on startup).
  3. `config.toml` with:
     ```toml
     [discord]
     token = "YOUR_DISCORD_BOT_TOKEN"
     ```

## Running the Bot
1. **Install dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure your token** using one of the methods above.
   - If you want to avoid global application-command rate limits during development, set `DISCORD_GUILD_ID` to a single guild ID. Commands will sync only to that guild.
   - Enable the **Message Content Intent** for your bot in the Discord Developer Portal (required because the bot requests this privileged intent).
3. **Run the bot**
   ```bash
   python bot.py
   ```
4. **Invite your bot** to a Discord server and use `/register` to start cultivating.

## Project Structure
- `bot.py`: Discord commands, UI views, and bot startup (including config loading).
- `heaven_and_earth/models.py`: Player, cultivation, stats, and equipment data models plus tick handling.
- `heaven_and_earth/storage.py`: TOML persistence for player data.
- `requirements.txt`: Python dependencies.

## Notes
- This is a gameplay scaffold; extend skills, inventory logic, and equipment effects as desired.
- Ticks and cultivation gains persist between restarts.
