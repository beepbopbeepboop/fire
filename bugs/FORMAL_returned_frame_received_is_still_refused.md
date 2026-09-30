# FORMAL_returned_frame_received_is_still_refused: row 9, and the two channels its lift depends on

The other half of the returned-frame family, and the one this change
deliberately did **not** lift.
`bugs/FORMAL_returned_frame_caller_owned_block.md` closed row 5 (a frame the
function BUILT); this is row 9 (a frame the function was HANDED), 11 files, and
it is still refused by `model.frame_return_refusal`'s `received` arm.

```
a Progress receiver is returned from a method of Progress, which did not create
the frame — it received the address as its receiver, so the function that DID
create it is somewhere up the call chain and nothing here establishes that its
frame is still there.
```

## Why it is a different construct and not an oversight

For a frame this function built, the convention settles the lifetime: the CALLER
reserves the block (`model.struct_returned_frame_sites`), so the object's
lifetime is the caller's and the question never arises. For a frame that arrived
as a parameter or as a method's receiver, **there is no caller to reserve
anything** — the creator is some ancestor, and this analysis cannot name it.

`FORMAL_frame_receiver_handoff.md` §8 states the argument that the lifetime is
actually sound, and it is the same one the by-reference receiver rests on:

> A frame belongs to the function that created it, and reclaimed when that
> function returns. An address only ever travels **down an active call chain**.
> … So the creator of a holder that arrived as an argument is an **ancestor of
> the callee**, and its bytes are live for every instant of the callee's
> activation.

Handing the address back to the CALLER moves it one activation further out,
which that argument covers. So the refusal is a **stated gap in the premises,
not a proof that the program is wrong** — and §8 declines to lift it for exactly
that reason, which is the right call and is what this doc records.

## What it costs, measured

Both architectures, the check lifted, the creator one frame deeper than the
caller that reads the value:

```
def fwd(x, p):  return p          # p was built in main
def main(n):
    var p = Point(); p.x = 7; p.y = 8
    return mid(1)                 # mid reads fwd(1, p).a
```

`return p` here built, ran, and returned **10 on arm64 and 0 on x86-64** where
the source says 7 — a use-after-free, and the two architectures disagreeing
about what the reused bytes held. That is `FORMAL_frame_receiver_handoff.md` §8's
own measurement, and it is the number that has to stay true.

## The two channels the lift depends on, and the exact next step

§8 lists them and both are still open:

1. **A module-level symbol table.** `G = p` inside a function, read from another,
   returns **10 on arm64 and 0 on x86-64** where the source says 5, measured
   (§9 of the same file). Until module-level storage is its own thing, a frame
   address can leave the callee through a name this analysis cannot even tell
   from a local — `g = r` in `main` is indistinguishable from a global store to
   any rule keyed on "not a local of this function". **This is
   `construct:module-global-storage`, another worker's claim, and this doc does
   not touch it.**
2. **A `*args` / `**kwargs` parameter list.** `params` is a flat list of names
   with no `vararg` and no `kwonlyargs`, so `f(1, 2, r)` against
   `def f(x, *rest)` is read as three fixed parameters and `r` binds to a slot
   named after a TUPLE. The fixpoint is safe today only because `plist[pos]`
   cannot reach a third index on a two-element list. `fire_compiler.py`'s
   `FunctionDef` already carries `param_has_default` / `param_defaults`, so the
   same treatment is available. **This one is unowned and is the smaller of the
   two.**

**The next step, concretely.** Once (1) exists, the change is: treat a
`ReturnStmt` whose value is a holder that is **not** in
`model.returned_frame_owned_names` and **is** one of `fn`'s parameters (or the
receiver of a method of the returned holder's own struct) as permitted, and keep
every other channel refused. The message is already the right one — the current
refusal text says the creator "is somewhere up the call chain and nothing here
establishes that its frame is still there", which is exactly what would become
establishable. Do **not** lift it for a name that arrived by a channel this
analysis does not model: the residual hole is in the RECOGNITION, not a way for
a frame to dangle.

## The 11 files, and where each is

Re-measured on this tree (`tools/formal_sweep.py`, arm64) after the row-5
change; all 11 still report this refusal, 10 in-file and 1 one import deep:

| file | note |
|---|---|
| `std/benchmark/_progress.mojo` | the map's example for the row |
| `std/builtin/range.mojo` | |
| `std/collections/string/_utf8.mojo` | |
| `std/itertools/itertools.mojo`, `std/itertools/__init__.mojo` | the second is the dependency of the first |
| `std/python/python_object.mojo` | |
| `std/sys/intrinsics.mojo` | |
| `fe_reader.py`, `test_suite.py`, `tools/memslot.py` | |

**0 of them would reach `pass` if the refusal were lifted**, measured the way the
brief asks: the same lift-and-re-sweep on the pre-change tree moved none of them,
because six are behind `info.mojo` / `dtype.mojo`'s MLIR (a documented
permanent limit) and the rest are behind `python.mojo`'s MLIR or an
already-classified host import. That is the number a planner wants, and it is
why this doc is a record of a gap and not a queue item.

## The case that keeps it honest

`refuse_a_received_frame_handed_on` in `test_formal_returned_frame.py` is
labelled a GUARD in the file, and it is the only one of that file's 18 cases
that passes on the pre-change tree. It exists so that a change which widened the
convention to cover a RECEIVED frame would fail against something: the widening
is the neighbouring construct, and a silent version of it is a use-after-free.
