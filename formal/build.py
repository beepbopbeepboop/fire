"""formalbuild — formal arm64 codegen + Mach-O emission, selected by
`./fire.py formalbuild <file.mojo>`.

Pipeline:
    source → fire_compiler.py tokenize/parse (the real AST)
           → formal.arm64_codegen.ARM64Codegen (machine code)
           → formal.macho.build_macho (MH_EXECUTE Mach-O64 / ARM64)
           → formal.arm64_proof_gen.generate_arm64_proof (Lean 4, opt-in)

Unlike the toy formal tree (which had its own parser and mini-AST), this
path parses with fire_compiler — fire_compiler.py is the single source of
truth for the AST in this project. Proof generation consumes the same
fire AST via aliases (no AST-to-AST translation).
"""

import os
from types import SimpleNamespace

import fire_compiler as F
from formal.arm64_codegen import ARM64Codegen, CodegenError
from formal.macho import build_macho, compute_macho_got_addrs
from formal.macho_linker import EXTERN_ENTRYOFF, TEXT_BASE
from mojo.middle.closures import discover_closures


class FormalBuildError(Exception):
    pass


def parse_module(source: str, filename: str = "<input>") -> list:
    from fire_compiler import py_tokenize, Parser
    return Parser(py_tokenize(source)).with_filename(filename).parse_module()


def _synthetic_main() -> F.FunctionDef:
    """Trivial `def main(): return 0` for sources with no top-level FunctionDef.

    A module that is only imports / constants / classes / module-level
    statements is a valid formal input (build.py's _extract_functions
    documents that surface as accepted-and-ignored); it just has nothing to
    lower. Emitting a real entry keeps the Mach-O startup path intact and
    matches the arm64 codegen contract that functions[0] is what the
    startup stub BLs — without inventing lowers for the ignored toplevel."""
    stmts = parse_module("def main():\n    return 0\n", filename="<synthetic-main>")
    for s in stmts:
        if isinstance(s, F.FunctionDef) and s.name == "main":
            return s
    raise FormalBuildError("synthetic main failed to parse")



class FormalClosureCtx:
    """TypeCtx for shared closure discovery on the formal arm64 path.

    No C/GIMPLE typing: every type collapses to int64_t. Optional
    selfhost_param_ctype is omitted (GIMPLE-only).
    """

    def __init__(self):
        self.var_types = {}
        self.func_return_types = {}
        self.struct_field_types = {}
        self._func_param_defaults = {}
        self._nested_async_api = {}
        self._method_threaded_comptime_params = {}
        self.current_func_name = ""
        self._all_closures = {}

    def _quick_type(self, expr):
        return "int64_t"

    def _resolve_type(self, ptype):
        return "int64_t"

    def _infer_return_type(self, body):
        return "int64_t"

    def _struct_method_overload_ids(self, s):
        return [""] * len(s.methods)


def _rewrite_closures_in_body(body, visible_keys, closures):
    """Rewrite CallExprs to nested defs: prepend by-value captures, rename lifted."""
    if not body:
        return
    for stmt in body:
        _rewrite_closures_in_stmt(stmt, visible_keys, closures)


def _rewrite_closures_in_stmt(stmt, visible_keys, closures):
    # Recurse into statement bodies first/along with exprs.
    if stmt is None:
        return
    # Common body-bearing statements
    for attr in ("body", "then_body", "else_body", "orelse", "finally_body"):
        sub = getattr(stmt, attr, None)
        if isinstance(sub, list):
            _rewrite_closures_in_body(sub, visible_keys, closures)
    elifs = getattr(stmt, "elifs", None)
    if elifs:
        for _c, b in elifs:
            _rewrite_closures_in_body(b, visible_keys, closures)
    handlers = getattr(stmt, "handlers", None)
    if handlers:
        for h in handlers:
            _rewrite_closures_in_body(getattr(h, "body", None), visible_keys, closures)
    items = getattr(stmt, "items", None)
    # WithStmt has body already handled; MatchStmt cases
    cases = getattr(stmt, "cases", None)
    if cases:
        for c in cases:
            _rewrite_closures_in_body(getattr(c, "body", None), visible_keys, closures)
    # FunctionDef nested: skip — flatten removes them before rewrite of parent
    # (we rewrite after strip, or skip FunctionDef here)
    if isinstance(stmt, F.FunctionDef):
        return
    # Expressions that may contain calls
    _rewrite_closures_in_exprs_on_stmt(stmt, visible_keys, closures)


def _rewrite_closures_in_exprs_on_stmt(stmt, visible_keys, closures):
    # Assign-like: value, target (target won't have calls usually)
    for attr in ("value", "iterable", "condition", "subject", "test"):
        e = getattr(stmt, attr, None)
        if e is not None and not isinstance(e, list):
            _rewrite_closures_in_expr(e, visible_keys, closures)
    # MultiAssign targets list + value
    targets = getattr(stmt, "targets", None)
    if isinstance(targets, list):
        for t in targets:
            _rewrite_closures_in_expr(t, visible_keys, closures)
    # Return/Raise handled via value
    # CallExpr as ExprStmt.value handled via value
    # Binary/Compare operands etc: deep rewrite via generic expr walker
    # For statements that ARE expressions (ExprStmt) or have .value we did value.
    # Also ForStmt.iterable done. IfStmt.condition done.
    # Try/With don't have top-level exprs beyond body.
    # AssertStmt.value done.
    # AugAssign: value + target
    # Match patterns skip.


def _rewrite_closures_in_expr(expr, visible_keys, closures):
    if expr is None or isinstance(expr, (str, int, float, bool)):
        return
    # Call?
    if isinstance(expr, F.CallExpr):
        # Rewrite args first (nested calls)
        for a in list(expr.args):
            _rewrite_closures_in_expr(a, visible_keys, closures)
        for _k, kv in list(expr.kwargs or []):
            _rewrite_closures_in_expr(kv, visible_keys, closures)
        # Target?
        if isinstance(expr.func, F.IdentExpr):
            name = expr.func.name
            ci = None
            for key in visible_keys:
                inner_map = closures.get(key) or {}
                if name in inner_map:
                    ci = inner_map[name]
                    break
            if ci is not None:
                expr.func = F.IdentExpr(ci.lifted_name)
                if ci.captures:
                    cap_args = [F.IdentExpr(cn) for cn, _ct in ci.captures]
                    expr.args = cap_args + list(expr.args)
        else:
            _rewrite_closures_in_expr(expr.func, visible_keys, closures)
        return
    if isinstance(expr, F.MemberExpr):
        _rewrite_closures_in_expr(expr.obj, visible_keys, closures)
        return
    if isinstance(expr, F.BinaryOp):
        _rewrite_closures_in_expr(expr.left, visible_keys, closures)
        _rewrite_closures_in_expr(expr.right, visible_keys, closures)
        return
    if isinstance(expr, F.UnaryOp):
        _rewrite_closures_in_expr(expr.operand, visible_keys, closures)
        return
    if isinstance(expr, F.CompareChain):
        for opnd in (expr.operands or []):
            _rewrite_closures_in_expr(opnd, visible_keys, closures)
        return
    if isinstance(expr, F.TernaryExpr):
        _rewrite_closures_in_expr(expr.condition, visible_keys, closures)
        _rewrite_closures_in_expr(expr.then_val, visible_keys, closures)
        _rewrite_closures_in_expr(expr.else_val, visible_keys, closures)
        return
    if isinstance(expr, F.SubscriptExpr):
        _rewrite_closures_in_expr(expr.obj, visible_keys, closures)
        _rewrite_closures_in_expr(expr.index, visible_keys, closures)
        return
    if isinstance(expr, F.ListExpr):
        for e in expr.elements:
            _rewrite_closures_in_expr(e, visible_keys, closures)
        return
    if isinstance(expr, F.TupleExpr):
        for e in expr.elements:
            _rewrite_closures_in_expr(e, visible_keys, closures)
        return
    if isinstance(expr, F.SetExpr):
        for e in expr.elements:
            _rewrite_closures_in_expr(e, visible_keys, closures)
        return
    if isinstance(expr, F.DictExpr):
        for k, v in expr.pairs:
            _rewrite_closures_in_expr(k, visible_keys, closures)
            _rewrite_closures_in_expr(v, visible_keys, closures)
        return
    if isinstance(expr, F.LambdaExpr):
        _rewrite_closures_in_expr(expr.body, visible_keys, closures)
        return
    if isinstance(expr, F.WalrusExpr):
        _rewrite_closures_in_expr(expr.value, visible_keys, closures)
        return
    if isinstance(expr, F.AwaitExpr):
        _rewrite_closures_in_expr(expr.value, visible_keys, closures)
        return
    # Unknown expr type: leave (formal will error later if it matters)


def _flatten_closures(functions, closures):
    """Strip nested FunctionDefs, lift with by-value capture params, rewrite calls.

    Returns a flat FunctionDef list (originals with nested defs removed +
    lifted defs renamed to ci.lifted_name with captures prepended as params).
    """
    # First pass: find all ClosureInfos and prepare lifted FunctionDefs
    lifted_defs = []  # (ci, parent_visible_keys_after_lift)

    def prepare(fn, visible_keys):
        """Strip nested defs from fn (any depth via control-flow bodies);
        queue lifted children. visible_keys are closure-map keys whose
        nested names are visible inside fn."""
        key_children = []
        unregistered = []

        def strip_body(body):
            out = []
            for stmt in body or []:
                if isinstance(stmt, F.FunctionDef):
                    ci = None
                    for key in visible_keys:
                        inner_map = closures.get(key) or {}
                        if stmt.name in inner_map:
                            ci = inner_map[stmt.name]
                            break
                    if ci is None:
                        # Not registered (async nested, etc.) — still lift
                        # so the parent body has no nested FunctionDef.
                        unregistered.append(stmt)
                        continue
                    key_children.append(ci)
                    continue
                # Recurse into control-flow statement lists (nested defs
                # inside if/for/while/try/with are registered the same way;
                # the old direct-children-only walk left them in place).
                for attr in ("body", "then_body", "else_body"):
                    sub = getattr(stmt, attr, None)
                    if isinstance(sub, list):
                        setattr(stmt, attr, strip_body(sub))
                elifs = getattr(stmt, "elifs", None)
                if elifs:
                    new_elifs = []
                    for c in elifs:
                        if (isinstance(c, tuple) and len(c) >= 2
                                and isinstance(c[1], list)):
                            new_elifs.append(
                                (c[0], strip_body(c[1]), *c[2:]))
                        else:
                            new_elifs.append(c)
                    stmt.elifs = new_elifs
                handlers = getattr(stmt, "handlers", None)
                if handlers:
                    for h in handlers:
                        hb = getattr(h, "body", None)
                        if isinstance(hb, list):
                            h.body = strip_body(hb)
                finally_body = getattr(stmt, "finally_body", None)
                if isinstance(finally_body, list):
                    stmt.finally_body = strip_body(finally_body)
                out.append(stmt)
            return out

        fn.body = strip_body(fn.body)
        for inner in unregistered:
            # Lift bare (no ClosureInfo): keep name; captures stay free
            # names resolved as outer locals via X19 fallback / rewritten
            # calls. Same shape GIMPLE uses for unregistered nested defs.
            lifted_defs.append((inner, list(visible_keys)))
            prepare(inner, list(visible_keys))
        for ci in key_children:
            inner = ci.inner_def
            # Rename to lifted symbol
            inner.name = ci.lifted_name
            # Prepend by-value capture params (formal ABI: leading args)
            if ci.captures:
                cap_params = [(cn, ct) for cn, ct in ci.captures]
                # Avoid duplicating a name already in params
                existing = {pn for pn, _pt in inner.params}
                cap_params = [(cn, ct) for cn, ct in cap_params if cn not in existing]
                if cap_params:
                    inner.params = list(cap_params) + list(inner.params)
            # Children of this lifted fn are scanned under ci.lifted_name
            child_keys = [ci.lifted_name] + list(visible_keys)
            lifted_defs.append((inner, child_keys))
            # Recurse into this lifted def to strip its own nested defs
            prepare(inner, child_keys)
            # Rewrite calls in this lifted def
            _rewrite_closures_in_body(inner.body, child_keys, closures)

    for fn in functions:
        prepare(fn, [fn.name])
        _rewrite_closures_in_body(fn.body, [fn.name], closures)

    # Append lifted defs (prepare already recursed depth-first into lifted_defs via append order)
    # Order: originals first, then lifted in discovery order
    return functions + [inner for inner, _keys in lifted_defs]


def _lift_lambdas(functions) -> list:
    """Lift LambdaExprs into top-level FunctionDefs (compile-only).

    - `name = lambda ...` → FunctionDef `name` (body becomes its Return),
      AssignStmt dropped (the name is the function symbol).
    - `(lambda ...)(args)` → IdentExpr of the lifted symbol as callee.
    - Residual bare lambdas (args, ternaries, …) get `_lifted_name` set so
      codegen can materialize the function address via ADRP.

    Returns the original function list plus the lifted defs (appended).
    """
    lifted: list = []
    used_names = {f.name for f in functions}
    counter = [0]

    def fresh_name(base: str) -> str:
        name = base or "lambda"
        if name not in used_names:
            used_names.add(name)
            return name
        counter[0] += 1
        while f"{name}_{counter[0]}" in used_names:
            counter[0] += 1
        name = f"{name}_{counter[0]}"
        used_names.add(name)
        return name

    def make_fn(lam: F.LambdaExpr, base: str) -> str:
        name = fresh_name(base)
        params = []
        param_has_default: dict = {}
        param_defaults: dict = {}
        for pname, pdefault in (lam.params or []):
            ptype = "int"
            if pdefault is not None:
                param_has_default[pname] = True
                param_defaults[pname] = pdefault
            params.append((pname, ptype))
        fdef = F.FunctionDef(
            name=name,
            params=params,
            return_type="int",
            body=[F.ReturnStmt(lam.body, line=lam.line, col=lam.col)],
            param_has_default=param_has_default,
            param_defaults=param_defaults,
            line=lam.line,
            col=lam.col,
        )
        lifted.append(fdef)
        lam._lifted_name = name
        return name

    def walk_expr(expr, owner_name: str) -> None:
        if expr is None or isinstance(expr, (str, int, float, bool)):
            return
        if isinstance(expr, F.LambdaExpr):
            make_fn(expr, owner_name)
            return
        if isinstance(expr, F.CallExpr):
            if isinstance(expr.func, F.LambdaExpr):
                # Immediately-invoked: lift, then call the named symbol.
                lam_name = make_fn(expr.func, owner_name)
                expr.func = F.IdentExpr(lam_name, line=expr.func.line,
                                        col=expr.func.col)
            else:
                walk_expr(expr.func, owner_name)
            for a in list(expr.args or []):
                walk_expr(a, owner_name)
            for _k, kv in list(expr.kwargs or []):
                walk_expr(kv, owner_name)
            return
        if isinstance(expr, F.AssignStmt):
            walk_expr(expr.value, owner_name)
            return
        # Generic structural walk over known expr shapes.
        for attr in ("left", "right", "operand", "value", "obj", "index",
                     "condition", "then_val", "else_val", "body", "iterable",
                     "test", "subject"):
            sub = getattr(expr, attr, None)
            if sub is not None and not isinstance(sub, (str, int, float, bool)):
                if isinstance(sub, list):
                    for x in sub:
                        walk_expr(x, owner_name)
                elif hasattr(sub, "__dict__"):
                    walk_expr(sub, owner_name)
        for attr in ("args", "elements", "operands", "values", "pairs",
                     "generators", "keywords"):
            sub = getattr(expr, attr, None)
            if isinstance(sub, list):
                for x in sub:
                    if isinstance(x, tuple):
                        for y in x:
                            if hasattr(y, "__dict__"):
                                walk_expr(y, owner_name)
                    elif hasattr(x, "__dict__"):
                        walk_expr(x, owner_name)
        if isinstance(expr, F.DictExpr):
            for k, v in expr.pairs or []:
                walk_expr(k, owner_name)
                walk_expr(v, owner_name)

    def walk_body(body: list, owner_name: str) -> list:
        """Return a new body with lambda-assigns replaced (def injected elsewhere)."""
        out = []
        for stmt in body or []:
            # Recurse into nested control-flow bodies first.
            for attr in ("body", "then_body", "else_body", "orelse",
                         "finally_body"):
                sub = getattr(stmt, attr, None)
                if isinstance(sub, list):
                    setattr(stmt, attr, walk_body(sub, owner_name))
            elifs = getattr(stmt, "elifs", None)
            if elifs:
                new_elifs = []
                for c in elifs:
                    if (isinstance(c, tuple) and len(c) >= 2
                            and isinstance(c[1], list)):
                        new_elifs.append(
                            (c[0], walk_body(c[1], owner_name), *c[2:]))
                    else:
                        new_elifs.append(c)
                stmt.elifs = new_elifs
            handlers = getattr(stmt, "handlers", None)
            if handlers:
                for h in handlers:
                    hb = getattr(h, "body", None)
                    if isinstance(hb, list):
                        h.body = walk_body(hb, owner_name)
            finally_body = getattr(stmt, "finally_body", None)
            if isinstance(finally_body, list):
                stmt.finally_body = walk_body(finally_body, owner_name)
            cases = getattr(stmt, "cases", None)
            if cases:
                for c in cases:
                    cb = getattr(c, "body", None)
                    if isinstance(cb, list):
                        c.body = walk_body(cb, owner_name)

            if (isinstance(stmt, F.AssignStmt)
                    and isinstance(stmt.value, F.LambdaExpr)
                    and isinstance(stmt.target, F.IdentExpr)):
                # `name = lambda ...` → top-level def; drop the assign.
                make_fn(stmt.value, stmt.target.name)
                continue

            for attr in ("value", "iterable", "condition", "subject", "test"):
                sub = getattr(stmt, attr, None)
                if sub is not None and hasattr(sub, "__dict__"):
                    walk_expr(sub, owner_name)
            targets = getattr(stmt, "targets", None)
            if isinstance(targets, list):
                for t in targets:
                    if hasattr(t, "__dict__"):
                        walk_expr(t, owner_name)
            out.append(stmt)
        return out

    for fn in functions:
        fn.body = walk_body(fn.body, fn.name)
        # Default values / param-level lambdas (rare): leave as-is.
    return functions + lifted


def _extract_functions(stmts: list) -> list:
    """Extract top-level FunctionDefs from a full module statement list.

    Imports, module-level assignments, structs, control flow, etc. are
    accepted and ignored here — the arm64 codegen only lowers FunctionDefs
    (ARM64Codegen.compile filters them). This lets Mojo's Python-superset
    surface (import os, from math import sqrt, x = 1, if __name__ == ...)
    parse and compile structurally without a hard toplevel gate.
    A module with zero top-level FunctionDefs still builds: _synthetic_main
    provides the entry the startup stub requires.
    Returns the FunctionDef list with `main` first when present (the
    startup stub BLs functions[0])."""
    functions = [s for s in stmts if isinstance(s, F.FunctionDef)]
    if not functions:
        functions = [_synthetic_main()]
    main = [f for f in functions if f.name == "main"]
    rest = [f for f in functions if f.name != "main"]
    return main + rest


def compile_formal(source_path: str, output: str = None,
                   test_input: int = 10, prove: bool = False) -> dict:
    """Compile `source_path` via the formal arm64 path to a Mach-O binary.

    output: destination path; defaults to <stem>.aout next to the source.
    test_input: value placed in X0 before the startup stub calls the entry
    function (formal's `-n`; forwarded as the entry's first argument).
    prove: also emit <stem>_proof.lean next to the binary (Lean 4 static
    typecheck target; does not execute the binary).
    """
    try:
        with open(source_path) as f:
            source = f.read()
    except OSError as e:
        raise FormalBuildError(f"cannot read {source_path}: {e}")

    try:
        stmts = parse_module(source, filename=source_path)
    except SyntaxError as e:
        raise FormalBuildError(f"parse error: {e}")

    try:
        # Structural acceptance: only FunctionDefs matter for codegen;
        # imports / module-level stmts are fine (filtered here + in codegen).
        functions = _extract_functions(stmts)
    except FormalBuildError:
        raise

    # Shared closure discovery (same scan GIMPLE uses), then flatten nested
    # defs into top-level lifted functions with by-value capture params.
    ctx = FormalClosureCtx()
    discover_closures(ctx, stmts)
    functions = _flatten_closures(functions, ctx._all_closures)
    # Lift LambdaExprs into top-level FunctionDefs so assigned/IIFE lambdas
    # lower as BL targets (residual bare lambdas get `_lifted_name` for ADRP).
    functions = _lift_lambdas(functions)

    # Rebuild a statement list with main-first ordering for the codegen.
    ordered = functions

    codegen = ARM64Codegen(test_input=test_input)
    try:
        has_extern_hint = True  # base chosen after we know external_syms
        # First pass: emit with the extern-capable base so relative branches
        # and string ADRP relocations are computed against the address the
        # code will actually live at once we know whether stubs are needed.
        # We don't know external_syms until after compile(), so compile once
        # at the extern base if anything turns out external and re-emit.
        base_extern = TEXT_BASE + EXTERN_ENTRYOFF
        base_noextern = TEXT_BASE + 480  # 32-byte header + 448 sizeofcmds
        code, info = codegen.compile(ordered, base_addr=base_noextern)
        external_syms = info.get("external_syms") or []
        if external_syms:
            # Re-emit at the extern entry base (layout differs).
            codegen = ARM64Codegen(test_input=test_input)
            code, info = codegen.compile(ordered, base_addr=base_extern)
            external_syms = info.get("external_syms") or []
            stub_addrs = compute_macho_got_addrs(
                len(code), external_syms, vaddr=info["base_addr"])
            codegen.asm.resolve_extern(stub_addrs)
            code = bytes(codegen.asm.sections["text"])
    except CodegenError as e:
        raise FormalBuildError(str(e))

    binary = build_macho(code, entry=info["base_addr"],
                         external_syms=external_syms)

    if output is None:
        stem = os.path.splitext(os.path.basename(source_path))[0] or "a.out"
        output = os.path.join(os.path.dirname(os.path.abspath(source_path)),
                              stem + ".aout")
    with open(output, "wb") as f:
        f.write(binary)
    os.chmod(output, 0o755)

    result = {
        "path": output,
        "code": code,
        "binary": binary,
        "info": info,
        "backend": "arm64/macho",
    }

    if prove:
        # prog is only ever read (functions + externs); proofgen never
        # constructs a Program. fire has no ExternFunction nodes on this
        # path — pass [] and let _gen_extern_test's `ret_type_of.get`
        # default handle any recorded extern_calls.
        from formal.arm64_proof_gen import generate_arm64_proof
        prog = SimpleNamespace(functions=ordered, externs=[])
        proof = generate_arm64_proof(prog, code, info)
        proof_path = os.path.splitext(output)[0] + "_proof.lean"
        if os.path.exists(proof_path):
            os.chmod(proof_path, 0o644)  # u+w so overwrite works
        with open(proof_path, "w") as f:
            f.write(proof)
        os.chmod(proof_path, 0o444)  # a-w, same as formal's Makefile
        result["proof_path"] = proof_path

    return result
