# Gate: refusal-taxonomy is red on master

**Job:** `refusal-taxonomy`. Filed by the full gate at `06996ee9ce`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py refusal-taxonomy`), then fix the cause.

## Gate ledger

- **Last known working:** `43c0925d6d` Merge branch 'master' into integ
- **First known not working:** `389bb2ae8d` cpp corpus: programs that reach the ported expression and raise lambda sites
- **Seen red in the full gate at:** `06996ee9ce` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-06996ee9.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-refusal-taxonomy.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
