# The resumable-iterator CURSOR: one registry, one set of accessors.
#
# `it = iter(<container>)` is a real single-pass iterator in Mojo/Python, and
# modelling it as a bare identity (the container, re-scanned from element 0 on
# every use) is wrong in a way no later pass can repair. So the binding lowers
# to the container plus a companion `int64_t` cursor temp, and every later use
# of that local — `next(it)`, `next(it, default)`, `for x in it:`, `len(it)`,
# `it.__next__()`, `[... for x in it]` — has to agree about what that cursor
# means.
#
# It is here, in the middle tier, because there are SIX such consumers spread
# over four back-end files (`emit_stmts` binds it; `emit_calls` reads it three
# ways; `emit_loops` reads it once; `emit_infra` reads it once), and
# `emit_infra` — which owns the registry's own creation in `_reset_func` —
# IMPORTS `emit_calls`, so it cannot be imported back. A helper in any back-end
# file would therefore have to be duplicated or reached through a cycle. Every
# read of `gen._list_iter_cursor` outside this module goes through these
# functions, which is what keeps the length, the element read, and the
# exhaustion test from drifting apart.
#
# The record. `gen._list_iter_cursor[cname]` is a dict with:
#
#   'kind'   'list' | 'span' — the container's storage, and nothing else. It
#            selects the element READ below; it is not a general tag, and a
#            third kind is not expected: every container this codegen gives a
#            real length AND a real indexed read is either a `MojoList *`
#            (the runtime's `mojo_list_len` / `mojo_list_get_*`) or a struct
#            with the `{_data, _len}` sugar shape the tree already recognises
#            in `emit_calls._struct_data_field` (Span, StringSlice, and the
#            stdlib's own byte-buffer structs).
#   'src'    the C expression holding the container (always a local's name).
#   'cursor' the `int64_t` temp: the index of the next UNCONSUMED element.
#   'full'   a C expression for the container's TOTAL length, read at BIND
#            time rather than at each use. Caching it is not an optimization:
#            a `for` loop body may append to the very container it is
#            iterating, and re-reading `mojo_list_len` per condition would then
#            walk into the appended tail — a different (and silently
#            different-answer) program.
#   'elem'   the element's C type, or None when nothing tracked one (a raw
#            byte buffer), in which case reads are byte/int-shaped.
#   'data'   for 'span', the `(field, ctype)` of the `_data`/`data` sugar
#            field; absent for 'list'.
#   'vct'    the C type ONE ELEMENT reads as — what `next(it)` returns and what
#            a `for` target is declared. Derived once, from 'elem', so the
#            consumers cannot each compute a different answer.
#
# Self-host note, because it is a constraint on this file and not a style
# preference: the self-hosted compiler compiles this source, so nothing here
# may be a generator, a default argument, or a name whose value came out of a
# `set` iteration. Every value interpolated into an f-string is therefore
# hoisted into a local and passed through `_as_str` first — the boxed-name
# hazard the back-end files spell out at length (e.g.
# `_compr_list_loop`'s "the returned temp NAME is erased to int64_t on the
# self-hosted path").
from __future__ import annotations

import mojo.middle.types as gimple_ctypes
from fire_compiler import _as_str


def cursor_for(gen, cname):
    """The cursor record for a C name, or None when it is not a cursor local."""
    return getattr(gen, '_list_iter_cursor', {}).get(cname)


def slot_ctype(elem):
    """The C type one element of element-type `elem` reads as. `None` (nothing
    tracked), a `void` element and the two special representations all land
    somewhere this codegen can hold: a byte buffer with no tracked element type
    reads as `int64_t` per element, exactly the reading `_lower_subscript`'s
    struct-pointer arm has always given such a span. The split between the
    representations lives in `read_at`, not here."""
    if elem == 'double':
        return 'double'
    if elem == 'char *':
        return 'char *'
    return 'int64_t'


def element_ctype(rec):
    """The C type one element of this cursor reads as."""
    return rec.get('vct') or 'int64_t'


def read_at(gen, rec, idx):
    """`(vct, c_expr)` for the element at `idx`, WITHOUT emitting anything.

    The caller owns the emission because `next()` needs the read inside one
    basic block with its own result temp, while a `for` loop reads directly
    into its target. Both ask this one question, so they cannot answer it
    differently.

    A 'list' cursor reads through the runtime's per-slot accessor, whose
    SUFFIX carries the element's representation — the same `list_suffix`
    choice `_lower_next_iter_cursor` and `_gen_for_iter_cursor` each used to
    make separately. A 'span' cursor reads through the tree's own
    `_mojo_at_<T>` scaled-arithmetic helper and dereferences it, registering
    the element type so the helper is emitted: the same two steps
    `_lower_subscript`'s struct-pointer arm already performs for `span[i]`, so
    no second pointer-arithmetic convention is introduced here. An untracked
    span element falls back to the `_data` field's own C element type, which
    for a byte buffer is `char`.
    """
    vct = element_ctype(rec)
    if rec.get('kind') == 'span':
        _data = rec['data']
        _src = _as_str(rec['src'])
        _idx = _as_str(idx)
        elem = rec.get('elem') or gimple_ctypes._elem_type(_data[1])
        if elem == 'void':
            elem = 'char'
        gen._ptr_helpers_needed.add(elem)
        et_ptr = elem + ' *'
        cn = gimple_ctypes._c_id(elem)
        idx64 = _as_str(gen._new_val('int64_t', f"(int64_t) {_idx}"))
        addr = gen._new_val(
            et_ptr, f"_mojo_at_{cn} (({et_ptr}){_src}->{_data[0]}, {idx64})")
        # No cast to `vct` here: for a struct-typed element that cast is not C,
        # and for a scalar one the dereference already has the element type.
        return vct, gen._new_val(vct, f"(*{_as_str(addr)})")
    _src2 = _as_str(rec['src'])
    _idx2 = _as_str(idx)
    suf = (gimple_ctypes.TypeLattice.list_suffix(rec['elem'])
           if rec.get('elem') else 'int')
    return vct, gen._new_val(vct, f"mojo_list_get_{suf} ({_src2}, {_idx2})")


def remaining(gen, rec):
    """A temp holding how many elements are UNCONSUMED: `full - cursor`,
    floored at 0.

    This is what `len(it)` means for a partially consumed iterator, and it is
    the one thing the previous implementation got wrong on the LIST cursor too:
    `len()` dispatched on the local's storage type and answered
    `mojo_list_len(it)` — the container's total length, unchanged by every
    `next()` — so `len(it)` after consuming all of `[1,2,3,4,5]` said 5.
    Silent, exit 0, and wrong in the direction a caller notices last.
    """
    _full = _as_str(rec['full'])
    _cur = _as_str(rec['cursor'])
    total = gen._new_temp('int64_t')
    gen._emit(f"  {total} = {_full};")
    left = gen._new_temp('int64_t')
    gen._emit(f"  {left} = {total} - {_cur};")
    zero = gen._new_val('int64_t', "(int64_t)0")
    over = gen._new_temp('_Bool')
    gen._emit(f"  {over} = {left} < {zero};")
    out = gen._new_temp('int64_t')
    bb_neg = gen._new_bb(); bb_ok = gen._new_bb(); bb_merge = gen._new_bb()
    gen._emit(f"  if ({over}) goto {bb_neg}; else goto {bb_ok};")
    gen._emit_label(bb_neg)
    gen._emit(f"  {out} = {zero};")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_ok)
    gen._emit(f"  {out} = {left};")
    gen._emit(f"  goto {bb_merge};")
    gen._emit_label(bb_merge)
    return out