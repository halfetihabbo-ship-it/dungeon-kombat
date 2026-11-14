# Dungeon Kombat v13 — The Kingdom Awakens

Medieval 100-floor Discord RPG. **Only player-facing slash command: `/play`**. The existing v12 player database, equipment, battle progress and Championship Arena results are retained using additive SQLite migrations.

## New in v13

- **Three Doors** after boss floors 10–90: Iron (three-turn tactical elite encounter; win 2/3 counters for bonus), Golden (guaranteed gold and materials), Runic (three-floor defence blessing), or safely skip. Door decisions are stored once per player/floor.
- **Treasure Chambers** after floors 5, 15, 25 ... 95: choose 350 gold, 8 materials or a three-floor +5% HP blessing. One claim per player/floor, never rerollable.
- **Enemy Intentions**: enemy attack intent is shown before every combat action. Heavy, guarding, reckless, venom, charging and normal moves have different tactical responses. The same deterministic intent is used for damage resolution and display.
- **Boss Phases**: each boss has three HP phases (>60%, 60–25%, <=25%), with increasingly aggressive patterns, more tactical openings, and named medieval bosses.
- **World Boss Raids**: one asynchronous raid per event day, with 3 tactical attempts per player/day. Players respond to telegraphed enemy moves using Strike/Guard/Pierce. Standardized raid damage (650 correct counter, 400 otherwise), no dungeon build advantage. Each attempt awards 100 gold and 1 material; participants can claim a one-time 350 gold and 5 material bonus if their server defeats the boss that day. Raid HP is 20,000 (best suited to roughly 11+ active players; adjustable in code).
- **Wandering Merchant**: accessible through `/play` after boss floors 10–90, with gold-purchased materials and three-floor temporary blessings. Each item can be purchased once at each merchant floor.
- **Medieval visual design**: existing procedurally drawn stonework, heraldic banners, torches and parchment, plus a new raid panel. All generated locally without remote assets.

## Player navigation

`/play` -> Castle Gate -> Enter Dungeon / My Fighter / Blacksmith / Gather Resources / Treasury / Championship Arena / Rankings / Arena Score / Rules & Dates / World Raid / Wandering Merchant / Create Fighter.

On a victory, **Next Floor** routes the player through any unclaimed Three Doors or Treasure Chamber encounter before the next fight. **Exit Dungeon** preserves progress. Pending elite trials resume on the next dungeon entry. No new slash commands are required.

## Railway deployment

1. Extract the ZIP. Upload **the files themselves**, not the enclosing folder, to the GitHub repository root.
2. In Railway, deploy from GitHub with the root directory `/` (or blank if using repository root).
3. Set variables: `DISCORD_TOKEN` (secret), `GUILD_ID=1557502185615397005`, `EVENT_START_DATE=2026-11-14` (or the date you want to start, in UTC), and `DATABASE_PATH=/data/dungeon_kombat.db`.
4. Attach a persistent Railway volume mounted at `/data`. Start command: `python main.py`.
5. Redeploy, wait for command synchronization, then use `/play`.

**Note:** The game counts event days from UTC midnight, not the exact deploy time. Keep the existing volume to preserve player progress. If the original event has already started, updating the ZIP does not restart its timer.

## Fairness and limits

- Arena is unchanged and standardized; dungeon loot, temporary blessings, raid rewards and equipment do not affect its tactical scoring.
- Door and chest claims, merchant purchases, and raid attempts are persisted and protected by a shared asyncio lock against double-click duplication.
- Encounter rewards and merchant bonuses are intentionally modest, but the new combat patterns have not been calibrated by a full live seven-day Monte Carlo run. Test difficulty before launching a new competition.
- Raid victory rewards can be claimed only on the day the raid is defeated.

## Verification

Python syntax checks, source-level structural tests, ZIP integrity verification and SQLite schema smoke tests are included in the build process. **Live Discord interaction tests have not been run** in this environment. Test all six new features on Railway before announcing the update.

### v13.1 — Exit Dungeon navigation
The **Exit Dungeon** button now edits the victory/defeat message into the full `/play` Castle Gate interface (including the medieval artwork and all menu buttons), instead of displaying a message instructing the player to run `/play` again. No dungeon attempt is spent by exiting.

## v14 — Shared Castle Entrance and one-panel player navigation

Run `/play` **once** in the game channel to publish the shared Castle Entrance. The
public **Enter the Kingdom** button is persistent across bot restarts. Each
player clicking it gets a **private** menu, so players share one entry panel
without seeing or interfering with each other's inventories and battles.

- New players see **Create Your Fighter**. Submitting the fighter-name modal
  immediately replaces their registration panel with the full Castle Gate menu.
- Existing players go directly to the Castle Gate.
- Navigating the menus, dungeon, gathering, merchant and raids edits the current
  private message instead of posting a fresh panel for every click.
- Buttons follow a consistent scheme: action buttons use Discord blurple;
  back/castle navigation uses neutral grey.
- **Exit Dungeon** and **Castle Gate** in battle return to the main player menu;
  in-progress battles and earned floor progress are preserved.
- The Championship Arena has Next Challenge / Resume and Castle Gate buttons.
- The public entrance button is registered as a persistent Discord component.
  Personal ephemeral panels can expire after inactivity; players can click the
  existing public entrance again without typing `/play`.

**Deployment:** Replace files in the GitHub repo root and redeploy Railway.
Keep `DISCORD_TOKEN`, `GUILD_ID`, `EVENT_START_DATE`, `DATABASE_PATH` and the
existing `/data` volume. No schema reset is required. The original event clock
is not restarted by deploying v14.

**Verification:** Python syntax checks pass; live Discord interaction testing
is required before relying on this update for a public event.

## v15 — Clean Castle Gate and Arena qualification

- Main private Castle Gate now has **four** core buttons: Enter Dungeon, My Fighter, Blacksmith, Kingdom.
- Kingdom submenu contains gathering, world raid, merchant, treasury, rankings, and rules.
- **Championship Arena button appears only for players with `floor >= 100`**, and the callback rechecks qualification before opening an Arena submenu with Enter Arena and My Arena Score. Existing arena handlers retain their own qualification checks.
- Shared public Enter the Kingdom button remains persistent; new fighter creation opens the main Castle Gate directly.
- Existing SQLite database and Railway settings are preserved.
- Live Discord interactions have not been tested.
