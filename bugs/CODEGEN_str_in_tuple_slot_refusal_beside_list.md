# CODEGEN: a str returned in a tuple slot beside a list compiles instead of refusing

**Found:** 2026-11-12, while running `python3 test_gimple.py` for the GIMPLE-tag gate fix.

## Symptom
```
FAIL  a_str_returned_in_a_tuple_slot_still_refuses_beside_a_list [single-TU]:
compiled, so the binary would read the str as a list (SIGSEGV)
```
Test case: `test_gimple.py` `test_a_str_returned_in_a_tuple_slot_still_refuses_beside_a_list`
(around line 9217).

## Expected
The compiler refuses the program: a `str` returned in a tuple slot whose sibling slot is a list is a
mixed-kind observation the box cannot carry. Today it compiles, and the binary reads the str as a list.

## Next step
Find where a tuple return slot's kind is merged with a sibling list slot (the mixed-kind observation
logic that already refuses the parameter and variable cases in the same test file). Make the tuple-slot
path refuse the same way. Quick test: `python3 test_gimple.py` case
`a_str_returned_in_a_tuple_slot_still_refuses_beside_a_list`.
