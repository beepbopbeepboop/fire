# TEST: `constr_refuse_an_undeclared_base_by_name` pins a needle no message
# reaches, so `test_formal_run.py` is red on `master` and the refusal it was
# written for is not the one a reader gets

**Area:** tests (FORMAL corpus). **Status: OPEN, measured on `master`, not
fixed.** Found 2026-10-04 while landing the byte-blob element width, by running
the whole of `test_formal_run.py` and reading its failures. **Pre-existing**:
the case fails identically with that change reverted (`git apply -R`, re-run,
re-apply). The sibling failure in the same run is
`bugs/FORMAL_a_var_decl_in_a_one_word_receiver_method_raises.md`.

## What I ran

```console
$ cat .tmp/dbg3.mojo
class MyErr(Widget):
    """no fields at all"""

def boom():
    raise MyErr("the message")

def main(n):
    try:
        boom()
    except:
        pass
    return 0

$ python3 tools/memslot.py --gb 8 --label dbg -- python3 fire.py build \
      --formal --no-prove --backend=arm64 -o .tmp/dbg3 .tmp/dbg3.mojo
```

## What I saw

The build refuses — which is right; this image declares no `Widget`, so a
subclass of it has no base fields to bring up — but with a **different
diagnostic** from the one the case pins:

```
build: constructing MyErr with 1 argument(s) does not match its fields (no
fields at all), and MyErr declares no `__init__` for it to call instead: with
no user-defined constructor, a struct's fields are filled in DECLARATION ORDER
from positional arguments and there is no other form, so this path can only
place a word in a slot it can name. Give the fields explicitly (`MyErr()` then
`obj.<field> = …`), which is the same program with a representation
```

`test_formal_run.py:11399` expects

```
refuse:derives from 'Widget', which this image does not declare
```

so the case reports

```
FAIL  constr_refuse_an_undeclared_base_by_name: --backend=arm64 refused, but
not with the expected words "derives from 'Widget', which this image does not
declare": … the arity sentence above
```

## Which of the two is stale

**The test's needle**, and the reading is not a guess: the arity message is
`model`'s, it is reached from `_emit_struct_constructor` (which asks the struct
"how many fields do you have", gets zero, and compares against one argument), and
it is a *better* answer than the base one for this program because it names the
alternative that works. The base diagnostic the case was written for fires when
the arity happens to MATCH — `class MyErr(Widget): var x: Int` with
`MyErr(1)` — which is the program whose failure is genuinely "this image does
not declare `Widget`".

So the shape is the same one `test_formal_run.py` has in several places: a
refusal family that grew a **better** message upstream of the one pinned, and a
case that has been red ever since. It is test debt, not a codegen regression —
nothing about the program's verdict changed, only which of two true sentences
about it is the first one printed.

## The exact next step

Two cases, and the second is the load-bearing one:

1. re-point `constr_refuse_an_undeclared_base_by_name` at the sentence the
   program now reaches (`does not match its fields`), and keep the class
   docstring's claim — a subclass of an UNDECLARED base with no fields of its
   own cannot place a word — as the comment above it;
2. **add** the case that makes the base diagnostic observable, with a field so
   the arity matches:

   ```
   class MyErr(Widget):
       var msg: String

   def boom():
       raise MyErr("the message")
   ```

   expected `refuse:derives from 'Widget', which this image does not declare`.

Without (2) the base diagnostic loses its only test, and the next person to read
the case sees a passing test and concludes the base refusal is the one that fires
for a no-field subclass — which is false.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
      constr_refuse_an_undeclared_base_by_name
$ python3 tools/memslot.py --gb 8 --label dbg -- python3 fire.py build \
      --formal --no-prove --backend=arm64 -o .tmp/dbg3 .tmp/dbg3.mojo
```