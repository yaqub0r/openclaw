#!/usr/bin/env python3
"""Generative image edit bridge.

Supported providers:
- automatic1111 (local Stable Diffusion WebUI API)
- none (pass-through)

Usage:
  python3 tools/image_power_stack/generative_bridge.py \
    --provider automatic1111 \
    --input in.png \
    --prompt "cinematic relight" \
    --output out.png \
    --mask optional_mask.png
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image


def b64_image(path: Path) -> str:
    buf = io.BytesIO()
    Image.open(path).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def save_b64_image(b64: str, out_path: Path) -> None:
    raw = base64.b64decode(b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)


def http_post_json(url: str, payload: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def run_automatic1111(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.api_url or os.getenv("AUTOMATIC1111_URL", "http://127.0.0.1:7860")
    endpoint = f"{base_url.rstrip('/')}/sdapi/v1/img2img"

    payload: dict[str, Any] = {
        "init_images": [b64_image(Path(args.input))],
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "steps": int(args.steps),
        "cfg_scale": float(args.cfg_scale),
        "denoising_strength": float(args.denoise),
        "sampler_name": args.sampler,
        "width": args.width,
        "height": args.height,
        "batch_size": 1,
    }

    if args.mask:
        payload["mask"] = b64_image(Path(args.mask))
        payload["inpainting_fill"] = 1
        payload["inpaint_full_res"] = True
        payload["inpainting_mask_invert"] = 0

    response = http_post_json(endpoint, payload)
    images = response.get("images") or []
    if not images:
        raise RuntimeError("automatic1111 returned no images")

    save_b64_image(images[0], Path(args.output))
    return {
        "provider": "automatic1111",
        "api": endpoint,
        "output": args.output,
    }


def run_none(args: argparse.Namespace) -> dict[str, Any]:
    src = Path(args.input)
    dst = Path(args.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    return {"provider": "none", "output": args.output, "passthrough": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generative edit bridge")
    parser.add_argument("--provider", default="none", choices=["none", "automatic1111"])
    parser.add_argument("--api-url", help="Automatic1111 base URL, e.g. http://127.0.0.1:7860")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mask")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--steps", type=int, default=28)
    parser.add_argument("--cfg-scale", type=float, default=7.0)
    parser.add_argument("--denoise", type=float, default=0.45)
    parser.add_argument("--sampler", default="DPM++ 2M Karras")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    args = parser.parse_args()

    if args.provider == "automatic1111":
        result = run_automatic1111(args)
    else:
        result = run_none(args)

    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
