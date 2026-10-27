#!/usr/bin/env python3
"""Fast, reproducible 60-second 16:9 motion graphics using photo cards + FFmpeg.

This production path is optimized for RAM and rendering speed: it prepares
18 authored keyframe stills, renders each moving 2-4s shot via FFmpeg zoompan,
then stream-copies the segments. No per-frame RGB piping or large AI models.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from render_framewise import (
    Renderer,SCENES,load_catalog,ensure_ffmpeg,make_audio,probe,create_contact_sheet,log
)

FPS=30
# Each tuple is a scene ID, local offset, and duration in seconds.
SHOT_TIMINGS=[
    ('intro',0,4),('intro',4,4),
    ('kf21',0,4),('kf21',4,4),('kf21',8,4),
    ('aircraft',0,4),('aircraft',4,4),('aircraft',8,4),
    ('eagles',0,4),('eagles',4,4),('eagles',8,4),
    ('highlight',0,2),('highlight',2,2),('highlight',4,2),('highlight',6,2),('highlight',8,2),
    ('ending',0,3),('ending',3,3)
]
SCENE_START={k:a for k,a,b,*_ in SCENES}

def run(args):
    ensure_ffmpeg()
    output=args.output_dir.expanduser().resolve()
    output.mkdir(parents=True,exist_ok=True)
    photos=args.photos.expanduser().resolve()
    if not photos.exists():raise FileNotFoundError(f'Photo directory not found: {photos}')
    catalog,has_kf21=load_catalog(photos,args.manifest)
    if args.preview:
        w,h=640,360
        shots=[(k,0.4,1) for k,_,_,*_ in SCENES]
    else:
        w,h=1920,1080
        shots=SHOT_TIMINGS
    total=sum(shot[2] for shot in shots)
    assert total==(6 if args.preview else 60)
    renderer=Renderer(catalog,has_kf21,w,h)
    final=output/('preview_6s.mp4' if args.preview else 'sacheon_airshow_2026_youtube.mp4')
    with tempfile.TemporaryDirectory(prefix='sacheon_shots_',dir=output) as temp:
        work=Path(temp)
        clip_paths=[]
        for i,(tag,local,duration) in enumerate(shots):
            scene_start=SCENE_START[tag]
            frame_time=scene_start+local+(0 if args.preview else duration*.5)
            still=work/f'still_{i:02d}.png'
            shot=work/f'shot_{i:02d}.mp4'
            frame=renderer.frame(frame_time)
            frame.save(still,compress_level=1)
            count=duration*FPS
            # zoompan handles movement with FFmpeg's optimized video pipeline.
            # Text and photo move together by 1-5%, staying inside 16:9 safe area.
            pan=(1 if i%2==0 else -1)
            zoom=f"min(1.0+on*0.00017,1.05)"
            x=f"iw/2-(iw/zoom/2)+{pan}*min(on*0.25,12)"
            y="ih/2-(ih/zoom/2)"
            vf=(f"scale={int(w*1.10)}:{int(h*1.10)}:force_original_aspect_ratio=increase,"
                f"crop={int(w*1.10)}:{int(h*1.10)},"
                f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={FPS},"
                f"format=yuv420p")
            cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate',str(FPS),'-i',str(still),
                 '-vf',vf,'-frames:v',str(count),'-c:v','libx264','-preset',args.preset,
                 '-threads','2','-crf','23','-pix_fmt','yuv420p',
                 '-video_track_timescale','30000','-an',str(shot)]
            subprocess.run(cmd,check=True)
            clip_paths.append(shot)
            log(f'Shot {i+1:02d}/{len(shots)}  {tag:<10}  {duration}s')
        concat=work/'shots.txt'
        concat.write_text(''.join("file '"+p.name+"'\n" for p in clip_paths),encoding='utf8')
        muted=work/'silent.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0',
                        '-i',str(concat),'-c','copy','-movflags','+faststart',str(muted)],check=True,cwd=work)
        if args.mute:
            shutil.copyfile(muted,final)
        else:
            audio=work/'original_ui_score.wav'
            make_audio(audio,total)
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(muted),'-i',str(audio),
                            '-c:v','copy','-c:a','aac','-b:a','128k','-t',str(total),
                            '-movflags','+faststart',str(final)],check=True)
    thumb=renderer.ending(56,54)
    thumb.save(output/'sacheon_airshow_thumbnail.jpg',quality=90)
    create_contact_sheet(catalog,output/'contact_sheet.jpg')
    report=probe(final)
    seconds=float(report['format']['duration'])
    video=next(s for s in report['streams'] if 'width' in s)
    if abs(seconds-total)>.08 or (video['width'],video['height'])!=(w,h):
        raise RuntimeError(f'Render failed QA, {seconds}s, {video["width"]}x{video["height"]}; expected {total}s, {w}x{h}')
    details={
        'status':'rendered_and_verified','file':str(final),'preview':args.preview,
        'duration':seconds,'resolution':[w,h],'fps':FPS,
        'engine':'Pillow still keyframes + FFmpeg animated zoompan + H.264',
        'photo_credit':'AJP YOO NA-HYUN','kf21_label_verified':has_kf21,
        'photos_used':sorted({str(p) for group in catalog.values() for p in group}),
        'article':'https://www.ajunews.com/view/20261023150655387',
        'ffprobe':report
    }
    (output/'render_report.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf8')
    log(f'SUCCESS: {final}')
    log(f'FFprobe validated: {seconds:.3f}s, {w}x{h}, H.264')


def main():
    ap=argparse.ArgumentParser(description='Fast 2026 Sacheon Airshow 60-second 16:9 YouTube video renderer')
    root=Path(__file__).resolve().parents[1]
    ap.add_argument('--photos',type=Path,default=root/'assets'/'demo_photos')
    ap.add_argument('--manifest',type=Path)
    ap.add_argument('--output-dir',type=Path,default=(Path.home()/'Desktop'/'Sacheon_Airshow_2026' if (Path.home()/'Desktop').exists() else Path.cwd()/'output'))
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preview',action='store_true',help='six 1s scene samples at 640x360')
    mode.add_argument('--full',action='store_true',help='60 seconds at 1920x1080')
    ap.add_argument('--mute',action='store_true')
    ap.add_argument('--preset',choices=['ultrafast','veryfast','medium'],default='veryfast')
    args=ap.parse_args()
    run(args)

if __name__=='__main__':
    try:main()
    except Exception as ex:
        print('ERROR:',ex,file=sys.stderr)
        sys.exit(1)
