# Gate: gimplerunner is red on master

**Job:** `gimplerunner`. Filed by the full gate at `8bc7bb14af`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py gimplerunner`), then fix the cause.

## Gate ledger

- **Last known working:** `0d832b8d39` integrate bug-land-gate-bootstrap-stage2-cc-3
- **First known not working:** `2837233b69` integrate bug-gir-stage5b-box-carry-needs-the-bind
- **Seen red in the full gate at:** `8bc7bb14af` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8bc7bb14.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-gimplerunner.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
