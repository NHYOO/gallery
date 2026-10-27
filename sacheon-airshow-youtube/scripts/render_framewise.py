#!/usr/bin/env python3
"""Self-contained 2026 Sacheon Airshow 16:9 motion-graphics renderer.

Uses only Pillow + system FFmpeg/FFprobe; no generative image/video model,
no network calls, no large AI model downloads, no Remotion dependencies.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

FPS=30
SCENES=[
    ('intro',0,8,'하늘을 설계하다','2026 SACHEON AIRSHOW'),
    ('kf21',8,20,'KF-21 BORAMAE','FROM BLUEPRINT TO SKY'),
    ('aircraft',20,32,'AIRCRAFT','THE MACHINES OF SACHEON'),
    ('eagles',32,44,'BLACK EAGLES','TRAILS ACROSS THE SKY'),
    ('highlight',44,54,'PRECISION  ·  POWER  ·  FLIGHT','AIRSHOW HIGHLIGHTS'),
    ('ending',54,60,'2026 SACHEON AIRSHOW','PHOTO BY AJP YOO NA-HYUN'),
]
TEAL=(63,214,247)
WHITE=(241,248,255)
NAVY=(6,15,29)
DEMO_MAP={
    'eagles':['be8.jpg','arcs.jpg','be5.jpg','taeg.jpg','burst.jpg','cross.jpg'],
    'aircraft':['t50.jpg','kc330.jpg','bennett.jpg','bepark.jpg','f35.jpg'],
    'highlight':['burst.jpg','cross.jpg','kid.jpg','bennett.jpg','kc330.jpg'],
    'ending':['arcs.jpg','be8.jpg'],
    # KF-21 must be confirmed from a user-created manifest before labeling.
    'kf21':[],
}

@dataclass(frozen=True)
class Photo:
    path:Path
    label:str=''


def log(s):
    print(s,flush=True)


def ensure_ffmpeg():
    for exe in ('ffmpeg','ffprobe'):
        if not shutil.which(exe):
            raise RuntimeError(f'{exe} was not found. macOS: brew install ffmpeg; Linux: sudo apt install ffmpeg')


def fonts():
    paths=[
        '/System/Library/Fonts/AppleSDGothicNeo.ttc',
        '/System/Library/Fonts/AppleGothic.ttf',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/NanumGothic.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    return next((s for s in paths if Path(s).exists()),None)

FONT_PATH=fonts()
@functools.lru_cache(maxsize=32)
def font(px):
    if FONT_PATH:
        try:return ImageFont.truetype(FONT_PATH,max(9,round(px)))
        except OSError:pass
    return ImageFont.load_default()


def file_list(photos):
    return sorted([p for p in photos.rglob('*') if p.is_file() and p.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.tif','.tiff'}],key=lambda p:p.name.casefold())


def load_catalog(photos,manifest):
    allfiles=file_list(photos)
    if not allfiles:raise RuntimeError('No photos found. Put photographs in input/photos/ or use --photos PATH.')
    index={p.name.casefold():p for p in allfiles}
    categories={}
    specified={}
    if manifest and manifest.exists():
        cfg=json.loads(manifest.read_text(encoding='utf-8'))
        specified=cfg.get('categories',{})
        if not isinstance(specified,dict):raise ValueError('manifest.categories must be an object')
    elif photos.name=='demo_photos':
        specified=DEMO_MAP
    for tag in ['intro','kf21','aircraft','eagles','highlight','ending']:
        names=specified.get(tag,[])
        if isinstance(names,str):names=[names]
        chosen=[]
        for name in names:
            p=photos/name
            if not p.is_file():p=index.get(Path(name).name.casefold())
            if p and p.is_file() and p not in chosen:chosen.append(p)
            else:log(f'WARNING: photo entry missing: {name}')
        categories[tag]=chosen
    if not categories['aircraft']:categories['aircraft']=allfiles[:]
    if not categories['eagles']:categories['eagles']=categories['aircraft'][:]
    if not categories['highlight']:categories['highlight']=allfiles[:]
    if not categories['ending']:categories['ending']=categories['highlight'][:1]
    if not categories['intro']:categories['intro']=categories['ending'][:]
    if not categories['kf21']:
        log('NOTICE: KF-21 identification not confirmed in manifest; scene 2 will show AIRCRAFT without claiming KF-21.')
        categories['kf21']=categories['aircraft'][:]
    return categories, bool(specified.get('kf21'))


def roundrect(d,xy,r,fill,outline=None,width=1):
    d.rounded_rectangle(tuple(map(int,xy)),max(1,int(r)),fill=fill,outline=outline,width=width)


def text(d,at,msg,px,fill=WHITE,anchor=None,stroke=0):
    d.text((round(at[0]),round(at[1])),msg,font=font(px),fill=fill,anchor=anchor,stroke_width=stroke,stroke_fill=NAVY)


def cover_photo(path,w,h,extra=1.11):
    with Image.open(path) as src:
        src=ImageOps.exif_transpose(src).convert('RGB')
        portrait=src.width/src.height<1.28
        canvas_w=int(w*extra); canvas_h=int(h*extra)
        if portrait:
            bg=ImageOps.fit(src,(canvas_w,canvas_h),method=Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(max(4,round(w/40))))
            bg=ImageEnhance.Brightness(bg).enhance(.63)
            fg=ImageOps.contain(src,(int(canvas_w*.74),int(canvas_h*.94)),method=Image.Resampling.LANCZOS)
            x=(canvas_w-fg.width)//2;y=(canvas_h-fg.height)//2
            bg.paste(fg,(x,y))
            return bg
        return ImageOps.fit(src,(canvas_w,canvas_h),method=Image.Resampling.LANCZOS)


class Renderer:
    def __init__(self, photos, confirmed,w,h):
        self.photos=photos;self.confirmed=confirmed;self.w=w;self.h=h
        self.scale=w/1920
        self.cache={};self.edge_cache={}
        self.random=random.Random(20261021)
    def p(self,v):return max(1,int(round(v*self.scale)))
    def get_photo(self,path):
        key=(str(path),self.w,self.h)
        if key not in self.cache:
            self.cache[key]=cover_photo(path,self.w,self.h)
        return self.cache[key]
    def bg(self,tag,sec,scene_start):
        candidates=self.photos[tag]
        # Cycle several photos per scene, every 4 seconds, deterministic.
        index=min(len(candidates)-1,max(0,int((sec-scene_start)/4)))
        photo=candidates[index]
        im=self.get_photo(photo)
        local=(sec-scene_start)%4
        zoom=1.02 + .023 * local/4
        tw=int(self.w*zoom);th=int(self.h*zoom)
        # Source canvas intentionally overscanned; controlled Ken Burns motion.
        source=im.resize((int(im.width*zoom),int(im.height*zoom)),Image.Resampling.BILINEAR)
        move_x=math.sin((sec-scene_start)*.30 + index)*self.p(20)
        move_y=math.cos((sec-scene_start)*.23 + index)*self.p(13)
        x=round((source.width-self.w)/2+move_x)
        y=round((source.height-self.h)/2+move_y)
        x=max(0,min(x,source.width-self.w));y=max(0,min(y,source.height-self.h))
        return source.crop((x,y,x+self.w,y+self.h)),photo
    def gradient(self,im,left=True,bottom=True):
        overlay=Image.new('RGBA',im.size,(0,0,0,0));d=ImageDraw.Draw(overlay,'RGBA')
        if left:
            for i in range(24):
                a=round(105*(1-i/24)**1.55)
                x=round(self.w*.61*i/24)
                d.rectangle((x,0,x+self.w*.61/24+2,self.h),fill=(0,8,22,a))
        if bottom:
            for i in range(14):
                a=round(88*(1-i/14)**1.5)
                y=round(self.h-self.h*.36*(i+1)/14)
                d.rectangle((0,y,self.w,y+self.h*.36/14+2),fill=(0,6,21,a))
        return Image.alpha_composite(im.convert('RGBA'),overlay).convert('RGB')
    def grid(self,d,sec,alpha=1):
        c=(40,110,140)
        step=self.p(115)
        off=int(sec*self.p(14))%step
        for x in range(-step+off,self.w+step,step):
            d.line((x,0,x,self.h),fill=c,width=self.p(1))
        for y in range(0,self.h+step,step):d.line((0,y,self.w,y),fill=c,width=self.p(1))
    def corner_hud(self,d,sec,tag):
        s=self.scale
        m=self.p(70);w=self.w;h=self.h
        color=(86,222,245)
        arm=self.p(50)
        for x,xdir in [(m,1),(w-m,-1)]:
            for y,ydir in [(m,1),(h-m,-1)]:
                d.line((x,y,x+xdir*arm,y),fill=color,width=self.p(2))
                d.line((x,y,x,y+ydir*arm),fill=color,width=self.p(2))
        text(d,(self.p(102),self.p(76)),f'SACHEON  /  2026    {tag.upper()}',self.p(20),fill=WHITE)
        text(d,(self.p(104),h-self.p(93)),f'PHOTO  ·  AJP YOO NA-HYUN',self.p(17),fill=WHITE)
        # design-only ticker, not aircraft telemetry
        barx=w-self.p(416);bary=h-self.p(102)
        d.rectangle((barx,bary,barx+self.p(290),bary+self.p(3)),fill=(53,94,130))
        d.rectangle((barx,bary,barx+self.p(290)*(sec/60),bary+self.p(3)),fill=TEAL)
    def scan(self,d,sec,scene_start):
        x=int(((sec-scene_start)*self.p(330))%(self.w+self.p(150)))
        d.line((x,0,x-self.p(130),self.h),fill=(56,177,207),width=self.p(3))
        d.line((x+self.p(7),0,x-self.p(123),self.h),fill=(179,237,242),width=self.p(1))
    def title_block(self,d,top,bottom,sub=None,lower=False):
        x=self.p(124);y=self.p(550 if lower else 430)
        d.rectangle((x,y-self.p(20),x+self.p(12),y+self.p(165)),fill=TEAL)
        tw=self.p(71 if len(top)<26 else 51)
        text(d,(x+self.p(43),y),top,tw,WHITE)
        text(d,(x+self.p(45),y+self.p(113)),bottom,self.p(28),TEAL)
        if sub:
            text(d,(x+self.p(45),y+self.p(166)),sub,self.p(20),(196,226,238))
    def intro(self,sec,start):
        bg,photo=self.bg('intro',sec,start)
        dark=ImageEnhance.Brightness(bg).enhance(.25+min(.50,max(0,sec-1)*.17))
        im=self.gradient(dark)
        d=ImageDraw.Draw(im)
        self.grid(d,sec)
        if sec<3.7:
            # Outline scanning of the supplied photograph, NOT an engineering blueprint.
            key=str(photo)
            if key not in self.edge_cache:
                source=self.get_photo(photo).resize((self.w,self.h),Image.Resampling.BILINEAR)
                edge_mask=source.convert('L').filter(ImageFilter.FIND_EDGES)
                edge_mask=edge_mask.point(lambda a:255 if a>57 else 0)
                cyan=Image.new('RGBA',edge_mask.size,(55,221,245,0))
                cyan.putalpha(edge_mask)
                self.edge_cache[key]=cyan
            edges=self.edge_cache[key]
            opacity=int(165*min(1,max(0,sec*.65))*max(0,min(1,(4-sec)/1.2)))
            edges=edges.copy();edges.putalpha(edges.getchannel('A').point(lambda a:int(a*opacity/255)))
            im=Image.alpha_composite(im.convert('RGBA'),edges).convert('RGB')
            d=ImageDraw.Draw(im)
        self.scan(d,sec,start)
        self.corner_hud(d,sec,'OUTLINE SCAN')
        self.title_block(d,'하늘을 설계하다','2026 SACHEON AIRSHOW','PHOTO MOTION GRAPHICS')
        return im
    def kf21(self,sec,start):
        bg,photo=self.bg('kf21',sec,start)
        im=self.gradient(bg)
        d=ImageDraw.Draw(im)
        self.scan(d,sec,start)
        self.corner_hud(d,sec,'AIRFRAME STUDY')
        x=self.p(180);y=self.p(260)
        d.ellipse((x-self.p(36),y-self.p(36),x+self.p(36),y+self.p(36)),outline=TEAL,width=self.p(2))
        d.line((x-self.p(80),y,x+self.p(80),y),fill=TEAL,width=self.p(2))
        d.line((x,y-self.p(80),x,y+self.p(80)),fill=TEAL,width=self.p(2))
        d.line((x+self.p(50),y-self.p(30),x+self.p(490),y-self.p(85)),fill=TEAL,width=self.p(2))
        if self.confirmed:
            self.title_block(d,'KF-21 BORAMAE','FROM BLUEPRINT TO SKY','VERIFIED PHOTO LABEL')
        else:
            self.title_block(d,'AIRCRAFT','FROM BLUEPRINT TO SKY','KF-21 IMAGE NOT YET VERIFIED')
        return im
    def aircraft(self,sec,start):
        pics=self.photos['aircraft']
        im=Image.new('RGB',(self.w,self.h),(8,18,33))
        d=ImageDraw.Draw(im)
        gap=self.p(18);edge=self.p(80)
        panel_w=(self.w-2*edge-2*gap)//3
        for i in range(3):
            photo=pics[(int((sec-start)/4)+i)%len(pics)]
            with Image.open(photo) as src:
                src=ImageOps.exif_transpose(src).convert('RGB')
                panel=ImageOps.fit(src,(panel_w,self.p(600)),method=Image.Resampling.BILINEAR)
            left=edge+i*(panel_w+gap)
            im.paste(panel,(left,self.p(233)))
            d.rectangle((left,self.p(233),left+panel_w,self.p(833)),outline=TEAL,width=self.p(3))
            text(d,(left+self.p(16),self.p(854)),f'FRAME  {i+1:02}',self.p(18),fill=TEAL)
        self.corner_hud(d,sec,'PHOTO ARRAY')
        text(d,(self.p(106),self.p(130)),'AIRCRAFT',self.p(70))
        text(d,(self.p(112),self.p(211)),'THE MACHINES OF SACHEON',self.p(24),fill=TEAL)
        return im
    def eagles(self,sec,start):
        bg,_=self.bg('eagles',sec,start)
        im=self.gradient(bg)
        d=ImageDraw.Draw(im)
        self.corner_hud(d,sec,'FORMATION')
        # Abstract decorative guide curves, explicitly not recovered flight paths.
        phase=(sec-start)/12
        points=[]
        for i in range(45):
            x=self.p(1070 + i*15)
            y=self.p(330+100*math.sin(i*.12+phase*3))
            points.append((x,y))
        d.line(points,fill=(58,214,240),width=self.p(3),joint='curve')
        for j in range(6):
            t=(phase*40+j*7)%44
            x,y=points[int(t)]
            d.ellipse((x-self.p(5),y-self.p(5),x+self.p(5),y+self.p(5)),fill=WHITE)
        self.title_block(d,'BLACK EAGLES','TRAILS ACROSS THE SKY')
        return im
    def highlight(self,sec,start):
        phase=sec-start
        if int(phase*2)%3==0:
            im,_=self.bg('highlight',sec,start)
            im=self.gradient(im)
        else:
            photos=self.photos['highlight']
            im=Image.new('RGB',(self.w,self.h),NAVY)
            cnt=2
            for i in range(cnt):
                srcp=photos[(int(phase*2)+i)%len(photos)]
                with Image.open(srcp) as src:
                    src=ImageOps.exif_transpose(src).convert('RGB')
                    box=ImageOps.fit(src,(self.w//2,self.h),method=Image.Resampling.BILINEAR)
                im.paste(box,(i*self.w//2,0))
        d=ImageDraw.Draw(im)
        self.corner_hud(d,sec,'HIGHLIGHTS')
        beats=['PRECISION','POWER','FLIGHT']
        which=min(2,int(phase/3.3334))
        text(d,(self.p(115),self.p(680)),beats[which],self.p(106),WHITE)
        d.rectangle((self.p(115),self.p(797),self.p(880),self.p(805)),fill=TEAL)
        return im
    def ending(self,sec,start):
        bg,_=self.bg('ending',sec,start)
        im=self.gradient(bg)
        d=ImageDraw.Draw(im)
        self.corner_hud(d,sec,'END CARD')
        text(d,(self.w//2,self.p(465)),'2026 SACHEON AIRSHOW',self.p(82),WHITE,anchor='mm')
        d.rectangle((self.p(620),self.p(530),self.w-self.p(620),self.p(535)),fill=TEAL)
        text(d,(self.w//2,self.p(615)),'PHOTO BY AJP YOO NA-HYUN',self.p(34),TEAL,anchor='mm')
        return im
    def frame(self,real_sec,preview=False):
        scene=SCENES[-1]
        for item in SCENES:
            if item[1]<=real_sec<item[2]:scene=item;break
        tag,start,end,*_=scene
        f=getattr(self,tag)(real_sec,start)
        # Simple 10-frame cross fades to dark without altering documentary images.
        local=real_sec-start
        fade_in=min(1,max(0,local/.28))
        fade_out=min(1,max(0,(end-real_sec)/.28))
        if tag=='intro':fade_in=min(1,max(0,real_sec/.45))
        if tag=='ending':fade_out=min(1,max(0,(60-real_sec)/.6))
        factor=min(fade_in,fade_out)
        if factor<1:f=ImageEnhance.Brightness(f).enhance(factor)
        if preview:
            d=ImageDraw.Draw(f)
            text(d,(self.p(1350),self.p(73)),'6s CONTACT PREVIEW',self.p(22),TEAL)
        return f


def make_audio(path,duration):
    # Original procedural audio; safe to use without external licensed tracks.
    sr=22050; n=int(duration*sr)
    data=array('h')
    boundaries=[0,8,20,32,44,54]
    for i in range(n):
        t=i/sr
        ramp=min(1,t/.7,(duration-t)/1.2)
        bed=(math.sin(2*math.pi*82*t)+.42*math.sin(2*math.pi*164.2*t))*.020
        pulse=0
        for b in boundaries:
            x=t-b
            if 0<=x<.28:
                pulse+=(1-x/.28)**2*math.sin(2*math.pi*(620+550*x)*x)*.11
        v=max(-1,min(1,(bed+pulse)*max(0,ramp)))
        data.append(int(v*32767))
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr);f.writeframes(data.tobytes())


def probe(path):
    x=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_name,width,height,r_frame_rate','-of','json',str(path)],capture_output=True,text=True,check=True)
    return json.loads(x.stdout)


def create_contact_sheet(photos,out):
    w,h=420,270
    allp=[]
    for group in photos.values():
        for p in group:
            if p not in allp:allp.append(p)
    sheet=Image.new('RGB',(w*4,h*max(1,math.ceil(len(allp)/4))),(240,246,248))
    d=ImageDraw.Draw(sheet)
    for i,p in enumerate(allp):
        with Image.open(p) as src:
            img=ImageOps.fit(ImageOps.exif_transpose(src).convert('RGB'),(w-20,h-44))
        x=i%4*w+10;y=i//4*h+5
        sheet.paste(img,(x,y))
        text(d,(x+5,y+h-33),p.name,20,fill=(20,40,50))
    sheet.save(out,quality=85)


def main():
    ap=argparse.ArgumentParser(description='Render a 60-second 16:9 documentary-photo motion graphics video.')
    root=Path(__file__).resolve().parents[1]
    ap.add_argument('--photos',type=Path,default=root/'assets'/'demo_photos',help='Folder containing user-supplied airshow photos (do not upload all images through a chat)')
    ap.add_argument('--manifest',type=Path,help='JSON manifest with verified photo groups, especially KF-21')
    ap.add_argument('--output-dir',type=Path,default=(Path.home()/'Desktop'/'Sacheon_Airshow_2026' if (Path.home()/'Desktop').exists() else Path.cwd()/'output'))
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preview',action='store_true',help='6 seconds, 640×360, 1 sec from each scene; sanity-check first')
    mode.add_argument('--full',action='store_true',help='60 seconds, 1920×1080 @ 30fps')
    ap.add_argument('--mute',action='store_true',help='Skip generated procedural audio track')
    ap.add_argument('--preset',choices=['ultrafast','veryfast','medium'],default='veryfast')
    args=ap.parse_args()
    ensure_ffmpeg()
    output=args.output_dir.expanduser().resolve();output.mkdir(parents=True,exist_ok=True)
    photos=args.photos.expanduser().resolve()
    if not photos.exists():raise FileNotFoundError(f'Photos folder not found: {photos}')
    catalog,kf21_verified=load_catalog(photos,args.manifest)
    preview=args.preview
    w,h=(640,360) if preview else (1920,1080)
    nframes=180 if preview else 1800
    duration=nframes/FPS
    r=Renderer(catalog,kf21_verified,w,h)
    final=output/('preview_6s.mp4' if preview else 'sacheon_airshow_2026_youtube.mp4')
    silent=output/('_render_without_audio.mp4' if not preview and not args.mute else final.name)
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r',str(FPS),'-i','pipe:0','-c:v','libx264','-preset',args.preset,'-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(silent)]
    log(f'Rendering {duration:.0f} seconds at {w}×{h} -> {silent}')
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for idx in range(nframes):
            # Six one-second excerpts at each scene's representative point.
            if preview:
                scene_idx=idx//30
                tag,scene_start,scene_end,*_=SCENES[scene_idx]
                sec=scene_start+min((scene_end-scene_start)*.4,2)+(idx%30)/30
            else:sec=idx/FPS
            im=r.frame(sec,preview=preview)
            proc.stdin.write(im.tobytes())
            if idx % (30 if preview else 180)==0:log(f'frame {idx}/{nframes}')
        proc.stdin.close()
        err=proc.stderr.read().decode('utf8',errors='replace')
        code=proc.wait()
        if code:raise RuntimeError(f'FFmpeg failed ({code}): {err[-3000:]}')
    except BaseException:
        try:proc.stdin.close()
        except Exception:pass
        proc.kill();proc.wait();raise
    if not preview and not args.mute:
        audio=output/'_generated_score.wav'
        make_audio(audio,60)
        mux=['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(silent),'-i',str(audio),'-c:v','copy','-c:a','aac','-b:a','128k','-t','60','-movflags','+faststart',str(final)]
        subprocess.run(mux,check=True)
        silent.unlink(missing_ok=True);audio.unlink(missing_ok=True)
    create_contact_sheet(catalog,output/'contact_sheet.jpg')
    thumb=r.frame(56)
    thumb.save(output/'sacheon_airshow_thumbnail.jpg',quality=89)
    report=probe(final)
    sec=float(report['format']['duration'])
    vw=next(s for s in report['streams'] if s.get('width'))
    if abs(sec-duration)>.08 or vw.get('width')!=w or vw.get('height')!=h:
        raise RuntimeError(f'Validation failed, expected {duration}s {w}x{h}: {report}')
    status={
        'status':'rendered_and_verified','preview':preview,'file':str(final),'duration':sec,
        'resolution':[w,h],'fps':FPS,'kf21_label_verified':kf21_verified,
        'source_images':sorted({str(p) for g in catalog.values() for p in g}),
        'article_reference':'https://www.ajunews.com/view/20261023150655387',
        'creation_method':'editorial photos + scripted 2D graphics, not generated flight footage',
        'metadata':report,
    }
    (output/'render_report.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
    log('SUCCESS: '+str(final))
    log(f'Validated: {sec:.3f}s, {w}×{h}, {FPS}fps')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(f'ERROR: {exc}',file=sys.stderr,flush=True)
        sys.exit(1)
