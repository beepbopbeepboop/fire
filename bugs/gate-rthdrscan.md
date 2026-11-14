# Gate: rthdrscan is red on master

**Job:** `rthdrscan`. Filed by the full gate at `e13c0d2506`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py rthdrscan`), then fix the cause.

## Gate ledger

- **Last known working:** none recorded (no earlier full-gate run covered this job)
- **First known not working:** not bisected: no earlier full-gate run had this job green
- **Seen red in the full gate at:** `e13c0d2506` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-e13c0d25.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-rthdrscan.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.

## Done when

    python3 tools/memslot.py --gb 8 --label rthdrscan -- python3 tools/suite.py rthdrscan

reports `1 passed, 0 failed`, and the pin that the job is not switched off
again passes:

    python3 tools/memslot.py --gb 8 --label pin -- python3 test_gate_rthdrscan.py

(`reg-gate-rthdrscan`). The census evidence is `test_runtime_header_scan.py`'s
own `test_every_declaration_is_seen` and
`test_the_quoted_census_is_the_live_census`; both are inside the job above.

## Status

- **2026-11-14 (bug-gate-rthdrscan):** the drift is two `issubclass`
  declarations (`mojo_is_classword`, `mojo_issubclass_rtclass`) that landed in
  `be6de3790` after the ledger's 832 rung, without a rung of their own, so the
  live scan read 834 against the pinned 832 and every quoted census figure was
  two behind. `test_runtime_header_scan.py --fix` wrote the rung
  (832 -> 834) and every prose copy from one scan (total 942 -> 944, word
  431 -> 433, box 511 unchanged, `fire_runtime.h` 832 -> 834, §2.2 share
  45.8% -> 45.9%). The `disabled=` marker is removed, so the job runs in
  `check` and `gate` again, and `test_suite.py`'s two `expected_disabled`
  censuses no longer name it.
