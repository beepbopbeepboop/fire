# An exception subclass of a builtin base BUILDS, and then the program dies in
# the `raise` with the handler never entered — CPython catches it

**Area:** FORMAL, the run-time behaviour of `raise` for a class this image
declares with a BUILTIN base. **Status: OPEN, measured on `master` (and on this
merge), NOT fixed here.** Found 2026-10-05 while merging `work/formal23-5` and
writing the negative half of `test_formal_run.py`'s
`constr_refuse_an_undeclared_base_by_name` — the case that pins an unresolved
base beside a legal builtin one. Both architectures agree, so this is not an
architecture drift; it is a program that builds and is not the program written,
with no refusal anywhere.

## What I ran

```console
$ cat .tmp/exc4.mojo
class MyErr(ValueError):
    """no fields at all"""

def boom():
    raise MyErr("the message")

def main(n):
    try:
        boom()
    except:
        pass
    print("caught")
    return 0

$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/exc4.arm64 .tmp/exc4.mojo
Built: .tmp/exc4.arm64  [arm64/macho]
$ ./.tmp/exc4.arm64 ; echo "exit=$?"
exit=1
```

and the same file with `--backend=x86_64` (`stdout='' exit=1`, byte-identical
answer). The CPython oracle is the same text with `main(1)` appended, which is
what `test_formal_run.py`'s own oracle does — the bare file defines `main` and
never calls it, so running it under `python3` unchanged exits 0 having printed
nothing, which is not the comparison:

```console
$ python3 .tmp/exc4_oracle.py ; echo "exit=$?"
caught
exit=0
```

## What I expected

`caught` and exit 0, on both machines. `ValueError` is a builtin base, so the
subclass inherits `BaseException.__new__`'s `args`, the construction is legal in
CPython, and a bare `except:` catches everything.

## What I saw

**The build succeeds and the program then dies.** Nothing is printed, the exit
code is 1, and the `except:` arm is never entered — the program is not the
program that was written, and nothing says so at build time.

**It is pre-existing.** The same file built from a `git archive master` export
with no diff applied:

```console
$ cd .tmp/master-tree && python3 .../tools/memslot.py --gb 8 --label t -- \
      python3 fire.py build --formal --no-prove --backend=arm64 -o ./exc3.arm64 \
      exc3.mojo
Built: ./exc3.arm64  [arm64/macho]
$ ./exc3.arm64 ; echo "exit=$?"
exit=1
```

**The construction is not the half that is broken**, which is what makes this a
`raise` question rather than an arity one. The same class constructed and never
raised builds and runs correctly on both machines:

```console
$ cat .tmp/exc2.mojo
class MyErr(ValueError):
    """no fields at all"""

def main(n):
    var e = MyErr("the message")
    print("built")
    return 0
$ ./.tmp/exc2.arm64 ; echo "exit=$?"
builtexit=0
```

(That program is `test_formal_run.py`'s
`constr_an_unresolved_BUILTIN_base_still_constructs`, added with the fix that
made the arity refusal name the base; it pins the ARITY path and deliberately
does not pin what a raised exception does.)

**The direct spelling is refused, and the subclass spelling is not** — which is
the asymmetry worth knowing before anyone reads this as "exceptions are
unsupported":

```console
$ cat .tmp/exc1.mojo
def boom():
    raise ValueError("the message")
...
$ python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/exc1 .tmp/exc1.mojo
build: exc1.mojo: the image would bind 1 symbol(s) that nothing provides, so it
could not be loaded: ValueError. `ValueError` is a call this build emitted and
nothing provides it, so that call is not lowered on this path …
```

So `raise ValueError("x")` says no, and `raise MyErr("x")` for
`class MyErr(ValueError)` says nothing and then traps. A subclass of an
unmodelled base is exactly the spelling a user writes when they want their own
exception type, so this is reachable from ordinary code and not from a corner.

## The exact next step

One question, and it is decidable at build time: **is the raised class derived
from a base this image cannot see?** `model.struct_unresolved_bases` already
answers that for the arity path (which is why `MyErr(Widget)` is refused with the
base's name) and `model.builtin_base_fields` answers the other half of it — a
class whose only unresolved base is a builtin exception has a real field list
(`args`) and is constructible, while `MyErr(Widget)` has none.

The run-time half is the separate question, and it is the one this doc is about:
whatever the `raise` lowers to for a class with no in-image base has to be
**refused**, with `struct_unresolved_bases`' own wording reused rather than a
new sentence, or the handler has to be emitted. A `raise` that cannot be caught
is worse than a refusal, because every program containing one is silently a
different program.

Two measurements to take first, in this order, because they decide which of those
two it is:

1. Does the image contain a landing pad at all for this `raise`? Read the
   function out of `info["labels"]` and `otool -tvV` as
   `bugs/FORMAL_arm64_a_narrow_typed_parameter_makes_the_universal_contract_false.md`
   and its neighbours do. If the trap is the stack-floor guard's `exit(2)` path
   with no handler installed, the fix is the refusal in (2); if a handler IS
   installed and the comparison that selects it never matches, the fix is in the
   dispatch.
2. Does the same program with a DECLARED, in-image exception base behave the
   same way? The `except` arm's own doc was deleted with its fix, so re-measure
   rather than reading it: a program whose base is declared here and whose
   `except:` arm is still never entered would say the arm is not emitted at all,
   which is a bigger and different fix.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- python3 fire.py build --formal \
      --no-prove --backend=arm64 -o .tmp/exc4.arm64 .tmp/exc4.mojo && ./.tmp/exc4.arm64
$ echo $?          # 1, with nothing printed
```