# FORMAL_string_constructor_collision: `String()` is a `char *` to the emitters and a three-slot frame to the analysis

**Status: the CRASH is fixed — a green build that died with SIGBUS is now a
build error naming both readings. The underlying ambiguity is NOT fixed, and it
is not a string-value-model problem.** The reproducer, the measurements and the
larger question (`bugs/FORMAL_string_value_model.md`'s D2 item) are in
`bugs/FORMAL_string_constructor_collision` on `work/merge2-formal`; this file
records what landed, because the fix had to be narrower than either of the two
the filing names, and the reason is worth the space.

## What landed

`formal/model.py::call_lowers_as_framed_construction` — the emitters' routing
order written down once, in the model both backends and the build pass read — and
two uses of it:

* `formal/build.py::_constructor_bindings` now records a constructor binding only
  when the emitters would actually lower the call as a construction.  Being in
  `framed_struct_names` is necessary and not sufficient.
* `formal/build.py::_park_construction_mismatches` +
  `formal/model.py::construction_mismatch_refusal` + the entry point
  `check_construction_mismatches`, which say WHY, by name, when the name is also
  used as a receiver.

## Before and after, both architectures

```
struct String:                        # three fields, exactly as the stdlib has it
    var _ptr_or_data: Pointer[UInt8]
    var _len_or_data: Int
    var _capacity_or_data: Int
    def size(self) -> Int: return self._len_or_data
def main(n: Int) -> Int:
    var a = String()
    a._len_or_data = 5
    return a.size()
```

| | arm64 | x86-64 |
|---|---|---|
| before | **Built.** SIGBUS, exit **138**, in read-only `__TEXT` | **Built.** SIGBUS, exit **138** |
| after | refused, identical words | refused, identical words |

## Why the fix had to be narrower than the filing's option (1)

The filing offers two directions and recommends (1): "make `_constructor_bindings`
ask the emitter's question … a call whose name the emitter will NOT lower as a
framed construction is not a constructor binding, so the name is a plain word and
`a._len_or_data = 5` becomes `model.field_access_refusal`". That half is exactly
what landed, and it is not enough on its own — the resulting message is FALSE.

Without the second half, the store is refused with `field_access_refusal`, whose
`holder` flag comes from `root in self._frame_holders` and is now False, so the
message reads:

> 'a' is bound here as a **parameter**, so none of the three is established

which is not what happened: `a` is a local bound from a string conversion, and it
holds the address of an interned `char *`.  "A refusal whose stated reason is
entirely false is the worst outcome on this path"
(`bugs/FORMAL_frame_receiver_handoff.md` §4), and the analysis is the only place
that knows the difference — the emitter sees the same `a` either way.  Hence
`check_construction_mismatches`, which fires **only when a `MemberExpr` is rooted
at the name**, because that is the use that has no reading.

**The receiver test is what keeps the legitimate use working.**  `String()` on
its own is CORRECT on this path — it is a `char *` and `printf("[%s]", a)` prints
`[]` — so a check that fired on the construction alone would refuse every file
that binds a string.  Measured as `FIXED_CASES` in `test_formal_value_model.py`.

## The coverage measurement, which came out better than the filing expected

The filing predicts this "will move verdicts in the sweep for every file that
declares its own `String`".  Measured by running the pass over every file and
reading the parked findings, with no codegen and no linking:

| scope | files scanned | raised before the collect | would refuse |
|---|---|---|---|
| this repository | 319 | 40 | **0** |
| the stdlib (`std/**.mojo`) | 294 | 75 | **11** |

and all **11** are already `codegen` or `codegen/dependency` in the sweep
snapshot — `builtin/_format_float.mojo`, `collections/string/_unicode.mojo`,
`collections/string/codepoint.mojo`, `ffi/__init__.mojo`, `iter/__init__.mojo`
(the `Optional` case, a two-field struct), `os/path/path.mojo`,
`subprocess/subprocess.mojo`, `sys/_libc_errno.mojo` (a `StringSlice`, an
IDENTITY constructor — the same collision under a different name),
`testing/prop/strategy/string_strategy.mojo`, `testing/suite.mojo`,
`testing/testing.mojo`.  **Net: not one file that answered before stops
answering**, so the denominator does not move and the coverage percentage is not
a gain and not a loss — only the message each of those eleven reports changes.

## What the guard also fixed, for free

`std/python/_cpython.mojo` has

```
var error: String
try:
    error = String(py=PythonObject(from_owned=err_ptr))
```

and `String` is a declaration this file reaches through its import of
`std.collections`, so it is in `framed_struct_names` and `error` was recorded as
a constructor binding — a HOLDER of a frame — and then assigned a `char *`.  The
holder-rebind check added in the previous commit was firing on it, and firing
WRONG: `error` holds a `char *`, which is fine for a `char *` name.  With the
guard the name is a plain word, `error` is not a holder, and the finding is gone
because it was never a defect — it was an artifact of this collision.  Worth
recording because it is the second time one commit's diagnostic turned out to be
measuring the previous commit's bug.

## What is still open, and it is D2

The name `String` denotes two things at once, and the fix makes the two
*disagree visibly* rather than making them agree:

* the emitters lower the string METHODS under the `char *` reading
  (`bugs/FORMAL_string_value_model.md`'s decision, and a measured one), and
* `struct_is_framed(String)` is True, so `model.struct_frame_slot` gives the
  three fields slots.

The stdlib's own comment is the best statement of why both are needed —
`std/collections/string/string.mojo:220-224` declares the three fields and then
says the string has TWO forms, "the declared form here, and the `inline` form
when `_capacity_or_data.is_inline()` is true", with a flag in the top byte of the
capacity field choosing between them AT RUN TIME.  So the representation question
is real and is not answered by any of the three refusals in this family: it is
`formal/model.py`'s "a `String` local must be either a three-slot frame or a
`char *`, and today the two representations are in force simultaneously", and it
is the cause of all sixteen "a String receiver" refusals in the stdlib sweep.

**Next step, unchanged from the filing and still not a constructor question:** the
frame/field derivation has to learn the inline form, which is a per-binding run
time choice rather than a per-name one.  A name bound to a `char *` is text; a
name bound to a fresh three-slot block is a frame; and a name that can be either
needs the flag read before the first field access, which no pass here does.  The
narrower version of that — refuse a `String` local whose value came from a
CONVERSION and whose field is written, which is what now happens — is the honest
answer until the flag is read.