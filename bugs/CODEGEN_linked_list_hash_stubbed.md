# CODEGEN: LinkedList.__hash__ lowers to a stub

Found 2026-11-10 by the estate audit: `test_linked_list_hash_step1.py` fails on master.

## Measured
The generated C for the test's `LinkedList` program contains stubbed calls:

    _t11 = _t9;  /* int64_t.__hash__() stubbed */

The test asserts that no `__hash__() stubbed` text is emitted for `LinkedList`.

## Next step
Lower `__hash__` for a struct that defines it, instead of falling back to the stub. Delete this doc in the commit
that fixes it.
