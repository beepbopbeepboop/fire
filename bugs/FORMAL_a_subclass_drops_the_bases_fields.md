# FORMAL_a_subclass_drops_the_bases_fields: `class Sub(Base)` has only `Sub`'s own fields, and nothing says so at the class

**Status: open, unowned, and it is a MODEL change rather than a lowering
tweak — measured on both architectures, 2026-10-03, with the three symptoms it
produces and the exact list of readers a fix has to reach.** Filed from the
sweep's `codegen` row "struct construction: arity does not match the fields"
(`mojo/backend_gimple/device_glue.py`, one file, in-file), which is the second
half of §3.2's single-file causes in
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md`.

## What is wrong

A struct's field list is derived from its OWN class body.
`formal/model.py::_split_declaration` walks `struct_fields(struct_def)` and
nothing else, so a base's fields are not in the subclass's layout, not in its
arity, and not in its width — and the base's name is read by exactly two things
in the whole tree: `dataclass_transform.inheritance_refusal` (which refuses
`@dataclass class C(A)` BY NAME, with the sentence "This path's struct has no
base-class field merge at all") and `struct_is_derived_from`. Nothing refuses a
PLAIN `class Sub(Base)`, so the drop surfaces later, as a fact about a
different line.

Measured, both architectures, from three files:

**1. A construction's arity** — the sweep's row:

```python
class LaunchError(Exception):
    """A kernel whose host side cannot be marshalled honestly."""
...
        raise LaunchError(f'GPU kernel {kernel!r} has no Int/Int64 parameter…')
```

    $ python3 fire.py build --formal --no-prove -o /tmp/dl mojo/backend_gimple/device_glue.py
    build: constructing LaunchError with 1 argument(s) does not match its fields
    (no fields at all), and LaunchError declares no `__init__` for it to call
    instead: …

which is TRUE (there are no fields) and useless as advice: the reader is told to
declare the fields, and the reason the class has none is that it inherits them.

**2. A field read or write through the subclass** — a wrong-reason refusal at
the use site:

```python
class Base:
    x: int
class Sub(Base):
    y: int
    z: int
...
    s = Sub()
    s.x = k          # x is Base's
```

    build: s.x is a field of s, and Sub has no field 'x': its 2 field(s): y, z.
    In Python this is an AttributeError at run time, so the program is very
    likely already raising here — but this path refuses rather than read a word
    it cannot place …

The "In Python this is an AttributeError" clause is **false** of the program:
`Sub` inherits `x`, so `s.x` is a field read in Python too. A refusal that
mis-describes the program sends the next reader to the wrong line — this one
says "the program is probably already raising here", which is a claim about the
source that is not true.

**3. The receiver's width**, which is the quiet one: a subclass whose base has
fields measures as a one-word struct when it declares none of its own, so it
gets the ONE-WORD convention (`self` IS the field) that its base's methods —
compiled from the base's declaration — do not agree with. Nothing in the class
says so.

## Why it is not a patch

The field list is read by name from all over, and the fix has to reach the
readers rather than add a second one:

| reader | what a merge changes |
|---|---|
| `struct_field_names` / `struct_field_count` / `struct_sole_field_name` | the width, and so `struct_fits_one_word`, `struct_is_framed`, and which of the two receiver conventions the struct gets |
| `_split_declaration`'s field/constant split | a base's CONSTANT must not become a subclass field, and the demotion evidence (`struct_field_evidence`, the write census) has to include the base's methods or it will demote names the base stores |
| `struct_frame_slots` / `struct_frame_defaults` / `struct_construction_plan` | the frame layout, the per-slot default store, and the arity message above |
| `struct_construction_plan`'s `structs_by_name` | already takes the table, so the BASE's construction sites and `__init__` overloads become reachable — a subclass whose base declares `__init__` has a call target this path does not have |
| `lib/ProofLib.lean`'s frame model | `Refine.FrameOk_except` and `Refine.FrameBound` are stated per width, and a merged layout changes the frame size a method's callee contract is proved modulo |

The last row is why this is not a light worker's change: it touches
`formal/model.py`, both backends and the Lean library, which is the class of
change `CLAUDE.md` says owes a full `make gate`. The next step is a gate, not a
build.

## What a fix has to decide first, and it is not "prepend the base's fields"

* **The declaration order.** CPython's dataclass puts the BASE's fields first
  and its own after, and the order decides which value lands in which slot —
  `dataclass_transform.inheritance_refusal` already says this, and it is why
  that refusal exists rather than a silent drop.
* **A base this image does not declare.** `LaunchError(Exception)` is the case
  the sweep found, and `Exception` is NOT declared anywhere in
  `formal/hostmods/` — so even a correct merge finds no fields for it. The
  sweep's file needs a hostmod declaration for `Exception` (one class, one
  field, one `__str__`) BEFORE the merge, and a fix that only merges would move
  its verdict from "arity does not match" to "the base is not declared" and
  stop there.
* **Whether a merged layout is a LAYOUT CHANGE or a new convention.** Every
  struct's frame size is a constant in the emitted code and in the proof, so
  merging is not "one more name in a list" — it is a different frame for every
  subclass in the tree.

## The two cheap things a reader gets today

Both are diagnostics rather than lowerings, both are refusals that already fire
on some other line, and neither is done here:

* the arity message could name an undeclared base (it has the StructDef's
  `bases` at hand), so `LaunchError`'s reader is told the base is undeclared
  rather than that there are no fields;
* the "In Python this is an AttributeError" clause in `field_access_refusal`
  could stop claiming it for a name one of the struct's own bases declares.

Both change text that pinned cases assert on
(`test_formal_run.py`'s `constr_refuse_*` group, `member_read_without_a_field`),
so they belong with whoever changes the behaviour, not beside it.

## Reproducing

    $ export PATH=/opt/homebrew/bin:$PATH
    $ python3 fire.py build --formal --no-prove -o /tmp/dl \
          mojo/backend_gimple/device_glue.py          # symptom 1
    $ python3 tools/formal_sweep.py -j 2 -t 120 mojo/backend_gimple/device_glue.py
    CODEGEN: mojo/backend_gimple/device_glue.py  (build: constructing
    LaunchError with 1 argument(s) does not match its fields (no fields at
    all) …)