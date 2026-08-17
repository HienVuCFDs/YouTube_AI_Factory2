from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_requests(path: Path) -> list[dict[str, str]]:
    # Accept a UTF-8 BOM as well: manifests may be inspected or regenerated
    # from Windows tools before being sent to the local GPU runner.
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    # PowerShell's ConvertTo-Json serializes a one-item array as an object.
    # Treat that as a one-request batch so the local test and the worker use
    # the same tolerant manifest contract.
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not payload:
        raise ValueError("VoxCPM manifest phải là một danh sách không rỗng")
    requests: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("VoxCPM manifest có phần tử không hợp lệ")
        text = str(item.get("text") or "").strip()
        output = str(item.get("output") or "").strip()
        if not text or not output:
            raise ValueError("Mỗi đoạn VoxCPM phải có text và output")
        requests.append({key: str(value) for key, value in item.items() if value is not None})
    return requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a batch of voiceover audio with VoxCPM on CUDA.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--model", default="openbmb/VoxCPM2")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--cfg-value", type=float, default=2.0)
    parser.add_argument("--inference-timesteps", type=int, default=10)
    args = parser.parse_args()

    if not args.device.startswith("cuda"):
        raise RuntimeError("VoxCPM production bắt buộc chạy bằng CUDA")

    import soundfile as sf
    # VoxCPM currently imports librosa, whose newer releases expect this
    # exception name.  The local pyVideoTrans environment ships soundfile
    # 0.9, which raises the same RuntimeError but does not export the name.
    # Keep the fallback decoder path usable without changing global packages.
    if not hasattr(sf, "SoundFileRuntimeError"):
        sf.SoundFileRuntimeError = RuntimeError  # type: ignore[attr-defined]
    # VoxCPM currently imports librosa, whose newer releases expect this
    # exception name.  The local pyVideoTrans environment ships soundfile
    # 0.9, which raises the same RuntimeError but does not export the name.
    # Keep the fallback decoder path usable without changing global packages.
    if not hasattr(sf, "SoundFileRuntimeError"):
        sf.SoundFileRuntimeError = RuntimeError  # type: ignore[attr-defined]
    import torch
    from voxcpm import VoxCPM

    if not torch.cuda.is_available():
        raise RuntimeError("VoxCPM không phát hiện được CUDA")

    model = VoxCPM.from_pretrained(
        args.model,
        load_denoiser=False,
        device=args.device,
    )
    for index, item in enumerate(_load_requests(Path(args.manifest)), start=1):
        output_path = Path(item["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = item["text"]
        style = str(item.get("style") or "").strip()
        if style:
            text = f"({style}){text}"
        kwargs: dict[str, object] = {
            "text": text,
            "cfg_value": args.cfg_value,
            "inference_timesteps": args.inference_timesteps,
            "normalize": True,
        }
        reference_audio = str(item.get("reference_audio") or "").strip()
        prompt_text = str(item.get("prompt_text") or "").strip()
        if reference_audio:
            kwargs["reference_wav_path"] = reference_audio
        if prompt_text:
            kwargs["prompt_wav_path"] = reference_audio
            kwargs["prompt_text"] = prompt_text
        # VoxCPM 2.0.3 does not expose ``seed`` in generate(), while newer
        # releases do.  Seed torch directly so the installed local runtime can
        # still produce repeatable voice-design auditions.
        if str(item.get("seed") or "").strip():
            seed = int(str(item["seed"]))
            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
        wav = model.generate(**kwargs)
        sf.write(str(output_path), wav, model.tts_model.sample_rate)
        print(json.dumps({"index": index, "output": str(output_path)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
