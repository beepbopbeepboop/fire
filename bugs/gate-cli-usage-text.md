# Gate: cli-usage-text is red on master

**Job:** `cli-usage-text`. Filed by the full gate at `203fd5ea3c`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py cli-usage-text`), then fix the cause.

## Gate ledger

- **Last known working:** `e8421fc41b` integrate fix-merge-fix-merge-fix-merge-bug-formal-formal-proof-covera
- **First known not working:** `f26ebe08f0` Merge branch 'master' of /Users/mrs/net/chatgpt/claude/mojo-reference
- **Seen red in the full gate at:** `203fd5ea3c` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-203fd5ea.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-cli-usage-text.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
