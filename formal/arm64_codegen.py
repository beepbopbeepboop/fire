#!/usr/bin/env python3
"""ARM64 code generator for the formal path — consumes fire_compiler's AST.

Maps fire_compiler nodes (the project's real AST; fire_compiler.py is the
single source of truth) to ARM64 machine code using AAPCS64:
- First arg: X0
- Return value: X0
- Callee-saved locals: X19..X28 (one register per variable)
- Frame pointer: X29
- Link register (return addr): X30
- Stack grows down from high address

Ported from /Users/mrs/net/chatgpt/claude/formal/compiler/arm64_codegen.py
and re-targeted from that toy project's mini-AST onto fire_compiler nodes.
Proof generation is intentionally NOT wired up yet.
"""

from formal.arm64 import *
from formal.types import (IntType, DEFAULT_INT_TYPE, function_var_types,
                          common_type, infer_expr, resolve, cmp_signed,
                          parse_type_name, _range_args)

import fire_compiler as F
from mojo.middle.boundnames import (
    _with_item_alias_name, bound_names_in_order, _lbn_target_names,
    _lbn_split_commas,
)


class CodegenError(Exception):
    pass


_CALLEE_SAVED = [19, 20, 21, 22, 23, 24, 25, 26, 27, 28]


def _for_target_tree(target: str):
    """Parse a ForStmt target string into a leaf name or nested list.

    `'i'` → `'i'`; `'(a, b)'` → `['a', 'b']`; `'(a, (b, c))'` →
    `['a', ['b', 'c']]`. Returns None when a leaf is not a plain identifier.
    Uses the shared top-level comma split (naive `.split(',')` tears nested
    groups)."""
    t = target.strip()
    if t.startswith("(") and t.endswith(")"):
        parts = _lbn_split_commas(t[1:-1])
        tree = []
        for p in parts:
            child = _for_target_tree(p)
            if child is None:
                return None
            tree.append(child)
        return tree if tree else None
    if t.isidentifier():
        return t
    return None


def _collect_var_names(f: F.FunctionDef) -> list:
    """Parameters first, then locals in order of first assignment.

    Statement-level names come from the shared middle-end walk
    (`mojo.middle.boundnames`) — same structure GIMPLE's
    `_locally_bound_names` uses. Formal only adds MemberExpr field-slot
    keys on top (scalar replacement; backend-specific, not middle-end)."""
    names = bound_names_in_order(f.body, f.params)
    seen = set(names)

    def add(name):
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            names.append(name)

    # MemberExpr field slots (IdentExpr-rooted chains only). Separate full
    # walk so Try/With/Match bodies and expression positions are covered —
    # the shared assign-target walk does not invent slot keys.
    def walk_members(node):
        if node is None or isinstance(node, (str, int, float, bool)):
            return
        if isinstance(node, F.MemberExpr):
            key = _member_slot_key(node)
            if key is not None:
                add(key)
                return
            walk_members(node.obj)
            return
        if isinstance(node, F.CallExpr):
            # Callee path is a symbol, not a value slot; only args matter.
            for a in node.args or []:
                walk_members(a)
            for _k, v in (node.kwargs or []):
                walk_members(v)
            return
        if isinstance(node, F.AssignStmt):
            if isinstance(node.target, F.MemberExpr):
                walk_members(node.target)
            elif isinstance(node.target, F.TupleExpr):
                for el in node.target.elements:
                    if isinstance(el, F.MemberExpr):
                        walk_members(el)
            walk_members(node.value)
            return
        if isinstance(node, F.AugAssignStmt):
            if isinstance(node.target, F.MemberExpr):
                walk_members(node.target)
            walk_members(node.value)
            return
        if hasattr(node, "__dataclass_fields__"):
            for fname in node.__dataclass_fields__:
                if fname in ("line", "col"):
                    continue
                val = getattr(node, fname, None)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, tuple):
                            for x in item:
                                walk_members(x)
                        else:
                            walk_members(item)
                elif isinstance(val, tuple):
                    for x in val:
                        walk_members(x)
                else:
                    walk_members(val)

    walk_members(f.body)

    # for-in (non-range) loop control temps: one index + one blob-pointer
    # register per nesting depth. Backend-local (register allocation only);
    # not middle-end bound names. Depth accounting matches `_emit_for_list`:
    # enter a for-not-range at depth d, walk its body at d+1; a range()
    # for does not consume a depth. Returns (saw_for_in, max_depth).
    def walk_for_temps(stmts, depth: int, acc: list) -> None:
        for s in stmts or []:
            if isinstance(s, F.ForStmt):
                if _range_args(s.iterable) is None:
                    acc[0] = True
                    acc[1] = max(acc[1], depth)
                    body_d = depth + 1
                else:
                    body_d = depth
                walk_for_temps(s.body, body_d, acc)
                walk_for_temps(s.else_body, body_d, acc)
            elif isinstance(s, F.IfStmt):
                walk_for_temps(s.then_body, depth, acc)
                for _c, body in (s.elifs or []):
                    walk_for_temps(body, depth, acc)
                walk_for_temps(s.else_body, depth, acc)
            elif isinstance(s, F.WhileStmt):
                walk_for_temps(s.body, depth, acc)
                walk_for_temps(s.else_body, depth, acc)
            elif isinstance(s, F.TryStmt):
                walk_for_temps(s.body, depth, acc)
                for h in (s.handlers or []):
                    walk_for_temps(h.body, depth, acc)
                walk_for_temps(s.else_body, depth, acc)
                walk_for_temps(s.finally_body, depth, acc)
            elif isinstance(s, F.WithStmt):
                walk_for_temps(s.body, depth, acc)

    acc = [False, -1]
    walk_for_temps(f.body, 0, acc)
    if acc[0]:
        for i in range(acc[1] + 1):
            add(f"_fi{i}")
            add(f"_fb{i}")
    return names


def var_register_map(f: F.FunctionDef) -> dict[str, int]:
    """Variable -> callee-saved register, matching `ARM64Codegen._emit_function`.

    The proof generator reuses this so per-block register-value facts name the
    same register the codegen actually allocated (parameters first, then locals
    in first-assignment order)."""
    return {name: _CALLEE_SAVED[i] for i, name in enumerate(_collect_var_names(f))}


def _callee_symbol(func) -> str | None:
    """Flatten a CallExpr callee to a symbol name string.

    IdentExpr → its name; MemberExpr → dotted chain (obj.method → "obj.method",
    os.path.join → "os.path.join"); other shapes → None (unsupported).
    Dotted names are treated as extern symbols by _emit_call (never in
    self._functions), so module/method calls lower to a BL to that name."""
    if isinstance(func, F.IdentExpr):
        return func.name
    parts = []
    node = func
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    if parts:
        if isinstance(node, F.IdentExpr):
            parts.append(node.name)
        parts.reverse()
        return ".".join(parts)
    return None


def _member_slot_key(expr) -> str | None:
    """Local-slot key for an IdentExpr-rooted MemberExpr chain (`a.b.c` →
    `"a.b.c"`); None when the root is not a plain name (call result, etc.).

    Formal has no heap/object layout: each named-base field is a distinct
    int64 local (scalar replacement of aggregates). Method-call callees
    (`obj.method`) never reach here as values — `_emit_call` uses
    `_callee_symbol` instead."""
    if not isinstance(expr, F.MemberExpr):
        return None
    parts = []
    node = expr
    while isinstance(node, F.MemberExpr):
        parts.append(node.member)
        node = node.obj
    if isinstance(node, F.IdentExpr):
        parts.append(node.name)
        parts.reverse()
        return ".".join(parts)
    return None


class ARM64Codegen:
    """ARM64 code generator over the fire_compiler AST."""

    def __init__(self, test_input: int = 10):
        self.test_input = test_input
        self.asm = Assembler()
        self._functions = {}
        self._current_function = None
        self._if_counter = 0
        self._while_counter = 0
        self._assert_counter = 0
        self._tup_counter = 0
        self._strings = []   # list[(label, bytes)]
        self._str_counter = 0
        self._var_regs = {}
        self._npairs = 1
        # Stack of enclosing loops, innermost last. Each entry:
        #   start -- loop top (continue target for `while`)
        #   step  -- iteration step (continue target for `for`)
        # break -- label after the loop's else (break target)
        self._loops = []
        # Enclosing try-finally bodies, outermost first. Flushed before
        # return/break/continue so finally runs on those paths.
        self._pending_finally = []
        # Bump cursor into the fixed frame's unused 4032-byte region
        # (grows upward from frame bottom). Reset per function.
        self._list_cursor = 0
        # Nesting depth of for-in (non-range) loops currently being emitted.
        # Selects _fi{d}/_fb{d} temps; reset per function.
        self._for_list_depth = 0
        # Names bound to a string pointer this function (StringLiteral RHS
        # or an alias of one). Subscript on these is a byte load/store, not
        # a list-blob index. Reset per function.
        self._string_vars = set()
        # Names bound to a dict pair-blob pointer this function (DictExpr
        # RHS or an alias of one). Subscript on these is a key lookup, not
        # a list index. Reset per function.
        self._dict_vars = set()
        # Unique-label counter for subscript bounds-check exit paths.
        self._sub_counter = 0
        # String literal interning: content → label (same bytes share one
        # ADRP/ADD site). Persists across compile() re-emits so labels stay
        # unique. Pointer equality on interned literals is then valid for
        # dict string keys.
        self._str_intern: dict = {}
        self._str_intern_map: dict = {}

    def compile(self, stmts: list, base_addr: int = 0x100000014) -> tuple:
        """Compile a fire_compiler module statement list to ARM64 machine code.

        `stmts` is Parser(...).parse_module()'s output — may contain imports,
        module-level assigns, etc.; only FunctionDefs are lowered. If a
        `main` function is present it is used as the entry (first in the
        emitted order); otherwise the first FunctionDef is the entry."""
        functions = [s for s in stmts if isinstance(s, F.FunctionDef)]
        if not functions:
            raise CodegenError("no function definitions to compile")
        # Prefer main as entry when present (startup stub BLs functions[0]).
        main = [f for f in functions if f.name == "main"]
        rest = [f for f in functions if f.name != "main"]
        functions = (main + rest) if main else functions
        for f in functions:
            if f.is_generator or f.is_async:
                raise CodegenError(
                    f"{f.name}: async/generator functions are not supported "
                    f"on the formal arm64 path")
            self._functions[f.name] = f

        self.asm.org(base_addr)

        # Startup stub: save LR, set X0 = test_input, BL entry, restore, RET.
        # (Entry is functions[0]; main is preferred when present.)
        self.asm.emit(encode_stp_sp_pre(29, 30))
        test_val = self.test_input
        if test_val <= 0xffff:
            self.asm.emit(encode_movz_xn_imm(0, test_val))
        else:
            self.asm.emit(encode_movz_xn_imm(0, test_val & 0xffff))
            self.asm.emit(encode_movk_xd_imm(0, (test_val >> 16) & 0xffff, 16))
        first_func_name = functions[0].name
        self.asm.emit(encode_bl(0))
        self.asm.emit_label_rel(first_func_name, here_offset=-4)
        self.asm.emit(encode_ldp_sp_post(29, 30))
        self.asm.emit(encode_ret())

        for f in functions:
            self._emit_function(f)

        # Append string literal data (labels resolved for ADRP/ADD loads)
        for label, data in self._strings:
            self.asm.label(label)
            self.asm.emit(data)

        self.asm.resolve()
        code = bytes(self.asm.sections["text"])
        external_syms = list({sym for sym, _, _, _ in self.asm.extern_refs})
        extern_calls = sorted(
            ({"sym": sym, "addr": pos}
             for sym, pos, _, kind in self.asm.extern_refs if kind == "bl"),
            key=lambda c: c["addr"])
        info = {
            "base_addr": base_addr,
            "entry_offset": self.asm.labels.get(first_func_name, 0),
            "func_offset": self.asm.labels.get(first_func_name, 0),
            "labels": dict(self.asm.labels),
            "func_name": first_func_name,
            "external_syms": external_syms,
            "extern_calls": extern_calls,
            "test_input": self.test_input,
        }
        return code, info

    @property
    def func_name(self):
        return self._current_function or ""

    def _emit_function(self, f: F.FunctionDef) -> None:
        self._current_function = f.name
        self.asm.label(f.name)

        var_names = _collect_var_names(f)
        if len(var_names) > len(_CALLEE_SAVED):
            raise CodegenError(
                f"{f.name}: too many variables "
                f"({len(var_names)} > {len(_CALLEE_SAVED)})")
        self._var_regs = {name: _CALLEE_SAVED[i]
                          for i, name in enumerate(var_names)}
        self._npairs = max(1, (len(var_names) + 1) // 2)

        self._call_types = {
            g.name: resolve(parse_type_name(g.return_type) or DEFAULT_INT_TYPE)
            for g in self._functions.values()
        }
        self._vtypes = function_var_types(f, self._call_types)
        self._pending_finally = []
        self._list_cursor = 0
        self._for_list_depth = 0
        self._string_vars = set()
        self._dict_vars = set()

        # Prologue: save FP/LR, set FP, save callee-saved var regs, spill
        # arg0 (X0) into X19 (always, matching formal — even with 0 params),
        # narrow-extend when there is a param, SUB SP frame.
        self.asm.emit(encode_stp_sp_pre(29, 30))
        self.asm.emit(encode_mov_zr_xn(29, 31))  # MOV X29, SP
        for i in range(self._npairs):
            self.asm.emit(encode_stp_sp_pre(19 + 2 * i, 20 + 2 * i))
        self.asm.emit(encode_mov_zr_xn(19, 0))   # MOV X19, X0 (save argument)
        if f.params:
            _pname0, ptype0 = f.params[0]
            pt = resolve(parse_type_name(ptype0) or DEFAULT_INT_TYPE)
            if pt.width < 64:
                self._emit_extend(19, 0, pt)
        self.asm.emit(encode_sub_xd_xn_imm(31, 31, 4032))

        for stmt in f.body:
            self._emit_stmt(stmt)

        if not _always_returns(f.body):
            self.asm.emit(encode_movz_xd_imm(0, 0))
            self._emit_epilogue()

        self._current_function = None

    def _emit_epilogue(self) -> None:
        self.asm.emit(encode_add_xd_xn_imm(31, 31, 4032))
        for i in reversed(range(self._npairs)):
            self.asm.emit(encode_ldp_sp_post(19 + 2 * i, 20 + 2 * i))
        self.asm.emit(encode_ldp_sp_post(29, 30))
        self.asm.emit(encode_ret())

    # ── Statements ─────────────────────────────────────────────────

    def _emit_stmt(self, stmt) -> None:
        if isinstance(stmt, F.ReturnStmt):
            if stmt.value is None:
                self.asm.emit(encode_movz_xd_imm(0, 0))
            else:
                self._emit_expr(stmt.value)
            self._flush_pending_finally()
            self._emit_epilogue()
            return

        if isinstance(stmt, F.IfStmt):
            self._emit_if(stmt)
            return

        if isinstance(stmt, F.ExprStmt):
            self._emit_expr(stmt.value)
            return

        if isinstance(stmt, F.PassStmt):
            return

        if isinstance(stmt, F.GlobalStmt):
            # `global NAME` is a binding declaration only — it emits no
            # runtime operation. formal's locals are callee-saved registers
            # (or stack slots); there is no separate module-global storage
            # to redirect subsequent stores into, so the declaration is a
            # no-op and the following AssignStmt still targets the local.
            return

        if isinstance(stmt, (F.ImportStmt, F.FromImportStmt)):
            # Single-file formal build: no dynamic loader, no sibling-module
            # link. Matches build.py's top-level filter — imports are
            # accepted and ignored; later uses of the bound names lower as
            # ordinary idents (uninitialized / extern as applicable).
            return

        if isinstance(stmt, F.AssertStmt):
            # assert cond [, msg] — evaluate cond; on falsy, _exit(1).
            # msg is not formatted into the diagnostic (no printf on this
            # path); the nonzero exit status is the signal.
            self._emit_expr(stmt.value)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self._assert_counter += 1
            aid = self._assert_counter
            fail_label = f"{self.func_name}_assert{aid}_fail"
            ok_label = f"{self.func_name}_assert{aid}_ok"
            self.asm.emit(encode_cbz_xn(0, 0))
            self.asm.emit_label_rel(fail_label, here_offset=-4)
            self._emit_b_to(ok_label)
            self.asm.label(fail_label)
            # Darwin arm64: x16 = SYS_exit (1), x0 = status, svc #0x80
            self.asm.emit(encode_movz_xd_imm(0, 1))
            self.asm.emit(encode_movz_xd_imm(16, 1))
            self.asm.emit(encode_svc(0x80))
            self.asm.label(ok_label)
            return

        if isinstance(stmt, F.RaiseStmt):
            # No EH runtime: evaluate the exception expression for side
            # effects (args of `raise RuntimeError(...)` etc.), run every
            # enclosing finally (same stack as return), then Darwin
            # exit(1). except handlers stay unreachable — there is no
            # unwinder to route to; the nonzero status is the signal.
            if stmt.value is not None:
                self._emit_expr(stmt.value)
            self._flush_pending_finally()
            self.asm.emit(encode_movz_xd_imm(0, 1))
            self.asm.emit(encode_movz_xd_imm(16, 1))
            self.asm.emit(encode_svc(0x80))
            return

        if isinstance(stmt, F.WhileStmt):
            self._emit_loop(cond=stmt.condition, body=stmt.body,
                            else_body=stmt.else_body or [], for_info=None)
            return

        if isinstance(stmt, F.ForStmt):
            if stmt.is_async:
                raise CodegenError("async for is not supported on the "
                                   "formal arm64 path")
            rargs = _range_args(stmt.iterable)
            if rargs is None:
                self._emit_for_list(stmt, stmt.else_body or [])
                return
            if (not isinstance(stmt.target, str)
                    or not stmt.target.isidentifier()):
                raise CodegenError(
                    f"for-loop target must be a plain name (got {stmt.target!r})")
            self._emit_loop(cond=None, body=stmt.body,
                            else_body=stmt.else_body or [],
                            for_info=(stmt.target, rargs))
            return

        if isinstance(stmt, F.BreakStmt):
            if not self._loops:
                raise CodegenError("break outside of a loop")
            self._flush_pending_finally(self._loops[-1]["fin_depth"])
            self._emit_b_to(self._loops[-1]["break"])
            return

        if isinstance(stmt, F.ContinueStmt):
            if not self._loops:
                raise CodegenError("continue outside of a loop")
            self._flush_pending_finally(self._loops[-1]["fin_depth"])
            self._emit_b_to(self._loops[-1]["step"])
            return

        if isinstance(stmt, F.AugAssignStmt):
            if isinstance(stmt.target, F.SubscriptExpr):
                self._emit_subscript_aug(stmt)
                return
            if isinstance(stmt.target, F.MemberExpr):
                slot = _member_slot_key(stmt.target)
                if slot is None:
                    raise CodegenError(
                        "unsupported augmented assignment target on the "
                        "formal arm64 path")
                name = slot
            elif isinstance(stmt.target, F.IdentExpr):
                name = stmt.target.name
            else:
                raise CodegenError(
                    "augmented assignment target must be a plain name")
            # fire tokens carry `+=`/`|=`/`^=`/…; the encoder table wants
            # the bare operator — same set `_emit_binop`'s ALU map accepts.
            op = stmt.op[:-1] if stmt.op.endswith('=') and stmt.op != '==' \
                else stmt.op
            ops = {"+": encode_add_xd_xn_xm,
                   "-": encode_sub_xd_xn_xm,
                   "*": encode_mul_xd_xn_xm,
                   "&": encode_and_xd_xn_xm,
                   "|": encode_orr_xd_xn_xm,
                   "^": encode_eor_xd_xn_xm}
            if op not in ops:
                raise CodegenError(
                    f"unsupported augmented operator {stmt.op!r} "
                    f"(formal arm64 path supports + - * & | ^)")
            reg = self._var_regs.get(name, 19)
            self.asm.emit(encode_mov_zr_xn(0, reg))
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(stmt.value, "X1")
            self.asm.emit(encode_ldp_sp_post(0, 2))
            self.asm.emit(ops[op](0, 0, 1))
            self._emit_trunc(common_type(
                self._ttype(F.IdentExpr(name)), self._ttype(stmt.value)))
            self.asm.emit(encode_mov_zr_xn(reg, 0))
            return

        if isinstance(stmt, F.AssignStmt):
            if isinstance(stmt.target, F.TupleExpr):
                self._emit_tuple_assign(stmt)
                return
            if isinstance(stmt.target, F.SubscriptExpr):
                self._emit_subscript_store(stmt.target, stmt.value)
                return
            if isinstance(stmt.target, F.MemberExpr):
                name = _member_slot_key(stmt.target)
                if name is None:
                    raise CodegenError(
                        "unsupported assignment target on the formal "
                        "arm64 path "
                        f"(got {type(stmt.target).__name__})")
            elif isinstance(stmt.target, F.IdentExpr):
                name = stmt.target.name
            else:
                raise CodegenError(
                    "assignment target must be a plain name "
                    f"(got {type(stmt.target).__name__})")
            # type_ann is metadata, not a storage decision: formal locals
            # always live in a callee-saved X-reg (or a stack-blob pointer
            # in X0). types.function_var_types already resolves ann-or-
            # infer for the type lattice; non-int ann (dict/list/set/…)
            # must not hard-fail emit — the VALUE still has to lower.
            self._emit_expr(stmt.value)
            self.asm.emit(encode_mov_zr_xn(self._var_regs.get(name, 19), 0))
            self._note_binding(name, stmt.value)
            return

        if isinstance(stmt, F.MultiAssignStmt):
            # Chained `a = b = expr`: evaluate the RHS once (X0 holds it),
            # then MOV into each target — MOV does not clobber X0.
            self._emit_expr(stmt.value)
            for t in stmt.targets:
                if isinstance(t, F.MemberExpr):
                    name = _member_slot_key(t)
                    if name is None:
                        raise CodegenError(
                            "chained assignment target on the formal "
                            "arm64 path "
                            f"(got {type(t).__name__})")
                elif isinstance(t, F.IdentExpr):
                    name = t.name
                else:
                    raise CodegenError(
                        "chained assignment target must be a plain name "
                        f"(got {type(t).__name__})")
                self.asm.emit(
                    encode_mov_zr_xn(self._var_regs.get(name, 19), 0))
            return

        if isinstance(stmt, F.VarDecl):
            # Declaration: register is allocated by _collect_var_names; only
            # emit an initializer when one was given.
            # Same as AssignStmt: ann is metadata; value emission gates.
            if stmt.value is not None:
                self._emit_expr(stmt.value)
                self.asm.emit(
                    encode_mov_zr_xn(self._var_regs.get(stmt.name, 19), 0))
                self._note_binding(stmt.name, stmt.value)
            return

        if isinstance(stmt, F.TryStmt):
            self._emit_try(stmt)
            return

        if isinstance(stmt, F.WithStmt):
            self._emit_with(stmt)
            return

        if isinstance(stmt, F.FunctionDef):
            raise CodegenError("nested function definitions are not "
                               "supported on the formal arm64 path")

        raise CodegenError(
            f"unsupported statement {type(stmt).__name__} on the formal "
            f"arm64 path")

    def _flush_pending_finally(self, depth: int = 0) -> None:
        """Emit pending try-finally frames with index >= depth (innermost
        first), X0 saved across them.

        `depth` is 0 for return (run every enclosing finally) and the
        loop's entry `fin_depth` for break/continue (only frames opened
        inside that loop). The list is truncated first so a return inside
        a finally does not re-enter the same body."""
        if len(self._pending_finally) <= depth:
            return
        fins = self._pending_finally[depth:]
        del self._pending_finally[depth:]
        self.asm.emit(encode_stp_sp_pre(0, 31))
        for fin in reversed(fins):
            for s in fin:
                self._emit_stmt(s)
        self.asm.emit(encode_ldp_sp_post(0, 31))

    def _emit_try(self, stmt: F.TryStmt) -> None:
        """try/except/else/finally without an exception runtime.

        Handlers are skipped: formal has no unwinder, so there is no
        edge from a raise site to an except arm (RaiseStmt itself exits
        the process after flushing finallys). `else` runs on the success
        path (always, without EH). On fall-through the finally emits
        here; on return/break/continue/raise `_flush_pending_finally`
        already ran it and truncated the stack, so the frame may be gone
        — pop only if it is still ours (guards IndexError after a
        return-driven flush)."""
        fin = stmt.finally_body or []
        need_fallthrough = bool(fin)
        if fin:
            self._pending_finally.append(fin)
        try:
            for s in stmt.body:
                self._emit_stmt(s)
            for s in (stmt.else_body or []):
                self._emit_stmt(s)
        finally:
            if fin:
                if (self._pending_finally
                        and self._pending_finally[-1] is fin):
                    self._pending_finally.pop()
                else:
                    need_fallthrough = False
        if need_fallthrough:
            for s in fin:
                self._emit_stmt(s)

    def _emit_with(self, stmt: F.WithStmt) -> None:
        """with-items without a context-manager protocol.

        Evaluate each context expression for its side effects (open(),
        lock acquisition, executor construction, …). With no __enter__/
        __exit__ runtime, an `as` alias is bound to the expression result
        itself (the context-manager object), not to an entered value.
        The body always runs on the fall-through path; return/break/
        continue inside do no cleanup (there is none). `async with`
        raises — same gate as async for."""
        if stmt.is_async:
            raise CodegenError("async with is not supported on the "
                               "formal arm64 path")
        for it in stmt.items or []:
            self._emit_expr(it.expr)
            if it.alias is not None:
                alias = _with_item_alias_name(it.alias)
                self.asm.emit(
                    encode_mov_zr_xn(self._var_regs.get(alias, 19), 0))
        for s in stmt.body:
            self._emit_stmt(s)

    def _emit_tuple_assign(self, stmt: F.AssignStmt) -> None:
        """`a, b = rhs` — two shapes, matching GIMPLE's unpack split.

        Literal TupleExpr/ListExpr of matching length: evaluate each
        element independently (so swaps are safe), push, pop into targets.

        Anything else (CallExpr returning a tuple, IdentExpr holding a
        list, …): evaluate once — X0 is the stack-blob address
        `[count:i64][e0..en-1]` — check the runtime count against the
        target count (mismatch → exit(1), same signal as assert), then
        load each slot. The blob layout is the same one `_emit_list`
        builds and `return (…)` / `return […]` leaves in X0."""
        target = stmt.target
        for el in target.elements:
            if not isinstance(el, F.IdentExpr):
                raise CodegenError(
                    "tuple assignment target elements must be plain names "
                    f"(got {type(el).__name__})")
        n_t = len(target.elements)
        value = stmt.value
        if isinstance(value, (F.TupleExpr, F.ListExpr)):
            if len(value.elements) != n_t:
                raise CodegenError(
                    f"tuple assignment length mismatch: {n_t} targets, "
                    f"{len(value.elements)} values")
            for el in value.elements:
                self._emit_expr(el)
                self.asm.emit(encode_stp_sp_pre(0, 31))
            for i in range(n_t - 1, -1, -1):
                self.asm.emit(encode_ldp_sp_post(0, 31))
                name = target.elements[i].name
                self.asm.emit(
                    encode_mov_zr_xn(self._var_regs.get(name, 19), 0))
            return

        # Blob unpack: X0 = [count][e0..] after evaluating the RHS once.
        self._emit_expr(value)
        self.asm.emit(encode_mov_zr_xn(9, 0))          # X9 = blob base
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))   # X1 = count
        self.asm.emit(encode_sub_xd_xn_imm(2, 1, n_t)) # X2 = count - n_t
        self._tup_counter += 1
        tid = self._tup_counter
        fail_label = f"{self.func_name}_tup{tid}_bad"
        ok_label = f"{self.func_name}_tup{tid}_ok"
        self.asm.emit(encode_cbnz_xn(0, 2))            # offset placeholder
        self.asm.emit_label_rel(fail_label, here_offset=-4)
        self._emit_b_to(ok_label)
        self.asm.label(fail_label)
        # Darwin arm64 exit(1) — same signal as a failed assert.
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok_label)
        # Push e0..e(n-1); pop assigns last target first.
        for i in range(n_t):
            self.asm.emit(encode_ldr_xt_xn_imm(0, 9, 8 * (i + 1)))
            self.asm.emit(encode_stp_sp_pre(0, 31))
        for i in range(n_t - 1, -1, -1):
            self.asm.emit(encode_ldp_sp_post(0, 31))
            name = target.elements[i].name
            self.asm.emit(encode_mov_zr_xn(self._var_regs.get(name, 19), 0))

    def _emit_if(self, stmt: F.IfStmt) -> None:
        """if / elif / else — elifs lower to a chain of nested conditionals."""
        self._if_counter += 1
        if_id = self._if_counter
        end_label = f"{self.func_name}_endif_{if_id}"

        # Build the else-chain: else_body is the innermost; walk elifs
        # reversed so elifs[0] ends up as the first alternate test.
        # We emit sequentially: test; fail → next test; pass → body; B end.
        branch_labels = []
        # First: the main condition.
        # Collect (cond, body) pairs in source order: (main, elif0, elif1, ...)
        tests = [(stmt.condition, stmt.then_body)]
        for cond, body in (stmt.elifs or []):
            tests.append((cond, body))

        has_fallthrough_else = stmt.else_body is not None or bool(stmt.elifs)
        # For each test except possibly the last, a failed test jumps to the
        # next test's label (or to else/end).
        next_labels = []
        for i in range(len(tests)):
            next_labels.append(f"{self.func_name}_if{if_id}_alt_{i}")
        else_label = f"{self.func_name}_else_{if_id}"

        for i, (cond, body) in enumerate(tests):
            self.asm.label(next_labels[i])
            self._emit_expr(cond)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cbz_xn(0, 0))
            fail = next_labels[i + 1] if i + 1 < len(tests) else (
                else_label if has_fallthrough_else else end_label)
            self.asm.emit_label_rel(fail, here_offset=-4)
            for s in body:
                self._emit_stmt(s)
            if i < len(tests) - 1 or stmt.else_body is not None:
                self._emit_b_to(end_label)

        if has_fallthrough_else:
            self.asm.label(else_label)
            if stmt.else_body:
                for s in stmt.else_body:
                    self._emit_stmt(s)
        self.asm.label(end_label)

    def _emit_b_to(self, label: str) -> None:
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(label, here_offset=-4)

    def _emit_loop(self, cond, body, else_body, for_info) -> None:
        """while or for-range loop with optional else clause.

        Layout:
            start:  <condition>  --falsy--> false:
                    <body>
            step:   [<for: i += step>]  B start
            false:  [<else_body>]
            end:
        `break` → end (skips else); `continue` → step (for-loops still
        advance the counter)."""
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        start_label = f"{fn}_loop{wid}_start"
        step_label = f"{fn}_loop{wid}_step"
        false_label = f"{fn}_loop{wid}_false"
        end_label = f"{fn}_loop{wid}_end"

        is_for = for_info is not None
        if is_for:
            target, rargs = for_info
            ireg = self._var_regs.get(target, 19)
            start_val, end_val, step_val = self._range_info(rargs)
            self._emit_expr(start_val)
            self.asm.emit(encode_mov_zr_xn(ireg, 0))

        self._loops.append({"start": start_label, "step": step_label,
                            "break": end_label,
                            "fin_depth": len(self._pending_finally)})
        try:
            self.asm.label(start_label)
            if is_for:
                self._emit_cmp(F.IdentExpr(target), end_val, "cc", "lt")
            else:
                self._emit_expr(cond)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cbz_xn(0, 0))
            self.asm.emit_label_rel(false_label, here_offset=-4)

            for s in body:
                self._emit_stmt(s)

            self.asm.label(step_label)
            if is_for:
                self._emit_for_inc(target, step_val)
            self.asm.emit(encode_b(0))
            self.asm.emit_label_rel(start_label, here_offset=-4)

            self.asm.label(false_label)
            for s in (else_body or []):
                self._emit_stmt(s)
            self.asm.label(end_label)
        finally:
            self._loops.pop()

    def _emit_for_list(self, stmt, else_body) -> None:
        """for x in <list-blob iterable> (not range), including tuple targets.

        The iterable is evaluated once into `_fb{d}` (X0 → temp). The blob
        layout matches `_emit_list` / tuple return: [count:i64][elem…].
        Index lives in `_fi{d}`. Element address = blob+8+8*i via
        ADD #8 then ADD Xm,LSL #3 then LDR.

        Target may be a plain name or the parser's tuple spelling
        `"(a, b)"` — names come from the shared `_lbn_target_names` walk
        (same split GIMPLE/register allocation use). For a tuple target,
        each element must itself be a blob `[count][e0…]`; count is checked
        against the target arity (mismatch → exit(1), same as `a, b = rhs`).
        break → end; continue → step (increments i first)."""
        d = self._for_list_depth
        self._for_list_depth += 1
        try:
            it = stmt.iterable
            # `x or []` / `a and b` lower via short-circuit and can yield a
            # list blob; other BinaryOps (e.g. `a + b`) are not blob-shaped.
            iter_ok = type(it) in (F.IdentExpr, F.CallExpr, F.ListExpr,
                                   F.TupleExpr, F.MemberExpr)
            if isinstance(it, F.BinaryOp) and it.op in ("or", "and"):
                iter_ok = True
            if not iter_ok:
                raise CodegenError(
                    "formal arm64 path only supports `for x in range(...)` "
                    f"loops (got iterable {type(it).__name__})")
            tnames = _lbn_target_names(stmt.target) if isinstance(
                stmt.target, str) else []
            if not tnames or any(not n.isidentifier() for n in tnames):
                raise CodegenError(
                    f"for-loop target must be a plain name or tuple of "
                    f"plain names (got {stmt.target!r})")
            ttree = _for_target_tree(stmt.target) if isinstance(
                stmt.target, str) else stmt.target
            if ttree is None:
                raise CodegenError(
                    f"for-loop target must be a plain name or tuple of "
                    f"plain names (got {stmt.target!r})")
            is_tuple_target = isinstance(ttree, list)

            self._while_counter += 1
            wid = self._while_counter
            fn = self.func_name
            start_label = f"{fn}_fl{wid}_start"
            step_label = f"{fn}_fl{wid}_step"
            false_label = f"{fn}_fl{wid}_false"
            end_label = f"{fn}_fl{wid}_end"

            ireg = self._var_regs.get(f"_fi{d}", 19)
            breg = self._var_regs.get(f"_fb{d}", 19)

            # Materialize the iterable once (also correct for `for x in x`).
            self._emit_expr(stmt.iterable)
            self.asm.emit(encode_mov_zr_xn(breg, 0))
            self.asm.emit(encode_movz_xd_imm(ireg, 0))

            self._loops.append({"start": start_label, "step": step_label,
                                "break": end_label,
                                "fin_depth": len(self._pending_finally)})
            try:
                self.asm.label(start_label)
                self.asm.emit(encode_mov_zr_xn(9, breg))
                self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))
                self.asm.emit(encode_cmp_xn_xm(ireg, 1))
                self.asm.emit(encode_cset_xd_cond(0, "lt"))
                self.asm.emit(encode_cbz_xn(0, 0))
                self.asm.emit_label_rel(false_label, here_offset=-4)

                self.asm.emit(encode_add_xd_xn_imm(2, 9, 8))
                self.asm.emit(encode_add_xd_xn_xm_lsl3(2, 2, ireg))
                self.asm.emit(encode_ldr_xt_xn_imm(0, 2, 0))

                if is_tuple_target:
                    # X0 = element (pointer to [count][e0…] blob).
                    # Nested groups are themselves blobs — recurse.
                    self._emit_for_unpack(ttree, f"{fn}_flt{wid}")
                else:
                    self.asm.emit(encode_mov_zr_xn(
                        self._var_regs.get(tnames[0], 19), 0))

                for s in stmt.body:
                    self._emit_stmt(s)

                self.asm.label(step_label)
                self.asm.emit(encode_add_xd_xn_imm(ireg, ireg, 1))
                self._emit_b_to(start_label)

                self.asm.label(false_label)
                for s in else_body:
                    self._emit_stmt(s)
                self.asm.label(end_label)
            finally:
                self._loops.pop()
        finally:
            self._for_list_depth -= 1

    def _emit_for_unpack(self, tree, tag: str) -> None:
        """Unpack a for-target tree from the blob pointer in X0.

        `tree` is a leaf name (`str`) or a list of children (tuple target).
        Leaf: move X0 into the name's register. List: X0 must be a blob
        `[count][e0…]` with count == len(children); each child recurses
        with its element in X0. Arity mismatch → exit(1)."""
        if isinstance(tree, str):
            self.asm.emit(encode_mov_zr_xn(
                self._var_regs.get(tree, 19), 0))
            return
        n_t = len(tree)
        self.asm.emit(encode_mov_zr_xn(9, 0))          # X9 = blob base
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))   # X1 = count
        self.asm.emit(encode_sub_xd_xn_imm(2, 1, n_t)) # X2 = count - n_t
        self._tup_counter += 1
        tid = self._tup_counter
        fail_label = f"{tag}_bad{tid}"
        ok_label = f"{tag}_ok{tid}"
        self.asm.emit(encode_cbnz_xn(0, 2))
        self.asm.emit_label_rel(fail_label, here_offset=-4)
        self._emit_b_to(ok_label)
        self.asm.label(fail_label)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok_label)
        for i, child in enumerate(tree):
            self.asm.emit(encode_ldr_xt_xn_imm(0, 9, 8 * (i + 1)))
            self._emit_for_unpack(child, tag)

    def _range_info(self, rargs: list) -> tuple:
        """(start, end, step) expressions for range(): 1/2/3 args."""
        zero = F.IntLiteral(0)
        one = F.IntLiteral(1)
        if len(rargs) == 1:
            return zero, rargs[0], one
        if len(rargs) == 2:
            return rargs[0], rargs[1], one
        if len(rargs) == 3:
            return rargs[0], rargs[1], rargs[2]
        raise CodegenError(f"range() takes 1-3 arguments, got {len(rargs)}")

    def _emit_for_inc(self, target: str, step) -> None:
        """Advance a for-range counter by `step`.

        Accepts IntLiteral / IdentExpr, and UnaryOp `-` of either (so
        `range(a, b, -1)` lowers — the parser keeps `-1` as
        `UnaryOp('-', IntLiteral(1))`, not a negative literal). Negative
        steps use SUB (ARM64 ADD imm12 is unsigned)."""
        ireg = self._var_regs.get(target, 19)
        if (isinstance(step, F.UnaryOp) and step.op == "-"
                and isinstance(step.operand, F.IntLiteral)):
            self.asm.emit(encode_sub_xd_xn_imm(ireg, ireg, step.operand.value))
            return
        if isinstance(step, F.IntLiteral):
            if step.value < 0:
                self.asm.emit(encode_sub_xd_xn_imm(ireg, ireg, -step.value))
            else:
                self.asm.emit(encode_add_xd_xn_imm(ireg, ireg, step.value))
            return
        if isinstance(step, F.UnaryOp) and step.op == "-" \
                and isinstance(step.operand, F.IdentExpr):
            self.asm.emit(encode_sub_xd_xn_xm(
                ireg, ireg, self._var_regs.get(step.operand.name, 19)))
            return
        if isinstance(step, F.IdentExpr):
            self.asm.emit(encode_add_xd_xn_xm(
                ireg, ireg, self._var_regs.get(step.name, 19)))
            return
        if isinstance(step, F.BinaryOp) and step.op == "+" \
                and isinstance(step.left, F.IdentExpr):
            # `range(a, b, i + k)` — evaluate k (must be literal-ish),
            # then add both. Only the common `var + int` form.
            k = step.right
            if isinstance(k, F.IntLiteral) and k.value >= 0:
                self.asm.emit(encode_add_xd_xn_xm(
                    ireg, ireg, self._var_regs.get(step.left.name, 19)))
                self.asm.emit(encode_add_xd_xn_imm(ireg, ireg, k.value))
                return
        raise CodegenError("for-loop step must be a literal or a variable")

    # ── Expressions (result in X0) ─────────────────────────────────

    def _emit_expr(self, expr) -> None:
        if isinstance(expr, F.IntLiteral):
            self._emit_mov_imm("X0", expr.value)
            return

        if isinstance(expr, F.IdentExpr):
            # Python singletons parse as bare idents (True/False become
            # BoolLiteral; None stays IdentExpr). Materialize them as
            # integers so `x is None` compares against 0, not a random var reg.
            if expr.name == "None":
                self.asm.emit(encode_movz_xd_imm(0, 0))
                return
            if expr.name == "True":
                self.asm.emit(encode_movz_xd_imm(0, 1))
                return
            if expr.name == "False":
                self.asm.emit(encode_movz_xd_imm(0, 0))
                return
            self.asm.emit(encode_mov_zr_xn(0, self._var_regs.get(expr.name, 19)))
            return

        if isinstance(expr, F.BoolLiteral):
            self._emit_mov_imm("X0", 1 if expr.value else 0)
            return

        if isinstance(expr, F.NoneLiteral):
            self.asm.emit(encode_movz_xd_imm(0, 0))
            return

        if isinstance(expr, F.StringLiteral):
            # ADRP+ADD loading the string literal's address into X0; bytes
            # appended after the code, immediates back-patched in resolve().
            # Interned by content so equal literals share one address —
            # makes pointer equality valid for dict string keys.
            label = self._intern_string(expr.value)
            self.asm.emit_adrp_add(0, label)
            return

        if isinstance(expr, F.UnaryOp):
            if expr.op == "not":
                self._emit_expr(expr.operand)
                self.asm.emit(encode_cmp_xn_imm(0, 0))
                self.asm.emit(encode_cset_xd_cond(0, "eq"))
                return
            if expr.op == "-":
                self._emit_expr(expr.operand)
                self.asm.emit(encode_neg_xd_xn(0, 0))
                self._emit_trunc(self._ttype(expr.operand))
                return
            if expr.op == "+":
                self._emit_expr(expr.operand)
                return
            raise CodegenError(
                f"unsupported unary operator {expr.op!r} on the formal "
                f"arm64 path")

        if isinstance(expr, F.BinaryOp):
            self._emit_binop(expr)
            return

        if isinstance(expr, F.CompareChain):
            raise CodegenError(
                "chained comparisons (a < b < c) are not supported on the "
                "formal arm64 path; split into explicit and/or")

        if isinstance(expr, F.CallExpr):
            self._emit_call(expr)
            return

        if isinstance(expr, F.TernaryExpr):
            # x = a if c else b  →  same branch shape as if/else, both arms
            # leave their value in X0, join at end.
            self._if_counter += 1
            tid = self._if_counter
            fn = self.func_name
            else_label = f"{fn}_tern{tid}_else"
            end_label = f"{fn}_tern{tid}_end"
            self._emit_expr(expr.condition)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cbz_xn(0, 0))
            self.asm.emit_label_rel(else_label, here_offset=-4)
            self._emit_expr(expr.then_val)
            self._emit_b_to(end_label)
            self.asm.label(else_label)
            self._emit_expr(expr.else_val)
            self.asm.label(end_label)
            return

        if isinstance(expr, F.MemberExpr):
            key = _member_slot_key(expr)
            if key is not None:
                self.asm.emit(
                    encode_mov_zr_xn(0, self._var_regs.get(key, 19)))
                return
            # Non-named base (call result, literal, …): evaluate the base
            # for side effects; formal has no object model, so the field
            # itself reads as 0.
            self._emit_expr(expr.obj)
            self.asm.emit(encode_movz_xd_imm(0, 0))
            return

        if isinstance(expr, (F.ListExpr, F.TupleExpr)):
            # TupleExpr and ListExpr have identical `elements` shape and
            # one blob layout — same stack-allocated [count][e0..en-1]
            # emitter, not a parallel implementation.
            self._emit_list(expr)
            return

        if isinstance(expr, F.DictExpr):
            self._emit_dict(expr)
            return

        if isinstance(expr, F.SubscriptExpr):
            self._emit_subscript(expr)
            return

        raise CodegenError(
            f"unsupported expression {type(expr).__name__} on the formal "
            f"arm64 path")

    def _intern_string(self, s: str) -> str:
        """Return a stable data label for `s`, emitting bytes on first use."""
        if s in self._str_intern:
            return self._str_intern[s]
        label = f"str_{self._str_counter}"
        self._str_counter += 1
        self._strings.append((label, s.encode() + b"\x00"))
        self._str_intern[s] = label
        return label

    def _note_binding(self, name: str, value) -> None:
        """Track whether `name` holds a string pointer or a dict pair-blob.

        Mutually exclusive marks: DictExpr RHS → dict var; StringLiteral
        (or alias of a known string) → string var; anything else clears
        both. Enables subscript dispatch (byte / key-lookup / list index)."""
        if isinstance(value, F.DictExpr):
            self._dict_vars.add(name)
            self._string_vars.discard(name)
        elif isinstance(value, F.StringLiteral):
            self._string_vars.add(name)
            self._dict_vars.discard(name)
        elif isinstance(value, F.IdentExpr):
            if value.name in self._dict_vars:
                self._dict_vars.add(name)
                self._string_vars.discard(name)
            elif value.name in self._string_vars:
                self._string_vars.add(name)
                self._dict_vars.discard(name)
            else:
                self._string_vars.discard(name)
                self._dict_vars.discard(name)
        else:
            self._string_vars.discard(name)
            self._dict_vars.discard(name)

    def _is_dict_subscript(self, obj) -> bool:
        """True when `obj` is known to hold a dict pair-blob pointer."""
        if isinstance(obj, F.IdentExpr):
            return obj.name in self._dict_vars
        if isinstance(obj, F.MemberExpr):
            key = _member_slot_key(obj)
            return key is not None and key in self._dict_vars
        if isinstance(obj, F.DictExpr):
            return True
        return False

    def _is_string_subscript(self, obj) -> bool:
        """True when `obj` is known to hold a char* (byte index path)."""
        if isinstance(obj, F.StringLiteral):
            return True
        if isinstance(obj, F.IdentExpr):
            return obj.name in self._string_vars
        if isinstance(obj, F.MemberExpr):
            key = _member_slot_key(obj)
            return key is not None and key in self._string_vars
        return False

    def _emit_subscript(self, e: F.SubscriptExpr) -> None:
        """`obj[index]` → element/byte value in X0.

        List/tuple blobs: `[count:i64][e0…]`, unsigned bounds-checked
        (negative indices wrap like Python, then bounds-check); OOB →
        Darwin exit(1). String pointers (literal or tracked var): raw
        byte load, no header."""
        if e.attrs is not None:
            raise CodegenError(
                "type-parameter subscript [...] is not supported on the "
                "formal arm64 path")
        if isinstance(e.index, F.SliceExpr):
            raise CodegenError(
                "slice subscript [...] is not supported on the formal "
                "arm64 path")
        if isinstance(e.index, F.TupleExpr):
            raise CodegenError(
                "multi-index subscript [...] is not supported on the "
                "formal arm64 path")
        self._emit_subscript_addr(e)
        if self._is_string_subscript(e.obj):
            self.asm.emit(encode_ldrb_wd_wn(0, 0, 0))
        else:
            self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))

    def _emit_dict(self, expr: F.DictExpr) -> None:
        """Stack-allocate a dict pair-blob: [count_pairs][k0][v0][k1][v1]…

        X0 exits holding the blob address. Keys/values are int64 or
        (interned) string/inner-blob pointers — same slot width as list
        blobs. Cursor reserves the full blob before any child is evaluated
        so nested containers sit above it. Star-unpack not applicable."""
        n = len(expr.pairs)
        size = 8 * (1 + 2 * n)
        if self._list_cursor + size > 4032:
            raise CodegenError(
                f"dict literal exceeds the formal frame "
                f"({self._list_cursor + size} > 4032 bytes)")
        offset = self._list_cursor
        self._list_cursor += size

        self._emit_list_base(offset)
        self._emit_mov_imm("X10", n)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
        for i, (k, v) in enumerate(expr.pairs):
            self._emit_expr(k)
            self._emit_list_base(offset)
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * (1 + 2 * i)))
            self._emit_expr(v)
            self._emit_list_base(offset)
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * (2 + 2 * i)))
        if n == 0:
            self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_dict_lookup_addr(self, e: F.SubscriptExpr) -> None:
        """X0 = &dict[key] value slot. Missing key → Darwin exit(1).

        Pair-blob layout: [count][k0][v0]…; value i is at base+16+16*i.
        Key compare is raw 64-bit equality — valid for interned string
        literals and integer keys (the formal dict surface).

        Stack on entry to the scan (two STP pushes):
          [SP+0]  key (lookup), [SP+8] XZR
          [SP+16] base,        [SP+24] junk
        Hit path stashes the value address in X4 across the two pops."""
        self._sub_counter += 1
        sid = self._sub_counter
        fn = self.func_name
        miss_label = f"{fn}_dlk{sid}_miss"
        hit_label = f"{fn}_dlk{sid}_hit"
        end_label = f"{fn}_dlk{sid}_end"
        loop_label = f"{fn}_dlk{sid}_loop"

        if isinstance(e.obj, F.DictExpr):
            self._emit_dict(e.obj)
        else:
            self._emit_expr(e.obj)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # push base
        self._emit_expr_to(e.index, "X1")               # X1 = key
        self.asm.emit(encode_stp_sp_pre(1, 31))         # push key
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 16))  # X9 = base
        self.asm.emit(encode_ldr_xt_xn_imm(2, 9, 0))    # X2 = count
        self.asm.emit(encode_movz_xd_imm(3, 0))         # X3 = i

        self.asm.label(loop_label)
        self.asm.emit(encode_cmp_xn_xm(3, 2))
        self.asm.emit(encode_cset_xd_cond(4, "ge"))     # 1 when i >= count
        self.asm.emit(encode_cbnz_xn(0, 4))
        self.asm.emit_label_rel(miss_label, here_offset=-4)
        # key_i addr = base + 8 + 16*i
        self.asm.emit(encode_add_xd_xn_imm(5, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl4(5, 5, 3))
        self.asm.emit(encode_ldr_xt_xn_imm(6, 5, 0))    # X6 = key_i
        self.asm.emit(encode_ldr_xt_xn_imm(7, 31, 0))   # X7 = lookup key
        self.asm.emit(encode_cmp_xn_xm(6, 7))
        self.asm.emit(encode_cset_xd_cond(8, "eq"))
        self.asm.emit(encode_cbnz_xn(0, 8))
        self.asm.emit_label_rel(hit_label, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(3, 3, 1))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(loop_label, here_offset=-4)

        self.asm.label(hit_label)
        self.asm.emit(encode_add_xd_xn_imm(4, 5, 8))    # X4 = value slot
        self.asm.emit(encode_ldp_sp_post(0, 31))        # pop key
        self.asm.emit(encode_ldp_sp_post(0, 31))        # pop base
        self.asm.emit(encode_mov_zr_xn(0, 4))
        self._emit_b_to(end_label)

        self.asm.label(miss_label)
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(end_label)

    def _emit_subscript_addr(self, e: F.SubscriptExpr) -> None:
        """X0 = &obj[index]. Blob path bounds-checks (exit 1 on OOB)."""
        if self._is_dict_subscript(e.obj):
            self._emit_dict_lookup_addr(e)
            return
        if self._is_string_subscript(e.obj):
            self._emit_expr(e.obj)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(e.index, "X1")
            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))  # base from [SP]
            self.asm.emit(encode_add_xd_xn_xm(0, 0, 1))
            self.asm.emit(encode_mov_zr_xn(2, 0))
            self.asm.emit(encode_ldp_sp_post(0, 31))
            self.asm.emit(encode_mov_zr_xn(0, 2))
            return
        obj_ok = type(e.obj) in (F.IdentExpr, F.CallExpr, F.ListExpr,
                                 F.TupleExpr, F.MemberExpr, F.SubscriptExpr)
        if not obj_ok:
            raise CodegenError(
                "subscript base must be a list/tuple name or literal on "
                f"the formal arm64 path (got {type(e.obj).__name__})")
        self._sub_counter += 1
        sid = self._sub_counter
        fn = self.func_name
        oob_label = f"{fn}_sub{sid}_oob"
        skip_neg_label = f"{fn}_sub{sid}_skipneg"
        end_label = f"{fn}_sub{sid}_end"

        self._emit_expr(e.obj)                 # X0 = blob base
        self.asm.emit(encode_stp_sp_pre(0, 2)) # save base
        self._emit_expr_to(e.index, "X1")      # X1 = index
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 0))  # X9 = base
        self.asm.emit(encode_ldr_xt_xn_imm(2, 9, 0))   # X2 = count
        # Python-style negative index: if index < 0, index += count.
        self.asm.emit(encode_cmp_xn_imm(1, 0))
        self.asm.emit(encode_cset_xd_cond(3, "lt"))
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(skip_neg_label, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_xm(1, 1, 2))
        self.asm.label(skip_neg_label)
        # OOB unless count > index (unsigned — covers still-negative).
        self.asm.emit(encode_cmp_xn_xm(2, 1))
        self.asm.emit(encode_cset_xd_cond(3, "hi"))
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(oob_label, here_offset=-4)
        # addr = base + 8 + index*8
        self.asm.emit(encode_add_xd_xn_imm(4, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(4, 4, 1))
        self.asm.emit(encode_mov_zr_xn(0, 4))
        self.asm.emit(encode_ldp_sp_post(0, 31))  # restore SP (clobbers X0)
        self.asm.emit(encode_mov_zr_xn(0, 4))
        self._emit_b_to(end_label)
        self.asm.label(oob_label)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(end_label)

    def _emit_subscript_store(self, target: F.SubscriptExpr, value) -> None:
        """`obj[index] = value` — evaluate addr once, then store."""
        self._emit_subscript_addr(target)
        self.asm.emit(encode_stp_sp_pre(0, 2))  # save addr
        self._emit_expr(value)                  # X0 = value
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 0))  # X9 = addr
        if self._is_string_subscript(target.obj):
            self.asm.emit(encode_strb_wd_wn(0, 9, 0))
        else:
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))

    def _emit_subscript_aug(self, stmt) -> None:
        """`obj[index] <op>= value` — addr and old value evaluated once."""
        op = stmt.op[:-1] if stmt.op.endswith('=') and stmt.op != '==' \
            else stmt.op
        ops = {"+": encode_add_xd_xn_xm,
               "-": encode_sub_xd_xn_xm,
               "*": encode_mul_xd_xn_xm,
               "&": encode_and_xd_xn_xm,
               "|": encode_orr_xd_xn_xm,
               "^": encode_eor_xd_xn_xm}
        if op not in ops:
            raise CodegenError(
                f"unsupported augmented operator {stmt.op!r} "
                f"(formal arm64 path supports + - * & | ^)")
        target = stmt.target
        is_str = self._is_string_subscript(target.obj)
        self._emit_subscript_addr(target)
        self.asm.emit(encode_stp_sp_pre(0, 31))   # push addr (X0, XZR)
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 0))  # X9 = addr
        if is_str:
            self.asm.emit(encode_ldrb_wd_wn(0, 9, 0))
        else:
            self.asm.emit(encode_ldr_xt_xn_imm(0, 9, 0))  # X0 = old
        self.asm.emit(encode_stp_sp_pre(0, 31))   # push old (stack: old, addr)
        self._emit_expr_to(stmt.value, "X1")      # X1 = value
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))  # X0 = old (re-load)
        self.asm.emit(ops[op](0, 0, 1))           # X0 = old op value
        # addr is at [SP+16] after the two pushes.
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 16))
        if is_str:
            self.asm.emit(encode_strb_wd_wn(0, 9, 0))
        else:
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))

    def _emit_list_base(self, offset: int) -> None:
        """X9 = address of the list blob at frame_bottom + offset.

        Frame geometry after the prologue (SP grows down):
          [X29+8]  saved LR
          [X29]    saved FP          <- X29
          [X29-16] saved X19,X20
          ...
          [X29-16*npairs-4032, X29-16*npairs)  unused 4032-byte scratch
        The body only pushes BELOW SP (stp_sp_pre), so this region stays
        free for list blobs. Addressing is X29-relative because SP moves
        during expression evaluation. Exits with base in X9."""
        self.asm.emit(encode_mov_zr_xn(9, 29))
        self.asm.emit(encode_sub_xd_xn_imm(9, 9, 4032))
        saved = 16 * self._npairs
        if saved:
            self.asm.emit(encode_sub_xd_xn_imm(9, 9, saved))
        if offset:
            self.asm.emit(encode_add_xd_xn_imm(9, 9, offset))

    def _emit_list(self, expr: F.ListExpr) -> None:
        """Stack-allocate a list blob: [count:i64][elem0]...[elemN-1].

        X0 exits holding the blob address (pointer-sized, no heap). Elements
        are int64s or string/inner-list pointers. Cursor reserves the full
        blob before any element is evaluated so nested lists sit above it.
        Exits without moving SP — the blob lives until the function returns.
        Star-unpack elements have no compile-time length and raise."""
        for el in expr.elements:
            if isinstance(el, F.UnaryOp) and el.op == "*":
                raise CodegenError(
                    "list unpacking (*...) is not supported on the formal "
                    "arm64 path")
        n = len(expr.elements)
        size = 8 * (1 + n)
        if self._list_cursor + size > 4032:
            raise CodegenError(
                f"list literals exceed the formal frame "
                f"({self._list_cursor + size} > 4032 bytes)")
        offset = self._list_cursor
        self._list_cursor += size

        self._emit_list_base(offset)
        self._emit_mov_imm("X10", n)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
        for i, el in enumerate(expr.elements):
            self._emit_expr(el)
            # Recompute base: element emission (calls, ADRP, …) clobbers X9.
            self._emit_list_base(offset)
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * (i + 1)))
        if n == 0:
            self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_binop(self, e: F.BinaryOp) -> None:
        op = e.op
        # Comparisons
        cmp_conds = {
            "<=": ("ls", "le"),
            ">": ("hi", "gt"),
            "==": ("eq", "eq"),
            ">=": ("cs", "ge"),
            "<": ("cc", "lt"),
            "!=": ("ne", "ne"),
            # Identity on the formal path is unboxed integer value equality
            # (no heap objects, no interning table).
            "is": ("eq", "eq"),
            "is not": ("ne", "ne"),
        }
        if op in cmp_conds:
            u, s = cmp_conds[op]
            self._emit_cmp(e.left, e.right, u, s)
            return

        # Short-circuit `and`/`or` produce a value in X0 (Python semantics:
        # return the deciding operand, not a bitwise mix). Conditions still
        # truthiness-test X0 with CBZ after the whole expression. Bitwise
        # ops stay in the ALU table below.
        if op in ("and", "or"):
            self._emit_and_or(e.left, e.right, is_or=(op == "or"))
            return

        # Bitwise ALU — evaluate both sides.
        alu = {
            "+": encode_add_xd_xn_xm,
            "-": encode_sub_xd_xn_xm,
            "*": encode_mul_xd_xn_xm,
            "&": encode_and_xd_xn_xm,
            "|": encode_orr_xd_xn_xm,
            "^": encode_eor_xd_xn_xm,
        }
        if op in alu:
            self._emit_expr(e.left)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(e.right, "X1")
            self.asm.emit(encode_ldp_sp_post(0, 2))
            self.asm.emit(alu[op](0, 0, 1))
            if op in ("+", "-", "*"):
                self._emit_trunc(common_type(self._ttype(e.left),
                                             self._ttype(e.right)))
            return

        if op in ("in", "not in"):
            self._emit_membership(e.left, e.right, invert=(op == "not in"))
            return

        raise CodegenError(
            f"unsupported binary operator {op!r} on the formal arm64 path")

    def _emit_and_or(self, left, right, is_or: bool) -> None:
        """Python short-circuit `and`/`or` as a value in X0.

        `or`: evaluate left; if nonzero keep it, else evaluate right.
        `and`: evaluate left; if zero keep it, else evaluate right.
        This is what `x or []` / `params or []` need — bitwise OR of a
        list pointer and an empty-list blob pointer is garbage."""
        self._if_counter += 1
        aid = self._if_counter
        fn = self.func_name
        end_label = f"{fn}_ao{aid}_end"
        skip_label = f"{fn}_ao{aid}_skip"
        self._emit_expr(left)
        self.asm.emit(encode_cmp_xn_imm(0, 0))
        # or: nonzero → done (skip right); and: zero → done.
        branch = encode_cbnz_xn(0, 0) if is_or else encode_cbz_xn(0, 0)
        self.asm.emit(branch)
        self.asm.emit_label_rel(skip_label, here_offset=-4)
        self._emit_expr(right)
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(end_label, here_offset=-4)
        self.asm.label(skip_label)
        self.asm.label(end_label)

    def _emit_membership(self, left, right, invert: bool) -> None:
        """`needle in haystack` / `needle not in haystack` over a list blob.

        RHS must lower to a formal list blob `[count:i64][elem…]` — IdentExpr,
        CallExpr, ListExpr, TupleExpr, or MemberExpr (SRA field slot holding a
        blob pointer; same shapes `_emit_for_list` plus field loads).
        Linear scan of int64 elements; result 0/1 in X0. `not in` inverts.
        String RHS is rejected (string pointers are not blob bases); set/dict
        membership is out of scope (no runtime type tags)."""
        if isinstance(right, F.StringLiteral):
            raise CodegenError(
                "`in`/`not in` RHS must be a list/tuple name or literal on "
                "the formal arm64 path (got StringLiteral)")
        if type(right) not in (F.IdentExpr, F.CallExpr, F.ListExpr,
                               F.TupleExpr, F.MemberExpr):
            raise CodegenError(
                "`in`/`not in` RHS must be a list/tuple name or literal on "
                f"the formal arm64 path (got {type(right).__name__})")

        self._if_counter += 1
        mid = self._if_counter
        fn = self.func_name
        loop_label = f"{fn}_in{mid}_loop"
        notfound_label = f"{fn}_in{mid}_nf"
        found_label = f"{fn}_in{mid}_hit"
        end_label = f"{fn}_in{mid}_end"

        # needle (left) on the stack so element loads can clobber X0/X1.
        # Slot stays pushed for the whole scan; each exit pops it, then
        # overwrites X0 with the boolean result.
        self._emit_expr(left)
        self.asm.emit(encode_stp_sp_pre(0, 2))
        # haystack blob → X9; count → X2; index → X3 (scratch, no calls).
        self._emit_expr_to(right, "X1")
        self.asm.emit(encode_mov_zr_xn(9, 1))
        self.asm.emit(encode_ldr_xt_xn_imm(2, 9, 0))
        self.asm.emit(encode_movz_xd_imm(3, 0))

        self.asm.label(loop_label)
        self.asm.emit(encode_cmp_xn_xm(3, 2))
        self.asm.emit(encode_cset_xd_cond(4, "ge"))  # 1 when i >= count
        self.asm.emit(encode_cbnz_xn(0, 4))
        self.asm.emit_label_rel(notfound_label, here_offset=-4)

        self.asm.emit(encode_add_xd_xn_imm(5, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(5, 5, 3))
        self.asm.emit(encode_ldr_xt_xn_imm(5, 5, 0))  # elem
        self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 0)) # needle from [SP]
        self.asm.emit(encode_cmp_xn_xm(5, 6))
        self.asm.emit(encode_cset_xd_cond(7, "eq"))
        self.asm.emit(encode_cbnz_xn(0, 7))
        self.asm.emit_label_rel(found_label, here_offset=-4)

        self.asm.emit(encode_add_xd_xn_imm(3, 3, 1))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(loop_label, here_offset=-4)

        self.asm.label(notfound_label)
        self.asm.emit(encode_ldp_sp_post(0, 1))
        self.asm.emit(encode_movz_xd_imm(0, 1 if invert else 0))
        self._emit_b_to(end_label)

        self.asm.label(found_label)
        self.asm.emit(encode_ldp_sp_post(0, 1))
        self.asm.emit(encode_movz_xd_imm(0, 0 if invert else 1))

        self.asm.label(end_label)

    def _bind_call_args(self, name: str, e: F.CallExpr) -> list:
        """Reorder args+kwargs into positional form for a known callee.

        Fills gaps left by a kwarg that targets a later parameter using that
        parameter's default (or empty for *args/**kwargs). Trailing optional
        parameters the caller omitted are dropped — the callee's prologue
        only consumes the registers actually passed.
        """
        if not e.kwargs:
            return list(e.args)
        fdef = self._functions.get(name)
        if fdef is None:
            names = [k for k, _v in e.kwargs]
            raise CodegenError(
                f"keyword arguments are not supported ({names})")
        params = [pname for pname, _ptype in fdef.params]
        slots: list = list(e.args)
        if len(slots) > len(params):
            raise CodegenError(
                f"call {name}(): too many positional arguments "
                f"({len(slots)} for {len(params)} parameters)")
        slots.extend([None] * (len(params) - len(slots)))
        for k, v in e.kwargs:
            idx = None
            for i, pname in enumerate(params):
                if pname == k or pname.lstrip("*") == k:
                    idx = i
                    break
            if idx is None:
                # **kwargs swallows unknown names; there is no place to put
                # them in an AAPCS call, so they are dropped (documented).
                if any(pname.startswith("**") for pname in params):
                    continue
                raise CodegenError(
                    f"call {name}(): unexpected keyword argument {k!r}")
            if idx < len(e.args):
                raise CodegenError(
                    f"call {name}(): multiple values for argument {k!r}")
            if slots[idx] is not None:
                raise CodegenError(
                    f"call {name}(): multiple values for argument {k!r}")
            slots[idx] = v
        last = -1
        for i, s in enumerate(slots):
            if s is not None:
                last = i
        slots = slots[: last + 1]
        for i, s in enumerate(slots):
            if s is not None:
                continue
            pname = params[i]
            if pname.startswith("*"):
                # empty *args/**kwargs: nothing to pass in this slot
                slots[i] = F.IntLiteral(0)
                continue
            if fdef.param_has_default.get(pname):
                slots[i] = fdef.param_defaults[pname]
            else:
                raise CodegenError(
                    f"call {name}(): missing required argument {pname!r}")
        return slots

    def _emit_call(self, e: F.CallExpr) -> None:
        name = _callee_symbol(e.func)
        if name is None:
            raise CodegenError(
                f"unsupported call target on the formal arm64 path "
                f"(got {type(e.func).__name__})")
        if name == "range":
            raise CodegenError("range() is only supported as a for-loop header")
        is_extern = name not in self._functions
        if is_extern:
            # Unknown signature: AAPCS has no place for Python kwargs on a
            # raw BL. Drop them (they are almost always literals like
            # flush=True) and pass positional args only — same ABI the
            # extern path already uses for zero-kwarg calls.
            args = list(e.args)
        else:
            args = self._bind_call_args(name, e)
        if len(args) > 8:
            raise CodegenError(
                f"call {name}(): at most 8 integer arguments are supported "
                f"(got {len(args)})")

        # AAPCS: pass up to 8 integer args in X0..X7. Evaluate left-to-right,
        # spilling each result so nested evaluations (which clobber X0/X1/X2)
        # don't destroy earlier arguments. Pop in reverse so arg0 lands in X0.
        # Second slot of each push/pop is XZR so loads never clobber a live arg.
        for arg in args:
            self._emit_expr(arg)
            self.asm.emit(encode_stp_sp_pre(0, 31))
        for i in range(len(args) - 1, -1, -1):
            self.asm.emit(encode_ldp_sp_post(0, 31))
            if i != 0:
                self.asm.emit(encode_mov_zr_xn(i, 0))
        if is_extern:
            self.asm.emit_extern_bl(name)
        else:
            self.asm.emit(encode_bl(0))
            self.asm.emit_label_rel(name, here_offset=-4)

    def _ttype(self, e) -> IntType:
        return infer_expr(e, self._vtypes, self._call_types)

    def _emit_extend(self, dst: int, src: int, t) -> None:
        """Materialize the full 64-bit representative of type t in X<dst>.

        SXTB/SXTH write a 32-bit result (zero-extended into 64), so 8/16-bit
        signed types need a second SXTW to sign-extend 32 -> 64."""
        t = resolve(t)
        if t.width == 64:
            return
        if t.signed:
            if t.width == 32:
                self.asm.emit(encode_sxtw_xd_wn(dst, src))
            else:
                self.asm.emit({8: encode_sxtb_wd_wn,
                               16: encode_sxth_wd_wn}[t.width](dst, src))
                self.asm.emit(encode_sxtw_xd_wn(dst, dst))
        else:
            self.asm.emit(encode_and_xd_xn_imm(dst, dst, t.width))

    def _emit_trunc(self, t) -> None:
        self._emit_extend(0, 0, t)

    def _emit_cmp(self, l, r, unsigned_cond: str, signed_cond: str) -> None:
        self._emit_expr(l)
        self.asm.emit(encode_stp_sp_pre(0, 2))
        self._emit_expr_to(r, "X1")
        self.asm.emit(encode_ldp_sp_post(0, 2))
        self.asm.emit(encode_cmp_xn_xm(0, 1))
        if cmp_signed(common_type(self._ttype(l), self._ttype(r))):
            self.asm.emit(encode_cset_xd_cond(0, signed_cond))
        else:
            self.asm.emit(encode_cset_xd_cond(0, unsigned_cond))

    def _emit_expr_to(self, expr, reg: str) -> None:
        self._emit_expr(expr)
        if reg != "X0":
            self.asm.emit(encode_mov_zr_xn(_reg_num(reg), 0))

    def _emit_mov_imm(self, reg: str, imm: int) -> None:
        rd = _reg_num(reg)
        if imm < 0:
            imm = imm & 0xffffffffffffffff
        if imm == 0:
            self.asm.emit(encode_movz_xd_imm(rd, 0))
        elif imm <= 0xffff:
            self.asm.emit(encode_movz_xd_imm(rd, imm))
        else:
            low16 = imm & 0xffff
            self.asm.emit(encode_movz_xd_imm(rd, low16))
            imm >>= 16
            pos = 16
            while imm > 0:
                chunk = imm & 0xffff
                self.asm.emit(encode_movk_xd_imm(rd, chunk, pos))
                imm >>= 16
                pos += 16


def _always_returns(stmts: list) -> bool:
    """Whether a statement list provably returns on every path."""
    if not stmts:
        return False
    st = stmts[0]
    rest = stmts[1:]
    if isinstance(st, F.ReturnStmt):
        return True
    if isinstance(st, F.IfStmt):
        if not st.else_body and not st.elifs:
            return _always_returns(rest)  # if can fall through; check rest
        if not _always_returns(st.then_body):
            return _always_returns(rest)
        for _c, body in (st.elifs or []):
            if not _always_returns(body):
                return _always_returns(rest)
        if st.else_body and not _always_returns(st.else_body):
            return _always_returns(rest)
        # All branches return — but statements after the if still matter.
        return _always_returns(rest) if rest else True
    if isinstance(st, F.WhileStmt):
        return _always_returns(rest)  # the loop body may not run
    return _always_returns(rest)


def _reg_num(reg: str) -> int:
    reg = reg.upper()
    _regs = {
        "X0": 0, "X1": 1, "X2": 2, "X3": 3, "X4": 4, "X5": 5, "X6": 6, "X7": 7,
        "X8": 8, "X9": 9, "X10": 10, "X11": 11, "X12": 12, "X13": 13, "X14": 14,
        "X15": 15, "X16": 16, "X17": 17, "X18": 18, "X19": 19, "X20": 20,
        "X21": 21, "X22": 22, "X23": 23, "X24": 24, "X25": 25, "X26": 26,
        "X27": 27, "X28": 28, "X29": 29, "X30": 30,
        "X31": 31, "SP": 31, "XZR": 31, "WZR": 31,
    }
    if reg not in _regs:
        raise ValueError(f"Unknown register: {reg}")
    return _regs[reg]
