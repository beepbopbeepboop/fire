# plan/step-27c: landing-pad / personality data structures (pure Python table + test, NO codegen change)
**Status: DONE (verified by agent, work landed)**

Class: mid      Size: M      Depends: 27a      Blocks: none
Source: 27a memo (`bugs/FORMAL_no_exceptions.md`, "EH design (step-27a)"); `formal/model/types.py` `handler_arm_matches` :2712, `exception_base_chain` :2608

## Current state (measured; file:line verified 2026-11-05)
- P0: `python3 -c "import formal.model"` must work (HEAD: `NameError: threading`, `formal/model/layout.py:3155`).
- `formal/model/` is a hub: `__init__.py` imports each module in dependency order (`cfg, methods, values, strings, structs, builtins, calls, types, init, frames, module, layout`; lines ~66-77) and lists them again in `_MODULES` (~line 92). There is no EH table anywhere (`grep -rn "landing\|personality" formal/ | head` is empty besides comments — recheck).
- Class matching is available: `handler_arm_matches(arm_name, flying_name, kinds=None, structs=None)` -> True/False/None (types.py:2712); `CPYTHON_EXCEPTION_BASES` frozenset at types.py:2247.

## Decisions already made
- New module `formal/model/eh.py` (value-model decisions live in `formal/model/`: Global invariant 1). Add `from .eh import *` AFTER `from .types import *` in `__init__.py` and `"eh"` into `_MODULES` after `"types"`. File starts with `from . import *` like its siblings.
- Data only, no emission. Exactly these definitions (frozen dataclasses, plain Python, no AST types except in the builder):
  - `PersonalityArm(arm_index: int, catch_names: tuple, class_ids: tuple, binds: str | None)` — `class_ids` is the build-time list of ids for which `handler_arm_matches` is True; `binds` is the `as` name (the first slice always has `binds=None`; a non-None name makes the builder REFUSE, matching `unemitted_handler_arm`).
  - `LandingPad(region_id: int, line: int, arms: tuple, has_finally: bool)`.
  - `LandingPadTable(function: str, pads: tuple)` with method `arm_for(region_id, class_id) -> int | None` (first matching arm, CPython order).
  - `build_landing_pads(fn, structs=None) -> LandingPadTable`: walks `iter_nodes(fn.body)` for `TryStmt`, one pad per try with handlers (a try with no handlers has no pad: it is a cleanup scope), arms in source order. `class_ids` come from the id assignment the 27a memo recommends; if 27a recommends reusing the existing sorted-name numbering (types.py:~2336-2370, read it), use `exception_class_ids(structs)`; UNVERIFIED — worker must check the real function name with `grep -n "def .*class_id\|def .*exception_id" formal/model/types.py`. Any `handler_arm_matches(...) is None` => raise `ValueError` whose text names the arm (an undecidable arm refuses the image, per its docstring).
- NOTHING calls `build_landing_pads` from codegen or build in this step. A `tools/`-free self-check only.

## Work order
1. `formal/model/eh.py` per Decisions, with a module docstring stating: pure data, consumed by a later step, `as e` refused.
2. Hub edits in `formal/model/__init__.py` (two lines).
3. `test_formal_eh_tables.py` (unittest style like `test_formal_peephole.py`): (a) `try/except ValueError/except OSError` yields one pad, two arms, in order; (b) `arm_for(region, id_of("KeyError"))` with arms `LookupError` -> 0 and `Exception` -> second: first match wins, equals CPython's behaviour proved by an oracle loop over `CPYTHON_EXCEPTION_BASES x CPYTHON_EXCEPTION_BASES` (actually raise and catch in Python, compare with `arm_for`, only for classes constructible bare; copy the exclusion list from `test_formal_exceptions.py::run_matching_oracle` :1311); (c) bare `except:` matches every id; (d) `as e` raises; (e) a `try`/`finally` with no handlers gives no pad but `has_finally` is visible via another helper or is simply absent (pick: absent, assert `pads == ()`); (f) unmodelled base class -> ValueError.
4. Register `test_formal_eh_tables.py` in `tools/suite.py` beside `test_formal_exceptions.py` (grep how that one is registered; `test_formal_exceptions.py` is in NO bucket per the doc, so register the new file in the bucket `test_formal_peephole.py` uses; confirm with `python3 tools/suite.py --list | grep eh_tables`).

## Do NOT
- Do not touch `arm64_codegen.py`/`x86_64_codegen.py`/`build.py`/`lib/`. Do not change `_emit_try`. Do not use the table to un-refuse anything.
- Do not reorder the `__init__.py` imports other than inserting `eh` after `types`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_eh_tables.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_value_model.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_exceptions.py
python3 tools/suite.py --list | grep eh_tables
```

## Done when
- [ ] `test_formal_eh_tables.py` passes (rows a-f); `test_formal_value_model.py` and `test_formal_exceptions.py` counts unchanged
- [ ] `git diff --stat` shows only `formal/model/eh.py`, `formal/model/__init__.py`, the new test, `tools/suite.py`

## If stuck
If importing `eh` perturbs the hub's namespace merge (a name collision shown by value-model tests), rename the colliding public names with an `eh_` prefix; if still red, move the module to `formal/eh_tables.py` (outside the hub), record the reason in the 27a section, and stop.

