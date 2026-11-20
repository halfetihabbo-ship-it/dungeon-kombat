"""Dungeon Master Discord bot. Requires discord.py 2.4+.
Run: DISCORD_TOKEN=... python bot.py
Commands: /play, /leaderboard, /help, /admin_start, /admin_stop.
"""
import os, asyncio, datetime, time, logging, sqlite3, json, random, math
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dungeon_master_engine import Engine, Room, MONSTERS, TRAPS, PATTERNS, PVP_SECONDS, MAX_ROOMS, ROOM_UNLOCK_LEVELS

logging.basicConfig(level=logging.INFO)
TOKEN=os.environ['DISCORD_TOKEN']
DB_PATH=os.getenv('DB_PATH','dungeon_master.sqlite3')
Path(DB_PATH).parent.mkdir(parents=True,exist_ok=True)
START=datetime.datetime.fromisoformat(os.getenv('EVENT_START','2026-11-22T00:00:00+00:00').replace('Z','+00:00')).timestamp()
DURATION=int(os.getenv('EVENT_DAYS','7'))*86400
GUILD_ID=os.getenv('GUILD_ID')
engine=Engine(DB_PATH)
lock=asyncio.Lock()
client=commands.Bot(command_prefix='!',intents=discord.Intents.default())

def active(): return START<=time.time()<START+DURATION
def event_day(now=None): return max(0,int(((now or time.time())-START)//86400))

def get(uid):
    try:return engine.load(str(uid))
    except KeyError:return None

def notification_enabled(uid):
    row=engine.db.execute('SELECT data FROM events WHERE id=?',(f'dm_notify:{uid}',)).fetchone()
    return bool(json.loads(row[0]).get('enabled',True)) if row else True

def next_raid_time(p):
    if p.wave>=336:return None
    # First wave is 30 minutes AFTER event start, not at the starting instant.
    scheduled=START+(p.wave+1)*1800
    row=engine.db.execute('SELECT data FROM events WHERE id=?',(f'joined_at:{p.id}',)).fetchone()
    if row:
        joined=json.loads(row[0])['at']
        scheduled=max(scheduled,joined+1800)
    return scheduled

def next_raid_text(p):
    due=next_raid_time(p)
    if due is None:return 'All 336 invasions completed.'
    return f'**<t:{int(due)}:R>** (<t:{int(due)}:t> local time)'

def display(p):
    e=discord.Embed(title='🏰 YOUR DUNGEON',description=f'**Level {p.level()}/75**  •  🪙 **{p.gold:,} Gold**  •  ✨ **{p.xp:,} XP**\n🏆 **{p.points:,} points**  •  💎 **{p.shards:,} shards**',color=0x5865F2)
    # Five starter rooms are intentionally granted at registration. The level-based
    # capacity is for EXTRA rooms, not a limit retroactively applied to starter rooms.
    built=len(p.rooms)
    unlocked=max(built,min(MAX_ROOMS,p.capacity()))
    next_unlock=ROOM_UNLOCK_LEVELS[built] if built<MAX_ROOMS else None
    room_status=f'{built}/{MAX_ROOMS} rooms built · {unlocked} room slots available'
    if next_unlock and p.level()<next_unlock:room_status+=f' · Next room unlocks at Lv{next_unlock}'
    elif next_unlock:room_status+=' · You can build another room now!'
    e.add_field(name='🏗️ Your defences',value=f'**{built} rooms** • {p.style} build • ⚡ Power **{p.power():.0f}**\n{room_status}',inline=False)
    e.add_field(name='🛡️ Invasions survived',value=f'**{p.wave}/336** waves',inline=True)
    if p.wave<336:
        q=engine.next_preview(p.id)
        e.add_field(name='⏳ Prepare for your next battle',value=f"**{next_raid_text(p)}**\n**Wave {q['wave']}** · {q['enemy_type']} enemies\n💡 {q['hint']}\n🔔 Alerts {'ON' if notification_enabled(p.id) else 'OFF'}",inline=False)
    e.set_footer(text='💡 New? Tap Quick Start. Upgrade a room before the next wave!')
    return e

def help_embed(section='overview'):
    e=discord.Embed(title='📖 Dungeon Master — Guide',color=0x7d5fff)
    pages={
      'overview':('Welcome to Dungeon Master','Build and defend a dungeon during a **seven-day competition**. NPC invasions occur every **30 minutes**, even while you are offline. Earn leaderboard points and finish in the top three.\n\n**Getting started**\n1. Use `/play` to open your private dashboard.\n2. Add rooms and configure monsters/traps.\n3. Upgrade and arrange rooms to counter the next invasion.\n4. Claim missions, raid fortresses and challenge other players.\n\n**Tip:** The dashboard shows the next raid time. Use **Raid Alerts** to turn 30-minute DM reminders on or off. Discord privacy settings may block DMs.'),
      'building':('Building & upgrades','Use **Build & Upgrade** → **Change Build** to choose **Balanced, Swarm, Fortress, Curse or Dragon**. Your gold, XP, room levels, monster levels and trap levels are preserved. The monsters and traps in your rooms are replaced to match your chosen style.\n\nUse **Dungeon** → **Add Room** to expand. Select a room from **Dungeon** → **Upgrade Rooms** to improve its monster, trap or room structure.\n\nUse `/configure` to change a room’s monster or trap, and `/reorder` to swap defensive positions. `/rooms` displays the current order.\n\n**Room slots:** Everyone starts with five rooms; the sixth unlocks at **Level 4**, then more slots unlock as you progress.\n\n**Limits:** 15 rooms, monster Lv30, trap Lv20, room Lv15, dungeon master Lv75. Deployment budgets and stacking restrictions prevent excessive combinations.'),
      'combat':('NPC invasions & combat','An NPC invasion is scheduled every **30 minutes** for up to **336 waves** across seven days. Your dashboard previews the upcoming enemy and its threat. Prepare the right room order, monsters and traps.\n\nDefences are processed automatically, including when you are offline. The wave results award resources and leaderboard points according to performance.\n\n**Raid alerts:** The bot can DM you **30 minutes before** each upcoming NPC invasion. Toggle them using `/notifications` or **Raid Alerts** on the main menu. Keep DMs from server members enabled.'),
      'activities':('Raids, PvP & missions','**Fortress Raid:** Repeatable activity with a 20-minute cooldown. Up to 12 rewarded raids per day; leaderboard points from the first six successful raids.\n\n**PvP Raid:** Once every six hours, against an eligible opponent within approximately ±10% dungeon power. Recon identifies the defender’s style.\n\n**Daily Mission:** Defend at least two invasions that event day, then claim the daily reward.'),
      'scoring':('Leaderboard & event rules','Use `/leaderboard` to see the standings. NPC defences are the main source of leaderboard points. PvP and fortress activities provide additional opportunities.\n\nThe competition runs for seven days from the event start. Use `/winners` after the event to see the final top three.\n\n**Commands:** `/play`, `/help`, `/rooms`, `/configure`, `/reorder`, `/leaderboard`, `/winners`.'),
    }
    title,description=pages.get(section,pages['overview']);e.add_field(name=title,value=description,inline=False)
    e.set_footer(text='Use the navigation buttons below to explore the guide.')
    return e

class MenuButton(discord.ui.Button):
    def __init__(self,label,action,row=0,style=discord.ButtonStyle.secondary):
        super().__init__(label=label,style=style,row=row);self.action=action
    async def callback(self,i):
        await i.response.defer()  # Acknowledge button immediately; edit after processing.
        await self.view.handle(i,self.action)

class RoomPicker(discord.ui.Select):
    def __init__(self,rooms):
        options=[discord.SelectOption(label=f'Room {n}: {r.monster} / {r.trap}'[:100],value=str(n-1),description=f'M{r.monster_level} · T{r.trap_level} · R{r.level}') for n,r in enumerate(rooms,1)]
        super().__init__(placeholder='Select a room to upgrade',options=options[:25],row=0)
    async def callback(self,i):
        await i.response.defer()
        self.view.selected=int(self.values[0]);await self.view.render(i,notice=f'Selected room {self.view.selected+1}.')

class Management(discord.ui.View):
    def __init__(self,owner,mode='main',selected=None):
        super().__init__(timeout=600);self.owner=str(owner);self.mode=mode;self.selected=selected
        if mode=='room':
            p=get(owner)
            valid=p is not None and self.selected is not None and 0<=self.selected<len(p.rooms)
            if not valid:
                if p and p.rooms:self.add_item(RoomPicker(p.rooms))
                buttons=[('Back to Dungeon','dungeon',1),('Help','help',1)]
            else:
                buttons=[('Monster +','monster',0),('Trap +','trap',0),('Room +','room',0),('Change Room','change_room',1),('Back to Dungeon','dungeon',1),('Help','help',2)]
        elif mode=='dungeon':
            buttons=[('⬆️ Upgrade Rooms','room_menu',0),('➕ Add Room','add',0),('🎭 Change Build','builds',1),('📋 Room Order','order',1),('⬅️ Back','main',2),('📖 Help','help',2)]
        elif mode=='builds':
            buttons=[('⚖️ Balanced','style:Balanced',0),('🐺 Swarm','style:Swarm',0),('🛡️ Fortress','style:Fortress',1),('🔮 Curse','style:Curse',1),('🐉 Dragon','style:Dragon',2),('⬅️ Back','dungeon',3)]
        elif mode=='activities':
            buttons=[('Fortress Raid','fortress',0),('PvP Raid','pvp',0),('Daily Mission','mission',1),('Back','main',2),('Help','help',2)]
        elif mode=='help':
            buttons=[('Overview','overview',0),('Building','building',0),('Combat','combat',1),('Activities','activities_help',1),('Scoring','scoring',2),('Back','main',3)]
        else:
            buttons=[('🚀 QUICK START — PLAY HERE','quickstart',0),('🏰 Build & Upgrade','dungeon',1),('⚔️ Go Adventuring','activities',1),('🎭 Change Build','builds',2),('🏆 My Progress','progress',2),('📖 Help','help',3),('🔔 Raid Alerts','alerts',3),('🔄 Refresh','refresh',4),('🚪 Exit','exit',4)]
        for label,action,row in buttons:
            style=discord.ButtonStyle.primary if action in ('dungeon','activities','room_menu','quickstart','builds') else discord.ButtonStyle.secondary
            if action=='exit':style=discord.ButtonStyle.danger
            self.add_item(MenuButton(label,action,row,style))
    async def interaction_check(self,i):
        if str(i.user.id)!=self.owner:
            await i.response.send_message('This is not your dungeon.',ephemeral=True);return False
        return True
    async def render(self,i,mode=None,notice=None,selected=None):
        mode=mode or self.mode
        view=Management(self.owner,mode,self.selected if selected is None else selected)
        p=get(self.owner)
        embed=help_embed() if mode=='help' else display(p)
        if mode=='main':notice=notice or ('**🚀 QUICK START — YOUR NEXT MOVE**\n1️⃣ Tap **Build & Upgrade** to strengthen your rooms.\n2️⃣ Try **Go Adventuring** to earn extra rewards.\n3️⃣ Be ready for the next invasion '+next_raid_text(p)+'\n\n✨ Tap **Quick Start** for a guided walkthrough.')
        if mode=='builds':notice=notice or f'🎭 **Choose your build!** Current: **{p.style}**. Selecting a style replaces room monsters and traps but keeps all your upgrade levels, gold, XP and progress.\n\n⚖️ Balanced: versatile · 🐺 Swarm: numbers · 🛡️ Fortress: defence · 🔮 Curse: debuffs · 🐉 Dragon: powerful legendary.'
        if mode=='dungeon':notice=notice or '🏰 **Build your defence:** **Upgrade Rooms** lets you select one room and keep upgrading it. **Add Room** expands your dungeon when unlocked. Everyone starts with five rooms; your sixth unlocks at Level 4. Use **Change Build** to switch your defence style without losing upgrades. **Room Order** shows the sequence attackers face. Use `/configure` to swap monsters/traps and `/reorder` to swap positions.'
        if mode=='room':
            if view.selected is not None and p and 0<=view.selected<len(p.rooms):
                r=p.rooms[view.selected]
                header=f'🔒 **Room {view.selected+1} selected** — {r.monster} Lv{r.monster_level} · {r.trap} Lv{r.trap_level} · Room Lv{r.level}\n'
                notice=header+(notice or 'Keep upgrading this room. Use **Change Room** only when finished.')
            else:notice=notice or 'Select a room once. It stays selected until you press **Change Room**.'
        if mode=='activities':notice=notice or '⚔️ **Fortress Raid:** Earn gold and XP (20-minute cooldown). **PvP Raid:** Attack a similar-power player (6-hour cooldown). **Daily Mission:** Claim after two invasions today.\n\nYour next NPC invasion: '+next_raid_text(p)
        await i.edit_original_response(content=notice,embed=embed,view=view)
    async def handle(self,i,action):
        if action=='quickstart':
            embed=discord.Embed(title='🚀 QUICK START — YOUR FIRST 3 MOVES',description='**1️⃣ Strengthen a room**\nTap **Build & Upgrade** → **Upgrade Rooms** → select any room. Upgrade its monster, trap or walls. You stay in that room until you change it.\n\n**🎭 Want a different build?**\nTap **Change Build** on the main menu and choose your style. Your upgrade levels and progress are preserved.\n\n**2️⃣ Earn extra rewards**\nOpen **Go Adventuring** → **Fortress Raid** for a chance to earn gold and XP.\n\n**3️⃣ Prepare for invasion**\nThe next NPC wave attacks automatically at the time on your dashboard. You have at least 30 minutes after joining to prepare.\n\n**🏆 Goal:** Earn the most points over seven days to finish in the top three!',color=0x57F287)
            return await i.edit_original_response(content='👇 **Ready?** Press **Build & Upgrade** to begin.',embed=embed,view=Management(self.owner,'main'))
        if action=='progress':
            p=get(self.owner)
            embed=display(p)
            embed.add_field(name='🎯 Your goal',value='Defend NPC waves, earn gold and XP, upgrade your dungeon and climb `/leaderboard`.',inline=False)
            return await i.edit_original_response(content='🏆 **Your progress so far**',embed=embed,view=Management(self.owner,'main'))
        if action=='alerts':
            enabled=not notification_enabled(self.owner)
            async with lock:
                engine.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',(f'dm_notify:{self.owner}',json.dumps({'enabled':enabled})))
            return await self.render(i,'main',f"🔔 Raid DM reminders **{'enabled' if enabled else 'disabled'}**. {'A reminder is sent 30 minutes before the next invasion when Discord allows DMs.' if enabled else 'You will not receive raid reminder DMs.'}")
        if action=='change_room':
            return await self.render(i,'room',selected=-1)
        if action in ('main','dungeon','activities','help','refresh','room_menu','builds'):
            mode={'room_menu':'room','refresh':self.mode}.get(action,action)
            return await self.render(i,mode,selected=-1 if action=='room_menu' else None)
        if action=='exit':return await i.edit_original_response(content='Dungeon menu closed. Use `/play` to reopen.',embed=None,view=None)
        if action in ('overview','building','combat','activities_help','scoring'):
            page='activities' if action=='activities_help' else action
            return await i.edit_original_response(content=None,embed=help_embed(page),view=Management(self.owner,'help'))
        if action.startswith('style:'):
            style=action.partition(':')[2]
            async with lock:
                try:changed=engine.change_style(self.owner,style)
                except ValueError as ex:return await i.followup.send(str(ex),ephemeral=True)
            return await self.render(i,'builds',f'🎭 **{style} selected!** Your existing upgrade levels and progress are preserved.' if changed else f'You are already using **{style}**.')
        if action=='order':
            p=get(self.owner)
            lines='\n'.join(f'{n}. {r.monster} Lv{r.monster_level} · {r.trap} Lv{r.trap_level} · Room Lv{r.level}' for n,r in enumerate(p.rooms,1))
            return await i.edit_original_response(content='**Room order**\n'+(lines or 'No rooms yet.')+'\n\nUse `/reorder first second` to swap rooms.',embed=display(p),view=Management(self.owner,'dungeon'))
        if not active():return await i.followup.send('Event is not active.',ephemeral=True)
        if action in ('monster','trap','room'):
            if self.selected is None or self.selected<0:return await i.followup.send('Select a room from the dropdown first.',ephemeral=True)
            async with lock:
                try:result=engine.upgrade(self.owner,self.selected,action)
                except ValueError as ex:return await i.followup.send(str(ex),ephemeral=True)
            return await self.render(i,'room',f"Upgraded {action} to level {result['new_level']} for {result['cost']:,} gold.")
        if action=='add':
            async with lock:
                try:price=engine.add_room(self.owner,'Goblin','Spike')
                except ValueError as ex:return await i.followup.send(str(ex),ephemeral=True)
            return await self.render(i,'dungeon',f'Added Goblin + Spike room for {price:,} gold.')
        if action=='fortress':
            async with lock:
                p=get(self.owner);now=int(time.time());key=f'fortress:{self.owner}'
                row=engine.db.execute('SELECT data FROM events WHERE id=?',(key,)).fetchone()
                last=int(json.loads(row[0])['last']) if row else 0
                if now-last<1200:return await i.followup.send(f'Next raid in {1200-(now-last)} seconds.',ephemeral=True)
                power=p.power()/max(1,len(p.rooms));chance=max(.35,min(.85,.55+.12*math.log(max(.2,power/85))))
                won=random.random()<chance
                try:result=engine.fortress(self.owner,now,won)
                except ValueError as ex:return await i.followup.send(str(ex),ephemeral=True)
                engine.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',(key,json.dumps({'last':now})));engine.db.commit()
            return await self.render(i,'activities',f"Fortress raid {'won' if won else 'lost'}: +{result['xp']} XP, +{result['gold']} gold.")
        if action=='mission':
            day=int((time.time()-START)//86400);key=f'mission:{self.owner}:{day}'
            async with lock:
                if engine.db.execute('SELECT 1 FROM events WHERE id=?',(key,)).fetchone():return await i.followup.send('Daily mission already claimed.',ephemeral=True)
                p=get(self.owner)
                if p.wave<day*48+2:return await i.followup.send('Defend at least two invasion waves today before claiming.',ephemeral=True)
                p.xp+=220;p.gold+=500;engine.save(p)
                engine.db.execute('INSERT INTO events VALUES (?,?)',(key,json.dumps({'claimed':True})));engine.db.commit()
            return await self.render(i,'activities','Daily mission complete: +220 XP and +500 gold.')
        if action=='pvp':
            async with lock:
                a=get(self.owner);now=int(time.time())
                if now-a.last_pvp<PVP_SECONDS:return await i.followup.send(f'PvP cooldown: {(PVP_SECONDS-(now-a.last_pvp))//60} minutes remaining.',ephemeral=True)
                ids=[x[0] for x in engine.db.execute('SELECT id FROM players WHERE id!=?',(self.owner,))]
                matches=[]
                for pid in ids:
                    d=get(pid)
                    if .9<=a.power()/max(1,d.power())<=1.1 and not (now-a.last_target_at<86400 and a.last_target==pid):matches.append(d)
                if not matches:return await i.followup.send('No eligible opponents within ±10% power. Try again later.',ephemeral=True)
                target=random.choice(matches)
                counter={'Swarm':'Cleave','Fortress':'Siege','Curse':'Dispel','Dragon':'Pierce','Balanced':'Cleave'}[target.style]
                try:result=engine.pvp(self.owner,target.id,now,attack=counter,scout=True)
                except ValueError as ex:return await i.followup.send(str(ex),ephemeral=True)
            return await self.render(i,'activities',f"Recon: {target.style} dungeon. Attacked with {counter} against <@{target.id}>. {'Victory!' if result['attacker_won'] else 'Defeat.'} +{result['attacker_points']} leaderboard points.")

@client.tree.command(name='play',description='Open your Dungeon Master menu')
async def play(i:discord.Interaction):
    await i.response.defer(ephemeral=True)
    async with lock:
        p=get(i.user.id)
        if not p:
            if not active():return await i.followup.send('Registration opens when the event starts. The event is not currently active.',ephemeral=True)
            p=engine.create(str(i.user.id))
            # New players do not receive catch-up invasions on registration.
            # Align to the global wave number; the first personal battle is >=30 min away.
            elapsed=max(0,int((time.time()-START)//1800))
            p.wave=min(336,elapsed)
            p.last_wave_at=int(START+p.wave*1800) if p.wave else -1800
            engine.save(p)
            engine.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',(f'joined_at:{p.id}',json.dumps({'at':time.time()})))
    await i.followup.send(content='🎮 **Welcome to your dungeon!** Start with **🚀 Quick Start** or tap **🏰 Build & Upgrade**.\n\n🛡️ **Your next invasion:** '+next_raid_text(p),embed=display(p),view=Management(str(i.user.id)),ephemeral=True)

@client.tree.command(name='notifications',description='Turn NPC invasion DM reminders on or off')
@app_commands.describe(enabled='Receive a DM 30 minutes before each NPC invasion')
async def notifications(i:discord.Interaction,enabled:bool):
    async with lock:
        engine.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',(f'dm_notify:{i.user.id}',json.dumps({'enabled':enabled})))
    await i.response.send_message(f"🔔 NPC invasion DM reminders **{'enabled' if enabled else 'disabled'}**. " + ('I will try to DM you 30 minutes before each upcoming raid. Allow server-member DMs in Discord.' if enabled else 'No further raid reminder DMs will be sent.'),ephemeral=True)

@client.tree.command(name='configure',description='Change a monster or trap in one of your dungeon rooms')
@app_commands.describe(room='Room number starting from 1',monster='Monster to deploy',trap='Trap to install')
@app_commands.choices(monster=[app_commands.Choice(name=x,value=x) for x in MONSTERS],trap=[app_commands.Choice(name=x,value=x) for x in TRAPS])
async def configure(i:discord.Interaction,room:int,monster:str=None,trap:str=None):
    if not active():return await i.response.send_message('Event is not active.',ephemeral=True)
    if monster is None and trap is None:return await i.response.send_message('Choose a monster or trap.',ephemeral=True)
    async with lock:
        if not get(i.user.id):return await i.response.send_message('Use /play first.',ephemeral=True)
        try:engine.change_room(str(i.user.id),room-1,monster,trap)
        except ValueError as ex:return await i.response.send_message(str(ex),ephemeral=True)
    await i.response.send_message(f'Updated room {room}. Changing equipment resets its individual upgrade level.',embed=display(get(i.user.id)),ephemeral=True)

@client.tree.command(name='reorder',description='Swap two rooms to change the defensive battle order')
async def reorder(i:discord.Interaction,first:int,second:int):
    if not active():return await i.response.send_message('Event is not active.',ephemeral=True)
    async with lock:
        p=get(i.user.id)
        if not p:return await i.response.send_message('Use /play first.',ephemeral=True)
        if not (1<=first<=len(p.rooms) and 1<=second<=len(p.rooms)):return await i.response.send_message('Invalid room numbers.',ephemeral=True)
        p.rooms[first-1],p.rooms[second-1]=p.rooms[second-1],p.rooms[first-1]
        engine.save(p)
    await i.response.send_message(f'Swapped rooms {first} and {second}.',ephemeral=True)

@client.tree.command(name='rooms',description='Inspect your room order and upgrade levels')
async def room_list(i:discord.Interaction):
    p=get(i.user.id)
    if not p:return await i.response.send_message('Use /play first.',ephemeral=True)
    msg='\n'.join(f'{k}. {r.monster} Lv{r.monster_level} · {r.trap} Lv{r.trap_level} · Room Lv{r.level}' for k,r in enumerate(p.rooms,1))
    await i.response.send_message(embed=discord.Embed(title='🏰 Room order',description=msg),ephemeral=True)

@client.tree.command(name='leaderboard',description='View the top dungeon masters')
async def leaderboard(i:discord.Interaction):
    rows=engine.leaderboard()[:10]
    msg='\n'.join(f'**{k}.** <@{p["player"]}> — {p["points"]:,} pts (Lv {p["level"]})' for k,p in enumerate(rows,1)) or 'No players yet.'
    await i.response.send_message(embed=discord.Embed(title='🏆 Dungeon Master Leaderboard',description=msg))

@client.tree.command(name='winners',description='Show the final top three after the event')
async def winners(i:discord.Interaction):
    if time.time()<START+DURATION:return await i.response.send_message('Final results are available when the event ends.',ephemeral=True)
    rows=engine.leaderboard()[:3]
    msg='\n'.join(f'{medal} <@{r["player"]}> — {r["points"]:,} points' for medal,r in zip(['🥇','🥈','🥉'],rows)) or 'No participants.'
    await i.response.send_message(embed=discord.Embed(title='🏆 Final Dungeon Master Results',description=msg))

@client.tree.command(name='help',description='Interactive Dungeon Master guide')
async def help_cmd(i:discord.Interaction):
    await i.response.send_message(embed=help_embed(),view=Management(str(i.user.id),'help'),ephemeral=True)

@client.tree.command(name='admin_start',description='Admin: restart event clock at the current time')
@app_commands.default_permissions(administrator=True)
async def admin_start(i:discord.Interaction):
    global START
    if not i.user.guild_permissions.administrator:return await i.response.send_message('Admin only.',ephemeral=True)
    if engine.db.execute('SELECT 1 FROM players LIMIT 1').fetchone():return await i.response.send_message('Cannot restart with existing players. Use a fresh database for a new competition.',ephemeral=True)
    START=time.time()
    engine.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',('event_start',json.dumps({'start':START})));engine.db.commit()
    await i.response.send_message('Event clock started. Existing players and progress are unchanged.',ephemeral=True)

@client.tree.command(name='admin_stop',description='Admin: stop the event')
@app_commands.default_permissions(administrator=True)
async def admin_stop(i:discord.Interaction):
    global START
    if not i.user.guild_permissions.administrator:return await i.response.send_message('Admin only.',ephemeral=True)
    START=time.time()-DURATION-1800
    engine.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',('event_start',json.dumps({'start':START})));engine.db.commit()
    await i.response.send_message('Event stopped.',ephemeral=True)

@tasks.loop(seconds=30)
async def raid_reminders():
    # Reminders are for the NEXT scheduled invasion, never for missed/catch-up waves.
    now=time.time()
    if not START<=now<START+DURATION:return
    async with lock:
        candidates=[]
        for (uid,) in engine.db.execute('SELECT id FROM players'):
            p=get(uid)
            due=next_raid_time(p)
            if due is None or not 0<due-now<=1800 or not notification_enabled(uid):continue
            # Only remind if the previous wave has been processed, avoiding false alerts on backlog.
            if p.wave and p.last_wave_at<START+p.wave*1800-60:continue
            key=f'raid_reminder:{uid}:{p.wave+1}'
            if engine.db.execute('SELECT 1 FROM events WHERE id=?',(key,)).fetchone():continue
            preview=engine.next_preview(uid)
            # Claim reminder BEFORE the network request, preventing repeated DMs on errors/restarts.
            engine.db.execute('INSERT INTO events VALUES (?,?)',(key,json.dumps({'at':now})))
            candidates.append((uid,due,preview))
    for uid,due,preview in candidates:
        try:
            user=client.get_user(int(uid)) or await client.fetch_user(int(uid))
            await user.send(embed=discord.Embed(title='⚔️ Dungeon Master — Invasion Incoming!',description=f"Your next NPC invasion starts **<t:{int(due)}:R>**.\n\n**Wave {preview['wave']}** · {preview['enemy_type']} · Threat {preview['threat']}\n{preview['hint']}\n\nOpen `/play` in the server to prepare your dungeon. Your defence fights automatically, even if you are offline.",color=0x7d5fff))
        except (discord.Forbidden,discord.HTTPException,ValueError) as ex:
            logging.info('Could not deliver raid reminder to %s: %s',uid,ex)

@raid_reminders.before_loop
async def before_raid_reminders():await client.wait_until_ready()

@tasks.loop(seconds=30)
async def waves():
    now=time.time()
    if now<START:return
    expected=min(336,max(0,int((min(now,START+DURATION)-START)//1800)))
    async with lock:
        ids=[r[0] for r in engine.db.execute('SELECT id FROM players')]
        for pid in ids:
            p=get(pid)
            # Shield new players for their first 30 minutes; skip waves that
            # occurred while they were joining rather than awarding instant battles.
            joined_row=engine.db.execute('SELECT data FROM events WHERE id=?',(f'joined_at:{pid}',)).fetchone()
            if joined_row and now<float(json.loads(joined_row[0])['at'])+1800:continue
            for _ in range(max(0,expected-p.wave)):
                engine.invasion(pid,int(START+(p.wave+1)*1800))

@waves.before_loop
async def before_waves():await client.wait_until_ready()

@client.event
async def on_ready():
    global START
    row=engine.db.execute('SELECT data FROM events WHERE id=?',('event_start',)).fetchone()
    if row:START=json.loads(row[0])['start']
    if not waves.is_running():waves.start()
    if not raid_reminders.is_running():raid_reminders.start()
    if not getattr(client,'_synced',False):
        if GUILD_ID:
            guild=discord.Object(id=int(GUILD_ID));client.tree.copy_global_to(guild=guild);await client.tree.sync(guild=guild)
        else:await client.tree.sync()
        client._synced=True
    logging.info('Ready as %s',client.user)

client.run(TOKEN)
