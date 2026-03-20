#!/usr/bin/env python3
"""Image Power Stack orchestrator.

Config JSON example:
{
  "deterministic_pipeline": "presets/ecommerce-cleanup.json",
  "generative": {
    "provider": "none",
    "prompt": "",
    "negative_prompt": "",
    "steps": 28,
    "cfg_scale": 7,
    "denoise": 0.45
  },
  "qa": {
    "min_width": 1080,
    "min_height": 1080,
    "min_blur_score": 8.0,
    "max_bytes": 6000000
  }
}
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DET_SCRIPT = ROOT / "deterministic_pipeline.py"
GEN_SCRIPT = ROOT / "generative_bridge.py"
QA_SCRIPT = ROOT / "qa_gate.py"


def run(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    payload: dict[str, Any] = {
        "code": proc.returncode,
        "stdout": out,
        "stderr": err,
    }
    if out:
        try:
            payload["json"] = json.loads(out)
        except Exception:
            pass
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic + generative + QA image stack")
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mask")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
      cfg_path = (workdir / cfg_path).resolve()

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (workdir / input_path).resolve()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (workdir / output_path).resolve()

    tmp_det = output_path.with_suffix(".det.tmp.png")

    det_cfg = cfg.get("deterministic_pipeline")
    if det_cfg:
        det_path = Path(det_cfg)
        if not det_path.is_absolute():
            # First try relative to config file; then fallback to stack root.
            candidate = (cfg_path.parent / det_path).resolve()
            det_path = candidate if candidate.exists() else (ROOT / det_path).resolve()

        det_cmd = [
            "python3",
            str(DET_SCRIPT),
            "--input",
            str(input_path),
            "--pipeline",
            str(det_path),
            "--output",
            str(tmp_det),
        ]
        det_res = run(det_cmd)
        if det_res["code"] != 0:
            print(json.dumps({"ok": False, "stage": "deterministic", "result": det_res}, indent=2))
            return 1
        stage_input = tmp_det
    else:
        stage_input = input_path

    gen = cfg.get("generative", {})
    gen_cmd = [
        "python3",
        str(GEN_SCRIPT),
        "--provider",
        str(gen.get("provider", "none")),
        "--input",
        str(stage_input),
        "--output",
        str(output_path),
        "--prompt",
        str(gen.get("prompt", "")),
        "--negative-prompt",
        str(gen.get("negative_prompt", "")),
        "--steps",
        str(int(gen.get("steps", 28))),
        "--cfg-scale",
        str(float(gen.get("cfg_scale", 7.0))),
        "--denoise",
        str(float(gen.get("denoise", 0.45))),
    ]

    if args.mask:
        mask_path = Path(args.mask)
        if not mask_path.is_absolute():
            mask_path = (workdir / mask_path).resolve()
        gen_cmd.extend(["--mask", str(mask_path)])
    if gen.get("api_url"):
        gen_cmd.extend(["--api-url", str(gen["api_url"])])
    if gen.get("sampler"):
        gen_cmd.extend(["--sampler", str(gen["sampler"])])
    if gen.get("width"):
        gen_cmd.extend(["--width", str(int(gen["width"]))])
    if gen.get("height"):
        gen_cmd.extend(["--height", str(int(gen["height"]))])

    gen_res = run(gen_cmd)
    if gen_res["code"] != 0:
        print(json.dumps({"ok": False, "stage": "generative", "result": gen_res}, indent=2))
        return 1

    qa = cfg.get("qa", {})
    qa_cmd = [
        "python3",
        str(QA_SCRIPT),
        "--output",
        str(output_path),
    ]
    if qa.get("min_width"):
        qa_cmd += ["--min-width", str(int(qa["min_width"]))]
    if qa.get("min_height"):
        qa_cmd += ["--min-height", str(int(qa["min_height"]))]
    if qa.get("max_bytes"):
        qa_cmd += ["--max-bytes", str(int(qa["max_bytes"]))]
    if qa.get("min_bytes"):
        qa_cmd += ["--min-bytes", str(int(qa["min_bytes"]))]
    if qa.get("min_blur_score") is not None:
        qa_cmd += ["--min-blur-score", str(float(qa["min_blur_score"]))]

    if qa.get("compare_to_source", True):
        qa_cmd += ["--source", str(input_path)]
        if qa.get("min_psnr") is not None:
            qa_cmd += ["--min-psnr", str(float(qa["min_psnr"]))]
        if qa.get("max_psnr") is not None:
            qa_cmd += ["--max-psnr", str(float(qa["max_psnr"]))]

    qa_res = run(qa_cmd)
    result = {
        "ok": qa_res["code"] == 0,
        "input": str(input_path),
        "output": str(output_path),
        "deterministic": det_res if det_cfg else {"code": 0, "skipped": True},
        "generative": gen_res,
        "qa": qa_res,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
