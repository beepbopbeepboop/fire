# FORMAL_comptime_class_attribute_read_through_a_receiver: a `comptime NAME = …` class attribute is in no table the frame analysis reads

**Status: found, NOT fixed.** Filed 2026-10-01 from the
`construct:class-fields-in-init-2` sweep re-measurement (the in-file tail of
the 'other refusal' row). The next step is named and small; what is *not*
small is deciding the substitution's soundness, which is why it is filed
rather than landed.

## The refusal

```
build: res._InjectedValues is a field of res, and _ZipIterator has no field
'_InjectedValues': its 2 field(s): origin, _values. In Python this is an
AttributeError at run time, so the program is very likely already raising
here — but this path refuses rather than read a word it cannot place, because
a frame slot holds one 64-bit word and there is no `k` to read: the name is
not in the layout at all
```

`../new-modular/Mojo/stdlib/std/iter/__init__.mojo`, on `_ZipIterator`. The
program is correct Mojo and nothing raises: `_InjectedValues` is declared 14
lines above the read.

## What is wrong, in one sentence

**`comptime NAME = …` in a struct body is parsed into `StructDef.comptime_aliases`,
and no table on this path reads that dict** — so the name is invisible to the
field census, to `struct_class_constants`, and to the constant-substitution
rewrite, and a read of it is reported as a read of a field the struct does not
have.

Measured, on the smallest reproducer:

```
$ python3 -c "…parse 'struct C:\n comptime is_flat = True\n comptime rank = 3\n
  var storage: Int'…"
fields: [('VarDecl', 'storage')]
comptime_aliases: {'is_flat': BoolLiteral(True), 'rank': IntLiteral(3)}
struct_class_constants: []
struct_declared_names: ['storage']
```

Three tables, three answers, and all three are consistent with each other and
wrong: the alias dict holds both names, and `struct_field_names`,
`struct_class_constants` (`formal/model.py`'s `_split_declaration`) and
`struct_declared_names` read only `StructDef.fields`. `grep -rn comptime_aliases
formal/model.py formal/build.py` returns nothing — the dict is written by
`fire_compiler.py` and read by the interpreter's `execute_StructDef`, and the
formal backend never looks at it.

## Two refusals, and the reader is sent to the wrong one

Which refusal you get depends on how the base is bound, and neither sentence
is the useful one:

* through a frame receiver — `res._InjectedValues`, `Coord.is_flat` in
  `std/python/numpy.mojo` (`shape.is_flat`), and 24 of `iter/__init__.mojo`'s
  names — you get `member_read_without_a_field`'s "has no field", which then
  adds "**In Python this is an AttributeError at run time, so the program is
  very likely already raising here**". That clause is false here in the strong
  sense: the program does not raise, because the attribute exists.
* through a base the analysis cannot place — `c.is_flat` where `c` is a local
  frame, or `Self.is_flat` inside the struct's own method (which is
  `Coord.cast`'s `comptime assert Self.is_flat`, `coord.mojo:682`) — you get
  `field_access_refusal`'s "'c' is bound here as a parameter, so none of the
  three is established", which is a true statement about the BINDING and says
  nothing about the name at all. The remedy it offers ("bind the base from a
  constructor this module declares") is already satisfied.

## The fix, and the part that has to be decided first

`formal/build.py`'s `_rewrite_class_constants` is the existing machinery and
already does the right thing for a class-level constant: substitute the
literal at the read, or refuse by name when the value is not a literal. It
recognises two spellings (`S.NAME` and `x.NAME` for a local built from `S()`)
and refuses to guess a third, for a stated reason that still holds — "without
types, `o.NAME` might be an instance of `S` (a constant) or of some other
struct with a real field of the same name".

So the fix has two halves and the second is the interesting one:

1. **Read `comptime_aliases` where the class-constant tables read `fields`.**
   `struct_class_constants` is the one to extend, because it is the only table
   whose JOB is "a name in the class body that is not per-instance state", and
   a `comptime` binding is exactly that — it is one value for every instance by
   definition. `struct_field_summary` and `struct_declared_names` follow from
   it for free, and both currently print a layout that omits these names.
2. **Decide whether a `comptime` binding may be substituted at a RECEIVER
   read**, which is the shape that actually occurs (`shape.is_flat`,
   `res._InjectedValues`, `Self.is_flat`) and the one `_constant_read_sites`
   deliberately does not cover. The soundness question is the existing one and
   it is not free: at `S.NAME` the name is unambiguously the class's, but at
   `o.NAME` it is only the class's if every binding of `o` is an `S` — which is
   the same agree-or-refuse discipline `frame_field_type_candidates` applies,
   and the same answer: substitute when they agree, refuse when they do not.

`Tuple[*Self.Ts]` — `_ZipIterator._InjectedValues`'s own value, and the reason
that file's read cannot be substituted even with (1) done — is a
`SubscriptExpr` over `Self.Ts`, so it is not a literal and (2)'s "refuse by
name when the value is not a literal" arm takes it. That is the correct
verdict and it is the same one the constant machinery already gives for a
non-literal class constant, so this file stays refused for a TRUE reason.

## What is measured, and what is not

* The refusals and both mechanisms: reproduced from source on this branch
  (`.tmp/r/t36.mojo`, `.tmp/r/t37.mojo` for the two shapes; `iter/__init__.mojo`
  and `python/numpy.mojo` through `tools/formal_sweep.py --arch arm64`).
* The parser tables: the four-line probe above, which is also the whole
  diagnosis — the names are in `comptime_aliases` and in no other table.
* Exposure: **82 files** in the two sweep roots declare at least one
  `comptime NAME = …` class attribute, **731 names** in total. The largest are
  `sys/_libc_errno.mojo` (153), `builtin/variadics.mojo` (61),
  `itertools/itertools.mojo` (34), `builtin/dtype.mojo` (32),
  `iter/__init__.mojo` (24), `sys/_amdgpu.mojo` (22), `simd.mojo` (21),
  `utils/coord.mojo` (17). Measured by parsing every `.py`/`.mojo` under
  `mojo-reference/` and `new-modular/Mojo/stdlib/std/` and counting
  `StructDef.comptime_aliases`.
* **NOT measured: how many of those 82 files this would move.** 82 is the count
  of files that DECLARE such an attribute, which is an upper bound on the files
  that READ one through a receiver, and reading it is a further filter again.
  A worker picking this up should re-sweep a handful of the seven largest
  before assuming the number; the sweep is the only thing that settles it.
* **NOT measured, and it is the reason this is filed rather than landed:** the
  substitution at (2) needs its own property argument, because it is the first
  time this path would materialize a class-level value through a receiver whose
  bindings are only flow-insensitively tracked. `frame_field_type_candidates`
  is the precedent and the shape to copy; it is not a one-line widening of
  `_constant_read_sites`, and shipping it without the argument is the
  silent-wrong-answer outcome both those tables exist to prevent.
