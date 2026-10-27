#!/usr/bin/env python3
"""Improve the existing trailer using its scene cache and supplied Junho audio.

No photographs, original audio, or previous exports are overwritten. All visual
material is reused; only scene timing, frame rate, captions and sound are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageOps

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent
sys.path.insert(0, str(PROJECT/'cinematic'))
from final_audio_mix import build_mix
from trailer import timestamp

FPS = 24
SECONDS = 60
WIDTH, HEIGHT = 1920, 1080


def ff(*args):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-threads','2','-filter_threads','1','-filter_complex_threads','1',
                    *map(str,args)], check=True)


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],text=True))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def guard_sources():
    paths = list((PROJECT/'assets').rglob('*')) + list((PROJECT/'output/cinematic').rglob('*'))
    return {str(p):sha(p) for p in paths if p.is_file()}


def load_cues(path):
    alignment = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    recorded_hash = alignment.get('metadata',{}).get('source_sha256')
    if recorded_hash != sha(PROJECT/'assets/narration.mp3'):
        raise ValueError('Alignment belongs to a different recording; realignment is required.')
    cues, previous = [], 0.0
    for segment in alignment['segments']:
        start, end = float(segment['start']), float(segment['end'])
        text = segment['text'].strip()
        if not text or not 0 <= start < end <= 53.91 or start < previous:
            raise ValueError('Invalid, overlapping or out-of-recording speech timestamps.')
        cues.append({'start':start+3.0,'end':end+3.0,'text':text})
        previous = end
    if not cues:
        raise ValueError('Real speech alignment is required.')
    return cues, alignment


def load_timeline(path):
    data = json.loads(Path(path).read_text())
    scenes = data['scenes']
    assert [s['id'] for s in scenes] == [f'{i:02}' for i in range(1,9)]
    assert scenes[0]['start'] == 3 and scenes[-1]['end'] == 60
    for a,b in zip(scenes,scenes[1:]):
        assert abs(a['end']-b['start']) < 1e-6
    for s in scenes:
        assert s['end'] > s['start']
        assert abs(s['start']*FPS-round(s['start']*FPS)) < 1e-5
        assert abs(s['end']*FPS-round(s['end']*FPS)) < 1e-5
    return scenes


def reuse_visuals(scenes, cache, work):
    """Retime only already-rendered footage, preserving imagery and camera moves."""
    transition = .5
    rendered = []
    expected = {f"scene_{s['id']}.mp4" for s in scenes}
    if not all((cache/name).is_file() for name in expected):
        archive=PROJECT/'output/narrated_final/reused_scene_cache.zip'
        if not archive.is_file():
            raise FileNotFoundError('Existing clean scene cache is required; no new visual generation is performed.')
        cache=work/'existing_scene_cache';cache.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as zipped:
            if set(zipped.namelist()) != expected:
                raise ValueError('Unexpected paths in the existing scene archive.')
            for name in expected:
                (cache/name).write_bytes(zipped.read(name))
    for index, scene in enumerate(scenes):
        source = cache/f"scene_{scene['id']}.mp4"
        source_duration = float(probe(source)['format']['duration'])
        input_options = ['-i',source]
        target = scene['end']-scene['start'] + (transition if index < len(scenes)-1 else 0)
        count = round(target*FPS)
        vf = (f'setpts=(PTS-STARTPTS)*{target/source_duration:.12f},'
              f'fps={FPS},tpad=stop_mode=clone:stop_duration=0.2,format=yuv420p')
        if index == 0:
            vf += ',fade=t=in:st=0:d=0.45'
        destination = work/f"reused_scene_{scene['id']}.mp4"
        ff(*input_options,'-vf',vf,'-frames:v',count,'-an','-c:v','libx264',
           '-preset','veryfast','-crf','18','-threads','2',destination)
        rendered.append(destination)
        print(f"REUSED {scene['id']} {scene['start']:.3f}–{scene['end']:.3f}s",flush=True)
    filters, current = [], '0:v'
    for index in range(1,len(scenes)):
        label=f'v{index}'
        effect='fadeblack' if scenes[index]['id'] in ('03','06') else 'fade'
        offset=scenes[index]['start']-3.0
        filters.append(f'[{current}][{index}:v]xfade=transition={effect}:duration={transition}:offset={offset:.6f}[{label}]')
        current=label
    inputs=[value for p in rendered for value in ('-i',p)]
    content=work/'reused_content_57s.mp4'
    ff(*inputs,'-filter_complex',';'.join(filters),'-map',f'[{current}]','-an',
       '-frames:v',57*FPS,'-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',content)
    black=work/'opening_black_3s.mp4'
    ff('-f','lavfi','-i',f'color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d=3',
       '-frames:v',3*FPS,'-an','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2',black)
    concat=work/'reused_visuals.txt'
    concat.write_text(f"file '{black.as_posix()}'\nfile '{content.as_posix()}'\n")
    visuals=work/'reused_visuals_60s_24fps.mp4'
    ff('-f','concat','-safe','0','-i',concat,'-c','copy',visuals)
    return visuals


def wrapped(text):
    lines,line=[],''
    for word in text.split():
        trial=(line+' '+word).strip()
        if len(trial)>29 and line:
            lines.append(line);line=word
        else:
            line=trial
    if line:
        lines.append(line)
    if len(lines)>2:
        raise ValueError('Split long captions at meaningful speech boundaries before export.')
    return r'\N'.join(lines)


def captions(scenes,cues,ass_path,srt_path):
    header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Voice,Noto Sans KR,43,&H00FFFFFF,&H000000FF,&H00140D07,&H90000000,0,0,0,0,100,100,0,0,1,3,1,2,120,120,110,1
Style: Title,Noto Sans KR,46,&H00F7F2EA,&H000000FF,&H0020180B,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,7,122,120,158,1
Style: Disclosure,Noto Sans KR,25,&H00D8DDDC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,9,120,120,65,1
Style: Credit,Noto Sans KR,25,&H00D8DDDC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,7,120,120,65,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    def add(start,end,style,text,fade=False):
        text=text.replace('{','(').replace('}',')')
        if fade:
            text=r'{\fad(160,180)}'+text
        events.append(f'Dialogue: 0,{timestamp(start,ass=True)},{timestamp(end,ass=True)},{style},,0,0,0,,{text}')
    add(3,60,'Credit','AI 내레이션 · 준호')
    for scene in scenes:
        add(scene['start'],scene['end'],'Disclosure',scene['disclosure'])
        if scene['id'] in ('01','02','07'):
            add(scene['start']+.15,min(scene['end']-.2,scene['start']+3.2),
                'Title',scene['title'],True)
    for cue in cues:
        add(cue['start'],cue['end'],'Voice',wrapped(cue['text']))
    ass_path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')
    srt_path.write_text('\n\n'.join(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}"
                                    for i,c in enumerate(cues,1))+'\n',encoding='utf-8-sig')


def encode(visuals,mix,ass_path,destination):
    fonts=PROJECT/'cinematic/assets/fonts'
    vf=(f'drawbox=x=0:y=0:w=iw:h=116:color=black:t=fill,'
        f'drawbox=x=0:y=ih-116:w=iw:h=116:color=black:t=fill,'
        f"ass=filename='{ass_path}':fontsdir='{fonts}',fade=t=out:st=59.45:d=0.55")
    ff('-i',visuals,'-i',mix,'-map','0:v:0','-map','1:a:0','-vf',vf,
       '-frames:v',FPS*SECONDS,'-t','60','-r',FPS,'-c:v','libx264','-preset','veryfast',
       '-crf','18','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k',
       '-ar','48000','-ac','2','-movflags','+faststart',destination)


def verify(destination,cues,originals,mix_report,alignment,scenes,work):
    data=probe(destination)
    video=next(x for x in data['streams'] if x['codec_type']=='video')
    audio=next(x for x in data['streams'] if x['codec_type']=='audio')
    assert float(data['format']['duration'])==60.0
    assert (video['width'],video['height'])==(1920,1080)
    assert video['r_frame_rate']=='24/1' and int(video['nb_frames'])==1440
    assert video['codec_name']=='h264' and audio['codec_name']=='aac'
    assert abs(float(audio['duration'])-60)<.001 and abs(float(video['duration'])-60)<.001
    assert audio['sample_rate']=='48000' and audio['channels']==2
    assert all(sha(p)==h for p,h in originals.items()),'A preserved input or old export changed'
    ff('-i',destination,'-map','0:v:0','-map','0:a:0','-f','null','-')
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(destination),
                                 '-map','0:a:0','-f','f32le','-ar','48000','-ac','2','-'])
    samples=np.frombuffer(raw,dtype='<f4')
    peak=float(np.max(np.abs(samples)))
    assert peak<1.0
    report={'status':'rendered_with_supplied_junho_narration',
            'file':str(destination),'duration_seconds':60.0,'resolution':[1920,1080],
            'fps':24,'frames':1440,'aspect_ratio':'16:9','video_codec':'h264',
            'audio_codec':'aac','audio_sample_rate':48000,'audio_channels':2,
            'full_stream_decode':'passed','decoded_audio_peak_dbfs':20*math.log10(peak),
            'preserved_input_count':len(originals),'originals_and_previous_exports_unchanged':True,
            'visuals':'Existing scene clips reused; opening black and speech-based timing edit only',
            'captions':{'language':'ko','burned_in':True,'srt':True,'cue_count':len(cues),
                        'source_offset_seconds':3.0,'timing_basis':alignment.get('metadata',alignment.get('method','local_speech_timestamps'))},
            'mix':mix_report,'scenes':scenes,'ffprobe':data}
    for point in (1,3.8,10,20,28,38,48,55,57.5):
        ff('-ss',point,'-i',destination,'-frames:v','1','-q:v','2',work/f'frame_{point}.jpg')
    first=np.asarray(Image.open(work/'frame_1.jpg'))
    assert np.mean(first)<1,'Opening is not black'
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--alignment',type=Path,required=True)
    ap.add_argument('--timeline',type=Path,required=True)
    ap.add_argument('--scene-cache',type=Path,default=REPO/'work/cinematic_60s_TEMP')
    ap.add_argument('--work-dir',type=Path,default=REPO/'work/narrated_final/render')
    ap.add_argument('--output-dir',type=Path,default=PROJECT/'output/narrated_final')
    args=ap.parse_args()
    work=args.work_dir.resolve();work.mkdir(parents=True,exist_ok=True)
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    cache=work/'fontcache';cache.mkdir(exist_ok=True)
    fc=work/'fonts.conf'
    fc.write_text(f'<?xml version="1.0"?><fontconfig><dir>{PROJECT}/cinematic/assets/fonts</dir><cachedir>{cache}</cachedir></fontconfig>')
    os.environ['FONTCONFIG_FILE']=str(fc)
    originals=guard_sources()
    cues,alignment=load_cues(args.alignment)
    scenes=load_timeline(args.timeline)
    ass=output/'sacheon_trailer_junho_60s_24fps.ass'
    srt=output/'sacheon_trailer_junho_60s_24fps.srt'
    captions(scenes,cues,ass,srt)
    visuals=reuse_visuals(scenes,args.scene_cache.resolve(),work)
    master=work/'final_mix.wav'
    photo=scenes[1]
    events={'kf21':scenes[2]['start'],
            'flybys':[photo['start']+(photo['end']-photo['start'])*.6]}
    mix_report=build_mix(PROJECT,work/'audio',master,cue_times=cues,event_times=events)
    destination=output/'sacheon_trailer_junho_60s_1080p_24fps_FINAL.mp4'
    encode(visuals,master,ass,destination)
    report=verify(destination,cues,originals,mix_report,alignment,scenes,work)
    (output/'verification_junho_final.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(f'VERIFIED {destination}',flush=True)


if __name__=='__main__':
    main()
