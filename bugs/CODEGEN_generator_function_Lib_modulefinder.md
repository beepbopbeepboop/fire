# CODEGEN_generator_function: Lib/modulefinder.py

## Status (updated 2026-08-10 — general tuple-valued yield now FIXED; `scan_opcodes`'s specific NESTED-tuple shape remains a distinct, still-refused sub-case)

Implemented real tuple-valued-`yield` support this session (`yield a,
b, ...` boxes into a real `MojoList *` at the yield site — see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). `scan_opcodes` is STILL refused, correctly — its shape is a
DISTINCT, deeper sub-case this fix deliberately does not cover:

```python
yield "store", (name,)
yield "absolute_import", (fromlist, name)
yield "relative_import", (level, fromlist, name)
```

Each of these is a tuple whose SECOND element is ITSELF a nested tuple
literal (varying inner arity: 1, 2, then 2 elements). `_cpp_expr`
lowers a bare tuple/list/dict/set literal to a raw C++ braced-init-list
(`{name}`), which is not a valid argument to `mojo_list_append_int/
_double/_str` (nor castable to any of those types) — attempting to box
it anyway would reproduce this family's ORIGINAL malformed-C++ failure
mode one level deeper. This session's fix added an explicit guard for
exactly this (`_generator_yield_ctype`'s `TupleExpr` branch now refuses,
via `return None`, whenever any element of the tuple is itself a
`TupleExpr`/`ListExpr`/`DictExpr`/`SetExpr`) — confirmed via a direct
repro (`yield "store", ("name",)`) that this now produces the same
clean, honest Python-level refusal `scan_opcodes` already got, not a
GCC-stage syntax error.

Recursive/nested tuple-element boxing (and, separately, the outer
tuple's own arity varying if it did) is out of this fix's scope — see
the task's "yield tuples with a FIXED, small element count" scope
boundary. Doc kept open (not deleted) — `scan_opcodes` remains
refused, now for a more precisely diagnosed reason.

## Status (updated 2026-08-09 — RECLASSIFIED: `scan_opcodes`'s tuple-valued yield is now the blocking error)

Re-verified against current master (`5ba7d4b`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/modulefinder.py`.
The build now fails immediately, before reaching any GCC-stage error
(i.e. before the `_quick_type` fix documented just below even gets a
chance to matter), on a hard Python-level `RuntimeError` from
`gen_module` (`gimple_codegen.py:30968`):

```
Error building: cannot compile module: function(s) scan_opcodes
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

This is exactly the tuple-of-heterogeneous-arity-yield shape the
2026-08-06 section below already identified in `scan_opcodes` (lines
393-403: `yield "store", (name,)` / `yield "absolute_import", (fromlist,
name)` / `yield "relative_import", (level, fromlist, name)`) — confirmed
again by re-reading the source. This is the same well-known,
already-tracked structural gap as `ipaddress.py`'s `_find_address_range`
and `mailbox.py`'s `iteritems` (see those bug docs' 2026-08-09 updates):
coroutine promises only support a single scalar, and
`_infer_generator_yield_ctype`'s `TupleExpr` branch at
`gimple_codegen.py:2699-2724` now honestly refuses rather than
mis-emitting broken C++.

This supersedes the "ONE error remained" claim in the 2026-08-07 section
below: that section's testing was done when `scan_opcodes` was
apparently still eligible under a weaker tuple-yield check (or wasn't
yet reached before other passes ran), so the module compiled far enough
to hit the `find_all_submodules` `_quick_type` bug and the `self.msg`
`*args` bug at GCC stage. A later session's work (visible in current
`gimple_codegen.py`) tightened the tuple-yield eligibility check, so
`scan_opcodes` now correctly aborts the whole-module compile before
either of those two are reached.

**The `_quick_type` `.keys()`/`.values()`/`.items()` fix described below
is still landed and still correct** (verified present in current
`gimple_codegen.py`'s `_quick_type`, around the `CallExpr`-on-`MemberExpr`
branch) — it's just no longer the *blocking* error for a full-module
build of this file, since `scan_opcodes`'s tuple-yield refusal now fires
first. **Classification: matches the tracked "tuple-valued yield"
structural generator-codegen gap** — out of scope for a narrow fix per
this task's guidance. Not attempted here.

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
