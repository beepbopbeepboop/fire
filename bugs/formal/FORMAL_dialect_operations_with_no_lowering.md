# FORMAL_dialect_operations_with_no_lowering: what is left of `__mlir_op` once the refusal stopped being false

Every `__mlir_op` construct on this path used to be refused with one sentence —
*"this path has no MLIR, so … a dialect attribute, type or operation has no
template for that word to assemble from"* — and **for a quarter of the arithmetic
sites that sentence was false**: the ordinary spelling (`a + b`, `a if c else b`,
`x != 0`) computes the same thing and both backends already emit it. That is
fixed. The refusal is now classified by what each operation DENOTES, it is TRUE
wherever it fires, and the operations that are answerable lower.

**This document is what is LEFT, and it is a capability list rather than a
diagnostic defect.** The classification, the census and the §Correction below are
here because the source comments cite them
(`formal/model.py:307`, `:574`, `:1373`, `formal/build.py:13453`, `:13740`), and
they are the record of why no name-keyed lowering table may come back.

**Status 2026-10-05 (`work/formal71-docs`): the census re-measured, the refusal
re-read at three constructs, and nothing here is a FALSE SENTENCE any more.**
`test_formal_mlir_precedence.py` is 40/40 and every row of it is a refusal that
must keep its own words or a program that must keep building and running.

## The census, measured

Over the stdlib (`../new-modular/Mojo/stdlib`), counting `__mlir_op` sites and
grouping by the operation name — which is the WRONG key for what an operation
denotes and the right key for how many there are:

```console
$ cd ../new-modular/Mojo/stdlib
$ grep -roE '__mlir_op\.`[a-zA-Z0-9_.]+`' --include='*.mojo' . | wc -l
262
$ … | sed 's/.*__mlir_op\.`//; s/`//' | sort -u | wc -l
104
$ grep -rlE '__mlir_op\.' --include='*.mojo' . | wc -l
51
```

**262 sites over 104 distinct operations in 51 files** — the same 104 operations
the 2026-10-02 measurement found, three more sites and two more files, which is
the stdlib moving rather than the compiler. The head of the list, unchanged:

    45  lit.ownership.mark_initialized      (17 files)  -- an effect, no value
    14  builtin.unrealized_conversion_cast  ( 2 files)
    10  pop.cmp                              ( 2 files)
    10  pop.cast                             ( 2 files)
     9  pop.pointer.bitcast                  ( 3 files)
     7  pop.cast_to_builtin                  ( 5 files)
     7  kgen.struct.extract
     7  index.cmp
     6  pop.external_call
     5  pop.atomic.rmw

And the classification over all of them, which `mlir_dialect_op_refusal` owns and
which `test_formal_mlir_precedence.py`'s `the_classification_covers_the_whole_-
corpus` re-measures by reading the class off the MESSAGE (so a branch that exists
but is unreachable fails): `typed-result 113 / effect 75 / unguarded 34 /
elementwise 24 / vector 13`, with 0 reaching the fallback.

## §Correction: counting by operation NAME is what made the original claim wrong

**This is the paragraph the source comments cite, and it is the reason no
lowering table may be keyed on a name.** The 38 arithmetic sites were counted by
grouping the corpus by operation name and asking whether each NAME sounds scalar.
The doc's own first piece of cited evidence says that is the wrong key:

```console
$ sed -n '1070,1083p' std/simd.mojo        # __add__, the row cited as `a + b`
    def __add__(self, rhs: Self) -> Self:
        """Computes `self + rhs`. …"""
        return Self(
            mlir_value=__mlir_op.`pop.add`(self._mlir_value, rhs._mlir_value)
        )
```

and the operand it is applied to is declared `simd.mojo:596-604`
`var _mlir_value: Self._mlir_type` where `comptime _mlir_type =
__mlir_type[`!kgen.simd<`, …]`. So `pop.add` there is an **N-LANE VECTOR** add,
not `a + b` on two words: whether an elementwise result is one word or N lanes is
a fact about the **OPERAND's type**, and the operation's name does not settle it.

Measured over those 38 sites, by reading each operand's DECLARED type:

    38 sites, 3 verdicts
      26  vector or mask operand   !kgen.simd<LENGTH, DTYPE>, !kgen.simd<0>, …
       9  word operand             __mlir_type.index, !kgen.scalar<ui8>
       3  neither                  pointer arithmetic (pop.offset, one pop.div)

**Which inverts the recommendation a name-keyed table would follow.** A table
reading `pop.add`/`pop.sub`/`pop.mul`/`pop.cmp` and emitting `a + b` would be
RIGHT for the 9 word-typed sites and WRONG for the 26 vector-typed ones:
`pop.add(a, b)` → `a + b` over two `!kgen.simd<4, ui32>` operands computes a
scalar add of two vector-typed words — a plausible-looking 64-bit number where the
source asked for four 32-bit lanes. That is why every arithmetic rewrite on this
path (`_lower_dialect_arith`) reads the operand's declared type through
`mlir_operand_declared_type` and refuses rather than guessing, and why
`test_formal_mlir_precedence.py`'s `no_dialect_table_is_keyed_on_the_operation_
name_alone` exists.

## What is left, and each item's next step

None of these is a false sentence; each is a capability with a stated reason. They
are in the order the corpus reaches them.

1. **`pop.cmp` and `index.cmp` — the PREDICATE.** 17 sites. `MLIR_UNGUARDED_OPS`
   refuses them because the predicate is written in the bracket
   (`pred=__mlir_attr.`#kgen.cmp_pred<eq>``) and this path cannot read that
   attribute; six distinct `#kgen.cmp_pred<…>` values appear in the corpus, so
   answering `eq` for all of them is a wrong answer rather than a refusal. Next
   step: read the attribute's SPELLING (it is a literal template with one
   fragment) and map the six predicates onto this path's comparison arms, with the
   unknown predicate still refused — `an_unknown_predicate_is_refused_rather_than_
   answered` in `test_formal_mlir_precedence.py` is the row that shape must keep.
   **Worth 0 files**: both files are behind other rows.
2. **`pop.cast` (10 sites), `pop.pointer.bitcast` (9), `kgen.struct.extract` (7),
   `pop.external_call` (6), `pop.atomic.rmw` (5), `lit.ref.to_pointer` (5)** —
   each needs a fact about a TYPE this path does not have: a pointee width, a
   struct's field index and result type, the callee's C signature, an atomic
   ordering and memory order. Next step per operation is in the message at the
   site, which is what `typed-result` / `unguarded` name.
3. **`pop.floordiv`** — absent for the weaker reason that **no corpus site reaches
   it**, which is a deliberate non-widening and not a gap. If it is ever wanted it
   is this path's `//` (`model.division_floors`: it FLOORS).
4. **`pop.div`** — the name does not say which of the two divisions it is, and this
   path has both (`/` truncates for ints, `//` floors). A bracket or a documented
   spelling has to settle it; answering either unconditionally is a wrong answer.
5. **The saturating and NaN-aware `pop.*`** — `pop.max`/`pop.min` are saturating
   and NaN-aware selections and are not `a if a > b else b`; `pop.abs` is not `-a`
   on the saturating cases. Each needs its own semantics, measured against CPython
   in the way `test_formal_mlir_precedence.py`'s `pop.rem`/`index.divs` rows were.
6. **Every `!kgen.scalar<uiN>`** — an N-bit unsigned value in a 64-bit word WRAPS
   at `2**N`, so the identity rewrite that is right for `index` is wrong here.
   Deliberately outside `MLIR_WORD_TYPE_NAMES` for that reason.
7. **Every `pop.simd.*`** — N lanes, and this path has no vector buffer.
8. **The `lit.*` ownership effects** — 45 of the 262 sites. They assert something
   about a reference this path does not track, so there is nothing to lower them
   TO; only the two divergences (`llvm.intr.trap`, `llvm.intr.debugtrap`) had a
   defensible answer, and those landed as `_emit_diverge`.

## What is NOT claimed

* **No corpus file is one row closer.** Every item above is behind another
  module's refusal — `std/builtin/simd_length.mojo` is stopped by
  `_select.mojo`'s export rule
  (`bugs/formal/FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`), and the
  `std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` scope's own terminal is
  `FORMAL std os io round2 scope is one refusal shape`. FILES BLOCKED IS
  AN UPPER BOUND, in the class column.
* **Nothing here says a refusal is wrong.** The refusal names the operation, says
  what it denotes, and names what is missing; `test_formal_mlir_precedence.py` is
  40/40 and each row asserts the words its own construct must keep.
* **The static check this area wanted and still does not have.** The old document
  recorded that `mlir_dialect_op_refusal` once carried an UNREACHABLE tail naming
  `MLIR_WORD_VALUED_OPS`, "a name that exists nowhere in the tree", and that "a
  static check that every global this module's functions read is defined in it …
  does not exist yet and is worth having". It still does not, it is not an MLIR
  question (the same class would apply to any module in `formal/`), and no
  registered test file owns it — landing it means choosing a home for a
  formal-module hygiene check, which is a registry question rather than this
  area's.
