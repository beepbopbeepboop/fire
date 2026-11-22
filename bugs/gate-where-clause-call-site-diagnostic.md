# Gate: where-clause-call-site-diagnostic is red on master

**Job:** `where-clause-call-site-diagnostic`. Filed by the full gate at `0d832b8d39`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py where-clause-call-site-diagnostic`), then fix the cause.

## Gate ledger

- **Last known working:** `8b8e7b6eb7` integrate fix-proof-bug-test-selfhost-struct-layout-map-comp
- **First known not working:** `c879963974` integrate fix-proof-bug-codegen-inprocess-bracketed-generic
- **Seen red in the full gate at:** `0d832b8d39` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-0d832b8d.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-where-clause-call-site-diagnostic.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
