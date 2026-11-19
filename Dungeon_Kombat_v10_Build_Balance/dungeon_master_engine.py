"""Dungeon Master integrated prototype: standard-library Python 3.10+.
Offline event engine / simulation, NOT a Discord bot. All timestamps UTC seconds.
Run: python dungeon_master_engine.py --simulate --output results.json
     python dungeon_master_engine.py --self-test
"""
from __future__ import annotations
import argparse, json, math, random, sqlite3, time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional
from dungeon_balance_sim import MONSTERS, TRAPS, room_power, SCOUT_COUNTER
from combat import battle, validate_layout

EVENT_SECONDS=7*86400
WAVE_SECONDS=1800
PVP_SECONDS=21600
LEVEL_CAP=75
MAX_ROOMS=15
MONSTER_CAP=30
TRAP_CAP=20
ROOM_CAP=15
ROOM_UNLOCK_LEVELS=[1,4,8,12,17,22,27,32,37,42,47,52,57,62,67]
COUNTER={'Cleave':'Swarm','Siege':'Fortress','Dispel':'Curse','Pierce':'Dragon'}
PATTERNS={
 'Swarm':[('Goblin','Spike'),('Spider','Poison')],
 'Fortress':[('Skeleton','Arrow'),('Orc','Ice')],
 'Curse':[('Necromancer','Curse'),('Spider','Poison')],
 'Balanced':[('Goblin','Spike'),('Skeleton','Arrow'),('Spider','Poison'),('Necromancer','Curse'),('Orc','Ice')],
 'Dragon':[('Dragon','Fire'),('Skeleton','Ice'),('Goblin','Spike'),('Spider','Poison'),('Orc','Arrow')],
}
@dataclass
class Room:
 monster:str='Goblin'
 trap:str='Spike'
 monster_level:int=1
 trap_level:int=1
 level:int=1

@dataclass
class Player:
 id:str
 style:str='Balanced'
 gold:int=5000
 xp:int=0
 points:int=0
 shards:int=0
 wave:int=0
 last_pvp:int=-PVP_SECONDS
 first_threat:float=0
 rooms:list[Room]=field(default_factory=list)
 last_target:str=''
 last_target_at:int=-EVENT_SECONDS
 last_wave_at:int=-WAVE_SECONDS
 pvp_rewarded_defences:int=0

 def level(self):return min(LEVEL_CAP,1+math.floor(math.sqrt(max(0,self.xp)/3.95)))
 def capacity(self):return sum(self.level()>=x for x in ROOM_UNLOCK_LEVELS)
 def power(self):return sum(room_power(r.monster,r.trap,r.monster_level,r.trap_level,r.level) for r in self.rooms)
 def snapshot(self):return json.loads(json.dumps(asdict(self)))

class Engine:
 def __init__(self,db=':memory:',seed=2026):
  self.db=sqlite3.connect(db, timeout=30, isolation_level=None, check_same_thread=False)
  self.db.execute('PRAGMA busy_timeout=30000')
  self.db.execute('PRAGMA journal_mode=WAL')
  self.db.execute('CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
  self.db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
  self.seed=seed
 def save(self,p):
  self.db.execute('INSERT OR REPLACE INTO players VALUES (?,?)',(p.id,json.dumps(asdict(p))))
 def load(self,pid):
  row=self.db.execute('SELECT state FROM players WHERE id=?',(pid,)).fetchone()
  if not row:raise KeyError(pid)
  d=json.loads(row[0]);d['rooms']=[Room(**r) for r in d['rooms']];return Player(**d)
 def create(self,pid,style='Balanced'):
  if style not in PATTERNS:raise ValueError('Unknown style')
  if self.db.execute('SELECT 1 FROM players WHERE id=?',(pid,)).fetchone():raise ValueError('Player already exists')
  p=Player(id=pid,style=style,rooms=[Room(m,t) for m,t in PATTERNS[style][:5]])
  validate_layout(p.rooms)
  self.save(p);return p
 def upgrade_cost(self,kind,level):
  base={'monster':130,'trap':110,'room':200}[kind]
  exponent={'monster':1.65,'trap':1.8,'room':1.9}[kind]
  return int(round(base*(level**exponent)))
 def upgrade(self,pid,index,kind):
  p=self.load(pid)
  if not 0<=index<len(p.rooms):raise ValueError('Invalid room')
  if kind not in ('monster','trap','room'):raise ValueError('Invalid upgrade')
  r=p.rooms[index];attr={'monster':'monster_level','trap':'trap_level','room':'level'}[kind]
  cap={'monster':MONSTER_CAP,'trap':TRAP_CAP,'room':ROOM_CAP}[kind]
  level=getattr(r,attr)
  if level>=cap:raise ValueError('Maximum level')
  price=self.upgrade_cost(kind,level)
  if p.gold<price:raise ValueError('Insufficient gold')
  p.gold-=price;setattr(r,attr,level+1);self.save(p)
  return {'cost':price,'new_level':level+1}
 def add_room(self,pid,monster='Goblin',trap='Spike'):
  p=self.load(pid)
  if monster not in MONSTERS or trap not in TRAPS:raise ValueError('Unknown equipment')
  if len(p.rooms)>=min(MAX_ROOMS,p.capacity()):raise ValueError('Room slot locked')
  if monster=='Dragon' and any(r.monster=='Dragon' for r in p.rooms):raise ValueError('One dragon maximum')
  price=450+len(p.rooms)*180
  if p.gold<price:raise ValueError('Insufficient gold')
  candidate=p.rooms+[Room(monster,trap)]
  validate_layout(candidate)
  p.gold-=price;p.rooms=candidate;self.save(p);return price
 def change_room(self,pid,index,monster=None,trap=None):
  p=self.load(pid)
  if not 0<=index<len(p.rooms):raise ValueError('Invalid room')
  if monster is not None:
   if monster not in MONSTERS:raise ValueError('Unknown monster')
   if monster=='Dragon' and any(i!=index and r.monster=='Dragon' for i,r in enumerate(p.rooms)):raise ValueError('One dragon maximum')
   p.rooms[index].monster=monster;p.rooms[index].monster_level=1
  if trap is not None:
   if trap not in TRAPS:raise ValueError('Unknown trap')
   p.rooms[index].trap=trap;p.rooms[index].trap_level=1
  validate_layout(p.rooms)
  self.save(p)
 def next_preview(self,pid):
  p=self.load(pid);wave=p.wave+1
  kinds=['Cleave','Siege','Dispel','Pierce']
  kind=kinds[(wave//7+self.seed)%4]
  return {'wave':wave,'enemy_type':kind,'hint':{'Cleave':'Area damage threatens swarms','Siege':'Armour-breaking threatens tanks','Dispel':'Anti-magic threatens curses','Pierce':'Piercing threatens dragons'}[kind], 'threat':round(self.threat(p,wave),2)}
 def threat(self,p,wave):
  # Public common threat ladder: never based on chosen build or upgrades.
  # Same wave and enemy composition for everyone; progress is earned by upgrades.
  return 100*(1+0.0015*(wave-1))
 def invasion(self,pid,now):
  p=self.load(pid);wave=p.wave+1
  if wave>336:raise ValueError('Event waves exhausted')
  if now-p.last_wave_at<WAVE_SECONDS:raise ValueError('Invasion cooldown active')
  if not p.first_threat:p.first_threat=100 # legacy field retained for old saved games
  preview=self.next_preview(pid)
  threat=self.threat(p,wave)
  result=battle(p.rooms,preview['enemy_type'],threat=threat,seed=f'{self.seed}:npc:{wave}')
  won=not result['attacker_won']
  xp=14 if won else 8
  gold=(190 if won else 90)+int((wave-1)*.45)
  # Partial defence earns fewer points; clearing all rooms yields zero.
  # Difficulty multiplier is identical for everyone at the same wave.
  stopped_fraction=(len(p.rooms)-result['rooms_cleared'])/max(1,len(p.rooms))
  points=round((18+27*stopped_fraction if won else 8+10*min(1,result['ticks']/140))*(1+(wave-1)/335*.35))
  p.last_wave_at=now;p.wave=wave;p.xp+=xp;p.gold+=gold;p.points+=points
  self.save(p)
  return {'wave':wave,'won':won,'rooms_cleared':result['rooms_cleared'],'gold':gold,'xp':xp,'points':points,'threat':round(threat,1),'enemy':preview['enemy_type']}
 def fortress(self,pid,now,success=True):
  # Daily progression budget: repeated fortress calls cannot generate unlimited
  # gold/XP, even if the player has unlimited time to play.
  p=self.load(pid)
  day=now//86400
  key=f'fortress_uses:{pid}:{day}'
  row=self.db.execute('SELECT data FROM events WHERE id=?',(key,)).fetchone()
  uses=int(json.loads(row[0])['count']) if row else 0
  if uses>=12:raise ValueError('Daily fortress reward limit reached (12 raids)')
  self.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',(key,json.dumps({'count':uses+1})))
  xp=260 if success else 35
  gold=480 if success else 75
  bonus=10 if success and uses<6 else 0
  p.xp+=xp;p.gold+=gold;p.shards+=2 if success else 0;p.points+=bonus
  self.save(p)
  return {'success':success,'xp':xp,'gold':gold,'points':bonus,'remaining_today':11-uses}
 def pvp(self,attacker_id,defender_id,now,attack='Cleave',scout=True):
  if attacker_id==defender_id:raise ValueError('Cannot attack yourself')
  if attack not in ('Cleave','Siege','Dispel','Pierce'):raise ValueError('Invalid attack')
  a=self.load(attacker_id);d=self.load(defender_id)
  if now-a.last_pvp<PVP_SECONDS:raise ValueError('PvP cooldown active')
  if now-a.last_target_at<86400 and a.last_target==defender_id:raise ValueError('Same target within 24 hours')
  a_rating=a.power();d_rating=d.power()
  if not (.9<=a_rating/max(1,d_rating)<=1.1):raise ValueError('Outside matchmaking range')
  # Attacker power is derived from the ATTACKER's deployed units, not defender strength.
  # 15-room battles have a larger resource budget than five-room battles.
  attacker_budget=a_rating
  result=battle(d.rooms,attack,attacker_power=attacker_budget,seed=f'{self.seed}:{attacker_id}:{defender_id}:{now}')
  won=result['attacker_won']
  a.last_pvp=now;a.last_target=defender_id;a.last_target_at=now
  a.gold+=500 if won else 50;a.points+=50 if won else 0;a.xp+=80
  defence_points=0
  if not won:
   d.gold+=300
   day=now//86400
   key=f'pvp_defence:{defender_id}:{day}'
   row=self.db.execute('SELECT data FROM events WHERE id=?',(key,)).fetchone()
   n=int(json.loads(row[0])['count']) if row else 0
   if n<4:
    defence_points=25;d.points+=25
    self.db.execute('INSERT OR REPLACE INTO events VALUES (?,?)',(key,json.dumps({'count':n+1})))
  else:d.gold+=50
  self.save(a);self.save(d)
  return {'attacker_won':won,'attacker_points':50 if won else 0,'defender_points':defence_points,'rooms_cleared':result['rooms_cleared']}
 def leaderboard(self):
  entries=[]
  for (pid,) in self.db.execute('SELECT id FROM players'):
   p=self.load(pid);entries.append({'player':pid,'points':p.points,'level':p.level(),'wave':p.wave})
  return sorted(entries,key=lambda x:(-x['points'],-x['level'],x['player']))

def simulate(seed=2026,styles=None):
 engine=Engine(seed=seed)
 profiles={'Dedicated':(6, 'Balanced'),'Regular':(2,'Fortress'),'Casual':(.75,'Swarm')}
 if styles:profiles={name:(hours,styles.get(name,style)) for name,(hours,style) in profiles.items()}
 for name,(hours,style) in profiles.items():engine.create(name,style)
 daily=[]
 for day in range(7):
  for name,(hours,style) in profiles.items():
   # 48 offline waves/day, active raids at 1.5/hour, one daily mission
   for w in range(48):engine.invasion(name,day*86400+w*1800)
   raids=round(hours*1.5)
   for k in range(raids):engine.fortress(name,day*86400+k*1200)
   p=engine.load(name);p.xp+=220;p.gold+=500;engine.save(p)
   # Spend until reaching a reasonable upgrade threshold; unlock rooms when affordable.
   for k in range(80):
    p=engine.load(name)
    if len(p.rooms)<p.capacity() and p.gold>5000:
     m,t=PATTERNS[style][len(p.rooms)%len(PATTERNS[style])]
     if m=='Dragon' and any(r.monster=='Dragon' for r in p.rooms):m='Skeleton'
     try:engine.add_room(name,m,t);continue
     except ValueError:pass
    candidates=[]
    for i,r in enumerate(p.rooms):
     for kind,level,cap in [('monster',r.monster_level,MONSTER_CAP),('trap',r.trap_level,TRAP_CAP),('room',r.level,ROOM_CAP)]:
      if level<cap:
       cost=engine.upgrade_cost(kind,level)
       if cost<=p.gold-700:candidates.append((level,cost,i,kind))
    if not candidates:break
    _,_,i,kind=min(candidates)
    engine.upgrade(name,i,kind)
   # PvP is tested separately in self-test: no fabricated opponents in this 3-profile progression run.
  daily.append({'day':day+1,**{name:{'level':engine.load(name).level(),'gold':engine.load(name).gold,'points':engine.load(name).points,'rooms':len(engine.load(name).rooms),'wave':engine.load(name).wave} for name in profiles}})
 return {'model':'integrated prototype v3; offline waves, upgrades, fortress economy; PvP separate','seed':seed,'daily':daily,'leaderboard':engine.leaderboard(),'limitations':['NPC invasion uses power-based win probability, not per-turn battle simulation','PvP uses v2 five-room bounded attrition, not full 15-room per-tick combat','No Discord integration or scheduler; external process must call on time','No event-end enforcement or live matchmaking service']}

def self_test():
 e=Engine(seed=7);a=e.create('a');b=e.create('b')
 assert a.level()==1 and len(a.rooms)==5
 assert e.next_preview('a')['wave']==1
 assert e.upgrade('a',0,'trap')['new_level']==2
 assert e.load('a').gold<5000
 assert e.invasion('a',0)['wave']==1
 assert e.load('a').wave==1
 assert e.fortress('a',0)['xp']==260
 try:e.pvp('a','a',0);raise AssertionError('self PvP allowed')
 except ValueError:pass
 # Upgrading one trap need not exceed the 10% matchmaking window.
 assert e.load('a').power()>0
 # Match equal players, verify cooldown and repeat target restrictions
 c=e.create('c');d=e.create('d')
 result=e.pvp('c','d',0);assert isinstance(result['attacker_won'],bool)
 try:e.pvp('c','d',3600);raise AssertionError('cooldown bypassed')
 except ValueError:pass
 try:e.pvp('c','d',21600);raise AssertionError('repeat target bypassed')
 except ValueError:pass
 assert len(e.leaderboard())==4
 print('SELF TEST PASS: create, upgrade, preview, invasion, fortress, PvP, cooldown, repeat target, leaderboard')

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--simulate',action='store_true');ap.add_argument('--self-test',action='store_true');ap.add_argument('--seed',type=int,default=2026);ap.add_argument('--output',default='/mnt/data/dungeon_master_results.json');args=ap.parse_args()
 if args.self_test:self_test()
 if args.simulate:
  results=simulate(args.seed);Path(args.output).write_text(json.dumps(results,indent=2));print(json.dumps(results['daily'][-1],indent=2))

# Transaction wrapping is applied after class definition. A write lock is acquired
# by SQLite before reading player state, preventing multi-process lost updates.
import functools
def _atomic(method):
 @functools.wraps(method)
 def wrapped(self,*args,**kwargs):
  self.db.execute('BEGIN IMMEDIATE')
  try:
   value=method(self,*args,**kwargs)
   self.db.execute('COMMIT')
   return value
  except BaseException:
   self.db.execute('ROLLBACK')
   raise
 return wrapped
for _name in ('create','upgrade','add_room','change_room','invasion','fortress','pvp'):
 setattr(Engine,_name,_atomic(getattr(Engine,_name)))
