# Gate: metalgpu is red on master

**Job:** `metalgpu`. Filed by the full gate at `b3ca726df3`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py metalgpu`), then fix the cause.

## Gate ledger

- **Last known working:** `96a3a333af` integrate fix-merge-bug-formal-svc-exit-handling-incomplete-3
- **First known not working:** `a7e7fc9cf5` Merge worktree-agent-af3a9438a1a01fb2c (DIAGNOSTICS_formatting_modular)
- **Seen red in the full gate at:** `b3ca726df3` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-b3ca726d.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-metalgpu.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
