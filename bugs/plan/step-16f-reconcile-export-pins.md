# plan/step-16f: reconcile the two export pins and the refusal wording with the inference
Class: easy      Size: S      Depends: 16c, 16d, 16e      Blocks: none
Source: `bugs/FORMAL_known_limits.md` §1.2 2026-10-04 ("the template is still never published under its base name, and the two pins that say so survive unchanged").

## Current state (measured 2026-11-05)
- `test_formal_imports.py` lines 5629 and 5639: `a bare call to a template is refused by the export rule`, `a generic template is not exported under its base name`. Also `test_formal_monomorph.py::test_a_bare_call_to_an_imported_generic_is_still_refused` (line 1044, pins widen(5)).
- `formal/model/module.py::imported_callee_refusal` (line 1996) wording says the source is right and offers `name[<a type>](...)` as a workaround. After 16c-e some bare calls are inferred; the sentence must not claim a call is un-inferable if it now is.

## Decisions already made
- The pins stay: the template is never exported under its bare name (the instantiation is). Edit a pin only if its program is now inferred; in that case change the program to one still not inferable (a literal argument `widen(5)`), keep the assertion.
- Refusal text: add the specific reason when `infer_bare_call` returned a Refusal-with-reason (if 16a/16b added reasons) else leave text.

## Work order
1. Run both test files; list pins that went red.
2. Fix each per the decision. 3. Re-run; record tally in §1.2 Status; delete nothing else.

## Do NOT
- Do not delete a pin to make a run green.

## Verification
```
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_imports.py
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_monomorph.py
python3 tools/plan_index.py --check
```

## Done when
- [ ] both files green apart from 15a's EXPECTED entry; if the bare-call doc bullets in §1.2 are now all closed, say which remain

## If stuck
List red pins with outputs in §1.2 Status and stop.
