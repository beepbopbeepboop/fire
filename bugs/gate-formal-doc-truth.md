# Gate: formal-doc-truth is red on master

**Job:** `formal-doc-truth`. Filed by the full gate at `4eba365d99`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py formal-doc-truth`), then fix the cause.

## Gate ledger

- **Last known working:** none recorded (no earlier full-gate run covered this job)
- **First known not working:** not bisected: no earlier full-gate run had this job green
- **Seen red in the full gate at:** `4eba365d99` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-4eba365d.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-formal-doc-truth.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
