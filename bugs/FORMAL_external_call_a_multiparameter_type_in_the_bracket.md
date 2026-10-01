# A two-parameter TYPE subscript inside an `external_call` bracket is refused as a value subscript

## Status

OPEN — found 2026-10-01 while registering `test_formal_external_call.py` for the
test estate (it was named by no spec and in no bucket; it is now
`formal-external-call`, in `proofs`, declared red with `expect=`). **1 of 29
cases fails, on arm64** — `env_round_trip`.

## What is believed

The refusal is CORRECT about the shape and is asking the question at the wrong
moment.

`external_call["getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]]` names
its return type as a two-parameter generic application. Somewhere between the
parser and `formal/model.py`'s subscript handling, that inner
`_CPointer[UInt8, UntrackedOrigin[mut=False]]` — a TYPE, with two type
arguments — is seen as a SUBSCRIPT WHOSE INDEX IS A TUPLE, and refused:

```
build: _CPointer[UInt8, UntrackedOrigin[…]] is a subscript whose index is a
tuple. A value here is one 64-bit word and a list is a flat blob of words, so a
tuple index has no representation on this path. It is one of two things: a
lookup keyed by the tuple, which is lowered only when the base is a known dict
and compares the key element-wise; or a two-dimensional index, which needs a row
stride the source never states. Refused rather than computing a plausible flat
index, and rather than using the tuple blob's own address as the index — that
builds, runs, and returns an element nobody asked for.
```

Every claim that message makes is true of a VALUE subscript and none of it is
true of this one. `_CPointer` is not a list, so "a list is a flat blob of words"
does not apply; the index is not a runtime tuple at all, it is two type
arguments the build resolves and then throws away; and "a two-dimensional index
which needs a row stride the source never states" describes `a[i, j]` on a
matrix, which is not what a generic application is.

So this is not a hole in the refusal — it is the refusal firing on the wrong
node. `external_call`'s OWN bracket is a two-element subscript and it is
correctly read as the construct (that is `formal-extcall-tuple`'s whole
subject, `4ad34f3`); the type annotation inside it should be read as a type
application and resolved as one, which `formal-value-model`'s
`5536f17b` ("a type APPLICATION is not a type value") already establishes for
the value side.

## What was run, and what it saw

```
$ python3 test_formal_external_call.py -v env_round_trip
  FAIL  env_round_trip: <the refusal above, verbatim>
external_call: PASS=0 FAIL=1
```

The program is the one `std/os/env.mojo` itself spells (`std/os/env.mojo:26-47`,
`50-62`, `65-85`), transcribed exactly: `setenv`/`unsetenv`/`getenv` through
`external_call`, `printf`-ing three answers. Its expectation is
`set=hello|absent=fallback|after=gone|`, which is what CPython's own `os.getenv`
family produces for the same calls.

The other 28 cases pass, including `env_setenv_status_is_the_c_int` and
`env_getenv_null_is_a_null_pointer`, which use `Int32` and `c_int` as the
bracket's return type — a ONE-parameter or unparameterized spelling the
subscript check has no tuple to find. So the failure is specific to the
multi-parameter type, not to `external_call`.

## Why it matters

This is one of the two halves of `bugs/FORMAL_env_family_next_terminal.md`'s
family, and the doc's own measurement is the reason it is worth closing rather
than filing: `external_call` was the terminal refusal behind 55 stdlib files,
`4ad34f3` closed the construct itself, and this is what the family runs into
one step later. A type annotation in an argument position is not an exotic
spelling — `_CPointer[UInt8, UntrackedOrigin[mut=False]]` is what the real
`env.mojo` writes, so the first caller of the finished construct hits this.

The wider shape is the one worth naming: `formal/model.py` has several
agree-or-refuse rules that read a subscript by its SHAPE (tuple index ⇒ no
representation) without asking whether the base is a type. Every one of them
can be reached the same way, by a multi-parameter generic in a position where a
value was assumed.

## Next step, in the order it should be taken

1. **Find where the type application stops being a type.** `formal/build.py`'s
   name walk has a type-position notion already (`5536f17b`); the question is
   whether the subscript refusal runs BEFORE or AFTER it. Start at
   `formal/model.py`'s tuple-subscript message text — it is quoted verbatim
   above, so `grep` finds the raiser — and read what it was handed for the
   `external_call` case.
2. **Prefer fixing the order over special-casing the caller.** The caller is
   `external_call`'s bracket reader and there are other bracket-shaped
   constructs; a rule that says "a subscript on a name the walk has RESOLVED as
   a type is a type application" fixes all of them, and one that says
   "`external_call` gets an exemption" fixes one.
3. **The test is already the regression.** `env_round_trip` goes green when the
   type application is resolved as one, and it is a differential case — it
   builds, runs and diffs against the expected stdout — so it cannot pass by
   refusing something else. It is registered red, so the moment this lands the
   `expect=` marker reports itself as a FAILURE ("marked expect=… but it
   PASSES"), which is the intended way for it to be retired: drop the marker
   from `formal-external-call` in `tools/suite.py` and delete this doc in the
   same commit.