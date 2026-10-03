# FORMAL_x86_64_dynamic_list_splat_is_refused: `[*xs]` builds on arm64 and is REFUSED on x86-64

**Area:** FORMAL / codegen. Found 2026-10-03 on `work/formal12-x86-parity-audit`
by the arm-vs-x86 construct audit (enumerate the `_emit_*` methods that exist in
`formal/arm64_codegen.py` and not in `formal/x86_64_codegen.py`, then build and
run each construct on both machines). The arm64 half was a silent wrong answer
and is FIXED in `8ad41d9c`; this doc is the x86-64 half, which is a refusal and
therefore the safe direction — it is here because the construct is half a feature
and the asymmetry is not recorded anywhere.

## What was run

    $ cat > .tmp/splat.mojo
    def main():
        var a = [1, 2]
        var b = [*a]
        printf("n=%d %d %d", len(b), b[0], b[1])
        return 0

    $ python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/splat /tmp/splat.mojo
    build: star-unpack of a non-literal into a list is not lowered on the formal x86-64 path

arm64, on the pre-fix tree, built it, ran it, exited 0 and printed `n=0` where
CPython prints `n=2 1 2`. After `8ad41d9c` arm64 prints `n=2 1 2` and matches.

A list literal whose `*` operand is a LITERAL is expanded at compile time and
works on both machines (`[0, *[1, 2], 3]` → `n=4 0 1 2 3`), so this is strictly
about the dynamic spelling: an operand with no compile-time length.

## What is missing, precisely

`formal/x86_64_codegen.py::_emit_list` raises on the non-literal operand:

    for el in elements:
        if isinstance(el, F.UnaryOp) and el.op == "*":
            if isinstance(el.operand, (F.ListExpr, F.TupleExpr)):
                flat.extend(el.operand.elements)
                continue
            raise CodegenError(
                "star-unpack of a non-literal into a list is not "
                "lowered on the formal x86-64 path")

arm64 lowers the same shape in `_emit_list` → `_emit_list_star` →
`_emit_star_splice`: reserve the blob, then append each source element at run
time with `_compr_append_elem`. **The x86-64 backend already has every piece of
that except the loop**: `_compr_append_elem(res_offset, cap)` with the element in
RAX, `_reserve_blob`, `_emit_blob_base`, and a `_while_counter`/label idiom.

**The one thing it does not have is a place to keep the loop's own state.** The
comprehension walk (`_emit_compr_gen`, `formal/x86_64_codegen.py:6086`) keeps its
counter in a NAMED FRAME SLOT — `_ci{d}` / `_cb{d}` — and those names only exist
because `_collect_var_names` (`formal/x86_64_codegen.py:199`, and the
`acc_c`/`walk_compr` pass at :300-306) walks the function's comprehensions and
appends two slots per nesting depth to the frame layout. A splice loop is not a
comprehension, so nothing reserves slots for it, and `_store_var` /
`_load_var` silently do nothing for a name that is not in `_frame_slots` or
`_frame_nested_slots` (`formal/x86_64_codegen.py:1418`, :1431).

## The next step

1. Teach `_collect_var_names` to reserve two slots for a list literal that has a
   non-literal `*` operand (say `_sp{d}` for the source base and `_si{d}` for the
   index, indexed by the same nesting depth the comprehension pass uses), so the
   frame layout knows about them before codegen does.
2. Add `_emit_list_star` / `_emit_star_splice` to `formal/x86_64_codegen.py`,
   mirroring `_emit_compr_gen`'s loop: source base in a frame slot, count read
   from `[base]`, index in the other slot, `setae` + `jne` to the exit label,
   `_emit_elem_addr` for the source element, `_compr_append_elem` for the store.
   The arm64 version is the reference for the SHAPE and the x86-64 version is the
   reference for the register and label discipline; the exit test must be the
   `setae`/`jne` pair, not a `cbz`-style test on the inverted flag, which is the
   bug `8ad41d9c` fixed on arm64.
3. Then delete the `raise` in `_emit_list` and let the dynamic case fall through
   to the new path, keeping the literal-operand expansion as it is.
4. `test_formal_list_splat.py` already accepts either answer per backend — arm64
   must match CPython, and x86-64 may match CPython or refuse naming the
   star-unpack. When step 3 lands, that file's five cases exercise the new path
   on x86-64 with no edit, which is why its x86-64 half is a disjunction and not
   a skip.

**One limit to carry over, not to fix here.** arm64 reserves a fixed 8 slots for
a dynamic operand (`static_n += 8` in `_emit_list_star`), so a source longer
than 8 elements appends past the reservation and `_compr_append_elem`'s capacity
guard `exit(1)`s. Measured: `a = [1..10]; b = [*a]` → exit 1, nothing on stderr.
That cap and the silent guard are the append path's and are shared with every
comprehension (`formal/model.py::list_append_overflow_message` is the text that
was supposed to be printed first, and `_compr_append_elem` does not print it).
Deciding the cap is a frame-budget question, not a lowering one.