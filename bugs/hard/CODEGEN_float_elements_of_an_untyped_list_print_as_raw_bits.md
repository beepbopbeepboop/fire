# CODEGEN: a `for x in <list of floats>` over an iterable of unknown type prints the doubles' raw bits

Residue of the (now removed) dict/list dispatch-arm doc. Its stated crash — the shared loop
variable fixed as the dict arm's `char *`, so `for i in o.read(): print(i)` over `[10, 20]`
SIGSEGV'd — no longer reproduces; `test_reg_dispatched_for_loop.py` pins the int, str and
string-keyed-dict shapes against CPython. What is left is the DOUBLE case.

## Repro (measured 2026-11-05)

    def main():
        d = {"a": [1.5, 2.5], "b": ["u", "v"]}
        for key in ["a", "b"]:
            for x in d[key]:
                print(x)
    main()

CPython: `1.5 2.5 u v`. Compiled: `4609434218613702656 4612811918334230528 u v`.
The same happens for any iterable whose static type is an unknown `int64_t` word that holds a
list of floats (`_gen_for_iter`'s dual dict/list/set dispatch, `emit_loops.py` ~1066-1320).

## Why

The dispatch's list arm reads each element with `mojo_list_get_int`, which returns a double's
raw IEEE-754 bits; the loop variable is a dyn word (`_dyn_word_locals`) and `print` renders it
through `mojo_cstr_or_int_str`, which can only tell a pointer from an integer.

## What was tried, and why it is not the fix

Adding the dispatched list pointer to `gen._maybe_kinds_vals` (so the arm reads through
`mojo_list_get_boxed`, the kind-aware accessor) prints `1.5 2.5` — and turns the int case into
float arithmetic: `for x in q["n"]: print(x + 1)` over `[10, 20]` printed `11.0 21.0`
(CPython `11 21`), because a boxed loop target then goes through
`ginf._float_param_arith` (`mojo_box_double(x) + (double)1`, always a double). That trades a
rare wrong value for a common one, so it was reverted.

## Next step

Make the read kind-aware without declaring the target a float-possible word: either a
`mojo_list_get_dyn` that boxes only a `'d'` slot and returns every other slot's bare word, with
the target registered in `_tagged_word_vals` so `_tagged_arith_select` (select by box kind at
run time, int answer beside an int) applies instead of `_float_param_arith`; or a per-list
runtime test choosing a boxed arm only when the list actually carries a non-int slot. Pin with
the program above plus the `int_elements_keep_int_arithmetic` case already in
`test_reg_dispatched_for_loop.py` (it must keep printing `11 21`).
