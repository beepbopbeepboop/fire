# FORMAL_a_negative_constant_beside_a_declared_unsigned_operand_promotes_to_unsigned

**Area:** FORMAL, both backends — `formal/types.py`'s `infer_expr` (the
`UnaryOp` and `BinaryOp` arms) and `common_type`.
**Status: NOT FIXED, and NOT a doc-driven sweep finding — found by
`tools/formal_fuzz.py` on 2026-10-03 while probing what
`bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness.md` had already fixed.**

## The reproducer

```mojo
def main(n):
    x: UInt32 = 7
    print(1 if (0 - 3) < x else 0)
    return 0
```

| | |
|---|---|
| CPython 3.14 | `1` (`-3 < 7`) |
| arm64 | **`0`** |
| x86-64 | **`0`** |

Builds, runs, exits 0. `(0 - 3)` is `0xFFFF…FD` under an unsigned comparison, so
it compares as greater than `7`.

## Why it survives the fix that closed the neighbouring bug

`common_type` is signed-wins, so a TYPED signed value beside a `UInt32` is
signed and the comparison is right. The gap is the *flexible* operand: `0 - 3`
has no declared type, `common_type` treats `None` as neutral, and the declared
`UInt32` is what decides. That is the right rule for a value whose type its
context supplies — and this value's type its context cannot supply, because
`-3` is not a `UInt32`.

`infer_expr` already knows this argument and already acts on it for one spelling.
Its `UnaryOp` arm reports a negated `IntLiteral` as `IntType(64, True)`, and the
comment there is the reasoning in full: "a negative value cannot be an unsigned
one: with both operands typeless, `common_type` is None, `cmp_signed(None)` is
False, and the comparison was emitted with unsigned condition codes". Since
2026-10-03 the second half of that sentence is no longer true (`cmp_signed`
resolves a flexible type to the signed default), but the conclusion has not
changed: `-3` is not unsigned, and the arm is still right to say so.

What is missing is the same reasoning for the OTHER spelling of a negative
constant — a `BinaryOp` that folds negative, which is what `0 - 3` is:

```python
if isinstance(e, F.BinaryOp):
    t = common_type(infer_expr(e.left, ...), infer_expr(e.right, ...))
    # MISSING: a constant negative value cannot be unsigned, whatever the
    # context says — the same argument the UnaryOp arm above makes.
    return t
```

## The next step, and the one thing not to do

Add the check to the `BinaryOp` arm, next to the `UnaryOp` one it mirrors, using
`formal/model.py`'s `fold_literal_expr` — which is the folder that already
answers "what does the build know this expression is", and answers `None` for an
opaque one so a variable is never mistaken for a constant. **Do not write a
second folder here**: `formal/types.py` cannot import `formal/model.py` (model
imports types), so a local one would be a third reading of the same question, and
the two would eventually disagree about a shape. Either move `fold_literal_expr`
down into `formal/types.py` — it is a pure function of an AST node and has no
model dependency — or have `infer_expr` take an optional folder from its caller.
The first is the smaller change: `fold_literal_expr`'s own docstring says its one
parameter exists for a single caller, so it has no back-pointer to keep.

Preserve the WIDTH `common_type` already decided and flip only the sign, so
`x: UInt8 = 7` beside `(0 - 3)` stays eight bits wide:

```python
folded = fold_literal_expr(e)
if isinstance(folded, int) and not isinstance(folded, bool) and folded < 0:
    return IntType(t.width if t is not None else 64, True)
return t
```

Two rows in `test_formal_run.py` beside `both_arch_a_declared_unsigned_operand_
is_still_unsigned`, which is the guard that must not move: a declared unsigned
value compared with a POSITIVE constant is still unsigned, and a fix that made
every flexible operand signed would break it.

## Reproducing

```console
$ python3 tools/memslot.py --gb 8 --label probe -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/mixed.mojo
$ ./.tmp/x          # 0, where CPython prints 1
```

The fuzzer finds this shape only by accident — it needs a declared unsigned
operand, which its generator does not emit — so the reproducer above is
hand-written, and the row belongs in the suite beside the flexible-signedness
ones rather than in the fuzzer's corpus.