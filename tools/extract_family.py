#!/usr/bin/env python3
"""Extract a family of GimpleGen methods into a module-level function file.

Function-extraction architecture (REF.html §8b path 1). Reads the method
sources from git HEAD's gimple_codegen.py, transforms each to a module-level
function taking `gen` as first parameter, and prints the generated module
body plus delegate definitions for insertion by the caller.

Usage: extract_family.py <output_module_docstring_file> <name1> <name2> ...
The transformed functions are written to stdout; delegates (signature +
forwarding call) are written to stderr as JSON.
"""
import ast
import copy
import builtins
import re
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mojo.middle.types as gimple_ctypes  # noqa: E402
import mojo.middle.solvers as gimple_solvers  # noqa: E402
import mojo.middle.exprtypes as gimple_exprtypes  # noqa: E402
import fire_compiler  # noqa: E402

CT = {n for n in dir(gimple_ctypes) if not n.startswith('__')}
SV = {n for n in dir(gimple_solvers) if not n.startswith('__')}
ET = {n for n in dir(gimple_exprtypes) if not n.startswith('__')}
MC = {n for n in dir(fire_compiler) if not n.startswith('_')}
HEADER_DEFINED = MC | CT | SV | ET | {
    'os', 're', 'regex_compile', 'dataclasses', 'zlib', 'hashlib', 'sys',
    'gimple_ctypes', 'gimple_solvers', 'gimple_exprtypes', 'gimple_codegen'}
BUILTIN = set(dir(builtins)) | {'__file__'}


def local_names(fn):
    a = fn.args
    loc = {p.arg for p in a.posonlyargs + a.args + a.kwonlyargs}
    loc |= {x.arg for x in ast.walk(fn) if isinstance(x, ast.arg)}
    if a.vararg:
        loc.add(a.vararg.arg)
    if a.kwarg:
        loc.add(a.kwarg.arg)
    for x in ast.walk(fn):
        if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            loc.add(x.id)
        elif isinstance(x, (ast.FunctionDef, ast.ClassDef)):
            loc.add(x.name)
        elif isinstance(x, ast.Import):
            loc.update(a.asname or a.name.split('.')[0] for a in x.names)
        elif isinstance(x, ast.ImportFrom):
            loc.update(a.asname or a.name for a in x.names)
        elif isinstance(x, ast.ExceptHandler) and x.name:
            loc.add(x.name)
        elif isinstance(x, ast.Global):
            loc.update(x.names)
        elif isinstance(x, ast.comprehension):
            for t in ast.walk(x.target):
                if isinstance(t, ast.Name):
                    loc.add(t.id)
    return loc


def main():
    names = set(sys.argv[2:])
    ref = os.environ.get('EXTRACT_REF', 'HEAD')
    orig = subprocess.run(['git', 'show', f'{ref}:gimple_codegen.py'],
                          capture_output=True, text=True).stdout
    L0 = orig.split('\n')
    tree = ast.parse(orig)
    ggen = next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == 'GimpleGen')

    funcs, delegates = [], []
    prev_end = 0
    for node in ggen.body:
        if not (isinstance(node, ast.FunctionDef) and node.name in names):
            continue
        s = node.lineno - 1
        e = node.end_lineno
        while s > prev_end and (L0[s-1].startswith('#') or L0[s-1].strip() == ''):
            s -= 1
        prev_end = e

        body = '\n'.join(ln[4:] if ln.startswith('    ') else ln
                         for ln in L0[s:e])
        fn = ast.parse(body).body[0]
        has_self = bool(fn.args.args) and fn.args.args[0].arg == 'self'
        taken = local_names(fn) - {'self'}
        pname = next((c for c in ('gen', '_g', '_gc', '_gctx') if c not in taken), '_gctx')
        if has_self:
            fn.args.args[0].arg = pname
        ren = ([(x.lineno, x.col_offset, x.end_col_offset) for x in ast.walk(fn)
                if isinstance(x, ast.Name) and x.id == 'self'] if has_self else [])
        bl = body.split('\n')
        for ln, c0, c1 in sorted(ren, key=lambda t: (-t[0], -t[1])):
            line = bl[ln-1]
            bl[ln-1] = line[:c0] + pname + line[c1:]
        b2 = '\n'.join(bl)

        fn2 = ast.parse(b2).body[0]
        loc = local_names(fn2)
        leaf = CT | SV | ET
        r1 = [(x.lineno, x.col_offset, x.end_col_offset,
               'gimple_ctypes' if x.id in CT else
               'gimple_solvers' if x.id in SV else 'gimple_exprtypes')
              for x in ast.walk(fn2)
              if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)
              and x.id in leaf and x.id not in loc]
        b3 = b2.split('\n')
        for ln, c0, c1, mod in sorted(r1, key=lambda t: (-t[0], -t[1])):
            line = b3[ln-1]
            b3[ln-1] = line[:c0] + mod + '.' + line[c0:]

        fn3 = ast.parse('\n'.join(b3)).body[0]
        known = local_names(fn3) | HEADER_DEFINED | BUILTIN | {pname}
        r2 = [x for x in ast.walk(fn3)
              if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)
              and x.id not in known and x.id != node.name]
        for x in sorted(r2, key=lambda t: (-t.lineno, -t.col_offset)):
            line = b3[x.lineno-1]
            b3[x.lineno-1] = line[:x.col_offset] + 'gimple_codegen.' + line[x.col_offset:]
        final = '\n'.join(b3)
        final = re.sub(r'^(def \w+)\(self,', '\\1(' + pname + ',', final, count=1, flags=re.M)
        final = re.sub(r'^(def \w+)\(self\)', r'\1(gen)', final, count=1, flags=re.M)
        ast.parse(final)
        # Post-fix: compiled List.index(tuple) arg mismatch in comptime-elif
        # (see git history "enumerate rewrite in comptime-elif").
        final = final.replace(
            "if elifs.index((elif_cond, elif_body)) < len(elifs) - 1 or has_else:",
            "if _elif_idx < len(elifs) - 1 or has_else:")
        final = final.replace(
            "for elif_cond, elif_body in elifs:",
            "for _elif_idx, (elif_cond, elif_body) in enumerate(elifs):")
        ast.parse(final)
        funcs.append(final)

        args = copy.deepcopy(node.args)
        d = ast.FunctionDef(name=node.name, args=args, body=[ast.Pass()],
                            decorator_list=[], returns=node.returns,
                            type_comment=None, type_params=[])
        ast.fix_missing_locations(d)
        sigtxt = ast.unparse(ast.Module(body=[d], type_ignores=[]))
        sig = sigtxt[:sigtxt.rindex(':')]
        a = node.args
        parts = (['self'] + [p.arg for p in (a.posonlyargs + a.args)[1:]]) if has_self \
            else [p.arg for p in (a.posonlyargs + a.args)]
        parts += [f'{dd.arg}={dd.arg}' for dd in a.kwonlyargs]
        if a.vararg:
            parts.append(f'*{a.vararg.arg}')
        if a.kwarg:
            parts.append(f'**{a.kwarg.arg}')
        delegates.append({'name': node.name, 'sig': sig,
                          'call': ', '.join(parts), 'span': [s, e]})

    found = {d['name'] for d in delegates}
    missing = names - found
    assert not missing, f"not found in GimpleGen: {sorted(missing)}"

    print('\n\n'.join(f.rstrip() for f in funcs))
    import json
    print('\n__DELEGATES__' + json.dumps(delegates))


if __name__ == '__main__':
    main()
