# Gate: formal-read-before-store is red on master

**Job:** `formal-read-before-store`. Filed by the full gate at `624ab4e38a`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py formal-read-before-store`), then fix the cause.

## Gate ledger

- **Last known working:** `4e1b239edf` integrate fix-proof-bug-suite-hard-readme-index-stale
- **First known not working:** `624ab4e38a` integrate fix-replan-codegen-selfhost-link-two-unqualified-ca
- **Seen red in the full gate at:** `624ab4e38a` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-624ab4e3.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-formal-read-before-store.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
