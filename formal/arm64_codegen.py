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


class CodegenError(Exception):
    pass


_CALLEE_SAVED = [19, 20, 21, 22, 23, 24, 25, 26, 27, 28]


def _collect_var_names(f: F.FunctionDef) -> list:
    """Parameters first, then locals in order of first assignment."""
    names = [pname for pname, _ptype in f.params]
    seen = set(names)

    def add(name):
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            names.append(name)

    def walk(stmts):
        for s in stmts or []:
            if isinstance(s, F.AssignStmt):
                if isinstance(s.target, F.IdentExpr):
                    add(s.target.name)
            elif isinstance(s, F.VarDecl):
                add(s.name)
            elif isinstance(s, F.AugAssignStmt):
                if isinstance(s.target, F.IdentExpr):
                    add(s.target.name)
            elif isinstance(s, F.ForStmt):
                add(s.target)
                walk(s.body)
                walk(s.else_body)
            elif isinstance(s, F.IfStmt):
                walk(s.then_body)
                for _c, body in (s.elifs or []):
                    walk(body)
                walk(s.else_body)
            elif isinstance(s, F.WhileStmt):
                walk(s.body)
                walk(s.else_body)

    walk(f.body)
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


class ARM64Codegen:
    """ARM64 code generator over the fire_compiler AST."""

    def __init__(self, test_input: int = 10):
        self.test_input = test_input
        self.asm = Assembler()
        self._functions = {}
        self._current_function = None
        self._if_counter = 0
        self._while_counter = 0
        self._strings = []   # list[(label, bytes)]
        self._str_counter = 0
        self._var_regs = {}
        self._npairs = 1
        # Stack of enclosing loops, innermost last. Each entry:
        #   start -- loop top (continue target for `while`)
        #   step  -- iteration step (continue target for `for`)
        #   break -- label after the loop's else (break target)
        self._loops = []

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
                raise CodegenError(
                    "formal arm64 path only supports `for x in range(...)` "
                    f"loops (got iterable {type(stmt.iterable).__name__})")
            if not isinstance(stmt.target, str) or not stmt.target.isidentifier():
                raise CodegenError(
                    f"for-loop target must be a plain name (got {stmt.target!r})")
            self._emit_loop(cond=None, body=stmt.body,
                            else_body=stmt.else_body or [],
                            for_info=(stmt.target, rargs))
            return

        if isinstance(stmt, F.BreakStmt):
            if not self._loops:
                raise CodegenError("break outside of a loop")
            self._emit_b_to(self._loops[-1]["break"])
            return

        if isinstance(stmt, F.ContinueStmt):
            if not self._loops:
                raise CodegenError("continue outside of a loop")
            self._emit_b_to(self._loops[-1]["step"])
            return

        if isinstance(stmt, F.AugAssignStmt):
            if not isinstance(stmt.target, F.IdentExpr):
                raise CodegenError(
                    "augmented assignment target must be a plain name")
            name = stmt.target.name
            # fire tokens carry `+=`/`-=`/`*=`; the encoder table wants `+`.
            op = stmt.op[:-1] if stmt.op.endswith('=') and stmt.op != '==' \
                else stmt.op
            ops = {"+": encode_add_xd_xn_xm,
                   "-": encode_sub_xd_xn_xm,
                   "*": encode_mul_xd_xn_xm}
            if op not in ops:
                raise CodegenError(
                    f"unsupported augmented operator {stmt.op!r} "
                    f"(formal arm64 path supports + - *)")
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
            if not isinstance(stmt.target, F.IdentExpr):
                raise CodegenError(
                    "assignment target must be a plain name "
                    f"(got {type(stmt.target).__name__})")
            name = stmt.target.name
            if stmt.type_ann is not None and parse_type_name(stmt.type_ann) is None:
                raise CodegenError(
                    f"unsupported type annotation {stmt.type_ann!r} "
                    f"(formal arm64 path supports fixed-width ints only)")
            self._emit_expr(stmt.value)
            self.asm.emit(encode_mov_zr_xn(self._var_regs.get(name, 19), 0))
            return

        if isinstance(stmt, F.VarDecl):
            # Declaration: register is allocated by _collect_var_names; only
            # emit an initializer when one was given.
            if stmt.type_ann is not None and parse_type_name(stmt.type_ann) is None:
                raise CodegenError(
                    f"unsupported type annotation {stmt.type_ann!r} "
                    f"(formal arm64 path supports fixed-width ints only)")
            if stmt.value is not None:
                self._emit_expr(stmt.value)
                self.asm.emit(
                    encode_mov_zr_xn(self._var_regs.get(stmt.name, 19), 0))
            return

        if isinstance(stmt, F.FunctionDef):
            raise CodegenError("nested function definitions are not "
                               "supported on the formal arm64 path")

        raise CodegenError(
            f"unsupported statement {type(stmt).__name__} on the formal "
            f"arm64 path")

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
                            "break": end_label})
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
        ireg = self._var_regs.get(target, 19)
        if isinstance(step, F.IntLiteral):
            self.asm.emit(encode_add_xd_xn_imm(ireg, ireg, step.value))
        elif isinstance(step, F.IdentExpr):
            self.asm.emit(encode_add_xd_xn_xm(
                ireg, ireg, self._var_regs.get(step.name, 19)))
        else:
            raise CodegenError("for-loop step must be a literal or a variable")

    # ── Expressions (result in X0) ─────────────────────────────────

    def _emit_expr(self, expr) -> None:
        if isinstance(expr, F.IntLiteral):
            self._emit_mov_imm("X0", expr.value)
            return

        if isinstance(expr, F.IdentExpr):
            self.asm.emit(encode_mov_zr_xn(0, self._var_regs.get(expr.name, 19)))
            return

        if isinstance(expr, F.BoolLiteral):
            self._emit_mov_imm("X0", 1 if expr.value else 0)
            return

        if isinstance(expr, F.StringLiteral):
            # ADRP+ADD loading the string literal's address into X0; bytes
            # appended after the code, immediates back-patched in resolve().
            label = f"str_{self._str_counter}"
            self._str_counter += 1
            self._strings.append((label, expr.value.encode() + b"\x00"))
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
            raise CodegenError(
                "conditional expressions (x if c else y) are not supported "
                "on the formal arm64 path; use an if statement")

        raise CodegenError(
            f"unsupported expression {type(expr).__name__} on the formal "
            f"arm64 path")

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
        }
        if op in cmp_conds:
            u, s = cmp_conds[op]
            self._emit_cmp(e.left, e.right, u, s)
            return

        # Short-circuit keywords and bitwise ops all lower to the same
        # evaluate-both-sides ALU form the toy path used for and/or
        # (bitwise AND/OR — not Python short-circuit; conditions are
        # truthiness-tested with CBZ after the whole expression).
        alu = {
            "+": encode_add_xd_xn_xm,
            "-": encode_sub_xd_xn_xm,
            "*": encode_mul_xd_xn_xm,
            "&": encode_and_xd_xn_xm,
            "|": encode_orr_xd_xn_xm,
            "^": encode_eor_xd_xn_xm,
            "and": encode_and_xd_xn_xm,
            "or": encode_orr_xd_xn_xm,
        }
        if op in alu:
            self._emit_expr(e.left)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(e.right, "X1")
            self.asm.emit(encode_ldp_sp_post(0, 2))
            self.asm.emit(alu[op](0, 0, 1))
            if op in ("+", "-", "*", "and", "or"):
                self._emit_trunc(common_type(self._ttype(e.left),
                                             self._ttype(e.right)))
            return

        raise CodegenError(
            f"unsupported binary operator {op!r} on the formal arm64 path")

    def _emit_call(self, e: F.CallExpr) -> None:
        name = _callee_symbol(e.func)
        if name is None:
            raise CodegenError(
                f"unsupported call target on the formal arm64 path "
                f"(got {type(e.func).__name__})")
        if e.kwargs:
            names = [k for k, _v in e.kwargs]
            raise CodegenError(
                f"keyword arguments are not supported ({names})")
        if name == "range":
            raise CodegenError("range() is only supported as a for-loop header")
        is_extern = name not in self._functions
        if len(e.args) > 8:
            raise CodegenError(
                f"call {name}(): at most 8 integer arguments are supported "
                f"(got {len(e.args)})")

        # AAPCS: pass up to 8 integer args in X0..X7. Evaluate left-to-right,
        # spilling each result so nested evaluations (which clobber X0/X1/X2)
        # don't destroy earlier arguments. Pop in reverse so arg0 lands in X0.
        # Second slot of each push/pop is XZR so loads never clobber a live arg.
        for arg in e.args:
            self._emit_expr(arg)
            self.asm.emit(encode_stp_sp_pre(0, 31))
        for i in range(len(e.args) - 1, -1, -1):
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
