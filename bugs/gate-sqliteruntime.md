# Gate: sqliteruntime is red on master

**Job:** `sqliteruntime`. Filed by the full gate at `ce55ca85bf`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py sqliteruntime`), then fix the cause.

## Gate ledger

- **Last known working:** `ae81632041` integrate fix-proof-bug-gate-bootstrap-stage2-dumps-abfullte-2
- **First known not working:** `8558b4ff29` land: fix-gate-bootstrap-stage2-dumps-abfulltest-leaf-mojo cannot land (worker says BLOCKED, not DONE, and no bug doc is left to con); the doc is the work
- **Seen red in the full gate at:** `ce55ca85bf` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-ce55ca85.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-sqliteruntime.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
