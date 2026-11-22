# Gate: linkmode is red on master

**Job:** `linkmode`. Filed by the full gate at `8bc7bb14af`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py linkmode`), then fix the cause.

## Gate ledger

- **Last known working:** `128bc1eb82` integrate fix-proof-fix-gate-type-string-ratchet
- **First known not working:** `67a2a92718` integrate bug-codegen-module-alias-attr-per-file-r
- **Seen red in the full gate at:** `8bc7bb14af` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8bc7bb14.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-linkmode.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
