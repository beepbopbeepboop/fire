# `List[T](n)` and `Array[T](x)` ignore their constructor argument; `Array[T]()` + append SIGSEGVs

Found 2026-10-01 while answering "would a fixed-size `Array` help the GPU
offload marshalling?". The answer turned out to be that **there is no working
`Array` in this tree to adopt**, which is worth establishing before anyone plans
around it.

## Status: OPEN, reproduced on current `metal`, unrelated to the GPU work

## What is actually there

`Array` is not defined anywhere. Not in `std/`, not in `fire_compiler.py`:

    $ grep -rn "Array" std/ | grep -E "(struct|class|alias|fn) Array|Array *="
    (nothing)
    $ grep -rn "Array" fire_compiler.py
    (nothing)

It appears in exactly two places, both lists of names the codegen treats
specially — `gimple_codegen.py:3540`'s `_IMPORTED_STRUCT_SKIP_BASENAMES` and the
prelude-symbol list beside it. So `Array[T]` resolves through the *generic
container machinery*, the same path as `List[T]`. `_mojo_type('Array')` returns a
bare `int64_t`, i.e. an opaque handle with no structure behind it.

That is consistent with what it does:

    Array[Float32]()          -> ok, len 0
    Array[Float32](5)         -> ok, len 0     <- argument ignored
    Array[Float32]([1.0,2.0]) -> ok, len 0     <- argument ignored
    List[Float32]()           -> ok, len 0
    List[Float32](5)          -> ok, len 0     <- argument ignored

## Bug 1: the constructor argument is silently ignored, for List too

`List[Float32](3)` yields a **length-0** list. This is not an `Array` quirk —
`List` has it as well, which is why it is filed as a container bug rather than an
`Array` one. Silent, exit 0, wrong answer: a program that sizes a buffer with
`List[Float32](n)` and then indexes `0..n-1` reads out of bounds and gets
whatever is there.

## Bug 2: `Array[T]()` + `append` + read SIGSEGVs

    var a = Array[Float32]()
    for i in range(1024): a.append(Float32(i))
    ... read a[i]                      -> SIGSEGV (exit -11)

`List` does the same sequence correctly (`len` 5, reads back), so this is
specific to `Array`. Reproduced with no offload in the program at all, so it is
not the GPU path.

## Bug 3 (neighbouring, may share a root cause)

`List` append-then-read returns the wrong *values*:

    a = List[Float32](); append(i + 0.5) for i in 0..4
    sum(a)  ->  10.0        expected 12.5

Five appends of `0.5..4.5` do not sum to 10.0. Unreduced; filed alongside
because it is the same shape of silent container wrongness and may be the same
root cause as the per-slot element-kind family in
`CODEGEN_list_element_read_defaults_to_str_across_a_call.md`.

## Why this was looked for

The GPU offload marshalling is bound by per-call buffer traffic, and the idea
was that a **fixed-size** array would help in two ways: a compile-time-known
length removes the per-buffer length side table from the launch marshalling, and
a container that never reallocates has a **stable address**, which is what would
make it sound to cache a device buffer against that address and skip re-uploading
unchanged contents.

Both are real benefits. **Neither is reachable**, because the prerequisite does
not exist: `Array` is a name with no definition behind it, its constructor
argument is discarded, and its one working construction path segfaults. Building
a fixed-size `Array` is a container-layer project of its own, larger than the
GPU work, and it is not a prerequisite that the offload path can assume.

Note the direction that survives without it: the offload runtime already caches
device buffers per argument slot across calls. What it cannot do is skip the
*upload*, because nothing can tell it the host bytes are unchanged. That needs
either a real stable-address buffer or an explicit caller-side "this changed"
signal; both are language/runtime work, and neither is a kernel-codegen change.

## To confirm a fix

    List[Float32](3)          -> len 3
    Array[Float32]([1.0,2.0]) -> len 2
    Array[Float32]() + append + read -> no SIGSEGV, correct values
