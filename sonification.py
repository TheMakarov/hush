"""A deterministic instrument for real packet captures. AGPL-3.0-or-later.

This creates new audio from packet bytes. It never decodes or records media.
Python standard library only; stereo 16-bit PCM WAV, plus an auditable score.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import io
import json
import math
from pathlib import Path
import secrets
import sys
import threading
import time
import wave

import sony_protocol as sony
from telemetry import OPCODES

PRESETS = ("garden", "modem", "drums")
SCALE = (0, 2, 4, 7, 9)  # C major pentatonic: C, D, E, G, A.
MAX_FRAMES = 128
MAX_EVENTS = 384


def validate_capture(frames):
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("Choose between 1 and 128 captured packets.")
    clean = []
    total = 0
    for index, item in enumerate(frames):
        if not isinstance(item, dict) or item.get("direction") not in ("TX", "RX"):
            raise ValueError("Every packet needs a TX or RX direction.")
        raw_hex = item.get("raw")
        if not isinstance(raw_hex, str) or len(raw_hex) > 12288:
            raise ValueError("A packet exceeds the 4096-byte limit.")
        try:
            raw = bytes.fromhex(raw_hex)
        except ValueError:
            raise ValueError("Packet data must contain hexadecimal bytes.") from None
        if not 1 <= len(raw) <= 4096:
            raise ValueError("Packets must contain 1–4096 bytes.")
        total += len(raw)
        if total > 196608:
            raise ValueError("Choose a smaller capture (at most 192 KiB of packet bytes).")
        timestamp = item.get("time", index)
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("Packet timestamps must be finite numbers.")
        payload = raw
        opcode = None
        ack = False
        valid = None
        label = "HCI BYTES" if item.get("source") == "HCI" else "PACKET BYTES"
        if raw[0] == sony.HEADER and raw[-1] == sony.TRAILER and item.get("source") != "HCI":
            try:
                kind, sequence, payload = sony.decode_message(raw)
                valid = True
                ack = kind == sony.MSG_ACK
                opcode = payload[0] if payload else None
                label = "ACK" if ack else OPCODES.get(opcode, "MDR MESSAGE")
            except sony.ProtocolError:
                valid = False
                label = "INVALID MDR FRAME"
        clean.append({"id": str(item.get("id", index + 1))[:64], "time": float(timestamp),
                      "direction": item["direction"], "source": "HCI" if item.get("source") == "HCI" else "MDR",
                      "raw": raw.hex(" ").upper(), "label": label, "valid": valid,
                      "opcode": opcode, "ack": ack, "payload_bytes": list(payload),
                      "sha256": hashlib.sha256(raw).hexdigest()})
    return sorted(clean, key=lambda packet: packet["time"])


def build_score(frames, preset="garden", duration=16, tempo=104, timing="groove"):
    if preset not in PRESETS:
        raise ValueError("Choose Packet Garden, Modem Dreams, or Wire Drums.")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 4 <= duration <= 32:
        raise ValueError("Composition length must be 4–32 seconds.")
    if isinstance(tempo, bool) or not isinstance(tempo, (int, float)) or not 60 <= tempo <= 160:
        raise ValueError("Tempo must be 60–160 BPM.")
    if timing not in ("groove", "wire"):
        raise ValueError("Choose groove or original packet timing.")
    packets = validate_capture(frames)
    if timing == "wire":
        start = max(packets[0]["time"], packets[-1]["time"] - duration + 1.7)
        packets = [packet for packet in packets if packet["time"] >= start]
    first, last = packets[0]["time"], packets[-1]["time"]
    span = last - first
    grid = 60 / tempo / 2
    events = []
    for index, packet in enumerate(packets):
        if timing == "wire":
            position = .18 + packet["time"] - first
        else:
            ratio = (packet["time"] - first) / span if span else index / max(1, len(packets) - 1)
            position = .18 + round(ratio * (duration - 2) / grid) * grid
        direction = packet["direction"]
        pan = -.58 if direction == "TX" else .58
        data = packet["payload_bytes"] or list(bytes.fromhex(packet["raw"])[1:3]) or [0]
        seed = int(packet["sha256"][:8], 16)
        if packet["ack"]:
            voice, values = "hat", [data[0]]
        elif preset == "garden":
            voice, values = "bell", data[:3]
        elif preset == "modem":
            voice, values = "fsk", data[:4]
        else:
            voice = "kick" if direction == "TX" else "clap"
            values = data[:1]
        for byte_index, byte in enumerate(values):
            if len(events) >= MAX_EVENTS:
                break
            degree = (byte + ((seed >> (byte_index * 3)) & 7)) % len(SCALE)
            midi = (48 if direction == "TX" else 60) + SCALE[degree] + (12 if byte_index == 2 else 0)
            offset = byte_index * (grid / 3 if preset == "garden" else .105)
            when = min(duration - .3, position + offset)
            length = {"bell": 1.35, "hat": .055, "fsk": .15, "kick": .38, "clap": .2}[voice]
            events.append({"time": round(when, 6), "duration": min(length, duration - when),
                           "voice": voice, "midi": midi if voice == "bell" else None,
                           "frequency": round(440 * 2 ** ((midi - 69) / 12), 4) if voice == "bell" else None,
                           "fsk_tones_hz": [560, 900] if voice == "fsk" else None,
                           "kick_sweep_hz": [128, 48] if voice == "kick" else None,
                           "pan": pan, "amplitude": .1 if voice == "hat" else .38,
                           "byte": byte, "byte_index": byte_index, "seed": seed,
                           "frame_id": packet["id"], "frame_sha256": packet["sha256"],
                           "direction": direction, "label": packet["label"]})
    return {"engine": "hush-packet-studio/1", "kind": "synthesized packet sonification",
            "preset": preset, "duration": duration, "tempo": tempo, "timing": timing,
            "scale": "C major pentatonic" if preset == "garden" else None, "packets": packets, "events": events,
            "mapping": {"direction": "TX left/lower register; RX right/higher register",
                        "pitch": ("Pentatonic degree from the payload byte and wire-byte SHA-256; see each event" if preset == "garden"
                                  else "Selected bytes encoded as custom two-tone FSK" if preset == "modem"
                                  else "Kick/clap from packet direction; soft noise hats from ACK status"),
                        "rhythm": "Original relative arrival times" if timing == "wire" else "Arrival times fitted to the clip and quantized to eighth notes",
                        "acknowledgements": "Soft noise hats", "modem": "Each selected byte drives a custom 10-bit FSK tone; not an audio codec decoder"}}


def synthesize(score, sample_rate=24000):
    count = int(score["duration"] * sample_rate)
    left, right = array("f", [0.0]) * count, array("f", [0.0]) * count
    tau = 2 * math.pi
    for event in score["events"]:
        start = int(event["time"] * sample_rate)
        length = min(int(event["duration"] * sample_rate), count - start)
        if length <= 0:
            continue
        l_gain = math.sqrt((1 - event["pan"]) / 2) * event["amplitude"]
        r_gain = math.sqrt((1 + event["pan"]) / 2) * event["amplitude"]
        frequency, voice = event["frequency"], event["voice"]
        state = event["seed"] or 1
        phase = previous_noise = 0.0
        for i in range(length):
            t = i / sample_rate
            attack = min(1.0, t / .006)
            envelope = attack * math.exp(-5 * t / event["duration"])
            if voice == "bell":
                value = (math.sin(tau * frequency * t) + .28 * math.sin(tau * frequency * 2.002 * t)
                         + .11 * math.sin(tau * frequency * 3.01 * t)) * envelope
            elif voice == "fsk":
                bit = min(9, int(10 * i / length))
                one = 0 if bit == 0 else 1 if bit == 9 else (event["byte"] >> (bit - 1)) & 1
                phase += tau * (900 if one else 560) / sample_rate
                value = math.sin(phase) * attack * min(1.0, (length - i) / (sample_rate * .006)) * .55
            elif voice == "kick":
                value = math.sin(tau * (48 * t + 80 * (1 - math.exp(-25 * t)) / 25)) * envelope
            else:
                state = (1664525 * state + 1013904223) & 0xffffffff
                noise = (state >> 8) / 8388608 - 1
                value = (noise - previous_noise * .75) * envelope * (.5 if voice == "hat" else .75)
                previous_noise = noise
            left[start + i] += value * l_gain
            right[start + i] += value * r_gain
    if score["preset"] == "garden":
        # A short cross-channel echo gives outgoing/incoming notes some space.
        dry_l, dry_r = array("f", left), array("f", right)
        delay = int(sample_rate * .23)
        for i in range(delay, count):
            left[i] += dry_r[i - delay] * .18
            right[i] += dry_l[i - delay] * .18
    peak = max(max(map(abs, left), default=0), max(map(abs, right), default=0))
    gain = min(2.0, .62 / peak) if peak else 0
    pcm = array("h")
    for i in range(count):
        fade = min(1, i / max(1, sample_rate * .01), (count - 1 - i) / max(1, sample_rate * .12))
        left[i] *= gain * fade
        right[i] *= gain * fade
        pcm.append(round(max(-.95, min(.95, left[i])) * 32767))
        pcm.append(round(max(-.95, min(.95, right[i])) * 32767))
    if sys.byteorder != "little":
        pcm.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    stride = max(1, count // 384)
    peaks = [round(max(max(map(abs, left[i:i + stride]), default=0), max(map(abs, right[i:i + stride]), default=0)), 4)
             for i in range(0, count, stride)][:384]
    return output.getvalue(), peaks


def compose(frames, *, preset="garden", duration=16, tempo=104, timing="groove", sample_rate=24000):
    score = build_score(frames, preset, duration, tempo, timing)
    audio, peaks = synthesize(score, sample_rate)
    score.update(sample_rate=sample_rate, channels=2, bits_per_sample=16,
                 audio_sha256=hashlib.sha256(audio).hexdigest())
    return audio, score, peaks


class RenderStore:
    """Four local in-memory renders, a 20-minute TTL, one bounded renderer."""
    def __init__(self):
        self.lock = threading.RLock()
        self.renderer = threading.BoundedSemaphore(1)
        self.items = {}

    def create(self, request):
        if not self.renderer.acquire(blocking=False):
            raise ValueError("A piece is already rendering. Try again in a moment.")
        try:
            audio, score, peaks = compose(request.get("frames"), preset=request.get("preset", "garden"),
                                          duration=request.get("duration", 16), tempo=request.get("tempo", 104),
                                          timing=request.get("timing", "groove"))
            key = secrets.token_hex(16)
            with self.lock:
                self.items = {k: value for k, value in self.items.items() if value["created"] > time.monotonic() - 1200}
                while len(self.items) >= 4:
                    del self.items[next(iter(self.items))]
                self.items[key] = {"audio": audio, "score": score, "created": time.monotonic()}
            return {"ok": True, "render_id": key, "wav_url": f"/api/sonifications/{key}/audio.wav",
                    "score_url": f"/api/sonifications/{key}/score.json", "peaks": peaks,
                    "score": {k: v for k, v in score.items() if k != "packets"},
                    "packet_count": len(score["packets"]), "byte_count": sum(len(bytes.fromhex(p["raw"])) for p in score["packets"]),
                    "wav_bytes": len(audio)}
        finally:
            self.renderer.release()

    def get(self, key):
        with self.lock:
            value = self.items.get(key)
            if value and value["created"] > time.monotonic() - 1200:
                return value
            self.items.pop(key, None)
            return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preset", choices=PRESETS, default="garden")
    parser.add_argument("--duration", type=int, default=16)
    parser.add_argument("--tempo", type=int, default=104)
    parser.add_argument("--timing", choices=("groove", "wire"), default="groove")
    args = parser.parse_args()
    data = json.loads(args.capture.read_text())
    frames = data if isinstance(data, list) else data.get("packets", data.get("frames"))
    audio, score, _ = compose(frames, preset=args.preset, duration=args.duration, tempo=args.tempo, timing=args.timing)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(audio)
    sidecar = args.output.with_suffix(".score.json")
    sidecar.write_text(json.dumps(score, indent=2) + "\n")
    print(f"Created {args.output}: {args.duration}s stereo PCM, {len(score['packets'])} real packets, {len(score['events'])} sounds.")
    print(f"Auditable score: {sidecar}")


if __name__ == "__main__":
    main()
