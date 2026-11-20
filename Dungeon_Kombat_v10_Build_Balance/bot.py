"""Abyss Ascension: single /play command, public join panel, private interactive menus."""
import logging
import time
import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import game

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv('DISCORD_TOKEN', '').strip()
GUILD_ID = os.getenv('GUILD_ID', '').strip()
ROLE_ID = os.getenv('DISCORD_ROLE_ID', '').strip()
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
GOLD = discord.Color.from_rgb(245, 184, 66)
PURPLE = discord.Color.from_rgb(125, 89, 224)

PRIZES = ('🥇 **1ST PLACE** — **200c + HC Box**',
          '🥈 **2ND PLACE** — **125c + HC Box**',
          '🥉 **3RD PLACE** — **75c + HC Box**')

def event_text(db):
    start, end = game.event_window(db)
    if end is None:
        return '⏳ The 7-day countdown begins when the first hero joins.'
    now = game.utcnow()
    if now < start:
        return f'🗓️ Starts <t:{int(start)}:F>'
    if now >= end:
        return '🏁 **EVENT ENDED** — Final rankings are locked.'
    return f'⏰ **Ends <t:{int(end)}:F>** · <t:{int(end)}:R>'

def prize_text():
    return '\n'.join(PRIZES)

def panel_embed():
    with game.open_db() as db:
        status = event_text(db)
    e = discord.Embed(
        title='⚔️🏰  ABYSS ASCENSION  🏰⚔️',
        description=(
            '# 🐉 ENTER THE DUNGEON!\n'
            '## 💥 CLIMB. FIGHT. CONQUER. 💥\n'
            '**SEVEN DAYS. ENDLESS FLOORS. THREE CHAMPIONS.**\n\n'
            '⚔️ Create your hero and automatically fight your way through the dungeon.\n'
            '🛡️ Collect powerful equipment and upgrade it at the Blacksmith.\n'
            '🐲 Defeat legendary bosses and conquer higher floors.\n'
            '🏆 Reach the **highest floor** to claim the top prizes!\n\n'
            '## 🎁 WIN THESE PRIZES!\n' + prize_text() + '\n\n'
            '## 🚀 READY TO JOIN?\n'
            '**👇 PRESS THE BIG GREEN JOIN BUTTON BELOW! 👇**\n'
            '*No complicated setup — choose your class and your hero starts climbing.*'
        ), color=GOLD)
    e.add_field(name='📅 EVENT TIMER', value=status, inline=False)
    e.add_field(name='🎮 HOW TO PLAY', value='**1️⃣ JOIN** → **2️⃣ PICK A CLASS** → **3️⃣ CLIMB & UPGRADE**', inline=False)
    e.set_footer(text='Abyss Ascension • Top 3 highest floors win • Ties: earliest to reach that floor')
    return e

def stats(s):
    return (f'🧙 **{s["class"]}**  ·  ⭐ **Lv. {s["level"]}**  ·  🏰 **Floor {s["floor"]:,}**\n'
            f'❤️ **{s["hp"]:,}/{game.max_hp(s):,} HP**  ·  ⚔️ **{game.attack_power(s):.0f} ATK**  ·  🛡️ **{game.defense_power(s):.0f} DEF**\n'
            f'🪙 **{s["gold"]:,} Gold**  ·  🧱 **{s["materials"]:,} Materials**  ·  🗝️ **{s["keys"]} Keys**')

def rankings_embed():
    with game.open_db() as db:
        ranks = game.leaderboard(db)
        status = event_text(db)
    lines = [f'{("🥇", "🥈", "🥉")[i] if i < 3 else f"`#{i+1}`"} **{discord.utils.escape_markdown(name)}** — Floor **{floor:,}**'
             for i, (_, name, floor, _) in enumerate(ranks)]
    e = discord.Embed(title='🏆 HALL OF CHAMPIONS',
                      description=('\n'.join(lines) or '🌱 No heroes yet — be the first!') + '\n\n' + status,
                      color=GOLD)
    e.add_field(name='🎁 TOP 3 PRIZES', value=prize_text(), inline=False)
    e.set_footer(text='Highest floor wins • Tie-break: earliest to reach that floor')
    return e

def help_embed():
    e = discord.Embed(title='📖⚔️ ABYSS ASCENSION — HELP & QUICK START', description=(
        '## 🚀 QUICK START — 3 STEPS\n'
        '**1️⃣ CREATE YOUR HERO** — Berserker ⚔️, Guardian 🛡️ or Rogue 🗡️.\n'
        '**2️⃣ CLIMB & PLAY** — Passive battles process every **45 seconds** (up to **8 hours** offline), but grant less XP. Expeditions and trials give meaningful active progress.\n'
        '**3️⃣ RETURN & GROW STRONGER** — Press **🔄 Refresh**, claim rewards, upgrade gear and fight bosses.\n'
        '⚔️ **Better weapons and armour auto-equip by default.** To adjust your build, go to **/play → 🧙 Hero → 🎒 Inventory** to compare gear, equip manually, lock favourites or turn Auto-Equip OFF.\n\n'
        '## 🧭 HOME NAVIGATION\n'
        '🔄 **Refresh** — Process idle battles and see your latest rewards.\n'
        '🏰 **Dungeon** — Active Expeditions, Floor Checkpoints, Tactical Boss Battles, Treasure Goblins, Mystery Chambers and Abyss Portals.\n'
        '🧙 **Hero** — Build Specialisations, Inventory, Enchanting, Relics, Companions and Skill Tree.\n'
        '🏰 **Kingdom** — Blacksmith, Adventurer Camp and Travelling Merchant.\n'
        '🎯 **Activities** — Wheel of Fortune, Quest Board, Daily Bounty, Gauntlet, Arena Trials and Treasure Vault.\n'
        '📖 **Info** — Leaderboard and Adventurer Log (12-hour progress reports).\n📘 **Help** — Open this complete guide directly from Home.\n\n'
        '## ⚔️ ACTIVE GAMEPLAY\n'
        '🎮 **Expeditions** — Three charges maximum, recharge one every two hours. Five rooms: Fight, Scout or Rest. Finish to bank XP and resources.\n'
        '🏰 **Checkpoints** — Every 10th floor (10, 20, 30, etc.), except legendary boss floors (50, 100, etc.), pauses automatic climbing. You receive **one Discord DM per checkpoint** when progress is processed through /play or Refresh. Go to **/play → 🏰 Dungeon → Checkpoint** and complete **Guard → Focus → Attack** to resume. If DMs are disabled, the checkpoint remains visible in your game UI.\n'
        '🧙 **Builds** — Hero → Build: Balanced, Aggressive, Defensive or Treasure Hunter. Switch freely to suit your approach.\n'
        '🐉 **Tactical Bosses** — Check the boss intent. Guard heavy strikes, use Power Strike against feints, and plan healing.\n\n'
        '## 🏰 DUNGEON DISCOVERIES\n'
        '🐉 **Boss Battle** — Legendary boss every 50 floors (instead of a normal checkpoint). One-time DM on check-in. Read enemy intent; choose Attack, Guard, Power Strike or Second Wind.\n'
        '👹 **Treasure Goblin** — Personal clue challenge every six hours, with two attempts; DM alert on check-in.\n'
        '🏰 **Mystery Chambers** — Discover while climbing; choose an encounter reward. DM alert on check-in.\n'
        '🌀 **Abyss Portals** — Optional three-stage Blood, Golden or Mystic routes; DM alert on check-in.\n\n'
        '## 🧙 HERO & EQUIPMENT\n'
        '🎒 **Inventory & Auto-Equip** — Your hero automatically equips stronger weapons and armour as they drop (**ON by default**). Visit **/play → 🧙 Hero → 🎒 Inventory** to compare stats and perks, manually equip gear, lock favourites, dismantle unwanted items or toggle Auto-Equip OFF/ON. A higher Attack or Defence stat may not always suit your build.\n'
        '✨ **Enchanting** — Character-bound bonuses persist when weapons auto-switch; changing costs 1,200 gold + 15 materials.\n'
        '💍 **Relics** — Collect from portals and equip one permanent passive bonus.\n'
        '🐾 **Companions** — Unlock, equip and upgrade your companion.\n'
        '🌳 **Skill Tree** — One point per five levels, with free resets.\n\n'
        '## 🏰 KINGDOM & 🎯 ACTIVITIES\n'
        '⚒️ **Blacksmith** — Upgrade weapon/armour to +10; refine from Floor 100.\n'
        '🏕️ **Camp** — Train Attack, Defence or Gold for 60 minutes, or rest to restore HP.\n'
        '🧙 **Merchant** — Shop rotates every six hours.\n'
        '🎡 **Wheel** — One spin every six hours.\n'
        '📜 **Quest Board** — Three daily objectives unlock a bonus chest.\n'
        '🎯 **Activities** — Claim Daily Bounty, play Gauntlet, use three daily Arena attempts and spend Vault Keys.\n\n'
        '## 📖 ADVENTURER LOG\n'
        'Open **/play → 📖 Info → Adventurer Log** to see your current stats and progress since the last report.\n'
        '📩 A private progress summary is sent every **12 hours** while the event is active. DMs must be enabled.\n'
        '⏳ Offline battles are capped at **8 hours** per progress calculation, including scheduled reports.\n\n'
        '## 💡 TIPS\n'
        '💰 Stuck? Your hero farms resources and heals. Passive auto-upgrading is disabled: visit the Blacksmith yourself. Every ten floors grants a milestone chest.\n'
        '🏠 **Home** returns to the main hub; **⬅️ Back** returns to the previous category.\n'
        '🏆 Highest floor after seven days wins; ties go to whoever reached it first.'
    ),color=PURPLE)
    e.add_field(name='🎁 PRIZES',value=prize_text(),inline=False)
    e.set_footer(text='Only /play is required • Button menus edit the same private panel')
    return e

CATEGORY_SCREENS = {
    'dungeon': ('🏰 DUNGEON', '🔄 Refresh your climb, defeat bosses and explore discoveries.\nYour hero continues climbing automatically while you explore menus.'),
    'hero': ('🧙 HERO', '🎒 Manage equipment, enchantments, relics, companions and skill points.'),
    'kingdom': ('🏰 KINGDOM', '⚒️ Visit the Blacksmith, Adventurer Camp or Travelling Merchant.'),
    'activities_menu': ('🎯 ACTIVITIES', '🎡 Spin the wheel, complete daily quests, claim bounties and enter the Arena.'),
    'info': ('📖 INFORMATION', '📘 Read the guide or check the competition leaderboard.'),
}
SCREEN_PARENT = {
    'expedition':'dungeon','checkpoint':'dungeon','boss':'dungeon','goblin':'dungeon','chamber':'dungeon','portal':'dungeon',
    'build':'hero','inventory':'hero','enchant':'hero','relics':'hero','pets':'hero','skills':'hero',
    'smith':'kingdom','camp':'kingdom','merchant':'kingdom',
    'journal':'info',
    'activities':'activities_menu','arena':'activities_menu','wheel':'activities_menu','quests':'activities_menu',
}

def journal_delta_text(report):
    d=report['delta']
    sign=lambda n: f'{n:+,}'
    return (f'🏰 Floors progressed: **{sign(d["floor"])}**\n'
            f'⭐ Levels gained: **{sign(d["level"])}**\n'
            f'✨ XP earned: **{sign(d["xp_total"])}**\n'
            f'⚔️ Battles won: **{d["wins"]:,}** · Lost: **{d["fails"]:,}**\n'
            f'🪙 Gold change: **{sign(d["gold"])}** · 🧱 Materials change: **{sign(d["materials"])}**\n'
            f'🗝️ Keys change: **{sign(d["keys"])}** · 🎡 Wheel spins: **{d["wheel_spins"]:,}**\n'
            f'🏟️ Arena wins: **{d["arena_wins"]:,}**\n'
            f'🕒 Tracking since <t:{int(report["since"])}:F>')

def journal_dm_embed(s,report):
    e=discord.Embed(title='📖 ABYSS ASCENSION — 12-HOUR ADVENTURER LOG',
                    description='Your latest adventure progress!\n\n'+journal_delta_text(report),color=PURPLE)
    e.add_field(name='🧙 CURRENT HERO',value=(
        f'**{s["class"]}** · ⭐ Level **{s["level"]:,}** · 🏰 Floor **{s["floor"]:,}**\n'
        f'❤️ **{s["hp"]:,}/{game.max_hp(s):,} HP** · ⚔️ **{game.attack_power(s):.0f} ATK** · 🛡️ **{game.defense_power(s):.0f} DEF**\n'
        f'🪙 **{s["gold"]:,} gold** · 🧱 **{s["materials"]:,} materials**'),inline=False)
    e.set_footer(text='Open /play → 📖 Info → Adventurer Log for your latest stats')
    return e

def player_embed(s, notice='', screen='home'):
    titles = {'home': '🏰⚔️ YOUR DUNGEON ADVENTURE', 'smith': '⚒️🔥 THE ROYAL BLACKSMITH',
              'activities': '🎯✨ QUESTS & TREASURE', 'wheel':'🎡✨ WHEEL OF FORTUNE', 'quests':'📜✨ DAILY QUEST BOARD', 'chamber': '🏰✨ MYSTERY CHAMBER', 'arena':'🏟️⚔️ ARENA TRIALS', 'pets':'🐾✨ COMPANIONS', 'skills':'🌳✨ SKILL TREE', 'merchant':'🧙🛒 TRAVELLING MERCHANT', 'journal':'📖 ADVENTURER LOG','expedition':'⚔️ ACTIVE EXPEDITION','checkpoint':'🏰 ASCENSION CHECKPOINT','build':'🧙 BUILD SPECIALISATIONS', 'goblin':'👹💰 TREASURE GOBLIN', 'boss': '🐉🔥 LEGENDARY BOSS', 'inventory':'🎒⚔️ HERO INVENTORY', 'enchant':'✨ WEAPON ENCHANTING', **{key: value[0] for key, value in CATEGORY_SCREENS.items()}}
    e = discord.Embed(title=titles.get(screen, titles['home']), description=stats(s), color=GOLD if screen=='home' else PURPLE)
    if screen=='home':
        if s.get('checkpoint'):
            e.add_field(name='🏰 CHECKPOINT WAITING',value=f'Floor **{s["checkpoint"]["floor"]}** needs a 3-step manual trial. Open Dungeon → Checkpoint.',inline=False)
        if s.get('chambers'):
            e.add_field(name='🚨🏰 MYSTERY CHAMBER DISCOVERED!',value=f'**{len(s["chambers"])} unclaimed chamber(s)!** Open **🏰 Dungeon → Mystery Chamber** to explore. Your hero keeps climbing!',inline=False)
        e.add_field(name='👹 TREASURE GOBLIN',value='A personal goblin appears every **6 hours**. Open **🏰 Dungeon → Treasure Goblin** to solve its clue and claim your loot!',inline=False)
        e.add_field(name='🎡 DAILY ACTIVITIES',value='🎡 **Wheel of Fortune** — spin every 6 hours.\n📜 **Quest Board** — 3 daily goals and a bonus chest.',inline=False)
        e.add_field(name='🗺️ YOUR ADVENTURE',
                    value=('🔴 **A LEGENDARY BOSS IS WAITING!** Open **🐉 Boss Battle**.' if s['boss']
                           else '🟠 **CHECKPOINT PAUSED** — clear the trial to resume.' if s.get('checkpoint') else '🟢 **AUTO-CLIMB ACTIVE!** Your hero is battling or farming.'), inline=False)
        e.add_field(name='🗡️ EQUIPMENT',
                    value=(f'⚔️ **{s["weapon"]["name"]}**  +{s["weapon"]["plus"]} · R{s["weapon"]["refine"]}\n'
                           f'🛡️ **{s["armour"]["name"]}**  +{s["armour"]["plus"]} · R{s["armour"]["refine"]}'), inline=False)
        e.add_field(name='🚀 QUICK NAVIGATION',
                    value='**🔄 Refresh** — Collect idle progress.\n**🏰 Dungeon** — Expeditions, Checkpoints, Bosses & Discoveries.\n**🧙 Hero** — Builds, Inventory, Enchanting, Relics, Pets & Skills.\n**🏰 Kingdom** — Blacksmith, Camp & Merchant.\n**🎯 Activities** — Wheel, Quests, Arena & Bounty.\n**📖 Info** — Leaderboard & Adventurer Log.\n**📘 Help** — Open the complete game guide instantly.',inline=False)
        e.add_field(name='📜 LATEST ADVENTURE REPORT', value=(notice or s.get('last_report') or 'Your journey begins!')[:1024], inline=False)
    elif screen=='journal':
        with game.open_db() as db:
            report=game.journal_stats(db, s['_user_id'])
        if report:
            e.add_field(name='📊 PROGRESS SINCE LAST REPORT',value=journal_delta_text(report),inline=False)
            e.add_field(name='⚔️ CURRENT COMBAT STATS',value=(f'❤️ HP: **{s["hp"]:,}/{game.max_hp(s):,}**\n'
                         f'⚔️ Attack: **{game.attack_power(s):.0f}** · 🛡️ Defence: **{game.defense_power(s):.0f}**\n'
                         f'🏰 Floor: **{s["floor"]:,}** · ⭐ Level: **{s["level"]:,}**\n'
                         f'🏆 Lifetime victories: **{s.get("wins",0):,}** · Defeats: **{s.get("fails",0):,}**'),inline=False)
            e.add_field(name='📩 NEXT REPORT',value=f'<t:{int(report["next_due"])}:R> (Discord DM)',inline=False)
    elif screen in CATEGORY_SCREENS:
        e.add_field(name='🧭 SELECT A DESTINATION', value=CATEGORY_SCREENS[screen][1], inline=False)
    elif screen=='build':
        style=s.get('build','balanced')
        e.add_field(name='🧙 CURRENT COMBAT BUILD',value=f'**{game.BUILD_STYLES.get(style,game.BUILD_STYLES["balanced"])[0]}**\nSwitch freely. Aggressive increases attack but lowers defence; Defensive favours survival; Treasure Hunter earns more gold but deals less damage.',inline=False)
    elif screen=='expedition':
        ex=s.get('expedition')
        if ex:
            e.add_field(name=f'⚔️ ROOM {ex["stage"]}/5',value=f'❤️ Expedition HP **{ex["hp"]}/100**\n🪙 Pending gold **{ex["gold"]:,}** · 🧱 Materials **{ex["materials"]}** · ⭐ XP **{ex["xp"]}**\nChoose Fight (high rewards/risk), Scout (safe supplies) or Rest (heal). Rewards bank only after room 5.',inline=False)
        else:
            e.add_field(name='🎟️ AVAILABLE EXPEDITIONS',value=f'**{s.get("expedition_charges",3)}/3** charges · +1 every 2 hours\nFive interactive rooms. Finish to claim XP and loot. No floor loss on failure.',inline=False)
    elif screen=='checkpoint':
        gate=s.get('checkpoint')
        if gate:
            clues=['🛡️ The guardian winds up a crushing strike. **Guard** to survive.', '🎯 A hidden rune is pulsing. **Focus** to break the seal.', '⚔️ The guardian is exposed. **Attack** to finish the trial.']
            e.add_field(name=f'🏰 FLOOR {gate["floor"]} · STAGE {gate["stage"]+1}/3',value=clues[gate['stage']],inline=False)
        else:e.add_field(name='🏰 NO CHECKPOINT WAITING',value='Every 10 floors requires a three-step trial (except legendary boss floors). Continue climbing to discover the next one.',inline=False)
    elif screen=='inventory':
        game.ensure_gear(s)
        weapon,armour=game.gear_bag(s,'weapon'),game.gear_bag(s,'armour')
        e.add_field(name='🎒 EQUIPMENT MANAGEMENT',value=(
            f"🤖 Auto-equip: **{'ON' if s['auto_equip'] else 'OFF'}**\n"
            f"⚔️ Weapons: **{len(weapon)}/20** · 🛡️ Armour: **{len(armour)}/20**\n"
            f"⚔️ Equipped: **{s['weapon']['name']}** ({game.gear_stat(s['weapon'])} power)\n"
            f"🛡️ Equipped: **{s['armour']['name']}** ({game.gear_stat(s['armour'])} power)\n\n"
            'Rare+ drops may carry a +2% Attack, Gold, Boss Damage or HP perk. Select gear below to compare, equip, lock or dismantle. '
            'Auto-equip respects locked equipped gear. Paid upgrades stay with their equipment slot.'),inline=False)
    elif screen=='enchant':
        current=game.ENCHANTMENTS.get(s.get('enchantment'),'None')
        e.add_field(name='✨ CHARACTER-BOUND ENCHANTMENT',value=(
            f'Active: **{current}**\n\n'
            '🩸 Lifesteal — restores HP after successful battles.\n'
            '⚡ Critical Strike — +3% attack power.\n'
            '🐉 Boss Slayer — +3% boss damage.\n'
            '💰 Treasure Finder — +3% battle gold.\n\n'
            'Each change costs **1,200 gold + 15 materials**. The enchantment stays active when you change weapons.'),inline=False)
    elif screen=='goblin':
        import time
        with game.open_db() as db: start=game.event_start(db)
        slot,attempts,claimed,clue=game.goblin_status(s,start,time.time())
        remaining=max(0,int((start+(slot+1)*game.GOBLIN_SECONDS)-time.time())) if start else 0
        if claimed: status='✅ You caught this goblin!'
        elif attempts>=2: status='❌ This goblin escaped.'
        else: status=f'👹 **A goblin is hiding!**\n\n**CLUE:** {clue[0]}\n\n'+ '\n'.join(f'**{i+1}.** {answer}' for i,answer in enumerate(clue[1])) + f'\n\n🎯 Attempts remaining: **{2-attempts}**'
        e.add_field(name='👹 PERSONAL GOBLIN CHALLENGE',value=status+f'\n\n⏳ Next goblin in **{remaining//3600}h {(remaining%3600)//60}m**.\n🎁 Same capped reward formula for every player; floors above 200 do not increase the reward.\n🌙 Goblins stay available for the full six-hour window.',inline=False)
    elif screen=='portal':
        active=s.get('portal_active');waiting=len(s.get('portals',[]))
        if active:
            desc=f'🌀 **Portal stage {active["stage"]}/3**\nLoot at stake: {active["gold"]:,} gold, {active["materials"]} materials.\n🔴 Blood: combat, XP and loot (defeat loses portal haul).\n🟡 Golden: reliable gold.\n🔵 Mystic: reliable materials.\nChoose a path each stage; finish all 3 to bank rewards.'
        else:desc=f'🌀 **{waiting} waiting portal(s)** (max 2 saved).\nNew portals appear roughly every 24–34 floors after Floor 25.\nEnter a portal to play 3 stages. A rare relic may drop when you finish.\nNormal dungeon climbing continues; no permanent HP or floor penalty.'
        e.add_field(name='🌀 ABYSS PORTALS',value=desc,inline=False)
    elif screen=='camp':
        import time
        left=max(0,int(s.get('camp_until',0)-time.time()))
        active=s.get('camp_buff') if left else None
        e.add_field(name='🏕️ ADVENTURER CAMP',value=f'Active buff: **{active or "None"}** · {left//60}m remaining\n\n⚔️ Attack training: +8% Attack for 60 min\n🛡️ Defence training: +8% Defence for 60 min\n💰 Treasure preparation: +8% battle gold for 60 min\n❤️ Rest: restore full HP immediately\n\nTraining costs **{350+s["floor"]:,} gold + 5 materials**. Rest costs **{150+s["floor"]//2:,} gold**. Only one buff active at a time.',inline=False)
    elif screen=='relics':
        owned=s.get('relics',[]);active=s.get('equipped_relic')
        lines=[f'{"✅" if key in owned else "🔒"} {name} — +{int(value*1000)/10:g}% {kind}'+(' **EQUIPPED**' if active==key else '') for key,(name,kind,value) in game.RELIC_TYPES.items()]
        e.add_field(name='💍 RELIC COLLECTION',value='\n'.join(lines)+'\n\nEquip one owned relic at a time. Relics can drop from completed Abyss Portals. They stay with your hero when equipment changes.',inline=False)
    elif screen=='smith':
        e.add_field(name='🔨 FORGE YOUR POWER',
                    value='⚔️ Upgrade Weapon / 🛡️ Upgrade Armour: +1 to +10.\n✨ Refine gear endlessly after Floor 100.\n♻️ Upgrades transfer when you find stronger gear.\n💡 Farm gold and materials to afford upgrades.', inline=False)
    elif screen=='activities':
        e.add_field(name='🎯 CHOOSE AN ADVENTURE',
                    value='📜 **Daily Bounty** — Claim gold and materials daily.\n🏟️ **Gauntlet** — Existing once-daily challenge.\n⚔️ **Arena Trials** — 3 attempts daily; choose difficulty.\n🗝️ **Treasure Vault** — Spend a key for treasure.', inline=False)
    elif screen=='wheel':
        import time
        left=game.wheel_remaining(s,time.time())
        status=f'⏳ Next spin in **{left//3600}h {(left%3600)//60}m**' if left else '🟢 **FREE SPIN AVAILABLE!**'
        e.add_field(name='🎡 SPIN EVERY SIX HOURS',value=f'{status}\n\n🎁 Prizes: gold, materials, Vault Keys, jackpot gold or equipment.\n🎲 Spins completed: **{s.get("wheel_spins",0)}**\n\nPress **Spin the Wheel** to reveal your prize!',inline=False)
    elif screen=='quests':
        import time
        with game.open_db() as db: start=game.event_start(db)
        day,progress=game.quest_status(s,start,time.time())
        rows=[f'{"✅" if progress.get(k,0)>=target else "⬜"} {game.QUEST_NAMES[k]} — **{min(target,progress.get(k,0))}/{target}**' for k,target in game.QUEST_TARGETS.items()]
        complete=all(progress.get(k,0)>=v for k,v in game.QUEST_TARGETS.items())
        claimed=s.get('quest_claimed',False) and s.get('quest_day')==day
        status='🎁 **READY TO CLAIM!**' if complete and not claimed else '✅ **Chest claimed today**' if claimed else '📋 Complete all three objectives to unlock the chest.'
        e.add_field(name='📜 TODAY’S THREE QUESTS',value='\n'.join(rows)+f'\n\n{status}\nReward: **{650+s["floor"]*3:,} gold + {18+s["floor"]//40} materials**\nResets each event day.',inline=False)
    elif screen=='chamber':
        chambers=s.get('chambers',[])
        if chambers:
            c=chambers[0];kind=c['kind']
            descriptions={'doors':'🟡 **Golden Door** — reliable treasure\n🔴 **Crimson Door** — fight for better rewards\n🔵 **Mystic Door** — uncertain magical reward', 'relic':'📜 **Study Runes** — gain materials\n💎 **Claim Relic** — earn gold\n🕊️ **Leave** — restore HP', 'guardian':'⚔️ **Attack** — high-risk rewards\n🛡️ **Guard** — safer materials\n🏃 **Retreat** — small gold reward'}
            e.add_field(name=f'🚨 CHAMBER FOUND ON FLOOR {c["floor"]} · {len(chambers)} WAITING',value=descriptions[kind],inline=False)
            e.add_field(name='🧭 CHOOSE YOUR ACTION',value='Select one option below. Each chamber can be completed only once. Auto-climbing continues!',inline=False)
        else:e.add_field(name='🏰 NO CHAMBERS WAITING',value='Keep climbing! New chambers appear roughly every 10–15 floors (maximum 3 saved).',inline=False)
    elif screen=='arena':
        e.add_field(name='🏟️ THREE DAILY ARENA ATTEMPTS',value=f'Attempts used: **{s.get("arena_tries",0)}/3** (resets each event day)\n🟢 **Easy** — safer, smaller prizes\n🟠 **Hard** — stronger foes, better loot\n🔴 **Nightmare** — toughest fights, biggest prizes\nEach attempt is a quick resolved fight. Your dungeon floor is not at risk.',inline=False)
    elif screen=='pets':
        owned=s.get('companions',{});active=s.get('active_companion')
        options=[('🐺 Wolf','wolf','Attack'),('🐻 Bear','bear','Defence'),('🦉 Owl','owl','Gold'),('🐉 Dragon','dragon','Boss damage')]
        e.add_field(name='🐾 CHOOSE YOUR COMPANION',value='\n'.join(f'{emoji} — **{benefit}** · '+(f'Lv{owned[key]}' if key in owned else 'Locked')+(' **EQUIPPED**' if key==active else '') for emoji,key,benefit in options)+'\n\nUnlock: **1,200 gold + 15 materials** (Dragon: **2,200 + 30**). Tap owned pets to equip. Upgrade active pet for gold/materials, maximum Lv8.',inline=False)
    elif screen=='skills':
        alloc=s.get('skill_alloc',{});pts=game.skill_points(s)
        e.add_field(name=f'🌳 AVAILABLE SKILL POINTS: {pts}',value=f'⚔️ **Warrior** ({alloc.get("warrior",0)}) — +2.5% attack/point (max 30%)\n🛡️ **Defender** ({alloc.get("defender",0)}) — +2.5% defence/point (max 30%)\n💰 **Treasure** ({alloc.get("treasure",0)}) — +2% battle gold/point (max 25%)\n\n⭐ Earn **1 point per 5 hero levels**. Resets are **free**.',inline=False)
    elif screen=='merchant':
        import time
        slot=int(time.time()//21600)
        bought=s.get('merchant_buys',{})
        offers=[('🧱 Materials', 'materials',650+s['floor']*2),('🗝️ Vault Key','key',1400+s['floor']*3),('🎁 Mystery Gear','gear',1800+s['floor']*5)]
        e.add_field(name='🛒 FRESH OFFERS EVERY 6 HOURS',value='\n'.join(f'{name} — **{cost:,} gold**'+(' · SOLD' if f'{slot}:{key}' in bought else '') for name,key,cost in offers)+'\n\nEach offer may be bought once per rotation.',inline=False)
    elif screen=='boss':
        b=s.get('boss')
        e.add_field(name='🐲 BOSS ENCOUNTER',
                    value=(f'🔥 **Floor {b["floor"]}** · ❤️ **{max(0,b["hp"]):,}/{b["max_hp"]:,} HP**\n'
                           f'⚔️ Turn **{b["turn"]}/6** · Power Strike cooldown **{b["cooldown"]}**\n'
                           f'🛡️ Heavy strike every 3rd turn — **Guard** to reduce damage!\n'
                           f'💚 Second Wind heals once per fight. · Mercy bonus **+{s["boss_mercy"]*5}%**'
                           if b else '🟢 No boss waiting! Keep climbing; a legendary boss appears every 50 floors.'), inline=False)
    if screen=='boss' and s.get('boss'):
        intent=game.boss_intent(s['boss'])
        e.add_field(name='👁️ ENEMY INTENT',value={'heavy':'💥 Heavy Strike next — Guard reduces damage','feint':'🌀 Feint next — Power Strike gets a bonus','strike':'⚔️ Normal Strike next — choose your timing'}[intent],inline=False)
    if notice and screen!='home':
        e.add_field(name='📣 LATEST RESULT', value=notice[:1024], inline=False)
    e.set_footer(text='⚔️ Battles: 45 seconds • 🌙 Offline: 8 hours • 🏆 7-day event • 📖 Help available')
    return e

async def send_private(interaction, *, embed=None, view=None, content=None):
    if interaction.response.is_done():
        # A deferred button press must update its existing private panel,
        # never post another ephemeral follow-up in the channel.
        kwargs = {}
        if content is not None: kwargs['content'] = content
        if embed is not None: kwargs['embed'] = embed
        if view is not None: kwargs['view'] = view
        await interaction.edit_original_response(**kwargs)
    elif interaction.type == discord.InteractionType.component:
        await interaction.response.edit_message(content=content, embed=embed, view=view)
    else:
        await interaction.response.send_message(content=content, embed=embed, view=view, ephemeral=True)

async def notify_boss(user, state):
    """Notify once per legendary boss floor when progress is processed.

    Bosses are generated during /play or Refresh, not by a background worker.
    A stored checkpoint prevents duplicate DMs after a failed boss attempt.
    """
    boss = state.get('boss')
    if not boss:
        return
    floor = int(boss.get('floor', 0))
    if floor <= 0:
        return
    with game.open_db() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            latest = game.get_player(db, user.id)
            if not latest or not latest.get('boss') or int(latest['boss'].get('floor', 0)) != floor:
                db.execute('COMMIT')
                return
            if int(latest.get('boss_dm_floor', 0)) >= floor:
                db.execute('COMMIT')
                return
            latest['boss_dm_floor'] = floor
            game.save_player(db, user.id, user.display_name, latest)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
    try:
        await user.send(
            '🐉 **ABYSS ASCENSION — LEGENDARY BOSS AVAILABLE!**\n'
            f'⚔️ A legendary boss is guarding **Floor {floor:,}**!\n'
            '🏰 Your automatic climb is paused at this checkpoint until you defeat it.\n'
            'Use **/play → 🏰 Dungeon → Boss Battle** to fight. '
            'Your equipment and progress are safe if you lose!'
        )
    except (discord.Forbidden, discord.HTTPException):
        logging.info('Could not DM boss notification to %s (DMs may be disabled)', user.id)

async def notify_checkpoint(user, state):
    """DM once when a new ten-floor checkpoint is discovered on check-in.

    Persist the notification floor before attempting the DM, so disabled DMs
    cannot cause repeated alerts. No new slash commands or background worker.
    """
    gate = state.get('checkpoint')
    if not gate:
        return
    floor = int(gate.get('floor', 0))
    if floor <= 0 or floor % 10 or floor % 50 == 0:
        return
    with game.open_db() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            latest = game.get_player(db, user.id)
            if not latest or not latest.get('checkpoint') or int(latest['checkpoint'].get('floor', 0)) != floor:
                db.execute('COMMIT')
                return
            if int(latest.get('checkpoint_dm_floor', 0)) >= floor:
                db.execute('COMMIT')
                return
            latest['checkpoint_dm_floor'] = floor
            game.save_player(db, user.id, user.display_name, latest)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
    try:
        await user.send(
            '🏰 **ABYSS ASCENSION — FLOOR CHECKPOINT!**\n'
            f'⚔️ You have reached **Floor {floor:,}**!\n'
            '⏸️ Your automatic climb is paused until you clear the three-stage trial.\n'
            '🛡️ **Guard → 🎯 Focus → ⚔️ Attack**\n'
            'Open **/play → 🏰 Dungeon → Checkpoint** to complete it and continue climbing.\n'
            '💾 Your existing floor and progress are safe.'
        )
    except (discord.Forbidden, discord.HTTPException):
        logging.info('Could not DM checkpoint notification to %s (DMs may be disabled)', user.id)

async def notify_chambers(user, state):
    """DM once for newly discovered chambers, max once per 6 hours.

    Idle discoveries are calculated on /play or Refresh, not in real time.
    """
    chambers=state.get('chambers',[])
    if not chambers:return
    now=time.time()
    with game.open_db() as db:
        latest=game.get_player(db,user.id)
        if not latest:return
        last=float(latest.get('chamber_dm_sent',0))
        known=int(latest.get('chamber_notice_count',0))
        if now-last<21600 or len(chambers)<=known:return
        # Reserve notification before sending to avoid duplicate concurrent DMs.
        latest['chamber_dm_sent']=now
        latest['chamber_notice_count']=len(chambers)
        game.save_player(db,user.id,user.display_name,latest)
    try:
        await user.send('🏰 **ABYSS ASCENSION — MYSTERY CHAMBER DISCOVERED!**\n'
                        f'🎁 You have **{len(chambers)} chamber(s)** waiting!\n'
                        '⚔️ Your hero keeps climbing. Use **/play → 🏰 Mystery Chamber** to explore!')
    except (discord.Forbidden,discord.HTTPException):
        logging.info('Could not DM chamber notification to %s (DMs may be disabled)',user.id)

async def notify_goblin(user, state):
    """Notify at most once per shared six-hour window, on player check-in."""
    now=time.time()
    with game.open_db() as db:
        start=game.event_start(db)
        if start is None:return
        slot,attempts,claimed,_=game.goblin_status(state,start,now)
        if claimed or attempts>=2:return
        db.execute('BEGIN IMMEDIATE')
        try:
            latest=game.get_player(db,user.id)
            if latest is None or latest.get('goblin_dm_slot',-1)==slot:
                db.execute('COMMIT');return
            latest['goblin_dm_slot']=slot
            game.save_player(db,user.id,user.display_name,latest)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK');raise
    try:
        await user.send('👹 **ABYSS ASCENSION — TREASURE GOBLIN!**\n'
                        'A goblin is hiding in your dungeon! You have until the end of this six-hour window to catch it.\n'
                        'Use **/play → 🏰 Dungeon → Treasure Goblin** to solve its clue. Two attempts available!')
    except (discord.Forbidden,discord.HTTPException):
        logging.info('Could not DM goblin notification to %s',user.id)

async def notify_portals(user, state):
    """DM on check-in for newly found portals, not on every offline floor."""
    count=len(state.get('portals',[]))
    if not count:return
    with game.open_db() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            latest=game.get_player(db,user.id)
            if not latest:
                db.execute('COMMIT');return
            known=int(latest.get('portal_dm_count',0))
            if count<=known:
                db.execute('COMMIT');return
            latest['portal_dm_count']=count
            game.save_player(db,user.id,user.display_name,latest)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK');raise
    try:
        await user.send(f'🌀 **ABYSS ASCENSION — ABYSS PORTAL DISCOVERED!**\n'
                        f'You have **{count} portal(s)** waiting. Enter a three-stage mini-dungeon through '
                        '**/play → 🏰 Dungeon → Abyss Portals**. Your normal climb continues!')
    except (discord.Forbidden,discord.HTTPException):
        logging.info('Could not DM portal notification to %s',user.id)

async def show_player(interaction, screen='home', action=None):
    try:
        # Component defer (thinking=False) acknowledges the button and edits
        # the existing message, instead of creating a new ephemeral reply.
        await interaction.response.defer(thinking=False)
        with game.open_db() as db:
            if not game.get_player(db, interaction.user.id):
                return await send_private(interaction, embed=help_embed(), view=JoinView())
            s, notice = (game.mutate(db, interaction.user.id, interaction.user.display_name, action)
                         if action else game.refresh(db, interaction.user.id, interaction.user.display_name))
        s['_user_id']=interaction.user.id
        await interaction.edit_original_response(embed=player_embed(s, notice, screen), view=ChamberView(s) if screen=='chamber' else InventoryView(s) if screen=='inventory' else GameView(screen))
        # The UI has already been updated. Notification errors must not
        # overwrite a successful panel with a misleading generic error.
        for notify in (notify_boss, notify_checkpoint, notify_chambers, notify_goblin, notify_portals):
            try:
                await notify(interaction.user, s)
            except Exception:
                logging.exception('Post-update notification failed: %s user=%s',
                                  notify.__name__, interaction.user.id)
    except ValueError as exc:
        await send_private(interaction, content=f'⚠️ {exc}')
    except Exception:
        logging.exception('Game interaction failed: screen=%s action=%s user=%s',
                          screen, action, interaction.user.id)
        # Do not send a separate ephemeral error or erase a previously
        # successful panel update. Errors are logged in Railway.
        if not interaction.response.is_done():
            await interaction.response.send_message(
                '⚠️ Unable to load that menu. Please try /play again.', ephemeral=True)

class NavButton(discord.ui.Button):
    def __init__(self, label, screen, *, emoji=None, action=None, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, emoji=emoji, style=style,
                         custom_id=f'climber:v2:{screen}:{action or "nav"}')
        self.screen, self.action = screen, action
    async def callback(self, interaction):
        if self.screen=='help':
            await interaction.response.edit_message(embed=help_embed(), view=HelpView())
        elif self.screen=='rankings':
            await interaction.response.edit_message(embed=rankings_embed(), view=RankingsView())
        else:
            await show_player(interaction, self.screen, self.action)

class GameView(discord.ui.View):
    def __init__(self, screen='home'):
        super().__init__(timeout=None)
        if screen=='home':
            buttons=[('Refresh','home','🔄',None,discord.ButtonStyle.success),
                     ('Dungeon','dungeon','🏰',None,discord.ButtonStyle.primary),
                     ('Hero','hero','🧙',None,discord.ButtonStyle.primary),
                     ('Kingdom','kingdom','🏰',None,discord.ButtonStyle.primary),
                     ('Activities','activities_menu','🎯',None,discord.ButtonStyle.primary),
                     ('Info','info','📖',None,discord.ButtonStyle.secondary),
                     ('Help','help','📘',None,discord.ButtonStyle.success)]
        elif screen=='dungeon':
            buttons=[('Expedition','expedition','⚔️',None,discord.ButtonStyle.success),
                     ('Checkpoint','checkpoint','🏰',None,discord.ButtonStyle.primary),
                     ('Refresh','home','🔄',None,discord.ButtonStyle.success),
                     ('Boss Battle','boss','🐉',None,discord.ButtonStyle.danger),
                     ('Treasure Goblin','goblin','👹',None,discord.ButtonStyle.success),
                     ('Mystery Chamber','chamber','🏰',None,discord.ButtonStyle.primary),
                     ('Abyss Portals','portal','🌀',None,discord.ButtonStyle.primary)]
        elif screen=='hero':
            buttons=[('Build','build','🧙',None,discord.ButtonStyle.success),
                     ('Inventory','inventory','🎒',None,discord.ButtonStyle.primary),
                     ('Enchant','enchant','✨',None,discord.ButtonStyle.primary),
                     ('Relics','relics','💍',None,discord.ButtonStyle.primary),
                     ('Companions','pets','🐾',None,discord.ButtonStyle.primary),
                     ('Skill Tree','skills','🌳',None,discord.ButtonStyle.primary)]
        elif screen=='kingdom':
            buttons=[('Blacksmith','smith','⚒️',None,discord.ButtonStyle.primary),
                     ('Adventurer Camp','camp','🏕️',None,discord.ButtonStyle.primary),
                     ('Merchant','merchant','🧙',None,discord.ButtonStyle.primary)]
        elif screen=='activities_menu':
            buttons=[('Wheel','wheel','🎡',None,discord.ButtonStyle.success),
                     ('Quest Board','quests','📜',None,discord.ButtonStyle.primary),
                     ('Bounty & Vault','activities','🎯',None,discord.ButtonStyle.primary),
                     ('Arena Trials','arena','⚔️',None,discord.ButtonStyle.primary)]
        elif screen=='info':
            buttons=[('Adventurer Log','journal','📖',None,discord.ButtonStyle.success),('Help','help','📖',None,discord.ButtonStyle.primary),
                     ('Leaderboard','rankings','🏆',None,discord.ButtonStyle.primary)]
        elif screen=='journal':
            buttons=[('Back','info','⬅️',None,discord.ButtonStyle.secondary),('Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='build':
            buttons=[('Balanced','build','⚖️','build_balanced',discord.ButtonStyle.secondary),
                     ('Aggressive','build','⚔️','build_aggressive',discord.ButtonStyle.danger),
                     ('Defensive','build','🛡️','build_defensive',discord.ButtonStyle.primary),
                     ('Treasure','build','💰','build_treasure',discord.ButtonStyle.success),
                     ('Back','hero','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='expedition':
            buttons=[('Start','expedition','🚀','expedition_start',discord.ButtonStyle.success),
                     ('Fight','expedition','⚔️','expedition_fight',discord.ButtonStyle.danger),
                     ('Scout','expedition','🔎','expedition_scout',discord.ButtonStyle.primary),
                     ('Rest','expedition','🏕️','expedition_rest',discord.ButtonStyle.secondary),
                     ('Leave','expedition','🚪','expedition_leave',discord.ButtonStyle.secondary),
                     ('Back','dungeon','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='checkpoint':
            buttons=[('Guard','checkpoint','🛡️','checkpoint_guard',discord.ButtonStyle.primary),
                     ('Focus','checkpoint','🎯','checkpoint_focus',discord.ButtonStyle.success),
                     ('Attack','checkpoint','⚔️','checkpoint_attack',discord.ButtonStyle.danger),
                     ('Back','dungeon','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='inventory':
            buttons=[('Auto-Equip ON/OFF','inventory','🤖','gear_auto',discord.ButtonStyle.primary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='enchant':
            buttons=[('Lifesteal','enchant','🩸','gear_enchant_lifesteal',discord.ButtonStyle.success),
                     ('Critical','enchant','⚡','gear_enchant_critical',discord.ButtonStyle.primary),
                     ('Boss Slayer','enchant','🐉','gear_enchant_boss',discord.ButtonStyle.primary),
                     ('Treasure Finder','enchant','💰','gear_enchant_treasure',discord.ButtonStyle.primary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='portal':
            buttons=[('Enter Portal','portal','🌀','portal_enter',discord.ButtonStyle.success),
                     ('Blood Path','portal','🔴','portal_blood',discord.ButtonStyle.danger),
                     ('Golden Path','portal','🟡','portal_golden',discord.ButtonStyle.primary),
                     ('Mystic Path','portal','🔵','portal_mystic',discord.ButtonStyle.primary),
                     ('Leave Portal','portal','🚪','portal_leave',discord.ButtonStyle.secondary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='camp':
            buttons=[('Train Attack','camp','⚔️','camp_attack',discord.ButtonStyle.primary),
                     ('Train Defence','camp','🛡️','camp_defence',discord.ButtonStyle.primary),
                     ('Treasure Prep','camp','💰','camp_gold',discord.ButtonStyle.primary),
                     ('Rest & Heal','camp','❤️','camp_rest',discord.ButtonStyle.success),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='relics':
            buttons=[('Ember Sigil','relics','🔥','relic_ember',discord.ButtonStyle.primary),
                     ('Guardian Charm','relics','🛡️','relic_ward',discord.ButtonStyle.primary),
                     ('Fortune Coin','relics','💰','relic_fortune',discord.ButtonStyle.primary),
                     ('Vitality Stone','relics','❤️','relic_vigor',discord.ButtonStyle.primary),
                     ('Unequip','relics','🚫','relic_unequip',discord.ButtonStyle.secondary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='smith':
            buttons=[('Weapon +1','smith','⚔️','upgrade_weapon',discord.ButtonStyle.success),
                     ('Armour +1','smith','🛡️','upgrade_armour',discord.ButtonStyle.success),
                     ('Refine Weapon','smith','✨','refine_weapon',discord.ButtonStyle.primary),
                     ('Refine Armour','smith','💎','refine_armour',discord.ButtonStyle.primary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='activities':
            buttons=[('Daily Bounty','activities','📜','daily',discord.ButtonStyle.success),
                     ('Gauntlet','activities','🏟️','challenge',discord.ButtonStyle.primary),
                     ('Arena Trials','arena','⚔️',None,discord.ButtonStyle.success),
                     ('Treasure Vault','activities','🗝️','vault',discord.ButtonStyle.primary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='wheel':
            buttons=[('Spin the Wheel','wheel','🎡','wheel',discord.ButtonStyle.success),('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='quests':
            buttons=[('Claim Quest Chest','quests','🎁','quest_claim',discord.ButtonStyle.success),('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='goblin':
            buttons=[('Answer 1','goblin','1️⃣','goblin_0',discord.ButtonStyle.primary),('Answer 2','goblin','2️⃣','goblin_1',discord.ButtonStyle.primary),('Answer 3','goblin','3️⃣','goblin_2',discord.ButtonStyle.primary),('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='arena':
            buttons=[('Easy','arena','🟢','arena_easy',discord.ButtonStyle.success),
                     ('Hard','arena','🟠','arena_hard',discord.ButtonStyle.primary),
                     ('Nightmare','arena','🔴','arena_nightmare',discord.ButtonStyle.danger),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='pets':
            buttons=[('Wolf','pets','🐺','pet_wolf',discord.ButtonStyle.primary),
                     ('Bear','pets','🐻','pet_bear',discord.ButtonStyle.primary),
                     ('Owl','pets','🦉','pet_owl',discord.ButtonStyle.primary),
                     ('Dragon','pets','🐉','pet_dragon',discord.ButtonStyle.primary),
                     ('Upgrade Active','pets','✨','pet_upgrade',discord.ButtonStyle.success),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='skills':
            buttons=[('Warrior +1','skills','⚔️','skill_warrior',discord.ButtonStyle.primary),
                     ('Defender +1','skills','🛡️','skill_defender',discord.ButtonStyle.primary),
                     ('Treasure +1','skills','💰','skill_treasure',discord.ButtonStyle.primary),
                     ('Free Reset','skills','🔁','skill_reset',discord.ButtonStyle.secondary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='merchant':
            buttons=[('Buy Materials','merchant','🧱','merchant_materials',discord.ButtonStyle.success),
                     ('Buy Vault Key','merchant','🗝️','merchant_key',discord.ButtonStyle.primary),
                     ('Buy Gear','merchant','🎁','merchant_gear',discord.ButtonStyle.primary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        elif screen=='chamber':
            buttons=[('Golden Door','chamber','🟡','chamber_gold',discord.ButtonStyle.success),
                     ('Crimson Door','chamber','🔴','chamber_crimson',discord.ButtonStyle.danger),
                     ('Mystic Door','chamber','🔵','chamber_mystic',discord.ButtonStyle.primary),
                     ('Study Runes','chamber','📜','chamber_study',discord.ButtonStyle.primary),
                     ('Claim Relic','chamber','💎','chamber_claim',discord.ButtonStyle.success),
                     ('Leave','chamber','🕊️','chamber_leave',discord.ButtonStyle.secondary),
                     ('Attack Guardian','chamber','⚔️','chamber_attack',discord.ButtonStyle.danger),
                     ('Guard','chamber','🛡️','chamber_guard',discord.ButtonStyle.primary),
                     ('Retreat','chamber','🏃','chamber_retreat',discord.ButtonStyle.secondary),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        else:
            buttons=[('Attack','boss','⚔️','boss_attack',discord.ButtonStyle.primary),
                     ('Guard','boss','🛡️','boss_guard',discord.ButtonStyle.secondary),
                     ('Power Strike','boss','💥','boss_power',discord.ButtonStyle.danger),
                     ('Second Wind','boss','💚','boss_heal',discord.ButtonStyle.success),
                     ('Back','home','⬅️',None,discord.ButtonStyle.secondary)]
        if screen in CATEGORY_SCREENS:
            buttons.append(('Home','home','🏠',None,discord.ButtonStyle.secondary))
        elif screen in SCREEN_PARENT:
            parent=SCREEN_PARENT[screen]
            buttons=[(label,parent if label=='Back' else target,emoji,action,style)
                     for label,target,emoji,action,style in buttons]
            # Most submenus offer Back and Home; fit within Discord's five rows.
            if len(buttons)<24:
                buttons.append(('Home','home','🏠',None,discord.ButtonStyle.secondary))
        for label,screen,emoji,action,style in buttons:
            self.add_item(NavButton(label,screen,emoji=emoji,action=action,style=style))

class InventorySelect(discord.ui.Select):
    def __init__(self,s,kind):
        game.ensure_gear(s)
        items=game.gear_bag(s,kind)
        options=[discord.SelectOption(label=f"{x['name']} ({x['rarity']})"[:100],
                   description=f"{x['kind']} · {game.gear_stat(x)} power"[:100],value=x['id'],
                   emoji='🔒' if x.get('locked') else ('⚔️' if x['kind']=='weapon' else '🛡️')) for x in items[:25]]
        super().__init__(placeholder=f'Select {kind} to manage ({len(items)}/20)',options=options or [discord.SelectOption(label='No stored gear',value='empty')],row=1)
        self.disabled=not bool(items)
    async def callback(self,interaction):
        item_id=self.values[0]
        with game.open_db() as db:
            s=game.get_player(db,interaction.user.id)
        if not s:return await interaction.response.edit_message(content='⚠️ Use /play first.',embed=None,view=JoinView())
        item=next((x for x in s.get('inventory',[]) if x.get('id')==item_id),None)
        if not item:return await interaction.response.edit_message(content='⚠️ Item no longer available. Refresh inventory.',embed=None,view=InventoryView(s))
        current=s[item['kind']]
        e=discord.Embed(title=f"🎒 {item['name']} — {item['rarity']}",description=(
            f"**Selected:** {game.gear_stat(item)} power\n"
            f"**Equipped:** {current['name']} ({game.gear_stat(current)} power)\n"
            f"**Difference:** {game.gear_stat(item)-game.gear_stat(current):+} power\n"
            f"**Status:** {'🔒 Locked' if item.get('locked') else 'Unlocked'}\n"
            f"**Perk:** {item.get('perk') or 'None'} (+2% when active)\n\n"
            'Equipping preserves your paid slot upgrades and active enchantment.'),color=0x9471D8)
        await interaction.response.edit_message(embed=e,view=GearItemView(item_id))

class GearItemView(discord.ui.View):
    def __init__(self,item_id):
        super().__init__(timeout=180)
        for label,op,emoji,style in [('Equip','equip','⚔️',discord.ButtonStyle.success),
            ('Lock / Unlock','lock','🔒',discord.ButtonStyle.primary),
            ('Dismantle','scrap','♻️',discord.ButtonStyle.danger)]:
            button=discord.ui.Button(label=label,emoji=emoji,style=style)
            async def clicked(interaction,op=op):
                await show_player(interaction,'inventory',f'gear_{op}_{item_id}')
            button.callback=clicked
            self.add_item(button)
        back=discord.ui.Button(label='Back to Inventory',emoji='🎒',style=discord.ButtonStyle.secondary)
        async def go_back(interaction):await show_player(interaction,'inventory')
        back.callback=go_back;self.add_item(back)

class InventoryView(GameView):
    def __init__(self,s):
        super().__init__('inventory')
        self.add_item(InventorySelect(s,'weapon'))
        self.add_item(InventorySelect(s,'armour'))

class ChamberView(discord.ui.View):
    def __init__(self,s):
        super().__init__(timeout=900)
        chambers=s.get('chambers',[])
        kind=chambers[0]['kind'] if chambers else None
        options={'doors':[('Golden Door','🟡','gold'),('Crimson Door','🔴','crimson'),('Mystic Door','🔵','mystic')],
                 'relic':[('Study Runes','📜','study'),('Claim Relic','💎','claim'),('Leave','🕊️','leave')],
                 'guardian':[('Attack Guardian','⚔️','attack'),('Guard','🛡️','guard'),('Retreat','🏃','retreat')]}.get(kind,[])
        for label,emoji,action in options:
            self.add_item(NavButton(label,'chamber',emoji=emoji,action='chamber_'+action,style=discord.ButtonStyle.primary))
        self.add_item(NavButton('Back','dungeon',emoji='⬅️'))
        self.add_item(NavButton('Home','home',emoji='🏠'))

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NavButton('Start / Return to Game','home',emoji='⚔️',style=discord.ButtonStyle.success))
        self.add_item(NavButton('Leaderboard','rankings',emoji='🏆'))

class RankingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NavButton('Back to Game','home',emoji='🏠',style=discord.ButtonStyle.success))
        self.add_item(NavButton('Help','help',emoji='📖'))

async def assign_role(interaction):
    if not ROLE_ID or not interaction.guild:
        return
    try:
        role = interaction.guild.get_role(int(ROLE_ID))
        if role and isinstance(interaction.user, discord.Member) and role not in interaction.user.roles:
            await interaction.user.add_roles(role, reason='Joined Abyss Ascension')
    except (discord.Forbidden, discord.HTTPException, ValueError):
        logging.warning('Could not assign Abyss Ascension role; check Manage Roles and hierarchy')

class HeroSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='🧙 Choose your hero class to begin!', custom_id='climber:v2:class',
                         options=[discord.SelectOption(label='Berserker',description='⚔️ Powerful attacks',emoji='⚔️'),
                                  discord.SelectOption(label='Guardian',description='🛡️ Strong defence and health',emoji='🛡️'),
                                  discord.SelectOption(label='Rogue',description='🗡️ Swift, balanced fighter',emoji='🗡️')])
    async def callback(self, interaction):
        try:
            with game.open_db() as db:
                existing=game.get_player(db,interaction.user.id)
                s=existing or game.create_player(db,interaction.user.id,interaction.user.display_name,self.values[0])
            await assign_role(interaction)
            await interaction.response.edit_message(embed=player_embed(s,'🎉 Hero created! Welcome to the dungeon.'),view=GameView())
        except ValueError as exc:
            await send_private(interaction,content=f'⚠️ {exc}')
        except Exception:
            logging.exception('Character creation failed')
            await send_private(interaction,content='⚠️ Could not create hero. Please try again.')

class ClassView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HeroSelect())
        self.add_item(NavButton('Read Quick Start','help',emoji='📖'))

class JoinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='⚔️ JOIN ABYSS ASCENSION ⚔️',style=discord.ButtonStyle.success,
                         custom_id='climber:v2:join',row=0)
    async def callback(self,interaction):
        with game.open_db() as db:
            existing=game.get_player(db,interaction.user.id)
        if existing:
            await assign_role(interaction)
            return await send_private(interaction,embed=player_embed(existing),view=GameView())
        await send_private(interaction,embed=discord.Embed(
            title='🧙✨ CREATE YOUR HERO!',
            description='## 🚀 YOUR ADVENTURE STARTS HERE!\nPick a class below. Your hero will begin climbing automatically.\n\n⚔️ **Berserker** — Heavy damage\n🛡️ **Guardian** — High health & defence\n🗡️ **Rogue** — Swift balanced fighter\n\n💡 Need guidance? Press **Read Quick Start**.',color=GOLD),view=ClassView())

class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(JoinButton())
        self.add_item(NavButton('HOW TO PLAY','help',emoji='📖',style=discord.ButtonStyle.primary))
        self.add_item(NavButton('VIEW PRIZES & LEADERBOARD','rankings',emoji='🏆'))

class ResetGameConfirmView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=60)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not interaction.guild or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message('🔒 Only the administrator who requested this reset can confirm it.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Confirm full reset', style=discord.ButtonStyle.danger, emoji='🗑️')
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            with game.open_db() as db:
                removed = game.reset_entire_game(db)
        except Exception:
            logging.exception('Full game reset failed')
            await interaction.edit_original_response(content='⚠️ Reset failed. Check Railway logs; no reset success was confirmed.', view=None)
            return
        logging.warning('Full Abyss Ascension reset by admin %s; %s player saves removed', interaction.user.id, removed)
        await interaction.edit_original_response(content=(
            f'✅ **Abyss Ascension has been reset.** Removed **{removed}** player saves, leaderboard entries and journal records. '
            'The seven-day countdown will restart when the next player joins, unless `EVENT_START_UTC` is set.'), view=None)
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary, emoji='✖️')
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content='Reset cancelled. No data was changed.', view=None)
        self.stop()


@bot.tree.command(name='resetgame', description='ADMIN ONLY: erase all game progress and restart the event')
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def resetgame(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message('🔒 Manage Server permission is required.', ephemeral=True)
        return
    with game.open_db() as db:
        player_count = db.execute('SELECT COUNT(*) FROM players').fetchone()[0]
    await interaction.response.send_message(
        '⚠️ **FULL GAME RESET — IRREVERSIBLE**\n\n'
        f'This will permanently erase **{player_count}** player saves, all inventory, floors, levels, '
        'leaderboard progress and Adventurer Log history. It also clears the database event start, '
        'so the seven-day countdown begins again when the next player joins.\n\n'
        '**This does not remove a configured `EVENT_START_UTC` environment variable.**\n\n'
        'Confirm below within 60 seconds, or cancel.',
        view=ResetGameConfirmView(interaction.user.id), ephemeral=True)


@bot.tree.command(name='play',description='Play Abyss Ascension or publish the public join panel')
@app_commands.describe(panel='Publish the large public join panel (server administrators only)')
async def play(interaction:discord.Interaction,panel:bool=False):
    if panel:
        if not interaction.guild or not isinstance(interaction.user,discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await send_private(interaction,content='🔒 Only server administrators with Manage Server can publish the join panel.')
        await interaction.response.send_message(embed=panel_embed(),view=JoinView())
        return
    with game.open_db() as db:
        s=game.get_player(db,interaction.user.id)
    if s:
        with game.open_db() as db:s,notice=game.refresh(db,interaction.user.id,interaction.user.display_name)
        s['_user_id']=interaction.user.id
        await send_private(interaction,embed=player_embed(s,notice),view=GameView())
        await notify_boss(interaction.user,s)
        await notify_checkpoint(interaction.user,s)
        await notify_chambers(interaction.user,s)
        await notify_goblin(interaction.user,s)
        await notify_portals(interaction.user,s)
    else:
        await send_private(interaction,embed=discord.Embed(
            title='🏰⚔️ WELCOME TO ABYSS ASCENSION!',
            description='## 🚀 CREATE YOUR HERO!\nSelect your class below and start your seven-day adventure.\n\n📖 New player? Tap **Read Quick Start** for an easy guide.',color=GOLD),view=ClassView())

@tasks.loop(minutes=5)
async def send_adventure_digests():
    now=game.utcnow()
    try:
        with game.open_db() as db:
            start,end=game.event_window(db,now)
            if start is None or now < start or (end is not None and now >= end):return
            players=db.execute('SELECT user_id,username FROM players').fetchall()
        for row in players:
            uid=row['user_id']
            try:
                with game.open_db() as db:
                    jr=game.journal_row(db,uid,now)
                    if jr is None or now < jr['started_at']+game.JOURNAL_SECONDS or now-jr['last_attempt'] < game.JOURNAL_SECONDS:
                        continue
                    # Save the attempt before network I/O to prevent DM spam on failures.
                    game.journal_mark_attempt(db,uid,now)
                    s,_=game.refresh(db,uid,row['username'],now)
                    report=game.journal_stats(db,uid,s,now)
                user=bot.get_user(uid) or await bot.fetch_user(uid)
                await user.send(embed=journal_dm_embed(s,report))
                with game.open_db() as db:
                    game.journal_mark_sent(db,uid,s,now)
            except (discord.Forbidden,discord.HTTPException):
                logging.info('Adventurer log DM unavailable for user %s',uid)
            except Exception:
                logging.exception('Adventurer log delivery failed for user %s',uid)
    except Exception:
        logging.exception('Adventurer log scheduler failed')

@send_adventure_digests.before_loop
async def wait_for_adventure_bot():
    await bot.wait_until_ready()

@bot.event
async def setup_hook():
    if not send_adventure_digests.is_running():send_adventure_digests.start()
    for view in (JoinView(),ClassView(),GameView('home'),GameView('dungeon'),GameView('hero'),GameView('kingdom'),GameView('activities_menu'),GameView('info'),GameView('smith'),GameView('activities'),
                 GameView('journal'),GameView('boss'),GameView('arena'),GameView('pets'),GameView('skills'),GameView('merchant'),GameView('wheel'),GameView('quests'),GameView('enchant'),HelpView(),RankingsView()):
        bot.add_view(view)
    if GUILD_ID:
        guild=discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()

@bot.event
async def on_ready():
    logging.info('Abyss Ascension online as %s',bot.user)

if __name__=='__main__':
    if not TOKEN:
        raise SystemExit('DISCORD_TOKEN is required.')
    bot.run(TOKEN)
