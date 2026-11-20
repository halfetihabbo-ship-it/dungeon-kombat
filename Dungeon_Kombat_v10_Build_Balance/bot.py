"""Dungeon Climber: single /play command, public join panel, private interactive menus."""
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands
import game

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv('DISCORD_TOKEN', '').strip()
GUILD_ID = os.getenv('GUILD_ID', '').strip()
ROLE_ID = os.getenv('DISCORD_ROLE_ID', '').strip()
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
GOLD = discord.Color.from_rgb(245, 184, 66)
PURPLE = discord.Color.from_rgb(125, 89, 224)

PRIZES = ('🥇 **1ST PLACE** — **200c + HC Box**',
          '🥈 **2ND PLACE** — **125c + HC Box**',
          '🥉 **3RD PLACE** — **75c + HC Box**')

def event_text(db):
    start, end = game.event_window(db)
    if end is None:
        return '⏳ The 7-day countdown begins when the first hero joins.'
    now = game.utcnow()
    if now < start:
        return f'🗓️ Starts <t:{int(start)}:F>'
    if now >= end:
        return '🏁 **EVENT ENDED** — Final rankings are locked.'
    return f'⏰ **Ends <t:{int(end)}:F>** · <t:{int(end)}:R>'

def prize_text():
    return '\n'.join(PRIZES)

def panel_embed():
    with game.open_db() as db:
        status = event_text(db)
    e = discord.Embed(
        title='⚔️🏰  DUNGEON CLIMBER  🏰⚔️',
        description=(
            '# 🐉 ENTER THE DUNGEON!\n'
            '## 💥 CLIMB. FIGHT. CONQUER. 💥\n'
            '**SEVEN DAYS. ENDLESS FLOORS. THREE CHAMPIONS.**\n\n'
            '⚔️ Create your hero and automatically fight your way through the dungeon.\n'
            '🛡️ Collect powerful equipment and upgrade it at the Blacksmith.\n'
            '🐲 Defeat legendary bosses and conquer higher floors.\n'
            '🏆 Reach the **highest floor** to claim the top prizes!\n\n'
            '## 🎁 WIN THESE PRIZES!\n' + prize_text() + '\n\n'
            '## 🚀 READY TO JOIN?\n'
            '**👇 PRESS THE BIG GREEN JOIN BUTTON BELOW! 👇**\n'
            '*No complicated setup — choose your class and your hero starts climbing.*'
        ), color=GOLD)
    e.add_field(name='📅 EVENT TIMER', value=status, inline=False)
    e.add_field(name='🎮 HOW TO PLAY', value='**1️⃣ JOIN** → **2️⃣ PICK A CLASS** → **3️⃣ CLIMB & UPGRADE**', inline=False)
    e.set_footer(text='Dungeon Climber • Top 3 highest floors win • Ties: earliest to reach that floor')
    return e

def stats(s):
    return (f'🧙 **{s["class"]}**  ·  ⭐ **Lv. {s["level"]}**  ·  🏰 **Floor {s["floor"]:,}**\n'
            f'❤️ **{s["hp"]:,}/{game.max_hp(s):,} HP**  ·  ⚔️ **{game.attack_power(s):.0f} ATK**  ·  🛡️ **{game.defense_power(s):.0f} DEF**\n'
            f'🪙 **{s["gold"]:,} Gold**  ·  🧱 **{s["materials"]:,} Materials**  ·  🗝️ **{s["keys"]} Keys**')

def rankings_embed():
    with game.open_db() as db:
        ranks = game.leaderboard(db)
        status = event_text(db)
    lines = [f'{("🥇", "🥈", "🥉")[i] if i < 3 else f"`#{i+1}`"} **{discord.utils.escape_markdown(name)}** — Floor **{floor:,}**'
             for i, (_, name, floor, _) in enumerate(ranks)]
    e = discord.Embed(title='🏆 HALL OF CHAMPIONS',
                      description=('\n'.join(lines) or '🌱 No heroes yet — be the first!') + '\n\n' + status,
                      color=GOLD)
    e.add_field(name='🎁 TOP 3 PRIZES', value=prize_text(), inline=False)
    e.set_footer(text='Highest floor wins • Tie-break: earliest to reach that floor')
    return e

def help_embed():
    e = discord.Embed(
        title='📖⚔️ DUNGEON CLIMBER — HELP & QUICK START',
        description=(
            '## 🚀 QUICK START — ONLY 3 STEPS!\n'
            '**1️⃣ CHOOSE YOUR HERO** — Berserker ⚔️, Guardian 🛡️ or Rogue 🗡️.\n'
            '**2️⃣ LET YOUR HERO CLIMB** — Battles happen automatically every **15 seconds** when progress is processed.\n'
            '**3️⃣ CHECK BACK & GET STRONGER** — Collect loot, upgrade equipment and defeat bosses!\n\n'
            '## 🧭 WHAT SHOULD I DO NEXT?\n'
            '🏠 **Home** — View your floor, health, loot and latest progress.\n'
            '⚒️ **Blacksmith** — Upgrade weapon/armour (+1 to +10), refine endlessly from Floor 100.\n'
            '🎯 **Activities** — Daily Bounty, Gauntlet and Treasure Vault.\n'
            '🐉 **Boss Battle** — Legendary boss every 50 floors. Use Attack, Guard, Power Strike and Second Wind.\n'
            '🏆 **Leaderboard** — See who is leading the competition.\n\n'
            '## 💡 IMPORTANT TIPS\n'
            '🌙 Offline progress counts for up to **8 hours** when you return.\n'
            '💰 Stuck on a floor? Your hero farms resources and gets stronger.\n'
            '🎁 Every 10 floors brings a milestone chest.\n'
            '🗝️ Vault Keys unlock treasure rewards.\n'
            '🛡️ Better dropped gear is automatically equipped.\n'
            '🔁 Use **Refresh** to collect your latest idle progress.\n'
            '🏁 The highest floor after **7 days** wins; ties go to whoever reached it first.'
        ), color=PURPLE)
    e.add_field(name='🎁 PRIZES', value=prize_text(), inline=False)
    e.set_footer(text='Everything is controlled from /play — no other commands needed!')
    return e

def player_embed(s, notice='', screen='home'):
    titles = {'home': '🏰⚔️ YOUR DUNGEON ADVENTURE', 'smith': '⚒️🔥 THE ROYAL BLACKSMITH',
              'activities': '🎯✨ QUESTS & TREASURE', 'boss': '🐉🔥 LEGENDARY BOSS'}
    e = discord.Embed(title=titles.get(screen, titles['home']), description=stats(s), color=GOLD if screen=='home' else PURPLE)
    if screen=='home':
        e.add_field(name='🗺️ YOUR ADVENTURE',
                    value=('🔴 **A LEGENDARY BOSS IS WAITING!** Open **🐉 Boss Battle**.' if s['boss']
                           else '🟢 **AUTO-CLIMB ACTIVE!** Your hero is battling or farming.'), inline=False)
        e.add_field(name='🗡️ EQUIPMENT',
                    value=(f'⚔️ **{s["weapon"]["name"]}**  +{s["weapon"]["plus"]} · R{s["weapon"]["refine"]}\n'
                           f'🛡️ **{s["armour"]["name"]}**  +{s["armour"]["plus"]} · R{s["armour"]["refine"]}'), inline=False)
        e.add_field(name='🚀 WHAT TO DO NEXT',
                    value='**1.** Tap 🔄 Refresh to claim progress.\n**2.** Visit ⚒️ Blacksmith for upgrades.\n**3.** Check 🎯 Activities for rewards.\n**4.** Fight 🐉 Bosses when they appear.', inline=False)
        e.add_field(name='📜 LATEST ADVENTURE REPORT', value=(notice or s.get('last_report') or 'Your journey begins!')[:1024], inline=False)
    elif screen=='smith':
        e.add_field(name='🔨 FORGE YOUR POWER',
                    value='⚔️ Upgrade Weapon / 🛡️ Upgrade Armour: +1 to +10.\n✨ Refine gear endlessly after Floor 100.\n♻️ Upgrades transfer when you find stronger gear.\n💡 Farm gold and materials to afford upgrades.', inline=False)
    elif screen=='activities':
        e.add_field(name='🎯 CHOOSE AN ADVENTURE',
                    value='📜 **Daily Bounty** — Claim a daily reward.\n🏟️ **Gauntlet** — Take on a daily challenge.\n🗝️ **Treasure Vault** — Spend a key for gold, materials and possible equipment.', inline=False)
    elif screen=='boss':
        b=s.get('boss')
        e.add_field(name='🐲 BOSS ENCOUNTER',
                    value=(f'🔥 **Floor {b["floor"]}** · ❤️ **{max(0,b["hp"]):,}/{b["max_hp"]:,} HP**\n'
                           f'⚔️ Turn **{b["turn"]}/6** · Power Strike cooldown **{b["cooldown"]}**\n'
                           f'🛡️ Heavy strike every 3rd turn — **Guard** to reduce damage!\n'
                           f'💚 Second Wind heals once per fight. · Mercy bonus **+{s["boss_mercy"]*5}%**'
                           if b else '🟢 No boss waiting! Keep climbing; a legendary boss appears every 50 floors.'), inline=False)
    if notice and screen!='home':
        e.add_field(name='📣 LATEST RESULT', value=notice[:1024], inline=False)
    e.set_footer(text='⚔️ Battles: 15 seconds • 🌙 Offline: 8 hours • 🏆 7-day event • 📖 Help available')
    return e

async def send_private(interaction, *, embed=None, view=None, content=None):
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(content=content, embed=embed, view=view, ephemeral=True)

async def show_player(interaction, screen='home', action=None):
    try:
        with game.open_db() as db:
            if not game.get_player(db, interaction.user.id):
                return await send_private(interaction, embed=help_embed(), view=JoinView())
            s, notice = (game.mutate(db, interaction.user.id, interaction.user.display_name, action)
                         if action else game.refresh(db, interaction.user.id, interaction.user.display_name))
        await interaction.response.edit_message(embed=player_embed(s, notice, screen), view=GameView(screen))
    except ValueError as exc:
        await send_private(interaction, content=f'⚠️ {exc}')
    except Exception:
        logging.exception('Game interaction failed')
        await send_private(interaction, content='⚠️ Something went wrong. Please try again.')

class NavButton(discord.ui.Button):
    def __init__(self, label, screen, *, emoji=None, action=None, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, emoji=emoji, style=style,
                         custom_id=f'climber:v2:{screen}:{action or "nav"}')
        self.screen, self.action = screen, action
    async def callback(self, interaction):
        if self.screen=='help':
            await interaction.response.edit_message(embed=help_embed(), view=HelpView())
        elif self.screen=='rankings':
            await interaction.response.edit_message(embed=rankings_embed(), view=RankingsView())
        else:
            await show_player(interaction, self.screen, self.action)

class GameView(discord.ui.View):
    def __init__(self, screen='home'):
        super().__init__(timeout=None)
        if screen=='home':
            buttons=[('Refresh','home','🔄',None,discord.ButtonStyle.success),
                     ('Blacksmith','smith','⚒️',None,discord.ButtonStyle.primary),
                     ('Activities','activities','🎯',None,discord.ButtonStyle.primary),
                     ('Boss Battle','boss','🐉',None,discord.ButtonStyle.danger),
                     ('Help','help','📖',None,discord.ButtonStyle.secondary),
                     ('Leaderboard','rankings','🏆',None,discord.ButtonStyle.secondary)]
        elif screen=='smith':
            buttons=[('Weapon +1','smith','⚔️','upgrade_weapon',discord.ButtonStyle.success),
                     ('Armour +1','smith','🛡️','upgrade_armour',discord.ButtonStyle.success),
                     ('Refine Weapon','smith','✨','refine_weapon',discord.ButtonStyle.primary),
                     ('Refine Armour','smith','💎','refine_armour',discord.ButtonStyle.primary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        elif screen=='activities':
            buttons=[('Daily Bounty','activities','📜','daily',discord.ButtonStyle.success),
                     ('Gauntlet','activities','🏟️','challenge',discord.ButtonStyle.primary),
                     ('Treasure Vault','activities','🗝️','vault',discord.ButtonStyle.primary),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        else:
            buttons=[('Attack','boss','⚔️','boss_attack',discord.ButtonStyle.primary),
                     ('Guard','boss','🛡️','boss_guard',discord.ButtonStyle.secondary),
                     ('Power Strike','boss','💥','boss_power',discord.ButtonStyle.danger),
                     ('Second Wind','boss','💚','boss_heal',discord.ButtonStyle.success),
                     ('Back to Home','home','🏠',None,discord.ButtonStyle.secondary)]
        for label,screen,emoji,action,style in buttons:
            self.add_item(NavButton(label,screen,emoji=emoji,action=action,style=style))

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NavButton('Start / Return to Game','home',emoji='⚔️',style=discord.ButtonStyle.success))
        self.add_item(NavButton('Leaderboard','rankings',emoji='🏆'))

class RankingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NavButton('Back to Game','home',emoji='🏠',style=discord.ButtonStyle.success))
        self.add_item(NavButton('Help','help',emoji='📖'))

async def assign_role(interaction):
    if not ROLE_ID or not interaction.guild:
        return
    try:
        role = interaction.guild.get_role(int(ROLE_ID))
        if role and isinstance(interaction.user, discord.Member) and role not in interaction.user.roles:
            await interaction.user.add_roles(role, reason='Joined Dungeon Climber')
    except (discord.Forbidden, discord.HTTPException, ValueError):
        logging.warning('Could not assign Dungeon Climber role; check Manage Roles and hierarchy')

class HeroSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='🧙 Choose your hero class to begin!', custom_id='climber:v2:class',
                         options=[discord.SelectOption(label='Berserker',description='⚔️ Powerful attacks',emoji='⚔️'),
                                  discord.SelectOption(label='Guardian',description='🛡️ Strong defence and health',emoji='🛡️'),
                                  discord.SelectOption(label='Rogue',description='🗡️ Swift, balanced fighter',emoji='🗡️')])
    async def callback(self, interaction):
        try:
            with game.open_db() as db:
                existing=game.get_player(db,interaction.user.id)
                s=existing or game.create_player(db,interaction.user.id,interaction.user.display_name,self.values[0])
            await assign_role(interaction)
            await interaction.response.edit_message(embed=player_embed(s,'🎉 Hero created! Welcome to the dungeon.'),view=GameView())
        except ValueError as exc:
            await send_private(interaction,content=f'⚠️ {exc}')
        except Exception:
            logging.exception('Character creation failed')
            await send_private(interaction,content='⚠️ Could not create hero. Please try again.')

class ClassView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HeroSelect())
        self.add_item(NavButton('Read Quick Start','help',emoji='📖'))

class JoinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='⚔️ JOIN DUNGEON CLIMBER ⚔️',style=discord.ButtonStyle.success,
                         custom_id='climber:v2:join',row=0)
    async def callback(self,interaction):
        with game.open_db() as db:
            existing=game.get_player(db,interaction.user.id)
        if existing:
            await assign_role(interaction)
            return await send_private(interaction,embed=player_embed(existing),view=GameView())
        await send_private(interaction,embed=discord.Embed(
            title='🧙✨ CREATE YOUR HERO!',
            description='## 🚀 YOUR ADVENTURE STARTS HERE!\nPick a class below. Your hero will begin climbing automatically.\n\n⚔️ **Berserker** — Heavy damage\n🛡️ **Guardian** — High health & defence\n🗡️ **Rogue** — Swift balanced fighter\n\n💡 Need guidance? Press **Read Quick Start**.',color=GOLD),view=ClassView())

class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(JoinButton())
        self.add_item(NavButton('HOW TO PLAY','help',emoji='📖',style=discord.ButtonStyle.primary))
        self.add_item(NavButton('VIEW PRIZES & LEADERBOARD','rankings',emoji='🏆'))

@bot.tree.command(name='play',description='Play Dungeon Climber or publish the public join panel')
@app_commands.describe(panel='Publish the large public join panel (server administrators only)')
async def play(interaction:discord.Interaction,panel:bool=False):
    if panel:
        if not interaction.guild or not isinstance(interaction.user,discord.Member) or not interaction.user.guild_permissions.manage_guild:
            return await send_private(interaction,content='🔒 Only server administrators with Manage Server can publish the join panel.')
        await interaction.response.send_message(embed=panel_embed(),view=JoinView())
        return
    with game.open_db() as db:
        s=game.get_player(db,interaction.user.id)
    if s:
        with game.open_db() as db:s,notice=game.refresh(db,interaction.user.id,interaction.user.display_name)
        await send_private(interaction,embed=player_embed(s,notice),view=GameView())
    else:
        await send_private(interaction,embed=discord.Embed(
            title='🏰⚔️ WELCOME TO DUNGEON CLIMBER!',
            description='## 🚀 CREATE YOUR HERO!\nSelect your class below and start your seven-day adventure.\n\n📖 New player? Tap **Read Quick Start** for an easy guide.',color=GOLD),view=ClassView())

@bot.event
async def setup_hook():
    for view in (JoinView(),ClassView(),GameView('home'),GameView('smith'),GameView('activities'),
                 GameView('boss'),HelpView(),RankingsView()):
        bot.add_view(view)
    if GUILD_ID:
        guild=discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()

@bot.event
async def on_ready():
    logging.info('Dungeon Climber online as %s',bot.user)

if __name__=='__main__':
    if not TOKEN:
        raise SystemExit('DISCORD_TOKEN is required.')
    bot.run(TOKEN)
