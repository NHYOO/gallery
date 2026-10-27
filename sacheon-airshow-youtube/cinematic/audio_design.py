"""Original procedural music and *synthetic* aviation sound design.

This module uses no recordings, sampled instruments, external songs or music AI.
The jet/engine/fly-by sounds are designed effects, never field-recorded audio.
It is a deterministic production bed, not a claim of orchestral performance.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt


SAMPLE_RATE = 48_000
DESIGN_CREDIT = "Original code-synthesized music and synthetic jet/transition effects"
CHORDS = {
    "01": (50, 57, 62, 65),       # D minor, open voicing
    "02": (46, 53, 58, 62),       # B-flat major
    "03": (50, 57, 62, 65),       # D minor hero reveal
    "04": (48, 55, 60, 64),       # C major
    "05": (43, 50, 58, 62),       # G minor
    "06": (46, 53, 58, 65),       # B-flat major / future
    "07": (45, 52, 57, 62),       # A suspended
    "08": (50, 57, 62, 65),       # D minor resolution
}


def _hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def _times(duration: float) -> np.ndarray:
    return np.arange(max(1, round(duration * SAMPLE_RATE)), dtype=np.float32) / SAMPLE_RATE


def _envelope(t: np.ndarray, duration: float, attack: float, release: float) -> np.ndarray:
    return (np.minimum(1, t / max(attack, 0.001))
            * np.minimum(1, np.maximum(duration - t, 0) / max(release, 0.001))).astype(np.float32)


def _filtered_noise(rng: np.random.Generator, size: int, low: float, high: float) -> np.ndarray:
    signal = rng.standard_normal(size).astype(np.float32)
    if low <= 0:
        sos = butter(3, high, fs=SAMPLE_RATE, btype="lowpass", output="sos")
    else:
        sos = butter(3, (low, high), fs=SAMPLE_RATE, btype="bandpass", output="sos")
    signal = sosfilt(sos, signal).astype(np.float32)
    scale = float(np.sqrt(np.mean(signal ** 2)))
    return signal / max(scale, 0.001)


def synthesize_score(destination: Path, scenes: list[dict], seconds: float) -> None:
    """Write an original stereo 48 kHz PCM music/effects bed of exactly seconds.

    Interface matches the ZIP trailer renderer. Music uses open minor/major
    harmony, bowed additive pads, an eighth-note ostinato, a low brass-like
    pulse, tuned drums and stereo reverb. Cut effects, synthetic engine beds
    and Doppler-style fly-bys follow scene timings. Narration is deliberately
    not fabricated by this function and must be supplied separately.
    """
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Audio duration must be a positive finite number")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    n = round(seconds * SAMPLE_RATE)
    score = np.zeros((n, 2), dtype=np.float32)
    rng = np.random.default_rng(20261027)

    def add(signal: np.ndarray, start: float, gain: float, pan: float = 0.0) -> None:
        begin = round(start * SAMPLE_RATE)
        source_start = max(0, -begin)
        begin = max(0, begin)
        count = min(len(signal) - source_start, n - begin)
        if count <= 0:
            return
        signal = signal[source_start:source_start + count] * gain
        if np.ndim(pan) == 0:
            angle = (float(np.clip(pan, -1, 1)) + 1) * np.pi / 4
            score[begin:begin + count, 0] += signal * math.cos(angle)
            score[begin:begin + count, 1] += signal * math.sin(angle)
        else:
            p = np.asarray(pan)[source_start:source_start + count]
            angle = (np.clip(p, -1, 1) + 1) * (np.pi / 4)
            score[begin:begin + count, 0] += signal * np.cos(angle)
            score[begin:begin + count, 1] += signal * np.sin(angle)

    timeline = []
    cursor = 0.0
    for index, scene in enumerate(scenes):
        duration = float(scene["duration"])
        if duration <= 0:
            raise ValueError("Every scene must have a positive duration")
        ident = str(scene.get("id", f"{index + 1:02}"))
        chord = CHORDS.get(ident, CHORDS["01"])
        timeline.append((cursor, duration, ident, chord))
        cursor += duration
    if not timeline:
        timeline = [(0.0, seconds, "01", CHORDS["01"])]

    # Slowly bowed harmonic layers, varied independently across stereo space.
    for start, duration, ident, chord in timeline:
        length = min(duration + 1.1, seconds - start)
        if length <= 0:
            continue
        t = _times(length)
        env = _envelope(t, length, 0.7, 1.1)
        growth = 0.55 + 0.45 * min(1.0, start / max(12, seconds * 0.7))
        for voice, note in enumerate(chord):
            hz = _hz(note)
            phase = 2 * np.pi * hz * t
            layer = np.zeros_like(t)
            for partial, level in ((1, 1), (2, 0.31), (3, 0.13), (4, 0.065), (5, 0.025)):
                drift = 0.0015 * np.sin(2 * np.pi * 0.17 * t + voice)
                layer += level * np.sin(partial * phase + drift * hz)
                layer += level * 0.40 * np.sin(partial * phase * 1.0018 + voice * 0.7)
            layer *= env * (0.91 + 0.09 * np.sin(2 * np.pi * 0.11 * t + voice))
            add(layer, start, 0.031 * growth, (voice - 1.5) * 0.43)

        # Sub-bass underneath each chord, softened at both edges.
        bass = np.sin(2 * np.pi * _hz(chord[0] - 12) * t)
        bass += 0.2 * np.sin(2 * np.pi * _hz(chord[0]) * t)
        add(bass * env, start, 0.037 * growth)

    # 90 BPM eighth-note strings: increase movement through the middle act.
    beat = 60.0 / 90.0
    eighth = beat / 2
    moment = 0.0
    step = 0
    while moment < seconds - 0.7:
        current = next((item for item in reversed(timeline) if moment >= item[0]), timeline[0])
        _, _, ident, chord = current
        fraction = moment / seconds
        density = 0.35 if fraction < 0.12 else (0.66 if fraction < 0.4 else 1.0)
        if fraction > 0.93:
            density *= 0.55
        # Start with quarter-notes, then reveal the complete ostinato.
        if density > 0.5 or step % 2 == 0:
            length = 0.48
            t = _times(length)
            note = chord[(0, 2, 1, 3, 0, 2, 3, 1)[step % 8]] + 12
            phase = 2 * np.pi * _hz(note) * t
            texture = (np.sin(phase) + 0.24 * np.sin(phase * 2.001)
                       + 0.07 * np.sin(phase * 3.002))
            env = (1 - np.exp(-t * 110)) * np.exp(-t * 10)
            add(texture * env, moment, 0.045 * density, 0.45 if step % 2 else -0.45)

        # Tuned low drum: pitch falls as a taut membrane relaxes.
        if step % 4 == 0 and moment > min(2.0, seconds * 0.2):
            t = _times(0.9)
            phase = 2 * np.pi * (43 * t + 21 * 0.06 * (1 - np.exp(-t / 0.06)))
            drum = np.sin(phase) * np.exp(-6.8 * t)
            strike = _filtered_noise(rng, len(t), 90, 1300) * np.exp(-65 * t)
            add(drum + strike * 0.16, moment, 0.10 * density)
        if step % 4 == 2 and fraction > 0.27:
            t = _times(0.25)
            click = _filtered_noise(rng, len(t), 1400, 4600) * np.exp(-30 * t)
            add(click, moment, 0.012 * density, -0.3 if step % 8 == 2 else 0.3)
        moment += eighth
        step += 1

    # A small original motif, left spacious enough for Korean narration.
    motif = (74, 77, 81, 79, 77, 74, 72, 74)
    motif_start = 1.0 if seconds <= 6 else seconds * 0.69
    for index, note in enumerate(motif):
        when = motif_start + index * beat
        if when >= seconds - 1:
            break
        t = _times(1.3)
        phase = 2 * np.pi * _hz(note) * t
        tone = np.sin(phase + 0.015 * np.sin(2 * np.pi * 4.8 * t))
        tone += 0.18 * np.sin(2 * phase)
        env = _envelope(t, 1.3, 0.1, 0.7) * np.exp(-0.9 * t)
        add(tone * env, when, 0.025, 0.12)

    # Scene entrances: low impacts with metal resonance and brief reverse air.
    for index, (start, duration, ident, chord) in enumerate(timeline):
        if index == 0:
            continue
        hero = 1.2 if ident in ("03", "06") else 0.8
        t = _times(1.9)
        phase = 2 * np.pi * (34 * t + 39 * 0.09 * (1 - np.exp(-t / 0.09)))
        low = np.sin(phase) * np.exp(-2.7 * t)
        metal = (np.sin(2 * np.pi * 186.2 * t) + 0.5 * np.sin(2 * np.pi * 291.9 * t))
        metal *= np.exp(-5 * t)
        noise = _filtered_noise(rng, len(t), 180, 2800)
        impact = low + 0.11 * metal + 0.15 * noise * np.exp(-12 * t)
        add(impact * _envelope(t, 1.9, 0.004, 0.4), start, 0.16 * hero)
        t = _times(0.9)
        air = _filtered_noise(rng, len(t), 450, 5500)
        air *= np.sin(np.pi * t / 0.9) ** 2
        add(air, start - 0.58, 0.038 * hero, np.linspace(-0.7, 0.7, len(t)))

    # Synthetic turbine floor during cockpit / aircraft sections. This is a
    # designed, band-limited noise and harmonic effect, not a real aircraft.
    for start, duration, ident, chord in timeline:
        if ident not in ("01", "02", "03", "04", "06"):
            continue
        length = min(duration, seconds - start)
        if length <= 0:
            continue
        t = _times(length)
        noise = _filtered_noise(rng, len(t), 45, 1800)
        pitch = 72 + 9 * np.sin(np.pi * t / max(length, 0.01))
        phase = 2 * np.pi * np.cumsum(pitch, dtype=np.float64) / SAMPLE_RATE
        turbine = (0.18 * np.sin(phase) + 0.07 * np.sin(phase * 3.97)).astype(np.float32)
        engine = noise * (0.6 + 0.15 * np.sin(2 * np.pi * 9.5 * t)) + turbine
        env = _envelope(t, length, 0.6, 0.75)
        add(engine * env, start, 0.018 if ident == "01" else 0.011)
        if ident in ("02", "03", "06"):
            # Fly-by: a falling harmonic pitch, a broad air burst and a pan.
            fly_length = min(2.9, length * 0.82)
            ft = _times(fly_length)
            progress = ft / fly_length
            freq = 98 + 120 * (1 - np.tanh((progress - 0.48) * 4)) / 2
            fphase = 2 * np.pi * np.cumsum(freq, dtype=np.float64) / SAMPLE_RATE
            roar = _filtered_noise(rng, len(ft), 90, 3600)
            tonal = (np.sin(fphase) + 0.3 * np.sin(fphase * 2.02)).astype(np.float32)
            env = np.sin(np.pi * progress) ** 2 * np.exp(-((progress - 0.5) / 0.5) ** 2)
            add((roar * 0.8 + tonal * 0.25) * env, start + 0.2, 0.055,
                np.linspace(-0.88, 0.88, len(ft)))

    # Early stereo echoes and a subdued diffuse tail; cross-channel taps
    # provide width without damaging a mono downmix or speech intelligibility.
    dry = score.copy()
    for delay, level in ((0.071, 0.11), (0.113, 0.09), (0.197, 0.08),
                         (0.293, 0.065), (0.431, 0.045), (0.617, 0.03)):
        shift = round(delay * SAMPLE_RATE)
        if shift < n:
            score[shift:, 0] += dry[:-shift, 1] * level
            score[shift:, 1] += dry[:-shift, 0] * level
    del dry
    fade_in = max(1, min(n, round(0.15 * SAMPLE_RATE)))
    fade_out = max(1, min(n, round((0.6 if seconds <= 6 else 1.4) * SAMPLE_RATE)))
    score[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)[:, None]
    score[-fade_out:] *= np.linspace(1, 0, fade_out, dtype=np.float32)[:, None]
    score -= np.mean(score, axis=0, keepdims=True)
    # Preserve headroom for a separately mixed voice; soft limit rare impacts.
    score = np.tanh(score * 1.35)
    peak = float(np.max(np.abs(score)))
    rms = float(np.sqrt(np.mean(score ** 2)))
    score *= min(0.78 / max(peak, 0.001), 0.075 / max(rms, 0.001))
    pcm = np.rint(np.clip(score, -1, 1) * 32767).astype("<i2")
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
