# FORMAL_read_before_store_returns_a_register: a name read before anything writes it returns whatever the allocator left behind

**Status: OPEN, pre-existing on both backends, and it predates the work that
lowered module top-level statements — which made it REACHABLE from a shape that
looks valid, and is now fixed (`formal/build.py`'s `module_body` /
`entry_function`, whose own bug doc was removed with the fix). What is left is
the general case, which is not that shape.**

Found while lowering module top-level statements (2026-09-29, the
`construct:toplevel-statements` claim), at `7214cc1`. Verified unchanged at
`HEAD~1` — see "Pre-existing" below, which is the load-bearing part of this
document.

---

## What I ran

`.tmp/m3.mojo`, in full:

```mojo
def f():
    for i in range(3):
        G = G + i
    printf("G=%d", G)
```

```console
$ python3 fire.py build --formal --no-prove -o m3.aout m3.mojo
Built: m3.aout  [arm64/macho]
$ ./m3.aout
G=-157679357
```

CPython raises `NameError: name 'G' is not defined` for that program. The
formal backend reads a register nothing ever wrote and prints a word that
varies with the build — `-157679350` for the same shape with `range(5)`,
`240046802` on x86-64 for `range(5)` where arm64 says `-157679350`.

After module top-level statements were lowered, one MORE shape reaches it,
and that one looks like a valid program at a glance:

```mojo
x = x + 1
printf("x=%d", x)
```

CPython: `NameError: name 'x' is not defined`. This path: `x=11`. That is
fixed at the source (see "What this document is not about" below); the
general case is what is filed here.

## Why

`bound_names_in_order` (`mojo/middle/boundnames.py`) lists a name that is
ASSIGNED anywhere in a function body, and `_allocation_order`
(`formal/arm64_codegen.py:274`, and the x86-64 twin) gives each listed name a
callee-saved register. The allocator answers "where does this name live",
and it answers correctly: `G` is written in the loop, so it must have a
register.

Nothing answers "is the register written YET at this read". `_load_var`
reads the register, and a register that has never been stored is whatever
the caller left in it. That is not a wrong constant, it is a wrong value
that CHANGES WITH THE BUILD — which is why it is a finding rather than a
cosmetic issue: the same source does not have one answer.

The two known values on this tree, arm64 and x86-64 disagreeing about a
number neither of them wrote, is the same class of failure
`bugs/FORMAL_known_limits.md` calls "a fabricated word" and that
`refuse_module_level_mlir_templates` was written to stop: a construct with
no representation here becomes a value the program never computed.

## Measured

| program | CPython | arm64 | x86-64 |
|---|---|---|---|
| `for i in range(3): G = G + i` then print `G` | `NameError` | `-157679357` | — |
| the same with `range(5)` | `NameError` | `-157679350` | `240046802` |
| `x = x + 1` at file level, then print `x` | `NameError` | `11` | — |
| `y = 0` then `y = y + 1`, then print | `1` | `1` | `1` |
| `z = 5` then `z += 1`, then print | `6` | `6` | `6` |

The last two rows are the control: a name stored BEFORE it is read is right,
so this is about the order and not about the register allocation.

## Pre-existing, and that is measured rather than asserted

The three rows that do not involve a module body build and run identically
on `HEAD~1` of this branch, i.e. before `formal/build.py` grew
`_module_body_function`:

```console
$ cd <HEAD~1 worktree> && python3 fire.py build --formal --no-prove -o m3.aout m3.mojo && ./m3.aout
G=-157679357
```

The same value, on the same source, from a tree that never lowered a
top-level statement. This document therefore does not claim the work that
lowered module bodies introduced it, and closing it does not belong to that
claim either.

## What this document is not about

The shape that LOOKED valid is not this document's subject, and it is
already fixed:

```mojo
total = 0
for i in range(5):
    total = total + i
printf("total=%d", total)
```

CPython prints 10. Lifting the module body into `__module_body__` printed
`-157679350` on arm64 and `240046802` on x86-64, because `total = 0` folds
to a literal, so `model.module_body` left the store out on the theory that
`_substitute_module_constants` would put the literal at each read — and it
does not, because it skips a name the reading function BINDS, and the body
binds `total`. `model.module_body` now keeps the store when the body rebinds
a folded constant, and the program prints 10 on both architectures
(`test_formal_toplevel.py`). That was a bug in the exemption, not in the
allocator, and it is why the two shapes are told apart here: one is a
missing store for a name the program DOES initialise, the other is a name
the program never initialises at all.

## How much of the tree is in it

Every program that reads a name it never stores, which is not a class the
sweep can count: the file parses, builds, and produces a value, so it lands
in `pass`. Measured over this tree and the stdlib, no file has this shape at
file level, and one file of the 210 with a module body had the *exemption*
bug above (`array_ops_jit.mojo`). So the sweep's contribution to sizing this
is nil, and that is the reason it is filed as a construct gap rather than as
a sweep finding: the corpus cannot see it.

## The exact next step

Refuse it, at the point where the read is lowered, by asking the question
the allocator does not ask.

**A cheap first version that is exact on a large subclass, and where to put
it:** in `formal/build.py`, beside `check_module_symbols` — the same
"a name read in a function that no table in the compiler places" check,
which already walks every function body and already collects the placed set
(parameters, `_names_bound_in`, comptime bindings, frame slots, substituted
module constants). A name in the placed set that is READ in the body and
appears in NO store in that body — not `bound_names_in_order` (which counts
a store inside a loop as a store) but a store the body's own statement
ORDER puts before the read — is this case, and it is decidable from the
walk `check_module_symbols` already does.

**What that version will not catch, stated so the next reader does not
believe it is the whole fix:**

```mojo
for i in range(3):
    if i:
        t = 1
printf("t=%d", t)      # CPython: UnboundLocalError when i == 0
```

Here `t` IS stored in the body, so a statement-order check passes it, and
whether the register holds 1 or garbage depends on which arm ran. Catching
it needs a DOMINATING-STORE analysis over the function's CFG — every path
from the entry to the read must pass a store — which is a real reachability
computation and not a walk. The honest two-step is therefore: ship the
statement-order refusal (it is a strict improvement and it is the shape
measured above), and record the CFG version as the remainder, the way
`formal/build.py` records the other limits that are "a change to the
emitter's model and not a name check".

**Where NOT to put it:** not in `check_module_symbols`'s `placed` set, which
is a set of names that have a HOME. A name can have a home and still have
no value at a given read; folding the two questions together would make the
homes message false about files that are fine.
