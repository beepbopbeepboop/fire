# CODEGEN (A3 default coroutine path): a bytes value yielded by a generator prints as its address

Found 2026-11-12 while fixing `CODEGEN_coro_a3_os_path_split_empty_head_truthy.md`.
The truthiness half is fixed (see that doc's Status); this is the printing half.

## Repro (measured)

    import os

    def g_split(pathname):
        dirname, basename = os.path.split(pathname)
        if not dirname:
            yield basename
            return
        yield dirname
        yield basename

    def main():
        for n in g_split(b'a/b.py'):
            print(n)

Build with `python3 fire.py build <file> -o <exe>` (default coroutine path, no
`MOJO_CORO`) and run.

- Expected (CPython, and what the bytes parts are): `b'a'` then `b'b.py'`.
- Measured: two decimal integers, e.g. `4326011088` / `4326015776` — the
  bytes object's address.

Generator values of an untyped (word) argument are str OR bytes; the str
case prints correctly (`a`, `b.py`) because the runtime's `mojo_repr_boxed`
recognises a live str pointer, but a registered bytes object is printed as a
plain int.

## What is wrong

Generated C for the consumer (`_gimple_main`, from `compile_to_gimple`):

    _t6 = __mgco_g_split_value (_t2);
    n = _t6;                              /* int64_t: no word-kind marking */
    _t7 = mojo_repr_boxed (n);            /* a raw word, not a box */

The loop variable `n` is typed `int64_t` and is not added to
`gen._dyn_word_locals`, so the print lowers to `mojo_repr_boxed(n)`, which
treats a raw word as an integer. The generator side agrees: its yields are
inferred `w` (word of unknown kind, `mojo/middle/coro.py` `_yield_kind` gives
`w` for the split pair's elements), and `_yield_shim('w')` is
`__mojo_coro_yield_i`, i.e. the raw word goes out with no kind information.

The tagged-word machinery (`mixed_slots`, `_tagged_generator_iterable`,
`mojo_list_append_word`, which classifies a registered bytes word as
`MOJO_KIND_BYTES`) covers a `for` over a generator only on the list-collect
path in `emit_infra.py` (~line 4587); the plain `for n in g(...)` loop does not
route a `w` value through it.

## Next step

1. Decide where the kind is carried. Two candidate fixes, both real:
   (a) consumer: a `for` over a generator whose value kind is `w` binds the
       loop target as a dyn word (`gen._dyn_word_locals`) and prints it via
       the runtime's kind-aware repr (the same path an untyped-param word
       takes), or
   (b) producer: a `w` yield boxes a registered bytes/str word
       (`mojo_box_from_*`) the way it already boxes floats/bools/None
       (`coro.py` ~line 5126), so `mojo_repr_boxed` renders it.
   (b) matches the existing `w`-yield design (box by static kind so the
   consumer can tell it apart); prefer (b) unless it breaks a box consumer.
2. Land it; the quick test is `test_os_path_split_word_truthy.py` with the
   two `print(n)` cases restored for `b'*.py'` / `b'a/b.py'` (expected lines
   `b'*.py'` only for `b'*.py'`, and `b'a'`, `b'b.py'` for `b'a/b.py'`).
   Compare against CPython output of the same source.
3. Delete this doc and the coro doc in the commit where that test passes, and
   run `python3 tools/dangling_doc_refs.py --ratchet`.
