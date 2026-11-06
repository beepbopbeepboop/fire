# plan/step-17: close out declared-`__init__` construction (it landed; pin it and fix the doc)
Class: easy      Size: S      Depends: 15a      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §6.1 (`builtin_slice.mojo` row), §6.3 lever #3 ("`Slice.__init__`, 20 files").

## Current state (measured 2026-11-05; the draft step was STALE: the capability exists)
- Declared-`__init__` construction is implemented: `formal/model/init.py::struct_construction_plan` (line 2700; kinds `CONSTRUCTION_DEFAULT/POSITIONAL/INIT/COPY`), `construction_init_arity_refusal` (~2150), `construction_init_body_refusal` (:2260), `construction_keyword_refusal` (:2356), `struct_fields_written_outside_init` (:322). The argument COUNT selects the overload and the selected body is inlined at the construction site. Pinned in `test_formal_run.py` (block at ~11897, row `constr_init_arity_selects_the_overload`, `Slice3(1, 9)` and `Slice3(2, 8, 5)` against CPython).
- The real `std/builtin/builtin_slice.mojo` no longer stops at `__init__`: `python3 fire.py build --formal --no-prove -o .tmp/s.aout ../modular/mojo/stdlib/std/builtin/builtin_slice.mojo` -> terminal `Slice.write_to: FormatStruct is called ... a bare call asks for none` (that is step 16's row).
- A faithful copy of `Slice` (three `Optional[Int]` fields, `__init__(out self, start: Int, end: Int)` ending `self.step = None`) builds to a different true refusal: "is an `Optional[Int]`, and this target has no word to spell `None` as for it ... WRONG about `Some(0)`" (`optional_none_word`). That is the Optional-representation limit, not `__init__`.
- `test_struct_formal.py` has no Slice/`__init__` rows (it is a different file; do not use it for this).

## Decisions already made
- No code change. This step records the truth and pins the real shape so the next sweep cannot silently regress it.

## Work order
1. In `test_formal_run.py`, find the case list that holds `constr_init_arity_selects_the_overload` (grep it). Add ONE row `constr_init_optional_none_field_is_refused` whose program is the Slice copy above plus `def main(n: Int) -> Int: var a = Slice(1, 9); return 7`, with the expected-refusal convention that file uses for refusal rows (read how an existing row with `refuse:` is written, e.g. `grep -n '"refuse' test_formal_run.py | head`) and the expected substring `Some(0)`.
2. Edit `bugs/FORMAL_known_limits.md`: in §6.1's table row for `std/builtin/builtin_slice.mojo` and §6.3 lever #3, add a dated line: "declared `__init__` construction landed (cases ...); `builtin_slice.mojo` now stops at FormatStruct (plan step-16) and, past it, `Optional[Int]` fields (optional_none_word)". Do not delete the rows (they are history the sweep map cites).
3. Run `python3 tools/dangling_doc_refs.py --ratchet` (compare with pre-step output; add nothing).

## Do NOT
- Do not implement anything in `formal/model/init.py`.
- Do not claim `Slice` builds.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py 2>&1 | tail -5
python3 tools/plan_index.py --check
```
(`test_formal_run.py` is large; if it takes more than 10 minutes, run it once and record the tally, do not rerun.)

## Done when
- [ ] new row passes and the `constr_init_*` rows still pass
- [ ] §6.1 / §6.3 carry the dated line

## If stuck
If the faithful copy builds, record that and the stdout in §6.1 and stop.
