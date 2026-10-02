# A cross-module struct CONSTRUCTOR called at MODULE scope is mistyped — silent pointer on one import spelling, a hard build failure on the other

**State: OPEN. Found 2026-09-30 while closing the last row of
`bugs/hard/CODEGEN_method_call_on_struct_param_mistyped.md` (doc deleted,
same commit). Not caused by that fix — verified pre-existing by reversing
that commit's diff and rebuilding.**

Distinct from the bug it was found next to: that one was the `import mod`
SPELLING not being considered by link mode at all, and it is fixed. This one
is orthogonal to the import spelling and orthogonal to module-vs-function
scope: it is the same mistake in both import spellings, and only at module
scope. Both halves matter, because a one-line "make both spellings agree"
fix does not touch either.

## What I ran

`.tmp/vd1b/insp.py`:

```python
class Parameter:
    def __init__(self, v, n):
        self.v = v
        self.n = n
    def label(self):
        return self.v
```

`cd .tmp/vd1b && python3 fire.py build <case>.py && ./<case>`, with
`python3 <case>.py` alongside for the CPython answer.

## What I saw

| case | statement | CPython | compiled | exit |
|---|---|---|---|---|
| `k3.py` | `def main(): print(show(insp.Parameter('v', 7)))` + `main()` — **inside a function** | `v` | `v` | 0 |
| `k4.py` | same, `from insp import Parameter` — **inside a function** | `v` | `v` | 0 |
| `k5.py` | `def main(): x = insp.Parameter('v',7); print(x.v)` + `main()` | `v` | `v` | 0 |
| `k8.py` | `print(show(insp.Parameter('v', 7)))` — **at module scope**, bare import | `v` | **`4335474136`** | **0** |
| `k10.py` | `x = insp.Parameter('v', 7); print(x.v)` — **at module scope**, bare import | `v` | **`4340569496`** | **0** |
| `k9.py` | `print(show(Parameter('v', 7)))` — **at module scope**, from-import | `v` | **BUILD FAILS** | 1 |
| `k11.py` | `x = Parameter('v', 7); print(x.v)` — **at module scope**, from-import | `v` | **BUILD FAILS** | 1 |
| `m1.py` | same as `k8.py` but the class is in the SAME file | `v` | `v` | 0 |
| `m2.py` | same as `k10.py` but the class is in the SAME file | `v` | `v` | 0 |

The two `4.3e9` answers are the `Parameter *` pointer's own bits printed as
a decimal (they move run to run, under ASLR) — the identical silent-wrong-
value-with-exit-0 shape the deleted doc was about, so it must not be filed
as "just another gap" without saying so. The two build failures are:

```
insp.py:5:1: error: non-trivial conversion in 'var_decl'
insp.py:7:1: error: non-trivial conversion in 'component_ref'
```

(`#line`-attributed into `insp.py`, but raised from the client file's
module-scope statements) — a `char *` stored into an `int64_t`-typed slot,
the same class of failure
`test_link_mode.py::test_sibling_class_constructor_field_function_scoped`'s
docstring describes for the constructor-field-hint pre-pass, reached through
a different route.

## What I expected

`v`, exit 0, from all four module-scope cases, exactly as the four
function-scope ones already give.

## Where

Two facts bracket it, and both are checkable in one `compile_linked` dump:

1. **It is not the import seam.** `mojo/backend_gimple/emit_resolve.py`'s
   `_register_link_imports` never considered a bare `import M` at all, so
   `M.Class(...)` reached the generic scalar-receiver stub and the module
   HANDLE came back as the object — that was the deleted doc's row and it is
   fixed. But the from-import spelling never had that problem and fails
   *differently and worse* here, and the single-file case is clean at module
   scope, so neither the seam nor module scope alone explains it.
2. **So the scope-dependent pass is the suspect.** The cross-module
   struct-pointer contract and the constructor-field-hint pre-pass
   (`module_gen.py`'s `_xmod_*` / Pass 1.3d-struct region, and
   `_arg_struct_ptr_type`'s observer) are driven off FUNCTION bodies. A
   module-scope call site is emitted by a different part of `gen_module`,
   and is not in the set of sites those passes collect. The single-file
   module-scope case is clean because in one translation unit the struct's
   own field table is already registered before the module's statements are
   emitted, with no cross-module identity to propagate.

## Exact next step

Diff `compile_linked`'s generated C for `k8.py` against `k3.py`'s and read
the module-scope call site against the function-body one; the question is
whether the module-scope `_t = <module handle>` / `/* int64_t.X() stubbed */`
is still there (seam again, i.e. the fix is incomplete) or the struct is
known and the wrong thing is the `var_decl`/`component_ref` store (the
pre-pass, i.e. a different fix). Then either way, extend the site collector
those passes use to include module-level statements — a module-scope
`Class(...)` call is the same shape and must be observed by the same pass,
or the two spellings will drift apart again.

Two regression tests belong next to whichever fix lands, both in
`test_link_mode.py` (the `linkmode` gate step, which drives
`driver.compile_program` and compares against CPython): the silent
pointer-valued row (`k10.py`) and the build-failure row (`k11.py`). Neither
belongs in `test_gimple_runner.py`, which drives the single-TU path where
both already work.