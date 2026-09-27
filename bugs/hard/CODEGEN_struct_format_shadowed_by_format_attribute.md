# HARD BUG: `struct.Struct.format(...)` silently returns `0` on the compiled path, where Python raises `TypeError`

**State: OPEN.** NEW 2026-09-26. Reproduces, pre-existing (confirmed on a clean HEAD~1), silent. The
attribute READ is correct; only the CALL is wrong, returning 0 where CPython and this
repo's own reference interpreter both raise TypeError. Untested: whether other struct
members hit the same default-to-0 stub.


## Status (2026-09-26 — confirmed reproducible and PRE-EXISTING; silent wrong value, not a compile failure; not fixed)

Surfaced while closing out the `struct` module's residual items, back when
that work lived in a doc that has since been removed. It had recorded this as
"`.format` read through a class-attribute-held `Struct` returns garbage" —
**both halves of that were wrong**, and this entry replaces it:

- it is not specific to a class-attribute-held `Struct`; a plain local
  fails identically;
- it does not return garbage — it returns `0`.

## The bug

`Struct.format` is an **attribute** (the format string) that shadows the
`Struct.format()` *method* in real Python. So reading it gives the format
string, and CALLING it is an error:

```python
>>> import struct
>>> s = struct.Struct("<HH")
>>> s.format
'<HH'
>>> s.format(70)
TypeError: 'str' object is not callable
```

The compiled path gets the read right and the call wrong — `s.format(70)`
returns `0` instead of raising, with exit 0:

```python
import struct

def main():
    var s = struct.Struct("<HH")
    print(s.format(70))
```

| expression | CPython | reference interpreter | compiled |
|---|---|---|---|
| `s.format` (attribute read) | `'<HH'` | `<HH` | `<HH` — **correct** |
| `s.format(70)` (call) | `TypeError: 'str' object is not callable` | same `TypeError` | `0` — **silent** |

That split is the useful diagnostic: the struct receiver IS being resolved
for the attribute read, so this is not a "can't find the receiver" problem.
It is specifically that a call on a `MojoStructFmt`'s `format` member is
dispatched as if `format` were the struct's own `format` method and then
stubbed, instead of being recognised as a call on a non-callable `char *`
attribute.

The same holds through a class attribute, for both field spellings:

```python
class Holder:
    var F = struct.Struct("<HH")
    def go(self, v):
        return self.F.format(v)      # compiled: 0
```

Note this is a *different* defect from the NULL-initializer crash that
landed for `var F = struct.Struct(...)`: that one left
the field NULL and `self.F.size` segfaulted. This one is reached through a
correctly-initialised `Struct` — `s.size`, `s.format` and `s.unpack(...)`
all behave correctly on the very same object — so it is an independent hole
in call dispatch, not a consequence of the field-registration fix.

## Correcting the record

The removed `struct` module doc recorded this as "`.format` returns a
pointer-sized integer rather than the format string ... and a LOCAL
`s = struct.Struct('<HH'); s.format` is correct too". **Both claims were
wrong** on re-test: the local case fails identically to the class-attribute
case, and the attribute read is correct in both. That section has been
corrected to point here.

## Why it is hard-class

Silent wrong value with exit 0, on a reachable stdlib type. A caller that
formats a struct and gets `0` has no signal at all. That is strictly worse
than a refusal, and it is the same class of defect as the other
silent-miscompile entries in this directory.

## Pre-existing, verified

Confirmed identical on a clean `HEAD~1` worktree, so it is **not** a
regression from the `struct_module` work (which touched per-slot unpack
kinds and class-field registration, and neither path is involved here).

## Evidence that dispatch *should* have worked

The pieces are all present, so this is a hole in the lowering rather than a
missing feature:

- `mojo_struct_format` is declared in `mojo/middle/types.py`'s
  `_RUNTIME_FUNCS` (returning `char *`).
- `'format'` is listed in `_STR_RETURNING_METHODS`.
- `emit_methods.py` has several `format` cases for *other* receivers
  (`str.format` and friends).

So the struct-receiver case is falling through to the default
"unknown method → `0`" stub rather than being routed to
`mojo_struct_format`. The interesting part — and the part not yet
investigated — is that a correctly-initialised `Struct` receiver is
resolved for `size` and `unpack` but not for `format`. That asymmetry is
the actual lead: whatever marks a `MojoStructFmt *` receiver as a struct
for `size`/`unpack` is not reaching the `format` case.

## Also unexamined

Whether the same default-to-`0` stub swallows other unimplemented
`Struct`/module-level `struct.*` members. Only `format` has been tested.
An audit of the `struct` API surface against the compiled path would
either find more holes or establish that `format` is the only one — worth
doing before fixing this one, so the fix is not scoped to a single symptom.
