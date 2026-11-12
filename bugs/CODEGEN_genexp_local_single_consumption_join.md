# CODEGEN: genexp local bound to a tagged-generator word refuses a str join

**Found:** 2026-11-12, while running `python3 test_gimple.py` for the GIMPLE-tag gate fix (bugs/gate-stdlib-syntax.md, fixed in f4a7ee488).

## Symptom
```
FAIL genexp_local_single_consumption_join: RuntimeError: 'arcname': a name bound to a
tagged generator word (a yield of more than one kind) cannot also hold a str value
(char *): the box cannot carry it; refused
```
Test case: `test_gimple.py` `genexp_local_single_consumption_join` (the `clean(...)` join over a
generator expression that yields a str/`char *` path).

## Expected
The single-consumption genexp local should compile and print `a/b/c` (per the test's expected output).

## Next step
The refusal is raised by the tagged-generator box logic (`_seed_genexp_list_narrowing` and the mixed-kind
box). Find which yield kinds the `arcname` local is seeded with and why a `char *` yield joins a
tagged generator word. Either allow the str kind into the box or narrow the genexp so it is not
classified as mixed. Quick test: `python3 test_gimple.py` case `genexp_local_single_consumption_join`.
