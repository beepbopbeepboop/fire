# FORMAL_tuple_store_to_a_field: a tuple store to a FIELD builds on arm64 and drops the value

**Found 2026-09-29 while lowering the second evidence source for a field's
type (`formal/model.py` `struct_field_assigned_type`). Not fixed here: the
fix is in the emitters, not in the frame analysis, and the frame analysis is
this lane's file. Status: open, with the reproducer, both architectures'
answers, and the exact next step.**

## What I ran

```
$ cat .tmp/scratch/tup2.mojo
class Tail:
    def __init__(self):
        self.p, self.q, self.r = 3, 4, 7

    def total(self):
        return self.p + self.q + self.r

def main(n: Int) -> Int:
    var t = Tail()
    return t.total()
```

The `var`→blank and `class` spellings are the same text CPython runs;
`fire_compiler` parses both, and `self.p, self.q, self.r = 3, 4, 7` is what
each sees.

## What I saw

| | result |
|---|---|
| CPython, same program | **14** |
| `build --formal --no-prove` (arm64) | **Built.** Runs, exits **0** |
| `build --formal --no-prove --backend x86_64` | **refused**: `tuple assignment targets must be plain names on the formal x86-64 path (got MemberExpr)` |

**arm64 builds it, runs it, and returns 0 where the source says 14.** No
crash, no diagnostic, exit status 0 — the shape of defect this backend exists
to make impossible, and the worst kind of the family: the program is wrong and
says nothing.

**What I expected:** either a store per element, or a refusal by name. A
tuple store to a plain name works on both architectures and is correct
(`a, b = 3, 4` → 7 on both, measured), so the arithmetic, the register
allocation and the target pairing are all already there; what is missing is
that a `MemberExpr` target is not one of the shapes the arm64 store path
emits.

## Why it matters more than a 300-byte reproducer

`self.a, self.b = A(), B()` is ordinary Python and this repository writes it:
`tools/procrun.py` has

```python
self.limit, self._chunks, self._size = limit, [], 0
```

So any lowering that has to reason about a field's VALUE — which is exactly
what a nested frame's placement is — can be fed an `__init__` whose store the
emitter drops. `formal/model.py`'s `struct_field_assigned_type` therefore
**recognises** the shape (so the refusal names the assignment rather than
saying the field is never assigned) and **does not read a type out of it**:

```python
if how == "tuple":
    untyped = (f"__init__ assigns `self.{name} = {expr_spelling(value)}` "
               f"as one element of a tuple target, and a tuple store to "
               f"a FIELD is not a store this path performs — x86-64 "
               f"refuses it by name and arm64 accepts it and leaves the "
               f"slot as it was — so what the slot holds is not settled "
               f"by that line")
```

That is a band-aid, and it is honestly labelled as one in the code: with the
type read out of the store, `byref_refuse_a_tuple_target_names_the_store`'s
program **built, ran, and answered 123 where the source says 128**.

## The exact next step

In `formal/arm64_codegen.py`, the store path for an `AssignStmt` whose
`target` is a `TupleExpr`/`ListExpr`: pair `target.elements[i]` with
`value.elements[i]` and emit the same store each element gets from the
`MemberExpr` branch — which for a receiver-relative target is the frame-slot
store (`_store_var` through `_frame_slots`), not a register move. Then delete
the `_STORE_TUPLE` arm in `struct_field_assigned_type` and let the inference
read the type again.

Two things to get right while doing it, both from the measurements above:

* **the receiver check.** `struct_receivers` (not the literal `self`) is
  what makes `this.a, this.b = …` work, and `struct_field_assigned_type`
  already reads the set that way; the emitter's store has to take the same
  set or the two will disagree about which targets are fields.
* **the length pairing.** `self.a, b.c = X(), Y()` and `self.a, *rest = …`
  are not per-field stores, and the frame analysis already refuses to read
  anything out of them. The emitter should refuse them by name on the same
  grounds rather than store element 0 and drop the rest.

After that, the `TupleExpr` refusal in `formal/x86_64_codegen.py` becomes
either a real lowering or stays, and `tools/procrun.py`'s finding moves off
`self._chunks` onto whatever the next thing in that file is.

## Verification this would need

`test_formal_run.py`, in the `ASSIGNED_TYPE_REFUSALS` group next to
`byref_refuse_a_tuple_target_names_the_store`:

* `assign_tuple_target_stores_every_field` — the reproducer above, **14**,
  built, run, compared with CPython, on arm64 and x86-64.
* a receiver-spelled target (`this.a, this.b = 1, 2` in a `@staticmethod`-free
  method) and a mixed target (`self.a, b.c = X(), Y()`) that must still be
  refused by name.

Then re-measure `python3 tools/formal_sweep.py --no-stdlib tools/procrun.py`:
it should leave the `field slot holds a frame address` family. It is in it
now, at x1, and `bugs/FORMAL_frame_receiver_handoff.md` §14 carries the
before/after numbers.
