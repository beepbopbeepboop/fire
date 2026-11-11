# CODEGEN: LinkedList.__hash__ lowers to a stub

## Status: PARTIAL (2026-11-10)

FIXED: the element hash inside the stdlib's `LinkedList.__hash__` is no longer a
stub. A scalar's one-argument `__hash__(hasher)` folds the value into the hasher
(`mojo_hasher_update_int`, runtime `mojo_hasher_new` / `_finish`), and
`test_linked_list_hash_step1.py` passes.

STILL OPEN: `hash(l)` on a `LinkedList` still goes to `mojo_hash` on the list
pointer (`mojo/backend_gimple/emit_calls.py`, the `hash` builtin), so it never
reaches the struct's `__hash__`. Two equal lists can hash differently. The fix is
to lower `hash(x)` for a struct with `__hash__` as: new hasher, call the struct's
`__hash__(x, hasher)`, return `mojo_hasher_finish`. The struct's mangled method
name must come from the same registry the method-call lowering uses.

Found 2026-11-10 by the estate audit: `test_linked_list_hash_step1.py` fails on master.

## Measured
The generated C for the test's `LinkedList` program contains stubbed calls:

    _t11 = _t9;  /* int64_t.__hash__() stubbed */

The test asserts that no `__hash__() stubbed` text is emitted for `LinkedList`.

## Next step
Lower `__hash__` for a struct that defines it, instead of falling back to the stub. Delete this doc in the commit
that fixes it.
