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
                          STRING_TYPE_NAMES, DICT_TYPE_NAMES,
                          DTYPE_TYPE_NAMES)

import fire_compiler as F
import mojo.middle.comptime as comptime_eval
from formal import model as M
from formal import monomorph
from mojo.middle.boundnames import (
    bound_names_in_order, _lbn_target_names,
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

# The argument registers BY NAME, in argument order.  `_ABI_ARG_REGS` is the
# count and the call path uses register NUMBERS (the encoders take numbers);
# the startup stub is the one site that materializes a literal into an
# argument register, and `_emit_mov_imm` takes a name.  x86-64's counterpart
# is `formal/x86_64.py`'s `ARG_REGS`, and it is here for the same reason it is
# there: the register file is the platform's, not the language's.
_ARG_X_REGS = ("X0", "X1", "X2", "X3", "X4", "X5", "X6", "X7")

# How many incoming arguments this backend passes IN TOTAL — eight in registers
# plus a stack area for the rest.  AAPCS has a stack convention and it is
# implemented, not refused: argument `8 + k` lives at `[SP + 8k]` as the callee
# enters, so a ninth argument is an ordinary load from the caller's frame rather
# than a hole.  The refusal that used to sit at `_ABI_ARG_REGS` on both ends was
# true about the register count and wrong about the consequence: it meant
# `struct.pack("<IIQQQQQQ", v0..v7)` could not reach its own module's documented
# "a format I cannot serve returns an empty list" contract.  That filing is
# deleted — it asked for exactly this and for the same convention against
# x86-64's register file, which `formal/x86_64_codegen.py` now has too, so the
# two backends are the one number rather than two.
#
# The bound is a FRAME bound and not an ABI one: every parameter past the
# eighth needs a home (a callee-saved register or a spill slot), and the spill
# area is finite.  Sixteen stack arguments is far past any call in this corpus
# and well inside `_SCRATCH`, so the number is a backstop rather than a design
# choice.
_MAX_INCOMING_ARGS = 24

# The local a frame-returning function keeps the CALLER'S block address in.
# A name rather than a dedicated register, so the word goes through the same
# register-or-spill-slot home every other local has; the leading underscores
# keep it out of any name the source can spell, and the reason it is not one of
# those is the same reason `_SCRATCH` is a constant: a source that binds this
# name must not be able to reach the convention's own state.
_SRET_LOCAL = "__sret_block"

# The local a one-field MUTATOR keeps the ADDRESS of its caller's one-word cell
# in, for the same reason `_SRET_LOCAL` exists: the word has to live somewhere
# the body cannot name, and it has to survive from the prologue — where the
# callee reads the receiver out of the cell — to every exit, where it writes the
# receiver back. `_recv_ref_receiver` names the receiver itself; this names the
# pointer to the cell holding it, and the two are read in that order at each
# exit (`model.receiver_writeback_name` is the rule).
_RECV_CELL_LOCAL = "__receiver_cell"


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
                # `depth + n` for the ITERABLE too, and the reason is the
                # emitter's convention rather than Python's: `_emit_comprehension`
                # raises `_compr_depth` to `d0 + len(gens)` for the WHOLE walk
                # — the iterable included, because `_emit_compr_gen` emits
                # `gen.iterable` after that assignment — so a nested
                # comprehension reached from an iterable is emitted at
                # `depth + n`. Reserving it at `depth` asked for `_ci{d}` where
                # the emitter wanted `_ci{d+n}`, and the emitter has no home for
                # a name the allocator never reserved: "… has no home".
                walk_compr_temps(g.iterable, depth + n, acc)
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


def _allocation_split(f: F.FunctionDef):
    """`(register-eligible names, address-taken names)` for a function.

    Comptime parameters first (they are leading arguments — the call site
    passes them ahead of the runtime ones, see `_comptime_param_names` and
    `_specialization_args`), then the runtime parameters (prologue always MOV
    X19, X0 — the FIRST parameter must be X19, so a generic function's X19 is
    its first comptime parameter and its first runtime parameter lands one
    register later), then for-list control temps (`_fi{d}`/`_fb{d}` — hot in
    the loop, prefer registers), then remaining locals in `_collect_var_names`
    order.

    **The second list is what makes the by-reference receiver convention work**
    (`model.receiver_writeback_name`). A one-field mutator receives the ADDRESS
    of its caller's storage, so the receiver's home must BE that storage rather
    than a callee-saved register: a register has no address, and the
    alternative — copying the word into a scratch slot around the call and back
    out again — has to be ordered against every other argument of the call,
    which is exactly the question `mutating_receiver_order_refusal` refuses.
    So those names are not merely LAST, they are removed from the first list:
    "past every register-eligible name" has to mean "in no register at all", or
    a function with fewer locals than registers hands the one receiver a register
    anyway and the call site has no address to pass.

    Split rather than one list because three readers need the two halves
    separately and a mismatch between them is a local with two homes: `_emit_function`
    allocates the first `register_home_count` names to X19..X28,
    `var_register_map` publishes the same map to the proof generator, and
    `_address_taken` is the contract the call site checks against.
    """
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
    base = ct + params + temps + others
    # Filtered to names this function really binds: the table is published from
    # the CALL SITES' walked arguments, so a name a later rewrite removed can
    # still be in it, and giving a home to a name no `AssignStmt` binds is a
    # second, silent answer to "where does this live".
    pinned_set = {n for n in getattr(f, "_address_taken", ()) if n in set(names)}
    ordered = [n for n in base if n not in pinned_set]
    pinned = [n for n in getattr(f, "_address_taken", ())
              if n in set(names) and n not in set(ordered)]
    return ordered, pinned


def _allocation_order(f: F.FunctionDef) -> list:
    """Every local of `f`, registers first — `_allocation_split`'s two halves.

    One list for the readers that want to walk the locals in allocation order;
    the register/spill boundary is `register_home_count`, not the position of a
    name in this list."""
    ordered, pinned = _allocation_split(f)
    return ordered + pinned


def register_home_count(f: F.FunctionDef) -> int:
    """How many of `f`'s locals get a callee-saved register.

    `len(register-eligible)` capped by the register file, and NOT `len(all
    locals)`: the address-taken names are the ones with no register, which is
    the whole point of the by-reference receiver convention. The same count
    `_emit_function` allocates with, and `var_register_map` publishes, so the
    proof generator's per-block register facts name the registers the codegen
    really used."""
    ordered, _pinned = _allocation_split(f)
    return min(len(ordered), len(_CALLEE_SAVED))


def var_register_map(f: F.FunctionDef) -> dict[str, int]:
    """Variable -> callee-saved register, matching `ARM64Codegen._emit_function`.

    The proof generator reuses this so per-block register-value facts name the
    same register the codegen actually allocated (parameters first, then
    for-list temps, then locals). Only `register_home_count(f)` names appear —
    the rest live in stack spill slots, and the address-taken ones live there
    DELIBERATELY (`model.receiver_writeback_name`)."""
    names = _allocation_order(f)
    return {name: _CALLEE_SAVED[i]
            for i, name in enumerate(names[:register_home_count(f)])}


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
dylib_exports: list = None, globals_base: int = None,
                 import_aliases: dict = None, extern_decls: dict = None,
                 entry_args: list = None):
        self.test_input = test_input
        # The startup stub's argument values, already NORMALISED by
        # `formal/build.py::_make_codegen` (the one place both backends are
        # constructed), so this backend and its proof generator read the same
        # list rather than each re-deriving it.  A one-argument entry is the
        # whole of every program in the corpus, and for it this is `[test_input]`
        # — the single `MOV` the stub always emitted.
        self.entry_args = list(entry_args) if entry_args else [test_input]
        # Where this unit's module-global data segment is MAPPED. A parameter
        # and not a lookup, because it differs per container (macho_linker and
        # elf define separate constants) and because every slot access has to be
        # computed against it BEFORE the image exists. None means "this unit has
        # no module globals", which is the ordinary case.
        self._globals_base = globals_base
        self.asm = Assembler()
        self._functions = {}
        self._structs: dict = {}
        # Filled by `compile()`: a callable NAME -> the label a call to it lands
        # on, and the per-definition labels it points at, which are not
        # published in `info["labels"]`. See `compile()` for why a name and an
        # address are two different things on this path.
        self._entry_labels: dict = {}
        self._internal_labels: set = set()
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
        # The functions whose prologue carries the stack-floor guard, filled by
        # `compile()` once the whole image's call graph is known — see
        # `model.stack_floor_guarded_names`. `compile()` is the only construction
        # path (`formal/build.py` is the only caller), so it always overwrites
        # this before a prologue is emitted.
        self._guarded_names: set = set()
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
        # `{id(call)}` of the calls that are an `ExprStmt`'s OWN value, per
        # function — `model.statement_call_ids`, the reader that tells a
        # by-reference mutator's two positions apart (its result is observed or
        # it is not).
        self._statement_calls: set = set()
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
        # Names bound to a list/tuple/set blob.  This is what makes `a + b` on
        # two LOCALS a concatenation: without it two bare idents are
        # indistinguishable from two integers and the operator silently lowers
        # to pointer arithmetic, so `var zs = xs + ys` answered with the sum of
        # two addresses and every read of `zs` was whatever was mapped there.
        # x86-64 has carried this table (and the `_is_container_expr` arm that
        # reads it) for a long time; the two backends must not answer the same
        # question differently, which is what made the operator architecture-
        # dependent.  Reset per function, like the sets above.
        self._blob_vars = set()
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
        # `{local name: (module as spelled, defining name)}` — what
        # `from m import f as g` binds. The flat map above is keyed by the
        # DEFINING name and a call site spells the LOCAL one, so without this
        # an aliased call found nothing and the image bound a symbol no library
        # defines. Consulted only for a bare callee that is an alias, and
        # resolved against the MODULE's export table, never the flat one: the
        # alias says where the name came from, and a name that happens to
        # collide with another library's export must still bind the module it
        # was imported from. See `model.dylib_aliased_export`.
        self._import_aliases: dict = dict(import_aliases or {})
        # `{export symbol: FunctionDef}` — the callee's OWN declaration, read
        # from the source each linked library was compiled from
        # (`formal/imports.py`'s `external_declarations`). Keyed by the symbol
        # the call binds, not by the name it is spelled, so a name collision
        # between two libraries cannot hand a call the wrong signature. Without
        # it an extern call passed `list(e.args)` and nothing more, and a
        # parameter the caller omitted kept whatever the caller last put in that
        # register: `need_two(1)` across a dylib returned 1867609072, a stack
        # address, where the callee's own default says 511.
        self._extern_decls: dict = dict(extern_decls or {})
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
        # The COMPREHENSION scope stack: `model.ValueKinds`.
        # `comprehension_generator_scopes` maps, outermost first, pushed by
        # `_emit_compr_gen` after each generator's target store. A comprehension
        # is its own scope in Python 3, so its loop variable is not a local of
        # this function and `ValueKinds.locals` must not answer for it — the
        # stack is what `_expr_str_kind` consults instead. Balanced by a
        # `finally` per generator, so it is empty between comprehensions and on
        # the way out of a failed one.
        self._compr_scopes: list = []

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
        # Which prologues carry the stack-floor guard, settled ONCE for the
        # whole image before any function is emitted (the guard is decided per
        # function, so it cannot be answered while a prologue is being written).
        # `values(self._functions.values())`, not `functions`: the guard reads
        # the same set of FunctionDefs either way, and this is the table the
        # emitters dispatch on.
        # `every_function` is `emit_startup`, and the two are the same fact: an
        # image with a startup stub has an ENTRY and therefore no exports, so
        # every prologue can carry the guard and nothing loses a per-export
        # contract (`model.stack_floor_guarded_names` carries the measurement).
        # A module dylib has no entry function and every function may be an
        # export, so it keeps the cycle-or-branch rule.
        self._guarded_names = M.stack_floor_guarded_names(
            self._functions.values(), self._structs,
            every_function=emit_startup)

        # A NAME is not an ADDRESS, and this is where that stops being true by
        # accident. `self._functions[f.name] = f` above means a name with two
        # definitions — an ordinary Mojo overload, or a class whose two
        # `__init__` overloads are renamed one — is ONE function in this image,
        # and a call to it reaches whichever body was registered last. That rule
        # is deliberate (`formal/build.py`'s `_check_holder_agreements` is asked
        # about EVERY definition for exactly this reason, and
        # `test_formal_run.py`'s `overload_*_CASES` assert the answer the last
        # body computes). What was NOT deliberate is how it reached the
        # assembler: every body was emitted under `self.asm.label(f.name)`, and
        # `Assembler.label` keeps the LAST address for a name, so the rule was
        # implemented by a silent rebinding — the defect
        # `Assembler.label` now refuses (fixed 2026-10-03 in 3656dc87).
        #
        # So each DEFINITION gets a label of its own, and the NAME is bound to
        # the last of them explicitly, below, once every body has been emitted.
        # The reachable set is unchanged — a call still lands on the last body,
        # at the same address — and what is left is a statement of that rule
        # instead of an accident of dict insertion order.
        self._entry_labels = {}          # callable NAME -> the label it lands on
        self._internal_labels = set()    # per-definition labels, not published
        self._def_labels = []            # per DEFINITION, in `functions` order
        nth: dict = {}
        for f in functions:
            n = nth.get(f.name, 0) + 1
            nth[f.name] = n
            label = f"{f.name}__def{n}"
            self._internal_labels.add(label)
            self._def_labels.append(label)
            self._entry_labels[f.name] = label

        self.asm.org(base_addr)

        first_func_name = functions[0].name
        self._entry_name = first_func_name if emit_startup else None
        if emit_startup:
            self.asm.emit(encode_stp_sp_pre(29, 30))
            test_val = self.test_input
            # `_emit_mov_imm`, not a hand-rolled movz+movk pair: it is the one
            # materializer on this backend, it covers the whole 64-bit word
            # (this pair did not — a `test_input` past 0xffff or below zero
            # emitted a truncated word, and nothing caught it because the
            # default is 10), and the same call is what `_emit_expr` makes for
            # every literal, so the startup word and a literal word are the same
            # code path.  One materializer per entry argument, in argument
            # order, because a `def main(n: Int, m: Int)` receives its second
            # parameter in x1 and the proof's concrete run test compares
            # against exactly what is emitted here (`model.entry_arg_values`).
            for _ai, _av in enumerate(self.entry_args[:len(_ARG_X_REGS)]):
                self._emit_mov_imm(_ARG_X_REGS[_ai], _av)
            self.asm.emit(encode_bl(0))
            self.asm.emit_label_rel(first_func_name, here_offset=-4)
            self.asm.emit(encode_ldp_sp_post(29, 30))
            self.asm.emit(encode_ret())

        for f, label in zip(functions, self._def_labels):
            self._emit_function(f, label)

        # Every body is out, so a NAME can be bound to the one a call reaches.
        # One binding per name, at one place, after every definition — which is
        # what the rebinding did by accident, stated on purpose. It happens
        # BEFORE `resolve()` so the startup `bl` above and every `bl` in a body
        # are patched out of it, and the per-definition labels stay out of
        # `info["labels"]` so a reader of that map sees one address per name,
        # which is what every consumer of it (`build.py`'s dylib export table,
        # `arm64_proof_gen.py`'s method table) is asking for.
        for name, label in self._entry_labels.items():
            self.asm.labels[name] = self.asm.labels[label]

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
            "labels": {n: a for n, a in self.asm.labels.items()
                       if n not in self._internal_labels},
            "func_name": first_func_name,
            "external_syms": external_syms,
            "extern_calls": extern_calls,
            "test_input": self.test_input,
            # EVERY entry argument's value, in order — the proof generator's
            # entry state is built from this list, so a two-parameter entry has
            # its x1 set to the same word the stub above materialized into it
            # rather than left to whatever the machine had.
            "entry_args": list(self.entry_args),
            # ADDRESSES (not offsets into `code` — `asm.label` records
            # `org + len(text)`, so a label is already the address the image
            # will map), in emission order, for the load-time initializer a
            # LIBRARY emits: `__TEXT,__init_offsets` in a Mach-O image,
            # `.init_array` in an ELF one. A container writes them into a
            # pointer array verbatim, which is only correct because this image
            # is loaded at the address it was linked at (no slide, no
            # rebase). Empty for every module with no body — which is every
            # program on this path, since a program enters its body through
            # the startup stub instead — so the key is inert unless a dylib
            # reads it.
            "mod_init_addrs": [
                self.asm.labels[f.name]
                for f in M.module_body_functions(functions)
                if f.name in self.asm.labels],
            # The INTERN TABLE, keyed by DECODED text: a string literal's value
            # on this path is the address of its bytes, and this is where those
            # addresses are.  `self._str_intern` is interning by content, so it
            # is one entry per distinct string and the mapping is 1:1 — which is
            # what lets a proof generator state "the machine's x0 holds THIS
            # word" about a call's string argument instead of fabricating one.
            # Published rather than recomputed: the label spelling is
            # `str_<emission counter>`, so the address is not derivable from
            # the text without replaying the emitter's own emission order.
            "str_addrs": {
                text: self.asm.labels[label]
                for text, label in self._str_intern.items()
                if label in self.asm.labels},
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

    def _emit_function(self, f: F.FunctionDef, label: str = None) -> None:
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
        # THIS DEFINITION's entry label, from the pre-pass in `compile()` — not
        # `f.name`, which is the name a CALL uses and which a second definition
        # of the same name shares.
        self.asm.label(label if label is not None else f"{f.name}__def1")

        # The by-reference RECEIVER locals first, because `_allocation_order`
        # reads `f._address_taken` to decide which names spill and this is what
        # completes the answer. It has to happen here rather than in the build
        # pass for the cross-module calls: `_prepare_functions` runs before the
        # imports resolve, so at build time there is no declaration to ask
        # (`formal/imports.py`'s `external_declarations` is read later, into
        # `self._extern_decls`). Publishing back onto the function keeps
        # `var_register_map` \u2014 the proof generator's reader of the same
        # allocation \u2014 in step.
        self._statement_calls = M.statement_call_ids(f)
        self._address_taken_for(f)
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
        # THIS function's own answer, from `formal/build.py`'s per-function
        # table — not `self._image_returns_frame.get(f.name)`, which is the
        # by-name JOIN. Two definitions of one name can disagree about whether
        # they return a frame (a Mojo overload pair where one ends `return
        # self` and the other `return self.other[…](…)`), and the by-name table
        # then gives both the same answer, so the hidden trailing block argument
        # is passed to a definition that does not want it or withheld from one
        # that does. The join is still what `_emit_call` asks, since a call site
        # carries a name; the by-name table stays name-keyed for that reason.
        self._returns_frame = getattr(f, "_returns_frame_struct", None)
        if self._returns_frame is None:
            # A function that never went through the frame analysis (a
            # synthetic one in an emitter unit test) has no per-function answer,
            # so fall back to the by-name table rather than to nothing.
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
        # The BY-REFERENCE RECEIVER, the other hidden convention, and it is read
        # off the function node for the same reason `_returns_frame` is: the
        # build pass (`formal/build.py`'s `_take_the_receiver_by_reference`)
        # decided it from the receiver's declared convention and the owner's
        # field count, and this emitter must not answer that question a second
        # time.  `_recv_ref_receiver` names the receiver whose value lives in
        # the CALLER's one-word cell at the address this function receives in
        # argument 0; `_recv_ref_sites` is this function's own table of the
        # hand-offs it MAKES (`model.struct_returned_frame_sites`'s shape).
        self._recv_ref_receiver = getattr(f, "_recv_ref_receiver", None)
        self._recv_ref_sites: dict = dict(
            getattr(f, "_recv_ref_sites", None) or {})
        if self._returns_frame is not None:
            var_names = list(var_names) + [_SRET_LOCAL]
        if self._recv_ref_receiver is not None:
            var_names = list(var_names) + [_RECV_CELL_LOCAL]
        n_reg = min(register_home_count(f) + len(var_names) - len(
            _allocation_order(f)), len(_CALLEE_SAVED))
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
        # order — and it is `struct_constructor_site_bytes`, not
        # `struct_frame_block_bytes`, because a ONE-FIELD struct whose sole field
        # holds a frame reserves the NESTED block alone (there is no object: the
        # value is the nested frame's address). One reader of that size, so a
        # site can never be reserved one amount and laid out another.
        self._frame_recv_bytes = sum(
            M.struct_constructor_site_bytes(st, self._structs)
            for st, _off, _nested in self._frame_sites.values())
        # Blocks for frames this function RECEIVES from a callee that returns
        # one.  The same region as the constructor frames and the same reason:
        # a returned block has exactly the lifetime a local one has — both live
        # in the creating function's scratch and die with it — so it goes at the
        # bottom of the same reserved scratch and the blob cursor starts above
        # the lot.  The layout is the shared model's, so x86-64 reserves the
        # same bytes at the same offsets and a returned frame cannot be correct
        # on one machine and a use-after-free on the other.
        # `model.frame_returning_predicate`, NOT `self._image_returns_frame.get`:
        # `struct_returned_frame_sites` takes a TWO-argument predicate and
        # `dict.get` takes `(key, default)`, so handing it the bound method
        # answers "no" with the bound NAME and treats every call in the module as
        # returning a frame.  The model's comment there has the measurement: five
        # wasted instructions per call, and a nine-argument call refused for an
        # argument it never had.
        self._ret_frame_sites = M.struct_returned_frame_sites(
            f, self._structs,
            M.frame_returning_predicate(self._image_returns_frame))
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
        # `{name: [StructDef, …]}` — the ONE-WORD mirror of the above, and the
        # second thing a word can be that is not an integer and not a frame: a
        # struct of exactly one field has no block, so `P(7)` binds a plain word
        # that IS `P`'s only field and every frame table is silent about it.
        # Published for the same reason the frame one is — a consumer that has
        # to know what a word is asks the table the analysis already built
        # rather than re-deriving the recognition (see `_printf_arg_is_text`).
        self._one_word_candidates = dict(
            getattr(f, "_one_word_candidates", None) or {})
        # `{name: declared return annotation}` — the evidence a construction
        # argument needs to be told apart from a container returned by a
        # callee.  Read once per function from the same function table the
        # emitter already has, so the answer cannot differ from the one the
        # build pass reached.  `CalleeReturnTable` rather than the bare mapping
        # because the construction pass also asks the SECOND question — what a
        # callee that declares no return type returns — and a second table
        # threaded through three callers is a second thing to keep in step.
        self._return_types = M.CalleeReturnTable(
            self._functions.values(), int_names=TYPE_NAMES,
            string_names=STRING_TYPE_NAMES)
        # What an UNANNOTATED parameter holds, agreed over every call site — the
        # hook `ValueKinds` asks, and the one reader for both backends
        # (`ParameterKindReader`), so the two architectures cannot disagree about
        # whether a word arriving from a caller is a `char *`. Lazy: a module
        # that annotates its parameters never walks its own bodies for it.
        self._param_kinds = M.ParameterKindReader(
            self._functions.values(), self._return_types)

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
        self._blob_vars = set()
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
        self._dict_caps, self._dict_caps_by_name = M.dict_store_capacity(
            f, M.dict_store_sites(f))

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
        if len(incoming) > _MAX_INCOMING_ARGS:
            # The other end of the same refusal. `_emit_call` catches a call
            # SITE with too many arguments, but a function can also be REACHED
            # without one — a dylib export, a reflection-resolved call, an
            # entry point the driver calls directly — and this used to answer
            # that by `break`ing out of the loop, which leaves every parameter
            # past the eighth with its home slot never written. The first read
            # of such a name then loaded whatever the slot held, so the value
            # was not merely wrong but BUILD-DEPENDENT. Refusing here means
            # the arity is rejected whichever way the function is entered.
            #
            # The limit is `_MAX_INCOMING_ARGS` and not `_ABI_ARG_REGS` because
            # the ninth argument onwards is a STACK argument, not an error: AAPCS
            # puts arguments 0..7 in X0..X7 and the rest in the caller's frame at
            # ascending offsets from the SP the callee enters with. See
            # `_load_home_from_stack` below, which is the other half of the same
            # convention as `_emit_call`'s `SUB`/`ADD`.
            raise CodegenError(
                f"{f.name}: {len(incoming)} parameters exceeds the "
                f"{_MAX_INCOMING_ARGS} the formal arm64 ABI passes ("
                f"{_ABI_ARG_REGS} in registers and "
                f"{_MAX_INCOMING_ARGS - _ABI_ARG_REGS} on the stack)")
        # Which incoming argument is the BY-REFERENCE RECEIVER, if this is such a
        # function. Not 0 unconditionally: a generic method's comptime
        # parameters are LEADING arguments (`model.incoming_args`, and
        # `_emit_call` prepends the bracket expressions), so
        # `def bump[T: Int](out self, k: Int)` receives its cell in X1.
        recv_idx = (len(_comptime_param_names(f))
                    if self._recv_ref_receiver is not None else None)
        for i, (pname, ptype) in enumerate(incoming):
            if i == recv_idx:
                # The receiver arrives as the ADDRESS of a one-word cell the
                # CALLER owns, not as the receiver. Park the address in a home
                # (every exit needs it, and X0..X7 are caller-saved), then read
                # the word out of the cell into X19 — so the "already in X19 by
                # the unconditional save above" invariant every other
                # first-parameter path relies on still holds, and the body reads
                # `self` as the VALUE it has always read. Every lowering below
                # is then unchanged, which is the point of doing it in the
                # prologue rather than rewriting the body's field accesses.
                self._store_var(_RECV_CELL_LOCAL, i)
                if i > 0:
                    # X16, NOT X19: for a generic method the receiver is not
                    # argument 0, and X19 already holds argument 0's value
                    # because it IS argument 0's home — `def bump[T](out self)`
                    # has `T` in X19, and loading the receiver there made the
                    # callee add the receiver's value instead of the bracket's.
                    # Measured, arm64: `c.bump[7](3)` printed `v=13` where the
                    # source says 15. X16 is the address scratch every other
                    # `_load_home_from_reg` caller borrows, so nothing else has
                    # to know this path exists.
                    self.asm.emit(encode_ldr_xt_xn_imm(16, i, 0))
                    self._load_home_from_reg(pname, 16, ptype)
                    continue
                self.asm.emit(encode_ldr_xt_xn_imm(19, 0, 0))
                if pname in self._var_spills:
                    self._load_home_from_reg(pname, 19, ptype)
                    continue
                if ptype is None:
                    continue     # a comptime parameter: already a full word
                self._emit_extend(19, 19,
                                  resolve(parse_type_name(ptype)
                                          or DEFAULT_INT_TYPE))
                continue
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
            # An incoming argument register becomes this local's home — a
            # callee-saved register when one was left, a spill slot otherwise,
            # and the store is what makes the body read the caller's value
            # rather than whatever the slot held. ONE routine for the write,
            # because the returned-frame hidden word below has the same
            # requirement and is not a parameter: it is an address, so it must
            # not be narrowed to a declared width.
            self._load_home_from_reg(pname, i, ptype)
        # …and the ones past the eighth, which AAPCS does NOT pass in a
        # register.  Argument `8 + k` arrives at `[SP_in + 8k]`, and `SP_in` is
        # the SP this function was called with — which the prologue above has
        # already moved past, so the address is the frame pointer plus the
        # sixteen bytes of saved FP/LR: `[X29 + 16 + 8k]`.  Every one of those
        # offsets is ABOVE X29 and every spill slot is below it, so a parameter
        # home can never land on the argument it is being loaded from.
        #
        # Before this existed the answer was to refuse, and the refusal was
        # right about the ABI and wrong about the consequence: `pack(fmt, v0..v7)`
        # is nine arguments, and it is `formal/hostmods/struct.mojo`'s OWN
        # documented "a format I cannot serve returns an empty list" contract
        # that the caller could never reach.  `bugs/FORMAL_struct_pack_over_eight_
        # arguments.md` has the measurement and both halves of the mechanism.
        for i, (pname, ptype) in enumerate(incoming):
            if i >= _ABI_ARG_REGS:
                self._load_home_from_stack(pname, i, ptype)
        # The RETURNED-FRAME hidden word, moved from the register the caller
        # passed it in to its home, in the same place and for the same reason
        # as the parameters above: every incoming argument is caller-saved, so
        # anything still in X0..X7 when the body starts is the CALLER's value
        # again.  It is a full word and NOT extended — it is an address, and
        # narrowing it would be a pointer into the low half of a stack.
        if self._returns_frame is not None:
            sret_arg = len(incoming)
            if sret_arg >= _ABI_ARG_REGS:
                raise CodegenError(
                    M.returned_frame_convention_refusal(f.name, sret_arg)
                    or f"{f.name} needs one hidden word for the caller's block "
                       f"and there is no argument register left for it")
            self._load_home_from_reg(_SRET_LOCAL, sret_arg)
        _emit_sub_imm(self.asm, 31, 31, _SCRATCH)
        # The stack-floor guard, immediately after the subtraction it guards,
        # and only in a function a call chain can re-enter: see
        # `model.stack_floor_guarded_names` for why the set is a cycle PLUS every
        # body that already branches, and `model.stack_floor_address` for the
        # sequence itself.
        if self.func_name in self._guarded_names:
            self._emit_stack_floor_guard()

        for stmt in f.body:
            self._emit_stmt(stmt)

        if not _always_returns(f.body):
            if self._recv_ref_receiver is not None:
                # A body that falls off its end is an exit like any other, and
                # it is the one that used to be reached by the appended
                # `return self`.  The `movz #0` is the same word it emitted for
                # every other fall-through, and the caller of a mutator ignores
                # it.
                self._emit_receiver_writeback()
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
            # One entry per LEVEL, not one entry per chain: `formal/build.py`'s
            # `_fill_chain_levels` publishes `h.a`, `h.a.b`, `h.a.b.c` … and the
            # recursion below is what turns a read of the last of those into the
            # sequence of loads the others describe. `h.a.b` is the two loads
            # this table has always meant and `h.a.b.c` is the same sequence
            # with a third step, reached by asking about its own prefix rather
            # than by walking a list of slots: the temporary is X17 throughout
            # because a middle frame's ADDRESS is what the next step loads from,
            # so the last one reads the VALUE into `dst`.
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
        # A FUNCTION of THIS image, read as a value, is its CODE ADDRESS.  Last
        # of the homes and not the first, because that is what makes shadowing
        # free: a local or a parameter spelled like a function is found by one of
        # the four arms above and never reaches here, which is the case
        # `test_formal_specialization.py`'s shadowing guard pins.
        #
        # It is `ADRP`+`ADD` and nothing else, and it is the assembler call a
        # STRING LITERAL's address already uses (`emit_adrp_add`), so the one
        # thing being invented here is that the label is code rather than data.
        # The label a NAME resolves to is bound after every body is out
        # (`compile()`'s `_entry_labels` loop) and `resolve()` runs after that,
        # so a function used as a value before its own definition is emitted is
        # the same address a direct call to it reaches.
        if name in self._functions:
            self.asm.emit_adrp_add(dst, name)
            return
        raise CodegenError(self._no_home(name))

    def _emit_stack_floor_guard(self) -> None:
        """Refuse instead of dying when the frame just taken crosses the floor.

        Every function on this path subtracts a FIXED 128 KiB frame and nothing
        checked the result, so the reachable recursion depth was `8 MiB /
        128 KiB` and crossing it was a SIGSEGV with no output and no status —
        measured on this tree: `deep(61)` answers, `deep(62)` dies with exit
        139. This converts that into `exit(STACK_TRAP_STATUS)`, which is the
        one outcome this backend already has an idiom for and the one a caller
        can read.

        The sequence and every decision in it are `model.stack_floor_address`'s
        and are written down there; what is here is its instruction selection:

            ADRP+ADD X17, &floor ; LDR X16, [X17]      the floor word
            CBNZ X16, done                             already stored
            ADD X16, SP, #0 ; SUB X16, X16, #BUDGET    the first caller sets it
            STR X16, [X17]
        done:
            ADD X17, SP, #0 ; CMP X17, X16
            B.HS ok                                    SP >= floor: carry set
            movz x0, 2 ; movz x16, 1 ; svc #0x80       SP < floor: exit(2)
        ok:

        **Every one of those forms is one `lib/ProofLib.lean` already reads.**
        That is not luck and it is the reason the sequence is shaped this way
        rather than as the shorter `CMP SP, X16`: the model reads an `Rn` of 31
        as `s.sp` in exactly the forms A64 gives that encoding to — `ADD Xd, SP,
        #imm` and the register `CMP` among them — and as the ZERO register
        everywhere else. So both the `ADD Xd, SP, #0` and the `CMP` that
        follows name two ordinary registers once the first has run, which is
        the same pair of instructions the machine executes either way.

        X16 and X17: the intra-procedure scratch pair `_emit_global_init` and
        the spill addressing already use. Neither holds anything across a
        prologue — AAPCS delivers arguments 0..7 in X0..X7 and every incoming
        argument has been moved to its home above this point.
        """
        if self._globals_base is None:
            # No `__DATA`, so no word to keep the floor in, so nothing to
            # compare against. `formal/build.py` always hands a base over — the
            # data segment is unconditional since the floor word landed — so
            # this is the `_emit_global_init` shape rather than a live case.
            return
        self._if_counter += 1
        sid = self._if_counter
        fn = self.func_name
        done_label = f"{fn}_sf{sid}_done"
        trap_label = f"{fn}_sf{sid}_trap"
        ok_label = f"{fn}_sf{sid}_ok"
        floor = M.stack_floor_address(self._globals_base)
        # X17 = the address of the floor word, X16 = the floor itself. The
        # same ADRP/ADD pair and the same LDR the lazy global initializer uses,
        # for the same reason: it is the addressing this backend already proves
        # against a real dyld rather than a new one.
        self._adrp_add_abs(17, floor)
        self.asm.emit(encode_ldr_xt_xn_imm(16, 17, 0))
        self.asm.emit(encode_cbnz_xn(0, 16))
        self.asm.emit_label_rel(done_label, here_offset=-4)
        # SP - BUDGET, through `_emit_sub_imm` rather than a bare immediate:
        # the budget is 7.5 MiB and an imm12 tops out at 4095, so this is the
        # same two-instruction shift the frame subtraction itself is.
        self.asm.emit(encode_add_xd_xn_imm(16, 31, 0))
        _emit_sub_imm(self.asm, 16, 16, M.STACK_FLOOR_BUDGET_BYTES)
        self.asm.emit(encode_str_xt_xn_imm(16, 17, 0))
        self.asm.label(done_label)
        # SP into X17, then `SP - floor`. The stack grows DOWN, so having spent
        # the budget is `SP < floor`, which is the subtraction BORROWING and so
        # carry CLEAR. `B.HS` is the complement of that — "carry set", i.e.
        # `SP >= floor` — and it branches OVER the trap, so the trap is the
        # fall-through and the body's first instruction is the branch target.
        self.asm.emit(encode_add_xd_xn_imm(17, 31, 0))
        self.asm.emit(encode_cmp_xn_xm(17, 16))
        self.asm.emit(encode_b_cond("hs", 12))
        self.asm.emit_label_rel(ok_label, here_offset=-4)
        # The trap is three instructions: `movz x0, <status>; movz x16, 1; svc
        # #0x80` is Darwin arm64 `exit(status)`, and it is the same sequence
        # with the same shape as the divide-by-zero arm of `_emit_div_shift_pow`.
        self.asm.label(trap_label)
        self.asm.emit(encode_movz_xd_imm(0, M.STACK_TRAP_STATUS))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        # `label`, not `emit_label_rel`: this DEFINES where the branch above
        # goes, and it lands on the first instruction of the BODY because the
        # trap is the fall-through. Branching OVER the trap rather than TO it
        # is the layout the divide-by-zero arm already uses
        # (`_emit_div_shift_pow`), and keeping the two the same shape is what
        # keeps the basic-block structure of a prologue the same as the one the
        # proof generator already walks: a branch to a three-instruction trap
        # block whose successor is the next thing to do. The alternative — a
        # `b` over the trap — adds a basic block that is nothing but an
        # unconditional branch, and a block with no instructions to run breaks
        # `formal/arm64_proof_gen.py`'s syntactic fuel chain (measured: `rw`
        # fails on `fuel - 0`).
        self.asm.label(ok_label)

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
            # The `_load_var` twin: the OUTER load is itself a lookup in the same
            # table, so a chain of any length the constructor placed to the
            # bound is storable as well as readable without a second mechanism.
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

    def _load_home_from_stack(self, name: str, index: int, ptype=None):
        """`[SP_in + 8·(index - 8)]` → this local's home, the stack half of AAPCS.

        The counterpart of `_load_home_from_reg` for the arguments that have no
        register, and it delegates to that function for the write so the two
        ends of the convention share one home-assignment rule: `X16` here is
        exactly `X<src>` there.

        The offset is `[X29 + 16 + 8·(index - 8)]`, positive and small (a
        function with 24 arguments and five saved pairs puts the last one at
        X29+112), so it is a plain unsigned scaled `LDR` and no scratch
        register is spent computing an address — which matters because X17 IS
        the address scratch `_store_var` uses on the spill path, and borrowing
        it here would overwrite the value before the store.

        A comptime parameter is already a full word with no declared width to
        normalize to, which is why `ptype=None` skips the extend — the same
        rule `_load_home_from_reg` applies, and for the same reason: narrowing a
        pointer to a declared width would truncate half of it.
        """
        self.asm.emit(encode_ldr_xt_xn_imm(16, 29,
                                           16 + 8 * (index - _ABI_ARG_REGS)))
        self._load_home_from_reg(name, 16, ptype)

    def _emit_receiver_writeback(self) -> None:
        """`*cell = self` — the one-field mutator's whole caller-visible effect.

        The callee half of `model.receiver_writeback_name`, and it replaces the
        `return self` this file used to append to every exit: the receiver's new
        value went back in the RETURN REGISTER, which is (a) why a mutator that
        also returned a value had nowhere to put one — `BinaryHeap.pop` — and
        (b) why the store only existed for a call in STATEMENT position, so
        `sink(c.bump(5))` and a call into another module both dropped it.

        Three registers, and the order is the whole of it. X15 first because
        `_load_var`'s spill path addresses through X17, so the receiver must be
        in hand before the cell's address is materialized; X16 next for the same
        reason; then one `STR`. Neither clobbers X0, so a `return <value>` has
        already put its answer there and this does not disturb it — which is the
        property that makes "mutate AND return" one lowering rather than two.
        """
        self._load_var(self._recv_ref_receiver, 15)
        self._load_var(_RECV_CELL_LOCAL, 16)
        self.asm.emit(encode_str_xt_xn_imm(15, 16, 0))

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
        # A FUNCTION of ANOTHER image, read as a value, has no address here.
        # This unit has the DECLARATION (it is how the callee's parameters are
        # bound for an ordinary call into a linked library) and no CODE — the
        # body is in the library, and materializing an address for it needs a
        # GOT slot and a stub section this assembler does not have.  It used to
        # be asked about `name in self._functions`, which `_load_var` now
        # answers before it comes here: a function of THIS image is an
        # `ADRP`+`ADD` away and is lowered, so the arm is the cross-image case
        # and `model.function_value_refusal` is still the sentence for it.
        if name in self._extern_decls:
            return M.function_value_refusal(name,
                                            self.func_name or "<module>")
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
                if self._recv_ref_receiver is not None:
                    self._emit_receiver_writeback()
                self.asm.emit(encode_movz_xd_imm(0, 0))
            elif self._returns_frame is not None:
                self._emit_frame_return(stmt.value)
            else:
                self._emit_expr(stmt.value)
                if self._recv_ref_receiver is not None:
                    self._emit_receiver_writeback()
            self._flush_pending_finally()
            self._emit_epilogue()
            return

        if isinstance(stmt, F.IfStmt):
            self._emit_if(stmt)
            return

        if isinstance(stmt, F.ExprStmt):
            # A dialect EFFECT whose value is discarded lowers here rather than
            # being refused: there is no result to represent and nothing reads
            # one, so the only thing left to emit is the effect itself — and
            # this path's one divergence is what `raise` already emits. Asked
            # through `model.mlir_effect_diverge_call`, the single reader of
            # that table, because a per-emitter copy is how the two
            # architectures come to disagree about what an operation denotes.
            if M.mlir_effect_diverge_call(stmt.value) is not None:
                self._emit_diverge()
                return
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
            # effects (args of `raise RuntimeError(...)` etc.), then diverge.
            # except handlers stay unreachable — there is no
            # unwinder to route to; the nonzero status is the signal.
            if stmt.value is not None:
                self._emit_expr(stmt.value)
            self._emit_diverge()
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
            # A STORE through a pointer's pointee, `p.value() = v`. Asked
            # here rather than left to the plain-name branch below, which
            # refuses a `CallExpr` target — and the receiver question is asked
            # FIRST because the read side asks it too: a `.value()` whose
            # receiver this path knows to hold a string is not a pointer at all
            # (527 of the corpus's 528 `.value()` sites are an enum, an iterator
            # or a SIMD), and a store through the text section is a SIGBUS
            # rather than a value.
            store_obj = M.pointer_store_receiver(stmt.target)
            if store_obj is not None:
                if self._expr_str_kind(store_obj) == M.STR_KIND:
                    raise CodegenError(M.read_only_text_store_refusal(
                        _dotted(stmt.target.func), store_obj))
                self._emit_pointer_store(stmt.target, stmt.value)
                return
            if isinstance(stmt.target, F.MemberExpr):
                name = _member_slot_key(stmt.target)
                if name is None:
                    # A store into a frame a POINTER names: the store half of
                    # the member-read arm's `p.value().field`, and refused below
                    # with a sentence about the BASE that the read arm would
                    # make false.  `model.pointer_frame_expression` is the same
                    # decision the read made, so the two cannot disagree about
                    # what the base holds.
                    st, _why = M.pointer_frame_expression(
                        self._cur_fn, M.member_base_node(stmt.target),
                        self._structs, self._structs)
                    if st is not None:
                        slot = M.struct_frame_slot(st, stmt.target.member)
                        if slot is None:
                            raise CodegenError(
                                f"{M.spelled(stmt.target)} stores into "
                                f"{stmt.target.member!r} of a {st.name} this "
                                f"pointer points at, and that struct's "
                                f"{M.struct_field_summary(st)} has no such "
                                f"field: this path has no way to know which "
                                f"word that is, and storing to the wrong one "
                                f"is a wrong answer rather than a failure")
                        self._emit_frame_store_through(
                            stmt.value, M.member_base_node(stmt.target), slot)
                        return
                    # REFUSED, not dropped. This used to evaluate both sides and
                    # return, which is a SILENTLY DISCARDED STORE: the program
                    # built, ran, and the write was simply not there
                    # (`g().x = 1` and `a[i].x = 1` both lost it). x86-64's
                    # arm here has refused since, with these words, so the same
                    # source built on one architecture and was refused on the
                    # other — the two-backends-disagree shape this pair may not
                    # have. Measured on this tree before the change:
                    # `--backend=arm64` built both stores and dropped them,
                    # `--backend=x86_64` refused both with
                    # `field_access_refusal`. Wave 5's rule at its most
                    # literal: a missing branch here is a dropped store, not a
                    # wrong value. The words are the shared model's, so both
                    # arches print the same line, and they spell the BASE
                    # (`a[0]`, not `…`) because that is the expression the
                    # reader wrote and the one the message is about.
                    #
                    # The base is EMITTED first, which is what a base that is
                    # itself unanswerable needs to say so rather than being
                    # reported as an unclassifiable field — `model.
                    # member_access_refusal`'s docstring is the argument, and
                    # this line is what it is for.
                    self._emit_expr(M.member_base_node(stmt.target))
                    raise CodegenError(M.member_access_refusal(
                        stmt.target, self.func_name, self._frame_holders))
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
            # An internal invariant, not a source construct.  `formal/build.py`
            # lowers every `with` to the context-manager protocol before any
            # codegen runs (`_rewrite_with_statements`), so a `WithStmt` here
            # means that pass did not see it — and the emitter used to have a
            # lowering of its own for it, which is how `with
            # tempfile.TemporaryDirectory() as d:` built, ran, printed the right
            # answers and left the directory on disk.  One implementation of the
            # protocol, in the pass that owns statement rewriting.
            raise CodegenError(
                f"{getattr(self._cur_fn, 'name', '<module>')}: a `with` "
                f"reached the emitter unrewritten, "
                f"which is a bug in formal/build.py's `_rewrite_with_statements` "
                f"and not a construct in this file: every `with` is lowered to "
                f"`__enter__`/`__exit__` before codegen")

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

    def _emit_diverge(self) -> None:
        """Leave the machine: run every enclosing finally, then Darwin
        `exit(1)`.

        The ONE way control stops on this path, and both of its callers share
        it rather than spelling the three instructions each: a `raise`, which
        has no unwinder to route to, and a dialect trap used as a statement
        (`model.mlir_effect_diverge_call`), which has no result and so leaves
        nothing else to emit. Two copies of `movz x0, #1; movz x16, #1;
        svc #0x80` is how two of them come to differ, and the finally flush is
        the part that is easy to drop — a `raise` inside a `try` must still run
        the `finally` on its way out.
        """
        self._flush_pending_finally()
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))

    def _emit_try(self, stmt: F.TryStmt) -> None:
        """try/except/else/finally without an exception runtime.

        Handlers are skipped: formal has no unwinder, so there is no
        edge from a raise site to an except arm (RaiseStmt itself exits
        the process after flushing finallys). `else` runs on the success
        path (always, without EH). On fall-through the finally emits
        here; on return/break/continue/raise `_flush_pending_finally`
        already ran it and truncated the stack — so the pop below is
        stack bookkeeping and nothing else.

        **The fall-through copy is emitted even when an exit edge inside
        the body already flushed this frame**, and that is a fix rather than
        an optimisation: the flush happens where the `return`/`break`/
        `continue`/`raise` is EMITTED, while the fall-through path is a
        different path through the same block, and it is still reachable. The
        old shape decided "was the frame flushed? then the end is unreachable"
        and dropped the copy, which is right for an UNCONDITIONAL `return` and
        wrong for every other case — measured on both architectures, with
        `try: if n > 0: return 1; … finally: print()` printing nothing at all
        when `n` was 0, and with a `continue` inside a `try` in a loop
        skipping the cleanup on every later iteration. Both are the failure
        this path exists to refuse elsewhere: a program that runs, exits 0 and
        has silently not done what its source says. The copy is dead code in
        the unconditional case, which costs bytes and nothing else.
        """
        fin = stmt.finally_body or []
        if fin:
            self._pending_finally.append(fin)
        try:
            for s in stmt.body:
                self._emit_stmt(s)
            for s in (stmt.else_body or []):
                self._emit_stmt(s)
        finally:
            if fin and self._pending_finally \
                    and self._pending_finally[-1] is fin:
                self._pending_finally.pop()
        for s in fin:
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
                # Non-named base (`a[i].x, b = …`): REFUSED, with the words the
                # single-assignment arm above uses for the same store. This used
                # to "evaluate for effects, store nowhere", which is a SILENTLY
                # DISCARDED STORE in a program that then runs and computes an
                # answer nobody wrote — and x86-64's `_tuple_target_key` has
                # refused this shape since, so the same source built on one
                # architecture and was refused on the other. The base is emitted
                # first for the reason `model.member_access_refusal` gives.
                self._emit_expr(M.member_base_node(el))
                raise CodegenError(M.member_access_refusal(
                    el, self.func_name, self._frame_holders))
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
        #
        # The STRIDE is `M.walk_stride`'s, not the element stride, and this is
        # the same bug `for k in d` had and `M.walk_stride` was written for: a
        # dict is `[npairs][k0][v0][k1][v1]…`, so CPython's `k, v = d` binds the
        # two KEYS and an element-stride read binds the key and the value — the
        # second target answers the first VALUE. Measured on both architectures
        # before this line: `d = {"a": 1, "b": 2}; k, v = d; print(k); print(v)`
        # printed `4376687999` and `1` on x86-64 and `4328785236` and `1` on
        # arm64 — two DIFFERENT addresses for the same key, so the two
        # architectures disagreed as well as disagreeing with CPython, all of
        # it exit 0. The count check above is already the right one (a dict's
        # count field holds its pair count), which is why only the loads move.
        stride = M.walk_stride(self._is_dict_subscript(value))
        for i in range(n_t):
            self._emit_blob_load(9, 8 + stride * i)
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
            self._emit_blob_load(9, 8 * (i + 1))
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

        A `while` is the obvious layout:

            start:  <condition>  --falsy--> false:
                    <body>
            step:   B start
            false:  [<else_body>]
            end:

        A `for … in range(…)` is NOT the same shape, and the whole difference is
        one rule: **CPython binds the loop variable to each value the iteration
        produces, so after the loop it holds the LAST one** — while this layout
        tests the counter before it is advanced, so its exit path arrives one
        past. Measured, both architectures, on a five-line program:
        `for i in range(0, 3): …` then `print(i)` is 2 under CPython and was 3.

            start:  <test>  --holds--> init:   i = start_val
                    B false                   (an empty range must not BIND
            init:   i = start_val             the counter at all — see below;
            body:   <body>                    it is CPython's rule, not an
            step:   i += step                 optimisation, and the emptiness
                    <test> --holds--> body     is a run-time fact as often as
                    i -= step                 not a compile-time one)
                    B false
            false:  [<else_body>]
            end:

        The counter is tested BEFORE the increment, so the loop-exit path
        arrives with the counter one past the last value the body saw, and the
        `i -= step` puts it back. Restoring on the exit path rather than testing
        differently is what makes `break` right too: `break` leaves the counter
        at the value the body last had, which is the last value CPython bound,
        and it jumps past the restore.

        The alternative — subtracting on every exit including the empty range —
        is one instruction shorter and is WRONG, and the case that shows it is
        `i = 0` before an `for i in range(0, 0)`: CPython prints 0 and a
        blanket `i -= step` prints `-step`. Hence the first test being emitted
        separately from the loop-back test.

        **The head test reads `start_val`, not the counter, and that is the
        second half of the same rule.** CPython's `for` binds the target only
        when the iteration produces a value, so a range that yields NOTHING must
        leave a name that already held one alone. Storing `start_val` into the
        counter before the test cannot express that: measured on both
        architectures, `i = 7; for i in range(0, 0): …` left `i == 0` where
        CPython leaves 7 — and the emptiness is a RUN-TIME fact as often as not
        (`for i in range(0, k)` with `k <= 0`), so it cannot be decided by
        looking at the arguments. Hence `init:`, between the head test and the
        body, which is where the store goes. It costs a second evaluation of
        `start_val`, so it is only emitted when `model.expr_is_repeatable` says
        the second one has the same answer; `for i in range(f(), 0)` keeps the
        store-then-test order, which is the old behaviour and the only sound one
        there. The instruction vocabulary is unchanged (CMP, B.cond, and the
        store the prologue already emitted), so the model needs no new step.

        `continue` → step (for-loops still advance the counter)."""
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        start_label = f"{fn}_loop{wid}_start"
        init_label = f"{fn}_loop{wid}_init"
        body_label = f"{fn}_loop{wid}_body"
        step_label = f"{fn}_loop{wid}_step"
        false_label = f"{fn}_loop{wid}_false"
        end_label = f"{fn}_loop{wid}_end"

        is_for = for_info is not None
        for_conds = None
        # Whether the head test can read `start_val` and leave the store for
        # `init:`. Set here so the prologue below knows not to store, and read
        # again inside the loop; `model.expr_is_repeatable` is the shared answer
        # and the x86-64 backend asks the same question for the same reason.
        bind_after_test = False
        if is_for:
            target, rargs = for_info
            start_val, end_val, step_val = self._range_info(rargs)
            bind_after_test = M.expr_is_repeatable(start_val)
            if not bind_after_test:
                self._emit_expr(start_val)
                self._store_var(target, 0)
            # The comparison has to follow the step's direction, or a descending
            # range exits immediately (and an ascending one would run away). A
            # step whose sign is only known at runtime is refused rather than
            # silently mis-compiled: the counter advances correctly but the loop
            # bound would be the wrong way round, which is a wrong answer, not a
            # slow one.
            _down = self._for_step_sign(step_val)
            if _down is None:
                raise CodegenError(
                    f"for-range step must be a literal or a negated "
                    f"literal, so the loop bound can be chosen at compile "
                    f"time (got {step_val!r})")
            for_conds = ("hi", "gt") if _down else ("cc", "lt")

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
                #
                # The left operand is `start_val` itself when the store was
                # deferred to `init:`, and the COUNTER otherwise. Both are the
                # same comparison with the same condition codes; the difference
                # is only which word answers it, and only the `init:` below
                # depends on that.
                self._emit_branch_if_cmp(
                    start_val if bind_after_test else F.IdentExpr(target),
                    end_val, for_conds[0], for_conds[1],
                    init_label if bind_after_test else body_label)
                self._emit_b_to(false_label)
                if bind_after_test:
                    self.asm.label(init_label)
                    self._emit_expr(start_val)
                    self._store_var(target, 0)
            elif not self._emit_branch_unless(cond, false_label):
                self._emit_truthy_word(cond)
                self.asm.emit(encode_cmp_xn_imm(0, 0))
                self._record_cond_branch()
                self.asm.emit(encode_cbz_xn(0, 0))
                self.asm.emit_label_rel(false_label, here_offset=-4)

            self.asm.label(body_label)
            for s in body:
                self._emit_stmt(s)

            self.asm.label(step_label)
            if is_for:
                self._emit_for_inc(target, step_val)
                self._emit_branch_if_cmp(F.IdentExpr(target), end_val,
                                         for_conds[0], for_conds[1],
                                         body_label)
                self._emit_for_restore(target, step_val)
                self._emit_b_to(false_label)
            else:
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
            self._refuse_non_container_operand("a for-in iteration", it)
            self._refuse_slot_container_operand("a for-in iteration", it)
            self._refuse_string_iteration("a for-in iteration", it)
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
                # `LSL #4` on a dict pair blob, `LSL #3` on a list blob: the
                # x86-64 `_emit_for_list` comment is the measurement, and this
                # is the same question on the same terms.  A dict is
                # `[npairs][k0][v0][k1][v1]…`, so one COUNT is one PAIR and the
                # `#3` walk reads `k0, v0, k1` — `for k in d` binding half the
                # values.  The decision is `M.walk_stride`'s (the same rule a
                # membership test asks); `lsl3`/`lsl4` are two hand-encoded
                # instructions, so the stride is compared rather than shifted.
                lsl = (encode_add_xd_xn_xm_lsl4
                       if M.walk_stride(self._is_dict_subscript(it))
                       == M.PAIR_STRIDE
                       else encode_add_xd_xn_xm_lsl3)
                if fi_reg is not None:
                    self.asm.emit(lsl(2, 2, fi_reg))
                else:
                    self._load_var(fi_name, 0)
                    self.asm.emit(lsl(2, 2, 0))
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
            self._emit_blob_load(9, 8 * (i + 1))
            self._emit_for_unpack(child, tag)

    def _emit_for_unpack_star_rest(self, name: str, tag: str) -> None:
        """Build rest blob under `name` from [src_base, n_fixed] on stack.

        Stack layout on entry (stp_pre X6=n_fixed, X9=src): [SP+0]=n_fixed,
        [SP+8]=src_base. Rest = source elements [n_fixed, count). Cap 64;
        overflow → exit(1). Pops both slots."""
        rest_cap = 64
        nbytes = 8 + 8 * rest_cap
        if self._list_cursor + nbytes > self._blob_cap:
            raise CodegenError(M.frame_blob_refusal(
                "a for-star unpacking buffer", self._list_cursor + nbytes,
                self._blob_cap))
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
        self._emit_for_step(target, step, subtract=False)

    def _emit_for_restore(self, target: str, step) -> None:
        """Walk the for-range counter BACK by `step`, on the loop-exit path.

        The same arithmetic as `_emit_for_inc` with the direction flipped, and
        it shares that method's body rather than repeating it: the two must
        accept the same step spellings, because a step the advance can lower and
        the restore cannot would leave the loop's exit value undefined for
        exactly the spellings a program is most likely to use. See
        the loop's exit value is defined for exactly the spellings a program is
        most likely to use."""
        self._emit_for_step(target, step, subtract=True)

    def _emit_for_step(self, target: str, step, subtract: bool) -> None:
        # RMW on the counter: register home edits in place; spill home
        # loads to X11, operates, stores back (X12 holds a spilled step
        # operand when one is needed).
        if target in self._var_regs:
            self._for_inc_in(target, step, subtract)
            return
        self._load_var(target, 11)
        self._for_inc_scratch(step, 11, subtract)
        self._store_var(target, 11)

    def _for_inc_in(self, target: str, step, subtract: bool = False) -> None:
        ireg = self._var_regs[target]
        self._for_inc_body(ireg, step, subtract)

    def _for_inc_body(self, ireg: int, step, subtract: bool = False) -> None:
        # `subtract` flips which instruction each spelling reaches for, and the
        # pairing is by SIGN: advancing by a negative literal is SUB, so
        # restoring by one is ADD, and an ADD of the negated immediate is the
        # only spelling of that arm64 offers (its ADD imm12 is unsigned).
        def op_for(value: int):
            """(immediate encoder, immediate) for `+= value`."""
            add, sub = encode_add_xd_xn_imm, encode_sub_xd_xn_imm
            if subtract:
                return (sub, value) if value >= 0 else (add, -value)
            return (add, value) if value >= 0 else (sub, -value)

        if (isinstance(step, F.UnaryOp) and step.op == "-"
                and isinstance(step.operand, F.IntLiteral)):
            enc, imm = op_for(-step.operand.value)
            self.asm.emit(enc(ireg, ireg, imm))
            return
        if isinstance(step, F.IntLiteral):
            enc, imm = op_for(step.value)
            self.asm.emit(enc(ireg, ireg, imm))
            return
        if isinstance(step, F.UnaryOp) and step.op == "-" \
                and isinstance(step.operand, F.IdentExpr):
            sreg = self._var_reg_or_scratch(step.operand.name, 12)
            self.asm.emit(encode_sub_xd_xn_xm(ireg, ireg, sreg) if subtract
                          else encode_add_xd_xn_xm(ireg, ireg, sreg))
            return
        if isinstance(step, F.IdentExpr):
            sreg = self._var_reg_or_scratch(step.name, 12)
            self.asm.emit(encode_sub_xd_xn_xm(ireg, ireg, sreg) if subtract
                          else encode_add_xd_xn_xm(ireg, ireg, sreg))
            return
        if isinstance(step, F.BinaryOp) and step.op == "+" \
                and isinstance(step.left, F.IdentExpr):
            k = step.right
            if isinstance(k, F.IntLiteral) and k.value >= 0:
                sreg = self._var_reg_or_scratch(step.left.name, 12)
                if subtract:
                    self.asm.emit(encode_sub_xd_xn_xm(ireg, ireg, sreg))
                    self.asm.emit(encode_sub_xd_xn_imm(ireg, ireg, k.value))
                    return
                self.asm.emit(encode_add_xd_xn_xm(ireg, ireg, sreg))
                self.asm.emit(encode_add_xd_xn_imm(ireg, ireg, k.value))
                return
        raise CodegenError("for-loop step must be a literal or a variable")

    def _for_inc_scratch(self, step, dst: int, subtract: bool = False) -> None:
        """Same as _for_inc_body but counter lives in `dst` (already loaded)."""
        self._for_inc_body(dst, step, subtract)

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
        # The RECEIVER of an inlined `__init__`, and the FIELD of one.  Neither
        # is in the source: they are what `model.init_receiver_rewrite` turned
        # `self` into once the body's stores were decided to run at the
        # construction site, because the block that object is being built in is
        # THIS call site's and its address is what `self` meant.  Asked here,
        # at the top of the walk, because both are ARGUMENTS to a lifted
        # `Class_m(<receiver>, …)` call and everything downstream — the argument
        # binder, the spill-and-pop sequence, the callee's frame-holder
        # contract — is then the code a method call has always run.
        if isinstance(expr, (M.CtorReceiver, M.CtorField)):
            self._emit_ctor_receiver(expr)
            return
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
            label = self._intern_string(expr)
            self.asm.emit_adrp_add(0, label)
            return

        if isinstance(expr, F.UnaryOp):
            # `-s` is negation of an address and `~s` is a bit complement of
            # one, and both are refused with `model.string_unary_refusal`,
            # which holds the message and the measurements; asking here is what
            # makes the two architectures refuse the same thing. `not` is not
            # in that table any more — the arm below is why.
            ureason = M.string_unary_refusal(
                expr.op, self._expr_str_kind(expr.operand),
                M.spelled(expr.operand))
            if ureason is not None:
                raise CodegenError(ureason)
            if expr.op == "not":
                # The TRUTHINESS conversion and its negation, so one table
                # answers `not s` and `if s:` and they cannot disagree:
                # `_emit_truthy_word` leaves a word whose ZERONESS is the answer
                # (`strlen(s)` for a string, a blob's count for a container, the
                # word itself for an integer or a frame address) and `eq`
                # against zero is `not`.
                #
                # Before this the operand was evaluated directly and compared
                # with zero, which is FALSE for every string including the
                # empty one — measured on both backends, `1 if not e else 0`
                # printed 0 where Python prints 1, so a program testing a
                # string for emptiness was told the empty string is non-empty.
                # `model.string_unary_refusal` used to hold that message; `-`
                # and `~` still need it, `not` no longer does.
                self._emit_truthy_word(expr.operand)
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
                # …and the same read off a POINTER's `.value()`, which is the
                # other way a frame arrives without a block to copy it into: the
                # address is the pointer's own word, so the field is one load at
                # `[X0, #8*slot]` straight after the receiver is evaluated.  The
                # arm above cannot serve this shape — it reserves and copies,
                # and there is nothing to copy, because the frame belongs to
                # whoever owns the memory the pointer names.
                #
                # `model.pointer_frame_expression`, which is the same decision
                # the holder tables and `_frame_return_status` are built from,
                # so the two spellings of `q.b` cannot disagree about what `q`
                # is.
                st, _why = M.pointer_frame_expression(
                    self._cur_fn, expr.obj, self._structs, self._structs)
                if st is not None:
                    slot = M.struct_frame_slot(st, expr.member)
                    if slot is None:
                        raise CodegenError(
                            f"{M.spelled(expr)} reads {expr.member!r} out of a "
                            f"{st.name} this pointer points at, and that "
                            f"struct's {M.struct_field_summary(st)} has no "
                            f"such field: this path has no way to know which "
                            f"word that is, and reading the wrong one is a "
                            f"wrong answer rather than a failure")
                    self._emit_expr(expr.obj)
                    self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 8 * slot))
                    return
            # A member read through a base this image cannot classify: REFUSED,
            # not answered with the word 0.  This used to evaluate the base for
            # its side effects and `mov x0, #0`, which is a plausible-looking
            # number and not the program's: `(7).foo` and `C.A.value` both
            # printed 0, `g().x` printed 0 where the source says the field's
            # value, and `a[0].foo` printed 0 — none of which is an error
            # anywhere, because CPython raises `AttributeError` for the first
            # two and the other two are real Python that reads a real field.
            # x86-64's arm at this same shape has refused with
            # `model.field_access_refusal` since, so the source built on one
            # architecture and was refused on the other from the same line;
            # these are the shared model's words, so both arches now print the
            # same thing.
            #
            # **The literal case is refused EARLIER**, by
            # `build.refuse_member_reads_through_a_literal_base`, with a message
            # that says what a literal is rather than what this path cannot
            # classify — so this arm is the second line, for a construct that
            # reached the emitter by a route the build pass does not model.
            #
            # The base is EMITTED first, for the reason the store arm above
            # gives and `model.member_access_refusal` argues: a base that is
            # itself unanswerable refuses with ITS message, which is the more
            # specific of the two (`p.value().b` is a pointer-width question,
            # not a field-layout one).
            self._emit_expr(M.member_base_node(expr))
            raise CodegenError(M.member_access_refusal(
                expr, self.func_name, self._frame_holders))

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

    def _intern_string(self, s) -> str:
        """Return a stable data label for `s`, emitting bytes on first use.

        `s` is a `StringLiteral` node or a plain string. The node form is what
        carries `is_raw`, which is why it is accepted rather than only
        `node.value`: `r"a\\nb"` and `"a\\nb"` are the same four characters
        once `_strip_string_prefix_and_quotes` has done its work, so a decoder
        handed only the body cannot tell them apart and would decode the raw one
        as well. A plain string is already-decoded text — a fold, a manifest
        value, `GlobalDataImage.string_cells`, a comptime read — and is taken at
        face value.

        THE decode point for a string literal on this backend, and it is here
        rather than at the call sites because every byte of every string on this
        path goes through this one function — and because this path is the one
        engine in the repository that does NOT hand the literal's text to a C
        compiler, which is where `fire_compiler.py` leaves escapes decoded-by-
        proxy. `fire_compiler.decoded_literal` is the tree's one reader of that
        question (the interpreter and the x86-64 backend delegate to the same
        one); without it `len("a\\nb")` was 4 on a formal image and the printed
        bytes carried a literal backslash, on both architectures, while
        `fire.py run` and `fire.py build` both printed a real newline. See
        `fire_compiler.decode_c_escapes` and, for the measurement,
        `FORMAL_string_literal_escape_is_not_decoded` — deleted, since
        that is fixed.

        Decoding BEFORE the intern lookup is what makes interning by content
        right: two literals differing only in escape spelling (`"\\t"` and a
        spelled tab) now get the same key, which is what `==` on a string
        address already assumes.
        """
        s = F.decoded_literal(s)
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
            declared_kind=self._declared_kind_for(name),
            declared_is_dict=self._declared_is_dict_for(name),
ctor_field_value=self._ctor_field_value_for(name),
            callee_is_dict=lambda callee: self._callee_is_dict(
                callee, stack | {name}),
            dict_names=DICT_TYPE_NAMES,
            param_kind=self._param_kinds.for_function(name))
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
                        owner, TYPE_NAMES, STRING_TYPE_NAMES, structs,
                        DTYPE_TYPE_NAMES)
                cands = frame_candidates.get(name)
                if cands:
                    return M.one_word_receiver_kind(
                        cands[0], TYPE_NAMES, STRING_TYPE_NAMES, structs,
                        DTYPE_TYPE_NAMES)
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
                    structs, DTYPE_TYPE_NAMES)
            if isinstance(expr, F.CallExpr) and isinstance(expr.func,
                                                            F.IdentExpr):
                return M.one_word_receiver_kind(
                    structs.get(expr.func.name), TYPE_NAMES,
                    STRING_TYPE_NAMES, structs, DTYPE_TYPE_NAMES)
            return None

        return kind_of_slot

    def _declared_is_dict_for(self, fn_name):
        """`declared_is_dict` bound to the function `fn_name`, for `ValueKinds`.

        The dict-ness twin of `_declared_kind_for`, over the same three shapes
        and the same `model.method_owner_struct` lookup, because the question
        "which struct's field is `self.seen`" must have one answer in this
        emitter: `self` is the receiver of `fn_name`'s method, and the frame-slot
        tables have already settled which candidates a local holder has.

        `None` — "this path cannot say" — is the answer for every other case,
        and it is what leaves the emitter's dict dispatch exactly where it was:
        an unannotated field, a field two candidates disagree about, and a base
        that is not a frame slot all read None, and `is_dict_value`'s binding
        evidence still wins where both exist."""
        owner = M.method_owner_struct(self._structs, fn_name)
        frame_candidates = dict(self._frame_candidates)
        structs = self._structs

        def slot_candidates(expr):
            """The structs whose FIELD `expr.member` is, or None."""
            if not isinstance(expr, F.MemberExpr) \
                    or not isinstance(expr.obj, F.IdentExpr):
                return None
            root = expr.obj.name
            if owner is not None and root in M.struct_receivers(owner):
                return [owner]
            return frame_candidates.get(root)

        return lambda expr: M.frame_slot_field_is_dict(
            slot_candidates(expr), getattr(expr, "member", None),
            DICT_TYPE_NAMES, structs)

    def _ctor_field_value_for(self, fn_name):
        """`ctor_field_value` bound to `fn_name`, for `ValueKinds`.

        The hook that answers "what did the construction put in this field",
        and the whole of it is `model.struct_ctor_field_value` asked with THIS
        UNIT'S struct table. That table is the only reason a hook exists at all:
        `ValueKinds` reads one function's source and has no way to know that
        `Point` is a struct, what its `__init__` stores, or which of its methods
        write a field — and a backend that asked those questions itself would be
        a second implementation of `init_body_stores`, which is the one function
        the emitters build a construction from.

        Three gates, and each is a refusal rather than a guess:

          * the callee must be a struct THIS unit declares. A struct of another
            module has no `__init__` here to read, and a name that is a
            function rather than a type is not a construction at all.
          * it must be a FRAMED struct (more than one field). A one-word
            struct's receiver IS its field, which `_declared_kind_for` answers
            from the declaration, and this hook must not be a second opinion
            about the same word.
          * no OTHER method may write the field
            (`struct_field_written_outside_init`). The kind is about the slot,
            and a setter that ran between the construction and the read makes
            the constructor's argument a statement about the past.

        `fn_name` is accepted and unused, deliberately: the two `ValueKinds`
        hooks have the same signature because both are per-FUNCTION questions,
        and a hook that ignored the function it was asked about would be the
        kind of thing that looks right until two functions in one module
        disagree.
        """
        structs = self._structs

        def ctor_field_value(struct_name, call, field):
            st = structs.get(struct_name)
            if st is None or not M.struct_is_framed(st):
                return None
            if M.struct_field_written_outside_init(st, field):
                return None
            return M.struct_ctor_field_value(st, call, field, structs)

        return ctor_field_value

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
        ann = M.frame_slot_declared_annotation(cands, expr.member,
                                                self._structs)
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
        ann = M.frame_slot_declared_annotation(cands, only, self._structs)
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
                                          self._structs,
                                          dtype_names=DTYPE_TYPE_NAMES))

    def _aliased_export(self, name: str):
        """The manifest export a bare callee reaches THROUGH an import alias.

        The forwarded table is passed because a package `__init__` is a NAMESPACE
        library with an empty export table, so the names it publishes are all in
        `forwarded` — which is what makes `from pkg import base as aliased`
        resolvable, and why this is asked of the same three tables in the same
        order as the DOTTED spelling (`model.dylib_aliased_export`).
        """
        return M.dylib_aliased_export(self._dylib_by_name,
                                      self._dylib_by_module, name,
                                      self._import_aliases,
                                      self._dylib_forwarded)

    def _extern_symbol(self, name: str) -> str:
        """The boundary symbol an unbound callee `name` is emitted against.

        The DECISION and the words are `model.dylib_extern_symbol`'s, shared
        with the x86-64 emitter: three spellings (a bare name from the flat
        map, a bare name bound by an import alias from the module the alias
        came from, and a dotted name from the library built for that module or
        from what it forwards), and a name that cannot be bound is refused by
        name here rather than emitted as a BL against a symbol nothing
        defines. This used to be a second copy of that rule, in two backends,
        which is two places for one language implementation to disagree about
        what a module call binds.
        """
        return M.dylib_extern_symbol(name, self._dylib_syms,
                                     self._dylib_by_name,
                                     self._dylib_by_module,
                                     self._dylib_forwarded,
                                     self._import_aliases)

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
            the same string, which is how a cross-image `-> str` classifies.
            An IMPORT ALIAS is that second kind under its local spelling, so
            it is asked about through `_aliased_export` — `dylib_export_lookup`
            reads the flat `{defining name: entry}` table and a call site
            spells the local name, which is exactly the lookup that misses;
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
        if entry is None and "." not in name:
            entry = self._aliased_export(name)
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
            # The callee's OWN DECLARATION first, then the signature: one
            # word of C cannot say `-> List[Int]` from `-> Int`, and
            # `model.imported_callee_kind` is the one place that decides which
            # of the two answers a container return type gets. A library
            # shipped without its sources has no declaration, and the same
            # call then answers exactly what it answered before.
            return M.imported_callee_kind(
                M.dylib_callee_export(self._dylib_by_name,
                                      self._dylib_by_module,
                                      self._dylib_forwarded,
                                      self._import_aliases, name),
                self._extern_decl_for(name),
                int_names=TYPE_NAMES, string_names=STRING_TYPE_NAMES)
        vk = self._vkinds_for(name, fn, stack)
        ann = getattr(fn, "return_type", None)
        if ann in STRING_TYPE_NAMES:
            return M.STR_KIND
        if ann in TYPE_NAMES:
            return M.INT_KIND
        return vk.return_kind

    def _callee_is_dict(self, name, stack):
        """Whether a call to this unit's function `name` produces a DICT, or
        None when the source does not say.

        `_callee_kind`'s evidence read on the other axis. That one answers what
        KIND a call result is, and on this path a dict and a list are one word
        pointing at a blob with the same 8-byte count header — so `return_kind`
        says "a blob" for both and `d["a"]` on the result of either took the
        sequence subscript. The two questions need two pieces of evidence, and
        this one is assembled from the same two: the callee's DECLARED return
        type first (`-> Dict[String, Int]` says it outright), then its RETURN
        STATEMENTS by unanimous agreement (`def mk(): … return d` states a dict
        without annotating anything).

        The stack and the memo are `_callee_kind`'s, deliberately: a
        `def a(): return b()` / `def b(): return a()` cycle is a word here and
        must be a word here too.
        """
        fn = self._functions.get(name)
        if fn is None or name in stack or len(stack) >= 3:
            return None
        if M.declared_type_is_dict(getattr(fn, "return_type", None),
                                   DICT_TYPE_NAMES):
            return True
        return self._vkinds_for(name, fn, stack).return_is_dict

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
            # `list_literal_reserved_slots`, not `len(lit.elements)`: a
            # literal with a `*` operand builds its blob by appending and
            # occupies the cap it reserved, so counting the `*` as ONE
            # element made `xs = [*a]; xs.append(3)` overflow the guard
            # with `a` of length 2. One rule, read by both backends.
            want = min(M.list_literal_reserved_slots(lit)
                       for lit in literals) + count
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
        # `M.is_dict_expr` is the shared spelling of this rule (a dict
        # literal OR a dict comprehension); it used to be written out here
        # and in x86_64_codegen separately, and x86-64's copy was missing
        # the comprehension half.
        if M.is_dict_expr(value):
            self._dict_vars.add(name)
            self._string_vars.discard(name)
        elif isinstance(value, F.CallExpr) and self._callee_is_dict(
                M.subscript_callee_name(value) or M._flat_callee(value),
                frozenset()):
            # `d = mk()` where `mk` returns a dict. The binding has no literal
            # in it, so this arm used to fall through to the clearing `else`
            # below and the subscript that followed took the SEQUENCE path:
            # `d["a"]` was emitted as a load at the key's interned ADDRESS, and
            # the image exited 1 from a build that was green. Measured on both
            # architectures, for an annotated callee and for an unannotated one
            # whose `return` states a dict literal. See
            # “FORMAL_container_from_a_call_has_no_shape_so_a_string_subscript_faults”
            # (deleted with the fix). The same shape as the `M.is_dict_expr`
            # arm above, so it clears the other two marks the same way.
            self._dict_vars.add(name)
            self._string_vars.discard(name)
            self._blob_vars.discard(name)
        elif self._is_container_expr(value):
            # A list/set/tuple literal, a comprehension, a SLICE and a `+`/`|`
            # of blobs all bind a blob — `var ys = xs[1:3]` is the case that
            # matters most, because a slice-bound name is the one a later `+`
            # has to recognise and it is not a literal anywhere.
            self._blob_vars.add(name)
            self._string_vars.discard(name)
            self._dict_vars.discard(name)
        elif isinstance(value, F.StringLiteral):
            self._string_vars.add(name)
            self._dict_vars.discard(name)
            self._blob_vars.discard(name)
        elif isinstance(value, F.IdentExpr):
            if value.name in self._dict_vars:
                self._dict_vars.add(name)
                self._string_vars.discard(name)
                self._blob_vars.discard(name)
            elif value.name in self._blob_vars:
                self._blob_vars.add(name)          # an alias keeps it: `b = a`
                self._string_vars.discard(name)
                self._dict_vars.discard(name)
            elif self._expr_str_kind(value) == M.STR_KIND:
                # `value.name in self._string_vars` OR a `comptime` binding
                # whose folded value is the text: `var t = OS` binds exactly the
                # `char *` `t = s` binds, and asking `_expr_str_kind` rather
                # than re-deriving the test here is what keeps the two paths
                # from disagreeing about the same read.
                self._string_vars.add(name)
                self._dict_vars.discard(name)
                self._blob_vars.discard(name)
            else:
                self._string_vars.discard(name)
                self._dict_vars.discard(name)
                self._blob_vars.discard(name)
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
            self._blob_vars.discard(name)
        else:
            self._string_vars.discard(name)
            self._dict_vars.discard(name)
            self._blob_vars.discard(name)

    def _is_dict_subscript(self, obj) -> bool:
        """True when `obj` is known to hold a dict pair-blob pointer.

        Three sources, and the ORDER is the same precedence `_expr_str_kind`
        uses for the string axis: the flow-sensitive `_dict_vars` first, since
        it is strictly better informed than the whole-function map, and
        `ValueKinds` after it for the shapes no BINDING statement can describe.

        * `M.is_dict_expr` and not `isinstance(obj, F.DictExpr)`: a dict
          COMPREHENSION is a `Comprehension` with kind='dict', and asking
          only about literals sent `d[k]` down the index path. See
          `M.is_dict_expr`.
        * `_dict_vars` — what the emission of this very function has bound.
        * `ValueKinds.is_dict_value` — the base with NO binding statement at
          all, which is a `Dict[String, Int]` PARAMETER. Measured: `def show(d:
          Dict[String, Int]): d["a"]` exited 1 with nothing printed on both
          architectures, because a parameter is bound by the signature and
          `_note_binding` never sees it. See
          `“FORMAL_container_from_a_call_has_no_shape_so_a_string_subscript_faults”`.
        """
        if isinstance(obj, F.IdentExpr):
            if obj.name in self._dict_vars:
                return True
        if isinstance(obj, F.MemberExpr):
            key = _member_slot_key(obj)
            if key is not None and key in self._dict_vars:
                return True
        if M.is_dict_expr(obj):
            return True
        return self._vkinds.is_dict_value(obj) is True

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
        “`s[i]` on a `String`-annotated PARAMETER reads the blob's count field”.
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
        so nested containers sit above it. Star-unpack not applicable.

        **The blob is reserved for `pairs_written + store_sites`, and the
        count word holds only `pairs_written`.**  A dict LITERAL says which
        pairs were written; it said nothing about how many more there is room
        for, which is why `d["new"] = v` had nowhere to write and the miss arm
        stopped the program (`model.dict_store_capacity`, the same reservation
        `list.append` gets from `_scan_list_caps`, and the same bargain: one
        store SITE per reservation, every EXECUTION of it counted, and a store
        in a loop stops loudly rather than writing past the blob)."""
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
        n = M.dict_literal_static_pairs(expr)
        assert n == len(static_pairs), (
            "dict_literal_static_pairs and _emit_dict disagree about what a "
            "literal writes: the reservation the store path is checked against "
            "is computed from the former and the blob from the latter")
        reserved = self._dict_caps.get(id(expr), n)
        size = 8 * (1 + 2 * reserved)
        if self._list_cursor + size > self._blob_cap:
            raise CodegenError(M.frame_blob_refusal(
                "a dict literal", self._list_cursor + size, self._blob_cap))
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
            self._emit_string_addr(reg, self._intern_string(e))
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

    def _emit_dict_lookup_addr(self, e: F.SubscriptExpr,
                                 store: bool = False) -> None:
        """X0 = &dict[key] value slot. A missing key on a READ stops the
        program; on a STORE it is CPython's INSERT.

        Pair-blob layout: [count][k0][v0]…; value i is at base+16+16*i.
        Key compare is raw 64-bit equality — valid for interned string
        literals and integer keys (the formal dict surface) — except for a
        static container key, which is compared element-wise (see
        `_static_key_needle`): a tuple key's blob pointer is not a value.

        **`store` is what separates the two miss answers, and it is why the
        miss arm is three arms and not one.**  `d[k] = v` INSERTS in CPython,
        and before this it stopped the program having printed nothing, on both
        backends, with the diagnostic naming neither the key nor the table. The
        insert needs three facts, and only one of them was missing: the SCAN is
        the same scan, and the pair address is arithmetic on the base and the
        count, so what is new is the ROOM — `model.dict_store_capacity`
        reserves `pairs + store sites` at the literal, and the arm below is
        that capacity checked, a pair written at the count, and the count
        bumped. The two arms that cannot insert say so in a sentence instead of
        exiting silently: no capacity (the blob was built by another function,
        so this build never saw its pairs) and a static container key (compared
        element-wise, never materialised, so there is no key word to write).

        `self._emit_subscript_addr` passes `store` down from the ONE caller
        that stores, so the read, the store and the augmented assignment cannot
        be told apart wrongly — and the augmented assignment
        (`d[k] += v`) deliberately keeps the READ arm, because it raises
        `KeyError` on a missing key and exiting is the right answer for it.

        Stack on entry to the scan (two STP pushes, or one when the key is
        compared element-wise and never needs a slot):
          [SP+0]  key (lookup), [SP+8] XZR
          [SP+16] base,        [SP+24] junk
        On the store arm the CALLER's spilled value is above those two pushes —
        [SP+32] — which is where the insert reads it from. Hit path stashes the
        value address in X4 across the pops."""
        self._sub_counter += 1
        sid = self._sub_counter
        fn = self.func_name
        miss_label = f"{fn}_dlk{sid}_miss"
        hit_label = f"{fn}_dlk{sid}_hit"
        end_label = f"{fn}_dlk{sid}_end"
        loop_label = f"{fn}_dlk{sid}_loop"
        # The room this store may use, and None for the two arms that cannot
        # insert. Decided BEFORE the scan because the miss arm's shape depends
        # on it, and read from the NAME table for the reason
        # `_emit_list_append` reads its capacity from the name table.
        cap = None
        why_no_room = None
        if store:
            base_name = e.obj.name if isinstance(e.obj, F.IdentExpr) else None
            if M.static_key_elements(e.index) is not None:
                why_no_room = M.dict_store_no_room_message(
                    base_name or "<expr>", M.spelled(e.index))
            else:
                cap = self._dict_caps_by_name.get(base_name)
                if cap is None:
                    why_no_room = M.dict_store_other_blob_message(
                        base_name or "<expr>", M.spelled(e.index))

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
        if store:
            # A dict STORE puts the value here, out of the caller's spill, and
            # leaves NOTHING to store through afterwards: `_emit_subscript_addr`
            # is a "where does this live" question, and on a miss there is no
            # where — the store IS the insert. Handing a value slot back to a
            # caller that then stores through it is how the miss arm's `None`
            # became a write to address 0.
            self.asm.emit(encode_ldr_xt_xn_imm(7, 31, base_off + 16))
            self.asm.emit(encode_str_xt_xn_imm(7, 4, 0))
            _pop_scan()
            self.asm.emit(encode_mov_zr_xn(0, 0))    # the assignment's None
        else:
            _pop_scan()
            self.asm.emit(encode_mov_zr_xn(0, 4))
        self._emit_b_to(end_label)

        self.asm.label(miss_label)
        if cap is None:
            _pop_scan()
            if why_no_room is not None:
                self._emit_overflow_diagnostic(why_no_room)
            self.asm.emit(encode_movz_xd_imm(0, 1))
            self.asm.emit(encode_movz_xd_imm(16, 1))
            self.asm.emit(encode_svc(0x80))
        else:
            # THE INSERT. `X1` = base and `X2` = count come off the scan's own
            # pushes, the spilled VALUE is at [SP+32] (see the stack note), and
            # the pair lands at `base + 8 + 16*count` — the same address the hit
            # arm computes, one past the end.
            oob_label = f"{fn}_dlk{sid}_oob"
            self.asm.emit(encode_ldr_xt_xn_imm(1, 31, base_off))
            self.asm.emit(encode_ldr_xt_xn_imm(2, 1, 0))     # X2 = count
            self._emit_mov_imm("X3", cap)
            self.asm.emit(encode_cmp_xn_xm(2, 3))
            self.asm.emit(encode_cset_xd_cond(4, "cs"))      # count >= cap
            self.asm.emit(encode_cbnz_xn(0, 4))
            self.asm.emit_label_rel(oob_label, here_offset=-4)
            self.asm.emit(encode_add_xd_xn_imm(5, 1, 8))
            self.asm.emit(encode_add_xd_xn_xm_lsl4(5, 5, 2))  # X5 = key slot
            self.asm.emit(encode_ldr_xt_xn_imm(6, 31, 0))    # X6 = key
            self.asm.emit(encode_str_xt_xn_imm(6, 5, 0))
            self.asm.emit(encode_ldr_xt_xn_imm(7, 31, base_off + 16))  # value
            self.asm.emit(encode_str_xt_xn_imm(7, 5, 8))
            self.asm.emit(encode_add_xd_xn_imm(2, 2, 1))
            self.asm.emit(encode_str_xt_xn_imm(2, 1, 0))     # count = n + 1
            _pop_scan()
            self.asm.emit(encode_mov_zr_xn(0, 0))    # the assignment's None
            self._emit_b_to(end_label)
            self.asm.label(oob_label)
            _pop_scan()
            self._emit_overflow_diagnostic(
                M.dict_store_overflow_message(
                    e.obj.name if isinstance(e.obj, F.IdentExpr) else "<expr>",
                    cap))
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

    def _refuse_string_iteration(self, op: str, obj) -> None:
        """Refuse to ITERATE a `char *` as a container.

        The sibling of `_refuse_frame_container_operand`, and the same
        failure: the blob walk reads offset 0 of the operand and calls it a
        COUNT, and a string's first eight bytes are text. `M.
        string_iteration_refusal` owns the wording and the measurements (see
        there for what both architectures returned before this), and both
        backends ask it through their own `_is_string_subscript`, which is
        the one place that knows whether an expression holds a `char *`.
        """
        if self._is_string_subscript(obj):
            raise CodegenError(M.string_iteration_refusal(
                op, self.func_name or "<module>"))

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

    def _refuse_frame_order_operand(self, op: str, operand) -> None:
        """Raise if `operand` is a bare name this function holds as a FRAME.

        The ORDERING sibling of `_refuse_frame_container_operand`, and asked
        from the same table for the same reason: `x < y` on two multi-field
        structs reached the flag-setting compare of two ADDRESSES, so which way
        it branched was decided by where the allocator put the two objects —
        measured on both architectures, `lt=1 gt=0 le=1 ge=0` for two objects
        holding EQUAL field values. `model.frame_order_operand_refusal` is the
        shared text, so x86-64 cannot describe the same construct differently,
        and both backends ask it at BOTH comparison sites (`_emit_binop` for a
        value and `_emit_branch_unless_cmp` for a condition) — the choke-point
        argument `bugs/FORMAL_string_value_model.md` makes for `if s < t:`
        bypassing `_emit_binop`, which is exactly how a string comparison came
        to be a diagnostic in one context and a branch in the other.
        """
        if (op not in M._FRAME_ORDER_OPS
                or not isinstance(operand, F.IdentExpr)
                or operand.name not in self._frame_holders):
            return
        cands = self._frame_candidates.get(operand.name) or ()
        reason = M.frame_order_operand_refusal(op, operand,
                                              [st.name for st in cands])
        if reason is not None:
            raise CodegenError(reason)

    def _refuse_non_container_operand(self, op: str, obj) -> None:
        """Raise if `obj` is a plain WORD this function bound to an integer.

        The third arm of the container family, and the one that had no arm at
        all: `frame_container_operand_refusal` fires for a FRAME ADDRESS and
        the string paths fire for a `char *`, and `a = 5` is neither, so the
        blob walk read a count out of the integer and computed an element
        address of `5 + 8`. Measured on BOTH architectures, `a[0] = 1` builds,
        links and dies of SIGSEGV at run time with the build green. See
        `model.non_container_element_refusal` for the whole of it.

        BARE NAME ONLY, for the same reason `_refuse_frame_container_operand`
        is: `h.xs[i]` on a field declared `List[Int]` is what that declaration
        is FOR, and the frame-holder table is about addresses rather than
        fields.

        The kind is read from `own_shape_kind` and NOT from `_expr_str_kind`,
        and that is the whole of the narrowing: `INT_KIND` is this model's
        DEFAULT for a word, so a parameter (`def at(xs): return xs[0]`), a call
        result (`ys = h.get()`) and a loop variable (`for row in rows:`) all
        carry it while being containers, and reading it as a claim refuses
        three correct programs — `own_shape_kind`'s docstring has the measured
        table. What it answers is "did a statement of THIS function say so",
        which is the difference between `a = 5` and every one of them.
        """
        if not isinstance(obj, F.IdentExpr):
            return
        if self._vkinds.own_shape_kind(obj.name) != M.INT_KIND:
            return
        raise CodegenError(M.non_container_element_refusal(
            op, M.spelled(obj), self.func_name or "<module>"))

    def _refuse_slot_container_operand(self, op: str, obj) -> None:
        """Raise if `obj` is a struct FIELD whose kind is an integer or a tag.

        **The FIELD sibling of the two above, and the one they are both blind
        to by design.** `_refuse_frame_container_operand` and
        `_refuse_non_container_operand` are BARE-NAME-only, each saying why:
        `h.x` is a 64-bit field and reading it as a blob is what a declared
        `List` field is FOR. That is right about a field whose declared type
        says nothing and it is how `s.n[0]` — `s.n` declared `Int` — reached
        the blob walk on one architecture and a SIGSEGV on the other.
        `model.slot_container_operand_refusal` has the measurement, the
        three-row table and the corpus census that says the gate is the KIND
        and that `None` stays out of it.

        Asked at the same four choke points as its two siblings, so a read, a
        store, an augmented assignment, a slice, a membership test and a for-in
        iteration all get this answer and the two architectures cannot come to
        disagree about which bases qualify.
        """
        if not isinstance(obj, F.MemberExpr):
            return
        why = M.slot_container_operand_refusal(
            op, self._expr_str_kind(obj), M.spelled(obj),
            self.func_name or "<module>")
        if why is not None:
            raise CodegenError(why)

    def _emit_subscript_addr(self, e: F.SubscriptExpr,
                             for_store: bool = False) -> None:
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
        address. Both now say no.

        `for_store` is the ONE thing that separates the three, because the
        dict lookup's answer does depend on it: `d[k] = v` INSERTS on a
        miss, while `d[k]` and `d[k] += v` do not (`_emit_dict_lookup_addr`
        has the arms). It is a parameter rather than a flag on the emitter
        because the augmented assignment must NOT inherit it — `+=` raises
        `KeyError` on a missing key, so stopping is the right answer there —
        and a flag the store caller sets and every other caller has to
        remember to clear is a flag that survives an exception path."""
        self._refuse_frame_container_operand("a subscript", e.obj)
        self._refuse_non_container_operand("a subscript", e.obj)
        self._refuse_slot_container_operand("a subscript", e.obj)
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
        why = M.multi_index_refusal_for(e, self._is_dict_subscript(e.obj),
                                        self._functions, self._structs)
        if why is not None:
            raise CodegenError(why)
        # A TYPE index, before the base's own shape is asked: the base does not
        # decide this. `xs[bool]` took the blob's bounds check against a 63-bit
        # tag and exited 1 with nothing printed, and `s[bool]` added a tag to a
        # `char *`. One call here covers the read, the store and the augmented
        # assignment, and it is asked of the KIND rather than of the node so a
        # local bound to a type is refused as well as the bare name.
        why = M.type_index_refusal(self._expr_str_kind(e.index),
                                   M.spelled(e.index))
        if why is not None:
            raise CodegenError(why)
        if self._is_dict_key_subscript(e):
            self._emit_dict_lookup_addr(e, store=for_store)
            return
        # A string index against a base whose shape nothing states: the one
        # spelling of this subscript that neither the dict path nor the byte
        # path can answer, and the residue after
        # `“FORMAL_container_from_a_call_has_no_shape_so_a_string_subscript_faults”`'s
        # other three (a module slot, a call result and a `Dict[…]`-annotated
        # parameter all have evidence now). Asked here — after the dict
        # dispatch and before the blob fallback — because those two are the
        # readings that DO exist and this is the pair the source does not
        # choose between.
        why = M.unstated_base_string_index_refusal(
            False, self._expr_str_kind(e.obj), self._expr_str_kind(e.index),
            M.spelled(e.obj), M.spelled(e.index))
        if why is not None:
            raise CodegenError(why)
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
            # FORMAL_subscript_of_a_pointer_reads_a_blob_count and
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
        # A COMPREHENSION is in this list for the same reason the container
        # literals are: it produces a blob of exactly the shape the walk below
        # reads (`[count][e0…]`, reserved before any generator runs). Without
        # it, `[i * 2 for i in [1, 2, 3]][2]` was REFUSED here and computed on
        # x86-64 — the two backends disagreeing about one program, which is
        # the one thing this pair may not do. A string base is not here
        # because it never reaches this gate: `_is_string_subscript` above
        # takes it as a byte load.
        obj_ok = type(e.obj) in (F.IdentExpr, F.CallExpr, F.ListExpr,
                                 F.TupleExpr, F.Comprehension, F.MemberExpr,
                                 F.SubscriptExpr)
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
        if self._is_dict_key_subscript(target):
            # The one subscript whose store is not "compute an address and
            # store through it": `d[k] = v` INSERTS on a miss, so there is no
            # address to return and the value is written inside the lookup's own
            # arms (`_emit_dict_lookup_addr`). Everything before this — the
            # multi-index, type-index and string-index refusals — still runs,
            # because it goes through `_emit_subscript_addr` like every other
            # subscript.
            self._emit_subscript_addr(target, for_store=True)
            self.asm.emit(encode_ldp_sp_post(reg, 31))   # pop the value
            self.asm.emit(encode_mov_zr_xn(reg, 0))      # the assignment's None
            return
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
        # A `char *` base has no element type to add a number to, and the store
        # at the end of this routine writes THROUGH the base — so over a string
        # literal, which lives in a read-only __TEXT page, `s[0] += 1` built an
        # image that died on SIGBUS on the assignment. Measured on this tree
        # before the check existed. The plain-name path above already asked
        # `model.string_binary_refusal` for exactly this question and this one
        # did not, which is the same "a second emitter that never went through
        # the check" shape `s += t` was; x86-64's twin asks it as well, so the
        # two architectures now refuse the same source for the same stated
        # reason instead of one crashing and one declining.
        reason = M.string_binary_refusal(
            op, self._expr_str_kind(target),
            self._expr_str_kind(stmt.value), spelled_op=stmt.op)
        if reason is not None:
            raise CodegenError(reason)
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

        Three sources, and `_string_vars` WINS where they disagree. It is
        flow-sensitive and tracks what the emission of this very function has
        bound so far, so it is strictly better informed than the whole-function
        `ValueKinds`; the whole-function map is what covers the shapes
        `_note_binding` does not see (a parameter's annotation, a function's
        return type, a subscript's element kind). A `comptime` binding is the
        third source and it is neither: `ValueKinds` never scans a
        `comptime NAME = …` statement, so a folded binding reached this as an
        unclassified read — and a STRING one, which `_emit_comptime_read`
        materializes as the interned literal, was then emitted as an INTEGER,
        differently on each architecture. The binding is a compile-time
        constant the emission already holds, so what it holds is known rather
        than guessed; `model.comptime_val_kind` is the one reader of it.

        Named for what it answers rather than for the first caller: `print`,
        the method-receiver guard and `_note_binding` all need the same
        question, and three copies of this precedence rule is three chances for
        one of them to decide that a `char *` is a number.

        `_compr_scopes` is consulted LAST and only for a bare name, and it is
        the answer rather than a fallback while it is in force: a comprehension
        has its own scope in Python 3, so `var x = 5` beside `[x for x in
        ["a", "b"]]` does not make the two bindings disagree, and a site inside
        the comprehension must see the loop variable and not the outer `x`.
        Measured on both architectures, `[x for x in ["p", "", "q"] if x]`
        returned 3 elements where CPython returns 2: the comprehension's `x`
        was in no kind map at all, so `if x:` fell to `TRUTHY_NONZERO` and
        tested the ADDRESS of the empty string for zeroness."""
        if isinstance(expr, F.MemberExpr):
            key = _member_slot_key(expr)
            if key is not None and key in self._string_vars:
                return M.STR_KIND
        elif isinstance(expr, F.IdentExpr):
            if expr.name in self._string_vars:
                return M.STR_KIND
            bound = M.comptime_val_kind(self._comptime_vals, expr.name)
            if bound is not None:
                return bound
        return self._vkinds.kind_of(expr, scopes=self._compr_scopes)

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
                frags.append(M.print_literal(a))
                continue
            kind = self._expr_str_kind(a)
            if kind == M.STR_KIND:
                frags.append("%s")
            elif M.is_number_kind(kind):
                # `is_number_kind` and not `== INT_KIND`: a type TAG is a word,
                # so `print(t)` for `t = bool` prints the tag, which is what it
                # printed before `TYPE_KIND` existed (`t` was then an `int` by
                # `_value_kind`'s default). Asking `== INT_KIND` here would make
                # the construct's own positive case a refusal.
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

    def _printf_arg_is_text(self, arg):
        """True / evidence / None: does this `printf` vararg hold text.

        Delegation, and nothing else: `model.printf_arg_text_evidence` is the
        decision, so x86-64's copy of this method cannot come to disagree with
        this one about what a format string means. What is passed in is the
        three facts only an emitter has — this function's `ValueKinds`, the
        flow-sensitive `_expr_str_kind`, and the one-field candidates
        `formal/build.py` published for the function (`None` for a name the FRAME
        table owns, which is the precedence `_seed_one_word_bindings` states:
        a name in both tables is a name with two layouts and the frame one is
        the truth).
        """
        return M.printf_arg_text_evidence(
            arg, self._vkinds,
            is_text=lambda e: M.string_operand_is_string(self._expr_str_kind(e)),
            one_word_text=lambda name: (
                None if name.name in self._frame_holders else
                M.one_word_value_text_evidence(
                    self._one_word_candidates.get(name.name),
                    TYPE_NAMES, STRING_TYPE_NAMES, self._structs)))

    def _refuse_unusable_printf_format(self, name, e: F.CallExpr) -> None:
        """Raise when `e`'s FORMAT cannot be used, for either of the two reasons.

        A no-op for every callee the model's set does not name, and for a call
        whose format is not a LITERAL: a format in a variable cannot be scanned.
        Both are the model's decision rather than this one's — it is asked with
        the callee name, the format and the arguments and answers for itself, so
        x86-64's copy of this method is two lines of delegation and the two
        cannot come apart.

        The two reasons are a `%s` conversion handed something that is not text,
        and a conversion with no argument behind it; which one is reported when
        both could apply is `printf_format_refusal`'s decision too.

        **The format text handed over is the DECODED one**, and that is not a
        tidiness: `fire_compiler.decoded_literal` is what `_intern_string` runs
        on, so it is what the format bytes will be at the call — and a `%` can
        ARRIVE from an escape. `printf("\\x25s", 5)` is `printf("%s", 5)` at run
        time, and handing this check the raw body `\\x25s` finds no conversion in
        it at all. The pre-existing `%s` refusal had that hole; the decode
        closes it, and it is the same decode-then-transform order
        `model.print_literal` states its own reason for.
        """
        args = list(e.args or [])
        idx = M.printf_format_arg_index(name)
        fmt = args[idx] if idx is not None and idx < len(args) else None
        reason = M.printf_format_refusal(
            name, F.decoded_literal(fmt) if isinstance(fmt, F.StringLiteral)
            else None,
            args[idx + 1:] if idx is not None else args[1:],
            self._printf_arg_is_text)
        if reason is not None:
            raise CodegenError(reason)

    def _print_kwargs(self, e: F.CallExpr):
        """`print`'s `sep=` / `end=` / `file=` / `flush=`, as (sep, end, flush).

        **Two lines of delegation**, and `M.print_kwargs`'s docstring is where
        the decision and its reasons are: `flush=` is answered there (the
        largest `codegen-refused` family in this repository's own source, per
        `bugs/FORMAL_proof_coverage_census_2026-10-03.md` §0.2), and the rule
        that the keyword is dispatched BEFORE its value is inspected is what
        stops a bool from being refused with a sentence about `sep`."""
        return M.print_kwargs(e, "arm64")

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
        reads no varargs and the register state afterwards is irrelevant.

        **`flush=True` IS A REAL `fflush` AND NOT A DROPPED KEYWORD**, after the
        `printf`: the one thing a formal image cannot see by not flushing is a
        program whose output has not reached the pipe yet, which is a missing
        line rather than a wrong one. `fflush(NULL)` is the C library's own
        "every stream"; there is exactly one stream this model writes, which is
        the fact `print(file=…)`'s refusal is stated on (`M.print_kwargs`)."""
        sep, end, flush = self._print_kwargs(e)
        frags, operands = self._print_call(list(e.args))
        fmt = M.print_format(frags, sep, end)
        self._emit_call(F.CallExpr(func=F.IdentExpr(name="printf"),
                                   args=[F.StringLiteral(fmt)] + operands))
        if flush:
            self._emit_call(F.CallExpr(func=F.IdentExpr(name="fflush"),
                                       args=[F.IntLiteral(0)]))

    def _emit_debug_assert(self, e: F.CallExpr) -> None:
        """`debug_assert(cond, *messages)` — evaluate `cond`, and on falsy exit.

        The same SHAPE as the `AssertStmt` arm, and deliberately: that arm's own
        comment says the nonzero exit status is the signal and the message is
        not formatted, which is also true here — this backend has one output
        stream and the interpreter's contract for a failed assert is an
        `AssertionError`, whose observable part is the status. What differs is
        that this one is a CALL (`debug_assert(cond, m)` reaches here, not the
        statement form), so it has to handle the arguments, and it has to
        refuse a bracket it cannot bind.

        The message arguments are EVALUATED on the failing path only. That is
        not a shortcut: they are ordinary argument expressions, so evaluating
        them is what keeps a side effect from being dropped, and a program whose
        condition HOLDS never evaluates them because the real `debug_assert`
        does not either — its own docstring says so ("make sure there are no
        side effects in your message and condition expressions", which is
        exactly why that is true). Formatting them is
        `FORMAL_string_value_model.md`'s question and not this one's; see
        `model.debug_assert_is_call`.

        The condition is evaluated through `_emit_truthy_word`, so the empty
        string and the empty list are falsy for the reason they are elsewhere
        rather than by a null test.
        """
        bracket_why = M.debug_assert_bracket_refusal(e.func)
        if bracket_why is not None:
            raise CodegenError(bracket_why)
        args = list(e.args)
        if e.kwargs:
            raise CodegenError(
                f"debug_assert() takes no keyword arguments on the formal "
                f"arm64 path (got {[k for k, _v in e.kwargs]}); the only "
                f"keyword the builtin declares is `location`, which is a "
                f"source location for a diagnostic this path does not format")
        if not args:
            raise CodegenError(
                "debug_assert() takes the condition as its first argument, and "
                "got none: there is nothing to test, and lowering the empty call "
                "as a check that always passes would be an assert that can "
                "never fail, which is a program whose assertion says nothing")
        self._emit_truthy_word(args[0])
        self.asm.emit(encode_cmp_xn_imm(0, 0))
        self._assert_counter += 1
        aid = self._assert_counter
        fail_label = f"{self.func_name}_assert{aid}_fail"
        ok_label = f"{self.func_name}_assert{aid}_ok"
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(fail_label, here_offset=-4)
        self._emit_b_to(ok_label)
        self.asm.label(fail_label)
        # The messages, for their effects, and only on the path that exits —
        # so a program that passes pays nothing for them and a program that
        # fails runs exactly the expressions the source wrote.
        for msg in args[1:]:
            self._emit_expr(msg)
        # Darwin arm64 exit(1): x16 = SYS_exit, x0 = status, svc #0x80. The
        # same three instructions `AssertStmt` and `RaiseStmt` emit, so the
        # status a failed `debug_assert` leaves behind is the one every other
        # failing check on this path leaves behind.
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok_label)

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
        how = (M.builtin_value_method(method)
               or M.pointer_bounded_method(method)
               or M.string_identity_method(method))
        if how == "list_append":
            self._emit_list_append(e)
        elif how == "list_clear":
            self._emit_list_clear(e)
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
        elif how == "str_identity":
            # A string -> `char *` conversion, which is the IDENTITY here: a
            # `String` on this path is its own address, and the `CStringSpan` it
            # becomes is a ONE-FIELD struct whose value IS that field
            # (`model.STRING_IDENTITY_METHODS`).  Emitting the receiver is the
            # whole lowering, and it is `std/os/env.mojo`'s every `external_call`
            # argument — measured, that file's terminal cause before this arm.
            self._emit_expr(e.func.obj)
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
            # unreachable — every `how` all three tables produce is covered by
            # an arm above — and saying so is the point: an unreachable arm that
            # once silently did the wrong thing is worth making a loud one.
            raise CodegenError(
                f"{_dotted(e.func)}() is a method call on a value and this "
                f"backend has no lowering for {method!r}, which reached the "
                f"value-method dispatch with `how` = {how!r}. Every lowering "
                f"every table names is matched by an explicit arm above, so this "
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
    # A STRUCT pointee has no load and that is the derivation rather than an
    # omission: a struct's value on this path IS its frame address, so the word
    # in the receiver IS the pointee and nothing is loaded — the same identity
    # `Pointer()` gives.  It is emitted as the receiver and nothing else, and
    # the fields are read off that word through the holder tables
    # (`model.pointer_frame_bindings` seeds them; `_emit_frame_load` reads
    # them), so the field read is one `LDR` at `+8*slot` whichever of the two
    # spellings the source used.  `model.dereference_lowering` says why the
    # answer was refused until the holder analysis could see the name.
    #
    # A 1-byte and a 2-byte load are sign- or zero-EXTENDED into the 64-bit X
    # register, because a formal value is one 64-bit word and the program will
    # treat the result as one: `UInt8 200` must read back as 200 and `Int8 -1`
    # as 2^64-1.  `LDRB` is already a zero-extend and `LDRSB` the sign-extend,
    # so the unsigned and signed 1-byte cases are the same instruction with a
    # different mnemonic, and the 2-byte pair likewise.
    def _emit_dereference(self, e: F.CallExpr, method: str) -> None:
        # The operand refusal is `model`'s and shared, so the two machines
        # cannot describe one construct differently — and so the arm that names
        # `unsafe_load(i)` as an OFFSET reads the same here as on x86-64.
        operands = M.dereference_operands_refusal(
            _dotted(e.func), method, e.args)
        if operands is not None:
            raise CodegenError(operands)
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
        if _load == "identity":
            # A NULLABLE POINTER's `value()` is `Optional.value()`, the UNWRAP,
            # and the receiver IS the pointer (`model.nullable_pointer_unwrap`).
            # Nothing is emitted after the receiver: the answer is the word that
            # is already in X0. The load below would read the FIRST BYTE of the
            # pointee instead, which is what this used to do — measured, SIGSEGV.
            return
        if _load == "frame":
            # A POINTER TO A STRUCT: the receiver word IS the frame's address
            # (`model.pointer_frame_pointee`), so X0 already holds the answer
            # and a load would read the frame's FIRST SLOT as though it were a
            # pointee — `p.value().b` would answer `a`, not `b`.
            return
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

    # ── the pointer value model: a STORE through a dereference ─────────────
    #
    # `p.value() = v` is `_emit_dereference`'s mirror, and the WIDTH is
    # `model.pointer_store_lowering`'s — the same table, the same reader and
    # the same refusal words as the load, because a store at a width the load
    # does not use would make one pointee two different sizes on one machine
    # and disagree with the other machine besides.  The four instructions:
    #
    #   ("store", 1, *)  STRB Wt, [Xn]      — UInt8/Byte/Int8/c_char
    #   ("store", 2, *)  STRH Wt, [Xn]      — UInt16/Int16
    #   ("store", 4, *)  STR  Wt, [Xn]      — UInt32/Int32/c_int
    #   ("store", 8, *)  STR  Xt, [Xn]      — Int64/a pointer
    #
    # The signedness in the tuple is the pointee's declared signedness and is
    # not consulted: a store has no result to sign-extend, and the width is what
    # it truncates to.  Truncation rather than a refusal is the decision, and
    # `model.py`'s section on it carries the argument — the short form is that
    # `p[i] = v` over the same pointee has always emitted `strb` on both
    # backends, so the two spellings of one store must answer alike, and
    # `*(UInt8 *)p = v` is C.
    #
    # The register discipline is `_emit_subscript_store_reg`'s, and it is not
    # tidiness: the address computation builds its answer in X0 out of X0..X4
    # and X9, so the VALUE has to be across the stack before the address is
    # computed or the address is what gets stored.  Measured on the subscript
    # path: `xs[2] = 9` left a frame pointer at element 2.  The value comes back
    # into X0 afterwards for the same reason it is put there first — every
    # `_emit_expr` leaves its answer in X0, and a statement's value is what the
    # next statement reads.
    def _emit_pointer_store(self, target: F.CallExpr, value) -> None:
        obj = target.func.obj
        how, why = M.pointer_store_lowering(
            self._cur_fn, target, self._structs, self._functions, self._structs)
        if how is None:
            raise CodegenError(M.pointer_store_refusal(
                target.func.member, why
            ).format(dotted=_dotted(target.func)))
        _store, width, _signed = how
        self._emit_expr(value)                    # X0 = value
        self.asm.emit(encode_stp_sp_pre(0, 31))   # push the value
        self._emit_expr(obj)                      # X0 = the address
        self.asm.emit(encode_mov_zr_xn(9, 0))     # X9 = addr, out of the way
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))   # X5 = the value
        if width == 1:
            self.asm.emit(encode_strb_wd_wn(5, 9, 0))
        elif width == 2:
            self.asm.emit(encode_strh_wt_wn_imm(5, 9, 0))
        elif width == 4:
            self.asm.emit(encode_str_wt_wn_imm(5, 9, 0))
        else:
            self.asm.emit(encode_str_xt_xn_imm(5, 9, 0))
        self.asm.emit(encode_ldp_sp_post(0, 31))  # pop the value back into X0

    # A STORE into a frame a POINTER names — `p.value().field = v`, the store
    # half of the member-read arm's `p.value().field`.  It exists because the
    # read being answerable makes the store's refusal FALSE: that refusal says
    # "this path has no way to say what 'p.value(...)' holds", and after the
    # read arm it plainly can.  A diagnostic that is false about the program is
    # worse than a missing one.
    #
    # The register discipline is `_emit_pointer_store`'s above, for its reason:
    # the address is computed out of X0..X4 and X9, so the VALUE has to be
    # across the stack before the base is computed or the address is what gets
    # stored (measured on the subscript path: `xs[2] = 9` left a frame pointer
    # at element 2).  A whole slot, always — a frame slot is 8 bytes whatever
    # its field's declared width, and `_emit_frame_store` is the same store.
    def _emit_frame_store_through(self, value, base, slot: int) -> None:
        self._emit_expr(value)                    # X0 = value
        self.asm.emit(encode_stp_sp_pre(0, 31))   # push the value
        self._emit_expr(base)                     # X0 = the frame's address
        self.asm.emit(encode_mov_zr_xn(9, 0))     # X9 = addr, out of the way
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, 0))   # X5 = the value
        self.asm.emit(encode_str_xt_xn_imm(5, 9, 8 * slot))
        self.asm.emit(encode_ldp_sp_post(0, 31))  # pop the value back into X0

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

    def _emit_list_clear(self, e: F.CallExpr) -> None:
        """`xs.clear()` — one store of zero at offset 0 of the blob.

        The blob is `[count:i64][elem0]…`, so its COUNT is offset 0 and
        emptying it is exactly that one store; the elements past the count are
        already unreachable and nothing walks them. It is `List.clear` in
        `std/collections/binary_heap.mojo` and nothing else, and it is here
        rather than as a rewrite because the store is the whole method — there
        is no loop and no capacity to compute.

        **No capacity check, and that is the difference from `append`.** An
        append needs room the compile-time scan cannot find for a blob it did
        not see built, which is why `_emit_list_append` refuses rather than
        growing one; a clear needs no room at all, so the receiver may be any
        word this image has established to be a list — which is what
        `model.BUILTIN_VALUE_METHOD_LIST_KINDS` gates, and the guard is a KIND
        precisely because a zero written at offset 0 of an arbitrary word is a
        store into whatever address that word holds.

        The receiver is emitted first and the base recomputed into X9, the
        register discipline `_emit_list_append` and `_emit_block_store` both
        use: evaluating a receiver can be anything, and both clobber X9.

        Returns 0, for `non_container_element_refusal`'s reason and
        `_emit_list_append`'s: `list.clear` returns None, and nothing in the
        language can tell that from a zero."""
        if e.args or e.kwargs:
            raise CodegenError(
                f"list.clear() takes no arguments on this path "
                f"(got {len(e.args or []) + len(e.kwargs or [])})")
        self._emit_expr(e.func.obj)                     # X0 = the blob base
        self.asm.emit(encode_mov_zr_xn(9, 0))
        self.asm.emit(encode_movz_xd_imm(0, 0))         # count = 0
        self.asm.emit(encode_str_xt_xn_imm(0, 9, 0))

    def _emit_list_append(self, e: F.CallExpr) -> None:
        """`xs.append(v)` — store v at the blob's count and bump the count.

        The blob is `[count:i64][elem0]…` in the frame, so there is no room to
        grow one: the capacity is a compile-time number (`_scan_list_caps`)
        and the store is checked against it, refusing to write past the blob.
        Appending more times than the scan found — inside a loop — therefore
        stops the program instead of quietly corrupting the frame, the same
        bargain `xs[i]` out of range makes.

        The stop is LOUD. It used to be a bare `exit(1)` with nothing on either
        stream, which is the worst of the three answers this backend can give:
        not a wrong number a reader can compare, not a named refusal they can
        act on, but silence. `model.list_append_overflow_message` (shared with
        x86-64, so the two machines cannot name this limit differently) is
        written to fd 2 first, through `write(2)`, and then the program stops.

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
        self._emit_overflow_diagnostic(
            M.list_append_overflow_message(
                recv.name if isinstance(recv, F.IdentExpr) else "<expr>", cap))
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(ok)
        self.asm.emit(encode_movz_xd_imm(0, 0))     # None

    def _emit_overflow_diagnostic(self, text: str) -> None:
        """`write(2, text, len)` — say WHICH bound was hit before stopping.

        The shared half of every bounded-container stop on this path, and the
        reason it goes through `write(2)` rather than the raw syscall the exit
        beside it uses: the exit sequence above is the Darwin one this backend
        already emits everywhere, but `write`'s syscall number is not what makes
        this a good message — the fact that the same C library call works on
        both platforms is, and `write` is the one call whose interface this
        value model can satisfy with nothing but an interned label and an
        immediate.

        SP is 16-byte aligned here (the append's own `stp` pushed a multiple of
        16), which is what AAPCS and the C library both assume at a call, so no
        extra adjustment is needed and the pushed base/value stay readable.
        X0-X2 are free: the values the append needed are already in X4 (base)
        and the out-of-range path discards them.
        """
        label = self._intern_string(text)
        _emit_sub_imm(self.asm, 31, 31, 16)
        self.asm.emit_adrp_add(1, label)
        self.asm.emit(encode_movz_xd_imm(0, 2))              # fd = stderr
        self.asm.emit(encode_movz_xd_imm(2, len(text)))      # length
        self._emit_extern_call("write", 3)
        _emit_add_imm(self.asm, 31, 31, 16)

    def _conversion_operand_is_text(self, operand) -> object:
        """True / False / None: does this conversion's operand hold text.

        The three-way answer `model.int_parse_lowering` and
        `model.printf_text_conversion_refusal` are both written against, asked
        here through `model.string_operand_is_string` so that the string reader
        is `_expr_str_kind`'s — the flow-sensitive one that tracks what THIS
        function's emission has bound, a parameter's annotation and a
        `comptime` binding included.

        `False` is positive evidence and comes from the type as well as the
        binding: an operand whose declared type is an integer one is not text
        whatever else this build does or does not know about it. `None` is the
        permissive direction and is the whole reason `int(n)` keeps working —
        an unannotated parameter is a word this build cannot classify.
        """
        if M.string_operand_is_string(self._expr_str_kind(operand)):
            return True
        if M.string_operand_is_string(getattr(
                self._expr_str_kind(operand), "kind", None)):
            return False
        return None

    def _emit_int_parse(self, text_expr, base: int) -> None:
        """`int(s, base)` — `strtoll(s, &end, base)`, and the `end` is checked.

        Three values have to survive the `strtoll` call and there is no
        callee-saved register free, so they go in a 32-byte window:
        `[sp+0]` the string, `[sp+8]` the `endptr` `strtoll` writes, `[sp+16]`
        the value it returns and `[sp+24]` that end pointer parked across the
        `strspn` below. 32 rather than 24 so SP is still 16-byte aligned at the
        call, which is what AAPCS and the C library both assume — the same
        bargain `f.write(s)` makes two hundred lines up.

        **The `endptr` check is the half that must not be skipped.** `strtoll`
        returns 0 for a string with no digits in it and returns the digits it
        managed for one with trailing rubbish, where CPython raises
        `ValueError`; this path has no exception, so the two are refused at run
        time rather than answered. `0` is not available as the answer either —
        `int("0")` is 0, and `formal/hostmods/argparse.mojo`'s own `is_decimal`
        says so — so nothing but the `endptr` distinguishes "parsed zero" from
        "parsed nothing". The stop writes `model.int_parse_trap_message` to fd 2
        first, because a silent exit is the worst of the three answers this
        backend can give (`_emit_list_append`'s own docstring is the argument).

        `base` is a compile-time constant (`model.int_parse_lowering` refuses
        anything else), which is why it is a `movz` immediate and not a
        register: a base read at run time would need a slot of its own to
        survive the call, and it is a different question from a stated one.
        """
        self._while_counter += 1
        trap = f"{self.func_name}_ip{self._while_counter}_trap"
        end = f"{self.func_name}_ip{self._while_counter}_end"
        _emit_sub_imm(self.asm, 31, 31, 32)
        self._emit_expr(text_expr)                        # X0 = s
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 0))     # [sp+0] = s
        _emit_add_imm(self.asm, 1, 31, 8)                 # X1 = &end
        self.asm.emit(encode_movz_xd_imm(2, base))         # X2 = base
        self._emit_extern_call("strtoll", 3)               # X0 = value
        self.asm.emit(encode_str_xt_xn_imm(0, 31, 16))    # [sp+16] = value
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 8))     # X1 = end
        # TWO questions about `end`, and `strtoll`'s answers to them are what
        # CPython's two rules are:
        #
        #   * `end == s` means NO DIGIT was consumed. `*end` is then the NUL of
        #     an empty or all-whitespace string, so the trailing test below would
        #     pass and the parse would answer 0 for `int("")` — which CPython
        #     raises on. The difference is the whole of `strspn`'s `s` versus
        #     CPython's "at least one digit".
        #   * `*end` is a NUL only when the rest of the string is empty. It is
        #     the first TRAILING whitespace when the string was padded, and
        #     CPython accepts that (`int("  41  ")` is 41), so the rest of the
        #     remainder is measured with `strspn` over C's own six whitespace
        #     characters and the test is on what is past THAT. Without it every
        #     padded read stops, which is a false refusal of a program CPython
        #     runs — the one shape `int(user_input)` has.
        #
        # `end` is PARKED at [sp+24] rather than kept in X1 across the call,
        # because `strspn`'s set is the second argument and lands in X1: leaving
        # `end` there made the addition below add the run to the WHITESPACE SET's
        # address, and every parse stopped. The window is 32 bytes for exactly
        # this reason — [sp+24] is the one slot nothing else wanted.
        self.asm.emit(encode_str_xt_xn_imm(1, 31, 24))    # [sp+24] = end
        self.asm.emit(encode_ldr_xt_xn_imm(3, 31, 0))     # X3 = s
        self.asm.emit(encode_sub_xd_xn_xm(4, 1, 3))       # X4 = end - s
        self.asm.emit(encode_cbz_xn(0, 4))                # no digits -> stop
        self.asm.emit_label_rel(trap, here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(0, 1))            # X0 = end
        self.asm.emit_adrp_add(1, self._intern_string(M.C_WHITESPACE))
        self._emit_extern_call("strspn", 2)               # X0 = trailing run
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 24))    # X1 = end
        self.asm.emit(encode_add_xd_xn_xm(1, 1, 0))      # X1 = past the run
        # ONE BYTE, not eight: `*past` is a NUL when the string was consumed,
        # and an 8-byte load at that address has the NUL in its low byte and
        # whatever follows the string in the other seven, so the word is
        # non-zero and every parse of a valid string stops. LDRB zero-extends,
        # so X2 is zero exactly when the byte is the NUL.
        self.asm.emit(encode_ldrb_wd_wn(2, 1, 0))        # W2 = *past
        self.asm.emit(encode_cbnz_xn(0, 2))              # not NUL -> stop
        self.asm.emit_label_rel(trap, here_offset=-4)
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 16))    # X0 = the value
        _emit_add_imm(self.asm, 31, 31, 32)
        self._emit_b_to(end)
        self.asm.label(trap)
        self._emit_overflow_diagnostic(M.int_parse_trap_message(base))
        self.asm.emit(encode_movz_xd_imm(0, M.SHIFT_TRAP_STATUS))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(end)

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

    # ── Reading and writing one element of a blob, at any distance ──
    #
    # A blob element `i` is at byte `8*(i+1)` from the blob's base, and the
    # immediate-offset LDR/STR reach 12 bits SCALED by the access size: 4095
    # words, 32760 bytes. Element 4095 is the first one past it. A list literal
    # or a `range()` literal that long used to die inside
    # `encode_str_xt_xn_imm`'s own `assert 0 <= imm12 < 0x1000`, three frames
    # below anything that could name the limit — a bare AssertionError out of
    # the encoder, on a program whose only problem is that it is large.
    #
    # So the offset goes in a REGISTER past the immediate's reach and the
    # register-offset form is used, and the limit that remains is the frame's,
    # which `_reserve_blob`-style checks already state. The immediate form is
    # still used below the threshold because it is one instruction instead of
    # three, and every list anyone writes is below it.
    #
    # X15 is the offset register: locals live in X19..X28 and the temps this
    # emitter uses are X0..X14 and X16..X18, so X15 is dead here. It is written
    # AFTER the value is in place and read by the very next instruction, so it
    # does not have to survive the element's own emission either.
    _BLOB_IMM_MAX = 0x1000 * 8 - 8      # last byte the scaled imm12 names
    _BLOB_OFFSET_REG = 15

    def _emit_blob_store(self, base: int, byte_off: int, val: int) -> None:
        """STR X{val}, [X{base}, #byte_off] — or the register-offset form.

        `base` is the blob's base register (X9, the convention every blob site
        in this file uses) and `byte_off` is a compile-time byte offset into it.
        See `_BLOB_IMM_MAX` for why the second form exists."""
        if byte_off <= self._BLOB_IMM_MAX:
            self.asm.emit(encode_str_xt_xn_imm(val, base, byte_off))
            return
        self._emit_mov_imm(f"X{self._BLOB_OFFSET_REG}", byte_off)
        self.asm.emit(encode_str_xt_xn_xm(
            val, base, self._BLOB_OFFSET_REG))

    def _emit_blob_load(self, base: int, byte_off: int, val: int = 0) -> None:
        """LDR X{val}, [X{base}, #byte_off] — or the register-offset form.

        The load-side twin of `_emit_blob_store`, and for the same reason: the
        tuple-unpack sites index a blob with the same `8*(i+1)` shape and would
        otherwise keep the assert alive one path over from the fix.
        """
        if byte_off <= self._BLOB_IMM_MAX:
            self.asm.emit(encode_ldr_xt_xn_imm(val, base, byte_off))
            return
        self._emit_mov_imm(f"X{self._BLOB_OFFSET_REG}", byte_off)
        self.asm.emit(encode_ldr_xt_xn_xm(
            val, base, self._BLOB_OFFSET_REG))

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
            raise CodegenError(M.frame_blob_refusal(
                "a list literal", self._list_cursor + size, self._blob_cap))
        offset = self._list_cursor
        self._list_cursor += size

        self._emit_list_base(offset)
        self._emit_mov_imm("X10", n)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
        for i, el in enumerate(expr.elements):
            self._emit_expr(el)
            # Recompute base: element emission (calls, ADRP, …) clobbers X9.
            self._emit_list_base(offset)
            self._emit_blob_store(9, 8 * (i + 1), 0)
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
            # A FRAME ADDRESS has no order, and the flag-setting compare below
            # would decide one by where the allocator put the two objects.
            self._refuse_frame_order_operand(op, e.left)
            self._refuse_frame_order_operand(op, e.right)
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

        if op == "*" and (self._is_container_expr(e.left)
                          or self._is_container_expr(e.right)):
            left_is = self._is_container_expr(e.left)
            if left_is and self._is_container_expr(e.right):
                raise CodegenError(M.list_repeat_operands_refusal(
                    M.spelled(e.left), M.spelled(e.right)))
            blob, count_expr = ((e.left, e.right) if left_is
                                else (e.right, e.left))
            n = self._static_int(count_expr)
            if n is None:
                raise CodegenError(M.list_repeat_count_refusal(
                    M.spelled(e), M.spelled(count_expr)))
            self._emit_list_repeat(blob, n)
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
            # `p + k` on a POINTER is element arithmetic, not address arithmetic:
            # Mojo's `Pointer[T].__add__` moves `k` ELEMENTS, so the offset has
            # to be scaled by the pointee's width or `p + 1` on a `Pointer[Int64]`
            # reads the second element. The scale is emitted and not assumed, and
            # `model.pointer_offset_scale` is the ONE predicate that says when —
            # the same call `_offset_scale` makes when the load asks whether the
            # address it is about to read through is already scaled, so the two
            # architectures and the two halves of a dereference cannot disagree.
            # A one-byte pointee is the identity scale and is not emitted at all,
            # so every `char *` program is byte-identical to what it was.
            scale = M.pointer_offset_scale(self._cur_fn, e) if op in ("+", "-") \
                else None
            self._emit_expr_to(e.right, "X1")
            if scale:
                self.asm.emit(encode_movz_xd_imm(2, scale))
                self.asm.emit(encode_mul_xd_xn_xm(1, 1, 2))
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

    def _static_bit_mask(self, e):
        """The bit number `e` selects, or None when `e` is not a single bit.

        A mask is written two ways and both are ordinary: `x & 8` and
        `x & (1 << 3)` are the same question. `_static_int` answers only the
        first on purpose — its callers want a LITERAL (a `range` bound, a slice
        index), and folding arithmetic into it would change what they accept —
        so the shift is folded HERE, where the question is "is this a power of
        two" and a second reader is not a second implementation of the same one.

        None for zero, for a negative mask, and for anything that is not exactly
        one bit: `x & 255` asks about eight bits and `x & -1` is a Python
        identity this path does not need to recognise.
        """
        value = self._static_int(e)
        if value is None and isinstance(e, F.BinaryOp) and e.op == "<<":
            base = self._static_int(e.left)
            shift = self._static_int(e.right)
            if base is not None and shift is not None and 0 <= shift <= 63:
                value = base << shift
        if value is None or value <= 0 or (value & (value - 1)):
            return None
        return value.bit_length() - 1

    def _bit_test_mask(self, cond):
        """`(operand, bit, negated)` for a TEST OF ONE BIT, else None.

        `x & 8`, `x & (1 << 3)` and `8 & x` are the same question and the
        ARCHITECTURE has one instruction for it: TBZ/TBNZ reads a single bit of
        a register and branches, so the mask never has to be built, the `cmp`
        never runs, and the three instructions this used to spend become one.
        That is 49,645 TBNZ and 25,037 TBZ in the 200-binary instruction mix
        `tools/arm64_insn_audit.py` disassembles — the two largest genuinely
        uncovered entries, and they were unreached because the encoder had no
        caller. Between them they are 1.85% of every instruction a real
        compiler emits.

        `negated` is the `not` spelling, and it is a different INSTRUCTION and
        not a different way of spelling the same one: `if not (x & 8):` holds
        when the bit is CLEAR, so the branch that leaves it is taken when the bit
        is SET, which is TBNZ. Emitting TBZ there would be a program that builds,
        runs and answers the other way round.

        Three shapes, and refusing the fourth is the point:

          * the mask is a single bit, by either spelling above. `x & 0xff` is
            not a bit test — it asks whether any of eight bits is set — and
            answering it with a TBZ would be a wrong answer, so it falls through
            to the general path and stays right;
          * the mask may be written either way round, because `&` is commutative
            in Python and a reader writes both;
          * the base must be a LOAD this backend can put in a register on its
            own. Anything that needs a conversion, a call or a frame address is
            declined, because the bit test is only cheaper when the operand is
            already a word and a frame address has no bits to read.

        The bit is capped at 31 and the reason is in the ENCODER: the b40 form
        (bits 32-63) relocates imm14, and encoding that from memory of the spec
        is how you get a branch to the wrong address. `encode_tbz_xn_bit` raises
        rather than guess, and this declines before reaching it so a bit >= 32
        is a correct AND/CMP rather than an exception out of the middle of a
        branch.
        """
        negated = False
        if isinstance(cond, F.UnaryOp) and cond.op == "not":
            negated = True
            cond = cond.operand
        if not (isinstance(cond, F.BinaryOp) and cond.op == "&"):
            return None
        left, right = cond.left, cond.right
        for operand, mask in ((left, right), (right, left)):
            bit = self._static_bit_mask(mask)
            if bit is None:
                continue
            if bit > 31 or not self._is_pure_expr(operand):
                return None                 # see the docstring for both
            return operand, bit, negated
        return None

    def _emit_branch_unless_bit_test(self, cond, false_label: str) -> bool:
        """`if x & (1 << n):` as ONE instruction. True if it emitted.

        `_emit_branch_unless`'s first arm, and it comes before the comparison
        arm because a bit test is not a comparison: there are no flags to read
        and no boolean to round-trip through a register, which is the same
        argument the B.cond wiring makes and the same reason this one records a
        `cond_branch` — the proof generator filters `if` tests by the PC the
        codegen named, and a branch it was not told about would be attributed
        some other block's source condition.

        Which of the two, from the polarity rather than from the shape: this
        function branches on the FALSE case, so `if x & 8:` is TBZ (false is the
        bit clear) and `if not (x & 8):` is TBNZ. Both are recorded, and both
        are two-way with `pc + 4` on the fallthrough, which is why the proof
        generator's block scanner treats them as the `cbz` kind.
        """
        found = self._bit_test_mask(cond)
        if found is None:
            return False
        operand, bit, negated = found
        self._emit_expr(operand)            # X0 = the word
        self._record_cond_branch()
        self.asm.emit(encode_tbnz_xn_bit(bit, 0, 0) if negated
                      else encode_tbz_xn_bit(bit, 0, 0))
        self.asm.emit_label_rel(false_label, here_offset=-4)
        return True

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
        if self._emit_branch_unless_bit_test(cond, false_label):
            return True
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
        # …and the FRAME ADDRESS row, asked here for the same reason: a
        # comparison in a condition never reaches `_emit_binop`, so a check
        # asked only there would leave `if x < y:` branching on two addresses
        # while `r = x < y` is a build error. Two spellings of one question
        # disagreeing is how a wrong BRANCH gets in.
        self._refuse_frame_order_operand(cond.op, cond.left)
        self._refuse_frame_order_operand(cond.op, cond.right)
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

    def _emit_branch_if_cmp(self, l, r, unsigned_cond: str,
                            signed_cond: str, label: str) -> None:
        """CMP + B.cond to `label` when the comparison HOLDS, no CSET.

        The positive form, because a construct needs both polarities from one
        comparison and two independent copies of this is how they come to
        disagree: `_emit_loop`'s for-range test branches one way at the loop head
        and the other way at the bottom, and they must be the same comparison.
        """
        self._emit_cmp_flags(l, r, unsigned_cond, signed_cond)
        chosen = signed_cond if self._signed else unsigned_cond
        self._record_cond_branch()
        self.asm.emit(encode_b_cond(chosen, 0))
        self.asm.emit_label_rel(label, here_offset=-4)
        return True

    def _emit_branch_unless_cmp(self, l, r, unsigned_cond: str,
                                signed_cond: str, false_label: str) -> None:
        """CMP + B.cond on two already-separated operands, no CSET.

        The operand-level half of `_emit_branch_unless`, for the callers that
        have a comparison's operands without the enclosing BinaryOp: the
        `for i in range(...)` test, which is built from the loop target and the
        range's end bound rather than parsed from source. `_emit_branch_if_cmp`
        with both condition codes inverted, so there is one comparison and one
        branch emission rather than two of each.
        """
        return self._emit_branch_if_cmp(l, r, invert_cond(unsigned_cond),
                                       invert_cond(signed_cond), false_label)

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
        self._refuse_non_container_operand("a membership test", right)
        self._refuse_slot_container_operand("a membership test", right)
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
        # (formal/model.walk_stride) — at the element stride it would
        # walk keys and values alternately and stop at the pair count.
        self.asm.emit(encode_add_xd_xn_xm_lsl4(5, 5, 3)
                      if M.walk_stride(is_dict) == M.PAIR_STRIDE
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

    def _extern_decl_for(self, name: str):
        """The declaration of an IMPORTED callee `name`, or None.

        Keyed by the SYMBOL the call binds, and the entry is found by
        `model.dylib_callee_export` — the one resolution, in the same order as
        `_extern_symbol` — so the declaration handed to `bind_call_arguments` is
        always the one whose parameter list the call is actually being checked
        against. Asking by bare name instead would be a way to hand a call the
        signature of a same-named function in a different library.

        The `forwarded` table reaches this through that shared resolution, and
        that is load-bearing rather than tidiness: a re-exported callee
        (`pkg.f`, where `pkg/__init__` is nothing but `from .sub import f`) is
        published by the PACKAGE's manifest and nowhere else, so a lookup that
        left it out found no declaration, and a call with no declaration is a
        call whose arguments are passed unexamined — `pkg.f(1, 2, 3)` dropped
        the third and `pkg.f(1)` read the second out of an uninitialized
        register, printing two different numbers on the two architectures. It
        is the same defect `test_formal_cross_module.py` pins for the bare
        spelling, reached by the dotted one.
        """
        entry = M.dylib_callee_export(self._dylib_by_name,
                                      self._dylib_by_module,
                                      self._dylib_forwarded,
                                      self._import_aliases, name)
        if entry is None:
            return None
        return self._extern_decls.get(entry.get("symbol"))

    def _callee_decl(self, name: str):
        """The FunctionDef a callee `name` was declared by, or None.

        This module's own functions first — a local definition always wins —
        and then the linked libraries', read from their own source. None means
        the callee is not a function this image can see a declaration for, and
        the caller falls back to passing the arguments as written."""
        fn = self._functions.get(name)
        return fn if fn is not None else self._extern_decl_for(name)

    def _bind_call_args(self, name: str, e: F.CallExpr) -> list:
        """`e`'s arguments in positional form, for a known callee.

        A THIN CALL into `M.bind_call_arguments`, which is the one
        implementation of the rule and the reason the two backends cannot
        disagree about it.  This function used to be a second copy of the rule
        with a hole: `if not e.kwargs: return list(e.args)` short-circuited
        before the arity check, so a call with no keywords was never examined
        at all — which is how `f(1, 2, r)` reached a `def f(x, *rest)` and
        bound all three as fixed parameters.

        `fdef` is the callee's declaration, and it is looked up in BOTH
        registries — this module's own functions first, then the declarations
        read from the source each linked library was compiled from
        (`self._extern_decls`, keyed by the export symbol the call binds).
        That second lookup is what makes a call into another image obey the
        SAME contract as a call inside one: its arguments are bound to the
        callee's real parameter list, so a defaulted parameter is materialized
        and an argument count below the arity with nothing to fill it is a
        refusal naming the callee. It used to pass `list(e.args)` and nothing
        more, which made an omitted register hold a stale value — measured,
        `need_two(1)` across a dylib returning 1867609072 where the callee's own
        default says 511, while the identical call in the same file returned
        511."""
        fdef = self._callee_decl(name)
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
                # With ARGUMENTS it is a different question, and
                # `model.blob_constructor_lowering` is what decides it — one
                # predicate for both architectures and for the value model's
                # `ctor_establishes_slot`, so a kind can never be claimed for a
                # slot whose constructor store the emitter would refuse.  A blob
                # that has to HOLD n elements needs a frame reservation sized by
                # a value this compiler does not have, so it keeps its own
                # diagnostic; a `capacity=` operand is a reservation rather than
                # content and lowers as the empty container, with its limits in
                # that function's docstring.
                if M.blob_constructor_lowering(name, e.args,
                                               e.kwargs) is None:
                    raise CodegenError(
                        M.blob_constructor_with_operands_refusal(
                            name, len(operands)))
                self._emit_empty_blob()
                return
            raise CodegenError(
                M.unrepresentable_type_ctor_refusal(name))
        # A keyword argument names the same single value a positional one
        # does, so it is accepted as the operand rather than rejected:
        # `String(unsafe_from_utf8_ptr=p.value())` is how std/os/env.mojo
        # builds a string from a raw pointer, and refusing every keyword form
        # blocked 78 stdlib files on a shape the language allows. What is
        # still refused is a genuine mismatch of ARITY — a conversion has one
        # operand, and two of them (positioned or named) is not a conversion.
        operands = list(e.args) + [v for _n, v in e.kwargs]
        # `int(s)` and `int(s, base)` are a PARSE, not a conversion, and the
        # decision is `model.int_parse_lowering`'s so that x86-64 cannot answer
        # this differently. It has to be asked here, before the zero-operand and
        # arity arms below, because those two are about a CONVERSION's arity and
        # a parse has a different one.
        if name in M.INT_TYPE_CTORS:
            verdict = M.int_parse_lowering(
                name, operands, self._conversion_operand_is_text)
            if verdict[0] == "parse":
                self._emit_int_parse(operands[0], verdict[1])
                return
            if verdict[0] == "refuse":
                raise CodegenError(verdict[1])
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
        # `S()`, `S(a, b)`, `S(x)` and a keyword form: ONE decision, asked for
        # EVERY shape. The gate this replaced (`if e.args or e.kwargs:`) meant a
        # zero-argument construction never asked, so a one-field struct whose
        # `__init__` takes no required parameter had its body dropped at the
        # site and `C()` was a fresh zero word — measured, both machines, wrong
        # answer, no refusal. See `model.one_word_construction`, which is where
        # the rule lives now.
        value, refusal = M.one_word_construction(
            st, e, self._structs, self._frame_candidates, self._return_types)
        if refusal is not None:
            raise CodegenError(refusal)
        if value is None:
            self._emit_fresh_one_word(name, st, e)
            return
        self._emit_expr(value)

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
        ok, bad = M.struct_frame_representable(st, self._structs)
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
        for slot, (kind, payload) in enumerate(
                M.struct_frame_defaults(st, self._structs)):
            if kind == M.DEFAULT_STRING:
                value = F.StringLiteral(value=payload)
            else:
                value = int(payload or 0)
            self._emit_block_store(site, slot, value)
        # …and then the constructor's own stores, for the one shape that has
        # them.  Empty for `S()`, which is why this is the same code as the
        # default constructor's rather than a fourth copy of it.
        for _field, slot, value in (plan[1] if shape ==
                                    M.CONSTRUCTION_INIT else ()):
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
        own base, and the outer base is recomputed per store anyway.  The site's
        OWN slots are not touched here — the constructor brings those up itself,
        and a nested frame's ADDRESS is stored into its slot after them.

        `site[0]` is the struct, and `model.struct_block_direct_children` is its
        OWN nested frames with their offsets — one level, not the flattened list,
        because the placement is a RECURSION and a recursive walk is what carries
        the parent's offset.  Reading the level from the model rather than from
        `site[2]` is what keeps a frame two levels down from being written at the
        top object's own offset.
        """
        for _fname, _slot, child, child_off in \
                M.struct_block_direct_children(site[0], self._structs,
                                               site[1]):
            self._emit_nested_frame_defaults(child, child_off)

    def _emit_frame_defaults(self, st, offset: int) -> None:
        """One frame's own slots, at their class-level defaults."""
        for slot, (kind, payload) in enumerate(
                M.struct_frame_defaults(st, self._structs)):
            if kind == M.DEFAULT_STRING:
                self._emit_expr(F.StringLiteral(value=payload))
            else:
                # `_emit_mov_imm`, not a hand-rolled movz: it is the one
                # materializer on this backend and it covers the whole 64-bit
                # word, which `encode_movz_xn_imm` does not -- a class-level
                # default past 0xffff (or below zero) emitted a truncated word.
                # Carried over from the `_emit_nested_frame_init` this replaced,
                # where it was the same store one level down.
                self._emit_mov_imm("X0", int(payload or 0))
            self._emit_frame_base(offset)
            self.asm.emit(encode_str_xt_xn_imm(0, 9, 8 * slot))

    def _emit_nested_frame_defaults(self, st, offset: int) -> None:
        """`st`'s nested subtree, defaults first, deepest first.

        The same walk `model.struct_block_direct_children` describes, and it is
        the recursion that used to crash: it unpacked FOUR values out of
        `model.struct_nested_frame_fields`, which returns three, so it worked
        only while no nested frame had a nested frame of its OWN — the list was
        empty and the unpack never ran. Measured, both architectures: a struct
        whose nested struct has a nested struct of its own raised `ValueError:
        not enough values to unpack (expected 4, got 3)` from the CONSTRUCTOR,
        which is the class a sweep files as a compiler bug, and it happened before
        any read of the chain could be reached.

        `base=offset` is load-bearing and is the difference between the offsets
        being absolute and being relative to each level: a nested frame's own
        children sit at `offset + its own frame size`, and asking the model for
        this level's children with no base hands back offsets counted from
        `st`'s own block — which for the third level of `Outer/Inner/Inner2` put
        `Inner2`'s defaults at 16, on top of `Inner`'s own frame, and the read of
        `o.inner.inner2.x` then returned a DIFFERENT garbage number on each
        architecture.
        """
        for _fname, _slot, child, child_off in \
                M.struct_block_direct_children(st, self._structs, offset):
            self._emit_nested_frame_defaults(child, child_off)
        self._emit_frame_defaults(st, offset)

    def _emit_frame_nested_addresses(self, site) -> None:
        """Store the ADDRESS of each frame `_emit_frame_nested` just brought up.

        Which is the whole of "the slot holds a nested frame": one store per
        typed-nested field, in the same order as `_emit_frame_nested`, so the
        address stored and the frame initialized are the same one by
        construction rather than by two walks agreeing.

        RECURSIVE, and that is the depth-2 half of it: the address of a frame
        two levels down goes into the slot of the frame that HOLDS it, and only
        a walk carrying each level's own offset knows whose slot that is. This
        loop used to read the FLATTENED list, which has no parent left in it, so
        a grandchild's address would have been stored in the top object's frame
        at the grandchild's slot index — a silent wrong layout behind the crash
        above.
        """
        self._emit_nested_frame_addresses(site[0], site[1])

    def _emit_nested_frame_addresses(self, st, offset: int) -> None:
        """This frame's nested frames' addresses, then their own subtrees'.

        `base=offset` for the reason `_emit_nested_frame_defaults` gives: a
        level's rows are counted from ITS OWN block unless it is told where that
        block is, and an address stored at a relative offset writes into the
        wrong frame.
        """
        for _fname, slot, child, child_off in \
                M.struct_block_direct_children(st, self._structs, offset):
            self._emit_nested_frame_addresses(child, child_off)
            self._emit_frame_base(child_off)
            self.asm.emit(encode_mov_zr_xn(0, 9))
            self._emit_frame_base(offset)
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
            self._emit_mov_imm("X0", value)
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
        self._emit_nested_rebase(self._returns_frame, 17)
        self.asm.emit(encode_mov_zr_xn(0, 17))

    def _emit_nested_rebase(self, st, base_reg: int) -> None:
        """Re-point the COPY's nested slots at the copy, level by level.

        The FLATTENED placement has no parent left in it, so a level-2 frame's
        address would have been stored in the TOP object's slot
        at the grandchild's index and the copy would point at the block being
        reclaimed.  A recursive walk over `struct_block_direct_children` keeps
        each row's parent in hand, which is the same reason the placement loops
        are recursive.
        """
        for _fname, slot, child, child_off in \
                M.struct_block_direct_children(st, self._structs):
            _emit_add_imm(self.asm, 16, base_reg, child_off)
            self.asm.emit(encode_str_xt_xn_imm(16, base_reg, 8 * slot))
            self._emit_nested_rebase(child, base_reg)

    def _emit_frame_base(self, offset: int) -> None:
        """X9 = the address of the receiver frame `offset` bytes into the area.

        Literally `_emit_list_base`: the frames are at the bottom of the same
        reserved scratch the blobs are, at the same `SP + offset` addresses, and
        the only difference is that the blob cursor is told to start above
        them. Sharing the one routine rather than writing a second one is what
        makes "a frame is a blob that the cursor skips" true by construction
        instead of by two address computations agreeing."""
        self._emit_list_base(offset)

    def _emit_ctor_receiver(self, node) -> None:
        """X0 = the block the inlined `__init__` is constructing, or its slot.

        The two nodes `model.init_receiver_rewrite` produces, and the arithmetic
        is the same two instructions in the same order the store loop above
        uses: `_emit_frame_base` puts the block's address in X9 and a field read
        is a load at `X9 + 8·slot`.  The address is X9-RELATIVE, so this is
        correct at any point in the body whatever SP is doing — which matters
        because the value is an ARGUMENT of a lifted method call and the
        arguments after it are evaluated (and spill) in between.

        X9 → X0 because a bare expression leaves its value in X0 and this is
        reached through `_emit_expr`, the same door every other value comes
        through.
        """
        site = self._frame_sites.get(id(node.call))
        if site is None:
            raise CodegenError(
                f"a read of the receiver of a constructor at a site this "
                f"function did not reserve a receiver frame for — the frame "
                f"layout and the body disagree, which is a compiler bug, not a "
                f"program error")
        self._emit_frame_base(site[1])
        if isinstance(node, M.CtorField):
            self.asm.emit(encode_ldr_xt_xn_imm(0, 9, 8 * node.slot))
            return
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_fresh_one_word(self, name: str, st, e=None) -> None:
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
        the same failure wearing a hat.

        **THE FRAME-VALUED SOLE FIELD IS THE THIRD CASE, and it is the one that
        was a null pointer.** When the sole field holds a nested FRAME, this word
        is an ADDRESS: a fresh word of zeros is a load from address 0 on the
        first field read, from a green build, with no diagnostic
        (fixed 2026-10-03 in 4af77b16, where a one-field struct whose
        sole field holds a frame brings that frame up instead of a null
        word). So the nested frame is brought up here, exactly as
        `_emit_frame_constructor` brings up a struct of two or more fields'
        nested frames — its defaults, then its own nested subtree, deepest
        first — and its ADDRESS is the value. `e` is the construction node, and
        it is what finds the site: the bytes were reserved in the prologue by
        `model.struct_constructor_sites`, so the frame exists before the body
        runs and this is only bringing it up, which is the whole difference
        between a layout change and a new lowering."""
        kind, payload = M.struct_default_word(st, self._structs)
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
        if kind == M.DEFAULT_NESTED_FRAME:
            field_name, nested = payload
            site = self._frame_sites.get(id(e)) if e is not None else None
            if site is None:
                raise CodegenError(
                    f"constructing {name} needs the frame its field "
                    f"{field_name!r} holds, and no prologue reservation was "
                    f"made for one: the frame has to exist before the body runs, "
                    f"so it cannot be handed out by a bump pointer the way a "
                    f"list blob is. This is a disagreement between the "
                    f"construction's layout table and the body rather than a "
                    f"limit of the path — a compiler bug.")
            # The nested struct's own subtree first, then its own slots: the
            # same order `struct_block_direct_children` lays them out in, and
            # through `_emit_frame_nested` ITSELF rather than a second walk of
            # the same rows — that helper reads only the struct and the offset
            # out of the tuple it is handed, so passing the nested pair brings a
            # subtree up at the offset the layout chose.
            self._emit_frame_nested((nested, site[1], ()))
            self._emit_frame_defaults(nested, site[1])
            # …and the nested struct's OWN nested frames' ADDRESSES, which is
            # the third step and the one whose absence was a NULL SLOT. The
            # frame-valued sole field used to stop after the two above, on the
            # reasoning that its own address is the result — which is true and
            # says nothing about the frames INSIDE it. A `nested` whose own
            # typed-nested field holds a frame had that field's slot left at the
            # zero `_emit_frame_defaults` just wrote, so the first read through
            # it was a load at address 0: measured, both architectures,
            # `struct Deep: x, y` / `struct Inner: a, b, d: Deep` /
            # `struct Outer: n: Inner` with `o.n.d.x = 5` built, ran and died of
            # SIGSEGV (exit 139), while the depth-1 and depth-2 reads of the same
            # three structs answered correctly.
            # `bugs/FORMAL_a_one_field_struct_whose_only_field_is_a_nested_
            # frame.md` §2 has the disassembly.
            #
            # AFTER the defaults above, not before: the slot this stores into is
            # one of the slots they wrote, and the framed path orders it the
            # same way for the same reason (`_emit_frame_positional`).
            self._emit_frame_nested_addresses((nested, site[1], ()))
            # …and the ADDRESS last, because every store above left something
            # else in X0. An address materialized once and then overwritten is a
            # null pointer, which is the bug this case exists to close.
            self._emit_frame_base(site[1])
            self.asm.emit(encode_mov_zr_xn(0, 9))
            return
        self._emit_mov_imm("X0", int(payload or 0))

    def _specialization_args(self, e: F.CallExpr, ct_params: list) -> list:
        """The argument expressions binding `ct_params` at this call site."""
        try:
            return comptime_eval.specialization_args(e, ct_params)
        except ValueError as exc:
            raise CodegenError(str(exc))

    def _receiver_argument(self, e, name):
        """Which of this call's arguments is a by-reference RECEIVER, or None.

        One reader for both halves of the question, because the two halves are
        what make it a trap: `self._recv_ref_sites` knows the calls this module
        compiled the callee for, and a cross-module call is not in it — its
        callee is a SYMBOL — so reading only the local table passes a VALUE to a
        callee that dereferences it. Measured before this existed: a cross-module
        `c.bump(5)` printed `c=10`, the callee's new value computed and dropped,
        because the per-module write-back table could not see the call.

        So the answer comes from the CALLEE'S OWN DECLARATION, which is the one
        source that covers all three ways a callee can be reached:
        `formal/build.py` marked the definitions this module compiled
        (`_recv_ref_receiver`), and `formal/imports.py`'s `external_declarations`
        read the imported module's own source for the rest — so a call across a
        dylib boundary obeys the same convention as a call inside one, which is
        the entire point of a boundary contract. Not 0 unconditionally: a
        generic method's comptime parameters are passed AHEAD of the runtime ones
        (`model.incoming_args`, and the argument loop above prepends
        `self._specialization_args`), so the receiver of `def pop[SomeT](mut
        self)` lands one or more slots in.

        `None` for a callee with no declaration at all — a C symbol from a
        library with no source, which is by definition not a Mojo mutator, so
        its receiver is an ordinary argument. A callee whose declaration is not
        a one-field mutator is likewise an ordinary argument.
        """
        recv = M.declared_receiver_writeback(self._callee_decl(name))
        if recv is None:
            return None
        decl = self._callee_decl(name)
        if id(e) not in self._statement_calls \
                and not M.declared_returns_a_value(decl):
            # The MEMBER name as the source spells it, from the build pass's own
            # entry where there is one — `Cell.bump`, not `Cell.Cell_bump`, and
            # not the receiver. Read off the declaration for a cross-module
            # callee, which is all the name that path has.
            entry = self._recv_ref_sites.get(id(e))
            if entry is not None:
                wb = entry[0]
                owner, member = wb.owner, wb.member
            else:
                owner = getattr(getattr(decl, "_owner_struct", None), "name",
                                name)
                member = decl.name
            raise CodegenError(M.mutating_receiver_value_refusal(
                owner, member, recv))
        fdef = self._functions.get(name)
        ct = len(_comptime_param_names(fdef)) if fdef is not None else 0
        return ct

    def _address_taken_for(self, f) -> tuple:
        """The locals of `f` this function must hand over by ADDRESS.

        `formal/build.py`'s `_plan_receiver_call_sites` publishes the answer for
        the calls whose callee THIS module compiles. The cross-module calls are
        added here, from the same `_callee_decl` reader `_receiver_argument`
        uses, because the build pass runs before the imports resolve and has no
        declarations to read — and a local that is spilled in one build and in a
        register in the other is two different ABIs for one program.

        PUBLISHED back onto `f._address_taken`, rather than kept beside the
        allocation, because `var_register_map` reads that attribute to give the
        proof generator the same per-block register facts the codegen allocated.
        Two answers to "which locals have registers" is the disagreement that
        makes a proof about the wrong code.
        """
        names = list(getattr(f, "_address_taken", ()) or ())
        seen = set(names)
        for node in M.iter_nodes(getattr(f, "body", None)):
            if not isinstance(node, F.CallExpr) or not node.args:
                continue
            name = _callee_symbol(node.func)
            if name is None:
                continue
            if self._receiver_argument(node, name) is None:
                continue
            recv = node.args[self._receiver_argument(node, name)]
            if isinstance(recv, F.IdentExpr) and recv.name not in seen:
                seen.add(recv.name)
                names.append(recv.name)
        f._address_taken = tuple(names)
        return f._address_taken

    def _emit_receiver_argument(self, recv, name) -> None:
        """X0 = the ADDRESS of the local `recv`, for a by-reference receiver.

        Off the frame pointer, which is what makes the local's home BE the
        storage the callee writes through: `formal/build.py` put the name past
        every register in `_allocation_order` for exactly this. A local with no
        spill slot has no address to hand over, and passing its VALUE would be
        the old defect with a new name — so it is refused rather than emitted.
        """
        if not isinstance(recv, F.IdentExpr) or recv.name not in self._var_spills:
            raise CodegenError(M.receiver_address_refusal(
                name, recv.name if isinstance(recv, F.IdentExpr)
                else type(recv).__name__))
        _emit_sub_imm(self.asm, 0, 29, self._spill_off(recv.name))

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
        # `debug_assert` — a builtin of the LANGUAGE, intercepted before
        # `_callee_symbol` for the same reason `external_call` is: it is not a
        # symbol on this link line, and left to the extern path it became a
        # `BL debug_assert` that nothing defines. BEFORE `_callee_symbol`
        # rather than beside the `print` arm because the BRACKETED spelling is
        # the one this backend's reader cannot flatten at all — x86-64's
        # `_callee_symbol` has no `SubscriptExpr` arm — so asking the shared
        # predicate on the CALL is what lets the two architectures answer the
        # same question about the same call. One predicate, two arms.
        if not is_extern_call and M.debug_assert_is_call(e):
            self._emit_debug_assert(e)
            return
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
        # A CALLEE THIS FUNCTION BINDS.  `func(i)` inside a function that took
        # `func` as a parameter is a call through a VALUE, and `name not in
        # self._functions` below cannot tell it from a call to a C symbol: both
        # are "a name this unit does not compile", and the extern path's job is
        # to emit a call to a symbol, so it emitted a call to a symbol spelled
        # `func`.  The image was then caught by the bind audit four stages
        # later, as a symbol nothing on the link line provides — a true
        # statement, and one that says nothing about the construct, so
        # `stdlib/std/algorithm/backend/cpu/map.mojo` (whose only statement is
        # `func(i)`) was classified `not-answerable/unresolved-extern` rather
        # than as the codegen gap it is.
        #
        # Asked HERE, at the one line that takes the extern path, and not in the
        # link audit: a name a function binds is a word in a register, a spill
        # slot, a receiver's frame or a `__DATA` cell, so there is no code
        # address in it for a call to land on.  The decision and the words are
        # `model.callee_is_a_bound_value` / `model.callee_value_refusal`, read
        # by x86-64 from the same two, so the architectures cannot disagree
        # about one call.
        #
        # IT LOWERS NOW, and what used to be a refusal is one branch through the
        # word.  `is_extern` is FALSE for it, which is the whole of the change
        # downstream: every arm guarded on `is_extern` below is about calling a
        # C symbol and none of them applies to a branch through a value, while
        # the argument loop, the ABI split and the call itself are the same code
        # either way.  A function value is a CODE ADDRESS on this path
        # (`_load_var`'s last home), so `BLR` is the instruction and
        # `model.value_call_bracket_reading` is what settles the one genuinely
        # ambiguous shape — a bracketed callee, which is a specialization or an
        # index and only the parameter's declared type can say.
        through_value = (not is_extern_call and name not in self._functions
                         and M.callee_is_a_bound_value(self._cur_fn, name))
        # …and the name has to be a BARE one. `_callee_symbol` flattens a
        # subscript callee to its base, so `a.b[3](x)` arrives here as `a.b`
        # and `a[i](x)` as `a`; only the first of those is a name the function
        # binds as a callable. `comptime.specialization_name` is the one
        # recogniser of the bare spelling (`monomorph._callee_base` reaches the
        # same one), so the test is asked rather than spelled.
        through_value = through_value and (
            e.func.name == name if isinstance(e.func, F.IdentExpr)
            else comptime_eval.specialization_name(e.func) == name)
        if through_value:
            ann = M.param_annotation(self._cur_fn, name)
            # A keyword, or a bracket this build cannot read as a
            # specialization, is the construct's own refusal; a parameter whose
            # DECLARED type cannot hold a function is `callee_value_refusal`.
            # Both are asked here, at the one line that decided the call is
            # through a value, so the two architectures cannot refuse it
            # differently.
            if e.kwargs:
                raise CodegenError(M.value_call_keyword_refusal(
                    M.member_chain_text(e.func), "a keyword argument in"))
            if not M.value_callee_can_hold_a_function(ann):
                raise CodegenError(M.callee_value_refusal(
                    name, self._cur_fn, M.member_chain_text(e.func), ann))
            if isinstance(e.func, F.SubscriptExpr):
                # A bracketed callee through a value: a specialization, or an
                # index into a container. Only the parameter's declared type
                # can say, and it is `model.value_call_bracket_reading`'s
                # question for one reason —
                # `std/algorithm/backend/tile.mojo`'s
                # `workgroup_function: Some[Static1DTileUnitFunc]`, which
                # cannot be indexed at all, so its brackets can only be
                # comptime parameters.
                if M.value_call_bracket_reading(self._cur_fn, name, ann) \
                        != "specialization":
                    raise CodegenError(M.value_bracket_reading_refusal(
                        name, self._cur_fn, ann))
        # The three builtins this emitter intercepts by BARE NAME, read out of
        # `model.EMITTER_BUILTINS` rather than spelled here, for the reason that
        # table's comment gives: the set of names a backend compiles itself is a
        # fact three places have to agree on — this chain, the x86-64 one, and
        # `model.FRAME_VARIADIC_BUILTIN_CALLS` — and three hand-written copies of
        # it are three chances for a caller to be told a callee is compiled when
        # it is not, or the reverse. `_emit_range_list` takes the ARGS LIST and
        # the other two take the CallExpr; that asymmetry is the emitter's and is
        # why the table names the method rather than dispatching it.
        if not is_extern_call and name == "range":
            self._emit_range_list(list(e.args))
            return
        if not is_extern_call and M.emitter_lowers(name):
            if name == "len":
                self._emit_len(e)
                return
            if name == "print":
                self._emit_print(e)
                return
        if not is_extern_call and M.builtin_function(name) == "file_open":
            self._emit_open(e)
            return
        # A FORMAT STRING THIS CALL CANNOT USE — a `%s` conversion handed
        # something that is not text, or a conversion with no argument behind
        # it.  Asked here for the same reason `print` is intercepted two lines
        # above and not left to the extern path: the format string is the
        # SOURCE's, and this is the last place both the format and the varargs
        # are in hand together.  `print` builds its own format and so cannot get
        # it wrong; `printf` takes one unchecked all the way to C, where `%s`
        # walks bytes at the address it is handed looking for a NUL and every
        # conversion is a request for one more argument.  Measured with these
        # refusals lifted, on both architectures: `a = 5; printf("[%s]", a)`
        # builds, runs, prints nothing and dies of SIGSEGV, exit 139; and
        # `printf("50% done")` prints `50 0one` here and `50143074168one` on
        # x86-64, because `% d` is a conversion and the two machines disagree
        # only about what was left where it reads.  The decisions and the
        # messages are `model.printf_format_refusal`, shared with x86-64; it
        # gates on the resolved CALLEE rather than on `is_extern_call`, so
        # `external_call["printf", Int32](fmt, n)` — which reaches this same
        # line with `name == "printf"` — is asked the same question.
        self._refuse_unusable_printf_format(name, e)
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
        # `mod.S(...)` — a CONSTRUCTION of a struct the module publishes. The
        # decision and its reasons are `model.dotted_struct_construction`; what
        # it needs from this emitter is the receiver-shape answer above, which
        # is why it sits immediately after it rather than beside the extern
        # path: a `recv.m(...)` on a value is a method call, and only a base
        # that is a MODULE can be a construction.
        if not is_extern_call and M.dotted_struct_construction(
                e.func, self._structs, self._import_aliases):
            self._emit_struct_constructor(e, e.func.member,
                                          self._structs[e.func.member])
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
        is_extern = is_extern_call or (name not in self._functions
                                       and not through_value)
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
        # IS here — AND the symbol is on the link line, which `_dylib_syms` is
        # (and `_aliased_export` is for a name bound by `from m import f as g`).
        # Note the two are independent and both are needed. A `MojoList *`
        # argument is a box no link line can answer, so it is refused EVEN IF a
        # dylib provides the symbol; and `mojo_print`, whose every type is a
        # word, is refused only because nothing here provides it. Refusing by
        # prefix got the first case right by accident and could not tell the
        # second from it.
        if is_extern and not M.gimple_runtime_callable(
                name, name in self._dylib_syms
                or self._aliased_export(name) is not None):
            raise CodegenError(M.gimple_runtime_refusal(name))
        if is_extern and self._callee_decl(name) is None:
            # Unknown signature: AAPCS has no place for Python kwargs on a
            # raw BL. Drop them (they are almost always literals like
            # flush=True) and pass positional args only — same ABI the
            # extern path already uses for zero-kwarg calls.
            args = list(e.args)
            # …and the count is checked against what the MANIFEST publishes,
            # because "no declaration to read" must not mean "no contract to
            # obey". `extern_call_count_refusal` is the shared rule and returns
            # "" for every case it cannot decide, which is most of them (the
            # runtime dylib publishes no contract at all). Before it, a call
            # whose library shipped without its sources dropped its extra
            # arguments and read its missing ones out of an uninitialized
            # register — measured, `two(1, 2, 3)` printing 12 and `two(1)`
            # printing 1798665114 where CPython refuses both.
            refusal = M.extern_call_count_refusal(
                name, len(args),
                M.dylib_callee_export(self._dylib_by_name,
                                      self._dylib_by_module,
                                      self._dylib_forwarded,
                                      self._import_aliases, name))
            if refusal:
                raise CodegenError(refusal)
        else:
            # An extern callee whose DECLARATION is known goes through the same
            # binder as a local one. That is the whole fix for a default
            # argument that arrives as a stack address: the callee is not in
            # `self._functions`, but it is in `self._extern_decls`, keyed by
            # the export symbol the call binds, and `bind_call_arguments` is
            # the one implementation of "which argument lands on which
            # parameter, and what fills the gap".
            # A callee reached through a word has NO declaration in this image,
            # so the binder has nothing to bind against and every argument is
            # passed exactly as the call site wrote it — in position, with the
            # specialization's brackets AHEAD of them. That is the same rule
            # the direct path applies to a generic's comptime parameters
            # (`comptime.param_names`: they are ordinary leading arguments),
            # read through the one bracket reader
            # `formal/monomorph.py::supplied_bracket_args`, so there is one
            # answer to "what does `f[a, b](x)` pass" rather than one per
            # backend and one per callee kind.
            args = (monomorph.supplied_bracket_args(e) + list(e.args)
                    if through_value else self._bind_call_args(name, e))
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
        elif not is_extern_call and isinstance(e.func, F.SubscriptExpr):
            # A BRACKETED callee this unit does not compile. The branch above
            # is the only place a specialization's brackets are turned into
            # arguments, so without this the brackets are silently DROPPED and
            # `plain[3](5)` is emitted as `plain(5)` — measured, an image that
            # built, ran and printed a number the source never wrote. The
            # shared text is `model.specialization_call_refusal`, which x86-64
            # asks too.
            #
            # `and not is_extern_call`, and that is load-bearing rather than
            # belt-and-braces: `is_extern` is `is_extern_call or name not in
            # self._functions`, so an `external_call["setenv", Int32](…)` is
            # `is_extern` TOO — and this arm, keyed on `is_extern` and the
            # bracket, then refused the whole `external_call` construct as a
            # specialization, naming the C symbol `setenv` as a generic. The
            # construct is not a specialization and it is lowered, ten lines
            # above, by the same `is_extern_call` flag every other arm in this
            # function is gated on. Measured: 9 of `test_formal_external_call.py`'s
            # 29 cases, on both architectures, before this guard.
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
        # AAPCS splits the arguments: the first eight in X0..X7 and the rest in
        # the caller's frame at ascending offsets from the SP the callee enters
        # with.  Both halves are implemented, so the refusal below is a FRAME
        # bound rather than the ABI's register count — it used to be
        # `nargs > _ABI_ARG_REGS`, which was true about X0..X7 and wrong about
        # the consequence: `pack(fmt, v0..v7)` is nine arguments and the
        # alternative it protected against (evaluate the extra arguments, drop
        # them, and branch) built an image that read the ninth parameter as
        # ZERO — measured, `nine(1,...,9)` returned 1 where the source says
        # 90001.  A wrong value is strictly worse than a refusal, but so is a
        # refusal to a program the ABI can express, and this one can.
        n_stack = max(0, nargs - _ABI_ARG_REGS)
        if nargs > _MAX_INCOMING_ARGS:
            raise CodegenError(
                f"call {name}(): {nargs} arguments exceeds the "
                f"{_MAX_INCOMING_ARGS} the formal arm64 ABI passes "
                f"({_ABI_ARG_REGS} in registers and "
                f"{_MAX_INCOMING_ARGS - _ABI_ARG_REGS} on the stack)")
        # The returned-frame hidden word IS an argument — the callee reads it
        # out of the register after the last source one — so eight source
        # arguments to a frame-returning function is a NINE-argument call. It
        # has to land in a REGISTER: the callee reads it at index
        # `len(incoming)` by `_load_home_from_reg` and has no stack convention
        # for it, so this is the one case the split above cannot absorb and it
        # keeps the construct's OWN sentence rather than a count the reader
        # cannot account for.
        if sret_site is not None and len(args) >= _ABI_ARG_REGS:
            raise CodegenError(
                M.returned_frame_convention_refusal(name, len(args))
                or f"calling {name}() needs one hidden word for the "
                   f"caller's block and there is no argument register "
                   f"left for it")
        # The outgoing-argument area, reserved FIRST and as a multiple of 16 so
        # SP is still aligned at the call (AAPCS requires it, and every other
        # SP movement in this backend is a multiple of 16 for the same reason).
        # Reserving before anything is evaluated is what makes the slots below
        # safe: an argument expression that itself CALLS pushes and pops
        # symmetrically, so it works strictly under the area this reserved and
        # cannot land in it.
        stack_bytes = 0
        if n_stack:
            stack_bytes = 16 * ((n_stack + 1) // 2)
            _emit_sub_imm(self.asm, 31, 31, stack_bytes)
        # The STACK arguments first, each stored into the slot the callee will
        # read it from.  FIRST is load-bearing and not a style preference: the
        # register arguments below are spilled with a `STP [SP, #-16]!` each,
        # so evaluating them first would move SP 128 bytes down and every
        # `[SP + 8k]` above would land in the register spill area instead of
        # the reserved outgoing slots.  Measured before this was reordered, with
        # the offsets correct for the SP at the time: `nine(1..9)` returned 37
        # where the source says 45, and `ten(1..10)` returned 0 where it says
        # 1000000010 — the ninth argument read as zero, which is the wrong value
        # the ORIGINAL refusal existed to prevent, arriving by a different road.
        #
        # Storing them before the register spills is also what makes a nested
        # call in a stack argument safe: with the area reserved and nothing else
        # pushed yet, that nested call pushes strictly below it.
        for k in range(n_stack):
            self._emit_expr(args[_ABI_ARG_REGS + k])
            self.asm.emit(encode_str_xt_xn_imm(0, 31, 8 * k))
        # The register arguments. Evaluate left-to-right, spilling each result
        # so nested evaluations (which clobber X0/X1/X2) don't destroy earlier
        # arguments. Pop in reverse so arg0 lands in X0. Second slot of each
        # push/pop is XZR so loads never clobber a live arg.
        #
        # A BY-REFERENCE RECEIVER is the one argument that is not an ordinary
        # expression: the callee writes the receiver's new value back through
        # it, so it is the ADDRESS of the caller's own storage rather than the
        # value in it.
        recv_arg = self._receiver_argument(e, name)
        # A CALLEE REACHED THROUGH A WORD is evaluated and spilled FIRST, below
        # every argument, and popped back after them.  Both halves of that are
        # forced:
        #
        #   * first, because the source writes the callee before the arguments
        #     and an argument expression here can be an arbitrary call that
        #     clobbers every caller-saved register — so evaluating the callee
        #     after the arguments would read whatever the last one left;
        #   * lowest on the stack, because the pops below are a fixed count, so
        #     a slot pushed UNDER them is the one still there when the count is
        #     spent, and a slot pushed over them would be popped as argument 0.
        #
        # X16 is the destination and X17 the pair's second half: both are
        # temporaries under AAPCS and neither is an argument register, and at
        # this point nothing transient is live (the last argument was popped).
        if through_value:
            self._emit_expr(e.func.obj if isinstance(e.func, F.SubscriptExpr)
                            else e.func)
            self.asm.emit(encode_stp_sp_pre(0, 31))
        for i, arg in enumerate(args[:_ABI_ARG_REGS]):
            if i == recv_arg:
                self._emit_receiver_argument(arg, name)
            else:
                self._emit_expr(arg)
            self.asm.emit(encode_stp_sp_pre(0, 31))
        if sret_site is not None:
            # The block's own address, in the same scratch the constructor
            # frames use and at the offset the shared layout gave it.
            self._emit_frame_base(self._ret_frame_base + sret_site[1])
            self.asm.emit(encode_mov_zr_xn(0, 9))
            self.asm.emit(encode_stp_sp_pre(0, 31))
        for i in range(min(nargs, _ABI_ARG_REGS) - 1, -1, -1):
            self.asm.emit(encode_ldp_sp_post(0, 31))
            if i != 0:
                self.asm.emit(encode_mov_zr_xn(i, 0))
        if through_value:
            # The callee's own slot, last off the stack and into X16 — one
            # `LDP` pair whose high half is the X17 the push left, so nothing
            # else has to move it.  It is popped HERE and not before the
            # arguments because the pop loop above is a fixed count and this
            # slot is underneath it.
            self.asm.emit(encode_ldp_sp_post(16, 17))
        if is_extern:
            # A linked library's export spelling wins over the bare name, so
            # the BL, the GOT slot and the bind stream all name the symbol the
            # library actually defines.
            symbol = self._extern_symbol(name)
            # A VARIADIC callee whose arguments overflow the registers is
            # refused rather than guessed at, and the gate is
            # `variadic_named_args` and NOT `is_extern`: an ordinary dylib
            # export — `struct.mojo`'s own `pack`, which is what this whole
            # change is for — has a normal C signature, and the stack slots
            # above are exactly where its ninth argument belongs. What is
            # refused is the one case where two conventions land on one SP:
            # `_emit_variadic_area` lays a variadic tail out at `[SP + 8i]` as
            # it stands at the call, which is where the outgoing stack
            # arguments now are, and nothing states an order between them.
            # Nothing in this corpus needs it — every `printf` in the tree is
            # under the register count — and emitting a layout that has not
            # been measured is what this backend's refusal discipline exists to
            # prevent. `M.VARIADIC_SLOTS` already bounds the `...` tail.
            if n_stack and M.variadic_named_args(symbol) is not None:
                raise CodegenError(
                    f"call {name}(): {nargs} arguments puts "
                    f"{n_stack} of them past the {_ABI_ARG_REGS} "
                    f"argument registers, and {name} is a VARIADIC C entry "
                    f"point, whose unnamed arguments this path lays out in a "
                    f"separate stack area — two conventions on one SP with no "
                    f"order stated between them. Pass fewer arguments, or wrap "
                    f"the call in a function of this module that takes the "
                    f"values as parameters")
            area = self._emit_variadic_area(symbol, len(args))
            self.asm.emit_extern_bl(symbol)
            if area:
                self.asm.emit(encode_add_xd_xn_imm(31, 31, area))
        elif through_value:
            # `BLR X16` — the branch-with-link through the word, and the one
            # instruction `encode_blr_xn` was defined for since before any
            # lowering called it.  Same frame discipline as the `BL` below it:
            # this backend puts nothing in X30 across a call (an argument
            # expression that itself calls runs BEFORE either of them), so the
            # link register needs no save for the indirect form either.
            self.asm.emit(encode_blr_xn(16))
        else:
            self.asm.emit(encode_bl(0))
            # The NAME a call reaches, not the label this image happens to keep
            # for it: `compile()` gives every definition its own entry label, and
            # `name` is the alias bound to the last of them after every body is
            # out. `resolve()` patches out of the alias, so a caller emitted
            # before the callee lands on the same address it always did.
            self.asm.emit_label_rel(self._entry_labels.get(name, name),
                                    here_offset=-4)
        if stack_bytes:
            _emit_add_imm(self.asm, 31, 31, stack_bytes)
        if ext_return is not None:
            self._emit_extern_return(ext_return)
        elif is_extern:
            # A BARE call to a C symbol: no `external_call` bracket means no
            # DECLARED return type, and a declared type is where
            # `external_call_return_kind` reads the ABI rule from. The rule does
            # not go away for want of a declaration — it is the C library's
            # prototype that says how wide the answer is, and
            # `model.BARE_C_RETURN_KINDS` is that prototype for every C symbol
            # this tree calls bare. `None` when the callee is a Mojo export some
            # linked library publishes, which is a word whatever it is spelled;
            # the decision and the export test are shared, so x86-64 cannot
            # disagree with this about one call.
            self._emit_extern_return(M.bare_c_return_kind(
                name, self._dylib_by_name, self._dylib_by_module,
                self._dylib_forwarded, self._import_aliases, self._dylib_syms))

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
        this width" per architecture rather than two.

        `None` is the fourth caller, and it means the same as `WORD`: the
        callee's return width is not established anywhere, so the register is
        handed on as it arrived.  `external_call_return_kind` cannot answer
        `None` (a declared type it does not know is refused, not passed
        through), so only the BARE-C-call path reaches this line with one."""
        if kind is None or kind == M.EXTERN_RETURN_VOID \
                or kind == M.EXTERN_RETURN_WORD:
            return
        width, signed = kind
        self._emit_extend(0, 0, IntType(width, signed))


    # ── Comprehension / slice / div-shift / compare-chain ──────────

    def _compr_cap(self, expr: F.Comprehension) -> int:
        """Upper bound on result element (or pair) count for frame reserve.

        Single-generator over a list/tuple literal uses its length; nested
        generators multiply. Unknown iterables fall back to a frame-safe
        default (runtime append still bounds-checks).

        **A LITERAL's length is `model.list_literal_reserved_slots`, not
        `len(elements)`, and the difference is a program that used to exit 1.**
        A generator's iterable is evaluated inside the comprehension's own
        reservation, so a `[*a]` literal builds its blob by APPENDING and
        contributes up to `dynamic_splat_capacity` elements — while
        `len([*a].elements)` is the one `*` written in it. `[v * 10 for v in
        [*a]]` therefore reserved a ONE-element result, `[*a]` appended three,
        and the second append hit the capacity guard: no output, exit 1, on
        every array size. The rule is the same one
        `list_literal_reserved_slots` states for the append path ("what it
        occupies is the cap it reserved, not the number of `*` operands
        written in it"), asked of the same shared function x86-64's `_compr_cap`
        reaches through `_blob_est`, so the two backends now size one
        comprehension's reservation identically.

        Nothing here is a WIDENING of a cap: the number is what the iterable
        can actually produce, stated in the units the reservation is in. The
        frame budget is one sequential ledger (`_list_cursor` against
        `_blob_cap`, every `_reserve_blob` a step along it), so the two
        reservations are added whether or not this function counts the second
        one — and a pair that does not fit is `_reserve_blob`'s refusal, not a
        write past the blob."""
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
                m = M.list_literal_reserved_slots(it)
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
        # `_container_ctx` is AMBIENT — it is read by `_emit_binop` at whatever
        # depth it finds itself — so a comprehension reached from a container
        # position (a for-iterable, a membership RHS, a parent generator's
        # iterable) inherited that position and lowered its OWN body with it:
        # `[x + 1 for x in [10, 20]]` inside `for y in …` took the concat path,
        # copied an integer as a blob and faulted on both architectures. A
        # comprehension's body is not a container position — inside one, `+` is
        # arithmetic, and the operands decide on their own (`_is_container_expr`
        # on a list literal, a name in `_blob_vars`). So the body is emitted
        # outside it and each generator's ITERABLE re-establishes it below.
        saved_ctx = self._container_ctx
        self._container_ctx = 0
        try:
            self._emit_compr_gen(expr, 0, offset, is_dict, cap, d0)
        finally:
            self._container_ctx = saved_ctx
            self._compr_depth = d0

        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_compr_gen(self, expr: F.Comprehension, gi: int,
                        res_offset: int, is_dict: bool, cap: int,
                        d0: int) -> None:
        """Recursive generator walk: gen[gi] … gen[-1], then append element.

        THE SCOPE STACK IS PUSHED AFTER THE TARGET STORE, and that placement is
        Python's rule rather than a convenience: generator `gi`'s own ITERABLE is
        evaluated in the scope of generators `0 … gi-1`, and the parent frame has
        already pushed exactly that and has not popped it (the pop is in this
        frame's `finally`, below the recursion). So the iterable above reads the
        enclosing scope, and everything from the target store down — the
        conditions, the element, the key, and every nested comprehension inside
        them — reads this generator's own scope as well.
        """
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

        # Same walk as a for-in, so the same operand it refuses: a `char *`
        # has no count word at offset 0, and one here is read as a count of
        # its own first bytes (measured: SIGBUS walking past the string).
        self._refuse_string_iteration("a comprehension iterable",
                                      gen.iterable)
        # Container ctx for the ITERABLE alone, so a BinaryOp `+` there means
        # list concat: `[x for x in a + b]` is a walk of the concatenation, and
        # without this it took the ALU path and looped forever. The elevation is
        # bounded to this expression because it is ambient — a nested
        # comprehension's body is not a container position (see
        # `_emit_comprehension`). The x86-64 backend's twin.
        self._container_ctx += 1
        try:
            self._emit_expr(gen.iterable)
        finally:
            self._container_ctx -= 1
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

            # From here down this generator's target is in scope: the
            # conditions, the element/key, and the recursion into the next
            # generator (whose own ITERABLE is evaluated one level up, which is
            # why the push is here and not at the top of the frame). See the
            # method's docstring.
            self._compr_scopes.append(
                self._vkinds.comprehension_generator_scopes(expr)[gi])
            try:
                for cond in gen.conditions or []:
                    if not self._emit_branch_unless(cond, step_label):
                        self._emit_truthy_word(cond)
                        self.asm.emit(encode_cmp_xn_imm(0, 0))
                        self._record_cond_branch()
                        self.asm.emit(encode_cbz_xn(0, 0))
                        self.asm.emit_label_rel(step_label, here_offset=-4)

                self._emit_compr_gen(expr, gi + 1, res_offset, is_dict, cap, d0)
            finally:
                self._compr_scopes.pop()

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
        # ONE 16-byte frame slot, with the key at [sp+0] and the value at
        # [sp+8], and both loads reading back exactly those offsets.
        #
        # This used to be two STP pairs — `stp x0, x1` then `stp x1, x31` —
        # which the comment above it read back as "the second stp lands lower,
        # so [sp+0] is the value and [sp+8] is the key". It does not: STP
        # Xrt1, Xrt2 stores Xrt1 at [SP] and Xrt2 at [SP+8], so after those
        # two pushes [sp+8] holds **X31**, a scratch register, and the key was
        # sitting unused at [sp+16]. Every dict comprehension therefore
        # stored a garbage key and the right value: the first pair read 0 out
        # of X31 by luck, so `{i: 100 + i for i in range(3)}[0]` was right and
        # [1] and [2] were a miss (exit 1). The value needed a second slot
        # only because the count load below clobbers X1; a plain STR into the
        # slot the STP already reserved is that, without moving the frame
        # twice or putting the key somewhere the loads cannot see.
        self.asm.emit(encode_stp_sp_pre(0, 31))            # key at [sp+0]
        self.asm.emit(encode_str_xt_xn_imm(1, 31, 8))     # value at [sp+8]
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
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 0))   # [sp+0] = key
        self.asm.emit(encode_str_xt_xn_imm(0, 4, 0))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 31, 8))   # [sp+8] = value
        self.asm.emit(encode_str_xt_xn_imm(0, 4, 8))
        self.asm.emit(encode_add_xd_xn_imm(1, 1, 1))
        self.asm.emit(encode_str_xt_xn_imm(1, 9, 0))
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
        are spliced at runtime with a frame-safe cap. The cap is
        `M.dynamic_splat_capacity`'s and not a number written here, so this
        backend and the x86-64 one cannot reserve different amounts for one
        source — which would be a program that builds on one machine and dies
        of the append path's capacity guard on the other.
        """
        cap = M.dynamic_splat_capacity(expr.elements,
                                       M.literal_splat_operand_is_static)
        offset = self._reserve_blob(8 + 8 * cap, "list unpack")
        self._emit_list_base(offset)
        self._emit_mov_imm("X10", 0)
        self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))

        for el in expr.elements:
            if isinstance(el, F.UnaryOp) and el.op == "*":
                op = el.operand
                if M.literal_splat_operand_is_static(op):
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

        The source base, its count and the index live in X10/X11/X12 — NOT in
        X9/X3, which is what this used and was wrong twice over:

        * `_compr_append_elem` re-derives the RESULT base into X9 (`_emit_list_base`
          writes X9 and nothing else) and puts its capacity flag in X3, so a
          loop keeping the source in X9/X3 read the result blob's own elements
          from the second iteration on. The comment here used to claim "append
          uses X0-X4 and may push/pop, but does not touch X9/X3", which is
          false about X3 outright and about X9 one call deeper.
        * the exit test was inverted: `cset ge` sets the flag when the index has
          REACHED the count, and this branched to `done` when the flag was
          CLEAR — that is, exactly when the loop should run. So the body never
          ran and `[*xs]` built an EMPTY list: it exited 0, and `len` of the
          result was 0, and reading an element of it exited 1. Measured on
          `def main(): a = [1, 2]; b = [*a]; printf("%d", len(b))` → `0`.

        X10-X13 are caller-saved scratch this sequence and the append between
        them all touch nothing of, which is the property the old pair did not
        have; X5 was already the element address here and stays it.
        """
        self.asm.emit(encode_mov_zr_xn(10, 0))         # X10 = src base
        self.asm.emit(encode_ldr_xt_xn_imm(11, 10, 0))  # X11 = src count
        self.asm.emit(encode_movz_xd_imm(12, 0))       # X12 = i = 0
        self._while_counter += 1
        loop = f"{self.func_name}_spl{self._while_counter}"
        done = f"{self.func_name}_spd{self._while_counter}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_xm(12, 11))
        self.asm.emit(encode_cset_xd_cond(13, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 13))
        self.asm.emit_label_rel(done, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(5, 10, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(5, 5, 12))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 5, 0))
        self._compr_append_elem(res_offset, cap)
        self.asm.emit(encode_add_xd_xn_imm(12, 12, 1))
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
            # …and a literal NEGATIVE amount is refused rather than emitted,
            # which is the build-time half of the same rule: the amount is
            # decidable here, and a refusal names the line where the run-time
            # trap in `_emit_shift_reg` can only leave a status behind. It has
            # to come BEFORE the saturation test, because a negative amount is
            # below 64 and would otherwise fall through to the register form
            # and be masked. `model.shift_amount_is_trap` is the decision, so
            # x86-64 asks the same question and words it identically.
            #
            # `fold_literal_expr` rather than this backend's `_static_int`:
            # both read a literal, but the shared folder is the one that also
            # answers `0 - 1` and `1 * -1`, and `0 - 1` is the spelling the
            # reproducer in the bug doc used. Two readers of "what does the
            # build know this amount is" is how the two spellings of one
            # literal would come to disagree about whether the build can
            # decide it.
            known = M.fold_literal_expr(imm_r)
            if M.shift_amount_is_trap(known):
                raise CodegenError(M.negative_shift_refusal(op, known))
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
            # X1 is a CSET flag, so "exp < 0" is X1 NON-zero: the negative exit
            # is a CBNZ, and the loop head below is the same. Both were CBZ,
            # which asks the flag for `exp >= 0` and `exp > 0` respectively and
            # therefore took the NEGATIVE exit for every non-negative exponent
            # and the loop exit on the first iteration — `2 ** n` for a local
            # `n` answered 0 on arm64 for every exponent, where x86-64's loop
            # (which tests the flags the same way) was right. The third branch
            # here, over `exp & 1`, is a CBZ and is right: the multiply is the
            # thing to SKIP when the bit is clear.
            self.asm.emit(encode_cbnz_xn(0, 1))
            self.asm.emit_label_rel(neg, here_offset=-4)
            # result = 1 in X2; keep exp in X0, base on stack
            self.asm.emit(encode_movz_xd_imm(2, 1))
            self.asm.label(loop)
            self.asm.emit(encode_cmp_xn_imm(0, 0))
            self.asm.emit(encode_cset_xd_cond(1, "le"))
            self.asm.emit(encode_cbnz_xn(0, 1))
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
            # Drop the base into the two registers the body had scratch for
            # (X4 = the mask 1, X5 = the multiply temp), NOT into (0, 31).
            # LDP-post into X0 is the shape the literal unroller uses above to
            # DISCARD the popped base, and it is right there because x0 holds
            # the answer. Here x0 has just been given the answer too, so
            # popping into it overwrote the result with the base — and
            # `2 ** n` for a local `n` answered 0 (or the base) on arm64 for
            # every exponent, while x86-64's loop, which pops into a scratch,
            # was right. X4 and X5 are dead at `done`: the body writes them and
            # reads neither after the last LSR.
            self.asm.emit(encode_ldp_sp_post(4, 5))     # drop base
            self._emit_trunc(common_type(self._ttype(e.left),
                                         self._ttype(e.right)))
            self._emit_b_to(f"{fn}_pow{pid}_end")
            self.asm.label(neg)
            self.asm.emit(encode_ldp_sp_post(4, 5))
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
        # The CHAIN is a separate emitter that never went through
        # `_emit_binop` — the `s += t` lesson again, one loop over.  Each link
        # compares the same two adjacent operands a plain comparison would, so
        # each link asks the same frame-ordering question.
        for i, op in enumerate(ops):
            self._refuse_frame_order_operand(op, operands[i])
            self._refuse_frame_order_operand(op, operands[i + 1])

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

        Python's slice, with the four defaults that depend on the sign of
        `step` — which is a RUN-TIME value on this path, so each default is
        its own word on the stack and the loop picks between them:

        |            | ascending (`step > 0`) | descending (`step < 0`) |
        |------------|------------------------|------------------------|
        | `i` starts at | `start`              | `start`                |
        | while        | `i < stop`           | `i > stop`             |
        | omitted start | 0                   | `count - 1`            |
        | omitted stop  | `count`             | -1                     |

        Both bounds are written once, wrapped (`-2` on a list of 6 is 4) and
        then clamped into `[0, count]`, in Python's order. A step of 0 is a
        `ValueError` in Python and `_exit(1)` here, because there is no
        exception on this path to raise it as — and an exit that flushes
        nothing, which is why the two loop defects below read for a long time
        as "a blob nothing ever filled".

        Result capacity is a static upper bound (literal length or 64).

        A STRING base is refused before any of that, and the reason is the
        count: the loop below reads it from offset 0 of the object, which for a
        `char *` is the first eight CHARACTERS, so the walk starts inside the
        string with a length taken from its own first two letters. Measured on
        both backends, `s = "abcde"; printf("[%s]", s[1:])` died with SIGSEGV
        (exit 139). `model.string_slice_refusal` holds the message and the
        argument for lowering the suffix case later."""
        self._refuse_frame_container_operand("a slice", obj)
        self._refuse_non_container_operand("a slice", obj)
        self._refuse_slot_container_operand("a slice", obj)
        sreason = M.string_slice_refusal(
            self._expr_str_kind(obj), M.spelled(obj))
        if sreason is not None:
            raise CodegenError(sreason)
        if isinstance(obj, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            # `list_literal_reserved_slots`, for the reason `_compr_cap` gives:
            # a `[*a]` literal fills its blob by appending, so what a slice of
            # it can hold is the cap it reserved and not the one `*` written.
            # Measured before this, `[*a][0:2]` with a three-element `a` exited
            # 1 on this backend and answered `2 3 4` on x86-64, whose slice
            # reservation never counted `elements` at all.
            src_cap = M.list_literal_reserved_slots(obj)
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

        # ── the six words the loop reads, and WHERE they are.  Six 16-byte
        # pushes, so every slot is a multiple of 16 and the offsets are named
        # once here rather than spelled as bare numbers through the rest of the
        # method — the previous version spelled them and had them drift out of
        # step with the pushes by two slots.
        #
        #   [SP+ 0] step    [SP+16] stop_d   [SP+32] stop
        #   [SP+48] start_d [SP+64] start     [SP+80] src
        SLOT_STEP, SLOT_STOP_D, SLOT_STOP = 0, 16, 32
        SLOT_START_D, SLOT_START, SLOT_SRC = 48, 64, 80

        self._emit_expr(obj)                          # X0 = src base
        self.asm.emit(encode_ldr_xt_xn_imm(9, 0, 0))  # X9 = count
        # Pushed BEFORE anything else is evaluated, because X0 is the only
        # register that holds the source base and the bounds below overwrite
        # it (`mov w0, #1`). Reading the count here rather than from the slot
        # is what makes the omitted-start default (`count - 1`) possible before
        # the pushes exist; the clamps re-read it from the slot afterwards,
        # since evaluating a bound may clobber X9.
        self.asm.emit(encode_stp_sp_pre(0, 2))        # src

        # start, evaluated ONCE.  An explicit bound is pushed twice — the
        # ascending word and the descending word — because the loop reads one or
        # the other and cannot know which; an omitted one pushes 0 and
        # `count - 1`, which is the whole reason the two exist.
        if start_e is None:
            self.asm.emit(encode_movz_xd_imm(4, 0))          # X4 = 0
            self.asm.emit(encode_stp_sp_pre(4, 31))           # start
            self.asm.emit(encode_mov_zr_xn(6, 9))
            self.asm.emit(encode_sub_xd_xn_imm(6, 6, 1))      # count - 1
            self.asm.emit(encode_stp_sp_pre(6, 31))           # start_d
        else:
            self._emit_expr_to(start_e, "X4")
            self.asm.emit(encode_stp_sp_pre(4, 31))           # start
            self.asm.emit(encode_add_xd_xn_imm(6, 4, 0))      # X6 = X4
            self.asm.emit(encode_stp_sp_pre(6, 31))           # start_d
        # stop, the same shape: `count` and -1 when omitted.
        if stop_e is None:
            self.asm.emit(encode_mov_zr_xn(5, 9))             # X5 = count
            self.asm.emit(encode_stp_sp_pre(5, 31))           # stop
            self.asm.emit(encode_movz_xd_imm(6, 1))
            self.asm.emit(encode_neg_xd_xn(6, 6))             # X6 = -1
            self.asm.emit(encode_stp_sp_pre(6, 31))           # stop_d
        else:
            self._emit_expr_to(stop_e, "X5")
            self.asm.emit(encode_stp_sp_pre(5, 31))           # stop
            self.asm.emit(encode_add_xd_xn_imm(6, 5, 0))      # X6 = X5
            self.asm.emit(encode_stp_sp_pre(6, 31))           # stop_d

        if step_e is None:
            self.asm.emit(encode_movz_xd_imm(8, 1))
        else:
            self._emit_expr_to(step_e, "X8")
        self.asm.emit(encode_stp_sp_pre(8, 31))                # step

        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, SLOT_SRC))
        self.asm.emit(encode_ldr_xt_xn_imm(9, 9, 0))          # X9 = count

        # Wrap negatives and clamp into [0, count] — Python's order, three
        # steps per bound.  The two upper clamps compared the COUNT against the
        # bound and wrote the count back when it was the larger of the two
        # (`cmp x9, x4; cset hi` asks "count > bound?"), so every bound BELOW
        # the count was raised to it: `xs[1:3]` became `xs[6:6]` and `xs[2:6]`
        # became `xs[6:6]`, so every forward slice was an empty list while the
        # blob it had just been given was full.  That is the "a consumer reads
        # the result as EMPTY" symptom, and it was these two comparisons.  The
        # lower clamp is new: without it `xs[-99:]` reads before the blob.
        #
        # An EXPLICIT bound clamps to ONE value for both directions, so its
        # descending word is rewritten from the ascending one.  The DEFAULTS are
        # not in [0, count] and must not be: `count - 1` and -1 are how
        # `xs[::-1]` reaches index 0.
        for reg, slot, other, expr, tag in (
                (4, SLOT_START, SLOT_START_D, start_e, "a"),
                (5, SLOT_STOP, SLOT_STOP_D, stop_e, "b")):
            self.asm.emit(encode_ldr_xt_xn_imm(reg, 31, slot))
            self.asm.emit(encode_cmp_xn_imm(reg, 0))
            self.asm.emit(encode_cset_xd_cond(0, "lt"))
            self.asm.emit(encode_cbz_xn(0, 0))
            w = f"{self.func_name}_slw{self._while_counter}{tag}"
            self.asm.emit_label_rel(w, here_offset=-4)
            self.asm.emit(encode_add_xd_xn_xm(reg, reg, 9))
            self.asm.emit(encode_str_xt_xn_imm(reg, 31, slot))
            self.asm.label(w)
            self.asm.emit(encode_ldr_xt_xn_imm(reg, 31, slot))
            self.asm.emit(encode_cmp_xn_xm(reg, 9))
            self.asm.emit(encode_cset_xd_cond(0, "gt"))
            self.asm.emit(encode_cbz_xn(0, 0))
            c = f"{self.func_name}_slk{self._while_counter}{tag}"
            self.asm.emit_label_rel(c, here_offset=-4)
            self.asm.emit(encode_mov_zr_xn(reg, 9))
            self.asm.emit(encode_str_xt_xn_imm(reg, 31, slot))
            self.asm.label(c)
            self.asm.emit(encode_ldr_xt_xn_imm(reg, 31, slot))
            self.asm.emit(encode_cmp_xn_imm(reg, 0))
            self.asm.emit(encode_cset_xd_cond(0, "lt"))
            self.asm.emit(encode_cbz_xn(0, 0))
            f0 = f"{self.func_name}_sll{self._while_counter}{tag}"
            self.asm.emit_label_rel(f0, here_offset=-4)
            self.asm.emit(encode_movz_xd_imm(reg, 0))
            self.asm.emit(encode_str_xt_xn_imm(reg, 31, slot))
            self.asm.label(f0)
            if expr is None:
                continue
            self.asm.emit(encode_ldr_xt_xn_imm(6, 31, slot))
            self.asm.emit(encode_str_xt_xn_imm(6, 31, other))

        # step == 0 → exit 1 (cbnz skips the exit when step != 0)
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, SLOT_STEP))
        self.asm.emit(encode_cmp_xn_imm(8, 0))
        zstep = f"{self.func_name}_slz{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 8))
        self.asm.emit_label_rel(zstep, here_offset=-4)
        self.asm.emit(encode_movz_xd_imm(0, 1))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
        self.asm.label(zstep)

        # i → X6, from the word the direction picks.
        #
        # The `cbz` below is the WHOLE of this conditional and its direction is
        # load-bearing: `cset x0, lt` is 1 exactly when step < 0, so `cbz x0`
        # fires when step >= 0 and must JUMP OVER the descending arm rather
        # than into it.  It used to point at that arm — the relocation named the
        # label the code fell through to — so every forward slice started at
        # `stop - 1` and walked DOWN to the result blob's capacity check, which
        # `_exit(1)`'d without printing anything.
        self.asm.emit(encode_cmp_xn_imm(8, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        pos_init = f"{self.func_name}_slp{self._while_counter}"
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(pos_init, here_offset=-4)
        self.asm.emit(encode_ldr_xt_xn_imm(6, 31, SLOT_START_D))
        # …and BRANCH over the ascending load rather than falling into it: with
        # both bounds omitted the two words are `count - 1` and 0, so falling
        # through answered `xs[::-1]` with one element.
        self._emit_b_to(f"{self.func_name}_slm{self._while_counter}")
        self.asm.label(pos_init)
        self.asm.emit(encode_ldr_xt_xn_imm(6, 31, SLOT_START))
        self.asm.label(f"{self.func_name}_slm{self._while_counter}")

        # Loop: the sign of step, then the bound that sign means.
        self._while_counter += 1
        wid = self._while_counter
        loop = f"{self.func_name}_slt{wid}"
        body = f"{self.func_name}_slb{wid}"
        step_lbl = f"{self.func_name}_sls{wid}"
        done = f"{self.func_name}_sld{wid}"
        pos_body = f"{self.func_name}_slq{wid}"
        self.asm.label(loop)
        self.asm.emit(encode_cmp_xn_imm(8, 0))
        self.asm.emit(encode_cset_xd_cond(0, "lt"))  # 1 if step < 0
        self.asm.emit(encode_cbz_xn(0, 0))            # step >= 0 → positive
        self.asm.emit_label_rel(pos_body, here_offset=-4)
        # Descending: body while i > stop_d.  `start` is inclusive and `stop`
        # exclusive, and an omitted stop is -1, which is what lets `xs[::-1]`
        # reach index 0.  This arm used to test `i >= 0` and consult no bound
        # the source wrote at all, so `xs[5:0:-1]` (which starts at 5) walked
        # up from -1 and copied nothing, while `xs[::-1]` — the one input for
        # which 0 is the right bound — was right by coincidence.
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, SLOT_STOP_D))
        self.asm.emit(encode_cmp_xn_xm(6, 5))            # signed: i - stop_d
        self.asm.emit(encode_cset_xd_cond(0, "gt"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(done, here_offset=-4)
        self._emit_b_to(body)
        self.asm.label(pos_body)
        # Ascending: body while i < stop.  This test DID NOT EXIST — the arm was
        # an unconditional `b body` under a comment that described this one — so
        # with step > 0 the loop ran until the capacity check stopped it,
        # whatever `stop` said.  Each bound is re-read from the stack rather
        # than kept in a register because the append below clobbers X0-X9 and
        # the bound is the one value the loop cannot recompute.
        self.asm.emit(encode_ldr_xt_xn_imm(5, 31, SLOT_STOP))
        self.asm.emit(encode_cmp_xn_xm(6, 5))            # signed: i - stop
        self.asm.emit(encode_cset_xd_cond(0, "lt"))
        self.asm.emit(encode_cbz_xn(0, 0))
        self.asm.emit_label_rel(done, here_offset=-4)
        self._emit_b_to(body)

        self.asm.label(body)
        # append src[i]
        self.asm.emit(encode_ldr_xt_xn_imm(9, 31, SLOT_SRC))
        self.asm.emit(encode_add_xd_xn_imm(5, 9, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(5, 5, 6))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 5, 0))
        self._compr_append_elem(offset, src_cap)
        # X6 survives the append (it clobbers X0-X4 and X9); step does not, so
        # it is re-read from the stack.  The reload of `start` that used to sit
        # here is gone: `_compr_append_elem` overwrites X4 with the element
        # address and nothing in the loop reads it afterwards — both bounds are
        # re-read from their own words because that is the only copy the append
        # cannot take.
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, SLOT_STEP))
        self.asm.emit(encode_add_xd_xn_xm(6, 6, 8))      # i += step
        self._emit_b_to(loop)

        self.asm.label(step_lbl)  # unused alias kept for label uniqueness
        self.asm.label(done)
        for _ in range(6):
            self.asm.emit(encode_ldp_sp_post(0, 31))
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
        # `start > count` is the question (the count is the SECOND operand, so
        # the subtraction is start - count); the old order asked "count >
        # start?" and clamped on THAT, which raised every in-range bound to the
        # count and made the range empty.
        self.asm.emit(encode_cmp_xn_xm(4, 2))
        self.asm.emit(encode_cset_xd_cond(0, "hi"))
        self.asm.emit(encode_cbz_xn(0, 0))
        c1 = f"{fn}_ssc{sid}1"
        self.asm.emit_label_rel(c1, here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(4, 2))
        self.asm.label(c1)
        self.asm.emit(encode_cmp_xn_xm(5, 2))
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
        self.asm.emit(encode_cbnz_xn(0, 0))           # i >= len → done
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

        THREE answers for the amount, in this order, and the order is the
        whole content of this function:

        1. **Negative** → `exit(SHIFT_TRAP_STATUS)`. A negative amount is not
           a shift distance, so there is no value to compute; the hardware
           would mask it to its low six bits and answer a different shift
           entirely (`1 << -1` was `1 << 63`). The compare is SIGNED, and it
           runs BEFORE the saturation compare for exactly the reason
           `shift_amount_is_trap` is a separate rule from `shift_saturates`:
           a negative amount is below 64, so unsigned it would take the
           saturating branch and answer 0 — a third wrong answer rather than
           the one that was there.
        2. **At or past the width** → the saturated value, which is 0 for
           `<<` and for a logical `>>` and the sign-extended word for an
           arithmetic one (`model.shift_saturated_is_zero`).
        3. **In range** → the shift instruction.

        The trap is the same three-instruction `exit` the divide-by-zero arm
        of `_emit_div_shift_pow` emits, and the same status
        (`model.SHIFT_TRAP_STATUS`), so "this program has no answer" is one
        answer on this path. A statically negative amount never reaches here —
        `_emit_div_shift_pow` refuses it at build time, which is the half that
        can name the line."""
        self._if_counter += 1
        sid = self._if_counter
        fn = self.func_name
        neg_label = f"{fn}_sh{sid}_neg"
        sat_label = f"{fn}_sh{sid}_sat"
        end_label = f"{fn}_sh{sid}_end"
        self.asm.emit(encode_cmp_xn_imm(1, 0))
        self.asm.emit(encode_b_cond("lt", 8))
        self.asm.emit_label_rel(neg_label, here_offset=-4)
        self.asm.emit(encode_cmp_xn_imm(1, M.SHIFT_WIDTH))
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
        self.asm.emit(encode_b(0))
        self.asm.emit_label_rel(end_label, here_offset=-4)
        # The negative-amount trap, laid out after the saturating arm so both
        # arms are reached by one short forward branch and neither falls into
        # the other. Darwin arm64 exit(status): x16 = SYS_exit, x0 = status,
        # svc #0x80 — the same three instructions, and the same status, as the
        # divide-by-zero arm of `_emit_div_shift_pow` above.
        self.asm.label(neg_label)
        self.asm.emit(encode_movz_xd_imm(0, M.SHIFT_TRAP_STATUS))
        self.asm.emit(encode_movz_xd_imm(16, 1))
        self.asm.emit(encode_svc(0x80))
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
        if isinstance(e, F.BinaryOp) and e.op in ("+", "|", "*", "or", "and"):
            return (self._is_container_expr(e.left)
                    or self._is_container_expr(e.right))
        if isinstance(e, F.IdentExpr):
            return e.name in self._blob_vars
        return False

    def _blob_est(self, e) -> int:
        """Static upper bound on element count for frame reservation."""
        if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            # `list_literal_reserved_slots`, NOT `len(e.elements)`: a literal
            # with a `*` operand builds its blob by appending and so occupies
            # the cap it reserved, while `len(elements)` counts the `*a` as ONE
            # element. Measured: `[1, 2] + [*c]` with `c = [7, 8, 9]` estimated
            # 3 elements for a 5-element result, and x86-64 — which checks the
            # run-time total against this estimate rather than trusting it —
            # stopped at the overflow guard. One rule with the two other places
            # a splat literal's size is needed.
            return M.list_literal_reserved_slots(e)
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
        if isinstance(e, F.BinaryOp) and e.op == "*":
            # REPETITION: len(blob) x count. The count has to be the literal the
            # emitter requires (`_emit_list_repeat` refuses anything else), so
            # the reservation is the product rather than the 64 an unknown
            # side gets below — over-reserving is the safe direction here,
            # since it is `frame_blob_refusal` at the end of the frame either
            # way.
            blob, count = ((e.left, e.right)
                           if self._is_container_expr(e.left)
                           else (e.right, e.left))
            n = self._static_int(count)
            if n is None:
                return 64
            return max(0, self._blob_est(blob) * max(0, n))
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
        # i >= nL leaves the loop, so the branch is on NON-zero.  `cbz` here
        # left on the FIRST iteration for every input, and a copy loop that
        # copies nothing is invisible from outside: the count word is written
        # from nL + nR beforehand, so `len(a + b)` was right and every element
        # of the result read 0 — `sum([1, 2] + [3])` answering 0.
        self.asm.emit(encode_cmp_xn_xm(5, 2))
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 0))
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
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(crd, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(0, 8, 8))
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 5))
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))
        self._emit_list_base(offset)
        self.asm.emit(encode_add_xd_xn_imm(6, 9, 8))
        # + 8*nL, SCALED: the left loop wrote nL elements, so the right one
        # starts nL ELEMENTS further on.  `add x6, x6, x2` added nL BYTES, and
        # the first right-hand element landed six bytes into the left's last
        # one — which is how a correct count and a correct-looking `len`
        # still produced `sum([1, 2] + [3]) == 196609`.
        self.asm.emit(encode_add_xd_xn_xm_lsl3(6, 6, 2))  # + 8*nL
        self.asm.emit(encode_add_xd_xn_xm_lsl3(6, 6, 5))
        self.asm.emit(encode_str_xt_xn_imm(0, 6, 0))
        self.asm.emit(encode_add_xd_xn_imm(5, 5, 1))
        self._emit_b_to(cr)
        self.asm.label(crd)
        self._emit_list_base(offset)
        self.asm.emit(encode_mov_zr_xn(0, 9))

    def _emit_list_repeat(self, blob, count) -> None:
        """`xs * n` as a list-blob REPETITION → base pointer in X0.

        The construct was not lowered at all before this: `*` reached the
        integer ALU with both operands still holding blob ADDRESSES, so
        `C = [7] * 4` bound `C` to `7*4` scaled by eight — the address of
        nothing — and every read through it walked a count at that address.
        Measured on both architectures before this emitter, on one program per
        architecture: `C = [7] * 4` then `for x in C: n = n + 1` built, ran, and
        died with SIGSEGV (exit 139) where CPython counts 4. A build that
        succeeds and then crashes is the worst of the three answers this
        backend can give, so it was worth the emitter rather than a refusal.

        Two loops and no division: `k` over the repetitions and `i` over the
        source's elements, with `X10` holding `k*nL` so the destination is
        `base + 8 + 8*(X10 + i)` without a multiply. The source blob is read
        through its own count word, so the answer is right for a blob whose
        length this path did not know statically either — the reservation below
        is the estimate and the loop is the truth.

        `count` is the literal: `_emit_binop` refuses a repetition whose count
        it cannot read (`model.list_repeat_count_refusal`), because the
        reservation is made before anything runs and there is no heap to grow
        into afterwards.
        """
        est = max(0, self._blob_est(blob) * max(0, count))
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(M.frame_blob_refusal(
                "a list repetition", self._list_cursor + 8, self._blob_cap))
        cap = max(1, min(est, (avail - 8) // 8))
        self._emit_expr(blob)
        self.asm.emit(encode_stp_sp_pre(0, 2))          # blob
        self._emit_mov_imm("X0", max(0, count))
        self.asm.emit(encode_stp_sp_pre(0, 2))          # count, blob
        # A nested emit above may have advanced the cursor — re-clamp.
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(M.frame_blob_refusal(
                "a list repetition", self._list_cursor + 8, self._blob_cap))
        cap = max(1, min(est, (avail - 8) // 8))
        offset = self._list_cursor
        self._list_cursor += 8 + 8 * cap
        self.asm.emit(encode_ldr_xt_xn_imm(8, 31, 0))    # count (top of stack)
        self.asm.emit(encode_ldr_xt_xn_imm(7, 31, 16))   # blob
        self.asm.emit(encode_ldp_sp_post(0, 31))         # drop count
        self.asm.emit(encode_ldp_sp_post(0, 31))         # drop blob
        self.asm.emit(encode_ldr_xt_xn_imm(2, 7, 0))     # nL
        self._emit_list_base(offset)                     # X9 = result base
        self.asm.emit(encode_movz_xd_imm(5, 0))           # k = 0
        self.asm.emit(encode_movz_xd_imm(10, 0))          # k*nL = 0
        self._while_counter += 1
        ck = f"{self.func_name}_rep{self._while_counter}"
        ckd = f"{ck}d"
        self.asm.label(ck)
        self.asm.emit(encode_cmp_xn_xm(5, 8))            # k >= count
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(ckd, here_offset=-4)
        self.asm.emit(encode_movz_xd_imm(6, 0))           # i = 0
        self._while_counter += 1
        ci = f"{self.func_name}_repi{self._while_counter}"
        cid = f"{ci}d"
        self.asm.label(ci)
        self.asm.emit(encode_cmp_xn_xm(6, 2))            # i >= nL
        self.asm.emit(encode_cset_xd_cond(0, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 0))
        self.asm.emit_label_rel(cid, here_offset=-4)
        self.asm.emit(encode_add_xd_xn_imm(0, 7, 8))     # src = blob + 8
        self.asm.emit(encode_add_xd_xn_xm_lsl3(0, 0, 6))  # + 8*i
        self.asm.emit(encode_ldr_xt_xn_imm(0, 0, 0))
        self.asm.emit(encode_add_xd_xn_imm(1, 9, 8))     # dst = base + 8
        self.asm.emit(encode_add_xd_xn_xm_lsl3(1, 1, 10))  # + 8*k*nL
        self.asm.emit(encode_add_xd_xn_xm_lsl3(1, 1, 6))  # + 8*i
        self.asm.emit(encode_str_xt_xn_imm(0, 1, 0))
        self.asm.emit(encode_add_xd_xn_imm(6, 6, 1))
        self._emit_b_to(ci)
        self.asm.label(cid)
        self.asm.emit(encode_add_xd_xn_xm(10, 10, 2))    # k*nL += nL
        self.asm.emit(encode_add_xd_xn_imm(5, 5, 1))     # k += 1
        self._emit_b_to(ck)
        self.asm.label(ckd)
        # The count word is len(blob) * count, computed from the two counts the
        # loops used, so `len(xs * n)` is the number of elements the copy
        # actually wrote rather than the count operand.
        self.asm.emit(encode_mul_xd_xn_xm(0, 2, 8))
        self.asm.emit(encode_str_xt_xn_imm(0, 9, 0))
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
        # THE COUNT IS nL, NOT nL + nR, and the two are indistinguishable in
        # every shape that only ITERATES the result — which is why the wrong one
        # was here so long.  The result starts out holding the nL left-hand
        # elements and NOTHING else, so the count that describes it is nL; the
        # dedup loop below grows it by one per element it actually appends.
        #
        # With nL + nR written here, `len` and a subscript both read a number no
        # store produced: `{1,2} | {2,3}` had count 4 over the three words
        # [1, 2, 3] and two unwritten ones, then appended `3` at index 4 and
        # made the count 5.  Measured, `printf("len=%d", len({1,2}|{2,3}))`:
        # arm64 5, CPython 3; `c[0], c[1], c[2]` was 1, 2, 0.  Iterating the
        # same blob read all five slots and summed 6, which is the right answer
        # from the right three elements and two zeros — so a case that walks the
        # union cannot see this, and the existing one could not either.
        #
        # `est` above stays the sum, because it is a RESERVATION: nL + nR is how
        # many words the result can need, and the reservation is what keeps the
        # append loop's `result[count]` store inside the blob.
        self.asm.emit(encode_mov_zr_xn(4, 2))            # n = nL (elements present)
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
        self.asm.emit(encode_cbnz_xn(0, 0))          # i >= nL → done
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
        #
        # BOTH SIDES ARE DECODED before the substring test, and that is what
        # keeps the constant and the call agreeing now that the call's operands
        # are interned decoded text. `"t" in "\t"` is a needle of `t` against a
        # haystack of one TAB, so it is FALSE; folding it on the raw source text
        # made it TRUE, because the raw haystack is a backslash and a `t` and
        # contains a `t`. Measured: `str_membership_two_literals`-shaped programs
        # disagreed between the literal fold and the same expression with a name
        # in it. `fire_compiler.decode_c_escapes` is the one decoder, the same
        # one `_intern_string` below uses — see
        # FORMAL_string_literal_escape_is_not_decoded.
        if isinstance(left, F.StringLiteral) and isinstance(right, F.StringLiteral):
            # The EMPTY needle is TRUE, which is Python's rule and what
            # `strstr` returns for it (the haystack itself, non-NULL). Folding
            # it to False because `bool("")` is False made the
            # both-operands-literal case disagree with the call the same
            # expression makes when either side is a name.
            needle = F.decoded_literal(left)
            haystack = F.decoded_literal(right)
            found = needle == "" or needle in haystack
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
                raise CodegenError(M.frame_blob_refusal(
                    "a range() literal", self._list_cursor + size,
                    self._blob_cap))
            offset = self._list_cursor
            self._list_cursor += size
            self._emit_list_base(offset)
            self._emit_mov_imm("X10", n)
            self.asm.emit(encode_str_xt_xn_imm(10, 9, 0))
            for i, val in enumerate(vals):
                self._emit_mov_imm("X0", val)
                self._emit_list_base(offset)
                self._emit_blob_store(9, 8 * (i + 1), 0)
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

        The SubscriptExpr arm below used to sit UNDER the SliceExpr arm's
        `continue`, so every subscript target fell off the end of the loop body
        and emitted no instructions at all: `del lst[0]` and `del lst[1:3]`
        built, ran, exited 0, and removed nothing, on both list and dict
        (`len(a)` still 3, `a[0]` still 10). A silent no-op where the source
        says "remove" is the one outcome this backend may not produce, and the
        four `_emit_del_*` helpers it needed were dead code behind that one
        `continue` — written, reviewed, and stranded.

        A multi-element subscript index is refused BEFORE the branches below,
        for the same reason: `del a[i, j]` is not one of the three lowered
        shapes, and the refusal belongs where the shape is still visible.

        The shapes this cannot lower are refused through the shared
        `M.del_refusal`, so this backend and its x86-64 twin say the same
        words about the same source."""
        for target in stmt.targets:
            if isinstance(target, (F.IdentExpr, F.MemberExpr)):
                continue
            if isinstance(target, F.SubscriptExpr) and (
                    M.is_multi_index(target.index)
                    or M.is_mlir_template(target)):
                why = M.multi_index_refusal_for(
                    target, self._is_dict_subscript(target.obj),
                    self._functions, self._structs)
                raise CodegenError(
                    f"del {why}" if why is not None else
                    "del on a subscript with a tuple index is not supported "
                    "on the formal arm64 path")
            why = M.del_refusal(
                target,
                self._is_string_subscript(target.obj)
                if isinstance(target, F.SubscriptExpr) else False,
                self._del_base_is_pointer(target))
            if why is not None:
                raise CodegenError(why)
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
                self._emit_del_list_index(target)
                continue
            # Dict/list slot behind a bare MemberExpr base is handled
            # above via _member_slot_key; unknown shapes fall through.
            raise CodegenError(
                f"unsupported del target on the formal arm64 path "
                f"(got {type(target).__name__})")

    def _del_base_is_pointer(self, target) -> bool:
        """Whether `target`'s base is a POINTER rather than a container.

        The READ path's own question — `subscript_base_lowering`, which answers
        `"load"` for a pointer whose pointee width this module established —
        asked here so `del` over a `Pointer` is refused instead of taking the
        buffer's first word for a count. A `SliceExpr` target has the same base
        as a subscript, and `del p[0:2]` is the same mistake with two bounds.
        """
        obj = getattr(target, "obj", None)
        if obj is None:
            return False
        shape, _width, _signed, _why = M.subscript_base_lowering(
            self._cur_fn, obj, self._structs, self._functions, self._structs)
        return shape == "load"

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
        # `CBNZ` and not `CBZ`: the exit is the `>= count` case, and the
        # scanner in `_emit_dict_lookup_addr` spells the same test the same
        # way. With `CBZ` the loop left before its own body on every
        # iteration, so the count came down and the elements did not move —
        # `del a[0]` on `[10, 20, 30]` printed `2 10`, which is a shorter
        # list rather than a removal. Invisible until now only because
        # nothing reached this function (see `_emit_del`).
        self.asm.emit(encode_cmp_xn_xm(3, 1))
        self.asm.emit(encode_cset_xd_cond(4, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 4))
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
        # `CBNZ`, matching the scan loop above: `j >= count` is the exit.
        self.asm.emit(encode_cmp_xn_xm(2, 1))
        self.asm.emit(encode_cset_xd_cond(3, "ge"))
        self.asm.emit(encode_cbnz_xn(0, 3))
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

        Bounds are Python-normalized: a negative bound gains the count, one
        still negative after that clamps to 0, `stop` clamps to
        [start, count], and start >= stop removes nothing. Callers reject a
        step.

        TWO THINGS THIS FUNCTION HAD WRONG, both of them measured, and both of
        them invisible while the function was unreachable.

        **The branches were backwards.** Each test is spelled
        `cset X3, <cond>` then a `CBZ`/`CBNZ X3` that `emit_label_rel` points
        at the SKIP label — so the body runs when the condition is TRUE. The
        previous version wrapped that in an extra unconditional `encode_b(0)`,
        which inverts it: with `cset X3, lt` and `CBNZ X3, #0` followed by
        `B <clamp-to-zero>`, a NON-negative bound went to the clamp and a
        negative one was wrapped. So `del lst[1:3]` normalized `start` to 0
        and then `stop = max(stop, start)` took it the other way, `n_del`
        came out 0, and the list was unchanged — the silent no-op this whole
        construct is about, reached for a second time and by a different
        route. `_emit_slice_store` above is the same normalization written the
        other way round, and that one works.

        **The base and the count were live across the bound EXPRESSIONS.**
        `X10` (base) and `X1` (count) were loaded first and the bounds were
        evaluated afterwards, and a bound is where a call, a nested
        subscript or a blob materialization runs — any of which writes
        scratch registers. They are pushed here instead, and the copy loop
        reloads them, which costs two loads and removes the question.
        """
        if step is not None:
            raise CodegenError(
                "del slice with step is not supported on the formal arm64 "
                "path")
        self._load_var(name, 10)                       # X10 = base
        self.asm.emit(encode_ldr_xt_xn_imm(1, 10, 0))  # X1 = count
        self.asm.emit(encode_stp_sp_pre(1, 31))        # [SP+0] count
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        # --- start index → X2 ---
        # ALWAYS pushed, omitted bound included: the count sits at [SP+16]
        # once start is on the stack, and a conditional push would make every
        # later offset conditional too (`del lst[:2]` read the count out of
        # the slot `start` had not taken and removed nothing).
        if start is None:
            self.asm.emit(encode_movz_xd_imm(2, 0))
        else:
            self._emit_expr_to(start, "X2")
            self._emit_slice_bound_normalize(2, 0)
        self.asm.emit(encode_stp_sp_pre(2, 31))         # [SP+0] start
        # --- stop index → X4 ---
        if stop is None:
            self.asm.emit(encode_ldr_xt_xn_imm(4, 31, 16))   # stop = count
        else:
            self._emit_expr_to(stop, "X4")
            self._emit_slice_bound_normalize(4, 16)
            self.asm.emit(encode_ldr_xt_xn_imm(2, 31, 0))    # start
        # stop = min(stop, count)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 31, 16))  # X1 = count
        self.asm.emit(encode_cmp_xn_xm(4, 1))
        self.asm.emit(encode_cset_xd_cond(3, "hi"))      # 1 when stop > count
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(f"{fn}_dru{wid}", here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(4, 1))           # stop = count
        self.asm.label(f"{fn}_dru{wid}")
        # stop = max(stop, start)  (empty when stop <= start)
        self.asm.emit(encode_cmp_xn_xm(4, 2))
        self.asm.emit(encode_cset_xd_cond(3, "lt"))      # 1 when stop < start
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(f"{fn}_drv{wid}", here_offset=-4)
        self.asm.emit(encode_mov_zr_xn(4, 2))           # stop = start
        self.asm.label(f"{fn}_drv{wid}")
        # n_del = stop - start; if 0 → done
        self.asm.emit(encode_sub_xd_xn_xm(5, 4, 2))
        self.asm.emit(encode_cmp_xn_imm(5, 0))
        self.asm.emit(encode_cset_xd_cond(3, "eq"))
        self._while_counter += 1
        dskip = f"{fn}_drs{self._while_counter}"
        self.asm.emit(encode_cbnz_xn(0, 3))
        self.asm.emit_label_rel(dskip, here_offset=-4)
        # The bounds may have clobbered the base and the count; both are on the
        # stack, so reload rather than trust the registers.
        self._load_var(name, 10)
        self.asm.emit(encode_ldr_xt_xn_imm(1, 10, 0))
        # copy [stop, count) → [start, start + (count - stop))
        self.asm.emit(encode_mov_zr_xn(6, 4))             # j = stop
        self._while_counter += 1
        mloop = f"{fn}_drm{self._while_counter}"
        mend = f"{fn}_dre{self._while_counter}"
        self.asm.label(mloop)
        self.asm.emit(encode_cmp_xn_xm(6, 1))
        self.asm.emit(encode_cset_xd_cond(3, "ge"))      # 1 when j >= count
        self.asm.emit(encode_cbnz_xn(0, 3))
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
        # pop start and count — on BOTH paths, `dskip` included, because the
        # push above is unconditional and a pop that only sometimes happens is
        # a stack that only sometimes comes back.
        self.asm.emit(encode_ldp_sp_post(2, 31))
        self.asm.emit(encode_ldp_sp_post(1, 31))

    def _emit_slice_bound_normalize(self, reg: int, count_off: int) -> None:
        """Python's negative-index rule for one slice bound, in `reg`.

        A negative bound gains the count; one still negative after that
        clamps to 0, because `del lst[-99:2]` on a four-element list removes
        two elements and not the whole list. `count_off` is the byte offset
        from SP of the count pushed by the caller, so this is safe to run
        between two bound EXPRESSIONS — which may write any scratch register.

        The idiom is `_emit_slice_store`'s, which is the one in this file that
        runs: `cset` the condition, `CBZ` past the body, and point the `CBZ`
        at the label after it. Everything about `del` that was wrong was this
        shape spelled the other way round.
        """
        self._while_counter += 1
        w = self._while_counter
        fn = self.func_name
        wrapped = f"{fn}_drw{w}"
        clamped = f"{fn}_drcl{w}"
        self.asm.emit(encode_cmp_xn_imm(reg, 0))
        self.asm.emit(encode_cset_xd_cond(3, "lt"))
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(wrapped, here_offset=-4)
        self.asm.emit(encode_ldr_xt_xn_imm(17, 31, count_off))   # X17 = count
        self.asm.emit(encode_add_xd_xn_xm(reg, reg, 17))
        self.asm.label(wrapped)
        self.asm.emit(encode_cmp_xn_imm(reg, 0))
        self.asm.emit(encode_cset_xd_cond(3, "lt"))
        self.asm.emit(encode_cbz_xn(0, 3))
        self.asm.emit_label_rel(clamped, here_offset=-4)
        self.asm.emit(encode_movz_xd_imm(reg, 0))
        self.asm.label(clamped)


def _always_returns(stmts: list) -> bool:
    """Whether a statement list provably returns on every path.

    ITERATIVE over the sibling stream, recursive only into the branches of a
    compound statement.  That split is not a style choice: the previous
    version recursed once per SIBLING (`return _always_returns(rest)`), so a
    function of N statements needed N Python frames and a straight-line
    `main` of a little over a thousand statements died with a bare
    `RecursionError` — the whole diagnostic, naming a function whose name
    says nothing about the program.  A generated program is exactly that
    shape (a few hundred `printf` calls in one function), and the sibling
    count is unbounded where the block NESTING depth is not, so the limit
    was an artefact of the walk rather than a property of the analysis.

    The predicate is unchanged, statement for statement: a `return` answers
    True; an `if` answers True when every one of its branches does, and
    otherwise falls through to the statements after it; a loop always falls
    through, because its body may not run.  An `if` with neither `elif`s nor
    an `else` has one branch, cannot answer for all of them, and falls
    through — which is why the branch count is the test, and why an EMPTY
    `else_body` (`[]`, not `None`) is still no `else`."""
    cur = stmts or []
    i, n = 0, len(cur)
    while i < n:
        st = cur[i]
        i += 1
        if isinstance(st, F.ReturnStmt):
            return True
        if isinstance(st, F.IfStmt):
            branches = [st.then_body]
            branches += [b for _c, b in (st.elifs or [])]
            if st.else_body:
                branches.append(st.else_body)
            # Fewer than two branches: the `if` can fall through, so it says
            # nothing about the statements after it — the same answer the
            # recursive walk gave, reached a different way.
            if len(branches) >= 2 and all(_always_returns(b) for b in branches):
                # All branches return — but statements after the if still
                # matter, and a list that ends here has reached its end.
                if i >= n:
                    return True
        # A loop, an `if` that falls through, and anything else all answer
        # the same question: is there a `return` later in this list?
    return False


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
