# plan/step-18b: make `_frame_methods` classify only the shapes whose contract is true
**Scope note (2026-11-07, from 18a):** the restriction is already in `_frame_methods` ("D1 (18b)" comments). Remaining work is only to pin it: add tests that `inc`, `pop`, `set2` on a one-field `Box` give `_frame_methods(...) is None` (programs in `.tmp/18a/measure.py`, pattern `test_one_field_mutator_by_reference_gets_contract`), then mark DONE.
Class: mid      Size: M      Depends: 18a      Blocks: 18c, 18d
Source: 18a's section "§6.3 Design: the by-reference one-field mutator contract" in `bugs/FORMAL_known_limits.md`.

## Current state (verify first: that section exists; else STOP)
- `formal/arm64_proof_gen.py::_frame_methods` (:13803): placeholder branches at ~13840-13866 and the relaxed `kind="set"` rule at ~13915 (`all(stores) and (len(f.body) == 1 or is_byref_onefield)`).
- Test: `test_formal_frame_method_finder.py` (5 tests, pass).

## Decisions already made
- Apply 18a's D1 verbatim: by-reference one-field methods are classified `set` only when the body is ONE assignment of a parameter to `self` and the machine shows ONE store; `get` only for `return self`; everything else `continue` (no contract, as before 2026-11-03). Remove the "placeholder, will be adjusted" lines.

## Work order
1. Edit `_frame_methods` per D1; keep the already-landed single-store case.
2. Add tests to `test_formal_frame_method_finder.py` in the same style as `test_one_field_mutator_by_reference_gets_contract`: one per row of 18a's table that D1 now EXCLUDES (`assertIsNone(found)` or the method absent from `found`), and keep the set_v case.
3. Run the existing proof generator unit file for frame contracts: `python3 tools/memslot.py --gb 24 --label t -- python3 test_formal_call_proof_gen.py` (no Lean if the file's default doesn't need it; if it invokes lean, SKIP it and say so).

## Do NOT
- Do not add any new classification. Do not edit `lib/`.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_frame_method_finder.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] the excluded shapes return no method; `set_v` still classifies `kind="set"`

## If stuck
Write the shape that still misclassifies into §6.3 Status and stop.
