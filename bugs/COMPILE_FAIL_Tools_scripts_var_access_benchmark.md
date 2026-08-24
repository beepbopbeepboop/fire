# COMPILE_FAIL: Tools/scripts/var_access_benchmark.py

Source file: `/Users/mrs/net/Python-3.14.6/Tools/scripts/var_access_benchmark.py`

(Found via full Python-3.14.6 source tree scan, not the earlier 100-file Lib/ sample.)

## Status (2026-08-23): re-verified — STILL-OPEN, byte-identical to the 2026-08-09 state.

Re-ran against current code (branch `fix/tools-misc` @ `c16c05c`): exactly the
same two errors in `read_classvar_from_instance_d4d5c5`
(`'_t5' undeclared ... did you mean '_t4'?`, `'a' undeclared`) and the same
root cause documented below (parameter `A` shadowing the C `typedef struct A A;`
in a shared namespace). Structural per that analysis; not attempted.

## Status (updated 2026-08-09, historical — superseded header only)

Re-ran against current `master`. Of the two issues this doc previously
tracked, one is now confirmed FIXED by unrelated prior work this session;
the other is real-rooted and STRUCTURAL — not fixed.

### 1. `'MojoBoundMethod' has no member named '__name__'` — FIXED

This was already tracked as a confirmed real-world instance in
`bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md` ("More
real-world instances confirmed 2026-08-06": `inner.__name__ =
'read_nonlocal'` plus a separate `f.__name__` read, both on
`MojoBoundMethod` values). That doc's Steps 1-4 (real per-object dynamic-
attribute storage + routing `MojoBoundMethod`/`MojoGenerator`/`MojoAsync`
through it) landed and were verified 2026-08-07, and this file was one of
its own confirmed-instance verification rows (0 "structure or union"/"has no
member named" errors afterward). Re-confirmed here: current `mojo.py build`
output no longer contains this error at all.

### 2. `'_t5' undeclared` / `'a' undeclared` — STRUCTURAL, root-caused, NOT fixed

Current error:
```
var_access_benchmark.py:91:7: error: '_t5' undeclared (first use in this function); did you mean '_t4'?
var_access_benchmark.py:92:7: error: 'a' undeclared (first use in this function)
```
in `read_classvar_from_instance_d4d5c5` (the C name for
`read_classvar_from_instance`).

Root cause, fully identified via direct `.ci` inspection (previously marked
"not root-caused further" — now is): the source is

```python
class A(object):
    def m(self):
        pass
...
def read_classvar_from_instance(trials=trials, A=A):
    A.x = 1
    a = A()
    for t in trials:
        a.x; a.x; a.x; ...
```

**The function parameter is named `A` — identical to the global class `A`
it defaults to.** This is a real, if unusual, Python idiom (deliberately
shadowing a global name with a same-named parameter/default, presumably here
so the benchmark measures "read a global vs. read a local" access patterns
uniformly across sibling functions). It's fatal to this codegen for two
compounding reasons:

1. **C namespace collision.** The struct type `A` is emitted as a C
   `typedef struct A A;`. The function is generated as
   `void read_classvar_from_instance_d4d5c5 (MojoList * trials, int64_t A)`
   — the PARAMETER also named `A`, typed `int64_t` (this codegen's opaque
   representation for "a class object value" — see sub-cases A/B in
   `bugs/hard/CODEGEN_dynamic_attribute_on_generic_object.md`). In C,
   typedef names and ordinary identifiers share one namespace; a parameter
   named `A` SHADOWS the typedef `A` for the rest of that function's scope.
   Every subsequent attempt to declare a variable of type `A *` in this
   function (`A * _t5;`, `A * a;` — for the `a = A()` local) is instead
   parsed by GCC as an ordinary expression `A * _t5;` (multiply undeclared
   variable `_t5` by the parameter `A`) rather than a declaration, since `A`
   no longer names a type in this scope. This cascades: `_t5`/`a` are never
   actually declared as C variables at all, hence "undeclared" at every
   later use.
2. **Deeper, pre-existing semantic gap (same root, worse than the syntax
   error alone reveals):** even setting the C-namespace collision aside,
   this codegen's constructor/attribute lowering resolves a bare identifier
   like `A` in `A.x = 1` / `A()` by a **pure name-based lookup** against
   global tables (`self.struct_field_types`, etc.) — confirmed via a search
   turning up roughly 40 call sites of the shape
   `raw_name in self.struct_field_types` used to decide "is this a struct
   constructor / class object access". None of them check whether that bare
   name is actually SHADOWED by a local variable or parameter in the
   current function scope (i.e., no Python-scoping-aware name resolution
   anywhere in this dispatch class). So even independent of the C-typedef
   collision, `A.x = 1` inside this function is being lowered as "set a
   field on the GLOBAL class A" rather than "call `.x = 1`-style dynamic
   attribute set on the VALUE currently bound to local parameter `A`" —
   already a real semantic (miscompile) gap, not just a syntax one.

**Classified STRUCTURAL, not attempted.** A correct fix requires genuine
scope-aware name resolution (checking local/parameter bindings before
falling back to global struct/class name lookup) threaded through roughly
40 independently-written call sites across this codegen's call- and
attribute-lowering machinery — exactly the shape of change this project's
own history warns is high-risk when done as a "narrow-looking" patch (see
CLAUDE.md's quality-gate section and the `_tuplegetter` incidents it
references). A parameter/local variable shadowing a same-named global class
is also a rare enough real-world pattern (this benchmark script does it
deliberately, for benchmarking purposes) that the risk/benefit of a broad,
scope-resolution-adding change doesn't currently justify it within a single
narrow-bug fix pass. Left open for a dedicated follow-up.

## Quality gate

No code change was made for this file's remaining issue (structural, not
attempted). Issue 1 required no code change here either — it was already
fixed by prior, unrelated work; this doc's re-verification is the only
change (the "structure or union" style errors are gone, confirmed via a
fresh `python3 mojo.py build` run).
