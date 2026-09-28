"""Render approved graphic layers and timed sound cues onto a finished scene."""
from __future__ import annotations

import array
import json
import math
import os
import random
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

COMPOSER = Path(__file__).resolve().parent.parent / "scene_composer"
SAMPLE_RATE = 48000


def render_graphic_track(direction: dict, output: Path, width: int, height: int, fps: int) -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Cần Node.js để dựng các lớp đồ họa đã lên kế hoạch")
    props = output.with_suffix(".props.json")
    props.write_text(json.dumps({**direction, "width": width, "height": height, "fps": fps},
                               ensure_ascii=False), encoding="utf-8")
    # No shell: paths containing spaces or metacharacters remain literal.
    with output.with_suffix(".render.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([node, str(COMPOSER / "render.cjs"), str(props), str(output)],
                                   cwd=str(COMPOSER), stdout=log, stderr=subprocess.STDOUT)
        try:
            result = process.wait(timeout=900)
        except subprocess.TimeoutExpired as exc:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
            process.wait()
            raise RuntimeError("Dựng lớp đồ họa quá 15 phút; đã dừng tiến trình render") from exc
    if result != 0 or not output.is_file():
        detail = output.with_suffix(".render.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"Không dựng được lớp đồ họa: {detail}")


def write_sound_cues(cues: list[dict[str, Any]], duration: float, output: Path) -> dict:
    """Synthesize small original cues locally; no download or provider quota.

    Each preset is peak-normalized before gain. Deterministic noise and short
    envelopes avoid abrupt boundaries and make repeated renders identical.
    """
    mix = array.array("f", [0.0]) * math.ceil(duration * SAMPLE_RATE)
    for index, cue in enumerate(cues):
        preset = cue["preset"]
        length = {"pop": .16, "tick": .055, "chime": .48, "whoosh": .38}[preset]
        samples = []
        rng = random.Random(19 + index)
        smooth = 0.0
        for i in range(round(length * SAMPLE_RATE)):
            t = i / SAMPLE_RATE
            x = t / length
            if preset == "whoosh":
                noise = rng.uniform(-1, 1)
                smooth = .7 * smooth + .3 * noise
                sample = smooth * math.sin(math.pi * x) ** 2
            elif preset == "chime":
                sample = (math.sin(2*math.pi*880*t) + .4*math.sin(2*math.pi*1320*t)) * math.exp(-8*x)
            elif preset == "tick":
                sample = math.sin(2*math.pi*1400*t) * math.exp(-10*x)
            else:
                phase = 2 * math.pi * (430*t - 1250*t*t)
                sample = math.sin(phase) * math.exp(-7*x)
            sample *= min(1, t / .004) * min(1, (length-t) / .015)
            samples.append(sample)
        peak = max((abs(s) for s in samples), default=1) or 1
        gain = 10 ** (cue["gain_db"] / 20) / peak
        offset = round(cue["at_seconds"] * SAMPLE_RATE)
        for i, sample in enumerate(samples):
            if 0 <= offset+i < len(mix):
                mix[offset+i] += sample * gain
    peak = max((abs(s) for s in mix), default=0)
    pcm = array.array("h", [round(max(-1, min(1, s)) * 32767) for s in mix])
    import sys
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(output), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(pcm.tobytes())
    return {"count": len(cues), "peak_dbfs": round(20*math.log10(peak), 2) if peak else None}


def composite_scene_direction(
    base: Path, direction: dict, executable: str, width: int, height: int, fps: int, codec: str,
) -> tuple[Path, dict]:
    from .ffmpeg_renderer import _encoding_arguments, _run
    duration = direction["duration_seconds"]
    layers, cues = direction["graphic_layers"], direction["audio_cues"]
    report = {"direction": direction, "applied_layer_ids": [], "applied_audio_cues": 0}
    if not layers and not cues:
        return base, report
    graphic = base.with_suffix(".graphics.mov")
    sound = base.with_suffix(".sfx.wav")
    output = base.with_name(base.stem + "-directed.mp4")
    args = [executable, "-y", "-i", str(base)]
    graph = []
    if layers:
        render_graphic_track(direction, graphic, width, height, fps)
        args += ["-i", str(graphic)]
        graph.append("[0:v:0][1:v:0]overlay=0:0:format=auto:shortest=1,format=yuv420p[v]")
        report["applied_layer_ids"] = [x["id"] for x in layers]
    if cues:
        report["sound"] = write_sound_cues(cues, duration, sound)
        args += ["-i", str(sound)]
        audio_index = 2 if layers else 1
        graph.append(f"[0:a:0][{audio_index}:a:0]amix=inputs=2:normalize=0:duration=first,"
                     "alimiter=limit=0.95:level=false:latency=1[a]")
        report["applied_audio_cues"] = len(cues)
    args += ["-filter_complex", ";".join(graph), "-map", "[v]" if layers else "0:v:0",
             "-map", "[a]" if cues else "0:a:0"]
    args += _encoding_arguments(codec) if layers else ["-c:v", "copy"]
    args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-t", f"{duration:.3f}", "-movflags", "+faststart", str(output)]
    try:
        _run(args, base.parent)
    finally:
        graphic.unlink(missing_ok=True)  # Large alpha intermediate, regenerated from props.
    return output, report
