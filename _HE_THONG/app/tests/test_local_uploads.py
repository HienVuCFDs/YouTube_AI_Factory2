"""Starting a project from a file on the user's machine."""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from youtube_monitor import main
from youtube_monitor.main import (
    LOCAL_UPLOAD_CHANNEL_ID,
    _contact_sheet_for_review,
    _xstack_layout,
    analyze_reference_images,
    database,
    upload_local_source,
)

FFMPEG = shutil.which("ffmpeg")


def _upload(name: str, payload: bytes = b"0" * 2048) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(payload))


def _clip(path: Path, seconds: int = 2) -> Path:
    subprocess.run(
        [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )
    return path


def _audio_clip(path: Path, seconds: int = 2) -> Path:
    subprocess.run(
        [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "aac", str(path)],
        check=True, capture_output=True,
    )
    return path


def _image(path: Path, colour: str = "red") -> Path:
    subprocess.run(
        [str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:d=1", "-frames:v", "1", str(path)],
        check=True, capture_output=True,
    )
    return path


@pytest.mark.skipif(FFMPEG is None, reason="Can FFmpeg de tao file thu")
def test_an_uploaded_video_becomes_a_usable_source(tmp_path: Path) -> None:
    """It has to look like any other source, or nothing downstream works."""
    clip = _clip(tmp_path / "canh.mp4", seconds=3)

    with clip.open("rb") as handle:
        result = upload_local_source(file=UploadFile(filename="canh.mp4", file=handle), title="")

    video = result["video"]
    assert video["youtube_video_id"].startswith("local-")
    assert video["youtube_channel_id"] == LOCAL_UPLOAD_CHANNEL_ID
    assert video["media_status"] == "downloaded_for_editing"
    assert Path(video["local_media_path"]).is_file(), "file phai nam tren dia de con cat canh duoc"
    assert result["duration_seconds"] == 3, "thoi luong phai doc tu chinh file"
    assert result["media_kind"] == "video"


@pytest.mark.skipif(FFMPEG is None, reason="Can FFmpeg de tao file thu")
def test_the_title_falls_back_to_the_file_name(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "Su tich trau cau.mp4")

    with clip.open("rb") as handle:
        result = upload_local_source(file=UploadFile(filename="Su tich trau cau.mp4", file=handle), title="")

    assert result["video"]["title"] == "Su tich trau cau"


@pytest.mark.skipif(FFMPEG is None, reason="Can FFmpeg de tao file thu")
def test_an_uploaded_audio_is_identified_as_audio(tmp_path: Path) -> None:
    recording = _audio_clip(tmp_path / "noi-dung.m4a", seconds=2)

    with recording.open("rb") as handle:
        result = upload_local_source(file=UploadFile(filename="noi-dung.m4a", file=handle), title="")

    assert result["media_kind"] == "audio"
    assert result["duration_seconds"] == 2


def test_a_file_that_is_not_media_is_refused() -> None:
    with pytest.raises(HTTPException) as caught:
        upload_local_source(file=_upload("ghi_chu.txt"), title="")

    assert caught.value.status_code == 400
    assert ".txt" in str(caught.value.detail)


def test_an_empty_file_is_refused() -> None:
    """A zero-byte upload would register a source that cannot be read."""
    with pytest.raises(HTTPException) as caught:
        upload_local_source(file=UploadFile(filename="rong.mp4", file=io.BytesIO(b"")), title="")

    assert caught.value.status_code == 400


def test_a_renamed_non_media_file_is_refused_and_removed() -> None:
    """The extension cannot turn arbitrary bytes into a usable source."""
    before = set(Path(main.PRODUCTION_ARTIFACT_DIR).glob("_tai_len/*"))

    with pytest.raises(HTTPException) as caught:
        upload_local_source(file=_upload("khong-phai-video.mp4"), title="")

    assert caught.value.status_code == 400
    assert set(Path(main.PRODUCTION_ARTIFACT_DIR).glob("_tai_len/*")) == before


def test_nothing_is_left_behind_when_the_upload_is_refused() -> None:
    before = set(Path(main.PRODUCTION_ARTIFACT_DIR).glob("_tai_len/*"))

    with pytest.raises(HTTPException):
        upload_local_source(file=_upload("ghi_chu.txt"), title="")

    assert set(Path(main.PRODUCTION_ARTIFACT_DIR).glob("_tai_len/*")) == before


# --- bang ghep anh tham khao ---------------------------------------------


def test_the_grid_positions_are_row_major() -> None:
    assert _xstack_layout(4, 2) == "0_0|w0_0|0_h0|w0_h0"
    assert _xstack_layout(5, 3) == "0_0|w0_0|w0+w0_0|0_h0|w0_h0"


@pytest.mark.skipif(FFMPEG is None, reason="Can FFmpeg de ghep anh")
def test_one_image_is_shown_as_itself(tmp_path: Path) -> None:
    """Tiling a single picture would only shrink it for no reason."""
    only = _image(tmp_path / "mot.png")

    assert _contact_sheet_for_review([only], 424242) == only


@pytest.mark.skipif(FFMPEG is None, reason="Can FFmpeg de ghep anh")
def test_several_images_are_tiled_into_one(tmp_path: Path) -> None:
    """A model shown them one at a time describes each, not what they share."""
    images = [_image(tmp_path / f"r{index}.png", colour) for index, colour
              in enumerate(["red", "green", "blue", "orange"])]

    sheet = _contact_sheet_for_review(images, 424243)

    assert sheet not in images
    assert sheet.is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(sheet)],
        capture_output=True, text=True,
    )
    assert probe.stdout.strip() == "1280,1280", "4 anh phai xep 2x2 o 640px moi o"


def test_analysing_images_needs_some_images() -> None:
    database.upsert_channel({
        "youtube_channel_id": "UC0000000000000000000003",
        "channel_url": "https://www.youtube.com/channel/UC0000000000000000000003",
        "title": "Kenh",
        "uploads_playlist_id": "UU0000000000000000000003",
    })
    database.upsert_video({
        "youtube_video_id": "video-no-images",
        "youtube_channel_id": "UC0000000000000000000003",
        "video_url": "https://www.youtube.com/watch?v=video-no-images",
        "title": "Nguon", "description": "", "metadata_hash": "h-noimg", "raw_payload": {},
    })
    project = database.create_production_project("video-no-images", title="Khong anh")

    with pytest.raises(HTTPException) as caught:
        analyze_reference_images(int(project["id"]), limit=6)

    assert caught.value.status_code == 400
