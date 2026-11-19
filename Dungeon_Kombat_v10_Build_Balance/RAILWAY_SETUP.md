# Railway deployment — corrected package

The previous ZIP had all Python files inside `dungeon_master_v14/`. If Railway's start command runs `/app/main.py` while `dungeon_master_engine.py` remains inside that subfolder, the import fails.

This package places **main.py, bot.py, dungeon_master_engine.py and combat.py at the same root level**. Upload the *contents* of this folder to the root of your GitHub repository, not a parent folder.

Railway setup:
1. Deploy this repository, with Root Directory unset (or `/`).
2. Start command: `python main.py` (also configured in `railway.json`).
3. Set `DISCORD_TOKEN` to your bot token.
4. If using a mounted volume at `/data`, set `DB_PATH=/data/dungeon_master.sqlite3` so player data survives redeploys.
5. Configure `EVENT_START` (ISO 8601 with timezone), `EVENT_DAYS` and optional `GUILD_ID` as required.
6. Deploy **one** worker replica only, to avoid duplicate background invasion scheduling.

If your Railway project uses a manually configured start command, it overrides the Procfile; update it to `python main.py`. If the repository has a custom Dockerfile, make sure it copies all five Python files to `/app`.

This is a packaging/import fix, not a new gameplay balance revision.
