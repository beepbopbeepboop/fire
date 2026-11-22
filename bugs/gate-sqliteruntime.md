# Gate: sqliteruntime is red on master

**Job:** `sqliteruntime`. Filed by the full gate at `ce55ca85bf`.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

Reproduce on master (`python3 tools/suite.py sqliteruntime`), then fix the cause.

## Done when

`python3 tools/suite.py sqliteruntime` passes (exit 0; no `TIMEOUT`, no
`RESOURCE`) inside the job's cap, and the direct command it runs prints
`70 passed, 0 failed, 70 checks`:

    python3 tools/memslot.py --gb 8 --label sqliteruntime -- python3 test_sqlite3_runtime.py

## Gate ledger

- **Last known working:** `ae81632041` integrate fix-proof-bug-gate-bootstrap-stage2-dumps-abfullte-2
- **First known not working:** `8558b4ff29` land: fix-gate-bootstrap-stage2-dumps-abfulltest-leaf-mojo cannot land (worker says BLOCKED, not DONE, and no bug doc is left to con); the doc is the work
- **Seen red in the full gate at:** `ce55ca85bf` (log `/Users/mrs/net/chatgpt/claude/work-verify/verify-ce55ca85.log`)
- **Skipped:** the job's registration in `tools/suite.py` carries `disabled='bugs/gate-sqliteruntime.md'`, so the gate spends no time on it. To fix it: remove the `disabled=` argument, make the job pass, and delete this doc in the same commit.

## Status — root cause found, 2026-11-21

The job was not failing on the optional-unit link mechanism it exists to
exercise. The gate log's red is a 600 s `TIMEOUT`, and the timeout was one
case: `test_probe_ignores_mentions` compiled the compiler's WHOLE import
closure (`from build_config import find_gcc` with `do_imports=True`) to pin
that the optional-unit probe does not mistake signature names appearing in the
generated C as string-literal data for calls.

Measured on this tree (`/usr/bin/time -l` under `tools/memslot.py --gb 8`),
that one call:

    build_config closure: 681.4 s, 147,776,581 bytes of C
    peak footprint 8.06 GB, max RSS 8.20 GB

That is a whole-closure compile inside a QUICK suite job — a self-host step's
cost — and it is what put the job past its 600 s cap. It also explains the
5.58 GB peak the job's `module` (24 GB) class and `memwhy` debt were recorded
from: the growth 1.3 -> 2.3 -> 5.58 GB across recent commits was this one
compile growing with the compiler's closure, not a drift in the builds the
job exists to test.

**Fix.** The case now compiles `mojo/middle/rt_sigs.py` — the compiler's
runtime signature table, i.e. the module that actually carries every optional
unit's names as literal data — on its own (`do_imports=False`): 0.5 s, 1 MB,
0.3 GB. It also asserts the pin's premise instead of assuming it (every
non-metal unit's every declared symbol is present in the generated C, so a
fixture that stopped carrying them fails rather than passing vacuously) and
caps the fixture at 4 MB so the whole-closure form cannot creep back in as
"still passing, just slow". The call-shaped-fragment-inside-a-literal shape
that the closure form was there for has its own direct case in
`test_probe_distinguishes_calls_from_mentions`.

Registration: `disabled=` removed, `mem='tiny'` (0.7 GB measured tree peak,
cold CAS cache), `timeout=1200` (measured 119 s warm / 368 s cold, and this is
the entry that has stretched on machine load alone before).

**Verified.** `python3 tools/suite.py sqliteruntime`: 2 passed (the job and its
`preflight` dep), 106 s wall, peak 0.4 GB. Direct:
`70 passed, 0 failed, 70 checks`, 119 s warm / 368 s cold.
