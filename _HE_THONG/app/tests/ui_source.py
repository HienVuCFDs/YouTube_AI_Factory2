"""The studio interface as one text, however many files it is kept in.

The page used to be a single 7500-line document, so a test could assert that
a behaviour exists by searching that one file. It is now the same document
split into ordered modules - which is the point, but it means "is this in the
UI" is a question about all of them.

This is the only place that knows how the interface is laid out on disk, so
splitting it further later changes one function rather than every test.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "youtube_monitor"
_TEMPLATE = _ROOT / "templates" / "index.html"
_STATIC = _ROOT / "static"


def studio_markup() -> str:
    """Only the document itself, for questions about HTML structure."""
    return _TEMPLATE.read_text(encoding="utf-8")


def studio_ui() -> str:
    """Markup, styles and every script module, in the order the page loads.

    Assertions about behaviour - a handler being wired, a message being
    shown - want this: the code moved between files without changing, and a
    test that only reads the markup would report it missing.
    """
    parts = [studio_markup()]
    for name in sorted(_STATIC.glob("*.css")):
        parts.append(name.read_text(encoding="utf-8"))
    # Document order, which is also the order the split produced them in.
    for name in ("core.js", "studio-lanes.js", "project-detail.js", "library.js", "publish.js"):
        module = _STATIC / name
        if module.is_file():
            parts.append(module.read_text(encoding="utf-8"))
    return "\n".join(parts)
