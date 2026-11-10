# CODEGEN_nested_def_class_capture_of_its_own_local

## Summary
A class declared inside a NESTED `def` whose method reads a binding that is
local to THAT SAME nested `def` is still captured by VALUE. Two wrong answers
follow, depending on where the binding is written:

```python
# (a) binding after the class statement: silent 0
def outer():
    def inner():
        class C:
            def get(self):
                return x
        x = 100
        print(C().get())      # CPython 100, this tree 0
    inner()

# (b) binding before, rebound after: REFUSED
def outer():
    def inner():
        x = 100
        class C:
            def get(self):
                return x
        x = 200
        print(C().get())      # CPython 200, this tree refuses:
                              # "reads `x`, ... which the enclosing function
                              #  rebinds, so a snapshot taken at the class
                              #  statement could differ ... silently answer 0"
    inner()
```

The same shape with a nested `def`'s own `global` declaration is silently
stale: `global G` + `G = 10` after the class prints the pre-assignment value
(`3`) instead of the global CPython reads at call time (`10`).

## Why this is the remaining half of the class-capture work
The by-reference class-capture pass
(`mojo/backend_gimple/module_gen.py::_gmi_capture_nested_class_enclosing_reads`)
walks the MODULE's top-level functions as `_ef`. A nested `def` appears in the
same walk as a class whose innermost-enclosing key is the lifted-name path
(`_ec_rel`, e.g. `inner`), but the two sets it decides ownership with are both
the OUTERMOST frame's:

* `_ef_bound` is `params + _gmi_local_binding_names(_ef.body)`, which
  deliberately over-approximates through nested defs, so `x` (owned by
  `inner`) IS a candidate;
* `_ef_own` is `bound_name_set(_ef.body)`, which does NOT recurse into nested
  defs, so `x` is NOT own to `_ef` and the capture stays on the by-VALUE cell
  (`_cap_x = x` at the `class` statement).

`discover_closures` then prunes `_class_ref_pending[lifted]` to the names the
lifted function captures FROM ITS ENCLOSING SCOPE (`ci.captures`), so an
`inner`-owned name is dropped there too, exactly as a shadowing local must be
for the OUTER-owner case. The machinery has no notion of "owned by the
lifted function itself".

The OUTER-local half of this family (a class in `inner` reading `outer`'s
local) is fixed by `codegen: late-bind class captures through a nested def`;
this doc is the other half, and it was never in that doc's scope. The direct
(cardinal) shape is fixed by `codegen: class methods capture enclosing locals
by reference`, and the DIRECT `global` spelling by `codegen: leave
globally-declared names uncaptured by class methods` (commit 65d736e32);
neither fix reaches a binding that belongs to the nested `def` that writes the
`class` statement.

A `global` declaration in that nested `def` is the same decision one step
weaker: the name is not a local at all, so it must not be captured. It is
still in `_ef_bound` (the over-approximation sees the assignment), and the
by-value cell snapshots the module global at the `class` statement.

## Reproduce
Through `test_gimple_runner.compile_mojo_to_gimple_exe` on this branch
(`work/bug-codegen-class-rebind-late-binding-r29`):

* case (a): compiled `0\n`; CPython `100\n`.
* case (b): `RuntimeError: ... reads `x`, ... which the enclosing function
  rebinds, so a snapshot taken at the class statement could differ ...`.
* nested global: compiled `3\n`; CPython `10\n`.

Not covered by any existing test: `gimple_nested_class_inside_nested_def_
shadows_outer_capture` reads its inner local BEFORE the class statement and
before the rebind, so the by-value snapshot and CPython agree (`100`). The
tests that do pin late binding (`..._late_binds`, `..._sees_later_rebind`) put
the local in the OUTER function.

## Next step
Carry the CLASS-DECLARING frame, not just the outermost one, through the
capture walk, and decide by-reference ownership against it:

1. `_gmi_nested_struct_defs` (`mojo/middle/exprtypes.py`) already carries the
   innermost enclosing `params` in slot 2 of each `[node, enclosing, params]`
   entry. Add the innermost `FunctionDef` as a fourth slot (append-only; every
   existing consumer indexes `[0]`/`[1]`/`[2]`), passing `_nc` when it
   recurses into a nested `def` and `_ncm` for a method body. In
   `_gmi_capture_nested_class_enclosing_reads`, pass `_ef` for the top call.
2. In that pass compute the declaring frame's own set
   (`params | bound_name_set(scope.body)`) and its `global_declared_names`
   (both are in `mojo/middle/boundnames.py`; the global set is what the direct
   fix in this branch uses to leave a module global UNCAPPED).
3. By-reference is then `name in _ef_own OR name in _declaring_own`, and a
   declaring-frame `global` name is excluded from `_caps` entirely. Keep the
   `_ef_own` alternative: it is the OUTER-owner path whose box travels through
   the lifted function's env.
4. `discover_closures` must not PRUNE a `_class_ref_pending[lifted]` entry
   that is owned by the lifted function itself. The parent's scan currently
   replaces the list with the intersection with `ci.captures`; keep the
   self-owned names in a separate part of the entry (or a parallel set) so
   the lifted function's own scan can type and publish them, and
   `_seed_mut_captured_local_types(lifted)` boxes them. `_gmi_apply_class_ref_
   types` already accepts a non-direct entry whose name is published in
   `_class_ref_locals[lifted]`.
5. `_gen_stmt_StructDef`'s by-reference branch already installs the box for a
   name in `_boxed_mut_locals` of the EMITTING function, which is exactly the
   lifted frame; no emitter change is expected, but verify the cell/typedef
   three-way agreement there.
6. Regression tests beside `gimple_nested_class_inside_nested_def_capture`:
   case (a) prints `100`, case (b) prints `200`, an instance built before the
   rebind prints the new value, the nested `global` case prints `10`, and the
   existing shadow-outer case still prints `100`.

A cheaper alternative for step 1/4 (box the inner local in the lifted
function without threading an owner) was rejected in the deleted OUTER-local
doc for the env-ownership reason; here the box genuinely belongs to the lifted
frame, so it is the ownership PLUMBING that is missing, not the storage.
