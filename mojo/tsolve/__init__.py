"""The whole-closure type solver (bugs/GIR_type_solver.md).

`solve_closure(root_path, root_stmts, load)` summarizes the import closure of
a program, solves it once, and answers every function's return type. Nothing
here imports the backend (`mojo/backend_gimple`); the only compiler module it
uses is `fire_compiler` for the AST node classes. `lower.py` takes the backend's
`gen` as a parameter and calls only `gen._resolve_type`.
"""
from __future__ import annotations

from mojo.tsolve import lower
from mojo.tsolve import solve as _solve
from mojo.tsolve import summarize as _summarize
from mojo.tsolve.summary import func_key


class Solution:
    """The answers of one solve. Built by `solve_closure` and never mutated."""

    def __init__(self, prog):
        self.prog: object = prog

    def ret_sty(self, path: str, name: str):
        """The solved return type of `name` in module `path`, as an STy.

        None unless the function is in the closure, decidable, UNANNOTATED, and
        has an answer (a `bot` answer is no answer: nothing reached its return)."""
        fs = self.prog.fns.get(func_key(path, name))
        if fs is None or not fs.decidable or fs.annotated_ret:
            return None
        t = self.prog.vars[fs.ret]
        if t.kind == 'bot':
            return None
        return t

    def ret_ctype(self, gen, path: str, name: str):
        """The C return type for `name` in module `path`, or None (see `ret_sty`)."""
        t = self.ret_sty(path, name)
        if t is None:
            return None
        return lower.ret_ctype(gen, t)


def solve_closure(root_path: str, root_stmts: list, load) -> Solution:
    prog = _summarize.summarize_closure(root_path, root_stmts, load)
    _solve.solve(prog)
    return Solution(prog)
