# The Golden Vault — Discord bot

A 7-day, 50-floor treasure competition. One `/play` command opens a private button-driven interface; all other actions are buttons. Includes rules, help, leaderboard, random challenges, health, healing, expeditions, daily activities, workshop, bosses and a Royal Treasury.

## Deploy on Railway
1. Create a Railway Python service from this project and add a **persistent volume** mounted at `/data` (otherwise SQLite progress disappears after redeploy).
2. Set `DISCORD_TOKEN` to the bot token. Set `DATABASE_PATH=/data/golden_vault.db`. Set `EVENT_START` to the event start in ISO 8601 UTC format, e.g. `2026-11-22T00:00:00+00:00`. Set `EVENT_DAYS=7`.
3. Optional: set `GUILD_ID` to your test server's numeric ID to sync `/play` immediately. Otherwise global command sync can take time.
4. In Discord Developer Portal, invite the bot with `bot` and `applications.commands` scopes, and permissions to Send Messages and Embed Links. No privileged intents required.
5. Run `python main.py` locally with Python 3.11+ and `pip install -r requirements.txt` or deploy on Railway.

## Game rules and balance
- Event lasts 7 days from `EVENT_START`; the bot displays countdown and stops score-bearing play at the end. If `EVENT_START` is omitted, the event begins when the bot first starts and that start is saved in the DB.
- 50 floors; 2–4 random challenges per floor, a guardian every 10 floors. Floor progress never resets.
- 100 HP maximum, +10 HP every five minutes (including offline), wrong answers and timeouts -10 HP. At 0 HP, wait to regenerate or use a potion.
- Trivia/true-false: 10 seconds; patterns: 30 seconds; memory: 5-second reveal + 30 seconds to answer; lock: 60 seconds; paths: 60 seconds.
- Questions and puzzle values randomised, shuffled answers and per-player state. Challenges are private and server-validated; expired interactions cannot score.
- Keys: bronze, silver and gold. Chests award fixed score by tier (no lucky leaderboard jackpots). Gold is for upgrades and potions. Keys are for chests.
- Expeditions: repeatable 3–5 rooms, bank loot when leaving, risk half unbanked gold on defeat. First 3 expeditions per UTC day award Vault Score; further expeditions award gold/keys only.
- Daily tasks: five per UTC day; missed days remain accessible during the event through a day selector. Guardian: one per day; daily tasks are independent of the floor climb.
- Royal Treasury unlocks at Floor 50, grants one score-bearing trial per day, with catch-up days available.
- Leaderboard: Vault Score, then floor, then accuracy. All UI buttons are scoped to the player except the public `/play` command response (which is ephemeral).

## Notes
- This is a fully playable initial release, not a load-tested production system. Try it in a test server before opening the event.
- A small bundled, human-reviewed-style general knowledge question bank is provided; expand it substantially before a public competition. The puzzle generators add variety, but a fixed trivia bank can repeat.
- Discord cannot prevent screenshots or AI assistance. Ten-second timers make copying less convenient, not impossible.
- SQLite writes are transactional; one bot process is supported. Do not run multiple replicas against the same SQLite file.
