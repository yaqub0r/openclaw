# Image Power Stack

Pipeline components:
- `deterministic_pipeline.py` — repeatable pixel operations (resize/crop/levels/denoise/unsharp/overlay/mask blur).
- `generative_bridge.py` — optional generative pass (`automatic1111` or `none`).
- `qa_gate.py` — hard quality checks (resolution/bytes/blur/psnr).
- `run_stack.py` — orchestrates deterministic -> generative -> QA.

## Quick start

```bash
python3 tools/image_power_stack/run_stack.py \
  --input ./in.png \
  --config tools/image_power_stack/presets/config-template.json \
  --output ./out.png
```

To use local Stable Diffusion WebUI (Automatic1111):
- Start API with `--api`.
- Set `"provider": "automatic1111"` in config.
- Optional: set `"api_url": "http://127.0.0.1:7860"`.

If QA fails, the command exits non-zero.
