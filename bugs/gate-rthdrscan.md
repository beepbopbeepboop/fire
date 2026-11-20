# Gate: rthdrscan is red on master

**Job:** `rthdrscan`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py rthdrscan`), then fix the cause. Do not skip or mark the test.

## Done when

`python3 test_runtime_header_scan.py` passes 84/84 (the job itself, wrapped in
`python3 tools/memslot.py --gb 8 --label rthdrscan --`), and the gate-wiring
pin `python3 test_gate_rthdrscan.py` passes with this doc deleted and the
`rthdrscan` registration still enabled. The two runtime declarations that
outran the ladder on 2026-11-20 (`mojo_repr_str_or_none`,
`mojo_textwrap_dedent`) are the drift this round closes; `--fix` writes every
quoted figure from the same scan the ladder asserts.
