# A generated proof that exceeds Lean's memory ceiling is REJECTED, and four short-circuit proofs are red for that reason alone

**Area:** FORMAL (the arm64 proof generator's output vs `formal/lean.py`'s Lean
run). Found 2026-10-03 on `work/formal16-7`, while landing a change to
`formal/arm64_proof_gen.py` and running `test_formal_short_circuit_cond.py` as
one of the narrow files that cover it. **NOT FIXED — and it is not the proof
generator's model, which is why it is filed rather than fixed here.**

## What was run, and what it showed

`test_formal_short_circuit_cond.py` on this tree, arm64, Lean present:

```
$ python3 tools/memslot.py --gb 8 --label scc -- \
      python3 test_formal_short_circuit_cond.py
...
Ran 12 tests in 393.868s
FAILED (failures=4)
```

All four are the same subtest of one assertion, and all four say the same
thing:

```
FAIL: test_generated_proofs_typecheck_with_no_sorries (program='either')
AssertionError: False is not true : either: either_proof.lean:5517:8:
    error: (kernel) excessive memory consumption detected
FAIL: … (program='both')
FAIL: … (program='short_and')
FAIL: … (program='short_or')
```

`either` is `formal/examples/either.mojo` verbatim:

```python
def either(n):
    if n > 10 or n == 0:
        return 1
    else:
        return 0
```

and `bugs/sweeps/proof_breadth_2026-10-03.jsonl` records that file as
`{"ident": "examples/either.mojo", "arch": "arm64", "cls": "pass",
"n_sorries": 0}`. **So this is a regression against the 2026-10-03 census, not
a long-standing red**, and the eight generator-level tests in the same file
(`test_cond_nodes_agrees_with_collect_conds`, `test_condition_pairing_filters_on_the_recorded_branch`, …) all pass — the model, the branch pairing and the step lemmas are all fine. Only Lean's kernel gives up.

## Where it happens, precisely

The error is at a `def … : Prog :=` — the program's CFG record — not at a
theorem:

```
$ sed -n '5512,5517p' either_proof.lean
  exact either_b6_runs st hpc

def either_prog : Prog :=
  { fname := "either", code := either_code, base := 4294967968, entry := 4294967988,
    exit := 4294968176, fuel := fun n => (200000 + 46 * n.toNat),
    blocks := [either_blk_0, …, either_blk_6],
    rets := [4294968148, 4294968172] }
```

The file is **688 KB** and 16 `sorry`s; every one of them is a named trust
boundary, so the hole count is not what is being complained about. `Prog`
carries a `blocks : List …` and a `fuel : Nat → Nat`, and a short-circuit
condition is exactly the shape that multiplies the block count: `either` has
7 blocks for 12 instructions, and the record has to be re-checked by the
kernel against the block definitions above it.

## It is NOT the string model, and that is measured rather than assumed

`work/formal16-7`'s change to `formal/arm64_proof_gen.py` (a string literal's
value in the model is its interned address) was in the tree while this ran, so
the obvious first question is whether it caused this. **It did not, and the
proof is a byte comparison**: with the change reverted in place
(`git apply -R` of its own diff — never `git checkout <path>`), `either`
generates an **identical** 688 KB file:

```
$ cmp either_HEAD_proof.lean either_proof.lean && echo IDENTICAL
IDENTICAL
```

and Lean rejects it identically. `either` contains no string literal, so the
only two of the change's four sites it could reach are the signature changes on
`_expr_ast`/`_stmts_ast`, which emit no text.

## The next step, and it is a decision rather than a patch

Three things are available and which one is right depends on a fact nobody has
measured:

1. **`formal/lean.py`'s Lean invocation.** Lean takes `maxHeartbeats` from the
   generated preamble (`set_option maxHeartbeats 20000000`) and has a
   `maxMemory` besides it that this file does not set. `(kernel) excessive
   memory consumption` is the `maxMemory` arm, so **the cheapest thing to try
   is `set_option maxMemory` in the generated preamble** — the same lever the
   file already pulls for `maxRecDepth` and `maxHeartbeats`, in the same three
   lines. Measure whether a higher `maxMemory` (or removing it) lets these four
   through before assuming the record has to shrink.
2. **Shrink the `Prog` record.** `fuel := fun n => (200000 + 46 * n.toNat)` is
   a function inside a structure the kernel has to compare for conversion; a
   `Nat` constant or a named `def` would be cheaper to check. This is
   `formal/arm64_proof_gen.py`'s `_gen_universal_e2e_cfg` and is a change to
   what is emitted, not to what it means.
3. **Do nothing here and let it be a census fact.** The eight Lean-checking
   formal gate tests are disabled, so nothing red is visible in a gate today —
   which is precisely why this is worth a doc: it is invisible, it is a
   regression against a recorded pass, and the next session to touch
   `arm64_proof_gen.py` will meet it as "the short-circuit proof test fails".

**Not measured here:** whether (1) works, what `maxMemory` the run is actually
defaulting to, and whether the four failures are one cause or a threshold that
four files happen to cross. The first of those is a one-line experiment on an
existing 688 KB file and is the next step.

## Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
mkdir -p .tmp/scc && cat > .tmp/scc/either.mojo <<'EOF'
def either(n):
    if n > 10 or n == 0:
        return 1
    else:
        return 0
EOF
python3 tools/memslot.py --gb 8 --label pg -- \
  python3 fire.py build --formal -o .tmp/scc/either.proof .tmp/scc/either.mojo
# build: proof check failed: either_proof.lean:5517:8: error:
#   (kernel) excessive memory consumption detected
```