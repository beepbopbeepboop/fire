# Gate: formal-sweep-truth is red on master

**Job:** `formal-sweep-truth`. Filed by the full gate at `06996ee9ce`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py formal-sweep-truth`), then fix the cause.

## Gate ledger

- **Last known working:** `43c0925d6d` Merge branch 'master' into integ
- **First known not working:** `e63e657976` integrate bug-land-mid-formal-x86-endtoend-memory
- **Seen red in the full gate at:** `06996ee9ce` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-06996ee9.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-formal-sweep-truth.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
