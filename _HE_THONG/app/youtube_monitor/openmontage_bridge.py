from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    from tools.video.video_compose import VideoCompose

    result = VideoCompose().execute(payload)
    report = {
        "success": bool(result.success),
        "data": result.data,
        "error": result.error,
        "artifacts": result.artifacts,
    }
    Path(args.result).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if not result.success:
        print(result.error or "OpenMontage tool thất bại", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
