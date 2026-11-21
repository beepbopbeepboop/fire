# Gate: stdlib-syntax-quick-bench-math is red on master

**Job:** `stdlib-syntax-quick-bench-math`. Filed by the full gate at `77c157bb07`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py stdlib-syntax-quick-bench-math`), then fix the cause.

## Gate ledger

- **Last known working:** `a679f97770` integrate bug-gate-suite-self-test-2
- **First known not working:** `b6600228ca` Merge remote-tracking branch 'origin/master'
- **Seen red in the full gate at:** `77c157bb07` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-77c157bb.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-stdlib-syntax-quick-bench-math.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
