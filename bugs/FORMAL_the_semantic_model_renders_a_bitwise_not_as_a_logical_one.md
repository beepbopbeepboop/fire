# FORMAL_the_semantic_model_renders_a_bitwise_not_as_a_logical_one: `~x` is modelled as `x = 0`, so the model of any program using `~` is FALSE

**Area:** FORMAL (the semantic model both backends share). **Status: OPEN, not
fixed, with the diagnosis and the exact fix.** Found 2026-10-03 by
`tools/formal_proof_breadth.py`'s proof-breadth census
(`bugs/FORMAL_proof_coverage_census_2026-10-03.md`), on a function extracted
from this repository's own `formal/macho_linker.py`.

**This is a MODEL bug, not a codegen bug and not a proof bug: the machine is
right, the model is wrong, and the only reason it has not produced a false
theorem is that the run tests are `native_decide` and they caught it.**

## The measurement

`formal/macho_linker.py:236`, verbatim as the census emits it:

```python
def executable_entry_offset(sizeofcmds: int) -> int:
    return ((32 + sizeofcmds + CODE_SIGNATURE_CMDSIZE) + 31) & ~31
CODE_SIGNATURE_CMDSIZE = 16
def main(x):
    return executable_entry_offset(x)
```

```sh
$ python3 tools/formal_proof_breadth.py --show executable_entry_offset   # the module
$ for n in 5 0 40; do python3 fire.py build --formal --no-prove -n $n -o .tmp/p$n.aout .tmp/prog.mojo && ./.tmp/p$n.aout; echo "n=$n exit=$?"; done
n=5 exit=64
n=0 exit=64
n=40 exit=96
$ python3 -c 'for x in (5,0,40): print(x, ((32 + x + 16) + 31) & ~31)'
5 64
0 64
40 96
```

**The machine is right** — 64, 64, 96, which is what CPython computes. And the
x86-64 proof says so, in its own words:

```
main_result 5 = mojo 5
is false
```

so `mojo 5 ≠ 64`. Here is the model that says otherwise, from the generated
`p_proof.lean`:

```lean
def executable_entry_offset_go (sizeofcmds : UInt64) : UInt64 :=
  (((((UInt64.ofNat 32) + sizeofcmds) + (UInt64.ofNat 16)) + (UInt64.ofNat 31)) &&&
    (if (UInt64.ofNat 31) = 0 then (1 : UInt64) else (0 : UInt64)))     -- `~31`
```

`~31` is rendered as **`if 31 = 0 then 1 else 0`**, i.e. `0`. So `mojo 5 = 84 &&& 0
= 0`, and the model's value is zero for every input. The `&&&` is right; the
operand is the bug.

## Why it is a bug and not a limitation

Python's `~` is **bitwise** complement; `not` is the logical one. The generator
has one case for both:

* `formal/arm64_proof_gen.py:586` (`_expr_go`, the untyped model):
  ```python
  if isinstance(e, Unary):
      op = _expr_go(e.operand, param, env, vtypes, call_types, scope)
      if e.op == "-":
          return f"(0 - {op})"
      return f"(if {op} = 0 then (1 : UInt64) else (0 : UInt64))"
  ```
* `formal/arm64_proof_gen.py:825` (`_expr_go_t`, the typed model): the same two
  cases, with the `-` wrapped in the width's truncator.
* `formal/arm64_proof_gen.py:1684` (`_expr_ast`, the AST layer):
  ```python
  opname = "neg" if e.op == "-" else "not"
  ```
  and `lib/ProofLib.lean:820` evaluates `unop "not"` as
  `if … = 0 then 1 else 0` — so **the AST layer makes the same mistake**, which
  is why `eval_eq_mojo` does not catch it: both sides agree, and both are wrong.
  They agree about a different program than the one the machine ran.

**Why nothing else caught it.** `formal/model.py:24199` has `"~": lambda v:
~v` in its interpreter-side table, so the tree's own interpreter is right — the
error is only in the PROOF LAYER's model, which is a separate implementation
(`CLAUDE.md`'s "a parser change can be invisible to the interpreter suites").
No example in `formal/examples` uses `~`, and `test_formal.py` runs those.

**Why it has not produced a false theorem yet.** The x86-64 generator's run
tests are `native_decide` over the machine model, so a wrong model is caught
wherever a run test exists — and a run test exists for every non-typed program.
The exposure is the shapes with no run test: a **typed** (fixed-width) function
takes the machine-value-flow path with the `eval_eq_mojo` bridge omitted (see
`generate_arm64_proof`'s `is_typed` branch), and there the model is the only
statement of what the source means. Fixing only the `_go` halves would make it
WORSE, not better: then `eval_eq_mojo` (AST says `not`, model says `^^^
0xFFFF…`) would become false for every program using `~`, so the fix has to
carry all three sites plus the library.

## The exact next step

1. **`lib/ProofLib.lean`**: give the AST layer its own operator rather than
   overloading `not`, because `not` is genuinely logical and used by every
   condition in the corpus:
   ```lean
   | MojoExpr.unop "bnot" operand => evalExpr callFunc operand env ^^^ (0xFFFFFFFFFFFFFFFF : UInt64)
   ```
   with `unop`'s catch-all arm left as it is.
2. **`formal/arm64_proof_gen.py:1684`**: `opname = {"-": "neg", "~": "bnot"}.get(e.op, "not")`.
3. **`formal/arm64_proof_gen.py:586`**: `if e.op == "~": return f"({op} ^^^ 0xFFFFFFFFFFFFFFFF)"`.
   `^^^` is already the spelling `^` uses, and `UInt64.xor` is 64-bit, so the
   untyped model needs no library helper.
4. **`formal/arm64_proof_gen.py:825`** (typed): the complement has to be taken
   **at the declared width**, because a 32-bit `~x` is `t32u (x ^^^
   0xFFFFFFFF)` and not `x ^^^ 0xFFFFFFFFFFFFFFFF`. `_t_wrap` already takes the
   width, so this is `_t_wrap(f"({op} ^^^ 0x{mask})", t)` with the mask from the
   width.
5. **A test beside the model tests**, asserting all three: that the emitted
   model of `def f(n): return ~n` is `^^^ 0xFFFFFFFFFFFFFFFF` and not an `if`,
   that the AST node is `unop "bnot"`, and — the teeth — that
   `f`'s `main_result n = mojo n` run test TYPECHECKS on both backends. That
   last one fails today with `is false`, which is the same failure this doc
   measured.

**Cost of doing it, so it is not started blind:** step 1 changes
`lib/ProofLib.lean`, so every cached proof verdict in `~/.gmojo` is invalidated
and `lib/ProofLib.olean` is rebuilt (~90 s, 7.7 GB — `bugs/PERF_memory_over_4gb_is_a_bug.md`'s
standing debt). Budget the whole `formal` proof suite behind it, not one
example.

## What is NOT the cause

* **Not the code generator.** It computes 64 where CPython computes 64, on both
  arches (`~` lowers to `ORN`/`NOT`, and both are in the step tables).
* **Not the interpreter.** `formal/model.py`'s own table has `"~": lambda v: ~v`.
* **Not `& ~31` being a weird idiom.** `& ~31` is the ordinary 32-byte-align
  idiom and this repository uses it in three places; the model is wrong for
  every `~`, whatever it is applied to.