# Gate: module-globals-compiled is red on master

**Job:** `module-globals-compiled`. Filed by the full gate at `f1fb3ca151`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py module-globals-compiled`), then fix the cause.

## Gate ledger

- **Last known working:** `7fcc52e494` integrate fix-proof-fix-gate-function-body-alias-class-import
- **First known not working:** `ea2938d8a5` integrate fix-proof-fix-gate-refusal-taxonomy
- **Seen red in the full gate at:** `f1fb3ca151` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-f1fb3ca1.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-module-globals-compiled.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
