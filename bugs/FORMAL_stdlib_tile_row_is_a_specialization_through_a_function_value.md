# `algorithm/backend/tile.mojo`: a specialization call through a FUNCTION-VALUE field, and 4 stdlib files behind it

**Area:** FORMAL (comptime specialization on a callee this unit does not
compile). Found 2026-10-01 on `work/formal-re-refusal` while working the
`other refusal` row. **NOT FIXED, and it is not this branch's to fix** — see
"Whose" below.

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