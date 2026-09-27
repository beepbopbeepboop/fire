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
from formal.macho_linker import (EXTERN_ENTRYOFF, NOEXTERN_ENTRYOFF, TEXT_BASE,
                                  build_macho_dylib, dylib_code_offset,
                                  externer_layout)
from mojo.middle.closures import discover_closures
from formal.comptime_runner import make_call_hook


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
    from fire_compiler import py_tokenize, Parser
    stmts = Parser(py_tokenize(source)).with_filename(filename).parse_module()
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


def _extract_functions(stmts: list, synthetic: bool = True) -> list:
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
    if not functions and synthetic:
        functions = [_synthetic_main()]
    main = [f for f in functions if f.name == "main"]
    rest = [f for f in functions if f.name != "main"]
    return main + rest


def _make_codegen(arch: str, fmt: str, test_input: int,
                  dylib_syms: dict = None, comptime_hook=None):
    """The codegen for `arch`, configured for the `fmt` binary it feeds.

    The only format-dependent choice is how an unbound symbol is called:
    Mach-O carries a __TEXT,__stubs trampoline (`call rel32` to it), while
    ELF has no stub section and calls through the .got slot the loader fills
    (`call [rip+disp32]`). Everything else about the two backends is the
    same contract, so it is selected here rather than at each call site."""
    if arch == "arm64":
        return ARM64Codegen(test_input=test_input,
                            dylib_syms=dylib_syms,
                            comptime_hook=comptime_hook)
    if arch == "x86_64":
        from formal.x86_64_codegen import X86_64Codegen
        return X86_64Codegen(test_input=test_input,
                             extern_style="got" if fmt == "elf" else "stub",
                             dylib_syms=dylib_syms,
                             comptime_hook=comptime_hook)
    raise FormalBuildError(
        f"unknown arch {arch!r} (expected one of {', '.join(ARCHES)})")


def _codegen_and_link(arch: str, fmt: str, ordered: list, test_input: int,
                      dylibs: list = None, comptime_hook=None,
                      structs: list = None):
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
    dylib list implies."""
    dylibs = list(dylibs or [])
    dylib_syms = {}
    for d in dylibs:
        for bare, mangled in (d.get("map") or {}).items():
            dylib_syms.setdefault(bare, mangled)
    if fmt == "elf":
        from formal.elf import (DEFAULT_BASE, DEFAULT_LIBC, build_elf,
                                 compute_got_addrs)
        codegen = _make_codegen(arch, fmt, test_input, dylib_syms, comptime_hook)
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
        binary = build_elf(code, entry=info["base_addr"],
                           vaddr=info["base_addr"],
                           external_syms=external_syms, lib_name=DEFAULT_LIBC)
        return code, info, external_syms, binary

    # The extern entry offset depends on the linked dylibs: each adds a load
    # command, and the code starts after the whole list.
    from formal.macho_linker import extern_entry_offset
    base_extern = TEXT_BASE + extern_entry_offset(
        [d["install_name"] for d in dylibs])
    base_noextern = TEXT_BASE + NOEXTERN_ENTRYOFF
    codegen = _make_codegen(arch, fmt, test_input, dylib_syms, comptime_hook)
    try:
        code, info = codegen.compile(ordered, base_addr=base_noextern,
                                     structs=structs)
        external_syms = info.get("external_syms") or []
        if external_syms:
            # Re-emit at the extern entry base (the layout differs, and so do
            # every address the code computed off its own base).
            codegen = _make_codegen(arch, fmt, test_input, dylib_syms, comptime_hook)
            code, info = codegen.compile(ordered, base_addr=base_extern,
                                         structs=structs)
            external_syms = info.get("external_syms") or []
            # The stub addresses must be computed for the SAME entry offset
            # the code was emitted at, which a linked dylib moves.
            stub_addrs = compute_macho_got_addrs(
                len(code), external_syms, vaddr=info["base_addr"], arch=arch,
                entryoff=extern_entry_offset(
                    [d["install_name"] for d in dylibs]))
            codegen.asm.resolve_extern(stub_addrs)
            code = bytes(codegen.asm.sections["text"])
    except CodegenError as e:
        raise FormalBuildError(str(e))
    binary = build_macho(code, external_syms=external_syms, arch=arch,
                         dylibs=[{"install_name": d["install_name"],
                                  "symbols": set((d.get("map") or {}).values())}
                                 for d in dylibs] or None)
    return code, info, external_syms, binary


def _imported_structs(source_path: str, stmts: list, arch: str) -> list:
    """Struct declarations from the modules this file imports, or [].

    A no-op for a target that has no module concept (an ELF image, or a
    non-Mach-O format): there is nothing to import and nothing to bind."""
    if not fmt_wants_macho(arch):
        return []
    from formal.imports import imported_struct_defs
    return imported_struct_defs(source_path, stmts, project_root=source_path)


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

    # Structural acceptance: only FunctionDefs matter for codegen; imports /
    # module-level statements are fine (filtered here + in the codegen).
    # The modules this file imports contribute their struct declarations
    # BEFORE the function pipeline runs, because a method call is rewritten to
    # `<Struct>_<method>` and the rewrite needs to know which struct owns the
    # name. Resolving this after would leave `c.get()` unrecognised in a file
    # that imported the struct, which is the only way such a call occurs.
    imported_structs = _imported_structs(source_path, stmts, arch)
    try:
        functions, structs = _prepare_functions(
            stmts, synthetic=True, extra_structs=imported_structs)
    except CodegenError as e:
        # A clean compile error. The function pipeline runs before codegen
        # proper, so a refusal raised there — a method whose receiver is wider
        # than a word, say — used to reach the user as a raw traceback instead
        # of the one-line diagnostic every other refusal produces.
        raise FormalBuildError(str(e))
    ordered = functions

    # The libraries this program links against, resolved before codegen: their
    # export spellings decide both the callee mangling and (via their load
    # commands) where the entry point lands.
    linked = load_dylib_manifests(link_dylibs)

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
    try:
        check_frame_field_blob_premises(structs)
        check_frame_subscript_escapes(functions)
        check_construction_shapes(functions, {st.name: st for st in structs})
    except CodegenError as e:
        raise FormalBuildError(str(e))
    if import_dylibs:
        have = {d["install_name"] for d in linked}
        linked = linked + [d for d in load_dylib_manifests(import_dylibs)
                           if d["install_name"] not in have]

    # `comptime f(...)` is resolved by RUNNING f through this same backend
    # (formal/comptime_runner.py), so a folded constant and the emitted code
    # can never come from two different implementations.
    comptime_hook = make_call_hook(source)
    code, info, external_syms, binary = _codegen_and_link(
        arch, fmt, ordered, test_input, dylibs=linked,
        comptime_hook=comptime_hook,
        structs=structs)

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


def _formal_module_functions(source_path: str) -> tuple[str, list]:
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
    functions, structs = _prepare_functions(stmts, synthetic=False)
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
    try:
        check_frame_field_blob_premises(structs)
        check_frame_subscript_escapes(functions)
        check_construction_shapes(functions, {st.name: st for st in structs})
    except CodegenError as e:
        raise FormalBuildError(str(e))
    module = re.sub(r"[^A-Za-z0-9_]", "_",
                    os.path.splitext(os.path.basename(source_path))[0])
    return module, functions, source, structs


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


def _member_chain(node) -> str:
    """`a.b.c` for a MemberExpr chain, spelled the way the source spells it.

    `_root_ident` reports a chain's root and depth and nothing else, which is
    the right answer for a lookup and the wrong one for a MESSAGE: the old
    field-of-a-field diagnostic printed `base.member`, so a refusal about
    `self.asm.emit` read as though the source said `self.emit`, and the reader
    went looking for a field of the wrong name. Every refusal that talks about a
    chain now spells the chain."""
    parts = []
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    parts.append(node.name if isinstance(node, F.IdentExpr) else "?")
    parts.reverse()
    return ".".join(parts)


def _subscript_chain(node) -> str:
    """`q[0]`, `REGISTRY[s.name]`, spelled the way the source spells it.

    A separate function from `_member_chain` rather than a branch of it, for
    the reason that function's docstring gives: the diagnostic is read by
    someone looking for the source they wrote, and `q.?` is not it.

    Which is a thing that was got wrong here and is worth recording: the first
    version printed `str(index)`, and a MemberExpr index has no `__str__`, so
    `REGISTRY[s.name] = spec` was reported as

        is stored through "REGISTRY[MemberExpr(obj=IdentExpr(name='s', line=255, ..."

    which is the AST.  A reader sent to a repr has to go and find the source to
    work out what the compiler was looking at, which is the whole cost the
    spelling exists to remove.  `_expr_spelling` is the one spelling function
    and this delegates to it, so a shape neither of them has a short name for
    degrades to the same honest placeholder rather than to a repr."""
    base = node.obj if isinstance(node, F.SubscriptExpr) else node
    idx = node.index if isinstance(node, F.SubscriptExpr) else None
    if isinstance(idx, (F.TupleExpr, F.ListExpr)):
        inner = ", ".join(_expr_spelling(e) for e in (idx.elements or []))
    else:
        inner = _expr_spelling(idx)
    if isinstance(base, F.IdentExpr):
        return f"{base.name}[{inner}]"
    if isinstance(base, F.MemberExpr):
        return f"{_member_chain(base)}[{inner}]"
    return f"[{inner}]"


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


def _check_holder_agreements(functions, holders, hstruct, params_of) -> None:
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
    """
    for fn in functions:
        hs = holders.get(fn.name) or ()
        by_name = hstruct.get(fn.name) or {}
        for node in M.iter_nodes(fn.body):
            if not isinstance(node, F.CallExpr) \
                    or not isinstance(node.func, F.IdentExpr):
                continue
            callee = node.func.name
            params = params_of.get(callee)
            if not params:
                continue
            for position, arg, _kw in _frame_argument_slots(node, params):
                pname = params[position] if position < len(params) else None
                if not pname:
                    continue
                here = isinstance(arg, F.IdentExpr) and arg.name in hs
                there = pname in holders.get(callee, ())
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
                                or not isinstance(site.func, F.IdentExpr) \
                                or site.func.name != callee:
                            continue
                        for i, a, _k in _frame_argument_slots(site, params):
                            if i != position:
                                continue
                            site_holder = isinstance(a, F.IdentExpr) \
                                and a.name in holders.get(site_fn.name, ())
                            spelling = _call_spelling(site, a, position, pname)
                            bucket = (holder_spellings if site_holder
                                      else plain_spellings)
                            if spelling not in bucket:
                                bucket.append(spelling)
                            for st in (hstruct.get(site_fn.name, {})
                                       .get(a.name) or ()) if site_holder \
                                    else ():
                                if st.name not in structs:
                                    structs.append(st.name)
                if not holder_spellings or not plain_spellings:
                    continue
                raise CodegenError(M.frame_holder_disagreement_refusal(
                    callee, position, pname, structs, holder_spellings,
                    plain_spellings))


def _expr_spelling(node) -> str:
    """The source's own spelling of an expression, as far as a name needs one.

    A refusal that quotes `CallExpr` where the source wrote `mid(1)` sends the
    reader to the AST to find the call, which is the opposite of what a
    diagnostic quoting a call site is for.  A shape with no short spelling is
    named by its type, which is at least a true statement and is obviously a
    placeholder to anyone who reads it."""
    if isinstance(node, F.IdentExpr):
        return node.name
    if isinstance(node, F.CallExpr) and isinstance(node.func, F.IdentExpr):
        return f"{node.func.name}({', '.join(_expr_spelling(a) for a in (node.args or []))})"
    if isinstance(node, F.MemberExpr):
        return _member_chain(node)
    for attr in ("value", "name"):
        v = getattr(node, attr, None)
        if isinstance(v, (str, int, float, bool)):
            return str(v)
    return type(node).__name__


def _call_spelling(call, arg, position, pname) -> str:
    """`f(2, 3)` — the call as the source spells it, for the disagreement."""
    parts = [_expr_spelling(a) for a in (call.args or [])]
    for k, v in (call.kwargs or []):
        parts.append(f"{k}={_expr_spelling(v)}")
    return f"{call.func.name}({', '.join(parts)})"


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
    """The `id()` of every MemberExpr used as `X.m(...)`'s callee object.

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

    `id()` of the node, because the walk yields nodes and a set of identities
    is the only way to say "this node, in this position" without a second walk
    that could disagree about which nodes it saw."""
    out = set()
    for node in M.iter_nodes(getattr(fn, "body", None)):
        if isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr):
            out.add(id(node.func))
    return out


def _frame_receivers(functions: list, structs_by_name: dict) -> None:
    """Annotate every function with its frame-pointer receivers and field slots.

    Writes `fn._frame_holders` (the names holding a frame address) and
    `fn._frame_slots` (`{"<holder>.<field>": slot}`, the table the codegen
    intercepts a local load/store with) onto each function, and RAISES for any
    construct a frame address may not take part in. Called once, at the end of
    `_prepare_functions`, so it sees the FINAL function list — after closures
    are flattened and lambdas lifted, because a lifted lambda is a function
    with its own locals and its own receivers.

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
    param0 = {}
    params_of = {}
    for fn in functions:
        names = []
        for p in (list(getattr(fn, "params", None) or [])):
            names.append(p[0] if isinstance(p, (tuple, list)) and p
                         and isinstance(p[0], str) else None)
        params_of[fn.name] = names
        if names and names[0]:
            param0[fn.name] = names[0]
    # `holders[fn]` is the set of names in `fn` holding a frame address, and
    # `hstruct[fn][name]` is the SET of structs it might be — carried through
    # the fixpoint rather than re-derived afterwards, because a holder that
    # arrived as a callee's parameter has no binding left to re-derive it
    # from. A candidate set that is EMPTY means the name was bound from a
    # constructor this path does not frame, so it holds a plain word and its
    # `.<field>` accesses are not frame accesses at all.
    holders = {fn.name: set() for fn in functions}
    hstruct = {fn.name: {} for fn in functions}
    # The declared return annotations, read ONCE for the whole unit and handed
    # to the construction decision below.  They are the evidence that tells a
    # construction argument that is an ordinary value from one that is a
    # container returned by a callee, and the two backends read the same table
    # (`formal/model.py`'s `function_return_types`) so the three callers of
    # `struct_construction_plan` cannot answer differently.
    rets = M.function_return_types(functions)
    for fn in functions:
        owner = owners.get(fn.name)
        if owner is not None and owner.name in framed:
            for recv in M.struct_receivers(owner):
                holders[fn.name].add(recv)
                hstruct[fn.name][recv] = [owner]
        for name, sts in _constructor_bindings(fn, framed).items():
            holders[fn.name].add(name)
            hstruct[fn.name].setdefault(name, []).extend(sts)
    changed = True
    while changed:
        changed = False
        for fn in functions:
            hs = holders[fn.name]
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
                    hstruct[fn.name][target] = list(hstruct[fn.name][value.name])
                    changed = True
                if not isinstance(node, F.CallExpr) \
                        or not isinstance(node.func, F.IdentExpr):
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
                # the opaque case `_check_frame_escapes` says so about.
                plist = params_of.get(node.func.name)
                if not plist:
                    continue
                for pos, pname, _kw in _frame_argument_slots(node, plist):
                    if pos >= len(plist):
                        continue
                    r = _root_ident(pname)
                    if not (r and r[0] in hs and r[1] == 0):
                        continue
                    callee = plist[pos]
                    if not callee or callee in holders.get(node.func.name, ()):
                        continue
                    holders[node.func.name].add(callee)
                    hstruct[node.func.name][callee] = \
                        list(hstruct[fn.name][r[0]])
                    changed = True
    for fn in functions:
        hs = holders[fn.name]
        if not hs:
            continue
        by_name = hstruct[fn.name]
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
                            # No single declared type, so the slot's contents
                            # are unknown — which is what the old message said,
                            # and now it also says WHICH candidate disagreed.
                            raise CodegenError(
                                f"{chain}() hands the word in the slot "
                                f"{base}.{outer} to "
                                f"{ost.name}.{node.member}(), whose receiver is "
                                f"the ADDRESS of a frame of 8-byte slots — so "
                                f"the slot would have to hold a frame address. "
                                f"The declared type of {outer!r} is the only "
                                f"thing here that could say so, and it does "
                                f"not: {M.field_type_disagreement(cands, outer, _type_rows(cands, outer))}"
                                f". Until every binding of the name agrees on "
                                f"one type there is no frame to place here"
                            )
                        if nested is _REASSIGNED:
                            raise CodegenError(
                                f"{base}.{outer} is declared as a "
                                f"{M.annotation_base_name(_field_annotation(cands, outer))}"
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
                    raise CodegenError(
                        f"{chain} reads a field of a field through the receiver "
                        f"{base}: a frame slot holds one 64-bit word, and the word "
                        f"in the slot {base}.{outer_field} is a value, not a "
                        f"struct, so there is no second layout to read through. "
                        f"Two things would make it representable and neither is a "
                        f"change to this function: an ANNOTATION on "
                        f"{outer_field!r} that EVERY binding of the name agrees "
                        f"on and that names a struct declared here (a struct "
                        f"declared here would then be a nested frame, placed in "
                        f"the outer object's own block), or a builtin method on "
                        f"the value — which is {node.member!r}() as a call, not "
                        f"a field read. The declared type of {outer_field!r} does "
                        f"not settle it: "
                        f"{M.field_type_disagreement(cands, outer_field, _type_rows(cands, outer_field))}"
                    )
                if nested is _REASSIGNED:
                    raise CodegenError(
                        f"{chain} reads through {base}.{outer_field}, which is "
                        f"declared as a "
                        f"{M.annotation_base_name(_field_annotation(cands, outer_field))}"
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
                    raise CodegenError(
                        f"{base}.{outer_field} cannot be placed, so the nested "
                        f"read {chain} has no first load: "
                        + ("the candidate layouts disagree — "
                           + M.field_type_disagreement(
                               cands, outer_field, _type_rows(cands, outer_field))
                           if odis else
                           f"no candidate declares it as a field of a frame")
                    )
                inner = M.struct_frame_slot(nested, node.member)
                if inner is None:
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
            slot, (disagree, rows) = M.struct_frame_slot_candidates(
                cands, node.member)
            if disagree:
                raise CodegenError(
                    f"{base}.{node.member} cannot be placed: this name holds a "
                    f"frame address in more than one shape, and the shapes do "
                    f"not agree on where {node.member!r} lives — "
                    + "; ".join(
                        f"{sn} puts it at slot {sl}" if sl is not None
                        else f"{sn} has no such field" for sn, sl in rows)
                    + ". Which one applies depends on the path taken, and this "
                      "analysis has none, so a slot index computed from either "
                      "would read the wrong word on the other: the program "
                      "would build, run, and return a number the source never "
                      "wrote"
                )
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
                             set(_constructor_bindings(fn, framed)), rets,
                             holders, hstruct, params_of)
        _check_method_receiver_types(fn, hs, by_name, owners, structs_by_name)
        fn._frame_holders = hs
        fn._frame_nested_slots = nested_slots
        fn._frame_slots = slots
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
    # AFTER the loop, over every function including the ones that hold no frame.
    # A parameter's being a frame holder is a fact about the whole image, and
    # the call site that disagrees with it can be in a function the loop above
    # skipped — see `_check_holder_agreements` for the program that measures it.
    _check_holder_agreements(functions, holders, hstruct, params_of)


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


def _field_annotation(cands, name):
    """The declared type of `name` as a candidate spells it, for a message.

    The first candidate's answer, and only ever used to NAME a type in a
    diagnostic — the decision itself is `frame_field_type_candidates`, which
    requires unanimity.  A reader is better served by the spelling one
    candidate used than by no type at all, and the message says "is declared as"
    rather than asserting it is the type.
    """
    for st in cands:
        _base, ann = M.struct_field_declared_type(st, name)
        if ann is not None:
            return ann
    return None


def _type_rows(cands, name):
    """The declared-type evidence for a field, for a refusal to quote.

    A function rather than a call at each use site because the refusal has to
    quote the SAME table the decision was made from; recomputing it at the raise
    would be a second walk of the same candidates that could disagree with the
    first, and a refusal that misreports why it fired is worse than one that
    does not report at all."""
    return M.field_type_rows(cands, name)


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


def _defer_subscript_escape(fn, value, holders, by_name, spelled) -> None:
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
    if not isinstance(value, F.IdentExpr) or value.name not in holders:
        return
    cands = by_name.get(value.name) or []
    who = ", ".join(st.name for st in cands) if cands else value.name
    fn._frame_subscript_escapes = list(
        getattr(fn, "_frame_subscript_escapes", ())) + [(
            who, value.name, spelled, fn.name)]


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


def _constructor_bindings(fn, framed) -> dict:
    """`{name: [struct, …]}` for locals bound from a framed struct's constructor.

    A LIST per name, and that is the fix for a miscompile rather than a
    refinement: `x = A()` on one path and `x = B()` on another is one name with
    two frame layouts, and a dict that kept the last binding computed a slot
    index from that one alone — so on the `A` path `x.v` read `A`'s idea of
    where `v` is, which is generally not where `A` puts it. Every candidate is
    kept and `model.struct_frame_slot_candidates` decides whether they agree.

    The empty list is meaningful and not an oversight: a name bound from a
    constructor this path does NOT frame holds a plain word, and remembering
    that is what stops a later `x.f` from being read as a frame slot."""
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


def _check_frame_escapes(fn, holders, by_name, param0, owners=None,
                         structs_by_name=None, created_here=frozenset(),
                         rets=None, all_holders=None, all_hstruct=None,
                         params_of=None) -> None:
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

    `all_holders`/`all_hstruct`/`params_of` are the whole image's tables, and
    they are what the CALL half is decided from.  A parameter is a frame holder
    or it is not, and that is a property of every call site at once — see
    `model.frame_holder_disagreement_refusal` for the measured program that
    says what happens when only one of them agrees."""
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

    def _names(node):
        return [st.name for st in (by_name.get(node.name) or [])] \
            if isinstance(node, F.IdentExpr) else []

    for node in M.iter_nodes(fn.body):
        if isinstance(node, F.ReturnStmt) and node.value is not None:
            # Whether the returning function CREATED the frame is not a thing
            # this walk knows: a holder may have arrived as one of its
            # parameters, in which case the creator is up the call chain.
            # `owners` says which case this is, and the message says so,
            # because "returned from the function that created it" is false for
            # the second and sends the reader to the wrong function looking for
            # it.
            owner = (owners or {}).get(fn.name)
            if isinstance(node.value, F.IdentExpr) \
                    and node.value.name in holders:
                raise CodegenError(M.frame_return_refusal(
                    owner.name if owner is not None else None,
                    node.value.name not in created_here,
                    _names(node.value)))
            _refuse_holder_use(fn, node.value, holders, by_name,
                               "is returned from the function that created it")
        elif isinstance(node, (F.ListExpr, F.TupleExpr, F.DictExpr)):
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
                _subscript_chain(node.target))
        elif isinstance(node, F.CallExpr):
            callee = node.func.name if isinstance(node.func, F.IdentExpr) else None
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
            #      rewriting did not lift)          -> case 3, opaque;
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
                    node, params_of.get(callee) if callee in all_holders
                    else ()):
                if callee is None:
                    # 0. A METHOD call on a value receiver: the one case where
                    #    the declaration genuinely is not in hand, so it is the
                    #    narrow case rather than the catch-all.
                    _refuse_holder_use(
                        fn, a, holders, by_name, "",
                        M.frame_opaque_position_refusal(
                            where_the=method or "the call", callee=None,
                            position=i, total=len(node.args or []),
                            struct_names=_names(a), method=method,
                            why="a method call on a value receiver is "
                                "dispatched by NAME, so `recv.m(x)` carries no "
                                "type and the parameter list this argument "
                                "lands in belongs to a declaration this walk "
                                "has not read"))
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
                    # the imported module's analysis made it a frame holder is
                    # a fact about THAT module's compilation, which this pass
                    # has not read and cannot: its body is in the dylib.  So
                    # this is the opaque case, and it is refused as opaque
                    # rather than as a position.
                    if i == 0:
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
                if callee not in known and callee not in all_holders:
                    # 2. Not in this image, whatever position.  Saying so is
                    #    true at every position; the old loop only said it at
                    #    position 0 and let the position sentence cover the
                    #    rest.
                    reason = M.frame_receiver_escape_refusal(callee, _names(a))
                    if reason is not None:
                        _refuse_holder_use(fn, a, holders, by_name, "", reason)
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


def _one_word_field_map(fn, structs_by_name: dict) -> dict:
    """{local name: its field name} for locals holding a one-word struct.

    Found from the binding, not inferred: a local initialised from a one-word
    struct's constructor holds that struct's only field, and nothing else on
    this path can produce such a value."""
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
        if st is not None and M.struct_fits_one_word(st) \
                and M.struct_field_count(st) == 1:
            mapping[target] = _sole_field_name(st)
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


def _constant_read_sites(body, structs_by_name: dict) -> dict:
    """{access path: struct} for every read of a class-level constant.

    The two spellings that are provably a read of the CLASS's own value:
    `S.NAME`, where `S` is the struct's name, and `x.NAME` where `x` is a local
    initialised from `S()`. A read through any other object is deliberately not
    in here: without types, `o.NAME` might be an instance of `S` (a constant) or
    of some other struct with a real field of the same name (a field), and
    guessing is the error this whole rule is arranged to avoid.

    A receiver spelling (`self.NAME`) is not here either, and cannot be: the
    model counts any name a method reaches that way as a FIELD, precisely so
    this decision never has to be made."""
    aliases = {}
    for node in M.iter_nodes(body):
        target = value = None
        if isinstance(node, F.VarDecl):
            target, value = node.name, node.value
        elif isinstance(node, F.AssignStmt) and isinstance(node.target,
                                                           F.IdentExpr):
            target, value = node.target.name, node.value
        if target and isinstance(value, F.CallExpr) \
                and isinstance(value.func, F.IdentExpr) \
                and value.func.name in structs_by_name:
            aliases[target] = value.func.name
    out = {}
    for st in structs_by_name.values():
        for name, _default in M.struct_class_constants(st):
            out[f"{st.name}.{name}"] = st
    for local, struct_name in aliases.items():
        for key in [k for k in out if k.startswith(struct_name + ".")]:
            out[f"{local}.{key.split('.', 1)[1]}"] = out[key]
    return out


def _constant_literal(struct_def, name: str):
    """The literal node a read of `struct_def`'s constant `name` yields, or None.

    None when the constant's value is not a literal this path can materialize
    exactly — a dict, a list, a call, a name. The caller refuses there; see
    `_rewrite_class_constants` for why substituting a zero is not an option."""
    for const_name, default in M.struct_class_constants(struct_def):
        if const_name != name:
            continue
        kind, payload = M.class_constant_word(const_name, default)
        if kind == M.DEFAULT_INT:
            return F.IntLiteral(value=int(payload))
        if kind == M.DEFAULT_STRING:
            return F.StringLiteral(value=payload)
        return None
    return None


def _rewrite_class_constants(node, structs_by_name: dict):
    """`S.NAME` -> the literal `NAME` holds, in place, over a statement tree.

    A class-level constant is not part of any value: it is one value for every
    instance, so there is nothing for a receiver word to hold and nothing for
    the member-access lowering to read. The two ways this could go wrong are
    both wrong answers rather than refusals, which is why the value is
    materialized HERE, at the read, instead of being left to the field path:

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
    plausible-looking wrong number rather than a crash."""
    if not structs_by_name:
        return node
    return _apply_constant_sites(node,
                                 _constant_read_sites(node, structs_by_name))


def _apply_constant_sites(node, sites: dict):
    """The substitution itself, over a statement tree, in place.

    Split from `_rewrite_class_constants` so the sites can be computed once per
    function: they are a census of the whole body, and recomputing them at every
    node would be quadratic in the size of the function."""

    if isinstance(node, list):
        for i, x in enumerate(node):
            node[i] = _apply_constant_sites(x, sites)
        return node
    if isinstance(node, F.MemberExpr) and isinstance(node.obj, F.IdentExpr):
        st = sites.get(f"{node.obj.name}.{node.member}")
        if st is not None:
            literal = _constant_literal(st, node.member)
            if literal is None:
                raise CodegenError(
                    f"{st.name}.{node.member} is a class-level constant, and a "
                    f"formal value is one 64-bit word with nowhere to keep a "
                    f"non-literal one: this path has no module-global storage, "
                    f"so reading {st.name}.{node.member} can only be answered by "
                    f"the value it is written with, and that value is not a "
                    f"literal. Write the value at the use site (a literal, or "
                    f"an assignment the compiler can see), which is the same "
                    f"program with a representation")
            return literal
    for name in getattr(node, "__dataclass_fields__", {}):
        setattr(node, name, _apply_constant_sites(getattr(node, name), sites))
    return node


def _prepare_functions(stmts: list, synthetic: bool = True,
                       extra_structs: list = None) -> tuple:
    """Turn a parsed module into the function list the codegen compiles.

    ONE pipeline for both entry points. It was two, and they had drifted:
    the executable path skipped method lifting and call rewriting entirely,
    so `c.get()` built an image that bound a symbol named `c.get` and died in
    dyld, while the dylib path handled it. Anything that changes what gets
    compiled has to happen here or the two front ends disagree about the same
    source file.

    Returns (functions, structs) — the structs are passed to the codegen so a
    `S(...)` constructor and a `self.<field>` access can be recognised."""
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
    functions = _extract_functions(stmts, synthetic=synthetic)
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
    for fn in functions:
        _rewrite_method_calls(fn.body, owners, wide)
        # A method's `self` IS the field; a local initialised from a one-word
        # constructor holds that struct's only field directly.
        mapping = _one_word_field_map(fn, structs_by_name)
        st = method_owners.get(fn.name)
        if st is not None and M.struct_fits_one_word(st) \
                and M.struct_field_count(st) == 1:
            mapping["self"] = _sole_field_name(st)
        _rewrite_self_fields(fn.body, mapping)
        # A class-level CONSTANT is not part of any value, so it is not
        # lowered as a field: it is materialized where it is read. Without
        # this a struct of nothing but constants — which the width rule now
        # correctly calls one word, or zero — reads its own table as the zero
        # an unwritten slot gives, and a program that builds and runs returns
        # a number nobody wrote.
        _rewrite_class_constants(fn.body, structs_by_name)
    ctx = FormalClosureCtx()
    discover_closures(ctx, stmts)
    functions = _flatten_closures(functions, ctx._all_closures)
    functions = _lift_lambdas(functions)
    # LAST, on the FINAL function list: which local names hold a frame
    # address is a property of the code that survives every rewrite above, and
    # a lifted lambda or a flattened closure is a function with its own locals
    # and its own receivers.
    _frame_receivers(functions, structs_by_name)
    return functions, structs


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


def _rewrite_method_calls(node, owners: dict, wide: dict = None) -> None:
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
    given a real slot at all."""
    if isinstance(node, list):
        for x in node:
            _rewrite_method_calls(x, owners, wide)
        return
    if (isinstance(node, F.CallExpr) and isinstance(node.func, F.MemberExpr)
            and isinstance(node.func.obj, F.IdentExpr)):
        owner = owners.get(node.func.member)
        if owner is not None:
            if (wide or {}).get(owner) is not None:
                st = wide[owner]
                raise CodegenError(
                    f"{owner}.{node.func.member}() cannot be lowered: its "
                    f"receiver has {M.struct_field_summary(st)}, and a formal "
                    f"value is one 64-bit word, so `self.<field>` has no "
                    f"representation on this path. The receiver would have to "
                    f"be a pointer to an out-of-line frame of fields, which is "
                    f"a change to the value model the two backends AND the Lean "
                    f"proof share, not to this one function. Concretely, "
                    f"{M.struct_width_cost(st)}")
            receiver = node.func.obj
            node.func = F.IdentExpr(name=M.method_function_name(
                owner, node.func.member))
            node.args = [receiver] + list(node.args)
            return
    for name in getattr(node, "__dataclass_fields__", {}):
        _rewrite_method_calls(getattr(node, name), owners, wide)


def dylib_manifest_path(dylib_path: str) -> str:
    """Where a dylib's export manifest lives: `<dylib>.manifest.json`."""
    return os.path.abspath(dylib_path) + ".manifest.json"


def write_dylib_manifest(dylib_path: str, install_name: str,
                         exports: list) -> str:
    """Record what a formal dylib exports, next to the dylib.

    An executable that links this library has to rewrite each call site's
    callee to the library's exported spelling (`_<module>__<fn>`), and it
    cannot know that mapping by looking at the source it is compiling — the
    callee is just a bare name. The build that *made* the library is the only
    place the mapping exists, so it leaves it behind. JSON because the
    executable build has to read it without importing this module's
    compile-time dependencies."""
    import json
    path = dylib_manifest_path(dylib_path)
    payload = {
        "dylib": os.path.abspath(dylib_path),
        "install_name": install_name,
        # What the executable records in its LC_LOAD_DYLIB. The library's own
        # id is `@rpath/...`, which a dependent can only resolve with an
        # LC_RPATH of its own, so a dependent links the real location.
        "load_path": os.path.abspath(dylib_path),
        # The reflection payload, in the shape doc/ABI.md's table carries: the
        # boundary symbol, its signature, and the module that owns it, so a
        # client can bind a call without ever reading the module's source.
        "exports": [{"module": e["module"], "name": e["name"],
                     "symbol": e["symbol"], "arity": e.get("arity"),
                     "signature": e.get("signature", ""),
                     "kind": e.get("kind")}
                    for e in exports],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")
    return path


def load_dylib_manifests(dylib_paths: list) -> list:
    """Read the manifests of the libraries an executable links against.

    Each entry is `{"install_name", "map": {bare callee -> exported symbol},
    "exports"}`. A library whose manifest is missing is an error rather than a
    silently ignored dependency: the executable would emit calls to symbols
    nothing defines and produce an image that dies in dyld at launch — which
    is exactly the failure this mechanism exists to prevent."""
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
                f"It is written next to the dylib by `mojo dylib --formal`.")
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
        # contribute. Every other library still has to offer something, so
        # the check above is unchanged for them.
        # Two libraries may export the same callee name; first one listed
        # wins, matching the dylib ordinal order the image will record.
        amap = {}
        for e in exports:
            amap.setdefault(e["name"], e["symbol"])
        out.append({
            "install_name": payload.get("load_path") or payload["dylib"],
            "map": amap,
            "exports": exports,
        })
    return out


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


def _is_libsystem(sym: str) -> bool:
    """True for a symbol libSystem itself provides.

    The externs a library legitimately sends outward are the C library's own
    (`printf`, `malloc`, …), and those are declared by the libSystem load
    command the image already carries. Everything else has to come from a
    dependency's export table."""
    import ctypes.util
    known = {"printf", "puts", "putchar", "malloc", "calloc", "realloc",
             "free", "memcpy", "memset", "strlen", "strcmp", "strncmp",
             "abort", "exit", "atoi", "qsort", "fmod", "pow", "sqrt"}
    return sym.lstrip("_") in known


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


def _declared_api_shape(text: str) -> dict:
    """What this source DECLARES, ignoring doc/ABI.md's rules — the input to
    `no_public_api_reason`.

    Eight buckets and the names behind them, because the question "why does this
    module export nothing" has several different true answers and picking the
    wrong one is what made the old single-sentence refusal useless:

      funcs / generic_funcs / private_funcs   top-level FunctionDefs
      structs / generic_structs / private_structs   top-level StructDefs

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
             "private_generic_structs": []}
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
    private = [n for _f, s in shapes
               for k in ("private_funcs", "private_generic_funcs",
                         "private_structs", "private_generic_structs")
               for n in s[k]]
    if not concrete_funcs and not concrete_structs and not gen_funcs \
            and not gen_structs:
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
                "signature": signature,
                "kind": "method",
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
            "signature": entry.get("signature", ""),
            "kind": entry.get("kind"),
        })
    return out


def _record_link_deps(manifest_path: str, linked: list) -> None:
    """Note the libraries this dylib links, so a program can close the set."""
    import json
    try:
        with open(manifest_path) as f:
            payload = json.load(f)
    except OSError:
        return
    payload["links"] = [{"install_name": d["install_name"],
                         "path": d.get("path")} for d in linked]
    with open(manifest_path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")


def _namespace_library(output: str, install_name: str, arch: str,
                       reexports: dict, dylib_syms: dict, dep_install: list,
                       linked: list) -> dict:
    """A dylib for a module whose whole API is RE-EXPORTED — a package
    `__init__.mojo`.

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
    """
    functions = {n: v for n, v in reexports.items() if v[1] != "type"}
    missing = sorted(n for n in functions if n not in dylib_syms)
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
    manifest_path = write_dylib_manifest(output, install_name, [])
    _record_namespace(manifest_path, reexports, dylib_syms)
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
        "backend": f"{arch}/macho-dylib-namespace",
    }


def _record_namespace(manifest_path: str, reexports: dict,
                      dylib_syms: dict) -> None:
    """Mark a manifest as a NAMESPACE library and record what it forwards.

    The `kind` field is what makes an empty `exports` list legal to read back
    (`load_dylib_manifests`): it is the difference between "this library
    defines nothing, and that is its purpose" and "this library's manifest is
    empty, which means the build went wrong". Each re-export records the
    SYMBOL it resolves to, taken verbatim from the defining module's own
    manifest, so a reader can check the forwarding without re-deriving it.
    """
    import json
    try:
        with open(manifest_path) as f:
            payload = json.load(f)
    except OSError:
        return
    payload["kind"] = "namespace"
    payload["reexports"] = {
        n: {"module": v[0], "kind": v[1], "symbol": dylib_syms.get(n)}
        for n, v in sorted(reexports.items())}
    with open(manifest_path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
        f.write("\n")


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
    if not fmt_wants_macho(arch) and fmt != "macho":
        raise FormalBuildError(
            f"a formal dylib is a Mach-O container; {arch!r} defaults to "
            f"{default_format(arch)!r}, which has no dylib form")
    reexports = dict(reexports or {})

    # The libraries THIS library links. Their export spellings decide how a
    # cross-module call is named — a call to a sibling's `base` has to become a
    # reference to `leaf_base_<hash>`, or the library builds and then fails to
    # load with "Symbol not found" for a function its sibling defines.
    linked = load_dylib_manifests(link_dylibs)
    dylib_syms = {}
    for d in linked:
        for bare, mangled in (d.get("map") or {}).items():
            dylib_syms.setdefault(bare, mangled)
    dep_install = [d["install_name"] for d in linked]
    dep_syms = {d["install_name"]: list((d.get("map") or {}).values())
                for d in linked}
    ordered = []
    seen: dict = {}
    structs_by_file: dict = {}
    for source_path in source_paths:
        module, functions, module_source, file_structs = \
            _formal_module_functions(source_path)
        structs_by_file[source_path] = file_structs
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
    if not _export_entries(source_paths, module_prefixes) \
            and not reexports:
        raise FormalBuildError(no_public_api_reason(source_paths))
    if not _export_entries(source_paths, module_prefixes) and reexports:
        # A proof is a property of CODE, and this library has none. Saying so
        # beats quietly returning a result with no `proof_path` in it: a
        # caller that asked for a checked proof and got a library would
        # otherwise believe it had one. (The only in-tree caller that passes
        # `reexports` is the import path, which asks for neither.)
        if prove:
            raise FormalBuildError(
                f"{os.path.basename(source_paths[0])} is a package whose API "
                f"is entirely re-exported, so it compiles to a library with no "
                f"code and there is nothing to prove. Its definitions are in "
                f"{', '.join(sorted({v[0] for v in reexports.values()})[:4])}"
                f", whose libraries are on this one's link line.")
        return _namespace_library(output, install_name, arch, reexports,
                                  dylib_syms, dep_install, linked)

    codegen = _make_codegen(arch, fmt, test_input, dylib_syms)
    try:
        code, info = codegen.compile(
            ordered,
            base_addr=TEXT_BASE + dylib_code_offset(install_name, False,
                                                    dep_install),
            emit_startup=False)
        external_syms = info.get("external_syms") or []
        if external_syms:
            # The dependency load commands are known BEFORE compiling, so the
            # no-extern offset already accounts for them; only the extern
            # segment and libSystem are discovered by the first pass.
            codegen = _make_codegen(arch, fmt, test_input, dylib_syms)
            code_file = dylib_code_offset(install_name, True, dep_install)
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

    # A library may only bind symbols it can account for. Every name the
    # image sends through a stub lands in its bind stream, and dyld resolves
    # each one at load time against libSystem or a declared dependency. A name
    # that is neither is not a working library — it is an image that builds
    # cleanly and then cannot be loaded, which is the failure mode this whole
    # import work exists to remove, just moved later. Checking here says it
    # where the library is built, and names the symbols.
    #
    # These are the formal model's unsupported constructs arriving late: a
    # struct used as a type (`CycleIterator`), a method call on a value
    # (`element.copy`), and compiler intrinsics (`rebind_var`). None is a
    # missing export to be added; each needs lowering this backend does not do.
    # Two spellings meet here: a manifest records the C identifier (what a
    # bind stream carries — dyld prepends the underscore) while a name the
    # codegen could not resolve arrives in the Mach-O spelling, with one.
    # Comparing them raw would report every dependency symbol as unprovided.
    provided = {n.lstrip("_") for n in dylib_syms}
    provided |= {n.lstrip("_") for n in dylib_syms.values()}
    unaccounted = [sym for sym in sorted(set(external_syms or []))
                   if sym.lstrip("_") not in provided
                   and not _is_libsystem(sym)]
    if unaccounted:
        raise FormalBuildError(
            f"{os.path.basename(source_paths[0])}: the library would bind "
            f"{len(unaccounted)} symbol(s) that nothing provides, so it could "
            f"not be loaded: {', '.join(unaccounted[:8])}"
            f"{' …' if len(unaccounted) > 8 else ''}. These are constructs "
            f"this backend does not lower (a struct type, a method call on a "
            f"value, a compiler intrinsic), not exports that are missing.")

    exports = _formal_exports(source_paths, ordered, info, module_prefixes,
                              _method_exports(source_paths, structs_by_file,
                                              module_prefixes))
    if not exports:
        raise FormalBuildError("formal dylib has no public functions")

    binary = build_macho_dylib(
        code,
        TEXT_BASE + dylib_code_offset(install_name, bool(external_syms),
                                      dep_install),
        exports, install_name, arch=arch, external_syms=external_syms,
        deps=dep_install, dep_syms=dep_syms)
    with open(output, "wb") as f:
        f.write(binary)
    os.chmod(output, 0o755)
    _ad_hoc_sign(output)
    manifest_path = write_dylib_manifest(output, install_name, exports)
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
        from formal.arm64_proof_gen import generate_dylib_proof
        proof = generate_dylib_proof(code, info, exports)
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
