# FORMAL_dataclass_runtime_reflection: `dataclasses.fields()` / `is_dataclass()` ask what a VALUE's type is, and a value here is one word with no type tag

**Status: OPEN, and it is a property of the value model rather than a gap in
the transform — and the "next bounded action" below is now MEASURED, and its
answer is the second branch.** The `@dataclass` DECORATOR half is implemented
and tested (`formal/dataclass_transform.py`, `test_dataclasses_formal.py`);
this document is about the other half, the runtime reflection, which is what
`ownership_check.py` and `mojo/backend_gimple/cpp_core.py` actually call and
which cannot be implemented on this target at all.

**The measurement (2026-10-03, this tree): 0 of the 3 `dataclasses.fields(…)`
sites have a statically known receiver type, and all 3
`getattr(node, f.name)` sites inherit that** — `KNOWN: 0 POLYMORPHIC: 6` by
`tools/dataclass_reflection_sites.py`. So the front-end transform the paragraph
below weighs is NOT the shape these two files want — they want a type-carrying walker, and the
backend wants nothing. The numbers, the method and what they decide are in
§"The measurement the doc asked for", below.

Found while writing the module for the formal backend (2026-09-29, the
`module:dataclasses` claim). Every measurement below is from this tree.

---

## What I ran

`ownership_check.py` and `cpp_core.py` use the module like this:

```python
def _is_node(x):
    return dataclasses.is_dataclass(x) and not isinstance(x, type)
...
for f in dataclasses.fields(node):          # node: a parameter, untyped
    _walk_expr(getattr(node, f.name), ...)
...
return dataclasses.replace(node, **changes) if changes else node
```

Measured on this tree:

```
$ python3 tools/formal_sweep.py --no-stdlib ownership_check.py mojo/backend_gimple/cpp_core.py
NOT-ANSWERABLE/HOST-IMPORT: ownership_check.py  (… imports 'dataclasses' …)     # before
```

and, with the module implemented, the same two files are refused by name at the
call site — `dataclasses.is_dataclass() asks what a VALUE's type is, and a
value on this path is one 64-bit word — or, for a struct of more than one
field, the address of a frame of 8-byte slots — with no type tag attached to
it` — which is progress for the reason the task states: the next refusal names
the construct.

## Why it cannot be a runtime module

Three measurements, and the third is the one that settles it:

1. **There is no type tag to ask with.** `formal/model.py`'s comment above
   `GlobalSymbol` states the rule: *"every value a formal program can name
   lives in a function's own stack scratch … and that scratch is reclaimed when
   the function returns"*. A value is one 64-bit word. A struct of more than one
   field is the ADDRESS of a frame of 8-byte slots. Neither carries anything
   saying which class it is, so `is_dataclass(x)` has nothing to compute from.

2. **A struct cannot even be passed.** Measured, `.tmp/dc/u1.py`:

   ```python
   import dataclasses
   class Point: x: int; y: int
   def main(n):
       p = Point(3, 4)
       if dataclasses.is_dataclass(p):   # refused before the call is emitted
           printf("is_dc")
   ```
   ```
   build: a Point receiver is passed to dataclasses.is_dataclass in argument
   position 0 … lowered as an operation on a VALUE: it wants the object
   itself, and on this path a multi-field struct has no value form
   ```
   That is `model.frame_receiver_escape_refusal`, and it fires for ANY callee.
   `hash(c)` is refused for the same reason (measured, `.tmp/dc/b1.py`).

3. **So a perfect `fields()` could not be REACHED.** (2) is the decisive one.
   A `formal/hostmods/dataclasses.mojo` exporting `def fields(x)` would compile
   into a dylib, be linked, and then be called with a word that says nothing
   about its class — and the callee has no way to find out. Implementing it
   "well" is not possible; implementing it *at all* would mean returning a
   fixed answer, which is the wrong answer.

## The part that IS a loop, and would need the front end

There is a second, separable obstacle, and it is worth recording because it
would still be there after (1)–(3) are solved:

```python
for f in dataclasses.fields(node):
    _walk_expr(getattr(node, f.name), ...)
```

`getattr(node, f.name)` is a DYNAMIC field read — the name is a run-time
value. **Status 2026-10-04 (`formal29-1`): the sentence after this one is now
WRONG in two directions and both are fixed; the conclusion is unchanged.** The
old text said `getattr(x, "a")` "does not lower at all; the image binds a symbol
nothing provides". Measured on this tree today, with a LITERAL name it is
REFUSED — `model.UNIMPLEMENTED_BUILTINS["getattr"]` exists and names the limit —
and with a literal name it now LOWERS, because `getattr(p, "a")` is `p.a` and
this backend has always lowered that. See "What landed 2026-10-04" at the end.

So even a hypothetical `fields()` that returned the right names would be
followed by a loop the backend cannot express, because the field to read is not
known until the loop runs — and that is now a statement about the loop alone,
with the name half measured rather than described.

Answering it would mean unrolling the loop in the front end, at the point where
the static type of the receiver IS known, turning

```python
for f in fields(x): body(f.name)
```

into `body("a"); body("b")` with `x.a` and `x.b` substituted. That is a
general loop-unrolling transform, it is not specific to `dataclasses`, and it
is a project rather than a patch. `ownership_check.py`'s `_walk_expr` is
recursive over an AST, so the unrolled body is a call per field per node, and
the node count is not known until run time — so the transform would have to
unroll at EVERY level of a recursion, which is a much larger thing than a loop
unroller.

## What would close it, and what it would cost

**Nothing on this path, for the reflection half as written.** The blocker is
the value model, and closing it means changing what a formal value IS: a value
carries a type tag (a small index into a per-image table of class names and
field layouts), which is a change to `formal/model.py`'s value representation
AND to the Lean proof (`lib/ProofLib.lean`'s `Value` is one word — the same
change `bugs/FORMAL_module_state_no_storage.md` describes for module state, and
for the same reason). That is the `bugs/FORMAL_contract_work_handoff.md` shape
of work: a model change plus a proof, not a codegen change.

**The alternative, and the one the corpus actually needs**, is to answer the
question AT COMPILE TIME where the static type is known — which is what
`dataclasses` in CPython already is for the declaration half, and what
`formal/dataclass_transform.py` does. The obstacle is that the call sites in
`ownership_check.py` and `cpp_core.py` are *generic over the node's type*:
`_walk_expr(node, …)` takes an untyped parameter, so there is no static type at
the call site to answer from. Converting those files to a compile-time answer
means giving the walker a type — an enum, or a per-class dispatch table — which
is a change to those files, not to the backend.

**Next bounded action**, if someone picks this up: measure how many of the
`dataclasses.fields(...)` / `getattr(node, f.name)` sites in the two files have
a statically known receiver type. If it is most of them, a front-end transform
that answers `fields(x)` for a known `x` and refuses it for an unknown one is
days, and it is the same seam `formal/dataclass_transform.py` already occupies.
If it is few, the files want a type-carrying walker instead and the backend
wants nothing.

## The measurement the doc asked for (2026-10-03)

The "next bounded action" above, done — reading the two files' ASTs rather than
their text, because a `grep` counts `getattr(gen, '_cpp_gen_self_struct', None)`
on generator state, which is a different question and 95 of the ~97 `getattr`
calls in `cpp_core.py`. The census is committed as a tool so the numbers below
are re-derivable rather than re-typed:

```console
$ python3 tools/memslot.py --gb 8 --label m -- \
      python3 tools/dataclass_reflection_sites.py
KNOWN: 0   POLYMORPHIC: 6
```

**`dataclasses.fields(…)` — three sites, none of them with a known receiver:**

| file:line | the call | the receiver | who reaches the enclosing function |
|---|---|---|---|
| `ownership_check.py:321` | `for f in dataclasses.fields(node)` | `_walk_expr`'s FIRST PARAMETER | 28 call sites, **18 distinct argument shapes** (`node.obj`, `stmt.value`, `operand`, `tgt`, `a`, `v`, `item.expr`, lists and tuples of them …), over the 23 AST classes the file names in `isinstance` guards |
| `ownership_check.py:587` | `for f in dataclasses.fields(stmt)` | `_check_stmt`'s first parameter | 1 call site, 1 shape — and that parameter is the STATEMENT walker, so "1 call site" means "every statement the file walks", not "one type" |
| `mojo/backend_gimple/cpp_core.py:1320` | `for f in dataclasses.fields(node)` | `_cpp_rename_ident`'s first parameter | 3 call sites with 3 shapes (`v`, `c`, `elem_node`), reached through `_cpp_rename_ident_container`'s `is_dataclass(v)` test — so it is "whichever dataclass node was handed down" |

**`getattr(node, f.name)` — three sites, one per `fields()` loop**, and none is
answerable independently: the attribute name is the loop variable `f`, so
removing `fields()` removes the answer with it. That is this document's "even a
hypothetical `fields()` that returned the right names would be followed by a
loop the backend cannot express", confirmed rather than restated.

**One more fact that decides it faster than the counts do: NEITHER file
declares the dataclasses it reflects over.** `ownership_check.py` declares one
`@dataclass` of its own — `Diagnostic`, measured 4 fields — and never passes it
to `fields()`; its `fields()` calls are about `fire_compiler`'s node classes,
reached through `_is_node(x) = dataclasses.is_dataclass(x) and not isinstance(x,
type)`. `cpp_core.py` declares none. So a front-end transform would have to
enumerate the field layouts of a module this path already refuses to place
(`fire_compiler` is `not-answerable/host-import`), for a walker that has no
static type at any of its three sites.

**What the answer is for.** It settles the question this section posed — "is
this days of transform or a change to the two files" — in favour of the second:
a type-carrying walker (an enum parameter, or a per-class dispatch table
threaded through `_walk_expr` / `_check_stmt`) is a change to THOSE FILES, and
after it a compile-time `fields(x)` would be answerable at three sites instead
of none. Until then the three refusals by name (`fields`, `is_dataclass`,
`replace`, and the `getattr`/`hasattr` spelling) are the honest answer, and they
are what `formal/dataclass_transform.py` already does.

## What is deliberately NOT being done here

`formal/dataclass_transform.py` refuses each of these names BY NAME, at the
call site, with the reason above — `is_dataclass`, `fields`, `asdict`,
`astuple`, `replace`, `__dataclass_fields__`, and the `getattr`/`hasattr`
spelling of the same question. That is the honest answer and it is pinned by
`test_dataclasses_formal.py`'s three reflection cases, which assert on the
message rather than only on the build failing. What is refused here is not
implemented, and the word "implemented" is doing no work it has not earned.

## What landed 2026-10-04 (`formal29-1`): `getattr(o, "name")` with a LITERAL
## name is the field read, and the refusal's reason was false for it

This is the `getattr` half of "What is deliberately NOT being done here", and it
is the one part of it that was **wrong rather than unimplemented**.

`model.UNIMPLEMENTED_BUILTINS["getattr"]` read, and this is the measured text:

> the attribute it names is a STRING at run time, and a field read on this path
> is a load from `[base, #8k]` with a slot index the build computed from the
> struct's own field list; a frame has no element width and no length, so a
> run-time-indexed read of one is not an address arithmetic question this backend
> can answer

and it refused this, identically on arm64 and x86-64:

```python
struct Pt:  a, b
def main(k): var p = Pt(); p.a = 7; p.b = 5
             var v = getattr(p, "a"); printf("getattr-a=%d", v)
```

**The name in that program is a literal.** There is no run-time string, no
unknown index, and no element width to establish: `v` is `p.a`, the slot comes
from `Pt`'s own field list and the read is `base + 8` — the read this backend has
always emitted. Four clauses of the sentence are false of this source, and the
one thing it does not say is the repair, because there is no defect to repair.
That is the failure mode the wide-receiver family documents itself as existing to
prevent: "a message that asserts a mechanism which is not operating sends the
reader after a non-bug", and its mirror — a message that asserts a limit which is
not operating.

**What landed**, and it is a REWRITE beside `_rewrite_identity_intrinsic_calls`
rather than an emitter branch, for the reason that function's own docstring
gives: every check downstream of `_prepare_functions` reads the AST, so a
lowering in an emitter would leave `getattr(p, "a")` in the tree the field-read
analysis has already classified.

* `model.LITERAL_ATTRIBUTE_READ_CALLS` + `model.literal_attribute_read` — the
  table is `{"getattr"}` and the predicate accepts a **bare string literal** and
  nothing else.
* `formal/build.py::_rewrite_literal_attribute_reads` erases `getattr(o, "name")`
  to `MemberExpr(o, "name")`, called immediately after
  `_rewrite_identity_intrinsic_calls` and for the same reason.
* the three siblings keep their own entries in `UNIMPLEMENTED_BUILTINS` with
  their own reasons, because each asks a different question: `hasattr` asks
  whether the attribute is THERE (a frame's slots are its whole layout, so there
  is no absent case), `setattr` is a store whose target is not a slot the build
  established, `delattr` removes one.
* `getattr`'s own entry now SAYS which case it is, and names the literal one as
  not it — so a reader who reaches it can tell in one clause that their program
  is not the case and that a different spelling is.

**The dynamic case is untouched, and that is the point.** `getattr(p, f.name)`,
`getattr(p, k)` and `getattr(p, "a" + b)` all still refuse, which is why
**this document's answer is unchanged**: all three `fields()` loops in
`ownership_check.py` and `mojo/backend_gimple/cpp_core.py` name the field with
`f.name`, so the loop the backend cannot express is still the loop, and the
front-end unroller is still what they would want. Measured on this tree after the
rewrite: both files are `codegen/dependency` behind `_syscalls.mojo`'s own
non-ASCII refusal, i.e. neither moved — which is the honest result and not a
disappointment, because the row they are in is the one this document measured.

**Files blocked: 0.** There are 11 `getattr(o, "literal")` sites in the corpus
and ten of them are in `formal/` and `mojo/backend_gimple/` — the compiler's own
sources, which this path does not compile as targets. What the change buys is
that a construct with two spellings answers both, and that the refusal is now
true of every program it reaches.

**Pinned four ways, and two of them are the boundary rather than the win**, which
is what makes the rewrite a rewrite and not a hole:

| row | what it pins |
|---|---|
| `test_formal_run.py`'s `getattr_of_a_literal_name_is_the_field_read` | the read is the SECOND slot (`b`, not `a`), both architectures — 3 + 4 = 7 laid out so a read at offset 0 would be visible |
| `getattr_defined_here_is_not_erased_to_a_field_read` | a module that DEFINES `getattr` keeps its own function (7, not 4) — the gate `_shadowing_attribute_read_names` exists for |
| `byref_refuse_getattr_of_a_computed_name` | `getattr(p, names[0])` still refuses, needle **"A LITERAL name is not this case"** — so a reword that dropped the clause fails here rather than leaving the right program refused with the wrong sentence |
| `byref_refuse_getattr_of_a_name_that_is_not_a_field` | `getattr(p, "zz")` is refused by the FIELD refusal (quoting `Pt`'s two real fields), not by a `getattr` message — which is the accurate answer about a name that is not in the layout |
