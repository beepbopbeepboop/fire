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

**Re-measured 2026-10-03 (`work/formal18-1`): §2's objection to direction (a) —
"the blast radius is unmeasured, and measuring it means the two counts that are
the integrator's jobs" — is now HALF answered, and the half that could be
measured cheaply says the refusal is much narrower than §2 feared. §0 has the
census; §2's recommendation stands and its reason is now a number rather than an
admission.**

Found 2026-10-03 on `work/formal17-fuzz-continue-a` by `tools/formal_fuzz.py`,
on the `strings` mix, seeds 0-3 — and, worth saying because it is unusual,
**not from the generator**: the generated program agreed on everything except a
`print` of one call's result, and the disagreement became visible only after the
minimiser deleted a `return` statement from a helper (`shrink` removes
statements, and a helper whose body is left with no `return` is a program with a
different defect in it). The reduced program is the minimal one and it is below.
The full program and the reduced program are both in
`.tmp/fz/sweep/strings/findings.json` in the worktree it was found in.

---

## 0. The census §2 asked for, over the repository AND the stdlib

§4's step 1 is "measure `compile_stdlib.py`'s `FAILED: N (E expected, U
unexpected)` and `build_stdlib_dylib.py`'s `skip <module>:` count". Those are two
hours and two gigabytes and they belong to the integrator. What can be measured
without either is the question the refusal would actually be asked about: **how
many call sites in this corpus consume the value of a function that has no
`return`?** A census over `fire_compiler.Parser`'s own AST, over this worktree's
`*.mojo` and all 252 under `../new-modular/Mojo/stdlib/std`:

| | |
|---|---|
| files scanned | every `*.mojo` under `.` and `../new-modular/Mojo/stdlib/std` |
| functions whose body has no value-returning `return` | **1586** |
| call sites of one, from the same module | **682** |
| …of which the call's VALUE is consumed (it is an argument of another call) | **48**, in **4 files** |

**And every one of those 48 is an artefact of the census being NAME-keyed.**
The four files are `utils/coord.mojo`, `testing/prop/strategy/string_strategy.mojo`,
`itertools/itertools.mojo` and `_gpu/host/info.mojo`, and the call sites are
`self.value()`, `self._flatten()`, `self.normalize_target_arch()` — calls through
a receiver. `coord.mojo` declares `def value` **three times** (lines 59, 150,
395) and `info.mojo` declares `normalize_target_arch` twice (214, 224); at least
one definition of each RETURNS a value, and a `{name: has-no-return}` set cannot
tell which. That is the imprecision every by-name table in `formal/build.py`
already refuses to have ("a name whose definitions disagree about whether they
return a frame is absent from it"), and a census that repeats it answers a
question nobody asked.

**So: zero free-function call sites in the whole corpus consume the value of a
return-less function, and the only rows a syntactic census reports are
overloaded method names.** That is a strong result for direction (a) and it is
not sufficient on its own, for two reasons the reader should not skip:

  * **it is syntactic and same-module.** A call through a receiver, and a call
    into an IMPORTED module, are both outside it, and a method's value being
    consumed is exactly the case the doc's own §1 shape is (`self.value()` is
    how a `DType`-like accessor reads). The right census keys on the resolved
    DEFINITION (`formal/build.py`'s `_name_defs`), not on the name.
  * **`compile_stdlib.py`'s `U` count is a different question.** It counts files
    that stop compiling, and the four files above are inside the stdlib the gate
    builds. Whether each of them is a genuinely `None`-printing row is still the
    question §4's step 4 asks, and it is answerable only by the two counts.

The census's script is `.tmp/census_none.py` in the worktree that wrote this
section, and it is deliberately left in `.tmp` rather than promoted: a census
whose own imprecision is this large is not a tool, it is a measurement with a
footnote.

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

0. **Re-do §0's census keyed on the resolved DEFINITION** (`formal/build.py`'s
   `_name_defs`), not on the name, and include calls through a receiver and into
   an imported module. §0's zero is a floor, not the count: it is the count with
   every overloaded method name removed by hand. That is a half-day and it is the
   difference between "direction (a) reaches four stdlib files" and "direction
   (a) reaches none".
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
