# FORMAL_comptime_class_attribute_read_through_a_receiver: a `comptime NAME = …` class attribute is in no table the frame analysis reads

**Status: the in-file half LANDED 2026-10-01** (`formal2-comptime-alias`, branch
`work/formal2-comptime-alias`). What is fixed, and what is left, is written out
below and measured; the original diagnosis is kept because the landed change is
its two halves and the reasoning is the reasoning. **The doc stays because one
half of the exposure is still open**: a `comptime` member declared in an
IMPORTED module is still invisible, for a reason that is not this bug's to fix
(§ "What is still open").

## The refusal, as measured before the change

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

## What was wrong, in one sentence (measured before the change)

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
formal/model.py formal/build.py` returned nothing — the dict was written by
`fire_compiler.py` and read by the interpreter's `execute_StructDef`, and the
formal backend never looked at it. (`struct_declared_names` still reads only
`StructDef.fields`, and still should: it is the order a POSITIONAL constructor
fills, and a `comptime` binding is not a slot. Measured: adding aliases there
shifts every later field's slot in the clause-4 write census.)

## Two refusals, and the reader was sent to the wrong one

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

## The fix, and the part that had to be decided first

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
* **NOT measured: how many of those 82 files this moves.** 82 is the count of
  files that DECLARE such an attribute, which is an upper bound on the files
  that READ one through a receiver, and reading it is a further filter again.
  The sweep is the only thing that settles it, and it is NOT cheap; what the
  landed change does settle is stated below.

## What landed, and what it measured

Both halves of "The fix" above, in `formal/model.py` (`struct_comptime_aliases`,
and `_split_declaration` classifying what it returns) and `formal/build.py`
(`_constant_read_sites` gaining the receiver spelling, with
`_method_class_constant_bases` and `_holder_class_constant_bases` as its two
evidence sources).

**The soundness argument the original filing said had to be decided first, and
the answer.** There are three bases, and they are not equally decidable, which
is why the table takes them from two places:

* **A method's own receiver, and `Self`.** A method of `S` is called with an
  `S` — that is what a receiver IS on this path, and it is the premise every
  frame layout here already rests on — and a `comptime` binding's value does
  not depend on the instance, because the interpreter evaluates it ONCE at
  struct-definition time in the class body's own scope with no instance in hand
  (`myinterpreter.execute_StructDef`). So `self.NAME` inside a method of `S` is
  the same value as `S.NAME`: not "the same when the types agree", which is the
  question the original filing was worried about, but unconditionally, because
  there is no instance in the expression the value came from. This base needs
  no binding census and that is what distinguishes it.
* **A settled holder.** `shape.is_flat` is a *parameter*, and nothing about the
  declaration says what it holds. What says it is the holder fixpoint: every
  binding of the name this image can see is one struct. That is the same
  "agree or refuse" evidence `struct_frame_slot_candidates` uses, in the same
  direction, and a base whose candidates disagree is simply not in the map, so
  the read falls through to the frame pass and is refused by name. This base
  is only available AFTER the fixpoint, which is why the rewrite is in two
  places rather than one — before `_rewrite_self_fields` for the method
  receiver, and inside `_frame_receivers` after the fixpoint for the holder.
* **Nothing else.** Without types, `o.NAME` through any other object might be
  an instance of `S` or of some other struct with a real field of the same
  name, and guessing is the error the whole rule is arranged to avoid.

The one place the substitution could have been a wrong answer and is not: a
`comptime` name the unit WRITES through an object is not substituted. The unit
write census vetoes it and it becomes a field with a slot, because then the
value really is per-instance — and the reference engine agrees: an instance
read consults the instance dict before the alias table
(`myinterpreter`'s member read, `methods` then `comptime_aliases`), so
`obj.A = 5` really does change what `obj.A` says. Pinned against CPython by
`test_formal_run.py`'s `comptime_alias_overwritten_matches_cpython` and by
`comptime_alias_the_program_overwrites_is_storage`.

**Measured, on both architectures, the wrong answers that are now right:**

| program | before | after | CPython |
|---|---|---|---|
| `struct C: comptime LIMIT = 10` + `def scaled(self): return self.LIMIT + self.n` | `0` | `13` | `13` |
| the same with `C.LIMIT` | refused (`'C' is read at line N before anything in this function stores it` — about a NAME, not about the attribute) | `13` | `13` |
| the same with `Self.LIMIT` | refused (`a field access through 'Self'`) | `13` | `13` |
| `def limit_of(c): return c.LIMIT`, `c` a framed argument | refused (`Coord has no field 'is_flat'`) | `10` | `10` |
| `comptime LIMIT = 10`, `c.LIMIT = 7`, read back | — | `7` | `7` |

The first row is the one that matters: it built, ran, exited 0 and printed a
number the source never wrote, on BOTH architectures — the zero was the
layout's (an unwritten slot), not a register's leftover, which is why the two
machines agreed on it. A `comptime` member read through a receiver was a
silent wrong answer, not a refusal, and that is the outcome this backend is not
allowed to produce.

**The two sweep files, re-measured after the change** (`python3 fire.py build
--formal --no-prove <file>`, and the same with `--backend=x86_64`; identical on
both, as before):

* `../new-modular/Mojo/stdlib/std/iter/__init__.mojo` — **moved off the false
  row.** The message is now

  ```
  build: Self._InjectedValues is a class-level constant of _ZipIterator, and a
  formal value is one 64-bit word with nowhere to keep a non-literal one: …
  that value is not a literal.
  ```

  which is what this section predicted: the correct verdict, for the correct
  reason, naming the spelling the source used. It does not build, and it should
  not: `Tuple[*Self.Ts]` is not a value this path can materialize.
* `../new-modular/Mojo/stdlib/std/python/numpy.mojo` — **did not move.** Still

  ```
  build: shape.is_flat is a field of shape, and Coord has no field 'is_flat' …
  In Python this is an AttributeError at run time …
  ```

  and the reason is § "What is still open" below, not this rule: `Coord` is
  declared in `std/utils/coord.mojo`, which reaches this build through
  `formal/imports.py`, which parses imported sources directly rather than
  through `formal.build.parse_module` and therefore attaches no field census.
  With no evidence the rule above deliberately claims nothing. Reproduced
  smallest: a two-file program whose `shapes.mojo` declares `comptime IS_FLAT =
  True` refuses in the importer and builds and runs in a single file.

So the row this was filed from — "a field the struct does not declare (missing,
or a comptime member)", 2 real files after the `other refusal` split — is
**0 files built, 1 moved to a true refusal on a representability limit, 1 still
on the old row behind the imported-module census gap.** `Coord.is_flat`'s own
value is `Self.rank == Self.flat_rank`, a `BinaryOp` over two names that are
themselves not literals, so even with the census attached it would refuse: this
is not a file waiting on a fix, it is a file this value model cannot represent.

## What is still open

**A `comptime` member declared in an IMPORTED module is still classified by
nothing.** `formal/imports.py`'s declaration collector parses each imported
module and keeps its `StructDef`s, discarding the statements; nothing calls
`formal.model.attach_field_evidence` on them, so `struct_field_evidence` is
None, so `_split_declaration` returns None, so every class-level name —
`LIMIT = 10` and `comptime LIMIT = 10` alike — stays a field and no constant is
substituted. Measured as the two-file reproducer above.

**The next step, exactly.** In `formal/imports.py`, keep the imported module's
`mod_stmts` and attach
`M.unit_field_evidence(mod_stmts)` to the `StructDef`s collected from them —
one call, and `formal/build.py:7261`'s existing comment already anticipates it
("A struct from an imported module keeps whatever its OWN file's parse
attached"). **It is not a one-line change and should not be made as one**: the
census is what decides a struct's WIDTH, so attaching it to imported modules
changes widths, and a width decides whether a receiver is a value or a frame
address. Every imported struct in the tree would be re-measured at once, and
the sweep is the only thing that can say whether that is a net gain. It also
belongs to whoever owns the field census, not to this construct.

The alternative — treating a `comptime` binding as a class constant with no
census at all, on the grounds that the DECLARATION is the evidence — was
considered and rejected: it makes the module that declares a class and the
module that imports it answer differently about the same class, which is the
divergence `attach_field_evidence`'s own docstring says this model exists to
make impossible.

