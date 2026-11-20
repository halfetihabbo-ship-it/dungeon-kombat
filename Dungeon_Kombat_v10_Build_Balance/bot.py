"""Abyss Ascension: single /play command, public join panel, private interactive menus."""
import logging
import time
import os
import discord
from discord import app_commands
from discord.ext import commands
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
    e = discord.Embed(
        title='📖⚔️ ABYSS ASCENSION — HELP & QUICK START',
        description=(
            '## 🚀 QUICK START — ONLY 3 STEPS!\n'
            '**1️⃣ CHOOSE YOUR HERO** — Berserker ⚔️, Guardian 🛡️ or Rogue 🗡️.\n'
            '**2️⃣ LET YOUR HERO CLIMB** — Battles happen automatically every **15 seconds** when progress is processed.\n'
            '**3️⃣ CHECK BACK & GET STRONGER** — Collect loot, upgrade equipment and defeat bosses!\n\n'
            '## 🧭 WHAT SHOULD I DO NEXT?\n'
            '🏠 **Home** — View your floor, health, loot and latest progress.\n'
            '⚒️ **Blacksmith** — Upgrade weapon/armour (+1 to +10), refine endlessly from Floor 100.\n'
            '🎯 **Activities** — Daily Bounty, Gauntlet, Arena Trials and Treasure Vault.\n'
            '🏰 **Mystery Chambers** — Discover them as you climb; get a DM at check-in, then choose a reward.\n'
            '🌀 **Abyss Portals** — Discover optional 3-stage portals while climbing. Receive a Discord DM at check-in; choose Blood, Golden or Mystic paths.\n'
            '🏕️ **Adventurer Camp** — Spend gold/materials on a 60-minute Attack, Defence or Gold buff, or rest to restore HP.\n'
            '💍 **Relic Collection** — Collect relics from completed portals; equip one permanent passive bonus at a time.\n'
            '🎒 **Inventory** — Store up to 20 weapons and 20 armour pieces; equip, lock or dismantle gear, and toggle auto-equip.\n'
            '✨ **Enchanting** — Select a hero-bound bonus that stays active when your weapon changes. Changing costs 1,200 gold and 15 materials.\n'
            '🎡 **Wheel** — one spin every six hours.\n'
            '👹 **Treasure Goblin** — personal six-hour clue challenge; two attempts.\n'
            '📜 **Quest Board** — three daily goals for a bonus chest.\n'
            '🐾 **Companions** — Unlock, equip and upgrade a battle companion.\n'
            '🌳 **Skill Tree** — Earn one skill point every 5 levels; free resets.\n'
            '🧙 **Merchant** — Shop for materials, gear and Vault Keys; stock refreshes every 6 hours.\n'
            '🐉 **Boss Battle** — Legendary boss every 50 floors. Use Attack, Guard, Power Strike and Second Wind.\n'
            '🏆 **Leaderboard** — See who is leading the competition.\n\n'
            '## 💡 IMPORTANT TIPS\n'
            '🌙 Offline progress counts for up to **8 hours** when you return.\n'
            '💰 Stuck on a floor? Your hero farms resources and gets stronger.\n'
            '🎁 Every 10 floors brings a milestone chest.\n'
            '🗝️ Vault Keys unlock treasure rewards.\n'
            '🛡️ Better gear is auto-equipped by default unless your equipped item is locked.\n'
            '🔁 Use **Refresh** to collect your latest idle progress.\n'
             '🏁 The highest floor after **7 days** wins; ties go to whoever reached it first.'
        ), color=PURPLE)
    e.add_field(name='🎁 PRIZES', value=prize_text(), inline=False)
    e.set_footer(text='Everything is controlled from /play — no other commands needed!')
    return e

def player_embed(s, notice='', screen='home'):
    titles = {'home': '🏰⚔️ YOUR DUNGEON ADVENTURE', 'smith': '⚒️🔥 THE ROYAL BLACKSMITH',
              'activities': '🎯✨ QUESTS & TREASURE', 'wheel':'🎡✨ WHEEL OF FORTUNE', 'quests':'📜✨ DAILY QUEST BOARD', 'chamber': '🏰✨ MYSTERY CHAMBER', 'arena':'🏟️⚔️ ARENA TRIALS', 'pets':'🐾✨ COMPANIONS', 'skills':'🌳✨ SKILL TREE', 'merchant':'🧙🛒 TRAVELLING MERCHANT', 'goblin':'👹💰 TREASURE GOBLIN', 'boss': '🐉🔥 LEGENDARY BOSS', 'inventory':'🎒⚔️ HERO INVENTORY', 'enchant':'✨ WEAPON ENCHANTING'}
    e = discord.Embed(title=titles.get(screen, titles['home']), description=stats(s), color=GOLD if screen=='home' else PURPLE)
    if screen=='home':
        if s.get('chambers'):
            e.add_field(name='🚨🏰 MYSTERY CHAMBER DISCOVERED!',value=f'**{len(s["chambers"])} unclaimed chamber(s)!** Tap 🏰 Mystery Chamber to explore. Your hero keeps climbing!',inline=False)
        e.add_field(name='👹 TREASURE GOBLIN',value='A personal goblin appears every **6 hours**. Check the Goblin menu to solve its clue and claim your loot!',inline=False)
        e.add_field(name='🎡 DAILY ACTIVITIES',value='🎡 **Wheel of Fortune** — spin every 6 hours.\n📜 **Quest Board** — 3 daily goals and a bonus chest.',inline=False)
        e.add_field(name='🗺️ YOUR ADVENTURE',
                    value=('🔴 **A LEGENDARY BOSS IS WAITING!** Open **🐉 Boss Battle**.' if s['boss']
                           else '🟢 **AUTO-CLIMB ACTIVE!** Your hero is battling or farming.'), inline=False)
        e.add_field(name='🗡️ EQUIPMENT',
                    value=(f'⚔️ **{s["weapon"]["name"]}**  +{s["weapon"]["plus"]} · R{s["weapon"]["refine"]}\n'
                           f'🛡️ **{s["armour"]["name"]}**  +{s["armour"]["plus"]} · R{s["armour"]["refine"]}'), inline=False)
        e.add_field(name='🚀 WHAT TO DO NEXT',
                    value='**1.** 🔄 Refresh to claim progress.\n**2.** ⚒️ Upgrade gear; 🌳 spend skill points.\n**3.** 🐾 Equip a companion; 🏟️ try the Arena.\n**4.** 🐉 Fight bosses and 🏰 explore chambers.', inline=False)
        e.add_field(name='📜 LATEST ADVENTURE REPORT', value=(notice or s.get('last_report') or 'Your journey begins!')[:1024], inline=False)
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
    if notice and screen!='home':
        e.add_field(name='📣 LATEST RESULT', value=notice[:1024], inline=False)
    e.set_footer(text='⚔️ Battles: 15 seconds • 🌙 Offline: 8 hours • 🏆 7-day event • 📖 Help available')
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
                        'Use **/play → 👹 Treasure Goblin** to solve its clue. Two attempts available!')
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
                        '**/play → 🌀 Abyss Portals**. Your normal climb continues!')
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
        await interaction.edit_original_response(embed=player_embed(s, notice, screen), view=ChamberView(s) if screen=='chamber' else InventoryView(s) if screen=='inventory' else GameView(screen))
        await notify_chambers(interaction.user, s)
        await notify_goblin(interaction.user, s)
        await notify_portals(interaction.user, s)
    except ValueError as exc:
        await send_private(interaction, content=f'⚠️ {exc}')
    except Exception:
        logging.exception('Game interaction failed')
        await send_private(interaction, content='⚠️ Something went wrong. Please try again.')

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
                     ('Blacksmith','smith','⚒️',None,discord.ButtonStyle.primary),
                     ('Activities','activities','🎯',None,discord.ButtonStyle.primary),
                     ('Wheel','wheel','🎡',None,discord.ButtonStyle.success),
                     ('Quest Board','quests','📜',None,discord.ButtonStyle.primary),
                     ('Treasure Goblin','goblin','👹',None,discord.ButtonStyle.success),
                     ('Inventory','inventory','🎒',None,discord.ButtonStyle.primary),
                     ('Enchant','enchant','✨',None,discord.ButtonStyle.primary),
                      ('Mystery Chamber','chamber','🏰',None,discord.ButtonStyle.success),
                     ('Abyss Portals','portal','🌀',None,discord.ButtonStyle.success),
                     ('Adventurer Camp','camp','🏕️',None,discord.ButtonStyle.primary),
                     ('Relic Collection','relics','💍',None,discord.ButtonStyle.primary),
                     ('Companions','pets','🐾',None,discord.ButtonStyle.primary),
                     ('Skill Tree','skills','🌳',None,discord.ButtonStyle.primary),
                     ('Merchant','merchant','🧙',None,discord.ButtonStyle.primary),
                     ('Boss Battle','boss','🐉',None,discord.ButtonStyle.danger),
                     ('Help','help','📖',None,discord.ButtonStyle.secondary),
                     ('Leaderboard','rankings','🏆',None,discord.ButtonStyle.secondary)]
        elif screen=='inventory':
            buttons=[('Auto-Equip ON/OFF','inventory','🤖','gear_auto',discord.ButtonStyle.primary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='enchant':
            buttons=[('Lifesteal','enchant','🩸','gear_enchant_lifesteal',discord.ButtonStyle.success),
                     ('Critical','enchant','⚡','gear_enchant_critical',discord.ButtonStyle.primary),
                     ('Boss Slayer','enchant','🐉','gear_enchant_boss',discord.ButtonStyle.primary),
                     ('Treasure Finder','enchant','💰','gear_enchant_treasure',discord.ButtonStyle.primary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='portal':
            buttons=[('Enter Portal','portal','🌀','portal_enter',discord.ButtonStyle.success),
                     ('Blood Path','portal','🔴','portal_blood',discord.ButtonStyle.danger),
                     ('Golden Path','portal','🟡','portal_golden',discord.ButtonStyle.primary),
                     ('Mystic Path','portal','🔵','portal_mystic',discord.ButtonStyle.primary),
                     ('Leave Portal','portal','🚪','portal_leave',discord.ButtonStyle.secondary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='camp':
            buttons=[('Train Attack','camp','⚔️','camp_attack',discord.ButtonStyle.primary),
                     ('Train Defence','camp','🛡️','camp_defence',discord.ButtonStyle.primary),
                     ('Treasure Prep','camp','💰','camp_gold',discord.ButtonStyle.primary),
                     ('Rest & Heal','camp','❤️','camp_rest',discord.ButtonStyle.success),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='relics':
            buttons=[('Ember Sigil','relics','🔥','relic_ember',discord.ButtonStyle.primary),
                     ('Guardian Charm','relics','🛡️','relic_ward',discord.ButtonStyle.primary),
                     ('Fortune Coin','relics','💰','relic_fortune',discord.ButtonStyle.primary),
                     ('Vitality Stone','relics','❤️','relic_vigor',discord.ButtonStyle.primary),
                     ('Unequip','relics','🚫','relic_unequip',discord.ButtonStyle.secondary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='smith':
            buttons=[('Weapon +1','smith','⚔️','upgrade_weapon',discord.ButtonStyle.success),
                     ('Armour +1','smith','🛡️','upgrade_armour',discord.ButtonStyle.success),
                     ('Refine Weapon','smith','✨','refine_weapon',discord.ButtonStyle.primary),
                     ('Refine Armour','smith','💎','refine_armour',discord.ButtonStyle.primary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='activities':
            buttons=[('Daily Bounty','activities','📜','daily',discord.ButtonStyle.success),
                     ('Gauntlet','activities','🏟️','challenge',discord.ButtonStyle.primary),
                     ('Arena Trials','arena','⚔️',None,discord.ButtonStyle.success),
                     ('Treasure Vault','activities','🗝️','vault',discord.ButtonStyle.primary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='wheel':
            buttons=[('Spin the Wheel','wheel','🎡','wheel',discord.ButtonStyle.success),('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='quests':
            buttons=[('Claim Quest Chest','quests','🎁','quest_claim',discord.ButtonStyle.success),('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='goblin':
            buttons=[('Answer 1','goblin','1️⃣','goblin_0',discord.ButtonStyle.primary),('Answer 2','goblin','2️⃣','goblin_1',discord.ButtonStyle.primary),('Answer 3','goblin','3️⃣','goblin_2',discord.ButtonStyle.primary),('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='arena':
            buttons=[('Easy','arena','🟢','arena_easy',discord.ButtonStyle.success),
                     ('Hard','arena','🟠','arena_hard',discord.ButtonStyle.primary),
                     ('Nightmare','arena','🔴','arena_nightmare',discord.ButtonStyle.danger),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='pets':
            buttons=[('Wolf','pets','🐺','pet_wolf',discord.ButtonStyle.primary),
                     ('Bear','pets','🐻','pet_bear',discord.ButtonStyle.primary),
                     ('Owl','pets','🦉','pet_owl',discord.ButtonStyle.primary),
                     ('Dragon','pets','🐉','pet_dragon',discord.ButtonStyle.primary),
                     ('Upgrade Active','pets','✨','pet_upgrade',discord.ButtonStyle.success),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='skills':
            buttons=[('Warrior +1','skills','⚔️','skill_warrior',discord.ButtonStyle.primary),
                     ('Defender +1','skills','🛡️','skill_defender',discord.ButtonStyle.primary),
                     ('Treasure +1','skills','💰','skill_treasure',discord.ButtonStyle.primary),
                     ('Free Reset','skills','🔁','skill_reset',discord.ButtonStyle.secondary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='merchant':
            buttons=[('Buy Materials','merchant','🧱','merchant_materials',discord.ButtonStyle.success),
                     ('Buy Vault Key','merchant','🗝️','merchant_key',discord.ButtonStyle.primary),
                     ('Buy Gear','merchant','🎁','merchant_gear',discord.ButtonStyle.primary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
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
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        else:
            buttons=[('Attack','boss','⚔️','boss_attack',discord.ButtonStyle.primary),
                     ('Guard','boss','🛡️','boss_guard',discord.ButtonStyle.secondary),
                     ('Power Strike','boss','💥','boss_power',discord.ButtonStyle.danger),
                     ('Second Wind','boss','💚','boss_heal',discord.ButtonStyle.success),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
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
        self.add_item(NavButton('Back to Home','home',emoji='🏠'))

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
        await send_private(interaction,embed=player_embed(s,notice),view=GameView())
        await notify_chambers(interaction.user,s)
    else:
        await send_private(interaction,embed=discord.Embed(
            title='🏰⚔️ WELCOME TO ABYSS ASCENSION!',
            description='## 🚀 CREATE YOUR HERO!\nSelect your class below and start your seven-day adventure.\n\n📖 New player? Tap **Read Quick Start** for an easy guide.',color=GOLD),view=ClassView())

@bot.event
async def setup_hook():
    for view in (JoinView(),ClassView(),GameView('home'),GameView('smith'),GameView('activities'),
                 GameView('boss'),GameView('arena'),GameView('pets'),GameView('skills'),GameView('merchant'),GameView('wheel'),GameView('quests'),GameView('enchant'),HelpView(),RankingsView()):
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
