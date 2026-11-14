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
    candidates = ['/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf', '/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for p in candidates:
        try:return ImageFont.truetype(p,size)
        except OSError:pass
    return ImageFont.load_default()

def blend(a,b,t):return tuple(round(x*(1-t)+y*t) for x,y in zip(a,b))

def scene(title, subtitle, accent, dark, seed, boss=False, arena=False, index=0):
    """Illustrated medieval castle hall: stone masonry, heraldry, torchlight and parchment."""
    w,h=1100,440
    rng=random.Random(seed)
    stone=(47,43,39); mortar=(26,24,23); parchment=(222,196,145); ink=(58,37,24)
    im=Image.new('RGB',(w,h),stone); d=ImageDraw.Draw(im)
    # Weathered castle masonry, deliberately muted instead of neon gradients.
    for row,y in enumerate(range(0,h,51)):
        for col,x in enumerate(range(-110,w+110,135)):
            x+=67 if row%2 else 0
            shade=rng.randint(-10,12)
            block=tuple(max(0,min(255,c+shade)) for c in stone)
            d.rectangle((x+2,y+2,x+132,y+48),fill=block,outline=mortar,width=3)
            for _ in range(4):
                xx=x+rng.randint(10,120);yy=y+rng.randint(8,40)
                d.line((xx,yy,xx+rng.randint(4,18),yy+rng.randint(-3,3)),fill=(63,57,49),width=1)
    # Castle battlements across the upper edge.
    d.rectangle((0,0,w,30),fill=(27,26,25))
    for x in range(0,w,100):
        d.rectangle((x,0,x+57,45),fill=(68,62,53),outline=(22,20,19),width=3)
    # Deep gothic arch and iron-bound dungeon doors.
    d.ellipse((330,56,770,520),fill=(21,19,19),outline=(113,101,79),width=17)
    d.rectangle((350,250,750,h),fill=(21,19,19))
    d.polygon([(391,430),(391,215),(550,109),(709,215),(709,430)],fill=(44,32,25),outline=(135,109,75))
    for x in (421,487,553,619,685):
        d.line((x,210,x,420),fill=(114,92,68),width=5)
    for y in (250,337):
        d.line((394,y,706,y),fill=(106,82,57),width=8)
    d.ellipse((660,308,675,323),fill=(193,153,76))
    # Medieval heraldic standards with stitched golden borders.
    for x in (105,900):
        d.line((x,57,x,300),fill=(145,117,69),width=8)
        d.polygon([(x-52,72),(x+52,72),(x+52,260),(x,226),(x-52,260)],fill=blend(accent,(85,32,30),.60),outline=(197,161,94))
        d.line((x-41,85,x+41,85),fill=(208,175,103),width=3)
        d.polygon([(x,120),(x+21,148),(x,194),(x-21,148)],fill=(215,174,96))
        d.line((x-18,154,x+18,154),fill=(85,50,31),width=4)
    # Torch sconces and flickering flames.
    for x in (255,845):
        d.line((x,190,x,272),fill=(133,115,91),width=9)
        d.polygon([(x-15,204),(x+15,204),(x+7,225),(x-7,225)],fill=(72,60,46))
        d.ellipse((x-27,134,x+27,216),fill=(150,89,36))
        d.polygon([(x-17,196),(x-20,165),(x,125),(x+20,165),(x+17,196)],fill=(240,166,60))
        d.polygon([(x-8,192),(x-9,171),(x,150),(x+10,172),(x+8,192)],fill=(255,226,138))
    # Floor flagstones.
    d.polygon([(0,h),(w,h),(730,350),(370,350)],fill=(65,57,47))
    for y in (370,394,425):d.line((0,y,w,y),fill=(30,28,25),width=3)
    for x in (110,260,410,550,690,840,990):d.line((550,350,x,h),fill=(30,28,25),width=2)
    # Boss sigil / shield, hand-drawn heraldic style.
    if boss:
        d.polygon([(550,190),(615,218),(608,296),(550,340),(492,296),(485,218)],fill=(98,32,31),outline=(224,183,105),width=6)
        d.polygon([(550,207),(570,252),(550,308),(530,252)],fill=(225,184,98))
        d.line((510,260,590,260),fill=(225,184,98),width=7)
    # Ornate parchment placard: more traditional fantasy than UI neon text.
    d.rounded_rectangle((28,22,748,129),radius=9,fill=(84,61,39),outline=(179,137,79),width=5)
    d.rounded_rectangle((36,30,740,121),radius=6,fill=parchment,outline=(116,77,43),width=3)
    d.line((50,104,718,104),fill=(150,105,60),width=2)
    display=title.title() if len(title)>24 else title
    d.text((57,42),display,font=font(34,True),fill=ink)
    d.text((59,87),subtitle.replace('•',' | '),font=font(17,True),fill=(108,69,38))
    d.rounded_rectangle((817,23,1071,82),radius=5,fill=(58,37,28),outline=(202,162,94),width=4)
    label='ROYAL TRIAL' if arena else ('BOSS CHAMBER' if boss else 'DUNGEON KEEP')
    d.text((833,40),label,font=font(19,True),fill=(242,211,153))
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
    palette={'doors':((175,120,63),(28,21,19),'THE THREE DOORS','IRON • GOLD • RUNES'),
             'treasure':((211,169,83),(31,23,17),'THE FORGOTTEN TREASURY','CHOOSE YOUR REWARD'),
             'merchant':((172,126,69),(30,23,17),'THE WANDERING MERCHANT','THE KINGDOM TRADES HERE'),
             'elite':((171,93,62),(30,20,19),'THE IRON GUARDIAN','THREE TACTICAL TRIALS'),
             'event':((211,152,72),(29,19,30),'THE DUNGEON AWAITS','SEVEN DAYS • ONE HUNDRED FLOORS'),
             'workshop':((198,125,66),(30,21,21),'THE FORGE','CRAFT • UPGRADE • EVOLVE'),
             'wallet':((207,170,80),(31,24,22),'TREASURY','GOLD • MATERIALS • EQUIPMENT'),
             'leaderboard':((203,170,92),(23,20,33),'HALL OF CHAMPIONS','THE TOP THREE WILL BE REMEMBERED'),
             'raid':((180,95,63),(33,20,17),'THE KINGDOM IS UNDER SIEGE','WORLD BOSS • STAND TOGETHER'),
             'fighter':((96,154,193),(17,25,39),'THE ADVENTURER','YOUR LEGEND IS STILL BEING WRITTEN'),
             'arena':((171,114,220),(23,17,40),'CHAMPIONSHIP ARENA','FIVE TRIALS • FIVE HUNDRED POINTS')}
    accent,dark,title,sub=palette[kind]
    return _file(scene(title,sub,accent,dark,8000+progress,boss=kind in ('leaderboard','arena')),'dungeon-panel.png')
