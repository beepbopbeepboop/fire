# `algorithm/backend/tile.mojo`: a specialization call through a FUNCTION-VALUE field, and 4 stdlib files behind it

**Area:** FORMAL (comptime specialization on a callee this unit does not
compile). Found 2026-10-01 on `work/formal-re-refusal` while working the
`other refusal` row. **NOT FIXED — and the "Whose" section below is STALE: the
`construct:mlir-and-gpu-globals` claim it points at no longer exists, so this row
is unowned. What is new is the measurement at the end, which shows that this
document's own next step is necessary and NOT sufficient.**

## What was run

    $ for a in arm64 x86_64; do python3 fire.py build --formal --no-prove \
        --backend=$a -o .tmp/tl ../new-modular/Mojo/stdlib/std/algorithm/backend/tile.mojo; done
    build: workgroup_function[…](…) calls a name this unit does not compile,
    so the brackets cannot be bound. A comptime specialization's brackets are
    the generic's comptime parameters, and on this path those are ordinary
    leading arguments the call site evaluates and passes first — a decision
    about a signature, which needs a declaration and there is none in hand. If
    `workgroup_function` is a generic of another module then its instantiation
    is the boundary symbol, one per set of type arguments (doc/ABI.md
    §Generics), and this path does not monomorphize, so there is no callee here
    to pass them to; if it is an ordinary value then the brackets are a
    subscript, which is not a call this path can name. Refused rather than
    emitted with the brackets dropped: that builds, runs, and returns a number
    the source never wrote, with nothing on the link line to catch it

Identical on both architectures.

## The shape

`tile.mojo:48` declares the callee as a VALUE:

    workgroup_function: Some[Static1DTileUnitFunc]      # def[width: Int](Int) -> None

and `:83`, `:160`, `:165`, `:218` call it as a specialization:

    workgroup_function[tile_size](current_offset)
    workgroup_function[secondary_cleanup_tile](work_idx, primary_cleanup_tile)
    workgroup_function[tile_size_x, tile_size_y](current_offset_x, current_offset_y)

Two facts make this harder than the `formal/*_mlir` bracket cases: the callee
is not a NAME (it is a parameter holding a function value, so there is no
declaration in hand even in principle — the generic type is written
`Some[Static1DTileUnitFunc]`, in a *field/parameter type*, and this path
resolves parameter types to words); and the brackets carry comptime arguments
that the call site evaluates, so dropping them would silently call the
unparameterised function.

## The 4 files

`tools/formal_sweep_causes.py --min 4 .tmp/sweep-x86-4.txt` counts 4, and 4/4
name something tile declares:

| file | |
|---|---|
| `std/algorithm/backend/tile.mojo` | the refusal itself (`CODEGEN`) |
| `std/algorithm/backend/__init__.mojo` | imports `.tile` |
| `std/algorithm/backend/unswitch.mojo` | imports `.tile` |
| `std/algorithm/__init__.mojo` | imports `.functional` → `.backend` → `.tile` |
| `std/algorithm/functional.mojo` | imports `.backend` → `.tile` |

(the sweep counts 4 dependents plus the file itself; the chain reaches 5
sources in all.)

## Whose

This is GPU code and it sits inside another worker's claim —
`construct:mlir-and-gpu-globals`, whose subject is `std/gpu/**` and the MLIR
dialect constructs, and `workgroup_function` is a GPU launch abstraction. It is
recorded here rather than fixed so that claim is not duplicated and so the 4
files are not counted twice in the `other refusal` row: with `re.mojo` and
`hashlib.mojo` closed by `work/formal-re-refusal`, `tile.mojo` is what is left of
that row's module-caused entries, and it is the smallest of the three.

## Re-verified 2026-10-01 (`work/formal3-7`): the refusal stands, and "Whose"
## above is still the operative section

Measured again rather than assumed, because a refusal that has quietly started
building is the failure this document exists to prevent:

```
$ python3 tools/memslot.py --gb 8 --label tile -- python3 fire.py build \
      --formal --no-prove -o .tmp/esc/tile \
      ../new-modular/Mojo/stdlib/std/algorithm/backend/tile.mojo
build: workgroup_function[…](…) calls a name this unit does not compile, so the
brackets cannot be bound. […]
```

The same refusal, on arm64 (the x86-64 half not repeated this time), so the two
options below are still the two options and neither has been taken.

**And this is still not `formal/`'s to fix**, which is what "Whose" says and
what `tools/control.py claims` confirms: `construct:mlir-and-gpu-globals` is
held by `formal-mlir-gpu`, whose subject is `std/gpu/**` and the MLIR dialect
constructs, and `workgroup_function` is a GPU launch abstraction at
`std/algorithm/backend/tile.mojo:48`. The doc records it so that claim is not
duplicated and so the 4 files are not counted twice in the `other refusal` row.

The one thing a reader should take from the re-verification is negative and
worth stating: nothing has moved, so nothing here is cheaper or more expensive
than it was, and the second option (refuse it in the stdlib, which is a
`new-modular` tree edit outside every worktree here) is still the only one that
is not a construct.

## The next step

One of two, and which one is a decision rather than an implementation:

  * **Bind the brackets to a declared parameter list.** The module already
    writes the declaration — `comptime Static1DTileUnitFunc = def[width:
    Int](Int) -> None` — as a module-level alias of a function TYPE. Reading a
    function type's leading parameters at the call site, and passing the
    bracketed values as ordinary leading arguments, is what the refusal text
    already describes as the right lowering. It needs the call site's knowledge
    that `workgroup_function` has type `Some[Static1DTileUnitFunc]`, which means
    the specialization answer has to be reachable from a PARAMETER's declared
    type and not only from a name's declaration.
  * **Or refuse it in the stdlib.** `tile.mojo` is GPU-only code and every one
    of its 4 dependents is the `algorithm` package's own plumbing; a
    `@parameter`-free spelling (`workgroup_function` called with the width as a
    normal leading argument) is the same program. That is a stdlib edit, and
    the new-modular tree is outside this worktree.

Either way the refusal stays until one of them lands: emitted with the brackets
dropped it would build, run, and return a number the source never wrote.
## Measured 2026-10-03 (`work/formal10-5`): the wall below the brackets is a FUNCTION VALUE

The refusal above is unchanged, on both architectures, byte for byte. What moved
is what a reader is told NEXT, and it is the wall this document's "next step"
runs into.

**A function has no representation on this path at all.** Measured, both
architectures:

```python
def plain(v): return v + 100
def call_it(f, x): return f(x)
def main(n): return call_it(plain, 5)
```

```
build: main: 'plain' is a function of this module read as a VALUE, and there is
no value of a function on this path: a formal value is one 64-bit word, and every
callee this backend reaches is a NAME — a function of this module, a struct's
constructor, a type conversion, or an export on the link line. Nothing here can
call through a word, so the call that would use it has no form. …
```

(The message is `model.function_value_refusal`, landed in the same commit as this
measurement; before it the same program was refused with `'plain' has no home:
the register allocator collected no home for it …`, which names an internal table
instead of the construct. Pinned by `test_formal_specialization.py`'s
`a function read as a value is refused by name`, on both architectures, with a
shadowing local as the negative guard.)

**So the two options at the end of this document are not the two options.** The
first — "bind the brackets to a declared parameter list", reading
`comptime Static1DTileUnitFunc = def[width: Int](Int) -> None` and passing the
bracketed values as leading arguments — is necessary and not sufficient, because
the thing it would pass them to is a WORD this path cannot call through. This
document already says the half of that it could see ("this path resolves
parameter types to words"); what it does not say is that a word naming a
function has no call form either. `workgroup_function` is declared
`Some[Static1DTileUnitFunc]`, so the row needs, in order: a value for a function,
a value for an `Optional` of that value, and then the brackets.

**What that costs the row's estimate, honestly.** Three constructs, not one, and
the first is a language feature this backend has no lowering for at all (no
indirect call exists: every callee is reached by name through `_functions`, a
struct declaration, a dylib export table or a type constructor). The 4 files
below it are still 4 files blocked, and no file of them moves until the first of
the three lands. Anyone picking this up should measure the function-value
question FIRST — it is checkable on a five-line program, which is how it was
measured here — rather than binding brackets.

**And "Whose" needs replacing.** `construct:mlir-and-gpu-globals` is not in
`python3 tools/control.py claims` any more, and `workgroup_function` is a GPU
launch abstraction rather than an MLIR dialect construct, so this row is
unowned work rather than somebody else's. It stays out of the `other refusal`
row's module-caused count for the reason the original author gave — it is not
counted twice — which is still true and is why the row belongs to whoever takes
the function-value question.
