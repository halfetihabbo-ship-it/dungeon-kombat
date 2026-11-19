"""Dungeon Master balance prototype v2. Python 3.10+, standard library only.
Room-by-room combat using normalized deployment budgets, finite status effects,
scouting and fixed-seed Monte Carlo. Not a Discord bot.
"""
from __future__ import annotations
from dataclasses import dataclass
import random, json, argparse, statistics

MONSTERS = {
 'Goblin':(85,17,3,1.35,1), 'Skeleton':(145,21,10,.85,2),
 'Orc':(190,27,9,.75,3), 'Spider':(100,14,4,1.05,2),
 'Necromancer':(105,15,4,.85,3), 'Dragon':(260,34,12,.65,6),
}
TRAPS = {'Spike':(36,2),'Poison':(20,2),'Fire':(33,3),'Ice':(20,3),'Arrow':(42,3),'Curse':(14,2)}
ATTACKS = ('Cleave','Siege','Dispel','Pierce')
BUILDS = {
 'Swarm':[('Goblin','Spike'),('Spider','Poison')],
 'Fortress':[('Skeleton','Arrow'),('Orc','Ice')],
 'Curse':[('Necromancer','Curse'),('Spider','Poison')],
 'Balanced':[('Goblin','Spike'),('Skeleton','Arrow'),('Spider','Poison'),('Necromancer','Curse'),('Orc','Ice')],
 'Dragon':[('Dragon','Fire'),('Skeleton','Ice'),('Goblin','Spike'),('Spider','Poison'),('Orc','Arrow')],
}
# Defensive counter multipliers. Attacker sees category on reconnaissance, not layout.
COUNTERS = {
 'Swarm':{'Cleave':.76,'Siege':1.13,'Dispel':1.09,'Pierce':1.03},
 'Fortress':{'Cleave':1.10,'Siege':.76,'Dispel':1.10,'Pierce':.90},
 'Curse':{'Cleave':1.08,'Siege':1.04,'Dispel':.76,'Pierce':1.02},
 'Balanced':{'Cleave':1.0,'Siege':1.0,'Dispel':1.0,'Pierce':1.0},
 'Dragon':{'Cleave':1.06,'Siege':.93,'Dispel':1.02,'Pierce':.78},
}
SCOUT_COUNTER={'Swarm':'Cleave','Fortress':'Siege','Curse':'Dispel','Dragon':'Pierce'}

def clamp(x,low,high):return max(low,min(high,x))

def layout(style, rooms=5):
 pattern=BUILDS[style]; result=[pattern[i%len(pattern)] for i in range(rooms)]
 # Only one legendary allowed in a layout.
 assert sum(m=='Dragon' for m,t in result)<=1
 return result

def unit_power(name,level=10):
 hp,attack,armor,speed,cost=MONSTERS[name]
 scale=1+.055*(level-1)
 # Defensive effective power per deployment point; capped armour and sustain.
 raw=(hp*scale*.075 + attack*scale*speed*1.8 + armor*.9)/cost**.40
 if name=='Necromancer':raw+=8 # healing charges: at most two per encounter
 if name=='Spider':raw+=7 # poison capped at 2 stacks
 if name=='Dragon':raw*=.83 # one legendary; slow, high deployment cost
 return raw

def trap_power(name,level=10):
 dmg,cost=TRAPS[name]
 scale=1+.065*(level-1)
 utility={'Spike':0,'Poison':9,'Fire':6,'Ice':12,'Arrow':3,'Curse':13}[name]
 return (dmg*scale*.72+utility)/cost**.35

def room_power(monster,trap,monster_level=10,trap_level=10,room_level=10):
 synergy=1.05 if (monster,trap) in [('Spider','Poison'),('Necromancer','Curse'),('Dragon','Fire')] else 1
 room_bonus=1+min(.12,.008*(room_level-1))
 return (unit_power(monster,monster_level)+trap_power(trap,trap_level))*synergy*room_bonus

def fight(style,attack_type,seed=1,rooms=5,def_level=10,atk_level=10,scout=False):
 """Simulate bounded attrition across ordered rooms; defender wins if attack runs out of momentum.
 Attack budget is calibrated once to the equal-budget baseline, not to the chosen defender.
 """
 rng=random.Random(seed); order=layout(style,rooms)
 # Calibration reference is a balanced, equally levelled five-room dungeon.
 ref=sum(room_power(m,t,10,10,10) for m,t in layout('Balanced',rooms))
 attack_budget=ref*(1+.055*(atk_level-10))*rng.uniform(.80,1.20)
 defence_budget=sum(room_power(m,t,def_level,def_level,def_level) for m,t in order)
 # Convert aggregate budget difference to modest bounded advantage.
 advantage=clamp(defence_budget/ref,.96,1.04)*({"Curse":1.035,"Swarm":.98}.get(style,1.0))
 counter=1+(COUNTERS[style][attack_type]-1)*.45
 if scout:
  best=SCOUT_COUNTER.get(style,attack_type)
  # Recon allows switching one of four attackers; only 25% counter improvement.
  counter=counter*.75+(1+(COUNTERS[style][best]-1)*.45)*.25
 # Each room has a contest; attacker health/momentum carries between rooms.
 momentum=attack_budget
 total=defence_budget
 for i,(m,t) in enumerate(order):
  weight=room_power(m,t,def_level,def_level,def_level)/total
  # Armour, poison, fire and ice are accounted for in unit/trap power;
  # no infinite DOT, stuns, healing or revives.
  order_bonus=1+.025*(i-(rooms-1)/2)/max(1,rooms)
  pressure=ref*weight*advantage*counter*order_bonus*rng.uniform(.85,1.15)
  momentum-=pressure
  if momentum<=0:break
 return {'defender_win':momentum<=0,'attacker_momentum':round(max(0,momentum),2)}

def run(n=1000,seed=2026):
 matrix={};recon={};strength={}
 for i,style in enumerate(BUILDS):
  for j,attack in enumerate(ATTACKS):
   results=[fight(style,attack,seed=seed+i*100000+j*10000+k) for k in range(n)]
   matrix[f'{style}/{attack}']=round(100*sum(x['defender_win'] for x in results)/n,1)
  for scouting in (False,True):
   results=[fight(style,ATTACKS[k%4],seed=seed+1000000+i*10000+k,scout=scouting) for k in range(n)]
   recon[f'{style}/{scouting}']=round(100*sum(x['defender_win'] for x in results)/n,1)
  for level in (9,10,11):
   results=[fight(style,ATTACKS[k%4],seed=seed+2000000+i*10000+k,atk_level=level) for k in range(n)]
   strength[f'{style}/attacker_level_{level}']=round(100*sum(x['defender_win'] for x in results)/n,1)
 return {'model':'bounded room-by-room budget/attrition prototype v2','seed':seed,'battles_per_matchup':n,'matrix':matrix,'recon':recon,'strength':strength,'notes':['No Discord integration','No per-tick unit HP engine','Combat effects are budgeted and capped, not individually animated']}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--battles',type=int,default=1000);p.add_argument('--seed',type=int,default=2026);p.add_argument('--output',default='/mnt/data/dungeon_balance_results.json');args=p.parse_args()
 result=run(args.battles,args.seed)
 with open(args.output,'w') as f:json.dump(result,f,indent=2)
 print(json.dumps(result,indent=2))
