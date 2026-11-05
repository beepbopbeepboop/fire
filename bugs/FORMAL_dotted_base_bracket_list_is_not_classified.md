# FORMAL_dotted_base_bracket_list_is_not_classified: the predicate answers no for every dotted base, and the asking pass cannot have the table it needs

**Status: still not fixed, and the filing's proposed fix is one layer away from
reachable — which is the new fact here, measured on this tree (2026-10-02,
`work/formal8-5`).** The remainder of `FORMAL_type_argument_read_as_a_container.md`
(deleted in `30e5e2e9`, which closed the half that could be closed). Re-measured
below, both halves of the claim, so a reader does not re-derive them. The fix
that precedes it is what makes the boundary visible:
`model.subscript_index_is_a_comptime_parameter_list` says yes for a BARE NAME it
can classify and no for everything else, and everything else includes the two
shapes the corpus writes most.

No stdlib file is measured against this today — the four files map rows 7 and 8
of the sweep work map tracked all reach a bare-name base (`Pointer`,
`UnsafePointer`, `_DequeIter`). So this costs 0 files and is here for the reader
who writes the next one, not as a queue item.

## What is still wrong

A subscript over a dotted base is a comptime parameter list whenever the dotted
name is a type, and a runtime index whenever it is a value, and the two are told
apart here **only** by whether the base is a bare `IdentExpr` the model
classifies (`formal/model.py`'s
`subscript_index_is_a_comptime_parameter_list`):

```python
    name = _base_name(e.obj)      # None for anything but a bare name
    if name is None:
        return False
```

Re-measured, both architectures, the three rows the filing names:

| source | refused as | what it actually is |
|---|---|---|
| `external_call["setenv", c_int]` (`std/os/env.mojo:22`, **55 files**) | `is a subscript whose index is a tuple … a lookup keyed by the tuple, or a two-dimensional index` | a template application at a concrete type argument — **FIXED** by `model.type_position_nodes`, and **not this row's work**: it belongs to `formal-extcall-tuple`'s `construct:external_call-tuple-subscript`, which is what `FORMAL_known_limits.md` §6.2 documents |
| `h.tag[Int, s]` — a field read as a subscript base | `a S receiver is stored in a container, which has no layout for a frame address on this path` | **unknown**, and possibly a real container index |
| `h.tag[Int, s]` — the same, reached through the escape check's other branch | `is stored in a container` | **unknown**, for the same reason |

Measured on this tree with the filing's reproducer verbatim (`.tmp/p/dotted.mojo`,
a two-field `S`, a two-field `Alias`, and `var m = h.tag[Int, s]`), arm64 and
x86-64 identically, and the control too:

```
$ python3 fire.py build --formal --no-prove --backend=arm64 -o dotted.out dotted.mojo
build: a S receiver is stored in a container, which has no layout for a frame
  address on this path: the receiver of a multi-field struct is the ADDRESS of a
  frame of 8-byte slots that belongs to the function which created it …

# struct Iter[O: AnyType] / def mk(r: Int) -> Iter[Int] / mk(n).v
$ python3 fire.py build --formal --no-prove --backend=arm64 -o iter.out iter.mojo
Built: iter.out  [arm64/macho]
```

The control is the filing's own point and it still holds: the shape the corpus
writes most, `Self.IteratorType[origin_of(self)]`, has a **single** index, so
there is no bracket list for the container check to mistake, and the parser
reduces a single-element `Iter[origin_of(r)]` in a return annotation to the bare
name `Iter` — the parameter list is not in the tree at all. **It needs a comma
in the brackets**, and this predicate is what would have to answer for it.

## The new fact: the asking pass cannot have the table the fix needs

The filing says the fix is one more table in `formal/imports.py` — a
`{exported_name: kind}` per imported module, threaded into
`subscript_index_is_a_comptime_parameter_list` beside `structs_by_name`. That is
right about the table and wrong about reachability, and the distance is worth
recording because it is invisible from the predicate's signature:

* The predicate has exactly **two** callers, and both are reached from inside
  `_frame_receivers`: `formal/build.py`'s `_check_frame_escapes` (the
  `type_index_ids` comprehension) and `model.multi_index_kind`.
* `_frame_receivers` is called by `_prepare_functions`, which its own docstring
  describes as running "**BEFORE** `_resolve_imports` — it is the pass that has
  the statements and not the link line". At that point there are no manifests, so
  `dylib_export_tables` answers nothing, and no imported source has been parsed.
* `_check_frame_escapes` is handed `imported` — the module NAMES from the
  statements — and not the link line. So the only way to have the table at the
  asking point is to resolve and parse every imported module's source INSIDE
  `_prepare_functions`, which duplicates the parse `formal/imports.py` does
  moments later and is the layering this file's comments argue against in half a
  dozen places.

The alternatives, and why each is worse:

* **Ask the predicate again later**, once imports have resolved. There is no
  later: the escape check is the thing being satisfied, and by then the frame
  escape has already been decided.
* **Widen `_base_name` and resolve the dotted spelling against this image's own
  declarations** (`Self.X` against the struct being compiled). This is the
  narrowing the filing explicitly warns against, and it is right to: it makes
  `Self.X` and `h.tag` the same answer, and `h.tag[Int, s]` may be a genuine
  index of a genuine value, so answering "type application" for it drops a real
  escape check. Only a RESOLVED name can be classified, and the resolution for
  the interesting case is in another module's source.

So the honest next step is not a table but a **layering decision**: either the
imported declarations are parsed before the frame analysis (and the parse is
shared rather than duplicated), or the escape check moves after the imports and
takes the tables as an argument. Both are bigger than this predicate and neither
is a patch to it. Until one of them happens, a bracket list over a dotted base
stays refused, which is the safe direction and the one
`POINTEE_WIDTHS`'s own comment names ("the absence is the safe direction").

## What it costs

Zero swept files, re-confirmed rather than assumed: the four files map rows 7 and
8 of the sweep work map tracked all reach a bare-name base (`Pointer`,
`UnsafePointer`, `_DequeIter`), and `Self.IteratorType[…]` is a single index.
This document is written down for the reader who writes the next `Foo[A, B]` and
finds the backend cannot classify `Foo`.

## Pinned, and stays a limit rather than becoming an accident

`a_bracket_list_over_a_dotted_base_is_still_refused` in `test_formal_run.py`,
on both backends.
