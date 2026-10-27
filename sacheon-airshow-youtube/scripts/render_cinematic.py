#!/usr/bin/env python3
"""Integrated cinematic path: supplied ZIP + existing gallery FFmpeg helpers.

Temporary exports explicitly disclose absent narration. A real recording uses
speech timestamps, never the provisional reading captions, for later exports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

PROJECT = Path(__file__).resolve().parents[1]
CINEMATIC = PROJECT / 'cinematic'
sys.path.insert(0, str(CINEMATIC))
import trailer as supplied
from audio_design import synthesize_score
from graphics_design import generate_graphics
from narration_sync import prepare_narration
from render_framewise import ensure_ffmpeg


def run(command):
    subprocess.run([str(x) for x in command], check=True)


def ff(*args):
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *args])


def metadata(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams',
        '-of', 'json', str(path)], text=True))


def asset_hashes():
    return {str(p.relative_to(PROJECT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((PROJECT / 'assets').rglob('*')) if p.is_file()}


def font(size, bold=False):
    path = CINEMATIC / 'assets/fonts' / ('NotoSansKR-Bold.ttf' if bold else 'NotoSansKR-Regular.ttf')
    return ImageFont.truetype(str(path), size)


def prepare_still(source, destination, scene):
    """Compose a video keyframe; never write to the source photograph."""
    with Image.open(source) as original:
        im = ImageOps.exif_transpose(original).convert('RGB')
    if scene['id'] == '08':
        canvas = Image.new('RGB', (1920, 1080), (5, 10, 19))
        character = ImageOps.contain(im, (650, 720), Image.Resampling.LANCZOS)
        canvas.paste(character, (1190, 180))
        draw = ImageDraw.Draw(canvas)
        draw.text((125, 295), '하늘을 설계하다', font=font(90, True), fill='#F4F5F5')
        draw.text((132, 430), '2026 SACHEON AIRSHOW', font=font(32), fill='#77C9DA')
        draw.line((135, 518, 350, 518), fill='#E4B76F', width=3)
        draw.text((132, 563), '10년 뒤, 우리의 하늘은', font=font(42), fill='#D5DFE6')
        draw.text((132, 628), '어떤 모습일까.', font=font(42), fill='#D5DFE6')
        draw.text((132, 800), 'PHOTO BY AJP YOO NA-HYUN', font=font(24), fill='#95A8BB')
    elif scene['id'] in ('03', '04', '05', '06'):
        canvas = ImageOps.fit(im, (1920, 1080), Image.Resampling.LANCZOS)
    elif scene['id'] == '01':
        canvas = ImageOps.fit(im, (1920, 1080), Image.Resampling.LANCZOS)
    else:
        # Fit complete formations inside the scope window; soft overscan behind.
        canvas = ImageOps.fit(im, (1920, 1080), Image.Resampling.LANCZOS)
        canvas = ImageEnhance.Brightness(canvas.filter(ImageFilter.GaussianBlur(55))).enhance(.40)
        photo = ImageOps.contain(im, (1840, 830), Image.Resampling.LANCZOS)
        canvas.paste(photo, ((1920-photo.width)//2, (1080-photo.height)//2))
    canvas.save(destination, compress_level=1)


def render_shot(source, destination, seconds, scene, shot_index, width, height, fps):
    # The ZIP renderer's moving-still path is reused, with conservative zoom.
    scene_copy = {**scene, 'duration': seconds}
    supplied.render_scene(scene_copy, source, destination, width=width, height=height,
                          fps=fps, transition=0, is_last=True, draft=False)


def create_visuals(scenes, work, width, height, fps, transition):
    scene_paths = []
    for index, scene in enumerate(scenes):
        references = scene['media'] if isinstance(scene['media'], list) else [scene['media']]
        total = float(scene['duration']) + (transition if index < len(scenes)-1 else 0)
        total_frames = round(total * fps)
        base, extra = divmod(total_frames, len(references))
        shots = []
        for shot_index, ref in enumerate(references):
            source = (CINEMATIC / ref).resolve()
            if not source.is_file():
                raise FileNotFoundError(f'Scene {scene["id"]} asset missing: {source}')
            still = work / f'keyframe_{scene["id"]}_{shot_index}.png'
            prepare_still(source, still, scene)
            shot = work / f'shot_{scene["id"]}_{shot_index}.mp4'
            frames = base + (shot_index < extra)
            render_shot(still, shot, frames/fps, scene, shot_index, width, height, fps)
            shots.append(shot)
        clip = work / f'scene_{scene["id"]}.mp4'
        if len(shots) == 1:
            shutil.copyfile(shots[0], clip)
        else:
            manifest = work / f'concat_{scene["id"]}.txt'
            manifest.write_text(''.join(f"file '{x.as_posix()}'\n" for x in shots))
            ff('-f', 'concat', '-safe', '0', '-i', manifest, '-c', 'copy', clip)
        scene_paths.append(clip)
        print(f'VISUAL {index+1}/{len(scenes)}: {scene["id"]}', flush=True)
    visuals = work / 'visuals.mp4'
    supplied.crossfade_scenes(scene_paths, scenes, transition, visuals, draft=False)
    return visuals


def temp_cues(scenes):
    cues, cursor = [], 0.0
    for scene in scenes:
        for cue in scene['narration_cues']:
            cues.append({**cue, 'start': cursor+cue['start'], 'end': cursor+cue['end']})
        cursor += scene['duration']
    return cues


def write_srt(cues, path):
    path.write_text('\n\n'.join(
        f"{i}\n{supplied.timestamp(c['start'])} --> {supplied.timestamp(c['end'])}\n{c['text']}"
        for i, c in enumerate(cues, 1))+'\n', encoding='utf-8-sig')


def wrap_caption(text):
    lines, line = [], ''
    for word in text.split():
        trial = (line+' '+word).strip()
        if len(trial) > 31 and line:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    if len(lines) > 3:
        raise ValueError('Caption exceeds three lines; provide shorter speech segments.')
    return r'\N'.join(lines)


def write_ass(scenes, cues, path, seconds, temporary):
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Voice,Noto Sans KR,42,&H00FFFFFF,&H000000FF,&H00100B06,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,120,120,83,1
Style: Title,Noto Sans KR,46,&H00F7F2EA,&H000000FF,&H0020180B,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,7,122,120,158,1
Style: Disclosure,Noto Sans KR,25,&H00D8DDDC,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,9,120,120,65,1
Style: Status,Noto Sans KR,26,&H008EC3E9,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,7,120,120,65,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    def event(start, end, style, text, fade=False):
        safe = text.replace('{', '(').replace('}', ')')
        if fade:
            safe = r'{\fad(180,200)}' + safe
        events.append(f'Dialogue: 0,{supplied.timestamp(start,ass=True)},{supplied.timestamp(end,ass=True)},{style},,0,0,0,,{safe}')
    if temporary:
        event(0, seconds, 'Status', '임시본 · 한국어 내레이션 미포함')
    else:
        event(0, seconds, 'Status', '한국어 내레이션 · 발화 타임스탬프 자막')
    cursor = 0.0
    for scene in scenes:
        end = cursor + scene['duration']
        event(cursor, end, 'Disclosure', scene['disclosure'])
        if scene['id'] not in ('03', '04', '05', '06', '08'):
            event(cursor+.15, min(end-.3, cursor+3.5), 'Title', scene['title'], True)
        cursor = end
    for cue in cues:
        event(cue['start'], cue['end'], 'Voice', wrap_caption(cue['text']))
    path.write_text(header+'\n'.join(events)+'\n', encoding='utf-8-sig')


def mix(visuals, score, voice, captions, destination, seconds, fps):
    inputs = ['-i', visuals, '-i', score]
    if voice:
        inputs.extend(['-i', voice])
        af = ('[2:a]asplit=2[key][voice];[1:a][key]sidechaincompress='
              'threshold=0.015:ratio=5:attack=25:release=350[bg];'
              '[bg][voice]amix=inputs=2:normalize=0,alimiter=limit=0.94[a]')
    else:
        af = '[1:a]alimiter=limit=0.94[a]'
    # Fixed overlays are composited after the camera moves, keeping captions still.
    escaped = str(captions).replace('\\', '/').replace(':', r'\:').replace("'", r"\'")
    fonts = str(CINEMATIC / 'assets/fonts')
    vf = (f'drawbox=x=0:y=0:w=iw:h=116:color=black:t=fill,'
          f'drawbox=x=0:y=ih-116:w=iw:h=116:color=black:t=fill,'
          f"ass=filename='{escaped}':fontsdir='{fonts}',"
          f'fade=t=in:st=0:d=0.3,fade=t=out:st={seconds-.5}:d=0.5')
    ff(*inputs, '-filter_complex_threads', '1', '-filter_complex', af,
       '-map', '0:v:0', '-map', '[a]', '-vf', vf, '-r', fps,
       '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-threads', '2',
       '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '256k', '-ar', '48000',
       '-ac', '2', '-t', f'{seconds:.3f}', '-movflags', '+faststart', destination)


def verify(path, seconds, width, height, fps, cues, before, temporary):
    data = metadata(path)
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
    assert abs(float(data['format']['duration'])-seconds) < .02
    assert (video['width'], video['height']) == (width, height)
    assert video['codec_name'] == 'h264' and audio['codec_name'] == 'aac'
    assert round(float(video['duration'])*fps) == round(seconds*fps)
    assert audio['sample_rate'] == '48000' and audio['channels'] == 2
    assert asset_hashes() == before, 'Original assets changed'
    assert all(0 <= c['start'] < c['end'] <= seconds for c in cues)
    assert all(a['end'] <= b['start'] for a,b in zip(cues, cues[1:]))
    # Decode both complete streams, not just the container headers.
    ff('-i', path, '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-')
    pcm = subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0',
                                  '-f','f32le','-ac','2','-ar','48000','-'])
    import numpy as np
    samples = np.frombuffer(pcm, dtype='<f4')
    rms = float(np.sqrt(np.mean(samples*samples)))
    peak = float(np.max(np.abs(samples)))
    assert rms > .005 and peak < 1, 'Audio is silent or clipped'
    return {'status': 'temporary_render_verified' if temporary else 'narrated_render_needs_listening_review',
            'file': str(path), 'duration_seconds': float(data['format']['duration']),
            'resolution': [width,height], 'aspect_ratio': '16:9', 'fps':fps,
            'video_codec':video['codec_name'], 'frame_count': int(video.get('nb_frames',round(seconds*fps))),
            'audio': {'codec':audio['codec_name'], 'sample_rate':48000,'channels':2,
                      'rms_dbfs':20*math.log10(rms),'peak_dbfs':20*math.log10(peak),
                      'narration_present':not temporary,
                      'music':'Original code-synthesized score',
                      'effects':'Synthesized engine, fly-by, impacts, transitions; not field recordings'},
            'subtitles':{'burned_in':True, 'language':'ko','cue_count':len(cues),
                         'timing':'provisional_without_narration' if temporary else 'speech_timestamps',
                         'speech_sync_verified':False},
            'original_assets_sha256_unchanged':True,'full_stream_decode':'passed',
            'kf21_photo_available':False,'kf21_coverage':'separate explanatory graphics',
            'ffprobe':data}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--temporary', action='store_true', help='Explicitly export without narration')
    parser.add_argument('--narration', type=Path)
    parser.add_argument('--alignment-json', type=Path)
    parser.add_argument('--transcribe', action='store_true',
                        help='Allow optional paid speech transcription API for a supplied recording')
    parser.add_argument('--output-dir', type=Path, default=PROJECT/'output/cinematic')
    args = parser.parse_args()
    if args.temporary == bool(args.narration):
        parser.error('Choose --temporary or --narration AUDIO (exactly one).')
    ensure_ffmpeg()
    before = asset_hashes()
    generate_graphics(CINEMATIC)
    config = json.loads((CINEMATIC/'storyboard.json').read_text())
    assert sum(s['duration'] for s in config['scenes']) == 60
    scenes = [dict(s) for s in (config['scenes'][:2] if args.preview else config['scenes'])]
    if args.preview:
        for s in scenes:
            s['duration'] = 3
        scenes[0]['narration_cues'] = [{'start':.4,'end':2.8,'text':'2036년, 조종석에 앉은 나를 상상해요.'}]
        scenes[1]['media'] = scenes[1]['media'][:1]
        scenes[1]['narration_cues'] = [{'start':.4,'end':2.8,'text':'그 꿈은 2026 사천에어쇼에서 시작됐어요.'}]
    seconds = sum(s['duration'] for s in scenes)
    width,height,fps = config['width'],config['height'],config['fps']
    # Exact integer-frame overlap avoids fractional-frame duration drift.
    transition = round(config['transition_seconds']*fps)/fps
    output = args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=True)
    label = f'{seconds}s_' + ('TEMP' if args.temporary else 'narrated')
    work = PROJECT.parent/'work'/f'cinematic_{label}'
    work.mkdir(parents=True,exist_ok=True)
    cache = work/'fontcache'
    cache.mkdir(exist_ok=True)
    fontconfig = work/'fontconfig.conf'
    fontconfig.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">'
                          '<fontconfig><dir>'+str(CINEMATIC/'assets/fonts')+'</dir>'
                          '<cachedir>'+str(cache)+'</cachedir></fontconfig>')
    os.environ['FONTCONFIG_FILE'] = str(fontconfig)
    supplied.WORK = work
    # Bound decoder/encoder/filter threads in every FFmpeg call in the ZIP path.
    def controlled_command(command, **kwargs):
        command = [str(x) for x in command]
        if command[0] == 'ffmpeg':
            command[1:1] = ['-threads','2','-filter_threads','1','-filter_complex_threads','1']
            command[-1:-1] = ['-threads','2']
        subprocess.run(command,cwd=CINEMATIC,check=True)
    supplied.command = controlled_command
    captions = output/f'captions_{label}.ass'
    srt = output/f'captions_{label}.srt'
    voice = None
    alignment = None
    if args.narration:
        voice = work/'narration.wav'
        alignment = prepare_narration(args.narration,voice,srt,duration=seconds,
                                      backend='openai' if args.transcribe else 'offline',
                                      alignment_json=args.alignment_json)
        cues = alignment['cues']
    else:
        cues = temp_cues(scenes)
        write_srt(cues,srt)
    write_ass(scenes,cues,captions,seconds,args.temporary)
    visuals = create_visuals(scenes,work,width,height,fps,transition)
    score = work/'original_music_and_sfx.wav'
    synthesize_score(score,scenes,seconds)
    destination = output/f'sacheon_trailer_{label}_1080p.mp4'
    mix(visuals,score,voice,captions,destination,seconds,fps)
    report = verify(destination,seconds,width,height,fps,cues,before,args.temporary)
    report['narration_alignment'] = alignment
    report_path = output/f'verification_{label}.json'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for point in ((1,2.1,3.8,5.2) if args.preview else (2,10,20,26,36,46,53,57)):
        ff('-ss',point,'-i',destination,'-frames:v','1','-q:v','2',work/f'check_{point}.jpg')
    print(f'VERIFIED {destination}: {seconds}s / {width}x{height} / {fps}fps / stereo audio / Korean captions',flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError,ValueError,FileNotFoundError,subprocess.CalledProcessError,AssertionError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        raise SystemExit(1)
