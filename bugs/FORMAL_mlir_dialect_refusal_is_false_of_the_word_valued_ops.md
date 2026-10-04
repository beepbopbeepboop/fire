# `__mlir_op`: 259 sites over 104 dialect operations were refused as "there is no MLIR on this path", and for a quarter of the arithmetic ones that is false

**Status (2026-10-04, `work/formal21-5`): the last false sentence in this
document's own subject is fixed, and the item it leaves behind is named — and it
is NOT reachable from the corpus today, which is a measurement rather than an
opinion.** The typed-result refusal said a bracket's `_type=` is "a fact this
path has no source for", which is false of every `_type=` this build classifies:
`model.mlir_result_clause` reports what the bracket says (the same treatment
`mlir_operand_clause` gives the operand, one branch over), and
`std/builtin/simd_length.mojo`'s `pop.cast_to_builtin[_type=__mlir_type.index]`
is the site that proves it. **That file's terminal has also MOVED**, measured:
it is no longer the cast at all but `_select.mojo`'s export rule
(`bugs/FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`, claimed by
`formal16-2`), so the cast is one refusal further on than this document has said
since 2026-10-04. See "What landed" below.

**Status (2026-10-04, `work/formal19-4`): items 1 and 3 of "The next step" are
DONE — the operand's DECLARED type is read, and the arithmetic operations whose
operand is a word lower to the ordinary spelling on both architectures. What is
left is items 4 and 5, both of them now named per operation rather than as one
class.** Read this before "The next step", because it corrects what that section
says the arithmetic table may contain.

**What landed, and it is a source-to-source rewrite in the shared pipeline rather
than an emitter arm per architecture** — the shape `pop.select` already uses
(`formal/build.py::_lower_dialect_select`), so "both architectures" is a
statement about ONE code path and not about two implementations agreeing:

  * `formal/model.py::mlir_operand_declared_type` reads a dialect operation's
    operand's type off a DECLARATION: a parameter annotation, a local
    annotation, or `<receiver>.<field>` / `<x: Struct>.<field>` against the
    unit's field table. It answers None for every shape nothing in the source
    states — a call result, a subscript, a comparison, an arithmetic expression,
    and a `comptime` ALIAS, which is how all 22 of `std/simd.mojo`'s sites are
    spelled and which resolves to a vector.
  * `formal/model.py::mlir_type_kind` classifies a declared dialect type as a
    `word` or a `vector`. **One word type — `__mlir_type.index`** — and that is
    a correction of this document's own count, which calls
    `!kgen.scalar<ui8>` word-typed: an N-bit unsigned integer held in a word
    WRAPS at 2^N, so `a + b` over two `ui8` is not the 64-bit add this path
    emits. `MLIR_WORD_TYPE_NAMES` is one name and the comment says why.
  * `formal/model.py::MLIR_WORD_ARITH_OPS` — eleven operations, each with the
    ordinary operator it denotes — and `MLIR_CMP_OPS` + `MLIR_CMP_PRED_OPS`, a
    CLOSED set of ten bracketed predicates.
  * `formal/build.py::_lower_dialect_arith` rewrites them, gated on the operand
    type alone. `index.divs` → `//`, `index.shrs` → `>>`, `index.cmp[pred=eq]`
    → `==`.

**The two rows that were MEASURED rather than read**, because this path's `//`
and `%` are not Python's and the table would otherwise be a guess:

```
f(-7, 2) on `__mlir_type.index` parameters     this path    CPython
  a // b        -3   truncating                   -4   floor
  a %  b        -1   rem, dividend's sign          1   Python's mod
  a >> b        -2   arithmetic                    -2
```

so `index.divs` → `//` is right and **`pop.floordiv` is NOT in the table**,
which is the clearest entry that is missing on purpose: floor division is the
other semantics and rewriting it to this path's `//` would be wrong for every
negative operand. `pop.div` is absent for the other half of the same question —
the name does not say which division it is, and a table that picked one is the
name-keyed table § Correction is about.

**What it is worth, in this document's units — and it is NOT a coverage
number.** The 12 sites in `std/builtin/simd_length.mojo` (`index.{add, sub,
mul, divs, and, shrs}` and six `index.cmp`) now lower, and **0 files reach
`pass`**: the file's own terminal is `pop.cast_to_builtin[_type=__mlir_type.
index](value._mlir_value)` in `__init__`, re-measured on this tree after the
change and unchanged. What the change bought is the MISSING FACT the document
says every arithmetic arm needs, and a refusal that is no longer false at the
sites where the fact is established (below).

**The refusal changed with it, and that was not optional.** Once the operand
type is readable, "this path has no lowering table that establishes the operand
type" is untrue at every site where it IS established, in two different
directions. `formal/model.py::mlir_operand_clause` now reports what the
declaration says, and the elementwise branch says which of THREE things is
missing: a VECTOR (the lane count and element width), an OPERATION whose
ordinary spelling computes something else, or a declaration that states nothing.
The clause says nothing about the OPERATION outside the elementwise branch,
because `pop.cmp` over a word is missing its PREDICATE and a sentence claiming
the operation was at fault would be false of it — a false diagnostic in the same
file whose subject is false diagnostics.

**One false claim this change FOUND and removed**, which is recorded here
because it is the same disease one step further in: with a field table keyed on
the field NAME alone, `SIMDLength___init__(out self, value: Int)` writing
`__mlir_op.`pop.cast_to_builtin`[…](value._mlir_value)` had its operand reported
as the `__mlir_type.index` field `SIMDLength` declares — a fact about the name
rather than about the field the source wrote. The reader now requires the base
to be a receiver spelling or a name the function declares as a struct of THIS
UNIT.

**Tests: `test_formal_mlir_precedence.py` is 28/28** (was 21), of which four are
new `CLASSIFIED` rows that pin each of the three refusal shapes above plus the
untyped-base case, and two are new `GUARDED` rows that BUILD AND RUN the
arithmetic on both architectures — the second of which is the regression pin for
the walk bug below.

**The census is unchanged and that is the point**: still 259 sites over 104
operations, still `typed-result 113 / effect 75 / unguarded 34 / elementwise 24
/ vector 13`. `mlir_dialect_op_refusal`'s CLASSES are unchanged; only what the
message says about an operand moved.

**A crash this change found in a shared walk, which is a bug in its own right
and is filed separately** (`bugs/FORMAL_a_child_rewriting_walk_empties_a_list_it
_mutated.md`): the walk each dialect rewrite used had `changed =
isinstance(node, tuple)` and then set `changed = True` inside the loop, so a
LIST with a replaced element returned its EMPTY accumulator — and a list nested
inside a list has its parent's `node[i] = repl` fire on it. Measured on
`Idx(tag=0, v=__mlir_op.`index.add`(self.v, rhs.v))`: the call's `kwargs` became
`[['tag', IntLiteral], []]` and the build died in
`model.struct_construction_plan` with `not enough values to unpack (expected 2,
got 0)`. It was latent in the select pass because the only construct that pass
replaces is a `CallExpr` and a `CallExpr` in argument position is reached
through its callee's `args`, a dataclass field whose result the caller
discards. `formal/build.py::_rewrite_dialect_in` is now the ONE walk for both
dialect passes.

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

**Status (2026-10-03, `work/formal8-7-r2`): item 2 of "The next step" is DONE,
and it did not need the BOOL kind that section recommended — it needed the
DECLARATION, which the program already had.** `pop.select` and `__mlir_bool__()`
are rewritten, in the shared pipeline, to the expressions they already denote on
this path: `x != 0` and `a if c else b`. `std/utils/_select.mojo` swept
`codegen -> pass` on both architectures, which is the one file this document's
item 2 was worth.

**Why the kind would have been the wrong tool, and this is the part worth
keeping.** The premise behind item 2 is the sentence
`MLIR_UNGUARDED_OPS["pop.select"]` carried:

> this path has no BOOL kind distinct from an integer — an unannotated word IS
> an integer — so a select answered kind-blind would test a `char *` for
> non-zero

Both clauses are true and NEITHER of them is about this program.
`std/utils/_select.mojo:17` is
`def _select_register_value[T: TrivialRegisterPassable](condition: Bool,
lhs: T, rhs: T) -> T`, so `condition` is not an unannotated word: the source says
it holds a `Bool`, and on this path a `Bool` is a word holding 0 or 1 — which is
exactly what `x != 0` computes. The question that decides the lowering is not
"can a kind tell a Bool from an `Int`" (it cannot, and does not need to —
`_kind_of_simple` already classifies a `BoolLiteral` as `INT_KIND`, which is
correct) but "does the source say this word is 0 or 1", and the source does.

**So the fifth kind constant would have bought nothing here and cost a wrong
answer somewhere else.** Every consumer of `INT_KIND` — `len`, a `%s` format, a
sign test — would have to learn to accept a kind it does not recognise, and the
two that must NOT (a format, a length) would gain a second opinion to keep
consistent. `formal/types.py::BOOL_TYPE_NAMES` plus `model.annotation_is_bool`
are the whole of what was needed: a vocabulary of the annotations that say
"0 or 1", and one reader of it. `declared_type_kind` still maps `Bool` to
`INT_KIND`, because that is what a `Bool` IS here.

**The guard is decidable and it is the refusal that proves it.** A receiver the
function does not declare a `Bool` is left alone, so `MLIR_BOOL_METHODS`'s own
refusal fires and now says what is missing and what to do — annotate the
receiver. Measured, both architectures, on the two programs that differ only in
the declaration:

    def pick(condition: Bool, lhs: Int, rhs: Int) -> Int:
        return __mlir_op.`pop.select`(condition.__mlir_bool__(), lhs, rhs)
    #   -> Built, and pick(1, 10, 20) = 10, pick(0, 10, 20) = 20

    def pick(condition: String, lhs: Int, rhs: Int) -> Int:
        return __mlir_op.`pop.select`(condition.__mlir_bool__(), lhs, rhs)
    #   -> refused: "`pop.select` is a dialect OPERATION whose value could be a
    #      word on this path, but it cannot be GUARDED here … The missing thing
    #      is therefore the declaration and not a kind"

**One deliberate non-widening.** A local bound to a COMPARISON (`c = n > 3`) is
provably a `Bool` too, and this pass does not claim it: an annotation is what the
SOURCE says about a NAME, while a comparison is a fact about a value's
provenance, and widening from one to the other is the value model's question,
not this one's. `test_formal_run.py`'s `recvkind_mlir_bool_needs_a_declared_bool`
is that program and pins the refusal.

**A rewrite in the shared pipeline rather than an emitter arm per architecture**,
which is why "both architectures" is a statement about one code path and not
about two implementations agreeing: `a if c else b` is an `F.TernaryExpr`, which
arm64 already emits as one `CSEL` (`_emit_csel_ternary`) and x86-64 as a branch,
so `pop.select` needed no new instruction selection at all. That is also the
argument the document made in §Correction for why a NAME-keyed table is the
wrong shape — a select's arms would have had to be re-decided per architecture
for no gain.

**SUPERSEDED by the Status at the head of this file (2026-10-04,
`work/formal19-4`): items 1 and 3 are DONE.** The paragraph below is kept as the
statement of what was believed when the effect lowering landed, and the two
clauses in it that the tree has since answered are both marked above.

**Status (2026-10-03, `work/formal14-std-os-io`): one EFFECT now lowers, and the
"effects stay refused" in item 3 below is narrower than it reads.** The sweep
scope `std/{os,io,pathlib,sys,time,hashlib,base64,ffi}` has exactly ONE in-file
`__mlir_op` refusal, and it is a trap used as a statement: `std/sys/debug.mojo:20`
is `__mlir_op.`llvm.intr.debugtrap`()()` and nothing else, so the whole module
was refused for it. That file now **builds on both architectures** and the
scope's `codegen` class is 0.

**Why an effect at a STATEMENT is a different question from an effect anywhere.**
`MLIR_EFFECT_OPS` is right that these operations denote no value, and the refusal
in `mlir_dialect_op_refusal` was written for exactly that fact. But it was asked
at every use, and at a use whose value is DISCARDED there is no result to
represent and nothing that reads one — so the ground the refusal stood on ("no
representation in a 64-bit word, because there is no value to represent") is
simply absent there. Refusing was an OVER-refusal, not a safety, and it cost a
module for a construct that lowers to the one thing this path already emits when
control must not continue: the divergence `raise` emits, now one `_emit_diverge`
per backend shared by both callers.

**It is not a trap instruction, and the reason is the proofs.** The source asked
for a fault a debugger sees; what is emitted is Darwin `exit(1)` on arm64 and the
C library's `exit` on x86-64. `brk #0`/`int3` would be the better lowering and is
the one to build once the Lean model grows a step for it — but every word in the
divergence already has a `work_step_*` lemma in `lib/work.lean`, whereas an
unmodelled `brk` falls through `formal/arm64_proof_gen.py`'s
`_step_branch_index` as "not modelled" and is skipped, which would put a hole in
the proofs of anything containing it.

**The narrowing is `MLIR_EFFECT_DIVERGENCE_OPS` = {`llvm.intr.trap`,
`llvm.intr.debugtrap`}, plus two requirements on the USE:** a zero-argument call,
and the whole value of an `F.ExprStmt` (`model.mlir_effects_all_lowered`, which
also requires every dialect root in the body to be one of those, so a second
construct cannot ride along unseen). So `return __mlir_op.`llvm.intr.trap`()` is
still refused with the same sentence, and every other member of
`MLIR_EFFECT_OPS` still is, for the fact it has beyond the missing value: an
ownership marker asserts something about a reference this path does not track, a
`pop.store` has an address whose pointee width nothing states, a `pop.fence` and
a `pop.inline_asm` are ordering and clobber facts with no encoding agreed here, a
coroutine step is the shape this path lowers to a plain call, and
`kgen.codegen.reachable` carries operands this path computes rather than being a
bare marker.

The four corpus sites this reaches, three of them in `std/sys` and `std/os`:

    std/sys/debug.mojo:20         __mlir_op.`llvm.intr.debugtrap`()
    std/sys/info.mojo:702         __mlir_op.`llvm.intr.trap`()
    std/os/os.mojo:242            __mlir_op.`llvm.intr.trap`()   (_abort_base)
    std/_plugin/selector.mojo:74  __mlir_op.`llvm.intr.trap`()

Only the first moves a file: the other three are behind other modules' refusals
(`bugs/FORMAL_std_os_io_scope_is_decided_by_five_modules_outside_the_claim.md`
has the chain), so this change moves them one refusal along rather than out.

**One defect found and removed on the way.** `mlir_dialect_op_refusal` had an
UNREACHABLE tail after its fallback `return`: a second copy of the unguarded arm
and a branch for `MLIR_WORD_VALUED_OPS`, **a name that exists nowhere in the
tree**. It never fired and so never raised the `NameError` it would have, which
is exactly the failure mode a reader cannot see; what is in its place is a comment
saying why a name-keyed word-valued table must not come back (the §Correction
below is the reason). A test that would have caught the class is
`test_formal_mlir_precedence.py`'s EMITTED table plus the
`a_trap_in_a_value_position_is_still_refused` row; what would catch a *future*
undefined name is a static check that every global this module's functions read is
defined in it, which does not exist yet and is worth having.

**Items 1 and 3 of "The next step" are unchanged and still in that order**, and
neither is about an effect.

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

## What landed (2026-10-04, `work/formal21-5`): the RESULT type, and where the file's terminal went

### The last false sentence, one branch over

The elementwise branch was fixed on 2026-10-04 for claiming a fact it had
(`mlir_operand_clause`); **the typed-result branch kept making the same claim
about the other half of the same site.** It said:

> and that bracket holds a DIALECT object (`__mlir_type.…`,
> `__mlir_attr.`#kgen.…``) rather than a value. This path's only value is a
> 64-bit word, so the result's width and element type are a fact it has no
> source for.

`__mlir_type.index` **is** in `MLIR_WORD_TYPE_NAMES` — the table this very
document's item 1 added — so `mlir_type_kind` reads that bracket and the
sentence is false of it. What a build says now, on the site
`std/builtin/simd_length.mojo:76` reaches:

    build: SIMDLength___init__: `pop.cast_to_builtin` is a dialect OPERATION whose
    RESULT TYPE is written in its own bracket … and that bracket holds a DIALECT
    object … rather than a value. Its bracket's result type is
    '__mlir_type.index', which this path holds in ONE 64-bit word — a signed,
    pointer-sized integer — so the RESULT is not what is missing here. What is
    therefore missing is the OPERAND's DECLARED type, and nothing in this unit
    states one: a DECLARATION is what this path reads, and a field read off a
    struct the unit does not declare — a builtin such as `Int`, which has no field
    table here — states nothing about its type. A deliberate deferral, not an
    impossibility: the operation is nameable and its result is one word, so what
    is missing is a fact about the operand rather than a representation of the
    result.

Three answers, and the third is the control: a `word` `_type=` says the result
is not the missing thing and names the operand; a `!kgen.simd<…>` `_type=` says
what is missing is a **representation** of N lanes, which is a different fact
from a type and is what that site actually lacks; **a bracket with no `_type=`
keeps the class's own sentence unchanged**, which is the case that says the clause
fires where there is a type to read and nowhere else. `MLIR_RESULT_TYPE_ATTRS` is
the single attribute name, because a bracket also carries `pred=`, `bin_op=`,
`mask=`, `ordering=` and a variant discriminant, and none of them is a type.

### What it is worth, in this document's units: 0 files, and the measurement is the point

**No file moves, and the reason is not the change — it is where the file's
terminal went.** Re-measured on this tree, both architectures, `simd_length.mojo`
no longer reaches its own cast at all:

    $ python3 fire.py build --formal --no-prove -o .tmp/x \
          ../new-modular/Mojo/stdlib/std/builtin/simd_length.mojo
    build: simd_length.mojo imports 'std.utils._select', which cannot be built
    either: _select.mojo: formal dylib has no public functions: _select.mojo
    exports nothing under doc/ABI.md's rules: every declaration in it is private
    (_select_register_value) …

**`_select.mojo`'s export rule, not the cast** — the 33-file row
(`FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md`, claimed by
`formal16-2`, and this document has said since 2026-10-02 that `simd_length.mojo`
is blocked on both). So the honest reading of this round is the one this document
keeps arriving at: **the refusal is now TRUE where it fires, and the file is one
row along.** `FILES BLOCKED IS AN UPPER BOUND` again, in the class column.

### What the remaining missing fact is, and why it is not a patch

The cast itself — `pop.cast_to_builtin[_type=index](x)` over a word `x` — is an
IDENTITY on this path, and would be rewritten the way `MLIR_WORD_ARITH_OPS`
rewrites `index.add`: to the operand itself, with no instruction selection. It is
**not** implemented, and the reason is a fact rather than a cost:

* the corpus has exactly ONE word-to-word cast — `simd_length.mojo:76`. The other
  `cast_to_builtin` sites are `__mlir_type.i1` (`bool.mojo`), `__mlir_type.ui8`
  (`dtype.mojo`) and `__mlir_type.`i32``/`i16`` (`_gpu/_utils.mojo`), all of which
  are outside `MLIR_WORD_TYPE_NAMES` **on purpose** (an N-bit unsigned in a word
  wraps at 2^N, so a 64-bit identity would be the wrong answer), and `simd.mijo`'s
  are over vectors;
* the operand's type cannot be established, because it is `value._mlir_value`
  where `value: Int` — a field of a **builtin** struct, and this path reads
  DECLARATIONS from the unit being compiled. There is no field table for `Int`
  here, and adding one to answer a single site in a file another row blocks is
  the speculative widening this document's own §Correction argues against.

**So the next step for this construct, if anyone wants it, is a builtin field
table** (`Int._mlir_value: __mlir_type.index` and its neighbours) read by
`mlir_operand_declared_type`, and it is worth building when some FILE's terminal
is the cast rather than when one file two rows back has one. The message now says
so at the site, which is the half that was false.

**Tests: `test_formal_mlir_precedence.py` is 32/32** (was 29) — three new
`CLASSIFIED` rows, one per answer plus the control, each asserting its own words
AND the absence of the sentence it replaces. **The census is unchanged**, which is
the point: still 259 sites over 104 operations, still `typed-result 113 / effect
75 / unguarded 34 / elementwise 24 / vector 13`. A message that reports more is
not a message that classifies differently.

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
`test_formal_mlir_precedence.py`, `test_refusal_taxonomy.py` (216/216 on the
tree items 1 and 3 landed on).

**The lowering table, item by item, with what is DONE and what is not.** The
§Correction above is why this was not the next mechanical step it was going to
be, and the reasoning behind each item is not repeated — the Status at the head
of this file is the current reading and this is the plan it was planned against.

  1. **Establish the operand's declared type at a dialect operation.** **DONE
     (2026-10-04, `work/formal19-4`): `model.mlir_operand_declared_type` reads it
     off a parameter annotation, a local annotation or a field declaration, and
     a `comptime` alias — which is how all 22 of `std/simd.mojo`'s sites are
     spelled — claims nothing.** What it reads is narrower than the item wanted
     and the narrowing is the safe direction: it does NOT resolve
     `Self.length`, so a vector operand stays refused, which is what the item's
     own "a wrong answer is worse than the refusal" requires.
  2. **The BOOL kind**, which unblocks `pop.select` and therefore
     `_select.mojo`. **DONE, and it needed the DECLARATION rather than a fifth
     kind constant: `formal/types.py::BOOL_TYPE_NAMES` + `model.annotation_is_
     bool` are the whole of it (2026-10-03, `work/formal8-7-r2`), and
     `_select.mojo` builds.** `simd_length.mojo` keeps its own terminal
     (`pop.cast_to_builtin`, a `_type=` that is a dialect type).
  3. **The arms themselves, keyed on name *and* established operand type, sharing
     `common_type`/`cmp_signed`/`shift_signedness`, with `pop.cmp`'s bracketed
     predicate answered from a small closed set or refused. DONE for the eleven
     operations whose operand is declared a word and for the ten bracketed
     predicates** (`MLIR_WORD_ARITH_OPS`, `MLIR_CMP_OPS`, `MLIR_CMP_PRED_OPS`),
     by rewriting to the ordinary spelling so both emitters' existing decisions
     apply rather than being re-decided. **Measured, and the measurement changed
     the table**: this path's `//` TRUNCATES and its `%` takes the dividend's
     sign, so `index.divs` → `//` and `pop.rem` → `%` are right and
     `pop.floordiv` is not in it. Not done and deliberately not planned:
     `pop.floordiv`, `pop.div` (the name does not say which division it is),
     `pop.abs`/`max`/`min`/`floor`/`ceil`/`trunc`/`round`/`fma`, every
     `pop.simd.*`, every UNSIGNED predicate (this path's `<` is signed and there
     is no unsigned spelling to rewrite to), and every operation over a
     `!kgen.scalar<uiN>` — an N-bit unsigned integer in a word WRAPS at 2^N, so
     the 64-bit add is not the ui8 add. Each of those sites now says which of
     the three things is missing rather than repeating the class's sentence.
     Memory, variants, coroutines and the `lit.*`/ownership effects stay
     refused, and `MLIR_EFFECT_OPS` says so in the message rather than leaving
     them to look like a missing lowering. **(2026-10-03: the two TRAPS are the
     one exception, and only as a statement whose value is discarded — see the
     Status at the top. `llvm.intr.trap` and `llvm.intr.debugtrap` lower to this
     path's divergence, and nothing else in `MLIR_EFFECT_OPS` does.)**

**What is left of this document, as of 2026-10-04, is one file's own terminal**
— `pop.cast_to_builtin[_type=__mlir_type.index](value._mlir_value)` in
`std/builtin/simd_length.mojo`'s `__init__`, re-measured unchanged after items 1
and 3 landed. It is a `_type=` over an `Int`'s dialect value, which is a value-
model question about `Int` rather than about the arithmetic, and it is
`bugs/FORMAL_known_limits.md` §2.2's territory rather than this document's.

**Both clauses of that paragraph were superseded by "What landed" above, and both
in the same direction.** The file's terminal is no longer the cast: it is
`_select.mojo`'s export rule, measured on this tree, so the cast is one refusal
further on than this section said. And the `_type=` over an `Int`'s dialect value
is no longer refused for a reason this document called a value-model question —
the build now READS the `_type=` and says the result is one word, and the missing
thing it names is a **builtin struct's field table** (`Int._mlir_value`), which is
a smaller and better-specified thing than "a value-model question about `Int`".
The cast is still not lowered, and the reason is measured rather than judged: one
word-to-word cast site in the corpus, in a file another row blocks first.

`test_formal_mlir_precedence.py` is the suite that goes red if any of this moves:
its `CLASSIFIED` rows assert each class's own words AND the absence of another
class's, so an arm that lowers an operation by name alone without establishing
the operand type will red the elementwise row rather than quietly answering a
vector site with a scalar add. Its `EMITTED` table is the other half, and it is
the part that would catch a lowering which builds and computes nothing.
