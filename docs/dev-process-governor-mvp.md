# Dev Process Governor (MVP)

This MVP moves software-process enforcement from "agent promises" to tooling:

## Included scripts

- `scripts/dev/dev_governor.py`
  - Task state machine
  - Short-lived signed tokens for privileged actions
  - Fail-closed verification
  - Audit log in `.runtime/dev-governor/audit.log.jsonl`

- `scripts/dev/dev_execution_rails_enforced.sh`
  - Requires governor token before running quality gates
  - Optional issue reference gate for GitHub repos
  - Emits deterministic `attestation.json`

- `scripts/dev/dev_governor_required_check.py`
  - Validates an attestation artifact for CI/required-check usage

## State flow

`Intake -> Plan -> Architecture -> ReviewPlan -> ApprovedForImplementation -> Verification -> Done`

## Example

```bash
TASK_ID=DEV-20260401-governor-mvp-enforcement

# move through planning states
python3 scripts/dev/dev_governor.py transition --task-id "$TASK_ID" --to Plan --actor main
python3 scripts/dev/dev_governor.py transition --task-id "$TASK_ID" --to Architecture --actor main
python3 scripts/dev/dev_governor.py transition --task-id "$TASK_ID" --to ReviewPlan --actor main
python3 scripts/dev/dev_governor.py transition --task-id "$TASK_ID" --to ApprovedForImplementation --actor reviewer

# issue implementation token
TOKEN_JSON=$(python3 scripts/dev/dev_governor.py unlock --task-id "$TASK_ID" --action implementation_start)
TOKEN=$(echo "$TOKEN_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

# run enforced rails (fails closed without valid token)
DEV_GOVERNOR_TOKEN="$TOKEN" scripts/dev/dev_execution_rails_enforced.sh \
  --task-id "$TASK_ID" \
  --workdir . \
  --issue-ref owner/repo#123 \
  --lint "npm run lint" \
  --typecheck "npm run typecheck" \
  --test "npm test" \
  --smoke "npm run smoke"
```

## CI integration

A starter workflow exists at:

- `.github/workflows/dev-governor-required-check.yml`

Use it as a required status check after wiring attestation artifact retrieval in your CI path.
