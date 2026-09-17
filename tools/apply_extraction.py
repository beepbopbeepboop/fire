#!/usr/bin/env python3
"""Apply a function-extraction batch to gimple_codegen.py.

Reads a JSON spec: {output_module: {"doc": str, "alias": str, "names": [...]}}
For each module: extracts the named GimpleGen methods as module-level
functions (via tools/extract_family.py against EXTRACT_REF, default the
pristine pre-extraction commit), deletes them from the class (decorator-
aware spans), and appends delegating methods preserving decorators and
@staticmethod semantics.

Idempotent: names already delegating to the same alias are skipped.
"""
import ast
import copy
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

CODEGEN = 'gimple_codegen.py'
ALIASES = {'gmp', 'ggc', 'gst', 'glo', 'gfn', 'gex', 'gcc_', 'gca', 'ginf', 'grsl'}


def first_params(path):
    t = ast.parse(open(path).read())
    out = {}
    for f in t.body:
        if isinstance(f, ast.FunctionDef):
            out[f.name] = f.args.args[0].arg if f.args.args else None
    return out


def is_delegate(node, alias=None):
    if len(node.body) != 1 or not isinstance(node.body[0], ast.Return):
        return False
    r = node.body[0].value
    if not (isinstance(r, ast.Call) and isinstance(r.func, ast.Attribute)
            and isinstance(r.func.value, ast.Name)):
        return False
    return alias is None or r.func.value.id == alias


def main(spec_path):
    spec = json.load(open(spec_path))
    src = open(CODEGEN).read()
    L = src.split('\n')
    tree = ast.parse(src)
    ggen = next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == 'GimpleGen')

    # index current class members
    cur = {}
    for node in ggen.body:
        if isinstance(node, ast.FunctionDef):
            cur[node.name] = node

    env = dict(os.environ)
    env.setdefault('EXTRACT_REF', 'c66e79a')

    all_delegates = []   # (module_alias, name)
    for out_path, cfg in spec.items():
        alias = cfg['alias']
        names = []
        for n in cfg['names']:
            node = cur.get(n)
            if node is None:
                names.append(n)
            elif is_delegate(node, alias):
                continue                      # already extracted to this module
            else:
                names.append(n)
        if not names:
            print(out_path, ': nothing to do')
            continue

        r = subprocess.run(
            ['python3', os.path.join(HERE, 'extract_family.py'), 'x'] + sorted(names),
            capture_output=True, text=True, env=env)
        assert r.returncode == 0, (out_path, r.stderr[-1500:])
        body = r.stdout.rpartition('__DELEGATES__')[0]
        dj = json.loads(r.stdout.rpartition('__DELEGATES__')[2])

        hdr = open(out_path).read().split('\n\nclass ')[0] if os.path.exists(out_path) else ''
        if not hdr or 'Function-extraction architecture' not in hdr:
            hdr = (f'"""{cfg["doc"]}\n\n'
                   'Function-extraction architecture: former GimpleGen methods as\n'
                   'module-level functions taking `gen` first; delegates remain on\n'
                   'the class; cross-module references are qualified.\n"""\n')
            # canonical import block (mirrors sibling modules)
            hdr += IMPORT_BLOCK.format(extra=cfg.get('imports', ''))

        text = hdr.rstrip('\n') + '\n\n' + body.strip('\n') + '\n'
        open(out_path, 'w').write(text)
        ast.parse(open(out_path).read())

        for d in dj:
            d['alias'] = alias
            all_delegates.append(d)
        print(out_path, ': extracted', len(dj))

    # delete + insert delegates
    byname = {d['name']: d for d in all_delegates}
    spans, prev, dec = [], 0, 0
    for node in ggen.body:
        if isinstance(node, ast.FunctionDef) and node.name in byname:
            s = node.lineno - 1
            if node.decorator_list:
                s = min(s, min(x.lineno - 1 for x in node.decorator_list))
                dec += 1
            e = node.end_lineno
            while s > prev and (L[s-1].startswith('#') or L[s-1].strip() == ''):
                s -= 1
            spans.append((s, e))
            prev = e
        else:
            prev = max(prev, getattr(node, 'end_lineno', 0))
    for s, e in sorted(spans, reverse=True):
        del L[s:e]

    t2 = ast.parse('\n'.join(L))
    gg2 = next(n for n in t2.body
               if isinstance(n, ast.ClassDef) and n.name == 'GimpleGen')
    at = max(getattr(x, 'end_lineno', x.lineno) for x in gg2.body)
    ins = []
    mods = {}
    for d in all_delegates:
        mods.setdefault(d['alias'], []).append(d)
    for alias, ds in mods.items():
        ins.append(f"\n    # ---- delegates via {alias} ----\n")
        for d in ds:
            sig = re.sub(r'\(', '(self, ', d['sig'], count=1) \
                if not d['sig'].split('(')[1].startswith('self') else d['sig']
            sig = sig.replace('(self, self,', '(self,').replace('(self, self)', '(self)')
            call = d['call']
            call = re.sub(r'^self, ', '', call) if False else call
            ins.append(f"    {sig}:\n        return {alias}.{d['name']}({call})\n")
    L2 = '\n'.join(L).split('\n')
    for i, tline in enumerate(ins):
        L2.insert(at + i, tline.rstrip('\n'))
    out = '\n'.join(L2)

    imports_needed = ' '.join(sorted(mods.keys()))
    i = out.index('\nclass GimpleGen:')
    existing = out[:i]
    add = ''
    mod_of = {cfg['alias']: p for p, cfg in spec.items()}
    for alias in sorted(mods.keys()):
        mod = mod_of[alias]
        base = os.path.basename(mod)[:-3]
        stmt = f'import {base} as {alias}'
        if stmt not in existing:
            add += '\n' + stmt
    out = out[:i] + add + out[i:]
    ast.parse(out)
    open(CODEGEN, 'w').write(out)
    print('delegates inserted:', len(all_delegates), '| decorated:', dec)


IMPORT_BLOCK = """from __future__ import annotations

import os
import re

from fire_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,
    EllipsisLiteral, NoneLiteral,
    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt, DelStmt, MatchStmt,
    StructDef, TraitDef,
    YieldExpr, YieldFromExpr, AwaitExpr,
)
import regex_compile
import mlir
import gimple_ctypes
import gimple_solvers
import gimple_exprtypes
import gimple_codegen
import gimple_gen_methods as gmp
import gimple_gen_calls as ggc{extra}
"""


if __name__ == '__main__':
    main(sys.argv[1])
