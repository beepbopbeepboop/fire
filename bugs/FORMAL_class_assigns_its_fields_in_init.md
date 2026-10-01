# FORMAL_class_assigns_its_fields_in_init: a field the class never DECLARES, assigned only in `__init__`, has no evidence — and the refusal names both missing sources

**Status: found, not fixed.** Filed from the 2026-09-30 sweep re-measurement
(`bugs/FORMAL_sweep_work_map_2026-09-30.md`, row 10 of the ranked terminal
causes: **10 files, all in-file**, so each one is a single-file fix and none of
them has a dependency stack behind it — which is the property rows 2 and 3 of
that table do not have, and the reason this row is the cheapest real work in the
whole sweep). Not claimed by any live task at the time of filing.

## The refusal

```
build: self._chunks.append() hands the word in the slot self._chunks to
Tail.append(), whose receiver is the ADDRESS of a frame of 8-byte slots — so
the slot would have to hold a frame address. The declared type of '_chunks' is
the only thing here that could say so, and it does not: Tail: Tail does not
declare '_chunks', so nothing here says what the slot holds — a class that
assigns its fields in __init__ and declares none, and a field named only by
__slots__ or only by a method's read of self._chunks, are both that shape. Until
every binding of the name agrees on one type there is no frame to place here
```

`formal/build.py`'s `_typed_nested_frame` arm for a depth-2 method call, with
`model.struct_field_declared_type`'s `(None, why)` as the evidence. Reproduced
on current master (`24f96604`), nothing lifted:

```
$ python3 fire.py build --formal --no-prove -o /tmp/pr tools/procrun.py
build: self._chunks.append() hands the word in the slot self._chunks to …
```

## What is wrong, in one sentence

**The field's declared type is the only evidence this rule consults, and a
`class` body that binds its fields any other way produces no declaration to
consult — so a class that is unremarkable Python is refused by name.**

`tools/procrun.py`'s `Tail` is the smallest real instance:

```python
class Tail:
    __slots__ = ('limit', '_chunks', '_size')

    def __init__(self, limit=4 << 20):
        self.limit, self._chunks, self._size = limit, [], 0

    def append(self, data: bytes):
        self._chunks.append(data)      # <-- refused here
```

`_chunks` is a list, and `self._chunks = []` says so. The refusal instead
dispatches `self._chunks.append` to **`Tail.append`**, a method of `Tail`,
because dispatch here is by NAME alone and `_chunks` has no type to dispatch on
— so the analysis asks the wrong question (`is the slot a frame address?`),
gets "no evidence", and prints a frame-layout diagnostic about a list.

**The refusal's own remedy sentence is the finding.** It names the two missing
evidence sources — "a class that assigns its fields in `__init__` and declares
none, and a field named only by `__slots__` or only by a method's read of
`self.<name>`" — and then advises the reader to fix their code instead. Both
named shapes are this repository's own house style, and the advice is a rewrite
of correct code.

## The 10 files

All in this repository, all in-file, all one shape:

| file | what is undeclared |
|---|---|
| `formal/arm64_codegen.py` | `self.asm` — `ARM64Codegen` assigns its fields in `__init__` and declares none |
| `formal/x86_64_codegen.py` | `self.asm` — the same shape in the other backend |
| `scripts/stage2_mojo_interpreter.mojo` | `interpreter.scope` |
| `test_myinterpreter.py` | `interpreter.scope` |
| `test_myinterpreter_simple.py` | `interpreter.scope` |
| `test_myinterpreter_validation.py` | `interpreter.scope` |
| `test_phase2_parser.py` | `interpreter.scope` |
| `test_phase2_parser_simple.py` | `interpreter.scope` |
| `test_phase3_codegen_simple.py` | `interpreter.scope` |
| `tools/procrun.py` | `self._chunks` |

Eight of the ten are the SAME construct in the same class (`Interpreter.scope`),
so the fix is worth far more than its file count suggests on the "how many
distinct things is this" axis and rather less on the "how many files move" axis
— which, per the work map, is the axis that decides whether it is worth doing.
It is on this list anyway because 10 files with no dependency behind them is
the best ratio in the sweep.

## The exact next step

**`formal/model.py`, beside `struct_field_declared_type` and in the same
agree-or-refuse shape as the wave-4 declared-type rule it is an extension of
(`bugs/FORMAL_wide_receiver_by_reference.md`, "Wave 4 (D2)").** A third
evidence source for a field's type, beside the declaration:

1. `__slots__ = ('a', 'b', …)` — the names are a declaration of the field SET
   and carry no annotation, so they can answer "this struct has an `a`" and
   never "an `a` of type T". That is enough to stop the *frame* question from
   being asked about a name the struct does not have, and not enough to place a
   frame.
2. `__init__`'s assignments — `self.x = <value>` and the tuple form
   (`self.a, self.b = limit, [], 0`, which is `Tail`'s spelling and is why a
   reader looking only for `AssignStmt` with a `MemberExpr` target misses it).
   The ASSIGNED VALUE is the evidence, and it is exactly the evidence the
   declared-type rule already consumes elsewhere in this file: a construction of
   a framed struct of this unit (`self.scope = Scope()`) is a nested frame,
   `[a, b, c]` is a container literal and therefore provably NOT a frame, and a
   bare word is a word.

**The rule has to keep the shape the existing one has, and that is the whole of
what makes it safe:** unanimity or nothing. Two `__init__`s that assign a name
two different ways, one assignment and no declaration, or a value the analysis
cannot classify, all have to return "no evidence" and land on today's refusal.
`ValueKinds` already implements the same flow-insensitive agree-or-refuse for
local names (`_bind`, `_conflicts`), and reusing its discipline rather than
inventing a second one is what keeps a reader from having to decide which of two
tie-break rules is in force.

**The narrowing, and it is the one that matters:** this must NOT be extended to
a field an EXECUTED method assigns. `S()` does not run `__init__` on this path
(premise **B2**), so the value an `__init__` puts in a slot is exactly the value
nothing ever puts there — which is why
`model.struct_fields_written_outside_init` excludes `__init__` and why
`FRAME_FIELD_BLOB_PREMISE_B1` treats an executed write as a refusal. `__init__`
is therefore evidence about the field's TYPE and never about its value, and a
placement list built from it must be write-once exactly as the wave-4 one is.

## What is measured, and what is not

* The 10 files and the exact refusal text: `bugs/FORMAL_sweep_work_map_2026-09-30.md`
  row 10, from the 2026-09-30 arm64 sweep on current master.
* The reproducer and both missing evidence sources: `tools/procrun.py`'s `Tail`,
  built on current master with nothing else changed.
* **NOT measured: how many of the 10 would reach `pass`.** The work map's
  §3 is entirely about that number not being the blocked-file count, and this
  row has not been through the same experiment. `Interpreter.scope` is the one
  to try first (`self.scope = Scope()` — a nested frame of a framed struct, the
  answerable branch of the rule), and `procrun.py` is the one to try second
  (`_chunks` is a list literal, the provably-NOT-a-frame branch). If both move,
  the row is worth 10 files; if either reveals a further refusal behind it, the
  ceiling is smaller and the map should say so.
