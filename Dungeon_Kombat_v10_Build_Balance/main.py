"""The Golden Vault: one-command, button-driven Discord game."""
import asyncio
import datetime as dt
import json
import os
import random
import sqlite3
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

UTC = dt.timezone.utc
DB_PATH = os.getenv('DATABASE_PATH', 'golden_vault.db')
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
EVENT_DAYS = int(os.getenv('EVENT_DAYS', '7'))
MAX_HP = 100
REGEN_SECONDS = 300
REGEN_HP = 10
QUESTIONS = [
 ('Which planet is known as the Red Planet?', 'Mars', ['Venus','Jupiter','Mercury']),
 ('Which element has the chemical symbol Fe?', 'Iron', ['Copper','Silver','Gold']),
 ('How many sides does a hexagon have?', '6', ['5','7','8']),
 ('Which ocean is the largest?', 'Pacific', ['Atlantic','Indian','Arctic']),
 ('What is the capital of Japan?', 'Tokyo', ['Osaka','Kyoto','Nagoya']),
 ('Which animal is the largest living mammal?', 'Blue whale', ['Elephant','Giraffe','Orca']),
 ('What is 12 multiplied by 8?', '96', ['84','88','108']),
 ('Which gas do plants absorb during photosynthesis?', 'Carbon dioxide', ['Oxygen','Nitrogen','Hydrogen']),
 ('Which continent contains Egypt?', 'Africa', ['Asia','Europe','South America']),
 ('What is the square root of 81?', '9', ['7','8','10']),
 ('Which instrument measures temperature?', 'Thermometer', ['Barometer','Hygrometer','Altimeter']),
 ('Who painted the Mona Lisa?', 'Leonardo da Vinci', ['Michelangelo','Raphael','Donatello']),
 ('Which is the smallest prime number?', '2', ['1','3','5']),
 ('How many minutes are in two hours?', '120', ['90','100','150']),
 ('Which organ pumps blood around the human body?', 'Heart', ['Liver','Lung','Kidney']),
 ('Which country is home to the city of Barcelona?', 'Spain', ['Italy','Portugal','France']),
 ('What is the chemical symbol for gold?', 'Au', ['Ag','Go','Gd']),
 ('Which is the longest side of a right triangle called?', 'Hypotenuse', ['Median','Radius','Diameter']),
 ('What is the freezing point of water in Celsius at standard pressure?', '0', ['-10','10','32']),
 ('Which language is primarily spoken in Brazil?', 'Portuguese', ['Spanish','French','Italian']),
 ('How many players are on the field for one football team in association football?', '11', ['9','10','12']),
 ('Which planet has prominent rings?', 'Saturn', ['Mars','Venus','Mercury']),
 ('What is 15 percent of 200?', '30', ['20','25','35']),
 ('Which metal is liquid at room temperature?', 'Mercury', ['Copper','Iron','Aluminium']),
 ('What is the capital of Canada?', 'Ottawa', ['Toronto','Vancouver','Montreal']),
 ('Which shape has eight sides?', 'Octagon', ['Hexagon','Pentagon','Heptagon']),
 ('What is 7 cubed?', '343', ['49','243','729']),
 ('Which scientist proposed the three laws of motion?', 'Isaac Newton', ['Albert Einstein','Marie Curie','Charles Darwin']),
 ('What is the largest planet in our Solar System?', 'Jupiter', ['Saturn','Neptune','Earth']),
 ('How many bones are in the typical adult human skeleton?', '206', ['196','216','226']),
 ('Which country is famous for the ancient city of Petra?', 'Jordan', ['Greece','Egypt','Turkey']),
 ('What is 144 divided by 12?', '12', ['10','11','14']),
 ('Which is a renewable energy source?', 'Wind', ['Coal','Natural gas','Petrol']),
 ('Which continent is the Sahara Desert in?', 'Africa', ['Asia','Australia','Europe']),
 ('Which is the first month of the year?', 'January', ['March','December','February']),
 ('Which blood cells primarily carry oxygen?', 'Red blood cells', ['Platelets','White blood cells','Plasma']),
 ('What is the boiling point of water in Celsius at standard pressure?', '100', ['80','90','120']),
 ('Which country uses the yen as currency?', 'Japan', ['China','South Korea','Thailand']),
 ('Which is the closest star to Earth?', 'The Sun', ['Sirius','Proxima Centauri','Polaris']),
 ('What is 9 times 9?', '81', ['72','80','99']),
]

conn = sqlite3.connect(DB_PATH, isolation_level=None, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=5000')
conn.executescript('''
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS players (
 uid INTEGER PRIMARY KEY, name TEXT NOT NULL, hp INTEGER DEFAULT 100, hp_tick INTEGER NOT NULL,
 floor INTEGER DEFAULT 1, floor_steps INTEGER DEFAULT 0, bronze INTEGER DEFAULT 0,
 silver INTEGER DEFAULT 0, gold_keys INTEGER DEFAULT 0, gold INTEGER DEFAULT 0,
 score INTEGER DEFAULT 0, correct INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0,
 shield INTEGER DEFAULT 0, regen_upgrade INTEGER DEFAULT 0, potions INTEGER DEFAULT 1,
 question_history TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS sessions (
 uid INTEGER PRIMARY KEY, mode TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
 deadline INTEGER NOT NULL, started INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS daily (
 uid INTEGER NOT NULL, day INTEGER NOT NULL, task INTEGER NOT NULL, PRIMARY KEY(uid,day,task));
CREATE TABLE IF NOT EXISTS expedition (
 uid INTEGER PRIMARY KEY, room INTEGER, max_rooms INTEGER, unbanked INTEGER, daily_day INTEGER);
CREATE TABLE IF NOT EXISTS expedition_score (
 uid INTEGER, day INTEGER, count INTEGER DEFAULT 0, PRIMARY KEY(uid,day));
''')

def now(): return int(time.time())
def iso_ts(s): return int(dt.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp())
configured = os.getenv('EVENT_START')
if not conn.execute("SELECT 1 FROM meta WHERE k='start'").fetchone():
    start = iso_ts(configured) if configured else now()
    conn.execute("INSERT INTO meta VALUES('start',?)", (str(start),))
START = int(conn.execute("SELECT v FROM meta WHERE k='start'").fetchone()['v'])
END = START + EVENT_DAYS*86400

def event_day(): return max(0, min(EVENT_DAYS-1, (now()-START)//86400))
def active(): return START <= now() < END

def player(uid, name=None):
    p=conn.execute('SELECT * FROM players WHERE uid=?',(uid,)).fetchone()
    if p is None:
        conn.execute('INSERT INTO players(uid,name,hp_tick) VALUES(?,?,?)',(uid,name or str(uid),now()))
    elif name and p['name']!=name:
        conn.execute('UPDATE players SET name=? WHERE uid=?',(name,uid))
    regen(uid)
    return conn.execute('SELECT * FROM players WHERE uid=?',(uid,)).fetchone()

def regen(uid):
    p=conn.execute('SELECT hp,hp_tick,regen_upgrade FROM players WHERE uid=?',(uid,)).fetchone()
    if not p: return
    steps=max(0,(now()-p['hp_tick'])//REGEN_SECONDS)
    if steps:
        hp=min(MAX_HP,p['hp']+steps*(REGEN_HP+p['regen_upgrade']*2))
        conn.execute('UPDATE players SET hp=?,hp_tick=? WHERE uid=?',(hp,p['hp_tick']+steps*REGEN_SECONDS,uid))
    if p['hp']==MAX_HP:
        conn.execute('UPDATE players SET hp_tick=? WHERE uid=?',(now(),uid))

def change(uid,**fields):
    allowed={'hp','floor','floor_steps','bronze','silver','gold_keys','gold','score','correct','attempts','shield','regen_upgrade','potions','question_history'}
    assert set(fields)<=allowed
    if fields: conn.execute('UPDATE players SET '+','.join(f'{k}=?' for k in fields)+' WHERE uid=?',(*fields.values(),uid))

def harm(uid,damage):
    p=player(uid)
    damage=max(0,damage-p['shield']*2)
    change(uid,hp=max(0,p['hp']-damage))
    return damage

def steps_required(floor_num):
    if floor_num<=10:return 2
    if floor_num<=25:return 3
    return 4

def make_challenge(uid,mode,level=1):
    # All randomness is server-side. No answers appear in custom IDs.
    kinds=['quiz','quiz','quiz','pattern','memory','lock','path']
    kind=random.choice(kinds)
    payload={}
    if kind=='quiz':
        p=player(uid)
        hist=json.loads(p['question_history'])
        candidates=[i for i in range(len(QUESTIONS)) if i not in hist[-min(25,len(QUESTIONS)-1):]]
        idx=random.choice(candidates or list(range(len(QUESTIONS))))
        q,answer,wrong=QUESTIONS[idx]
        choices=[answer]+wrong
        random.shuffle(choices)
        payload={'question':q,'options':choices,'answer':choices.index(answer),'qid':idx}
        hist.append(idx)
        change(uid,question_history=json.dumps(hist[-40:]))
        duration=10
    elif kind=='pattern':
        start=random.randint(1,12); step=random.randint(2,9)
        answer=start+step*4
        opts={answer}
        while len(opts)<4: opts.add(answer+random.choice([-3,-2,-1,1,2,3,4])*step)
        choices=list(opts);random.shuffle(choices)
        payload={'question':f'Complete the sequence: {start}, {start+step}, {start+2*step}, {start+3*step}, ?', 'options':list(map(str,choices)),'answer':choices.index(answer)}
        duration=30
    elif kind=='memory':
        runes=['☀','☾','◆','✦','♜','♠']
        seq=random.sample(runes,3 if level<30 else 4)
        options=[' '.join(seq)]
        while len(options)<4:
            shuffled=seq[:];random.shuffle(shuffled)
            val=' '.join(shuffled)
            if val not in options:options.append(val)
        random.shuffle(options)
        payload={'sequence':' '.join(seq),'options':options,'answer':options.index(' '.join(seq)),'reveal_until':now()+5}
        duration=35
    elif kind=='lock':
        symbols=['☀','☾','◆','✦']
        goal=[random.randrange(4) for _ in range(3)]
        current=[random.randrange(4) for _ in range(3)]
        if goal==current:current[0]=(current[0]+1)%4
        payload={'goal':goal,'current':current,'symbols':symbols}
        duration=60
    else:
        # A three-step direction path; the sequence is revealed briefly, then hidden.
        dirs=['⬆','⬇','⬅','➡']
        seq=[random.choice(dirs) for _ in range(3 if level<30 else 4)]
        payload={'sequence':seq,'progress':0,'reveal_until':now()+5}
        duration=65
    conn.execute('INSERT OR REPLACE INTO sessions(uid,mode,kind,payload,deadline,started) VALUES(?,?,?,?,?,?)',
                 (uid,mode,kind,json.dumps(payload),now()+duration,now()))
    return kind

def session(uid):return conn.execute('SELECT * FROM sessions WHERE uid=?',(uid,)).fetchone()
def clear_session(uid):conn.execute('DELETE FROM sessions WHERE uid=?',(uid,))
def fmt_time(seconds):
    seconds=max(0,seconds)
    return f'{seconds//3600}h {(seconds%3600)//60}m' if seconds>=3600 else f'{seconds//60}m {seconds%60}s'

def base_embed(uid,title='🏰 THE GOLDEN VAULT',description=''):
    p=player(uid)
    e=discord.Embed(title=title,description=description,color=0xd9a441)
    e.add_field(name='❤️ Health',value=f"{p['hp']}/100",inline=True)
    e.add_field(name='🏰 Floor',value=f"{p['floor']}/50",inline=True)
    e.add_field(name='💎 Vault Score',value=f"{p['score']:,}",inline=True)
    e.add_field(name='🗝️ Keys',value=f"Bronze {p['bronze']} · Silver {p['silver']} · Gold {p['gold_keys']}",inline=False)
    e.add_field(name='🪙 Gold',value=f"{p['gold']:,} · Potions {p['potions']}",inline=False)
    status=(f'Ends <t:{END}:R>' if active() else f'Starts <t:{START}:R>' if now()<START else 'Event finished')
    e.set_footer(text=f'Day {event_day()+1}/{EVENT_DAYS} · {status} · Private player panel')
    return e

RULES='''**🏆 Objective:** Highest Vault Score after seven days wins. Ties: highest floor, then best accuracy.
**🏰 Dungeon:** 50 floors; 2–4 randomly generated challenges per floor. Guardian at every 10th floor. Progress is permanent.
**❤️ Health:** Start with 100 HP; wrong answers and timeouts cost 10 HP. Recover 10 HP every five minutes, including offline. Healing potions restore 25 HP.
**⏱️ Timers:** Trivia 10s; patterns 30s; memory 5s reveal + 30s answer; locks 60s; paths 5s reveal + 60s input.
**🗝️ Treasure:** Earn keys and gold, open chests and build Vault Score. Chests have fixed score values by tier; no random score jackpots.
**🧭 Expeditions:** Repeatable 3–5-room expeditions. You may bank loot by leaving; if you collapse, lose half the unbanked gold. First three completed expeditions each day award bonus score.
**📅 Daily activities:** Five tasks and one guardian per event day; missed event days can be completed later before the event ends. Royal Treasury unlocks at Floor 50.
**⚖️ Fair play:** Do not use AI, outside answer tools, or share solutions. Randomised challenges and short trivia timers discourage cheating but cannot guarantee prevention.
**🔒 Privacy:** Challenges and menus are shown privately to each player.'''
HELP='''**Start:** Use `/play` once, then navigate entirely with buttons.
**Dungeon:** Tap *Dungeon* → *Start Floor Challenge*. Correct answers move the floor progress bar forward. Floor 10/20/30/40/50 ends with a guardian challenge.
**Answering:** Select an answer before the timer expires. Memory and path sequences are visible for five seconds; tap *Hide & Start* after viewing them. Lock puzzles require rotating three runes to match the target.
**Health:** Restores automatically, even while offline. Use a potion in *Workshop* to heal instantly. No loss of completed floors at zero HP.
**Expeditions:** Start a run, clear rooms, then decide whether to continue or bank. Treasure stays unbanked until you leave or finish. Expeditions can be repeated.
**Daily:** Choose an event day and one of five tasks; each completed task awards Vault Score and resources. Catch up on missed days while the event is active.
**Guardian:** One special challenge per day, separate from floor guardians.
**Workshop:** Buy healing potions and damage protection using gold.
**Treasure:** Spend keys on chests. Bronze/Silver/Gold chests award 40/120/300 Vault Score.
**Leaderboard:** Displays the top ten by Vault Score, floor, then accuracy.
**Timing:** Timers are enforced by the server. Closing Discord does not pause a challenge.'''

class UI(discord.ui.View):
    def __init__(self,uid,page='home',day=None):
        super().__init__(timeout=900)
        self.uid=uid;self.page=page;self.day=day
        self.build()
    def add(self,label,action,style=discord.ButtonStyle.secondary,emoji=None,row=None,disabled=False):
        b=discord.ui.Button(label=label,style=style,emoji=emoji,row=row,disabled=disabled)
        async def cb(interaction):
            if interaction.user.id!=self.uid:
                await interaction.response.send_message('This panel belongs to another player. Use `/play`.',ephemeral=True);return
            await route(interaction,self.uid,action,self.day)
        b.callback=cb;self.add_item(b)
    def build(self):
        p=player(self.uid)
        if self.page=='home':
            self.add('Dungeon','dungeon',discord.ButtonStyle.primary,'🏰',0)
            self.add('Expeditions','expeditions',emoji='🧭',row=0)
            self.add('Daily Vault','daily',emoji='📅',row=0)
            self.add('Treasure','treasure',emoji='💎',row=1)
            self.add('Workshop','workshop',emoji='⚒️',row=1)
            self.add('Royal Treasury','royal',emoji='👑',row=1)
            self.add('Leaderboard','leaderboard',emoji='🏆',row=2)
            self.add('Rules','rules',emoji='📜',row=2)
            self.add('Help','help',emoji='❔',row=2)
        elif self.page in ('rules','help','leaderboard','workshop','treasure','dungeon','expeditions','daily','royal','guardian'):
            if self.page=='dungeon':self.add('Start Floor Challenge','start_floor',discord.ButtonStyle.success,disabled=not active() or p['hp']<10 or p['floor']>50)
            if self.page=='expeditions':
                running=conn.execute('SELECT 1 FROM expedition WHERE uid=?',(self.uid,)).fetchone()
                if not running:self.add('Start Expedition','start_expedition',discord.ButtonStyle.success,disabled=not active() or p['hp']<10)
                else:
                    self.add('Next Chamber','exp_next',discord.ButtonStyle.primary,disabled=not active() or p['hp']<10 or bool(session(self.uid)))
                    self.add('Bank & Leave','exp_bank',discord.ButtonStyle.success)
            if self.page=='workshop':
                self.add('Buy Potion · 100g','buy_potion',disabled=p['gold']<100)
                self.add('Use Potion · +25 HP','use_potion',discord.ButtonStyle.success,disabled=p['potions']<1 or p['hp']==100)
                self.add('Shield · 300g','buy_shield',disabled=p['gold']<300 or p['shield']>=3)
                self.add('Regen Upgrade · 500g','buy_regen',disabled=p['gold']<500 or p['regen_upgrade']>=3)
            if self.page=='treasure':
                self.add('Bronze · 2 keys','chest_bronze',disabled=p['bronze']<2 or not active())
                self.add('Silver · 2 keys','chest_silver',disabled=p['silver']<2 or not active())
                self.add('Gold · 1 key','chest_gold',disabled=p['gold_keys']<1 or not active())
            if self.page=='daily':
                for i in range(EVENT_DAYS):self.add(f'Day {i+1}',f'day_{i}',disabled=i>event_day() or not active(),row=i//5)
            if self.page=='guardian':self.add('Face Daily Guardian','start_guardian',discord.ButtonStyle.success,disabled=not active() or p['hp']<10)
            if self.page=='royal':self.add('Royal Trial','start_royal',discord.ButtonStyle.success,disabled=not active() or p['floor']<=50 or p['hp']<10)
            self.add('Main Menu','home',discord.ButtonStyle.primary,'🏠',row=4)
        elif self.page=='day':
            for i in range(5):
                done=bool(conn.execute('SELECT 1 FROM daily WHERE uid=? AND day=? AND task=?',(self.uid,self.day,i)).fetchone())
                self.add(f'Trial {i+1}'+(' ✓' if done else ''),f'task_{i}',disabled=done or not active() or p['hp']<10,row=i//5)
            self.add('Daily Guardian','guardian',row=1)
            self.add('Daily Menu','daily',row=2)
            self.add('Main Menu','home',discord.ButtonStyle.primary,row=4)
        elif self.page=='challenge':
            s=session(self.uid)
            if s:
                payload=json.loads(s['payload']);kind=s['kind']
                if kind in ('quiz','pattern','memory'):
                    for i,opt in enumerate(payload['options']):
                        self.add(str(opt)[:70],f'answer_{i}',discord.ButtonStyle.primary,row=i//2)
                elif kind=='lock':
                    for i in range(3):self.add(f'Rotate Dial {i+1}',f'rotate_{i}',row=0)
                    self.add('Unlock','unlock',discord.ButtonStyle.success,row=1)
                elif kind=='path':
                    for i,sym in enumerate(['⬆','⬇','⬅','➡']):self.add(sym,f'path_{i}',discord.ButtonStyle.primary,row=0)
                if kind in ('memory','path') and now()<payload.get('reveal_until',0):
                    self.add('Hide & Start','hide',discord.ButtonStyle.success,row=2)
                self.add('Forfeit Challenge','forfeit',discord.ButtonStyle.danger,row=4)

def challenge_embed(uid):
    s=session(uid)
    if not s:return base_embed(uid,description='No active challenge.')
    data=json.loads(s['payload']);kind=s['kind'];remain=max(0,s['deadline']-now())
    e=base_embed(uid,f'⚔️ {kind.title()} Chamber',f'⏱️ **{remain} seconds remaining** · <t:{s["deadline"]}:R>')
    if kind in ('quiz','pattern'):e.add_field(name='Question',value=data['question'],inline=False)
    if kind=='memory':
        visible=now()<data['reveal_until'] and not data.get('hidden')
        e.add_field(name='Memorise these runes' if visible else 'Which sequence did you see?',value=data['sequence'] if visible else 'Choose the original rune sequence.',inline=False)
    if kind=='lock':
        syms=data['symbols']
        e.add_field(name='Target',value=' '.join(syms[i] for i in data['goal']),inline=False)
        e.add_field(name='Your dials',value=' '.join(syms[i] for i in data['current']),inline=False)
    if kind=='path':
        visible=now()<data['reveal_until'] and not data.get('hidden')
        e.add_field(name='Safe path' if visible else 'Navigate the path',value=' '.join(data['sequence']) if visible else f"Correct steps: {data['progress']}/{len(data['sequence'])}",inline=False)
    return e

async def show(interaction,uid,page='home',note='',day=None):
    p=player(uid)
    if page=='challenge' and not session(uid):page='home'
    if page=='challenge':e=challenge_embed(uid)
    elif page=='rules':e=base_embed(uid,'📜 Rules',RULES)
    elif page=='help':e=base_embed(uid,'❔ How to Play',HELP)
    elif page=='dungeon':
        required=steps_required(p['floor']) if p['floor']<=50 else 0
        e=base_embed(uid,'🏰 Dungeon',f"Floor **{p['floor']}/50** · Challenges **{p['floor_steps']}/{required}**\nGuardians await every 10 floors. Floor challenges are randomly generated.")
    elif page=='expeditions':
        ex=conn.execute('SELECT * FROM expedition WHERE uid=?',(uid,)).fetchone()
        desc=f"Current expedition: room **{ex['room']}/{ex['max_rooms']}** · Unbanked gold **{ex['unbanked']}**" if ex else 'Enter a randomly generated 3–5-room vault. Bank treasure or risk it for greater rewards.'
        e=base_embed(uid,'🧭 Vault Expeditions',desc)
    elif page=='treasure':e=base_embed(uid,'💎 Treasure Chests','Spend keys on guaranteed Vault Score. Bronze: 2 keys → 40 score; Silver: 2 keys → 120 score; Gold: 1 key → 300 score.')
    elif page=='workshop':e=base_embed(uid,'⚒️ Workshop',f"Shield level: **{p['shield']}/3** (reduces damage by 2 per level). Regeneration level: **{p['regen_upgrade']}/3** (+2 HP per five minutes per level).")
    elif page=='daily':e=base_embed(uid,'📅 Daily Vault','Choose any unlocked event day. Missed days remain available until the event closes. Each day offers five trials and a daily guardian.')
    elif page=='day':
        completed=conn.execute('SELECT COUNT(*) n FROM daily WHERE uid=? AND day=? AND task BETWEEN 0 AND 4',(uid,day)).fetchone()['n']
        e=base_embed(uid,f'📅 Day {day+1} Vault Trials',f'Completed: **{completed}/5**. Each trial has a randomised challenge and awards 70 Vault Score on success.')
    elif page=='guardian':e=base_embed(uid,'🐉 Daily Guardian','One guardian challenge per event day, worth 150 Vault Score. Select the day in Daily Vault first to target a previous day.')
    elif page=='royal':e=base_embed(uid,'👑 Royal Treasury','Unlock at Floor 50. One special trial per event day (including catch-up days), worth 200 Vault Score.')
    elif page=='leaderboard':
        leaders=conn.execute('SELECT * FROM players ORDER BY score DESC,floor DESC,(correct*1.0/MAX(attempts,1)) DESC LIMIT 10').fetchall()
        lines=[f"**{i}.** {discord.utils.escape_markdown(r['name'])[:25]} — 💎 **{r['score']:,}** · Floor {min(50,r['floor'])} · {round(100*r['correct']/max(1,r['attempts']))}%" for i,r in enumerate(leaders,1)]
        e=base_embed(uid,'🏆 Leaderboard','\n'.join(lines) if lines else 'No players yet.')
    else:e=base_embed(uid,description='Explore the dungeon, collect keys, open treasure and compete for the highest Vault Score!')
    if note:e.add_field(name='Update',value=note[:1024],inline=False)
    view=UI(uid,page,day)
    if interaction.response.is_done():await interaction.followup.send(embed=e,view=view,ephemeral=True)
    else:await interaction.response.edit_message(embed=e,view=view)

async def complete(uid,success,mode,kind,reason=''):
    p=player(uid)
    clear_session(uid)
    if not success:
        if reason in ('Time expired.','Challenge forfeited.'):
            change(uid,attempts=p['attempts']+1)
        lost=harm(uid,10)
        if mode=='exp' and player(uid)['hp']==0:
            ex=conn.execute('SELECT * FROM expedition WHERE uid=?',(uid,)).fetchone()
            if ex:
                conn.execute('DELETE FROM expedition WHERE uid=?',(uid,))
                change(uid,gold=player(uid)['gold']+ex['unbanked']//2)
                reason += f' Expedition collapsed; recovered {ex["unbanked"]//2} of {ex["unbanked"]} unbanked gold.'
        return 'dungeon' if mode=='floor' else 'expeditions' if mode=='exp' else 'day' if mode.startswith('task:') else 'home', f'❌ {reason or "Challenge failed."} Lost {lost} HP.'
    change(uid,correct=p['correct']+1,gold=p['gold']+20)
    if mode=='floor':
        progress=p['floor_steps']+1
        if progress>=steps_required(p['floor']):
            f=p['floor']
            if f%10==0:
                # The final step on every 10th floor is the guardian challenge.
                change(uid,floor=f+1,floor_steps=0,bronze=p['bronze']+2,silver=p['silver']+1,score=p['score']+100)
                return 'dungeon',f'🏆 Floor {f} Guardian defeated! +2 bronze, +1 silver, +100 score, +20 gold.'
            change(uid,floor=f+1,floor_steps=0,bronze=p['bronze']+2,score=p['score']+20)
            return 'dungeon',f'🏰 Floor {f} cleared! +2 bronze keys, +20 score, +20 gold.'
        change(uid,floor_steps=progress,bronze=p['bronze']+1)
        return 'dungeon',f'✅ Challenge passed! +1 bronze key, +20 gold. Progress {progress}/{steps_required(p["floor"])}.'
    if mode=='exp':
        ex=conn.execute('SELECT * FROM expedition WHERE uid=?',(uid,)).fetchone()
        if not ex:return 'expeditions','Expedition no longer active.'
        loot=ex['unbanked']+random.randint(50,90)
        if ex['room']>=ex['max_rooms']:
            conn.execute('DELETE FROM expedition WHERE uid=?',(uid,))
            return bank_exp(uid,loot,ex['daily_day'],'🏁 Expedition completed!')
        conn.execute('UPDATE expedition SET room=room+1,unbanked=? WHERE uid=?',(loot,uid))
        return 'expeditions',f'💰 Chamber cleared! {loot} unbanked gold. Continue or leave safely.'
    if mode.startswith('task:'):
        _,day,task=mode.split(':');day=int(day);task=int(task)
        conn.execute('INSERT OR IGNORE INTO daily VALUES(?,?,?)',(uid,day,task))
        change(uid,score=p['score']+70,bronze=p['bronze']+1)
        return 'day','✅ Daily trial completed! +70 Vault Score, +1 bronze key, +20 gold.'
    if mode.startswith('guardian:'):
        day=int(mode.split(':')[1]);conn.execute('INSERT OR IGNORE INTO daily VALUES(?,?,?)',(uid,day,5))
        change(uid,score=p['score']+150,silver=p['silver']+1)
        return 'day','🐉 Daily Guardian defeated! +150 Vault Score and +1 silver key.'
    if mode.startswith('royal:'):
        day=int(mode.split(':')[1]);conn.execute('INSERT OR IGNORE INTO daily VALUES(?,?,?)',(uid,day,6))
        change(uid,score=p['score']+200,gold_keys=p['gold_keys']+1)
        return 'royal','👑 Royal Trial completed! +200 Vault Score and +1 gold key.'
    return 'home','Challenge completed.'

def bank_exp(uid,loot,day,prefix='🏦 Treasure banked!'):
    p=player(uid)
    row=conn.execute('SELECT count FROM expedition_score WHERE uid=? AND day=?',(uid,day)).fetchone()
    count=row['count'] if row else 0
    bonus=60 if count<3 else 0
    conn.execute('INSERT INTO expedition_score(uid,day,count) VALUES(?,?,1) ON CONFLICT(uid,day) DO UPDATE SET count=count+1',(uid,day))
    change(uid,gold=p['gold']+loot,bronze=p['bronze']+(1 if count<3 else 0),score=p['score']+bonus)
    return 'expeditions',f'{prefix} +{loot} gold, +{1 if count<3 else 0} bronze key, +{bonus} Vault Score. ({min(count+1,3)}/3 daily score expeditions)'

async def route(interaction,uid,action,day=None):
    player(uid,interaction.user.display_name)
    s=session(uid)
    if s and now()>s['deadline']:
        mode=s['mode'];kind=s['kind']
        page,msg=await complete(uid,False,mode,kind,'Time expired.')
        if action.startswith(('answer_','rotate_','path_')) or action in ('unlock','hide','forfeit'):
            await show(interaction,uid,page,msg,day=day);return
    if action in ('home','dungeon','expeditions','daily','treasure','workshop','royal','leaderboard','rules','help'):
        await show(interaction,uid,action,day=day);return
    if action.startswith('day_'):
        await show(interaction,uid,'day',day=int(action.split('_')[1]));return
    if action=='guardian':
        await show(interaction,uid,'guardian',day=day);return
    if not active():
        if s:clear_session(uid)
        await show(interaction,uid,'home','The event is not currently active.');return
    p=player(uid)
    if action=='start_floor':
        if s:await show(interaction,uid,'challenge','Finish or forfeit the active challenge.');return
        if p['floor']>50:await show(interaction,uid,'royal','All 50 floors are complete!');return
        if p['hp']<10:await show(interaction,uid,'dungeon','You need at least 10 HP. Rest or use a potion.');return
        make_challenge(uid,'floor',p['floor']);await show(interaction,uid,'challenge');return
    if action=='start_expedition':
        if s:await show(interaction,uid,'challenge');return
        if p['hp']<10:await show(interaction,uid,'expeditions','You need at least 10 HP.');return
        if conn.execute('SELECT 1 FROM expedition WHERE uid=?',(uid,)).fetchone():await show(interaction,uid,'expeditions');return
        conn.execute('INSERT INTO expedition VALUES(?,?,?,?,?)',(uid,1,random.randint(3,5),0,event_day()))
        await show(interaction,uid,'expeditions','New expedition started! Enter the first chamber.');return
    if action=='exp_next':
        if s:await show(interaction,uid,'challenge');return
        if not conn.execute('SELECT 1 FROM expedition WHERE uid=?',(uid,)).fetchone():await show(interaction,uid,'expeditions');return
        if p['hp']<10:await show(interaction,uid,'expeditions','Recover to at least 10 HP first.');return
        make_challenge(uid,'exp',p['floor']);await show(interaction,uid,'challenge');return
    if action=='exp_bank':
        ex=conn.execute('SELECT * FROM expedition WHERE uid=?',(uid,)).fetchone()
        if not ex:await show(interaction,uid,'expeditions');return
        if s and s['mode']=='exp':await show(interaction,uid,'challenge','Finish or forfeit the current challenge first.');return
        conn.execute('DELETE FROM expedition WHERE uid=?',(uid,))
        page,msg=bank_exp(uid,ex['unbanked'],ex['daily_day']);await show(interaction,uid,page,msg);return
    if action.startswith('chest_'):
        tier=action.split('_')[1]
        field,cost,points={'bronze':('bronze',2,40),'silver':('silver',2,120),'gold':('gold_keys',1,300)}[tier]
        if p[field]<cost:await show(interaction,uid,'treasure','Not enough keys.');return
        change(uid,**{field:p[field]-cost,'score':p['score']+points})
        await show(interaction,uid,'treasure',f'🎁 Opened {tier} chest! +{points} Vault Score.');return
    if action=='buy_potion':
        if p['gold']>=100:change(uid,gold=p['gold']-100,potions=p['potions']+1)
        await show(interaction,uid,'workshop','Purchased a healing potion.' if p['gold']>=100 else 'Not enough gold.');return
    if action=='use_potion':
        if p['potions'] and p['hp']<100:change(uid,potions=p['potions']-1,hp=min(100,p['hp']+25))
        await show(interaction,uid,'workshop','Potion used.' if p['potions'] and p['hp']<100 else 'Cannot use a potion.');return
    if action in ('buy_shield','buy_regen'):
        field='shield' if action=='buy_shield' else 'regen_upgrade';cost=300 if field=='shield' else 500
        if p['gold']>=cost and p[field]<3:change(uid,gold=p['gold']-cost,**{field:p[field]+1})
        await show(interaction,uid,'workshop','Upgrade purchased.' if p['gold']>=cost and p[field]<3 else 'Cannot purchase upgrade.');return
    if action.startswith('task_'):
        task=int(action.split('_')[1]);day=event_day() if day is None else day
        if conn.execute('SELECT 1 FROM daily WHERE uid=? AND day=? AND task=?',(uid,day,task)).fetchone():await show(interaction,uid,'day','Already completed.',day);return
        if s:await show(interaction,uid,'challenge');return
        if p['hp']<10:await show(interaction,uid,'day','Recover health first.',day);return
        make_challenge(uid,f'task:{day}:{task}',p['floor']);await show(interaction,uid,'challenge',day=day);return
    if action=='start_guardian':
        day=event_day() if day is None else day
        if conn.execute('SELECT 1 FROM daily WHERE uid=? AND day=? AND task=5',(uid,day)).fetchone():await show(interaction,uid,'day','Guardian already defeated for this day.',day);return
        if s:await show(interaction,uid,'challenge');return
        if p['hp']<10:await show(interaction,uid,'guardian','Recover health first.',day);return
        make_challenge(uid,f'guardian:{day}',p['floor']);await show(interaction,uid,'challenge',day=day);return
    if action=='start_royal':
        if p['floor']<=50:await show(interaction,uid,'royal','Reach Floor 50 and complete it to unlock.');return
        days=[d for d in range(event_day()+1) if not conn.execute('SELECT 1 FROM daily WHERE uid=? AND day=? AND task=6',(uid,d)).fetchone()]
        if not days:await show(interaction,uid,'royal','All available Royal Trials are completed.');return
        if s:await show(interaction,uid,'challenge');return
        if p['hp']<10:await show(interaction,uid,'royal','Recover health first.');return
        make_challenge(uid,f'royal:{days[0]}',p['floor']);await show(interaction,uid,'challenge');return
    if action=='forfeit':
        if not s:await show(interaction,uid,'home');return
        page,msg=await complete(uid,False,s['mode'],s['kind'],'Challenge forfeited.')
        await show(interaction,uid,page,msg,day=day);return
    if not s:await show(interaction,uid,'home','No active challenge.');return
    payload=json.loads(s['payload']);kind=s['kind'];mode=s['mode']
    if action=='hide' and kind in ('memory','path'):
        payload['hidden']=True
        conn.execute('UPDATE sessions SET payload=? WHERE uid=?',(json.dumps(payload),uid))
        await show(interaction,uid,'challenge');return
    if kind in ('quiz','pattern','memory') and action.startswith('answer_'):
        if kind=='memory' and now()<payload['reveal_until'] and not payload.get('hidden'):
            await show(interaction,uid,'challenge','Wait for the reveal to finish or press Hide & Start.');return
        index=int(action.split('_')[1]);correct=index==payload['answer']
        change(uid,attempts=p['attempts']+1)
        page,msg=await complete(uid,correct,mode,kind,'Wrong answer.')
        await show(interaction,uid,page,msg,day=int(mode.split(':')[1]) if ':' in mode else day);return
    if kind=='lock' and action.startswith('rotate_'):
        i=int(action.split('_')[1]);payload['current'][i]=(payload['current'][i]+1)%4
        conn.execute('UPDATE sessions SET payload=? WHERE uid=?',(json.dumps(payload),uid))
        await show(interaction,uid,'challenge');return
    if kind=='lock' and action=='unlock':
        change(uid,attempts=p['attempts']+1)
        page,msg=await complete(uid,payload['current']==payload['goal'],mode,kind,'The runes did not match.')
        await show(interaction,uid,page,msg,day=int(mode.split(':')[1]) if ':' in mode else day);return
    if kind=='path' and action.startswith('path_'):
        if now()<payload['reveal_until'] and not payload.get('hidden'):
            await show(interaction,uid,'challenge','Wait for the reveal to finish or press Hide & Start.');return
        chosen=['⬆','⬇','⬅','➡'][int(action.split('_')[1])]
        if chosen!=payload['sequence'][payload['progress']]:
            change(uid,attempts=p['attempts']+1)
            page,msg=await complete(uid,False,mode,kind,'Wrong path step.')
            await show(interaction,uid,page,msg,day=int(mode.split(':')[1]) if ':' in mode else day);return
        payload['progress']+=1
        if payload['progress']==len(payload['sequence']):
            change(uid,attempts=p['attempts']+1)
            page,msg=await complete(uid,True,mode,kind)
            await show(interaction,uid,page,msg,day=int(mode.split(':')[1]) if ':' in mode else day);return
        conn.execute('UPDATE sessions SET payload=? WHERE uid=?',(json.dumps(payload),uid))
        await show(interaction,uid,'challenge');return
    await show(interaction,uid,'challenge')

intents=discord.Intents.default()
bot=commands.Bot(command_prefix='!',intents=intents)
@bot.tree.command(name='play',description='Open The Golden Vault game menu')
async def play(interaction:discord.Interaction):
    uid=interaction.user.id
    player(uid,interaction.user.display_name)
    # /play creates a fresh private panel; existing panels are also scoped to the player.
    await interaction.response.send_message(embed=base_embed(uid,description='Explore, earn keys, unlock treasure and climb the leaderboard!'),view=UI(uid,'home'),ephemeral=True)

@bot.event
async def on_ready():
    if getattr(bot,'_synced',False):return
    guild=os.getenv('GUILD_ID')
    try:
        if guild:
            g=discord.Object(id=int(guild));bot.tree.copy_global_to(guild=g)
            await bot.tree.sync(guild=g)
        else:await bot.tree.sync()
        bot._synced=True
        print(f'Golden Vault online as {bot.user}; start={START}, end={END}',flush=True)
    except Exception as exc:print('Command sync error:',repr(exc),flush=True)

if __name__=='__main__':
    token=os.getenv('DISCORD_TOKEN')
    if not token:raise SystemExit('Set DISCORD_TOKEN in Railway variables or environment.')
    bot.run(token)
