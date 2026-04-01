#!/usr/bin/env python3
"""Minimal process governor for software tasks.

- Enforces task state machine
- Issues short-lived signed tokens for privileged actions
- Verifies tokens fail-closed
- Appends audit events to .runtime/dev-governor/audit.log.jsonl
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

RUNTIME_DIR = Path(".runtime/dev-governor")
TASKS_DIR = RUNTIME_DIR / "tasks"
AUDIT_LOG = RUNTIME_DIR / "audit.log.jsonl"
SECRET_FILE = RUNTIME_DIR / "secret.key"

STATES = [
    "Intake",
    "Plan",
    "Architecture",
    "ReviewPlan",
    "ApprovedForImplementation",
    "Verification",
    "Done",
]
ALLOWED_NEXT = {
    "Intake": {"Plan"},
    "Plan": {"Architecture"},
    "Architecture": {"ReviewPlan"},
    "ReviewPlan": {"ApprovedForImplementation", "Plan"},
    "ApprovedForImplementation": {"Verification", "Plan"},
    "Verification": {"Done", "ApprovedForImplementation", "Plan"},
    "Done": set(),
}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)


def load_secret() -> bytes:
    env = os.getenv("DEV_GOVERNOR_SECRET", "")
    if env:
        return env.encode("utf-8")
    ensure_dirs()
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    secret = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(secret)
    os.chmod(SECRET_FILE, 0o600)
    return secret


def safe_task_file(task_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)
    return TASKS_DIR / f"{safe}.json"


def read_task(task_id: str) -> dict:
    ensure_dirs()
    f = safe_task_file(task_id)
    if not f.exists():
        t = now_utc()
        return {
            "taskId": task_id,
            "state": "Intake",
            "createdAt": t,
            "updatedAt": t,
            "history": [{"at": t, "state": "Intake", "actor": "system", "reason": "auto-init"}],
        }
    return json.loads(f.read_text(encoding="utf-8"))


def write_task(task: dict) -> None:
    ensure_dirs()
    safe_task_file(task["taskId"]).write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit(event: dict) -> None:
    ensure_dirs()
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now_utc(), **event}, ensure_ascii=False) + "\n")


def sign(payload: dict, secret: bytes) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret, body, hashlib.sha256).digest()
    b = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    s = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{b}.{s}"


def parse_token(token: str) -> tuple[dict, bytes]:
    b, s = token.split(".", 1)
    body = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))
    sig = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    return json.loads(body.decode("utf-8")), sig


def required_state_for_action(action: str) -> str:
    return {
        "implementation_start": "ApprovedForImplementation",
        "done_transition": "Verification",
        "merge_eligible": "Verification",
    }.get(action, "ApprovedForImplementation")


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, "task": read_task(args.task_id)}, ensure_ascii=False))
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    task = read_task(args.task_id)
    cur = task.get("state", "Intake")
    dst = args.to
    if dst not in STATES:
        print(json.dumps({"ok": False, "error": {"code": "INVALID_STATE", "message": dst}}, ensure_ascii=False))
        return 2
    if dst != cur and dst not in ALLOWED_NEXT.get(cur, set()):
        audit({"type": "transition_denied", "taskId": args.task_id, "from": cur, "to": dst, "actor": args.actor})
        print(json.dumps({"ok": False, "error": {"code": "INVALID_TRANSITION", "message": f"{cur}->{dst} not allowed"}}, ensure_ascii=False))
        return 3
    task["state"] = dst
    task["updatedAt"] = now_utc()
    task.setdefault("history", []).append({"at": now_utc(), "state": dst, "actor": args.actor, "reason": args.reason or ""})
    write_task(task)
    audit({"type": "transition", "taskId": args.task_id, "from": cur, "to": dst, "actor": args.actor, "reason": args.reason or ""})
    print(json.dumps({"ok": True, "task": task}, ensure_ascii=False))
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    task = read_task(args.task_id)
    req = required_state_for_action(args.action)
    if task.get("state") != req:
        audit({"type": "unlock_denied", "taskId": args.task_id, "state": task.get("state"), "requiredState": req, "action": args.action})
        print(json.dumps({"ok": False, "error": {"code": "STATE_NOT_ALLOWED", "message": f"state must be {req}", "state": task.get("state")}}, ensure_ascii=False))
        return 4
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    exp = now + int(args.ttl_seconds)
    token_id = secrets.token_hex(8)
    payload = {
        "v": 1,
        "tokenId": token_id,
        "taskId": args.task_id,
        "action": args.action,
        "actor": args.actor,
        "iat": now,
        "exp": exp,
    }
    token = sign(payload, load_secret())
    audit({"type": "unlock_issued", "taskId": args.task_id, "tokenId": token_id, "action": args.action, "actor": args.actor, "exp": exp})
    print(json.dumps({"ok": True, "taskId": args.task_id, "token": token, "tokenId": token_id, "exp": exp}, ensure_ascii=False))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        payload, sig = parse_token(args.token)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": {"code": "TOKEN_INVALID", "message": str(exc)}}, ensure_ascii=False))
        return 5

    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    exp_sig = hmac.new(load_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, exp_sig):
        print(json.dumps({"ok": False, "error": {"code": "TOKEN_SIGNATURE_INVALID", "message": "signature mismatch"}}, ensure_ascii=False))
        return 6

    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    if int(payload.get("exp", 0)) < now:
        print(json.dumps({"ok": False, "error": {"code": "TOKEN_EXPIRED", "message": "expired"}}, ensure_ascii=False))
        return 7

    if payload.get("taskId") != args.task_id:
        print(json.dumps({"ok": False, "error": {"code": "TOKEN_TASK_MISMATCH", "message": "task mismatch"}}, ensure_ascii=False))
        return 8
    if payload.get("action") != args.action:
        print(json.dumps({"ok": False, "error": {"code": "TOKEN_ACTION_MISMATCH", "message": "action mismatch"}}, ensure_ascii=False))
        return 9

    task = read_task(args.task_id)
    req = required_state_for_action(args.action)
    if task.get("state") != req:
        print(json.dumps({"ok": False, "error": {"code": "STATE_NOT_ALLOWED", "message": f"state must be {req}", "state": task.get("state")}}, ensure_ascii=False))
        return 10

    print(json.dumps({"ok": True, "taskId": args.task_id, "tokenId": payload.get("tokenId"), "action": payload.get("action"), "actor": payload.get("actor"), "exp": payload.get("exp")}, ensure_ascii=False))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dev process governor")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status")
    s.add_argument("--task-id", required=True)
    s.set_defaults(func=cmd_status)

    t = sub.add_parser("transition")
    t.add_argument("--task-id", required=True)
    t.add_argument("--to", required=True, choices=STATES)
    t.add_argument("--actor", default="unknown")
    t.add_argument("--reason", default="")
    t.set_defaults(func=cmd_transition)

    u = sub.add_parser("unlock")
    u.add_argument("--task-id", required=True)
    u.add_argument("--actor", default="governor")
    u.add_argument("--action", default="implementation_start", choices=["implementation_start", "done_transition", "merge_eligible"])
    u.add_argument("--ttl-seconds", type=int, default=900)
    u.set_defaults(func=cmd_unlock)

    v = sub.add_parser("verify")
    v.add_argument("--task-id", required=True)
    v.add_argument("--token", required=True)
    v.add_argument("--action", required=True, choices=["implementation_start", "done_transition", "merge_eligible"])
    v.set_defaults(func=cmd_verify)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    raise SystemExit(args.func(args))
