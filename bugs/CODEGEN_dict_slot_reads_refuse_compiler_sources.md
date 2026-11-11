# CODEGEN: compiling the compiler's own sources is refused: dict-slot reads are tagged words

Found 2026-11-10. Since the dict-slot read work landed (7ae229803, merged to master in 6b5c68c5b), the self-host build
refuses to compile fire.ci's own modules. Three of them:

    ERROR: compiling imported module 'ast_rewriter': 'node': a name bound to a tagged generator word (a yield of more
    than one kind) cannot also hold a value of another C type (str or float): the box cannot carry it; refused
    ERROR: compiling imported module 'mojo.middle.coro': '_callee': ... refused
    ERROR: compiling imported module 'mojo.middle.module_shared': '_fd': ... refused

## Measured (bisect on ast_rewriter.py, compile_module_to_c, linkable=False)

| commit | result |
|---|---|
| d049ce259 (before the session) | OK |
| 35576ecc9, f36706357, 1e2cd3d11, 7654f53c9 (dict-slot series, earlier steps) | OK |
| 7ae229803 "make dict slot reads always carry value kind" | REFUSED |
| 3213b5e88, 08fd01352, abbde2442, 0d8bb4429, master | REFUSED |

module_shared.py is refused on master and was OK at d049ce259.

## Why

7ae229803 makes a subscript read of a dict slot a tagged word. A name bound from such a read, and later stored from a
str or float value (`node = d['k']` then `node = 'x'`, the same shape in the three modules), trips the existing
refusal in emit_infra.py (MIXED_NAME_NON_INT64_REFUSAL, from efef2b08a). The refusal is correct for a real
generator word; a dict read is not one, so the refusal should not fire for it.

## Next step

Either the dict read must not be tagged when the name is later reassigned with another type, or the refusal must
only fire for a generator word (`_tagged_next` names). Measure with the probe above; the fix is done when all three
modules compile and test_dict_slot_read_regression.py still passes.
