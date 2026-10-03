# `__mlir_op`: 259 sites over 104 dialect operations were refused as "there is no MLIR on this path", and for a quarter of the arithmetic ones that is false

**Area:** FORMAL (MLIR dialect constructs). Found 2026-10-02 on
`work/formal5-mlir-constructs` (claim `sweep5:mlir-constructs`), working the
sweep5 cause row **"MLIR dialect construct (`__mlir_attr` / `__mlir_type` /
`__mlir_op`)"** — 5 files, 4 in-file and 1 behind `_select.mojo`.

**The refusal text is FIXED** (2026-10-02, `work/formal6-mlir-constructs`): the
operation is now named and classified by what it DENOTES, and this doc's own
census is CORRECTED twice below — its central claim was wrong in a way that would
have made the recommended implementation produce wrong answers, and it
under-counted one of the five files. **The lowering table is still not built**;
see "The next step".

**What is worth keeping here is the census**, and the correction to it.

## What was run

Re-verified on current master (`24068a01` + the `formal3`/`formal4` merges),
both architectures, `--no-prove` so the measurement is the codegen path. **This
is the refusal as it read BEFORE the 2026-10-02 fix** — one sentence for all 104
operations, naming the `__mlir_` PREFIX rather than the operation:

    $ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
        --backend=$a -o .tmp/m ../new-modular/Mojo/stdlib/std/utils/_select.mojo; done
    build: _select_register_value: __mlir_op is an MLIR dialect construct. This
    path has no MLIR: it lowers a Mojo program to a Mach-O image whose only value
    is a 64-bit word, and an MLIR attribute, type or operation has no
    representation in one — the fragment-and-sub-expression template would have
    to become a container, and a container here is a blob in the frame of the
    function that built it, which disagrees with the compiler that does have
    MLIR. Refused by name rather than read out of a register, which is what
    produced 10 on arm64 and 0 on x86-64 for one source. Write the value the
    construct denotes at the use site
    # byte for byte identical text, both backends

What the SAME build says now — the operation is named, and what it needs is the
BOOL kind rather than a representation, which is the one fact `_select.mojo`
actually waits on:

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/m \
        ../new-modular/Mojo/stdlib/std/utils/_select.mojo
    build: _select_register_value: `pop.select` is a dialect OPERATION whose
    value could be a word on this path, but it cannot be GUARDED here: its first
    argument is a BOOL (`condition.__mlir_bool__()`), and this path has no BOOL
    kind distinct from an integer — an unannotated word IS an integer — so a
    select answered kind-blind would test a `char *` for non-zero and answer 1.
    The missing piece is a BOOL kind, which `MLIR_BOOL_METHODS` already names. A
    deliberate deferral, not an impossibility: the operation is nameable and its
    operands are values, so what is missing is the fact its result depends on —
    not a representation of the result
    # byte for byte identical on --backend=x86_64

The five files, and what each is actually made of:

| file | what blocks it | class the fix now reports |
|---|---|---|
| `std/utils/_select.mojo:38` | `return __mlir_op.\`pop.select\`(condition.__mlir_bool__(), lhs, rhs)` | **unguarded** — the BOOL kind |
| `std/builtin/simd_length.mojo` | **13 `__mlir_op` sites of its own** — see the correction below | **unguarded** — `pop.cast_to_builtin` |
| `std/sys/debug.mojo:20` | `__mlir_op.\`llvm.intr.debugtrap\`() ` | **effect** — no value at all |
| `std/builtin/type_aliases.mojo:18` | `comptime Never = __mlir_type.\`!kgen.never\`` — a **type**; §2.1 | §2.1, unchanged |
| `std/origin/__init__.mojo:38` | `comptime AnyOrigin = __mlir_attr[...]` — a **dialect attribute**; §2.1 | §2.1, unchanged |

Two of the five are already recorded as limits (`FORMAL_known_limits.md` §2.1
for the two templates). The other three are `__mlir_op`, and each now reports the
class it belongs to — which is the point: `debug.mojo` and `_select.mojo` were
previously indistinguishable, and they need different things (nothing at all
versus a BOOL kind).

### Second correction (2026-10-02): `simd_length.mojo` has 13 operations of its
### own, and closing `_select.mojo` does not close it

This doc recorded `simd_length.mojo` as "imports `_select.mojo`; nothing of its
own (`uses:` column reads 1 of 1)". The `uses:` column is about how many files a
refusing module BLOCKS, not about how much work the module has, and reading it as
the latter is what produced the error. Counted from the source, not from the
sweep:

    $ grep -c "__mlir_op" std/builtin/simd_length.mojo
    13

in 13 distinct functions — `__init__`, `__eq__`, `__ne__`, `__add__`, `__sub__`,
`__le__`, `__gt__`, `__lt__`, `__ge__`, `__and__`, `__truediv__`, `__mul__`,
`__rshift__` — and six of them (`index.add/sub/mul/and/divs/shrs`) are among the
**9 word-typed sites** in the whole corpus. Only `__rshift__` calls `_select`.

Measured, by removing the `_select` import from a copy and building the file on
its own, both architectures:

    $ python3 fire.py build --formal --no-prove --backend=arm64 \
        -o sl .tmp/iso4/std/builtin/simd_length.mojo
    build: SIMDLength___init__: `pop.cast_to_builtin` is a dialect OPERATION whose
    value could be a word on this path, but it cannot be GUARDED here: its result
    type is the `_type=` in its bracket, which is a dialect type rather than a
    value. …
    # byte for byte identical on --backend=x86_64

So the file's own terminal is `pop.cast_to_builtin` in `__init__`, reached before
any of the arithmetic, and it is a **different missing fact** from `pop.select`'s
BOOL kind — a dialect RESULT TYPE rather than a kind. Two consequences for
whoever takes the remaining work:

  * **Closing `_select.mojo` does not close `simd_length.mojo`**, so the sweep's
    cause row does not shrink by 2 files when the BOOL kind lands. It shrinks by
    1 (`_select.mojo`), and `simd_length.mojo` stays on the `pop.cast_to_builtin`
    / `_type=`-is-a-dialect-type question.
  * The **9 word-typed sites** in §Correction are almost all here, in the one
    file that is reachable, which makes this file the natural first target for
    the operand-type work rather than `std/simd.mojo` (which is 22 sites of pure
    vector and is not a scalar target at all).

## The census, which nobody had

`__mlir_op.\`<dialect>.<op>\`` over the whole stdlib, counted not guessed:

    259 sites, 104 distinct operations, 49 files
    45  lit.ownership.mark_initialized      (17 files)   -- an effect, no value
    14  builtin.unrealized_conversion_cast  ( 2 files)
    10  pop.cmp                              ( 2 files)
     9  pop.pointer.bitcast                  ( 3 files)
     8  pop.cast                             ( 1 file)
    ...

and the subset this document ORIGINALLY counted as word-valued — **now
CORRECTED, see "§Correction" below; the 28-site list was counted by operation
NAME and is wrong about 26 of the 38 sites it covers**:

    38 sites over 27 ops:  pop.add  pop.sub  pop.mul  pop.div  pop.floordiv
    pop.rem  pop.neg  pop.shl  pop.shr  pop.floor  pop.ceil  pop.trunc  pop.abs
    pop.round  pop.fma  pop.offset  pop.bitcast  pop.select  pop.max  pop.min
    pop.cmp  index.add  index.sub  index.mul  index.divs  index.shrs  index.and

The evidence that a SCALAR such an operation is representable is not a judgement
call, it is that **the same computation is written both ways in the same tree**:

| the dialect op | the spelling both backends lower today |
|---|---|
| a scalar `__mlir_op.\`pop.add\`(a, b)` | `a + b` — each backend's binary arm |
| a scalar `__mlir_op.\`pop.sub\`(a, b)` | `a - b` |
| a scalar `__mlir_op.\`pop.floordiv\`(a, b)` | `a // b` — `_emit_div_shift_pow` (arm64, UDIV/SDIV) / `_emit_div_mod` (x86-64, IDIV) |
| `__mlir_op.\`pop.select\`(c, a, b)` (`std/utils/_select.mojo:38`) | `a if c else b` — `F.TernaryExpr`: arm64 takes the one-instruction path (`_emit_csel_ternary`, when all three operands are pure), x86-64 the branch shape |

The qualifier **scalar** is the correction, and it is load-bearing. See below.

So `mlir_dialect_refusal`'s own argument — *"the fragment-and-sub-expression
**template** would have to become a container"* — describes `__mlir_attr[…]`,
which is a template, and is **not an argument at all** about a bare
`__mlir_op.\`pop.add\`(a, b)` call. There is no template, no container, and no
frame blob.

## §Correction (2026-10-02): counting by operation NAME is what made the claim
## wrong, and a table keyed on the name would have produced wrong answers

The list above was built by grouping the corpus **by operation name** and asking
whether each NAME sounds scalar. That is the wrong key, and the doc's own first
piece of cited evidence says so in the source's own words:

    $ sed -n '1070,1083p' std/simd.mojo        # __add__, the row cited as `a + b`
        def __add__(self, rhs: Self) -> Self:
            """Computes `self + rhs`.
            ...
            Returns:
                A new vector whose element at position `i` is computed as
                `self[i] + rhs[i]`.
            """
            return Self(
                mlir_value=__mlir_op.`pop.add`(self._mlir_value, rhs._mlir_value)
            )

and the operand it is applied to is declared

    simd.mojo:596-604   comptime _mlir_type = __mlir_type[`!kgen.simd<`, …]
                         var _mlir_value: Self._mlir_type

so `pop.add` at `simd.mojo:1082` is an **N-LANE VECTOR** add, not `a + b` on two
words. `pop.add` is ELEMENTWISE: whether its result is one word or N lanes is a
fact about the **operand's type**, and the operation's name does not settle it.

Measured over the 38 sites, by reading each operand's DECLARED type rather than
the operation's name:

    38 sites, 3 verdicts
      26  vector or mask operand   !kgen.simd<LENGTH, DTYPE>, !kgen.simd<0>, …
      9   word operand             __mlir_type.index, !kgen.scalar<ui8>
      3   neither                  pointer arithmetic (pop.offset, one pop.div)

The 9 word-typed sites are all in two files — `std/builtin/simd_length.mojo`'s
six `index.*` operations over `__mlir_type.index`, and `std/builtin/dtype.mojo`'s
two `pop.cmp` over `!kgen.scalar<ui8>`, plus `pop.select` in
`std/utils/_select.mojo`. Everything in `std/simd.mojo` — 22 of the 38, and every
row the original table cited as evidence — is a vector or a mask.

**Why this is not a smaller version of the same finding: it inverts the
recommendation.** The original "next step" was to start a lowering table with
`pop.add`/`pop.sub`/`pop.mul`/`pop.cmp`, reading the operation name and emitting
the ordinary spelling. That table would be RIGHT for the 9 word-typed sites and
WRONG for the 26 vector-typed ones: `pop.add(a, b)` → `a + b` over two
`!kgen.simd<4, ui32>` operands computes a scalar add of two vector-typed words —
a plausible-looking 64-bit number where the source asked for four 32-bit lanes.
A wrong answer rather than a refusal, which is the outcome this backend is built
to prevent, and it is the outcome a name-keyed table makes *more* likely rather
than less, because it looks like a mechanical substitution.

What is therefore needed before any table is honest is **the operand's type**,
which is `formal/model.py`'s existing kind machinery (`ValueKinds.kind_of`,
`declared_type_kind`, and — for the vector case — the element count that
`Self.length` carries). That is a real piece of work and it is the next step, not
this document's.

`mlir_dialect_op_refusal` says exactly that and no more: for an elementwise
operation it reports that whether the result is a word or an N-lane vector "is a
fact about its OPERANDS' type and not about the operation's name", and names the
operand type as the missing piece. It does not claim these denote words.

## The classification that landed, over all 259 sites

`mlir_dialect_op_refusal` classifies **every one** of the 259 sites, which is a
census rather than a handful of hand-picked rows — and `test_formal_mlir_precedence.py`'s
`the_classification_covers_the_whole_corpus` re-measures it, reading the class off
the MESSAGE rather than off the tables so a branch that exists but is unreachable
fails. Measured:

    259 sites over 104 operations, 0 reaching the fallback
      113  typed-result   the RESULT TYPE is in the bracket (_type=, pred=,
                         bin_op=, mask=, ordering=, a variant discriminant)
       75  effect         no value at all — a store, a trap, an ownership
                         marker, a free, a coroutine step, inline assembly
       34  unguarded      a named fact this path lacks: a predicate, a pointee
                         width, a BOOL kind, a GEP scale, the Mojo version
       24  elementwise    arithmetic whose word-or-vector answer is the
                         OPERAND's type (the 38-site question above)
       13  vector         over !kgen.simd<N, D> — N lanes, never a word

Three of these classes have a MEMBERSHIP RULE that is measured rather than
assembled by judgement, and that is what stops the tables being a pile of
opinions:

  * **effect** — the 15 operations the corpus uses as a STANDALONE statement at
    EVERY one of their sites (continuation lines joined first, so a multi-line
    call is classified on the statement it belongs to). "Every call site discards
    it" is the strongest statement a corpus can make about an operation. And an
    operation absent from the set is not thereby an effect: `pop.atomic.rmw` is
    read as `var res = __mlir_op.`pop.atomic.rmw`[…]` at
    `std/atomic/atomic.mojo:326` and returns the old value.
  * **typed-result** — the 31 operations carrying `_type=`/`pred=`/`bin_op=`/
    `mask=`/a discriminant at every site. A property of the SPELLING, so it is
    safe to key on the name: the reader can go and look at the bracket.
  * **vector** — the `pop.simd.` prefix, which is structural in the name rather
    than per-site, and is why `pop.add` is deliberately NOT here: the corpus has
    it both ways depending on the operand.

## What is actually WRONG here, stated narrowly

**Not the refusal.** It refuses, it does not fabricate a word, and that is the
right outcome for every one of the 104 ops — the operations outside the arithmetic
family really do denote something with no representation (an effect, a trap, a
pointer with no pointee width, a variant discriminant, a coroutine suspension),
and the arithmetic ones are refused for the operand-type reason above rather than
for a representation reason. Nothing in this document proposes to lower any of
them.

**The classification and the diagnostic**, which is what a reader and the sweep
both consume:

1. `formal/model.py`'s `mlir_dialect_refusal` is keyed on the **`__mlir_` NAME** —
   it is "asked for any `__mlir_*` name no template rule covers"
   (`formal/model.py:181`), and `FORMAL_known_limits.md` §2.2 states the rule it
   implements as "a name with the `__mlir_` prefix that no template rule covers
   has no representation in a 64-bit word, and is refused by name"
   (`FORMAL_known_limits.md:633`). For 26 of the 104 operations that sentence is
   false, and the false part is the load-bearing part of the sentence.
2. Its repair — *"Write the value the construct denotes at the use site"* — is
   for `pop.add` an instruction to do by hand the thing the compiler already
   emits two lines away. A refusal that tells the reader to hand-write a
   lowering this backend has is not actionable; it is a dead end wearing a
   repair.
3. `tools/formal_sweep_causes.py`'s cause row is titled "MLIR dialect construct"
   and lands these files in the same bucket as `__mlir_attr[...]`, so the
   planner who reads the table is told 5 files need "a different target" when
   the measurable truth is 76 sites whose missing thing is nothing at all (an
   effect), 38 whose missing thing is the OPERAND'S TYPE, and a remainder whose
   missing thing really is the target. **Now landed:** the row carries the
   classified wordings too (`is a dialect OPERATION`), so the three classes are
   visible in the table rather than only in the message.

The sibling refusal **already in the same file** is the model for doing this
better, and the contrast is the argument. `MLIR_BOOL_METHODS`
(`formal/model.py:7183`) refuses `c.__mlir_bool__()` with:

> is a real builtin and **is implementable** as the same test `if` already does
> (a Bool is a word holding 0 or 1 on this path), but it is refused because it
> **cannot be GUARDED** here … **The fix is a BOOL kind, not a lowering of this
> call**

That names the construct, says what it denotes, distinguishes "cannot lower"
from "can lower but cannot prove safe", and names the missing piece. Its
docstring calls itself "a deliberate deferral, not an impossibility".
`mlir_dialect_op_refusal` is now written in that shape — which is why
`pop.select` reports the BOOL kind and `llvm.intr.debugtrap` reports that it has
no value, instead of both reporting that there is no MLIR.

## Why this is not a two-line fix

A `pop.add` arm is one line. A correct table is not, and a wrong one is worse
than the refusal, so the constraints any implementer has to respect are these —
the FIRST of which is new since this doc was filed, and is the §Correction above:

- **The table cannot be keyed on the operation NAME alone, because the name does
  not decide whether the result is a word.** This is the constraint the original
  version of this document got backwards: it asked for a name-keyed table and
  would have shipped a wrong answer for 26 of the 38 arithmetic sites. An arm
  must first establish the OPERAND's type, which means `ValueKinds.kind_of`,
  `declared_type_kind`, and — for `!kgen.simd<LENGTH, DTYPE>` — the element
  count `Self.length` carries, because a 4-lane `ui32` vector is 128 bits and
  this path's only value is 64. Keyed on name *and* established operand type, the
  name-keyed arm is still the right shape for the 9 word-typed sites.
- **The op name must be the WHOLE of what the table keys on, once the operand
  type is established.** `pop.cmp` is written
  `__mlir_op.\`pop.cmp\`[pred=__mlir_attr.\`#kgen.cmp_pred<eq>\`](a, b)` — ten
  sites, six distinct predicate values. A table that reads the name and ignores the
  bracket would lower `eq` and `ne` the same way, which is a wrong answer rather
  than a refusal. The predicate `#kgen.cmp_pred<…>` is itself a dialect
  attribute, so it needs the same answer `target_template` gives for
  `#kgen.param.expr<…>` (§2.0): a small closed set, or a refusal.
- **Each arm must select instructions from the decisions the two backends
  already SHARE**, or the architectures will drift — which is the defect class
  this backend exists to prevent. The ones already shared are `common_type`,
  `cmp_signed` and `model.shift_signedness`; `index.divs` and `pop.div` are
  signedness-sensitive and `index.shrs` is a shift, so an arm that re-decides
  any of those locally is a new copy of an existing answer.
- **`pop.select`'s own guard is a missing kind, not a missing lowering.**
  `_select.mojo:38` is `pop.select(condition.__mlir_bool__(), lhs, rhs)`, and
  `__mlir_bool__()` is refused by `MLIR_BOOL_METHODS` for a **separate, already
  diagnosed** reason: there is no BOOL kind distinct from INT, so lowering it
  kind-blind would answer `(receiver != 0)` on a `char *` too. So lowering
  `pop.select` does **not** unblock `_select.mojo` or its one dependent,
  `simd_length.mojo`; the BOOL kind does, and that is a fifth kind constant
  threaded through `ValueKinds` and both backends' kind oracles. That is the
  whole of `_select.mojo`'s remaining cost, and it is a different piece of work.
  **Now reported as such** rather than as a missing representation.
- **`pop.load` / `pop.store` / `pop.pointer.bitcast` (14 sites) are not in the
  arithmetic bucket** even though they look like it: a load's width is its
  pointee's, and this path refuses an undeclared pointee elsewhere
  (`_serialize.mojo`'s next terminal is exactly that refusal). They belong with
  the pointee question, not with `pop.add`. **Now reported as such**, one named
  missing fact per operation.

So the honest sequencing is: **the operand type first** (it is what the arithmetic
arms all need, and the §Correction shows a table without it is worse than no
table), **the BOOL kind second** (it is diagnosed, it is small, and it is what
`pop.select` and therefore the `_select.mojo`/`simd_length.mojo` pair actually
waits on), **then** the arithmetic and comparison arms, each sharing the existing
decisions.

## Whose

**This overlapped another live claim, and that was deliberate rather than an
oversight.** `python3 tools/control.py claims` showed `formal-mlir-gpu` holding
`construct:mlir-and-gpu-globals`, whose subject `std/gpu/**` and "the MLIR
dialect constructs" includes this family, and `bugs/FORMAL_known_limits.md`
§2.2 already closed the `__mlir_op` refusal as measured and pinned. This doc
was filed from `sweep5:mlir-constructs` because the sweep5 cause row is what
produced the measurement. **As of 2026-10-02** `formal-mlir-gpu` has exited
(`control.py status`: `exited-ok DONE`, +0 commits, and its branch tip is
`96af2abf`, an ancestor of `master` — it landed nothing), so its claim is stale
and `sweep6:mlir-constructs` is the claim this family is worked under. The
census is now **merged into §2.2** as §2.2's correction section, so there are
not two places counting this family with different numbers. Whoever picks up the
remaining table should read §2.2 first.

`§2.1`'s two template families are a different matter and are **not** in scope
here: `__mlir_type` names a type and `__mlir_attr[...]` names a dialect
attribute, and neither is a value, so the "no representation" sentence is
correct of them. They keep their own refusal text and their own §2.1 rows, and
`mlir_dialect_op_refusal` is not asked about either.

## The next step

**Done (2026-10-02, `work/formal6-mlir-constructs`): the diagnostic.** Landed as
described in the header — `mlir_dialect_op_refusal` classifies the operation into
effect / unguarded / elementwise / unclassified, names the operation, and says
which fact is missing. The coordinate change the original text called mandatory
was made in full: `tools/formal_sweep_causes.py` gained
`("is a dialect OPERATION",)` and KEPT the old prefix marker (still reachable for
a caller with no operation in hand); `tools/formal_sweep.py`'s `_REFUSAL_FAMILIES`
gained `dialect OPERATION` and kept `MLIR dialect construct` for the same reason;
`test_refusal_taxonomy.py` has a sample per wording, which is the only thing that
proves a marker is not dead. Tests: 8 new `CLASSIFIED` rows in
`test_formal_mlir_precedence.py` (15/15 in that file), `test_refusal_taxonomy.py`
163/163.

**Not done: the lowering table**, and the §Correction above is why it is not the
next mechanical step it was going to be. The remaining work, in order:

  1. **Establish the operand's declared type at a dialect operation.** This is
     what every arithmetic arm needs and what the name cannot supply: 26 of the
     38 arithmetic sites are over `!kgen.simd<LENGTH, DTYPE>`, whose answer needs
     `Self.length` (the element count), not just `ValueKinds.kind_of`. Until this
     exists, an arm keyed on the operation name is right for 9 sites and wrong
     for 26, and a wrong answer is worse than the refusal this branch keeps.
  2. **The BOOL kind**, which unblocks `pop.select` and therefore
     `_select.mojo` — **one** file of the sweep's cause row, not two:
     `simd_length.mojo` has its own terminal (`pop.cast_to_builtin`, a `_type=`
     that is a dialect type) and stays on this list's item 3 regardless.
     Diagnosed already (`MLIR_BOOL_METHODS`); a fifth kind constant through
     `ValueKinds` and both backends' kind oracles.
  3. **Then** the arms themselves, keyed on name *and* established operand type,
     sharing `common_type`/`cmp_signed`/`shift_signedness`, with `pop.cmp`'s
     bracketed predicate answered from a small closed set or refused. Start with
     `std/builtin/simd_length.mojo`: it holds 6 of the 9 word-typed sites, it is
     reachable, and its own terminal (`pop.cast_to_builtin`) is a result-type
     question rather than the vector-width one. Memory, variants, coroutines and
     the `lit.*`/ownership effects stay refused, and `MLIR_EFFECT_OPS` says so in
     the message rather than leaving them to look like a missing lowering.

`test_formal_mlir_precedence.py` is the suite that goes red if any of this moves:
its `CLASSIFIED` rows assert each class's own words AND the absence of another
class's, so an arm that lowers an operation by name alone without establishing
the operand type will red the elementwise row rather than quietly answering a
vector site with a scalar add.
