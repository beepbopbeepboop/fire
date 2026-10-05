# `formal/examples/fact.mojo`'s `@ensure(result >= 0)` is FALSE, and nothing
# reported it for as long as the decorator existed

**Status: FOUND and now REPORTED on every build. The fix is a one-line change to
an example file, deliberately not made here — see §4.**

## 1. What I ran and what I saw

```
$ python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import fire_compiler as F
from formal import contracts as CT
path = 'formal/examples/fact.mojo'
src = open(path).read()
fn = [f for f in CT.functions if False] # (via test_formal_contracts.py's reader)
PY
```

Concretely, the row is
`test_the_corpus_facts_own_contract_is_false` in `test_formal_contracts.py`:

```
$ python3 test_formal_contracts.py -v 2>&1 | grep corpus_contract
PASS  the_corpus_contract_is_REFUTED
```

and the verdict it prints is:

```
fact: REFUTED — a bounded search found an input satisfying every precondition
whose model's result violates a postcondition (at 21, the model returns
-4249290049419214848)
```

`formal/examples/fact.mojo` is four lines:

```python
@spec(fact_spec; fact_spec 0 = 1; fact_spec (n+1) = (n+1) * fact_spec n)
@require(n >= 0)
@ensure(result >= 0)
def fact(n):
```

`21! = 51090942171709440000`, and `51090942171709440000 mod 2^64` is
`14197454024290336768`, which read as a signed 64-bit integer is
`14197454024290336768 - 18446744073709551616 = -4249290049419214848`.

The clause says `result >= 0`.  `result` is `fact(21)`.  It is negative.

## 2. Why it was never reported

**Because nothing read the decorator.**  `@require` / `@ensure` parsed —
`fire_compiler.py`'s `_parse_decorator_args` builds a `CallExpr` for a region
with no top-level `;`, which `test_examples_parse.py` pins — and then both
emitters ignored `FunctionDef.decorators` entirely
(`formal/model.py::unapplied_decorator_refusal` is only asked about a decorator
that is a `def` of the same unit, and `require`/`ensure` are not).

So a promise sat in the source of four of this repository's own corpus files,
unread, unrefuted and unprovable, for as long as it was there.  This is the
exact shape `lib/Contracts.lean`'s docstring lists as having happened four
times: *a `sorry` over a false statement is indistinguishable from one over a
true one*.  Here there was not even a `sorry` — there was nothing at all, which
is quieter.

## 3. What IS reported now, and what is not

`formal/build.py::_search_contracts` runs on **every** build and publishes its
verdicts in `result["contracts"]`, which `fire.py` prints:

```
contracts: 1 declared (NOT checked in the image; pass --check-contracts for
that, ...):
  contract fact: REFUTED at [21] — a bounded search found an input satisfying
  every precondition whose model's result violates a postcondition
```

A REFUTED verdict is a **build failure only under `--check-contracts`**, and
that division is deliberate.  Making it fatal by default would turn four corpus
builds red — and `test_formal.py`, `x86-examples` and the arm64/x86-64 proof
suites with them — for a bug that is in an EXAMPLE, and the fix belongs to
whoever owns the example rather than to a flag nobody set.

`fact.mojo`'s other three files, by measurement, are **not** refuted:

| file | contract | verdict |
|---|---|---|
| `fact.mojo` | `@ensure(result >= 0)` | **REFUTED** at `n = 21` |
| `count.mojo` | `@require(n >= 0)` | UNKNOWN — the search cannot run the recursion at `2^63` |
| `fib.mojo` | `@ensure(result >= 0)` | UNKNOWN, same reason |
| `sum.mojo` | `@ensure(result >= 0)` | UNKNOWN, same reason |

UNKNOWN there is **not** a pass: `classify` reports it with the number of
skipped inputs attached, and `Verdict.ok` is False for it.

## 4. The fix, and why it is not in this commit

Two changes are available and both belong to the owner of the example corpus.

**Change the clause.**  A true and still meaningful postcondition for `fact`
is `@ensures(n <= 1 → result == 1)` — the base cases, which is what a factorial
contract can honestly say over `UInt64` arithmetic, since `fact(70)` is `0` mod
`2^64` (`v_2(70!) = 67 ≥ 64`) and so `@ensures(result != 0)` is false too.
Whether the ladder discharges it is a measurement, not a guess: see
`bugs/FORMAL_contract_ladder_reach.md`, which is the other half.

**Or delete the clause.**  The `@spec(...)` above it is the recursion
specification and is unaffected; the `@require(n >= 0)` is harmless (it is
trivially true on the unsigned reading and is what makes `n == 0` the base
case).

Either way the change is to `formal/examples/fact.mojo`, whose generated proof
`test_formal.py` and `x86-examples` both consume, so it needs a gate run rather
than a worker's `--lean` invocation.  That is the integrator's, not this
branch's.

## 5. The next step, precisely

1. Decide whether `fact` should promise something or nothing.
2. Change `formal/examples/fact.mojo` accordingly.
3. Run `python3 test_formal_contracts.py --lean` — `test_the_corpus_facts_own_
   contract_is_false` will need its expected status updated in the same commit,
   because it asserts the CURRENT measured truth and that is the whole point of
   it.
4. Run `make check-formal` and `make check-x86-examples`.