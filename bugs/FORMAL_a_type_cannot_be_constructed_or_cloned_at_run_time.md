# FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time: `collections.namedtuple` and `copy.deepcopy` are one missing capability, and it is a reflection table

**Status: OPEN, not started, and deliberately filed as ONE capability rather than
two modules.** Split out of `FORMAL_glob_copy_collections_io_not_attempted.md`,
whose own text says this document "does not exist yet and should" — that a
reader who finds one of these two should be told about the other, because they
are the same missing thing. That parent is a measurement record whose remaining
actions are withdrawn or filed elsewhere; this is the part of it that is work.

**This is not a defect in anything that exists.** `formal/hostmods/` has no
`collections.mojo` and no `copy.mojo`, and the absence is correct: neither can
be written, and the reason is a capability this target does not have rather than
a module nobody has got round to. Writing either module alone would produce a
function whose name promises a graph walk and delivers an identity, which is the
outcome `bugs/FORMAL_hashlib_sha3_and_blake2s_absent.md` filed a decision rather
than shipping one.

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

1. **Say the answer where the reader is.** Five `namedtuple` call sites in this
   repository's own tooling want a record; the answer on this target is a
   `struct`, and nothing in the refusal for `import collections` says so. The
   cheapest real deliverable here is a line in the host-import refusal naming
   `namedtuple` and what this target offers instead — it converts zero files and
   it is the difference between a reader who knows what to do and a reader who
   files the next bug doc about `collections`.
2. **`copy.copy` for a compile-time-known struct**: a fresh block and a
   field-by-field copy, with references copied as references. That is a
   LOWERING in both backends plus a representation rule ("a clone of a framed
   struct is a fresh frame"), and it is the same feature
   `bugs/FORMAL_frame_receiver_handoff.md` §4c already names as missing —
   "`S(x)` — a copy construction — has no lowering, for any struct and any
   argument. A fresh block plus an `n`-slot copy is a feature in both backends."
   **Do these as one change**: they are one feature with two call sites, and
   filing them separately is how they get half-built.
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