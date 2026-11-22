# Gate: gimplegenerators is red on master

**Job:** `gimplegenerators`. Filed by the full gate at `8bc7bb14af`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py gimplegenerators`), then fix the cause.

## Gate ledger

- **Last known working:** `128bc1eb82` integrate fix-proof-fix-gate-type-string-ratchet
- **First known not working:** `c14b59c7ba` integrate bug-codegen-coro-paramflow-cycle-is-not
- **Seen red in the full gate at:** `8bc7bb14af` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8bc7bb14.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-gimplegenerators.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
