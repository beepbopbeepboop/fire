# FORMAL_functools_is_unbuildable_as_a_host_module: every name in CPython's `functools` needs a capability this path lacks, and a module that exports nothing is refused

**Area:** FORMAL (host modules / module classification). **Status: the census
below is STALE, and the staleness is the finding — step 1 of "The exact next
step" has LANDED.** Found on `construct:sweep5:hostmods-core` (2026-10-02), whose
brief was to add `functools` to `formal/hostmods/` alongside `collections`,
`enum` and `contextlib`. `enum` and `contextlib` landed; this is the other two.

**Status 2026-10-05 (`work/formal23-4`): `reduce` is WRITABLE and the module is
blocked by ONE thing that is not a `functools` capability at all — the module was
WRITTEN, measured on both architectures, and not landed, and the reason is
`bugs/FORMAL_a_dropped_decorator_never_resolves_the_name_it_spells.md`.** Read
this before §"The exact next step", which is now two steps out of date.

    $ printf 'import functools\n\ndef add2(a, b):\n    return a + b\n\ndef main() -> int:\n    printf("r=%d\\n", functools.reduce(add2, [1, 2, 3, 4], 0))\n    return 0\n' > .tmp/ft/fmod.mojo

With a `formal/hostmods/functools.mojo` exporting `reduce` and `functools`
removed from `formal/imports.py`'s host-module set:

| shape | this tree | CPython |
|---|---|---|
| `reduce(add2, [1,2,3,4], 0)` | `r=10` arm64, `r=10` x86-64 | 10 |
| `reduce(mul2, [1,2,3,4], 1)` (non-commutative) | `m=24` arm64, `m=24` x86-64 | 24 |
| `reduce(add2, [7], 100)` (one element) | `o=107` | 107 |
| `reduce(add2, [], 5)` (empty) | `e=5` | 5 |
| `reduce(add2, [1,2,3,4])` (CPython's 2-arg form) | refused: `missing required argument 'initial'` | 10 |
| `@functools.lru_cache(maxsize=1)` on a function | **BUILDS, exit 0, prints 89** | memoised |

So every capability §"The exact next step" lists as missing is now present —
a first-class CALLABLE (step 1, 2026-10-04) and `len()` of a list PARAMETER
(this tree, `model.parameter_kinds_by_call_site`) — and one refusal has MOVED
rather than gone: CPython's two-argument `reduce` cannot be a defaulted
`initial`, because a default is not materialised across a dylib boundary
(`FORMAL_default_argument_not_applied_across_a_dylib`) and a probe module with
`initial = 0` answers **0** to `reduce(mul2, [1,2,3,4])` where CPython answers
24. A required `initial` turns that into a refusal, which is the safe direction.

**What stops the module, then, is the last row, and it is a different bug from
anything in this document.** A decorator on this path is parsed and dropped, so
the module's ABSENCE is the only thing refusing `@functools.lru_cache`; publish
a `functools` and that program builds and runs and does not memoise. The bare
attribute read `functools.lru_cache` refuses correctly and well (naming the
module, the missing name and what the module publishes), so the refusal
machinery is there — it is only the DECORATOR spelling that never asks. That is
`bugs/FORMAL_a_dropped_decorator_never_resolves_the_name_it_spells.md`, and its
§"The exact next step" also carries the row that constrains the fix
(`test_dataclasses_formal.py`'s `@dataclasses.dataclass` passes for the SAME
reason and must keep passing).

**What this session did NOT do, deliberately:** land the module. Writing one
whose 19 absent names are honestly refused and whose 1 present name is checked
against CPython is a day's transcription, and it would have turned a green
`functools-absent` group red — a REGRESSION, because the group's own comment
says the decorator spelling is the one program that would build and skip the
work it asked for. A missing capability that refuses is better than a present
one that lies, and this is the case where that ordering is the whole decision.

**Status 2026-10-04 (`work/formal29-3`): step 1 is DONE — a first-class function
value is a CODE ADDRESS on this path — so §"What I saw" §2's headline measurement
is inverted, and the blocker `reduce` hits is a different one entirely.** Read this
before §2 and before the absence group in `test_formal_core_hostmods.py`, whose
docstring repeats the same inverted sentence.

    formal/build.py:13586 — "A function value is a CODE ADDRESS on this path now,
    materialized by each backend's `_load_var` and branched through by its
    `_emit_call`, so the name HAS a home and the pre-pass has no question left
    to ask."

Measured on this tree today, **both architectures**, every shape §2 says is
refused:

| program | §2 measured | measured now |
|---|---|---|
| `var g = dbl; return g(5)` | refused by `model.function_value_refusal` ("a function is a code address and a value here is one 64-bit word, so there is nothing for that word to hold") | **exit 10** — CPython 10 |
| `call2(dbl, 5)`, both functions in the caller's file | "refused outright … so it is not a dylib-boundary problem" | **exit 10** — CPython 10 |
| `call2(neg, 5)` and `call2(dbl, 5)` through the same parameter | — | **-5 and 10**, CPython's, so the word carries a CALL SITE and not one fixed target |
| `f(a, b)` with **two** arguments through one parameter | — | works, which is what `reduce` needs |

**What that changes in the census.** The "needs a first-class CALLABLE as an
argument" row no longer blocks anything by itself. `reduce` is the one name in it
whose remaining requirement is small, and it is blocked by something else
entirely:

```
$ def fold(func, xs, initial): … while i < len(xs): acc = func(acc, xs[i]) …
build: len(xs) is len() of a value classified as 'int', and an integer has no
  length: …
```

A LIST PARAMETER, on both architectures, with `xs[i]` on the same parameter
answering correctly. Filed as its own document, and **that document is now
DELETED — the reader it names is fixed** (`parameter_kinds_by_call_site`
claims a counted blob from a parameter's CALL SITES, so `len(xs)` is the count
field where it already was for the subscript; measured on both architectures,
`reduce(add2, [1, 2, 3, 4], 0)` builds, runs and answers CPython's `10`).
One correction to the filed doc's table, which is why it is worth repeating
here: its ANNOTATED rows (`List[Int]`, `List[Cell]`) had already been answered
by `ValueKinds.kind_of`'s `declared_param_kind` fallback when it was filed, so
only the UNANNOTATED spelling was ever live. Both are pinned now, side by side,
in `test_formal_run.py`'s `both_arch_len_of_a_container_annotated_parameter`
(the guard) and `both_arch_len_of_an_unannotated_parameter_every_call_site_
passes_a_list` (the fix).

**So `reduce` is WRITABLE as of this commit**, measured end to end on both
architectatures, and what stands between it and a `formal/hostmods/functools.mojo`
is step 2 alone.

**What has NOT moved, and is the rest of this document.** Step 2 — DECORATOR
application — is unchanged and is `bugs/COMPILE_FAIL_decorator_application_dropped.md`'s
to own: a decorator is still parsed and never applied, so the eight names in the
DECORATOR row are still refused and must stay refused, and §"Why this is not
write it anyway" still holds for them. `get_cache_token()` still has no constant
answer. The TYPE-OR-OBJECT row (`GenericAlias`, `UnionType`, `itemgetter`,
`MappingProxyType`, `RLock`, `Placeholder`) is untouched by the callable landing
and still needs what it needs. And §4's point — that a module which exports
nothing is refused, so `functools.mojo` cannot be written even as a stub — is
STILL TRUE, which is why nothing here has landed as a module: a `functools` that
exported only `reduce` would be an honest partial one, but it would still be a
module named after a standard-library namespace whose most-used member
(`lru_cache`) it refuses, and the doc's own rule ("until step 2, no `functools`
name may be exported") is a judgement about that, not about the export gate.

**Update 2026-10-02: the safeguard this document's last line leans on now
exists.** It said "the test's `functools`-shaped absence group is what keeps that
true" — and `grep functools test_formal_core_hostmods.py` returned nothing, so
the promise was not kept and a `functools.mojo` could have landed exporting
`lru_cache` with every suite still green. `test_formal_core_hostmods.py` has the
group now: `functools-absent`, 20 names from this document's own census plus the
`@functools.lru_cache(maxsize=1)` spelling, each asserted to be refused AND to
name the module, because a refusal that does not name the module sends the
reader to fix the wrong file. The decorator case is separate on purpose: it is
the one program that would BUILD if the import stopped being what refuses it,
since a decorator on this path is parsed and never applied. Measured: 7/7
groups in that file pass.

**Update 2026-10-03: one of the two measurements under §"What I saw" was a
false diagnosis, and it is fixed — which matters because a false diagnosis is
what makes a missing capability look like a binding bug.** §2 measured "a
callable argument is refused outright … The message is the read-before-store one:
`f`/`dbl` is read as a VALUE and the register allocator gives the name a home
because the function assigns it somewhere, so the image cannot say 'unbound'."
The refusal was real; the sentence was not, in every clause. Both this emitter and
the allocation walk know `dbl` is not a local — which is why neither gave it one
— so they do not "disagree", and nothing was assigned anywhere. What is true is
that a first-class function has no representation on this path at all: a value is
one 64-bit word and a function is a code address, so there is nothing for that
word to hold.

`formal/model.py::function_value_refusal` now says that, and both backends raise
it (`_no_home` in each) when the unplaceable name is a function of this image.
Measured, both spellings and both architectures:

```
$ printf 'def dbl(x: Int) -> Int:\n    return x * 2\n\ndef main(n: Int) -> Int:\n    var g = dbl\n    return g(5)\n' > .tmp/fv.mojo
$ python3 fire.py build --formal --no-prove -o .tmp/fv .tmp/fv.mojo
build: main: 'dbl' is a FUNCTION, and a function is not a value on this path: … a value is one 64-bit word
       and a function is a code address, so there is nothing for that word to hold …
$ python3 fire.py build --formal --backend=x86_64 --no-prove -o .tmp/fv .tmp/fv.mojo
build: main: 'dbl' is a FUNCTION, and a function is not a value on this path: …
```

Pinned by `test_formal_run.py`'s `REFUSAL_CASES`:
`a_function_name_read_as_a_value_is_named_as_one` and
`a_function_name_passed_as_an_argument_is_named_as_one` — two spellings because
they reach the read differently, and the second is the one a
`functools.reduce(add2, [1,2,3], 0)` would be.

**This does not make `functools` writable and is not a step towards it**: the
construct is still refused, and refused for the right reason now. What it removes
is the last message in this family that sent a reader to look at the register
allocator.

**What is still exactly as below, and is the whole of the remaining work:**
nothing here is module-shaped. Step 1 (a first-class function value) is a
lowering in both backends plus a representation rule, and the representation
question belongs with the owner of the value model rather than with a module
author — `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`
and `formal/model.py`'s copy-construction refusal both name the same missing
capability, and whichever lands first unblocks this. Step 2 (decorator
application) must land before any decorator is exported, and it is
`bugs/COMPILE_FAIL_decorator_application_dropped.md`'s to own.

## What I ran

With a stub `formal/hostmods/functools.mojo` on the search root, arm64, plus a
census of CPython 3.14.7's `functools` by what each public name actually needs:

```console
$ python3 fire.py build --formal --no-prove -o /tmp/x version.py
build: version.py imports 'subprocess', which is a host module (CPython standard
library), which has no Mojo source for this backend to compile

$ python3 fire.py build --formal --no-prove -o /tmp/y t.py     # stub in place
build: t.py imports 'functools', which cannot be built either: functools.mojo:
formal dylib has no public functions: functools.mojo exports nothing under
doc/ABI.md's rules: every declaration in it is private (_p), and a private name
is excluded from the boundary on purpose …
```

## What I saw

**1. `functools` converts ZERO files, and the one file that wants it is permanent.**
`version.py` is the only sweep row for `functools`, and with the module stubbed
in it moves to `subprocess` — `HOST_UNREACHABLE`, a second process, permanent by
the rule at the top of `formal/imports.py`. So the module's ceiling is a
diagnostic that changes subject, not a build.

**2. Every public name needs one of three capabilities this path lacks.** CPython
3.14.7's `functools`, classified:

| needs | names |
|---|---|
| a first-class CALLABLE as an argument | `cache`, `cmp_to_key`, `partial`, `partialmethod`, `singledispatch`, `singledispatchmethod`, `update_wrapper`, `wraps`, `cached_property`, `MethodType`, `reduce` |
| DECORATOR semantics | `cache`, `lru_cache`, `total_ordering`, `singledispatch`, `update_wrapper`, `wraps`, `cached_property`, `partialmethod`, `recursive_repr` |
| a TYPE or an OBJECT with state | `GenericAlias`, `UnionType`, `itemgetter`, `cached_property`, `MethodType`, `MappingProxyType`, `RLock`, `partial`, `Placeholder` |
| DATA that is not one word | `WRAPPER_ASSIGNMENTS`, `WRAPPER_UPDATES` (tuples of strings — a tuple is a frame blob) |

Two of those are refusals with a name each, and both were measured rather than
assumed:

* **A callable argument is refused outright.** `functools.reduce(add2, [1,2,3], 0)`
  does not lower, and neither does the same shape with BOTH functions in the
  caller's own file (`def call2(f, a): return f(a)` called as `call2(dbl, 5)`),
  so it is not a dylib-boundary problem. **The message this bullet used to
  quote was a false diagnosis and has been replaced** — see the 2026-10-03 note
  at the top: it is now `model.function_value_refusal`, which says a function is
  a code address and a value here is one 64-bit word. With the name coming from
  an imported module the failure is still blunter, and still a different one:
  `the library would bind 1 symbol(s) that nothing provides: f`.
* **A decorator is silently DROPPED.** `@tag` on a function and `@unique` on a
  class both build, and neither the decorator body nor anything it was supposed
  to enforce ever runs (measured with a `printf` inside the decorator: no
  output). `bugs/COMPILE_FAIL_decorator_application_dropped.md` owns the
  general finding. So exporting `lru_cache` would make `@functools.lru_cache(maxsize=1)`
  build and cache nothing — which for `version()` happens to be answer-preserving
  and for anything else is a program that runs and skips the work it asked for.

**3. `get_cache_token()` is the one name left, and it has no correct constant
answer.** It returns `18` on this CPython — `len()` of the private `_caches`
list. Its entire purpose is to CHANGE when a registration is added. There is no
cache registry on this path to derive it from, so any fixed number is a
fabricated token rather than a mirror.

**4. And a module that cannot export any of them does not build.** `doc/ABI.md`'s
export rule refuses a dylib with no public functions (measured, message above),
so `functools.mojo` cannot be written even as a stub: there is no content that is
both honest and exportable.

## Why this is not "write it anyway"

A `functools.mojo` exporting `lru_cache`, `wraps` and `reduce` would build, and
`version.py` would then build too — with a dropped decorator and a refused
callable, i.e. two of the three ways this tree produces a plausible program that
is not the one the source says. `FORMAL_hashlib_sha3_and_blake2s_absent`
filed a decision of exactly this shape rather than shipping one, and the same
argument applies here.

This is also the shape the (now deleted) `glob`/`copy`/`collections`/`io`
measurement record warned about for `glob` and then withdrew its own advice
about: a module that does not export the name a caller wants converts "out of
reach, with an owner" into an export-map refusal, which dresses a fact about
the target as a gap in the backend.

## The exact next step

**SUPERSEDED by the Status at the top — read that first.** What is below is the
plan as written on 2026-10-02 and it is wrong about two of its three steps.
Step 1 LANDED on 2026-10-04 (a function value is a code address) and the
`len()`-of-a-list-parameter step it did not know about landed on 2026-10-05, so
the list below is one step long and its order is stale. What survives, and is
now the whole of the remaining work, is step 2 — with the addition the 2026-10-05
Status measured: step 2 alone is not enough, because "a decorator is parsed and
never applied" is only safe while every decorator a caller can spell is ALREADY a
refusal. The next step is therefore
`bugs/FORMAL_a_dropped_decorator_never_resolves_the_name_it_spells.md`'s, whose
§"The exact next step" carries the check and the pinned row that constrains it.

Not a module. The root capability is **a first-class function value**, and it is
the same one `collections` needs for a different reason and that
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` §2 already
touches ("a shallow field-wise clone of a compile-time-known struct … is the
same feature `formal/model.py`'s copy-construction refusal already names").
Whichever of those lands first unblocks this; the module is then a transcription
and not a design.

Order of work, if it is picked up:

1. ~~A function value as a parameter and as a return — a lowering in both
   backends plus a representation rule, since a callee and a caller must agree
   on what a function IS (a code address; `formal/model.py`'s
   `pointer_value_model` already says what a word can and cannot denote).~~
   **DONE, 2026-10-04.** See the 2026-10-04 Status at the top.
2. Decorator application — separately, and before any decorator is exported by a
   hostmod. The two are related (a decorator IS a function value) but a
   half-working version of this that unblocks `reduce` and leaves `@wraps`
   silently dropped is worse than neither. **AND, measured 2026-10-05: a
   decorator whose name does not resolve must be REFUSED rather than ignored, or
   publishing any `functools` name turns `@functools.lru_cache` into a program
   that runs and skips the memoisation it asked for** — that is
   `bugs/FORMAL_a_dropped_decorator_never_resolves_the_name_it_spells.md`, and it
   is the actual gate on step 3.
3. `functools` then follows, and `test_formal_core_hostmods.py` grows a group
   for it the way `enum` and `contextlib` grew theirs — with `reduce` removed
   from its `absent` list and a `functools` group beside `ctx` that compares
   `reduce` against CPython's own over the four shapes the 2026-10-05 Status
   measured, including the empty sequence and the one-element one.

Until step 2, no `functools` name may be exported, and the test's
`functools`-shaped absence group is what keeps that true.
