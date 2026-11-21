"""The builder: the lowering code CALLS a statement shape instead of
spelling it as C text (doc/GIR.md, stage 2b).

Every function here appends one `Instr` to `gen.body_lines`; the four
function-assembly sites print the list (`Instr.line()`).  A statement built
here is a shape the verifier can read, not a string nobody type-checks.

Operands are still C spellings ("_t41", "(int64_t)_t7", "0LL"): the coercion
that decides WHICH operands to pass lives in the backend's `_rt_args`,
`_binop_text` and friends, and stage 4 is what turns those spellings into
`Type`s.  What moves here is the statement, one family per step:

  copies and casts   copy, cast_into        (emit_resolve._copy/_cast_into)
  arithmetic         binop_into             (emit_resolve._binop_into)
  calls              call_into, call_void   (emit_resolve._rt_call/_rt_into/
                                             _rt_void, emit_infra._emit_call)
  labels             label                  (emit_resolve._emit_label)
  everything else    raw                    (emit_infra._emit_raw)
                                             the adapter for a statement no
                                             family has claimed yet

`raw` is the floor and only shrinks: a lowering site that calls `gen._emit`
is counted by test_type_string_ratchet.py, and a site that calls one of these
is not.

This module is in the compiler's own import closure, so it stays in the
self-hostable subset (doc/GIR.md rule 2): plain functions and classes, every
field annotated in `__init__`, no closures, no lambdas, no `re`, no tuple
unpacking, no `getattr`, no generators.
"""
from __future__ import annotations

from mojo.ir.instr import Ex, Instr, ex_var
from mojo.ir.types import type_named


def raw(gen, text: str) -> Instr:
    """Append a line no statement family models yet, printed verbatim.

    `text` carries its own indentation and may be one line of a statement
    that lowers to several (`if (x) {`, `free (p);`, `}`), a `#line`
    directive, or a comment.  This is the adapter that shrinks; `_emit_raw`
    is its only backend caller."""
    i = _opaque(text)
    append(gen, i)
    return i


def append(gen, instr: Instr) -> None:
    """Append `instr` to the body being lowered, stamped with the `#line`
    directive of the innermost source statement (the rule the text emitter
    used to apply on its own)."""
    d = gen._stmt_line_directive
    if d:
        text = instr.line()
        if text.strip() and not text.lstrip().startswith('#'):
            gen.body_lines.append(_opaque(d))
    gen.body_lines.append(instr)


def copy(gen, dst: str, src: str, cast_to: str = '') -> None:
    """`dst = src;`, or `dst = (T) src;` when the two representations differ.

    `cast_to` is the destination's C type when the caller established that
    the copy needs the conversion written out, or '' for a plain copy."""
    rhs = ex_var(src)
    if cast_to:
        rhs = _cast_ex(cast_to, rhs)
    append(gen, _assign(ex_var(dst), rhs))


def cast_into(gen, dst: str, ctype: str, val: str) -> None:
    """`dst = (ctype) val;` into an existing variable declared `ctype`."""
    append(gen, _assign(ex_var(dst), _cast_ex(ctype, ex_var(val))))


def binop_into(gen, dst: str, a: str, op: str, b: str) -> None:
    """`dst = a op b;` for arithmetic, a bit operation or a comparison."""
    append(gen, _assign(ex_var(dst), _bin_ex(a, op, b)))


def call_into(gen, dst: str, fname: str, args: list) -> None:
    """`dst = fname (args);` -- a call whose result is stored in `dst`.

    `args` are already-coerced argument spellings, one per parameter."""
    append(gen, _assign(ex_var(dst), _call_ex(fname, args)))


def call_void(gen, fname: str, args: list) -> None:
    """`fname (args);` -- a call made for its effect."""
    i = Instr('expr')
    i.rhs = _call_ex(fname, args)
    append(gen, i)


def label(gen, name: str, freq_hint: str = '') -> None:
    """`name:` on a line of its own, after a blank line.

    A label opens a basic block, so it is never stamped with the source
    directive of the statement that follows it. `freq_hint` is the loop's
    estimated trip count, which the backend prints as a trailing comment."""
    i = Instr('label')
    i.label = name
    if freq_hint:
        i.text = '  /* ' + freq_hint + ' */'
    gen.body_lines.append(i)


def _opaque(text: str) -> Instr:
    i = Instr('opaque')
    i.text = text
    return i


def _cast_ex(ctype: str, inner: Ex) -> Ex:
    e = Ex('cast')
    e.ty = type_named(ctype)
    e.a = inner
    return e


def _bin_ex(a: str, op: str, b: str) -> Ex:
    e = Ex('bin')
    e.op = op
    e.a = ex_var(a)
    e.b = ex_var(b)
    return e


def _call_ex(fname: str, args: list) -> Ex:
    e = Ex('call')
    e.a = ex_var(fname)
    parts: list = []
    for a in args:
        parts.append(ex_var(a))
    e.args = parts
    return e


def _assign(lhs: Ex, rhs: Ex) -> Instr:
    i = Instr('assign')
    i.lhs = lhs
    i.rhs = rhs
    return i
