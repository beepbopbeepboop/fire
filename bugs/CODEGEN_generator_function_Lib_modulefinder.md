# CODEGEN_generator_function: Lib/modulefinder.py

## Status (updated 2026-08-07 — `_quick_type` `.keys()`/`.values()`/`.items()` case FIXED)

Re-verified against current master: the `struct _subprocess_toplev`/
`struct _genericpath_toplev` errors quoted below are already gone
(fixed by `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md`'s "mechanism 2" landing since 2026-08-06). Only ONE error
remained: `modulefinder.py:296:1: error: invalid conversion in return
statement` — still well outside the generator (`scan_opcodes`, lines
393+), inside `find_all_submodules`:

```python
def find_all_submodules(self, m):
    if not m.__path__:
        return                      # bare return -> void/None
    modules = {}
    ...
    return modules.keys()           # MojoDict *.keys() -> MojoList * (real)
```

**Root cause: another `_quick_type` return-type-estimator gap, same
family as `bugs/hard/CODEGEN_comprehension_return_type_defaults_
int64.md` (task #145).** `_quick_type` (gimple_codegen.py:6691, the
project-wide return/expression-type estimator that populates forward-
declared function return types via `_collect_return_types`/
`_infer_return_type`, Pass 2b) had NO case at all for a `.keys()`/
`.values()`/`.items()` method call — the real lowering
(`_lower_dict_method`, gimple_codegen.py:11406) correctly returns a real
`MojoList *` (`mojo_dict_keys`/`_values`/`_items`) for all three, but
the pre-pass fell all the way through to the `int64_t` default,
producing a wrong `int64_t` forward declaration against a body that
really returns a pointer — the exact "non-trivial conversion"/"invalid
conversion" class of `-fgimple` refusal this family of bugs always
produces.

**Fixed** in `_quick_type`'s `CallExpr`-on-`MemberExpr` branch
(gimple_codegen.py, right before the "Try as struct instance method
call" fallback): added
```python
if meth in ('keys', 'values', 'items') and not node.args:
    return 'MojoList *'
```
Deliberately UNCONDITIONAL on the receiver's own known type (unlike a
first attempt gated on `self.var_types.get(mod) == 'MojoDict *'`, which
did NOT work — `_collect_return_types` runs BEFORE a function's own
local variable types are recorded into `self.var_types`, so `modules =
{}` earlier in the SAME function body being scanned is invisible at
this point; same documented blind spot as the `.read()`/`.readline()`
case a few lines above it in the same method). Instead treated the same
way that block already treats `.strip()`/`.lower()`/etc. — unconditional
because `.keys`/`.values`/`.items` are dict-view-only method NAMES in
this codebase's supported Python subset (no other builtin container
type has them), so blind-trusting the method name alone is safe by the
same reasoning already established there.

**Verified fixed**: isolated compile
(`compile_to_gimple_with_cpp(..., do_imports=False)`) now declares
`MojoList * ModuleFinder_find_all_submodules(...)` (was `int64_t`), and
the original `:296:1` GCC error is gone from both the isolated compile
and the full `python3 mojo.py build .../modulefinder.py` re-run.

**Remaining, NOT fixed (out of scope, matches an already-deferred hard
bug)**: 2 new-visibility errors at line 284 (`passing argument 3 of
'ModuleFinder_msg' makes pointer from integer without a cast`) —
`def msg(self, level, str, *args):` called as `self.msg(2, "can't list
directory", dir)`. This is the `*args`-parameter-signature shape
`bugs/hard/CODEGEN_args_kwargs_signature_assumed_forwarding_only.md`
(task #142) already covers and this task's guidance explicitly holds
back — not attempted.

### Gate verification for this fix

- `python3 test_gimple.py`, `python3 test_module_cache.py`: see combined
  end-of-session gate run (all passing, 0 failed).
- `make check-selfhost`: passing.
- From-scratch stdlib dylib rebuild: 0 `skip <module>:` lines (same as
  baseline).
- `python3 compile_stdlib.py -j8`: 664/664, 0 unexpected failures (same
  as baseline — this fix does not change the count, since
  `Lib/modulefinder.py` was already not part of the 664-file corpus
  compile_stdlib.py tracks; verified via the shared end-of-session run
  covering all fixes made in this session together).

## Status (updated 2026-08-06, superseded above — struct_toplev errors since independently fixed)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'dis' was not declared` .cpp error no longer reproduces.
`modulefinder.py` has one generator, `scan_opcodes` (lines 393-403,
`yield "store", (name,)` / `yield "absolute_import", (fromlist, name)` /
`yield "relative_import", (level, fromlist, name)` — a tuple-of-
heterogeneous-arity yields). It does NOT appear anywhere in the current
error list and `MOJO_DEBUG=1` shows no "not eligible" refusal naming it
— `scan_opcodes` now appears to compile cleanly through the coroutine
path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Every current error is well before the generator (lines 89-343, vs. the
generator at 393+) and is the same recurring pattern seen in
`Lib/glob.py`'s current re-diagnosis:

```
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:89:30: error: invalid use of undefined type 'struct _subprocess_toplev'
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:282:30: error: invalid use of undefined type 'struct _genericpath_toplev'
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:296:1: error: invalid conversion in return statement
```
`struct _subprocess_toplev`/`struct _genericpath_toplev` are opaque
per-module "namespace" pseudo-structs this codegen emits for whole-module
attribute access (e.g. `subprocess.something`) — used here but apparently
never given a matching full definition, a module-attribute-access gap in
the same spirit as (though a different concrete shape from) dyld.py's
already-documented bullet 4 ("module attribute access not threaded into
generator scope"), except this occurs in ORDINARY (non-generator) code,
well outside `scan_opcodes`'s own body. Not investigated further — out
of scope for this generator-codegen cluster; worth a `struct _X_toplev`-
focused non-generator bug report on its own (recurs identically in
`Lib/glob.py`'s current error list too — see that file's bug doc).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/modulefinder.py
