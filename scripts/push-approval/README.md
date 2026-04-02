# native_push_approval.py

OpenClaw-native push approval MVP script.

## Quick smoke test

```bash
python3 scripts/push-approval/native_push_approval.py request \
  --risk high --action test --summary "smoke" --requester local
```

Then approve and consume:

```bash
python3 scripts/push-approval/native_push_approval.py decide --id <id> --decision approve --actor owner
python3 scripts/push-approval/native_push_approval.py consume --id <id> --token <token> --actor agent
```
