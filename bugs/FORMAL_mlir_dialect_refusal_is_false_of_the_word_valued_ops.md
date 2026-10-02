# `__mlir_op`: 259 sites over 104 dialect operations are refused as "there is no MLIR on this path", and for 28 of them that is false

**Area:** FORMAL (MLIR dialect constructs). Found 2026-10-02 on
`work/formal5-mlir-constructs` (claim `sweep5:mlir-constructs`), working the
sweep5 cause row **"MLIR dialect construct (`__mlir_attr` / `__mlir_type` /
`__mlir_op`)"** — 5 files, 4 in-file and 1 behind `_select.mojo`. **NOT FIXED,
and deliberately so**: see "Whose" and "Why this is not a two-line fix" below.
The two things here that are worth taking are the **census** (nobody had
measured the family) and the fact that the family's refusal text is **false of
a measurable subset**, which is a diagnostic defect even though the refusal
itself is safe.

## What was run

Re-verified on current master (`24068a01` + the `formal3`/`formal4` merges),
both architectures, `--no-prove` so the measurement is the codegen path:

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

The five files, and what each is actually made of:

| file | what blocks it |
|---|---|
| `std/utils/_select.mojo:38` | `return __mlir_op.\`pop.select\`(condition.__mlir_bool__(), lhs, rhs)` — a **value**, and a register select, which is a spelling this backend already lowers (`a if c else b` → CSEL, `_emit_csel_ternary`) |
| `std/builtin/simd_length.mojo` | imports `_select.mojo`; nothing of its own (`uses:` column reads 1 of 1) |
| `std/sys/debug.mojo:20` | `__mlir_op.\`llvm.intr.debugtrap\`() `— **no value at all**; the operation is a trap |
| `std/builtin/type_aliases.mojo:18` | `comptime Never = __mlir_type.\`!kgen.never\`` — a **type**; §2.1 of `FORMAL_known_limits.md` |
| `std/origin/__init__.mojo:38` | `comptime AnyOrigin = __mlir_attr[...]` — a **dialect attribute**; §2.1 |

Two of the five are already recorded as limits (`FORMAL_known_limits.md` §2.1
for the two templates). The other three are `__mlir_op`, and that is where the
finding is.

## The census, which nobody had

`__mlir_op.\`<dialect>.<op>\`` over the whole stdlib, counted not guessed:

    259 sites, 104 distinct operations, 49 files
    45  lit.ownership.mark_initialized      (17 files)   -- an effect, no value
    14  builtin.unrealized_conversion_cast  ( 2 files)
    10  pop.cmp                              ( 2 files)
     9  pop.pointer.bitcast                  ( 3 files)
     8  pop.cast                             ( 1 file)
    ...

and the subset that a 64-bit-word image **can** hold, because each of these ops
denotes a scalar the backend already computes for the ordinary spelling:

    28 sites over 26 ops:  pop.add  pop.sub  pop.mul  pop.div  pop.floordiv
    pop.rem  pop.neg  pop.shl  pop.shr  pop.floor  pop.ceil  pop.trunc  pop.abs
    pop.round  pop.fma  pop.offset  pop.bitcast  pop.select  pop.max  pop.min
    index.add  index.sub  index.mul  index.divs  index.shrs  index.and

The evidence that this subset is representable is not a judgement call, it is
that **the same computation is written both ways in the same tree**:

| the dialect op | the spelling both backends lower today |
|---|---|
| `__mlir_op.\`pop.add\`(a, b)` (`std/simd.mojo:1082`) | `a + b` — `_emit_div_shift_pow`'s siblings in each backend's binary arm |
| `__mlir_op.\`pop.sub\`(a, b)` (`std/simd.mojo:1098`) | `a - b` |
| `__mlir_op.\`pop.floordiv\`(a, b)` (`std/simd.mojo:1155`) | `a // b` — `_emit_div_shift_pow` (arm64, UDIV/SDIV) / `_emit_div_mod` (x86-64, IDIV) |
| `__mlir_op.\`pop.select\`(c, a, b)` (`std/utils/_select.mojo:38`) | `a if c else b` — `F.TernaryExpr`: arm64 takes the one-instruction path (`_emit_csel_ternary`, when all three operands are pure), x86-64 the branch shape |

So `mlir_dialect_refusal`'s own argument — *"the fragment-and-sub-expression
**template** would have to become a container"* — describes `__mlir_attr[…]`,
which is a template, and is **not an argument at all** about a bare
`__mlir_op.\`pop.add\`(a, b)` call. There is no template, no container, and no
frame blob: the operation denotes an integer, and the backend already emits the
instruction for it.

## What is actually WRONG here, stated narrowly

**Not the refusal.** It refuses, it does not fabricate a word, and that is the
right outcome for every one of the 104 ops — the 231 sites in the "rest" bucket
above really do denote something with no representation (an effect, a trap, a
pointer with no pointee width, a variant discriminant, a coroutine suspension).
Nothing in this document proposes to lower any of them.

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
   the measurable truth is 28 sites whose only missing thing is a name→lowering
   table, and 231 whose missing thing really is the target.

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
`mlir_dialect_refusal` says none of those things and asserts a property of the
target instead.

## Why this is not a two-line fix

A `pop.add` arm is one line. A correct table is not, and a wrong one is worse
than the refusal, so the constraints any implementer has to respect are these:

- **It must be a table keyed on the dialect operation name, and the op name
  must be the WHOLE of the key.** `pop.cmp` is written
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
- **`pop.load` / `pop.store` / `pop.pointer.bitcast` (14 sites) are not in the
  word-valued bucket** even though they look like it: a load's width is its
  pointee's, and this path refuses an undeclared pointee elsewhere
  (`_serialize.mojo`'s next terminal is exactly that refusal). They belong with
  the pointee question, not with `pop.add`.

So the honest sequencing is: **BOOL kind first** (it is diagnosed, it is small,
and it is what `pop.select` and therefore the `_select.mojo`/`simd_length.mojo`
pair actually waits on), **then** a value-op table starting with the arithmetic
and comparison ops, each arm sharing the existing decisions.

## Whose

**This overlaps another live claim and that is deliberate rather than an
oversight.** `python3 tools/control.py claims` shows `formal-mlir-gpu` holding
`construct:mlir-and-gpu-globals`, whose subject `std/gpu/**` and "the MLIR
dialect constructs" includes this family, and `bugs/FORMAL_known_limits.md`
§2.2 already closes the `__mlir_op` refusal as measured and pinned. This doc
was filed from `sweep5:mlir-constructs` because the sweep5 cause row is what
produced the measurement; whoever merges the two should **merge the census into
§2.2** rather than keep two places that count the same family. Nothing in this
branch edits `formal/model.py`'s MLIR rules, so there is no code conflict to
resolve — only this text.

`§2.1`'s two template families are a different matter and are **not** in scope
here: `__mlir_type` names a type and `__mlir_attr[...]` names a dialect
attribute, and neither is a value, so the "no representation" sentence is
correct of them.

## The next step

Two decisions, both for the controller rather than for a worker:

  * **The diagnostic, which is cheap and safe.** Reword
    `formal/model.py`'s `mlir_dialect_refusal` so it does not claim "no
    representation" about a construct that denotes a word. Either split it the
    way `MLIR_BOOL_METHODS` does (implementable-but-unguarded / genuinely
    unrepresentable), or state the op NAME it refused and say that this path has
    no lowering table for dialect operations. Either way the coordinate change
    is mandatory and is the thing to budget for: `tools/formal_sweep_causes.py`
    keys the cause row on the literal substring `"__mlir_op is an MLIR dialect
    construct"`, and `test_formal_sweep.py` asserts every marker matches a
    refusal the sweep actually produced — so a reword that misses those fails a
    test rather than silently moving a column, which is the correct failure and
    the reason the marker exists.
  * **The lowering table**, which is a feature: `formal/arm64_codegen.py` and
    `formal/x86_64_codegen.py` need arms for the 26 word-valued ops, keyed on
    the operation name, sharing `common_type`/`cmp_signed`/`shift_signedness`,
    with the bracketed predicate of `pop.cmp` answered or refused. Start with
    `pop.add`/`pop.sub`/`pop.mul`/`pop.cmp` (the arithmetic and comparison ops,
    20 of the 28 sites) and leave memory, variants, coroutines and `lit.*`
    effects refused. `bugs/FORMAL_known_limits.md` §2.2 is where the result
    belongs, and `test_formal_mlir_precedence.py` is the suite that goes red if
    the refusal ever moves.
