"""Dungeon Kombat — solo 100-floor Discord dungeon tournament.
Python 3.11+, discord.py 2.4+, Pillow. All database writes are serialized.
"""
import asyncio
import io
import math
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
from arena import install as install_arena
from visuals import floor_file, panel_file

TOKEN = os.getenv('DISCORD_TOKEN', '')
GUILD_ID = os.getenv('GUILD_ID', '')
DB_PATH = os.getenv('DATABASE_PATH', '/data/dungeon_kombat.db' if Path('/data').exists() else 'dungeon_kombat.db')
START_DATE = os.getenv('EVENT_START_DATE', '2026-11-14')  # UTC, inclusive
DAYS = 7
DAILY_ATTEMPTS = 20
MAX_ATTEMPTS = 140
STAMINA_CAP = 45
STAMINA_DAILY = 15
STAMINA_REGEN_SECONDS = 2 * 60 * 60
STAT_NAMES = ('vitality', 'strength', 'defence', 'agility', 'energy')
WEAPONS = {'Sword': (1.0, 'Blade Flurry'), 'Axe': (1.2, 'Armour Break'), 'Daggers': (0.8, 'Shadow Strike'), 'Staff': (0.9, 'Elemental Blast'), 'Spear': (1.05, 'Piercing Thrust')}
COLORS = {'Crimson': (175, 47, 60), 'Azure': (45, 113, 195), 'Emerald': (38, 147, 96), 'Violet': (132, 75, 175), 'Gold': (203, 151, 50)}
TIERS = ['Forgotten Caves', 'Haunted Woods', 'Crypt of Shadows', 'Inferno Depths', 'Frozen Abyss', 'Toxic Wasteland', 'Cursed Citadel', 'Storm Temple', 'The Void', 'Throne of the Fallen']
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA foreign_keys=ON')
lock = asyncio.Lock()

conn.executescript('''
CREATE TABLE IF NOT EXISTS players (
 user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL, headgear TEXT NOT NULL,
 weapon TEXT NOT NULL DEFAULT 'Sword', weapon_stage INTEGER NOT NULL DEFAULT 0,
 weapon_upgrade INTEGER NOT NULL DEFAULT 0, armor_upgrade INTEGER NOT NULL DEFAULT 0,
 floor INTEGER NOT NULL DEFAULT 0, gold INTEGER NOT NULL DEFAULT 0, materials INTEGER NOT NULL DEFAULT 0,
 points INTEGER NOT NULL DEFAULT 0, vitality INTEGER NOT NULL DEFAULT 0, strength INTEGER NOT NULL DEFAULT 0,
 defence INTEGER NOT NULL DEFAULT 0, agility INTEGER NOT NULL DEFAULT 0, energy INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0, granted_days INTEGER NOT NULL DEFAULT 0,
 spent INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, total_turns INTEGER NOT NULL DEFAULT 0,
 respecs INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS battles (
 user_id INTEGER PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
 floor INTEGER NOT NULL, hp INTEGER NOT NULL, energy INTEGER NOT NULL, potions INTEGER NOT NULL,
 enemy_hp INTEGER NOT NULL, turn INTEGER NOT NULL DEFAULT 1, guarding INTEGER NOT NULL DEFAULT 0,
 focused INTEGER NOT NULL DEFAULT 0, enemy_charge INTEGER NOT NULL DEFAULT 0,
 poisoned INTEGER NOT NULL DEFAULT 0, log TEXT NOT NULL DEFAULT '', seed INTEGER NOT NULL DEFAULT 0
);
''')
# Additive schema migration: preserves existing fighters, equipment and battles.
for table, fields in {
    'players': {'stamina_regen_at':'INTEGER NOT NULL DEFAULT 0','stamina':'INTEGER NOT NULL DEFAULT 0','stamina_days':'INTEGER NOT NULL DEFAULT 0',
        'skill':"TEXT NOT NULL DEFAULT 'None'",'relics':'INTEGER NOT NULL DEFAULT 0',
        'enchantment':"TEXT NOT NULL DEFAULT 'None'",'weapon_advanced':'INTEGER NOT NULL DEFAULT 0',
        'armor_advanced':'INTEGER NOT NULL DEFAULT 0', 'blessing':"TEXT NOT NULL DEFAULT 'None'",'blessing_floors':'INTEGER NOT NULL DEFAULT 0'},
    'battles': {'special_cd':'INTEGER NOT NULL DEFAULT 0'}
}.items():
    existing={r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    for field,sqltype in fields.items():
        if field not in existing:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {field} {sqltype}')
# v13: additive, idempotent world events. Existing players and battles are retained.
conn.executescript('''
CREATE TABLE IF NOT EXISTS dungeon_encounters (
 user_id INTEGER NOT NULL, floor INTEGER NOT NULL, kind TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', choice TEXT,
 PRIMARY KEY(user_id,floor,kind)
);
CREATE TABLE IF NOT EXISTS elite_trials (
 user_id INTEGER NOT NULL, floor INTEGER NOT NULL, turn INTEGER NOT NULL DEFAULT 0,
 successes INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,floor)
);
CREATE TABLE IF NOT EXISTS merchant_purchases (
 user_id INTEGER NOT NULL, floor INTEGER NOT NULL, item TEXT NOT NULL,
 PRIMARY KEY(user_id,floor,item)
);
CREATE TABLE IF NOT EXISTS world_raids (
 day INTEGER PRIMARY KEY, hp INTEGER NOT NULL, max_hp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS raid_participation (
 user_id INTEGER NOT NULL, day INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 damage INTEGER NOT NULL DEFAULT 0, victory_claimed INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,day)
);
''')
conn.commit()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

def event_day():
    start = datetime.strptime(START_DATE, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - start).days + 1

def event_state():
    day = event_day()
    return 'upcoming' if day < 1 else 'ended' if day > DAYS else 'active'

def get_player(uid):
    return conn.execute('SELECT * FROM players WHERE user_id=?', (uid,)).fetchone()

def get_battle(uid):
    return conn.execute('SELECT * FROM battles WHERE user_id=?', (uid,)).fetchone()

def grant_attempts(uid):
    p = get_player(uid)
    day = min(DAYS, max(0, event_day()))
    if day > p['granted_days']:
        added = (day - p['granted_days']) * DAILY_ATTEMPTS
        conn.execute('UPDATE players SET attempts=MIN(?,attempts+?),granted_days=? WHERE user_id=?', (MAX_ATTEMPTS, added, day, uid))
    return get_player(uid)

def grant_stamina(uid, now=None):
    """Lazy, offline-safe stamina regeneration and 00:00 UTC daily grants.

    The timestamp is the last regeneration accounting boundary. At full capacity,
    the timer pauses so spending stamina never creates an instant refill.
    """
    if now is None:
        now = int(time.time())
    p = get_player(uid)
    if p is None:
        return None
    current = int(p['stamina'])
    anchor = int(p['stamina_regen_at'])
    if anchor <= 0 or anchor > now:
        anchor = now  # Existing players don't receive retroactive regeneration.
    if current >= STAMINA_CAP:
        anchor = now
    else:
        ticks = max(0, (now - anchor) // STAMINA_REGEN_SECONDS)
        if ticks:
            current = min(STAMINA_CAP, current + ticks)
            anchor = now if current == STAMINA_CAP else anchor + ticks * STAMINA_REGEN_SECONDS
    day = min(DAYS, max(0, event_day()))
    if day > p['stamina_days']:
        current = min(STAMINA_CAP, current + (day - p['stamina_days']) * STAMINA_DAILY)
        if current == STAMINA_CAP:
            anchor = now
    conn.execute('UPDATE players SET stamina=?,stamina_days=?,stamina_regen_at=? WHERE user_id=?',
                 (current, max(day, p['stamina_days']), anchor, uid))
    return get_player(uid)

def stamina_next_regen(p, now=None):
    if now is None:
        now = int(time.time())
    if p['stamina'] >= STAMINA_CAP:
        return 'Full — regeneration paused'
    anchor = int(p['stamina_regen_at']) or now
    seconds = max(0, STAMINA_REGEN_SECONDS - max(0, now - anchor))
    hours, rem = divmod(seconds, 3600)
    minutes = (rem + 59) // 60
    if minutes == 60:
        hours += 1
        minutes = 0
    return f'{hours}h {minutes}m until +1 stamina'

def advanced_cost(level):
    return 4500+2200*level,22+12*level

def stats(p):
    def effective(n):
        return min(n,40)+max(0,min(n-40,40))*.6+max(0,n-80)*.3
    hp=int(100+effective(p['vitality'])*5+p['armor_upgrade']*4)
    atk=int(20+effective(p['strength'])*2+(10+p['weapon_stage']*22+p['weapon_upgrade']*4)*WEAPONS[p['weapon']][0])
    defense=int(10+effective(p['defence'])+p['armor_upgrade']*4)
    speed=int(10+effective(p['agility']))
    energy=int(50+effective(p['energy'])*3)
    hp+=p['armor_advanced']*10
    defense+=p['armor_advanced']*4
    atk+=p['weapon_advanced']*8
    if p['skill']=='Berserker': atk=round(atk*1.15);hp=round(hp*1.10)
    elif p['skill']=='Guardian': defense=round(defense*1.05);atk=round(atk*1.02)
    elif p['skill']=='Arcanist': energy+=20;atk=round(atk*1.05);hp=round(hp*1.05)
    hp=round(hp*(1+min(p['relics'],10)*.005))
    if p['enchantment']=='Flame': atk=round(atk*1.035)
    elif p['enchantment']=='Ward': hp=round(hp*1.045)
    if p['blessing_floors']>0:
        if p['blessing']=='supplies': hp=round(hp*1.05)
        elif p['blessing']=='knight': defense=round(defense*1.08)
        elif p['blessing']=='berserker': atk=round(atk*1.08)
    return hp,atk,defense,speed,energy

def enemy_stats(floor):
    boss=floor%10==0
    hp=round((72+9*floor+.10*floor**2)*(1.52 if boss else 1))
    attack=round((10+.82*floor+.003*floor**2)*(1.18 if boss else 1))
    defense=round((4+.28*floor)*(1.15 if boss else 1))
    progress=(floor/100)**1.25
    hp=round(hp*(1+.05*progress))
    attack=round(attack*(.95+.05*progress))
    if floor>=35 and not boss:
        late=(floor-35)/65
        hp=round(hp*(1+.08*late));attack=round(attack*(1+.07*late))
    if boss:
        tier=floor//10
        hp=round(hp*(1.02+.007*tier))
        attack=round(attack*(.98+.003*tier))
        hp=round(hp*(1.18 if 20<=floor<=80 else (1.05 if floor==90 else .90)))
        attack=round(attack*(1.09 if 20<=floor<=80 else (.99 if floor==90 else .84)))
    hp=round(hp*1.07)  # v9: modest HP pressure, tested against 7-day activity schedules
    return hp,attack,defense,boss

def reward_for_floor(floor):
    """Deterministic first-clear rewards; boss chests include extra gold/materials."""
    band = (floor - 1) // 10
    gold = 90 + 12*floor + 15*band
    mats = 1 + floor // 40
    if floor % 10 == 0:
        gold += 350 + 60*band
        mats += 6 + band
    return gold, mats

# Adventure encounters are first-clear only. No extra dungeon attempts are spent.
def encounter_kind(floor):
    if floor % 10 == 0 and floor < 100: return 'doors'
    if floor % 5 == 0 and floor % 10 != 0: return 'treasure'
    return None

def pending_encounter(uid):
    return conn.execute("SELECT * FROM dungeon_encounters WHERE user_id=? AND status='pending' ORDER BY floor LIMIT 1",(uid,)).fetchone()

BOSS_NAMES=('The Fallen Knight','The Crypt Warden','The Iron Golem','The Plague Keeper',
            'The Royal Executioner','The Frost Guardian','The Shadow Lord',
            'The Infernal Beast','The Ancient Lich','The Dragon King')

def boss_phase(b):
    max_hp,_,_,boss=enemy_stats(b['floor'])
    if not boss: return 0
    ratio=b['enemy_hp']/max(1,max_hp)
    return 1 if ratio>0.60 else 2 if ratio>0.25 else 3

def enemy_intent(b):
    """Telegraph is deterministic from persisted turn, floor and seed.
    The same intent is used in the embed and in damage resolution.
    """
    if b['enemy_charge']: return 'charged'
    phase=boss_phase(b)
    rng=random.Random(b['seed']+b['turn']*397+phase*13)
    options=['heavy','guard','reckless','normal']
    if b['floor']>=11: options.append('venom')
    if phase>=2: options+=['heavy','guard']
    if phase==3: options+=['reckless','heavy']
    return rng.choice(options)

INTENT_TEXT={
 'charged':'The foe is charging a devastating blow. Defending is wise.',
 'heavy':'The foe raises its weapon for a HEAVY STRIKE. Defend to blunt it.',
 'guard':'The foe braces behind a shield. Focus or use a special attack.',
 'reckless':'The foe lunges recklessly, exposing a weak point. Attack now!',
 'venom':'The foe prepares a venomous strike. Defend to avoid poisoning.',
 'normal':'The foe watches your stance and prepares a standard strike.'}

MERCHANT_ITEMS={
 'supplies':('Healer’s Supplies',250,0,'A three-battle blessing: +5% maximum HP.'),
 'forge':('Blacksmith’s Bundle',600,0,'Gain 8 materials.'),
 'knight':('Knight’s Blessing',450,0,'A three-battle blessing: +8% defence.'),
 'berserker':('Berserker’s Elixir',450,0,'A three-battle blessing: +8% attack.'),
 'relic':('Relic Fragments',1200,0,'Gain 5 materials and 300 gold back.')}

def damage_reduction(defense):
    return max(.45, 100/(100+min(defense,75)*.65+max(0,defense-75)*.09))

def free_points(p):
    return p['floor']*3 - sum(p[s] for s in STAT_NAMES)

def info_embed(p):
    hp, atk, defense, speed, energy = stats(p)
    e = discord.Embed(title=f'⚔️ {p["name"]}', description=f'Floor **{p["floor"]}/100** • {TIERS[min(p["floor"]//10,9)]}', color=discord.Color.dark_red())
    e.add_field(name='Combat stats', value=f'❤️ {hp} HP\n⚔️ {atk} ATK\n🛡️ {defense} DEF\n⚡ {speed} SPD\n🔮 {energy} Energy')
    e.add_field(name='Equipment', value=f'{p["weapon"]} • Stage {p["weapon_stage"]+1} • +{p["weapon_upgrade"]} (Advanced +{p["weapon_advanced"]})\nArmour +{p["armor_upgrade"]} (Advanced +{p["armor_advanced"]})')
    e.add_field(name='Progress', value=f'⭐ {free_points(p)} unspent stat points\n🪙 {p["gold"]} gold\n🔩 {p["materials"]} materials\n🎟️ {p["attempts"]} attempts\n⛏️ {p["stamina"]}/45 activity stamina\n🕒 {stamina_next_regen(p)}\n🌳 {p["skill"]} • 🔮 {p["enchantment"]} • 🏅 {p["relics"]} relics')
    e.set_footer(text=f'Day {max(0,min(DAYS,event_day()))}/{DAYS} • Solo tournament • UTC')
    return e

def avatar_png(p):
    # Deterministic layered 2D preview; no external AI/image service needed.
    img = Image.new('RGBA', (320, 380), (22, 25, 38, 255))
    d = ImageDraw.Draw(img)
    color = COLORS.get(p['color'], COLORS['Crimson'])
    d.ellipse((64, 335, 257, 365), fill=(6, 8, 16, 180))
    d.polygon([(125, 218),(153, 218),(145, 335),(108, 335)], fill=(43, 49, 66))
    d.polygon([(168, 218),(194, 218),(212, 335),(174, 335)], fill=(43, 49, 66))
    d.rectangle((104, 330, 151, 347), fill=(15, 17, 25))
    d.rectangle((173, 330, 219, 347), fill=(15, 17, 25))
    d.polygon([(118, 126),(200, 126),(224, 227),(97, 227)], fill=color, outline=(245, 207, 134))
    d.polygon([(116, 132),(94, 153),(69, 249),(96, 259),(134, 176)], fill=color)
    d.polygon([(202, 132),(226, 153),(249, 249),(222, 259),(184, 176)], fill=color)
    d.ellipse((124, 53, 195, 146), fill=(208, 159, 120), outline=(12, 12, 19), width=4)
    if p['headgear'] == 'Helmet':
        d.polygon([(113, 101),(117, 46),(155, 28),(196, 46),(207, 101),(191, 133),(180, 89),(137, 89),(130, 133)], fill=(145, 152, 165))
        d.line((136, 93, 183, 93), fill=(18, 26, 38), width=8)
    elif p['headgear'] == 'Hood':
        d.polygon([(104, 125),(108, 62),(132, 28),(187, 28),(210, 62),(216, 125),(188, 100),(185, 68),(134, 68),(130, 100)], fill=(39, 41, 58))
    elif p['headgear'] == 'Mask':
        d.polygon([(126, 101),(194, 101),(187, 135),(160, 145),(132, 135)], fill=(36, 40, 52))
    d.line((136, 96, 149, 96), fill=(13, 18, 25), width=3)
    d.line((171, 96, 184, 96), fill=(13, 18, 25), width=3)
    d.rectangle((105, 214, 216, 229), fill=(26, 28, 40))
    d.rectangle((149, 211, 172, 232), fill=(228, 191, 93))
    if p['weapon'] == 'Staff':
        d.line((244, 302, 264, 61), fill=(158, 101, 56), width=9)
        d.ellipse((250, 42, 277, 70), fill=(69, 204, 235))
    elif p['weapon'] == 'Axe':
        d.line((241, 310, 258, 91), fill=(131, 89, 55), width=9)
        d.polygon([(257, 76),(296, 67),(292, 134),(255, 126)], fill=(178, 185, 193))
    elif p['weapon'] == 'Daggers':
        d.polygon([(78, 255),(48, 305),(61, 264)], fill=(207, 215, 223))
        d.polygon([(245, 255),(279, 305),(265, 264)], fill=(207, 215, 223))
    elif p['weapon'] == 'Spear':
        d.line((242, 330, 266, 72), fill=(138, 94, 61), width=8)
        d.polygon([(266, 25),(253, 81),(278, 81)], fill=(207, 215, 223))
    else:
        d.polygon([(241, 258),(268, 59),(281, 35),(277, 69),(251, 262)], fill=(207, 215, 223))
        d.line((228, 255, 268, 266), fill=(235, 186, 79), width=7)
    return img.convert('RGB')

def avatar_file(p):
    bio = io.BytesIO()
    avatar_png(p).save(bio, format='PNG')
    bio.seek(0)
    return discord.File(bio, filename='fighter.png')


# Single-panel navigation: component interactions update their own ephemeral panel.
# Slash-command entry points still create the initial message.
async def ui_reply(interaction, content=None, *, embed=None, embeds=None, file=None, files=None, view=None, ephemeral=True, **kwargs):
    payload = {'content': content}
    if embed is not None: payload['embed'] = embed
    if embeds is not None: payload['embeds'] = embeds
    if view is None:
        view = PlayMenu(interaction.user.id) if get_player(interaction.user.id) else RegistrationGate()
    payload['view'] = view
    attachments = list(files or [])
    if file is not None: attachments.append(file)
    if interaction.type in (discord.InteractionType.component, discord.InteractionType.modal_submit):
        payload['attachments'] = attachments
        return await interaction.response.edit_message(**payload)
    if attachments:
        payload['files'] = attachments
    return await interaction.response.send_message(**payload, ephemeral=ephemeral, **kwargs)

class CreateFighter(discord.ui.Modal, title='Create your fighter'):
    fighter_name = discord.ui.TextInput(label='Fighter name', max_length=24, min_length=2, placeholder='Shadow Reaper')
    async def on_submit(self, interaction: discord.Interaction):
        async with lock:
            if get_player(interaction.user.id):
                return await ui_reply(interaction, 'You already have a fighter. Open `/play` and select My Fighter.', ephemeral=True)
            if event_state() == 'ended':
                return await ui_reply(interaction, 'Registration has closed.', ephemeral=True)
            conn.execute('INSERT INTO players(user_id,name,color,headgear) VALUES(?,?,?,?)', (interaction.user.id, str(self.fighter_name), 'Crimson', 'Mask'))
            grant_attempts(interaction.user.id)
            conn.commit()
            p = get_player(interaction.user.id)
        await ui_reply(interaction, f'⚔️ **{p["name"]} has joined the kingdom!** Your character is ready. Choose your next adventure below.', embed=castle_embed('WELCOME, ADVENTURER', 'Your fighter has been created. The Castle Gate is now open.'), file=panel_file('event'), view=PlayMenu(interaction.user.id), ephemeral=True)

class CustomizeView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid
        self.add_item(CustomSelect(uid, 'color', list(COLORS)))
        self.add_item(CustomSelect(uid, 'headgear', ['Mask','Helmet','Hood','None']))
        self.add_item(CustomSelect(uid, 'weapon', list(WEAPONS)))
        self.add_item(BackToCastle(row=3))

class CustomSelect(discord.ui.Select):
    def __init__(self, uid, field, choices):
        self.uid, self.field = uid, field
        super().__init__(placeholder=f'Choose {field}', options=[discord.SelectOption(label=x, value=x) for x in choices])
    async def callback(self, interaction):
        if interaction.user.id != self.uid:
            return await ui_reply(interaction, 'This is not your character.', ephemeral=True)
        async with lock:
            if get_battle(self.uid):
                return await ui_reply(interaction, 'Finish your current battle before changing equipment.', ephemeral=True)
            p = get_player(self.uid)
            if self.field == 'weapon' and p['weapon'] != self.values[0]:
                # Weapon type switch keeps stage but resets weapon upgrades; refunded as materials.
                conn.execute('UPDATE players SET weapon=?, weapon_upgrade=0, weapon_advanced=0, materials=materials+? WHERE user_id=?', (self.values[0], p['weapon_upgrade']*2, self.uid))
            else:
                conn.execute(f'UPDATE players SET {self.field}=? WHERE user_id=?', (self.values[0], self.uid))
            conn.commit()
            p = get_player(self.uid)
        await ui_reply(interaction, 'Updated fighter preview:', embed=info_embed(p), file=avatar_file(p), ephemeral=True)

class BattleView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=None)
        self.uid = uid
    async def interaction_check(self, interaction):
        if interaction.user.id != self.uid:
            await ui_reply(interaction, 'This battle belongs to another fighter.', ephemeral=True)
            return False
        return True
    @discord.ui.button(label='Attack', emoji='⚔️', style=discord.ButtonStyle.primary)
    async def attack(self, interaction, button):
        await resolve_action(interaction, 'attack')
    @discord.ui.button(label='Defend', emoji='🛡️', style=discord.ButtonStyle.secondary)
    async def defend(self, interaction, button):
        await resolve_action(interaction, 'defend')
    @discord.ui.button(label='Special', emoji='🔥', style=discord.ButtonStyle.primary)
    async def special(self, interaction, button):
        await resolve_action(interaction, 'special')
    @discord.ui.button(label='Heal', emoji='💚', style=discord.ButtonStyle.primary)
    async def heal(self, interaction, button):
        await resolve_action(interaction, 'heal')
    @discord.ui.button(label='Focus', emoji='⚡', style=discord.ButtonStyle.secondary)
    async def focus(self, interaction, button):
        await resolve_action(interaction, 'focus')
    @discord.ui.button(label='Castle Gate', emoji='🏰', style=discord.ButtonStyle.secondary, row=1)
    async def exit_battle(self, interaction, button):
        # Preserve the ongoing battle; entering the dungeon resumes it.
        await open_castle(interaction)

class DungeonResultView(discord.ui.View):
    """Next-floor navigation; exit closes the panel without spending attempts."""
    def __init__(self, uid, won):
        super().__init__(timeout=900)
        self.uid=uid
        if not won:
            self.next_floor.label='Retry Floor'
    async def interaction_check(self, interaction):
        if interaction.user.id != self.uid:
            await ui_reply(interaction, 'This is another fighter’s dungeon.', ephemeral=True)
            return False
        return True
    @discord.ui.button(label='Next Floor',emoji='🚪',style=discord.ButtonStyle.primary)
    async def next_floor(self, interaction, button):
        if pending_encounter(self.uid):
            await open_encounter(interaction)
        else:
            await dungeon.callback(interaction)
    @discord.ui.button(label='Exit Dungeon',emoji='🏰',style=discord.ButtonStyle.secondary)
    async def exit_dungeon(self, interaction, button):
        await interaction.response.edit_message(content=None, embed=castle_embed(), attachments=[panel_file('event')], view=PlayMenu(self.uid))

def battle_embed(p, b, message=None):
    maxhp, atk, defense, speed, maxenergy = stats(p)
    enemyhp, enemyatk, enemydef, boss = enemy_stats(b['floor'])
    e = discord.Embed(title=f'⚔️ Floor {b["floor"]} — {"BOSS" if boss else "Monster"}', description=f'**{TIERS[(b["floor"]-1)//10]}**\n{message or b["log"]}', color=discord.Color.red() if boss else discord.Color.dark_blue())
    e.add_field(name=f'🧍 {p["name"]}', value=f'❤️ {b["hp"]}/{maxhp}\n🔮 {b["energy"]}/{maxenergy}\n💚 {b["potions"]} potions')
    e.add_field(name='💀 Enemy', value=f'❤️ {b["enemy_hp"]}/{enemyhp}\n⚔️ {enemyatk} ATK\n🛡️ {enemydef} DEF' + ('\n🛡️ Shielded: normal attacks effective' if boss and b['floor']>=20 and b['turn']%5 in (1,2) else ''))
    e.add_field(name='Turn', value=f'{b["turn"]}/{30 if boss else 20} • Special cooldown: {b["special_cd"]}' + (f' • 🔥 Boss enrage +{(b["turn"]-8)*10}% incoming damage' if boss and b['turn']>8 else ''), inline=False)
    intent=enemy_intent(b)
    e.add_field(name='📜 Enemy Intention',value=INTENT_TEXT[intent],inline=False)
    if boss:
        phase=boss_phase(b)
        e.add_field(name='👑 Boss',value=f'{BOSS_NAMES[(b["floor"]//10)-1]} • Phase {phase}/3' + (' • Final Stand: higher damage, exposed openings' if phase==3 else ''),inline=False)
    if b['poisoned']:
        e.add_field(name='☠️ Poison', value=f'{b["poisoned"]} turns remaining', inline=False)
    e.set_image(url="attachment://dungeon-floor.png")
    e.set_footer(text=f"Zone {(b['floor']-1)//10+1}/10 • {'BOSS ENCOUNTER' if boss else 'DUNGEON ENCOUNTER'} • Every floor has its own scene")
    return e

async def resolve_action(interaction, action):
    async with lock:
        p = get_player(interaction.user.id)
        b = get_battle(interaction.user.id)
        if not p or not b:
            return await ui_reply(interaction, 'No active battle. Use `/dungeon`.', ephemeral=True)
        maxhp, atk, defense, speed, maxenergy = stats(p)
        enemymax, enemyatk, enemydef, boss = enemy_stats(b['floor'])
        if action == 'special' and (b['energy'] < 28 or b['special_cd'] > 0):
            return await ui_reply(interaction, 'Special requires 28 energy and no active cooldown.', ephemeral=True)
        if action == 'heal' and (b['potions'] == 0 or b['hp'] >= maxhp):
            return await ui_reply(interaction, 'You cannot use a potion now.', ephemeral=True)
        hp, energy, enemyhp, potions = b['hp'], b['energy'], b['enemy_hp'], b['potions']
        focused, charge, poison = b['focused'], b['enemy_charge'], b['poisoned']
        cooldown=max(0,b['special_cd']-1)
        guard = action == 'defend'
        notes = []
        if action in ('attack','special'):
            multiplier = 1.38 if action == 'attack' else 1.48
            if action == 'special':
                energy -= 28
                cooldown=3
                # Each weapon has a distinct combat effect.
                if p['weapon'] == 'Axe': multiplier = 1.55
                elif p['weapon'] == 'Daggers': multiplier = 1.53
                elif p['weapon'] == 'Staff': multiplier = 1.56
                elif p['weapon'] == 'Spear': multiplier = 1.53
            shielded=boss and b['floor']>=20 and b['turn']%5 in (1,2)
            if shielded: multiplier *= (.48 if action=='special' else 1.55)
            if action=='attack': energy=min(maxenergy,energy+7)
            if focused: multiplier *= 1.15
            base = max(1, round(atk * multiplier * damage_reduction(enemydef)))
            # Small variation is deterministic for this battle and turn/action.
            rng = random.Random(b['seed'] + b['turn']*131 + (1 if action=='attack' else 2))
            crit = rng.random() < min(0.25, 0.05 + speed/500)
            dealt = max(1, round(base*(1.35 if crit else 1)*rng.uniform(0.95,1.05)))
            if action == 'special' and p['weapon'] == 'Spear': dealt = round(dealt*1.12)
            enemyhp = max(0, enemyhp-dealt)
            notes.append(f'{"🔥 Special" if action=="special" else "⚔️ Attack"} deals **{dealt}** damage'+(' (CRITICAL!)' if crit else '')+'.')
            if action == 'special' and p['weapon'] == 'Axe': notes.append('🪓 Armour Break enhances this attack.')
        elif action == 'defend':
            notes.append('🛡️ You defend against the next attack.')
        elif action == 'heal':
            recovered = min(maxhp-hp, max(30,round(maxhp*0.3)))
            hp += recovered
            potions -= 1
            notes.append(f'💚 Restored **{recovered}** HP.')
        elif action == 'focus':
            energy = min(maxenergy,energy+18)
            notes.append('⚡ Restored 18 energy; your next attack is strengthened.')
        if action in ('attack','special'): focused = 0
        elif action == 'focus': focused = 1
        intent=enemy_intent(b)
        phase=boss_phase(b)
        if action in ('attack','special') and intent=='guard' and enemyhp>0:
            # Guarding enemies resist ordinary attacks; special pierces the guard.
            mitigation=0.10 if action=='special' else 0.25
            adjustment=round(dealt*mitigation)
            enemyhp+=adjustment
            notes.append(f'🛡️ Enemy guard absorbs {adjustment} damage.')
        if action in ('attack','special') and intent=='reckless' and enemyhp>0:
            bonus=round(dealt*.15)
            enemyhp=max(0,enemyhp-bonus)
            notes.append(f'⚔️ Exploited opening: +{bonus} damage!')
        if enemyhp > 0:
            rng = random.Random(b['seed'] + b['turn']*157)
            incoming = round(enemyatk*damage_reduction(defense)*rng.uniform(0.9,1.1))
            if charge: incoming = round(incoming*2.1)
            elif intent=='heavy': incoming=round(incoming*1.45)
            elif intent=='reckless': incoming=round(incoming*.82)
            elif intent=='guard': incoming=round(incoming*.72)
            if boss and phase==2: incoming=round(incoming*1.07)
            elif boss and phase==3: incoming=round(incoming*1.14)
            if boss and b['turn']>8: incoming=round(incoming*(1+.10*(b['turn']-8)))
            if guard: incoming = max(1,round(incoming*0.55))
            # Dodge soft cap: no more than 20%.
            dodge = min(0.2, max(0, (speed-10)*0.001))
            if rng.random() < dodge:
                incoming = 0
                notes.append('⚡ You dodged the enemy attack!')
            hp = max(0,hp-incoming)
            notes.append(f'💀 Enemy hits for **{incoming}** damage.')
            if poison:
                tick = max(1,round(maxhp*0.04))
                hp = max(0,hp-tick)
                poison -= 1
                notes.append(f'☠️ Poison deals **{tick}** damage.')
            if b['floor'] >= 11 and intent=='venom' and not guard and not poison:
                poison = 2
                notes.append('☠️ The enemy poisons you for two turns!')
            charge = 1 if b['floor'] >= 31 and b['turn'] % 4 == 0 else 0
        nextturn = b['turn']+1
        won = enemyhp == 0
        lost = hp <= 0 or nextturn > (30 if boss else 20)
        if won:
            floor = b['floor']
            gold, mats = reward_for_floor(floor)
            respec = 1 if boss else 0
            conn.execute('UPDATE players SET floor=?,gold=gold+?,materials=materials+?,total_turns=total_turns+?,respecs=respecs+? WHERE user_id=?', (floor,gold,mats,b['turn'],respec,interaction.user.id))
            conn.execute('DELETE FROM battles WHERE user_id=?',(interaction.user.id,))
            notes.append(f'🏆 **VICTORY!** Floor {floor} cleared. +{gold} gold, +{mats} materials, +3 stat points.' + (' 🎁 Boss chest included! +1 respec token.' if boss else ''))
            if floor in (20,40,60,80):
                conn.execute('UPDATE players SET weapon_stage=weapon_stage+1 WHERE user_id=?',(interaction.user.id,))
                notes.append('✨ Weapon evolved! Your +upgrade level has been preserved.')
            kind=encounter_kind(floor)
            if kind:
                conn.execute('INSERT OR IGNORE INTO dungeon_encounters(user_id,floor,kind) VALUES(?,?,?)',(interaction.user.id,floor,kind))
                notes.append('📜 A new castle encounter awaits! Choose **Next Floor** to resolve it.')
            conn.execute('UPDATE players SET blessing_floors=MAX(0,blessing_floors-1) WHERE user_id=?',(interaction.user.id,))
            if boss:
                conn.execute('UPDATE players SET relics=relics+1 WHERE user_id=?',(interaction.user.id,))
                notes.append('🏅 Earned a permanent boss relic (+0.5% maximum HP).')
        elif lost:
            conn.execute('UPDATE players SET losses=losses+1 WHERE user_id=?',(interaction.user.id,))
            conn.execute('DELETE FROM battles WHERE user_id=?',(interaction.user.id,))
            notes.append('💀 **DEFEAT.** This attempt is spent, but your completed floors are safe.')
        else:
            conn.execute('UPDATE battles SET hp=?,energy=?,potions=?,enemy_hp=?,turn=?,guarding=?,focused=?,enemy_charge=?,poisoned=?,special_cd=?,log=? WHERE user_id=?', (hp,energy,potions,enemyhp,nextturn,int(guard),focused,charge,poison,cooldown,'\n'.join(notes),interaction.user.id))
        conn.commit()
        p = get_player(interaction.user.id)
        b2 = get_battle(interaction.user.id)
        if b2:
            embed = battle_embed(p,b2,'\n'.join(notes))
        else:
            embed = discord.Embed(title='🏆 Dungeon cleared!' if won else '💀 Dungeon failed', description='\n'.join(notes), color=discord.Color.green() if won else discord.Color.red())
            embed.add_field(name='Progress',value=f'Highest floor: **{p["floor"]}/100**\nRemaining attempts: **{p["attempts"]}**')
            embed.set_image(url='attachment://dungeon-floor.png')
    # The original ephemeral message may no longer be editable after restarts; respond with a fresh panel.
    await ui_reply(interaction, embed=embed,file=floor_file(b2['floor'] if b2 else b['floor']),view=BattleView(interaction.user.id) if b2 else DungeonResultView(interaction.user.id, won),ephemeral=True)

@bot.tree.command(name='register',description='Create your own dungeon fighter')
async def register(interaction: discord.Interaction):
    if get_player(interaction.user.id):
        return await ui_reply(interaction, 'You already have a fighter. Open `/play` and select My Fighter.',ephemeral=True)
    await interaction.response.send_modal(CreateFighter())

@bot.tree.command(name='fighter',description='View your fighter and avatar')
async def fighter(interaction: discord.Interaction):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await ui_reply(interaction, 'Register first with `/register`.',ephemeral=True)
        grant_attempts(interaction.user.id)
        grant_stamina(interaction.user.id)
        conn.commit()
        p = get_player(interaction.user.id)
    e=info_embed(p); e.set_image(url='attachment://dungeon-panel.png')
    await ui_reply(interaction, embed=e,files=[avatar_file(p),panel_file('fighter',p['floor'])],ephemeral=True)

@bot.tree.command(name='customize',description='Customize your avatar, weapon and armour colours')
async def customize(interaction: discord.Interaction):
    p = get_player(interaction.user.id)
    if not p: return await ui_reply(interaction, 'Open `/play` and select Create Fighter first.',ephemeral=True)
    await ui_reply(interaction, 'Choose an option below. The avatar preview updates after each selection. Switching weapon class resets its upgrade level and refunds 2 materials per level.',embed=info_embed(p),file=avatar_file(p),view=CustomizeView(interaction.user.id),ephemeral=True)

@bot.tree.command(name='allocate',description='Spend stat points on your fighter')
@app_commands.describe(attribute='Attribute to improve',points='How many points to spend (1–30)')
@app_commands.choices(attribute=[app_commands.Choice(name=s.title(),value=s) for s in STAT_NAMES])
async def allocate(interaction: discord.Interaction, attribute: app_commands.Choice[str], points: app_commands.Range[int,1,30]):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await ui_reply(interaction, 'Open `/play` and select Create Fighter first.',ephemeral=True)
        if get_battle(interaction.user.id): return await ui_reply(interaction, 'You cannot allocate points during combat.',ephemeral=True)
        if free_points(p)<points: return await ui_reply(interaction, f'You have only {free_points(p)} free points.',ephemeral=True)
        conn.execute(f'UPDATE players SET {attribute.value}={attribute.value}+? WHERE user_id=?',(points,interaction.user.id))
        conn.commit()
        p = get_player(interaction.user.id)
    await ui_reply(interaction, f'Allocated {points} points to {attribute.name}.',embed=info_embed(p),ephemeral=True)

@bot.tree.command(name='respec',description='Reset your allocated stats using a respec token')
async def respec(interaction: discord.Interaction):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await ui_reply(interaction, 'Register first.',ephemeral=True)
        if get_battle(interaction.user.id): return await ui_reply(interaction, 'Finish your battle first.',ephemeral=True)
        if p['respecs']<1: return await ui_reply(interaction, 'No respec tokens. Earn one from every boss.',ephemeral=True)
        conn.execute('UPDATE players SET vitality=0,strength=0,defence=0,agility=0,energy=0,respecs=respecs-1 WHERE user_id=?',(interaction.user.id,))
        conn.commit()
        p = get_player(interaction.user.id)
    await ui_reply(interaction, 'All stat points have been refunded.',embed=info_embed(p),ephemeral=True)

@bot.tree.command(name='upgrade',description='Upgrade your weapon or armour')
@app_commands.choices(item=[app_commands.Choice(name='Weapon',value='weapon'),app_commands.Choice(name='Armour',value='armor')])
async def upgrade(interaction: discord.Interaction,item:app_commands.Choice[str]):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await ui_reply(interaction, 'Register first.',ephemeral=True)
        if get_battle(interaction.user.id): return await ui_reply(interaction, 'Finish your battle first.',ephemeral=True)
        field = 'weapon_upgrade' if item.value=='weapon' else 'armor_upgrade'
        current = p[field]
        if current>=10: return await ui_reply(interaction, 'Already at +10. Weapon evolution at floors 20, 40, 60 and 80 preserves upgrades.',ephemeral=True)
        gold = (current+1)*150
        mats = current+1
        if p['gold']<gold or p['materials']<mats:
            return await ui_reply(interaction, f'Upgrade requires **{gold} gold** and **{mats} materials**. You have {p["gold"]} gold and {p["materials"]} materials.',ephemeral=True)
        conn.execute(f'UPDATE players SET {field}={field}+1,gold=gold-?,materials=materials-? WHERE user_id=?',(gold,mats,interaction.user.id))
        conn.commit()
        p = get_player(interaction.user.id)
    await ui_reply(interaction, f'Upgrade successful: {item.name} +{p[field]}!',embed=info_embed(p),ephemeral=True)

class WorkshopConfirm(discord.ui.View):
    def __init__(self, uid, item):
        super().__init__(timeout=120)
        self.uid, self.item = uid, item
    @discord.ui.button(label='Confirm upgrade',style=discord.ButtonStyle.primary,emoji='🔨')
    async def confirm(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id!=self.uid:
            return await ui_reply(interaction, 'This workshop belongs to another fighter.',ephemeral=True)
        async with lock:
            p=get_player(self.uid)
            if not p or get_battle(self.uid):
                return await ui_reply(interaction, 'Register or finish your current battle first.',ephemeral=True)
            field='weapon_upgrade' if self.item=='weapon' else 'armor_upgrade'
            level=p[field]
            if level>=10:
                return await ui_reply(interaction, 'This item is already +10.',ephemeral=True)
            cost=150*(level+1); mats=level+1
            if p['gold']<cost or p['materials']<mats:
                return await ui_reply(interaction, f'Need {cost:,} gold and {mats} materials; check `/wallet`.',ephemeral=True)
            conn.execute(f'UPDATE players SET {field}={field}+1,gold=gold-?,materials=materials-? WHERE user_id=?',(cost,mats,self.uid))
            conn.commit(); p=get_player(self.uid)
        await interaction.response.edit_message(content=f'✅ {self.item.title()} upgraded to **+{p[field]}**!',embed=info_embed(p),view=ForgeMenu(self.uid))

class WorkshopView(discord.ui.View):
    def __init__(self,uid):
        super().__init__(timeout=180)
        self.uid=uid
    @discord.ui.button(label='Upgrade Weapon',style=discord.ButtonStyle.primary,emoji='⚔️')
    async def weapon(self,interaction:discord.Interaction,button:discord.ui.Button):
        await self.ask(interaction,'weapon')
    @discord.ui.button(label='Upgrade Armour',style=discord.ButtonStyle.secondary,emoji='🛡️')
    async def armor(self,interaction:discord.Interaction,button:discord.ui.Button):
        await self.ask(interaction,'armor')
    async def ask(self,interaction,item):
        if interaction.user.id!=self.uid:
            return await ui_reply(interaction, 'This workshop belongs to another fighter.',ephemeral=True)
        p=get_player(self.uid)
        if not p or get_battle(self.uid):
            return await ui_reply(interaction, 'Register or finish your battle first.',ephemeral=True)
        level=p['weapon_upgrade' if item=='weapon' else 'armor_upgrade']
        if level>=10:
            return await ui_reply(interaction, 'Already fully upgraded (+10).',ephemeral=True)
        cost=150*(level+1); mats=level+1
        await ui_reply(interaction, f'🔨 **{item.title()} +{level} → +{level+1}**\nCost: **{cost:,} gold** and **{mats} materials**\nYour wallet: **{p["gold"]:,} gold**, **{p["materials"]} materials**\nConfirm to purchase (cost rechecked at purchase time).',view=WorkshopConfirm(self.uid,item),ephemeral=True)

@bot.tree.command(name='workshop',description='Open the weapon and armour upgrade workshop')
async def workshop(interaction:discord.Interaction):
    p=get_player(interaction.user.id)
    if not p: return await ui_reply(interaction, 'Open `/play` and select Create Fighter first.',ephemeral=True)
    e=info_embed(p);e.set_image(url='attachment://dungeon-panel.png')
    await ui_reply(interaction, '🔨 **DUNGEON WORKSHOP**\nChoose which item to upgrade. Upgrades always succeed and weapon evolution preserves your +level.',embed=e,file=panel_file('workshop'),view=WorkshopView(interaction.user.id),ephemeral=True)

@bot.tree.command(name='wallet',description='View your gold, materials and next equipment upgrade costs')
async def wallet(interaction: discord.Interaction):
    p = get_player(interaction.user.id)
    if not p: return await ui_reply(interaction, 'Open `/play` and select Create Fighter first.',ephemeral=True)
    e = discord.Embed(title='🪙 Dungeon Wallet',description=f'**Gold:** {p["gold"]:,}\n**Materials:** {p["materials"]:,}',color=discord.Color.gold())
    for title,field in [('Weapon','weapon_upgrade'),('Armour','armor_upgrade')]:
        level=p[field]
        if level>=10: detail='MAX +10'
        else:
            g=(level+1)*150; m=level+1
            detail=f'+{level} → +{level+1}: **{g:,} gold** and **{m} materials**\n'+('✅ Affordable' if p['gold']>=g and p['materials']>=m else '❌ Not yet affordable')
        e.add_field(name=title,value=detail,inline=False)
    e.add_field(name='Advanced forging',value=f'Weapon +{p["weapon_advanced"]}/5 • Armour +{p["armor_advanced"]}/5. Unlock at Floor 50 after +10. Open `/play` → Blacksmith → Advanced Forging.',inline=False)
    e.set_footer(text='Boss chests award bonus resources every 10 floors. Rewards are first-clear only.')
    e.set_image(url='attachment://dungeon-panel.png')
    await ui_reply(interaction, embed=e,file=panel_file('wallet'),ephemeral=True)

@bot.tree.command(name='dungeon',description='Enter the next solo dungeon floor or resume your battle')
async def dungeon(interaction: discord.Interaction):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await ui_reply(interaction, 'Open `/play` and select Create Fighter first.',ephemeral=True)
        b = get_battle(interaction.user.id)
        if not b and pending_encounter(interaction.user.id):
            return await open_encounter(interaction)
        elite=conn.execute('SELECT floor FROM elite_trials WHERE user_id=? AND completed=0 ORDER BY floor LIMIT 1',(interaction.user.id,)).fetchone()
        if not b and elite:
            return await elite_panel(interaction,elite['floor'])
        if b:
            embed = battle_embed(p,b,'Your battle is still in progress. Continue below.')
        else:
            if event_state()!='active':
                return await ui_reply(interaction, 'Dungeon attempts are available only during the seven-day event. Check `/event`.',ephemeral=True)
            p = grant_attempts(interaction.user.id)
            if p['floor']>=100: return await ui_reply(interaction, '🏆 You have cleared all 100 dungeon floors!',ephemeral=True)
            if p['attempts']<=0: return await ui_reply(interaction, 'No attempts remaining. New attempts unlock at 00:00 UTC each event day.',ephemeral=True)
            floor = p['floor']+1
            enemyhp,_,_,_ = enemy_stats(floor)
            hp,_,_,_,energy = stats(p)
            seed = random.SystemRandom().randint(1,2**31-1)
            conn.execute('INSERT INTO battles(user_id,floor,hp,energy,potions,enemy_hp,seed) VALUES(?,?,?,?,?,?,?)',(interaction.user.id,floor,hp,energy,3,enemyhp,seed))
            conn.execute('UPDATE players SET attempts=attempts-1,spent=spent+1 WHERE user_id=?',(interaction.user.id,))
            b = get_battle(interaction.user.id)
            embed = battle_embed(p,b,'A monster blocks your path! Choose your first action.')
        conn.commit()
    await ui_reply(interaction, embed=embed,file=floor_file(b['floor']),view=BattleView(interaction.user.id),ephemeral=True)

@bot.tree.command(name='activities',description='Earn resources through daily stamina-limited activities')
@app_commands.choices(activity=[app_commands.Choice(name='Gold Mine (80 gold)',value='mine'),app_commands.Choice(name='Crystal Cavern (2 materials)',value='crystal'),app_commands.Choice(name='Ancient Ruins (110 gold, 2 materials)',value='ruins')])
async def activities(interaction:discord.Interaction,activity:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p:return await ui_reply(interaction, 'Register first.',ephemeral=True)
        if event_state()!='active':return await ui_reply(interaction, 'Activities are available during the seven-day dungeon event.',ephemeral=True)
        p=grant_stamina(interaction.user.id)
        if p['stamina']<1:return await ui_reply(interaction, f'No activity stamina left. You gain 15 at 00:00 UTC daily and +1 every 2 hours (maximum 45). {stamina_next_regen(p)}.',ephemeral=True)
        gold,mats={'mine':(80,0),'crystal':(0,2),'ruins':(110,2)}[activity.value]
        conn.execute('UPDATE players SET stamina=stamina-1,gold=gold+?,materials=materials+? WHERE user_id=?',(gold,mats,interaction.user.id))
        conn.commit()
        remaining=p['stamina']-1
        # A full pool has a paused timer. Start its 2-hour timer when first spent.
        if p['stamina'] >= STAMINA_CAP:
            conn.execute('UPDATE players SET stamina_regen_at=? WHERE user_id=?',(int(time.time()),interaction.user.id))
            conn.commit()
        updated=get_player(interaction.user.id)
    await ui_reply(interaction, f'⛏️ **{activity.name}** complete! +{gold} gold, +{mats} materials. **{remaining}** stamina remaining. 🕒 {stamina_next_regen(updated)}.',ephemeral=True)

@bot.tree.command(name='stamina',description='Check your activity stamina and next regeneration')
async def stamina_status(interaction:discord.Interaction):
    async with lock:
        p=get_player(interaction.user.id)
        if not p:
            return await ui_reply(interaction, 'Register first with `/register`.',ephemeral=True)
        if event_state()=='active':
            p=grant_stamina(interaction.user.id)
            conn.commit()
        message=(f'⚡ **Activity stamina: {p["stamina"]}/{STAMINA_CAP}**\n'
                 f'🕒 {stamina_next_regen(p) if event_state()=="active" else "Regeneration only during the event"}\n'
                 f'🎁 +{STAMINA_DAILY} daily at 00:00 UTC (up to cap {STAMINA_CAP}).\n'
                 f'⛏️ Use `/play` → Gather Resources to spend stamina.')
    await ui_reply(interaction, message,ephemeral=True)

@bot.tree.command(name='skill',description='Select one permanent skill specialization (after Floor 5)')
@app_commands.choices(path=[app_commands.Choice(name='Berserker — attack focus',value='Berserker'),app_commands.Choice(name='Guardian — survival focus',value='Guardian'),app_commands.Choice(name='Arcanist — energy focus',value='Arcanist')])
async def skill(interaction:discord.Interaction,path:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p or p['floor']<5:return await ui_reply(interaction, 'Clear Floor 5 first.',ephemeral=True)
        if p['skill']!='None':return await ui_reply(interaction, 'Your skill specialization is already selected.',ephemeral=True)
        if get_battle(interaction.user.id):return await ui_reply(interaction, 'Finish your battle before changing equipment.',ephemeral=True)
        conn.execute('UPDATE players SET skill=? WHERE user_id=?',(path.value,interaction.user.id));conn.commit()
    await ui_reply(interaction, f'🌳 **{path.value}** unlocked. View its bonuses with `/fighter`.',ephemeral=True)

@bot.tree.command(name='enchant',description='Enchant equipment with Flame or Ward (Floor 30+)')
@app_commands.choices(effect=[app_commands.Choice(name='Flame — +3.5% attack',value='Flame'),app_commands.Choice(name='Ward — +4.5% HP',value='Ward')])
async def enchant(interaction:discord.Interaction,effect:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p or p['floor']<30:return await ui_reply(interaction, 'Clear Floor 30 to unlock enchantments.',ephemeral=True)
        if p['enchantment']!='None':return await ui_reply(interaction, 'You already have an enchantment.',ephemeral=True)
        if get_battle(interaction.user.id):return await ui_reply(interaction, 'Finish your battle first.',ephemeral=True)
        if p['gold']<4000 or p['materials']<25:return await ui_reply(interaction, 'Requires 4,000 gold and 25 materials.',ephemeral=True)
        conn.execute('UPDATE players SET enchantment=?,gold=gold-4000,materials=materials-25 WHERE user_id=?',(effect.value,interaction.user.id));conn.commit()
    await ui_reply(interaction, f'✨ {effect.value} enchantment equipped!',ephemeral=True)

@bot.tree.command(name='advance',description='Upgrade +10 weapon or armour with advanced forging (Floor 50+)')
@app_commands.choices(item=[app_commands.Choice(name='Weapon',value='weapon'),app_commands.Choice(name='Armour',value='armor')])
async def advance(interaction:discord.Interaction,item:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p or p['floor']<50:return await ui_reply(interaction, 'Advanced forging unlocks at Floor 50.',ephemeral=True)
        if get_battle(interaction.user.id):return await ui_reply(interaction, 'Finish your battle first.',ephemeral=True)
        key=item.value+'_advanced';lvl=p[key]
        if p[item.value+'_upgrade']<10:return await ui_reply(interaction, 'Reach equipment +10 first.',ephemeral=True)
        if lvl>=5:return await ui_reply(interaction, 'Already at advanced +5.',ephemeral=True)
        gold,mats=advanced_cost(lvl)
        if p['gold']<gold or p['materials']<mats:return await ui_reply(interaction, f'Next upgrade costs {gold:,} gold and {mats} materials.',ephemeral=True)
        conn.execute(f'UPDATE players SET {key}={key}+1,gold=gold-?,materials=materials-? WHERE user_id=?',(gold,mats,interaction.user.id));conn.commit()
    await ui_reply(interaction, f'🔨 {item.name} advanced to **+{lvl+1}** for {gold:,} gold and {mats} materials.',ephemeral=True)

arena_system = install_arena(bot, conn, lock, get_player, event_day, lambda i: open_castle(i))

@bot.tree.command(name='leaderboard',description='View the solo dungeon tournament rankings')
async def leaderboard(interaction: discord.Interaction):
    rows = conn.execute('SELECT p.user_id,p.name,p.floor,p.spent,p.losses,p.total_turns,\n        COALESCE(SUM(a.score),0) AS arena_points,\n        COALESCE(SUM(CASE WHEN a.turn=4 THEN 1 ELSE 0 END),0) AS arena_done\n        FROM players p LEFT JOIN arena_runs a ON a.user_id=p.user_id\n        GROUP BY p.user_id\n        ORDER BY CASE WHEN p.floor=100 AND COALESCE(SUM(CASE WHEN a.turn=4 THEN 1 ELSE 0 END),0)=5 THEN 1 ELSE 0 END DESC,\n        CASE WHEN p.floor=100 AND COALESCE(SUM(CASE WHEN a.turn=4 THEN 1 ELSE 0 END),0)=5 THEN COALESCE(SUM(a.score),0) ELSE 0 END DESC,\n        p.floor DESC,p.spent ASC,p.losses ASC,p.total_turns ASC,p.user_id ASC LIMIT 15').fetchall()
    e = discord.Embed(title='🏆 Dungeon Kombat Leaderboard',description='Completed Championship Arena scores rank first (out of 500); then dungeon floor and efficiency. Arena qualifiers have two extra days to finish.',color=discord.Color.gold())
    if not rows: e.description='No fighters have registered yet.'
    else:
        for i,p in enumerate(rows):
            arena_text = f' • 🏟️ **{p["arena_points"]}/500**' if p['arena_done']==5 else (f' • Arena {p["arena_done"]}/5' if p['arena_done'] else '')
            e.add_field(name=f'{["🥇","🥈","🥉"][i] if i<3 else str(i+1)+"."} {p["name"]}',value=f'Floor **{p["floor"]}/100** • {p["spent"]} attempts{arena_text}',inline=False)
    e.set_image(url="attachment://dungeon-panel.png")
    await ui_reply(interaction, embed=e,file=panel_file("leaderboard"),ephemeral=False)

@bot.tree.command(name='event',description='View the tournament dates and rules')
async def event(interaction: discord.Interaction):
    e=discord.Embed(title='🏰 Dungeon Kombat: The Kingdom Trials',description=f'**Start (UTC):** {START_DATE}\n**Duration:** 7 days\n**Status:** {event_state().title()}\n**Current day:** {event_day()}\n**Goal:** Clear as many of 100 solo dungeon floors as possible.',color=discord.Color.orange())
    e.add_field(name='Attempts',value='20 new attempts per day; unused attempts carry over. Max 140 total.')
    e.add_field(name='Combat',value='Turn-based: Attack, Defend, Special, Heal, Focus. Boss every 10 floors.')
    e.add_field(name='Ranking',value='Clear Floor 100 to unlock five Arena challenges worth 500 total points. Arena completion and score determine the champions; dungeon progress and efficiency break ties.',inline=False)
    e.add_field(name='Arena window',value='Arena is open on event days 1–9, including two days after the dungeon closes.',inline=False)
    e.add_field(name='Rewards',value='First-clear rewards and boss relics. `/activities` earns extra resources using 15 daily stamina plus +1 regeneration every 2 hours (cap 45). `/skill` unlocks after Floor 5, `/enchant` after Floor 30 and `/advance` after Floor 50.',inline=False)
    e.set_image(url="attachment://dungeon-panel.png")
    await ui_reply(interaction, embed=e,file=panel_file("event"),ephemeral=True)

# ----- v13 medieval encounters, merchant and cooperative world raids -----
def encounter_embed(row):
    floor,kind=row['floor'],row['kind']
    if kind=='doors':
        desc=('Three ancient doors stand before you. Each promises a different path. '
              'Choose once; the result is saved. You may also leave safely.\n\n'
              '🛡️ **Iron Door:** face an elite guardian for extra gold and materials.\n'
              '🪙 **Golden Door:** collect a guaranteed treasury reward.\n'
              '✨ **Runic Door:** receive a temporary combat blessing.')
        title=f'🚪 Floor {floor} — The Three Doors'
    else:
        title=f'🗝️ Floor {floor} — The Forgotten Treasury'
        desc=('Choose exactly one chest. Rewards are guaranteed, with no hidden traps.\n\n'
              '🪙 King’s Chest — 350 gold\n🔨 Smith’s Chest — 8 materials\n'
              '💚 Healer’s Chest — a three-battle +5% HP blessing')
    e=discord.Embed(title=title,description=desc,color=discord.Color.from_rgb(137,94,48))
    e.set_image(url='attachment://dungeon-panel.png')
    return e

async def open_encounter(interaction):
    row=pending_encounter(interaction.user.id)
    if not row: return await dungeon.callback(interaction)
    await ui_reply(interaction, embed=encounter_embed(row),file=panel_file(row['kind']),view=EncounterView(interaction.user.id,row['floor'],row['kind']),ephemeral=True)

class EncounterView(discord.ui.View):
    def __init__(self,uid,floor,kind):
        super().__init__(timeout=900)
        self.uid,self.floor,self.kind=uid,floor,kind
        options=([('Iron Door','iron','⚔️'),('Golden Door','gold','🪙'),('Runic Door','rune','✨')]
                 if kind=='doors' else [('King’s Chest','gold','🪙'),('Smith’s Chest','material','🔨'),('Healer’s Chest','supply','💚')])
        for label,value,emoji in options:
            btn=discord.ui.Button(label=label,emoji=emoji,style=discord.ButtonStyle.primary)
            async def choose(i,choice=value): await resolve_encounter(i,self.floor,self.kind,choice)
            btn.callback=choose
            self.add_item(btn)
        skip=discord.ui.Button(label='Leave Safely',emoji='🚪',style=discord.ButtonStyle.secondary,row=1)
        async def leave(i): await resolve_encounter(i,self.floor,self.kind,'skip')
        skip.callback=leave;self.add_item(skip)
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await ui_reply(i, 'This is not your encounter.',ephemeral=True);return False
        return True

async def resolve_encounter(interaction,floor,kind,choice):
    async with lock:
        uid=interaction.user.id
        row=conn.execute('SELECT * FROM dungeon_encounters WHERE user_id=? AND floor=? AND kind=?',(uid,floor,kind)).fetchone()
        if not row or row['status']!='pending':
            return await ui_reply(interaction, 'This encounter has already been resolved.',ephemeral=True)
        if get_battle(uid):return await ui_reply(interaction, 'Finish your current battle first.',ephemeral=True)
        gold=mats=0;blessing=None
        if kind=='doors':
            if choice=='iron': gold,mats=0,0
            elif choice=='gold': gold,mats=350+floor,4
            elif choice=='rune': blessing='knight'
            elif choice!='skip':return await ui_reply(interaction, 'Invalid choice.',ephemeral=True)
        else:
            if choice=='gold':gold=350
            elif choice=='material':mats=8
            elif choice=='supply':blessing='supplies'
            elif choice!='skip':return await ui_reply(interaction, 'Invalid choice.',ephemeral=True)
        # One atomic claim; repeated clicks cannot collect rewards twice.
        updated=conn.execute("UPDATE dungeon_encounters SET status='claimed',choice=? WHERE user_id=? AND floor=? AND kind=? AND status='pending'",(choice,uid,floor,kind))
        if updated.rowcount!=1:
            return await ui_reply(interaction, 'Already claimed.',ephemeral=True)
        if kind=='doors' and choice=='iron':
            conn.execute('INSERT OR IGNORE INTO elite_trials(user_id,floor) VALUES(?,?)',(uid,floor))
        if blessing:
            conn.execute('UPDATE players SET blessing=?,blessing_floors=3 WHERE user_id=?',(blessing,uid))
        conn.execute('UPDATE players SET gold=gold+?,materials=materials+? WHERE user_id=?',(gold,mats,uid))
        conn.commit()
    text=('You leave the chamber safely.' if choice=='skip' else
          f'You received **{gold} gold**, **{mats} materials**.' + (f' **{blessing.title()} blessing** for three cleared floors.' if blessing else ''))
    if kind=='doors' and choice=='iron':
        return await elite_panel(interaction,floor)
    await ui_reply(interaction, embed=discord.Embed(title='📜 Encounter Resolved',description=text,color=discord.Color.gold()),view=ContinueView(uid),ephemeral=True)

ELITE_CUES=('heavy','reckless','guard')
ELITE_CORRECT={'heavy':'defend','reckless':'attack','guard':'special'}

async def elite_panel(interaction,floor):
    row=conn.execute('SELECT * FROM elite_trials WHERE user_id=? AND floor=?',(interaction.user.id,floor)).fetchone()
    if not row or row['completed']:
        return await ui_reply(interaction, 'This elite trial is already complete.',ephemeral=True)
    turn=row['turn'];cue=ELITE_CUES[(turn+floor//10)%3]
    embed=discord.Embed(title=f'🛡️ Iron Guardian — Floor {floor}',description='Optional three-round tactical encounter. Read the guardian’s intention. Two correct counters earn the bonus; there is no HP or attempt penalty for failure.\n\n'+INTENT_TEXT[cue],color=discord.Color.dark_gold())
    embed.add_field(name='Round',value=f'{turn+1}/3')
    embed.add_field(name='Successful counters',value=f'{row["successes"]}/3')
    embed.set_image(url='attachment://dungeon-panel.png')
    await ui_reply(interaction, embed=embed,file=panel_file('elite'),view=EliteView(interaction.user.id,floor),ephemeral=True)

class EliteView(discord.ui.View):
    def __init__(self,uid,floor):super().__init__(timeout=900);self.uid=uid;self.floor=floor
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await ui_reply(i, 'This is another adventurer’s trial.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Attack',emoji='⚔️',style=discord.ButtonStyle.primary)
    async def attack(self,i,b):await elite_action(i,self.floor,'attack')
    @discord.ui.button(label='Defend',emoji='🛡️',style=discord.ButtonStyle.secondary)
    async def defend(self,i,b):await elite_action(i,self.floor,'defend')
    @discord.ui.button(label='Special',emoji='✨',style=discord.ButtonStyle.primary)
    async def special(self,i,b):await elite_action(i,self.floor,'special')

async def elite_action(interaction,floor,action):
    async with lock:
        uid=interaction.user.id
        row=conn.execute('SELECT * FROM elite_trials WHERE user_id=? AND floor=?',(uid,floor)).fetchone()
        if not row or row['completed']:
            return await ui_reply(interaction, 'This trial has already ended.',ephemeral=True)
        turn=row['turn'];cue=ELITE_CUES[(turn+floor//10)%3]
        correct=action==ELITE_CORRECT[cue]
        successes=row['successes']+int(correct)
        complete=turn+1==3
        conn.execute('UPDATE elite_trials SET turn=?,successes=?,completed=? WHERE user_id=? AND floor=?',(turn+1,successes,int(complete),uid,floor))
        gold=mats=0
        if complete and successes>=2:
            gold,mats=450+floor*2,5+floor//20
            conn.execute('UPDATE players SET gold=gold+?,materials=materials+? WHERE user_id=?',(gold,mats,uid))
        conn.commit()
    if complete:
        message=(f'Guardian defeated! **+{gold} gold and +{mats} materials.**' if successes>=2 else
                 'The guardian holds the Iron Door. No bonus this time, but your dungeon progress is safe.')
        return await ui_reply(interaction, embed=discord.Embed(title='⚔️ Iron Trial Complete',description=message,color=discord.Color.gold()),view=ContinueView(uid),ephemeral=True)
    await elite_panel(interaction,floor)

class ContinueView(discord.ui.View):
    def __init__(self,uid):super().__init__(timeout=900);self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await ui_reply(i, 'This is not your fighter.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Next Floor',emoji='⚔️',style=discord.ButtonStyle.primary)
    async def next(self,i,b):await dungeon.callback(i)
    @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary)
    async def castle(self,i,b):await open_castle(i)

async def merchant_menu(interaction):
    p=get_player(interaction.user.id)
    if not p:return await ui_reply(interaction, 'Create a fighter first.',ephemeral=True)
    floor=(p['floor']//10)*10
    if floor<10 or floor>=100:
        return await ui_reply(interaction, 'The Wandering Merchant visits after boss floors 10–90.',ephemeral=True)
    if get_battle(interaction.user.id):
        return await ui_reply(interaction, 'Finish your battle before visiting the merchant.',ephemeral=True)
    options=[]
    for key,(name,cost,_,desc) in MERCHANT_ITEMS.items():
        bought=conn.execute('SELECT 1 FROM merchant_purchases WHERE user_id=? AND floor=? AND item=?',(interaction.user.id,floor,key)).fetchone()
        options.append(f'{"~~" if bought else ""}**{name}** — {cost:,} gold: {desc}{"~~ (Purchased)" if bought else ""}')
    embed=discord.Embed(title=f'🧙 Wandering Merchant — Floor {floor}',description='\n'.join(options)+f'\n\nYour gold: **{p["gold"]:,}**',color=discord.Color.from_rgb(135,90,43))
    embed.set_image(url='attachment://dungeon-panel.png')
    await ui_reply(interaction, embed=embed,file=panel_file('merchant'),view=MerchantView(interaction.user.id,floor),ephemeral=True)

class MerchantView(discord.ui.View):
    def __init__(self,uid,floor):
        super().__init__(timeout=900);self.uid=uid;self.floor=floor
        select=discord.ui.Select(placeholder='Purchase one item (each item once per merchant)',options=[discord.SelectOption(label=v[0],value=k,description=f'{v[1]:,} gold') for k,v in MERCHANT_ITEMS.items()])
        async def buy(i):await purchase_merchant(i,self.floor,select.values[0])
        select.callback=buy;self.add_item(select)
        self.add_item(BackToCastle(row=1))
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await ui_reply(i, 'This merchant panel is not yours.',ephemeral=True);return False
        return True

async def purchase_merchant(interaction,floor,key):
    if key not in MERCHANT_ITEMS:return await ui_reply(interaction, 'Invalid item.',ephemeral=True)
    name,cost,_,_=MERCHANT_ITEMS[key]
    async with lock:
        uid=interaction.user.id;p=get_player(uid)
        if not p or (p['floor']//10)*10!=floor or get_battle(uid):
            return await ui_reply(interaction, 'Merchant no longer available.',ephemeral=True)
        if p['gold']<cost:return await ui_reply(interaction, f'Need {cost:,} gold; you have {p["gold"]:,}.',ephemeral=True)
        if conn.execute('SELECT 1 FROM merchant_purchases WHERE user_id=? AND floor=? AND item=?',(uid,floor,key)).fetchone():
            return await ui_reply(interaction, 'You already purchased this item at this merchant.',ephemeral=True)
        conn.execute('INSERT INTO merchant_purchases(user_id,floor,item) VALUES(?,?,?)',(uid,floor,key))
        gold=mats=0
        if key=='forge':mats=8
        elif key=='relic':gold,mats=300,5
        elif key in ('supplies','knight','berserker'):
            conn.execute('UPDATE players SET blessing=?,blessing_floors=3 WHERE user_id=?',(key,uid))
        conn.execute('UPDATE players SET gold=gold-?+?,materials=materials+? WHERE user_id=?',(cost,gold,mats,uid))
        conn.commit()
    await ui_reply(interaction, f'🧙 Purchased **{name}** for {cost:,} gold. +{gold} gold, +{mats} materials. Blessings, if any, last three cleared floors.',ephemeral=True)

RAID_BOSSES=['Stone Colossus','Dread Wyvern','Crypt Behemoth','Iron Titan','Frost Wyrm','Ashen Giant','Ancient Dragon']

def raid_day():return event_day()
def ensure_raid(day):
    conn.execute('INSERT OR IGNORE INTO world_raids(day,hp,max_hp) VALUES(?,?,?)',(day,20000,20000))
    return conn.execute('SELECT * FROM world_raids WHERE day=?',(day,)).fetchone()

async def raid_menu(interaction):
    if event_state()!='active':return await ui_reply(interaction, 'World raids run during the seven-day dungeon event.',ephemeral=True)
    if not get_player(interaction.user.id):return await ui_reply(interaction, 'Create a fighter first.',ephemeral=True)
    async with lock:
        day=raid_day();raid=ensure_raid(day)
        record=conn.execute('SELECT * FROM raid_participation WHERE user_id=? AND day=?',(interaction.user.id,day)).fetchone()
        conn.commit()
    tries=record['attempts'] if record else 0
    embed=discord.Embed(title=f'🐉 Day {day} World Raid — {RAID_BOSSES[(day-1)%7]}',description='An asynchronous kingdom-wide raid. Each fighter gets three short attacks per day. Damage is standardized; dungeon equipment does not affect raid power.\n\nRaid victory grants a bonus to all participants who claim it.',color=discord.Color.dark_red())
    embed.add_field(name='Raid HP',value=f'{raid["hp"]:,} / {raid["max_hp"]:,}')
    embed.add_field(name='Your attempts',value=f'{3-tries}/3 remaining')
    embed.add_field(name='Your damage',value=f'{record["damage"]:,}' if record else '0')
    if tries<3 and raid['hp']>0:
        cue=ELITE_CUES[(day+tries)%3]
        embed.add_field(name='Guardian’s intention',value=INTENT_TEXT[cue],inline=False)
    embed.set_image(url='attachment://dungeon-panel.png')
    await ui_reply(interaction, embed=embed,file=panel_file('raid'),view=RaidView(interaction.user.id),ephemeral=True)

class RaidView(discord.ui.View):
    def __init__(self,uid):super().__init__(timeout=900);self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await ui_reply(i, 'This raid panel is not yours.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Strike',emoji='⚔️',style=discord.ButtonStyle.primary)
    async def attack(self,i,b):await raid_attack(i,'attack')
    @discord.ui.button(label='Guard',emoji='🛡️',style=discord.ButtonStyle.primary)
    async def guard(self,i,b):await raid_attack(i,'defend')
    @discord.ui.button(label='Pierce',emoji='✨',style=discord.ButtonStyle.secondary)
    async def pierce(self,i,b):await raid_attack(i,'special')
    @discord.ui.button(label='Claim Victory Bonus',emoji='🏆',style=discord.ButtonStyle.primary)
    async def claim(self,i,b):await raid_claim(i)
    @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary)
    async def castle(self,i,b):await open_castle(i)

async def raid_attack(interaction,action):
    async with lock:
        day=raid_day();uid=interaction.user.id
        if event_state()!='active':return await ui_reply(interaction, 'The raid has ended.',ephemeral=True)
        if not get_player(uid):return await ui_reply(interaction, 'Create a fighter first.',ephemeral=True)
        raid=ensure_raid(day)
        if raid['hp']<=0:return await ui_reply(interaction, 'The kingdom has defeated this boss! Claim your victory bonus.',ephemeral=True)
        conn.execute('INSERT OR IGNORE INTO raid_participation(user_id,day) VALUES(?,?)',(uid,day))
        row=conn.execute('SELECT * FROM raid_participation WHERE user_id=? AND day=?',(uid,day)).fetchone()
        if row['attempts']>=3:return await ui_reply(interaction, 'All three raid attempts used today.',ephemeral=True)
        # Every player sees the same learnable telegraphs and equal potential damage.
        cue=ELITE_CUES[(day+row['attempts'])%3]
        correct=action==ELITE_CORRECT[cue]
        damage=min(raid['hp'],650 if correct else 400)
        conn.execute('UPDATE world_raids SET hp=MAX(0,hp-?) WHERE day=?',(damage,day))
        conn.execute('UPDATE raid_participation SET attempts=attempts+1,damage=damage+? WHERE user_id=? AND day=?',(damage,uid,day))
        conn.execute('UPDATE players SET gold=gold+100,materials=materials+1 WHERE user_id=?',(uid,))
        conn.commit()
        left=raid['hp']-damage
    await ui_reply(interaction, f'⚔️ {"Perfect counter!" if correct else "The boss resisted your move."} You dealt **{damage}** raid damage! +100 gold and +1 material. Boss HP: **{left:,}**. You have **{2-row["attempts"]}** attacks remaining.',view=RaidView(uid),ephemeral=True)

async def raid_claim(interaction):
    async with lock:
        day=raid_day();uid=interaction.user.id
        if not 1<=day<=7:return await ui_reply(interaction, 'Raid rewards are available only during the event.',ephemeral=True)
        raid=ensure_raid(day)
        row=conn.execute('SELECT * FROM raid_participation WHERE user_id=? AND day=?',(uid,day)).fetchone()
        if not row or row['attempts']<1:return await ui_reply(interaction, 'Participate in this raid first.',ephemeral=True)
        if raid['hp']>0:return await ui_reply(interaction, f'The boss still has {raid["hp"]:,} HP.',ephemeral=True)
        if row['victory_claimed']:return await ui_reply(interaction, 'Victory bonus already claimed.',ephemeral=True)
        conn.execute('UPDATE raid_participation SET victory_claimed=1 WHERE user_id=? AND day=?',(uid,day))
        conn.execute('UPDATE players SET gold=gold+350,materials=materials+5 WHERE user_id=?',(uid,))
        conn.commit()
    await ui_reply(interaction, '🏆 World Boss defeated! Your share: **350 gold and 5 materials**.',ephemeral=True)

# Player-facing interface: /play is the sole slash command. Existing command
# callbacks remain as internal handlers, preserving the same game rules.

def castle_embed(title='THE KINGDOM\'S GATE', detail='Choose your path from the castle hall.'):
    e=discord.Embed(title=f'🏰 DUNGEON KOMBAT | {title}',description=detail,color=discord.Color.from_rgb(111,74,43))
    e.set_image(url='attachment://dungeon-panel.png')
    return e

async def open_castle(interaction):
    view=PlayMenu(interaction.user.id) if get_player(interaction.user.id) else RegistrationGate()
    await ui_reply(interaction, embed=castle_embed(),file=panel_file('event'),view=view,ephemeral=True)

class RegistrationGate(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
    @discord.ui.button(label='Create Your Fighter', emoji='⚔️', style=discord.ButtonStyle.primary)
    async def create(self, interaction, button):
        if get_player(interaction.user.id):
            return await open_castle(interaction)
        await interaction.response.send_modal(CreateFighter())

class KingdomEntrance(discord.ui.View):
    """Persistent shared entry button. Each click opens a private independent UI."""
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label='Enter the Kingdom', emoji='🏰', style=discord.ButtonStyle.primary, custom_id='dk:v14:enter_kingdom')
    async def enter(self, interaction, button):
        view=PlayMenu(interaction.user.id) if get_player(interaction.user.id) else RegistrationGate()
        await interaction.response.send_message(embed=castle_embed('YOUR ADVENTURE', 'Create your fighter or choose your next destination.'),file=panel_file('event'),view=view,ephemeral=True)

class OwnedView(discord.ui.View):
    def __init__(self,uid,timeout=900):
        super().__init__(timeout=timeout);self.uid=uid
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.uid:
            await ui_reply(interaction, 'This menu belongs to another adventurer. Open your own with `/play`.',ephemeral=True)
            return False
        return True

class BackToCastle(discord.ui.Button):
    def __init__(self,row=4):
        super().__init__(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary,row=row)
    async def callback(self,interaction):
        await open_castle(interaction)

class ActionSelect(discord.ui.Select):
    def __init__(self,uid,kind,options,placeholder):
        super().__init__(placeholder=placeholder,options=[discord.SelectOption(label=label,value=value,description=desc) for label,value,desc in options],row=0)
        self.uid=uid;self.kind=kind
    async def callback(self,interaction):
        if interaction.user.id!=self.uid:
            return await ui_reply(interaction, 'This is another fighter’s menu.',ephemeral=True)
        value=self.values[0]
        if self.kind=='stats':
            return await interaction.response.send_modal(AllocateModal(value))
        if self.kind=='activity':
            names={'mine':'Gold Mine','crystal':'Crystal Cavern','ruins':'Ancient Ruins'}
            return await activities.callback(interaction,app_commands.Choice(name=names[value],value=value))
        if self.kind=='skill':
            return await skill.callback(interaction,app_commands.Choice(name=value,value=value))
        if self.kind=='enchant':
            return await enchant.callback(interaction,app_commands.Choice(name=value,value=value))
        if self.kind=='advance':
            return await advance.callback(interaction,app_commands.Choice(name=value.title(),value=value))
        if self.kind=='upgrade':
            return await upgrade.callback(interaction,app_commands.Choice(name=value.title(),value=value))
        if self.kind=='appearance':
            return await customize.callback(interaction)

class AllocateModal(discord.ui.Modal,title='Allocate Attribute Points'):
    amount=discord.ui.TextInput(label='Number of points (1–30)',placeholder='5',min_length=1,max_length=2)
    def __init__(self,attribute):
        super().__init__();self.attribute=attribute
    async def on_submit(self,interaction):
        try: n=int(str(self.amount))
        except ValueError: n=0
        if not 1<=n<=30:
            return await ui_reply(interaction, 'Enter a whole number between 1 and 30.',ephemeral=True)
        await allocate.callback(interaction,app_commands.Choice(name=self.attribute.title(),value=self.attribute),n)

class ActionsView(OwnedView):
    def __init__(self,uid,kind):
        super().__init__(uid)
        self.kind=kind
        configs={
            'stats':('Spend attribute points',[(x.title(),x,'Improve '+x.title()) for x in STAT_NAMES]),
            'activity':('Choose resource expedition', [('Ancient Ruins','ruins','110 gold + 2 materials'),('Gold Mine','mine','80 gold'),('Crystal Cavern','crystal','2 materials')]),
            'skill':('Choose permanent specialization',[('Berserker','Berserker','Attack-focused fighter'),('Guardian','Guardian','Defence-focused fighter'),('Arcanist','Arcanist','Energy-focused fighter')]),
            'enchant':('Choose enchantment',[('Flame','Flame','+3.5% attack'),('Ward','Ward','+4.5% HP')]),
            'advance':('Choose advanced forging',[('Weapon','weapon','Requires +10 weapon and Floor 50'),('Armour','armor','Requires +10 armour and Floor 50')]),
            'upgrade':('Choose basic upgrade',[('Weapon','weapon','Up to +10'),('Armour','armor','Up to +10')]),
        }
        label,options=configs[kind]
        self.add_item(ActionSelect(uid,kind,options,label))
        self.add_item(BackToCastle(row=1))

class FighterMenu(OwnedView):
    @discord.ui.button(label='View Fighter',emoji='🛡️',style=discord.ButtonStyle.primary,row=0)
    async def fighter_button(self,i,b): await fighter.callback(i)
    @discord.ui.button(label='Allocate Stats',emoji='📊',style=discord.ButtonStyle.secondary,row=0)
    async def stats_button(self,i,b): await open_actions(i,'stats')
    @discord.ui.button(label='Appearance & Weapon',emoji='⚔️',style=discord.ButtonStyle.secondary,row=1)
    async def customize_button(self,i,b): await customize.callback(i)
    @discord.ui.button(label='Choose Skill',emoji='🌳',style=discord.ButtonStyle.secondary,row=1)
    async def skill_button(self,i,b): await open_actions(i,'skill')
    @discord.ui.button(label='Reset Stats',emoji='🔄',style=discord.ButtonStyle.primary,row=2)
    async def respec_button(self,i,b): await ui_reply(i, 'Spend one respec token and refund all allocated points?',view=ConfirmRespec(self.uid),ephemeral=True)
    @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary,row=3)
    async def back(self,i,b): await open_castle(i)

class ConfirmRespec(OwnedView):
    @discord.ui.button(label='Confirm Respec',style=discord.ButtonStyle.primary)
    async def confirm(self,i,b): await respec.callback(i)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,i,b): await open_castle(i)

class ForgeMenu(OwnedView):
    @discord.ui.button(label='Basic Upgrades',emoji='🔨',style=discord.ButtonStyle.primary,row=0)
    async def basic(self,i,b): await workshop.callback(i)
    @discord.ui.button(label='Advanced Forging',emoji='🛡️',style=discord.ButtonStyle.secondary,row=0)
    async def advanced(self,i,b): await open_actions(i,'advance')
    @discord.ui.button(label='Enchant Equipment',emoji='✨',style=discord.ButtonStyle.secondary,row=1)
    async def enchant_button(self,i,b): await open_actions(i,'enchant')
    @discord.ui.button(label='Treasury & Costs',emoji='🪙',style=discord.ButtonStyle.secondary,row=1)
    async def wallet_button(self,i,b): await wallet.callback(i)
    @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b): await open_castle(i)

class GatherMenu(OwnedView):
    @discord.ui.button(label='Gather Resources',emoji='⛏️',style=discord.ButtonStyle.primary,row=0)
    async def gather(self,i,b): await open_actions(i,'activity')
    @discord.ui.button(label='Check Stamina',emoji='⏳',style=discord.ButtonStyle.secondary,row=0)
    async def stamina(self,i,b): await stamina_status.callback(i)
    @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b): await open_castle(i)

async def open_actions(i,kind):
    descriptions={
        'stats':'Select an attribute, then enter how many points to spend.',
        'activity':'Spend one stamina to earn the selected rewards.',
        'skill':'Specializations unlock after Floor 5. Your choice is permanent.',
        'enchant':'Enchantment unlocks after Floor 30 and costs 4,000 gold and 25 materials.',
        'advance':'Advanced forging unlocks at Floor 50 after reaching +10.',
        'upgrade':'Improve equipment using gold and materials.',
    }
    await ui_reply(i, embed=discord.Embed(title='📜 '+kind.title(),description=descriptions[kind],color=discord.Color.from_rgb(124,89,50)),view=ActionsView(i.user.id,kind),ephemeral=True)

class PlayMenu(OwnedView):
    @discord.ui.button(label='Enter Dungeon',emoji='⚔️',style=discord.ButtonStyle.secondary,row=0)
    async def enter(self,i,b): await dungeon.callback(i)
    @discord.ui.button(label='My Fighter',emoji='🛡️',style=discord.ButtonStyle.secondary,row=0)
    async def hero(self,i,b): await ui_reply(i, embed=discord.Embed(title='🛡️ Fighter Hall',description='Manage your character, stats, specialization and appearance.',color=discord.Color.from_rgb(124,89,50)),view=FighterMenu(self.uid),ephemeral=True)
    @discord.ui.button(label='Blacksmith',emoji='🔨',style=discord.ButtonStyle.secondary,row=0)
    async def forge(self,i,b): await ui_reply(i, embed=discord.Embed(title='🔨 Royal Blacksmith',description='Upgrade and enchant your equipment.',color=discord.Color.from_rgb(124,89,50)),view=ForgeMenu(self.uid),ephemeral=True)
    @discord.ui.button(label='Gather Resources',emoji='⛏️',style=discord.ButtonStyle.secondary,row=1)
    async def gather(self,i,b): await ui_reply(i, embed=discord.Embed(title='⛏️ The Kingdom Outskirts',description='Earn gold and materials. Stamina regenerates over time.',color=discord.Color.from_rgb(124,89,50)),view=GatherMenu(self.uid),ephemeral=True)
    @discord.ui.button(label='Treasury',emoji='🪙',style=discord.ButtonStyle.secondary,row=1)
    async def treasury(self,i,b): await wallet.callback(i)
    @discord.ui.button(label='Championship Arena',emoji='🏟️',style=discord.ButtonStyle.secondary,row=1)
    async def arena_button(self,i,b): await ARENA_COMMAND.callback(i)
    @discord.ui.button(label='Rankings',emoji='🏆',style=discord.ButtonStyle.secondary,row=2)
    async def rankings(self,i,b): await leaderboard.callback(i)
    @discord.ui.button(label='Arena Score',emoji='🎯',style=discord.ButtonStyle.secondary,row=2)
    async def score(self,i,b): await ARENA_SCORE_COMMAND.callback(i)
    @discord.ui.button(label='Rules & Dates',emoji='📜',style=discord.ButtonStyle.secondary,row=2)
    async def rules(self,i,b): await event.callback(i)
    @discord.ui.button(label='World Raid',emoji='🐉',style=discord.ButtonStyle.secondary,row=3)
    async def raid(self,i,b): await raid_menu(i)
    @discord.ui.button(label='Wandering Merchant',emoji='🪙',style=discord.ButtonStyle.secondary,row=3)
    async def merchant(self,i,b): await merchant_menu(i)
    @discord.ui.button(label='Return to Castle',emoji='🏰',style=discord.ButtonStyle.secondary,row=4)
    async def create(self,i,b): await open_castle(i)

ARENA_COMMAND=bot.tree.get_command('arena')
ARENA_SCORE_COMMAND=bot.tree.get_command('arena-score')

@bot.tree.command(name='play',description='Open the Dungeon Kombat castle gate and all game functions')
async def play(interaction:discord.Interaction):
    await interaction.response.send_message(embed=castle_embed('THE KINGDOM ENTRANCE', 'All adventurers can use the button below. Your character and menus open privately, so players never control each other’s progress.'),file=panel_file('event'),view=KingdomEntrance())

# The only visible slash command is /play. All original handlers remain
# callable by the UI, including the separately installed arena module.
for _cmd in list(bot.tree.get_commands()):
    if _cmd.name!='play': bot.tree.remove_command(_cmd.name)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} | DB: {DB_PATH} | Event start: {START_DATE}')

async def setup_commands():
    if GUILD_ID:
        guild=discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f'Synced commands to guild {GUILD_ID}')
    else:
        await bot.tree.sync()
        print('Synced global commands (may take time to appear)')

@bot.event
async def setup_hook():
    bot.add_view(KingdomEntrance())
    await setup_commands()

if __name__=='__main__':
    if not TOKEN:
        raise SystemExit('Set DISCORD_TOKEN in Railway variables or local environment.')
    bot.run(TOKEN)
