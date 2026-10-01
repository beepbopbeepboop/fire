#!/usr/bin/env python3
"""x86-64 code generator for the formal path — consumes fire_compiler's AST.

Maps fire_compiler nodes (the project's real AST; fire_compiler.py is the
single source of truth) to x86-64 machine code, using the System V AMD64
integer convention so the extern path needs no thunk:
- arguments: RDI, RSI, RDX, RCX, R8, R9
- return value: RAX
- locals: RBX, R12, R13, R14, R15 (callee-saved), overflow to RBP-relative
  spill slots
- expression temporaries: RAX (result), R10/R11 (scratch), RDX:RAX for the
  one-operand divide forms
- frame pointer: RBP; the stack grows down

Ported from /Users/mrs/net/chatgpt/claude/formal/compiler/codegen.py (the toy
formal compiler's x86-64 backend) and re-targeted from that project's mini-AST
onto fire_compiler nodes, mirroring formal/arm64_codegen.py's structure and
its `compile()` contract. That toy's register handling collapsed every local
onto RBX and its variable reads returned the last assignment rather than the
named one; the register allocation here is the same shape the arm64 backend
uses (locals in callee-saved registers, spill slots past the fifth).

Scope: the integer/boolean surface — literals, variables, the arithmetic and
bitwise operators, comparisons and compare chains, short-circuit and/or,
if/elif/else, while, for over range(), break/continue, augmented assignment,
recursion, and calls out to externs. Container and string values (lists,
dicts, sets, comprehensions, subscripts, slices, string literals) are NOT
lowered here: they need a heap/blob runtime that the toy x86-64 path never
had and that the proof model in lib/ProofLib.lean does not describe. They
raise CodegenError naming the construct rather than silently miscompiling.
"""

from formal.types import (IntType, DEFAULT_INT_TYPE, function_var_types,
                          common_type, infer_expr, resolve, cmp_signed,
                          parse_type_name, mask_of, TYPE_NAMES,
                          STRING_TYPE_NAMES)
from formal.x86_64 import *  # noqa: F401,F403 — encoders, Reg, Assembler

import fire_compiler as F
import mojo.middle.comptime as comptime_eval
from formal import model as M
from formal.model import CodegenError, IDENTITY_TYPE_CTORS
from mojo.middle.boundnames import bound_names_in_order

# Bytes of stack the frame always reserves BELOW the spill slots: expression
# temporaries live in 16-byte slots (see _push_slot), and a function that used
# none would otherwise be sitting exactly at the spill area.
_TEMP_SLACK = 256

# Sizes of the push/pop slots the codegen uses. Both are 16 bytes so that RSP
# is 16-byte aligned at every point where a CALL can happen — the System V AMD64
# requirement, and the thing an SSE-using or variadic callee (a libc `printf`)
# will fault on if it is violated. A left operand or an argument therefore
# occupies a whole 16-byte slot, not 8: the low 8 bytes hold the value and the
# high 8 are padding.
_SLOT = 16

# Bytes of frame reserved for container blobs (list/tuple/dict pair blobs,
# comprehension results, slice views). A blob is [count:i64][element…], built
# in the frame rather than on a heap — formal has no allocator — and lives
# until the function returns. The cursor grows UP from the frame bottom (so a
# nested container sits above its parent, as in the arm64 backend) and is
# capped just below the spill/saved-register area.
_BLOB_BYTES = 16384

# Condition-code pairs for the six comparisons, as (unsigned, signed) setcc
# mnemonics. The literal's type picks the row: `int` is unsigned 64-bit, so
# `n < 0` on an unannotated parameter is an unsigned comparison — the same
# lattice formal/types.py encodes and the arm64 backend follows.
_CMP_CONDS = {
    "<=": ("setbe", "setle"),
    "<": ("setb", "setl"),
    ">=": ("setae", "setge"),
    ">": ("seta", "setg"),
    "==": ("sete", "sete"),
    "!=": ("setne", "setne"),
    # Identity on the formal path is unboxed integer value equality (no heap
    # objects, no interning table) — same reading the arm64 backend uses.
    "is": ("sete", "sete"),
    "is not": ("setne", "setne"),
}
_SETCC = {
    "sete": encode_sete, "setne": encode_setne, "setl": encode_setl,
    "setle": encode_setle, "setg": encode_setg, "setge": encode_setge,
    "setb": encode_setb, "setbe": encode_setbe, "seta": encode_seta,
    "setae": encode_setae,
}
_ALU_RR = {
    "+": encode_add_r64_r64,
    "-": encode_sub_r64_r64,
    "*": encode_imul_r64_r64,
    "&": encode_and_r64_r64,
    "|": encode_or_r64_r64,
    "^": encode_xor_r64_r64,
}
_SHIFT_IMM = {"<<": "<<", ">>": ">>"}
_SHIFT_CL = {"<<": "<<", ">>": ">>signed"}


def _always_returns(stmts: list) -> bool:
    """Whether every path through `stmts` ends in a return.

    Drives the implicit `return 0` a function needs so execution cannot fall
    off the end of the body into whatever follows it in .text."""
    for s in stmts or []:
        if isinstance(s, F.ReturnStmt):
            return True
        if isinstance(s, F.RaiseStmt):
            return True
        if isinstance(s, F.IfStmt):
            branches = [s.then_body] + [b for _c, b in (s.elifs or [])]
            if s.else_body:
                branches.append(s.else_body)
            # An elif chain with no final else has a reachable fall-through,
            # so it does not count as always returning.
            if len(branches) < 2:
                continue
            if all(_always_returns(b) for b in branches):
                return True
        if isinstance(s, F.WhileStmt):
            # `while True:` with no break never falls through.
            cond = s.condition
            if (isinstance(cond, F.BoolLiteral) and cond.value) \
                    and not _has_break(s.body):
                return True
        if isinstance(s, F.TryStmt):
            if _always_returns(s.body) and _always_returns(s.finally_body or []):
                return True
    return False


def _has_break(stmts: list) -> bool:
    """Whether `stmts` contains a `break` that belongs to THIS loop.

    A break inside a nested loop belongs to that loop, so the walk does not
    descend into one."""
    for s in stmts or []:
        if isinstance(s, F.BreakStmt):
            return True
        if isinstance(s, F.IfStmt):
            if _has_break(s.then_body):
                return True
            for _c, body in (s.elifs or []):
                if _has_break(body):
                    return True
            if _has_break(s.else_body):
                return True
        if isinstance(s, F.TryStmt):
            if _has_break(s.body):
                return True
    return False


def _range_args(iterable):
    """range(...) arguments from a fire ForStmt iterable, else None."""
    if (isinstance(iterable, F.CallExpr)
            and isinstance(iterable.func, F.IdentExpr)
            and iterable.func.name == "range"):
        return list(iterable.args)
    return None


def _collect_var_names(f: F.FunctionDef) -> list:
    """Parameters first, then locals in first-assignment order.

    The bound names come from the shared middle-end walk
    (`bound_names_in_order`) — the same list the arm64 backend allocates from,
    so a name that is a local here is a local there. The only additions are
    the loop control temps, which are backend-local (they hold a loop's bound,
    step, index or iterable pointer, not a source-level value) and are
    appended after every real name so they only ever spill.
    """
    names = bound_names_in_order(f.body, f.params)
    seen = set(names)

    def walk(stmts, depth: int, acc: list) -> None:
        """Track the deepest loop nesting, whatever kind.

        EVERY loop consumes a depth, range() included: `_emit_loop` indexes
        its `_fe{d}`/`_fs{d}` bound/step temps with the same counter
        `_emit_for_list` uses for `_fi{d}`/`_fb{d}`, and both need a fresh
        index inside a nested loop or they would collide with the enclosing
        one's. So this walk counts loops, not kinds — an earlier version that
        let a range() loop share its parent's depth built the temp list for
        the wrong function and failed at emit time with "no home for _fb1"."""
        for s in stmts or []:
            if isinstance(s, F.ForStmt):
                acc[0] = max(acc[0], depth)
                walk(s.body, depth + 1, acc)
                walk(s.else_body, depth + 1, acc)
            elif isinstance(s, F.IfStmt):
                walk(s.then_body, depth, acc)
                for _c, body in (s.elifs or []):
                    walk(body, depth, acc)
                walk(s.else_body, depth, acc)
            elif isinstance(s, F.WhileStmt):
                walk(s.body, depth, acc)
                walk(s.else_body, depth, acc)
            elif isinstance(s, F.TryStmt):
                walk(s.body, depth, acc)
                for h in (s.handlers or []):
                    walk(h.body, depth, acc)
                walk(s.else_body, depth, acc)
                walk(s.finally_body, depth, acc)
            elif isinstance(s, F.WithStmt):
                walk(s.body, depth, acc)

    acc = [-1]
    walk(f.body, 0, acc)
    if acc[0] >= 0:
        # All four loop-temp families for every depth: the emitter indexes
        # them with one counter, so a depth only used by a range() loop may
        # still need the _fi/_fb pair reserved (and vice versa).
        for i in range(acc[0] + 1):
            for name in (f"_fe{i}", f"_fs{i}", f"_fi{i}", f"_fb{i}"):
                if name not in seen:
                    seen.add(name)
                    names.append(name)

    # Comprehension generator loops: one index + one iterable-pointer temp per
    # generator, counted from a base depth that leaves the for-in temps alone
    # (so a comprehension inside a for, or the reverse, cannot alias).
    def walk_compr(node, depth: int, acc: list) -> None:
        if node is None or isinstance(node, (str, int, float, bool)):
            return
        if isinstance(node, F.Comprehension):
            n = len(node.generators or [])
            if n:
                acc[0] = max(acc[0], depth + n - 1)
            for g in node.generators or []:
                walk_compr(g.iterable, depth, acc)
                for c in g.conditions or []:
                    walk_compr(c, depth + n, acc)
            walk_compr(node.element, depth + n, acc)
            walk_compr(node.key, depth + n, acc)
            return
        if hasattr(node, "__dataclass_fields__"):
            for fname in node.__dataclass_fields__:
                if fname in ("line", "col"):
                    continue
                val = getattr(node, fname, None)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, tuple):
                            for y in item:
                                walk_compr(y, depth, acc)
                        else:
                            walk_compr(item, depth, acc)
                elif isinstance(val, tuple):
                    for y in val:
                        walk_compr(y, depth, acc)
                else:
                    walk_compr(val, depth, acc)

    acc_c = [-1]
    for st in (f.body or []):
        walk_compr(st, 0, acc_c)
    if acc_c[0] >= 0:
        for i in range(acc_c[0] + 1):
            for name in (f"_ci{i}", f"_cb{i}"):
                if name not in seen:
                    seen.add(name)
                    names.append(name)
    return names


def var_register_map(f: F.FunctionDef) -> dict[str, Reg]:
    """Variable -> callee-saved register, matching `_emit_function`.

    Exported for a future proof generator, the way formal/arm64_codegen.py
    exports its own `var_register_map`: per-value facts have to name the
    register the codegen actually allocated. Only the first
    `len(CALLEE_SAVED)` names appear — the rest live in spill slots."""
    names = _collect_var_names(f)
    return {name: CALLEE_SAVED[i]
            for i, name in enumerate(names[:len(CALLEE_SAVED)])}


def _with_item_alias_name(alias) -> str:
    """The local name a `with ... as NAME` binds, or None."""
    from mojo.middle.boundnames import _with_item_alias_name as _impl
    return _impl(alias)


def _callee_symbol(func) -> str | None:
    """Flatten a CallExpr callee to a symbol name string.

    IdentExpr → its name; MemberExpr → the dotted chain (`obj.method` →
    "obj.method", `os.path.join` → "os.path.join"). A dotted name is never in
    `self._functions`, so `_emit_call` lowers it to a call to that extern —
    which is how a module-level or method call reaches the C library. Same
    reading as the arm64 backend, so the two agree on what a callee name is.
    """
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
    `"a.b.c"`); None when the root is not a plain name (a call result, etc.).

    A formal value is one word, so each named-base field of a struct is a
    distinct int64 local; this is the name that field has."""
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
    function's body. The nested FunctionDef itself IS yielded."""
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
    """(node, receiver, method, args) for every `recv.method(...)` in `fn`."""
    for node in _walk_ast(getattr(fn, "body", None) or []):
        if (isinstance(node, F.CallExpr)
                and isinstance(node.func, F.MemberExpr)):
            yield (node, node.func.obj, node.func.member, list(node.args))


def _binds_name(target, name: str) -> bool:
    """Whether an assignment target introduces the local `name`."""
    if isinstance(target, F.IdentExpr):
        return target.name == name
    if isinstance(target, (F.TupleExpr, F.ListExpr)):
        return any(_binds_name(el, name) for el in target.elements)
    if isinstance(target, str):
        from mojo.middle.boundnames import _lbn_target_names
        return name in _lbn_target_names(target)
    return False


def _list_literals_bound_to(fn, name: str) -> list:
    """Every list literal in `fn` that assigns to `name`."""
    out = []
    for node in _walk_ast(getattr(fn, "body", None) or []):
        if isinstance(node, F.AssignStmt) and _binds_name(node.target, name) \
                and isinstance(node.value, F.ListExpr):
            out.append(node.value)
        elif isinstance(node, F.VarDecl) and node.name == name \
                and isinstance(node.value, F.ListExpr):
            out.append(node.value)
    return out


def _dotted(func) -> str:
    """`recv.method` as written, for a diagnostic that quotes the source."""
    name = _callee_symbol(func)
    return name if name else type(func).__name__


def _call(name: str, args: list):
    """A synthesized CallExpr for a builtin lowered into another call.

    `print` is lowered by rewriting it into a `printf` call, and building that
    call as an AST node (rather than special-casing printf inside the argument
    shuffle) means it goes through exactly the path a printf written by hand
    does — same argument registers, same variadic convention, same return."""
    return F.CallExpr(func=F.IdentExpr(name=name), args=list(args))


class X86_64Codegen:
    """x86-64 code generator over the fire_compiler AST."""

    def __init__(self, test_input: int = 10, extern_style: str = "stub",
                 dylib_syms: dict = None, comptime_hook=None,
                 module_source: str = "", dylib_exports: list = None):
        """test_input: the value the startup stub passes to the entry.

        extern_style: how a call to an unbound symbol is emitted.
          "stub" — `call rel32` to a __TEXT,__stubs trampoline that jumps
            through a GOT slot. What the Mach-O image carries, and what
            `formal.macho.compute_macho_got_addrs` hands back to
            `Assembler.resolve_extern`.
          "got" — `call [rip+disp32]` straight through the GOT slot, which
            needs no stub section. What the ELF image carries
            (`formal.elf.compute_got_addrs`), matching the toy x86-64 path
            this was ported from.

        dylib_syms: {source-level callee name: the spelling a linked formal
        dylib exports it under}. A call whose callee is not defined in this
        module but appears here is emitted against the mangled spelling, so
        the recorded extern symbol is the one the linked dylib actually
        defines. Built by formal.build._codegen_and_link from the dylib
        manifests.

        comptime_hook / module_source: the compile-time evaluation hook
        `(name, args) -> int | None` built by
        `formal.comptime_runner.make_call_hook`, and the module's own source.
        ACCEPTED AND STORED, NOT YET USED: the arm64 backend folds these into
        comptime specialization (a `f[x]` subscript call whose arguments are
        all compile-time constants is expanded inline instead of called), and
        this backend has no specialization pass yet, so every call still
        lowers to a real `call`. Nothing here silently pretends to specialize
        — a comptime-parameterized call is emitted as an ordinary call, which
        runs correctly as long as the callee is a real function.
        """
        if extern_style not in ("stub", "got"):
            raise CodegenError(
                f"unknown extern_style {extern_style!r} (expected stub|got)")
        self.test_input = test_input
        self.extern_style = extern_style
        self._dylib_syms = dict(dylib_syms or {})
        # The same libraries' MANIFEST export entries, in the same order
        # `_dylib_syms` was built in, indexed flat by bare name (so a bare
        # callee resolves to the entry `_dylib_syms` resolved it to, by
        # construction rather than by a second copy of the same precedence
        # rule) and by module identity, which is what makes `mod.f(...)` — the
        # spelling `import mod` binds — resolve. The entry carries the declared
        # signature, so a call's result can be classified instead of guessed.
        # The same three tables, and the same `model.dylib_export_lookup`, as
        # the arm64 backend: one contract, two emitters. The third is the
        # names a module publishes by RE-EXPORT rather than by definition, and
        # all three come from `model.dylib_export_tables` — the one builder,
        # because the indexing was two copies of the same three questions,
        # which is two places for them to disagree about which library owns a
        # name.
        (self._dylib_by_name, self._dylib_by_module,
         self._dylib_forwarded) = M.dylib_export_tables(dylib_exports)
        self._comptime_hook = comptime_hook
        self._module_source = module_source
        self.asm = Assembler()


        self._functions = {}
        self._current_function = None
        # The FUNCTION NODE, not just its name — the pointer value model reads
        # a receiver's declared pointee from the function being emitted.  See
        # arm64's `_emit_function`.
        self._cur_fn = None
        self._if_counter = 0
        # The element width the subscript being emitted reads and writes at, in
        # bytes.  `_emit_subscript_addr` sets it on every path — a container
        # element is 8, a string byte is 1, a declared pointee is its own — and
        # the load and the store read it, so the address computation and the
        # instruction that uses it cannot disagree.  Same rule and same reason as
        # the arm64 backend's `_sub_width`, and the decision is
        # `model.subscript_base_lowering` so the two cannot drift.
        self._sub_width = 8
        self._while_counter = 0
        self._var_regs = {}
        self._var_spills = {}
        self._spill_bytes = 0
        self._frame_bytes = 0
        # PCs of the conditional branches that test an `if`/`elif`/`while`/
        # ternary condition, so a later proof generator can tell an `if`'s own
        # branch from a short-circuit `and`/`or`'s (same reason, and the same
        # `cond_branches` key, as formal/arm64_codegen.py).
        self._cond_branch_pcs = []
        # ── A multi-field receiver, BY REFERENCE ──────────────────────────
        # The x86-64 twin of arm64's, over the SAME shared layout
        # (`formal/model.py`'s `struct_constructor_sites` / `struct_frame_bytes`),
        # because a representation the two backends lay out differently is a
        # representation one of them computes on wrongly. `_frame_sites` is
        # `{id(call): (struct, offset)}`; the frames sit at the bottom of the
        # frame's blob region and the blob cursor starts above them, which is
        # what keeps a method's own list/dict blobs off the receiver it was
        # handed. `_frame_slots` is `formal/build.py`'s
        # `{f"{holder}.{field}": slot}`, consulted by `_load_var`/`_store_var`.
        self._frame_sites: dict = {}
        self._frame_recv_bytes = 0
        self._frame_slots: dict = {}
        # `{"h.a.b": slot}` — a NESTED frame read, which is two loads
        # and therefore not something `_frame_slots` can express.
        self._frame_nested_slots: dict = {}
        # The NAMES in this function that hold a frame address, as opposed to
        # the slot table above: `_frame_slots` says which `h.f` is a load, and
        # the holder set says which `h` is a frame at all — which is what tells
        # a `h.f.g` chain (a field of a field, no layout) from an ordinary
        # `a.b.c` member path. Reset per function; arm64 keeps the same pair.
        self._frame_holders: set = set()
        # Enclosing loops, innermost last: `start` (continue target for
        # `while`), `step` (continue target for `for`, which must still
        # advance the counter), `break` (label after the loop's else).
        self._loops = []
        # Nesting depth of for-range loops currently being emitted; selects
        # the `_fe{d}`/`_fs{d}` temps. Reset per function.
        self._for_depth = 0
        self._string_vars = set()
        # Nonzero while evaluating a for-iterable / membership RHS: a
        # BinaryOp `+`/`|` there means list/set concatenation, not the
        # integer ALU form.
        self._container_ctx = 0
        # Nesting depth of for-in (blob iteration) loops; selects the
        # `_fi{d}`/`_fb{d}` temps. Reset per function.
        self._for_depth = 0
        # Base depth for comprehension generator temps (`_ci{d}`/`_cb{d}`),
        # so a comprehension nested in a for-list cannot alias its temps.
        self._compr_depth = 0
        # Enclosing try-finally bodies, outermost first. Flushed before a
        # return/break/continue so the finally runs on those paths too.
        self._pending_finally = []
        # Names bound to a string address this function (a StringLiteral RHS
        # or an alias of one). A subscript on one of these is a byte load, not
        # a list index. Reset per function.
        self._string_vars = set()
        # Names bound to a dict pair-blob pointer, whose subscript is a key
        # lookup rather than an index. Mutually exclusive with the above.
        self._dict_vars = set()
        # Names bound to a list/tuple/set blob. This is what makes `a + b`
        # on two LOCALS a concatenation: without it, two bare idents are
        # indistinguishable from two integers, and the operator silently
        # lowers to pointer arithmetic.
        self._blob_vars = set()
        # Names bound to a FILE DESCRIPTOR (the lowered `open`, or an alias of
        # one). `write`/`close` lower to the C library's `write(2)`/`close(2)`,
        # so the receiver has to be one, and `open(2)` is the only thing on
        # this path that produces one — see model.VALUE_METHOD_RECEIVERS for
        # what went wrong without this. Reset per function.
        self._fd_vars = set()
        # String-literal data, appended after all the code: (label, bytes).
        # `_str_intern` maps content to label so equal literals share one
        # address. Both persist across compile()'s two-pass re-emit so the
        # labels stay unique.
        self._strings = []
        self._str_counter = 0
        self._str_intern = {}
        # {function name: model.ValueKinds}, for the whole module. `_functions`
        # is fixed for a compile, so a callee's answer is the same at every
        # call site and there is no reason to re-derive it per function.
        self._vkinds_cache: dict = {}

    # ── entry point ──────────────────────────────────────────────────

    def compile(self, stmts: list, base_addr: int = 0x100001000,
                emit_startup: bool = True, structs: list = None) -> tuple:
        """Compile a fire_compiler module statement list to x86-64 code.

        `structs` is the module's struct declarations (`formal/build.py` calls
        both backends through one `_codegen_and_link` and hands both the same
        list). Accepting it here is what keeps `--backend=x86_64` from dying
        with a TypeError on a keyword meant for the other backend (see
        bugs/FORMAL_arm64_instruction_coverage.md, "Landed alongside: dylib_syms"),
        and USING it is what keeps the two backends from disagreeing about
        which callee names are types: without it a struct constructor fell
        through to the extern path and became a `call _Point` against a symbol
        nothing defines, so `--arch=x86-64` built an image that arm64 refused
        and that then died in dyld. Which names are types is a decision of the
        shared model, not of one backend.

        `stmts` is Parser(...).parse_module()'s output — may contain imports,
        module-level assigns, etc.; only FunctionDefs are lowered. If a `main`
        function is present it is the entry (first in the emitted order);
        otherwise the first FunctionDef is.

        The returned `info` mirrors the arm64 backend's: `labels` maps every
        label to its absolute address, `external_syms`/`extern_calls` describe
        the unbound calls the binary format has to stub, and `base_addr` /
        `func_offset` locate the entry — a proof generator and the binary
        emitters both read these rather than recomputing the layout."""
        functions = [s for s in stmts if isinstance(s, F.FunctionDef)]
        if not functions:
            raise CodegenError("no function definitions to compile")
        if emit_startup:
            functions = M.entry_function(functions)
        # The module's struct declarations, by name. `formal/build.py` hands
        # both backends the same list through one `_codegen_and_link`, so
        # consuming it here is what lets the two agree about which callee names
        # are TYPES rather than functions — the decision belongs to
        # formal.model, and a backend that ignores the list decides it alone.
        self._structs = {st.name: st for st in (structs or [])
                         if getattr(st, "name", None)}
        for f in functions:
            # async def and generators lower as ordinary functions: formal
            # has no event loop / iterator protocol, so `await` is identity
            # and `yield` leaves its value in RAX (compile-only fidelity).
            self._functions[f.name] = f

        self.asm.org(base_addr)

        first_func_name = functions[0].name
        if emit_startup:
            # Save/restore RBP around the call so the kernel's return lands
            # with RAX still holding the entry function's value: that value
            # becomes the process exit status, which is what makes a formal
            # build runnable (same contract as the arm64 startup stub).
            self.asm.emit(encode_push_r64(Reg.RBP))
            self.asm.emit(encode_mov_r64_r64(Reg.RBP, Reg.RSP))
            if functions[0].params:
                self._emit_mov_imm(ARG_REGS[0], self.test_input)
            self.asm.emit(encode_call_rel32(0))
            self.asm.emit_label_rel32(first_func_name, here_offset=-4)
            self.asm.emit(encode_pop_r64(Reg.RBP))
            self.asm.emit(encode_ret())

        for f in functions:
            self._emit_function(f)

        # String literal data goes after the code: its label is what the
        # RIP-relative LEAs point at, so it has to exist before resolve().
        for label, data in self._strings:
            self.asm.label(label)
            self.asm.emit(data)

        self.asm.resolve()
        code = bytes(self.asm.sections["text"])
        external_syms = list({sym for sym, _, _, _ in self.asm.extern_refs})
        extern_calls = sorted(
            ({"sym": sym, "addr": pos, "kind": kind}
             for sym, pos, _, kind in self.asm.extern_refs
             if kind in ("call", "call_got")),
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
            "cond_branches": sorted(self._cond_branch_pcs),
        }
        return code, info

    @property
    def func_name(self):
        return self._current_function or ""

    # ── functions ────────────────────────────────────────────────────

    def _emit_function(self, f: F.FunctionDef) -> None:
        self._current_function = f.name
        self._cur_fn = f
        self.asm.label(f.name)

        var_names = _collect_var_names(f)
        n_reg = min(len(var_names), len(CALLEE_SAVED))
        self._var_regs = {name: CALLEE_SAVED[i]
                          for i, name in enumerate(var_names[:n_reg])}
        self._var_spills = {name: i
                            for i, name in enumerate(var_names[n_reg:])}
        self._spill_bytes = 8 * len(self._var_spills)
        # Frame geometry, all as negative offsets from RBP. RBP is 16-byte
        # aligned (RSP is 8 mod 16 at entry and PUSH RBP makes it 16 mod 16),
        # so a 16-aligned total keeps every call site aligned:
        #
        #   -8                        saved RBP
        #   -8*(1+i)                  saved callee-saved registers holding locals
        #   -8*(n_reg+1+i)            spill slots
        #   -top .. -(top+_BLOB)      container blobs, cursor growing UP from
        #                              the frame bottom and capped at -top
        #   -(top+_BLOB) .. -(top+_BLOB+_TEMP_SLACK)   pushed temporaries
        #                              (RSP lives at the bottom, and only ever
        #                              moves below it, so it cannot reach a
        #                              blob or a spill slot)
        self._top_bytes = 8 * (len(self._var_regs) + len(self._var_spills))
        self._blob_base = -(self._top_bytes + _BLOB_BYTES)
        self._blob_cap = -self._top_bytes
        # Receiver frames occupy the BOTTOM of the blob region and the blob
        # cursor starts above them. arm64's `_emit_function` says why this is
        # the placement; the short version is that a callee's whole frame lies
        # below the caller's RSP, so a callee's frames and blobs are both below
        # every frame the caller owns, and a blob made in the same function
        # cannot land on one.
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
        # actually is.  The x86-64 twin of arm64's, and it is the same table
        # rather than a re-derivation: a copy's soundness rests entirely on
        # recognising the source, and two recognitions could disagree.
        self._frame_candidates = dict(
            getattr(f, "_frame_candidates", None) or {})
        # The x86-64 twin of arm64's, from the same function table: a
        # construction argument has to be told apart from a container returned
        # by a callee, and the declared return type is the only evidence there
        # is.
        self._return_types = M.function_return_types(
            self._functions.values())
        self._list_cursor = self._blob_base + self._frame_recv_bytes
        self._frame_bytes = _align16(self._top_bytes + _BLOB_BYTES
                                     + _TEMP_SLACK)


        self._call_types = {
            g.name: resolve(parse_type_name(g.return_type) or DEFAULT_INT_TYPE)
            for g in self._functions.values()
        }
        self._vtypes = function_var_types(f, self._call_types)
        self._for_depth = 0
        self._compr_depth = 0
        self._container_ctx = 0
        self._string_vars = set()
        self._dict_vars = set()
        self._blob_vars = set()
        self._fd_vars = set()
        # `comptime NAME = value` bindings in scope, and the list-valued ones
        # kept as their AST. Reset per function, exactly like the tables above:
        # a comptime binding is compile-time state local to the body that
        # declares it, and carrying one across a function boundary would make
        # a name resolve in a function that never wrote it.
        self._comptime_vals: dict = {}
        self._comptime_list_asts: dict = {}
        self._pending_finally = []
        # What each local holds (see model.ValueKinds) and how much room each
        # list literal needs for `append`. Whole-function properties, so they
        # are computed once here rather than guessed at each use site.
        self._vkinds = self._scan_value_kinds(f)
        self._list_caps, self._list_caps_by_name = self._scan_list_caps(
            f, self._vkinds)

        # Prologue: establish the frame pointer, reserve the frame, spill the
        # callee-saved registers this function borrows into the frame's tail
        # (they hold locals, so the CALLER's values have to survive a
        # recursive or nested call), then move each incoming argument home.
        self.asm.emit(encode_push_r64(Reg.RBP))
        self.asm.emit(encode_mov_r64_r64(Reg.RBP, Reg.RSP))
        self.asm.emit(encode_sub_r64_imm32(Reg.RSP, self._frame_bytes))
        for i, reg in enumerate(self._var_regs.values()):
            self.asm.emit(encode_mov_rm64_r64(Reg.RBP, self._saved_reg_off(i),
                                              reg))
        params = list(f.params or [])

        if len(params) > len(ARG_REGS):
            raise CodegenError(
                f"{f.name}: {len(params)} parameters exceeds the "
                f"{len(ARG_REGS)} the formal x86-64 ABI passes in registers")
        for i, (pname, ptype) in enumerate(params):
            ptype_t = parse_type_name(ptype) or DEFAULT_INT_TYPE
            if pname in self._var_regs:
                home = self._var_regs[pname]
                self.asm.emit(encode_mov_r64_r64(home, ARG_REGS[i]))
                # Normalize the incoming bits to the parameter's declared
                # width: values are supposed to arrive already extended (the
                # caller does it), but an extern caller need not, and a stale
                # high word would poison every later comparison.
                self._emit_extend(home, ptype_t)
            else:
                self.asm.emit(encode_mov_r64_r64(Reg.R11, ARG_REGS[i]))
                self._emit_extend(Reg.R11, ptype_t)
                self._store_var(pname, Reg.R11)

        for stmt in f.body:
            self._emit_stmt(stmt)

        if not _always_returns(f.body):
            self._emit_mov_imm(Reg.RAX, 0)
            self._emit_epilogue()

        self._current_function = None

    def _emit_epilogue(self) -> None:
        """Restore the borrowed callee-saved registers, then leave; ret.

        The save/restore of the registers holding locals is the whole reason
        they are callee-saved: a call in this function would otherwise destroy
        the caller's copy. `leave` alone cannot do it — it moves RSP back to
        the frame pointer and pops RBP, abandoning the frame (and the saved
        registers with it) — so each one is reloaded from its frame slot
        first.

        The slots are addressed off RBP, so the restore does not depend on
        where RSP happens to be."""
        for i, reg in enumerate(self._var_regs.values()):
            self.asm.emit(encode_mov_r64_rm64(reg, Reg.RBP,
                                              self._saved_reg_off(i)))
        self.asm.emit(encode_leave())
        self.asm.emit(encode_ret())


    def _push_slot(self, reg: Reg) -> None:
        """Push `reg` as a 16-byte slot (see _SLOT)."""
        self.asm.emit(encode_sub_r64_imm32(Reg.RSP, _SLOT))
        self.asm.emit(encode_mov_rm64_r64(Reg.RSP, 0, reg))

    def _pop_slot(self, reg: Reg) -> None:
        """Pop a 16-byte slot into `reg` and release it."""
        self.asm.emit(encode_mov_r64_rm64(reg, Reg.RSP, 0))
        self.asm.emit(encode_add_r64_imm32(Reg.RSP, _SLOT))


    def _saved_reg_off(self, index: int) -> int:
        """RBP-relative slot holding the `index`-th borrowed callee-saved
        register. The first slot below RBP is the saved RBP itself, so these
        start at -8."""
        return -8 * (1 + index)

    def _spill_off(self, name: str) -> int:
        """RBP-relative slot for `name`'s spill home (negative).

        Spill slots sit below the saved-register area, so a spilled local and
        a borrowed register can never name the same 8 bytes."""
        return -8 * (len(self._var_regs) + 1 + self._var_spills[name])

    def _load_var(self, name: str, dst: Reg) -> None:
        """dst = local `name`. Register homes MOV; spill slots load from
        [RBP + off]. A name in none of those tables is REFUSED, with the name.

        It used to read 0, and arm64's answer to the same name was X19 — the
        two architectures disagreeing about one program, which is the failure
        this project cannot have. The immediate 0 was the more plausible of
        the two and the more dangerous: `G = 5` at module level, read from a
        function, returned 0 here and 10 on arm64 where the source says 5.
        Neither was an answer; both were a register. A global needs storage
        with static duration and this path has none, so the name is placed by
        `formal/model.py`'s module symbol table (a folded literal is
        substituted at the read, in `formal/build.py`) or it is not placed at
        all, and "not placed" is a refusal.

        A FRAME SLOT (`h.x`, `h` holding the address of `x`'s frame) is a
        memory access rather than a local: `mov dst, [h + 8*slot]`. It is
        intercepted here, and not at the read sites, because every read of a
        field on this path already funnels through this one function — the
        same interception, and the same reason for it, as arm64's."""
        slot = self._frame_slots.get(name)
        if slot is not None:
            self._load_var(name.rsplit(".", 1)[0], Reg.R11)
            self.asm.emit(encode_mov_r64_rm64(dst, Reg.R11, 8 * slot))
            return
        # A NESTED frame slot is TWO loads.  Checked before the one-load table
        # would matter if the key could collide, and before the register and
        # spill homes for the reason that matters: an x86-64 backend with no
        # globals reads an unknown name as 0, so a missing entry here is a
        # silent zero rather than a wrong register.
        nested = self._frame_nested_slots.get(name)
        if nested is not None:
            self._load_var(name.rsplit(".", 1)[0], Reg.R11)
            self.asm.emit(encode_mov_r64_rm64(dst, Reg.R11, 8 * nested))
            return
        if name in self._var_regs:
            r = self._var_regs[name]
            if dst != r:
                self.asm.emit(encode_mov_r64_r64(dst, r))
            return
        if name in self._var_spills:
            self.asm.emit(encode_mov_r64_rm64(dst, Reg.RBP,
                                              self._spill_off(name)))
            return
        raise CodegenError(self._no_home(name))

    def _no_home(self, name: str) -> str:
        """The refusal for a name with no register, spill slot or frame slot.

        The same words arm64's `_no_home` gives, from the same model function,
        because the two architectures are one language implementation: this
        read used to be an immediate 0 here and X19 there, for one program."""
        holder = name.split(".", 1)[0] in self._frame_holders
        if "." in name:
            return M.field_access_refusal(name, self.func_name or "<module>",
                                          name.split(".", 1)[0], holder)
        return M.unresolved_name_refusal(
            name, self.func_name or "<module>",
            "the register allocator collected no home for it, so the emitter "
            "and the allocation walk disagree about this function's locals")

    def _store_var(self, name: str, src: Reg) -> None:
        """local `name` = src. Register homes MOV; spill slots store to
        [RBP + off]. A frame slot is a store into the receiver's frame, and
        that store is the whole reason a method's effect reaches its caller:
        the caller's local holds the same address."""
        slot = self._frame_slots.get(name)
        if slot is not None:
            if src == Reg.R11:
                # R11 is about to hold the address; park the value in the other
                # caller-saved scratch (R10/R11 hold no local — see x86_64.py).
                self.asm.emit(encode_mov_r64_r64(Reg.R10, Reg.R11))
                src = Reg.R10
            self._load_var(name.rsplit(".", 1)[0], Reg.R11)
            self.asm.emit(encode_mov_rm64_r64(Reg.R11, 8 * slot, src))
            return
        # A NESTED frame slot: the outer load gives the nested frame's base and
        # the store lands in its own slot.  The R11 parking is the same dance as
        # the one-load case above, for the same reason.
        nested = self._frame_nested_slots.get(name)
        if nested is not None:
            if src == Reg.R11:
                self.asm.emit(encode_mov_r64_r64(Reg.R10, Reg.R11))
                src = Reg.R10
            self._load_var(name.rsplit(".", 1)[0], Reg.R11)
            self.asm.emit(encode_mov_rm64_r64(Reg.R11, 8 * nested, src))
            return
        if name in self._var_regs:
            r = self._var_regs[name]
            if src != r:
                self.asm.emit(encode_mov_r64_r64(r, src))
            return
        if name in self._var_spills:
            self.asm.emit(encode_mov_rm64_r64(Reg.RBP, self._spill_off(name),
                                              src))
            return
        raise CodegenError(self._no_home(name))

    # ── statements ───────────────────────────────────────────────────

    def _emit_stmt(self, stmt) -> None:
        if isinstance(stmt, F.ReturnStmt):
            if stmt.value is None:
                self._emit_mov_imm(Reg.RAX, 0)
            else:
                self._emit_expr(stmt.value)
            self._flush_pending_finally()
            self._emit_epilogue()
            return

        if isinstance(stmt, F.ExprStmt):
            self._emit_expr(stmt.value)
            return

        if isinstance(stmt, F.PassStmt):
            return

        if isinstance(stmt, F.GlobalStmt):
            # `global NAME` is a binding declaration only. formal's locals are
            # callee-saved registers or stack slots; there is no separate
            # module-global storage to redirect subsequent stores into, so the
            # declaration is a no-op and the AssignStmt still targets the
            # local. Same reading as the arm64 backend.
            return

        if isinstance(stmt, (F.ImportStmt, F.FromImportStmt)):
            # Single-file formal build: no dynamic loader, no sibling-module
            # link. Matches build.py's top-level filter — imports are accepted
            # and ignored; later uses of the bound names lower as ordinary
            # idents (uninitialized, or extern where a call names them).
            return

        if isinstance(stmt, F.StructDef):
            # Type-only; methods are lifted by build._flatten_closures. Nothing
            # to emit.
            return

        if isinstance(stmt, F.AssertStmt):
            # assert cond [, msg]: evaluate cond, exit(1) when falsy. The
            # message is not formatted — there is no printf on this path — and
            # the nonzero status is the signal.
            #
            # The JMP over the exit is not an optimisation, it is the whole
            # statement. There was none here: `jcc fail` was immediately
            # followed by `label fail`, so the branch had nothing to skip and
            # the FALL-THROUGH path went straight into exit(1). Every `assert`
            # failed, whatever it asserted — measured on this backend,
            # `assert 1` printed nothing and exited 1, while arm64 (which has
            # the same shape with the branch over the exit spelled `b ok`)
            # printed `passed`. The `_emit_mov_imm(Reg.R11, 1)` was also
            # dead: R11 is the divisor, the shift count, and the alloc size on
            # this path, and an `assert` does none of those.
            self._emit_truthy_word(stmt.value)
            self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
            self._if_counter += 1
            aid = self._if_counter
            fail_label = f"{self.func_name}_assert{aid}_fail"
            ok_label = f"{self.func_name}_assert{aid}_ok"
            self._record_cond_branch()
            self._emit_jcc(COND_E, fail_label)
            self._emit_jmp(ok_label)
            self.asm.label(fail_label)
            self._emit_call_exit(1)
            self.asm.label(ok_label)
            return

        if isinstance(stmt, F.RaiseStmt):
            # No EH runtime: evaluate the exception expression for its side
            # effects (the args of `raise RuntimeError(...)`), then exit(1).
            # Handlers stay unreachable — there is no unwinder to route to.
            if stmt.value is not None:
                self._emit_expr(stmt.value)
            self._flush_pending_finally()
            self._emit_call_exit(1)
            return

        if isinstance(stmt, F.TryStmt):
            self._emit_try(stmt)
            return

        if isinstance(stmt, F.WithStmt):
            # async with lowers as a plain with (no event loop / context
            # manager protocol on this path).
            self._emit_with(stmt)
            return

        if isinstance(stmt, F.IfStmt):
            self._emit_if(stmt)
            return

        if isinstance(stmt, F.WhileStmt):
            self._emit_loop(cond=stmt.condition, body=stmt.body,
                            else_body=stmt.else_body or [], for_info=None)
            return

        if isinstance(stmt, F.ForStmt):
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
            self._emit_jmp(self._loops[-1]["break"])
            return

        if isinstance(stmt, F.ContinueStmt):
            if not self._loops:
                raise CodegenError("continue outside of a loop")
            self._flush_pending_finally(self._loops[-1]["fin_depth"])
            self._emit_jmp(self._loops[-1]["step"])
            return

        if isinstance(stmt, F.AugAssignStmt):
            if isinstance(stmt.target, F.IdentExpr):
                self._check_comptime_target(stmt.target.name,
                                            "augmented assignment")
            self._emit_aug_assign(stmt)
            return

        if isinstance(stmt, F.AssignStmt):
            if isinstance(stmt.target, F.SubscriptExpr):
                self._emit_subscript_store(stmt.target, stmt.value)
                return
            if isinstance(stmt.target, F.SliceExpr):
                self._emit_slice_store(stmt.target, stmt.value)
                return
            if isinstance(stmt.target, F.TupleExpr):
                self._emit_tuple_assign(stmt)
                return
            if not isinstance(stmt.target, F.IdentExpr):
                # A receiver FIELD of a by-reference struct is a real store
                # (`mov [holder + 8*slot], value`), and it is the whole reason
                # a method's effect is visible to its caller. Any other
                # MemberExpr target is a field of an object formal has no
                # model for: evaluate both sides and drop the store (the same
                # compile-only reading a MemberExpr load gets).
                if isinstance(stmt.target, F.MemberExpr):
                    key = _member_slot_key(stmt.target)
                    # `_frame_nested_slots` is here for the same reason the
                    # load side has its own branch: a nested key is not in
                    # `_frame_slots`, so without it `o.inner.a = 1` would fall
                    # into the "no model for this object" reading below and be
                    # DROPPED — the program would build, run, and return a
                    # number the source never wrote.  arm64 routes every name
                    # through `_store_var` and would have stored it, so this is
                    # also the divergence the pair must not have.
                    if key is not None and (key in self._frame_slots
                                            or key in self._frame_nested_slots):
                        self._emit_expr(stmt.value)
                        self._store_var(key, Reg.RAX)
                        # …and the slot's VALUE KIND has to be recorded, the
                        # same way a local's is. Without this a slot assigned a
                        # string literal is not known to hold a `char *`, so a
                        # later `self.name.startswith(p)` is refused here as
                        # "the source does not say what its receiver holds" —
                        # while arm64, which does record it, builds the same
                        # program and runs it. That is the two-backends
                        # disagreeing about one source file, which is the one
                        # thing this pair is not allowed to do.
                        self._note_binding(key, stmt.value)
                        return
                    # REFUSED, not dropped.  This used to evaluate both sides
                    # and return, which is a SILENTLY DISCARDED STORE: the
                    # program built, ran, and the write was simply not there.
                    # arm64's `_store_var` had no slot either and fell through
                    # to `mov x19, src`, so the two architectures disagreed
                    # about the same source — one dropped it, one put it in a
                    # register the next function reads as its first parameter.
                    # Wave 5's rule exactly: on x86-64 a missing branch is a
                    # dropped store, not a wrong value.  The words are the
                    # shared model's, so both arches print the same line.
                    self._emit_expr(stmt.target.obj)
                    key = _member_slot_key(stmt.target)
                    spelled = key or M.member_chain_text(stmt.target)
                    root = spelled.split(".", 1)[0] if spelled else "this"
                    raise CodegenError(M.field_access_refusal(
                        spelled, self.func_name or "<module>", root,
                        root in self._frame_holders))
                raise CodegenError(
                    f"assignment to {type(stmt.target).__name__} is not "
                    f"lowered on the formal x86-64 path; only a plain name "
                    f"has a home")
            # type_ann is metadata, not a storage decision: types.
            # function_var_types already resolves ann-or-infer for the type
            # lattice, so a non-int annotation must not stop the VALUE from
            # lowering.
            self._check_comptime_target(stmt.target.name, "assignment")
            self._emit_expr(stmt.value)
            self._store_var(stmt.target.name, Reg.RAX)
            self._note_binding(stmt.target.name, stmt.value)
            return

        if isinstance(stmt, F.MultiAssignStmt):
            # Chained `a = b = expr`: evaluate the RHS once, then MOV it into
            # each target — a MOV does not clobber RAX.
            self._emit_expr(stmt.value)
            for t in stmt.targets:
                if not isinstance(t, F.IdentExpr):
                    raise CodegenError(
                        "chained assignment target must be a plain name "
                        f"(got {type(t).__name__})")
                self._store_var(t.name, Reg.RAX)
                self._note_binding(t.name, stmt.value)
            return

        if isinstance(stmt, F.VarDecl):
            # The home is allocated by _collect_var_names; only an
            # initializer emits anything.
            if stmt.value is not None:
                self._emit_expr(stmt.value)
                self._store_var(stmt.name, Reg.RAX)
                self._note_binding(stmt.name, stmt.value)
            return

        if isinstance(stmt, F.FunctionDef):
            raise CodegenError("nested function definitions are not "
                               "supported on the formal x86-64 path")

        if isinstance(stmt, F.ComptimeVarStmt):
            # `comptime NAME = <const>`: fold and record, emit nothing. Same
            # rule as the gimple path's _gen_stmt_ComptimeVarStmt — a comptime
            # binding is compile-time state, so it produces no instructions and
            # no storage. The DECISION is shared (comptime_eval.resolve_var),
            # which is the whole point of that module living in mojo/middle/.
            self._bind_comptime(stmt)
            return

        if isinstance(stmt, F.ComptimeIfStmt):
            # Which branch is taken is a language decision, shared
            # (comptime_eval.resolve_if); 'runtime' here just means the
            # condition did not fold, and this backend then emits the ordinary
            # runtime branch — the same degradation the gimple path makes, so
            # all three agree on the observable behaviour.
            which = comptime_eval.resolve_if(stmt, self._comptime_vals)
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
            f"x86-64 path")

    def _check_comptime_target(self, name: str, what: str) -> None:
        """Refuse a store to a name that is currently a `comptime` binding.

        The store would otherwise be silently dropped: reads of the name go
        through `_comptime_vals` (which is the whole point — the binding is a
        constant, not a local), so a following `_store_var` would write a slot
        nothing ever reads. That is a silent miscompile, so it is an error.
        Real Mojo rejects the assignment too, for the same reason: a `comptime`
        name is not assignable.

        Not optional to the comptime support above, and this is why: x86-64 used
        to refuse every `comptime` binding outright, so it could not reach the
        state this guards. Adding the bindings without this would have introduced
        a miscompile rather than removed one. arm64's copy of the rule is the
        same function for the same reason."""
        if name in self._comptime_vals or name in self._comptime_list_asts:
            raise CodegenError(
                f"{what} to comptime binding {name!r} (a `comptime` name is a "
                "compile-time constant and cannot be assigned)")

    def _bind_comptime(self, stmt) -> None:
        """Record a `comptime NAME = value` binding, or fail honestly.

        The decision itself is shared — `comptime_eval.resolve_var` — and is the
        same function the arm64 backend and the gimple path call, so all three
        agree on what a `comptime` binding means and on exactly which
        initializers do not fold. What is left to the backend is only the
        failure: a binding that does not fold to a constant is an ERROR here
        rather than a runtime local, because a runtime local would give the
        program different behaviour than the source declares.

        This is the refusal `bugs/FORMAL_known_limits.md` §3 records as ARCH
        DRIFT. x86-64 used to refuse every `comptime` binding one layer up, at
        the statement dispatch, with "unsupported statement ComptimeVarStmt" —
        a different limit for the same construct on the two architectures, and
        one that named a shape the author never wrote. Sharing the resolver
        removes the drift by construction rather than by keeping the two
        wordings in step by hand.
        """
        name = stmt.target
        resolved = comptime_eval.resolve_var(stmt, self._comptime_vals)
        if resolved is None:
            raise CodegenError(M.comptime_fold_refusal(name))
        kind, val = resolved
        if kind == "list":
            self._comptime_list_asts[name] = val
        else:
            self._comptime_vals[name] = val

    def _emit_comptime_read(self, name: str) -> None:
        """RAX = the value of the `comptime` binding `name`.

        A string binding is not a machine word here: this path has no interned
        comptime strings, so it materializes the interned literal for the text —
        which is what the value *is* everywhere else a string is on this
        backend (see the `StringLiteral` case in `_emit_expr`, a LEA of the
        same interned data)."""
        val = self._comptime_vals[name]
        if isinstance(val, str):
            self.asm.emit(encode_lea_r64_rip(Reg.RAX, 0))
            self.asm.emit_label_rip(self._intern_string(val), here_offset=-4)
            return
        self._emit_mov_imm(Reg.RAX, int(val))

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
            self.COMPTIME_UNROLL_CAP)

    def _emit_comptime_target(self, target, value) -> None:
        """Bind a `comptime for` target for one iteration, as an ordinary local
        assignment (the counter is a real runtime local — only the trip count
        was compile-time here), so a folded and an unfolded `comptime for`
        produce the same shape of code."""
        self._emit_stmt(F.AssignStmt(target=F.IdentExpr(name=target),
                                     value=value, line=0, col=0))

    def _intern_string(self, s: str) -> str:
        """Return a stable data label for `s`, emitting the bytes on first use.

        The bytes live after all the code (see `compile`), so a string is
        read-only data in the image's text — the same place the arm64 backend
        puts them."""
        if s in self._str_intern:
            return self._str_intern[s]
        label = f"str_{self._str_counter}"
        self._str_counter += 1
        self._strings.append((label, s.encode() + b"\0"))
        self._str_intern[s] = label
        return label

    def _flush_pending_finally(self, depth: int = 0) -> None:
        """Emit the pending try-finally frames from `depth` inward.

        `depth` is 0 for a return (every enclosing finally runs) and the
        enclosing loop's own `fin_depth` for break/continue (only the frames
        opened INSIDE that loop). The list is truncated first, so a return
        inside a finally does not re-enter the same body. RAX (the return
        value being built) is saved across the flush in a 16-byte slot."""
        if len(self._pending_finally) <= depth:
            return
        fins = self._pending_finally[depth:]
        del self._pending_finally[depth:]
        self._push_slot(Reg.RAX)
        for fin in reversed(fins):
            for s in fin:
                self._emit_stmt(s)
        self._pop_slot(Reg.RAX)

    def _emit_try(self, stmt: F.TryStmt) -> None:
        """try/except/else/finally without an exception runtime.

        The except arms are SKIPPED: formal has no unwinder, so there is no
        edge from a raise site to a handler — and `raise` itself exits the
        process, so no handler is ever reachable. `else` runs on the success
        path (which, without EH, is simply the fall-through). A `finally` is
        pushed onto `_pending_finally` so the paths that leave early
        (return/break/continue/raise) run it too, and the normal fall-through
        emits it here."""
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
                    # A return/raise inside the body already flushed it, so
                    # the frame is gone and this code is unreachable.
                    need_fallthrough = False
        if need_fallthrough:
            for s in fin:
                self._emit_stmt(s)

    def _emit_with(self, stmt: F.WithStmt) -> None:
        """with-items, without a context-manager protocol.

        Evaluate each context expression for its side effects (open(), lock
        acquisition, ...); with no __enter__/__exit__ runtime an `as` alias
        binds to the context expression's own value, not to an entered one.
        The body always runs on the fall-through path, and return/break/
        continue inside it do no cleanup (there is none to do). `async with`
        lowers as a plain with. Same reading as the arm64 backend.
        """
        for it in stmt.items or []:
            self._emit_expr(it.expr)
            if it.alias is not None:
                alias = _with_item_alias_name(it.alias)
                if alias is not None:
                    self._store_var(alias, Reg.RAX)
        for s in stmt.body:
            self._emit_stmt(s)

    def _emit_extern_call(self, name: str) -> None:
        """Call an unbound symbol, in whichever of the two extern forms the
        target binary format uses (see __init__'s `extern_style`)."""
        if self.extern_style == "got":
            self.asm.emit_extern_call_got(name)
        else:
            self.asm.emit_extern_call(name)

    def _emit_call_exit(self, status: int) -> None:
        """Call the C library's `exit(status)`.

        The extern path (a stub the loader binds) rather than a raw syscall,
        because the syscall number for exit differs between Darwin and Linux
        and the formal x86-64 path emits the same code for both — the binary
        format, not the instruction stream, is what differs per platform."""
        self._emit_mov_imm(Reg.RDI, status)
        self._emit_mov_imm(Reg.RAX, 0)   # AL = 0 vector registers (varargs)
        self._emit_extern_call("exit")

    def _emit_aug_assign(self, stmt) -> None:
        if isinstance(stmt.target, F.IdentExpr):
            name = stmt.target.name
        elif isinstance(stmt.target, F.MemberExpr) \
                and _member_slot_key(stmt.target) in (
                    self._frame_slots.keys() | self._frame_nested_slots.keys()):
            # `self.count += 1` on a by-reference receiver. No new code: the
            # load and the store below go through `_load_var`/`_store_var`,
            # which already turn a frame slot into a memory access, so the whole
            # accumulator dance is unchanged.
            name = _member_slot_key(stmt.target)
        else:
            raise CodegenError(
                "augmented assignment target must be a plain name on the "
                f"formal x86-64 path (got {type(stmt.target).__name__})")
        op = stmt.op[:-1] if stmt.op.endswith("=") and stmt.op != "==" \
            else stmt.op
        # The same refusal `_emit_binop` makes, asked HERE because an augmented
        # assignment is a separate emitter that never went through it. That is
        # not a hypothetical: `s += t` built, ran, and printed `[]` on arm64
        # and segfaulted on x86-64 — the same non-answer as `s = s + t`, which
        # BOTH backends refused, from the same line of source. `stmt.op` is
        # the spelling to quote, so the diagnostic names the `+=` the reader
        # is looking at rather than the `+` the table is keyed on.
        reason = M.string_binary_refusal(
            op, self._expr_str_kind(stmt.target),
            self._expr_str_kind(stmt.value), spelled_op=stmt.op)
        if reason is not None:
            raise CodegenError(reason)
        ttype = self._ttype(stmt.target)
        # The accumulator is R11, not RAX: for `-` and `>>` the variable's
        # OLD value is the left operand and the assigned expression the right
        # one, and RAX is holding the right one. R11 is written as the left
        # operand so the operation reads in source order.
        self._load_var(name, Reg.RAX)
        self._push_slot(Reg.RAX)
        self._emit_expr(stmt.value)
        self._pop_slot(Reg.R11)
        if op in _ALU_RR:
            self.asm.emit(_ALU_RR[op](Reg.R11, Reg.RAX))   # R11 = old op rhs
            self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R11))
        elif op in ("<<", ">>"):
            # The count has to be in CL and the value in RAX, which is what
            # `_emit_shift_reg` takes. The signedness is the NAME's own, not
            # the promotion's — `model.shift_signedness`, the same rule
            # `_emit_shift` uses for the binary form, so `y >>= n` and
            # `y = y >> n` cannot disagree about whether the result is
            # signed.
            self.asm.emit(encode_mov_r64_r64(Reg.RCX, Reg.RAX))
            self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R11))
            self._emit_shift_reg(op, cmp_signed(
                M.shift_signedness(self._ttype(F.IdentExpr(name)))))
        else:
            raise CodegenError(
                f"unsupported augmented operator {stmt.op!r} on the formal "
                f"x86-64 path (supports + - * & | ^ << >>)")
        self._emit_trunc(common_type(ttype, self._ttype(stmt.value)))
        self._store_var(name, Reg.RAX)


    # ── control flow ─────────────────────────────────────────────────

    def _emit_jcc_bool(self, reg: Reg, cc: int, label: str) -> None:
        """Branch on a 0/1 boolean already sitting in `reg`.

        SETcc does NOT set flags, so a Jcc placed straight after it reads the
        flags left by whatever CMP produced the boolean — i.e. it tests the
        original comparison a second time instead of the result. That is not
        a subtle difference: for `i >= count` the CMP's ZF is only set when
        i EQUALS count, so a bare `jne` after the SETcc leaves the loop on
        the first iteration. The TEST re-establishes flags from the value.
        """
        self.asm.emit(encode_test_r64_r64(reg, reg))
        self._emit_jcc(cc, label)

    def _emit_jcc(self, cc: int, label: str) -> None:
        """Branch to `label` when condition `cc` holds.

        ALWAYS the 6-byte rel32 form, never the 2-byte rel8 one. A rel8
        branch reaches 127 bytes and a real function body runs to thousands,
        so a short branch is not merely slower — it is a build failure
        ("j8 offset out of range") for any function with a loop or a
        comprehension in it, and picking the width per branch would mean the
        width could not be known until every label is placed. The arm64
        backend does not have to think about this: its branches are ±128 MiB.
        """
        self.asm.emit(encode_jcc_rel32(cc, 0))
        self.asm.emit_label_rel32(label, here_offset=-4)

    def _emit_jmp(self, label: str) -> None:
        """Unconditional jump. Always the 5-byte rel32 form: x86-64 has no
        short jmp the assembler will pick, and a fixed-width form means the
        emitted size never depends on how far the target turns out to be."""
        self.asm.emit(encode_jmp_rel32(0))
        self.asm.emit_label_rel32(label, here_offset=-4)

    def _record_cond_branch(self) -> None:
        """Note that the next emitted instruction is an `if`'s own branch.

        Call immediately before the Jcc. The cursor is the address the branch
        itself will land at, which is what a later proof generator's pc → word
        map is keyed on. A short-circuit `and`/`or` in a condition emits a
        Jcc of its own that closes a block identically, so the consumer cannot
        tell them apart without this list."""
        self._cond_branch_pcs.append(
            self.asm._org + len(self.asm.sections["text"]))

    def _emit_truthy_word(self, expr, reg: Reg = Reg.RAX) -> None:
        """Evaluate `expr` into `reg` so that its ZERONESS is its truthiness.

        THE truthiness conversion, and every site that tests a condition for
        truth rather than for equality goes through it. What it produces is a
        WORD whose zero/nonzero is the answer — not a 0/1 — so a branch site
        can keep the `test reg,reg` / `jcc` pair it already had and a value
        site (`s and k`) can use the word directly, which is what Python's
        `and`/`or` want anyway (they return an operand, not a bool).

        Three lowerings, chosen by `model.truthy_lowering` on the operand's
        kind, and the ZERONESS is the same for all of them:

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
                                its count.

        The row names are arm64's, x86-64's and the model's at once because
        they are the MODEL's — `model.truthy_lowering` returns one of the two
        `len_operand_lowering` rows or `nonzero` — and a second private copy of
        this decision per backend is how `~s` came to mean `s` on one
        architecture and be refused on the other. The empty string is the case
        that separates a correct lowering from a null test, so it is the case
        to check any change here against.

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
            self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
            # or: nonzero → the left's word is already the answer; and: zero →
            # the left's word is already the answer. Only the right operand is
            # ever evaluated, which is the whole of short-circuiting.
            self._emit_jcc(COND_NE if expr.op == "or" else COND_E, join)
            self._emit_truthy_word(expr.right)
            self.asm.label(join)
            return
        how = M.truthy_lowering(self._expr_str_kind(expr), expr)
        self._emit_expr(expr)
        if reg is not Reg.RAX:
            self.asm.emit(encode_mov_r64_r64(reg, Reg.RAX))
        if how == M.TRUTHY_FROM_STRLEN:
            self.asm.emit(encode_mov_r64_r64(Reg.RDI, reg))
            self._emit_extern_call(M.STRING_LENGTH_SYMBOL)
        elif how == M.TRUTHY_FROM_BLOB_FIELD:
            self.asm.emit(encode_mov_r64_rm64(reg, reg, 0))

    def _emit_branch_if_false(self, label: str) -> None:
        """Jump to `label` when RAX is zero (the condition is falsy)."""
        self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
        self._record_cond_branch()
        self._emit_jcc(COND_E, label)

    def _emit_if(self, stmt: F.IfStmt) -> None:
        """if / elif / else — the elif chain lowers to sequential tests, each
        failing branch jumping to the next test (or to else/end).

            L_i:  <test i>  --falsy--> L_{i+1}
                  <body i>  --jmp--> end
            L_else: <else body>
            end:"""
        self._if_counter += 1
        if_id = self._if_counter
        fn = self.func_name
        end_label = f"{fn}_endif_{if_id}"

        tests = [(stmt.condition, stmt.then_body)]
        for cond, body in (stmt.elifs or []):
            tests.append((cond, body))
        has_else = stmt.else_body is not None or bool(stmt.elifs)
        else_label = f"{fn}_else_{if_id}"

        for i, (cond, body) in enumerate(tests):
            self.asm.label(f"{fn}_if{if_id}_alt_{i}")
            self._emit_truthy_word(cond)
            fail = f"{fn}_if{if_id}_alt_{i + 1}" if i + 1 < len(tests) else (
                else_label if has_else else end_label)
            self._emit_branch_if_false(fail)
            for s in body:
                self._emit_stmt(s)
            if i < len(tests) - 1 or stmt.else_body is not None:
                self._emit_jmp(end_label)

        if has_else:
            self.asm.label(else_label)
            for s in (stmt.else_body or []):
                self._emit_stmt(s)
        self.asm.label(end_label)

    def _emit_loop(self, cond, body, else_body, for_info) -> None:
        """while, or for over range(), with an optional else clause.

            start:  <test>          --done--> false:
                    <body>
            step:   [for: i += step]
                    jmp start
            false:  [<else body>]
            end:

        `break` jumps to end (skipping the else); `continue` jumps to step, so
        a for-loop still advances its counter."""
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        start_label = f"{fn}_loop{wid}_start"
        step_label = f"{fn}_loop{wid}_step"
        false_label = f"{fn}_loop{wid}_false"
        end_label = f"{fn}_loop{wid}_end"

        for_range = for_info is not None
        depth = self._for_depth
        end_tmp = f"_fe{depth}"
        step_tmp = f"_fs{depth}"
        descending = False
        if for_range:
            target, rargs = for_info
            start_val, end_val, step_val = _range_info(rargs)
            lit_step = self._static_int(step_val)
            if lit_step is not None and lit_step < 0:
                descending = True
            # The bound and step are evaluated ONCE, before the loop, into
            # temps: re-evaluating them per iteration would re-run any calls
            # in the range() arguments.
            self._emit_expr(end_val)
            self._store_var(end_tmp, Reg.RAX)
            if lit_step is None:
                self._emit_expr(step_val)
                self._store_var(step_tmp, Reg.RAX)
            self._emit_expr(start_val)
            self._store_var(target, Reg.RAX)
            self._for_depth += 1

        self._loops.append({"start": start_label, "step": step_label,
                            "break": end_label,
                            "fin_depth": len(self._pending_finally)})
        try:
            self.asm.label(start_label)
            if for_range:
                self._load_var(target, Reg.RAX)
                self._load_var(end_tmp, Reg.R11)
                self.asm.emit(encode_cmp_r64_r64(Reg.RAX, Reg.R11))
                self._record_cond_branch()
                # The branch LEAVES the loop, so its condition is the negation
                # of the loop's own: an ascending range runs while i < end and
                # exits on i >= end, a descending one runs while i > end and
                # exits on i <= end. (The `while` form below cannot get this
                # wrong, because it branches on the negation of a value the
                # condition expression already produced.) Signed, since the
                # counter and the bound are int64 values.
                cc = COND_LE if descending else COND_GE
                self._emit_jcc(cc, false_label)
            else:
                self._emit_truthy_word(cond)
                self._emit_branch_if_false(false_label)

            for s in body:
                self._emit_stmt(s)

            self.asm.label(step_label)
            if for_range:
                self._emit_for_inc(target, step_val, step_tmp, lit_step)
            self._emit_jmp(start_label)

            self.asm.label(false_label)
            for s in (else_body or []):
                self._emit_stmt(s)
            self.asm.label(end_label)
        finally:
            if for_range:
                self._for_depth -= 1
            self._loops.pop()

    def _emit_for_inc(self, target: str, step, step_tmp: str, lit_step) -> None:
        """Advance a for-range counter by `step`."""
        self._load_var(target, Reg.RAX)
        if lit_step is not None:
            if lit_step == 0:
                raise CodegenError("range() step must not be zero")
            if 0 < lit_step <= 0x7FFFFFFF:
                self.asm.emit(encode_add_r64_imm32(Reg.RAX, lit_step))
            elif -0x80000000 <= lit_step < 0:
                self.asm.emit(encode_sub_r64_imm32(Reg.RAX, -lit_step))
            else:
                self.asm.emit(encode_mov_r64_imm32(Reg.R11, lit_step))
                self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.R11))
        else:
            # A negative literal arrives as UnaryOp('-', IntLiteral(n)), so
            # both spellings have to reduce to a static step.
            self._load_var(step_tmp, Reg.R11)
            self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.R11))
        self._store_var(target, Reg.RAX)

    # ── containers ───────────────────────────────────────────────────
    #
    # A list, tuple, set or dict is a BLOB in the frame, not a heap object:
    #     list/tuple/set:  [count:i64][element 0]…[element n-1]
    #     dict:            [count:i64][key 0][value 0]…      (pairs, 16 bytes)
    #     slice view:      [count:i64][element …]            (a materialized copy)
    # and its VALUE is the blob's address. The layout is the arm64 backend's
    # byte for byte, so a value produced by either backend describes the same
    # thing and a future proof model only has to learn it once.

    def _reserve_blob(self, nbytes: int, what: str) -> int:
        """Reserve `nbytes` of blob area, returning its RBP-relative offset.

        The whole blob is reserved BEFORE any element is evaluated, so a
        nested container lands above its parent rather than inside the region
        the parent is still filling."""
        if self._list_cursor + nbytes > self._blob_cap:
            raise CodegenError(
                f"{what} exceed the formal frame "
                f"({self._list_cursor + nbytes} > {self._blob_cap} bytes)")
        offset = self._list_cursor
        self._list_cursor += nbytes
        return offset

    def _emit_elem_addr(self, base_reg: Reg, index_reg: Reg, dst_reg: Reg,
                        header: int = 8, scale: int = 3) -> None:
        """dst = base + header + (index << scale) — one blob element.

        The blob's elements start `header` bytes in (past the count, or past
        count+key for a dict pair) and are `1 << scale` bytes apart. Written
        as a shift and two adds rather than a multiply of a partly-built
        address, because `(base + header) * index` is a different — and
        silently plausible — address."""
        self.asm.emit(encode_mov_r64_r64(dst_reg, index_reg))
        self.asm.emit(encode_shift_r64_imm8("<<", dst_reg, scale))
        self.asm.emit(encode_add_r64_imm32(dst_reg, header))
        self.asm.emit(encode_add_r64_r64(dst_reg, base_reg))

    def _emit_blob_base(self, offset: int, reg: Reg) -> None:
        """reg = RBP + offset — the blob's address.

        RBP-relative rather than RSP-relative because RSP moves while
        expressions are evaluated (pushed temporaries) but a blob lives until
        the function returns."""
        self.asm.emit(encode_lea_r64_rm64(reg, Reg.RBP, offset))

    def _emit_empty_blob(self) -> None:
        """The empty container: eight bytes with a zero count, base in RAX.

        `List()`, `List[Int]()`, `Dict()` and the rest of
        `model.EMPTY_BLOB_CTORS`, and it is `_emit_list` with `n == 0` — the
        same eight bytes, the same `[count][elements]` layout and the same
        reservation, because an empty container IS the zero-element literal.
        The instruction sequence is `_emit_list`'s with its loop deleted, and
        the shared parts (`_reserve_blob`, `_emit_blob_base`, `_emit_mov_imm`,
        the store) are the same calls in the same order, so the two layouts and
        the two architectures cannot drift.

        Its own method rather than a call into `_emit_list` with a synthesised
        `ListExpr`, for the reason arm64's `_emit_empty_blob` gives at length:
        `_emit_list` also handles a star-unpack and reserves CAPACITY slots
        when the function appends to the literal, and neither applies to a
        constructor's result — appending to an empty container built by
        `List()` is a different question that `_scan_list_caps` does not answer.
        """
        offset = self._reserve_blob(8, "empty containers")
        self._emit_blob_base(offset, Reg.R11)
        self._emit_mov_imm(Reg.R10, 0)
        self.asm.emit(encode_mov_rm64_r64(Reg.R11, 0, Reg.R10))
        self._emit_blob_base(offset, Reg.RAX)

    def _emit_list(self, expr) -> None:
        """A list/tuple/set literal → its blob address in RAX.

        Elements are int64s, string addresses or inner-blob addresses. `*xs`
        has no compile-time length and raises; `*literal` is expanded
        statically.

        The blob is allocated with CAPACITY slots, not `n` of them, when the
        function appends to this literal (see `_scan_list_caps`): the count
        field still starts at `n`, so every reader of the blob is unchanged,
        and the slots past the count are the room `append` writes into."""
        elements = list(expr.elements)
        flat = []
        for el in elements:
            if isinstance(el, F.UnaryOp) and el.op == "*":
                if isinstance(el.operand, (F.ListExpr, F.TupleExpr)):
                    flat.extend(el.operand.elements)
                    continue
                raise CodegenError(
                    "star-unpack of a non-literal into a list is not "
                    "lowered on the formal x86-64 path")
            flat.append(el)
        n = len(flat)
        cap = max(n, self._list_caps.get(id(expr), n))
        offset = self._reserve_blob(8 * (1 + cap), "list literals")
        self._emit_blob_base(offset, Reg.R11)
        self._emit_mov_imm(Reg.R10, n)
        self.asm.emit(encode_mov_rm64_r64(Reg.R11, 0, Reg.R10))
        for i, el in enumerate(flat):
            self._emit_expr(el)
            # Recompute the base: element emission (a call, a string LEA)
            # clobbers R11.
            self._emit_blob_base(offset, Reg.R11)
            self.asm.emit(encode_mov_rm64_r64(Reg.R11, 8 * (i + 1), Reg.RAX))
        self._emit_blob_base(offset, Reg.RAX)

    def _emit_len(self, e) -> None:
        """`len(x)` — a blob's count field, or a string's `strlen`.

        A builtin, intercepted here for the same reason `range` is. Left to the
        extern path it became a call to a symbol `len` that libSystem does not
        define, so the image built and then aborted in the loader with
        "Symbol not found: _len" — the same defect the arm64 backend had.

        TWO lowerings, chosen by `model.len_operand_lowering` on the operand's
        kind, and the choice is the model's so the two architectures cannot
        make it differently:

          BLOB   a list is `[count][elements]` and a list value IS its blob
                 address in RAX, so this is one load from offset 0 (the same
                 read the comprehension generator already does for its own
                 count).

          STRING a string is a bare `char *` to NUL-terminated bytes, so its
                 length is not a field but a COMPUTATION: `strlen` is the
                 length of a NUL-terminated `char *` by definition. Same libc
                 call `endswith`, `count` and `f.write(s)` already make here.

        The string half used to be a refusal, and the refusal was narrower than
        the bug: it fired on a SYNTACTIC `StringLiteral` and on an identity
        type-constructor, and for every other shape it fell through to the
        count-field load — which for a `char *` reads the first eight
        CHARACTERS. Measured on this backend and on arm64, `len(m)` where
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
            self._emit_expr(operand)          # RAX = the char *
            # RDI, not RAX: an expression leaves its value in RAX and the first
            # ARGUMENT register is RDI. The same note as in `_emit_str_affix`,
            # and the same consequence — strlen dereferences whatever RDI held,
            # so omitting the move is a fault inside libc rather than a wrong
            # answer. Measured: with it omitted, `len(m)` for `m = "hello"`
            # segfaulted on x86-64 while arm64 returned 5, and
            # `len("  hi".lstrip())` returned 4 instead of 2.
            self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
            self._emit_extern_call(M.STRING_LENGTH_SYMBOL)
            return
        self._emit_expr(operand)
        # RAX holds the blob address; the count is its first 8 bytes.
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RAX, 0))

    # ── print ────────────────────────────────────────────────────────────

    # ── what a value is, for the paths that must decide before emitting ──

    def _expr_str_kind(self, expr):
        """What `expr` holds: "str", "int", or None if undecidable.

        Two sources, and `_string_vars` WINS where they disagree: it is
        flow-sensitive and tracks what the emission of this very function has
        bound so far, so it is strictly better informed than the
        whole-function `ValueKinds`, which is what covers the shapes
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

        The same rule as the arm64 backend's, so the two architectures cannot
        disagree about which receivers are descriptors: `_fd_vars`, a name bound
        from `open` in an earlier statement of this function and its aliases.

        A frame slot is not covered (proving a field holds a descriptor is
        cross-field flow), and neither is a CALL RESULT — `open(p, "w").write(s)`
        refuses, because a method on a call result is not a value receiver on
        this path at all (`_is_value_receiver`), which is a separate pre-existing
        gap the arm64 docstring records in full."""
        if isinstance(expr, F.IdentExpr):
            return expr.name in self._fd_vars
        if isinstance(expr, F.MemberExpr):
            key = _member_slot_key(expr)
            return key is not None and key in self._fd_vars
        return False

    def _print_call(self, args: list):
        """`(format, operands)` for a `print` of `args`.

        A literal operand contributes a fragment to the format and NO operand
        to the call; a value contributes a conversion and one operand. Passing
        the literals as well is the mistake this shape exists to prevent: the
        format would ask printf for fewer arguments than it was handed, and
        everything after the first literal would be read one slot late.

        The int conversion follows the operand's own type. The model's default
        integer is UNSIGNED, and `%lld` on a UInt64 whose top bit is set would
        print a negative number, so signedness decides; the width does not, a
        narrow int already sign/zero-extends to the word it is stored in."""
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
                    f"string or a number on the formal x86-64 path, and "
                    f"guessing would print an address as if it were text (or "
                    f"a number as if it were text). Annotate the name, or "
                    f"print a literal, or bind it to a literal first")
            operands.append(a)
        return frags, operands

    def _print_kwargs(self, e):
        """`print`'s `sep=` / `end=` / `file=`, as (sep, end). Only literals.

        `file=` is refused unless it is stdout, because this model has exactly
        one stream and a `file=sys.stderr` that quietly went to stdout would be
        a program whose diagnostics are missing rather than one that failed."""
        sep, end = " ", "\n"
        for k, v in e.kwargs:
            if not isinstance(v, F.StringLiteral):
                raise CodegenError(
                    f"print({k}=...) must be a string literal on the formal "
                    f"x86-64 path (got {type(v).__name__}): the separator and "
                    f"the line ending are baked into the format string, which "
                    f"is built before the call is emitted")
            if k == "sep":
                sep = v.value
            elif k == "end":
                end = v.value
            elif k == "file":
                if not (isinstance(v, F.MemberExpr) and v.member == "stdout"):
                    raise CodegenError(
                        f"print(file=...) other than sys.stdout is not lowered "
                        f"on the formal x86-64 path: this model has one output "
                        f"stream")
            else:
                raise CodegenError(
                    f"print() has no keyword argument {k!r} on the formal "
                    f"x86-64 path (supports sep, end, file)")
        return sep, end

    def _emit_print(self, e) -> None:
        """`print(...)` — a real call to the C library's `printf`.

        Not a stub and not a dropped call: the format string is built here out
        of what each operand statically is and the operands are passed as
        printf's varargs, so what lands on stdout is what the source says. Left
        to the extern path this was a call to a symbol `print`, which no C
        library defines: the image built and then aborted in the loader.

        `print()` with no arguments still prints a blank line, and the call's
        value is `None` — the format has no conversions, so printf reads no
        varargs and the register state afterwards is irrelevant."""
        sep, end = self._print_kwargs(e)
        frags, operands = self._print_call(list(e.args))
        fmt = M.print_format(frags, sep, end)
        self._emit_call(_call("printf", [F.StringLiteral(fmt)] + operands))

    # ── methods on a value ───────────────────────────────────────────────

    def _is_value_receiver(self, obj) -> bool:
        """True when `obj` is a VALUE, so `obj.m(...)` is a method call.

        A module path (`os.path.join`) roots at a name too, so the test is
        whether that name is one of this function's own; register allocation
        knows every local, parameters included.

        A string LITERAL is a value as unambiguously as a name is, and it has
        to be here: with only `append`/`write`/`close` lowerable, every one of
        them needs a NAME to mutate or to file-descriptor, so a literal
        receiver could not arise — and `"x".strip()` fell through to the extern
        path and became a call to a symbol spelled `x.strip`, which is the
        flat-symbol bug this predicate exists to prevent. The arm64 backend
        found the same hole at the same time; the two must agree, or `"x".count("x")`
        works on one architecture and dies in dyld on the other.

        A FRAME SLOT is a value here too, and has to be: `h.f.m(...)` reads
        `[h + 8k]` and hands that word to the callee, so it is a method call on
        a value and `model.value_method_refusal` decides it. A frame slot is
        deliberately not a register or spill home, so this membership test has
        to be extended rather than left to find it by accident; without it the
        chain falls to the extern path and becomes a call against a symbol
        spelled after the chain. arm64's copy of this function says the same
        thing about the same shape, and the two have to keep agreeing."""
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

    def _emit_value_method(self, e, method: str) -> None:
        """`recv.method(...)` where `recv` is a value."""
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
                f"x86-64 path (got {[k for k, _v in e.kwargs]})")
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
            # own was answered by calling `str.count` on its receiver.  The
            # arm64 backend carries the full reasoning; see its `else`.
            self._emit_str_count(e)
        else:
            # `_emit_str_count` WAS this arm; `count` is an explicit arm above
            # now.  The arm64 backend carries the full reasoning — the short
            # version is that a zero-argument method with no lowering was
            # reported as `str.count() takes exactly one argument (got 0)`,
            # which is how a `value()` newly made answerable by the pointer
            # value model reported `str.count` as its blocker.  Both backends
            # now say what the arm means, and both name `how`, so a table entry
            # with no arm is visible on either architecture.
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
    # The arm64 backend carries the reasoning; the DECISION is
    # `model.dereference_lowering`, shared, so the two architectures cannot
    # disagree about a load's width — which is the failure mode that matters
    # here, because a disagreement is not a diagnostic that differs but a
    # `movzbl` on one side and a `movq` on the other over the same bytes.
    #
    #   ("load", 1, unsigned)  movzbl (%rax), %eax      0F B6  — UInt8/Byte
    #   ("load", 1, signed)    movsbq (%rax), %rax      48 0F BE — Int8
    #   ("load", 2, unsigned)  movzwl (%rax), %eax      0F B7  — UInt16
    #   ("load", 2, signed)    movswq (%rax), %rax      48 0F BF — Int16
    #   ("load", 4, unsigned)  movl   (%rax), %eax      8B     — UInt32
    #   ("load", 4, signed)    movslq (%rax), %rax      48 63  — Int32/c_int
    #   ("load", 8, *)         movq   (%rax), %rax      48 8B  — Int64/a pointer
    #
    # A STRUCT pointee has no instruction here and that is a decision, not an
    # omission: the derivation says the answer is the receiver (a struct's value
    # IS its frame address), and emitting it today returns 0 where the source
    # says 22 on both architectures, because nothing recognises a name bound
    # through a pointer as a frame holder.  `model.dereference_lowering` says so
    # at length; the next step is one line in the holder fixpoint.
    def _emit_dereference(self, e, method: str) -> None:
        if e.args or e.kwargs:
            raise CodegenError(
                f"{_dotted(e.func)}() takes no arguments on the formal x86-64 "
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
        self._emit_expr(obj)                    # RAX = the address
        base = Reg(0)
        dst = Reg(0)
        if width == 1:
            self.asm.emit(encode_movsx_r64_rm8(dst, base) if signed
                          else encode_movzx_r64_rm8(dst, base))
        elif width == 2:
            self.asm.emit(encode_movsx_r64_rm16(dst, base) if signed
                          else encode_movzx_r64_rm16(dst, base))
        elif width == 4:
            self.asm.emit(encode_movsx_r64_rm32(dst, base) if signed
                          else encode_mov_r32_rm32(dst, base))
        else:
            self.asm.emit(encode_mov_r64_rm64(dst, base))

    # ── methods on a string ───────────────────────────────────────────────
    #
    # The arm64 backend carries the reasoning; this is the same list of
    # methods for the same reasons, with x86-64 instructions. `lstrip`,
    # `startswith`, `endswith`, `find` and `count` are pointer-bounded — their
    # answer is a function of the bytes from the receiver to its NUL — and
    # libSystem already implements each one, so what is emitted is a CALL and
    # not a second implementation of `strstr` that could be subtly wrong.
    # `strip`/`rstrip`/`upper`/`split`/... are refused by name, with the
    # reason in model.LENGTH_DEPENDENT_METHODS, which both backends share so
    # the two architectures cannot disagree about what is supported.

    def _method_recv_kind(self, e):
        """What the receiver of a method call holds, for the model's guard.

        The same question `print` asks, under the same precedence — the
        flow-sensitive `_string_vars` first, the whole-function `ValueKinds`
        second. It is load-bearing: without it `mlir_value.value()` (359 of the
        method calls in the stdlib) would be lowered as a string operation on
        whatever word the receiver holds."""
        obj = e.func.obj if isinstance(e.func, F.MemberExpr) else None
        return None if obj is None else self._expr_str_kind(obj)

    def _emit_str_lstrip(self, e) -> None:
        """`s.lstrip()` — an INTERIOR pointer to the first non-whitespace byte.

        `strspn(s, STRIP_CHARS)` IS the left-strip: it returns the length of the
        initial segment of `s` made only of those characters, so `s + that` is
        the answer. Nothing is written and nothing is copied, which is what
        makes this pointer-bounded and `strip` not.

        The character set is model.STRIP_CHARS, ONE definition for both
        backends. An earlier version hand-wrote the scan loop per architecture
        and each copy had its own bug."""
        # One push, so [rsp] = s.
        self._emit_expr(e.func.obj)
        self._push_slot(Reg.RAX)
        self._emit_expr(F.StringLiteral(M.STRIP_CHARS))
        self.asm.emit(encode_mov_r64_r64(Reg.RSI, Reg.RAX))    # accept set
        self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RSP, 0))  # s
        self._emit_extern_call("strspn")
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, 0))
        self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.RCX))     # s + strspn
        self._pop_slot(Reg.R11)          # never RAX — it holds the answer

    # `_push_slot` pushes, so the LAST thing pushed is at [rsp+0] and each
    # earlier one is one _SLOT further up. Every offset below is counted from
    # that, and the rule is worth stating because getting it backwards is
    # invisible: the call still happens, still returns a value, and the
    # arguments are simply the wrong two strings. `strstr(needle, haystack)`
    # is a well-defined NULL, so a reversed pair of arguments made every
    # `find` return -1 and every `count` return 0 — plausible-looking wrong
    # answers, which is the one outcome these methods must never produce.

    def _emit_str_affix(self, e, *, at_end: bool) -> None:
        """`s.startswith(p)` / `s.endswith(p)` — a bounded compare, 0 or 1.

        Both are `strncmp(...) == 0`, and `strncmp` stops at the first
        difference or at a NUL in either operand, so neither can read past the
        end of a NUL-terminated buffer. An empty affix is a zero-length
        compare, which compares equal — the "yes" Python gives.

        `endswith` compares from `s + len(s) - len(p)`, so the lengths are
        needed first AND the suffix must be shown not to be longer than the
        receiver: without that test the subtraction underflows and `strncmp`
        reads before the start of the buffer. Unsigned compares, matching the
        signedness `strlen` actually returns."""
        args = list(e.args)
        name = "str.endswith" if at_end else "str.startswith"
        if len(args) != 1:
            raise CodegenError(
                f"{name}() takes exactly one argument on this path "
                f"(got {len(args)})")
        # RDI, not RAX: an expression leaves its value in RAX and the first
        # ARGUMENT register is RDI. Omitting the move is not a wrong-answer bug
        # but a fault inside libc — strlen dereferences whatever RDI held.
        if not at_end:
            # push s, then p  =>  [rsp] = p, [rsp+16] = s
            self._emit_expr(e.func.obj)
            self._push_slot(Reg.RAX)
            self._emit_expr(args[0])
            self._push_slot(Reg.RAX)
            self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 0))     # p
            self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
            self._emit_extern_call("strlen")           # RAX = len(p)
            self.asm.emit(encode_mov_r64_r64(Reg.RDX, Reg.RAX))         # n
            self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RSP, 16))    # s
            self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 0))     # p
            self._emit_extern_call("strncmp")
            # `_emit_setcc_bool`, not a bare `sete`: a SETcc writes only the
            # low byte and RAX still holds strncmp's return value, so the
            # answer would be 0x...0000FF and every later comparison of it
            # wrong. The helper's own docstring says so.
            self._emit_setcc_bool(Reg.RAX, "sete")
            # Pop into R11, never RAX: arm64's epilogue is an `add rsp, N` that
            # leaves the result alone, but x86-64's _pop_slot WRITES its target
            # — popping into RAX threw away the 0/1 the setcc had just produced.
            self._pop_slot(Reg.R11)
            self._pop_slot(Reg.R11)
            return
        # push s, p, len(p), len(s)
        #   => [rsp] = len(s), [rsp+16] = len(p), [rsp+32] = p, [rsp+48] = s
        self._while_counter += 1
        no_label = f"{self.func_name}_endswith{self._while_counter}_no"
        done_label = f"{self.func_name}_endswith{self._while_counter}_done"
        self._emit_expr(e.func.obj)
        self._push_slot(Reg.RAX)                      # s
        self._emit_expr(args[0])
        self._push_slot(Reg.RAX)                      # p
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 0))     # p
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
        self._emit_extern_call("strlen")
        self._push_slot(Reg.RAX)                      # len(p)
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 32))    # s
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
        self._emit_extern_call("strlen")
        self._push_slot(Reg.RAX)                      # len(s)
        # len(s) < len(p) -> cannot be a suffix
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, 0))      # len(s)
        self.asm.emit(encode_mov_r64_rm64(Reg.RDX, Reg.RSP, 16))     # len(p)
        self.asm.emit(encode_cmp_r64_r64(Reg.RCX, Reg.RDX))
        self._emit_jcc(COND_B, no_label)
        # RAX = s + len(s) - len(p)
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 48))     # s
        self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.RCX))
        self.asm.emit(encode_sub_r64_r64(Reg.RAX, Reg.RDX))
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))         # s+ls-lp
        self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 32))    # p
        self.asm.emit(encode_mov_r64_rm64(Reg.RDX, Reg.RSP, 16))    # len(p)
        self._emit_extern_call("strncmp")
        self._emit_setcc_bool(Reg.RAX, "sete")
        self._emit_jmp(done_label)
        self.asm.label(no_label)
        self._emit_mov_imm(Reg.RAX, 0)
        self.asm.label(done_label)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)

    def _emit_str_find(self, e) -> None:
        """`s.find(p)` — the index of the first occurrence, or -1.

        `strstr` walks both operands to their NULs, so the answer is exactly
        the difference of two pointers, and the case that has to be handled is
        "not found", which is a NULL rather than a position: -1 is what Python
        returns, and returning the NULL's own low bits would be a
        plausible-looking address. An empty needle makes `strstr` return the
        receiver itself, i.e. 0, which is also what Python returns.

        The argument order is `strstr(HAYSTACK, NEEDLE)` and it is the whole
        method: `strstr("bc", "abcabc")` is a well-defined NULL, so getting it
        backwards does not crash and does not look wrong in the image — it
        returns -1 for every haystack that contains its needle."""
        args = list(e.args)
        if len(args) != 1:
            raise CodegenError(
                f"str.find() takes exactly one argument on this path "
                f"(got {len(args)})")
        self._while_counter += 1
        no_label = f"{self.func_name}_find{self._while_counter}_no"
        done_label = f"{self.func_name}_find{self._while_counter}_done"
        # push s, then p  =>  [rsp] = p, [rsp+16] = s
        self._emit_expr(e.func.obj)
        self._push_slot(Reg.RAX)                      # [rsp+16] = s
        self._emit_expr(args[0])
        self._push_slot(Reg.RAX)                      # [rsp] = p
        self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RSP, 16))    # haystack
        self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 0))     # needle
        self._emit_extern_call("strstr")
        self.asm.emit(encode_cmp_r64_imm8(Reg.RAX, 0))
        self._emit_jcc(COND_E, no_label)
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, 16))    # s
        self.asm.emit(encode_sub_r64_r64(Reg.RAX, Reg.RCX))
        self._emit_jmp(done_label)
        self.asm.label(no_label)
        self._emit_mov_imm(Reg.RAX, -1)
        self.asm.label(done_label)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)

    def _emit_str_count(self, e) -> None:
        """`s.count(p)` — how many NON-OVERLAPPING occurrences.

        Non-overlapping is Python's rule and it is the whole of the loop: each
        match advances the cursor by the needle's length, so "aaa".count("aa")
        is 1 and not 2. Overlapping it would be a one-instruction difference
        and a silently wrong count.

        The empty needle is the case with no loop at all — it matches at each of
        the L+1 positions in a string of length L, so the count is
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
        end = f"{fn}_count{n}_end"
        # push s, p, len(p), cursor, count
        #   => [rsp] = count, [rsp+16] = cursor, [rsp+32] = len(p),
        #      [rsp+48] = p, [rsp+64] = s
        self._emit_expr(e.func.obj)
        self._push_slot(Reg.RAX)                      # s
        self._emit_expr(args[0])
        self._push_slot(Reg.RAX)                      # p
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 0))     # p
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
        self._emit_extern_call("strlen")
        self._push_slot(Reg.RAX)                      # len(p)
        # Still three slots deep here: [rsp] = len(p), [rsp+16] = p,
        # [rsp+32] = s — NOT the offsets the five-slot layout below uses.
        # Reading len(p) from the five-slot table's [rsp+16] loads `p` itself,
        # a non-zero pointer, so the empty-needle branch is never taken and
        # count("") spins forever in the loop.
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, 0))     # len(p)
        self.asm.emit(encode_cmp_r64_imm8(Reg.RCX, 0))
        self._emit_jcc(COND_E, empty)
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 32))    # s
        self._push_slot(Reg.RAX)                      # cursor
        self._emit_mov_imm(Reg.RAX, 0)
        self._push_slot(Reg.RAX)                      # count = 0
        self.asm.label(loop)
        self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RSP, 16))    # cursor
        self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 48))    # p
        self._emit_extern_call("strstr")
        self.asm.emit(encode_cmp_r64_imm8(Reg.RAX, 0))
        self._emit_jcc(COND_E, done)
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, 0))      # count
        self.asm.emit(encode_add_r64_imm8(Reg.RCX, 1))
        self.asm.emit(encode_mov_rm64_r64(Reg.RSP, 0, Reg.RCX))
        # cursor = hit + len(p)
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, 32))    # len(p)
        self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.RCX))
        self.asm.emit(encode_mov_rm64_r64(Reg.RSP, 16, Reg.RAX))
        self._emit_jmp(loop)
        self.asm.label(empty)
        # Three slots deep: [rsp+32] = s. The answer goes into [rsp+0], which
        # on this path holds len(p) == 0 and is dead — and it has to go there
        # rather than staying in RAX, because `done` reads the answer from
        # [rsp+0] and a path that branches there with the answer only in RAX
        # returns the loop's counter instead.
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 32))    # s
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
        self._emit_extern_call("strlen")
        self.asm.emit(encode_add_r64_imm8(Reg.RAX, 1))   # L+1 positions
        self.asm.emit(encode_mov_rm64_r64(Reg.RSP, 0, Reg.RAX))
        # Release the THREE slots this path actually pushed and leave. Branching
        # to `done` instead would run its five pops over three pushes and leave
        # RSP 32 bytes too high — which does not fault here, it makes the NEXT
        # statement's stack-relative operand loads read the wrong slots. A
        # following printf then printed the image's own bytes. The arm64
        # backend cannot hit this: its window is one `sub sp` at the top and
        # one `add sp` at the bottom, so both paths share a depth.
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._emit_jmp(end)
        self.asm.label(done)
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 0))      # count
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self.asm.label(end)

    def _emit_str_membership(self, left, right, invert: bool) -> None:
        """`needle in haystack` with a STRING haystack — `strstr`/`strchr`.

        The measured state of this before it existed, on BOTH backends: `if
        "ell" in s:` for `s = "hello"` terminated the process with SIGBUS. A
        string haystack had no case here at all, so the blob scan read the
        first eight bytes of the CHARACTERS as a `[count]` header and walked
        off the end of the mapping — and where the count it read happened to
        be small enough not to fault, it returned FALSE, which is a wrong
        answer rather than a crash.

        Two libc calls, one per needle shape, and which one is decided by
        `model.string_membership_lowering` so that this backend and the arm64
        one cannot disagree about what a given `in` is:

            needle is a char *   ->  strstr(HAYSTACK, NEEDLE) != NULL
            needle is a byte     ->  strchr(HAYSTACK, BYTE)    != NULL

        THE ARGUMENT ORDER IS THE WHOLE METHOD for `strstr`, and it is the
        reason this is not a one-liner: `strstr("bc", "abcabcabc")` is a
        well-defined NULL, so getting it backwards does not crash, does not
        look wrong in the image, and returns FALSE for every haystack that
        contains its needle — which is every real use of `in`. SysV puts the
        haystack in RDI and the needle in RSI, and an expression leaves its
        value in RAX, so both operands are moved across explicitly.

        Two libc calls rather than a hand-written scan, for the reason the
        `strspn` change gives for `lstrip`: the call IS the algorithm, it
        cannot be half-right, and there is then nothing here to keep in step
        between two architectures.

        THE RESULT IS 0/1 IN RAX, and that is not a detail: there is no BOOL
        kind distinct from INT on this path (which is why `__mlir_bool__` is
        refused), so "0/1" and "a bool" are the same thing here. `not in`
        inverts at the end, once, rather than at each exit.

        EDGE CASES, all of which the caller reaches:

          * an EMPTY needle is TRUE, and `strstr` agrees: it returns the
            haystack itself, which is non-NULL. A membership test that says an
            empty needle is absent is wrong in the direction that HIDES bugs.
          * a needle LONGER than the haystack is FALSE, and `strstr` agrees:
            the terminator cannot match a non-terminator byte.
          * a needle at offset 0 and a needle at the very END both come back
            non-NULL, and both are TRUE.
          * the byte case with byte == 0 is the ONE thing libc gets wrong for
            this representation: `strchr(s, 0)` returns a pointer to the
            terminator, so a bare `!= NULL` would make `0 in "abc"` TRUE where
            Python says FALSE — and on this path it is certainly false, since
            the only NUL in a string is the one that ends it. So the byte is
            tested against zero IN FRONT of the call and the answer is
            materialised without calling anything. The test is `je` to the
            absent block and not `jne`: the inverted test inverts the whole
            table, so every real byte comes back absent and only `0 in s`
            comes back present.
        """
        # Both operands literal is a COMPILE-TIME answer, taken first because
        # it is the one case where the answer is not a question about the
        # representation. The empty needle is TRUE here, which is Python's
        # rule and also what `strstr` would say, so the constant and the call
        # cannot disagree.
        if isinstance(left, F.StringLiteral) and isinstance(right, F.StringLiteral):
            # The EMPTY needle is TRUE, which is Python's rule and what
            # `strstr` returns for it (the haystack itself, non-NULL). Folding
            # it to False because `bool("")` is False made the
            # both-operands-literal case disagree with the call the same
            # expression makes when either side is a name.
            found = left.value == "" or left.value in right.value
            self._emit_mov_imm(Reg.RAX, (0 if found else 1) if invert
                               else (1 if found else 0))
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
        self._if_counter += 1
        mid = self._if_counter
        fn = self.func_name
        hit = f"{fn}_smh{mid}"
        miss = f"{fn}_smn{mid}"
        end = f"{fn}_smx{mid}"
        # push haystack, then needle  =>  [rsp] = needle, [rsp+16] = haystack.
        # Both have to survive the call, and every register is caller-saved
        # across one, so both go to the stack — the same discipline
        # `_emit_str_find` and `_emit_str_count` use, and for the same reason.
        self._emit_expr(right)
        self._push_slot(Reg.RAX)                      # [rsp+16] = haystack
        self._emit_expr(left)
        self._push_slot(Reg.RAX)                      # [rsp]    = needle
        if how == M.STRING_MEMBERSHIP_BYTE:
            # The needle is a byte VALUE, not a pointer, so it is masked here
            # rather than dereferenced: `s[1]` and a subscript are how a byte
            # is spelled, and both are integers that may be wider than 8 bits.
            self.asm.emit(encode_and_r64_imm8(Reg.RAX, 8))
            self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 0))
            self.asm.emit(encode_test_r64_r64(Reg.RSI, Reg.RSI))
            self._emit_jcc(COND_E, miss)              # 0 in s is False
        else:
            self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 0))
        self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RSP, 16))
        self._emit_extern_call(M.STRING_BYTE_SEARCH_SYMBOL if how ==
                               M.STRING_MEMBERSHIP_BYTE
                               else M.STRING_SEARCH_SYMBOL)
        self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
        self._emit_jcc(COND_NE, hit)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._emit_mov_imm(Reg.RAX, 0)                # NULL → absent
        self._emit_jmp(end)
        self.asm.label(miss)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._emit_mov_imm(Reg.RAX, 0)
        self._emit_jmp(end)
        self.asm.label(hit)
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        self._emit_mov_imm(Reg.RAX, 1)                # non-NULL → present
        self.asm.label(end)
        if invert:
            # NOT as a TEST/SETcc on the 0/1 already in RAX rather than as
            # three separate inverted constants at the three exits: three
            # inversions is three chances for one of them to be the missing one.
            self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
            self._emit_setcc_bool(Reg.RAX, "sete")

    def _emit_list_append(self, e) -> None:
        """`xs.append(v)` — store v at the blob's count and bump the count.

        The blob is `[count][elem0]…` in the frame, so there is no room to
        grow one: the capacity is a compile-time number (`_scan_list_caps`) and
        the store is checked against it, exiting(1) rather than writing past
        the blob. Appending more times than the scan found — inside a loop —
        stops the program instead of quietly corrupting the frame, the same
        bargain every other bounded container operation on this path makes.

        Returns 0, this model's `None`; `list.append` returns None, and
        returning the new count would be a value Python does not have."""
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
                f"list.append() is not lowered on the formal x86-64 path: a "
                f"list blob lives in the frame, so the room an append needs "
                f"has to be known when the list is built. This one is not "
                f"(the receiver is not a list literal this function appends "
                f"to, or it is also bound to something that is not a list)")
        self._push_slot(Reg.RAX)
        self._emit_expr(recv)                      # RAX = base
        self.asm.emit(encode_mov_r64_r64(Reg.R11, Reg.RAX))
        self._push_slot(Reg.R11)                   # [rsp] = base
        self._emit_expr(args[0])                   # RAX = value
        self._push_slot(Reg.RAX)                   # [rsp] = value
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.RSP, 0))   # value
        self.asm.emit(encode_mov_r64_rm64(Reg.R11, Reg.RSP, 16))  # base
        self.asm.emit(encode_mov_r64_rm64(Reg.R8, Reg.R11, 0))   # count
        self.asm.emit(encode_cmp_r64_imm32(Reg.R8, cap))
        self._emit_setcc_bool(Reg.R8, "setae")
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        oob = f"{fn}_appoob{wid}"
        ok = f"{fn}_appok{wid}"
        self._emit_jcc_bool(Reg.R8, COND_NE, oob)
        self._emit_jmp(ok)          # in range: skip the exit
        self.asm.label(oob)
        self._emit_call_exit(1)
        self.asm.label(ok)
        self.asm.emit(encode_mov_r64_rm64(Reg.R8, Reg.R11, 0))   # count again
        self._emit_elem_addr(Reg.R11, Reg.R8, Reg.RDI)           # the slot
        self.asm.emit(encode_mov_rm64_r64(Reg.RDI, 0, Reg.R10))   # store value
        self.asm.emit(encode_add_r64_imm32(Reg.R8, 1))
        self.asm.emit(encode_mov_rm64_r64(Reg.R11, 0, Reg.R8))    # count = n+1
        self._pop_slot(Reg.RAX)
        self._pop_slot(Reg.RAX)
        self._pop_slot(Reg.RAX)
        self._emit_mov_imm(Reg.RAX, 0)             # None

    def _emit_file_write(self, e) -> None:
        """`f.write(s)` — `write(fd, s, strlen(s))` through the C library.

        `open(...)` on this path is already the C library's `open` (left to
        the extern path, which is right for it), so the receiver of a file
        method IS a descriptor. The length has to be computed, because a
        `char *` here has no header — the same reason `len()` of a string is
        refused."""
        args = list(e.args)
        if len(args) != 1:
            raise CodegenError(
                f"file.write() takes exactly one argument on this path "
                f"(got {len(args)})")
        self._emit_expr(e.func.obj)                # RAX = fd
        self._push_slot(Reg.RAX)                   # [rsp] = fd
        self._emit_expr(args[0])                   # RAX = string
        # An expression leaves its value in RAX; the first argument register
        # is RDI. AL has to be zeroed for a variadic callee, which means after
        # the value is safely in its slot.
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
        self._push_slot(Reg.RAX)                   # [rsp] = string
        self._emit_mov_imm(Reg.RAX, 0)
        self._emit_extern_call("strlen")           # RAX = length
        self._push_slot(Reg.RAX)                   # [rsp] = length
        # Three values, three slots: [rsp] length, [rsp+16] string,
        # [rsp+32] descriptor. The descriptor is the DEEPEST of the three
        # because the string was pushed after it.
        self.asm.emit(encode_mov_r64_rm64(Reg.RDX, Reg.RSP, 0))
        self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 16))
        self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RSP, 32))
        self._emit_mov_imm(Reg.RAX, 0)
        self._emit_extern_call("write")
        self._pop_slot(Reg.RAX)
        self._pop_slot(Reg.RAX)
        self._pop_slot(Reg.RAX)

    def _emit_file_close(self, e) -> None:
        """`f.close()` — the C library's `close` on the descriptor."""
        if e.args:
            raise CodegenError(
                f"file.close() takes no arguments on this path "
                f"(got {len(e.args)})")
        self._emit_expr(e.func.obj)
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
        self._emit_mov_imm(Reg.RAX, 0)
        self._emit_extern_call("close")

    def _emit_open(self, e) -> None:
        """`open(path, mode)` — the C library's `open(2)`.

        The mode is a Python spelling and the C function wants a flag word, so
        the translation happens here: passing the mode STRING as the flags word
        is not a wrong answer, it is a wrong SYSTEM CALL.

        A descriptor is returned whatever happens, and a failure is NOT turned
        into an exit: the language raises for it and this model cannot raise
        from inside a call, so a program that checks the descriptor sees -1
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
                    f"x86-64 path (got {type(mode_arg).__name__}): a string "
                    f"is a bare char * and the flags word is built before the "
                    f"call is emitted")
            mode = mode_arg.value
        flags = M.OPEN_FLAGS.get(mode)
        if flags is None and mode.endswith("+"):
            base = M.OPEN_FLAGS.get(mode[:-1])
            flags = None if base is None else base | M.OPEN_READ_WRITE
        if flags is None:
            raise CodegenError(
                f"open(): mode {mode!r} is not lowered on the formal x86-64 "
                f"path (supports {', '.join(sorted(set(M.OPEN_FLAGS)))}, each "
                f"with an optional trailing '+')")
        self._emit_expr(args[0])                   # RAX = path
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))   # RDI = path
        self._emit_mov_imm(Reg.RSI, flags)         # RSI = flags
        self._emit_mov_imm(Reg.RDX, M.OPEN_CRE_MODE)   # RDX = mode
        self._emit_mov_imm(Reg.RAX, 0)
        self._emit_extern_call("open")

    def _emit_range_list(self, rargs: list) -> None:
        """`range(a[,b[,step]])` as a VALUE → a list blob in RAX.

        The element count is computed at run time (the bounds can be
        variables), but the reservation cannot be — a blob is a fixed-size
        frame object, and a nested container emitted while filling it must
        land above the whole thing. So the reservation is the exact count when
        every bound is a literal and a fixed cap otherwise, and the runtime
        count is checked against it: too many elements exits(1) rather than
        running past the blob area into the spill slots."""
        start_e, stop_e, step_e = _range_info(rargs)
        statics = [self._static_int(e) for e in (start_e, stop_e, step_e)]
        exact = None
        if all(v is not None for v in statics):
            start, stop, step = statics
            if step == 0:
                raise CodegenError("range() step must not be zero")
            span = (stop - start) if step > 0 else (start - stop)
            exact = max(0, (span + abs(step) - 1) // abs(step))
        cap = exact if exact is not None else 64
        offset = self._reserve_blob(8 + 8 * cap, "range() lists")

        # R10 = start, R11 = step; count goes in R9.
        self._emit_expr(start_e)
        self.asm.emit(encode_mov_r64_r64(Reg.R10, Reg.RAX))
        self._emit_expr(step_e)
        self.asm.emit(encode_mov_r64_r64(Reg.R11, Reg.RAX))
        # Unique per emission: a second range() in the same function would
        # otherwise reuse these names, and the label table keeps only the LAST
        # definition — so the first fill loop's backward branch would resolve
        # to the second one.
        self._while_counter += 1
        rid = self._while_counter
        zero_label = f"{self.func_name}_rz{rid}"
        div_label = f"{self.func_name}_rd{rid}"
        ok_label = f"{self.func_name}_rok{rid}"
        fill_label = f"{self.func_name}_rfill{rid}"
        done_label = f"{self.func_name}_rdone{rid}"
        abs_label = f"{self.func_name}_rabs{rid}"
        self.asm.emit(encode_test_r64_r64(Reg.R11, Reg.R11))
        self._emit_jcc_bool(Reg.R11, COND_E, zero_label)
        self._emit_expr(stop_e)
        # span = |stop - start|
        self.asm.emit(encode_sub_r64_r64(Reg.RAX, Reg.R10))
        if (self._static_int(step_e) or 1) < 0:
            self.asm.emit(encode_neg_r64(Reg.RAX))
        # count = ceil(span / |step|). |step| has to be computed as a
        # CONDITIONAL negate, not an unconditional one: NEG of 1 is
        # 0xFFFF_FFFF_FFFF_FFFF, and `span + |step| - 1` then wraps, so the
        # divide yields 0 and the list comes out empty. R11 keeps the SIGNED
        # step for the fill below.
        self.asm.emit(encode_mov_r64_r64(Reg.R9, Reg.RAX))
        self.asm.emit(encode_mov_r64_r64(Reg.R8, Reg.R11))
        self.asm.emit(encode_test_r64_r64(Reg.R8, Reg.R8))
        abs_label = f"{self.func_name}_rabs"
        self._emit_jcc(COND_GE, abs_label)
        self.asm.emit(encode_neg_r64(Reg.R8))
        self.asm.label(abs_label)
        self.asm.emit(encode_add_r64_r64(Reg.R9, Reg.R8))
        self.asm.emit(encode_sub_r64_imm8(Reg.R9, 1))
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R9))
        self.asm.emit(encode_xor_edx_edx())
        self.asm.emit(encode_div_r64(Reg.R8))
        self.asm.emit(encode_mov_r64_r64(Reg.R9, Reg.RAX))
        self._emit_jmp(div_label)
        self.asm.label(zero_label)
        self._emit_mov_imm(Reg.R9, 0)
        self.asm.label(div_label)
        # Cap check: the reservation is `cap` elements.
        self.asm.emit(encode_cmp_r64_imm32(Reg.R9, cap))
        self._emit_jcc(COND_BE, ok_label)
        self._emit_call_exit(1)
        self.asm.label(ok_label)
        self._emit_blob_base(offset, Reg.RDI)
        self.asm.emit(encode_mov_rm64_r64(Reg.RDI, 0, Reg.R9))
        # Fill: out[1+j] = start + j*step, walking the source by 8*|step| is
        # not possible (the step is a runtime value), so compute each element.
        self.asm.emit(encode_mov_r64_r64(Reg.RCX, Reg.RDI))
        self.asm.emit(encode_add_r64_imm32(Reg.RCX, 8))
        self._emit_mov_imm(Reg.R8, 0)
        self.asm.label(fill_label)
        self.asm.emit(encode_cmp_r64_r64(Reg.R8, Reg.R9))
        self._emit_jcc(COND_AE, done_label)
        # value = start + j*step
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R10))
        self.asm.emit(encode_imul_r64_r64(Reg.R8, Reg.R11))
        self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.R8))
        self.asm.emit(encode_mov_rm64_r64(Reg.RCX, 0, Reg.RAX))
        self.asm.emit(encode_add_r64_imm8(Reg.RCX, 8))
        self.asm.emit(encode_add_r64_imm8(Reg.R8, 1))
        self._emit_jmp(fill_label)
        self.asm.label(done_label)
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.RDI))

    def _is_string_subscript(self, obj) -> bool:
        """True when `obj` is known to hold a string (char*) address, so a
        subscript is a byte load rather than a list index.

        The same one-authority rule as the arm64 backend's, and for the same
        reason: the flow-sensitive `_string_vars` map only ever sees a BINDING
        statement, so a `String`-annotated PARAMETER was missing from it while
        the whole-function `ValueKinds` — which `_expr_str_kind` falls back to —
        knows. The same name was then a `char *` to `len` and a list blob to
        this predicate, and the blob path bounds-checks against the first eight
        CHARACTERS of the string. See
        bugs/CODEGEN_string_parameter_subscript_reads_count_field.md.
        """
        if isinstance(obj, F.StringLiteral):
            return True
        return self._expr_str_kind(obj) == M.STR_KIND

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
        """RAX = the ADDRESS of `obj[index]` (not its value).

        Split out so the same address computation serves a read, a store and
        an augmented assignment. A list index is bounds-checked (negative
        indices wrap like Python first, then the bound is checked); an
        out-of-range index exits(1), which is the same signal the arm64
        backend uses.

        Both refusals live HERE, and the x86-64 path had NEITHER of them, so
        `x[i, j]` and `x[k=1]` did not fail on this architecture: the first
        materialized the index tuple as a frame blob and then used that blob's
        own ADDRESS as an element index — `s[i, j]` segfaulted, and
        `a[i, j]` returned an element nobody asked for — while arm64 refused
        the first. Same language, two architectures, one crashing and one
        confidently wrong. `model.multi_index_refusal_for` is the shared text,
        so the two cannot drift again."""
        self._refuse_frame_container_operand("a subscript", e.obj)
        self._sub_width = 8
        if e.attrs is not None:
            raise CodegenError(
                "type-parameter subscript [...] is not supported on the "
                "formal x86-64 path")
        # Unconditional, because `multi_index_refusal_for` now decides the MLIR
        # case on the BASE name rather than on a comma list — see its
        # docstring. A single-element `__mlir_type[x]` used to skip this call
        # entirely and fabricate a word.
        why = M.multi_index_refusal_for(
            e, self._is_dict_subscript(e.obj), self._functions)
        if why is not None:
            raise CodegenError(why)
        if self._is_dict_subscript(e.obj):
            self._emit_dict_lookup_addr(e)
            return
        self._emit_expr(e.obj)
        self._push_slot(Reg.RAX)                    # base
        self._emit_expr(e.index)
        self._pop_slot(Reg.R11)                     # R11 = base
        if self._is_string_subscript(e.obj):
            # A string INDEX would make this `s + i` with two addresses. Asked
            # HERE, in the single choke point a read, a store and an augmented
            # assignment all pass through, so all three are covered by one
            # call. Measured on both backends: `s[t]` segfaulted here and
            # printed an address's low byte on arm64.
            ireason = M.string_index_refusal(
                self._expr_str_kind(e.obj), self._expr_str_kind(e.index),
                M.spelled(e.index))
            if ireason is not None:
                raise CodegenError(ireason)
            # A string is a plain byte run: no header, no count, so there is
            # nothing to bounds-check the index against and (deliberately) no
            # check emitted — reading the NUL terminator is the same answer a
            # NUL-terminated read gives.
            # addr = base + index. RAX still holds the INDEX here and R11
            # the base, so this is a plain add — copying the base into RAX
            # first would compute base+base.
            self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.R11))
            self._sub_width = 1
            return
        shape, width, signed, sub_why = M.subscript_base_lowering(
            self._cur_fn, e.obj, self._structs, self._functions, self._structs)
        if shape is None:
            raise CodegenError(sub_why)
        if shape == "load":
            # A POINTER subscript is `base + index*width`, with NO count header
            # and no bounds check — the same question `p.value()` asks, routed
            # through the same reader, and the reason the two spellings of it
            # now agree.  Before the route existed this fell through to the blob
            # walk, whose first word of the base is a COUNT, so `p[0]` read the
            # byte at offset 0 as the element count and loaded
            # `base + 8 + 8*count`.  See
            # bugs/FORMAL_subscript_of_a_pointer_reads_a_blob_count.md.
            self._sub_width = width
            if width != 1:
                # The scale is emitted rather than assumed: `base + i` is right
                # for a one-byte element and is the SECOND element for any
                # other width, the same trap `model._offset_scale` refuses on
                # the dereference path.
                self.asm.emit(encode_imul_r64_r64_imm(Reg.RAX, Reg.RAX,
                                                           width))
            self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.R11))
            return
        self.asm.emit(encode_mov_r64_r64(Reg.R10, Reg.R11))
        self.asm.emit(encode_mov_r64_rm64(Reg.R11, Reg.R10, 0))    # count
        self._emit_bounds_check(Reg.RAX, Reg.R11)
        self._emit_elem_addr(Reg.R10, Reg.RAX, Reg.RAX)

    def _emit_bounds_check(self, index_reg: Reg, count_reg):
        """Exit(1) unless `index_reg` is a valid element index.

        A negative index counts from the end, Python-style: it is negated and
        `count` added, and only then range-checked, so an index below `-count`
        stays negative and is rejected by the same unsigned comparison. The
        count register is left intact — the caller needs it for the address
        arithmetic that follows.

        `count_reg` None means a string, which has no count header: its
        elements run to a NUL, so there is nothing to check the index against
        and the read stops at the terminator."""
        self._if_counter += 1
        bid = self._if_counter
        fn = self.func_name
        ok_label = f"{fn}_bnds{bid}_ok"
        bad_label = f"{fn}_bnds{bid}_bad"
        wrapped_label = f"{fn}_bnds{bid}_wrapped"
        if count_reg is None:
            return
        if True:
            self.asm.emit(encode_cmp_r64_imm8(index_reg, 0))
            self._emit_jcc(COND_GE, wrapped_label)
            # Python: a negative index counts from the end, i.e. it is ADDED
            # to the count (-1 + 3 == 2), not subtracted from it as an
            # absolute value (3 - 1 == 2 coincides, 3 - |−1| == 4 does not).
            # An index below -count stays negative and fails the check below.
            self.asm.emit(encode_add_r64_r64(index_reg, count_reg))
            self.asm.label(wrapped_label)
            self.asm.emit(encode_cmp_r64_r64(index_reg, count_reg))
        self._emit_jcc(COND_AE, bad_label)     # index >= count
        self._emit_jmp(ok_label)
        self.asm.label(bad_label)
        self._emit_call_exit(1)
        self.asm.label(ok_label)

    def _emit_subscript(self, e: F.SubscriptExpr) -> None:
        """`obj[index]` → the element (or byte, for a string) in RAX.

        The subscript's refusals are in `_emit_subscript_addr`, which this
        calls, so that the store path is covered by the same check."""
        if isinstance(e.index, F.SliceExpr):
            self._emit_slice_parts(e.obj, e.index.start, e.index.stop,
                                   e.index.step)
            return
        self._emit_subscript_addr(e)
        # The address is in RAX; the element has to be LOADED before any
        # extension — MOVZX of the address itself would yield the low byte of a
        # pointer.
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RAX, 0))
        if self._sub_width == 1:
            # Unsigned: a `UInt8` element is a byte, and a formal value is one
            # 64-bit word holding an integer, so `200` has to read back as 200.
            # The signed form is the same two-instruction pair with a different
            # mnemonic, chosen from the pointee the model established.
            self.asm.emit(encode_movzx_r64_r8(Reg.RAX, Reg.RAX))

    def _blob_est(self, e) -> int:
        """Static upper bound on a blob expression's element count.

        A concat has to reserve its result BEFORE evaluating either operand
        (a nested container must not land inside the region being filled), so
        the size has to be known without running anything — hence an estimate
        over the syntax rather than the value. The runtime count is checked
        against it below, so an under-estimate fails loudly instead of
        overrunning the frame."""
        if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            return len(e.elements)
        if isinstance(e, F.DictExpr):
            return len(e.pairs)
        if isinstance(e, F.SliceExpr):
            return 64
        if isinstance(e, F.Comprehension):
            return self._compr_cap(e)
        if isinstance(e, F.CallExpr):
            return 64
        if isinstance(e, F.BinaryOp):
            if e.op in ("+", "|"):
                return self._blob_est(e.left) + self._blob_est(e.right)
            if e.op in ("or", "and"):
                return max(self._blob_est(e.left), self._blob_est(e.right))
        return 64

    def _compr_cap(self, expr: F.Comprehension) -> int:
        """Upper bound on a comprehension's RESULT size, for the reservation.

        Nested generators MULTIPLY: `[i + j for i in range(n) for j in
        range(n)]` can produce n*n elements, and taking the maximum of the
        per-generator bounds (as an earlier version here did) reserves a
        fraction of what the appends will need, so the result runs off the end
        of its own blob. An unknown iterable falls back to a frame-safe
        default, and the runtime append still bounds-checks against whatever
        was reserved (see _compr_append_elem).

        Capped at 256 the way the arm64 backend caps it, so a `range` of
        something huge cannot reserve the whole frame at compile time."""
        gens = expr.generators or []
        if not gens:
            return 1
        total = 1
        for g in gens:
            total *= max(1, self._blob_est(g.iterable))
            if total > 256:
                return 256
        return max(1, total)

    def _emit_list_concat(self, left, right) -> None:
        """`a + b` over two blobs → a fresh blob holding both, in RAX.

        The result is a COPY: a blob is a fixed-size frame object with no
        capacity to grow into, so the element counts are read at run time and
        the two copies are loops. The reservation is a static estimate clamped
        to the frame's remaining blob area, and the runtime total is checked
        against it — an under-estimate exits(1) rather than overwriting the
        spill slots above the blob area.

        Register plan for the two copies (no call happens in between, so
        caller-saved scratch is free): RSI/RDX the operands, RDI the result,
        R8/R9 the two counts, RCX a walking destination pointer, RAX the
        element, R11 the index."""
        est = max(1, self._blob_est(left) + self._blob_est(right))
        avail = self._blob_cap - self._list_cursor
        if avail < 16:
            raise CodegenError(
                f"list concat exceeds the formal frame "
                f"({self._list_cursor} > {self._blob_cap} bytes)")
        cap = min(est, (avail - 8) // 8)

        self._emit_expr(left)
        self._push_slot(Reg.RAX)                    # [rsp] = left
        self._emit_expr(right)
        self.asm.emit(encode_mov_r64_r64(Reg.RDX, Reg.RAX))   # right
        self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 0))
        self.asm.emit(encode_add_r64_imm32(Reg.RSP, _SLOT))

        # A nested emit above advanced the cursor; re-clamp against what is
        # actually left.
        avail = self._blob_cap - self._list_cursor
        if avail < 16:
            raise CodegenError(
                f"list concat exceeds the formal frame "
                f"({self._list_cursor} > {self._blob_cap} bytes)")
        cap = min(est, (avail - 8) // 8)
        offset = self._reserve_blob(8 + 8 * cap, "list concatenation")

        self.asm.emit(encode_mov_r64_rm64(Reg.R8, Reg.RSI, 0))   # nL
        self.asm.emit(encode_mov_r64_rm64(Reg.R9, Reg.RDX, 0))   # nR
        self._emit_blob_base(offset, Reg.RDI)                    # dst
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R8))
        self.asm.emit(encode_add_r64_r64(Reg.RAX, Reg.R9))       # total
        self.asm.emit(encode_mov_rm64_r64(Reg.RDI, 0, Reg.RAX))
        self._while_counter += 1
        fn = f"{self.func_name}_cat{self._while_counter}"
        overflow_label = f"{fn}_ovf"
        self.asm.emit(encode_cmp_r64_imm32(Reg.RAX, cap))
        self._emit_jcc(COND_BE, overflow_label)
        self._emit_call_exit(1)
        self.asm.label(overflow_label)

        self._while_counter += 2
        cl = f"{fn}_lcl{self._while_counter}"
        cld = f"{fn}_lcd{self._while_counter}"
        cr = f"{fn}_lcr{self._while_counter - 1}"
        crd = f"{fn}_lcrd{self._while_counter - 1}"
        # left: dst[1+i] = left[1+i]
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.RSI))
        self.asm.emit(encode_add_r64_imm32(Reg.RAX, 8))
        self.asm.emit(encode_mov_r64_r64(Reg.RCX, Reg.RDI))
        self.asm.emit(encode_add_r64_imm32(Reg.RCX, 8))
        self._emit_mov_imm(Reg.R11, 0)
        self.asm.label(cl)
        self.asm.emit(encode_cmp_r64_r64(Reg.R11, Reg.R8))
        self._emit_jcc(COND_AE, cld)
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.RAX, 0))
        self.asm.emit(encode_mov_rm64_r64(Reg.RCX, 0, Reg.R10))
        self.asm.emit(encode_add_r64_imm8(Reg.RAX, 8))
        self.asm.emit(encode_add_r64_imm8(Reg.RCX, 8))
        self.asm.emit(encode_add_r64_imm8(Reg.R11, 1))
        self._emit_jmp(cl)
        self.asm.label(cld)
        # right: RCX already points at dst + 8 + 8*nL, which is where the
        # right operand's elements start.
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.RDX))
        self.asm.emit(encode_add_r64_imm32(Reg.RAX, 8))
        self._emit_mov_imm(Reg.R11, 0)
        self.asm.label(cr)
        self.asm.emit(encode_cmp_r64_r64(Reg.R11, Reg.R9))
        self._emit_jcc(COND_AE, crd)
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.RAX, 0))
        self.asm.emit(encode_mov_rm64_r64(Reg.RCX, 0, Reg.R10))
        self.asm.emit(encode_add_r64_imm8(Reg.RAX, 8))
        self.asm.emit(encode_add_r64_imm8(Reg.RCX, 8))
        self.asm.emit(encode_add_r64_imm8(Reg.R11, 1))
        self._emit_jmp(cr)
        self.asm.label(crd)
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.RDI))

    def _emit_membership(self, left, right, invert: bool) -> None:
        """`needle in haystack` / `needle not in haystack`, list blob or string.

        Two haystacks, and which one this is has to be decided BEFORE anything
        is emitted, because the two share no code at all: a list haystack is a
        frame-allocated blob whose first 8 bytes are its count, and a string
        haystack is a `char *` into the image's read-only text.

        THIS BACKEND HAD NO STRING CASE AT ALL, which is the measured state and
        not an oversight in the reading of it: `"ell" in s` for `s = "hello"`
        terminated the process with SIGBUS on BOTH architectures, and where it
        did not fault — `"bc" in "abcd"` on this one — it returned FALSE, which
        is a wrong answer rather than a crash. The blob scan read the first
        eight bytes of the CHARACTERS as a `[count]` header and walked off the
        end of the mapping looking for elements.

        The decision itself is `model.string_membership_lowering`, shared with
        the arm64 backend, so the two architectures cannot come apart on which
        of the two a given haystack is, nor on which libc call a given needle
        shape makes. Neither can they come apart on the RESULT: 0/1 in RAX,
        `not in` inverted, and a bool is an int on this path because there is
        no BOOL kind distinct from INT (which is why `__mlir_bool__` is
        refused) — the same 0/1 the blob scan has always produced.

        The needle stays in its 16-byte stack slot for the whole blob scan and
        is read (not popped) each iteration, because every register is scratch
        inside the loop; it is released once, on whichever exit is taken."""
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
        self._emit_expr(left)
        self._push_slot(Reg.RAX)                   # needle
        self._emit_expr(right)
        self.asm.emit(encode_mov_r64_r64(Reg.R9, Reg.RAX))    # haystack
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.R9, 0))   # count
        self._emit_mov_imm(Reg.R8, 0)              # index
        self._if_counter += 1
        mid = self._if_counter
        fn = self.func_name
        loop_label = f"{fn}_in{mid}_loop"
        notfound_label = f"{fn}_in{mid}_nf"
        found_label = f"{fn}_in{mid}_hit"
        end_label = f"{fn}_in{mid}_end"
        self.asm.label(loop_label)
        self.asm.emit(encode_cmp_r64_r64(Reg.R8, Reg.R10))
        self._emit_setcc_bool(Reg.R11, "setae")
        self._emit_jcc_bool(Reg.R11, COND_NE, notfound_label)
        self._emit_elem_addr(Reg.R9, Reg.R8, Reg.RDI)
        self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RDI, 0))
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.RSP, 0))   # needle
        self.asm.emit(encode_cmp_r64_r64(Reg.RDI, Reg.R10))
        self._emit_setcc_bool(Reg.R11, "sete")
        # Equal -> found. (Jumping to `found` on NOT-equal is the same
        # inverted-polarity trap as the loop exit above.)
        self._emit_jcc_bool(Reg.R11, COND_NE, found_label)
        self.asm.emit(encode_add_r64_imm8(Reg.R8, 1))
        self._emit_jmp(loop_label)
        self.asm.label(found_label)
        self._pop_slot(Reg.R10)
        self._emit_mov_imm(Reg.RAX, 0 if invert else 1)
        self._emit_jmp(end_label)
        self.asm.label(notfound_label)
        self._pop_slot(Reg.R10)
        self._emit_mov_imm(Reg.RAX, 1 if invert else 0)
        self.asm.label(end_label)

    def _emit_for_list(self, stmt, else_body) -> None:
        """`for x in <blob>` — including a tuple target.

        The iterable is materialized ONCE (so `for x in x` behaves), the
        index and the blob pointer live in per-depth temps `_fi{d}`/`_fb{d}`,
        and `continue` jumps past the increment's target (step), so it still
        advances — the same contract the range loop has."""
        d = self._for_depth
        self._for_depth += 1
        try:
            it = stmt.iterable
            if not isinstance(it, (F.IdentExpr, F.ListExpr, F.TupleExpr,
                                   F.SetExpr, F.DictExpr, F.StringLiteral,
                                   F.SubscriptExpr, F.SliceExpr,
                                   F.Comprehension, F.MemberExpr,
                                   F.TernaryExpr, F.UnaryOp, F.CallExpr,
                                   F.BinaryOp, F.AwaitExpr, F.WalrusExpr)):
                raise CodegenError(
                    f"unsupported for-loop iterable {type(it).__name__} on "
                    f"the formal x86-64 path")
            # The blob walk below reads the count at offset 0 of the iterable
            # and then elements at `base + 8 + 8k`, so a FRAME ADDRESS here
            # iterates the struct's fields.  Measured on both architectures:
            # summing a four-field struct gave 99 on arm64 and 53 on x86-64.
            self._refuse_frame_container_operand("a for-in iteration", it)
            from mojo.middle.boundnames import _lbn_target_names
            tnames = _lbn_target_names(stmt.target) \
                if isinstance(stmt.target, str) else []
            if not tnames or any(not n.isidentifier() for n in tnames):
                raise CodegenError(
                    f"for-loop target must be a plain name or tuple of plain "
                    f"names (got {stmt.target!r})")

            self._while_counter += 1
            wid = self._while_counter
            fn = self.func_name
            start_label = f"{fn}_fl{wid}_start"
            step_label = f"{fn}_fl{wid}_step"
            false_label = f"{fn}_fl{wid}_false"
            end_label = f"{fn}_fl{wid}_end"
            fi_name, fb_name = f"_fi{d}", f"_fb{d}"

            # Materialize the iterable once, under container context so a
            # BinaryOp `+` here means list concat rather than integer add.
            self._container_ctx += 1
            try:
                self._emit_expr(it)
            finally:
                self._container_ctx -= 1
            self._store_var(fb_name, Reg.RAX)
            self._emit_mov_imm(Reg.RAX, 0)
            self._store_var(fi_name, Reg.RAX)

            self._loops.append({"start": start_label, "step": step_label,
                                "break": end_label,
                                "fin_depth": len(self._pending_finally)})
            try:
                self.asm.label(start_label)
                self._load_var(fb_name, Reg.R11)
                self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.R11, 0))
                self._load_var(fi_name, Reg.RAX)
                self.asm.emit(encode_cmp_r64_r64(Reg.RAX, Reg.R10))
                # R8, not R11: R11 holds the blob base, and the element
                # address computed next is relative to it.
                self._emit_setcc_bool(Reg.R8, "setae")
                self._emit_jcc_bool(Reg.R8, COND_NE, false_label)
                self._emit_elem_addr(Reg.R11, Reg.RAX, Reg.RDI)
                self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RDI, 0))
                if len(tnames) == 1:
                    self._store_var(tnames[0], Reg.RAX)
                else:
                    self._emit_for_unpack(tnames, Reg.RAX,
                                          f"{fn}_flt{wid}")

                for s in stmt.body:
                    self._emit_stmt(s)

                self.asm.label(step_label)
                self._load_var(fi_name, Reg.RAX)
                self.asm.emit(encode_add_r64_imm8(Reg.RAX, 1))
                self._store_var(fi_name, Reg.RAX)
                self._emit_jmp(start_label)

                self.asm.label(false_label)
                for s in (else_body or []):
                    self._emit_stmt(s)
                self.asm.label(end_label)
            finally:
                self._loops.pop()
        finally:
            self._for_depth -= 1

    def _emit_dict(self, expr: F.DictExpr) -> None:
        """A dict literal → its pair-blob address in RAX.

        Layout `[count:i64][key0][value0]…` — pairs at 16-byte stride, which
        is what makes a lookup a linear scan over the KEYS at that stride
        (a stride-8 scan would walk keys and values alternately). `**other` /
        `*xs` are evaluated for their side effects and skipped: a pair-blob
        has a fixed size and no way to grow into a runtime-sized merge."""
        pairs = []
        for k, v in expr.pairs:
            if isinstance(k, F.UnaryOp) and k.op in ("**", "*"):
                self._emit_expr(k.operand)
                if v is not None:
                    self._emit_expr(v)
                continue
            pairs.append((k, v))
        n = len(pairs)
        offset = self._reserve_blob(8 + 16 * n, "dict literals")
        self._emit_blob_base(offset, Reg.R11)
        self._emit_mov_imm(Reg.R10, n)
        self.asm.emit(encode_mov_rm64_r64(Reg.R11, 0, Reg.R10))
        for i, (k, v) in enumerate(pairs):
            self._emit_expr(k)
            self._emit_blob_base(offset, Reg.R11)
            self.asm.emit(encode_mov_rm64_r64(Reg.R11, 8 + 16 * i, Reg.RAX))
            if v is not None:
                self._emit_expr(v)
            else:
                self._emit_mov_imm(Reg.RAX, 0)
            self._emit_blob_base(offset, Reg.R11)
            self.asm.emit(encode_mov_rm64_r64(Reg.R11, 16 + 16 * i, Reg.RAX))
        self._emit_blob_base(offset, Reg.RAX)

    def _is_dict_subscript(self, obj) -> bool:
        """True when `obj` is known to hold a dict pair-blob pointer, so a
        subscript is a key lookup rather than an index."""
        if isinstance(obj, F.DictExpr):
            return True
        if isinstance(obj, F.IdentExpr):
            return obj.name in self._dict_vars
        return False

    def _emit_dict_lookup_addr(self, e: F.SubscriptExpr) -> None:
        """RAX = the ADDRESS of the value stored under `e`'s key.

        A linear scan over the pairs at 16-byte stride, comparing keys; a
        miss exits(1), the same signal an out-of-range list index gives (this
        path has no exception runtime to raise KeyError with). The key is
        spilled first because the scan clobbers RAX."""
        self._emit_expr(e.obj)
        self._push_slot(Reg.RAX)                   # dict blob
        self._emit_expr(e.index)
        self._push_slot(Reg.RAX)                   # key
        self._pop_slot(Reg.RDI)                    # key
        self._pop_slot(Reg.RSI)                    # dict blob
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.RSI, 0))   # npairs
        self._emit_mov_imm(Reg.R11, 0)             # i
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        loop_label = f"{fn}_dl{wid}_loop"
        miss_label = f"{fn}_dl{wid}_miss"
        hit_label = f"{fn}_dl{wid}_hit"
        end_label = f"{fn}_dl{wid}_end"
        self.asm.label(loop_label)
        self.asm.emit(encode_cmp_r64_r64(Reg.R11, Reg.R10))
        self._emit_setcc_bool(Reg.R8, "setae")
        self._emit_jcc_bool(Reg.R8, COND_NE, miss_label)
        # key at dict + 8 + 16*i
        self._emit_elem_addr(Reg.RSI, Reg.R11, Reg.R9, header=8, scale=4)
        self.asm.emit(encode_mov_r64_rm64(Reg.R9, Reg.R9, 0))
        self.asm.emit(encode_cmp_r64_r64(Reg.R9, Reg.RDI))
        self._emit_setcc_bool(Reg.R8, "sete")
        self._emit_jcc_bool(Reg.R8, COND_NE, hit_label)
        self.asm.emit(encode_add_r64_imm8(Reg.R11, 1))
        self._emit_jmp(loop_label)
        self.asm.label(hit_label)
        # value address = dict + 16 + 16*i
        self._emit_elem_addr(Reg.RSI, Reg.R11, Reg.RAX, header=16, scale=4)
        self._emit_jmp(end_label)
        self.asm.label(miss_label)
        self._emit_call_exit(1)
        self.asm.label(end_label)

    def _emit_for_unpack(self, tnames: list, blob_reg: Reg, tag: str) -> None:
        """Bind a tuple target's names from the blob pointer in `blob_reg`.

        The element must itself be a `[count][e0…]` blob whose count matches
        the target's arity; a mismatch exits(1), the same signal `a, b = rhs`
        gives."""
        fn = self.func_name
        self.asm.emit(encode_mov_r64_r64(Reg.R10, blob_reg))
        self.asm.emit(encode_mov_r64_rm64(Reg.R11, Reg.R10, 0))
        self.asm.emit(encode_cmp_r64_imm32(Reg.R11, len(tnames)))
        self._if_counter += 1
        uid = self._if_counter
        ok_label = f"{fn}_fu{uid}_ok"
        bad_label = f"{fn}_fu{uid}_bad"
        self._emit_jcc(COND_NE, bad_label)
        self._emit_jmp(ok_label)     # arity matches: skip the exit
        self.asm.label(bad_label)
        self._emit_call_exit(1)
        self.asm.label(ok_label)
        for i, name in enumerate(tnames):
            self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.R10, 8 * (i + 1)))
            self._store_var(name, Reg.RAX)

    # ── expressions (result in RAX) ──────────────────────────────────

    def _emit_expr(self, expr) -> None:
        # An MLIR attribute/type template is refused HERE, at the top of the
        # walk, and for the same reason arm64's twin is: the construct's dotted
        # spelling is a plain member read, so it reaches no subscript and no
        # address computation and used to fall through to a load of a name
        # nothing defines. `is_mlir_template` keys on the base name, so this one
        # call covers the dotted spelling, the single-element bracket and the
        # multi-element bracket, and the text is the shared arch-free one — the
        # two architectures cannot drift on what a template means, which is the
        # failure `limit_mlir_multi_element_template` is pinned against.
        why = M.mlir_template_refusal(expr)
        if why is not None:
            raise CodegenError(why)
        # Likewise a `...`. This one MATTERS here: it used to fall through to
        # `_unsupported_expr_message`, which appends "container and string
        # values are not" — false of a `...`, and a claim that sent the reader
        # looking for a list the file does not contain. Shared text with arm64.
        why = M.ellipsis_refusal(expr)
        if why is not None:
            raise CodegenError(why)
        if isinstance(expr, F.IntLiteral):
            self._emit_mov_imm(Reg.RAX, expr.value)
            return

        if isinstance(expr, F.BoolLiteral):
            self._emit_mov_imm(Reg.RAX, 1 if expr.value else 0)
            return

        if isinstance(expr, F.NoneLiteral):
            self._emit_mov_imm(Reg.RAX, 0)
            return

        if isinstance(expr, F.IdentExpr):
            # A `comptime NAME = …` binding is a compile-time constant, not a
            # local: no register or slot was ever assigned to it, so the
            # ordinary `_load_var` below would read whatever happens to be in a
            # slot. Materialize the folded value instead. Consulted for EVERY
            # expression context, not just other comptime ones, because a
            # version of this that only looked in comptime contexts read an
            # ordinary use of a `comptime` name as a local and silently
            # emitted 0 (see mojo/middle/comptime.py's rule 3).
            if expr.name in self._comptime_vals:
                self._emit_comptime_read(expr.name)
                return
            # Python singletons parse as bare idents (True/False are
            # BoolLiterals; None stays an IdentExpr). Materialize them as
            # integers so `x is None` compares against 0 rather than against
            # whatever a register happens to hold.
            if expr.name in ("None", "True", "False"):
                self._emit_mov_imm(
                    Reg.RAX, {"None": 0, "True": 1, "False": 0}[expr.name])
                return
            self._load_var(expr.name, Reg.RAX)
            return

        if isinstance(expr, F.FloatLiteral):
            # formal is int-only; truncate toward zero (matches a C cast).
            self._emit_mov_imm(Reg.RAX, int(expr.value))
            return

        if isinstance(expr, F.StringLiteral):
            # The literal's ADDRESS is the value: a string is a pointer to
            # bytes appended after the code, materialized with a RIP-relative
            # LEA whose displacement the assembler back-patches once the data
            # label is known. Interned by content, so equal literals share one
            # address. Mirrors the arm64 backend's ADRP+ADD of the same data.
            self.asm.emit(encode_lea_r64_rip(Reg.RAX, 0))
            # -4, not -3: the 7-byte encoding is REX, opcode, ModRM, disp32,
            # so the displacement FIELD starts 4 bytes before the end (and
            # there is no SIB byte in front of it to skip).
            self.asm.emit_label_rip(self._intern_string(expr.value),
                                    here_offset=-4)
            return

        if isinstance(expr, F.UnaryOp):
            self._emit_unary(expr)
            return

        if isinstance(expr, F.BinaryOp):
            self._emit_binop(expr)
            return

        if isinstance(expr, F.CompareChain):
            self._emit_compare_chain(expr)
            return

        if isinstance(expr, F.CallExpr):
            self._emit_call(expr)
            return

        if isinstance(expr, F.TernaryExpr):
            # `a if c else b` — same branch shape as if/else, both arms leave
            # their value in RAX, joined at the end.
            self._if_counter += 1
            tid = self._if_counter
            fn = self.func_name
            else_label = f"{fn}_tern{tid}_else"
            end_label = f"{fn}_tern{tid}_end"
            self._emit_truthy_word(expr.condition)
            self._emit_branch_if_false(else_label)
            self._emit_expr(expr.then_val)
            self._emit_jmp(end_label)
            self.asm.label(else_label)
            self._emit_expr(expr.else_val)
            self.asm.label(end_label)
            return

        if isinstance(expr, F.Comprehension):
            self._emit_comprehension(expr)
            return

        if isinstance(expr, F.DictExpr):
            self._emit_dict(expr)
            return

        if isinstance(expr, (F.ListExpr, F.TupleExpr, F.SetExpr)):
            # TupleExpr and ListExpr have identical `elements` and one blob
            # layout, so they share an emitter rather than two parallel ones.
            # A set lowers as a list blob: membership and iteration are the
            # only uses formal sees, and the blob gives both.
            self._emit_list(expr)
            return

        if isinstance(expr, F.SubscriptExpr):
            self._emit_subscript(expr)
            return

        if isinstance(expr, F.SliceExpr):
            # `obj[a:b]` parses as a SliceExpr carrying the object; the other
            # spelling, a subscript whose INDEX is a slice, is handled inside
            # _emit_subscript.
            self._emit_slice_parts(expr.obj, expr.start, expr.stop,
                                   expr.step)
            return

        if isinstance(expr, F.AwaitExpr):
            # No event loop: await e ≡ e.
            self._emit_expr(expr.value)
            return

        if isinstance(expr, F.YieldExpr):
            # Generator lowered as a plain function: yield e leaves e in RAX
            # (the "send" result is not modeled — compile-only).
            if expr.value is not None:
                self._emit_expr(expr.value)
            else:
                self._emit_mov_imm(Reg.RAX, 0)
            return

        if isinstance(expr, F.WalrusExpr):
            self._emit_expr(expr.value)
            self._store_var(expr.name, Reg.RAX)
            self._note_binding(expr.name, expr.value)
            return

        if isinstance(expr, F.LambdaExpr):
            # Lifted by build._lift_lambdas at call/assign sites; a residual
            # bare lambda (argument position) has no address to take without
            # a function-pointer representation, so it reads as 0.
            self._emit_mov_imm(Reg.RAX, 0)
            return

        if isinstance(expr, F.MemberExpr):
            # A receiver FIELD of a by-reference struct is real memory:
            # `mov rax, [holder + 8*slot]`. Anything else has no object model
            # here — evaluate the base for its side effects, read the field as
            # 0 — which is the same compile-only reading as before, kept
            # because it is what every non-frame member access on this path
            # already does.
            key = _member_slot_key(expr)
            if key is not None and key in self._frame_slots:
                self._load_var(key, Reg.RAX)
                return
            # A NESTED frame slot, which is two loads and is routed through
            # `_load_var` for exactly that reason.  It has to be a SEPARATE
            # branch here rather than a longer key in `_frame_slots`: the
            # guard below refuses any dotted key that is not a one-load slot, so
            # a nested key left to fall through would be refused by the guard
            # rather than read — and the arm64 twin, whose `_emit_expr` defers to
            # `_load_var` for every key, would answer it.  One backend refusing
            # and the other computing is the divergence this pair must not have.
            if key is not None and key in self._frame_nested_slots:
                self._load_var(key, Reg.RAX)
                return
            # …except a chain DEEPER than a frame slot, which is a field of a
            # field and must not be read as the 0 below. arm64's second line at
            # the same shape refuses it too, and both are here because the two
            # backends must not disagree about which programs they can answer:
            # one reading 0 and one reading a scratch register is exactly the
            # kind of split this gate exists to catch, and it is a silent one.
            # A `h.f.m(...)` CALL does not come through here — the call path
            # reads `h.f` as a value receiver and dispatches on the method.
            if key is not None and "." in key \
                    and key not in self._frame_nested_slots \
                    and key.split(".", 1)[0] in self._frame_holders:
                raise CodegenError(
                    f"{key} reads a field of a field through the receiver "
                    f"{key.split('.', 1)[0]} and reached a value position, where "
                    f"a frame slot has no second layout to offer: the word in "
                    f"the slot is a value, and this path will not read a word "
                    f"as though it were a struct's storage")
            self._emit_expr(expr.obj)
            # …and a field access whose base is NOT a frame holder is REFUSED,
            # not read as 0.  This is the x86-64 half of
            # `byref_one_name_two_widths_agree` / `one_field_struct_field_read_
            # is_correct_on_arm64`, and it is the same defect the store half
            # above had: `h.v` through a parameter is a real field read with no
            # field layout to read from, and 0 is a plausible-looking wrong
            # number.  Measured on the pre-change tree for ONE program:
            # arm64 exited 1 (right, by accident — `h` is argument 0, so it is
            # X19 and `_load_var`'s fall-through read X19) and x86-64 exited 0
            # (wrong).  Two architectures, one source, two answers.  The words
            # are the shared model's, so both arches print the same line.
            root = (key or M.member_chain_text(expr)).split(".", 1)[0]
            raise CodegenError(M.field_access_refusal(
                key or M.member_chain_text(expr), self.func_name or "<module>",
                root, root in self._frame_holders))

        raise CodegenError(self._unsupported_expr_message(expr))

    def _unsupported_expr_message(self, expr) -> str:
        """Why an expression has no lowering, naming the construct.

        The container and string forms need a heap/blob runtime (a list blob
        is [count][elements…], a dict a pair blob, a string an interned
        address) that neither the toy x86-64 path this was ported from nor
        lib/ProofLib.lean's x86-64 model describes. Saying so beats emitting
        something that runs and computes the wrong answer."""
        return (f"unsupported expression {type(expr).__name__} on the formal "
                f"x86-64 path: the integer/boolean surface is lowered, "
                f"container and string values are not")

    def _emit_unary(self, expr) -> None:
        # `-s` is negation of an address and `~s` is a bit complement of one,
        # and `not s` is FALSE for every string including the empty one,
        # because a pointer is never zero. Measured on both backends: `~s`
        # returned 8881076 on arm64 and 3236815 on x86-64, and `not ""`
        # returned 0 where Python returns 1. `model` holds the messages and
        # the measurements; asking here is what makes the two architectures
        # refuse the same thing.
        ureason = M.string_unary_refusal(
            expr.op, self._expr_str_kind(expr.operand),
            M.spelled(expr.operand))
        if ureason is not None:
            raise CodegenError(ureason)
        if expr.op == "not":
            self._emit_expr(expr.operand)
            self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
            self._emit_setcc_bool(Reg.RAX, "sete")
            return
        if expr.op == "-":
            self._emit_expr(expr.operand)
            self.asm.emit(encode_neg_r64(Reg.RAX))
            self._emit_trunc(self._ttype(expr.operand))
            return
        if expr.op == "+":
            self._emit_expr(expr.operand)
            return
        if expr.op == "~":
            self._emit_expr(expr.operand)
            self.asm.emit(encode_not_r64(Reg.RAX))
            self._emit_trunc(self._ttype(expr.operand))
            return
        raise CodegenError(
            f"unsupported unary operator {expr.op!r} on the formal x86-64 "
            f"path")

    def _emit_setcc_bool(self, reg: Reg, mnem: str) -> None:
        """reg = 0/1 from the flags: SETcc the low byte, then zero-extend.

        The zero-extension is not optional — a SETcc leaves the rest of the
        register's old bits in place, and a stale high word would make every
        later comparison of the same value wrong."""
        self.asm.emit(_SETCC[mnem](reg))
        self.asm.emit(encode_movzx_r64_r8(reg, reg))

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
        if op in _CMP_CONDS:
            unsigned, signed = _CMP_CONDS[op]
            if not self._emit_strcmp(e.left, e.right, op):
                self._emit_cmp(e.left, e.right, unsigned, signed)
            return

        # Python `and`/`or` return the deciding OPERAND, not a bitwise mix
        # of the two, so they branch rather than hitting the ALU table.
        if op in ("and", "or"):
            self._emit_and_or(e.left, e.right, is_or=(op == "or"))
            return

        # List/set concat, either because we are under a container context (a
        # for-iterable or a membership RHS) or because one side is visibly a
        # container literal / producer.
        if op in ("+", "|") and (self._container_ctx > 0
                                 or self._is_container_expr(e.left)
                                 or self._is_container_expr(e.right)):
            if op == "+":
                self._emit_list_concat(e.left, e.right)
            else:
                self._emit_list_concat(e.left, e.right)
            return

        if op in ("in", "not in"):
            self._emit_membership(e.left, e.right, invert=(op == "not in"))
            return

        if op in _ALU_RR:
            self._emit_two_sided(e.left, e.right, _ALU_RR[op], Reg.R11)
            if op in ("+", "-", "*"):
                self._emit_trunc(common_type(self._ttype(e.left),
                                             self._ttype(e.right)))
            return

        if op in ("/", "//", "%"):
            self._emit_div_mod(e, op)
            return

        if op in ("<<", ">>"):
            self._emit_shift(e, op)
            return

        if op == "**":
            self._emit_pow(e)
            return

        raise CodegenError(
            f"unsupported binary operator {op!r} on the formal x86-64 path")

    def _emit_two_sided(self, left, right, alu, scratch: Reg) -> None:
        """left OP right, both in RAX on exit.

        The left operand is pushed while the right one is evaluated because
        evaluating an expression clobbers RAX, and a nested call clobbers
        every caller-saved register."""
        self._emit_expr(left)
        self._push_slot(Reg.RAX)
        self._emit_expr(right)
        self.asm.emit(encode_mov_r64_r64(scratch, Reg.RAX))
        self._pop_slot(Reg.RAX)
        self.asm.emit(alu(Reg.RAX, scratch))

    def _emit_strcmp(self, l, r, op: str) -> bool:
        """`l == r` / `l != r` on two STRINGS as `strcmp(l, r) == 0`.

        True if it emitted, 0/1 in RAX, the same shape `_emit_cmp` produces for
        an integer — so every consumer of a comparison's value works unchanged,
        which is the whole reason this backend needs only one hook where arm64
        needs two (it has a separate flag-consuming branch path).

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
        is shared with the arm64 backend so they cannot come apart there.

        RDI, not RAX, for the second operand: an expression leaves its value in
        RAX and the first ARGUMENT register is RDI, and `strcmp` dereferences
        both. Omitting the move is a fault inside libc rather than a wrong
        answer, which is the same trap `_emit_str_affix` documents.
        """
        if M.string_comparison_lowering(
                op, self._expr_str_kind(l), self._expr_str_kind(r),
                l, r) != M.STRING_COMPARE_CONTENT:
            return False
        # push l, then r  =>  [rsp] = r, [rsp+16] = l. The same two-slot shape
        # `_emit_str_affix` uses, and for the same reason: an expression leaves
        # its value in RAX and a nested call clobbers every caller-saved
        # register, so both operands have to survive the calls.
        self._emit_expr(l)
        self._push_slot(Reg.RAX)
        self._emit_expr(r)
        self._push_slot(Reg.RAX)
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 0))    # r
        self.asm.emit(encode_mov_r64_r64(Reg.RDI, Reg.RAX))
        self._emit_extern_call("strlen")                  # RAX = len(r)
        self.asm.emit(encode_add_r64_imm8(Reg.RAX, 1))     # n = len(r) + 1
        self.asm.emit(encode_mov_r64_r64(Reg.RDX, Reg.RAX))
        self.asm.emit(encode_mov_r64_rm64(Reg.RDI, Reg.RSP, 16))   # l
        self.asm.emit(encode_mov_r64_rm64(Reg.RSI, Reg.RSP, 0))    # r
        self._emit_extern_call(M.STRING_COMPARE_SYMBOL)
        self._emit_setcc_bool(Reg.RAX, "sete" if op == "==" else "setne")
        # Into R11, never RAX: `_pop_slot` WRITES its target, and popping into
        # RAX would throw away the 0/1 the setcc just produced. Same trap, same
        # fix, as `_emit_str_affix`.
        self._pop_slot(Reg.R11)
        self._pop_slot(Reg.R11)
        return True

    def _emit_cmp(self, l, r, unsigned_mnem: str, signed_mnem: str) -> None:
        """l <op> r as 0/1 in RAX, at the signedness of the operands' type."""
        self._emit_expr(l)
        self._push_slot(Reg.RAX)
        self._emit_expr(r)
        self.asm.emit(encode_mov_r64_r64(Reg.R11, Reg.RAX))
        self._pop_slot(Reg.RAX)
        self.asm.emit(encode_cmp_r64_r64(Reg.RAX, Reg.R11))
        mnem = (signed_mnem if cmp_signed(
            common_type(self._ttype(l), self._ttype(r))) else unsigned_mnem)
        self._emit_setcc_bool(Reg.RAX, mnem)

    def _emit_compare_chain(self, e: F.CompareChain) -> None:
        """`a < b < c` — every operand evaluated once, the links ANDed.

        All operands are evaluated and pushed BEFORE any link is compared: an
        operand appears in two links (as one link's right side and the next
        one's left), and re-evaluating it would run its side effects twice.
        With them all on the stack, each link is two loads, a CMP and a SETcc,
        and the running AND lives in R10 (not a local home, and nothing
        clobbers it — no call happens in this loop)."""
        operands = e.operands
        ops = e.ops
        if len(operands) != len(ops) + 1:
            raise CodegenError("malformed compare chain")
        for operand in operands:
            self._emit_expr(operand)
            self._push_slot(Reg.RAX)
        n = len(operands)
        # Operand i was pushed i-th, so it now sits one _SLOT above RSP per
        # operand pushed after it.
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.RSP, _SLOT * (n - 1)))
        for i, op in enumerate(ops):
            if op not in _CMP_CONDS:
                raise CodegenError(
                    f"unsupported compare-chain operator {op!r} on the "
                    f"formal x86-64 path")
            unsigned, signed = _CMP_CONDS[op]
            self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP,
                                              _SLOT * (n - 1 - i)))
            self.asm.emit(encode_mov_r64_rm64(Reg.R11, Reg.RSP,
                                              _SLOT * (n - 2 - i)))
            self.asm.emit(encode_cmp_r64_r64(Reg.RAX, Reg.R11))
            mnem = (signed if cmp_signed(common_type(
                self._ttype(operands[i]), self._ttype(operands[i + 1])))
                else unsigned)
            self._emit_setcc_bool(Reg.RAX, mnem)
            self.asm.emit(encode_and_r64_r64(Reg.R10, Reg.RAX))
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R10))
        self.asm.emit(encode_add_r64_imm32(Reg.RSP, _SLOT * n))


    def _emit_and_or(self, left, right, is_or: bool) -> None:
        """Python short-circuit `and`/`or` as a value in RAX.

        `or`: evaluate left; if nonzero keep it, else evaluate right.
        `and`: evaluate left; if zero keep it, else evaluate right."""
        self._if_counter += 1
        aid = self._if_counter
        fn = self.func_name
        end_label = f"{fn}_ao{aid}_end"
        skip_label = f"{fn}_ao{aid}_skip"
        self._emit_truthy_word(left)
        self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
        self._record_cond_branch()
        # or: nonzero → done (skip right); and: zero → done.
        self._emit_jcc(COND_NE if is_or else COND_E, skip_label)
        self._emit_expr(right)
        self._emit_jmp(end_label)
        self.asm.label(skip_label)
        self.asm.label(end_label)

    def _emit_div_mod(self, e: F.BinaryOp, op: str) -> None:
        """`/` `//` `%`.

        IDIV/DIV are the one-operand forms: RDX:RAX divided by the operand,
        quotient in RAX and remainder in RDX. RDX is therefore not available
        as general scratch for the right operand, and the left one has to
        reach RAX before the divide. Division by zero is a hardware fault, so
        it is turned into exit(1) — the same signal the arm64 backend uses
        for its own divide-by-zero path.

        `/` and `//` both truncate toward zero here: formal's default integer
        type is unsigned, and the toy x86-64 path this was ported from made
        the same conflation (there was one `BinOp.Kind.DIV` for both)."""
        signed = cmp_signed(common_type(self._ttype(e.left),
                                        self._ttype(e.right)))
        self._if_counter += 1
        cid = self._if_counter
        fn = self.func_name
        div0_label = f"{fn}_dv{cid}_z"
        ok_label = f"{fn}_dv{cid}_ok"
        self._emit_expr(e.left)
        self._push_slot(Reg.RAX)
        self._emit_expr(e.right)
        self.asm.emit(encode_mov_r64_r64(Reg.R11, Reg.RAX))
        self._pop_slot(Reg.RAX)
        self.asm.emit(encode_test_r64_r64(Reg.R11, Reg.R11))
        self._record_cond_branch()
        self._emit_jcc(COND_E, div0_label)
        if signed:
            self.asm.emit(encode_cqo())
            self.asm.emit(encode_idiv_r64(Reg.R11))
        else:
            self.asm.emit(encode_xor_edx_edx())
            self.asm.emit(encode_div_r64(Reg.R11))
        if op == "%":
            self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.RDX))
        self._emit_trunc(common_type(self._ttype(e.left),
                                     self._ttype(e.right)))
        self._emit_jmp(ok_label)
        self.asm.label(div0_label)
        self._emit_call_exit(1)
        self.asm.label(ok_label)

    def _emit_shift(self, e: F.BinaryOp, op: str) -> None:
        """`<<` `>>`. A literal count in 0..63 uses the immediate form;
        anything else moves the count into CL (the only register form)."""
        result_t = common_type(self._ttype(e.left), self._ttype(e.right))
        # The signedness that picks `sar` over `shr` is the LEFT operand's own,
        # not the promotion's — a shift's right operand is a COUNT, and how
        # far to move says nothing about what to move in. `result_t` is still
        # the answer to "what width is the result", which does involve both
        # operands. See `model.shift_signedness`; the arm64 emitter asks the
        # same question the same way.
        signed = cmp_signed(M.shift_signedness(self._ttype(e.left)))
        lit = self._static_int(e.right)
        if lit is not None and 0 <= lit <= 63:
            self._emit_expr(e.left)
            self.asm.emit(encode_shift_r64_imm8(
                _SHIFT_CL[op] if signed else _SHIFT_IMM[op], Reg.RAX, lit))
            self._emit_trunc(result_t)
            return
        # A literal amount at or past the word's width, decided HERE with no
        # branch. The immediate form's range check above is what routes it
        # here, and the hardware would mask it back to a shift by zero —
        # `3 >> 64` was `3` on this backend exactly as on arm64, because both
        # were written to the same wrong rule (the rule itself is
        # `model.shift_saturated_is_zero`; the arithmetic `>>` case is not 0,
        # which is why only the SIGN is left to a run-time fact).
        if lit is not None and M.shift_saturates(lit):
            self._emit_expr(e.left)
            self._emit_saturated(op, signed)
            self._emit_trunc(result_t)
            return
        # The register form: put the value in RAX and the amount in RCX, which
        # is what `_emit_shift_reg` takes, and let it carry the saturation
        # rule. The binary form and the `<<=`/`>>=` form both come through
        # here, because they are one operator and a second copy of the rule
        # is how `y <<= 64` kept the hardware's masking while `y = y << 64`
        # did not.
        self._emit_expr(e.left)
        self._push_slot(Reg.RAX)
        self._emit_expr(e.right)
        self.asm.emit(encode_mov_r64_r64(Reg.RCX, Reg.RAX))
        self._pop_slot(Reg.RAX)
        self._emit_shift_reg(op, signed)
        self._emit_trunc(result_t)

    def _emit_shift_reg(self, op: str, signed: bool) -> None:
        """Variable shift RAX = RAX <op> RCX, SATURATING.

        THE ONE register-form shift emitter on this backend; RAX holds the
        value and RCX the amount on entry, and RAX is the result on exit.

        The amount is compared against 64 and a saturating branch taken
        BEFORE the shift, because the three x86 shift forms do not agree
        about an out-of-range count and agreeing with none of them is not a
        rule: `SHR`/`SAR` saturate at 63 (so `x >> 64` would be `x >> 63`,
        which is 1 for a negative operand where Python says 0), while `SHL`
        masks the count to 6 bits (so `x << 64` is `x`). One comparison
        covers all three, and the saturated value is the same one arm64
        computes — `model.shift_saturated_is_zero` is the rule and this is
        only its instruction selection.

        The compare is SIGNED, matching arm64's and for the same reason: an
        amount of 64 or more saturates, and a NEGATIVE one (which CPython
        rejects with ValueError, and which this path has always handed to
        the hardware) keeps the masking it had. Unsigned, a negative amount
        would take the saturating branch and answer 0 — a third wrong answer
        rather than the one that is there now. See
        bugs/FORMAL_negative_shift_amount_masks_instead_of_raising.md.
        """
        self._if_counter += 1
        sid = self._if_counter
        fn = self.func_name
        sat_label = f"{fn}_sh{sid}_sat"
        end_label = f"{fn}_sh{sid}_end"
        self.asm.emit(encode_cmp_r64_imm32(Reg.RCX, M.SHIFT_WIDTH))
        self._record_cond_branch()
        self._emit_jcc(COND_GE, sat_label)
        self.asm.emit(encode_shift_r64_cl(
            _SHIFT_CL[op] if signed else _SHIFT_IMM[op], Reg.RAX))
        self._emit_jmp(end_label)
        self.asm.label(sat_label)
        self._emit_saturated(op, signed)
        self.asm.label(end_label)

    def _emit_saturated(self, op: str, signed: bool) -> None:
        """Materialise the answer a SATURATING shift gives, in RAX.

        The decision is `model.shift_saturated_is_zero` — shared with arm64,
        so the two architectures cannot answer it differently — and this is
        only its instruction selection. Two cases, and the second is the one
        a `return 0` saturation gets wrong: `sar rax, 63` is exactly "the
        sign-extended word", 0 for a non-negative operand and -1 for a
        negative one, which is what Python's arithmetic `>>` gives at any
        amount at or past 64. `RAX` holds the value on entry, so the sign is
        read from it rather than recomputed."""
        if M.shift_saturated_is_zero(op, signed):
            self._emit_mov_imm(Reg.RAX, 0)
        else:
            self.asm.emit(encode_shift_r64_imm8(">>signed", Reg.RAX, 63))

    def _emit_pow(self, e: F.BinaryOp) -> None:
        """`**`.

        A small literal exponent unrolls into that many multiplies (the common
        `x ** 2`); anything else is binary exponentiation over a loop, which
        needs scratch the register allocator does not hand out, so the base
        and the accumulator live on the stack for the duration."""
        result_t = common_type(self._ttype(e.left), self._ttype(e.right))
        lit = self._static_int(e.right)
        if lit is not None and 0 <= lit <= 8:
            if lit == 0:
                self._emit_mov_imm(Reg.RAX, 1)
                return
            self._emit_expr(e.left)
            if lit == 1:
                self._emit_trunc(result_t)
                return
            if lit == 2:
                self.asm.emit(encode_imul_r64_r64(Reg.RAX, Reg.RAX))
            else:
                self._push_slot(Reg.RAX)
                for _ in range(lit - 1):
                    self.asm.emit(encode_mov_r64_r64(Reg.R11, Reg.RAX))
                    self._pop_slot(Reg.RAX)
                    self.asm.emit(encode_imul_r64_r64(Reg.RAX, Reg.R11))
                    self._push_slot(Reg.RAX)
                self._pop_slot(Reg.R11)
            self._emit_trunc(result_t)
            return
        if lit is not None and lit < 0:
            # Integer ** negative → 0: formal's integer lattice has no
            # fractions, and 0 matches the toy path for |base| > 1.
            self._emit_mov_imm(Reg.RAX, 0)
            return

        # Binary exponentiation. Stack layout: [rsp] is the accumulator,
        # [rsp+8] the base. The exponent stays in RAX for the whole loop — it
        # is the loop counter — so the body only touches RCX/R11.
        self._if_counter += 1
        pid = self._if_counter
        fn = self.func_name
        loop_label = f"{fn}_pow{pid}_l"
        body_label = f"{fn}_pow{pid}_b"
        done_label = f"{fn}_pow{pid}_d"
        neg_label = f"{fn}_pow{pid}_n"
        end_label = f"{fn}_pow{pid}_end"
        self._emit_expr(e.left)
        self._push_slot(Reg.RAX)                          # base
        self._emit_expr(e.right)                          # exponent -> RAX
        self._emit_mov_imm(Reg.R11, 1)
        self._push_slot(Reg.R11)                           # accumulator = 1
        # A negative exponent yields 0.
        self.asm.emit(encode_cmp_r64_imm8(Reg.RAX, 0))
        self._record_cond_branch()
        self._emit_jcc(COND_L, neg_label)

        self.asm.label(loop_label)
        self.asm.emit(encode_cmp_r64_imm8(Reg.RAX, 0))
        self._record_cond_branch()
        self._emit_jcc(COND_E, done_label)
        self.asm.label(body_label)
        # if exp & 1: acc *= base
        self._emit_mov_imm(Reg.R11, 1)
        self.asm.emit(encode_and_r64_r64(Reg.R11, Reg.RAX))
        skip_label = f"{fn}_pow{pid}_so"
        self._emit_jcc(COND_E, skip_label)
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, 0))     # acc
        self.asm.emit(encode_mov_r64_rm64(Reg.R11, Reg.RSP, _SLOT))  # base
        self.asm.emit(encode_imul_r64_r64(Reg.RCX, Reg.R11))
        self.asm.emit(encode_mov_rm64_r64(Reg.RSP, 0, Reg.RCX))
        self.asm.label(skip_label)
        # base *= base
        self.asm.emit(encode_mov_r64_rm64(Reg.RCX, Reg.RSP, _SLOT))
        self.asm.emit(encode_imul_r64_r64(Reg.RCX, Reg.RCX))
        self.asm.emit(encode_mov_rm64_r64(Reg.RSP, _SLOT, Reg.RCX))
        # exp >>= 1
        self.asm.emit(encode_shift_r64_imm8(">>", Reg.RAX, 1))
        self._emit_jmp(loop_label)
        self.asm.label(done_label)
        self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RSP, 0))
        self.asm.emit(encode_add_r64_imm32(Reg.RSP, 2 * _SLOT))  # drop both
        self._emit_trunc(result_t)
        self._emit_jmp(end_label)
        self.asm.label(neg_label)
        self.asm.emit(encode_add_r64_imm32(Reg.RSP, 2 * _SLOT))
        self._emit_mov_imm(Reg.RAX, 0)
        self.asm.label(end_label)

    def _emit_subscript_store(self, target: F.SubscriptExpr, value) -> None:
        """`obj[index] = value` — the address is computed once, then stored.

        The index expression is evaluated exactly once (it can contain calls),
        and the value after it, so the two evaluate in source order."""
        self._emit_expr(value)
        self._push_slot(Reg.RAX)                   # value
        self._emit_subscript_addr(target)          # RAX = address
        self._pop_slot(Reg.R11)                    # R11 = value
        if self._sub_width == 1:
            # A BYTE store, and this used to be a full 64-bit store into a
            # one-byte element: both branches of the old `if` were the same
            # instruction, so `p[0] = 65` on a `Pointer[UInt8]` overwrote the
            # seven bytes after it. It was unreachable over a POINTER (the
            # subscript took the blob path and exited 1 first) and reachable
            # over a `char *` in a string literal, which is a read-only
            # __TEXT page, so nothing noticed. Widening `_sub_width` to the
            # pointee made it reachable over a `malloc`'d buffer, where the
            # overwrite is a silent corruption rather than a fault, so the two
            # branches have to differ.
            self.asm.emit(encode_mov_rm8_r8(Reg.RAX, 0, Reg.R11))
        else:
            self.asm.emit(encode_mov_rm64_r64(Reg.RAX, 0, Reg.R11))

    def _emit_slice_store(self, target: F.SliceExpr, value) -> None:
        raise CodegenError(
            "assignment to a slice target is not lowered on the formal "
            "x86-64 path: a slice is a materialized copy here, so writing "
            "through one would have to write back into its source blob")

    def _emit_tuple_assign(self, stmt) -> None:
        """`a, b = rhs` — the RHS must be a `[count][e0…]` blob.

        The count is checked against the target arity and a mismatch
        exits(1), the same signal an out-of-range subscript gives."""
        names = []
        for el in stmt.target.elements:
            if isinstance(el, F.IdentExpr):
                names.append(el.name)
            elif isinstance(el, (F.ListExpr, F.TupleExpr)):
                names.extend(e.name for e in el.elements
                             if isinstance(e, F.IdentExpr))
            else:
                raise CodegenError(
                    "tuple assignment targets must be plain names on the "
                    f"formal x86-64 path (got {type(el).__name__})")
        if not names:
            raise CodegenError("tuple assignment needs at least one target")
        self._emit_expr(stmt.value)
        self._emit_for_unpack(names, Reg.RAX,
                              f"{self.func_name}_ta{self._while_counter}")

    def _emit_slice_parts(self, obj, start, stop, step) -> None:
        """`obj[start:stop:step]` → a NEW blob holding the selected elements.

        Python slice semantics over a blob: a missing bound defaults per side
        (0 / len going up, -1 / len-1 coming down), a negative bound counts
        from the end, and the result is empty when the range runs the wrong
        way. The result is a copy — a blob has no spare capacity, and the
        source may be shared with another name.

        A non-literal step has no compile-time value, so the element stride
        the copy loop folds into its address arithmetic is unknown here; that
        raises rather than emitting a wrong stride.

        A STRING base is refused before any of that, and the reason is the
        count: the loop below reads it from offset 0 of the object, which for a
        `char *` is the first eight CHARACTERS, so the walk starts inside the
        string with a length taken from its own first two letters. Measured on
        both backends, `s = "abcde"; printf("[%s]", s[1:])` died with SIGSEGV
        (exit 139). `model.string_slice_refusal` holds the message and the
        argument for lowering the suffix case later."""
        self._refuse_frame_container_operand("a slice", obj)
        sreason = M.string_slice_refusal(
            self._expr_str_kind(obj), M.spelled(obj))
        if sreason is not None:
            raise CodegenError(sreason)
        lit_step = self._static_int(step) if step is not None else 1
        if lit_step is None:
            raise CodegenError(
                "a slice with a non-literal step is not lowered on the formal "
                "x86-64 path: the copy loop's stride is fixed at emit time")
        if lit_step == 0:
            raise CodegenError(
                "a slice step of 0 is a ValueError in Python and has no "
                "meaning on the formal x86-64 path")
        ascending = lit_step > 0
        stride = 8 * abs(lit_step)

        self._emit_expr(obj)
        self._push_slot(Reg.RAX)                   # source blob
        cap = 64
        static_len = self._static_int(stop)
        if static_len is not None and static_len > 0:
            cap = static_len
        offset = self._reserve_blob(8 + 8 * cap, "slice views")
        self._pop_slot(Reg.RSI)                    # source
        self.asm.emit(encode_mov_r64_rm64(Reg.R8, Reg.RSI, 0))   # n

        def bound(expr, default):
            return expr if expr is not None else F.IntLiteral(default)

        self._emit_expr(bound(start, 0 if ascending else -1))
        self._push_slot(Reg.RAX)
        if stop is None and ascending:
            # `xs[3:]` runs to the END of the sequence, so the default stop
            # is the element count — a runtime value, not a literal. Using 0
            # here instead makes every open-ended slice empty (stop <= start)
            # and every read of the result a bounds failure.
            self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R8))
        else:
            self._emit_expr(bound(stop, -1))
        self.asm.emit(encode_mov_r64_r64(Reg.RDX, Reg.RAX))    # stop
        self._pop_slot(Reg.RCX)                                 # start
        # Clamp each bound into [0, n]; a negative one counts from the end.
        for reg in (Reg.RCX, Reg.RDX):
            tag = f"{self.func_name}_s{reg.value}"
            self.asm.emit(encode_cmp_r64_imm8(reg, 0))
            self._emit_jcc(COND_GE, f"{tag}a")
            self.asm.emit(encode_add_r64_r64(reg, Reg.R8))
            self.asm.label(f"{tag}a")
            self.asm.emit(encode_cmp_r64_imm8(reg, 0))
            self._emit_jcc(COND_GE, f"{tag}z")
            self._emit_mov_imm(reg, 0)
            self.asm.label(f"{tag}z")
            self.asm.emit(encode_cmp_r64_r64(reg, Reg.R8))
            self._emit_jcc(COND_LE, f"{tag}c")
            self.asm.emit(encode_mov_r64_r64(reg, Reg.R8))
            self.asm.label(f"{tag}c")
        # n has done its work; R8 now carries the clamped start, which the
        # copy loop needs and RCX does not have room for.
        self.asm.emit(encode_mov_r64_r64(Reg.R8, Reg.RCX))

        fn = self.func_name
        self._if_counter += 1
        sid = self._if_counter
        empty_label = f"{fn}_sl{sid}_empty"
        go_label = f"{fn}_sl{sid}_go"
        # count = ceil(|stop - start| / |step|) when the range runs the right
        # way, else 0. The divide is the unsigned DIV form, so RDX is zeroed
        # first and the quotient comes back in RAX.
        if ascending:
            self.asm.emit(encode_cmp_r64_r64(Reg.RDX, Reg.RCX))
        else:
            self.asm.emit(encode_cmp_r64_r64(Reg.RCX, Reg.RDX))
        self._emit_jcc(COND_LE, empty_label)
        # Two-operand SUB writes the difference into its FIRST operand, so
        # the subtraction happens in RDX and the result moves to R9.
        self.asm.emit(encode_sub_r64_r64(Reg.RDX, Reg.RCX))
        self.asm.emit(encode_mov_r64_r64(Reg.R9, Reg.RDX))
        if not ascending:
            self.asm.emit(encode_neg_r64(Reg.R9))
        self._emit_mov_imm(Reg.R10, abs(lit_step))
        self.asm.emit(encode_add_r64_r64(Reg.R9, Reg.R10))
        self.asm.emit(encode_sub_r64_imm32(Reg.R9, 1))
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.R9))
        self.asm.emit(encode_xor_edx_edx())
        self.asm.emit(encode_div_r64(Reg.R10))
        self.asm.emit(encode_mov_r64_r64(Reg.R9, Reg.RAX))     # count
        self._emit_jmp(go_label)
        self.asm.label(empty_label)
        self._emit_mov_imm(Reg.R9, 0)
        self.asm.label(go_label)

        self._emit_blob_base(offset, Reg.RDI)
        self.asm.emit(encode_mov_rm64_r64(Reg.RDI, 0, Reg.R9))
        # src = blob + 8 + 8*start  (the element area, at the clamped start)
        self.asm.emit(encode_mov_r64_r64(Reg.R10, Reg.RSI))
        self.asm.emit(encode_add_r64_imm32(Reg.R10, 8))
        self.asm.emit(encode_shift_r64_imm8("<<", Reg.R8, 3))
        self.asm.emit(encode_add_r64_r64(Reg.R10, Reg.R8))
        self.asm.emit(encode_mov_r64_r64(Reg.RCX, Reg.RDI))
        self.asm.emit(encode_add_r64_imm32(Reg.RCX, 8))
        self._emit_mov_imm(Reg.R11, 0)
        copy_label = f"{fn}_sl{sid}_copy"
        done_label = f"{fn}_sl{sid}_done"
        self.asm.label(copy_label)
        self.asm.emit(encode_cmp_r64_r64(Reg.R11, Reg.R9))
        self._emit_jcc(COND_AE, done_label)
        self.asm.emit(encode_mov_r64_rm64(Reg.R8, Reg.R10, 0))
        self.asm.emit(encode_mov_rm64_r64(Reg.RCX, 0, Reg.R8))
        if ascending:
            self.asm.emit(encode_add_r64_imm32(Reg.R10, stride))
        else:
            self.asm.emit(encode_sub_r64_imm32(Reg.R10, stride))
        self.asm.emit(encode_add_r64_imm32(Reg.RCX, 8))
        self.asm.emit(encode_add_r64_imm8(Reg.R11, 1))
        self._emit_jmp(copy_label)
        self.asm.label(done_label)
        self.asm.emit(encode_mov_r64_r64(Reg.RAX, Reg.RDI))

    def _emit_comprehension(self, expr: F.Comprehension) -> None:
        """Lower a list/set/dict/generator comprehension to a frame blob.

        The result layout is the list/dict one (`[count][element…]`), built by
        APPENDING: the blob is reserved with a capacity up front (a blob has
        no way to grow), the count starts at 0 and is incremented per element,
        and appending past the reserved capacity exits(1) rather than writing
        past the blob area. Nested generators recurse, each with its own
        `_ci{d}`/`_cb{d}` temps, so a comprehension inside a for (or the
        reverse) cannot alias a loop's.

        A dict comprehension stores its KEY in `.element` and its VALUE in
        `.key` — the parser's swap, which the arm64 backend also relies on."""
        is_dict = (getattr(expr, "kind", "list") == "dict")
        gens = expr.generators or []
        elem_size = 16 if is_dict else 8
        if not gens:
            offset = self._reserve_blob(8, "comprehension")
            self._emit_blob_base(offset, Reg.RAX)
            self._emit_mov_imm(Reg.R11, 0)
            self.asm.emit(encode_mov_rm64_r64(Reg.RAX, 0, Reg.R11))
            self._emit_blob_base(offset, Reg.RAX)
            return

        cap = self._compr_cap(expr)
        avail = self._blob_cap - self._list_cursor
        if avail < 8:
            raise CodegenError(
                f"comprehension exceeds the formal frame "
                f"({self._list_cursor} > {self._blob_cap} bytes)")
        max_cap = (avail - 8) // elem_size
        cap = max(0, min(cap, max_cap))
        offset = self._reserve_blob(8 + elem_size * cap, "comprehension")
        self._emit_blob_base(offset, Reg.R11)
        self._emit_mov_imm(Reg.R10, 0)
        self.asm.emit(encode_mov_rm64_r64(Reg.R11, 0, Reg.R10))

        d0 = self._compr_depth
        self._compr_depth = d0 + len(gens)
        try:
            self._emit_compr_gen(expr, 0, offset, is_dict, cap, d0)
        finally:
            self._compr_depth = d0
        self._emit_blob_base(offset, Reg.RAX)

    def _emit_compr_gen(self, expr: F.Comprehension, gi: int, res_offset: int,
                        is_dict: bool, cap: int, d0: int) -> None:
        """Recursive generator walk: gen[gi] … gen[-1], then append."""
        gens = expr.generators
        if gi >= len(gens):
            if is_dict:
                self._emit_expr(expr.element)          # KEY
                self._push_slot(Reg.RAX)
                self._emit_expr(expr.key)              # VALUE
                self._compr_append_pair(res_offset, cap)
            else:
                self._emit_expr(expr.element)
                self._compr_append_elem(res_offset, cap)
            return

        gen = gens[gi]
        di = d0 + gi
        ci_name, cb_name = f"_ci{di}", f"_cb{di}"

        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        start_label = f"{fn}_cg{wid}_start"
        step_label = f"{fn}_cg{wid}_step"
        false_label = f"{fn}_cg{wid}_false"
        end_label = f"{fn}_cg{wid}_end"

        # Under container context so a BinaryOp `+` iterable means concat.
        self._container_ctx += 1
        try:
            self._emit_expr(gen.iterable)
        finally:
            self._container_ctx -= 1
        self._store_var(cb_name, Reg.RAX)
        self._emit_mov_imm(Reg.RAX, 0)
        self._store_var(ci_name, Reg.RAX)

        self._loops.append({"start": start_label, "step": step_label,
                            "break": end_label})
        try:
            self.asm.label(start_label)
            self._load_var(cb_name, Reg.R11)
            self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.R11, 0))   # count
            self._load_var(ci_name, Reg.RAX)
            self.asm.emit(encode_cmp_r64_r64(Reg.RAX, Reg.R10))
            # R8, not R11: R11 holds the blob base, and the element
            # address computed next is relative to it.
            self._emit_setcc_bool(Reg.R8, "setae")
            self._emit_jcc_bool(Reg.R8, COND_NE, false_label)
            self._emit_elem_addr(Reg.R11, Reg.RAX, Reg.RDI)
            self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.RDI, 0))

            from mojo.middle.boundnames import _lbn_target_names
            tnames = _lbn_target_names(gen.target) \
                if isinstance(gen.target, str) else []
            if not tnames or any(not n.isidentifier() for n in tnames):
                raise CodegenError(
                    f"comprehension target must be a plain name or tuple of "
                    f"plain names (got {gen.target!r})")
            if len(tnames) == 1:
                self._store_var(tnames[0], Reg.RAX)
            else:
                self._emit_for_unpack(tnames, Reg.RAX, f"{fn}_cgu{wid}")

            for cond in gen.conditions or []:
                self._emit_truthy_word(cond)
                self.asm.emit(encode_test_r64_r64(Reg.RAX, Reg.RAX))
                self._record_cond_branch()
                self._emit_jcc(COND_E, step_label)

            self._emit_compr_gen(expr, gi + 1, res_offset, is_dict, cap, d0)

            self.asm.label(step_label)
            self._load_var(ci_name, Reg.RAX)
            self.asm.emit(encode_add_r64_imm8(Reg.RAX, 1))
            self._store_var(ci_name, Reg.RAX)
            self._emit_jmp(start_label)

            self.asm.label(false_label)
            self.asm.label(end_label)
        finally:
            self._loops.pop()

    def _compr_append_elem(self, res_offset: int, cap: int) -> None:
        """Append RAX to the list result; exit(1) past the reserved capacity.

        Registers: R11 the result blob, R10 the count, RDI the element's
        address. RDI rather than R11 because `_emit_elem_addr` builds the
        destination FROM the index first, so the base register has to survive
        that first move — passing the same register for both computes
        base+8*base."""
        self._push_slot(Reg.RAX)                     # the element
        self._emit_blob_base(res_offset, Reg.R11)
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.R11, 0))   # count
        self.asm.emit(encode_cmp_r64_imm32(Reg.R10, cap))
        self._emit_setcc_bool(Reg.R8, "setae")
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        oob = f"{fn}_cgoob{wid}"
        ok = f"{fn}_cgok{wid}"
        self._emit_jcc_bool(Reg.R8, COND_NE, oob)
        self._emit_jmp(ok)          # in range: skip the exit
        self.asm.label(oob)
        self._emit_call_exit(1)
        self.asm.label(ok)
        self._emit_elem_addr(Reg.R11, Reg.R10, Reg.RDI)
        self._pop_slot(Reg.RAX)
        self.asm.emit(encode_mov_rm64_r64(Reg.RDI, 0, Reg.RAX))
        self.asm.emit(encode_add_r64_imm8(Reg.R10, 1))
        self._emit_blob_base(res_offset, Reg.R11)
        self.asm.emit(encode_mov_rm64_r64(Reg.R11, 0, Reg.R10))

    def _compr_append_pair(self, res_offset: int, cap: int) -> None:
        """Append a (key, value) pair to a dict result.

        The caller leaves the KEY in a pushed slot and the VALUE in RAX, so
        the VALUE is pushed here to complete the pair; the pop order below
        unwinds it in the opposite order."""
        self._push_slot(Reg.RAX)                     # VALUE above KEY
        self._emit_blob_base(res_offset, Reg.R11)
        self.asm.emit(encode_mov_r64_rm64(Reg.R10, Reg.R11, 0))   # npairs
        self.asm.emit(encode_cmp_r64_imm32(Reg.R10, cap))
        self._emit_setcc_bool(Reg.R8, "setae")
        self._while_counter += 1
        wid = self._while_counter
        fn = self.func_name
        oob = f"{fn}_cpoob{wid}"
        ok = f"{fn}_cpok{wid}"
        self._emit_jcc_bool(Reg.R8, COND_NE, oob)
        self._emit_jmp(ok)          # in range: skip the exit
        self.asm.label(oob)
        self._emit_call_exit(1)
        self.asm.label(ok)
        self._emit_elem_addr(Reg.R11, Reg.R10, Reg.RDI, header=8, scale=4)
        self._pop_slot(Reg.R8)                       # VALUE
        self.asm.emit(encode_mov_rm64_r64(Reg.RDI, 8, Reg.R8))
        self._pop_slot(Reg.R8)                       # KEY
        self.asm.emit(encode_mov_rm64_r64(Reg.RDI, 0, Reg.R8))
        self.asm.emit(encode_add_r64_imm8(Reg.R10, 1))
        self._emit_blob_base(res_offset, Reg.R11)
        self.asm.emit(encode_mov_rm64_r64(Reg.R11, 0, Reg.R10))

    # ── calls ────────────────────────────────────────────────────────

    def _scan_value_kinds(self, fn) -> M.ValueKinds:
        """What every local of `fn` holds, from its source alone.

        The decision is model.ValueKinds' (it has to come out the same on both
        backends); this supplies the hooks that are this backend's: the
        annotation vocabularies from formal.types, a callee's kind from its
        declared return type or its return statements, the local-slot key
        for a field chain, and — since a field's DECLARED type is a fact about
        the struct rather than about this function — `_declared_kind` below."""
        return self._vkinds_for(fn.name, fn, frozenset())

    def _vkinds_for(self, name, fn, stack) -> M.ValueKinds:
        """A ValueKinds for `fn`, memoized across the whole module.

        `_functions` is fixed for a compile, so the answer for a callee does
        not change between call sites; the `stack` is what stops
        `def a(): return b()` / `def b(): return a()` from recursing forever
        (a cycle is a word, like every other undecidable answer)."""
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
        with the arm64 emitter: a bare name (`from mod import f`) is answered by
        the flat map and a dotted one (`import mod`, spelled `mod.f`) only by
        the library built for that module or by what that module forwards, so
        `mod.f` can never bind some other library's `f`; and a dotted name whose
        module IS linked but does not publish it is refused here, naming both
        halves, rather than emitted as a BL against a symbol nothing defines.
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
            # an integer — the pointer's own value.
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

        A list blob is `[count][elem0]…` carved out of the frame, so
        `xs.append(v)` needs room the literal's own element count does not
        promise — `xs = []` plus one append is the commonest shape there is and
        starts with nothing. The number of `append` call sites on a name in
        this function is a sound compile-time bound for STRAIGHT-LINE code, and
        the store is bounds-checked against it at run time, so the shape this
        gets wrong (an append inside a loop) exits(1) loudly instead of writing
        past the blob — the same bargain every other bounded container
        operation on this path makes.

        Two maps because the two ends of the operation are different places:
        `_emit_list` allocates and has only the literal NODE (an expression
        carries no name); `_emit_list_append` stores and has only the
        receiver's NAME. Both are computed from one pass so they cannot
        disagree. A name bound to more than one literal takes the smallest of
        their capacities, so the bound holds whichever blob is live."""
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

    def _note_binding(self, name: str, value) -> None:
        """Record that `name` now holds a string address (or stop saying so).

        A subscript on a string address is a byte load rather than a list
        index, and nothing else in the value distinguishes the two, so the
        binding has to be tracked at each store. An assignment of anything
        else clears the mark."""
        # A dict is checked FIRST: it is a pair-blob too, but its subscript is
        # a key lookup, so it must not be recorded as a plain blob (which
        # would make `d[k]` take the index path and read the key as data).
        #
        # The descriptor mark is separate and not mutually exclusive: a
        # descriptor IS an int, so a name bound to one is correctly an int too,
        # but it must not be handed to `write(2)`/`close(2)` as an arbitrary
        # number. See model.VALUE_METHOD_RECEIVERS.
        if M.is_open_call(value):
            self._fd_vars.add(name)
        elif isinstance(value, F.IdentExpr) and value.name in self._fd_vars:
            self._fd_vars.add(name)          # an alias keeps it: `g = f`
        else:
            self._fd_vars.discard(name)
        if isinstance(value, F.DictExpr) or (
                isinstance(value, F.IdentExpr)
                and value.name in self._dict_vars):
            self._dict_vars.add(name)
        elif self._is_container_expr(value) or (
                isinstance(value, F.IdentExpr)
                and value.name in self._blob_vars):
            self._blob_vars.add(name)
        elif isinstance(value, F.StringLiteral) or (
                isinstance(value, F.IdentExpr)
                and value.name in self._string_vars):
            self._string_vars.add(name)
        elif isinstance(value, F.CallExpr) and M.string_method_yields_string(
                value, self._expr_str_kind(
                    value.func.obj if isinstance(value.func, F.MemberExpr)
                    else None) == M.STR_KIND):
            # A lowered string method that yields a string: `m = s.lstrip()`
            # binds a `char *` exactly as `m = s` does. Without this the name
            # fell through to the clearing `else` below, and the consequence
            # was not a refusal — it was a WRONG ANSWER, because the things
            # that consult `_string_vars` (a string `==`, and `print`) then
            # treated the pointer as a number. `"  hi".lstrip() == "hi"`
            # compared a pointer against an integer and said False.
            self._string_vars.add(name)
        else:
            self._string_vars.discard(name)
            self._dict_vars.discard(name)
            self._blob_vars.discard(name)

    def _is_container_expr(self, e) -> bool:
        """True when `e` is known to lower to a blob pointer rather than an
        integer — the test that decides whether `+` concatenates."""
        if isinstance(e, (F.ListExpr, F.TupleExpr, F.SetExpr, F.DictExpr,
                          F.Comprehension, F.SliceExpr)):
            return True
        if isinstance(e, F.CallExpr) and isinstance(e.func, F.IdentExpr):
            return e.func.name in ("range", "list", "sorted", "set",
                                   "reversed")
        if isinstance(e, F.BinaryOp) and e.op in ("+", "|", "or", "and"):
            return (self._is_container_expr(e.left)
                    or self._is_container_expr(e.right))
        if isinstance(e, F.IdentExpr):
            return e.name in self._blob_vars
        return False

    def _emit_call(self, e: F.CallExpr) -> None:
        name = _callee_symbol(e.func)
        if name is None:
            # A SUBSCRIPT callee, `List[Int]()`. arm64's `_callee_symbol` has
            # carried a `SubscriptExpr` arm for a long time and this copy has
            # not, so a bracketed call target reaches the refusal below on this
            # architecture alone — a pre-existing x86-64 gap, listed in
            # `bugs/FORMAL_wide_receiver_by_reference.md` §5.1 among the
            # architecture gaps, and NOT closed here: closing it means teaching
            # this backend a comptime-specialization call convention it does not
            # have, which is a change of far more than this construct.
            #
            # What IS closed here is the one bracketed callee this path can
            # answer, and it is closed by asking the SAME two shared predicates
            # arm64 asks rather than by copying its decision: the base name
            # (`model.subscript_callee_name`) and whether that name has an
            # empty form (`model.empty_blob_constructor`). So the two
            # architectures reach the same answer for `List[Int]()` by the same
            # rule, and the residual gap stays a gap instead of becoming a
            # third private copy of the flattening.
            base = M.subscript_callee_name(e)
            if base is not None and M.empty_blob_constructor(base):
                operands = list(e.args) + [v for _n, v in (e.kwargs or [])]
                if operands:
                    raise CodegenError(
                        M.blob_constructor_with_operands_refusal(
                            base, len(operands)))
                self._emit_empty_blob()
                return
            raise CodegenError(
                "unsupported call target on the formal x86-64 path "
                f"(got {type(e.func).__name__})")
        if name == "range":
            # A range() used as a VALUE rather than as a for-loop iterable:
            # materialize it as a list blob, which is what makes
            # `[i for i in range(n)]` and `for i in list(range(n))` work.
            self._emit_range_list(list(e.args))
            return
        if name == "len":
            self._emit_len(e)
            return
        if name == "print":
            self._emit_print(e)
            return
        if M.builtin_function(name) == "file_open":
            self._emit_open(e)
            return
        # A DEREFERENCE.  Intercepted HERE rather than left to the value-method
        # table below for two reasons, and both are about the RESULT rather than
        # about the receiver.  A dereference is an EXPRESSION: `return
        # pointer.unsafe_value()`, `s._ptr = p.value()` — the corpus puts it in
        # argument, store and return positions, and `_emit_value_method` is a
        # statement emitter with no result register, so the only place its answer
        # can land is RAX.  And the decision has to be
        # `model.dereference_lowering` and not `model.value_method_refusal`,
        # because the refusal cannot see the function and so cannot see a
        # declared pointee — which is the whole of the pointer value model.
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
        # this, `items.append(4)` became a call to a symbol spelled
        # `items.append` — an image that built and then died in the loader.
        if isinstance(e.func, F.MemberExpr) and \
                self._is_value_receiver(e.func.obj):
            self._emit_value_method(e, e.func.member)
            return
        # A TYPE is not a function. Intercepted before the extern path, which
        # would emit a `call _S` against a symbol named after the type —
        # nothing defines it, so the image builds and then cannot be loaded.
        # arm64 has always made this decision (and has always read the same two
        # shared tables); x86-64 did not, so the same source either refused on
        # one architecture and produced an unloadable binary on the other, or
        # silently agreed to something neither backend meant.
        #
        # The one exception, and it is arm64's rule read from the same shared
        # predicate: a name in `UNREPRESENTABLE_TYPE_CTORS` that this module
        # also declares as a struct, called with that struct's field count, is
        # a construction of that struct.  `model.type_constructor_prefers_local
        # _struct` is where the arity rule and the two exclusions live.
        if name not in self._functions:
            nargs = len(e.args) + len(e.kwargs or [])
            if not M.type_constructor_prefers_local_struct(
                    name, self._structs, nargs):
                tkind = M.type_constructor_kind(name)
                if tkind is not None:
                    self._emit_type_constructor(e, name, tkind)
                    return
        if name in self._structs:
            self._emit_struct_constructor(e, name, self._structs[name])
            return
        is_extern = name not in self._functions
        # The gimple backend's C runtime is a library of a DIFFERENT target, not
        # an external dependency of this one, and the source spells its ABI as
        # bare `mojo_*` names. Everything a call to one of those could bind to
        # has been ruled out above (not a function of this module, not a struct,
        # not a type constructor, and a linked dylib supplies its own spelling
        # below). What is left is decided by the runtime's ABI rather than by
        # the name, in the one shared function arm64 also reads, so the two
        # architectures cannot come to different verdicts about one construct:
        # a call is answerable when every type crossing the boundary is one
        # 64-bit word — which is what a value IS here — AND the symbol is on the
        # link line. A `MojoList *` argument is a box no link line can answer
        # and is refused even when a dylib provides the symbol; `mojo_print`,
        # whose every type is a word, is refused only because nothing here
        # provides it. Same decision, same words, from the one place.
        if is_extern and not M.gimple_runtime_callable(
                name, name in self._dylib_syms):
            raise CodegenError(M.gimple_runtime_refusal(name))
        # A callee that a linked formal dylib provides is emitted against the
        # spelling that dylib exports, not the name the source used.
        symbol = self._extern_symbol(name)
        # An unknown signature has no place for keyword arguments on a raw
        # call, so an extern call passes positionals only; those kwargs are
        # almost always literals like `flush=True`. A known callee gets them
        # bound to their parameters' registers.
        args = list(e.args) if is_extern else self._bind_call_args(name, e)

        if len(args) > len(ARG_REGS):
            raise CodegenError(
                f"call {name}(): {len(args)} arguments exceeds the "
                f"{len(ARG_REGS)} the formal x86-64 ABI passes in registers")
        # Evaluate left to right onto the stack, then pop in reverse into the
        # argument registers: evaluating argument i+1 clobbers RAX and every
        # caller-saved register, including the ones argument i belongs in.
        # POP only ever targets RAX, so each popped value is moved across
        # after the pop — including argument 0, whose register is RDI and not
        # RAX the way the arm64 ABI's X0 would have been.
        for arg in args:
            self._emit_expr(arg)
            self._push_slot(Reg.RAX)
        for i in range(len(args) - 1, -1, -1):
            self._pop_slot(Reg.RAX)
            self.asm.emit(encode_mov_r64_r64(ARG_REGS[i], Reg.RAX))

        if is_extern:
            # AL = number of vector registers used, which the ABI requires a
            # variadic callee be told; 0 is always right for the calls this
            # path makes, and harmless for the rest.
            self._emit_mov_imm(Reg.RAX, 0)
            self._emit_extern_call(symbol)

        else:
            self.asm.emit(encode_call_rel32(0))
            self.asm.emit_label_rel32(name, here_offset=-4)


    def _bind_call_args(self, name: str, e: F.CallExpr) -> list:
        """`e`'s arguments in positional form, for a known callee.

        A THIN CALL into `M.bind_call_arguments` — the same one arm64 calls,
        and the reason the two backends cannot disagree about which argument
        lands on which parameter.  This was a second copy of the rule whose
        `if not e.kwargs: return list(e.args)` skipped the arity check
        entirely for a call with no keywords."""
        fdef = self._functions.get(name)
        if fdef is None:
            if e.kwargs:
                raise CodegenError(
                    f"keyword arguments are not supported "
                    f"({[k for k, _ in e.kwargs]})")
            return list(e.args or [])
        slots, err = M.bind_call_arguments(name, fdef, e.args, e.kwargs)
        if err is not None:
            raise CodegenError(err)
        return slots

    # ── types and immediates ─────────────────────────────────────────

    def _emit_type_constructor(self, e: F.CallExpr, name: str,
                               tkind: tuple) -> None:
        """`Int(x)` / `String(s)` / `Span(...)` — a conversion or a refusal.

        The three answers are the shared model's (`M.type_constructor_kind`),
        and this is the x86-64 half of them. arm64 has always had this; without
        it x86-64 emitted a `call _Pointer` for `Pointer(0)`, which links
        against nothing and kills the image in dyld at launch.

        An UNREPRESENTABLE type is refused here rather than passed through: a
        `Span` or an `Error` is not something one 64-bit word can be, and a
        backend that pretended otherwise would build an image whose answer is
        not the program's."""
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
                # `LEN_FROM_BLOB_FIELD` reads a length from.  arm64 does this in
                # its own `_emit_type_constructor` with the same wording, and
                # `model.empty_blob_constructor` is the one predicate both ask,
                # so the two cannot answer differently about which names have
                # an empty form.
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
        # A keyword argument names the same single value a positional one does,
        # so it is accepted as the operand — arm64 has always done this and its
        # comment says why: `String(unsafe_from_utf8_ptr=…)` is how
        # std/os/env.mojo builds a string from a raw pointer, and refusing
        # every keyword form blocked 78 stdlib files on a shape the language
        # allows. x86-64 read `e.args` alone, so the two backends disagreed
        # about one source file over a conversion neither of them had a reason
        # to refuse. Measured with no frame anywhere in the program (a
        # one-field struct, so nothing here is a receiver): `Pointer(to=t)`
        # built on arm64 and was refused here with "got 0 argument(s)".
        #
        # It became REACHABLE from the frame hand-off rather than being
        # harmless: `Pointer(to=stat)` over a struct's frame is the one hand-off
        # in the frame family that is correct (a pointer wants the address, and
        # a frame address is one), and it is spelled with a keyword, so the
        # frame analysis stopped refusing the file and this refusal took its
        # place. What is still refused is a genuine mismatch of ARITY — a
        # conversion has one operand, and two of them, positioned or named, is
        # not a conversion.
        operands = list(e.args) + [v for _n, v in (e.kwargs or [])]
        if not operands:
            # The ONE zero-operand conversion this path can answer, and the
            # reason is a property of STRINGS and of nothing else: a literal
            # here is interned and NUL-terminated, so the address of `""` IS
            # the empty string, `strlen` of it is 0 and `printf("%s")` of it
            # prints nothing.  So `String()` is `String("")` by another
            # spelling, and refusing it refused a representable program over a
            # word COUNT rather than over the value.  A zero operand for any
            # other type is still refused — 0 is not the empty `Pointer` and
            # not the empty `Int` in any sense this value model can state.
            if name in M.STRING_TYPE_CTORS:
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
        self._emit_extend(Reg.RAX, IntType(width, signed))

    def _emit_struct_constructor(self, e: F.CallExpr, name: str,
                                 st) -> None:
        """`S()` — default-initialize a struct, not a call.

        The x86-64 twin of arm64's `_emit_struct_constructor`, and the reason
        the two backends no longer disagree here. Mojo has no user-defined
        constructor: `S()` brings every field up at its default and the fields
        are then assigned. On this path a value is one 64-bit word, so that is
        exactly what a struct of zero or one field IS — the word itself, zero
        for a fresh one — and neither shape needs a call.

        WIDER structs are represented BY REFERENCE on both machines — the
        receiver word is the ADDRESS of a frame of 8-byte slots, and every
        field is brought up at its own default. arm64 emits `LDR`/`STR
        Xt, [Xn, #8k]` for those; this emits `mov` to and from `[Rn + 8k]` for
        the same layout, and the layout itself is `formal/model.py`'s so the
        two cannot disagree about it.

        A struct that fits NEITHER representation is refused by name and
        width. It used to reach the extern path here and produce an image that
        built and then could not be loaded ("Symbol not found: _Point"), while
        arm64 refused the identical source; an x86-64 backend that emits a call
        to a symbol nothing defines is exactly the failure these diagnostics
        exist to prevent."""
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
            # A ONE-FIELD struct with an argument: the receiver IS the field, so
            # the argument is not stored, it is the result.  What is refused is
            # what the shared DECISION refuses, by name — see
            # `model.struct_construction_plan`, which is the same function
            # arm64 calls, so the two architectures cannot disagree about which
            # of the shapes this is or about why one of them is refused.
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

    def _emit_frame_constructor(self, e: F.CallExpr, name: str, st) -> None:
        """`S()`, `S(a, b, …)`, `S(a, b, c)` with an `__init__`, or `S(x)`.

        The x86-64 half of the four shapes.  The DECISION is shared
        (`formal/model.py`'s `struct_construction_plan`,
        `struct_frame_representable`, `struct_frame_defaults`), so which of the
        shapes a call is — and which of them is refused, and why — is not
        expressible differently on the two machines.  What differs is the
        instruction: arm64 emits `LDR`/`STR Xt, [Xn, #8k]` for the same layout
        and this emits `mov` to and from `[RBP + 8k]`."""
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
        base = self._blob_base + site[1]
        if shape == M.CONSTRUCTION_COPY:
            self._emit_frame_copy(e, name, st, base, plan[1])
            return
        if shape == M.CONSTRUCTION_POSITIONAL:
            self._emit_frame_positional(e, name, st, base, site, plan[1])
            return
        ok, bad = M.struct_frame_representable(st)
        if not ok:
            raise CodegenError(
                f"constructing {name} cannot bring its field {bad!r} up at "
                f"its default on this path: the default is not a literal, and "
                f"this constructor has no scope to evaluate it in (assign the "
                f"field explicitly after `S()` instead, which is the same "
                f"program with a representation)")
        # Nested frames FIRST, in the same order arm64 does it and for the same
        # reason: the block is laid out with the object's own slots at the
        # bottom, and the outer base is recomputed per store anyway.  The
        # layout and the list of children both come from the shared model, so
        # the bytes reserved and the defaults stored cannot disagree.
        self._emit_frame_nested(site)
        for slot, (kind, payload) in enumerate(M.struct_frame_defaults(st)):
            if kind == M.DEFAULT_STRING:
                value = F.StringLiteral(value=payload)
            else:
                value = int(payload or 0)
            self._emit_block_store(base, slot, value)
        # …and then the constructor's own stores, for the one shape that has
        # them.  Empty for `S()`, which is why this is the same code as the
        # default constructor's rather than a fourth copy of it.
        for _field, slot, value in (plan[1] if shape == M.CONSTRUCTION_INIT
                                    else ()):
            self._emit_block_store(base, slot, value)
        # Each nested field's slot then gets the ADDRESS of the frame just
        # brought up.  Same order as the loop above, so the address stored and
        # the frame initialized are the same one by construction.
        self._emit_frame_nested_addresses(base, site)
        # The address is the RESULT and every store above left something else
        # in RAX, so it is materialized last.
        self._emit_blob_base(base, Reg.RAX)

    def _emit_frame_nested(self, site) -> None:
        """Bring every PLACED nested frame of this site's struct up.

        Nested frames FIRST, in the same order arm64 does it and for the same
        reason: the block is laid out with the object's own slots at the
        bottom.  `site[2]` is the PLACEMENT (`model.struct_constructor_sites`),
        so a declared type that was not placed cannot reach this loop.
        """
        for _fname, _slot, _child, child_off in site[2]:
            self._emit_nested_frame_init(_child, child_off + self._blob_base)

    def _emit_frame_nested_addresses(self, base: int, site) -> None:
        """Store the ADDRESS of each frame `_emit_frame_nested` just brought up.

        Which is the whole of "the slot holds a nested frame": one store per
        typed-nested field, in the same order as `_emit_frame_nested`, so the
        address stored and the frame initialized are the same one by
        construction rather than by two walks agreeing.
        """
        for _fname, slot, _child, child_off in site[2]:
            self._emit_blob_base(child_off + self._blob_base, Reg.RAX)
            self.asm.emit(encode_mov_rm64_r64(Reg.RBP, base + 8 * slot,
                                              Reg.RAX))

    def _emit_block_store(self, base: int, slot: int, value) -> None:
        """One store into a CONSTRUCTION's fresh block: `value` to `8·slot`.

        The x86-64 twin of arm64's `_emit_frame_store`, and the register
        discipline is the existing one: the value is evaluated into RAX and
        stored straight to `[RBP + 8k]`, with no base register to recompute
        because the destination is RBP-relative and therefore fixed.  That is
        also why evaluating a value between two stores is safe here — a call or
        a string LEA cannot move RBP.

        `value` is either an AST node to evaluate or an `int` to materialize,
        which is what lets the class-level defaults and an inlined
        constructor's stores share one loop: a literal default has nothing to
        evaluate, and a literal inside a constructor body is the same node.
        """
        if isinstance(value, int):
            self._emit_mov_imm(Reg.RAX, value)
        else:
            self._emit_expr(value)
        self.asm.emit(encode_mov_rm64_r64(Reg.RBP, base + 8 * slot, Reg.RAX))

    def _emit_frame_positional(self, e: F.CallExpr, name: str, st, base: int,
                               site, fields) -> None:
        """`S(a, b, …)` — one store per argument, at `base + 8k` in declaration order.

        The x86-64 twin of arm64's, over the same three shared helpers.  What
        is specific here is only that a positional argument covers EVERY field,
        so no slot is brought up at its class-level default first — there would
        be nothing left of the default to keep.
        """
        self._emit_frame_nested(site)
        for arg, (_field, slot) in zip(e.args, fields):
            self._emit_block_store(base, slot, arg)
        self._emit_frame_nested_addresses(base, site)
        # The address is the RESULT and every store above left something else
        # in RAX, so it is materialized last — the same last line the default
        # constructor ends with, and for the same reason.
        self._emit_blob_base(base, Reg.RAX)

    def _emit_frame_copy(self, e: F.CallExpr, name: str, st, base: int,
                         nslots: int) -> None:
        """`S(x)` — a fresh block and an `n`-slot copy of the source's slots.

        The x86-64 twin of arm64's, and the shallowness, the confinement and
        the three closed doors onto a dead blob are all argued there; what
        differs is only that the two bases are R11 (the source, live across the
        loop) and RBP-relative (the destination, never in a register at all),
        so this loop is two instructions per slot with nothing recomputed.
        """
        self._emit_expr(e.args[0])
        self.asm.emit(encode_mov_r64_r64(Reg.R11, Reg.RAX))
        for slot in range(nslots):
            self.asm.emit(encode_mov_r64_rm64(Reg.RAX, Reg.R11, 8 * slot))
            self.asm.emit(encode_mov_rm64_r64(Reg.RBP, base + 8 * slot,
                                              Reg.RAX))
        self._emit_blob_base(base, Reg.RAX)

    def _emit_nested_frame_init(self, st, base: int, depth: int = 0) -> None:
        """Bring a NESTED receiver frame up at its own slot defaults.

        The x86-64 twin of arm64's `_emit_nested_frame_init`, and it recurses
        through the same `model.struct_nested_frame_fields` and stops at the
        same `model.MAX_NESTED_FRAME_DEPTH`, so a cyclic declaration graph
        truncates identically on both machines rather than hanging on one.

        `base` is the ABSOLUTE byte offset from `RBP` (arm64 passes the
        relative offset and adds nothing, because its `_emit_frame_base` adds
        the scratch base itself); the shape of the emitted stores is otherwise
        identical, which is what makes a default one machine can bring up and
        the other cannot not expressible.
        """
        if depth >= M.MAX_NESTED_FRAME_DEPTH:
            return
        for _fname, _slot, child, child_off in \
                M.struct_nested_frame_fields(st, self._structs):
            self._emit_nested_frame_init(child, child_off + self._blob_base,
                                         depth + 1)
        for slot, (kind, payload) in enumerate(M.struct_frame_defaults(st)):
            if kind == M.DEFAULT_STRING:
                self._emit_expr(F.StringLiteral(value=payload))
            else:
                self._emit_mov_imm(Reg.RAX, int(payload or 0))
            self.asm.emit(encode_mov_rm64_r64(Reg.RBP, base + 8 * slot,
                                              Reg.RAX))

    def _emit_fresh_one_word(self, name: str, st) -> None:
        """`S()` for a struct of zero or one field — a value, not a call.

        The x86-64 twin of arm64's, and the shared half is the DECISION
        (formal.model.struct_default_word): the one word a fresh struct holds is
        its sole field brought up at that field's default, which is zero only
        when there is no default to honour. Emitting a hard 0 regardless meant a
        program that read the field without writing it first got a value the
        source never said — and, before this, a struct constructor was not even
        recognised here and became a `call _S` against a symbol nothing
        defines."""
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
        self._emit_mov_imm(Reg.RAX, int(payload or 0))

    def _ttype(self, e) -> IntType:
        return infer_expr(e, self._vtypes, self._call_types)

    def _emit_extend(self, reg: Reg, t) -> None:
        """Materialize the full 64-bit representative of type t in `reg`.

        Values live in 64-bit registers throughout: signed types
        sign-extended, unsigned zero-extended. The narrow unsigned cases mask
        or zero-extend instead; a 32-bit unsigned value is a plain 32-bit MOV,
        which the CPU zero-extends into the full register for free."""
        t = resolve(t)
        if t.width == 64:
            return
        if t.signed:
            if t.width == 32:
                self.asm.emit(encode_movsx_r64_r32(reg, reg))
            elif t.width == 8:
                self.asm.emit(encode_movsx_r64_r8(reg, reg))
            elif t.width == 16:
                self.asm.emit(encode_movsx_r64_r16(reg, reg))
            else:
                raise CodegenError(f"unsupported integer width {t.width}")
        else:
            if t.width == 8:
                # 0xFF does not fit a signed imm8, so this needs the imm32
                # form; with REX.W that sign-extends to 0x00000000_000000FF,
                # which is the mask an 8-bit value wants.
                self.asm.emit(encode_and_r64_imm32(reg, mask_of(t)))
            elif t.width == 16:
                self.asm.emit(encode_movzx_r64_r16(reg, reg))
            elif t.width == 32:
                self.asm.emit(encode_mov_r32_r32(reg, reg))
            else:
                raise CodegenError(f"unsupported integer width {t.width}")

    def _emit_trunc(self, t) -> None:
        self._emit_extend(Reg.RAX, t)

    def _emit_mov_imm(self, reg: Reg, imm: int) -> None:
        """Materialize `imm` in `reg`, choosing the shortest correct form.

        A value that fits in a signed 32-bit field goes through the imm32
        form, which the CPU sign-extends for free; anything wider needs the
        full 10-byte mov-imm64. Negative values are normalized to their
        two's-complement 64-bit pattern first."""
        imm &= 0xFFFFFFFFFFFFFFFF
        signed = imm - (1 << 64) if imm >> 63 else imm
        if -(2 ** 31) <= signed < 2 ** 31:
            self.asm.emit(encode_mov_r64_imm32(reg, signed))
        else:
            self.asm.emit(encode_mov_r64_imm64(reg, imm))

    def _static_int(self, e):
        """A literal integer value for `e`, else None.

        UnaryOp('-', IntLiteral(n)) counts as -n, so `range(a, b, -1)` is
        recognized as a descending range even though the parser keeps the
        minus as a node."""
        if isinstance(e, F.IntLiteral):
            return e.value
        if isinstance(e, F.UnaryOp) and e.op == "-" \
                and isinstance(e.operand, F.IntLiteral):
            return -e.operand.value
        return None


def _align16(value: int) -> int:
    return (value + 15) & ~15


def _range_info(rargs: list) -> tuple:
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
