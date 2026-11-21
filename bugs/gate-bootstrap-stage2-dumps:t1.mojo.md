# Gate: bootstrap-stage2-dumps:t1.mojo is red on master

**Job:** `bootstrap-stage2-dumps:t1.mojo`. Filed by the full gate at `c0182fd365`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py bootstrap-stage2-dumps:t1.mojo`), then fix the cause.

## Gate ledger

- **Last known working:** `d0c0a1cc57` integrate bug-codegen-stdlib-syntax-six-files-red
- **First known not working:** `0b0316114e` integrate fix-gate-formal-host-import-shapes
- **Seen red in the full gate at:** `8a4b0af29f` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8a4b0af2.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-bootstrap-stage2-dumps:t1.mojo.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
