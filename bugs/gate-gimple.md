# Gate: gimple is red on master

**Job:** `gimple`. Filed by the full gate at `96a3a333af`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py gimple`), then fix the cause.

## Gate ledger

- **Last known working:** `624ab4e38a` integrate fix-replan-codegen-selfhost-link-two-unqualified-ca
- **First known not working:** `3b8492aec9` Merge remote-tracking branch 'origin/master'
- **Seen red in the full gate at:** `96a3a333af` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-96a3a333.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-gimple.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
