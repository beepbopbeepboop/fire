# FORMAL_nested_short_circuit_chain_in_a_condition: `((a or b) or c)` is still unproved

`if a or b:` and `if a and b:` as a whole condition are **proved** (the
per-path entry statement they needed is in `formal/arm64_proof_gen.py`;
`formal/examples/either.mojo` and `both.mojo` build AND typecheck). A chain
NESTED inside a chain is not, and this says why and what closes it.

## What was measured

```
$ cat .tmp/nc/nested_or.mojo
def f(n):
    if n > 10 or n == 0 or n < -4:
        return 1
    else:
        return 0
$ python3 fire.py build --formal -o .tmp/nc/nested_or.aout .tmp/nc/nested_or.mojo
nested_or_proof.lean:25:54:      error: unsolved goals        -- eval_eq_mojo
nested_or_proof.lean:5277:259:   error: counterexample       -- a merge hcond
nested_or_proof.lean:5324:261:   error: counterexample
nested_or_proof.lean:5668:257:   error: counterexample
nested_or_proof.lean:5720:259:   error: counterexample
```

The failure is honest — Lean rejects the file rather than accepting a
`sorry`-backed theorem — so nothing is silently wrong; the program simply has
no proof.

## Why the two-path statement does not reach it

`_emit_truthy_word` recurses, so a nested chain is a chain of chains and the
OUTER merge block has **four** entry paths, not two, each with a *different*
cset having written the condition register:

| path | X0 holds |
|---|---|
| outer taken, inner taken (`a`) | `a`'s cset |
| outer taken, inner fall (`b`) | `b`'s cset |
| outer fall (`c`) | `c`'s cset |

The machinery that was added states the merge block's register as ONE
operand's cset, found by looking back along the path for the block whose cset
wrote that register (`_cset_registers` in `formal/arm64_proof_gen.py`). That
works for a two-operand chain because each entry path has exactly one cset
before it. Here the outer merge's left operand is *itself* a chain, so
"the left operand's condition" is not one operand's cset — it is the value of
a sub-chain, and the fact that pins it (`hscL`) describes the sub-chain's
left operand, not the outer one.

## The next step

Recurse instead of stopping at two levels: make the travelling fact a *value*
fact rather than a boolean one. Concretely, the merge block's statement should
be

    arm64_reg r <merge> = 0 ↔ ¬(<the operand whose cset wrote r, on this path>)

with the cset's OWN condition recovered from the block it is in (the flag
lemma plus the block's `qT` chain, which `_cond_flag_lines` already does for
`loop_cond_flag`), rather than from the source AST. That makes the statement
independent of how many chains are nested, because every entry path then names
the machine's own answer instead of a source-level operand.

Two things to keep:

  * the recombination step (`_sc_merge_hsrc`) still needs the OTHER operand's
    fact, and for a nested chain "the other operand" is a sub-chain, so
    `hscL` has to be a fact about a sub-chain's VALUE. The natural shape is a
    `def <chain>_val (left : Bool) (right : Bool) : Bool` in the generated
    file with a `by_cases` proof of the `or`/`and` law, which then composes at
    any depth;
  * `either`/`both` must keep proving after that — they are the canary for the
    non-nested case and `test_formal_short_circuit_cond.py` is where that is
    asserted.

**Done when:** the program above builds and its proof typechecks, and
`test_formal_short_circuit_cond.py`'s `KNOWN_GAP` entry for it is deleted.