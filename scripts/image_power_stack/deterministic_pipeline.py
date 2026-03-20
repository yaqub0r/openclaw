#!/usr/bin/env python3
"""Deterministic image pipeline runner (Pillow + NumPy).

Usage:
  python3 tools/image_power_stack/deterministic_pipeline.py \
    --input in.png --pipeline presets/ecommerce-cleanup.json --output out.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageColor, ImageEnhance, ImageFilter, ImageOps, ImageDraw, ImageFont


def _to_rgb_color(value: str | list[int] | tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(value, str):
        return ImageColor.getrgb(value)
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return (0, 0, 0)


def op_resize_exact(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    return img.resize((int(cfg["width"]), int(cfg["height"])), Image.Resampling.LANCZOS)


def op_resize_fit(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    width = int(cfg["width"])
    height = int(cfg["height"])
    color = _to_rgb_color(cfg.get("pad_color", "#000000"))
    return ImageOps.pad(img, (width, height), color=color, method=Image.Resampling.LANCZOS)


def op_crop_center(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    width = int(cfg["width"])
    height = int(cfg["height"])
    w, h = img.size
    left = max(0, (w - width) // 2)
    top = max(0, (h - height) // 2)
    right = min(w, left + width)
    bottom = min(h, top + height)
    return img.crop((left, top, right, bottom))


def op_rotate(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    return img.rotate(float(cfg.get("degrees", 0.0)), expand=bool(cfg.get("expand", True)))


def op_levels(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    brightness = float(cfg.get("brightness", 1.0))
    contrast = float(cfg.get("contrast", 1.0))
    color = float(cfg.get("color", 1.0))
    sharpness = float(cfg.get("sharpness", 1.0))

    out = ImageEnhance.Brightness(img).enhance(brightness)
    out = ImageEnhance.Contrast(out).enhance(contrast)
    out = ImageEnhance.Color(out).enhance(color)
    out = ImageEnhance.Sharpness(out).enhance(sharpness)
    return out


def op_denoise_median(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    size = int(cfg.get("size", 3))
    size = max(3, size if size % 2 == 1 else size + 1)
    return img.filter(ImageFilter.MedianFilter(size=size))


def op_unsharp(img: Image.Image, cfg: dict[str, Any]) -> Image.Image:
    radius = float(cfg.get("radius", 2.0))
    percent = int(cfg.get("percent", 150))
    threshold = int(cfg.get("threshold", 3))
    return img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))


def op_overlay_image(img: Image.Image, cfg: dict[str, Any], base_dir: Path) -> Image.Image:
    path = Path(cfg["path"])
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    overlay = Image.open(path).convert("RGBA")

    if cfg.get("scale"):
        scale = float(cfg["scale"])
        ow, oh = overlay.size
        overlay = overlay.resize((max(1, int(ow * scale)), max(1, int(oh * scale))), Image.Resampling.LANCZOS)

    opacity = float(cfg.get("opacity", 1.0))
    if opacity < 1.0:
        alpha = overlay.split()[-1]
        alpha = alpha.point(lambda p: int(p * max(0.0, min(1.0, opacity))))
        overlay.putalpha(alpha)

    out = img.convert("RGBA")
    x = int(cfg.get("x", 0))
    y = int(cfg.get("y", 0))
    out.alpha_composite(overlay, dest=(x, y))
    return out.convert("RGB")


def op_draw_text(img: Image.Image, cfg: dict[str, Any], base_dir: Path) -> Image.Image:
    out = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(out)
    text = str(cfg.get("text", ""))
    x = int(cfg.get("x", 0))
    y = int(cfg.get("y", 0))
    fill = cfg.get("color", "#FFFFFF")
    font_size = int(cfg.get("size", 32))

    font = None
    font_path = cfg.get("font")
    if font_path:
        fp = Path(font_path)
        if not fp.is_absolute():
            fp = (base_dir / fp).resolve()
        if fp.exists():
            font = ImageFont.truetype(str(fp), font_size)
    if font is None:
        font = ImageFont.load_default()

    draw.text((x, y), text, fill=fill, font=font)
    return out.convert("RGB")


def _gaussian_kernel(size: int, sigma: float) -> np.ndarray:
    ax = np.arange(-size // 2 + 1.0, size // 2 + 1.0)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-(xx**2 + yy**2) / (2.0 * sigma**2))
    kernel = kernel / np.sum(kernel)
    return kernel


def _convolve2d(channel: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(channel, ((ph, ph), (pw, pw)), mode="reflect")
    out = np.zeros_like(channel, dtype=np.float32)
    for i in range(channel.shape[0]):
        for j in range(channel.shape[1]):
            patch = padded[i : i + kh, j : j + kw]
            out[i, j] = np.sum(patch * kernel)
    return out


def op_mask_blur(img: Image.Image, cfg: dict[str, Any], base_dir: Path) -> Image.Image:
    mask_path = Path(cfg["mask_path"])
    if not mask_path.is_absolute():
        mask_path = (base_dir / mask_path).resolve()
    mask = Image.open(mask_path).convert("L")

    radius = max(1, int(cfg.get("radius", 6)))
    sigma = max(0.8, radius / 2.0)
    ksize = radius * 2 + 1
    kernel = _gaussian_kernel(ksize, sigma)

    arr = np.array(img.convert("RGB"), dtype=np.float32)
    blurred = np.zeros_like(arr)
    for c in range(3):
        blurred[:, :, c] = _convolve2d(arr[:, :, c], kernel)

    mask_arr = np.array(mask.resize(img.size), dtype=np.float32) / 255.0
    mask_arr = mask_arr[:, :, None]
    mixed = arr * (1.0 - mask_arr) + blurred * mask_arr
    mixed = np.clip(mixed, 0, 255).astype(np.uint8)
    return Image.fromarray(mixed, mode="RGB")


def run_pipeline(img: Image.Image, pipeline: list[dict[str, Any]], base_dir: Path) -> Image.Image:
    out = img
    for step in pipeline:
        op = step.get("op")
        if op == "resize_exact":
            out = op_resize_exact(out, step)
        elif op == "resize_fit":
            out = op_resize_fit(out, step)
        elif op == "crop_center":
            out = op_crop_center(out, step)
        elif op == "rotate":
            out = op_rotate(out, step)
        elif op == "levels":
            out = op_levels(out, step)
        elif op == "denoise_median":
            out = op_denoise_median(out, step)
        elif op == "unsharp":
            out = op_unsharp(out, step)
        elif op == "overlay_image":
            out = op_overlay_image(out, step, base_dir)
        elif op == "draw_text":
            out = op_draw_text(out, step, base_dir)
        elif op == "mask_blur":
            out = op_mask_blur(out, step, base_dir)
        else:
            raise ValueError(f"Unknown op: {op}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic image pipeline")
    parser.add_argument("--input", required=True)
    parser.add_argument("--pipeline", required=True, help="JSON file with pipeline array or object {steps:[...]}")
    parser.add_argument("--output", required=True)
    parser.add_argument("--quality", type=int, default=95)
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    pipe_path = Path(args.pipeline)

    cfg = json.loads(pipe_path.read_text(encoding="utf-8"))
    steps = cfg["steps"] if isinstance(cfg, dict) and "steps" in cfg else cfg
    if not isinstance(steps, list):
        raise ValueError("Pipeline must be a list or {steps:[...]}")

    img = Image.open(in_path).convert("RGB")
    result = run_pipeline(img, steps, pipe_path.parent)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs: dict[str, Any] = {}
    ext = out_path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        save_kwargs["quality"] = int(args.quality)
        save_kwargs["optimize"] = True
    result.save(out_path, **save_kwargs)

    print(json.dumps({
        "ok": True,
        "input": str(in_path),
        "pipeline": str(pipe_path),
        "output": str(out_path),
        "steps": len(steps),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
