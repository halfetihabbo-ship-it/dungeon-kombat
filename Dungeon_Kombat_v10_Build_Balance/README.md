# Dungeon Kombat v10 — Build balance experiment

This is a playable Discord bot code update, retaining the visual panels, stamina regeneration and randomized Championship Arena from v9. Live Discord/Railway testing has **not** been performed.

## Combat changes
- Berserker: +15% attack and +10% maximum HP.
- Guardian: +5% defence and +2% attack (after first test showed that an 8% attack penalty made the build uncompetitive).
- Arcanist: +5% attack, +5% maximum HP, +20 maximum energy.
- Defence damage reduction now has stronger diminishing returns, with a 55% reduction cap.
- Boss attacks gain 10% additional damage per turn after turn 8. This is uncapped; long boss fights become extremely dangerous.
- Three healing potions per battle (previously two); no additional potion refills within a battle.

## Simulation
Run `python simulate_live.py --runs 180`. It reads actual production functions from `main.py` and independently approximates tactical combat and equipment purchases.

Results: 1,620 runs (3 builds x 3 activity schedules x 180 seeds). Dedicated and regular automated tactical players reach floor 100 in 100% of tested runs for all builds. Casual completion: balanced 93.9%, aggressive 50.0%, defensive 49.4%.

**Interpretation:** build fairness improved among dedicated players, but difficulty is now too easy for them, and balanced remains more forgiving for casuals. These are simulation estimates, not real-player guarantees.

## Important limitations
- Simulation does not use Discord buttons, networking, or actual human decisions.
- It uses the existing Axe/Sword policy per build, not all five weapon classes, and one tactical combat AI.
- Arena scoring and fairness are not simulated.
- The 5% post-kill healing proposed earlier was *not* implemented; HP resets at the beginning of each battle, so post-kill healing would have no gameplay effect.
- The 3-heal limit is implemented through a three-potion battle inventory.

## Deployment
Configure DISCORD_TOKEN, GUILD_ID, EVENT_START_DATE and persistent DATABASE_PATH. Back up SQLite before deploying. Install requirements.txt and launch `python main.py`.
