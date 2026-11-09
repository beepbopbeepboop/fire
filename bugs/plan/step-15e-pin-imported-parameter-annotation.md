# plan/step-15e: re-pin the imported-instantiation parameter annotation (value vs frame)
**Status: DONE 2026-11-06 (measured).** 'a parameter annotation of an imported instantiation' PASSES; `test_formal_monomorph.py` 60/0/0 on 2026-11-06.
Class: easy      Size: S      Depends: 15a      Blocks: none
Source: the deleted generic-monomorph-scope FORMAL doc §1 / §1a (status 2026-10-13); `bugs/FORMAL_known_limits.md` §1.2.

## Current state (measured 2026-11-05)
- Commit `75086acf2` ("pin §1a — the value half is answered and the frame half is the remainder", ancestor of HEAD) added the case `a parameter annotation of an imported instantiation`; HEAD's `test_formal_monomorph.py` lacks it (`grep -n "imported instantiation" test_formal_monomorph.py` finds nothing).
- Documented behaviour: `def keep(p: Pair[Int])` in a library. ONE-field `Pair` (a value, one word): builds and answers CPython. TWO-field `Pair` (a frame address): REFUSED with "...the parameter in that position is a frame holder of Pair...": the contract names the TEMPLATE, the caller holds `Pair_1_T_3_Int`. The one reader that would change is `formal/model/structs.py::parameter_declared_structs` (line 1855), which has five callers: that is a corpus-wide change, deliberately not taken.

## Decisions already made
- Test-only step: restore the case (`git show 75086acf2 --format= -- test_formal_monomorph.py`), add to `TESTS`, run it. If a half's behaviour differs from the documented one, pin the CURRENT truth and record the delta; do not change code.

## Work order
1. Re-add the case + `TESTS` row.
2. Run; if it fails, read the output, adjust ONLY the expected string to the observed true behaviour if the observed behaviour is a refusal that names the frame holder or a build that matches CPython; anything else -> If stuck.
3. One dated Status paragraph in `bugs/FORMAL_known_limits.md` §1.2: both halves pinned, frame half remains open with the reader named above.

## Do NOT
- Do not edit `parameter_declared_structs`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] the case PASSES (both halves, both arches); suite tally otherwise unchanged

## If stuck
Write the observed outputs of both halves verbatim into §1.2 Status and stop.
