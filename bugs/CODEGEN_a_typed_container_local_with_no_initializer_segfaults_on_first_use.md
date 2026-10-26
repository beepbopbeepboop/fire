# CODEGEN: a typed container LOCAL or module GLOBAL with no initializer is never allocated, and the first use segfaults

**Area:** CODEGEN (`mojo/backend_gimple`). **Status: OPEN, measured
2026-10-19, PRE-EXISTING on `master`.** Found while fixing the FIELD half
of the same root cause (a no-initializer container STRUCT FIELD stayed
NULL and SIGSEGVd on the first mutation — that half is fixed on this
branch: the field is seeded from a per-class empty container in the
struct's allocator, exactly like an explicit `= []` field). The field
fix is `mojo/backend_gimple/module_gen.py`'s `_class_field_decl` /
class-attribute registration; this doc is the LOCAL and module-GLOBAL
half, which is a different mechanism and was deliberately not folded
into that fix.

## What I ran

```
$ printf 'def main():\n    var xs: List[Int]\n    xs.append(1)\n    print(xs)\n' > .tmp/pa3.mojo
$ python3 fire.py --jit .tmp/pa3.mojo
JIT execution failed with code -11
$ python3 fire.py run .tmp/pa3.mojo
[1]
```

The same shape at module level (the interpreter answers it too):

```
$ printf 'var xs: List[Int]\n\ndef main():\n    xs.append(1)\n    print(xs)\n' > .tmp/pa_mod.mojo
$ python3 fire.py --jit .tmp/pa_mod.mojo
JIT execution failed with code -11
$ python3 fire.py run .tmp/pa_mod.mojo
[1]
```

The generated C for the local shows the defect precisely:

```c
int64_t _gimple_main (void)
{
  MojoList * xs;                       /* declared, NEVER assigned */
  ...
  mojo_list_append_int (xs, _t1);      /* NULL dereference -> SIGSEGV */
```

The annotation resolves to the right ctype (`MojoList *`), the element
type is seeded from it, but no container is ever allocated for a
no-initializer BINDING — the pointer holds whatever zero-init left in
the slot. Every first use through it (append, subscript, len) crashes.

## What is NOT this bug

- A no-initializer container STRUCT FIELD is fixed (this branch): it is
  seeded per-class in the allocator and mutates fine.
- An INITIALIZED binding (`var xs = []`, `var xs: List[Int] = []`)
  works fine, as before.
- The `()`-suffix idiom (`var xs: list()`, no initializer) auto-allocates
  and works; see the scoping note below for why the bracketed spelling
  was deliberately left out.

## Why it matters

The interpreter binds a FRESH empty container for every no-initializer
`List`/`Dict`/`Set` local (its `_container_field_default`, landed with
the interpreter's container-default fix) and for the struct-FIELD case —
so `var xs: List[Int]; xs.append(1)` is a correct, ordinary program on
`fire.py run` and a silent SIGSEGV on `fire.py --jit`: the plausible-
crash class this fleet files as bugs. The two-instance divergence the
field fix introduces (a no-init FIELD is a per-class shared container on
the compiled path, fresh per instance on the interpreter) is a separate,
deliberately-undecided semantic question — this doc is only about the
NEVER-ALLOCATED binding.

## The exact next step

`mojo/backend_gimple/emit_stmts.py`'s `_gen_stmt_VarDecl` no-value
branch (the `else:` beside the initializer arm, around the BUG-2026-030
struct-local allocation). It already auto-allocates the `()`-suffix
annotation shape (`var x: list()`) with `mojo_list_new ()` /
`mojo_dict_new ()` / `mojo_set_new ()`. The bracketed spelling
(`var x: List[Int]`, no initializer) is deliberately EXCLUDED there by a
comment: "a bracketed `var x: List[T]` (no initializer) is real Mojo's
own explicit 'must assign before use' form ... auto-allocating THAT too
would silently paper over genuine definite-assignment bugs".

That comment predates the interpreter's container-default fix, which
made the no-initializer local a fresh empty container on the OTHER
engine, and it predates the field fix on this branch, which made the no-
initializer FIELD a retained container on this one. The comment's
rationale is a language-semantics DECISION, not an implementation limit,
so the first step is to RESOLVE the conflict, not to patch the branch:

1. Decide which engine's no-initializer local semantics the language
   wants (fresh empty container, matching the interpreter and the field
   fix, versus must-assign-before-use, in which case the interpreter's
   `_container_field_default` local arm is the half to walk back).
2. Whichever way it resolves, apply it to BOTH the local and the module-
   GLOBAL spelling (the same `_gen_stmt_VarDecl` branch handles the
   `gen._in_toplevel_gen` case; a module-level `var xs: List[Int]`
   crashes the same way) and update the stale comment.

The cheapest measurement is the two probes above through `fire.py --jit`
vs `fire.py run`: exit -11 / `[1]` before, `[1]` / `[1]` after. Do NOT
reuse the field fix's per-class global mechanism for a LOCAL: a local
must be fresh per call (a per-class global for a function local would
leak state across calls); the `()`-suffix branch's `gen._new_val(ctype,
_alloc)` emission is the existing per-binding pattern to extend.
