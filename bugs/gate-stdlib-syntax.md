# Gate: stdlib-syntax is red on master

**Job:** `stdlib-syntax`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py stdlib-syntax`), then fix the cause. Do not skip or mark the test.

## Gate ledger

- **Last known working:** `46ef25daa9` integrate fix-replan-compile-fail-tools-c-analyzer-c-analyzer
- **First known not working:** `b0910af726` codegen: call the real `_eval_const_int`, not a name GimpleGen never had
- **Seen red in the full gate at:** `77c157bb07` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-77c157bb.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-stdlib-syntax.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
