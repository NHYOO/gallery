"""Mix the supplied Junho recording and two uploaded Mixkit effects.

Reuses the existing cinematic score. Only resampling, gain, envelopes and peak
control are applied to the voice; neither pitch nor playback speed is changed.
All source files remain untouched. Intermediate stems belong in work/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

import numpy as np
from scipy.io import wavfile


RATE = 48_000
SECONDS = 60.0
VOICE_START = 3.0
FRAMES = int(RATE * SECONDS)


def _run(args):
    subprocess.run([str(a) for a in args], check=True)


def _ff(*args):
    _run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', *args])


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _decode(path):
    data = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0',
        '-f', 'f32le', '-ac', '2', '-ar', str(RATE), '-'])
    return np.frombuffer(data, dtype='<f4').reshape(-1, 2).copy()


def _write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), RATE, np.asarray(data, dtype=np.float32))


def _db(value):
    return 20 * math.log10(max(float(value), 1e-12))


def _rms(data):
    return float(np.sqrt(np.mean(np.square(data, dtype=np.float64)))) if data.size else 0.0


def _loudness(path):
    result = subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'info', '-i', str(path),
        '-af', 'loudnorm=I=-16:TP=-1:LRA=11:print_format=json', '-f', 'null', '-'
    ], capture_output=True, text=True, check=True)
    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', result.stderr, re.S)
    if not matches:
        raise RuntimeError('Could not measure program loudness.')
    stats = json.loads(matches[-1])
    return {'integrated_lufs': float(stats['input_i']),
            'true_peak_dbtp': float(stats['input_tp']),
            'loudness_range_lu': float(stats['input_lra'])}


def _fade(audio, attack, release):
    audio = audio.copy()
    n = len(audio)
    a = min(n, max(1, round(attack * RATE)))
    r = min(n, max(1, round(release * RATE)))
    audio[:a] *= np.sin(np.linspace(0, np.pi / 2, a, dtype=np.float32))[:, None] ** 2
    audio[-r:] *= np.cos(np.linspace(0, np.pi / 2, r, dtype=np.float32))[:, None] ** 2
    return audio


def _voice_activity(timeline):
    """Ten-ms energy analysis with look-ahead, syllable hold and smooth release."""
    hop = 480
    blocks = timeline.mean(axis=1).reshape(-1, hop)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1))
    flags = rms > 0.004
    held = flags.copy()
    # Start lowering the bed slightly before consonants and hold through syllables.
    for shift in range(1, 7):
        held[:-shift] |= flags[shift:]
    for shift in range(1, 13):
        held[shift:] |= flags[:-shift]
    smooth = np.zeros(len(held), dtype=np.float32)
    state = 0.0
    for i, target in enumerate(held.astype(np.float32)):
        tau = .022 if target > state else .22
        coefficient = math.exp(-.01 / tau)
        state = coefficient * state + (1-coefficient) * target
        smooth[i] = state
    centers = np.arange(len(smooth)) * hop + hop / 2
    activity = np.interp(np.arange(FRAMES), centers, smooth).astype(np.float32)
    return activity, np.repeat(flags, hop), rms


def _add(target, clip, start):
    offset = round(float(start) * RATE)
    if offset < 0:
        clip = clip[-offset:]
        offset = 0
    count = min(len(clip), len(target)-offset)
    if count > 0:
        target[offset:offset+count] += clip[:count]


def _pan(clip, reverse=False):
    # A gentle equal-power passage supplements, rather than replaces, source stereo.
    progress = np.linspace(0, 1, len(clip), dtype=np.float32)
    if reverse:
        progress = 1-progress
    left = .35 + .65 * np.cos(progress * np.pi / 2)
    right = .35 + .65 * np.sin(progress * np.pi / 2)
    return clip * np.column_stack((left, right))


def build_mix(project_root, work_dir, destination, cue_times=None, event_times=None):
    """Build a 60s master and reviewable stems without altering the source audio.

    event_times accepts {'kf21': seconds, 'flybys': [pass_center_seconds, ...]}.
    The fly-by source's audible passage is centered at the requested event time.
    cue_times is retained for renderer metadata; ducking follows actual voice RMS.
    """
    root, work, destination = map(lambda p: Path(p).resolve(),
                                   (project_root, work_dir, destination))
    work.mkdir(parents=True, exist_ok=True)
    sources = {key: root/'assets'/name for key, name in {
        'narration': 'narration.mp3', 'flyby': 'mixkit-aircraft-flyby-3170.wav',
        'rumble': 'mixkit-jet-plane-flying-rumble-1587.wav'}.items()}
    score = root.parent/'work/cinematic_60s_TEMP/original_music_and_sfx.wav'
    if not score.is_file():
        # The previous MP4 has the same score and remains a valid reuse source.
        score = root/'output/cinematic/sacheon_trailer_60s_TEMP_1080p.mp4'
    sources['existing_score'] = score
    for source in sources.values():
        if not source.is_file():
            raise FileNotFoundError(f'Required existing audio is missing: {source}')
    if destination in sources.values():
        raise ValueError('The output must be separate from every original audio input.')
    hashes = {str(p): _hash(p) for p in sources.values()}
    raw_voice = _decode(sources['narration'])
    voice_seconds = len(raw_voice)/RATE
    if VOICE_START + voice_seconds > SECONDS:
        raise ValueError('The unmodified narration does not fit after the 3s opening.')
    source_loudness = _loudness(sources['narration'])
    voice_gain_db = min(5.0, -18-source_loudness['integrated_lufs'])
    normalized = work/'voice_normalized.wav'
    # True-peak control is amplitude-only. latency=1 compensates limiter look-ahead.
    _ff('-i', sources['narration'], '-map', '0:a:0', '-af',
        f'aresample=192000,volume={10**(voice_gain_db/20):.9f},'
        'alimiter=limit=0.707946:level=false:latency=1,aresample=48000',
        '-ac', '2', '-c:a', 'pcm_f32le', normalized)
    voice_clip = _decode(normalized)
    if len(voice_clip) != len(raw_voice):
        raise RuntimeError('Voice sample count changed; playback duration must be preserved.')
    voice = np.zeros((FRAMES, 2), dtype=np.float32)
    _add(voice, voice_clip, VOICE_START)
    activity, voiced_mask, frame_rms = _voice_activity(voice)
    raw_bed = _decode(score)
    bed = np.zeros_like(voice)
    bed[:min(FRAMES,len(raw_bed))] = raw_bed[:FRAMES]
    t = np.arange(FRAMES, dtype=np.float32)/RATE
    voice_end = VOICE_START+voice_seconds
    # Existing score returns to the foreground between phrases and after the voice.
    music_db = 3.0 - 14.0*activity
    outro = np.clip((t-voice_end)/1.8, 0, 1)
    music_db += 7.0*outro
    bed *= np.power(10.0,music_db/20)[:,None]
    bed *= np.clip(t/.9,0,1)[:,None]
    ending_fade = np.clip((SECONDS-t)/.8,0,1)
    bed *= ending_fade[:,None]

    events = event_times or {}
    kf21 = float(events.get('kf21', events.get('kf21_time', 18.0)))
    flybys = list(events.get('flybys', events.get('flyby_times', [10.1,15.7])))[:2]
    rumble, flyby = _decode(sources['rumble']), _decode(sources['flyby'])
    effects = np.zeros_like(voice)
    event_report = []
    opening = _fade(rumble[:round(3.8*RATE)],1.65,1.1)*.75
    _add(effects, opening,0)
    event_report.append({'source':'rumble','start':0.0,'end':3.8,'role':'opening_engine_rise'})
    detail = _fade(rumble[round(6*RATE):round(10.6*RATE)],.4,1.1)*.55
    _add(effects,detail,kf21)
    event_report.append({'source':'rumble','start':kf21,'end':kf21+len(detail)/RATE,'role':'KF-21_explanatory_graphic'})
    # Retain the complete audible fly-by, omitting only the source's trailing silence.
    passage = flyby[round(.45*RATE):round(7.5*RATE)]
    peak_hop = 4800
    peak_blocks = passage[:len(passage)//peak_hop*peak_hop].reshape(-1,peak_hop,2)
    pass_peak_offset = (int(np.argmax(np.mean(peak_blocks*peak_blocks,axis=(1,2))))+.5)*.1
    for index, center in enumerate(flybys):
        start = max(0,float(center)-pass_peak_offset)
        clip = _pan(_fade(passage,.22,.65), reverse=bool(index%2))*.50
        _add(effects,clip,start)
        event_report.append({'source':'flyby','start':start,'end':start+len(clip)/RATE,
                             'pass_center':float(center),'role':'photo_formation_passage',
                             'source_peak_offset_seconds':pass_peak_offset,
                             'pan':'left_to_right' if index%2==0 else 'right_to_left'})
    sfx_db = -18.0*activity
    effects *= np.power(10,sfx_db/20)[:,None]
    effects *= ending_fade[:,None]
    voice_path,bed_path,sfx_path = (work/name for name in ('voice_stem.wav','bed_stem.wav','sfx_stem.wav'))
    for path, samples in ((voice_path,voice),(bed_path,bed),(sfx_path,effects)):
        _write(path,samples)
    combined = work/'mix_before_master.wav'
    _write(combined,voice+bed+effects)
    pre_master = _loudness(combined)
    master_gain_db = max(-5,min(6,-16-pre_master['integrated_lufs']))
    master = work/'final_mix.wav'
    _ff('-i',combined,'-af',
        f'aresample=192000,volume={10**(master_gain_db/20):.9f},'
        'alimiter=limit=0.870964:level=false:latency=1,aresample=48000,'
        'apad=whole_dur=60,atrim=end_sample=2880000',
        '-ar',str(RATE),'-ac','2','-c:a','pcm_s24le',master)
    if destination != master:
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.suffix.lower() in ('.aac','.m4a','.mp4'):
            _ff('-i',master,'-c:a','aac','-b:a','256k','-t','60',destination)
        else:
            _ff('-i',master,'-c:a','pcm_s24le',destination)
    final = _decode(master)
    if len(final)!=FRAMES or np.max(np.abs(final)) >= 1:
        raise RuntimeError('Master duration or clipping verification failed.')
    after = {str(p):_hash(p) for p in sources.values()}
    if after != hashes:
        raise RuntimeError('Source audio changed.')
    gap_mask = (activity<.15) & (t>=VOICE_START) & (t<voice_end)
    background = bed+effects
    snr = _db(_rms(voice[voiced_mask]))-_db(_rms(background[voiced_mask]))
    final_loudness = _loudness(master)
    if final_loudness['true_peak_dbtp'] > -0.9:
        raise RuntimeError('True-peak headroom check failed.')
    report = {'sample_rate':RATE,'channels':2,'duration':len(final)/RATE,
        'narration':{'source':str(sources['narration']),'start':VOICE_START,
                     'end':voice_end,'decoded_duration':voice_seconds,
                     'decoded_samples':len(raw_voice),'pitch_changed':False,
                     'speed_changed':False,'source_samples_retained':True,
                     'gain_db':voice_gain_db,'source_loudness':source_loudness},
        'mix':{'loudness':final_loudness,'master_gain_db':master_gain_db,
               'sample_peak_dbfs':_db(np.max(np.abs(final))),
               'narration_over_background_rms_db':snr,
               'music_duck_at_speech_db':-14,'effects_duck_at_speech_db':-18,
               'pause_music_recovery_db':14,'pause_seconds_detected':float(gap_mask.sum()/RATE)},
        'effect_events':event_report,'provided_cue_count':len(cue_times or []),
        'paths':{'voice_stem':str(voice_path),'bed_stem':str(bed_path),'sfx_stem':str(sfx_path),
                 'master':str(master),'destination':str(destination)},
        'source_sha256':hashes,'source_files_unchanged':True,
        'method':'Existing procedural score + supplied audio; voice RMS look-ahead ducking; amplitude-only true-peak control'}
    (work/'audio_mix_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--work-dir',type=Path,default=Path('/workspace/gallery/work/narrated_final/audio_test'))
    args=parser.parse_args()
    report=build_mix(args.project_root,args.work_dir,args.work_dir/'final_mix.wav')
    print(json.dumps(report,ensure_ascii=False,indent=2))
