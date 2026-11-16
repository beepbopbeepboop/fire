# Gate: module-globals-compiled is red on master

**Job:** `module-globals-compiled`. Filed by the full gate at `cbdd0e7213`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py module-globals-compiled`), then fix the cause.

## Gate ledger

- **Last known working:** `d3ec70ee73` integrate bug-formal-arm64-instruction-coverage-pa
- **First known not working:** `c5d067739a` Merge remote-tracking branch 'fire/master'
- **Seen red in the full gate at:** `cbdd0e7213` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-cbdd0e72.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-module-globals-compiled.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
