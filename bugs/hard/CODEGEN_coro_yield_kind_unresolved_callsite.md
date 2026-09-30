# HARD BUG: an untypable generator call site silently poisons the yield slot back to `int64_t`

**State: the headline FIXED 2026-09-27; item 8 reclassified (still open, on
different grounds); the "test hole" section still open.** Found 2026-09-26 by
re-testing the claims in the now-removed
`CODEGEN_coro_stackswitch_yield_kind_identifier_inference.md`. That doc is
right that the headline miscompile is gone and that the non-unanimous case is
now an honest refusal. But its gate fired only on **provable disagreement**
between call sites. A single call site the static scan cannot type was neither
resolved nor recorded as a conflict — it emptied the slot, and the yield slot
fell back to `_KIND_TO_SLOT_CTYPE[None] == 'int64_t'`, which is the exact
silent truncation the doc set out to remove. Worse, one untypable call site
**discarded otherwise-unanimous literal evidence**, so a program with a clean
`g(3.5)` call site still miscompiled.

## Status

**The docstring's parenthetical is implemented, and all eight cases were
re-measured with CPython alongside.** Cases 1-7 are now *correct output*, not
merely refusals — a better answer than this doc predicted, for the reason in
"Why these became correct rather than merely refused" below.

| # | program | CPython | before | after |
|---|---|---|---|---|
| 1 | `def g(x): yield x`, called `g(3.5)` **and** `g(9.5)` from a sibling `def caller(v)` that does `g(v)` | `3.5` `9.5` | `3` `9` | correct: `3.5` `9.5` |
| 2 | same, `caller(3.5)` only | `3.5` | `3` | correct: `3.5` |
| 3 | same, `caller("hi")` only | `hi` | `4367111544` | correct: `hi` |
| 4 | `def compute(): return 3.5`; `var v = compute(); for s in g(v)` | `3.5` | `3` | correct: `3.5` |
| 5 | `def g(x): yield x * 2` via `caller(2.5)` | `5.0` | `4` | correct: `5.0` |
| 6 | struct method `def vals(self, x): yield x` called `vals(3.5)` | `3.5` | `3` | correct: `3.5` |
| 7 | `def g(x): yield x` called `g(self.k)` from a method, `k: Float64` | `3.5` | `3` | correct: `3.5` |
| 8 | `def rows(data): for r in data: yield r`, called `rows([1.5, 2.5])` | `1.5` `2.5` | two 19-digit IEEE-754 bit patterns | an honest GCC compile error, not a wrong answer — reclassified, see below |

Case 6 was recorded here as printing `3.5` `3.5` (two values); the program as
written has a single call site and prints one. The type outcome is the one the
doc claims.

### The fix itself

`_scan_callsite_param_kinds` now refuses a hole the way it already refused a
disagreement, implementing the parenthetical the registry's own docstring
specified. A hole is a hole because the stack-switch ABI fixes one C type per
generator: there is no sound way to keep going, and not even "the majority
kind", because the untypable argument is exactly the one carrying the other
type.

**Doing only that cost 8 green tests**, which is why this section is longer
than "one line". The strict rule is correct and untenable at the same time, so
the landed fix is the rule *plus* a widened scan: every hole with sound
evidence behind it is now closed, and what remains is refused. Closed, each
with the reason it was closeable:

1. **A parameter with ANY annotation is not a hole.** The scan used
   `_ann_kind(pann) is not None` to mean "typed", but `_ann_kind` returns None
   both for "no annotation" and for "annotated with a non-scalar". A
   `tk: Ticker` parameter yielded as a struct POINTER is *typed*, just not with
   a scalar — the struct-pointer yield machinery types its slot. Recording a
   hole there, and refusing, took `def gen(tk: Ticker): yield tk` out of the
   compiled path over a type we actually know. This is also literally the
   registry's documented scope ("unannotated param names"). *(2 tests)*
2. **A bare identifier the caller's env already types as a list answers
   `('list', k)`.** `_yield_kind`'s identifier arm deliberately answers None
   for a container, which is right for a *yield* and wrong for a *parameter*:
   a parameter's consumer is `for r in data:` / `d[0]`, and both read the
   `('list', k)` entry. The same answer already worked for a list *literal*
   argument, which is how item 8's `rows([1.5, 2.5])` stopped being a hole at
   all. *(1 test)*
3. **`_argkind`'s `if caller_env:` gate was truthiness where membership was
   meant.** An empty caller env is still a caller env, so `_argkind(x, {})`
   disagreed with `_argkind(x, {'anything': 'i'})` for the same `x`: a
   `n - step` argument read as an int in a function that happened to have one
   typed local, and as a hole in one that did not. Once a hole is a refusal,
   that inconsistency became the difference between compiling and refusing.
   *(2 tests)*
4. **The same whole-module scan now covers ordinary `def`s**
   (`_PLAIN_CALLSITE_PARAM_KINDS`). A conflict is a refusal for a generator
   and a non-answer for an ordinary function, so only the generator half
   records one; but the ordinary half types the ENCLOSING function's
   parameters, which is what a synthesized generator-expression body is called
   with — `(x * k for x in xs)` in `def scaled(k)` lowers to `__genexp_0(k)`.
   **This is what closed cases 1, 2, 3 and 4 outright instead of refusing
   them**: the `g(v)` hole *is* `caller`'s own parameter, and `caller(9.5)`
   types it. The scan runs two passes for this, and the second has to be able
   to READ the first one's results — getting that wrong (clearing the
   registries at the top of each pass) is what it did at first, and the
   symptom is a conflict that never goes away. *(1 test)*
5. **A call argument that is itself a call** now consults the same-module
   return kind, via one shared `_callee_return_kind` used by all three places
   that answer that question (a yielded expression, a call-site argument, and a
   local's initializer — three answers that had drifted, the initializer path
   knowing neither, which is why case 4 was a hole at all). The return kind
   comes from the annotation, or, for an unannotated `def`, from
   `_literal_return_kind`: unanimous scalar-literal `return`s read as a
   declaration, and nothing at all when the body does not repeat itself.
   *(1 test)*
6. **`bytes` / `bytearray` / `memoryview` locals are `('list', 'i')`** — a fact
   about the type, not an inference about a value, so it is safe where an
   inference would not be. *(1 test)*

### Why these became correct rather than merely refused

Worth recording, because this doc predicted refusals and the trade it warned
about (cpp going "from correct to refused" on case 1) did not happen. The
reason is item 4: the doc's cases 1-3 all route the untypable argument through
an ordinary function's unannotated parameter, and that parameter is *itself*
determined by that function's call sites. The evidence was always there; it
was just not being read, and the doc read the absence of a read as the absence
of evidence.

### Item 8 — OPEN, but not this bug

`rows([1.5, 2.5])` no longer prints the floats' raw IEEE-754 bit patterns; it
now fails to compile:

    b2h.mojo:3:3: error: pointer value used where a floating-point was expected

That is the intended direction (an honest failure, not silently wrong output)
but it is **not a fix**, and this doc's attribution of item 8 to the yield-kind
machinery is wrong. The identical wrong output appears with **no generator
involved at all**:

    def show(data):
        for r in data:
            print(r)

    def main():
        show([1.5, 2.5])

CPython `1.5` `2.5`; compiled, both before and after this pass,
`4609434218613702656` `4612811918334230528`. So item 8 is the ordinary
codegen's "a for-loop over a list PARAMETER does not know the element type"
gap: the yield slot is now correctly `double` while the loop target `r` is
`char *`, hence the cast error. Closing it means typing list-element loop
targets in the ordinary loop lowering from a cross-call element-type contract
— a different subsystem, and one CLAUDE.md puts behind a full `make gate` of
its own. Not attempted here. A plain list *literal* loop is fine
(`for r in [1.5, 2.5]: print(r)` prints `1.5` `2.5`), which is what makes this
specifically a list-PARAMETER problem.

### Stdlib breadth, now measured rather than argued

`compile_stdlib.py` reports `PASSED: 664` / `FAILED: 0 (0 expected, 0
unexpected)` with `GCC CAS: 664/664 hits (100%)` — byte-identical generated C
across the whole tree — and `build_stdlib_dylib.py` still builds from the same
**291** modules with **zero** `skip` lines, before and after. The widened scan
and the hole-is-a-conflict rule between them changed not one byte of generated
stdlib C, and no stdlib module fell back to source.


## Symptom (as recorded 2026-09-26; all eight resolved or reclassified in Status)

All of these compiled, ran, exit 0, and printed a plausible wrong value. No
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

## Root cause (as diagnosed 2026-09-26; fixed as described in Status)

`mojo/middle/coro.py`, inside `_scan_callsite_param_kinds` (pre-fix line 2094):

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

**The registry's own docstring already specified the fix.**
`_CALLSITE_PARAM_CONFLICTS` describes itself as holding "set of
unannotated param names whose call-site arguments DISAGREE **(or include one
the static scan could not type at all)**". The parenthetical was not
implemented. It also stated the rationale for refusing — "the default would
silently truncate a float to int64_t or print a `char *` as its address" —
which is exactly what happened instead. This was a code/comment
contradiction, not a design gap: routing the emptied set into `conflicted`
closed items 1-6 without touching the feature-sized tagged-ABI work, and
turned out to close them *correctly* rather than by refusing (see Status).

Two narrower contributing causes, each independently worth a line, and **both
now fixed**:

- **`self.<field>` was never resolvable at a call site.**
  `_scan_callsite_param_kinds` built the caller's env as `cenv =
  _static_env(fn)` with **no `struct_def`**, while `_static_env` only populates
  its `self.<field>` keys under `if struct_def is not None`. So `g(self.k)`
  inside any method was untypable even when `k` carries a class-body
  `Float64` annotation. Case 7. (Yield *sites* did get `struct_def` threaded
  down, which is why the removed doc's `yield self.base + i` repro genuinely
  worked.) The scan now passes the same env the yield sites already get, so
  the two agree about `self.k`.
- **A list passed as a parameter was never a `('list', elem)` env entry.**
  This doc blamed the absence of a list *annotation* shape in `_ann_kind`,
  which is **not** what was happening, and the correction matters because the
  two imply different fixes. `_argkind` DID compute `('list', 'd')` for the
  `rows([1.5, 2.5])` argument and then **threw it away** at an
  `isinstance(k, str)` filter sitting between the computation and the
  return; `_yield_kind` could not recover it, because a whole list has no
  scalar slot kind, so the argument recorded as a hole. The filter is gone,
  and the same answer now also comes from a bare *identifier* argument, which
  is the shape that made `def g(d): yield d[0]` called `g(xs)` a hole too.

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
   output, so the 664/664 number was not evidence that this residue was
   absent. **The number itself was always right, though, and is now measured
   rather than argued**: see the stdlib paragraph in Status.
4. **The `MOJO_CORO=cpp` claim, which the doc both makes and retracts.** The
   2026-09-06 section still says "`MOJO_CORO=cpp` remains the escape hatch for
   the non-unanimous residual", the 2026-09-05 section says "`MOJO_CORO=cpp`
   remains a correct escape hatch for this shape", and the Impact section says
   it "remains a fully correct escape hatch" — all three contradicted by the
   same doc's own Correction 2, and all three stale for a second,
   independent reason: re-tested, cpp is **correct** on case 1
   (`MOJO_CORO=cpp` on item 1 prints `3.5` / `9.5`, because it really does model
   the per-yield value independently) and **still wrong** on case 3
   (`4362836760`). So cpp is not an escape hatch for this residue either —
   it is a different, partial answer, which is worse than either extreme.
   **And the trade this section warned about did not happen**: because the
   fix closed cases 1-3 *correctly* rather than by refusing, cpp now prints
   `3.5` for case 1 as A3 does, and the two backends agree on all of 1-7.

## A test hole found on the way — still open, re-measured

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
    compiled:  1 / 3.5 / 4340962992 / 1.5      (re-measured 2026-09-27)

That `print(x)` half is the cross-cutting one-C-type-per-slot limitation the
doc's Correction 1 already names (an ordinary `def g(x): return x` does the
same), so it is **not** counted as a separate bug here, and there is no
correct assertion to write for it yet — which is why this pass left both the
hole and the shape alone. It is recorded because the test that would have
caught it does not test it, and because `_argkind`'s evidence for `x` is
genuinely conflicting and genuinely ignored.

## Where

Line numbers are pre-fix; the shapes they named are now as follows.

- `mojo/middle/coro.py` — `_scan_callsite_param_kinds` (the hole rule and the
  two-pass driver), `_argkind` (the `('list', k)` answers and the
  `caller_env is not None` gate), `_CALLSITE_PARAM_CONFLICTS` /
  `_CALLSITE_PARAM_KINDS` / `_PLAIN_CALLSITE_PARAM_KINDS` (the registries and
  their docstrings), `_ambiguous_slot_message` (the one diagnostic both
  backends build, so they cannot drift), `_KIND_TO_SLOT_CTYPE[None]` (the
  default this no longer reaches), `_static_env` (the `self.<field>` seeding,
  the `bytes`/`bytearray`/`memoryview` entry, the plain-registry seed),
  `_callee_return_kind` / `_scan_func_ret_kinds` / `_literal_return_kind` (the
  return-kind reach), and the registry docstring that specified this fix
  before it was implemented.
- `mojo/backend_gimple/cpp_async.py` — its copy of the shared ambiguity gate,
  which now builds the message from the same helper. A fix in
  `_scan_callsite_param_kinds` closes both backends at once; the trade this
  section predicted for cpp did not materialise, see Contradictions item 4.
- `test_gimple.py` — the `conflicting_callsite_gate_is_narrow` hole (still
  open), and the refusal-message expectation in
  `conflicting_callsite_yield_kind_refused_not_miscompiled`, which was
  **changed**: the message used to say "call sites pass conflicting types",
  which described only the disagreement half and so misdescribed every case
  this doc is about. It is now one shared string naming both causes, and that
  test is where the new wording is pinned.
- `test_gimple_generator_runner.py` — the regression cases added for this
  pass: `generator_callsite_through_unannotated_caller_param`,
  `generator_callsite_string_through_caller_param`,
  `generator_callsite_self_field_kind`,
  `generator_callsite_untypable_argument_refused` (the one shape with no
  reachable evidence, which must stay refused), plus the two nested-async
  capture cases that came with the sibling fix.
