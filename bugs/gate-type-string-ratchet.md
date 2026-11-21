# Gate: type-string-ratchet is red on master

**Job:** `type-string-ratchet`. Filed by the full gate at `8a4b0af29f`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py type-string-ratchet`), then fix the cause.

## Gate ledger

- **Last known working:** `a679f97770` integrate bug-gate-suite-self-test-2
- **First known not working:** `ee09473665` integrate bug-codegen-sort-wrong-order-for-tuples
- **Seen red in the full gate at:** `8a4b0af29f` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-8a4b0af2.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-type-string-ratchet.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.
