# Gate: rthdrscan is red on master

**Job:** `rthdrscan`. Created when branch `master` (task `master`) turned the gate red.
**Two states:** this doc exists = the job is red and this is the work. Delete it when the job is green on master.

It is red on `master`: reproduce it there (`python3 tools/suite.py rthdrscan`), then fix the cause. Do not skip or mark the test.

## Gate ledger

- **Last known working:** `a8e4f64bc` (the merge resolution read the live 837
  and every quoted figure matched it; `rthdrscan` was green there).
- **First known not working:** not bisected per commit; the drift is exactly the
  three commits listed under Status, the last of which is `6c661dd89`.
- **Seen red in the gate at:** `4bd601838` (this branch's base), live scan 856
  against the pinned 837.
- **Skipped:** no — the registration in `tools/suite.py` carries no
  `disabled=`; the job runs and fails.

## Done when

    python3 tools/memslot.py --gb 8 --label rthdrscan -- python3 tools/suite.py rthdrscan

reports `1 passed, 0 failed`, and the pin that the job is not switched off and
the doc stays deleted passes:

    python3 tools/memslot.py --gb 8 --label pin -- python3 test_gate_rthdrscan.py

(`reg-gate-rthdrscan`). The census evidence is `test_runtime_header_scan.py`'s
own `test_every_declaration_is_seen` (the ladder rung) and
`test_the_quoted_census_is_the_live_census` (every prose copy); both are inside
the job above.

## Status

- **2026-11-18 (bug-gate-rthdrscan):** the drift is nineteen runtime
  declarations that landed after the ledger's 837 figure without a rung, in
  three commits: `4ded7f5f3` (four float8 entries: `mojo_box_from_f8`,
  `mojo_f8_round`, `mojo_f8_spelling`, `mojo_is_f8_box`), `0c7b94fd4` (eight
  bit-intrinsic entries including `mojo_bswap`/`mojo_ctlz`/`mojo_ctpop`/
  `mojo_cttz` and `mojo_unsupported_intrinsic`) and `6c661dd89` (seven
  analyzer entries: `mojo_builtin_list_append`,
  `mojo_cleanup_pad_checkpoint`, `mojo_dict_set_opt_int`, `mojo_int_of_word`,
  and the three `mojo_list_get_*_checked` readers). The live scan read 856
  against the pinned
  837, so `rthdrscan` failed on the ladder and on every stale prose figure.
  `test_runtime_header_scan.py --fix` wrote the 837 -> 856 rung and the whole
  census from one scan (total 947 -> 966, word 435 -> 448, box 512 -> 518,
  `fire_runtime.c` 803 -> 815 KB, §2.2 share 45.9% -> 46.4%, export gap
  60 -> 73), and the ledger now also records the merge's unledgered 834 -> 837
  step (`a0dfc3b0f`'s three file-iteration entries), which the merge resolution
  had taken as a bare figure. No `disabled=` marker was involved; the job runs
  in `check` and `gate` throughout.
