# FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time: `collections.namedtuple` and `copy.deepcopy` are one missing capability, and it is a reflection table

**Status: item 1 LANDED (2026-10-02, `work/formal8-1`) and item 2 is ALREADY
IMPLEMENTED — measured on both architectures 2026-10-05 and now pinned by a row
that did not exist; item 3 (the reflection table) is still open and is the whole
of what is left.** Item 2 was recorded here for six weeks as "one capability with
an owner named, and neither is a light change", and that was wrong: the copy
construction lowering is in both emitters and answers CPython. What was MISSING
was not the lowering but the test that could tell a copy from an alias — see
"What item 2 turned out to be" below, which is also why the doc stays: item 3 is
open and a doc for an open bug is the right thing to have. Deliberately filed as ONE capability
rather than two modules. Split out of
`FORMAL_glob_copy_collections_io_not_attempted.md` — a measurement record of
`glob`, `copy`, `collections` and `io`, DELETED 2026-10-03 by `work/formal10-3`
with the fixes it recorded, its remaining actions withdrawn or filed elsewhere —
whose own text said this document "does not exist yet and should". A reader who
finds one of these two should be told about the other, because they are the same
missing thing. This is the part of that parent that is work.

## 1. LANDED: the host-import refusal now says what this target offers

The refusal was, in full:

    build: hm.mojo imports 'collections', which is a host module (CPython
    standard library), which has no Mojo source for this backend to compile

…which reads as "this target cannot do records", and the next thing a reader does
with that is file the next bug document about `collections`. It is now:

    build: hm.mojo imports 'collections', which is a host module (CPython
    standard library), which has no Mojo source for this backend to compile. The
    record the callers here want is a STRUCT: declare it with its fields, and
    read them as fields. What cannot be done is building the type at run time —
    `namedtuple("Census", "ok detail …")` asks for a type from a string, and there
    is no word on this path that denotes a type (doc/ABI.md, Generics).
    `Counter` is a dict rather than a record, so it is the other question: see
    bugs/FORMAL_listdir_no_run_time_sequence.md.

`formal/imports.py`'s `unresolvable_import_error` appends
`_host_module_advice(name)`, and `HOST_MODULE_ADVICE` has entries for
`collections`, `copy` and `functools` — **three, not every host module**, because
advice on all of them is the same noise in a different place, and a module with
no entry gets exactly the sentence it had. Both directions are pinned by
`test_formal_imports.py`'s
`a_host_module_refusal_says_what_this_target_offers` (the advice is present for
`collections`, and ABSENT for `itertools`), and the advice is a table beside the
rule rather than a paragraph inside it, so it is one edit per module and a
module that gains Mojo source stops being asked for advice at all
(`_is_host_module` answers False for it, which is the same fact
`test_formal_fcntl.py`'s `resolve` group pins for `fcntl`).

**The measurement below is refreshed, and it has grown.** Eleven non-test
sources in this repository now import `collections`, `copy` or `functools` (16
statements), not five: `formal/lean.py`, `formal/model.py`,
`tools/formal_sweep.py`, `tools/formal_sweep_causes.py`,
`tools/arm64_insn_audit.py`, `formal/build.py`, `myinterpreter.py`,
`mojo/middle/coro.py` (three statements), `mojo/middle/offload.py`,
`consolidate_string_pool.py`, `tools/apply_extraction.py`,
`tools/extract_family.py`, `version.py`, `tools/analyze_stdlib_errors.py`. The
`namedtuple` share is unchanged in kind — five call sites in four files — and
still none of them is converted by a module, because the thing they want is a
record the compiler can see.

**This is not a defect in anything that exists.** `formal/hostmods/` has no
`collections.mojo` and no `copy.mojo`, and the absence is correct: neither can
be written, and the reason is a capability this target does not have rather than
a module nobody has got round to. Writing either module alone would produce a
function whose name promises a graph walk and delivers an identity, which is the
outcome `FORMAL_hashlib_sha3_and_blake2s_absent` filed a decision rather
than shipping one.

## What item 2 turned out to be (measured 2026-10-05, both architectures)

**The copy construction lowers, and answers CPython.** `S(x)` for a
compile-time-known struct is a fresh block and a field-by-field copy, in BOTH
backends:

```mojo
struct Wide:
    var a: Int
    var b: Int
    var c: Int

def copyit(t):
    var u = Wide(t)
    u.a = u.a + 100
    u.c = 0 - 1
    return u
```

prints `105 6 -1|5 6 7` — the copy is mutated and **the original is untouched**,
which is the representation rule ("a clone of a framed struct is a fresh frame")
and the only thing that separates a copy from an alias. A `List[Int]` FIELD
copies as a reference and reads back correctly (`Box(a).xs[1]` is `2`).

**What was actually missing is the ROW that tells a copy from an alias.**
`test_formal_returned_frame.py`'s
`positional_init_and_copy_constructions_all_land_in_the_block` exercises
`Wide(t)` and checks that the fields LAND — and an ALIASED copy prints the same
numbers, so that row would pass either way. It is now joined by
`a_copy_construction_is_a_fresh_block_not_an_alias`, which mutates the copy and
reads the ORIGINAL; an alias answers `105 6 -1|105 6 -1` and fails. That row is
the coverage this doc's item 2 was really asking for, and it is why the item is
closed rather than re-specified.

**The oracle had to be written out field by field, and that is a fact about the
two languages rather than a shortcut.** Python has no `S(x)` copy construction —
`Wide(t)` there calls `__init__(self, t)` and raises `TypeError` — so the CPython
twin states the same program with three assignments. `copy.copy(t)` is the real
Python spelling and needs a host module this path does not have, which is §1's
gap and a backend refusal rather than something a backend row can lean on.

## What is missing, stated as one thing

**There is no way to make a NEW TYPE at run time, and no way to make a NEW
INSTANCE of a type the compiler did not see.** Two consequences, and they are
consequences rather than two features:

* `collections.namedtuple("Census", "ok detail …")` is
  `type(typename, (tuple,), class_namespace)`. It builds a class with N fields,
  an `__init__`, `__repr__`, `_asdict`, iteration and indexing. On this path a
  **type is not a value** — there is no word that denotes one — so it cannot be
  returned from a module function, let alone bound to a module-level name.
* `copy.deepcopy(node)` walks an arbitrary object graph: read every attribute,
  decide which are values and which are references, allocate a new object per
  node, repoint the edges. Allocating a new instance of an **arbitrary** type is
  the missing half, and discovering a type's attribute set at run time is the
  other. Guessing which attributes are edges gives a copy that shares structure
  it should not — a silent wrong answer, which is worse than a refusal.

They are one capability because both need the same two things: **a type
descriptor the runtime can read** (a name, a field count, per-field offsets and
kinds) **and a way to allocate an instance from it.** `doc/ABI.md`'s
Aggregates section already describes the first half for structs — passed by
pointer with a reflection-table layout — so the layout exists; what does not is
the *construction* half and the *read* half for a type chosen at run time.

## Who wants it, and what it is worth — MEASURED on this tree

Every file below stops at the host import on this tree, so none of them reaches
the call, and none of them is waiting for a module:

```
$ python3 -c "… compile_formal(<file>, arch='arm64', prove=False) …"
formal/lean.py              imports 'collections', which is a host module …
formal/model.py             imports 'collections', …
tools/arm64_insn_audit.py   imports 'collections', …
tools/formal_sweep.py       imports 'collections', …
mojo/middle/coro.py         imports 'copy', …
```

**5 files, 0 of which a module would convert.** The uses:

| file:line | use |
|---|---|
| `formal/lean.py:816` | `Census = collections.namedtuple("Census", "ok detail cached n_sorries lib_sorries lib_detail lines")` |
| `formal/model.py:13195` | `InitShape = collections.namedtuple("InitShape", "method params positional required optional")` |
| `tools/formal_sweep.py:1810,1860,1871` | `Missing`, `Verdict`, `BuildRun` — all `namedtuple` |
| `tools/arm64_insn_audit.py:94` | `counts = collections.Counter()` — a dict |
| `mojo/middle/coro.py:1645` | `new = copy.copy(call)` |
| `mojo/middle/coro.py:4639` | `return copy.deepcopy(node)` |

Five of the six are `namedtuple`, which is the honest headline: **the dominant
want is a compile-time-known record type with readable fields, not a
run-time-constructed class.** That matters, because a compile-time-known record
IS representable — it is a struct, and `formal/hostmods/struct.mojo` exists. So
the highest-value thing here is *not* the reflection table; it is that these five
call sites want to spell a record in Python and this target's answer is "declare
a struct", and a reader moving one of these files has to be told that in a place
they will look.

**`Counter` is not in this document.** `counts = collections.Counter()` is a
dict, which is the blob/crossing-a-boundary question, not the type-construction
one — `bugs/FORMAL_listdir_no_run_time_sequence.md` §"What is still missing"
already has that capability decomposed into four steps, and a dict is item (1)
there (`BLOB_KIND`) plus item (3) (a callee returning a container). One of the
five files above is blocked on THAT and not on this.

**`copy.copy` is not `copy.deepcopy`, and the difference is the whole of
`coro.py`.** `coro.py:1645` copies an AST node and then mutates the copy's
`args`/`kwargs`. Every node is a plain dataclass, so what it wants is a
field-wise copy of a type the compiler KNOWS at that call site — not a graph
walk and not a run-time type. That is much closer to representable than
`deepcopy`, and it is a strictly smaller piece of work: a shallow field-wise
clone of a compile-time-known struct, with the edges copied shallowly (which is
what `copy.copy` means). `coro.py:4639`'s `deepcopy` is the hard one and is not
reachable by the same step.

## The exact next step, in the order the uses justify

0. ~~**Say the answer where the reader is.**~~ **DONE** — see above. It
   converts zero files and it is the difference between a reader who knows what
   to do and a reader who files the next bug doc about `collections`.
1. **Say the answer where the reader is.** Five `namedtuple` call sites in this
   repository's own tooling want a record; the answer on this target is a
   `struct`, and nothing in the refusal for `import collections` says so. The
   cheapest real deliverable here is a line in the host-import refusal naming
   `namedtuple` and what this target offers instead — it converts zero files and
   it is the difference between a reader who knows what to do and a reader who
   files the next bug doc about `collections`.
2. ~~**`copy.copy` for a compile-time-known struct**~~ **DONE, and it was
   already done — measured on both architectures 2026-10-05, and the missing
   half was the test, not the lowering.** See "What item 2 turned out to be"
   above: `S(x)` is a fresh block and a field-by-field copy in BOTH backends,
   answers CPython, copies a `List[Int]` field as a reference, and is now pinned
   by `test_formal_returned_frame.py`'s
   `a_copy_construction_is_a_fresh_block_not_an_alias` — the row that can tell a
   copy from an alias, which the row it joins could not. `formal/model.py`'s
   `_frame_source_structs` is the recognition it rests on and its own docstring
   already states the refusal that keeps an unrecognised frame from being copied
   as eight bytes of unrelated memory.
   **What is still NOT answered here, and is the reason this doc exists**:
   `import copy` itself is a HOST module (`formal/hostmods/` has no
   `copy.mojo`, and cannot: `deepcopy` walks an arbitrary object graph), so a
   caller that writes `copy.copy(node)` still stops at the import. That is §1's
   advice sentence doing its job, not a gap in the copy construction.
3. **The reflection table** — a runtime-readable type descriptor and
   construction from it — which is what `namedtuple` at run time and
   `deepcopy` over an arbitrary graph both need, and which is the actual root
   cause. It is the largest item, it has no caller that checks it against
   anything but CPython, and it is **not** Phase 6's tagged-value convergence
   (`bugs/FORMAL_listdir_no_run_time_sequence.md`) — that is about a VALUE's
   representation, and this is about a TYPE's. They share the reflection table
   and nothing else.

## What is NOT the answer, so nobody proposes it again

* **Not a `collections.mojo` that raises.** A module whose `namedtuple` refuses
  is a module that moves no file and adds a message; the caller still cannot
  write the line. That is the same reasoning that kept SHAKE and blake2s out of
  `formal/hostmods/hashlib.mojo`.
* **Not `copy.copy(x) -> x`.** An identity for a scalar is correct, and for
  anything with a frame in it it is the use-after-free this backend's whole
  frame-lifetime analysis exists to prevent.
* **Not monomorphisation.** A `namedtuple` whose field list is a compile-time
  constant is a struct; a program that needs one cannot have it, and that is
  `doc/ABI.md` §Generics, not a narrowing of a check.