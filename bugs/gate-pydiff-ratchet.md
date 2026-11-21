# Gate: pydiff-ratchet is red on master

**Job:** `pydiff-ratchet`. Filed by the full gate at `77c157bb07`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py pydiff-ratchet`), then fix the cause.

## Gate ledger

- **Last known working:** `ee09473665` integrate bug-codegen-sort-wrong-order-for-tuples
- **First known not working:** `77c157bb07` integrate bug-land-codegen-true-division-result-tr
- **Seen red in the full gate at:** `77c157bb07` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-77c157bb.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-pydiff-ratchet.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
