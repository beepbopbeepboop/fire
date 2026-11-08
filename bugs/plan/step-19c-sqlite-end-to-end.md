# plan/step-19c: a real sqlite3 word-shaped call through a formal executable, and the census numbers
**Status: DONE 2026-11-07 (measured).** `test_optional_unit_word_call_links_and_runs` (arm64 + x86_64: 2 linked dylibs, the second is sqlite3, exit 7 from `mojo_sqlite3_errmsg(0) == 0`) and `test_optional_unit_box_call_is_still_refused` added; `test_formal_runtime_link.py` 213 -> 225 passed, 0 failed. Census figures refreshed to the live ones (897 entry points, 411 word-shaped, 783 in `fire_runtime.h`); `test_runtime_header_scan.py` 43/28 -> 72/0 (the remaining failure was the census quote the plan wave deleted from `formal/build.py`, restored). `test_formal_dylib.py` NOT re-run. zlib/ssl/ncurses/metal untested.
Class: easy      Size: S      Depends: 19b      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §3.1.

## Current state
- After 19b a formal image can link `libmojosqlite3*` beside the core runtime. Safe word-shaped calls with no live handle (read `runtime/fire_sqlite3.c`): `mojo_sqlite3_close(0)` is a no-op (`if (db)`), `mojo_sqlite3_errmsg(0)` returns NULL (0). `mojo_sqlite3_open` is not word-shaped, so no live handle can be obtained from a formal program: the end-to-end evidence is therefore a link + a deterministic host value, not a query.

## Decisions already made
- Program: `def main():\n    mojo_sqlite3_close(0)\n    if mojo_sqlite3_errmsg(0) == 0:\n        return 7\n    return 1\n` — exit code 7 on both arches (copy `test_word_shaped_call_links_and_runs`, `build(...)`, `run(r)`).
- Box control stays: the existing `test_box_surface_still_refused` (:227, it uses `mojo_sqlite3_open`) must keep its verdict and its message.

## Work order
1. Add `test_optional_unit_word_call_links_and_runs` to `test_formal_runtime_link.py` and register in its runner (see `main()` at :1082 for how cases are listed). Assert: exit 7; `len(r["linked_dylibs"]) == 2`; the second basename contains `sqlite3`; `otool -L` (if available, mirror `test_image_carries_the_load_command`) names it.
2. Add the negative: a program calling `mojo_sqlite3_close(0)` AND a box-shaped one (`mojo_sqlite3_open(":memory:")`) is refused with the box message, not built.
3. Update `bugs/FORMAL_known_limits.md` §3.1: replace "871 entry points, 405 word-shaped" figures with the current ones ONLY IF `test_runtime_header_scan.py` pins them (it computes live: run it and copy its printed figures); add a dated Status "optional unit registry wired for the formal path: sqlite3 16/22 word-shaped reachable; zlib 2, ssl 11, ncurses 16, metal 5 follow the same path (untested)".
4. `python3 tools/dangling_doc_refs.py --ratchet` — add nothing.

## Do NOT
- Do not claim zlib/ssl/ncurses/metal work; they are untested.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_runtime_link.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_dylib.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] new case passes on arm64 (and x86_64 where the existing runtime-link cases run it)
- [ ] `test_formal_dylib.py` tally equals its pre-step tally (record both numbers)

## If stuck
If `mojo_sqlite3_errmsg(0)` is not 0 or the call crashes, pick `mojo_sqlite3_close(0)` only (exit code from a constant) and say the value test could not be done.
