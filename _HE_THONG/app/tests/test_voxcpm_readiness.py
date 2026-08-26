"""Deciding whether VoxCPM can run, and saying why when it cannot."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from youtube_monitor import settings


@pytest.fixture(autouse=True)
def clear_cache():
    settings._voxcpm_probe = None
    yield
    settings._voxcpm_probe = None


def test_a_missing_runner_is_named_not_blamed_on_cuda(monkeypatch) -> None:
    monkeypatch.setattr(settings, "VOXCPM_RUNNER", Path("F:/khong-co-that.py"))

    ready, detail = settings.voxcpm_runtime_status()

    assert not ready
    assert "khong-co-that.py" in detail


def test_a_cpu_device_says_so(monkeypatch) -> None:
    monkeypatch.setattr(settings, "VOXCPM_DEVICE", "cpu")

    ready, detail = settings.voxcpm_runtime_status()

    assert not ready
    assert "cpu" in detail


def test_a_slow_first_import_is_reported_as_slow_not_as_broken(monkeypatch) -> None:
    """Loading torch and waking CUDA can take a long time on a cold disk, which
    is the state the machine is in when the app starts from its .bat right
    after boot. Telling the user to install voxcpm sends them to fix something
    that was never wrong."""
    monkeypatch.setattr(settings, "VOXCPM_PYTHON", Path(__file__))
    monkeypatch.setattr(settings, "VOXCPM_RUNNER", Path(__file__))
    monkeypatch.setattr(settings, "VOXCPM_DEVICE", "cuda")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="probe", timeout=180)

    monkeypatch.setattr(settings.subprocess, "run", timeout)
    ready, detail = settings.voxcpm_runtime_status()

    assert not ready
    assert "thử lại" in detail


def test_the_probes_answer_is_remembered(monkeypatch) -> None:
    """It costs about five seconds; running it per request would be felt."""
    calls = []
    monkeypatch.setattr(settings, "_run_voxcpm_probe", lambda: (calls.append(1), (True, ""))[1])

    settings.voxcpm_runtime_status()
    settings.voxcpm_runtime_status()

    assert len(calls) == 1


def test_a_failure_is_asked_about_again(monkeypatch) -> None:
    """The flag used to be worked out once at import and frozen, so a probe
    that timed out at startup left VoxCPM unusable for the whole session and
    restarting the app was the only cure."""
    calls = []
    monkeypatch.setattr(settings, "_run_voxcpm_probe", lambda: (calls.append(1), (False, "cham"))[1])
    monkeypatch.setattr(settings, "_VOXCPM_RETRY_AFTER_SECONDS", 0)

    settings.voxcpm_runtime_status()
    settings.voxcpm_runtime_status()

    assert len(calls) == 2


def test_nothing_probes_at_import_time() -> None:
    """Starting the app must not wait on torch."""
    source = (Path(settings.__file__)).read_text(encoding="utf-8")

    assert "VOXCPM_RUNTIME_READY = " not in source
