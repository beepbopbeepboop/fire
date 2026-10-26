# FORMAL_the_external_call_suite_has_a_red_env_round_trip: a raw pointer local bound from a C call is classified 'int', so `String(ptr)` is refused

**Area:** FORMAL, the value model — `formal/model.py`'s `string_conversion_refusal`
(`:27376`) and `ValueKinds`'s kind for a local bound from an `external_call`
(`_own_shape_of` `:23945`, `_kind_with_ann` `:23908`), against
`test_formal_external_call.py`'s `env_round_trip` case.
**Status: OPEN, measured, not fixed.** Found 2026-10-07 (`work/formal383-docs`)
while running the narrow suites behind the arm64 step-table audit's fix (whose
doc is deleted with it) and `FORMAL_stdlib_module_names_are_not_classified.md`.

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- \
          python3 test_formal_external_call.py
    ...
      FAIL  env_round_trip: ... this build classifies ptr as 'int'. ...
      FAIL  no_module_level_name_is_bound_twice_in_model: got
            ['SET_ALGEBRA_OPS (lines 14039, 14054)'], expected []

`no_module_level_name_is_bound_twice_in_model` is FIXED in the same branch
(a merge of the two set-algebra branches landed `SET_ALGEBRA_OPS` twice; one
binding was deleted and the row is green). This doc is the OTHER red, and the
suite still exits 1 because of it. It is a registered job
(`test('formal-external-call', …, desc='external_call[sym, RetType]: both the
answers and the refusals')`, `tools/suite.py`) with no `expect=` marker, so the
`check` bucket is red on `master` today and not by a known-failure marker.

## What was seen

`env_round_trip` is the FIRST `CASES` row in `test_formal_external_call.py`
(`:68`), the transcription of `std/os/env.mojo` where a raw pointer is turned
into a `char *`:

    def getenv(var name: String, default: String = "") -> String:
        var ptr = external_call[
            "getenv", _CPointer[UInt8, UntrackedOrigin[mut=False]]
        ](name)
        if not ptr:
            return default
        return String(unsafe_from_utf8_ptr=ptr)

and it no longer builds. The refusal, verbatim:

    build: String(ptr) is refused on this path: String is a string type
    constructor, ... this build classifies ptr as 'int'. ...

Minimal reproducer, arm64 and x86-64, byte-identical, and it is not about the
`_CPointer` spelling — `OpaquePointer`, `Pointer[UInt8]` and
`UnsafePointer[UInt8]` refuse the same way:

    def getenv(var name: String) -> String:
        var p = external_call["getenv", Pointer[UInt8]](name)
        return String(unsafe_from_utf8_ptr=p)

    def main() -> Int32:
        printf("%s", getenv("NOPE_X"))
        return 0

## Why, and the two readings

`string_conversion_refusal`'s own contract (`formal/model.py:27403`) is "only
POSITIVE evidence refuses: a kind that is not None and is not `STR_KIND`", and
its one exemption is a DEREFERENCE (`deref_receiver(operand) is not None`,
`:27427`) — which is why the sibling rows
`env_round_trip_with_the_optional_pointer_spelling` and
`env_round_trip_with_the_stdlib_spelling_of_every_argument` PASS: both write
`String(unsafe_from_utf8_ptr=ptr.value())`, and `.value()` is a load here.

For the raw `ptr`, `_expr_str_kind` (`arm64_codegen.py:6306`,
`x86_64_codegen.py:4203`) falls through to `ValueKinds.kind_of`, which answers
`INT_KIND` — and `_own_shape_of` (`:23945`) says OUT LOUD that this is the "a
word, therefore an integer" DEFAULT for a call result and NOT a claim about the
value ("a claim of 'the source says this name holds an integer' may not rest on
it"). So the refusal's premise — positive evidence — is not satisfied, and it
fires anyway because `_expr_str_kind` can only answer `"str"`, `"int"` or
`None`: it has no way to say "a pointer", and a call-result local is recorded as
`INT_KIND` whatever the callee's declared return type is.

Two sound readings, and they are a decision rather than a patch:

1. **The row is stale and the supported spelling is `.value()`.** The
   `nullable_pointer_unwrap` work (`baea817f`, "make a nullable pointer's
   `value()` the unwrap it is") made `.value()` the spelling, and the two rows
   beside `env_round_trip` use it. On this reading the fix is to write
   `String(unsafe_from_utf8_ptr=ptr.value())` in this row too — but that is a
   test edit that stops measuring the raw spelling, so it should be made
   deliberately and not to quiet a suite.
2. **`string_conversion_refusal` is over-firing**, and the fix is to make it
   read OWN evidence rather than `_expr_str_kind`'s folded answer — the same
   distinction `_own_shape_of` already draws for `_bind`. `_expr_str_kind` is
   shared by `print` and the method-receiver guard, where the word default IS
   wanted (a call result formatted as a number), so the change belongs at the
   refusal (or in a second, evidence-returning accessor), NOT in
   `_expr_str_kind`.

**Not measured here:** whether the pre-`string_conversion_refusal` behaviour
(`c8d877e9`, 2026-10-04) was a CORRECT build for `env_round_trip` — i.e. whether
this is a regression or a row that was already red at the tuple-subscript wall
(`test_formal_external_call.py`'s own comment at `:151` says `env_round_trip` is
"sitting on" that wall, and the wall has since been fixed). Either way the row
is red today and the suite is unmarked.

## The exact next step

Decide reading 1 or 2 above. Under reading 1, edit the `env_round_trip` row to
`ptr.value()` and say in its comment why the raw spelling is no longer the one
this path lowers. Under reading 2, give `ValueKinds` (or the refusal) the OWN
evidence for a name bound from a call and exempt a pointer return type the way
`deref_receiver` exempts a load. Either way the pin is the same row passing AND
the reproducer above building; `test_formal_external_call.py` is registered, so
`make check` is red until one lands.
