"""The one way a module's source becomes the statement list the backend compiles.

Tokenize, parse, rewrite, in that order, with the filename attached for
`file:line:col:` diagnostics. Every site that turns an imported module's file
into statements calls this (bugs/GIR_type_solver.md, step 2), so the whole-closure
type solver and the compile of an import see the same tree.

A leaf module: it imports only `fire_compiler` and `ast_rewriter`, so the backend
(`mojo/backend_gimple/emit_resolve.py`) and the middle tier (`funcs_shared.py`) can
both import it without a cycle.
"""
from __future__ import annotations

import ast_rewriter
from fire_compiler import Parser, py_tokenize


def parse_module_source(source: str, path: str) -> list:
    """The rewritten statements of `source`, the text of the file at `path`."""
    return ast_rewriter.rewrite(Parser(py_tokenize(source)).with_filename(path).parse_module())


def parse_module_file(path: str) -> list:
    """The rewritten statements of the module file at `path`."""
    with open(path, 'r') as f:
        source = f.read()
    return parse_module_source(source, path)
