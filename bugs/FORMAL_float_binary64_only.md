# binary64 only: `Float32` and the narrow formats are refused by name, and `float32` arithmetic is the next slice

**Area:** FORMAL (the float value model). Claim `project26:float`, found
2026-10-04 on `work/formal26-float`. **Status: the SCOPE is unchanged and it is
not sound** — binary64 is still all that is supported, and one place inside it
was a silent wrong answer rather than a refusal until 2026-10-05
(`formal29-2-r2`); §"What was measured" below records that, and it is a different
kind of finding from the narrow formats this document is about.

## What is supported, and where

`formal/model.py`'s `FLOAT_KIND` is **IEEE-754 binary64** and nothing else, and
`formal/types.py`'s `FLOAT_TYPE_NAMES` is `{"Float64", "float64"}` — two
spellings of one declaration, for the reason every other vocabulary in that file
carries both (`TYPE_NAMES` has `int` and `Int`, `STRING_TYPE_NAMES` has `String`
and `str`).

`formal/arm64.py` and `formal/x86_64.py` carry the SCALAR DOUBLE forms only:
`FADD`/`FSUB`/`FMUL`/`FDIV`, `FNEG`, `FCMP`, `FMOV`, `SCVTF`, `FCVTZS` on arm64;
`ADDSD`/`SUBSD`/`MULSD`/`DIVSD`, `UCOMISD`, `MOVQ`, `CVTSI2SD`, `CVTTSD2SI` on
x86-64. Every encoding is differentially tested against the platform assembler
(`test_arm64_encoders.py`, `test_x86_64_encoders.py`).

## What is NOT, and why the refusal is the right answer

**`Float32` is four bytes with a different exponent bias and its bits are NOT a
sub-pattern of a double's.** So a 64-bit word holding a `binary32` cannot be a
`FLOAT_KIND` here: reading it as a double is a wrong answer, not an
approximation, and it is the same wrong answer for every input except zero. The
honest options were to refuse by name or to accept and misread, and the codebase
already had the pattern for it — `POINTEES_REFUSED` refuses `Float16`, `Float32`
and `Float64` BY NAME rather than merely omitting them, and
`model.unrepresentable_type_ctor_refusal` is the same move for a constructor.

`Float16`, `BFloat16`, the `float8_*` / `float6_*` / `float4_*` families and
`UInt128` are all in the same position, and they are named in
`model.type_value_name_space`'s comment as types a `DType` VALUE can name — a
dtype tag is a word two programs comparing dtypes agree on, which is all a dtype
VALUE is on this path, so a tag for a format this path cannot HOLD is not a lie.

`POINTEES_REFUSED["Float32"]`'s text — *"a Float32 is four bytes of IEEE binary32
and this path has no float kind distinct from an int"* — is TRUE and only true of
binary32, and `test_formal_run.py`'s `deref_refuse_float_pointee` pins it as such.
Its `Float64` sibling was CORRECTED in the same change, because that half of the
sentence had become false: a `Float64` load IS bit-exact now. The corrected text
and the reason are in `bugs/FORMAL_float_pointer_pointee.md`.

## What the next slice would be

A `binary32` kind, and it is NOT a matter of adding `FSADD`/`FSDIV` and four more
encoders:

- **A second `FLOAT32_KIND`** threaded through `ValueKinds`,
  `declared_type_kind`, `truthy_lowering`, `float_comparison`,
  `float_binary_refusal` and both backends' readers. Every one of those today
  answers "is this a double?" and a second width makes the question "which
  width?", which is a different function at each of them rather than a new row.
- **Mixed-width arithmetic** — `Float32 + Float64` — which needs a promotion
  rule. There is none today for double/int either (it is refused), and this is
  the same decision at a second width.
- **A `Float32` value is still ONE word**, so storage needs nothing — the same
  property that makes `Float64` cheap, and the reason the estimate for the second
  width is about the KIND and not about the frame layout.
- **A `Float32` in the Lean model** is a 32-bit pattern, and `lib/IEEE754.lean`'s
  `Bits` is `UInt64` with 11-bit exponents and a 52-bit mantissa baked into every
  mask. A binary32 model is a second parameterisation of the same functions, not
  a copy of them: `isNaN32`, `key32`, `ltBits32`, and the four SCALAR SINGLE
  decode arms. Writing it as a copy is what `CLAUDE.md`'s "consolidate duplicates
  rather than maintaining parallel implementations" is about, so the shape to
  reach for is one pair of functions parameterised by the width.
- **A `Float16`/`BFloat16` cannot go in a 64-bit word without a mask on every
  read**, so it is a genuinely larger change than `Float32` and should be argued
  for separately.

## What was measured, so the next person does not have to

`formal/model.py`'s `FLOAT_BINARY_MNEMONICS` has four rows (`+`, `-`, `*`, `/`),
so `//`, `%`, `**` and the bitwise operators on two doubles are REFUSED by name —
`model.float_binary_refusal`'s message says which four are lowered and why the
other is not (neither FP unit has an instruction, and CPython's `7.0 // 2` is
`3.0`, not a truncated `3`). That refusal is a slice boundary of this one and not
a gap in it.
## Status, 2026-10-05 (`formal29-2-r2`): the scope had one silent wrong answer
## inside it, and it is closed

"Binary64 only" was a scope nobody had checked against the other half of the
question, which is what a **double is read AS**. Every consumer of a float on
this path asked for a KIND — `float_binary_refusal`, `float_conversion_lowering`,
`float_comparison`, `truthy_lowering` — and every producer agreed, because the
producers are literals, annotations and initialisers. A `printf` conversion is
none of those: it is a *format string*, and both backends place a vararg from
the FORMAT rather than from the operand's kind (AAPCS has one register file, and
SysV's classifier reads the conversions), so nothing ever compared the two.

Measured, both architectures, before the fix:

| source | printed | what it is |
|---|---|---|
| `def show(x: Float64): printf("[%d]", x)` with `x = 3.9` | `[858993459]` | `0x33333333`, the low 32 bits of 3.9 |
| the same with `%c` | `[3]` | `0x33`, the same two bytes as a character |
| `var a = 7; printf("[%.17g]", a)` | `[3.4584595208887258e-323]` | the integer 7 read as the bit pattern of a double |

Green builds, exit 0, wrong numbers on the screen. Not a rounding anywhere: a
`%d` reads the vararg as an integer and a `%g` reads it as a double, so a
disagreement is a rendering of the wrong VALUE rather than of the right one.

**What landed.** `model.printf_kind_conversion_refusal`, asked from
`printf_format_refusal` — the one entry point both backends already ask, next to
`printf_text_conversion_refusal`, which is the same rule on the `%s` axis. The
evidence is `model.printf_arg_float_evidence`, which is a three-way answer
(`"float"` / `"int"` / `None`) because the two directions have different evidence
available: `FLOAT_KIND` is never a default, so a double is positive evidence
from `_expr_str_kind` alone, while "an integer" needs what
`printf_text_conversion_refusal`'s own rows call positive evidence —
`ValueKinds.own_shape_kind`, a statement of THIS function binding the name to a
number on its own shape.

**`None` never refuses, and that is load-bearing.** An unannotated parameter
holding a double (`def show(x): printf("%f", x)` called `show(2.5)`) prints 2.5
today and must keep doing so: both backends place the word from the format, so
a caller that passed a double needs no annotation here. Reading "the source does
not say" as "not a float" would refuse a program that is right, which is the
failure mode every evidence rule in this area is written against — and the row
`float_an_unannotated_parameter_at_a_floating_conversion_still_prints` pins it.

Pinned by `test_formal_run.py`'s new `FLOAT_REFUSALS` group, five rows: the two
refusals that are the defect, the third for the other direction, and two
controls (`%d` of an integer, `Int(x)` of a double — the conversion the message
names, so a rule that broke the conversion while refusing the mismatch would
still pass the three refusals). `FLOAT_CASES` is 21/21 and the new group 5/5.

**What this does NOT close.** It is a hole in the boundary of the scope, not a
change to it: the scope is still binary64, `Float32` is still refused by name for
the reason §"What is NOT" gives, and the SECOND slice is still a second kind. It
also removes one hazard from
`bugs/FORMAL_float_pointer_pointee.md`'s remaining work rather than doing any of
it: letting a `Pointer[Float64]` load through without a kind would have made
`printf("%d", p.value())` print a bit pattern, so the rule above is a
PREREQUISITE for that change and not an alternative to it.

## Status, 2026-10-05 (`formal28-3`): §"What is NOT"'s second sentence was
## FALSE about the CONSTRUCTOR, and that is now the refusal the doc always said
## it was

§"What is NOT, and why the refusal is the right answer" says:

> The honest options were to refuse by name or to accept and misread, and the
> codebase already had the pattern for it — `POINTEES_REFUSED` refuses `Float16`,
> `Float32` and `Float64` BY NAME rather than merely omitting them, and
> `model.unrepresentable_type_ctor_refusal` is the same move for a constructor.

**The first half is true and the second was not.** `POINTEES_REFUSED` refuses
those three BY NAME at a DEREFERENCE, and no constructor table carried them —
so `Float32(1.0)` took `type_constructor_kind`'s documented `None` ("not a type
constructor at all (a genuine function call)"), emitted `BL Float32`, and the
build failed at the **LINK AUDIT** with a message about a SYMBOL:

```
build: t_Float32.mojo: the image would bind 1 symbol(s) that nothing provides,
  so it could not be loaded: Float32. `Float32` is a call this build emitted and
  nothing provides it, so that call is not lowered on this path: this backend has
  no call to bind there, which is a fact about the PROGRAM and not about the link
  line. Write the operation out, or bind the name from a library that provides it.
```

which is the failure mode this document's own §"Status 2026-10-05" calls "a
message about a SYMBOL rather than about the type", and the last sentence is a
false prescription: there is no library that provides `Float32`, because it is a
type and not a symbol.

Measured, **both architectures, over all thirteen names** in
`model.NARROW_FLOAT_TYPE_NAMES` — `Float16`, `Float32`, `BFloat16`, `Float128`'s
nine `Float8_*`/`Float6_*`/`Float4_*` formats and `UInt128`: **13/13 reached the
link audit before, 13/13 refuse BY NAME after.** This is the same defect
`UNREPRESENTABLE_TYPE_CTORS`'s own comment records for `bytearray`/`bytes` —
*"their absence did not refuse them, it made them look like ordinary function
calls"* — reached through a different door.

### Why the list was spelled twice, and what it cost

The narrow formats were in **two** tables already: `POINTEES_REFUSED` for the
load and, by hand, inside `TYPE_VALUE_NAMES`'s union for the dtype tag. The
constructor was the **door between them**, and a name absent from the table the
constructor asks falls out of the world rather than being refused — which is
also why `BFloat16` (in neither, before this change) had the same exit. It is
now `NARROW_FLOAT_TYPE_NAMES`, read by `UNREPRESENTABLE_TYPE_CTORS` and by that
union, so the two cannot disagree about which formats exist. `type_value_name_space()`
is unchanged (verified name-for-name against the pre-change set) and
`type_value_tags_are_distinct()` still answers `[]`.

### The generic refusal text was FALSE of these names, and it needed its own

`unrepresentable_type_ctor_refusal`'s generic sentence is "this image has **no
declaration of Float32 to construct** — it is not a struct in this module or in
anything it imports". True of `Span` (nothing in hand declares one), false of
`Float32`: a `Float32` is a real type with a fixed 32-bit layout, and the image
already knows about it — `POINTEES_REFUSED` refuses it by name two constructs
away. A reader told to go and declare it finds nothing to declare.

So `narrow_float_ctor_refusal` says what is actually true, and says the two
things a reader needs to act on: **a dtype TAG of the format works today**
(`DType.float32` is a word two programs comparing dtypes agree on, so the tag
half and the value half are two different facts), and **`Float32(x)` is not an
approximation of `Float64(x)` that could be waved through, because it rounds.**
`UInt128` gets its own clause — two WORDS, not the wrong bits in one — which is
why its test row pins that sentence rather than the float one.

### Pinned, five rows plus three table guards

`test_formal_run.py`'s `FLOAT_REFUSALS`: the three refusals with their distinct
reasons, and **two controls** — `Float64(7)` still lowers and prints CPython's
`[7.0]` on both backends (a set taken from a name's *spelling* rather than from
what the path can REPRESENT would refuse this row), and `DType.float32 ==
DType.bfloat16` still compares as tags, which is what keeps the refusal's two
sentences two facts. Plus three import-time guards on the table itself: every
member routed to a refusal, disjoint from `FLOAT_TYPE_CTORS`, and a subset of
the tag name space.

**What this does NOT change, measured.** The **scope** is untouched — still
binary64, still one `FLOAT_KIND`, and the second slice is still the second kind
this document's §"What the next slice would be" describes. **Files moved: 0.**
The five stdlib files that spell a narrow format in real code (`simd.mojo`,
`math/math.mojo`, `random/philox.mojo`, `builtin/_format_float.mojo`,
`collections/string/_parsing_numbers/parsing_floats.mojo` — 36 constructor sites
between them) are each blocked **earlier** than the constructor, and their
verdicts are byte-identical before and after on both backends.
