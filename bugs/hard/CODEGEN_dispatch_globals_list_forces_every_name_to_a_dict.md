# `selfhost`: the dispatch-globals list forced every name to `MojoDict *`

## Status: the reported defect is FIXED; the layer it was masking is 11 errors
## from green and is four further defects, each filed separately.

`python3 tools/suite.py selfhost` still fails, but not for the reason this doc
was written for. The four `# ERROR: compiling imported module ...` lines are
gone, `gimple` / `modcache` / `linkmode` are green, and the self-host build's
own gcc error count went **35 -> 11**. What is left is listed at the bottom,
with a bug doc each.

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

    python3 tools/memslot.py --gb 8 --label sh-build -- python3 .tmp/sh_build.py
    cd .tmp/sh && sed 's/^#line .*$//' fire.ci > fire_nl.ci
    /opt/local/bin/gcc-mp-15 -x c -fsyntax-only -fgimple -w -std=gnu11 \
        -I<repo>/runtime fire_nl.ci 2>&1 | grep 'error:'

where `.tmp/sh_build.py` is `fire.build_executable(<repo>/fire.py, src,
output=<repo>/.tmp/sh/mojo_selfhost)` run with the cwd set to `<repo>/.tmp/sh`
(the writer puts `mojo.{ci,o}` in the CWD). Every count below is from that
pass, and they are strictly comparable to each other.

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

## What is left, and where it is filed

Eleven errors, in four further defects, each with its own doc:

* `bugs/CODEGEN_closure_env_struct_omits_a_captured_field.md` — 2 errors.
  `gen_module_impl`'s merged closure env
  (`gen_module_impl__is_foreign_main__mk_round_env`) declares three captured
  fields and both the allocator and the body write a fourth, `self`.
* `bugs/CODEGEN_selfhost_annotated_init_field_typed_as_the_receiver.md` — 1
  error. `fire_compiler.py`'s `self._comptime_rhs_failures: list = []` inside
  `Parser.__init__` gives the struct field the type `struct Parser *`.
* `bugs/CODEGEN_myinterpreter_star_args_call_passes_kwargs_twice.md` — 2
  errors. `myinterpreter_MojoFunction___call__` is declared `(MojoFunction *,
  MojoList *, MojoDict *)` and called with FOUR arguments; the 5 "non-trivial
  conversion" errors in the same four `myinterpreter` functions are the same
  investigation's other half.
* `bugs/CODEGEN_compute_exc_descendants_call_site_return_temp_is_the_box.md` —
  1 error. The call `self._exc_descendants =
  _compute_exc_descendants(all_struct_defs)` declares its result temp `int64_t`
  while the definition and the table both say `MojoDict *`.

## Re-verify with

`test_selfhost.py`, then `make bootstrap` — the residual errors are in the
compiled closure's own bodies, and only a real stage-1/2/3 run says whether a
fix to them holds.