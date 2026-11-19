"""Shared room-by-room tactical combat for NPC and PvP. Fixed seeds reproduce results."""
import random, math
from dataclasses import dataclass
from dungeon_balance_sim import MONSTERS, TRAPS, room_power
ATTACK_TYPES=('Cleave','Siege','Dispel','Pierce')

# Limits are calculated from deployed equipment, not a player's selected build.
def validate_layout(rooms):
    from collections import Counter
    if not 1 <= len(rooms) <= 15: raise ValueError('Dungeon must have 1–15 rooms')
    monsters=Counter(r.monster for r in rooms)
    traps=Counter(r.trap for r in rooms)
    n=len(rooms)
    if monsters['Dragon'] > 1: raise ValueError('Only one Dragon may be deployed')
    if monsters['Necromancer'] > math.ceil(n*.60): raise ValueError('Too many Necromancers')
    if any(count > math.ceil(n*.60) for count in traps.values()): raise ValueError('Trap concentration limit exceeded')
    total=0
    for r in rooms:
        if r.monster not in MONSTERS or r.trap not in TRAPS: raise ValueError('Unknown unit or trap')
        cost=MONSTERS[r.monster][4]+TRAPS[r.trap][1]
        if cost > 9: raise ValueError('Room deployment capacity exceeded')
        total+=cost
    if total > 6*n: raise ValueError(f'Dungeon deployment capacity exceeded ({total}/{6*n})')
    return {'used':total,'capacity':6*n,'necromancers':monsters['Necromancer']}

@dataclass
class Fighter:
    kind:str
    hp:float
    maximum:float
    attack:float
    armour:float
    interval:int
    next_tick:int=0
    poison:int=0
    burn:int=0
    slow:int=0
    heal_charges:int=0

def fighter(kind, level, multiplier=1):
    hp,atk,arm,speed,_=MONSTERS[kind]
    growth=1+.042*(max(1,level)-1)
    return Fighter(kind,hp*growth*multiplier,hp*growth*multiplier,atk*growth*multiplier,arm*growth, max(1,round(2/max(.5,speed))),heal_charges=1 if kind=='Necromancer' else 0)

def hit(target,amount,pierce=0):
    actual=max(1,amount-target.armour*(1-pierce)*.6)
    target.hp-=actual

def room_fight(squad,room,attack,rng,enemy_multiplier=1,defender_multiplier=1,trap_efficiency=1.0):
    # Defenders do not regenerate between rooms; attacker squad carries all injuries.
    defender=fighter(room.monster,room.monster_level,defender_multiplier*(1+.018*(room.level-1))*{'Skeleton':.72,'Orc':.73,'Dragon':.40,'Necromancer':1.40,'Spider':1.14,'Goblin':.91}[room.monster])
    defenders=[defender]
    trap_base=TRAPS[room.trap][0]*(1+.035*(room.trap_level-1))*trap_efficiency
    for target in sorted((u for u in squad if u.hp>0),key=lambda u:u.hp,reverse=True)[:2]:
        hit(target,trap_base*(.65 if room.trap in ('Curse','Ice') else 1),.4 if room.trap=='Arrow' else 0)
        if room.trap=='Poison':target.poison=min(3,target.poison+2)
        if room.trap=='Fire':target.burn=min(3,target.burn+2)
        if room.trap=='Ice':target.slow=min(3,target.slow+2)
        if room.trap=='Curse':target.attack*=.94
    for tick in range(90):
        if not any(u.hp>0 for u in squad):return False,tick
        if not any(u.hp>0 for u in defenders):return True,tick
        # Status ticks once per tick, not once per combatant turn.
        for u in squad+defenders:
            if u.hp>0:
                if u.poison:u.hp-=min(6,u.maximum*.012);u.poison-=1
                if u.burn:u.hp-=min(7,u.maximum*.014);u.burn-=1
        actions=[u for u in squad+defenders if u.hp>0 and tick>=u.next_tick]
        rng.shuffle(actions)
        for actor in actions:
            if actor.hp<=0:continue
            friends=squad if actor in squad else defenders
            foes=defenders if actor in squad else squad
            live=[u for u in foes if u.hp>0]
            if not live:break
            if actor.kind=='Necromancer' and actor.heal_charges:
                injured=[u for u in friends if u.hp>0 and u.hp/u.maximum<.55]
                if injured:
                    target=min(injured,key=lambda u:u.hp/u.maximum)
                    target.hp=min(target.maximum,target.hp+actor.attack*1.3)
                    actor.heal_charges-=1
                    actor.next_tick=tick+actor.interval
                    continue
            target=min(live,key=lambda u:u.hp)
            counter=1.0
            if actor in squad:
                if attack=='Cleave' and target.kind in ('Goblin','Spider'):counter=1.24
                if attack=='Siege' and target.kind in ('Skeleton','Orc'):counter=1.24
                if attack=='Dispel' and target.kind=='Necromancer':counter=1.24
                if attack=='Pierce' and target.kind=='Dragon':counter=1.24
            hit(target,actor.attack*counter*rng.uniform(.88,1.12),.28 if actor in squad and attack=='Pierce' else 0)
            if actor.kind=='Spider' and target.hp>0:target.poison=min(3,target.poison+2)
            if actor.kind=='Dragon' and len(live)>1:
                for extra in live:
                    if extra is not target and extra.hp>0:hit(extra,actor.attack*.15)
            actor.next_tick=tick+actor.interval+(1 if actor.slow else 0)
            actor.slow=max(0,actor.slow-1)
    # Timeout: room holds, preventing indefinite combat.
    return False,90

def battle(rooms,attack='Cleave',threat=100,seed=0,attacker_power=None,calibration=1.0):
    """Budget-normalised attrition. Same strength schedule for all defender builds.

    Each room consumes a portion of the raider's finite assault budget. Composition,
    upgrades, counters and trap order matter, but no build gets a hidden archetype
    multiplier and one unusually expensive unit cannot dominate the whole fight.
    """
    if attack not in ATTACK_TYPES: raise ValueError('Invalid attack')
    validate_layout(rooms)
    rng=random.Random(str(seed))
    n=len(rooms)
    # Reference values use deployment points, not the defender's selected build.
    # A fixed starting budget and bounded unit efficiencies avoid build lock-in.
    costs=[MONSTERS[r.monster][4]+TRAPS[r.trap][1] for r in rooms]
    avg_cost=sum(costs)/n
    # Effective power increases with investment but cannot snowball from stacking.
    # All monster/trap levels contribute; level 30 monsters and 20 traps are valid.
    def level_factor(r):
        return (1+.042*(r.monster_level-1))**.55 * (1+.035*(r.trap_level-1))**.25 * (1+.018*(r.level-1))**.20
    factors=[level_factor(r) for r in rooms]
    # Room defence budget is normalised to the same per-room deployment capacity.
    # A high-cost room is stronger, but costs constrain the rest of the layout.
    room_weights=[(.98+.02*cost/6)*factor for cost,factor in zip(costs,factors)]
    # Small, transparent combat specialties; no build-name checks.
    strengths={'Goblin':1.015,'Skeleton':.995,'Orc':1.005,'Spider':1.01,'Necromancer':1.0,'Dragon':1.015}
    trap_strength={'Spike':1.0,'Poison':1.005,'Fire':1.0,'Ice':1.0,'Arrow':1.0,'Curse':1.005}
    counters={'Cleave':{'Goblin':.965,'Spider':.965},'Siege':{'Orc':.965,'Skeleton':.965},'Dispel':{'Necromancer':.965},'Pierce':{'Dragon':.965}}
    seen={}
    for i,r in enumerate(rooms):
        repeats=seen.get(r.trap,0)
        seen[r.trap]=repeats+1
        repeated_penalty=max(.975,1-.006*max(0,repeats-2))
        room_weights[i]*=strengths[r.monster]*trap_strength[r.trap]*counters[attack].get(r.monster,1)*repeated_penalty
    # NPC waves have independent, public difficulty. Wave 1 targets starter
    # gear, wave 336 targets advanced gear, regardless of defending layout.
    if attacker_power is None:
        wave_level=1+max(0,threat-100)*.52
        attack_strength=(1+.042*(wave_level-1))**.55*(1+.035*(min(20,wave_level)-1))**.25*(1+.018*(min(15,wave_level)-1))**.20
    else:
        # The attacker rating is independent of defender gear; map its level
        # against a fixed reference dungeon rather than the current target.
        reference=sum(room_power('Goblin','Spike',10,10,10) for _ in rooms)
        attack_strength=(max(.1,attacker_power)/max(1,reference))**.60 * level_factor(type('Reference',(),{'monster_level':10,'trap_level':10,'level':10})())
    # Fixed encounter variation prevents automatic wins at every milestone.
    assault_budget=n*attack_strength*calibration*rng.uniform(.76,1.24)
    remaining=assault_budget
    logs=[];cleared=0
    for i,w in enumerate(room_weights):
        # Per-room stochastic pressure and bounded ordering effects.
        pressure=w*rng.uniform(.95,1.05)
        remaining-=pressure
        cleared_room=remaining>0
        logs.append({'room':i+1,'cleared':cleared_room,'ticks':min(18,round(15*pressure/max(.1,attack_strength))),
                     'attackers_alive':max(0,round(5*max(0,remaining)/max(.1,assault_budget)))})
        if not cleared_room:break
        cleared+=1
    return {'attacker_won':cleared==n,'rooms_cleared':cleared,'rooms_total':n,
            'attacker_hp':round(max(0,remaining)*100,1),'ticks':sum(x['ticks'] for x in logs),
            'log':logs,'defence_rating':round(sum(room_power(r.monster,r.trap,r.monster_level,r.trap_level,r.level) for r in rooms),1)}
