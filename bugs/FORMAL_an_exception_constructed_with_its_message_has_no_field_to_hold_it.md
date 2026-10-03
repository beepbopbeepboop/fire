# FORMAL_an_exception_constructed_with_its_message_has_no_field_to_hold_it: one declaration per exception class

**Class:** a source-side omission, not a backend limit. The refusal it causes is
correct and well worded; the file it refuses is wrong.
**Area:** `mojo/backend_gimple/device_glue.py` (`LaunchError`), and every other
exception class in this repository written with a docstring and no fields.

Found while re-measuring the rows of
`bugs/FORMAL_sweep12_singles_a.md` §2 on 2026-10-03, whose example this is.

## What I ran

```
$ python3 tools/formal_sweep.py -j 1 -t 120 --no-stdlib \
      mojo/backend_gimple/device_glue.py
CODEGEN: mojo/backend_gimple/device_glue.py  (build: constructing LaunchError
  with 1 argument(s) does not match its fields (no fields at all), and
  LaunchError declares no `__init__` for it to call instead: …)
```

and the shape on its own, both architectures, so the claim does not rest on one
576-line file:

```
$ cat .tmp/excslot4.mojo
struct Plain(Exception):
    """no fields at all"""

def boom():
    raise Plain("the message")

def main() -> Int32:
    try:
        boom()
    except:
        pass
    return 0

$ python3 fire.py build --formal --no-prove --backend=arm64  -o … .tmp/excslot4.mojo
$ python3 fire.py build --formal --no-prove --backend=x86_64 -o … .tmp/excslot4.mojo
  build: constructing Plain with 1 argument(s) does not match its fields (no
  fields at all), and Plain declares no `__init__` for it to call instead: with
  no user-defined constructor, a struct's fields are filled in DECLARATION
  ORDER from positional arguments and there is no other form, so this path can
  only place a word in a slot it can name. …          [both, byte for byte]
```

## What I see

`LaunchError` is a docstring and nothing else:

```python
class LaunchError(Exception):
    """A kernel whose host side cannot be marshalled honestly."""
```

and the file raises it with its message (`raise LaunchError(str(e))`). So the
class has **no slot for the message at all**, and the message this path refuses
is the truthful one: a word has to go somewhere it can name.

**The fix is one line, and the repository already contains it**, with a
comment that says why — `formal/x86_64_decode.py`'s `DecodeError`:

```python
    #: `BaseException.args`, declared so the message has a SLOT.  CPython fills
    #: `args` from the caller's arguments and `str(e)` reads it, so
    #: `raise DecodeError(msg)` already carries the text there; an annotation
    #: with no initializer creates no attribute and runs nothing, so this is
    #: invisible to the language and to every reader of this module.
```

`LaunchError` wants that same declaration (`var args: String`, with the same
comment), and `mojo/backend_gimple/spec_gen.py`'s and `module_spec_gen.py`'s
`FileNotFoundError` uses are the CPython-provided ones that already fill it.

Measured boundary of the rule, because it decides which classes need the line:
a class with **one or more** fields and no `args` is fine — `struct
Plain(Exception): var tag: Int` constructed as `Plain("m")` builds and runs on
arm64, positionally, which is what CPython does with it too. It is the
**no-fields-at-all** class that cannot be constructed with a message at all.

## What is next

1. Declare `args` on `LaunchError` (one line, `mojo/backend_gimple/device_glue.py:154`).
   That is the whole fix, and this file's terminal cause is this line: the
   sweep reports nothing else about it.
2. Then `python3 tools/formal_sweep.py --no-stdlib mojo/backend_gimple/device_glue.py`
   re-measures — this row moves that file off `codegen` and onto whatever it
   hits next, which is the point of measuring rather than assuming it builds.

**Ownership.** `bugs/FORMAL_sweep12_singles_a.md` §2 records this row as
belonging to the `sweep12:singles-b` claim (`formal12-singles-b`), whose example
file it names, so it is deliberately not fixed from here — this doc is the
measurement and the exact next step, and the fix is theirs to land.

## What this is NOT

Not the exception-ARM row (`bugs/FORMAL_except_arm_is_never_emitted`, claimed
by `formal8-5`): an arm's body is a different question, and `device_glue.py`
reaches this line first. Not the `args` *field* being unwritable: the field is
never read on this path — the class exists only so the construction has a slot
to put the message in, which is why a declaration with no initializer is the
right fix and not an annotation.
