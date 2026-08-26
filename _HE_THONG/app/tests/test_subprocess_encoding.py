"""Every child process must be decoded as UTF-8, not as the machine's locale.

VoxCPM's failure looked like the model was broken. It was not: the runner ran
fine, but the parent decoded its output with cp1252, the reader thread died on
the first Vietnamese byte, and `result.stderr` came back empty. The app then
raised "VoxCPM GPU process failed" with nothing after the colon - an error
message with the error removed.

Twenty-five call sites had the same hole, and every tool this app drives
(yt-dlp, FFmpeg, the CLI bridges) prints Vietnamese titles and paths.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "youtube_monitor"
LAUNCHERS = {"run", "Popen", "check_output", "call", "check_call"}


def _calls_decoding_text() -> list[tuple[str, int, set[str | None]]]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in LAUNCHERS:
                continue
            keys = {kw.arg for kw in node.keywords}
            if "text" in keys or "universal_newlines" in keys:
                found.append((path.name, node.lineno, keys))
    return found


def test_the_scan_actually_finds_the_call_sites() -> None:
    """A test that silently matches nothing would pass forever."""
    assert len(_calls_decoding_text()) > 20


@pytest.mark.parametrize("call", _calls_decoding_text(), ids=lambda c: f"{c[0]}:{c[1]}")
def test_a_decoded_call_states_its_encoding(call: tuple[str, int, set[str | None]]) -> None:
    name, lineno, keys = call
    assert "encoding" in keys, (
        f"{name}:{lineno} decodes child output with the system locale; "
        "on Windows that is cp1252 and Vietnamese output is lost"
    )


@pytest.mark.parametrize("call", _calls_decoding_text(), ids=lambda c: f"{c[0]}:{c[1]}")
def test_a_decoded_call_survives_a_byte_it_cannot_map(call: tuple[str, int, set[str | None]]) -> None:
    """Even UTF-8 is not safe: a tool that writes raw bytes (a progress bar, a
    truncated multi-byte character) would still raise, and a crash while
    reading an error message hides the error."""
    name, lineno, keys = call
    assert "errors" in keys, f"{name}:{lineno} has no errors= fallback while decoding"
