# FORMAL_dataclass_runtime_reflection: `dataclasses.fields()` / `is_dataclass()` ask what a VALUE's type is, and a value here is one word with no type tag

**Status: OPEN, and it is a property of the value model rather than a gap in
the transform.** The `@dataclass` DECORATOR half is implemented and tested
(`formal/dataclass_transform.py`, `test_dataclasses_formal.py`); this document
is about the other half, the runtime reflection, which is what
`ownership_check.py` and `mojo/backend_gimple/cpp_core.py` actually call and
which cannot be implemented on this target at all.

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
value. Measured, `.tmp/dc/p2.py`: `getattr(x, "a")` does not lower at all; the
image binds a symbol nothing provides. So even a hypothetical `fields()` that
returned the right names would be followed by a loop the backend cannot
express, because the field to read is not known until the loop runs.

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

## What is deliberately NOT being done here

`formal/dataclass_transform.py` refuses each of these names BY NAME, at the
call site, with the reason above — `is_dataclass`, `fields`, `asdict`,
`astuple`, `replace`, `__dataclass_fields__`, and the `getattr`/`hasattr`
spelling of the same question. That is the honest answer and it is pinned by
`test_dataclasses_formal.py`'s three reflection cases, which assert on the
message rather than only on the build failing. What is refused here is not
implemented, and the word "implemented" is doing no work it has not earned.
