#!/usr/bin/env python3
"""Render a Korean 60-second cinematic news trailer from a JSON storyboard.

Requires ffmpeg/ffprobe and the Python packages in requirements.txt.
Uses the user's photos/video; generates captions, TTS narration, soundtrack,
sound design, cinematic moves, scene transitions, and final H.264/AAC MP4.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
STORYBOARD = ROOT / "storyboard.json"
OUTPUT = ROOT / "output"
WORK = OUTPUT / "work"
SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_VIDEO = {".mp4", ".mov", ".mkv", ".webm"}


def command(args: list[str], *, verbose: bool = True, env: dict | None = None) -> None:
    if verbose:
        print("+", shlex.join([str(arg) for arg in args]), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True, env=env)


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height", "-of", "json",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def media_duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def ensure_dependencies() -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise RuntimeError(f"{binary} is missing. Install ffmpeg first.")


def make_demo_image(path: Path, scene: dict, width: int, height: int) -> None:
    """Create an obvious non-photographic test card, never fake news footage."""
    path.parent.mkdir(parents=True, exist_ok=True)
    palettes = [
        ((7, 16, 35), (22, 56, 96)),
        ((8, 33, 66), (58, 113, 172)),
        ((5, 10, 24), (62, 96, 133)),
        ((4, 23, 35), (20, 88, 102)),
        ((13, 20, 38), (62, 68, 100)),
        ((12, 15, 34), (46, 58, 104)),
        ((19, 21, 32), (61, 79, 89)),
        ((36, 24, 41), (144, 91, 67)),
    ]
    a, b = palettes[(int(scene["id"]) - 1) % len(palettes)]
    gradient = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    top = np.array(a, dtype=np.float32)[None, None, :]
    bottom = np.array(b, dtype=np.float32)[None, None, :]
    rgb = np.repeat((top * (1 - gradient) + bottom * gradient).astype("uint8"), width, axis=1)
    image = Image.fromarray(rgb, "RGB")
    draw = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font = ImageFont.truetype(font_path, max(30, width // 28))
    except OSError:
        font = ImageFont.load_default()
    draw.line((0, int(height * 0.66), width, int(height * 0.43)), fill=(106, 161, 194), width=max(2, width // 500))
    draw.line((0, int(height * 0.76), width, int(height * 0.48)), fill=(57, 124, 168), width=max(2, width // 600))
    draw.text((width * 0.06, height * 0.35), f"SCENE {scene['id']}", font=font, fill="white")
    draw.text((width * 0.06, height * 0.48), scene["label"], font=font, fill=(188, 214, 242))
    image.save(path, quality=90)


def find_media(scene: dict, *, demo: bool, width: int, height: int) -> list[Path]:
    refs = scene["media"] if isinstance(scene["media"], list) else [scene["media"]]
    if not refs:
        raise ValueError(f"Scene {scene['id']} needs at least one media asset.")
    paths = []
    for idx, ref in enumerate(refs):
        media = ROOT / ref
        if media.exists():
            paths.append(media)
            continue
        if demo:
            generated = WORK / "demo_assets" / f"{scene['id']}_{idx:02}.jpg"
            make_demo_image(generated, scene, width, height)
            paths.append(generated)
            continue
        raise FileNotFoundError(
            f"Missing {media}. Add your photo/video, change storyboard.json, "
            "or use --demo for placeholder cards."
        )
    return paths


def render_scene(scene: dict, media: Path, destination: Path, *, width: int,
                 height: int, fps: int, transition: float, is_last: bool,
                 draft: bool) -> None:
    duration = float(scene["duration"]) + (0 if is_last else transition)
    frames = math.ceil(duration * fps)
    ext = media.suffix.lower()
    if ext in SUPPORTED_IMAGES:
        input_args = ["-loop", "1", "-framerate", str(fps), "-i", str(media)]
        # Ken Burns move generated from the real still, not AI-altered content.
        vf = (
            f"scale={width * 6 // 5}:{height * 6 // 5}:force_original_aspect_ratio=increase,"
            f"crop={width * 6 // 5}:{height * 6 // 5},"
            "zoompan=z='min(zoom+0.00045,1.105)':"
            "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
            f"d=1:s={width}x{height}:fps={fps},"
            "eq=contrast=1.08:saturation=0.88:brightness=-0.012,"
            "vignette=PI/5,format=yuv420p"
        )
    elif ext in SUPPORTED_VIDEO:
        input_args = ["-stream_loop", "-1", "-i", str(media)]
        vf = (
            f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "eq=contrast=1.08:saturation=0.88:brightness=-0.012,"
            "vignette=PI/5,format=yuv420p"
        )
    else:
        raise ValueError(f"Unsupported media type for {media}")

    command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *input_args,
        "-vf", vf, "-frames:v", str(frames), "-an",
        "-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast",
        "-crf", "25" if draft else "19", "-pix_fmt", "yuv420p",
        str(destination),
    ], verbose=False)


def crossfade_scenes(scene_paths: list[Path], scenes: list[dict],
                     transition: float, destination: Path, *, draft: bool) -> None:
    if len(scene_paths) == 1:
        shutil.copyfile(scene_paths[0], destination)
        return
    inputs = [value for path in scene_paths for value in ("-i", str(path))]
    filters: list[str] = []
    current = "0:v"
    elapsed = 0.0
    for i in range(1, len(scene_paths)):
        elapsed += float(scenes[i - 1]["duration"])
        target = f"blend{i}"
        effect = scenes[i].get("entrance_transition", "fade")
        if effect not in ("fade", "fadeblack", "fadewhite", "fadefast", "fadeslow"):
            raise ValueError(f"Unsupported entrance_transition: {effect}")
        filters.append(
            f"[{current}][{i}:v]xfade=transition={effect}:duration={transition:.3f}:"
            f"offset={elapsed:.3f}[{target}]"
        )
        current = target
    command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(filters), "-map", f"[{current}]",
        "-an", "-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast",
        "-crf", "24" if draft else "19", "-pix_fmt", "yuv420p",
        str(destination),
    ], verbose=False)


def openai_voice(scene: dict, dest: Path) -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for --tts openai.")
    body = {
        "model": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        "voice": os.environ.get("OPENAI_TTS_VOICE", "coral"),
        "input": scene["narration"],
        "response_format": "wav",
        "speed": 1.05,
        "instructions": (
            "한국어 내레이션. 13~15세 청소년처럼 호기심 있고 담백하게. "
            "뉴스 다큐멘터리 영화 예고편 스타일. 과한 광고 톤 없이 명료하고 "
            "절제된 감정으로, 문장 사이에 짧은 여백을 둔다."
        ),
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            dest.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"TTS API error ({exc.code}): {detail}") from exc


def mac_voice(scene: dict, dest: Path) -> None:
    if not shutil.which("say"):
        raise RuntimeError("macOS 'say' is unavailable; use --tts openai or recordings.")
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout
    korean = next((row.split()[0] for row in voices.splitlines() if "ko_KR" in row), None)
    voice = os.environ.get("MACOS_KOREAN_VOICE", korean or "Yuna")
    text_path = WORK / f"voice_{scene['id']}.txt"
    text_path.write_text(scene["narration"], encoding="utf-8")
    aiff = dest.with_suffix(".aiff")
    command(["say", "-v", voice, "-r", "190", "-f", str(text_path), "-o", str(aiff)], verbose=False)
    command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(aiff), "-ar", "48000", str(dest)], verbose=False)


def find_recording(scene: dict) -> Path | None:
    prefix = ROOT / "assets" / "narration" / scene["id"]
    for suffix in (".wav", ".mp3", ".m4a", ".aiff"):
        path = prefix.with_suffix(suffix)
        if path.exists():
            return path
    return None


def tempo_filters(ratio: float) -> list[str]:
    filters: list[str] = []
    while ratio > 2.0:
        filters.append("atempo=2.0")
        ratio /= 2.0
    while ratio < 0.5:
        filters.append("atempo=0.5")
        ratio /= 0.5
    filters.append(f"atempo={ratio:.5f}")
    return filters


def prepare_voice(scenes: list[dict], *, mode: str, destination: Path) -> None:
    parts: list[Path] = []
    for scene in scenes:
        segment = WORK / f"narration_{scene['id']}.wav"
        duration = float(scene["duration"])
        recording = find_recording(scene)
        if mode == "none":
            recording = None
        elif recording is None:
            raw = WORK / f"tts_{scene['id']}.wav"
            if mode == "openai" or (mode == "auto" and os.environ.get("OPENAI_API_KEY")):
                print(f"  TTS {scene['id']} / OpenAI", flush=True)
                openai_voice(scene, raw)
            elif mode in ("mac", "auto") and platform.system() == "Darwin":
                print(f"  TTS {scene['id']} / macOS", flush=True)
                mac_voice(scene, raw)
            else:
                raise RuntimeError(
                    f"No narration for scene {scene['id']}. Add assets/narration/{scene['id']}.wav, "
                    "set OPENAI_API_KEY, use macOS --tts mac, or test with --tts none."
                )
            recording = raw
        if recording is None:
            command([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t",
                str(duration), "-c:a", "pcm_s16le", str(segment),
            ], verbose=False)
        else:
            raw_length = media_duration(recording)
            available = max(0.5, duration - 0.60)
            # Do not unnaturally slow down short voice lines; speed up only when needed.
            ratio = max(1.0, raw_length / available)
            if ratio > 1.35:
                print(
                    f"  Warning: scene {scene['id']} voice requires {ratio:.2f}x speed; "
                    "consider shortening this line or increasing its screen time.",
                    flush=True,
                )
            chain = tempo_filters(ratio) if ratio > 1.001 else []
            chain.extend(["adelay=250:all=1", f"apad=whole_dur={duration:.3f}"])
            command([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(recording), "-af", ",".join(chain), "-ar", "48000",
                "-ac", "2", "-t", str(duration), "-c:a", "pcm_s16le", str(segment),
            ], verbose=False)
        parts.append(segment)
    # A single concat input avoids per-scene desynchronization after transitions.
    manifest = WORK / "audio_concat.txt"
    manifest.write_text(
        "".join(f"file '{str(path).replace(chr(39), '')}'\n" for path in parts),
        encoding="utf-8",
    )
    command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
        "-safe", "0", "-i", str(manifest), "-c:a", "pcm_s16le", str(destination),
    ], verbose=False)


def synthesize_score(destination: Path, scenes: list[dict], seconds: float) -> None:
    """Copyright-free synthesized temp score: D minor drone, pulses, impacts, risers."""
    rate = 24000
    n = int(round(seconds * rate))
    t = np.arange(n, dtype=np.float32) / rate
    rng = np.random.default_rng(20261027)
    # Low, slowly evolving D-minor harmony.
    chord = np.zeros(n, dtype=np.float32)
    for frequency, weight in ((73.42, 0.45), (110.0, 0.32), (146.83, 0.27), (174.61, 0.25)):
        phase = 2 * np.pi * frequency * t + 0.25 * np.sin(t * 0.23)
        chord += weight * np.sin(phase)
    score = 0.11 * chord * (0.82 + 0.18 * np.sin(2 * np.pi * 0.13 * t))
    score += 0.025 * np.sin(2 * np.pi * 36.71 * t)
    pulse_period = 1.4
    beat_age = np.mod(t - 0.4, pulse_period)
    score += 0.10 * np.sin(2 * np.pi * (74 * beat_age - 36 * beat_age**2)) * np.exp(-13 * beat_age)
    # Gentle, noise-based risers before the reveal and future section.
    noise = rng.standard_normal(n).astype(np.float32)
    for start, end in ((13.5, 23), (42.0, 51.5)):
        progress = np.clip((t - start) / (end - start), 0, 1)
        envelope = np.where((t >= start) & (t < end), progress**2, 0)
        score += 0.052 * noise * envelope
    # Bass impacts and aerial whooshes tied to the cuts.
    cut = 0.0
    boundaries = []
    for scene in scenes[:-1]:
        cut += float(scene["duration"])
        boundaries.append(cut)
    for moment in boundaries:
        age = t - moment
        active = (age >= 0) & (age < 1.8)
        positive_age = np.maximum(age, 0)
        impact = 0.20 * np.sin(2 * np.pi * (60 * positive_age - 8 * positive_age**2))
        score += active * impact * np.exp(-3.5 * positive_age)
        whoosh = np.exp(-((t - moment) / 0.23) ** 2)
        score += 0.035 * whoosh * noise
    fade_in = np.clip(t / 1.6, 0, 1)
    fade_out = np.clip((seconds - t) / 1.6, 0, 1)
    score *= fade_in * fade_out * (0.78 + 0.20 * t / max(seconds, 1))
    score = np.tanh(score * 1.7) * 0.8
    with wave.open(str(destination), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((score * 32767).astype("<i2").tobytes())


def timestamp(seconds: float, *, ass: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, rem = divmod(milliseconds, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    sec, ms = divmod(rem, 1000)
    if ass:
        return f"{hours}:{minutes:02}:{sec:02}.{ms // 10:02}"
    return f"{hours:02}:{minutes:02}:{sec:02},{ms:03}"


def split_caption(text: str) -> list[str]:
    groups = re.split(r"(?<=[.!?])\s+", text.strip())
    captions: list[str] = []
    for group in groups:
        if len(group) > 48 and ", " in group:
            first, second = group.split(", ", 1)
            captions.extend((first + ",", second))
        else:
            captions.append(group)
    return [caption for caption in captions if caption]


def two_lines(text: str, maximum: int = 27) -> str:
    if len(text) <= maximum:
        return text
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > maximum and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\\N".join(lines[:3])


def ass_escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


def write_captions(scenes: list[dict], duration: float, *, width: int, height: int,
                   destination: Path, srt: Path) -> None:
    header = f"""[Script Info]
Title: Sacheon Cinematic Trailer
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Voice,Noto Sans KR,47,&H00FFFFFF,&H000000FF,&H00151515,&H90000000,-1,0,0,0,100,100,0,0,1,3,0,2,110,110,105,1
Style: Title,Noto Sans KR,60,&H00FFFFFF,&H000000FF,&H00302515,&H90000000,-1,0,0,0,100,100,2,0,1,2,0,7,118,120,122,1
Style: Disclosure,Noto Sans KR,27,&H00DDDDEE,&H000000FF,&H00251C12,&H90000000,0,0,0,0,100,100,0,0,1,2,0,9,80,95,85,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    srt_events = []
    cursor = 0.0
    for scene in scenes:
        dur = float(scene["duration"])
        start = cursor
        end = min(duration, start + dur)
        title_start = start + min(0.25, dur / 10)
        title_end = min(end - 0.4, start + min(3.1, dur - 0.5))
        if title_end > title_start:
            events.append(
                f"Dialogue: 1,{timestamp(title_start,ass=True)},{timestamp(title_end,ass=True)},"
                f"Title,,0,0,0,,{{\\fad(280,300)}}{ass_escape(scene['label'])}"
            )
        if scene["id"] in ("01", "06"):
            disclosure = "상상 속 미래 · AI 연출" if scene["id"] == "01" else "미래 기술 구상 · AI 연출"
            events.append(
                f"Dialogue: 2,{timestamp(start,ass=True)},{timestamp(end,ass=True)},"
                f"Disclosure,,0,0,0,,{disclosure}"
            )
        captions = split_caption(scene["narration"])
        usable = max(0.5, dur - 0.55)
        total_chars = sum(len(c) for c in captions)
        cue_start = start + 0.28
        for idx, cue in enumerate(captions):
            if idx == len(captions) - 1:
                cue_end = end - 0.18
            else:
                cue_end = cue_start + usable * len(cue) / max(1, total_chars)
            cue_end = max(cue_start + 0.15, cue_end)
            events.append(
                f"Dialogue: 0,{timestamp(cue_start,ass=True)},{timestamp(cue_end,ass=True)},"
                f"Voice,,0,0,0,,{{\\fad(120,160)}}{ass_escape(two_lines(cue))}"
            )
            srt_events.append((cue_start, cue_end, cue))
            cue_start = cue_end
        cursor = end
    destination.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    srt.write_text(
        "\n\n".join(
            f"{i}\n{timestamp(start)} --> {timestamp(end)}\n{cue}"
            for i, (start, end, cue) in enumerate(srt_events, 1)
        ) + "\n", encoding="utf-8-sig",
    )


def final_mix(video: Path, score: Path, voice: Path, captions: Path,
              destination: Path, *, duration: float, draft: bool) -> None:
    # Compressor ducks the music under spoken words without losing impacts.
    audio_filter = (
        "[2:a]asplit=2[duckkey][narr];"
        "[1:a]volume=0.55[score];"
        "[score][duckkey]sidechaincompress=threshold=0.015:ratio=7:"
        "attack=20:release=420[duck];"
        "[duck][narr]amix=inputs=2:weights='1 1.35':duration=longest:"
        "normalize=0,alimiter=limit=0.93[audio]"
    )
    font_environment = os.environ.copy()
    font_environment["FONTCONFIG_FILE"] = str(ROOT / "assets" / "fonts" / "fonts.conf")
    (WORK / "fontcache").mkdir(exist_ok=True)
    command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-stream_loop", "-1", "-i", str(score),
        "-i", str(voice), "-filter_complex", audio_filter,
        "-map", "0:v:0", "-map", "[audio]",
        "-vf", "ass=output/captions.ass:fontsdir=assets/fonts",
        "-c:v", "libx264", "-preset", "ultrafast" if draft else "medium",
        "-crf", "26" if draft else "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
        "-t", f"{duration:.3f}", "-movflags", "+faststart", "-shortest",
        str(destination),
    ], env=font_environment)


def main() -> int:
    parser = argparse.ArgumentParser(description="60-second cinematic Sacheon airshow trailer")
    parser.add_argument("--demo", action="store_true", help="use test cards for missing footage")
    parser.add_argument("--preview", action="store_true", help="render a six-second, two-scene test")
    parser.add_argument("--draft", action="store_true", help="render a fast 640x360 draft")
    parser.add_argument(
        "--tts", choices=("auto", "openai", "mac", "none"), default="auto",
        help="auto: recordings > OPENAI_API_KEY > macOS say; none: music/captions only",
    )
    args = parser.parse_args()
    ensure_dependencies()
    OUTPUT.mkdir(exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    config = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    original_scenes = config["scenes"]
    if len({scene["id"] for scene in original_scenes}) != len(original_scenes):
        raise ValueError("Every scene id must be unique.")
    if abs(sum(float(s["duration"]) for s in original_scenes) - 60) > 0.001:
        raise ValueError("The full storyboard must add up to exactly 60 seconds.")
    preview_source = [original_scenes[0], original_scenes[2]]
    scenes = [dict(s) for s in (preview_source if args.preview else original_scenes)]
    if args.preview:
        scenes[0]["duration"] = 3
        scenes[1]["duration"] = 3
        scenes[0]["narration"] = "2036년, 저는 조종석을 꿈꿔요."
        scenes[1]["narration"] = "제 눈을 사로잡은 건 KF-21 보라매."
    duration = sum(float(s["duration"]) for s in scenes)
    width = 640 if args.draft else int(config["width"])
    height = 360 if args.draft else int(config["height"])
    fps = int(config["fps"])
    transition = float(config["transition_seconds"])
    if transition <= 0 or transition >= min(s["duration"] for s in scenes):
        raise ValueError("Invalid transition duration.")
    print(f"Rendering {duration:.1f}s | {width}x{height} | {fps} fps", flush=True)
    scene_paths = []
    for idx, scene in enumerate(scenes):
        media_files = find_media(scene, demo=args.demo, width=width, height=height)
        destination = WORK / f"scene_{scene['id']}.mp4"
        print(
            f"  Visual {idx + 1}/{len(scenes)}: "
            + ", ".join(path.name for path in media_files), flush=True,
        )
        if len(media_files) == 1:
            render_scene(
                scene, media_files[0], destination, width=width, height=height, fps=fps,
                transition=transition, is_last=(idx == len(scenes) - 1), draft=args.draft,
            )
        else:
            clip_seconds = float(scene["duration"]) + (
                0 if idx == len(scenes) - 1 else transition
            )
            total_frames = math.ceil(clip_seconds * fps)
            base, remainder = divmod(total_frames, len(media_files))
            parts = []
            for shot_idx, media in enumerate(media_files):
                frames = base + (1 if shot_idx < remainder else 0)
                shot_scene = {**scene, "duration": frames / fps}
                part = WORK / f"shot_{scene['id']}_{shot_idx:02}.mp4"
                render_scene(
                    shot_scene, media, part, width=width, height=height, fps=fps,
                    transition=0, is_last=True, draft=args.draft,
                )
                parts.append(part)
            shot_manifest = WORK / f"shot_concat_{scene['id']}.txt"
            shot_manifest.write_text(
                "".join(f"file '{str(path)}'\n" for path in parts), encoding="utf-8",
            )
            command([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(shot_manifest),
                "-c", "copy", str(destination),
            ], verbose=False)
        scene_paths.append(destination)

    visuals = WORK / "visuals.mp4"
    print("  Transitions", flush=True)
    crossfade_scenes(scene_paths, scenes, transition, visuals, draft=args.draft)
    captions = OUTPUT / "captions.ass"
    srt = OUTPUT / "captions.srt"
    write_captions(scenes, duration, width=width, height=height, destination=captions, srt=srt)

    voice = WORK / "voice_timeline.wav"
    print("  Narration", flush=True)
    prepare_voice(scenes, mode="none" if args.demo and args.tts == "auto" else args.tts, destination=voice)

    score = ROOT / "assets" / "music.wav"
    if not score.exists():
        score = ROOT / "assets" / "music.mp3"
    if not score.exists():
        score = WORK / "original_temp_score.wav"
        print("  Original cinematic temp score + impacts + risers", flush=True)
        synthesize_score(score, scenes, duration)
    name = "preview_6s.mp4" if args.preview else ("trailer_draft.mp4" if args.draft else "sacheon_trailer_60s_1080p.mp4")
    result = OUTPUT / name
    print("  Sound mix + subtitles + final export", flush=True)
    final_mix(visuals, score, voice, captions, result, duration=duration, draft=args.draft)
    metadata = probe(result)
    actual = float(metadata["format"]["duration"])
    video_stream = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    audio_streams = [s for s in metadata["streams"] if s["codec_type"] == "audio"]
    if abs(actual - duration) > 0.22 or not audio_streams:
        raise RuntimeError(f"Output verification failed: duration={actual}, audio={bool(audio_streams)}")
    if video_stream.get("width") != width or video_stream.get("height") != height:
        raise RuntimeError("Output video dimensions do not match the requested format.")
    print(f"\nSUCCESS: {result}\n  {actual:.2f}s, {width}x{height}, audio+burned Korean captions")
    print(f"  Separate caption file: {srt}")
    return 0


if __name__ == "__main__":
    # Preserve ZIP rendering helpers, while using the integrated safety/QA path.
    import runpy
    scripts = ROOT.parent / 'scripts'
    sys.path.insert(0, str(scripts))
    runpy.run_path(str(scripts / 'render_cinematic.py'), run_name='__main__')
