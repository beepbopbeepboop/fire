# `selfhost`: the dispatch-globals list forces every name to `MojoDict *`

## What I ran

Merging the `bugs3` batch, `selfhost` is red on my branch and green at the base
commit `d0796643`:

    python3 tools/suite.py selfhost
    # FAIL  selfhost  (155s)  exit 1

    python3 tools/memslot.py --gb 8 --label selfhost -- python3 test_selfhost.py

    # ERROR: compiling imported module 'module_loader' from .../module_loader.py:
    #   cannot coerce MojoSet * to MojoDict * (incompatible container kinds)
    #   at .../module_loader.py: value='_t56' dest='_t57'
    # ERROR: compiling imported module 'generated_dispatch' ...
    # ERROR: compiling imported module 'mojo.middle.types' ...
    # ERROR: compiling imported module 'gimple_codegen' ...
    ✗ self-host compile/link regressed

Base reports `Results: 2 passed, 0 failed`. 35 gcc errors at my tip.

## Root cause, established

`e98ea1f8` / `939843ee` ("One list for the dispatch globals, because four
hand-written copies stopped agreeing when they moved module") collapsed four
hand-written copies of the same fact into one list. **All four copies held the
same EIGHT names** — `_STMT_DISPATCH`, `_EXPR_DISPATCH`, `_BIN_OPS`,
`_TYPE_MAP`, `_SIGNED`, `_UNSIGNED`, `_FLOAT` (dict) and `_CMP_OPS` (set) — and
the consolidation rewrote the list's contents to TWENTY-THREE while
deduplicating. Verified from the diff:

    -_DISPATCH_TABLE_NAMES = ('_STMT_DISPATCH', ..., '_FLOAT', '_CMP_OPS')
    -_EARLY_DISPATCH_DICTS = {'_STMT_DISPATCH', ..., '_FLOAT'}
    -_EARLY_DISPATCH_SETS = {'_CMP_OPS'}
    -_dispatch_dict_names = ['_STMT_DISPATCH', ..., '_FLOAT']
    -_dispatch_set_names = ['_CMP_OPS']
    +_DISPATCH_TABLE_GLOBAL_NAMES = ('_STMT_DISPATCH', ..., '_SELFHOST_EXTRA_FIELD_CACHE')

Three sites then answered a name from that list with a blanket type, and the
list no longer distinguished dict from set:

| site | before | after |
|---|---|---|
| `module_gen.py` early cdecl seed | `_EARLY_DISPATCH_DICTS` / `_EARLY_DISPATCH_SETS` (7 + 1) | `_EARLY_DISPATCH_DICTS = set(all 23)`, `_EARLY_DISPATCH_SETS = set()` — every name `MojoDict *` |
| `module_gen.py` import declaration | `_dispatch_dict_names` / `_dispatch_set_names` (7 + 1) | `_dispatch_dict_names = list(all 23)`, fallback `or 'MojoDict *'` |

Nine of the added names are `frozenset`s and one (`_CMP_OPS`) is a set
(`generated_dispatch.py` declares `_CMP_OPS: set`), so "a dispatch table is a
dict" is wrong for ten of them.

The failure needs one more ingredient, and it is why this is a build error
rather than a misprint: the answer is written into the SHARED, bare-name-keyed
`_global_c_decl_types`, and `_own_overlay_global_ctype`'s rule 1 says "a
CONTAINER cdecl beats a scalar own-conclusion". So module_loader's own
set-valued `_C_KEYWORDS = frozenset({...})` (module_loader.py:13) found
`_global_c_decl_types['_C_KEYWORDS'] == 'MojoDict *'` and coerced to it.
Measured at the assignment site:

    _global_c_decl_types['_C_KEYWORDS'] = 'MojoDict *'
    _own_global_var_types['_C_KEYWORDS'] = 'MojoSet *'      <- the owner's own answer
    _global_dst_ctype('_C_KEYWORDS')      = 'MojoDict *'

## What I tried, and why each is not the fix

Recorded because the three obvious moves each fail in a way that is
informative, and the patch for the first one is preserved at
`.tmp/selfhost-partial.patch` (not committed — see below).

**1. Carry the type in the list (a `name -> ctype` mapping).** Removes all four
`# ERROR: compiling imported module` lines. But the self-host build then reports
**97** gcc errors instead of 35, dominated by:

    12  assignment to 'int64_t' from 'MojoSet *' makes integer from pointer
     8  assignment to 'MojoSet *' from 'int64_t' makes pointer from integer
     8  'struct _mojo_backend_gimple_emit_funcs_toplev' has no member named '_TYPE_MAP'
     6  'struct _mojo_backend_gimple_emit_infra_toplev' has no member named '_module_loader'

The removed errors were not fixed, they were MASKED: those four modules used to
fail and roll back to source inclusion (`emit_resolve.py`'s `except` around
`_compile_imported_module`), so gcc never saw their bodies. Correctly typed,
they compile far enough to show what is actually wrong with them — a second,
independent layer.

**2. Narrow the list back to the eight names.** Much worse — this is the
measurement that proves the widening is load-bearing. The importer's
declaration site declares each listed name as a field of the importing module's
own globals struct, and the generated code READS it back through that field, so
dropping a name stops declaring the field:

    'struct _mojo_middle_exprtypes_toplev' has no member named '_CPP_CALLABLE_CTYPE'
    'struct _mojo_middle_module_shared_toplev' has no member named '_BUILTIN_RET_CTYPES'

`_selfhost_module_scalar_globals`'s SKIP is why all 24 belong in the list even
though only some need a type forced; `_BUILTIN_RET_CTYPES` is not even in the
list and was still mis-declared, because the skip is what stops it.

**3. Make `_DISPATCH_TABLE_GLOBAL_NAMES` a dict and drop the `set(...)`.**
`_selfhost_module_scalar_globals` does `set(<the list>)`; over a dict global the
compiled path hands the dict pointer to `mojo_dict_iter_new`:

    mojo/middle/module_shared.py:194:29: error: passing argument 1 of
      'mojo_dict_iter_new' makes pointer from integer without a cast

Membership does not need the `set()` — `in` on the mapping is the same test —
but that only matters once the structure is a dict, and attempt 1 shows a dict
is not needed.

**4. The two structures are genuinely two questions.** "Is this one of ours?"
(membership: the skip and `_is_dispatch_name`) and "what C type does it have?"
(the declaration sites) are not the same fact, which is why one hand-written
list could not answer both correctly. The shape that survives all three
failures is a NAMES tuple plus a `name -> ctype` mapping covering exactly it,
with `assert set(MAPPING) == set(TUPLE)` at module scope in `types.py` so the
two cannot drift — attempt 1's mapping was correct and attempt 2 shows the
coverage must be complete, and the assert is what makes both true at once.

## Why this is not committed

Attempt 1 is a real fix to the reported symptom and is strictly more code
correct, but it turns a 35-error failure into a 97-error one, and I cannot
demonstrate from inside a merge that the 97 are closer to green — only that
they were previously hidden. Landing that in the tree would hand the next
person a red `selfhost` with a harder error list than the one that is easy to
read now. The patch is at `.tmp/selfhost-partial.patch` (regenerable, and
nothing else depends on it) and this doc records everything needed to rebuild it.

## Exact next step

1. Land the shape from attempt 4: keep
   `_DISPATCH_TABLE_GLOBAL_NAMES` a tuple of all 24 names for membership, add
   `_DISPATCH_TABLE_FORCED_CTYPES` covering exactly those 24 with each one's
   real type, and assert the two agree. Point the early-cdecl seed and the
   import declaration at the mapping. This reproduces the tree as of
   `.tmp/selfhost-partial.patch`.
2. Then work the 97 down. They are three classes, and they are the real content
   of this bug:
   * **`MojoSet *` <-> `int64_t` on the same global (20).** The home module's
     struct field and the IMPORTER's field disagree about whether a container
     global is a real pointer or the box. `_own_overlay_global_ctype` is the
     helper whose stated job is "a cross-module same-bare-name homonym can never
     make one side coerce with a different type than the other side declared",
     so it is the first place to look — rule 1 may need to consult
     `_module_global_field_type(module, name)` (the qualified-name counterpart,
     already present for exactly the `submod.NAME` spelling) rather than only the
     shared bare-name dict.
   * **"has no member named" (17).** Each names a global an importing module now
     reads through its OWN struct field. Either the field is not declared for
     that importer, or it is declared and the reference is emitted anyway.
     `_module_globals[mod]` is the single list the typedef, the initializer and
     the accessors are all generated from, so a name missing from it while the
     body references it is a bug in whichever of those three did not consult it.
   * **`_module_loader` (6), `_DISPATCH_TABLE_FORCED_CTYPES` (4).** An IMPORTED
     MODULE used as a value, and a module-level constant in `module_gen.py`
     itself. Same shape as the first class; check whether an import's own name is
     in the same tables the tables' contents are.
3. Re-verify with `test_selfhost.py`, then `make bootstrap` — the layer-2 errors
   are in the compiled closure and only a real stage-1/2/3 run can say whether a
   fix holds. This is why the change is not attempted inside a merge: the job
   that can answer the question is one a merge worker may not run.
