"""Deterministic, persistent Championship Arena for Dungeon Kombat.

Five four-turn challenges, 100 points each. Per-player randomised encounter
order and stances, equal maximum scores. One scored run per challenge.
"""
import discord
from visuals import arena_file, panel_file
import secrets
import random
from discord import app_commands

CHALLENGES = [
    ('The Iron Sentinel', 'Read the mechanical guardian’s wind-up and openings.',
     [('windup','guard'),('opening','strike'),('shield','pierce'),('exposed','burst')]),
    ('The Ember Wyrm', 'Manage heat and attack windows against a fire dragon.',
     [('flames','guard'),('opening','strike'),('shield','pierce'),('windup','guard')]),
    ('The Shadow Duelist', 'Counter feints and exploit moments of vulnerability.',
     [('feint','focus'),('opening','strike'),('windup','guard'),('exposed','burst')]),
    ('The Crystal Titan', 'Break crystal armour and survive heavy blows.',
     [('shield','pierce'),('windup','guard'),('opening','strike'),('exposed','burst')]),
    ('The Fallen Champion', 'A final test of precision, timing and restraint.',
     [('feint','focus'),('shield','pierce'),('flames','guard'),('exposed','burst')]),
]
OPTIONS = {'guard':'🛡️ Guard','strike':'⚔️ Strike','pierce':'🗡️ Pierce','burst':'✨ Burst','focus':'🎯 Focus'}
CUES = {
    'windup':'The enemy raises its weapon for a devastating charged strike.',
    'opening':'The enemy overextends and leaves its core unprotected.',
    'shield':'A reinforced barrier covers the enemy’s weak points.',
    'exposed':'The enemy staggers, briefly exposing a critical weak spot.',
    'flames':'A wave of fire surges across the arena.',
    'feint':'The enemy makes a suspicious feint; an immediate attack may miss.',
}
# Each encounter is a tactical challenge, not an RNG contest. Max 25 per turn.
POINTS = {
    'windup':{'guard':25,'focus':12,'pierce':5,'strike':3,'burst':3},
    'opening':{'strike':25,'burst':20,'pierce':17,'focus':8,'guard':2},
    'shield':{'pierce':25,'focus':15,'burst':8,'strike':5,'guard':4},
    'exposed':{'burst':25,'strike':21,'pierce':18,'focus':8,'guard':2},
    'flames':{'guard':25,'focus':12,'pierce':6,'strike':4,'burst':3},
    'feint':{'focus':25,'guard':17,'pierce':9,'strike':2,'burst':2},
}


def install(bot, conn, lock, get_player, event_day, open_castle):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS arena_runs (
      user_id INTEGER NOT NULL, challenge INTEGER NOT NULL,
      turn INTEGER NOT NULL DEFAULT 0, score INTEGER NOT NULL DEFAULT 0,
      choices TEXT NOT NULL DEFAULT '',
      scenario_seed TEXT,
      PRIMARY KEY(user_id,challenge)
    );
    ''')
    # Upgrade an existing installation without dropping scored runs.
    columns={r[1] for r in conn.execute('PRAGMA table_info(arena_runs)').fetchall()}
    if 'scenario_seed' not in columns:
        conn.execute('ALTER TABLE arena_runs ADD COLUMN scenario_seed TEXT')
    for old in conn.execute("SELECT user_id,challenge FROM arena_runs WHERE scenario_seed IS NULL").fetchall():
        conn.execute("UPDATE arena_runs SET scenario_seed=? WHERE user_id=? AND challenge=?",
                     (secrets.token_hex(16),old[0],old[1]))
    conn.commit()

    def unlocked(uid):
        p = get_player(uid)
        return p is not None and p['floor'] >= 100

    def arena_open():
        # Starts as soon as the first qualified player arrives; closes two days
        # after the seven-day dungeon event to let Day-7 qualifiers participate.
        return 1 <= event_day() <= 9

    def runs(uid):
        return conn.execute('SELECT challenge,turn,score FROM arena_runs WHERE user_id=? ORDER BY challenge',(uid,)).fetchall()

    def total(uid):
        r = runs(uid)
        return sum(x['score'] for x in r), sum(x['turn'] == 4 for x in r)

    # A run is assigned a secret random seed once, persisted in SQLite.
    # Four scenarios have the same scoring ceiling, but cue order, stance,
    # and the best response depend on the player's individual scenario.
    def scenario(seed, challenge):
        rng=random.Random(int(seed,16))
        base=[cue for cue,_ in CHALLENGES[challenge][2]]
        rng.shuffle(base)
        variants=[]
        for cue in base:
            stance=rng.choice(('steady','charged','feinting'))
            variants.append((cue,stance))
        return variants

    def round_rules(cue,stance):
        # Different enemy stances change the tactical solution. All players
        # face 4 decisions worth up to 25 each; no build advantage.
        scores=POINTS[cue].copy()
        if stance=='charged':
            # A charged enemy is vulnerable to precision, not brute force.
            best='pierce' if cue in ('opening','exposed','shield') else 'guard'
        elif stance=='feinting':
            # A deceptive stance rewards patience and focus.
            best='focus'
        else:
            best=max(scores,key=scores.get)
        if best != max(scores,key=scores.get):
            scores[best]=25
            for key in scores:
                if key!=best:
                    scores[key]=min(scores[key],20)
        return scores,best

    STANCE_HINTS={
      'steady':'The enemy holds a steady stance.',
      'charged':'The enemy gathers power; a precision counter or strong guard may be needed.',
      'feinting':'The enemy shifts unpredictably, disguising its next movement.',
    }

    def encounter_embed(uid, challenge, message=''):
        name, desc, phases = CHALLENGES[challenge]
        row = conn.execute('SELECT turn,score,scenario_seed FROM arena_runs WHERE user_id=? AND challenge=?',(uid,challenge)).fetchone()
        turn = row['turn'] if row else 0
        score = row['score'] if row else 0
        e=discord.Embed(title=f'🏟️ Championship Arena • {challenge+1}/5: {name}',description=desc,color=discord.Color.purple())
        e.add_field(name='Challenge score',value=f'{score}/100',inline=True)
        e.add_field(name='Round',value=f'{min(turn+1,4)}/4' if turn < 4 else 'Complete',inline=True)
        if turn < 4:
            cue,stance=scenario(row['scenario_seed'],challenge)[turn]
            e.add_field(name='Enemy telegraph',value=CUES[cue]+' '+STANCE_HINTS[stance],inline=False)
            e.add_field(name='Your move',value='Choose one action. Every choice is permanent; no retries.',inline=False)
        else:
            e.add_field(name='Result',value='Challenge completed. Use `/play` → Championship Arena for the next encounter.',inline=False)
        if message: e.add_field(name='Last action',value=message,inline=False)
        e.set_image(url="attachment://arena-scene.png")
        e.set_footer(text='Individual randomised encounters • equal maximum 500 points')
        return e

    async def ui_reply(interaction, content=None, *, embed=None, file=None, view=None, ephemeral=True):
        payload={'content':content}
        if embed is not None:payload['embed']=embed
        if view is None:view=ArenaNavigation()
        payload['view']=view
        if interaction.type==discord.InteractionType.component:
            payload['attachments']=[file] if file else []
            return await interaction.response.edit_message(**payload)
        if file is not None:payload['file']=file
        return await interaction.response.send_message(**payload,ephemeral=True)

    class ArenaNavigation(discord.ui.View):
        def __init__(self):super().__init__(timeout=900)
        @discord.ui.button(label='Next Challenge / Resume',emoji='⚔️',style=discord.ButtonStyle.primary)
        async def next(self,i,b):await arena.callback(i)
        @discord.ui.button(label='Castle Gate',emoji='🏰',style=discord.ButtonStyle.secondary)
        async def castle(self,i,b):await open_castle(i)

    class ArenaView(discord.ui.View):
        def __init__(self, uid, challenge):
            super().__init__(timeout=900)
            self.uid=uid
            self.challenge=challenge
            for key,label in OPTIONS.items():
                button=discord.ui.Button(label=label,style=discord.ButtonStyle.primary if key in ('strike','pierce','burst') else discord.ButtonStyle.secondary)
                async def callback(interaction, action=key):
                    if interaction.user.id != self.uid:
                        return await ui_reply(interaction, 'This is another fighter’s arena encounter.',ephemeral=True)
                    async with lock:
                        if not arena_open():
                            return await ui_reply(interaction, 'The Championship Arena is closed.',ephemeral=True)
                        if not unlocked(self.uid):
                            return await ui_reply(interaction, 'Clear Level 100 to qualify.',ephemeral=True)
                        row=conn.execute('SELECT turn,score,choices,scenario_seed FROM arena_runs WHERE user_id=? AND challenge=?',(self.uid,self.challenge)).fetchone()
                        if row is None or row['turn'] >= 4:
                            return await ui_reply(interaction, 'This challenge is already complete or has not been started. Use `/play` → Championship Arena.',ephemeral=True)
                        turn=row['turn']
                        cue,stance=scenario(row['scenario_seed'],self.challenge)[turn]
                        scores,optimal=round_rules(cue,stance)
                        gained=scores[action]
                        conn.execute('UPDATE arena_runs SET turn=?,score=score+?,choices=choices||? WHERE user_id=? AND challenge=? AND turn=?',
                                     (turn+1,gained,('|' if row['choices'] else '')+action,self.uid,self.challenge,turn))
                        conn.commit()
                        msg=f'{OPTIONS[action]}: **+{gained}/25 points**. '+('Perfect counter!' if action==optimal else 'The opponent resisted your approach.')
                        embed=encounter_embed(self.uid,self.challenge,msg)
                        done=turn+1==4
                    await interaction.response.edit_message(embed=embed,attachments=[arena_file(self.challenge,turn+1)],view=ArenaNavigation() if done else ArenaView(self.uid,self.challenge))
                button.callback=callback
                self.add_item(button)

    @bot.tree.command(name='arena',description='Compete in five Championship Arena challenges after clearing Floor 100')
    async def arena(interaction:discord.Interaction):
        async with lock:
            if not unlocked(interaction.user.id):
                return await ui_reply(interaction, '🔒 Clear all 100 dungeon floors to qualify for the Championship Arena.',ephemeral=True)
            r=runs(interaction.user.id)
            score,completed=total(interaction.user.id)
            if completed==5:
                return await ui_reply(interaction, f'🏆 All five challenges complete! **Your final Arena score: {score}/500**. Check `/play` → Rankings.',ephemeral=True)
            if not arena_open():
                return await ui_reply(interaction, 'The Championship Arena is open during event days 1–9 only.',ephemeral=True)
            # Strict sequential progression; existing partially completed runs resume.
            challenge=next(i for i in range(5) if not any(x['challenge']==i and x['turn']==4 for x in r))
            if not any(x['challenge']==challenge for x in r):
                conn.execute('INSERT INTO arena_runs(user_id,challenge,scenario_seed) VALUES(?,?,?)',(interaction.user.id,challenge,secrets.token_hex(16)))
                conn.commit()
            e=encounter_embed(interaction.user.id,challenge)
        row=conn.execute('SELECT turn FROM arena_runs WHERE user_id=? AND challenge=?',(interaction.user.id,challenge)).fetchone()
        await ui_reply(interaction, embed=e,file=arena_file(challenge,row['turn']),view=ArenaView(interaction.user.id,challenge))

    @bot.tree.command(name='arena-score',description='Check your Championship Arena qualification and score')
    async def arena_score(interaction:discord.Interaction):
        if not unlocked(interaction.user.id):
            return await ui_reply(interaction, 'You must clear Floor 100 to qualify.',ephemeral=True)
        score,completed=total(interaction.user.id)
        e=discord.Embed(title='🏟️ Championship Arena Score',description=f'**{score}/500 points** • **{completed}/5** challenges complete',color=discord.Color.gold())
        r={x['challenge']:x for x in runs(interaction.user.id)}
        for i,(name,_,_) in enumerate(CHALLENGES):
            x=r.get(i)
            e.add_field(name=f'{i+1}. {name}',value='Not started' if not x else f'{x["score"]}/100 • '+('Complete' if x['turn']==4 else f'{x["turn"]}/4 rounds'),inline=False)
        e.set_image(url="attachment://dungeon-panel.png")
        await ui_reply(interaction, embed=e,file=panel_file("arena"))

    return {'total':total,'open':arena_open}
