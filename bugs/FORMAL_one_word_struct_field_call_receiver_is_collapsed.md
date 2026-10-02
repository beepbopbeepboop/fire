# FORMAL_one_word_struct_field_call_receiver_is_collapsed: `self.f.m(x)` in a ONE-FIELD struct becomes a call to the OUTER struct's own `m`, and the refusal that catches it names a name the source never spells

**Area:** FORMAL (`formal/build.py`, `_rewrite_self_fields` and the holder
fixpoint's `nested_fields` loop). **Status: OPEN — a mis-dispatch whose only
backstop is a check that reports the wrong name. NOT FIXED HERE**: the two
candidate fixes were both measured and neither is a production-quality change
(§ "What was tried"), so what is left is the diagnosis and the next step.

Filed from the `std-c` slice of the 2026-10-02 formal sweep
(`bugs/FORMAL_sweep_work_map_2026-10-02_std-c.md`).

## What I ran

```
$ /opt/homebrew/bin/python3.14 fire.py build --formal --no-prove \
      ../new-modular/Mojo/stdlib/std/builtin/builtin_slice.mojo
build: builtin_slice.mojo imports 'std.format._utils', which cannot be built
either: builtin_slice.mojo: StridedSlice_write_to: self.write_to is not a field
of StridedSlice — write_to is one of its METHODS, and nothing in StridedSlice
stores into an attribute of that name, so in Python this expression is the bound
method. …
```

Reduced to the smallest program that still shows it (both build the module
`builtin_slice.mojo` does not, and neither lowers it):

```mojo
struct Inner:
    var a: Int
    var b: Int

    def get(self) -> Int:
        return self.a + self.b

struct Outer:
    var inner: Inner

    def get(self) -> Int:
        return self.inner.get()
```

```
build: one.mojo: Outer_get: self.get is not a field of Outer — get is one of
its METHODS, and nothing in Outer stores into an attribute of that name, so in
Python this expression is the bound method. …
```

## What I expected

`Inner_get`. The source calls a method of `Inner` on a field of `Outer`; the
declared type of that field says what is in the slot; and this path already has
the machinery that reads a field's declared type and dispatches on it —
`model.frame_field_type_candidates` behind `_typed_nested_frame`, which is what
resolves `h.a.m(x)` for a **frame holder** `h`.

## What is wrong, in one sentence

**`_rewrite_self_fields` collapses `self.f` to `self` for a one-field struct
UNCONDITIONALLY — including when `self.f` is the RECEIVER of a call — and
collapsing the receiver of a call changes which struct's method the call names,
so `self.inner.get()` is rewritten into `self.get()`: a call to `Outer`'s own
`get`, i.e. unbounded recursion wearing the source's syntax.**

`formal/build.py`'s own comment on `_rewrite_self_fields` says what the
rewrite is for — "a one-word struct's field and its receiver are the SAME
storage" — and that is true of a *read*. It is not true of a call receiver:
`self.inner` and `self` are the same WORD, but `Inner.get` and `Outer.get` are
not the same METHOD, and the rewrite keeps the method name while replacing the
thing it is looked up on.

### The evidence chain, measured

`_rewrite_self_fields` is reached with `mapping = {"self": "inner"}`, from
`if st is not None and M.struct_is_one_field(st): mapping["self"] = _sole_field_name(st)`
(`formal/build.py:8975`). Before that, `_rewrite_method_calls` ran
(`:8962`) and did **not** rewrite the call, because its receiver is a
`MemberExpr` and it only rewrites a plain `IdentExpr` receiver — which is
stated in `_rewrite_nested_method_calls`' docstring and is the reason that
function exists. So the order is: the call is left alone, then the field access
underneath it is collapsed, and what is left is a call to the outer struct.

`_rewrite_nested_method_calls` is the pass that WOULD have resolved it, and it
does not fire here for two independent reasons, both measured:

* **its table is never populated for this function.** `nested_fields` is built
  inside the holder fixpoint, and that loop opens with
  `if not hs and not _stores_a_frame_returning_call(...): continue`
  (`formal/build.py:3136`). `Outer.get` holds no FRAME — a one-field struct's
  receiver is a word handed over by value (`struct_is_framed(Outer)` is False) —
  so `hs` is empty, the function is skipped, and `nested_fields` is `{}` for it.
* **even with the table, the method name is ambiguous.** `nested_fields` is
  only filled for `len(declared) == 1` (`:3206`), where `declared =
  by_method.get(node.member)` is keyed by BARE method name. In
  `std/builtin/builtin_slice.mojo` THREE structs declare `write_to` — `Slice`,
  `StridedSlice`, `ContiguousSlice` — so the call is skipped as ambiguous.

Everything else needed to resolve the call is already computed and agrees:

| question | answer, measured on `builtin_slice.mojo` |
|---|---|
| `struct_frame_slots(StridedSlice)` | `['_inner']` |
| `frame_field_type_candidates([StridedSlice], '_inner', decls)` | `Slice`, `(disagree=False, …)` |
| `struct_fields_written_outside_init(StridedSlice)` | `set()` |
| `struct_nested_frame_fields(StridedSlice, decls)` | `[('_inner', 0, Slice)]` |
| `struct_is_one_field(StridedSlice)` / `struct_is_framed` | `True` / `False` |

So `struct_nested_frame_fields` says the slot holds a nested `Slice` frame, and
the dispatch that would place it is unreachable for this function. The two rules
are not in conflict here, by the way: with the slot holding a nested frame
address, the one-word struct's word IS that address, so `self` and
`self._inner` are the same word and the elision is right — only the METHOD
LOOKUP is not.

### Why nothing is wrong today, and what would be

`check_value_position_method_reads` (`formal/build.py:3997`) refuses it, and it
is right that there is a problem. Its message is what is wrong: `node.member`
is `write_to` and `node.obj.name` is `self`, both read off the tree **after**
the rewrite, so the sentence says "`self.write_to` is not a field of
`StridedSlice`" about an expression the source does not contain, calls the
expression "the bound method", and tells the reader to "call it
(`self.write_to(...)`)" — which is the recursion. The check's own docstring
says it is asked of "every demoted read" because a node walk cannot tell a
callee from a value; the rewrite removes the one piece of evidence (`node.obj`)
that would have told them apart, so the check is now certain about a shape it
cannot see.

If that check were removed, or if the demoted set were empty for that struct,
the program would build and recurse forever.

## Exposure, measured on the `std-c` slice

`python3 tools/formal_sweep.py` over `std/` minus `std-a`/`std-b` (118 files,
arm64): **9 of the first 78 files classified name this refusal as their
terminal reason** — `builtin_slice.mojo: StridedSlice_write_to: self.write_to
is not a field of StridedSlice`. Every one of them reaches it through an import
(`std.memory`, `std.collections`, `std.traits`, … → `std.builtin`), which is the
whole-eager-closure property `FORMAL_dylib_export_gate_ceiling.md` §2 measures.
The other 5 `write_to` structs in that one file (`Slice_write_to`,
`ContiguousSlice_write_to`, and `write_repr_to` × 3) are the same shape waiting
behind the first refusal.

## What was tried, and why neither change landed

Both were implemented, measured, and reverted; the tree carries neither.

1. **Do not collapse a call receiver** (`_mark_call_receivers` tagging every
   `MemberExpr` that is a call's object, and `_rewrite_self_fields` returning
   the node unchanged for a tagged one). It removes the mis-dispatch: the
   refusal becomes `the image would bind 1 symbol(s) that nothing provides:
   self.inner.get`, which at least names the symbol the source spells, and
   `builtin_slice.mojo` moves off the misleading message onto a real one
   (`StridedSlice___init__ returns a frame address, so it cannot be compiled
   into a dylib`). But it LOWERS nothing: `self.inner.get` is an unresolved
   symbol, so the sweep class moves from a `codegen` finding to
   `not-answerable/unresolved-extern`, and a coverage report that trades a
   finding for a non-finding is worse, not better. It is a better DIAGNOSIS and
   a worse INSTRUMENT, and only the first is what this doc is for.
2. **Narrow the ambiguous method name by the receiver field's declared type**
   (`_owner_from_receiver_type`, calling `M.frame_field_type_candidates` on
   `cands` and the chain's outer field and keeping the one declaring struct it
   names). This is the right rule and it is the second half of the next step —
   but it measured **no effect at all** on this tree, because the function is
   skipped by the `if not hs` `continue` before the table is ever consulted. It
   would be dead code today, and a change with no measured effect is not a fix.

## The next step, exactly

**Let the holder fixpoint visit a function whose receiver is a one-field struct,
and resolve the call there.** The two halves, in the order they must be done:

1. **Do not `continue` past a function whose only "holder" is a one-field
   struct's receiver.** That `continue` is there for a measured reason (the
   `xs[1] = make(5)` subscript escape) and gating it on `hs` is what excludes
   every one-field struct. The narrow form: keep the `continue`, and give
   `_rewrite_nested_method_calls` its own pass over the functions the fixpoint
   skipped, with `nested_fields` built from `struct_nested_frame_fields` and
   `by_name[fn]` — the same table, read outside the loop that cannot reach it.
   Nothing new has to be decided, only moved.
2. **Then the `len(declared) == 1` gate** becomes the wrong question for a
   depth-2 chain and needs `_owner_from_receiver_type`: a field's declared type
   names the owner even when a bare name does not. The comment at
   `formal/build.py:3200` gives the right reason for the gate (`x.m()` with an
   untyped `x` really is name dispatch) and it keeps holding for depth 1.

**And one thing to check before starting**, because it decides whether this is a
two-line change or a design question: `StridedSlice.__init__` writes
`self._inner = Slice(start, end, stride)`, and a nested-frame field initialised
by a CONSTRUCTOR CALL is refused elsewhere
(`constructing B with the call to 'A' as field 'a' is refused on this path`,
measured on a four-line reproducer). If that refusal also fires for
`StridedSlice`, then the nested-frame route is closed for this struct and the
honest answer for `builtin_slice.mojo` is the representability limit, not a
dispatch fix — in which case the valuable half of this change is
`check_value_position_method_reads` learning to say "the rewrite collapsed this
receiver" instead of naming `self.write_to`.
