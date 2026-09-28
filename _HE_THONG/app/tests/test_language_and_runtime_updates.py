from pathlib import Path
import threading

from youtube_monitor import languages, settings
from youtube_monitor.database import Database
from youtube_monitor.thumbnail_generator import compose_thumbnail


def test_german_and_spanish_have_distinct_script_instructions():
    assert "German" in languages.instruction("de")
    assert "Spanish" in languages.instruction("es")
    assert languages.resolve("de")["tokens_per_second"] != languages.resolve("vi")["tokens_per_second"]


def test_thumbnail_selections_are_independent(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    project = db.create_idea_project("A shelter in the mountains", title="Shelter")
    selected = {}
    for variant in ("long", "short"):
        asset = db.create_project_asset(project["id"], "image", f"{variant}.jpg", str(tmp_path / f"{variant}.jpg"))
        thumb = db.create_project_thumbnail(project["id"], asset["id"], video_variant=variant)
        selected[variant] = db.select_project_thumbnail(thumb["id"])["id"]
    assert {item["video_variant"]: item["id"] for item in db.list_project_thumbnails(project["id"]) if item["selected"]} == selected


def test_cover_export_preserves_vertical_shape_and_text(tmp_path):
    from PIL import Image
    source = tmp_path / "source.png"
    Image.new("RGB", (400, 800), "#225566").save(source)
    output = compose_thumbnail(source, tmp_path / "cover.jpg", vertical=True, title="Überleben im Wald")
    with Image.open(output) as result:
        assert result.size == (720, 1280)
        assert result.format == "JPEG"
        assert len(result.getcolors(720 * 1280)) > 1


def test_voxcpm_status_does_not_wait_or_spawn_duplicate_probes(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def probe():
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return True, ""
    monkeypatch.setattr(settings, "_voxcpm_probe", None)
    monkeypatch.setattr(settings, "_voxcpm_probe_thread", None)
    monkeypatch.setattr(settings, "_run_voxcpm_probe", probe)
    try:
        assert settings.voxcpm_runtime_status(wait=False)[0] is False
        assert entered.wait(1)
        assert settings.voxcpm_runtime_status(wait=False)[0] is False
        assert calls == [1]
    finally:
        release.set()
        settings._voxcpm_probe_thread.join(3)
    assert settings.voxcpm_runtime_status() == (True, "")


def test_native_voice_previews_use_native_text(tmp_path, monkeypatch):
    from youtube_monitor import main
    monkeypatch.setattr(main, "PRODUCTION_ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(main, "EDGE_TTS_RUNTIME_READY", True)
    monkeypatch.setattr(main, "EDGE_TTS_COMMAND", 'tts "{text_file}" "{output_file}" {voice_role}')
    requests = []
    def synthesize(args, **kwargs):
        text_path, audio_path = Path(args[1]), Path(args[2])
        requests.append((args[-1], text_path.read_text(encoding="utf-8")))
        audio_path.write_bytes(b"test-audio")
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr(main.subprocess, "run", synthesize)
    main.stream_edge_voice_preview("de-DE-KatjaNeural", "+0%")
    main.stream_edge_voice_preview("es-ES-ElviraNeural", "+0%")
    assert "Hörprobe" in requests[0][1]
    assert "muestra de voz" in requests[1][1]
