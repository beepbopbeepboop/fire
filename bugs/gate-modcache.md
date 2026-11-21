# Gate: modcache is red on master

**Job:** `modcache`. Filed by the full gate at `d0c0a1cc57`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py modcache`), then fix the cause.

## Gate ledger

- **Last known working:** `77c157bb07` integrate bug-land-codegen-true-division-result-tr
- **First known not working:** `d0c0a1cc57` integrate bug-codegen-stdlib-syntax-six-files-red
- **Seen red in the full gate at:** `d0c0a1cc57` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-d0c0a1cc.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-modcache.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
