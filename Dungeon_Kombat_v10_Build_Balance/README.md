# Dungeon Kombat v23 — Endless Dungeon

Seven-day tournament, unlimited dungeon attempts, highest completed floor wins. The Championship Arena has been retired.

## Deployment
Use the existing Railway persistent volume and `DATABASE_PATH=/data/dungeon_kombat.db`. The schema migration is additive and does not reset players, equipment or the event clock. Back up the database before upgrading.

Only `/play` is exposed to players; all other actions use private buttons. The Adventurer Handbook is available before entering the Kingdom.

## Rules
- Unlimited attempts during the seven-day event, no cooldown or daily cap.
- First-clear rewards only; failed floors grant no gold/materials.
- Endless enemy HP and damage scaling after floor 100; boss every 10 floors.
- Top three ranked by highest completed floor, then fewer defeats, attempts, and turns.
- Guardian +12% defence, +10% HP, +2% attack; other builds unchanged.
- Weapon/armour upgrades capped at +10 basic and +5 advanced.
- One collectible weapon and one armour equipped at a time.
- Royal Bounties, loot, crafting, missions and gathering retained.

Run `python -m py_compile main.py visuals.py` before deployment. Simulation is a separate simplified approximation, not a live Discord integration test.
