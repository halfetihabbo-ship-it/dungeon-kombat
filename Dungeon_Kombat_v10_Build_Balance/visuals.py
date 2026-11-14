"""Procedural fantasy dungeon art. All visuals generated locally; no external URLs or APIs."""
import io, math, random
from PIL import Image, ImageDraw, ImageFont
import discord

THEMES = [
 ('FORGOTTEN CAVES',(31,95,114),(8,17,29),'⛏'),
 ('HAUNTED WOODS',(59,126,89),(9,24,21),'🌲'),
 ('CRYPT OF SHADOWS',(114,81,148),(19,14,31),'☠'),
 ('INFERNO DEPTHS',(221,91,45),(39,15,17),'🔥'),
 ('FROZEN ABYSS',(96,177,221),(12,30,48),'❄'),
 ('TOXIC WASTELAND',(139,182,64),(20,31,17),'☣'),
 ('CURSED CITADEL',(166,69,99),(28,14,27),'♜'),
 ('STORM TEMPLE',(97,133,207),(16,23,44),'⚡'),
 ('THE VOID',(157,97,202),(13,10,31),'✦'),
 ('THRONE OF THE FALLEN',(210,160,74),(30,18,25),'♛'),
]
ARENA_THEMES = [
 ('IRON SENTINEL',(161,175,189),(24,31,45)),
 ('EMBER WYRM',(239,114,58),(47,19,20)),
 ('SHADOW DUELIST',(173,107,218),(24,15,40)),
 ('CRYSTAL TITAN',(94,219,224),(11,37,48)),
 ('FALLEN CHAMPION',(224,180,94),(38,20,31)),
]

def font(size, bold=False):
    candidates = ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf']
    for p in candidates:
        try:return ImageFont.truetype(p,size)
        except OSError:pass
    return ImageFont.load_default()

def blend(a,b,t):return tuple(round(x*(1-t)+y*t) for x,y in zip(a,b))

def scene(title, subtitle, accent, dark, seed, boss=False, arena=False, index=0):
    w,h=1100,440
    rng=random.Random(seed)
    im=Image.new('RGB',(w,h),dark); d=ImageDraw.Draw(im)
    for y in range(h):
        t=y/h
        d.line((0,y,w,y),fill=blend(blend(dark,accent,.18),dark,t*.92))
    # Gothic stone blocks and torchlit pillars.
    for col in range(0,w+120,115):
        offset=rng.randint(-18,18)
        for y in range(-40,h+50,75):
            x=col+offset+(58 if (y//75)%2 else 0)
            c=blend(dark,accent,rng.uniform(.08,.18))
            d.rounded_rectangle((x,y,x+112,y+72),radius=3,outline=c,width=2)
    # Receding vaulted arches, with glowing inner chamber.
    for i in range(5):
        margin=95+i*67
        ytop=33+i*37
        x0,x1=margin,w-margin
        d.arc((x0,ytop,x1,720-i*50),180,360,fill=blend(accent,(230,225,214),.12+i*.035),width=max(3,11-i))
        d.line((x0,ytop+230,x0,h),fill=blend(accent,dark,.5),width=7)
        d.line((x1,ytop+230,x1,h),fill=blend(accent,dark,.5),width=7)
    # Floor perspective.
    d.polygon([(0,h),(w,h),(w*.64,315),(w*.36,315)],fill=blend(dark,accent,.20))
    for i in range(1,6):
        yy=315+int((i/5)**1.7*125)
        d.line((0,yy,w,yy),fill=blend(accent,dark,.58),width=2)
    for i in range(9):
        x=int(w*i/8)
        d.line((w//2,315,x,h),fill=blend(accent,dark,.62),width=2)
    # Massive boss silhouette or atmospheric doorway.
    cx,cy=550,235
    if boss:
        d.ellipse((cx-115,cy-117,cx+115,cy+120),fill=blend(dark,accent,.34),outline=accent,width=5)
        d.polygon([(cx-100,cy+106),(cx-86,cy-38),(cx-35,cy-98),(cx+35,cy-98),(cx+86,cy-38),(cx+100,cy+106)],fill=blend(dark,accent,.5),outline=accent)
        d.polygon([(cx-90,cy-54),(cx-144,cy-145),(cx-20,cy-103),(cx+20,cy-103),(cx+144,cy-145),(cx+90,cy-54)],fill=blend(dark,accent,.64))
        d.ellipse((cx-53,cy-28,cx-28,cy-11),fill=(255,219,132))
        d.ellipse((cx+28,cy-28,cx+53,cy-11),fill=(255,219,132))
        d.line((cx,cy+18,cx,cy+78),fill=accent,width=9)
    else:
        d.rounded_rectangle((cx-79,115,cx+79,345),radius=66,fill=blend(dark,accent,.32),outline=accent,width=6)
        d.arc((cx-65,132,cx+65,290),180,360,fill=blend(accent,(255,255,255),.4),width=5)
        d.line((cx-60,235,cx-60,330),fill=accent,width=5)
        d.line((cx+60,235,cx+60,330),fill=accent,width=5)
    # Floating dust / embers.
    for _ in range(95):
        x=rng.randrange(w); y=rng.randrange(40,h-20); r=rng.choice([1,1,2,3])
        d.ellipse((x-r,y-r,x+r,y+r),fill=blend(accent,(255,255,225),rng.uniform(.2,.65)))
    # Text plate for legibility.
    d.rounded_rectangle((30,24,610,123),radius=16,fill=blend(dark,(0,0,0),.42),outline=accent,width=2)
    d.text((52,36),title,font=font(34,True),fill=(247,236,211),stroke_width=1,stroke_fill=(5,5,10))
    d.text((54,88),subtitle,font=font(20),fill=blend(accent,(255,255,255),.62))
    d.rounded_rectangle((870,28,1068,78),radius=12,fill=dark,outline=accent,width=2)
    d.text((893,40),'CHAMPIONSHIP' if arena else ('BOSS FLOOR' if boss else 'DUNGEON'),font=font(15,True),fill=(250,239,220))
    return im

def _file(img,name):
    buf=io.BytesIO();img.save(buf,'PNG',optimize=True);buf.seek(0)
    return discord.File(buf,filename=name)

def floor_file(floor):
    idx=min(9,max(0,(floor-1)//10));name,accent,dark,_=THEMES[idx]
    img=scene(name,f'FLOOR {floor:03d} / 100  •  ZONE {idx+1:02d} / 10',accent,dark,1000+floor,boss=floor%10==0,index=idx)
    return _file(img,'dungeon-floor.png')

def arena_file(challenge,turn):
    name,accent,dark=ARENA_THEMES[challenge]
    img=scene(name,f'CHALLENGE {challenge+1} / 5  •  ROUND {min(turn+1,4)} / 4',accent,dark,5000+challenge*19,boss=True,arena=True)
    return _file(img,'arena-scene.png')

def panel_file(kind,progress=0):
    palette={'event':((211,152,72),(29,19,30),'THE DUNGEON AWAITS','SEVEN DAYS • ONE HUNDRED FLOORS'),
             'workshop':((198,125,66),(30,21,21),'THE FORGE','CRAFT • UPGRADE • EVOLVE'),
             'wallet':((207,170,80),(31,24,22),'TREASURY','GOLD • MATERIALS • EQUIPMENT'),
             'leaderboard':((203,170,92),(23,20,33),'HALL OF CHAMPIONS','THE TOP THREE WILL BE REMEMBERED'),
             'fighter':((96,154,193),(17,25,39),'THE ADVENTURER','YOUR LEGEND IS STILL BEING WRITTEN'),
             'arena':((171,114,220),(23,17,40),'CHAMPIONSHIP ARENA','FIVE TRIALS • FIVE HUNDRED POINTS')}
    accent,dark,title,sub=palette[kind]
    return _file(scene(title,sub,accent,dark,8000+progress,boss=kind in ('leaderboard','arena')),'dungeon-panel.png')
