# Gate: gimple-lint is red on master

**Job:** `gimple-lint`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py gimple-lint`), then fix the cause. Do not skip or mark the test.

## Gate ledger

- **Last known working:** `d3ec70ee73` integrate bug-formal-arm64-instruction-coverage-pa
- **First known not working:** `a0dfc3b0fd` Fix compiled file-object iteration, cpp string equality, generator defaults
- **Seen red in the full gate at:** `bec49b8101` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-bec49b81.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-gimple-lint.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
