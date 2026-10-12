# A conditional expression has no value in the arm64 semantic model, and it is the largest single thing between a generated program and a proof

**Area:** FORMAL / proof generation. Found 2026-10-04 on
`work/formal17-fuzz-continue-b` by `tools/formal_proof_fuzz.py`, which
generates programs in the shape the model can state and counts what stops them.

**Status: PARTIAL, and the model's half is FIXED (2026-10-04).** Both models
state `a if c else b` — `formal/arm64_proof_gen.py::_ternary_go`, one renderer
for the untyped and the typed model — and `_expr_ast` now REFUSES the
construct instead of fabricating `MojoExpr.int 0`, so both generators drop the
bridge with the gap named rather than emitting a mirror of a different program.
**What is left is the two halves below, and they are not this model's to
close:** the machine half is a `CSEL` step lemma
(`bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`,
which also carries the certificate-bound blocker) and the cross-check half is a
`MojoExpr` constructor in `lib/ProofLib.lean`. §0 is the measurement of what
changed and §"What is left" is the residue. **The arm64 refusal COUNT is
unchanged** (41 of 60), because on arm64 a conditional expression is one
`CSEL`; what changed is that the refusal names the instruction it cannot step
instead of naming a construct the model now handles.

## 0. What landed, measured, and the one family in §"What was seen" that was
## never this bug

Four pieces, in `formal/arm64_proof_gen.py`, plus the test class
`test_formal_eval_eq_mojo_bridge.py::TestAConditionalExpressionIsAValue`.

1. **`_ternary_go`** renders `a if c else b` as `(if <c is true> then <a> else
   <b>)` for both models, with the value and condition renderers injected. One
   renderer and not two, because the two models differ only in what a value is
   (a raw word, or a word extended at a declared width) and a second copy is a
   second answer to one question — the failure mode this file exists to prevent
   is a model that computes something the machine does not, which Lean accepts
   as long as the generator can find a closing tactic. The CONDITION goes
   through `_cmp_go` / `_expr_bool_go_t`, the same readers an enclosing `if`
   uses, so a signed comparison stays signed and a non-comparison is a test
   against zero (Python's truthiness, `_emit_truthy_word`'s rule on both
   backends). The typed model wraps the SELECTED word at the arms' common type,
   which is the one thing it adds: `t32s (if … then (t8s a) else (t32s b))` for
   `a if a > b else b` with `a: Int8, b: Int32`.
2. **`_expr_ast` refuses** a conditional expression rather than falling through
   to `MojoExpr.int 0`. That fall-through was not a gap in the proof: it put
   `def ast := … [MojoStmt.return (MojoExpr.int 0)]` into the generated file
   under a comment reading "mirrors source code", for a source that says
   `return 1 if n > 3 else 0`. Measured on the x86-64 file at HEAD (reproduced
   by loading this file's pre-change `_expr_go`/`_expr_ast`), the AST for that
   program was literally `MojoStmt.return (MojoExpr.int 0)`.
3. **`_ast_model_cannot_state(fn)` is the ONE reader of "can the untyped AST
   model state this body"**, replacing three separate reads of
   `_range_loop_pattern`. It answers for the loop shape it always answered for
   and for the new one, and it NAMES the shape so the note in the generated file
   says which gap it is. The bridge is OMITTED for such a body — not the proof
   refused — because the machine half can carry the program and refusing it over
   the AST model's missing constructor would be refusing it for the wrong
   reason.
4. **`_cfg_decomposition_refusal`** names the instruction the walk cannot step,
   read off its own encoding (`_unmodelled_instruction`), and only attributes it
   to the conditional expression when it IS a `CSEL`.

**Measured on the corpus this doc was found with** — the same command, same
`--count 60 --arch both --no-check --mix ternary`, 3.4 s, 0.2 GB, ledger
`.tmp/ppf/tern4/records.jsonl`:

| | at HEAD | now |
|---|---|---|
| arm64 `--mix ternary` reaching a proof | 19 of 60 | 19 of 60 (unchanged: `CSEL`) |
| arm64 refusals naming the construct | 37 (`a TernaryExpr has no value…`) | **0** |
| arm64 refusals naming `CSEL` and its measurement | 0 | **38** |
| arm64 refusals naming a `STUR` spill | 0 (the 4 were "CFG decomposition unsupported") | **3** |
| x86-64 model for `return 1 if n > 3 else 0` | the IDENTITY placeholder, with the note "nothing downstream of it is claimed" | the real `(if ((n ^^^ 0x8000…) > (3 ^^^ 0x8000…)) then 1 else 0)` |
| x86-64 `ast` value for the same program | `MojoExpr.return (MojoExpr.int 0)` — a mirror of a different program | absent, with the gap named |

**And the "4 CFG decomposition unsupported" family in the table below was never
this bug.** Re-measured per record, all three of the four are a `STUR`: a
function with enough spilled locals reaches a frame offset a scaled 12-bit
displacement cannot express, the emitter uses the unscaled 9-bit form, and
`arm64_step` has no arm for it — twelve spilled locals is enough to reproduce,
and `bugs/FORMAL_arm64_instruction_coverage.md` already lists `LDUR`/`STUR` as
the one uncovered instruction whose emission carried a real bug. That is a
separate wall with its own row, and a message that blamed the ternary for it
would send a reader to fix the wrong thing, which is what row
`a_spill_is_not_attributed_to_the_conditional_expression` pins.

**Verified with Lean**, which is the half the text rows cannot reach:
`test_formal_eval_eq_mojo_bridge.py::TestTheConditionalExpressionModelTypechecks`
checks the generated x86-64 file — `ok`, and exactly the two designed trust
boundaries as holes (the AST/model conformance theorem and the end-to-end one).
Without `lib/ProofLib.olean` it skips loudly, like its siblings.

## What was run

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label ppfA -- \
  python3 tools/formal_proof_fuzz.py --count 60 --arch both --no-check \
  --mix ternary -j 4 --work .tmp/ppf/tern2      # phase A only: no Lean, no images
python3 tools/formal_proof_fuzz.py --print-program 7 --mix ternary
```

60 generated programs per architecture, `--mix ternary` (the default `plain` mix
has no conditional expression and therefore never reaches this). 5 s wall,
0.3 GB. Ledger: `.tmp/ppf/tern2/records.jsonl`.

## What was seen

| reaching a proof | arm64 | x86-64 |
|---|---|---|
| `--mix plain` (no conditional expression) | 60 of 60 | 60 of 60 |
| `--mix ternary` | **19 of 60** | 60 of 60 |

The 41 arm64 refusals are two families and the first is three quarters of them
(**re-measured: the second is a spill — see §0**):

| n | refusal |
|---|---|
| **37** | `model: a TernaryExpr has no value in the semantic model (a `UInt64 → UInt64` function over the source's arithmetic); refusing rather than modelling it as 0, which would be a false statement about the source` |
| 4 | `universal theorem: CFG decomposition unsupported for this function shape` |

The minimal reproducer is two lines:

```python
def main(n) -> Int:
    a = 1 if n > 3 else 0
    print(a)
    return 0
```

On x86-64 the same program produced a file — because that generator CATCHES the
shared generator's refusal and emits its documented placeholder (fixed earlier
today for the arity, see the commit before this one), which is the trust-
boundary decision `bugs/FORMAL_proof_coverage_census_2026-10-03.md` §6 names
("changing it is a trust-boundary decision"). So the two backends degraded
differently for one construct, and only one of them said so in the file. **§0
lands the other half of that**: the placeholder is gone (the model is real), and
what the file records instead is that the bridge is absent because `MojoExpr`
has no conditional form.

## Why it is the largest thing in the way

A conditional expression is not an exotic construct: it is `a if c else b` in
every language this compiler targets, and on this path the CODEGEN already
lowers it — `_emit_csel_ternary` when all three operands are pure (arm64), the
branch shape otherwise (x86-64). So the code generator answers the question and
the MODEL refused it, and the refusal was on the construct real code is full of.
The census already counted it once, over repository functions (§4, one item of
21 that reached the proof layer); over a generated corpus it was 37 of 60.

**What it is worth now, precisely.** The model half is done and verified against
Lean, so on x86-64 a conditional expression costs a program nothing it was
paying before and buys the whole file a real model. On arm64 it buys a
diagnostic: the program still gets no proof, and the message now says which
instruction is in the way. **The count that would make it "the largest thing in
the way" is unchanged** — 19 of 60 — and it does not move until the machine
half does.

## Why closing it is not a patch (the three layers, re-read after §0)

`_expr_go` is where a `UInt64 → UInt64` value is rendered, and its `TernaryExpr`
arm was a fall-through to `_no_value_model`. Adding one arm is ten lines:

```python
if isinstance(e, TernaryExpr):
    return (f"(if {_cmp_go(e.condition, …)} then {_expr_go(e.then, …)} "
            f"else {_expr_go(e.otherwise, …)})")
```

and that alone changes nothing, because three things downstream each need the
same new case. **Two of the three are now done and one is not**, which is the
whole of what §0 landed:

1. **the AST bridge** (`_expr_ast` in the same file) renders a `MojoExpr` for the
   same source, and `eval_eq_mojo` states the two layers are the same function.
   `lib/ProofLib.lean`'s `MojoExpr` would need a conditional form — a library
   change, and one that invalidates every cached proof verdict. **PARTIAL:** the
   renderer refuses instead of fabricating, both generators omit the bridge with
   the gap named, and the model is proved on its own; the constructor itself is
   still missing.
2. **the machine half.** arm64's codegen emits `CSEL` for the pure case, and
   `bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`
   is the measured statement that `arm64_step` has no arm for it. **NOT DONE**,
   and it is the one that decides the count. **Its order is also the reverse of
   what this section assumed**: the `CSEL` branch is a three-line Lean change
   blocked behind the certificate bound in
   `bugs/FORMAL_a_three_branch_certificate_exceeds_the_lean_bound.md`, and the
   branch-shaped case (impure operands) has no `CSEL` at all — but no program in
   the `--mix ternary` corpus has impure operands, because the generator writes
   them from names and literals.
3. **the typed model** (`_expr_go_t`) had the same fall-through, and its
   condition must be rendered at the operands' common type. **DONE**, with the
   result carried at the arms' common type as well (§0 item 1).

## What is left, in the order a taker should do it

1. **`arm64_step` + `_STEP_CONDS` for `CSEL`**, i.e.
   `bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`,
   whose own next step says the certificate bound must be fixed first. That is
   another lane's claim; it is what makes a conditional expression worth having
   on arm64 and nothing here substitutes for it.
2. **`MojoExpr`'s conditional form** in `lib/ProofLib.lean` plus the matching
   `evalExpr` arm and `evalExpr_unop` congruence — the same three-place shape
   the `bnot` row in `test_formal_eval_eq_mojo_bridge.py` pins. Until then the
   bridge is absent for these programs and the note in the file says so.
3. **The normalisation this doc originally proposed is not needed and should not
   be built**: rewriting the source to an `if` before the AST is built would
   change the emitted code (a `CSEL` becomes a branch, which is the win
   `_emit_csel_ternary` exists for) and would make the model describe a program
   the machine does not run. The model states the construct as it is emitted.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
mkdir -p .tmp/tern && cat > .tmp/tern/t.mojo <<'EOF'
def main(n):
    a = 1 if n > 3 else 0
    print(a)
    return 0
EOF
# arm64: the refusal now names the instruction and its measurement
python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
  -o .tmp/tern/t.proof .tmp/tern/t.mojo
# x86-64: a real model, no `ast`, two designed holes, and it CHECKS
python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_eval_eq_mojo_bridge.py
# the corpus, per record, with the CSEL/STUR split
python3 tools/memslot.py --gb 8 --label ppfA -- python3 tools/formal_proof_fuzz.py \
  --count 60 --arch both --no-check --mix ternary -j 4 --work .tmp/ppf/tern4
```
