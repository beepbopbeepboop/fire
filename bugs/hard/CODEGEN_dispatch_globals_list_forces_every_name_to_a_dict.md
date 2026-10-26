# `selfhost`: the dispatch-globals list forced every name to `MojoDict *`

## Status: FIXED, and so is every defect it was masking — the self-host
## closure's generated C compiles with **0** gcc errors and `selfhost` is
## green. 2026-10-03, `work/merge-bugs3-r4`.

`python3 tools/suite.py selfhost` passes: it self-compiles, LINKS, and the
produced binary compiles a two-line program to a 27 KB `.ci`
(`test_selfhost.py`'s `run_produced_binary`). The error count went
**35 -> 11 -> 0**, the 11 having been four further defects whose docs are
deleted and whose fixes are one commit each on that branch:

| errors | root cause | fix |
|---|---|---|
| 2 | a shared closure-env struct's field list was a per-member COPY, and the typedef is emitted from whichever member comes first | `mojo/middle/closures.py`, one shared list object per call group |
| 1 | `_emit_call`'s `imported_symbols` text-scan guess outranked the pinned `_SELFHOST_SIGS` answer | `mojo/backend_gimple/emit_infra.py`, the cascade now skips names the pinned table lists |
| 6 | the `s.fields` "don't know" placeholder `<Cls> *` outranked a `self.X = ...` assignment's evidence | `mojo/backend_gimple/module_gen.py`, `can_override` fires for it too |
| 2 | `_func_kwargs_slot['MojoFunction___call__']` was the index for the OLD `(self, interpreter, *args, **kwargs)`, so the vararg merge packed one positional too few | a module-level `_SELFHOST_KWARGS_SLOTS` beside `_SELFHOST_SIGS`, checked from `inspect` in `test_gimple.py` |

One further defect was behind the 0-byte `.ci` that survived all eleven: a
`**expr` pair in a dict literal was stored as a dict KEY instead of merged, and
this compiler's own `emit_infra.py::_reset_func` seeds `gen._dict_val_types`
with one. Fixed in `mojo/backend_gimple/emit_exprs.py` and pinned by
`test_gimple.py`'s `dict_literal_star_star_pair_merges_instead_of_storing`.

**This file survives the fixes on purpose.** CLAUDE.md deletes the doc of a
fully fixed bug, and the defect above is fully fixed — but what is left here is
the one place the measurement recipe is written down, and it is what made the
eleven tractable at all (below). Anyone changing the compiled path needs it;
keep it, and keep the recipe in step with the tree.

## What I ran

Merging the `bugs3` batch, `selfhost` was red on the branch and green at the
base commit `d0796643`:

    python3 tools/suite.py selfhost
    # FAIL  selfhost  (110s)  exit 1

    python3 tools/memslot.py --gb 8 --label selfhost -- python3 test_selfhost.py

    # ERROR: compiling imported module 'module_loader' from .../module_loader.py:
    #   cannot coerce MojoSet * to MojoDict * (incompatible container kinds)
    #   at .../module_loader.py: value='_t56' dest='_t57'
    # ERROR: compiling imported module 'generated_dispatch' ...
    # ERROR: compiling imported module 'mojo.middle.types' ...
    # ERROR: compiling imported module 'gimple_codegen' ...
    # ✗ self-host compile/link regressed

Base reports `Results: 2 passed, 0 failed`. 35 gcc errors at the merged tip.

`mojoc` fails with the **identical four lines** — it builds the same self-host
closure — so this was one defect behind two registered jobs, and
`bootstrap-stage2-cc` was blocked behind it rather than independently broken
(its registered dep is `bootstrap-stage1-transitive`, which needs the stage-1
dumps, which need the self-hosted binary neither of the two could produce).

## How it is measured now

The self-host build takes ~110 s and its errors report PYTHON line numbers,
because the generated `.ci` is full of `#line` directives pointing back into
the compiler's own sources. To iterate on the second layer, keep the artifact
and compile it separately with the directives stripped, so gcc reports
GENERATED line numbers and a 30 s syntax-only pass replaces the 110 s build:

    python3 tools/memslot.py --gb 8 --label sh-ci -- python3 -c \
      "from gimple_codegen import compile_to_gimple_cached; \
       open('.tmp/sh/fire.ci','w').write(compile_to_gimple_cached(\
       open('fire.py').read(), do_imports=True, filename='fire.py'))"
    cd .tmp/sh && sed 's/^#line .*$//' fire.ci > fire_nl.ci
    /opt/local/bin/gcc-mp-15 -x c -fsyntax-only -fgimple -w -std=gnu11 \
        -I<repo>/runtime fire_nl.ci 2>&1 | grep 'error:'

The first step is the codegen half of `fire.build_executable` verbatim, and it
is now written out rather than left as a side effect: `build_executable` puts
its `.ci`/`.o`/`_gen.cpp` intermediates in a private scratch directory beside
the artifact and DELETES it on every return path, because they were named off
a bare module basename and used to land in the process's CWD — two builds of
two modules sharing a basename overwrote each other's `gen.ci` with no lock,
and `tools/suite.py` runs `-j18` out of a common checkout. The call was
`fire.build_executable(<repo>/fire.py, src,
output=<repo>/.tmp/sh/mojo_selfhost)` run with the cwd set to `<repo>/.tmp/sh`
and the recipe then read `fire.ci` out of that cwd; the artifact it left
behind was the only reason the cwd mattered. ~2m45s / 1.3 GB, and the result is
the same 42 MB `.ci`. Every count below is from that syntax-only pass, and they
are strictly comparable to each other.

## Root cause, and the fix

`e98ea1f8` / `939843ee` ("One list for the dispatch globals, because four
hand-written copies stopped agreeing when they moved module") collapsed four
hand-written copies of the same fact into one list. **All four copies held the
same EIGHT names** — `_STMT_DISPATCH`, `_EXPR_DISPATCH`, `_BIN_OPS`,
`_TYPE_MAP`, `_SIGNED`, `_UNSIGNED`, `_FLOAT` (dict) and `_CMP_OPS` (set) — and
the consolidation rewrote the list's contents to TWENTY-FOUR while
deduplicating. Three sites then answered a name from that list with a blanket
type, and the list no longer distinguished dict from set:

| site | before | after |
|---|---|---|
| `module_gen.gen_module_impl` early cdecl seed | `_EARLY_DISPATCH_DICTS` / `_EARLY_DISPATCH_SETS` (7 + 1) | `_EARLY_DISPATCH_DICTS = set(all 24)`, `_EARLY_DISPATCH_SETS = set()` — every name `MojoDict *` |
| `module_gen.gen_module_impl` import declaration | `_dispatch_dict_names` / `_dispatch_set_names` (7 + 1) | `_dispatch_dict_names = list(all 24)`, fallback `or 'MojoDict *'` |
| `module_gen.gen_module_impl` non-literal RHS | `'_CMP_OPS'` vs everything else | one name right out of twenty-four |

A fifth copy — `gimple_codegen.GimpleGen._own_overlay_global_ctype` rule 4's
exclusion tuple — was still the ORIGINAL eight, so every one of the sixteen
names the consolidation added was excluded by a list that never heard of it.

Ten of the added names are `frozenset`s and one (`_CMP_OPS`) is a set
(`generated_dispatch.py` declares `_CMP_OPS: set`), so "a dispatch table is a
dict" is wrong for all ten. Two more are dicts, two are plain strings and one
is a compiled regex.

The failure needed one more ingredient, and it is why this was a build error
rather than a misprint: the answer is written into the SHARED, bare-name-keyed
`_global_c_decl_types`, and `_own_overlay_global_ctype`'s rule 1 says "a
CONTAINER cdecl beats a scalar own-conclusion". So module_loader's own
set-valued `_C_KEYWORDS = frozenset({...})` (module_loader.py:13) found
`_global_c_decl_types['_C_KEYWORDS'] == 'MojoDict *'` and coerced to it.
Measured at the assignment site:

    _global_c_decl_types['_C_KEYWORDS'] = 'MojoDict *'
    _own_global_var_types['_C_KEYWORDS'] = 'MojoSet *'      <- the owner's own answer
    _global_dst_ctype('_C_KEYWORDS')      = 'MojoDict *'

**The fix.** `_DISPATCH_TABLE_GLOBAL_NAMES` (a tuple of names) becomes
`_DISPATCH_TABLE_GLOBAL_CTYPES` (a `name -> ctype` mapping, each name's real
container kind read off its own definition) plus ONE accessor,
`dispatch_table_global_ctype()`, whose `... is not None` is also the one
membership test. A name list and a parallel type list can disagree and that
disagreement has now been a build break twice; a single mapping cannot. It is a
FUNCTION and not a bare read of the dict at each call site because these sites
are in other modules, and a module-level `tuple(<dict>)` / `set(<tuple>)`
derived view of the table does not survive the self-hosted compiled path at
all ("passing argument 1 of 'mojo_list_len' makes pointer from integer without
a cast") — see the accessor's own docstring.

### The three shapes the consolidation had not tried, and why each is not the fix

Recorded because each fails in a way that is informative. (1) carrying the type
in the list removes all four `cannot coerce` lines but takes the build from 35
errors to 97; (2) narrowing the list back to eight names is much worse, 99
errors, because the importer's declaration site declares each listed name as a
field of the IMPORTING module's own globals struct and the generated code
reads it back through that field — so dropping a name stops declaring the
field (`'struct _mojo_middle_exprtypes_toplev' has no member named
'_CPP_CALLABLE_CTYPE'`); (3) making the names list a dict and dropping the
`set(...)` hands the dict pointer to `mojo_dict_iter_new`
(`mojo/middle/module_shared.py:194`). The shape that survives all three is a
mapping whose keys ARE the membership set, which is what landed.

## The layer the four `# ERROR` lines were masking

Correctly typed, `module_loader`, `generated_dispatch`, `mojo.middle.types` and
`gimple_codegen` compile far enough for gcc to see their bodies — which it
never did, because a failed nested-module compile rolls back to source
inclusion (`emit_resolve.py`'s `except` around `_compile_imported_module`).
So the errors went 35 -> 71, and four independent defects came out. All four
are pre-existing and all four are reachable only through that rollback:

1. **The home module's field disagreed with every importer's (26 errors).**
   `_gscan_declare_global` consulted the table only from its DictExpr /
   ListExpr / SetExpr rows, so `module_loader.py`'s `_C_KEYWORDS =
   frozenset({...})` — a CALL — never reached one, fell through to the generic
   int64_t fallback, and declared `int64_t _C_KEYWORDS` in
   `_module_loader_toplev` while `gimple_codegen`, `module_gen` and
   `module_shared` all declared the same name `MojoSet *`. Every bare read is
   a direct `_<mod>_globals.<name>` load typed from `_global_var_types`, so the
   mismatch is one `-Wint-conversion` per read, in both directions. Fixed by
   one shared helper (`_gmi_declare_table_global`) at the TOP of both
   declaration scans, with the four per-RHS-shape guards deleted rather than
   kept in step.

2. **The from-import declaration site decided the field for the whole module
   (5 errors).** It runs BEFORE the AssignStmt/VarDecl scans, so what it writes
   into `_declared_globals` stops them re-deriving the name — and it preferred
   `_global_var_types`, which for an alias RHS (`_BIN_OPS = _GD_BIN_OPS`) is
   the useless `int64_t` the Phase-1.7 scan could not resolve. Both
   `_mojo_middle_types_toplev` and `_gimple_codegen_toplev` declared
   `int64_t _BIN_OPS` where the toplevel body then stored the accessor's real
   `MojoDict *`. Fixed by routing it through the same helper.

3. **A bare read of a FROM-IMPORTED global loaded this module's own struct
   (32 errors).** `build_stdlib_dylib.py` has `from module_loader import
   load_module, STDLIB_PATH, module_name_for_path` at module level and reads
   `STDLIB_PATH` bare inside `stdlib_modules()`; but only a module's OWN
   top-level assignments become struct fields, so the read emitted
   `_build_stdlib_dylib_globals.STDLIB_PATH`. Same for `TEST_PATH` in
   `build_config`, `_BUILTIN_RET_CTYPES` in `module_shared`/`resolve_shared`,
   `_module_loader` in `emit_infra`/`emit_funcs`/`funcs_shared`, and
   `_BIN_OPS` / `_TYPE_MAP` / `_FIXED_ARRAY_ANN_RE` — the last three because
   `_lower_MemberExpr` deliberately lowers `gimple_ctypes.X` as a BARE `X`
   ("the qualifier is a Python-import artifact"), in modules that reached
   `mojo.middle.types` with `import ... as gimple_ctypes` and so never ran the
   from-import declaration site at all. Fixed in `_lower_IdentExpr`'s
   global-read branch by asking `_module_global_field_type` which module
   actually declares the name and loading THAT module's field, with the field's
   own declared type — the authority the `submod.GLOBAL` branch already used.

4. **Two stale signatures and one shadowed local (3 errors).**
   `_SELFHOST_SIGS['_compute_exc_descendants']` claimed `int64_t` for a
   function that builds and returns a dict, and because that free function's C
   name is unmangled every self-host fragment declares it, so a stale entry is
   a hard "conflicting types" rather than the coercion imprecision the rest of
   that table tolerates. And `gen_module_impl`'s
   `for _mgk in self._module_globals:` rebinds the very slot
   `_mgk: set = set()` (the `_multi_kind_globals` local) had declared
   `MojoSet *`.

Counts: 35 at the merged tip, 71 after the mapping, 53 after (1), 18 after
(2)+(3), 11 after (4).

## What was left, and where it went

The section this replaces recorded the eleven as four open defects with four
docs. All four are fixed, their docs are deleted with the fixes, and the table
at the top names each root cause and the commit that closed it. Kept here only
so the sequence is readable in one place; nothing in it is still open.

## Re-verify with

The recipe in "How it is measured now" above, then `test_selfhost.py`. It
reports 0, and `python3 tools/suite.py mojoc selfhost bootstrap-stage2-cc
gimple` is green — `mojoc` and `selfhost` build the same closure and
`bootstrap-stage2-cc` compiles it, so all three are the same measurement by
three routes.

Note the two traps that recipe exists to avoid, both of which cost time here:
`.ci` is 42 MB with a 22 MB `#line`-stripped copy, so regenerating it is ~2
minutes and the syntax-only pass over the stripped copy is ~1.3 seconds (a
30-minute `mojoc` per attempt is not needed), and the stripped copy has to be
re-derived from the `.ci` each time — reusing a stale one silently reports the
previous run's error list at the previous run's line numbers.