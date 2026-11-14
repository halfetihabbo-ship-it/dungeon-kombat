from pathlib import Path
p=Path('/mnt/data/dk_v13/main.py')
s=p.read_text()
needle="conn.commit()\n\nintents = discord.Intents.default()"
replacement="""# v13: additive, idempotent world events. Existing players and battles are retained.
conn.executescript('''
CREATE TABLE IF NOT EXISTS dungeon_encounters (
 user_id INTEGER NOT NULL, floor INTEGER NOT NULL, kind TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', choice TEXT,
 PRIMARY KEY(user_id,floor,kind)
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

intents = discord.Intents.default()"""
assert needle in s;s=s.replace(needle,replacement)
needle="def damage_reduction(defense):"
new='''# Adventure encounters are first-clear only. No extra dungeon attempts are spent.
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

'''
assert needle in s;s=s.replace(needle,new+needle)
# migration new blessing fields
needle="'armor_advanced':'INTEGER NOT NULL DEFAULT 0'},"
s=s.replace(needle,"'armor_advanced':'INTEGER NOT NULL DEFAULT 0', 'blessing':\"TEXT NOT NULL DEFAULT 'None'\",'blessing_floors':'INTEGER NOT NULL DEFAULT 0'},")
# add blessing to stats
needle="    return hp,atk,defense,speed,energy\n"
s=s.replace(needle,"""    if p['blessing_floors']>0:
        if p['blessing']=='supplies': hp=round(hp*1.05)
        elif p['blessing']=='knight': defense=round(defense*1.08)
        elif p['blessing']=='berserker': atk=round(atk*1.08)
    return hp,atk,defense,speed,energy
""")
# embed telegraphs
needle="    if b['enemy_charge']:\n        e.add_field(name='⚠️ Warning', value='Enemy is charging a powerful attack next turn!', inline=False)"
s=s.replace(needle,"""    intent=enemy_intent(b)
    e.add_field(name='📜 Enemy Intention',value=INTENT_TEXT[intent],inline=False)
    if boss:
        phase=boss_phase(b)
        e.add_field(name='👑 Boss',value=f'{BOSS_NAMES[(b["floor"]//10)-1]} • Phase {phase}/3' + (' • Final Stand: higher damage, exposed openings' if phase==3 else ''),inline=False)""")
# enemy intent mechanics
needle="        if enemyhp > 0:\n            rng = random.Random(b['seed'] + b['turn']*157)"
s=s.replace(needle,"""        intent=enemy_intent(b)
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
            rng = random.Random(b['seed'] + b['turn']*157)""")
needle="            if charge: incoming = round(incoming*2.1)"
s=s.replace(needle,"""            if charge: incoming = round(incoming*2.1)
            elif intent=='heavy': incoming=round(incoming*1.45)
            elif intent=='reckless': incoming=round(incoming*.82)
            elif intent=='guard': incoming=round(incoming*.72)
            if boss and phase==2: incoming=round(incoming*1.07)
            elif boss and phase==3: incoming=round(incoming*1.14)""")
needle="            if b['floor'] >= 11 and b['turn'] % 5 == 0 and not poison:"
s=s.replace(needle,"            if b['floor'] >= 11 and intent=='venom' and not guard and not poison:")
# victory triggers encounter, blessing duration
needle="            if boss:\n                conn.execute('UPDATE players SET relics=relics+1 WHERE user_id=?',(interaction.user.id,))"
s=s.replace(needle,"""            kind=encounter_kind(floor)
            if kind:
                conn.execute('INSERT OR IGNORE INTO dungeon_encounters(user_id,floor,kind) VALUES(?,?,?)',(interaction.user.id,floor,kind))
                notes.append('📜 A new castle encounter awaits! Choose **Next Floor** to resolve it.')
            conn.execute('UPDATE players SET blessing_floors=MAX(0,blessing_floors-1) WHERE user_id=?',(interaction.user.id,))
            if boss:
                conn.execute('UPDATE players SET relics=relics+1 WHERE user_id=?',(interaction.user.id,))""")
# next floor intercepted
needle="        await dungeon.callback(interaction)"
s=s.replace(needle,"""        if pending_encounter(self.uid):
            await open_encounter(interaction)
        else:
            await dungeon.callback(interaction)""",1)
# dungeon start guard for pending encounter
needle="        b = get_battle(interaction.user.id)\n        if b:\n            embed = battle_embed"
s=s.replace(needle,"""        b = get_battle(interaction.user.id)
        if not b and pending_encounter(interaction.user.id):
            return await open_encounter(interaction)
        if b:
            embed = battle_embed""",1)
# new functions before castle menu
needle="# Player-facing interface: /play is the sole slash command. Existing command"
assert needle in s
new='''# ----- v13 medieval encounters, merchant and cooperative world raids -----
def encounter_embed(row):
    floor,kind=row['floor'],row['kind']
    if kind=='doors':
        desc=('Three ancient doors stand before you. Each promises a different path. '
              'Choose once; the result is saved. You may also leave safely.\\n\\n'
              '🛡️ **Iron Door:** face an elite guardian for extra gold and materials.\\n'
              '🪙 **Golden Door:** collect a guaranteed treasury reward.\\n'
              '✨ **Runic Door:** receive a temporary combat blessing.')
        title=f'🚪 Floor {floor} — The Three Doors'
    else:
        title=f'🗝️ Floor {floor} — The Forgotten Treasury'
        desc=('Choose exactly one chest. Rewards are guaranteed, with no hidden traps.\\n\\n'
              '🪙 King’s Chest — 350 gold\\n🔨 Smith’s Chest — 8 materials\\n'
              '💚 Healer’s Chest — a three-battle +5% HP blessing')
    return discord.Embed(title=title,description=desc,color=discord.Color.from_rgb(137,94,48))

async def open_encounter(interaction):
    row=pending_encounter(interaction.user.id)
    if not row: return await dungeon.callback(interaction)
    await interaction.response.send_message(embed=encounter_embed(row),view=EncounterView(interaction.user.id,row['floor'],row['kind']),ephemeral=True)

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
            await i.response.send_message('This is not your encounter.',ephemeral=True);return False
        return True

async def resolve_encounter(interaction,floor,kind,choice):
    async with lock:
        uid=interaction.user.id
        row=conn.execute('SELECT * FROM dungeon_encounters WHERE user_id=? AND floor=? AND kind=?',(uid,floor,kind)).fetchone()
        if not row or row['status']!='pending':
            return await interaction.response.send_message('This encounter has already been resolved.',ephemeral=True)
        if get_battle(uid):return await interaction.response.send_message('Finish your current battle first.',ephemeral=True)
        gold=mats=0;blessing=None
        if kind=='doors':
            if choice=='iron': gold,mats=450+floor*2,5+floor//20
            elif choice=='gold': gold,mats=350+floor,4
            elif choice=='rune': blessing='knight'
            elif choice!='skip':return await interaction.response.send_message('Invalid choice.',ephemeral=True)
        else:
            if choice=='gold':gold=350
            elif choice=='material':mats=8
            elif choice=='supply':blessing='supplies'
            elif choice!='skip':return await interaction.response.send_message('Invalid choice.',ephemeral=True)
        # One atomic claim; repeated clicks cannot collect rewards twice.
        updated=conn.execute("UPDATE dungeon_encounters SET status='claimed',choice=? WHERE user_id=? AND floor=? AND kind=? AND status='pending'",(choice,uid,floor,kind))
        if updated.rowcount!=1:
            return await interaction.response.send_message('Already claimed.',ephemeral=True)
        if blessing:
            conn.execute('UPDATE players SET blessing=?,blessing_floors=3 WHERE user_id=?',(blessing,uid))
        conn.execute('UPDATE players SET gold=gold+?,materials=materials+? WHERE user_id=?',(gold,mats,uid))
        conn.commit()
    text=('You leave the chamber safely.' if choice=='skip' else
          f'You received **{gold} gold**, **{mats} materials**.' + (f' **{blessing.title()} blessing** for three cleared floors.' if blessing else ''))
    await interaction.response.send_message(embed=discord.Embed(title='📜 Encounter Resolved',description=text,color=discord.Color.gold()),view=ContinueView(uid),ephemeral=True)

class ContinueView(discord.ui.View):
    def __init__(self,uid):super().__init__(timeout=900);self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await i.response.send_message('This is not your fighter.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Next Floor',emoji='⚔️',style=discord.ButtonStyle.success)
    async def next(self,i,b):await dungeon.callback(i)
    @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary)
    async def castle(self,i,b):await open_castle(i)

async def merchant_menu(interaction):
    p=get_player(interaction.user.id)
    if not p:return await interaction.response.send_message('Create a fighter first.',ephemeral=True)
    floor=(p['floor']//10)*10
    if floor<10 or floor>=100:
        return await interaction.response.send_message('The Wandering Merchant visits after boss floors 10–90.',ephemeral=True)
    if get_battle(interaction.user.id):
        return await interaction.response.send_message('Finish your battle before visiting the merchant.',ephemeral=True)
    options=[]
    for key,(name,cost,_,desc) in MERCHANT_ITEMS.items():
        bought=conn.execute('SELECT 1 FROM merchant_purchases WHERE user_id=? AND floor=? AND item=?',(interaction.user.id,floor,key)).fetchone()
        options.append(f'{"~~" if bought else ""}**{name}** — {cost:,} gold: {desc}{"~~ (Purchased)" if bought else ""}')
    embed=discord.Embed(title=f'🧙 Wandering Merchant — Floor {floor}',description='\\n'.join(options)+f'\\n\\nYour gold: **{p["gold"]:,}**',color=discord.Color.from_rgb(135,90,43))
    await interaction.response.send_message(embed=embed,view=MerchantView(interaction.user.id,floor),ephemeral=True)

class MerchantView(discord.ui.View):
    def __init__(self,uid,floor):
        super().__init__(timeout=900);self.uid=uid;self.floor=floor
        select=discord.ui.Select(placeholder='Purchase one item (each item once per merchant)',options=[discord.SelectOption(label=v[0],value=k,description=f'{v[1]:,} gold') for k,v in MERCHANT_ITEMS.items()])
        async def buy(i):await purchase_merchant(i,self.floor,select.values[0])
        select.callback=buy;self.add_item(select)
        self.add_item(BackToCastle(row=1))
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await i.response.send_message('This merchant panel is not yours.',ephemeral=True);return False
        return True

async def purchase_merchant(interaction,floor,key):
    if key not in MERCHANT_ITEMS:return await interaction.response.send_message('Invalid item.',ephemeral=True)
    name,cost,_,_=MERCHANT_ITEMS[key]
    async with lock:
        uid=interaction.user.id;p=get_player(uid)
        if not p or (p['floor']//10)*10!=floor or get_battle(uid):
            return await interaction.response.send_message('Merchant no longer available.',ephemeral=True)
        if p['gold']<cost:return await interaction.response.send_message(f'Need {cost:,} gold; you have {p["gold"]:,}.',ephemeral=True)
        if conn.execute('SELECT 1 FROM merchant_purchases WHERE user_id=? AND floor=? AND item=?',(uid,floor,key)).fetchone():
            return await interaction.response.send_message('You already purchased this item at this merchant.',ephemeral=True)
        conn.execute('INSERT INTO merchant_purchases(user_id,floor,item) VALUES(?,?,?)',(uid,floor,key))
        gold=mats=0
        if key=='forge':mats=8
        elif key=='relic':gold,mats=300,5
        elif key in ('supplies','knight','berserker'):
            conn.execute('UPDATE players SET blessing=?,blessing_floors=3 WHERE user_id=?',(key,uid))
        conn.execute('UPDATE players SET gold=gold-?+?,materials=materials+? WHERE user_id=?',(cost,gold,mats,uid))
        conn.commit()
    await interaction.response.send_message(f'🧙 Purchased **{name}** for {cost:,} gold. +{gold} gold, +{mats} materials. Blessings, if any, last three cleared floors.',ephemeral=True)

RAID_BOSSES=['Stone Colossus','Dread Wyvern','Crypt Behemoth','Iron Titan','Frost Wyrm','Ashen Giant','Ancient Dragon']

def raid_day():return event_day()
def ensure_raid(day):
    conn.execute('INSERT OR IGNORE INTO world_raids(day,hp,max_hp) VALUES(?,?,?)',(day,20000,20000))
    return conn.execute('SELECT * FROM world_raids WHERE day=?',(day,)).fetchone()

async def raid_menu(interaction):
    if event_state()!='active':return await interaction.response.send_message('World raids run during the seven-day dungeon event.',ephemeral=True)
    if not get_player(interaction.user.id):return await interaction.response.send_message('Create a fighter first.',ephemeral=True)
    async with lock:
        day=raid_day();raid=ensure_raid(day)
        record=conn.execute('SELECT * FROM raid_participation WHERE user_id=? AND day=?',(interaction.user.id,day)).fetchone()
        conn.commit()
    tries=record['attempts'] if record else 0
    embed=discord.Embed(title=f'🐉 Day {day} World Raid — {RAID_BOSSES[(day-1)%7]}',description='An asynchronous kingdom-wide raid. Each fighter gets three short attacks per day. Damage is standardized; dungeon equipment does not affect raid power.\\n\\nRaid victory grants a bonus to all participants who claim it.',color=discord.Color.dark_red())
    embed.add_field(name='Raid HP',value=f'{raid["hp"]:,} / {raid["max_hp"]:,}')
    embed.add_field(name='Your attempts',value=f'{3-tries}/3 remaining')
    embed.add_field(name='Your damage',value=f'{record["damage"]:,}' if record else '0')
    embed.set_image(url='attachment://dungeon-panel.png')
    await interaction.response.send_message(embed=embed,file=panel_file('raid'),view=RaidView(interaction.user.id),ephemeral=True)

class RaidView(discord.ui.View):
    def __init__(self,uid):super().__init__(timeout=900);self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await i.response.send_message('This raid panel is not yours.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Attack World Boss',emoji='⚔️',style=discord.ButtonStyle.danger)
    async def attack(self,i,b):await raid_attack(i)
    @discord.ui.button(label='Claim Victory Bonus',emoji='🏆',style=discord.ButtonStyle.success)
    async def claim(self,i,b):await raid_claim(i)
    @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary)
    async def castle(self,i,b):await open_castle(i)

async def raid_attack(interaction):
    async with lock:
        day=raid_day();uid=interaction.user.id
        if event_state()!='active':return await interaction.response.send_message('The raid has ended.',ephemeral=True)
        if not get_player(uid):return await interaction.response.send_message('Create a fighter first.',ephemeral=True)
        raid=ensure_raid(day)
        if raid['hp']<=0:return await interaction.response.send_message('The kingdom has defeated this boss! Claim your victory bonus.',ephemeral=True)
        conn.execute('INSERT OR IGNORE INTO raid_participation(user_id,day) VALUES(?,?)',(uid,day))
        row=conn.execute('SELECT * FROM raid_participation WHERE user_id=? AND day=?',(uid,day)).fetchone()
        if row['attempts']>=3:return await interaction.response.send_message('All three raid attempts used today.',ephemeral=True)
        # Stable per-user/day/attempt: no rerolling by button spam.
        rng=random.Random(uid*13+day*311+row['attempts']*947)
        raw=600+rng.randrange(0,101)
        damage=min(raid['hp'],raw)
        conn.execute('UPDATE world_raids SET hp=MAX(0,hp-?) WHERE day=?',(damage,day))
        conn.execute('UPDATE raid_participation SET attempts=attempts+1,damage=damage+? WHERE user_id=? AND day=?',(damage,uid,day))
        conn.execute('UPDATE players SET gold=gold+100,materials=materials+1 WHERE user_id=?',(uid,))
        conn.commit()
        left=raid['hp']-damage
    await interaction.response.send_message(f'⚔️ Your fighter dealt **{damage}** standardized raid damage! +100 gold and +1 material. Boss HP: **{left:,}**. You have **{2-row["attempts"]}** attacks remaining.',ephemeral=True)

async def raid_claim(interaction):
    async with lock:
        day=raid_day();uid=interaction.user.id
        if not 1<=day<=7:return await interaction.response.send_message('Raid rewards are available only during the event.',ephemeral=True)
        raid=ensure_raid(day)
        row=conn.execute('SELECT * FROM raid_participation WHERE user_id=? AND day=?',(uid,day)).fetchone()
        if not row or row['attempts']<1:return await interaction.response.send_message('Participate in this raid first.',ephemeral=True)
        if raid['hp']>0:return await interaction.response.send_message(f'The boss still has {raid["hp"]:,} HP.',ephemeral=True)
        if row['victory_claimed']:return await interaction.response.send_message('Victory bonus already claimed.',ephemeral=True)
        conn.execute('UPDATE raid_participation SET victory_claimed=1 WHERE user_id=? AND day=?',(uid,day))
        conn.execute('UPDATE players SET gold=gold+350,materials=materials+5 WHERE user_id=?',(uid,))
        conn.commit()
    await interaction.response.send_message('🏆 World Boss defeated! Your share: **350 gold and 5 materials**.',ephemeral=True)

'''
s=s.replace(needle,new+needle)
# menu buttons limited to 5 rows, add 2 buttons on row3 (3 currently? row3 Create only)
needle="    @discord.ui.button(label='Create Fighter',emoji='🧙',style=discord.ButtonStyle.success,row=3)"
s=s.replace(needle,"""    @discord.ui.button(label='World Raid',emoji='🐉',style=discord.ButtonStyle.danger,row=3)
    async def raid(self,i,b): await raid_menu(i)
    @discord.ui.button(label='Wandering Merchant',emoji='🪙',style=discord.ButtonStyle.secondary,row=3)
    async def merchant(self,i,b): await merchant_menu(i)
    @discord.ui.button(label='Create Fighter',emoji='🧙',style=discord.ButtonStyle.success,row=4)""")
# panel_file in visuals separately
p.write_text(s)
v=Path('/mnt/data/dk_v13/visuals.py')
t=v.read_text().replace("'fighter':((96,154,193)","'raid':((180,95,63),(33,20,17),'THE KINGDOM IS UNDER SIEGE','WORLD BOSS • STAND TOGETHER'),\n             'fighter':((96,154,193)")
v.write_text(t)
