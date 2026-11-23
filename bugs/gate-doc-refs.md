# Gate: doc-refs is red on master

**Job:** `doc-refs`. Filed by the full gate at `c137e69c7c`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py doc-refs`), then fix the cause.

## Gate ledger

- **Last known working:** `ecbd89e570` integrate fix-proof-bug-gate-codegen-container-param-unknown
- **First known not working:** `c137e69c7c` integrate fix-orch-bug-comptime-declined-fold-condition-rep
- **Seen red in the full gate at:** `c137e69c7c` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-c137e69c.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-doc-refs.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
