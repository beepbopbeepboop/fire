# Gate: codegen-container-param-unknown-arg is red on master

**Job:** `codegen-container-param-unknown-arg`. Filed by the full gate at `7ae7ff25c2`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py codegen-container-param-unknown-arg`), then fix the cause.

## Gate ledger

- **Last known working:** `7cc63afc41` integrate fix-proof-bug-land-gate-linkmode
- **First known not working:** `7ae7ff25c2` integrate bug-codegen-separate-compile-definer-sig
- **Seen red in the full gate at:** `7ae7ff25c2` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-7ae7ff25.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-codegen-container-param-unknown-arg.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
