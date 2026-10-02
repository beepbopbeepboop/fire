"""Formal codegen + binary emission, selected by
`./fire.py build --formal <file.mojo>` (or a bare `./fire.py --formal`), with
`--backend=arm64` (the default) or `--backend=x86_64` choosing the target.

Pipeline (arm64):
    source → fire_compiler.py tokenize/parse (the real AST)
           → formal.arm64_codegen.ARM64Codegen (machine code)
           → formal.macho.build_macho (MH_EXECUTE Mach-O-64 / ARM64)
           → formal.arm64_proof_gen.generate_arm64_proof (Lean 4, opt-in)

Pipeline (x86_64): the same front end and the same proof-free contract, with
formal.x86_64_codegen.X86_64Codegen and formal.macho.build_macho(arch=
"x86_64") — a Mach-O-64 / x86_64 image, which runs natively under Rosetta 2 on
Apple Silicon. On Linux the same codegen emits an ELF64 image instead
(formal.elf.build_elf, with the extern calls going through .got rather than a
stub section); `default_format` picks that automatically.

Unlike the toy formal tree (which had its own parser and mini-AST), this
path parses with fire_compiler — fire_compiler.py is the single source of
truth for the AST in this project. Proof generation consumes the same
fire AST via aliases (no AST-to-AST translation), one generator per
architecture: formal.arm64_proof_gen and formal.x86_64_proof_gen.
"""

import copy
import os
import re
import subprocess
import sys
from types import SimpleNamespace

import fire_compiler as F
from formal import model as M
from formal.arm64_codegen import ARM64Codegen, CodegenError
from formal.macho import build_macho, compute_macho_got_addrs
from formal.macho_linker import (EXTERN_ENTRYOFF, EXTERN_GLOBALS_ENTRYOFF,
                                  NOEXTERN_ENTRYOFF, NOEXTERN_GLOBALS_ENTRYOFF,
                                  TEXT_BASE, build_macho_dylib,
                                  dylib_code_offset, externer_layout)
from mojo.middle.closures import discover_closures
from formal.comptime_runner import make_call_hook
from formal import dataclass_transform as DC


class FormalBuildError(Exception):
    pass


class ImportBuildError(FormalBuildError):
    """An import could not be turned into a linkable dependency.

    A FormalBuildError so it reaches the user as an ordinary compile error
    ("build: ...") rather than a traceback — an import that cannot be resolved
    used to be dropped silently, and the program then died in dyld at launch
    with "Symbol not found" for a function the source plainly imports.
    """


# The architectures the formal path can target.
ARCHES = ("arm64", "x86_64")


def default_format(arch: str) -> str:
    """Binary format for `arch` on this host: Mach-O on macOS, ELF on Linux.

    Both are native executable formats with no loader of ours involved, which
    is the whole point of the formal path producing something runnable."""
    return "macho" if sys.platform == "darwin" else "elf"


def _ad_hoc_sign(path: str) -> None:
    if sys.platform != "darwin":
        return
    result = subprocess.run(["codesign", "-s", "-", path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise FormalBuildError(
            (result.stderr or result.stdout or "codesign failed").strip())


def parse_module(source: str, filename: str = "<input>") -> list:
    from fire_compiler import py_tokenize_named, Parser
    stmts = Parser(py_tokenize_named(source, filename)).with_filename(filename).parse_module()
    # One census of what this unit writes into a field, attached to every struct
    # it declares. It is what lets formal.model tell a class-level CONSTANT from
    # per-instance state (see the rule above struct_class_constants), and it has
    # to be attached HERE rather than at the point of use because the two
    # backends ask the model about a struct they were handed, with no unit in
    # hand. Attached per FILE, so it is exactly what this file can see; a struct
    # that arrives from an imported module keeps whatever its own module's parse
    # attached, and a module parsed without it keeps every declared name as a
    # field.
    M.attach_field_evidence(list(M.iter_struct_defs(stmts)),
                            M.unit_field_evidence(stmts))
    return stmts


# The name the module body is compiled under: `model.MODULE_BODY_NAME`, which
# is where it lives because both backends' entry selection recognises it. Bound
# here only so the construction below reads as one idea.
MODULE_BODY_NAME = M.MODULE_BODY_NAME


def _module_body_function(body: list, declares: list = None) -> F.FunctionDef:
    """`def __module_body__(): <body>` — the module's top level as a function.

    The whole of the fix for `bugs/FORMAL_toplevel_statements_dropped.md`. A
    file whose body is

        import sys
        sys.exit(3)

    used to build, link, pass the bind audit and do nothing: `_extract_functions`
    picked out `FunctionDef`s, found none, and `_synthetic_main` supplied
    `return 0`. The image was exit 0 where the source says 3, and the coverage
    sweep counted the file a pass.

    Wrapping the body in a function is the whole lowering, and it is the RIGHT
    one rather than a convenient one, because everything the backends already
    know how to lower is a function body. Method-call rewriting, frame
    receivers, spill allocation, the blob arena, the module-constant
    substitution, the unresolved-name check, both architectures' expression
    walk: all of it runs over function bodies, and the module's top level is
    exactly that once it is named. There is no second implementation to keep in
    step with the first, and a construct the backends refuse inside a function
    is refused here by the SAME code with the SAME message — which is what
    makes "a top-level statement is not lowerable" a fact about the construct
    instead of a fact about where it was written.

    The name is not `main`, and must not be: a module that declares its own
    `def main` has that function called by the body (or not), and the startup
    stub branches to `functions[0]`, which is this one. Making the body
    `main` would both collide with the source's own `main` and silently
    displace it.

    `return 0` at the end, matching `_synthetic_main`'s contract and CPython's
    (a script that runs off the end exits 0) — and deliberately NOT the value
    of the last statement, because CPython's is 0 and the last statement's
    value is what a REPL would print, not what a process exits with.

    `declares` is the module's own FunctionDefs, and is checked for one of
    this name. `__module_body__` is a legal Python identifier, so a file CAN
    define it, and both backends key their function tables by name
    (`self._functions[f.name] = f`) — two functions of one name means the
    second silently replaces the first, and which one wins would depend on
    emission order. Refusing by name is the only answer that is not a
    coin toss, and the reader can rename their function in one edit.
    """
    if any(getattr(f, "name", None) == MODULE_BODY_NAME
           for f in (declares or [])):
        raise CodegenError(
            f"this module defines a function named `{MODULE_BODY_NAME}`, "
            f"which is the name this path compiles a module's top-level "
            f"statements under. Both backends key their function tables by "
            f"name, so two functions of one name means one silently replaces "
            f"the other depending on emission order. Rename it")
    fn = F.FunctionDef(name=MODULE_BODY_NAME,
                       params=[],
                       return_type=None,
                       body=list(body) + [F.ReturnStmt(
                           value=F.IntLiteral(value=0, line=0, col=0, raw=""))],
                       line=getattr(body[0], "line", 0) if body else 0,
                       col=0)
    return fn


def _synthetic_main() -> F.FunctionDef:
    """Trivial `def main(): return 0` for a module with nothing to run.

    The module has no top-level statements (so `model.module_body` is empty)
    and no top-level `FunctionDef` (so `_extract_functions` finds none): a
    module that is only imports / constants / classes. Emitting a real entry
    keeps the Mach-O startup path intact and matches the arm64 codegen contract
    that functions[0] is what the startup stub BLs."""
    stmts = parse_module("def main():\n    return 0\n", filename="<synthetic-main>")
    for s in stmts:
        if isinstance(s, F.FunctionDef) and s.name == "main":
            return s
    raise FormalBuildError("synthetic main failed to parse")


def _first_body_where(body: list) -> str:
    """"line N: " for the first statement of a module body, or "".

    A diagnostic that can point at a line should, and the line is the only
    thing that distinguishes `sep = "/"` at the top of a file from the same
    store three hundred lines down. Empty when the body carries no line
    numbers, because a message reading "line : " is worse than one that does
    not mention a line at all."""
    line = getattr(body[0], "line", 0) if body else 0
    return f"line {line}: " if line else ""


def _refuse_unlowerable_module_body(body: list) -> None:
    """Raise `CodegenError` on a top-level statement with no function-level meaning.

    Asked on the module body BEFORE it is wrapped, because inside the synthetic
    function these statements are no longer the constructs they are: a
    file-level `return` would return from `__module_body__`, a `global` would
    name a scope that does not exist, and a `yield` would make the ENTRY a
    generator that nothing iterates. Each of those would build and run and
    compute something other than what the file says, which is the failure mode
    this whole backend's refusals exist to prevent.

    Every other shape is not refused here: it is wrapped, and the ordinary
    function-body pipeline then lowers it or refuses it with its own message
    naming the construct. Refusing a second, larger set here would report
    things as top-level problems that are really ordinary codegen gaps, and
    the sweep's whole point is that a refusal names the construct."""
    for stmt in body:
        why = M.module_body_refusal(stmt)
        if why is not None:
            raise CodegenError(why)


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


def _extract_functions(stmts: list, synthetic: bool = True,
                       symbols: dict = None, body: list = None) -> list:
    """The function list the codegen compiles, entry first.

    Three kinds of top-level statement reach this function and each has its own
    answer, which is the whole of what a module's top level means to this
    backend:

      * a `FunctionDef` is compiled, and `main` is put first because the startup
        stub branches to `functions[0]`;
      * an `import` is not a function and is not body — it names a module the
        linker resolves (`_resolve_imports`), and a nested one inside an `if` or
        a `try` is a body statement like any other;
      * everything else that has an EFFECT is the module BODY, and it is
        compiled as one function (`_module_body_function`) placed FIRST, so it
        runs before `main` and the startup stub enters it.

    That third bullet is the fix for `bugs/FORMAL_toplevel_statements_dropped.md`
    and it is a change of class, not of wording: a file whose whole body is
    `sys.exit(3)` used to build, run, and exit 0, and the sweep called it a
    pass. `model.module_body` decides which statements those are, by kind, once,
    for both backends and both front ends.

    `symbols` is `collect_module_symbols(stmts)`'s table — passed in rather
    than rebuilt because `_prepare_functions` has already built AND published
    it, and the foldable-constant exemption is a lookup in it. `body` is that
    same table's `model.module_body(stmts, symbols)` answer, passed for the
    same reason: asking it twice would be a second analysis of the same
    statements that could disagree with the first, and a caller that had
    already refused the body (the dylib path) must be refused the same body.

    A module with neither a FunctionDef nor a body statement still builds:
    `_synthetic_main` provides the entry the startup stub requires.
    """
    functions = [s for s in stmts if isinstance(s, F.FunctionDef)]
    if body is None:
        body = M.module_body(stmts, symbols)
    entry = ([_module_body_function(body, functions)]
             if body else [])
    if not functions and not entry and synthetic:
        functions = [_synthetic_main()]
    # The body first, then `main`, then the rest. The body is the module's own
    # code and CPython runs it before anything calls `main`; `main` next
    # because the startup stub's contract is `functions[0]`, which the body
    # now is, and a declared `main` is an ordinary function the body may call.
    main = [f for f in functions if f.name == "main"]
    rest = [f for f in functions if f.name != "main"]
    return entry + main + rest


def _make_codegen(arch: str, fmt: str, test_input: int,
                  dylib_syms: dict = None, comptime_hook=None,
                  dylib_exports: list = None, import_aliases: dict = None,
                  extern_decls: dict = None):
    """The codegen for `arch`, configured for the `fmt` binary it feeds.

    The only format-dependent choice made here is how an unbound symbol is
    called: Mach-O carries a __TEXT,__stubs trampoline (`call rel32` to it),
    while ELF has no stub section and calls through the .got slot the loader
    fills (`call [rip+disp32]`). Everything else about the two backends is the
    same contract, so it is selected here rather than at each call site. `fmt`
    is also handed to the x86-64 backend as `target_fmt`, for the other
    format-dependent question — which SPELLING of a C name this target binds,
    since macOS and glibc disagree about that (see
    `model.target_libc_symbol`).

    `dylib_exports` is the linked libraries' manifest export lists, in the
    same LINK ORDER as `dylib_syms`, so the two answer identically about a
    bare callee. It is a separate argument rather than a re-derivation from
    `dylib_syms` because it carries two things the flat map threw away: the
    module that owns each export (which is what makes `mod.f()` resolvable
    without ever consulting a bare name) and the declared signature (which is
    what says whether a call's result is a string). See
    `model.dylib_export_lookup`.

    `import_aliases` is `formal/imports.py`'s `import_bindings` table: the
    local name `from m import f as g` binds, and where it came from. Without
    it the emitters can only look a bare callee up by its DEFINING name, so `g`
    found nothing and the image bound a symbol no library defines. See
    `model.dylib_aliased_export`.

    `extern_decls` is `formal/imports.py`'s `external_declarations` table:
    `{export symbol: FunctionDef}`, the callee's own declaration read from the
    source the linked library was compiled from. It is what lets a call ACROSS
    a dylib boundary bind its arguments the way a call inside one image does,
    so a defaulted parameter is materialized instead of arriving as whatever
    the caller last left in the register."""
    # Where this unit's module-global data segment will be MAPPED, handed to
    # both backends because every slot access is an absolute address computed
    # before the image exists. None when the module declares no writable
    # global, so an ordinary program pays nothing and emits no data segment.
    gbase = globals_base(fmt) if M.module_slots() else None
    if arch == "arm64":
        return ARM64Codegen(test_input=test_input,
                            dylib_syms=dylib_syms,
                            comptime_hook=comptime_hook,
                            dylib_exports=dylib_exports,
                            globals_base=gbase,
                            import_aliases=import_aliases,
                            extern_decls=extern_decls)
    if arch == "x86_64":
        from formal.x86_64_codegen import X86_64Codegen
        return X86_64Codegen(test_input=test_input,
                             extern_style="got" if fmt == "elf" else "stub",
                             dylib_syms=dylib_syms,
                             comptime_hook=comptime_hook,
                             dylib_exports=dylib_exports,
                             globals_base=gbase,
                             target_fmt=fmt,
                             import_aliases=import_aliases,
                             extern_decls=extern_decls)
    raise FormalBuildError(
        f"unknown arch {arch!r} (expected one of {', '.join(ARCHES)})")


def globals_image(fmt: str = "macho"):
    """The data image for the current unit's module-global slots, or None.

    One function, and the only caller of `model.build_data_image` on the build
    side, because the blob and its fixup list are ONE fact that the linker and
    the codegen both act on: the linker writes the bytes and emits a relocation
    per fixup, and the codegen addresses slot `i` at the same offsets the blob
    was laid out from. Building it in two places would give two images and one
    of them would be wrong in a way no test could attribute.

    `fmt` selects the base address the image's data segment is MAPPED at, which
    the two containers define separately (`macho_linker.GLOBALS_VM` and
    `elf.GLOBALS_VM`) and which is not optional: both linkers' relocation
    machinery adds the load slide to the value already in the file, so a slot
    word must hold the link-time ADDRESS.

    None for a module with no `global NAME` — the ordinary case — so a program
    that does not use this capability gets byte-for-byte the image it got
    before."""
    table = M.module_slots()
    if not table:
        return None
    return M.build_data_image(table, globals_base(fmt))


def globals_base(fmt: str = "macho") -> int:
    """The address this container maps a unit's module-global data at.

    Read by THREE parties that must not each look it up: the image builder
    (which writes `base + offset` into every address-valued slot), the two
    backends' `_global_slot_address` (which compute where slot `i` lives), and
    the linker (which declares the segment there). One function, so a format
    whose base moved cannot leave three copies behind."""
    if fmt == "elf":
        from formal.elf import GLOBALS_VM
        return GLOBALS_VM
    from formal.macho_linker import GLOBALS_VM
    return GLOBALS_VM


def _container_family(path: str) -> str:
    """Which executable CONTAINER `path` is: "macho", "elf", or "unknown".

    Four bytes of magic, which is the same test `file(1)` makes and the only
    thing a loader gets to look at before deciding it can open the image at
    all. Read from the file rather than from the build that produced it,
    because the whole point of asking is not to trust the build.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return "unknown"
    if magic == b"\xcf\xfa\xed\xfe":
        return "macho"
    if magic == b"\x7fELF":
        return "elf"
    return "unknown"


def _audit_link_line_containers(linked, fmt: str, where: str) -> None:
    """Every library on this link line must be in the image's OWN container.

    The gap this closes is the one that let an ELF image import a module for
    as long as it did, and it is the check `_audit_bound_symbols` structurally
    cannot be. That one asks "does something on this link line DECLARE this
    name?", reads each library's manifest, and finds it there — which was true,
    and irrelevant, because the library was a Mach-O and the image an ELF, so
    no ELF loader would ever open it. The symbol was declared by a file the
    loader refuses to read.

    Both halves of a mismatch are worth saying: the image cannot open the
    library, AND the library cannot be opened by the loader that would be
    running. The name that is wrong is the container, not the symbol, so this
    names the container.

    It is deliberately cheap and unconditional rather than ELF-only. A Mach-O
    image with an ELF library is the same defect with the two formats swapped,
    and nothing about the host decides which way it goes: `fmt` is chosen by
    the caller, so a caller can ask for one container while the libraries on
    the line are in the other.
    """
    want = "macho" if fmt == "macho" else "elf"
    for d in linked or []:
        path = d.get("path")
        if not path:
            continue
        got = _container_family(path)
        if got != want:
            article = "an" if want == "elf" else "a"
            raise FormalBuildError(
                f"the {where} is {want} but {os.path.basename(path)} is "
                f"{got}: {article} {want} loader cannot open {article} {got} "
                f"library, so every symbol it exports is unresolvable at "
                f"load. The library's container is what has to match, not the "
                f"symbol names — rebuild the dependency for {fmt!r}. This "
                f"path emits {want} module libraries only.")
def _audit_bound_symbols(external_syms, dylib_syms, where: str,
                          dylib_exports=None) -> list:
    """Every extern must be accounted for: a C library, or a linked dependency.

    An image that binds a symbol nothing provides is not a working image — it
    builds cleanly and then cannot be loaded, or dies at the first call. That
    is the failure mode the whole import mechanism exists to prevent, and this
    check is where it is caught, in the place that can still name the symbol.

    It used to run on the DYLIB path only. The executable path — `build
    --formal`, which is what the test suites and the coverage sweep actually
    drive — emitted `external_syms` into the Mach-O/ELF with nothing checking
    them, so the one path that matters most had the weakest checking. Both call
    this now, which is also why it is factored out rather than copied: two
    copies of a rule like this is how they come to disagree about what
    "accounted for" means.

    `dylib_syms` is the merged `{bare callee: exported symbol}` of every linked
    library's manifest. Two spellings meet here: a manifest records the C
    identifier (what a bind stream carries — dyld prepends the underscore) while
    a name the codegen could not resolve arrives in the Mach-O spelling, with
    one. Comparing them raw reports every dependency symbol as unprovided, so
    both sides are compared without the underscore.

    `dylib_exports` is the same libraries' manifest export LISTS, and it is a
    separate argument because the flat map is lossy in a way this check must
    not inherit: it keeps only the FIRST library's answer for each bare name,
    so with two modules that both export `which`, `left.which` wins the bare
    entry and `right_which` appears nowhere in it. A dotted call
    (`ARM64Codegen._extern_symbol`) resolves by MODULE IDENTITY and so can bind
    the second one — and this check then reported the library's own export as
    a symbol nothing provides, which is the opposite of the truth and stopped
    a perfectly good program from building. Everything the link line really
    provides is accounted for, whoever it belongs to.

    Returns the unaccounted names, which is empty when the image is sound. The
    caller decides how to report, because the two paths have different names to
    report it against.
    """
    provided = {n.lstrip("_") for n in (dylib_syms or {})}
    provided |= {n.lstrip("_") for n in (dylib_syms or {}).values()}
    for lib in (dylib_exports or []):
        for entry in (lib.get("exports") or []):
            name = entry.get("symbol") or entry.get("name")
            if name:
                provided.add(name.lstrip("_"))
    return [sym for sym in sorted(set(external_syms or []))
            if sym.lstrip("_") not in provided
            and not _is_libsystem(sym)]


def _unaccounted_report(source_path: str, unaccounted: list, where: str) -> str:
    """The one wording for "this image would bind symbols nothing provides"."""
    return (f"{os.path.basename(source_path)}: the {where} would bind "
            f"{len(unaccounted)} symbol(s) that nothing provides, so it could "
            f"not be loaded: {', '.join(unaccounted[:8])}"
            f"{' …' if len(unaccounted) > 8 else ''}. Nothing on this link "
            f"line defines them: not the C library, and not any library this "
            f"program linked. Two very different causes produce that, and the "
            f"distinction is not lost — each name in this list is either a call "
            f"the codegen emitted (`info['external_syms']`, so some construct "
            f"was not lowered and the call is dangling) or a name that entered "
            f"the image as a bare reference with no call site behind it. "
            f"Deciding which is a question for the assembler, and it is asked "
            f"nowhere in this backend, so this message stops at the fact both "
            f"causes share. (Provider check: {_libsystem_probe_status()}.)")


def _codegen_and_link(arch: str, fmt: str, ordered: list, test_input: int,
                      dylibs: list = None, comptime_hook=None,
                      structs: list = None, source_path: str = None,
                      import_aliases: dict = None, extern_decls: dict = None):
    """Compile `ordered` for `arch` and wrap it in its binary container.

    Returns (code, info, external_syms, binary). Mach-O needs two passes: the
    entry offset (and so the base address the code is emitted for) depends on
    whether the image carries the extern machinery, which is only known after
    the first pass has seen every call site. ELF has one fixed base, so a
    single pass plus the GOT back-patch is enough.

    `dylibs` is the linked-library set (see `load_dylib_manifests`): each
    entry's symbols are callee names the codegen must mangle to that library's
    exported spelling, and each adds a load command — which moves the entry
    point, so the second pass has to be emitted for the offset the *same*
    dylib list implies.

    `import_aliases` is `formal/imports.py`'s `import_bindings` table, passed
    straight through to the codegen: a call site spells the name AS WRITTEN, so
    `from m import f as g` has to reach `f`'s export rather than miss the flat
    map and bind `g`.

    `extern_decls` is `formal/imports.py`'s `external_declarations`, for the
    same reason read from the other end: a callee in another image has a
    parameter list this build cannot see unless it is handed over."""
    dylibs = list(dylibs or [])
    dylib_syms = {}
    for d in dylibs:
        for bare, mangled in (d.get("map") or {}).items():
            dylib_syms.setdefault(bare, mangled)
    # The export ENTRIES, in the same order, so the codegen's own flat lookup
    # resolves a bare callee to the same entry the map above resolved it to —
    # the two are built from one iteration rather than from two
    # re-implementations of "first library on the line wins".
    dylib_exports = dylib_export_lists(dylibs)
    # BEFORE any codegen pass: a library the loader cannot open makes every
    # symbol it exports unresolvable, so there is nothing worth compiling and
    # the diagnostic is better before the image exists.
    _audit_link_line_containers(dylibs, fmt, "image")
    if fmt == "elf":
        from formal.elf import (DEFAULT_BASE, DEFAULT_LIBC, build_elf,
                                 compute_got_addrs)
        codegen = _make_codegen(arch, fmt, test_input, dylib_syms,
                                comptime_hook, dylib_exports, import_aliases,
                                extern_decls)
        try:
            code, info = codegen.compile(ordered, base_addr=DEFAULT_BASE,
                                         structs=structs)
        except CodegenError as e:
            raise FormalBuildError(str(e))
        external_syms = info.get("external_syms") or []
        if external_syms:
            got = compute_got_addrs(len(code), external_syms,
                                    vaddr=info["base_addr"],
                                    lib_name=DEFAULT_LIBC)
            codegen.asm.resolve_extern(got)
            code = bytes(codegen.asm.sections["text"])
        unaccounted = _audit_bound_symbols(external_syms, dylib_syms,
                                          "image", dylib_exports)
        if unaccounted:
            raise FormalBuildError(
                _unaccounted_report(source_path or "<program>", unaccounted,
                                    "image"))
        binary = build_elf(code, entry=info["base_addr"],
                           vaddr=info["base_addr"],
                           external_syms=external_syms, lib_name=DEFAULT_LIBC,
                           globals_image=globals_image(fmt))
        return code, info, external_syms, binary

    # The extern entry offset depends on the linked dylibs: each adds a load
    # command, and the code starts after the whole list. `has_globals` moves it
    # the same way, because a module-global `__DATA` segment is one more load
    # command — and it is read from the PUBLISHED table rather than recomputed,
    # so the image the linker is about to be handed and the layout the code was
    # emitted for are the same fact read twice.
    from formal.macho_linker import extern_entry_offset
    has_globals = bool(M.module_slots())
    base_extern = TEXT_BASE + extern_entry_offset(
        [d["install_name"] for d in dylibs], has_globals=has_globals)
    base_noextern = TEXT_BASE + (NOEXTERN_GLOBALS_ENTRYOFF if has_globals
                                 else NOEXTERN_ENTRYOFF)
    codegen = _make_codegen(arch, fmt, test_input, dylib_syms, comptime_hook,
                            dylib_exports, import_aliases, extern_decls)
    try:
        code, info = codegen.compile(ordered, base_addr=base_noextern,
                                     structs=structs)
        external_syms = info.get("external_syms") or []
        if external_syms:
            # Re-emit at the extern entry base (the layout differs, and so do
            # every address the code computed off its own base).
            codegen = _make_codegen(arch, fmt, test_input, dylib_syms,
                                    comptime_hook, dylib_exports,
                                    import_aliases, extern_decls)
            code, info = codegen.compile(ordered, base_addr=base_extern,
                                         structs=structs)
            external_syms = info.get("external_syms") or []
            # The stub addresses must be computed for the SAME entry offset
            # the code was emitted at, which a linked dylib moves.
            stub_addrs = compute_macho_got_addrs(
                len(code), external_syms, vaddr=info["base_addr"], arch=arch,
                entryoff=extern_entry_offset(
                    [d["install_name"] for d in dylibs],
                    has_globals=has_globals))
            codegen.asm.resolve_extern(stub_addrs)
            code = bytes(codegen.asm.sections["text"])
    except CodegenError as e:
        raise FormalBuildError(str(e))
    unaccounted = _audit_bound_symbols(external_syms, dylib_syms,
                                        "image", dylib_exports)
    if unaccounted:
        raise FormalBuildError(
            _unaccounted_report(source_path or "<program>", unaccounted,
                                "image"))
    binary = build_macho(code, external_syms=external_syms, arch=arch,
                         dylibs=[{"install_name": d["install_name"],
                                  "symbols": set((d.get("map") or {}).values())}
                                 for d in dylibs] or None,
                         globals_image=globals_image(fmt))
    return code, info, external_syms, binary


def _imported_structs(source_path: str, stmts: list, arch: str,
                      linked: list = None) -> list:
    """Struct declarations from the modules this file imports, or [].

    A no-op for a target that has no module concept (an ELF image, or a
    non-Mach-O format): there is nothing to import and nothing to bind.

    `linked` widens it to the libraries the program was HANDED, which is not the
    same set and used to be a hole. `--link-dylib heaplib.dylib` with a program
    that has no import statement is the only way `Bag` reaches such a program —
    the dylib carries the struct's METHODS in its manifest (`kind: "method"`
    entries, one per `add`/`__len__`) but not its DECLARATION, and without one
    `var b = Bag(); b.n = 4` was refused with a repair the reader cannot apply:
    "Bind the base from a constructor THIS MODULE declares", for a struct
    declared in a file this build does not have. That advice was right and
    impossible. The declaration is read from the source the library recorded
    when it was built — the same bytes its methods were compiled from — so the
    field list, `struct_is_framed`'s answer and the frame slot table all come
    from one file and cannot disagree with the library on the link line."""
    if not fmt_wants_macho(arch):
        return []
    from formal.imports import (imported_struct_defs, linked_module_paths,
                                module_struct_defs)
    out, seen = [], set()
    for st in imported_struct_defs(source_path, stmts,
                                   project_root=source_path):
        seen.add(st.name)
        out.append(st)
    for path in linked_module_paths(linked):
        for st in module_struct_defs(path, source_path):
            if st.name not in seen:
                seen.add(st.name)
                out.append(st)
    return out


def _import_aliases(stmts: list) -> dict:
    """`{local name: (module as spelled, defining name)}` for this file's imports.

    Read here, from the statements this build already parsed, and handed to the
    emitters — a call site spells the name AS WRITTEN, so `from m import f as g`
    needs the mapping from `g` back to `m`'s `f` and no amount of looking up the
    bare name in the libraries' export tables can produce it. See
    `formal/imports.py`'s `import_bindings`."""
    from formal.imports import import_bindings
    return import_bindings(stmts)


def _external_declarations(linked: list) -> dict:
    """`{export symbol: FunctionDef}` for the linked libraries' function exports.

    Read from each library's own source — the path its manifest records — so a
    call ACROSS a dylib boundary binds its arguments from the callee's real
    parameter list instead of passing whatever the caller wrote and letting an
    omitted register hold a stale value. Without it a defaulted parameter
    arrived as a stack address, which is a silently wrong argument rather than a
    missing feature. See `formal/imports.py`'s `external_declarations`."""
    from formal.imports import external_declarations
    return external_declarations(linked)


def _resolve_imports(source_path: str, stmts: list, arch: str) -> list:
    """Compile every module this file imports, and return their dylibs.

    Returns [] when the file imports nothing. A file that imports something
    unresolvable is an ERROR, not a shrug: the alternative is the failure this
    replaces — an image that builds and then dies in dyld because a call's
    symbol does not exist.
    """
    from formal.imports import (build_module_dylib, dylib_chain,
                                imported_modules, resolve_module_path,
                                unresolvable_import_error)
    mods = imported_modules(stmts)
    if not mods:
        return []
    if fmt_wants_macho(arch):
        # Per-architecture, and that is load-bearing rather than tidiness.
        # This directory holds BUILT module dylibs, and a dylib is a
        # target-specific image: an arm64 library and an x86-64 library for
        # the same source are not two versions of one artifact, they are two
        # different artifacts. Sharing one directory keyed by module name
        # alone meant the second sweep overwrote the first's file, so a
        # program could be handed a link line naming a dylib of the wrong
        # architecture — which builds, links and passes every static check,
        # and then dies in dyld with "mach-o file, but is an incompatible
        # architecture" before `main` runs. The same directory is also
        # written concurrently by unrelated builds, so a name collision there
        # is a live hazard and not only a theoretical one.
        out_dir = os.path.join(cas_dir(), "formal-imports", arch)
        chain = []
        for mod in mods:
            path = resolve_module_path(mod, relative_to=source_path)
            if path is None:
                # One wording for one condition, and it is BUILT next to the
                # rules that decide which of the two reasons applies
                # (formal/imports.py's `unresolvable_import_error`): the same
                # error is raised there for an unresolvable import inside a
                # DEPENDENCY, and two messages for one cause is how a real
                # failure ends up filed under the wrong heading.
                raise ImportBuildError(
                    unresolvable_import_error(source_path, mod))
            try:
                dylib = build_module_dylib(mod, path, out_dir, arch,
                                           project_root=source_path)
            except ImportBuildError as e:
                # The dependency's own error names the file that failed, which
                # is rarely the file the user asked about — and now that a
                # sibling `.py` resolves, reaching a DEPENDENCY is the common
                # way to fail (`model.py` → `fire_compiler` → `re`). Say how
                # we got there, or the message reads as being about a file that
                # was never mentioned.
                raise ImportBuildError(
                    f"{os.path.basename(source_path)} imports {mod!r}, which "
                    f"cannot be built either: {e}") from None
            if dylib:
                chain.extend(dylib_chain(dylib))
        seen, out = set(), []
        for d in chain:
            if d not in seen:
                seen.add(d)
                out.append(d)
        return out
    return []


def fmt_wants_macho(arch: str) -> bool:
    return default_format(arch) == "macho"


def cas_dir() -> str:
    import cas
    return cas.CAS_DIR


def compile_formal(source_path: str, output: str = None,
                   test_input: int = 10, prove: bool = True,
                   check: bool = True, arch: str = "arm64",
                   fmt: str = None, link_dylibs: list = None) -> dict:
    """Compile `source_path` through the formal path for `arch`.

    arch: "arm64" (default) or "x86_64".
    fmt: "macho" or "elf"; defaults to the host's native format
    (`default_format`). The two are interchangeable per architecture, so
    either can be requested explicitly — useful for checking the ELF emitter
    from a Mac.
    output: destination path; defaults to <stem>.aout (Mach-O) or <stem>.elf
    (ELF) next to the source.
    link_dylibs: formal libraries (.dylib paths) this program links against.
    A call to a name one of them exports is rewritten to that library's
    exported symbol, so the image records the library as a dependency and dyld
    binds the call at launch — see `load_dylib_manifests`. Without this a
    cross-module call lowers to a BL against a symbol nothing defines.
    test_input: value passed to the entry function by the startup stub
    (formal's `-n`).
    prove: also emit <stem>_proof.lean next to the binary (Lean 4 static
    typecheck target; does not execute the binary). Supported for both
    architectures.
    """
    if arch not in ARCHES:
        raise FormalBuildError(
            f"unknown arch {arch!r} (expected one of {', '.join(ARCHES)})")
    if fmt is None:
        fmt = default_format(arch)
    if fmt not in ("macho", "elf"):
        raise FormalBuildError(f"unknown format {fmt!r} (expected macho|elf)")


    try:
        with open(source_path) as f:
            source = f.read()
    except OSError as e:
        raise FormalBuildError(f"cannot read {source_path}: {e}")

    try:
        stmts = parse_module(source, filename=source_path)
    except SyntaxError as e:
        raise FormalBuildError(f"parse error: {e}")

    # The target this image is FOR, published BEFORE anything that can build a
    # module — `_imported_structs` below compiles each imported module into a
    # dylib, and each of those publishes the target of ITS OWN build (a dylib is
    # always Mach-O, `formal/imports.py`). Publishing again after would work, but
    # a value that is only correct because of the order of two lines is a value
    # that will be wrong the day someone reorders them; so this one goes first
    # and the dylib's publish is the one that has to be undone.
    #
    # The pipeline is where a `#kgen.param.expr<…>` target query is answered:
    # `arch` and `fmt` are the two facts the linker is about to act on, and a
    # query like "what is the current target's arch" has exactly one correct
    # answer for them. They are the same pair the dylib cache is keyed on, so
    # the two front ends cannot describe one target two ways.
    M.publish_target(M.target_for(arch, fmt))

    # Structural acceptance: only FunctionDefs matter for codegen; imports /
    # module-level statements are fine (filtered here + in the codegen).
    # The modules this file imports contribute their struct declarations
    # BEFORE the function pipeline runs, because a method call is rewritten to
    # `<Struct>_<method>` and the rewrite needs to know which struct owns the
    # name. Resolving this after would leave `c.get()` unrecognised in a file
    # that imported the struct, which is the only way such a call occurs.
    # The libraries this program links against, resolved before codegen: their
    # export spellings decide both the callee mangling and (via their load
    # commands) where the entry point lands. Read BEFORE the function pipeline
    # because `_imported_structs` needs them: a library handed over with
    # `--link-dylib` and no import statement is the only way its struct
    # declarations reach this file at all.
    linked = load_dylib_manifests(link_dylibs)
    imported_structs = _imported_structs(source_path, stmts, arch, linked)
    # …and the target again, because the dylib builds above republished it as
    # the dylib's own Mach-O target. This is the one place the two genuinely
    # differ (an `--fmt=elf` build on a Mac asks for an ELF image and a Mach-O
    # dylib), and the executable's functions are the ones the linker is about to
    # act on.
    M.publish_target(M.target_for(arch, fmt))
    try:
        functions, structs, symbols, slots = _prepare_functions(
            stmts, synthetic=True, extra_structs=imported_structs)
    except CodegenError as e:
        # A clean compile error. The function pipeline runs before codegen
        # proper, so a refusal raised there — a method whose receiver is wider
        # than a word, say — used to reach the user as a raw traceback instead
        # of the one-line diagnostic every other refusal produces.
        raise FormalBuildError(str(e))
    ordered = functions

    # `import X` means X is a dependency. Each imported module is compiled in
    # FULL into a dylib that represents it (formal/imports.py) and goes on the
    # link line with everything it itself needs, dependencies first. Without
    # this an import was silently dropped and its calls became BLs against
    # symbols nothing defines.
    try:
        import_dylibs = _resolve_imports(source_path, stmts, arch)
    except ImportBuildError as e:
        # A clean compile error, not a traceback: an unresolvable import used
        # to be dropped silently, and the resulting program died in dyld at
        # launch with "Symbol not found" for a function the source plainly
        # imports.
        raise FormalBuildError(str(e))
    if fmt != "macho" and import_dylibs:
        # An ELF image with a module dependency, refused rather than emitted.
        #
        # `formal/imports.py` builds module libraries with
        # `build_macho_dylib`, so `import_dylibs` here is a list of Mach-O
        # shared objects — and `formal/elf.py`'s `build_elf` carries ONE
        # `lib_name` (`libc.so.6`) and writes exactly one `DT_NEEDED`, with no
        # `.dynamic` entry for anything else. The libraries are therefore built,
        # audited (their symbols are `provided`, so `_audit_bound_symbols`
        # passes) and then put NOWHERE: the image's `.dynstr` carries
        # `ANY_add1_9f63a2` while the only `DT_NEEDED` is libc.
        #
        # That is the worst shape this can take, because the audit is what
        # makes it look right. The image builds, the audit passes, and the
        # program dies at load with an unresolved symbol for a function its
        # own source imports. This is the ELF half of the container gap named
        # in bugs/CODEGEN_x86_64_module_dylib_emitted_as_macho.md: `arch`
        # selects the code generator and is honoured, but there is no ELF
        # shared-object emitter, so a program that imports a module has no
        # target-shaped library to link.
        from formal.elf import DEFAULT_LIBC
        raise FormalBuildError(
            f"{os.path.basename(source_path)} imports {len(import_dylibs)} "
            f"module(s) and cannot be built for {fmt!r}: module libraries are "
            f"Mach-O on this path (formal/macho_linker.py's build_macho_dylib "
            f"is the only emitter) and {fmt} has no shared-object form here — "
            f"formal/elf.py writes one DT_NEEDED ({DEFAULT_LIBC!r}) and no "
            f".dynamic entry for anything else, so the image would carry the "
            f"module's symbols in .dynstr with nothing providing them. The "
            f"code generator does honour arch; the container is the missing "
            f"half. Build for macho, or lower the module into this image.")
    # HERE and not inside `_prepare_functions`, which ran before the imports
    # resolved: a file that imports a host module is out of reach whatever its
    # codegen says, and this check fires on a third of the repository, so
    # raising it earlier would report the secondary problem in 67 files and
    # move the coverage denominator for it.  See
    # `check_frame_field_blob_premises`.
    #
    # …and `check_construction_shapes`, for the same measured reason: from
    # inside `_prepare_functions` it preempted the import diagnosis for 14
    # files of this repository, every one of them a file that imports a host
    # module.
    #
    # BOTH wrapped, and the wrapping is a fix rather than a courtesy: this
    # function's `except CodegenError` is around `_prepare_functions`, so a
    # refusal from either late check reached the caller as a raised exception
    # and was classified `backend-crash` — a verdict for a compiler bug, on a
    # construct that is a refusal.  Measured: with the construction check
    # outside the wrapper, `std/gpu/host/func_attribute.mojo` went from a
    # named `codegen` finding to `backend-crash`.
    #
    # …and `check_module_symbols` re-publishes THIS unit's table first, because
    # `_resolve_imports` — which runs between here and the above — compiles
    # every imported module into a dylib, and each of those is a NESTED
    # `_prepare_functions` that publishes ITS module's globals over ours. The
    # symptom was measured and it was exactly the two-architecture split this
    # design exists to prevent: `_assembly.mojo` refused `'_get_kgen_string'`
    # with the message naming THIS module on arm64 and the one naming the
    # imported module on x86-64, because the two architectures built the
    # dylibs in a different order and so had a different module's table
    # published at the point the check read it.
    #
    # `imported_modules(stmts)` GATED on `import_dylibs`, and the gate is
    # load-bearing rather than defensive. `_resolve_imports` is a no-op for a
    # target with no module mechanism (an ELF image: no dylib form, nothing to
    # link), so on that target an `import` produces no library and a dotted
    # call `mod.f()` has no symbol to bind. Handing the checker the module
    # names there would stop it refusing that call and let the image be
    # emitted with a `BL` against a symbol nothing defines — refused today, a
    # load-time failure after this change. No module dylib on the line, no
    # dotted call.
    from formal.imports import imported_modules
    # Read once and used twice: the constants an imported module publishes (for
    # the substitution below) and the libraries this image links (further
    # down). Reading the manifests in both places is a second answer to the
    # same question, taken at two different moments.
    import_manifests = load_dylib_manifests(import_dylibs)
    try:
        # A module-level CONSTANT of an IMPORTED module, in both spellings
        # (`from mod import CONST` and `mod.CONST`), BEFORE the late checks and
        # after `_resolve_imports` — which is the only place the link line's
        # manifests exist, and the build that compiled each module is the only
        # place its folded values were ever computed. A literal needs no
        # storage to cross a dylib boundary (there is exactly one value of a
        # folded module-level name in a whole program), so this is a
        # substitution rather than a symbol; a module-level name the folder
        # could not fold has no value to substitute and is still refused by
        # name, which is what keeps `sys.argv` and `os.sep` different answers
        # (`bugs/FORMAL_module_state_no_storage.md`).
        symbols = _publish_imported_constants(functions, symbols,
                                              import_manifests)
        # The link line as the CALL will resolve it: this program's own
        # `link_dylibs` first, then the imports `_resolve_imports` just built.
        # `check_imported_frame_handoffs` reads a per-parameter frame-holder
        # contract out of these, and it must read the SAME resolution the
        # emitted call binds — the order and the first-wins precedence are what
        # `dylib_syms` and `dylib_export_tables` already use, so passing the two
        # lists in that order is what keeps the contract consulted and the
        # contract used the same one. The dedup is the same test the merge below
        # applies, because a library already on the line must not contribute a
        # second, later-wins entry.
        _have = {d["install_name"] for d in linked}
        _line = list(linked) + [d for d in import_manifests
                                if d["install_name"] not in _have]
        _run_late_checks(stmts, functions, structs, symbols, slots,
                         imported_modules(stmts) if import_dylibs else None,
                         _line)
    except CodegenError as e:
        raise FormalBuildError(str(e))
    if import_dylibs:
        have = {d["install_name"] for d in linked}
        linked = linked + [d for d in import_manifests
                           if d["install_name"] not in have]

    # The gimple runtime's C library, on this image's link line, if and only if
    # the program names an entry point of it that the library really provides
    # (see `_runtime_library_for` for why those are two questions). LAST in the
    # list, so an imported module's own export still wins the name if the two
    # ever collide: an import is a specific thing the program asked for and the
    # runtime is the ambient one. `_codegen_and_link` merges the maps with
    # `setdefault` in list order, so position here is the precedence.
    runtime_lib, runtime_calls = _runtime_library_for(ordered, arch, fmt)
    if runtime_lib is not None:
        linked = linked + [runtime_lib]


    # `comptime f(...)` is resolved by RUNNING f through this same backend
    # (formal/comptime_runner.py), so a folded constant and the emitted code
    # can never come from two different implementations.
    comptime_hook = make_call_hook(source)
    code, info, external_syms, binary = _codegen_and_link(
        arch, fmt, ordered, test_input, dylibs=linked,
        comptime_hook=comptime_hook,
        structs=structs, source_path=source_path,
        import_aliases=_import_aliases(stmts),
        extern_decls=_external_declarations(linked))

    if output is None:
        stem = os.path.splitext(os.path.basename(source_path))[0] or "a.out"
        ext = ".elf" if fmt == "elf" else ".aout"
        output = os.path.join(os.path.dirname(os.path.abspath(source_path)),
                              stem + ext)
    with open(output, "wb") as f:
        f.write(binary)
    os.chmod(output, 0o755)
    if fmt == "macho":
        # Only Mach-O images are ad-hoc signed; the kernel refuses an
        # unsigned one, and an ELF image carries no such requirement.
        _ad_hoc_sign(output)

    result = {
        "path": output,
        "code": code,
        "binary": binary,
        "info": info,
        "backend": f"{arch}/{fmt}",
        # The libraries this image actually carries, by the path its load
        # commands name. A caller that wants to know whether a `mojo_*` call was
        # linked against the real runtime or refused asks here; the image
        # itself is the other answer, but reading a Mach-O to find out is not
        # something a test should have to do twice.
        "linked_dylibs": [d["install_name"] for d in linked],
        # Which `mojo_*` calls the runtime library was put on the link line FOR.
        # Empty on both sides of the decision is the normal case, and the
        # distinction is the whole gate: a call that is word-shaped but not
        # exported is refused, and one that is exported is not.
        "runtime_calls": list(runtime_calls),
    }

    if prove:
        # prog is only ever read (functions + externs); proofgen never
        # constructs a Program. fire has no ExternFunction nodes on this
        # path — pass [] and let _gen_extern_test's `ret_type_of.get`
        # default handle any recorded extern_calls.
        if arch == "x86_64":
            from formal.x86_64_proof_gen import generate_x86_64_proof
            generate_proof = generate_x86_64_proof
        else:
            from formal.arm64_proof_gen import generate_arm64_proof
            generate_proof = generate_arm64_proof
        prog = SimpleNamespace(functions=ordered, externs=[])
        proof = generate_proof(prog, code, info)
        proof_path = os.path.splitext(output)[0] + "_proof.lean"
        if os.path.exists(proof_path):
            os.chmod(proof_path, 0o644)  # u+w so overwrite works
        with open(proof_path, "w") as f:
            f.write(proof)
        os.chmod(proof_path, 0o444)  # a-w, same as formal's Makefile
        result["proof_path"] = proof_path
        if check:
            from formal.lean import check_proof_cached
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ok, detail, cached, n_sorries = check_proof_cached(
                proof_path, repo_root=repo_root)
            result["proof_checked"] = ok
            result["proof_cached"] = cached
            result["proof_sorries"] = n_sorries
            if not ok:
                raise FormalBuildError(f"proof check failed: {detail}")

    return result


def _formal_module_functions(source_path: str, link_dylibs: list = None,
                             arch: str = "arm64", fmt: str = None,
                             link_manifests: list = None) -> tuple[str, list]:
    """The functions and structs of a MODULE, for the library build.

    `link_dylibs` is the program's dependency set: a module's own build has to
    resolve the same imports the program does, or a name the module reads
    resolves against no library. `arch`/`fmt` are the EXECUTABLE's target,
    because the dylib is an image for the machine that will link it — the same
    pair `formal/imports.py` keys its build cache on, and the reason a module
    compiled for one target and linked into another was wrong rather than
    refused.

    `link_manifests` is `load_dylib_manifests`'s answer for `link_dylibs`,
    passed in so the late frame checks can read a per-parameter frame-holder
    contract off the link line without re-reading every manifest once per source
    file of the library."""
    try:
        with open(source_path) as f:
            source = f.read()
    except OSError as e:
        raise FormalBuildError(f"cannot read {source_path}: {e}")
    try:
        stmts = parse_module(source, filename=source_path)
    except SyntaxError as e:
        raise FormalBuildError(f"{source_path}: parse error: {e}")
    # A module with no top-level functions is NOT an error here. binary_heap
    # and a third of std/ are struct-only, and they used to be rejected with
    # "no top-level functions" — which was not merely premature but wrong: the
    # question is not whether the file has functions but whether it has
    # anything to EXPORT, and that is answered by reflect.collect_exports_src
    # (which finds nothing in binary_heap either, so it is refused a moment
    # later, by the check that can actually say why). Reporting the accurate
    # reason matters: "no top-level functions" reads like a codegen gap.
    # The dylib is an image for the same target as the executable that will
    # link it, and it is the executable's own `arch`/`fmt` that decides it
    # (formal/imports.py keys its build cache on them for exactly that reason).
    # Published HERE because it is the first thing in the dylib pipeline that
    # knows the pair, and `_prepare_functions` is what every reader below
    # consults.
    M.publish_target(M.target_for(arch, fmt or default_format(arch)))
    #
    # `as_dylib=True` because a LIBRARY has no entry point. A module whose API
    # is its top-level statements — `sep = "/"` — compiles here to a dylib that
    # exports nothing, has no code to run the store, and is then refused by
    # `no_public_api_reason` for the wrong reason ("no public functions"), which
    # sends the reader looking for a missing `def` when the file has exactly
    # what it meant to write. The body is refused by name here instead, which is
    # the same message the executable path gives and the same answer the reader
    # needs: a module-level store needs storage, and this path has none
    # (`bugs/FORMAL_module_state_no_storage.md`).
    functions, structs, symbols, slots = _prepare_functions(
        stmts, synthetic=False, as_dylib=True)
    # The other of the two call sites of `check_frame_field_blob_premises`, and
    # for the same reason: this is the dylib path, it has no import resolution
    # of its own to be preempted by, and the check has to apply to a dylib
    # exactly as it does to an executable or the invariant is a property of one
    # front end.  Marked as a call site so the pair stays findable.
    #
    # …and the other of the two call sites of `check_construction_shapes`, for
    # the same two reasons: this is the dylib path, and a refusal raised from
    # `_prepare_functions` would report a construction gap in a file whose
    # import is the more fundamental fact.
    #
    # BOTH wrapped, and the wrapping is a fix rather than a courtesy: this
    # function's caller has its `except CodegenError` around the CODEGEN step
    # only, so a refusal from either check reached the sweep as a raised
    # exception and was classified `backend-crash` — a verdict for a compiler
    # bug, on a construct that is a refusal.  Measured: with the check outside
    # the wrapper, `std/gpu/host/func_attribute.mojo` went from a named
    # `codegen` finding to `backend-crash`.
    from formal.imports import imported_modules
    try:
        # `link_manifests` is `compile_formal_dylib`'s own `linked`, passed in
        # rather than re-read from `link_dylibs` here: a library is compiled
        # from SEVERAL sources and this function runs once per source, so
        # re-reading would parse every manifest once per file of the library.
        # A module dylib needs the link line for the same reason an executable
        # does — its own functions can hand a frame to a function in one of ITS
        # imports, and `check_imported_frame_handoffs` is what decides that.
        _run_late_checks(stmts, functions, structs, symbols, slots,
                         imported_modules(stmts) if link_dylibs else None,
                         link_manifests or [])
    except CodegenError as e:
        raise FormalBuildError(str(e))
    module = re.sub(r"[^A-Za-z0-9_]", "_",
                    os.path.splitext(os.path.basename(source_path))[0])
    return module, functions, source, structs, slots, _module_constants(symbols)
    return module, functions, source, structs, slots


def _run_late_checks(stmts: list, functions: list, structs: list,
                     symbols: dict, slots: dict,
                     imported_module_names, link_line=None) -> None:
    """Publish this unit's module-level tables, then run every late check.

    ONE function for the two front ends, and the reason is a measured drift
    rather than a tidiness preference: this block was open-coded at both call
    sites (`compile_formal` and `_formal_module_functions`), and merging four
    branches into one tree showed what that costs — `formal-module-state` had
    to remember to add `publish_global_slots` in two places and widen
    `_prepare_functions`'s return from three values to four in both, and
    `mod-dataclasses` had to remember to add `check_dataclass_constructs` in
    two places. Two of four branches each paid double for the same capability,
    and nothing would have failed if one had paid once. The set of checks is
    therefore decided once, here, and the next one is a line rather than an
    edit to two call sites that must agree.

    THE ORDER IS LOAD-BEARING and is the reason this is not just a list:

      * **publish first, always.** The two tables are re-published here rather
        than at their construction because building an import is a NESTED
        `_prepare_functions` — each imported module is compiled in full into a
        dylib — and each one publishes ITS module's globals over ours. The
        symptom when this was skipped was measured, and it was exactly the
        two-architecture split this design exists to prevent: `_assembly.mojo`
        refused `'_get_kgen_string'` with the message naming THIS module on
        arm64 and the one naming the imported module on x86-64, because the
        two architectures built the dylibs in a different order and so had a
        different module's table published at the point the check read it.
      * **`check_module_symbols` LAST.** It is the check with the fullest
        story — "this path places a name in a register, a spill slot, a
        receiver field's frame, or a folded module constant, and yours is in
        none of them" — so a file that has a more specific problem should
        report that one, and every check above it is more specific.
      * **after the imports resolved, which is why this is HERE and not inside
        `_prepare_functions`.** A file that imports a host module is out of
        reach whatever its codegen says; raising this earlier reported the
        secondary problem in 67 files and moved the coverage denominator for
        it (`check_frame_field_blob_premises`), and 14 more for the
        construction check.

    Raises `CodegenError`. Both call sites wrap it, and the wrapping is a fix
    rather than a courtesy: each caller's `except CodegenError` is around
    `_prepare_functions` / the codegen step only, so a refusal from here
    reached the sweep as a raised exception and was classified `backend-crash`
    — a verdict for a compiler bug, on a construct that is a refusal. Measured:
    with the construction check outside the wrapper,
    `std/gpu/host/func_attribute.mojo` went from a named `codegen` finding to
    `backend-crash`.

    `imported_module_names` is `imported_modules(stmts)` GATED by the caller
    on whether the build has any module dylib to link, and the gate is
    load-bearing rather than defensive: `_resolve_imports` is a no-op for a
    target with no module mechanism (an ELF image: no dylib form, nothing to
    link), so on that target an `import` produces no library and a dotted call
    `mod.f()` has no symbol to bind. Handing the checker the module names there
    would stop it refusing that call and let the image be emitted with a `BL`
    against a symbol nothing defines — refused today, a load-time failure after
    this change. No module dylib on the line, no dotted call."""
    M.publish_module_symbols(symbols)
    M.publish_global_slots(slots)
    by_name = {st.name: st for st in structs}
    check_frame_field_blob_premises(structs)
    check_frame_subscript_escapes(functions)
    # Three more late frame checks, each added by a later branch and each paid
    # for twice while this block was open-coded at both call sites — which is the
    # drift `_run_late_checks` exists to stop. They keep the order they had at
    # their own call site: a holder rebound from a word, a construction whose
    # shape does not match, and a module global shadowed by a local read.
    check_frame_holder_rebinds(functions)
    check_construction_mismatches(functions)
    check_shadowed_global_reads(functions)
    check_construction_shapes(functions, by_name)
    check_frame_return_shapes(functions)
    # …and the one hole the returned-frame convention opens in premise (B1),
    # which is the same premise with the sign reversed.
    check_returned_frame_blob_writes(functions)
    # The ONE late check that can also be an ANSWER rather than a report, which
    # is why it is here and not in the group above: a frame address reaching a
    # callee compiled into another module is decided from the contract that
    # module's manifest published, and when the contract says the parameter is a
    # frame holder of a struct this image also has, the hand-off is followed and
    # nothing is raised.  It needs `link_line` — the link line's manifests —
    # which is why it is the one check with a new argument rather than one of
    # the five that only need this unit's own tables.
    check_imported_frame_handoffs(functions, link_line or [])
    # A `@dataclass` option this backend cannot lower is a fact about the FILE
    # rather than about the image, so it belongs with this group rather than
    # with the construct checks that only an executable's codegen can answer.
    check_dataclass_constructs(stmts, functions)
    check_module_symbols(functions, by_name,
                         imported_module_names=imported_module_names,
                         link_line=link_line)


def _struct_methods(stmts: list) -> list:
    """A struct's methods, as ordinary functions named `<Struct>_<method>`.

    They have to be lifted out because nothing else puts them in the compiled
    set: `_extract_functions` takes only module-level FunctionDefs, so a
    method was invisible to the codegen and `c.get()` fell through the call
    path to a BL against a symbol literally spelled `c.get` — the receiver's
    own name glued to the method's. Every such program built and then died in
    dyld.

    A one-word struct additionally needs `self.<field>` to mean `self`,
    since the receiver IS the field. That rule is applied where member
    accesses are lowered, not by rewriting the AST here: expressing it as an
    empty-member MemberExpr sends every later AST pass into infinite
    recursion, because a member access whose object is itself is a cycle.

    A struct of MORE than one field is lifted too when the by-reference
    receiver is on (`formal.model.struct_is_framed`): its receiver word is
    the address of a frame of fields, so `self.<field>` is a load from
    `[self, #8k]` rather than a rewrite, and the method needs no special
    casing at all — which is the whole dividend of the by-reference design.
    """
    out = []
    for st in stmts:
        if not isinstance(st, F.StructDef):
            continue
        for m in M.struct_methods(st):
            if not M.struct_fits_one_word(st) \
                    and not M.struct_is_framed(st):
                # Not compiled, and not exported — but NOT an error here. The
                # body would read `self.<field>` as a field of an integer, so
                # it cannot be lowered; refusing at DECLARATION though broke
                # every module that merely mentions such a method, including
                # ones that never call it and built and ran correctly before
                # (the sweep lost five files to it). A method that is declared
                # and never called costs nothing; the refusal belongs at the
                # call site, which is where _rewrite_method_calls puts it.
                continue
            fn = copy.deepcopy(m)
            fn.name = M.method_function_name(st.name, m.name)
            out.append(fn)
    return out


# ── A frame-pointer receiver: which names hold one, and what may hold one ──
#
# A struct of more than one field is lowered with its receiver BY REFERENCE
# (`formal/model.py`'s `struct_is_framed`): the receiver word is the ADDRESS of
# an out-of-line frame of 8-byte slots, so `h.x` is a load from `[h, #8k]` and
# `h.x = v` a store. Nothing in the value model changes — a pointer is one word
# — and `_rewrite_method_calls` needs no change either, because the receiver it
# already passes IS that address.
#
# What this function decides, and it has to be decided ONCE and in the build
# pass, is which local names hold such an address. Two instances of one struct
# get two frames and so never alias; but that is only true if the name holding
# an instance is the SAME name at the write and at the read, which on a path
# with no type inference means recognising the binding rather than inferring
# the type. That is the same discipline, and the same limitation, as
# `_one_word_field_map` above: found from the binding, not inferred.
#
# Everything a holder may NOT do is a REFUSAL naming the construct, and that is
# the point of the rule rather than a limitation of it. A frame lives in the
# frame of the function that created it, so a holder that escapes — returned,
# stored in a container, handed to a callee this module cannot see — would be
# read back as whatever now occupies those bytes, and the program would build,
# run, and be wrong. Refusing by name is the only honest answer available, and
# it is available because the value is a pointer and the escape is visible in
# the source.


def _root_ident(node):
    """`(name, depth)` for a chain of `.member` hops over a plain name, else None.

    `depth` is how many hops there are, which is what separates a frame slot
    (`h.x`, depth 1) from a field OF a field (`h.sub.x`, depth 2) — the second
    has no representation here, because slot `k` holds one 64-bit word and that
    word is a field, not a struct.

    None for anything the hops do not account for, and that is load-bearing
    rather than tidy: `h[i].f` and `f(h).g` both bottom out at a name but are
    NOT `h.f`, and a chain that reached the frame-slot table through a
    subscript would silently read the wrong word. So the walk has to be
    MemberExpr all the way down, and anything else is None — which sends it to
    the ordinary local-slot lowering, i.e. to the pre-existing behaviour, not
    to a frame access."""
    depth = 0
    while isinstance(node, F.MemberExpr):
        depth += 1
        node = node.obj
    if isinstance(node, F.IdentExpr):
        return (node.name, depth)
    return None


def _frame_argument_slots(call, params):
    """`(position, expression, keyword_name)` for every argument of `call`.

    The position is a PARAMETER index, not an index into `args + kwargs`.  A
    positional argument's is its own index; a keyword argument's is looked up
    BY NAME, and a keyword naming no parameter yields nothing — that argument
    then has no position in the callee, which is the opaque case
    `model.frame_opaque_position_refusal` describes rather than a position
    question.

    A parameter list of `None` (a callee this image does not have) yields only
    the positional indices, so a caller can still say *which* argument it is
    looking at; whether that argument lands on a parameter is the caller's
    separate question.

    Why the keyword is resolved by name and not by its place in
    `args + kwargs`: the position of a keyword argument is the parameter list's
    statement about where it lands, and the concatenated list is this pass's.
    `take(x=1, y=r)` has `y` at index 1 of the concatenation, which happens to
    be right; `take(y=r, x=1)` has it at index 1 as well, which is wrong — `y`
    is the SECOND parameter there and `x` the first, and following index 1
    would make `x` a frame holder.  A wrong holder is a wrong answer, not a
    refusal, so the name is the only thing safe to go on.  The keyword's own
    name is carried out as well because a diagnostic that quotes an index is
    quoting this list, and a reader comparing it against `take(y=r, x=1)` in
    their own source is being sent to the wrong argument."""
    out = []
    for i, a in enumerate(call.args or []):
        if i < len(params) or not params:
            out.append((i, a, None))
    for kwname, value in (call.kwargs or []):
        if kwname in params:
            out.append((params.index(kwname), value, kwname))
    return out


# `a.b.c` for a MemberExpr chain, spelled the way the source spells it:
# `model.member_chain_text`, the one chain spelling in the tree.
#
# It used to be spelled here as well, and it was here because the messages
# wanted it: `_root_ident` reports a chain's root and depth and nothing else,
# which is the right answer for a lookup and the wrong one for a MESSAGE.  The
# old field-of-a-field diagnostic printed `base.member`, so a refusal about
# `self.asm.emit` read as though the source said `self.emit`, and the reader
# went looking for a field of the wrong name. Every refusal that talks about a
# chain spells the chain, and one function does the spelling.
_member_chain = M.member_chain_text


# `q[0]`, `REGISTRY[s.name]`. The implementation is the model's
# (`model.subscript_chain_text`) for the reason `expr_spelling` below is an
# alias: the model owns the one spelling of an expression, and a second copy
# here is a second convention for a diagnostic a reader has to learn.  This
# local name is kept because two call sites in this file read better with it
# than with the model's, and renaming them would be churn.
_subscript_chain = M.subscript_chain_text


def _callee_wants_a_value(callee: str) -> bool:
    """Does `callee()` read its argument as a VALUE, whatever the position?

    POSITIVE, and the word matters: `frame_receiver_escape_refusal` answers for
    five cases and its fifth is "a name with no definition in hand", which is
    not a statement about what the callee wants with its argument — it is a
    statement about there being no callee.  Asking that function whether the
    callee wants a value therefore answers YES for every name in the image,
    because every name this module compiles reaches its fifth case, and a
    predicate like that refuses the entire hand-off family.  So the four cases
    that really are about the argument are named here, and the fifth is left to
    `_check_frame_escapes`'s own "is it in this image" question, which is the
    question that decides it.

    The tables are the model's, read at call time rather than copied: a
    hand-written copy of a sort this file and `formal/model.py` both make is
    how the two come apart, and they are the same question."""
    # `FRAME_ADDRESS_CTORS` is excluded FIRST and it is not a detail.
    # `Pointer` and its siblings are `identity` type constructors, so
    # `type_constructor_kind` calls them "identity" and the `kind` test below
    # would say they want a value — when handing one a frame address is the
    # ONE hand-off in this family that is simply correct, and
    # `frame_receiver_escape_refusal` returns None for it.  Measured, with the
    # exclusion missing: `Pointer(0, r)` was refused with
    #
    #   a R receiver is passed to Pointer(), a C library entry point, in
    #   argument position 1 of 2. This is not a question about the position:
    #   Pointer() is variadic and takes its arguments as values …
    #
    # Every clause of which is false: `Pointer` is not a C entry point, it is
    # not variadic, and the thing that refuses it is an arity check two frames
    # away.  A message that asserts a mechanism which is not operating sends
    # the reader after a non-bug, which is the whole defect this file exists to
    # stop — and it is a worse one than the sentence it replaced, because the
    # sentence it replaced at least said "a position this path cannot see".
    if callee in M.FRAME_ADDRESS_CTORS:
        return False
    if callee in M.FRAME_C_LIBRARY_CALLS or callee in M.FRAME_C_VALUE_CALLS:
        return True
    if callee in M.FRAME_VALUE_ONLY_CALLS:
        return True
    kind = M.type_constructor_kind(callee)
    return kind is not None and kind[0] in ("unsupported", "identity")


def _check_holder_agreements(functions, holders, hstruct, params_of,
                             declared=None, structs_by_name=None,
                             name_defs=None, returns_frame=None) -> None:
    """Refuse a parameter reached with a frame address at one call site and
    with something else at another.  A WHOLE-IMAGE pass, and that is the whole
    content of where it runs.

    The measurable half of "a frame only works as the first parameter", and it
    is measurable at the FIRST position too, which is why it is here and not
    beside the non-first rule.  A parameter is a frame holder or it is not, and
    that is a property of every call site at once:

    ```
    struct R: var a: Int; var b: Int
    def f(x: Int, y: Int) -> Int: return x.a
    def main(n: Int) -> Int:
        var r = R(); r.a = 7; r.b = 8
        return f(r, 1) + f(2, 3)
    ```

    `f` is compiled with `x` a frame holder, so `x.a` is a load at `base + 0` —
    and `f(2, 3)` arrives with `x = 2`, where there is no frame.  **Measured on
    both architectures, with nothing lifted: it builds, runs, and dies with
    SIGSEGV, exit 139.**  That is in the shipped tree and predates every
    position rule; the family was written about the wrong defect.

    WHY A SEPARATE PASS AND NOT A BRANCH IN `_check_frame_escapes`, which is
    where every other channel out of a frame is caught: that function is called
    once per function and only for the functions that HOLD a frame, because
    every branch in it needs a non-empty holder set to have anything to say.
    The call site that has to be caught here can be in a function that holds no
    frame at all — `f(r, 1) + f(2, 3)` with the second call in a function that
    never mentions `r` — and skipping those is not a small omission: it is
    precisely the case where the disagreement is invisible from the frame's own
    function.  Measured: with the check inside `_check_frame_escapes`, that
    program built and died with SIGSEGV on both architectures.

    `declared` is `{fn name: {parameter}}`, the holders whose status came from a
    DECLARED type rather than from a call site, and it adds the one case the
    two-bucket rule below cannot express.  Those holders are the ones with no
    frame-side to compare against by construction: `Slice.__eq__` is a method
    nothing in the image calls, so there is no site handing `other` a frame and
    `holder_spellings` is empty however many sites pass something else.  The
    rule as written reads that as agreement (`if not holder_spellings or not
    plain_spellings: continue`) and emits a load from `base + 8k` on a word that
    is not an address — which is the silently-wrong outcome this pass exists to
    make impossible, reached through the fix rather than around it.  So for
    these parameters the question is not "do the sites agree with each other"
    but "does ANY site agree with the declaration", and the answer being no is
    a refusal naming the declaration and every site.
    """
    declared = declared or {}
    name_defs = name_defs if name_defs is not None else {}
    for fn in functions:
        hs = holders.get(_fn_key(fn)) or ()
        by_name = hstruct.get(_fn_key(fn)) or {}
        for node in M.iter_nodes(fn.body):
            if not isinstance(node, F.CallExpr):
                continue
            callee = M.call_callee_name(node.func)
            if callee is None:
                continue
            # A by-NAME read of a per-function table, and this loop runs ONCE
            # PER DEFINITION of the name rather than skipping the name when it
            # has several. That is the whole of what keeps this sound against an
            # OVERLOADED callee, and it is the reason the fixpoint's hand-off
            # edge declining to guess was not enough on its own.
            #
            # The reason is what the emitters do with an overloaded name: both
            # backends register functions in one table keyed by name
            # (`self._functions[f.name] = f`), so a name with two definitions
            # is ONE function in the image and a call to it reaches whichever
            # body was registered last. There is no resolution here to appeal
            # to — the image genuinely has one `pick` — so "does every call site
            # agree with what `pick`'s parameter was compiled to expect" has to
            # be asked of EVERY definition, because any of them is the one that
            # runs. Skipping the ambiguous name instead (which is what the
            # hand-off edge does, correctly, since it must pick one) drops the
            # check exactly where it is needed, and the program builds and
            # returns a number the source never wrote: measured on
            # `def pick(ref value: A)` / `def pick[K](ref value: B)` called once
            # with each, keying the tables per definition lifted the refusal and
            # the image read `A.pad` where the source says `A.src` (7 for 42).
            #
            # Asking per definition rather than per name also means the two
            # `pick` bodies are each measured against the call sites that could
            # reach them, which is the only reading under which "every call site
            # agrees" is a statement about the program.
            for def_fn in (name_defs.get(callee) or ()):
                params = params_of.get(_fn_key(def_fn))
                if not params:
                    continue
                _check_one_callee(functions, fn, callee, def_fn, params, node,
                                  hs, holders, hstruct, declared,
                                  structs_by_name or {}, returns_frame)


def _check_one_callee(functions, fn, callee, def_fn, params, node, hs,
                      holders, hstruct, declared, structs_by_name,
                      returns_frame=None) -> None:
    """One definition's worth of the holder-agreement check, for one call site.

    The body of `_check_holder_agreements`'s per-callee loop, split out so it
    can run once per DEFINITION of an overloaded name rather than once per name
    — which is what the call there explains and what keeps it sound when both
    backends register one function per NAME.
    """
    by_decl = declared.get(_fn_key(def_fn)) or {}
    for position, arg, _kw in _frame_argument_slots(node, params):
        pname = params[position] if position < len(params) else None
        if not pname:
            continue
        here = isinstance(arg, F.IdentExpr) and arg.name in hs
        there = pname in (holders.get(_fn_key(def_fn)) or ())
        if pname in by_decl:
            _check_declared_parameter(
                functions, callee, position, pname, by_decl[pname],
                holders, hstruct, structs_by_name, params, returns_frame)
            continue
        if here == there:
            # Both frame addresses, or neither.  A parameter reached one
            # way at every call site is the case the by-reference
            # design exists for, and it says nothing here.
            continue
        # Every call site of this parameter, sorted into the two kinds
        # and spelled as the source spells it.  BOTH lists go into the
        # message rather than "this one and the others", because either
        # site can be the one the reader is standing at and a message
        # that names the wrong one of the pair is the same defect as a
        # message that names the wrong reason: it sends the reader to a
        # call that is fine.
        holder_spellings, plain_spellings, structs = [], [], []
        for site_fn in functions:
            for site in M.iter_nodes(site_fn.body):
                if not isinstance(site, F.CallExpr) \
                        or M.call_callee_name(site.func) != callee:
                    continue
                for i, a, _k in _frame_argument_slots(site, params):
                    if i != position:
                        continue
                    site_holder = isinstance(a, F.IdentExpr) \
                        and a.name in holders.get(_fn_key(site_fn), ())
                    spelling = _call_spelling(site, a, position, pname)
                    bucket = (holder_spellings if site_holder
                              else plain_spellings)
                    if spelling not in bucket:
                        bucket.append(spelling)
                    for st in (hstruct.get(_fn_key(site_fn), {})
                               .get(a.name) or ()) if site_holder else ():
                        if st.name not in structs:
                            structs.append(st.name)
        if not holder_spellings or not plain_spellings:
            continue
        raise CodegenError(M.frame_holder_disagreement_refusal(
            callee, position, pname, structs, holder_spellings,
            plain_spellings))


def _frame_valued_calls(site_fn, structs_by_name, returns_frame, fns):
    """`{id(call): ([struct name], why)}` — the calls in `site_fn` whose VALUE is
    a frame address, read off the tables the emitters build their blocks from.

    **Two more shapes than `_argument_frames` used to know, and they are read
    off the emitters' own tables rather than re-derived here.**  A frame address
    reaches a callee through a constructor call (`f(Pair(3, 4))` — the emitter
    reserves a block per construction site in the prologue and the
    construction's value is its address, `formal/arm64_codegen.py`'s
    `_emit_frame_constructor`) or through a call to a function that RETURNS one
    (`f(make())` — `model.struct_returned_frame_sites`, the caller's half of the
    same arrangement).  Both are frames at the call site in the same sense
    `f(r)` is, and the emitters lower them; a check that cannot see them reads
    those two programs as "the declaration is contradicted at every call site"
    when the call site is handing over precisely the value the declaration
    promised.  That is `formal/types.py`'s `mask_of(IntType(w, False))` and it
    is the whole of the false-refusal half of the 13-file
    `frame_declared_parameter_refusal` row in
    `bugs/FORMAL_declared_parameter_against_its_call_sites.md` §2.

    **So the recogniser is shared, not parallel.**  `struct_constructor_sites`
    and `struct_returned_frame_sites` are the tables both backends reserve their
    scratch from, and the construction case additionally goes through
    `model.call_lowers_as_framed_construction` — the emitter's own dispatch
    predicate, which is what keeps `String()` (a type CONVERSION, and a plain
    word) out of this set while `Pair(3, 4)` (a construction, and an address) is
    in it.  A second implementation of "is this call a frame" would agree with
    the emitters until the day one of them was edited, and the disagreement is a
    refusal lifted on a word that is not an address: a wrong answer rather than
    a failure.

    `returns_frame` is the fixpoint's `{callee name: struct}`, the same
    dictionary published on every function as `_image_returns_frame` and read by
    both emitters through `struct_returned_frame_sites`.  It is handed over as
    `model.frame_returning_predicate(...)` rather than as `dict.get`, for the
    reason that function's docstring gives: the callee asks with TWO arguments
    and `dict.get`'s second is a default, so a missing callee would answer with
    the bound name.
    """
    out = {}
    constructors = M.struct_constructor_sites(site_fn, structs_by_name)
    returned = M.struct_returned_frame_sites(
        site_fn, structs_by_name,
        M.frame_returning_predicate(returns_frame or {}))
    if not constructors and not returned:
        return out
    for node in M.iter_nodes(getattr(site_fn, "body", None)):
        if not isinstance(node, F.CallExpr) \
                or not isinstance(node.func, F.IdentExpr):
            continue
        built = constructors.get(id(node))
        if built is not None and M.call_lowers_as_framed_construction(
                node.func.name, structs_by_name,
                len(node.args or []) + len(node.kwargs or []), fns):
            out[id(node)] = ([built[0].name],
                             f"a {built[0].name} frame built here")
            continue
        got = returned.get(id(node))
        if got is not None:
            out[id(node)] = ([got[0].name],
                             f"a {got[0].name} frame from {node.func.name}()")
    return out


def _argument_frames(site_fn, arg, holders, hstruct, structs_by_name,
                     frame_calls=None):
    """The frame addresses `arg` could be at this call site, and what if not.

    `([struct names], why)` — the structs whose FRAME the argument is, when this
    image can say so, and otherwise the sentence a refusal should use for what
    the argument turned out to be instead.  The two are not the same question:
    an argument this analysis cannot place is not evidence of anything, and a
    caller has to be told which of the two it is looking at.

    Four shapes put an address on the stack for a callee, and they are the only
    four:

      * a bare NAME the site function's holder analysis recognised — the
        ordinary `f(r)` with `r` a frame;
      * a FIELD access whose root is a holder and whose slot holds a PLACED
        NESTED FRAME (`take(self.in1)`), which is an address too.  That question
        is `_typed_nested_frame`, the one place `struct_nested_frame_fields`'
        placement is decided, and it is asked here rather than read off a
        published table because the table records only the CALL shape
        `h.a.m()`, and a nested frame handed over as an ordinary argument never
        appears in it;
      * a CONSTRUCTION of a framed struct — `f(Pair(3, 4))`;
      * a call to a function that RETURNS a frame — `f(make())`.

    The last two are `frame_calls`, `_frame_valued_calls`'s table, and they are
    the two the emitters already lower; they were missing here, which is what
    made `_check_declared_parameter` refuse a program whose call sites agree
    with the declaration.

    A frame of the WRONG struct comes back as a non-empty list naming it,
    which is the whole point of returning the list rather than a bool: `base +
    8k` is one layout, and reading another struct's word through it is the wrong
    answer rather than a failure.
    """
    if isinstance(arg, F.IdentExpr):
        if arg.name not in (holders.get(_fn_key(site_fn)) or ()):
            return ([], _describe_value(arg))
        names = [st.name for st in
                 ((hstruct.get(_fn_key(site_fn)) or {}).get(arg.name) or ())]
        why = f"a {'/'.join(names)} frame" if names else "an unplaced one"
        return (names, why)
    key = _root_ident(arg)
    if key is not None and key[1] == 1 and isinstance(arg, F.MemberExpr) \
            and key[0] in (holders.get(_fn_key(site_fn)) or ()):
        nested = _typed_nested_frame(key[0], arg.member,
                                     ((hstruct.get(_fn_key(site_fn)) or {})
                                      .get(key[0]) or ()),
                                     structs_by_name, None)
        if isinstance(nested, F.StructDef):
            return ([nested.name], f"a {nested.name} nested frame")
    placed = (frame_calls or {}).get(id(arg))
    if placed is not None:
        return (placed[0], placed[1])
    return ([], _describe_value(arg))


def _check_declared_parameter(functions, callee, position, pname, want,
                              holders, hstruct, structs_by_name,
                              params, returns_frame=None) -> None:
    """A parameter this image classified from its DECLARED type: refuse any
    call site that hands it something of the wrong shape.

    Two kinds share this check because they are the same decision read twice,
    and the decision is always "does this image corroborate the declaration":
    a parameter declared as a framed struct is compiled as a frame ADDRESS, and
    one declared as a one-field struct is compiled as that struct's only FIELD.
    Both are facts about every call site at once, and neither is a fact about
    one.

    The hole this closes is reachable only through the fix, which is why it is
    worth stating rather than leaving to the two-bucket rule beside it.  Before
    a declaration could classify a parameter, that happened only when a call
    site handed it a frame, so `f(r, 1)` beside `f(2, 3)` was the disagreement
    and both buckets were non-empty.  A declaration has no such site — the
    construct exists precisely because the method is called from nowhere in this
    image — so a program that DOES call it with a plain word produced
    `plain_spellings` and an EMPTY `holder_spellings`, which the old rule reads
    as agreement and then loads eight bytes from wherever the word points.

    `want` is the struct the declaration named, which is the struct every other
    consumer reads: the emitter's `base + 8k` is computed from this same table,
    so a message naming a different struct would send the reader to a layout
    that is not the one in the image.

    The rule is therefore "every call site agrees", not "the sites agree with
    each other", and the message names the declaration, the parameter and every
    site: either can be the one the reader is standing at.

    A method with NO call site in the image is not this function's business —
    that is the construct being fixed, there is nothing to disagree with, and
    `sites` being empty is what "nothing to say" looks like here.

    **What counts as a call site that AGREES.**  `_argument_frames` says which
    frame an argument is, and the four shapes it knows are the four the emitters
    put a frame ADDRESS in that slot: a placed nested field, a holder name, a
    construction, a frame-returning call (`_frame_valued_calls` for the last
    two, read off the emitters' own block tables).  An argument outside that set
    is not evidence against the declaration — it is an argument this path cannot
    place — and the two are not the same answer, so they do not get the same
    one.  Reading "cannot place" as "contradiction" is what refused
    `mask_of(IntType(w, False))`, whose call site hands over exactly the value
    the declaration promised; measured, the image that refusal was standing in
    front of builds, runs and returns 7, which is what CPython returns for the
    same program.
    """
    framed = M.struct_is_framed(want)
    fns = [f.name for f in functions]
    # One table per SITE FUNCTION, built on first use: the loop below asks
    # about every call of `callee` in the image, and recomputing this per
    # argument would walk every body once per argument.
    frame_calls: dict = {}
    sites = []
    for site_fn in functions:
        for site in M.iter_nodes(site_fn.body):
            if not isinstance(site, F.CallExpr) \
                    or not isinstance(site.func, F.IdentExpr) \
                    or site.func.name != callee:
                continue
            for i, a, _k in _frame_argument_slots(site, params):
                if i != position:
                    continue
                key = _fn_key(site_fn)
                if key not in frame_calls:
                    frame_calls[key] = _frame_valued_calls(
                        site_fn, structs_by_name, returns_frame, fns)
                cands, why = _argument_frames(site_fn, a, holders, hstruct,
                                              structs_by_name,
                                              frame_calls[key])
                # A framed declaration is corroborated by a frame OF THAT
                # STRUCT; a one-field one is corroborated by anything that is
                # not a frame address at all, because its value is one word and
                # this path cannot say which word — the same trust a one-field
                # RECEIVER already gets, and refused the moment the site is
                # provably handing over an address instead.
                ok = want.name in cands if framed else not cands
                if not ok:
                    sites.append((_call_spelling(site, a, position, pname), why))
    if sites:
        raise CodegenError(M.frame_declared_parameter_refusal(
            callee, position, pname, want.name,
            "the ADDRESS of a frame of 8-byte slots, where every field is a "
            "load at `base + 8k`" if framed else
            "that struct's only field, because the receiver of a one-field "
            "struct IS its field",
            sites))


# The source's own spelling of an expression, and of a `.member` chain, are
# `model.expr_spelling` / `model.member_chain_text`.  Both used to be spelled
# here as well; `model.py` needs them for its own refusals and a model function
# must not reach up into the build pass for a string, so the model owns the one
# implementation and this file calls it.
_expr_spelling = M.expr_spelling


def _expr_spelling(node) -> str:
    """The source's own spelling of an expression, as far as a name needs one.

    A refusal that quotes `CallExpr` where the source wrote `mid(1)` sends the
    reader to the AST to find the call, which is the opposite of what a
    diagnostic quoting a call site is for.  A shape with no short spelling is
    named by its type, which is at least a true statement and is obviously a
    placeholder to anyone who reads it.

    The OPERATOR arms came later than the rest and the reason is a message that
    read `G is read in bump() at BinaryOp` — a true statement, a placeholder,
    and useless, because the reader's question is which read.  Every refusal that
    quotes a value goes through this one function, so the fix belongs here rather
    than in each caller."""
    if isinstance(node, F.IdentExpr):
        return node.name
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.IdentExpr):
        return f"{node.func.name}({', '.join(_expr_spelling(a) for a in (node.args or []))})"
    if isinstance(node, F.MemberExpr):
        return _member_chain(node)
    if isinstance(node, F.BinaryOp):
        return (f"{_expr_spelling(node.left)} {node.op} "
                f"{_expr_spelling(node.right)}")
    if isinstance(node, F.UnaryOp):
        return f"{node.op}{_expr_spelling(node.operand)}"
    if isinstance(node, (F.ListExpr, F.TupleExpr, F.SetExpr)):
        return (f"{'(' if isinstance(node, F.TupleExpr) else ''}"
                f"{', '.join(_expr_spelling(e) for e in node.elements)}"
                f"{')' if isinstance(node, F.TupleExpr) else ''}")
    if isinstance(node, F.SubscriptExpr):
        return f"{_expr_spelling(node.obj)}[{_expr_spelling(node.index)}]"
    for attr in ("value", "name"):
        v = getattr(node, attr, None)
        if isinstance(v, (str, int, float, bool)):
            return str(v)
    return type(node).__name__


def _call_spelling(call, arg, position, pname) -> str:
    """`f(2, 3)` — the call as the source spells it, for the disagreement.

    The callee is spelled through `_expr_spelling` and not `call.func.name`,
    because a call whose name this pass had to look through — `f[1](2, 3)` —
    has no `.name` on its func node at all.  That is not a defensive shape: a
    disagreement is reported by quoting BOTH call sites, so a spelling that
    raised on exactly the calls it exists to quote would turn a refusal into a
    crash, and the crash would be the *safety* check this family is built out
    of (`model.frame_holder_disagreement_refusal`).
    """
    parts = [_expr_spelling(a) for a in (call.args or [])]
    for k, v in (call.kwargs or []):
        parts.append(f"{k}={_expr_spelling(v)}")
    return f"{_expr_spelling(call.func)}({', '.join(parts)})"


# Every function in the image under analysis, published by `_frame_receivers`.
#
# `_check_holder_agreement` has to name the OTHER call sites of a callee, and a
# call site is a node inside some function's body — so it needs the function
# OBJECTS, which the holder maps (keyed by name, holding name sets) do not
# carry.  A module-level list rather than a parameter because the disagreement
# is a property of the whole image and threading the image through every
# `_check_frame_escapes` call to reach one message would put a global's worth of
# plumbing in the way of the common case.  It is REBOUND, never appended to, so
# a second unit in the same process (the dylib build compiles several) cannot
# see the first one's functions.
_IMAGE_FUNCTIONS = ()


def _call_receivers(fn):
    """The `id()` of every MemberExpr used as `X.m(...)`'s — or `X.m[T](...)`'s
    — callee object.

    POSITION, not shape, and the distinction is the whole of the largest group
    in the sweep. `self.f.g` in a value position is a field of a field: the
    word in slot `k` is a value, and there is no layout behind it. `self.f.g()`
    is a METHOD CALL on that value, and the value is all the callee ever gets
    either way — so the frame layout is not what decides it, and refusing it
    here with a layout diagnostic hides the diagnostic that does decide it
    (`model.value_method_refusal`, which names the method and what the backend
    can lower). Getting this backwards is not a wording problem: with the
    refusal lifted and nothing downstream taught about frame slots, the chain
    reaches `_emit_expr` as a value, misses every slot table, and reads a
    scratch register — a wrong answer rather than a failure.

    **The specialization counts as a call too, and leaving it out is what made
    `recv.m[T](x)` a value-position method reference.** The brackets are a
    generic's comptime parameters, so `b.run[3](4)` is a call in the same sense
    `b.run(4)` is, and both receivers are the same node: the `MemberExpr` under
    the `SubscriptExpr`. The walk therefore looks THROUGH a subscript on the
    callee, which is what `formal/model.py`'s `call_callee_name` does for the
    same reason — one recogniser per question, and both answers say `call`.

    `id()` of the node, because the walk yields nodes and a set of identities
    is the only way to say "this node, in this position" without a second walk
    that could disagree about which nodes it saw."""
    out = set()
    for node in M.iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr):
            continue
        func = node.func
        if isinstance(func, F.SubscriptExpr):
            func = func.obj
        if isinstance(func, F.MemberExpr):
            out.add(id(func))
    return out


# How many times the holder fixpoint below is allowed to saturate-and-rewrite.
# The pair converges in two on anything measured (the second round exists for
# the `__eq__` second-parameter edge and for a `len` reached through a rewritten
# call); the bound is a backstop that raises rather than the alternative, which is
# a hang in the compiler on a program whose rewrite is not monotone.
_HOLDER_FIXPOINT_ROUNDS = 4


def _fn_key(fn):
    """The key every PER-FUNCTION table in the frame analysis is filed under.

    `id(fn)`, and the reason it is identity rather than `fn.name` is that these
    tables answer "what does THIS body do with its own names" — a question one
    definition answers and a second definition of the same name answers
    differently. Mojo overloads make that ordinary: `std/builtin/reversed.mojo`
    declares `reversed` eight times with a different receiver type each time,
    and 53 of the 1595 files in the two sweep roots declare some name more than
    once (measured, `tools/` probe over both roots).

    Keying by name made the first definition's answer stand for all of them,
    which is the wrong answer rather than a refusal: the member read
    `value.src` in `reversed`'s `_DictEntryIter` overload was resolved against
    the `List` overload's candidate struct, so the refusal named a struct the
    program never passed and a field the struct does have. `id` is the right
    identity here because a `FunctionDef` is a plain mutable dataclass (no
    `__hash__`, `eq=True`) that is never copied or re-parsed between the
    fixpoint and the codegen that reads the published attributes — the tables
    are built and consumed within one `_frame_receivers` call.

    A NAME-keyed table is still right where the question is about the name, and
    `param0` is the one that is left: it answers "is this a function in this
    image", which a name answers for every definition of it. The other by-name
    question — "what does a CALL to `f` give back" — is answered by
    `_returns_frame_by_name`, which is a JOIN over the definitions rather than
    one definition's slot, because a call site cannot say which one it reached.
    """
    return id(fn)


def _name_is_overloaded(name_defs: dict, name) -> bool:
    """Whether `name` has more than one definition in this image.

    The question every BY-NAME reader of the frame tables has to ask before it
    answers, and it is asked here rather than at each site because the answer
    is the same fact and one place that reads it is one place to fix.

    A name with two definitions is not a name with one answer: the caller's
    `f(x)` could mean either body, so "is `f`'s first parameter a frame holder"
    is only answerable when both definitions agree. Measured: `reversed` has
    eight, and `pick`-shaped pairs in this repository's own sources differ in
    their receiver's struct, so treating the first as the answer produced a
    refusal against the wrong layout.
    """
    return len(name_defs.get(name) or ()) > 1


def _by_name_holder(name_defs: dict, holders: dict, hstruct: dict, name):
    """`(holder_set, struct_map)` for a NAME, only when its definitions agree.

    The cross-function readers of the holder tables — the hand-off fixpoint's
    edge into a callee, `_check_holder_agreements`, `_argument_frames` — reach
    a callee by NAME, because that is all a call site carries. When the name has
    ONE definition this is that definition's own table and the answer is
    exactly as before.

    When it has SEVERAL it is `(None, None)`, and that is a refusal rather than a
    guess: the call `f(r)` may reach any of them, so "the parameter at position
    0 is a frame address of struct S" is only true of the definition the call
    actually selected, and nothing in this analysis selects one. Returning
    `None` says "this call site's frame-ness cannot be resolved to a
    definition", which every caller already treats as "do not take this edge" —
    so the effect is that an overloaded callee is not claimed to be a holder
    rather than being claimed on behalf of whichever definition sorted first.
    The alternative, keeping today's behaviour, is the defect: it attributes
    one definition's layout to a body that may be a different one, which is
    how `reversed`'s `_DictEntryIter` overload was refused against `List`'s.
    """
    defs = name_defs.get(name) or ()
    if len(defs) != 1:
        return (None, None)
    key = _fn_key(defs[0])
    return (holders.get(key), hstruct.get(key))


def _returns_frame_by_name(name_defs: dict, returns_frame: dict) -> tuple:
    """`({name: struct}, {name: rows})` — what a CALL to `name` hands back.

    The by-name reader of the returned-frame table, and the same agree-or-refuse
    discipline as `_by_name_holder`: a call site carries a name and nothing else,
    so "is the value of `f(...)` a frame address, and whose" is answerable only
    when every definition of `f` gives the same answer. Where they do not
    agree the name is ABSENT from the view — which every reader treats as "this
    call does not hand back a frame" — and the disagreement is reported in the
    second half so the caller can REFUSE it, which is the direction both wrong
    answers fail in (see `model.frame_return_overloads_disagree_refusal`).

    It is also what makes the holder fixpoint TERMINATE, and that is not a
    refinement: `returns_frame` used to be keyed by `fn.name` and written by
    every definition under that name, so two definitions of one name with
    different answers overwrote each other once per pass in opposite directions
    — each pass one stored its struct and the other popped it, `changed` went
    true on both, and the inner `while changed:` never ended. Measured on
    `std/python/bindings.mojo`, whose `PythonTypeBuilder.def_py_init` is
    declared twice (one overload ends `return self`, the other
    `return self.def_py_init[…](…)`): 7819 passes and 4.1 M node walks in 20 s,
    still going, at 0.06 GB flat — the sweep's `-t 30` was the only bound on it,
    and `std/python/bindings.mojo` now refuses in 2.0 s with a specific message
    (the next real finding: calling a compile-time `def` parameter means
    MONOMORPHISING it, and this path does not instantiate type parameters —
    `bugs/FORMAL_known_limits.md` §1.1).

    The per-function table it reads is keyed by `_fn_key`, like every other
    per-function table here, so one definition's answer can no longer overwrite
    another's and the two questions — "what does THIS body return" and "what
    does a CALL to this name return" — stop sharing one slot.

    The rows are `[(definition spelling, answer)]`, because the reader's next
    question is which definition to change and nothing else in the message can
    say it.
    """
    view, conflicts = {}, {}
    for name, defs in (name_defs or {}).items():
        answers = [returns_frame.get(_fn_key(d)) for d in defs]
        if all(a is None for a in answers):
            continue
        # Identity, not `==`: two StructDefs that happen to share a name are two
        # layouts, and the caller reserves a block sized for one of them.
        if len({id(a) for a in answers}) == 1:
            view[name] = answers[0]
            continue
        conflicts[name] = [
            (_definition_spelling(d),
             f"a frame address of {a.name}" if a is not None
             else "an ordinary value")
            for d, a in zip(defs, answers)]
    return view, conflicts


def _definition_spelling(fn) -> str:
    """`f` / `f[K]` — enough to tell two definitions of a name apart.

    The comptime parameters are what a reader has to look at to find the second
    definition, so a refusal that names both without them sends the reader
    through the file looking for a second `def` whose first line is identical.
    """
    names = [n for n in (getattr(fn, "comptime_params", None) or ()) if n]
    return f"{fn.name}[{', '.join(names)}]" if names else fn.name


def _holder_state(holders: dict, hstruct: dict, returns_frame: dict) -> tuple:
    """A comparable snapshot of EVERYTHING the holder fixpoint decides from.

    The holder sets, the candidate structs each holder name may have, and the
    returned-frame table — which are the only mutable inputs to a pass, the
    bodies and the parameter lists being fixed for the duration. Two passes
    that start from equal snapshots decide identically, so a pass that ends
    where it started while reporting progress cannot be followed by a pass
    that settles: that is the certificate the inner loop's backstop refuses on,
    and it is why the comparison is of CONTENT rather than of sizes (a name
    traded for another, or a candidate list replaced by an equal-length one,
    moves no size).
    """
    return (
        tuple(sorted((key, tuple(sorted(names)))
                     for key, names in holders.items())),
        tuple(sorted((key, name, tuple(id(st) for st in structs))
                     for key, by_name in hstruct.items()
                     for name, structs in by_name.items())),
        frozenset((key, id(st)) for key, st in returns_frame.items()),
    )


def _frame_receivers(functions: list, structs_by_name: dict,
                     dc_classes: dict = None, imported: dict = None,
                     star_imports: tuple = (),
                     method_owners: dict = None) -> None:
    """Annotate every function with its frame-pointer receivers and field slots.

    Writes `fn._frame_holders` (the names holding a frame address) and
    `fn._frame_slots` (`{"<holder>.<field>": slot}`, the table the codegen
    intercepts a local load/store with) onto each function, and RAISES for any
    construct a frame address may not take part in. Called once, at the end of
    `_prepare_functions`, so it sees the FINAL function list — after closures
    are flattened and lambdas lifted, because a lifted lambda is a function
    with its own locals and its own receivers.

    `method_owners` is `{function name: struct}` and it is needed HERE rather
    than only at the class-constant rewrites that follow: a `comptime` binding
    read through a receiver is the same read whichever order the two passes run
    in, and `refuse_none_comparisons` runs BEFORE the rewrite that would
    materialize it — so asking it a census that does not know which functions are
    methods is asking a different question than the substitution asks.

    The fixpoint is over one edge only: a call `f(c, …)` in some function where
    `c` is a holder makes `f`'s FIRST parameter a holder. That is the whole of
    interprocedural flow here, and it is sound in the direction that matters
    because it can only ADD holders — a name wrongly added is a name whose
    field accesses become memory accesses, and a name wrongly missing is the
    silent case, which is why every way a holder can be created is enumerated
    rather than inferred.

    A holder's type is a SET of candidates, not one struct, and that is a
    correctness requirement rather than a refinement: `x = A()` on one path and
    `x = B()` on another gives one name two frame layouts, and settling on
    either computes a slot index that is wrong on the other path. See
    `model.struct_frame_slot_candidates` for the two-struct counterexample and
    `model` for why the answer is agree-or-refuse."""
    structs = list(structs_by_name.values())
    global _IMAGE_FUNCTIONS
    _IMAGE_FUNCTIONS = tuple(functions)
    framed = M.framed_struct_names(structs)
    if not framed:
        # A module with no framed struct has no frame anywhere in it, which is a
        # DEFINITE answer about every parameter — each is an ordinary word —
        # and not the absence of one.  The distinction is load-bearing for the
        # contract this publishes: `def bump(x: Int, by: Int)` in a module that
        # declares no struct is exactly the case where a consumer must be told
        # "that slot is a plain word" rather than "nothing is known about it",
        # and publishing nothing there made the consumer report the second for
        # the first.  The holder tables stay empty, which is what the rest of
        # this function would have computed.
        for fn in functions:
            fn._frame_param_contract = [None] * len(
                M.function_param_shape(fn).names)
        return
    owners = M.method_owner_names(structs)
    # {BARE method name: [struct, …]}, which is the other direction and is not
    # the same table: `owners` is keyed by the lifted `<Struct>_<method>` a
    # rewritten call spells, and a MemberExpr's `.member` is the bare name.  A
    # name two structs declare is left with both, so a caller can tell "one
    # owner" from "ambiguous" rather than seeing whichever came last.
    by_method = {}
    for st in structs:
        for m in M.struct_methods(st):
            by_method.setdefault(m.name, []).append(st)
    # `param0[fn]` is the name of `fn`'s FIRST parameter, and `params_of[fn]`
    # is the whole parameter list in order.  The full list is here for the
    # same reason the fixpoint below walks every position rather than the
    # first: a parameter is a parameter wherever it sits, and there was never
    # a reason to look only at index 0 except that `self` is at index 0.
    # `param0` is kept because `known = set(param0)` is the "is a function in
    # this image" test `_check_frame_escapes` makes, and it is spelled once.
    #
    # `known` answering FALSE is not the same question as the callee having no
    # definition anywhere, which is what the CALL half used to conclude from
    # it: an IMPORTED free function is in neither table, and `imported` is the
    # third one.  Passed in rather than re-read from the AST here for the same
    # reason `dc_classes` is: two recognitions of the same fact is the pair
    # that agrees until the day it does not.
    param0 = {}
    params_of = {}
    for fn in functions:
        # `model.function_param_shape`, so the variadic table has ONE reader.
        # A `*rest` / `**kw` entry used to land in this list as a name spelled
        # with its star, which made `f(1, 2, r)` against `def f(x, *rest)`
        # bind `r` to argument 1 and leave argument 2 with no parameter at
        # all — and this table is what the hand-off fixpoint reads to decide
        # whether a CALLEE's parameter is a frame holder, so a wrong entry here
        # is a frame address followed into the wrong slot.
        shape = M.function_param_shape(fn)
        names = list(shape.names)
        params_of[_fn_key(fn)] = names
        if names and names[0]:
            param0[fn.name] = names[0]
    # `holders[fn]` is the set of names in `fn` holding a frame address, and
    # `hstruct[fn][name]` is the SET of structs it might be — carried through
    # the fixpoint rather than re-derived afterwards, because a holder that
    # arrived as a callee's parameter has no binding left to re-derive it
    # from. A candidate set that is EMPTY means the name was bound from a
    # constructor this path does not frame, so it holds a plain word and its
    # `.<field>` accesses are not frame accesses at all.
    #
    # KEYED BY FUNCTION IDENTITY (`_fn_key`), not by name, and that is the fix
    # rather than a refinement. Every one of these tables says what ONE
    # function's body does with its own names, so two definitions of one name
    # are two answers — but Mojo overloads are ordinary (`def reversed[...]`
    # appears eight times in std/builtin/reversed.mojo alone, with a different
    # receiver type in each), and keying by name made the FIRST definition's
    # answer stand for all of them. The measured consequence is a member read
    # resolved against the WRONG struct's layout: `reversed`'s `_DictEntryIter`
    # overload reads `value.src`, `_DictEntryIter` declares `src`, and the
    # refusal said `List has no field 'src'` — because the `List` overload was
    # declared first and its `hstruct['reversed']['value']` entry was the one
    # the `_DictEntryIter` body's read was checked against. That is a refusal
    # whose every clause is false about the program.
    #
    # A question ABOUT A NAME is a different table, and `param0` is the one
    # that stays name-keyed: it answers "is this a function in this image",
    # which a name answers for every definition of it. The other by-name
    # question — what a CALL to a name hands back — is `_returns_frame_by_name`
    # over a per-function table, for the reason its docstring gives.
    holders = {_fn_key(fn): set() for fn in functions}
    hstruct = {_fn_key(fn): {} for fn in functions}
    # `{name: [FunctionDef, …]}` — every definition of every name in the image.
    # The by-name readers need it to tell "one function called `f`" from "four
    # functions called `f`", which is the same agree-or-refuse discipline
    # `struct_frame_slot_candidates` applies to a field's slot and for the same
    # reason: a name that means several bodies answers no single question.
    _name_defs = {}
    for fn in functions:
        _name_defs.setdefault(fn.name, []).append(fn)
    # The declared return annotations, read ONCE for the whole unit and handed
    # to the construction decision below.  They are the evidence that tells a
    # construction argument that is an ordinary value from one that is a
    # container returned by a callee, and the two backends read the same table
    # (`formal/model.py`'s `function_return_types`) so the three callers of
    # `struct_construction_plan` cannot answer differently.
    rets = M.function_return_types(functions)
    # `declared_holders[fn.name]` is `{parameter: struct}` for the holders whose
    # status came from the DECLARED TYPE rather than from a call site or a
    # receiver, and it is carried to `_check_holder_agreements` below.  The
    # distinction is load-bearing rather than bookkeeping: a holder the
    # fixpoint found has at least one call site that hands it a frame address
    # BY CONSTRUCTION, so the agreement check's "one kind of value at every
    # call site" test has a frame side to compare the others against.  A holder
    # the DECLARATION found has no such guarantee — the whole construct is a
    # method nothing in the image calls — so that test has to be able to say
    # "no call site agrees", which is a refusal the pre-existing rule does not
    # make.
    declared_holders = {_fn_key(fn): {} for fn in functions}
    # `{_fn_key(fn): struct}` — the functions that RETURN a frame address, and
    # the struct whose layout that frame has.  It is the other half of the
    # holder fixpoint below and is computed inside the same loop, because the
    # two feed each other: a call to one of these functions binds a holder, and
    # which functions are in the table is read out of the holder table.  It is
    # a property of the WHOLE IMAGE for the same reason a parameter's being a
    # holder is (`model.frame_holder_disagreement_refusal`): the caller has to
    # reserve a block BEFORE the call and read the result out of it afterwards,
    # so one call site's answer is not enough.
    #
    # KEYED BY FUNCTION IDENTITY, like every other per-function table here, and
    # the by-name question a call site asks is answered by the JOIN in
    # `_returns_frame_by_name` rather than by this table being keyed by name.
    # That is a termination fix as much as a correctness one — see that
    # function's docstring for the measured hang a name-keyed slot produced
    # when two definitions of one name disagreed.
    returns_frame: dict = {}
    for fn in functions:
        owner = owners.get(fn.name)
        if owner is not None and owner.name in framed:
            for recv in M.struct_receivers(owner):
                holders[_fn_key(fn)].add(recv)
                hstruct[_fn_key(fn)][recv] = [owner]
        # Every parameter of every function, not only a method's: a free
        # function's `def f(r: S)` is the same construct as `def __eq__(self,
        # other: Self)`, the declaration is the same kind of evidence, and
        # restricting it to methods would leave the identical refusal standing
        # one function away with nothing in the reader's source to tell the two
        # apart.
        for pname, pst in M.parameter_declared_structs(
                fn, structs_by_name, owner).items():
            # A name something else already established keeps THAT
            # classification: the fixpoint below runs over every call site and
            # the receiver seeding above is the method's own declaration, so
            # adding a second opinion here would put two structs in a candidate
            # list where one layout is the truth.
            if pname in holders[_fn_key(fn)]:
                continue
            if M.struct_is_framed(pst):
                holders[_fn_key(fn)].add(pname)
                hstruct[_fn_key(fn)][pname] = [pst]
            elif not M.struct_is_one_field(pst):
                continue
            declared_holders[_fn_key(fn)][pname] = pst
        for name, sts in _constructor_bindings(
                fn, framed, [f.name for f in functions]).items():
            holders[_fn_key(fn)].add(name)
            hstruct[_fn_key(fn)].setdefault(name, []).extend(sts)
    for _round in range(_HOLDER_FIXPOINT_ROUNDS):
        grew = False
        changed = True
        # `None` rather than the current state, so the FIRST pass of a round can
        # never be the one the backstop below refuses — it is the pass that
        # establishes what there is to compare against.
        _pass_state = None
        while changed:
            changed = False
            # The by-name view of `returns_frame`, recomputed once per pass and
            # read by the two call-site edges below: both ask "does a CALL to
            # this name hand back a frame", which is the JOIN over that name's
            # definitions and not one definition's slot. Recomputed rather than
            # maintained because it is a pure function of a table that is small
            # (one entry per function) — a second table to keep in step would be
            # a second thing that can disagree.
            by_name_returns_frame, _conflicts = _returns_frame_by_name(
                _name_defs, returns_frame)
            for fn in functions:
                hs = holders[_fn_key(fn)]
                for node in M.iter_nodes(fn.body):
                    target = value = None
                    if isinstance(node, F.VarDecl):
                        target, value = node.name, node.value
                    elif isinstance(node, F.AssignStmt) \
                            and isinstance(node.target, F.IdentExpr):
                        target, value = node.target.name, node.value
                    if target and isinstance(value, F.IdentExpr) \
                            and value.name in hs and target not in hs:
                        # a copy: the same frame under a second name
                        hs.add(target)
                        hstruct[_fn_key(fn)][target] = \
                            list(hstruct[_fn_key(fn)][value.name])
                        changed = grew = True
                    # A call to a function that RETURNS A FRAME binds a frame
                    # address, and this is the edge that makes the returned-frame
                    # convention a whole-image property rather than a per-file one:
                    # `q = make()` puts a frame address in `q`, so `q.x` is a frame
                    # read and `q` has to be in the holder table for the codegen to
                    # emit a load instead of a register move.
                    #
                    # It is inside the fixpoint rather than after it because it
                    # DEPENDS on what the fixpoint decides: which functions return
                    # a frame is itself read out of the holder table, so the two
                    # questions have to be asked together until neither answer
                    # moves.  It is keyed on the BINDING node — a `VarDecl` or an
                    # `AssignStmt` — and not on the `CallExpr`, because those are
                    # two different nodes in this walk and the binding is the one
                    # that says the address outlives the call.
                    #
                    # `M.call_callee_name` and NOT `value.func.name`, for the same
                    # reason the edge below uses it: a comptime specialization
                    # `make[T]()` names the same function `make` does, and reading
                    # the name off the node would make this edge blind to every
                    # generic frame-returning constructor.
                    if target and isinstance(value, F.CallExpr):
                        frame_fn = M.call_callee_name(value.func)
                        st = (by_name_returns_frame.get(frame_fn)
                              if frame_fn else None)
                        if st is not None and target not in hs:
                            hs.add(target)
                            hstruct[_fn_key(fn)].setdefault(target, []).append(st)
                            changed = grew = True
                    if not isinstance(node, F.CallExpr):
                        continue
                    # `model.call_callee_name`, and NOT `node.func.name`: a
                    # comptime specialization `f[T](r)` names the same function `f`
                    # does, contributes no call-time argument of its own, and so
                    # lands the frame on `f`'s parameter at exactly the position
                    # the bare spelling would. Reading the name off the node instead
                    # made this edge blind to every generic call, which is what left
                    # `_check_frame_escapes` with nothing to follow — and a blind
                    # edge here is the SILENT direction: had the escape check been
                    # lifted without this, `f`'s parameter would have read as an
                    # ordinary word and `r.a` a load eight bytes from wherever it
                    # pointed.  One recogniser, four readers
                    # (`_check_frame_escapes` and `_check_holder_agreements` as
                    # well, and the returned-frame edge above), because the four
                    # have to agree about which function a call is.
                    #
                    # It subsumes the `or not isinstance(node.func, F.IdentExpr)`
                    # guard this edge used to carry: `call_callee_name` answers
                    # None for a callee that is not a plain or generic name, which
                    # is the same set, and ONE recogniser for "which function is
                    # this call" is the property the comment above is about.
                    target_fn = M.call_callee_name(node.func)
                    if target_fn is None:
                        continue
                    # EVERY argument position, not just the first, and a keyword
                    # resolved BY NAME — the position a keyword lands in is the
                    # parameter list's business, and reading it off the
                    # concatenated `args + kwargs` list would follow a frame
                    # address into the wrong parameter.
                    #
                    # The lifetime reasoning this needs, and it is the whole
                    # reason it is safe: a frame belongs to the function that
                    # created it, and an address only ever travels DOWN an active
                    # call chain, so the creator of a holder that arrived as an
                    # argument is an ancestor of the callee and its frame is live
                    # for every instant of the callee's activation. The callee may
                    # therefore read and write through it — which is the same
                    # licence a method receiver has, and the same one the
                    # cross-module hand-off relies on. What it may NOT do is let
                    # the word leave, because then it outlives the call and the
                    # creator may be gone: `return y`, a container, a field, a
                    # subscript and a module-level name are all refused by name in
                    # `_check_frame_escapes`.
                    #
                    # `r[1] == 0` is kept: a field read is a VALUE and not an
                    # address, so only a bare name hands the frame over.
                    #
                    # `plist` is the callee's OWN parameter list, and the edge is
                    # only taken for a position that list has: a callee this image
                    # does not have has no parameter to make a holder, and that is
                    # the opaque case `_check_frame_escapes` says so about. It is
                    # `function_param_shape(fn).names`, so it holds the RUNTIME
                    # parameters in order and a comptime parameter is not in it —
                    # which is right, because the brackets are passed ahead of these
                    # (`model.incoming_args`) and so occupy no call-time position.
                    # The callee is reached BY NAME — all a call site carries —
                    # so the name has to be resolved to the definition it
                    # denotes before its parameter list means anything. Both
                    # halves come from `_by_name_holder`, which returns
                    # `(None, None)` for a name with SEVERAL definitions: that
                    # is the same "this edge cannot be taken" the `if not plist`
                    # produces for a callee this image does not have, except
                    # this one is a real answer about a real image rather than a
                    # missing definition. See its docstring for why picking one
                    # of several is the defect. `plist` is read HERE, from the
                    # resolved definition, rather than by name from `params_of`
                    # — a by-name read of a table keyed by identity is a miss on
                    # every call, which is how this edge went silently dead
                    # when the tables were re-keyed.
                    callee_holders, callee_hstruct = _by_name_holder(
                        _name_defs, holders, hstruct, target_fn)
                    if callee_holders is None:
                        continue
                    _defs = _name_defs.get(target_fn) or ()
                    plist = params_of.get(_fn_key(_defs[0]))
                    if not plist:
                        continue
                    for pos, pname, _kw in _frame_argument_slots(node, plist):
                        if pos >= len(plist):
                            continue
                        r = _root_ident(pname)
                        if not (r and r[0] in hs and r[1] == 0):
                            continue
                        callee = plist[pos]
                        if not callee or callee in callee_holders:
                            continue
                        callee_holders.add(callee)
                        callee_hstruct[callee] = \
                            list(hstruct[_fn_key(fn)][r[0]])
                        changed = grew = True
            # The OTHER half of the same fixpoint: which functions RETURN a frame.
            # It has to be here and not after the loop because the edge above reads
            # it — `q = make()` is a holder only if `make` is known to return a
            # frame — and because it reads the holder table the same loop is still
            # growing.  The two questions therefore have to be asked together until
            # neither answer moves, which terminates because frame-ness only ever
            # GROWS: a return value is a frame either because a name holds one (the
            # holder table, monotone) or because it is a call to a function already
            # known to return one (also monotone).
            for fn in functions:
                status, st, holder = _frame_return_status(
                    fn, holders[_fn_key(fn)], hstruct[_fn_key(fn)],
                    by_name_returns_frame)
                fn._frame_return_status = status
                key = _fn_key(fn)
                if status == _RETURN_FRAME and returns_frame.get(key) is not st:
                    changed = grew = True
                if status == _RETURN_FRAME:
                    returns_frame[key] = st
                    # The `(holder, struct)` pair, published for the checks that
                    # ask about the block rather than about the callee:
                    # `check_returned_frame_blob_writes` needs the NAME to look
                    # the container writes up, and a struct alone cannot say
                    # which of the returned frame's fields it is.
                    fn._returned_frame = (holder, st)
                elif returns_frame.pop(key, None) is not None:
                    changed = grew = True
            # A pass that claims progress and leaves every table it reads exactly
            # as it found it is not going to settle: the next pass reads the same
            # state, makes the same decisions, and reaches here again. So it is
            # refused instead of spun on. This is the inner loop's backstop, and
            # it is here because the OUTER loop's bound (`_HOLDER_FIXPOINT_ROUNDS`)
            # cannot fire while this one is still running — which is how a
            # non-terminating fixpoint reached a hang rather than the documented
            # refusal. The state compared is everything the pass decides from:
            # the holder sets, the candidate lists they name, and the returned-
            # frame table.
            if changed and _holder_state(holders, hstruct,
                                         returns_frame) == _pass_state:
                raise CodegenError(
                    f"the holder analysis reported progress in a pass that "
                    f"changed none of its tables: no holder was added, no "
                    f"frame-returning function entered or left the table, and "
                    f"the next pass would therefore decide exactly as this one "
                    f"did. That means the fixpoint has no fixed point on this "
                    f"program, which is a compiler bug, not a program error")
            _pass_state = _holder_state(holders, hstruct, returns_frame)
        moved = (_rewrite_len_on_frame_receivers(functions, holders,
                                          hstruct)
                 + _rewrite_eq_on_frame_receivers(functions, holders,
                                                 hstruct))
        if not (grew or moved):
            break
    else:
        raise CodegenError(
            f"the holder analysis did not settle in {_HOLDER_FIXPOINT_ROUNDS} "
            f"rounds: an operator rewrite is still introducing frames at each "
            f"one, which means the rewrite is not monotone and the fixpoint it "
            f"feeds has no fixed point. That is a compiler bug, not a program "
            f"error")

    # The whole image's BY-NAME table, published on every function, and the
    # reason it is published rather than passed: the CALLER of a frame-returning
    # function is a different function from the one that returns it, and the
    # emitters ask the question per call site with no unit in hand — the same
    # reason `_frame_candidates` is published rather than threaded. It is the
    # JOIN (`_returns_frame_by_name`), so a name whose definitions disagree is
    # absent from it and no call site claims a frame from it.
    #
    # `_returns_frame_struct` is published alongside it because the emitter's
    # other question is not a by-name one: "does the function I am EMITTING
    # return a frame" has an answer for each definition separately, and reading
    # it out of the by-name table gave both definitions of an overloaded name
    # one answer — which for a pair whose definitions disagree is a wrong
    # answer for one of them, since the extra trailing block argument is either
    # passed or it is not.
    by_name_returns_frame, conflicts = _returns_frame_by_name(_name_defs,
                                                             returns_frame)
    for fn in functions:
        fn._image_returns_frame = dict(by_name_returns_frame)
        fn._returns_frame_struct = returns_frame.get(_fn_key(fn))
    _check_returned_frame_budget(functions, returns_frame, params_of)
    # An overloaded name whose definitions disagree about returning a frame is
    # PARKED on each of them, for the reason every other returned-frame refusal
    # in this file is: this pass runs inside `_prepare_functions`, which is
    # before the imports resolve, so a refusal raised here would be reported in
    # place of the import diagnosis — and a file that imports a host module is
    # out of this backend's reach whatever its own convention says. Parked on
    # every definition rather than once so the message cannot be lost by a
    # definition that no later check walks.
    for name, rows in conflicts.items():
        message = M.frame_return_overloads_disagree_refusal(name, rows)
        for fn in _name_defs.get(name) or ():
            _park_frame_return(fn, message)

    # A class-level constant read through a HOLDER — `shape.is_flat`, where
    # `shape` arrived as a parameter and this fixpoint is what settled that it is
    # a `Coord` — is the third spelling of the same read, and it can only be
    # recognized HERE: until the fixpoint has run, "which struct does this name
    # hold" has no answer at all, which is the first bullet of the comment below
    # for a different rewrite and is the reason this one is not in
    # `_prepare_functions` with the other two. After the fixpoint and before the
    # per-function loop, so the loop never sees the read — which is what it would
    # otherwise refuse, by `model.member_read_without_a_field`, with a message
    # that is false about a class constant ("Coord has no field 'is_flat'") and
    # adds that in Python it is an AttributeError, which for a `comptime` member
    # it is not.
    #
    # The `None`-comparison refusal is asked first and separately, for the reason
    # `refuse_none_comparisons` gives about its own ordering: the fold destroys
    # the fact the check is about, so a spelling the fold reaches and the check
    # does not is a spelling that silently answers `None == 0`. It is a second
    # call rather than a moved one because the first call, in
    # `_prepare_functions`, is the only one that can see a method's own receiver
    # read before `_rewrite_self_fields` rewrites it.
    def _holder_bases(fn):
        return _holder_class_constant_bases(hstruct.get(_fn_key(fn)) or {},
                                            structs_by_name)

    refuse_none_comparisons(functions, structs_by_name, _holder_bases,
                            method_owners)
    for fn in functions:
        if not hstruct.get(_fn_key(fn)):
            continue
        _rewrite_class_constants(fn, structs_by_name,
                                 method_owners.get(fn.name),
                                 _holder_bases(fn))

    # AFTER the fixpoint and BEFORE the per-function loop below, and both of
    # those positions are load-bearing rather than tidy:
    #
    #   * after, because the question is "does this name hold a frame, and of
    #     WHICH struct" and the fixpoint is what settles both.  Before it, a
    #     parameter that only some call site reaches with a frame address would
    #     not be a holder yet and the rewrite would fire on nothing.
    #   * before, because `_check_frame_escapes` refuses `len(<frame address>)`
    #     as a value-only call, and the whole point is that it must no longer
    #     see one.  The rewrite changes the CALLEE, so the check below is
    #     looking at a call this pass has already turned into a method call with
    #     the frame as its first argument — which is the shape the by-reference
    #     design exists for, and needs nothing new to be right about.
    #
    # …and the fixpoint and the two rewrites above it are ONE fixpoint rather
    # than three passes, because the rewrites feed it.  `len` introduces one
    # edge, `Struct___len__` with a frame in argument 0, whose parameter is
    # already a holder, so for `len` a second saturation was never needed and
    # none happened.  `a == b` introduces an edge at argument 0 AND at argument
    # 1: `S___eq__(a, b)` hands `b` to the method's SECOND parameter, and that
    # parameter is a holder only because the fixpoint has seen the call.  The
    # `__eq__` that reads the field it is given — `self.x == other.x`, which is
    # what an equality method is for — was refused by name ("`other.x` is a
    # field access through `other`, and this path has no way to say what
    # `other` holds") until the round after the one that made the call.  Both
    # rewrites are idempotent and only ever add, so the pair converges, and
    # `_HOLDER_FIXPOINT_ROUNDS` is the bound that says so out loud rather than
    # leaving a non-monotone rewrite to hang.  If that bound is ever reached,
    # `_check_holder_agreements` at the end of this function is what would
    # otherwise have said the parameter is not a holder, by name, at the call
    # site.
    for fn in functions:
        hs = holders[_fn_key(fn)]
        if not hs and not _stores_a_frame_returning_call(fn,
                                                        by_name_returns_frame):
            # No frame is HELD here, so there is nothing for the escape check to
            # say — except the one shape that holds nothing: `xs[1] = make(5)`
            # puts the address of the block this function reserved into a list,
            # and the list's element outlives the activation.  The emitter's
            # subscript store does not lower a frame address, so the store is
            # dropped and the program exits 0 where the source says 5.  That is
            # why the skip is conditional on a second scan rather than deleted:
            # running the check for every function would change the messages for
            # the hundreds that legitimately hold nothing.
            continue
        by_name = hstruct[_fn_key(fn)]
        call_recv = _call_receivers(fn)
        # `{"h.a": struct}` — the fields of a HOLDER in this function whose
        # agreed declared type is a framed struct of this module, so the slot
        # holds a nested frame this compiler placed.  Distinct from
        # `_frame_nested_slots`, which is the read side and a two-load access:
        # this is the CALL side and a one-word receiver.
        nested_fields = {}
        # `_frame_slots` is `{"<holder>.<field>": slot}` — ONE load, which is
        # what the codegen's `_load_var`/`_store_var` interception expects.
        # `_frame_nested_slots` is `{"<holder>.<field>.<field>": slot}` — a
        # load of a load, and it is a SEPARATE table rather than an entry with a
        # null in it because a null is indistinguishable from "this field has
        # no slot", which is the disagreement this whole pass exists to keep
        # apart from "this field is nested".
        slots, nested_slots = {}, {}
        # `@dataclass` makes `==` a FIELD compare, and this is the only place
        # a name's struct is known (the fixpoint above settled the locals, the
        # interprocedural edge settled the parameters), so the desugaring runs
        # HERE and takes `by_name` as given. Measured: a bare struct's `==` is a
        # compare of two words, and for a multi-field struct those words are
        # frame ADDRESSES — `Two(1, 2) == Two(1, 2)` is False on this path
        # where CPython's `@dataclass` says True. The rewrite is into a chain
        # this path already lowers correctly (`a.x == b.x and a.y == b.y`
        # through a function boundary, measured to build and print what CPython
        # prints), so it is a desugaring and not a new lowering. See
        # formal/dataclass_transform.py.
        if dc_classes:
            DC.rewrite_equality(fn, hs, by_name, dc_classes)
        for node in M.iter_nodes(fn.body):
            if not isinstance(node, F.MemberExpr):
                continue
            r = _root_ident(node)
            if r is None or r[0] not in hs:
                continue
            base, depth = r
            cands = by_name.get(base) or []
            chain = _member_chain(node)
            is_call_recv = id(node) in call_recv
            if is_call_recv:
                # A METHOD CALL whose receiver is (or starts at) a frame
                # address. The callee is handed ONE WORD — a load from
                # `[base, 8k]` for a depth-2 chain, the address itself for a
                # depth-1 one — and what that word has to be is a question
                # about the METHOD, not about the frame layout. So the two
                # cases where the method's own declaration settles it are
                # decided here, and everything else is handed on to
                # `model.value_method_refusal`, which is the diagnostic that
                # describes it. Deciding them here is what keeps a frame
                # diagnostic from being printed for a call that never had a
                # layout question.
                # `owners` is keyed by the LIFTED name `<Struct>_<method>`, and
                # this is the BARE name the source spells, so the lookup is
                # `by_method`.  A name two structs declare is genuinely
                # ambiguous, and `_rewrite_method_calls` already refused to
                # rewrite it, so there is nothing to say about it here that it
                # has not said — hence the `== 1` and not a pick.
                declared = by_method.get(node.member) or ()
                if len(declared) == 1:
                    ost = declared[0]
                    if depth > 1:
                        # A field's DECLARED TYPE is the one thing on this path
                        # that says what the word in the slot is, and it has
                        # three answers, not two.  `model.frame_field_type_can
                        # didates` is the agree-or-refuse check over them and
                        # its own diagnostic is `model.field_type_disagree
                        # ment`; what happens next is decided by which answer
                        # came back, and the third one is the reason this
                        # function grew rather than shrank.
                        # `chain` is `self.inner.sum`, so the field whose slot
                        # is being read is the one BEFORE the last, not the
                        # method's own name.  Getting this wrong is not a
                        # cosmetic problem: the refusal would then report the
                        # declared type of a name the struct never declares,
                        # which is the same "the tool looked at something else"
                        # failure C5 fixed in the message text.
                        outer = chain.split(".")[-2] if depth > 1 else None
                        nested = _typed_nested_frame(
                            base, outer, cands, structs_by_name, ost)
                        if nested is _NOT_TYPED:
                            # No single type, so the slot's contents are unknown
                            # — which is what the old message said, and now it
                            # also says WHICH candidate disagreed and where each
                            # one got its answer from.
                            raise CodegenError(
                                f"{chain}() hands the word in the slot "
                                f"{base}.{outer} to "
                                f"{ost.name}.{node.member}(), whose receiver is "
                                f"the ADDRESS of a frame of 8-byte slots — so "
                                f"the slot would have to hold a frame address. "
                                f"Only a type for {outer!r} could say so — a "
                                f"declaration in the class body, or a "
                                f"construction its __init__ assigns — and there "
                                f"is no single one: {M.field_type_disagreement(cands, outer, _type_rows(cands, outer, structs_by_name))}"
                                f". Until every binding of the name agrees on "
                                f"one type there is no frame to place here"
                            )
                        if nested is _REASSIGNED:
                            ann = _field_annotation(cands, outer,
                                                    structs_by_name)
                            raise CodegenError(
                                f"{base}.{outer} is a "
                                f"{M.annotation_base_name(_field_annotation(cands, outer, structs_by_name))}"
                                f", a struct of this module whose receiver is a "
                                f"frame of 8-byte slots, so the slot does hold a "
                                f"frame address — but a method of "
                                f"{', '.join(sorted({st.name for st in cands}))} "
                                f"ASSIGNS that field, so what is in the slot is a "
                                f"frame belonging to whichever function ran the "
                                f"assignment rather than the frame this "
                                f"constructor placed. Those two lifetimes are "
                                f"independent, which is the whole reason the "
                                f"placed frame is preferred, so it is not "
                                f"available here. Assign the field to a name and "
                                f"call the method on the name, which is the same "
                                f"program with a lifetime this analysis can see"
                            )
                        if nested is None:
                            # Agreed, and the agreed type is provably NOT a
                            # frame of this unit.  The word in the slot is a
                            # plain value, so the frame layout is not what is
                            # in question and a frame diagnostic would be a
                            # diagnostic about the wrong thing.  Fall through to
                            # the value path, which either lowers the method or
                            # refuses it with `model.value_method_refusal`.
                            continue
                        # Agreed, and it names a framed struct: the slot holds a
                        # NESTED FRAME, placed in the outer object's own block
                        # so that its lifetime is the outer object's.  The
                        # placement itself is `model.struct_nested_frame_fields`
                        # via `struct_constructor_sites`; nothing more is needed
                        # here.  The write half of the rule needs nothing
                        # either: the placement list excludes every field an
                        # executed method writes, so a placed nested frame is
                        # write-once by construction and a field that IS
                        # written got `_REASSIGNED` above instead.
                        nested_fields[f"{base}.{outer}"] = nested
                        continue
                    if depth == 1 and ost.name not in {
                            s.name for s in (by_name.get(base) or [])}:
                        raise CodegenError(
                            f"{chain}() is a call to {ost.name}.{node.member}"
                            f"(), but the receiver is a "
                            f"{', '.join(s.name for s in by_name.get(base) or [])}"
                            f" frame: a method is rewritten to take its OWN "
                            f"struct's frame, and passing a different struct's "
                            f"address has the callee read one object's fields "
                            f"out of another's storage. Dispatch here is by "
                            f"method name alone — `recv.m(x)` carries no type — "
                            f"so the two cannot be told apart except by "
                            f"refusing")
                continue
            if depth > 1:
                # A field of a field in a VALUE position.  Same three answers
                # as the call case above, and the one that matters is the
                # nested frame: `self.a.b` where `a` is declared to be a framed
                # struct of this module is a load from the slot followed by a
                # load from the nested frame, and both addresses are placed.
                # `chain` is the whole chain, so the OUTER field is the one
                # before the last and the inner is `node.member` — the chain
                # is spelled rather than reconstructed because
                # `self.a.b.c`'s outer field is `b`, not `a`.
                parts = chain.split(".")
                outer_field = parts[-2] if len(parts) >= 2 else node.member
                cands = by_name.get(base) or []
                nested = _typed_nested_frame(
                    base, outer_field, cands, structs_by_name, None)
                if nested is _NOT_TYPED:
                    vrows = _type_rows(cands, outer_field, structs_by_name)
                    raise CodegenError(
                        f"{chain} reads a field of a field through the receiver "
                        f"{base}: a frame slot holds one 64-bit word, and the word "
                        f"in the slot {base}.{outer_field} is a value, not a "
                        f"struct, so there is no second layout to read through. "
                        f"Two things would make it representable and neither is a "
                        f"change to this function: a TYPE for "
                        f"{outer_field!r} that EVERY binding of the name agrees "
                        f"on and that names a struct declared here — a declaration "
                        f"in the class body, or a construction its __init__ "
                        f"assigns — which would then be a nested frame, placed in "
                        f"the outer object's own block, or a builtin method on "
                        f"the value, which is {node.member!r}() as a call, not "
                        f"a field read. Nothing types {outer_field!r} here: "
                        f"{M.field_type_disagreement(cands, outer_field, _type_rows(cands, outer_field, structs_by_name))}"
                    )
                if nested is _REASSIGNED:
                    vann = _field_annotation(cands, outer_field, structs_by_name)
                    raise CodegenError(
                        f"{chain} reads through {base}.{outer_field}, which is "
                        f"a "
                        f"{M.annotation_base_name(_field_annotation(cands, outer_field, structs_by_name))}"
                        f" — a struct of this module whose receiver is a frame — "
                        f"but a method of "
                        f"{', '.join(sorted({st.name for st in cands}))} ASSIGNS "
                        f"it, so the word in the slot is a frame belonging to "
                        f"whichever function ran the assignment. Assign the "
                        f"field to a name and read through the name, which is the "
                        f"same program with a lifetime this analysis can see"
                    )
                if nested is None:
                    # Agreed, and not a frame of this unit — so the outer field
                    # is a plain value and the inner name is a member of
                    # whatever that value is.  Not this pass's business; the
                    # ordinary value lowering owns it.
                    continue
                # A nested frame read in a value position: two loads, and the
                # OUTER one is already in `_frame_slots` (the depth-1 MemberExpr
                # of the same chain was visited on an earlier turn of this walk,
                # and if it was not then the name is not a holder's field and
                # there is nothing to place).  The INNER one goes in its own
                # table, because a `_frame_slots` entry is one load and this is
                # two, and a two-load access with a one-load table entry is a
                # wrong answer rather than a failure.
                outer_slot, (odis, orows) = M.struct_frame_slot_candidates(
                    cands, outer_field)
                if odis or outer_slot is None:
                    trows = _type_rows(cands, outer_field, structs_by_name)
                    raise CodegenError(
                        f"{base}.{outer_field} cannot be placed, so the nested "
                        f"read {chain} has no first load: "
                        + ("the candidate layouts disagree — "
                           + M.field_type_disagreement(
                               cands, outer_field,
                               _type_rows(cands, outer_field, structs_by_name))
                           if odis else
                           f"no candidate declares it as a field of a frame")
                    )
                inner = M.struct_frame_slot(nested, node.member)
                if inner is None:
                    # The METHOD check `member_read_without_a_field` makes for a
                    # depth-1 read, applied here too, and it is the same defect
                    # this site had: `self.strong.fetch_add` is a read of a
                    # member `Atomic` does not have as a FIELD — it is one of
                    # its METHODS, and the sentence below said so in a way that
                    # sent the reader to the layout ("and that struct's 3
                    # field(s): T, scope, _value has no such field") when the
                    # answer is that the name is not a field at all.
                    #
                    # Measured on `std/memory/arc_pointer.mojo`, whose
                    # `self.strong.fetch_add[ordering=…](1)` is that call.
                    # One recogniser (`model.structs_declaring_method`) so the
                    # two sites cannot drift, which is the property the depth-1
                    # message was written to have.
                    owners = M.structs_declaring_method([nested], node.member)
                    if owners:
                        raise CodegenError(
                            f"{chain} names {node.member!r}, which is a METHOD "
                            f"of the nested {owners[0].name} frame rather than "
                            f"one of its fields: a value-position method "
                            f"reference is a bound method, and a method is not "
                            f"a word — there is no slot to read it out of and "
                            f"nothing to store it in, so this path has no "
                            f"representation for it. Call it "
                            f"(`{chain}(...)`), which is a receiver and a call "
                            f"and lowers, or write the operation out where it "
                            f"was used"
                        )
                    raise CodegenError(
                        f"{chain} reads {node.member!r} out of a nested "
                        f"{nested.name} frame, and that struct's "
                        f"{M.struct_field_summary(nested)} has no such field"
                    )
                slots[f"{base}.{outer_field}"] = outer_slot
                nested_slots[f"{base}.{outer_field}.{node.member}"] = inner
                continue
            if not cands:
                # bound from a constructor that is not framed: a plain word.
                # Not a frame access, so not this pass's business.
                continue
            slot, (disagree, _rows) = M.struct_frame_slot_candidates(
                cands, node.member)
            if disagree:
                # The message is the model's because it has to pick between
                # three SHAPES — a method, a field the struct does not have, and
                # a genuine two-candidate disagreement — and only the model can
                # ask which, because only it has the struct tables. It used to
                # be spelled here, and it printed "more than one shape" for
                # every one of the three; see
                # `model.member_read_without_a_field`.
                raise CodegenError(
                    M.member_read_without_a_field(chain, base, node.member,
                                                  cands))
            if slot is None:
                raise CodegenError(
                    f"{base}.{node.member} is a member access on a "
                    f"{cands[0].name} receiver, and {node.member!r} is not one "
                    f"of its {M.struct_field_summary(cands[0])}: this path has "
                    f"no way to know which word that is, and reading the wrong "
                    f"one is a wrong answer rather than a failure")
            slots[f"{base}.{node.member}"] = slot
        # Which of this function's holders were built HERE, as opposed to
        # arriving as a method receiver or as a callee's parameter.  It is the
        # difference between "returned from the function that created it" and
        # "returned from a function that received it", and the second is the
        # larger half of the family: the holder fixpoint makes a callee's
        # parameter a holder, so `def fwd(r): return r` in a program whose
        # object `main` built was reported as a return from the creator.  A
        # constructor binding is the one way a frame is created in this
        # function, and it is the same enumeration the fixpoint started from,
        # so the two cannot disagree about which names those are.
        #
        # `holders`/`hstruct`/`params_of` are the WHOLE IMAGE's tables, not
        # this function's, and that is the point of passing them: whether an
        # argument is refused depends on what the CALLEE was compiled to
        # believe about the parameter it lands in, which is not a fact this
        # function can see.  `params_of` is complete before the fixpoint runs,
        # so it is complete here.
        _check_frame_escapes(fn, hs, by_name, param0, owners, structs_by_name,
                             set(_constructor_bindings(
                                 fn, framed,
                                 [f.name for f in functions])), rets,
                             holders, hstruct, params_of,
                             _callee_defs(functions), imported,
                             star_imports, _name_defs,
                             by_name_returns_frame)
        _check_method_receiver_types(fn, hs, by_name, owners, structs_by_name)
        fn._frame_holders = hs
        fn._frame_nested_slots = nested_slots
        fn._frame_slots = slots
        # THE PER-PARAMETER CONTRACT, and it is the answer to a question an
        # IMPORTING module cannot answer for itself: "did your compilation
        # make parameter 2 a frame holder, and of which struct?"  That is a
        # fact about a compilation this process did not perform, and the
        # refusal an importing module used to raise said so — which was true
        # and unhelpful, because the information EXISTS, on the other side of
        # the module boundary, in this table.
        #
        # Published here rather than derived at the manifest writer because
        # here is where the fixpoint has just settled it, and a second
        # derivation would be a second recognition of "is this parameter a
        # frame holder" — the pair of recognitions that agrees until the day
        # it does not, which is the failure mode `_frame_candidates` exists to
        # prevent and which this must not reintroduce one function along.
        #
        # POSITIONALLY, keyed on the parameter list rather than by name, because
        # that is what a CALL SITE has: the importing module knows the argument
        # index and has no idea what the callee called its parameters. The
        # value is the SET of structs the parameter might be a holder of, for
        # the same reason `hstruct` is a set rather than one struct — a set of
        # one is the ordinary case and a set of two is a disagreement the
        # consumer is entitled to see.
        fn._frame_param_contract = _parameter_frame_contract(
            fn, params_of.get(fn.name) or (), holders.get(fn.name) or (),
            (hstruct.get(fn.name) or {}), declared_holders.get(fn.name) or {})
        # `by_name` itself, published, and the reason is a CONSTRUCTION rather
        # than a field read: a copy construction `S(x)` needs to know what `x`
        # IS, and the holder analysis is the only thing in the compiler that
        # can say a word is a frame address.  Without it the emitters would
        # have to re-derive the recognition, and two recognitions of "is this
        # name a frame" is exactly the kind of pair that agrees until the day
        # it does not.  `model.struct_construction_plan` is the single decision
        # and both backends call it with this table.
        fn._frame_candidates = dict(by_name)
        # LAST for this function, and after the walk above rather than inside
        # it: the rewrite MUTATES the tree the walk is iterating, and a walk
        # that mutates what it is walking is how a pass ends up seeing a node
        # twice or not at all.  `_rewrite_method_calls` cannot do this job
        # because it runs before any of this — the holder set, the candidate
        # list and the declared-type agreement are all settled here — and
        # guessing a nested receiver there is exactly the name-dispatch bug
        # `_check_method_receiver_types` exists for.
        _rewrite_nested_method_calls(fn, nested_fields)
        # …and the `len` spelling of the same receiver, which is the second
        # route to one `__len__` decision rather than a second decision about
        # it.  It asks `_typed_nested_frame` rather than reading
        # `nested_fields`, because that table is populated only for a
        # depth-2 CALL receiver and `len(h.a)` is a depth-1 value read — the
        # struct and the lifetime have to be settled again, by the same
        # function, or the two spellings would be answering from two tables.
        _rewrite_len_on_nested_frames(fn, by_name, structs_by_name)
    # AFTER the loop, over every function including the ones that hold no frame.
    # A parameter's being a frame holder is a fact about the whole image, and
    # the call site that disagrees with it can be in a function the loop above
    # skipped — see `_check_holder_agreements` for the program that measures it.
    _check_holder_agreements(functions, holders, hstruct, params_of,
                             declared_holders, structs_by_name,
                             _name_defs, returns_frame)
    _collect_holder_rebinds(functions, holders, hstruct, structs_by_name,
                            by_name_returns_frame)
    _park_construction_mismatches(functions, framed)


def _parameter_frame_contract(fn, params, holders, hstruct, declared) -> list:
    """`[holder, holder, …]` — one entry per PARAMETER, in call-site order.

    The question an importing module cannot answer about a callee in another
    module: is parameter *i* a frame address, and of which struct? The answer
    has to be published by the module that compiled the callee, because it is a
    fact about THAT compilation — the holder fixpoint above saw that module's
    call sites and this module's callee will not.

    **Positional, and it must stay positional.** A call site has an argument
    index; it has no idea what the callee named its parameters, and a
    name-keyed table could not be consulted by one that renamed them (or, for a
    method, that lifted `S_m` and passes `self` at position 0 under whatever
    the receiver rewrite spelled it). The parameter NAME rides along in each
    entry only so a refusal can quote it, which is what makes the diagnostic
    readable — nothing consults it.

    Three kinds of entry, and the distinction is the whole content:

      * `[names]` — the parameter is a frame holder of one of those structs.
        A consumer that is handed a frame of one of them may follow the
        address; a consumer handed anything else has a real disagreement.
      * `["one-word"]` — the parameter is declared as a ONE-FIELD struct of
        this module, so its "receiver IS its field" and a frame address is
        the wrong category entirely. It is `declared` and not `holders` that
        says so, and the two are not exclusive: a framed DECLARATION seeds
        both, because `declared` records the evidence rather than a different
        classification, which is why the holder test comes first.
      * `None` — an ordinary word. Nothing in this module ever hands it an
        address, so it was compiled to read the word as a value.

    A struct whose holder candidacy is EMPTY (`hstruct` has the name mapped to
    `[]`) is not a holder at all — `model.struct_frame_slot_candidates` uses
    that to mean "bound from a constructor this path does not frame" — and is
    reported as `None` rather than as a holder of nothing, because "a holder of
    no known struct" and "an ordinary word" are the same instruction to a
    consumer and a third spelling of it would be a way for the two to drift.
    """
    out = []
    for pname in params:
        cands = hstruct.get(pname) or ()
        names = [st.name for st in cands]
        if names and pname in holders:
            out.append(names)
        elif pname in declared:
            # Only reachable for a ONE-FIELD struct.  A framed declaration
            # seeds BOTH `holders` and `declared` (the fixpoint does not make
            # the two exclusive — `declared` records the EVIDENCE, not a
            # different classification), so the framed case was already answered
            # by the branch above and arriving here means the struct does not
            # need a frame: its receiver IS its field.
            out.append(["one-word"])
        else:
            out.append(None)
    return out


def _park_construction_mismatches(functions, framed) -> None:
    """PARK a `C(...)` the EMITTERS lower as a type conversion but which names a
    local FRAMED struct — provided the name is then used as a receiver.

    This is the other half of `_constructor_bindings`' guard.  The guard stops
    the analysis claiming a frame for a call the emitters do not lower as one;
    this says WHY, by name, because the alternative is a diagnostic that is
    false.  The emitter's own `model.field_access_refusal` answers `a.f` with
    "'a' is bound here as a parameter", and for a local bound from a conversion
    that is not what happened: `a` holds the address of an interned `char *`.
    A refusal whose stated reason is entirely false is the worst outcome on this
    path (`bugs/FORMAL_frame_receiver_handoff.md` §4), and the analysis is the
    only place that knows the difference, so it is the analysis that has to say
    it.

    **Only when the name is used as a RECEIVER.**  `var s = String()` on its own
    is a `char *` and is correct on this path — that is the whole of
    `bugs/FORMAL_string_value_model.md`'s decision, and a program that builds one
    of those and never writes a field through it must keep building.  So the
    finding needs a `MemberExpr` rooted at the name, which is the use that has no
    reading.

    The reproducer, which is the stdlib's own three-field `String` verbatim:

    ```
    struct String:
        var _ptr_or_data: Pointer[UInt8]
        var _len_or_data: Int
        var _capacity_or_data: Int
        def size(self) -> Int: return self._len_or_data
    def main(n: Int) -> Int:
        var a = String()
        a._len_or_data = 5
        return a.size()
    ```

    Before the guard, on both architectures: SIGBUS, exit 138, in read-only
    `__TEXT` — the emitter produced the address of the interned empty string and
    the analysis turned the field store into a store through it.
    """
    fns = [f.name for f in functions]
    for fn in functions:
        used_as_receiver = set()
        for node in M.iter_nodes(getattr(fn, "body", None)):
            if not isinstance(node, F.MemberExpr):
                continue
            r = _root_ident(node)
            if r is not None and r[1] >= 1:
                used_as_receiver.add(r[0])
        if not used_as_receiver:
            continue
        for node in M.iter_nodes(getattr(fn, "body", None)):
            target = value = None
            if isinstance(node, F.VarDecl):
                target, value = node.name, node.value
            elif isinstance(node, F.AssignStmt) and isinstance(node.target,
                                                              F.IdentExpr):
                target, value = node.target.name, node.value
            if not target or not isinstance(value, F.CallExpr) \
                    or not isinstance(value.func, F.IdentExpr):
                continue
            callee = value.func.name
            if callee not in framed or target not in used_as_receiver:
                continue
            if M.call_lowers_as_framed_construction(
                    callee, framed, len(value.args or [])
                    + len(value.kwargs or []), fns):
                continue
            fn._construction_mismatch = (target, callee,
                                         M.struct_field_summary(framed[callee]))
            return


def check_construction_mismatches(functions) -> None:
    """Raise the construction/analysis disagreement
    `_park_construction_mismatches` parked.

    The fifth late frame check, at the entry points for the reason the other
    four are: `_prepare_functions` runs before `_resolve_imports`, so a refusal
    from inside it preempts the import diagnosis.  One finding is enough — a
    program with two is one defect with two lines."""
    for fn in functions:
        finding = getattr(fn, "_construction_mismatch", None)
        if finding is None:
            continue
        target, callee, summary = finding
        raise CodegenError(M.construction_mismatch_refusal(
            target, callee, summary, fn.name))


def _value_may_be_a_frame(value, structs_by_name, holders, alias=None,
                         returns_frame: dict = None) -> bool:
    """Whether `value` is one of the three things that can put a FRAME in a name.

    The list is the recognition's own, and it is short because the recognition
    is: `formal/build.py`'s `_frame_receivers` makes a name a holder from a
    method receiver of a framed struct, a construction of a framed struct, a
    copy of another holder, and a callee parameter some call site reaches with a
    frame address.  Three of those four are ASSIGNMENTS with a value, and they
    are the two spellings below plus a constructor call:

      * `S(...)` where `S` is a framed struct this module declares — the
        construction, whose result IS the address of a fresh block;
      * another holder's name — a copy, which copies the address;
      * (a method's receiver is a PARAMETER, so it is not a value at all.)

    `alias` is the struct the enclosing method is a method of, under the name
    `Self`, because `self = Self(...)` is how a Mojo constructor rebinds its own
    receiver and is in real stdlib code (`memory/alloc.mojo`,
    `runtime/tracing.mojo`) — so `Self(...)` is a construction, and without the
    alias every one of those files would be refused for rebinding a name to a
    fresh frame of its own type.

    A call to one of this module's own FUNCTIONS is on the list in exactly ONE
    case, and it is the case the returned-frame convention created: a function
    the image's own analysis has settled RETURNS A FRAME, so `q = make()` puts a
    frame address in `q` and reading `q.x` is a frame read.  That is evidence,
    not a guess — it is the same `returns_frame` table the emitter asks at the
    call site to decide whether to reserve a block, so a rebind check and a
    codegen cannot disagree about which calls hand back a frame.

    Every OTHER call is deliberately NOT on the list, and the reason is the one
    this docstring gave before the convention existed, unchanged: a call to an
    ordinary function says nothing about frames, the function's return is
    whatever its body returns, and a frame that outlived the function that built
    it is the use-after-free the escape checks exist for.  Allowing every call
    here would make the check silent for the shape it is most needed for — and
    with the convention in place the shape it is most needed for is the OTHER
    one, so the distinction is now the whole content of the rule.
    """
    if isinstance(value, F.IdentExpr):
        return value.name in holders
    if isinstance(value, F.CallExpr):
        callee = M.call_callee_name(value.func)
        if callee is not None and returns_frame and callee in returns_frame:
            return True
    if isinstance(value, F.CallExpr) and isinstance(value.func, F.IdentExpr):
        name = value.func.name
        if alias is not None and name == "Self":
            return M.struct_is_framed(alias)
        st = (structs_by_name or {}).get(name)
        return st is not None and M.struct_is_framed(st) \
            and M.type_constructor_kind(name) is None
    return False


def _collect_holder_rebinds(functions, holders, hstruct, structs_by_name,
                         returns_frame: dict = None) -> None:
    """PARK every name this function holds a frame for and also assigns a word to.

    The mirror image of the one-name-two-shapes defect wave 3 fixed, and
    invisible to that fix by construction: `model.struct_frame_slot_candidates`
    asks whether two FRAME layouts agree on a slot, and there is only one layout
    here.  The second binding is not a frame at all, so the candidate set is
    `[R]` and nothing contradicts it — there is simply a second binding whose
    value is a word.  Measured, both architectures, from a green build:

    ```
    class R:
        def __init__(self):
            self.a = 0
            self.b = 0
    def main(n):
        r = R()
        r.a = 7
        r = 5
        return r.a
    ```

    → SIGSEGV, exit 139, where the source says 5.

    **Parked, not raised, and that is the whole design.**  A refusal raised from
    here would come from inside `_prepare_functions`, which runs BEFORE
    `_resolve_imports`, so it would be reported in place of the import diagnosis
    — the defect `check_frame_field_blob_premises` and
    `check_construction_shapes` are placed outside that window to avoid, measured
    at 67 and 14 files of this repository respectively, and `mojo/middle/
    closures.py` moved from `not-answerable/host-import` to `codegen` when a new
    channel was added there.  So the finding lands on `fn._frame_holder_rebinds`
    and `check_frame_holder_rebinds` raises it from the entry points, beside
    those two.

    The finding is `(name, value spelling, the spelling that made it a holder)`,
    because the message has to name the binding that DISAGREES: the two readings
    are "`r` is a frame" and "`r` is a word", and the reader has to be told which
    line settles it rather than being handed the conclusion.

    `r = 5` inside a CONDITIONAL is the same finding, and is not special-cased:
    the analysis has no path sensitivity, which is the same statement
    `struct_dunder_dispatch_candidates` and `struct_frame_slot_candidates` make
    when they refuse rather than pick, and it is why a store to a name that only
    one path binds as a frame is refused here too.

    **The method's own receiver is EXCLUDED, and it has to be.**  `self = Self(…)`
    is how a Mojo constructor rebinds its own receiver, and it is in real stdlib
    code — five occurrences across `memory/alloc.mojo` and
    `runtime/tracing.mojo` alone — so a check that flagged it would refuse nine
    stdlib files for rebinding a name to a fresh frame of its own type, which is
    the opposite of the defect.  `self = <a word>` is a different thing again
    (the caller's slot still points at the old frame, so the method's effect
    does not reach its caller) and it is not this check's to decide; the escape
    checks are where a receiver that stops being the caller's object belongs.
    The exclusion is by NAME from `model.struct_receivers`, so `out self` and
    `inout self` are covered by the same rule rather than by a second one.
    """
    owners = M.method_owner_names(list((structs_by_name or {}).values()))
    for fn in functions:
        hs = holders.get(_fn_key(fn)) or ()
        if not hs:
            continue
        by_name = hstruct.get(_fn_key(fn)) or {}
        owner = owners.get(fn.name)
        receivers = set(M.struct_receivers(owner)) if owner is not None else set()
        findings = []
        for node in M.iter_nodes(getattr(fn, "body", None)):
            if isinstance(node, F.AssignStmt):
                if isinstance(node.target, F.IdentExpr):
                    targets = [node.target]
                elif isinstance(node.target, (F.TupleExpr, F.ListExpr)):
                    targets = list(node.target.elements)
                else:
                    targets = []
                values = (list(node.value.elements)
                          if isinstance(node.value, (F.TupleExpr, F.ListExpr))
                          else [node.value])
            elif isinstance(node, F.VarDecl):
                if node.value is None:
                    continue
                targets, values = [node.name], [node.value]
            else:
                continue
            if not targets or len(targets) != len(values):
                # A target/value arity this path does not pair up (a starred
                # element, a group) is the tuple-store pass's question, not this
                # one's; saying "one name is rebound" about a pairing that does
                # not exist would be a claim about a construct it did not read.
                continue
            for target, value in zip(targets, values):
                if not isinstance(target, F.IdentExpr) or target.name not in hs:
                    continue
                if target.name in receivers:
                    continue
                if _value_may_be_a_frame(value, structs_by_name, hs, owner,
                                        returns_frame):
                    continue
                cands = by_name.get(target.name) or ()
                findings.append((
                    target.name, _expr_spelling(value),
                    ", ".join(f"{st.name}()" for st in cands)
                    or "a frame this function was given",
                    tuple(cands)))
        if findings:
            fn._frame_holder_rebinds = findings


def check_frame_holder_rebinds(functions) -> None:
    """Raise the name-rebound-from-a-word findings `_collect_holder_rebinds` parked.

    The fourth late frame check, and it is at the entry points for the measured
    reason the other three are: `_prepare_functions` runs before the imports
    resolve, so a refusal raised from inside it preempts the import diagnosis,
    which is the answer that says whether the file is reachable at all.  One
    finding is raised rather than all of them, because a program with three of
    them has one defect with three lines and the first is enough to act on."""
    for fn in functions:
        for name, value_spelling, frame_spelling, cands in (
                getattr(fn, "_frame_holder_rebinds", ()) or ()):
            raise CodegenError(M.holder_rebound_from_a_word_refusal(
                fn.name, name, value_spelling, frame_spelling,
                cands))


def _rewrite_nested_method_calls(fn, nested_fields) -> None:
    """`h.a.m(x)` → `A_m(h.a, x)`, for the fields `nested_fields` names.

    The last step of a nested frame, and it exists because the OTHER method-call
    rewrite cannot do it.  `_rewrite_method_calls` runs before any frame
    analysis exists, so at that point nothing knows that `h.a` is a nested frame
    rather than a value; and it only rewrites a receiver that is a plain
    `IdentExpr`, so a `MemberExpr` receiver was never rewritten at all and the
    chain reached the backend as a call to a symbol spelled `self.inner.sum`.
    Rewriting it HERE, from the table the declared-type agreement produced, is
    what makes the ordinary call path apply: the receiver is a frame slot, the
    call is an ordinary `BL A_m`, and nothing new has to be right.

    The receiver stays the slot key `h.a`, which is a load out of the outer
    frame — the same word the value-position read of that field produces — so
    both spellings of the access go through `_load_var` and there is one
    lowering of it.

    Only a receiver the table names is rewritten.  A chain the table does not
    name is left alone deliberately: it is either a value receiver (the
    declared type said the slot is not a frame) or untyped, and both of those
    already have a diagnostic that describes them.  Rewriting a guess here would
    replace a refusal with a call to a struct's method on a word that is not its
    frame, which is C5's second silently-wrong program with a new cause.
    """
    if not nested_fields:
        return
    for node in M.iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr) or not isinstance(node.func,
                                                             F.MemberExpr):
            continue
        obj = node.func.obj
        if not isinstance(obj, F.MemberExpr):
            continue
        key = _root_ident(obj)
        if key is None or key[1] != 1:
            continue
        st = nested_fields.get(f"{key[0]}.{obj.member}")
        if st is None:
            continue
        node.func = F.IdentExpr(name=M.method_function_name(st.name,
                                                            node.func.member))
        node.args = [obj] + list(node.args)


def _rewrite_identity_intrinsic_calls(functions) -> None:
    """Erase every `origin_of(x)` in `functions` down to `x`, in place.

    THE REWRITE AND NOT A LOWERING, and the reason is measured rather than
    stylistic: the escape analysis reads the AST, so a lowering that lives in an
    emitter leaves `origin_of(s)` standing in the tree the build pass has
    already walked, and the frame address the call names walks straight through
    three refusals that are all correct about it and none of which can see it.

    Measured on both architectures, with the identity implemented in the
    emitters and everything else about this change in place:

    ```
    struct S:  a, b
    def main(n): var s = S(); s.a = 3; s.b = 4; return origin_of(s)
    ```
    BUILDS, RUNS, and returns the frame's own address modulo 256. `return s` is
    refused by name (`frame_return_refusal`) and `return origin_of(s)` was not,
    because by the time the return branch is asked, the node is a call it does
    not recognise rather than the bare name it refuses. And:

    ```
    printf("%d\n", origin_of(s))
    ```
    builds, runs, prints `1793355120` — the frame's address as a decimal — and
    exits 0. That is the precise failure `FRAME_C_VALUE_CALLS`'s own message
    cites as the reason the hand-off is refused ("measured, `printf(\"val=%d\n\",
    r)` builds, runs, prints the frame's address as a decimal, and exits 0"),
    reached through a door the fix had opened. So the call is erased HERE, where
    every consumer downstream — the escape walk, the holder fixpoint, the
    position rules, both emitters — reads the same tree this rewrite leaves
    behind, and `origin_of` becomes indistinguishable from the operand it was
    already the identity of. That is also why nothing else has to be taught
    about it: no emitter branch, no new refusal, one rewrite.

    WHERE it runs is load-bearing in the same way `_frame_receivers` is: last of
    the rewrites, and before the frame analysis, so it sees the final function
    list and so does the analysis that has to see the result. It is called from
    `_prepare_functions` rather than from inside `_frame_receivers`, because that
    function returns early for a unit with no framed struct at all, and the
    identity does not care whether the operand is a frame: `origin_of(n)` on a
    plain `Int` is the same rewrite, and it is the case that was refused for a
    DIFFERENT reason — an emitted call to a symbol nothing in this image
    defines, which the link check reported as an unbound symbol rather than as
    anything to do with the construct.
    """
    for fn in functions:
        _erase_identity_intrinsics(getattr(fn, "body", None))


def _erase_identity_intrinsics(node):
    """`node` with every identity-intrinsic call in it replaced by its operand.

    Returns the node to USE in its place, which is `node` itself unless it was
    one of those calls. Functional rather than in-place, because the children of
    a statement tree live in LISTS (`args`, `kwargs`, `elements`, `pairs`) and
    `body` is itself a list: replacing an element of one in place means knowing
    every field name that holds a list, and this rebuilds whatever it is handed
    and puts it back through `setattr` instead, so a new child list shape is
    not a place this can be wrong.

    NOTHING IS ALLOCATED unless something changes: a list or tuple comes back as
    the object it was handed unless one of its elements moved, which is the case
    for every list in every function of every unit this path compiles — the
    compiler's own sources included, in the self-host steps. A rewrite that
    rebuilt the whole tree unconditionally would be a per-compile cost paid by
    programs that never write `origin_of` at all.

    A nested `FunctionDef` is rewritten too, which is deliberate and matches
    `model.iter_nodes`: the escape walk descends into one, so a call this
    rewrite erased from inside it has to be erased before the escape walk asks.
    Running over the flattened function list as well is harmless — the second
    pass finds nothing to do.
    """
    if isinstance(node, (list, tuple)):
        moved = None
        for i, x in enumerate(node):
            replacement = _erase_identity_intrinsics(x)
            if replacement is x:
                continue
            if moved is None:
                moved = list(node)
            moved[i] = replacement
        if moved is None:
            return node
        return tuple(moved) if isinstance(node, tuple) else moved
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.IdentExpr):
        operand = M.identity_call_operand(node.func.name, node)
        if operand is not None:
            # Recurse INTO the operand rather than returning it whole, so
            # `origin_of(origin_of(s))` erases both and not just the outer one.
            return _erase_identity_intrinsics(operand)
    for fname in getattr(node, "__dataclass_fields__", ()):
        if fname in ("line", "col"):
            continue
        value = getattr(node, fname, None)
        if value is None or isinstance(value, (int, float, str, bool)):
            continue
        replacement = _erase_identity_intrinsics(value)
        if replacement is not value:
            setattr(node, fname, replacement)
    return node


def _rewrite_len_on_frame_receivers(functions, holders, hstruct) -> int:
    """`len(h)` → `Struct___len__(h)`, for every `h` that holds a frame.

    The `len` half of the by-reference hand-off, and the reason it is a REWRITE
    rather than a lowering is that the lowering already exists: `h.__len__()` is
    what `_rewrite_method_calls` turns into `Struct___len__(h)`, the callee is
    compiled as an ordinary function taking its receiver first, and that first
    parameter is a frame address on both the caller's and the callee's side of
    the boundary.  So the question this pass answers is not "how do I compute a
    length" — it is "WHICH struct's `__len__` is this", and
    `model.struct_dunder_len_candidates` is the one place that is decided.

    It cannot be done where `_rewrite_method_calls` runs, for the reason
    `_rewrite_nested_method_calls`'s docstring gives about its own job: at that
    point no frame analysis exists, so nothing knows that `h` is a frame rather
    than a word, and a `len` on an ordinary value — a string, a list — must keep
    going to the count-field and `strlen` lowerings.  Guessing there would
    replace those with a call to a method the type may not have.

    The three cases, and each one is a DIFFERENT answer rather than a variant:

      * the name holds a frame and every candidate struct declares a
        `__len__`  → rewritten;
      * the name holds a frame and NO candidate declares one  → left alone, and
        `model.frame_len_refusal` says so at the hand-off.  This is the case
        `FRAME_VALUE_ONLY_CALLS` was right about all along and the old message
        was not: there is genuinely no length in a frame;
      * the name holds a frame and the candidates DISAGREE about `__len__`  →
        refused, naming which candidate declares one.  Agree-or-refuse, the same
        rule and for the same reason as `struct_frame_slot_candidates`: which
        frame the name holds depends on the path taken, and this analysis has
        none, so the call the rewrite would emit is one of two and the program
        would build, run, and answer with the other struct's length.

    Only a BARE NAME is rewritten.  A chain is a field read, and `len(h.xs)` is
    the blob-count lowering that has always worked; rewriting it would call a
    struct's `__len__` on a word that is a value.
    """
    moved = 0
    for fn in functions:
        hs = holders.get(_fn_key(fn)) or ()
        by_name = hstruct.get(_fn_key(fn)) or {}
        if not hs:
            continue
        # Collected first and mutated after, for the reason
        # `_rewrite_nested_method_calls` is called outside the walk that
        # discovers what it rewrites: `M.iter_nodes` yields a node and then
        # recurses into its fields, so replacing a field while it is being
        # walked is how a pass ends up seeing a node twice or not at all.  The
        # rewrite is idempotent here, but the collection is what makes that a
        # property of the shape rather than of the ordering.
        pending = []
        for node in M.iter_nodes(getattr(fn, "body", None)):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.IdentExpr) \
                    or node.func.name != "len" \
                    or (node.kwargs or []) \
                    or len(node.args or []) != 1:
                continue
            operand = node.args[0]
            if not isinstance(operand, F.IdentExpr) or operand.name not in hs:
                continue
            cands = by_name.get(operand.name) or ()
            if not cands:
                # A name with no candidate struct is a plain word, and `len` on
                # a plain word is the lowering that has always run.
                continue
            owner, (disagree, rows) = M.struct_dunder_len_candidates(cands)
            if disagree:
                raise CodegenError(M.frame_len_candidates_disagree(
                    _expr_spelling(operand), [st.name for st in cands], rows))
            if owner is None:
                continue
            pending.append(
                (node, M.method_function_name(owner, M.DUNDER_LEN)))
        for node, callee in pending:
            node.func = F.IdentExpr(name=callee)
        moved += len(pending)
    return moved


def _replace_nodes(root, replacements: dict) -> None:
    """Swap each child of `root` that `replacements` names, in place.

    A pass that has to turn one NODE into a differently-shaped node — a
    `BinaryOp` into a `CallExpr` — cannot do it by mutating the node it found,
    because the fields it would have to write do not exist on the shape it is
    replacing.  It has to reach the parent, which is why this exists and why
    `M.iter_nodes` is not enough: that walk yields a node and then recurses into
    it, so a rewrite applied during the walk is a walk that mutates what it is
    walking.  Collect first, replace second, exactly as
    `_rewrite_len_on_frame_receivers` does.

    Keyed by `id()` because the nodes are dataclasses with no `__eq__` of their
    own — `id` is the identity the walk has, and every key here comes from a node
    the walk is currently holding, so no node can be collected and freed between
    being found and being replaced.
    """
    if isinstance(root, (list, tuple)):
        for i, child in enumerate(root):
            new = replacements.get(id(child))
            if new is not None:
                root[i] = new
            else:
                _replace_nodes(child, replacements)
        return
    if not hasattr(root, "__dataclass_fields__"):
        return
    for name in root.__dataclass_fields__:
        child = getattr(root, name)
        new = replacements.get(id(child))
        if new is not None:
            setattr(root, name, new)
        elif isinstance(child, (list, tuple)):
            _replace_nodes(child, replacements)
        elif hasattr(child, "__dataclass_fields__"):
            _replace_nodes(child, replacements)


def _eq_dispatch_call(node, op: str, left, right, cands_l, cands_r, by_name,
                      hs) -> object:
    """The call that answers `left op right`, or None to leave the operator be.

    The decision is `model.struct_dunder_dispatch_candidates` and nothing here
    decides it again; this reads its answer out of the table, refuses the
    disagreement by name, and builds the call the ordinary call path then
    handles.  `None` is the answer for every shape this pass deliberately does
    not touch, and each is a shape where the pre-existing lowering is either
    CORRECT or already refused by something closer to the mistake:

      * an operand that is not a BARE NAME — `f(h) == h`, `h.x == h`.  The
        holder table is keyed by name, and a name is the only thing here that can
        say what a word holds; guessing past it is the bug this file exists to
        stop;
      * a name with no candidates, which is a plain word, so its `==` is the
        word compare that has always run;
      * no candidate declaring the dunder, which is CPython's INHERITED
        identity `__eq__` — and a frame's address compare already IS that, so
        leaving it alone is the right answer and not a gap.
    """
    if not isinstance(left, F.IdentExpr) or not isinstance(right, F.IdentExpr):
        return None
    if left.name not in hs or right.name not in hs:
        return None
    cands = list(by_name.get(left.name) or ()) + list(by_name.get(right.name)
                                                  or ())
    if not cands:
        return None
    owner, dunder, negate, (disagree, rows) = \
        M.struct_dunder_dispatch_candidates(cands_l, cands_r, op)
    if disagree:
        raise CodegenError(M.eq_dispatch_candidates_disagree(
            f"{left.name} {op} {right.name}",
            sorted({st.name for st in cands}), rows))
    if owner is None:
        return None
    call = F.CallExpr(
        func=F.IdentExpr(name=M.method_function_name(owner, dunder)),
        args=[left, right])
    if not negate:
        return call
    return F.UnaryOp(op="not", operand=call)


def _rewrite_eq_on_frame_receivers(functions, holders, hstruct) -> int:
    """`a == b` → `Struct___eq__(a, b)`, for two names that hold the same frame.

    The COMPARISON half of what `_rewrite_len_on_frame_receivers` does for
    `len`, and it is here for exactly the reason that function's call site gives:
    the operator carries no type, so nothing can decide WHOSE `__eq__` it is until
    the holder analysis has run, and rewriting it before then would replace a
    word compare with a call to a method the type may not have.

    Why it was a WRONG ANSWER and not a refusal: `a == b` on two frame
    addresses is a flag-setting compare of two words, and the words are
    ADDRESSES, so the operator answers "are these the same object" — which is
    CPython's INHERITED `__eq__` and is correct for a struct that declares none.
    A struct that DOES declare one is the case the language sends to the method
    and the lowering bypassed: measured, a class whose `__eq__` returns
    unconditionally True gave `eq=0 direct=1`, where CPython gives
    `eq=1 direct=1` — the method was found, called and ignored by the operator,
    and a program that took the wrong branch said nothing about it.

    BOTH operands must be names this analysis believes hold a frame of the SAME
    single struct, and that is the whole of the safety argument, so it is worth
    spelling out rather than leaving to the code:

      * both being holders is what makes the rewritten call SAFE.  The callee is
        the struct's own method, its first parameter is that struct's receiver,
        and a receiver is a frame address by definition — so the call is the
        shape the by-reference design exists for and `_check_frame_escapes`
        follows it into a parameter it recognises.  Rewriting `h == 5` instead
        would hand a word that may not be a frame to a method that dereferences
        it, and `h`'s own name can be rebound to a word elsewhere in the same
        function (`bugs/FORMAL_holder_rebound_from_a_word.md`), so "may not be"
        is a measured fact about this pass, not a hypothetical;
      * the SAME struct is what makes it CORRECT.  Python resolves
        `a == b` through `type(a)`, and the two agreeing means there is no
        reflected-operand question to answer — which this path could not answer,
        since `NotImplemented` has no representation;
      * a disagreement is REFUSED rather than resolved, for the reason
        `struct_frame_slot_candidates` gives: the call would be one of two and
        the program would build, run and answer with the other one.

    The chain spelling (`a == b == c`) is one `F.CompareChain` and lowers here
    as the `and` of its pairwise comparisons, which is what the language says a
    chain is.  Only when EVERY operand is a bare name: the rewrite re-reads the
    middle operands, and a name read twice is the same load twice, while an
    operand with a call in it would be called twice where the language calls it
    once.  A chain with a call in it is left alone — see the remainder named in
    `bugs/FORMAL_eq_does_not_dispatch_to_a_user_dunder.md`.

    Returns how many operators it rewrote, which is what lets the caller run
    this and the holder fixpoint as ONE fixpoint: a round that neither grew a
    holder nor moved an operator has nothing left to do, and a round that DID
    move one may have introduced a call the next round's fixpoint has to follow.
    """
    moved = 0
    for fn in functions:
        hs = holders.get(_fn_key(fn)) or ()
        by_name = hstruct.get(_fn_key(fn)) or {}
        if not hs:
            continue
        pending = []
        for node in M.iter_nodes(getattr(fn, "body", None)):
            if isinstance(node, F.BinaryOp) and node.op in ("==", "!=") \
                    and isinstance(node.left, F.IdentExpr) \
                    and isinstance(node.right, F.IdentExpr):
                call = _eq_dispatch_call(
                    node, node.op, node.left, node.right,
                    by_name.get(node.left.name) or (),
                    by_name.get(node.right.name) or (), by_name, hs)
                if call is not None:
                    pending.append((id(node), call))
                continue
            if not isinstance(node, F.CompareChain) or len(node.ops) < 2:
                continue
            if any(op not in ("==", "!=") for op in node.ops):
                continue
            if not all(isinstance(o, F.IdentExpr) for o in node.operands):
                continue
            links, lowered = [], True
            for i, op in enumerate(node.ops):
                left, right = node.operands[i], node.operands[i + 1]
                call = _eq_dispatch_call(
                    node, op, left, right, by_name.get(left.name) or (),
                    by_name.get(right.name) or (), by_name, hs)
                if call is None:
                    lowered = False
                    break
                links.append(call)
            if not lowered:
                continue
            # `and`, folded left, so the leftmost comparison is evaluated first
            # and a false one short-circuits the rest — the chain's own rule,
            # reached by the same short-circuit `and` every other one uses.
            whole = links[0]
            for link in links[1:]:
                whole = F.BinaryOp(op="and", left=whole, right=link)
            pending.append((id(node), whole))
        for node_id, call in pending:
            _replace_nodes(fn.body, {node_id: call})
        moved += len(pending)
    return moved


def _rewrite_len_on_nested_frames(fn, by_name, structs_by_name) -> None:
    """`len(h.a)` → `Struct___len__(h.a)`, when `h.a` holds a placed frame.

    The same rewrite as `_rewrite_len_on_frame_receivers` for the OTHER spelling
    of a frame address, and it settles its struct with `_typed_nested_frame` —
    the SAME function the depth-2 paths use — so the two spellings reach one
    decision by one route rather than by two decisions that could come apart.
    That matters here in a way it did not for a bare name: whether the slot holds
    this unit's placed frame or whatever some method last assigned into it is
    the lifetime question, and `_typed_nested_frame`'s `_REASSIGNED` answer is
    what settles it.  A struct this compiler placed in the outer object's own
    block outlives the call; a frame belonging to whichever function ran the
    assignment need not, and reading it would be a use-after-free.

    It runs LATER than the bare-name pass, and for a reason that is about
    reachability rather than order: `_check_frame_escapes` refuses a BARE NAME
    holding a frame, and `h.a` is a field read — a 64-bit value, not an address
    — so nothing refuses `len(h.a)` on the way past and it reaches the emitter
    either way.  The bare-name spelling has to be rewritten before that check;
    this one does not.

    `_typed_nested_frame` returning `_NOT_TYPED` or `_REASSIGNED` is NOT
    re-raised here, and deliberately: the emitter's own `model.len_refusal` is
    already what refuses those programs, and a refusal raised from
    `_prepare_functions` is reported INSTEAD of the import diagnosis — the
    measured defect `check_frame_field_blob_premises` and
    `check_construction_shapes` are placed outside the wrapper to avoid, which
    cost `mojo/middle/closures.py` its import diagnosis once already.  Leaving
    them to the emitter is both the smaller change and the one that keeps the
    file's class.

    The receiver stays the slot key `h.a` rather than becoming a copied-out
    value, which is the whole of the by-reference argument for a nested frame:
    the slot holds a real frame address placed in the outer object's own block
    (`model.struct_nested_frame_fields`), so handing it to the method is handing
    it the address, and the callee reads `[base + 8k]` out of storage whose
    lifetime is the outer object's.
    """
    for node in M.iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr) \
                or not isinstance(node.func, F.IdentExpr) \
                or node.func.name != "len" \
                or (node.kwargs or []) \
                or len(node.args or []) != 1:
            continue
        operand = node.args[0]
        if not isinstance(operand, F.MemberExpr):
            continue
        key = _root_ident(operand)
        if key is None or key[1] != 1:
            continue
        base, field = key[0], operand.member
        cands = by_name.get(base) or ()
        if not cands:
            continue
        nested = _typed_nested_frame(base, field, cands, structs_by_name, None)
        if not isinstance(nested, F.StructDef):
            # No `__len__` on the placed frame's struct, or the slot is not one
            # this unit placed.  Both are the emitter's business and both are
            # already refused there; see the docstring.
            continue
        if M.dunder_len_method(nested) is None:
            continue
        node.func = F.IdentExpr(name=M.method_function_name(nested.name,
                                                            M.DUNDER_LEN))


# The three answers a field's declared type can have, as one value rather than
# two, because "no single type" and "a single type that is not a frame" are the
# two halves of the rule and mixing them up is the silently-wrong direction in
# both directions: treating an untyped slot as a value read gives a scratch
# register, and treating a value as a frame address gives a wild load.
#
#   `_NOT_TYPED`   — the candidates do not agree, so nothing is known.
#   `None`         — they agree, and the agreed type is provably NOT a frame of
#                    this unit, so the word in the slot is a plain value.
#   `_REASSIGNED`  — they agree, and it IS a framed struct of this unit, but
#                    some executed method WRITES the field, so the slot holds
#                    whatever that assignment put there rather than the frame the
#                    constructor placed.  Distinct from `_NOT_TYPED` because the
#                    diagnosis is different and much more useful: the type is
#                    known and it is a frame, and what is unknown is WHOSE.
#   a StructDef    — they agree, it is a framed struct of this unit, and nothing
#                    writes the field, so the word in the slot is the address of
#                    a NESTED FRAME that `model.struct_nested_frame_fields`
#                    places in the outer object's own block.
#
# The fourth answer is the one that took a measurement to get right.  Without
# it, a written field was treated as the constructor's frame and every write to
# it was refused — which is sound about the frame and useless about the
# program: `self._bytes = remaining` in `std/collections/string/_utf8.mojo` is
# ordinary code, and refusing it moved 164 stdlib files' verdicts in the sweep
# to say so.
_NOT_TYPED = object()
_REASSIGNED = object()


def _field_annotation(cands, name, decls=None):
    """The type of `name` as a candidate spells it, for a message.

    The first candidate's answer, and only ever used to NAME a type in a
    diagnostic — the decision itself is `frame_field_type_candidates`, which
    requires unanimity.  A reader is better served by the spelling one
    candidate used than by no type at all, and the message says "is declared as"
    rather than asserting it is the type.

    `decls` is the same table the decision was made from, so the spelling is
    the DECLARATION's when there is one and the constructor assignment's when
    there is not; a message that printed "is declared as" for the second would
    send the reader to a declaration the class does not have.
    """
    for st in cands:
        _base, ann, _ev, _why = M.struct_field_type(st, name, decls)
        if ann is not None:
            return ann
    return None


def _type_rows(cands, name, decls=None):
    """The type evidence for a field, for a refusal to quote.

    A function rather than a call at each use site because the refusal has to
    quote the SAME table the decision was made from; recomputing it at the raise
    would be a second walk of the same candidates that could disagree with the
    first, and a refusal that misreports why it fired is worse than one that
    does not report at all."""
    return M.field_type_rows(cands, name, decls)


def _typed_nested_frame(base, field, cands, structs_by_name, method_owner):
    """The nested frame `base.<field>` holds, or `_NOT_TYPED`, or None.

    The whole of C5's named next step, in one function: read a field's DECLARED
    type, apply the agree-or-refuse rule to it
    (`model.frame_field_type_candidates`), and return the one thing the emitter
    can act on.  Three answers, as `_NOT_TYPED` documents.

    `method_owner` is the struct declaring the method being called on the field,
    or None for a value-position field read.  It is used for ONE thing and that
    thing is worth reading twice: when the agreed type is a framed struct but a
    DIFFERENT struct owns the method, the call is a mis-dispatch and this path
    must not place a nested frame to make it work.  `recv.m(x)` carries no type,
    so `_rewrite_method_calls` has already sent it to `method_owner.m` by name
    alone; placing a nested frame for a type the callee does not expect would
    make the program build and compute on the wrong layout, which is the shape
    of C5's second silently-wrong program with a different cause.

    The four answers are `_NOT_TYPED`, `None`, `_REASSIGNED` and a StructDef;
    see the note on the sentinels for why `_REASSIGNED` is not the same answer
    as `_NOT_TYPED`.
    """
    if not cands:
        return _NOT_TYPED
    nested, (disagree, _rows) = M.frame_field_type_candidates(
        cands, field, structs_by_name)
    if nested is None:
        if disagree:
            return _NOT_TYPED
        return None
    if method_owner is not None and method_owner.name != nested.name:
        return None
    # Agreed, and it names a framed struct.  It is a NESTED FRAME only if every
    # candidate both agrees and never writes the field — the placement list is
    # the authority, and consulting it rather than re-deriving the condition is
    # what keeps the emitter and this decision from disagreeing about which
    # fields are placed.
    for st in cands:
        if not any(name == field for name, _slot, _child
                   in M.struct_nested_frame_fields(st, structs_by_name)):
            return _REASSIGNED
    return nested


def _defer_subscript_escape(fn, value, holders, by_name, spelled,
                            returns_by_name=None) -> None:
    """Record a frame address stored through a subscript, for a LATE refusal.

    Nothing is raised here.  The refusal is real and the finding is kept, but
    `_check_frame_escapes` runs inside `_prepare_functions`, which is before the
    imports resolve, and a refusal raised there is reported INSTEAD of the
    import diagnosis — the defect `check_frame_field_blob_premises` and
    `check_construction_shapes` are placed outside the wrapper to avoid, for
    the same measured reason.  So the finding is parked on the function and
    `check_frame_subscript_escapes` raises it from the entry points, beside the
    other two.

    The measured cost of getting this wrong, on this branch: with it raising
    here, `mojo/middle/closures.py` was reported as a `codegen` finding about
    `self.dispatch_patterns[pattern_key]` when what the reader needs first is
    "imports 'fire_compiler', which … imports 're', which is a host module".
    One file moved the wrong way and the wrong message won."""
    if isinstance(value, F.IdentExpr):
        if value.name not in holders:
            return
        cands = by_name.get(value.name) or []
        who = ", ".join(st.name for st in cands) if cands else value.name
    elif isinstance(value, F.CallExpr):
        # `xs[1] = make(5)`.  A call to a frame-returning callee puts the address
        # of the block THIS function reserved into the list, and the list's
        # element is a heap cell that outlives this activation — so it is the
        # same escape as `q[0] = r` with the frame one lifetime further out.  It
        # used to be missed because the value is a call rather than a name, and
        # the emitter's subscript store does not lower a frame address, so the
        # store was dropped: the program built, ran, and exited 0 where the
        # source says 5.  The read of `returns_by_name` is the fixpoint's JOIN,
        # so a name whose definitions disagree is absent from it and the store is
        # not refused on one of two answers.
        callee = M.call_callee_name(value.func)
        st = returns_by_name.get(callee) if callee else None
        if st is None:
            return
        who = f"frame in {callee}()"
    else:
        return
    fn._frame_subscript_escapes = list(
        getattr(fn, "_frame_subscript_escapes", ())) + [(
            who, M.expr_spelling(value), spelled, fn.name)]


def check_frame_subscript_escapes(functions) -> None:
    """Raise the frame addresses `_check_frame_escapes` parked on the functions.

    The third of the three late frame checks, and it is here for the same reason
    as the other two: a refusal raised before the imports resolve is reported
    in place of the import diagnosis, which is the more useful of the two
    answers and the one that says whether the file is reachable at all."""
    for fn in functions:
        for who, name, spelled, where in (
                getattr(fn, "_frame_subscript_escapes", ()) or ()):
            raise CodegenError(
                f"a {who} receiver is stored through {spelled!r} in {where}(), "
                f"so it outlives the frame it names: the list's element is a "
                f"heap cell, so the word survives the call the frame was "
                f"created in, and the read that follows it is a read of "
                f"reused bytes. Measured on both architectures with nothing "
                f"lifted, before this check existed: the shape builds, runs, "
                f"and returns 0 where the source says 7 — silently, with the "
                f"program exiting 0")


def check_returned_frame_blob_writes(functions) -> None:
    """Refuse a CONTAINER written into the block a function RETURNS.

    A fourth late frame check, and here for the reason the other three are:
    `_prepare_functions` runs before the imports resolve, so a refusal raised
    from inside it is reported in place of the import diagnosis, and the import
    is the more useful of the two answers.

    It exists because the returned-frame convention opens a hole the by-reference
    receiver does not have.  Premise (B1) — a frame slot never holds a blob — is
    true because a blob is bump-allocated in the function that made it, and it
    is enforced for METHODS by `check_frame_field_blob_premises`.  A returned
    block outlives the function that made it, so the same reasoning applies with
    the sign reversed: a blob written into that block names scratch the caller
    has already taken for its own frames, and the first append through it writes
    into the callee's reclaimed stack.  The program builds, runs, and returns a
    number nobody wrote.

    It reads `fn._returned_frame` — the `(holder, struct)` pair
    `_frame_receivers` publishes for every function that hands a frame back, and
    the same pair the emitters' copy is sized from, so the block this refuses is
    the block that would otherwise have been written into.
    """
    for fn in functions:
        plan = getattr(fn, "_returned_frame", None)
        if plan is None:
            continue
        holder, _struct = plan
        for field, why in M.returned_frame_container_writes(fn, holder):
            raise CodegenError(M.returned_frame_blob_refusal(
                fn.name, holder, field, why))


def check_frame_field_blob_premises(structs) -> None:
    """Refuse a method that puts a CONTAINER into a field of a framed receiver.

    Called by the ENTRY POINTS, after their imports have resolved, and not from
    `_prepare_functions` — and the reason is a measured one rather than a
    stylistic one. `_prepare_functions` runs BEFORE `_resolve_imports`, so a
    refusal raised from inside it preempts the import diagnosis, and this check
    fires on 106 of this repository's 284 files: 67 of them import a CPython
    host module, and for those the import is the more fundamental fact (a file
    that imports `ast` is out of this backend's reach whatever its codegen
    says).  Measured with the call inside `_prepare_functions`: 67 files moved
    `not-answerable/host-import` → `codegen`, which puts 67 unbuildable files
    into the measured denominator and reports the coverage as 40.4% when the
    accurate figure is the baseline's.  That is the mirror image of the drift
    `bugs/FORMAL_wide_receiver_by_reference.md` calls out, and it flatters
    nothing while misinforming.

    So the check moved LATER, to the one point where both facts are known.  It
    is a separate function rather than a flag so that "which entry points call
    it" is a one-line answer, and both call sites are marked.

    The enforcement half of the premise `formal/model.py` states
    (`model.frame_field_premise` / `FRAME_FIELD_BLOB_PREMISE_B1`).  The premise
    is that a frame slot never holds a blob, and it was true only because two
    other decisions happened to make it true: no field can take a non-literal
    default, and `S()` does not run `__init__`.  Neither is a property of the
    frame layout, so a `reset()` that assigns a list into a field — a shape
    ordinary Python and absent from the corpus only by luck — put a blob in a
    slot with the ASSIGNING function's lifetime while the slot's lifetime is
    the object's.  A method reaching through the slot afterwards appends into
    reclaimed stack.  The program builds, runs, and returns a number nobody
    wrote.

    Framed structs only.  A ONE-WORD struct's receiver IS its field, so a
    container written there is a blob in a local slot whose lifetime the
    ordinary value path already governs, and refusing it would be refusing a
    different (and separately owned) problem.  The narrowness is deliberate:
    this check is about the lifetime the FRAME introduces, and it should not
    reach past that.

    `__init__` is excluded, and the reason is the second premise rather than a
    convenience: it does not run on this path.  That is the whole content of
    why nearly every container-shaped struct in the corpus passes this check
    while `self.items = List[Self.T]()` sits unread in its `__init__` — and
    `model.frame_field_premise_note` is what says so out loud, so the exclusion
    is a stated premise with a name rather than a silent hole.
    """
    for st in structs:
        if not M.struct_is_framed(st):
            continue
        writes = M.struct_field_container_writes(st)
        if writes:
            raise CodegenError(M.frame_field_premise_refusal(st))


def check_dataclass_constructs(stmts: list, functions: list) -> None:
    """Every `@dataclass` construct in the unit, checked. One refusal each.

    Called by the ENTRY POINTS, beside `check_construction_shapes`, and for the
    same measured reason: `_prepare_functions` runs before `_resolve_imports`,
    so a refusal raised from inside it preempts the import diagnosis and reports
    the secondary problem on every file that imports a CPython host module.
    This backend's `dataclasses` is a FRONT-END transform
    (`formal/dataclass_transform.py` has the measurement that decides the
    layer), so this check is the back half of it: the rewrites happened in
    `_prepare_functions`, and what is left is what cannot be rewritten.

    Two halves, and they are different in kind:

      * the CLASS checks — inheritance, `@dataclass(...)` options, `__post_init__`,
        `InitVar` — read the module's StructDefs. They are a fact about the file
        and are true whatever the file imports;
      * the REFLECTION checks — `dc.fields(x)`, `is_dataclass(v)` — read the
        function bodies, and are gated on the file having IMPORTED
        `dataclasses`, which is what `DC.bound_module_names` computes from the
        import statements. Without that gate this would refuse every `.fields`
        in the tree, including the ones on objects that have nothing to do with
        this module.

    Both halves are cheap when there is nothing to do: `dataclass_classes`
    returns `{}` for a file with no `@dataclass`, and `bound_module_names`
    returns `set()` for a file with no such import, so the whole check is a
    function call on 578 of the sweep's files. That matters because it runs on
    every build of every file, including the 664 stdlib ones."""
    # …and over THIS MODULE'S OWN StructDefs, for the same reason the rewrite in
    # `_prepare_functions` is: an imported declaration belongs to a separate
    # compilation unit that goes through this same pipeline when it is built
    # into a dylib, so checking it here reports another file's class against
    # this file.
    classes = DC.dataclass_classes(stmts)
    if classes:
        DC.check_dataclass_classes(classes)
    names = DC.bound_module_names(stmts)
    if names:
        DC.check_reflection_calls(functions, names)


def check_construction_shapes(functions, structs_by_name) -> None:
    """Decide every `S(...)` in the unit, and refuse the ones with no shape.

    Called by the ENTRY POINTS, beside `check_frame_field_blob_premises`, and
    for the SAME measured reason: `_prepare_functions` runs before
    `_resolve_imports`, so a refusal raised from inside it preempts the import
    diagnosis.  This one fired on **14 of this repository's 284 files** from
    there — every one of them a file that imports a CPython host module, so
    every one of them a file that is out of reach whatever its codegen says —
    and all 14 moved `not-answerable/host-import` → `codegen`, which puts 14
    unbuildable files into the measured denominator.  The same drift in the same
    direction, one function over.

    It is a separate function rather than a branch of `_check_frame_escapes`
    for a second reason, and this one is about ORDER rather than diagnosis: a
    struct-constructor call has to be SKIPPED by the escape check's
    argument-position loop, because `S(a, r)` has a frame address in a
    non-first position and that loop would refuse it as "a position whose
    meaning this path cannot see" — a sentence about a construct that is a
    perfectly ordinary positional construction.  So the skip has to be here,
    in the loop, and the decision has to be somewhere that can run after the
    loop has had its say.

    The DECISION is `model.struct_construction_plan`, the same function both
    backends call before they emit, and the same text — which is what lets one
    `refuse:` case in `test_formal_run.py` hold both architectures and the
    build pass at once.

    `functions` rather than `structs`, because a construction is a call in
    some function's body.  `fn._frame_candidates` is the holder table
    `_frame_receivers` published, and it is what tells a COPY construction what
    its source is; a function with no holders has none published, and an empty
    table is the right answer there — a name that is not a holder is a plain
    word, and the copy decision refuses exactly that.
    """
    if not structs_by_name:
        return
    rets = M.function_return_types(functions)
    for fn in functions or ():
        cands = getattr(fn, "_frame_candidates", None) or {}
        for node in M.iter_nodes(getattr(fn, "body", None)):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.IdentExpr):
                continue
            st = structs_by_name.get(node.func.name)
            if st is None or M.type_constructor_kind(node.func.name) is not None:
                continue
            _plan, refusal = M.struct_construction_plan(
                st, node, structs_by_name, cands, rets)
            if refusal is not None:
                raise CodegenError(refusal)


# `_check_nested_frame_writes` USED to live here, refusing any write to a field
# that held a placed nested frame.  It is gone, and the reason is worth
# recording because the deletion is the fix rather than a simplification: the
# check was a band-aid over a placement decision that was too permissive, and
# it fired 164 stdlib files' worth of ordinary code (`self._bytes = remaining`)
# for a frame the program had just replaced.  `model.struct_nested_frame_fields`
# now excludes every field some executed method writes, so a placed nested
# frame is write-once BY CONSTRUCTION and there is nothing left to check.  The
# four-way answer in `_typed_nested_frame` is what a written field gets instead,
# and it is a diagnosis rather than a prohibition: the type is known, the field
# is known to be reassigned, and what is unknown is whose frame the slot holds.


def _describe_value(value) -> str:
    """How a refusal names the value that would have gone into a nested slot."""
    if value is None:
        return "no value"
    if isinstance(value, F.IdentExpr):
        return f"a name, {value.name!r}"
    if isinstance(value, F.CallExpr):
        name = value.func.name if isinstance(value.func, F.IdentExpr) else "?"
        return f"a call to {name!r}"
    if isinstance(value, (F.ListExpr, F.DictExpr, F.TupleExpr)):
        return "a container literal"
    if isinstance(value, F.IntLiteral):
        return f"the literal {value.value}"
    if isinstance(value, F.StringLiteral):
        return f"the string {value.value!r}"
    return f"a {type(value).__name__}"


# The three answers `_frame_return_status` gives, and why there are three and
# not two.  `_RETURN_FRAME` is the only one that compiles, and it is a property
# of the whole image: a caller reserves a block for this function's result and
# reads it out of that block afterwards, so the answer cannot be per-path.
_RETURN_FRAME = "frame"
_RETURN_WORD = "word"
_RETURN_UNSOUND = "unsound"


def _frame_return_status(fn, holders, by_name, returns_by_name):
    """`(status, struct_or_None, holder_or_None)` — what `fn` gives back.

    The decision the returned-frame convention turns on, and it is asked of
    every `return` in the body rather than of the first one, because the
    convention is a property of the FUNCTION: a caller has to decide, before
    the call, whether to reserve a block for the result, and it can only do
    that if the answer is the same on every path.

      * `_RETURN_FRAME` — every path returns a frame address, all of them of
        one struct, and the body cannot fall off the end.  The struct is the
        one the copy is laid out for, and the holder is the NAME it came back
        under, which `check_returned_frame_blob_writes` needs and which is None
        for `return f()` — the callee built that one, in the caller's block, so
        this function never held a name for it.
      * `_RETURN_WORD` — no path returns a frame address.  The ordinary case,
        and everything that compiled before the convention existed.
      * `_RETURN_UNSOUND` — a frame on one path and something else on another,
        or a frame and a fall-off-the-end, or two frames of different widths.
        The caller is PARKED a refusal for (`check_frame_return_shapes`)
        rather than refused here, for the reason every other frame refusal in
        this file is parked: `_prepare_functions` runs before the imports
        resolve, and a refusal raised from inside it is reported in place of
        the import diagnosis.

    A value is frame-valued in exactly two ways, and they are the two the
    holder analysis can recognise: a bare name that holds a frame address, and
    a call to a function already known to return one.  Anything else is a
    word — including a field read (`self.x` is a VALUE read out of the frame,
    not the frame) and a copy construction, which is a frame in THIS function's
    own scratch and is copied out by the same convention when it is returned.

    `returns_by_name` is the JOIN (`_returns_frame_by_name`), not the
    per-function table: the second case asks about a CALLEE, and a callee is
    reached by name. A name whose definitions disagree about whether they
    return a frame is absent from it, so the call is read as a word — which is
    the answer a caller can act on, since reserving a block for a result half
    the definitions do not return would size the caller's scratch for a copy
    that does not happen.
    """
    frames, words = [], []
    for node in M.iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.ReturnStmt) or node.value is None:
            continue
        value = node.value
        if isinstance(value, F.IdentExpr) and value.name in holders:
            cands = by_name.get(value.name) or []
            if cands:
                frames.append((cands, value.name))
                continue
        if isinstance(value, F.CallExpr) and isinstance(value.func, F.IdentExpr):
            st = returns_by_name.get(value.func.name)
            if st is not None:
                frames.append(([st], f"{value.func.name}()"))
                continue
        words.append(_expr_spelling(value))
    if not frames:
        return _RETURN_WORD, None, None
    if words:
        _park_frame_return(fn, M.frame_return_mixed_refusal(
            fn.name, _frame_return_spelling(frames[0][1]),
            f"the value {words[0]!r}", False))
        return _RETURN_UNSOUND, None, None
    if not M.returns_on_every_path(getattr(fn, "body", None)):
        _park_frame_return(fn, M.frame_return_mixed_refusal(
            fn.name, _frame_return_spelling(frames[0][1]), None, True))
        return _RETURN_UNSOUND, None, None
    # Every path returns a frame, so the only question left is WHICH frame, and
    # the answer has to be one struct: the copy is `n` slots wide and the
    # caller reserved a block sized for the struct this returns.
    shapes = []
    for cands, _spelling in frames:
        for st in cands:
            if st not in shapes:
                shapes.append(st)
    if len(shapes) > 1:
        rows = [(st.name, len(M.struct_frame_slots(st))) for st in shapes]
        _park_frame_return(fn, M.frame_return_candidates_refusal(fn.name, rows))
        return _RETURN_UNSOUND, None, None
    # The HOLDER is the returned NAME, and it is only a name for one of the two
    # shapes a frame return takes: a bare `return p` names it, and `return f()`
    # does not — the callee built that one, in the caller's block, and this
    # function never held a name for it.  None is the honest answer for the
    # second, and `check_returned_frame_blob_writes` reads None as "there is no
    # name here to have put a container into".
    holder = next((sp for _cands, sp in frames if "()" not in sp), None)
    return _RETURN_FRAME, shapes[0], holder


def _frame_return_spelling(value) -> str:
    """How a refusal names the value a `return` gives a frame address."""
    if isinstance(value, F.IdentExpr):
        return f"the frame in {value.name!r}"
    return f"the frame in {value!r}"


def _park_frame_return(fn, message) -> None:
    """Record a returned-frame refusal for `check_frame_return_shapes` to raise.

    Parked, never raised, for the reason the subscript escape is parked
    (`_defer_subscript_escape`): this pass runs inside `_prepare_functions`,
    which is BEFORE the imports resolve, so a refusal raised from here is
    reported in place of the import diagnosis — and a file that imports `os` is
    out of this backend's reach whatever its codegen says, which is the more
    useful of the two answers."""
    fn._frame_return_problems = list(
        getattr(fn, "_frame_return_problems", ())) + [message]


def check_frame_return_shapes(functions) -> None:
    """Raise the returned-frame refusals `_frame_receivers` parked.

    The fourth of the late frame checks and the same reason as the other three:
    a refusal raised before the imports resolve is reported in place of the
    import diagnosis.  A returned frame that is unsound on one path is a real
    finding and a late one — the import is the more fundamental fact, and this
    one only matters if the imports resolve."""
    for fn in functions or ():
        for message in (getattr(fn, "_frame_return_problems", ()) or ()):
            raise CodegenError(message)


def _bracket_callee_roots(body) -> set:
    """Node ids of the bare names a call's BRACKETED callee is written on.

    `f[x](...)` and `mod.f[x](...)`, keyed by the ROOT `IdentExpr` because
    `M.iter_nodes` has no parent and the root is the only node the name-placement
    walk below ever sees. One function for it because there are now two users —
    the construct refusal in `check_module_symbols` and the export refusal that
    follows it — and a set computed twice is a set that can disagree with
    itself, which is the failure mode the whole callee-exemption arrangement
    exists to prevent."""
    out = set()
    for c in M.iter_nodes(body):
        if not isinstance(c, F.CallExpr) \
                or not isinstance(c.func, F.SubscriptExpr):
            continue
        root = c.func
        while isinstance(root, (F.MemberExpr, F.SubscriptExpr)):
            root = root.obj
        if isinstance(root, F.IdentExpr):
            out.add(id(root))
    return out


def _defer_imported_frame_handoff(fn, callee, position, call, argument,
                                  by_name) -> None:
    """PARK a frame address reaching a callee compiled into ANOTHER module.

    Nothing is raised here, and the finding is not lost: `_prepare_functions`
    runs BEFORE `_resolve_imports`, so at this point no imported module has been
    compiled and no manifest exists to read a per-parameter frame-holder
    contract out of.  Raising here is what the pass used to do, and it is a
    refusal raised before the imports resolve — reported in place of the import
    diagnosis, which is the more fundamental fact about the file (67 files of
    this repository import a CPython host module, so for those the import is
    the answer and this one is a detail).

    So the site is recorded and `check_imported_frame_handoffs` decides it from
    the link line at the entry points.  The recorded tuple is everything the
    decision needs and nothing it cannot have:

      * `callee` and `position` — which parameter of which function, which is
        what the manifest's `frame_params` list is indexed by;
      * `spelling` — how the source writes the argument, so a refusal quotes
        the reader's own text rather than a re-rendering of it;
      * `structs` — the struct NAMES the argument is a frame of here, which is
        what the contract's names are compared against.  Empty is meaningful
        and is not the same as absent: it means this image cannot say what its
        own argument is, which is one of the four `why_absent` answers.

    Parking is unconditional — no shape is filtered here — because the decision
    needs the link line to make ANY of its four answers, and filtering before
    that would be filtering on a fact not yet in hand.
    """
    fn._imported_frame_handoffs = list(
        getattr(fn, "_imported_frame_handoffs", ()) or ()) + [(
            callee, position,
            [st.name for st in (by_name.get(argument.name) or [])],
            _call_spelling(call, argument, position, None))]


def check_imported_frame_handoffs(functions, link_line) -> None:
    """Raise the cross-image frame-address refusals `_check_frame_escapes` parked.

    The sixth of the late frame checks, and the same reason as the other five: a
    refusal raised before the imports resolve is reported in place of the import
    diagnosis.  What makes this one different from all of them is that it can
    also be an ANSWER — `model.resolve_frame_parameter_contract` returns
    `(True, None)` when the callee module's own manifest says the parameter is a
    frame holder of a struct this image also has, and then nothing is raised and
    the hand-off is followed.  That is the whole point of the contract: five of
    the six late checks can only report, and this one decides.

    `link_line` is `load_dylib_manifests`'s entries in LINK ORDER, which is the
    order that resolved the CALL — the same `setdefault`-first-wins precedence
    `dylib_syms` uses, so the contract consulted is the contract the emitted
    call binds.  Consulted through `dylib_export_lookup`, the one resolver both
    emitters use for a callee spelling, rather than by a bare-name lookup of our
    own: a dotted callee (`mod.f`, the spelling `import mod` binds) has to be
    answered from the module that owns the export, and a second resolution that
    could bind a different library's `f` is exactly the silently-wrong binding
    that module identity exists to prevent.

    The first refusal wins and the rest are not reported, which is the same rule
    every other check here follows: one finding is enough, and a reader who
    fixes it will find the next.
    """
    by_name, by_module, forwarded = M.dylib_export_tables(
        dylib_export_lists(link_line))
    for fn in functions or ():
        for callee, position, structs, spelling in (
                getattr(fn, "_imported_frame_handoffs", ()) or ()):
            entry = M.dylib_export_lookup(by_name, by_module, callee,
                                          forwarded)
            follow, refusal = M.resolve_frame_parameter_contract(
                [entry] if entry is not None else [], position, structs,
                spelling, callee)
            if not follow:
                raise CodegenError(refusal)


def _check_returned_frame_budget(functions, returns_frame, params_of) -> None:
    """Refuse a frame-returning callee with no argument register left.

    The hidden word is one more argument, and this path passes arguments in
    registers: arm64 has X0..X7 and x86-64 has six.  A callee that already
    takes the whole budget cannot be given the word, and the alternative is not
    a rough edge — `_emit_call` drops arguments past the budget for
    compile-only fidelity, so the word would be dropped and the callee would
    copy the frame into whatever the register held.  That is the silent wrong
    answer, and `model.returned_frame_convention_refusal` is the message for
    it.  Counted from the DECLARED parameter list rather than from a call site,
    because the callee is compiled once and every call site has to agree."""
    for fn in functions or ():
        if returns_frame.get(_fn_key(fn)) is None:
            continue
        names = params_of.get(_fn_key(fn)) or []
        n = len(M.incoming_args(fn))
        if n < len(names):
            n = len(names)
        message = M.returned_frame_convention_refusal(fn.name, n)
        if message:
            _park_frame_return(fn, message)


def _constructor_bindings(fn, framed, functions=()) -> dict:
    """`{name: [struct, …]}` for locals bound from a framed struct's constructor.

    A LIST per name, and that is the fix for a miscompile rather than a
    refinement: `x = A()` on one path and `x = B()` on another is one name with
    two frame layouts, and a dict that kept the last binding computed a slot
    index from that one alone — so on the `A` path `x.v` read `A`'s idea of
    where `v` is, which is generally not where `A` puts it. Every candidate is
    kept and `model.struct_frame_slot_candidates` decides whether they agree.

    The empty list is meaningful and not an oversight: a name bound from a
    constructor this path does NOT frame holds a plain word, and remembering
    that is what stops a later `x.f` from being read as a frame slot.

    **`model.call_lowers_as_framed_construction`, and that is the guard that
    makes this list agree with the emitters.**  Being in `framed` is necessary
    and not sufficient: a call to a name the emitters route to a type
    CONVERSION before they reach `_emit_struct_constructor` produces a plain
    word, and recording it as a construction binding would make the name a
    three-slot frame HOLDER anyway — so `x.f = v` becomes a store at
    `[word + 8·slot]`.  Measured, both architectures, from a green build:

    ```
    struct String:                        # three fields, exactly as the stdlib has it
        var _ptr_or_data: Pointer[UInt8]
        var _len_or_data: Int
        var _capacity_or_data: Int
        def size(self) -> Int: return self._len_or_data
    def main(n: Int) -> Int:
        var a = String()
        a._len_or_data = 5
        return a.size()
    ```

    → SIGBUS, exit 138, in read-only `__TEXT`, because the store's base is the
    address of an interned `""`.  With the guard the name is a plain word, and
    `a._len_or_data = 5` is `model.field_access_refusal` — a build error naming
    the field and the name, which is the answer this backend owes rather than a
    fault at an address it did not mean to touch.

    `functions` is the image's compiled function names, which the predicate reads
    for the one case where a name is both a function and a struct: the emitters
    skip the type-constructor interception for a name they compiled, so the call
    IS a construction there, and a pass that disagreed on that would refuse a
    program that builds."""
    out = {}
    for node in M.iter_nodes(fn.body):
        target = value = None
        if isinstance(node, F.VarDecl):
            target, value = node.name, node.value
        elif isinstance(node, F.AssignStmt) and isinstance(node.target,
                                                          F.IdentExpr):
            target, value = node.target.name, node.value
        if not target or not isinstance(value, F.CallExpr):
            continue
        if isinstance(value.func, F.IdentExpr) and value.func.name in framed:
            if not M.call_lowers_as_framed_construction(
                    value.func.name, framed, len(value.args or [])
                    + len(value.kwargs or []), functions):
                continue
            # De-duplicated, order kept: `x = A()` twice on two paths is ONE
            # candidate, and a refusal that printed "a A, A receiver" because it
            # counted a binding twice would be reporting the walk rather than
            # the program.
            got = out.setdefault(target, [])
            st = framed[value.func.name]
            if st not in got:
                got.append(st)
    return out


def _check_method_receiver_types(fn, holders, by_name, owners,
                                structs_by_name) -> None:
    """Refuse a method of one struct called on another struct's receiver.

    The hole is pre-existing and it is in the receiver, so it belongs to this
    pass rather than to the call rewriting that created it.  Method dispatch
    here is by NAME: `_rewrite_method_calls` turns `recv.m(x)` into
    `S_m(recv, x)` from the method name alone, because `recv.m(x)` carries no
    type.  That is fine while the receiver's type is not being used for
    anything, and it stops being fine the moment the receiver IS a frame: the
    callee writes `self.<field>` at `base + 8k` for ITS OWN struct's layout,
    so handing it a different struct's address has it write one object's field
    into another object's storage.

    Measured on a two-struct program, and it was a wrong answer rather than a
    crash:

        struct Helper:  a, b     |  fn go(self, v): self.a = v; return self.a
        struct Owner:   h, t     |  fn run(self):   return self.go(5)
        o.run(); o.h   ->  5, 5

    `self.a = v` inside `Helper_go` writes slot 0 of the frame it was handed,
    which is `Owner`'s `h`.  Python leaves `h` alone, so the program computes
    something the source never wrote — and worse, it does so silently, because
    the two structs' first fields are both integers and the write lands
    somewhere legal.

    The refusal is possible here and not at the rewrite because the holder set
    is only known once the fixpoint has run, which is after the rewrite.  So
    the check reads the REWRITTEN call: a `S_m` whose first argument is a
    holder of a struct that is not `S`.
    """
    for node in M.iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, F.CallExpr) or not node.args:
            continue
        if not isinstance(node.func, F.IdentExpr):
            continue
        # `owners` is keyed by the LIFTED name, which is what a rewritten call
        # spells, so this is the call the rewriting produced and not a guess.
        st = owners.get(node.func.name)
        if st is None or st.name not in structs_by_name:
            continue
        owner = st.name
        prefix = owner + "_"
        named = (owner, node.func.name[len(prefix):]
                 if node.func.name.startswith(prefix) else node.func.name)
        recv = node.args[0]
        if not isinstance(recv, F.IdentExpr) or recv.name not in holders:
            continue
        cands = [st.name for st in (by_name.get(recv.name) or [])]
        if not cands or owner in cands:
            continue
        raise CodegenError(
            f"{recv.name}.{named[1]}() is dispatched to {owner}.{named[1]}() by "
            f"method NAME, and the receiver is a "
            f"{', '.join(cands)} frame: {owner}.{named[1]}() writes its own "
            f"struct's fields at `base + 8k` for {owner}'s layout, so handing "
            f"it a {', '.join(cands)} address stores one struct's field in "
            f"another struct's storage. The program still runs and still "
            f"returns a number, which is why this cannot be left to fail "
            f"loudly later. `recv.m(x)` carries no type on this path, so the "
            f"two cannot be told apart except by refusing — give the method a "
            f"name of its own, or call it on a value of its own struct"
        )


def _stores_a_frame_returning_call(fn, returns_by_name) -> bool:
    """Whether `fn` puts a frame-returning call's address through a subscript.

    The one frame escape a function can commit while holding no frame name, and
    therefore the one the `if not hs` skip above would miss.  Deliberately
    narrow — a subscript STORE whose right-hand side is a call this image knows
    returns a frame — because the answer is only used to decide whether the
    escape check is worth running, and a broader predicate would run it on
    hundreds of functions that have nothing to say.
    """
    table = returns_by_name or {}
    if not table:
        return False
    for node in M.iter_nodes(getattr(fn, "body", None)):
        if not isinstance(node, (F.AssignStmt, F.AugAssignStmt)):
            continue
        if not isinstance(getattr(node, "target", None), F.SubscriptExpr):
            continue
        value = getattr(node, "value", None)
        if not isinstance(value, F.CallExpr):
            continue
        callee = M.call_callee_name(value.func)
        if callee and callee in table:
            return True
    return False


def _check_frame_escapes(fn, holders, by_name, param0, owners=None,
                         structs_by_name=None, created_here=frozenset(),
                         rets=None, all_holders=None, all_hstruct=None,
                         params_of=None, callee_defs=None,
                         imported=None, star_imports=(),
                         name_defs=None, returns_by_name=None) -> None:
    """Refuse every construct a frame ADDRESS may not take part in.

    A frame belongs to the function that created it and is reclaimed when that
    function returns, so a holder that outlives its creator — returned, put in
    a container, stored through a subscript or a module-level name, parked in
    another frame's field, or handed to something that wants a value — would
    be dereferenced after its bytes had been reused. The program would build,
    run, and produce a number the source never wrote, which is the outcome this
    backend exists to make impossible, so each of these is a refusal that names
    the construct.

    The one that was MISSING here, and the reason this function grew a case
    rather than a reason: parking a frame address in another object's field.
    `interpreter.scope = func_scope` looks like an ordinary assignment, and
    `func_scope`'s frame lives in the frame of whatever function built it — so
    the slot can outlive those bytes by as much as the object's own lifetime.
    Every other channel out of a function is a return or a container and both
    were already refused; this one was a hole, and it is the same hole one
    level down, which is the direction this whole design leaks in.

    `owners` and `structs_by_name` are what let the CALL half tell a callee it
    can bind from one it cannot, which is the question the old single refusal
    answered wrongly for 23 of this repository's 25 hand-off sites. Both are
    optional so the dylib path, which has no imported structs and so has no
    cross-module callee to recognise, can call this with neither.

    `created_here` is the set of holder names this function BUILT; a holder
    outside it arrived from a caller, and the return refusal says so rather than
    naming this function as the creator.

    `returns_by_name` is the fixpoint's by-name table of the callees that hand
    back a frame (`_returns_frame_by_name`), and it is what lets the SUBSCRIPT
    escape recognise `xs[1] = make(5)`.  That value is not a name, so the
    holder walk has nothing to look up and the check used to see an ordinary
    assignment — and the emitter drops the store, so the program built, ran and
    exited 0 where the source says 5.  It is the same escape as `q[0] = r`, one
    hop further out: the frame this call hands back lives in the caller's
    scratch, which is longer-lived than a local's, and the list's element is
    longer still.

    `all_holders`/`all_hstruct`/`params_of` are the whole image's tables, and
    they are what the CALL half is decided from.  A parameter is a frame holder
    or it is not, and that is a property of every call site at once — see
    `model.frame_holder_disagreement_refusal` for the measured program that
    says what happens when only one of them agrees.

    `imported` and `star_imports` are this module's imported-NAME tables
    (`formal.imports`'s `imported_bound_names` and `star_imported_modules`),
    passed in for the same reason `params_of` is: a callee this image does not
    compile is refused for one of five different reasons, and which one depends
    on facts that live outside this function."""
    known = set(param0)
    # `<Struct>_<method>` for every method of every struct in hand, MINUS the
    # ones this module compiles.  The difference is exactly the set of callees
    # that live in an IMPORTED module: their bodies are in the dylib that
    # module compiles into, and they are exported under the module-qualified
    # spelling `dylib_syms` maps them to.  A frame address is exactly what such
    # a callee wants — it is a method of the receiver's own struct, so it was
    # compiled against the very field list in hand, and `base + 8k` means the
    # same thing on both sides of the boundary.
    cross_module = set(owners or ()) - known
    struct_names = structs_by_name or {}
    # The dylib path calls this with none of the three, and a missing table
    # must not turn into a `KeyError` in the middle of a diagnostic: without
    # them the call half can still refuse a variadic or an unknown callee, and
    # the holder-agreement check simply has nothing to compare against.
    all_holders = all_holders if all_holders is not None else {}
    all_hstruct = all_hstruct if all_hstruct is not None else {}
    params_of = params_of if params_of is not None else {}
    # `name_defs` is `{name: [FunctionDef, …]}`. `all_holders` and `params_of`
    # are keyed by FUNCTION IDENTITY (`_fn_key`), and the reads of them below
    # ask about a NAME, so both go through this table rather than indexing by
    # name — see `_by_name_holder` for why a name with two definitions is not a
    # name with one answer.
    name_defs = name_defs if name_defs is not None else {}
    # The membership question — "does any definition of this callee take a
    # frame?" — is a UNION over the name's definitions, which is the honest
    # reading of "any": a call site that named an overloaded function could have
    # reached any of them, so every holder any of them has is one this call site
    # might have handed a frame to. Narrowing it to one definition is what made
    # `reversed`'s `_DictEntryIter` overload's receiver look like `List`'s.
    holders_by_name = {}
    for _name, _defs in name_defs.items():
        _u = set()
        for _fn in _defs:
            _u.update(all_holders.get(_fn_key(_fn)) or ())
        if _u:
            holders_by_name[_name] = _u
    # …and the parameter-list half of the same question, which is NOT a union:
    # a name's definitions spell their parameters differently (`reversed`'s do,
    # eight ways), so there is no list to merge. It answers for a name with ONE
    # definition, which is what `_frame_argument_slots` needs — the positions it
    # walks are that definition's.
    def _by_name_params(name):
        _defs = name_defs.get(name) or ()
        return params_of.get(_fn_key(_defs[0])) if len(_defs) == 1 else None

    def _names(node):
        return [st.name for st in (by_name.get(node.name) or [])] \
            if isinstance(node, F.IdentExpr) else []

    # Bracket lists that are TYPE ARGUMENT lists, collected before the walk and
    # keyed by the index node's identity — `M.iter_nodes` has no parent, so this
    # is the only way a child can be named again, and `struct_constructor_sites`
    # already keys on `id` for the same reason.
    #
    # A TYPE ARGUMENT LIST IS NOT A CONTAINER, and the branch below could not
    # tell the two apart: `Pointer[Deque[T], origin_of(self)]` and
    # `[s, 1]` both arrive as a `TupleExpr`, and both were refused with the
    # sentence "is stored in a container, which has no layout for a frame
    # address" — which is FALSE about the first, and false in the way that
    # costs the most, because it tells the reader their program has a frame
    # that outlives its creator when it has no such frame at all. Measured on
    # the 2026-09-30 sweep: 4 stdlib files
    # (`std/builtin/tuple.mojo`, `std/collections/{deque,linked_list,set}.mojo`),
    # each of which is refused for a store that does not happen.
    #
    # Skipping is the safe direction and the WHOLE of it is a skip: the
    # subscript is not thereby allowed through — `model.multi_index_kind`
    # answers `MULTI_INDEX_COMPTIME_PARAMS` for these bases and the construct is
    # refused by name, with a sentence about explicit parameters that is true.
    # What is not done here is inventing a decision:
    # `subscript_index_is_a_comptime_parameter_list` answers only for a base
    # this image can classify, so a bracket list over a name it cannot — a
    # dotted `h.tag[…]`, an unknown name, a local — takes the refusal below
    # exactly as before, and that limit is written down in
    # `bugs/FORMAL_dotted_base_bracket_list_is_not_classified.md`. Every escape
    # the branch is really for (`d[s, 1] = 5`, `var k = l[s, 1]`, `[s, 1]`) has a
    # base that is a dict or a list, and no type name is either.
    type_index_ids = {
        id(sub.index)
        for sub in M.iter_nodes(getattr(fn, "body", None))
        if M.subscript_index_is_a_comptime_parameter_list(
            sub, structs_by_name, callee_defs)
    }

    for node in M.iter_nodes(fn.body):
        if isinstance(node, F.ReturnStmt) and node.value is not None:
            # `return <frame>` used to be refused here, and the refusal was
            # CORRECT: the block belongs to the function that reserved it and
            # that function's scratch dies with it, so the address the caller
            # would dereference names reclaimed stack. It is not the answer
            # any more, because the answer exists: `_frame_receivers` has
            # decided whether this function returns a frame, and when it does
            # the CONVENTION puts the copy in a block in the CALLER's own
            # scratch (`model.struct_returned_frame_sites`) with the caller's
            # block address passed as one hidden trailing word. So the emitter
            # copies and there is nothing left for this pass to object to.
            #
            # `_frame_return_status` is three-valued and the third value is why
            # this branch is a branch at all: `_RETURN_UNSOUND` means the
            # function returns a frame on one path and not on another, which
            # is a real refusal — parked for
            # `check_frame_return_shapes` to raise from the entry points,
            # because a refusal raised from inside `_prepare_functions` is
            # reported in place of the import diagnosis. It is NOT this
            # message: the mechanism operating there is the two return
            # conventions, not a frame escaping a frame.
            #
            # `owners` says which case the received frame is, and the message
            # for a function that really does return a word still says so,
            # because "returned from the function that created it" is false for
            # a frame that arrived as a PARAMETER and sends the reader to the
            # wrong function looking for it.
            owner = (owners or {}).get(fn.name)
            if getattr(fn, "_frame_return_status", _RETURN_WORD) != _RETURN_WORD:
                continue
            if isinstance(node.value, F.IdentExpr) \
                    and node.value.name in holders:
                raise CodegenError(M.frame_return_refusal(
                    owner.name if owner is not None else None,
                    node.value.name not in created_here,
                    _names(node.value)))
            _refuse_holder_use(fn, node.value, holders, by_name,
                               "is returned from the function that created it")
        elif isinstance(node, (F.ListExpr, F.TupleExpr, F.DictExpr)):
            if id(node) in type_index_ids:
                # A TYPE APPLICATION, not a store — the skip is justified above
                # and the subscript is refused by name further in.
                continue
            for el in _container_values(node):
                _refuse_holder_use(fn, el, holders, by_name,
                                   "is stored in a container, which has no "
                                   "layout for a frame address")
        elif isinstance(node, F.AssignStmt) \
                and isinstance(node.target, F.MemberExpr) \
                and isinstance(node.value, F.IdentExpr):
            _refuse_holder_use(
                fn, node.value, holders, by_name,
                f"is stored in the field {_member_chain(node.target)!r}, so it "
                f"outlives the frame it names by however long that object "
                f"lives: the slot belongs to the function that created THAT "
                f"frame, and nothing here can say the two lifetimes agree")
        elif isinstance(node, (F.AssignStmt, F.AugAssignStmt)) \
                and isinstance(getattr(node, "target", None), F.SubscriptExpr):
            # A SUBSCRIPT store, `q[0] = r`.  It reads as an ordinary
            # assignment and it is the same hole as the container literal one
            # level along: the list's element is a heap cell, so the frame
            # address outlives the frame by however long the list lives.
            #
            # Measured before this branch existed, on both architectures, with
            # nothing lifted: `var q = [1, 2, 3]; q[0] = r; return q[0].a`
            # builds, runs, and returns **0** where the source says 7 — a
            # wrong answer, silently, with the program exiting 0.
            #
            # RECORDED, NOT RAISED, and that is the reason this branch is not
            # shaped like the four above it.  A refusal raised from
            # `_prepare_functions` preempts the import diagnosis, which is the
            # defect `check_frame_field_blob_premises` and
            # `check_construction_shapes` were moved out to fix: 14 files of
            # this repository that import a host module were being reported as
            # codegen gaps because of it.  Measured here, the same way: with
            # this branch raising from `_prepare_functions`, `mojo/middle/
            # closures.py` went from `not-answerable/host-import` — "imports
            # 'fire_compiler', which … imports 're', which is a host module" —
            # to a `codegen` finding about a subscript.  So it is collected
            # here and raised by `check_frame_subscript_escapes`, which the
            # entry points call beside the other two.
            _defer_subscript_escape(
                fn, getattr(node, "value", None), holders, by_name,
                _subscript_chain(node.target), returns_by_name)
        elif isinstance(node, F.CallExpr):
            callee = M.call_callee_name(node.func)
            # A struct CONSTRUCTOR carries NO escape to check, and the reason is
            # worth stating because it is the whole reason the other two shapes
            # are representable.  `S(...)`'s block belongs to the function the
            # site is in, and this object cannot leave that activation — every
            # channel out is refused above — so a word read into one of its
            # slots came from a live local of this function or of an ancestor
            # of it and outlives every read of the slot.  That is exactly what
            # the ASSIGNMENT branch above cannot say: there `o` may be an
            # object an ANCESTOR built, so the slot outlives `i`'s creator.
            #
            # It used to be a branch here, refusing `R(r)` as "a copy
            # construction", and the refusal was a missing lowering.  The
            # lowering exists now, so the question is not WHETHER to refuse but
            # WHICH shape this is — and that is
            # `check_construction_shapes`, which is LATER, next to
            # `check_frame_field_blob_premises`, for the same reason that one
            # is: a refusal raised from `_prepare_functions` preempts the
            # import diagnosis, and 14 files of this repository that import a
            # host module were being reported as codegen gaps because of it.
            #
            # Skipping the whole argument loop rather than only the frame case
            # also matters for ORDER: `S(a, r)` has a frame address in a
            # non-first position, which the loop below would refuse as
            # "a position whose meaning this path cannot see" — a sentence
            # about a construct that is now a positional construction and
            # perfectly representable.
            if callee in struct_names \
                    and M.type_constructor_kind(callee) is None:
                continue
            # A METHOD call's own name, for the message: `recv.m(x)` that the
            # rewriting did not lift has no callee name to report, and "a call
            # this path does not recognise" sends the reader looking for a
            # missing function rather than at the method the source names.
            method = (_member_chain(node.func)
                      if isinstance(node.func, F.MemberExpr) else None)
            # ONE loop over the arguments, and what each one is decided BY is
            # the CALLEE, not its position.  The old loop asked the position
            # first and used it as the catch-all, which put three unrelated
            # things under one sentence and made the commonest of them
            # unreachable: a variadic C entry point, a callee with no
            # definition in hand, and a method call on a value receiver were
            # each reported as "a position whose meaning this path cannot
            # see", and so was a parameter that is a perfectly good holder in
            # any position but the first.
            #
            # The order below is the order the question is actually decided
            # in, and the first three are the ones that do not depend on the
            # position at all:
            #
            #   0. there is no callee NAME at all (a method call the
            #      rewriting did not lift, or a callee that is not a
            #      name)                                   -> case 3, opaque;
            #   1. the callee wants a VALUE, or is variadic  -> case 2;
            #   2. the callee is not in this image            -> case 3;
            #   3. the callee's parameter list is in hand and the
            #      parameter IS a holder                     -> followed;
            #   4. …and if it is NOT                          -> the
            #      disagreement, which is a fact about the program.
            #
            # 0 is FIRST and the ordering is load-bearing rather than
            # tidy: `callee` is None for a method call, and None is not in
            # `known` and not in `all_holders` either, so leaving it to step 2
            # printed the "no definition in hand" sentence with no name in it
            # — a refusal about a function that does not exist, for a method
            # call the source plainly writes.  Measured: `mk().take(r)` came
            # back as "a R receiver is passed to (), which is a name with no
            # definition in hand".
            for i, a, kwname in _frame_argument_slots(
                    node, _by_name_params(callee) or () if callee in all_holders
                    else ()):
                if callee is None:
                    # 0. A callee this pass cannot NAME.  Two shapes, and they
                    #    are two different sentences, which is the fix: a
                    #    method call on a value receiver really is dispatched
                    #    by NAME and really has no parameter list in hand, while
                    #    a callee that is not a member expression at all
                    #    (`mod.f[T](x)`, a computed callee) has no NAME to
                    #    dispatch on.  Saying the method thing about the second
                    #    is a refusal whose stated reason is entirely false, and
                    #    it is what this branch used to do for BOTH — measured
                    #    on the corpus, six files whose terminal finding this
                    #    message produced had a comptime specialization at the
                    #    callee and not one of them contains a method call.
                    #    A comptime specialization of a bare name no longer
                    #    arrives here at all: `model.call_callee_name` answers
                    #    `f` for `f[T](x)` and the argument is decided by the
                    #    ordinary parameter list.
                    _refuse_holder_use(
                        fn, a, holders, by_name, "",
                        M.frame_opaque_position_refusal(
                            where_the=method or "the call", callee=None,
                            position=i, total=len(node.args or []),
                            struct_names=_names(a), method=method,
                            callee_shape=None if method
                            else _expr_spelling(node.func),
                            why="a method call on a value receiver is "
                                "dispatched by NAME, so `recv.m(x)` carries no "
                                "type and the parameter list this argument "
                                "lands in belongs to a declaration this walk "
                                "has not read" if method else
                                "this call's callee names no function this "
                                "pass has a parameter list for"))
                    continue
                if callee == "len" and isinstance(a, F.IdentExpr) \
                        and a.name in holders \
                        and len(node.args or []) == 1 and not (node.kwargs or []):
                    # `len` first, and before `_callee_wants_a_value`, because
                    # it is the one value-only callee whose argument is exactly
                    # what it wants.
                    #
                    # A frame address IS a length's receiver: `len(h)` on a
                    # `Heap` frame is `h.__len__()`, a method of the receiver's
                    # OWN struct, which is the one hand-off a frame address
                    # makes — the by-reference design settles its lifetime on
                    # the same evidence a method receiver uses.
                    # `_rewrite_len_on_frame_receivers` has therefore already
                    # turned this into `Heap___len__(h)` whenever the struct
                    # declares one, and reaching `len` here means it does not.
                    #
                    # So the refusal is `model.frame_len_refusal` and NOT
                    # `frame_receiver_escape_refusal`'s "a wrong category of
                    # argument" sentence.  That sentence is true about the
                    # CATEGORY — a frame has no header, and a count-field read
                    # of one is the struct's first field — and it answers a
                    # question that is not what stops this program, which is why
                    # a reader who follows its advice ("give it a field,
                    # `len(self.n)`") is sent to change a program that is
                    # already correct whenever the struct HAS a `__len__`.
                    #
                    # THE ARITY IS NOT THIS BRANCH'S BUSINESS, and the condition
                    # above says so: it is the rewrite's own condition, one
                    # positional argument and no keywords.  `len(h, x)` is a
                    # shape the rewrite does not take, and the fault there is
                    # the ARITY, which the emitter has its own message for.
                    # Claiming the operand is not a bare frame name would be
                    # false in its first clause — it is the bare name `h` — and
                    # measured, `return len(b, b)` on a `Bag` frame reaches it.
                    # Falling through leaves those programs on
                    # `frame_receiver_escape_refusal`, which is what refused
                    # them before this branch existed.
                    _refuse_holder_use(
                        fn, a, holders, by_name, "",
                        M.frame_len_refusal(_expr_spelling(a), _names(a)))
                    continue
                # 1. A value-taking callee, in ANY position.  This is the
                #    check that was unreachable, because the old loop only
                #    asked it at position 0 and a `printf` in any other
                #    position got the position sentence instead.
                if _callee_wants_a_value(callee):
                    # The model's own classification is the WHOLE message here,
                    # with no fallback arm.  An `or <something else>` was in
                    # this spot and was dead as well as dangerous: a predicate
                    # that asks "does this callee want a value" and a function
                    # that answers it can only ever agree, so the second call
                    # could never be reached — and had it been, it would have
                    # printed a sentence about a mechanism that is not
                    # operating.  `frame_receiver_escape_refusal`'s
                    # `FRAME_C_VALUE_CALLS` branch already IS the variadic
                    # message, and a second copy of it here is how the two would
                    # come apart.
                    _refuse_holder_use(
                        fn, a, holders, by_name, "",
                        M.frame_receiver_escape_refusal(callee, _names(a)))
                    continue
                if callee in cross_module:
                    # A method of an imported struct, called on a frame of a
                    # struct.  `_check_method_receiver_types` has already
                    # refused the case where the two structs disagree, so what
                    # is left is the hand-off the by-reference design exists
                    # for, and it needs nothing special: see
                    # `_method_exports`, which is the other half — the export
                    # that makes the symbol bindable at all.
                    #
# …but only at the RECEIVER.  Further along, the argument
                    # lands on one of that method's own parameters, and whether
                    # the imported module's analysis made it a frame holder is a
                    # fact about THAT module's compilation — which is now
                    # PUBLISHED, in that module's manifest, by the same
                    # `_export_frame_contract` the free-function case reads.  So
                    # this is no longer the opaque case: it is parked and decided
                    # from the contract, by the same late check and for the same
                    # reason — `_prepare_functions` runs before the imports
                    # resolve, so a refusal raised here is reported in place of
                    # the import diagnosis.
                    if i == 0:
                        continue
                    if isinstance(a, F.IdentExpr) and a.name in holders:
                        _defer_imported_frame_handoff(
                            fn, callee, i, node, a, by_name)
                        continue
                    _refuse_holder_use(
                        fn, a, holders, by_name, "",
                        M.frame_opaque_position_refusal(
                            f"{callee}()", callee, i, len(node.args or []),
                            _names(a), method, kwname,
                            f"{callee}() is compiled into "
                            f"{struct_names and 'an imported module' or 'another image'}"
                            f", and whether ITS analysis made that parameter a "
                            f"frame holder is a fact about that module's "
                            f"compilation, which this pass has not read"))
                    continue
                if callee not in known and callee not in holders_by_name:
                    # 2. Not in this image, whatever position.  Saying so is
                    #    true at every position; the old loop only said it at
                    #    position 0 and let the position sentence cover the
                    #    rest.
                    #
                    # `frame_receiver_escape_refusal`'s fifth case, with the
                    # three facts that pick between its five sentences.  All
                    # three are the CALLER's: `imported` is
                    # `formal.imports.imported_bound_names`' table for this
                    # module and `star_imports` its
                    # `star_imports`, both read from the import
                    # statements because `_resolve_imports` has not run yet,
                    # and `fn.comptime_params` is this function's own `def[…]`.
                    # Without them `_b64encode` (imported, and therefore
                    # compiled — into another module's library) and `ElementFn`
                    # (a compile-time parameter, which no compilation will ever
                    # define until a call site instantiates it) were both
                    # reported with the one sentence that fits neither, and a
                    # `from lib import *` callee was reported as a name nothing
                    # binds when `lib`'s export set may bind it.
                    #
                    # `owners` — the imported-METHOD table the `cross_module`
                    # branch above is built from — is deliberately not the
                    # source: it holds lifted `<Struct>_<method>` spellings,
                    # which is what a rewritten `recv.m(x)` becomes, and a bare
                    # imported FUNCTION is not one of them.  That gap is the
                    # half of the cross-module question the method case already
                    # answers for the RECEIVER.
                    comptime_params = getattr(fn, "comptime_params", None) or ()
                    # The classifier is asked TWICE, and the comparison is the
                    # decision.  Once with the cross-image facts and once
                    # without: the arms that decide about the ARGUMENT — a
                    # variadic builtin, a C entry point, a value-only callee, a
                    # type constructor — do not read those facts, so both calls
                    # answer identically and the answer is the whole of what
                    # stops this program.  Only when the two DIFFER is the
                    # fifth case the one that answered, and that is the arm the
                    # link line's contract now decides.
                    #
                    # Asking the classifier for the fifth case DIRECTLY is the
                    # mistake this avoids, and it was made here first: it skips
                    # every arm above it, so `print(p)` — which is compiled, and
                    # variadic, and wants a value — was reported as "a name with
                    # no definition in hand", false of it and a reader sent
                    # looking for a missing export of a builtin.  Two calls
                    # rather than a second table of the classifier's own order,
                    # because a hand-kept copy of that order is a second
                    # recognition of it and the two would come apart.
                    names = _names(a)
                    _cpt = fn.name if callee in comptime_params else None
                    reason = M.frame_receiver_escape_refusal(
                        callee, names,
                        imported_from=(imported or {}).get(callee),
                        comptime_param_of=_cpt,
                        star_imported_from=star_imports[0] if star_imports
                        else None)
                    if reason is None:
                        continue
                    # The SAME call with the two IMPORT facts removed and
                    # everything else held fixed — `comptime_param_of` in both,
                    # because a compile-time parameter is decided without them
                    # and must not be mistaken for a cross-image arm.  When the
                    # two agree, the arms that decide about the ARGUMENT
                    # answered and the answer is the whole of what stops this
                    # program.
                    plain = M.frame_receiver_escape_refusal(
                        callee, names, comptime_param_of=_cpt)
                    if (plain is not None and plain == reason) \
                            or not isinstance(a, F.IdentExpr) \
                            or a.name not in holders:
                        _refuse_holder_use(fn, a, holders, by_name, "", reason)
                        continue
                    # The fifth case, and the callee is bound by a `from … import
                    # …` or a `from … import *` in THIS file — so the callee is
                    # compiled into another module, which published a
                    # per-parameter frame-holder contract in its manifest
                    # (`_export_frame_contract`).  The decision needs that
                    # manifest, and `_prepare_functions` runs BEFORE
                    # `_resolve_imports` compiles the modules, so the site is
                    # PARKED here and `check_imported_frame_handoffs` decides it
                    # from the link line at the entry points — the same
                    # park-then-decide-late shape `_defer_subscript_escape`
                    # uses, and for the same measured reason: a refusal raised
                    # from here is reported in place of the import diagnosis,
                    # which is the more fundamental fact about the file.
                    _defer_imported_frame_handoff(fn, callee, i, node, a,
                                                  by_name)
                    continue
                # 4. A function of this image, and its parameter list is in
                #    hand.  Either the parameter IS a frame holder — which is
                #    the case the fixpoint now follows in EVERY position, and
                #    nothing to refuse — or it is not, and the argument is a
                #    frame address going into a slot the callee reads as a
                #    plain value.  That last one is the disagreement, and it
                #    is a whole-image fact rather than a local one, so it is
                #    asked by `_check_holder_agreements` below rather than
                #    here: the call site that has to be caught can be in a
                #    function that holds no frame at all, and those are skipped
                #    by the `if not hs` guard above.


def _container_values(node) -> list:
    """The values a container literal holds, in source order.

    A dict's are its VALUES, not its keys: `{p: 1}` parks the frame address just
    as `[p]` does, and reading the keys instead would miss exactly the case
    this exists to catch."""
    if isinstance(node, F.DictExpr):
        return [v for _k, v in (node.pairs or [])]
    return list(getattr(node, "elements", None) or [])


def _refuse_holder_use(fn, node, holders, by_name, why, reason=None) -> None:
    """Raise if `node` IS a frame address rather than something read out of one.

    Deliberately only a bare name. `h.x` is a 64-bit FIELD, not an address, and
    passing it onward is as ordinary as passing any other word; what has no
    representation here is the address itself, so a chain with a `.member` in
    it is not this function's business.

    `reason` is the whole message when the caller has one — which is how the
    hand-off cases get to say what is actually wrong with the hand-off instead
    of restating the rule they are an instance of. See
    `model.frame_receiver_escape_refusal`, which is where the difference
    between "the callee wants a value" and "the callee is not in this image"
    is drawn; a single message covering both named a cause that was not
    operating for the larger of the two groups."""
    if not isinstance(node, F.IdentExpr) or node.name not in holders:
        return
    if reason is not None:
        raise CodegenError(reason)
    cands = by_name.get(node.name) or []
    name = ", ".join(st.name for st in cands) if cands else node.name
    raise CodegenError(
        f"a {name} receiver {why} on this path: the receiver of a "
        f"multi-field struct is the ADDRESS of a frame of 8-byte slots that "
        f"belongs to the function which created it, so it can only be read, "
        f"written, copied, or passed as a method's receiver. "
        f"bugs/FORMAL_wide_receiver_by_reference.md records the design and "
        f"what is still open about it")


def _one_word_field_map(fn, structs_by_name: dict, owner=None) -> dict:
    """{local name: its field name} for locals holding a one-word struct.

    Found from the binding, not inferred: a local initialised from a one-word
    struct's constructor holds that struct's only field, and nothing else on
    this path can produce such a value.

    A PARAMETER declared as a one-field struct joins them, from the
    declaration rather than from a binding, because the declaration is the same
    evidence for a parameter that the constructor call is for a local: the
    receiver of a one-field struct IS its field, so a word the caller passed
    for an `S` is that field.  `owner` is what a bare `Self` reduces to, and it
    is the struct the caller's own `self` rewrite below already handles — so
    the two never both fire for one name and cannot disagree about which field
    a name means.
    """
    mapping = {}
    for node in M.iter_nodes(fn.body):
        target = value = None
        if isinstance(node, F.VarDecl):
            target, value = node.name, node.value
        elif isinstance(node, F.AssignStmt) and isinstance(node.target,
                                                           F.IdentExpr):
            target, value = node.target.name, node.value
        if not target or not isinstance(value, F.CallExpr):
            continue
        if not isinstance(value.func, F.IdentExpr):
            continue
        st = structs_by_name.get(value.func.name)
        if st is not None and M.struct_is_one_field(st):
            mapping[target] = _sole_field_name(st)
    for pname, pst in M.parameter_declared_structs(
            fn, structs_by_name, owner).items():
        if pname in mapping or not M.struct_is_one_field(pst):
            continue
        mapping[pname] = _sole_field_name(pst)
    return mapping


def _sole_field_name(st) -> str:
    """The name of a struct's only field — the word the whole struct is.

    Refused rather than guessed when that field binds no name. This value is
    used to rewrite `<local>.<field>` to the local itself, so a wrong name here
    does not fail a build, it silently computes on the wrong storage — worse
    than the crash this replaced, since a formal backend's whole value is that
    its answer can be trusted.

    The name comes from the DERIVED field set (formal.model), which is what
    makes this work for a class that declares nothing and assigns its one field
    in `__init__` — the shape most of this repo's own source uses, and the one
    a reader of `StructDef.fields` would have measured as an empty struct."""
    name = M.struct_sole_field_name(st)
    if name is None:
        raise CodegenError(
            f"{st.name} has exactly one field but that field binds no name, "
            f"so there is nothing for its one word to be called; a field must "
            f"be declared as `name: Type` or `name = value` to be "
            f"representable on this path")
    return name


def _rewrite_self_fields(node, mapping: dict):
    """`x.f` -> `x` where `mapping[x] == f`, returning any replacement node.

    This is what makes a one-word struct's field and its receiver the SAME
    storage. Without it the two are separate: `c.n = x` wrote a `c.n` slot
    while the method call passed `c`, so the method read the constructor's
    zero and every accessor returned a constant — a program that builds, runs,
    and computes the wrong answer. Rewriting the access is what keeps the
    field and the value identical, rather than leaving the codegen to
    reconcile two spellings of one word."""
    if isinstance(node, list):
        for i, x in enumerate(node):
            node[i] = _rewrite_self_fields(x, mapping)
        return node
    if (isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr)
            and mapping.get(node.obj.name) == node.member):
        return F.IdentExpr(name=node.obj.name)
    for name in getattr(node, "__dataclass_fields__", {}):
        setattr(node, name, _rewrite_self_fields(getattr(node, name), mapping))
    return node


def _constant_read_sites(fn, structs_by_name: dict, owner=None,
                         receiver_structs: dict = None) -> dict:
    """{access path: (struct, kind)} for every read of a class-level constant.

    `fn` and not a statement list, because the evidence below is a property of
    the FUNCTION: what it binds, and which struct it is a method of. Both call
    sites have the function and neither has anything else.

    `kind` is `"constant"` for a class-level assignment and `"comptime"` for a
    `comptime NAME = …` binding, and the two are named differently in a refusal
    because they are different constructs: one is a value the class body
    assigned, the other is a compile-time binding with no word behind it at all
    (`model.struct_comptime_aliases`). Both are materialized at the read by the
    same rewrite, because both are one value for every instance.

    Four spellings, each with the evidence that makes the name the CLASS's own
    value rather than a same-named field of something else:

      * `S.NAME`, where `S` is the struct's own name. Unambiguous — provided the
        function does not itself bind a local called `S`, which is checked
        against the same bound-name set the module-constant substitution uses,
        because a local of that name is what the source means there.
      * `self.NAME` (and `this`/`cls`, or whatever this struct's methods spell
        their receiver — `model.struct_receivers`) and `Self.NAME`, inside a
        method of `S`. The receiver is an `S` or a SUBCLASS of it, which is why
        anything this unit derives from `S` disqualifies it: see
        `model.struct_is_derived_from`.
      * `x.NAME` where `x` is a local every binding of which constructs `S`
        (`_constant_constructor_bindings`), or a parameter declared `x: S`
        (`model.parameter_declared_structs` — the same declaration evidence the
        frame-slot check uses for `other.start` in `Slice.__eq__`).

    The receiver spellings are deliberately NOT offered for a class-level
    ASSIGNMENT. `self.A` with `A = 3` stays a field, because that is what
    `struct_default_word` puts the 3 behind and what makes the spelling correct
    for a one-field struct (the note above `model.struct_class_constants` has the
    argument). A `comptime` binding is the case they are for: it has no word to
    put anything behind, so `self.rank` in a struct declaring `comptime rank: Int
    = 3` reads the 3 — in the language, and in `myinterpreter`'s
    `_eval_member_of`.

    A read through any OTHER object is not here and still cannot be: without
    types, `o.NAME` might be an instance of `S` (a constant) or of some other
    struct with a real field of the same name (a field), and guessing is the
    error this whole rule is arranged to avoid."""
    sites = {}
    if not structs_by_name:
        return sites
    bound = _names_bound_in(fn)
    for st in structs_by_name.values():
        if st.name in bound:
            continue
        for name, _default in M.struct_class_constants(st):
            sites[f"{st.name}.{name}"] = (
                st, "comptime" if name in M.struct_comptime_aliases(st)
                else "constant")
    def publish(holder, st, comptime_only):
        """Every read of `st`'s class-level values through `holder`.

        `comptime_only` is the receiver case and the reason the two are not one
        loop: `self.A` for a class-level ASSIGNMENT stays a field (see the
        docstring), while `self.rank` for a `comptime` binding is the binding.

        A subclass REDECLARING a binding withholds exactly that one read, and the
        site is recorded as `overridden` rather than dropped so the refusal can
        say why — see `_overridden_comptime_refusal`. The two shapes are kept
        apart on purpose: `Child(Base)` that overrides `rank` makes `self.rank`
        inside a method `Base` declares unanswerable, and a `Child(Base)` that
        inherits it changes nothing, so disqualifying the whole struct would
        refuse a program whose answer is exact."""
        shadowed = _overridden_comptime_names(structs_by_name, st)
        for name, _default in M.struct_class_constants(st):
            kind = _constant_kind(st, name)
            if comptime_only and kind != "comptime":
                continue
            if holder != st.name and name in shadowed:
                sites[f"{holder}.{name}"] = (st, "overridden")
                continue
            sites[f"{holder}.{name}"] = (st, kind)

    # A LOCAL (or a parameter) bound to `S` may read ANY of `S`'s class-level
    # values: the base is the value the call site or the declaration says it is,
    # and nothing about `x.A` is a field read when `A` is the class's own value.
    locals_ = dict(_constant_constructor_bindings(fn, structs_by_name)[0])
    for local, st in M.parameter_declared_structs(
            fn, structs_by_name, owner).items():
        locals_.setdefault(local, st)
    for local, st in locals_.items():
        publish(local, st, comptime_only=False)
    # The RECEIVER, and `Self` beside it. Only a `comptime` binding is readable
    # through these; see the docstring for why the assignment case is not.
    if owner is not None:
        for receiver in sorted(M.struct_receivers(owner)):
            publish(receiver, owner, comptime_only=True)
        shadowed = _overridden_comptime_names(structs_by_name, owner)
        for name in M.struct_comptime_aliases(owner):
            sites[f"Self.{name}"] = (
                (owner, "overridden") if name in shadowed
                else (owner, "comptime"))
    for holder, st in sorted((receiver_structs or {}).items()):
        if holder in locals_ or holder == st.name:
            continue
        # A holder is a VALUE, so it reads a class-level ASSIGNMENT as well as
        # a `comptime` one — the same reasoning as a local above, and the reason
        # this is `comptime_only=False`, while the receiver is the other way
        # round.
        publish(holder, st, comptime_only=False)
    return sites

def _binding_names(node) -> list:
    """The names one node binds, as strings — every shape, not just `x = …`.

    `_write_targets` is the enumeration (declaration, assignment, augmented
    assignment, `for`, `with … as`, tuple target, comprehension target,
    `except … as`), and this adds the two the census below needs and
    `_write_targets` has no opinion about: the name a `VarDecl` introduces and
    the parameters of a NESTED `def`/`lambda`, which shadow an outer local of
    the same name inside a body this pass will also rewrite."""
    out = []
    for t in _write_targets(node):
        name = t if isinstance(t, str) else getattr(t, "name", None)
        if isinstance(name, str):
            out.append(name.lstrip("*"))
    if isinstance(node, F.VarDecl) and isinstance(node.name, str):
        out.append(node.name)
    kind = type(node).__name__
    if kind in ("FunctionDef", "LambdaExpr"):
        for p in (getattr(node, "params", None) or []):
            if isinstance(p, (tuple, list)) and p and isinstance(p[0], str):
                out.append(p[0].lstrip("*"))
    return out

def _constant_constructor_bindings(fn, structs_by_name: dict) -> dict:
    """`{local: struct}` for a local this body can only have bound to ONE struct.

    The evidence for a `x.NAME` read of a class-level value, and what makes it
    a census rather than a guess: a local qualifies only when EVERY binding of
    it in this body is a call to that struct's constructor and nothing else
    could have bound it.

    Which is stricter than the shape this replaced, and deliberately so — the
    earlier version kept the LAST `x = S(...)` it walked past and answered every
    `x.NAME` from it, which produced a wrong number rather than a refusal. The
    program that shows it:

        struct S:
            var n: Int
            LIMIT = 3
        struct T:
            var LIMIT: Int
        def pick(flag: Int) -> Int:
            var o = T()
            if flag:
                o = S(1)
            return o.LIMIT

    With `flag == 0` the receiver is a `T` whose `LIMIT` was never written, so
    this path's own model says the answer is the word 0 (`struct_default_word`'s
    `DEFAULT_NONE` for a field with no initializer); the image built, ran, and
    printed 3 on BOTH branches, on both architectures. Now `o` is dropped and the
    read is refused, which is the outcome this path exists to prefer over a
    plausible number.

    Three ways a name can be bound without a constructor call, and all three
    disqualify it:

      * a PARAMETER, which the caller may have filled with anything — so a
        constructor binding inside the body is one arm of the function, not the
        function;
      * a binding of any other shape (`o = other`, `for o in …`, `o, x = …`,
        `with … as o`, `o += 1`, a comprehension target), enumerated by
        `_binding_names` so this census and the shadowing rule in
        `_substitute_module_constants` read the same set of bindings;
      * a NESTED `def`/`lambda` parameter of the same name, which shadows the
        outer local in a body this rewrite also visits — the lambdas are lifted
        to functions AFTER this pass, so their parameters are still spelled in
        place here.

    Two bindings of the SAME struct are fine (`o = S(1)` on both arms): the
    question is what the name can hold, not how often it was written. Two
    bindings of DIFFERENT structs are a disagreement, and are refused like every
    other disagreement on this path.

    Returns `(agreed, disputed)`. The second half is what the REFUSAL is built
    from, and it is reported rather than dropped: the emitter's own
    `model.field_access_refusal` answers a base it cannot place with "'o' is
    bound here as a parameter", which for `var o = T()` / `o = S(1)` is not
    what happened at all, and it offers as the remedy the very thing the source
    already did. `disputed[name]` is `[(struct name, the source's spelling of
    that binding)]`, so the diagnostic can name the disagreement and the line
    that caused it instead of guessing at a binding it does not have
    (`_class_read_disagreement`)."""
    bound_elsewhere = set()
    for p in (getattr(fn, "params", None) or []):
        if isinstance(p, (tuple, list)) and p and isinstance(p[0], str):
            bound_elsewhere.add(p[0].lstrip("*"))
    ctor, disputed = {}, {}
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        target = value = None
        if isinstance(node, F.VarDecl):
            target, value = node.name, node.value
        elif isinstance(node, F.AssignStmt) and isinstance(node.target,
                                                           F.IdentExpr):
            target, value = node.target.name, node.value
        struct_name = None
        if target and isinstance(value, F.CallExpr) \
                and isinstance(value.func, F.IdentExpr) \
                and value.func.name in structs_by_name:
            struct_name = value.func.name
        names = _binding_names(node)
        if not names and isinstance(target, str):
            names = [target]
        for name in names:
            if struct_name is not None and name not in bound_elsewhere:
                seen = disputed.setdefault(name, [])
                if not any(s == struct_name for s, _spelling in seen):
                    seen.append((struct_name, M.expr_spelling(value)))
            if name in bound_elsewhere or struct_name is None \
                    or ctor.get(name, struct_name) != struct_name:
                ctor.pop(name, None)
                continue
            ctor[name] = struct_name
    return ({name: structs_by_name[s] for name, s in ctor.items()},
            {name: sorted(bindings) for name, bindings in disputed.items()
             if name not in ctor and len(bindings) > 1})

def _class_read_disagreement(fn, structs_by_name: dict) -> dict:
    """`{access path: diagnostic}` for every class-level value a base may not be.

    The reads this path cannot answer because the BASE is a local bound from two
    different constructors and the name means different things on each — `o`
    built from `S()` and from `T()`, read as `o.LIMIT`, where `LIMIT` is a
    class-level constant of one and a field of the other.

    It is a refusal with its own words rather than a gap, because the two
    available answers are both wrong and the emitter's is the more wrong of the
    two. Substituting the constant would answer a field read with a literal;
    falling through to the field lowering would answer it with whatever the word
    holds; and what the emitter says instead — `field_access_refusal`'s "'o' is
    bound here as a parameter" — is a claim about a binding that never happened,
    followed by a remedy (`bind the base from a constructor this module
    declares`) the source has already used. A refusal whose stated reason is
    entirely false is the worst outcome on this path
    (`bugs/FORMAL_frame_receiver_handoff.md` §4), and this is the one place the
    disagreement is actually known.

    Only a path whose name is a class-level value of one of the candidates is
    reported. A name that is a plain field of all of them is not ambiguous —
    whichever struct it is, the read is a field read — so it is left to the
    field path, which can place it or refuse it with a reason about the layout.
    And nothing is reported for a name that is not read: the caller raises this
    at the read site, so an unused local costs nothing.
    """
    _agreed, disputed = _constant_constructor_bindings(fn, structs_by_name)
    out = {}
    for local, bindings in sorted(disputed.items()):
        structs = [structs_by_name[n] for n, _spelling in bindings
                   if n in structs_by_name]
        spellings = ", ".join(spelling for _n, spelling in bindings)
        for st in structs:
            for name, _default in M.struct_class_constants(st):
                path = f"{local}.{name}"
                if path in out:
                    continue
                kind = _constant_kind(st, name)
                others = [s for s in structs if s is not st]
                other_text = ", ".join(
                    f"{s.name} declares {name!r} as "
                    + ("a field" if name in M.struct_field_names(s)
                       else "nothing at all")
                    for s in others)
                out[path] = (
                    f"{path} reads a {'`comptime` class attribute' if kind == 'comptime' else 'class-level constant'}"
                    f" of {st.name} through {local!r}, and {local!r} is built "
                    f"from more than one constructor in this function "
                    f"({spellings}): {other_text}. So the same spelling is the "
                    f"class's own value on one path and "
                    + ("a field" if others and any(
                        name in M.struct_field_names(s) for s in others)
                       else "nothing readable")
                    + f" on another, and which one reaches this read depends on "
                    f"which binding ran — which is a question about control "
                    f"flow, and this path lowers a field from the BINDING of its "
                    f"base with no analysis of which binding is live. Refused "
                    f"rather than answered from either: the literal is a wrong "
                    f"number where the read is a field, and the field is a wrong "
                    f"number where the read is the constant. Use two names, or "
                    f"read the class's own value through the class "
                    f"({st.name}.{name})")
    return out

def _overridden_comptime_names(struct_defs: dict, st) -> set:
    """The `comptime` names a struct DERIVED from `st` redeclares.

    The set that decides whether a receiver read of `st`'s own binding can be
    answered. A subclass that inherits a binding cannot change what it reads — the
    interpreter merges the bases' aliases into the child and the child's own win,
    so an inherited one is the base's value verbatim — and a subclass that
    REDECLARES it makes the read depend on the receiver's class, which this path
    does not track (`formal/build.py`'s `_method_owners` dispatches a method by
    name, so a method `st` declares is compiled once and runs with whatever
    receiver the call site passed)."""
    out = set()
    for derived in M.struct_derived_names(struct_defs.values(), st.name):
        other = (struct_defs or {}).get(derived)
        if other is not None:
            out |= set(M.struct_comptime_aliases(other))
    return out

def _overridden_comptime_refusal(struct_def, name: str, spelling: str) -> str:
    """The refusal for a `comptime` read a subclass redeclares."""
    return (
        f"{spelling} reads a `comptime` class attribute of {struct_def.name}, "
        f"whose value is not necessarily {struct_def.name}'s: a struct "
        f"deriving from {struct_def.name} in this unit redeclares it, and the "
        f"interpreter gives the DERIVED class's value — the base's aliases are "
        f"merged into the child and the child's own win, and a method "
        f"{struct_def.name} declares is called with whichever receiver the call "
        f"site passed. This path dispatches a method by NAME and does not track "
        f"the receiver's class, so it cannot say which of the two a read gets, "
        f"and answering with {struct_def.name}'s own value would print the "
        f"parent's number for a child. Read it through the class instead "
        f"({struct_def.name}.{name}), which is unambiguous, or give the subclass "
        f"no binding of its own so the two cannot differ"
    )

def _constant_kind(struct_def, name: str) -> str:
    """`"comptime"` for a `comptime` binding, `"constant"` for an assignment.

    One reading of the two kinds, because the rewrite and the two diagnostics
    that quote a read all have to agree about which construct a spelling names:
    a reader told "class-level constant" about `Self.rank` would go looking for
    a class-level assignment that does not exist."""
    return "comptime" if name in M.struct_comptime_aliases(struct_def) \
        else "constant"





def _method_class_constant_bases(fn, owner) -> dict:
    """`{base name: owner}` for the class values `fn` may read through its receiver.

    `owner` is the struct whose method `fn` is (`method_owner_names`), or None
    for a free function, which has no receiver and no `Self`.

    Two bases, and the soundness argument is the same for both:

      * the method's own receiver. A method of `S` is called with an `S` — that
        is what a receiver IS on this path, and it is the premise every frame
        layout here rests on — and a `comptime` binding's value does not depend
        on the instance, so `self.NAME` inside a method of `S` is the same value
        as `S.NAME`. Not "probably the same": there is no instance in the
        expression the value was computed from, because the interpreter evaluates
        it once at struct-definition time in the class body's own scope.
      * `Self`, which names that same type rather than an instance of it.

    This is why the receiver spelling needs no binding census and the general
    `o.NAME` does: here the base's type is not inferred, it is what the
    declaration says the method is."""
    if owner is None:
        return {}
    out = {"Self": owner}
    recv = M.method_receiver_name(fn)
    if recv is not None:
        out[recv] = owner
    return out


def _holder_class_constant_bases(by_name: dict, structs_by_name: dict) -> dict:
    """`{base name: struct}` for a holder this function's analysis agrees on.

    `by_name` is one function's `hstruct` row: `{name: [candidate structs]}`,
    which the holder fixpoint builds out of the BINDINGS it can see — a
    construction, a method call's receiver argument, a parameter every call site
    passes the same way. So a single candidate is the same statement the rest of
    the frame analysis makes about that name: every binding of it is that struct.
    Two or more is the disagreement `struct_frame_slot_candidates` refuses on,
    and it is refused here for the same reason and in the same direction — an
    empty or multi-valued list contributes no base, so the read falls through to
    the frame pass, which refuses it by name. It is a narrowing of what the frame
    pass can answer, never a widening: a base it accepts is one whose every
    visible binding is one struct.

    An EMPTY candidate list means the name holds a plain word rather than a frame
    address, which is a different fact and not a disagreement."""
    out = {}
    for name, cands in (by_name or {}).items():
        if not cands:
            continue
        first = cands[0]
        if all(c is first for c in cands[1:]):
            out[name] = first
    return out


def _constant_literal(struct_def, name: str):
    """`(literal node or None, the initializer)` for a read of the constant `name`.

    The initializer comes back with the `None` because that is the half a
    refusal needs: `Level.NOTSET`'s value is the CALL `Self(0)` and
    `_ZipIterator._InjectedValues`'s is `Tuple[*Self.Ts]`, and a diagnostic that
    quotes the thing it could not materialize sends the reader to the line that
    would have to change, while one that says "not a literal" sends them to
    search the file for a literal that is not there.

    None for the first half when the value is not a literal this path can
    materialize exactly — a dict, a list, a call, a name. The caller refuses
    there; see `_rewrite_class_constants` for why substituting a zero is not an
    option."""
    for const_name, default in M.struct_class_constants(struct_def):
        if const_name != name:
            continue
        kind, payload = M.class_constant_word(const_name, default)
        if kind == M.DEFAULT_INT:
            return F.IntLiteral(value=int(payload)), default
        if kind == M.DEFAULT_STRING:
            return F.StringLiteral(value=payload), default
        return None, default
    return None, None


def _rewrite_class_constants(fn, structs_by_name: dict, owner=None,
                             receiver_structs: dict = None):
    """`S.NAME` / `self.NAME` -> the literal `NAME` holds, in place, over `fn`.

    A class-level constant — a class-level assignment OR a `comptime` binding —
    is not part of any value: it is one value for every instance, so there is
    nothing for a receiver word to hold and nothing for the member-access
    lowering to read. The two ways this could go wrong are both wrong answers
    rather than refusals, which is why the value is materialized HERE, at the
    read, instead of being left to the field path:

      * leave it. `Regs.R0` then reads the local slot spelled `Regs.R0`, which
        nothing ever writes, and the constant becomes whatever the register
        held. A class of nothing but literal constants, with a method adding
        two of them, then built, ran, and returned 31 where the source says 12.
      * refuse everything. Then a class whose constants are all literals — the
        case this path can represent exactly — would be refused for a
        representable program.

    So a LITERAL constant is substituted (it has no free names, so its value is
    the same at every read site in every function), and anything else is
    refused by name: there is no module-global storage on this path for a
    non-literal to live in, and a container constant read as 0 is a
    plausible-looking wrong number rather than a crash.

    `owner` is the struct `fn` is a method of, and it is what makes the RECEIVER
    spellings available — `self.rank`, `Self.rank`, and the `this`/`cls`/`Self`
    spellings `model.struct_receivers` reports for this struct. Without it (a
    plain function) the receiver of the same name is some other value, and the
    census in `_constant_read_sites` says so rather than guessing.

    `receiver_structs` is the same question asked with evidence the caller has
    and this function does not — a base the image's holder analysis settled on
    one struct, or a method receiver — and it is a second argument rather than
    another spelling of `owner` because it is strictly more evidence, not the
    same evidence twice. See `_constant_read_sites` for what puts a base in it."""
    if not structs_by_name:
        return
    _apply_constant_sites(
        fn.body,
        _constant_read_sites(fn, structs_by_name, owner, receiver_structs),
        _class_read_disagreement(fn, structs_by_name))


# ── A module-level NAME, and where its value lives ─────────────────────────
#
# `G = 5` at module level, read from a function, returned 10 on arm64 and 0 on
# x86-64 where the source says 5. The cause is not arithmetic and not the
# language: it is that `_extract_functions` takes only module-level
# FunctionDefs, so the assignment became NO CODE AT ALL, and the read then fell
# through `_load_var` to whatever the register allocator had left in X19 (or to
# an immediate zero on x86-64). Same source, two answers, so the question "what
# is a module-level name" was never asked.
#
# `formal/model.py` now has the table that answers it
# (`collect_module_symbols`, published by `_prepare_functions` and read by
# both backends' local collection), and it splits the answer in two:
#
#   * a module-level name whose value the build FOLDS to a literal is
#     SUBSTITUTED at every read, here, and needs no storage because nothing
#     ever stores it — a function body that assigns the name binds a LOCAL of
#     the same name, which shadows it, so no function can change the value.
#   * anything else is a real global with nowhere to live, and is refused by
#     NAME in `check_module_symbols` — after import resolution, beside the
#     other late checks, so it does not preempt the import diagnosis for a file
#     whose fundamental problem is that it imports `os`.
#
# The substitution is HERE rather than in a backend for the reason
# `_rewrite_class_constants` above is: it is a source-to-source rewrite, and
# doing it in the shared pipeline is what makes the two architectures
# structurally unable to disagree about it.


def _module_constant_sites() -> dict:
    """`{name: literal node}` for every module-level name the build can fold.

    Reads the PUBLISHED table rather than re-deriving it, so a caller with no
    statement list in hand and the executable path's consumer cannot answer
    differently about the same name.

    A name with a `__DATA` SLOT is excluded, and that exclusion is the load-
    bearing part rather than an optimisation. A slotted name is one some function
    writes through `global`, so its value CHANGES while the program runs —
    substituting its module-level initializer at every read would replace a value
    the program computed with the constant it started at. Measured on the tree
    this replaces: `G = 5` with `def bump(): global G; G = G + 1` called twice
    printed `G=5` where CPython prints `G=7`, because the read was the folded 5
    and the write went into a register nothing else named. Two homes for one
    word, and the read picked the one that never changes."""
    stored = M.module_slots()
    return {name: sym.literal for name, sym in M.module_symbols().items()
            if sym.literal is not None and name not in stored}


def _module_constants(symbols: dict) -> dict:
    """`{name: literal}` for the module-level names a symbols table folded.

    The VALUE half of `_module_constant_sites`, and what a dylib records so an
    importer can answer the same question across the boundary: a folded
    module-level name has exactly one value in a whole program, so the build
    that compiled the module is the authority on it and the importer
    materializes the same literal. What is NOT here is every module-level name
    the folder could not fold — those are real globals, and a dylib has nowhere
    to put one (`bugs/FORMAL_module_state_no_storage.md`).

    A name the folder turned into an `IntLiteral` is a number, including for a
    `True`, because a formal value has no separate boolean: `fold_literal_expr`
    already decided that and `_folded_node` already encoded it, and re-deciding
    it here is how the two would come to disagree about what `X = True` is."""
    out = {}
    for name, sym in (symbols or {}).items():
        lit = getattr(sym, "literal", None)
        value = getattr(lit, "value", None) if lit is not None else None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            continue
        out[name] = value
    return out


def _names_bound_in(fn) -> set:
    """Every name `fn` binds itself: its parameters and everything it assigns.

    The shadowing rule, and the reason a module-level substitution cannot be a
    blind textual replace: `G = 5` at module level and `G = 7` inside a
    function are two different variables, and a rewrite that put the 5 into the
    function's body would replace the function's OWN local with a constant.

    The set is the UNION of two readings on purpose. `bound_names_in_order` is
    the shared middle-end walk the register allocator uses, and it does not
    descend into every statement the emitter descends into — measured:
    `std/math/polynomial.mojo:101` has `var result = …` inside a `comptime
    if`'s `else` arm, the allocator collects it, and the walk alone did not,
    so this check called a name "unplaced" that the emitter has a register for.
    A name ANY of them reports as written here is genuinely written somewhere
    in this body, which is what "a local of this function" means, so the
    union cannot place a name the function does not bind.

    The one hole this leaves, and it is a hole the EMITTER already has rather
    than one introduced here: a name written only inside an arm that never
    executes gets a register home and is never written into it. Closing that
    needs a reachability analysis over the allocator's own table, which is a
    change to the emitter's model and not to a name check. Recorded here
    rather than fixed, because fixing it here would make this check disagree
    with the table it is checking."""
    from mojo.middle.boundnames import bound_names_in_order
    out = set()
    for p in (getattr(fn, "params", None) or []):
        if isinstance(p, (tuple, list)) and p and isinstance(p[0], str):
            out.add(p[0].lstrip("*"))
    try:
        out.update(n for n in bound_names_in_order(fn.body, fn.params)
                   if isinstance(n, str))
    except Exception:
        pass
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        for t in _write_targets(node):
            if isinstance(t, str):
                out.add(t)
            elif isinstance(t, F.IdentExpr):
                out.add(t.name)
    return out


def _write_targets(node) -> list:
    """The names a single node WRITES. `[]` for a node that writes none.

    Every form a binding can take: a declaration, an assignment, an augmented
    assignment, a `for` target, a `with … as`, a tuple/paren target, and a
    comprehension's `for … in`. A read is deliberately not here — that is the
    whole distinction this module turns on."""
    kind = type(node).__name__
    target = None
    if kind in ("AssignStmt", "AugAssignStmt", "ForStmt", "WithStmt",
                "AsTarget", "ComprehensionFor", "ExceptHandler"):
        target = getattr(node, "target", None) or getattr(node, "name", None)
        if kind == "ExceptHandler":
            target = getattr(node, "name", None)
    elif kind == "VarDecl":
        return [node.name]
    elif kind in ("MultiAssignStmt",):
        return [t for t in (getattr(node, "targets", None) or [])]
    if target is None:
        return []
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        return list(getattr(target, "elements", None) or [])
    return [target]


def _substitute_module_constants(functions: list) -> int:
    """Replace every read of a foldable module-level name with its value.

    Returns the number of names substituted, for the sweep's own accounting.

    In place, over each function's body, and only for names the reading
    function does not itself bind. A STORE to such a name cannot occur — a
    function that assigns the name shadows it, which is the premise that makes
    the substitution sound — but a `del` of one can be written, and a store
    position is skipped explicitly rather than left to the shadowing rule
    alone."""
    sites = _module_constant_sites()
    if not sites:
        return 0
    done = 0
    for fn in functions:
        local = _names_bound_in(fn)
        mine = {n: lit for n, lit in sites.items() if n not in local}
        if not mine:
            continue
        stores = _assigned_names(fn.body)
        for n, lit in mine.items():
            if n not in stores:
                done += 1
        _apply_module_constant_sites(fn.body, mine, stores)
    return done


def _publish_imported_constants(functions: list, symbols: dict,
                                imported: list) -> dict:
    """Substitute the link line's folded constants into `functions`, in place.

    Returns the symbols table the substitution needs the callers to PUBLISH, so
    one function owns both halves and they cannot be applied out of order: the
    rewrite needs the sites, and the checks after it need the table those sites
    came from.

    Both spellings of the read are answered, because they are two spellings of
    one question — what is the value of a module-level name another module
    declares:

      * a BARE read — `from mod import CONST`, then `CONST` — goes through the
        module-constant substitution this unit already runs, because a name a
        linked module publishes as a literal is foldable in exactly the sense
        that pass means. It is done by re-publishing the table with those names
        promoted and re-running the pass, rather than by a second rewriter, so
        the two can never disagree about a name that is BOTH a unit-level
        constant and an imported one (the unit's own binding wins, which is
        what the shadowing rule already says) or about a store position.
      * a DOTTED read — `mod.CONST`, the spelling `import mod` binds and the one
        this is for — is answered from the module its own qualifier names. There
        is no bare name in it to fold, so it is its own walk, and it is here
        rather than in a backend because it is a source-to-source rewrite: both
        architectures have to see the same literal, and a rewrite performed in
        an emitter is two implementations of one decision.

    A STORE is not a read and is left alone: `mod.X = 5` writes another
    module's state, which has nowhere to live and is refused by name
    (`bugs/FORMAL_module_state_no_storage.md`). Substituting it would trade a
    refused store for a dropped one.

    `imported` is the link line's `load_dylib_manifests` entries, which is the
    only place the answer exists: the build that compiled each module is the
    only place its folded values were ever computed, and it left them in that
    module's manifest. An empty list is a no-op, so an image with no dylibs on
    its line behaves exactly as it did before."""
    tables = M.dylib_module_constants(imported)
    if not tables:
        return symbols
    sites = _imported_constant_sites(imported, symbols)
    merged = _with_imported_constants(symbols, sites)
    if sites:
        M.publish_module_symbols(merged)
        _substitute_module_constants(functions)
    for fn in functions:
        _apply_imported_constant_sites(fn.body, tables,
                                       _names_bound_in(fn))
    return merged


def _imported_constant_sites(imported: list, symbols: dict) -> dict:
    """`{bare name: literal node}` for the constants a linked module publishes.

    The BARE half of the answer, and it works by the same argument as the
    dotted half: a `from mod import CONST` binds a bare name, and the only
    question is which module's value of that name is meant. A linked library
    that publishes it as a folded literal is the authority, and the libraries
    are consulted in LINK ORDER, which is `load_dylib_manifests`'s own
    precedence for every other name on the line — so a bare constant resolves
    by the same rule a bare callee does, and a dotted one resolves by module
    identity exactly as a dotted callee does.

    Only names the PUBLISHED table records as `imported` are candidates, and
    that is what keeps this from answering a question the source did not ask: a
    bare name this unit defines itself is not `imported`, and a bare name no
    linked module publishes as a literal keeps the ordinary module-global
    refusal, which is the answer for a real global and for a typo alike."""
    tables = M.dylib_module_constants(imported)
    sites = {}
    for name, sym in (symbols or {}).items():
        if getattr(sym, "site", None) != "imported":
            continue
        for value in _constants_named(tables, name):
            sites[name] = M.constant_literal_node(
                value, getattr(sym, "line", 0) or 0, 0)
            break
    return sites


def _constants_named(tables: dict, name: str) -> list:
    """Every value a linked module publishes under the bare `name`.

    In link order, because `dylib_module_constants` preserves it. A bare name
    cannot say which module it means, and a program that imports two modules
    publishing the same constant has a question this path does not answer
    precisely; the first library on the line is the answer it already gives
    for a bare callee, so the choice is made once, here, rather than at each
    read site."""
    return [table[name] for table in tables.values() if name in table]


def _with_imported_constants(symbols: dict, sites: dict) -> dict:
    """`symbols` with each imported constant promoted to a FOLDABLE binding.

    The substitution reads the published table, so a name has to be IN it with
    a literal for a bare read of it to be answered at all. The site stays
    `imported` and keeps its module: a read that survives the substitution for
    any reason (a store, a callee) must still be refused as an imported name
    rather than as a local this unit happens to define, and the message that
    says so names the module it came from."""
    out = {}
    for name, sym in (symbols or {}).items():
        lit = sites.get(name)
        if lit is None or getattr(sym, "site", None) != "imported":
            out[name] = sym
        else:
            out[name] = M.GlobalSymbol(name, lit, "imported",
                                       getattr(sym, "module", None),
                                       getattr(sym, "line", 0) or 0)
    return out


def _apply_imported_constant_sites(node, tables: dict, bound: set) -> int:
    """The dotted read `mod.CONST` walk, in place. Returns the sites rewritten.

    Parent-directed, for the one reason the identifier rewriter is: a store
    target is not a read, and only the parent can say so. A chain is answered
    from its WHOLE qualifier (`os.path.SEP` asks `os.path`), because that is
    the module the name belongs to; and a name the qualifier's module does not
    publish is left alone, so `xs.count`, `struct.field` and a module's own
    function keep whatever answers they had.

    ONE test, in `_rewrite_dotted_child`, used from every parent shape — and that is
    the whole design. A child reached from a list element, from a dataclass
    field, from a call's argument list and from a store's VALUE side are four
    spellings of the same parent-directed rewrite, and a rewrite applied in
    three of them and not the fourth is not a rewrite. Measured, that fourth
    omission was live: `print(mod.K)` lowered (a call argument goes through
    `_rewrite_dotted_child`) while `x = mod.K` and `var x = mod.K` were refused
    with `mod_global_refusal` — the message that claims a dylib cannot publish a
    VARIABLE, about a name that is a folded CONSTANT the module's own manifest
    already carries. Both spellings were refused by the same walk with the same
    message, so the construct looked like a storage gap in half its positions.
    Hence the assignment below rather than a bare recursive call: the store's
    value is a CHILD of the statement, so the replacement has to be written back
    into the statement's slot, which is what `_rewrite_dotted_child` returns it
    for.
    """
    if isinstance(node, list):
        done = 0
        for i, child in enumerate(node):
            node[i], n = _rewrite_dotted_child(child, tables, bound)
            done += n
        return done
    if isinstance(node, (F.AssignStmt, F.AugAssignStmt, F.VarDecl)):
        # The TARGET is a store and is left alone — `mod.K = 5` writes another
        # module's state, which has nowhere to live and is refused by name
        # (`bugs/FORMAL_module_state_no_storage.md`); substituting it would trade
        # a refused store for a dropped one. The VALUE side is an ordinary read
        # and goes through the ONE test.
        value, n = _rewrite_dotted_child(getattr(node, "value", None),
                                         tables, bound)
        if hasattr(node, "value"):
            node.value = value
        return n
    if isinstance(node, F.CallExpr):
        # The callee is a SYMBOL, not a read of a value — the same rule the
        # identifier rewriter follows, for the same reason: `mod.f(...)` must
        # not become `7(...)`, a call to a number, if some module on the line
        # also publishes a constant `f`.
        done = _apply_imported_constant_sites(node.args or [], tables, bound)
        for i, pair in enumerate(node.kwargs or []):
            if not isinstance(pair, (tuple, list)) or len(pair) < 2:
                continue
            value, n = _rewrite_dotted_child(pair[1], tables, bound)
            node.kwargs[i] = (pair[0], value)
            done += n
        return done
    done = 0
    for fname in getattr(node, "__dataclass_fields__", {}):
        if fname in ("line", "col"):
            continue
        child, n = _rewrite_dotted_child(getattr(node, fname, None), tables, bound)
        setattr(node, fname, child)
        done += n
    return done


def _rewrite_dotted_child(child, tables: dict, bound: set):
    """`(possibly-replaced child, sites rewritten)`.

    The one test, and the one place a replacement is produced: a node this
    rewrites is a node its PARENT holds, so the replacement is recorded in the
    parent's slot. A rewrite that handed a new node back to a caller with
    nowhere to put it would be a rewrite that silently did nothing."""
    if child is None or isinstance(child, (str, int, float, bool)):
        return child, 0
    if _is_dotted_constant(child, tables, bound):
        return _imported_constant_node(child, tables), 1
    return child, _apply_imported_constant_sites(child, tables, bound)


def _imported_constant_node(expr, tables: dict):
    """The literal node for the constant `expr` reads, at `expr`'s position."""
    return M.constant_literal_node(
        _dotted_constant_value(expr, tables),
        getattr(expr, "line", 0) or 0, getattr(expr, "col", 0) or 0)


def _dotted_qualifier(expr):
    """`("os.path", "SEP")` for `os.path.SEP`, or None.

    The root has to be a bare name — a call result or a subscript is not a
    module reference and not a name a module can be asked about. Whether that
    root is a LOCAL of the reading function is the caller's question, because
    only the caller has the function: a local shadows nothing, and a local has
    no module behind it either way."""
    parts = []
    node = expr
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    if not parts or not isinstance(node, F.IdentExpr):
        return None
    return ".".join([node.name] + list(reversed(parts[:-1]))), parts[0]


def _dotted_constant_value(expr, tables: dict):
    """The literal `expr` names, or None. None is a refusal, never a zero."""
    pair = _dotted_qualifier(expr)
    if pair is None:
        return None
    return M.imported_constant(tables, pair[0], pair[1])


def _is_dotted_constant(expr, tables: dict, bound: set) -> bool:
    """Whether `expr` is a read of a constant some linked module publishes."""
    if not isinstance(expr, F.MemberExpr):
        return False
    pair = _dotted_qualifier(expr)
    if pair is None or pair[0].split(".", 1)[0] in bound:
        return False
    return M.imported_constant(tables, pair[0], pair[1]) is not None


def _assigned_names(body) -> set:
    """Names this body WRITES. A write is not a read and is never substituted.

    Only the two forms that reach here matter — a `VarDecl` and an assignment
    target — but the set is computed over the whole body because a write inside
    a loop or a branch is a write."""
    out = set()
    for node in M.iter_nodes(body):
        target = None
        if isinstance(node, (F.AssignStmt, F.AugAssignStmt)):
            target = getattr(node, "target", None)
        elif isinstance(node, F.VarDecl):
            target = F.IdentExpr(name=node.name)
        if isinstance(target, F.IdentExpr):
            out.add(target.name)
    return out


def _apply_module_constant_sites(node, sites: dict, stores: set) -> None:
    """The walk, in place. Every `IdentExpr` is rewritten in its parent's slot.

    Written as a parent-directed recursion rather than a node-directed one
    because the two positions a name must NOT be rewritten in — a store target
    and a call's callee — are only identifiable from the parent, and replacing
    them would be the two wrong answers this whole change exists to remove
    (a store turned into a value is a dropped store; a callee turned into a
    literal is a call to a number).

    A TUPLE is descended into, and that is not a generalization — it is the
    `elif` arm. `IfStmt.elifs` is a list of `(condition, body)` pairs, and a
    condition is an ordinary expression position in every respect, so the
    substitution covered `if x == K:` and skipped `elif x == K:`. The skipped
    name then reached the emitter as a bare `IdentExpr` with no home and was
    REFUSED ("'K' has no home") on both architectures, for a construct the
    build answers everywhere else — measured in
    bugs/CODEGEN_elif_arm_reading_a_module_constant_has_no_home.md, whose
    diagnosis blamed the emitter's phi/web slot. It was this walk: the same
    shape of mistake as the assignment case in that file, one position over.
    The other walks over this tree already knew `elifs` was pairs and spelled
    it out (`strip_body`, `walk_body`); this one did not, and a walk that has
    to be re-derived per consumer is exactly how they drift.

    A tuple has no assignable slots, so the walk RETURNS a new one for it and
    the caller puts it back; a list is still rewritten in place."""
    if isinstance(node, (list, tuple)):
        out_items = []
        for child in node:
            if isinstance(child, F.IdentExpr) and child.name in sites \
                    and child.name not in stores:
                out_items.append(copy.deepcopy(sites[child.name]))
                continue
            if isinstance(child, F.CallExpr) and isinstance(child.func,
                                                           F.IdentExpr) \
                    and child.func.name in sites:
                # a callee NAME is not a read of the value
                for a in child.args or []:
                    _apply_module_constant_sites(a, sites, stores)
                for _k, v in (child.kwargs or []):
                    _apply_module_constant_sites(v, sites, stores)
                out_items.append(child)
                continue
            # This walk rewrites a child's own slots IN PLACE and returns None
            # for anything that is not itself a list or a tuple, so the
            # original child is what goes back in the sequence — unless the
            # recursion handed back a rebuilt sequence, which is the one case
            # where the child itself is the container.
            rebuilt = _apply_module_constant_sites(child, sites, stores)
            out_items.append(child if rebuilt is None else rebuilt)
        if isinstance(node, tuple):
            return tuple(out_items)
        node[:] = out_items
        return node
    if isinstance(node, (F.AssignStmt, F.AugAssignStmt, F.VarDecl)):
        # The target is a store: leave it, and walk the value side only.
        #
        # …through `_rewrite_child`, which RETURNS a replacement, and not
        # through this function, which rewrites in place. That is the whole
        # difference and it was a live bug: a bare `IdentExpr` has no child
        # slots to rewrite (its fields are `name`, `line` and `col`, all
        # scalars), so handing one to the in-place walk walked straight through
        # it and left the name in place. Every other position reached the
        # replacement — a list element is matched in the list branch, and every
        # other single child goes through `_rewrite_child` — so the substitution
        # silently covered `return G`, `print(G)` and `G + 1` and missed
        # `x = G`, `x: Int = G` and `h.a = G`. The consequence is the `has no
        # home` refusal, on both architectures, for a construct the build
        # answers. Pinned by `test_formal_globals.py`'s
        # `read_global_as_an_assignment_value` and
        # `read_global_into_a_field_store`, the second of which is the one that
        # matters — a `MemberExpr` store target is the shape this backend uses
        # for every struct field write, so the uncovered position was reached by
        # ordinary code rather than by an assignment to a bare local.
        node.value = _rewrite_child(getattr(node, "value", None), sites,
                                    stores)
        return
    for name in getattr(node, "__dataclass_fields__", {}):
        setattr(node, name,
                _apply_module_constant_sites(getattr(node, name), sites,
                                             stores)
                if isinstance(getattr(node, name), (list,)) else
                _rewrite_child(getattr(node, name), sites, stores))
    return


def _rewrite_child(child, sites: dict, stores: set):
    """One non-list child: replace an `IdentExpr` read, else recurse.

    A TUPLE is the one child that cannot be rewritten where it lies — the walk
    rebuilds it and returns it, so the caller has to put it back. An `elif` PAIR
    arrives here because `IfStmt.elifs` is a LIST of tuples, so the list branch
    hands each one over rather than descending into it itself."""
    if child is None or isinstance(child, (str, int, float, bool)):
        return child
    if isinstance(child, F.IdentExpr):
        if child.name in sites and child.name not in stores:
            return copy.deepcopy(sites[child.name])
        return child
    if isinstance(child, F.CallExpr):
        if isinstance(child.func, F.IdentExpr) \
                and child.func.name in sites:
            for a in child.args or []:
                _apply_module_constant_sites(a, sites, stores)
            for _k, v in (child.kwargs or []):
                _apply_module_constant_sites(v, sites, stores)
            return child
    if isinstance(child, tuple):
        return _apply_module_constant_sites(child, sites, stores)
    _apply_module_constant_sites(child, sites, stores)
    return child


def _fold_target_queries(functions: list) -> int:
    """Replace every `#kgen.param.expr<…>` target query in a body with its value.

    Returns the number of sites folded.

    A source-to-source rewrite in the SHARED pipeline rather than a case in
    either backend's expression walk, and the reason is the same one
    `_substitute_module_constants` and `_rewrite_class_constants` give: a
    question the BUILD answers is a question that must not be answered twice.
    If this lived in the emitters then arm64 and x86-64 would each carry their
    own copy of the answer to "what is the current target's arch", and the two
    would be free to disagree about it — the failure mode this module's whole
    design exists to prevent. Replacing the query with the literal it denotes
    also means everything downstream — the comptime folder, the name check, both
    instruction selectors — sees an ordinary `StringLiteral` and needs to know
    nothing about MLIR at all.

    PRE-ORDER, and it does NOT descend into a query it folded (that subtree is
    gone with it) nor into one it did not. The second half is the part that is
    not an optimisation: `std/_plugin/selector.mojo` nests a
    `target_get_field` inside an `eq` that also needs a plugin table this build
    has no value for, and replacing the inner node would leave the outer one
    holding a hole no evaluator can read — turning a refusal that names the
    missing plugin into one that names an argument. Refusing a whole template
    is the honest answer, so the walk leaves it whole."""
    done = 0
    for fn in functions:
        body = getattr(fn, "body", None)
        if not isinstance(body, list):
            continue
        count = [0]
        _fold_target_queries_in(body, count)
        done += count[0]
    return done


def _fold_target_queries_in(node, count: list):
    """The walk, in place. Returns a replacement node for `node`, or None.

    `count` is a one-element list because a list element has to be replaced
    through its parent while a single-attribute child has to be replaced
    through `setattr`, and one walk serves both — so the number of sites folded
    comes back through a box rather than as a return value that only one of the
    two shapes could carry."""
    if isinstance(node, (list, tuple)):
        # A tuple as well as a list, and not as a generality: a call's KEYWORD
        # arguments are a list of `(name, value)` pairs (`CallExpr.kwargs`),
        # which is where `std/builtin/type_aliases.mojo` keeps its templates —
        # `Origin[0, _mlir_origin=__mlir_attr[…]]()`. Descent that stops at
        # lists walks straight past them and leaves the query in the tree, so
        # the backend then refuses a construct the build can answer, and the
        # read of a `comptime` bound from it materializes a register.
        #
        # A tuple cannot be assigned into, so a tuple with a replaced element
        # comes back as a LIST and the list slot it was read from takes it. A
        # tuple with nothing replaced returns None, which is what keeps the
        # common case — every keyword argument in the corpus that is not a
        # template — from rewriting the list it lives in.
        out = []
        changed = isinstance(node, tuple)
        for i, child in enumerate(node):
            if M.is_mlir_template(child):
                # A template this pass could not answer keeps its shape, WHOLE:
                # see the function's note on `selector.mojo`. The test is
                # `model.template_is_answered`, the SAME one the module-level
                # refusal asks, because these two walks over the same tree used
                # to disagree and refused a construct the build answers.
                folded = M.fold_target_template(child)
                if folded is not None:
                    folded = M.folded_literal_node(folded, child)
                    count[0] += 1
                    changed = True
                if isinstance(node, list):
                    node[i] = folded if folded is not None else child
                else:
                    out.append(folded if folded is not None else child)
                continue
            repl = _fold_target_queries_in(child, count)
            if repl is not None:
                changed = True
            if isinstance(node, list):
                if repl is not None:
                    node[i] = repl
            else:
                out.append(child if repl is None else repl)
        return out if (changed and isinstance(node, tuple)) else None
    if node is None or isinstance(node, (str, int, float, bool)):
        return None
    folded = M.fold_target_template(node)
    if folded is not None:
        count[0] += 1
        return M.folded_literal_node(folded, node)
    for name in getattr(node, "__dataclass_fields__", {}):
        child = getattr(node, name)
        if isinstance(child, (list, tuple)):
            _fold_target_queries_in(child, count)
        elif child is not None and not isinstance(child, (str, int, float,
                                                          bool)):
            repl = _fold_target_queries_in(child, count)
            if repl is not None:
                setattr(node, name, repl)
    return None


def _bound_before_first_statement(stmts) -> set:
    """Names a function's body binds NOT by an assignment: a `global`
    declaration, a loop target, a `with … as` alias, a comprehension variable.

    Every one of these is a name that is either not a local at all
    (`global`) or is local and ALREADY BOUND before the first statement's value
    is evaluated.  A read of one of them is legal, and a check that flagged it
    would be refusing correct code — which is the failure mode
    `bugs/FORMAL_a_frame_holder_rebound_from_a_word.md` records for the receiver
    exclusion, and the reason this is a named helper rather than a condition
    repeated at each use."""
    out = set()
    for node in M.iter_nodes(stmts):
        if isinstance(node, (F.AssignStmt, F.VarDecl, F.AugAssignStmt)):
            continue
        if isinstance(node, F.GlobalStmt):
            for n in (getattr(node, "names", None) or ()):
                out.add(n.name if hasattr(n, "name") else n)
            continue
        target = getattr(node, "target", None)
        if isinstance(target, F.IdentExpr):
            out.add(target.name)
        elif isinstance(target, (F.TupleExpr, F.ListExpr)):
            for e in target.elements:
                if isinstance(e, F.IdentExpr):
                    out.add(e.name)
        if isinstance(node, F.WithStmt):
            for item in (getattr(node, "items", None) or ()):
                alias = getattr(item, "alias", None)
                if isinstance(alias, F.IdentExpr):
                    out.add(alias.name)
    return out


def _assign_target_names(node) -> list:
    """The plain names one assignment statement binds, or [] for any other shape."""
    if isinstance(node, F.AssignStmt):
        if isinstance(node.target, F.IdentExpr):
            return [node.target.name]
        if isinstance(node.target, (F.TupleExpr, F.ListExpr)):
            return [e.name for e in node.target.elements
                    if isinstance(e, F.IdentExpr)]
        return []
    if isinstance(node, F.VarDecl):
        return [node.name]
    if isinstance(node, F.AugAssignStmt) and isinstance(node.target,
                                                        F.IdentExpr):
        # An augmented assignment READS before it writes, so a name reached only
        # this way is a read-before-assign of exactly the same kind — and CPython
        # raises on it too.
        return [node.target.name]
    return []


def _declared_global_names(stmts) -> set:
    """The names a function's body declares `global`."""
    out = set()
    for node in M.iter_nodes(stmts):
        if not isinstance(node, F.GlobalStmt):
            continue
        for n in (getattr(node, "names", None) or ()):
            out.add(n.name if hasattr(n, "name") else n)
    return out


def _collect_shadowed_global_reads(functions) -> None:
    """PARK the two ways a function and a module-level binding of the same name
    come to disagree: reading a local it has not assigned, and writing a global
    it has declared.

    1. `G = 5` at module level, then `def bump(): G = G + 1; return G`.  The
       right-hand `G` does not resolve in module scope — a name assigned anywhere
       in a function body is local to that body from its first line — so CPython
       raises `UnboundLocalError` and the program has no number.  This path reads
       the name's local home, which has no value, and answers whatever the
       register allocator left there: measured, 11 on x86-64 and 78152773 on
       arm64, from identical source, with the module's `G` correctly left at 5.
    2. `def bump(): global G; G = G + 1; return G`.  This one the language
       allows and the value model has nowhere for: there is no `__DATA` slot to
       redirect the write into, so the emitters treat `global` as a no-op and the
       assignment lands in a local.  Measured, CPython 6 and 6; this path 10601485
       and 5 on arm64, 11 and 5 on x86-64.

    **The read half is scoped to the module-global case, and the measurement is
    why.**  The language's rule is general — reading any local before its first
    assignment raises — and enforcing the general form was measured at **233
    sites in 57 files of this repository** and **8 in 5 stdlib files** (a
    syntactic scan with a call's callee, a `global` declaration and every
    loop/with/comprehension target already excluded), which is a coverage cost of
    a different order from the one site this fixes.  With the name ALSO bound at
    module level the collision is unambiguous — the source is visibly asking
    about the module's binding, and the alternative reading is the one CPython
    rejects — and the same scan finds **0 sites in 319 repository files and 0 in
    294 stdlib files**.  The general remainder is written down in
    `bugs/FORMAL_a_local_read_before_its_first_assignment.md`.

    Parked rather than raised, for the reason the other five late frame checks
    are: `_prepare_functions` runs before `_resolve_imports`, so a refusal from
    inside it preempts the import diagnosis.
    """
    globals_ = set(M.module_symbols())
    if not globals_:
        return
    for fn in functions:
        stmts = list(getattr(fn, "body", None) or ())
        if not stmts:
            continue
        declared_globals = _declared_global_names(stmts) & globals_
        prebound = _bound_before_first_statement(stmts)
        prebound |= set(M.function_param_shape(fn).names or ())
        assigned = set()
        for node in M.iter_nodes(stmts):
            assigned |= set(_assign_target_names(node))
        if declared_globals & assigned:
            # …and only for a name with NO `__DATA` slot, which is the same rule
            # `_module_constant_sites` states and for the same reason: a slotted
            # name is one some function writes through `global`, its value
            # changes while the program runs, and the write has somewhere real to
            # go. Case 2 in the docstring was written when there was no slot to
            # redirect the write into and it says so;
            # `formal-module-globals` landed the slot, so refusing it now refuses
            # a program this path computes exactly. Measured: it was 6 of
            # `test_formal_globals.py`'s 17 cases before this gate and 0 after,
            # and the image answers CPython (`G = 5` with
            # `global G; G = G + 1` called twice, read back after: 7).
            writable = declared_globals & assigned - set(M.module_slots() or ())
            if writable:
                fn._mutated_module_global = sorted(writable)[0]
                return
        candidates = (assigned & globals_) - prebound - declared_globals
        if not candidates:
            continue
        bound = set(prebound)
        for node in M.iter_nodes(stmts):
            names = _assign_target_names(node)
            if not names:
                continue
            value = getattr(node, "value", None)
            if value is None:
                continue
            # A tuple target's value is evaluated before ANY store, so a read of
            # a tuple target's own name there is legal; a plain `x = x + 1` is
            # not, and is the finding.
            own = (set() if isinstance(getattr(node, "target", None),
                                       F.IdentExpr)
                   else set(names))
            callee_names = {n.func.name for n in M.iter_nodes(value)
                            if isinstance(n, F.CallExpr)
                            and isinstance(n.func, F.IdentExpr)}
            for n in M.iter_nodes(value):
                if not isinstance(n, F.IdentExpr):
                    continue
                if n.name not in candidates or n.name in bound:
                    continue
                if n.name in own or n.name in callee_names:
                    continue
                fn._shadowed_global_reads = [(n.name, _expr_spelling(value))]
                break
            if getattr(fn, "_shadowed_global_reads", None):
                break
            bound |= set(names)


def check_shadowed_global_reads(functions) -> None:
    """Raise the read-before-assign and mutated-global findings
    `_collect_shadowed_global_reads` parked.  The sixth late check, at the entry
    points, for the reason the other five are."""
    for fn in functions:
        mutated = getattr(fn, "_mutated_module_global", None)
        if mutated is not None:
            raise CodegenError(M.mutated_module_global_refusal(
                mutated, fn.name))
        for name, value_spelling in (
                getattr(fn, "_shadowed_global_reads", ()) or ()):
            raise CodegenError(M.shadowed_module_global_read_refusal(
                fn.name, name, value_spelling))
def _materialize_entry_dunder_name(functions: list) -> int:
    """Replace a read of `__name__` in the MODULE BODY with `"__main__"`.

    Only in the module body, and the restriction is the whole correctness
    argument. `__name__` is a Python-level value, not a local, and the module
    body is the only place on this path where one specific value of it is
    knowable: the body IS the program's entry, and the entry program's
    `__name__` is `"__main__"` — that is what CPython says for `python3
    file.mojo`, and it is the same answer on both architectures because it is
    a fact about what the file is rather than about the machine. It is also
    what makes the `if __name__ == "__main__":` guard work, which is 143 of
    the 210 files in this tree and the stdlib that have a top-level statement:
    without it every one of them would be refused on a name, and the refusal
    would be about a construct that has an exact answer.

    In a FUNCTION it stays unplaced and is still refused by
    `check_module_symbols`, which is right: a function's `__name__` is the
    name of whatever MODULE it was defined in, and a function lifted out of an
    imported module has no answer this path can give. Materializing it there
    too would answer a question the source does not ask with a value that is
    right only for this file — the same class of lie as a `PLATFORM` constant
    in `bugs/FORMAL_module_state_no_storage.md`.

    Uses the module-constant substitution's OWN rewriter rather than a second
    one, because the two have the same subtlety: a store target and a call's
    callee are not reads, and a rewrite that replaced either would turn a
    store into a dropped one and a call into a call to a string.

    Returns the number of functions touched, for the test to pin.
    """
    sites = {"__name__": F.StringLiteral(value="__main__", line=0, col=0,
                                         is_bytes=False)}
    done = 0
    for fn in functions:
        if getattr(fn, "name", None) != M.MODULE_BODY_NAME:
            continue
        stores = _assigned_names(fn.body)
        if "__name__" in stores:
            # The body assigns it, so it is an ordinary local here and the
            # substitution must not overwrite the source's own value.
            continue
        _apply_module_constant_sites(fn.body, sites, stores)
        done += 1
    return done


def _module_published_names(module: str, link_line) -> set:
    """Every name the library built for `module` publishes, by definition or by
    re-export.

    What the module-attribute refusal prints, so a reader can see in one line
    whether the attribute they wrote is one the module has. Read through
    `model.dylib_export_tables` — the same tables the emitted CALL binds
    through, in the same link order — rather than off the manifests directly,
    because "what this module publishes" is a question the emitter already asks
    and a second reading of the manifests is a second answer to it.

    A module with no library on the line publishes nothing, and that is the
    honest answer rather than a crash: `imported_module_names` is gated on
    `import_dylibs` by `_run_late_checks`, so an empty table means the caller
    has not resolved imports and the rooted-chain gate is already closed."""
    if not link_line:
        return set()
    _by_name, by_module, forwarded = M.dylib_export_tables(
        dylib_export_lists(link_line))
    return set(M.dylib_export_module(by_module, module)) | set(
        M.dylib_export_module(forwarded, module))


def check_module_symbols(functions: list, structs_by_name: dict = None,
                         imported_module_names=None, link_line=None) -> None:
    """Refuse every name a function reads that no table in the compiler places.

    A LATE check, called beside `check_frame_field_blob_premises` and
    `check_construction_shapes` and for the reason build.py records for those
    two: raising out of `_prepare_functions` preempts the import diagnosis, so
    fourteen files of this repository that import a host module were reported as
    codegen gaps instead of as the host imports they are.

    A name read in a function is placed by exactly one of these, and a read
    that is in none of them is a wrong answer waiting to happen:

      * a PARAMETER or a LOCAL of the reading function — the allocator's own
        table, which the emitter and this check must agree on;
      * a COMPTIME binding, module-level or in this very function, and a
        generic's compile-time parameters: the backends resolve those
        themselves (`_comptime_vals`) and answer the read from a folded value,
        so a name they place is not this check's business;
      * a TYPE name — a struct this unit compiles, reached as `S.x` or called
        as `S()`. A struct is not a value and has no register;
      * a RECEIVER FIELD (`h.x`), which is a load from a frame, not a name;
      * a module-level constant the build FOLDED, which
        `_substitute_module_constants` has already replaced in the AST by the
        time this runs — so reaching here means the substitution did not cover
        this read, and the message says that rather than blaming the register.

    What is left is the tail the X19 fall-through used to answer with whatever
    the allocator left behind, and it is refused with the name and the reason.
    The list of names that resolve with no local at all is
    `model.name_resolves_without_a_local`, and it is deliberately short.

    An MLIR TEMPLATE is asked about FIRST, in its own spelling, because its
    refusal names the construct and this one would name a symptom: `__mlir_
    attr[`…`]`'s callee is a bare name with no home, and the diagnostic that
    says "a multi-index subscript" was already wrong about it once. The same
    holds for a BARE `__mlir_op` with no template attached, which is why it is
    part of that pre-pass and not of the walk below — see the note on
    `first_mlir` for the measured cost and for why pre-empting is the right
    answer rather than a coin flip.

    `imported_module_names` is the set of module names this unit imports. It
    is what tells the DOTTED callee `mod.f(...)` from a value's method: the
    root of the chain is a module reference, not a read of a value, and the
    emitter resolves the call from that module's own export table. Omitted (or
    empty) the dotted spelling is refused exactly as before, so a caller that
    has not resolved its imports still gets the old answer.

    `link_line` is the same list `check_imported_frame_handoffs` takes — the
    link line's manifests in LINK ORDER, which is the order the emitted call
    binds. It is consulted for ONE thing, and only when a rooted member chain
    needs a refusal: what that module PUBLISHES, so the message can print it
    (`sys.argv` next to the list of names `sys` does publish, which is
    `dylib_extern_symbol`'s own device for a dotted call). Omitted it prints
    nothing rather than guessing, and the refusal is unchanged otherwise — so
    a caller that passes only the first three arguments keeps every verdict it
    had."""
    struct_names = set(structs_by_name or {})
    # A read-before-store hit per function, raised after the loop: see the
    # ordering note where they are raised.
    unstored: list = []
    for fn in functions:
        shape = M.function_param_shape(fn)
        placed = {n for n, _t in shape.fixed}
        placed |= {shape.vararg, shape.kwarg}
        placed.discard(None)
        placed |= _names_bound_in(fn)
        placed |= _comptime_bound_names(fn)
        placed |= struct_names
        # A name in BRACKETS after a name this unit compiles is a comptime
        # SPECIALISATION, not a read of a value: `_horner_evaluate[coeffs](x)`
        # names the function with the type arguments it is specialised at, and
        # the backends handle exactly that shape (`_specialization_args`,
        # `_specialization_of`). `std/math/polynomial.mojo:49` and
        # `std/utils/_serialize.mojo:28` are the real sources. Without this the
        # root of the bracket is a bare name with no home and is refused,
        # which is a symptom naming the allocator instead of the construct.
        placed |= set(_callee_defs(functions))
        frame_slots = dict(getattr(fn, "_frame_slots", None) or {})
        holders = set(getattr(fn, "_frame_holders", None) or ())
        # A call's CALLEE is not a read of a value: it names a symbol, and a
        # callee this unit does not compile is a link-time fact rather than a
        # missing local. ONE loop below answers THREE of the four spellings of
        # that question, because several loops answering one question are free
        # to disagree about where the answer stops — and `M.iter_nodes` has no
        # parent, so a node can only be named again by its identity.
        #
        #   1. `f(…)` — a bare name. A callee this unit does not compile is a
        #      link-time fact rather than a missing local, and an un-compiled
        #      callee is the common case in a file that calls into a dylib.
        #   2. `mod.f(…)` — a module, which is the other spelling of a
        #      cross-module call and the only one `import mod` produces. The
        #      emitter answers the call from that module's own export table
        #      (see `ARM64Codegen._extern_symbol`). Without this the check
        #      refused `mod` — "is imported from `mod`, so it is a module-level
        #      name of another module" — for a call the emitter can already
        #      lower, which made `import mod` unusable and left
        #      `from mod import f` as the only spelling of a module call this
        #      path had. The refusal was worse than useless here: its own
        #      remedy sentence said "give it a function (a `struct.fn()` call
        #      lowers)", recommending the very spelling it refused.
        #      GATED on the root naming an imported module, and that gate is
        #      what makes this safe: a dotted call on anything else — a value's
        #      method (`xs.append`), a struct's field (`h.f.g`), a
        #      module-global table with no storage (`TABLE.lookup`) — keeps
        #      whatever answer it had, so this adds a spelling and changes no
        #      existing verdict. The gate admits a PACKAGE PREFIX of an
        #      imported name, not just an exact match: `import os.path` binds
        #      the name `os` — that is what Python does, and
        #      `os.path.join(…)` is 532 of the measured `os` call sites in this
        #      tree — while a name that is a dotted PREFIX of an import cannot
        #      be a value, because a local, a parameter and a module-global are
        #      all bare names and nothing in this language puts an attribute on
        #      one. The dotted qualifier itself is resolved by module identity
        #      further in (`_extern_symbol`), where the manifest says whether
        #      that submodule exports the name at all.
        #
        #      `struct.pack(...)` parses as `CallExpr(func=MemberExpr(obj=
        #      IdentExpr('struct'), member='pack'))`, so a test on `func` alone
        #      would miss it — the ROOT IdentExpr is what has to be collected,
        #      and only in CALLEE position: the same name in a genuine read
        #      (`len(struct)`) is still refused, which is the point — a module
        #      object has no storage either way, and what has no storage is the
        #      READ, not the call through it.
        #   3. `f[a, b](…)` — a SUBSCRIPT callee: a comptime SPECIALIZATION
        #      (`_horner_evaluate[coeffs](x)`, `plain[3](5)`) or a TYPE
        #      APPLICATION (`List[Int]()`, `Tuple[Int, Int]()`,
        #      `List[Self.T]()`). Both are one level up from case 1 and get the
        #      same answer: the bracket is that symbol's compile-time argument
        #      list and the base is the thing the call dispatches on, so
        #      neither the base nor anything in the bracket is a read of a
        #      value.
        #
        #      Specialization was the spelling the arm64 sweep reported for
        #      seventeen files: `std/sys/_assembly.mojo` writes
        #      `_get_kgen_string[asm]()`, and keying on
        #      `isinstance(func, F.IdentExpr)` alone missed every one of them,
        #      so the ROOT of the bracket was walked as if it were a read of a
        #      value and the file was told "'_get_kgen_string' is imported from
        #      std.collections.string.string_slice, so it is a module-level name
        #      of another module" — a storage problem the file does not have.
        #      The name is a CALLEE. What crosses the dylib boundary is the
        #      INSTANTIATION, and whether this path has a symbol for it is a
        #      question for the export rule and the linker, not for the
        #      allocator's local table; that question is asked where it belongs
        #      (see `_callee_defs` for the generic's base name, and the export
        #      rule in `no_public_api_reason` for what a generic can bind as).
        #
        #      The type application is the SAME shape with the SAME refusal, and
        #      it was the second-largest cause on the tree:
        #      `std/collections/binary_heap.mojo`'s
        #      `self._data = List[Self.T]()` was told "'List' has no home: the
        #      module-level symbol table is empty for this unit … the register
        #      allocator collected no home for it", and 79 of the 80 files the
        #      x86-64 sweep filed under that sentence were waiting on it.
        #      Every clause is false about the file: `List` is a TYPE, it is in
        #      none of the four places a value can be, and no amount of reading
        #      `_load_var` would have found anything.
        #      (`model.empty_blob_constructor` is what makes the zero-operand
        #      form ANSWERABLE and is asked by both backends; this exemption is
        #      only what stops the name-placement walk from refusing the callee
        #      before either of them is reached. A blob constructor WITH
        #      operands keeps its own refusal — a blob sized at layout time
        #      needs a frame reservation this compiler cannot size.)
        #
        #      `model.subscript_callee_names` is the ONE recogniser of the
        #      shape and it returns NODES, not names, because `iter_nodes` has
        #      no parent and the same spelling is a genuine read in a value
        #      position — `len(List)`, `var xs: List[Int]`. Exempting by NAME
        #      would exempt every read of `List` in the function, which is the
        #      silently-wrong direction this whole pass is arranged to refuse.
        #
        #      It is a CALL-SITE exemption, so `f(x)` where `f` is genuinely
        #      undeclared is unaffected (it was already exempt, and refuses
        #      downstream at the emitter's "this module does not compile" arm),
        #      and a type in a non-callee position keeps whatever answer it
        #      had. The `bracketed` scan below runs FIRST, so a construct
        #      refusal still wins over this: an MLIR template in CALLEE position
        #      is refused by name, and a specialization with no callee to bind
        #      the brackets to is refused by
        #      `model.specialization_call_refusal`. This loop never pre-empts
        #      either, in either direction.
        #   4. `external_call["setenv", Int32](…)` — a C symbol named by a
        #      string literal in the bracket, so `external_call` is left as a
        #      bare name with no home, and the bracket's second element is a
        #      type EXPRESSION (`Int32`, `_CPointer[UInt8,
        #      UntrackedOrigin[mut=False]]`) that is compile-time by
        #      construction and is not a read of a value either. This is the
        #      same AST shape as case 3 and it is NOT collected there, because
        #      it needs a well-formedness test of its own: only a WELL-FORMED
        #      template is exempt, and a malformed one still reaches the
        #      bracketed refusal below, which words the malformed template
        #      rather than a name-placement symptom. So case 4 has its own loop
        #      below, and the precedence is stated in the `elif` that skips it.
        #
        #      The type nodes are added rather than left to fall through
        #      because `'Int32' has no home` is a true statement about this pass
        #      and a useless one — it names an allocator table the reader has to
        #      go and look up instead of the subscript they wrote, and it was
        #      what every `external_call[…]` in the stdlib was reported as.
        #      `xc_callees` is the same set of templates, kept apart because
        #      the bracketed scan below needs the OPPOSITE answer for a
        #      template that is NOT a callee: `var x = external_call["sym", T]`
        #      is a template used as a value, and the name-placement message
        #      there names a symptom of this pass rather than the construct.
        #      `M.iter_nodes` has no parent, so "is this subscript a call's
        #      callee" is answerable here and nowhere else.
        callees = set()
        imported = imported_module_names or ()
        for c in M.iter_nodes(fn.body):
            if not isinstance(c, F.CallExpr):
                continue
            func = c.func
            if isinstance(func, F.IdentExpr):
                callees.add(id(func))
            elif isinstance(func, F.MemberExpr):
                # Case 2, through `model.dylib_module_reference` — the ONE
                # recogniser of "this chain is rooted at an imported module".
                # The gate was inline `any(root.name == m or m.startswith(...))`
                # before, and the member-read loop below asks the same question
                # about the same chains, so it lives in one function: that is
                # the only way the two cannot disagree about where the exemption
                # stops. Only the ROOT's identity is collected, because a
                # callee is a symbol and the emitter resolves the whole chain
                # from it (`ARM64Codegen._extern_symbol`).
                if M.dylib_module_reference(func, imported) is not None:
                    root = func
                    while isinstance(root, (F.MemberExpr, F.SubscriptExpr)):
                        root = root.obj
                    callees.add(id(root))
            elif not M.is_external_call_template(func):
                # Case 3. `elif`, not `if`: a SubscriptExpr callee that IS an
                # `external_call` template belongs to case 4, whose loop below
                # collects the well-formed ones and subtracts the malformed
                # ones back out again — so collecting it here would undo that
                # precedence and let a malformed template's type argument fall
                # through as a name with no home, which is the symptom the
                # subtraction exists to stop.
                for node in M.subscript_callee_names(c):
                    callees.add(id(node))
        # The same rule one level up, for a callee spelled with a BRACKET.
        # `external_call["setenv", Int32](…)` puts the C symbol in the bracket
        # and leaves `external_call` as a bare name with no home — but it is the
        # callee of a call, exactly as `_sym` above is, and a callee is not a
        # read of a value.  The bracket's second element is a type EXPRESSION
        # and is compile-time by construction, so it is not a read of a value
        # either — `Int32` is a type the module need not declare and there is no
        # local by that spelling to find.  Only a WELL-FORMED template is
        # exempt: a malformed one still reaches the bracketed refusal below with
        # a message about the template rather than a name-placement symptom.
        # Collected here rather than added to `name_resolves_without_a_local`
        # because that list is a statement about NAMES THAT HAVE A VALUE, and
        # `external_call` has none — it is a template, and the value the call
        # produces is the C function's, not this name's.
        #
        # `xc_callees` is the same set, kept apart because the bracketed scan
        # below needs the OPPOSITE answer for a template that is NOT a callee:
        # `var x = external_call["sym", T]` is a template used as a value, and
        # the name-placement message ("`external_call` has no home") names a
        # symptom of this pass rather than the construct.  `M.iter_nodes` has no
        # parent, so "is this subscript a call's callee" is answerable here and
        # nowhere else.
        xc_callees = set()
        for c in M.iter_nodes(fn.body):
            if not isinstance(c, F.CallExpr) \
                    or not M.is_external_call_template(c.func) \
                    or M.external_call_spec(c.func)[2] is not None:
                continue
            xc_callees.add(id(c.func))
            callees.add(id(c.func.obj))
            callees |= {id(n) for n in _external_call_type_nodes(c.func.index)}
        # …and the SAME rule the other way, because the general
        # `subscript_callee_names` exemption above knows nothing about
        # `external_call`: it exempts the root of ANY bracketed callee, which
        # includes a MALFORMED template's root — and the whole point of the
        # `external_call_spec(c.func)[2] is not None` guard is the opposite, so
        # that the template is refused by the bracketed scan below with the
        # sentence that names the construct ("declares its return type as
        # Scalar[dtype], and this path has no value of that kind …") rather
        # than falling through to whichever free name the function happens to
        # read next. Measured: without this, `check_module_symbols` reported
        # `'x' has no home` for
        # `external_call["sym", Scalar[dtype]](x)` — a true statement about
        # this pass and a useless one, since `x` is not what the reader wrote
        # and the unmodellable return type is.
        #
        # A subtraction rather than a guard in the general loop, because the
        # specific rule has to be stated where the reason for it is: the
        # general one is about `List[Int]()` and has no opinion here, and
        # whichever runs LAST wins a set, so saying it here is what makes the
        # precedence explicit instead of incidental.
        callees -= {id(c.func.obj) for c in M.iter_nodes(fn.body)
                    if isinstance(c, F.CallExpr)
                    and M.is_external_call_template(c.func)
                    and M.external_call_spec(c.func)[2] is not None}
        # A BRACKETED or DOTTED form has the same problem one level up:
        # `__mlir_attr[…]`, `__mlir_attr.`lit`` and
        # `__mlir_op.`lit.materialize_into`[value=v]` are a SubscriptExpr and/or
        # a MemberExpr rooted at a bare name, and that root on its own is just a
        # name with no home. The refusals that NAME the construct are asked
        # first, through the ONE reader both backends use, so the
        # better-worded message wins here rather than being pre-empted by the
        # symptom. Recorded by the identity of the ROOT IdentExpr, because
        # `M.iter_nodes` has no parent and the two spellings nest.
        bracket_callee_roots = _bracket_callee_roots(fn.body)
        bracketed = {}
        exempt_roots = set()
        first_mlir = None
        for sub in M.iter_nodes(fn.body):
            if isinstance(sub, F.IdentExpr):
                # `exempt_roots` is the OTHER half of the rule the arm below
                # states, and skipping it here would be reading one node two
                # ways inside one loop: an identifier that roots a sub-expression
                # that is not a use of anything is not an MLIR dialect construct
                # either. `_fold_target_queries` has normally
                # replaced those templates with literals before this runs, so the
                # set is empty in practice — and it is written down rather than
                # left to that, because the failure it prevents is a REFUSAL of
                # a construct this build answers, which is the worse of the two
                # mistakes available here.
                if first_mlir is None and id(sub) not in exempt_roots \
                        and sub.name.startswith(M.MLIR_DIALECT_PREFIX):
                    first_mlir = bracketed.get(id(sub)) \
                        or M.mlir_dialect_refusal(sub.name)
                continue
            if not isinstance(sub, (F.SubscriptExpr, F.MemberExpr)):
                continue
            if M.template_is_answered(sub):
                # Answered at build time, so nothing is left to refuse about it
                # and the tree below it is not a use of anything. The rewrite
                # (`_fold_target_queries`) has normally already replaced these
                # with literals before this check runs, so reaching here means
                # the rewrite did not cover this position — which is why the
                # condition is the shared `template_is_answered` rather than a
                # second opinion written beside it.
                continue
            root_ident = sub.obj
            while isinstance(root_ident, (F.MemberExpr, F.SubscriptExpr)):
                root_ident = root_ident.obj
            if not isinstance(root_ident, F.IdentExpr):
                continue
            # A TYPE APPLICATION in callee position — `Tuple[Int, Int]()`,
            # `List[Int]()` — is a construct both backends lower
            # (`empty_blob_constructor` in each `_emit_call`), and the
            # multi-element bracket on it is the type's own argument list, not
            # a two-dimensional index. So the tuple-index refusal is not asked
            # about it. The gate is here, in the `bracketed` computation, and
            # not in the placement loop below: the loop asks `bracketed`
            # BEFORE the callee exemption (that order is what lets a template
            # root be refused by name instead of through its type argument),
            # so a root recorded here is refused unconditionally — and with
            # the loop's original order the same case was fine, which is
            # exactly the kind of coupling that makes one branch's ordering
            # change another's verdict. Measured: `Tuple[Int, Int]()` built
            # and printed 0 before, and was refused with "`Tuple[Int, Int]` is
            # a subscript whose index is a tuple" after.
            type_application = (isinstance(sub, F.SubscriptExpr)
                                and id(root_ident) in bracket_callee_roots
                                and M.empty_blob_constructor(root_ident.name))
            why = M.mlir_template_refusal(sub)
            if why is None and isinstance(sub, F.SubscriptExpr) \
                    and not type_application:
                why = M.multi_index_refusal_for(sub, False,
                                                _callee_defs(functions),
                                                structs_by_name)
                if why is None and M.is_external_call_template(sub) \
                        and id(sub) not in xc_callees:
                    # A well-formed template that is not a call's callee: a
                    # template read as a VALUE.  `multi_index_refusal_for`
                    # cannot see it (no parent), and without this the name
                    # would fall through to the placement message below, which
                    # says `external_call` has no home — a true statement about
                    # this pass and a useless one, because the file is not
                    # missing a variable, it is using a call as a subscript.
                    why = M.external_call_value_refusal(
                        M.external_call_spelling(sub))
            if why is None and isinstance(sub, F.MemberExpr):
                # The dotted spelling can also be the base of a bracket, and
                # `std/builtin/value.mojo` spells an MLIR template exactly
                # that way (`__mlir_op.`lit…`[value=value]`), so the SUBSCRIPT
                # is asked about the dotted chain it wraps.
                for outer in M.iter_nodes(fn.body):
                    if isinstance(outer, F.SubscriptExpr) \
                            and outer.obj is sub:
                        why = M.mlir_template_refusal(outer)
                        if why is None:
                            why = M.multi_index_refusal_for(
                                outer, False, _callee_defs(functions),
                                structs_by_name)
                        break
            if why is None and isinstance(sub, F.SubscriptExpr) \
                    and id(root_ident) in bracket_callee_roots:
                # A BRACKETED CALLEE this unit does not compile. Asked HERE,
                # which is where the other construct refusals are asked and for
                # the reason the order below documents: the refusal that names
                # the construct wins over one about the boundary it crosses,
                # because the boundary is a consequence of the brackets rather
                # than the other way round.
                #
                # This is the ONE place the two branches' answers to the same
                # construct meet. `imported_callee_refusal` (below) refuses the
                # same call because the defining module exports no single
                # symbol for a generic — true, and the right sentence when the
                # base name is a `_`-prefixed or generic template. It is the
                # WRONG sentence for a name the module does export, which
                # `plain[3](5)` is: the report told the reader "`lib` does not
                # export it … a C library name like `exit` or `write`", about a
                # `plain` the module exports perfectly well, and the reader has
                # no way to tell which of the four reasons applies to their
                # name. `specialization_call_refusal` asks the question that
                # both shapes share — there is no callee here to pass the
                # brackets to — and it is the one both backends already ask at
                # `_emit_call`, so this hoists the answer rather than adding
                # one. `imported_callee_refusal` keeps the case it is right
                # about: a bracketed callee whose base name is not a function
                # here for any OTHER reason, which is what is left after this.
                # The three exclusions are the three bracketed callees this tree
                # already has a BETTER answer for, and asking here without them
                # replaced all three: `List[Int]()` with
                # `specialization_call_refusal` (it is the one bracketed callee
                # both backends lower, and the arm that lowers it is
                # `empty_blob_constructor` below); an MLIR dialect subscript with
                # it (the dialect refusal further down names the construct,
                # which is the whole point of it); and an `external_call`
                # TEMPLATE with it, which is the sharpest of the three — the
                # template is not a specialization at all, it is a call to a C
                # symbol with a declared return type, it is lowered, and
                # `multi_index_refusal_for` above already answers for it.
                # Measured: without the third, 9 of
                # `test_formal_external_call.py`'s 29 cases were refused as
                # "calls a name this unit does not compile", naming
                # `external_call`. A construct refusal asked here has to be the
                # LAST one, not the first.
                #
                # `root_ident.name` and not `model.subscript_callee_name`:
                # that one takes the CALL, and `iter_nodes` hands this loop the
                # subscript with no parent to find the call through. Membership
                # in `bracket_callee_roots` is what established that this root
                # IS a call's bracketed base, so the name is the base name by
                # that fact rather than by asking again.
                base_name = root_ident.name
                if (base_name not in _callee_defs(functions)
                        and not M.empty_blob_constructor(base_name)
                        and not base_name.startswith(M.MLIR_DIALECT_PREFIX)
                        and not M.is_external_call_template(sub)
                        and not M.debug_assert_callee(sub)):
                    why = (M.ambiguous_method_specialization_refusal(
                        M.member_chain_text(sub.obj), sub.obj.member,
                        _ambiguous_method_owners(sub.obj, structs_by_name))
                        if _ambiguous_method_owners(sub.obj, structs_by_name)
                        else M.specialization_call_refusal(base_name))
                elif M.debug_assert_callee(sub):
                    # The FOURTH bracketed callee this tree has a better answer
                    # for, and it is a different KIND of answer from the three
                    # above rather than a fourth spelling. `debug_assert` is a
                    # builtin of the LANGUAGE, so its declaration is a fact
                    # about the language rather than something this image has to
                    # compile — which is exactly the premise
                    # `specialization_call_refusal` states and then says there
                    # is none in hand. Left in, it refused all 28 bracketed
                    # `debug_assert` call sites in the new-modular stdlib with
                    # a message about generics and monomorphization, none of
                    # which is what those call sites are.
                    #
                    # Asked through `M.debug_assert_bracket_refusal`, the ONE
                    # reader both backends ask, so a bracket this path cannot
                    # account for is still refused rather than dropped here and
                    # answered there — a dropped bracket is the
                    # `plain[3](5)` → `plain(5)` image this whole scan exists
                    # to prevent.
                    why = M.debug_assert_bracket_refusal(sub)
            if why is not None:
                bracketed[id(root_ident)] = why
        # A BRACKETED CALLEE, `f[x](...)`, is a comptime SPECIALIZATION of `f`
        # and so a call, as much as a bare `f(...)` is — and the bare form is
        # already exempt above, which is why this shape was left out of that
        # set and reached the module-global refusal below. It is NOT added to
        # `callees` here, and that is deliberate: a name this module's export
        # rule keeps off the boundary (a leading `_`, a generic template — the
        # two together are `std/sys/_assembly.mojo`'s
        # `_get_kgen_string[asm]()`, nineteen swept files' worth) has no symbol
        # for the call to bind however the name check treats it, so the honest
        # answer is a refusal that says THAT, not one that lets the call
        # through to a dangling `BL` and a link-audit message about a symbol
        # the reader has to go and look up. The two construct refusals above
        # are asked first, so an MLIR template in callee position is still
        # refused by name — the message here is about the EXPORT, and a
        # template that is not exported is two different facts.
        bracket_callees = _bracket_callee_roots(fn.body)
        bracket_callees -= set(bracketed)
        # A dotted READ of an imported module — `sys.argv`, `os.path.join` in a
        # value position, `len(sys.argv)` — is the same construct as the dotted
        # CALL above, asked one question later, and before this it was refused
        # for a reason that was FALSE about it.
        #
        # The callee exemption collects the ROOT of a dotted call and lets the
        # emitter resolve the chain; nothing collected the root of a dotted READ,
        # so the placement walk below reached the root `sys` as a free name and
        # answered `module_global_refusal` — "'sys' … is a module-level name of
        # another module … there is no storage for one here". `sys` is not a
        # module-level name of `sys`; `sys` IS the module, and a module is not a
        # value with nowhere to live, it is the library on the link line with a
        # manifest. The name that has no representation is the ATTRIBUTE
        # (`sys.argv`), which is what the new message says and what the old one
        # did not. Measured on this tree: all six files the work map's row
        # "a module-level name of ANOTHER module is not exported as a word"
        # blocks — `t_argv.mojo`, `mojo.mojo`, `tools/ab_filelist.py`,
        # `tools/audit_determinism.py`, `tools/ci_line.py`, `tools/detach.py` —
        # name `sys`, on BOTH architectures, three at `main:` and three at
        # `__module_body__:`.
        #
        # The root is exempted and the MEMBER is refused, and both halves are
        # load-bearing. Exempting the root alone would be a silently wrong
        # answer rather than a failure: `ARM64Codegen._emit_expr` on
        # `MemberExpr(IdentExpr('sys'), 'argv')` finds no frame slot for
        # `"sys.argv"` and falls to its "no object model, so the field itself
        # reads as 0" arm, evaluating `_load_var('sys')` and emitting `#0` —
        # `print(sys.argv)` would print 0 and exit 0. So the member refusal is
        # raised for EVERY rooted chain, before the placement walk skips the
        # root, and the two cannot be separated.
        #
        # Collected by node IDENTITY of the root, never by name, for the reason
        # the rest of this function repeats: `iter_nodes` has no parent, the same
        # spelling is a module root in one position and a genuine local in
        # another (`import os` plus a parameter named `os` shadows it), and
        # keying on the string would exempt every read of that name in the
        # function — the silently-wrong direction this whole pass is arranged to
        # refuse. `_apply_imported_constant_sites` has already substituted a
        # published CONSTANT by this point (`_publish_imported_constants` runs
        # before these checks), so a chain that survives to here names a module
        # attribute the module does not publish as a value.
        module_reads = {}
        if imported:
            # Every `MemberExpr` on the SPINE of a call's callee — `os.path` as
            # well as `os.path.join` in `os.path.join("a", "b")`. Collected by
            # walking each dotted callee down to its root, which is the same walk
            # the callee exemption does, because it is the same question: is
            # this link part of a SYMBOL the emitter resolves, or a value being
            # read? `callees` cannot answer it — it records only the chain's
            # ROOT — and `iter_nodes` has no parent, so this is the only place
            # that can. Measured, and this is the second version: skipping only
            # the outermost `MemberExpr` refused `os.path.join(…)`, a program
            # that builds on master, because `os.path` is the callee's object.
            dotted_callees = set()
            for c in M.iter_nodes(fn.body):
                if not isinstance(c, F.CallExpr) \
                        or not isinstance(c.func, F.MemberExpr):
                    continue
                link = c.func
                while True:
                    dotted_callees.add(id(link))
                    if not isinstance(link, F.MemberExpr):
                        break
                    link = link.obj
            for sub in M.iter_nodes(fn.body):
                if not isinstance(sub, F.MemberExpr):
                    continue
                # A CALL through the chain is the callee exemption's business
                # and the emitter already resolves it from the module's export
                # table; `_extern_symbol` refuses a name the module does not
                # publish, with a message that already lists what it does
                # publish. Asking about it here too would pre-empt that with
                # this one — and would REFUSE programs that build today, which
                # is how both versions of this arm were caught. Every link on
                # the callee's spine is skipped, `os.path` included: the spine
                # is `dylib_export_module`'s question, not this one's.
                if id(sub) in dotted_callees:
                    continue
                root_name = M.dylib_module_reference(sub, imported)
                if root_name is None:
                    continue
                # A LOCAL of this function shadows an imported module name, and
                # a local's attribute read is a frame slot, not a module
                # attribute — `def main(os): os.argv` is a parameter read. The
                # callee exemption has the same shadowing hole and is not
                # changed here; this arm must not widen it.
                if root_name in placed or root_name in frame_slots:
                    continue
                root = sub
                while isinstance(root, (F.MemberExpr, F.SubscriptExpr)):
                    root = root.obj
                if id(root) in bracketed:
                    continue
                leaf = sub.member
                module_reads[id(root)] = M.module_attribute_refusal(
                    M.member_chain_text(sub), root_name, leaf, fn.name,
                    _module_published_names(root_name, link_line))
        # A TYPE name in a VALUE position is a compile-time constant whose value
        # is the type's TAG, so it has a home — the same one a folded
        # module-level constant has, which is the fourth of the four this walk
        # already accepts, and both backends materialise it where they
        # materialise the others. `bugs/FORMAL_type_name_as_a_value.md` is the
        # long form; `model.TYPE_VALUE_NAMES` is the name space and
        # `model.type_value_tag` the one reader both backends ask, so the two
        # architectures cannot disagree about what a type is.
        #
        # `DType.<member>` is collected FIRST and by node identity, because
        # `iter_nodes` has no parent and the walk only ever sees the `DType`
        # IdentExpr: the value there is the MEMBER's tag, not the tag of a type
        # called `DType`, so the base is placed as part of the member rather
        # than as a name in its own right. A member with no tag (the float8
        # family) is refused HERE, by the member's name, so that the two
        # diagnostics that are about types stay apart: a bare `DType` is the
        # type OF a type and `model.dtype_object_refusal` says so.
        dtype_members = {}
        for sub in M.iter_nodes(fn.body):
            if M.is_dtype_member_access(sub):
                dtype_members[id(sub.obj)] = sub.member
        # A name that is the BASE of a subscript is not read as a value, and
        # this is the case that says so. `List[Self.T]()` and
        # `rebind[Scalar[dtype]](…)` are type APPLICATIONS — the bracket is the
        # type's argument list and the base names the symbol the call dispatches
        # on — so the base has no tag, and asking `type_value_tag` about it
        # would hand `List` a value and let this walk walk past the one question
        # it should be asking. Measured: with the tag asked unconditionally,
        # `std/collections/binary_heap.mojo` stopped being refused at
        # `BinaryHeap___init__: 'List' has no home` and its next refusal moved
        # to a LATER FUNCTION, which is the signature of a construct that has
        # stopped being examined rather than one that has been answered. Whether
        # a bracketed callee is answerable is a different question with its own
        # answer (`model.subscript_callee_names`), and this arm must not
        # pre-empt it in either direction.
        subscript_bases = set()
        for sub in M.iter_nodes(fn.body):
            if isinstance(sub, F.SubscriptExpr) and isinstance(sub.obj, F.IdentExpr):
                subscript_bases.add(id(sub.obj))
        # The MLIR refusal is raised BEFORE the name-placement walk below, not
        # inside it, and the order is the point: the walk answers "this name has
        # no home", which is TRUE of a dialect root and useless to a reader
        # holding a file whose real problem is that it asked for an MLIR
        # construct this build cannot assemble.  `first_mlir` is computed above
        # for exactly this purpose.  The walk's own dialect arm is GONE rather
        # than kept as a second opinion: the same reader asked the same question
        # twice is how two architectures and two call sites come to name
        # different limits for one construct, and an arm that cannot run would
        # read as support for a shape that does not work.
        if first_mlir is not None:
            raise CodegenError(
                f"{fn.name}: {first_mlir}" if fn.name else first_mlir)
        for node in M.iter_nodes(fn.body):
            if not isinstance(node, F.IdentExpr):
                continue
            # `bracketed` is asked BEFORE the callee exemption, and the order
            # is load-bearing rather than tidiness. A construct refusal is
            # about the whole expression — `external_call['setenv', Int32]`
            # assembles a two-element subscript, and `Int32` inside it is a
            # TYPE ARGUMENT rather than a read of a value. Skipping a callee
            # root without asking first made the type argument the reported
            # failure, which names an allocator table the reader has to go and
            # look up instead of the subscript they wrote; measured, it
            # replaced the tuple-index refusal on every `external_call[…]` in
            # the stdlib with `'Int32' has no home`.
            if id(node) in bracketed:
                raise CodegenError(bracketed[id(node)])
            # The module-attribute refusal, asked HERE and before the callee
            # exemption, for the same reason `bracketed` is: the message that
            # names the CONSTRUCT wins over the one about the root's storage.
            # `sys.argv` used to be reported as a placement failure of `sys` —
            # "'sys' … there is no storage for one here" — which is a claim
            # about a name that is not a value; this names the attribute the
            # source actually wrote. `test_formal_module_attr.py` case 4 (a
            # module OBJECT still has no storage) is unaffected and is the test
            # that would catch this exemption widening past a member chain.
            if id(node) in module_reads:
                raise CodegenError(module_reads[id(node)])
            if id(node) in callees:
                continue
            name = node.name
            if name in placed or name in frame_slots \
                    or M.module_constant_literal(name) is not None \
                    or M.name_resolves_without_a_local(name):
                continue
            member = dtype_members.get(id(node))
            if member is not None:
                if M.dtype_member_is_a_type(member):
                    continue
                raise CodegenError(M.dtype_member_refusal(name, member))
            if id(node) not in subscript_bases \
                    and M.type_value_tag(node) is not None:
                continue
            if name == "DType":
                # The one type name that is not a type as a value. Asked here
                # rather than left to the fallback below, because the fallback's
                # sentence — "no local or parameter by that spelling … read out
                # of whatever register the allocator left behind" — is false
                # about it: there is no register question here at all. AFTER the
                # local check above, so a function that binds its own `DType`
                # still reads its own.
                raise CodegenError(M.dtype_object_refusal(name))
            if "." in name and name.split(".", 1)[0] in holders:
                continue
            if name.startswith(M.MLIR_DIALECT_PREFIX):
                # An MLIR DIALECT construct no template rule covers — see
                # `model.mlir_dialect_refusal` for why naming it beats the
                # fallback's "no home", which names a symptom of the register
                # fall-through and sends the reader to the allocator instead of
                # to the construct.
                why = M.mlir_dialect_refusal(name)
                raise CodegenError(f"{fn.name}: {why}" if fn.name else why)
            gslot = M.module_slot(name)
            if gslot is not None:
                # A module-level name WITH a `__DATA` slot: the storage exists
                # and both backends lower a read of it to a load, so it is
                # placed — unless the slot has no initializer, in which case the
                # load would read the zero an unwritten slot gives. That is a
                # plausible-looking wrong number rather than a refusal, so it is
                # refused by name with the reason the initializer is missing.
                why = M.static_initializer_refusal_reason(gslot)
                if why is not None:
                    raise CodegenError(
                        M.global_value_refusal(name, fn.name, why))
                continue
            sym = M.module_symbol(name)
            # A TYPE read as a value is the same kind of misdirection as the
            # MLIR dialect above, and it is asked in the same place for the same
            # ordering reason: `unresolved_name_refusal` enumerates where a NAME
            # lives — a register, a spill slot, a receiver field's frame, a folded
            # module constant — and a type is in none of those because a type is
            # not a value, so that sentence is false about the file and sends
            # the reader to the register allocator for a fact about the
            # language. The census behind this is in
            # bugs/FORMAL_type_name_as_a_value.md.
            #
            # Asked AFTER the module-symbol question, not before, and the
            # ordering is not a compromise — it is what the measurement forced.
            # Asking it first moved two stdlib files off the module message:
            # `bench_set.mojo` (`Set`) and `list_strategy.mojo` (`List`), both
            # `from std.collections import …`. Their message is not a symptom,
            # it is MORE specific, and it carries a backtick-quoted module name
            # that `tools/formal_sweep.py` reads to file the verdict as
            # `not-answerable/unresolved-import` — so pre-empting it with a
            # message that has no module name in it silently reclassifies those
            # two files in the sweep's own accounting. So for a name that is
            # BOTH, both facts are said.
            if sym is not None and M.is_type_name(name):
                # The construct first, then the module fact, indented so the
                # two read as two sentences rather than one run-on — and with
                # the module message's own `fn:` prefix suppressed, since this
                # half already carries it.
                raise CodegenError(
                    M.type_as_value_fact(name, fn.name) + "  "
                    + M.module_global_refusal(name, sym, ""))
            if sym is not None:
                if id(node) in bracket_callees \
                        and getattr(sym, "site", None) == "imported":
                    # A CALL to a name this module does not export, which is a
                    # fact about the boundary and not about storage — see the
                    # `bracket_callees` note above for why this is refused here
                    # rather than allowed to reach a dangling `BL`.
                    raise CodegenError(M.imported_callee_refusal(
                        name, sym, fn.name))
                # A module-level name with no slot, refused for the reason a
                # module-level name is refused: nothing writes it, so its value
                # is the module-level one, and the build can only know that if
                # it folds to a literal — and there is no storage with a
                # lifetime longer than a frame's for the rest.
                # `model.module_global_refusal` says which of the four kinds it
                # is, because the four have four different repairs.
                raise CodegenError(M.module_global_refusal(name, sym,
                                                           fn.name))
            raise CodegenError(M.unresolved_name_refusal(
                name, fn.name, _why_unplaced(node, fn, frame_slots)))
        _refuse_variadic_reads(functions, fn, shape)
        unstored.append(_unstored_read(fn, placed, frame_slots))
    # Raised LAST, and that ordering is the design rather than an accident of
    # where the call landed. A read-before-store is a SYMPTOM — the name has a
    # home and the program reads it before filling it — and this module
    # already has refusals that name the CAUSE, which are the ones a reader
    # can act on. Two real cases, both measured on the stdlib, where raising
    # this one first replaced a better message with a worse one:
    #
    #   std/algorithm/backend/tile.mojo:77  a `comptime for` over the
    #     `*args` of the enclosing function, which is the variadic-ABI
    #     refusal's exact case and was replaced by "'tile_size_list' is read
    #     at line 77 before anything in this function stores it".
    #   std/math/polynomial.mojo:86  a `comptime` binding that does not
    #     fold, whose own refusal says what to do about it ("make the
    #     initializer a literal … or bind it with an ordinary `var`"), and
    #     which was replaced by a message about a name that is a PARAMETER
    #     of the generic.
    #
    # So: same rule the rest of this function already follows for the MLIR
    # and multi-index refusals — the diagnostic that NAMES THE CONSTRUCT is
    # asked first, so the better-worded message wins rather than being
    # pre-empted by a symptom of it. A caller that gets this refusal has
    # therefore been told about everything that could be said more precisely.
    for hit in unstored:
        if hit is not None:
            name, line, fn_name = hit
            raise CodegenError(M.read_before_store_refusal(name, fn_name,
                                                           line))


def _unstored_read(fn, placed: set, frame_slots: dict):
    """`(name, line)` for a name this function reads before anything in it
    stores, or None.

    The second question about a name's storage, asked beside the first one
    (`check_module_symbols`) and deliberately not folded into it. The first
    asks "does this name have a HOME"; this one asks "does it have a VALUE at
    this read", and a name can answer yes and still be wrong: the allocator
    gives a register to every name the function assigns somewhere, so a name
    read before its first store has a perfectly good home holding whatever
    the CALLER left in it. The value is then not merely incorrect but
    BUILD-DEPENDENT — the same source gave -157679357 on one arm64 build and
    -157679350 on another, and 240046802 on x86-64 — which is what makes it a
    finding rather than a cosmetic issue.

    `placed` is passed rather than recomputed, and it is the SAME set the
    walk above consults, for the reason the docstring there gives about not
    folding the two questions together: that set answers "has a home", and a
    check that made it answer "has a value" would be false about files that
    are fine. Names outside it — no home at all — stay that other check's
    refusal, which names the better problem.

    `frame_slots` names are excluded for the same reason they are excluded
    there: a frame slot is placed by a CONSTRUCTOR, and whether the
    constructor has run is not a question a name walk can answer.

    Returns rather than raises, because of where it is called from — see the
    ordering note at the call site.
    """
    # `M.incoming_args`, not `fn.params`: a generic's `[dtype: DType]`
    # parameters are leading ARGUMENTS and this walk used `fn.params`, which
    # does not carry them, so `def widen[x: Int32](v: Int32): return v * x`
    # was refused for reading `x` before anything in the function stores it —
    # the read is of a value the CALLER passed, which is the same reason a
    # runtime parameter is excluded and the same sentence in the docstring
    # above. Measured: `test_formal_specialization.py`'s
    # `a_local_specialization_lowers_and_matches_cpython` builds on this tree
    # and did not. One reader of "the names a call site binds", and it is the
    # one the ABI itself is written against.
    params = {name for name, _ptype in M.incoming_args(fn)}
    # Only names this function ITSELF binds can be unstored: a parameter is
    # stored by the caller, and everything else in `placed` is stored by
    # something this walk does not see.
    own = placed - params - set(frame_slots)
    if not own:
        return None
    hit = M.read_before_store(fn, params, own)
    return None if hit is None else (hit[0], hit[1], fn.name)


def _external_call_type_nodes(index) -> list:
    """Every node of an `external_call[...]` bracket's TYPE argument.

    The template's second element is a type EXPRESSION — `Int32`,
    `_CPointer[UInt8, UntrackedOrigin[mut=False]]` — so it is compile-time by
    construction and the name-placement pass must not read it as a runtime
    name.  Returns `[]` for the one-element bracket, where there is no type
    argument at all, and is only ever called for a WELL-FORMED template
    (`external_call_spec` with no `why`), which is exactly the set of brackets
    whose second element `type_expr_text` could render — so no node it returns
    is a value read."""
    items = list(index.elements) if isinstance(index, F.TupleExpr) else [index]
    if len(items) < 2:
        return []
    return list(M.iter_nodes(items[1]))


def _callee_defs(functions: list) -> dict:
    """`{name: FunctionDef}` for the whole image, for the multi-index reader.

    `M.multi_index_refusal_for` consults it only to recognise a generic's
    explicit-parameter list (`pick[1, 2]`), and an unknown callee falls through
    to the tuple-index refusal, which is still true of it."""
    return {fn.name: fn for fn in functions
            if isinstance(getattr(fn, "name", None), str)}


def _comptime_bound_names(fn) -> set:
    """Names bound as compile-time constants, and a generic's `comptime_params`.

    Three places, because a `comptime` binding is a compile-time value in all
    of them and the backends resolve all of them — `_bind_comptime` folds the
    value into `_comptime_vals` and `_emit_comptime_read` materializes it at
    the read, and a generic's `[dtype: DType]` parameters are leading
    arguments. A `comptime for` TARGET is the third, and it is the one real
    stdlib source uses most: `std/gpu/host/tile.mojo:77` is
    `comptime for tile_size in tile_size_list:` and `tile_size` is a name
    bound by that statement and by nothing else.
    `limit_comptime_over_a_runtime_parameter` is the case the first covers:
    `comptime num_coefficients = len(coefficients)` does not fold, and the
    message that says so is the backend's, not this one's."""
    out = set(getattr(fn, "comptime_params", None) or ())
    for node in M.iter_nodes(getattr(fn, "body", None) or []):
        kind = type(node).__name__
        if kind not in ("ComptimeVarStmt", "ComptimeForStmt"):
            continue
        t = getattr(node, "target", None)
        if isinstance(t, str):
            out.add(t)
        elif isinstance(t, F.IdentExpr):
            out.add(t.name)
        elif isinstance(t, (F.TupleExpr, F.ListExpr)):
            for el in getattr(t, "elements", None) or []:
                if isinstance(el, F.IdentExpr):
                    out.add(el.name)
    return out


def _why_unplaced(node, fn, frame_slots: dict) -> str:
    """The evidence this check had, in words, for `node`'s name.

    Passed to the message rather than recomputed there, so the message cannot
    claim a reason nobody checked — which is the failure mode a diagnostic
    written away from its evidence always has."""
    sym = M.module_symbol(node.name)
    if sym is not None:
        return (f"it is a module-level name of this module "
                f"({sym.site}), and its value is not one the build can fold")
    if M.module_symbols():
        return ("this module declares no module-level name by that spelling, "
                "and the reading function declares no local or parameter by "
                "it either")
    return ("the module-level symbol table is empty for this unit, and the "
            "reading function declares no local or parameter by that "
            "spelling")


def _refuse_variadic_reads(functions: list, fn, shape) -> None:
    """Refuse a body that reads its `*args` / `**kwargs` parameter.

    The caller side is already correct and needs no change: `_bind_call_args`
    passes the fixed parameters and drops the rest, which is exactly what a
    variadic callee that ignores its variadic parameter does. The hole is the
    read. `def f(x, *rest): return rest[2]` called `f(1, 2, r)` was read as
    three fixed parameters, so `rest` was parameter 1 and index 2 had no
    parameter at all — measured on both architectures, the program built and
    died with SIGSEGV. It is refused here, by name, with the reason, rather
    than left to a register or a bound check.

    `del` of one and a re-binding of one are not reads and are not refused."""
    if not shape.variadic:
        return
    starred = {shape.vararg: False, shape.kwarg: True}
    starred = {k: v for k, v in starred.items() if k}
    if not starred:
        return
    present = set()
    for node in M.iter_nodes(fn.body):
        if isinstance(node, (F.AssignStmt, F.AugAssignStmt, F.VarDecl)):
            t = getattr(node, "target", None)
            if isinstance(t, F.IdentExpr) and t.name in starred:
                present.add(t.name)
        if isinstance(node, F.DelStmt):
            for t in getattr(node, "targets", None) or []:
                if isinstance(t, F.IdentExpr) and t.name in starred:
                    present.add(t.name)
    note = _variadic_call_note(functions, fn, shape)
    for node in M.iter_nodes(fn.body):
        if isinstance(node, F.IdentExpr) and node.name in starred \
                and node.name not in present:
            raise CodegenError(M.variadic_read_refusal(
                fn.name, node.name, starred[node.name], note))


def _variadic_call_note(functions: list, fn, shape) -> str:
    """How many arguments the callers of `fn` pass past the fixed parameters.

    Read from the image's call sites where there is one, and stated as a range
    when the callers disagree, because the count is the fact that makes the
    refusal concrete: `f(1, 2, r)` against `def f(x, *rest)` is three
    arguments for one fixed parameter."""
    fixed = len(shape.fixed)
    counts = set()
    for other in functions:
        for node in M.iter_nodes(getattr(other, "body", None) or []):
            if not isinstance(node, F.CallExpr) or not isinstance(
                    node.func, F.IdentExpr):
                continue
            if node.func.name != fn.name:
                continue
            counts.add(len(node.args or []))
    if not counts:
        return (f"the call may pass any number, against {fixed} fixed "
                f"parameter(s)")
    lo, hi = min(counts), max(counts)
    return (f"this module's call sites pass {lo}..{hi} argument(s), against "
            f"{fixed} fixed parameter(s)")





# The AST fields that hold a TYPE rather than a value, so that a rewrite which
# substitutes VALUES knows where not to go.  `VarDecl.type_ann` and
# `AssignStmt.type_ann` are `x: T`, `FunctionDef.return_type` is `-> T`, and a
# parameter's annotation is a STRING inside `FunctionDef.params[i][1]` (so there
# is nothing to substitute there and nothing to skip either — a table of names
# rather than a set of node types is what keeps that from drifting).
#
# Read by `_apply_constant_sites`, whose sites table gained the receiver
# spellings and with them the possibility of a read in one of these positions.
#
# NOT read by `_apply_module_constant_sites`, which is the other
# value-substituting walk here and has the same shape of question.  Left alone
# deliberately: that walk is parent-directed (a store target and a callee name
# are only identifiable from the parent), its sites are a table of NAMES rather
# than of member reads, and a module-level constant in an annotation is a
# different exposure with its own measurement.  Widening it from here would be a
# change nobody measured, and this table is here because a reader of one
# substitution needs to know about the other.
_TYPE_POSITION_FIELDS = frozenset({"type_ann", "return_type", "annotation"})

def _first_unanswerable_mlir(value):
    """The first MLIR template in `value` this build cannot answer, or None.

    One walk and one reader, and both are the ones the rest of this path uses:
    `model.iter_templates_preorder` (which is how
    `refuse_module_level_mlir_templates` finds the templates in a module-level
    binding's initializer) and `model.mlir_template_refusal` (which answers a
    `#kgen.param.expr<…>` target query this build knows and refuses the rest, so
    a binding that asks the target a question is NOT caught here).

    It exists because the two questions meet on one construct: a `comptime` class
    attribute whose value is an MLIR template. `utils/numerics.mojo`'s
    `FPUtils.integral_type` and `memory/pointer.mojo`'s `_Null._mlir_type` are
    two, and without this the read is refused as "not a literal" — which drops a
    refusal that named the MLIR construct onto one that does not, and sends the
    reader to a literal the file does not contain."""
    if value is None:
        return None
    for node in M.iter_templates_preorder(value):
        if M.mlir_template_refusal(node) is not None:
            return node
    return None





def _apply_constant_sites(node, sites: dict, disputed: dict = None):
    """The substitution itself, over a statement tree, in place.

    Split from `_rewrite_class_constants` so the sites can be computed once per
    function: they are a census of the whole body, and recomputing them at every
    node would be quadratic in the size of the function.

    A TUPLE is descended into and REBUILT, for the reason
    `_apply_module_constant_sites` gives at length: `IfStmt.elifs` is a list of
    `(condition, body)` pairs, so without this the class-constant rewrite covered
    `if p.B == 1:` and skipped `elif p.B == 1:` — the same one-position gap, in
    the second of the two walks that share it.

    A TYPE POSITION is skipped whole, and that is a correctness fix rather than a
    politeness: `var _value: Self._mlir_type` in `std/builtin/none.mojo` is a
    read of a `comptime` binding in an ANNOTATION, and an annotation is not
    evaluated on this path — `struct_field_names`, `annotation_base_name` and
    `struct_field_declared_type` read the SPELLING. Substituting there would put
    the integer 3 where the source wrote a type (`var _v: 3`) and refuse on the
    next one (`NoneType._mlir_type` is not a literal, so it would have taken
    `builtin/none.mojo` — measured, one of only two stdlib files that build at
    all and has a struct-body MLIR binding — from BUILDS to REFUSED). The
    positions are the three field names an annotation can arrive in, and the list
    is a table rather than a shape test because the shape test would have to know
    every node that carries one.

    The refusal names the SPELLING the source wrote, not the struct's own name:
    a reader who wrote `res._InjectedValues` is looking at that line, and a
    message about `_ZipIterator._InjectedValues` sends them to the declaration
    they had already found. The two kinds are named apart as well, because a
    `comptime` binding is not a class-level assignment and the remedy differs
    (a binding's value is often a COMPUTATION, which no amount of writing the
    result at the use site can fix — the binding itself has to become a
    literal)."""

    if isinstance(node, (list, tuple)):
        items = [_apply_constant_sites(x, sites, disputed) for x in node]
        if isinstance(node, tuple):
            return tuple(items)
        node[:] = items
        return node
    if isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr):
        why = (disputed or {}).get(f"{node.obj.name}.{node.member}")
        if why is not None:
            raise CodegenError(why)
        got = sites.get(f"{node.obj.name}.{node.member}")
        if got is not None:
            st, kind = got
            if kind == "overridden":
                raise CodegenError(_overridden_comptime_refusal(
                    st, node.member, f"{node.obj.name}.{node.member}"))
            literal, default = _constant_literal(st, node.member)
            if literal is None:
                spelling = f"{node.obj.name}.{node.member}"
                declared = (f"a `comptime` class attribute" if kind == "comptime"
                            else f"a class-level constant")
                mlir = _first_unanswerable_mlir(default)
                if mlir is not None:
                    raise CodegenError(
                        f"{spelling} reads {declared} of {st.name}, whose value "
                        f"is an MLIR construct: "
                        f"{M.mlir_template_refusal(mlir)} It is reached "
                        f"through the binding rather than in a function body, "
                        f"which is why the expression walk that refuses MLIR "
                        f"templates does not see it: that walk runs over "
                        f"FUNCTION bodies and over module-level bindings "
                        f"(`model.refuse_module_level_mlir_templates`), and a "
                        f"struct body's `comptime` binding is neither — so the "
                        f"refusal is asked here, at the read, which is where the "
                        f"construct is fatal.")
                reason = (f"a `comptime` binding's value is written in the class "
                          f"body and is often a CALL or a COMPUTATION rather "
                          f"than a literal, and this path has no comptime "
                          f"evaluator to run one"
                          if kind == "comptime" else
                          f"a class-level constant's value is written in the "
                          f"class body, and this path has no module-global "
                          f"storage to read it back out of")
                spelled = (M.expr_spelling(default)
                           if default is not None else "nothing at all")
                raise CodegenError(
                    f"{spelling} reads {declared} of {st.name}, whose value is "
                    f"`{spelled}` — and a formal value is one 64-bit word with "
                    f"nowhere to keep a non-literal one: {reason}. Write the "
                    f"value at the use site (a literal, or an assignment the "
                    f"compiler can see), which is the same program with a "
                    f"representation")
            return literal
    for name in getattr(node, "__dataclass_fields__", {}):
        if name in _TYPE_POSITION_FIELDS:
            continue
        setattr(node, name,
                _apply_constant_sites(getattr(node, name), sites, disputed))
    return node


def _constant_read_spelling(node) -> str:
    """The `S.NAME` access path `node` spells, or None.

    The spellings `_constant_read_sites` recognizes as a read of a CLASS's own
    value, and nothing else — the same restriction, so this cannot name a
    path that table does not have an answer for."""
    if isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr):
        return f"{node.obj.name}.{node.member}"
    return None


def refuse_none_comparisons(functions: list, structs_by_name: dict,
                             receiver_bases=None,
                             method_owners: dict = None) -> None:
    """Refuse `==` / `!=` whose operand is a read of a `None`-valued constant.

    Asked BEFORE either substitution, and that ordering is the whole reason this
    function exists at all: `None` folds to the word 0 (`model.NONE_WORD`), which
    is the representation and not an approximation, but the fold is lossy in
    exactly one direction — after it, `p.b == 0` and `p.b is None` are the same
    expression, and CPython says one is False and the other True. Answering
    either from the folded word is a wrong answer rather than a refusal, and this
    backend's rule is that a wrong answer is the one outcome it may not produce.

    So the fold stands for every use that cannot observe the difference —
    materializing the value, passing it, printing it, arithmeticking on it — and
    the one construct that can is refused by name. A distinguishable null is not
    offered as an alternative because the model is one untagged 64-bit word: there
    is nowhere for a second bit of "this zero is a None" to live, which is the
    same limit `model.pointer_value_model` records for pointers.

    Both spellings of a read are covered, and each is covered by asking the
    question the substitution would have answered:
      * a CLASS-level constant (`S.NONE_FIELD`, or a local aliased from `S()`),
        via the same `_constant_read_sites` census the rewrite uses;
      * a MODULE-level `G = None`, via the published symbol table's
        `none_valued` — which is the fact the folded `IntLiteral(0)` no longer
        carries.
    A function that BINDS the name shadows it, so a read of a local called `G`
    is not this check's business, exactly as in `_substitute_module_constants`.

    `method_owners` is `{function name: struct}` and is here for the same reason
    `_rewrite_class_constants` takes it: a `None`-valued `comptime` binding read
    through a receiver (`self.MISSING`, `p.MISSING`) is a comparison this cannot
    answer, and asking a DIFFERENT census than the substitution does would leave
    one of the two answering a comparison the other has already materialized."""
    none_names = {name for name, sym in M.module_symbols().items()
                  if getattr(sym, "none_valued", False)}
    none_consts = {(st.name, cname)
                   for st in (structs_by_name or {}).values()
                   for cname, default in M.struct_class_constants(st)
                   if M.is_none_expr(default)}
    if not none_names and not none_consts:
        return
    for fn in functions:
        # The alias census is PER FUNCTION, because `p = Plain(1)` is a fact
        # about one body: `p.b` is a read of the class's own value in the
        # function that wrote that `p` and not in any other.
        none_paths = {path: kind for path, (st, kind) in _constant_read_sites(
            fn, structs_by_name, (method_owners or {}).get(fn.name),
            receiver_bases(fn) if receiver_bases else None).items()
            if (st.name, path.partition(".")[2]) in none_consts}
        if not none_names and not none_paths:
            continue
        bound = _names_bound_in(fn)
        for node in M.iter_nodes(fn.body):
            if not isinstance(node, F.BinaryOp) or node.op not in ("==", "!="):
                continue
            for operand in (node.left, node.right):
                if isinstance(operand, F.IdentExpr) \
                        and operand.name in none_names \
                        and operand.name not in bound:
                    spelling, kind = operand.name, "module-level name"
                else:
                    spelling = _constant_read_spelling(operand)
                    kind = "class-level constant"
                    if spelling is None or spelling not in none_paths:
                        continue
                    if none_paths[spelling] == "comptime":
                        kind = "`comptime` class attribute"
                raise CodegenError(
                    f"{spelling} is {kind} holding `None`, and `{node.op}` cannot "
                    f"be answered for it: `None` is this target's word 0 (which is "
                    f"why the value itself is representable and is substituted), "
                    f"and one untagged word cannot say whether that 0 arrived as "
                    f"a `None` or as the integer 0 — where Python says `None == 0` "
                    f"is False and `x is None` is not `x == 0`. Compare against a "
                    f"value the model can tell apart (a field the function "
                    f"assigns), or branch on the value being set some other way, "
                    f"rather than on a comparison this path cannot answer")
    return None


def _prepare_functions(stmts: list, synthetic: bool = True,
                       extra_structs: list = None,
                       as_dylib: bool = False) -> tuple:
    """Turn a parsed module into the function list the codegen compiles.

    `as_dylib` says this unit is being compiled as a LIBRARY rather than as a
    program, and it is the one thing that differs between the two: a dylib has
    no entry point, so nothing would ever call the module body, and a module
    whose whole content is its top-level statements would compile to a library
    that computes nothing at load time and exports nothing — the same silent
    no-op, one level down, and the reason the dylib path must not pretend the
    body is code. The refusal is raised by the caller (after imports resolve,
    so a file with a bad import still reports the import), and is the same
    message the executable path would give for a body it cannot lower.

    ONE pipeline for both entry points. It was two, and they had drifted:
    the executable path skipped method lifting and call rewriting entirely,
    so `c.get()` built an image that bound a symbol named `c.get` and died in
    dyld, while the dylib path handled it. Anything that changes what gets
    compiled has to happen here or the two front ends disagree about the same
    source file.

    Returns (functions, structs, symbols, slots) — the structs are passed to
    the codegen so a `S(...)` constructor and a `self.<field>` access can be
    recognised, and `symbols` (the module-level name table) and `slots` (the
    module-global `__DATA` slot table) are RETURNED as well as published.
    Returned because the published copy is not durable: building an import
    compiles the imported module through this same function, and that nested
    call publishes ITS globals over ours, so the caller re-publishes its own
    before anything reads the table. Measured, and the symptom was the two
    architectures disagreeing about which module a name came from."""
    # A module-level `comptime X = __mlir_type[…]` is a compile-time binding the
    # function-body expression walk never sees — this pipeline lowers
    # FunctionDefs and nothing else — so the MLIR-template refusal has to be
    # asked HERE, where the module statements still are. Before, the binding
    # compiled away silently and every use site read an undefined name, which
    # built and printed a fabricated word (10 on arm64, 0 on x86-64, for the
    # same source): `std/builtin/type_aliases.mojo` declares four and was
    # counted in the sweep as a file that built. HERE and not in either
    # backend's `compile()` because that is handed the prepared FUNCTION list
    # and never sees the module statements, and here rather than at either
    # front end because this is the one pipeline both of them go through.
    M.refuse_module_level_mlir_templates(stmts)
    # The module's own statement list is the ONE place a module-level name's
    # home is stated, so it is read here and PUBLISHED, for the same reason
    # `attach_field_evidence` and `publish_placed_frame_structs` publish what
    # they carry: the consumers are a per-function rewrite in this file and a
    # node walk inside a backend, and neither has the module statements in
    # hand.  Replaces, never merges — a dylib and its dependent are two units
    # and their globals are not one table.
    symbols = M.collect_module_symbols(stmts)
    M.publish_module_symbols(symbols)
    # A top-level statement whose MEANING changes when the body is wrapped in a
    # function — a file-level `return`, `global`, `break`, a `yield`/`await` —
    # is refused HERE, before the wrapping, and NOT by the function pipeline it
    # is about to join. Inside `__module_body__` each of those is a different
    # construct: a `return` returns from the entry, a `global` names a scope
    # that does not exist, a `yield` makes the entry a generator nothing
    # iterates. Lowered rather than refused, each builds, runs, and computes
    # something other than what the file says.
    #
    # Only `module_body_refusal`'s shapes are refused here; everything else is
    # wrapped and then answered by the ordinary codegen, so a construct the
    # backends cannot lower is still reported as a construct rather than as a
    # top-level-statement problem.
    body = M.module_body(stmts, symbols)
    if as_dylib:
        # …and on the DYLIB path the WHOLE body is refused, not just the
        # file-level-only shapes, because a library has no entry point for any
        # of it. Emitting `__module_body__` into a dylib would produce a
        # function nothing calls, exported or not: the module's top-level code
        # would be compiled, dead, and the file would build and link and do
        # nothing at load time — the same silent no-op one level down, which is
        # worse than the executable case because a caller linking the library
        # has no way to see that the store never ran.
        #
        # Said HERE, before `no_public_api_reason` gets its turn, because that
        # check reports "this module has no public functions" for a module
        # whose content IS its top level, which sends the reader looking for a
        # missing `def` in a file that has exactly what it meant to write.
        if body:
            kinds = sorted({type(s).__name__ for s in body})
            raise CodegenError(
                f"{_first_body_where(body)}this module's API is its "
                f"top-level statements ({', '.join(kinds[:4])}"
                f"{' …' if len(kinds) > 4 else ''}), and a library has no "
                f"entry point to run them. This path compiles an import into "
                f"a dylib, and the code that would run a module's top level "
                f"is not called at load time, so it would compile to a "
                f"function nothing ever runs — the file would build, link, "
                f"and do nothing, which is the same silent no-op an "
                f"executable had. A module-level name has no storage either: "
                f"every value a formal program can name lives in a function's "
                f"own stack scratch, reclaimed when the function returns "
                f"(bugs/FORMAL_module_state_no_storage.md). Give the module a "
                f"function and call it — `def sep(): return \"/\"` instead of "
                f"`sep = \"/\"` — which is the same program with a "
                f"representation.")
    else:
        _refuse_unlowerable_module_body(body)
    functions = _extract_functions(stmts, synthetic=synthetic, symbols=symbols,
                                   body=body)
    owners = _method_owners(stmts, extra_structs)
    # This file's own declarations win over an imported one of the same name:
    # a local definition shadows the import, and the local is what this file's
    # code means.
    structs, seen_struct = [], set()
    for st in ([s for s in stmts if isinstance(s, F.StructDef)]
               + list(extra_structs or [])):
        if st.name not in seen_struct:
            seen_struct.add(st.name)
            structs.append(st)
    structs_by_name = {st.name: st for st in structs}
    # `@dataclass` is a COMPILE-TIME transform (formal/dataclass_transform.py
    # has the measurement that decides the layer), so it runs HERE, in the one
    # pipeline both front ends go through, and not in a backend: a Mojo
    # `dataclasses` module could not be called, because a decorator applied to
    # a class is dropped before the front end ever looks at it (measured:
    # `.tmp/dc/q1.py` builds, runs, and the decorator's own `printf` never runs).
    #
    # Over THIS MODULE'S OWN StructDefs and not over `structs`, which also
    # carries the declarations of everything it imports. Two reasons, and the
    # second is the one that bites: an imported module is a SEPARATE
    # compilation unit that goes through this same pipeline when it is built
    # into a dylib (formal/imports.py's `build_module_dylib`), so its
    # dataclasses are lowered and checked when IT is compiled — and doing it
    # again here reported another file's class against this file. Measured: with
    # the imported declarations included, `formal/types.py` was refused for a
    # `field(default_factory=…)` in a class declared in `fire_compiler.py`,
    # under a message that named neither the class nor the field.
    #
    # The `field(default=LITERAL)` lowering is a REWRITE and has to precede
    # `_rewrite_class_constants` below, which is what materialises a class-level
    # constant where it is read: a `field(...)` left in place is materialised as
    # a CALL and refused, and the literal it wraps is materialised as the
    # literal. So this is not a convenience — it is the only thing between a
    # working class and a refusal. The CHECKS are deliberately NOT here; they
    # run beside `check_construction_shapes`, for the reason the comment on
    # that call site gives (a file that imports a host module has a more
    # fundamental fact about it than a codegen gap).
    dc_classes = DC.dataclass_classes(stmts)
    if dc_classes:
        DC.lower_field_defaults(dc_classes)
    # The `==` rewrite's table is WIDER — this module's dataclasses PLUS the
    # ones it imports — because a comparison between two values of an IMPORTED
    # dataclass is as much this module's problem as a comparison between two of
    # its own. An imported declaration is a separate parse of the other
    # module's source, so a `field(default=…)` wrapper is still on its fields;
    # only the field NAMES are read here (`struct_field_names`, which gets them
    # from the declaration's target either way), so the wrapper is harmless.
    dc_equality = (DC.dataclass_classes(stmts, structs) if structs
                   else dc_classes)
    method_owners = M.method_owner_names(structs)
    functions = functions + _struct_methods(stmts)
    # A struct of more than one field is not refused here when its receiver is
    # by reference (formal.model.struct_is_framed): the receiver word is a
    # frame address, which is one word, so the method needs no special casing
    # and the call needs no change. What is still refused is a struct that
    # fits neither representation.
    wide = {st.name: st for st in structs
            if not M.struct_fits_one_word(st) and not M.struct_is_framed(st)}
    # Re-attach the census to the structs THIS FILE declares, so that a
    # consumer of the same file's declarations cannot narrow one of them behind
    # this build's back: the two would then measure the same class differently
    # (here 248 fields, in an importer 263) and the one that is wrong is the one
    # that computes on it. A struct from an imported module keeps whatever its
    # OWN file's parse attached, and a module parsed without that evidence (the
    # current formal/imports.py, which parses imported sources directly rather
    # than through parse_module) keeps every declared name as a field — the
    # pre-rule answer, which is a refusal rather than a wrong answer. Widening
    # the union across files instead would be unsound for exactly that reason:
    # an importer's census says nothing about the writes in the file that
    # DECLARES the class, which is where the rest of them live.
    own = {id(st) for st in M.iter_struct_defs(stmts)}
    M.attach_field_evidence([st for st in structs if id(st) in own],
                            M.unit_field_evidence(stmts))
    # Which callees this module PLACES: the framed structs it declares, and
    # every struct reached as a typed-nested field of one of them.  Published
    # rather than threaded because the one consumer — the blob-in-a-field
    # premise check — is a node walk with no unit in hand, the same reason
    # `attach_field_evidence` puts the evidence on the struct.
    M.publish_placed_frame_structs(
        {st.name for st in structs_by_name.values()
         if M.struct_is_framed(st)}
        | {child.name for st in structs_by_name.values()
           for _f, _s, child in M.struct_nested_frame_fields(
               st, structs_by_name)})
    # A method declared with NO parameters takes no receiver. `def first():`
    # inside a class is a plain function that happens to be spelled like a
    # method, and prepending `Regs` to its call passes a NAME where a value is
    # required — a class name is not a value and has no register, so the call
    # bound a name with no home.  The call rewriting below skips the receiver
    # for exactly those, which is the language's rule and not a special case.
    receiverless = _receiverless_methods(owners, structs_by_name)
    # The class values a function may read through its OWN receiver, per
    # function, and read here rather than at the substitution because both of
    # the consumers below need the same answer and neither has the other's
    # context: the `None`-comparison refusal has to see the read before the fold
    # erases it, and the substitution has to run BEFORE `_rewrite_self_fields`
    # — a one-word struct's `self.<sole field>` is rewritten to plain `self`
    # there, which for a `comptime` member means rewriting the read of a class
    # value into a read of the receiver word. Measured: a one-word struct whose
    # method returns `self.LIMIT` printed 0 where the source says 10, on both
    # architectures, and the one-word mapping is what turned it into that.
    def _method_receiver_bases(fn):
        return _method_class_constant_bases(fn, method_owners.get(fn.name))

    # A comparison against a `None`-valued constant is refused HERE, before the
    # two rewrites below materialize the value: after them the fact is gone,
    # because `None` is folded to the word 0 and the fold cannot say that this
    # zero was a `None`. See `refuse_none_comparisons` for why the fold stands
    # and only the comparison is refused.
    refuse_none_comparisons(functions, structs_by_name,
                            _method_receiver_bases, method_owners)
    for fn in functions:
        _rewrite_method_calls(fn.body, owners, wide, receiverless)
        # A class-level CONSTANT read through a RECEIVER is the same read, and
        # goes before `_rewrite_self_fields` for the reason the comment above
        # gives. Everything else about it is `_rewrite_class_constants`.
        _rewrite_class_constants(fn, structs_by_name,
                                 method_owners.get(fn.name),
                                 _method_receiver_bases(fn))
        # A method's `self` IS the field; a local initialised from a one-word
        # constructor holds that struct's only field directly.
        mapping = _one_word_field_map(fn, structs_by_name,
                                      method_owners.get(fn.name))
        st = method_owners.get(fn.name)
        if st is not None and M.struct_is_one_field(st):
            mapping["self"] = _sole_field_name(st)
        _rewrite_self_fields(fn.body, mapping)
        # A class-level CONSTANT is not part of any value, so it is not
        # lowered as a field: it is materialized where it is read. Without
        # this a struct of nothing but constants — which the width rule now
        # correctly calls one word, or zero — reads its own table as the zero
        # an unwritten slot gives, and a program that builds and runs returns
        # a number nobody wrote. The receiver spelling was already handled
        # above, where the one-word mapping could not yet have eaten it; this
        # pass sees what is left, which is the class name and a local built
        # from a constructor.
        _rewrite_class_constants(fn, structs_by_name,
                                 method_owners.get(fn.name))
    ctx = FormalClosureCtx()
    discover_closures(ctx, stmts)
    functions = _flatten_closures(functions, ctx._all_closures)
    functions = _lift_lambdas(functions)
    # The module-global `__DATA` slots, on the FINAL function list and BEFORE
    # the substitution below. Both positions are load-bearing:
    #
    #   * after every rewrite, because a `global G` inside a lifted lambda or a
    #     flattened closure declares G a module global just as one inside a
    #     top-level function does, and a slot table built from the pre-rewrite
    #     list would not know that — the name would be folded away by the
    #     substitution below and the write would be lost, which is the exact
    #     defect this capability exists to fix.
    #   * before the substitution, which must skip a slotted name because a
    #     write through `global` changes its value while the program runs.
    #
    # Published for the reason `_MODULE_SYMBOLS` is: the consumers are a
    # per-function walk inside each backend and the linker, and none of them has
    # the module statements in hand.
    slots = M.collect_global_slots(stmts, functions)
    M.publish_global_slots(slots)
    # A module-level NAME whose value the build can FOLD is substituted at
    # every read, so `G = 5` read from a function is the 5 and not whatever
    # the register allocator left behind.  LAST of the rewrites, for the reason
    # `_frame_receivers` is: a lifted lambda and a flattened closure are
    # functions with their own locals, and a shadowing local in one of them has
    # to be visible to the substitution or the module constant would replace
    # the function's OWN name.
    _substitute_module_constants(functions)
    _collect_shadowed_global_reads(functions)
    _materialize_entry_dunder_name(functions)
    # A COMPILE-TIME IDENTITY becomes its operand before anything downstream
    # reads the tree, and immediately before `_frame_receivers` for the reason
    # that function's own call site is last: the frame analysis and the escape
    # walk that follows it are the checks this rewrite exists to keep seeing the
    # operand, so it has to be the last thing to touch the code they read.
    # `_rewrite_identity_intrinsic_calls`'s docstring has the two programs that
    # say what the ordering is worth.
    _rewrite_identity_intrinsic_calls(functions)
    # …and a target query IN a body, which the constant substitution cannot
    # reach: `__mlir_attr[...]` is an expression, not a name, and a function
    # that asks the build what it is compiling for has to get the answer
    # materialized as the literal it is.  Same list, same position, same
    # reason.  Independently of order with the substitution above: a
    # module-level `comptime ARCH = <query>` was already folded to a literal by
    # `collect_module_symbols`, and this pass only sees the query where the
    # SOURCE wrote one.
    _fold_target_queries(functions)
    # LAST, on the FINAL function list: which local names hold a frame
    # address is a property of the code that survives every rewrite above, and
    # a lifted lambda or a flattened closure is a function with its own locals
    # and its own receivers.
    #
    # `dc_classes` goes in as an argument rather than being re-read from the
    # module statements, for the same reason the pass publishes
    # `fn._frame_candidates`: the holder analysis is the only thing in the
    # compiler that can say a word is a frame address, so a second recognition
    # of "is this name a dataclass value" — computed here from the AST instead
    # of from `by_name` — is exactly the pair that agrees until the day it does
    # not. `formal/dataclass_transform.rewrite_equality` takes the holder
    # table as given.
    # The two import tables for the same reason and one step further out: they
    # are what tells a callee this unit does not COMPILE from a callee NOTHING
    # compiles, and `known`/`cross_module` cannot answer that (neither holds an
    # imported free function, nor a star import's export set).  Read here, once,
    # from the statements this function was given, rather than by the pass from
    # `stmts` — the pass does not have them.
    from formal.imports import (imported_bound_names,
                                star_imported_modules)
    _frame_receivers(functions, structs_by_name, dc_equality,
                     imported_bound_names(stmts),
                     star_imported_modules(stmts), owners)
    # The slot table is RETURNED as well as published, for the reason
    # `symbols` is: building an import compiles the imported module through this
    # same function, and that nested call publishes ITS globals over ours, so
    # the caller re-publishes its own before anything reads the table.
    return functions, structs, symbols, slots


def _method_owners(stmts: list, extra_structs: list = None) -> dict:
    """{method_name: struct_name} for every method a module declares.

    Dispatch is by name alone, because `recv.m(...)` carries no type
    information on this path — the receiver's type is not inferred. So a method
    name declared by two structs in one module is genuinely ambiguous, and it
    is left out of this map rather than resolved arbitrarily: the call then
    fails as the unresolvable symbol it is, instead of silently binding to one
    struct's method."""
    owners: dict = {}
    ambiguous = set()
    for st in list(stmts) + list(extra_structs or []):
        if not isinstance(st, F.StructDef):
            continue
        for m in M.struct_methods(st):
            if m.name in owners and owners[m.name] != st.name:
                ambiguous.add(m.name)
            owners[m.name] = st.name
    for name in ambiguous:
        owners.pop(name, None)
    return owners


def _receiverless_methods(owners: dict, structs_by_name: dict) -> set:
    """Method names whose declaration takes no receiver.

    `def first():` inside a class is a plain function that happens to be
    spelled like a method, and the language gives it no receiver.  The
    rewriting below skips the receiver for exactly those, which is the
    language's rule rather than a special case: prepending `Regs` to such a
    call passes a NAME where a value is required, and a class name is not a
    value — it has no register, no slot and no frame, so the call bound a name
    with no home at all.

    Collected from the DECLARATION (an empty parameter list), not from the
    spelling, and only for structs `owners` actually resolved: a name two
    structs declare is ambiguous and `_rewrite_method_calls` already refuses
    to rewrite it, so there is nothing to decide here."""
    out = set()
    for struct_name in (owners or {}).values():
        st = (structs_by_name or {}).get(struct_name)
        if st is None:
            continue
        for m in M.struct_methods(st):
            if not (getattr(m, "params", None) or []):
                out.add(m.name)
    return out


def _method_call_target(call, owners: dict):
    """`recv.m` or `recv.m[T]` on a CallExpr: (owner, member, receiver), or None.

    The one recogniser for "this call's callee is a method of a struct this
    module declares", over BOTH spellings a method call has: a bare `recv.m`
    and a comptime-specialized `recv.m[T]`.  The second is the same call with a
    generic's brackets on it, so it must be the same answer — a subscript whose
    base is the MemberExpr is not a subscript of a VALUE, and treating it as one
    is what made `recv.m[T](a)` arrive at the frame analysis as a field read of
    `recv.m` and get refused as a bound-method value (see `_specialized_method_call`
    for the measurement and the shapes deliberately left out).

    `None` for every other callee, which is the answer `owners` itself gives for
    a name two structs declare — dispatch here is by NAME, so an ambiguous one
    has no owner to lift to.
    """
    func = call.func
    if isinstance(func, F.SubscriptExpr):
        func = func.obj
    if not (isinstance(func, F.MemberExpr) and isinstance(func.obj, F.IdentExpr)):
        return None
    owner = owners.get(func.member)
    if owner is None:
        return None
    return owner, func.member, func.obj


def _ambiguous_method_owners(base, structs_by_name: dict) -> list:
    """The structs in this image that BOTH declare `base.<member>`, or [].

    The one place the ambiguity is computed, and it is asked of the DECLARATIONS
    (`M.struct_methods`) rather than of `_method_owners`' output, because that map
    has already thrown the name away — it pops every ambiguous name precisely so
    `_rewrite_method_calls` cannot pick one.  Re-deriving it from the same tables
    it reads is what keeps the two from disagreeing about whether a name was
    ambiguous.

    `None` for a callee that is not a method call on a plain name, which is the
    answer `owners` gives for those too and the reason the caller can use a bare
    truthiness test.
    """
    if not (isinstance(base, F.MemberExpr) and isinstance(base.obj, F.IdentExpr)):
        return []
    declaring = [st for st in (structs_by_name or {}).values()
                 if any(m.name == base.member for m in M.struct_methods(st))]
    return declaring if len(declaring) > 1 else []


def _rewrite_method_calls(node, owners: dict, wide: dict = None,
                          receiverless: set = None) -> None:
    """`recv.m(a)` -> `Struct_m(recv, a)`, in place, over a statement tree.

    Rewriting the CALL rather than special-casing a method call in the
    codegen means the ordinary call path handles it: the method is already
    compiled as a function taking `self` first, so the receiver simply
    becomes its first argument and every existing rule about arguments,
    registers and tail calls applies unchanged.

    Which is also why the by-reference receiver needed NO change here. The
    receiver this already passes is the word the local holds, and for a
    multi-field struct that word is the address of its frame — so the receiver
    arrives as the address it already was, and the one parameter `MojoFunc`
    has is still enough. The whole ABI question
    `bugs/FORMAL_wide_receiver_by_reference.md` asks is answered by that
    accident of the design, and this function is where it shows up: the
    receiver-width refusal below fires only for a struct that fits NEITHER
    representation, which with the switch on is one whose fields cannot be
    given a real slot at all.

    `recv.m[T](a)` goes through the same lift with the brackets KEPT on the
    callee, which is the whole of what a specialization is: `model.incoming_args`
    puts a generic's comptime parameters first and arm64's `_emit_call` passes
    the bracket expressions first, so `Struct_m[T](recv, a)` and
    `Struct_m(recv, a)` reach the callee's parameters identically.  See
    `_specialized_method_call`."""
    if isinstance(node, list):
        for x in node:
            _rewrite_method_calls(x, owners, wide, receiverless)
        return
    if isinstance(node, F.CallExpr):
        target = _method_call_target(node, owners)
        if target is not None:
            owner, member, receiver = target
            if (wide or {}).get(owner) is not None:
                st = wide[owner]
                raise CodegenError(
                    f"{owner}.{member}() cannot be lowered: its "
                    f"receiver has {M.struct_field_summary(st)}, and a formal "
                    f"value is one 64-bit word, so `self.<field>` has no "
                    f"representation on this path. The receiver would have to "
                    f"be a pointer to an out-of-line frame of fields, which is "
                    f"a change to the value model the two backends AND the Lean "
                    f"proof share, not to this one function. Concretely, "
                    f"{M.struct_width_cost(st)}")
            lifted = F.IdentExpr(name=M.method_function_name(owner, member))
            if member not in (receiverless or ()):
                node.args = [receiver] + list(node.args)
            if isinstance(node.func, F.SubscriptExpr):
                # The brackets stay, and stay on the callee: they are the
                # specialization, and the emitter reads them off the callee
                # (`arm64_codegen._specialization_of`).  Only the BASE is
                # replaced, which is the one thing that changes — it becomes the
                # lifted name instead of the receiver's.
                node.func.obj = lifted
                return
            node.func = lifted
            return
    for name in getattr(node, "__dataclass_fields__", {}):
        _rewrite_method_calls(getattr(node, name), owners, wide, receiverless)


def dylib_manifest_path(dylib_path: str) -> str:
    """Where a dylib's export manifest lives: `<dylib>.manifest.json`."""
    return os.path.abspath(dylib_path) + ".manifest.json"


def _write_json_atomic(path: str, payload) -> None:
    """Write JSON to `path` through a private temp file and `os.replace`.

    The established mechanism in this repository — `cas.publish` does exactly
    this, and its own comment says why ("Hash-named files are immutable, so a
    racing identical write is harmless (`os.replace` is atomic)") — applied to
    the one file here that other processes read WHILE it is being written.

    `open(path, "w")` truncates AT THE OPEN, so between that open and the first
    byte written the file is 0 bytes, and a reader in that window gets
    `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.
    That is not an `OSError`, so none of the `except OSError` around these reads
    catches it: it propagates out of the build driver and the sweep files the
    file as `tool: the build driver raised: json.decoder.JSONDecodeError`. The
    writers are serialised by `formal/imports.py`'s `_dylib_lock`; the READERS
    take no lock at all, so the pair exists inside one `-j6` sweep — two workers
    importing the same stdlib module both build its dylib, and one links it
    while the other rewrites its manifest. Measured twice, on real manifests of
    11.6 kB: the original report saw 357 of 882 concurrent reads (40 %) land in
    the 0.21 ms window, and the reproducer against this tree's own code saw 1804
    failures in 4095 reads — 1759 of them the empty-file `char 0` signature —
    against 0 in 12792 reads after the fix.

    fsync before the rename, because the failure this removes is a reader
    seeing a half-written file; a rename that reaches disk before the data does
    would trade it for a reader seeing the PREVIOUS content on a power cut,
    which is a whole-file answer and so harmless. The temp name carries the pid
    and a random suffix so two writers in one process cannot collide on it.
    """
    import json
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(
        directory, f".{os.path.basename(path)}.tmp.{os.getpid()}."
                   f"{os.urandom(4).hex()}")
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=1, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update_dylib_manifest(manifest_path: str, mutate) -> None:
    """Read `<dylib>.manifest.json`, apply `mutate(payload)`, write it back.

    ONE read-modify-write for every caller, because there were four of them
    (`write_dylib_manifest`, `_record_link_deps`, `_record_namespace`,
    `formal/imports.py`'s `_record_depends`) and four copies of a
    read-modify-write is four chances to leave one of them truncating. The
    write goes through `_write_json_atomic`, so a reader sees the whole old
    file or the whole new one.

    A manifest that is not there yet is not an error here: it is the state
    before `write_dylib_manifest` has run, and each of these callers is
    recording something INTO a manifest someone else may not have written yet.
    So there is nothing to update and nothing to report — which is what the
    `except OSError` these call sites already had does, and it stays. Widening
    it to `ValueError` would be the wrong fix: it would convert the race above
    into a silent "no manifest", which reads downstream as a module that
    exports nothing — the exact false finding `load_dylib_manifests` warns
    about — and it would also swallow the half-written file a crashed writer
    leaves behind.
    """
    import json
    try:
        with open(manifest_path) as f:
            payload = json.load(f)
    except OSError:
        return
    mutate(payload)
    _write_json_atomic(manifest_path, payload)


def write_dylib_manifest(dylib_path: str, install_name: str,
                         exports: list, module: str = None,
                         constants: dict = None, source: str = None) -> str:
    """Record what a formal dylib exports, next to the dylib.

    An executable that links this library has to rewrite each call site's
    callee to the library's exported spelling (`_<module>__<fn>`), and it
    cannot know that mapping by looking at the source it is compiling — the
    callee is just a bare name. The build that *made* the library is the only
    place the mapping exists, so it leaves it behind. JSON because the
    executable build has to read it without importing this module's
    compile-time dependencies.

    `module` is the ABI identity of the module this library was built from
    (`model.abi_module_name`), and it is what makes a DOTTED call resolvable
    through a library that exports nothing: every export entry already carries
    its module, so a normal library could be keyed from its own table, but a
    package `__init__` that only re-exports has an empty table BY DESIGN (see
    `_namespace_library`) and nothing in its manifest named it. A consumer
    asking "does `pkg` publish `f`?" had no way to find `pkg` at all, so
    `pkg.f(...)` reached the link audit as a dangling symbol instead of a
    refusal that could name the module.

    Each export entry carries `frame_params` — the per-parameter frame-holder
    contract `_formal_exports` publishes off `fn._frame_param_contract`. It is
    the one thing in a manifest that is not a SYMBOL, and it is what lets a
    consumer decide a frame-address hand-off across the module boundary instead
    of refusing it as unknowable: the callee module's own compilation says
    which of its parameters are frame addresses and of which struct, and that
    is a fact about a compilation the consumer did not perform and cannot
    re-derive. `bugs/FORMAL_callee_no_def_ceiling_zero.md` records what it is
    worth.

    `constants` is the module-level name → folded LITERAL table, and it is the
    one thing a dylib publishes that is not a symbol. It exists because a
    literal needs no storage: there is exactly one value of a folded
    module-level name in a whole program (the module-level sequence is its only
    writer, and a function that assigns the name shadows it), so an importer
    can materialize the same value in its own image instead of reading an
    address. A module-level name the build could NOT fold is not here — it is
    a real global with nowhere to live, and it stays refused, which is what
    keeps `sys.argv` and `os.sep` different answers
    (`bugs/FORMAL_module_state_no_storage.md`).

    `source` is the module's own source path, recorded for the same reason and
    read back by `formal/imports.py`'s `external_declarations`: an export entry
    carries an ARITY and a signature, and neither is enough to bind a call whose
    arguments are short of the arity — a DEFAULT is part of the function's
    contract, and materializing it at the call site needs the default's own
    expression, which only the DECLARATION has. Reading it from the path
    recorded here is what makes the two sides unable to disagree: it is the
    exact file this library was compiled from, not a module name resolved again
    by whoever is reading."""
    import json
    path = dylib_manifest_path(dylib_path)
    payload = {
        "dylib": os.path.abspath(dylib_path),
        "install_name": install_name,
        # What the executable records in its LC_LOAD_DYLIB. The library's own
        # id is `@rpath/...`, which a dependent can only resolve with an
        # LC_RPATH of its own, so a dependent links the real location.
        "load_path": os.path.abspath(dylib_path),
        # The module's own source, when this library was built from one. Absent
        # for a library with no source of its own (the runtime dylib, written by
        # `runtime_manifest`), which is exactly what "there is no declaration to
        # read" looks like, so a reader can tell the two apart.
        "source": os.path.abspath(source) if source else None,
        # The reflection payload, in the shape doc/ABI.md's table carries: the
        # boundary symbol, its signature, and the module that owns it, so a
        # client can bind a call without ever reading the module's source.
        "module": module,
        "constants": dict(constants or {}),
        "exports": [{"module": e["module"], "name": e["name"],
                     "symbol": e["symbol"], "arity": e.get("arity"),
                     "call": e.get("call"),
                     "signature": e.get("signature", ""),
                     "kind": e.get("kind"),
                     "frame_params": e.get("frame_params") or []}
                    for e in exports],
    }
    # Atomic, like every other manifest write: this one truncates a file other
    # processes read while they link (see `_write_json_atomic`), and it is the
    # write that makes the file exist at all, so a reader in its window would
    # read an empty manifest rather than a stale one.
    _write_json_atomic(path, payload)
    return path


def load_dylib_manifests(dylib_paths: list) -> list:
    """Read the manifests of the libraries an executable links against.

    Each entry is `{"install_name", "source", "map": {bare callee ->
    exported symbol}, "exports", "module", "reexports", "constants"}`. A
    library whose manifest is missing is an error rather than a silently
    ignored dependency: the executable would emit calls to symbols nothing
    defines and produce an image that dies in dyld at launch — which is exactly
    the failure this mechanism exists to prevent.

    The `map` is keyed by the BARE name and only by the bare name, and that is
    the whole contract: it is what a BARE callee resolves through, first
    library on the line winning. A DOTTED callee — `mod.f`, the spelling
    `import mod` binds — is answered from `exports` by module identity
    (`model.dylib_export_lookup`), because the flat map cannot say which module
    owns a name and answering it from here would let `mod.f` bind some other
    library's `f`. The two spellings of the same export are therefore NOT both
    written into the map: there is one resolution per spelling, and each is
    where it can see the module the name is qualified by.

    `module`, `reexports` and `constants` are the parts of the manifest that do
    not name a SYMBOL, and each exists for a spelling the symbol table cannot
    answer:

      * `module` — which module this library IS. A normal library could be
        keyed from its own exports, but a namespace library's table is empty by
        design and nothing else in its manifest named it.
      * `reexports` — the names this module publishes by forwarding rather than
        by defining, each with the symbol the DEFINING module really exports.
        This is what makes `pkg.f(...)` — the spelling `import pkg` binds, and
        the only spelling a package has for a re-exported name — resolve.
      * `constants` — the module-level names the build folded to literals.
        A dylib cannot export a variable (there is nowhere for one to live,
        `bugs/FORMAL_module_state_no_storage.md`), but a LITERAL needs no
        storage: the importer materializes the same value in its own image,
        which is what a module-level constant substitution already does inside
        one unit. That is the whole of what makes `mod.CONST` and `sys.argv`
        different answers."""
    import json
    out = []
    for dylib in dylib_paths or []:
        mpath = dylib_manifest_path(dylib)
        try:
            with open(mpath) as f:
                payload = json.load(f)
        except OSError as e:
            raise FormalBuildError(
                f"cannot read the export manifest for {dylib} ({mpath}): {e}. "
                f"It is written next to the dylib by `fire dylib --formal`.")
        exports = payload.get("exports") or []
        if not exports and payload.get("kind") != "namespace":
            raise FormalBuildError(
                f"{dylib}'s manifest lists no exports")
        # A NAMESPACE library (a package `__init__` that only re-exports —
        # `_namespace_library`) legitimately has none: its definitions are in
        # the submodules whose own libraries are also on this link line, and
        # its export table is empty on purpose, so that no consumer resolves a
        # name to an address inside an image that has no code. It contributes
        # an empty map and its load commands, which is all it has to
        # contribute — plus the forwarding under `reexports`, which is how a
        # consumer binds `pkg.f` to the definition in the submodule rather than
        # to an address in this one. Every other library still has to offer
        # something, so the check above is unchanged for them.
        # Two libraries may export the same callee name; first one listed
        # wins, matching the dylib ordinal order the image will record.
        amap = {}
        for e in exports:
            amap.setdefault(e["name"], e["symbol"])
        out.append({
            "install_name": payload.get("load_path") or payload["dylib"],
            "path": dylib,
            "source": payload.get("source"),
            "map": amap,
            "exports": exports,
            "module": payload.get("module") or "",
            "reexports": payload.get("reexports") or {},
            "constants": payload.get("constants") or {},
            # The trait-only namespace library's own names. Read back for the
            # same reason `module` is: so a reader can tell an empty trie that
            # is BY DESIGN (this library declares traits, which have no
            # symbol) from one that means the build went wrong, without
            # re-parsing the source the manifest was written from.
            "traits": list(payload.get("traits") or []),
        })
    return out


def dylib_export_lists(dylibs: list) -> list:
    """The `[{"module", "exports", "reexports", "constants"}]` view of a link
    line.

    What both emitters are constructed with, and one iteration over the link
    line rather than the two it used to be: `_dylib_syms` (the flat bare-name
    map), the flat map's own entries and the module-keyed table are three
    questions about the same libraries in the same order, and asking them in
    three places is three places to disagree about which library won a name.
    `constants` rides along because it is the same link line and the same
    manifests — `model.dylib_module_constants` reads this list — and a
    manifest's constants dropped here would silently answer every imported
    constant read with "no value", which is the refusal this whole mechanism
    exists to replace.
    """
    return [{"module": d.get("module") or "",
             "exports": list(d.get("exports") or []),
             "reexports": d.get("reexports") or {},
             "constants": d.get("constants") or {}}
            for d in (dylibs or [])]


# ── The gimple runtime's C library, on a formal link line ──────────────────
#
# FORMAL.md phase 2 made a `mojo_*` call DECIDABLE. `model.gimple_runtime_
# callable` answers, from the runtime header's own types, whether a formal image
# could make one — "every type crossing the boundary is one 64-bit word, AND the
# symbol is on the link line" — and for the 219 entry points that were word-shaped
# the second half was false for every single one of them. The library was not
# missing: `runtime_dylib()` (build_stdlib_dylib.py:981) builds a
# per-architecture `-dynamiclib` exporting the whole `mojo_*` namespace, it is
# CAS-cached, `_arch_or_die`-checked against the architecture it was asked for,
# and the gimple path links it every day. What was missing is that nothing ever
# put it on a FORMAL link line, so the honest summary of the reachable surface
# was "0 of the word-shaped calls are callable from a proof" and the refusal was
# — correctly — saying exactly that.
#
# What is here closes that, and it is deliberately NOT a codegen change.
# `is_gimple_runtime_builtin` answers "can this target bind this", and widening
# it would have taught the compiler to emit a call it had no way to resolve: the
# image would build, the audit would pass it as unaccounted-or-libc, and the
# program would die in the loader. The answer there stays no until the symbol is
# genuinely on the line. The line is what changes.
#
# Three decisions, each of which could have gone the other way:
#
#   * The export table is READ OUT OF THE DYLIB's export trie — the one
#     structure dyld itself consults — rather than taken from the headers the
#     library was built from, and not from an `nm` invocation. Re-deriving it
#     from the header would be a second hand-kept answer to a question the
#     artifact already answers, and the two drift the moment a unit is dropped
#     for a symbol collision (which `build_stdlib_dylib` does, silently, per
#     module). An `nm` proxy is nearly right and has a real failure: it reports
#     every global the objects DEFINE, while dyld resolves against what the
#     linker EXPORTED, and those differ. The trie is the link contract.
#
#   * The library goes on the line only when the program names an entry point of
#     it that a formal image could make (`_runtime_word_calls`). Not a flag: a
#     formal image that names nothing there must keep the smallest link line it
#     has, because every dependency is a load command, a load command moves the
#     entry point, and the entry point moves every address in the image. Doing
#     it unconditionally would re-emit all 590 files of the coverage sweep for
#     no gain, and would put a library dyld has to open in front of every
#     program — including the ones a proof is about. Doing it NEVER is the
#     failure this would have been the other way round: a refusal for a call
#     that should have compiled.
#
#   * An ELF image gets nothing. `build_elf` carries one `lib_name` and no
#     dependency list, and `formal/elf.py` is not this file's to grow. A
#     `mojo_*` call on an ELF target is still refused, by the same shared rule
#     and the same words, and the refusal now says why.


_MH_MAGIC_64 = 0xFEEDFACF
_MH_DYLIB = 6
_LC_SEGMENT_64 = 0x19          # not decoded; the walk skips what it does not know
_LC_DYLD_EXPORTS_TRIE = 0x33 | 0x80000000   # LC_REQ_DYLD, as the linker writes it

# An export trie's terminal payload is (flags, address). The low two bits of
# `flags` are the KIND — 0 regular, 1 thread-local, 2 absolute — and 0x04/0x08
# mark a weak definition and a re-export. Only KIND 0 is an ordinary function
# this path can call: a thread-local is not code an image can branch to, an
# absolute is an address constant, and a re-export forwards to whatever THIS
# library depends on, so binding it here would be binding the wrong image.
_MH_EXPORT_KIND_MASK = 0x03
_MH_EXPORT_KIND_REGULAR = 0x00


def _uleb128(data: bytes, pos: int) -> tuple:
    """(value, next position) for the LEB128 the Mach-O link-edit formats use."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise FormalBuildError(
                "a Mach-O LEB128 field runs past the end of its structure")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise FormalBuildError(
                "a Mach-O LEB128 field is wider than 64 bits")


def _read_export_trie(trie: bytes, offset: int, prefix: str,
                      out: dict) -> None:
    """Walk one node of an export trie, adding every ordinary export to `out`.

    The format is a prefix tree of edge LABELS: at each node a LEB128 terminal
    size, that many bytes of terminal payload if the size is non-zero (the
    flags and the image offset of the symbol this node's accumulated prefix
    names), then one child-count byte and that many (NUL-terminated label,
    LEB128 child offset) pairs. Empty terminal payload is the common case and
    means "this prefix is not itself a symbol" — every interior node of the
    tree is like that, and reading the count byte from the wrong offset is how
    a reader walks off the end of the structure.

    Recursive rather than iterative because the recursion is bounded by the
    length of a symbol name, which is a handful.
    """
    size, pos = _uleb128(trie, offset)
    end = pos + size
    if size:
        if end > len(trie):
            raise FormalBuildError(
                "an export trie's terminal payload runs past the end of the "
                "trie")
        flags, after = _uleb128(trie, pos)
        address, after = _uleb128(trie, after)
        if after > end:
            raise FormalBuildError(
                f"an export trie's terminal payload for {prefix!r} overruns "
                f"the size its own header declares")
        if (flags & _MH_EXPORT_KIND_MASK) == _MH_EXPORT_KIND_REGULAR and address:
            out[prefix] = flags
    if end >= len(trie):
        raise FormalBuildError(
            "an export trie node's child count runs past the end of the trie")
    nchildren = trie[end]
    pos = end + 1
    for _ in range(nchildren):
        nul = trie.find(b"\0", pos)
        if nul < 0:
            raise FormalBuildError(
                "an export trie edge label is not NUL-terminated")
        label = trie[pos:nul].decode("utf-8", "replace")
        child, pos = _uleb128(trie, nul + 1)
        _read_export_trie(trie, child, prefix + label, out)


def macho_dylib_exports(path: str) -> dict:
    """{Mach-O name: flags} for every ordinary export of a Mach-O dylib.

    An INDEPENDENT reader: `formal/macho_linker.py` writes these images and has
    a `_export_trie` that builds one, and asking the writer to read its own
    output is how a writer's bug becomes invisible. This parses the file's load
    commands and the trie dyld would consult, and knows nothing about how any of
    it was produced.

    Raises rather than returning a partial table. Every caller here wants the
    whole export surface — a name quietly missing from this dict is a call that
    is refused, and a name quietly ADDED is a bind whose ordinal points at the
    wrong library — so a truncated answer is the one thing worse than no answer.
    """
    import struct          # lazy, like `json` above: keep the module edges few
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 32:
        raise FormalBuildError(f"{path} is too small to be a Mach-O file")
    (magic, _cputype, _sub, filetype, ncmds, sizeofcmds, _flags,
     _reserved) = struct.unpack_from("<8I", data, 0)
    if magic != _MH_MAGIC_64:
        raise FormalBuildError(
            f"{path} is not a 64-bit Mach-O (magic {magic:#x}); the runtime "
            f"library this looks for is built by clang for the host")
    if filetype != _MH_DYLIB:
        raise FormalBuildError(
            f"{path} is not a dylib (filetype {filetype}); a link line names "
            f"libraries, and an executable on it is a cycle, not a provider")
    if sizeofcmds > len(data) - 32:
        raise FormalBuildError(
            f"{path} has a load-command list that runs past the end of the file")
    out = {}
    pos = 32
    for _ in range(ncmds):
        if pos + 8 > 32 + sizeofcmds:
            raise FormalBuildError(
                f"{path}: a load command starts past sizeofcmds")
        cmd, cmdsize = struct.unpack_from("<II", data, pos)
        if cmdsize < 8 or pos + cmdsize > 32 + sizeofcmds:
            raise FormalBuildError(
                f"{path}: load command {cmd:#x} has an impossible cmdsize "
                f"{cmdsize}")
        if cmd == _LC_DYLD_EXPORTS_TRIE:
            if cmdsize < 16:
                raise FormalBuildError(
                    f"{path}: LC_DYLD_EXPORTS_TRIE is {cmdsize} bytes, which is "
                    f"too small to hold its own dataoff/datasize")
            dataoff, datasize = struct.unpack_from("<II", data, pos + 8)
            if dataoff + datasize > len(data):
                raise FormalBuildError(
                    f"{path}: its export trie runs past the end of the file")
            _read_export_trie(data[dataoff:dataoff + datasize], 0, "", out)
        pos += cmdsize
    if not out:
        raise FormalBuildError(
            f"{path} exports nothing, so a client could bind no name in it")
    return out


def _c_export_name(macho_name: str):
    """The C identifier a Mach-O export name spells, or None for a name that is
    not one.

    A Mach-O symbol is its C name with a leading underscore — that underscore is
    dyld's, and `_bind_info` says so where it takes the C spelling back off
    before writing the bind stream. So `_mojo_strlen` is `mojo_strlen`.

    Exactly ONE leading underscore. C++ template instantiations and the rest of
    what the mangler emitted are `__ZNSt...`, i.e. two, and there is no C
    declaration to bind them to: a program calls a name it spelled, and no
    program spells `__ZNSt3vectorIiNS_9allocatorIiEEE9push_backERKi`. Listing
    them would widen the map with names nothing can ask for, and would make the
    bind audit wave through a dangling call whose name happened to be mangled.
    """
    if not macho_name.startswith("_") or macho_name.startswith("__"):
        return None
    name = macho_name[1:]
    for ch in name:
        if not (ch.isalnum() or ch == "_") or ord(ch) > 127:
            return None
    if not name or name[0].isdigit():
        return None
    return name


def runtime_manifest(dylib: str) -> str:
    """Write (and return) the export manifest for the runtime dylib.

    The SAME artifact and the SAME manifest shape a formal module dylib gets
    (`write_dylib_manifest`), so `load_dylib_manifests` reads the runtime
    library with no special case anywhere: one manifest format, one loader, one
    link line. That is the point of writing it here at all — the alternative is
    a second, runtime-specific shape threaded through `_codegen_and_link`,
    `_dylib_syms` and `_audit_bound_symbols`, which is three places to keep in
    step for the sake of a list that is already in the file.

    The `exports` are the trie's ordinary exports, and each one's `signature`
    is filled in from the runtime header when `model.runtime_abi` declares it.
    A name the dylib exports that no header declares is still exported — it is
    real and a client can bind it — with an empty signature, because inventing
    one would be the kind of plausible-looking wrong answer this whole mechanism
    exists to avoid.

    Idempotent, and safe to race: the dylib's own name is content-addressed
    (`runtime_dylib`'s docstring), so two processes that agree write byte-equal
    files at the same path, and `write_dylib_manifest` replaces rather than
    appends.
    """
    import json
    abi = M.runtime_abi()
    exports = []
    for macho_name in sorted(macho_dylib_exports(dylib)):
        name = _c_export_name(macho_name)
        if name is None:
            continue
        entry = abi.get(name)
        exports.append({
            "module": "mojo_runtime",
            "name": name,
            # The C spelling, not the Mach-O one: `symbol` is what the bind
            # stream carries and what `_dylib_syms` rewrites a call site to,
            # and dyld puts the underscore back on.
            "symbol": name,
            "arity": None,
            "signature": entry["signature"] if entry else "",
            "kind": 0,       # reflect.SYM_FUNCTION
        })
    install = "@rpath/" + os.path.basename(dylib)
    return write_dylib_manifest(dylib, install, exports)


def runtime_library(arch: str, fmt: str):
    """The `mojo_*` C runtime as one link-line entry, or None for a target that
    cannot carry a library at all.

    The return value is exactly what `load_dylib_manifests` produces for a
    module dylib, which is deliberate: from `_codegen_and_link` down — the
    callee mangling, the LC_LOAD_DYLIB, the bind ordinal, the audit — nothing
    downstream can tell the runtime from an imported module, and nothing
    downstream has to know.

    `fmt != "macho"` returns None. That is not a shrug: `build_elf` carries one
    `lib_name` and no dependency list, so an ELF image genuinely cannot name a
    second library, and the caller falls back to the shared refusal, which says
    so. Returning None and letting the refusal speak is the honest failure; the
    alternative — silently linking nothing and reporting a successful build —
    is the failure class this whole programme exists to remove.

    A Mach-O target that cannot BUILD the library is an error rather than a
    None. `runtime_dylib` needs a working host toolchain, and on a host without
    one there is no library to link, no word-shaped call to make, and no
    diagnostic the refusal could improve on: the refusal already says the link
    line does not define the name, and it would be right.
    """
    if fmt != "macho":
        return None
    from build_stdlib_dylib import runtime_dylib    # lazy: see the note below
    dylib = os.path.abspath(runtime_dylib(arch=arch))
    if not os.path.exists(dylib_manifest_path(dylib)):
        runtime_manifest(dylib)
    return load_dylib_manifests([dylib])[0]


def _runtime_word_calls(ordered: list) -> list:
    """The `mojo_*` entry points `ordered` calls that a formal image could make.

    A pre-pass over the source's own AST, and therefore a SUPERSET of what
    codegen can emit. Nothing between here and the call lowering invents a
    callee name: `_prepare_functions` renames a repeated definition, and
    `_rewrite_method_calls` spells a method `Owner_method`, neither of which is
    in the runtime ABI; `comptime_runner` can only REPLACE a call with a
    constant, and dropping a name can never make the linker need a library it
    would not otherwise have needed. Over-approximating costs an image that does
    not call the library one load command. Under-approximating costs a refusal
    for a call that should have compiled, which is the failure this whole change
    exists to remove — so the direction is not a preference.

    Two filters, and both are the question `model.gimple_runtime_callable` asks
    rather than a second version of it:

      * the `mojo_*` NAMESPACE, because that is the scope the rule is scoped to.
        The headers also declare `input`, `setattr`, `string_strip`,
        `int64_t_basename` and `py_tokenize`, and `gimple_runtime_callable`
        answers True for all of them on purpose — they are the C library and the
        compiler's own shims, not the runtime's ABI. A pre-pass keyed on the
        header table alone would put a 478-name library on the link line of
        every image that calls `input()`, which is four files of this
        repository's corpus, for a name no library there defines.
      * a name this module DEFINES, because codegen resolves a call to a local
        function before it ever reaches the extern path, and a module that
        defines its own `mojo_thing` must not drag the C runtime onto its link
        line to answer a call that never left the file.
    """
    abi = M.runtime_abi()
    local = set()
    for fn in (ordered or []):
        name = getattr(fn, "name", None)
        if isinstance(name, str):
            local.add(name)
    found = set()

    def walk(node):
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
            return
        if isinstance(node, F.CallExpr):
            fn = node.func
            if isinstance(fn, F.IdentExpr) and fn.name not in local \
                    and fn.name.startswith(M.GIMPLE_RUNTIME_PREFIX):
                entry = abi.get(fn.name)
                if entry is not None and entry["word"]:
                    found.add(fn.name)
        for field in getattr(node, "__dataclass_fields__", {}):
            walk(getattr(node, field))

    for fn in (ordered or []):
        walk(getattr(fn, "body", None))
    return sorted(found)


def _runtime_library_for(ordered: list, arch: str, fmt: str):
    """(entry, covered names) for the runtime library, or (None, []).

    The second half of the decision `_runtime_word_calls` cannot make: a name
    being word-shaped says the CALL is answerable, and only the library's own
    export table says whether this one answers it. They are different sets and
    the difference is 51 entry points on this tree, because
    `runtime_dylib` links `runtime_units(arch, None)` — the core runtime, the
    coroutine runtime and the async scheduler — and NOT the OPTIONAL units
    `fire_sqlite3.c`, `fire_ssl.c`, `fire_zlib.c` and `fire_ncurses.c`, which
    the gimple path compiles on demand (`build_config.OPTIONAL_RUNTIME_UNITS`).
    So `mojo_strlen` is exported and `mojo_sqlite3_step` is not, and both are
    word-shaped.

    Checking the intersection rather than linking optimistically is what keeps
    the other 5 honest: a program that calls only `mojo_sqlite3_close` gets the
    refusal that says the library does not export the name, rather than a
    478-name library on its link line that changes nothing about the verdict.
    """
    named = _runtime_word_calls(ordered)
    if not named:
        return None, []
    lib = runtime_library(arch, fmt)
    if lib is None:
        return None, []
    amap = lib.get("map") or {}
    covered = [n for n in named if n in amap]
    if not covered:
        return None, []
    return lib, covered


def _module_prefix(source_path: str) -> str:
    """This module's ABI qualifier — `module_loader.module_name_for_path`, the
    single source of truth both backends must use (its own docstring: "both
    MUST derive a struct's module-qualified symbol from the exact same
    function applied to the exact same resolved file path, or the two sides can
    disagree")."""
    try:
        from module_loader import module_name_for_path
        return module_name_for_path(os.path.abspath(source_path))
    except Exception:
        return re.sub(r"[^A-Za-z0-9_]", "_",
                      os.path.splitext(os.path.basename(source_path))[0])


def _abi_symbol(entry: dict):
    """The boundary symbol for a reflection entry, or None for a TYPE entry.

    `reflect.export_csym` is the single source of truth for this — the same
    function the gimple dylib's table and its `nm` cross-check use — so a
    formal dylib advertises exactly the symbols a gimple dylib would, and an
    importer cannot end up binding a name the other backend spells
    differently. It is a C identifier (no leading underscore); the Mach-O name
    is that with `_` prepended, which is what the export trie stores and what
    dyld looks up.

    A TYPE entry has no function symbol (and the formal path has no object
    model to represent one), so it yields None.
    """
    # Lazy: `reflect` imports gimple_codegen, and this path must never pull
    # the gimple engine in (the same reason _load_formal_build resolves
    # formal.build through importlib in fire.py).
    from reflect import SYM_TYPE, export_csym
    if entry.get("kind") == SYM_TYPE:
        return None
    try:
        return export_csym(entry)
    except Exception:
        return None


def _libsystem_handle():
    """A dlopen-able handle on the C library this image's load command names.

    `None` until the first call, then either a handle or `False` for "this host
    will not let us ask". Deliberately NOT `ctypes.CDLL(None)`: the global
    namespace contains everything the *building* process has loaded, so it
    answers questions about the compiler rather than about the target.
    Measured on this machine, same symbol, two handles:

        CDLL('/usr/lib/libSystem.B.dylib')   sqlite3_open -> False   correct
        CDLL(None)                           sqlite3_open -> True    WRONG

    because this python has libsqlite3 in its own global namespace. A build-time
    audit that inherits that would wave through exactly the symbols it exists to
    catch. `tools/formal_sweep.py` reached the same conclusion about its own
    earlier probe, and for the same reason, its own comment is explicit that the
    global namespace "is a false PASS".
    """
    global _LIBSYSTEM_HANDLE
    if _LIBSYSTEM_HANDLE is None:
        _LIBSYSTEM_HANDLE = False
        try:
            import ctypes
            import platform
            if platform.system() == "Darwin":
                from formal.macho_linker import LIBSYSTEM_PATH
                name = LIBSYSTEM_PATH.decode().rstrip("\0")
            else:
                from formal.elf import DEFAULT_LIBC
                name = DEFAULT_LIBC
            _LIBSYSTEM_HANDLE = ctypes.CDLL(name)
        except Exception:
            _LIBSYSTEM_HANDLE = False
    return _LIBSYSTEM_HANDLE


_LIBSYSTEM_HANDLE = None

# The 19 names this function used to hardcode, kept ONLY as the fallback for a
# host that will not let us dlopen its C library. They are a guess at names
# rather than a check of anything, which is the whole reason the real table
# exists; on such a host this is no worse than the behaviour being replaced.
_LIBSYSTEM_LEGACY = frozenset((
    "printf", "puts", "putchar", "malloc", "calloc", "realloc", "free",
    "memcpy", "memset", "strlen", "strcmp", "strncmp", "abort", "exit",
    "atoi", "qsort", "fmod", "pow", "sqrt",
))

# memo: bare symbol -> bool
_LIBSYSTEM_MEMO = {}


def _is_libsystem(sym: str) -> bool:
    """True for a symbol the C library this image links actually provides.

    The externs a library legitimately sends outward are the C library's own
    (`printf`, `malloc`, …), and those are declared by the libSystem load
    command the image already carries. Everything else has to come from a
    dependency's export table.

    This used to be a 19-name literal, which was a guess at names rather than a
    check of anything, and it was wrong in the direction that hides defects: a
    formal program calling `stat`, `clock_gettime`, `regcomp` or `arc4random_buf`
    — all of which libSystem genuinely provides, and all of which are the whole
    reason a module like `os` or `re` is in the *modelled* half of
    `formal/imports.py`'s host split — was reported as binding a symbol nothing
    provides. Now the answer comes from dlsym against the real library.

    The name asked about is `model.libc_source_name`'s, not the symbol's own
    spelling, and the difference is a whole architecture's worth: a
    `readdir$INODE64` in the symbol list is the 64-bit-inode `readdir(3)` (see
    `model.target_libc_symbol`), and the dlsym here runs in THIS python3, so it
    can only answer for the host — where that spelling may not exist at all. On
    an arm64 host asking about `readdir$INODE64` would report an x86-64 image's
    correct binding as a symbol nothing provides, which is a build refused over
    a name that is right.

    Memoised per symbol: this runs once per extern per build, and a dlsym per
    extern would be a needless syscall storm in a large program.
    """
    bare = M.libc_source_name(sym) if isinstance(sym, str) else sym
    if not bare:
        return False
    hit = _LIBSYSTEM_MEMO.get(bare)
    if hit is not None:
        return hit
    handle = _libsystem_handle()
    if handle is False:
        answer = bare in _LIBSYSTEM_LEGACY
    else:
        try:
            answer = hasattr(handle, bare)
        except Exception:
            answer = bare in _LIBSYSTEM_LEGACY
    _LIBSYSTEM_MEMO[bare] = answer
    return answer


def _libsystem_probe_status() -> str:
    """How the answer above was reached, for a diagnostic that depends on it.

    A build that fell back to the 19-name list is making a weaker claim than one
    that asked the library, and a reader of the audit output should be able to
    tell which happened rather than being told "nothing provides this symbol"
    with no indication that the question was only partly asked.
    """
    return ("asked the C library (dlsym)"
            if _libsystem_handle() is not False
            else "FALLBACK: this host would not let the build open its C "
                 "library, so a 19-name list was used instead")



def _export_entries(source_paths: list, prefixes: dict = None) -> dict:
    """{name: (prefix, entry, symbol)} for everything these files export.

    Split out of _formal_exports so the DECISION can be made before any code
    is emitted. Whether a module has a public API is a property of its source
    and of doc/ABI.md's export rules, not of what the codegen happens to
    manage; asking the question afterwards meant a struct-only module was
    refused with "no function definitions to compile", which reads like a
    codegen gap rather than "this file exports nothing"."""
    import reflect          # lazy — see _abi_symbol
    exported: dict = {}
    for src_path in source_paths:
        prefix = (prefixes or {}).get(src_path) or _module_prefix(src_path)
        with open(src_path) as f:
            text = f.read()
        for entry in reflect.collect_exports_src(text, prefix):
            symbol = _abi_symbol(entry)
            if symbol:
                exported.setdefault(entry["name"], (prefix, entry, symbol))
    return exported


def _declared_traits(source_paths: list) -> list:
    """The public TRAIT names `source_paths` declare at top level.

    A trait is a compile-time contract and a THIRD kind of top-level
    declaration, and until this function existed nothing in the export path
    could see one: `_declared_api_shape` buckets `FunctionDef` and `StructDef`
    only, and `reflect.collect_exports_src` — which every table here is built
    from, on purpose, so one rule decides what crosses — has no trait rule
    because a trait has no symbol. So a module whose whole API is traits read
    as a module that "declares no function and no type at all", and was
    refused with that sentence. It is false about the file: `AnyType` IS a
    type, `std/traits/anytype.mojo` declares one, and every read of the name in
    the standard library is a type position — `def f[T: AnyType](…)`,
    `var h: Some[Copyable]`.

    Measured on the new-modular stdlib: 11 of its 252 files are trait-only
    (`traits/{anytype,movable,copyable}`, `hashlib/hasher`, `os/pathlike`,
    `builtin/{comparable,enum_like,floatable,identifiable}`,
    `python/conversions`, `testing/prop/strategy/__init__`), and the five
    `codegen/dependency` lines `tools/formal_sweep.py` attributes to
    `anytype.mojo` are all this one module. See
    `formal_traits_namespace` for what a trait-only module builds as.
    """
    out = []
    for path in source_paths:
        try:
            with open(path) as f:
                stmts = F.Parser(F.py_tokenize(f.read())).parse_module()
        except Exception:
            # An unparseable file has no shape to report. Returning nothing
            # leaves it on the refusal it was already getting, so this can
            # never wave through a file the parser could not read.
            continue
        for st in stmts:
            if isinstance(st, F.TraitDef) and not st.name.startswith("_"):
                out.append(st.name)
    return out


def _declared_api_shape(text: str) -> dict:
    """What this source DECLARES, ignoring doc/ABI.md's rules — the input to
    `no_public_api_reason`.

    Eight buckets and the names behind them, because the question "why does this
    module export nothing" has several different true answers and picking the
    wrong one is what made the old single-sentence refusal useless:

      funcs / generic_funcs / private_funcs   top-level FunctionDefs
      structs / generic_structs / private_structs   top-level StructDefs
      traits / private_traits   top-level TraitDefs

    The `traits` bucket is what keeps a trait-only module's refusal true. It
    used to have no bucket at all, so `std/traits/anytype.mojo` — which
    declares `trait AnyType` and nothing else — was told it "declares no
    function and no type at all", which is false about the file. A trait is a
    type; the standard library only ever reads it in a type position. See
    `_declared_traits` for what a module made of them builds as.

    A definition is filed as a GENERIC TEMPLATE **per definition**, and for a
    function the test is the parser's own `FunctionDef.comptime_params` — the
    bracket list, recorded on that one def. It used to be a set of NAMES
    collected by regex over the whole text, which cannot tell `def exit():` from
    `def exit[intable: Intable](…)`: both were filed as templates, so
    `std/sys/terminate.mojo` was described as having no concrete public function
    when it defines one. `std/memory/memory.mojo` had the same defect on
    `memset_zero`, which it defines twice, once each way.

    For a STRUCT the text regex is still the only test, because `StructDef`
    carries no `comptime_params` at all — `fire_compiler.Parser` records a
    function's bracket list and drops a struct's. So this function and
    `reflect.export_exclusions` (the export rule itself) can disagree, and the
    disagreement is measured rather than assumed: over 380 .mojo/.py files, the
    name-keyed regex excludes exactly ONE top-level public concrete definition
    that a per-definition test would not — `join` in `std/os/path/path.mojo`,
    where a nested `def join[...]` inside another function puts the name in the
    set. Every other name the regex excludes is excluded anyway (it is private,
    a C library symbol, overloaded, or genuinely a template), so the two tests
    agree on every export decision in the corpus today.

    That residual is left alone on purpose. Reconciling it means changing
    `reflect`'s export rule, which changes which symbols reach a dylib — a
    change to what the compiler accepts, and not this function's to make. It is
    why every message below that could be contradicted by it is computed from
    `reflect.export_exclusions` rather than from these buckets.
    """
    generic_names = set(re.findall(r'\bstruct\s+(\w+)\s*\[', text))
    shape = {"funcs": [], "structs": [], "generic_funcs": [],
             "generic_structs": [], "private_funcs": [],
             "private_generic_funcs": [], "private_structs": [],
             "private_generic_structs": [], "traits": [], "private_traits": []}
    try:
        stmts = F.Parser(F.py_tokenize(text)).parse_module()
    except Exception:
        return shape
    for st in stmts:
        if isinstance(st, F.FunctionDef):
            # Per DEFINITION: the parser recorded this def's own bracket list.
            # Keying on a name set instead filed `def exit():` as a template
            # because some other `exit` in the same file spelled one.
            key = ("generic_funcs" if st.comptime_params else "funcs")
            (shape[key] if not st.name.startswith("_")
             else shape["private_" + key]).append(st.name)
        elif isinstance(st, F.StructDef):
            # No per-definition signal exists for a struct (see the docstring),
            # so this one is still the name-keyed text test.
            key = "generic_structs" if st.name in generic_names else "structs"
            (shape[key] if not st.name.startswith("_")
             else shape["private_" + key]).append(st.name)
        elif isinstance(st, F.TraitDef):
            # A trait is neither parametric (the parser records no bracket list
            # on `TraitDef`) nor a layout, so the one bucket is the whole test.
            # It matters because a module made only of traits reads as EMPTY to
            # every other bucket here, and the refusal that follows says the
            # file "declares no function and no type at all".
            key = "private_traits" if st.name.startswith("_") else "traits"
            shape[key].append(st.name)
    return shape


def no_public_api_reason(source_paths: list) -> str:
    """The refusal text for a module that exports nothing, naming WHY.

    Every one of these files is a real module that a real file imports, so the
    refusal is load-bearing: it is what stops a program from being handed a
    link line with nothing on it. What it must therefore also do is SAY which
    of the ways a module can have no boundary symbol it has hit, because they
    need different work and the reader cannot tell them apart from the old
    wording:

      * it declares nothing at all (module-level `comptime` constants only —
        `std/sys/_io.mojo`'s `stdin`/`stdout`/`stderr`): there is no
        function and no type to cross, and there never will be;
      * every public function is a GENERIC template (`std/stat/stat.mojo`'s
        seven `S_ISxxx[intable: Intable]`): doc/ABI.md is explicit that a
        generic is not a single boundary symbol, each INSTANTIATION is, and
        the CAS keying that needs is Stage 5. Until monomorphization exists
        on this path there is no name an importer could bind;
      * only struct TYPES, no free functions: the boundary symbol for a type
        is its layout in the reflection table (which this backend does not
        emit), so a type alone gives a dylib nothing to export;
      * every declaration is private (`_`-prefixed), which doc/ABI.md's
        public-symbol rule excludes on purpose;
      * every public name is a C LIBRARY SYMBOL (`std/sys/terminate.mojo`'s
        `exit`), which this path resolves with `dlsym` out of the system
        dylibs and so does not advertise.

    The generic case is the one worth being careful about in the OTHER
    direction: exporting a template under its base name would be easy and
    would make these files build, and it would be wrong. `S_ISREG` as one
    symbol is one function; called at `Int` and at some other `Intable` it is
    two, and only one address can be in the trie. Publishing a link line that
    can silently bind the wrong body is the failure this whole mechanism
    exists to prevent, so the honest answer is the refusal until the
    instantiation keying lands.

    **A branch may only claim what it checked.** Three of the branches below
    used to assert a fact that is not true of the file they fired on, which is
    worse than no message: it sends the next reader looking for a construct the
    file does not contain. Two of them gated a claim about a SET on the set
    being NON-EMPTY and then asserted something about its ELEMENTS, and the
    third was reached by every module the four named branches did not cover, so
    it described a rule (privacy) that had never been applied. Hence the two
    changes here: the "private and parametric" branch gates on the
    INTERSECTION, and the fall-through computes each name's reason from
    `reflect.export_exclusions` — the same function the export table is built
    from, so a message cannot name a rule the export did not apply."""
    import reflect          # lazy, as in _export_entries — one rule, not two
    names = [os.path.basename(p) for p in source_paths]
    head = f"formal dylib has no public functions: {', '.join(names)}"
    shapes = []
    excluded: dict = {}
    for p in source_paths:
        try:
            with open(p) as f:
                text = f.read()
        except OSError:
            text = ""
        shapes.append((os.path.basename(p), _declared_api_shape(text)))
        try:
            excluded.update(reflect.export_exclusions(text))
        except Exception:
            # An unparseable file has no shape to report; the fall-through then
            # says so rather than inventing a reason for it.
            pass
    concrete_funcs = [n for _f, s in shapes for n in s["funcs"]]
    concrete_structs = [n for _f, s in shapes for n in s["structs"]]
    gen_funcs = [n for _f, s in shapes for n in s["generic_funcs"]]
    gen_structs = [n for _f, s in shapes for n in s["generic_structs"]]
    traits = [n for _f, s in shapes for n in s["traits"]]
    private = [n for _f, s in shapes
               for k in ("private_funcs", "private_generic_funcs",
                         "private_structs", "private_generic_structs",
                         "private_traits")
               for n in s[k]]
    if not concrete_funcs and not concrete_structs and not gen_funcs \
            and not gen_structs and not traits:
        if private:
            listed = ", ".join(sorted(set(private))[:6])
            return (f"{head} exports nothing under doc/ABI.md's rules: every "
                    f"declaration in it is private ({listed}), and a private "
                    f"name is excluded from the boundary on purpose — the "
                    f"leading underscore is the source saying this is not for "
                    f"another module.")
        return (f"{head} exports nothing under doc/ABI.md's rules because it "
                f"declares no function and no type at all — only module-level "
                f"constants, which are inlined at their use site and cross no "
                f"boundary. There is nothing an importer could bind, and "
                f"nothing this backend could add.")
    # The C-LIBRARY-SYMBOL case, checked before the generic ones because it is
    # the only rule that is a NAME test rather than a shape test, so it can hold
    # whatever the declarations look like. Its exclusion is right for a CALL and
    # wrong for a DEFINITION, which is worth saying: `terminate.mojo` DEFINES
    # `exit`, and if it also exported one other name then an importer's `exit()`
    # would bind libSystem's, silently, with no diagnostic. So the message names
    # the hazard instead of only the rule.
    public_names = [n for n in (concrete_funcs + concrete_structs
                                + gen_funcs + gen_structs)]
    clib_only = sorted({n for n in public_names
                        if excluded.get(n) == reflect.EXCL_CLIB})
    if public_names and len(clib_only) == len(set(public_names)):
        listed = ", ".join(clib_only[:6])
        return (f"{head} exports nothing under doc/ABI.md's rules: every name "
                f"it declares ({listed}{' …' if len(clib_only) > 6 else ''}) is "
                f"a C library symbol, which this path resolves with `dlsym` out "
                f"of the system dylibs and so does not advertise. The rule is "
                f"right for a CALL and wrong for a DEFINITION, and this file "
                f"DEFINES the name: if it also exported one other symbol, an "
                f"importer's `{clib_only[0]}()` would bind the system's, "
                f"silently, with no diagnostic. Nothing in this module needs "
                f"exporting until it declares a name the C library does not "
                f"already provide.")
    # A branch that said "the ONLY function it declares is the generic template
    # …, which is both private and parametric" used to live here, gated on the
    # module having ANY private declaration. It is DELETED rather than
    # re-gated, and the reason is worth keeping: its two facts come from
    # disjoint sets, so no input reaches it. `gen_funcs` holds only names that
    # do NOT start with `_` and `private` holds only names that do, so
    # `set(gen_funcs) & set(private)` is empty for every possible module — the
    # suggested repair (gate on the intersection) would have made the branch
    # unreachable, which is the same defect wearing a fix.
    #
    # And nothing is lost: the module that branch was written for,
    # `std/utils/_select.mojo`, whose only declaration is the private template
    # `_select_register_value`, is caught by the FIRST branch above, which says
    # the true thing and says it in one sentence — every declaration in it is
    # private, and here it is. Its false readings were on the two shapes the
    # gate let through: `std/memory/unsafe.mojo` (two PUBLIC generics and one
    # private helper, told its only function was "bitcast, pack_bits … both
    # private and parametric") and anything with a public struct beside a
    # private template. Both now take a branch whose claim is about names it
    # has actually looked at.
    if not concrete_funcs and gen_funcs:
        listed = ", ".join(sorted(set(gen_funcs))[:6])
        return (f"{head} exports nothing under doc/ABI.md's rules: every "
                f"public function in it is a GENERIC template ({listed}"
                f"{' …' if len(set(gen_funcs)) > 6 else ''}), and doc/ABI.md "
                f"is explicit that a generic is not a single boundary symbol "
                f"— each INSTANTIATION is, keyed in the CAS by its type "
                f"arguments. That monomorphization is Stage 5 and this path "
                f"does not do it, so there is no name an importer could bind. "
                f"Exporting the template under its base name instead would be "
                f"wrong, not conservative: one trie entry cannot be two "
                f"instantiations, so a call with different type arguments "
                f"would silently bind the first one's body.")
    if not concrete_funcs and not gen_funcs and not concrete_structs \
            and gen_structs:
        listed = ", ".join(sorted(set(gen_structs))[:6])
        return (f"{head} exports nothing under doc/ABI.md's rules: it "
                f"declares only the generic struct template(s) {listed}, and a "
                f"parametric type has no single boundary layout either.")
    if not concrete_funcs and concrete_structs:
        listed = ", ".join(sorted(set(concrete_structs))[:6])
        return (f"{head} exports nothing under doc/ABI.md's rules: it has no "
                f"free function, only the struct type(s) {listed}. A type "
                f"crosses the boundary as its layout in the reflection table, "
                f"which this backend does not emit.")
    return _excluded_names_reason(head, excluded, public_names, reflect)


# Why each rule of doc/ABI.md's export rule is what it is, in the words the
# refusal uses — a function, not a module-level dict, because `reflect` is
# imported LAZILY here (see `_export_entries` and `_abi_symbol`: the gimple
# reflection module pulls the whole compiled backend in with it, and the
# formal backends do not otherwise need it). Keyed by `reflect`'s own
# constants, so a rule added there and not here shows up as a name with no
# reason rather than being silently folded into another rule's sentence — which
# is the failure this function exists to prevent.
def _exclusion_why(reflect) -> dict:
    return {
        reflect.EXCL_PRIVATE: (
            "a private name (a leading `_`), which the public-symbol rule "
            "excludes on purpose: the underscore is the source saying this is "
            "not for another module"),
        reflect.EXCL_CLIB: (
            "a C library symbol this path resolves with `dlsym` out of the "
            "system dylibs — right for a call, wrong for a definition, since an "
            "importer's call would bind the system's rather than this "
            "module's"),
        reflect.EXCL_OVERLOADED: (
            "declared more than once with different signatures, and one trie "
            "entry cannot be two instantiations"),
        reflect.EXCL_GENERIC: (
            "a GENERIC template, and a generic is not a single boundary symbol "
            "— each INSTANTIATION is, keyed in the CAS by its type arguments, "
            "which is Stage 5 and this path does not do it"),
    }


def _excluded_names_reason(head: str, excluded: dict, public_names: list,
                           reflect) -> str:
    """The fall-through: name the rule that excluded each public name, or say so.

    This is what every module the named branches do not cover lands on, and it
    used to be a sentence about PRIVACY — "every declaration in it is private (a
    leading `_`)" — reached by any module with at least one concrete public
    function that exports nothing. `std/memory/memory.mojo` has fifteen public
    functions and four private ones and was told it had none.

    So it states, per name, the rule `reflect.export_exclusions` applied, which
    is the same function `_export_entries` builds the table from: the message
    cannot name a rule the export did not apply, and every clause in it is
    computed rather than assumed. When the exclusion table has nothing to say —
    an unparseable file, or a name whose only declaration is nested — it says
    that instead of inventing a reason, because a refusal that asserts a
    falsehood is worse than one that admits it does not know."""
    why_of = _exclusion_why(reflect)
    groups: dict = {}
    for name in sorted(set(public_names)):
        why = excluded.get(name)
        if why in why_of:
            groups.setdefault(why, []).append(name)
    if not groups:
        return (f"{head} exports nothing under doc/ABI.md's rules. Its public "
                f"declarations ({', '.join(sorted(set(public_names))[:6])}) are "
                f"not excluded by any of the four rules of the public-symbol "
                f"rule, so this is not a fact about the module's shape and "
                f"nothing here names the cause — report it rather than trusting "
                f"this sentence, which is saying that it does not know.")
    clauses = []
    for why in sorted(groups, key=lambda k: sorted(groups[k])):
        listed = ", ".join(groups[why][:6])
        more = " …" if len(groups[why]) > 6 else ""
        clauses.append(f"{listed}{more} because it is {why_of[why]}")
    return (f"{head} exports nothing under doc/ABI.md's rules. Each of its "
            f"public declarations is excluded by the public-symbol rule, and "
            f"the rule that excluded it is named here rather than assumed: "
            f"{'; '.join(clauses)}.")


def _method_exports(source_paths: list, structs_by_file: dict,
                    prefixes: dict = None) -> dict:
    """{compiled function name: (module, symbol, signature)} for methods.

    Built here rather than inside _formal_exports because the module qualifier
    is a property of the FILE a struct was declared in, and only the caller
    knows which file that was. Naming is doc/ABI.md's: module-qualified, so
    two modules' same-named structs cannot collide in one library.

    A method of a WIDE struct is exported too, and the filter that used to
    exclude it here was a wave-3 leftover whose own comment says so: "refused
    at lift time, never compiled".  That was true when a multi-field struct had
    no representation at all.  It stopped being true the moment the by-reference
    receiver landed — a wide struct's method IS compiled, its receiver word is
    the frame's address, and `_struct_methods` lifts it on exactly the
    `struct_is_framed` condition.  So the filter was dropping the export of code
    that was in the library, and an importer's `S_get(...)` call had no symbol
    to bind to.

    Measured, on two files differing in nothing but the field count: a one-field
    struct's method appears in the manifest and a two-field struct's does not,
    with the same code path and the same `_export_entries` probe — which finds
    `S.get` in both cases, so the export SET was never the thing excluding it.
    With the filter gone, a two-field struct's method is advertised, the call
    binds, and the program returns the value the source computes on both
    architectures.

    The hand-off is sound rather than merely possible, and the reason is the one
    `bugs/FORMAL_wide_receiver_by_reference.md` gives for the by-reference design
    itself: the callee is a method of the receiver's OWN struct, and the
    importer derived that struct's field list from this very file
    (`imported_struct_defs`), so `base + 8k` is computed from the same field
    list on both sides of the boundary.  What a frame address is NOT meaningful
    to is an extern, or code compiled against a different declaration — and
    `_check_frame_escapes` still refuses both.
    """
    out = {}
    for src_path, structs in (structs_by_file or {}).items():
        prefix = (prefixes or {}).get(src_path) or _module_prefix(src_path)
        for st in structs:
            for m in M.struct_methods(st):
                out[M.method_function_name(st.name, m.name)] = (
                    prefix,
                    M.abi_method_symbol(prefix, st.name, m.name),
                    f"{st.name}.{m.name}")
    return out


def _formal_exports(source_paths: list, ordered: list, info: dict,
                    prefixes: dict = None, methods: dict = None) -> list:
    """The library's export table, per doc/ABI.md's boundary contract.

    The export SET is decided by `reflect.collect_exports_src` — the same
    function the gimple dylib uses — so both dylibs advertise the same things
    and a client cannot find a symbol in one that the other omits. That
    function is also what keeps the awkward cases honest: a private (`_`)
    name, a generic template (no single concrete symbol exists) and an
    overloaded name (selected per call site, not one symbol) are all excluded
    rather than exported under a name that means something else.

    The SYMBOL spelling is the ABI's: a free function is bare (`name`), and a
    struct method is module-qualified (`<module>_<Struct>_<method>`) so two
    modules' same-named structs never collide. The formal path has no object
    model, so no method is compiled here — but the naming is the ABI's so that
    a method can be added without renaming anything.
    """
    # An explicit identity wins: a package's `__init__.mojo` has no
    # distinguishing FILE name, so deriving the qualifier from the path gives
    # every package the same `_init_` — the exact collision
    # module_name_for_path exists to prevent (it can only disambiguate under
    # STDLIB_PATH; a local sibling package is addressed by the module name the
    # importer used). The set itself is the probe's, computed before codegen.
    exported = _export_entries(source_paths, prefixes)
    out = []
    emitted = set()
    # A function that RETURNS A FRAME ADDRESS is not exportable, and the
    # refusal is here rather than in the emitter because the emitter has no
    # idea the function is being offered at a boundary.  The reason is the
    # hidden word: the returned-frame convention is "the caller reserves a
    # block and passes its address as one trailing argument", and that is a
    # property of ONE image's calling convention.  An importer compiled the
    # module's source with its own `_frame_receivers` pass, has no table saying
    # which of this library's functions take the extra word, and passes
    # arguments the way the source spells them — so an exported one copies its
    # caller's block into whatever the seventh argument register held.
    frame_returns = [fn.name for fn in ordered
                     if getattr(fn, "_frame_return_status", None) == _RETURN_FRAME]
    offered = [n for n in frame_returns
               if n in exported or n in (methods or {})]
    if offered:
        raise CodegenError(M.dylib_frame_return_refusal(
            source_paths[0] if source_paths else "this module",
            sorted(offered)))
    for fn in ordered:
        # An overload was renamed to `<name>__ovN` above, so it no longer
        # matches — which is what keeps a name that reflect *did* export from
        # being emitted twice, once per definition. `emitted` states that as an
        # invariant rather than relying on the rename: two trie entries with
        # one symbol is not a de-duplication problem, it is a corrupt export
        # table that dyld resolves to whichever it finds first.
        if fn.name in emitted:
            continue
        if fn.name in (methods or {}):
            # A struct method is part of the module's API even when the module
            # has no free functions at all, which is the whole of a
            # struct-only module like std/collections/binary_heap. Without
            # this, such a module exports nothing, cannot be built as a
            # dylib, and every importer of it fails.
            emitted.add(fn.name)
            module, symbol, signature = methods[fn.name]
            out.append({
                "module": module,
                "name": fn.name,
                "symbol": symbol,
                "entry": info["labels"][fn.name],
                # The receiver is the first parameter and an importer's call
                # passes it, so the arity recorded is the whole signature.
                "arity": len(fn.params),
                "call": M.export_call_contract(fn),
                "signature": signature,
                "kind": "method",
                "frame_params": _export_frame_contract(fn),
            })
            continue
        if fn.name not in exported:
            continue                      # private, generic, or overloaded
        emitted.add(fn.name)
        prefix, entry, symbol = exported[fn.name]
        out.append({
            "module": prefix,
            "name": fn.name,
            "symbol": symbol,
            "entry": info["labels"][fn.name],
            "arity": len(fn.params),
            "call": M.export_call_contract(fn),
            "signature": entry.get("signature", ""),
            "kind": entry.get("kind"),
            "frame_params": _export_frame_contract(fn),
        })
    return out


def _export_frame_contract(fn) -> list:
    """The per-parameter frame-holder contract this export publishes, or [].

    Read off `fn._frame_param_contract`, which `_frame_receivers` published
    from the holder fixpoint — the same table the emitters read `self` from
    for a field load, so what a consumer is told is what the callee's own code
    was compiled to do rather than a second opinion about it.

    `[]` when the function has no contract table, which is the honest "this
    compilation could not classify it": a FunctionDef that never went through
    `_frame_receivers` (a synthetic one, say) rather than a function whose
    parameters are all ordinary words — that case publishes a list of `None`s,
    which is a different and much more useful thing to say.

    The names are the callee module's own struct names, and a consumer
    compares them against the structs it has in hand. Two modules declaring
    different `P`s is a real possibility on this path and the contract makes it
    VISIBLE rather than assumed, which is the property that makes following the
    address sound: `base + 8k` means the same thing on both sides only because
    both computed it from the same field list, and "the same field list" is
    exactly what the consumer checks.
    """
    contract = getattr(fn, "_frame_param_contract", None)
    if contract is None:
        return []
    return [[st for st in entry] if isinstance(entry, list) else None
            for entry in contract]


def _record_link_deps(manifest_path: str, linked: list) -> None:
    """Note the libraries this dylib links, so a program can close the set."""

    def _record(payload):
        payload["links"] = [{"install_name": d["install_name"],
                             "path": d.get("path")} for d in linked]

    update_dylib_manifest(manifest_path, _record)


def _namespace_library(output: str, install_name: str, arch: str,
                       reexports: dict, dylib_syms: dict, dep_install: list,
                       linked: list, module: str = None,
                       constants: dict = None, traits: list = None,
                       source: str = None) -> dict:
    """A dylib for a module whose whole API is RE-EXPORTED — a package
    `__init__.mojo` — or whose whole API is TRAIT DECLARATIONS.

    This is the shape that was being refused as "a struct-only module has no
    free-function API", which it is not: `pkg/__init__.mojo` containing
    `from .sub import addone` has a real, public, importable API, and
    `addone` really exists — in `pkg/sub.mojo`, whose dylib this package's
    link line already carries. Refusing it took out every file that imports the
    PACKAGE, for a module that had nothing wrong with it, and it did so on
    every stdlib package: `std/stat`, `std/atomic`, `std/ffi`, `std/compile`,
    `std/sys`, `std/reflection`, `std/gpu/sync` and the rest are all
    re-export-only `__init__` files.

    What it emits is a real MH_DYLIB with NO code and an EMPTY export trie,
    and that emptiness is the whole design, not a shortcut. The re-exported
    names are NOT copied into this library's export table. They already
    resolve: the consumer's symbol map is assembled from the manifests of
    every library on its link line, and `pkg_sub.dylib`'s manifest maps
    `addone` to the symbol `pkg_sub.dylib` really defines. Re-listing that
    symbol here would be actively harmful — the export trie is an address
    lookup, so a trie claiming a symbol this image does not contain sends
    every consumer of the package to an address inside an empty file, and
    the program dies in dyld (or, worse, binds something). The one outcome
    worse than refusing.

    So the manifest records the re-exports under `reexports` (for a reader and
    for `depends_on`) and leaves `exports` empty, and `load_dylib_manifests`
    accepts an empty `exports` list ONLY for a manifest that says
    `kind: "namespace"` — the check it otherwise makes, that a library with
    nothing to offer is a mistake worth refusing, stays in force for every
    other library.

    A re-exported FUNCTION that no dependency actually provides is still
    refused, naming the name. Otherwise the package would build, the
    consumer's call would stay unbound, and the failure would move from this
    build to dyld at launch — which is the exact regression the import
    machinery exists to remove.

    A re-exported TYPE is not in that set, and must not be: a type has no
    function symbol to bind. It crosses as a layout in the reflection table
    and reaches the importer as a StructDef, which `imported_struct_defs`
    collects by following the same re-export edge. Treating "no symbol for it"
    as a missing definition would refuse every package that re-exports a type,
    which is most of them, and would be refusing a module whose API is
    complete.

    **A TRAIT-ONLY module belongs here too, and for the same reason one step
    earlier.** A trait is a compile-time contract: it names a set of method
    SIGNATURES, and this backend dispatches a method by name on the receiver's
    own type (`_struct_methods` lifts a struct's methods; nothing resolves a
    name to a trait). So a trait-only module has no code to emit — no default
    method body is reachable through it, because reaching one would need
    dispatch through the trait, which does not exist on this path. Measured, in
    both directions: a trait default method called on a value is refused by the
    method-call refusal naming the receiver, identically whether the trait is
    declared in the same file or imported from a module (both are refused by
    `model`'s one message), and a struct that defines the method itself is
    lowered from the STRUCT and answers correctly. So an empty trie here loses
    no reachable code.

    The traits are recorded under `traits` rather than `reexports`, and the
    difference is load-bearing rather than tidiness: a re-export is a name this
    module FORWARDS to a definition elsewhere, so a consumer binds it through
    the submodule's symbol; a trait is DECLARED here and has no symbol at all.
    Filing a trait under `reexports` would put it in the "must be provided as a
    symbol" check above — the message for a missing function DEFINITION — and
    refuse the module over a name it declares itself. `load_dylib_manifests`
    reads `traits` so the names are visible to a reader without re-parsing the
    source, the same reason `module` and `reexports` are read back.
    """
    functions = {n: v for n, v in reexports.items() if v[1] != "type"}
    # A re-exported name is missing only if NO module this one imports provides
    # it — by SYMBOL or, for a constant, by VALUE. A constant has no symbol to
    # forward, so counting it missing refused every package that re-exports one
    # (`from .limits import NAME`), and the message pointed at a missing
    # definition where the value was sitting in a manifest on the same link
    # line. The constants table is keyed by MODULE, so the names are its
    # values' keys — asking it for the modules instead would make every
    # re-exported constant look missing again, which is the bug.
    dep_constants = M.dylib_module_constants(dylib_export_lists(linked))
    provided = set(dylib_syms) | {name for table in dep_constants.values()
                                  for name in table}
    missing = sorted(n for n in functions if n not in provided)
    if missing:
        listed = ", ".join(missing[:8])
        mods = ", ".join(sorted({functions[n][0] for n in missing})[:4])
        raise FormalBuildError(
            f"{os.path.basename(install_name)} re-exports {listed} from {mods}, "
            f"but no module it imports exports "
            f"{'that name' if len(missing) == 1 else 'those names'}, so a "
            f"caller of {'it' if len(missing) == 1 else 'them'} would have "
            f"nothing to bind. This is a real gap in that module's public API "
            f"— a private, generic or overloaded definition, all of which "
            f"doc/ABI.md keeps out of the boundary — and not something this "
            f"backend can paper over: emitting a link line with no definition "
            f"behind it turns a build error into a wrong answer at run time.")
    binary = build_macho_dylib(b"", TEXT_BASE + dylib_code_offset(
        install_name, False, dep_install), [], install_name, arch=arch,
        deps=dep_install or None)
    with open(output, "wb") as f:
        f.write(binary)
    os.chmod(output, 0o755)
    _ad_hoc_sign(output)
    manifest_path = write_dylib_manifest(output, install_name, [], source=source,
                                         module=module, constants=constants)
    _record_namespace(manifest_path, reexports, dylib_syms, traits=traits)
    if linked:
        _record_link_deps(manifest_path, linked)
    return {
        "manifest_path": manifest_path,
        "path": output,
        "code": b"",
        "binary": binary,
        "info": {"labels": {}},
        "exports": [],
        "reexports": reexports,
        "traits": list(traits or []),
        "backend": f"{arch}/macho-dylib-namespace",
    }


def _namespace_constants(reexports: dict, own: dict, linked: list) -> dict:
    """The constants a namespace library publishes: its own, plus the ones it
    RE-EXPORTS.

    A package `__init__` that is nothing but `from .x import NAME` publishes
    `NAME` as part of its API whatever `NAME` is, and a re-exported CONSTANT is
    the one kind that needs no symbol to forward: the value is a literal, so the
    consumer materializes the same one in its own image. The library that
    DEFINES it is already on this one's link line and its value is already in
    that library's manifest, so this is a copy of a fact rather than a second
    derivation of it — and the name is looked up in the dependencies' published
    constants rather than re-folded from source, because the build that folded
    it is the one whose answer counts.

    `kind` here is `declared_kinds`' verdict on the DEFINING declaration, and a
    module-level binding is not a declaration it recognizes, so a re-exported
    constant arrives as `"unknown"` — which is exactly why it must be looked up
    rather than trusted to be a function. A name that is a function re-export
    keeps its own route (the `reexports` forwarding), and a name that is a TYPE
    has no value of this kind at all."""
    out = dict(own or {})
    tables = M.dylib_module_constants(dylib_export_lists(linked))
    for name, (_module, kind) in (reexports or {}).items():
        if kind != "unknown" or name in out:
            continue
        for value in _constants_named(tables, name):
            out[name] = value
            break
    return out


def _record_namespace(manifest_path: str, reexports: dict,
                      dylib_syms: dict, traits: list = None) -> None:
    """Mark a manifest as a NAMESPACE library and record what it forwards.

    The `kind` field is what makes an empty `exports` list legal to read back
    (`load_dylib_manifests`): it is the difference between "this library
    defines nothing, and that is its purpose" and "this library's manifest is
    empty, which means the build went wrong". Each re-export records the
    SYMBOL it resolves to, taken verbatim from the defining module's own
    manifest, so a reader can check the forwarding without re-deriving it.

    `traits` is the trait-only module's equivalent record, under its own key
    rather than under `reexports`, and the reason it is not folded into that
    one is that the two entries mean different things to a reader: a re-export
    says "this name is DEFINED elsewhere, and here is its symbol", while a
    trait says "this name is DECLARED here and has no symbol anywhere". A
    reader that wanted to check that every published name binds would look in
    `reexports` and find, for a trait, no symbol to check — which is the true
    fact, but stated in the one field whose contract is "there is a symbol".
    """
    def _mark(payload):
        payload["kind"] = "namespace"
        payload["reexports"] = {
            n: {"module": v[0], "kind": v[1], "symbol": dylib_syms.get(n)}
            for n, v in sorted(reexports.items())}
        if traits:
            # Absent rather than empty for a pure re-export package: the key
            # means "this library declares traits", and writing `[]` there
            # would claim a module with traits and none, which is a different
            # file.
            payload["traits"] = sorted(set(traits))

    update_dylib_manifest(manifest_path, _mark)


def compile_formal_dylib(source_paths: list, output: str = None,
                         test_input: int = 10, prove: bool = True,
                         check: bool = True, module_prefixes: dict = None,
                         link_dylibs: list = None, arch: str = "arm64",
                         fmt: str = "macho", reexports: dict = None) -> dict:
    """Compile `source_paths` into one dylib for `arch`.

    `arch`/`fmt` select the CODEGEN and the container, exactly as
    `compile_formal` does for an executable (`_make_codegen` /
    `arch_spec`). This used to be hardwired to arm64, which meant a module
    dylib was ALWAYS an arm64 image no matter which architecture the program
    linking it was built for: an x86-64 program got an arm64 `.dylib` on its
    link line, built and linked cleanly, and then died in dyld with "mach-o
    file, but is an incompatible architecture" before `main` ever ran. The
    dylib is part of the target, not part of the host, so the architecture
    the CALLER is for is the architecture the library has to be.

    `reexports` ({name: module}) is the set of names this module binds with
    `from .other import name` and does not itself define. It changes the
    refusal below and nothing else: a package `__init__` whose whole body is
    re-exports produces a NAMESPACE library (see `_namespace_library`) instead
    of an error, because its API is real and its definitions live in the
    submodules already on its link line.
    """
    if not source_paths:
        raise FormalBuildError("at least one source file is required")
    # `fmt` selects the CODEGEN, which is real — there is an x86-64 code
    # generator. What has no x86-64 (or ELF) form here is the CONTAINER:
    # `build_macho_dylib` is the only emitter on this path, and
    # `formal/elf.py` builds executables with no `.dynamic`/`.dynsym`/
    # `.dynstr`/`.hash` writer at all. So a `fmt` that asks for anything else
    # is refused by name.
    #
    # The previous condition was `not fmt_wants_macho(arch) and fmt != "macho"`,
    # which on a Mach-O host is `False and …` for EVERY `fmt` — so `fmt="elf"`
    # on macOS was accepted, ignored, and returned a Mach-O labelled by the
    # caller's own argument. An argument that reads like it is doing something
    # and does not is worse than a hardcoded literal: the caller gets an
    # artifact it did not ask for and no diagnostic. Refusing says the gap is
    # the container, which is where the work is.
    if fmt != "macho":
        raise FormalBuildError(
            f"a formal dylib is a Mach-O container; {fmt!r} was asked for and "
            f"this path has no {fmt} dylib emitter (formal/elf.py builds "
            f"executables only — no .dynamic/.dynsym/.dynstr/.hash). The code "
            f"generator is selected by arch={arch!r} and does honour it; the "
            f"container is the missing half.")
    reexports = dict(reexports or {})

    # The libraries THIS library links. Their export spellings decide how a
    # cross-module call is named — a call to a sibling's `base` has to become a
    # reference to `leaf_base_<hash>`, or the library builds and then fails to
    # load with "Symbol not found" for a function its sibling defines.
    linked = load_dylib_manifests(link_dylibs)
    ordered = []
    seen: dict = {}
    structs_by_file: dict = {}
    # What this library PUBLISHES besides its symbols, and it is two things.
    #
    # (a) the module-level names its own build folded to literals, which a
    # consumer materializes in its own image rather than reading an address for
    # (there is nowhere for one to live — `bugs/FORMAL_module_state_no_storage.md`
    # — and a literal does not need one). Collected from the module's own symbol
    # table, so the values are the ones THIS build folded rather than a second
    # reading of the source.
    constants: dict = {}
    # (b) the library's merged module-global slot table, published before the
    # codegen runs because every slot access is an absolute address computed
    # against it. Built by hand here rather than by re-running
    # `collect_global_slots`, because a library is compiled from SEVERAL
    # sources and each one's table numbers its own slots from zero.
    library_slots: dict = {}
    library_slot_owners: dict = {}
    for source_path in source_paths:
        module, functions, module_source, file_structs, file_slots, \
            file_constants = \
            _formal_module_functions(source_path, link_dylibs, arch=arch,
                                     fmt="macho", link_manifests=linked)
        structs_by_file[source_path] = file_structs
        for name, value in file_constants.items():
            constants.setdefault(name, value)
        for name, slot in (file_slots or {}).items():
            owner = library_slot_owners.get(name)
            if owner is not None:
                # Two files of ONE library both declaring the same module-level
                # name is a genuine collision, not something to resolve: a slot
                # is placed by its BARE name, so one `COUNT` in two files would
                # silently share a word. (In Mojo they are `a.COUNT` and
                # `b.COUNT`; this backend carries no module identity at a use
                # site, which is the same limit
                # `FORMAL_module_attribute_access_refused` records for
                # module-attribute CALLS.) Refused by name, naming BOTH files,
                # rather than one of them silently winning by ordering.
                raise FormalBuildError(
                    f"{source_path}: module-level name {name!r} is also "
                    f"declared in {owner}, and this library compiles both files "
                    f"into one image, so the two would share a single word. A "
                    f"module global is placed by its bare name on this path, so "
                    f"two files of one library cannot both declare it")
            library_slots[name] = M.GlobalSlot(name, len(library_slots),
                                               slot.init, slot.site)
            library_slot_owners[name] = source_path
        for fn in functions:
            # A repeated name is an OVERLOAD, not a collision — and Mojo
            # overloads are ordinary (`def tile[...]` appears three times in
            # std/algorithm/backend/tile.mojo alone). Refusing them was wrong
            # twice over: the message named the same file on both sides, and
            # doc/ABI.md already excludes an overloaded name from the export
            # set precisely because no single symbol denotes it, so there is
            # nothing to disambiguate at the boundary.
            #
            # Both definitions are still kept, because dropping the second
            # would silently discard code. They are renamed apart because the
            # codegen keeps ONE registry keyed by name (`self._functions`), so
            # leaving them as-is would let the last definition displace the
            # first with no diagnostic. The first keeps the source name, so a
            # call in this module still resolves; a call that wanted the
            # second overload resolves to the first, which is the documented
            # limit of name-based dispatch here — and no importer can ask for
            # the second by symbol, since the export set excludes it.
            n = seen.get(fn.name, 0)
            seen[fn.name] = n + 1
            if n:
                fn.name = f"{fn.name}__ov{n + 1}"
            ordered.append(fn)

    # The gimple runtime's C library, on THIS library's link line, for the same
    # reason and under the same condition as on the executable path — and here it
    # is not tidiness. A module dylib that binds `mojo_strlen` has a symbol in
    # its own bind stream, and the ordinal that name gets is an index into THIS
    # image's LC_LOAD_DYLIB list. Without the load command here, that ordinal
    # names whatever library happens to sit at that position, and the library
    # builds, links, passes the audit below, and then calls the wrong function.
    # LAST again, for the same precedence reason as `compile_formal`, and gated
    # on the library really providing the name for the same reason.
    runtime_lib, _covered = _runtime_library_for(ordered, arch, fmt)
    if runtime_lib is not None:
        linked = linked + [runtime_lib]
    # Same reason and same check as the image path: a sibling library in the
    # wrong container is on this library's `deps` list and will be written into
    # its load commands, so the loader is told to open a file it cannot open.
    _audit_link_line_containers(linked, fmt, "library")
    dylib_syms = {}
    for d in linked:
        for bare, mangled in (d.get("map") or {}).items():
            dylib_syms.setdefault(bare, mangled)
    # …and the export ENTRIES, in the same order, for the two things the flat
    # map cannot answer: a DOTTED sibling call (`leaf.base(x)` resolved by
    # module identity, which the map's first-wins-per-bare-name cannot
    # express) and a call's declared return kind.
    dylib_exports = dylib_export_lists(linked)
    dep_install = [d["install_name"] for d in linked]
    dep_syms = {d["install_name"]: list((d.get("map") or {}).values())
                for d in linked}

    if output is None:
        stem = os.path.splitext(os.path.basename(source_paths[0]))[0] or "module"
        output = os.path.join(
            os.path.dirname(os.path.abspath(source_paths[0])),
            stem + ".dylib")
    install_name = "@rpath/" + os.path.basename(output)
    # A library that calls out carries extra load commands (__DATA_CONST and an
    # LC_LOAD_DYLIB for libSystem), which move its code — so the base the code
    # is emitted for, the stub addresses its call sites branch to, and the
    # image the emitter builds must all be derived for the SAME decision. The
    # first pass discovers whether there are externs at all; the second emits
    # at the offset that implies, exactly as the executable path does.
    #
    # A module can be useful source and still be useless as a LIBRARY, and
    # then no importer of it can link. That is a real property of the module
    # and it has to be said, so the refusal below names WHICH of the ways it
    # happens — see `no_public_api_reason`. The one-sentence version this
    # replaces ("a struct-only module has no free-function API") was false for
    # most of the files it was reported against, and a message that is false
    # about the file is worse than no message: it sends the reader looking for
    # a struct that isn't there.
    traits = _declared_traits(source_paths)
    if not _export_entries(source_paths, module_prefixes) \
            and not reexports and not traits:
        raise FormalBuildError(no_public_api_reason(source_paths))
    if not _export_entries(source_paths, module_prefixes) \
            and (reexports or traits):
        # A proof is a property of CODE, and this library has none. Saying so
        # beats quietly returning a result with no `proof_path` in it: a
        # caller that asked for a checked proof and got a library would
        # otherwise believe it had one. (The only in-tree caller that passes
        # `reexports` is the import path, which asks for neither.)
        #
        # The sentence is built from WHICH of the two reasons applies, because
        # the two are different facts about the module and one sentence cannot
        # be true of both. A pure re-export package has its definitions in
        # named submodules; a TRAIT-ONLY module declares everything itself and
        # has no definition anywhere else to point at, because a trait is not a
        # definition that can be lowered — see `_namespace_library`'s
        # `traits` parameter for why the empty trie is still the right answer.
        if prove:
            if traits:
                raise FormalBuildError(
                    f"{os.path.basename(source_paths[0])} declares only the "
                    f"trait(s) {', '.join(sorted(set(traits))[:6])}, and a "
                    f"trait is a compile-time contract with no code to emit, "
                    f"so this library has no code and there is nothing to "
                    f"prove.")
            raise FormalBuildError(
                f"{os.path.basename(source_paths[0])} is a package whose API "
                f"is entirely re-exported, so it compiles to a library with no "
                f"code and there is nothing to prove. Its definitions are in "
                f"{', '.join(sorted({v[0] for v in reexports.values()})[:4])}"
                f", whose libraries are on this one's link line.")
        return _namespace_library(
            output, install_name, arch, reexports, dylib_syms, dep_install,
            linked,
            source=source_paths[0],
            module=(module_prefixes or {}).get(source_paths[0])
            or _module_prefix(source_paths[0]),
            constants=_namespace_constants(reexports, constants, linked),
            traits=traits)

    # A DYDLIB cannot export a function that returns a frame, and this is the
    # one place that knows it: the convention needs the CALLER to reserve the
    # block the object is copied into, and an importer of this library is a
    # compilation this build does not perform — it binds the symbol and has no
    # way to learn the width of the block it must reserve.  Refusing here is the
    # honest answer rather than emitting a function every importer gets wrong,
    # and it is the executable build's own answer that is absent here: `main`
    # has a stub to refuse it and an exported function has nothing.
    #
    # Read off the per-function table `_frame_receivers` published rather than
    # recomputed, so the question is the one the emitters will ask.
    for fn in ordered:
        if getattr(fn, "_returns_frame_struct", None) is not None:
            raise FormalBuildError(M.returned_frame_library_refusal(fn.name))

    # The library's merged slot table is PUBLISHED before the codegen runs,
    # because a slot access is an absolute address the codegen computes against
    # it, and the image the linker is handed at the end has to be built from the
    # same table. The per-file tables each numbered their slots from zero, so
    # this merge is what makes the library's slots distinct.
    M.publish_global_slots(library_slots)
    has_globals = bool(library_slots)
    codegen = _make_codegen(arch, fmt, test_input, dylib_syms,
                            dylib_exports=dylib_exports)
    try:
        code, info = codegen.compile(
            ordered,
            base_addr=TEXT_BASE + dylib_code_offset(
                install_name, False, dep_install, has_globals),
            emit_startup=False)
        external_syms = info.get("external_syms") or []
        if external_syms:
            # The dependency load commands are known BEFORE compiling, so the
            # no-extern offset already accounts for them; only the extern
            # segment and libSystem are discovered by the first pass.
            codegen = _make_codegen(arch, fmt, test_input, dylib_syms,
                                    dylib_exports=dylib_exports)
            code_file = dylib_code_offset(install_name, True, dep_install,
                                          has_globals)
            code, info = codegen.compile(ordered,
                                         base_addr=TEXT_BASE + code_file,
                                         emit_startup=False)
            external_syms = info.get("external_syms") or []
            stub_addrs = externer_layout(len(code), external_syms, arch=arch,
                                        entryoff=code_file)["stub_addrs"]
            codegen.asm.resolve_extern(stub_addrs)
            code = bytes(codegen.asm.sections["text"])
        else:
            external_syms = []
    except CodegenError as e:
        raise FormalBuildError(str(e))

    # A library may only bind symbols it can account for. Checked by the SAME
    # function the executable path now uses, and for the same reason: every name
    # the image sends through a stub lands in its bind stream, and dyld resolves
    # each one at load time against libSystem or a declared dependency. A name
    # that is neither is not a working library — it is an image that builds
    # cleanly and then cannot be loaded, which is the failure mode this whole
    # import work exists to remove, just moved later. Checking here says it
    # where the library is built, and names the symbols.
    unaccounted = _audit_bound_symbols(external_syms, dylib_syms,
                                        "library", dylib_exports)
    if unaccounted:
        raise FormalBuildError(
            _unaccounted_report(source_paths[0], unaccounted, "library"))

    exports = _formal_exports(source_paths, ordered, info, module_prefixes,
                              _method_exports(source_paths, structs_by_file,
                                              module_prefixes))
    if not exports:
        raise FormalBuildError("formal dylib has no public functions")

    binary = build_macho_dylib(
        code,
        TEXT_BASE + dylib_code_offset(install_name, bool(external_syms),
                                      dep_install, has_globals),
        exports, install_name, arch=arch, external_syms=external_syms,
        deps=dep_install, dep_syms=dep_syms,
        globals_image=globals_image("macho") if has_globals else None)
    with open(output, "wb") as f:
        f.write(binary)
    os.chmod(output, 0o755)
    _ad_hoc_sign(output)
    manifest_path = write_dylib_manifest(
        output, install_name, exports,
        source=source_paths[0],
        module=(module_prefixes or {}).get(source_paths[0])
        or _module_prefix(source_paths[0]),
        constants=constants)
    if linked:
        _record_link_deps(manifest_path, linked)

    result = {
        "manifest_path": manifest_path,
        "path": output,
        "code": code,
        "binary": binary,
        "info": info,
        "exports": exports,
        "backend": f"{arch}/macho-dylib",
    }

    if prove:
        from formal.arm64_proof_gen import generate_dylib_proof, _dylib_spec_lean
        # The spec comes from the export's SOURCE, and the proof checks the
        # machine against it (`bv_decide`), so a wrong spec is a build failure
        # rather than a believed claim.  An export whose body is not a single
        # `return` of pure arithmetic over its parameter gets no spec, and the
        # proof keeps naming that export's contract as an open obligation
        # instead of guessing one.
        specs = {}
        for fn in ordered:
            spec = _dylib_spec_lean(fn)
            if spec is not None:
                specs[fn.name] = spec
        proof = generate_dylib_proof(code, info, exports, specs)
        proof_path = os.path.splitext(output)[0] + "_proof.lean"
        if os.path.exists(proof_path):
            os.chmod(proof_path, 0o644)
        with open(proof_path, "w") as f:
            f.write(proof)
        os.chmod(proof_path, 0o444)
        result["proof_path"] = proof_path
        if check:
            from formal.lean import check_proof_cached
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            ok, detail, cached, n_sorries = check_proof_cached(
                proof_path, repo_root=repo_root)
            result["proof_checked"] = ok
            result["proof_cached"] = cached
            result["proof_sorries"] = n_sorries
            if not ok:
                raise FormalBuildError(f"proof check failed: {detail}")
    return result
