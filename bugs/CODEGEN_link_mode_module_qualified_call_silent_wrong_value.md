# CODEGEN (link-mode): a CALL through an imported module marker
# (`module.func(...)`) silently returns the wrong value

## Discovered 2026-08-28, via `test_link_mode.py` (the new link-mode
## regression suite added alongside the asyncio/futures.py link-mode fix)

Real link-mode (`driver.compile_program`, the actual default `mojo.py
build` pipeline — NOT the `do_imports=False` inline path every other
gate step, including `compile_stdlib.py`, exercises) silently returns
the WRONG VALUE (not a compile error, not a crash) on this shape:

```python
# pkg2/base2.py
def doubleval(x):
    return x * 2

# pkg2/main.py
from . import base2
print(base2.doubleval(21))
```

Builds clean (exit 0), runs clean (exit 0), prints `0` instead of `42`.

Root cause: `gimple_gen_methods.py`'s `_lower_method_call` has
special-cased dispatch for a handful of hardcoded compiler-internal
module names (`ast_rewriter`, `mlir`, `regex_compile`) that resolve a
module-qualified call to the real compiled function via
`gen._func_csym(method_name)` / `gen._call_expr(...)`, but no GENERIC
case for an arbitrary imported module. A call through any other module
marker falls through to the generic dynamic-dispatch fallback, which
for an opaque `int64_t` module-marker receiver resolves against
unrelated builtin scalar-type method stubs (confirmed via the
generated `.ci`: `base2.doubleval(21)` with the method renamed to the
colliding builtin name `double` emitted `_t4 = _t2; /* int64_t.double()
stubbed */` — an accidental match against a completely unrelated
builtin numeric-cast stub) instead of ever reaching the real compiled
function.

## Attempted fix REVERTED 2026-08-28 — real self-hosting regression

A generic version of the same resolution `_lower_MemberExpr`'s sibling
value-read case already uses (`module_name in gen.imported_symbols and
method_name in gen.func_return_types`) was implemented, firing
`_func_csym`/`_call_expr` for ANY imported module instead of the 3
hardcoded names. It fixed the repro above (verified: prints `42`) —
but **broke `make check-selfhost`**: `mojo_compiler.py`'s own `re.compile(
...)` call got mis-routed to a DIFFERENT, unrelated 2-argument
`compile` function elsewhere in the self-hosted source (`error: too few
arguments to function 'compile_abb124'; expected 2, have 1`, in
`mojo_compiler.py` and `gimple_ctypes.py`).

Root cause of the regression: `gen.func_return_types` is a single FLAT
dict keyed by bare method name only, with NO module qualification —
exactly the same known hazard `bugs/hard/CODEGEN_same_bare_name_struct_
collision_across_modules.md` already documents for a different call
shape. The 3 hardcoded cases (`ast_rewriter.rewrite`, `mlir.type_to_c`,
`regex_compile.compile_pattern`) are safe only because those specific
method names happen not to collide with anything else in this
compiler's own self-hosted source — a bare-name lookup is NOT safe to
generalize to arbitrary method names (`compile`, `read`, `open`, ... —
exactly the common, collision-prone names real code uses).

**Not re-attempted this pass.** A safe fix needs module-QUALIFIED
symbol resolution — e.g. mirroring `gimple_ctypes._join_import_member`
(already used elsewhere for exactly this "same bare name, different
module" disambiguation) so the lookup key encodes which module's
`doubleval`/`compile`/whatever is meant, not just the bare name. This
is real, scoped follow-up work, not a same-session narrow fix.

`test_link_mode.py`'s `test_bare_submodule_import_call_KNOWN_BUG` pins
this exact repro and expects the wrong-value bug (`rc == 0, stdout ==
'0'`) — when this doc is closed, that test's expectation (and its
`_KNOWN_BUG` suffix) must be updated to expect `'42'`, not just
deleted.

## Repro

```
mkdir -p /tmp/repro/pkg2
touch /tmp/repro/pkg2/__init__.py
cat > /tmp/repro/pkg2/base2.py <<'EOF'
def doubleval(x):
    return x * 2
EOF
cat > /tmp/repro/pkg2/main.py <<'EOF'
from . import base2
print(base2.doubleval(21))
EOF
cd /tmp/repro && python3 <path-to-mojo-reference>/mojo.py build pkg2/main.py && ./main
# Built: .../main
# 0        <- should print 42
```
