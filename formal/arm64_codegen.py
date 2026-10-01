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
                          parse_type_name, _range_args, TYPE_NAMES,
                          STRING_TYPE_NAMES)

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


# The ONE CodegenError both backends raise (formal/model.py), bound here under
# the name this module has always used. It used to be a class defined right
# here, and defining a second one with the same name is not a harmless
# duplicate: every consumer catches the refusal by class identity, so the
# x86-64 backend's copy was a class nobody caught and its refusals escaped
# `fire.py` as raw tracebacks instead of diagnostics.
CodegenError = M.CodegenError

_CALLEE_SAVED = [19, 20, 21, 22, 23, 24, 25, 26, 27, 28]

# How many arguments AAPCS passes in registers: X0..X7. Named once and used by
# BOTH ends of the convention (the callee's prologue and `_emit_call`), because
# the two are one fact and a program that is refused at one end and silently
# truncated at the other is the bug this constant exists to prevent.
#
# The x86-64 backend has its own (`ARG_REGS`, six of them) for the same reason:
# the limit is the platform's, not the language's, and it belongs in the
# backend. What is NOT the backend's is what to do past the limit, and both
# refuse.
_ABI_ARG_REGS = 8

# The local a frame-returning function keeps the CALLER'S block address in.
# A name rather than a dedicated register, so the word goes through the same
# register-or-spill-slot home every other local has; the leading underscores
# keep it out of any name the source can spell, and the reason it is not one of
# those is the same reason `_SCRATCH` is a constant: a source that binds this
# name must not be able to reach the convention's own state.
_SRET_LOCAL = "__sret_block"


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
    `_lbn_locally_bound_names` uses. Formal only adds MemberExpr field-slot
    keys on top (scalar replacement; backend-specific, not middle-end)."""
    names = bound_names_in_order(f.body, f.params)
    # A name the function declares `global` is NOT a local of it, whatever the
    # assignment walk said: `global G; G = G + 1` assigns G, so the walk reports
    # it bound, and giving it a register here would make the function keep TWO
    # homes for one word — a register, which the emitter would read back as the
    # current value, and the `__DATA` slot, which is where the module's value
    # lives. Which one a read picked would decide the program's answer, and the
    # two architectures would not have to pick the same one.
    module_globals = M.global_names_bound_in(f)
    if module_globals:
        names = [n for n in names if n not in module_globals]
    seen = set(names)

    # `h.x` for a frame receiver is a SLOT IN MEMORY, not a local: the value
    # lives at `[h, #8k]` and is loaded by `_load_var`. Allocating a register
    # for it would waste one of the ten callee-saved registers on a name nothing
    # ever stores, and push every other local one step closer to a spill slot.
    frame_slots = getattr(f, "_frame_slots", None) or {}
    frame_holders = getattr(f, "_frame_holders", None) or set()

    def add(name):
        # A chain DEEPER than a frame slot gets no register home either. It is
        # a field of a field, which the build pass refuses and `_emit_expr`
        # refuses again; giving it a register would mean a relaxed refusal
        # turned into a MOV of a register nothing ever wrote, which is quieter
        # than the crash it replaced. The cost of excluding it is one callee-
        # saved register, which is the cheaper of the two mistakes.
        if isinstance(name, str) and name not in seen \
                and name not in frame_slots \
                and not ("." in name
                         and name.split(".", 1)[0] in frame_holders):
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


def _walk_ast(node):
    """Every AST node reachable from `node`, not descending into a nested
    function's body.

    A nested `def` has its own locals, so a whole-function property (what a
    name holds, how many times a list is appended to) must not pick up the
    names inside one. The nested FunctionDef node itself IS yielded, so a
    caller that cares about it still sees it."""
    if isinstance(node, list):
        for x in node:
            yield from _walk_ast(x)
        return
    if not hasattr(node, "__dataclass_fields__"):
        return
    if isinstance(node, F.FunctionDef):
        yield node
        return
    yield node
    for fname in node.__dataclass_fields__:
        if fname in ("line", "col"):
            continue
        yield from _walk_ast(getattr(node, fname))


def _walk_value_methods(fn):
    """(node, receiver, method, args) for every `recv.method(...)` in `fn`.

    The receiver is the MemberExpr's object as written, so a caller can tell a
    plain local (`items` in `items.append(4)`) from a module path (`os` in
    `os.path.join`) without having to re-derive the chain."""
    for node in _walk_ast(getattr(fn, "body", None) or []):
        if (isinstance(node, F.CallExpr)
                and isinstance(node.func, F.MemberExpr)):
            yield (node, node.func.obj, node.func.member, list(node.args))


def _list_literals_bound_to(fn, name: str) -> list:
    """Every ListExpr in `fn` that assigns to `name` (directly or by tuple)."""
    out = []
    for node in _walk_ast(getattr(fn, "body", None) or []):
        if isinstance(node, F.AssignStmt) and _binds_name(node.target, name) \
                and isinstance(node.value, F.ListExpr):
            out.append(node.value)
        elif isinstance(node, F.VarDecl) and node.name == name \
                and isinstance(node.value, F.ListExpr):
            out.append(node.value)
    return out


def _binds_name(target, name: str) -> bool:
    """Whether an assignment target introduces the local `name`."""
    if isinstance(target, F.IdentExpr):
        return target.name == name
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        return any(_binds_name(el, name) for el in target.elements)
    if isinstance(target, str):
        return name in _lbn_target_names(target)
    return False


def _dotted(func) -> str:
    """`recv.method` as written, for a diagnostic that quotes the source."""
    name = _callee_symbol(func)
    return name if name else type(func).__name__


def _emit_add_imm(asm, xd: int, xn: int, imm: int) -> None:
    """ADD Xd, Xn, #imm, using the shifted form where it fits."""
    if imm >= 0:
        _emit_imm_shift12(asm, xd, xn, imm, encode_add_xd_xn_imm,
                          encode_add_xd_xn_imm_sh)
    else:
        _emit_imm_shift12(asm, xd, xn, -imm, encode_sub_xd_xn_imm,
                          encode_sub_xd_xn_imm_sh)


def _emit_imm_shift12(asm, xd, xn, imm, enc_plain, enc_shift) -> None:
    """Materialise `imm` into Xd with as few ADD/SUB immediates as possible.

    The instruction has a 12-bit immediate field and a shift that scales it by
    4096, so almost every large constant is ONE instruction with `sh` set
    rather than a chain. The frame scratch here is 131072 = 32 << 12, and this
    runs at the top of every list base, dict, comprehension and container
    append — the chunked version spent 33 instructions on it each time, in a
    function that had no other reason to be large.

    Two instructions cover everything that fits: the low 12 bits plainly, then
    the remainder shifted. Only beyond 2^24 does it fall back to chunking.
    """
    if imm < 0:
        imm = -imm
    if imm <= 0xFFF:
        asm.emit(enc_plain(xd, xn, imm))
        return
    if (imm & 0xFFF) == 0 and (imm >> 12) <= 0xFFF:
        asm.emit(enc_shift(xd, xn, imm >> 12, 1))
        return
    low = imm & 0xFFF
    high = imm >> 12
    if high <= 0xFFF:
        asm.emit(enc_plain(xd, xn, low))
        asm.emit(enc_shift(xd, xd, high, 1))
        return
    while imm > 0:
        chunk = min(imm, 0xFFF)
        asm.emit(enc_plain(xd, xn, chunk))
        imm -= chunk


def _emit_sub_imm(asm, xd: int, xn: int, imm: int) -> None:
    """SUB Xd, Xn, #imm, using the shifted form where it fits."""
    if imm >= 0:
        _emit_imm_shift12(asm, xd, xn, imm, encode_sub_xd_xn_imm,
                          encode_sub_xd_xn_imm_sh)
    else:
        _emit_imm_shift12(asm, xd, xn, -imm, encode_add_xd_xn_imm,
                          encode_add_xd_xn_imm_sh)


class ARM64Codegen:
    """ARM64 code generator over the fire_compiler AST."""

    def __init__(self, test_input: int = 10, dylib_syms: dict = None,
                 comptime_hook=None, module_source: str = "",
                 dylib_exports: list = None, globals_base: int = None):
        self.test_input = test_input
        # Where this unit's module-global data segment is MAPPED. A parameter
        # and not a lookup, because it differs per container (macho_linker and
        # elf define separate constants) and because every slot access has to be
        # computed against it BEFORE the image exists. None means "this unit has
        # no module globals", which is the ordinary case.
        self._globals_base = globals_base
        self.asm = Assembler()
        self._functions = {}
        self._structs: dict = {}
        self._current_function = None
        self._cur_fn = None
        self._if_counter = 0
        self._while_counter = 0
        self._assert_counter = 0
        self._tup_counter = 0
        # Per-image counter for the lazy module-global initializer's skip
        # label; unique per function because the assembler's labels are.
        self._gi_counter = 0
        self._fn_local_names: set = set()
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
        # ── A multi-field receiver, BY REFERENCE ──────────────────────────
        # `_frame_sites` is this function's `{id(call): (struct, offset)}` from
        # `model.struct_constructor_sites`: one reserved frame per constructor
        # call SITE, laid out in walk order, all of it BELOW the ordinary frame
        # (and therefore below SP) so that a method's write to its receiver
        # provably cannot reach the caller's window — which is what
        # `ProofLib.Frame.frameWrite_read_above_sp` says, and why the
        # reservation is in the prologue rather than handed out by a bump
        # cursor as the body is walked. `_frame_recv_bytes` is their total and
        # is added to the prologue's SP reservation. `_frame_slots` is
        # `formal/build.py`'s `{f"{holder}.{field}": slot}` for this function,
        # consulted by `_load_var`/`_store_var` to turn what would have been a
        # local load into `LDR Xt, [Xh, #8k]`. Both reset per function.
        self._frame_sites: dict = {}
        self._frame_recv_bytes = 0
        self._frame_slots: dict = {}
        # `{"h.a.b": slot}` — a NESTED frame read, which is two loads
        # and therefore not something `_frame_slots` can express.
        self._frame_nested_slots: dict = {}
        # The NAMES in this function that hold a frame address, as opposed to
        # the slot table above. Kept because the two answer different
        # questions: `_frame_slots` says which `h.f` is a load, and the holder
        # set says which `h` is a frame at all — which is what tells a
        # `h.f.g` chain (a field of a field, no layout) from an ordinary
        # `a.b.c` member path (scalar replacement, a local). Reset per function.
        self._frame_holders: set = set()
        self._frame_base = 0
        # ── A frame that COMES BACK from a callee ────────────────────────
        # `_ret_frame_sites` is this function's `{id(call): (struct, offset,
        # bytes)}` from `model.struct_returned_frame_sites`: one reserved
        # block per call site of a function that returns a frame, at
        # `_ret_frame_base` and above, and the same region the constructor
        # frames use because a returned block has the same lifetime a local
        # one has.  `_returns_frame` is the struct THIS function returns, and
        # `_image_returns_frame` the whole image's table, which is what
        # `_emit_call` asks to decide whether a call site needs a block.
        self._ret_frame_sites: dict = {}
        self._ret_frame_base = 0
        self._ret_frame_bytes = 0
        self._returns_frame = None
        self._image_returns_frame: dict = {}
        self._entry_name = None
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
        # Names bound to a FILE DESCRIPTOR this function (the result of the
        # lowered `open`, or an alias of one). `write`/`close` lower to the C
        # library's `write(2)`/`close(2)`, so the receiver has to be one, and
        # `open(2)` is the only thing on this path that produces one — see
        # model.VALUE_METHOD_RECEIVERS for what went wrong without this.
        # Reset per function, like the sets above: a descriptor opened in one
        # function is not one in the next.
        self._fd_vars = set()
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
        # The same libraries' MANIFEST export entries, in the same order
        # `_dylib_syms` was built in, indexed the way `model.dylib_export_tables`
        # indexes them: flat by bare name (so a bare callee resolves to the
        # entry `_dylib_syms` resolved it to, by construction rather than by a
        # second copy of the same precedence rule), by module identity (which is
        # what makes `mod.f(...)` — the spelling `import mod` binds — resolve),
        # and by module identity again for the names a module publishes by
        # RE-EXPORT rather than by definition. The entry carries the declared
        # signature, so a call's result can be classified instead of guessed.
        # One builder, both backends: the tables were two copies of the same
        # indexing, which is two places for them to disagree about which
        # library owns a name.
        # See `model.dylib_export_lookup`.
        (self._dylib_by_name, self._dylib_by_module,
         self._dylib_forwarded) = M.dylib_export_tables(dylib_exports)
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
        # The element width the subscript being emitted reads at, in bytes.
        # `_emit_subscript_addr` sets it on every path (a container element and
        # a dict value are 8, a string byte is 1, a declared pointee is its
        # own) and the caller that emits the load or the store reads it, so
        # the address computation and the instruction that uses it cannot
        # disagree. Defaulted here because a stale value from a previous
        # subscript in the same function would silently pick a width.
        self._sub_width = 8
        # {function name: model.ValueKinds}, for the whole module. `_functions`
        # is fixed for a compile, so a callee's answer is the same at every
        # call site and there is no reason to re-derive it per function.
        self._vkinds_cache: dict = {}
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
            functions = M.entry_function(functions)
        for f in functions:
            # async def and generators lower as ordinary functions: formal
            # has no event loop / iterator protocol, so `await` is identity
            # and `yield` leaves its value in X0 (compile-only fidelity).
            self._functions[f.name] = f

        self.asm.org(base_addr)

        first_func_name = functions[0].name
        self._entry_name = first_func_name if emit_startup else None
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
        # The whole image's `{function: struct}` table for the functions that
        # RETURN a frame, published by `formal/build.py`'s fixpoint.  It is
        # read twice and for two different questions: whether THIS function is
        # one (the callee half, below) and whether a call site in it is one
        # (the caller half, in `_emit_call`).  One table for both, because two
        # answers to "does callee F return a frame" is the disagreement that
        # makes a caller reserve a block the callee never writes.
        self._image_returns_frame = dict(
            getattr(f, "_image_returns_frame", None) or {})
        # The FUNCTION NODE, not just its name.  The pointer value model reads
        # a receiver's declared type from the function being emitted — a
        # parameter annotation, a `var p: Pointer[T]`, the bindings of a name —
        # and `_current_function` is a string, so it cannot answer any of those.
        self._cur_fn = f
        # This function's LOCAL names, which is what decides whether a bare
        # name is served from `__DATA` or from a register — see
        # `_module_global`. Built from the same shared allocation order the
        # registers come from, so the two cannot disagree.
        self._fn_local_names = set(_collect_var_names(f))
        self.asm.label(f.name)

        var_names = _allocation_order(f)
        # The RETURNED-FRAME convention, set up before the locals so that the
        # hidden word has a home of its own.  A function that returns a frame
        # address takes one extra trailing argument — the address of a block in
        # its CALLER's scratch — and `return <frame>` becomes "copy the block
        # to that word, return that word".  The word is kept in an ordinary
        # local's home rather than a dedicated register so that it goes
        # through `_load_var`/`_store_var` like every other value on this path:
        # a register of its own would be a second answer to "where does a
        # function keep a word", and the one that has to hold it is the same
        # answer for a spilled local and a register local.
        self._returns_frame = self._image_returns_frame.get(f.name)
        if self._returns_frame is not None and f.name == self._entry_name:
            # The ENTRY has no caller to reserve a block, so the convention has
            # nothing to hand it.  Refused here, where which function is the
            # entry is already known, and with the SHARED message so x86-64
            # says the same thing about the same program.
            raise CodegenError(M.entry_frame_return_refusal(f.name))
        if self._returns_frame is not None and getattr(
                f, "_frame_return_problems", None):
            # The build pass parked a returned-frame refusal for this function
            # and its entry points raise it after the imports resolve.  Reaching
            # an emitter with one still parked means this function was compiled
            # outside those entry points, and compiling it would emit a plain
            # address return on the paths that do not return a frame — the
            # silent wrong number the parked refusal exists to prevent.  The
            # SAME text either way, because it is the same parked message.
            raise CodegenError(f._frame_return_problems[0])
        if self._returns_frame is not None:
            var_names = list(var_names) + [_SRET_LOCAL]
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
        # Receiver frames for this function's multi-field structs. They live at
        # the BOTTOM of the same reserved scratch the list/dict blobs use, and
        # the blob cursor starts ABOVE them, which is the whole of the
        # placement argument:
        #
        #   * a callee's scratch begins below the caller's SP, so a callee's
        #     frames and a callee's blobs are both below every frame the
        #     CALLER owns — a method cannot overwrite the receiver it was
        #     handed, and two frames created by the same function are at
        #     different offsets and so cannot alias;
        #   * a blob created in the same function starts past the frames, so
        #     `self.items.append(1)` inside a method cannot scribble on the
        #     receiver it is appending to.
        #
        # `Refine.FrameOk`'s window is `SP + j` for `j >= 0`, so a frame at
        # `SP + k` is INSIDE it and a method that writes its receiver does not
        # satisfy `FrameOk` — which is why the callee contract for a method is
        # `Refine.FrameOk_except`, the predicate
        # `bugs/FORMAL_wide_receiver_by_reference.md` lands for exactly this.
        # The layout itself is `formal/model.py`'s, so the x86-64 backend
        # reserves the same bytes in the same order.
        self._frame_sites = M.struct_constructor_sites(f, self._structs)
        # The BLOCK size, not the frame size: a site whose struct has a
        # typed-nested field reserves that nested frame too, and the blob cursor
        # has to start above the lot or a blob would land on one.  Reading the
        # block from the shared model rather than summing frame bytes here is
        # what keeps the two backends reserving the same bytes in the same
        # order.
        self._frame_recv_bytes = sum(
            M.struct_frame_block_bytes(st, self._structs)
            for st, _off, _nested in self._frame_sites.values())
        # Blocks for frames this function RECEIVES from a callee that returns
        # one.  The same region as the constructor frames and the same reason:
        # a returned block has exactly the lifetime a local one has — both live
        # in the creating function's scratch and die with it — so it goes at the
        # bottom of the same reserved scratch and the blob cursor starts above
        # the lot.  The layout is the shared model's, so x86-64 reserves the
        # same bytes at the same offsets and a returned frame cannot be correct
        # on one machine and a use-after-free on the other.
        self._ret_frame_sites = M.struct_returned_frame_sites(
            f, self._structs, self._image_returns_frame.get)
        self._ret_frame_base = self._frame_recv_bytes
        self._ret_frame_bytes = sum(v[2] for v in self._ret_frame_sites.values())
        self._frame_slots = dict(getattr(f, "_frame_slots", None) or {})
        # `{"h.a.b": slot}` — a NESTED frame read, two loads rather than one,
        # and a separate table because a `_frame_slots` entry is one load and a
        # null in it is indistinguishable from "this field has no slot", which
        # is the disagreement `formal/build.py` exists to keep apart from
        # "this field is nested".
        self._frame_nested_slots = dict(
            getattr(f, "_frame_nested_slots", None) or {})
        self._frame_holders = set(getattr(f, "_frame_holders", None) or ())
        # `{holder name: [StructDef, …]}` — formal/build.py's recognition table,
        # published so a COPY construction can ask what the word it is handed
        # actually is.  A copy needs a base to copy from and the holder
        # analysis is the only thing in the compiler that can say a word is a
        # frame address, so the copy's decision and the emitter's come from the
        # same table rather than from two walkers that could disagree.
        self._frame_candidates = dict(
            getattr(f, "_frame_candidates", None) or {})
        # `{name: declared return annotation}` — the evidence a construction
        # argument needs to be told apart from a container returned by a
        # callee.  Read once per function from the same function table the
        # emitter already has, so the answer cannot differ from the one the
        # build pass reached.
        self._return_types = M.function_return_types(
            self._functions.values())

        self._call_types = {
            g.name: resolve(parse_type_name(g.return_type) or DEFAULT_INT_TYPE)
            for g in self._functions.values()
        }
        self._vtypes = function_var_types(f, self._call_types)
        self._pending_finally = []
        # The blob cursor starts ABOVE the receiver frames AND above the blocks
        # reserved for frames this function receives, not at the bottom of the
        # scratch: the frames live there (see above) and a blob must not land
        # on one.
        self._list_cursor = self._frame_recv_bytes + self._ret_frame_bytes
        self._for_list_depth = 0
        self._compr_depth = 0
        self._container_ctx = 0
        self._string_vars = set()
        self._dict_vars = set()
        # …seeded with the module globals this function mentions, because the
        # literal that says what they hold is in the MODULE's statement list and
        # `_note_binding` only ever sees this function's. Seeded BEFORE the body
        # is walked, and not instead of it: a name the function also binds is
        # still module-scoped until the local store, which is the same
        # order-dependent rule the local marks already implement.
        self._note_global_kinds(f)
        self._fd_vars = set()
        self._comptime_vals = {}
        self._comptime_list_asts = {}
        # What each local holds (see model.ValueKinds) and how much room each
        # list literal needs for `append`. Both are properties of the whole
        # function, so they are computed once here rather than guessed at each
        # use site: `_string_vars` above is the flow-sensitive half of the same
        # question, and the two are combined (never contradicted) in
        # _expr_str_kind.
        self._vkinds = self._scan_value_kinds(f)
        self._list_caps, self._list_caps_by_name = self._scan_list_caps(
            f, self._vkinds)

        # Prologue: save FP/LR, set FP, save callee-saved var regs, move each
        # incoming argument into ITS OWN callee-saved home (always arg0 into
        # X19, matching formal — even with 0 params), narrow-extend each to its
        # declared width, SUB SP frame.
        self.asm.emit(encode_stp_sp_pre(29, 30))
        self.asm.emit(encode_mov_zr_xn(29, 31))  # MOV X29, SP
        for i in range(self._npairs):
            self.asm.emit(encode_stp_sp_pre(19 + 2 * i, 20 + 2 * i))
        # The module-global initializer, LAZILY: a function that touches a
        # global checks a flag and fills the slots if they are not filled yet.
        # Placed here — after the frame is established and the callee-saved
        # registers are saved, before anything can read a slot — because the
        # prologue above is what makes X16/X17 available to it. See
        # `_emit_global_init` for why this is CODE and not a relocation, and
        # `model.initialization_is_lazy` for why it is not in the startup stub.
        if M.function_touches_globals(f):
            self._gi_counter += 1
            self._emit_global_init(skip_label=f"__gi_done_{self._gi_counter}")
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
        if len(incoming) > _ABI_ARG_REGS:
            # The other end of the same refusal. `_emit_call` catches a call
            # SITE with too many arguments, but a function can also be REACHED
            # without one — a dylib export, a reflection-resolved call, an
            # entry point the driver calls directly — and this used to answer
            # that by `break`ing out of the loop, which leaves every parameter
            # past the eighth with its home slot never written. The first read
            # of such a name then loaded whatever the slot held, so the value
            # was not merely wrong but BUILD-DEPENDENT. Refusing here means
            # the arity is rejected whichever way the function is entered.
            raise CodegenError(
                f"{f.name}: {len(incoming)} parameters exceeds the "
                f"{_ABI_ARG_REGS} the formal arm64 ABI passes in registers")
        for i, (pname, ptype) in enumerate(incoming):
            if i == 0:
                # Already in X19 by the unconditional save above, which also
                # keeps the no-parameter case (unknown-name reads fall back to
                # X19 and so still see the entry argument).
                if ptype is None:
                    continue     # a comptime parameter: already a full word
                self._emit_extend(19, 19,
                                  resolve(parse_type_name(ptype)
                                          or DEFAULT_INT_TYPE))
                continue
            # Past the 10 callee-saved registers a parameter's home is a spill
            # slot, and the incoming register is written there now or its first
            # read in the body would load whatever the slot happened to hold.
            # Unreachable until the returned-frame hidden word made an
            # eleventh local possible; see `_load_home_from_reg` for the bug
            # that was waiting there.
            self._load_home_from_reg(pname, i, ptype)
        # The RETURNED-FRAME hidden word, moved from the register the caller
        # passed it in to its home, in the same place and for the same reason
        # as the parameters above: every incoming argument is caller-saved, so
        # anything still in X0..X7 when the body starts is the CALLER's value
        # again.  It is a full word and NOT extended — it is an address, and
        # narrowing it would be a pointer into the low half of a stack.
        if self._returns_frame is not None:
            sret_arg = len(incoming)
            if sret_arg >= 8:
                raise CodegenError(
                    M.returned_frame_convention_refusal(f.name, sret_arg)
                    or f"{f.name} needs one hidden word for the caller's block "
                       f"and there is no argument register left for it")
            self._load_home_from_reg(_SRET_LOCAL, sret_arg)
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

        A FRAME SLOT is not a local at all: `name` is spelled `h.x`, `h` holds
        the address of `x`'s frame, and the value lives in memory at
        `[h, #8*slot]`.  Intercepted here rather than at every call site
        because every read of a field on this path — expression position,
        augmented assignment, a chained `a = b = …` — already funnels through
        this one function, so one branch here covers all of them and there is
        no second lowering to keep in step.

        A MODULE GLOBAL is also not a local, and for the sharper reason: its
        home has to outlive every frame, so it is in the image's `__DATA` and
        this is an ADRP/ADD to that address followed by a load. Intercepted
        here for the same reason as the frame slot, and for one more: the name
        is deliberately absent from `_var_regs`/`_var_spills` (see
        `_collect_var_names`), so this branch is the ONLY place it can be read
        from — there is no second home for a read to disagree with.

        A name in none of those tables has NO ADDRESS, and the two answers the
        old code gave it were the two answers the two architectures gave the
        same program: X19 (a callee-saved register holding whatever the caller
        left — measured, the `test_input` 10) and an immediate zero. So it
        refuses, with the name, and the build pass's `check_module_symbols` is
        the check that normally catches it first with a fuller story."""
        slot = self._frame_slots.get(name)
        if slot is not None:
            self._emit_frame_load(name, slot, dst)
            return
        gslot = self._module_global(name)
        if gslot is not None:
            self._emit_global_load(gslot, dst)
            return
        # A NESTED frame slot is TWO loads and is checked before the one-load
        # table, because the name is `h.a.b` and the one-load table keys on
        # `h.a`: with the order the other way round, `h.a.b` misses the nested
        # table, misses the one-load table (no such key), misses the register and
        # spill homes, and reads X19 — which is the wrong answer this whole
        # interception exists to prevent, arrived at by a missing entry rather
        # than by a refusal.
        nested = self._frame_nested_slots.get(name)
        if nested is not None:
            outer, _dot, _rest = name.rpartition(".")
            self._load_var(outer, 17)
            self.asm.emit(encode_ldr_xt_xn_imm(dst, 17, 8 * nested))
            return
        if name in self._var_regs:
            r = self._var_regs[name]
            if dst != r:
                self.asm.emit(encode_mov_zr_xn(dst, r))
            return
        if name in self._var_spills:
            off = self._spill_off(name)
            # `_spill_off` is the distance DOWN to the slot, so the
            # displacement is NEGATIVE. Passing the positive value here
            # addressed x29+off -- above the frame pointer, inside the
            # CALLER's frame -- and silently corrupted it. The unscaled form
            # takes a signed imm9, so it covers every offset from -8 to -256.
            if off <= 256:
                self.asm.emit(encode_ldur_xt_xn_imm(dst, 29, -off))
                return
            self.asm.emit(encode_mov_zr_xn(17, 29))
            _emit_sub_imm(self.asm, 17, 17, off)
            self.asm.emit(encode_ldr_xt_xn_imm(dst, 17, 0))
            return
        # A TYPE name read as a value is the FOURTH place a name's value comes
        # from, after the three above, and it is asked HERE — at the end, where
        # the X19 fall-through used to be — for two reasons. It is the only
        # reader of "does this name have a home" in the file, so putting the tag
        # anywhere earlier would mean a second one: measured, an arm in
        # `_emit_expr` before `_load_var` made `var Int = 7; printf("%d", Int)`
        # print the TAG of the type `Int` (-913451874) instead of the local's
        # 7, silently and on every such program. And a type has no home by
        # definition, so "no home" and "is a type" are not in competition here —
        # they are the same observation read twice.
        #
        # Asked of the shared model reader so this architecture and x86-64
        # cannot answer `t == Int32` differently, which for a tag is not a
        # diagnostic that differs but a comparison that comes out one way on one
        # side. `formal/build.py` places the name in a pre-pass, so a type
        # reaching here is a route that pass does not model, and the tag is
        # still the answer rather than the fall-through.
        tag = M.type_tag_for_name(name)
        if tag is not None:
            self._emit_mov_imm(f"X{dst}", tag)
            return
        raise CodegenError(self._no_home(name))

    def _emit_global_init(self, skip_label: str = None) -> None:
        """Fill every address-valued module-global slot, and set the flag.

        WHY CODE AND NOT A RELOCATION. The obvious mechanism is a relocation —
        dyld's classic `REBASE` opcode stream for Mach-O, `R_X86_64_RELATIVE` for
        ELF — and it is what the file-format documentation describes. It does not
        work on the target this backend actually runs on: measured on macOS 26,
        a well-formed `LC_DYLD_INFO_ONLY` rebase stream naming `__DATA` is parsed
        (a malformed one aborts at launch with "missing
        REBASE_OPCODE_SET_SEGMENT_AND_OFFSET_ULEB") and then SILENTLY NOT
        APPLIED — the slot still held the link-time address, and the first read
        through it was a segfault. A silent no-op relocation is the worst
        possible failure for this, because the image is well-formed by every
        check available.

        So the addresses are computed by the same instructions that already work
        here: ADRP/ADD is how a string literal's address reaches a register, and
        it is PC-relative, so it is correct under whatever slide dyld chose.

        `skip_label`, when given, is where control goes once the flag says the
        globals are already filled — the caller's lazy-init check branches there
        and the body of every function that touches a global ends up with one
        branch that is never taken after the first call.

        X16 and X17: the address being stored and the address of the slot. Both
        are the intra-procedure scratch registers, and neither holds anything
        across these instructions."""
        table = M.module_slots()
        base = self._globals_base
        if not table or base is None:
            if skip_label:
                self.asm.emit_label_rel(skip_label, here_offset=-4)
            return
        image = M.build_data_image(table, base)
        if skip_label:
            # CBNZ over the whole body — the flag is CLEAR (zero) until the
            # last store below, so the first call falls through and runs it and
            # every later call branches past it.
            self._adrp_add_abs(17, base + image.init_flag_offset)
            self.asm.emit(encode_ldr_xt_xn_imm(16, 17, 0))
            # Recorded AFTER the instruction is emitted, biased back over it —
            # the idiom every branch on this path uses, because the assembler
            # computes the position from the current length.
            self.asm.emit(encode_cbnz_xn(0, 16))
            self.asm.emit_label_rel(skip_label, here_offset=-4)
        for at, target in image.fixups:
            self._adrp_add_abs(16, base + target)
            self._adrp_add_abs(17, base + at)
            self.asm.emit(encode_str_xt_xn_imm(16, 17, 0))
        # A word holding a STRING, which is the same store with the other end
        # computed from a LABEL rather than from the data segment: the interned
        # literal is the one `char *` to these bytes on this path, so the word
        # has to be the address the rest of the program already uses for this
        # text. `emit_adrp_add` rather than `_adrp_add_abs` because that is the
        # addressing a string literal in an expression already uses, and the
        # equality of the two addresses is the whole point — see
        # `GlobalDataImage.string_cells`.
        for at, text in image.string_cells:
            self.asm.emit_adrp_add(16, self._intern_string(text))
            self._adrp_add_abs(17, base + at)
            self.asm.emit(encode_str_xt_xn_imm(16, 17, 0))
        if skip_label:
            # Set the flag LAST, after every store, so a slot is never observed
            # filled while another still holds its link-time address.
            self._adrp_add_abs(16, base + image.init_flag_offset)
            self._adrp_add_abs(17, base + image.init_flag_offset)
            self.asm.emit(encode_movz_xn_imm(16, 1))
            self.asm.emit(encode_str_xt_xn_imm(16, 17, 0))
            # `label`, not `emit_label_rel`: this DEFINES where the check above
            # branches to. Recording a relocation here would be a second branch
            # to a label nothing ever defines, which the assembler reports as
            # "Undefined label" at resolve time.
            self.asm.label(skip_label)

    def _global_slot_address(self, slot) -> None:
        """X17 = the address of a module-global's `__DATA` slot.

        ADRP brings the page and ADD the offset, the same pair the string
        literals use (`emit_adrp_add`), so the addressing is the one this
        backend already proves against a real dyld rather than a new one. X17
        because it is this function's existing scratch for spill addressing and
        is dead across the load that follows.

        The address is `globals_base() + 8 * slot.index`, and all three parts
        come from shared functions — `formal.build.globals_base` for the
        container's mapping base and `model.GLOBAL_SLOT_BYTES` for the stride,
        which is the same pair the image builder used to LAY the bytes out. Two
        independent computations of an address would be two answers to one
        question, and the linker writing one while the code reads the other is
        not a crash anyone can attribute."""
        addr = self._globals_base + M.GLOBAL_SLOT_BYTES * slot.index
        self._adrp_add_abs(17, addr)

    def _adrp_add_abs(self, reg: int, addr: int) -> None:
        """ADRP Xreg, page ; ADD Xreg, Xreg, #off, for an ABSOLUTE address.

        `emit_adrp_add` takes a LABEL and resolves it against the assembler's
        label table; a slot's address is not a label in the code, it is a
        constant in another segment, so it is encoded here directly. The page
        delta is measured from the instruction's own position, which the
        assembler knows — hence going through `emit_adrp_add` with a synthetic
        label would be one indirection for a number already known."""
        pos = self.asm._org + len(self.asm.sections["text"])
        page_delta = ((addr & ~0xFFF) - (pos & ~0xFFF)) // 4096
        immlo = page_delta & 3
        immhi = (page_delta >> 2) & 0x7FFFF
        self.asm.emit(struct.pack("<I", 0x90000000 | (immlo << 29)
                                  | (immhi << 5) | reg))
        self.asm.emit(struct.pack("<I", 0x91000000 | ((addr & 0xFFF) << 10)
                                  | (reg << 5) | reg))

    def _emit_global_load(self, slot, dst: int) -> None:
        """Xdst = a module-global's value — one load from its `__DATA` slot."""
        self._global_slot_address(slot)
        self.asm.emit(encode_ldr_xt_xn_imm(dst, 17, 0))

    def _emit_global_store(self, slot, src: int) -> None:
        """A module-global's value = Xsrc — one store to its `__DATA` slot.

        The address goes into X17 and the value has to be somewhere else, so a
        store whose value is already in X17 parks it in X16 first. X16 is the
        IP0/intra-procedure-call scratch on AAPCS and holds nothing across these
        two instructions on this path, which is the same reason `_emit_frame_store`
        uses it."""
        if src == 17:
            self.asm.emit(encode_mov_zr_xn(16, src))
            src = 16
        self._global_slot_address(slot)
        self.asm.emit(encode_str_xt_xn_imm(src, 17, 0))

    def _emit_frame_load(self, name: str, slot: int, dst: int) -> None:
        """`LDR Xdst, [Xholder, #8*slot]` — a receiver field read.

        The holder's ADDRESS is loaded first, into X17.  X17 rather than a
        fresh register because it is already this function's scratch for spill
        addressing and is dead across the single instruction that follows, and
        because a holder is an ordinary local — a register home or a spill slot
        — so `_load_var` on it is exactly the ordinary path."""
        holder = name.rsplit(".", 1)[0]
        self._load_var(holder, 17)
        self.asm.emit(encode_ldr_xt_xn_imm(dst, 17, 8 * slot))

    def _emit_frame_store(self, name: str, slot: int, src: int) -> None:
        """`STR Xsrc, [Xholder, #8*slot]` — a receiver field write.

        The write half of the pair above, and the reason a method's effect is
        visible to its caller: the caller's local holds the SAME address, so
        the store lands in the frame the caller will read back."""
        holder = name.rsplit(".", 1)[0]
        if src == 17:
            # The value is in the scratch the address wants. Park it in a
            # caller-saved register that holds nothing across these two
            # instructions (X16 is the IP/caller-saved intra-procedure slot on
            # AAPCS and is dead everywhere on this path).
            self.asm.emit(encode_mov_zr_xn(16, src))
            src = 16
        self._load_var(holder, 17)
        self.asm.emit(encode_str_xt_xn_imm(src, 17, 8 * slot))

    def _module_global(self, name: str):
        """The `__DATA` slot that holds `name` in the function being EMITTED.

        The decision and the words are `model.module_slot_for`'s, shared with
        the x86-64 emitter: two spellings of CPython's scoping rule in two
        backends is two places for one language implementation to disagree about
        where a word lives."""
        return M.module_slot_for(name, self._fn_local_names)


    def _store_var(self, name: str, src: int) -> None:
        """local `name` = src. Register homes MOV; spill slots STR via X17.

        A frame slot is a store into the receiver's frame — see
        `_emit_frame_store` and `_load_var` above for why the branch is here
        rather than at the call sites. A module global is a store into the
        image's `__DATA`, for the same reason and with the same single-home
        argument: the name was kept out of this function's registers, so this
        is the only place the store can land."""
        slot = self._frame_slots.get(name)
        if slot is not None:
            self._emit_frame_store(name, slot, src)
            return
        gslot = self._module_global(name)
        if gslot is not None:
            self._emit_global_store(gslot, src)
            return
        # A NESTED frame slot, and the same two-step as `_load_var`: the OUTER
        # load gives the nested frame's base and the store lands in the nested
        # frame's own slot.  Checked before the register and spill homes for the
        # reason given in `_load_var` — a name in no table here is written to
        # X19, and X19 is argument 0.
        nested = self._frame_nested_slots.get(name)
        if nested is not None:
            outer = name.rsplit(".", 1)[0]
            parked = src
            if src == 17:
                self.asm.emit(encode_mov_zr_xn(16, src))
                parked = 16
            self._load_var(outer, 17)
            self.asm.emit(encode_str_xt_xn_imm(parked, 17, 8 * nested))
            return
        if name in self._var_regs:
            r = self._var_regs[name]
            if src != r:
                self.asm.emit(encode_mov_zr_xn(r, src))
            return
        if name in self._var_spills:
            off = self._spill_off(name)
            # One instruction instead of three. The unscaled form takes a
            # signed displacement directly, which is exactly what a spill slot
            # is: a fixed negative offset from the frame pointer. (The sign
            # matters: see the note in `_load_var`.)
            if off <= 256:
                self.asm.emit(encode_stur_xt_xn_imm(src, 29, -off))
                return
            self.asm.emit(encode_mov_zr_xn(17, 29))
            _emit_sub_imm(self.asm, 17, 17, off)
            self.asm.emit(encode_str_xt_xn_imm(src, 17, 0))
            return
        # A store with no home was a store into X19, which the NEXT function
        # reads as its FIRST PARAMETER — wave 5's rule in its most literal
        # form: a missing branch here is not a wrong value, it is a wrong
        # store. Refused, by name, with the same reason the read half gives.
        raise CodegenError(self._no_home(name))

    def _load_home_from_reg(self, name: str, src: int, ptype=None):
        """X<src> → this local's home, and the register it ended up in.

        ONE routine for "an incoming argument register becomes a local",
        because there are two callers with the same requirement and the
        second one (the returned-frame hidden word) is not a parameter: it is
        an address, so it must not be narrowed to a declared width, and it
        still has to be out of the caller-saved X0..X7 before the body runs.

        The SPILL half of it was wrong before this existed and is what the
        returned-frame convention made reachable: it moved `X<src>` into X17
        and then stored X17 *through* X17, so the slot received the ADDRESS of
        itself instead of the value. It was unreachable while a function had
        at most eight parameters and ten callee-saved registers; a
        frame-returning function's hidden word is an eleventh local, so a
        program with ten locals reached it. A parameter is written to its slot
        first and then EXTENDED through a register, because the slot is what
        the body reads later and a stale high word poisons every comparison —
        which the old `continue` skipped, since that path could not be taken."""
        if name in self._var_regs:
            home = self._var_regs[name]
            if home != src:
                self.asm.emit(encode_mov_zr_xn(home, src))
            if ptype is not None:
                self._emit_extend(home, home, resolve(
                    parse_type_name(ptype) or DEFAULT_INT_TYPE))
            return home
        if name in self._var_spills:
            # Park the value in a register the address scratch is not, so the
            # extend has something to work on and the store has the right
            # operand whichever way round it goes.
            if src == 17:
                self.asm.emit(encode_mov_zr_xn(16, src))
                src = 16
            if ptype is not None:
                self._emit_extend(16, src, resolve(
                    parse_type_name(ptype) or DEFAULT_INT_TYPE))
                src = 16
            self._store_var(name, src)
            return None
        return None

    def _no_home(self, name: str) -> str:
        """The refusal for a name with no register, spill slot or frame slot.

        A FIELD CHAIN is a different question from a bare name and gets
        different words: `b.z = 1` with `b` a parameter has no field layout to
        store into, and this function used to answer it with `mov x19, src` —
        a store into the register the NEXT function reads as its first
        parameter. Wave 5's rule in its most literal form."""
        holder = name.split(".", 1)[0] in self._frame_holders
        if "." in name:
            return M.field_access_refusal(name, self.func_name or "<module>",
                                          name.split(".", 1)[0], holder)
        return M.unresolved_name_refusal(
            name, self.func_name or "<module>",
            "the register allocator collected no home for it, so the emitter "
            "and the allocation walk disagree about this function's locals")

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
            elif self._returns_frame is not None:
                self._emit_frame_return(stmt.value)
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
            self._emit_truthy_word(stmt.value)
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
            # The same refusal `_emit_binop` makes, asked HERE because an
            # augmented assignment is a separate emitter that never went
            # through it. That is not a hypothetical: `s += t` built, ran, and
            # printed `[]` on arm64 and segfaulted on x86-64 — the same
            # non-answer as `s = s + t`, which BOTH backends refused, from the
            # same line of source. `stmt.op` is the spelling to quote, so the
            # diagnostic names the `+=` the reader is looking at.
            reason = M.string_binary_refusal(
                op, self._expr_str_kind(stmt.target),
                self._expr_str_kind(stmt.value), spelled_op=stmt.op)
            if reason is not None:
                raise CodegenError(reason)
            if op in M.AUG_SHIFT_OPS:
                self._load_var(name, 0)
                self.asm.emit(encode_stp_sp_pre(0, 2))
                self._emit_expr_to(stmt.value, "X1")
                self.asm.emit(encode_ldp_sp_post(0, 2))
                # The LEFT operand is the name being shifted, so its own type
                # decides the fill and the shift AMOUNT's type is not
                # consulted — `model.shift_signedness`, the same rule
                # `_emit_div_shift_pow` uses for the binary form. A `y <<= n`
                # and a `y = y << n` are the same operator and must not
                # disagree about whether the result is signed.
                self._emit_shift_reg(op, signed=cmp_signed(
                    M.shift_signedness(self._ttype(F.IdentExpr(name)))))
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
            fail = next_labels[i + 1] if i + 1 < len(tests) else (
                else_label if has_fallthrough_else else end_label)
            if not self._emit_branch_unless(cond, fail):
                self._emit_truthy_word(cond)
                self.asm.emit(encode_cmp_xn_imm(0, 0))
                self._record_cond_branch()
                self.asm.emit(encode_cbz_xn(0, 0))
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
                # The old lowering called `_emit_cmp` here and never branched
                # on the CSET it left behind: `for i in range(a, b)` computed
                # a boolean, dropped it, and looped forever. Compare and branch
                # on the flags directly.
                # The comparison has to follow the step's direction, or a
                # descending range exits immediately (and an ascending one
                # would run away). A step whose sign is only known at runtime
                # is refused rather than silently mis-compiled: the counter
                # advances correctly but the loop bound would be the wrong way
                # round, which is a wrong answer, not a slow one.
                _down = self._for_step_sign(step_val)
                if _down is None:
                    raise CodegenError(
                        f"for-range step must be a literal or a negated "
                        f"literal, so the loop bound can be chosen at compile "
                        f"time (got {step_val!r})")
                _u, _sg = ("hi", "gt") if _down else ("cc", "lt")
                self._emit_branch_unless_cmp(F.IdentExpr(target), end_val,
                                              _u, _sg, false_label)
            elif not self._emit_branch_unless(cond, false_label):
                self._emit_truthy_word(cond)
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
            # The blob walk below reads the count at offset 0 of the iterable
            # and then elements at `base + 8 + 8k`, so a FRAME ADDRESS here
            # iterates the struct's fields.  Measured on both architectures:
            # summing a four-field struct gave 99 on arm64 and 53 on x86-64.
            self._refuse_frame_container_operand("a for-in iteration", it)
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

    def _for_step_sign(self, step):
        """True if `step` counts down, False if up, None if not decidable.

        Mirrors the forms `_for_inc_body` accepts, so the loop test and the
        counter advance always agree on the direction.
        """
        if isinstance(step, F.UnaryOp) and step.op == "-":
            if isinstance(step.operand, F.IntLiteral):
                return step.operand.value != 0
            return None  # `-x`: sign depends on the runtime value
        if isinstance(step, F.IntLiteral):
            return step.value < 0
        return None

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
        # An MLIR attribute/type template is refused HERE, at the top of the
        # walk, rather than at the subscript address computation below. The
        # address path is only reached for a `SubscriptExpr`, and the construct
        # has a THIRD spelling that reaches no subscript at all: the dotted
        # `__mlir_attr.`#kgen.param.expr<…>``, which is a plain member read and
        # so fell through to `_load_var` on a name nothing defines. It built,
        # it ran, and it printed a fabricated word — 10 here, 0 on x86-64, for
        # the same source, and 1 on this architecture if the program had five
        # more locals. `is_mlir_template` keys on the base name, so one call
        # covers all three spellings and both architectures (the text is the
        # shared arch-free one).
        why = M.mlir_template_refusal(expr)
        if why is not None:
            raise CodegenError(why)
        # Likewise a `...`, which used to reach the walk's tail and be named as
        # an AST node the author never wrote. Shared text, so x86-64 says the
        # same thing — and neither says the false thing x86-64 used to append
        # about containers and strings.
        why = M.ellipsis_refusal(expr)
        if why is not None:
            raise CodegenError(why)
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
            # `-s` is negation of an address and `~s` is a bit complement of
            # one, and `not s` is FALSE for every string including the empty
            # one, because a pointer is never zero. Measured on both backends:
            # `~s` returned 8881076 on arm64 and 3236815 on x86-64, and
            # `not ""` returned 0 where Python returns 1. `model` holds the
            # messages and the measurements; asking here is what makes the two
            # architectures refuse the same thing.
            ureason = M.string_unary_refusal(
                expr.op, self._expr_str_kind(expr.operand),
                M.spelled(expr.operand))
            if ureason is not None:
                raise CodegenError(ureason)
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
            if expr.op == "~":
                # `~x` — bitwise NOT, one MVN. This branch is what made `~` a
                # refusal on arm64 for an integer: the x86-64 `_emit_unary` has
                # had one since before wave 5, this file did not, and so the
                # two backends would have answered `~5` differently (one -6,
                # one a CodegenError) for a construct that has one meaning.
                # `~` on a STRING is refused above, before this: the refusal is
                # about the operand, not the operator.
                self._emit_expr(expr.operand)
                self.asm.emit(encode_mvn_xd_xn(0, 0))
                self._emit_trunc(self._ttype(expr.operand))
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
            # x = a if c else b. With nothing observable in c/a/b this is one
            # CSEL instead of a branch: both arms are computed, one is chosen.
            # That is the whole point of the instruction, and it is also why
            # the arms must be pure — see _is_pure_expr.
            if (self._is_pure_expr(expr.condition)
                    and self._is_pure_expr(expr.then_val)
                    and self._is_pure_expr(expr.else_val)):
                self._emit_csel_ternary(expr)
                return
            # Otherwise: same branch shape as if/else, both arms leave their
            # value in X0, join at end.
            self._if_counter += 1
            tid = self._if_counter
            fn = self.func_name
            else_label = f"{fn}_tern{tid}_else"
            end_label = f"{fn}_tern{tid}_end"
            if not self._emit_branch_unless(expr.condition, else_label):
                self._emit_truthy_word(expr.condition)
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
            # `DType.<member>` is a VALUE naming a type — `dtype == DType.int32`
            # is how `std/testing/prop/random.mojo:304` asks a question — and
            # the value is the member's tag, the same word the bare `Int32` is.
            # Asked BEFORE the member path below, which would read the slot key
            # `DType.int32` and refuse it: this is a compile-time constant, not
            # a field of anything.
            tag = M.type_value_tag(expr)
            if tag is not None:
                self._emit_mov_imm("X0", tag)
                return
            if M.is_dtype_member_access(expr):
                # `DType.float8_e4m3fn` and its siblings: a real Mojo type whose
                # NAME is in no table on this path, so there is no tag to
                # compute. Refused by name here, because the arm below would
                # read the slot key `DType.<member>` and report a missing FIELD.
                raise CodegenError(M.dtype_member_refusal("DType", expr.member))
            key = _member_slot_key(expr)
            if key is not None:
                # A chain DEEPER than a frame slot reaching a VALUE position is
                # the one shape the frame layout cannot answer, and it must not
                # fall through to `_load_var`: a name that is in no register
                # home and no spill slot reads X19, so `h.f.g` would quietly
                # become "whatever that scratch register holds" — a wrong answer
                # with no failure anywhere. `formal/build.py` refuses it in the
                # same shape, and this is the second line of that refusal: the
                # build pass is a whole-module judgement and this one is
                # per-emission, so a construct that reached here by some route
                # the build pass does not model is still stopped rather than
                # read. A `h.f.m(...)` CALL does not come through here — the
                # call path reads `h.f` as a value receiver and dispatches on
                # the method — so what is refused here is a genuine field of a
                # field.
                root = key.split(".", 1)[0]
                if "." in key and key not in self._frame_slots \
                        and key not in self._frame_nested_slots \
                        and root in self._frame_holders:
                    raise CodegenError(
                        f"{key} reads a field of a field through the receiver "
                        f"{root} and reached a value position, where a frame "
                        f"slot has no second layout to offer: the word in the "
                        f"slot is a value, and this path will not read a word "
                        f"as though it were a struct's storage")
                self._load_var(key, 0)
                return
            # A field read off a call that RETURNS A FRAME: `fwd(r).a`,
            # `r.give().x`.  The base is the block this function reserved for
            # that call's result, so the field is one load at `base + 8*slot`
            # — the same access a named holder gets, with the address arriving
            # from the call rather than from a register.  Without this branch
            # it fell into the "no object model, the field reads as 0" path
            # below, which is a plausible number and not the program's.
            if isinstance(expr.obj, F.CallExpr):
                site = self._ret_frame_sites.get(id(expr.obj))
                if site is not None:
                    st = site[0]
                    slot = M.struct_frame_slot(st, expr.member)
                    if slot is None:
                        raise CodegenError(
                            f"{M.spelled(expr)} reads {expr.member!r} out of a "
                            f"{st.name} this call returns, and that struct's "
                            f"{M.struct_field_summary(st)} has no such field: "
                            f"this path has no way to know which word that is, "
                            f"and reading the wrong one is a wrong answer "
                            f"rather than a failure")
                    self._emit_expr(expr.obj)
                    self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 8 * slot))
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

    def _scan_value_kinds(self, fn) -> M.ValueKinds:
        """What every local of `fn` holds, from its source alone.

        The decision is model.ValueKinds' (it has to come out the same on both
        backends); this only supplies the hooks that are this backend's:
        the annotation vocabularies from formal.types, a callee's kind from its
        declared return type or its return statements, the local-slot key for a
        field chain, and — since a field's DECLARED type is a fact about the
        struct rather than about this function — `_declared_kind` below."""
        return self._vkinds_for(fn.name, fn, frozenset())

    def _vkinds_for(self, name, fn, stack) -> M.ValueKinds:
        """A ValueKinds for `fn`, memoized across the whole module.

        `_functions` is fixed for a compile, so the answer for a callee does not
        change between call sites and is worth keeping; the `stack` is what
        stops `def a(): return b()` / `def b(): return a()` from recursing
        forever (a cycle is a word, like every other undecidable answer)."""
        if name in self._vkinds_cache:
            return self._vkinds_cache[name]
        vk = M.ValueKinds(
            fn,
            int_names=TYPE_NAMES,
            string_names=STRING_TYPE_NAMES,
            func_kind=lambda callee: self._callee_kind(callee, stack | {name}),
            slot_key=_member_slot_key,
            declared_kind=self._declared_kind_for(name))
        self._vkinds_cache[name] = vk
        return vk

    def _declared_kind_for(self, fn_name):
        """`_declared_kind` bound to the function `fn_name`, for `ValueKinds`.

        Three shapes, and the third is the one that needed measuring.  A METHOD
        of a struct: `self.<field>` is that struct's field and `self` itself is
        the struct's only word when the struct has one field, so both are
        decided by `model.method_owner_struct` finding the owner from the
        lifted name.  A FRAME SLOT: `h.<field>` is a load at `base + 8k` out of
        a frame whose layout `formal/build.py` settled, so the holder's
        candidate structs are the declaration, and the agree-or-refuse in
        `model.frame_slot_field_kind` is what says they agree.

        The third shape is the CONSTRUCTOR of a one-word struct bound to a
        local: `r = B()` produces B's only word, so `len(r)` is the same
        question as `len(self.<f>)` asked one level out.  All three were
        answered "a word, therefore an integer" before this hook existed, so
        `var t = self.xs; len(t)` refused with "an integer has no length"
        about a list — a refusal whose reason is false, and one that sends the
        reader after an annotation which is already on the declaration line.
        A `None` from the struct table leaves the old default in place, so
        nothing that used to decide still decides differently.
        """
        owner = M.method_owner_struct(self._structs, fn_name)
        # BOUND, not read off `self` at query time: `_vkinds_cache` is keyed by
        # name and lives for the whole compile, so a closure that reached back
        # into `self._frame_candidates` would answer about whichever function
        # happened to be emitting when it was asked. The table is per function
        # and is fixed before `_scan_value_kinds` runs (see `_emit_function`).
        frame_candidates = dict(self._frame_candidates)
        structs = self._structs

        def kind_of_slot(expr):
            if isinstance(expr, F.IdentExpr):
                name = expr.name
                if owner is not None and name in M.struct_receivers(owner):
                    return M.one_word_receiver_kind(
                        owner, TYPE_NAMES, STRING_TYPE_NAMES, structs)
                cands = frame_candidates.get(name)
                if cands:
                    return M.one_word_receiver_kind(
                        cands[0], TYPE_NAMES, STRING_TYPE_NAMES, structs)
                return None
            if isinstance(expr, F.MemberExpr):
                # ONE level only.  `a.b.c` is a load of a load and the outer
                # field's declared type is the type of the WORD, not of
                # whatever that word points at, so a chain says nothing here.
                if not isinstance(expr.obj, F.IdentExpr):
                    return None
                root = expr.obj.name
                if owner is not None and root in M.struct_receivers(owner):
                    cands = [owner]
                else:
                    cands = frame_candidates.get(root)
                if not cands:
                    return None
                return M.frame_slot_field_kind(
                    cands, expr.member, TYPE_NAMES, STRING_TYPE_NAMES,
                    structs)
            if isinstance(expr, F.CallExpr) and isinstance(expr.func,
                                                            F.IdentExpr):
                return M.one_word_receiver_kind(
                    structs.get(expr.func.name), TYPE_NAMES,
                    STRING_TYPE_NAMES, structs)
            return None

        return kind_of_slot

    def _slot_declared_annotation(self, expr):
        """`(annotation, kind)` a frame slot's field DECLARES, or None.

        The refusal half of `_declared_kind_for`: that one answers "what does
        this slot hold" and returns None when the VALUE is not established,
        which is the right answer for a lowering and the wrong one for a
        message — "the source does not say what this operand holds" is false
        about a field that says `var xs: List[Int]` two lines above.  So the
        annotation is reported separately, ungated by the value, and
        `model.len_refusal` decides what to do with it.  Same shapes and the
        same one-level limit as the kind hook; see there for why.

        The fourth shape is a bare NAME that IS a one-word struct's whole value:
        the receiver of a method of a single-field struct, and a local bound to
        such a struct's constructor.  `self.<field>` was rewritten to `self` by
        `_rewrite_self_fields` long before this runs, so without this arm the
        one-field list-backed struct — the shape 30 stdlib files are blocked on
        at `binary_heap.mojo` — is reported with no annotation at all, and the
        message is the "the source does not say" one that is false about
        `var _data: List[Self.T]`.
        """
        owner = M.method_owner_struct(
            self._structs, getattr(self._cur_fn, "name", None))
        if isinstance(expr, F.IdentExpr):
            if owner is not None and expr.name in M.struct_receivers(owner):
                return self._one_word_slot_ann([owner])
            cands = self._frame_candidates.get(expr.name)
            if cands:
                return self._one_word_slot_ann(list(cands))
            # A LOCAL bound to a one-word struct's constructor: `r = B()`, so
            # the name IS the struct's one field.  Found by walking the
            # function's own bindings rather than by guessing from the name —
            # the same walk and the same rule as `_one_word_field_map` in
            # formal/build.py, and it has to agree with it, because that is
            # what turned `r.<field>` into `r` in the first place.
            bound = None
            for node in M.iter_nodes(getattr(self._cur_fn, "body", None)):
                target = value = None
                if isinstance(node, F.VarDecl):
                    target, value = node.name, node.value
                elif isinstance(node, F.AssignStmt) and isinstance(
                        node.target, F.IdentExpr):
                    target, value = node.target.name, node.value
                if (target == expr.name and isinstance(value, F.CallExpr)
                        and isinstance(value.func, F.IdentExpr)):
                    bound = self._structs.get(value.func.name)
            return self._one_word_slot_ann([bound] if bound else None)
        if not isinstance(expr, F.MemberExpr) \
                or not isinstance(expr.obj, F.IdentExpr):
            return None
        root = expr.obj.name
        cands = [owner] if (owner is not None
                           and root in M.struct_receivers(owner)) \
            else self._frame_candidates.get(root)
        if not cands:
            return None
        ann = M.frame_slot_declared_annotation(cands, expr.member)
        if ann is None:
            return None
        return self._slot_ann_pair(ann)

    def _one_word_slot_ann(self, cands):
        """`(annotation, kind)` for a struct that IS its one field, or None."""
        if not cands or M.struct_field_count(cands[0]) != 1:
            return None
        only = M.struct_sole_field_name(cands[0])
        if only is None:
            return None
        ann = M.frame_slot_declared_annotation(cands, only)
        return self._slot_ann_pair(ann) if ann is not None else None

    def _slot_ann_pair(self, ann):
        """`(annotation, kind)`, with the kind UNGATED by the value.

        Ungated because `len_refusal` needs it to choose between the container
        row, the string row and the integer row, and the gate that suppressed
        the kind from the lowering decision is the reason the refusal is being
        reached at all.
        """
        if ann is None:
            return None
        return (ann, M.declared_type_kind(ann, TYPE_NAMES, STRING_TYPE_NAMES,
                                          self._structs))

    def _extern_symbol(self, name: str) -> str:
        """The boundary symbol an unbound callee `name` is emitted against.

        The DECISION and the words are `model.dylib_extern_symbol`'s, shared
        with the x86-64 emitter: two spellings (a bare name from the flat map, a
        dotted name from the library built for that module or from what it
        forwards), and a dotted name whose module is linked but does not publish
        it is refused by name here rather than emitted as a BL against a symbol
        nothing defines. This used to be a second copy of that rule, in two
        backends, which is two places for one language implementation to
        disagree about what a module call binds.
        """
        return M.dylib_extern_symbol(name, self._dylib_syms,
                                     self._dylib_by_name,
                                     self._dylib_by_module,
                                     self._dylib_forwarded)

    def _untyped_callee(self, name) -> bool:
        """Is `name` a MOJO function that does not say what it returns?

        The question `string_compare_word_refusal` needs and `ValueKinds` cannot
        answer: an unannotated call's result and an `-> int` call's result are
        both `INT_KIND` on this path, because a word is an integer, and the two
        are not the same thing — one of them may be a `char *`, and `f() == g()`
        on two of those compares two addresses.

        Two sources, because there are two kinds of Mojo callee, and the third
        kind is the one that must NOT be in this set:

          * a function of THIS image — the parser recorded its `return_type`,
            and `None` is the answer when the source has no `->`;
          * an export of a LINKED MODULE — its manifest signature carries the
            return type, and `reflect._c_signature` spells an unannotated
            function's as `void`, so `void` here is the same fact as `None`
            above. `dylib_export_return_kind` reads the `char *` case out of
            the same string, which is how a cross-image `-> str` classifies;
          * and an UNBOUND EXTERN is NOT in this set at all. `memcmp(a, b, n)
            == 0` is in every `os` function on this path and is correct on
            every one of them; `getenv(name) == 0` is a NULL check. A C
            library function has no Mojo return annotation to be missing.
        """
        fn = self._functions.get(name)
        if fn is not None:
            return getattr(fn, "return_type", None) is None
        entry = M.dylib_export_lookup(self._dylib_by_name,
                                      self._dylib_by_module, name)
        if entry is None:
            return False
        return M.signature_return_type(
            entry.get("signature") or "").strip() == "void"

    def _callee_kind(self, name, stack):
        """What a call to the local function `name` produces, or None."""
        fn = self._functions.get(name)
        if fn is None or name in stack or len(stack) >= 3:
            if fn is not None:
                return M.INT_KIND
            # Not a function of this unit: it is a linked module's export, and
            # the manifest entry says what it returns. Without this the result
            # was unclassified, and `print(mod.name())` formatted a `char *` as
            # an integer — the pointer's own value, so the program printed
            # 4335747904 where it meant to print `darwin`.
            return M.dylib_export_return_kind(
                M.dylib_export_lookup(self._dylib_by_name,
                                      self._dylib_by_module, name,
                                      self._dylib_forwarded))
        vk = self._vkinds_for(name, fn, stack)
        ann = getattr(fn, "return_type", None)
        if ann in STRING_TYPE_NAMES:
            return M.STR_KIND
        if ann in TYPE_NAMES:
            return M.INT_KIND
        return vk.return_kind

    def _scan_list_caps(self, fn, vkinds: M.ValueKinds):
        """({ListExpr node: slots}, {name: slots}) for `fn`'s appendable lists.

        A list blob is `[count:i64][elem0]…` carved out of the frame, so
        `xs.append(v)` needs room the literal's own element count does not
        promise — `xs = []` plus one append is the commonest shape there is and
        starts with nothing. The number of `append` call sites on a name in
        this function is a sound compile-time bound for STRAIGHT-LINE code, and
        the store is bounds-checked against it at runtime, so the shape this
        gets wrong (an append inside a loop) exits(1) loudly instead of writing
        past the blob — the same bargain every other bounded container
        operation on this path makes.

        Two maps because the two ends of the operation are different places:
        `_emit_list` allocates, and it has only the literal NODE (an expression
        carries no name); `_emit_list_append` stores, and it has only the
        receiver's NAME. Both must agree on the number, and they are computed
        from one pass so they cannot. A name bound to more than one literal
        takes the smallest of their capacities, so the bound holds whichever
        blob is live."""
        appends: dict = {}
        for _node, recv, method, _args in _walk_value_methods(fn):
            if method != "append" or not isinstance(recv, F.IdentExpr):
                continue
            appends[recv.name] = appends.get(recv.name, 0) + 1
        by_node: dict = {}
        by_name: dict = {}
        for name, count in appends.items():
            # A list the function appends to must also BE a list: if the name
            # is bound to something else anywhere, the capacity would be a
            # promise about the wrong blob, so the entry is dropped and the
            # append site refuses instead.
            if not M.is_list_kind(vkinds.name_kind(name)):
                continue
            literals = _list_literals_bound_to(fn, name)
            if not literals:
                continue
            want = min(len(lit.elements) for lit in literals) + count
            for literal in literals:
                prev = by_node.get(id(literal))
                by_node[id(literal)] = want if prev is None else min(prev, want)
            by_name[name] = want
        return by_node, by_name

    def _note_global_kinds(self, fn) -> None:
        """Mark the module globals `fn` mentions, from their SLOTS.

        The counterpart of `_note_binding` for a name this function does not
        bind. A local gets its kind from the assignment it is bound by; a module
        global has no assignment in the function at all, so without this its
        kind is whatever a bare word defaults to — an integer — and the two
        things that ask go wrong in opposite directions:

          * `D["a"]` on a dict global was emitted as a SEQUENCE subscript, so
            the key's interned address became an element offset and the image
            exited 1 on the bounds check (measured, both architectures);
          * `print(NAME)` on a string global rendered the address as a decimal
            (measured) — see `model.global_slot_is_string`.

        Only marks what the SLOT says, and a name with no slot was refused by
        name long before here, so this cannot invent a kind."""
        for node in M.iter_nodes(getattr(fn, "body", None) or []):
            if not isinstance(node, F.IdentExpr):
                continue
            if M.global_slot_is_dict(node.name):
                self._dict_vars.add(node.name)
            elif M.global_slot_is_string(node.name):
                self._string_vars.add(node.name)

    def _note_binding(self, name: str, value) -> None:
        """Track whether `name` holds a string pointer or a dict pair-blob.

        Mutually exclusive marks: DictExpr RHS → dict var; StringLiteral
        (or alias of a known string) → string var; anything else clears
        both. Enables subscript dispatch (byte / key-lookup / list index).

        The descriptor mark is SEPARATE and not mutually exclusive, because it
        answers a different question: a descriptor is an int, so a name bound
        to one is also correctly an int, and clearing the string/dict marks for
        it is right. What it must not be is silently treated as an arbitrary
        int by `_emit_value_method`, which is what `model.VALUE_METHOD_RECEIVERS`
        is for."""
        if M.is_open_call(value):
            # `f = open(p, "w")` — the one binding that makes a word a
            # descriptor. Checked first because `open` is an ordinary call and
            # would otherwise fall to the clearing `else` below.
            self._fd_vars.add(name)
        elif isinstance(value, F.IdentExpr) and value.name in self._fd_vars:
            # An alias keeps it: `g = f`. Anything else below clears it.
            self._fd_vars.add(name)
        else:
            self._fd_vars.discard(name)
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
        elif isinstance(value, F.CallExpr) and M.string_method_yields_string(
                value, self._expr_str_kind(
                    value.func.obj if isinstance(value.func, F.MemberExpr)
                    else None) == M.STR_KIND):
            # A lowered string method that yields a string: `m = s.lstrip()`
            # binds a `char *` exactly as `m = s` does. Without this the name
            # fell through to the clearing `else` below, and the consequence
            # was not a refusal — it was a WRONG ANSWER, because the two
            # things that consult `_string_vars` (a string `==`, and `print`)
            # then treated the pointer as a number. `"  hi".lstrip() == "hi"`
            # compared a pointer against an integer and said False.
            self._string_vars.add(name)
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
        """True when `obj` is known to hold a char* (byte index path).

        One question, asked through the one authority that answers it:
        `_expr_str_kind`, so the flow-sensitive `_string_vars` map still wins
        where the two disagree and this cannot contradict the three call sites
        (`len`, `print`, a string method receiver) that were already right.

        The FALLBACK is the whole of a fixed silent wrong answer. A parameter is
        bound by the signature, so `_note_binding` never sees it and it was not
        in `_string_vars` — while the whole-function `ValueKinds` IS seeded from
        the parameter's annotation. Asking only the flow-sensitive set therefore
        gave one name two answers on this path: a `char *` to `len`/`print`, a
        LIST BLOB to this one. Falling through to the blob path is what made it
        silent AND wrong-shaped rather than a crash — a blob is
        `[count:i64][elem0]…`, so `s[0]` read the first eight CHARACTERS of the
        string as the element count and loaded `base + 8 + 8*count`, which for
        `"AB"` walks off the string and returns a text-section address. Measured
        before the fallback: `f(s: String): return s[0]` on `f("AB")` printed
        -8070450326089498624, where 65 is the answer. See
        bugs/CODEGEN_string_parameter_subscript_reads_count_field.md.
        """
        if isinstance(obj, F.StringLiteral):
            return True
        return self._expr_str_kind(obj) == M.STR_KIND

    def _emit_subscript(self, e: F.SubscriptExpr) -> None:
        """`obj[index]` → element/byte value in X0.

        List/tuple blobs: `[count:i64][e0…]`, unsigned bounds-checked
        (negative indices wrap like Python, then bounds-check); OOB →
        Darwin exit(1). String pointers (literal or tracked var): raw
        byte load, no header. A declared POINTER: a load of the pointee's
        width, which `_emit_subscript_addr` recorded in `_sub_width`.

        Every refusal lives in `_emit_subscript_addr`, which this calls: a
        read, a store and an augmented assignment all go through it, and a
        check that lives here covers only the read."""
        if isinstance(e.index, F.SliceExpr):
            # `obj[start:stop:step]` parses as SliceExpr with .obj attached;
            # a nested `base[sl]` form puts SliceExpr in .index.
            sl = e.index
            self._emit_slice_parts(e.obj, sl.start, sl.stop, sl.step)
            return
        self._emit_subscript_addr(e)
        self._emit_subscript_load(0, 0)

    def _emit_subscript_load(self, reg: int, base: int) -> None:
        """Load one element through X{base} into X{reg}, at `_sub_width`.

        ONE place, because the read, the store's own read-modify and the
        augmented assignment each used to spell this choice separately and the
        pointer route made a third width possible. A one-byte element is
        zero-extended by `LDRB`, which is what a `UInt8` read is; anything
        wider is the full 64-bit load, and the sub-word widths the pointee
        table can return (2 and 4) are the same two instructions
        `_emit_dereference` uses for them.
        """
        if self._sub_width == 1:
            self.asm.emit(encode_ldrb_wd_wn(reg, base, 0))
        else:
            self.asm.emit(encode_ldr_xt_xn_imm(reg, base, 0))

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

        ONLY a known dict base qualifies. The rule used to be broader — a
        static container key qualified on its own, on the reasoning that a
        tuple index in Python is a dict key or a TypeError and never a list
        multi-index. That reasoning is right about Python and wrong about
        this corpus: `size_of[type, target]` and every other multi-element
        subscript in the stdlib is a compile-time parameter list on a generic,
        so the broader rule sent those down the dict path, where the "index"
        is a freshly materialized blob and the scan compares one address
        against another. It built, it ran, and it disagreed with x86-64."""
        return self._is_dict_subscript(e.obj)

    def _refuse_frame_container_operand(self, op: str, obj) -> None:
        """Raise if `obj` is a BARE NAME holding a frame address.

        The container family reads offset 0 of its operand and calls it a
        count, and it is the one lowering that never asked what the operand
        was — so a frame address went straight into the blob walk and `r[0]`
        returned the struct's second field.  See
        `model.frame_container_operand_refusal` for the measurement and
        `model.FRAME_KIND` for why the kind alone does not stop it.

        BARE NAME ONLY, deliberately and for the same reason
        `build._refuse_holder_use` is: `h.x` is a 64-bit FIELD and reading it
        as a blob is what a declared `List` field is FOR, while the address
        itself is the thing with no container reading.  The table is the
        frame-holder analysis's own, published per function by
        `formal/build.py`, so this asks the same question the hand-off checks
        ask rather than re-deriving what a name holds.
        """
        if not isinstance(obj, F.IdentExpr) or obj.name not in self._frame_holders:
            return
        cands = self._frame_candidates.get(obj.name) or ()
        raise CodegenError(M.frame_container_operand_refusal(
            op, M.spelled(obj), [st.name for st in cands]))

    def _emit_subscript_addr(self, e: F.SubscriptExpr) -> None:
        """X0 = &obj[index]. Blob path bounds-checkes (exit 1 on OOB).

        The single choke point for a subscript: a read, a store
        (`_emit_subscript_store_reg`) and an augmented assignment
        (`_emit_subscript_aug`) all come through here, so every refusal that
        belongs to a subscript belongs here too. Two did not, and both were
        reachable only through the store — `a[i, j] = v` and `a[x=1] = v` —
        because the checks sat in the read path. The first LIVELOCKED the
        proof generator (the emitted index is a frame address, so the
        bounds-check branch the step model has to follow is not one it has a
        contract for) and the second emitted a store through a computed
        address. Both now say no."""
        self._refuse_frame_container_operand("a subscript", e.obj)
        if M.is_external_call_template(e):
            # The ONE place an `external_call[...]` is a subscript that is not
            # the callee of a call, and `M.multi_index_refusal_for` above (and
            # in `build.py`) cannot see that, because `M.iter_nodes` has no
            # parent.  `_emit_call` intercepts the template BEFORE any address
            # is computed, so reaching here means the source used it as a
            # VALUE — and there is no such value: the bracket names a symbol and
            # a return type, and the word it would produce is the C function's,
            # which only a call can ask for.  Refused here rather than falling
            # through to the dict/frame address paths, which would answer with
            # an address into a frame that nobody asked for.
            raise CodegenError(M.external_call_value_refusal(
                M.external_call_spelling(e)))
        # The element width this subscript reads at, for the caller that emits
        # the load. A container element and a dict value are a word, a string
        # byte and a declared pointee are whatever the pointee is, and the
        # default here is the word because it is the answer for the two that
        # reach their own branch and set it before returning.
        self._sub_width = 8
        if e.attrs is not None:
            raise CodegenError(
                "type-parameter subscript [...] is not supported on the "
                "formal arm64 path")
        # Unconditional, because `multi_index_refusal_for` now decides the MLIR
        # case on the BASE name rather than on a comma list — see its
        # docstring. A single-element `__mlir_type[x]` used to skip this call
        # entirely and fabricate a word.
        why = M.multi_index_refusal_for(
            e, self._is_dict_subscript(e.obj), self._functions)
        if why is not None:
            raise CodegenError(why)
        if self._is_dict_key_subscript(e):
            self._emit_dict_lookup_addr(e)
            return
        if self._is_string_subscript(e.obj):
            # A string INDEX would make this `s + i` with two addresses. Asked
            # HERE, in the single choke point a read, a store and an augmented
            # assignment all pass through, so all three are covered by one
            # call. Measured: `s[t]` printed 67 on arm64 — the low byte of a
            # text-section address — and segfaulted on x86-64.
            ireason = M.string_index_refusal(
                self._expr_str_kind(e.obj), self._expr_str_kind(e.index),
                M.spelled(e.index))
            if ireason is not None:
                raise CodegenError(ireason)
            self._sub_width = 1
            self._emit_expr(e.obj)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(e.index, "X1")
            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))  # base from [SP]
            self.asm.emit(encode_add_xd_xn_xm(0, 0, 1))
            self.asm.emit(encode_mov_zr_xn(2, 0))
            self.asm.emit(encode_ldp_sp_post(0, 31))
            self.asm.emit(encode_mov_zr_xn(0, 2))
            return
        shape, width, _signed, sub_why = M.subscript_base_lowering(
            self._cur_fn, e.obj, self._structs, self._functions, self._structs)
        if shape is None:
            raise CodegenError(sub_why)
        if shape == "load":
            # A POINTER subscript is `base + index*width` and a load of `width`
            # bytes — `p[i]` and `p.value()` are the same question, and this is
            # the half of the pair that used to fall through to the blob walk
            # and read the element COUNT out of the pointer itself. Measured
            # before the route existed: `p[0]` on a `Pointer[UInt8]` holding
            # "ab" returned -1879048144 (0x9002_2E68 = "ab" plus the next two
            # bytes of __TEXT) and the same spelling on a `malloc`'d buffer
            # exited 1 with no message, because the count there is 0. See
            # bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md and
            # `model.subscript_base_lowering`, which owns the decision.
            self._sub_width = width
            self._emit_expr(e.obj)                    # X0 = the address
            self.asm.emit(encode_stp_sp_pre(0, 2))    # save it
            self._emit_expr_to(e.index, "X1")         # X1 = index
            self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 0))   # X9 = base
            if width != 1:
                # The scale is emitted, not assumed: `base + i` is right for a
                # one-byte element and is the SECOND element for any other
                # width, which is the same trap `_offset_scale` refuses rather
                # than guesses on the dereference path.
                self.asm.emit(encode_movz_xd_imm(2, width))
                self.asm.emit(encode_mul_xd_xn_xm(1, 1, 2))
            self.asm.emit(encode_add_xd_xn_xm(9, 9, 1))  # X9 = &elem
            self.asm.emit(encode_mov_zr_xn(0, 9))
            self.asm.emit(encode_ldp_sp_post(0, 31))  # restore SP (clobbers X0)
            self.asm.emit(encode_mov_zr_xn(0, 9))
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
        and survives the store, exactly as in the statement form.

        The VALUE is spilled across the address computation, and that is the
        whole point of this function. `_emit_subscript_addr` builds its answer
        in X0 out of X0..X4 and X9, so with `reg == 0` — which is what both
        callers pass, the statement form and the tuple unpack alike — the
        value was destroyed before the store and the ADDRESS is what got
        written: `xs[2] = 9` left a frame pointer at element 2, and reading it
        back printed that address as if it were the program's data. It built,
        it ran, and it disagreed with the x86-64 backend, which spills the
        value for exactly this reason. The spill is unconditional rather than
        special-cased on `reg == 0` because the register set the address
        computation clobbers is the backend's business, not this caller's.
        """
        self.asm.emit(encode_stp_sp_pre(reg, 31))   # push the value
        self._emit_subscript_addr(target)           # X0 = address
        self.asm.emit(encode_stp_sp_pre(0, 2))      # save addr
        self.asm.emit(encode_mov_zr_xn(9, 0))       # X9 = addr
        # X5 is outside the set the address computation above uses, and
        # nothing is emitted between the load and the store. The value is at
        # [sp+16]: the addr pair pushed just above took [sp+0] and [sp+8].
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 16))  # X5 = value
        if self._sub_width == 1:
            self.asm.emit(encode_strb_wd_wn(5, 9, 0))
        else:
            self.asm.emit(encode_str_xt_xn_imm(5, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))    # pop addr
        self.asm.emit(encode_ldr_xt_xn_imm(reg, 31, 0))  # value back in X{reg}
        self.asm.emit(encode_ldp_sp_post(0, 31))    # pop value

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
        self._emit_subscript_addr(target)
        self.asm.emit(encode_stp_sp_pre(0, 31))   # push addr (X0, XZR)
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 0))  # X9 = addr
        self._emit_subscript_load(0, 9)           # X0 = old, at the element's width
        self.asm.emit(encode_stp_sp_pre(0, 31))   # push old (stack: old, addr)
        self._emit_expr_to(stmt.value, "X1")      # X1 = value
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))  # X0 = old (re-load)
        if want_shift:
            # As above: the thing being shifted decides the fill, and for a
            # subscript target that is the ELEMENT, which is what `target`
            # types as.
            self._emit_shift_reg(op, signed=cmp_signed(
                M.shift_signedness(self._ttype(target))))
        else:
            self.asm.emit(ops[op](0, 0, 1))       # X0 = old op value
        # addr is at [SP+16] after the two pushes.
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, 16))
        if self._sub_width == 1:
            self.asm.emit(encode_strb_wd_wn(0, 9, 0))
        else:
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self.asm.emit(encode_ldp_sp_post(0, 31))

    def _emit_len(self, e: F.CallExpr) -> None:
        """`len(x)` — a blob's count field, or a string's `strlen`.

        A builtin, and it has to be intercepted here for the same reason
        `range` is: nothing else on this path knows the name. Left to the
        extern path it became a BL against a symbol `len` that libSystem does
        not define, so the image built and then aborted in the loader with
        "Symbol not found: _len" (or, where a `len` happened to exist, called
        it and returned whatever was in the result register).

        TWO lowerings, chosen by `model.len_operand_lowering` on the operand's
        kind, and the choice is the model's so the two architectures cannot
        make it differently:

          BLOB   the blob is `[count:i64][elem0]...` (see _emit_list) and a
                 list value IS its address, so this is one load from offset 0
                 — no traversal.

          STRING a string is a bare `char *` to NUL-terminated bytes, so its
                 length is not a field but a COMPUTATION: `strlen` is the
                 length of a NUL-terminated `char *` by definition. Same libc
                 call `endswith`, `count` and `f.write(s)` already make here.

        The string half used to be a refusal, and the refusal was narrower than
        the bug: it fired on a SYNTACTIC `StringLiteral` and on an identity
        type-constructor, and for every other shape it fell through to the
        count-field load — which for a `char *` reads the first eight
        CHARACTERS. Measured on this backend and on x86-64, `len(m)` where
        `m = "hello"` returned 1819043176 (0x6C6C6568, `hell` little-endian),
        and `len("  hi".lstrip())` returned 536897896 (0x20006869, `hi` plus
        the trimmed spaces). Both built, both ran, both were wrong.

        So the unclassified case is now a REFUSAL naming itself rather than a
        read, which is the third row of `len_operand_lowering` and the reason
        it exists: there is no shape for which reading offset 0 is right unless
        the source has said what the operand holds.
        """
        args = list(e.args)
        if len(args) != 1 or e.kwargs:
            raise CodegenError(
                f"len() takes exactly one argument on this path "
                f"(got {len(args) + len(e.kwargs)})")
        operand = args[0]
        how = M.len_operand_lowering(self._expr_str_kind(operand), operand)
        if how is None:
            slot = self._slot_declared_annotation(operand)
            raise CodegenError(M.len_refusal(
                self._expr_str_kind(operand), M.spelled(operand),
                slot[0] if slot else None,
                slot[1] if slot else None))
        if how == M.LEN_FROM_STRLEN:
            self._emit_expr(operand)          # X0 = the char *
            self._emit_extern_call(M.STRING_LENGTH_SYMBOL)
            return
        self._emit_expr(operand)
        # X0 holds the blob address; the count is its first 8 bytes.
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))

    # ── print ────────────────────────────────────────────────────────────

    # ── what a value is, for the paths that must decide before emitting ──

    def _expr_str_kind(self, expr):
        """What `expr` holds: "str", "int", or None if undecidable.

        Two sources, and `_string_vars` WINS where they disagree. It is
        flow-sensitive and tracks what the emission of this very function has
        bound so far, so it is strictly better informed than the whole-function
        `ValueKinds`; the whole-function map is what covers the shapes
        `_note_binding` does not see (a parameter's annotation, a function's
        return type, a subscript's element kind).

        Named for what it answers rather than for the first caller: `print`,
        the method-receiver guard and `_note_binding` all need the same
        question, and three copies of this precedence rule is three chances for
        one of them to decide that a `char *` is a number."""
        if isinstance(expr, F.MemberExpr):
            key = _member_slot_key(expr)
            if key is not None and key in self._string_vars:
                return M.STR_KIND
        elif isinstance(expr, F.IdentExpr) and expr.name in self._string_vars:
            return M.STR_KIND
        return self._vkinds.kind_of(expr)

    def _expr_is_fd(self, expr) -> bool:
        """True when `expr` is known to be a FILE DESCRIPTOR.

        The one fact the KIND cannot carry. A descriptor is an int, so
        `ValueKinds` calls it `int` and is right to — but `write(2)` needs more
        than "a number", it needs "a number open(2) handed back", and nothing
        but where the word was bound says so. `_fd_vars` is the whole test: a
        name bound from `open` in an earlier statement of this very function,
        and its aliases (`_note_binding`).

        Two shapes are deliberately NOT covered, and both refuse rather than
        guess:

        * A FRAME SLOT. Proving a field holds a descriptor is cross-field flow,
          which is the hand-off question and not this one, so `self._fd.write(s)`
          refuses with the receiver's SHAPE in the message rather than being
          lowered on the strength of a name it does not have.
        * A CALL RESULT, so `open(p, "w").write(s)` refuses. Not because a
          descriptor there is unknowable — `model.is_open_call` answers it — but
          because a method on a call result never reaches this code at all:
          `_is_value_receiver` says a CallExpr is not a value receiver, so the
          call is not a method call on this path. That is a real gap and a
          separate bug (the receiver is also not lowered by `_emit_open`, so it
          yields the descriptor with a mis-lowered open); it is recorded here
          rather than papered over, because an arm of this function that can
          never run would read as support for a shape that does not work."""
        if isinstance(expr, F.IdentExpr):
            return expr.name in self._fd_vars
        if isinstance(expr, F.MemberExpr):
            key = _member_slot_key(expr)
            return key is not None and key in self._fd_vars
        return False

    def _print_call(self, args: list):
        """`(format, operands)` for a `print` of `args`.

        The two lists are the SAME length relation the language has: a literal
        operand contributes a fragment to the format and NO operand to the
        call, and a value contributes a conversion and one operand. Passing the
        literals as well is the mistake this shape exists to prevent — the
        format would then ask printf for fewer arguments than it was handed,
        and everything after the first literal would be read one slot late."""
        frags, operands = [], []
        for a in args:
            if isinstance(a, F.StringLiteral):
                frags.append(M.print_literal(a.value))
                continue
            kind = self._expr_str_kind(a)
            if kind == M.STR_KIND:
                frags.append("%s")
            elif kind == M.INT_KIND:
                frags.append("%lld" if cmp_signed(self._ttype(a)) else "%llu")
            else:
                raise CodegenError(
                    f"print() cannot tell whether {type(a).__name__} is a "
                    f"string or a number on the formal arm64 path, and "
                    f"guessing would print an address as if it were text (or "
                    f"a number as if it were text). Annotate the name, or "
                    f"print a literal, or bind it to a literal first")
            operands.append(a)
        return frags, operands

    def _print_kwargs(self, e: F.CallExpr):
        """`print`'s `sep=` / `end=` / `file=`, as (sep, end). Only literals.

        `file=` is refused unless it is stdout, because this model has exactly
        one stream and a `file=sys.stderr` that quietly went to stdout would be
        a program whose diagnostics are missing rather than one that failed."""
        sep, end = " ", "\n"
        for k, v in e.kwargs:
            if not isinstance(v, F.StringLiteral):
                raise CodegenError(
                    f"print({k}=...) must be a string literal on the formal "
                    f"arm64 path (got {type(v).__name__}): the separator and "
                    f"the line ending are baked into the format string, which "
                    f"is built before the call is emitted")
            if k == "sep":
                sep = v.value
            elif k == "end":
                end = v.value
            elif k == "file":
                if not (isinstance(v, F.MemberExpr)
                        and v.member == "stdout"):
                    raise CodegenError(
                        f"print(file=...) other than sys.stdout is not lowered "
                        f"on the formal arm64 path: this model has one output "
                        f"stream")
            else:
                raise CodegenError(
                    f"print() has no keyword argument {k!r} on the formal "
                    f"arm64 path (supports sep, end, file)")
        return sep, end

    def _emit_print(self, e: F.CallExpr) -> None:
        """`print(...)` — a real call to the C library's `printf`.

        Not a stub and not a dropped call: the format string is built here out
        of what each operand statically is, and the operands themselves are
        passed as `printf`'s varargs, so what lands on stdout is what the
        source says. Left to the extern path this was `BL _print`, which is not
        a C symbol: the image built and then aborted in the loader with
        "Symbol not found: _print", which is how the most ordinary program in
        the tree failed to run.

        `print()` with no arguments still prints a blank line, and the call's
        value is `None` — the format string's `%`-count is zero, so printf
        reads no varargs and the register state afterwards is irrelevant."""
        sep, end = self._print_kwargs(e)
        frags, operands = self._print_call(list(e.args))
        fmt = M.print_format(frags, sep, end)
        self._emit_call(F.CallExpr(func=F.IdentExpr(name="printf"),
                                   args=[F.StringLiteral(fmt)] + operands))

    # ── methods on a value ───────────────────────────────────────────────

    def _is_value_receiver(self, obj) -> bool:
        """True when `obj` is a VALUE, so `obj.m(...)` is a method call.

        A module path (`os.path.join`) roots at a name too, so the test is
        whether that name is one of this function's own. Register allocation
        knows every local of the function being emitted, including its
        parameters, so membership there is the whole answer for a name.

        A string LITERAL is a value as unambiguously as a name is: it is
        interned into a `char *` and `s.strip()` on one means exactly what it
        means on a local. It has to be here, and the reason it was not is
        worth recording: with only `append`/`write`/`close` lowerable, every
        one of them needs a NAME to mutate or to file-descriptor, so a literal
        receiver was never a case that could arise — and `"x".strip()` fell
        through to the extern path and became `BL _strip`, the flat-symbol call
        to a method this path is supposed to refuse. Adding the string methods
        made the hole reachable, and a method on a literal is the most ordinary
        method call there is.

        A FRAME SLOT is a value here too, and has to be: `h.f.m(...)` reads
        `mem[h + 8k]` and hands that word to the callee, so it is a method call
        on a value and `model.value_method_refusal` is what decides it. The
        build pass used to refuse the chain outright as a field of a field,
        which meant the case never got here — and if it had got here without
        this, `_callee_symbol` would have flattened `h.f.m` to a dotted name,
        found no such function, and emitted `BL h.f.m`: an image that builds
        and then dies in the loader. A frame slot is explicitly NOT a
        register or spill home (`_collect_var_names` leaves it out for
        exactly that reason), so the membership test below has to be extended
        rather than left to find it by accident."""
        if isinstance(obj, F.StringLiteral):
            return True
        if isinstance(obj, F.IdentExpr):
            return obj.name in self._var_regs or obj.name in self._var_spills
        if isinstance(obj, F.MemberExpr):
            key = _member_slot_key(obj)
            if key is None:
                return False
            return (key in self._var_regs or key in self._var_spills
                    or key in self._frame_slots)
        return False

    def _emit_value_method(self, e: F.CallExpr, method: str) -> None:
        """`recv.method(...)` where `recv` is a local value."""
        obj = e.func.obj if isinstance(e.func, F.MemberExpr) else None
        reason = M.value_method_refusal(
            method, self._method_recv_kind(e), _dotted(e.func),
            receiver_is_fd=self._expr_is_fd(obj),
            receiver_shape=M.receiver_shape(obj))
        if reason is not None:
            raise CodegenError(reason)
        if e.kwargs:
            raise CodegenError(
                f"{_dotted(e.func)}() takes no keyword arguments on the formal "
                f"arm64 path (got {[k for k, _v in e.kwargs]})")
        how = M.builtin_value_method(method) or M.pointer_bounded_method(method)
        if how == "list_append":
            self._emit_list_append(e)
        elif how == "file_write":
            self._emit_file_write(e)
        elif how == "file_close":
            self._emit_file_close(e)
        elif how == "str_lstrip":
            self._emit_str_lstrip(e)
        elif how in ("str_startswith", "str_endswith"):
            self._emit_str_affix(e, at_end=how == "str_endswith")
        elif how == "str_find":
            self._emit_str_find(e)
        elif how == "str_count":
            # EXPLICIT, and it was implicit until this wave: `count`'s lowering
            # was the `else` below, so every method name with no lowering of its
            # own was answered by calling `str.count` on its receiver.  See the
            # comment on the `else`.
            self._emit_str_count(e)
        else:
            # `_emit_str_count` WAS this arm, and the fall-through was invisible
            # in two directions at once.  `how` is
            # `builtin_value_method(method) or pointer_bounded_method(method)`,
            # so a name in NEITHER table reaches the arm; and `count`'s own
            # lowering was the arm rather than an explicit case, so the arm
            # meant two different things at different times.
            #
            # The consequence, measured: any method name that `value_method_
            # refusal` above let through with no `how` of its own was answered
            # by calling `str.count` on its receiver.  For a zero-argument
            # method that surfaced as `str.count() takes exactly one argument on
            # this path (got 0)` — which is how a `value()` newly made
            # answerable by this wave's pointer value model reported `str.count`
            # as its blocker, and a reader would have gone looking for a
            # counting bug in a module with no counting in it.  For a
            # ONE-argument method it would have counted the receiver's bytes
            # and returned the number.
            #
            # `count` is now an explicit arm above, and this arm means what it
            # says: a method with no lowering is refused as one.  It should be
            # unreachable — every `how` both tables produce is covered by an arm
            # above — and saying so is the point: an unreachable arm that once
            # silently did the wrong thing is worth making a loud one.
            raise CodegenError(
                f"{_dotted(e.func)}() is a method call on a value and this "
                f"backend has no lowering for {method!r}, which reached the "
                f"value-method dispatch with `how` = {how!r}. Every lowering "
                f"both tables name is matched by an explicit arm above, so this "
                f"is a table entry with no arm rather than a construct: "
                f"`method` resolved to {how!r} and nothing claimed it. Refused "
                f"rather than lowered as the nearest arm, which is how a "
                f"zero-argument method came to be reported as "
                f"`str.count() takes exactly one argument (got 0)`")

    # ── the pointer value model: a DEREFERENCE ─────────────────────────────
    #
    # `recv.value()` / `recv.unsafe_value()` on a POINTER is a load, and the
    # load's WIDTH is the pointee's — which `model.dereference_lowering` has
    # established from a declared type, or has refused.  There is no width this
    # emitter is allowed to choose, and that is the entire point: the pre-change
    # tree could only have emitted an 8-byte load, which over-reads a `UInt8`
    # pointee by seven bytes and faults at a page edge (see the measurement in
    # `bugs/FORMAL_pointer_value_model.md`).
    #
    # The two answers and the two instructions:
    #
    #   ("load", 1, unsigned)  LDRB Wt, [Xn]          — `UInt8`/`Byte`
    #   ("load", 1, signed)    LDRSB Xt, [Xn]         — `Int8`/`c_char`
    #   ("load", 2, signed)    LDRSH Xt, [Xn]         — `Int16`/`c_short`
    #   ("load", 2, unsigned)  LDRH  Wt, [Xn]          — `UInt16`
    #   ("load", 4, signed)    LDRSW Xt, [Xn]         — `Int32`/`c_int`
    #   ("load", 4, unsigned)  LDR   Wt, [Xn]          — `UInt32`/`SIMDSize`
    #   ("load", 8, signed)    LDR   Xt, [Xn]          — `Int64`/`c_long`
    #   ("load", 8, unsigned)  LDR   Xt, [Xn]          — `Int`/UInt64/a pointer
    #
    # A STRUCT pointee has no instruction here and that is a decision, not an
    # omission: the derivation says the answer is the receiver — a struct's
    # value on this path IS its frame address, the same identity `Pointer()`
    # gives — and emitting it today returns 0 where the source says 22 on BOTH
    # architectures, because nothing recognises a name bound through a pointer
    # as a frame holder.  `model.dereference_lowering` says so at length; the
    # next step is one line in `formal/build.py`'s holder fixpoint.
    #
    # A 1-byte and a 2-byte load are sign- or zero-EXTENDED into the 64-bit X
    # register, because a formal value is one 64-bit word and the program will
    # treat the result as one: `UInt8 200` must read back as 200 and `Int8 -1`
    # as 2^64-1.  `LDRB` is already a zero-extend and `LDRSB` the sign-extend,
    # so the unsigned and signed 1-byte cases are the same instruction with a
    # different mnemonic, and the 2-byte pair likewise.
    def _emit_dereference(self, e: F.CallExpr, method: str) -> None:
        if e.args or e.kwargs:
            raise CodegenError(
                f"{_dotted(e.func)}() takes no arguments on the formal arm64 "
                f"path (got {[M.dotted_receiver(a) for a in e.args]})")
        obj = e.func.obj
        how, why = M.dereference_lowering(
            self._cur_fn, obj, self._structs, self._functions, self._structs)
        if how is None:
            raise CodegenError(M.dereference_refusal(
                method, why,
                M.receiver_declared_is_pointer(self._cur_fn, obj, self._structs)
            ).format(dotted=_dotted(e.func)))
        _load, width, signed = how
        self._emit_expr(obj)                    # X0 = the address
        if width == 1:
            self.asm.emit(encode_ldrsb_xt_xn_imm(0, 0, 0) if signed
                          else encode_ldrb_wd_wn(0, 0, 0))
        elif width == 2:
            self.asm.emit(encode_ldrsh_xt_xn_imm(0, 0, 0) if signed
                          else encode_ldrh_wt_wn_imm(0, 0, 0))
        elif width == 4:
            self.asm.emit(encode_ldrsw_xt_xn_imm(0, 0, 0) if signed
                          else encode_ldr_wt_wn_imm(0, 0, 0))
        else:
            self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))

    # ── methods on a string ───────────────────────────────────────────────
    #
    # All of these are pointer-bounded: their answer is a function of the bytes
    # from the receiver to its NUL, and libSystem already implements each one.
    # The instructions below are therefore selection, not algorithm — a
    # hand-written scan would be a second implementation of `strstr` that could
    # be subtly wrong, where a call cannot. `model.POINTER_BOUNDED_METHODS` is
    # the list, and the reason each method is on it and not on the other table
    # is written there.
    #
    # The one thing every one of these needs and does not assume is that the
    # receiver IS a char *: `value_method_refusal` has already established
    # that, and it is the check that stops `mlir_value.value()` (359 of the
    # method calls in the stdlib) from being read as a string operation.

    def _method_recv_kind(self, e: F.CallExpr):
        """What the receiver of a method call holds, for the model's guard.

        Literally the question `_expr_str_kind` already answers, under the same
        precedence: the flow-sensitive `_string_vars` map is strictly better
        informed than the whole-function `ValueKinds`, and it covers the case
        that matters most here — a name bound to a string literal in an earlier
        statement of this very function."""
        obj = e.func.obj if isinstance(e.func, F.MemberExpr) else None
        return None if obj is None else self._expr_str_kind(obj)

    def _emit_b_cond_to(self, cond: str, label: str) -> None:
        """A conditional branch to a forward label (relocation-based)."""
        self.asm.emit(encode_b_cond(cond, 0))
        self.asm.emit_label_rel(label, here_offset=-4)

    def _emit_str_lstrip(self, e: F.CallExpr) -> None:
        """`s.lstrip()` — an INTERIOR pointer to the first non-whitespace byte.

        `strspn(s, STRIP_CHARS)` IS the left-strip: it returns the length of the
        initial segment of `s` made only of those characters, so `s + that` is
        the answer. Nothing is written and nothing is copied — the bytes from
        there to the receiver's existing NUL are already the result, which is
        what makes this pointer-bounded and `strip` not (see
        model.LENGTH_DEPENDENT_METHODS["strip"], where the measured `maxprot`
        and the wrong answer a pointer-only version gives are both recorded).

        The character set is model.STRIP_CHARS, ONE definition for both
        backends. An earlier version hand-wrote the scan loop per architecture
        and each copy had its own bug."""
        _emit_sub_imm(self.asm, 31, 31, 32)
        self._emit_expr(e.func.obj)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))          # [sp+0] = s
        self._emit_expr(F.StringLiteral(M.STRIP_CHARS))
        self.asm.emit(encode_mov_zr_xn(1, 0))                  # X1 = the set
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))          # X0 = s
        self._emit_extern_call("strspn")
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 0))
        self.asm.emit(encode_add_xd_xn_xm(0, 0, 1))           # s + strspn(s)
        _emit_add_imm(self.asm, 31, 31, 32)

    def _emit_str_affix(self, e: F.CallExpr, *, at_end: bool) -> None:
        """`s.startswith(p)` / `s.endswith(p)` — a bounded compare, 0 or 1.

        Both are `strncmp(...) == 0`, and `strncmp` stops at the first
        difference or at a NUL in either operand, so neither can read past the
        end of a NUL-terminated buffer. An empty affix is a zero-length
        compare, which compares equal, which is the "yes" Python gives.

        `endswith` compares from `s + len(s) - len(p)`, so the lengths are
        needed first AND the suffix has to be shown not to be longer than the
        receiver: without that test the subtraction underflows and `strncmp`
        reads before the start of the buffer. The test is unsigned, matching
        the signedness `strlen` actually returns."""
        args = list(e.args)
        name = "str.endswith" if at_end else "str.startswith"
        if len(args) != 1:
            raise CodegenError(
                f"{name}() takes exactly one argument on this path "
                f"(got {len(args)})")
        if not at_end:
            # [sp+0] the receiver, [sp+8] the affix.
            _emit_sub_imm(self.asm, 31, 31, 32)
            self._emit_expr(e.func.obj)
            self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))
            self._emit_expr(args[0])
            self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))
            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))
            self._emit_extern_call("strlen")
            self.asm.emit(encode_mov_zr_xn(2, 0))            # X2 = len(p)
            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))     # X0 = s
            self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))     # X1 = p
            self._emit_extern_call("strncmp", 3)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cset_xd_cond(0, "eq"))
            _emit_add_imm(self.asm, 31, 31, 32)
            return
        # [sp+0] s, [sp+8] p, [sp+16] len(s), [sp+24] len(p)
        self._while_counter += 1
        no_label = f"{self.func_name}_endswith{self._while_counter}_no"
        done_label = f"{self.func_name}_endswith{self._while_counter}_done"
        _emit_sub_imm(self.asm, 31, 31, 32)
        self._emit_expr(e.func.obj)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))
        self._emit_expr(args[0])
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))
        self._emit_extern_call("strlen")
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 24))        # len(p)
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))
        self._emit_extern_call("strlen")
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 16))        # len(s)
        self.asm.emit(encode_ldr_xt_xn_imm(2, 31, 16))        # X2 = len(s)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 24))        # X1 = len(p)
        self.asm.emit(encode_cmp_xn_xm(2, 1))
        self._emit_b_cond_to("lo", no_label)                  # len(s) < len(p)
        # X0 = s + len(s) - len(p)
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 16))
        self.asm.emit(encode_add_xd_xn_xm(0, 0, 1))
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 24))
        self.asm.emit(encode_sub_xd_xn_xm(0, 0, 1))
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))         # X1 = p
        self.asm.emit(encode_ldr_xt_xn_imm(2, 31, 24))        # X2 = len(p)
        self._emit_extern_call("strncmp", 3)
        self.asm.emit(encode_cmp_xn_imm(0, 0))
        self.asm.emit(encode_cset_xd_cond(0, "eq"))
        self._emit_b_to(done_label)
        self.asm.label(no_label)
        self.asm.emit(encode_movz_xd_imm(0, 0))
        self.asm.label(done_label)
        _emit_add_imm(self.asm, 31, 31, 32)

    def _emit_str_find(self, e: F.CallExpr) -> None:
        """`s.find(p)` — the index of the first occurrence, or -1.

        `strstr` walks both operands to their NULs, so the answer is exactly
        the difference of two pointers, and the one case that has to be handled
        is "not found", which is a NULL rather than a position: -1 is what
        Python returns, and returning the NULL's own low bits would be a
        plausible-looking address. An empty needle makes `strstr` return the
        receiver itself, i.e. 0, which is also what Python returns.

        The argument order is `strstr(HAYSTACK, NEEDLE)` and it is the whole
        method: `strstr("bc", "abcabcabc")` is a well-defined NULL, so getting
        it backwards does not crash and does not look wrong in the image — it
        returns -1 for every haystack that contains its needle, which is every
        real use of `find`. `strncmp` is symmetric and does not care; `strstr`
        is not, and this one was backwards in a first version of this code."""
        args = list(e.args)
        if len(args) != 1:
            raise CodegenError(
                f"str.find() takes exactly one argument on this path "
                f"(got {len(args)})")
        self._while_counter += 1
        no_label = f"{self.func_name}_find{self._while_counter}_no"
        done_label = f"{self.func_name}_find{self._while_counter}_done"
        _emit_sub_imm(self.asm, 31, 31, 32)
        self._emit_expr(e.func.obj)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))          # [sp+0] = s
        self._emit_expr(args[0])
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))          # [sp+8] = p
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))          # X0 = s
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))          # X1 = p
        self._emit_extern_call("strstr")
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(no_label, here_offset=-4)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 0))
        self.asm.emit(encode_sub_xd_xn_xm(0, 0, 1))
        self._emit_b_to(done_label)
        self.asm.label(no_label)
        self._emit_mov_imm("X0", -1)
        self.asm.label(done_label)
        _emit_add_imm(self.asm, 31, 31, 32)

    def _emit_str_count(self, e: F.CallExpr) -> None:
        """`s.count(p)` — how many NON-OVERLAPPING occurrences.

        Non-overlapping is Python's rule and it is the whole of the loop: each
        match advances the cursor by the needle's length, so "aaa".count("aa")
        is 1 and not 2. Overlapping it would be a one-instruction difference
        and a silently wrong count.

        The empty needle is the case with no loop at all — it matches at every
        one of the L+1 positions in a string of length L, so the count is
        `strlen(s) + 1` — and it is also the case that would otherwise spin
        forever, since `strstr` returns the cursor unchanged for it."""
        args = list(e.args)
        if len(args) != 1:
            raise CodegenError(
                f"str.count() takes exactly one argument on this path "
                f"(got {len(args)})")
        self._while_counter += 1
        n = self._while_counter
        fn = self.func_name
        loop = f"{fn}_count{n}_loop"
        done = f"{fn}_count{n}_done"
        empty = f"{fn}_count{n}_empty"
        _emit_sub_imm(self.asm, 31, 31, 48)
        self._emit_expr(e.func.obj)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))          # [sp+0] s
        self._emit_expr(args[0])
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))          # [sp+8] p
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))
        self._emit_extern_call("strlen")
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 16))         # [sp+16] len(p)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 16))
        # NOTE the argument order: encode_cbz_xn takes (offset, register), so
        # the register goes SECOND. Written the other way round this is
        # `cbz x0` with a one-word offset — it tests the strlen result, which
        # is not zero, so the empty-needle case is never taken and count("")
        # walks off into the loop instead. Every other call in this file has
        # the register second; this one had it first.
        self.asm.emit(encode_cbz_xn(0, 1))
        self.asm.emit_label_rel(empty, here_offset=-4)
        self.asm.emit(encode_ldr_xt_xn_imm(3, 31, 0))
        self.asm.emit(encode_str_xt_xn_imm(3, 31, 24))         # cursor = s
        self.asm.emit(encode_movz_xd_imm(3, 0))
        self.asm.emit(encode_str_xt_xn_imm(3, 31, 32))         # count = 0
        self.asm.label(loop)
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 24))
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))
        self._emit_extern_call("strstr")
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(done, here_offset=-4)
        self.asm.emit(encode_ldr_xt_xn_imm(3, 31, 32))
        self.asm.emit(encode_add_xd_xn_imm(3, 3, 1))
        self.asm.emit(encode_str_xt_xn_imm(3, 31, 32))
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 16))
        self.asm.emit(encode_add_xd_xn_xm(0, 0, 1))            # hit + len(p)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 24))
        self._emit_b_to(loop)
        self.asm.label(empty)
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))
        self._emit_extern_call("strlen")
        # An empty needle matches BETWEEN every pair of adjacent characters as
        # well as at each end, so a string of length L has L+1 positions and
        # the answer is L+1 — not L. `"".count("")` is 1 and `"ab".count("")`
        # is 3, which is the only place the off-by-one is visible.
        self.asm.emit(encode_add_xd_xn_imm(0, 0, 1))
        # Store into the SAME slot the loop accumulates into, because `done`
        # reads the answer from there and not from X0. Branching to `done` with
        # the answer only in X0 looks right and is not: the reload at `done`
        # overwrites it with the loop's counter, which is 0 on this path, so
        # every count("") returned 0. Both paths now leave the answer in one
        # place.
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 32))
        self._emit_b_to(done)
        self.asm.label(done)
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 32))
        _emit_add_imm(self.asm, 31, 31, 48)

    def _emit_list_append(self, e: F.CallExpr) -> None:
        """`xs.append(v)` — store v at the blob's count and bump the count.

        The blob is `[count:i64][elem0]…` in the frame, so there is no room to
        grow one: the capacity is a compile-time number (`_scan_list_caps`)
        and the store is checked against it, exiting(1) rather than writing
        past the blob. Appending more times than the scan found — inside a
        loop — therefore stops the program instead of quietly corrupting the
        frame, the same bargain `xs[i]` out of range makes.

        Returns 0, which is this model's `None`: `list.append` returns None,
        and nothing in the language can observe the difference between that and
        a zero that a program then printed as a number, but returning the new
        count would be a value Python does not have."""
        args = list(e.args)
        if len(args) != 1:
            raise CodegenError(
                f"list.append() takes exactly one argument on this path "
                f"(got {len(args)})")
        recv = e.func.obj
        cap = self._list_caps_by_name.get(
            recv.name if isinstance(recv, F.IdentExpr) else None)
        if cap is None:
            raise CodegenError(
                f"list.append() is not lowered on the formal arm64 path: a "
                f"list blob lives in the frame, so the room an append needs "
                f"has to be known when the list is built. This one is not "
                f"(the receiver is not a list literal this function appends "
                f"to, or it is also bound to something that is not a list)")
        self._emit_expr(recv)
        # [sp+0] = the blob base, [sp+8] = the value. The push stores the base
        # and a junk word; the value goes in the second slot.
        self.asm.emit(encode_stp_sp_pre(0, 2))
        self._emit_expr(args[0])
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))
        self.asm.emit(encode_ldr_xt_xn_imm(4, 31, 0))       # X4 = base
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))       # X0 = value
        self.asm.emit(encode_ldr_xt_xn_imm(1, 4, 0))        # X1 = count
        self._emit_mov_imm("X2", cap)
        self.asm.emit(encode_cmp_xn_xm(1, 2))
        self.asm.emit(encode_cset_xd_cond(3, "cs"))        # X3 = count >= cap
        self._while_counter += 1
        oob = f"{self.func_name}_appoob{self._while_counter}"
        ok = f"{self.func_name}_appok{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(oob, here_offset=-4)
        # value slot = base + 8 + 8*count
        self.asm.emit(encode_add_xd_xn_xm_lsl3(5, 4, 1))
        self.asm.emit(encode_add_xd_xn_imm(5, 5, 8))
        self.asm.emit(encode_str_xt_xn_imm(0, 5, 0))
        self.asm.emit(encode_add_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 4, 0))       # count = n + 1
        self.asm.emit(encode_ldp_sp_post(0, 31))
        self._emit_b_to(ok)
        self.asm.label(oob)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok)
        self.asm.emit(encode_movz_xd_imm(0, 0))     # None

    def _emit_file_write(self, e: F.CallExpr) -> None:
        """`f.write(s)` — `write(fd, s, strlen(s))` through the C library.

        `open(...)` on this path is already the C library's `open` (left to the
        extern path, which is right for it: libSystem defines it), so the
        receiver of a file method IS a descriptor and there is no file object
        to take apart. The length has to be computed, because a `char *` here
        has no header — the same reason `len()` of a string is refused."""
        args = list(e.args)
        if len(args) != 1:
            raise CodegenError(
                f"file.write() takes exactly one argument on this path "
                f"(got {len(args)})")
        # Three values have to survive the strlen call and there is no callee-
        # saved register free, so they go in a 32-byte window: [sp+0] the
        # descriptor, [sp+8] the string, [sp+16] the length strlen returns.
        # 32 rather than 24 so SP is still 16-byte aligned at the call, which
        # is what the C library assumes.
        _emit_sub_imm(self.asm, 31, 31, 32)
        self._emit_expr(e.func.obj)               # X0 = fd
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))
        self._emit_expr(args[0])
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))
        self._emit_extern_call("strlen")
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 16))     # [sp+16] = length
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))      # X1 = string
        self.asm.emit(encode_ldr_xt_xn_imm(2, 31, 16))     # X2 = length
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))      # X0 = fd
        self._emit_extern_call("write")
        _emit_add_imm(self.asm, 31, 31, 32)

    def _emit_file_close(self, e: F.CallExpr) -> None:
        """`f.close()` — the C library's `close` on the descriptor."""
        if e.args:
            raise CodegenError(
                f"file.close() takes no arguments on this path "
                f"(got {len(e.args)})")
        self._emit_expr(e.func.obj)
        self._emit_extern_call("close")

    def _emit_open(self, e: F.CallExpr) -> None:
        """`open(path, mode)` — the C library's `open(2)`.

        The mode is a Python spelling (`"w"`) and the C function wants a flag
        word, so the translation happens here rather than at the call: passing
        the mode STRING as the flags word is not a wrong answer, it is a wrong
        SYSTEM CALL — the low bits of a pointer are O_RDONLY and a garbage
        permission word, which is how `open(p, "w")` produced a file nobody
        could read.

        A descriptor is returned whatever happens, and a failure is NOT turned
        into an exit: the language raises for it, and this model has no way to
        raise from inside a call. A program that checks the descriptor sees -1,
        exactly as the C library reports it."""
        args = list(e.args)
        if len(args) not in (1, 2) or e.kwargs:
            raise CodegenError(
                f"open() takes a path and an optional mode on this path "
                f"(got {len(args) + len(e.kwargs)})")
        mode = "r"
        if len(args) == 2:
            mode_arg = args[1]
            if not isinstance(mode_arg, F.StringLiteral):
                raise CodegenError(
                    f"open()'s mode must be a string literal on the formal "
                    f"arm64 path (got {type(mode_arg).__name__}): a string is "
                    f"a bare char * and the flags word is built before the "
                    f"call is emitted")
            mode = mode_arg.value
        flags = M.OPEN_FLAGS.get(mode)
        if flags is None and mode.endswith("+"):
            base = M.OPEN_FLAGS.get(mode[:-1])
            flags = None if base is None else base | M.OPEN_READ_WRITE
        if flags is None:
            raise CodegenError(
                f"open(): mode {mode!r} is not lowered on the formal arm64 "
                f"path (supports {', '.join(sorted(set(M.OPEN_FLAGS)))}, each "
                f"with an optional trailing '+')")
        # [sp+0] = the path, [sp+8] = the flag word. The permission word goes in
        # X2 AND through the variadic tail, because Apple's open(2) reads it
        # from the area (see model.VARIADIC_LIBC); X2 is set as well so the
        # register convention is not violated for anything that does read it
        # there. The result has to be put back in the push slot BEFORE the pop,
        # because the pop loads [sp+0] into X0 and would otherwise hand the
        # caller the path back instead of the descriptor.
        self._emit_expr(args[0])                   # X0 = path
        self.asm.emit(encode_stp_sp_pre(0, 2))
        self._emit_mov_imm("X0", flags)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))      # X0 = path
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))      # X1 = flags
        self._emit_mov_imm("X2", M.OPEN_CRE_MODE)          # X2 = mode
        self._emit_extern_call("open", 3)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))      # keep the result
        self.asm.emit(encode_ldp_sp_post(0, 31))

    def _emit_extern_call(self, symbol: str, total: int = 0) -> None:
        """Call a C library function by name (AAPCS: X0..X7, result in X0).

        Goes through the same variadic convention as the generic extern path
        (`_emit_call`), because the file builtins below are called by name
        rather than through a CallExpr. `total` is how many arguments are in the
        registers right now, which is what decides whether a variadic tail has
        to be laid out; a name that is not variadic ignores it."""
        area = self._emit_variadic_area(symbol, total)
        self.asm.emit_extern_bl(self._dylib_syms.get(symbol, symbol))
        if area:
            self.asm.emit(encode_add_xd_xn_imm(31, 31, area))

    def _emit_variadic_area(self, symbol: str, total: int) -> int:
        """Build a variadic call's unnamed-argument area. Returns bytes to pop.

        Apple arm64 does not pass a variadic function's `...` arguments in
        registers: the caller reserves an area and the i-th unnamed argument
        goes at offset 8*(i-1) from SP as it stands at the call, ascending. The
        values are already in X1..X7 (the ordinary argument shuffle put them
        there), so this copies them down and gives the space back afterwards.

        Returns 0 for a non-variadic callee, and for a variadic one with no
        unnamed arguments — so a call like `printf("hello")` emits exactly what
        it always did."""
        named = M.variadic_named_args(symbol)
        if named is None or total <= named:
            return 0
        unnamed = total - named
        if unnamed > M.VARIADIC_SLOTS:
            raise CodegenError(
                f"call {symbol.lstrip('_')}(): {unnamed} variadic arguments "
                f"exceeds the {M.VARIADIC_SLOTS} the Apple arm64 variadic area "
                f"holds")
        size = 8 * M.VARIADIC_SLOTS
        self.asm.emit(encode_sub_xd_xn_imm(31, 31, size))
        for i in range(unnamed):
            self.asm.emit(encode_str_xt_xn_imm(named + i, 31, 8 * i))
        return size

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
        # One SUB from the frame pointer, not mov-then-three-subs. The total
        # is a compile-time constant, and with the shifted-immediate form it
        # almost always fits in a single instruction; expressing it as
        # separate steps also made the codegen fragile, since the saved-pair
        # and blob offsets are only meaningful relative to the scratch base
        # this line is computing.
        total = _SCRATCH + 16 * self._npairs - offset
        _emit_sub_imm(self.asm, 9, 29, total)

    def _emit_empty_blob(self) -> None:
        """The empty container: eight bytes with a zero count, base in X0.

        `List()`, `List[Int]()`, `Dict()` and the rest of
        `model.EMPTY_BLOB_CTORS`, and it is `_emit_list` with `n == 0` — the
        same eight bytes, the same `[count][elements]` layout and the same
        reservation, because an empty container IS the zero-element literal, and
        the instruction sequence below is `_emit_list`'s with its loop deleted.

        Its own method rather than a call into `_emit_list` with a synthesised
        `ListExpr`, and the reason is that the two are NOT the same code with a
        different argument: `_emit_list` also handles a star-unpack, reserves
        CAPACITY slots when the function appends to the literal, and says
        "list literals exceed the formal frame" when the reservation does not
        fit. None of those applies here — there is nothing to unpack, and
        appending to an empty container built by a CONSTRUCTOR is a different
        question that `_scan_list_caps` does not answer — and a reader who had
        to work out which of `_emit_list`'s four behaviours a constructor
        inherits would be reasoning about the wrong thing. So the eight bytes
        are written out, the shared parts (`_emit_list_base`,
        `_emit_mov_imm`, the store) being the same calls in the same order as
        `_emit_list` uses, so the two layouts cannot drift.
        """
        if self._list_cursor + 8 > self._blob_cap:
            raise CodegenError(
                f"an empty container exceeds the formal frame "
                f"({self._list_cursor + 8} > {self._blob_cap} bytes)")
        offset = self._list_cursor
        self._list_cursor += 8
        self._emit_list_base(offset)
        self._emit_mov_imm("X10", 0)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_list(self, expr: F.ListExpr) -> None:
        """Stack-allocate a list blob: [count:i64][elem0]...[elemN-1].

        X0 exits holding the blob address (pointer-sized, no heap). Elements
        are int64s or string/inner-list pointers. Cursor reserves the full
        blob before any element is evaluated so nested lists sit above it.
        Exits without moving SP — the blob lives until the function returns.
        Star-unpack elements have no compile-time length and raise.

        The blob is allocated with CAPACITY slots, not `n` of them, when the
        function appends to this literal (see `_scan_list_caps`): the count
        field still starts at `n`, so every reader of the blob is unchanged,
        and the slots past the count are the room `append` writes into."""
        has_star = any(isinstance(el, F.UnaryOp) and el.op == "*"
                       for el in expr.elements)
        if has_star:
            self._emit_list_star(expr)
            return
        n = len(expr.elements)
        cap = max(n, self._list_caps.get(id(expr), n))
        size = 8 * (1 + cap)
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
        # Any operator that reaches the integer ALU or the flag-setting compare
        # with a `char *` operand is refused, and this is the only place that
        # knows both operand kinds before that happens. Measured on the
        # pre-change tree, on BOTH backends: `print("ab" + "cd")` printed `[]`
        # on arm64 and segfaulted on x86-64 — one wrong answer and one crash
        # from one line of source — and `s ^ t` returned 4 on arm64 and 28 on
        # x86-64, which is the same defect with the crash replaced by two
        # architectures disagreeing about a number neither computed. See
        # `model.string_binary_refusal`, which is the one table both backends
        # ask and which holds the measurements.
        reason = M.string_binary_refusal(
            op, self._expr_str_kind(e.left), self._expr_str_kind(e.right),
            left=e.left, right=e.right, fn=self._cur_fn,
            untyped_callee=self._untyped_callee)
        if reason is not None:
            raise CodegenError(reason)
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
            if op in ("==", "!=") and self._emit_strcmp_flags(e.left, e.right):
                self.asm.emit(encode_cset_xd_cond(
                    0, "ne" if op == "!=" else "eq"))
                return
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

    def _emit_strcmp_flags(self, l, r) -> bool:
        """`l == r` on two STRINGS as `strcmp(l, r) == 0`. True if it emitted.

        The flags are left EQ (or the caller's negation of it) with nothing
        after them, so the value path CSETs and the branch path B.conds — the
        same split `_emit_cmp` / `_emit_cmp_flags` already make for integers.

        WHY CONTENT, measured rather than assumed. `==` on two strings used to
        compare the two POINTERS. That is right for two interned literals —
        interning is by content, so equal literals are the same object — and
        wrong for every derived interior pointer, which is exactly what
        `lstrip` returns and what every sub-range method would return:

            m = "  abc".lstrip()
            if m == "abc": ...        # NOT taken, on both backends

        A correct program taking the wrong branch, which is worse than a wrong
        number: nothing downstream can tell. `is` / `is not` keep the pointer
        compare, which for them is the answer and not an approximation of it;
        `model.string_comparison_lowering` is what keeps the two pairs apart and
        is shared with the x86-64 backend so they cannot come apart there.

        The 32-byte scratch area and the load-back are the same shape
        `_emit_str_affix` uses for `strncmp`, for the reason its comment gives:
        an expression leaves its value in X0, and a nested call clobbers every
        caller-saved register, so both operands have to survive the call.
        """
        if M.string_comparison_lowering(
                "==", self._expr_str_kind(l), self._expr_str_kind(r),
                l, r) != M.STRING_COMPARE_CONTENT:
            return False
        # [sp+0] l, [sp+8] r, [sp+16] len(r). The same scratch area and the
        # same store-then-reload discipline `_emit_str_affix` uses for
        # `strncmp`, for the reason its comment gives: an expression leaves its
        # value in X0, and a call clobbers every caller-saved register, so
        # both operands and the length have to survive the two calls.
        _emit_sub_imm(self.asm, 31, 31, 32)
        self._emit_expr(l)
        # X0 for BOTH stores, and that is the contract `_emit_expr` states: an
        # expression leaves its value in X0. Storing X1 instead is the kind of
        # slip that works until the register allocator moves something into X1.
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))
        self._emit_expr(r)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))        # X0 = r
        self._emit_extern_call("strlen")                    # X0 = len(r)
        self.asm.emit(encode_add_xd_xn_imm(0, 0, 1))        # n = len(r) + 1
        self.asm.emit(encode_mov_zr_xn(2, 0))                # X2 = n
        # X1 is reloaded from the slot AFTER the strlen, not before it: a call
        # clobbers every caller-saved register, so a pointer parked in X1
        # before the call is garbage after it. Measured — with the reload
        # before the call, `"abc" == "abc"` was FALSE on arm64 and TRUE on
        # x86-64, which is the worst shape a two-backend lowering can have.
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))        # X1 = r
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))        # X0 = l
        self._emit_extern_call(M.STRING_COMPARE_SYMBOL, 3)  # X0 = 0 iff equal
        # The SP restore comes BEFORE the compare on purpose: ADD (immediate)
        # sets no flags on this architecture, but putting it first means the
        # CMP below is unconditionally the last flag-setter, which is a
        # property a reader can check rather than one they have to know.
        _emit_add_imm(self.asm, 31, 31, 32)
        self.asm.emit(encode_cmp_xn_imm(0, 0))              # EQ iff equal
        self._signed = False
        return True

    def _emit_cmp_flags(self, l, r, unsigned_cond: str, signed_cond: str) -> None:
        """CMP only — no CSET.

        Split out of _emit_cmp so a conditional can branch on the flags
        directly. With the CSET in the middle, `if a < b` cost cmp + cset +
        cbz: the boolean was materialised into a register only for the very
        next instruction to read it back. B.cond reads the flags the compare
        already set."""
        self._emit_expr(l)
        self.asm.emit(encode_stp_sp_pre(0, 2))
        self._emit_expr_to(r, "X1")
        self.asm.emit(encode_ldp_sp_post(0, 2))
        self.asm.emit(encode_cmp_xn_xm(0, 1))
        self._signed = cmp_signed(common_type(self._ttype(l), self._ttype(r)))

    def _emit_truthy_word(self, expr, reg: str = "X0") -> None:
        """Evaluate `expr` into `reg` so that its ZERONESS is its truthiness.

        THE truthiness conversion, and every site that tests a condition for
        truth rather than for equality goes through it. What it produces is a
        WORD whose zero/nonzero is the answer — not a 0/1 — so a branch site
        can keep the `cmp #0` / `cbz` pair it already had and a value site
        (`s and k`) can use the word directly, which is what Python's `and`/
        `or` want anyway (they return an operand, not a bool).

        Three lowerings, chosen by `model.truthy_lowering` on the operand's
        kind, and the flag ZERONESS is the same for all of them:

          TRUTHY_NONZERO         the word itself. Right for an integer (the
                                only falsy integer is 0) and for a FRAME
                                ADDRESS, whose truthiness is pointer
                                truthiness — a frame is never mapped at 0.
          TRUTHY_FROM_STRLEN     `strlen(s)`. The empty string is a NON-NULL
                                pointer, so the row above would say it is
                                truthy; `strlen("") == 0` is the answer, and
                                it is the same computation `len(s)` makes
                                with a symbol this backend already calls.
          TRUTHY_FROM_BLOB_FIELD one load from offset 0. A list blob is
                                `[count:i64][elem…]`, so its truthiness IS
                                its count — and an empty list blob's count
                                is 0, so `if []:` was FALSE-for-the-right-
                                reason only by accident before this.

        The empty string is the case that separates a correct lowering from a
        null test, so it is the case to check any change here against.

        A SHORT-CIRCUIT CHAIN is handled here rather than in the three rows
        above, and it is the row that is easy to miss: `a and b` is a value
        whose truthiness is not the truthiness of the word it evaluates to.
        Python's `and`/`or` return an OPERAND, and the operand that survives
        can be an empty string or an empty list — so `if f and e:` with
        `e = []` selects `e`, and testing the selected word for zeroness says
        truthy because an empty list blob lives in a frame at a non-zero
        address. Measured on both backends, that printed `1` where Python
        prints `0`. The rule is the honest one and needs no kind at all:

            truthy(a and b)  =  truthy(a) and truthy(b)
            truthy(a or b)   =  truthy(a) or  truthy(b)

        — so this RECURSES into both operands and never materialises the chain
        as a value, which is what makes the answer independent of which operand
        the chain happens to return.
        """
        if isinstance(expr, F.BinaryOp) and expr.op in ("and", "or"):
            self._if_counter += 1
            tid = self._if_counter
            fn = self.func_name
            join = f"{fn}_trv{tid}_j"
            self._emit_truthy_word(expr.left)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            # or: nonzero → the left's word is already the answer; and: zero →
            # the left's word is already the answer. Only the right operand is
            # ever evaluated, which is the whole of short-circuiting.
            self.asm.emit(encode_cbnz_xn(0, 0) if expr.op == "or"
                          else encode_cbz_xn(0, 0))
            self.asm.emit_label_rel(join, here_offset=-4)
            self._emit_truthy_word(expr.right)
            self.asm.label(join)
            return
        how = M.truthy_lowering(self._expr_str_kind(expr), expr)
        self._emit_expr_to(expr, reg)
        if how == M.TRUTHY_FROM_STRLEN:
            if reg != "X0":
                self.asm.emit(encode_mov_zr_xn(0, _reg_num(reg)))
            self._emit_extern_call(M.STRING_LENGTH_SYMBOL)
        elif how == M.TRUTHY_FROM_BLOB_FIELD:
            self.asm.emit(encode_ldr_xt_xn_imm(
                _reg_num(reg), _reg_num(reg), 0))

    def _emit_branch_unless(self, cond, false_label: str) -> bool:
        """Branch to `false_label` unless `cond` holds. True if it emitted.

        A comparison becomes CMP + B.cond: one branch, and no boolean round
        trip through a register. Anything else — a call, a truthiness test, a
        short-circuit chain — is left to the caller, because those genuinely do
        need a value.

        Branching on the FALSE case keeps the shape of the old lowering: one
        conditional branch to the same target, recorded the same way, so the
        block structure the rest of the backend (and the proof generator's
        `_cond_branches` filter) already expects is unchanged.
        """
        if not (isinstance(cond, F.BinaryOp) and cond.op in self._cmp_conds()):
            return False
        # A comparison in a CONDITION does not go through `_emit_binop` — the
        # whole point of this function is to branch on the flags instead of
        # materialising a boolean — so the refusal has to be asked here too,
        # or `if s < t:` reaches the flag-setting compare while `r = s < t`
        # is refused. That is the worst version of the defect: the SAME
        # comparison is a diagnostic in one context and a branch decided by
        # the interning order of two literals in the other. Measured on the
        # pre-change tree: `s < t` was TRUE and `s > t` FALSE on both backends
        # for `s = "abc"`, `t = "bc"`, with no property of the program
        # deciding either.
        reason = M.string_binary_refusal(
            cond.op, self._expr_str_kind(cond.left),
            self._expr_str_kind(cond.right), left=cond.left, right=cond.right,
            fn=self._cur_fn, untyped_callee=self._untyped_callee)
        if reason is not None:
            raise CodegenError(reason)
        # A string `==`/`!=` is a `strcmp`, and the strcmp form leaves the flags
        # set, so the branch is the same B.cond on a different compare. Handled
        # here rather than in `_emit_branch_unless_cmp` because that function is
        # reached from the for-range test too, which builds its own operands and
        # has no operator to decide with.
        if cond.op in ("==", "!=") \
                and self._emit_strcmp_flags(cond.left, cond.right):
            self._record_cond_branch()
            self.asm.emit(encode_b_cond(
                invert_cond("ne" if cond.op == "!=" else "eq"), 0))
            self.asm.emit_label_rel(false_label, here_offset=-4)
            return True
        u, s = self._cmp_conds()[cond.op]
        self._emit_branch_unless_cmp(cond.left, cond.right, u, s, false_label)
        return True

    def _emit_branch_unless_cmp(self, l, r, unsigned_cond: str,
                                signed_cond: str, false_label: str) -> None:
        """CMP + B.cond on two already-separated operands, no CSET.

        The operand-level half of `_emit_branch_unless`, for the one caller
        that has a comparison's operands without the enclosing BinaryOp: the
        `for i in range(...)` test, which is built from the loop target and
        the range's end bound rather than parsed from source.
        """
        self._emit_cmp_flags(l, r, unsigned_cond, signed_cond)
        chosen = signed_cond if self._signed else unsigned_cond
        self._record_cond_branch()
        self.asm.emit(encode_b_cond(invert_cond(chosen), 0))
        self.asm.emit_label_rel(false_label, here_offset=-4)
        return True

    def _cmp_conds(self) -> dict:
        """Operator -> (unsigned condition, signed condition).

        Hoisted out of _emit_binop so the branch path and the value path
        cannot disagree about what `<` means. They did once, which is how a
        comparison came to branch one way and evaluate the other."""
        return {
            "<=": ("ls", "le"), ">": ("hi", "gt"), "==": ("eq", "eq"),
            ">=": ("cs", "ge"), "<": ("cc", "lt"), "!=": ("ne", "ne"),
            "is": ("eq", "eq"), "is not": ("ne", "ne"),
        }

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
        # Gated on the left needing NO CONVERSION as well as on the operands
        # being pure. The two forms below are branchless precisely because the
        # left is a LOAD whose word is already the answer, and a `strlen` is a
        # CALL: it clobbers X0, it clobbers the flags the CSEL reads, and the
        # `mov X1, X0` hoist below exists only because a load cannot. A string
        # or a list left falls through to the branching form at the end, which
        # is not the slower answer — it is the only one of the two that can
        # compute a length.
        if (M.truthy_lowering(self._expr_str_kind(left), left)
                == M.TRUTHY_NONZERO
                and self._is_pure_expr(left) and self._is_pure_expr(right)):
            # Branchless, and it also removes the block the proof generator
            # used to mistake for an `if`'s entry condition: a short-circuit
            # CBZ ends a basic block exactly like a real one does, which is
            # why `_cond_branches` exists as a filter at all.
            self._emit_expr(left)
            if (self._is_flag_preserving_load(left)
                    and self._is_flag_preserving_load(right)):
                # The left operand has to be moved out of X0 BEFORE the right
                # one is evaluated into it, or the left is simply lost — the
                # same overwrite that inverted the ternary. MOV does not write
                # the flags, so hoisting it above the compare is free.
                self.asm.emit(encode_mov_zr_xn(1, 0))    # X1 = left
                self.asm.emit(encode_cmp_xn_imm(0, 0))
                self._emit_expr(right)                  # X0 = right; a load
                # X1 is the LEFT and X0 the RIGHT, and the two operators read
                # that pair in opposite directions: `or` takes the left when it
                # is truthy, `and` takes the right. Collapsing them into one
                # CSEL compiles and inverts `and`.
                if is_or:
                    self.asm.emit(encode_csel_xd_xm_cond(0, 1, 0, "ne"))
                else:
                    self.asm.emit(encode_csel_xd_xm_cond(0, 0, 1, "ne"))
                return
            self.asm.emit(encode_stp_sp_pre(0, 31))
            self._emit_expr(right)
            self.asm.emit(encode_mov_zr_xn(1, 0))       # X1 = right
            self.asm.emit(encode_ldp_sp_post(0, 31))   # X0 = left
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            # Same condition for both — "is the left truthy" — and only the
            # OPERANDS differ, because that is the whole difference between
            # them: `or` keeps the left when it is truthy, `and` keeps the
            # right. Swapping the condition instead of the operands compiles
            # and inverts the operator, which is exactly what it did first
            # time: `5 and 9` returned 5.
            if is_or:
                self.asm.emit(encode_csel_xd_xm_cond(0, 0, 1, "ne"))
            else:
                self.asm.emit(encode_csel_xd_xm_cond(0, 1, 0, "ne"))
            return
        self._if_counter += 1
        aid = self._if_counter
        fn = self.func_name
        end_label = f"{fn}_ao{aid}_end"
        skip_label = f"{fn}_ao{aid}_skip"
        self._emit_truthy_word(left)
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
        """`needle in haystack` / `needle not in haystack`, list blob or string.

        Two haystacks, and which one this is has to be decided BEFORE anything
        is emitted, because the two share no code at all: a list haystack is a
        frame-allocated blob whose first 8 bytes are its count, and a string
        haystack is a `char *` into the image's read-only text. Reading a blob
        count out of a string is how `"ell" in s` used to die with SIGBUS — the
        first eight CHARACTERS were taken for a count and the scan walked off
        the end of the mapping — so the question is asked first and the string
        case is dispatched before the blob case is even considered.

        The decision itself is `model.string_membership_lowering`, shared with
        the x86-64 backend, so the two architectures cannot come apart on which
        of the two a given haystack is. Neither can they come apart on the
        RESULT: 0/1 in X0, `not in` inverted, and a bool is an int on this
        path because there is no BOOL kind distinct from INT (which is why
        `__mlir_bool__` is refused) — the same 0/1 the blob scan has always
        produced, so a caller cannot tell the two apart except by being right.

        List RHS must lower to a formal list blob `[count:i64][elem…]` —
        IdentExpr, CallExpr, ListExpr, TupleExpr, or MemberExpr (SRA field slot
        holding a blob pointer; same shapes `_emit_for_list` plus field loads).
        Linear scan of int64 elements; result 0/1 in X0. `not in` inverts.
        A dict RHS is a *pair* blob `[count][k0][v0]…`, so it is scanned over
        its KEYS at stride 16 — a stride-8 scan of a pair blob walks keys and
        values alternately and stops at the pair count, i.e. it can only ever
        see the first half of the dict. BinaryOp RHS (`or`/`and`/`+`/`|`) is
        allowed — evaluated under container ctx so `+`/`|` lower as list/set
        ops."""
        if (isinstance(right, F.StringLiteral)
                or M.string_membership_lowering(
                    self._expr_str_kind(left),
                    self._expr_str_kind(right)) is not None):
            self._emit_str_membership(left, right, invert=invert)
            return
        # A string haystack is answered above and a blob one is refused here.
        # A FRAME is neither, and the blob scan below would read its first
        # field as the count — see `model.frame_container_operand_refusal` for
        # the measurement, which is a wrong answer rather than a crash.
        self._refuse_frame_container_operand("a membership test", right)
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
        """`e`'s arguments in positional form, for a known callee.

        A THIN CALL into `M.bind_call_arguments`, which is the one
        implementation of the rule and the reason the two backends cannot
        disagree about it.  This function used to be a second copy of the rule
        with a hole: `if not e.kwargs: return list(e.args)` short-circuited
        before the arity check, so a call with no keywords was never examined
        at all — which is how `f(1, 2, r)` reached a `def f(x, *rest)` and
        bound all three as fixed parameters."""
        fdef = self._functions.get(name)
        if fdef is None:
            if e.kwargs:
                names = [k for k, _v in e.kwargs]
                raise CodegenError(
                    f"keyword arguments are not supported ({names})")
            return list(e.args or [])
        slots, err = M.bind_call_arguments(name, fdef, e.args, e.kwargs)
        if err is not None:
            raise CodegenError(err)
        return slots

    def _emit_type_constructor(self, e: F.CallExpr, name: str,
                               tkind: tuple) -> None:
        """`Int(x)` / `String(s)` / `String()` — a conversion, not a call.

        On the formal paths a value is a 64-bit word and a string is already a
        `char *`, so an integer construction is a width/sign normalization of
        the operand and a string construction is the identity. Both take
        exactly one operand, as in the language; anything else is a shape error
        rather than a guess.

        The ONE exception is a zero-operand STRING, and it is an exception
        because a string's zero value is representable exactly where nothing
        else's is: string literals on this path are interned and
        NUL-terminated, so the address of `""` IS the empty string, and
        `String("")` already builds and already has `len` 0.  So `String()` is
        the same word by a different spelling, and refusing it refused a
        representable program for a reason that was about the WORD COUNT rather
        than about the value — `std/format/repr.mojo`'s `var string = String()`
        is the site, and it is a `String` return value being built empty.

        A zero-operand conversion of any OTHER type is refused, because 0 is
        not the empty `Pointer` and not the empty `Int` and not the empty
        `StringLiteral` in any sense this value model can state."""
        kind, info = tkind
        if kind == "unsupported":
            operands = list(e.args) + [v for _n, v in (e.kwargs or [])]
            if M.empty_blob_constructor(name):
                # The EMPTY container, which is a different question from the
                # one this arm was written for and the one `List[Int]()` was
                # refused for.  A container's value is a pointer to a blob laid
                # out `[count:i64][element 0]…`, so the empty one is eight
                # bytes with a zero count in them — the same eight bytes and the
                # same layout `_emit_list` builds for `[]`, and the same one
                # `LEN_FROM_BLOB_FIELD` reads a length from.  So it is emitted
                # as the zero-element literal rather than refused: `len()` of it
                # is 0, which is what the source says.
                #
                # With ARGUMENTS it is a genuinely different problem and keeps
                # its own diagnostic: a blob's size is fixed when the function
                # is laid out, so one that has to hold n elements needs a frame
                # reservation sized by a value this compiler does not have.
                if operands:
                    raise CodegenError(
                        M.blob_constructor_with_operands_refusal(
                            name, len(operands)))
                self._emit_empty_blob()
                return
            raise CodegenError(
                f"constructing {name} has no representation on this path: this "
                f"image has no declaration of {name} to construct — it is not a "
                f"struct in this module or in anything it imports, so there is "
                f"no field list to bring up, and a formal value is one 64-bit "
                f"word. A name that IS declared as a struct here is decided by "
                f"`_emit_struct_constructor` instead, which asks the struct: a "
                f"one-field struct is a plain word and constructs. (Emitting a "
                f"call to a symbol named {name!r} that nothing defines is not "
                f"the alternative — that built and then failed to load.)")
        # A keyword argument names the same single value a positional one
        # does, so it is accepted as the operand rather than rejected:
        # `String(unsafe_from_utf8_ptr=p.value())` is how std/os/env.mojo
        # builds a string from a raw pointer, and refusing every keyword form
        # blocked 78 stdlib files on a shape the language allows. What is
        # still refused is a genuine mismatch of ARITY — a conversion has one
        # operand, and two of them (positioned or named) is not a conversion.
        operands = list(e.args) + [v for _n, v in e.kwargs]
        if not operands:
            if name in M.STRING_TYPE_CTORS:
                # `String()` is `String("")`, and the reason it can be is the
                # one property of this path's strings that no other type has:
                # a literal is NUL-terminated, so its own address is its
                # length.  `strlen` of it is 0 and `printf("%s")` of it prints
                # nothing, which is what an empty `String` must do.
                self._emit_expr(F.StringLiteral(value=""))
                return
            raise CodegenError(
                f"{name}() with no operand is refused on this path: a "
                f"conversion of a value takes the value to convert, and 0 is "
                f"not the empty {name} in any sense this one-word value model "
                f"can state — a zero pointer is a null dereference and a zero "
                f"integer is a value the source never wrote. "
                + (f"Pass the value to convert"
                   if name in M.IDENTITY_TYPE_CTORS else
                   f"Build the value first and pass it"))
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
        """`S()`, `S(a, b)` or `S(x)` — a construction, not a call.

        Mojo has no user-defined constructor: `S()` brings every field up at
        its default and the fields are then assigned. On this path a value is
        one 64-bit word, so that is exactly what a struct of zero or one field
        IS — the word itself, zero for a fresh one. Both shapes therefore need
        no call at all, and emitting one was the bug: it produced a BL against
        a symbol named after the type, so the library built and then could not
        be loaded ("Symbol not found: _Counter").

        WIDER structs are represented BY REFERENCE, and their constructor is
        still not a call: the receiver word is the ADDRESS of a frame of
        8-byte slots that the prologue already reserved
        (`model.struct_constructor_sites`), every field is brought up at its
        own default, and the address is the result. A pointer is one word, so
        nothing that was one word before becomes two, and the call sites need
        no change at all — they pass the address they already had.

        A struct that fits NEITHER representation is refused by name and width.
        It used to reach the extern path and produce that same unloadable
        image, so the honest limit has to be stated where the decision is made
        rather than discovered by dyld.

        The width is the DERIVED one (formal.model.struct_field_count), not
        `len(st.fields)`. A class that assigns its fields in `__init__` declares
        none, so the declared count called it a zero-field marker, handed back
        a zero word, and left the receiver with no representation for the
        fields a method then went on read — while the sibling refusal in
        formal/build.py, which reads the derived count, called the same class
        wide. One struct, two widths, two backends: the count has to come from
        the shared model or the two answers can disagree."""
        if M.struct_is_framed(st):
            self._emit_frame_constructor(e, name, st)
            return
        if M.struct_field_count(st) > 1:
            raise CodegenError(
                f"constructing {name} needs {M.struct_field_summary(st)}, and a "
                f"formal value is one 64-bit word — a multi-field struct has "
                f"no representation on this path (previously this emitted a "
                f"call to a symbol named {name!r} that nothing defines, so the "
                f"image built and then failed to load). The by-reference "
                f"receiver that gives one is switched off "
                f"({M.WIDE_RECEIVER_ENV}=0)")
        if e.kwargs:
            raise CodegenError(M.construction_keyword_refusal(
                name, [k for k, _v in e.kwargs]))
        if e.args:
            # A ONE-FIELD struct with an argument is a positional construction
            # whose store is free: the receiver IS the field, so the argument
            # is not stored anywhere, it is the result.  The old text here —
            # "a struct is default-initialized and its fields assigned" — was
            # stale for the wrong reason: it was true before the by-
            # reference receiver gave a multi-field struct a block to fill and
            # it stopped being the reason at the same moment.  What is still
            # refused is what the DECISION refuses, by name: see
            # `model.struct_construction_plan`.
            #
            # A struct that DECLARES an `__init__` is the one case where the
            # result is not simply the argument: the constructor's body decides
            # what lands in the field, and a body this path inlines gives a
            # list of stores whose LAST one is the field's final value.  The
            # same word for the same reason — the receiver IS the field, so
            # there is nothing to store it into.
            plan, refusal = M.struct_construction_plan(
                st, e, self._structs, self._frame_candidates,
                self._return_types)
            if refusal is not None:
                raise CodegenError(refusal)
            if plan[0] == M.CONSTRUCTION_INIT:
                if plan[1]:
                    self._emit_expr(plan[1][-1][2])
                    return
                self._emit_fresh_one_word(name, st)
                return
            self._emit_expr(e.args[0])
            return
        self._emit_fresh_one_word(name, st)

    def _emit_frame_constructor(self, e: F.CallExpr, name: str,
                                st: F.StructDef) -> None:
        """`S()`, `S(a, b, …)`, `S(a, b, c)` with an `__init__`, or `S(x)`.

        Four shapes, one decision (`model.struct_construction_plan`) and one
        exit convention: the ADDRESS of the fresh block is in X0.

        * `S()` — every field brought up at its own default in its own slot, and
          every placed nested frame brought up in the block above.  A default
          that cannot be materialized refuses the construction, naming the
          field: a fresh struct whose field reads 0 where the source says
          something else is the wrong answer this whole path exists to avoid,
          and it would be invisible — the program builds, runs, and returns a
          number nobody wrote.
        * `S(a, b, …)` — one store per argument, at `base + 8k` in DECLARATION
          ORDER, which is the whole of it.  The nested frames are still brought
          up first, because a positional argument may not land on a slot one
          of them occupies (`model.struct_construction_plan` refuses that) and
          so every placed nested frame is still the block's own.
        * `S(a, b, c)` on a struct that DECLARES `__init__` — the same block,
          brought up at the class-level defaults first and then given the
          constructor's own stores, in the constructor's own order, because the
          language default-initializes the object before the constructor runs
          and this path inlines the body rather than calling it.  So a field the
          constructor assigns wins and a field it does not keeps its default —
          which is the language's rule, arrived at by a different route.
        * `S(x)` — a COPY: no defaults at all, and an `n`-slot copy of the
          source's slots into the fresh block.  Shallow, and that is the
          language's semantics and not a shortcut: a slot holds one word, and
          a word that is a frame address or a blob address copies as the
          address it is, which is what a value-typed struct's field does in
          every language this path is standing in for.  What makes it SAFE is
          not the shallowness but the confinement — a block belongs to the
          function that built it and `_check_frame_escapes` refuses every way
          out of that activation — together with the fact that no slot can
          hold a blob from a function that has returned (`model.
          construction_dead_blob_refusal` refuses the one construction argument
          that could put one there, and premise (B1) refuses the method half).

        The frame was reserved in the prologue (see `_emit_function`), so this
        is a fixed X29-relative address and the result does not depend on how
        many times the constructor runs: a constructor inside a loop reuses
        its site's block, exactly as a C local is reused."""
        plan, refusal = M.struct_construction_plan(
            st, e, self._structs, self._frame_candidates, self._return_types)
        if refusal is not None:
            raise CodegenError(refusal)
        shape = plan[0]
        site = self._frame_sites.get(id(e))
        if site is None:
            raise CodegenError(
                f"constructing {name} at a site this function did not reserve "
                f"a receiver frame for — the frame layout and the body "
                f"disagree, which is a compiler bug, not a program error")
        if shape == M.CONSTRUCTION_COPY:
            self._emit_frame_copy(e, name, st, site, plan[1])
            return
        if shape == M.CONSTRUCTION_POSITIONAL:
            self._emit_frame_positional(e, name, st, site, plan[1])
            return
        ok, bad = M.struct_frame_representable(st)
        if not ok:
            raise CodegenError(
                f"constructing {name} cannot bring its field {bad!r} up at "
                f"its default on this path: the default is not a literal, and "
                f"this constructor has no scope to evaluate it in (assign the "
                f"field explicitly after `S()` instead, which is the same "
                f"program with a representation)")
        # A NESTED frame first, and first because the block is laid out with
        # the object's own slots at the bottom: bringing a nested frame up needs
        # its own base, and the outer base is recomputed per store anyway.
        # `site[2]` is the PLACEMENT (`model.struct_constructor_sites`), so a
        # declared type that was not placed cannot reach this loop.
        self._emit_frame_nested(site)
        for slot, (kind, payload) in enumerate(M.struct_frame_defaults(st)):
            if kind == M.DEFAULT_STRING:
                value = F.StringLiteral(value=payload)
            else:
                value = int(payload or 0)
            self._emit_block_store(site, slot, value)
        # …and then the constructor's own stores, for the one shape that has
        # them.  Empty for `S()`, which is why this is the same code as the
        # default constructor's rather than a fourth copy of it.
        for _field, slot, value in (plan[1] if shape == M.CONSTRUCTION_INIT
                                    else ()):
            self._emit_block_store(site, slot, value)
        self._emit_frame_nested_addresses(site)
        # …and once more at the end, because the address is the RESULT and
        # every store above left something else in X0. An address materialized
        # once and then overwritten is a null pointer, and the program
        # segfaults on the first field read rather than computing anything.
        self._emit_frame_base(site[1])
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_frame_nested(self, site) -> None:
        """Bring every PLACED nested frame of this site's struct up.

        Nested frames first, and first because the block is laid out with the
        object's own slots at the bottom: bringing a nested frame up needs its
        own base, and the outer base is recomputed per store anyway.
        `site[2]` is the PLACEMENT (`model.struct_constructor_sites`), so a
        declared type that was not placed cannot reach this loop.
        """
        for _fname, _slot, _child, child_off in site[2]:
            self._emit_nested_frame_init(_child, child_off)

    def _emit_frame_nested_addresses(self, site) -> None:
        """Store the ADDRESS of each frame `_emit_frame_nested` just brought up.

        Which is the whole of "the slot holds a nested frame": one store per
        typed-nested field, in the same order as `_emit_frame_nested`, so the
        address stored and the frame initialized are the same one by
        construction rather than by two walks agreeing.
        """
        for _fname, slot, _child, child_off in site[2]:
            self._emit_frame_base(child_off)
            self.asm.emit(encode_mov_zr_xn(0, 9))
            self._emit_frame_base(site[1])
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * slot))

    def _emit_block_store(self, site, slot: int, value) -> None:
        """One store into a CONSTRUCTION's fresh block: `value` to `8·slot`.

        The register discipline every construction shape shares, and unchanged
        by any of them: the value is evaluated into X0 and the base is
        recomputed into X9 immediately before the store, because evaluating a
        value can be anything (a call, a string LEA) and both of those clobber
        X9.  So the base is recomputed per store rather than hoisted.

        `value` is either an AST node to evaluate or an `int` to materialize,
        which is what lets the class-level defaults and an inlined
        constructor's stores share one loop: a literal default has nothing to
        evaluate, and a literal inside a constructor body is the same node.
        """
        if isinstance(value, int):
            self.asm.emit(encode_movz_xn_imm(0, value))
        else:
            self._emit_expr(value)
        self._emit_frame_base(site[1])
        self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * slot))

    def _emit_frame_positional(self, e: F.CallExpr, name: str, st, site,
                               fields) -> None:
        """`S(a, b, …)` — one store per argument, at `base + 8k` in declaration order.

        `_emit_frame_store` is the register discipline and `_emit_frame_nested`
        / `_emit_frame_nested_addresses` are the two placement loops, all three
        shared with the default and `__init__` shapes; what is specific here is
        only that a positional argument covers EVERY field, so no slot is
        brought up at its class-level default first — there would be nothing
        left of the default to keep.

        The nested frames are brought up first and their addresses stored
        afterwards, in the same order `model.struct_constructor_sites` laid them
        out.  A positional argument can never land on one of those slots — the
        plan refuses that by name — so the two halves cannot fight over a slot.
        """
        self._emit_frame_nested(site)
        for arg, (_field, slot) in zip(e.args, fields):
            self._emit_block_store(site, slot, arg)
        self._emit_frame_nested_addresses(site)
        # The address is the RESULT, and every store above left something else
        # in X0.  Same last line as the default constructor's, and for the same
        # reason: an address materialized once and then overwritten is a null
        # pointer and the program segfaults on the first field read.
        self._emit_frame_base(site[1])
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_frame_copy(self, e: F.CallExpr, name: str, st, site,
                         nslots: int) -> None:
        """`S(x)` — a fresh block and an `n`-slot copy of the source's slots.

        SHALLOW, and deliberately so.  A slot holds one word; a word that is a
        frame address or a blob address copies as the address it is, which is
        what a copy of a value-typed struct does in every language this path
        stands in for — `Repeat(a)` in the corpus shares `a`'s `node` exactly
        as Python does.  Deep-copying instead would be a DIFFERENT program, and
        a silently different one.

        The safety argument is not the shallowness, it is the confinement: a
        block belongs to the function that built it, `_check_frame_escapes`
        refuses every way out of that activation, and the source frame is
        reachable from a live local of this function — so the source's bytes are
        alive for every read the destination will ever get.  The one way a slot
        could hold an address of DEAD bytes is a blob built by a function that
        has returned, and the three doors into that are all closed elsewhere:
        premise (B1) refuses a method writing a container into a field,
        premise (B2) means `__init__` never runs, and
        `model.construction_dead_blob_refusal` refuses a construction argument
        that is a container returned by a callee.  A copy is the most likely
        place to reintroduce the hazard, which is why it is checked here rather
        than assumed covered.

        X10 holds the source base across the loop and X9 the destination, so
        neither is recomputed per slot: `LDR`/`STR` clobber no register here,
        and the two bases are the only live state the loop has.  X10 is a
        caller-saved temporary on AAPCS64 and is set after the source
        expression has been evaluated, so nothing the argument needed can be
        living in it.
        """
        self._emit_expr(e.args[0])
        self.asm.emit(encode_mov_zr_xn(10, 0))
        self._emit_frame_base(site[1])
        for slot in range(nslots):
            self.asm.emit(encode_ldr_xt_xn_imm(0, 10, 8 * slot))
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * slot))
        self._emit_frame_base(site[1])
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_nested_frame_init(self, st, offset: int, depth: int = 0) -> None:
        """Bring a NESTED receiver frame up at its own slot defaults.

        The recursion is the same shape as `model.struct_frame_block_bytes`,
        which is what keeps the BYTES reserved and the defaults STORED in
        agreement: the model's recursion decides the size, this one fills it, and
        both walk `struct_nested_frame_fields` in the same order from the same
        function.  A cycle is bounded by the model's `MAX_NESTED_FRAME_DEPTH` and
        the same bound is applied here, so a cyclic declaration graph produces a
        truncated init in both rather than a hang in one.

        Every default goes through X0 and the base through X9, exactly as the
        outer constructor does, so there is no register discipline to get wrong
        between the two levels.
        """
        if depth >= M.MAX_NESTED_FRAME_DEPTH:
            return
        for _fname, _slot, child, child_off in \
                M.struct_nested_frame_fields(st, self._structs):
            self._emit_nested_frame_init(child, child_off, depth + 1)
        self._emit_frame_base(offset)
        for slot, (kind, payload) in enumerate(M.struct_frame_defaults(st)):
            if kind == M.DEFAULT_STRING:
                self._emit_expr(F.StringLiteral(value=payload))
            else:
                self.asm.emit(encode_movz_xn_imm(0, int(payload or 0)))
            self._emit_frame_base(offset)
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * slot))

    def _emit_frame_return(self, value) -> None:
        """`return <frame>` in a function the convention applies to.

        The whole of the callee's half, and it is three steps because the
        destination is a block the CALLER reserved and named:

          * the source address is whatever the expression yields in X0 — a
            bare holder name IS its block's address, and a call to another
            frame-returning function leaves the address of the block reserved
            for ITS result in this function. Both are the same word, which is
            why there is no separate path for the two;
          * the BLOCK is copied, not just the fields: the object's own slots
            and, for each placed nested frame, that frame's bytes — and then
            each nested slot is RE-POINTED at the copy. That last step is what
            makes the copy more than a memcpy: without it the destination slot
            would hold the address of a frame in the frame being reclaimed,
            and the caller would read a nested field out of dead memory. The
            re-point is the same loop the constructor runs to bring the nested
            frames up (`_emit_frame_constructor`), over the same shared layout;
          * the destination address is the RESULT, in X0 — the same word the
            caller passed in, so the call site's value is the block the caller
            reserved and every use of it downstream is an ordinary frame
            access.

        The copy is SHALLOW for every field that is not a placed nested frame,
        and that is the language's semantics rather than a shortcut: a slot
        holds one word.  What makes it safe is the confinement — every other
        channel out of a block is refused by `formal/build.py` — and premise
        (B1), that a frame slot never holds a container whose blob belongs to
        another activation.
        """
        self._emit_expr(value)
        self._load_var(_SRET_LOCAL, 17)
        nested, block = M.struct_frame_block_layout(self._returns_frame,
                                                    self._structs)
        # The source is X0 and the destination is X17 for the whole loop: a
        # store never writes its base register, so the source address survives
        # every iteration, and X16 is the only other register this needs.
        for off in range(0, block, 8):
            self.asm.emit(encode_ldr_xt_xn_imm(16, 0, off))
            self.asm.emit(encode_str_xt_xn_imm(16, 17, off))
        for _fname, slot, _child, child_off in nested:
            _emit_add_imm(self.asm, 16, 17, child_off)
            self.asm.emit(encode_str_xt_xn_imm(16, 17, 8 * slot))
        self.asm.emit(encode_mov_zr_xn(0, 17))

    def _emit_frame_base(self, offset: int) -> None:
        """X9 = the address of the receiver frame `offset` bytes into the area.

        Literally `_emit_list_base`: the frames are at the bottom of the same
        reserved scratch the blobs are, at the same `SP + offset` addresses, and
        the only difference is that the blob cursor is told to start above
        them. Sharing the one routine rather than writing a second one is what
        makes "a frame is a blob that the cursor skips" true by construction
        instead of by two address computations agreeing."""
        self._emit_list_base(offset)

    def _emit_fresh_one_word(self, name: str, st) -> None:
        """`S()` for a struct of zero or one field — a value, not a call.

        The one word a fresh struct holds is its sole field brought up at that
        field's default (formal.model.struct_default_word), which is zero only
        when there is no default to honour. Emitting a hard 0 regardless was
        the same class of bug as emitting a call: a program that read the field
        without writing it first got a value the source never said, and it built
        and ran and was wrong.

        A default that is not a literal is refused, naming the field. Substituting
        0 for it is the bug; evaluating it at the call site would mean resolving
        names in a scope the constructor does not have, and guessing there is
        the same failure wearing a hat."""
        kind, payload = M.struct_default_word(st)
        if kind == M.DEFAULT_OPAQUE:
            raise CodegenError(
                f"constructing {name} cannot bring its field {payload!r} up at "
                f"its default on this path: the default is not a literal, and "
                f"this constructor has no scope to evaluate it in (assign the "
                f"field explicitly after `S()` instead, which is the same "
                f"program with a representation)")
        if kind == M.DEFAULT_STRING:
            self._emit_expr(F.StringLiteral(value=payload))
            return
        self.asm.emit(encode_movz_xn_imm(0, int(payload or 0)))

    def _specialization_args(self, e: F.CallExpr, ct_params: list) -> list:
        """The argument expressions binding `ct_params` at this call site."""
        try:
            return comptime_eval.specialization_args(e, ct_params)
        except ValueError as exc:
            raise CodegenError(str(exc))

    def _emit_call(self, e: F.CallExpr) -> None:
        # `external_call["sym", RetType](args…)` — a direct call to the C symbol
        # the bracket names, with `RetType` marshalling the result.
        #
        # Intercepted at the TOP, before `_callee_symbol`, and that is the whole
        # point: `_callee_symbol` reads the bracket as a generic's comptime
        # specialization and answers `external_call`, so without this the call
        # became `BL external_call` — a symbol no library defines, on an image
        # that would have died in dyld.
        #
        # The `is_extern_call` flag is the other half, and it is what makes
        # `std/os/env.mojo` lowerable at all: the bracket names a C SYMBOL, and
        # that module defines Mojo functions called `getenv`, `setenv` and
        # `unsetenv` over the same three C symbols.  A name is looked up in
        # `self._functions` before the extern path is taken, so a bare name
        # would have branched to the module's OWN `getenv` — which takes an
        # `Int` and returns an `Int`, so the call "succeeded" and the program
        # then read an Int where it had asked for a `char *` and segfaulted
        # dereferencing it.  A C function and a Mojo function occupy different
        # namespaces in the language (the real compiler mangles the Mojo one to
        # `__mlir_fn.env.getenv`), so on this path the C symbol must go to the
        # extern machinery even when this image declares that name — and the
        # BUILTIN interception below must be skipped for the same reason, since
        # `external_call["printf", Int32](fmt, n)` is a call to `printf` with
        # the format the source wrote, not `print`.
        ext_return = None
        is_extern_call = M.is_external_call_template(e.func)
        if is_extern_call:
            symbol, ext_return, why = M.external_call_spec(e.func)
            if why is not None:
                raise CodegenError(M.external_call_refusal(
                    M.external_call_spelling(e.func), why))
            name = symbol
        else:
            name = _callee_symbol(e.func)
        if name is None:
            raise CodegenError(
                f"unsupported call target on the formal arm64 path "
                f"(got {type(e.func).__name__})")
        if not is_extern_call and name == "range":
            self._emit_range_list(list(e.args))
            return
        if not is_extern_call and name == "len":
            self._emit_len(e)
            return
        if not is_extern_call and name == "print":
            self._emit_print(e)
            return
        if not is_extern_call and M.builtin_function(name) == "file_open":
            self._emit_open(e)
            return
        # A DEREFERENCE.  Intercepted HERE rather than left to the value-method
        # table below for two reasons, and both are about the RESULT rather than
        # about the receiver.  A dereference is an EXPRESSION: `return
        # pointer.unsafe_value()`, `s._ptr = p.value()`, `String(unsafe_from_
        # utf8_ptr=ptr.value())` — the corpus puts it in argument, store and
        # return positions, and `_emit_value_method` is a statement emitter with
        # no result register, so the only place its answer can land is X0.  And
        # the decision has to be `model.dereference_lowering` and not
        # `model.value_method_refusal`, because the refusal cannot see the
        # function and so cannot see a declared pointee — which is the whole of
        # the pointer value model.
        if isinstance(e.func, F.MemberExpr) \
                and e.func.member in M.DEREFERENCE_TRY_NAMES \
                and self._expr_str_kind(e.func.obj) != M.STR_KIND:
            self._emit_dereference(e, e.func.member)
            return
        # A method on a plain VALUE is not a call to a symbol spelled
        # `recv.method`. `_callee_symbol` flattens both spellings to a dotted
        # name, so the two are told apart by the receiver: a local is a value
        # and the method is one of model.BUILTIN_VALUE_METHODS, anything else
        # is a module path and the dotted name really is an extern. Before
        # this, `items.append(4)` became `BL _items.append` — an image that
        # built and then died in dyld.
        if isinstance(e.func, F.MemberExpr) and \
                self._is_value_receiver(e.func.obj):
            self._emit_value_method(e, e.func.member)
            return
        # A type constructor is a conversion, not a call. Intercepted before the
        # extern path, because the extern path would emit a BL against a
        # symbol named e.g. `Int` that nothing defines (the decision is
        # formal/model.type_constructor_kind; the width normalization below is
        # the arm64 half).
        #
        # ONE exception, and it is decided by ARITY rather than by a name: a
        # name in `UNREPRESENTABLE_TYPE_CTORS` that THIS MODULE also declares
        # as a struct, called with that struct's field count.  The hand-kept
        # list is a statement about types this path cannot represent
        # abstractly; a struct of one field is a plain word, which is the most
        # representable thing there is, and the file's own declaration is the
        # only thing in hand that says what the name means.  See
        # `model.type_constructor_prefers_local_struct` for why the identity
        # and integer tables are NOT overridden — `Pointer` is a struct some
        # files here declare and an identity conversion, and preferring the
        # declaration would change a program's MEANING rather than its
        # verdict.
        if not is_extern_call and name not in self._functions:
            nargs = len(e.args) + len(e.kwargs or [])
            if not M.type_constructor_prefers_local_struct(
                    name, self._structs, nargs):
                tkind = M.type_constructor_kind(name)
                if tkind is not None:
                    self._emit_type_constructor(e, name, tkind)
                    return
        if not is_extern_call and name in self._structs:
            self._emit_struct_constructor(e, name, self._structs[name])
            return
        is_extern = is_extern_call or name not in self._functions
        # The gimple backend's C runtime is not an external dependency of THIS
        # target but a library of a different one, and it is spelled in the
        # source as bare `mojo_*` names (`mojo_sqlite3_open`, `mojo_list_len`,
        # `mojo_print`). Everything a call to one of those could bind to has
        # been ruled out above: not a function of this module, not a struct, not
        # a type constructor, and a dylib the program linked would have
        # supplied its own spelling below.
        #
        # What is left is decided by the runtime's ABI rather than by the name
        # (`model.gimple_runtime_callable`): a call is answerable when every
        # type crossing the boundary is one 64-bit word — which is what a value
        # IS here — AND the symbol is on the link line, which `_dylib_syms` is.
        # Note the two are independent and both are needed. A `MojoList *`
        # argument is a box no link line can answer, so it is refused EVEN IF a
        # dylib provides the symbol; and `mojo_print`, whose every type is a
        # word, is refused only because nothing here provides it. Refusing by
        # prefix got the first case right by accident and could not tell the
        # second from it.
        if is_extern and not M.gimple_runtime_callable(
                name, name in self._dylib_syms):
            raise CodegenError(M.gimple_runtime_refusal(name))
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
        elif isinstance(e.func, F.SubscriptExpr):
            # A BRACKETED callee this unit does not compile. The branch above
            # is the only place a specialization's brackets are turned into
            # arguments, so without this the brackets are silently DROPPED and
            # `plain[3](5)` is emitted as `plain(5)` — measured, an image that
            # built, ran and printed a number the source never wrote. The
            # shared text is `model.specialization_call_refusal`, which x86-64
            # asks too.
            raise CodegenError(M.specialization_call_refusal(name))
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
        sret_site = self._ret_frame_sites.get(id(e))
        nargs = len(args) + (1 if sret_site is not None else 0)
        # AAPCS passes the first eight arguments in X0..X7. A ninth has no
        # register, and this path has no stack-argument convention to fall
        # back on, so the call is REFUSED here rather than truncated: the
        # alternative — evaluate the extra arguments for their side effects,
        # drop them, and branch — built an image that ran and read the ninth
        # parameter as ZERO, which is a perfectly good answer to a great many
        # questions (measured: `nine(1,...,9)` returned 1 where the source
        # says 90001). A wrong value is strictly worse than a refusal here,
        # because nothing downstream can tell a dropped argument from a
        # caller who passed zero. Same shape, same words, as the x86-64
        # check in `_emit_call` there — the two differ in their limit (8 vs
        # 6) because the ABIs do, not in what they do about it.
        #
        # `nargs` and not `len(args)`, because the returned-frame hidden word
        # below IS an argument — the callee reads it out of the register
        # after the last source one — so eight source arguments to a
        # frame-returning function is a NINE-argument call. The frame
        # overflow check that used to sit after the pushes is hoisted to
        # here, so ONE refusal covers both overflows and the
        # evaluate-then-drop it guarded against is gone with it: with the
        # drop removed, that later check had nothing left to catch, and
        # keeping it would be a second answer to a question asked once.
        # The frame case still gets the construct's OWN sentence, which
        # names the hidden word and the budget it ran into rather than
        # reporting a count the reader cannot account for.
        if nargs > _ABI_ARG_REGS:
            if sret_site is not None:
                raise CodegenError(
                    M.returned_frame_convention_refusal(name, len(args))
                    or f"calling {name}() needs one hidden word for the "
                       f"caller's block and there is no argument register "
                       f"left for it")
            raise CodegenError(
                f"call {name}(): {nargs} arguments exceeds the "
                f"{_ABI_ARG_REGS} the formal arm64 ABI passes in registers")

        # AAPCS: pass up to 8 integer args in X0..X7. Evaluate left-to-right,
        # spilling each result so nested evaluations (which clobber X0/X1/X2)
        # don't destroy earlier arguments. Pop in reverse so arg0 lands in X0.
        # Second slot of each push/pop is XZR so loads never clobber a live arg.
        for arg in args:
            self._emit_expr(arg)
            self.asm.emit(encode_stp_sp_pre(0, 31))
        if sret_site is not None:
            # The block's own address, in the same scratch the constructor
            # frames use and at the offset the shared layout gave it.
            self._emit_frame_base(self._ret_frame_base + sret_site[1])
            self.asm.emit(encode_mov_zr_xn(0, 9))
            self.asm.emit(encode_stp_sp_pre(0, 31))
        for i in range(nargs - 1, -1, -1):
            self.asm.emit(encode_ldp_sp_post(0, 31))
            if i != 0:
                self.asm.emit(encode_mov_zr_xn(i, 0))
        if is_extern:
            # A linked library's export spelling wins over the bare name, so
            # the BL, the GOT slot and the bind stream all name the symbol the
            # library actually defines.
            symbol = self._extern_symbol(name)
            area = self._emit_variadic_area(symbol, len(args))
            self.asm.emit_extern_bl(symbol)
            if area:
                self.asm.emit(encode_add_xd_xn_imm(31, 31, area))
        else:
            self.asm.emit(encode_bl(0))
            self.asm.emit_label_rel(name, here_offset=-4)
        if ext_return is not None:
            self._emit_extern_return(ext_return)

    def _emit_extern_return(self, kind) -> None:
        """Put the return register into the shape the DECLARED return type says.

        The ABI puts the low `bits` of a narrow integer return in X0 and leaves
        the rest unspecified, and a W-register write zero-extends on AArch64, so
        the value that actually arrives is zero-extended.  `Int32` and `c_int`
        are signed and the source means the sign-extended value:
        `zero_extend(0xFFFFFFFF)` is 4294967295, not -1.  So this is the
        conversion, not tidying, and `model.py`'s section on the construct is
        where the reasoning and the measurement live.

        A pointer (`getenv` declares `_CPointer[UInt8, …]`), a 64-bit integer
        and a string are already the whole register, so they need no
        instruction, and `NoneType` returns nothing at all.  The width
        normalization itself is `_emit_extend` — the same one an `Int32(x)`
        conversion uses, so there is one implementation of "make this word
        this width" per architecture rather than two."""
        if kind == M.EXTERN_RETURN_VOID or kind == M.EXTERN_RETURN_WORD:
            return
        width, signed = kind
        self._emit_extend(0, 0, IntType(width, signed))


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
                self._emit_expr(expr.element)  # KEY -> X0
                # Save the KEY ALONE. Saving X0 and X1 together and popping
                # both looked right and was not: the value is evaluated into
                # X0, so the pop that restored the key also overwrote the
                # value, and X1 was left holding whatever the loop had last
                # put there. Every dict comprehension therefore stored a
                # stale value — `{i: 100 + i for i in range(3)}` had the right
                # keys and len, and a wrong value behind each one.
                self.asm.emit(encode_stp_sp_pre(0, 31))
                self._emit_expr(expr.key)      # VALUE -> X0
                self.asm.emit(encode_mov_zr_xn(1, 0))   # X1 = value
                self.asm.emit(encode_ldp_sp_post(0, 31))  # X0 = key
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
                if not self._emit_branch_unless(cond, step_label):
                    self._emit_truthy_word(cond)
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
        # Two pushes, and the offsets below depend on the order: the SECOND
        # stp lands lower, so [sp+0] is the value pushed second and [sp+8] is
        # the key. They were read the other way round, so every dict
        # comprehension stored its key in the value slot and vice versa —
        # which is why the right keys and the right len sat next to values
        # that were somebody else's.
        self.asm.emit(encode_stp_sp_pre(0, 1))  # push key, value
        self.asm.emit(encode_stp_sp_pre(1, 31))  # push value again (lower)
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
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))   # [sp+8] = key
        self.asm.emit(encode_str_xt_xn_imm(0, 4, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))   # [sp+0] = value
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
        use LSLV/LSRV/ASRV (immediate form when the RHS is a small literal),
        and an amount at or past the word's width SATURATES rather than being
        masked to a shift by zero — `model.shift_saturated_is_zero` is the rule
        and this is only its instruction selection. `**` unrolls a small
        literal exponent.

        The two decisions a shift makes are NOT the same decision, and only
        one of them promotes both operands: a shift's signedness comes from
        the thing being SHIFTED (`model.shift_signedness`), because the right
        operand is a count and a count's signedness says nothing about what to
        shift in. Division and remainder keep the promotion, where the two
        operands really do combine."""
        result_t = common_type(self._ttype(e.left), self._ttype(e.right))
        signed = cmp_signed(result_t)
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
            # The signedness that picks ASRV over LSRV is the LEFT operand's
            # own, not the promotion's. `result_t` above is still the answer to
            # "what width is the result", which is a different question and
            # does involve both operands; only the FILL depends on this one.
            # Without the split, `UInt64 >> Int` chose signedness from the
            # unannotated (hence signed) shift AMOUNT and computed
            # 0xFFFFFFFFFFFFFFFF >> 4 as 0xFFFFFFFFFFFFFFFF.
            signed = cmp_signed(M.shift_signedness(self._ttype(e.left)))
            imm_r = e.right
            if isinstance(imm_r, F.IntLiteral) and 0 <= imm_r.value <= 63:
                self._emit_expr(e.left)
                if op == "<<":
                    self.asm.emit(encode_lsl_xd_xn_imm(0, 0, imm_r.value))
                elif signed:
                    self.asm.emit(encode_asr_xd_xn_imm(0, 0, imm_r.value))
                else:
                    self.asm.emit(encode_lsr_xd_xn_imm(0, 0, imm_r.value))
                self._emit_trunc(result_t)
                return
            # A literal amount at or past the word's width is decided HERE,
            # with no branch: the value cannot be shifted that far, and the
            # immediate form's range check above is what sends it to the
            # register form, where the hardware would mask the amount back to
            # a shift by zero. `3 >> 64` was `3` and `3 << 64` was `3`. The
            # saturation rule (and why the arithmetic `>>` case is not simply
            # 0) is `model.shift_saturated_is_zero`; only the SIGN is a runtime
            # fact here, so the operand is still evaluated and `ASR #63`
            # replicates it.
            lit = self._static_int(imm_r)
            if lit is not None and M.shift_saturates(lit):
                self._emit_saturated(op, signed)
                self._emit_trunc(result_t)
                return
            # The register form: `_emit_shift_reg` is the ONE emitter for it
            # and carries the saturation rule, so this only has to put the
            # value in X0 and the amount in X1 and step aside. That is the
            # whole consolidation — a second copy of the rule here is what
            # let the `<<=` spelling keep the hardware's masking while the
            # `<<` spelling did not.
            self._emit_expr(e.left)
            self.asm.emit(encode_stp_sp_pre(0, 2))
            self._emit_expr_to(e.right, "X1")
            self.asm.emit(encode_ldp_sp_post(0, 2))
            self._emit_shift_reg(op, signed)
            self._emit_trunc(result_t)
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
        self._refuse_frame_container_operand("a slice", obj)
        """`obj[start:stop:step]` → new list blob in X0.

        Defaults: start=0, stop=count, step=1 (None nodes). Negative bounds
        wrap against count then clamp to [0, count]. step==0 exits(1).
        Negative step iterates i from stop-1 down while i >= start and
        i >= 0 (Python's stop-default of -1 for reversed slices is mapped
        to start=0 / stop=count via the None defaults when both are
        omitted; explicit negative-step bounds follow the clamped rule).
        Result capacity is a static upper bound (literal length or 64).

        A STRING base is refused before any of that, and the reason is the
        count: the loop below reads it from offset 0 of the object, which for a
        `char *` is the first eight CHARACTERS, so the walk starts inside the
        string with a length taken from its own first two letters. Measured on
        both backends, `s = "abcde"; printf("[%s]", s[1:])` died with SIGSEGV
        (exit 139). `model.string_slice_refusal` holds the message and the
        argument for lowering the suffix case later."""
        sreason = M.string_slice_refusal(
            self._expr_str_kind(obj), M.spelled(obj))
        if sreason is not None:
            raise CodegenError(sreason)
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
        """Variable shift X0 = X0 <op> X1 (LSLV/LSRV/ASRV), SATURATING.

        X0 holds the value and X1 the amount on entry; both are live and
        X0 is the result on exit.

        THE ONE register-form shift emitter on this backend. It was not,
        and being the second one is how the same defect reached the source
        twice: `_emit_div_shift_pow` had its own copy, and a program that
        spelled the shift `x <<= n` went through THIS one and got the
        hardware's modulo-64 masking, so `y <<= 64` left `y` unchanged
        while `y = y << 64` zeroed it. Both spellings are the same operator
        and the rule is one rule (`model.shift_saturated_is_zero`), so the
        rule lives here and both callers come to it.

        The amount is compared against 64 and a saturating branch taken
        BEFORE the shift instruction runs, so the masking is never the
        answer. The sign for the arithmetic case is X0's own, read before
        X0 is overwritten.

        The compare is SIGNED, which is what keeps this fix to the case it
        fixes: an amount of 64 or more (signed, so 64..2^63-1) saturates,
        and a NEGATIVE amount is below 64 and keeps the masking it has
        always had. That is not an endorsement — CPython raises ValueError
        for a negative amount, and this path answers with the masked shift
        — it is a separate question left alone rather than changed under
        cover of a fix about the saturation boundary. See
        bugs/FORMAL_negative_shift_amount_masks_instead_of_raising.md, which
        is also why the compare must not be made unsigned: unsigned, a
        negative amount would take the saturating branch and answer 0, a
        THIRD wrong answer rather than this one.
        """
        self._if_counter += 1
        sid = self._if_counter
        fn = self.func_name
        sat_label = f"{fn}_sh{sid}_sat"
        end_label = f"{fn}_sh{sid}_end"
        self.asm.emit(encode_cmp_xn_imm(1, 64))
        self.asm.emit(encode_b_cond("ge", 8))
        self.asm.emit_label_rel(sat_label, here_offset=-4)
        if op == "<<":
            self.asm.emit(encode_lslv_xd_xn_xm(0, 0, 1))
        elif signed:
            self.asm.emit(encode_asrv_xd_xn_xm(0, 0, 1))
        else:
            self.asm.emit(encode_lsrv_xd_xn_xm(0, 0, 1))
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(end_label, here_offset=-4)
        self.asm.label(sat_label)
        self._emit_saturated(op, signed)
        self.asm.label(end_label)

    def _emit_saturated(self, op: str, signed: bool) -> None:
        """Materialise the answer a SATURATING shift gives, in X0.

        The decision is `model.shift_saturated_is_zero` and this is only its
        instruction selection, so that a second backend cannot answer the
        same question differently. Two cases, and the second is the one a
        `return 0` saturation gets wrong: `ASR X0, X0, #63` is exactly "the
        sign-extended word", which is 0 for a non-negative operand and -1 for
        a negative one — which is what Python's arithmetic `>>` gives at any
        amount at or past 64. `X0` holds the value being shifted on entry, so
        the sign is read from it rather than recomputed."""
        if M.shift_saturated_is_zero(op, signed):
            self.asm.emit(encode_movz_xd_imm(0, 0))
        else:
            self.asm.emit(encode_asr_xd_xn_imm(0, 0, 63))

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
            raise CodegenError(M.comptime_fold_refusal(name))
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

    def _is_flag_preserving_load(self, e) -> bool:
        """True when `e` lowers to one load or move, neither of which writes
        the flags.

        That is what makes the no-stack CSEL path sound. The general form has
        to spill, because evaluating an arm clobbers the flags the condition's
        compare just set — but `LDR`/`LDUR`/`MOV`/`MOVZ` leave the flags
        alone, so when every arm is a plain local or literal the two values can
        be materialised after the compare with nothing saved at all.

        Deliberately narrow: any arithmetic, call, or container re-evaluates
        something and is excluded, which is the same reason the purity test is
        narrow. A wrong answer here would be a CSEL reading a stale flag, and
        that is silent."""
        return isinstance(e, (F.IdentExpr, F.IntLiteral, F.StringLiteral,
                              F.BoolLiteral))

    def _emit_csel_ternary(self, expr) -> None:
        """`a if c else b` branchlessly: evaluate both arms, CSEL between them.

        Ordering is forced by the fact that CSEL reads two registers at once:
        the condition has to be computed before either arm, because an arm's
        evaluation clobbers X0, and the arms have to be on the stack before
        the condition is dropped back in, or the second arm's evaluation would
        destroy the first.

            X0 = c ;  push
            X0 = a ;  push
            X0 = b ;  X1 = b
            X0 = a (pop)
            X2 = c (pop)
            cmp X2, #0 ; csel X0, X0, X1, ne

        `ne` rather than `eq` because Python's ternary tests the condition for
        TRUTHINESS, not equality with zero-by-identity: any non-zero value
        takes the `then` arm.
        """
        self._emit_truthy_word(expr.condition)
        if (self._is_flag_preserving_load(expr.then_val)
                and self._is_flag_preserving_load(expr.else_val)):
            # Nothing to spill: the arms are loads, and a load does not write
            # the flags. Compare, materialise both arms, select.
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self._emit_expr(expr.then_val)         # X0 = then arm
            self.asm.emit(encode_mov_zr_xn(1, 0))  # X1 = then arm
            self._emit_expr(expr.else_val)         # X0 = else arm
            # Select X1 when the condition held. The obvious-looking
            # `csel X0, X0, X1, ne` is WRONG here: X0 has been overwritten
            # with the else arm by now, so its "then" operand is the else arm
            # and the ternary comes out inverted. It compiles, runs, and
            # answers with the other value.
            self.asm.emit(encode_csel_xd_xm_cond(0, 1, 0, "ne"))
            return
        self.asm.emit(encode_stp_sp_pre(0, 31))
        self._emit_expr(expr.then_val)
        self.asm.emit(encode_stp_sp_pre(0, 31))
        self._emit_expr(expr.else_val)
        self.asm.emit(encode_mov_zr_xn(1, 0))            # X1 = else arm
        self.asm.emit(encode_ldp_sp_post(0, 31))        # X0 = then arm
        self.asm.emit(encode_ldp_sp_post(2, 31))        # X2 = condition
        self.asm.emit(encode_cmp_xn_imm(2, 0))
        self.asm.emit(encode_csel_xd_xm_cond(0, 0, 1, "ne"))

    def _is_pure_expr(self, e) -> bool:
        """True when evaluating `e` can be neither observed nor fatal.

        Deliberately narrow, because CSEL evaluates BOTH arms. An arm holding
        a call may print, mutate a blob, or hit a cap, and running it when its
        value is thrown away is a behaviour change, not an optimisation. So the
        allow-list is literals, locals, field reads, and arithmetic over them.

        Container literals are excluded even though a list display is
        side-effect-free in principle: a list arm reserves frame space for its
        blob, and reserving both arms' worth at once is a frame-pressure
        change for no benefit. Calls are excluded even for known-pure builtins,
        because the builtin set is exactly what grows over time and a stale
        allow-list here would silently change semantics when it does."""
        if isinstance(e, (F.IntLiteral, F.StringLiteral, F.BoolLiteral,
                          F.IdentExpr)):
            return True
        if isinstance(e, F.MemberExpr):
            return self._is_pure_expr(e.obj)
        if isinstance(e, F.UnaryOp):
            return self._is_pure_expr(e.operand)
        if isinstance(e, F.BinaryOp):
            return (self._is_pure_expr(e.left)
                    and self._is_pure_expr(e.right))
        if isinstance(e, F.TernaryExpr):
            return (self._is_pure_expr(e.condition)
                    and self._is_pure_expr(e.then_val)
                    and self._is_pure_expr(e.else_val))
        return False

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

    def _emit_str_membership(self, left, right, invert: bool) -> None:
        """`needle in haystack` with a STRING haystack — `strstr`/`strchr`.

        The measured state of this before it existed as a string path, on both
        backends: `if "ell" in s:` for `s = "hello"` terminated the process
        with SIGBUS. A string haystack that was not a syntactic literal fell
        through to the blob scan, which read the first eight bytes of the
        CHARACTERS as a `[count]` header and walked off the end of the mapping.

        Two libc calls, one per needle shape, and which one is decided by
        `model.string_membership_lowering` so that this backend and the x86-64
        one cannot disagree about what a given `in` is:

            needle is a char *   ->  strstr(HAYSTACK, NEEDLE) != NULL
            needle is a byte     ->  strchr(HAYSTACK, BYTE)    != NULL

        THE ARGUMENT ORDER IS THE WHOLE METHOD for `strstr`, and it is the
        reason this is not a one-liner: `strstr("bc", "abcabcabc")` is a
        well-defined NULL, so getting it backwards does not crash, does not
        look wrong in the image, and returns FALSE for every haystack that
        contains its needle — which is every real use of `in`.

        Two libc calls rather than the hand-written scans that were here
        before, for the reason the `strspn` change gives for `lstrip`: the
        call IS the algorithm, it cannot be half-right, and there is then
        nothing here to keep in step between two architectures. The substring
        scan that was here had a real bug of exactly the kind a second
        implementation of a libc routine has — it tested `hay[i] == 0` for the
        loop exit but read `hay[i + b]` for the compare, so a needle that
        matched a PREFIX walked one byte past the terminator.

        THE RESULT IS 0/1 IN X0, and that is not a detail: there is no BOOL
        kind distinct from INT on this path (which is why `__mlir_bool__` is
        refused), so "0/1" and "a bool" are the same thing here and a `cset`
        of a flag is the whole of it. `not in` inverts at the end, once.

        EDGE CASES, all of which the caller reaches and two of which are
        answered by libc rather than by us:

          * an EMPTY needle is TRUE, and `strstr` agrees: it returns the
            haystack itself, which is non-NULL. The old scan had a special
            case for it, and a membership test that says an empty needle is
            absent is wrong in the direction that HIDES bugs.
          * a needle LONGER than the haystack is FALSE, and `strstr` agrees:
            the terminator cannot match a non-terminator byte.
          * a needle at offset 0 and a needle at the very END both come back
            non-NULL, and both are TRUE.
          * the byte case with byte == 0 is the ONE thing libc gets wrong for
            this representation: `strchr(s, 0)` returns a pointer to the
            terminator, so a bare `!= NULL` would make `0 in "abc"` TRUE where
            Python says FALSE — and on this path it is certainly false, since
            the only NUL in a string is the one that ends it. So the byte is
            tested against zero in front of the call and the answer is
            materialised without calling anything.
        """
        # Both operands literal is a COMPILE-TIME answer, and it is taken first
        # because it is the one case where the answer is not a question about
        # the representation at all. The empty needle is TRUE here, which is
        # Python's rule and also what `strstr` would say, so the constant and
        # the call cannot disagree.
        if isinstance(left, F.StringLiteral) and isinstance(right, F.StringLiteral):
            # The EMPTY needle is TRUE, which is Python's rule and what
            # `strstr` returns for it (the haystack itself, non-NULL). Folding
            # it to False because `bool("")` is False made the
            # both-operands-literal case disagree with the call the same
            # expression makes when either side is a name.
            found = left.value == "" or left.value in right.value
            self.asm.emit(encode_movz_xd_imm(
                0, (0 if found else 1) if invert else (1 if found else 0)))
            return
        how = M.string_membership_lowering(
            self._expr_str_kind(left), self._expr_str_kind(right))
        if how is None:
            # The caller only routes here for a string haystack, so `how` is
            # None exactly when the NEEDLE is neither a string nor an integer:
            # no `strstr` and no `strchr` can be called, and the blob scan the
            # caller would otherwise use would read the needle's bytes at
            # whatever integer it happens to hold. Refused by name.
            raise CodegenError(
                f"`{'not in' if invert else 'in'}` with a string on the right "
                f"and {M.spelled(left)} on the left is refused: the needle's "
                f"kind is neither a string nor an integer, so there is no "
                f"`{M.STRING_SEARCH_SYMBOL}` and no "
                f"`{M.STRING_BYTE_SEARCH_SYMBOL}` to make the call with. "
                f"Annotate it, or bind it to a string or a byte this path can "
                f"see the type of")
        self._while_counter += 1
        hit = f"{self.func_name}_smh{self._while_counter}"
        miss = f"{self.func_name}_smn{self._while_counter}"
        end = f"{self.func_name}_smx{self._while_counter}"
        # 32 bytes of scratch at [sp, sp+32): haystack at +0, needle at +8.
        # An expression leaves its value in X0 and a call clobbers every
        # caller-saved register, so BOTH operands have to survive the call —
        # the same discipline `_emit_strcmp_flags` and `_emit_str_find` use,
        # and for the same measured reason (`"abc" == "abc"` was FALSE on
        # arm64 when one operand was parked in a register across a call).
        _emit_sub_imm(self.asm, 31, 31, 32)
        self._emit_expr(right)
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))        # [sp+0] = haystack
        if how == M.STRING_MEMBERSHIP_BYTE:
            # The needle is a byte VALUE, not a pointer, so it is masked here
            # rather than dereferenced: `s[1]` and a subscript are how a byte
            # is spelled, and both are integers that may be wider than 8 bits.
            # The mask is the byte the C comparison would use.
            self._emit_expr(left)
            self.asm.emit(encode_and_xd_xn_imm(0, 0, 8))
            self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))    # [sp+8] = byte
            self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))    # X1 = byte
            # `strchr(s, 0)` is non-NULL — it returns the TERMINATOR — so the
            # zero byte has to leave BEFORE the call, and it leaves as ABSENT,
            # which is what Python says and what the representation guarantees:
            # the only NUL in a string is the one that ends it. `cbz` (branch
            # if ZERO) to the miss block, NOT `cbnz`: the inverted test reads
            # the same on the page and inverts the whole table, so every real
            # byte came back absent and only `0 in s` came back present.
            self.asm.emit(encode_cmp_xn_imm(1, 0))
            self.asm.emit(encode_cbz_xn(1, 0))
            self.asm.emit_label_rel(miss, here_offset=-4)    # 0 in s is False
            # AAPCS: the HAYSTACK is the first argument and goes in X0. Loading
            # the byte into X0 and the haystack into X0 as well is a
            # two-operand mistake that reads as a one-instruction slip, and it
            # showed up as `98 in "abc"` returning FALSE on both backends with
            # every instruction in the image correct — libc was handed the byte
            # as the haystack and walked off the end of the mapping looking
            # for a NUL.
            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))    # X0 = haystack
            self._emit_extern_call(M.STRING_BYTE_SEARCH_SYMBOL, 2)
        else:
            self._emit_expr(left)
            self.asm.emit(encode_str_xt_xn_imm(0, 31, 8))    # [sp+8] = needle
            self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))    # X1 = needle
            self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))    # X0 = haystack
            self._emit_extern_call(M.STRING_SEARCH_SYMBOL, 2)
        self.asm.emit(encode_cmp_xn_imm(0, 0))               # NE iff found
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(hit, here_offset=-4)
        self.asm.emit(encode_movz_xd_imm(0, 0))              # NULL → absent
        self._emit_b_to(end)
        # `miss` — the `0 in s` exit — is placed BETWEEN the two, and BRANCHES
        # to `end` rather than falling into it, so the `hit` block's own fall
        # through lands on `end` and not on the constant that overwrites it.
        # With the labels the other way round, every present needle came out
        # absent: the image was correct in every instruction and returned
        # FALSE for `"ell" in "hello"` on both backends. Measured, and it is
        # the reason this comment is here rather than a `b` nobody questions.
        self.asm.label(miss)
        self.asm.emit(encode_movz_xd_imm(0, 0))
        self._emit_b_to(end)
        self.asm.label(hit)
        self.asm.emit(encode_movz_xd_imm(0, 1))              # non-NULL → present
        self.asm.label(end)
        # The SP restore comes AFTER the constant materialisations, and those
        # are flag-free, so the result in X0 is the only thing anything
        # downstream reads. `not in` inverts HERE, once, rather than at each of
        # the exits — three inversions is three chances for one of them to be
        # the one that is missing.
        if invert:
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cset_xd_cond(0, "eq"))
        _emit_add_imm(self.asm, 31, 31, 32)

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

        Bare Ident/Member del is a no-op (no GC; SRA slots persist).

        A multi-element subscript index is refused HERE, before the branches
        below, because the SubscriptExpr branch below is unreachable (it sits
        after the SliceExpr branch's `continue`), so without this
        `del a[i, j]` fell off the end of the loop and did NOTHING: it built,
        it ran, and the list still had three elements. A silent no-op where
        the source says "remove" is the one outcome this backend may not
        produce, and the refusal belongs at the point where the shape is still
        visible rather than in a branch nothing reaches."""
        for target in stmt.targets:
            if isinstance(target, (F.IdentExpr, F.MemberExpr)):
                continue
            if isinstance(target, F.SubscriptExpr) and (
                    M.is_multi_index(target.index)
                    or M.is_mlir_template(target)):
                why = M.multi_index_refusal_for(
                    target, self._is_dict_subscript(target.obj),
                    self._functions)
                raise CodegenError(
                    f"del {why}" if why is not None else
                    "del on a subscript with a tuple index is not supported "
                    "on the formal arm64 path")
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
