"""The Golden Vault: one-command, button-driven Discord game."""
import asyncio
import datetime as dt
import json
import itertools
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
RUNE_REVEAL_SECONDS = 3
RUNE_ANSWER_SECONDS = 15  # legacy default; actual duration scales with floor
AUTO_HIDE_TASKS = {}
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


# Curated factual questions are generated locally; no trivia API or network latency.
# Numeric questions remain a small minority of the bank.
def build_question_bank():
    bank = list(QUESTIONS)
    capitals = {
        'France':'Paris','Germany':'Berlin','Italy':'Rome','Spain':'Madrid',
        'Portugal':'Lisbon','Greece':'Athens','Ireland':'Dublin','Norway':'Oslo',
        'Sweden':'Stockholm','Finland':'Helsinki','Denmark':'Copenhagen',
        'Poland':'Warsaw','Austria':'Vienna','Hungary':'Budapest',
        'Czechia':'Prague','Belgium':'Brussels','Netherlands':'Amsterdam',
        'Switzerland':'Bern','Iceland':'Reykjavik','Croatia':'Zagreb',
        'Romania':'Bucharest','Bulgaria':'Sofia','Serbia':'Belgrade',
        'Ukraine':'Kyiv','Estonia':'Tallinn','Latvia':'Riga',
        'Lithuania':'Vilnius','Slovakia':'Bratislava','Slovenia':'Ljubljana',
        'Japan':'Tokyo','China':'Beijing','South Korea':'Seoul',
        'Thailand':'Bangkok','Vietnam':'Hanoi','Philippines':'Manila',
        'Indonesia':'Jakarta','Malaysia':'Kuala Lumpur','Singapore':'Singapore',
        'India':'New Delhi','Pakistan':'Islamabad','Nepal':'Kathmandu',
        'Bangladesh':'Dhaka','Mongolia':'Ulaanbaatar','Turkey':'Ankara',
        'Egypt':'Cairo','Morocco':'Rabat','Kenya':'Nairobi',
        'Ethiopia':'Addis Ababa','Nigeria':'Abuja','Ghana':'Accra',
        'Senegal':'Dakar','Uganda':'Kampala','Rwanda':'Kigali',
        'Canada':'Ottawa','United States':'Washington, D.C.',
        'Mexico':'Mexico City','Cuba':'Havana','Jamaica':'Kingston',
        'Costa Rica':'San José','Panama':'Panama City',
        'Colombia':'Bogotá','Peru':'Lima','Chile':'Santiago',
        'Argentina':'Buenos Aires','Uruguay':'Montevideo',
        'Paraguay':'Asunción','Ecuador':'Quito','Brazil':'Brasília',
        'Australia':'Canberra','New Zealand':'Wellington','Fiji':'Suva',
    }
    countries=list(capitals)
    cities=list(capitals.values())
    rng=random.Random(81462)
    for country,city in capitals.items():
        wrong=rng.sample([c for c in cities if c!=city],3)
        bank.append((f'What is the capital of {country}?',city,wrong))
        wrong_countries=rng.sample([c for c in countries if c!=country],3)
        bank.append((f'Which country has {city} as its capital?',country,wrong_countries))

    # Curated subject-specific facts, grouped so incorrect answers are plausible.
    topics = {
      'Which scientist is associated with this discovery or theory?': {
        'Theory of evolution by natural selection':'Charles Darwin',
        'Theory of general relativity':'Albert Einstein',
        'Laws of planetary motion':'Johannes Kepler',
        'Discovery of penicillin':'Alexander Fleming',
        'Discovery of radioactivity':'Henri Becquerel',
        'First successful smallpox vaccine':'Edward Jenner',
        'Discovery of the neutron':'James Chadwick',
        'Discovery of the electron':'J. J. Thomson',
        'Heliocentric model of the solar system':'Nicolaus Copernicus',
        'Periodic table of chemical elements':'Dmitri Mendeleev',
        'Principle of buoyancy':'Archimedes',
        'Experiments with pea plant inheritance':'Gregor Mendel',
        'Research on radium and polonium':'Marie Curie',
        'Laws of electromagnetic induction':'Michael Faraday',
        'Early work on computer algorithms':'Ada Lovelace',
      },
      'Who wrote this book?': {
        'Pride and Prejudice':'Jane Austen','1984':'George Orwell',
        'The Hobbit':'J. R. R. Tolkien','Frankenstein':'Mary Shelley',
        'Dracula':'Bram Stoker','Jane Eyre':'Charlotte Brontë',
        'Wuthering Heights':'Emily Brontë','The Great Gatsby':'F. Scott Fitzgerald',
        'Moby-Dick':'Herman Melville','The Odyssey':'Homer',
        'The Divine Comedy':'Dante Alighieri','Don Quixote':'Miguel de Cervantes',
        'The Picture of Dorian Gray':'Oscar Wilde','The Time Machine':'H. G. Wells',
        'Little Women':'Louisa May Alcott','The Metamorphosis':'Franz Kafka',
        'The Stranger':'Albert Camus','War and Peace':'Leo Tolstoy',
        'The Trial':'Franz Kafka','The Handmaid’s Tale':'Margaret Atwood',
      },
      'Which artist painted this work?': {
        'The Starry Night':'Vincent van Gogh','The Persistence of Memory':'Salvador Dalí',
        'The Scream':'Edvard Munch','Girl with a Pearl Earring':'Johannes Vermeer',
        'The Birth of Venus':'Sandro Botticelli','Guernica':'Pablo Picasso',
        'The Night Watch':'Rembrandt','The Kiss':'Gustav Klimt',
        'American Gothic':'Grant Wood','Water Lilies':'Claude Monet',
        'The Great Wave off Kanagawa':'Hokusai','The Son of Man':'René Magritte',
        'A Sunday Afternoon on the Island of La Grande Jatte':'Georges Seurat',
        'The School of Athens':'Raphael','The Last Supper':'Leonardo da Vinci',
      },
      'Which sport uses this term?': {
        'Birdie':'Golf','Love':'Tennis','Home run':'Baseball',
        'Scrum':'Rugby','Hat-trick':'Football','Strike':'Bowling',
        'Checkmate':'Chess','Touchdown':'American football',
        'Slam dunk':'Basketball','Wicket':'Cricket',
        'Ippon':'Judo','Knockout':'Boxing',
      },
      'Which instrument is associated with this measurement?': {
        'Atmospheric pressure':'Barometer','Earthquake vibrations':'Seismometer',
        'Wind speed':'Anemometer','Relative humidity':'Hygrometer',
        'Temperature':'Thermometer','Electric current':'Ammeter',
        'Electric voltage':'Voltmeter','Airborne altitude':'Altimeter',
        'Rainfall':'Rain gauge','Light intensity':'Photometer',
      },
      'Which historical civilisation built or is associated with this site?': {
        'Machu Picchu':'Inca','Chichén Itzá':'Maya',
        'The Colosseum':'Ancient Rome','The Parthenon':'Ancient Greece',
        'The Great Pyramid of Giza':'Ancient Egypt','Persepolis':'Achaemenid Persia',
        'Angkor Wat':'Khmer Empire','The Terracotta Army':'Qin dynasty',
      },
    }
    for template,entries in topics.items():
        pool=list(dict.fromkeys(entries.values()))
        for item,answer in entries.items():
            wrong=rng.sample([v for v in pool if v!=answer],3)
            bank.append((f'{template} {item}',answer,wrong))
    # Keep a small, varied set of arithmetic questions instead of thousands of near duplicates.
    for a,b in [(17,8),(23,7),(14,12),(19,9),(16,11),(27,6),(18,13),
                (21,8),(32,7),(15,14),(24,9),(26,8),(13,17),(28,7)]:
        result=a*b
        bank.append((f'What is {a} × {b}?',str(result),
                     [str(result+b),str(result-b),str(result+a)]))
    unique={}
    for q,answer,wrong in bank:
        if len(set([answer]+wrong))==4:
            unique[q]=(q,answer,wrong)
    return list(unique.values())

QUESTIONS = build_question_bank()

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
# Additive migration: retain existing Railway /data player progress.
if 'ancient_keys' not in {row['name'] for row in conn.execute('PRAGMA table_info(players)')}:
    conn.execute('ALTER TABLE players ADD COLUMN ancient_keys INTEGER NOT NULL DEFAULT 0')

conn.executescript('''
CREATE TABLE IF NOT EXISTS treasury_progress (
 uid INTEGER PRIMARY KEY,
 completed_runs INTEGER NOT NULL DEFAULT 0,
 total_chambers INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS treasury_runs (
 uid INTEGER PRIMARY KEY,
 tier INTEGER NOT NULL,
 room INTEGER NOT NULL,
 max_rooms INTEGER NOT NULL,
 unbanked_gold INTEGER NOT NULL DEFAULT 0
);
''')
TREASURY_RATES = (
    (10,50,35,5),
    (0,40,50,10),
    (0,30,55,15),
    (0,20,60,20),
    (0,10,60,30),
)
FLOOR_RATES = (
    (90,10,0,0),
    (70,25,5,0),
    (45,40,14,1),
    (25,45,27,3),
    (10,35,45,10),
)
KEY_FIELDS = ('bronze','silver','gold_keys','ancient_keys')
KEY_NAMES = ('Bronze','Silver','Gold','Ancient')
TREASURY_NAMES = ('Royal Chambers','Ancient Chambers','Cursed Chambers','Mythic Chambers','Golden Sanctum')
# Each completed tier requires mastery of the previous tier.
TREASURY_UNLOCK_RUNS = (0,3,8,16,28)

def treasury_tier(uid):
    row=conn.execute('SELECT completed_runs FROM treasury_progress WHERE uid=?',(uid,)).fetchone()
    count=row['completed_runs'] if row else 0
    return max(i+1 for i,required in enumerate(TREASURY_UNLOCK_RUNS) if count>=required)

def key_roll(rates):
    return random.choices(range(4),weights=rates,k=1)[0]

def award_key(uid,rates,guaranteed_min=0):
    index=max(guaranteed_min,key_roll(rates))
    field=KEY_FIELDS[index]
    conn.execute(f'UPDATE players SET {field}={field}+1 WHERE uid=?',(uid,))
    return KEY_NAMES[index]

def floor_rates(floor_number):
    return FLOOR_RATES[min(4,max(0,(floor_number-1)//10))]

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
    allowed={'hp','floor','floor_steps','bronze','silver','gold_keys','ancient_keys','gold','score','correct','attempts','shield','regen_upgrade','potions','question_history'}
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


def generate_lock_puzzle(level, royal=False):
    """Generate a deduction lock with exactly one valid combination."""
    names=['Sun','Moon','Gem','Star','Crown']
    glyphs=['☀','☾','◆','✦','♛']
    expert=royal or level>50
    pool=5 if expert else 4
    difficulty='easy' if level<=15 and not expert else 'medium' if level<=35 and not expert else 'expert' if expert else 'hard'
    # All three symbols must differ; that is part of the player-facing instructions.
    universe=list(itertools.permutations(range(pool),3))
    for _ in range(100):
        goal=random.choice(universe)
        predicates=[]
        for a in range(pool):
            predicates.append((f'The {names[a]} is not used.',lambda x,a=a:a not in x))
            for pos in range(3):
                predicates.append((f'The {names[a]} is not in dial {pos+1}.',lambda x,a=a,pos=pos:x[pos]!=a))
                if difficulty=='easy':
                    predicates.append((f'Dial {pos+1} shows the {names[a]}.',lambda x,a=a,pos=pos:x[pos]==a))
            for b in range(pool):
                if a==b:continue
                predicates.append((f'The {names[a]} is somewhere left of the {names[b]}.',lambda x,a=a,b=b:a in x and b in x and x.index(a)<x.index(b)))
                predicates.append((f'The {names[a]} is directly beside the {names[b]}.',lambda x,a=a,b=b:a in x and b in x and abs(x.index(a)-x.index(b))==1))
        random.shuffle(predicates)
        true_clues=[(label,pred) for label,pred in predicates if pred(goal)]
        # Prefer deductions over direct assignments beyond the tutorial tier.
        if difficulty!='easy':true_clues=[v for v in true_clues if not v[0].startswith('Dial ')]
        candidates=universe[:];chosen=[]
        while len(candidates)>1 and len(chosen)<8:
            choices=[]
            for label,pred in true_clues:
                if label in [c[0] for c in chosen]:continue
                filtered=[x for x in candidates if pred(x)]
                if 0<len(filtered)<len(candidates):choices.append((len(filtered),random.random(),label,pred,filtered))
            if not choices:break
            # Choose clues that eliminate possibilities but avoid trivial one-clue solutions.
            choices.sort(key=lambda z:(z[0],z[1]))
            best=choices[0]
            chosen.append((best[2],best[3]));candidates=best[4]
        if len(candidates)!=1:continue
        minimum={'easy':3,'medium':4,'hard':5,'expert':5}[difficulty]
        for label,pred in true_clues:
            if len(chosen)>=minimum:break
            if label not in [c[0] for c in chosen]:chosen.append((label,pred))
        random.shuffle(chosen)
        # Verify the exact displayed clues uniquely determine the goal.
        solutions=[x for x in universe if all(pred(x) for _,pred in chosen)]
        if solutions!=[goal]:continue
        current=[random.randrange(pool) for _ in range(3)]
        if current==list(goal):current[0]=(current[0]+1)%pool
        legend=' · '.join(f'{glyphs[i]} {names[i]}' for i in range(pool))
        clues=('Set **3 different symbols** using the clues below. Each dial has '+str(pool)+' possible symbols.\n\n'
               +'\n'.join(f'**{i+1}.** {label}' for i,(label,_) in enumerate(chosen))
               +'\n\n**Symbols:** '+legend)
        duration={'easy':30,'medium':45,'hard':60,'expert':75}[difficulty]
        return {'goal':list(goal),'current':current,'symbols':glyphs[:pool],
                'clues':clues,'difficulty':difficulty},duration
    raise RuntimeError('Could not generate a unique lock puzzle')

def make_challenge(uid,mode,level=1):
    # All randomness is server-side. No answers appear in custom IDs.
    kinds=['quiz','quiz','quiz','pattern','pattern','memory','lock','path']
    kind=random.choice(kinds)
    payload={}
    if kind=='quiz':
        p=player(uid)
        hist=json.loads(p['question_history'])
        recent=set(hist[-min(500,len(QUESTIONS)-1):])
        candidates=[i for i in range(len(QUESTIONS)) if i not in recent]
        idx=random.choice(candidates or list(range(len(QUESTIONS))))
        q,answer,wrong=QUESTIONS[idx]
        choices=[answer]+wrong
        random.shuffle(choices)
        payload={'question':q,'options':choices,'answer':choices.index(answer),'qid':idx}
        hist.append(idx)
        change(uid,question_history=json.dumps(hist[-500:]))
        duration=10
    elif kind=='pattern':
        difficulty=1 if level<=10 else 2 if level<=30 else 3
        pattern_type=random.choice(['add','multiply','squares','alternate'] if difficulty==1 else ['multiply','squares','alternate','difference','fibonacci'])
        if pattern_type=='add':
            start=random.randint(1,15);step=random.randint(2,9)
            sequence=[start+i*step for i in range(5)]
        elif pattern_type=='multiply':
            start=random.randint(1,4);factor=random.randint(2,3)
            sequence=[start*factor**i for i in range(5)]
        elif pattern_type=='squares':
            offset=random.randint(0,8)
            sequence=[(i+2)**2+offset for i in range(5)]
        elif pattern_type=='alternate':
            start=random.randint(2,14);a=random.randint(2,7);b=random.randint(8,15)
            sequence=[start]
            for i in range(4):sequence.append(sequence[-1]+(a if i%2==0 else b))
        elif pattern_type=='difference':
            start=random.randint(1,20);step=random.randint(2,6)
            sequence=[start]
            for i in range(1,5):sequence.append(sequence[-1]+step*i)
        else:  # Fibonacci-style: each next number is the sum of the previous two.
            sequence=[random.randint(2,8),random.randint(3,11)]
            for i in range(3):sequence.append(sequence[-1]+sequence[-2])
        answer=sequence[-1]
        opts={answer}
        while len(opts)<4:
            candidate=answer+random.choice([-8,-6,-4,-3,-2,-1,1,2,3,4,6,8])
            if candidate>=0:opts.add(candidate)
        choices=list(opts);random.shuffle(choices)
        payload={'question':'Complete the sequence: '+', '.join(map(str,sequence[:-1]))+', ?',
                 'options':list(map(str,choices)),'answer':choices.index(answer),'pattern_type':pattern_type}
        duration=20 if difficulty==1 else 25 if difficulty==2 else 35
    elif kind=='memory':
        runes=['☀','☾','◆','✦','♜','♠','♣','⬟']
        count=5 if level<=10 else 6 if level<=30 else 7
        reveal=4 if count==4 else 5 if count==5 else 6
        answer_seconds=15 if count==4 else 20 if count==5 else 25
        seq=random.sample(runes,count)
        options=[' '.join(seq)]
        while len(options)<4:
            shuffled=seq[:];random.shuffle(shuffled)
            val=' '.join(shuffled)
            if val not in options:options.append(val)
        random.shuffle(options)
        payload={'sequence':' '.join(seq),'options':options,'answer':options.index(' '.join(seq)),
                 'reveal_until':now()+reveal}
        duration=reveal+answer_seconds
    elif kind=='lock':
        payload,duration=generate_lock_puzzle(level,royal=(mode=='treasury' or mode.startswith('royal:')))
    else:
        dirs=['⬆','⬇','⬅','➡']
        count=5 if level<=10 else 6 if level<=30 else 7
        seq=[random.choice(dirs) for _ in range(count)]
        reveal=4
        payload={'sequence':seq,'progress':0,'reveal_until':now()+reveal}
        duration=reveal+(25 if level<=10 else 30 if level<=30 else 35)
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
    e.add_field(name='🗝️ Keys',value=f"Bronze {p['bronze']} · Silver {p['silver']} · Gold {p['gold_keys']} · Ancient {p['ancient_keys']}",inline=False)
    e.add_field(name='🪙 Gold',value=f"{p['gold']:,} · Potions {p['potions']}",inline=False)
    status=(f'Ends <t:{END}:R>' if active() else f'Starts <t:{START}:R>' if now()<START else 'Event finished')
    e.set_footer(text=f'Day {event_day()+1}/{EVENT_DAYS} · {status} · Private player panel')
    return e

RULES='''**🏆 Objective:** Highest Vault Score after seven days wins. Ties: highest floor, then best accuracy.
**🏰 Dungeon:** 50 floors; 2–4 randomly generated challenges per floor. Guardian at every 10th floor. Progress is permanent.
**❤️ Health:** Start with 100 HP; wrong answers and timeouts cost 10 HP. Recover 10 HP every five minutes, including offline. Healing potions restore 25 HP.
**⏱️ Timers:** Trivia 10s; patterns 15–30s; memory 3–5s automatic reveal + 12–20s answer; deduction locks 30–75s; paths 4s automatic reveal + 25s input.
**🗝️ Treasure:** Dungeon keys are randomised and improve with floor progression. Treasury key rarity improves across five tiers; successful chambers have a 40% key chance and full runs guarantee a key. Forge five lower-tier keys into one higher-tier key. Ancient chests award 900 score. Earn keys and gold, open chests and build Vault Score. Chests have fixed score values by tier; no random score jackpots.
**🧭 Expeditions:** Repeatable 3–5-room expeditions. You may bank loot by leaving; if you collapse, lose half the unbanked gold. First three completed expeditions each day award bonus score.
**📅 Daily activities:** Five tasks and one guardian per event day; missed event days can be completed later before the event ends. Royal Treasury unlocks after completing Floor 50 and offers unlimited runs.
**⚖️ Fair play:** Do not use AI, outside answer tools, or share solutions. Randomised challenges and short trivia timers discourage cheating but cannot guarantee prevention.
**🔒 Privacy:** Challenges and menus are shown privately to each player.'''
HELP='''**🏰 Getting started**
Use `/play` to open your private game panel. Navigate with buttons; you do not need any other command. Use **Home** to return to the main menu. If a challenge panel stops working after a bot restart, use `/play` again.

**🎯 Goal and leaderboard**
Earn the most **Vault Score** during the seven-day event. Open **Leaderboard** to see the top 10. Ties are decided by dungeon progress, then answer accuracy. **Gold** is spending currency; it is not the same as Vault Score.

**🏰 Dungeon (50 floors)**
Open **Dungeon** and start the next floor challenge. Clear 2–4 random challenges per floor. Every 10th floor has a guardian. Completed floors are saved permanently. Finish Floor 50 to unlock **Royal Treasury**.

**🧩 Questions and puzzles**
General-knowledge questions have **10 seconds** to answer. Number patterns have **15–30 seconds**. Rune Memory reveals a sequence for **3–5 seconds**, hides it automatically, then gives **12–20 seconds** to reproduce it. Hidden Path hides automatically after **4 seconds**, then gives **25 seconds** for input. Deduction lockpicking has **30 seconds (easy), 45 seconds (medium), 60 seconds (hard), or 75 seconds (Royal Treasury expert)**. Use the clues to set three different symbols, then press Unlock. Each puzzle is randomly generated and checked to have exactly one solution. Later floors feature harder puzzles. Question choices and puzzle sequences are randomised; recently seen trivia is tracked to reduce repeats. Timers continue even if you close Discord.

**❤️ Health and recovery**
You have up to **100 HP**. Wrong answers and timeouts normally cost **10 HP**. Health regenerates by **10 HP every 5 minutes**, including while offline, with workshop upgrades able to improve regeneration. Healing potions restore **25 HP**. At zero HP, wait to recover or use a potion; completed floors are safe.

**🧭 Vault Expeditions**
Enter a random **3–5 chamber** expedition. Win challenges to gather **unbanked gold**. After chambers, choose whether to continue or leave and bank your gold. If you collapse, you lose **half of your unbanked gold**. Expeditions are repeatable without a daily entry limit, but only your **first three completed expeditions per event day** award expedition bonus Vault Score; later runs still earn resources.

**🗝️ Treasure chests and Key Forge**
Find Bronze, Silver, Gold and Ancient keys. Open **Treasure** to exchange keys for guaranteed Vault Score: **2 Bronze → 40**, **2 Silver → 120**, **1 Gold → 300**, **1 Ancient → 900**. In **Key Forge**, convert **5 Bronze → 1 Silver**, **5 Silver → 1 Gold**, or **5 Gold → 1 Ancient**. Forging consumes the keys and awards no score until a chest is opened.

**⚒️ Workshop**
Spend gold on healing potions and upgrades. Shield upgrades reduce damage; regeneration upgrades restore more HP over time.

**📅 Daily Vault and Guardians**
Each event day has **five daily trials** and **one daily guardian**. Successful daily trials award **70 Vault Score** each; the daily guardian awards **150**. Choose an available day to complete missed trials before the event ends.

**👑 Royal Treasury — unlimited runs**
Unlock after completing Floor 50. Run unlimited expeditions of 5–9 chambers across five progressively unlocked tiers. Each successful chamber has a **40% key drop chance**; rarity depends on tier. A fully completed run guarantees an additional key and Vault Score; tiers III–V also grant a Gold-or-better guardian key. You can bank unbanked gold early but forfeit the run-completion rewards. Incorrect answers lose 25% of unbanked Treasury gold and cost health; reaching zero HP ends the run. Tier unlocks require 0, 3, 8, 16 and 28 completed runs.

**🗝️ Dungeon key progression**
Successful dungeon challenges have a **40% chance** to drop a random key. Clearing a floor guarantees a key, with rarity improving every ten floors. Guardian floors guarantee a higher-tier key and may drop an extra key. The Key Forge still converts five lower-tier keys into one higher-tier key.

**📜 Rules and fair play**
Open **Rules** for the full event rules. Do not share answers or use AI/answer tools during challenges. Menus and challenges are private to you.'''

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
            # Acknowledge the button immediately, before database and challenge work.
            await interaction.response.defer()
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
        elif self.page in ('rules','help','leaderboard','workshop','treasure','dungeon','expeditions','daily','royal','guardian','forge'):
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
                self.add('Ancient · 1 key','chest_ancient',disabled=p['ancient_keys']<1 or not active())
                self.add('Key Forge','forge',discord.ButtonStyle.primary,emoji='⚒️')
            if self.page=='forge':
                self.add('5 Bronze → 1 Silver','forge_bronze',disabled=p['bronze']<5 or not active())
                self.add('5 Silver → 1 Gold','forge_silver',disabled=p['silver']<5 or not active())
                self.add('5 Gold → 1 Ancient','forge_gold',disabled=p['gold_keys']<5 or not active())
            if self.page=='daily':
                for i in range(EVENT_DAYS):self.add(f'Day {i+1}',f'day_{i}',disabled=i>event_day() or not active(),row=i//5)
            if self.page=='guardian':self.add('Face Daily Guardian','start_guardian',discord.ButtonStyle.success,disabled=not active() or p['hp']<10)
            if self.page=='royal':
                run=conn.execute('SELECT * FROM treasury_runs WHERE uid=?',(self.uid,)).fetchone()
                if run:
                    self.add('Next Treasury Chamber','treasury_next',discord.ButtonStyle.success,disabled=not active() or p['hp']<10 or bool(session(self.uid)))
                    self.add('Bank & Leave','treasury_bank',discord.ButtonStyle.primary,disabled=bool(session(self.uid)))
                else:
                    self.add('Start Treasury Run','treasury_start',discord.ButtonStyle.success,disabled=not active() or p['floor']<=50 or p['hp']<10)
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
                        self.add(str(opt)[:70],f'answer_{i}',discord.ButtonStyle.primary,row=i//2,disabled=(kind=='memory' and now()<payload.get('reveal_until',0) and not payload.get('hidden')))
                elif kind=='lock':
                    for i in range(3):self.add(f'Rotate Dial {i+1}',f'rotate_{i}',row=0)
                    self.add('Unlock','unlock',discord.ButtonStyle.success,row=1)
                elif kind=='path':
                    for i,sym in enumerate(['⬆','⬇','⬅','➡']):self.add(sym,f'path_{i}',discord.ButtonStyle.primary,row=0,disabled=(now()<payload.get('reveal_until',0) and not payload.get('hidden')))
                # The sequence is hidden automatically; no manual Hide & Start step.
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
        e.add_field(name='Deduction clues',value=data.get('clues','Match the target: '+ ' '.join(syms[i] for i in data['goal'])),inline=False)
        e.add_field(name='Your dials',value=' '.join(syms[i] for i in data['current']),inline=False)
    if kind=='path':
        visible=now()<data['reveal_until'] and not data.get('hidden')
        e.add_field(name='Safe path' if visible else 'Navigate the path',value=' '.join(data['sequence']) if visible else f"Correct steps: {data['progress']}/{len(data['sequence'])}",inline=False)
    return e

async def auto_hide_sequence(interaction,uid,started,reveal_until):
    """Automatically replace the ephemeral reveal with the answer panel."""
    try:
        await asyncio.sleep(max(0, reveal_until-now()))
        current=session(uid)
        if not current or current['started'] != started or current['kind'] not in ('memory','path'):
            return
        payload=json.loads(current['payload'])
        if payload.get('hidden'):
            return
        payload['hidden']=True
        conn.execute('UPDATE sessions SET payload=? WHERE uid=?',(json.dumps(payload),uid))
        await interaction.edit_original_response(embed=challenge_embed(uid),view=UI(uid,'challenge'))
    except asyncio.CancelledError:
        raise
    except discord.HTTPException:
        # A stale/deleted Discord panel must not interrupt game progression.
        pass
    finally:
        task=AUTO_HIDE_TASKS.get(uid)
        if task is asyncio.current_task():
            AUTO_HIDE_TASKS.pop(uid,None)

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
    elif page=='treasure':e=base_embed(uid,'💎 Treasure Chests','Spend keys on guaranteed Vault Score. Bronze: 2 keys → 40 score; Silver: 2 keys → 120 score; Gold: 1 key → 300 score; Ancient: 1 key → 900 score. Use Key Forge to combine keys.')
    elif page=='forge':e=base_embed(uid,'⚒️ Royal Key Forge','Convert 5 Bronze → 1 Silver, 5 Silver → 1 Gold, or 5 Gold → 1 Ancient. Forging consumes the five lower-tier keys. Forging does not award score directly.')
    elif page=='workshop':e=base_embed(uid,'⚒️ Workshop',f"Shield level: **{p['shield']}/3** (reduces damage by 2 per level). Regeneration level: **{p['regen_upgrade']}/3** (+2 HP per five minutes per level).")
    elif page=='daily':e=base_embed(uid,'📅 Daily Vault','Choose any unlocked event day. Missed days remain available until the event closes. Each day offers five trials and a daily guardian.')
    elif page=='day':
        completed=conn.execute('SELECT COUNT(*) n FROM daily WHERE uid=? AND day=? AND task BETWEEN 0 AND 4',(uid,day)).fetchone()['n']
        e=base_embed(uid,f'📅 Day {day+1} Vault Trials',f'Completed: **{completed}/5**. Each trial has a randomised challenge and awards 70 Vault Score on success.')
    elif page=='guardian':e=base_embed(uid,'🐉 Daily Guardian','One guardian challenge per event day, worth 150 Vault Score. Select the day in Daily Vault first to target a previous day.')
    elif page=='royal':
        run=conn.execute('SELECT * FROM treasury_runs WHERE uid=?',(uid,)).fetchone()
        tier=treasury_tier(uid)
        countrow=conn.execute('SELECT completed_runs FROM treasury_progress WHERE uid=?',(uid,)).fetchone()
        runs=countrow['completed_runs'] if countrow else 0
        if p['floor']<=50:
            desc='🔒 Complete all 50 dungeon floors to unlock unlimited Royal Treasury expeditions.'
        else:
            desc=(f'**Current tier:** {tier}/5 — {TREASURY_NAMES[tier-1]}\\n'
                  f'**Completed runs:** {runs}\\n'
                  f'**Key chance per cleared chamber:** 40%\\n'
                  f'**Guaranteed key:** 1 upon completing a run\\n'
                  f'**Key rarity (Bronze / Silver / Gold / Ancient):** {" / ".join(map(str,TREASURY_RATES[tier-1]))}%\\n'
                  f'**Run length:** {5+tier-1} chambers\\n'
                  f'**Next tier:** '+(f'{TREASURY_UNLOCK_RUNS[tier]-runs} more completed runs' if tier<5 else 'Maximum tier reached'))
            if run:
                desc+=f"\\n\\n**Active run:** {run['room']}/{run['max_rooms']} chambers · {run['unbanked_gold']} unbanked gold"
        e=base_embed(uid,'👑 Royal Treasury',desc)
    elif page=='leaderboard':
        leaders=conn.execute('SELECT * FROM players ORDER BY score DESC,floor DESC,(correct*1.0/MAX(attempts,1)) DESC LIMIT 10').fetchall()
        lines=[f"**{i}.** {discord.utils.escape_markdown(r['name'])[:25]} — 💎 **{r['score']:,}** · Floor {min(50,r['floor'])} · {round(100*r['correct']/max(1,r['attempts']))}%" for i,r in enumerate(leaders,1)]
        e=base_embed(uid,'🏆 Leaderboard','\n'.join(lines) if lines else 'No players yet.')
    else:e=base_embed(uid,description='Explore the dungeon, collect keys, open treasure and compete for the highest Vault Score!')
    if note:e.add_field(name='Update',value=note[:1024],inline=False)
    view=UI(uid,page,day)
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=e,view=view)
    else:
        await interaction.response.edit_message(embed=e,view=view)
    if page=='challenge':
        current=session(uid)
        if current and current['kind'] in ('memory','path'):
            payload=json.loads(current['payload'])
            if not payload.get('hidden') and now()<payload.get('reveal_until',0):
                old=AUTO_HIDE_TASKS.get(uid)
                if not old or old.done():
                    AUTO_HIDE_TASKS[uid]=asyncio.create_task(auto_hide_sequence(interaction,uid,current['started'],payload['reveal_until']))

async def complete(uid,success,mode,kind,reason=''):
    p=player(uid)
    clear_session(uid)
    if not success:
        if reason in ('Time expired.','Challenge forfeited.'):
            change(uid,attempts=p['attempts']+1)
        lost=harm(uid,10)
        if mode=='treasury':
            run=conn.execute('SELECT * FROM treasury_runs WHERE uid=?',(uid,)).fetchone()
            if run:
                penalty=run['unbanked_gold']//4
                conn.execute('UPDATE treasury_runs SET unbanked_gold=unbanked_gold-? WHERE uid=?',(penalty,uid))
                reason+=f' Lost {penalty} unbanked Treasury gold.'
                if player(uid)['hp']==0:
                    remaining=run['unbanked_gold']-penalty
                    conn.execute('DELETE FROM treasury_runs WHERE uid=?',(uid,))
                    change(uid,gold=player(uid)['gold']+remaining//2)
                    reason+=f' Treasury run collapsed; recovered {remaining//2} gold.'
        if mode=='exp' and player(uid)['hp']==0:
            ex=conn.execute('SELECT * FROM expedition WHERE uid=?',(uid,)).fetchone()
            if ex:
                conn.execute('DELETE FROM expedition WHERE uid=?',(uid,))
                change(uid,gold=player(uid)['gold']+ex['unbanked']//2)
                reason += f' Expedition collapsed; recovered {ex["unbanked"]//2} of {ex["unbanked"]} unbanked gold.'
        return 'dungeon' if mode=='floor' else 'expeditions' if mode=='exp' else 'day' if mode.startswith('task:') else 'royal' if mode=='treasury' else 'home', f'❌ {reason or "Challenge failed."} Lost {lost} HP.'
    change(uid,correct=p['correct']+1,gold=p['gold']+20)
    if mode=='floor':
        progress=p['floor_steps']+1
        if progress>=steps_required(p['floor']):
            f=p['floor']
            change(uid,floor=f+1,floor_steps=0,score=p['score']+(100 if f%10==0 else 20))
            earned=award_key(uid,floor_rates(f),guaranteed_min=(1 if f%10==0 and f<=20 else 2 if f%10==0 else 0))
            bonus=''
            if f%10==0 and random.random()<0.25:
                bonus=' Bonus key: '+award_key(uid,floor_rates(f))+'.'
            return 'dungeon',f'🏆 Floor {f} cleared! +{100 if f%10==0 else 20} score, {earned} Key.{bonus}'
        change(uid,floor_steps=progress)
        earned=award_key(uid,floor_rates(p['floor'])) if random.random()<0.40 else None
        return 'dungeon',f'✅ Challenge passed! +20 gold'+(f', {earned} Key' if earned else '')+f'. Progress {progress}/{steps_required(p["floor"])}.'
    if mode=='treasury':
        run=conn.execute('SELECT * FROM treasury_runs WHERE uid=?',(uid,)).fetchone()
        if not run:return 'royal','Treasury run is no longer active.'
        tier=run['tier']
        loot=run['unbanked_gold']+random.randint(45,75)*tier
        conn.execute('INSERT INTO treasury_progress(uid,completed_runs,total_chambers) VALUES(?,0,1) ON CONFLICT(uid) DO UPDATE SET total_chambers=total_chambers+1',(uid,))
        drop=award_key(uid,TREASURY_RATES[tier-1]) if random.random()<0.40 else None
        msg=f'💎 Chamber cleared! +{loot-run["unbanked_gold"]} unbanked gold.'
        if drop:msg+=f' Found {drop} Key!'
        if run['room']>=run['max_rooms']:
            guaranteed=award_key(uid,TREASURY_RATES[tier-1])
            guardian=('Gold Key' if tier>=3 else 'Silver Key')
            if tier>=3:
                award_key(uid,TREASURY_RATES[tier-1],guaranteed_min=2)
            conn.execute('DELETE FROM treasury_runs WHERE uid=?',(uid,))
            conn.execute('INSERT INTO treasury_progress(uid,completed_runs,total_chambers) VALUES(?,1,0) ON CONFLICT(uid) DO UPDATE SET completed_runs=completed_runs+1',(uid,))
            current=player(uid)
            score=100*tier
            change(uid,gold=current['gold']+loot,score=current['score']+score)
            msg+=f' 🏆 Run complete! Banked {loot} gold, +{score} Vault Score, guaranteed {guaranteed} Key.'
            if tier>=3:msg+=f' Guardian bonus: {guardian} or better!'
            return 'royal',msg
        conn.execute('UPDATE treasury_runs SET room=room+1,unbanked_gold=? WHERE uid=?',(loot,uid))
        return 'royal',msg+' Continue or bank safely.'
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
    if action in ('home','dungeon','expeditions','daily','treasure','workshop','royal','leaderboard','rules','help','forge'):
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
    if action=='treasury_start':
        if s:await show(interaction,uid,'challenge','Finish your current challenge first.');return
        if p['floor']<=50:await show(interaction,uid,'royal','Complete Floor 50 first.');return
        if p['hp']<10:await show(interaction,uid,'royal','Recover health first.');return
        if conn.execute('SELECT 1 FROM treasury_runs WHERE uid=?',(uid,)).fetchone():
            await show(interaction,uid,'royal','Finish your current run first.');return
        tier=treasury_tier(uid)
        conn.execute('INSERT INTO treasury_runs(uid,tier,room,max_rooms,unbanked_gold) VALUES(?,?,?,?,0)',(uid,tier,1,4+tier))
        await show(interaction,uid,'royal','👑 New Treasury run started!');return
    if action=='treasury_next':
        if s:await show(interaction,uid,'challenge');return
        run=conn.execute('SELECT * FROM treasury_runs WHERE uid=?',(uid,)).fetchone()
        if not run:await show(interaction,uid,'royal','Start a Treasury run first.');return
        if p['hp']<10:await show(interaction,uid,'royal','Recover health first.');return
        make_challenge(uid,'treasury',51+run['tier']*10)
        await show(interaction,uid,'challenge');return
    if action=='treasury_bank':
        if s:await show(interaction,uid,'challenge','Finish the current challenge first.');return
        run=conn.execute('SELECT * FROM treasury_runs WHERE uid=?',(uid,)).fetchone()
        if not run:await show(interaction,uid,'royal','No active run.');return
        conn.execute('DELETE FROM treasury_runs WHERE uid=?',(uid,))
        change(uid,gold=p['gold']+run['unbanked_gold'])
        await show(interaction,uid,'royal',f'🏦 Banked {run["unbanked_gold"]} gold. No completion key or score awarded.');return
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
    if action.startswith('forge_'):
        tier=action.split('_',1)[1]
        recipes={'bronze':('bronze','silver'),'silver':('silver','gold_keys'),'gold':('gold_keys','ancient_keys')}
        if tier not in recipes:await show(interaction,uid,'forge','Unknown recipe.');return
        source,target=recipes[tier]
        # Atomic conditional update prevents concurrent button presses duplicating keys.
        with conn:
            updated=conn.execute(f'UPDATE players SET {source}={source}-5, {target}={target}+1 WHERE uid=? AND {source}>=5',(uid,)).rowcount
        await show(interaction,uid,'forge','⚒️ Forged one higher-tier key!' if updated else 'You need five keys of the required tier.');return
    if action.startswith('chest_'):
        tier=action.split('_')[1]
        field,cost,points={'bronze':('bronze',2,40),'silver':('silver',2,120),'gold':('gold_keys',1,300),'ancient':('ancient_keys',1,900)}[tier]
        with conn:
            updated=conn.execute(f'UPDATE players SET {field}={field}-?, score=score+? WHERE uid=? AND {field}>=?',(cost,points,uid,cost)).rowcount
        if not updated:await show(interaction,uid,'treasure','Not enough keys.');return
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
            await show(interaction,uid,'challenge','Wait for the sequence to hide automatically.');return
        index=int(action.split('_')[1]);correct=index==payload['answer']
        change(uid,attempts=p['attempts']+1)
        page,msg=await complete(uid,correct,mode,kind,'Wrong answer.')
        await show(interaction,uid,page,msg,day=int(mode.split(':')[1]) if ':' in mode else day);return
    if kind=='lock' and action.startswith('rotate_'):
        i=int(action.split('_')[1]);payload['current'][i]=(payload['current'][i]+1)%len(payload['symbols'])
        conn.execute('UPDATE sessions SET payload=? WHERE uid=?',(json.dumps(payload),uid))
        await show(interaction,uid,'challenge');return
    if kind=='lock' and action=='unlock':
        change(uid,attempts=p['attempts']+1)
        page,msg=await complete(uid,payload['current']==payload['goal'],mode,kind,'The runes did not match.')
        await show(interaction,uid,page,msg,day=int(mode.split(':')[1]) if ':' in mode else day);return
    if kind=='path' and action.startswith('path_'):
        if now()<payload['reveal_until'] and not payload.get('hidden'):
            await show(interaction,uid,'challenge','Wait for the sequence to hide automatically.');return
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
    s=session(uid)
    if s and now()>=s['deadline']:
        await complete(uid,False,s['mode'],s['kind'],'Time expired.')
        s=None
    if s:
        data=json.loads(s['payload'])
        if s['kind'] in ('memory','path') and now()>=data.get('reveal_until',0) and not data.get('hidden'):
            data['hidden']=True
            conn.execute('UPDATE sessions SET payload=? WHERE uid=?',(json.dumps(data),uid))
        await interaction.response.send_message(embed=challenge_embed(uid),view=UI(uid,'challenge'),ephemeral=True)
        # On restart, /play provides a fresh panel and resumes pending reveals.
        if s['kind'] in ('memory','path') and now()<data.get('reveal_until',0):
            old=AUTO_HIDE_TASKS.pop(uid,None)
            if old:old.cancel()
            AUTO_HIDE_TASKS[uid]=asyncio.create_task(auto_hide_sequence(interaction,uid,s['started'],data['reveal_until']))
    else:
        await interaction.response.send_message(embed=base_embed(uid,description='Explore, earn keys, unlock treasure and climb the leaderboard!'),view=UI(uid,'home'),ephemeral=True)

@bot.tree.command(name='regen_test', description='Admin testing: restore your health instantly')
@app_commands.describe(amount='HP to restore (leave blank to fully heal)')
@app_commands.default_permissions(administrator=True)
async def regen_test(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100] | None = None):
    if not interaction.guild or not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('This testing command is for server administrators only.', ephemeral=True)
        return
    uid = interaction.user.id
    p = player(uid, interaction.user.display_name)
    old_hp = p['hp']
    new_hp = MAX_HP if amount is None else min(MAX_HP, old_hp + amount)
    conn.execute('UPDATE players SET hp=?, hp_tick=? WHERE uid=?', (new_hp, now(), uid))
    await interaction.response.send_message(
        f'❤️ Testing health restored: **{old_hp} → {new_hp}/{MAX_HP} HP**. '
        'Use `/play` to refresh your game panel.', ephemeral=True
    )

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
