# HARD BUG: an untypable generator call site silently poisons the yield slot back to `int64_t`

**State: OPEN.** Found 2026-09-26 by re-testing the claims in the now-removed
`CODEGEN_coro_stackswitch_yield_kind_identifier_inference.md`. That doc is
right that the headline miscompile is gone and that the non-unanimous case is
now an honest refusal. But its gate fires only on **provable disagreement**
between call sites. A single call site the static scan cannot type is neither
resolved nor recorded as a conflict — it empties the slot, and the yield slot
falls back to `_KIND_TO_SLOT_CTYPE[None] == 'int64_t'`, which is the exact
silent truncation the doc set out to remove. Worse, one untypable call site
**discards otherwise-unanimous literal evidence**, so a program with a clean
`g(3.5)` call site still miscompiles.

## Symptom

All of these compile, run, exit 0, and print a plausible wrong value. No
diagnostic. Verified against CPython (via `/tmp/coro_verify/ref.py`, which
`exec`s the Mojo source as Python — every shape here is valid Python).

| # | program | CPython | compiled |
|---|---|---|---|
| 1 | `def g(x): yield x`, called `g(3.5)` **and** `g(9.5)` from a sibling `def caller(v)` that does `g(v)` with `v` unannotated | `3.5` / `9.5` | **`3` / `9`** |
| 2 | same, `caller(3.5)` only | `3.5` | **`3`** |
| 3 | same, `caller("hi")` only | `hi` | **`4367111544`** (raw `char *` as a decimal) |
| 4 | `def compute(): return 3.5`; `var v = compute(); for s in g(v)` | `3.5` | **`3`** |
| 5 | `def g(x): yield x * 2` via `caller(2.5)` | `5.0` | **`4`** |
| 6 | struct method `def vals(self, x): yield x` via `caller(3.5)` | `3.5` `3.5` | **`3` `3`** |
| 7 | `def g(x): yield x` called `g(self.k)` from a method, `k: Float64` as a class-body field annotation | `3.5` | **`3`** |
| 8 | `def rows(data): for r in data: yield r`, called `rows([1.5, 2.5])` | `1.5` `2.5` | **`4609434218613702656` / `4612811918334230528`** — the floats' raw IEEE-754 bits |

Case 1 is the sharpest: the module contains a textbook-resolvable call site
`g(3.5)`. On its own that resolves the slot to `double` and prints `3.5`. Add
one more caller whose argument is a bare identifier, and **both** call sites
start printing truncated integers. Case 8 is the worst output: a list of floats
round-tripped through a generator prints two 19-digit integers.

## Root cause

`mojo/middle/coro.py:2094`, inside `_scan_callsite_param_kinds`:

```python
kinds = {k for k in kinds if k is not None} if None not in kinds else set()
```

`_argkind` returns `None` for any argument the syntactic scan cannot type. The
intent is clearly "a `None` poisons the slot" — but the effect is that the
slot's kind set becomes **empty**. An empty set then falls through both
branches: it is not `len(kinds) == 1` so it is not resolved
(`mojo/middle/coro.py:2098`), and it is not `len(kinds) > 1` so it is not
recorded in `_CALLSITE_PARAM_CONFLICTS` (`mojo/middle/coro.py:2100`). With no
resolution and no conflict, the generator's yield slot defaults through
`_KIND_TO_SLOT_CTYPE[None] == 'int64_t'` (`mojo/middle/coro.py:365`) and
`_static_env` cannot type the yield either — so `_yield_kind` returns `None`
and the float is truncated / the `char *` is printed as an address.

**The registry's own docstring already specifies the fix.**
`mojo/middle/coro.py:776-779` describes `_CALLSITE_PARAM_CONFLICTS` as "set of
unannotated param names whose call-site arguments DISAGREE **(or include one
the static scan could not type at all)**". The parenthetical is not
implemented. `:778-779` also states the rationale for refusing — "the default
would silently truncate a float to int64_t or print a `char *` as its address"
— which is exactly what happens instead. This is a code/comment
contradiction, not a design gap: routing the emptied set into `conflicted` (or
treating "no kind evidence at all" as its own conflict class) closes items
1-6 and 8 without touching the feature-sized tagged-ABI work.

Two narrower contributing causes, each independently worth a line:

- **`self.<field>` is never resolvable at a call site.** `mojo/middle/coro.py:2080`
  builds the caller's env as `cenv = _static_env(fn)` with **no `struct_def`**,
  while `_static_env` only populates its `self.<field>` keys under
  `if struct_def is not None` (`mojo/middle/coro.py:273`). So
  `g(self.k)` inside any method is untypable even when `k` carries a
  class-body `Float64` annotation. Case 7. (Yield *sites* do get `struct_def`
  threaded down, which is why the removed doc's `yield self.base + i` repro
  genuinely works.)
- **A list passed as a parameter is never a `('list', elem)` env entry.**
  `_static_env` builds those tuples only for locals it saw assigned or
  `.append`ed to (`mojo/middle/coro.py:249-250`); a `('list', kind)` param
  annotation is not one of the shapes `_ann_kind` produces. So
  `for r in data: yield r` (case 8) can bind `r` from neither the iterable
  nor a list local.

## Contradictions with the removed doc's own recorded claims

1. **The banner.** "the non-unanimous residual is an HONEST REFUSAL on both
   backends rather than a truncated float / printed pointer." True for
   provable disagreement. In the ordinary sense "non-unanimous" also covers
   "unanimous over the *resolvable* call sites only" — the case in item 1 —
   which still truncates.
2. **`_argkind`'s documented reach.** The doc describes call-site evidence as
   resolving "identifier / `self.<field>` refs via the caller's own
   `_static_env`". The `self.<field>` half does not work (`:2080`), and
   `_yield_kind`'s own docstring repeats the claim.
3. **The breadth check.** "`python3 compile_stdlib.py` 664/664 … the new
   refusal fires on no stdlib generator (as expected; the ambiguity needs a
   yielded *unannotated* param with disagreeing call sites, and where that
   occurred the old behavior was already wrong output)." That reasoning only
   covers the `len(kinds) > 1` branch. Case 8 needs no disagreement at all —
   one call site, one unannotated param, and the old behaviour is still wrong
   output. The 664/664 number is not evidence that this residue is absent.
4. **The `MOJO_CORO=cpp` claim, which the doc both makes and retracts.** The
   2026-09-06 section still says "`MOJO_CORO=cpp` remains the escape hatch for
   the non-unanimous residual", the 2026-09-05 section says "`MOJO_CORO=cpp`
   remains a correct escape hatch for this shape", and the Impact section says
   it "remains a fully correct escape hatch" — all three contradicted by the
   same doc's own Correction 2, and all three now stale for a second,
   independent reason: re-tested, cpp is **correct** on case 1
   (`MOJO_CORO=cpp` on item 1 prints `3.5` / `9.5`, because it really does model
   the per-yield value independently) and **still wrong** on case 3
   (`4362836760`). So cpp is not an escape hatch for this residue either —
   it is a different, partial answer, which is worse than either extreme.

## A test hole found on the way

`test_gimple.py`'s `conflicting_callsite_gate_is_narrow` asserts the refusal
is narrow, and its part (a) — the "conflicting param that is NOT yielded still
compiles" direction — does not create a conflict at all:

```python
def g(x):
    var t = 0
    for i in range(x):
        t = t + i
    yield t
...
    for v in g(3):   # 'i'
    for v in g(5):   # 'i'  -- unanimous, not conflicting
```

Two ints, so the `len(kinds) > 1` branch never fires and the "narrow"
behaviour is untested. The shape it means to cover does compile — and prints a
raw pointer for the string call site:

    def g(x, y):
        print(x)          # conflicting, NOT yielded -> not refused
        yield y
    for v in g(1, 3.5): print(v)
    for v in g("s", 1.5): print(v)

    CPython:   1 / 3.5 / s   / 1.5
    compiled:  1 / 3.5 / 4330444464 / 1.5

That `print(x)` half is the cross-cutting one-C-type-per-slot limitation the
doc's Correction 1 already names (an ordinary `def g(x): return x` does the
same), so it is **not** counted as a separate bug here. It is recorded because
the test that would have caught it does not test it, and because
`_argkind`'s evidence for `x` is genuinely conflicting and genuinely ignored.

## Where

`mojo/middle/coro.py` — `:2094` (the poisoning line, the whole bug),
`:2098`/`:2100` (resolve-vs-conflict branch), `:365` (the `None -> int64_t`
default), `:2080` + `:273` (`self.<field>` unreachable at a call site),
`:776-784` (the docstring that already specifies the fix),
`_argkind` / `_yield_kind` / `_static_env` for the reach gaps.

`mojo/backend_gimple/cpp_async.py:414-426` consults the same
`_ambiguous_yielded_params`, so a fix in `_scan_callsite_param_kinds` closes
both backends at once — but see item 4 above for the fact that cpp currently
behaves *better* than A3 on case 1, so that fix will change cpp's output from
correct to refused. That is the intended trade (honest refusal over silent
truncation is the doc's own stated policy) but it should be a conscious one.

`test_gimple.py:5803-5844` — the `conflicting_callsite_gate_is_narrow` hole.
