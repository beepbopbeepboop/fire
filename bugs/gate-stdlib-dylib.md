# Gate: stdlib-dylib is red on master

**Job:** `stdlib-dylib`. Filed by the full gate at `899f0d5e7b`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py stdlib-dylib`), then fix the cause.

## Gate ledger

- **Last known working:** `e8421fc41b` integrate fix-merge-fix-merge-fix-merge-bug-formal-formal-proof-covera
- **First known not working:** `131b61adee` diag: runtime assert prints 'Assert Error: <msg>'; except <name>: is a catch-all binding
- **Seen red in the full gate at:** `899f0d5e7b` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-899f0d5e.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-stdlib-dylib.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
