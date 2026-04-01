#!/usr/bin/env python3
"""Validate governor attestation file for CI required-check usage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fail(code: str, message: str, rc: int = 1) -> int:
    print(json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False))
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--attestation", required=True)
    ap.add_argument("--require-overall-pass", action="store_true")
    args = ap.parse_args()

    p = Path(args.attestation)
    if not p.exists():
        return fail("ATTESTATION_MISSING", f"Missing: {p}")

    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return fail("ATTESTATION_INVALID", str(exc))

    if d.get("version") != 1:
        return fail("ATTESTATION_VERSION_INVALID", "version must be 1")
    if d.get("taskId") != args.task_id:
        return fail("TASK_ID_MISMATCH", "attestation taskId mismatch")

    gov = d.get("governor") or {}
    if not gov.get("tokenId"):
        return fail("GOVERNOR_TOKEN_MISSING", "governor.tokenId missing")
    if not gov.get("action"):
        return fail("GOVERNOR_ACTION_MISSING", "governor.action missing")

    overall = ((d.get("gates") or {}).get("overall"))
    if args.require_overall_pass and overall != "pass":
        return fail("GATES_NOT_PASS", f"overall={overall!r}")

    print(json.dumps({"ok": True, "taskId": d.get("taskId"), "tokenId": gov.get("tokenId"), "action": gov.get("action"), "overall": overall}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
