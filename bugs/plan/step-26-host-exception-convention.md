# plan/step-26: one discoverable host-module failure convention (`hoststatus`)
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: M      Depends: none      Blocks: 23, 23a, 23b, 23c, 23d, 23e
Source: `bugs/FORMAL_no_exceptions.md` ("The rule, stated once"; "The next step" item 1)

## Current state (measured; file:line verified 2026-11-05)
- P0 (check first): `python3 -c "import formal.model"` FAILS at HEAD with `NameError: name 'threading' is not defined` (`formal/model/layout.py:3155`, `_LIBSYSTEM_LOAD_LOCK = threading.Lock()`; layout.py is `from . import *` + no `import threading`). Every test below imports it. If it still fails, make it your own first commit: add `import threading` under line 1 of `formal/model/layout.py`, re-run the import, commit "layout.py: import threading". If already fixed, skip.
- The doc's table claims three conventions. Measured truth:
  - `os`: statuses come straight from libc through `formal/hostmods/os/_syscalls.mojo` (`fs_unlink`, `fs_mkdir`, ...); the only status the module itself *computes* is `makedirs`/`_make_one` (`formal/hostmods/os/__init__.mojo:983-1040`, `return 0 - 1` at :1000 and :1006, `return 0` at :1008, :1038). The prose rule is in the module docstring ("A FAILURE IS A STATUS, NOT AN EXCEPTION", ~line 60) and in the `remove`/`mkdir`/`makedirs` docstrings.
  - `json`: `valid(s)` (`json.mojo:619`) is a 1/0 PREDICATE, not a status; `top_kind` (:630, `return 0 - 1` at :638) and `member_kind` (:743, `return 0 - 1` at :752) return -1 as "no kind". Docstring rule at `json.mojo:41-43` and :91.
  - `hashlib`: the doc row ("a disagreement is a status") is FALSE of the tree: `grep -n -i 'fail\|status\|raise' formal/hostmods/hashlib.mojo` finds nothing; every digest is total. Nothing to migrate; only a citation.
- Constants cannot be module-level names: `os/__init__.mojo` header ("A CONSTANT IS A CALL"), so a "pair of names" must be two zero-argument functions.
- Hostmods import each other with `from <module> import name` (e.g. `formal/hostmods/glob.mojo:157` `from fnmatch import match_any`; `tempfile.mojo:191` `from os import getenv_or, getcwd`). `formal/imports.py::_HOSTMODS_ROOT` (line 79) is the last search root, so `from hoststatus import status_ok, status_err` resolves from any hostmod and from user programs.
- `test_formal_hostmods_census.py::hostmod_modules()` WALKS `formal/hostmods/**.mojo`, so a new module is automatically built on both backends by `test_every_hostmod_builds` (a new file must therefore build).
- The tree writes -1 as `0 - 1` everywhere in hostmods; follow that spelling.

## Decisions already made
- The exported pair lives in a NEW module `formal/hostmods/hoststatus.mojo` (exact path), exactly these two functions:
  ```
  def status_ok() -> int:
      """The success status: 0. See bugs/FORMAL_no_exceptions.md, "The rule, stated once"."""
      return 0

  def status_err() -> int:
      """The failure status: -1. ..."""
      return 0 - 1
  ```
  Module docstring states the rule once (copy "The rule, stated once" paragraph and the `os.makedirs` sentence: never invent a status where CPython has no failure to report). Both carry `-> int` (the annotation puts the signature in the dylib manifest; see `os/__init__.mojo` header).
- Predicates (`json.valid`, `os.path.exists`, ...) stay 1/0 and are NOT statuses; the docstring of `hoststatus` says so. A "kind or none" sentinel (`top_kind`, `member_kind`) uses `status_err()` for the "none".
- Scope of code migration (behaviour byte-for-byte unchanged): ONLY the four sites listed in Work order 3-4. Everything else gets a one-line citation in its docstring, no code change. Do not touch `_syscalls.mojo` or any `0 - 1` that is an internal scanner sentinel (`json.mojo` has ~40 of those: scan_* functions return -1 for "no match"; they are NOT statuses).
- hashlib: citation only: "total function; no failure status (convention: hoststatus.mojo)".

## Work order
1. P0 above.
2. Create `formal/hostmods/hoststatus.mojo` as decided. Build it alone: `python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py hoststatus.mojo` (check the argument form with `--list` first; module args are relative paths).
3. `formal/hostmods/os/__init__.mojo`: add `from hoststatus import status_ok, status_err` next to the other imports (line ~130-138). In `makedirs` and `_make_one` replace `return 0 - 1` (:1000, :1006) by `return status_err()` and `return 0` that mean success (:1008, :1038) by `return status_ok()`. Re-read both functions first; change only returns that are statuses.
4. `formal/hostmods/json.mojo`: add the same import (near the top, after the docstring); replace `return 0 - 1` at :638 (`top_kind`) and :752 (`member_kind`) by `return status_err()`. Nothing else.
5. Citations (docstring text only): `hoststatus.mojo` named in the docstring of every function in `os/__init__.mojo` whose docstring contains "0 on success" (8 hits: `grep -n 'on success' formal/hostmods/os/__init__.mojo`), in `json.mojo`'s module docstring and in the docstrings of `valid`, `top_kind`, `member_kind`, and in `hashlib.mojo`'s module docstring. For `shutil`, `fcntl`, `signal`, `tempfile`, `argparse`, `subprocess` (also contain "on success"): add ONE sentence to their module docstring, "Status convention: hoststatus.mojo."
6. Pin it: in `test_formal_hostmods_census.py` add pure-Python `test_status_docs_cite_hoststatus()`: for every file from `hostmod_modules()` whose text matches `r"0 on success|-1 on failure"` assert `"hoststatus"` appears in it; register it in `main()` beside `test_no_unrecorded_x86_64_failures`. Also assert `hoststatus.mojo` defines exactly `status_ok` and `status_err` (regex on `^def (\w+)`).
7. `bugs/FORMAL_no_exceptions.md`: in "The rule, stated once" replace the three-row table's third row with the measured truth (hashlib: total, no status) and add "The convention is `formal/hostmods/hoststatus.mojo`: `status_ok()`/`status_err()`." Mark "The next step" item 1 DONE with the date. Do NOT delete the doc (item 2 is open; step-27).

## Do NOT
- Do not rewrite the ~40 scanner `0 - 1` in json.mojo or any `fs_*` wrapper in `_syscalls.mojo`.
- Do not make `valid()` return a status or change any value any function returns.
- Do not add a status to `makedirs` for "already exists" (the doc's reason: CPython has no failure to report for `exist_ok=True`).
- Do not make the constants module-level names (no storage across a dylib boundary).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hostmods_census.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_os.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_json.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_hashlib.py
python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_admitted.py
```
(`test_formal_os_backing.py` also runs `os` on both backends; run it if time allows.)

## Done when
- [ ] `formal/hostmods/hoststatus.mojo` exists with exactly `status_ok`, `status_err`; census builds it on both backends
- [ ] the five commands above pass with the same case counts as before (record before/after counts in the commit message)
- [ ] `grep -c status_err formal/hostmods/os/__init__.mojo formal/hostmods/json.mojo` is 2 and 3 (import + uses)
- [ ] `FORMAL_no_exceptions.md` item 1 marked DONE, hashlib row corrected

## If stuck
If importing `hoststatus` from `os` breaks `test_formal_os.py` (e.g. a circular or link-line problem), revert the import in os only, keep the module and the citations, and write the exact failure into `bugs/FORMAL_no_exceptions.md` Status; stop.
