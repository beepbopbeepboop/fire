"""STy to C (bugs/GIR_type_solver.md, 2.4): the one place a solved source type becomes a C type.

This is the only mapping from the solver's lattice to a spelling. It takes the
backend's `gen` only for `_resolve_type`, which knows a struct's emitted C name.
When GIR stage 4 (one type vocabulary) lands, this returns a `mojo.ir.types.Type`
instead of a string; that changes this file only.
"""
from __future__ import annotations

from mojo.tsolve import sty


def ret_ctype(gen, t) -> str:
    """The C return type of a solved source type `t`."""
    k = t.kind
    if k == 'bot' or k == 'none':
        return 'void'
    if k == 'bool':
        return '_Bool'
    if k == 'float':
        return 'double'
    if k == 'str':
        return 'char *'
    if k == 'list' or k == 'tuple':
        return 'MojoList *'
    if k == 'dict':
        return 'MojoDict *'
    if k == 'set':
        return 'MojoSet *'
    if k == 'struct':
        return gen._resolve_type(t.name)
    # int, func and dyn all lower to the boxed word.
    return 'int64_t'
