# Dungeon Kombat v21 — Royal Bounties & Loot

## Installation
Upload the root files to your existing GitHub repo and redeploy Railway. Keep the **same persistent Railway volume** mounted at `/data` and `DATABASE_PATH=/data/dungeon_kombat.db`. Do **not** delete the existing database. The new SQLite tables are created automatically. The tournament start date remains unchanged.

Requires Python 3.11+, discord.py 2.4+, Pillow. Only player slash command: `/play`. All menus are private after using the public Castle Gate entrance.

## Changes
- Removed World Raid menu and raid mechanics. Existing `world_raids` and `raid_participation` database tables are left untouched for safe migration but no longer used.
- Replaced raid Daily Mission with **Defeat today's Royal Bounty** (200 gold + 4 materials), keeping the all-three bonus unchanged.
- Added **Royal Bounty**: unlock Floor 5, up to three attempts/day, each challenge is three visible tactical cues (Attack, Defend, Special). Two correct moves win. Winning grants 300 gold, five materials, a guaranteed not-yet-owned random item if any remain, and daily mission progress. A challenge is resumable if its panel is closed.
- Added **24 optional collectible items** (35 total including 11 original milestones): Common, Uncommon, Rare, Epic, Legendary. Weapons give +0.9% to +2.9% attack; armour gives +1.2% to +3.2% HP. Equipped items do not change original weapon class or special ability. Only one collectible weapon and one armour can be equipped.
- **Dungeon loot:** each first-time successful floor clear has a 22% chance to award one random item, with rarity weights 55/28/12/4/1. Roll is recorded per player and floor and cannot be farmed by retries. Duplicate items are possible and don't grant additional copies or bonuses. Original milestone items remain guaranteed.
- **Crafting:** eight specific recipes, from Floor 12 to Floor 85. Costs are listed in the Crafting menu; crafting succeeds if the player meets floor and resource requirements and does not own the item. Duplicates are not charged. Access via Kingdom → Blacksmith → Craft Equipment.
- All changes are additive to the player database and preserve existing progress. Kingdom events, fighter builds, original weapons, and Arena remain intact.

## Important notes
- Existing stored raid mission progress will not be counted toward the new bounty mission. Existing player data and previous raid tables are not deleted.
- The 22% loot chance is per *first successful clear*, not every attempt; duplicate drops can occur.
- Bounty fights are three-turn **tactical counter puzzles**, not full HP-based boss fights. This is deliberate to avoid making the event dependent on random combat odds.
- The bot has passed Python 3.11 syntax/AST checks and standalone loot/recipe checks. A live Discord integration test is still required. The v19 combat balance simulation was **not rerun** with the extra resources and loot; these features may alter completion rates.
