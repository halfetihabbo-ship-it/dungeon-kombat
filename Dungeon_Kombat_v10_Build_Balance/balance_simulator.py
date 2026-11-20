import random, statistics, csv
from collections import defaultdict
DAYS=7; RUNS=500
PROFILES={'Casual':(3,13,.48),'Regular':(6,20,.72),'Dedicated':(10,24,.91)}
# Abstract power units. Gear scales sublinearly; enemies increase steadily.
def enemy(f): return 24+1.65*f+0.0038*f*f
def gear(f,quality): return (10+1.45*f**.82)*quality
def simulate(profile,seed):
 r=random.Random(seed); checks,coverage,skill=PROFILES[profile]
 floor=1; gold=250; material=0; upgrades=0; drops=0; fails=0; bosses=0; manual_bosses=0; boss_retries=0; farm_cycles=0; active_rewards=0; streak=0; farm_left=0; last_manual_window=-1; predicted_farms=0; auto_upgrades=0
 gear_level=1; refine=0; dayfloors=[]
 for day in range(1,DAYS+1):
  # Offline cap and check-in cadence determine usable daily hours.
  hours=min(coverage,checks*8)
  # A 15-second battle; each floor needs 2-3 victories. Model in 45-second floor attempts.
  attempts=int(hours*3600/45)
  # Active boss time, loot management and upgrading consume part of the time.
  attempts=int(attempts*(.72+.13*skill))
  for i in range(attempts):
   target=floor+1
   window=i//max(1,attempts//checks)
   # Every fight earns gold; farming produces resources even on a loss.
   gold+=8+floor*.30
   if r.random()<.14:material+=1
   # Active boss/challenge materials earned during check-ins.
   if i % max(1,attempts//checks)==0:
    bonus=round(2+5*skill)
    material+=bonus; active_rewards+=bonus
   # Check-in spending; no capped refinement, guaranteed upgrades, transferable levels.
   if i % max(1,attempts//checks)==0:
    spend=min(7,int(gold//(120+upgrades*22)))
    for _ in range(spend):
     price=120+upgrades*22
     if gold<price:break
     gold-=price;upgrades+=1
    while material>=7 and gold>=250+refine*35:
     material-=max(4,7-floor//250);gold-=250+refine*35;refine+=1
   if floor//10>gear_level//10:gear_level=floor;drops+=1
   if r.random()<.017:
    gear_level=max(gear_level,floor+r.randint(0,2));drops+=1
   # Both enemy and gear scale indefinitely; diminishing gains prevent runaway.
   player=(28+1.25*gear_level+upgrades*2.1+refine*3.3)*(1+.10*skill)
   foe=25+1.25*target+.0065*target**2
   if target%50==0:foe*=1.12
   elif target%25==0:foe*=1.065
   elif target%10==0:foe*=1.025
   # Boss skill, mercy after repeated defeats, and healing are approximated.
   boss=target%25==0
   # Major bosses require an active check-in; model a fixed manual attempt cost.
   if farm_left>0:
    farm_left-=1
    # Farm a known-clear floor: reliable income and materials, then retry.
    gold+=14+floor*.42
    if r.random()<min(.85,.40+floor/1600):material+=1+floor//250
    continue
   # A manual boss is attempted once per check-in window, not on one exact tick.
   if target%50==0 and last_manual_window==window+day*10000:
    continue
   if target%50==0:last_manual_window=window+day*10000
   if boss:foe*=1-.11*skill
   # Smart farming: avoid hopeless progression attempts. At most one
   # predicted farming batch per decision, and spend resources during idle.
   ratio=player/foe
   if ratio < .61:
    predicted_farms+=1
    gold+=14+floor*.42
    if r.random()<min(.85,.40+floor/1600):material+=1+floor//250
    # Automatic affordable refinement; preserves resources for future gear.
    if material>=max(4,7-floor//250) and gold>=250+refine*35:
     material-=max(4,7-floor//250);gold-=250+refine*35;refine+=1;auto_upgrades+=1
    elif gold>=120+upgrades*22:
     gold-=120+upgrades*22;upgrades+=1;auto_upgrades+=1
    continue
   chance=max(.025,min(.94,.46+.85*(ratio-1)))
   if boss:chance=max(chance,.16+.24*skill)
   if target%50==0:
    manual_bosses+=1
    chance=max(chance,.22+.30*skill)
   if r.random()<chance:
    floor+=1;streak=0
    if boss:bosses+=1
   else:
    fails+=1;streak+=1
    if streak>=5:
     farm_left=5;farm_cycles+=1;streak=0
    if target%50==0:boss_retries+=1
    # After a failed floor, hero farms previous floor, with guaranteed income.
    # This is one floor attempt (2-3 battles), not an additional time penalty.
  dayfloors.append(floor)
 return dict(profile=profile,seed=seed,**{f'day{d}':v for d,v in enumerate(dayfloors,1)},floor=floor,upgrades=upgrades,drops=drops,fails=fails,bosses=bosses,manual_bosses=manual_bosses,boss_retries=boss_retries,farm_cycles=farm_cycles,active_rewards=active_rewards,predicted_farms=predicted_farms,auto_upgrades=auto_upgrades)

def run():
 out=[]
 for p in PROFILES:
  for i in range(RUNS):out.append(simulate(p,110000+i))
 with open('/mnt/data/dungeon_climber_results.csv','w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
 for p in PROFILES:
  a=[x for x in out if x['profile']==p];vals=sorted(x['floor'] for x in a)
  print(p,'days',[round(statistics.median(x[f'day{d}'] for x in a)) for d in range(1,8)],'p10/median/p90',vals[29],statistics.median(vals),vals[449], 'fail median',statistics.median(x['fails'] for x in a),'boss median',statistics.median(x['bosses'] for x in a),'farm cycles',statistics.median(x['farm_cycles'] for x in a),'active materials',statistics.median(x['active_rewards'] for x in a),'predicted farm',statistics.median(x['predicted_farms'] for x in a),'auto upgrades',statistics.median(x['auto_upgrades'] for x in a))
if __name__=='__main__':run()
