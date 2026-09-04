"""The voice model the user picked must be the one that comes back."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from youtube_monitor.main import database
from tests.ui_source import studio_ui


@pytest.fixture(scope="module")
def page() -> str:
    return studio_ui()


def test_changing_the_provider_writes_the_choice_down(page: str) -> None:
    """Step 4 rehydrates this dropdown from the project's saved settings every
    time it is entered. A choice that lived only in the page was therefore
    overwritten on the walk back in - pick Edge TTS, leave, return, VoxCPM.
    """
    listener = page[page.index("$('studioVoiceProviderSelect')?.addEventListener"):]
    listener = listener[:listener.index("});")]

    assert "saveRenderSettings" in listener


def test_that_save_does_not_announce_itself(page: str) -> None:
    """It happens on every click of the dropdown; two banners per click bury
    the messages the user actually needs to read."""
    listener = page[page.index("$('studioVoiceProviderSelect')?.addEventListener"):]
    listener = listener[:listener.index("});")]

    assert "quiet: true" in listener
    assert re.search(r"if \(!quiet\) setMessage\('Đang lưu thiết lập render", page)


def test_switching_provider_keeps_the_voice_sample(tmp_path) -> None:
    """Moving to Edge TTS and back must not lose the VoxCPM sample: without
    one, VoxCPM invents a different speaker for every scene."""
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000031",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000031",
        "title": "Kenh", "uploads_playlist_id": "UU0000000000000000000031",
    })
    database.upsert_video({
        "youtube_video_id": "video-voice-provider", "youtube_channel_id": "UC0000000000000000000031",
        "video_url": "https://x/video-voice-provider", "title": "Nguon", "description": "",
        "metadata_hash": "h-voice-provider", "raw_payload": {},
    })
    project = database.create_production_project("video-voice-provider", title="Giong")
    project_id = int(project["id"])
    sample = tmp_path / "mau.wav"
    sample.write_bytes(b"RIFF")
    asset = database.create_project_asset(
        project_id, asset_type="audio", original_name="mau.wav",
        file_path=str(sample), mime_type="audio/wav", file_size=4,
    )

    def save(provider: str, reference: int | None) -> dict:
        current = database.get_project_render_settings(project_id)
        return database.update_project_render_settings(
            project_id,
            music_asset_id=current.get("music_asset_id"),
            music_volume=float(current.get("music_volume") or 0.12),
            transition_style="fade", output_profile="youtube_landscape",
            voice_provider=provider, voice_model="vi-VN-HoaiMyNeural", voice_rate="+0%",
            voice_reference_asset_id=reference, voice_prompt_text="",
            subtitle_provider="timeline_text", subtitle_model="timeline", publish_language="vi",
        )

    save("voxcpm", int(asset["id"]))
    moved = save("edge_tts", int(asset["id"]))

    assert moved["voice_provider"] == "edge_tts"
    assert moved["voice_reference_asset_id"] == int(asset["id"])


def test_an_unloaded_sample_field_is_not_read_as_a_cleared_one(page: str) -> None:
    """The hidden field is filled in by hydrateStudioVoiceSettings, which runs
    only once step 4 is open. Saving before that read the empty field as "no
    sample" and wiped the project's voice."""
    block = page[page.index("voice_reference_asset_id: (() =>"):]
    block = block[:block.index("})(),")]

    assert "options.length > 1" in block, "phai phan biet chua nap voi da xoa"
    assert "stored" in block
