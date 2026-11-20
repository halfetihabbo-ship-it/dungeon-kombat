"""Dungeon Climber core. Standard-library only; no Discord dependency."""
from __future__ import annotations
import json, math, os, random, sqlite3, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = os.getenv('DATABASE_PATH', '/data/dungeon_climber.db')
BATTLE_SECONDS = 15
OFFLINE_CAP_SECONDS = 8 * 3600
EVENT_DAYS = 7
WEAPONS = [
 ('Rusty Sword',5),('Wooden Club',8),('Iron Dagger',12),
 ('Steel Sword',20),('Hunter\'s Axe',28),('Knight\'s Blade',38),
 ('Shadow Dagger',55),('Warhammer',70),('Frostblade',90),
 ('Infernal Axe',120),('Thunder Sword',155),('Dragonfang',195),
 ('Abyssal Blade',250),('Celestial Sword',320),('Sword of Eternity',400)]
ARMOUR = [
 ('Worn Leather',5),('Cloth Robes',8),('Reinforced Leather',12),
 ('Chainmail',20),('Iron Plate',28),('Steel Armour',38),
 ('Guardian Plate',55),('Shadow Armour',70),('Frostguard',90),
 ('Infernal Armour',120),('Thunderplate',155),('Dragonhide',195),
 ('Abyssal Armour',250),('Celestial Armour',320),('Armour of Eternity',400)]
RARITIES = ['Common']*3+['Uncommon']*3+['Rare']*3+['Epic']*3+['Legendary']*3
RARITY_UNLOCK = {'Common':1,'Uncommon':1,'Rare':21,'Epic':51,'Legendary':101}
RARITY_WEIGHTS = {'Common':50,'Uncommon':30,'Rare':15,'Epic':4,'Legendary':1}
CLASSES = {'Berserker':(1.15,0.90,1.00),'Guardian':(0.92,1.20,1.15),'Rogue':(1.06,1.00,1.00)}


def utcnow(): return time.time()
def tier(floor_):
    return 1.50 if floor_>=350 else 1.35 if floor_>=200 else 1.20 if floor_>=100 else 1.10 if floor_>=50 else 1.0

def gear_stat(item):
    # Endless scaling applies to every dropped item; no power ceiling.
    return round((item['base'] + 0.60 * item['found_floor']) * tier(item['found_floor']) * (1 + 0.075*item.get('plus',0) + 0.025*item.get('refine',0)))

def new_item(kind,index,floor_):
    name,base = (WEAPONS if kind=='weapon' else ARMOUR)[index]
    return {'kind':kind,'name':name,'base':base,'rarity':RARITIES[index],
            'found_floor':floor_,'plus':0,'refine':0}

def open_db():
    path=Path(DB_PATH); path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript('''CREATE TABLE IF NOT EXISTS players (
      user_id INTEGER PRIMARY KEY, username TEXT NOT NULL, state TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
    return db

def event_start(db):
    row=db.execute("SELECT value FROM config WHERE key='start'").fetchone()
    if row:return float(row['value'])
    setting=os.getenv('EVENT_START_UTC','').strip()
    if setting:
        start=datetime.fromisoformat(setting.replace('Z','+00:00'))
        if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
        return start.timestamp()
    # If not configured, event starts at first player registration.
    return None

def event_window(db,now=None):
    now=utcnow() if now is None else now
    start=event_start(db)
    return start, (start+EVENT_DAYS*86400 if start is not None else None)

def begin_event(db,now=None):
    now=utcnow() if now is None else now
    if event_start(db) is None:
        db.execute("INSERT OR IGNORE INTO config(key,value) VALUES('start',?)",(str(now),))
    return event_window(db,now)

def initial_state(cls,now):
    return {'class':cls,'floor':1,'best':1,'best_at':now,'level':1,'xp':0,
       'gold':250,'materials':0,'keys':0,'hp':100,'last_tick':now,'wins':0,'fails':0,
       'farm':0,'farming':False,'farming_steps':0,'retry_streak':0,
       'weapon':new_item('weapon',0,1),'armour':new_item('armour',0,1),
       'inventory':[],'pity':0,'boss':None,'boss_mercy':0,'daily':-1,
       'daily_claimed':0,'challenges':0,'ability_cd':0,'last_report':'Ready to climb!',
       'manual_wins':0,'active_rewards':0}

def get_player(db,uid):
    row=db.execute('SELECT * FROM players WHERE user_id=?',(uid,)).fetchone()
    return json.loads(row['state']) if row else None

def save_player(db,uid,username,s):
    db.execute('INSERT INTO players(user_id,username,state) VALUES(?,?,?) '
               'ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,state=excluded.state',
               (uid,username,json.dumps(s,separators=(',',':'))))

def create_player(db,uid,username,cls,now=None):
    now=utcnow() if now is None else now
    if cls not in CLASSES:raise ValueError('Choose a valid class.')
    db.execute('BEGIN IMMEDIATE')
    try:
        if get_player(db,uid):raise ValueError('You already have a hero.')
        start,end=begin_event(db,now)
        if now<start:raise ValueError('The event has not started yet.')
        if now>=end:raise ValueError('The seven-day event has finished.')
        s=initial_state(cls,now);save_player(db,uid,username,s)
        db.execute('COMMIT');return s
    except Exception:
        db.execute('ROLLBACK');raise

def attack_power(s):
    return (14 + s['level']*2.0 + gear_stat(s['weapon'])*0.42 + s['weapon']['refine']*1.2)*CLASSES[s['class']][0]

def defense_power(s):
    return (8 + s['level']*1.2 + gear_stat(s['armour'])*0.42 + s['armour']['refine']*1.2)*CLASSES[s['class']][1]

def max_hp(s):return int((100+s['level']*6+gear_stat(s['armour'])*0.24)*CLASSES[s['class']][2])

def enemy_power(f):return 24+1.65*f+0.0038*f*f

def combat_odds(s,f):
    power=attack_power(s)*0.65+defense_power(s)*0.35
    ratio=power/max(1,enemy_power(f))
    return max(0.08,min(0.96,0.56+0.65*(ratio-1)))

def drop_item(s,rng,guaranteed=False):
    f=s['floor'];allowed=[r for r in RARITY_WEIGHTS if f>=RARITY_UNLOCK[r]]
    weights=[RARITY_WEIGHTS[r] for r in allowed]
    rarity=rng.choices(allowed,weights=weights,k=1)[0]
    kind=rng.choice(['weapon','armour'])
    indices=[i for i,r in enumerate(RARITIES) if r==rarity]
    item=new_item(kind,rng.choice(indices),f)
    current=s[kind]
    if gear_stat(item)>gear_stat(current):
        # Transfer paid upgrades to the replacement item.
        item['plus']=current.get('plus',0);item['refine']=current.get('refine',0)
        s[kind]=item;s['materials']+=1;s['pity']=0
        return f"Equipped {item['name']} ({rarity})"
    s['materials']+=2 if rarity in ('Epic','Legendary') else 1
    s['pity']+=1
    return f"Dismantled {item['name']} (+materials)"

def milestone_loot(s,rng):
    f=s['floor']
    if f%10: return ''
    s['gold']+=100+f*3;s['materials']+=4+f//30
    if f%50==0:s['keys']+=2
    elif f%25==0:s['keys']+=1
    if s['pity']>=4:
        # Pity chest: guaranteed slight improvement, without bypassing refinement.
        kind=min(('weapon','armour'),key=lambda k:gear_stat(s[k]))
        item=dict(s[kind]);item['found_floor']=max(f,item['found_floor']+1)
        s[kind]=item;s['pity']=0
        return f'Milestone chest: improved {kind} (pity protection)'
    return 'Milestone chest: '+drop_item(s,rng,True)

def add_xp(s,amount):
    s['xp']+=amount
    while s['xp']>=40+s['level']*18:
        s['xp']-=40+s['level']*18;s['level']+=1;s['hp']=max_hp(s)

def auto_upgrade(s):
    # Low-cost incremental refinement; no finite upper bound.
    count=0
    for _ in range(3):
        kind=min(('weapon','armour'),key=lambda k:gear_stat(s[k]))
        item=s[kind];cost_gold=150+item['refine']*85;cost_mat=3+item['refine']//5
        if s['gold']<cost_gold or s['materials']<cost_mat:break
        if item['refine']>=s['floor']//10+10:break
        s['gold']-=cost_gold;s['materials']-=cost_mat;item['refine']+=1;count+=1
    return count

def _one_battle(s,rng):
    target=s['floor']+1
    if target%50==0:
        s['boss']={'floor':target,'hp':round(140+target*1.6),'max_hp':round(140+target*1.6),
                   'turn':0,'guard':False,'second_wind':False,'cooldown':0}
        return 'Legendary boss waiting — fight it using the Boss button'
    # Smart farming: do not blindly spend battles on unwinnable floors.
    odds=combat_odds(s,target)
    farming=s['farming'] or (odds<0.61 and s['retry_streak']>=2)
    if farming:
        s['farming']=True;s['farming_steps']+=1;s['farm']+=1
        s['gold']+=round(16+s['floor']*0.9)
        s['materials']+=1+(s['floor']//150)
        add_xp(s,6+s['floor']//18)
        s['hp']=min(max_hp(s),s['hp']+max(1,max_hp(s)//20))
        auto_upgrade(s)
        if s['farming_steps']>=5:
            s['farming_steps']=0;s['farming']=False;s['retry_streak']=0
        return 'Farmed resources'
    if rng.random()<odds:
        s['floor']=target;s['wins']+=1;s['retry_streak']=0
        s['gold']+=round(20+target*0.85);s['materials']+=rng.randint(0,2)
        add_xp(s,10+target//16)
        s['hp']=min(max_hp(s),s['hp']+max(1,max_hp(s)//20))
        if rng.random()<0.055:drop_item(s,rng)
        loot=milestone_loot(s,rng)
        if target%10==0 and target%50!=0:s['gold']+=target*2
        auto_upgrade(s)
        return loot or f'Cleared floor {target}'
    s['fails']+=1;s['retry_streak']+=1
    s['gold']+=round(7+target*0.25);s['materials']+=int(rng.random()<0.25)
    s['hp']=max(1,s['hp']-max(1,max_hp(s)//18))
    if s['hp']<max_hp(s)*0.3:s['hp']=max_hp(s)//2
    if s['retry_streak']>=5:s['farming']=True;s['farming_steps']=0
    return 'Floor attempt failed; recovery and farming available'

def progress(s,now=None,seed=None):
    now=utcnow() if now is None else now
    start=s['last_tick'];effective=max(0,min(now-start,OFFLINE_CAP_SECONDS))
    rng=random.Random(seed)
    count=int(effective//BATTLE_SECONDS)
    if count<=0:return 'No new battles yet (15 seconds per battle).'
    processed=0;last=''
    for _ in range(count):
        if s['boss']:break
        last=_one_battle(s,rng);processed+=1
    # Keep remaining unused time if boss blocked, but do not retroactively
    # apply that time after the boss is defeated: boss is a real checkpoint.
    s['last_tick']=now-(effective-count*BATTLE_SECONDS) if not s['boss'] else now
    if s['floor']>s['best']:
        s['best']=s['floor'];s['best_at']=now
    msg=f'{processed} battles · Floor {s["floor"]} · {last}'
    s['last_report']=msg
    return msg

def refresh(db,uid,username,now=None):
    now=utcnow() if now is None else now
    db.execute('BEGIN IMMEDIATE')
    try:
        s=get_player(db,uid)
        if s is None:raise ValueError('Use /play to create a hero first.')
        start,end=event_window(db,now)
        if start is not None and now<start:msg='Event has not started.'
        elif end is not None and now>=end:
            # Stop progress at event end; never count later time.
            msg=progress(s,min(end,now)) if s['last_tick']<end else 'Event finished.'
        else:msg=progress(s,now)
        save_player(db,uid,username,s);db.execute('COMMIT');return s,msg
    except Exception:
        db.execute('ROLLBACK');raise

def mutate(db,uid,username,action,now=None):
    now=utcnow() if now is None else now
    db.execute('BEGIN IMMEDIATE')
    try:
        s=get_player(db,uid)
        if not s:raise ValueError('Use /play first.')
        start,end=event_window(db,now)
        if start is not None and now<start:raise ValueError('Event has not started.')
        if end is not None and now>=end:raise ValueError('Event finished; leaderboard is frozen.')
        progress(s,now)
        if action=='upgrade_weapon' or action=='upgrade_armour':
            kind=action.split('_')[1];item=s[kind]
            if item['plus']>=10:raise ValueError('At +10. Use Refinement for endless upgrades.')
            cost=250+item['plus']*210;materials=3+item['plus']*2
            if s['gold']<cost or s['materials']<materials:raise ValueError(f'Need {cost:,} gold and {materials} materials.')
            s['gold']-=cost;s['materials']-=materials;item['plus']+=1
            msg=f'Upgraded {item["name"]} to +{item["plus"]}.'
        elif action in ('refine_weapon','refine_armour'):
            if s['floor']<100:raise ValueError('Refinement unlocks at Floor 100.')
            kind=action.split('_')[1];item=s[kind]
            cost=150+item['refine']*85;materials=3+item['refine']//5
            if s['gold']<cost or s['materials']<materials:raise ValueError(f'Need {cost:,} gold and {materials} materials.')
            s['gold']-=cost;s['materials']-=materials;item['refine']+=1
            msg=f'Refined {item["name"]} to R{item["refine"]}.'
        elif action=='vault':
            if s['keys']<1:raise ValueError('You need a Vault Key. Earn them at milestone bosses.')
            s['keys']-=1;s['gold']+=300+s['floor']*4;s['materials']+=8+s['floor']//30
            msg='Opened the Treasure Vault: gold and materials awarded!'
            if random.random()<0.65:msg+=' '+drop_item(s,random.Random(),True)
        elif action=='daily':
            day=int((now-start)//86400)
            if s['daily']==day:raise ValueError('Daily bounty already claimed today.')
            s['daily']=day;s['gold']+=400+s['floor']*2;s['materials']+=12;s['active_rewards']+=1
            msg='Daily bounty claimed: gold and 12 materials!'
        elif action=='challenge':
            day=int((now-start)//86400)
            if s.get('challenge_day')==day:raise ValueError('Challenge already completed today.')
            odds=max(.25,min(.85,combat_odds(s,s['floor']+5)+0.1))
            s['challenge_day']=day
            if random.random()<odds:
                s['gold']+=250+s['floor']*3;s['materials']+=10;s['active_rewards']+=1
                msg='Gauntlet victory! Bonus gold and 10 materials.'
            else:s['gold']+=100;msg='Gauntlet defeated you, but you earned 100 gold.'
        elif action.startswith('boss_'):
            b=s.get('boss')
            if not b:raise ValueError('No legendary boss is waiting.')
            move=action[5:]
            if move not in ('attack','guard','power','heal'):raise ValueError('Unknown boss move.')
            if move=='power' and b['cooldown']>0:raise ValueError(f'Power Strike available in {b["cooldown"]} turn(s).')
            if move=='heal' and b['second_wind']:raise ValueError('Second Wind can only be used once per boss.')
            if b['turn']>=6:raise ValueError('Boss encounter expired. Retry it.')
            b['turn']+=1
            if move=='heal':
                s['hp']=min(max_hp(s),s['hp']+int(max_hp(s)*.35));b['second_wind']=True
                dealt=0
            elif move=='guard':dealt=round(attack_power(s)*.25)
            else:
                dealt=round(attack_power(s)*(1.75 if move=='power' else 1.0)*(1+s['boss_mercy']*.05)*random.uniform(.85,1.15))
            b['hp']-=dealt
            if move=='power':b['cooldown']=3
            elif b['cooldown']>0:b['cooldown']-=1
            if b['hp']<=0:
                s['floor']=b['floor'];s['best']=max(s['best'],s['floor']);s['best_at']=now
                s['gold']+=500+b['floor']*5;s['materials']+=20+b['floor']//20;s['keys']+=2
                s['manual_wins']+=1;s['boss_mercy']=0;s['boss']=None;s['retry_streak']=0
                add_xp(s,80+b['floor']//3)
                msg=f'🏆 Legendary boss defeated! Floor {s["floor"]} unlocked. +2 Vault Keys.'
            else:
                # Telegraph cycles: guard reduces incoming damage.
                incoming=round((12+b['floor']*.11)*(1.6 if b['turn']%3==0 else 1.0))
                if move=='guard':incoming=round(incoming*.25)
                incoming=max(1,round(incoming*(1-min(.6,defense_power(s)/(enemy_power(b['floor'])*2)))))
                s['hp']-=incoming
                if s['hp']<=0 or b['turn']>=6:
                    s['boss_mercy']=min(4,s['boss_mercy']+1)
                    s['hp']=max_hp(s);s['boss']=None
                    s['gold']+=100+s['floor'];s['materials']+=5
                    msg=f'Boss escaped. Mercy bonus now +{s["boss_mercy"]*5}% damage. Farm and retry.'
                    # Boss gate will respawn on next tick.
                else:
                    msg=f'{move.title()}: dealt {dealt}, took {incoming}. Boss HP {max(0,b["hp"]):,}/{b["max_hp"]:,}. Turn {b["turn"]}/6.'
        else:raise ValueError('Unknown action.')
        save_player(db,uid,username,s);db.execute('COMMIT');return s,msg
    except Exception:
        db.execute('ROLLBACK');raise

def leaderboard(db,limit=10):
    rows=[]
    for row in db.execute('SELECT user_id,username,state FROM players'):
        s=json.loads(row['state']);rows.append((row['user_id'],row['username'],s['best'],s['best_at']))
    return sorted(rows,key=lambda r:(-r[2],r[3],r[0]))[:limit]
