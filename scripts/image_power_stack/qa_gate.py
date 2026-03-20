#!/usr/bin/env python3
"""Image QA gate: resolution/bytes/blur/delta checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def grayscale_arr(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("L"), dtype=np.float32)


def blur_score(gray: np.ndarray) -> float:
    # Laplacian variance approximation via finite differences
    lap = (
        -4 * gray
        + np.roll(gray, 1, axis=0)
        + np.roll(gray, -1, axis=0)
        + np.roll(gray, 1, axis=1)
        + np.roll(gray, -1, axis=1)
    )
    return float(np.var(lap))


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0])
        w = min(a.shape[1], b.shape[1])
        a = a[:h, :w]
        b = b[:h, :w]
    mse = np.mean((a - b) ** 2)
    if mse <= 1e-12:
        return 99.0
    return float(20 * np.log10(255.0 / np.sqrt(mse)))


def run_checks(args: argparse.Namespace) -> dict[str, Any]:
    out_path = Path(args.output)
    out_img = Image.open(out_path)
    out_size = out_path.stat().st_size
    width, height = out_img.size

    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    if args.min_width:
        add_check("min_width", width >= args.min_width, f"width={width} min={args.min_width}")
    if args.min_height:
        add_check("min_height", height >= args.min_height, f"height={height} min={args.min_height}")
    if args.max_bytes:
        add_check("max_bytes", out_size <= args.max_bytes, f"bytes={out_size} max={args.max_bytes}")
    if args.min_bytes:
        add_check("min_bytes", out_size >= args.min_bytes, f"bytes={out_size} min={args.min_bytes}")

    out_gray = np.array(out_img.convert("L"), dtype=np.float32)
    blur = blur_score(out_gray)
    if args.min_blur_score is not None:
        add_check("min_blur_score", blur >= args.min_blur_score, f"blur_score={blur:.2f} min={args.min_blur_score}")

    psnr_val = None
    if args.source:
        src_gray = grayscale_arr(Path(args.source))
        psnr_val = psnr(src_gray, out_gray)
        if args.min_psnr is not None:
            add_check("min_psnr", psnr_val >= args.min_psnr, f"psnr={psnr_val:.2f} min={args.min_psnr}")
        if args.max_psnr is not None:
            add_check("max_psnr", psnr_val <= args.max_psnr, f"psnr={psnr_val:.2f} max={args.max_psnr}")

    overall = all(item["ok"] for item in checks) if checks else True
    return {
        "ok": overall,
        "output": str(out_path),
        "width": width,
        "height": height,
        "bytes": out_size,
        "blur_score": blur,
        "psnr": psnr_val,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Image QA gate")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source")
    parser.add_argument("--min-width", type=int)
    parser.add_argument("--min-height", type=int)
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--min-bytes", type=int)
    parser.add_argument("--min-blur-score", type=float)
    parser.add_argument("--min-psnr", type=float)
    parser.add_argument("--max-psnr", type=float)
    args = parser.parse_args()

    result = run_checks(args)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
