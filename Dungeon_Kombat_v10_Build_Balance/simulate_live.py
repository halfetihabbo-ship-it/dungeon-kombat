"""Seven-day Monte Carlo using production stats, enemy, rewards, upgrade costs and combat rules.
Limitations: combat is an independent Python reproduction of resolve_action; real Discord interactions not exercised.
"""
import ast, random, statistics, csv, json, argparse
from pathlib import Path
src=Path(__file__).with_name('main.py'); tree=ast.parse(src.read_text())
keep={'stats','enemy_stats','reward_for_floor','damage_reduction','advanced_cost'}
ns={'WEAPONS':{'Sword':(1.0,''),'Axe':(1.2,''),'Daggers':(.8,''),'Staff':(.9,''),'Spear':(1.05,'')}}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in keep],type_ignores=[]),str(src),'exec'),ns)
BUILDS={'balanced':['strength','vitality','defence','strength','vitality','energy'], 'aggressive':['strength','strength','vitality','strength','defence','energy'], 'defensive':['vitality','defence','strength','vitality','strength','energy']}
# logins/day: active users can catch 2-hour regen, while casuals waste some due to cap.
SCHEDULES={'dedicated':[0,6,12,18,23], 'regular':[0,12,22], 'casual':[20]}

def run(seed,build='balanced',schedule='dedicated',enemy_multiplier=1):
 r=random.Random(seed);p={k:0 for k in ('strength','vitality','defence','agility','energy')};p.update(weapon='Axe' if build=='aggressive' else 'Sword',weapon_stage=0,weapon_upgrade=0,armor_upgrade=0,weapon_advanced=0,armor_advanced=0,skill='None',relics=0,enchantment='None')
 gold=mats=attempts=spent=losses=floor=stamina=0;regen_anchor=0;daily=[];complete_day=None;total_activity=0; total_turns=0
 for day in range(7):
  attempts=min(140,attempts+20)
  # lazy daily grant, 2h regen; 45 cap. At UTC midnight.
  stamina=min(45,stamina+15)
  for hour in SCHEDULES[schedule]:
   now=day*24+hour
   ticks=max(0,(now-regen_anchor)//2)
   if ticks:
    stamina=min(45,stamina+ticks)
    regen_anchor=now if stamina==45 else regen_anchor+ticks*2
   # Activities: full dedicated, 70% regular, 40% casual of available stamina.
   use=stamina if schedule=='dedicated' else (int(stamina*.70) if schedule=='regular' else int(stamina*.40))
   stamina-=use; total_activity+=use
   # Ruins is dominant activity in current playable code.
   gold+=110*use;mats+=2*use
   # Spend all attempts at sessions; casuals play ~12 fights per day.
   fights=attempts if schedule!='casual' else min(attempts,15)
   for _ in range(fights):
    if floor>=100:break
    # Gear purchases, current exact costs. Alternate priorities, with weapons favoured.
    while True:
     options=[]
     for k,w in [('weapon_upgrade',1.3),('armor_upgrade',1.05)]:
      n=p[k]; cost=150*(n+1); material=n+1
      if n<10 and gold>=cost and mats>=material:options.append((w/(n+1)**.35,k,cost,material))
     if not options:break
     _,key,cost,material=max(options);gold-=cost;mats-=material;p[key]+=1
    if floor>=5 and p['skill']=='None':p['skill']={'balanced':'Arcanist','aggressive':'Berserker','defensive':'Guardian'}[build]
    if floor>=30 and p['enchantment']=='None' and gold>=4000 and mats>=25:
     gold-=4000;mats-=25;p['enchantment']='Ward' if build=='defensive' else 'Flame'
    if floor>=50:
     for key in ('weapon','armor'):
      n=p[key+'_advanced'];cost,material=ns['advanced_cost'](n)
      if p[key+'_upgrade']==10 and n<5 and gold>=cost and mats>=material:
       gold-=cost;mats-=material;p[key+'_advanced']+=1
    target=floor+1;maxhp,atk,defense,speed,maxenergy=ns['stats'](p)
    ehp,eatk,edef,boss=ns['enemy_stats'](target);ehp=round(ehp*enemy_multiplier)
    hp=maxhp;energy=maxenergy;potions=3;focused=0;charge=0;poison=0;cooldown=0
    attempts-=1;spent+=1;won=False
    for turn in range(1,(30 if boss else 20)+1):
     shield=boss and target>=20 and turn%5 in (1,2)
     incoming=eatk*ns['damage_reduction'](defense)*(2.1 if charge else 1)
     if charge and incoming>hp*.22:action='defend'
     elif hp<maxhp*.55 and potions and incoming<hp and hp<maxhp-30:action='heal'
     elif energy>=28 and cooldown==0 and not shield and not charge:action='special'
     elif energy<19 and hp>incoming*2 and not shield:action='focus'
     else:action='attack'
     guard=action=='defend';cooldown=max(0,cooldown-1)
     if action in ('attack','special'):
      mult=1.38 if action=='attack' else {'Axe':1.55,'Daggers':1.53,'Staff':1.56,'Spear':1.53}.get(p['weapon'],1.48)
      if action=='special':energy-=28;cooldown=3
      if shield:mult*=.48 if action=='special' else 1.55
      if action=='attack':energy=min(maxenergy,energy+7)
      if focused:mult*=1.15
      base=max(1,round(atk*mult*ns['damage_reduction'](edef)))
      crit=r.random()<min(.25,.05+speed/500)
      dealt=max(1,round(base*(1.35 if crit else 1)*r.uniform(.95,1.05)))
      if action=='special' and p['weapon']=='Spear':dealt=round(dealt*1.12)
      ehp=max(0,ehp-dealt);focused=0
     elif action=='heal':hp=min(maxhp,hp+max(30,round(maxhp*.3)));potions-=1
     elif action=='focus':energy=min(maxenergy,energy+18);focused=1
     if ehp<=0:won=True;total_turns+=turn;break
     damage=round(eatk*ns['damage_reduction'](defense)*r.uniform(.9,1.1))
     if charge:damage=round(damage*2.1)
     if boss and turn>8:damage=round(damage*(1+.10*(turn-8)))
     if guard:damage=max(1,round(damage*.55))
     if r.random()<min(.2,max(0,(speed-10)*.001)):damage=0
     hp=max(0,hp-damage)
     if poison:hp=max(0,hp-max(1,round(maxhp*.04)));poison-=1
     if target>=11 and turn%5==0 and not poison:poison=2
     charge=1 if target>=31 and turn%4==0 else 0
     if hp<=0:break
    if won:
     floor=target;g,m=ns['reward_for_floor'](floor);gold+=g;mats+=m
     if floor in (20,40,60,80):p['weapon_stage']+=1
     if floor%10==0:p['relics']+=1
     for i in range(3):p[BUILDS[build][(floor*3-3+i)%6]]+=1
     if floor==100:complete_day=day+1
    else:losses+=1
   if floor==100:break
  daily.append(dict(day=day+1,floor=floor,gold=gold,materials=mats,stamina=stamina,attempts=attempts,weapon=p['weapon_upgrade'],armor=p['armor_upgrade'],advanced_weapon=p['weapon_advanced'],advanced_armor=p['armor_advanced']))
  if floor==100:
   for remaining_day in range(day+1,7):daily.append(dict(day=remaining_day+1,floor=floor,gold=gold,materials=mats,stamina=stamina,attempts=attempts,weapon=p['weapon_upgrade'],armor=p['armor_upgrade'],advanced_weapon=p['weapon_advanced'],advanced_armor=p['armor_advanced']))
   break
 return dict(build=build,schedule=schedule,floor=floor,complete_day=complete_day,spent=spent,losses=losses,gold=gold,materials=mats,activities=total_activity,weapon=p['weapon_upgrade'],armor=p['armor_upgrade'],advanced_weapon=p['weapon_advanced'],advanced_armor=p['armor_advanced'],daily=daily)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--runs',type=int,default=100);ap.add_argument('--multiplier',type=float,default=1);args=ap.parse_args()
 summary=[];days=[]
 for build in BUILDS:
  for schedule in SCHEDULES:
   runs=[run(45000+i,build,schedule,args.multiplier) for i in range(args.runs)]
   row=dict(build=build,schedule=schedule,runs=len(runs),completion_pct=round(100*sum(x['floor']==100 for x in runs)/len(runs),1),median_floor=statistics.median(x['floor'] for x in runs),median_gold=statistics.median(x['gold'] for x in runs),median_materials=statistics.median(x['materials'] for x in runs),median_activities=statistics.median(x['activities'] for x in runs),median_weapon_advanced=statistics.median(x['advanced_weapon'] for x in runs),median_armor_advanced=statistics.median(x['advanced_armor'] for x in runs))
   summary.append(row);print(row,flush=True)
   for d in range(7):days.append(dict(build=build,schedule=schedule,day=d+1,median_floor=statistics.median(x['daily'][d]['floor'] for x in runs)))
 for name,rows in [('summary.csv',summary),('daily.csv',days)]:
  with (Path(__file__).with_name(name)).open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
if __name__=='__main__':main()
