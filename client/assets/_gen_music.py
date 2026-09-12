#!/usr/bin/env python3
"""Generates the Asherfall lobby soundtrack from scratch — original
synthesized ambient/chiptune pads, no third-party samples. Pure stdlib.

Run once to (re)create the .wav tracks referenced by config.MUSIC_TRACKS.
"""
import math
import struct
import wave

SR = 44100

# note -> frequency (equal temperament, A4=440)
def note(n, octave=4):
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    semis = names.index(n) + (octave - 4) * 12 - 9  # relative to A4
    return 440.0 * (2 ** (semis / 12.0))


def adsr(t, dur, a=0.06, d=0.15, s=0.7, r=0.4):
    if t < a:
        return t / a
    if t < a + d:
        return 1 - (1 - s) * (t - a) / d
    if t < dur - r:
        return s
    if t < dur:
        return s * max(0.0, (dur - t) / r)
    return 0.0


def voice(freq, t, kind):
    ph = 2 * math.pi * freq * t
    if kind == "pad":       # warm detuned saw-ish stack
        return (math.sin(ph) + 0.5 * math.sin(2 * ph)
                + 0.3 * math.sin(2 * math.pi * (freq * 1.004) * t)) / 1.8
    if kind == "bell":      # glassy sine + shimmer
        return (math.sin(ph) + 0.35 * math.sin(3 * ph)) / 1.35
    if kind == "pluck":     # short triangle-ish
        tri = 2 / math.pi * math.asin(math.sin(ph))
        return tri
    if kind == "bass":
        return math.sin(ph) + 0.2 * math.sin(2 * ph)
    return math.sin(ph)


def render(chords, beat, kind, gain, bass_octave=2, lead_kind=None):
    """chords: list of (list-of-(name,octave)). Each chord lasts `beat` sec."""
    total = int(SR * beat * len(chords))
    buf = [0.0] * total
    for ci, chord in enumerate(chords):
        start = int(ci * beat * SR)
        for (name, octv) in chord:
            f = note(name, octv)
            for i in range(int(beat * SR)):
                t = i / SR
                env = adsr(t, beat, r=beat * 0.4)
                idx = start + i
                if idx < total:
                    buf[idx] += env * voice(f, t, kind) * gain
        # walking bass on chord root
        root = chord[0]
        bf = note(root[0], bass_octave)
        for i in range(int(beat * SR)):
            t = i / SR
            env = adsr(t, beat, a=0.01, r=beat * 0.3)
            idx = start + i
            if idx < total:
                buf[idx] += env * voice(bf, t, "bass") * gain * 0.6
        # optional lead arpeggio
        if lead_kind:
            arp = chord + [chord[0]]
            step = beat / len(arp)
            for si, (nm, oc) in enumerate(arp):
                lf = note(nm, oc + 1)
                s0 = start + int(si * step * SR)
                for i in range(int(step * SR)):
                    t = i / SR
                    env = adsr(t, step, a=0.005, d=0.05, s=0.4, r=step * 0.5)
                    idx = s0 + i
                    if idx < total:
                        buf[idx] += env * voice(lf, t, lead_kind) * gain * 0.5
    return buf


def write_wav(path, samples):
    peak = max(1e-6, max(abs(s) for s in samples))
    norm = 0.85 / peak
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = bytearray()
        for s in samples:
            v = int(max(-1.0, min(1.0, s * norm)) * 32767)
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    print("wrote", path, f"{len(samples)/SR:.1f}s")


# --- four original tracks, each looped a few times to fill the lobby ---
def build():
    # 1. Neon Market — bright major, hopeful trading-floor vibe
    prog = [[("C", 4), ("E", 4), ("G", 4)],
            [("A", 3), ("C", 4), ("E", 4)],
            [("F", 3), ("A", 3), ("C", 4)],
            [("G", 3), ("B", 3), ("D", 4)]]
    write_wav("neon_market.wav", render(prog * 4, 1.1, "pluck", 0.5, lead_kind="bell"))

    # 2. Orbital Drift — slow ambient pad, spacious
    prog = [[("D", 4), ("F", 4), ("A", 4)],
            [("B", 3), ("D", 4), ("F", 4)],
            [("G", 3), ("B", 3), ("D", 4)],
            [("A", 3), ("C", 4), ("E", 4)]]
    write_wav("orbital_drift.wav", render(prog * 3, 2.0, "pad", 0.5))

    # 3. Cargo Run — driving minor arpeggio, momentum
    prog = [[("E", 4), ("G", 4), ("B", 4)],
            [("C", 4), ("E", 4), ("G", 4)],
            [("D", 4), ("F#", 4), ("A", 4)],
            [("E", 4), ("G", 4), ("B", 4)]]
    write_wav("cargo_run.wav", render(prog * 5, 0.85, "pluck", 0.5, lead_kind="pluck"))

    # 4. Boardroom — stately, wealthy, warm bells
    prog = [[("F", 4), ("A", 4), ("C", 5)],
            [("C", 4), ("E", 4), ("G", 4)],
            [("D", 4), ("F", 4), ("A", 4)],
            [("A#", 3), ("D", 4), ("F", 4)]]
    write_wav("boardroom.wav", render(prog * 3, 1.6, "bell", 0.5))


if __name__ == "__main__":
    build()
