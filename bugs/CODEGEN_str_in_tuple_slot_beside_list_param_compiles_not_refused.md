# CODEGEN: a str returned in a tuple slot and passed to an iterated parameter beside a list compiles, instead of refusing mixed containers

Status: OPEN. Filed 2026-11-12 by the line-directive worker. It fails on HEAD (460c17efa) with no change of mine applied, so it is pre-existing; it was found by running `test_gimple.py` as the quick test for the touched emitter.

## Symptom

`test_gimple.py` case `a_str_returned_in_a_tuple_slot_still_refuses_beside_a_list` (around line 9217) fails:

    FAIL  a_str_returned_in_a_tuple_slot_still_refuses_beside_a_list [single-TU]: compiled, so the binary would read the str as a list (SIGSEGV)

Program:

    def pair():
        return "de", 1
    def each(xs):
        for x in xs:
            print(x)
    def main():
        s, n = pair()
        each(s)
        each([4, 5])
    main()

Expected: a loud refusal naming `'xs'` and `'each'` (the mixed-container refusal), because `each`'s parameter is passed a str and a list, and the str must not be read as a list. Actual: `compile` succeeds (`gimple_codegen._run_pipeline(src, filename='case.py', do_imports=True)` returns), so the generated binary would treat the string's pointer as a `MojoList *`.

Measured: the same call on a `git archive HEAD` extract and on the working tree both print `COMPILED`. The sibling case `a_list_returned_in_a_tuple_slot_is_not_a_mixed_str_observation` passes, so the tuple-slot exemption works for a list and is not refusing a str in slot 0.

## Likely cause (unverified)

The per-slot kind of `s, n = pair()` is taken from the callee's return. The exemption that lets a container-typed tuple slot skip the mixed-container refusal (the one `a_list_returned_in_a_tuple_slot...` pins) seems to also apply when the slot is a `char *` str literal, so `each(s)`'s parameter is not observed as str. Start in the code that records the mixed-str observation for an iterated parameter (grep `is_mixed`/`mixed_str` and the tuple-slot exemption in `mojo/middle/` and `mojo/backend_gimple/`).

## Next step

1. Reproduce the single case: `python3 -c` with the program above, printing the generated `each` signature and `main`'s call, to see what kind `s` gets.
2. Fix so a str observed in a tuple slot counts toward the mixed-container refusal, while a container-typed slot stays exempt.
3. The quick test is the named case, plus `a_list_returned_in_a_tuple_slot_is_not_a_mixed_str_observation` and `an_iterated_parameter_passed_a_list_and_a_str_compiles_per_kind` still passing, all in `test_gimple.py`.

## Done when

`python3 test_gimple.py` runs `a_str_returned_in_a_tuple_slot_still_refuses_beside_a_list` and reports PASS (and its neighbours stay PASS). Then delete this doc in that commit.
