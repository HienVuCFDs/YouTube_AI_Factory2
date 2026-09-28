"""Piper: a Vietnamese voice that keeps working when nothing else does.

Every other engine here depends on something outside the machine - Edge on a
public endpoint that intermittently returns no audio, Google on an API key and
a monthly allowance. Piper runs locally from an .onnx file on CPU, so a render
is never blocked by a quota, a network, or a service having a bad day. The
voice is less polished than Google's; being available is the point.

Models are downloaded once from the Piper release page; `vi_VN-vais1000-medium`
is the usual Vietnamese choice.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

TIMEOUT_SECONDS = 300


class PiperTtsError(RuntimeError):
    pass


def command(binary: str, model: Path, output_path: Path, *, speaker: int | None = None) -> list[str]:
    """The piper invocation. Text arrives on stdin, so it is never quoted into
    a shell command where an apostrophe in the narration could break it."""
    args = [binary, "--model", str(model), "--output_file", str(output_path)]
    if speaker is not None:
        args += ["--speaker", str(speaker)]
    return args


def available(binary: str, model: str) -> bool:
    """Whether a render could actually use Piper right now."""
    return bool(shutil.which(binary) and str(model).strip() and Path(model).is_file())


def synthesize(
    text: str,
    output_path: Path,
    *,
    binary: str = "piper",
    model: str = "",
    speaker: int | None = None,
) -> Path:
    """Speak `text` into `output_path` as WAV, or raise PiperTtsError."""
    spoken = str(text or "").strip()
    if not spoken:
        raise PiperTtsError("Không có lời để đọc")
    resolved = shutil.which(binary)
    if not resolved:
        raise PiperTtsError(f"Không tìm thấy piper: {binary}")
    model_path = Path(str(model or ""))
    if not model_path.is_file():
        raise PiperTtsError(
            f"Không tìm thấy model Piper: {model or '(chưa cấu hình)'}. "
            "Tải một model vi_VN (ví dụ vi_VN-vais1000-medium.onnx) rồi trỏ PIPER_MODEL vào nó."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command(resolved, model_path, output_path, speaker=speaker),
            input=spoken,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PiperTtsError(f"Chạy piper thất bại: {exc}") from exc
    if result.returncode != 0:
        raise PiperTtsError((result.stderr or result.stdout or "piper thất bại").strip()[-600:])
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise PiperTtsError("piper chạy xong nhưng không tạo được audio")
    return output_path
