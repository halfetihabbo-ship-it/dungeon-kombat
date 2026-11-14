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
START_DATE = os.getenv('EVENT_START_DATE', '2026-11-22')  # UTC, inclusive
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
        'armor_advanced':'INTEGER NOT NULL DEFAULT 0'},
    'battles': {'special_cd':'INTEGER NOT NULL DEFAULT 0'}
}.items():
    existing={r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    for field,sqltype in fields.items():
        if field not in existing:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {field} {sqltype}')
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

class CreateFighter(discord.ui.Modal, title='Create your fighter'):
    fighter_name = discord.ui.TextInput(label='Fighter name', max_length=24, min_length=2, placeholder='Shadow Reaper')
    async def on_submit(self, interaction: discord.Interaction):
        async with lock:
            if get_player(interaction.user.id):
                return await interaction.response.send_message('You already have a fighter. Use `/fighter`.', ephemeral=True)
            if event_state() == 'ended':
                return await interaction.response.send_message('Registration has closed.', ephemeral=True)
            conn.execute('INSERT INTO players(user_id,name,color,headgear) VALUES(?,?,?,?)', (interaction.user.id, str(self.fighter_name), 'Crimson', 'Mask'))
            grant_attempts(interaction.user.id)
            conn.commit()
            p = get_player(interaction.user.id)
        await interaction.response.send_message('Your fighter is ready! Use `/customize` to change appearance, `/allocate` to spend points, and `/dungeon` to enter.', embed=info_embed(p), file=avatar_file(p), ephemeral=True)

class CustomizeView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid
        self.add_item(CustomSelect(uid, 'color', list(COLORS)))
        self.add_item(CustomSelect(uid, 'headgear', ['Mask','Helmet','Hood','None']))
        self.add_item(CustomSelect(uid, 'weapon', list(WEAPONS)))

class CustomSelect(discord.ui.Select):
    def __init__(self, uid, field, choices):
        self.uid, self.field = uid, field
        super().__init__(placeholder=f'Choose {field}', options=[discord.SelectOption(label=x, value=x) for x in choices])
    async def callback(self, interaction):
        if interaction.user.id != self.uid:
            return await interaction.response.send_message('This is not your character.', ephemeral=True)
        async with lock:
            if get_battle(self.uid):
                return await interaction.response.send_message('Finish your current battle before changing equipment.', ephemeral=True)
            p = get_player(self.uid)
            if self.field == 'weapon' and p['weapon'] != self.values[0]:
                # Weapon type switch keeps stage but resets weapon upgrades; refunded as materials.
                conn.execute('UPDATE players SET weapon=?, weapon_upgrade=0, weapon_advanced=0, materials=materials+? WHERE user_id=?', (self.values[0], p['weapon_upgrade']*2, self.uid))
            else:
                conn.execute(f'UPDATE players SET {self.field}=? WHERE user_id=?', (self.values[0], self.uid))
            conn.commit()
            p = get_player(self.uid)
        await interaction.response.send_message('Updated fighter preview:', embed=info_embed(p), file=avatar_file(p), ephemeral=True)

class BattleView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=None)
        self.uid = uid
    async def interaction_check(self, interaction):
        if interaction.user.id != self.uid:
            await interaction.response.send_message('This battle belongs to another fighter.', ephemeral=True)
            return False
        return True
    @discord.ui.button(label='Attack', emoji='⚔️', style=discord.ButtonStyle.primary)
    async def attack(self, interaction, button):
        await resolve_action(interaction, 'attack')
    @discord.ui.button(label='Defend', emoji='🛡️', style=discord.ButtonStyle.secondary)
    async def defend(self, interaction, button):
        await resolve_action(interaction, 'defend')
    @discord.ui.button(label='Special', emoji='🔥', style=discord.ButtonStyle.danger)
    async def special(self, interaction, button):
        await resolve_action(interaction, 'special')
    @discord.ui.button(label='Heal', emoji='💚', style=discord.ButtonStyle.success)
    async def heal(self, interaction, button):
        await resolve_action(interaction, 'heal')
    @discord.ui.button(label='Focus', emoji='⚡', style=discord.ButtonStyle.secondary)
    async def focus(self, interaction, button):
        await resolve_action(interaction, 'focus')

def battle_embed(p, b, message=None):
    maxhp, atk, defense, speed, maxenergy = stats(p)
    enemyhp, enemyatk, enemydef, boss = enemy_stats(b['floor'])
    e = discord.Embed(title=f'⚔️ Floor {b["floor"]} — {"BOSS" if boss else "Monster"}', description=f'**{TIERS[(b["floor"]-1)//10]}**\n{message or b["log"]}', color=discord.Color.red() if boss else discord.Color.dark_blue())
    e.add_field(name=f'🧍 {p["name"]}', value=f'❤️ {b["hp"]}/{maxhp}\n🔮 {b["energy"]}/{maxenergy}\n💚 {b["potions"]} potions')
    e.add_field(name='💀 Enemy', value=f'❤️ {b["enemy_hp"]}/{enemyhp}\n⚔️ {enemyatk} ATK\n🛡️ {enemydef} DEF' + ('\n🛡️ Shielded: normal attacks effective' if boss and b['floor']>=20 and b['turn']%5 in (1,2) else ''))
    e.add_field(name='Turn', value=f'{b["turn"]}/{30 if boss else 20} • Special cooldown: {b["special_cd"]}' + (f' • 🔥 Boss enrage +{(b["turn"]-8)*10}% incoming damage' if boss and b['turn']>8 else ''), inline=False)
    if b['enemy_charge']:
        e.add_field(name='⚠️ Warning', value='Enemy is charging a powerful attack next turn!', inline=False)
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
            return await interaction.response.send_message('No active battle. Use `/dungeon`.', ephemeral=True)
        maxhp, atk, defense, speed, maxenergy = stats(p)
        enemymax, enemyatk, enemydef, boss = enemy_stats(b['floor'])
        if action == 'special' and (b['energy'] < 28 or b['special_cd'] > 0):
            return await interaction.response.send_message('Special requires 28 energy and no active cooldown.', ephemeral=True)
        if action == 'heal' and (b['potions'] == 0 or b['hp'] >= maxhp):
            return await interaction.response.send_message('You cannot use a potion now.', ephemeral=True)
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
        if enemyhp > 0:
            rng = random.Random(b['seed'] + b['turn']*157)
            incoming = round(enemyatk*damage_reduction(defense)*rng.uniform(0.9,1.1))
            if charge: incoming = round(incoming*2.1)
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
            if b['floor'] >= 11 and b['turn'] % 5 == 0 and not poison:
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
    await interaction.response.send_message(embed=embed,file=floor_file(b2['floor'] if b2 else b['floor']),view=BattleView(interaction.user.id) if b2 else None,ephemeral=True)

@bot.tree.command(name='register',description='Create your own dungeon fighter')
async def register(interaction: discord.Interaction):
    if get_player(interaction.user.id):
        return await interaction.response.send_message('You already have a fighter. Use `/fighter`.',ephemeral=True)
    await interaction.response.send_modal(CreateFighter())

@bot.tree.command(name='fighter',description='View your fighter and avatar')
async def fighter(interaction: discord.Interaction):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await interaction.response.send_message('Register first with `/register`.',ephemeral=True)
        grant_attempts(interaction.user.id)
        grant_stamina(interaction.user.id)
        conn.commit()
        p = get_player(interaction.user.id)
    e=info_embed(p); e.set_image(url='attachment://dungeon-panel.png')
    await interaction.response.send_message(embed=e,files=[avatar_file(p),panel_file('fighter',p['floor'])],ephemeral=True)

@bot.tree.command(name='customize',description='Customize your avatar, weapon and armour colours')
async def customize(interaction: discord.Interaction):
    p = get_player(interaction.user.id)
    if not p: return await interaction.response.send_message('Use `/register` first.',ephemeral=True)
    await interaction.response.send_message('Choose an option below. The avatar preview updates after each selection. Switching weapon class resets its upgrade level and refunds 2 materials per level.',embed=info_embed(p),file=avatar_file(p),view=CustomizeView(interaction.user.id),ephemeral=True)

@bot.tree.command(name='allocate',description='Spend stat points on your fighter')
@app_commands.describe(attribute='Attribute to improve',points='How many points to spend (1–30)')
@app_commands.choices(attribute=[app_commands.Choice(name=s.title(),value=s) for s in STAT_NAMES])
async def allocate(interaction: discord.Interaction, attribute: app_commands.Choice[str], points: app_commands.Range[int,1,30]):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await interaction.response.send_message('Use `/register` first.',ephemeral=True)
        if get_battle(interaction.user.id): return await interaction.response.send_message('You cannot allocate points during combat.',ephemeral=True)
        if free_points(p)<points: return await interaction.response.send_message(f'You have only {free_points(p)} free points.',ephemeral=True)
        conn.execute(f'UPDATE players SET {attribute.value}={attribute.value}+? WHERE user_id=?',(points,interaction.user.id))
        conn.commit()
        p = get_player(interaction.user.id)
    await interaction.response.send_message(f'Allocated {points} points to {attribute.name}.',embed=info_embed(p),ephemeral=True)

@bot.tree.command(name='respec',description='Reset your allocated stats using a respec token')
async def respec(interaction: discord.Interaction):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await interaction.response.send_message('Register first.',ephemeral=True)
        if get_battle(interaction.user.id): return await interaction.response.send_message('Finish your battle first.',ephemeral=True)
        if p['respecs']<1: return await interaction.response.send_message('No respec tokens. Earn one from every boss.',ephemeral=True)
        conn.execute('UPDATE players SET vitality=0,strength=0,defence=0,agility=0,energy=0,respecs=respecs-1 WHERE user_id=?',(interaction.user.id,))
        conn.commit()
        p = get_player(interaction.user.id)
    await interaction.response.send_message('All stat points have been refunded.',embed=info_embed(p),ephemeral=True)

@bot.tree.command(name='upgrade',description='Upgrade your weapon or armour')
@app_commands.choices(item=[app_commands.Choice(name='Weapon',value='weapon'),app_commands.Choice(name='Armour',value='armor')])
async def upgrade(interaction: discord.Interaction,item:app_commands.Choice[str]):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await interaction.response.send_message('Register first.',ephemeral=True)
        if get_battle(interaction.user.id): return await interaction.response.send_message('Finish your battle first.',ephemeral=True)
        field = 'weapon_upgrade' if item.value=='weapon' else 'armor_upgrade'
        current = p[field]
        if current>=10: return await interaction.response.send_message('Already at +10. Weapon evolution at floors 20, 40, 60 and 80 preserves upgrades.',ephemeral=True)
        gold = (current+1)*150
        mats = current+1
        if p['gold']<gold or p['materials']<mats:
            return await interaction.response.send_message(f'Upgrade requires **{gold} gold** and **{mats} materials**. You have {p["gold"]} gold and {p["materials"]} materials.',ephemeral=True)
        conn.execute(f'UPDATE players SET {field}={field}+1,gold=gold-?,materials=materials-? WHERE user_id=?',(gold,mats,interaction.user.id))
        conn.commit()
        p = get_player(interaction.user.id)
    await interaction.response.send_message(f'Upgrade successful: {item.name} +{p[field]}!',embed=info_embed(p),ephemeral=True)

class WorkshopConfirm(discord.ui.View):
    def __init__(self, uid, item):
        super().__init__(timeout=120)
        self.uid, self.item = uid, item
    @discord.ui.button(label='Confirm upgrade',style=discord.ButtonStyle.success,emoji='🔨')
    async def confirm(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id!=self.uid:
            return await interaction.response.send_message('This workshop belongs to another fighter.',ephemeral=True)
        async with lock:
            p=get_player(self.uid)
            if not p or get_battle(self.uid):
                return await interaction.response.send_message('Register or finish your current battle first.',ephemeral=True)
            field='weapon_upgrade' if self.item=='weapon' else 'armor_upgrade'
            level=p[field]
            if level>=10:
                return await interaction.response.send_message('This item is already +10.',ephemeral=True)
            cost=150*(level+1); mats=level+1
            if p['gold']<cost or p['materials']<mats:
                return await interaction.response.send_message(f'Need {cost:,} gold and {mats} materials; check `/wallet`.',ephemeral=True)
            conn.execute(f'UPDATE players SET {field}={field}+1,gold=gold-?,materials=materials-? WHERE user_id=?',(cost,mats,self.uid))
            conn.commit(); p=get_player(self.uid)
        await interaction.response.edit_message(content=f'✅ {self.item.title()} upgraded to **+{p[field]}**!',embed=info_embed(p),view=None)

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
            return await interaction.response.send_message('This workshop belongs to another fighter.',ephemeral=True)
        p=get_player(self.uid)
        if not p or get_battle(self.uid):
            return await interaction.response.send_message('Register or finish your battle first.',ephemeral=True)
        level=p['weapon_upgrade' if item=='weapon' else 'armor_upgrade']
        if level>=10:
            return await interaction.response.send_message('Already fully upgraded (+10).',ephemeral=True)
        cost=150*(level+1); mats=level+1
        await interaction.response.send_message(f'🔨 **{item.title()} +{level} → +{level+1}**\nCost: **{cost:,} gold** and **{mats} materials**\nYour wallet: **{p["gold"]:,} gold**, **{p["materials"]} materials**\nConfirm to purchase (cost rechecked at purchase time).',view=WorkshopConfirm(self.uid,item),ephemeral=True)

@bot.tree.command(name='workshop',description='Open the weapon and armour upgrade workshop')
async def workshop(interaction:discord.Interaction):
    p=get_player(interaction.user.id)
    if not p: return await interaction.response.send_message('Use `/register` first.',ephemeral=True)
    e=info_embed(p);e.set_image(url='attachment://dungeon-panel.png')
    await interaction.response.send_message('🔨 **DUNGEON WORKSHOP**\nChoose which item to upgrade. Upgrades always succeed and weapon evolution preserves your +level.',embed=e,file=panel_file('workshop'),view=WorkshopView(interaction.user.id),ephemeral=True)

@bot.tree.command(name='wallet',description='View your gold, materials and next equipment upgrade costs')
async def wallet(interaction: discord.Interaction):
    p = get_player(interaction.user.id)
    if not p: return await interaction.response.send_message('Use `/register` first.',ephemeral=True)
    e = discord.Embed(title='🪙 Dungeon Wallet',description=f'**Gold:** {p["gold"]:,}\n**Materials:** {p["materials"]:,}',color=discord.Color.gold())
    for title,field in [('Weapon','weapon_upgrade'),('Armour','armor_upgrade')]:
        level=p[field]
        if level>=10: detail='MAX +10'
        else:
            g=(level+1)*150; m=level+1
            detail=f'+{level} → +{level+1}: **{g:,} gold** and **{m} materials**\n'+('✅ Affordable' if p['gold']>=g and p['materials']>=m else '❌ Not yet affordable')
        e.add_field(name=title,value=detail,inline=False)
    e.add_field(name='Advanced forging',value=f'Weapon +{p["weapon_advanced"]}/5 • Armour +{p["armor_advanced"]}/5. Unlock at Floor 50 after +10. Use `/advance`.',inline=False)
    e.set_footer(text='Boss chests award bonus resources every 10 floors. Rewards are first-clear only.')
    e.set_image(url='attachment://dungeon-panel.png')
    await interaction.response.send_message(embed=e,file=panel_file('wallet'),ephemeral=True)

@bot.tree.command(name='dungeon',description='Enter the next solo dungeon floor or resume your battle')
async def dungeon(interaction: discord.Interaction):
    async with lock:
        p = get_player(interaction.user.id)
        if not p: return await interaction.response.send_message('Use `/register` first.',ephemeral=True)
        b = get_battle(interaction.user.id)
        if b:
            embed = battle_embed(p,b,'Your battle is still in progress. Continue below.')
        else:
            if event_state()!='active':
                return await interaction.response.send_message('Dungeon attempts are available only during the seven-day event. Check `/event`.',ephemeral=True)
            p = grant_attempts(interaction.user.id)
            if p['floor']>=100: return await interaction.response.send_message('🏆 You have cleared all 100 dungeon floors!',ephemeral=True)
            if p['attempts']<=0: return await interaction.response.send_message('No attempts remaining. New attempts unlock at 00:00 UTC each event day.',ephemeral=True)
            floor = p['floor']+1
            enemyhp,_,_,_ = enemy_stats(floor)
            hp,_,_,_,energy = stats(p)
            seed = random.SystemRandom().randint(1,2**31-1)
            conn.execute('INSERT INTO battles(user_id,floor,hp,energy,potions,enemy_hp,seed) VALUES(?,?,?,?,?,?,?)',(interaction.user.id,floor,hp,energy,3,enemyhp,seed))
            conn.execute('UPDATE players SET attempts=attempts-1,spent=spent+1 WHERE user_id=?',(interaction.user.id,))
            b = get_battle(interaction.user.id)
            embed = battle_embed(p,b,'A monster blocks your path! Choose your first action.')
        conn.commit()
    await interaction.response.send_message(embed=embed,file=floor_file(b['floor']),view=BattleView(interaction.user.id),ephemeral=True)

@bot.tree.command(name='activities',description='Earn resources through daily stamina-limited activities')
@app_commands.choices(activity=[app_commands.Choice(name='Gold Mine (80 gold)',value='mine'),app_commands.Choice(name='Crystal Cavern (2 materials)',value='crystal'),app_commands.Choice(name='Ancient Ruins (110 gold, 2 materials)',value='ruins')])
async def activities(interaction:discord.Interaction,activity:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p:return await interaction.response.send_message('Register first.',ephemeral=True)
        if event_state()!='active':return await interaction.response.send_message('Activities are available during the seven-day dungeon event.',ephemeral=True)
        p=grant_stamina(interaction.user.id)
        if p['stamina']<1:return await interaction.response.send_message(f'No activity stamina left. You gain 15 at 00:00 UTC daily and +1 every 2 hours (maximum 45). {stamina_next_regen(p)}.',ephemeral=True)
        gold,mats={'mine':(80,0),'crystal':(0,2),'ruins':(110,2)}[activity.value]
        conn.execute('UPDATE players SET stamina=stamina-1,gold=gold+?,materials=materials+? WHERE user_id=?',(gold,mats,interaction.user.id))
        conn.commit()
        remaining=p['stamina']-1
        # A full pool has a paused timer. Start its 2-hour timer when first spent.
        if p['stamina'] >= STAMINA_CAP:
            conn.execute('UPDATE players SET stamina_regen_at=? WHERE user_id=?',(int(time.time()),interaction.user.id))
            conn.commit()
        updated=get_player(interaction.user.id)
    await interaction.response.send_message(f'⛏️ **{activity.name}** complete! +{gold} gold, +{mats} materials. **{remaining}** stamina remaining. 🕒 {stamina_next_regen(updated)}.',ephemeral=True)

@bot.tree.command(name='stamina',description='Check your activity stamina and next regeneration')
async def stamina_status(interaction:discord.Interaction):
    async with lock:
        p=get_player(interaction.user.id)
        if not p:
            return await interaction.response.send_message('Register first with `/register`.',ephemeral=True)
        if event_state()=='active':
            p=grant_stamina(interaction.user.id)
            conn.commit()
        message=(f'⚡ **Activity stamina: {p["stamina"]}/{STAMINA_CAP}**\n'
                 f'🕒 {stamina_next_regen(p) if event_state()=="active" else "Regeneration only during the event"}\n'
                 f'🎁 +{STAMINA_DAILY} daily at 00:00 UTC (up to cap {STAMINA_CAP}).\n'
                 f'⛏️ Use `/activities` to spend stamina.')
    await interaction.response.send_message(message,ephemeral=True)

@bot.tree.command(name='skill',description='Select one permanent skill specialization (after Floor 5)')
@app_commands.choices(path=[app_commands.Choice(name='Berserker — attack focus',value='Berserker'),app_commands.Choice(name='Guardian — survival focus',value='Guardian'),app_commands.Choice(name='Arcanist — energy focus',value='Arcanist')])
async def skill(interaction:discord.Interaction,path:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p or p['floor']<5:return await interaction.response.send_message('Clear Floor 5 first.',ephemeral=True)
        if p['skill']!='None':return await interaction.response.send_message('Your skill specialization is already selected.',ephemeral=True)
        if get_battle(interaction.user.id):return await interaction.response.send_message('Finish your battle before changing equipment.',ephemeral=True)
        conn.execute('UPDATE players SET skill=? WHERE user_id=?',(path.value,interaction.user.id));conn.commit()
    await interaction.response.send_message(f'🌳 **{path.value}** unlocked. View its bonuses with `/fighter`.',ephemeral=True)

@bot.tree.command(name='enchant',description='Enchant equipment with Flame or Ward (Floor 30+)')
@app_commands.choices(effect=[app_commands.Choice(name='Flame — +3.5% attack',value='Flame'),app_commands.Choice(name='Ward — +4.5% HP',value='Ward')])
async def enchant(interaction:discord.Interaction,effect:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p or p['floor']<30:return await interaction.response.send_message('Clear Floor 30 to unlock enchantments.',ephemeral=True)
        if p['enchantment']!='None':return await interaction.response.send_message('You already have an enchantment.',ephemeral=True)
        if get_battle(interaction.user.id):return await interaction.response.send_message('Finish your battle first.',ephemeral=True)
        if p['gold']<4000 or p['materials']<25:return await interaction.response.send_message('Requires 4,000 gold and 25 materials.',ephemeral=True)
        conn.execute('UPDATE players SET enchantment=?,gold=gold-4000,materials=materials-25 WHERE user_id=?',(effect.value,interaction.user.id));conn.commit()
    await interaction.response.send_message(f'✨ {effect.value} enchantment equipped!',ephemeral=True)

@bot.tree.command(name='advance',description='Upgrade +10 weapon or armour with advanced forging (Floor 50+)')
@app_commands.choices(item=[app_commands.Choice(name='Weapon',value='weapon'),app_commands.Choice(name='Armour',value='armor')])
async def advance(interaction:discord.Interaction,item:app_commands.Choice[str]):
    async with lock:
        p=get_player(interaction.user.id)
        if not p or p['floor']<50:return await interaction.response.send_message('Advanced forging unlocks at Floor 50.',ephemeral=True)
        if get_battle(interaction.user.id):return await interaction.response.send_message('Finish your battle first.',ephemeral=True)
        key=item.value+'_advanced';lvl=p[key]
        if p[item.value+'_upgrade']<10:return await interaction.response.send_message('Reach equipment +10 first.',ephemeral=True)
        if lvl>=5:return await interaction.response.send_message('Already at advanced +5.',ephemeral=True)
        gold,mats=advanced_cost(lvl)
        if p['gold']<gold or p['materials']<mats:return await interaction.response.send_message(f'Next upgrade costs {gold:,} gold and {mats} materials.',ephemeral=True)
        conn.execute(f'UPDATE players SET {key}={key}+1,gold=gold-?,materials=materials-? WHERE user_id=?',(gold,mats,interaction.user.id));conn.commit()
    await interaction.response.send_message(f'🔨 {item.name} advanced to **+{lvl+1}** for {gold:,} gold and {mats} materials.',ephemeral=True)

arena_system = install_arena(bot, conn, lock, get_player, event_day)

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
    await interaction.response.send_message(embed=e,file=panel_file("leaderboard"),ephemeral=False)

@bot.tree.command(name='event',description='View the tournament dates and rules')
async def event(interaction: discord.Interaction):
    e=discord.Embed(title='🦃 Dungeon Kombat: Thanksgiving Edition',description=f'**Start (UTC):** {START_DATE}\n**Duration:** 7 days\n**Status:** {event_state().title()}\n**Current day:** {event_day()}\n**Goal:** Clear as many of 100 solo dungeon floors as possible.',color=discord.Color.orange())
    e.add_field(name='Attempts',value='20 new attempts per day; unused attempts carry over. Max 140 total.')
    e.add_field(name='Combat',value='Turn-based: Attack, Defend, Special, Heal, Focus. Boss every 10 floors.')
    e.add_field(name='Ranking',value='Clear Floor 100 to unlock five Arena challenges worth 500 total points. Arena completion and score determine the champions; dungeon progress and efficiency break ties.',inline=False)
    e.add_field(name='Arena window',value='Arena is open on event days 1–9, including two days after the dungeon closes.',inline=False)
    e.add_field(name='Rewards',value='First-clear rewards and boss relics. `/activities` earns extra resources using 15 daily stamina plus +1 regeneration every 2 hours (cap 45). `/skill` unlocks after Floor 5, `/enchant` after Floor 30 and `/advance` after Floor 50.',inline=False)
    e.set_image(url="attachment://dungeon-panel.png")
    await interaction.response.send_message(embed=e,file=panel_file("event"),ephemeral=True)

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
    await setup_commands()

if __name__=='__main__':
    if not TOKEN:
        raise SystemExit('Set DISCORD_TOKEN in Railway variables or local environment.')
    bot.run(TOKEN)
