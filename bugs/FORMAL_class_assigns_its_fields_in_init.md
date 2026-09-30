# FORMAL_class_assigns_its_fields_in_init: a field the class never DECLARES, assigned only in `__init__`, has no evidence — and the refusal names both missing sources

**Status: FIXED, and the measured ceiling was 0 files.** The `__init__`-
assignment source landed on 2026-09-30 (`formal/model.py`:
`struct_field_declared_type` now falls back to `struct_init_field_types`; the
classifier is `assigned_value_base_name`, unanimity is
`ValueKinds._bind`'s, and `decls` is threaded down because a call to a FUNCTION
is not a type — see §"What landed" below). **0 of the 10 files reach `pass`**;
every one moves, and two leave the `codegen` class outright. The doc stays
because the measurement is the deliverable and because the NEXT refusal on six
of the ten is not in this row — see §"Where the ten files land", which is the
part a planner should read next.

## The refusal, as it was

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
$ python3 tools/formal_sweep.py tools/procrun.py
CODEGEN: tools/procrun.py  (build: self._chunks.append() hands the word in the
                            slot self._chunks to …)
```

(The map's original repro was `fire.py build --formal … tools/procrun.py`
directly. **That no longer reproduces on this tree** and the sweep command is the
one to use — see §"What is measured, and what is not" for why: the file's host
imports now win, because the frame pass runs before imports resolve.)

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

## What landed

`formal/model.py`, exactly the shape §"The exact next step" above asked for, with
one addition that next step did not foresee and that is the load-bearing part of
the fix:

* `assigned_value_base_name(value, decls)` — the classifier. A literal (container
  or scalar) names its type and is therefore **provably not a frame address**. A
  bare-constructor call `S()` names `S` **only when `decls` says `S` is a struct
  this module declares**, because `self.x = make()` is a call to a *function* and
  reading it as "a type that is not a struct of this unit" would answer the frame
  question "provably not a frame" about a slot that may well hold a frame. Without
  `decls` the constructor row contributes nothing — the absent answer, which can
  neither place a frame nor suppress a frame diagnostic. **This is the one thing
  in the fix that is not a lookup, and getting it wrong is silent rather than
  loud**, so it is the first thing to re-read before changing anything here.
* `struct_init_field_types(struct_def, decls)` — unanimity or nothing, exactly
  `ValueKinds._bind`'s discipline, over every assignment spelling.
* `struct_init_field_type_why(struct_def, name, decls)` — the negative half, so a
  refusal says WHICH evidence was read and rejected instead of "no evidence".
* `struct_field_declared_type(struct_def, name, decls)` consults it **only when the
  class body spells no annotation**, and `decls` is threaded down through
  `field_type_rows` → `frame_field_type_candidates` / `field_type_is_value` /
  `frame_slot_declared_annotation` and out to both backends' `_structs` table. An
  annotation is an explicit statement of type and nothing assigned later talks it
  out of it; a class body that declares nothing has said nothing at all.
* `__slots__` needed no source of its own, as §(1) of the next step guessed: it
  declares the field SET with no annotation, and `struct_field_names` has always
  counted its names, so it could add nothing to *this* function.

`decls` is also what keeps the narrowing true: `struct_nested_frame_fields` still
excludes every field `struct_fields_written_outside_init` reports, `__init__`
included in that exclusion, so a written field is still `_REASSIGNED`.

`test_formal_run.py`'s `INIT_FIELD_TYPE_CASES` / `INIT_FIELD_TYPE_REFUSALS`: five
cases build, EXECUTE and match CPython, seven refuse with the same words on both
architectures. One of the five deliberately does NOT match CPython — a class-level
default of 7 with `self.limit = 99` in `__init__` returns 7 on both backends and
99 under `python3`, which is premise (B2) and is pinned as such.

## Where the ten files land

Measured with `python3 tools/formal_sweep.py` on exactly the ten files, on both
architectures where the refusal is the backend's and not the sweep's:

```
$ python3 tools/memslot.py --gb 8 --label measure-row10 -- \
      python3 tools/formal_sweep.py tools/procrun.py test_myinterpreter.py \
        test_myinterpreter_simple.py test_myinterpreter_validation.py \
        test_phase2_parser.py test_phase2_parser_simple.py \
        test_phase3_codegen_simple.py scripts/stage2_mojo_interpreter.mojo \
        formal/arm64_codegen.py formal/x86_64_codegen.py
[arm64] 10 files: PASS=0 not-pass=10
```

**0 reach `pass`.** The row's own table was right that these are all one shape and
wrong that one shape is therefore ten files of work; here is where each lands:

| files | new terminal cause | what it is |
|---|---|---|
| 5 | "a `Interpreter` receiver is returned from the function that created it" (3) / "… is stored in a container" (2) | rows 5 and 9 of the map — the frame-LIFETIME family, `bugs/FORMAL_wide_receiver_by_reference.md`. `Interpreter.__init__` binds `self.scope` and never returns `self`, but these tests return the object. |
| 3 | leave the `codegen` class: `test_myinterpreter.py` and `tools/procrun.py` on `import 're'`, `test_myinterpreter_simple.py` on `import 'types'` — all host modules | nothing more to fix in this row: the file is `not-answerable`, and the sweep had already been recording the host import in its "also imports a host module" line. Note the ORDER: `formal/build.py`'s frame pass runs before imports resolve, so a frame refusal used to be reported *instead of* the import diagnosis (`_defer_subscript_escape`'s docstring is about exactly this), which is why these three reported a codegen finding before and a host import now |
| 1 (`formal/arm64_codegen.py`) | `self._untyped_callee` — and the message is now TRUE | row 13's shape: a method of the struct used as a value. See `formal/model.py`'s `member_read_without_a_field`, and `bugs/FORMAL_field_set_method_name_and_kwarg_blind_spot.md`, which is why this one reports as a method at all |
| 1 (`formal/x86_64_codegen.py`) | `self._vkinds` | a per-function cache stored on `self` by an EXECUTED method — the exact shape §"The narrowing" refuses, and correctly |

So the row was worth **one false diagnostic removed and ten files moved**, and
what it was actually worth in `pass` is zero — the third measured ceiling of zero
in that map, after rows 2 and 3.

## What is measured, and what is not

* The 10 files and the exact refusal text: `bugs/FORMAL_sweep_work_map_2026-09-30.md`
  row 10, from the 2026-09-30 arm64 sweep on current master.
* The reproducer and both missing evidence sources: `tools/procrun.py`'s `Tail`,
  built on current master with nothing else changed.
* **The ceiling: 0 of 10**, by the re-sweep above, and the destination of each
  file, in the table above.
* **The `Tail` shape on its own, with nothing else in the file.** `Tail` lifted
  out of `tools/procrun.py` into a six-line class reaches the honest diagnostic
  about a list on BOTH architectures —
  `build: list.append() is not lowered on the formal <arch> path` — where before
  it was refused with a frame-layout diagnostic about `_chunks`. That is pinned
  as `init_assigned_container_reaches_the_value_method_refusal`.
  Note the ORIGINAL repro command in §"The refusal" no longer reproduces
  verbatim on this tree: `tools/procrun.py` imports `re`, `os`, `signal`,
  `subprocess`, `sys`, `tempfile` and `threading`, so the build now reports the
  host import before the frame pass would have. `formal/build.py`'s frame pass
  runs before imports resolve, which is why the sweep reported the codegen
  finding for years and the direct build now does not — `_defer_subscript_escape`'s
  docstring is about exactly this ordering. The finding itself is reproduced by
  the isolated class, and the sweep's own line records the host import for this
  file on every run.
* **NOT measured: a full-corpus sweep.** The change widens what
  `struct_field_declared_type` can answer for every struct in the tree, and only
  the ten files above were re-swept. `make gate`'s `stdlib-syntax` and
  `stdlib-dylib` verdicts are the numbers that would catch a regression here, and
  this worker did not run them.
