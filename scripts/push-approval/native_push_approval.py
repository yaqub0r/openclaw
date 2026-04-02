#!/usr/bin/env python3
"""OpenClaw-native push approval MVP (provider-agnostic).

Implements a local approval challenge lifecycle with one-time token consumption.
Designed as a safe, minimal foundation for later transport/provider adapters (e.g., Duo).

Storage (default):
  .runtime/push-approval/
    approvals/<approvalId>.json
    audit.log.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_iso() -> str:
    return now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.approvals = root / "approvals"
        self.audit = root / "audit.log.jsonl"
        self.approvals.mkdir(parents=True, exist_ok=True)

    def path(self, approval_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in approval_id)
        return self.approvals / f"{safe}.json"

    def write(self, obj: dict[str, Any]) -> None:
        self.path(obj["approvalId"]).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read(self, approval_id: str) -> dict[str, Any]:
        p = self.path(approval_id)
        if not p.exists():
            raise FileNotFoundError(f"approval not found: {approval_id}")
        return json.loads(p.read_text(encoding="utf-8"))

    def all(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for p in sorted(self.approvals.glob("*.json")):
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return items

    def append_audit(self, event: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.audit.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now_iso(), **event}, ensure_ascii=False) + "\n")


def action_hash(action: str, summary: str, scope: str) -> str:
    payload = json.dumps({"action": action, "summary": summary, "scope": scope}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def maybe_expire(rec: dict[str, Any], store: Store) -> dict[str, Any]:
    if rec.get("status") in {"pending", "approved"}:
        exp = parse_iso(rec["expiresAt"])
        if now_utc() > exp:
            rec["status"] = "expired"
            rec["expiredAt"] = now_iso()
            store.write(rec)
            store.append_audit({"type": "expired", "approvalId": rec["approvalId"], "risk": rec.get("risk")})
    return rec


def cmd_request(args: argparse.Namespace) -> int:
    store = Store(Path(args.store_dir))
    approval_id = f"pa-{now_utc().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
    created = now_utc()
    expires = created + dt.timedelta(seconds=max(30, int(args.ttl_seconds)))

    rec = {
        "version": 1,
        "approvalId": approval_id,
        "status": "pending",
        "risk": args.risk,
        "action": args.action,
        "summary": args.summary,
        "scope": args.scope,
        "requester": args.requester,
        "notify": {
            "channel": args.notify_channel,
            "target": args.notify_target,
        },
        "createdAt": created.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "expiresAt": expires.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "actionHash": action_hash(args.action, args.summary, args.scope),
        "decision": None,
        "tokenDigest": None,
        "consumedAt": None,
        "consumedBy": None,
    }
    store.write(rec)
    store.append_audit({
        "type": "created",
        "approvalId": approval_id,
        "risk": args.risk,
        "action": args.action,
        "requester": args.requester,
        "expiresAt": rec["expiresAt"],
    })

    prompt = (
        f"Approval required ({args.risk})\\n"
        f"id: {approval_id}\\n"
        f"action: {args.action}\\n"
        f"summary: {args.summary}\\n"
        f"scope: {args.scope}\\n"
        f"requester: {args.requester}\\n"
        f"expires: {rec['expiresAt']}\\n"
        f"approve: native_push_approval.py decide --id {approval_id} --decision approve --actor <you>\\n"
        f"deny: native_push_approval.py decide --id {approval_id} --decision deny --actor <you>"
    )

    print(json.dumps({"ok": True, "approval": rec, "pushPrompt": prompt}, ensure_ascii=False))
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    store = Store(Path(args.store_dir))
    rec = maybe_expire(store.read(args.id), store)
    if rec.get("status") != "pending":
        print(json.dumps({"ok": False, "error": {"code": "NOT_PENDING", "message": f"approval status is {rec.get('status')}"}}, ensure_ascii=False))
        return 2

    decision = args.decision
    rec["decision"] = {
        "decision": decision,
        "actor": args.actor,
        "at": now_iso(),
        "reason": args.reason or "",
    }

    if decision == "approve":
        token = f"pat-{secrets.token_urlsafe(24)}"
        rec["status"] = "approved"
        rec["approvedAt"] = now_iso()
        rec["tokenDigest"] = token_digest(token)
        store.write(rec)
        store.append_audit({"type": "approved", "approvalId": rec["approvalId"], "actor": args.actor})
        print(json.dumps({"ok": True, "approvalId": rec["approvalId"], "status": rec["status"], "token": token, "actionHash": rec["actionHash"], "expiresAt": rec["expiresAt"]}, ensure_ascii=False))
        return 0

    rec["status"] = "denied"
    rec["deniedAt"] = now_iso()
    store.write(rec)
    store.append_audit({"type": "denied", "approvalId": rec["approvalId"], "actor": args.actor, "reason": args.reason or ""})
    print(json.dumps({"ok": True, "approvalId": rec["approvalId"], "status": rec["status"]}, ensure_ascii=False))
    return 0


def cmd_consume(args: argparse.Namespace) -> int:
    store = Store(Path(args.store_dir))
    rec = maybe_expire(store.read(args.id), store)

    if rec.get("status") != "approved":
        print(json.dumps({"ok": False, "error": {"code": "NOT_APPROVED", "message": f"approval status is {rec.get('status')}"}}, ensure_ascii=False))
        return 3

    if rec.get("consumedAt"):
        print(json.dumps({"ok": False, "error": {"code": "ALREADY_CONSUMED", "message": "token already consumed"}}, ensure_ascii=False))
        return 4

    if rec.get("tokenDigest") != token_digest(args.token):
        store.append_audit({"type": "consume_denied", "approvalId": rec["approvalId"], "actor": args.actor, "reason": "token_mismatch"})
        print(json.dumps({"ok": False, "error": {"code": "TOKEN_INVALID", "message": "token mismatch"}}, ensure_ascii=False))
        return 5

    if args.expected_action_hash and args.expected_action_hash != rec.get("actionHash"):
        store.append_audit({"type": "consume_denied", "approvalId": rec["approvalId"], "actor": args.actor, "reason": "action_hash_mismatch", "expected": args.expected_action_hash, "actual": rec.get("actionHash")})
        print(json.dumps({"ok": False, "error": {"code": "ACTION_HASH_MISMATCH", "message": "approval bound to different action"}}, ensure_ascii=False))
        return 6

    rec["status"] = "consumed"
    rec["consumedAt"] = now_iso()
    rec["consumedBy"] = args.actor
    store.write(rec)
    store.append_audit({"type": "consumed", "approvalId": rec["approvalId"], "actor": args.actor})
    print(json.dumps({"ok": True, "approvalId": rec["approvalId"], "status": rec["status"], "consumedAt": rec["consumedAt"]}, ensure_ascii=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store = Store(Path(args.store_dir))
    rec = maybe_expire(store.read(args.id), store)
    print(json.dumps({"ok": True, "approval": rec}, ensure_ascii=False))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = Store(Path(args.store_dir))
    items = [maybe_expire(x, store) for x in store.all()]
    if args.status:
        items = [x for x in items if x.get("status") == args.status]
    items = sorted(items, key=lambda x: x.get("createdAt", ""), reverse=True)
    if args.limit:
        items = items[: args.limit]
    print(json.dumps({"ok": True, "count": len(items), "items": items}, ensure_ascii=False))
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    store = Store(Path(args.store_dir))
    cutoff = now_utc() - dt.timedelta(days=max(1, args.max_age_days))
    removed = 0
    for p in store.approvals.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            t = parse_iso(rec.get("createdAt", now_iso()))
            if t < cutoff and rec.get("status") in {"denied", "expired", "consumed"}:
                p.unlink(missing_ok=True)
                removed += 1
        except Exception:
            continue
    store.append_audit({"type": "cleanup", "removed": removed, "maxAgeDays": args.max_age_days})
    print(json.dumps({"ok": True, "removed": removed}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="OpenClaw native push approval MVP")
    ap.add_argument("--store-dir", default=os.getenv("OPENCLAW_PUSH_APPROVAL_DIR", ".runtime/push-approval"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    req = sub.add_parser("request")
    req.add_argument("--risk", choices=["low", "medium", "high"], required=True)
    req.add_argument("--action", required=True)
    req.add_argument("--summary", required=True)
    req.add_argument("--scope", default="global")
    req.add_argument("--requester", required=True)
    req.add_argument("--ttl-seconds", type=int, default=900)
    req.add_argument("--notify-channel", default="")
    req.add_argument("--notify-target", default="")
    req.set_defaults(func=cmd_request)

    dec = sub.add_parser("decide")
    dec.add_argument("--id", required=True)
    dec.add_argument("--decision", choices=["approve", "deny"], required=True)
    dec.add_argument("--actor", required=True)
    dec.add_argument("--reason", default="")
    dec.set_defaults(func=cmd_decide)

    con = sub.add_parser("consume")
    con.add_argument("--id", required=True)
    con.add_argument("--token", required=True)
    con.add_argument("--actor", required=True)
    con.add_argument("--expected-action-hash", default="")
    con.set_defaults(func=cmd_consume)

    st = sub.add_parser("status")
    st.add_argument("--id", required=True)
    st.set_defaults(func=cmd_status)

    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=["pending", "approved", "denied", "expired", "consumed"], default="")
    ls.add_argument("--limit", type=int, default=20)
    ls.set_defaults(func=cmd_list)

    cl = sub.add_parser("cleanup")
    cl.add_argument("--max-age-days", type=int, default=14)
    cl.set_defaults(func=cmd_cleanup)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
