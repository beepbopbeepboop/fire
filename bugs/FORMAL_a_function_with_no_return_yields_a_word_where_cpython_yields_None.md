# FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None

**Area:** FORMAL, both backends — the answer comes from
`formal/model.py`'s `ValueKinds._value_kind` ("`kind_of(value)`, or `INT_KIND`
when it is unclassified and is not a container") together with an epilogue that
does not write the return register (`formal/arm64_codegen.py::_emit_epilogue`
emits the scratch teardown, the frame restore and `RET`, and nothing else), so
nothing in the pair knows the callee returns nothing.
**Status: NOT FIXED. Minimised, measured on both architectures, and NOT a patch
— the fix is a decision about what this path does with `None`, and it has a
blast radius this session did not have the budget to measure (§4).**

Found 2026-10-03 on `work/formal17-fuzz-continue-a` by `tools/formal_fuzz.py`,
on the `strings` mix, seeds 0-3 — and, worth saying because it is unusual,
**not from the generator**: the generated program agreed on everything except a
`print` of one call's result, and the disagreement became visible only after the
minimiser deleted a `return` statement from a helper (`shrink` removes
statements, and a helper whose body is left with no `return` is a program with a
different defect in it). The reduced program is the minimal one and it is below.
The full program and the reduced program are both in
`.tmp/fz/sweep/strings/findings.json` in the worktree it was found in.

## 1. What is wrong

A `def` with no `return` statement returns a WORD, and the word is printed as
an integer, where CPython returns and prints `None`.

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove -o .tmp/x .tmp/probe/p82.mojo
```

`p82.mojo`:

```mojo
def g(a, b):
    w = 1

def main() -> Int32:
    print(g(1, 2))
    print(5)
    return 0
```

| source | CPython 3.14 | arm64 | x86-64 |
|---|---|---|---|
| `print(g(1, 2))` | `None` | `0` | `0` |
| `print(5)` | `5` | `5` | `5` |

Both images build, run and exit 0. Two further shapes, measured:

* through a local — `v = g(1, 2); print(v)` prints `0` on both;
* after a call that returned something —

  ```mojo
  def noisy(a, b):
      print("side")
      return 77

  def quiet(a, b):
      w = 1

  def main() -> Int32:
      print(noisy(1, 2))
      print(quiet(3, 4))
      return 0
  ```

  prints `side / 77 / 0` on both images and `side / 77 / None` on CPython — so
  the value is NOT the caller's leftover (77 does not survive), and the honest
  description is "whatever the callee's last instruction left in the return
  register", which was 0 in every case measured here and is not guaranteed to
  be.

The `-> Int32` spelling is not the subject: `def quiet(a) -> Int32: w = 1;
return 0` agrees with CPython, and so does any function that RETURNS. The
subject is the function that falls off its end.

## 2. Why it is not a one-line fix

Two directions, and they are not equivalent in what they cost.

**(a) Refuse where the value is OBSERVED.** The value model already refuses
`print(x)` when `x` is an unclassified name ("print() cannot tell whether
IdentExpr is a string or a number on the formal … path, and guessing would
print an address as if it were text"), and `print(g(...))` is the same question
one call deeper: the callee states nothing, so the same guess follows. The
predicate exists and is already computed per function: `ValueKinds._returns` is
empty for a function with no `return`, and `ValueKinds.return_is_dict` /
`func_kind` are asked from it. So the refusal has a home.

**The blast radius is the reason this is not done here.** The refusal would fire
on `print`/`len`/`%s` of such a call — and on a stdlib or host-module file that
prints the result of a side-effecting helper, which is ordinary Python. That is
a NEW refusal, and the rule this repository holds itself to is that a
type-resolution or shape change must not move the `skip <module>:` count in
`stdlib-dylib` (§ "Two gate verdicts need judgement" in `CLAUDE.md`). Measuring
that means `compile_stdlib.py` and `build_stdlib_dylib.py`, which are the
integrator's jobs and not this worker's. **So the first step of any fix is to
run those two and record the two counts before touching a refusal.**

**(b) Represent `None`.** A distinguished word (a pointer to a `__DATA` cell, or
a tag like the type index already in this model) makes every *use* correct
rather than only the observed ones — `if g():` is already right by accident
(0 is falsy like `None`), `x is None` and `x == None` are not. That is a change
to the value model itself, to both emitters' return paths, and to the Lean
model in `lib/ProofLib.lean` if the proofs are to keep checking, which makes it
a project rather than a patch.

The recommendation is (a) with the counts measured first, because it is the
direction this path already takes everywhere else it cannot tell what a word
holds, and because a refusal is a sentence a reader can act on where `0` is not.

## 3. What this is NOT

* **Not a miscompile of a construct that has a representation.** `None` is
  genuinely absent from this value model — one 64-bit word per value, and a
  word has no way to say "no value" (`formal/model.py`'s "What a value is"
  section). This is the same class as `bugs/FORMAL_string_value_model.md`: the
  question is what the path does when the source says something the word cannot
  hold, and the answer must not be a plausible number.
* **Not the arm64/x86-64 divergence class.** Both machines answer `0`. It is
  reported here because it is a wrong answer, not because the two disagree.
* **Not a fuzzer artefact to be silenced.** It must NOT become a
  `KNOWN_DIVERGENCES` row: `tools/formal_fuzz.py`'s rule is that a row is a
  claim that the corpus still MEASURES the construct, and the corpus cannot
  produce a function with no `return` — `Gen.define_function` always emits one.
  A row nothing can trigger is a row that has stopped measuring. If the
  generator is ever taught to emit a helper with an empty body, this is the
  construct to add, and this doc is what it should point at.

## 4. The exact next step

1. Measure `compile_stdlib.py`'s `FAILED: N (E expected, U unexpected)` and
   `build_stdlib_dylib.py`'s `skip <module>:` count on master, and keep them.
2. Add to `formal/model.py` a refusal with the shape of
   `print_kind_refusal`, asked where a call's VALUE is consumed as a value and
   the callee is a function of this module whose `_returns` set is empty and
   whose declaration states no return type. Name the callee and say that CPython
   returns `None` and this path has no representation for it — the same wording
   discipline `string_concat_refusal` uses, and for the same reason: a reader
   told only "cannot tell" goes looking for something to look at.
3. Ask it from BOTH backends' single choke point for a call's value, or the two
   will drift the way `_is_dict_subscript` and `is_dict_expr` did.
4. Re-run the two counts from step 1. If either went up by more than the rows
   that are genuinely `None`-printing, the answer is (b), not (a).

## 5. A second thing this found, about the fuzzer itself

The disagreement was INVISIBLE in the generated program and appeared only after
`shrink` deleted a `return`. That is worth knowing as a property of the tool
rather than as a defect in it: the minimiser is allowed to leave constructs in a
reduced program that the original did not have, and `blame` then correctly
reports the disagreement as unexplained — because the explanation is a construct
the generator never intended to emit. `tools/formal_fuzz.py`'s attribution
already states the conservative direction it takes when a disagreement is not
explained ("there is a known bug in here too is not a reason to miss this one"),
and this is the case that direction is for: **a finding reached through the
minimiser is a finding about a construct the corpus does not cover, and the
ledger records it as one.**
