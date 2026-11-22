# Gate: globcompiled is red on master

**Job:** `globcompiled`. Filed by the full gate at `7fcc52e494`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py globcompiled`), then fix the cause.

## Gate ledger

- **Last known working:** `8bc7bb14af` integrate bug-codegen-per-file-from-import-calls-m
- **First known not working:** `7574df21a1` integrate bug-land-codegen-module-alias-call-shado
- **Seen red in the full gate at:** `7fcc52e494` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-7fcc52e4.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-globcompiled.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
