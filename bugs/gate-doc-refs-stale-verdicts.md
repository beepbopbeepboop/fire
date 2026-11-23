# Gate: doc-refs-stale-verdicts is red on master

**Job:** `doc-refs-stale-verdicts`. Filed by the full gate at `2eea7fd75d`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py doc-refs-stale-verdicts`), then fix the cause.

## Gate ledger

- **Last known working:** `8c358432b4` integrate fix-gate-doc-refs
- **First known not working:** `b2ca311db4` bugs: CODEGEN_selfhost_stage2_attributeerror_comptimevar_node
- **Seen red in the full gate at:** `2eea7fd75d` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-2eea7fd7.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-doc-refs-stale-verdicts.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
