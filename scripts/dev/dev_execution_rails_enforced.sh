#!/usr/bin/env bash
set -euo pipefail

# Minimal fail-closed execution rails for software tasks.
# Requires governor token verification before running gates.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOV_SCRIPT="${SCRIPT_DIR}/dev_governor.py"

TASK_ID=""
WORKDIR="$(pwd)"
ISSUE_REF=""
LINT_CMD="${DEV_LINT_CMD:-}"
TYPE_CMD="${DEV_TYPECHECK_CMD:-}"
TEST_CMD="${DEV_TEST_CMD:-}"
SMOKE_CMD="${DEV_SMOKE_CMD:-}"
GOV_TOKEN="${DEV_GOVERNOR_TOKEN:-}"
GOV_ACTION="${DEV_GOVERNOR_ACTION:-implementation_start}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id) TASK_ID="$2"; shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --issue-ref) ISSUE_REF="$2"; shift 2 ;;
    --lint) LINT_CMD="$2"; shift 2 ;;
    --typecheck) TYPE_CMD="$2"; shift 2 ;;
    --test) TEST_CMD="$2"; shift 2 ;;
    --smoke) SMOKE_CMD="$2"; shift 2 ;;
    --governor-token) GOV_TOKEN="$2"; shift 2 ;;
    --governor-action) GOV_ACTION="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { echo "Missing --task-id" >&2; exit 2; }
[[ -n "$GOV_TOKEN" ]] || { echo '{"ok":false,"error":{"code":"GOVERNOR_TOKEN_REQUIRED","message":"missing governor token"}}' >&2; exit 11; }

python3 "$GOV_SCRIPT" verify --task-id "$TASK_ID" --token "$GOV_TOKEN" --action "$GOV_ACTION" >/tmp/dev-governor-verify.json
GOV_TOKEN_ID="$(python3 -c 'import json; print(json.load(open("/tmp/dev-governor-verify.json")).get("tokenId",""))')"
GOV_ACTOR="$(python3 -c 'import json; print(json.load(open("/tmp/dev-governor-verify.json")).get("actor",""))')"
GOV_EXP="$(python3 -c 'import json; print(json.load(open("/tmp/dev-governor-verify.json")).get("exp",""))')"

# Issue gate for GitHub repos (existing issue is acceptable)
if git -C "$WORKDIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ORIGIN_URL="$(git -C "$WORKDIR" remote get-url origin 2>/dev/null || true)"
  if [[ "$ORIGIN_URL" == *"github.com"* ]]; then
    [[ -n "$ISSUE_REF" ]] || { echo '{"ok":false,"error":{"code":"ISSUE_REQUIRED","message":"--issue-ref required for GitHub repo"}}' >&2; exit 12; }
  fi
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${WORKDIR}/.runtime/dev-rails/${TASK_ID}/${TS}"
mkdir -p "$RUN_DIR"

run_gate() {
  local name="$1"; local cmd="$2"; local log="$RUN_DIR/${name}.log"
  if [[ -z "$cmd" ]]; then echo "SKIP: no command configured" > "$log"; echo "skip"; return 0; fi
  set +e
  (cd "$WORKDIR" && bash -lc "$cmd") >"$log" 2>&1
  local rc=$?
  set -e
  [[ $rc -eq 0 ]] && echo "pass" || echo "fail"
}

LINT_STATUS="$(run_gate lint "$LINT_CMD")"
TYPE_STATUS="$(run_gate typecheck "$TYPE_CMD")"
TEST_STATUS="$(run_gate test "$TEST_CMD")"
SMOKE_STATUS="$(run_gate smoke "$SMOKE_CMD")"

OVERALL="pass"
for s in "$LINT_STATUS" "$TYPE_STATUS" "$TEST_STATUS" "$SMOKE_STATUS"; do
  [[ "$s" == "fail" ]] && OVERALL="fail"
done

GIT_COMMIT="$(git -C "$WORKDIR" rev-parse HEAD 2>/dev/null || true)"
GIT_BRANCH="$(git -C "$WORKDIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
ATTESTATION_PATH="$RUN_DIR/attestation.json"

python3 - <<PY > "$ATTESTATION_PATH"
import json
print(json.dumps({
  "version": 1,
  "taskId": "${TASK_ID}",
  "timestampUtc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "workdir": "${WORKDIR}",
  "git": {"branch": "${GIT_BRANCH}", "commit": "${GIT_COMMIT}"},
  "governor": {"action": "${GOV_ACTION}", "tokenId": "${GOV_TOKEN_ID}", "actor": "${GOV_ACTOR}", "exp": "${GOV_EXP}"},
  "issueGate": {"issueRef": "${ISSUE_REF}"},
  "gates": {"lint": "${LINT_STATUS}", "typecheck": "${TYPE_STATUS}", "test": "${TEST_STATUS}", "smoke": "${SMOKE_STATUS}", "overall": "${OVERALL}"}
}, ensure_ascii=False, indent=2))
PY

echo "DEV_EXECUTION_RAILS_ENFORCED_RESULT overall=${OVERALL} run_dir=${RUN_DIR} attestation=${ATTESTATION_PATH}"
[[ "$OVERALL" == "pass" ]]
