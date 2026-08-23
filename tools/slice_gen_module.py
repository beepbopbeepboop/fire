#!/usr/bin/env python3
"""Slice GimpleGen.gen_module into hoisted phase functions (v3, scope-aware).

Spec JSON: [{"name": str, "start": int, "end": int}, ...] — 1-based inclusive
statement indices partitioning gen_module's top-level body.

Each range becomes `def <name>(self, _ctx)` in gimple_module_gen.py. Names
whose binding escapes the phase (used across phases / trailing code, or via
nested-def closures/nonlocal) are rewritten to `_ctx.<name>`. Scoping rules:
nested FunctionDef/Lambda/ClassDef/comprehensions bind locally; free reads
and nonlocal/global writes of nested defs count toward the enclosing phase.
"""
import ast
import json
import sys

CODEGEN = 'gimple_codegen.py'
OUT = 'gimple_module_gen.py'
MOD_ALIAS = 'gmg'


def scoped_rw(stmts, initial_bound=frozenset()):
    """(reads, writes): names referenced/bound escaping to the enclosing
    scope of `stmts`. Properly handles nested defs/lambdas/classes/
    comprehensions/except-as/global-nonlocal."""
    FR, FW = set(), set()

    def params_of(a):
        out = {p.arg for p in (a.posonlyargs + a.args + a.kwonlyargs)}
        if a.vararg:
            out.add(a.vararg.arg)
        if a.kwarg:
            out.add(a.kwarg.arg)
        return out

    def walk(n, bound):
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, (ast.Store, ast.Del)):
                if n.id in bound:
                    return
                # first binding at this scope: binds here AND is an escape-write
                FW.add(n.id)
                bound.add(n.id)
            else:
                if n.id not in bound:
                    FR.add(n.id)
            return
        if isinstance(n, ast.Nonlocal):
            for nm in n.names:
                FR.add(nm)
                FW.add(nm)
            return
        if isinstance(n, ast.Global):
            for nm in n.names:
                FR.add(nm)
                FW.add(nm)
            return
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                walk(d, bound)
            for dflt in list(n.args.defaults) + [x for x in n.args.kw_defaults if x]:
                walk(dflt, bound)
            inner = set(bound) | {n.name} | params_of(n.args)
            for st in n.body:
                walk(st, inner)
            return
        if isinstance(n, ast.Lambda):
            for dflt in list(n.args.defaults) + [x for x in n.args.kw_defaults if x]:
                walk(dflt, bound)
            inner = set(bound) | params_of(n.args)
            walk(n.body, inner)
            return
        if isinstance(n, ast.ClassDef):
            for d in n.decorator_list:
                walk(d, bound)
            for b in n.bases:
                walk(b, bound)
            for kw in n.keywords:
                walk(kw.value, bound)
            inner = set(bound) | {n.name}
            for st in n.body:
                walk(st, inner)
            return
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            inner = set(bound)
            for gn in n.generators:
                walk(gn.iter, bound)
                for t in ast.walk(gn.target):
                    if isinstance(t, ast.Name):
                        inner.add(t.id)
                    elif isinstance(t, (ast.Tuple, ast.List)):
                        for e in ast.walk(t):
                            if isinstance(e, ast.Name):
                                inner.add(e.id)
                for c in gn.ifs:
                    walk(c, inner)
            if isinstance(n, ast.DictComp):
                walk(n.key, inner)
                walk(n.value, inner)
            else:
                walk(n.elt, inner)
            return
        if isinstance(n, ast.ExceptHandler):
            if n.type:
                walk(n.type, bound)
            b2 = set(bound)
            if n.name:
                b2.add(n.name)
            for st in n.body:
                walk(st, b2)
            return
        for ch in ast.iter_child_nodes(n):
            walk(ch, bound)

    for st in stmts:
        walk(st, set(initial_bound))
    return FR, FW


def globals_declared(stmts):
    g = set()
    for n in stmts:
        for x in ast.walk(n):
            if isinstance(x, ast.Global):
                g.update(x.names)
    return g


def main(spec_path):
    spec = json.load(open(spec_path))
    src = open(CODEGEN).read()
    L = src.split('\n')
    tree = ast.parse(src)
    ggen = next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == 'GimpleGen')
    gm = next(x for x in ggen.body
              if isinstance(x, ast.FunctionDef) and x.name == 'gen_module')
    body = gm.body
    N = len(body)

    cursor = 1
    for ph in spec:
        assert ph['start'] == cursor and ph['end'] >= ph['start'], ph
        cursor = ph['end'] + 1
    assert cursor == N + 1

    gm_params = {a.arg for a in gm.args.args}

    RW = []
    for node in body:
        r, w = scoped_rw([node])
        RW.append((r, w))
    glob_by_phase = [globals_declared(body[ph['start'] - 1:ph['end']])
                     for ph in spec]

    # cross-phase names per phase: touch ∩ anything bound outside the phase
    phase_cross = []
    for j, ph in enumerate(spec):
        lo_i, hi_i = ph['start'] - 1, ph['end']
        touch = set()
        for k in range(lo_i, hi_i):
            touch |= RW[k][0] | RW[k][1]
        outside = set()
        for k in range(N):
            if lo_i <= k < hi_i:
                continue
            r, w = scoped_rw([body[k]])
            outside |= r | w
        tail_txt = 'class _T:\n' + '\n'.join(L[body[-1].end_lineno:])
        for x in ast.walk(ast.parse(tail_txt)):
            if isinstance(x, ast.Name):
                outside.add(x.id)
            elif isinstance(x, ast.arg):
                outside.add(x.arg)
    # A name rides ctx iff it is touched in MORE THAN ONE region (phase or
    # trailing code). Imported globals of gimple_codegen and builtins
    # resolve fine as globals and never ride ctx.
    import builtins as _bi
    mod_globals = set(dir(_bi))
    for n2 in tree.body:
        if isinstance(n2, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            mod_globals.add(n2.name)
        elif isinstance(n2, ast.Assign):
            for t2 in n2.targets:
                for x2 in ast.walk(t2):
                    if isinstance(x2, ast.Name):
                        mod_globals.add(x2.id)
        elif isinstance(n2, ast.AnnAssign) and isinstance(n2.target, ast.Name):
            mod_globals.add(n2.target.id)
        elif isinstance(n2, ast.Import):
            for a2 in n2.names:
                mod_globals.add(a2.asname or a2.name.split('.')[0])
        elif isinstance(n2, ast.ImportFrom):
            for a2 in n2.names:
                mod_globals.add(a2.asname or a2.name)
    mod_globals |= {'_ctx', 'gmg', 'self'}

    tail_txt2 = 'class _T:\n' + '\n'.join(L[body[-1].end_lineno:])
    name_regions = {}
    for j, ph in enumerate(spec):
        lo_i, hi_i = ph['start'] - 1, ph['end']
        for k in range(lo_i, hi_i):
            for nm in RW[k][0] | RW[k][1]:
                if nm in mod_globals:
                    continue
                name_regions.setdefault(nm, set()).add(j)
    for x in ast.walk(ast.parse(tail_txt2)):
        if isinstance(x, ast.Name) and x.id not in mod_globals:
            name_regions.setdefault(x.id, set()).add(len(spec))

    phase_cross = []
    for j, ph in enumerate(spec):
        lo_i, hi_i = ph['start'] - 1, ph['end']
        cross = set()
        for k in range(lo_i, hi_i):
            for nm in RW[k][0] | RW[k][1]:
                regs = name_regions.get(nm, set())
                if len(regs - {j}) >= 1:
                    cross.add(nm)
        phase_cross.append(sorted(cross))

    cuts = [body[ph['start'] - 1].lineno for ph in spec]
    cuts.append(body[-1].end_lineno)

    new_modules = []
    head_lines = L[:cuts[0] - 1]

    hdr = ('"""gen_module phase functions.\n\nHoisted verbatim by '
           'tools/slice_gen_module.py; shared state rides on _ctx.\n"""\n'
           'from __future__ import annotations\n'
           '\nimport os\nimport re\nimport sys\n'
           '\nfrom mojo_compiler import (\n'
           '    IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral,\n'
           '    EllipsisLiteral, NoneLiteral,\n'
           '    IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr,\n'
           '    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,\n'
           '    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension,\n'
           '    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,\n'
           '    ReturnStmt, RaiseStmt,\n'
           '    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,\n'
           '    ImportStmt, FromImportStmt,\n'
           '    IfStmt, WhileStmt, ForStmt,\n'
           '    FunctionDef, TryStmt, WithStmt,\n'
           '    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,\n'
           '    GlobalStmt, DelStmt, MatchStmt,\n'
           '    StructDef, TraitDef,\n'
           '    YieldExpr, YieldFromExpr, AwaitExpr,\n'
           '    py_tokenize, Parser,\n'
           ')\n'
           'from module_loader import load_module, get_symbol_type\n'
           'import ast_rewriter\n'
           'import mlir\n'
           'import regex_compile\n'
           'import gimple_ctypes\n'
           'import gimple_solvers\n'
           'import gimple_exprtypes\n'
           'import gimple_codegen\n'
           'from gimple_exprtypes import _walk_ast\n'
           '\n'
           '\ndef __getattr__(name):'
           '\n    # Remaining gen_module-era module globals resolve against the'
           '\n    # host module lazily (avoids import-order cycles).'
           '\n    import gimple_codegen as _gc'
           '\n    return getattr(_gc, name)\n'
           )

    for j, ph in enumerate(spec):
        lo, hi = cuts[j], cuts[j + 1] - 1
        seg = L[lo - 1:hi]
        cross = set(phase_cross[j]) - glob_by_phase[j]

        seg_src = '\n'.join(l[8:] if l.startswith('        ') else l.lstrip()
                            for l in seg)
        seg_ast = ast.parse(seg_src)

        # Scope-aware substitution: a cross name is rewritten to
        # _ctx.<name> ONLY where it resolves to the phase/gen_module scope.
        # Nested defs/lambdas/classes/comprehensions/except-as introduce
        # bindings that shadow it (e.g. _scan_for_closures's own
        # `outer_name` parameter must stay a plain local).
        class ScopeAwareSub(ast.NodeTransformer):
            def __init__(self, cross):
                self.cross = set(cross)
                self.bound = {'self', '_ctx'}

            def _params(self, a):
                out = {p.arg for p in (a.posonlyargs + a.args + a.kwonlyargs)}
                if a.vararg:
                    out.add(a.vararg.arg)
                if a.kwarg:
                    out.add(a.kwarg.arg)
                return out

            def visit_FunctionDef(self, n):
                for d in n.decorator_list:
                    self.visit(d)
                for dflt in list(n.args.defaults) + \
                        [x for x in n.args.kw_defaults if x]:
                    self.visit(dflt)
                saved = self.bound
                self.bound = saved | {n.name} | self._params(n.args)
                for st in n.body:
                    self.visit(st)
                self.bound = saved
                return n

            def visit_AsyncFunctionDef(self, n):
                return self.visit_FunctionDef(n)

            def visit_Lambda(self, n):
                for dflt in list(n.args.defaults) + \
                        [x for x in n.args.kw_defaults if x]:
                    self.visit(dflt)
                saved = self.bound
                self.bound = saved | self._params(n.args)
                self.visit(n.body)
                self.bound = saved
                return n

            def visit_ClassDef(self, n):
                for d in n.decorator_list:
                    self.visit(d)
                for b in n.bases:
                    self.visit(b)
                for kw in n.keywords:
                    self.visit(kw.value)
                saved = self.bound
                self.bound = saved | {n.name}
                for st in n.body:
                    self.visit(st)
                self.bound = saved
                return n

            def _comp(self, n):
                saved = self.bound
                for gn in n.generators:
                    self.visit(gn.iter)
                    t_saved = self.bound
                    for t in ast.walk(gn.target):
                        if isinstance(t, ast.Name):
                            self.bound = self.bound | {t.id}
                        elif isinstance(t, (ast.Tuple, ast.List)):
                            for e in ast.walk(t):
                                if isinstance(e, ast.Name):
                                    self.bound = self.bound | {e.id}
                    for c in gn.ifs:
                        self.visit(c)
                    self.bound = t_saved
                if isinstance(n, ast.DictComp):
                    self.visit(n.key)
                    self.visit(n.value)
                else:
                    self.visit(n.elt)
                self.bound = saved
                return n

            visit_ListComp = _comp
            visit_SetComp = _comp
            visit_GeneratorExp = _comp
            visit_DictComp = _comp

            def visit_ExceptHandler(self, n):
                if n.type:
                    self.visit(n.type)
                saved = self.bound
                if n.name:
                    self.bound = self.bound | {n.name}
                for st in n.body:
                    self.visit(st)
                self.bound = saved
                return n

            def visit_Name(self, n):
                if n.id in self.cross and n.id not in self.bound:
                    return ast.copy_location(
                        ast.Attribute(value=ast.Name(id='_ctx', ctx=ast.Load()),
                                      attr=n.id, ctx=n.ctx), n)
                return n

            def visit_Nonlocal(self, n):
                return None

        sub = ScopeAwareSub(cross)
        sub.bound = {'self', '_ctx'}
        seg_ast = sub.visit(seg_ast)

        # publish cross-phase function/class defs into ctx right after their
        # definition so later phases resolve them via _ctx
        new_body = []
        for nd in seg_ast.body:
            new_body.append(nd)
            nm = getattr(nd, 'name', None)
            if isinstance(nd, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and nm in cross:
                new_body.append(ast.parse(
                    f"_ctx.{nm} = {nm}").body[0])
        seg_ast.body = new_body
        ast.fix_missing_locations(seg_ast)
        seg_txt = ast.unparse(seg_ast)

        fn = [f"def {ph['name']}(self, _ctx):"]

        # names referenced by this phase that resolve against gimple_codegen
        # module globals (e.g. _merge_struct_inheritance): import them
        # lazily INSIDE the function so the codegen<->module_gen import
        # cycle never matters (by call time codegen is fully loaded).
        hdr_ast = ast.parse(hdr)
        header_names = set()
        for h2 in ast.walk(hdr_ast):
            if isinstance(h2, ast.Name):
                header_names.add(h2.id)
            elif isinstance(h2, ast.alias):
                header_names.add(h2.asname or h2.name.split('.')[0])
        local_bound = set()
        for x2 in ast.walk(seg_ast):
            if isinstance(x2, ast.Name) and isinstance(x2.ctx, (ast.Store, ast.Del)):
                local_bound.add(x2.id)
            elif isinstance(x2, ast.arg):
                local_bound.add(x2.arg)
            elif isinstance(x2, ast.Import):
                for a3 in x2.names:
                    local_bound.add(a3.asname or a3.name.split('.')[0])
            elif isinstance(x2, ast.ImportFrom):
                for a3 in x2.names:
                    local_bound.add(a3.asname or a3.name)
        for x2 in ast.walk(seg_ast):
            if isinstance(x2, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local_bound.add(x2.name)
            elif isinstance(x2, ast.ExceptHandler) and x2.name:
                local_bound.add(x2.name)
        unresolved = set()
        for x2 in ast.walk(seg_ast):
            if isinstance(x2, ast.Name):
                nm2 = x2.id
                if (nm2 not in local_bound and nm2 not in header_names
                        and nm2 not in dir(__builtins__) and nm2 != 'self'
                        and nm2 != '_ctx'):
                    unresolved.add(nm2)
        # drop ctx-qualified ones (they were rewritten to attributes already,
        # so surviving bare Names are genuinely non-ctx)
        unresolved -= set(cross)
        if unresolved:
            fn.append(f"    from gimple_codegen import {', '.join(sorted(unresolved))}")

        fn += ['    ' + l if l else '' for l in seg_txt.split('\n')]
        new_modules.append('\n'.join(fn).rstrip() + '\n')

    # first-touch seeding (params of gen_module are visible from the start)
    first_touch = {}
    for j, ph in enumerate(spec):
        lo_i, hi_i = ph['start'] - 1, ph['end']
        for nm in phase_cross[j]:
            for k in range(lo_i, hi_i):
                if nm in RW[k][0] or nm in RW[k][1]:
                    first_touch.setdefault(nm, j)
                    break
    seed_pre = sorted(nm for nm, j0 in first_touch.items()
                      if any(nm in RW[k][0] or nm in RW[k][1]
                             for k in range(0, spec[j0]['start'] - 1))
                      or nm in gm_params)

    need_back = sorted(set().union(*[set(c) for c in phase_cross]) & set())
    # restrict need_back to names actually read by trailing code
    tail_txt = 'class _T:\n' + '\n'.join(L[body[-1].end_lineno:])
    tail_all = {x.id for x in ast.walk(ast.parse(tail_txt))
                if isinstance(x, ast.Name)}
    need_back = sorted(set(need_back) & tail_all)

    gm_lines = list(head_lines)
    gm_lines.append("        from types import SimpleNamespace as _NS")
    gm_lines.append("        _ctx = _NS()")
    for nm in sorted(set(seed_pre) | (set(need_back) & gm_params)):
        gm_lines.append(f"        _ctx.{nm} = {nm}")
    gm_lines.append("        # Phases (hoisted verbatim to gimple_module_gen.py):")
    for ph in spec:
        gm_lines.append(f"        {MOD_ALIAS}.{ph['name']}(self, _ctx)")
    for nm in need_back:
        gm_lines.append(f"        {nm} = _ctx.{nm}")
    gm_lines += L[cuts[-1]:]

    open(OUT, 'w').write(hdr + '\n\n'.join(m.rstrip('\n') for m in new_modules) + '\n')

    out = '\n'.join(gm_lines)
    anchor_imp = 'import gimple_gen_methods as gmp\n'
    out = out.replace(anchor_imp,
                      anchor_imp + f'import gimple_module_gen as {MOD_ALIAS}\n', 1)
    ast.parse(out)
    open(CODEGEN, 'w').write(out)
    print("modules:", [ph['name'] for ph in spec])
    print("codegen:", len(out.split('\n')), "| module_gen:",
          len(open(OUT).read().split('\n')))


if __name__ == '__main__':
    main(sys.argv[1])
