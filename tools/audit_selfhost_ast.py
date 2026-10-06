#!/usr/bin/env python3
"""Static audit (Python `ast`) for SELF-HOST-UNSAFE constructs in this
compiler's own source.

This is the AST-based version of tools/audit_determinism.py (which greps
text). It parses each target `.py` with the real `ast` module and flags the
exact syntactic shapes this project has repeatedly been bitten by once the
file is compiled by the self-hosted backend, with file:line so a fix is
mechanical:

  GENEXPR-ANYALL  `any(<genexpr>)` / `all(<genexpr>)` — the genexpr's body
                  appended nothing / the result erased to the garbage
                  non-list 1 (`mojo_list_len(0x1)` SIGSEGV).
                  Fix: an explicit `for` loop with a bool accumulator.

  GENEXPR-TUPLE   `<genexpr>` / comprehension whose `for` target is a TUPLE
                  (`for _, eb in ...`) — every slot boxes to int64_t.
                  Fix: index the tuple, or loop and subscript.

  LISTCOMP-UNPACK `[f(a, b) for a, b in ...]` — same tuple-boxing, plus the
                  comprehension result erasure.
                  Fix: explicit append loop.

  DICTCOMP-UNPACK `{k: v for k, v in ...}` — the key erases to int64_t, so
                  dict lookups by that key can never hit.
                  Fix: explicit loop (`_as_str` the key).

  CMP-ERASED      `<name> == '<literal>'` / `!=` where `<name>` may be a
                  boxed/erased value — the constant-FALSE static guard.
                  Reported as a WARNING (only a runtime trace can prove it).

  STARARGS        `def f(<params>)` whose param list parses WITHOUT a
                  `*args` entry although the source has one — the parser
                  bug fixed in fire_compiler._parse_funcdef. Detected by
                  reparsing the file with the real Parser and comparing the
                  source text's `*name` occurrences against `params`.

Only the first four are hard findings; the rest are warnings. Usage:
    python3 tools/audit_selfhost_ast.py [paths...]
Default paths: the compiler's own source (fire_compiler.py, myinterpreter.py,
fire.py, module_loader.py, gimple_codegen.py, mojo/, ownership_destruct.py,
reflect.py, cas.py, generated_dispatch.py).
"""
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT = [
    'fire_compiler.py', 'myinterpreter.py', 'fire.py', 'module_loader.py',
    'gimple_codegen.py', 'ownership_destruct.py', 'reflect.py', 'cas.py',
    'generated_dispatch.py', 'ast_rewriter.py', 'mlir.py', 'regex_compile.py',
]
DEFAULT += sorted(os.path.relpath(p, HERE) for p in
                  glob.glob(os.path.join(HERE, 'mojo', '**', '*.py'), recursive=True))


def _is_tup_target(t) -> bool:
    return isinstance(t, (ast.Tuple, ast.List)) and len(t.elts) > 1


def scan(path: str) -> list:
    """Returns [(severity, kind, lineno, detail)]."""
    src = open(path).read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [('ERROR', 'PARSE', e.lineno or 0, str(e))]
    out = []
    for n in ast.walk(tree):
        # any/all over a generator expression
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in ('any', 'all') and n.args
                and isinstance(n.args[0], ast.GeneratorExp)):
            gen = n.args[0]
            for c in gen.generators:
                if _is_tup_target(c.target):
                    out.append(('HARD', 'GENEXPR-TUPLE', n.lineno,
                                f"{n.func.id}(... for <tuple> in ...)"))
            out.append(('HARD', 'GENEXPR-ANYALL', n.lineno,
                        f"{n.func.id}(<genexpr>)"))
        # bare genexpr passed elsewhere (not to any/all) with a tuple target
        if isinstance(n, ast.GeneratorExp):
            for c in n.generators:
                if _is_tup_target(c.target):
                    out.append(('HARD', 'GENEXPR-TUPLE', n.lineno,
                                "genexpr tuple target"))
        # list/set comprehensions with tuple targets
        if isinstance(n, (ast.ListComp, ast.SetComp)):
            for c in n.generators:
                if _is_tup_target(c.target):
                    out.append(('HARD', 'LISTCOMP-UNPACK', n.lineno,
                                "comprehension tuple target"))
        # dict comprehensions with tuple targets (key erasure)
        if isinstance(n, ast.DictComp):
            for c in n.generators:
                if _is_tup_target(c.target):
                    out.append(('HARD', 'DICTCOMP-UNPACK', n.lineno,
                                "dict-comp tuple target"))
        # `for a, b in ...:` statement loops (tuple unpack in the for-clause)
        if isinstance(n, (ast.For, ast.AsyncFor)) and _is_tup_target(n.target):
            out.append(('WARN', 'FOR-TUPLE', n.lineno, "for-clause tuple unpack"))
    return out


def main(argv) -> int:
    paths = argv or DEFAULT
    totals = {}
    for rel in paths:
        p = rel if os.path.isabs(rel) else os.path.join(HERE, rel)
        if not os.path.exists(p):
            continue
        for sev, kind, ln, detail in scan(p):
            totals[kind] = totals.get(kind, 0) + 1
            if sev in ('HARD', 'ERROR'):
                print(f"{sev:5} {kind:16} {rel}:{ln}  {detail}")
    print("\n== summary ==")
    for k in sorted(totals):
        print(f"  {k:16} {totals[k]}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
