#!/usr/bin/env python3
"""ARM64 code generator for the formal path — consumes fire_compiler's AST.

Maps fire_compiler nodes (the project's real AST; fire_compiler.py is the
single source of truth) to ARM64 machine code using AAPCS64:
- First arg: X0
- Return value: X0
- Callee-saved locals: first 10 names in X19..X28; overflow spills to
  stack slots at the top of the fixed scratch region
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
import mojo.middle.comptime as comptime_eval
from formal import model as M
from mojo.middle.boundnames import (
    _with_item_alias_name, bound_names_in_order, _lbn_target_names,
    _lbn_split_commas,
)

# Fixed per-function scratch above the saved-pair area. 8160 = 2×4080
# (each fits an imm12 SUB/ADD; a single imm12 maxes at 4095). Grows the
# blob/spill region past the old 4032 cap that large functions exhausted
# mid-expression (list concat / comprehension reserves left 0 free).
_SCRATCH = 131072
_SCRATCH_CHUNK = 4080


class CodegenError(Exception):
    pass


_CALLEE_SAVED = [19, 20, 21, 22, 23, 24, 25, 26, 27, 28]


def _for_target_tree(target: str):
    """Parse a for/comprehension target string into a leaf name or nested list.

    `'i'` → `'i'`; `'(a, b)'` → `['a', 'b']`; `'a, b'` (the comprehension
    Generator.target spelling, no surrounding parens) → `['a', 'b']`;
    `'(a, (b, c))'` → `['a', ['b', 'c']]`. Returns None when a leaf is not
    a plain identifier. Uses the shared top-level comma split (naive
    `.split(',')` tears nested groups)."""
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
    # Bare comma form (comprehension targets): 'a, b' / 'a, b, c'
    if "," in t:
        parts = _lbn_split_commas(t)
        if len(parts) > 1:
            tree = []
            for p in parts:
                child = _for_target_tree(p)
                if child is None:
                    return None
                tree.append(child)
            return tree if tree else None
    if t.startswith("*"):
        rest = t[1:].strip()
        if rest.isidentifier():
            return "*" + rest
        return None
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

    # Comprehension generator loops: one index + one blob-pointer temp per
    # nesting depth (`_ci{d}`/`_cb{d}`), independent of for-list depths so a
    # comprehension inside a for (or vice versa) cannot alias temps.
    def walk_compr_temps(node, depth: int, acc: list) -> None:
        if node is None or isinstance(node, (str, int, float, bool)):
            return
        if isinstance(node, list):
            # A statement list is what this is called with (`f.body`), and a
            # list has no __dataclass_fields__, so without this the walk
            # returned immediately and NO comprehension temp was ever
            # allocated. They then fell through _store_var/_load_var's
            # unknown-name path, which silently uses X19 — so `_cb0` (the
            # loop's blob base) and `_ci0` (the index) aliased one register,
            # and storing the index destroyed the base. Every comprehension
            # read `ldr xN, [x0]`.
            for x in node:
                walk_compr_temps(x, depth, acc)
            return
        if isinstance(node, F.Comprehension):
            gens = node.generators or []
            n = len(gens)
            if n:
                acc[0] = True
                acc[1] = max(acc[1], depth + n - 1)
            for g in gens:
                walk_compr_temps(g.iterable, depth, acc)
                for c in g.conditions or []:
                    walk_compr_temps(c, depth + n, acc)
            walk_compr_temps(node.element, depth + n, acc)
            if node.key is not None:
                walk_compr_temps(node.key, depth + n, acc)
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
                                walk_compr_temps(x, depth, acc)
                        else:
                            walk_compr_temps(item, depth, acc)
                elif isinstance(val, tuple):
                    for x in val:
                        walk_compr_temps(x, depth, acc)
                else:
                    walk_compr_temps(val, depth, acc)

    acc_c = [False, -1]
    walk_compr_temps(f.body, 0, acc_c)
    if acc_c[0]:
        for i in range(acc_c[1] + 1):
            add(f"_ci{i}")
            add(f"_cb{i}")
    return names


def _allocation_order(f: F.FunctionDef) -> list:
    """Register-then-spill allocation order for a function's locals.

    Comptime parameters first (they are leading arguments — the call site
    passes them ahead of the runtime ones, see `_comptime_param_names` and
    `_specialization_args`), then the runtime parameters (prologue always MOV
    X19, X0 — the FIRST parameter must be X19, so a generic function's X19 is
    its first comptime parameter and its first runtime parameter lands one
    register later), then for-list control temps (`_fi{d}`/`_fb{d}` — hot in
    the loop, prefer registers), then remaining locals in `_collect_var_names`
    order. First `len(_CALLEE_SAVED)` names get X19..X28; the rest spill."""
    names = _collect_var_names(f)
    ct = _comptime_param_names(f)
    nparams = len(f.params or [])
    params = names[:nparams]
    rest = names[nparams:]
    # A comptime parameter is only ever READ in the body, never assigned, so
    # `bound_names_in_order` (which walks assignments) does not list it and it
    # has to be added here or it gets no register home at all — every read
    # then falls back to X19 and the generic's comptime and runtime
    # parameters alias each other. A name that is also a runtime parameter
    # (a shadowed comptime name) keeps the runtime parameter's home, so the
    # de-dup below can never hand one register to two names.
    taken = set(params) | set(rest)
    ct = [n for n in ct if n not in taken]
    temps = [n for n in rest
             if n[:3] in ("_fi", "_fb", "_ci", "_cb")]
    others = [n for n in rest if n not in set(temps)]
    return ct + params + temps + others


def var_register_map(f: F.FunctionDef) -> dict[str, int]:
    """Variable -> callee-saved register, matching `ARM64Codegen._emit_function`.

    The proof generator reuses this so per-block register-value facts name the
    same register the codegen actually allocated (parameters first, then
    for-list temps, then locals). Only the first `len(_CALLEE_SAVED)` names
    appear — the rest live in stack spill slots, not registers."""
    names = _allocation_order(f)
    return {name: _CALLEE_SAVED[i]
            for i, name in enumerate(names[:len(_CALLEE_SAVED)])}


# The comptime RULES (which branch, what a binding folds to, how a bracket
# call binds parameters) live in mojo/middle/comptime.py, shared with the
# gimple backend and usable as-is by the x86-64 one. What is left here is the
# arm64 half: materialize a constant, and emit the runtime fallback when a
# decision comes back "not statically known".


def _comptime_param_names(f: F.FunctionDef) -> list:
    return comptime_eval.param_names(f)


def _callee_symbol(func) -> str | None:
    """Flatten a CallExpr callee to a symbol name string.

    IdentExpr → its name; MemberExpr → dotted chain (obj.method → "obj.method",
    os.path.join → "os.path.join"); a SubscriptExpr over either →
    `<name>[<comptime bindings>]` (a comptime specialization, see
    `_specialization_of`); other shapes → None (unsupported).
    Dotted names are treated as extern symbols by _emit_call (never in
    self._functions), so module/method calls lower to a BL to that name."""
    if isinstance(func, F.SubscriptExpr):
        return _specialization_of(func)
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


def _specialization_of(func: F.SubscriptExpr) -> str | None:
    """`f[a, b](...)` → "f", the bare name of the generic being specialized."""
    name = comptime_eval.specialization_name(func)
    if name is not None:
        return name
    base = func.obj
    if isinstance(base, F.MemberExpr):
        return _member_slot_key(base)
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


def _emit_add_imm(asm, xd: int, xn: int, imm: int) -> None:
    """ADD Xd, Xn, #imm for imm > 4095 (split into imm12 chunks)."""
    while imm > 0:
        chunk = min(imm, 4095)
        asm.emit(encode_add_xd_xn_imm(xd, xn, chunk))
        imm -= chunk


def _emit_sub_imm(asm, xd: int, xn: int, imm: int) -> None:
    """SUB Xd, Xn, #imm for imm > 4095 (split into imm12 chunks)."""
    while imm > 0:
        chunk = min(imm, 4095)
        asm.emit(encode_sub_xd_xn_imm(xd, xn, chunk))
        imm -= chunk


class ARM64Codegen:
    """ARM64 code generator over the fire_compiler AST."""

    def __init__(self, test_input: int = 10, dylib_syms: dict = None,
                 comptime_hook=None, module_source: str = ""):
        self.test_input = test_input
        self.asm = Assembler()
        self._functions = {}
        self._structs: dict = {}
        self._current_function = None
        self._if_counter = 0
        self._while_counter = 0
        self._assert_counter = 0
        self._tup_counter = 0
        self._strings = []   # list[(label, bytes)]
        self._str_counter = 0
        self._var_regs = {}
        self._var_spills = {}
        self._npairs = 1
        self._spill_bytes = 0
        # PCs of the branches that test an `if`/`elif`/`while` condition.
        # A short-circuit `and`/`or` in a condition emits a CBZ/CBNZ of its
        # own, so the proof generator cannot tell the `if`'s branch from the
        # `and`/`or`'s by opcode alone -- it has to be told.  See
        # `generate_arm64_proof`'s `_cond_branches` consumer.
        self._cond_branch_pcs = []
        self._blob_cap = _SCRATCH
        # Stack of enclosing loops, innermost last. Each entry:
        #   start -- loop top (continue target for `while`)
        #   step  -- iteration step (continue target for `for`)
        # break -- label after the loop's else (break target)
        self._loops = []
        # Enclosing try-finally bodies, outermost first. Flushed before
        # return/break/continue so finally runs on those paths.
        self._pending_finally = []
        # Bump cursor into the fixed frame's unused scratch region
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
        # `comptime NAME = value` bindings for the function being emitted:
        # name -> folded constant. These are compile-time constants, NOT
        # locals — nothing is stored, and every read materializes the value
        # (see `_emit_comptime_read`). Reset per function, exactly like the
        # container-tracking sets above: a `comptime` in one function does
        # not bind in the next.
        self._comptime_vals: dict = {}
        # {bare callee name -> exported symbol} for the formal libraries this
        # program links against. A call to one of these names is emitted
        # against the library's exported spelling, so the image can record the
        # dependency and dyld can bind it; without the map the same call
        # becomes a BL against a symbol nothing defines.
        self._dylib_syms: dict = dict(dylib_syms or {})
        # Compile-time evaluator for `comptime f(...)`: a (name, args) -> int
        # hook that RUNS the callee with this backend (formal/
        # comptime_runner.py). Keeping it out here is what lets the folding
        # RULES stay in mojo/middle/comptime.py for every backend to share.
        self._comptime_hook = comptime_hook
        # `comptime NAME = [a, b, c]` — a list/tuple-valued binding, kept as
        # its AST (the elements are not all one scalar, so there is nothing to
        # fold them *to*). Only consulted to unroll `comptime for x in NAME`,
        # the way the gimple path's `_comptime_list_asts` is; see
        # mojo/middle/comptime.py for why a list binding is recorded rather
        # than rejected. Reset per function, like _comptime_vals.
        self._comptime_list_asts: dict = {}
        # Unique-label counter for subscript bounds-check exit paths.
        self._sub_counter = 0
        # String literal interning: content → label (same bytes share one
        # ADRP/ADD site). Persists across compile() re-emits so labels stay
        # unique. Pointer equality on interned literals is then valid for
        # dict string keys.
        self._str_intern: dict = {}
        self._str_intern_map: dict = {}
        # Nonzero while evaluating a for-iterable / membership RHS / list
        # concat operand: BinaryOp `+`/`|` then mean list/set ops, not the
        # integer ALU forms.
        self._container_ctx = 0

    def compile(self, stmts: list, base_addr: int = 0x100000014,
                emit_startup: bool = True, structs: list = None) -> tuple:
        """Compile a fire_compiler module statement list to ARM64 machine code.

        `stmts` is Parser(...).parse_module()'s output — may contain imports,
        module-level assigns, etc.; only FunctionDefs are lowered. If a
        `main` function is present it is used as the entry (first in the
        emitted order); otherwise the first FunctionDef is the entry."""
        functions = [s for s in stmts if isinstance(s, F.FunctionDef)]
        if not functions:
            raise CodegenError("no function definitions to compile")
        # Structs, indexed by name. They arrive as a separate list because the
        # callers hand `compile()` a FUNCTION list (closures and lambdas have
        # already been lifted out of it), so the StructDefs are not in `stmts`
        # to be picked up here. This is what lets a `S(...)` constructor be
        # recognised as a type rather than falling through the call path and
        # becoming a BL against a symbol named `S` that nothing defines.
        for st in (structs or []):
            self._structs[st.name] = st
        if emit_startup:
            main = [f for f in functions if f.name == "main"]
            rest = [f for f in functions if f.name != "main"]
            functions = (main + rest) if main else functions
        for f in functions:
            # async def and generators lower as ordinary functions: formal
            # has no event loop / iterator protocol, so `await` is identity
            # and `yield` leaves its value in X0 (compile-only fidelity).
            self._functions[f.name] = f

        self.asm.org(base_addr)

        first_func_name = functions[0].name
        if emit_startup:
            self.asm.emit(encode_stp_sp_pre(29, 30))
            test_val = self.test_input
            if test_val <= 0xffff:
                self.asm.emit(encode_movz_xn_imm(0, test_val))
            else:
                self.asm.emit(encode_movz_xn_imm(0, test_val & 0xffff))
                self.asm.emit(encode_movk_xd_imm(0, (test_val >> 16) & 0xffff, 16))
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
            # PCs of the branches that test an `if`/`elif`/`while`/ternary
            # condition.  The proof generator needs these because a
            # short-circuit `and`/`or` in a condition emits a CBZ/CBNZ that
            # looks just like the `if`'s own branch, and picking the wrong one
            # makes it model the condition as the `and`/`or`'s left operand.
            "cond_branches": sorted(self._cond_branch_pcs),
        }
        return code, info

    @property
    def func_name(self):
        return self._current_function or ""

    def _emit_function(self, f: F.FunctionDef) -> None:
        self._current_function = f.name
        self.asm.label(f.name)

        var_names = _allocation_order(f)
        n_reg = min(len(var_names), len(_CALLEE_SAVED))
        self._var_regs = {name: _CALLEE_SAVED[i]
                          for i, name in enumerate(var_names[:n_reg])}
        self._var_spills = {name: i
                            for i, name in enumerate(var_names[n_reg:])}
        self._spill_bytes = 8 * len(self._var_spills)
        if self._spill_bytes > _SCRATCH:
            raise CodegenError(
                f"{f.name}: too many variables "
                f"({len(var_names)}; spill {self._spill_bytes} > {_SCRATCH})")
        # Spill slots sit at the TOP of the scratch (just below the
        # saved-pair area); list/dict blobs grow from the bottom and
        # must stop before the first spill slot.
        self._blob_cap = _SCRATCH - self._spill_bytes
        self._npairs = max(1, (n_reg + 1) // 2)

        self._call_types = {
            g.name: resolve(parse_type_name(g.return_type) or DEFAULT_INT_TYPE)
            for g in self._functions.values()
        }
        self._vtypes = function_var_types(f, self._call_types)
        self._pending_finally = []
        self._list_cursor = 0
        self._for_list_depth = 0
        self._compr_depth = 0
        self._container_ctx = 0
        self._string_vars = set()
        self._dict_vars = set()
        self._comptime_vals = {}
        self._comptime_list_asts = {}

        # Prologue: save FP/LR, set FP, save callee-saved var regs, move each
        # incoming argument into ITS OWN callee-saved home (always arg0 into
        # X19, matching formal — even with 0 params), narrow-extend each to its
        # declared width, SUB SP frame.
        self.asm.emit(encode_stp_sp_pre(29, 30))
        self.asm.emit(encode_mov_zr_xn(29, 31))  # MOV X29, SP
        for i in range(self._npairs):
            self.asm.emit(encode_stp_sp_pre(19 + 2 * i, 20 + 2 * i))
        self.asm.emit(encode_mov_zr_xn(19, 0))   # MOV X19, X0 (argument 0)
        # AAPCS delivers argument i in Xi on entry, and Xi is caller-saved —
        # so arguments 1..7 have to be moved into the callee-saved register
        # they were allocated to BEFORE anything clobbers X0..X7. Only arg0
        # used to be moved, which meant arguments 1..7 were read back from a
        # callee-saved home that still held the CALLER's value: every function
        # with 2+ parameters silently computed on garbage (`add2(3, 7)`
        # returned 232, not 307; `add3(1, 2, 3)` returned 24, not 10203).
        # Invisible in the single-argument cases the run tests cover, and
        # invisible to compilation — only running the binary shows it.
        # The incoming arguments, in ABI order: a generic function's comptime
        # parameters first (the call site passes them ahead of the runtime
        # ones), then its runtime parameters.
        incoming = M.incoming_args(f)
        for i, (pname, ptype) in enumerate(incoming):
            if i >= 8:
                break            # AAPCS has no register for argument 8+
            if i == 0:
                # Already in X19 by the unconditional save above, which also
                # keeps the no-parameter case (unknown-name reads fall back to
                # X19 and so still see the entry argument).
                home, src = 19, 19
            else:
                home = self._var_regs.get(pname)
                if home is None:
                    # Past the 10 callee-saved registers, so this parameter's
                    # home is a spill slot: write the incoming argument there
                    # now, or its first read in the body would load whatever
                    # the slot happened to hold. Same addressing as
                    # `_store_var`'s spill path. NOT reachable today — the
                    # caller only ever passes 8 arguments (AAPCS X0-X7, see
                    # `_emit_call`), so at most 8 parameters exist to be
                    # spilled — but it is written rather than left as a
                    # silent-wrong-value trap for whoever raises that limit.
                    if pname in self._var_spills:
                        self.asm.emit(encode_mov_zr_xn(17, i))
                        _emit_sub_imm(self.asm, 17, 17,
                                      self._spill_off(pname))
                        self.asm.emit(encode_str_xt_xn_imm(17, 17, 0))
                    continue
                self.asm.emit(encode_mov_zr_xn(home, i))
                src = home
            if ptype is None:
                continue         # a comptime parameter: already a full word
            self._emit_extend(home, src,
                              resolve(parse_type_name(ptype) or DEFAULT_INT_TYPE))
        _emit_sub_imm(self.asm, 31, 31, _SCRATCH)

        for stmt in f.body:
            self._emit_stmt(stmt)

        if not _always_returns(f.body):
            self.asm.emit(encode_movz_xd_imm(0, 0))
            self._emit_epilogue()

        self._current_function = None

    def _emit_epilogue(self) -> None:
        _emit_add_imm(self.asm, 31, 31, _SCRATCH)
        for i in reversed(range(self._npairs)):
            self.asm.emit(encode_ldp_sp_post(19 + 2 * i, 20 + 2 * i))
        self.asm.emit(encode_ldp_sp_post(29, 30))
        self.asm.emit(encode_ret())

    def _spill_off(self, name: str) -> int:
        """X29-relative distance down to `name`'s spill slot.

        Slot i lives at `X29 - 16*npairs - 8*(i+1)` — the high end of the
        scratch, just below the saved-pair area. LDR/STR only
        take a non-negative unsigned offset, so callers materialize
        `X29 - off` into X17 first."""
        return 16 * self._npairs + 8 * (self._var_spills[name] + 1)

    def _load_var(self, name: str, dst: int) -> None:
        """dst = local `name`. Register homes MOV; spill slots LDR via X17.

        Unknown names fall back to X19 (same as the old `.get(..., 19)`)."""
        if name in self._var_regs:
            r = self._var_regs[name]
            if dst != r:
                self.asm.emit(encode_mov_zr_xn(dst, r))
            return
        if name in self._var_spills:
            off = self._spill_off(name)
            self.asm.emit(encode_mov_zr_xn(17, 29))
            _emit_sub_imm(self.asm, 17, 17, off)
            self.asm.emit(encode_ldr_xt_xn_imm(dst, 17, 0))
            return
        if dst != 19:
            self.asm.emit(encode_mov_zr_xn(dst, 19))

    def _store_var(self, name: str, src: int) -> None:
        """local `name` = src. Register homes MOV; spill slots STR via X17."""
        if name in self._var_regs:
            r = self._var_regs[name]
            if src != r:
                self.asm.emit(encode_mov_zr_xn(r, src))
            return
        if name in self._var_spills:
            off = self._spill_off(name)
            self.asm.emit(encode_mov_zr_xn(17, 29))
            _emit_sub_imm(self.asm, 17, 17, off)
            self.asm.emit(encode_str_xt_xn_imm(src, 17, 0))
            return
        self.asm.emit(encode_mov_zr_xn(19, src))

    def _var_reg_or_scratch(self, name: str, scratch: int) -> int:
        """Register holding `name`, or load into `scratch` and return it."""
        if name in self._var_regs:
            return self._var_regs[name]
        self._load_var(name, scratch)
        return scratch

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

        if isinstance(stmt, F.StructDef):
            # Type-only: fields live as SRA slots when used; methods were
            # lifted by closure discovery. Nothing to emit here.
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
            # async for lowers as a plain for (no event loop on this path).
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
                self._check_comptime_target(name, "augmented assignment")
            else:
                raise CodegenError(
                    "augmented assignment target must be a plain name")
            # fire tokens carry `+=`/`|=`/`^=`/…; the encoder table wants
            # the bare operator — same set `_emit_binop`'s ALU map accepts.
            op = stmt.op[:-1] if stmt.op.endswith('=') and stmt.op != '==' \
                else stmt.op
            if op in M.AUG_SHIFT_OPS:
                self._load_var(name, 0)
                self.asm.emit(encode_stp_sp_pre(0, 2))
                self._emit_expr_to(stmt.value, "X1")
                self.asm.emit(encode_ldp_sp_post(0, 2))
                self._emit_shift_reg(op, signed=cmp_signed(
                    self._ttype(F.IdentExpr(name))))
                self._emit_trunc(common_type(
                    self._ttype(F.IdentExpr(name)), self._ttype(stmt.value)))
                self._store_var(name, 0)
                return
            ops = {"+": encode_add_xd_xn_xm,
                   "-": encode_sub_xd_xn_xm,
                   "*": encode_mul_xd_xn_xm,
                   "&": encode_and_xd_xn_xm,
                   "|": encode_orr_xd_xn_xm,
                   "^": encode_eor_xd_xn_xm}
            if op not in M.AUG_OPS:
                raise CodegenError(
                    f"unsupported augmented operator {stmt.op!r} "
                    f"(formal arm64 path supports "
                    f"{' '.join(M.AUG_OPS)})")
            if op in M.AUG_DIV_OPS or op == "**":
                # Same lowering as the binary form (UDIV/SDIV, or DIV+MSUB
                # for `%`, with the divide-by-zero exit; the `**` unroller for
                # a small literal exponent), so `c //= 2` and `c = c // 2` —
                # and `c **= 2` and `c = c ** 2` — agree.
                self._emit_div_shift_pow(
                    F.BinaryOp(op=op,
                               left=F.IdentExpr(name=name),
                               right=stmt.value),
                    op)
                self._store_var(name, 0)
                return
            self._load_var(name, 0)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(stmt.value, "X1")
            self.asm.emit(encode_ldp_sp_post(0, 2))
            self.asm.emit(ops[op](0, 0, 1))
            self._emit_trunc(common_type(
                self._ttype(F.IdentExpr(name)), self._ttype(stmt.value)))
            self._store_var(name, 0)
            return

        if isinstance(stmt, F.AssignStmt):
            if isinstance(stmt.target, F.TupleExpr):
                self._emit_tuple_assign(stmt)
                return
            if isinstance(stmt.target, F.SubscriptExpr):
                self._emit_subscript_store(stmt.target, stmt.value)
                return
            if isinstance(stmt.target, F.SliceExpr):
                self._emit_slice_store(stmt.target, stmt.value)
                return
            if isinstance(stmt.target, F.MemberExpr):
                name = _member_slot_key(stmt.target)
                if name is None:
                    # Non-named base (`obj[i].field = v`): formal has no
                    # object model — evaluate both sides for effects, drop
                    # the store (same as MemberExpr load reading 0).
                    self._emit_expr(stmt.target.obj)
                    self._emit_expr(stmt.value)
                    return
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
            self._check_comptime_target(name, "assignment")
            self._emit_expr(stmt.value)
            self._store_var(name, 0)
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
                self._store_var(name, 0)
            return

        if isinstance(stmt, F.VarDecl):
            # Declaration: register is allocated by _collect_var_names; only
            # emit an initializer when one was given.
            # Same as AssignStmt: ann is metadata; value emission gates.
            if stmt.value is not None:
                self._emit_expr(stmt.value)
                self._store_var(stmt.name, 0)
                self._note_binding(stmt.name, stmt.value)
            return

        if isinstance(stmt, F.TryStmt):
            self._emit_try(stmt)
            return

        if isinstance(stmt, F.WithStmt):
            self._emit_with(stmt)
            return

        if isinstance(stmt, F.DelStmt):
            self._emit_del(stmt)
            return

        if isinstance(stmt, F.FunctionDef):
            raise CodegenError("nested function definitions are not "
                               "supported on the formal arm64 path")

        if isinstance(stmt, F.ComptimeVarStmt):
            # `comptime NAME = <const>`: fold and record, emit nothing.
            # Same rule as the gimple path's _gen_stmt_ComptimeVarStmt —
            # a comptime binding is compile-time state, so it produces no
            # instructions and no storage.
            self._bind_comptime(stmt)
            return

        if isinstance(stmt, F.ComptimeIfStmt):
            # Which branch is taken is a language decision, shared
            # (comptime_eval.resolve_if); 'runtime' here just means the
            # condition did not fold, and the arm64 half then emits the
            # ordinary runtime branch — the same degradation the gimple path
            # makes, so both agree on the observable behaviour.
            which = comptime_eval.resolve_if(stmt, self._comptime_vals,
                                             call_hook=self._comptime_hook)
            if which == "then":
                for s in stmt.then_body:
                    self._emit_stmt(s)
                return
            if which == "else":
                for s in (stmt.else_body or []):
                    self._emit_stmt(s)
                return
            if isinstance(which, tuple) and which[0] == "elif":
                for s in (stmt.elifs[which[1]][1]):
                    self._emit_stmt(s)
                return
            self._emit_stmt(F.IfStmt(condition=stmt.condition,
                                     then_body=stmt.then_body,
                                     elifs=getattr(stmt, "elifs", None),
                                     else_body=stmt.else_body,
                                     line=stmt.line, col=stmt.col))
            return

        if isinstance(stmt, F.ComptimeForStmt):
            # Folded when the iterable is a compile-time-known sequence (the
            # `comptime for i in range(0, 8)` idiom), else emitted as the
            # ordinary runtime loop.
            vals = self._comptime_iterable(stmt.iterable)
            if vals is None:
                self._emit_stmt(F.ForStmt(target=stmt.target,
                                          iterable=stmt.iterable,
                                          body=stmt.body,
                                          line=stmt.line, col=stmt.col))
                return
            for v in vals:
                self._emit_comptime_target(stmt.target, v)
                for s in stmt.body:
                    self._emit_stmt(s)
            return

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
        # async with lowers as a plain with (no event loop / context-manager
        # protocol on this path — same as the non-async with above).
        for it in stmt.items or []:
            self._emit_expr(it.expr)
            if it.alias is not None:
                alias = _with_item_alias_name(it.alias)
                self._store_var(alias, 0)
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

        def _tup_slot(el):
            if isinstance(el, F.IdentExpr):
                return el.name
            if isinstance(el, F.MemberExpr):
                key = _member_slot_key(el)
                if key is not None:
                    return key
                # Non-named base: evaluate for effects, store nowhere.
                return None
            if isinstance(el, F.TupleExpr):
                # Nested target `(a, b), c = rhs` — handled by the
                # recursive unpack below; this slot is a nested group.
                return ("nested", el)
            if isinstance(el, F.SubscriptExpr):
                # `a[i], b = rhs` — an element target keeps its own
                # bounds-checked store, the same one `a[i] = v` uses, so a
                # tuple unpack and a single store agree on what an
                # out-of-range index does (both exit(1)).
                return ("sub", el)
            raise CodegenError(
                "tuple assignment target elements must be plain names "
                f"(got {type(el).__name__})")

        slots = [_tup_slot(el) for el in target.elements]
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
                sl = slots[i]
                if sl is None:
                    continue
                self._store_tup_slot(sl, 0)
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
            sl = slots[i]
            if sl is None:
                continue
            self._store_tup_slot(sl, 0)

    def _store_tup_slot(self, slot, reg: int) -> None:
        """Store the unpacked value in X{reg} into one target slot.

        One dispatcher for both unpack paths (literal tuple RHS and blob
        RHS) and all three slot shapes, so a target kind can never be handled
        in one path and missed in the other."""
        if slot is None:
            return
        if isinstance(slot, tuple):
            if slot[0] == "nested":
                self._emit_tuple_assign_nested(slot[1], reg)
            else:
                self._emit_subscript_store_reg(slot[1], reg)
            return
        self._store_var(slot, reg)

    def _emit_tuple_assign_nested(self, elements, reg: int) -> None:
        """Unpack a nested tuple-target group against a blob pointer.

        `elements` is a TupleExpr/ListExpr target node (or a plain list).
        `reg` holds the nested blob pointer `[count][e0…]`. Compile-only:
        the outer unpack already validated top-level arity."""
        if isinstance(elements, (F.TupleExpr, F.ListExpr)):
            els = list(elements.elements)
        else:
            els = list(elements)
        self.asm.emit(encode_mov_zr_xn(9, reg))
        for i, el in enumerate(els):
            self.asm.emit(encode_ldr_xt_xn_imm(0, 9, 8 * (i + 1)))
            if isinstance(el, F.IdentExpr):
                self._store_var(el.name, 0)
            elif isinstance(el, F.MemberExpr):
                key = _member_slot_key(el)
                if key is not None:
                    self._store_var(key, 0)
            elif isinstance(el, (F.TupleExpr, F.ListExpr)):
                # Nested-nested: X0 is a pointer to a further blob.
                self._emit_tuple_assign_nested(el, 0)
            # else: leave value in X0 (dropped)

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
            self._record_cond_branch()
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
            start_val, end_val, step_val = self._range_info(rargs)
            self._emit_expr(start_val)
            self._store_var(target, 0)

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
            self._record_cond_branch()
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
            # Any expression that materializes a list/set/tuple blob (or a
            # string/byte view) is a legal iterable — `_emit_expr` under
            # container ctx produces the pointer `_emit_for_list` walks.
            # Previously a narrow allowlist rejected TernaryExpr /
            # MemberExpr / CallExpr shapes that lower fine.
            iter_ok = isinstance(it, (
                F.IdentExpr, F.ListExpr, F.TupleExpr, F.SetExpr,
                F.DictExpr, F.StringLiteral, F.SubscriptExpr, F.SliceExpr,
                F.Comprehension, F.MemberExpr, F.TernaryExpr, F.UnaryOp,
                F.CallExpr, F.BinaryOp, F.AwaitExpr, F.WalrusExpr))
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

            fi_name, fb_name = f"_fi{d}", f"_fb{d}"
            fi_reg = self._var_regs.get(fi_name)
            fb_reg = self._var_regs.get(fb_name)

            # Materialize the iterable once (also correct for `for x in x`).
            # Container ctx makes BinaryOp `+`/`|` lower as list/set ops.
            self._container_ctx += 1
            try:
                self._emit_expr(stmt.iterable)
            finally:
                self._container_ctx -= 1
            self._store_var(fb_name, 0)
            self.asm.emit(encode_movz_xd_imm(0, 0))
            self._store_var(fi_name, 0)

            self._loops.append({"start": start_label, "step": step_label,
                                "break": end_label,
                                "fin_depth": len(self._pending_finally)})
            try:
                self.asm.label(start_label)
                self._load_var(fb_name, 9)
                self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))
                if fi_reg is not None:
                    self.asm.emit(encode_cmp_xn_xm(fi_reg, 1))
                else:
                    self._load_var(fi_name, 0)
                    self.asm.emit(encode_cmp_xn_xm(0, 1))
                self.asm.emit(encode_cset_xd_cond(0, "lt"))
                self.asm.emit(encode_cbz_xn(0, 0))
                self.asm.emit_label_rel(false_label, here_offset=-4)

                self.asm.emit(encode_add_xd_xn_imm(2, 9, 8))
                if fi_reg is not None:
                    self.asm.emit(encode_add_xd_xn_xm_lsl3(2, 2, fi_reg))
                else:
                    self._load_var(fi_name, 0)
                    self.asm.emit(encode_add_xd_xn_xm_lsl3(2, 2, 0))
                self.asm.emit(encode_ldr_xt_xn_imm(0, 2, 0))

                if is_tuple_target:
                    # X0 = element (pointer to [count][e0…] blob).
                    # Nested groups are themselves blobs — recurse.
                    self._emit_for_unpack(ttree, f"{fn}_flt{wid}")
                else:
                    self._store_var(tnames[0], 0)

                for s in stmt.body:
                    self._emit_stmt(s)

                self.asm.label(step_label)
                if fi_reg is not None:
                    self.asm.emit(encode_add_xd_xn_imm(fi_reg, fi_reg, 1))
                else:
                    self._load_var(fi_name, 0)
                    self.asm.emit(encode_add_xd_xn_imm(0, 0, 1))
                    self._store_var(fi_name, 0)
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

        `tree` is a leaf name (`str`), `'*name'` (trailing star), or a list
        of children (tuple target). Leaf: move X0 into the name's register.
        Star leaf: X0 is a blob; build a rest blob of the tail and store its
        base under `name` (only legal as the last element of a tuple). List:
        X0 must be a blob `[count][e0…]` with count == len(children) (or
        >= n_fixed when a trailing star is present); each child recurses
        with its element in X0. Arity mismatch → exit(1)."""
        if isinstance(tree, str):
            if tree.startswith("*"):
                self._store_var(tree[1:], 0)
                return
            self._store_var(tree, 0)
            return
        n_t = len(tree)
        star_i = -1
        for i, child in enumerate(tree):
            if isinstance(child, str) and child.startswith("*"):
                if i != n_t - 1:
                    raise CodegenError(
                        f"starred for-target {child!r} must be last")
                star_i = i
        n_fixed = n_t - (1 if star_i >= 0 else 0)
        self.asm.emit(encode_mov_zr_xn(9, 0))          # X9 = blob base
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))   # X1 = count
        if star_i >= 0:
            # Need count >= n_fixed. cmp X1, #n_fixed → lt means count short.
            self.asm.emit(encode_cmp_xn_imm(1, n_fixed))
        else:
            self.asm.emit(encode_sub_xd_xn_imm(2, 1, n_t))  # count - n_t
            self.asm.emit(encode_mov_zr_xn(1, 2))           # reuse for test
            self.asm.emit(encode_cmp_xn_imm(1, 0))
        self._tup_counter += 1
        tid = self._tup_counter
        fail_label = f"{tag}_bad{tid}"
        ok_label = f"{tag}_ok{tid}"
        if star_i >= 0:
            self.asm.emit(encode_cset_xd_cond(2, "lt"))
            self.asm.emit(encode_cbnz_xn(0, 2))
        else:
            self.asm.emit(encode_cbnz_xn(0, 1))
        self.asm.emit_label_rel(fail_label, here_offset=-4)
        self._emit_b_to(ok_label)
        self.asm.label(fail_label)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok_label)
        # Keep src base and n_fixed across fixed-child unpack (X9/X1 are
        # clobbered by nested _emit_for_unpack). Push [n_fixed, src_base]:
        # stp_pre(X6, X9) → [SP+0]=n_fixed, [SP+16]=src_base after adjust?
        # stp pre-index: SP -= 16; [SP]=X6; [SP+8]=X9. So [0]=n_fixed,
        # [8]=src. Star helper expects [0]=n_fixed, [16]=src — mismatch.
        # Push as [0]=n_fixed, [8]=src and read src from [8].
        if star_i >= 0:
            self._emit_mov_imm("X6", n_fixed)
            self.asm.emit(encode_stp_sp_pre(6, 9))
        for i, child in enumerate(tree):
            if isinstance(child, str) and child.startswith("*"):
                self._emit_for_unpack_star_rest(child[1:], tag)
                continue
            self.asm.emit(encode_ldr_xt_xn_imm(0, 9, 8 * (i + 1)))
            self._emit_for_unpack(child, tag)

    def _emit_for_unpack_star_rest(self, name: str, tag: str) -> None:
        """Build rest blob under `name` from [src_base, n_fixed] on stack.

        Stack layout on entry (stp_pre X6=n_fixed, X9=src): [SP+0]=n_fixed,
        [SP+8]=src_base. Rest = source elements [n_fixed, count). Cap 64;
        overflow → exit(1). Pops both slots."""
        rest_cap = 64
        nbytes = 8 + 8 * rest_cap
        if self._list_cursor + nbytes > self._blob_cap:
            raise CodegenError(
                f"for-star rest exceeds the formal frame "
                f"({self._list_cursor + nbytes} > {self._blob_cap} bytes)")
        offset = self._list_cursor
        self._list_cursor += nbytes

        self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 0))   # X6 = n_fixed
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 8))   # X5 = src base
        self.asm.emit(encode_ldr_xt_xn_imm(3, 5, 0))    # X3 = count
        self.asm.emit(encode_sub_xd_xn_imm(3, 3, 6))    # rest_count
        self.asm.emit(encode_movz_xd_imm(4, 0))         # i = 0

        self._while_counter += 1
        loop = f"{tag}_sl{self._while_counter}"
        done = f"{tag}_sd{self._while_counter}"
        oob = f"{tag}_so{self._while_counter}"
        oob_end = f"{tag}_sx{self._while_counter}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_xm(4, 3))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(done, here_offset=-4)
        self.asm.emit(encode_cmp_xn_imm(4, rest_cap))
        self.asm.emit(encode_cset_xd_cond(0, "cs"))
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(oob, here_offset=-4)
        # elem = src + 8 + 8*(n_fixed + i)
        self.asm.emit(encode_add_xd_xn_xm(7, 6, 4))
        self.asm.emit(encode_add_xd_xn_imm(0, 5, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 7))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))
        self._emit_list_base(offset)
        self.asm.emit(encode_add_xd_xn_imm(7, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(7, 7, 4))
        self.asm.emit(encode_str_xt_xn_imm(0, 7, 0))
        self.asm.emit(encode_add_xd_xn_imm(4, 4, 1))
        self._emit_b_to(loop)
        self.asm.label(done)
        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(1, 3))           # rest_count
        self.asm.emit(encode_str_xt_xn_imm(1, 9, 0))
        self.asm.emit(encode_mov_zr_xn(0, 9))
        self._store_var(name, 0)
        self.asm.emit(encode_ldp_sp_post(0, 31))        # pop [n_fixed, src]
        self._emit_b_to(oob_end)
        self.asm.label(oob)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(oob_end)

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
        # RMW on the counter: register home edits in place; spill home
        # loads to X11, operates, stores back (X12 holds a spilled step
        # operand when one is needed).
        if target in self._var_regs:
            self._for_inc_in(target, step)
            return
        self._load_var(target, 11)
        self._for_inc_scratch(step, 11)
        self._store_var(target, 11)

    def _for_inc_in(self, target: str, step) -> None:
        ireg = self._var_regs[target]
        self._for_inc_body(ireg, step)

    def _for_inc_body(self, ireg: int, step) -> None:
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
            sreg = self._var_reg_or_scratch(step.operand.name, 12)
            self.asm.emit(encode_sub_xd_xn_xm(ireg, ireg, sreg))
            return
        if isinstance(step, F.IdentExpr):
            sreg = self._var_reg_or_scratch(step.name, 12)
            self.asm.emit(encode_add_xd_xn_xm(ireg, ireg, sreg))
            return
        if isinstance(step, F.BinaryOp) and step.op == "+" \
                and isinstance(step.left, F.IdentExpr):
            k = step.right
            if isinstance(k, F.IntLiteral) and k.value >= 0:
                sreg = self._var_reg_or_scratch(step.left.name, 12)
                self.asm.emit(encode_add_xd_xn_xm(ireg, ireg, sreg))
                self.asm.emit(encode_add_xd_xn_imm(ireg, ireg, k.value))
                return
        raise CodegenError("for-loop step must be a literal or a variable")

    def _for_inc_scratch(self, step, dst: int) -> None:
        """Same as _for_inc_body but counter lives in `dst` (already loaded)."""
        self._for_inc_body(dst, step)

    # ── Expressions (result in X0) ─────────────────────────────────

    def _emit_expr(self, expr) -> None:
        if isinstance(expr, F.IntLiteral):
            self._emit_mov_imm("X0", expr.value)
            return

        if isinstance(expr, F.IdentExpr):
            # A `comptime NAME = ...` binding is a compile-time constant, not
            # a local: no register or slot was ever assigned to it, so the
            # ordinary `_load_var` below would read whatever happens to be in
            # a register. Materialize the folded value instead — which is also
            # what makes the constant "dead-end" in a load-immediate, the same
            # place the gimple path's bare `(int64_t)N` literal dead-ends in
            # gcc. Consulted for EVERY expression context, not just other
            # comptime ones, for the reason mojo/middle/comptime.py gives.
            if expr.name in self._comptime_vals:
                self._emit_comptime_read(expr.name)
                return
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
            self._load_var(expr.name, 0)
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
            if M.is_ownership_transfer(expr):
                # `x^` — see formal/model.py: a compile-time-only marker, so
                # the value flows straight through on every formal path.
                self._emit_expr(expr.operand)
                return
            raise CodegenError(
                f"unsupported unary operator {expr.op!r} on the formal "
                f"arm64 path")

        if isinstance(expr, F.BinaryOp):
            self._emit_binop(expr)
            return

        if isinstance(expr, F.CompareChain):
            self._emit_compare_chain(expr)
            return

        if isinstance(expr, F.Comprehension):
            self._emit_comprehension(expr)
            return

        if isinstance(expr, F.SliceExpr):
            self._emit_slice(expr)
            return

        if isinstance(expr, F.FloatLiteral):
            # formal is int-only; truncate toward zero (matches C cast).
            self._emit_mov_imm("X0", int(expr.value))
            return

        if isinstance(expr, F.SetExpr):
            # Formal has no set runtime — lower as a list blob (membership
            # / iteration are the only uses seen on this path).
            self._emit_list(expr)
            return

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
            self._record_cond_branch()
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
                self._load_var(key, 0)
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

        if isinstance(expr, F.AwaitExpr):
            # No event loop: await e ≡ e.
            self._emit_expr(expr.value)
            return

        if isinstance(expr, F.YieldExpr):
            # Generator lowered as a plain function: yield e leaves e in X0
            # (the "send" result is not modeled — compile-only).
            if expr.value is not None:
                self._emit_expr(expr.value)
            else:
                self.asm.emit(encode_movz_xd_imm(0, 0))
            return

        if isinstance(expr, F.WalrusExpr):
            self._emit_expr(expr.value)
            self._store_var(expr.name, 0)
            self._note_binding(expr.name, expr.value)
            return

        if isinstance(expr, F.LambdaExpr):
            # Lifted by build._lift_lambdas for call/assign sites; a
            # residual bare lambda (argument position) materializes as the
            # address of its lifted symbol when registered, else 0.
            lam_name = getattr(expr, "_lifted_name", None)
            if lam_name and lam_name in self._functions:
                self.asm.emit_adrp_add(0, lam_name)
                return
            self.asm.emit(encode_movz_xd_imm(0, 0))
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
        if isinstance(value, F.DictExpr) or (
                isinstance(value, F.Comprehension) and value.kind == "dict"):
            self._dict_vars.add(name)
            self._string_vars.discard(name)
        elif isinstance(value, F.SetExpr) or (
                isinstance(value, F.Comprehension)
                and value.kind in ("set", "list", "generator")):
            self._string_vars.discard(name)
            self._dict_vars.discard(name)
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
            # `obj[start:stop:step]` parses as SliceExpr with .obj attached;
            # a nested `base[sl]` form puts SliceExpr in .index.
            sl = e.index
            self._emit_slice_parts(e.obj, sl.start, sl.stop, sl.step)
            return
        if isinstance(e.index, F.TupleExpr):
            # `d[(a, b)]` is a dict lookup with a tuple key, compared
            # element-wise — it does not need the base to be a *known* dict,
            # because in Python a tuple index is a dict key or a TypeError,
            # never a list multi-index (which this path has no representation
            # for anyway). A computed tuple index keeps the old error: there
            # the base really could be a numpy-style multi-index.
            if self._static_key_needle(e.index) is None:
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
        # Static pairs only: `**other` / `*xs` are evaluated for side
        # effects then skipped (fixed pair-blob, no dynamic growth).
        static_pairs = []
        splat_exprs = []
        for k, v in expr.pairs:
            if isinstance(k, F.UnaryOp) and k.op in ("**", "*"):
                splat_exprs.append(k.operand)
                if v is not None:
                    splat_exprs.append(v)
                continue
            if v is None:
                # Parser marks ** with value None — operand already in k.
                splat_exprs.append(k)
                continue
            static_pairs.append((k, v))
        n = len(static_pairs)
        size = 8 * (1 + 2 * n)
        if self._list_cursor + size > self._blob_cap:
            raise CodegenError(
                f"dict literal exceeds the formal frame "
                f"({self._list_cursor + size} > {self._blob_cap} bytes)")
        offset = self._list_cursor
        self._list_cursor += size

        # Materialize splats first (may clobber X9/X0) so static stores
        # below run with a clean base recompute per store.
        for se in splat_exprs:
            self._emit_expr(se)

        self._emit_list_base(offset)
        self._emit_mov_imm("X10", n)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
        pair_i = 0
        for k, v in static_pairs:
            self._emit_expr(k)
            self._emit_list_base(offset)
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * (1 + 2 * pair_i)))
            self._emit_expr(v)
            self._emit_list_base(offset)
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * (2 + 2 * pair_i)))
            pair_i += 1
        if n == 0:
            self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _static_key_needle(self, e):
        """Element expressions of a statically-known container key, or None.

        The rule (and why a raw 64-bit compare is not value equality for a
        tuple key) is formal/model.py's, shared with the x86-64 path so both
        architectures agree on what "equal key" means."""
        return M.static_key_elements(e)

    def _emit_key_const(self, e, reg: int) -> None:
        """X{reg} = the canonical 64-bit value of a literal key element."""
        if isinstance(e, F.StringLiteral):
            self._emit_string_addr(reg, self._intern_string(e.value))
            return
        if isinstance(e, F.BoolLiteral):
            self._emit_mov_imm(f"X{reg}", 1 if e.value else 0)
            return
        self._emit_mov_imm(f"X{reg}", e.value)

    def _emit_key_eq(self, needle, cand: int, ok: int) -> None:
        """X{ok} = 1 iff the blob pointer in X{cand} is equal to `needle`.

        Element-wise for a static container key (count first, then each
        element against the element's own canonical value), raw 64-bit
        equality otherwise. Clobbers X10-X13 and `ok` only; every caller
        keeps its own live state in X0-X9.
        """
        elems = self._static_key_needle(needle)
        self.asm.emit(encode_movz_xd_imm(ok, 1))
        if elems is None:
            self._emit_key_const(needle, 11)
            self.asm.emit(encode_cmp_xn_xm(cand, 11))
            self.asm.emit(encode_cset_xd_cond(ok, "eq"))
            return
        # The blob header is the element count, so a length mismatch is the
        # cheapest rejection and needs no element compare at all.
        self.asm.emit(encode_ldr_xt_xn_imm(11, cand, 0))
        self._emit_mov_imm("X12", len(elems))
        self.asm.emit(encode_cmp_xn_xm(11, 12))
        self.asm.emit(encode_cset_xd_cond(13, "eq"))
        self.asm.emit(encode_and_xd_xn_xm(ok, ok, 13))
        for j, el in enumerate(elems):
            off = M.element_offset(j)
            if off <= 0xfff:
                self.asm.emit(encode_add_xd_xn_imm(11, cand, off))
            else:
                self._emit_mov_imm("X12", off)
                self.asm.emit(encode_add_xd_xn_xm(11, cand, 12))
            self.asm.emit(encode_ldr_xt_xn_imm(11, 11, 0))
            self._emit_key_const(el, 12)
            self.asm.emit(encode_cmp_xn_xm(11, 12))
            self.asm.emit(encode_cset_xd_cond(13, "eq"))
            self.asm.emit(encode_and_xd_xn_xm(ok, ok, 13))

    def _emit_dict_lookup_addr(self, e: F.SubscriptExpr) -> None:
        """X0 = &dict[key] value slot. Missing key → Darwin exit(1).

        Pair-blob layout: [count][k0][v0]…; value i is at base+16+16*i.
        Key compare is raw 64-bit equality — valid for interned string
        literals and integer keys (the formal dict surface) — except for a
        static container key, which is compared element-wise (see
        `_static_key_needle`): a tuple key's blob pointer is not a value.

        Stack on entry to the scan (two STP pushes, or one when the key is
        compared element-wise and never needs a slot):
          [SP+0]  key (lookup), [SP+8] XZR
          [SP+16] base,        [SP+24] junk
        Hit path stashes the value address in X4 across the pops."""
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
        key_pushed = self._static_key_needle(e.index) is None
        if key_pushed:
            self._emit_expr_to(e.index, "X1")           # X1 = key
            self.asm.emit(encode_stp_sp_pre(1, 31))     # push key
        base_off = 16 if key_pushed else 0
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, base_off))  # X9 = base
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
        if key_pushed:
            self.asm.emit(encode_ldr_xt_xn_imm(7, 31, 0))   # X7 = lookup key
            self.asm.emit(encode_cmp_xn_xm(6, 7))
            self.asm.emit(encode_cset_xd_cond(8, "eq"))
        else:
            self._emit_key_eq(e.index, 6, 8)
        self.asm.emit(encode_cbnz_xn(0, 8))
        self.asm.emit_label_rel(hit_label, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(3, 3, 1))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(loop_label, here_offset=-4)

        def _pop_scan():
            if key_pushed:
                self.asm.emit(encode_ldp_sp_post(0, 31))    # pop key
            self.asm.emit(encode_ldp_sp_post(0, 31))        # pop base

        self.asm.label(hit_label)
        self.asm.emit(encode_add_xd_xn_imm(4, 5, 8))    # X4 = value slot
        _pop_scan()
        self.asm.emit(encode_mov_zr_xn(0, 4))
        self._emit_b_to(end_label)

        self.asm.label(miss_label)
        _pop_scan()
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(end_label)

    def _is_dict_key_subscript(self, e: F.SubscriptExpr) -> bool:
        """True when this subscript is a dict lookup, key compare included.

        A known dict base is one way; a static container key is the other,
        since a tuple index on a list is not a Python operation at all."""
        return (self._is_dict_subscript(e.obj)
                or self._static_key_needle(e.index) is not None)

    def _emit_subscript_addr(self, e: F.SubscriptExpr) -> None:
        """X0 = &obj[index]. Blob path bounds-checks (exit 1 on OOB)."""
        if self._is_dict_key_subscript(e):
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
        self._emit_expr(value)                  # X0 = value
        self._emit_subscript_store_reg(target, 0)

    def _emit_subscript_store_reg(self, target: F.SubscriptExpr,
                                  reg: int) -> None:
        """Store the value already in X{reg} into `target[index]`.

        Split from `_emit_subscript_store` so a caller that already HAS the
        value in a register — a tuple unpack popping its elements — does not
        have to invent an AST node to carry it. The address is computed once
        and survives the store, exactly as in the statement form."""
        self._emit_subscript_addr(target)
        self.asm.emit(encode_stp_sp_pre(0, 2))  # save addr
        self.asm.emit(encode_mov_zr_xn(9, 0))   # X9 = addr
        if self._is_string_subscript(target.obj):
            self.asm.emit(encode_strb_wd_wn(reg, 9, 0))
        else:
            self.asm.emit(encode_str_xt_xn_imm(reg, 9, 0))
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
        want_shift = op in ("<<", ">>")
        if op not in ops and not want_shift:
            raise CodegenError(
                f"unsupported augmented operator {stmt.op!r} "
                f"(formal arm64 path supports + - * & | ^ << >>)")
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
        if want_shift:
            self._emit_shift_reg(op, signed=cmp_signed(
                self._ttype(target)))
        else:
            self.asm.emit(ops[op](0, 0, 1))       # X0 = old op value
        # addr is at [SP+16] after the two pushes.
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 16))
        if is_str:
            self.asm.emit(encode_strb_wd_wn(0, 9, 0))
        else:
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))

    def _emit_len(self, e: F.CallExpr) -> None:
        """`len(x)` — the count field of a list/tuple blob.

        A builtin, and it has to be intercepted here for the same reason
        `range` is: nothing else on this path knows the name. Left to the
        extern path it became a BL against a symbol `len` that libSystem does
        not define, so the image built and then aborted in the loader with
        "Symbol not found: _len" (or, where a `len` happened to exist, called
        it and returned whatever was in the result register).

        The blob is `[count:i64][elem0]...` (see _emit_list) and a list value
        IS its address, so this is one load from offset 0 — no traversal.

        A STRING is refused rather than guessed at. A string here is a bare
        `char *` with no length prefix, so there is nothing at offset 0 to
        read; returning the pointer's low bits, or the address itself, would
        be a plausible-looking wrong answer."""
        args = list(e.args)
        if len(args) != 1 or e.kwargs:
            raise CodegenError(
                f"len() takes exactly one argument on this path "
                f"(got {len(args) + len(e.kwargs)})")
        operand = args[0]
        if isinstance(operand, F.StringLiteral) or (
                isinstance(operand, F.CallExpr)
                and _callee_symbol(operand.func) in M.IDENTITY_TYPE_CTORS):
            raise CodegenError(
                f"len() of a string is not lowered on this path: a string is "
                f"a bare char * with no length prefix, so its length cannot be "
                f"read (len of a list or tuple is the blob's count field and "
                f"is supported)")
        self._emit_expr(operand)
        # X0 holds the blob address; the count is its first 8 bytes.
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))

    def _emit_list_base(self, offset: int) -> None:
        """X9 = address of the list blob at frame_bottom + offset.

        Frame geometry after the prologue (SP grows down):
          [X29+8]  saved LR
          [X29]    saved FP          <- X29
          [X29-16] saved X19,X20
          ...
          [X29-16*npairs-SCRATCH, X29-16*npairs)  scratch:
            high end = spill slots (8*nspill, if any); low end = list/dict
            blobs (grows up from frame bottom, capped at _blob_cap)
        The body only pushes BELOW SP (stp_sp_pre), so this region stays
        free for list blobs. Addressing is X29-relative because SP moves
        during expression evaluation. Exits with base in X9."""
        self.asm.emit(encode_mov_zr_xn(9, 29))
        _emit_sub_imm(self.asm, 9, 9, _SCRATCH)
        saved = 16 * self._npairs
        if saved:
            self.asm.emit(encode_sub_xd_xn_imm(9, 9, saved))
        if offset:
            _emit_add_imm(self.asm, 9, 9, offset)

    def _emit_list(self, expr: F.ListExpr) -> None:
        """Stack-allocate a list blob: [count:i64][elem0]...[elemN-1].

        X0 exits holding the blob address (pointer-sized, no heap). Elements
        are int64s or string/inner-list pointers. Cursor reserves the full
        blob before any element is evaluated so nested lists sit above it.
        Exits without moving SP — the blob lives until the function returns.
        Star-unpack elements have no compile-time length and raise."""
        has_star = any(isinstance(el, F.UnaryOp) and el.op == "*"
                       for el in expr.elements)
        if has_star:
            self._emit_list_star(expr)
            return
        n = len(expr.elements)
        size = 8 * (1 + n)
        if self._list_cursor + size > self._blob_cap:
            raise CodegenError(
                f"list literals exceed the formal frame "
                f"({self._list_cursor + size} > {self._blob_cap} bytes)")
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

        # List/set concat under container context (for-iterable, membership
        # RHS) or when either side is a container literal / producer.
        if op in ("+", "|") and (
                self._container_ctx > 0
                or self._is_container_expr(e.left)
                or self._is_container_expr(e.right)):
            if op == "+":
                self._emit_list_concat(e.left, e.right)
            else:
                self._emit_set_union(e.left, e.right)
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

        if op in ("/", "//", "%", "<<", ">>", "**"):
            self._emit_div_shift_pow(e, op)
            return

        raise CodegenError(
            f"unsupported binary operator {op!r} on the formal arm64 path")

    def _record_cond_branch(self) -> None:
        """Note that the next emitted instruction is an `if`'s own CBZ.

        Call immediately before emitting that CBZ.  The assembler's cursor
        `_org + len(text)` is the address the next 4 bytes land at, which is
        the branch's own PC, and `_org` is the absolute load address, so the
        recorded value is directly comparable with the proof generator's
        `pc -> word` map.
        """
        self._cond_branch_pcs.append(
            self.asm._org + len(self.asm.sections["text"]))

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
        String RHS is a byte/substring scan; a dict RHS is a *pair* blob
        `[count][k0][v0]…`, so it is scanned over its KEYS at stride 16 — a
        stride-8 scan of a pair blob walks keys and values alternately and
        stops at the pair count, i.e. it can only ever see the first half of
        the dict. BinaryOp RHS (`or`/`and`/`+`/`|`) is allowed — evaluated
        under container ctx so `+`/`|` lower as list/set ops."""
        if isinstance(right, F.StringLiteral):
            self._emit_str_membership(left, right, invert=invert)
            return
        if type(right) not in (F.IdentExpr, F.CallExpr, F.ListExpr,
                               F.TupleExpr, F.MemberExpr, F.SubscriptExpr,
                               F.SliceExpr, F.Comprehension, F.SetExpr,
                               F.BinaryOp):
            raise CodegenError(
                "`in`/`not in` RHS must be a list/tuple name or literal on "
                f"the formal arm64 path (got {type(right).__name__})")

        is_dict = self._is_dict_subscript(right)
        key_pushed = self._static_key_needle(left) is None
        self._if_counter += 1
        mid = self._if_counter
        fn = self.func_name
        loop_label = f"{fn}_in{mid}_loop"
        notfound_label = f"{fn}_in{mid}_nf"
        found_label = f"{fn}_in{mid}_hit"
        end_label = f"{fn}_in{mid}_end"

        # needle (left) on the stack so element loads can clobber X0/X1.
        # Slot stays pushed for the whole scan; each exit pops it, then
        # overwrites X0 with the boolean result. A static container needle is
        # compared element-wise and never needs a slot, so nothing is pushed.
        if key_pushed:
            self._emit_expr(left)
            self.asm.emit(encode_stp_sp_pre(0, 2))
        # haystack blob → X9; count → X2; index → X3 (scratch, no calls).
        self._container_ctx += 1
        try:
            self._emit_expr_to(right, "X1")
        finally:
            self._container_ctx -= 1
        self.asm.emit(encode_mov_zr_xn(9, 1))
        self.asm.emit(encode_ldr_xt_xn_imm(2, 9, 0))
        self.asm.emit(encode_movz_xd_imm(3, 0))

        self.asm.label(loop_label)
        self.asm.emit(encode_cmp_xn_xm(3, 2))
        self.asm.emit(encode_cset_xd_cond(4, "ge"))  # 1 when i >= count
        self.asm.emit(encode_cbnz_xn(0, 4))
        self.asm.emit_label_rel(notfound_label, here_offset=-4)

        self.asm.emit(encode_add_xd_xn_imm(5, 9, M.BLOB_HEADER_BYTES))
        # A dict is a pair blob, so membership walks KEYS at the pair stride
        # (formal/model.membership_stride) — at the element stride it would
        # walk keys and values alternately and stop at the pair count.
        self.asm.emit(encode_add_xd_xn_xm_lsl4(5, 5, 3) if is_dict
                      else encode_add_xd_xn_xm_lsl3(5, 5, 3))
        self.asm.emit(encode_ldr_xt_xn_imm(5, 5, 0))  # elem / key
        if key_pushed:
            self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 0))  # needle from [SP]
            self.asm.emit(encode_cmp_xn_xm(5, 6))
            self.asm.emit(encode_cset_xd_cond(7, "eq"))
        else:
            self._emit_key_eq(left, 5, 7)
        self.asm.emit(encode_cbnz_xn(0, 7))
        self.asm.emit_label_rel(found_label, here_offset=-4)

        self.asm.emit(encode_add_xd_xn_imm(3, 3, 1))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(loop_label, here_offset=-4)

        def _pop_needle():
            if key_pushed:
                self.asm.emit(encode_ldp_sp_post(0, 1))

        self.asm.label(notfound_label)
        _pop_needle()
        self.asm.emit(encode_movz_xd_imm(0, 1 if invert else 0))
        self._emit_b_to(end_label)

        self.asm.label(found_label)
        _pop_needle()
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

    def _emit_type_constructor(self, e: F.CallExpr, name: str,
                               tkind: tuple) -> None:
        """`Int(x)` / `String(s)` — a conversion, not a call.

        On the formal paths a value is a 64-bit word and a string is already a
        `char *`, so an integer construction is a width/sign normalization of
        the operand and a string construction is the identity. Both take
        exactly one operand, as in the language; anything else is a shape error
        rather than a guess."""
        kind, info = tkind
        if kind == "unsupported":
            raise CodegenError(
                f"constructing {name} has no representation on this path "
                f"(a formal value is one 64-bit word, and {name} is not one "
                f"thing) — previously this emitted a call to a symbol named "
                f"{name!r} that nothing defines")
        # A keyword argument names the same single value a positional one
        # does, so it is accepted as the operand rather than rejected:
        # `String(unsafe_from_utf8_ptr=p.value())` is how std/os/env.mojo
        # builds a string from a raw pointer, and refusing every keyword form
        # blocked 78 stdlib files on a shape the language allows. What is
        # still refused is a genuine mismatch of ARITY — a conversion has one
        # operand, and two of them (positioned or named) is not a conversion.
        operands = list(e.args) + [v for _n, v in e.kwargs]
        if len(operands) != 1:
            raise CodegenError(
                f"{name}(...) takes exactly one value to convert on this path "
                f"(got {len(operands)} argument(s))")
        self._emit_expr(operands[0])
        if kind == "identity":
            return
        width, signed = info
        self._emit_extend(0, 0, IntType(width, signed))

    def _emit_struct_constructor(self, e: F.CallExpr, name: str,
                                 st: F.StructDef) -> None:
        """`S()` — default-initialize a struct, not a call.

        Mojo has no user-defined constructor: `S()` brings every field up at
        its default and the fields are then assigned. On this path a value is
        one 64-bit word, so that is exactly what a struct of zero or one field
        IS — the word itself, zero for a fresh one. Both shapes therefore need
        no call at all, and emitting one was the bug: it produced a BL against
        a symbol named after the type, so the library built and then could not
        be loaded ("Symbol not found: _Counter").

        Wider structs have no representation here and are refused by name and
        width. They used to reach the extern path and produce that same
        unloadable image, so the honest limit has to be stated where the
        decision is made rather than discovered by dyld.
        """
        fields = list(getattr(st, "fields", None) or [])
        if len(fields) > 1:
            raise CodegenError(
                f"constructing {name} needs {len(fields)} words, and a formal "
                f"value is one word — a multi-field struct has no "
                f"representation on this path (previously this emitted a call "
                f"to a symbol named {name!r} that nothing defines, so the "
                f"image built and then failed to load)")
        if e.args or e.kwargs:
            # Positional/keyword construction is not Mojo's struct syntax, and
            # silently ignoring a supplied value would lose data.
            raise CodegenError(
                f"{name}(...) takes no arguments on this path: a struct is "
                f"default-initialized and its fields assigned, and a "
                f"{len(e.args) + len(e.kwargs)}-argument construction is not a "
                f"shape this backend can honour")
        self.asm.emit(encode_movz_xn_imm(0, 0))   # X0 = 0: a fresh value

    def _specialization_args(self, e: F.CallExpr, ct_params: list) -> list:
        """The argument expressions binding `ct_params` at this call site."""
        try:
            return comptime_eval.specialization_args(e, ct_params)
        except ValueError as exc:
            raise CodegenError(str(exc))

    def _emit_call(self, e: F.CallExpr) -> None:
        name = _callee_symbol(e.func)
        if name is None:
            raise CodegenError(
                f"unsupported call target on the formal arm64 path "
                f"(got {type(e.func).__name__})")
        if name == "range":
            self._emit_range_list(list(e.args))
            return
        if name == "len":
            self._emit_len(e)
            return
        # A type constructor is a conversion, not a call. Intercepted before the
        # extern path, because the extern path would emit a BL against a
        # symbol named e.g. `Int` that nothing defines (the decision is
        # formal/model.type_constructor_kind; the width normalization below is
        # the arm64 half).
        if name not in self._functions:
            tkind = M.type_constructor_kind(name)
            if tkind is not None:
                self._emit_type_constructor(e, name, tkind)
                return
        if name in self._structs:
            self._emit_struct_constructor(e, name, self._structs[name])
            return
        is_extern = name not in self._functions
        if is_extern:
            # Unknown signature: AAPCS has no place for Python kwargs on a
            # raw BL. Drop them (they are almost always literals like
            # flush=True) and pass positional args only — same ABI the
            # extern path already uses for zero-kwarg calls.
            args = list(e.args)
        else:
            args = self._bind_call_args(name, e)
        # A comptime specialization `f[a, b](x)` binds the callee's comptime
        # parameters (which are leading arguments on this path), so the bracket
        # expressions are evaluated here, in the caller's scope, and passed
        # ahead of the call-time arguments. A bare `f(x)` to the same generic
        # binds each comptime parameter to 0: this path has no type inference
        # to deduce them from the arguments, and 0 is the same "unknown
        # compile-time value" every other unresolved compile-time name
        # already gets here — but the two spellings can never disagree about
        # the callee's arity, because both go through the same parameter list.
        if not is_extern:
            fdef = self._functions.get(name)
            ct_params = _comptime_param_names(fdef) if fdef is not None else []
            if ct_params:
                bound = self._specialization_args(e, ct_params)
                args = bound + list(args)
        # Flatten `*star` / reject `**dst` before the arity check so a
        # single list literal expands to its elements (common: f(*[a,b])).
        flat: list = []
        side_effects: list = []
        for a in args:
            if isinstance(a, F.UnaryOp) and a.op == "*":
                op = a.operand
                if isinstance(op, (F.ListExpr, F.TupleExpr)):
                    flat.extend(op.elements)
                    continue
                # Dynamic *unpack: no static expansion under AAPCS — keep
                # the operand's side effects, contribute no positional.
                side_effects.append(op)
                continue
            if isinstance(a, F.UnaryOp) and a.op == "**":
                # **kwargs: evaluate mapping for effects; formal ABI has no
                # keyword slots (same drop as unknown-signature kwargs).
                side_effects.append(a.operand)
                continue
            flat.append(a)
        args = flat
        # Side-effect-only operands must still run, but AFTER real args are
        # evaluated would reorder observably — evaluate them first into a
        # pushed slot, then the real args on top, then pop in reverse.
        # Simpler and order-preserving enough for compile: run them first
        # (they don't produce call arguments).
        for se in side_effects:
            self._emit_expr(se)
        # AAPCS: only X0..X7 are argument registers. Args past 8 are
        # evaluated for side effects then dropped (same compile-only
        # fidelity as unknown-signature kwargs / dynamic *unpack).
        if len(args) > 8:
            extra = args[8:]
            args = args[:8]
            for x in extra:
                self._emit_expr(x)

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
            # A linked library's export spelling wins over the bare name, so
            # the BL, the GOT slot and the bind stream all name the symbol the
            # library actually defines.
            self.asm.emit_extern_bl(self._dylib_syms.get(name, name))
        else:
            self.asm.emit(encode_bl(0))
            self.asm.emit_label_rel(name, here_offset=-4)


    # ── Comprehension / slice / div-shift / compare-chain ──────────

    def _compr_cap(self, expr: F.Comprehension) -> int:
        """Upper bound on result element (or pair) count for frame reserve.

        Single-generator over a list/tuple literal uses its length; nested
        generators multiply. Unknown iterables fall back to a frame-safe
        default (runtime append still bounds-checks)."""
        gens = expr.generators or []
        if not gens:
            return 0

        def _lit(v):
            if isinstance(v, F.IntLiteral):
                return v.value
            if isinstance(v, F.UnaryOp) and v.op == "-" \
                    and isinstance(v.operand, F.IntLiteral):
                return -v.operand.value
            return None

        n = 1
        for g in gens:
            it = g.iterable
            if isinstance(it, (F.ListExpr, F.TupleExpr, F.SetExpr)):
                m = len(it.elements)
            elif isinstance(it, F.CallExpr) and isinstance(it.func, F.IdentExpr) \
                    and it.func.name == "range" and it.args:
                if len(it.args) == 1:
                    a0 = _lit(it.args[0])
                    m = max(0, a0) if a0 is not None else 64
                elif len(it.args) >= 2:
                    a0, a1 = _lit(it.args[0]), _lit(it.args[1])
                    if a0 is not None and a1 is not None:
                        m = max(0, a1 - a0)
                    else:
                        m = 64
                else:
                    m = 64
            else:
                m = 64
            n *= m
            if n > 256:
                return 256
        return max(1, n)

    def _reserve_blob(self, nbytes: int, what: str) -> int:
        if nbytes % 8:
            nbytes += 8 - (nbytes % 8)
        if self._list_cursor + nbytes > self._blob_cap:
            raise CodegenError(
                f"{what} exceeds the formal frame "
                f"({self._list_cursor + nbytes} > {self._blob_cap} bytes)")
        offset = self._list_cursor
        self._list_cursor += nbytes
        return offset

    def _emit_comprehension(self, expr: F.Comprehension) -> None:
        """Lower list/set/dict/generator comprehensions to stack blobs.

        Result layout matches `_emit_list` / `_emit_dict`. Generator loops
        use `_ci{d}`/`_cb{d}` temps (allocated by `_collect_var_names`).
        `kind == 'generator'` lowers like a list (same as the interpreter).
        Dict comps store KEY in `.element` and VALUE in `.key` (parser swap)."""
        kind = expr.kind
        is_dict = (kind == "dict")
        gens = expr.generators or []
        if not gens:
            nbytes = 16 if is_dict else 8
            offset = self._reserve_blob(nbytes, "comprehension")
            self._emit_list_base(offset)
            self._emit_mov_imm("X10", 0)
            self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
            self.asm.emit(encode_mov_zr_xn(0, 9))
            return

        cap = self._compr_cap(expr)
        elem_size = 16 if is_dict else 8
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(
                "comprehension exceeds the formal frame "
                f"({self._list_cursor + 8} > {self._blob_cap} bytes)")
        max_cap = (avail - 8) // elem_size
        if cap > max_cap:
            cap = max_cap
        if cap < 0:
            cap = 0
        nbytes = (8 + 16 * cap) if is_dict else (8 + 8 * cap)
        offset = self._reserve_blob(nbytes, "comprehension")
        self._emit_list_base(offset)
        self._emit_mov_imm("X10", 0)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))

        d0 = self._compr_depth
        self._compr_depth = d0 + len(gens)
        try:
            self._emit_compr_gen(expr, 0, offset, is_dict, cap, d0)
        finally:
            self._compr_depth = d0

        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_compr_gen(self, expr: F.Comprehension, gi: int,
                        res_offset: int, is_dict: bool, cap: int,
                        d0: int) -> None:
        """Recursive generator walk: gen[gi] … gen[-1], then append element."""
        gens = expr.generators
        if gi >= len(gens):
            if is_dict:
                self._emit_expr(expr.element)  # KEY
                self.asm.emit(encode_stp_sp_pre(0, 2))
                self._emit_expr(expr.key)      # VALUE
                self.asm.emit(encode_ldp_sp_post(0, 2))  # X0=key, X1=val
                self._compr_append_pair(res_offset, cap)
            else:
                self._emit_expr(expr.element)
                self._compr_append_elem(res_offset, cap)
            return

        gen = gens[gi]
        di = d0 + gi
        ci_name, cb_name = f"_ci{di}", f"_cb{di}"
        ci_reg = self._var_regs.get(ci_name)
        cb_reg = self._var_regs.get(cb_name)

        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        start_label = f"{fn}_cg{wid}_start"
        step_label = f"{fn}_cg{wid}_step"
        false_label = f"{fn}_cg{wid}_false"
        end_label = f"{fn}_cg{wid}_end"

        self._emit_expr(gen.iterable)
        self._store_var(cb_name, 0)
        self.asm.emit(encode_movz_xd_imm(0, 0))
        self._store_var(ci_name, 0)

        self._loops.append({"start": start_label, "step": step_label,
                            "break": end_label,
                            "fin_depth": len(self._pending_finally)})
        try:
            self.asm.label(start_label)
            self._load_var(cb_name, 9)
            self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))
            if ci_reg is not None:
                self.asm.emit(encode_cmp_xn_xm(ci_reg, 1))
            else:
                self._load_var(ci_name, 0)
                self.asm.emit(encode_cmp_xn_xm(0, 1))
            self.asm.emit(encode_cset_xd_cond(0, "lt"))
            self.asm.emit(encode_cbz_xn(0, 0))
            self.asm.emit_label_rel(false_label, here_offset=-4)

            self.asm.emit(encode_add_xd_xn_imm(2, 9, 8))
            if ci_reg is not None:
                self.asm.emit(encode_add_xd_xn_xm_lsl3(2, 2, ci_reg))
            else:
                self._load_var(ci_name, 0)
                self.asm.emit(encode_add_xd_xn_xm_lsl3(2, 2, 0))
            self.asm.emit(encode_ldr_xt_xn_imm(0, 2, 0))

            tnames = _lbn_target_names(gen.target) if isinstance(
                gen.target, str) else []
            if not tnames or any(not n.isidentifier() for n in tnames):
                raise CodegenError(
                    f"comprehension target must be a plain name or tuple "
                    f"of plain names (got {gen.target!r})")
            ttree = _for_target_tree(gen.target) if isinstance(
                gen.target, str) else gen.target
            if ttree is None:
                raise CodegenError(
                    f"comprehension target must be a plain name or tuple "
                    f"of plain names (got {gen.target!r})")
            if isinstance(ttree, list):
                self._emit_for_unpack(ttree, f"{fn}_cgu{wid}")
            else:
                self._store_var(tnames[0], 0)

            for cond in gen.conditions or []:
                self._emit_expr(cond)
                self.asm.emit(encode_cmp_xn_imm(0, 0))
                self._record_cond_branch()
                self.asm.emit(encode_cbz_xn(0, 0))
                self.asm.emit_label_rel(step_label, here_offset=-4)

            self._emit_compr_gen(expr, gi + 1, res_offset, is_dict, cap, d0)

            self.asm.label(step_label)
            if ci_reg is not None:
                self.asm.emit(encode_add_xd_xn_imm(ci_reg, ci_reg, 1))
            else:
                self._load_var(ci_name, 0)
                self.asm.emit(encode_add_xd_xn_imm(0, 0, 1))
                self._store_var(ci_name, 0)
            self._emit_b_to(start_label)

            self.asm.label(false_label)
            self.asm.label(end_label)
        finally:
            self._loops.pop()

    def _compr_append_elem(self, res_offset: int, cap: int) -> None:
        """Append X0 to list result at res_offset; exit(1) past cap."""
        self.asm.emit(encode_stp_sp_pre(0, 2))
        self._emit_list_base(res_offset)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))
        self._emit_mov_imm("X2", cap)
        self.asm.emit(encode_cmp_xn_xm(1, 2))
        self.asm.emit(encode_cset_xd_cond(3, "cs"))
        self._while_counter += 1
        oob = f"{self.func_name}_cgoob{self._while_counter}"
        ok = f"{self.func_name}_cgok{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(oob, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(4, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(4, 4, 1))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))
        self.asm.emit(encode_str_xt_xn_imm(0, 4, 0))
        self.asm.emit(encode_add_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self._emit_b_to(ok)
        self.asm.label(oob)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok)

    def _compr_append_pair(self, res_offset: int, cap: int) -> None:
        """Append (X0=key, X1=value) to dict result; exit(1) past cap."""
        self.asm.emit(encode_stp_sp_pre(0, 1))  # push key; X1 still value?
        # STP X0, XZR — X1 is untouched, still value. Push it next:
        self.asm.emit(encode_stp_sp_pre(1, 31))  # push value
        self._emit_list_base(res_offset)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))
        self._emit_mov_imm("X2", cap)
        self.asm.emit(encode_cmp_xn_xm(1, 2))
        self.asm.emit(encode_cset_xd_cond(3, "cs"))
        self._while_counter += 1
        oob = f"{self.func_name}_cpoob{self._while_counter}"
        ok = f"{self.func_name}_cpok{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(oob, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(4, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl4(4, 4, 1))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))
        self.asm.emit(encode_str_xt_xn_imm(0, 4, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))
        self.asm.emit(encode_str_xt_xn_imm(0, 4, 8))
        self.asm.emit(encode_add_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self._emit_b_to(ok)
        self.asm.label(oob)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok)

    def _emit_list_star(self, expr) -> None:
        """List literal containing `*iterable` splats — reserve, then append.

        Static list/tuple operands contribute their length; dynamic operands
        are spliced at runtime with a frame-safe cap."""
        static_n = 0
        for el in expr.elements:
            if isinstance(el, F.UnaryOp) and el.op == "*":
                op = el.operand
                if isinstance(op, (F.ListExpr, F.TupleExpr, F.SetExpr)):
                    static_n += len(op.elements)
                else:
                    static_n += 8
            else:
                static_n += 1
        cap = max(1, static_n)
        offset = self._reserve_blob(8 + 8 * cap, "list unpack")
        self._emit_list_base(offset)
        self._emit_mov_imm("X10", 0)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))

        for el in expr.elements:
            if isinstance(el, F.UnaryOp) and el.op == "*":
                op = el.operand
                if isinstance(op, (F.ListExpr, F.TupleExpr, F.SetExpr)):
                    for sub in op.elements:
                        self._emit_expr(sub)
                        self._compr_append_elem(offset, cap)
                else:
                    self._emit_expr(op)
                    self._emit_star_splice(offset, cap)
            else:
                self._emit_expr(el)
                self._compr_append_elem(offset, cap)

        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_star_splice(self, res_offset: int, cap: int) -> None:
        """X0 = source blob; append every element into the result.

        Keeps source base in X9 and index in X3 across appends (append
        uses X0-X4 and may push/pop, but does not touch X9/X3)."""
        self.asm.emit(encode_mov_zr_xn(9, 0))       # src base
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))  # src count
        self.asm.emit(encode_movz_xd_imm(3, 0))       # i = 0
        self._while_counter += 1
        loop = f"{self.func_name}_spl{self._while_counter}"
        done = f"{self.func_name}_spd{self._while_counter}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_xm(3, 1))
        self.asm.emit(encode_cset_xd_cond(4, "ge"))
        self.asm.emit(encode_cbz_xn(0, 4))
        self.asm.emit_label_rel(done, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(5, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(5, 5, 3))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 5, 0))
        self._compr_append_elem(res_offset, cap)
        self.asm.emit(encode_add_xd_xn_imm(3, 3, 1))
        self._emit_b_to(loop)
        self.asm.label(done)

    def _emit_div_shift_pow(self, e: F.BinaryOp, op: str) -> None:
        """`/` `//` `%` `<<` `>>` `**` on the formal arm64 path.

        Division is UDIV/SDIV (trunc toward zero; `//` matches `/` on the
        unsigned default). Remainder is DIV then MSUB (n - (n/d)*d). Shifts
        use LSLV/LSRV/ASRV (immediate form when the RHS is a small literal).
        `**` unrolls a small literal exponent."""
        signed = cmp_signed(common_type(self._ttype(e.left),
                                        self._ttype(e.right)))
        if op in ("/", "//", "%"):
            self._if_counter += 1
            cid = self._if_counter
            fn = self.func_name
            div0_label = f"{fn}_dv{cid}_z"
            ok_label = f"{fn}_dv{cid}_ok"
            self._emit_expr(e.left)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(e.right, "X1")
            self.asm.emit(encode_ldp_sp_post(0, 2))
            self.asm.emit(encode_cmp_xn_imm(1, 0))
            self.asm.emit(encode_cbz_xn(0, 1))
            self.asm.emit_label_rel(div0_label, here_offset=-4)
            if signed:
                self.asm.emit(encode_sdiv_xd_xn_xm(2, 0, 1))
            else:
                self.asm.emit(encode_udiv_xd_xn_xm(2, 0, 1))
            if op in ("/", "//"):
                self.asm.emit(encode_mov_zr_xn(0, 2))
            else:
                self.asm.emit(encode_msub_xd_xn_xm_xa(0, 2, 1, 0))
            self._emit_trunc(common_type(self._ttype(e.left),
                                         self._ttype(e.right)))
            self.asm.emit(encode_b(0))
            self.asm.emit_label_rel(ok_label, here_offset=-4)
            self.asm.label(div0_label)
            self.asm.emit(encode_movz_xd_imm(0, 1))
            self.asm.emit(encode_movz_xd_imm(16, 1))
            self.asm.emit(encode_svc(0x80))
            self.asm.label(ok_label)
            return

        if op in ("<<", ">>"):
            imm_r = e.right
            if isinstance(imm_r, F.IntLiteral) and 0 <= imm_r.value <= 63:
                self._emit_expr(e.left)
                if op == "<<":
                    self.asm.emit(encode_lsl_xd_xn_imm(0, 0, imm_r.value))
                elif signed:
                    self.asm.emit(encode_asr_xd_xn_imm(0, 0, imm_r.value))
                else:
                    self.asm.emit(encode_lsr_xd_xn_imm(0, 0, imm_r.value))
                self._emit_trunc(common_type(self._ttype(e.left),
                                             self._ttype(e.right)))
                return
            self._emit_expr(e.left)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(e.right, "X1")
            self.asm.emit(encode_ldp_sp_post(0, 2))
            if op == "<<":
                self.asm.emit(encode_lslv_xd_xn_xm(0, 0, 1))
            elif signed:
                self.asm.emit(encode_asrv_xd_xn_xm(0, 0, 1))
            else:
                self.asm.emit(encode_lsrv_xd_xn_xm(0, 0, 1))
            self._emit_trunc(common_type(self._ttype(e.left),
                                         self._ttype(e.right)))
            return

        if op == "**":
            exp = e.right
            lit = self._static_int(exp)
            if lit is not None and 0 <= lit <= 64:
                n = lit
                if n == 0:
                    self.asm.emit(encode_movz_xd_imm(0, 1))
                    return
                self._emit_expr(e.left)
                if n == 1:
                    return
                if n == 2:
                    # x0 = base * base; no stack traffic needed.
                    self.asm.emit(encode_mul_xd_xn_xm(0, 0, 0))
                else:
                    self.asm.emit(encode_stp_sp_pre(0, 2))  # push base
                    for _ in range(n - 1):
                        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 0))
                        self.asm.emit(encode_mul_xd_xn_xm(0, 0, 1))
                    # Pop without writing x0: the popped value is the pre-MUL
                    # base, and x0 now holds the product.  LDP-post into
                    # (0,2) would restore the base over it, so discard into
                    # x2/x3, which are dead at this point.
                    self.asm.emit(encode_ldp_sp_post(2, 3))
                self._emit_trunc(common_type(self._ttype(e.left),
                                             self._ttype(e.right)))
                return
            if lit is not None and lit < 0:
                # Integer ** negative → 0 (matches Python for |base| > 1
                # and the formal int lattice has no fractions).
                self.asm.emit(encode_movz_xd_imm(0, 0))
                return
            # Runtime exponent: result = 1; while exp > 0: result *= base;
            # exp >>= 1; base *= base (binary exponentiation). Negative exp
            # exits with 0.
            self._if_counter += 1
            pid = self._if_counter
            fn = self.func_name
            loop = f"{fn}_pow{pid}_l"
            body = f"{fn}_pow{pid}_b"
            done = f"{fn}_pow{pid}_d"
            neg = f"{fn}_pow{pid}_n"
            self._emit_expr(e.left)
            self.asm.emit(encode_stp_sp_pre(0, 2))       # base
            self._emit_expr(e.right)
            # X0 = exp
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cset_xd_cond(1, "lt"))
            self.asm.emit(encode_cbz_xn(0, 1))
            self.asm.emit_label_rel(neg, here_offset=-4)
            # result = 1 in X2; keep exp in X0, base on stack
            self.asm.emit(encode_movz_xd_imm(2, 1))
            self.asm.label(loop)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cset_xd_cond(1, "le"))
            self.asm.emit(encode_cbz_xn(0, 1))
            self.asm.emit_label_rel(done, here_offset=-4)
            self.asm.label(body)
            # if exp & 1: result *= base  (X1 = exp & 1; skip if zero)
            self.asm.emit(encode_movz_xd_imm(4, 1))
            self.asm.emit(encode_and_xd_xn_xm(1, 0, 4))  # exp & 1
            so = f"{fn}_pow{pid}_so"
            self.asm.emit(encode_cbz_xn(0, 1))
            self.asm.emit_label_rel(so, here_offset=-4)
            self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))
            self.asm.emit(encode_mul_xd_xn_xm(2, 2, 5))
            self.asm.label(so)
            # base *= base
            self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))
            self.asm.emit(encode_mul_xd_xn_xm(5, 5, 5))
            self.asm.emit(encode_str_xt_xn_imm(5, 31, 0))
            # exp >>= 1
            self.asm.emit(encode_lsr_xd_xn_imm(0, 0, 1))
            self._emit_b_to(loop)
            self.asm.label(done)
            self.asm.emit(encode_mov_zr_xn(0, 2))
            self.asm.emit(encode_ldp_sp_post(0, 31))     # drop base
            self._emit_trunc(common_type(self._ttype(e.left),
                                         self._ttype(e.right)))
            self._emit_b_to(f"{fn}_pow{pid}_end")
            self.asm.label(neg)
            self.asm.emit(encode_ldp_sp_post(0, 31))
            self.asm.emit(encode_movz_xd_imm(0, 0))
            self.asm.label(f"{fn}_pow{pid}_end")
            return

        raise CodegenError(
            f"unsupported binary operator {op!r} on the formal arm64 path")

    def _emit_compare_chain(self, e: F.CompareChain) -> None:
        """`a < b < c` — each operand evaluated once; results ANDed.

        Left of link i is the right of link i-1 (kept on the stack).
        Result 0/1 in X0."""
        ops = e.ops
        operands = e.operands
        if len(operands) != len(ops) + 1:
            raise CodegenError("malformed compare chain")
        cmp_conds = {
            "<=": ("ls", "le"),
            ">": ("hi", "gt"),
            "==": ("eq", "eq"),
            ">=": ("cs", "ge"),
            "<": ("cc", "lt"),
            "!=": ("ne", "ne"),
            "is": ("eq", "eq"),
            "is not": ("ne", "ne"),
        }
        for op in ops:
            if op not in cmp_conds:
                raise CodegenError(
                    f"unsupported compare-chain operator {op!r} on the "
                    f"formal arm64 path")

        self._if_counter += 1
        cid = self._if_counter
        fn = self.func_name
        false_label = f"{fn}_cc{cid}_false"
        end_label = f"{fn}_cc{cid}_end"

        self._emit_expr(operands[0])
        self.asm.emit(encode_stp_sp_pre(0, 2))

        for i, op in enumerate(ops):
            u, s = cmp_conds[op]
            self._emit_expr_to(operands[i + 1], "X1")
            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))
            self.asm.emit(encode_cmp_xn_xm(0, 1))
            if cmp_signed(common_type(self._ttype(operands[i]),
                                      self._ttype(operands[i + 1]))):
                self.asm.emit(encode_cset_xd_cond(0, s))
            else:
                self.asm.emit(encode_cset_xd_cond(0, u))
            self.asm.emit(encode_cbz_xn(0, 0))
            self.asm.emit_label_rel(false_label, here_offset=-4)
            if i < len(ops) - 1:
                self.asm.emit(encode_str_xt_xn_imm(1, 31, 0))

        self.asm.emit(encode_ldp_sp_post(0, 2))
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(end_label, here_offset=-4)
        self.asm.label(false_label)
        self.asm.emit(encode_ldp_sp_post(0, 2))
        self.asm.emit(encode_movz_xd_imm(0, 0))
        self.asm.label(end_label)

    def _emit_slice(self, expr: F.SliceExpr) -> None:
        self._emit_slice_parts(expr.obj, expr.start, expr.stop, expr.step)

    def _emit_slice_parts(self, obj, start_e, stop_e, step_e) -> None:
        """`obj[start:stop:step]` → new list blob in X0.

        Defaults: start=0, stop=count, step=1 (None nodes). Negative bounds
        wrap against count then clamp to [0, count]. step==0 exits(1).
        Negative step iterates i from stop-1 down while i >= start and
        i >= 0 (Python's stop-default of -1 for reversed slices is mapped
        to start=0 / stop=count via the None defaults when both are
        omitted; explicit negative-step bounds follow the clamped rule).
        Result capacity is a static upper bound (literal length or 64)."""
        if isinstance(obj, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            src_cap = len(obj.elements)
        elif isinstance(obj, F.Comprehension):
            src_cap = self._compr_cap(obj)
        else:
            src_cap = 64
        src_cap = max(1, src_cap)
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(
                f"slice exceeds the formal frame "
                f"({self._list_cursor + 8} > {self._blob_cap} bytes)")
        if src_cap > (avail - 8) // 8:
            src_cap = max(1, (avail - 8) // 8)
        offset = self._reserve_blob(8 + 8 * src_cap, "slice")
        self._emit_list_base(offset)
        self._emit_mov_imm("X10", 0)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))

        self._emit_expr(obj)
        self.asm.emit(encode_stp_sp_pre(0, 2))  # [SP+0]=src base

        if step_e is None:
            self.asm.emit(encode_movz_xd_imm(8, 1))
        else:
            self._emit_expr_to(step_e, "X8")
        self.asm.emit(encode_stp_sp_pre(8, 31))  # push step
        # SP+0=step, SP+16=src

        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 16))
        self.asm.emit(encode_ldr_xt_xn_imm(9, 9, 0))  # count

        if start_e is None:
            self.asm.emit(encode_movz_xd_imm(4, 0))
        else:
            self._emit_expr_to(start_e, "X4")
        self.asm.emit(encode_stp_sp_pre(4, 31))  # push start
        # SP+0=start, SP+16=step, SP+32=src

        if stop_e is None:
            self.asm.emit(encode_mov_zr_xn(5, 9))
        else:
            self._emit_expr_to(stop_e, "X5")
        self.asm.emit(encode_stp_sp_pre(5, 31))  # push stop
        # SP+0=stop, SP+16=start, SP+32=step, SP+48=src

        # Wrap negatives and clamp to [0, count].
        self.asm.emit(encode_ldr_xt_xn_imm(4, 31, 16))
        self.asm.emit(encode_cmp_xn_imm(4, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        self.asm.emit(encode_cbz_xn(0, 0))
        w1 = f"{self.func_name}_slw{self._while_counter}a"
        self.asm.emit_label_rel(w1, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_xm(4, 4, 9))
        self.asm.emit(encode_str_xt_xn_imm(4, 31, 16))
        self.asm.label(w1)
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))
        self.asm.emit(encode_cmp_xn_imm(5, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        self.asm.emit(encode_cbz_xn(0, 0))
        w2 = f"{self.func_name}_slw{self._while_counter}b"
        self.asm.emit_label_rel(w2, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_xm(5, 5, 9))
        self.asm.emit(encode_str_xt_xn_imm(5, 31, 0))
        self.asm.label(w2)
        self.asm.emit(encode_ldr_xt_xn_imm(4, 31, 16))
        self.asm.emit(encode_cmp_xn_xm(9, 4))
        self.asm.emit(encode_cset_xd_cond(0, "hi"))
        self.asm.emit(encode_cbz_xn(0, 0))
        c1 = f"{self.func_name}_slk{self._while_counter}a"
        self.asm.emit_label_rel(c1, here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(4, 9))
        self.asm.emit(encode_str_xt_xn_imm(4, 31, 16))
        self.asm.label(c1)
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))
        self.asm.emit(encode_cmp_xn_xm(9, 5))
        self.asm.emit(encode_cset_xd_cond(0, "hi"))
        self.asm.emit(encode_cbz_xn(0, 0))
        c2 = f"{self.func_name}_slk{self._while_counter}b"
        self.asm.emit_label_rel(c2, here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(5, 9))
        self.asm.emit(encode_str_xt_xn_imm(5, 31, 0))
        self.asm.label(c2)

        # step == 0 → exit 1 (cbnz skips the exit when step != 0)
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, 32))
        self.asm.emit(encode_cmp_xn_imm(8, 0))
        zstep = f"{self.func_name}_slz{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 8))
        self.asm.emit_label_rel(zstep, here_offset=-4)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(zstep)

        # i → X6: start if step>0 else stop-1
        self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 16))  # start
        self.asm.emit(encode_cmp_xn_imm(8, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        self.asm.emit(encode_cbz_xn(0, 0))
        neg_init = f"{self.func_name}_sln{self._while_counter}"
        self.asm.emit_label_rel(neg_init, here_offset=-4)
        self._emit_b_to(f"{self.func_name}_slm{self._while_counter}")
        self.asm.label(neg_init)
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))
        self.asm.emit(encode_sub_xd_xn_imm(6, 5, 1))
        self.asm.label(f"{self.func_name}_slm{self._while_counter}")

        # Loop: determine signedness of step, then test against stop/start.
        self._while_counter += 1
        wid = self._while_counter
        loop = f"{self.func_name}_slt{wid}"
        body = f"{self.func_name}_slb{wid}"
        step_lbl = f"{self.func_name}_sls{wid}"
        done = f"{self.func_name}_sld{wid}"
        neg_body = f"{self.func_name}_sln{wid}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_imm(8, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))  # 1 if step < 0
        self.asm.emit(encode_cbz_xn(0, 0))            # step >= 0 → positive
        self.asm.emit_label_rel(neg_body, here_offset=-4)
        # positive: body if i < stop else done
        self._emit_b_to(body)
        self.asm.label(neg_body)
        # negative: body if i >= 0 else done
        self.asm.emit(encode_cmp_xn_imm(6, 0))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(done, here_offset=-4)
        self._emit_b_to(body)

        self.asm.label(body)
        # append src[i]
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 48))  # src base
        self.asm.emit(encode_add_xd_xn_imm(5, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(5, 5, 6))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 5, 0))
        self._compr_append_elem(offset, src_cap)
        # append may clobber X6/X8 — reload step and update i from stack
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, 32))  # step
        self.asm.emit(encode_ldr_xt_xn_imm(4, 31, 16))  # start (keep live)
        self.asm.emit(encode_add_xd_xn_xm(6, 6, 8))     # i += step
        self._emit_b_to(loop)

        self.asm.label(step_lbl)  # unused alias kept for label uniqueness
        self.asm.label(done)
        self.asm.emit(encode_ldp_sp_post(0, 31))  # pop stop
        self.asm.emit(encode_ldp_sp_post(0, 31))  # pop start
        self.asm.emit(encode_ldp_sp_post(0, 31))  # pop step
        self.asm.emit(encode_ldp_sp_post(0, 31))  # pop src (clobbers X0)
        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_slice_store(self, target: F.SliceExpr, value) -> None:
        """`obj[a:b] = value` — same-length replace of the slice range.

        Formal list blobs cannot change length without a compaction pass;
        if len(value) != slice_len at runtime, Darwin exit(1). step must
        be 1 (or None)."""
        if target.step is not None:
            st = target.step
            if not (isinstance(st, F.IntLiteral) and st.value == 1):
                raise CodegenError(
                    "slice assignment with step != 1 is not supported on "
                    "the formal arm64 path")
        obj = target.obj
        self._if_counter += 1
        sid = self._if_counter
        fn = self.func_name
        fail_label = f"{fn}_ss{sid}_fail"
        done_label = f"{fn}_ss{sid}_done"

        self._emit_expr(value)
        self.asm.emit(encode_stp_sp_pre(0, 2))  # [SP]=val base
        self._emit_expr(obj)
        self.asm.emit(encode_stp_sp_pre(0, 2))  # [SP]=obj, [SP+16]=val
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(2, 9, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, 16))
        self.asm.emit(encode_ldr_xt_xn_imm(3, 8, 0))

        if target.start is None:
            self.asm.emit(encode_movz_xd_imm(4, 0))
        else:
            self._emit_expr_to(target.start, "X4")
        if target.stop is None:
            self.asm.emit(encode_mov_zr_xn(5, 2))
        else:
            self._emit_expr_to(target.stop, "X5")
        self.asm.emit(encode_cmp_xn_imm(4, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        self.asm.emit(encode_cbz_xn(0, 0))
        w1 = f"{fn}_ssw{sid}1"
        self.asm.emit_label_rel(w1, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_xm(4, 4, 2))
        self.asm.label(w1)
        self.asm.emit(encode_cmp_xn_imm(5, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        self.asm.emit(encode_cbz_xn(0, 0))
        w2 = f"{fn}_ssw{sid}2"
        self.asm.emit_label_rel(w2, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_xm(5, 5, 2))
        self.asm.label(w2)
        self.asm.emit(encode_cmp_xn_xm(2, 4))
        self.asm.emit(encode_cset_xd_cond(0, "hi"))
        self.asm.emit(encode_cbz_xn(0, 0))
        c1 = f"{fn}_ssc{sid}1"
        self.asm.emit_label_rel(c1, here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(4, 2))
        self.asm.label(c1)
        self.asm.emit(encode_cmp_xn_xm(2, 5))
        self.asm.emit(encode_cset_xd_cond(0, "hi"))
        self.asm.emit(encode_cbz_xn(0, 0))
        c2 = f"{fn}_ssc{sid}2"
        self.asm.emit_label_rel(c2, here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(5, 2))
        self.asm.label(c2)
        self.asm.emit(encode_cmp_xn_xm(5, 4))
        self.asm.emit(encode_cset_xd_cond(0, "cs"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(fail_label, here_offset=-4)
        self.asm.emit(encode_sub_xd_xn_xm(6, 5, 4))
        self.asm.emit(encode_cmp_xn_xm(3, 6))
        self.asm.emit(encode_cset_xd_cond(0, "eq"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(fail_label, here_offset=-4)
        self.asm.emit(encode_movz_xd_imm(7, 0))
        loop = f"{fn}_ssl{sid}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_xm(7, 6))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(done_label, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_xm(10, 4, 7))
        self.asm.emit(encode_add_xd_xn_imm(11, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(11, 11, 10))
        self.asm.emit(encode_add_xd_xn_imm(12, 8, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(12, 12, 7))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 12, 0))
        self.asm.emit(encode_str_xt_xn_imm(0, 11, 0))
        self.asm.emit(encode_add_xd_xn_imm(7, 7, 1))
        self._emit_b_to(loop)
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(done_label, here_offset=-4)
        self.asm.label(fail_label)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(done_label)
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))


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
        if imm > 0xffffffffffffffff:
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
            while imm > 0 and pos <= 48:
                chunk = imm & 0xffff
                self.asm.emit(encode_movk_xd_imm(rd, chunk, pos))
                imm >>= 16
                pos += 16

    def _emit_shift_reg(self, op: str, signed: bool) -> None:
        """Variable shift X0 = X0 <op> X1 (LSLV/LSRV/ASRV)."""
        if op == "<<":
            self.asm.emit(encode_lslv_xd_xn_xm(0, 0, 1))
        elif signed:
            self.asm.emit(encode_asrv_xd_xn_xm(0, 0, 1))
        else:
            self.asm.emit(encode_lsrv_xd_xn_xm(0, 0, 1))

    def _check_comptime_target(self, name: str, what: str) -> None:
        """Refuse a store to a name that is currently a `comptime` binding.

        The store would otherwise be silently dropped: reads of the name go
        through `_comptime_vals` (which is the whole point — the binding is a
        constant, not a local), so a following `_store_var` would write a slot
        nothing ever reads. That is a silent miscompile, so it is an error.
        Real Mojo rejects the assignment too, for the same reason: a `comptime`
        name is not assignable."""
        if name in self._comptime_vals:
            raise CodegenError(
                f"{what} to comptime binding {name!r} (a `comptime` name is a "
                "compile-time constant and cannot be assigned)")

    def _bind_comptime(self, stmt) -> None:
        """Record a `comptime NAME = value` binding, or fail honestly.

        The decision itself is shared (comptime_eval.resolve_var); what is
        arm64-specific is only that an unresolvable binding is an ERROR here
        rather than a runtime local. The gimple path instead leaves the name
        unbound so a later read hits its unknown-identifier placeholder —
        same observable outcome (the name is not the declared value), reached
        without a hard failure mid-function.
        """
        name = stmt.target
        resolved = comptime_eval.resolve_var(
                stmt, self._comptime_vals, self._comptime_hook)
        if resolved is None:
            raise CodegenError(
                f"comptime {name} = ... does not fold to a compile-time "
                "constant on the formal arm64 path")
        kind, val = resolved
        if kind == "list":
            self._comptime_list_asts[name] = val
        else:
            self._comptime_vals[name] = val

    def _emit_comptime_read(self, name: str) -> None:
        """X0 = the value of the `comptime` binding `name`.

        A string binding is not a machine word here: this path has no
        interned comptime strings, so it materializes the interned literal
        for the text, which is what the value *is* everywhere else a string
        is (see `_emit_expr`'s StringLiteral case and the dict key compare,
        which relies on literals being interned by content)."""
        val = self._comptime_vals[name]
        if isinstance(val, str):
            self.asm.emit_adrp_add(0, self._intern_string(val))
            return
        self._emit_mov_imm("X0", int(val))

    # A `comptime for` over more iterations than this is emitted as the
    # ordinary runtime loop instead of unrolled: the point of folding is a
    # compile-time-known trip count, not a guarantee it is small. The cap is
    # passed to the shared resolver, which is where the expansion happens.
    COMPTIME_UNROLL_CAP = 64

    def _comptime_iterable(self, iterable):
        """The elements of a `comptime for` iterable when they are all known
        at compile time, else None (→ emit the ordinary runtime loop)."""
        return comptime_eval.resolve_for_iterable(
            iterable, self._comptime_vals, self._comptime_list_asts,
            self.COMPTIME_UNROLL_CAP, self._comptime_hook)

    def _emit_comptime_target(self, target, value) -> None:
        """Bind a `comptime for` target for one iteration, as an ordinary
        local assignment (the counter is a real runtime local — only the
        trip count was compile-time here), so a folded and an unfolded
        `comptime for` produce the same shape of code."""
        self._emit_stmt(F.AssignStmt(target=F.IdentExpr(name=target),
                                     value=value, line=0, col=0))

    def _is_container_expr(self, e) -> bool:
        """True when `e` is known to lower to a list/set/tuple blob."""
        if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr,
                          F.Comprehension, F.SliceExpr)):
            return True
        if isinstance(e, F.CallExpr) and isinstance(e.func, F.IdentExpr):
            return e.func.name in ("range", "list", "sorted", "set",
                                   "reversed")
        if isinstance(e, F.BinaryOp) and e.op in ("+", "|", "or", "and"):
            return (self._is_container_expr(e.left)
                    or self._is_container_expr(e.right))
        return False

    def _blob_est(self, e) -> int:
        """Static upper bound on element count for frame reservation."""
        if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            return len(e.elements)
        if isinstance(e, F.Comprehension):
            return self._compr_cap(e)
        if isinstance(e, F.SliceExpr):
            return 64
        if isinstance(e, F.CallExpr) and isinstance(e.func, F.IdentExpr):
            if e.func.name == "range":
                si = self._static_int(e.args[0]) if e.args else None
                ti = self._static_int(e.args[1]) if len(e.args) > 1 else None
                pi = self._static_int(e.args[2]) if len(e.args) > 2 else 1
                if si is not None and ti is not None and pi is not None \
                        and pi != 0:
                    if pi > 0:
                        return max(0, (ti - si + pi - 1) // pi)
                    return max(0, (si - ti + (-pi) - 1) // (-pi))
                return 64
            if e.func.name in ("list", "sorted", "set", "reversed"):
                return 64
        if isinstance(e, F.BinaryOp) and e.op in ("+", "|"):
            return self._blob_est(e.left) + self._blob_est(e.right)
        if isinstance(e, F.BinaryOp) and e.op in ("or", "and"):
            return max(self._blob_est(e.left), self._blob_est(e.right))
        if isinstance(e, F.IdentExpr):
            return 64
        return 64

    def _static_int(self, e):
        if isinstance(e, F.IntLiteral):
            return e.value
        if isinstance(e, F.UnaryOp) and e.op == "-" \
                and isinstance(e.operand, F.IntLiteral):
            return -e.operand.value
        return None

    def _emit_list_concat(self, left, right) -> None:
        """`a + b` as list-blob concat → base pointer in X0."""
        est = max(1, self._blob_est(left) + self._blob_est(right))
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(
                "list concat exceeds the formal frame "
                f"({self._list_cursor + 8} > {self._blob_cap} bytes)")
        cap = min(est, (avail - 8) // 8)
        if cap < 1:
            cap = 1
        self._emit_expr(left)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # left
        self._emit_expr(right)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # right, left
        # Nested emits above may have advanced the cursor — re-clamp.
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(
                "list concat exceeds the formal frame "
                f"({self._list_cursor + 8} > {self._blob_cap} bytes)")
        cap = min(est, (avail - 8) // 8)
        if cap < 1:
            cap = 1
        nbytes = 8 + 8 * cap
        offset = self._list_cursor
        self._list_cursor += nbytes
        # X0 = right ptr (top of stack); pop both into temps via loads.
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, 0))   # right
        self.asm.emit(encode_ldr_xt_xn_imm(7, 31, 16))  # left
        self.asm.emit(encode_ldp_sp_post(0, 31))        # drop right
        self.asm.emit(encode_ldp_sp_post(0, 31))        # drop left
        # counts
        self.asm.emit(encode_ldr_xt_xn_imm(2, 7, 0))    # nL
        self.asm.emit(encode_ldr_xt_xn_imm(3, 8, 0))    # nR
        self.asm.emit(encode_add_xd_xn_xm(4, 2, 3))     # n
        self._emit_list_base(offset)
        self.asm.emit(encode_str_xt_xn_imm(4, 9, 0))
        # copy left elements
        self.asm.emit(encode_movz_xd_imm(5, 0))         # i = 0
        self._while_counter += 1
        cl = f"{self.func_name}_lcl{self._while_counter}"
        cld = f"{self.func_name}_lcd{self._while_counter}"
        self.asm.label(cl)
        self.asm.emit(encode_cmp_xn_xm(5, 2))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(cld, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(0, 7, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 5))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))
        self._emit_list_base(offset)
        self.asm.emit(encode_add_xd_xn_imm(6, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(6, 6, 5))
        self.asm.emit(encode_str_xt_xn_imm(0, 6, 0))
        self.asm.emit(encode_add_xd_xn_imm(5, 5, 1))
        self._emit_b_to(cl)
        self.asm.label(cld)
        # copy right elements at nL+i
        self.asm.emit(encode_movz_xd_imm(5, 0))         # j = 0
        self._while_counter += 1
        cr = f"{self.func_name}_lcr{self._while_counter}"
        crd = f"{self.func_name}_lrd{self._while_counter}"
        self.asm.label(cr)
        self.asm.emit(encode_cmp_xn_xm(5, 3))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(crd, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(0, 8, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 5))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))
        self._emit_list_base(offset)
        self.asm.emit(encode_add_xd_xn_imm(6, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm(6, 6, 2))     # + nL
        self.asm.emit(encode_add_xd_xn_xm_lsl3(6, 6, 5))
        self.asm.emit(encode_str_xt_xn_imm(0, 6, 0))
        self.asm.emit(encode_add_xd_xn_imm(5, 5, 1))
        self._emit_b_to(cr)
        self.asm.label(crd)
        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_set_union(self, left, right) -> None:
        """`a | b` as set union over list blobs (right deduped into left
        copy). Result is a fresh list blob of unique elements in X0."""
        # Build via concat then… for sweep purposes concat is enough to
        # compile; full dedup would need a membership scan per element.
        # Dedup: append left as-is, then for each right elem scan result.
        est = max(1, self._blob_est(left) + self._blob_est(right))
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(
                "set union exceeds the formal frame "
                f"({self._list_cursor + 8} > {self._blob_cap} bytes)")
        cap = min(est, (avail - 8) // 8)
        if cap < 1:
            cap = 1
        self._emit_expr(left)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # left
        self._emit_expr(right)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # right, left
        # Nested emits above may have advanced the cursor — re-clamp.
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(
                "set union exceeds the formal frame "
                f"({self._list_cursor + 8} > {self._blob_cap} bytes)")
        cap = min(est, (avail - 8) // 8)
        if cap < 1:
            cap = 1
        nbytes = 8 + 8 * cap
        offset = self._list_cursor
        self._list_cursor += nbytes
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, 0))   # right
        self.asm.emit(encode_ldr_xt_xn_imm(7, 31, 16))  # left
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldr_xt_xn_imm(2, 7, 0))    # nL
        self.asm.emit(encode_ldr_xt_xn_imm(3, 8, 0))    # nR
        self.asm.emit(encode_add_xd_xn_xm(4, 2, 3))     # n (upper bound)
        self._emit_list_base(offset)
        self.asm.emit(encode_str_xt_xn_imm(4, 9, 0))
        # copy all of left into result[0..nL)
        self.asm.emit(encode_movz_xd_imm(5, 0))
        self._while_counter += 1
        ul = f"{self.func_name}_sul{self._while_counter}"
        uld = f"{self.func_name}_sud{self._while_counter}"
        self.asm.label(ul)
        self.asm.emit(encode_cmp_xn_xm(5, 2))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(uld, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(0, 7, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 5))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))
        self._emit_list_base(offset)
        self.asm.emit(encode_add_xd_xn_imm(6, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(6, 6, 5))
        self.asm.emit(encode_str_xt_xn_imm(0, 6, 0))
        self.asm.emit(encode_add_xd_xn_imm(5, 5, 1))
        self._emit_b_to(ul)
        self.asm.label(uld)
        # append right elements not already in result[0..count)
        # X2=nL, X3=nR, X5=j; result count reloaded each inner scan
        self.asm.emit(encode_movz_xd_imm(5, 0))         # j = 0
        self._while_counter += 1
        ur = f"{self.func_name}_sur{self._while_counter}"
        ur_next = f"{self.func_name}_sun{self._while_counter}"
        urd = f"{self.func_name}_srd{self._while_counter}"
        urs = f"{self.func_name}_sus{self._while_counter}"
        urd2 = f"{self.func_name}_su2{self._while_counter}"
        self.asm.label(ur)
        self.asm.emit(encode_cmp_xn_xm(5, 3))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(urd, here_offset=-4)     # j >= nR → done
        # elem = right[j]
        self.asm.emit(encode_add_xd_xn_imm(0, 8, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 5))
        self.asm.emit(encode_ldr_xt_xn_imm(6, 0, 0))     # X6 = elem
        # scan result[0..count)
        self._emit_list_base(offset)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))     # count
        self.asm.emit(encode_movz_xd_imm(0, 0))          # k = 0
        self.asm.label(urs)
        self.asm.emit(encode_cmp_xn_xm(0, 1))
        self.asm.emit(encode_cset_xd_cond(4, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 4))
        self.asm.emit_label_rel(urd2, here_offset=-4)    # not found → append
        self.asm.emit(encode_add_xd_xn_imm(4, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(4, 4, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(4, 4, 0))
        self.asm.emit(encode_cmp_xn_xm(4, 6))
        self.asm.emit(encode_cset_xd_cond(4, "eq"))
        self.asm.emit(encode_cbnz_xn(0, 4))
        self.asm.emit_label_rel(ur_next, here_offset=-4)  # found → next j
        self.asm.emit(encode_add_xd_xn_imm(0, 0, 1))
        self._emit_b_to(urs)
        self.asm.label(urd2)
        # append: result[count] = elem; count++
        self._emit_list_base(offset)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))
        self.asm.emit(encode_add_xd_xn_imm(4, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(4, 4, 1))
        self.asm.emit(encode_str_xt_xn_imm(6, 4, 0))
        self.asm.emit(encode_add_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 9, 0))
        self.asm.label(ur_next)
        self.asm.emit(encode_add_xd_xn_imm(5, 5, 1))
        self._emit_b_to(ur)
        self.asm.label(urd)
        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_str_membership(self, left, right: F.StringLiteral,
                             invert: bool) -> None:
        """`needle in 'haystack'` — byte or substring scan → 0/1 in X0.

        Both-literal short-circuits at compile time. Otherwise the needle
        is either an int byte (subscript/literal) or a string pointer; the
        haystack is the interned literal."""
        hay = right.value
        if isinstance(left, F.StringLiteral):
            found = left.value in hay if left.value else True
            result = (0 if found else 1) if not invert else (
                1 if found else 0)
            self.asm.emit(encode_movz_xd_imm(0, result))
            return
        label = self._intern_string(hay)
        self._if_counter += 1
        mid = self._if_counter
        fn = self.func_name
        str_needle = (
            isinstance(left, F.IdentExpr) and left.name in self._string_vars
        ) or (isinstance(left, F.MemberExpr)
              and _member_slot_key(left) in self._string_vars)
        # haystack address → X9 (does not clobber X0)
        self.asm.emit_adrp_add(9, label)
        if str_needle:
            # X0 = needle ptr. Push it; scan as substring.
            self._emit_expr(left)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            # nlen: walk needle until NUL → X2, needle base → X7
            self.asm.emit(encode_ldr_xt_xn_imm(7, 31, 0))
            self.asm.emit(encode_mov_zr_xn(1, 7))
            self._while_counter += 1
            nl = f"{fn}_sml{self._while_counter}"
            nd = f"{fn}_smd{self._while_counter}"
            self.asm.label(nl)
            self.asm.emit(encode_ldrb_wd_wn(2, 1, 0))
            self.asm.emit(encode_cmp_xn_imm(2, 0))
            self.asm.emit(encode_cset_xd_cond(3, "eq"))
            self.asm.emit(encode_cbnz_xn(0, 3))
            self.asm.emit_label_rel(nd, here_offset=-4)
            self.asm.emit(encode_add_xd_xn_imm(1, 1, 1))
            self._emit_b_to(nl)
            self.asm.label(nd)
            self.asm.emit(encode_sub_xd_xn_imm(2, 1, 7))  # nlen
            # empty needle → found
            self.asm.emit(encode_cmp_xn_imm(2, 0))
            self.asm.emit(encode_cset_xd_cond(0, "eq"))
            self._while_counter += 1
            found = f"{fn}_smf{self._while_counter}"
            notf = f"{fn}_smn{self._while_counter}"
            end = f"{fn}_smx{self._while_counter}"
            outloop = f"{fn}_smo{self._while_counter}"
            inloop = f"{fn}_smi{self._while_counter}"
            inok = f"{fn}_smk{self._while_counter}"
            self.asm.emit(encode_cbnz_xn(0, 0))
            self.asm.emit_label_rel(found, here_offset=-4)
            self.asm.emit(encode_movz_xd_imm(8, 0))       # i = 0
            self.asm.label(outloop)
            # hay[i] == 0 → not found
            self.asm.emit(encode_add_xd_xn_imm(0, 9, 0))
            self.asm.emit(encode_add_xd_xn_xm(0, 0, 8))
            self.asm.emit(encode_ldrb_wd_wn(2, 0, 0))
            self.asm.emit(encode_cmp_xn_imm(2, 0))
            self.asm.emit(encode_cset_xd_cond(3, "eq"))
            self.asm.emit(encode_cbnz_xn(0, 3))
            self.asm.emit_label_rel(notf, here_offset=-4)
            self.asm.emit(encode_movz_xd_imm(0, 0))       # b = 0
            self.asm.label(inloop)
            # b >= nlen → matched
            self.asm.emit(encode_cmp_xn_xm(0, 2))
            self.asm.emit(encode_cset_xd_cond(3, "ge"))
            self.asm.emit(encode_cbnz_xn(0, 3))
            self.asm.emit_label_rel(found, here_offset=-4)
            # compare hay[i+b] vs needle[b]
            self.asm.emit(encode_add_xd_xn_imm(4, 9, 0))
            self.asm.emit(encode_add_xd_xn_xm(4, 4, 8))  # + i
            self.asm.emit(encode_add_xd_xn_xm(4, 4, 0))  # + b
            self.asm.emit(encode_ldrb_wd_wn(5, 4, 0))
            self.asm.emit(encode_add_xd_xn_xm(4, 7, 0))  # needle[b]
            self.asm.emit(encode_ldrb_wd_wn(6, 4, 0))
            self.asm.emit(encode_cmp_xn_xm(5, 6))
            self.asm.emit(encode_cset_xd_cond(3, "ne"))
            self.asm.emit(encode_cbnz_xn(0, 3))
            self.asm.emit_label_rel(inok, here_offset=-4)  # match → next b
            self.asm.emit(encode_add_xd_xn_imm(0, 0, 1))
            self._emit_b_to(inloop)
            self.asm.label(inok)
            self.asm.emit(encode_add_xd_xn_imm(8, 8, 1))  # i++
            self._emit_b_to(outloop)
            self.asm.label(found)
            self.asm.emit(encode_ldp_sp_post(0, 1))
            self.asm.emit(encode_movz_xd_imm(0, 0 if invert else 1))
            self._emit_b_to(end)
            self.asm.label(notf)
            self.asm.emit(encode_ldp_sp_post(0, 1))
            self.asm.emit(encode_movz_xd_imm(0, 1 if invert else 0))
            self.asm.label(end)
            return
        # Byte needle: X0 = byte value. Mask, push, scan hay bytes.
        self._emit_expr(left)
        self.asm.emit(encode_and_xd_xn_imm(0, 0, 8))
        self.asm.emit(encode_stp_sp_pre(0, 2))
        self._while_counter += 1
        loop = f"{fn}_bml{self._while_counter}"
        hit = f"{fn}_bmf{self._while_counter}"
        miss = f"{fn}_bmn{self._while_counter}"
        end = f"{fn}_bmx{self._while_counter}"
        self.asm.label(loop)
        self.asm.emit(encode_ldrb_wd_wn(2, 9, 0))
        self.asm.emit(encode_cmp_xn_imm(2, 0))
        self.asm.emit(encode_cset_xd_cond(3, "eq"))
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(miss, here_offset=-4)
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))    # needle byte
        self.asm.emit(encode_cmp_xn_xm(0, 2))
        self.asm.emit(encode_cset_xd_cond(3, "eq"))
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(hit, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(9, 9, 1))
        self._emit_b_to(loop)
        self.asm.label(hit)
        self.asm.emit(encode_ldp_sp_post(0, 1))
        self.asm.emit(encode_movz_xd_imm(0, 0 if invert else 1))
        self._emit_b_to(end)
        self.asm.label(miss)
        self.asm.emit(encode_ldp_sp_post(0, 1))
        self.asm.emit(encode_movz_xd_imm(0, 1 if invert else 0))
        self.asm.label(end)

    def _emit_string_addr(self, reg: int, label: str) -> None:
        """X{reg} = address of interned string `label` (ADRP+ADD)."""
        self.asm.emit_adrp_add(reg, label)

    def _emit_range_list(self, rargs: list) -> None:
        """Materialize range(...) as a list blob [count][i0…] in X0.

        Static when start/stop/step are all int literals; otherwise a
        runtime loop with a frame-safe cap (overflow → exit(1))."""
        start_e, stop_e, step_e = self._range_info(rargs)
        si = self._static_int(start_e)
        ti = self._static_int(stop_e)
        pi = self._static_int(step_e)
        if si is not None and ti is not None and pi is not None:
            if pi == 0:
                raise CodegenError("range() step must not be zero")
            vals = []
            v = si
            if pi > 0:
                while v < ti:
                    vals.append(v)
                    v += pi
            else:
                while v > ti:
                    vals.append(v)
                    v += pi
            n = len(vals)
            size = 8 * (1 + n)
            if self._list_cursor + size > self._blob_cap:
                raise CodegenError(
                    f"range() literal exceeds the formal frame "
                    f"({self._list_cursor + size} > {self._blob_cap} bytes)")
            offset = self._list_cursor
            self._list_cursor += size
            self._emit_list_base(offset)
            self._emit_mov_imm("X10", n)
            self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
            for i, val in enumerate(vals):
                self._emit_mov_imm("X0", val)
                self._emit_list_base(offset)
                self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * (i + 1)))
            self.asm.emit(encode_mov_zr_xn(0, 9))
            return
        # Dynamic: evaluate start/stop/step onto stack, loop, append.
        self._emit_expr(start_e)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # start
        self._emit_expr(stop_e)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # stop, start
        self._emit_expr(step_e)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # step, stop, start
        elem_cap = max(1, min(
            256, (self._blob_cap - self._list_cursor - 8) // 8))
        nbytes = 8 + 8 * elem_cap
        if self._list_cursor + nbytes > self._blob_cap:
            raise CodegenError(
                f"range() exceeds the formal frame "
                f"({self._list_cursor + nbytes} > {self._blob_cap} bytes)")
        offset = self._list_cursor
        self._list_cursor += nbytes
        self._emit_list_base(offset)
        self._emit_mov_imm("X10", 0)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
        # idx = start (X4), stop in X5, step in X6
        self.asm.emit(encode_ldr_xt_xn_imm(4, 31, 32))  # start
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 16))  # stop
        self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 0))   # step
        # step == 0 → exit(1)
        self.asm.emit(encode_cmp_xn_imm(6, 0))
        self.asm.emit(encode_cset_xd_cond(0, "eq"))
        self._while_counter += 1
        zstep = f"{self.func_name}_rsz{self._while_counter}"
        zok = f"{self.func_name}_rsk{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(zstep, here_offset=-4)
        self._emit_b_to(zok)
        self.asm.label(zstep)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(zok)
        # loop
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        start_label = f"{fn}_rl{wid}_start"
        step_label = f"{fn}_rl{wid}_step"
        end_label = f"{fn}_rl{wid}_end"
        oob = f"{fn}_rl{wid}_oob"
        oob_end = f"{fn}_rl{wid}_oe"
        # determine loop condition by step sign (runtime branch once)
        # We re-check each iteration: if step > 0 use lt, else gt.
        self.asm.label(start_label)
        self.asm.emit(encode_cmp_xn_imm(6, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))     # 1 if step < 0
        self._while_counter += 1
        neg = f"{fn}_rn{self._while_counter}"
        pos = f"{fn}_rp{self._while_counter}"
        after = f"{fn}_ra{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(neg, here_offset=-4)
        # step >= 0: continue while idx < stop
        self.asm.emit(encode_cmp_xn_xm(4, 5))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(after, here_offset=-4)
        self._emit_b_to(end_label)
        self.asm.label(neg)
        # step < 0: continue while idx > stop
        self.asm.emit(encode_cmp_xn_xm(4, 5))
        self.asm.emit(encode_cset_xd_cond(0, "gt"))
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(after, here_offset=-4)
        self._emit_b_to(end_label)
        self.asm.label(after)
        # append idx if count < elem_cap
        self._emit_list_base(offset)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))
        self.asm.emit(encode_cmp_xn_imm(1, elem_cap))
        self.asm.emit(encode_cset_xd_cond(0, "cs"))
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(oob, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(2, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(2, 2, 1))
        self.asm.emit(encode_str_xt_xn_imm(4, 2, 0))
        self.asm.emit(encode_add_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 9, 0))
        self.asm.label(step_label)
        self.asm.emit(encode_add_xd_xn_xm(4, 4, 6))     # idx += step
        self._emit_b_to(start_label)
        self.asm.label(end_label)
        # Drop step/stop/start BEFORE materialising the result. `ldp_sp_post`
        # writes X0 and X1, so computing the blob base into X0 first and
        # popping afterwards returned the loop's `start` (0 for range(n))
        # instead of the blob address. Every consumer of a range() value —
        # including the comprehension generator, which stores the address as
        # its loop bound and then does `ldr xN, [xBound]` — therefore read
        # through a null pointer and the program died with SIGSEGV, or
        # silently walked whatever was at address 0.
        self.asm.emit(encode_ldp_sp_post(0, 31))        # drop step/stop/start
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))
        self._emit_b_to(oob_end)
        self.asm.label(oob)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(oob_end)

    def _emit_del(self, stmt) -> None:
        """`del target…` — list index/slice remove, dict key shift-delete.

        Bare Ident/Member del is a no-op (no GC; SRA slots persist)."""
        for target in stmt.targets:
            if isinstance(target, (F.IdentExpr, F.MemberExpr)):
                continue
            if isinstance(target, F.SliceExpr):
                self._emit_del_slice(target)
                continue
                if isinstance(target, F.SubscriptExpr):
                    if self._is_dict_subscript(target.obj):
                        self._emit_del_dict_key(target)
                        continue
                    if isinstance(target.index, F.SliceExpr):
                        self._emit_del_slice_index(target)
                        continue
                    if self._is_string_subscript(target.obj):
                        raise CodegenError(
                            "del on a string index is not supported on the "
                            "formal arm64 path")
                    self._emit_del_list_index(target)
                    continue
                # Dict/list slot behind a bare MemberExpr base is handled
                # above via _member_slot_key; unknown shapes fall through.
                raise CodegenError(
                    f"unsupported del target on the formal arm64 path "
                    f"(got {type(target).__name__})")

    def _emit_del_list_index(self, target) -> None:
        """`del lst[i]` / `del obj.attr[i]` — shift left, count-- (OOB → exit).

        Base may be IdentExpr or an IdentExpr-rooted MemberExpr (SRA slot);
        evaluated once via `_emit_expr` into X10 after the bounds-checked
        element address is pushed."""
        if not isinstance(target.obj, (F.IdentExpr, F.MemberExpr)):
            raise CodegenError(
                "del on a non-name list is not supported on the formal "
                "arm64 path")
        self._emit_subscript_addr(target)   # X0 = &elem (bounds-checked)
        self.asm.emit(encode_stp_sp_pre(0, 2))  # elem addr
        self._emit_expr(target.obj)
        self.asm.emit(encode_mov_zr_xn(10, 0))  # X10 = base
        self.asm.emit(encode_ldr_xt_xn_imm(1, 10, 0))  # count
        # i = (elem - (base+8)) / 8
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))  # elem addr
        self.asm.emit(encode_add_xd_xn_imm(2, 10, 8))
        self.asm.emit(encode_sub_xd_xn_xm(0, 0, 2))
        self.asm.emit(encode_lsr_xd_xn_imm(0, 0, 3))
        # shift elements [i+1, count) → [i, count-1)
        self.asm.emit(encode_add_xd_xn_imm(3, 0, 1))  # j = i+1
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        loop = f"{fn}_dls{wid}"
        endl = f"{fn}_dle{wid}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_xm(3, 1))
        self.asm.emit(encode_cset_xd_cond(4, "ge"))
        self.asm.emit(encode_cbz_xn(0, 4))
        self.asm.emit_label_rel(endl, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(5, 10, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(5, 5, 3))
        self.asm.emit(encode_ldr_xt_xn_imm(6, 5, 0))
        self.asm.emit(encode_sub_xd_xn_imm(5, 5, 8))
        self.asm.emit(encode_str_xt_xn_imm(6, 5, 0))
        self.asm.emit(encode_add_xd_xn_imm(3, 3, 1))
        self._emit_b_to(loop)
        self.asm.label(endl)
        self.asm.emit(encode_sub_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 10, 0))
        self.asm.emit(encode_ldp_sp_post(0, 1))

    def _emit_del_dict_key(self, target) -> None:
        """`del d[k]` / `del obj.d[k]` — shift-delete; missing → exit(1)."""
        if not isinstance(target.obj, (F.IdentExpr, F.MemberExpr)):
            raise CodegenError(
                "del on a non-name dict is not supported on the formal "
                "arm64 path")
        base_name = (target.obj.name if isinstance(target.obj, F.IdentExpr)
                     else _member_slot_key(target.obj))
        if base_name is None:
            raise CodegenError(
                "del on a non-name dict is not supported on the formal "
                "arm64 path")
        self._emit_expr(target.index)
        self.asm.emit(encode_stp_sp_pre(0, 2))  # key
        self._load_var(base_name, 9)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 9, 0))  # count
        self.asm.emit(encode_movz_xd_imm(2, 0))       # i = 0
        self._if_counter += 1
        sid = self._if_counter
        fn = self.func_name
        loop = f"{fn}_ddk{sid}"
        miss = f"{fn}_ddm{sid}"
        found = f"{fn}_ddf{sid}"
        shift = f"{fn}_dds{sid}"
        shd = f"{fn}_ddd{sid}"
        end = f"{fn}_dde{sid}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_xm(2, 1))
        self.asm.emit(encode_cset_xd_cond(3, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(miss, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(4, 9, 8))
        self.asm.emit(encode_add_xd_xn_imm(5, 2, 0))
        self.asm.emit(encode_add_xd_xn_xm_lsl4(4, 4, 5))
        self.asm.emit(encode_ldr_xt_xn_imm(4, 4, 0))  # pair key
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))  # want key
        self.asm.emit(encode_cmp_xn_xm(4, 5))
        self.asm.emit(encode_cset_xd_cond(4, "eq"))
        self.asm.emit(encode_cbnz_xn(0, 4))
        self.asm.emit_label_rel(found, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(2, 2, 1))
        self._emit_b_to(loop)
        self.asm.label(found)
        # shift pairs [i+1, count) → [i, count-1); count--
        self.asm.emit(encode_add_xd_xn_imm(2, 2, 1))  # j = i+1
        self.asm.label(shift)
        self.asm.emit(encode_cmp_xn_xm(2, 1))
        self.asm.emit(encode_cset_xd_cond(3, "ge"))
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(shd, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(4, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl4(4, 4, 2))
        self.asm.emit(encode_ldr_xt_xn_imm(5, 4, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(6, 4, 8))
        self.asm.emit(encode_sub_xd_xn_imm(4, 4, 16))
        self.asm.emit(encode_str_xt_xn_imm(5, 4, 0))
        self.asm.emit(encode_str_xt_xn_imm(6, 4, 8))
        self.asm.emit(encode_add_xd_xn_imm(2, 2, 1))
        self._emit_b_to(shift)
        self.asm.label(shd)
        self.asm.emit(encode_sub_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 1))
        self._emit_b_to(end)
        self.asm.label(miss)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(end)

    def _emit_del_slice(self, target) -> None:
        """`del obj[a:b]` bare SliceExpr — range remove on a list name/slot."""
        if not isinstance(target.obj, (F.IdentExpr, F.MemberExpr)):
            raise CodegenError(
                "del slice on a non-name list is not supported on the "
                "formal arm64 path")
        key = (target.obj.name if isinstance(target.obj, F.IdentExpr)
               else _member_slot_key(target.obj))
        if key is None:
            raise CodegenError(
                "del slice on a non-name list is not supported on the "
                "formal arm64 path")
        self._emit_del_list_range(key, target.start, target.stop,
                                  target.step)

    def _emit_del_slice_index(self, target) -> None:
        """`del obj[i:j]` SubscriptExpr with SliceExpr index."""
        sl = target.index
        if sl.step is not None:
            raise CodegenError(
                "del slice with step is not supported on the formal arm64 "
                "path")
        if not isinstance(target.obj, (F.IdentExpr, F.MemberExpr)):
            raise CodegenError(
                "del slice on a non-name list is not supported on the "
                "formal arm64 path")
        key = (target.obj.name if isinstance(target.obj, F.IdentExpr)
               else _member_slot_key(target.obj))
        if key is None:
            raise CodegenError(
                "del slice on a non-name list is not supported on the "
                "formal arm64 path")
        self._emit_del_list_range(key, sl.start, sl.stop, None)

    def _emit_del_list_range(self, name: str, start, stop, step) -> None:
        """Remove [start, stop) from list `name` (memmove tail + count).

        Bounds are Python-normalized (negative → +count; stop clamped to
        [start, count]). start >= stop is a no-op. Callers reject step."""
        if step is not None:
            raise CodegenError(
                "del slice with step is not supported on the formal arm64 "
                "path")
        self._load_var(name, 10)                       # X10 = base
        self.asm.emit(encode_ldr_xt_xn_imm(1, 10, 0))  # X1 = count
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        # --- start index → X2 ---
        if start is None:
            self.asm.emit(encode_movz_xd_imm(2, 0))
        else:
            self._emit_expr_to(start, "X2")
            self.asm.emit(encode_cmp_xn_imm(2, 0))
            self.asm.emit(encode_cset_xd_cond(3, "lt"))
            self.asm.emit(encode_cbnz_xn(0, 3))
            self.asm.emit(encode_b(0))
            self.asm.emit_label_rel(f"{fn}_drn{wid}", here_offset=-4)
            self.asm.emit(encode_add_xd_xn_xm(2, 2, 1))  # start += count
            self.asm.emit(encode_b(0))
            self.asm.emit_label_rel(f"{fn}_drc{wid}", here_offset=-4)
            self.asm.label(f"{fn}_drn{wid}")
            self.asm.emit(encode_movz_xd_imm(2, 0))       # negative → 0
            self.asm.label(f"{fn}_drc{wid}")
        # --- stop index → X4 ---
        if stop is None:
            self.asm.emit(encode_mov_zr_xn(4, 1))
        else:
            self._emit_expr_to(stop, "X4")
            self.asm.emit(encode_cmp_xn_imm(4, 0))
            self.asm.emit(encode_cset_xd_cond(3, "lt"))
            self.asm.emit(encode_cbnz_xn(0, 3))
            self.asm.emit(encode_b(0))
            self.asm.emit_label_rel(f"{fn}_dro{wid}", here_offset=-4)
            self.asm.emit(encode_add_xd_xn_xm(4, 4, 1))  # stop += count
            self.asm.emit(encode_b(0))
            self.asm.emit_label_rel(f"{fn}_drp{wid}", here_offset=-4)
            self.asm.label(f"{fn}_dro{wid}")
            self.asm.emit(encode_movz_xd_imm(4, 0))       # negative → 0
            self.asm.label(f"{fn}_drp{wid}")
        # stop = min(stop, count)
        self.asm.emit(encode_cmp_xn_xm(4, 1))
        self.asm.emit(encode_cset_xd_cond(3, "hi"))
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(f"{fn}_dru{wid}", here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(4, 1))
        self.asm.label(f"{fn}_dru{wid}")
        # stop = max(stop, start)  (empty when stop <= start)
        self.asm.emit(encode_cmp_xn_xm(4, 2))
        self.asm.emit(encode_cset_xd_cond(3, "lt"))
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(f"{fn}_drv{wid}", here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(4, 2))
        self.asm.label(f"{fn}_drv{wid}")
        # n_del = stop - start; if 0 → done
        self.asm.emit(encode_sub_xd_xn_xm(5, 4, 2))
        self.asm.emit(encode_cmp_xn_imm(5, 0))
        self.asm.emit(encode_cset_xd_cond(3, "eq"))
        self._while_counter += 1
        dskip = f"{fn}_drs{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(dskip, here_offset=-4)
        # copy [stop, count) → [start, start + (count - stop))
        self.asm.emit(encode_mov_zr_xn(6, 4))             # j = stop
        self._while_counter += 1
        mloop = f"{fn}_drm{self._while_counter}"
        mend = f"{fn}_dre{self._while_counter}"
        self.asm.label(mloop)
        self.asm.emit(encode_cmp_xn_xm(6, 1))
        self.asm.emit(encode_cset_xd_cond(3, "ge"))
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(mend, here_offset=-4)
        self.asm.emit(encode_sub_xd_xn_xm(7, 6, 4))       # j - stop
        self.asm.emit(encode_add_xd_xn_xm(7, 7, 2))       # + start
        self.asm.emit(encode_add_xd_xn_imm(0, 10, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 6))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))
        self.asm.emit(encode_add_xd_xn_imm(8, 10, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(8, 8, 7))
        self.asm.emit(encode_str_xt_xn_imm(0, 8, 0))
        self.asm.emit(encode_add_xd_xn_imm(6, 6, 1))
        self._emit_b_to(mloop)
        self.asm.label(mend)
        self.asm.emit(encode_sub_xd_xn_xm(1, 1, 5))       # count -= n_del
        self.asm.emit(encode_str_xt_xn_imm(1, 10, 0))
        self.asm.label(dskip)


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
