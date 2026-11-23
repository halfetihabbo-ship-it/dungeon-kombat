"""Abyss Ascension core. Standard-library only; no Discord dependency."""
from __future__ import annotations
import json, math, os, random, sqlite3, time, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = os.getenv('DATABASE_PATH', '/data/dungeon_climber.db')
BATTLE_SECONDS = 45  # slower passive climb; manual play is the main accelerator
OFFLINE_CAP_SECONDS = 8 * 3600
EVENT_DAYS = 8
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
            'found_floor':floor_,'plus':0,'refine':0,'perk':None}

def open_db():
    path=Path(DB_PATH); path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=5000')
    db.executescript('''CREATE TABLE IF NOT EXISTS players (
      user_id INTEGER PRIMARY KEY, username TEXT NOT NULL, state TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);''')
    db.execute('''CREATE TABLE IF NOT EXISTS adventure_journal (
        user_id INTEGER PRIMARY KEY, baseline TEXT NOT NULL, started_at REAL NOT NULL,
        last_sent REAL NOT NULL DEFAULT 0, last_attempt REAL NOT NULL DEFAULT 0)''')
    db.execute('CREATE TABLE IF NOT EXISTS panel_joins (user_id INTEGER PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS published_panels (guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, message_id INTEGER PRIMARY KEY)')
    return db

def reset_progress_only(db):
    """Erase all hero progress, retaining registrations, panels and launch settings."""
    db.execute('BEGIN IMMEDIATE')
    try:
        count = db.execute('SELECT COUNT(*) FROM players').fetchone()[0]
        db.execute('DELETE FROM players')
        db.execute('DELETE FROM adventure_journal')
        db.execute('COMMIT')
        return count
    except Exception:
        db.execute('ROLLBACK')
        raise


def reset_entire_game(db):
    """Clear game-specific saves and restart the DB-based event clock.

    The externally configured EVENT_START_UTC, if set, is deliberately untouched.
    The caller must require an administrator confirmation before invoking this.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        count = db.execute('SELECT COUNT(*) FROM players').fetchone()[0]
        db.execute('DELETE FROM players')
        db.execute('DELETE FROM adventure_journal')
        db.execute('DELETE FROM panel_joins')
        db.execute("DELETE FROM config WHERE key='start'")
        db.execute('COMMIT')
        return count
    except Exception:
        db.execute('ROLLBACK')
        raise


# Journal snapshots are stored separately so existing player JSON saves stay compatible.
JOURNAL_SECONDS = 12 * 3600

def journal_snapshot(s):
    return {key:int(s.get(key,0)) for key in ('floor','level','xp','xp_total','wins','fails','gold','materials','keys','wheel_spins','arena_wins')}

def journal_row(db,uid,now=None):
    now=utcnow() if now is None else now
    row=db.execute('SELECT * FROM adventure_journal WHERE user_id=?',(uid,)).fetchone()
    if row:return row
    player=get_player(db,uid)
    if player is None:return None
    db.execute('INSERT OR IGNORE INTO adventure_journal(user_id,baseline,started_at,last_attempt) VALUES(?,?,?,0)',
               (uid,json.dumps(journal_snapshot(player)),now))
    return db.execute('SELECT * FROM adventure_journal WHERE user_id=?',(uid,)).fetchone()

def journal_stats(db,uid,s,now=None):
    now=utcnow() if now is None else now
    row=journal_row(db,uid,now)
    if row is None:return None
    baseline=json.loads(row['baseline']);current=journal_snapshot(s)
    delta={k:current[k]-int(baseline.get(k,current[k])) for k in current}
    return {'current':current,'delta':delta,'since':float(row['started_at']),
            'next_due':float(row['started_at'])+JOURNAL_SECONDS,
            'last_sent':float(row['last_sent'] or 0)}

def journal_mark_sent(db,uid,s,now=None):
    now=utcnow() if now is None else now
    db.execute('UPDATE adventure_journal SET baseline=?,started_at=?,last_sent=?,last_attempt=? WHERE user_id=?',
               (json.dumps(journal_snapshot(s)),now,now,now,uid))

def journal_mark_attempt(db,uid,now=None):
    now=utcnow() if now is None else now
    db.execute('UPDATE adventure_journal SET last_attempt=? WHERE user_id=?',(now,uid))

def event_start(db):
    setting=os.getenv('EVENT_START_UTC','').strip()
    # Fixed event configuration overrides legacy saved start timestamps.
    if not setting:
        row=db.execute("SELECT value FROM config WHERE key='start'").fetchone()
        if row:return float(row['value'])
    if setting:
        start=datetime.fromisoformat(setting.replace('Z','+00:00'))
        if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
        return start.timestamp()
    # If not configured, event starts at first player registration.
    return None

def event_window(db,now=None):
    now=utcnow() if now is None else now
    start=event_start(db)
    end_setting=os.getenv('EVENT_END_UTC','').strip()
    if end_setting:
        end_dt=datetime.fromisoformat(end_setting.replace('Z','+00:00'))
        if end_dt.tzinfo is None:end_dt=end_dt.replace(tzinfo=timezone.utc)
        end=end_dt.timestamp()
    else:
        end=start+EVENT_DAYS*86400 if start is not None else None
    if start is not None and end is not None and end <= start:
        raise ValueError('EVENT_END_UTC must be after EVENT_START_UTC')
    return start,end

def begin_event(db,now=None):
    now=utcnow() if now is None else now
    if event_start(db) is None:
        db.execute("INSERT OR IGNORE INTO config(key,value) VALUES('start',?)",(str(now),))
    return event_window(db,now)

def initial_state(cls,now):
    return {'class':cls,'floor':1,'best':1,'best_at':now,'level':1,'xp':0,'xp_total':0,
       'gold':250,'materials':0,'keys':0,'hp':100,'last_tick':now,'wins':0,'fails':0,
       'farm':0,'farming':False,'farming_steps':0,'retry_streak':0,
       'weapon':new_item('weapon',0,1),'armour':new_item('armour',0,1),
       'boss_dm_floor':0,'inventory':[],'auto_equip':True,'enchantment':None,'pity':0,'boss':None,'boss_mercy':0,'daily':-1,
       'daily_claimed':0,'challenges':0,'ability_cd':0,'last_report':'Ready to climb!',
       'manual_wins':0,'active_rewards':0,'chambers':[],'chamber_next':12,'chamber_dm_sent':0,'chamber_notice_count':0,'skill_alloc':{'warrior':0,'defender':0,'treasure':0},'companions':{},'active_companion':None,'arena_day':-1,'arena_tries':0,'arena_wins':0,'merchant_buys':{},'wheel_last':0,'wheel_spins':0,'quest_day':-1,'quest_progress':{},'quest_claimed':False,'goblin_slot':-1,'goblin_attempts':0,'goblin_claimed':False,'goblin_dm_slot':-1,'portals':[],'portal_next':25,'portal_dm_count':0,'portal_active':None,'relics':[],'equipped_relic':None,'camp_buff':None,'camp_until':0,'build':'balanced','expedition_charges':3,'expedition_at':now,'expedition':None,'checkpoint':None,'checkpoint_cleared':0}

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
        if now>=end:raise ValueError('The event has finished.')
        s=initial_state(cls,now);save_player(db,uid,username,s)
        journal_row(db,uid,now)
        db.execute('COMMIT');return s
    except Exception:
        db.execute('ROLLBACK');raise

def skill_points(s):
    return max(0,(s['level']-1)//5-sum(s.get('skill_alloc',{}).values()))

def companion_bonus(s,kind):
    level=s.get('companions',{}).get(s.get('active_companion'),0)
    bonuses={'wolf':'attack','bear':'defense','owl':'treasure','dragon':'boss'}
    return level if bonuses.get(s.get('active_companion'))==kind else 0

RELIC_TYPES = {
 'ember':('🔥 Ember Sigil','attack',0.025),
 'ward':('🛡️ Guardian Charm','defence',0.03),
 'fortune':('💰 Fortune Coin','gold',0.035),
 'vigor':('❤️ Vitality Stone','hp',0.035),
}
def relic_bonus(s,kind):
    key=s.get('equipped_relic')
    return RELIC_TYPES[key][2] if key in RELIC_TYPES and RELIC_TYPES[key][1]==kind else 0

def camp_bonus(s,kind,now=None):
    now=utcnow() if now is None else now
    return 0.08 if s.get('camp_buff')==kind and float(s.get('camp_until',0))>now else 0

def attack_power(s):
    warrior=s.get('skill_alloc',{}).get('warrior',0)
    return (14 + s['level']*2.0 + gear_stat(s['weapon'])*0.42 + s['weapon']['refine']*1.2)*CLASSES[s['class']][0]*(1+min(.3,warrior*.025)+min(.2,companion_bonus(s,'attack')*.025)+enchant_bonus(s,'critical')+gear_perk(s,'power')+relic_bonus(s,'attack')+camp_bonus(s,'attack'))*build_mod(s,'attack')

def defense_power(s):
    return (8 + s['level']*1.2 + gear_stat(s['armour'])*0.42 + s['armour']['refine']*1.2)*CLASSES[s['class']][1]*(1+min(.3,s.get('skill_alloc',{}).get('defender',0)*.025)+min(.2,companion_bonus(s,'defense')*.025)+relic_bonus(s,'defence')+camp_bonus(s,'defence'))*build_mod(s,'defense')

def max_hp(s):return int((100+s['level']*6+gear_stat(s['armour'])*0.24)*CLASSES[s['class']][2]*(1+gear_perk(s,'vitality')+relic_bonus(s,'hp')))

def treasure_multiplier(s):
    return (1+min(.25,s.get('skill_alloc',{}).get('treasure',0)*.02)+min(.20,companion_bonus(s,'treasure')*.025)+enchant_bonus(s,'treasure')+gear_perk(s,'treasure')+relic_bonus(s,'gold')+camp_bonus(s,'gold'))*build_mod(s,'gold')

BUILD_STYLES = {
    'balanced': ('⚖️ Balanced', 1.0, 1.0, 1.0),
    'aggressive': ('⚔️ Aggressive', 1.16, .87, .94),
    'defensive': ('🛡️ Defensive', .90, 1.22, .96),
    'treasure': ('💰 Treasure Hunter', .92, .95, 1.18),
}
EXPEDITION_RECHARGE = 2*3600
EXPEDITION_CAP = 3
CHECKPOINT_STEP = 10

def recharge_expeditions(s, now):
    charges=int(s.get('expedition_charges',3))
    last=float(s.get('expedition_at',now))
    if charges>=EXPEDITION_CAP:
        s['expedition_charges']=EXPEDITION_CAP;s['expedition_at']=now
        return
    gained=max(0,int((now-last)//EXPEDITION_RECHARGE))
    if gained:
        s['expedition_charges']=min(EXPEDITION_CAP,charges+gained)
        s['expedition_at']=now if s['expedition_charges']==EXPEDITION_CAP else last+gained*EXPEDITION_RECHARGE

def checkpoint_floor(s):
    return ((int(s['floor'])//CHECKPOINT_STEP)+1)*CHECKPOINT_STEP

def checkpoint_ready(s):
    target=checkpoint_floor(s)
    return target%50!=0 and target>int(s.get('checkpoint_cleared',0))

def boss_intent(b):
    return ('heavy' if (b['turn']+1)%3==0 else 'feint' if (b['turn']+1)%3==2 else 'strike')

def build_mod(s, stat):
    style=BUILD_STYLES.get(s.get('build','balanced'),BUILD_STYLES['balanced'])
    return style[{'attack':1,'defense':2,'gold':3}[stat]]

def enemy_power(f):return 24+1.65*f+0.0038*f*f

def combat_odds(s,f):
    power=attack_power(s)*0.65+defense_power(s)*0.35
    ratio=power/max(1,enemy_power(f))
    return max(0.08,min(0.96,0.56+0.65*(ratio-1)))

INVENTORY_LIMIT = 40  # 20 weapons + 20 armour pieces
ENCHANTMENTS = {'lifesteal': 'Lifesteal', 'critical': 'Critical Strike', 'boss': 'Boss Slayer', 'treasure': 'Treasure Finder'}

def ensure_gear(s):
    s.setdefault('inventory', [])
    s.setdefault('auto_equip', True)
    s.setdefault('enchantment', None)
    for kind in ('weapon','armour'):
        s[kind].setdefault('id', uuid.uuid4().hex[:12])
        s[kind].setdefault('locked', False)
    for item in s['inventory']:
        item.setdefault('id', uuid.uuid4().hex[:12])
        item.setdefault('locked', False)
    return s

def gear_bag(s,kind):
    return [x for x in s.get('inventory',[]) if x.get('kind')==kind]

def stash(s,item):
    ensure_gear(s)
    bag=gear_bag(s,item['kind'])
    if len(bag)>=20:
        candidates=[x for x in bag if not x.get('locked')]
        if not candidates:return False
        worst=min(candidates,key=gear_stat)
        if gear_stat(worst)>=gear_stat(item):return False
        s['inventory'].remove(worst)
    item.setdefault('id',uuid.uuid4().hex[:12]);item.setdefault('locked',False)
    s['inventory'].append(item)
    return True

def equip_from_bag(s,item):
    ensure_gear(s)
    kind=item['kind'];old=s[kind]
    # Forged upgrades are slot-bound: + and refinement never disappear when swapping.
    old_plus,old_refine=old.get('plus',0),old.get('refine',0)
    s['inventory'].remove(item)
    old['plus']=0;old['refine']=0
    item['plus']=old_plus;item['refine']=old_refine
    s[kind]=item
    stash(s,old)

def gear_perk(s,name):
    return sum(0.02 for kind in ('weapon','armour') if s[kind].get('perk')==name)

def enchant_bonus(s,name):
    return 0.03 if s.get('enchantment')==name else 0.0

def drop_item(s,rng,guaranteed=False):
    f=s['floor'];allowed=[r for r in RARITY_WEIGHTS if f>=RARITY_UNLOCK[r]]
    weights=[RARITY_WEIGHTS[r] for r in allowed]
    rarity=rng.choices(allowed,weights=weights,k=1)[0]
    kind=rng.choice(['weapon','armour'])
    indices=[i for i,r in enumerate(RARITIES) if r==rarity]
    item=new_item(kind,rng.choice(indices),f)
    ensure_gear(s)
    if rarity in ('Rare','Epic','Legendary'):
        item['perk']=rng.choice(['power','treasure','boss','vitality'])
    current=s[kind]
    better=gear_stat(item)>gear_stat(current)
    if better and s['auto_equip'] and not current.get('locked',False):
        # Save the previous item; keep paid upgrades on the equipped slot.
        old=dict(current)
        item['plus']=old.get('plus',0);item['refine']=old.get('refine',0)
        old['plus']=0;old['refine']=0
        s[kind]=item
        stash(s,old)
        s['pity']=0
        return f"Auto-equipped {item['name']} ({rarity})"
    if stash(s,item):
        s['pity']+=1
        return f"Stored {item['name']} ({rarity}) in inventory"
    s['materials']+=2 if rarity in ('Epic','Legendary') else 1
    s['pity']+=1
    return f"Inventory full; dismantled {item['name']} (+materials)"

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
    s['xp_total']=s.get('xp_total',0)+amount
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
    if target%CHECKPOINT_STEP==0 and target%50!=0 and target>int(s.get('checkpoint_cleared',0)):
        s['checkpoint']={'floor':target,'stage':0}
        return f'Checkpoint Floor {target} waiting — complete the trial from Dungeon'
    if target%50==0:
        s['boss']={'floor':target,'hp':round(140+target*1.6),'max_hp':round(140+target*1.6),
                   'turn':0,'guard':False,'second_wind':False,'cooldown':0}
        return 'Legendary boss waiting — fight it using the Boss button'
    # Smart farming: do not blindly spend battles on unwinnable floors.
    odds=combat_odds(s,target)
    farming=s['farming'] or (odds<0.61 and s['retry_streak']>=2)
    if farming:
        s['farming']=True;s['farming_steps']+=1;s['farm']+=1
        s['gold']+=round((16+s['floor']*0.9)*treasure_multiplier(s))
        s['materials']+=1+(s['floor']//150)
        add_xp(s,2+s['floor']//45)
        s['hp']=min(max_hp(s),s['hp']+max(1,max_hp(s)//20))
        # Blacksmith upgrades are now a player decision.
        if s['farming_steps']>=5:
            s['farming_steps']=0;s['farming']=False;s['retry_streak']=0
        return 'Farmed resources'
    if rng.random()<odds:
        s['floor']=target;s['wins']+=1;s['retry_streak']=0
        if target>=s.get('chamber_next',12):
            s['chamber_next']=target+rng.randint(10,15)
            if len(s.setdefault('chambers',[]))<3:
                s['chambers'].append({'floor':target,'kind':rng.choice(['doors','relic','guardian']),'id':f'{target}-{rng.randrange(1000000)}'})
        if target>=s.get('portal_next',25):
            s['portal_next']=target+rng.randint(24,34)
            if len(s.setdefault('portals',[]))<2:
                s['portals'].append({'floor':target,'id':f'{target}-{rng.randrange(1000000)}'})
        s['gold']+=round((20+target*0.85)*treasure_multiplier(s));s['materials']+=rng.randint(0,2)
        add_xp(s,4+target//32)
        s['hp']=min(max_hp(s),s['hp']+max(1,max_hp(s)//20)+int(max_hp(s)*enchant_bonus(s,'lifesteal')))
        if rng.random()<0.055:drop_item(s,rng)
        loot=milestone_loot(s,rng)
        if target%10==0 and target%50!=0:s['gold']+=target*2
        # Blacksmith upgrades are now a player decision.
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
    if count<=0:return 'No new battles yet (45 seconds per battle).'
    processed=0;last=''
    for _ in range(count):
        if s['boss'] or s.get('checkpoint'):break
        last=_one_battle(s,rng);processed+=1
    # Bank unused idle time behind a manual checkpoint (up to the offline cap).
    # This lets casual players clear several waiting gates in one session.
    # Legendary bosses still consume remaining time to prevent boss farming.
    s['last_tick']=now-(effective-processed*BATTLE_SECONDS) if s.get('checkpoint') else now-(effective-count*BATTLE_SECONDS) if not s['boss'] else now
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
        ensure_gear(s)
        start,end=event_window(db,now)
        if start is not None and s.get('last_tick', now)<start:
            s['last_tick']=start
        if start is not None and now<start:msg='Event has not started.'
        elif end is not None and now>=end:
            # Stop progress at event end; never count later time.
            msg=progress(s,min(end,now)) if s['last_tick']<end else 'Event finished.'
        else:msg=progress(s,now)
        save_player(db,uid,username,s);db.execute('COMMIT');return s,msg
    except Exception:
        db.execute('ROLLBACK');raise

QUEST_TARGETS = {'bounty':1,'arena':2,'chamber':1}
QUEST_NAMES = {'bounty':'📜 Claim the Daily Bounty','arena':'🏟️ Enter 2 Arena Trials','chamber':'🏰 Complete a Mystery Chamber'}
WHEEL_COOLDOWN = 6 * 3600

def quest_status(s, start, now):
    day=int((now-start)//86400) if start is not None else 0
    progress=s.get('quest_progress',{}) if s.get('quest_day',-1)==day else {}
    return day,progress

def quest_record(s, start, now, kind):
    day,progress=quest_status(s,start,now)
    if s.get('quest_day')!=day:
        s['quest_day']=day;s['quest_progress']={};s['quest_claimed']=False
    s['quest_progress'][kind]=min(QUEST_TARGETS[kind],s['quest_progress'].get(kind,0)+1)

def wheel_remaining(s,now):
    return max(0,int(math.ceil(float(s.get('wheel_last',0))+WHEEL_COOLDOWN-now)))

GOBLIN_SECONDS = 6 * 3600
GOBLIN_CLUES = [
    ('I have pages but no voice. What am I?', ['A book', 'A sword', 'A candle'], 0),
    ('I grow smaller as I give light. What am I?', ['A shield', 'A candle', 'A key'], 1),
    ('I open locks but have no hands. What am I?', ['A crown', 'A coin', 'A key'], 2),
    ('I show your face but never speak. What am I?', ['A mirror', 'A map', 'A bell'], 0),
    ('I point north without taking a step. What am I?', ['A lantern', 'A compass', 'A helmet'], 1),
    ('I ring without a mouth. What am I?', ['A book', 'A boot', 'A bell'], 2),
]

def goblin_status(s, start, now):
    # Personal encounter per six-hour EVENT window. No climbing-speed advantage.
    slot=max(0,int((now-start)//GOBLIN_SECONDS)) if start is not None else 0
    # Event window starts at first player registration, so all players share slots.
    active=s.get('goblin_slot',-1)==slot
    attempts=s.get('goblin_attempts',0) if active else 0
    claimed=s.get('goblin_claimed',False) if active else False
    return slot, attempts, claimed, GOBLIN_CLUES[slot%len(GOBLIN_CLUES)]

def mutate(db,uid,username,action,now=None):
    now=utcnow() if now is None else now
    db.execute('BEGIN IMMEDIATE')
    try:
        s=get_player(db,uid)
        if not s:raise ValueError('Use /play first.')
        ensure_gear(s)
        start,end=event_window(db,now)
        if start is not None and now<start:raise ValueError('Event has not started.')
        if end is not None and now>=end:raise ValueError('Event finished; leaderboard is frozen.')
        if start is not None and s.get('last_tick', now)<start:
            s['last_tick']=start
        progress(s,now)
        recharge_expeditions(s,now)
        if action.startswith('build_'):
            style=action[6:]
            if style not in BUILD_STYLES:raise ValueError('Unknown build style.')
            s['build']=style
            msg=f'🧙 Combat stance set to {BUILD_STYLES[style][0]}. This affects both idle and active combat.'
        elif action=='expedition_start':
            if s.get('expedition'):raise ValueError('Finish your current expedition first.')
            if s.get('expedition_charges',0)<1:raise ValueError('No expedition charges. One recharges every two hours (max 3).')
            s['expedition_charges']-=1
            s['expedition']={'stage':1,'hp':100,'gold':0,'materials':0,'xp':0,'wins':0,'history':[]}
            msg='⚔️ Expedition started! Five rooms await. Choose Fight, Scout or Rest.'
        elif action.startswith('expedition_'):
            move=action[11:];ex=s.get('expedition')
            if not ex:raise ValueError('Start an expedition first.')
            if move=='leave':
                s['expedition']=None;msg='🏕️ Expedition abandoned. Unclaimed rewards lost; your normal climb is safe.'
            elif move in ('fight','scout','rest'):
                if ex['stage']>5:raise ValueError('Expedition already complete.')
                stage=ex['stage'];rng=random.Random()
                if move=='fight':
                    odds=max(.42,min(.88,combat_odds(s,s['floor']+stage*3)+.13))
                    if rng.random()<odds:
                        ex['gold']+=115+stage*40+s['floor']//3;ex['materials']+=2+stage
                        ex['xp']+=35+stage*13;ex['wins']+=1
                        result=f'⚔️ Room {stage}: Enemy defeated!'
                    else:
                        ex['hp']-=24+stage*6;result=f'💥 Room {stage}: You took {24+stage*6} expedition HP damage.'
                elif move=='scout':
                    ex['gold']+=65+stage*20;ex['materials']+=2
                    ex['xp']+=12+stage*4;result=f'🔎 Room {stage}: Found a hidden supply cache.'
                else:
                    ex['hp']=min(100,ex['hp']+35);ex['xp']+=5
                    result=f'🏕️ Room {stage}: Recovered expedition HP.'
                ex['history'].append(result);ex['stage']+=1
                if ex['hp']<=0:
                    s['expedition']=None;msg=result+' 💀 Expedition failed. Normal floors and inventory are safe.'
                elif ex['stage']>5:
                    s['gold']+=ex['gold'];s['materials']+=ex['materials'];add_xp(s,ex['xp'])
                    msg=result+f' 🏆 Expedition complete! +{ex["gold"]:,} gold, +{ex["materials"]} materials, +{ex["xp"]} XP.'
                    s['expedition']=None
                else:msg=result+f' Next: room {ex["stage"]}/5 · HP {ex["hp"]}/100.'
            else:raise ValueError('Unknown expedition action.')
        elif action.startswith('checkpoint_'):
            move=action[11:];gate=s.get('checkpoint')
            if not gate:raise ValueError('No checkpoint is waiting.')
            if move not in ('attack','guard','focus'):raise ValueError('Unknown trial action.')
            required=('guard','focus','attack')
            expected=required[gate['stage']]
            if move!=expected:
                msg=f'⚠️ Trial stage {gate["stage"]+1}/3: Wrong approach. Read the clue and try again.'
            else:
                gate['stage']+=1
                if gate['stage']>=3:
                    s['checkpoint_cleared']=max(s.get('checkpoint_cleared',0),gate['floor'])
                    s['checkpoint']=None
                    reward=50+gate['floor']//3;add_xp(s,reward)
                    msg=f'🏰 Checkpoint Floor {gate["floor"]} cleared! +{reward} XP. Idle climbing resumes.'
                else:msg=f'✅ Trial stage passed! Stage {gate["stage"]+1}/3 is ready.'
        elif action.startswith('portal_'):
            choice=action[7:]
            if choice=='enter':
                if s.get('portal_active'):raise ValueError('Finish your current portal first.')
                if not s.get('portals'):raise ValueError('No Abyss Portal waiting. Keep climbing!')
                p=s['portals'].pop(0)
                s['portal_dm_count']=min(s.get('portal_dm_count',0),len(s['portals']))
                s['portal_active']={'floor':p['floor'],'stage':1,'gold':0,'materials':0,'path':None}
                msg='🌀 Entered the Abyss Portal! Choose Blood, Golden or Mystic to begin stage 1/3.'
            elif choice in ('blood','golden','mystic'):
                p=s.get('portal_active')
                if not p:raise ValueError('Enter a waiting portal first.')
                if p['stage']>3:raise ValueError('Portal already complete.')
                if choice=='blood':
                    odds=max(.35,min(.85,combat_odds(s,p['floor']+5)+.10))
                    if random.random()>odds:
                        s['portal_active']=None
                        msg='💀 Blood Portal guardian defeated you. Your normal progress and equipment are safe; this portal is lost.'
                    else:
                        xp=25+p['floor']//8;add_xp(s,xp)
                        p['gold']+=110+p['floor'];p['materials']+=3
                        msg=f'🔴 Blood guardian defeated! +{xp} XP; loot secured for stage {p["stage"]}.'
                elif choice=='golden':
                    p['gold']+=180+p['floor']*2;p['materials']+=1
                    msg='🟡 Golden cache discovered! Loot added to your portal haul.'
                else:
                    p['gold']+=85+p['floor'];p['materials']+=5
                    msg='🔵 Mystic runes solved! Gold and materials added to your haul.'
                if s.get('portal_active'):
                    p['stage']+=1
                    if p['stage']>3:
                        s['gold']+=p['gold'];s['materials']+=p['materials']
                        if random.random()<.20 and len(s.get('relics',[]))<12:
                            available=[k for k in RELIC_TYPES if k not in s.get('relics',[])]
                            if available:
                                relic=random.choice(available);s.setdefault('relics',[]).append(relic)
                                msg+=f' 💍 Relic found: {RELIC_TYPES[relic][0]}!'
                        msg+=f' 🏆 Portal cleared! +{p["gold"]:,} gold and +{p["materials"]} materials.'
                        s['portal_active']=None
                    else:msg+=f' Choose a path for stage {p["stage"]}/3.'
            elif choice=='leave':
                if not s.get('portal_active'):raise ValueError('No active portal.')
                s['portal_active']=None
                msg='🌀 Left the portal. Unclaimed portal loot was forfeited; dungeon progress is safe.'
            else:raise ValueError('Unknown portal action.')
        elif action.startswith('camp_'):
            kind=action[5:]
            if kind not in ('attack','defence','gold','rest'):raise ValueError('Unknown camp action.')
            if kind=='rest':
                cost=150+s['floor']//2
                if s['gold']<cost:raise ValueError(f'Need {cost:,} gold to rest.')
                s['gold']-=cost;s['hp']=max_hp(s)
                msg=f'🏕️ Rested at camp: HP fully restored for {cost:,} gold.'
            else:
                cost=350+s['floor'];mat=5
                if s['gold']<cost or s['materials']<mat:raise ValueError(f'Need {cost:,} gold and {mat} materials.')
                s['gold']-=cost;s['materials']-=mat
                s['camp_buff']=kind;s['camp_until']=now+3600
                msg=f'🏕️ Prepared {kind.title()} buff: +8% for 60 minutes (replaces previous camp buff).'
        elif action.startswith('relic_'):
            key=action[6:]
            if key=='unequip':s['equipped_relic']=None;msg='💍 Relic unequipped.'
            elif key in RELIC_TYPES and key in s.get('relics',[]):
                s['equipped_relic']=key;msg=f'💍 Equipped {RELIC_TYPES[key][0]}.'
            else:raise ValueError('You have not collected that relic yet.')
        elif action=='gear_auto':
            s['auto_equip']=not s['auto_equip']
            msg=f"🎒 Auto-equip {'ON' if s['auto_equip'] else 'OFF'}."
        elif action.startswith('gear_equip_') or action.startswith('gear_lock_') or action.startswith('gear_scrap_'):
            parts=action.split('_',2)
            if len(parts)!=3:raise ValueError('Select an inventory item first.')
            operation,item_id=parts[1],parts[2]
            item=next((x for x in s['inventory'] if x['id']==item_id),None)
            if not item:raise ValueError('That item is no longer in your inventory. Refresh the menu.')
            if operation=='equip':
                name=item['name'];equip_from_bag(s,item)
                msg=f'⚔️ Equipped {name}. Your slot upgrades and enchantment remain active.'
            elif operation=='lock':
                item['locked']=not item.get('locked',False)
                msg=f"🔒 {item['name']} {'locked' if item['locked'] else 'unlocked'}."
            elif operation=='scrap':
                if item.get('locked'):raise ValueError('Unlock the item before dismantling it.')
                reward=2 if item['rarity'] in ('Epic','Legendary') else 1
                s['inventory'].remove(item);s['materials']+=reward
                msg=f"♻️ Dismantled {item['name']} for +{reward} materials."
            else:raise ValueError('Unknown inventory action.')
        elif action.startswith('gear_enchant_'):
            kind=action[len('gear_enchant_'):]
            if kind not in ENCHANTMENTS:raise ValueError('Unknown enchantment.')
            if s.get('enchantment')==kind:raise ValueError('That enchantment is already active.')
            gold,materials=1200,15
            if s['gold']<gold or s['materials']<materials:raise ValueError(f'Need {gold:,} gold and {materials} materials.')
            s['gold']-=gold;s['materials']-=materials;s['enchantment']=kind
            msg=f'✨ {ENCHANTMENTS[kind]} enchanted! This bonus stays with your hero through all equipment changes.'
        elif action.startswith('goblin_'):
            slot,attempts,claimed,clue=goblin_status(s,start,now)
            if claimed:raise ValueError('You already caught this goblin. A new one arrives in the next six-hour window.')
            if attempts>=2:raise ValueError('The goblin escaped! Another appears next six-hour window.')
            try: choice=int(action.split('_')[1])
            except (ValueError,IndexError):raise ValueError('Choose one of the three answers.')
            if choice not in (0,1,2):raise ValueError('Choose one of the three answers.')
            s['goblin_slot']=slot;s['goblin_attempts']=attempts+1
            if choice==clue[2]:
                s['goblin_claimed']=True
                gold=250+min(s['floor'],200)*2
                materials=6+min(s['floor']//50,4)
                s['gold']+=gold;s['materials']+=materials
                msg=f'👹 Goblin caught! +{gold:,} gold and +{materials} materials. 🪙 New balance: {s["gold"]:,} gold.'
            elif attempts+1>=2:
                msg='👹 Wrong answer! The Treasure Goblin escaped. Another appears in the next six-hour window.'
            else:msg='👹 Not quite! You have one attempt left. Read the clue and try again.'
        elif action=='upgrade_weapon' or action=='upgrade_armour':
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
            msg=f'📜 Daily Bounty claimed! +{400+s["floor"]*2:,} gold and +12 materials. 🪙 Balance: {s["gold"]:,} gold.'
            quest_record(s,start,now,'bounty')
        elif action=='wheel':
            remaining=wheel_remaining(s,now)
            if remaining:raise ValueError(f'Wheel available in {remaining//3600}h {(remaining%3600)//60}m.')
            # Reward is rolled on the server; each spin is recorded before saving.
            outcome=random.choices(['gold','materials','key','bonus_gold','gear'],weights=[45,30,10,12,3],k=1)[0]
            if outcome=='gold':
                reward=200+s['floor']*2;s['gold']+=reward;msg=f'🎡 Wheel: 🪙 +{reward:,} gold! Balance: {s["gold"]:,}.'
            elif outcome=='materials':
                reward=8+s['floor']//30;s['materials']+=reward;msg=f'🎡 Wheel: 🧱 +{reward} materials!'
            elif outcome=='key':
                s['keys']+=1;msg='🎡 Wheel: 🗝️ +1 Vault Key!'
            elif outcome=='bonus_gold':
                reward=500+s['floor']*4;s['gold']+=reward;msg=f'🎡 JACKPOT! 🪙 +{reward:,} gold! Balance: {s["gold"]:,}.'
            else:
                msg='🎡 LEGENDARY SPIN! 🎁 '+drop_item(s,random.Random(),True)
            s['wheel_last']=now;s['wheel_spins']=s.get('wheel_spins',0)+1
        elif action=='quest_claim':
            day,qp=quest_status(s,start,now)
            if s.get('quest_claimed',False) and s.get('quest_day')==day:raise ValueError('Today’s quest chest has already been claimed.')
            if not all(qp.get(k,0)>=target for k,target in QUEST_TARGETS.items()):raise ValueError('Complete all 3 daily quests before claiming your chest.')
            gold=650+s['floor']*3;materials=18+s['floor']//40
            s['gold']+=gold;s['materials']+=materials;s['quest_claimed']=True
            msg=f'📜 Quest Board complete! 🎁 +{gold:,} gold and +{materials} materials. 🪙 Balance: {s["gold"]:,} gold.'
        elif action.startswith('chamber_'):
            chambers=s.setdefault('chambers',[])
            if not chambers:raise ValueError('No Mystery Chambers waiting. Keep climbing!')
            choice=action.split('_',1)[1]
            chamber=chambers[0];kind=chamber['kind'];f=chamber['floor']
            allowed={'doors':('gold','crimson','mystic'),'relic':('study','claim','leave'),'guardian':('attack','guard','retreat')}[kind]
            if choice not in allowed:raise ValueError('That choice is not available in this chamber.')
            rng=random.Random()
            if kind=='doors':
                if choice=='gold':
                    gold=120+f*2+rng.randint(0,80);mat=3+f//45
                    s['gold']+=gold;s['materials']+=mat
                    msg=f'🟡 Golden Door: +{gold:,} gold and +{mat} materials!'
                elif choice=='crimson':
                    win=rng.random()<max(.4,min(.85,combat_odds(s,f+3)+.1))
                    if win:
                        gold=220+f*3;s['gold']+=gold;s['materials']+=8
                        msg=f'🔴 Guardian defeated! +{gold:,} gold and +8 materials!'
                    else:
                        s['gold']+=75;msg='🔴 Guardian escaped! You recovered 75 gold.'
                else:
                    if rng.random()<.7:
                        gold=200+f*2;s['gold']+=gold
                        msg=f'🔵 Mystic blessing! +{gold:,} gold.'
                    else:
                        s['materials']+=6;msg='🔵 Strange magic! +6 materials.'
            elif kind=='relic':
                if choice=='study':
                    s['materials']+=9;msg='📜 You deciphered the runes: +9 materials!'
                elif choice=='claim':
                    gold=160+f*3;s['gold']+=gold;msg=f'💎 Claimed the relic: +{gold:,} gold!'
                else:
                    s['hp']=min(max_hp(s),s['hp']+max_hp(s)//4);msg='🕊️ Left peacefully and restored 25% HP.'
            else:
                if choice=='attack':
                    win=rng.random()<max(.35,min(.9,combat_odds(s,f+2)+.12))
                    if win:
                        gold=260+f*3;s['gold']+=gold;s['materials']+=10
                        msg=f'⚔️ Guardian vanquished! +{gold:,} gold, +10 materials!'
                    else:
                        s['gold']+=80;msg='⚔️ The guardian resisted. You escaped with 80 gold.'
                elif choice=='guard':
                    s['materials']+=7;s['hp']=min(max_hp(s),s['hp']+max_hp(s)//10)
                    msg='🛡️ You outlasted the guardian: +7 materials and recovered HP!'
                else:
                    s['gold']+=100;msg='🏃 You withdrew safely with 100 gold.'
            chambers.pop(0)
            quest_record(s,start,now,'chamber')
            s['chamber_notice_count']=min(s.get('chamber_notice_count',0),len(chambers))
            msg+=f' • 🏰 {len(chambers)} chamber(s) remaining.'
        elif action.startswith('skill_'):
            branch=action[6:]
            if branch=='reset':
                s['skill_alloc']={'warrior':0,'defender':0,'treasure':0}
                msg='🌳 Skill Tree reset for free. Reassign your earned points!'
            elif branch in ('warrior','defender','treasure'):
                if skill_points(s)<1:raise ValueError('No skill points available. Earn 1 every 5 hero levels.')
                alloc=s.setdefault('skill_alloc',{'warrior':0,'defender':0,'treasure':0})
                alloc[branch]=alloc.get(branch,0)+1
                msg=f'🌳 +1 {branch.title()} skill! {skill_points(s)} point(s) remaining.'
            else:raise ValueError('Unknown skill branch.')
        elif action.startswith('pet_') and action!='pet_upgrade':
            pet=action[4:]
            pets=s.setdefault('companions',{})
            if pet not in ('wolf','bear','owl','dragon'):raise ValueError('Unknown companion.')
            if pet not in pets:
                cost=1200 if pet!='dragon' else 2200
                mats=15 if pet!='dragon' else 30
                if s['gold']<cost or s['materials']<mats:raise ValueError(f'Unlock costs {cost:,} gold and {mats} materials.')
                s['gold']-=cost;s['materials']-=mats;pets[pet]=1
                s['active_companion']=pet
                msg=f'🐾 Unlocked {pet.title()} Lv1 and equipped it!'
            else:
                s['active_companion']=pet
                msg=f'🐾 Equipped {pet.title()} Lv{pets[pet]}.'
        elif action=='pet_upgrade':
            pet=s.get('active_companion')
            if not pet:raise ValueError('Unlock and equip a companion first.')
            level=s['companions'][pet]
            if level>=8:raise ValueError('Companion is at max level 8.')
            gold=450*level;mat=8*level
            if s['gold']<gold or s['materials']<mat:raise ValueError(f'Need {gold:,} gold and {mat} materials.')
            s['gold']-=gold;s['materials']-=mat;s['companions'][pet]+=1
            msg=f'🐾 {pet.title()} upgraded to Lv{s["companions"][pet]}!'
        elif action.startswith('arena_'):
            difficulty=action[6:]
            if difficulty not in ('easy','hard','nightmare'):raise ValueError('Unknown Arena difficulty.')
            day=int((now-start)//86400)
            if s.get('arena_day')!=day:s['arena_day']=day;s['arena_tries']=0
            if s['arena_tries']>=3:raise ValueError('You have used all 3 Arena attempts today.')
            s['arena_tries']+=1
            quest_record(s,start,now,'arena')
            mods={'easy':(-8,.85,250,6),'hard':(8,.65,500,12),'nightmare':(22,.48,850,20)}
            offset,cap,gold,mat=mods[difficulty]
            odds=max(.15,min(.92,combat_odds(s,max(1,s['floor']+offset))*.75+cap*.25))
            if random.random()<odds:
                reward=gold+s['floor']*(2 if difficulty=='easy' else 3 if difficulty=='hard' else 4)
                s['gold']+=reward;s['materials']+=mat;s['arena_wins']=s.get('arena_wins',0)+1
                msg=f'🏟️ {difficulty.title()} Arena victory! +{reward:,} gold, +{mat} materials. Attempts left: {3-s["arena_tries"]}.'
            else:
                consolation=80+s['floor'];s['gold']+=consolation
                msg=f'🏟️ {difficulty.title()} Arena defeat. +{consolation:,} consolation gold. Attempts left: {3-s["arena_tries"]}.'
        elif action.startswith('merchant_'):
            item=action[9:]
            slot=int(now//21600)
            bought=s.setdefault('merchant_buys',{})
            key=f'{slot}:{item}'
            if key in bought:raise ValueError('You already bought this offer. New stock every 6 hours.')
            if item=='materials':
                cost=650+s['floor']*2
                if s['gold']<cost:raise ValueError(f'Need {cost:,} gold.')
                s['gold']-=cost;amount=20+s['floor']//25;s['materials']+=amount
                msg=f'🧙 Bought {amount} materials for {cost:,} gold.'
            elif item=='key':
                cost=1400+s['floor']*3
                if s['gold']<cost:raise ValueError(f'Need {cost:,} gold.')
                s['gold']-=cost;s['keys']+=1
                msg=f'🧙 Bought 1 Vault Key for {cost:,} gold.'
            elif item=='gear':
                cost=1800+s['floor']*5
                if s['gold']<cost:raise ValueError(f'Need {cost:,} gold.')
                s['gold']-=cost
                msg=f'🧙 Bought equipment for {cost:,} gold. '+drop_item(s,random.Random(),True)
            else:raise ValueError('Unknown merchant offer.')
            s['merchant_buys']={k:v for k,v in bought.items() if k.startswith(f'{slot}:')}
            s['merchant_buys'][key]=True
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
            intent=boss_intent(b)
            b['turn']+=1
            if move=='heal':
                s['hp']=min(max_hp(s),s['hp']+int(max_hp(s)*.35));b['second_wind']=True
                dealt=0
            elif move=='guard':dealt=round(attack_power(s)*.25)
            else:
                dealt=round(attack_power(s)*(1.75 if move=='power' else 1.0)*(1+s['boss_mercy']*.05+min(.25,companion_bonus(s,'boss')*.035)+enchant_bonus(s,'boss')+gear_perk(s,'boss'))*random.uniform(.85,1.15))
            if intent=='feint' and move=='power':dealt=round(dealt*1.25)
            if intent=='heavy' and move=='guard':dealt=round(dealt*1.5)
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
                incoming=round((12+b['floor']*.11)*(1.75 if intent=='heavy' else .65 if intent=='feint' else 1.0))
                if move=='guard':incoming=round(incoming*(.18 if intent=='heavy' else .75 if intent=='feint' else .35))
                incoming=max(1,round(incoming*(1-min(.6,defense_power(s)/(enemy_power(b['floor'])*2)))))
                s['hp']-=incoming
                if s['hp']<=0 or b['turn']>=6:
                    s['boss_mercy']=min(4,s['boss_mercy']+1)
                    s['hp']=max_hp(s);s['boss']=None
                    s['gold']+=100+s['floor'];s['materials']+=5
                    msg=f'Boss escaped. Mercy bonus now +{s["boss_mercy"]*5}% damage. Farm and retry.'
                    # Boss gate will respawn on next tick.
                else:
                    msg=f'{move.title()} vs {intent.upper()}: dealt {dealt}, took {incoming}. Boss HP {max(0,b["hp"]):,}/{b["max_hp"]:,}. Turn {b["turn"]}/6.'
        else:raise ValueError('Unknown action.')
        save_player(db,uid,username,s);db.execute('COMMIT');return s,msg
    except Exception:
        db.execute('ROLLBACK');raise

def leaderboard(db,limit=10):
    rows=[]
    for row in db.execute('SELECT user_id,username,state FROM players'):
        s=json.loads(row['state']);rows.append((row['user_id'],row['username'],s['best'],s['best_at']))
    return sorted(rows,key=lambda r:(-r[2],r[3],r[0]))[:limit]