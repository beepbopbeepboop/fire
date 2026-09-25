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

import os
import re
import subprocess
import sys
from types import SimpleNamespace

import fire_compiler as F
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
                      dylibs: list = None, comptime_hook=None):
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
            code, info = codegen.compile(ordered, base_addr=DEFAULT_BASE)
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
        code, info = codegen.compile(ordered, base_addr=base_noextern)
        external_syms = info.get("external_syms") or []
        if external_syms:
            # Re-emit at the extern entry base (the layout differs, and so do
            # every address the code computed off its own base).
            codegen = _make_codegen(arch, fmt, test_input, dylib_syms, comptime_hook)
            code, info = codegen.compile(ordered, base_addr=base_extern)
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


def _resolve_imports(source_path: str, stmts: list, arch: str) -> list:
    """Compile every module this file imports, and return their dylibs.

    Returns [] when the file imports nothing. A file that imports something
    unresolvable is an ERROR, not a shrug: the alternative is the failure this
    replaces — an image that builds and then dies in dyld because a call's
    symbol does not exist.
    """
    from formal.imports import (build_module_dylib, dylib_chain,
                                imported_modules, resolve_module_path)
    mods = imported_modules(stmts)
    if not mods:
        return []
    if fmt_wants_macho(arch):
        out_dir = os.path.join(cas_dir(), "formal-imports")
        chain = []
        for mod in mods:
            path = resolve_module_path(mod, relative_to=source_path)
            if path is None:
                # One wording for one condition: formal/imports.py raises the
                # same error for an unresolvable import inside a DEPENDENCY,
                # and two messages for one cause is how a real failure ends up
                # filed under the wrong heading.
                from formal.imports import _is_host_module
                kind = ("a host module (CPython standard library), which has "
                        "no Mojo source for this backend to compile"
                        if _is_host_module(mod)
                        else "not a stdlib or sibling module, and no such file "
                             "exists")
                raise ImportBuildError(
                    f"{os.path.basename(source_path)} imports {mod!r}, which "
                    f"is {kind}")
            dylib = build_module_dylib(mod, path, out_dir, arch,
                                       project_root=source_path)
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
    functions = _extract_functions(stmts)

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
    if import_dylibs:
        have = {d["install_name"] for d in linked}
        linked = linked + [d for d in load_dylib_manifests(import_dylibs)
                           if d["install_name"] not in have]

    # Shared closure discovery (same scan GIMPLE uses), then flatten nested
    # defs into top-level lifted functions with by-value capture params.
    ctx = FormalClosureCtx()
    discover_closures(ctx, stmts)
    functions = _flatten_closures(functions, ctx._all_closures)
    # Lift LambdaExprs into top-level FunctionDefs so assigned/IIFE lambdas
    # lower as call targets (residual bare lambdas get `_lifted_name`).
    functions = _lift_lambdas(functions)
    ordered = functions

    # `comptime f(...)` is resolved by RUNNING f through this same backend
    # (formal/comptime_runner.py), so a folded constant and the emitted code
    # can never come from two different implementations.
    comptime_hook = make_call_hook(source)
    code, info, external_syms, binary = _codegen_and_link(
        arch, fmt, ordered, test_input, dylibs=linked,
        comptime_hook=comptime_hook)

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
            ok, detail, cached = check_proof_cached(proof_path, repo_root=repo_root)
            result["proof_checked"] = ok
            result["proof_cached"] = cached
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
    functions = _extract_functions(stmts, synthetic=False)
    ctx = FormalClosureCtx()
    discover_closures(ctx, stmts)
    functions = _flatten_closures(functions, ctx._all_closures)
    functions = _lift_lambdas(functions)
    module = re.sub(r"[^A-Za-z0-9_]", "_",
                    os.path.splitext(os.path.basename(source_path))[0])
    return module, functions, source


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
        if not exports:
            raise FormalBuildError(
                f"{dylib}'s manifest lists no exports")
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


def _formal_exports(source_paths: list, ordered: list,
                    info: dict, prefixes: dict = None) -> list:
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
        if fn.name not in exported or fn.name in emitted:
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


def compile_formal_dylib(source_paths: list, output: str = None,
                         test_input: int = 10, prove: bool = True,
                         check: bool = True, module_prefixes: dict = None,
                         link_dylibs: list = None) -> dict:
    if not source_paths:
        raise FormalBuildError("at least one source file is required")

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
    for source_path in source_paths:
        module, functions, module_source = _formal_module_functions(source_path)
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
    # Refuse before emitting, and for the true reason. A module can compile no
    # code and still be useless as a library: binary_heap and a third of std/
    # are struct-only, and doc/ABI.md's export rules give them no public
    # symbol, so no importer could ever bind them. Saying so is the difference
    # between "this backend cannot do structs yet" and a mystery.
    if not _export_entries(source_paths, module_prefixes):
        names = [os.path.basename(p) for p in source_paths]
        raise FormalBuildError(
            f"formal dylib has no public functions: {', '.join(names)} "
            f"exports nothing under doc/ABI.md's rules (a struct-only module "
            f"has no free-function API, and this backend compiles no struct "
            f"methods)")

    codegen = ARM64Codegen(test_input=test_input, dylib_syms=dylib_syms)
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
            codegen = ARM64Codegen(test_input=test_input, dylib_syms=dylib_syms)
            code_file = dylib_code_offset(install_name, True, dep_install)
            code, info = codegen.compile(ordered,
                                         base_addr=TEXT_BASE + code_file,
                                         emit_startup=False)
            external_syms = info.get("external_syms") or []
            stub_addrs = externer_layout(len(code), external_syms,
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

    exports = _formal_exports(source_paths, ordered, info, module_prefixes)
    if not exports:
        raise FormalBuildError("formal dylib has no public functions")

    binary = build_macho_dylib(
        code,
        TEXT_BASE + dylib_code_offset(install_name, bool(external_syms),
                                      dep_install),
        exports, install_name, external_syms=external_syms,
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
        "backend": "arm64/macho-dylib",
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
            ok, detail, cached = check_proof_cached(proof_path, repo_root=repo_root)
            result["proof_checked"] = ok
            result["proof_cached"] = cached
            if not ok:
                raise FormalBuildError(f"proof check failed: {detail}")
    return result
