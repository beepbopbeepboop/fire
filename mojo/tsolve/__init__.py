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

    def knows(self, path: str, name: str) -> bool:
        """True when `name` in module `path` is a definition the closure has."""
        return func_key(path, name) in self.prog.fns

    def definition(self, path: str, name: str):
        """The FunctionDef the closure defines for `name` in `path`, or None."""
        fs = self.prog.fns.get(func_key(path, name))
        if fs is None:
            return None
        return fs.node

    def is_annotated(self, path: str, name: str) -> bool:
        """True when the closure defines `name` with an annotated return (4.4)."""
        fs = self.prog.fns.get(func_key(path, name))
        return fs is not None and fs.annotated_ret

    def why_none(self, path: str, name: str) -> str:
        """Why `ret_sty` answers None for `name` in module `path`: '' when it answers,
        else `not-defined`, `undecidable`, `annotated` or `bot` (no value reaches a return)."""
        fs = self.prog.fns.get(func_key(path, name))
        if fs is None:
            return 'not-defined'
        if not fs.decidable:
            return 'undecidable'
        if fs.annotated_ret:
            return 'annotated'
        if self.prog.vars[fs.ret].kind == 'bot':
            return 'bot'
        if self.has_bot_return(fs):
            return 'bot-return'
        return ''

    def has_bot_return(self, fs) -> bool:
        """True when some return site evaluates to `bot`: a value the solver knows nothing
        about leaves the function there, and joining without it would drop it (4.3)."""
        for t in fs.ret_terms:
            if _solve.eval_term(self.prog, t).kind == 'bot':
                return True
        return False

    def ret_sty(self, path: str, name: str):
        """The solved return type of `name` in module `path`, as an STy.

        None unless the function is in the closure, decidable, UNANNOTATED, and
        has an answer (a `bot` answer is no answer: nothing reached its return)."""
        fs = self.prog.fns.get(func_key(path, name))
        if fs is None or not fs.decidable or fs.annotated_ret:
            return None
        t = self.prog.vars[fs.ret]
        if t.kind == 'bot' or self.has_bot_return(fs):
            return None
        return t

    def ret_ctype(self, gen, path: str, name: str):
        """The C return type for `name` in module `path`, or None (see `ret_sty`)."""
        t = self.ret_sty(path, name)
        if t is None:
            return None
        return lower.ret_ctype(gen, t)


def solve_closure(root_path: str, root_stmts: list, loader) -> Solution:
    """`loader` is an object whose `resolve(ref, importer)` returns a ModuleFile or None."""
    prog = _summarize.summarize_closure(root_path, root_stmts, loader)
    _solve.solve(prog)
    return Solution(prog)
