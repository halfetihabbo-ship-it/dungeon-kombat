# Dungeon Climber — Discord bot (Python / Railway)

A playable **first implementation** of the agreed 7-day hybrid idle dungeon game.
The balancing simulator is included separately for reference; its predicted floor
numbers are **not guaranteed** by this new implementation.

## Setup

1. Create a Discord application and bot in the Discord Developer Portal.
2. Invite the bot to your server with the `bot` and `applications.commands` scopes;
   grant `Send Messages`, `Embed Links`, and `Use Application Commands` permissions.
3. Upload this folder to GitHub and connect the repository to a Railway service.
4. In Railway, set `DISCORD_TOKEN` to your bot token and `GUILD_ID` to your test server ID.
5. **Create a Railway Volume mounted at `/data`**. Set `DATABASE_PATH=/data/dungeon_climber.db`.
   Without the volume, player progress may be lost on redeploy.
6. Optionally set `EVENT_START_UTC=2026-11-22T18:00:00Z` (change to your date).
   If omitted, the first player's character creation starts the seven-day timer.
7. Start the service (`python bot.py`). Commands may take a little time to sync.

## Commands

- `/play` — create a Berserker, Guardian, or Rogue; then opens the private button UI.
- `/leaderboard` — highest floor reached; earliest arrival wins a tie.
- `/guide` — instructions.
- `/eventstatus` — start/end timer.

## Main game

- A battle is processed every 15 seconds **when the player checks in**; elapsed
  time is caught up from the saved timestamp, capped at eight hours. No background
  task per player is needed.
- The hero climbs automatically. Every 50th floor requires manual boss actions.
- Failed floors earn resources; repeated failures trigger five rounds of farming.
- Milestone chests appear every ten floors; vault keys from major milestones.
- Weapon and armour drops scale with floor; upgrades transfer to replacement gear.
- Blacksmith has +1 to +10 upgrades and uncapped Refinement after Floor 100.
- Daily Bounty, Gauntlet, Vault and event leaderboard are available in the UI.

## Important before public launch

This is a **playable beta**, not a production-verified version of your previous bot.
It has not been connected to your Discord server or Railway deployment. The
existing abstract simulator and this concrete combat implementation have different
mechanics; test actual floor pacing, equipment and bosses with players before
announcing prizes.

**Persistence:** SQLite on a Railway Volume is suitable for one bot process.
Do not run multiple bot replicas against the same SQLite database.

**Security:** Never commit a real Discord token. Use Railway Variables.

**Event reset:** This beta intentionally has no public reset command. For a
new event, back up the database and create a fresh database or use a separate
Railway volume. Avoid deleting active player data without a backup.

**Known scope limitations:** Bosses use a six-turn interactive combat model, not
full animated battles; equipment is automatically equipped or dismantled (no
inventory browsing), and classes are simple stat variants. There is no
independent global background combat loop; progression is calculated at check-in.

## New: Single command, public role panel and prizes

**The only slash command is `/play`.** Use `/play` to create/open your private game UI.
A server administrator with **Manage Server** can run `/play panel:True` in the
announcement channel to post a **public, persistent join panel** with a large
headline, a green **JOIN DUNGEON CLIMBER** button, help and leaderboard buttons.
Joining via the button opens a **private** class-selection menu; players do not
need to use slash commands. The join panel survives bot restarts.

**Prizes:** 1st 200c + HC Box; 2nd 125c + HC Box; 3rd 75c + HC Box.
The Help section, leaderboard and event timer are accessible through buttons.

**Optional Discord role assignment:** Create a participant role and set
`DISCORD_ROLE_ID` to its numeric ID in Railway Variables. Give the bot the
**Manage Roles** permission and put the bot's role **above** the participant
role in Server Settings → Roles. A participant receives this role on join;
without `DISCORD_ROLE_ID`, the join panel still works as an enrollment panel.

**Upgrade note:** Existing global `/leaderboard`, `/guide` and `/eventstatus`
commands from an older deployment may remain visible temporarily because Discord
caches command definitions. This version registers only `/play` (and when
`GUILD_ID` is set, synchronizes the guild command). For older global commands,
remove them from the Discord developer app or perform a one-time global sync.
