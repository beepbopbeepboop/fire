# Gate: bootstrap-stage2-cc is red on master

**Job:** `bootstrap-stage2-cc`. Filed by the full gate at `d0c0a1cc57`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py bootstrap-stage2-cc`), then fix the cause.

## Gate ledger

- **Last known working:** `2557e196fd` integrate bug-land-formal-dylib-export-proof-holes
- **First known not working:** `ab2c16d63f` land: bug-land-formal-x86-64-idx-forms-fuzz-an cannot land (conflicts with master); the doc is the work
- **Seen red in the full gate at:** `d0c0a1cc57` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-d0c0a1cc.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-bootstrap-stage2-cc.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
