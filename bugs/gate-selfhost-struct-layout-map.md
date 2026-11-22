# Gate: selfhost-struct-layout-map is red on master

**Job:** `selfhost-struct-layout-map`. Filed by the full gate at `8b8e7b6eb7`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py selfhost-struct-layout-map`), then fix the cause.

## Gate ledger

- **Last known working:** none recorded (no earlier full-gate run covered this job)
- **First known not working:** not bisected: the run at dd5da5eb5d did not report this job green (it did not run there), so there is no last_good to bisect from
- **Seen red in the full gate at:** `8b8e7b6eb7` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8b8e7b6e.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-selfhost-struct-layout-map.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
