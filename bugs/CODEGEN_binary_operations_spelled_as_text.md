# 16 binary operations are still spelled as text and skip operand conversion

Class: easy. One mechanical rewrite, 16 sites, no new logic and no second
implementation. Read `doc/GIR.md` "Stage 2a, binary operations" first.

Measured 2026-11-14 on this tree: `python3 test_gimple_lint.py unit` prints
`16 binary operations spelled as text (baseline 16)`. Set
`TEXT_BINOP_BASELINE = 0` in `test_gimple_lint.py` and the same command lists
every site, one per line:

    mojo/backend_gimple/emit_calls.py:8114: 1LL << 32
    mojo/backend_gimple/emit_exprs.py:5086: {} = {} {} 0;
    mojo/backend_gimple/emit_loops.py:149: {} = {} < {};
    ...

(`{}` stands for an f-string hole.)

## Why it matters

GIMPLE requires both operands of `a + b` to have the result's type, and both
operands of `a < b` to have each other's type. An `int` variable added to an
`int64_t` variable is an error GCC reports only in a `__GIMPLE`-tagged
function, and silently miscompiles elsewhere. The helpers below look up each
operand's declared type and write the conversion out. A right-hand side
written as text inside `gen._emit(f"...")` or `gen._new_val(t, f"...")` gets
no conversion.

## Goal

Rewrite each site with one of these three helpers
(`mojo/backend_gimple/emit_resolve.py`):

    # before                                         # after
    t = gen._new_val('int64_t', f"{a} + {b}")         t = gen._binop('int64_t', a, '+', b)
    c = gen._new_val('_Bool', f"{a} < {b}")           c = gen._cmp(a, '<', b)
    gen._emit(f"  {t} = {a} & {b};")                  gen._binop_into(t, a, '&', b)
    gen._emit(f"  {t} = {x} {op} 0;")                 gen._binop_into(t, x, op, '0')

Rules:

- Each operand is a Python `str`: a temp or variable name, or literal C text
  such as `'0'`, `'1LL'`, `'255ULL'`.
- An operand that is not certainly a `str` (an `int`, a value read from a
  dict or a list) is wrapped so the text stays exactly what the f-string
  produced: `f"{x}"`. Example: `f"{cur} | {1 << bit[1]}ULL"` becomes
  `gen._binop_into(nxt, f"{cur}", '|', f"{1 << bit[1]}ULL")`.
- An operand written with parentheses, `f'({kret_v}) == 0'`, keeps them:
  `gen._cmp(f"({kret_v})", '==', '0')`.
- Extra spaces in the old text (`f"  {t_lt}   = {ctr} < {stop_v};"`) are not
  kept. That site's output changes by those spaces only; say so in the commit.
- Do not change what is computed. Do not add or remove a cast.

## How to verify

1. `python3 test_gimple_lint.py unit` must print `0 binary operations
   spelled as text`. Set `TEXT_BINOP_BASELINE = 0` in the same commit.
2. `python3 test_gimple.py` must print `460 passed, 0 failed` (or the same
   counts as before your change, if another branch has moved them).
3. `python3 tools/suite.py stdlib-syntax stdlib-dylib gimple-lint` must pass.

## Done when

`TEXT_BINOP_BASELINE` is 0, the three checks pass, and this file is deleted
in the same commit (then run `python3 tools/dangling_doc_refs.py --ratchet`).
A partial round (some sites done) lowers `TEXT_BINOP_BASELINE` to the new
count and lists the remaining sites here.
