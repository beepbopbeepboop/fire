# FORMAL_a_kernel_string_through_a_call_boundary_still_answers_in_bytes: the foreign-bytes KIND rides on the reading EXPRESSION, so a call drops it and `len` answers in bytes

**Area:** FORMAL, both backends — `formal/model.py::FOREIGN_BYTES_KIND` and the
two emitters' call lowering. **Status: the DIRECT spelling is FIXED and pinned;
the TRANSITIVE and RETURNED spellings are still a silent wrong answer on both
architectures, measured 2026-10-14, and are the work this document is for.**

## What I ran, and what I saw

Over a directory holding `plain` and `héllo` (`.tmp/probe/utf8`, a scratch
fixture), on arm64 and x86_64, built with `fire.py build --formal --no-prove`:

```python
from os import listdir, listdir_free


def nchars(s: String) -> int:
    return len(s)


def main(n):
    names = listdir(".tmp/probe/utf8")
    for x in names:
        printf("[%s] chars=%d@@", x, nchars(x))
    listdir_free(names)
    return 0
```

```
arm64    [plain] chars=5@@[héllo] chars=6@@     exit 0
x86-64   [plain] chars=5@@[héllo] chars=6@@     exit 0
CPython  [plain] chars=5    [héllo] chars=5
```

**Green build, exit 0, nothing on stderr, the same wrong number on both
architectures** — `6` for `héllo`'s five characters, a `strlen` inside the
callee presented as a `len` over CPython's `str`. This is the exact defect
`bugs/FORMAL_len_of_a_readdir_name_is_refused_and_needs_a_bytes_kind.md` records
for the direct `len(x)`, reached one call further out.

The reason is structural and is the whole of the diagnosis: **`FOREIGN_BYTES_KIND`
is a fact about the EXPRESSION that read the kernel's bytes — a `listdir` element,
a loop target, a `getcwd()` call — and not a runtime tag on the word.** It is
attached to the value on the caller's side and is gone the instant the value
crosses a call, so the callee sees the honest `String` annotation and emits a
`strlen`. `parameter_kinds_by_call_site` does not help, and deliberately so: it
answers what an UNANNOTATED parameter holds, and a `String` parameter is
annotated.

**Two more shapes are wrong for the same reason, and neither is fixed here:**

* **TRANSITIVE.** `def f(s: String): return g(s)` where `def g(s: String): return
  len(s)`. Measured, both architectures: `chars=6` for `héllo`, exit 0. The kind
  is gone at `main`'s call to `f`.
* **RETURNED.** `def ident(s: String) -> String: return s`, then `y = ident(x)`
  and `len(y)`. Measured, both architectures: `chars=6`, exit 0. The kind is gone
  at the return; `y`'s kind is the `String` annotation.

The CONTROL is what keeps the boundary the right width: passing a kernel string
into a `String` parameter that only PRINTS it is correct and must keep working
(pinned by `a_kernel_name_into_a_printing_parameter_still_runs`), so the fix is
not "refuse every foreign argument at every call".

## What landed (2026-10-14): the DIRECT spelling is refused

`formal/model.py::foreign_bytes_into_text_parameter_refusal`, asked from both
emitters' `_emit_call` beside `_refuse_word_position_kind_mismatch` (so the two
architectures cannot decide one call differently). It walks the CALLEE's own
body — `model.codepoint_measured_parameters`, which collects the `len(p)` and
`p.find(...)` uses of a parameter name and does NOT descend into a nested `def`
— and refuses a call that passes a `FOREIGN_BYTES_KIND` argument into a
parameter the body measures as text. A function that only prints the argument is
not touched.

Pinned in `test_formal_os_backing.py` by three rows, both architectures:
`a_kernel_name_into_a_len_parameter_is_refused`,
`a_kernel_name_into_a_find_parameter_is_refused` (`find`'s byte OFFSET is the
sibling construct) and the printing control above. `test_formal_run.py` 1234/1234,
`test_formal_unicode.py` 180/180, `test_formal_value_model.py` 125/125,
`test_formal_hostmods_census.py` 74/74 rows and `test_formal_os_backing.py`
78/78 after the change.

## The exact next step, and why it is not a call-site test

**The transitive and returned spellings need the foreign kind to PROPAGATE —
through a parameter at every call that reaches it, and through a return that
hands a parameter back — which is a whole-image fixed point and not a predicate
at one call.** The machinery to hang it on exists and is the argument for doing
it there rather than at the calls:

* `model.parameter_kinds_by_call_site` already computes a per-parameter kind by
  UNANIMITY over every call site; what it lacks is a FOREIGN row, and its
  `_parameter_argument_shape` is a SHAPE reader (a literal, a list literal, a
  callee's declared return) with no access to the caller's `ValueKinds`, which is
  where a kernel string's kind lives. Teaching it the kind means running the
  caller's kind reader per call — the fixed point, since a callee's own arguments
  then need the table the walk is building.
* the RETURNED shape has no reader at all: `ValueKinds` gives a call the callee's
  DECLARED return kind (`String`), and there is nothing that says "this callee
  returns the parameter it was given". A `-> String` that is `return s` is the
  same problem one direction over.

Two honest ends, in the order worth trying:

1. **Propagate the kind as an over-approximation**: a parameter whose body
   measures it as text, or which flows to another such parameter or to the
   return, is `FOREIGN_BYTES_KIND`-compatible — meaning `len` on it refuses
   unless every call site proves ASCII. That trades a real capability (`len` of a
   runtime `String` that is in fact ASCII) for soundness, which is the direction
   this whole kind exists to take, and is the reason it is worth measuring before
   choosing it.
2. **Or answer the count at run time**, which closes the subject rather than the
   spelling: a code-point count over the bytes with CPython's `surrogateescape`
   (maximal-subpart) splitting. That is
   `bugs/FORMAL_len_of_a_readdir_name_is_refused_and_needs_a_bytes_kind.md`'s
   "not small" item and it retires this document with it.

**Do NOT** close this with a call-site predicate that walks one level further
(`f`'s parameters against `g`'s): it is the same shape as the direct fix and it
stops one call short of the fixed point, which is how the direct spelling looked
"done" until this document measured the next one.
