# FORMAL_dotted_base_bracket_list_is_not_classified: a subscript over a name this unit cannot classify keeps its refusal, and proving otherwise is `formal/imports.py`'s question

**Status: not fixed, and deliberately not guessed.** The remainder of
`FORMAL_type_argument_read_as_a_container.md` (deleted in `30e5e2e9`, which
closed the half that could be closed). It is written down because the fix that
precedes it makes the boundary visible: `model.subscript_index_is_a_comptime_parameter_list`
says yes for a BARE NAME it can classify and no for everything else, and
everything else includes the two shapes the corpus writes most.

No stdlib file is measured against this today — the four files
`FORMAL_frame_by_value_ceiling_zero.md` tracks all reach a bare-name base
(`Pointer`, `UnsafePointer`, `_DequeIter`). So this costs 0 files and is here
for the reader who writes the next one, not as a queue item.

## What is still wrong

A subscript over a dotted base is a comptime parameter list whenever the dotted
name is a type, and it is a runtime index whenever it is a value, and the two
are told apart here **only** by whether the base is a bare `IdentExpr` the
model classifies:

```python
    name = _base_name(e.obj)      # None for anything but a bare name
    if name is None:
        return False
```

So these keep their pre-`30e5e2e9` refusals:

| source | refused as | what it actually is |
|---|---|---|
| `external_call["setenv", c_int]` (`std/os/env.mojo:22`, **55 files**) | `is a subscript whose index is a tuple … a lookup keyed by the tuple, or a two-dimensional index` | a template application at a concrete type argument; `FORMAL_known_limits.md` §6.2 documents this one in full, and it is **not** mine — `formal-extcall-tuple` holds `construct:external_call-tuple-subscript` |
| `h.tag[Int, s]` — a field read as a subscript base, with no frame in it | the same sentence | **unknown**, and possibly a real container index |
| `h.tag[Int, s]` — the same, with a frame address in the list | `is stored in a container` (from `_check_frame_escapes`) | **unknown**, for the same reason |

The last two rows are why this is a limit and not a bug: the refusal is only
*possibly* wrong, and "possibly wrong" is the direction this backend refuses in
everywhere else (`POINTEE_WIDTHS`'s own comment: "the absence is the safe
direction"). What makes the first row worth writing down is that the source
says in so many words that it is a template application.

**The shape the corpus writes most, `Self.IteratorType[origin_of(self)]`, is
NOT in this doc**, and the reason is worth recording because it has been got
wrong twice in this area (once in the predecessor doc, once here). It has a
**single** index, so there is no bracket list for the container check to
mistake, and the parser reduces a single-element `Iter[origin_of(r)]` in a
return annotation to the bare name `Iter` — the parameter list is not in the
tree at all. Measured:

```python
struct Iter[O: AnyType]:
    var v: Int

def mk(r: Int) -> Iter[origin_of(r)]:
    return Iter(1)
```

```
$ python3 fire.py build --formal --no-prove -o d2.out d2.mojo
Built: d2.out  [arm64/macho]
```

It BUILDS, on the pre-`30e5e2e9` tree as well as this one. So the doc's
predecessor named the wrong undecidable case, and the right one needs a
**comma** in the brackets.

## The reproducer

```python
# .tmp/p/dotted.mojo
struct S:
    var a: Int
    var b: Int

struct Alias:
    var tag: Int
    var v: Int

def main(n: Int) -> Int:
    var s = S()
    s.a = 3
    s.b = 4
    var h = Alias()
    h.tag = 1
    h.v = 2
    var m = h.tag[Int, s]
    return s.a
```

```
$ python3 fire.py build --formal --no-prove -o dotted.out dotted.mojo
build: a S receiver is stored in a container, which has no layout for a frame
address on this path: …
```

Pinned as `a_bracket_list_over_a_dotted_base_is_still_refused` in
`test_formal_run.py`, on both backends, so the limit stays a limit rather than
becoming an accident.

## The exact next step

**It needs the imported module's declarations, and `formal/imports.py` is
already the place that has them.** The predicate currently answers from three
tables the compiling unit owns — the type-constructor names, this module's
structs, this image's generic `FunctionDef`s — and the fourth, "does the
IMPORTED module export this name as a type", is the one thing it does not have.

The shape of the change is one more table in the same place, not a new walk:
`formal/imports.py` already publishes each imported module's export set (it is
what decides `_extern_symbol`'s "this submodule exports the name at all"), so
the addition is a `{exported_name: kind}` per imported module, threaded into
`subscript_index_is_a_comptime_parameter_list` beside `structs_by_name`.

**Do not close it by widening `_base_name`.** Turning `Self.X` and `h.tag` into
the same answer is the one change that could make a file build that should not:
`h.tag[Int, s]` is a genuine index of a genuine value, and answering "type
application" for it would drop a real escape check. The dotted base has to be
resolved to a NAME first, and only a resolved name can be classified.

Two consequences worth stating because they are easy to get wrong:

* the `external_call` half is **not this row's work** — it is `§6.2` of
  `FORMAL_known_limits.md`, 55 files, owned by `formal-extcall-tuple`, and its
  remedy is Stage 5 monomorphization rather than a better sentence.

Nothing here is a file on the sweep: the four files
`FORMAL_frame_by_value_ceiling_zero.md` tracks all reach a bare-name base, so
this is written down for the reader who writes the next `Foo[A, B]` and finds
the backend cannot classify `Foo`.