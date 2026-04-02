---
name: push-approval
description: "OpenClaw-native push approval (MFA-style human confirmation) for high-risk actions. Creates approval challenges, sends push prompts via existing channels, and enforces one-time token consumption before execution."
---

# Push Approval (OpenClaw-native MVP)

Use this skill when you need human-in-the-loop approval before high-risk actions.

## What this MVP provides

- Challenge lifecycle: `request -> approve|deny|expire -> consume`
- One-time token consumption (replay resistant)
- TTL-based expiry (fail closed)
- Audit trail in JSONL
- Provider-agnostic core (Duo/Okta/etc can be added later)

## Script

- `scripts/push-approval/native_push_approval.py`

State dir defaults to:
- `.runtime/push-approval`

Override with:
- `OPENCLAW_PUSH_APPROVAL_DIR=/path`

## Usage

### 1) Request approval

```bash
python3 scripts/push-approval/native_push_approval.py request \
  --risk high \
  --action config.patch \
  --summary "Enable security policy for group memory writes" \
  --scope "group:120363425197476195@g.us" \
  --requester "agent:main" \
  --ttl-seconds 600 \
  --notify-channel whatsapp \
  --notify-target +13479278207
```

The output includes:
- `approvalId`
- `actionHash`
- `pushPrompt` text (send this via `message` tool)

### 2) Send push prompt

Use `message` tool (or your normal channel runtime) to send `pushPrompt` to approver.

### 3) Approve or deny

```bash
python3 scripts/push-approval/native_push_approval.py decide \
  --id <approvalId> \
  --decision approve \
  --actor owner:+13479278207
```

(Use `--decision deny` to reject.)

Approve output includes a one-time `token`.

### 4) Enforce before action (consume token)

```bash
python3 scripts/push-approval/native_push_approval.py consume \
  --id <approvalId> \
  --token <token> \
  --actor agent:main \
  --expected-action-hash <actionHash>
```

If consume fails, do **not** run the guarded action.

## Risk guidance

- `low`: no push required by default
- `medium`: push optional / policy-driven
- `high`: push required, fail closed

## Security notes

- Approval tokens are one-time use
- Expired or denied approvals cannot be consumed
- Approval is action-bound via `actionHash`
- Keep approval prompts concise and explicit

## Future add-ons

- Duo push provider backend
- IdP/webhook backends (Okta/Auth0/etc)
- richer operator UI for pending approvals
