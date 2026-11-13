# Gate: rthdrscan is red on master

**Job:** `rthdrscan`. Filed by the full gate at `f2ba176bb9`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py rthdrscan`), then fix the cause.

## Gate ledger

- **Last known working:** none recorded (no earlier full-gate run covered this job)
- **First known not working:** not bisected: no earlier full-gate run had this job green
- **Seen red in the full gate at:** `f2ba176bb9` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-f2ba176b.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-rthdrscan.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
