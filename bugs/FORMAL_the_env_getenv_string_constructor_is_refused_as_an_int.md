# FORMAL_the_env_getenv_string_constructor_is_refused_as_an_int: `String(unsafe_from_utf8_ptr=ptr)` for a pointer-returning `external_call` is refused, so `formal-external-call` is red

**Measured 2026-10-08 on `3bc7d54b`, both architectures. It is a regression in a
gate job: `tools/suite.py`'s `formal-external-call` row records the file as
`PASS=45 FAIL=0` ("NOT red any more", its own comment says), and the same file
today is `PASS=51 FAIL=1`.**

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_external_call.py env_round_trip
  FAIL  env_round_trip: nt'. It used to pass the value through unchanged, which
  is a number where every later step expects a pointer: `len(str(n))` with n = 10
  built, ran and died of SIGSEGV (exit -11) on both architectures, inside
  `strlen` walking the bytes at address 10. …

external_call: PASS=0 FAIL=1

$ python3 test_formal_external_call.py
external_call: PASS=51 FAIL=1
```

(The full refusal, from the case's own source in isolation:)

```console
$ cat .tmp/env.mojo
def getenv(var name: String, default: String = "") -> String:
    var ptr = external_call["getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]](name)
    if not ptr:
        return default
    return String(unsafe_from_utf8_ptr=ptr)

def main() -> Int32:
    printf("x=%s\n", getenv("HOME", "none"))
    return 0
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove -o .tmp/env.aout .tmp/env.mojo
build: String(ptr) is refused on this path: String is a string type constructor,
and a string on this path IS a `char *` — an interned, NUL-terminated literal —
so constructing one is the identity on a value that is already text and nothing
at all on one that is not, and this build classifies ptr as 'int'. …
```

## What I expected

`env_round_trip` is a transcription of `std/os/env.mojo:26-85`, and its
`getenv` is the file's own text. `external_call["getenv", _CPointer[UInt8,
UntrackedOrigin[mut=False]]]` declares a `char *`, so `ptr` is a pointer and
`String(unsafe_from_utf8_ptr=ptr)` is the identity on a `char *` — the case
builds, runs and prints `set=hello|absent=fallback|after=gone|`, exit 0. That is
what `tools/suite.py`'s comment records it doing when the row lost its
`expect=`, and what the case's pinned expectation (0,
`"set=hello|absent=fallback|after=gone|"`) still says.

## What is wrong, and where it lives

The classification of `ptr` is `int`, not a pointer, so the string
constructor's refusal (`formal/model.py::string_conversion_refusal`, the
`String(X)` path) fires on a value that IS a `char *`. The pointer's declared
type is the stdlib alias shape `_CPointer[UInt8, UntrackedOrigin[mut=False]]`,
which `formal/model.py`'s pointer-alias table is supposed to resolve (see
`bugs/FORMAL_pointer_value_model.md` §3, which measures exactly this line and
`bugs/FORMAL_string_value_model.md`). So this is a value-model regression in
the pointer alias / external-call return classification, not in the string
constructor rule itself.

**It is not the `external_call` construct.** The call is read and bound; what
fails is the TYPE the bound word is given. `c_symbol_wins_over_a_local_of_the_
same_name` and the other `external_call` rows still pass, and
`a_nested_bracket_in_the_type_argument_is_not_a_tuple_index` — the other half of
this same row's history — still passes. Only the one case that reads the
returned pointer as text fails.

## Why it is not fixed here

I found it while fixing an unrelated bug in `formal/arm64_codegen.py` /
`formal/x86_64_codegen.py` (`printf(fmt, g(…))` for a return-less `g` was not
refused). **The failure reproduces on the pristine tree with my change
reverted**, measured both ways with `git diff`/`git apply -R`/`git apply`, so it
is pre-existing and independent. The fix is in `formal/model.py`'s pointer
value model, which is another worker's claimed area
(`FORMAL_pointer_value_model`, `FORMAL_string_value_model`), so it is filed
rather than edited.

## The exact next step

Ask `formal/model.py`'s pointer-alias reader for the external call's declared
return type in this transcription. `external_call["getenv", _CPointer[UInt8,
UntrackedOrigin[mut=False]]]` is the stdlib's nullable-pointer spelling, and the
value model already has `baea817f`'s "teach the value model the stdlib's
pointer ALIASES" work for it — the regression is that the alias is not being
resolved for the `external_call` return position, so `ptr` lands in the default
`INT_KIND`. Bisect from `3bc7d54b` over `formal/model.py` with:

```console
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_external_call.py env_round_trip
```

and the row is done when it is `PASS=1 FAIL=0` again — which also clears the
only red in `python3 test_formal_external_call.py`.
