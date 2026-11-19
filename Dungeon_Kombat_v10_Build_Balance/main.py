"""Dungeon Master Discord bot. Requires discord.py 2.4+.
Run: DISCORD_TOKEN=... python bot.py
Commands: /play, /leaderboard, /help, /admin_start, /admin_stop.
"""
import os, asyncio, datetime, time, logging, sqlite3, json, random, math
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dungeon_master_engine import Engine, Room, MONSTERS, TRAPS, PVP_SECONDS, MAX_ROOMS, ROOM_UNLOCK_LEVELS

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

def display(p):
    e=discord.Embed(title='🏰 Dungeon Master',description=f'Level **{p.level()}/75** · Gold **{p.gold:,}** · XP **{p.xp:,}** · Shards **{p.shards:,}**',color=0x7d5fff)
    e.add_field(name='Dungeon',value=f'{len(p.rooms)}/{min(MAX_ROOMS,p.capacity())} rooms · {p.style} · Power {p.power():.0f}')
    e.add_field(name='Invasions',value=f'{p.wave}/336 · {p.points:,} points')
    if p.wave<336:
        q=engine.next_preview(p.id)
        e.add_field(name='⚔️ Next invasion',value=f"Wave {q['wave']}: {q['enemy_type']} · Threat {q['threat']}\n{q['hint']}",inline=False)
    return e

class RoomPicker(discord.ui.Select):
    def __init__(self,action,options):
        super().__init__(placeholder=f'Choose {action}',options=[discord.SelectOption(label=x,value=x) for x in options[:25]])
        self.action=action
    async def callback(self,interaction):
        view=self.view
        view.selected=self.values[0]
        await interaction.response.edit_message(content=f'Selected {self.action}: **{view.selected}**. Choose an action below.',view=view)

class Management(discord.ui.View):
    def __init__(self,owner,mode='main',selected=None):
        super().__init__(timeout=600);self.owner=owner;self.mode=mode;self.selected=selected
        if mode=='room':
            p=get(owner)
            self.add_item(RoomPicker('room',[f'{i+1}: {r.monster} / {r.trap} (M{r.monster_level} T{r.trap_level} R{r.level})' for i,r in enumerate(p.rooms)]))
    async def interaction_check(self,i):
        if str(i.user.id)!=self.owner:
            await i.response.send_message('This is not your dungeon.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Dungeon / Upgrades',style=discord.ButtonStyle.primary,row=0)
    async def rooms(self,i,b):
        p=get(self.owner)
        await i.response.edit_message(embed=display(p),content='Select a room, then upgrade its monster, trap or structure.',view=Management(self.owner,'room'))
    @discord.ui.button(label='Upgrade Monster',style=discord.ButtonStyle.secondary,row=1)
    async def monster(self,i,b):await self.upgrade(i,'monster')
    @discord.ui.button(label='Upgrade Trap',style=discord.ButtonStyle.secondary,row=1)
    async def trap(self,i,b):await self.upgrade(i,'trap')
    @discord.ui.button(label='Upgrade Room',style=discord.ButtonStyle.secondary,row=1)
    async def room(self,i,b):await self.upgrade(i,'room')
    async def upgrade(self,i,kind):
        if not active():return await i.response.send_message('The event is not active.',ephemeral=True)
        if not self.selected:return await i.response.send_message('Select a room first using Dungeon / Upgrades.',ephemeral=True)
        index=int(self.selected.split(':')[0])-1
        async with lock:
            try:result=engine.upgrade(self.owner,index,kind)
            except ValueError as ex:return await i.response.send_message(str(ex),ephemeral=True)
            p=get(self.owner)
        await i.response.edit_message(content=f"Upgraded {kind} to level {result['new_level']} for {result['cost']:,} gold.",embed=display(p),view=Management(self.owner,'room'))
    @discord.ui.button(label='Add Room',style=discord.ButtonStyle.success,row=0)
    async def add(self,i,b):
        if not active():return await i.response.send_message('Event is not active.',ephemeral=True)
        async with lock:
            try:price=engine.add_room(self.owner,'Goblin','Spike')
            except ValueError as ex:return await i.response.send_message(str(ex),ephemeral=True)
        await i.response.edit_message(content=f'Added Goblin + Spike room for {price:,} gold.',embed=display(get(self.owner)),view=Management(self.owner))
    @discord.ui.button(label='Fortress Raid',style=discord.ButtonStyle.success,row=0)
    async def fortress(self,i,b):
        if not active():return await i.response.send_message('Event is not active.',ephemeral=True)
        async with lock:
            p=get(self.owner);now=int(time.time());key=f'fortress:{self.owner}'
            row=engine.db.execute('SELECT data FROM events WHERE id=?',(key,)).fetchone()
            last=int(json.loads(row[0])['last']) if row else 0
            if now-last<1200:return await i.response.send_message(f'Next raid in {1200-(now-last)} seconds.',ephemeral=True)
            # Outcome depends on dungeon strength and deterministic enemy difficulty; no unlimited guaranteed success.
            power=p.power()/max(1,len(p.rooms));chance=max(.35,min(.85,.55+.12*math.log(max(.2,power/85))))
            won=random.random()<chance
            result=engine.fortress(self.owner,now,won)
            engine.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',(key,json.dumps({'last':now})));engine.db.commit()
        await i.response.edit_message(content=f"Fortress raid {'won' if won else 'lost'}: +{result['xp']} XP, +{result['gold']} gold.",embed=display(get(self.owner)),view=Management(self.owner))
    @discord.ui.button(label='Daily Mission',style=discord.ButtonStyle.secondary,row=2)
    async def mission(self,i,b):
        if not active():return await i.response.send_message('Event is not active.',ephemeral=True)
        day=int((time.time()-START)//86400);key=f'mission:{self.owner}:{day}'
        async with lock:
            if engine.db.execute('SELECT 1 FROM events WHERE id=?',(key,)).fetchone():return await i.response.send_message('Daily mission already claimed.',ephemeral=True)
            p=get(self.owner)
            if p.wave<day*48+2:return await i.response.send_message('Defend at least two invasion waves today before claiming.',ephemeral=True)
            p.xp+=220;p.gold+=500;engine.save(p)
            engine.db.execute('INSERT INTO events VALUES (?,?)',(key,json.dumps({'claimed':True})));engine.db.commit()
        await i.response.edit_message(content='Daily mission complete: +220 XP and +500 gold.',embed=display(get(self.owner)),view=Management(self.owner))
    @discord.ui.button(label='PvP Raid',style=discord.ButtonStyle.danger,row=2)
    async def pvp(self,i,b):
        if not active():return await i.response.send_message('Event is not active.',ephemeral=True)
        async with lock:
            a=get(self.owner);now=int(time.time())
            if now-a.last_pvp<PVP_SECONDS:return await i.response.send_message(f'PvP cooldown: {(PVP_SECONDS-(now-a.last_pvp))//60} minutes remaining.',ephemeral=True)
            ids=[x[0] for x in engine.db.execute('SELECT id FROM players WHERE id!=?',(self.owner,))]
            matches=[]
            for pid in ids:
                d=get(pid)
                if .9<=a.power()/max(1,d.power())<=1.1 and not (now-a.last_target_at<86400 and a.last_target==pid):matches.append(d)
            if not matches:return await i.response.send_message('No eligible opponents within ±10% power. Try again later.',ephemeral=True)
            target=random.choice(matches)
            # Recon shows speciality, not exact trap positions.
            counter={'Swarm':'Cleave','Fortress':'Siege','Curse':'Dispel','Dragon':'Pierce','Balanced':'Cleave'}[target.style]
            try:result=engine.pvp(self.owner,target.id,now,attack=counter,scout=True)
            except ValueError as ex:return await i.response.send_message(str(ex),ephemeral=True)
        await i.response.edit_message(content=f"Recon: {target.style} dungeon. Attacked with {counter} against <@{target.id}>. {'Victory!' if result['attacker_won'] else 'Defeat.'} +{result['attacker_points']} leaderboard points.",embed=display(get(self.owner)),view=Management(self.owner))
    @discord.ui.button(label='Refresh',style=discord.ButtonStyle.secondary,row=2)
    async def refresh(self,i,b):await i.response.edit_message(content=None,embed=display(get(self.owner)),view=Management(self.owner))
    @discord.ui.button(label='Exit',style=discord.ButtonStyle.secondary,row=3)
    async def exit(self,i,b):await i.response.edit_message(content='Dungeon menu closed.',embed=None,view=None)

@client.tree.command(name='play',description='Open your Dungeon Master menu')
async def play(i:discord.Interaction):
    async with lock:
        p=get(i.user.id)
        if not p:
            if not active():return await i.response.send_message('Registration opens when the event starts. The event is not currently active.',ephemeral=True)
            p=engine.create(str(i.user.id))
    await i.response.send_message(embed=display(p),view=Management(str(i.user.id)),ephemeral=True)

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

@client.tree.command(name='help',description='Dungeon Master rules and controls')
async def help_cmd(i:discord.Interaction):
    await i.response.send_message('**Dungeon Master:** /play to manage your dungeon. NPC waves run every 30 minutes while the event is live, including offline. Preview the next enemy type, upgrade monsters/traps/rooms, raid NPC fortresses (20-minute cooldown), claim one mission each day and raid another player once every 6 hours. PvP targets are matched within ±10% power. Most leaderboard points come from successful NPC defences. Event lasts seven days.',ephemeral=True)

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
async def waves():
    now=time.time()
    if now<START:return
    expected=min(336,max(0,int((min(now,START+DURATION)-START)//1800)+1))
    async with lock:
        ids=[r[0] for r in engine.db.execute('SELECT id FROM players')]
        for pid in ids:
            p=get(pid)
            for _ in range(max(0,expected-p.wave)):
                engine.invasion(pid,int(START+p.wave*1800))

@waves.before_loop
async def before_waves():await client.wait_until_ready()

@client.event
async def on_ready():
    global START
    row=engine.db.execute('SELECT data FROM events WHERE id=?',('event_start',)).fetchone()
    if row:START=json.loads(row[0])['start']
    if not waves.is_running():waves.start()
    if not getattr(client,'_synced',False):
        if GUILD_ID:
            guild=discord.Object(id=int(GUILD_ID));client.tree.copy_global_to(guild=guild);await client.tree.sync(guild=guild)
        else:await client.tree.sync()
        client._synced=True
    logging.info('Ready as %s',client.user)

client.run(TOKEN)
