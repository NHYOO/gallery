"""Add real narration and captions timed to the recorded speech.

No timing is estimated from character counts. Supply reviewed segment timestamps
or use the optional OpenAI Whisper transcription API. The latter needs a separate
API key, network access, and API billing; this module never creates credentials.
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
import numpy as np


API_URL = "https://api.openai.com/v1/audio/transcriptions"
UPLOAD_LIMIT = 25_000_000


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(result.stdout)
    if not info.get("streams"):
        raise ValueError("The narration file has no audio stream.")
    seconds = float(info["format"]["duration"])
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("The narration file has no measurable positive duration.")
    return seconds


def _transcribe(audio: Path) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "내레이션 파일은 있지만 발화 타임스탬프가 없습니다. "
            "alignment_json에 실제 발화 구간을 제공하거나 OPENAI_API_KEY와 "
            "음성 인식 API 접근을 설정하세요. 글자 수로 동기화를 추정하지 않습니다."
        )
    if audio.stat().st_size > UPLOAD_LIMIT:
        raise ValueError(
            "Narration exceeds the transcription API's 25 MB upload limit. "
            "Supply alignment_json, or a smaller audio encoding of the same recording."
        )
    boundary = "sacheon_" + uuid.uuid4().hex
    parts = []
    for name, value in (("model", "whisper-1"), ("language", "ko"),
                        ("response_format", "verbose_json"),
                        ("timestamp_granularities[]", "segment")):
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\""
             f"\r\n\r\n{value}\r\n").encode("utf-8")
        )
    # A fixed safe filename avoids injecting arbitrary filesystem names into MIME.
    suffix = audio.suffix.lower()
    safe_suffix = suffix if suffix in {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".mpeg", ".mpga"} else ".wav"
    mime = mimetypes.guess_type("narration" + safe_suffix)[0] or "application/octet-stream"
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
         f"filename=\"narration{safe_suffix}\"\r\nContent-Type: {mime}\r\n\r\n").encode("ascii")
    )
    parts.extend((audio.read_bytes(), f"\r\n--{boundary}--\r\n".encode("ascii")))
    request = urllib.request.Request(
        API_URL, data=b"".join(parts), method="POST",
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "multipart/form-data; boundary=" + boundary},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Never echo request headers, credentials, or the untrusted response body.
        raise RuntimeError(f"Speech transcription API failed (HTTP {exc.code}).") from None
    except urllib.error.URLError:
        raise RuntimeError("Speech transcription API could not be reached. Check the configured network access.") from None


def _validated_segments(data: dict, audio_seconds: float, duration: float) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise ValueError("Alignment JSON must contain a segments array.")
    if not data["segments"]:
        raise ValueError("No timed speech segments were provided or recognized.")
    cues = []
    previous_end = 0.0
    for index, segment in enumerate(data["segments"], 1):
        if not isinstance(segment, dict):
            raise ValueError(f"Alignment segment {index} must be an object.")
        try:
            start, end = float(segment["start"]), float(segment["end"])
            text = segment["text"]
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Alignment segment {index} needs start, end, and text.") from None
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Alignment segment {index} has empty text.")
        if not (math.isfinite(start) and math.isfinite(end)):
            raise ValueError(f"Alignment segment {index} has non-finite timestamps.")
        if start < 0 or start < previous_end or end <= start:
            raise ValueError(f"Alignment segment {index} is reversed or overlaps an earlier segment.")
        if end > duration or end > audio_seconds + 0.05:
            raise ValueError(f"Alignment segment {index} extends past the narration or video.")
        # Check SRT's millisecond resolution as well as floating-point times.
        if round(end * 1000) <= round(start * 1000):
            raise ValueError(f"Alignment segment {index} is too short for SRT timestamps.")
        cues.append({"start": start, "end": end, "text": text.strip()})
        previous_end = end
    return cues


def _timestamp(seconds: float) -> str:
    total = round(seconds * 1000)
    hours, total = divmod(total, 3_600_000)
    minutes, total = divmod(total, 60_000)
    sec, ms = divmod(total, 1000)
    return f"{hours:02}:{minutes:02}:{sec:02},{ms:03}"


def prepare_narration(audio_path, output_wav, srt_path, duration=60,
                      backend="openai", alignment_json=None) -> dict:
    """Normalize/pad a recording and create SRT using actual speech timestamps.

    ``alignment_json`` can be a path or an already parsed object containing
    ``{"segments": [{"start": 0.25, "end": 2.7, "text": "한국어 발화"}]}``.
    Without it, ``backend='openai'`` performs Korean Whisper transcription.
    ASR timestamps are model estimates and still require listening review;
    successful execution does not claim human-verified frame accuracy.
    The original file is never changed; speech is never speed-adjusted.
    """
    audio, wav, srt = (Path(path).expanduser().resolve()
                       for path in (audio_path, output_wav, srt_path))
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video duration must be a positive finite number.")
    if not audio.is_file():
        raise FileNotFoundError("The narration recording does not exist.")
    if len({audio, wav, srt}) != 3:
        raise ValueError("Narration input, output WAV, and SRT must use separate paths.")
    audio_seconds = _probe_duration(audio)
    if audio_seconds > duration + 0.05:
        raise ValueError(
            f"Narration is {audio_seconds:.3f}s, longer than the {duration:.3f}s video. "
            "Provide a recording that fits; audio is not automatically cut or sped up."
        )
    pcm = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(audio), '-map', '0:a:0',
        '-f', 'f32le', '-ac', '1', '-ar', '16000', '-'
    ])
    samples = np.frombuffer(pcm, dtype='<f4')
    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
    if rms < 0.001:
        raise ValueError('내레이션 입력이 무음이거나 지나치게 작습니다. 실제 음성 녹음을 확인하세요.')
    if alignment_json is not None:
        data = alignment_json if isinstance(alignment_json, dict) else json.loads(
            Path(alignment_json).expanduser().read_text(encoding="utf-8-sig")
        )
        method = "provided_speech_timestamps"
    elif backend == "openai":
        data = _transcribe(audio)
        method = "openai_whisper1_korean_segments"
    else:
        raise ValueError('실제 발화 타임스탬프 JSON을 제공하거나 --transcribe로 음성 인식 API 사용을 명시하세요. API는 별도 키와 네트워크 접근이 필요합니다.')
    cues = _validated_segments(data, audio_seconds, duration)
    subtitle = "\n\n".join(
        f"{index}\n{_timestamp(cue['start'])} --> {_timestamp(cue['end'])}\n{cue['text']}"
        for index, cue in enumerate(cues, 1)
    ) + "\n"
    wav.parent.mkdir(parents=True, exist_ok=True)
    srt.parent.mkdir(parents=True, exist_ok=True)
    # Only the normalized output is padded/truncated within the 50 ms codec
    # duration tolerance above; the input recording is always untouched.
    with tempfile.TemporaryDirectory(prefix="narration_sync_", dir=wav.parent) as temporary:
        pending = Path(temporary) / "narration.wav"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(audio),
            "-map", "0:a:0", "-vn", "-af",
            f"loudnorm=I=-18:TP=-2:LRA=7,apad=whole_dur={duration:.6f}",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            "-t", f"{duration:.6f}", str(pending),
        ], check=True)
        actual = _probe_duration(pending)
        if abs(actual - duration) > 0.01:
            raise RuntimeError("Normalized narration duration verification failed.")
        pending.replace(wav)
    srt.write_text(subtitle, encoding="utf-8-sig")
    return {
        "narration_present": True,
        "caption_timing": "speech_timestamps",
        "alignment_method": method,
        "alignment_review_required": method.startswith("openai_"),
        "input_duration": audio_seconds,
        "input_audio_rms_dbfs": 20 * math.log10(rms),
        "timeline_duration": duration,
        "voice_wav": str(wav),
        "srt": str(srt),
        "cues": cues,
    }


# Usage from the renderer after receiving a real recording:
# info = prepare_narration("assets/narration.wav", "work/voice.wav",
#                          "output/captions.srt", duration=60)
# Or offline, with speech timestamps exported/reviewed from an aligner:
# info = prepare_narration("assets/narration.wav", "work/voice.wav",
#                          "output/captions.srt", alignment_json="alignment.json")
