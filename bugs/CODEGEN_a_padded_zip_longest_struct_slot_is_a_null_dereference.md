# CODEGEN_a_padded_zip_longest_struct_slot_is_a_null_dereference: `zip_longest`'s padded STRUCT slot is a NULL the body dereferences

**Area:** CODEGEN (`mojo/backend_gimple/emit_loops.py`,
`_gen_for_zip_longest`'s per-slot assignment, and whatever decides a member
read on a statically-typed struct pointer). Found 2026-10-05 while fixing the
padded slot's FILL VALUE — commit `e301ba41`, *"zip_longest: a padded slot is
refused unless this path can spell what fills it"*, which closed
`FORMAL_zip_longest_double_slot_fills_with_zero_not_none.md`. That commit's
subject is the FILL; this is the same padded row seen from the other end — the
value is right, the USE of it is not guarded.

## What I ran, and what I saw

```mojo
struct StackItem:
    var peek: Bool = False

def main():
    import itertools
    var inputs = [StackItem(), StackItem(), StackItem()]
    var outputs = [StackItem()]
    for input, output in itertools.zip_longest(inputs, outputs):
        input.peek = output.peek = True
    print("done")
main()
```

    CPython    AttributeError: 'NoneType' object has no attribute 'peek' …
    compiled   (no output)  exit -11   # SIGSEGV

The same shape without the member read does not crash — `print(input,
output)` over the same pair prints three rows and exits 0, with the padded
slot's NULL rendering as the model's `None` — so the crash is the WRITE
through the padded slot, not the padding.

**This is the exact shape `_gen_for_zip_longest`'s own docstring was written
for**: `Tools/cases_generator/analyzer.py`'s `analyze_stack` spells
`zip_longest(inputs, outputs)` with `input.peek = output.peek = True`. A crash
there is a self-hosting build failure, not a wrong answer.

## Why the model does not see it, and where the real fix is

The absent value is not the problem: a padded struct slot is filled with
`(int64_t)0`, which IS this model's `None` (see
`mojo/backend_gimple/emit_loops.py`'s `_zip_longest_slot_domain`, and
`_lower_IdentExpr`'s `None` → `int64_t 0`). The problem is that only a
`None` the SOURCE wrote gets the None-aware read path:

| program | compiled |
|---|---|
| `var p: StackItem * = None; print(p.peek)` | `AttributeError: peek`, exit 1 — routed through `_mojo_dispatch_getattr`, whose generic `mojo_obj_getattr` is None-aware |
| the same read through a padded `zip_longest` slot | SIGSEGV — `p->peek`, a raw dereference |

Measured by dumping the generated C for both (`.tmp/` scratch, `--dump`).
The difference is the variable's DECLARED type: a `None` assignment makes the
variable `int64_t`, and every read of an `int64_t`-declared name is dynamic;
a zip_longest slot is declared with its sequence's real element type
(`StackItem *`), which is the whole reason the handler exists — see its
docstring, `analyzer.py` included.

So the fix is not in `zip_longest`. It is: **a member read on a
statically-typed struct pointer that can be NULL must take the None-aware
path**, which means the codegen needs to know a pointer is nullable, and
nothing records that today (`gen.var_types` says the type and nothing about
absence; `_mojo_dispatch_getattr`'s `_mojo_getattr_S` shim is only reached
from an `int64_t`-declared name).

Two shapes, and the choice is worth stating rather than leaving to whoever
picks this up:

1. **A nullability flag per local** (`gen._nullable_ptrs`, set at every site
   that can store a `None` into a pointer-typed local — the zip_longest padded
   select, an out-of-range or optional read, a `None`-returning callee — and
   consulted by the member-read emitter). This makes the whole family correct
   at once rather than one producer at a time, at the cost of a per-member-read
   branch in every program.
2. **A boxed slot for a padded struct-pointer `zip_longest` slot** (declare
   the target `int64_t` when the element type is a pointer). Two lines, and it
   REGRESSES what the handler was written for: the struct-typed loop variables
   are why `analyzer.py`'s `input.peek = …` emits a member write into a struct
   at all, and `bugs/CODEGEN_zip_loop_target_keeps_the_first_loops_type.md`
   (still open, unclaimed) is about the same declaration.

(1) is the production answer and (2) is the workaround. **This doc does not
pick one for you and does not want a zip_longest-only guard**: a guard inside
`_gen_for_zip_longest` would fire for a body that only PRINTS the padded slot,
where the answer is already right, and would hide the general gap behind the
one producer that happens to have a bug doc.

## What is asserted today, so this cannot rot silently

`test_gimple_runner.py`'s `gimple_zip_longest_pads_every_domain_it_can` (with
CPython as the oracle) covers the domains where the padded row is representable
and correct. **Nothing covers this one**: the closest is the refusal the sibling
fix added for a padded FLOAT slot
(`gimple_zip_longest_a_padded_float_slot_raises`), which is the same "absent is
a value" question with the opposite answer — a float slot cannot hold the
absence at all, so it raises, while a struct slot holds it and then hands the
body a NULL it dereferences.

When this is fixed, the assertion is that the program above prints
`AttributeError` on stderr with a non-zero exit instead of a signal, and
`analyzer.py`'s shape must keep compiling (its member WRITE is the reason the
slot is typed `StackItem *`).

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label segv -- \
  python3 fire.py build -o .tmp/segv .tmp/segv.mojo
python3 tools/memslot.py --gb 8 --label segv -- .tmp/segv   # exit -11
python3 tools/memslot.py --gb 8 --label segv -- python3 fire.py --dump .tmp/segv.mojo
grep -n 'peek' segv.ci        # the raw `->` member write, no NULL guard
```