#!/usr/bin/env python3
"""Mechanically rewrite `any(<genexpr>)` / `all(<genexpr>)` into an explicit
loop, for the self-host-unsafe constructs tools/audit_selfhost_ast.py reports.

The genexpr forms erase to the garbage non-list 1 on the self-hosted path
(`mojo_list_len(0x1)` SIGSEGV), so they must become:

    <any>  ->  _sh_saw = False
               for <targets> in <iterable>:
                   [if <cond>: pass]
                   if <elt>:
                       _sh_saw = True
                       break
    <all>  ->  _sh_saw = True
               for <targets> in <iterable>:
                   [if <cond>: pass]
                   if not <elt>:
                       _sh_saw = False
                       break

Only the SIMPLE, single-generator, no-`is`-tests genexpr shape is rewritten
(that is the overwhelming majority and the crash class); anything with
multiple `for` clauses or `if` clauses inside the genexpr is LEFT ALONE and
reported, so a human makes the call.

Usage:
    python3 tools/fix_genexpr_anyall.py [--dry-run] [paths...]
"""
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import subprocess

TARGETS = subprocess.run(
    [sys.executable, os.path.join(HERE, 'tools', 'audit_selfhost_ast.py')],
    capture_output=True, text=True).stdout


def targets() -> list:
    out = []
    for line in TARGETS.splitlines():
        if 'GENEXPR-ANYALL' in line and ':' in line:
            loc = line.split()[2]
            out.append(loc)
    return out


def fix_file(path: str, dry: bool) -> int:
    src = open(path).read()
    lines = src.split('\n')
    tree = ast.parse(src)
    # collect (start_line0, end_line0, replacement_lines) for simple cases
    edits = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in ('any', 'all') and n.args
                and isinstance(n.args[0], ast.GeneratorExp)):
            continue
        gen = n.args[0]
        if len(gen.generators) != 1 or gen.generators[0].ifs:
            continue  # imperfect shape -> leave for a human
        c = gen.generators[0]
        tgt = ast.get_source_segment(src, c.target)
        it = ast.get_source_segment(src, c.iter)
        elt = ast.get_source_segment(src, gen.elt)
        if tgt is None or it is None or elt is None:
            continue
        s, e = n.lineno - 1, n.end_lineno  # [s, e) lines of the whole call
        # Preserve the leading indentation + any prefix on the first line and
        # the trailing suffix on the last line (the call is usually a whole
        # condition or a boolean sub-expression, so require a clean span).
        first = lines[s]
        last = lines[e - 1]
        indent = first[:len(first) - len(first.lstrip())]
        prefix = '' if n.col_offset == len(indent) else None
        suffix = last[n.end_col_offset:]
        if prefix is None:
            # mid-expression call (e.g. `x and any(...)`) -> skip
            continue
        cond = 'if not ' + elt if n.func.id == 'all' else 'if ' + elt
        seed = 'True' if n.func.id == 'all' else 'False'
        body = [f"{indent}_sh_saw = {seed}", f"{indent}for {tgt} in {it}:"]
        body.append(f"{indent}    {cond}:")
        body.append(f"{indent}        _sh_saw = {not (n.func.id == 'all') and True or (n.func.id != 'all') and 'True' or 'False'}")
        # ^ placeholder replaced below with real value
        body[-1] = (f"{indent}        _sh_saw = True" if n.func.id == 'any'
                    else f"{indent}        _sh_saw = False")
        body.append(f"{indent}        break")
        replacement = body
        # re-attach any trailing text that followed the call on its last line
        if suffix:
            replacement.append(f"{indent}{suffix}")
        edits.append((s, e, replacement))
    if not edits:
        return 0
    for s, e, rep in sorted(edits, reverse=True):
        lines[s:e] = rep
    if not dry:
        open(path, 'w').write('\n'.join(lines))
    return len(edits)


def main(argv) -> int:
    dry = '--dry-run' in argv
    argv = [a for a in argv if a != '--dry-run']
    paths = argv or sorted(set(t.split(':')[0] for t in targets()))
    total = 0
    for rel in paths:
        p = rel if os.path.isabs(rel) else os.path.join(HERE, rel)
        if not os.path.exists(p):
            continue
        n = fix_file(p, dry)
        if n:
            print(f"{'[dry] ' if dry else ''}{rel}: {n} rewritten")
            total += n
    print(f"total: {total}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
