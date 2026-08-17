from __future__ import annotations

from pathlib import Path


FOLDER_NAMES = {
    "script": "01_KICH_BAN",
    "audio": "02_AM_THANH",
    "assets": "03_TAI_NGUYEN",
    "exports": "04_XUAT_BAN",
    "premiere": "05_PREMIERE",
    "work": "_WORK",
}


def project_root(artifact_root: Path, project_id: int | str) -> Path:
    return Path(artifact_root) / str(project_id)


def ensure_project_layout(artifact_root: Path, project_id: int | str) -> dict[str, Path]:
    """Return one predictable, user-facing folder layout for a project."""
    root = project_root(artifact_root, project_id)
    layout = {"root": root}
    for key, name in FOLDER_NAMES.items():
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        layout[key] = directory
    return layout

