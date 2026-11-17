# SUITE: `modcache`'s slice-2 check asserts an extern object the in-TU pre-pass no longer needs

**Status (2026-11-17): open. Pre-existing on master (reproduced on a pristine
`master` checkout at `b531a4f6a`); found while landing the nested-bracket
generic-call fix, which does not touch this path.**

## What I ran

    python3 test_module_cache.py        # twice, isolated CAS, 178 passed, 1 failed

The failing check is `test_elaboration_inference_and_comptime`
(`test_module_cache.py:408`):

    code, _d, objs, _cpp, _cxx = compile_linked(
        "from el_box import box\nfn main():\n    var y = box(42)\n")
    check("slice2: inferred generic call elaborates (no explicit [..])",
          ('box_1_T_5_Int64' in code or 'box_1_T_3_Int' in code) and len(objs) == 1)

## What I saw

The inferred instantiation IS elaborated and the call IS concrete — the
generated C contains

    int64_t box_1_T_5_Int64 (int64_t);
    _t1 = box_1_T_5_Int64 (_t2);
    int64_t box_1_T_5_Int64 (int64_t x) { ... }

i.e. the body of the instantiation is DEFINED in the same translation unit by
the in-TU pre-pass, so `objs` (the link-object list) is correctly empty. The
`len(objs) == 1` half of the assertion is what fails. Measured identically on a
pristine `master` worktree: symbol list `['box_1_T_5_Int64', 'box_globals',
'box_toplev']`, `OBJS: []`.

## Expected

The check should accept the in-TU definition — which is the stronger result,
and is why no object is linked — rather than demanding the older
extern-object route.

## Exact next step

Update the assertion to say what the in-TU pre-pass now produces: require the
concrete symbol in `code` AND that it has a definition in the same unit (the
`int64_t box_1_T_5_Int64 (int64_t x)` signature line without `extern`), and
drop or invert `len(objs) == 1` with a comment explaining the in-TU definition
needs no link object (`emits a body`, not `records an object`). Then
`python3 test_module_cache.py` should report 179 passed, 0 failed. Note that
`modcache` is registered with `cache=True`, so a recorded PASS could have been
replayed over this red before it was noticed; run the file directly to check.
