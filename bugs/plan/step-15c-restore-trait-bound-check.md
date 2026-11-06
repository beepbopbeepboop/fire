# plan/step-15c: restore the trait-bound conformance check on an instantiation
Class: mid      Size: M      Depends: 15a      Blocks: none
Source: deleted `bugs/formal/FORMAL_generic_monomorph_scope.md` §8 ("A generic with a trait bound — FIXED 2026-10-13"); `bugs/FORMAL_known_limits.md` §1.2.

## Current state (measured 2026-11-05)
- Commit `0c3db7ff3` ("a bounded template's type argument must CONFORM, and the failure is named") IS an ancestor of HEAD, but its code is absent: `grep -n "check_bounds\|_FAILED_DEMANDS\|failed_demand_reason" formal/monomorph.py formal/build.py` finds nothing; `elaborate.check_bounds` (elaborate.py:636) and `elaborate.ConformanceError` (:25) exist. The two pins `a trait bound violation is refused by name` / `a conforming type argument is still instantiated` are not in `test_formal_monomorph.py`.
- Consequence (measured by the original doc as a WRONG ANSWER, not a latent one): `trait Greet`, `struct Cat` with no `hello`, `struct Box[T: Greet]`, `Box[Cat]()` builds and runs although the language rejects it.
- The commit touched: `formal/monomorph.py` (+74), `formal/build.py` (+22), `formal/imports.py` (1 line), tests (+98). `git show 0c3db7ff3 --format= -- formal/monomorph.py formal/build.py formal/imports.py test_formal_monomorph.py` is the exact work list.

## Decisions already made
- Re-apply the five pieces of that diff by hand: (1) `_FAILED_DEMANDS`, `clear_failed_demands()`, `failed_demand_reason(template)`, `_record_failed_demands(failed)` in `formal/monomorph.py`; (2) in `instantiate(src, name, args)`, before `monomorphize.monomorphize_source(...)`: `elaborate.check_bounds(src, template_src, targs)` and `except elaborate.ConformanceError as e: raise MonomorphError(str(e)) from None`; (3) `instantiate_all(module_src, wanted, record=False)` calls `_record_failed_demands(failed)` when `record`; (4) `formal/imports.py::_own_instantiations` passes `record=True` (it currently calls `MM.instantiate_all(consumer_src, wanted)`); (5) `formal/build.py`: in `compile_formal` after `M.clear_exception_kinds()` call `_MM.clear_failed_demands()`, and in `check_module_symbols` (bracketed-callee branch) compute `failed_reason = MM.failed_demand_reason(base_name) if sub.obj is root_ident else None` and put `or failed_reason` between `_bracketed_export_gap(...)` and `M.specialization_call_refusal(...)`.
- Direction is safe by construction (`check_conformance` ACCEPTS an unknown trait or a type with no source in the defining module); do not strengthen it.
- A dependency's bounded template applied to the CONSUMER's own type stays accepted (that is 15d's question).

## Work order
1. Apply pieces (1)-(5); locate each insertion by function name (line numbers have moved).
2. Re-add both test cases from the commit's test diff to the file and `TESTS`.
3. Add one dated Status paragraph to `bugs/FORMAL_known_limits.md` §1.2: trait-bound check restored, case names.

## Do NOT
- Do not call `check_bounds` from any other site.
- Do not record failures for a dependency's demands (`record=True` ONLY for the unit's own half).

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] both restored cases PASS on arm64 and x86_64; the violation message names the trait AND the missing method (`missing method 'hello'`) and does not contain "asked for none"
- [ ] no other case changes verdict vs the 15a tally

## If stuck
If `check_bounds` raises for a CONFORMING template in an existing case, record the case + message in §1.2 Status and stop; do not weaken the check.
