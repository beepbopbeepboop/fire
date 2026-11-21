# Gate: suite-self-test is red on master

**Job:** `suite-self-test`. Filed by the full gate at `d0c0a1cc57`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py suite-self-test`), then fix the cause.

## Gate ledger

- **Last known working:** `afd2aca41a` integrate bug-codegen-loop-over-plain-function-ret-2
- **First known not working:** `210191e85b` integrate fix-gate-bootstrap-stage2-cc-r2
- **Seen red in the full gate at:** `d0c0a1cc57` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-d0c0a1cc.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-suite-self-test.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
