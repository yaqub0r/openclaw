# Push Approval (OpenClaw-native MVP)

This document describes the native push-approval MVP introduced for task `DEV-20260402-push-approval-mfa-skill`.

## Summary

The MVP adds a provider-agnostic approval core that supports:

1. Challenge creation (`request`)
2. Human decision (`approve` / `deny`)
3. One-time token consumption (`consume`)
4. TTL-based expiry and fail-closed behavior
5. Append-only audit events

Implemented script:

- `scripts/push-approval/native_push_approval.py`

## Lifecycle

```text
request -> pending
pending -> approved | denied | expired
approved -> consumed | expired
```

## Why this shape

- Keeps core approval semantics in OpenClaw-native control plane
- Avoids hard dependency on external MFA providers in v1
- Enables later provider adapters (e.g., Duo push) without redesign

## Integration pattern

Use this as a preflight guard for risky actions:

1) create approval challenge
2) notify approver via channel
3) wait for decision
4) require successful consume before executing action

### Example flow (high risk)

```bash
REQ=$(python3 scripts/push-approval/native_push_approval.py request \
  --risk high \
  --action exec \
  --summary "Run migration in production" \
  --scope "prod" \
  --requester "agent:main")

# send REQ.pushPrompt to approver via channel
# approver runs decide --decision approve
# action runner receives token and runs consume
```

## Auditing

Audit file:

- `.runtime/push-approval/audit.log.jsonl`

Event types include:

- `created`, `approved`, `denied`, `expired`, `consumed`, `consume_denied`, `cleanup`

## Hardening backlog

- provider backend adapter interface
- rate limits / anti-spam on challenge creation
- richer authz policy for approvers
- centralized API and UI surface
