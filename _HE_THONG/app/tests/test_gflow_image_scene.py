"""Flow's image side: one still, or the chained frames of a motion loop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_monitor import scene_generator
from youtube_monitor.gif_generator import GFLOW_GIF_FRAME_COUNT


class _FakeDatabase:
    EXTERNAL_SIDECAR_PROVIDERS: set[str] = set()

    def __init__(self) -> None:
        self.beats: list[str] = []

    def get_production_project(self, project_id: int) -> dict[str, object]:
        return {"id": project_id, "title": "Test", "gflow_project_id": "cloud-1", "gflow_profile": "default"}

    def get_project_asset(self, asset_id: int) -> dict[str, object] | None:
        return None

    def touch_scene_generation_job(self, job_id: int, stage: str) -> None:
        self.beats.append(stage)


def _job(**overrides: object) -> dict[str, object]:
    job = {
        "id": 7,
        "project_id": 3,
        "timeline_segment_id": 11,
        "job_kind": "image",
        "prompt": "a quiet street at dawn",
        "duration_seconds": 4,
        "visual_fps": 8,
    }
    job.update(overrides)
    return job


@pytest.fixture()
def flow_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_generate(job, reference_path, output_path, *, gflow_project_id="", heartbeat=None):
        calls.append({
            "prompt": str(job.get("prompt") or ""),
            "reference": str(reference_path) if reference_path else None,
            "output": str(output_path),
        })
        if heartbeat:
            heartbeat()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"png-bytes")
        return str(output_path)

    monkeypatch.setattr(scene_generator, "generate_gflow_image", fake_generate)
    monkeypatch.setattr(scene_generator, "create_gflow_project", lambda *a, **k: "cloud-1")
    return calls


def test_still_scene_asks_flow_once(tmp_path: Path, flow_calls: list[dict[str, object]]) -> None:
    output = scene_generator.generate_gflow_image_scene(_FakeDatabase(), _job(), tmp_path)

    assert len(flow_calls) == 1
    assert flow_calls[0]["reference"] is None
    assert output.endswith(".png")


def test_gif_frames_chain_each_onto_the_previous(
    tmp_path: Path, flow_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every frame after the first must be drawn from the one before it.

    This is the whole point of the route: without the chain each frame is an
    independent drawing, which is how the old sheet ended up with a moving
    background and a subject that never changed.
    """
    assembled: dict[str, object] = {}

    def fake_assemble(frames, output_path, **kwargs):
        assembled["frames"] = [str(item) for item in frames]
        Path(output_path).write_bytes(b"gif-bytes")
        return str(output_path)

    monkeypatch.setattr(scene_generator, "create_gif_from_frames", fake_assemble)
    prompts = [f"frame {index + 1}" for index in range(GFLOW_GIF_FRAME_COUNT)]

    output = scene_generator.generate_gflow_image_scene(
        _FakeDatabase(),
        _job(job_kind="gif", prompt=json.dumps({"frames": prompts})),
        tmp_path,
    )

    assert [call["prompt"] for call in flow_calls] == prompts
    assert flow_calls[0]["reference"] is None
    for previous, call in zip(flow_calls, flow_calls[1:]):
        assert call["reference"] == previous["output"]
    assert assembled["frames"] == [call["output"] for call in flow_calls]
    assert output.endswith(".gif")


def test_gif_falls_back_when_no_per_frame_prompts_were_written(
    tmp_path: Path, flow_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain prompt still produces a chained loop rather than an error."""
    monkeypatch.setattr(
        scene_generator,
        "create_gif_from_frames",
        lambda frames, output_path, **kwargs: (Path(output_path).write_bytes(b"gif"), str(output_path))[1],
    )

    scene_generator.generate_gflow_image_scene(
        _FakeDatabase(), _job(job_kind="gif", prompt="a bar chart filling up"), tmp_path
    )

    assert len(flow_calls) == GFLOW_GIF_FRAME_COUNT
    assert flow_calls[0]["prompt"] == "a bar chart filling up"
    assert "stage 2" in str(flow_calls[1]["prompt"])
    assert flow_calls[1]["reference"] == flow_calls[0]["output"]


def test_heartbeat_runs_for_every_frame(
    tmp_path: Path, flow_calls: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four drawings in a row take minutes; the watchdog must not reclaim them."""
    monkeypatch.setattr(
        scene_generator,
        "create_gif_from_frames",
        lambda frames, output_path, **kwargs: (Path(output_path).write_bytes(b"gif"), str(output_path))[1],
    )
    database = _FakeDatabase()

    scene_generator.generate_gflow_image_scene(
        database, _job(job_kind="gif", prompt="counter ticking up"), tmp_path
    )

    assert database.beats == [f"gflow_gif_frame_{index + 1}" for index in range(GFLOW_GIF_FRAME_COUNT)]
