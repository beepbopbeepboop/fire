# plan/step-15a: repair the monomorph baseline (import errors, debug litter, stale test expectations)
**Status: DONE 2026-11-05 (verified).** `test_formal_monomorph.py`: PASS=60, EXPECTED=0, FAIL=0. Fixed here: (1) `tools/formal_template_call_census._strip_comments` cut `#` inside backtick/quoted literals (`std/sys/info.mojo`'s `` `#kgen.param.expr<…>` ``), producing an "unterminated backtick string literal"; now literal-aware (`_comment_start`). (2) `elaborate.extract_fn_source` parsed an INDENTED method candidate as a module ("Unexpected INDENT") when a name is both a method and a free function (`is_amd_gpu`); dedents for the arity check. (3) The ambiguity refusal for `Template.<attr>` with 2+ instantiations had been lost: restored `model.template_attribute_read_ambiguous` (formal/model/types.py) and its raise in `monomorph.rewrite_instantiation_uses`. Two branches had built two different refusals and the merge kept both tests; ONE message now carries both opening phrases, and the older test's needles were updated with a comment saying why.
Class: mid      Size: M      Depends: none      Blocks: 15b, 15c, 15d, 15e, 16a, 16b, 16c, 17, 18a, 19, 20, 22
Source: `bugs/FORMAL_known_limits.md` §1.2 (RE-MEASURED 2026-10-03 / 10-04) and the deleted generic-monomorph-scope FORMAL doc (last full text in git history at 4fdf0a95d^, 883 lines).

## Current state (measured 2026-11-05 on HEAD 99b35eb6e + the uncommitted doc edits)
- **HEAD (committed) cannot import `formal`; as of 2026-11-05 a working-tree edit to `formal/model/layout.py` (+`import threading`, not mine) may already fix it.** `formal/model/layout.py:3155` does `_LIBSYSTEM_LOAD_LOCK = threading.Lock()` and nothing imports `threading` (layout.py starts `from . import *`; `formal/model/__init__.py` imports at lines 28-32 have `dataclasses, os, re, typing` only). Every `test_formal_*.py` dies with `NameError: name 'threading' is not defined`. Proof: `python3 -c "import formal.model"`. (With `threading` injected into builtins `formal.model`, `formal.imports`, `formal.monomorph` all import: that is the only missing name.)
- `tools/formal_template_call_census.py` lines 1-3 are merge junk BEFORE the shebang (`import sys` / `sys.path.insert(0, os.path.dirname(...))` / `from module_loader import STDLIB_PATH`); `os` is not yet imported there (real imports are at lines 104-114) -> `NameError: name 'os'` -> 3 census cases in `test_formal_monomorph.py` ERROR.
- Debug-write litter left by commit `cd70b0fc5` (writes to `/tmp/DEBUG_*.txt` and `.tmp/DEBUG_*.txt`): `formal/build.py` 1835, 1852, 1867, 1874, 1886; `formal/monomorph.py` 2001; `formal/imports.py` 2718, 2726, 2737. (`DEBUG_ASSERT_COMPTIME_PARAMS` in `formal/model/builtins.py` is a real constant: leave it.)
- `test_formal_monomorph.py` (54 cases) with `threading` supplied via a sitecustomize shim: **PASS=46 FAIL=8**: 3 census ERRORs (the `os` bug) + 5 FAILs listed below. Takes ~36 s, 0.1 GB.

| case | what it prints/does now | cause |
|---|---|---|
| `a struct template the module declares can itself apply` (line 468), `a type argument in a local annotation is a demand` (526) | formal prints `7\nTrue\n`; test expects `7\n1\n` | the twin does `print(int(b.get()))`; Mojo/CPython print a Bool as `True`. The test is stale, the program is right. |
| `an own struct template with a comptime value is diagnosed as one` (1285) | `Tagged[Int, 0]()` BUILDS | comptime-value instantiation landed (`7031ef1b0`, `formal/monomorph.py::value_demands_for`); test expects a refusal. Stale. |
| `a variadic bracket parameter takes the extra arguments` (3538), last block | `all_instantiation_calls(...)` returns `{}` | `Pair[Int, 1, 2, 3]` is now read by the permissive reader: `MM.all_bracketed_calls(src)` gives `{'Pair': [('Int','1','2','3')], 'tile': [('2','3')]}`. Stale. |
| `a class attribute through two instantiations is refused` (3760) | refusal text is "This path compiles one image for every instantiation ... closed by binding the parameter values at the instantiation site", not "applies TypeDict at 2 of them" | a FEATURE regression (ambiguity refusal naming both instantiations). NOT fixed here. |

## Decisions already made
- Fix the import bugs at their source (one `import threading` in `formal/model/__init__.py`; census header rewritten), not with try/except.
- Stale expectations are updated to the true behaviour (below). The class-attribute case goes into `EXPECTED_FAILURES` (the dict just above `main()` in the test file; key = the case's name string exactly as in `TESTS`) with a reason naming this step; it is NOT edited to match the new text, because the old text was the feature.
- Do not touch any other behaviour. This step changes no codegen.

## Work order
1. Run `python3 -c "import formal.model"`. If it already succeeds (another lane added `import threading` to `formal/model/layout.py` after this plan was measured, uncommitted in the shared tree) do NOTHING for this item; otherwise add `import threading` to `formal/model/__init__.py` after `import re` (line 31). Then run `python3 -c "import formal.model, formal.imports, formal.monomorph"`; must print nothing.
2. `tools/formal_template_call_census.py`: delete lines 1-3; make line 1 the shebang; after the existing `import sys` (line 108) the code at 112 already does `sys.path.insert(0, ROOT)`; add `from module_loader import STDLIB_PATH  # noqa: E402` right after that block ONLY IF `STDLIB_PATH` is used in the file (`grep -n STDLIB_PATH tools/formal_template_call_census.py`); otherwise add nothing.
3. Delete every debug block listed above (`grep -n "DEBUG_" formal/build.py formal/monomorph.py formal/imports.py | grep -v ASSERT`). Each is a `try: with open(...DEBUG...) ... except Exception: pass` wrapper: remove the whole wrapper, keep surrounding logic. In `formal/build.py` ~1835 check the `_dbg` variable has no other use. After: `grep -rn "DEBUG_" formal/build.py formal/monomorph.py formal/imports.py` prints nothing.
4. Test edits in `test_formal_monomorph.py`:
   a. line 468 case: change the twin's last line to `print(b.get())` and the expected string to `"7\nTrue\n"`; same for the case at 526 (read it, same twin shape).
   b. line 1285 case: rename to `an own struct template with a comptime value is instantiated`, in `TESTS` too; rewrite as a CPython differential: lib-less single file `struct Tagged[T, origin: Int]: var v: Int` with `def main(): var t = Tagged[Int, 0](); t.v = 42; print(t.v)`; expect `42\n` on both arches (`run_pair_case(tmpdir, arch, "mm_own_comptime", None, src, cpython)`; copy the call shape from the case at line 468). If it does not build, STOP (see If stuck).
   c. line 3538 case: replace `MM.all_instantiation_calls(` in the last `callers = ...` block by `MM.all_bracketed_calls(` and the assertion text accordingly; keep `check(callers.get("Pair") == [("Int","1","2","3")])`.
   d. `EXPECTED_FAILURES["a class attribute through two instantiations is refused"] = "regression: ambiguity refusal text lost; plan step-15a, see FORMAL_known_limits.md §1.2 Status"`. Its key must equal the `TESTS` name string.
5. Append a dated Status paragraph to `bugs/FORMAL_known_limits.md` §1.2 (end of the 2026-10-04 block, before `## 1.3`): the baseline numbers before/after, and "features present in git history but ABSENT from HEAD: aliased import (`4440853a2`, on branch `origin/work/bug-formal-formal-generic-monomorph-scop-5902`, not merged), trait-bound conformance (`0c3db7ff3`, ancestor of HEAD but code absent), imported-parameter-annotation pin (`75086acf2`, ancestor, test absent) -> steps 15b/15c/15e".

## Do NOT
- Do not `git checkout`/`restore`/`stash` anything; the tree has uncommitted doc edits.
- Do not make the tests pass by loosening `check(...)` strings beyond what step 4 says.
- Do not "fix" the class-attribute regression here.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 -c "import formal.model, formal.imports, formal.monomorph"
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] first command prints nothing
- [ ] `test_formal_monomorph.py` ends `PASS=53 EXPECTED=1 SKIP=0 FAIL=0` (54 cases)
- [ ] `grep -rn "DEBUG_" formal/build.py formal/monomorph.py formal/imports.py` is empty
- [ ] `test_formal_imports.py` has no `threading`/`os` NameError (record its tally; any failure there that is not an import error is pre-existing: list names in the Status paragraph, do not fix)

## If stuck
If any stale case does not behave as the table says, write the observed output into the Status paragraph of §1.2 and stop; do not edit the case.
