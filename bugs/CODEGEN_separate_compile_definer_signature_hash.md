# CODEGEN: a separately compiled importer hashes its own view of an unannotated callee

**Found by:** the `globcompiled` gate fix (work/fix-gate-globcompiled). Not fixed there: the inline
`fire.py build` path is fixed, this shape is not.

**Related, not the same doc:** `bugs/hard/CODEGEN_stdlib_dylib_lazy_undefined_refs.md` (the stdlib dylib's
undefined `_std_` references). This is the same family (the importer hashes a parameter list the definer
does not emit), reached through a different compile shape.

## Symptom

A callee with an UNANNOTATED parameter, called from an importer that passes a value of a different
inferred type. Each module compiled on its own (`compile_module_to_c` per file, one `GimpleGen` per
module, as `test_codegen_module_alias_function_value.py` does) links to nothing:

```
# helper.py
def f(p):
    for c in p:
        pass
    return 42

# main.py
import helper as h
print(h.f("abc"))
```

Measured on HEAD and on the `globcompiled` fix: the link fails with
`undefined symbol _helper_f_9f63a2` (referenced from `main`). `helper.py`'s own C defines
`helper_f_815e8f (MojoList *)`: the definer types `p` as a list from its body, and the importer hashes
`int64_t` (its own resolution, `char *` from the literal call site, or the default).

Expected: the call names the symbol the definition emits, and the program prints `42`.

## Why

`_home_def_param_types` (the store `emit_funcs._commit_home_def_pts` writes and
`_imported_def_pts` reads first) is a field of each `GimpleGen` instance (`gimple_codegen.py`, the
`__init__` assignment). The inline `fire.py build` path compiles the definer and the importer in one
instance, so the committed signature is visible and the call hashes it. A separately compiled definer
commits into its own instance; the importer's instance never sees it and falls back to its own
`_home_signature_ctypes`, which can disagree.

The same fallback is what `funcs_shared.module_member_function_csym` and
`register_module_member_value` use when nothing is committed. Both now prefer the committed entry
(this fix), so the gap is exactly the separate-compile case.

## Next step

Make the separately compiled definer's committed signature reachable from the importer. Options, to
choose between (do not pick by convenience):

1. Publish each definer's committed `_home_def_param_types` entries into the export table the importer
   already reads (`_local_sibling_module_exports`), so the separate compile carries the definer's answer
   the same way it carries the function's return type (`_home_def_return_types`, which the importer
   reads through the export scan for the same reason).
2. Have the separate compile of a module with a sibling import compile its dependencies first and share
   the store (the inline path's behaviour, made explicit).

Option 1 matches the return-type precedent. Quick test: the case above, added to
`test_codegen_module_alias_function_value.py` as a CASES entry, with `value_read=False`. It must link and
print `42` on both the per-file path and the inline path.
