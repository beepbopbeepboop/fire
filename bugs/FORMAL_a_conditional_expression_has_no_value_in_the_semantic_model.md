# A conditional expression has no value in the arm64 semantic model, and it is the largest single thing between a generated program and a proof

**Area:** FORMAL / proof generation. Found 2026-10-04 on
`work/formal17-fuzz-continue-b` by `tools/formal_proof_fuzz.py`, which
generates programs in the shape the model can state and counts what stops them.
**NOT FIXED** — the refusal is correct and the fix is three layers deep, not a
patch. §"Why closing it is not a patch" says what the three layers are.

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

The 41 arm64 refusals are two families and the first is three quarters of them:

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

On x86-64 the same program produces a proof — because that generator CATCHES the
shared generator's refusal and emits its documented placeholder (fixed earlier
today for the arity, see the commit before this one), which is the trust-
boundary decision `bugs/FORMAL_proof_coverage_census_2026-10-03.md` §6 names
("changing it is a trust-boundary decision"). So the two backends currently
degrade differently for one construct, and only one of them says so in the file.

## Why it is the largest thing in the way

A conditional expression is not an exotic construct: it is `a if c else b` in
every language this compiler targets, and on this path the CODEmIt already
lowers it — `_emit_csel_ternary` when all three operands are pure (arm64), the
branch shape otherwise (x86-64). So the code generator answers the question and
the MODEL refuses it, and the refusal is on the construct real code is full of.
The census already counted it once, over repository functions (§4, one item of
21 that reached the proof layer); over a generated corpus it is 37 of 60.

## Why closing it is not a patch

`_expr_go` is where a `UInt64 → UInt64` value is rendered, and its `TernaryExpr`
arm is a fall-through to `_no_value_model`. Adding one arm is ten lines:

```python
if isinstance(e, TernaryExpr):
    return (f"(if {_cmp_go(e.condition, …)} then {_expr_go(e.then, …)} "
            f"else {_expr_go(e.otherwise, …)})")
```

and that alone changes nothing, because three things downstream each need the
same new case:

1. **the AST bridge** (`_expr_ast` in the same file) renders a `MojoExpr` for the
   same source, and `eval_eq_mojo` states the two layers are the same function.
   `lib/ProofLib.lean`'s `MojoExpr` would need a ternary form — a library
   change, and one that invalidates every cached proof verdict.
2. **the machine half.** arm64's codegen emits `CSEL` for the pure case, and
   `bugs/FORMAL_arm64_csel_is_not_modelled_so_the_step_table_cannot_claim_it.md`
   is the measured statement that `arm64_step` has no arm for it. So on arm64 the
   model would be right and the machine proof would still be unobtainable until
   that lands; the branch-shaped case (impure operands) does not have this
   problem.
3. **the typed model** (`_expr_go_t`) has the same fall-through, and its
   condition must be rendered at the operands' common type.

So the order is: AST bridge + `MojoExpr` (library), `arm64_step` for `CSEL`, then
both models. Item 2 is a project of its own and is already filed.

## The next step

Do item 3 and the **branch-shaped** half of item 1 without touching the library:
emit the ternary as an `if` in `_expr_go` (it is one), and have `_expr_ast`
render the same `if` — `MojoExpr` has no ternary form, but `_if_expand` already
turns an `if`-shaped source into arms, so a source-level conditional expression
could be normalised to an `if` **before** the AST is built rather than modelled
as a new node. That is a parser/normalisation change in the generator, it needs
no `lib/` change, and it makes the two layers agree by construction.

That is a real piece of work (a normaliser, plus both model renderers, plus the
`x86_64_proof_gen` note that says the model is a placeholder today), so it is
written down rather than done.