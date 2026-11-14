# Dungeon Kombat v12 — Medieval Castle Menu

**Only player-facing slash command: `/play`.** Every game function is accessible through private Discord buttons, dropdowns, and modal forms. All game data uses the same SQLite database and additive migrations as v11.

## Menus
- `/play` → Enter Dungeon, My Fighter, Blacksmith, Gather Resources, Treasury, Championship Arena, Rankings, Arena Score, Rules & Dates, Create Fighter.
- My Fighter → View Fighter, Allocate Stats (select attribute, type 1–30), Appearance & Weapon, Choose Skill, Reset Stats (confirmation).
- Blacksmith → Basic Upgrades, Advanced Forging, Enchant Equipment, Treasury.
- Gather Resources → Gather Resources (choose activity), Check Stamina.
- Dungeon battle → Attack, Defend, Special, Heal, Focus. After battle → Next Floor / Retry Floor and Exit Dungeon.
- Arena → five challenges, each with tactical buttons.

The castle, dungeon and arena artwork is rendered locally with medieval stonework, torchlight, heraldic banners, parchment, and serif lettering. No remote images are required.

## Railway
Upload the *contents* of this package directly to your GitHub repository root (not an enclosing ZIP folder). Set `DISCORD_TOKEN`, `GUILD_ID`, `EVENT_START_DATE` (`2026-11-14` to start on 14 November UTC), and `DATABASE_PATH=/data/dungeon_kombat.db`. Mount a persistent Railway volume at `/data`. Start command: `python main.py`.

Do not reset or delete your existing database when upgrading. Existing fighter records and arena scores are retained.

## Verification
Python syntax compilation passed. Live Discord button interactions could not be tested in this environment because `discord.py` is not installed and package installation is unavailable. Test on Railway before public launch.
