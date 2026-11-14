from pathlib import Path
p=Path('/mnt/data/dk_v13/main.py');s=p.read_text()
s=s.replace("    embed.add_field(name='Your damage',value=f'{record[\"damage\"]:,}' if record else '0')","""    embed.add_field(name='Your damage',value=f'{record["damage"]:,}' if record else '0')
    if tries<3 and raid['hp']>0:
        cue=ELITE_CUES[(day+tries)%3]
        embed.add_field(name='Guardian’s intention',value=INTENT_TEXT[cue],inline=False)""")
s=s.replace("    @discord.ui.button(label='Attack World Boss',emoji='⚔️',style=discord.ButtonStyle.danger)\n    async def attack(self,i,b):await raid_attack(i)","""    @discord.ui.button(label='Strike',emoji='⚔️',style=discord.ButtonStyle.danger)
    async def attack(self,i,b):await raid_attack(i,'attack')
    @discord.ui.button(label='Guard',emoji='🛡️',style=discord.ButtonStyle.primary)
    async def guard(self,i,b):await raid_attack(i,'defend')
    @discord.ui.button(label='Pierce',emoji='✨',style=discord.ButtonStyle.secondary)
    async def pierce(self,i,b):await raid_attack(i,'special')""")
s=s.replace('async def raid_attack(interaction):','async def raid_attack(interaction,action):')
s=s.replace("        # Stable per-user/day/attempt: no rerolling by button spam.\n        rng=random.Random(uid*13+day*311+row['attempts']*947)\n        raw=600+rng.randrange(0,101)\n        damage=min(raid['hp'],raw)","""        # Every player sees the same learnable telegraphs and equal potential damage.
        cue=ELITE_CUES[(day+row['attempts'])%3]
        correct=action==ELITE_CORRECT[cue]
        damage=min(raid['hp'],650 if correct else 400)""")
s=s.replace("    await interaction.response.send_message(f'⚔️ Your fighter dealt **{damage}** standardized raid damage! +100 gold and +1 material. Boss HP: **{left:,}**. You have **{2-row[\"attempts\"]}** attacks remaining.',ephemeral=True)","""    await interaction.response.send_message(f'⚔️ {"Perfect counter!" if correct else "The boss resisted your move."} You dealt **{damage}** standardized raid damage! +100 gold and +1 material. Boss HP: **{left:,}**. You have **{2-row["attempts"]}** attacks remaining. Reopen **World Raid** to see the next telegraph.',ephemeral=True)""")
p.write_text(s)
