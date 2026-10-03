# FORMAL_functools_is_unbuildable_as_a_host_module: every name in CPython's `functools` needs a capability this path lacks, and a module that exports nothing is refused

**Area:** FORMAL (host modules / module classification). **Status: OPEN, measured,
not started — and the measurement is the whole finding.** Found on
`construct:sweep5:hostmods-core` (2026-10-02), whose brief was to add
`functools` to `formal/hostmods/` alongside `collections`, `enum` and
`contextlib`. `enum` and `contextlib` landed; this is the other two.

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

**What is still exactly as below, and is the whole of the remaining work:**
nothing here is module-shaped. Step 1 (a first-class function value) is a
lowering in both backends plus a representation rule, and the representation
question belongs with the owner of the value model rather than with a module
author — `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`
and §4c of `FORMAL_frame_receiver_handoff.md` both name the same missing
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
  so it is not a dylib-boundary problem. The message is the read-before-store
  one: `f`/`dbl` is read as a VALUE and the register allocator gives the name a
  home because the function assigns it somewhere, so the image cannot say
  "unbound". With the name coming from an imported module the failure is even
  blunter: `the library would bind 1 symbol(s) that nothing provides: f`.
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
is not the one the source says. `bugs/FORMAL_hashlib_sha3_and_blake2s_absent.md`
filed a decision of exactly this shape rather than shipping one, and the same
argument applies here.

This is also the shape the (now deleted) `glob`/`copy`/`collections`/`io`
measurement record warned about for `glob` and then withdrew its own advice
about: a module that does not export the name a caller wants converts "out of
reach, with an owner" into an export-map refusal, which dresses a fact about
the target as a gap in the backend.

## The exact next step

Not a module. The root capability is **a first-class function value**, and it is
the same one `collections` needs for a different reason and that
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` §2 already
touches ("a shallow field-wise clone of a compile-time-known struct … is the
same feature `FORMAL_frame_receiver_handoff.md` §4c already names as missing").
Whichever of those lands first unblocks this; the module is then a transcription
and not a design.

Order of work, if it is picked up:

1. A function value as a parameter and as a return — a lowering in both backends
   plus a representation rule, since a callee and a caller must agree on what a
   function IS (a code address; `formal/model.py`'s `pointer_value_model` already
   says what a word can and cannot denote).
2. Decorator application — separately, and before any decorator is exported by a
   hostmod. The two are related (a decorator IS a function value) but a
   half-working version of this that unblocks `reduce` and leaves `@wraps`
   silently dropped is worse than neither.
3. `functools` then follows, and `test_formal_core_hostmods.py` grows a group
   for it the way `enum` and `contextlib` grew theirs.

Until step 2, no `functools` name may be exported, and the test's
`functools`-shaped absence group is what keeps that true.
