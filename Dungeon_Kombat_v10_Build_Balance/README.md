# Dungeon Kombat v16 — Royal Bounties & Armoury

Medieval-themed, seven-day, 100-floor Discord dungeon tournament. **One player-facing command: `/play`**. A host posts the shared entrance once; players use the persistent public entrance to open private panels. New fighter creation goes directly to the Castle Gate.

## Navigation

- Castle Gate: Enter Dungeon, My Fighter, Kingdom, Rules & Guide. Championship Arena appears only after clearing Floor 100 and eligibility is checked server-side.
- Kingdom: Blacksmith, Activities, Daily Missions, Kingdom Events, World Raid, Merchant, Treasury, Rankings, Castle Gate.
- My Fighter: Equipment Collection (two equipment selectors), View Fighter, Allocate Stats, Appearance & Weapon, Choose Skill, Reset Stats.

## New systems

**Daily Missions**: 5 dungeon victories, 3 gathering activities, 2 raid attacks. Claim 250 gold + 3 materials, 180 gold + 5 materials, and 200 gold + 4 materials respectively. Claim all three for an additional 500 gold + 10 materials. Progress and claims persist in SQLite and reset each UTC day. Rewards are claimed manually in Kingdom > Daily Missions. The mission is awarded only for a valid completed activity/battle/raid.

**Kingdom Events**: Seven fixed UTC daily modifiers: 10% first-clear gold on days 1, 3 and 6; +1 material per gathering action on days 2 and 5; +10% activity gold on days 4 and 7. Shown under Kingdom > Kingdom Events and on the Bounty Board. No Arena effects.

**Collectible equipment**: 11 named permanent milestone pieces, guaranteed at floors 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100. Six collectible weapons and five armours. Equip in My Fighter > Equipment Collection. Collectible weapons provide +0.8% to +2.8% attack; armour +1% to +3% HP. Equipment does **not** replace the base weapon class, remove upgrades, or affect Arena. Previously completed milestones are backfilled when opening the collection. No trading or random loot drops in this version.

**Preserved**: 100 floors, medieval artwork, enemy intentions, boss phases, Three Doors, treasure rooms, wandering merchant, daily world raids, original weapon classes, basic/advanced forging, persistent shared entrance and standardized Championship Arena.

## Deploy to Railway

1. Upload files from the ZIP **at the root of your GitHub repository** (do not upload an enclosing folder).
2. Deploy the repository on Railway, Root Directory `/` (or blank).
3. Variables: `DISCORD_TOKEN` (secret), `GUILD_ID=1557502185615397005`, `EVENT_START_DATE=2026-11-14` (change to your intended event start date), `DATABASE_PATH=/data/dungeon_kombat.db`.
4. Keep a persistent Railway volume mounted at `/data`. Start command `python main.py`.
5. Redeploy and test the original public entrance panel or post `/play` once if needed. **Do not delete the existing volume**; SQLite migrations are additive. Updating does not restart the seven-day event clock.

## Simulation

`simulation/simulate_live.py` is a **simplified Monte Carlo** based on production `stats`, `enemy_stats`, `reward_for_floor`, `damage_reduction`, `advanced_cost`, and collectible definitions. `simulation/simulate_baseline.py` uses the v15 versions of those functions. Each tested 3 builds x 3 activity schedules x 180 seeds = **1,620 trials per version**. Summary and day-by-day CSVs included.

Limitations: independent approximated combat AI, not actual Discord event interactions; it does not fully reproduce enemy intention/boss phase choices, Three Doors, treasure encounters, merchant decisions, world raid rewards, or exact claim timing. It approximates 1 dungeon and 1 gathering mission reward per active day and **excludes raid and full-completion mission bonuses**. Player schedules are assumptions; results are not live completion statistics.

**Balance warning:** Updated dedicated and regular builds all cleared Floor 100 in 100% of modelled runs. This is easier than a target of ~80–90% dedicated completion. Casual clear rates were 100% balanced, 91.1% aggressive and 94.4% defensive. More difficulty calibration is recommended before launch; do not interpret these figures as proof the live game is balanced.

## Testing

- `python -m py_compile main.py arena.py visuals.py`
- `python simulation/test_v16.py` (from within the simulation directory, the test expects `main.py` in the parent; use the included test command below)
- `python simulation/simulate_live.py --runs 180`

Source syntax and SQLite schema smoke tests passed. **Discord interactions have not been tested live** in this environment. Verify missions, collection selectors, world raids, navigation and Arena on Railway before a public event.

## v17 late-game difficulty adjustment (simulation-based)

Enemy HP now scales gradually by an additional 0% at Floor 40 to 8.5% at Floor 100. Enemy attack is unchanged. This avoids a sudden boss-only spike and preserves early-game accessibility. No Arena combat/scoring rules were changed. The change is intentionally modest rather than forcing a target completion rate at the expense of aggressive or casual builds.

The `simulation/summary.csv` and `simulation/daily.csv` are the latest v17 results (180 seeds per build/schedule, 1,620 total trials). **Caution:** dedicated builds still reach Floor 100 in 100% of these simplified simulations. Casual aggressive completion falls from 91.1% to 28.3%, indicating that more targeted class-specific balancing is required before declaring this change fair. Test in a staging guild before production.

## v18: Seven-day participation balance
- Berserker HP bonus increased from 10% to 15% to reduce its vulnerability to late-game encounters; attack bonus unchanged.
- Existing 20 daily dungeon attempts, carryover, floor scaling, item milestones, missions, events and Championship Arena remain unchanged.
- Simulation assumptions: dedicated players attempt 20 floors/day; regular players attempt 11–18 floors/day (randomly); casual players attempt 6–10 floors/day. These are **player-behaviour assumptions**, not hardcoded gameplay restrictions.
- `simulation/summary.csv` has 500 runs per build/activity combination (4,500 simulated seven-day campaigns). `median_finish_hours` is **elapsed time since event start**, not active play time. Completion times only include successful runs.
- The simulator approximates combat and does not reproduce all boss phases, doors, merchant choices or raids. Treat the completion rates as directional, not a prediction of live server behaviour.

## v19 Berserker balance adjustment
- Berserker specialization: +15% attack, **+21% HP** (formerly +15% HP).
- No changes to other fighter specializations, enemy difficulty, event duration or Championship Arena.
- `simulation/simulate_live.py --runs 500` generated 4,500 simulated seven-day campaigns. See `simulation/summary.csv` and `simulation/daily.csv`.
- Completion (dedicated/regular/casual): balanced 100/59.8/0%; aggressive 100/63.0/0%; defensive 100/58.6/0%.
- Simulator approximates combat decisions; live Discord combat and boss mechanics remain to be tested.
