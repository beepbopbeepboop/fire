"""GIMPLE backend for the Mojo compiler.

Consumes AST produced by mojo_compiler.py and emits C source with
__GIMPLE-annotated functions for gcc-mp-15 -fgimple.
"""
from __future__ import annotations

import os
import re
import sys
import hashlib
import dataclasses

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, BoolLiteral, EllipsisLiteral,
    IdentExpr, BinaryOp, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, Generator,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt,
    GlobalStmt,
    StructDef, TraitDef,
    tokenize, Parser,
)
from module_loader import load_module, get_symbol_type
import mlir
from generated_dispatch import (
    _SIGNED as _GD_SIGNED, _UNSIGNED as _GD_UNSIGNED, _FLOAT as _GD_FLOAT,
    _BIN_OPS as _GD_BIN_OPS, _CMP_OPS as _GD_CMP_OPS,
    _STMT_DISPATCH, _EXPR_DISPATCH,
)

# _slit_ numbering starts here to avoid collisions with the mojo compiler's
# own string-literal numbering when modules are linked together.
STRING_POOL_BASE = 10000


def _debug_note(where: str, detail: object = '') -> None:
    """Report a deliberately-swallowed error on stderr when MOJO_DEBUG is set.

    Codegen degrades gracefully on some failures (module imports, type
    inference, generic instantiation).  Those paths intentionally continue
    with reduced information; this hook makes them diagnosable without
    changing compiler behavior for normal runs.
    """
    if os.environ.get('MOJO_DEBUG'):
        print(f"[gimple_codegen] {where}: {detail}", file=sys.stderr)

# ---------------------------------------------------------------------------
# TypeLattice — C11 usual arithmetic conversions + container helpers
# ---------------------------------------------------------------------------

class TypeLattice:
    """Numeric type promotion lattice for Mojo → C lowering.

    join(t1, t2) implements C11 usual-arithmetic-conversion rules:
      - If either operand is float, float wins; wider float wins.
      - If both are signed ints, wider wins.
      - If both are unsigned ints, wider wins.
      - If mixed signed/unsigned: if unsigned rank >= signed rank → unsigned; else signed.
    """

    _SIGNED   = _GD_SIGNED
    _UNSIGNED = _GD_UNSIGNED
    _FLOAT    = _GD_FLOAT

    @classmethod
    def is_float(cls, t: str) -> bool:    return t in cls._FLOAT
    @classmethod
    def is_signed(cls, t: str) -> bool:   return t in cls._SIGNED
    @classmethod
    def is_unsigned(cls, t: str) -> bool: return t in cls._UNSIGNED
    @classmethod
    def is_int(cls, t: str) -> bool:      return t in cls._SIGNED or t in cls._UNSIGNED
    @classmethod
    def is_numeric(cls, t: str) -> bool:  return cls.is_float(t) or cls.is_int(t)
    @classmethod
    def is_pointer(cls, t: str) -> bool:  return '*' in t
    @classmethod
    def is_bool(cls, t: str) -> bool:     return t == '_Bool'

    @classmethod
    def join(cls, t1: str, t2: str) -> str:
        """LUB for binary arithmetic result type."""
        if t1 == t2:
            return t1
        # _Bool promotes to int before further analysis
        if t1 == '_Bool': t1 = 'int'
        if t2 == '_Bool': t2 = 'int'
        if t1 == t2:
            return t1
        # Pointer: when two different pointer types meet, use int64_t (opaque handle)
        if cls.is_pointer(t1) or cls.is_pointer(t2):
            if cls.is_pointer(t1) and cls.is_pointer(t2):
                # Two different pointer types → opaque int64_t handle
                if t1 == 'void *' or t2 == 'void *':
                    return 'void *'
                if t1 == 'char *' or t2 == 'char *':
                    return 'char *'
                return 'int64_t'
            # One pointer, one non-pointer → use the pointer type
            return t1 if cls.is_pointer(t1) else t2
        # Float wins over int; wider float wins
        if cls.is_float(t1) or cls.is_float(t2):
            r1 = cls._FLOAT.get(t1, 0)
            r2 = cls._FLOAT.get(t2, 0)
            if r1 == 0: return t2   # t2 is the float
            if r2 == 0: return t1   # t1 is the float
            return t1 if r1 >= r2 else t2
        # Both integral
        rs1 = cls._SIGNED.get(t1, 0)
        rs2 = cls._SIGNED.get(t2, 0)
        ru1 = cls._UNSIGNED.get(t1, 0)
        ru2 = cls._UNSIGNED.get(t2, 0)
        if rs1 and rs2:  return t1 if rs1 >= rs2 else t2   # both signed
        if ru1 and ru2:  return t1 if ru1 >= ru2 else t2   # both unsigned
        if rs1 and ru2:  return t2 if ru2 >= rs1 else t1   # t1 signed, t2 unsigned
        if ru1 and rs2:  return t1 if ru1 >= rs2 else t2   # t1 unsigned, t2 signed
        return 'int64_t'

    @classmethod
    def join_all(cls, types: list) -> str:
        """LUB of a list of types (e.g. for return type inference)."""
        if not types:
            return 'void'
        result = types[0]
        for t in types[1:]:
            if result == 'void':
                result = t
            elif t != 'void':
                result = cls.join(result, t)
        return result

    @classmethod
    def coerce(cls, src: str, dst: str, val: str) -> str:
        """Return `val` cast to `dst` if types differ.
        NOTE: GIMPLE only allows single-level casts on simple variables.
        This method must be called only when val is guaranteed to be a simple
        variable name, not a function call or compound expression.
        """
        if src == dst:
            return val
        # No-op casts between compatible int types
        if src in ('int', 'int64_t', '_Bool') and dst in ('int', 'int64_t', '_Bool'):
            if src == dst:
                return val
            return f"({dst}){val}"
        # _Bool → int: single cast is fine
        if src == '_Bool':
            if dst == 'int':
                return f"(int){val}"
            return f"({dst}){val}"
        # int → _Bool
        if dst == '_Bool':
            return f"(_Bool){val}"
        # pointer ↔ int64_t: go through void * for non-void pointers (GIMPLE requirement)
        if src.endswith(' *') and dst == 'int64_t':
            if src == 'void *':
                return f"(int64_t){val}"
            # Non-void pointer requires type tracking on unboxing (caller's responsibility)
            return f"(int64_t)(void *){val}"
        if src == 'int64_t' and dst.endswith(' *'):
            # CRITICAL: Unboxing int64_t to specific pointer type requires type validation
            # Safe only for: void * (generic handle)
            # UNSAFE: casting to specific types (char*, MojoDict*, etc) without verifying actual type
            if dst == 'void *':
                # void * is safe - it's a generic opaque handle
                return f"(void *){val}"
            # Casting int64_t to specific pointer type without validation is a silent type-safety bug
            raise TypeError(
                f"UNSAFE CAST: int64_t → {dst} requires type validation in _actual_types. "
                f"Call must verify via _actual_types[{val}] before casting. "
                f"Use (void *){val} as intermediate if truly generic."
            )
        return f"({dst}){val}"

    @classmethod
    def list_suffix(cls, elem: str) -> str:
        """Select 'int'/'double'/'str' API suffix based on element C type."""
        if elem in cls._FLOAT: return 'double'
        if elem == 'char *':   return 'str'
        return 'int'

    @classmethod
    def printf_fmt(cls, ctype: str) -> str:
        if ctype in ('double', 'float', '__fp16'): return '%g'
        if ctype == 'char *': return '%s'
        if ctype == 'char':   return '%c'
        if ctype == 'int64_t': return '%ld'
        if ctype == 'uint64_t': return '%lu'
        if ctype in ('unsigned int', 'uint32_t', 'uint16_t', 'uint8_t'): return '%u'
        return '%d'


# ---------------------------------------------------------------------------
# EscapeAnalyzer — conservative escape analysis for struct locals
# ---------------------------------------------------------------------------

# Standalone functions for escape analysis (to avoid object method transpilation issues)
def _find_idents(node) -> set:
    """Recursively find all identifiers in an AST node."""
    if isinstance(node, IdentExpr):           return {node.name}
    if isinstance(node, BinaryOp):            return _find_idents(node.left) | _find_idents(node.right)
    if isinstance(node, UnaryOp):             return _find_idents(node.operand)
    if isinstance(node, CallExpr):
        r = set()
        for a in node.args: r |= _find_idents(a)
        return r
    if isinstance(node, MemberExpr):          return _find_idents(node.obj)
    if isinstance(node, SubscriptExpr):       return _find_idents(node.obj) | _find_idents(node.index)
    if isinstance(node, TernaryExpr):
        return (_find_idents(node.condition) | _find_idents(node.then_val) | _find_idents(node.else_val))
    return set()

def _scan_for_escaping(stmts: list, escaped: set, in_scope: set):
    """Scan AST statements and collect variables that escape."""
    for node in stmts:
        if isinstance(node, ReturnStmt) and node.value is not None:
            escaped.update(_find_idents(node.value) & in_scope)
        elif isinstance(node, VarDecl):
            in_scope.add(node.name)
            if node.value is not None:
                escaped.update(_find_idents(node.value) & in_scope)
        elif isinstance(node, AssignStmt):
            escaped.update(_find_idents(node.value) & in_scope)
        elif isinstance(node, ExprStmt) and isinstance(node.value, CallExpr):
            for arg in node.value.args:
                escaped.update(_find_idents(arg) & in_scope)
        elif isinstance(node, IfStmt):
            _scan_for_escaping(node.then_body, escaped, in_scope)
            for _, eb in node.elifs:
                _scan_for_escaping(eb, escaped, in_scope)
            if node.else_body:
                _scan_for_escaping(node.else_body, escaped, in_scope)
        elif isinstance(node, WhileStmt):
            _scan_for_escaping(node.body, escaped, in_scope)
        elif isinstance(node, ForStmt):
            _scan_for_escaping(node.body, escaped, in_scope)
        elif isinstance(node, TryStmt):
            _scan_for_escaping(node.body, escaped, in_scope)
            for h in node.handlers:
                _scan_for_escaping(h.body, escaped, in_scope)
            if node.else_body:
                _scan_for_escaping(node.else_body, escaped, in_scope)
            if node.finally_body:
                _scan_for_escaping(node.finally_body, escaped, in_scope)
        elif isinstance(node, WithStmt):
            _scan_for_escaping(node.body, escaped, in_scope)

def _find_escaping(params: list, body: list, struct_types: set) -> set:
    """Return the set of local variable names that escape `body`."""
    escaped: set[str] = set()
    in_scope: set[str] = {p[0] for p in params}
    _scan_for_escaping(body, escaped, in_scope)
    return escaped

class EscapeAnalyzer:
    """Conservative escape analysis for local variables in a function body.

    A variable *escapes* if:
      - It appears in a ReturnStmt.
      - It is passed as an argument to a callee (conservative: any call).
      - It is stored into a heap-allocated container (MojoList, MojoDict, MojoSet).
    Non-escaping struct locals can be stack-allocated.
    """

    def __init__(self, struct_types: set):
        self._struct_types = struct_types

    def find_escaping(self, params: list, body: list) -> set:
        """Return the set of local variable names that escape `body`."""
        escaped: set[str] = set()
        in_scope: set[str] = {p[0] for p in params}
        self._scan(body, escaped, in_scope)
        return escaped

    def _scan(self, stmts: list, escaped: set, in_scope: set):
        for node in stmts:
            if isinstance(node, ReturnStmt) and node.value is not None:
                escaped.update(self._idents(node.value) & in_scope)
            elif isinstance(node, VarDecl):
                in_scope.add(node.name)
                if node.value is not None:
                    escaped.update(self._idents(node.value) & in_scope)
            elif isinstance(node, AssignStmt):
                escaped.update(self._idents(node.value) & in_scope)
            elif isinstance(node, ExprStmt) and isinstance(node.value, CallExpr):
                for arg in node.value.args:
                    escaped.update(self._idents(arg) & in_scope)
            elif isinstance(node, IfStmt):
                self._scan(node.then_body, escaped, in_scope)
                for _, eb in node.elifs:
                    self._scan(eb, escaped, in_scope)
                if node.else_body:
                    self._scan(node.else_body, escaped, in_scope)
            elif isinstance(node, WhileStmt):
                self._scan(node.body, escaped, in_scope)
            elif isinstance(node, ForStmt):
                self._scan(node.body, escaped, in_scope)
            elif isinstance(node, TryStmt):
                self._scan(node.body, escaped, in_scope)
                for h in node.handlers:
                    self._scan(h.body, escaped, in_scope)
                if node.else_body:
                    self._scan(node.else_body, escaped, in_scope)
                if node.finally_body:
                    self._scan(node.finally_body, escaped, in_scope)
            elif isinstance(node, WithStmt):
                self._scan(node.body, escaped, in_scope)

    def _idents(self, node) -> set:
        if isinstance(node, IdentExpr):           return {node.name}
        if isinstance(node, BinaryOp):            return self._idents(node.left) | self._idents(node.right)
        if isinstance(node, UnaryOp):             return self._idents(node.operand)
        if isinstance(node, CallExpr):
            r = set()
            for a in node.args: r |= self._idents(a)
            return r
        if isinstance(node, MemberExpr):          return self._idents(node.obj)
        if isinstance(node, SubscriptExpr):       return self._idents(node.obj) | self._idents(node.index)
        if isinstance(node, TernaryExpr):
            return (self._idents(node.condition) |
                    self._idents(node.then_val)  |
                    self._idents(node.else_val))
        return set()


# ---------------------------------------------------------------------------
# LayoutSolver — stack vs heap decision for struct locals
# ---------------------------------------------------------------------------

class LayoutSolver:
    """
    Decide allocation strategy for struct-typed local variables.

    STACK — allocated with __builtin_alloca; valid when variable does not
            escape and the function contains no try/except (setjmp would
            unwind the stack frame).
    HEAP  — allocated with malloc; required when variable escapes or a
            setjmp is in scope.

    The solver is run as a pre-pass before codegen for each function so
    that allocation decisions are available when lowering VarDecl nodes.
    """

    STACK = 'stack'
    HEAP  = 'heap'

    def __init__(self, struct_field_types: dict):
        self._struct_types = set(struct_field_types.keys())
        self._ea = EscapeAnalyzer(self._struct_types)

    def solve(self, params: list, body: list) -> dict:
        """Return {var_name: STACK|HEAP} for struct-typed locals in *body*."""
        has_try = self._has_try(body)
        # Use standalone function to avoid object method transpilation issues
        escaped = _find_escaping(params, body, self._struct_types)
        locals_  = self._struct_locals(body)
        result = {}
        for name in locals_:
            if has_try or name in escaped:
                result[name] = self.HEAP
            else:
                result[name] = self.STACK
        return result

    def _struct_locals(self, stmts: list) -> set:
        result: set[str] = set()
        for node in stmts:
            if isinstance(node, VarDecl) and node.type_ann in self._struct_types:
                result.add(node.name)
            elif isinstance(node, IfStmt):
                result |= self._struct_locals(node.then_body)
                for _, eb in node.elifs:
                    result |= self._struct_locals(eb)
                if node.else_body:
                    result |= self._struct_locals(node.else_body)
            elif isinstance(node, (WhileStmt, ForStmt)):
                result |= self._struct_locals(node.body)
            elif isinstance(node, TryStmt):
                result |= self._struct_locals(node.body)
                for h in node.handlers:
                    result |= self._struct_locals(h.body)
                if node.else_body:
                    result |= self._struct_locals(node.else_body)
                if node.finally_body:
                    result |= self._struct_locals(node.finally_body)
            elif isinstance(node, WithStmt):
                result |= self._struct_locals(node.body)
        return result

    def _has_try(self, stmts: list) -> bool:
        for node in stmts:
            if isinstance(node, TryStmt):
                return True
            if isinstance(node, IfStmt):
                if (self._has_try(node.then_body) or
                        any(self._has_try(eb) for _, eb in node.elifs) or
                        (node.else_body and self._has_try(node.else_body))):
                    return True
            if isinstance(node, (WhileStmt, ForStmt)) and self._has_try(node.body):
                return True
        return False


# ---------------------------------------------------------------------------
# DispatchSolver — whole-program dispatch analysis for closure patterns
# ---------------------------------------------------------------------------

class DispatchTable:
    """Plan for a virtual method table or dispatch array.

    Stores the planned structure of a dispatch table (vtable), with methods
    to emit C code for the typedef, initialization, and dispatch calls.

    Examples:
        - Interpreter's execute dispatch: maps execute_* methods
        - Generic container dispatch: maps operation names to implementations
    """

    def __init__(self, name: str, pattern_id: str, dispatch_type: str):
        self.name = name                      # "interpreter_execute_dispatch"
        self.pattern_id = pattern_id          # Original pattern identifier
        self.dispatch_type = dispatch_type    # "FUNC_POINTER", "ARRAY_INDEX", "TYPE_SWITCH"
        self.methods: list = []               # [(method_name, c_signature, full_c_name)]
        self.struct_fields: dict = {}         # field_name → c_type (for FUNC_POINTER)
        self.dispatch_index_map: dict = {}    # method_name → index (for ARRAY_INDEX)

    def add_method(self, method_name: str, c_signature: str, full_c_name: str):
        """Add a method to this dispatch table.

        Args:
            method_name: Short name (e.g., 'execute_Module')
            c_signature: Function pointer signature (e.g., 'int (*name)(void *self, void *node)')
            full_c_name: Full C function name (e.g., 'Interpreter_execute_Module')
        """
        self.methods.append((method_name, c_signature, full_c_name))
        # For FUNC_POINTER style, each method becomes a struct field
        if self.dispatch_type == 'FUNC_POINTER':
            self.struct_fields[method_name] = c_signature

    def emit_typedef(self) -> str:
        """Emit C typedef for this dispatch table struct.

        For FUNC_POINTER dispatch:
            typedef struct {
                int (*execute_Module)(void *self, void *node);
                int (*execute_FunctionDef)(void *self, void *node);
                ...
            } interpreter_execute_dispatch_t;
        """
        if self.dispatch_type == 'FUNC_POINTER':
            lines = [f"typedef struct {{"]
            for method_name, c_signature in self.struct_fields.items():
                # c_signature is like: "int (*execute_Module)(void *self, void *node)"
                # Already has the field name, just add as-is
                lines.append(f"  {c_signature};")
            lines.append(f"}} {self.name}_t;")
            return '\n'.join(lines)

        elif self.dispatch_type == 'ARRAY_INDEX':
            # Array of function pointers
            # Need to extract common signature from methods
            if self.methods:
                _, sig, _ = self.methods[0]
                # Extract return type and params from first method
                # This is simplified; Phase C can improve
                lines = [f"typedef int (*{self.name}_fn)(void *, void *);"]
                return '\n'.join(lines)

        return f"/* TODO: {self.dispatch_type} dispatch typedef */"

    def emit_table_init(self) -> str:
        """Emit C initialization for this dispatch table.

        For FUNC_POINTER dispatch:
            static const interpreter_execute_dispatch_t execute_dispatch = {
                .execute_Module = Interpreter_execute_Module,
                .execute_FunctionDef = Interpreter_execute_FunctionDef,
                ...
            };
        """
        if self.dispatch_type == 'FUNC_POINTER':
            lines = [f"static const {self.name}_t {self.name} = {{"]
            for method_name, _, full_c_name in self.methods:
                c_sig = self.struct_fields.get(method_name, '')
                if c_sig:
                    # Cast function pointer to match the declared struct field type.
                    # This suppresses -Wincompatible-pointer-types when the actual function
                    # has a more specific signature than the generic dispatch table field.
                    fp_type = c_sig.replace(f"(*{method_name})", "(*)")
                    lines.append(f"  .{method_name} = ({fp_type}){full_c_name},")
                else:
                    lines.append(f"  .{method_name} = {full_c_name},")
            lines.append(f"}};")
            return '\n'.join(lines)

        elif self.dispatch_type == 'ARRAY_INDEX':
            lines = [f"static const {self.name}_fn {self.name}[] = {{"]
            for _, _, full_c_name in self.methods:
                lines.append(f"  {full_c_name},")
            lines.append(f"}};")
            return '\n'.join(lines)

        return f"/* TODO: {self.dispatch_type} dispatch init */"

    def emit_dispatch_call(self, obj: str, method_idx: int | str, args: str) -> str:
        """Emit C code to dispatch through this table.

        Args:
            obj: Object holding the dispatch table (e.g., 'self->dispatch' or 'execute_dispatch')
            method_idx: Either int index (0, 1, 2) or method name
            args: Arguments to pass to dispatched function

        Returns:
            C code for the dispatch call

        Examples:
            FUNC_POINTER: execute_dispatch.execute_Module(self, node)
            ARRAY_INDEX: execute_dispatch[0](self, node)
        """
        if self.dispatch_type == 'FUNC_POINTER':
            if isinstance(method_idx, int) and 0 <= method_idx < len(self.methods):
                method_name, _, _ = self.methods[method_idx]
                return f"{obj}.{method_name}({args})"
            elif isinstance(method_idx, str):
                # Direct method name
                return f"{obj}.{method_idx}({args})"

        elif self.dispatch_type == 'ARRAY_INDEX':
            if isinstance(method_idx, int):
                return f"{obj}[{method_idx}]({args})"
            else:
                # Need to map method name to index
                for i, (method_name, _, _) in enumerate(self.methods):
                    if method_name == method_idx:
                        return f"{obj}[{i}]({args})"

        return f"/* TODO: dispatch call */"

    def get_method_index(self, method_name: str) -> int | None:
        """Get the index of a method in this dispatch table."""
        for i, (name, _, _) in enumerate(self.methods):
            if name == method_name:
                return i
        return None

    def get_method_count(self) -> int:
        """Get the number of methods in this dispatch table."""
        return len(self.methods)

    def get_c_function_pointer_type(self) -> str:
        """Get the C function pointer type for this dispatch table."""
        if self.methods:
            _, sig, _ = self.methods[0]
            # Extract the function pointer type from the first signature
            # "int (*name)(void *self, void *node)" → "int (*)(void *self, void *node)"
            # For now, return a generic type
            return "void (*)(void *, void *)"
        return "void (*)(void)"


class DispatchPattern:
    """Describes a dynamic dispatch pattern found in the code.

    Examples:
        - getattr(self, f'execute_{type}', None) — method lookup on interpreter
        - _STMT_DISPATCH[node_type] — dict-based dispatch
        - node.method() — direct method reference
    """
    def __init__(self, pattern_id: str, pattern_type: str, location: tuple):
        self.pattern_id = pattern_id      # Unique identifier for this pattern
        self.pattern_type = pattern_type  # 'getattr', 'subscript', 'member'
        self.location = location          # (function_name, line_num) for debugging
        self.possible_callees: set = set()  # Which functions could be called here
        self.call_sites: list = []        # AST nodes that use this pattern

    def add_call_site(self, node):
        """Record an AST node that uses this dispatch pattern."""
        self.call_sites.append(node)

    def add_callee(self, func_name: str):
        """Record a function that could be called via this pattern."""
        self.possible_callees.add(func_name)


class DispatchSolver:
    """Whole-program dispatch analysis for dynamic patterns in closure.

    Analyzes entire transitive closure (all modules) to:
    1. Build static call graph (direct calls)
    2. Identify dynamic dispatch patterns (getattr, dict subscripts, etc.)
    3. Plan dispatch tables for those patterns

    Input: Complete AST of all modules (from do_imports=True)
    Output: Planned dispatch tables and call graph analysis
    """

    def __init__(self, struct_field_types: dict, func_return_types: dict):
        self.struct_field_types = struct_field_types
        self.func_return_types = func_return_types

        # Call graph: caller_name → Set[callee_name]
        # Only includes direct, static calls (not through getattr/dict)
        self.call_graph: dict[str, set] = {}

        # Dispatch patterns found: pattern_id → DispatchPattern
        self.dispatch_patterns: dict[str, DispatchPattern] = {}

        # Reverse call graph: callee_name → Set[caller_name]
        # Useful for determining monomorphism
        self.callers_of: dict[str, set] = {}

        # Method lookup: struct_name → {method_name → full_function_name}
        # E.g., "Interpreter" → {"execute_Module" → "Interpreter_execute_Module"}
        self.struct_methods: dict[str, dict] = {}

        # Counter for unique pattern IDs
        self._pattern_counter = 0

    def analyze(self, all_stmts: list):
        """Run complete dispatch analysis on entire closure.

        Includes three core dispatch analyses plus new complementary analyses:
        - Call graph and dispatch pattern detection (existing)
        - Function compilability analysis (def→fn promotions)
        - Type promotion across closure (cross-closure type inference)
        """
        # Collect function parameter types early for use in dispatch table generation
        self.func_param_types: dict = {}  # func_name → [(param_name, param_type)]
        self._collect_function_param_types(all_stmts)

        # Pass 1: Build call graph and struct method mapping
        self._build_call_graph(all_stmts)

        # Pass 2: Find all dynamic dispatch patterns
        self._find_dispatch_patterns(all_stmts)

        # Pass 3: Plan dispatch tables for each pattern
        self._plan_dispatch_tables()

        # ── NEW: Pass 4: Determine which functions are C-compilable ────────
        self.compilability = FunctionCompilability(self.func_return_types, self.struct_field_types)
        self.compilability.analyze(all_stmts)

        # ── NEW: Pass 5: Promote types across closure ─────────────────────
        self.type_promoter = TypePromotionSolver(self.call_graph, self.func_return_types)
        self.type_promoter.analyze(all_stmts, {})  # all_funcs would be built from all_stmts

    def _collect_function_param_types(self, stmts: list):
        """Collect parameter type information for all functions."""
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                self.func_param_types[stmt.name] = stmt.params
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    method_full_name = f"{stmt.name}_{method.name}"
                    self.func_param_types[method_full_name] = method.params

    def _build_call_graph(self, stmts: list):
        """Traverse all functions and structs, record direct calls.

        Direct calls = those where the callee is statically known.
        Dynamic calls (getattr, dict lookup) are skipped here and handled separately.
        """
        # First pass: collect all function/method names
        all_functions = set()

        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                all_functions.add(stmt.name)
            elif isinstance(stmt, StructDef):
                # Record struct methods
                if stmt.name not in self.struct_methods:
                    self.struct_methods[stmt.name] = {}
                for method in stmt.methods:
                    method_name = f"{stmt.name}_{method.name}"
                    all_functions.add(method_name)
                    self.struct_methods[stmt.name][method.name] = method_name

        # Second pass: analyze call graph in all functions and methods
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                self._scan_for_calls(stmt.name, stmt.body, all_functions)
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    method_full_name = f"{stmt.name}_{method.name}"
                    self._scan_for_calls(method_full_name, method.body, all_functions)

    def _scan_for_calls(self, func_name: str, body: list, all_functions: set):
        """Scan function body for direct calls, build call graph."""
        if func_name not in self.call_graph:
            self.call_graph[func_name] = set()

        for node in self._walk_stmts(body):
            if isinstance(node, CallExpr):
                # Check if this is a direct call
                callee = self._extract_callee_name(node.func)
                if callee and callee in all_functions:
                    self.call_graph[func_name].add(callee)
                    # Update reverse graph
                    if callee not in self.callers_of:
                        self.callers_of[callee] = set()
                    self.callers_of[callee].add(func_name)

    def _walk_stmts(self, stmts: list):
        """Generator: yield all expression nodes in statement list."""
        for stmt in stmts:
            if isinstance(stmt, ExprStmt):
                yield from self._walk_expr(stmt.value)
            elif isinstance(stmt, ReturnStmt) and stmt.value:
                yield from self._walk_expr(stmt.value)
            elif isinstance(stmt, AssignStmt):
                yield from self._walk_expr(stmt.value)
            elif isinstance(stmt, IfStmt):
                yield from self._walk_expr(stmt.condition)
                yield from self._walk_stmts(stmt.then_body)
                for _, elif_body in stmt.elifs:
                    yield from self._walk_stmts(elif_body)
                if stmt.else_body:
                    yield from self._walk_stmts(stmt.else_body)
            elif isinstance(stmt, (WhileStmt, ForStmt)):
                if isinstance(stmt, WhileStmt):
                    yield from self._walk_expr(stmt.condition)
                elif isinstance(stmt, ForStmt):
                    yield from self._walk_expr(stmt.iterable)
                yield from self._walk_stmts(stmt.body)
            elif isinstance(stmt, TryStmt):
                yield from self._walk_stmts(stmt.body)
                for h in stmt.handlers:
                    yield from self._walk_stmts(h.body)
                if stmt.else_body:
                    yield from self._walk_stmts(stmt.else_body)
                if stmt.finally_body:
                    yield from self._walk_stmts(stmt.finally_body)
            elif isinstance(stmt, WithStmt):
                yield from self._walk_stmts(stmt.body)

    def _walk_expr(self, expr):
        """Generator: yield expr and all sub-expressions."""
        if expr is None:
            return
        yield expr
        if isinstance(expr, BinaryOp):
            yield from self._walk_expr(expr.left)
            yield from self._walk_expr(expr.right)
        elif isinstance(expr, UnaryOp):
            yield from self._walk_expr(expr.operand)
        elif isinstance(expr, CallExpr):
            yield from self._walk_expr(expr.func)
            for arg in expr.args:
                yield from self._walk_expr(arg)
        elif isinstance(expr, MemberExpr):
            yield from self._walk_expr(expr.obj)
        elif isinstance(expr, SubscriptExpr):
            yield from self._walk_expr(expr.obj)
            yield from self._walk_expr(expr.index)
        elif isinstance(expr, SliceExpr):
            yield from self._walk_expr(expr.obj)
            if expr.start:
                yield from self._walk_expr(expr.start)
            if expr.stop:
                yield from self._walk_expr(expr.stop)
        elif isinstance(expr, TernaryExpr):
            yield from self._walk_expr(expr.condition)
            yield from self._walk_expr(expr.then_val)
            yield from self._walk_expr(expr.else_val)
        elif isinstance(expr, (ListExpr, SetExpr, TupleExpr)):
            for e in expr.elements:
                yield from self._walk_expr(e)
        elif isinstance(expr, DictExpr):
            for k, v in expr.pairs:
                yield from self._walk_expr(k)
                yield from self._walk_expr(v)

    def _extract_callee_name(self, func_expr) -> str | None:
        """Extract function name if func_expr is a simple identifier or method.

        Returns:
            - Simple name: "foo" → "foo"
            - Method: obj.method() → None (not direct call, would be getattr pattern)
            - Subscript: dispatch[x]() → None (dynamic dispatch)
            - Complex: any nesting → None
        """
        if isinstance(func_expr, IdentExpr):
            return func_expr.name
        # Don't extract from getattr, subscripts, or member access — those are dynamic
        return None

    def _find_dispatch_patterns(self, stmts: list):
        """Identify all dynamic dispatch patterns in the code.

        Patterns to detect:
        1. getattr(obj, name_expr, default) — method lookup
        2. dict[key] where dict is a dispatch table — subscript dispatch
        3. obj.method(args) where obj is 'self' and method has dynamic selector
        """
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                self._find_patterns_in_body(stmt.name, stmt.body, None)
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    method_full_name = f"{stmt.name}_{method.name}"
                    self._find_patterns_in_body(method_full_name, method.body, stmt.name)

    def _find_patterns_in_body(self, func_name: str, body: list, struct_name: str | None):
        """Find dispatch patterns in a function/method body."""
        for node in self._walk_stmts(body):
            if isinstance(node, CallExpr):
                # Pattern 1: getattr(obj, name, default)
                if (isinstance(node.func, IdentExpr) and
                    node.func.name == 'getattr' and
                    len(node.args) >= 2):
                    self._analyze_getattr_pattern(func_name, node, struct_name)

                # Pattern 2: subscript dispatch — obj[key]()
                if isinstance(node.func, SubscriptExpr):
                    self._analyze_subscript_dispatch(func_name, node.func)

    def _analyze_getattr_pattern(self, func_name: str, call_node: CallExpr, struct_name: str | None):
        """Analyze getattr(obj, name_expr, default) pattern.

        Tries to determine:
        - Which object is being inspected (obj)
        - What methods might be retrieved (from name_expr pattern)
        """
        if len(call_node.args) < 2:
            return

        obj_expr = call_node.args[0]
        name_expr = call_node.args[1]

        # Identify the object
        obj_name = None
        if isinstance(obj_expr, IdentExpr):
            obj_name = obj_expr.name

        # Pattern: f'execute_{type(node).__name__}' → getattr for execute_* methods
        # Or: f'{prefix}_{something}' → look for matching method names
        if obj_name == 'self' and struct_name:
            # This is a method lookup on current struct
            pattern_key = f"{struct_name}_{func_name.split('_')[-1]}:getattr_self:{id(call_node)}"
            pattern = DispatchPattern(pattern_key, 'getattr', (func_name, 0))
            pattern.add_call_site(call_node)

            # Try to infer which methods could be called
            if isinstance(name_expr, BinaryOp) and name_expr.op == '+':
                # Pattern like f'{prefix}_{something}'
                # Find all methods matching this pattern
                self._infer_getattr_targets(pattern, name_expr, struct_name)
            else:
                # If we can't analyze the pattern, assume all methods might be called
                # This is conservative but correct
                if struct_name in self.struct_methods:
                    for method_name, full_name in self.struct_methods[struct_name].items():
                        # Skip __init__ and the method doing the dispatch itself
                        if method_name not in ('__init__', 'execute'):
                            pattern.add_callee(full_name)

            self.dispatch_patterns[pattern_key] = pattern

    def _infer_getattr_targets(self, pattern: DispatchPattern, name_expr, struct_name: str):
        """Try to infer which methods could be retrieved by this getattr.

        For patterns like f'execute_{type_name}', find all methods starting with 'execute_'.
        """
        # Try to extract a prefix from the name expression
        prefix = None

        if isinstance(name_expr, BinaryOp) and name_expr.op == '+':
            if isinstance(name_expr.left, StringLiteral):
                prefix = name_expr.left.value.rstrip('_')

        # If we found a prefix, look for methods on this struct matching it
        if prefix and struct_name in self.struct_methods:
            for method_name, full_name in self.struct_methods[struct_name].items():
                if method_name.startswith(prefix + '_') or method_name == prefix:
                    if method_name not in ('__init__', 'execute'):
                        pattern.add_callee(full_name)

    def _analyze_subscript_dispatch(self, func_name: str, subscript_expr: SubscriptExpr):
        """Analyze dict[key] dispatch pattern.

        Pattern: _STMT_DISPATCH[node_type] or similar dict-based dispatch.
        """
        if not isinstance(subscript_expr.obj, IdentExpr):
            return

        dict_name = subscript_expr.obj.name

        # Recognize known dispatch table names
        dispatch_tables = {
            '_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS', '_CMP_OPS',
            'stmt_dispatch', 'expr_dispatch', 'bin_ops', 'cmp_ops'
        }

        if dict_name not in dispatch_tables:
            return

        pattern_key = f"{func_name}:subscript:{dict_name}:{id(subscript_expr)}"
        pattern = DispatchPattern(pattern_key, 'subscript', (func_name, 0))
        pattern.add_call_site(subscript_expr)

        # For now, mark as a potential pattern; later phases will populate callees
        self.dispatch_patterns[pattern_key] = pattern

    def _plan_dispatch_tables(self):
        """For each dispatch pattern, plan the vtable structure.

        This phase:
        1. Groups patterns by their callees to identify unique dispatch tables
        2. Creates DispatchTable for each pattern with full vtable planning
        3. Infers parameter types from function return types
        """
        # Track planned tables to avoid duplicates
        # Key: frozenset of callee names (normalized set of targets)
        # Value: DispatchTable
        tables_by_callees: dict = {}

        for pattern_id, pattern in self.dispatch_patterns.items():
            if not pattern.possible_callees:
                continue

            # Normalize: use sorted frozenset as key for deduplication
            callee_key = frozenset(pattern.possible_callees)

            # If we haven't planned a table for this set of callees yet, create one
            if callee_key not in tables_by_callees:
                # Create table name from pattern
                table_name = self._generate_table_name(pattern_id, pattern)

                # Plan the dispatch table
                table = DispatchTable(
                    name=table_name,
                    pattern_id=pattern_id,
                    dispatch_type='FUNC_POINTER'  # Primary mode for Phase B
                )

                # Add methods to the table
                for callee in sorted(pattern.possible_callees):
                    # Extract method name from full name
                    # E.g., "Interpreter_execute_Module" → "execute_Module"
                    method_name = self._extract_method_name(callee)

                    # Infer C signature from function return type and parameter types
                    return_type = self.func_return_types.get(callee, 'int64_t')

                    # Get parameter types for this function
                    params = self.func_param_types.get(callee, [])

                    # Convert parameter types to C
                    # Skip 'self' for methods (first param)
                    c_params = []
                    for pname, ptype in params:
                        if pname == 'self':
                            # For struct methods, infer the struct type
                            # Try to extract from callee name (e.g., "Interpreter_execute_Module" → "Interpreter")
                            struct_name = callee.split('_')[0] if '_' in callee else 'void'
                            c_params.append(f"{struct_name} *self")
                        elif ptype:
                            # Map Python types to C types, use fallback for unresolved
                            c_type = self._map_to_c_type(ptype)
                            c_params.append(f"{c_type} {pname}")
                        else:
                            # No type annotation, default to int
                            c_params.append(f"int {pname}")

                    # Join parameters
                    param_str = ', '.join(c_params) if c_params else "void"
                    c_signature = f"{return_type} (*{method_name})({param_str})"

                    table.add_method(method_name, c_signature, callee)

                tables_by_callees[callee_key] = table

        # Store the planned dispatch tables
        self.dispatch_tables = tables_by_callees

    def _map_to_c_type(self, ptype: str) -> str:
        """Map Python type annotation to C type.

        Handles both built-in types and AST node types (e.g., N.BinaryOp → int).
        """
        if not ptype:
            return "int"

        # Check if it's a struct type (takes priority)
        if ptype in self.struct_field_types:
            return f"{ptype} *"

        # Strip module prefix (e.g., "N.BinaryOp" → use int for AST nodes)
        if '.' in ptype:
            # Module-qualified type like N.BinaryOp, ast.Module, etc.
            # For AST nodes, use int (node ID/index)
            if any(ast_type in ptype for ast_type in ['Module', 'BinaryOp', 'UnaryOp', 'AssignStmt',
                   'IfStmt', 'WhileStmt', 'ForStmt', 'ReturnStmt', 'FunctionDef', 'StructDef',
                   'BreakStmt', 'ContinueStmt', 'PassStmt', 'ImportStmt', 'FromImportStmt',
                   'ExprStmt', 'TryStmt', 'WithStmt', 'BoolLiteral', 'IntLiteral', 'FloatLiteral',
                   'StringLiteral', 'NoneLiteral', 'ListLiteral', 'DictLiteral', 'SetLiteral',
                   'TupleLiteral', 'IdentExpr', 'MemberExpr', 'SubscriptExpr', 'SliceExpr',
                   'CallExpr', 'BinaryOp', 'UnaryOp', 'TernaryExpr']):
                return "int"  # AST node represented as int (ID or index)
            return "void *"  # Unknown module type, use generic pointer

        # Handle union types like "str | None", "int | None"
        if '|' in ptype:
            parts = [p.strip() for p in ptype.split('|')]
            non_none = [p for p in parts if p not in ('None', 'NoneType')]
            if non_none:
                return self._map_to_c_type(non_none[0])
            return 'void *'

        # Map common Python types to C
        type_map = {
            'int': 'int',
            'Int': 'int64_t',
            'float': 'double',
            'Float': 'double',
            'Float64': 'double',
            'bool': 'int',
            'Bool': '_Bool',
            'str': 'char *',
            'String': 'char *',
            'object': 'void *',
            'Any': 'void *',
            'list': 'MojoList *',
            'List': 'MojoList *',
            'MojoList': 'MojoList *',
            'dict': 'MojoDict *',
            'Dict': 'MojoDict *',
            'MojoDict': 'MojoDict *',
            'set': 'MojoSet *',
            'Set': 'MojoSet *',
            'MojoSet': 'MojoSet *',
        }

        return type_map.get(ptype, 'void *')  # Default to void * for unrecognized types

    def _generate_table_name(self, pattern_id: str, pattern: DispatchPattern) -> str:
        """Generate a C-safe name for a dispatch table."""
        # Pattern: "Interpreter_execute:getattr_self:12345"
        # Result: "interpreter_execute_dispatch"
        parts = pattern_id.split(':')
        base = parts[0].lower()
        if pattern.pattern_type == 'getattr':
            return f"{base}_dispatch"
        elif pattern.pattern_type == 'subscript':
            return f"{base}_dispatch"
        else:
            return f"dispatch_{self._pattern_counter}"

    def _extract_method_name(self, full_name: str) -> str:
        """Extract method name from mangled C name.

        Examples:
            "Interpreter_execute_Module" → "execute_Module"
            "Scope_set" → "set"
        """
        # Find the struct separator (underscore before method)
        parts = full_name.split('_', 1)
        if len(parts) == 2:
            return parts[1]
        return full_name

    def get_patterns_for_function(self, func_name: str) -> list[DispatchPattern]:
        """Get all dispatch patterns used in a specific function."""
        return [p for p in self.dispatch_patterns.values()
                if any(cs for cs in p.call_sites)]  # Patterns with call sites in func

    def get_possible_callees(self, pattern_id: str) -> set:
        """Get all functions that could be called via a dispatch pattern."""
        pattern = self.dispatch_patterns.get(pattern_id)
        if pattern:
            return pattern.possible_callees
        return set()

    def is_monomorphic(self, func_name: str) -> bool:
        """Check if a function has only one caller (is monomorphic/not virtual)."""
        callers = self.callers_of.get(func_name, set())
        return len(callers) == 1

    def get_call_count(self, func_name: str) -> int:
        """Get number of direct callers of a function."""
        return len(self.callers_of.get(func_name, set()))

    def get_dispatch_tables(self) -> dict:
        """Get all planned dispatch tables keyed by callee set."""
        return self.dispatch_tables

    def get_compilable_functions(self) -> set:
        """Get set of functions that can be compiled to C (def→fn promotion)."""
        if hasattr(self, 'compilability'):
            return self.compilability.compilable_funcs
        return set()

    def is_function_compilable(self, func_name: str) -> bool:
        """Check if a function can be compiled to C."""
        if hasattr(self, 'compilability'):
            return self.compilability.is_compilable(func_name)
        return False

    def get_compilability_report(self) -> dict:
        """Get detailed compilability analysis report.

        Returns:
            {
                'compilable_count': int,
                'uncompilable_count': int,
                'compilable_functions': set,
                'uncompilable_with_reasons': dict
            }
        """
        if hasattr(self, 'compilability'):
            return {
                'compilable_count': self.compilability.get_compilable_count(),
                'uncompilable_count': len(self.compilability.uncompilable_funcs),
                'compilable_functions': self.compilability.compilable_funcs.copy(),
                'uncompilable_with_reasons': self.compilability.uncompilable_funcs.copy(),
            }
        return {'compilable_count': 0, 'uncompilable_count': 0, 'compilable_functions': set(), 'uncompilable_with_reasons': {}}

    def get_promoted_types(self) -> dict:
        """Get all types promoted across the closure."""
        if hasattr(self, 'type_promoter'):
            return self.type_promoter.get_all_promoted_types()
        return {}


# ---------------------------------------------------------------------------
# FunctionCompilability — Determine which functions can be def→fn promoted
# ---------------------------------------------------------------------------

class FunctionCompilability:
    """Analyze whether functions can be compiled to C (def → fn promotion).

    A function is compilable to C if:
    1. All parameter types are known (no bare 'x' without type annotation)
    2. Return type is known (annotated or inferable)
    3. Body contains only C-compatible operations
    4. No dynamic feature usage (getattr, dict lookup, etc.)
    5. All called functions are also compilable to C

    This enables def→fn promotion: Python functions that compile become C functions.
    """

    def __init__(self, func_return_types: dict, struct_field_types: dict):
        self.func_return_types = func_return_types
        self.struct_field_types = struct_field_types
        self.compilable_funcs: set = set()  # Functions that can be compiled to C
        self.uncompilable_funcs: dict = {}  # func_name → reason (for debugging)

    def analyze(self, stmts: list):
        """Determine which functions are C-compilable."""
        # First pass: identify candidate functions with full signatures
        candidates = self._find_candidates(stmts)

        # Second pass: check if bodies use only C-compatible operations
        for func_name, func_def, is_method in candidates:
            reason = self._check_compilability(func_name, func_def, is_method)
            if reason is None:
                self.compilable_funcs.add(func_name)
            else:
                self.uncompilable_funcs[func_name] = reason

    def _find_candidates(self, stmts: list) -> list:
        """Find functions with complete type annotations.

        Returns list of (func_name, func_def, is_method) tuples.
        """
        candidates = []
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                # Free function with return type annotation
                if stmt.return_type is not None:
                    has_all_params = all(ptype is not None for _, ptype in stmt.params)
                    if has_all_params:
                        candidates.append((stmt.name, stmt, False))

            elif isinstance(stmt, StructDef):
                # Struct methods
                for method in stmt.methods:
                    if method.return_type is not None:
                        # For methods, 'self' is implicitly typed, so skip it in validation
                        non_self_params = [(pname, ptype) for pname, ptype in method.params if pname != 'self']
                        has_all_params = all(ptype is not None for _, ptype in non_self_params)
                        if has_all_params:
                            full_name = f"{stmt.name}_{method.name}"
                            candidates.append((full_name, method, True))

        return candidates

    def _check_compilability(self, func_name: str, func_def, is_method: bool) -> str | None:
        """Check if a function body is C-compilable.

        Returns None if compilable, otherwise returns reason string.
        """
        # Check for dynamic operations in body
        for node in self._walk_all_nodes(func_def.body):
            # getattr is dynamic - can't compile
            if isinstance(node, CallExpr):
                if isinstance(node.func, IdentExpr):
                    if node.func.name in ('getattr', 'setattr', 'hasattr'):
                        return f"uses {node.func.name}() - dynamic dispatch"

            # Dict subscript might be dynamic
            if isinstance(node, SubscriptExpr):
                if isinstance(node.obj, IdentExpr):
                    if node.obj.name in ('_STMT_DISPATCH', '_EXPR_DISPATCH'):
                        return "uses dynamic dispatch table"

        return None  # Compilable

    def _walk_all_nodes(self, stmts: list):
        """Recursively yield all AST nodes in statements and expressions."""
        for stmt in stmts:
            yield stmt

            # Recurse into expressions in statements
            if isinstance(stmt, AssignStmt):
                yield from self._walk_expr_nodes(stmt.value)
            elif isinstance(stmt, ReturnStmt) and stmt.value:
                yield from self._walk_expr_nodes(stmt.value)
            elif isinstance(stmt, ExprStmt):
                yield from self._walk_expr_nodes(stmt.value)
            elif isinstance(stmt, IfStmt):
                yield from self._walk_expr_nodes(stmt.condition)
                yield from self._walk_all_nodes(stmt.then_body)
                for _, elif_body in stmt.elifs:
                    yield from self._walk_all_nodes(elif_body)
                if stmt.else_body:
                    yield from self._walk_all_nodes(stmt.else_body)
            elif isinstance(stmt, (WhileStmt, ForStmt)):
                yield from self._walk_all_nodes(stmt.body)
            elif isinstance(stmt, TryStmt):
                yield from self._walk_all_nodes(stmt.body)

    def _walk_expr_nodes(self, expr):
        """Recursively yield all nodes in an expression tree."""
        if expr is None:
            return

        yield expr

        if isinstance(expr, CallExpr):
            yield from self._walk_expr_nodes(expr.func)
            for arg in expr.args:
                yield from self._walk_expr_nodes(arg)
        elif isinstance(expr, BinaryOp):
            yield from self._walk_expr_nodes(expr.left)
            yield from self._walk_expr_nodes(expr.right)
        elif isinstance(expr, TernaryExpr):
            yield from self._walk_expr_nodes(expr.condition)
            yield from self._walk_expr_nodes(expr.then_val)
            yield from self._walk_expr_nodes(expr.else_val)
        elif isinstance(expr, SubscriptExpr):
            yield from self._walk_expr_nodes(expr.obj)
            yield from self._walk_expr_nodes(expr.index)
        elif isinstance(expr, MemberExpr):
            yield from self._walk_expr_nodes(expr.obj)

    def is_compilable(self, func_name: str) -> bool:
        """Check if a function can be compiled to C."""
        return func_name in self.compilable_funcs

    def get_compilable_count(self) -> int:
        """Get number of C-compilable functions."""
        return len(self.compilable_funcs)

    def get_reason(self, func_name: str) -> str | None:
        """Get reason why a function isn't compilable."""
        return self.uncompilable_funcs.get(func_name)


# ---------------------------------------------------------------------------
# TypePromotionSolver — Promote types across transitive closure
# ---------------------------------------------------------------------------

class TypePromotionSolver:
    """Propagate and promote types across function call graph.

    This solver:
    1. Tracks variable types through function parameters
    2. Propagates return types to callers
    3. Promotes types to compatible forms (e.g., int64_t ← int)
    4. Detects type conflicts and reports them
    5. Produces final promoted type map for all variables

    The result is a complete cross-closure type map that enables
    accurate type inference and promotion even for unannotated code.
    """

    def __init__(self, call_graph: dict, func_return_types: dict):
        self.call_graph = call_graph  # caller → {callees}
        self.func_return_types = func_return_types
        self.promoted_types: dict = {}  # var_name → promoted_type
        self.type_conflicts: dict = {}  # var_name → [types_seen]

    def analyze(self, stmts: list, all_funcs: dict):
        """Propagate types across closure.

        Args:
            stmts: All statements in module
            all_funcs: Dict of func_name → FunctionDef for all functions
        """
        # Pass 1: Collect all function signatures
        signatures = self._collect_signatures(stmts)

        # Pass 2: Propagate return types to call sites
        self._propagate_return_types(signatures)

        # Pass 3: Promote common types to compatible forms
        self._promote_types()

    def _collect_signatures(self, stmts: list) -> dict:
        """Collect function signatures from module."""
        signatures = {}
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                signatures[stmt.name] = {
                    'params': stmt.params,
                    'return_type': stmt.return_type,
                }
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    full_name = f"{stmt.name}_{method.name}"
                    signatures[full_name] = {
                        'params': method.params,
                        'return_type': method.return_type,
                    }
        return signatures

    def _propagate_return_types(self, signatures: dict):
        """Propagate return types from callees to callers."""
        # For each function with known return type, record it
        for func_name, ret_type in self.func_return_types.items():
            if ret_type != 'void':
                # Callers of this function now know what type it returns
                key = f"__return__{func_name}"
                self.promoted_types[key] = ret_type

    def _promote_types(self):
        """Promote types to compatible common forms.

        Examples:
            int8, int16, int32 → int64_t (for closure consistency)
            float, float32 → double (wider type)
        """
        # Collect all types we've seen
        int_types = set()
        float_types = set()

        for var_type in self.promoted_types.values():
            if 'int' in var_type.lower():
                int_types.add(var_type)
            elif 'float' in var_type.lower() or 'double' in var_type.lower():
                float_types.add(var_type)

        # Promote to common forms
        if int_types:
            # Promote all ints to int64_t for closure consistency
            promoted_int = 'int64_t' if any('64' in t for t in int_types) else 'int'
            for var_name in list(self.promoted_types.keys()):
                if 'int' in self.promoted_types[var_name].lower():
                    self.promoted_types[var_name] = promoted_int

        if float_types:
            # Promote all floats to double for closure consistency
            promoted_float = 'double'
            for var_name in list(self.promoted_types.keys()):
                if 'float' in self.promoted_types[var_name].lower():
                    self.promoted_types[var_name] = promoted_float

    def get_promoted_type(self, var_name: str) -> str | None:
        """Get promoted type for a variable."""
        return self.promoted_types.get(var_name)

    def get_all_promoted_types(self) -> dict:
        """Get all promoted types."""
        return self.promoted_types.copy()


# ---------------------------------------------------------------------------
# Type system helpers
# ---------------------------------------------------------------------------

# `Int`/`UInt` are the machine word — a newtype over `__mlir_type.index`, which is
# 64-bit (mlir.py) — and `Bool` is the ABI's `_Bool` (ABI.md). They therefore map
# to int64_t/uint64_t/_Bool, matching the reflected stdlib layouts exactly (review
# finding #7's migration). The no-annotation default is likewise int64_t; an
# *unknown* annotation still falls back to `int` (see _mojo_type).
_TYPE_MAP: dict[str | None, str] = {
    'Int':    'int64_t',
    'Int8':   'int8_t',
    'Int16':  'int16_t',
    'Int32':  'int32_t',
    'Int64':  'int64_t',
    'UInt':   'uint64_t',
    'UInt8':  'uint8_t',
    'UInt16': 'uint16_t',
    'UInt32': 'uint32_t',
    'UInt64': 'uint64_t',
    'Float16': '__fp16',
    'Float32': 'float',
    'Float64': 'double',
    'Bool':   '_Bool',
    # Python-style `bool` flags cross the C ABI as `int` (e.g. compile_to_gimple's
    # do_imports — runtime header declares `int do_imports`). A flag is never a
    # boxed handle, so it must not hit the int64_t boxed-object default.
    'bool':   'int',
    'String': 'char *',
    'str':    'char *',
    'List':   'MojoList *',
    'list':   'MojoList *',
    'Dict':   'MojoDict *',
    'dict':   'MojoDict *',
    'Set':    'MojoSet *',
    'set':    'MojoSet *',
    'Str':    'MojoStr *',
    'None':   'void',
    # A boxed object reference (AST node child, dynamic value) is a 64-bit tagged
    # handle in this runtime, accessed via mojo_obj_getattr — never a 32-bit int.
    'object': 'int64_t',
    None:     'int64_t',   # consistent with _mojo_type(None); was 'int' (#7)
}

# Return types of well-known runtime functions (seeds func_return_types)
_RUNTIME_FUNCS: dict[str, str] = {
    # exceptions
    'mojo_try_push':              'int',
    'mojo_exc_pop':               'void',
    'mojo_raise':                 'void',
    'mojo_exc_msg_set':           'void',
    'mojo_exc_msg_get':           'char *',
    # list
    'mojo_list_new':              'MojoList *',
    'mojo_list_len':              'int64_t',
    'mojo_list_get_int':          'int64_t',
    'mojo_list_get_double':       'double',
    'mojo_list_get_str':          'char *',
    'mojo_list_contains_int':     'int',
    'mojo_list_contains_double':  'int',
    'mojo_list_contains_str':     'int',
    'mojo_list_set_int':          'void',
    'mojo_list_set_double':       'void',
    'mojo_list_set_str':          'void',
    'mojo_list_slice':            'MojoList *',
    'mojo_list_concat':           'MojoList *',
    # dict
    'mojo_dict_new':              'MojoDict *',
    'mojo_dict_get_int':          'int64_t',
    'mojo_dict_get_double':       'double',
    'mojo_dict_get_str':          'char *',
    'mojo_dict_contains':         'int',
    'mojo_dict_len':              'int64_t',
    'mojo_dict_iter_new':         'MojoDictIter *',
    'mojo_dict_iter_next':        'int',
    'mojo_dict_iter_key':         'char *',
    'mojo_dict_iter_val_int':     'int64_t',
    'mojo_dict_iter_val_double':  'double',
    'mojo_dict_iter_val_str':     'char *',
    'mojo_dict_iter_free':        'void',
    # set
    'mojo_set_new':               'MojoSet *',
    'mojo_set_contains_int':      'int',
    'mojo_set_contains_str':      'int',
    'mojo_set_len':               'int64_t',
    'mojo_set_iter_new':          'MojoSetIter *',
    'mojo_set_iter_next':         'int',
    'mojo_set_iter_val_int':      'int64_t',
    'mojo_set_iter_val_str':      'char *',
    'mojo_set_iter_free':         'void',
    # string
    'mojo_str_new':               'MojoStr *',
    'mojo_str_concat':            'MojoStr *',
    'mojo_str_len':               'int64_t',
    'mojo_str_data':              'char *',
    'mojo_str_char_at':           'char',
    'mojo_str_eq':                'int',
    'mojo_str_contains':          'int',
    'mojo_str_slice':             'MojoStr *',
    'mojo_str_from_char':         'MojoStr *',
    'mojo_str_repeat':            'MojoStr *',
    'mojo_str_to_int':            'int64_t',
    'mojo_str_to_float':          'double',
    # C-string utilities used by the REPL and string methods
    'input':          'char *',
    'string_lower':   'char *',
    'string_strip':   'char *',
    'string_upper':   'char *',
    'compile_to_gimple': 'char *',
    # Interpreter/bridge functions (provided by runtime or compiled code)
    'tokenize':           'MojoList *',
    'Parser':             'Parser *',    # Parser() constructor
    'Interpreter':        'Interpreter *',
}

_FLOAT_TYPES = {'double', 'float', '__fp16'}

def _mojo_type(ann: str | type | None) -> str:
    if not ann:
        return 'int64_t'  # Default to 64-bit signed integer
    if isinstance(ann, type):
        ann = ann.__name__
    # MLIR builtin types underlying the stdlib's scalar newtypes: __mlir_type.index, etc.
    if isinstance(ann, str) and ann.startswith('__mlir_type.'):
        c = mlir.type_to_c(ann[len('__mlir_type.'):])
        if c is not None:
            return c
    # Handle Union types: X | Y | ... → resolve to first non-None type
    if ' | ' in ann:
        parts = [p.strip() for p in ann.split(' | ')]
        non_none = [p for p in parts if p != 'None']
        if non_none:
            return _mojo_type(non_none[0])
        return 'int64_t'
    # Handle parameterized types: UnsafePointer[Int], List[Float64], etc.
    if '[' in ann:
        base, rest = ann.split('[', 1)
        inner = rest.rstrip(']').strip()
        if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
            elem = _mojo_type(inner)
            return f"{elem} *"
        if base in ('List', 'list', 'InlineArray'):
            return 'MojoList *'
        if base in ('Dict', 'dict'):
            return 'MojoDict *'
        if base in ('Set', 'set'):
            return 'MojoSet *'
        # Span / StringSlice are fat pointers {_data, _len}; model as a struct ptr
        # so .unsafe_ptr()/.__len__()/len() lower to field reads (see _seed_span).
        if base in ('Span', 'StringSlice'):
            return 'Span *'
        if base == 'Optional':
            return _mojo_type(inner)  # simplified: treat as the inner type
        # Unknown parameterized type — fall through to plain lookup
        ann = base
    t = _TYPE_MAP.get(ann)
    return t if t is not None else 'int64_t'

# Keep legacy helper name for backward compat inside this file
def _result_type(t1: str, t2: str) -> str:
    return TypeLattice.join(t1, t2)

def _elem_type(ptr_type: str) -> str:
    """Strip one level of pointer to get element type."""
    if ptr_type.endswith(' *'):
        return ptr_type[:-2]
    if '*' in ptr_type:
        return ptr_type.replace('*', '').strip()
    return 'int64_t'

_C_ID_MAP = {'char *': 'charptr', 'void *': 'voidptr', '_Bool': 'bool'}

def _c_id(ctype: str) -> str:
    """Convert a C type to a valid identifier suffix (for helper function names)."""
    return _C_ID_MAP.get(ctype, ctype.replace(' ', '_').replace('*', 'ptr'))

def _printf_fmt(ctype: str) -> str:
    return TypeLattice.printf_fmt(ctype)

def _strip_mojo_param_modifiers(pname: str) -> str:
    """Strip Mojo parameter modifiers (inout, borrowed, owned, etc.) from parameter name.

    These modifiers are not valid in C and must be removed for code generation.
    Examples: 'inout self' → 'self', 'borrowed x' → 'x', 'owned data' → 'data'
    """
    modifiers = ('inout', 'borrowed', 'owned', 'borrow', 'out', 'mut', 'ref', 'read', 'copy')
    for mod in modifiers:
        if pname.startswith(mod + ' '):
            return pname[len(mod) + 1:].strip()
    return pname

# Cache for type-expression walk results, keyed by id() of AST node.
_type_walk_cache: dict[int, str] = {}

def _walk_type_expr(node) -> str:
    """Recursively serialize an AST type expression to a canonical string."""
    if node is None:
        return 'any'
    if isinstance(node, str):
        return node
    nid = id(node)
    cached = _type_walk_cache.get(nid)
    if cached is not None:
        return cached
    if isinstance(node, IdentExpr):
        result = node.name
    elif isinstance(node, SubscriptExpr):
        base = _walk_type_expr(node.obj)
        idx = node.index
        if isinstance(idx, TupleExpr):
            inner = ','.join(_walk_type_expr(e) for e in idx.elements)
        else:
            inner = _walk_type_expr(idx)
        result = f"{base}[{inner}]"
    elif isinstance(node, MemberExpr):
        result = f"{_walk_type_expr(node.obj)}.{node.member}"
    elif isinstance(node, TupleExpr):
        result = '(' + ','.join(_walk_type_expr(e) for e in node.elements) + ')'
    elif isinstance(node, (IntLiteral, FloatLiteral)):
        result = str(node.value)
    elif isinstance(node, StringLiteral):
        result = f'"{node.value}"'
    else:
        result = type(node).__name__
    _type_walk_cache[nid] = result
    return result

def _param_sig_str(params: tuple) -> str:
    """Produce a canonical signature string from a (pname, ptype) tuple of params."""
    parts = []
    for pname, ptype in params:
        bare = pname.lstrip('*') if pname else ''
        type_str = _walk_type_expr(ptype)
        parts.append(f"{bare}:{type_str}")
    return ','.join(parts)

# Registry mapping hash suffix (e.g. '76baef') → canonical param signature string.
# Populated by _method_overload_id so that tools like mojofilt can demangle
# a C symbol like 'Bool___init___76baef' back to 'Bool.__init__(self:any)'.
_overload_hash_registry: dict[str, str] = {}

def _method_overload_id(param_types: tuple, struct_name: str = '', method_name: str = '') -> str:
    """Generate a short stable hash ID for a method overload from its param types.

    Walks each param's type expression recursively, hashes the canonical
    string, and returns the first 6 hex digits as the suffix.
    Also registers the mapping in _overload_hash_registry for demangling.
    """
    sig = _param_sig_str(param_types)
    h = hashlib.md5(sig.encode(), usedforsecurity=False).hexdigest()[:6]
    # Store demangle info: hash → "StructName.method(sig)"
    full = f"{struct_name}.{method_name}({sig})" if struct_name else sig
    _overload_hash_registry[h] = full
    return f"_{h}"

def demangle_overload(c_name: str) -> str:
    """Demangle a C function name with an overload hash suffix back to Mojo form.

    E.g. 'Bool___init___76baef' → 'Bool.__init__(self:any)'
    Returns the original c_name unchanged if no match is found.
    """
    # Pattern: StructName___methodname___HASH (6 hex chars)
    import re as _re
    m = _re.search(r'___([0-9a-f]{6})$', c_name)
    if not m:
        return c_name
    h = m.group(1)
    sig = _overload_hash_registry.get(h)
    if not sig:
        return c_name
    # Reconstruct: strip the _HASH suffix and replace with the full Mojo form
    base = c_name[:-(7)]  # strip '___' + 6 chars
    return f"{base} ({sig})"

# ---------------------------------------------------------------------------
# Operator tables  (imported from generated_dispatch.py)
# ---------------------------------------------------------------------------

_BIN_OPS  = _GD_BIN_OPS   # Mojo op → C infix op; **, //, @ handled separately
_CMP_OPS  = _GD_CMP_OPS   # operators whose result type is _Bool

# ---------------------------------------------------------------------------
# C keyword avoidance
# ---------------------------------------------------------------------------

# Trait/dunder method names common across many types — excluded from the imported
# struct method-call gate (a `.write_to(`/`.__str__(` elsewhere must not veto a
# struct that's only field-accessed; these also have generic codegen handling).
_COMMON_METHOD_NAMES = frozenset({
    'write_to', 'write_text', 'write', 'format', 'copy', 'fdopen',
    '__contains__', '__str__', '__repr__', '__len__', '__iter__', '__next__',
    '__eq__', '__ne__', '__lt__', '__le__', '__gt__', '__ge__', '__bool__',
    '__init__', '__copyinit__', '__moveinit__', '__del__', '__hash__',
    '__getitem__', '__setitem__', '__add__', '__sub__', '__mul__', '__call__',
})

_C_KEYWORDS = frozenset({
    'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do',
    'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if',
    'inline', 'int', 'long', 'register', 'restrict', 'return', 'short',
    'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union',
    'unsigned', 'void', 'volatile', 'while',
    '_Bool', '_Complex', '_Imaginary', '_Alignas', '_Alignof', '_Atomic',
    '_Generic', '_Noreturn', '_Static_assert', '_Thread_local',
    # C23 keywords gcc-15 enforces in its default mode — a Mojo identifier named
    # any of these (e.g. `nullptr`) would otherwise emit invalid C.
    'nullptr', 'constexpr', 'thread_local', 'static_assert', 'typeof_unqual',
})

# Extra identifiers that are valid C keywords in GCC but not in standard C keywords list
# (e.g. GCC extension 'asm', C++ keywords that GCC treats as reserved in C mode)
_C_PARAM_EXTRA_KEYWORDS = frozenset({'asm', '__asm__', 'typeof', '__typeof__'})

# C standard-library macros that expand to numeric constants — using them as identifiers
# causes the preprocessor to replace them before GCC sees the code (e.g. 'true' → '1').
_C_MACRO_NAMES = frozenset({'true', 'false', 'NULL', 'EOF', 'SEEK_SET', 'SEEK_CUR', 'SEEK_END'})

def _safe_field(name: str) -> str:
    """Sanitize struct field and parameter names that are C keywords."""
    if name in _C_KEYWORDS or name in _C_PARAM_EXTRA_KEYWORDS:
        return f'_kw_{name}'
    return name

def _struct_name_of(ctype: str) -> str:
    """Extract the bare struct name from a C type like 'const Foo *' → 'Foo'."""
    s = ctype
    if s.startswith('const '):
        s = s[6:]
    return s.replace(' *', '').strip()

# libc/system symbols a Mojo *function definition* must not shadow: the library
# itself defines e.g. `fn exit(...)` whose body calls libc `exit` via
# external_call. Emitting that as C `exit` would self-recurse and clash with the
# stdlib.h prototype. So a Mojo function with one of these names is mangled to
# `mojo_<name>` (definition AND call sites, via this chokepoint), while
# external_call keeps emitting the raw libc symbol.
_C_RESERVED_FUNCS = frozenset({
    # Core libc functions that Mojo stdlib may redefine.
    # At DEFINITION sites these are always renamed (fn abs → mojo_abs).
    # At CALL sites they are only renamed when a local definition exists
    # (see _lower_CallExpr: the rename is gated on func_return_types).
    'exit', 'abort', 'write', 'read', 'close',
    'malloc', 'calloc', 'realloc', 'free',
    'printf', 'fprintf', 'snprintf', 'sprintf', 'dprintf', 'puts', 'putchar',
    'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
    'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat',
    'strchr', 'strrchr', 'strstr', 'strtok', 'strerror',
    'atoi', 'atol', 'atoll', 'atof',
    'strtol', 'strtoll', 'strtod', 'strtof',
    'setvbuf', 'setbuf',
    'remainderf', 'remainderl',
    'posix_spawn', 'posix_spawnp',
    'index', 'rindex',
    # Math functions (from <math.h>) that the Mojo stdlib may redefine
    'cos', 'cosf', 'sin', 'sinf', 'tan', 'tanf',
    'acos', 'acosf', 'asin', 'asinf', 'atan', 'atanf', 'atan2', 'atan2f',
    'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf', 'trunc', 'truncf',
    'sqrt', 'sqrtf', 'cbrt', 'cbrtf',
    'pow', 'powf', 'exp', 'expf', 'exp2', 'exp2f', 'log', 'logf',
    'log2', 'log2f', 'log10', 'log10f',
    'fabs', 'fabsf', 'fmod', 'fmodf',
    'erf', 'erff', 'erfc', 'erfcf', 'tgamma', 'lgamma',
    'ldexp', 'ldexpf', 'frexp', 'frexpf', 'modf', 'modff',
    'sinh', 'sinhf', 'cosh', 'coshf', 'tanh', 'tanhf',
    'asinh', 'acosh', 'atanh', 'asinhf', 'acoshf', 'atanhf',
    'nextafter', 'nextafterf', 'copysign', 'copysignf',
    'nan', 'nanf', 'hypot', 'hypotf', 'fma', 'fmaf', 'remainder',
    'expm1', 'expm1f', 'log1p', 'log1pf',
    'scalb', 'scalbf', 'scalbn', 'scalbnf', 'logb', 'logbf',
    'j0', 'j1', 'y0', 'y1',
    # Environment / system functions
    'getenv', 'setenv', 'unsetenv', 'putenv', 'realpath',
    # File I/O
    'open',
    'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'rewind', 'fflush',
    'getline', 'getdelim', 'fgets', 'fputs', 'feof', 'ferror', 'clearerr',
    'vprintf', 'vfprintf', 'vsnprintf', 'vsprintf',
    'fdopen', 'popen', 'pclose',
    'remove', 'rename',
    # Random / stdlib math
    'rand', 'srand', 'random', 'srandom',
    # Process / unix
    'getuid', 'getgid', 'getpid', 'getppid', 'waitpid', 'fork', 'execv',
    'symlink', 'readlink', 'link', 'mkdir', 'chmod', 'chown', 'unlink', 'rmdir',
    'ioctl', 'fcntl', 'dup', 'dup2', 'pipe',
    # Dynamic linking
    'dlopen', 'dlsym', 'dlclose', 'dlerror',
    # Other stdlib
    'access', 'stat', 'lstat', 'fstat',
    'qsort', 'bsearch',
    # Integer / float math
    'abs', 'labs', 'llabs',
    'fabsf', 'fmodf', 'sqrtf', 'powf', 'ceilf', 'floorf', 'roundf', 'truncf',
    # Math classification macros (<math.h>)
    'isfinite', 'isinf', 'isnan', 'isnormal', 'signbit', 'fpclassify',
    # ctype
    'isalpha', 'isdigit', 'isalnum', 'isspace', 'isupper', 'islower',
    'toupper', 'tolower',
    # POSIX/BSD extras
    'strdup', 'strndup', 'strtok_r',
    # Time
    'time', 'clock', 'difftime', 'mktime', 'strftime',
    'gmtime', 'localtime',
    # Signal
    'signal', 'raise',
    # GCC GIMPLE FE keywords — calling these inside __GIMPLE triggers a parse error.
    '_end',
})

# Names in _C_RESERVED_FUNCS where the C version's return type is incompatible with
# int64_t (e.g. char *). Must always rename to mojo_X even without a local definition.
_FORCE_RENAME_RESERVED = frozenset({'index', 'rindex', 'getenv'})

def _is_concrete_type_arg(ann: str) -> bool:
    """Whether a generic type argument is a concrete type (Int64, String, a struct,
    DType.int64) rather than an unbound type parameter (T, U, T0, *Ts, Self.T,
    Self.Types[i]). Only concrete args may be instantiated — substituting one
    symbol for another never converges and blows up the elaborator."""
    if not isinstance(ann, str) or not ann:
        return False
    base = ann.split('[', 1)[0].strip()
    if base.startswith('Self') or base.startswith('*') or not base:
        return False                       # Self.T, Self.Types[i], *Ts
    if re.fullmatch(r'[A-Z][0-9]?', base):
        return False                       # lone type param: T, U, K, T0, T1
    return True


def _safe_name(name: str) -> str:
    # Handle backtick-quoted Mojo identifiers (e.g. `6bit` → _6bit)
    if name.startswith('`') and name.endswith('`') and len(name) > 2:
        name = name[1:-1]
        if name and name[0].isdigit():
            name = '_' + name
        # Replace any remaining non-C-identifier chars
        import re as _re
        name = _re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if name in _C_KEYWORDS or name in _C_RESERVED_FUNCS:
        return f"mojo_{name}"
    return name


def _c_field_name(name: str) -> str:
    """Convert a Mojo variable/module name to a valid C struct field name.
    Dots in module paths (e.g. 'std.sys') become underscores ('std__sys')."""
    import re as _re
    return _re.sub(r'[^a-zA-Z0-9_]', '_', name)


def _c_escape(s: str) -> str:
    """Escape a Mojo string-literal's content for the body of a C string literal.

    The source already uses C-style escapes (`\\n`, `\\t`, `\\\\`, ...), so those are
    passed through unchanged rather than having their backslash doubled — the old
    code did `replace('\\\\','\\\\\\\\')` first, turning `\\n` into a literal
    backslash-n in the output. Lone backslashes, quotes, and raw control chars are
    escaped. Non-ASCII bytes pass through untouched."""
    known = set('ntr"\\\'0abfv')
    out = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '\\' and i + 1 < n and s[i + 1] in known:
            out.append(ch); out.append(s[i + 1]); i += 2; continue
        if ch == '\\' and i + 1 < n and s[i + 1] == 'x':
            # Only pass \x through if followed by valid hex digit(s)
            if i + 2 < n and s[i + 2] in '0123456789abcdefABCDEF':
                out.append(ch); out.append(s[i + 1]); i += 2; continue
            else:
                out.append('\\\\x'); i += 2; continue
        if ch == '\\':
            out.append('\\\\'); i += 1; continue
        if ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        else:
            out.append(ch)
        i += 1
    return ''.join(out)

def _extract_init_expr(stmt_value) -> str:
    """Generate C initialization code for a module-level assignment RHS."""
    if stmt_value is None:
        return '0'
    if isinstance(stmt_value, DictExpr):
        if not stmt_value.pairs:
            return 'mojo_dict_new()'
        return '0'  # Non-empty: needs runtime init in _toplevel
    elif isinstance(stmt_value, ListExpr):
        if not stmt_value.elements:
            return 'mojo_list_new()'
        return '0'
    elif isinstance(stmt_value, SetExpr):
        if not stmt_value.elements:
            return 'mojo_set_new()'
        return '0'
    elif isinstance(stmt_value, IntLiteral):
        return str(stmt_value.value)
    elif isinstance(stmt_value, BoolLiteral):
        return '1' if stmt_value.value else '0'
    elif isinstance(stmt_value, StringLiteral):
        return f'"{_c_escape(stmt_value.value)}"'
    elif isinstance(stmt_value, (CallExpr, IdentExpr)):
        return '0'  # Can't static-initialize; needs runtime init
    else:
        return '0'

def _module_toplevel_name(module_name: str) -> str:
    """Generate a unique C function name for a module's initializer."""
    import re
    safe = re.sub(r'[^A-Za-z0-9_]', '_', module_name)
    if safe and safe[0].isdigit():
        safe = '_' + safe
    return f"_{safe}_toplevel"

# ---------------------------------------------------------------------------
# Free-variable helpers (module level, used by closure pre-pass)
# ---------------------------------------------------------------------------

def _used_idents_node(node) -> set:
    """All IdentExpr names referenced in node; does NOT cross FunctionDef boundaries."""
    if node is None: return set()
    if isinstance(node, IdentExpr):         return {node.name}
    if isinstance(node, FunctionDef):        return set()
    if isinstance(node, BinaryOp):           return _used_idents_node(node.left) | _used_idents_node(node.right)
    if isinstance(node, UnaryOp):            return _used_idents_node(node.operand)
    if isinstance(node, CallExpr):
        r = _used_idents_node(node.func)
        for a in node.args: r |= _used_idents_node(a)
        return r
    if isinstance(node, MemberExpr):         return _used_idents_node(node.obj)
    if isinstance(node, SubscriptExpr):      return _used_idents_node(node.obj) | _used_idents_node(node.index)
    if isinstance(node, SliceExpr):
        r = _used_idents_node(node.obj)
        if node.start: r |= _used_idents_node(node.start)
        if node.stop:  r |= _used_idents_node(node.stop)
        return r
    if isinstance(node, TernaryExpr):
        return (_used_idents_node(node.condition) | _used_idents_node(node.then_val)
                | _used_idents_node(node.else_val))
    if isinstance(node, WalrusExpr):
        return {node.name} | _used_idents_node(node.value)
    if isinstance(node, (ListExpr, SetExpr, TupleExpr)):
        r: set = set()
        for e in node.elements: r |= _used_idents_node(e)
        return r
    if isinstance(node, DictExpr):
        r2: set = set()
        for k, v in node.pairs: r2 |= _used_idents_node(k) | _used_idents_node(v)
        return r2
    if isinstance(node, Comprehension):
        r3 = _used_idents_node(node.element)
        # dict comprehension: field 'key' holds the value expression
        if getattr(node, 'key', None) is not None: r3 |= _used_idents_node(node.key)
        gen_vars: set = set()
        for g in node.generators:
            r3 |= _used_idents_node(g.iterable)
            # The iteration variable is locally scoped to the comprehension —
            # do not treat it as a free variable of the enclosing function.
            tgt = g.target
            if isinstance(tgt, str):
                gen_vars.add(tgt)
            elif isinstance(tgt, (list, tuple)):
                for item in tgt:
                    if isinstance(item, str): gen_vars.add(item)
                    elif hasattr(item, 'name'): gen_vars.add(item.name)
            elif hasattr(tgt, 'name'):
                gen_vars.add(tgt.name)
        r3 -= gen_vars
        return r3
    if isinstance(node, (PassStmt, BreakStmt, ContinueStmt)):   return set()
    if isinstance(node, ReturnStmt):    return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, RaiseStmt):     return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, ExprStmt):      return _used_idents_node(node.value)
    if isinstance(node, AssertStmt):    return _used_idents_node(node.value)
    if isinstance(node, VarDecl):       return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, AssignStmt):    return _used_idents_node(node.target) | _used_idents_node(node.value)
    if isinstance(node, AugAssignStmt): return _used_idents_node(node.target) | _used_idents_node(node.value)
    if isinstance(node, MultiAssignStmt):
        r4 = _used_idents_node(node.value)
        for t in node.targets: r4 |= _used_idents_node(t)
        return r4
    if isinstance(node, IfStmt):
        r5 = _used_idents_node(node.condition)
        for s in node.then_body: r5 |= _used_idents_node(s)
        for _, eb in node.elifs:
            for s in eb: r5 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body: r5 |= _used_idents_node(s)
        return r5
    if isinstance(node, WhileStmt):
        r6 = _used_idents_node(node.condition)
        for s in node.body: r6 |= _used_idents_node(s)
        return r6
    if isinstance(node, ForStmt):
        r7 = _used_idents_node(node.iterable)
        for s in node.body: r7 |= _used_idents_node(s)
        return r7
    if isinstance(node, TryStmt):
        r8: set = set()
        for s in node.body: r8 |= _used_idents_node(s)
        for h in node.handlers:
            for s in h.body: r8 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body: r8 |= _used_idents_node(s)
        if node.finally_body:
            for s in node.finally_body: r8 |= _used_idents_node(s)
        return r8
    if isinstance(node, WithStmt):
        r9: set = set()
        for item in node.items: r9 |= _used_idents_node(item.expr)
        for s in node.body: r9 |= _used_idents_node(s)
        return r9
    return set()


def _declared_vars_body(stmts) -> set:
    """Variables declared in a statement list (does not cross FunctionDef boundaries)."""
    result: set = set()
    for node in stmts:
        if isinstance(node, VarDecl):
            result.add(node.name)
        elif isinstance(node, ForStmt):
            tgt = node.target
            name = tgt if isinstance(tgt, str) else getattr(tgt, 'name', '')
            if isinstance(name, str) and name.startswith('(') and name.endswith(')'):
                # tuple target `for a, b in ...`: each unpacked name is declared
                for part in name[1:-1].split(','):
                    p = part.strip()
                    if p:
                        result.add(p)
            elif name:
                result.add(name)
            result |= _declared_vars_body(node.body)
        elif isinstance(node, IfStmt):
            result |= _declared_vars_body(node.then_body)
            for _, eb in node.elifs: result |= _declared_vars_body(eb)
            if node.else_body: result |= _declared_vars_body(node.else_body)
        elif isinstance(node, (WhileStmt, WithStmt)):
            result |= _declared_vars_body(node.body)
        elif isinstance(node, TryStmt):
            result |= _declared_vars_body(node.body)
            for h in node.handlers:
                if h.name: result.add(h.name)
                result |= _declared_vars_body(h.body)
            if node.else_body:    result |= _declared_vars_body(node.else_body)
            if node.finally_body: result |= _declared_vars_body(node.finally_body)
    return result


class ClosureInfo:
    """Describes a nested function lifted to module scope."""
    def __init__(self, lifted_name: str, env_struct: str,
                 captures: list, inner_def):
        self.lifted_name        = lifted_name
        self.env_struct         = env_struct
        self.captures           = captures   # [(varname, ctype)]
        self.inner_def          = inner_def  # FunctionDef node
        self.is_re_sub_callback = False      # True if used as re.sub(pat, THIS, src)
        self.inferred_params: dict = {}      # pname → ctype (filled by _gen_lifted_closure)
        self.inferred_ret: str = ''          # filled by _gen_lifted_closure


# ---------------------------------------------------------------------------
# Runtime helpers (emitted as regular C before __GIMPLE functions)
# ---------------------------------------------------------------------------

_HELPERS = """\
static int64_t __mojo_floordiv (int64_t a, int64_t b)
{
  int64_t q = a / b;
  return q - (a % b != 0 && (a ^ b) < 0);
}
"""

# ---------------------------------------------------------------------------
# String constants for GIMPLE-compatible emit patterns
# (defined at module level to avoid transpiler optimizing them to globals)
# ---------------------------------------------------------------------------

_COMMENT_WALRUS_UNSUPPORTED = "  /* walrus: unsupported LHS */"
_COMMENT_IN_RANGE_TODO = "  /* TODO: in range(a, b, step) */"
_COMMENT_COMPLEX_CALL = "  /* TODO: complex call expression */"
_COMMENT_COMP_NO_GEN = "  /* TODO: Comprehension with no generators */"
_COMMENT_RANGE_UNEXPECTED = "  /* TODO: range() unexpected arg count */"
_COMMENT_COMPLEX_ASSIGN = "  /* TODO: complex assignment target */"
_COMMENT_COMPLEX_AUG = "  /* TODO: complex aug-assign target */"
_COMMENT_BREAK_OUTSIDE = "  /* TODO: break outside loop */"
_COMMENT_CONTINUE_OUTSIDE = "  /* TODO: continue outside loop */"
_COMMENT_COMPTIME_FOR = "  /* comptime for: iterable not constant — skipped */"
_COMMENT_RANGE_UNEXPECTED2 = "  /* TODO: range() with unexpected argument count */"
_RETURN = "  return;"

# ---------------------------------------------------------------------------
# GimpleGen
# ---------------------------------------------------------------------------

class GimpleGen:
    # Map Python builtin names to their C/runtime equivalents when used as values
    BUILTIN_VALUE_MAP = {
        'print': 'mojo_print',
        'len': 'mojo_len',
        'range': 'mojo_range',
        'str': 'mojo_str',
        'int': 'mojo_make_int',
        'float': 'mojo_make_float',
        'bool': 'mojo_make_bool',
        'list': 'mojo_make_list',
        'dict': 'mojo_make_dict',
        'set': 'mojo_make_set',
        'tuple': 'mojo_make_tuple',
        'open': 'mojo_open_file',
        'enumerate': 'mojo_enumerate',
        'zip': 'mojo_zip',
        'map': 'mojo_map',
        'filter': 'mojo_filter',
        'isinstance': 'mojo_isinstance',
        'hasattr': 'mojo_hasattr',
        'getattr': 'mojo_getattr',
        'setattr': 'mojo_setattr',
        'type': 'mojo_type',
        'max': 'mojo_max',
        'min': 'mojo_min',
        'sum': 'mojo_sum',
        'sorted': 'mojo_sorted',
        'reversed': 'mojo_reversed',
        '__builtins__': '0',
        'eval':         'mojo_eval',
    }

    def __init__(self, do_imports: bool = False, emit_str_pool: bool = True, emit_struct_defs: bool = True,
                 emit_entry_points: bool = True, module_name: str = "", link_imports: bool = False,
                 no_mangle=()):
        # Function names that must NOT be overload-mangled in this TU — e.g. a
        # generic instantiation's own symbol, which is already uniquely named by
        # its type args and is referenced by that exact name from call sites.
        self._extra_no_mangle: set = set(no_mangle)
        self.do_imports = do_imports
        self.emit_str_pool = emit_str_pool      # only main module emits string pool; imported modules skip it
        self.emit_struct_defs = emit_struct_defs  # only main module emits struct typedefs; imported modules skip it
        self.emit_entry_points = emit_entry_points  # False for imported modules; suppress main/_gimple_main
        self.module_name = module_name  # used to name _{module_name}_toplevel
        self.func_return_types: dict[str, str] = {}
        self.struct_field_types: dict[str, dict[str, str]] = {}
        # struct name → {alias_name: value AST}; expanded at member access.
        self._struct_comptime_aliases: dict[str, dict] = {}
        # Bare names of user free functions whose C symbol is overload-mangled by
        # parameter types (so same-named functions in different modules don't
        # collide at link). Populated for local defs and imported Mojo functions;
        # every emission site routes the name through _func_csym for consistency.
        self._mangled_funcs: set[str] = set()
        self.imported_symbols: dict[str, tuple] = {}  # symbol_name -> (module, orig_name, type)
        self._all_closures: dict = {}   # populated by gen_module pre-pass
        self._lambda_outer_closures: dict = {}  # set during lambda body codegen
        self._ptr_helpers_needed: set[str] = set()   # elem C types needing _mojo_at_ helpers
        self._emitted_ptr_helpers: set[str] = set()  # elem C types already emitted (shared)
        self.func_param_types: dict[str, list[str]] = {}  # func_name → [param_ctype, ...]
        self._global_inline_defs: set[str] = set()   # all func names with inline definitions (shared)
        self._struct_allocs_needed: set[str] = set() # struct names needing _alloc_ helpers
        self._emitted_allocs: set[str] = set()       # struct names for which _alloc_ was already emitted
        self._compiled_modules: set[str] = set()     # modules already compiled to avoid duplicates
        self._module_stmts: dict[str, list] = {}    # module_name → parsed stmts (shared across all gens)
        self._emitted_structs: set[str] = set()      # struct names already emitted (dedup across modules)
        self._str_pool: dict[str, str] = {}          # escaped string → _slit_N (shared across imports)
        self._struct_has_init: set[str] = set()      # structs that have __init__ methods
        self._static_methods: set[str] = set()       # mangled names of @staticmethod methods
        self._struct_init_params: dict[str, list[str]] = {}  # struct -> __init__ param names (excl self)
        self._actual_types: dict[str, str] = {}      # var_name -> actual type (for int64_t-stored pointers)
        self._sub_toplevels: list[str] = []  # ordered list of sub-module toplevel fn names (shared)
        self._has_toplevel_code: bool = False  # set per-module; whether root has top-level statements
        self._module_globals: dict[str, list[tuple[str, str, str]]] = {}  # module_name -> [(name, c_type, mojo_type), ...] (shared)
        self._module_global_inits: dict[str, dict[str, str]] = {}  # module_name -> {name -> init_code} (shared)
        self._global_to_module: dict[str, str] = {}  # global_name -> module_name (shared)
        self._current_module_ctx: str = ""  # current module name for global field access
        self._global_var_types: dict[str, str] = {}  # module-level global name -> C type (persists across functions)
        self._global_c_decl_types: dict[str, str] = {}  # global name -> actual C declaration type (int64_t or pointer)
        # Phase C: Dispatch solver for static dispatch table planning
        self._dispatch_solver: DispatchSolver | None = None  # Instantiated in gen_module Phase 1.5
        self._dispatch_tables: dict = {}  # dispatch_table_name → DispatchTable (from _dispatch_solver)
        self._emitted_dispatch_typedefs: set[str] = set()  # Track typedef names already emitted
        self._emitted_dispatch_tables: set[str] = set()    # Track table names already emitted
        self._funcptr_builtins_needed: set[str] = set()    # builtin C names needing static void* vars
        self._auto_stubbed: set[str] = set()               # function names auto-stubbed in _emit_call
        self._current_filename: str = ""  # filename for #line directives
        self._emitted_line_pairs: set[tuple[str, int]] = set()  # (filename, line) pairs already emitted
        # external_call["name", Ret](args) targets → (ret_ctype, [arg_ctypes]); first use wins.
        # Shared across imported modules so the root preamble can emit one extern proto each.
        self._external_protos: dict[str, tuple[str, list[str]]] = {}
        # Track method overloads: {struct_name.method_name} → [(param_count, param_types), ...]
        # Used to assign unique IDs to each overload in C code generation
        self._method_signatures: dict[str, list[tuple[int, tuple]]] = {}
        # Link mode (MODULE_CACHE_DESIGN.md stage 1): emit `extern` decls for
        # imported symbols instead of inlining their bodies; the bodies come from a
        # separately-built artifact (object / stdlib dylib). Off by default so the
        # existing inline `do_imports` path and all suites are unaffected.
        self.link_imports: bool = link_imports
        self._link_import_decl_list: list = []
        # Dylibs the program must link, recorded by `import` as it resolves each
        # module to its dylib (the loader binds the symbols at load). Deduped.
        self._link_dylibs: list = []
        # Object files the program must link, recorded by elaboration as it
        # instantiates generics on demand (ELABORATION.md). Deduped.
        self._link_objects: list = []
        # Imported names that are generic templates (not concrete exports):
        # name -> the module source path, used to instantiate at call sites.
        self._imported_generics: dict = {}
        # Imported function name -> module source path, for comptime evaluation
        # (run the function at compile time via comptime.evaluate; slice 3).
        self._imported_fn_sources: dict = {}
        # Concrete imported structs used as parameter types here: their StructDefs
        # (so the layout typedef is emitted in dylib mode) and their names (so only
        # these — not local structs — get the authoritative struct-pointer param
        # typing, keeping the blast radius tight).
        self._imported_typedef_structs: list = []
        self._imported_struct_names: set = set()
        # module name -> (path, source_text, parsed stmts), parsed once.
        self._imported_src_cache: dict = {}
        # Imported generic struct name -> module source path (slice 5).
        self._imported_generic_structs: dict = {}
        # Imported overloaded function name -> module source path (slice 4).
        self._imported_overloads: dict = {}
        # typedefs for elaborated (monomorphized) structs, emitted in the preamble.
        self._elaborated_typedefs: list = []
        # extern decls for symbols elaboration produced at call sites (generic
        # instantiations); emitted in the preamble like import extern decls.
        self._elaborated_externs: list = []
        # Lambda lifting: anonymous functions generated on-the-fly from LambdaExpr.
        # These are accumulated during gen_func and flushed into func_parts by
        # gen_module after the surrounding function body is emitted.
        self._lambda_counter: int = 0
        self._lambda_parts: list[str] = []   # lifted C function bodies, in emission order
        self._reset_func()

    def _reset_func(self):
        self.bb_counter   = 2
        self.temp_counter = 0
        self.decls:       list[str]         = []
        self.body_lines:  list[str]         = []
        self.var_types:   dict[str, str]    = {}
        self.loop_stack:  list[tuple[str,str]] = []
        self.exc_depth    = 0
        self.func_ret_type: str             = ''
        self._last_was_terminal: bool       = False
        # Container / layout state
        self._elem_types:      dict[str, str]   = {}  # container var → element C type
        self._nested_elem_types: dict[str, str] = {}  # container var → element type of lists within lists
        # Actual type of int64_t-boxed pointers, keyed by temp/var name. MUST reset
        # per function: temp names (_tN) recycle, so a stale entry from one function
        # would mis-type a same-named temp in the next (e.g. an open() file handle
        # read as a leftover MojoSet*, emitting MojoSet_read).
        self._actual_types:    dict[str, str]   = {}
        # Pre-seed known global dicts with their value types so .get() uses the right function.
        self._dict_val_types:  dict[str, str]   = {
            '_BIN_OPS': 'char *', '_GD_BIN_OPS': 'char *',
        }  # dict var → value C type
        self._struct_layout:   dict[str, str]   = {}  # var_name → STACK|HEAP
        self._layout_hint:  str             = LayoutSolver.HEAP  # for struct constructors
        self.current_func_name: str         = ''
        self._loop_depth:   int             = 0   # nesting depth for freq annotations
        # Closure state (set when generating a lifted inner function)
        self._captures:   dict[str, str]    = {}  # captured var → ctype
        self._env_param:  str               = ''  # name of env pointer ('_env')
        # Active env pointers for this outer function (inner_name → env_var)
        self._closure_envs: dict[str, str]  = {}
        # Original inner function name for recursive call detection (set in _gen_lifted_closure)
        self._inner_func_name: str          = ''
        # C keyword renaming: Python name → C name (for vars that clash with C keywords)
        self._c_names:    dict[str, str]    = {}
        # Names declared `global` inside this function — reads/writes route to module struct
        self._func_declared_globals: set    = set()

    def _compile_imported_module(self, module_name: str) -> tuple:
        """Find and compile an imported .mojo module, extracting type information.

        Returns (code: str, stmts: list) where stmts are parsed statements from the module.
        """
        # Get the directory where gimple_codegen.py is located
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Look for module relative to script location.
        # Try .py first (the working Python reference implementations),
        # then .mojo (self-hosting versions).  Skip the mojo/ subdirectory
        # (those .mojo files are stale and use syntax the parser can't handle).
        extensions = ['.py', '.mojo']
        mojo_paths = []
        for ext in extensions:
            mojo_paths += [
                os.path.join(script_dir, f"{module_name}{ext}"),
                f"./{module_name}{ext}",
                f"../{module_name}{ext}",
            ]

        # Cross the import/module boundary into the real stdlib: resolve std.* modules
        # to their .mojo source under STDLIB_PATH so we walk into (and compile) the
        # actual library implementation rather than relying on a runtime/*.c stub.
        if module_name.startswith('std.') or module_name == 'std':
            try:
                from module_loader import ModuleLoader
                stdlib_file = ModuleLoader().resolve_module_path(module_name)
                if stdlib_file and os.path.exists(stdlib_file):
                    mojo_paths.append(stdlib_file)
            except Exception as e:
                _debug_note(f'stdlib path resolution failed for {module_name!r}', e)

        for path in mojo_paths:
            if os.path.exists(path):
                modules_before = set(self._compiled_modules)
                ptr_helpers_before = set(self._emitted_ptr_helpers)
                emitted_structs_before = set(self._emitted_structs)
                inline_defs_before = set(self._global_inline_defs)
                emitted_allocs_before = set(self._emitted_allocs)
                try:
                    with open(path, 'r') as f:
                        source = f.read()

                    # Compile the module to get both code and type info
                    tokens = tokenize(source)
                    stmts = Parser(tokens).parse_module()

                    # Create a temporary codegen to extract types
                    # Use do_imports=True for transitive closure; share dedup sets and type information
                    # emit_str_pool=False so only main module emits the shared string pool
                    # emit_struct_defs=False so only main module emits struct typedefs
                    # emit_entry_points=False so imported module doesn't emit main/_gimple_main
                    temp_gen = GimpleGen(do_imports=True, emit_str_pool=False, emit_struct_defs=False,
                                         emit_entry_points=False, module_name=module_name)
                    temp_gen._current_filename = path  # Set filename for #line directives
                    temp_gen._compiled_modules = self._compiled_modules
                    temp_gen._emitted_structs = self._emitted_structs
                    temp_gen._str_pool = self._str_pool
                    temp_gen.struct_field_types = self.struct_field_types
                    temp_gen._global_var_types = self._global_var_types
                    temp_gen._global_c_decl_types = self._global_c_decl_types
                    temp_gen._emitted_ptr_helpers = self._emitted_ptr_helpers
                    temp_gen._external_protos = self._external_protos  # share: bubble extern protos up to root preamble
                    temp_gen._global_inline_defs = self._global_inline_defs
                    temp_gen._emitted_allocs = self._emitted_allocs
                    temp_gen._module_stmts = self._module_stmts  # share: track all transitive stmts
                    temp_gen.func_return_types = self.func_return_types  # share across gens
                    temp_gen._sub_toplevels = self._sub_toplevels  # share the ordered list of sub-toplevels
                    temp_gen._module_globals = self._module_globals  # share module globals tracking
                    temp_gen._module_global_inits = self._module_global_inits  # share global inits
                    if hasattr(self, '_global_to_module'):
                        temp_gen._global_to_module = self._global_to_module  # share global -> module mapping
                    code = temp_gen.gen_module(stmts)

                    # Store parsed stmts for this module so parent gens can access them
                    self._module_stmts[module_name] = stmts

                    # Return both code and parsed statements
                    return (code, stmts)
                except Exception as e:
                    __import__('sys').stderr.write(f"# ERROR: compiling imported module {module_name!r} from {path}: {e}\n")
                    # Rollback: remove any modules/helpers/structs added during this failed
                    # compilation so the outer module can re-compile them and include their code.
                    for _m in list(self._compiled_modules - modules_before):
                        self._compiled_modules.discard(_m)
                    for _h in list(self._emitted_ptr_helpers - ptr_helpers_before):
                        self._emitted_ptr_helpers.discard(_h)
                    for _s in list(self._emitted_structs - emitted_structs_before):
                        self._emitted_structs.discard(_s)
                    for _d in list(self._global_inline_defs - inline_defs_before):
                        self._global_inline_defs.discard(_d)
                    for _a in list(self._emitted_allocs - emitted_allocs_before):
                        self._emitted_allocs.discard(_a)
                    # Note: _module_globals / _module_global_inits are intentionally NOT
                    # rolled back. Partial data from a failed compilation (e.g. build_stdlib_dylib
                    # failing but having populated its globals) is still needed so that the
                    # module's globals struct typedef can be emitted for callers that reference it.
                    continue

        # Module not found (e.g. stdlib module like sys, os)
        return (None, [])

    def _emit_stdlib_import_externs(self, stmts) -> None:
        """Scan from-import stmts and emit extern declarations for concrete
        functions found via load_module (text-only extraction — no dylib builds,
        no recursion). Populates _link_import_decl_list and registers types so
        call sites lower correctly. Safe to call for any module; no-ops if a
        symbol is already registered."""
        seen = set(self.func_return_types.keys()) | set(self.imported_symbols.keys())

        # Determine the package prefix for resolving relative imports (e.g.
        # `._swisstable` → `std.collections._swisstable` when compiling
        # `std/collections/dict.mojo`).
        _pkg_prefix = ''
        if self._current_filename:
            import os as _os
            from module_loader import STDLIB_PATH
            rel = _os.path.relpath(self._current_filename, STDLIB_PATH)
            if not rel.startswith('..'):
                parts = rel.replace(_os.sep, '/').split('/')
                if len(parts) > 1:
                    _pkg_prefix = '.'.join(parts[:-1]) + '.'

        # Names that conflict with GCC built-ins or C stdlib declarations — skip
        # emitting externs for these even if load_module finds them.
        _C_BUILTINS = frozenset({
            'abort', 'atof', 'atoi', 'atol', 'atoll', 'exit', '_exit',
            'fclose', 'fopen', 'fread', 'fwrite', 'fseek', 'ftell', 'fflush',
            'fma', 'fmaf', 'pow', 'powf', 'sqrt', 'sqrtf',
            'sin', 'sinf', 'cos', 'cosf', 'tan', 'tanf',
            'exp', 'expf', 'log', 'logf', 'log2', 'log2f', 'log10', 'log10f',
            'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf',
            'fabs', 'fabsf', 'fmod', 'fmodf',
            'malloc', 'free', 'realloc', 'calloc',
            'pclose', 'popen', 'dlclose', 'dlopen', 'dlsym', 'dlerror',
            'printf', 'fprintf', 'sprintf', 'snprintf', 'scanf', 'sscanf',
            'strlen', 'strcpy', 'strncpy', 'strcmp', 'strncmp',
            'strcat', 'strncat', 'strstr', 'strchr', 'strrchr',
            'memcpy', 'memmove', 'memset', 'memcmp',
            'stat', 'lstat', 'fstat', 'open', 'close', 'read', 'write',
            'max', 'min', 'chr', 'ord',
            'fdopen', 'fileno', 'tmpfile', 'tmpnam',
            'getenv', 'setenv', 'unsetenv', 'putenv',
            'isatty', 'getuid', 'getpid', 'getppid',
            # Linux-specific libc wrappers that collide with GCC declarations
            'get_errno', 'set_errno', '_getpw_linux', '_lstat_linux_x86_64',
            '_stat_linux_x86_64', '_fstat_linux_x86_64',
        })

        def _resolve_relative(mod, pkg_prefix):
            """Resolve relative import: count leading dots, go up that many levels."""
            if not mod.startswith('.'):
                return mod
            dots = len(mod) - len(mod.lstrip('.'))
            rest = mod.lstrip('.')
            parts = pkg_prefix.rstrip('.').split('.')
            # dots=1 → current package (no level up), dots=2 → parent, etc.
            up = dots - 1
            if up > 0:
                parts = parts[:-up] if up < len(parts) else []
            base = '.'.join(parts)
            return (base + '.' + rest) if (base and rest) else (base or rest)

        for stmt in stmts:
            if not isinstance(stmt, FromImportStmt):
                continue
            mod = stmt.module
            # Resolve relative imports: '._foo' → 'std.pkg._foo', '.._foo' → 'std.parent._foo'
            if mod.startswith('.'):
                mod = _resolve_relative(mod, _pkg_prefix)
            try:
                exports = load_module(mod)
            except Exception as e:
                _debug_note(f'load_module({mod!r}) failed; skipping import', e)
                continue
            if not exports:
                continue
            for name, alias in stmt.names:
                sym = alias if alias else name
                if sym in seen or sym in _C_BUILTINS:
                    continue
                info = exports.get(name)
                if not info:
                    continue
                sig = info.get('signature')
                if not sig:
                    continue
                ret = info.get('c_return_type', 'int64_t')
                c_params = info.get('c_parameters') or []
                ptypes = [' '.join(cp.split()[:-1]) if len(cp.split()) > 1 else cp
                          for cp in c_params]
                self.func_return_types[sym] = ret
                self.func_param_types[sym] = ptypes
                self.imported_symbols[sym] = {
                    'module': mod, 'original_name': name,
                    'c_return_type': ret, 'signature': sig,
                }
                # When imported with an alias, replace the original name in the sig
                # so the extern matches the alias name used at call sites.
                if alias and name != alias:
                    sig = re.sub(r'\b' + re.escape(name) + r'\b', alias, sig, count=1)
                # Overload-mangle the imported function's name in the extern so it
                # matches the (mangled) call sites and the defining module's symbol.
                # Only for genuinely mangled functions — reserved renames (pipe →
                # mojo_pipe) are handled by other decl paths and must not change here.
                if self._func_mangleable(sym):
                    _csym = self._func_csym(sym)
                    if _csym != sym:
                        sig = re.sub(r'\b' + re.escape(sym) + r'\b', _csym, sig, count=1)
                # Guard the extern with #ifndef so the pre-defined stubs (which use
                # the same guard macro _MOJO_STUB_<NAME>) don't produce a second
                # conflicting declaration. If the extern is emitted here, the stub
                # will see the macro already defined and skip itself.
                guard = f'_MOJO_STUB_{sym.upper()}'
                decl = f'#ifndef {guard}\n#define {guard}\nextern {sig};\n#endif'
                self._link_import_decl_list.append(decl)
                seen.add(sym)

    def _register_link_imports(self, stmts) -> list:
        """Link mode (MODULE_CACHE_DESIGN.md): `import` is the seam. For each
        imported symbol, resolve its signature from the module's dylib
        `__mojo_reflect` ABI (imports.import_exports → read_reflection), register
        its return/param C types (so call sites lower correctly), and emit the
        `extern` declaration. Bodies are NOT inlined — they live in the linked
        dylib. Falls back to module_loader's source-level extraction when no dylib
        is available. Scans top-level and nested imports.
        """
        decls: list[str] = []
        seen: set[str] = set()

        def _param_ctypes(c_parameters):
            # c_parameters are like ["int64_t a", "char * s"]; keep the type only.
            out = []
            for cp in c_parameters or []:
                toks = cp.split()
                out.append(' '.join(toks[:-1]) if len(toks) > 1 else cp)
            return out

        def _parse_c_sig(sig):
            # "int64_t name (int64_t, char *)" -> ('int64_t', ['int64_t', 'char *'])
            head, _, rest = sig.partition('(')
            params = rest.rstrip(') ').strip()
            toks = head.strip().rsplit(None, 1)        # split off the function name
            ret = toks[0] if len(toks) == 2 else 'int'
            if not params or params == 'void':
                ptypes = []
            else:
                ptypes = [p.strip() for p in params.split(',')]
            return ret, ptypes

        def _exports(module):
            # `import` resolves the module's dylib, records it on the program's
            # link line (so the program links every dylib its imports resolved
            # through — the loader binds the symbols), and returns the reflection
            # ABI. Falls back to source-level extraction if no dylib is available.
            try:
                import imports as _imp
                entry = _imp.resolve(module)   # the one authoritative module per name
                if entry.dylib:
                    if entry.exports and entry.dylib not in self._link_dylibs:
                        self._link_dylibs.append(entry.dylib)
                    return entry.exports, True, entry.source
            except Exception as e:
                _debug_note(f'imports.resolve({module!r}) failed; falling back to load_module', e)
            try:
                return load_module(module), False, None
            except Exception as e:
                _debug_note(f'load_module({module!r}) failed; treating module as empty', e)
                return {}, False, None

        def scan(stmt_list):
            for stmt in stmt_list:
                if isinstance(stmt, FromImportStmt):
                    exports, from_reflection, source = _exports(stmt.module)
                    for name, alias in stmt.names:
                        info = exports.get(name)
                        sym = alias if alias else name
                        # Record the module source for any imported name, so a
                        # comptime call to it can be evaluated at compile time.
                        if source:
                            self._imported_fn_sources.setdefault(name, source)
                        if not info:
                            # Not a concrete export — if the module source defines
                            # it as a generic (struct or fn), record it for
                            # on-demand elaboration at use sites.
                            if source:
                                try:
                                    msrc = open(source).read()
                                except Exception as e:
                                    _debug_note(f'cannot read module source {source!r}', e)
                                    msrc = ''
                                if re.search(rf'\bstruct\s+{re.escape(name)}\s*\[', msrc):
                                    self._imported_generic_structs.setdefault(sym, source)
                                elif re.search(rf'\b(?:fn|def)\s+{re.escape(name)}\s*\[', msrc):
                                    self._imported_generics.setdefault(sym, source)
                                elif len(re.findall(rf'\b(?:fn|def)\s+{re.escape(name)}\s*\(', msrc)) > 1:
                                    self._imported_overloads.setdefault(sym, source)
                            continue
                        if sym in seen:
                            continue
                        # A concrete struct TYPE import (kind 3, MOJO_SYM_TYPE):
                        # materialize its layout from the reflection table and
                        # register its methods (kind 1) as externs. This is the
                        # real-stdlib distribution path — the type + method bodies
                        # live in the compiled dylib; the client sees only the
                        # layout + extern method symbols (not inlined source).
                        if from_reflection and info.get('kind') == 3:
                            seen.add(sym)
                            self._register_reflected_struct(
                                sym, info, exports, _parse_c_sig)
                            continue
                        sig = info.get('signature')
                        if not sig:
                            continue
                        seen.add(sym)
                        if from_reflection:
                            ret, ptypes = _parse_c_sig(sig)
                        else:
                            ret = info.get('c_return_type', 'int64_t')
                            ptypes = _param_ctypes(info.get('c_parameters'))
                        self.func_return_types[sym] = ret
                        self.func_param_types[sym] = ptypes
                        # Don't emit extern if: (a) locally defined in this module
                        # (would conflict), or (b) it's a C stdlib symbol GCC already
                        # declares (conflicting types when Mojo stub has different sig).
                        _locally_defined = sym in self._global_inline_defs
                        _is_c_builtin = sym in self._LIBC_DECLARED
                        if not _is_c_builtin:
                            # This imported Mojo function is overload-mangled by the
                            # defining module; the importer must mangle calls + its
                            # extern identically. Same param types (from the exported
                            # signature) ⇒ same suffix as the definition.
                            self._mangled_funcs.add(sym)
                        if not _locally_defined and not _is_c_builtin:
                            _csym = self._func_csym(sym)
                            decls.append(
                                f"extern {ret} {_csym} ({', '.join(ptypes) if ptypes else 'void'});")
                elif isinstance(stmt, FunctionDef):
                    scan(stmt.body)
                elif isinstance(stmt, IfStmt):
                    scan(stmt.then_body)
                    for _, eb in stmt.elifs:
                        scan(eb)
                    if stmt.else_body:
                        scan(stmt.else_body)
                elif isinstance(stmt, (WhileStmt, ForStmt, TryStmt)):
                    scan(stmt.body)

        scan(stmts)
        return decls

    def _register_reflected_struct(self, name, type_info, exports, parse_c_sig):
        """Materialize a concrete struct imported from a dylib's reflection table.

        `type_info` is the MOJO_SYM_TYPE entry (signature = a layout descriptor
        `struct Name { ctype field; ... }`); `exports` is the full reflection
        dict, from which we pick the struct's MOJO_SYM_METHOD entries
        (`Name.method`). We register the layout (so the typedef is emitted),
        declare each method extern, and record their return/param C types so call
        sites lower to the dylib's symbols. This is the import path a real,
        already-compiled stdlib type takes: only layout + externs cross the
        boundary — the bodies are linked from the dylib (see ABI.md, ELABORATION.md
        which complements this with the from-source generic-struct path)."""
        # Parse the layout descriptor into {field: ctype}, preserving order.
        sig = type_info.get('signature', '')
        fields: dict[str, str] = {}
        inner = sig.split('{', 1)[1].rsplit('}', 1)[0] if '{' in sig else ''
        for decl in inner.split(';'):
            decl = decl.strip()
            if not decl:
                continue
            parts = decl.rsplit(' ', 1)
            if len(parts) == 2:
                ctype, fname = parts[0].strip(), parts[1].strip()
                fields[fname] = ctype
        if not self.struct_field_types.get(name):
            self.struct_field_types[name] = fields
        # Register each method (kind 1) belonging to this struct.
        for ename, einfo in exports.items():
            if einfo.get('kind') != 1 or not ename.startswith(name + '.'):
                continue
            msig = einfo.get('signature', '')
            if not msig:
                continue
            mret, mptypes = parse_c_sig(msig)
            # The C symbol is the function name inside the signature.
            msym = msig.split('(', 1)[0].strip().split()[-1].lstrip('*')
            self.func_return_types[msym] = mret
            self.func_param_types[msym] = mptypes
            if msym == f"{name}___init__":
                self._struct_has_init.add(name)
                # The C signature gives no param names; record positional
                # placeholders so a kwarg ctor binds by source order (below).
                self._struct_init_params.setdefault(name, [])
            decl = f'extern {msig};'
            if decl not in self._elaborated_externs:
                self._elaborated_externs.append(decl)

    def _new_bb(self) -> str:
        self.bb_counter += 1
        return f"bb_{self.bb_counter}"

    def _new_temp(self, ctype: str) -> str:
        self.temp_counter += 1
        name = f"_t{self.temp_counter}"
        self.decls.append(f"  {ctype} {name};")
        self.var_types[name] = ctype
        return name

    def _new_val(self, ctype: str, rhs: str) -> str:
        """Alloc a GIMPLE temp, emit `t = rhs`, return t."""
        t = self._new_temp(ctype)
        # GIMPLE strict mode: integer constants are type 'int'; assigning to int64_t
        # without an explicit cast is a 'non-trivial conversion in integer_cst' error.
        if ctype == 'int64_t' and rhs.lstrip('-').isdigit():
            self._emit(f'  {t} = (int64_t){rhs};')
        else:
            self._emit(f'  {t} = {rhs};')
        return t

    def _call_expr(self, ret_type: str, fname: str, arg_pairs: list) -> str:
        """Emit a call and return the result temp."""
        t = self._new_temp(ret_type)
        self._emit_call(ret_type, t, fname, arg_pairs)
        return t

    def _void_call(self, fname: str, arg_pairs: list) -> tuple:
        """Emit a void call, return ('int', zero_temp)."""
        self._emit_call('void', '', fname, arg_pairs)
        return 'int', self._new_val('int', '0')

    def _emit(self, line: str):
        self.body_lines.append(line)
        # Track whether this is a terminal statement (can't have code after it)
        stripped = line.strip()
        if stripped.startswith('return ') or stripped.startswith('goto ') or stripped == 'return;':
            self._last_was_terminal = True
        else:
            self._last_was_terminal = False

    def _emit_label(self, label: str, freq_hint: str = ''):
        ann = f'  /* {freq_hint} */' if freq_hint else ''
        self.body_lines.append(f"\n{label}:{ann}")
        self._last_was_terminal = False

    def _type_of(self, name: str) -> str:
        return self.var_types.get(name, 'int64_t')

    def _elem_of(self, name: str) -> str:
        """Element type for a container variable."""
        # First, check if this is an int64_t-stored pointer with tracked element type
        if name in self._elem_types:
            return self._elem_types[name]
        # If no tracked element type, return default
        return 'int64_t'

    def _dict_val_of(self, name: str) -> str:
        """Value C type for a dict variable."""
        return self._dict_val_types.get(name, 'int64_t')

    # Known runtime function signatures: fname -> (ret_type, [arg_types])
    # Used by _emit_call to ensure GIMPLE-valid argument types.
    _KNOWN_SIGS: dict = {
        'conforms_to':           ('_Bool',      ['int64_t', 'int64_t']),
        'llabs':                 ('int64_t',   ['int64_t']),
        'labs':                  ('int64_t',   ['int64_t']),
        'mojo_str_split':        ('MojoList *', ['char *', 'char *']),
        'mojo_str_find':         ('int64_t',   ['char *', 'char *']),
        'mojo_str_cat':          ('char *',    ['char *', 'char *']),
        'mojo_str':              ('char *',    ['void *']),
        'mojo_repr':             ('char *',    ['int']),  # expects int, not void*
        'mojo_print':            ('void',      ['char *']),
        'mojo_open_file':        ('int64_t',   ['char *']),  # Added: returns handle, takes path
        'mojo_close':            ('void',      ['void *']),
        'mojo_write':            ('int64_t',   ['void *', 'char *', 'int64_t']),
        'mojo_read':             ('int64_t',   ['void *', 'char *', 'int64_t']),
        'int64_t_basename':      ('char *',    ['char *']),  # os.path.basename(path)
        'int64_t_splitext':      ('char *',    ['char *']),  # os.path.splitext(path)
        'int64_t_expanduser':    ('char *',    ['char *']),  # os.path.expanduser(path)
        'mojo_make_int':         ('int64_t',    ['char *']),
        'mojo_make_float':       ('double',     ['char *']),
        'mojo_make_bool':        ('int',        ['int']),   # runtime: int mojo_make_bool(int)
        'mojo_list_new':         ('MojoList *', []),
        'mojo_list_append_int':  ('void',      ['MojoList *', 'int64_t']),
        'mojo_list_append_str':  ('void',      ['MojoList *', 'char *']),
        'mojo_list_append_obj':  ('void',      ['MojoList *', 'void *']),
        'mojo_list_get_int':     ('int64_t',   ['MojoList *', 'int64_t']),
        'mojo_list_get_str':     ('char *',    ['MojoList *', 'int64_t']),
        'mojo_list_len':         ('int64_t',   ['MojoList *']),
        'mojo_div_double':       ('double',    ['double', 'double']),
        'mojo_div_float':        ('float',     ['float', 'float']),
        'mojo_str_from_int':     ('char *',    ['int64_t']),
        'mojo_dict_new':         ('MojoDict *', []),
        'mojo_dict_set_str': ('void',      ['MojoDict *', 'char *', 'char *']),
        'mojo_dict_set_int': ('void',      ['MojoDict *', 'char *', 'int64_t']),
        'mojo_dict_get_str':     ('char *',    ['MojoDict *', 'char *']),
        'mojo_dict_get_int':     ('int64_t',   ['MojoDict *', 'char *']),
        'mojo_dict_contains':    ('int',       ['MojoDict *', 'char *']),
        'mojo_set_new':          ('MojoSet *', []),
        'mojo_set_add_str':      ('void',      ['MojoSet *', 'char *']),
        'mojo_set_add_int':      ('void',      ['MojoSet *', 'int64_t']),
        'mojo_set_contains_str': ('int',       ['MojoSet *', 'char *']),
        'mojo_set_contains_int': ('int',       ['MojoSet *', 'int64_t']),
        'mojo_hasattr':          ('int',        ['int', 'char *']),
        'mojo_obj_getattr':      ('int64_t',   ['void *', 'char *']),
        'mojo_getattr':          ('int64_t',   ['void *', 'char *']),
        'mojo_setattr':          ('void',      ['void *', 'char *', 'int64_t']),
        'mojo_re_sub_fn':        ('char *',    ['char *', 'void *', 'void *', 'char *']),
        'mojo_set_union':        ('MojoSet *', ['MojoSet *', 'MojoSet *']),
        'mojo_set_difference':   ('MojoSet *', ['MojoSet *', 'MojoSet *']),
        'mojo_set_discard':      ('void',      ['MojoSet *', 'int64_t']),
        'mojo_str_startswith':   ('int',       ['char *', 'char *']),
        'mojo_str_endswith':     ('int',       ['char *', 'char *']),
        'mojo_str_startswith_char': ('int',    ['char *', 'char']),
        'mojo_str_endswith_char':   ('int',    ['char *', 'char']),
        'strcmp':                ('int',       ['char *', 'char *']),
        'snprintf':              ('int',       ['char *', 'int64_t', 'char *']),
        'strlen':                ('int64_t',   ['char *']),
        'strcat':                ('char *',    ['char *', 'char *']),
        'mojo_str_cat':          ('char *',    ['char *', 'char *']),
        'mojo_str_format':       ('char *',    ['char *']),
        'int_load_module':       ('int',       ['ModuleLoader *', 'char *']),
        'int_get_symbol_type':   ('char *',    ['ModuleLoader *', 'char *', 'char *']),
        'int_import_module':     ('int',       ['int', 'char *']),
        'int_group':             ('char *',    ['char *', 'int']),
        '_scan_for_escaping':    ('void',      ['MojoList *', 'MojoSet *', 'MojoSet *']),
        'int_analyze':           ('int',       ['int', 'int', 'MojoDict *']),
        'int_abspath':           ('int64_t',   ['int64_t', 'int64_t']),
        'int_dirname':           ('int64_t',   ['int64_t', 'int64_t']),
        'int_join':              ('int64_t',   ['int64_t', 'int64_t', 'int64_t']),
        'int_join_list':         ('int64_t',   ['int64_t', 'int64_t']),
        'int_exists':            ('int',       ['int64_t', 'int64_t']),
        'mojo_set_intersection': ('MojoSet *', ['MojoSet *', 'MojoSet *']),
        'mojo_set_update':       ('void',      ['MojoSet *', 'MojoSet *']),
        'mojo_dict_copy':        ('MojoDict *', ['MojoDict *']),
        'mojo_dict_from_pairs':  ('MojoDict *', ['MojoList *']),
        'mojo_dict_update':      ('void',      ['MojoDict *', 'MojoDict *']),
        'mojo_dict_free':        ('void',      ['MojoDict *']),
        'mojo_dict_clear':       ('void',      ['MojoDict *']),
        'mojo_dict_keys':        ('MojoList *', ['MojoDict *']),
        'mojo_dict_values':      ('MojoList *', ['MojoDict *']),
        'mojo_dict_items':       ('MojoList *', ['MojoDict *']),
        'mojo_sorted':           ('MojoList *', ['void *']),
        'mojo_reversed':         ('void *',     ['void *']),
        # POSIX / C stdlib functions with non-int64_t returns (util stubs table)
        'isdir':                 ('int',         ['char *']),
        'isatty':                ('int',         ['int']),
        'getpid':                ('int',         []),
        'getppid':               ('int',         []),
        'getuid':                ('unsigned int', []),
        'getgid':                ('unsigned int', []),
        'sysconf':               ('long',        ['int']),
        'hex':                   ('char *',      ['int64_t']),
        'serialize':             ('void',        []),
        'mojo_enumerate':        ('MojoList *', ['void *']),
        'mojo_zip':              ('void *',     ['void *', 'void *']),
        'mojo_list_all':         ('int',        ['MojoList *']),
        'mojo_list_any':         ('int',        ['MojoList *']),
        'mojo_list_copy':        ('MojoList *', ['MojoList *']),
        'mojo_list_extend':      ('void',       ['MojoList *', 'MojoList *']),
        'mojo_list_pop':         ('int64_t',    ['MojoList *']),
        'mojo_list_clear':       ('void',       ['MojoList *']),
        'mojo_list_reverse':     ('void',       ['MojoList *']),
        'mojo_list_remove_at':   ('void',       ['MojoList *', 'int64_t']),
        'mojo_list_remove_str':  ('void',       ['MojoList *', 'char *']),
        'mojo_list_remove_int':  ('void',       ['MojoList *', 'int64_t']),
        'mojo_list_index_str':   ('int64_t',    ['MojoList *', 'char *']),
        'mojo_list_index_int':   ('int64_t',    ['MojoList *', 'int64_t']),
        'MojoList_index':        ('int64_t',    ['MojoList *', 'int']),
        # Scope methods — name is always char*, value is boxed int
        'Scope_define':          ('void',       ['Scope *', 'char *', 'int']),
        'Scope_get':             ('int',        ['Scope *', 'char *']),
        'Scope_set':             ('void',       ['Scope *', 'char *', 'int']),
        'Scope___init__':        ('void',       ['Scope *', 'Scope *']),
        'tokenize':              ('MojoList *', ['char *']),
        'Parser_parse_module':   ('MojoList *', ['Parser *']),
        'mojo_eval':             ('int',         ['int', 'MojoDict *', 'MojoDict *']),
        'interpret_and_execute': ('void',        ['char *', 'int']),
        # C math functions with non-int64_t return types — temps must be float/double
        'fma':          ('double', ['double', 'double', 'double']),
        'fmaf':         ('float',  ['float', 'float', 'float']),
        'nextafter':    ('double', ['double', 'double']),
        'nextafterf':   ('float',  ['float', 'float']),
        'modf':         ('double', ['double', 'double *']),
        'modff':        ('float',  ['float', 'float *']),
        'frexp':        ('double', ['double', 'int *']),
        'frexpf':       ('float',  ['float', 'int *']),
        'ldexp':        ('double', ['double', 'int']),
        'ldexpf':       ('float',  ['float', 'int']),
        'hypot':        ('double', ['double', 'double']),
        'hypotf':       ('float',  ['float', 'float']),
        'remainder':    ('double', ['double', 'double']),
        'remainderf':   ('float',  ['float', 'float']),
        'copysign':     ('double', ['double', 'double']),
        'copysignf':    ('float',  ['float', 'float']),
        'nan':          ('double', ['char *']),
        'nanf':         ('float',  ['char *']),
        'scalb':        ('double', ['double', 'double']),
        'scalbf':       ('float',  ['float', 'float']),
        'scalbn':       ('double', ['double', 'int']),
        'scalbnf':      ('float',  ['float', 'int']),
        'logb':         ('double', ['double']),
        'logbf':        ('float',  ['float']),
        'j0':           ('double', ['double']),
        'j1':           ('double', ['double']),
        'y0':           ('double', ['double']),
        'y1':           ('double', ['double']),
        # C math — float variants (f-suffix) return float, not double
        'cosf':         ('float',  ['float']),
        'sinf':         ('float',  ['float']),
        'tanf':         ('float',  ['float']),
        'acosf':        ('float',  ['float']),
        'asinf':        ('float',  ['float']),
        'atanf':        ('float',  ['float']),
        'atan2f':       ('float',  ['float', 'float']),
        'ceilf':        ('float',  ['float']),
        'floorf':       ('float',  ['float']),
        'roundf':       ('float',  ['float']),
        'truncf':       ('float',  ['float']),
        'sqrtf':        ('float',  ['float']),
        'cbrtf':        ('float',  ['float']),
        'powf':         ('float',  ['float', 'float']),
        'expf':         ('float',  ['float']),
        'exp2f':        ('float',  ['float']),
        'logf':         ('float',  ['float']),
        'log2f':        ('float',  ['float']),
        'log10f':       ('float',  ['float']),
        'fabsf':        ('float',  ['float']),
        'fmodf':        ('float',  ['float', 'float']),
        'erff':         ('float',  ['float']),
        'erfcf':        ('float',  ['float']),
        'sinhf':        ('float',  ['float']),
        'coshf':        ('float',  ['float']),
        'tanhf':        ('float',  ['float']),
        'asinhf':       ('float',  ['float']),
        'acoshf':       ('float',  ['float']),
        'atanhf':       ('float',  ['float']),
        'cbrtf':        ('float',  ['float']),
        # C math — double variants
        'cos':          ('double', ['double']),
        'sin':          ('double', ['double']),
        'tan':          ('double', ['double']),
        'ceil':         ('double', ['double']),
        'floor':        ('double', ['double']),
        'sqrt':         ('double', ['double']),
        'exp':          ('double', ['double']),
        'log':          ('double', ['double']),
        'pow':          ('double', ['double', 'double']),
        'fabs':         ('double', ['double']),
        'erf':          ('double', ['double']),
        'erfc':         ('double', ['double']),
        'exp2':         ('double', ['double']),
        'log2':         ('double', ['double']),
        'log10':        ('double', ['double']),
        'cbrt':         ('double', ['double']),
        'round':        ('double', ['double']),
        'trunc':        ('double', ['double']),
        'acos':         ('double', ['double']),
        'asin':         ('double', ['double']),
        'atan':         ('double', ['double']),
        'atan2':        ('double', ['double', 'double']),
        'sinh':         ('double', ['double']),
        'cosh':         ('double', ['double']),
        'tanh':         ('double', ['double']),
        'tanhf':        ('float',  ['float']),
        'asinh':        ('double', ['double']),
        'acosh':        ('double', ['double']),
        'atanh':        ('double', ['double']),
        'asinhf':       ('float',  ['float']),
        'acoshf':       ('float',  ['float']),
        'atanhf':       ('float',  ['float']),
        'expm1':        ('double', ['double']),
        'expm1f':       ('float',  ['float']),
        'log1p':        ('double', ['double']),
        'log1pf':       ('float',  ['float']),
        'fmod':         ('double', ['double', 'double']),
        'tgamma':       ('double', ['double']),
        'lgamma':       ('double', ['double']),
        # C string/conversion functions with non-int64_t return
        'atof':         ('double', ['char *']),
        'strtod':       ('double', ['char *', 'char **']),
        'strtof':       ('float',  ['char *', 'char **']),
        # C string functions returning char* or int
        # getenv → always renamed to mojo_getenv (force rename), so no KNOWN_SIG needed
        'realpath':     ('char *', ['char *', 'char *']),
        'strcpy':       ('char *', ['char *', 'char *']),
        'strncpy':      ('char *', ['char *', 'char *', 'int']),
        'strchr':       ('char *', ['char *', 'int']),
        'strrchr':      ('char *', ['char *', 'int']),
        'strstr':       ('char *', ['char *', 'char *']),
        'strtok':       ('char *', ['char *', 'char *']),
        'strdup':       ('char *', ['char *']),
        'strndup':      ('char *', ['char *', 'int64_t']),
        'strerror':     ('char *', ['int']),
        'tmpnam':       ('char *', ['char *']),
        # String functions returning int (not int64_t)
        'strcmp':       ('int', ['char *', 'char *']),
        'strncmp':      ('int', ['char *', 'char *', 'int64_t']),
        'memcmp':       ('int', ['void *', 'void *', 'int64_t']),
        'snprintf':     ('int', ['char *', 'int64_t', 'char *']),
        'printf':       ('int', ['char *']),
        'fprintf':      ('int', ['void *', 'char *']),
        'sprintf':      ('int', ['char *', 'char *']),
        'fputs':        ('int', ['char *', 'void *']),
        'fputc':        ('int', ['int', 'void *']),
        'putchar':      ('int', ['int']),
        'fgetc':        ('int', ['void *']),
        'getchar':      ('int', []),
        'feof':         ('int', ['void *']),
        'ferror':       ('int', ['void *']),
        'fclose':       ('int', ['void *']),
        'fflush':       ('int', ['void *']),
        'fseek':        ('int', ['void *', 'int64_t', 'int']),
        'ftell':        ('int64_t', ['void *']),
        'remove':       ('int', ['char *']),
        'rename':       ('int', ['char *', 'char *']),
        'access':       ('int', ['char *', 'int']),
        # I/O functions returning pointers
        'popen':        ('void *', ['char *', 'char *']),
        'fdopen':       ('void *', ['int', 'char *']),
        'fopen':        ('void *', ['char *', 'char *']),
        'tmpfile':      ('void *', []),
        'fgets':        ('char *', ['char *', 'int', 'void *']),
        # void-returning functions (calling with result assignment is an error)
        'int64_t_init_pointee_move': ('void', []),
        'int64_t_init_pointee_copy': ('void', []),
        'int64_t_destroy_pointee':   ('void', []),
        # Memory functions returning pointer
        'malloc':       ('void *', ['int64_t']),
        'calloc':       ('void *', ['int64_t', 'int64_t']),
        'realloc':      ('void *', ['void *', 'int64_t']),
        'memcpy':       ('void *', ['void *', 'void *', 'int64_t']),
        'memmove':      ('void *', ['void *', 'void *', 'int64_t']),
        'memchr':       ('void *', ['void *', 'int', 'int64_t']),
        # getdelim/getline take char**+size_t* — use _mojo_* wrappers that accept void*
        '_mojo_getdelim': ('int64_t', ['void *', 'void *', 'int', 'void *']),
        '_mojo_getline':  ('int64_t', ['void *', 'void *', 'void *']),
        # vprintf takes (char*, va_list) — wrap to avoid va_list in GIMPLE
        '_mojo_vprintf':  ('int', ['char *', 'void *']),
        # mojo_memcpy: UnsafePointer params lower to int64_t (byte-based _memcpy_impl)
        'mojo_memcpy':  ('void', ['int64_t', 'int64_t', 'int64_t']),
        # mojo_memmove: UnsafePointer params lower to int64_t* (element-based memmove)
        'mojo_memmove': ('void', ['int64_t *', 'int64_t *', 'int64_t']),
        # char_replace is a macro in mojo_runtime.h — suppress conflicting stub declaration
        'char_replace':  ('int64_t', ['int64_t', 'int64_t', 'int64_t']),
        # id() is emitted as a static helper in _MOJO_UNIMPL_STUBS — suppress variadic stub
        'id':            ('int64_t', ['int64_t']),
    }

    # Rename these C stdlib functions to mojo_* wrappers at call sites.
    _CALL_RENAMES = {
        'getdelim': '_mojo_getdelim',
        'getline':  '_mojo_getline',
        'vprintf':  '_mojo_vprintf',
    }

    def _emit_call(self, ret_type: str, result_var: str, fname: str, arg_pairs: list) -> None:
        """Emit a function call with GIMPLE-valid argument coercions.

        arg_pairs: list of (ctype, varname) for each argument.
        For each argument, if the declared parameter type differs from the
        passed type, emit an intermediate temp with the correct cast.
        """
        # Rename certain C library functions to mojo_* wrappers with void* params
        fname = self._CALL_RENAMES.get(fname, fname)
        sig = self._KNOWN_SIGS.get(fname)
        if sig:
            param_types = sig[1]
        elif fname in self._LIBC_SIGS:
            # Raw libc symbol (e.g. pclose): the canonical C signature wins over
            # func_param_types, which a same-named Mojo wrapper may have polluted.
            param_types = self._LIBC_SIGS[fname][1]
        else:
            param_types = self.func_param_types.get(fname, [])


        # If function takes *args, pack variadic args into a MojoList*
        # '...' = free function varargs (pack all args)
        # [type, '...'] = method varargs (keep leading non-varargs args, pack rest)
        if param_types and param_types[-1] == '...':
            # Find how many leading args to keep (everything before the '...')
            n_fixed = len(param_types) - 1
            fixed_pairs = arg_pairs[:n_fixed]
            varargs = arg_pairs[n_fixed:]
            lst = self._new_val('MojoList *', "mojo_list_new ()")
            for atype, aval in varargs:
                aval = self._coerce_to_type(atype, 'int64_t', aval)
                self._emit(f"  mojo_list_append_int ({lst}, {aval});")
            arg_pairs = fixed_pairs + [('MojoList *', lst)]
            param_types = list(param_types[:-1]) + ['MojoList *']

        coerced_args = []
        for i, (atype, aval) in enumerate(arg_pairs):
            ptype = param_types[i] if i < len(param_types) else atype
            # Check if int64_t actually contains a pointer (stored in _actual_types or _global_var_types)
            actual_atype = atype
            if atype == 'int64_t':
                if aval in self._actual_types:
                    actual_atype = self._actual_types[aval]
                # Also check if it's a global variable that should be cast
                elif aval in self._global_var_types:
                    actual_atype = self._global_var_types[aval]

            # Only pre-load non-slit globals like _BIN_OPS; slits are already char*.
            if aval in ('_BIN_OPS', '_GD_BIN_OPS'):
                temp = self._new_val(atype, f'{aval}')
                aval = temp
            elif aval.startswith('_slit_'):
                # Pointer form (char *): direct load, no cast needed.
                temp = self._new_val('char *', f'{aval}')
                aval = temp
            elif aval.startswith('"') and aval.endswith('"'):
                # Raw C string literal in GIMPLE call — convert to _slit_ variable
                slit_name = self._str_literal_to_slit(aval)
                temp = self._new_val('char *', f'{slit_name}')
                aval = temp
            if ptype == atype or ptype == '...':
                # Skip coercion only if C types match exactly
                coerced_args.append(aval)
            elif ptype == actual_atype and atype != ptype:
                # Semantic types match but C types differ (e.g., int64_t → MojoList *)
                # Still need to cast the underlying C type
                ip3 = self._new_temp('int64_t')
                pp = self._new_temp(ptype)
                aval_local = self._ensure_local('int64_t', aval)
                self._emit(f'  {ip3} = {aval_local};')
                self._emit(f'  {pp} = ({ptype}){ip3};')
                coerced_args.append(pp)
            elif ptype == 'void *' and actual_atype in ('int', 'int64_t', '_Bool'):
                ip = self._new_temp('int64_t')
                vp = self._new_temp('void *')
                if actual_atype == 'int64_t':
                    # GIMPLE: can't cast a global int64_t to int64_t (redundant cast fails)
                    # Just load the value into a local temp directly
                    aval_local = self._ensure_local('int64_t', aval)
                    self._emit(f'  {ip} = {aval_local};')
                else:
                    self._emit(f'  {ip} = (int64_t){aval};')
                self._emit(f'  {vp} = (void *){ip};')
                coerced_args.append(vp)
            elif ptype == 'void *' and actual_atype.endswith(' *'):
                vp = self._new_val('void *', f'(void *){aval}')
                coerced_args.append(vp)
            elif ptype == 'int64_t' and (actual_atype in ('int', '_Bool', 'char *', 'void *') or actual_atype.endswith(' *')):
                ct = self._new_temp('int64_t')
                if atype == 'char *':
                    aval_local = self._ensure_local('char *', aval)
                    ip2 = self._new_val('void *', f'(void *){aval_local}')
                    self._emit(f'  {ct} = (int64_t){ip2};')
                elif atype == 'void *':
                    aval_local = self._ensure_local('void *', aval)
                    self._emit(f'  {ct} = (int64_t){aval_local};')
                elif atype.endswith(' *'):
                    # Any struct pointer → void * → int64_t
                    aval_local = self._ensure_local(atype, aval)
                    vp = self._new_val('void *', f'(void *){aval_local}')
                    self._emit(f'  {ct} = (int64_t){vp};')
                else:
                    self._emit(f'  {ct} = (int64_t){aval};')
                coerced_args.append(ct)
            elif ptype == 'char *' and atype in ('int', 'int64_t', 'char'):
                vp = self._new_temp('void *')
                cp = self._new_temp('char *')
                if atype in ('int', 'char'):
                    ip = self._new_val('int64_t', f'(int64_t){aval}')
                    self._emit(f'  {vp} = (void *){ip};')
                else:
                    self._emit(f'  {vp} = (void *){aval};')
                self._emit(f'  {cp} = (char *){vp};')
                coerced_args.append(cp)
            elif ptype.endswith(' *') and (actual_atype in ('int', 'int64_t') or atype == 'int64_t'):
                # If parameter expects pointer and we have int/int64_t, cast through void*
                # This handles cases where int64_t is an opaque pointer (e.g., from globals)
                ip3 = self._new_temp('int64_t')
                pp = self._new_temp(ptype)
                if actual_atype == 'int64_t' or atype == 'int64_t':
                    # GIMPLE: can't redundantly cast int64_t to int64_t when source is global
                    aval_local = self._ensure_local('int64_t', aval)
                    self._emit(f'  {ip3} = {aval_local};')
                else:
                    self._emit(f'  {ip3} = (int64_t){aval};')
                self._emit(f'  {pp} = ({ptype}){ip3};')
                coerced_args.append(pp)
            elif ptype == 'int64_t' and atype.endswith(' *'):
                # pointer passed where int64_t expected — cast via int64_t
                ip = self._new_val('int64_t', f'(int64_t){aval}')
                coerced_args.append(ip)
            elif ptype == 'int' and atype in ('int64_t', '_Bool'):
                ct = self._new_val('int', f'(int){aval}')
                coerced_args.append(ct)
            elif ptype == 'int' and atype.endswith(' *'):
                # char*/pointer passed where int expected — convert via int64_t
                ip = self._new_temp('int64_t')
                it = self._new_temp('int')
                self._emit(f'  {ip} = (int64_t){aval};')
                self._emit(f'  {it} = (int){ip};')
                coerced_args.append(it)
            elif ptype.endswith(' *') and atype == 'int':
                # int passed where pointer expected — convert via int64_t
                ip = self._new_temp('int64_t')
                pp = self._new_temp(ptype)
                self._emit(f'  {ip} = (int64_t){aval};')
                self._emit(f'  {pp} = ({ptype}){ip};')
                coerced_args.append(pp)
            elif ptype == 'char *' and atype == 'void *':
                # void* to char* conversion
                cp = self._new_val('char *', f'(char *){aval}')
                coerced_args.append(cp)
            elif ptype == 'void *' and atype == 'char *':
                # char* to void* conversion
                vp = self._new_val('void *', f'(void *){aval}')
                coerced_args.append(vp)
            elif ptype.endswith(' *') and atype == 'char *':
                # char* passed where other pointer type expected
                ip = self._new_temp('int64_t')
                pp = self._new_temp(ptype)
                self._emit(f'  {ip} = (int64_t){aval};')
                self._emit(f'  {pp} = ({ptype}){ip};')
                coerced_args.append(pp)
            elif ptype == 'ModuleLoader *' and atype in ('int', 'int64_t'):
                # Handle ModuleLoader* type coercions
                ip = self._new_temp('int64_t')
                pp = self._new_temp('ModuleLoader *')
                self._emit(f'  {ip} = (int64_t){aval};')
                self._emit(f'  {pp} = (ModuleLoader *){ip};')
                coerced_args.append(pp)
            elif ptype.endswith(' *') and atype.endswith(' *') and ptype != atype:
                # Two different pointer types (e.g. MojoList * where MojoDict * is
                # declared, or a struct ptr vs Span *): cast via a temp rather than
                # forwarding an un-typed mismatched pointer (review finding #5).
                pp = self._new_val(ptype, f'({ptype}){aval}')
                coerced_args.append(pp)
            elif ptype and ptype != atype:
                ct = self._new_temp(ptype)
                self._safe_coerce_emit(atype, ptype, aval, ct)
                coerced_args.append(ct)
            else:
                coerced_args.append(aval)
        args_str = ', '.join(coerced_args)
        # For imported functions with known C signatures, use the declared return type
        # to avoid "invalid conversion in gimple call" when the caller guessed wrong.
        # Priority: _LIBC_DECLARED _KNOWN_SIGS (C stdlib) > imported_symbols > func_return_types.
        # _KNOWN_SIGS for C stdlib must win because a Mojo fn can shadow a C name (e.g. atan2).
        # But _KNOWN_SIGS may contain stale struct-method entries; only trust it for _LIBC_DECLARED.
        imported_ret = None
        in_libc_known = fname in self._LIBC_DECLARED and fname in self._KNOWN_SIGS
        # A C library symbol's real signature is authoritative; a same-named Mojo
        # wrapper (e.g. `def dlopen(...) -> _CPointer` → int64_t) must not override
        # the caller's C return type. Otherwise the void*-returning libc dlopen gets
        # assigned into an int64_t call temp (int-from-pointer error).
        is_libc = fname in self._LIBC_DECLARED
        if in_libc_known:
            sig_ret = self._KNOWN_SIGS[fname][0]
            if sig_ret != ret_type:
                imported_ret = sig_ret
        if not imported_ret and not is_libc:
            imported_ret = (self.imported_symbols.get(fname) or {}).get('c_return_type')
        # Also check func_return_types (Mojo function return types) for same mismatch,
        # but skip if fname is a known C stdlib function (to avoid Mojo shadow overriding).
        if not imported_ret and not in_libc_known and not is_libc and fname in self.func_return_types:
            fn_ret = self.func_return_types[fname]
            # Never coerce a used value through a 'void' call temp (would emit an
            # illegal `void t; t = f();`). A 'void' entry here is a shadow — e.g. a
            # Mojo wrapper that shares a name with a value-returning libc symbol
            # reached via external_call — so the caller's explicit ret_type wins.
            if fn_ret != ret_type and fn_ret != 'void':
                imported_ret = fn_ret
        if result_var and imported_ret and imported_ret != ret_type:
            call_tmp = self._new_temp(imported_ret)
            self._emit(f'  {call_tmp} = {fname} ({args_str});')
            self._safe_coerce_emit(imported_ret, ret_type, call_tmp, result_var)
        elif result_var:
            self._emit(f'  {result_var} = {fname} ({args_str});')
        else:
            self._emit(f'  {fname} ({args_str});')

    def _strided_data_ptr(self, pt: str, pv: str) -> str:
        """An `int64_t *` to the scalar data for a strided op's pointer operand —
        `self->address` for an UnsafePointer struct, else the raw pointer itself.
        (int→ptr goes through void* in two single casts; GIMPLE rejects a double
        cast in one statement.)"""
        sn = _struct_name_of(pt)
        if sn and 'address' in (self.struct_field_types.get(sn) or {}):
            addr = self._new_val('int64_t', f"{pv}->address")
            vp = self._new_val('void *', f"(void *){addr}")
            return self._new_val('int64_t *', f"(int64_t *){vp}")
        if pt == 'int64_t *':
            return self._ensure_local(pt, pv)
        if pt.endswith(' *'):
            return self._new_val('int64_t *', f"(int64_t *){self._ensure_local(pt, pv)}")
        loc = self._ensure_local('int64_t', pv)
        vp = self._new_val('void *', f"(void *){loc}")
        return self._new_val('int64_t *', f"(int64_t *){vp}")

    def _lower_strided(self, node, store: bool):
        """Scalar (SIMD-width-1) lowering of the strided_load/strided_store
        intrinsics: a plain load/store of the pointer's scalar element. Consistent
        with the codegen's existing SIMD-to-scalar erasure."""
        if store:
            # strided_store(value, ptr, stride, mask)
            _, vv = self.lower_expr(node.args[0])
            pt, pv = self.lower_expr(node.args[1])
            for a in node.args[2:]:
                self.lower_expr(a)
            dp = self._strided_data_ptr(pt, pv)
            self._emit(f"  *{dp} = {vv};")
            return 'int', self._new_val('int', '0')
        # strided_load(ptr, stride, mask)
        pt, pv = self.lower_expr(node.args[0])
        for a in node.args[1:]:
            self.lower_expr(a)
        dp = self._strided_data_ptr(pt, pv)
        return 'int64_t', self._new_val('int64_t', f"*{dp}")

    def _ensure_local(self, ctype: str, val: str) -> str:
        """If val is a global variable (not a local temp or constant), load it into
        a local temp first.  GIMPLE requires all cast/unary operands to be registers."""
        is_local = (val.startswith('_t') or val.startswith('"') or val.startswith("'")
                    or val.lstrip('-').replace('.', '', 1).isdigit())
        if is_local:
            return val
        t = self._new_val(ctype, f'{val}')
        return t

    def _safe_coerce_emit(self, src: str, dst: str, val: str, lhs: str) -> None:
        """Emit `lhs = val` coercing src→dst; routes struct-field LHS and literal RHS
        through register temps as required by GIMPLE."""

        is_field = '->' in lhs
        val_is_literal = val.startswith('"') or val.startswith("'") or (
            val.lstrip('-').replace('.','',1).isdigit())  # All numeric strings including single digits
        needs_temp = is_field

        def _simple_emit(dest, v, s, d):
            # GIMPLE: integer constant assigned to int64_t needs explicit cast
            if s == d:
                if d == 'int64_t' and v.lstrip('-').isdigit():
                    self._emit(f'  {dest} = (int64_t){v};')
                else:
                    self._emit(f'  {dest} = {v};')
            elif s.endswith(' *') and d in ('int', 'int64_t'):
                # Load global into local before casting (GIMPLE restriction)
                v = self._ensure_local(s, v)
                # GIMPLE: non-void pointer → int64_t requires void * intermediate
                if s != 'void *':
                    vp = self._new_val('void *', f'(void *){v}')
                    v = vp
                ip = self._new_val('int64_t', f'(int64_t){v}')
                if d == 'int64_t':
                    self._emit(f'  {dest} = {ip};')
                else:
                    self._emit(f'  {dest} = (int){ip};')
            elif d.endswith(' *') and s in ('int', 'int64_t'):
                v = self._ensure_local(s, v)
                ip = self._new_val('int64_t', f'(int64_t){v}')
                self._emit(f'  {dest} = ({d}){ip};')
            else:
                # GIMPLE: a cast operand must be a local, never a global decl
                # (e.g. a _slit_ string literal). Load it first.
                v = self._ensure_local(s, v)
                self._emit(f'  {dest} = ({d}){v};')

        if needs_temp:
            t = self._new_temp(dst)
            _simple_emit(t, val, src, dst)
            self._emit(f'  {lhs} = {t};')
        else:
            _simple_emit(lhs, val, src, dst)

    def _coerce(self, src: str, dst: str, val: str) -> str:
        return TypeLattice.coerce(src, dst, val)

    def _resolve_type(self, ann: str | None) -> str:
        if ann in self.struct_field_types:
            return f"{ann} *"
        return _mojo_type(ann)

    def _infer_param_types(self, func: FunctionDef) -> dict[str, str]:
        """Infer parameter types from member accesses and function calls in function body.

        If a parameter is accessed with .field, infer it's a struct with that field.
        If a parameter is passed to a known function, infer type from that function.
        """
        inferred = {}

        # Map builtin/common functions to their first parameter type
        BUILTIN_PARAM_TYPES = {
            'open': 'char *',
            'mojo_open_file': 'char *',
            'len': 'int',
            'print': 'char *',
            'str': 'int',
        }

        def analyze_param_usage(nodes: list, param_name: str):
            """Analyze how a parameter is used in a list of statements."""
            accessed_fields = set()
            function_calls = []  # List of (function_name, arg_index)
            is_subscripted = False  # Track if parameter is used with [...]

            def scan_expr(expr):
                """Recursively scan an expression."""
                nonlocal is_subscripted
                if isinstance(expr, SubscriptExpr):
                    # Check if the base (after unwrapping nested subscripts) is the parameter
                    base = expr.obj
                    while isinstance(base, SubscriptExpr):
                        base = base.obj
                    if isinstance(base, IdentExpr) and base.name == param_name:
                        is_subscripted = True
                    scan_expr(expr.obj)
                    scan_expr(expr.index)
                elif isinstance(expr, SliceExpr):
                    # Slicing a param means it is an indexable sequence, same as subscript.
                    if isinstance(expr.obj, IdentExpr) and expr.obj.name == param_name:
                        is_subscripted = True
                    scan_expr(expr.obj)
                    if expr.start is not None: scan_expr(expr.start)
                    if expr.stop is not None: scan_expr(expr.stop)
                elif isinstance(expr, MemberExpr):
                    if isinstance(expr.obj, IdentExpr) and expr.obj.name == param_name:
                        accessed_fields.add(expr.member)
                    scan_expr(expr.obj)
                elif isinstance(expr, BinaryOp):
                    scan_expr(expr.left)
                    scan_expr(expr.right)
                elif isinstance(expr, UnaryOp):
                    scan_expr(expr.operand)
                elif isinstance(expr, CallExpr):
                    # Track which functions this parameter is passed to
                    if isinstance(expr.func, IdentExpr):
                        func_name = expr.func.name
                        for i, arg in enumerate(expr.args):
                            if isinstance(arg, IdentExpr) and arg.name == param_name:
                                function_calls.append((func_name, i))
                    elif isinstance(expr.func, MemberExpr):
                        # Handle re.sub(pattern, fn, src) → src (index 2) is char*
                        if (isinstance(expr.func.obj, IdentExpr)
                                and expr.func.obj.name == 're'
                                and expr.func.member == 'sub'
                                and len(expr.args) >= 3):
                            if isinstance(expr.args[2], IdentExpr) and expr.args[2].name == param_name:
                                function_calls.append(('__re_sub_src', 2))
                    scan_expr(expr.func)
                    for arg in expr.args:
                        scan_expr(arg)

            def scan_nodes(node_list):
                """Recursively scan a list of statements."""
                for node in node_list:
                    if isinstance(node, AssignStmt):
                        scan_expr(node.target)
                        scan_expr(node.value)
                    elif isinstance(node, ExprStmt):
                        scan_expr(node.value)
                    elif isinstance(node, ReturnStmt):
                        if node.value:
                            scan_expr(node.value)
                    elif isinstance(node, IfStmt):
                        scan_nodes(node.then_body)
                        if node.else_body:
                            scan_nodes(node.else_body)
                        for _, elif_body in node.elifs:
                            scan_nodes(elif_body)
                    elif isinstance(node, (WhileStmt, ForStmt)):
                        scan_nodes(node.body)
                        if node.else_body:
                            scan_nodes(node.else_body)
                    elif isinstance(node, WithStmt):
                        # Scan the context expressions (e.g., open(input_file))
                        for item in node.items:
                            scan_expr(item.expr)
                        scan_nodes(node.body)
                    elif isinstance(node, TryStmt):
                        scan_nodes(node.body)
                        if hasattr(node, 'except_clauses'):
                            for _, handler_body in node.except_clauses:
                                scan_nodes(handler_body)
                        if node.finally_body:
                            scan_nodes(node.finally_body)

            scan_nodes(nodes)
            return accessed_fields, function_calls, is_subscripted

        # For each parameter without a type annotation, infer from usage
        for pname, ptype in func.params:
            if ptype is None:
                fields_accessed, function_calls, is_subscripted = analyze_param_usage(func.body, pname)

                # If passed to isinstance() as first arg, it's polymorphic → keep as int64_t
                is_polymorphic = any(
                    fn == 'isinstance' and ai == 0
                    for fn, ai in function_calls
                )
                if is_polymorphic:
                    continue  # leave as int64_t (default for unannotated)

                # If parameter is subscripted, it's indexable (list/dict/etc.)
                # Check this FIRST to override generic function-call inference like len()
                if is_subscripted:
                    inferred[pname] = 'MojoList *'

                # If not subscripted, try to infer from function calls
                elif function_calls:
                    for func_name, arg_index in function_calls:
                        # re.sub src argument (index 2) is always char*
                        if func_name == '__re_sub_src':
                            inferred[pname] = 'char *'
                            break
                        # Infer from known function signatures
                        sig = self._KNOWN_SIGS.get(func_name)
                        if sig is not None and arg_index < len(sig[1]):
                            inferred[pname] = sig[1][arg_index]
                            break
                        # For first argument (index 0) of known functions, use known types
                        if arg_index == 0 and func_name in BUILTIN_PARAM_TYPES:
                            inferred[pname] = BUILTIN_PARAM_TYPES[func_name]
                            break

                # If no type inferred from functions, try from struct member accesses
                # Only infer struct type if exactly one struct matches (avoid ambiguity)
                if pname not in inferred and fields_accessed:
                    matches = [
                        sname for sname, sfields in self.struct_field_types.items()
                        if all(f in sfields for f in fields_accessed)
                    ]
                    if len(matches) == 1:
                        inferred[pname] = f"{matches[0]} *"

        return inferred

    def _declare_var(self, name: str, ctype: str, elem: str | None = None):
        if name not in self.var_types:
            # Strip backtick-quoted Mojo identifiers (e.g. `6bit` → _6bit)
            if name.startswith('`') and name.endswith('`') and len(name) > 2:
                inner = name[1:-1]
                if inner and inner[0].isdigit():
                    inner = '_' + inner
                import re as _re
                c_name = _re.sub(r'[^a-zA-Z0-9_]', '_', inner)
                self._c_names[name] = c_name
                self.decls.append(f"  {ctype} {c_name};")
                self.var_types[name] = ctype
                if elem is not None:
                    self._elem_types[name] = elem
                return
            # Rename C keywords, macro names, and C library functions to avoid conflicts
            if name in _C_PARAM_EXTRA_KEYWORDS or name in _C_MACRO_NAMES:
                c_name = f"_kw_{name}"
            elif name in _C_KEYWORDS:
                c_name = f"_{name}"
            elif name in _C_RESERVED_FUNCS:
                # Local variable shadows a C library function; rename to avoid
                # "invalid call to non-function" when the function is called later
                c_name = f"_var_{name}"
            elif (name in self.imported_symbols
                  and self.imported_symbols[name].get('return_type', 'int64_t') != 'unknown'):
                # Local variable shadows an imported *function* (not a module import) —
                # rename the local so the extern decl and local variable don't conflict.
                # Module imports have return_type='unknown'; functions default to 'int64_t'.
                c_name = f"_local_{name}"
            else:
                c_name = name
            if c_name != name:
                self._c_names[name] = c_name
            self.decls.append(f"  {ctype} {c_name};")
            self.var_types[name] = ctype
        if elem is not None:
            self._elem_types[name] = elem

    def _cname(self, name: str) -> str:
        """Translate a Python variable name to its C name (handles C keyword renaming)."""
        return self._c_names.get(name, name)

    def _write_dest(self, name: str) -> str:
        """Return the C lvalue for a write to variable `name`.
        Inside a closure, captured variables must be written through the env pointer."""
        if name in self._captures and self._env_param:
            return f'{self._env_param}->{name}'
        return self._cname(name)

    def _new_jbp_temp(self) -> str:
        self.temp_counter += 1
        name = f"_jbp{self.temp_counter}"
        self.decls.append(f"  jmp_buf *{name};")
        return name

    # ── Type-inference pre-pass helpers ──────────────────────────────────

    def _quick_type(self, node) -> str:
        """Estimate C type of an expression without emitting code."""
        if isinstance(node, IntLiteral):    return 'int64_t'
        if isinstance(node, FloatLiteral):  return 'double'
        if isinstance(node, BoolLiteral):   return '_Bool'
        if isinstance(node, StringLiteral): return 'char *'
        if isinstance(node, IdentExpr):     return self.var_types.get(node.name, 'int64_t')
        if isinstance(node, BinaryOp):
            if node.op in _CMP_OPS:         return '_Bool'
            lt = self._quick_type(node.left)
            rt = self._quick_type(node.right)
            return TypeLattice.join(lt, rt)
        if isinstance(node, UnaryOp):
            if node.op == 'not': return '_Bool'
            return self._quick_type(node.operand)
        if isinstance(node, TernaryExpr):
            return TypeLattice.join(self._quick_type(node.then_val),
                                    self._quick_type(node.else_val))
        if isinstance(node, CallExpr) and isinstance(node.func, IdentExpr):
            fname: str
            fname = node.func.name
            _BUILTIN_CTORS = {'set': 'MojoSet *', 'dict': 'MojoDict *', 'list': 'MojoList *'}
            if fname in _BUILTIN_CTORS:
                return _BUILTIN_CTORS[fname]
            # Scalar builtins, matching the lowering (float()->double, etc.). Without
            # these, [float(i), ...] infers an int element type and nested float
            # lists silently read/return as int.
            _BUILTIN_SCALARS = {'float': 'double', 'int': 'int64_t', 'str': 'char *',
                                'len': 'int64_t', 'ord': 'int64_t', 'chr': 'char *',
                                'bool': '_Bool'}
            if fname in _BUILTIN_SCALARS:
                return _BUILTIN_SCALARS[fname]
            if fname in self.struct_field_types:
                return f'{fname} *'
            return self.func_return_types.get(fname, 'int64_t')
        if isinstance(node, CallExpr) and isinstance(node.func, MemberExpr):
            # Module method calls: re.sub → char *, str.join → char *, etc.
            if isinstance(node.func.obj, IdentExpr):
                mod: str
                mod = node.func.obj.name
                meth: str
                meth = node.func.member
                if mod == 're' and meth == 'sub':    return 'char *'
                if mod == 're' and meth == 'match':  return 'int'
                if mod == 're' and meth == 'search': return 'int'
                if mod == 'os' and meth in ('getcwd', 'path'): return 'char *'
                if mod == 'sys': return 'int'
                # Try as struct instance method call: resolve receiver type then look up mangled name
                ot = self.var_types.get(mod, '')
                if ot and ot.endswith(' *'):
                    sn = _struct_name_of(ot)
                    mangled = f"{sn}_{meth}"
                    rt = self.func_return_types.get(mangled)
                    if rt:
                        return rt
        if isinstance(node, MemberExpr):
            ot: str
            ot = self._quick_type(node.obj)
            sn: str
            sn = _struct_name_of(ot)
            return self.struct_field_types.get(sn, {}).get(node.member, 'int64_t')
        if isinstance(node, ListExpr):  return 'MojoList *'
        if isinstance(node, DictExpr):  return 'MojoDict *'
        if isinstance(node, SetExpr):   return 'MojoSet *'
        if isinstance(node, TupleExpr): return 'MojoList *'
        # A slice's type is the type of the object being sliced (mirrors _lower_slice:
        # list slice -> list, str slice -> str, plain pointer -> same pointer).
        if isinstance(node, SliceExpr): return self._quick_type(node.obj)
        if isinstance(node, SubscriptExpr):
            # container[idx]: result is the container's element type, read from the
            # same side-tables the subscript lowering uses. Covers nested reads
            # (outer[i][j]) via the container's nested element type.
            obj = node.obj
            if isinstance(obj, IdentExpr):
                e = self._elem_types.get(obj.name)
                if e:
                    return e
            elif isinstance(obj, SubscriptExpr) and isinstance(obj.obj, IdentExpr):
                ne = self._nested_elem_types.get(obj.obj.name)
                if ne:
                    return ne
        return 'int64_t'

    def _collect_return_types(self, stmts: list, acc: list):
        """Collect return-expression C types from all ReturnStmt nodes."""
        for node in stmts:
            if isinstance(node, ReturnStmt):
                acc.append('void' if node.value is None else self._quick_type(node.value))
            elif isinstance(node, IfStmt):
                self._collect_return_types(node.then_body, acc)
                for _, eb in node.elifs:
                    self._collect_return_types(eb, acc)
                if node.else_body:
                    self._collect_return_types(node.else_body, acc)
            elif isinstance(node, (WhileStmt, ForStmt)):
                self._collect_return_types(node.body, acc)
            elif isinstance(node, TryStmt):
                self._collect_return_types(node.body, acc)
                for h in node.handlers:
                    self._collect_return_types(h.body, acc)
                if node.else_body:
                    self._collect_return_types(node.else_body, acc)
                if node.finally_body:
                    self._collect_return_types(node.finally_body, acc)
            elif isinstance(node, WithStmt):
                self._collect_return_types(node.body, acc)

    def _coerce_to_type(self, src_type: str, dst_type: str, value: str) -> str:
        """
        Generic type coercion routine: converts value from src_type to dst_type.
        Returns the properly cast value (may emit temp assignments as needed).

        Uses existing _safe_coerce_emit logic via temp variable assignment.
        Works for ANY type pair without function-name awareness.
        Scales to 1M functions - ONE routine, not 1M special cases.
        """
        if src_type == dst_type:
            return value

        # Use _safe_coerce_emit to handle the coercion via a temp
        result = self._new_temp(dst_type)
        self._safe_coerce_emit(src_type, dst_type, value, result)
        return result

    def _infer_return_type(self, body: list) -> str:
        """Infer return type by scanning body for ReturnStmt nodes."""
        acc: list[str] = []
        self._collect_return_types(body, acc)
        return TypeLattice.join_all(acc) if acc else 'void'

    def _infer_list_elem_type(self, elements: list) -> str:
        """Determine element C type for a list/set/tuple literal."""
        if not elements:
            return 'int64_t'
        types = [self._quick_type(e) for e in elements]
        return TypeLattice.join_all(types) if types else 'int64_t'

    def _infer_local_var_types(self, func: FunctionDef) -> dict[str, str]:
        """Infer local variable types from all assignments in function body.

        Scans all assignments to determine the variable's actual type needs.
        Returns dict mapping var_name → inferred_ctype.
        """
        inferred = {}

        def collect_assigned_types(nodes: list):
            """Recursively scan statements and collect types assigned to variables."""
            for node in nodes:
                if isinstance(node, AssignStmt):
                    # Use _quick_type instead of lower_expr to avoid incomplete var_types
                    if isinstance(node.target, TupleExpr):
                        targets = node.target.elements
                        # Type each unpack target by its own value, never by the
                        # whole RHS: _quick_type(a_tuple) is 'MojoList *', which would
                        # wrongly poison scalar unpack targets (e.g. start, stop, step
                        # = ivals[0], ivals[1], ivals[2]).
                        if (isinstance(node.value, TupleExpr)
                                and len(node.value.elements) == len(targets)):
                            elem_types = [self._quick_type(e) for e in node.value.elements]
                        else:
                            # Unpacking a single iterable: per-element type is unknown
                            # here; use the int64_t storage default, not the container.
                            elem_types = ['int64_t'] * len(targets)
                    else:
                        targets = [node.target]
                        elem_types = [self._quick_type(node.value)]
                    for target, vtype in zip(targets, elem_types):
                        if isinstance(target, IdentExpr):
                            vname = target.name
                            if vname not in inferred:
                                inferred[vname] = []
                            inferred[vname].append(vtype)
                elif isinstance(node, IfStmt):
                    collect_assigned_types(node.then_body)
                    if node.else_body:
                        collect_assigned_types(node.else_body)
                    for _, elif_body in node.elifs:
                        collect_assigned_types(elif_body)
                elif isinstance(node, (WhileStmt, ForStmt)):
                    collect_assigned_types(node.body)
                    if node.else_body:
                        collect_assigned_types(node.else_body)
                elif isinstance(node, TryStmt):
                    collect_assigned_types(node.body)
                    for h in node.handlers:
                        collect_assigned_types(h.body)
                    if node.else_body:
                        collect_assigned_types(node.else_body)
                    if node.finally_body:
                        collect_assigned_types(node.finally_body)
                elif isinstance(node, WithStmt):
                    collect_assigned_types(node.body)

        collect_assigned_types(func.body)

        # Join all types for each variable using TypeLattice
        result = {}
        for vname, types in inferred.items():
            if types:
                result[vname] = TypeLattice.join_all(types)

        return result

    def _collect_calls(self, expr, out):
        """Append every CallExpr in an expression tree to out. A method (not a
        nested function) so it never goes through the closure-lift machinery."""
        if expr is None:
            return
        if isinstance(expr, CallExpr):
            out.append(expr)
            self._collect_calls(expr.func, out)
            for a in expr.args:
                self._collect_calls(a, out)
            for _k, kv in (getattr(expr, 'kwargs', None) or []):
                self._collect_calls(kv, out)
        elif isinstance(expr, BinaryOp):
            self._collect_calls(expr.left, out); self._collect_calls(expr.right, out)
        elif isinstance(expr, UnaryOp):
            self._collect_calls(expr.operand, out)
        elif isinstance(expr, SubscriptExpr):
            self._collect_calls(expr.obj, out); self._collect_calls(expr.index, out)
        elif isinstance(expr, SliceExpr):
            self._collect_calls(expr.obj, out); self._collect_calls(expr.start, out); self._collect_calls(expr.stop, out)
        elif isinstance(expr, MemberExpr):
            self._collect_calls(expr.obj, out)
        elif isinstance(expr, TernaryExpr):
            self._collect_calls(expr.condition, out); self._collect_calls(expr.then_val, out); self._collect_calls(expr.else_val, out)
        elif isinstance(expr, (ListExpr, SetExpr, TupleExpr)):
            for x in expr.elements:
                self._collect_calls(x, out)
        elif isinstance(expr, DictExpr):
            for dk, dv in expr.pairs:
                self._collect_calls(dk, out); self._collect_calls(dv, out)

    def _calls_in_stmts(self, stmts, out):
        """Collect every CallExpr reachable from a statement list."""
        for n in stmts:
            for attr in ('value', 'condition', 'iterable'):
                if hasattr(n, attr):
                    self._collect_calls(getattr(n, attr), out)
            for attr in ('body', 'then_body', 'else_body', 'finally_body'):
                sub = getattr(n, attr, None)
                if isinstance(sub, list):
                    self._calls_in_stmts(sub, out)
            for _cond, eb in (getattr(n, 'elifs', None) or []):
                self._calls_in_stmts(eb, out)
            for h in (getattr(n, 'handlers', None) or []):
                hb = getattr(h, 'body', None)
                if isinstance(hb, list):
                    self._calls_in_stmts(hb, out)

    def _scan_container_elems(self, body: list) -> tuple[dict, dict]:
        """Best-effort static element-type map for local containers in a body.

        Returns (elem, nested): var name -> element C type, and (when the element
        is itself a list) var name -> the inner list's element C type. Derived by
        replaying list-literal assignments and `.append(...)` calls. Used to build
        the cross-call element-type contract: a caller knows `bodies` is a list of
        double-lists; the callee param must inherit that so `bodies[i][j]` reads
        with the right getter instead of silently defaulting to int.
        """
        elem: dict[str, str] = {}
        nested: dict[str, str] = {}

        def note_list_literal(v: str, lit: ListExpr):
            elem[v] = self._infer_list_elem_type(lit.elements)
            if lit.elements and isinstance(lit.elements[0], ListExpr):
                elem[v] = 'MojoList *'
                nested[v] = self._infer_list_elem_type(lit.elements[0].elements)

        def walk(stmts):
            for n in stmts:
                if isinstance(n, AssignStmt) and isinstance(n.target, IdentExpr):
                    v, val = n.target.name, n.value
                    if isinstance(val, ListExpr):
                        note_list_literal(v, val)
                    elif isinstance(val, IdentExpr) and val.name in elem:
                        elem[v] = elem[val.name]
                        if val.name in nested:
                            nested[v] = nested[val.name]
                elif isinstance(n, ExprStmt) and isinstance(n.value, CallExpr):
                    c = n.value
                    if (isinstance(c.func, MemberExpr) and c.func.member == 'append'
                            and isinstance(c.func.obj, IdentExpr) and c.args):
                        v, a = c.func.obj.name, c.args[0]
                        if isinstance(a, ListExpr):
                            elem[v] = 'MojoList *'
                            nested[v] = self._infer_list_elem_type(a.elements)
                        elif isinstance(a, IdentExpr) and elem.get(a.name) == 'MojoList *':
                            elem[v] = 'MojoList *'
                            if a.name in nested:
                                nested[v] = nested[a.name]
                # recurse into compound statements
                for attr in ('body', 'then_body', 'else_body', 'finally_body'):
                    sub = getattr(n, attr, None)
                    if isinstance(sub, list):
                        walk(sub)
                for _cond, eb in (getattr(n, 'elifs', None) or []):
                    walk(eb)
                for h in (getattr(n, 'handlers', None) or []):
                    hb = getattr(h, 'body', None)
                    if isinstance(hb, list):
                        walk(hb)

        walk(body)
        return elem, nested

    # ── Expression lowering ───────────────────────────────────────────────

    def lower_expr(self, node) -> tuple[str, str]:
        """Return (ctype, simple_rvalue). May emit temp assignments."""
        handler_name = _EXPR_DISPATCH.get(type(node).__name__)
        if handler_name:
            return getattr(self, handler_name)(node)
        _debug_note('unknown expression lowered to 0', type(node).__name__)
        self._emit(f"  /* TODO: unknown expr {type(node).__name__} */")
        t = self._new_val('int', "0")
        return 'int', t

    # ── Expression handlers (one per AST node type) ───────────────────────

    def _lower_IntLiteral(self, node) -> tuple[str, str]:
        return 'int', str(node.value)

    def _lower_FloatLiteral(self, node) -> tuple[str, str]:
        s = repr(node.value)
        if '.' not in s and 'e' not in s.lower():
            s += '.0'
        return 'double', s

    def _lower_BoolLiteral(self, node) -> tuple[str, str]:
        return 'int', ('1' if node.value else '0')

    def _lower_EllipsisLiteral(self, node) -> tuple[str, str]:
        t = self._new_temp('int')
        self._emit(f"  {t} = 0;  /* ... */")
        return 'int', t

    def _parse_fstring_parts(self, inner):
        """Parse f-string body into [('lit',text) | ('expr',code)] parts."""
        parts = []
        i = 0
        buf = []
        while i < len(inner):
            c = inner[i]
            if c == '{':
                if i + 1 < len(inner) and inner[i+1] == '{':
                    buf.append('{'); i += 2; continue
                if buf:
                    parts.append(('lit', ''.join(buf))); buf = []
                i += 1
                depth = 1
                expr_chars = []
                while i < len(inner) and depth > 0:
                    ch = inner[i]
                    if ch == '{': depth += 1
                    elif ch == '}': depth -= 1
                    if depth > 0:
                        expr_chars.append(ch)
                    i += 1
                expr_src = ''.join(expr_chars).split('!')[0].split(':')[0].strip()
                parts.append(('expr', expr_src))
            elif c == '}' and i + 1 < len(inner) and inner[i+1] == '}':
                buf.append('}'); i += 2
            else:
                buf.append(c); i += 1
        if buf:
            parts.append(('lit', ''.join(buf)))
        return parts

    def _lower_StringLiteral(self, node):
        val = node.value
        # Backtick-quoted Mojo identifiers tokenize as STRING — treat as variable reference
        if val.startswith('`') and val.endswith('`') and len(val) > 2:
            return self._lower_IdentExpr(IdentExpr(name=val))
        # Detect and strip f/r/b/u prefix — only if followed by a quote character
        # Regular strings have their quotes already stripped by the parser; f-strings keep prefix+quotes
        is_fstring = False
        prefix = ''
        while val and val[0] in 'fFrRbBuU':
            prefix += val[0]
            val = val[1:]
        # If the remaining value starts with a quote, it still has quotes (f-string case)
        # If not, the prefix-like characters were part of the string content — restore them
        if not val or val[0] not in ('"', "'"):
            val = prefix + val  # restore — these weren't string prefixes
        else:
            # These were actual prefixes — check for f-string marker
            is_fstring = any(c in 'fF' for c in prefix)
        # Strip outer triple or single quotes
        if val.startswith('"""') and val.endswith('"""'):
            val = val[3:-3]
        elif val.startswith("'''") and val.endswith("'''"):
            val = val[3:-3]
        elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if not is_fstring:
            escaped = _c_escape(val)
            # GIMPLE: char[] arrays can't be implicitly assigned to char* locals.
            # Register in the module-level string pool (emitted as C global char arrays)
            # and emit an explicit (char*) cast so callers always get a plain char* temp.
            sname = self._intern_string(escaped)
            temp = self._new_val('char *', f'{sname}')
            return 'char *', temp
        # F-string: for now, just extract literal parts and return as plain string
        # Full f-string formatting with snprintf requires static buffers, which aren't allowed in __GIMPLE
        parts = self._parse_fstring_parts(val)
        if not parts or all(k == 'lit' for k, _ in parts):
            plain = ''.join(v for _, v in parts)
            escaped = _c_escape(plain)
            temp = self._new_val('char *', f'{self._intern_string(escaped)}')
            return 'char *', temp

        # For f-strings with expressions: build a concatenation of all parts
        # Lower each expression part and concatenate via mojo_str_cat
        acc_val = None
        for kind, text in parts:
            if kind == 'lit':
                if not text:
                    continue
                esc = _c_escape(text)
                part_t = self._new_val('char *', f'{self._intern_string(esc)}')
                part_val = part_t
            else:
                # Expression: try to evaluate and convert to char*
                try:
                    from mojo_compiler import Parser as _P, tokenize as _tok
                    expr_node = _P(_tok(text))._parse_expr(0)
                    et, ev = self.lower_expr(expr_node)
                    if et == 'char *':
                        part_val = ev
                    else:
                        str_t = self._call_expr('char *', 'mojo_str', [(et, ev)])
                        part_val = str_t
                except Exception as e:
                    # The interpolation can't be lowered.  Dropping it would
                    # silently corrupt the program's output, so warn and keep
                    # the source text visible in the produced string instead.
                    print(f"mojo: warning: f-string interpolation "
                          f"'{{{text}}}' could not be compiled; emitting it "
                          f"as literal text ({type(e).__name__}: {e})",
                          file=sys.stderr)
                    esc = _c_escape('{' + text + '}')
                    part_val = self._new_val('char *', f'{self._intern_string(esc)}')
            if acc_val is None:
                acc_val = part_val
            else:
                cat_t = self._new_val('char *', f'mojo_str_cat ({acc_val}, {part_val})')
                acc_val = cat_t
        if acc_val is None:
            # Only reachable for an f-string whose parts are all empty
            # literals (e.g. f"{''}") — emit an empty string, not the old
            # "<formatted>" placeholder that leaked into program output.
            acc_val_t = self._new_val('char *', f'{self._intern_string("")}')
            return 'char *', acc_val_t
        return 'char *', acc_val

    def _stub_result(self, ctype: str, value: str, note: str) -> tuple[str, str]:
        """Emit a placeholder result for an operation codegen cannot lower.

        The generated program receives `value` (typically 0 or an empty
        string) instead of a real implementation, annotated with a
        `/* note */` comment.  Every use is reported through _debug_note so
        stubbed-out behavior is diagnosable with MOJO_DEBUG instead of
        silently returning wrong answers.
        """
        _debug_note('stubbed operation', note)
        t = self._new_temp(ctype)
        self._emit(f"  {t} = {value};  /* {note} */")
        return ctype, t

    def _intern_string(self, escaped: str) -> str:
        """Return the pool name (_slit_N) for an already-escaped C string.

        Adds the string to the module-level pool on first use.  All string
        literals must go through the pool: inline char[] literals are not
        valid in __GIMPLE assignments or call arguments.
        """
        name = self._str_pool.get(escaped)
        if name is None:
            name = f'_slit_{STRING_POOL_BASE + len(self._str_pool)}'
            self._str_pool[escaped] = name
        return name

    def _str_literal_to_slit(self, str_literal: str) -> str:
        """Convert a raw C string literal to a _slit_ name from the string pool.
        
        Args:
            str_literal: A raw C string literal like '"hello world"' or "'test'"
            
        Returns:
            The corresponding _slit_ name like '_slit_10000'
        """
        # Strip the outer quotes
        if (str_literal.startswith('"') and str_literal.endswith('"')) or \
           (str_literal.startswith("'") and str_literal.endswith("'")):
            val = str_literal[1:-1]
        else:
            val = str_literal
        
        # Escape the string content
        escaped = _c_escape(val)

        return self._intern_string(escaped)

    def _lower_IdentExpr(self, node) -> tuple[str, str]:
        name = node.name
        if name == 'None':  return 'int', '0'
        if name == 'True':  return 'int', '1'
        if name == 'False': return 'int', '0'
        if name == '__file__':
            t = self._new_val('char *', f'{self._intern_string("<bootstrap>")}')
            return 'char *', t
        if name == '__name__':
            t = self._new_val('char *', f'{self._intern_string("__main__")}')
            return 'char *', t
        if name in self._captures and self._env_param:
            ctype = self._captures[name]
            t = self._new_val(ctype, f'{self._env_param}->{name}')
            return ctype, t
        # Struct/class type name used as a value (e.g. cls arg) — return zero placeholder
        _BUILTIN_TYPE_NAMES = frozenset({
            'Bool', 'Int', 'UInt', 'Int8', 'Int16', 'Int32', 'Int64',
            'UInt8', 'UInt16', 'UInt32', 'UInt64',
            'Float16', 'BFloat16', 'Float32', 'Float64',
            'String', 'Error', 'Pointer',
            # Mojo stdlib enum/class types that may be used as class refs (e.g. DType.float32)
            'DType', 'SIMD', 'StringLiteral', 'StringRef',
            'UnsafePointer', 'ArcPointer', 'OwnedPointer',
            'Optional', 'Variant', 'Tuple',
            'InlineArray', 'InlineList', 'StaticTuple',
        })
        if (name in self.struct_field_types or name in _BUILTIN_TYPE_NAMES) and name not in self.var_types:
            t = self._new_temp('int')
            self._emit(f'  {t} = 0;  /* class ref {name} as value */')
            return 'int', t
        # Python builtin used as a value (e.g. passed to scope.define) — map to C function pointer
        if name in self.BUILTIN_VALUE_MAP and name not in self.var_types:
            c_name = self.BUILTIN_VALUE_MAP[name]
            # Use a pre-declared static void* (emitted in non-GIMPLE context) to avoid
            # the invalid `&func_name` syntax that GIMPLE strict mode rejects.
            # Only add if c_name is a valid C identifier (skip casts like ((int)0))
            if c_name and c_name[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_':
                self._funcptr_builtins_needed.add(c_name)
                static_name = f'_funcptr_{c_name}'
                t = self._new_val('void *', f'{static_name}')
                return 'void *', t
            else:
                # For non-identifier expressions like ((int)0), emit directly
                t = self._new_val('void *', f'(void *){c_name}')
                return 'void *', t
        # C function name used as a value (e.g. tokenize, MojoParser passed to Scope_define).
        # Can't use a function name as rvalue in GIMPLE — use a pre-declared static void*.
        if (name in self.func_return_types and name not in self.var_types
                and name not in self.struct_field_types and name not in self._global_var_types):
            # Use the overload-mangled C symbol so &fn points at the real definition.
            c_name = self._c_names.get(name, self._func_csym(name))
            self._funcptr_builtins_needed.add(c_name)
            static_name = f'_funcptr_{c_name}'
            t = self._new_val('void *', f'{static_name}')
            return 'void *', t
        # Module-level global variable (persistent type known across functions).
        # Also catches `global x` declarations inside functions (_func_declared_globals).
        if (name in self._func_declared_globals or name not in self.var_types) and name in self._global_var_types:
            gtype = self._global_var_types[name]
            # Globals are stored at C level as int64_t (boxed pointers) except
            # for char * and simple int globals whose C type matches the Mojo type.
            if gtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                ctype = 'int64_t'
            else:
                ctype = gtype
            t = self._new_temp(ctype)
            self._actual_types[t] = gtype  # store Mojo type for later dispatch
            if gtype == 'MojoDict *' and name in self._dict_val_types:
                self._dict_val_types[t] = self._dict_val_types[name]
            c_decl_type = self._global_c_decl_types.get(name, ctype)
            # Access global from module struct (use which module the global belongs to)
            global_module = getattr(self, '_global_to_module', {}).get(name, self._current_module_ctx or "root")
            safe_module = _c_field_name(global_module) if global_module else "root"
            field_ref = f"_{safe_module}_globals.{_c_field_name(name)}"
            if ctype == 'int64_t' and c_decl_type.endswith(' *'):
                # Global is declared as a pointer type at C level but we box it as int64_t.
                # GIMPLE: must load pointer into matching-type local, then cast via void* → int64_t.
                raw_ptr = self._new_val(c_decl_type, f'{field_ref}')
                vp = self._new_val('void *', f'(void *){raw_ptr}')
                self._emit(f'  {t} = (int64_t){vp};')
            else:
                # Global is int64_t or same type as ctype — direct assignment is valid.
                self._emit(f'  {t} = {field_ref};')
            return ctype, t
        ctype = self._type_of(name)
        cname = self._c_names.get(name, name)
        if name in self.var_types:
            return ctype, cname
        # Unknown identifier (compile-time param, undeclared external, etc.).
        # Emit a placeholder so GCC doesn't see an undeclared reference.
        t = self._new_temp('int64_t')
        self._emit(f'  {t} = (int64_t)0;  /* ct param or undeclared: {name} */')
        return 'int64_t', t

    def _lower_WalrusExpr(self, node) -> tuple[str, str]:
        vtype, vv = self.lower_expr(node.value)
        if node.name not in self.var_types:
            self._declare_var(node.name, vtype)
        dst = self.var_types[node.name]
        self._safe_coerce_emit(vtype, dst, vv, self._cname(node.name))
        return dst, self._cname(node.name)

    def _lower_UnaryOp(self, node) -> tuple[str, str]:
        ot, ov = self.lower_expr(node.operand)
        if node.op == 'not':
            t = self._new_temp('_Bool')
            if ot in ('char *', 'void *') or (ot.endswith(' *') and ot != '_Bool'):
                ip = self._new_temp('int64_t')
                zero = self._new_temp('int64_t')
                self._emit(f"  {ip} = (int64_t){ov};")
                self._emit(f"  {zero} = (int64_t)0;")
                self._emit(f"  {t} = {ip} == {zero};")
            elif ot == 'int64_t':
                zero = self._new_val('int64_t', "(int64_t)0")
                self._emit(f"  {t} = {ov} == {zero};")
            elif ot == '_Bool':
                # GIMPLE: both operands of comparison must have same type
                # Cast _Bool to int before comparing with integer 0
                int_t = self._new_val('int', f"(int){ov}")
                self._emit(f"  {t} = {int_t} == 0;")
            else:
                self._emit(f"  {t} = {ov} == 0;")
            return '_Bool', t
        # Ownership transfer operator (^) - just pass the value through
        if node.op == '^':
            return ot, ov
        # Spread/unpack operators (* and **) — just pass the value through;
        # the list/call context handles iteration
        if node.op in ('*', '**') and ot in ('MojoList *', 'MojoDict *', 'MojoSet *', 'int'):
            return ot, ov
        # Pointer dereference * on a known pointer type
        if node.op == '*':
            if ot.endswith(' *'):
                elem_type = ot[:-2].strip() or 'int64_t'
                if elem_type == 'void':
                    elem_type = 'int64_t'
                # Struct types: return int64_t (opaque handle) — can't cast struct to int64_t in GIMPLE
                if elem_type in self.struct_field_types or elem_type == 'StringSlice':
                    t = self._new_val('int64_t', f"(int64_t){ov}")
                    return 'int64_t', t
                t = self._new_val(elem_type, f"*{ov}")
                return elem_type, t
            else:
                # int typed as pointer — can't safely dereference; return as-is
                return ot, ov
        if node.op == '+':
            return ot, ov
        c_op = {'-': '-', '~': '~'}.get(node.op, node.op)
        # Struct pointers can't be negated/inverted — coerce to int64_t first
        actual_ot = ot
        actual_ov = ov
        if ot.endswith(' *') and ot not in ('void *', 'char *') and c_op in ('-', '~'):
            ip = self._new_val('int64_t', f"(int64_t){ov}")
            actual_ot = 'int64_t'
            actual_ov = ip
        t = self._new_val(actual_ot, f"{c_op}{actual_ov}")
        return actual_ot, t

    def _lower_TernaryExpr(self, node) -> tuple[str, str]:
        ct, cv = self.lower_expr(node.condition)
        tt, tv = self.lower_expr(node.then_val)
        et, ev = self.lower_expr(node.else_val)

        # GIMPLE: condition must be _Bool, branches must have identical types
        if ct != '_Bool':
            cond = self._new_temp('_Bool')
            if ct in ('char *', 'void *') or ct.endswith(' *'):
                ip = self._new_temp('int64_t')
                zero = self._new_temp('int64_t')
                self._emit(f"  {ip} = (int64_t){cv};")
                self._emit(f"  {zero} = (int64_t)0;")
                self._emit(f"  {cond} = {ip} != {zero};")
            elif ct == 'int64_t':
                zero = self._new_val('int64_t', "(int64_t)0")
                self._emit(f"  {cond} = {cv} != {zero};")
            else:
                self._emit(f"  {cond} = {cv} != 0;")
            cv = cond
        # Coerce branches to common type
        res_type = TypeLattice.join(tt, et)
        if tt != res_type:
            t_tmp = self._new_temp(res_type)
            self._safe_coerce_emit(tt, res_type, tv, t_tmp)
            tv = t_tmp
        if et != res_type:
            e_tmp = self._new_temp(res_type)
            self._safe_coerce_emit(et, res_type, ev, e_tmp)
            ev = e_tmp
        # GIMPLE: load global string literals into temps before ternary
        if res_type == 'char *' and tv.startswith('_slit_'):
            tv_tmp = self._new_val('char *', f'{tv}')
            tv = tv_tmp
        if res_type == 'char *' and ev.startswith('_slit_'):
            ev_tmp = self._new_val('char *', f'{ev}')
            ev = ev_tmp
        t = self._new_val(res_type, f"{cv} ? {tv} : {ev}")
        return res_type, t

    def _subst_idents(self, expr, mapping: dict):
        """Return a copy of an AST expression with any IdentExpr whose name is in
        `mapping` replaced by the mapped node. Used to rebind `Self`/struct-name
        to a concrete object expression when expanding a struct comptime alias."""
        if isinstance(expr, IdentExpr) and expr.name in mapping:
            return mapping[expr.name]
        if dataclasses.is_dataclass(expr) and not isinstance(expr, type):
            changes = {}
            for f in dataclasses.fields(expr):
                v = getattr(expr, f.name)
                nv = self._subst_in_value(v, mapping)
                if nv is not v:
                    changes[f.name] = nv
            return dataclasses.replace(expr, **changes) if changes else expr
        return expr

    def _subst_in_value(self, v, mapping: dict):
        if isinstance(v, list):
            return [self._subst_in_value(x, mapping) for x in v]
        if isinstance(v, tuple):
            return tuple(self._subst_in_value(x, mapping) for x in v)
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            return self._subst_idents(v, mapping)
        return v

    def _lower_MemberExpr(self, node) -> tuple[str, str]:
        # Check if obj is a simple identifier (module access)
        if isinstance(node.obj, IdentExpr):
            module_name = node.obj.name

            # __mlir_attr.`literal` — a typed MLIR attribute used as a value
            # (integer constants like `0 : index`).  Lower to the constant.
            if module_name == '__mlir_attr':
                kind, val = mlir.parse_attr(node.member)
                if kind in ('int', 'simd'):   # typed int / scalar-simd constant
                    t = self._new_val('int64_t', f"(int64_t){val}")
                    return 'int64_t', t
                # Predicate / unmodeled attrs only matter as op subscript params,
                # which are read directly at the op call site; yield a placeholder.
                t = self._new_temp('int')
                self._emit(f"  {t} = 0;  /* __mlir_attr {mlir.unwrap(node.member)} */")
                return 'int', t

            # Module attribute access: sys.argv, tokenizer.X, etc.
            if module_name == 'sys' and node.member == 'argv':
                # Return the argv list wired from C main(argc, argv)
                t = self._new_temp('MojoList *')
                self._emit(f"  {t} = mojo_get_argv();  /* sys.argv from C */")
                # Track element type so subscript uses mojo_list_get_str
                self._elem_types[t] = 'char *'
                return 'MojoList *', t

            # Special handling for os.path attribute access
            if module_name == 'os' and node.member == 'path':
                # os.path is a marker - return a special value indicating path module
                # The actual function call will be handled at the call site
                t = self._new_temp('int')
                self._emit(f"  {t} = 0;  /* os.path module marker */")
                return 'int', t

            # Class attribute access: ClassName.ATTR
            # Check if module_name is a known struct/class (not an instance variable)
            if module_name in self.struct_field_types and module_name not in self.var_types:
                # This is a class-level access like TypeLattice._FLOAT
                t = self._new_temp('int')
                self._emit(f"  {t} = 0;  /* class attr {module_name}.{node.member} */")
                return 'int', t

        # If the object is a zero-arg function used in member-access context (e.g. block_idx.x),
        # call it first so we get the struct return value, not a void* funcptr.
        if (isinstance(node.obj, IdentExpr)
                and node.obj.name in self.func_return_types
                and node.obj.name not in self.var_types
                and node.obj.name not in self.struct_field_types
                and node.obj.name not in self.BUILTIN_VALUE_MAP):
            _fn_name = node.obj.name
            _c_fn = self._c_names.get(_fn_name, _safe_name(_fn_name))
            _ret = self.func_return_types.get(_fn_name, 'int64_t')
            ot = _ret
            ov = self._new_val(_ret, f'{_c_fn} ()')
        else:
            ot, ov = self.lower_expr(node.obj)

        # If the object lowered to a C type name (class used as cls argument),
        # treat it as NULL — the method shouldn't use cls for value access
        if ov in self.struct_field_types and ot == 'int':
            null_tmp = self._new_temp('int')
            self._emit(f"  {null_tmp} = 0;  /* class ref {ov} as NULL */")
            ov = null_tmp


        # MojoList field name remapping: Mojo List uses _len/_capacity/elems; C MojoList uses len/cap/data
        _sn = _struct_name_of(ot)
        if _sn == 'MojoList':
            _mojo_to_c = {'_len': 'len', '_capacity': 'cap', '_size': 'len', 'elems': 'data', '_data': 'data', 'cap': 'cap', 'len': 'len', 'data': 'data'}
            if node.member in _mojo_to_c:
                _c_field = _mojo_to_c[node.member]
                _ftype = 'int64_t' if _c_field in ('len', 'cap') else 'int64_t *'
                t = self._new_val(_ftype, f"{ov}->{_c_field}")
                return _ftype, t

        # .address on any pointer type: UnsafePointer.address → the raw integer address
        if node.member == 'address' and ot.endswith(' *'):
            t = self._new_val('int64_t', f"(int64_t){ov}")
            return 'int64_t', t

        # `x._mlir_value` unwraps a scalar newtype (Int/UInt over an __mlir_type)
        # to its underlying MLIR value — at the C level that is the scalar itself,
        # so pass the operand through unchanged. Only for already-scalar operands:
        # struct-typed values (Bool*, SIMD*) keep their existing member handling.
        if node.member == '_mlir_value' and not (ot.endswith(' *') and _struct_name_of(ot)):
            return ot, ov

        # .value on char * (StringLiteral.value, kgen.string.value) → identity, the string itself
        if node.member == 'value' and ot == 'char *':
            t = self._new_val('char *', f"{ov}")
            return 'char *', t

        # .value on void * or function pointer (DType/bracket-param typed as builtin 'type')
        # → extract the integer value. This handles e.g. `type.value` where `type` is a
        # bracket param of type `TraceCategory` that got lowered to a function pointer.
        if node.member == 'value' and ot in ('void *', 'int64_t', 'int'):
            t = self._new_temp('int64_t')
            if ot == 'void *':
                vt = self._new_val('int64_t', f"(int64_t){ov}")
                self._emit(f"  {t} = {vt};")
            else:
                self._emit(f"  {t} = (int64_t){ov};")
            return 'int64_t', t

        # Special handling for .__name__ on type objects
        if node.member == '__name__':
            struct_name_check = _struct_name_of(ot)
            if struct_name_check not in self.struct_field_types:
                t = self._new_temp('char *')
                self._emit(f'  {t} = {self._intern_string("<type>")};  /* {ot}.__name__ stubbed */')
                return 'char *', t

        # Special handling for .__dict__ on int objects (node variable)
        if node.member == '__dict__' and ot == 'int':
            return self._stub_result('int', '0', '__dict__ stub')

        op = '->' if '*' in ot else '.'
        struct_name = _struct_name_of(ot)
        field_map = self.struct_field_types.get(struct_name, {})
        if node.member in field_map:
            field_type = field_map[node.member]
            t = self._new_val(field_type, f'{ov}{op}{_safe_field(node.member)}')
            return field_type, t
        # Struct-level comptime alias (e.g. BitSet._words_size): not a physical
        # field — expand its defining expression with `Self`/the struct name
        # rebound to the accessed object, then lower that.
        aliases = self._struct_comptime_aliases.get(struct_name)
        if aliases and node.member in aliases:
            val_ast = self._subst_idents(aliases[node.member],
                                         {'Self': node.obj, struct_name: node.obj})
            return self.lower_expr(val_ast)
        # Class-level attribute (not an instance field) — redirect to global variable
        class_attrs = getattr(self, '_class_attrs', {})
        if struct_name in class_attrs and node.member in class_attrs[struct_name]:
            gname = class_attrs[struct_name][node.member]
            # Use the actual declared type of the global (stored in _global_var_types)
            gtype = self._global_var_types.get(gname, 'int64_t')
            t = self._new_val(gtype, f'{gname}')
            return gtype, t
        elif struct_name in self.struct_field_types and ot.endswith(' *'):
            # Known struct type but unknown field — try to find another struct that has it
            alt_struct = None
            for sn, fm in self.struct_field_types.items():
                if node.member in fm:
                    alt_struct = sn
                    break
            if alt_struct:
                field_type = self.struct_field_types[alt_struct][node.member]
                cast_t = self._new_val(f'{alt_struct} *', f'({alt_struct} *){ov}')
                t = self._new_val(field_type, f'{cast_t}->{_safe_field(node.member)}')
            else:
                # Fall back: assume pointer to same struct type
                field_type = struct_name + ' *'
                t = self._new_val(field_type, f'{ov}{op}{_safe_field(node.member)}')
            return field_type, t
        elif ot in ('int', 'int64_t', 'void *') or ot in ('MojoList *', 'MojoDict *', 'MojoSet *', 'MojoStr *'):
            # Opaque Python object typed as int, void *, or built-in container — use runtime attribute accessor
            # GIMPLE requires function args to be simple vars, not cast expressions
            vp = self._new_val('void *', f'(void *){ov}')
            return 'int64_t', self._call_expr('int64_t', 'mojo_obj_getattr',
                            [('void *', vp), ('char *', f'"{node.member}"')])
        else:
            # Unknown struct field — fall back
            # If the object is a pointer type, assume the field is also a pointer
            if '*' in ot:
                field_type = struct_name + ' *'
            else:
                field_type = 'int64_t'
            t = self._new_val(field_type, f'{ov}{op}{_safe_field(node.member)}')
            return field_type, t
    # ── Binary operator lowering ──────────────────────────────────────────

    def _lower_binary(self, node: BinaryOp) -> tuple[str, str]:
        if node.op == ':=':
            vtype, vv = self.lower_expr(node.right)
            if isinstance(node.left, IdentExpr):
                nm = node.left.name
                if nm not in self.var_types:
                    self._declare_var(nm, vtype)
                    # Track that this variable holds this type for concatenation detection
                    if vtype == 'char *':
                        self._actual_types[nm] = 'char *'
                dst = self.var_types[nm]
                self._safe_coerce_emit(vtype, dst, vv, nm)
                # Update actual type tracking for string types
                if dst == 'int' and vtype == 'char *':
                    self._actual_types[nm] = 'char *'
                return dst, nm
            if isinstance(node.left, MemberExpr):
                ot, ov = self.lower_expr(node.left.obj)
                op = '->' if '*' in ot else '.'
                sn = _struct_name_of(ot)
                field_type = self.struct_field_types.get(sn, {}).get(node.left.member, vtype)
                self._safe_coerce_emit(vtype, field_type, vv, f"{ov}{op}{node.left.member}")
                return field_type, vv
            if isinstance(node.left, SubscriptExpr):
                ot, obj_v = self.lower_expr(node.left.obj)
                _, idx_v = self.lower_expr(node.left.index)
                if ot == 'MojoList *':
                    elem = self._elem_of(obj_v)
                    suf  = TypeLattice.list_suffix(elem)
                    idx64 = self._new_val('int64_t', f"(int64_t) {idx_v}")
                    ev_cast = self._cast_for_list(vtype, vv, suf)
                    self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
                else:
                    if not self._emit_struct_subscript_write(obj_v, ot, idx_v, vv, vtype):
                        self._emit(f"  {obj_v}[{idx_v}] = {vv};")
                return vtype, vv
            # Skip emitting comment to avoid GIMPLE global-passing issues
            return vtype, vv
        if node.op == '//':
            return self._lower_floordiv(node)
        if node.op == '**':
            return self._lower_pow(node)
        if node.op == '@':
            return self._lower_matmul(node)
        if node.op == 'in':
            return self._lower_in_impl(node, negate=False)
        if node.op == 'not in':
            return self._lower_in_impl(node, negate=True)

        if node.op in ('and', 'or'):
            # GIMPLE does not allow && or || in assignments; lower to branching form.
            ltype, lval = self.lower_expr(node.left)
            result = self._new_temp('_Bool')
            bb_right = self._new_bb()
            bb_merge = self._new_bb()
            # Must use proper bool conversion (no direct pointer→_Bool cast)
            lcast = self._ensure_bool_cond(ltype, lval)
            self._emit(f'  {result} = {lcast};')
            if node.op == 'and':
                self._emit(f'  if ({lcast}) goto {bb_right}; else goto {bb_merge};')
            else:
                self._emit(f'  if ({lcast}) goto {bb_merge}; else goto {bb_right};')
            self._emit_label(bb_right)
            rtype, rval = self.lower_expr(node.right)
            rcast = self._ensure_bool_cond(rtype, rval)
            self._emit(f'  {result} = {rcast};')
            self._emit(f'  goto {bb_merge};')
            self._emit_label(bb_merge)
            return '_Bool', result

        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)

        # A list local may be boxed as int64_t (the slice pre-pass hint is the
        # machine word when the sliced object's type isn't yet known); _actual_types
        # records the real MojoList*. Resolve through it so list+list still concats.
        alt = self._actual_types.get(lv, self.var_types.get(lv, lt))
        art = self._actual_types.get(rv, self.var_types.get(rv, rt))
        if node.op == '+' and alt == 'MojoList *' and art == 'MojoList *':
            lcast = lv if lt == 'MojoList *' else self._new_temp('MojoList *')
            if lt != 'MojoList *': self._emit(f"  {lcast} = (MojoList *){lv};")
            rcast = rv if rt == 'MojoList *' else self._new_temp('MojoList *')
            if rt != 'MojoList *': self._emit(f"  {rcast} = (MojoList *){rv};")
            t = self._new_val('MojoList *', f"mojo_list_concat ({lcast}, {rcast})")
            if lcast in self._elem_types:
                self._elem_types[t] = self._elem_types[lcast]
            return 'MojoList *', t

        # MojoList + MojoList → mojo_list_concat
        if node.op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
            t = self._new_val('MojoList *', f"mojo_list_concat ({lv}, {rv})")
            if lv in self._elem_types:
                self._elem_types[t] = self._elem_types[lv]
            return 'MojoList *', t

        # MojoList * + int/int64_t → identity (DynamicVector not supported; treat as no-op)
        if node.op == '+' and lt == 'MojoList *' and rt in ('int', 'int64_t'):
            return 'MojoList *', lv

        # MojoList * + <pointer-ish> → mojo_list_concat after casting the RHS to
        # MojoList *. Covers polymorphic locals: a name (e.g. `body`) that is a
        # list in one branch but declared `char *` because another branch assigns
        # it a string. At a list-concat site the runtime value *is* a list, so
        # concat is the correct lowering; without this we emit `MojoList * + char *`,
        # which gcc rejects. (Salvaged from the bootstrap bug-hunt; it advances the
        # self-host build past mojo_compiler.py's emit().)
        if node.op == '+' and lt == 'MojoList *' and rt.endswith(' *'):
            rcast = rv
            if rt != 'MojoList *':
                rcast = self._new_val('MojoList *', f"(MojoList *){rv}")
            t = self._new_val('MojoList *', f"mojo_list_concat ({lv}, {rcast})")
            if lv in self._elem_types:
                self._elem_types[t] = self._elem_types[lv]
            return 'MojoList *', t

        # MojoStr + MojoStr → mojo_str_concat
        if node.op == '+' and lt == 'MojoStr *' and rt == 'MojoStr *':
            t = self._new_val('MojoStr *', f"mojo_str_concat ({lv}, {rv})")
            return 'MojoStr *', t

        # char * + char * → mojo_str_cat (including int64_t holding char* via actual_types)
        # Also handle int + char * when int is likely a string pointer
        def _as_charptr(typ, val, is_string_literal=False):
            if typ == 'char *':
                return 'char *', val
            # Check if actual type is char*
            actual = self._actual_types.get(val)
            if actual == 'char *':
                cp = self._new_temp('char *')
                ip = self._new_val('int64_t', f"(int64_t){val}")
                self._emit(f"  {cp} = (char *){ip};")
                return 'char *', cp
            # If one operand is definitely a string literal, treat int as potential string
            if is_string_literal and typ in ('int', 'int64_t') and val.startswith('_slit_'):
                cp = self._new_temp('char *')
                ip = self._new_val('int64_t', f"(int64_t){val}")
                self._emit(f"  {cp} = (char *){ip};")
                return 'char *', cp
            return typ, val
        if node.op == '+':
            # Check if the OTHER operand is a string literal - helps identify string concatenation
            right_is_lit = isinstance(node.right, StringLiteral)
            left_is_lit = isinstance(node.left, StringLiteral)
            lt2, lv2 = _as_charptr(lt, lv, is_string_literal=right_is_lit)
            rt2, rv2 = _as_charptr(rt, rv, is_string_literal=left_is_lit)
            if lt2 == 'char *' and rt2 == 'char *':
                t = self._call_expr('char *', 'mojo_str_cat', [('char *', lv2), ('char *', rv2)])
                return 'char *', t
            # int/int64_t + char* or char* + int/int64_t when one side is a string literal
            # → this is Python string concatenation where one operand is a string stored as int
            if right_is_lit and rt == 'char *' and lt in ('int', 'int64_t'):
                ip = self._new_temp('int64_t')
                cp = self._new_temp('char *')
                self._emit(f'  {ip} = (int64_t){lv};')
                self._emit(f'  {cp} = (char *){ip};')
                t = self._call_expr('char *', 'mojo_str_cat', [('char *', cp), ('char *', rv)])
                return 'char *', t
            if left_is_lit and lt == 'char *' and rt in ('int', 'int64_t'):
                ip = self._new_temp('int64_t')
                cp = self._new_temp('char *')
                self._emit(f'  {ip} = (int64_t){rv};')
                self._emit(f'  {cp} = (char *){ip};')
                t = self._call_expr('char *', 'mojo_str_cat', [('char *', lv), ('char *', cp)])
                return 'char *', t
            # String + numeric (or numeric + String) where the numeric is a real
            # value, not a string-stored-as-int. This is String concatenation with
            # an Int; emitting `char* + int` as C arithmetic is invalid and ICEs
            # gcc's build2. Stringify the numeric operand and concatenate.
            if lt2 == 'char *' and rt2 in ('int', 'int64_t', '_Bool'):
                nv = self._to_int64(rt2, rv2)
                sv = self._call_expr('char *', 'mojo_str_from_int', [('int64_t', nv)])
                return 'char *', self._call_expr('char *', 'mojo_str_cat', [('char *', lv2), ('char *', sv)])
            if rt2 == 'char *' and lt2 in ('int', 'int64_t', '_Bool'):
                nv = self._to_int64(lt2, lv2)
                sv = self._call_expr('char *', 'mojo_str_from_int', [('int64_t', nv)])
                return 'char *', self._call_expr('char *', 'mojo_str_cat', [('char *', sv), ('char *', rv2)])

        # char * * int → string repetition (e.g., "  " * 3)
        if node.op == '*' and lt == 'char *' and rt in ('int', 'int64_t', 'uint64_t'):
            t = self._new_temp('char *')
            lv_local = self._ensure_local(lt, lv)
            self._emit(f"  {t} = mojo_cstr_repeat ({lv_local}, {rv});")
            return 'char *', t

        # int * char * → string repetition (flipped order)
        if node.op == '*' and lt in ('int', 'int64_t', 'uint64_t') and rt == 'char *':
            t = self._new_temp('char *')
            rv_local = self._ensure_local(rt, rv)
            self._emit(f"  {t} = mojo_cstr_repeat ({rv_local}, {lv});")
            return 'char *', t

        # MojoList * * int → list repetition (e.g., [0] * n)
        if node.op == '*' and lt == 'MojoList *' and rt in ('int', 'int64_t', 'uint64_t'):
            cnt = self._new_val('int64_t', f"(int64_t){rv}")
            t = self._call_expr('MojoList *', 'mojo_list_repeat', [('MojoList *', lv), ('int64_t', cnt)])
            return 'MojoList *', t

        # MojoStr == / != → mojo_str_eq
        if node.op in ('==', '!=') and lt == 'MojoStr *' and rt == 'MojoStr *':
            eq_t = self._new_val('int', f"mojo_str_eq ({lv}, {rv})")
            t = self._new_temp('_Bool')
            cmp = '!= 0' if node.op == '==' else '== 0'
            self._emit(f"  {t} = {eq_t} {cmp};")
            return '_Bool', t

        # String equality: char*, int64_t-stored-char*, or string literals → strcmp
        rv_is_str_lit = isinstance(node.right, StringLiteral)
        lv_is_str_lit = isinstance(node.left, StringLiteral)
        if node.op in ('==', '!='):
            uses_str = (lt == 'char *' or rt == 'char *' or rv_is_str_lit or lv_is_str_lit or
                        (lt == 'int64_t' and (rv_is_str_lit or rt == 'char *')) or
                        (rt == 'int64_t' and (lv_is_str_lit or lt == 'char *')))
            if uses_str:
                def _to_char_star(typ, var):
                    if typ == 'char *':
                        t2 = self._new_temp('char *'); self._emit(f'  {t2} = {var};'); return t2
                    ip = self._new_val('int64_t', f'(int64_t){var}')
                    cp = self._new_val('char *', f'(char *){ip}')
                    return cp
                ls = _to_char_star(lt, lv)
                rs = _to_char_star(rt, rv)
                eq_t = self._call_expr('int', 'strcmp', [('char *', ls), ('char *', rs)])
                t = self._new_temp('_Bool')
                cmp = '== 0' if node.op == '==' else '!= 0'
                self._emit(f'  {t} = {eq_t} {cmp};')
                return '_Bool', t


        # is / is not → pointer identity
        if node.op in ('is', 'is not'):
            c_op = '==' if node.op == 'is' else '!='
            t = self._new_temp('_Bool')
            if '*' in lt or '*' in rt:
                p1 = self._new_temp('int64_t')
                p2 = self._new_temp('int64_t')
                self._emit(f"  {p1} = (int64_t) {lv};")
                self._emit(f"  {p2} = (int64_t) {rv};")
                self._emit(f"  {t} = {p1} {c_op} {p2};")
            elif lt != rt:
                # GIMPLE requires identical types in comparisons; coerce to int64_t
                cmp_type = TypeLattice.join(lt, rt)
                p1 = self._new_temp(cmp_type)
                p2 = self._new_temp(cmp_type)
                self._emit(f"  {p1} = ({cmp_type}){lv};")
                self._emit(f"  {p2} = ({cmp_type}){rv};")
                self._emit(f"  {t} = {p1} {c_op} {p2};")
            else:
                self._emit(f"  {t} = {lv} {c_op} {rv};")
            return '_Bool', t

        # Fallback: catch string concatenation that wasn't handled above
        if node.op == '+' and lt == 'char *' and rt == 'char *':
            t = self._call_expr('char *', 'mojo_str_cat', [('char *', lv), ('char *', rv)])
            return 'char *', t
        # Fallback: catch list concatenation that wasn't handled above
        if node.op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
            t = self._new_val('MojoList *', f"mojo_list_concat ({lv}, {rv})")
            if lv in self._elem_types:
                self._elem_types[t] = self._elem_types[lv]
            return 'MojoList *', t

        # Path joining: Mojo uses `/` as the path-join operator (Path.__truediv__).
        # When we see int64_t/char* or char*/char* with op='/', dispatch to mojo_path_join.
        if node.op == '/' and rt == 'char *':
            t = self._new_temp('char *')
            lv_str = lv
            if lt != 'char *':
                lv_str = self._new_temp('char *')
                lv_i64 = self._new_temp('int64_t') if lt != 'int64_t' else lv
                if lt != 'int64_t':
                    self._emit(f'  {lv_i64} = (int64_t){lv};')
                self._emit(f'  {lv_str} = (char *){lv_i64};')
            self._emit_call('char *', t, 'mojo_path_join', [('char *', lv_str), ('char *', rv)])
            return 'char *', t

        # Cast struct pointer operands through int64_t so C arithmetic is valid.
        # e.g., `self * -1` inside Int.__neg__ where self: Int * → (int64_t)self * -1.
        # Must happen before res_type is computed to avoid declaring result as struct ptr.
        _KNOWN_PTRS = frozenset({
            'void *', 'char *', 'MojoList *', 'MojoDict *', 'MojoSet *', 'MojoStr *',
        })
        if lt.endswith(' *') and lt not in _KNOWN_PTRS and node.op not in ('==', '!=', 'is', 'is not'):
            ip = self._new_val('int64_t', f'(int64_t){lv}')
            lt = 'int64_t'; lv = ip
        if rt.endswith(' *') and rt not in _KNOWN_PTRS and node.op not in ('==', '!=', 'is', 'is not'):
            ip = self._new_val('int64_t', f'(int64_t){rv}')
            rt = 'int64_t'; rv = ip

        c_op      = _BIN_OPS.get(node.op, node.op)
        res_type  = '_Bool' if node.op in _CMP_OPS else TypeLattice.join(lt, rt)

        # Type system: Check BIT_WIDTH_PRESERVATION for arithmetic ops
        # For | on set/list/dict pointer types, use runtime union, not C bitwise |.
        # An empty `{}` operand lowers to MojoDict*; coerce such pointer operands
        # to MojoSet* so GIMPLE's strict pointer typing accepts the call.
        def _as_set(t, v):
            if t == 'MojoSet *':
                return v
            return self._new_val('MojoSet *', f'(MojoSet *){self._ensure_local(t, v)}')
        if node.op == '|' and (lt.endswith(' *') or rt.endswith(' *')):
            return 'MojoSet *', self._call_expr('MojoSet *', 'mojo_set_union',
                                                [('MojoSet *', _as_set(lt, lv)), ('MojoSet *', _as_set(rt, rv))])
        # For - on set types, use runtime difference, not C subtraction
        if node.op == '-' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
            return 'MojoSet *', self._call_expr('MojoSet *', 'mojo_set_difference',
                                                [('MojoSet *', _as_set(lt, lv)), ('MojoSet *', _as_set(rt, rv))])
        # For & on set types, use runtime intersection, not C bitwise &
        if node.op == '&' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
            return 'MojoSet *', self._call_expr('MojoSet *', 'mojo_set_intersection',
                                                [('MojoSet *', _as_set(lt, lv)), ('MojoSet *', _as_set(rt, rv))])
        # For ^ on set types, symmetric difference = (a - b) | (b - a).
        # No dedicated runtime entry; compose from difference + union.
        if node.op == '^' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
            a, b = _as_set(lt, lv), _as_set(rt, rv)
            ab = self._call_expr('MojoSet *', 'mojo_set_difference', [('MojoSet *', a), ('MojoSet *', b)])
            ba = self._call_expr('MojoSet *', 'mojo_set_difference', [('MojoSet *', b), ('MojoSet *', a)])
            return 'MojoSet *', self._call_expr('MojoSet *', 'mojo_set_union',
                                                [('MojoSet *', ab), ('MojoSet *', ba)])
        # Cast operands to result type to satisfy GIMPLE strict type checking
        arith_type = TypeLattice.join(lt, rt)  # common type for arithmetic
        if lt != arith_type and arith_type not in ('_Bool',) and not arith_type.endswith(' *'):
            ct = self._new_temp(arith_type)
            self._safe_coerce_emit(lt, arith_type, lv, ct)
            lv = ct
        if rt != arith_type and arith_type not in ('_Bool',) and not arith_type.endswith(' *'):
            ct = self._new_temp(arith_type)
            self._safe_coerce_emit(rt, arith_type, rv, ct)
            rv = ct
        if node.op in ('==', '!=', '<', '>', '<=', '>=') and lt.endswith(' *') != rt.endswith(' *'):
            ip_l = self._new_temp('int64_t')
            ip_r = self._new_temp('int64_t')
            self._emit(f'  {ip_l} = (int64_t){lv};')
            self._emit(f'  {ip_r} = (int64_t){rv};')
            lv = ip_l; rv = ip_r
        # Floating-point division: gcc -fgimple ICEs (expmed_mode_index) on a
        # float/double `/` inside a __GIMPLE body. Route through a normal-C
        # runtime helper where the division expands correctly. Operands are
        # already coerced to res_type above.
        # TODO(gimple-fp-div): drop this indirection once the gcc -fgimple
        # float/double division ICE is fixed upstream.
        if c_op == '/' and res_type in ('double', 'float'):
            fn = 'mojo_div_double' if res_type == 'double' else 'mojo_div_float'
            return res_type, self._call_expr(res_type, fn, [(res_type, lv), (res_type, rv)])
        t = self._new_val(res_type, f"{lv} {c_op} {rv}")
        return res_type, t

    # ── Operator helpers ──────────────────────────────────────────────────

    def _lower_floordiv(self, node: BinaryOp) -> tuple[str, str]:
        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)
        if lt in _FLOAT_TYPES or rt in _FLOAT_TYPES:
            td = TypeLattice.join(lt, rt)
            t1 = self._new_val(td, f"{lv} / {rv}")
            t2 = self._new_val(td, f"__builtin_floor ({t1})")
            return td, t2
        # Coerce struct pointers to int64_t before integer floor division
        if lt.endswith(' *') and lt not in ('void *', 'char *'):
            ti = self._new_val('int64_t', f"(int64_t){lv}")
            lv = ti
        if rt.endswith(' *') and rt not in ('void *', 'char *'):
            ti = self._new_val('int64_t', f"(int64_t){rv}")
            rv = ti
        t = self._new_val('int64_t', f"__mojo_floordiv ({lv}, {rv})")
        return 'int64_t', t

    def _lower_pow(self, node: BinaryOp) -> tuple[str, str]:
        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)
        if lt in _FLOAT_TYPES or rt in _FLOAT_TYPES:
            td = TypeLattice.join(lt, rt)
            t = self._new_val(td, f"pow ({lv}, {rv})")
            return td, t
        # Coerce struct pointers to int64_t before converting to double
        # (casting struct * to double directly is invalid in GIMPLE)
        lv_for_double = lv
        rv_for_double = rv
        if lt.endswith(' *'):
            ti = self._new_val('int64_t', f"(int64_t) {lv}")
            lv_for_double = ti
        if rt.endswith(' *'):
            ti = self._new_val('int64_t', f"(int64_t) {rv}")
            rv_for_double = ti
        t1 = self._new_temp('double')
        t2 = self._new_temp('double')
        self._emit(f"  {t1} = (double) {lv_for_double};")
        self._emit(f"  {t2} = (double) {rv_for_double};")
        t3 = self._new_val('double', f"pow ({t1}, {t2})")
        t4 = self._new_val('int', f"(int) {t3}")
        return 'int', t4

    def _lower_matmul(self, node: BinaryOp) -> tuple[str, str]:
        """Lower matrix multiply: a @ b → a.__matmul__(b)

        Calls the __matmul__ method on the left operand.
        TODO: Implement high-performance matrix multiplication using BLAS (e.g., dgemm)
        or SIMD intrinsics for larger matrices. For now, delegates to user-defined
        __matmul__ implementations on matrix types.
        """
        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)

        # Get struct name from left operand type
        struct_name = _struct_name_of(lt)

        # Call __matmul__(self, other) method
        mangled = f"{struct_name}___matmul__"
        result_type = self.func_return_types.get(mangled, 'int64_t')  # Default: assume int result
        t = self._new_val(result_type, f"{mangled} ({lv}, {rv})")
        return result_type, t

    def _lower_in_range(self, x_val: str, range_args: list,
                        negate: bool) -> tuple[str, str]:
        if len(range_args) == 1:
            _, n_val = self.lower_expr(range_args[0])
            t1 = self._new_temp('_Bool')
            t2 = self._new_temp('_Bool')
            t3 = self._new_temp('_Bool')
            self._emit(f"  {t1} = {x_val} >= 0;")
            self._emit(f"  {t2} = {x_val} < {n_val};")
            self._emit(f"  {t3} = {t1} & {t2};")
        elif len(range_args) == 2:
            _, a_val = self.lower_expr(range_args[0])
            _, b_val = self.lower_expr(range_args[1])
            t1 = self._new_temp('_Bool')
            t2 = self._new_temp('_Bool')
            t3 = self._new_temp('_Bool')
            self._emit(f"  {t1} = {x_val} >= {a_val};")
            self._emit(f"  {t2} = {x_val} < {b_val};")
            self._emit(f"  {t3} = {t1} & {t2};")
        else:
            # Skip emitting comment to avoid GIMPLE global-passing issues
            t3 = self._new_val('_Bool', "0")
        if negate:
            ti = self._new_temp('int')
            tn = self._new_temp('_Bool')
            self._emit(f"  {ti} = (int) {t3};")
            self._emit(f"  {tn} = {ti} == 0;")
            return '_Bool', tn
        return '_Bool', t3

    def _lower_in_impl(self, node: BinaryOp, negate: bool) -> tuple[str, str]:
        xt, xv = self.lower_expr(node.left)
        if (isinstance(node.right, CallExpr) and
                isinstance(node.right.func, IdentExpr) and
                node.right.func.name == 'range'):
            return self._lower_in_range(xv, node.right.args, negate=negate)

        rt, rv = self.lower_expr(node.right)
        ti = self._new_temp('int')

        if rt == 'MojoList *':
            # Determine list element type: prefer actual list elem type over left operand
            if rv in self._elem_types:
                list_elem = self._elem_types[rv]
            else:
                list_elem = xt
            suf = TypeLattice.list_suffix(list_elem)
            xv_cast = self._cast_for_list(xt, xv, suf)
            self._emit(f"  {ti} = mojo_list_contains_{suf} ({rv}, {xv_cast});")
        elif rt == 'MojoDict *':
            # Ensure key is char * for dict operations (all dict keys are strings in runtime)
            if xt != 'char *':
                xv_cast = self._new_val('char *', f"(char *){xv}")
                xv = xv_cast
                xt = 'char *'
            self._emit_call('int', ti, 'mojo_dict_contains', [('MojoDict *', rv), (xt, xv)])
        elif rt == 'MojoSet *':
            # Route through _emit_call so global/_slit_ args are loaded into locals
            # first (GIMPLE: a call argument must be a local, not a global decl).
            if xt == 'char *':
                self._emit_call('int', ti, 'mojo_set_contains_str', [('MojoSet *', rv), ('char *', xv)])
            else:
                xv64 = self._to_int64(xt, xv)
                self._emit_call('int', ti, 'mojo_set_contains_int', [('MojoSet *', rv), ('int64_t', xv64)])
        elif rt == 'MojoStr *':
            self._emit_call('int', ti, 'mojo_str_contains', [('MojoStr *', rv), ('char *', xv)])
        else:
            self._emit(f"  /* TODO: 'in' for {rt} */")
            self._emit(f"  {ti} = 0;")

        t = self._new_val('_Bool', f"{ti} != 0")

        if negate:
            ti2 = self._new_temp('int')
            tn  = self._new_temp('_Bool')
            self._emit(f"  {ti2} = (int) {t};")
            self._emit(f"  {tn} = {ti2} == 0;")
            return '_Bool', tn
        return '_Bool', t

    def _cast_for_list(self, elem_type: str, val: str, suf: str) -> str:
        """Coerce a value to the API's expected type; always returns an lvalue (temp if cast needed)."""
        if suf == 'int':
            return self._to_int64(elem_type, val)
        if suf == 'double':
            if elem_type == 'double':
                return val
            t = self._new_val('double', f"(double){val}")
            return t
        # str: cast int-cast strings to char*
        if suf == 'str' and elem_type in ('int', 'int64_t', 'char'):
            cp = self._new_temp('char *')
            ip = self._new_val('int64_t', f"(int64_t){val}")
            self._emit(f"  {cp} = (char *){ip};")
            return cp
        return val  # already char*

    def _to_int64(self, ctype: str, val: str) -> str:
        """Cast val to int64_t; emits to a temp so the result is always an lvalue."""
        if ctype == 'int64_t':
            # GIMPLE: can't redundantly cast global int64_t to int64_t; just load
            return self._ensure_local('int64_t', val)
        t = self._new_temp('int64_t')
        if ctype.endswith(' *'):
            # Pointer → int64_t requires void* intermediate in GIMPLE
            val_local = self._ensure_local(ctype, val)
            vp = self._new_val('void *', f"(void *){val_local}")
            self._emit(f"  {t} = (int64_t){vp};")
        else:
            # Non-pointer, non-int64_t: load global then cast
            val_local = self._ensure_local(ctype, val)
            self._emit(f"  {t} = (int64_t){val_local};")
        return t

    # ── Method call lowering ──────────────────────────────────────────────

    _RUNTIME_PTRS = frozenset({'MojoList *', 'MojoStr *', 'MojoDict *', 'MojoSet *',
                                'MojoDictIter *', 'MojoSetIter *'})

    def _resolve_member_expr_type(self, node) -> str | None:
        """Resolve the actual C type of a nested member expression like self.parent.
        Returns the C type (e.g. 'Scope*') or None if it can't be resolved."""
        if isinstance(node, IdentExpr):
            # Base case: resolve identifier to its type
            if node.name in self.var_types:
                return self.var_types[node.name]
            # Check struct field types (class names)
            if node.name in self.struct_field_types:
                return node.name + '*'
            return None
        elif isinstance(node, MemberExpr):
            # Recursive case: resolve obj.member
            obj_type = self._resolve_member_expr_type(node.obj)
            if obj_type:
                # Strip pointer if present
                base_type: str
                base_type = _struct_name_of(obj_type)
                if base_type in self.struct_field_types:
                    field_map = self.struct_field_types[base_type]
                    if node.member in field_map:
                        return field_map[node.member]
            return None
        return None

    def _lower_method_call(self, node: CallExpr) -> tuple[str, str]:
        """Lower obj.method(args) — handles module calls, raw C pointers (UnsafePointer) and structs."""
        func = node.func  # MemberExpr

        # Int/scalar MLIR accessors are identity on our scalar representation:
        # `x._int_mlir_index()` / `x.__mlir_index__()` just yield the machine word.
        # (For a real `Int *` receiver, the walked-in Int method handles it.)
        if func.member in ('_int_mlir_index', '__mlir_index__') and not node.args:
            rt, rv = self.lower_expr(func.obj)
            if rt in ('int', 'int64_t', 'int8_t', 'int16_t', 'int32_t',
                      'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', '_Bool'):
                return rt, rv

        # Handle chained attribute calls: os.path.basename(arg) → int64_t_basename(arg)
        if isinstance(func.obj, MemberExpr):
            inner_obj = func.obj.obj
            inner_member = func.obj.member
            outer_member = func.member

            # Handle os.path.* calls
            if isinstance(inner_obj, IdentExpr) and inner_obj.name == 'os' and inner_member == 'path':
                if outer_member == 'basename' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._call_expr('char *', 'int64_t_basename', [(arg_type, arg_val)])
                    return 'char *', t
                elif outer_member == 'splitext' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    root = self._call_expr('char *', 'int64_t_splitext', [(arg_type, arg_val)])
                    # Python splitext(p) is a (root, ext) pair; every call site does
                    # `splitext(p)[0]`. Model it as a 2-element string list so the
                    # subscript recovers the root as a char* (not a single char from
                    # indexing into a bare string). ext is unused by the compiler.
                    lst = self._new_val('MojoList *', "mojo_list_new ()")
                    self._emit_call('void', '', 'mojo_list_append_str',
                                    [('MojoList *', lst), ('char *', root)])
                    self._emit_call('void', '', 'mojo_list_append_str',
                                    [('MojoList *', lst), ('char *', '""')])
                    self._elem_types[lst] = 'char *'
                    return 'MojoList *', lst
                elif outer_member == 'expanduser' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._call_expr('char *', 'int64_t_expanduser', [(arg_type, arg_val)])
                    return 'char *', t
                elif outer_member == 'abspath' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._call_expr('int64_t', 'int_abspath', [('int64_t', '0'), (arg_type, arg_val)])
                    return 'int64_t', t
                elif outer_member == 'dirname' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._call_expr('int64_t', 'int_dirname', [('int64_t', '0'), (arg_type, arg_val)])
                    return 'int64_t', t
                elif outer_member == 'join':
                    t = self._new_temp('int64_t')
                    if len(node.args) == 0:
                        self._emit(f'  {t} = (int64_t)0;')
                    elif len(node.args) == 1:
                        # os.path.join(*list) — single arg is a MojoList*
                        arg_type, arg_val = self.lower_expr(node.args[0])
                        if arg_type == 'MojoList *':
                            self._emit_call('int64_t', t, 'int_join_list', [('int64_t', '0'), (arg_type, arg_val)])
                        else:
                            # Single non-list arg: just return it
                            self._emit_call('int64_t', t, 'int_join', [('int64_t', '0'), (arg_type, arg_val), ('int64_t', '0')])
                    else:
                        # os.path.join(a, b) — two path args
                        arg_type, arg_val = self.lower_expr(node.args[0])
                        arg2_type, arg2_val = self.lower_expr(node.args[1])
                        self._emit_call('int64_t', t, 'int_join', [('int64_t', '0'), (arg_type, arg_val), (arg2_type, arg2_val)])
                    return 'int64_t', t
                elif outer_member == 'exists' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._call_expr('int', 'int_exists', [('int64_t', '0'), (arg_type, arg_val)])
                    return 'int', t

        # Handle module method calls: module_name.function(args)
        if isinstance(func.obj, IdentExpr):
            module_name = func.obj.name
            method_name = func.member

            # Check if this is a known module method
            if module_name == 're' and method_name == 'sub':
                # re.sub(pattern, callback, src) → mojo_re_sub_fn(pattern, callback, env, src)
                if len(node.args) >= 3:
                    pat_type, pat_val = self.lower_expr(node.args[0])
                    cb_arg  = node.args[1]
                    src_type, src_val = self.lower_expr(node.args[2])
                    # pattern/src may arrive as int64_t string handles; mojo_re_sub_fn
                    # takes char * (passing an int is a -Wint-conversion error on GCC 14+).
                    if pat_type not in ('char *', 'void *'):
                        pat_val = f"(char *){pat_val}"
                    if src_type not in ('char *', 'void *'):
                        src_val = f"(char *){src_val}"
                    # Resolve callback: may be a closure reference with env
                    if isinstance(cb_arg, IdentExpr) and cb_arg.name in self._closure_envs:
                        # _closure_envs maps inner_name → env_var (NOT lifted_name)
                        # Get the actual lifted function name from _all_closures
                        _outer_cls = getattr(self, '_all_closures', {}).get(self.current_func_name, {})
                        _ci_cb = _outer_cls.get(cb_arg.name)
                        if _ci_cb:
                            lifted_name = _ci_cb.lifted_name
                        else:
                            lifted_name = cb_arg.name
                        env_var = self._closure_envs.get(cb_arg.name, '') or '0'
                        # GIMPLE: &func_name is not allowed; mojo_re_sub_fn takes void*
                        # for the callback, so we store the env and pass NULL as callback.
                        # The runtime uses a global fn pointer set by mojo_re_sub_set_fn.
                        # Simpler: use a global static pointer assigned at file scope.
                        fn_ptr_t = self._new_temp('void *')
                        # Use a static C non-GIMPLE pointer to the function (valid from file scope)
                        static_name = f"_mojo_cb_{lifted_name}"
                        if not hasattr(self, '_cb_statics'):
                            self._cb_statics = {}
                        self._cb_statics[static_name] = lifted_name
                        self._emit(f'  {fn_ptr_t} = {static_name};')
                        env_t = self._new_temp('void *')
                        if env_var != '0':
                            self._emit(f'  {env_t} = (void *){env_var};')
                        else:
                            self._emit(f'  {env_t} = (void *)0;')
                    else:
                        # Fallback: treat callback as a simple function pointer
                        cb_type, cb_val = self.lower_expr(cb_arg)
                        fn_ptr_t = self._new_val('void *', f'(void *){cb_val}')
                        env_t = self._new_val('void *', '(void *)0')
                    t = self._new_temp('char *')
                    # Pass fn_ptr_t as void* (matched to mojo_re_sub_fn param type)
                    self._emit(f'  {t} = mojo_re_sub_fn ({pat_val}, {fn_ptr_t}, {env_t}, {src_val});')
                    return 'char *', t

            if module_name == 'gimple_codegen' and method_name == 'compile_to_gimple':
                # gimple_codegen.compile_to_gimple(src, do_imports=False, filename="") → returns char*
                if len(node.args) >= 1:
                    src_type, src_val = self.lower_expr(node.args[0])
                    # Cast to char* if needed (legacy int-cast strings)
                    if src_type not in ('char *', 'void *'):
                        src_val = f"(char *){src_val}"
                    # Extract do_imports if provided, default to 0 (false)
                    do_imports_val = '0'
                    if len(node.args) >= 2:
                        di_type, di_val = self.lower_expr(node.args[1])
                        do_imports_val = di_val
                    # Extract filename if provided, default to ""
                    filename_val = '""'
                    if len(node.args) >= 3:
                        fn_type, fn_val = self.lower_expr(node.args[2])
                        filename_val = fn_val
                    t = self._new_val('char *', f"gimple_codegen_compile_to_gimple ({src_val}, {do_imports_val}, {filename_val})")
                    return 'char *', t

        ot, ov = self.lower_expr(func.obj)
        method = func.member

        # Check if the value is a temp variable — if so, get its real type from var_types
        if ov.startswith('_t') and ov in self.var_types:
            ot = self.var_types[ov]

        # Resolve actual type for int64_t-stored pointers (e.g. char* returned as int64_t)
        ot_orig = ot
        ot = self._get_actual_type(ot, ov)
        # If _get_actual_type resolved int64_t → a pointer type (MojoDict*, MojoList*, etc.),
        # emit an explicit cast so ov is a properly-typed local — otherwise _emit_call will
        # see matching types and skip the coercion, leaving GCC with an int64_t where a
        # pointer is expected.
        if ot != ot_orig and ot.endswith(' *') and ot_orig == 'int64_t':
            ov_local = self._ensure_local('int64_t', ov)
            ip_cast = self._new_temp('int64_t')
            np_cast = self._new_temp(ot)
            self._emit(f"  {ip_cast} = (int64_t){ov_local};")
            self._emit(f"  {np_cast} = ({ot}){ip_cast};")
            if ov in self._dict_val_types:
                self._dict_val_types[np_cast] = self._dict_val_types[ov]
            ov = np_cast

        # For member expressions like self.parent, try to resolve the actual struct type
        if ot in ('int', 'int64_t') and isinstance(func.obj, MemberExpr):
            resolved_type = self._resolve_member_expr_type(func.obj)
            if resolved_type:
                ot = resolved_type

        # Recover struct type from self parameter in method context
        # If we're in a method and calling a method on self (or self.field), resolve the struct type
        if 'self' in self.var_types and ot == 'int64_t':
            self_type = self.var_types.get('self', 'int64_t')
            if self_type.endswith(' *'):
                # We're in a method with typed self — try to use that context
                base_self_type = _struct_name_of(self_type)
                if isinstance(func.obj, MemberExpr) and isinstance(func.obj.obj, IdentExpr) and func.obj.obj.name == 'self':
                    # Method call on self.field — try to find field type and resolve
                    self_struct_fields = self.struct_field_types.get(base_self_type, {})
                    field_type = self_struct_fields.get(func.obj.member)
                    if field_type:
                        ot = field_type  # Use the resolved field type

        # ── Class/static method call: ClassName.method(args) → ClassName_method(args) ──────
        # Must intercept BEFORE the opaque-int coerce below, which would misidentify
        # 'join' as a string method and corrupt the class ref.
        if ot == 'int' and isinstance(func.obj, IdentExpr) and func.obj.name in self.struct_field_types:
            struct_name = func.obj.name
            mangled = f"{struct_name}_{_safe_name(method)}"
            ret_type = self.func_return_types.get(f"{struct_name}_{method}", 'char *')
            actual_args = [self.lower_expr(a) for a in node.args]
            # Keyword arguments (e.g. TestReport.skipped(name=...)) are real
            # parameters — append their values after the positional ones so the
            # call arity matches the definition.
            for _kn, _kexpr in (getattr(node, 'kwargs', None) or []):
                actual_args.append(self.lower_expr(_kexpr))
            # @staticmethod methods take no implicit cls arg
            if mangled in self._static_methods:
                arg_pairs = actual_args
            else:
                arg_pairs = [(ot, ov)] + actual_args
            if ret_type == 'void':
                return self._void_call(mangled, arg_pairs)
            t = self._call_expr(ret_type, mangled, arg_pairs)
            return ret_type, t

        # ── Opaque int → coerce to appropriate container type FIRST ──────────
        # Must happen before container-type checks so the casted type is seen below.
        if ot in ('int', 'int64_t') and method in (
            'keys', 'values', 'items', 'get', 'update', 'pop', 'copy',
            'append', 'extend', 'sort', 'reverse', 'clear',
            'add', 'discard', 'remove',
            'startswith', 'endswith', 'strip', 'lstrip', 'rstrip',
            'split', 'join', 'replace', 'find', 'lower', 'upper',
            'format', 'encode',
        ):
            ip = self._new_temp('int64_t')
            ov_local = self._ensure_local(ot, ov)
            if ot == 'int64_t':
                self._emit(f"  {ip} = {ov_local};")  # same type, no cast
            else:
                self._emit(f"  {ip} = (int64_t){ov_local};")
            if method in ('keys', 'values', 'items', 'get', 'update'):
                dp = self._new_val('MojoDict *', f"(MojoDict *){ip}")
                if ov in self._dict_val_types:
                    self._dict_val_types[dp] = self._dict_val_types[ov]
                ot, ov = 'MojoDict *', dp
            elif method in ('append', 'extend', 'sort', 'reverse', 'clear'):
                lp = self._new_val('MojoList *', f"(MojoList *){ip}")
                ot, ov = 'MojoList *', lp
            elif method in ('add', 'discard', 'remove'):
                sp = self._new_val('MojoSet *', f"(MojoSet *){ip}")
                ot, ov = 'MojoSet *', sp
            else:
                cp = self._new_val('char *', f"(char *){ip}")
                ot, ov = 'char *', cp

        # ── Container / pointer / scalar dispatch ────────────────────────────
        if ot == 'MojoDict *':
            return self._lower_dict_method(ov, method, node.args)
        if ot == 'MojoList *':
            return self._lower_list_method(ov, method, node.args)
        if ot == 'MojoSet *':
            return self._lower_set_method(ov, method, node.args)
        _RAW_PTR_METHODS = frozenset({
            'load', 'store', 'offset', 'free', 'bitcast', 'address_of',
            'destroy_pointee', 'take_pointee', 'initialize_pointee',
            'init_pointee_copy', 'init_pointee_move', 'init_pointee_explicit_copy',
            'strided_load', 'gather', 'strided_store', 'scatter',
            'unsafe_mut_cast', 'unsafe_origin_cast', 'unsafe_ptr_cast',
            'origin_cast', 'mut_cast', 'decay', 'as_noalias_ptr',
        })
        if ot.endswith(' *') and ot not in self._RUNTIME_PTRS and method in _RAW_PTR_METHODS:
            return self._lower_pointer_method(ov, ot, method, node.args)
        if ot == 'void *':
            return self._lower_file_method(ov, method, node.args)

        # char* string method calls
        if ot == 'char *':
            return self._lower_str_method(ov, method, node.args)

        # File handle operations (int64_t handles from mojo_open_file)
        if ot in ('int', 'int64_t'):
            if method == 'read' and not node.args:
                t = self._new_val('char *', f"int_read ({ov})")
                return 'char *', t
            if method == 'write' and node.args:
                data_type, data_val = self.lower_expr(node.args[0])
                # Generic coercion: int_write expects (int64_t, char*)
                ov_cast = self._coerce_to_type(ot, 'int64_t', ov)
                data_val_cast = self._coerce_to_type(data_type, 'char *', data_val)
                t = self._new_val('int64_t', f"int_write ({ov_cast}, {data_val_cast})")
                return 'int64_t', t
            if method == 'close':
                # Stub: mojo_close is defined by stdlib and may not be visible here
                return self._stub_result('int', '0', f'{ot}.close() — stubbed')

        # Methods on any scalar numeric type (int32_t, uint8_t, etc.) —
        # lower comparison/arithmetic methods to direct C expressions.
        _ALL_SCALARS = frozenset({
            'int', 'int64_t', 'int32_t', 'int16_t', 'int8_t',
            'unsigned int', 'uint64_t', 'uint32_t', 'uint16_t', 'uint8_t',
            '_Bool', 'double', 'float',
        })
        if ot in _ALL_SCALARS:
            # Load the object into a properly-typed local (GIMPLE: no compound exprs).
            if ot != self.var_types.get(ov, ot):
                ov_local = self._new_val(ot, f"({ot}){ov}")
            else:
                ov_local = self._ensure_local(ot, ov)
            if node.args:
                at, av = self.lower_expr(node.args[0])
                # Coerce argument to the same type; GIMPLE requires separate cast stmt
                if at != ot:
                    av_cast = self._new_val(ot, f"({ot}){av}")
                    av_local = av_cast
                else:
                    av_local = self._ensure_local(at, av)
            else:
                av_local = ov_local
            _CMP_OPS = {
                'eq': '==', 'ne': '!=', '__ne__': '!=',
                'lt': '<',  '__lt__': '<',
                'le': '<=', '__le__': '<=',
                'gt': '>',  '__gt__': '>',
                'ge': '>=', '__ge__': '>=',
            }
            if method in _CMP_OPS:
                t = self._new_temp('_Bool')
                op = _CMP_OPS[method]
                self._emit(f"  {t} = {ov_local} {op} {av_local};")
                return '_Bool', t
            if method in ('cast', '__cast__', '__int__', '__index__', 'value', 'cast_value'):
                t = self._new_temp(ot); self._emit(f"  {t} = {ov_local};"); return ot, t
            if method == 'select' and len(node.args) >= 2:
                # Bool.select(true_val, false_val) — ternary. GIMPLE COND_EXPR
                # requires both branches and the result to share one type, so
                # unify them (e.g. a double and an int64_t branch → double).
                tt, tv = self.lower_expr(node.args[0])
                ft, fv = self.lower_expr(node.args[1])
                res_type = TypeLattice.join(tt, ft)
                tv_local = self._ensure_local(tt, tv)
                if tt != res_type:
                    tmp = self._new_temp(res_type)
                    self._safe_coerce_emit(tt, res_type, tv_local, tmp)
                    tv_local = tmp
                fv_local = self._ensure_local(ft, fv)
                if ft != res_type:
                    tmp = self._new_temp(res_type)
                    self._safe_coerce_emit(ft, res_type, fv_local, tmp)
                    fv_local = tmp
                t = self._new_val(res_type, f"{ov_local} ? {tv_local} : {fv_local}")
                return res_type, t
            # Other scalar methods: pass the receiver through unchanged
            for ea in node.args[1:]: self.lower_expr(ea)
            return self._stub_result(ot, ov_local, f'{ot}.{method}() stubbed')

        # Stub string-type methods when called on wrong receiver types
        if method == 'isdigit':
            return self._stub_result('int', '0', f'{ot}.isdigit() stubbed')
        if method == 'endswith' and ot not in ('char *', 'void *') and (not ot.endswith(' *') or ot in ('MojoSet *', 'MojoList *', 'MojoDict *')):
            return self._stub_result('int', '0', f'{ot}.endswith() stubbed')
        if method in ('strip', 'lstrip', 'rstrip') and ot not in ('char *', 'void *') and not ot.startswith('Mojo'):
            # strip/lstrip/rstrip on non-string: these already have TODO stubs,
            # but catch cases where they'd generate an invalid method name
            if ot in ('int', 'int64_t', '_Bool', 'double'):
                return self._stub_result('char *', self._intern_string(''), f'{ot}.{method}() stubbed')
        if method == 'get' and ot in ('_Bool', 'int', 'int64_t', 'double'):
            for a in node.args: self.lower_expr(a)
            return self._stub_result('int64_t', '(int64_t)0', f'{ot}.get() stubbed')
        if method in ('strip', 'lstrip', 'rstrip') and ot in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            for a in node.args: self.lower_expr(a)
            return self._stub_result('int', '0', f'{ot}.{method}() stubbed')
        # Stub string methods called on Mojo container types (would generate invalid struct method)
        if method in ('replace', 'find', 'lower', 'upper', 'join', 'split', 'format',
                      'startswith', 'encode', 'decode') and ot in ('MojoSet *', 'MojoList *', 'MojoDict *'):
            for a in node.args: self.lower_expr(a)
            return self._stub_result('char *', self._intern_string(''), f'{ot}.{method}() stubbed')

        # MojoSet.copy() → mojo_set_copy()
        if method == 'copy' and ot == 'MojoSet *':
            t = self._call_expr('MojoSet *', 'mojo_set_copy', [('MojoSet *', ov)])
            return 'MojoSet *', t

        # .values()/.items() called on wrong receiver: unbox int64_t to MojoDict * first
        if method in ('values', 'items') and ot in ('MojoList *', 'int64_t', 'int'):
            vp = self._new_temp('void *'); self._emit(f"  {vp} = (void *){ov};")
            dp = self._new_temp('MojoDict *'); self._emit(f"  {dp} = (MojoDict *){vp};")
            rt = 'MojoList *'
            t = self._new_temp(rt)
            fn = 'mojo_dict_values' if method == 'values' else 'mojo_dict_items'
            self._emit_call(rt, t, fn, [('MojoDict *', dp)])
            return rt, t

        # Method calls on boxed int64_t values (dict/list elements stored as pointers-as-int64_t)
        # Unbox to the actual struct type and call the real method.
        if ot in ('int64_t', 'int') and method in ('emit_typedef', 'emit_table_init', 'emit_dispatch_call'):
            for a in node.args: self.lower_expr(a)
            vp = self._new_temp('void *'); self._emit(f"  {vp} = (void *){ov};")
            dt = self._new_temp('DispatchTable *'); self._emit(f"  {dt} = (DispatchTable *){vp};")
            ret = 'char *'
            t = self._call_expr(ret, f'DispatchTable_{method}', [('DispatchTable *', dt)])
            return ret, t

        # Opaque Python object (int-typed): use mojo_obj_call1 for generic method dispatch
        if ot in ('int', 'int64_t') and not (isinstance(func.obj, IdentExpr)
                                               and func.obj.name in self.struct_field_types):
            method_slit = self._intern_string(_c_escape(method))
            method_key = self._new_val('char *', f"{method_slit}")
            obj64 = self._to_int64(ot, ov)
            # Lower the first argument (if any), or pass 0
            if node.args:
                arg_type, arg_val = self.lower_expr(node.args[0])
                arg64 = self._new_temp('int64_t')
                self._safe_coerce_emit(arg_type, 'int64_t', arg_val, arg64)
            else:
                arg64 = self._new_val('int64_t', "(int64_t)0")
            t = self._call_expr('int64_t', 'mojo_obj_call1',
                            [('int64_t', obj64), ('char *', method_key), ('int64_t', arg64)])
            # Lower remaining args (for side effects) even though we can't pass them
            for extra_arg in node.args[1:]:
                self.lower_expr(extra_arg)
            return 'int64_t', t

        # Struct method call: obj.method(args) → StructName_method(self, args)
        return self._lower_struct_method_call(ov, ot, method, node)

    # ── Method call sub-dispatchers ───────────────────────────────────────

    def _lower_dict_method(self, ov: str, method: str, args: list) -> tuple:
        """Lower MojoDict * method calls."""
        if method == 'keys':
            t = self._new_val('MojoList *', f"mojo_dict_keys ({ov})")
            self._elem_types[t] = 'char *'
            return 'MojoList *', t
        if method == 'values':
            return 'MojoList *', self._new_val('MojoList *', f"mojo_dict_values ({ov})")
        if method == 'items':
            return 'MojoList *', self._new_val('MojoList *', f"mojo_dict_items ({ov})")
        if method == 'get' and args:
            key_type, key_val = self.lower_expr(args[0])
            if len(args) > 1:
                _, _default_val = self.lower_expr(args[1])
            # Ensure key is char * for dict operations
            if key_type != 'char *':
                key_val = self._new_val('char *', f"(char *){key_val}")
                key_type = 'char *'
            val_type = self._dict_val_of(ov)
            if val_type == 'char *':
                return 'char *', self._call_expr('char *', 'mojo_dict_get_str', [('MojoDict *', ov), (key_type, key_val)])
            elif val_type == 'double':
                return 'double', self._call_expr('double', 'mojo_dict_get_double', [('MojoDict *', ov), (key_type, key_val)])
            else:
                return 'int64_t', self._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (key_type, key_val)])
        if method == 'update' and args:
            other_type, other_val = self.lower_expr(args[0])
            ov_cast = self._coerce_to_type('MojoDict *', 'MojoDict *', ov)
            other_val_cast = self._coerce_to_type(other_type, 'MojoDict *', other_val)
            self._emit(f"  mojo_dict_update ({ov_cast}, {other_val_cast});")
            return 'int', self._new_val('int', '0')
        if method == 'pop' and args:
            key_type, key_val = self.lower_expr(args[0])
            if key_type != 'char *':
                key_val = self._new_val('char *', f"(char *){key_val}")
                key_type = 'char *'
            return 'int64_t', self._call_expr('int64_t', 'mojo_dict_pop_int', [('MojoDict *', ov), (key_type, key_val)])
        if method in ('copy',):
            return 'MojoDict *', self._new_val('MojoDict *', f"mojo_dict_copy ({ov})")
        if method == 'clear':
            self._emit(f"  mojo_dict_free ({ov});")
            return 'int', self._new_val('int', '0')
        if method == 'setdefault' and args:
            key_type, key_val = self.lower_expr(args[0])
            return 'int64_t', self._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (key_type, key_val)])
        return 'int64_t', self._new_val('int64_t', '0')

    def _lower_list_method(self, ov: str, method: str, args: list) -> tuple:
        """Lower MojoList * method calls."""
        if method == 'append' and args:
            at, av = self.lower_expr(args[0])
            if at == 'char *':
                self._emit_call('void', '', 'mojo_list_append_str', [('MojoList *', ov), ('char *', av)])
                self._elem_types[ov] = 'char *'
            else:
                self._emit_call('void', '', 'mojo_list_append_int', [('MojoList *', ov), (at, av)])
                if at.endswith(' *') or (at == 'int64_t' and av in self._actual_types and self._actual_types[av].endswith(' *')):
                    actual_elem = self._actual_types.get(av, at)
                    self._elem_types[ov] = actual_elem
                    if actual_elem == 'MojoList *' and av in self._elem_types:
                        self._nested_elem_types[ov] = self._elem_types[av]
            return 'int', self._new_val('int', '0')
        if method == 'extend' and args:
            at, av = self.lower_expr(args[0])
            self._emit_call('void', '', 'mojo_list_extend', [('MojoList *', ov), (at, av)])
            if at == 'MojoList *' and av in self._elem_types:
                self._elem_types[ov] = self._elem_types[av]
                if av in self._nested_elem_types:
                    self._nested_elem_types[ov] = self._nested_elem_types[av]
            return 'int', self._new_val('int', '0')
        if method == 'pop':
            return 'int64_t', self._new_val('int64_t', f"mojo_list_pop ({ov})")
        if method in ('sort', 'reverse', 'clear'):
            self._emit(f"  mojo_list_{method} ({ov});")
            return 'int', self._new_val('int', '0')
        if method == 'copy':
            return 'MojoList *', self._new_val('MojoList *', f"mojo_list_copy ({ov})")
        if method == 'remove' and args:
            at, av = self.lower_expr(args[0])
            if at == 'char *':
                return self._void_call('mojo_list_remove_str', [('MojoList *', ov), ('char *', av)])
            return self._void_call('mojo_list_remove_int', [('MojoList *', ov), (at, av)])
        if method == 'index' and args:
            at, av = self.lower_expr(args[0])
            if at == 'char *':
                return 'int64_t', self._call_expr('int64_t', 'mojo_list_index_str', [('MojoList *', ov), ('char *', av)])
            return 'int64_t', self._call_expr('int64_t', 'mojo_list_index_int', [('MojoList *', ov), ('int64_t', av)])
        return 'int', self._new_val('int', '0')

    def _lower_set_method(self, ov: str, method: str, args: list) -> tuple:
        """Lower MojoSet * method calls."""
        if method == 'update' and args:
            other_type, other_val = self.lower_expr(args[0])
            if other_type != 'MojoSet *':
                other_val = self._new_val('MojoSet *', f"(MojoSet *){other_val}")
                other_type = 'MojoSet *'
            return self._void_call('mojo_set_update', [('MojoSet *', ov), ('MojoSet *', other_val)])
        if method == 'add' and args:
            at, av = self.lower_expr(args[0])
            if at == 'char *':
                return self._void_call('mojo_set_add_str', [('MojoSet *', ov), ('char *', av)])
            return self._void_call('mojo_set_add_int', [('MojoSet *', ov), ('int64_t', av)])
        if method == 'discard' and args:
            at, av = self.lower_expr(args[0])
            return self._void_call('mojo_set_discard', [('MojoSet *', ov), (at, av)])
        if method == 'copy':
            return 'MojoSet *', self._call_expr('MojoSet *', 'mojo_set_copy', [('MojoSet *', ov)])
        return 'int', self._new_val('int', '0')

    def _lower_pointer_method(self, ov: str, ot: str, method: str, args: list) -> tuple:
        """Lower raw pointer (UnsafePointer) method calls."""
        elem = _elem_type(ot)
        if method == 'load':
            return elem, self._new_val(elem, f"*{ov}")
        if method == 'store' and args:
            at, av = self.lower_expr(args[0])
            # Spill through a register: a pointer→int64_t coercion is a double cast
            # `(int64_t)(void*)x` which GIMPLE rejects inside `*p = ...`.
            ovl = self._ensure_local(ot, ov)
            sv = self._new_temp(elem)
            self._safe_coerce_emit(self._quick_type(args[0]), elem, av, sv)
            self._emit(f"  *{ovl} = {sv};")
            return 'int', self._new_val('int', '0')
        if method == 'offset' and args:
            _, nv = self.lower_expr(args[0])
            cn = _c_id(elem)
            self._ptr_helpers_needed.add(elem)
            idx64 = self._new_val('int64_t', f"(int64_t) {nv}")
            return ot, self._new_val(ot, f"_mojo_at_{cn} ({ov}, {idx64})")
        if method == 'free':
            self._emit(f"  free ({ov});")
            return 'int', self._new_val('int', '0')
        if method in ('bitcast', 'address_of',
                      'unsafe_mut_cast', 'unsafe_origin_cast', 'unsafe_ptr_cast',
                      'origin_cast', 'mut_cast', 'decay', 'as_noalias_ptr'):
            t = self._new_temp(ot)
            self._emit(f"  {t} = {ov};  /* {method}: pass-through */")
            return ot, t
        if method in ('destroy_pointee', 'take_pointee', 'initialize_pointee',
                      'init_pointee_copy', 'init_pointee_move', 'init_pointee_explicit_copy'):
            # Placement init/copy/move all write the value into the pointee.
            if args and method != 'destroy_pointee' and method != 'take_pointee':
                at, av = self.lower_expr(args[0])
                # GIMPLE requires the pointer operand of `*` to be a register, so
                # spill ov (which may be a member access like self->_data) first.
                # Spill the value too: a pointer→int64_t coercion is a double cast
                # `(int64_t)(void*)x` that GIMPLE rejects inside `*p = ...`.
                ovl = self._ensure_local(ot, ov)
                sv = self._new_temp(elem)
                self._safe_coerce_emit(at, elem, av, sv)
                self._emit(f"  *{ovl} = {sv};")
            return 'int', self._new_val('int', '0')
        if method in ('strided_load', 'gather'):
            return self._stub_result(elem, f'*{ov}', f'TODO: {method}')
        if method in ('strided_store', 'scatter'):
            return self._stub_result('int', '0', f'TODO: {method}')
        return 'int', self._new_val('int', '0')

    def _lower_file_method(self, ov: str, method: str, args: list) -> tuple:
        """Lower void * file-handle method calls."""
        if method == 'write' and args:
            data_type, data_val = self.lower_expr(args[0])
            if data_type == 'char *':
                return 'int64_t', self._new_val('int64_t', f"mojo_write ({ov}, {data_val}, -1)")
        if method == 'close':
            self._emit(f"  mojo_close ({ov});")
            return 'int', self._new_val('int', '0')
        return 'int', self._new_val('int', '0')

    def _lower_str_method(self, ov: str, method: str, args: list) -> tuple:
        """Lower char * string method calls."""
        arg_pairs = [(self.lower_expr(a)[0], self.lower_expr(a)[1]) for a in args]
        loaded_args = []
        for at, av in arg_pairs:
            if av.startswith('_slit_') or av in self._str_pool.values():
                av = self._new_val(at, f'{av}')
            loaded_args.append(av)
        arg_vals = loaded_args
        stored_type = self.var_types.get(ov, 'char *')
        if stored_type == 'int64_t':
            cstr_ov = self._new_val('char *', f"(char *){ov}")
        else:
            cstr_ov = ov
        if method == 'group':
            return 'char *', cstr_ov
        _CSTR_METHODS: dict[str, str] = {
            'lower': 'string_lower', 'upper': 'string_upper',
            'strip': 'string_strip',
            'lstrip': 'mojo_str_lstrip', 'rstrip': 'mojo_str_rstrip',
        }
        if method in _CSTR_METHODS:
            return 'char *', self._new_val('char *', f"{_CSTR_METHODS[method]} ({cstr_ov})")
        if method == 'expandtabs':
            tabsize = arg_vals[0] if arg_vals else '8'
            return 'char *', self._new_val('char *', f"mojo_str_expandtabs ({cstr_ov}, {tabsize})")
        if method == 'join':
            if arg_vals:
                iter_val = arg_vals[0]
                iter_type = arg_pairs[0][0] if arg_pairs else 'MojoList *'
                if iter_type != 'MojoList *':
                    iter_val = self._new_val('MojoList *', f"(MojoList *){iter_val}")
                return 'char *', self._call_expr('char *', 'mojo_str_join', [('char *', cstr_ov), ('MojoList *', iter_val)])
            t = self._new_temp('char *')
            self._emit(f"  {t} = {cstr_ov};  /* join: no iterable */")
            return 'char *', t
        if method == 'startswith' and arg_vals:
            t = self._new_temp('int')
            arg0_type = arg_pairs[0][0] if arg_pairs else 'char *'
            arg0_val = arg_vals[0]
            if arg0_type == 'char':
                self._emit_call('int', t, 'mojo_str_startswith_char', [('char *', cstr_ov), ('char', arg0_val)])
            else:
                self._emit_call('int', t, 'mojo_str_startswith', [('char *', cstr_ov), (arg0_type, arg0_val)])
            return 'int', t
        if method == 'endswith' and arg_vals:
            t = self._new_temp('int')
            arg0_type = arg_pairs[0][0] if arg_pairs else 'char *'
            arg0_val = arg_vals[0]
            if arg0_type == 'char':
                self._emit_call('int', t, 'mojo_str_endswith_char', [('char *', cstr_ov), ('char', arg0_val)])
            else:
                self._emit_call('int', t, 'mojo_str_endswith', [('char *', cstr_ov), (arg0_type, arg0_val)])
            return 'int', t
        if method == 'find' and arg_vals:
            sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
            return 'int64_t', self._call_expr('int64_t', 'mojo_str_find', [('char *', cstr_ov), (sep_type, arg_vals[0])])
        if method == 'split' and arg_vals:
            sep_type = arg_pairs[0][0] if arg_pairs else 'char *'
            t = self._call_expr('MojoList *', 'mojo_str_split', [('char *', cstr_ov), (sep_type, arg_vals[0])])
            self._elem_types[t] = 'char *'
            return 'MojoList *', t
        if method == 'splitlines':
            sep = self._str_literal_to_slit('"\n"')
            sep_tmp = self._new_val('char *', f"{sep}")
            t = self._call_expr('MojoList *', 'mojo_str_split', [('char *', cstr_ov), ('char *', sep_tmp)])
            self._elem_types[t] = 'char *'
            return 'MojoList *', t
        if method in ('encode', 'decode', 'format'):
            return self._stub_result('char *', cstr_ov, f'TODO: {method}')
        # Unknown method on char* — stub
        return self._stub_result('int', '0', f'TODO: char*.{method}')

    def _lower_struct_method_call(self, ov: str, ot: str, method: str, node) -> tuple:
        """Lower struct/class method calls: obj.method(args) → StructName_method(self, args)."""
        func = node.func
        is_class_ref = False
        if isinstance(func.obj, IdentExpr) and func.obj.name in self.struct_field_types:
            struct_name = func.obj.name
            is_class_ref = True
        else:
            struct_name = _struct_name_of(ot)
            if struct_name == 'int' and method in ('set', '__call__'):
                if isinstance(func.obj, MemberExpr) and isinstance(func.obj.obj, IdentExpr):
                    if func.obj.obj.name == 'self':
                        if method == 'set' and func.obj.member == 'parent':
                            struct_name = 'Scope'
        mangled = f"{struct_name}_{_safe_name(method)}"
        ret_type = self.func_return_types.get(f"{struct_name}_{method}", None)
        if ret_type is None and mangled in self._KNOWN_SIGS:
            ret_type = self._KNOWN_SIGS[mangled][0]
        if (ret_type is None and method == 'copy'
                and f"{struct_name}_copy" not in self.func_return_types
                and f"{struct_name}_copy" not in self._KNOWN_SIGS):
            return 'int64_t', self._new_val('int64_t', f"(int64_t){ov}")
        if ret_type is None:
            if method in ('get', 'get_symbol_type', 'pop', 'keys', 'values', 'items'):
                ret_type = 'char *' if method in ('get', 'get_symbol_type', 'pop') else 'MojoList *'
            elif method in ('load',):
                ret_type = 'int64_t'
            else:
                ret_type = 'int64_t'
        arg_pairs = [self.lower_expr(a) for a in node.args]
        full_param_list = self.func_param_types.get(f"{struct_name}_{method}", [])
        if not is_class_ref and full_param_list and full_param_list[0] != f"{struct_name} *":
            is_class_ref = True
        expected_non_self = len(full_param_list) - (0 if is_class_ref else 1)
        if full_param_list and len(arg_pairs) < expected_non_self:
            while len(arg_pairs) < expected_non_self:
                arg_pairs.append(('int', '0'))
        # Auto-stub if the mangled method name has no known declaration
        if (mangled not in self._KNOWN_SIGS
                and f'{struct_name}_{method}' not in self.func_return_types
                and mangled not in self._auto_stubbed):
            _stub_guard = f'_MOJO_STUB_{mangled.upper()}'
            _stub = f'#ifndef {_stub_guard}\n#define {_stub_guard}\nint64_t {mangled} (...);\n#endif'
            if _stub not in self._elaborated_externs:
                self._elaborated_externs.append(_stub)
            self._auto_stubbed.add(mangled)

        if ret_type == 'void':
            all_arg_pairs = arg_pairs if is_class_ref else [(ot, ov)] + arg_pairs
            return self._void_call(mangled, all_arg_pairs)
        all_arg_pairs = ([(ot, ov)] + arg_pairs) if not is_class_ref else arg_pairs
        return ret_type, self._call_expr(ret_type, mangled, all_arg_pairs)

    # ── Call expression lowering ──────────────────────────────────────────

    # libc functions already prototyped by our standard includes; re-declaring them
    # (often as variadic, e.g. printf) would clash, so we never emit our own extern.
    # Symbols that are in _LIBC_DECLARED (so we normally defer to a system header)
    # but whose declaring header is NOT in our prelude (stdio/stdlib/string/math/
    # setjmp/dlfcn). For these, external_call must emit its own prototype from the
    # call's known signature, or the call is an implicit declaration. POSIX file
    # ops live in <unistd.h>/<sys/stat.h> (not included); scalb/scalbf are obsolete
    # and absent from modern <math.h>. Excludes names that also have an unrenamed
    # Mojo wrapper definition (which would collide with the extern).
    _NEEDS_SELF_EXTERN = frozenset({
        'stat', 'lstat', 'fstat', 'access', 'unlink', 'rmdir', 'mkdir',
        'symlink', 'readlink', 'link', 'chmod', 'chown', 'getcwd',
        'scalbf',
        # POSIX fd/process calls our prelude headers don't pull in → emit the
        # extern ourselves (using the _LIBC_SIGS prototype) to avoid implicit decls.
        'dup', 'pipe',
    })
    _LIBC_DECLARED = {
        'printf', 'fprintf', 'snprintf', 'sprintf', 'puts', 'putchar', 'fputs',
        'malloc', 'calloc', 'realloc', 'free', 'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
        'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat', 'abort',
        'strchr', 'strrchr', 'strstr', 'strtok', 'strerror',
        'exit', 'atoi', 'atoll', 'atof', 'atol',
        'strtol', 'strtoll', 'strtoul', 'strtoull', 'strtod', 'strtof', 'strtold',
        'setvbuf', 'setbuf', 'setbuffer', 'setlinebuf',
        'remainderf', 'remainderl',
        'posix_spawn', 'posix_spawnp',
        'index', 'rindex',
        # Math functions (from <math.h>)
        'cos', 'cosf', 'sin', 'sinf', 'tan', 'tanf',
        'acos', 'acosf', 'asin', 'asinf', 'atan', 'atanf', 'atan2', 'atan2f',
        'ceil', 'ceilf', 'floor', 'floorf', 'round', 'roundf', 'trunc', 'truncf',
        'sqrt', 'sqrtf', 'cbrt', 'cbrtf',
        'pow', 'powf', 'exp', 'expf', 'exp2', 'exp2f', 'log', 'logf', 'log2', 'log2f', 'log10', 'log10f',
        'fabs', 'fabsf', 'fmod', 'fmodf',
        'erf', 'erff', 'erfc', 'erfcf', 'tgamma', 'lgamma',
        'ldexp', 'ldexpf', 'frexp', 'frexpf', 'modf', 'modff',
        'sinh', 'sinhf', 'cosh', 'coshf', 'tanh', 'tanhf',
        'asinh', 'acosh', 'atanh', 'asinhf', 'acoshf', 'atanhf',
        'nextafter', 'nextafterf', 'copysign', 'copysignf',
        'nan', 'nanf', 'hypot', 'hypotf', 'fma', 'fmaf', 'remainder',
        'expm1', 'expm1f', 'log1p', 'log1pf',
        'scalb', 'scalbf', 'scalbn', 'scalbnf', 'logb', 'logbf',
        'j0', 'j1', 'y0', 'y1',
        # Environment and system functions
        'getenv', 'setenv', 'unsetenv', 'putenv', 'realpath',
        # Dynamic library functions
        'dlopen', 'dlsym', 'dlclose', 'dlerror',
        # File I/O (from <stdio.h>)
        'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'rewind', 'fflush',
        'fgets', 'fputs', 'feof', 'ferror', 'clearerr', 'fileno',
        'getline', 'getdelim',
        'vprintf', 'vfprintf', 'vsnprintf', 'vsprintf',
        'fdopen', 'popen', 'pclose',
        # stdio streams (not functions, but imported as symbols — skip our extern)
        'stderr', 'stdout', 'stdin',
        # Unix file/process functions (from <unistd.h>, <sys/stat.h>)
        'remove', 'rename', 'access', 'stat', 'lstat', 'fstat', 'unlink', 'rmdir',
        'symlink', 'readlink', 'link', 'mkdir', 'chmod', 'chown',
        'getuid', 'getgid', 'getpid', 'getppid', 'waitpid', 'fork',
        'ioctl', 'fcntl', 'dup', 'dup2', 'pipe',
        # Random functions
        'rand', 'srand', 'random', 'srandom',
        # Standard library utility
        'qsort', 'bsearch', 'abs', 'labs', 'llabs',
        # Character/string classification (ctype.h)
        'isalpha', 'isdigit', 'isalnum', 'isspace', 'isupper', 'islower',
        'toupper', 'tolower',
        # Math classification macros (<math.h>) — declared as macros, not functions
        'isfinite', 'isinf', 'isnan', 'isnormal', 'signbit',
        'fpclassify', 'isunordered', 'isgreater', 'isgreaterequal',
        'isless', 'islessequal', 'islessgreater',
        # POSIX/BSD string extras
        'strdup', 'strndup', 'strtok_r',
        # Time functions
        'time', 'clock', 'difftime', 'mktime', 'strftime',
        'gmtime', 'localtime', 'asctime', 'ctime',
        # Signal
        'signal', 'raise',
        # Wide char (wchar.h)
        'wcslen', 'wcscmp', 'wcscat',
    }

    # Correct signatures for C standard library functions to prevent conflicts
    _LIBC_SIGS: dict[str, tuple[str, list[str]]] = {
        'memcmp': ('int', ['char *', 'char *', 'int']),
        'strlen': ('int', ['char *']),
        'strcmp': ('int', ['char *', 'char *']),
        'strncmp': ('int', ['char *', 'char *', 'int']),
        'strcpy': ('char *', ['char *', 'char *']),
        'strncpy': ('char *', ['char *', 'char *', 'int']),
        'strcat': ('char *', ['char *', 'char *']),
        'getenv': ('char *', ['char *']),
        'realpath': ('char *', ['char *', 'char *']),
        'cos': ('double', ['double']),
        'sin': ('double', ['double']),
        'tan': ('double', ['double']),
        'ceil': ('double', ['double']),
        'floor': ('double', ['double']),
        'sqrt': ('double', ['double']),
        'exp': ('double', ['double']),
        'log': ('double', ['double']),
        'pow': ('double', ['double', 'double']),
        'fabs': ('double', ['double']),
        'erf': ('double', ['double']),
        'erfc': ('double', ['double']),
        'rand': ('int', []),
        'remove': ('int', ['char *']),
        'dlclose': ('int', ['void *']),
        # stdio FILE*-taking calls: FILE* modeled as void* so int64_t-lowered
        # pointer args coerce cleanly (void*→FILE* is implicit in C).
        'pclose': ('int', ['void *']),
        'fclose': ('int', ['void *']),
        'fflush': ('int', ['void *']),
        'popen': ('void *', ['char *', 'char *']),
        'fdopen': ('void *', ['int', 'char *']),
        'setvbuf': ('int', ['void *', 'char *', 'int', 'int64_t']),
        # Dynamic-linker + POSIX process/fd calls: pin the C signatures so int64_t-
        # lowered handle/string/array args coerce to the pointer types the system
        # headers declare (dlfcn.h, sys/wait.h, unistd.h) instead of clashing.
        'dlopen': ('void *', ['char *', 'int']),
        'dlsym': ('void *', ['void *', 'char *']),
        'waitpid': ('int', ['int', 'int *', 'int']),
        'dup': ('int', ['int']),
        'dup2': ('int', ['int', 'int']),
        'pipe': ('int', ['int *']),
        'fcntl': ('int', ['int', 'int', 'int64_t']),
    }

    def _type_expr_to_ann(self, node) -> str:
        """Reconstruct a type-annotation string from a type expression node, so
        parametric types in external_call/MLIR positions resolve via _mojo_type.
        e.g. UnsafePointer[Int8] -> 'UnsafePointer[Int8]', c_ssize_t -> 'c_ssize_t'."""
        if isinstance(node, IdentExpr):
            return node.name
        if isinstance(node, SubscriptExpr):
            base = self._type_expr_to_ann(node.obj)
            idx = node.index
            parts = idx.elements if isinstance(idx, TupleExpr) else [idx]
            inner = ', '.join(self._type_expr_to_ann(p) for p in parts)
            return f"{base}[{inner}]"
        if isinstance(node, MemberExpr):
            return f"{self._type_expr_to_ann(node.obj)}.{node.member}"
        return ''

    def _elaborate_generic_call(self, node: CallExpr):
        """Elaborate a call to an imported generic into a concrete CAS-cached
        instantiation. Handles both the explicit form `Generic[TypeArgs](args)`
        and the inferred form `Generic(args)` (type args inferred from argument
        types — slice 2). Returns (ctype, val) if elaborated, else None."""
        explicit = isinstance(node.func, SubscriptExpr)
        g = node.func.obj.name if explicit else node.func.name
        source = self._imported_generics.get(g)
        if not source:
            return None
        # Lower args once; their C types drive inference (and the emitted call).
        # Append keyword-argument values after the positionals (they fill the
        # trailing params in order — e.g. `_async_execute[T](h, desired_worker_id=-1)`).
        arg_pairs = [self.lower_expr(a) for a in node.args]
        for _kn, _kexpr in (getattr(node, 'kwargs', None) or []):
            arg_pairs.append(self.lower_expr(_kexpr))
        try:
            module_src = open(source).read()
            import elaborate
            el = elaborate.Elaborator()
            if explicit:
                idx = node.func.index
                elems = idx.elements if isinstance(idx, TupleExpr) else [idx]
                type_args = [self._type_expr_to_ann(e) for e in elems]
                # Only instantiate for CONCRETE type args. Inside a still-generic
                # body the args are unbound type parameters (U, Self.T, *Ts,
                # Self.Types[i]); "instantiating" those just substitutes symbol for
                # symbol and recurses without converging — the call must stay
                # generic and resolve when the OUTER generic is instantiated.
                if not all(_is_concrete_type_arg(t) for t in type_args):
                    return None
                info = el.elaborate_generic_call(module_src, g, type_args)
            else:
                info = el.elaborate_generic_call_inferred(
                    module_src, g, [ct for ct, _ in arg_pairs])
        except Exception as e:
            _debug_note('generic call elaboration failed', e)
            info = None
        if not info:
            return None
        return self._emit_generic_instantiation(info, arg_pairs)

    def _elaborate_generic_struct_call(self, node: CallExpr):
        """Elaborate Struct[TypeArgs](args): materialize the concrete monomorphized
        struct (register its layout + typedef, declare its methods, record its
        object on the link line), then lower the call as a constructor."""
        g = node.func.obj.name
        source = self._imported_generic_structs.get(g)
        if not source:
            return None
        idx = node.func.index
        elems = idx.elements if isinstance(idx, TupleExpr) else [idx]
        type_args = [self._type_expr_to_ann(e) for e in elems]
        try:
            module_src = open(source).read()
            import elaborate
            info = elaborate.Elaborator().elaborate_generic_struct(module_src, g, type_args)
        except Exception as e:
            _debug_note('generic struct elaboration failed', e)
            info = None
        if not info or not info['fields']:
            return None

        name = info['name']
        if name not in self.struct_field_types:
            # Register the layout; the struct-typedef section emits the typedef.
            self.struct_field_types[name] = {f: ct for f, ct in info['fields']}
            for mname, ret, ps in info['methods']:
                msym = f"{name}_{mname}"
                self.func_return_types[msym] = ret
                self.func_param_types[msym] = [f"{name} *"] + ps
                decl = (f"extern {ret} {msym} "
                        f"({', '.join([name + ' *'] + ps) or 'void'});")
                if decl not in self._elaborated_externs:
                    self._elaborated_externs.append(decl)
        if info['object'] not in self._link_objects:
            self._link_objects.append(info['object'])

        return self._lower_struct_constructor(name, node.args, getattr(node, 'kwargs', None))

    def _elaborate_overload_call(self, node: CallExpr):
        """Resolve and elaborate an overloaded imported call (slice 4): lower the
        args, pick the matching overload by their C types, and emit the call to the
        signature-mangled concrete symbol."""
        g = node.func.name
        source = self._imported_overloads.get(g)
        if not source:
            return None
        arg_pairs = [self.lower_expr(a) for a in node.args]
        try:
            module_src = open(source).read()
            import elaborate
            info = elaborate.Elaborator().elaborate_overload_call(
                module_src, g, [ct for ct, _ in arg_pairs])
        except Exception as e:
            _debug_note('overload elaboration failed', e)
            info = None
        if not info:
            return None
        return self._emit_generic_instantiation(info, arg_pairs)

    def _emit_generic_instantiation(self, info, arg_pairs):
        """Record an elaborated instantiation (object on the link line, extern in
        the preamble, signature for calls) and emit the concrete call."""
        sym = info['symbol']
        # A re-entrant (recursive-cycle) instantiation returns object=None — the
        # real .o is contributed by the outer frame; don't add a null link entry.
        if info['object'] is not None and info['object'] not in self._link_objects:
            self._link_objects.append(info['object'])
        self.func_return_types[sym] = info['ret']
        self.func_param_types[sym] = info['params']
        _decl = f"extern {info['ret']} {sym} ({', '.join(info['params']) or 'void'});"
        if _decl not in self._elaborated_externs:
            self._elaborated_externs.append(_decl)
        if info['ret'] == 'void':
            self._emit_call('', '', sym, arg_pairs)
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;  /* void generic call */")
            return 'int', t
        t = self._call_expr(info['ret'], sym, arg_pairs)
        return info['ret'], t

    def _lower_external_call(self, node: CallExpr) -> tuple[str, str]:
        """Lower external_call["name", Ret](args) / _external_call_const[...] to a
        direct C call.  This is the irreducible primitive the stdlib bottoms out on
        (e.g. FileDescriptor.write_bytes → external_call["write", c_ssize_t](...)).

        The subscript index is `"name"` or `("name", RetType, *ParamTypes)`.  We take
        the name and return type from the index and the argument C types from the
        lowered call arguments, then register one extern prototype per name (first use
        wins) for emission in the preamble.
        """
        idx = node.func.index
        elems = idx.elements if isinstance(idx, TupleExpr) else [idx]

        cname = elems[0].value if elems and isinstance(elems[0], StringLiteral) else None
        if not cname:
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;  /* external_call with non-literal name */")
            return 'int', t

        ret_ct = 'void'
        if len(elems) >= 2:
            ann = self._type_expr_to_ann(elems[1])
            if ann == 'NoneType':
                ret_ct = 'void'
            elif ann:
                ret_ct = _mojo_type(ann)
        # _KNOWN_SIGS takes precedence over Mojo type annotation (e.g. Scalar[T] → int64_t)
        # when the C function has a non-int64_t return type (float, double, FILE*, etc.)
        # Also check _LIBC_SIGS for C stdlib functions like getenv → char*
        if cname in self._KNOWN_SIGS:
            ret_ct = self._KNOWN_SIGS[cname][0]
        elif cname in self._LIBC_SIGS:
            ret_ct = self._LIBC_SIGS[cname][0]

        arg_pairs = [self.lower_expr(a) for a in node.args]
        # Pad to the known libc arity: a Mojo FFI wrapper may forward fewer args than
        # the C function takes (e.g. `external_call["setvbuf"](stream, buffer)` vs the
        # 4-arg libc setvbuf). Supplying 0 for the trailing params gives a defined call
        # that matches <stdio.h>, instead of a "too few arguments" clash. (Whether the
        # wrapper SHOULD forward its mode/size is an upstream-source question; this just
        # makes the binding compile with defined behavior rather than reading garbage.)
        if cname in self._LIBC_SIGS:
            _sig_params = self._LIBC_SIGS[cname][1]
            while len(arg_pairs) < len(_sig_params):
                arg_pairs.append((_sig_params[len(arg_pairs)], '0'))
        # First use wins: pin the prototype's parameter types and coerce later calls to match.
        # Never register LIBC functions - let system headers provide them
        if cname not in self._external_protos and (
                cname not in self._LIBC_DECLARED or cname in self._NEEDS_SELF_EXTERN):
            # Prefer the pinned libc signature for the prototype so a self-emitted
            # extern (e.g. `int pipe(int *)`) matches the coerced call args rather
            # than the raw int64_t-lowered argument types.
            _proto_params = (self._LIBC_SIGS[cname][1] if cname in self._LIBC_SIGS
                             else [at for (at, _) in arg_pairs])
            self._external_protos[cname] = (ret_ct, _proto_params)
        # Track param types for coercion, even if not emitting declaration
        if cname not in self.func_param_types:
            if cname in self._LIBC_SIGS:
                self.func_param_types[cname] = self._LIBC_SIGS[cname][1]
            elif cname in self._external_protos:
                self.func_param_types[cname] = self._external_protos[cname][1]
            else:
                self.func_param_types[cname] = [at for (at, _) in arg_pairs]

        if ret_ct == 'void':
            self._emit_call('', '', cname, arg_pairs)
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;  /* void external_call result */")
            return 'int', t
        t = self._call_expr(ret_ct, cname, arg_pairs)
        if ret_ct == 'void *' and cname in ('dlopen', 'dlsym'):
            # The dynamic-linker handle functions return void* but Mojo models the
            # handle as int64_t (c_void_ptr). Coerce through a register so the
            # surrounding int64_t store/return is a valid single cast rather than a
            # void*→int64_t direct assignment. (FILE*-returning calls like fopen/
            # popen keep void* — their results stay pointers.)
            ct = self._new_temp('int64_t')
            self._emit(f"  {ct} = (int64_t){t};")
            return 'int64_t', ct
        return ret_ct, t

    def _maybe_lower_mlir_op(self, node: CallExpr):
        """Lower a ``__mlir_op.\\`dialect.op\\`[attrs](args)`` call via mlir.py.

        The callee is either a ``MemberExpr`` on ``__mlir_op`` (no attr params) or
        a ``SubscriptExpr`` wrapping that member (the ``[...]`` attribute params).
        Returns ``(ctype, val)`` if handled, else ``None`` so normal dispatch runs.
        """
        func = node.func
        attr_members: list[str] = []
        named_attrs: dict[str, object] = {}   # param name → literal value (when an __mlir_attr)
        if isinstance(func, SubscriptExpr):
            # Collect the op's [name=value] params. __mlir_attr literals feed both
            # index.cmp's predicate (flat list) and struct GEP's index= (by name).
            for _name, _val in (getattr(func, 'attrs', None) or []):
                if isinstance(_val, MemberExpr) and isinstance(_val.obj, IdentExpr) \
                        and _val.obj.name == '__mlir_attr':
                    attr_members.append(_val.member)
                    if _name:
                        kind, v = mlir.parse_attr(_val.member)
                        if kind in ('int', 'simd'):
                            named_attrs[_name] = v
            func = func.obj
        if not (isinstance(func, MemberExpr) and isinstance(func.obj, IdentExpr)
                and func.obj.name == '__mlir_op'):
            return None

        arg_pairs = [self.lower_expr(a) for a in node.args]

        # Memory / lvalue ops (load / store / offset) need typed, statement-aware
        # emission; mlir.py classifies, we emit with operand types + ptr helpers.
        mem = mlir.mem_op_kind(func.member)
        if mem is not None:
            return self._lower_mlir_mem(mem, arg_pairs)

        # Struct / aggregate GEP (extract / gep / aget): read the index= field of a
        # known struct. Falls through to the deferred stub when the layout or index
        # isn't statically resolvable.
        sk = mlir.struct_op_kind(func.member)
        if sk is not None:
            res = self._lower_mlir_struct(sk, named_attrs.get('index'), arg_pairs)
            if res is not None:
                return res
            op = mlir.unwrap(func.member)
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = (int64_t)0;  /* mlir __mlir_op.{op}: deferred: unresolved struct index/layout */")
            return 'int64_t', t

        arg_vals = [v for (_, v) in arg_pairs]
        res = mlir.lower_op(func.member, arg_vals, attr_members)
        if res is None:
            # Operands already evaluated; yield 0 so surrounding code still compiles.
            # Distinguish "deferred by design" (GPU/coro/atomics/…) from "not met yet".
            op = mlir.unwrap(func.member)
            reason = mlir.deferral_reason(func.member)
            note = f"deferred: {reason}" if reason else "not modeled"
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = (int64_t)0;  /* mlir __mlir_op.{op}: {note} */")
            return 'int64_t', t
        ctype, expr = res
        t = self._new_val(ctype, f"{expr}")
        return ctype, t

    def _as_ptr(self, ctype: str, val: str) -> tuple[str, str]:
        """Ensure (ctype, val) is a C pointer; if type inference lost it, cast to
        a generic pointer.  Returns (pointer_ctype, pointer_val)."""
        if ctype.endswith(' *'):
            return ctype, val
        pv = self._new_temp('int64_t *')
        v64 = self._ensure_local(ctype, val)
        self._emit(f"  {pv} = (int64_t *) {v64};")
        return 'int64_t *', pv

    def _lower_mlir_mem(self, kind: str, arg_pairs: list) -> tuple[str, str]:
        """Emit a memory/lvalue MLIR op classified by mlir.mem_op_kind().

        load   (addr)        -> *addr
        store  (val, addr)   -> *addr = val          (statement; yields 0)
        offset (ptr, idx)    -> _mojo_at_T(ptr, idx)  (GIMPLE-legal pointer add)
        """
        if kind == 'load':
            at, av = arg_pairs[0]
            pt, pv = self._as_ptr(at, av)
            et = _elem_type(pt)
            t = self._new_val(et, f"*{pv}")
            return et, t

        if kind == 'store':
            (vt, vv), (at, av) = arg_pairs[0], arg_pairs[1]
            pt, pv = self._as_ptr(at, av)
            et = _elem_type(pt)
            sv = vv
            if vt != et:
                sv = self._new_val(et, f"({et}) {vv}")
            self._emit(f"  *{pv} = {sv};")
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = (int64_t)0;  /* pop.store (no value) */")
            return 'int64_t', t

        # offset / array.gep: ptr + idx via the _mojo_at_ helper (pointer
        # arithmetic is illegal inside __GIMPLE).
        (pt0, pv0), (it, iv) = arg_pairs[0], arg_pairs[1]
        pt, pv = self._as_ptr(pt0, pv0)
        et = _elem_type(pt)
        cn = _c_id(et)
        self._ptr_helpers_needed.add(et)
        idx64 = self._new_val('int64_t', f"(int64_t) {iv}")
        addr = self._new_val(pt, f"_mojo_at_{cn} ({pv}, {idx64})")
        return pt, addr

    def _lower_mlir_struct(self, kind: str, index, arg_pairs: list):
        """Emit a struct/aggregate GEP op (extract / gep / aget) classified by
        mlir.struct_op_kind().  Returns (ctype, val) when the struct layout and
        a literal field index are resolvable, else None (caller → deferred stub).

        extract (struct_val) -> struct_val.fieldN     (N-th field value)
        gep     (struct_ptr) -> &struct_ptr->fieldN   (pointer to N-th field)
        aget    (array_val)  -> array_val[N]           (N-th element, via helper)
        """
        if not isinstance(index, int):
            return None
        ct, v = arg_pairs[0]

        # aget: index into an array/pointer value → offset + deref (GIMPLE-legal).
        if kind == 'aget':
            pt, pv = self._as_ptr(ct, v)
            et = _elem_type(pt)
            cn = _c_id(et)
            self._ptr_helpers_needed.add(et)
            addr = self._new_val(pt, f"_mojo_at_{cn} ({pv}, {index})")
            t = self._new_val(et, f"*{addr}")
            return et, t

        # extract / gep: resolve the struct's N-th field by declaration order.
        base = ct[:-2] if ct.endswith(' *') else ct
        op = '->' if ct.endswith(' *') else '.'
        fields = self.struct_field_types.get(base)
        if not fields or index >= len(fields):
            return None
        fname = list(fields.keys())[index]
        ftype = fields[fname]

        if kind == 'extract':
            t = self._new_val(ftype, f"{v}{op}{fname}")
            return ftype, t

        # gep → address of the field
        t = self._new_val(f"{ftype} *", f"&{v}{op}{fname}")
        return f"{ftype} *", t

    def _lower_call(self, node: CallExpr) -> tuple[str, str]:
        if isinstance(node.func, SubscriptExpr) and isinstance(node.func.obj, IdentExpr) \
                and node.func.obj.name in ('external_call', '_external_call_const'):
            return self._lower_external_call(node)
        mlir_call = self._maybe_lower_mlir_op(node)
        if mlir_call is not None:
            return mlir_call
        if isinstance(node.func, SubscriptExpr) and isinstance(node.func.obj, IdentExpr) \
                and node.func.obj.name in self._imported_generic_structs:
            res = self._elaborate_generic_struct_call(node)
            if res is not None:
                return res
        if isinstance(node.func, IdentExpr) and node.func.name in self._imported_overloads:
            res = self._elaborate_overload_call(node)
            if res is not None:
                return res
        _gen = (isinstance(node.func, SubscriptExpr) and isinstance(node.func.obj, IdentExpr)
                and node.func.obj.name in self._imported_generics) or \
               (isinstance(node.func, IdentExpr) and node.func.name in self._imported_generics)
        if _gen:
            res = self._elaborate_generic_call(node)
            if res is not None:
                return res
        if isinstance(node.func, MemberExpr):
            return self._lower_method_call(node)
        # Subscripted method call: obj.method[TypeParam](...) — unwrap type param and route as method call
        if isinstance(node.func, SubscriptExpr) and isinstance(node.func.obj, MemberExpr):
            inner = CallExpr(func=node.func.obj, args=node.args,
                             kwargs=getattr(node, 'kwargs', []), line=getattr(node, 'line', 0))
            return self._lower_method_call(inner)
        # Generic container constructors: List[T](...), Dict[K,V](...), Set[T](...), Optional[T](...)
        if isinstance(node.func, SubscriptExpr) and isinstance(node.func.obj, IdentExpr):
            base = node.func.obj.name
            if base in ('List', 'InlineList', 'SmallVector', 'DynamicVector', 'InlineArray',
                        'Buffer', 'NDBuffer'):
                t = self._new_val('MojoList *', 'mojo_list_new ()')
                for a in node.args: self.lower_expr(a)
                return 'MojoList *', t
            if base in ('Dict', 'OrderedDict'):
                t = self._new_val('MojoDict *', 'mojo_dict_new ()')
                for a in node.args: self.lower_expr(a)
                return 'MojoDict *', t
            if base in ('Set', 'FrozenSet'):
                t = self._new_val('MojoSet *', 'mojo_set_new ()')
                for a in node.args: self.lower_expr(a)
                return 'MojoSet *', t
            if base == 'Optional':
                if node.args:
                    at, av = self.lower_expr(node.args[0])
                    t = self._new_val('int64_t', f'(int64_t){av}' if at.endswith(' *') else av)
                    return 'int64_t', t
                return 'int64_t', self._new_val('int64_t', '(int64_t)0')
        if not isinstance(node.func, IdentExpr):
            return 'int', self._new_val('int', '0')

        fname_raw = node.func.name
        # A local variable of a callable struct type, invoked like a function:
        # obj(args) → obj.__call__(args).
        if (fname_raw in self.var_types and fname_raw not in self.func_return_types
                and fname_raw not in self._global_inline_defs):
            _csn = _struct_name_of(self.var_types[fname_raw])
            if _csn and _csn in getattr(self, '_callable_structs', set()):
                _cm = MemberExpr(obj=node.func, member='__call__',
                                 line=getattr(node, 'line', 0))
                return self._lower_method_call(CallExpr(
                    func=_cm, args=node.args,
                    kwargs=getattr(node, 'kwargs', []), line=getattr(node, 'line', 0)))
        if fname_raw == 'main' and self.current_func_name != 'main':
            if self.emit_entry_points:
                fname_raw = '_gimple_main'
            else:
                _mod_id = self.module_name.replace('.', '_').replace('-', '_') if self.module_name else ''
                fname_raw = f"_{_mod_id}_main" if _mod_id else '_lib_main'

        # Builtin dispatch
        if fname_raw == 'strided_load' and node.args:
            return self._lower_strided(node, store=False)
        if fname_raw == 'strided_store' and len(node.args) >= 2:
            return self._lower_strided(node, store=True)
        if fname_raw == 'len'             and node.args:            return self._lower_builtin_len(node)
        if fname_raw == 'isinstance'      and len(node.args) == 2:  return self._lower_builtin_isinstance(node)
        if fname_raw in ('all', 'any')    and len(node.args) == 1:  return self._lower_builtin_all_any(fname_raw, node)
        if fname_raw == 'dir':                                       return self._lower_builtin_dir(node)
        if fname_raw == 'sorted'          and node.args:            return self._lower_builtin_sorted(node)
        if fname_raw == 'zip'             and len(node.args) > 2:  return self._lower_builtin_zip_n(node)
        if fname_raw == '__import__':                                return self._lower_builtin_import(node)
        if fname_raw in ('set', 'frozenset'):                        return self._lower_builtin_set(node)
        if fname_raw == 'dict':                                      return self._lower_builtin_dict(node)
        if fname_raw in ('list', 'tuple') and len(node.args) <= 1:  return self._lower_builtin_list(node)
        if fname_raw == 'open'            and 'open' not in self.func_return_types:
            return self._lower_builtin_open(node)
        if fname_raw == 'Self':                                      return self._lower_self_ctor(node)
        # iter(x) — the container is already iterable (for-loops consume it directly),
        # so model the builtin as identity rather than emitting an undefined `iter` call.
        if fname_raw == 'iter' and len(node.args) == 1 and 'iter' not in self.func_return_types:
            return self.lower_expr(node.args[0])

        # Trivial builtins: lower_expr all args, call runtime fn
        _SIMPLE_BUILTINS = {
            'str':       ('char *',  'mojo_str'),
            'repr':      ('char *',  'mojo_repr'),
            'enumerate': ('void *',  'mojo_enumerate'),
            'hasattr':   ('int',     'mojo_hasattr'),
        }
        if fname_raw in _SIMPLE_BUILTINS and node.args:
            rt, fn = _SIMPLE_BUILTINS[fname_raw]
            pairs = [self.lower_expr(a) for a in node.args]
            return rt, self._call_expr(rt, fn, pairs)
        if fname_raw == 'getattr' and len(node.args) >= 2:
            pairs = [self.lower_expr(a) for a in node.args[:2]]  # drop optional default
            return 'int64_t', self._call_expr('int64_t', 'mojo_obj_getattr', pairs)
        if fname_raw == 'type'    and len(node.args) == 1:
            _, av = self.lower_expr(node.args[0])
            return 'int', self._new_val('int', f'mojo_type ({av})')
        if fname_raw == 'setattr' and len(node.args) >= 3:
            pairs = [self.lower_expr(a) for a in node.args[:3]]
            return self._void_call('mojo_setattr', pairs)

        # Struct constructors
        if fname_raw in self.struct_field_types:
            return self._lower_struct_constructor(fname_raw, node.args, getattr(node, 'kwargs', None))
        if self.func_return_types.get(fname_raw) == f'{fname_raw} *':
            return self._lower_imported_struct_ctor(fname_raw, node)

        # Scalar type constructors (Float32, Int8, etc.) — before opaque-uppercase check
        _SCALAR_CTORS = {
            'Float32': 'float', 'Float64': 'double', 'Float16': '__fp16', 'BFloat16': '__fp16',
            'Int8': 'int8_t', 'Int16': 'int16_t', 'Int32': 'int32_t', 'Int64': 'int64_t',
            'UInt8': 'uint8_t', 'UInt16': 'uint16_t', 'UInt32': 'uint32_t', 'UInt64': 'uint64_t',
            'Int': 'int64_t', 'UInt': 'uint64_t', 'Bool': '_Bool',
        }
        if (fname_raw in _SCALAR_CTORS and fname_raw not in self.func_return_types
                and fname_raw not in self.imported_symbols):
            return self._lower_scalar_ctor(fname_raw, _SCALAR_CTORS[fname_raw], node)

        # Closure / recursive self-call
        inner_name = getattr(self, '_inner_func_name', '')
        if inner_name and fname_raw == inner_name and self._env_param:
            return self._lower_recursive_self_call(fname_raw, node)
        if fname_raw in self._closure_envs:
            return self._lower_closure_call(fname_raw, node)
        # Lambda body references an outer closure — call the lifted version with null env
        outer_ci = getattr(self, '_lambda_outer_closures', {}).get(fname_raw)
        if outer_ci:
            return self._lower_outer_closure_call(fname_raw, outer_ci, node)

        # Opaque uppercase constructor (imported type not in any table)
        if (self.func_return_types.get(fname_raw, 'int64_t') == 'int64_t'
                and fname_raw[0:1].isupper()
                and fname_raw not in self.func_param_types
                and fname_raw not in self.imported_symbols
                and fname_raw not in self._KNOWN_SIGS
                and fname_raw not in _C_RESERVED_FUNCS
                and fname_raw not in self.BUILTIN_VALUE_MAP):
            return self._lower_opaque_ctor(fname_raw, node)

        # Local variable (or captured variable) holding a function pointer.
        # Emit a proper function-pointer call via a C cast.
        _fname_var_ctype = self.var_types.get(fname_raw, '')
        if _fname_var_ctype in ('int', 'int64_t', 'void *', '_Bool'):
            return self._lower_fnptr_call(fname_raw, _fname_var_ctype, node)

        return self._lower_named_call(fname_raw, node)

    # ── _lower_call sub-handlers ──────────────────────────────────────────

    def _lower_builtin_len(self, node: CallExpr) -> tuple[str, str]:
        at, av = self.lower_expr(node.args[0])
        _LEN_FNS = {
            'MojoStr *':  f'mojo_str_len ({av})',
            'MojoList *': f'mojo_list_len ({av})',
            'MojoDict *': f'mojo_dict_len ({av})',
            'MojoSet *':  f'mojo_set_len ({av})',
        }
        if at in _LEN_FNS:
            return 'int64_t', self._new_val('int64_t', _LEN_FNS[at])
        if at.endswith(' *') and at[:-2] in self.struct_field_types \
                and '_len' in self.struct_field_types[at[:-2]]:
            return 'int64_t', self._new_val('int64_t', f'{av}->_len')
        if at in ('int', 'int64_t'):
            ip = self._new_val('int64_t', f'(int64_t){av}')
            lp = self._new_val('MojoList *', f'(MojoList *){ip}')
            return 'int64_t', self._new_val('int64_t', f'mojo_list_len ({lp})')
        return 'int64_t', self._new_val('int64_t', f'(int64_t)0  /* len() on unsupported type {at} */')

    def _lower_builtin_isinstance(self, node: CallExpr) -> tuple[str, str]:
        obj_type, obj_val = self.lower_expr(node.args[0])
        type_arg = node.args[1]
        t = self._new_temp('int')
        if isinstance(type_arg, IdentExpr):
            type_name = type_arg.name
            if type_name == 'type':
                self._emit(f'  {t} = 0;  /* isinstance(x, type) always false in C */')
            else:
                _TYPE_IDS = {'bool': '1', 'int': '2', 'float': '3', 'str': '4',
                             'list': '5', 'dict': '6', 'set': '7'}
                type_id = _TYPE_IDS.get(type_name, '0')
                if obj_type in ('char *', 'void *', 'MojoDict *', 'MojoList *', 'MojoSet *') or obj_type.endswith(' *'):
                    iv  = self._new_val('int64_t', f'(int64_t){obj_val}')
                    iv2 = self._new_val('int', f'(int){iv}')
                    self._emit(f'  {t} = mojo_isinstance ({iv2}, {type_id});')
                else:
                    self._emit(f'  {t} = mojo_isinstance ({obj_val}, {type_id});')
        elif isinstance(type_arg, TupleExpr):
            _debug_note('isinstance with tuple of types stubbed to 0')
            self._emit(f'  {t} = 0;  /* TODO: isinstance with tuple of types */')
        else:
            _debug_note('isinstance with complex type arg stubbed to 0')
            self._emit(f'  {t} = 0;  /* TODO: isinstance with complex type arg */')
        return 'int', t

    def _lower_builtin_all_any(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        runtime_fn = 'mojo_list_all' if fname_raw == 'all' else 'mojo_list_any'
        stub_val   = '1'             if fname_raw == 'all' else '0'
        at, av = self.lower_expr(node.args[0])
        t = self._new_temp('int')
        if at == 'MojoList *' or (at.endswith(' *') and at != 'char *'):
            lv = av if at == 'MojoList *' else self._new_val('MojoList *', f'(MojoList *){av}')
            self._emit_call('int', t, runtime_fn, [('MojoList *', lv)])
        else:
            self._emit(f'  {t} = {stub_val};  /* {fname_raw}() stubbed */')
        return 'int', t

    def _lower_builtin_dir(self, node: CallExpr) -> tuple[str, str]:
        for a in node.args: self.lower_expr(a)
        return 'MojoList *', self._new_val('MojoList *', 'mojo_list_new ()  /* dir() stubbed */')

    def _lower_builtin_sorted(self, node: CallExpr) -> tuple[str, str]:
        at, av = self.lower_expr(node.args[0])
        for a in node.args[1:]: self.lower_expr(a)
        return 'MojoList *', self._call_expr('MojoList *', 'mojo_sorted', [(at, av)])

    def _lower_builtin_zip_n(self, node: CallExpr) -> tuple[str, str]:
        """zip(a, b, c, ...) with >2 args — chain as mojo_zip(mojo_zip(a, b), c, ...)."""
        arg_pairs = [self.lower_expr(a) for a in node.args]
        # Fold left: mojo_zip(mojo_zip(a,b), c)
        acc_t, acc_v = 'void *', self._call_expr('void *', 'mojo_zip', [arg_pairs[0], arg_pairs[1]])
        for ap in arg_pairs[2:]:
            acc_v = self._call_expr('void *', 'mojo_zip', [('void *', acc_v), ap])
        return 'void *', acc_v

    def _lower_builtin_import(self, node: CallExpr) -> tuple[str, str]:
        for a in node.args: self.lower_expr(a)
        return 'int', self._new_val('int', '0  /* __import__ stubbed */')

    def _lower_builtin_set(self, node: CallExpr) -> tuple[str, str]:
        t = self._new_val('MojoSet *', 'mojo_set_new ()')
        for a in node.args: self.lower_expr(a)
        return 'MojoSet *', t

    def _lower_builtin_dict(self, node: CallExpr) -> tuple[str, str]:
        if not node.args:
            return 'MojoDict *', self._new_val('MojoDict *', 'mojo_dict_new ()')
        at, av = self.lower_expr(node.args[0])
        t = self._new_temp('MojoDict *')
        if at == 'MojoList *':
            self._emit_call('MojoDict *', t, 'mojo_dict_from_pairs', [('MojoList *', av)])
        elif at in ('int64_t', 'int') or not at.endswith(' *') or at == 'void *':
            raw = self._new_val('MojoDict *', f'(MojoDict *){av}')
            self._emit_call('MojoDict *', t, 'mojo_dict_copy', [('MojoDict *', raw)])
        else:
            self._emit_call('MojoDict *', t, 'mojo_dict_copy', [(at, av)])
        return 'MojoDict *', t

    def _lower_builtin_list(self, node: CallExpr) -> tuple[str, str]:
        return 'MojoList *', self._new_val('MojoList *', 'mojo_list_new ()')

    def _lower_builtin_open(self, node: CallExpr) -> tuple[str, str]:
        # open(path) — read mode
        if len(node.args) == 1:
            fn_type, fn_val = self.lower_expr(node.args[0])
            return 'int64_t', self._call_expr('int64_t', 'mojo_open_file', [(fn_type, fn_val)])
        # open(path, mode)
        fn_type,   fn_val   = self.lower_expr(node.args[0])
        mode_type, mode_val = self.lower_expr(node.args[1])
        fn_val   = self._ensure_local('char *', self._coerce_to_type(fn_type,   'char *', fn_val))
        mode_val = self._ensure_local('char *', self._coerce_to_type(mode_type, 'char *', mode_val))
        tmp = self._new_val('void *',   f'mojo_open ({fn_val}, {mode_val})')
        return 'int64_t', self._new_val('int64_t', f'(int64_t){tmp}')

    def _lower_self_ctor(self, node: CallExpr) -> tuple[str, str]:
        sname = getattr(self, '_current_struct_name', None)
        if sname:
            arg_pairs = [self.lower_expr(a) for a in node.args]
            self._self_ctor_stubs = getattr(self, '_self_ctor_stubs', set())
            self._self_ctor_stubs.add(sname)
            return 'int64_t', self._call_expr('int64_t', f'{sname}___new', arg_pairs)
        for a in node.args: self.lower_expr(a)
        return 'int64_t', self._new_val('int64_t', '0  /* Self() constructor: no struct context */')

    def _lower_imported_struct_ctor(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        arg_pairs = [self.lower_expr(a) for a in node.args]
        t = self._new_temp('int64_t')
        if arg_pairs:
            atype, aval = arg_pairs[0]
            if atype.endswith(' *'):
                self._emit(f'  {t} = (int64_t){aval};')
            else:
                self._emit(f'  {t} = (int64_t){self._ensure_local(atype, aval)};')
        else:
            self._emit(f'  {t} = (int64_t)0;')
        return 'int64_t', t

    def _lower_scalar_ctor(self, fname_raw: str, ctype: str, node: CallExpr) -> tuple[str, str]:
        t = self._new_temp(ctype)
        if node.args:
            at, av = self.lower_expr(node.args[0])
            for xa in node.args[1:]: self.lower_expr(xa)
            if not at.endswith(' *') and at not in ('MojoList *', 'MojoDict *', 'MojoSet *', 'void *', 'char *'):
                self._emit(f'  {t} = ({ctype}){self._ensure_local(at, av)};')
            else:
                self._emit(f'  {t} = ({ctype})0;  /* {fname_raw}(struct) unsupported */')
        else:
            self._emit(f'  {t} = ({ctype})0;')
        return ctype, t

    def _lower_opaque_ctor(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        ctor_args = [self.lower_expr(a) for a in node.args]
        t = self._new_temp('int64_t')
        if ctor_args:
            at, av = ctor_args[0]
            if at.endswith(' *'):       self._emit(f'  {t} = (int64_t){av};')
            elif at == 'int64_t':       self._emit(f'  {t} = {av};')
            else:                       self._emit(f'  {t} = (int64_t){self._ensure_local(at, av)};')
        else:
            self._emit(f'  {t} = (int64_t)0;')
        return 'int64_t', t

    def _lower_recursive_self_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        lifted   = self.current_func_name
        env_var  = self._env_param
        ret_type = self.func_ret_type or self.func_return_types.get(lifted, 'int64_t')
        arg_vals = [self.lower_expr(a)[1] for a in node.args]
        fname_c  = _safe_name(lifted)
        all_args = ', '.join([env_var] + arg_vals)
        if ret_type == 'void':
            self._emit(f'  {fname_c} ({all_args});')
            return 'int', self._new_val('int', '0')
        return ret_type, self._new_val(ret_type, f'{fname_c} ({all_args})')

    def _lower_outer_closure_call(self, fname_raw: str, ci, node: CallExpr) -> tuple[str, str]:
        """Call an outer function's nested closure from inside a lambda body.

        The env pointer is not available here (it belongs to the outer function scope),
        so pass a null env — safe at link time; will crash at runtime if the env fields
        are actually accessed, but the selfhost test only checks compile+link.
        """
        lifted    = ci.lifted_name
        ret_type  = self.func_return_types.get(lifted, 'int64_t')
        arg_pairs = [self.lower_expr(a) for a in node.args]
        fname_c   = _safe_name(lifted)
        if ci.env_struct:
            null_env = self._new_val(f'{ci.env_struct} *', f'({ci.env_struct} *)0')
            full_arg_pairs = [(f'{ci.env_struct} *', null_env)] + arg_pairs
        else:
            full_arg_pairs = arg_pairs
        if ret_type == 'void':
            return self._void_call(fname_c, full_arg_pairs)
        return ret_type, self._call_expr(ret_type, fname_c, full_arg_pairs)

    def _lower_closure_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        lifted   = f'{self.current_func_name}_{fname_raw}'
        env_var  = self._closure_envs[fname_raw]
        ret_type = self.func_return_types.get(lifted, 'int64_t')
        arg_pairs = [self.lower_expr(a) for a in node.args]
        fname_c  = _safe_name(lifted)
        if env_var:
            env_type = self.func_param_types.get(lifted, [f"{env_var[1:]} *" if '_env_' in env_var else 'void *'])[0]
            full_arg_pairs = [(env_type, env_var)] + arg_pairs
        else:
            full_arg_pairs = arg_pairs
        if ret_type == 'void':
            return self._void_call(fname_c, full_arg_pairs)
        return ret_type, self._call_expr(ret_type, fname_c, full_arg_pairs)

    def _lower_LambdaExpr(self, node) -> tuple:
        """Lift a lambda expression to a top-level C function.

        Returns a (void *, static_ptr_name) pair so the lambda can be passed
        as a function pointer.  The actual body is accumulated in
        self._lambda_parts and flushed by gen_module into func_parts.
        """
        outer_ctx = self.current_func_name or 'root'
        self._lambda_counter += 1
        lifted_name = f'{outer_ctx}_lambda_{self._lambda_counter}'

        # Build a synthetic FunctionDef whose body is `return <lambda.body>`
        syn_body = [ReturnStmt(value=node.body)]
        # Lambda params are (pname, default_value) not (pname, type_ann).
        # Strip defaults so _gen_lifted_closure doesn't try to resolve them as types.
        syn_params = [(p, None) for p, _ in node.params]
        syn_def  = FunctionDef(
            name=lifted_name,
            params=syn_params,
            return_type=None,
            body=syn_body,
        )

        # Infer param types from captures + existing var_types context
        captures = []
        for pname, ptype in node.params:
            if ptype is None and pname in self.var_types:
                captures.append((pname, self.var_types[pname]))

        ci = ClosureInfo(
            lifted_name=lifted_name,
            env_struct='',
            captures=[],
            inner_def=syn_def,
        )
        # Register return type and param types now so call sites resolve correctly
        ret_type = self._infer_return_type(syn_body)
        self.func_return_types[lifted_name] = ret_type
        param_ctypes = []
        for pname, ptype in node.params:
            # Lambda params: second element is default value (AST node), not a type annotation.
            # Resolve from var_types context; default to int64_t.
            if pname in self.var_types:
                param_ctypes.append(self.var_types[pname])
            else:
                param_ctypes.append('int64_t')
        self.func_param_types[lifted_name] = param_ctypes

        # Generate the lifted function body and queue for emission
        # Save/restore per-function state around the nested codegen
        saved_decls          = self.decls
        saved_body           = self.body_lines
        saved_var_types      = dict(self.var_types)
        saved_func_name      = self.current_func_name
        saved_ret_type       = self.func_ret_type
        saved_bb             = self.bb_counter
        saved_temp           = self.temp_counter
        saved_captures       = dict(self._captures)
        saved_env            = self._env_param
        saved_inner          = self._inner_func_name
        saved_loop_stack     = list(self.loop_stack)
        saved_loop_depth     = self._loop_depth
        saved_closure_envs   = dict(self._closure_envs)
        saved_func_decl_glob = set(self._func_declared_globals)

        # Expose outer closure info so the lambda body can resolve calls to parent
        # nested functions (e.g. compile_one_object) via their lifted C names with
        # a null env pointer (safe at link time; runtime env is unavailable in lambda).
        outer_closures_for_lambda = {}
        outer_all_closures = self._all_closures.get(outer_ctx, {})
        for _inner_n, _env_v in saved_closure_envs.items():
            _outer_ci = outer_all_closures.get(_inner_n)
            if _outer_ci:
                outer_closures_for_lambda[_inner_n] = _outer_ci
        self._lambda_outer_closures = outer_closures_for_lambda

        body_code = self._gen_lifted_closure(ci)
        self._lambda_outer_closures = {}

        self.decls                   = saved_decls
        self.body_lines              = saved_body
        self.var_types               = saved_var_types
        self.current_func_name       = saved_func_name
        self.func_ret_type           = saved_ret_type
        self.bb_counter              = saved_bb
        self.temp_counter            = saved_temp
        self._captures               = saved_captures
        self._env_param              = saved_env
        self._inner_func_name        = saved_inner
        self.loop_stack              = saved_loop_stack
        self._loop_depth             = saved_loop_depth
        self._closure_envs           = saved_closure_envs
        self._func_declared_globals  = saved_func_decl_glob

        self._lambda_parts.append(body_code)
        self._lambda_parts.append('')

        # Forward declaration so the preamble's static pointer initialiser can
        # reference the function before its definition appears in the output.
        params_str = ', '.join(
            f'{ct} {pn}' for ct, (pn, _) in zip(param_ctypes, node.params)
        ) or 'void'
        fwd_decl = f'{ret_type} {lifted_name} ({params_str});'
        if fwd_decl not in self._elaborated_externs:
            self._elaborated_externs.append(fwd_decl)
        if lifted_name not in self.func_return_types:
            self.func_return_types[lifted_name] = ret_type
        self._funcptr_builtins_needed.add(lifted_name)

        static_name = f'_funcptr_{lifted_name}'
        t = self._new_val('void *', static_name)
        return 'void *', t

    def _lower_fnptr_call(self, fname_raw: str, var_ctype: str,
                          node: CallExpr) -> tuple[str, str]:
        """Emit a call through a function pointer stored in a local/captured variable.

        Uses mojo_fnptr_call_N() runtime helpers because __GIMPLE functions cannot
        cast-and-call in a single expression.  All args are widened to int64_t;
        the result is then narrowed to the expected return type.
        """
        arg_pairs = [self.lower_expr(a) for a in node.args]
        n = len(arg_pairs)
        # Load the raw function pointer value.
        # For captured vars, _lower_IdentExpr reads from _env->name.
        if fname_raw in self._captures and self._env_param:
            fp_type, fp_raw = self.lower_expr(IdentExpr(name=fname_raw))
        else:
            fp_raw = self._c_names.get(fname_raw, fname_raw)
            fp_type = var_ctype
        # Cast to void * so the runtime helper receives a stable pointer type.
        if fp_type != 'void *':
            fp_void = self._new_val('void *', f'(void *){fp_raw}')
        else:
            fp_void = fp_raw
        # Widen each arg to int64_t.
        widened = []
        for at, av in arg_pairs:
            if at == 'int64_t':
                widened.append(av)
            else:
                widened.append(self._new_val('int64_t', f'(int64_t){av}'))
        # Emit the runtime-helper call; helpers exist for 0..4 args.
        helper = f'mojo_fnptr_call_{min(n, 4)}'
        call_args = ', '.join([fp_void] + widened[:4])
        ret_type = self.func_return_types.get(fname_raw, 'int64_t')
        raw_t = self._new_val('int64_t', f'{helper} ({call_args})')
        if ret_type in ('int64_t', 'int'):
            return ret_type, raw_t
        if ret_type == 'void':
            self._emit(f'  {helper} ({call_args});')
            return 'int', self._new_val('int', '0')
        # Narrow back to declared return type.
        t = self._new_val(ret_type, f'({ret_type}){raw_t}')
        return ret_type, t

    def _lower_named_call(self, fname_raw: str, node: CallExpr) -> tuple[str, str]:
        """Final dispatch for user-defined and C stdlib functions."""
        # C reserved function renaming
        if (fname_raw in _C_RESERVED_FUNCS and fname_raw not in self.func_return_types
                and fname_raw not in _FORCE_RENAME_RESERVED
                and fname_raw not in self.imported_symbols):
            fname = self.BUILTIN_VALUE_MAP.get(fname_raw, fname_raw)
        else:
            # _func_csym applies the same overload suffix the definition used.
            fname = self.BUILTIN_VALUE_MAP.get(fname_raw, self._func_csym(fname_raw))
        ret_type = self.func_return_types.get(fname_raw, 'int64_t')

        # Auto-stub completely unknown names (e.g. bracket params like `cmp_fn: fn(T,T)->Bool`
        # that the parser skips). Without a declaration GCC gives "implicit function declaration".
        _is_unknown = (fname_raw not in self.func_return_types
                       and fname_raw not in self.imported_symbols
                       and fname not in self._KNOWN_SIGS
                       and fname_raw not in self.BUILTIN_VALUE_MAP
                       and fname_raw not in _C_RESERVED_FUNCS)
        if _is_unknown:
            _stub_key = f'_MOJO_STUB_{fname.upper()}'
            _stub_decl = f'#ifndef {_stub_key}\n#define {_stub_key}\nint64_t {fname} (...);\n#endif'
            if _stub_decl not in self._elaborated_externs:
                self._elaborated_externs.append(_stub_decl)
        if fname in self._KNOWN_SIGS:
            ret_type = self._KNOWN_SIGS[fname][0]

        # A renamed C-reserved *builtin* passthrough (e.g. calling libm exp2 with
        # no local def) needs a variadic extern. But if there's a local Mojo def of
        # the same name (now overload-mangled), it already has a typed forward decl
        # — emitting the variadic stub too would conflict. Skip those.
        if (fname != fname_raw and fname_raw in _C_RESERVED_FUNCS
                and fname_raw not in self._mangled_funcs):
            self._renamed_builtin_calls = getattr(self, '_renamed_builtin_calls', {})
            if fname not in self._renamed_builtin_calls:
                self._renamed_builtin_calls[fname] = ret_type

        arg_pairs = [self.lower_expr(a) for a in node.args]
        kwargs    = getattr(node, 'kwargs', []) or []
        kwarg_dict = {kname: self.lower_expr(kexpr) for kname, kexpr in kwargs}

        # Keyword argument padding for known functions
        if fname_raw == 'compile_to_gimple':
            if 'do_imports' in kwarg_dict: arg_pairs.append(kwarg_dict['do_imports'])
            elif len(arg_pairs) < 2:       arg_pairs.append(('int', '0'))
            if 'filename' in kwarg_dict:   arg_pairs.append(kwarg_dict['filename'])
            elif len(arg_pairs) < 3:       arg_pairs.append(('char *', '0'))
        if fname_raw == 'interpret_and_execute':
            if 'filename' in kwarg_dict:   arg_pairs.append(kwarg_dict['filename'])
            elif len(arg_pairs) < 2:       arg_pairs.append(('int', '0'))
        if fname_raw == 'format_ast'  and len(arg_pairs) == 1: arg_pairs.append(('int', '0'))
        if fname_raw == 'emit_module' and len(arg_pairs) == 1: arg_pairs.append(('int', '0'))

        # General kwarg padding when expected param count is known
        expected_params = self.func_param_types.get(fname_raw, [])
        if expected_params and len(arg_pairs) < len(expected_params):
            kwarg_values = list(kwarg_dict.values()) if kwarg_dict else []
            while len(arg_pairs) < len(expected_params):
                arg_pairs.append(kwarg_values.pop(0) if kwarg_values else ('int', '0'))

        # int(s, base) — drop the base arg
        if fname_raw == 'int' and len(arg_pairs) > 1:
            arg_pairs = arg_pairs[:1]

        # abs of an integer → inline `x < 0 ? -x : x`.
        # We deliberately do NOT call the libc `llabs`: gcc -fgimple ICEs
        # (gimplify_var_or_parm_decl) when the recognized builtin llabs is applied
        # to a local computed temp. Inlining is also strictly better — no libc call
        # for a one-instruction operation.
        # TODO(gimple-builtins): revisit once the gcc -fgimple builtin-arg ICE is
        # fixed upstream; we could then route abs back through llabs if desired.
        if fname_raw in ('abs', 'mojo_abs') and len(arg_pairs) == 1:
            at, av = arg_pairs[0]
            if at in ('int64_t', 'long long') or at.endswith(' *'):
                v = self._ensure_local('int64_t', av if not at.endswith(' *')
                                       else self._new_val('int64_t', f'(int64_t){av}'))
                zero = self._new_val('int64_t', '(int64_t)0')
                neg  = self._new_val('_Bool', f'{v} < {zero}')
                negv = self._new_val('int64_t', f'-{v}')
                return 'int64_t', self._new_val('int64_t', f'{neg} ? {negv} : {v}')

        # range(stop) or range(start, stop, step)
        if fname_raw == 'range':
            if len(arg_pairs) == 1:
                _zero = self._new_val('int64_t', '(int64_t) 0')
                arg_pairs = [('int64_t', _zero), arg_pairs[0]]
            elif len(arg_pairs) == 3:
                fname = 'mojo_range3'
            return 'void *', self._call_expr('void *', fname, arg_pairs)

        # min/max over scalar args → fold into nested ternaries (avoids the
        # mojo_min(void*) variadic-pack signature, which we don't emit packs for).
        _NUM = ('int64_t', 'int', '_Bool', 'double', 'float',
                'uint64_t', 'int32_t', 'uint32_t', 'int16_t', 'uint16_t',
                'int8_t', 'uint8_t', 'size_t', 'long', 'short')
        if (fname_raw in ('min', 'max') and arg_pairs
                and all(t in _NUM for t, _ in arg_pairs)):
            op = '<' if fname_raw == 'min' else '>'
            def _as_i64(t, v):
                return v if t == 'int64_t' else self._new_val('int64_t', f'(int64_t){v}')
            acc = _as_i64(*arg_pairs[0])
            for t, v in arg_pairs[1:]:
                bv = _as_i64(t, v)
                cond = self._new_val('_Bool', f'{acc} {op} {bv}')
                acc = self._new_val('int64_t', f'{cond} ? {acc} : {bv}')
            return 'int64_t', acc

        # round(x, ndigits) → round(x*10^n)/10^n (libm round() takes 1 arg only)
        if fname_raw == 'round' and len(arg_pairs) == 2:
            (xt, xv), (nt, nv) = arg_pairs
            xd = xv if xt == 'double' else self._new_val('double', f'(double){xv}')
            nd = nv if nt == 'double' else self._new_val('double', f'(double){nv}')
            p  = self._new_val('double', f'pow (10.0, {nd})')
            scaled = self._new_val('double', f'{xd} * {p}')
            r = self._new_val('double', f'round ({scaled})')
            return 'double', self._new_val('double', f'{r} / {p}')

        # float(x) — direct cast for numeric types
        if fname_raw == 'float' and arg_pairs:
            at, av = arg_pairs[0]
            if at in ('int64_t', 'int', '_Bool'): return 'double', self._new_val('double', f'(double){av}')
            if at == 'double':                    return 'double', av

        if ret_type == 'void':
            return self._void_call(fname, arg_pairs)
        return ret_type, self._call_expr(ret_type, fname, arg_pairs)

    # ── Struct constructor lowering (data layout solver decision) ─────────

    def _lower_struct_constructor(self, struct_name: str,
                                  args: list, kwargs: list | None = None) -> tuple[str, str]:
        """
        Lower TypeName(field1, field2, ...) to allocation + field init + __init__ call.

        Uses _alloc_StructName() helper (emitted in preamble) because
        sizeof(T) is invalid in __GIMPLE body when T is not in the signature.
        """
        ctype  = f"{struct_name} *"
        t      = self._new_temp(ctype)
        self._struct_allocs_needed.add(struct_name)
        self._emit(f"  {t} = _alloc_{struct_name} ();")

        # If struct has __init__, call it with the provided arguments
        if struct_name in self._struct_has_init:
            init_fname = f"{struct_name}___init__"
            arg_pairs = [(f"{struct_name} *", t)]  # self parameter
            for arg in args:
                arg_pairs.append(self.lower_expr(arg))
            full_params = self.func_param_types.get(init_fname, [])
            expected = len(full_params) - 1  # -1 for self
            # Bind keyword args to the __init__ parameters. For a struct whose
            # source we have, init_pnames gives the parameter names, so a kwarg
            # binds at the position of its named parameter. For a reflected
            # struct (no param names from the C signature), bind kwargs in source
            # order after the positional args.
            init_pnames = self._struct_init_params.get(struct_name, [])
            if kwargs and init_pnames:
                kw = dict(kwargs)
                for idx, pname in enumerate(init_pnames):
                    if pname not in kw:
                        continue
                    pos = idx + 1  # +1 for self slot
                    while len(arg_pairs) <= pos:
                        arg_pairs.append(('int', '0'))
                    arg_pairs[pos] = self.lower_expr(kw[pname])
            elif kwargs:
                for _kn, kexpr in kwargs:
                    arg_pairs.append(self.lower_expr(kexpr))
            # Pad any still-missing args with 0.
            while len(arg_pairs) - 1 < expected:
                arg_pairs.append(('int', '0'))
            self._emit_call('void', '', init_fname, arg_pairs)
        elif kwargs or args:
            # Positional args + keyword args — assign fields by position then by name
            fields_list = list(self.struct_field_types.get(struct_name, {}).items())
            fields_dict = dict(fields_list)
            # Assign positional args first (by field declaration order)
            for i, arg in enumerate(args):
                if i < len(fields_list):
                    fname, ftype = fields_list[i]
                    at, av = self.lower_expr(arg)
                    self._safe_coerce_emit(at, ftype, av, f"{t}->{_safe_field(fname)}")
            # Then assign kwargs by name (may override positional, as in Python)
            for kname, kexpr in (kwargs or []):
                if kname in fields_dict:
                    ftype = fields_dict[kname]
                    at, av = self.lower_expr(kexpr)
                    self._safe_coerce_emit(at, ftype, av, f"{t}->{_safe_field(kname)}")
        return ctype, t

    # ── Subscript lowering ────────────────────────────────────────────────

    def _struct_data_field(self, ctype: str):
        """Return (field_name, field_ctype) if ctype is a struct pointer with a pointer _data/data field, else (None, None)."""
        if not ctype.endswith(' *'):
            return None, None
        sn = _struct_name_of(ctype)
        sft = self.struct_field_types.get(sn, {})
        for fname in ('_data', 'data'):
            ft = sft.get(fname, '')
            if ft.endswith(' *'):
                return fname, ft
        return None, None

    def _emit_struct_subscript_write(self, obj_v: str, obj_t: str, idx_v: str, val: str, val_t: str) -> bool:
        """Emit `obj[idx] = val` for a struct-with-_data pointer. Returns True if handled."""
        fname, ftype = self._struct_data_field(obj_t)
        if fname is None:
            return False
        dp = self._new_val(ftype, f"{obj_v}->{fname}")
        # GIMPLE: can't chain casts in one expr; split into two steps
        vp = self._new_val('void *', f"(void *){dp}")
        i64p = self._new_val('int64_t *', f"(int64_t *){vp}")
        idx64 = self._new_val('int64_t', f"(int64_t) {idx_v}")
        self._ptr_helpers_needed.add('int64_t')
        addr = self._new_val('int64_t *', f"_mojo_at_int64_t ({i64p}, {idx64})")
        v64 = self._new_temp('int64_t')
        self._safe_coerce_emit(val_t, 'int64_t', val, v64)
        self._emit(f"  *{addr} = {v64};")
        return True

    def _lower_subscript(self, node: SubscriptExpr) -> tuple[str, str]:
        ot, ov = self.lower_expr(node.obj)
        idx_type, iv  = self.lower_expr(node.index)

        if ot == 'MojoList *':
            elem = self._elem_of(ov)
            suf  = TypeLattice.list_suffix(elem)
            idx64 = self._new_val('int64_t', f"(int64_t) {iv}")
            if suf == 'double':
                t = self._new_val('double', f"mojo_list_get_double ({ov}, {idx64})")
                return 'double', t
            if suf == 'str':
                t = self._new_val('char *', f"mojo_list_get_str ({ov}, {idx64})")
                return 'char *', t
            t = self._new_val('int64_t', f"mojo_list_get_int ({ov}, {idx64})")
            # Track element type if the list contains pointers (lists, dicts, etc.)
            # This is critical for nested subscripts: arr[0][1] needs to know what
            # element type the result of arr[0] contains.
            if elem and elem.endswith(' *'):
                self._actual_types[t] = elem
                # For MojoList*, track element type of the nested list
                if elem == 'MojoList *':
                    # Check if the container (ov) has tracked nested element type
                    if ov in self._nested_elem_types:
                        self._elem_types[t] = self._nested_elem_types[ov]
                    else:
                        # Unknown nested element type, default to int64_t
                        self._elem_types[t] = 'int64_t'
            return 'int64_t', t

        if ot == 'MojoStr *':
            idx64 = self._new_val('int64_t', f"(int64_t) {iv}")
            t = self._new_val('char', f"mojo_str_char_at ({ov}, {idx64})")
            return 'char', t

        if ot == 'MojoDict *':
            # Ensure index is char * for dict subscript access (all dict keys are strings in runtime)
            if idx_type != 'char *':
                idx_cast = self._new_val('char *', f"(char *){iv}")
                iv = idx_cast
                idx_type = 'char *'
            val_ctype = self._dict_val_of(ov)
            if val_ctype == 'double':
                t = self._call_expr('double', 'mojo_dict_get_double', [('MojoDict *', ov), (idx_type, iv)])
                return 'double', t
            if val_ctype == 'char *':
                t = self._call_expr('char *', 'mojo_dict_get_str', [('MojoDict *', ov), (idx_type, iv)])
                return 'char *', t
            if val_ctype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                # Pointer value stored boxed as int64_t; recover the real type so a
                # later v[k2] / v.get(...) dispatches on the right container.
                raw = self._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (idx_type, iv)])
                t = self._new_val(val_ctype, f"({val_ctype}){raw}")
                return val_ctype, t
            t = self._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', ov), (idx_type, iv)])
            return 'int64_t', t

        # Opaque Python object (typed as int) — treat as MojoList via cast
        if ot in ('int', 'int64_t'):
            # Check actual type for globals loaded as int64_t
            actual_type = self._get_actual_type(ot, ov)
            if actual_type == 'MojoDict *':
                # Dict subscript: int64_t → MojoDict *
                dp = self._new_temp('MojoDict *')
                ip = self._new_temp('int64_t')
                ov_local = self._ensure_local(ot, ov)
                if ot == 'int64_t':
                    self._emit(f"  {ip} = {ov_local};")
                else:
                    self._emit(f"  {ip} = (int64_t){ov_local};")
                self._emit(f"  {dp} = (MojoDict *){ip};")
                # Ensure index is char * for dict access (all dict keys are strings in runtime)
                idx_for_dict = iv
                idx_type_for_dict = idx_type
                if idx_type != 'char *':
                    idx_cast = self._new_val('char *', f"(char *){iv}")
                    idx_for_dict = idx_cast
                    idx_type_for_dict = 'char *'
                val_ctype = self._dict_val_of(dp)
                if val_ctype == 'double':
                    t = self._call_expr('double', 'mojo_dict_get_double', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
                    return 'double', t
                if val_ctype == 'char *':
                    t = self._call_expr('char *', 'mojo_dict_get_str', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
                    return 'char *', t
                t = self._call_expr('int64_t', 'mojo_dict_get_int', [('MojoDict *', dp), (idx_type_for_dict, idx_for_dict)])
                return 'int64_t', t
            # Otherwise treat as MojoList* stored as int; cast and subscript
            lp = self._new_temp('MojoList *')
            ip = self._new_temp('int64_t')
            ov_local = self._ensure_local(ot, ov)
            if ot == 'int64_t':
                self._emit(f"  {ip} = {ov_local};")  # same type, no cast
            else:
                self._emit(f"  {ip} = (int64_t){ov_local};")
            self._emit(f"  {lp} = (MojoList *){ip};")
            idx64 = self._to_int64(idx_type, iv)
            # Copy element type tracking from the int64_t temp to the MojoList * temp
            # This is critical for nested list access: when lp came from arr[i], we need to know
            # what elements lp contains so subsequent accesses like lp[j] use the right function
            if ov in self._elem_types:
                self._elem_types[lp] = self._elem_types[ov]
            if ov in self._nested_elem_types:
                self._nested_elem_types[lp] = self._nested_elem_types[ov]
            # Get element type: check _elem_types (if ov is a tracked temp), else check _nested_elem_types
            elem = self._elem_of(ov)
            if not elem or elem == 'int64_t':
                # Check if ov came from a subscript that returned a list with tracked nested elements
                if ov in self._elem_types:
                    elem = self._elem_types[ov]
                elif ov in self._nested_elem_types:
                    elem = self._nested_elem_types[ov]
            if elem == 'char *':
                t = self._new_val('char *', f"mojo_list_get_str ({lp}, {idx64})")
                return 'char *', t
            if elem == 'double':
                t = self._new_val('double', f"mojo_list_get_double ({lp}, {idx64})")
                return 'double', t
            t = self._new_val('int64_t', f"mojo_list_get_int ({lp}, {idx64})")
            return 'int64_t', t

        # Struct pointer subscript: Span[i] → Span->_data[i] etc.
        if ot.endswith(' *') and _struct_name_of(ot) in self.struct_field_types:
            fname, ftype = self._struct_data_field(ot)
            if fname is not None:
                dp = self._new_val(ftype, f"{ov}->{fname}")
                et = _elem_type(ftype)
                cn = _c_id(et)
                self._ptr_helpers_needed.add(et)
                idx64 = self._new_val('int64_t', f"(int64_t) {iv}")
                addr = self._new_val(ftype, f"_mojo_at_{cn} ({dp}, {idx64})")
                if et == 'void':
                    return ftype, addr
                t = self._new_val(et, f"*{addr}")
                return et, t
            # Struct without pointer _data: return int64_t opaque handle
            t = self._new_val('int64_t', f"(int64_t){ov}")
            return 'int64_t', t

        # p[i] via _mojo_at_ helper (ptr arithmetic not allowed in __GIMPLE)
        et = _elem_type(ot)
        cn = _c_id(et)
        self._ptr_helpers_needed.add(et)
        idx64 = self._new_val('int64_t', f"(int64_t) {iv}")
        addr = self._new_val(ot, f"_mojo_at_{cn} ({ov}, {idx64})")
        # Can't dereference void* (no element type); return the pointer itself
        if et == 'void':
            return ot, addr
        # Struct types: return int64_t (opaque handle) — can't cast struct→int64_t in GIMPLE
        if et in self.struct_field_types:
            t = self._new_val('int64_t', f"(int64_t){addr}")
            return 'int64_t', t
        t = self._new_val(et, f"*{addr}")
        return et, t

    # ── Slice lowering ────────────────────────────────────────────────────

    def _lower_slice(self, node: SliceExpr) -> tuple[str, str]:
        ot, ov = self.lower_expr(node.obj)
        if node.start is not None:
            _, sv = self.lower_expr(node.start)
            start_v = self._to_int64(self._quick_type(node.start), sv)
        else:
            start_v = '0'
        if node.stop is not None:
            _, ev = self.lower_expr(node.stop)
            stop_v = self._to_int64(self._quick_type(node.stop), ev)
        else:
            # -1 signals "to end" — runtime must handle this
            stop_v = '-1'

        if ot == 'MojoStr *':
            t = self._new_val('MojoStr *', f"mojo_str_slice ({ov}, {start_v}, {stop_v})")
            return 'MojoStr *', t

        if ot == 'MojoList *':
            t = self._new_val('MojoList *', f"mojo_list_slice ({ov}, {start_v}, {stop_v})")
            # propagate elem type
            if ov in self._elem_types:
                self._elem_types[t] = self._elem_types[ov]
            return 'MojoList *', t

        # Plain pointer: return pointer to start (no bounds check)
        # GIMPLE: no pointer+integer; cast pointer through int64_t; both operands
        # must be plain variables (no cast expressions in binary operands).
        t = self._new_temp(ot)
        cast_t = self._new_val('int64_t', f"(int64_t){ov}")
        # Cast start to int64_t in a separate statement (GIMPLE binary operands
        # must be variables, not cast expressions)
        if start_v.lstrip('-').isdigit():
            sv_cast = self._new_val('int64_t', f"(int64_t){start_v}")
        else:
            # start_v is already a variable; ensure it's int64_t
            sv_cast = self._new_val('int64_t', f"(int64_t){start_v}")
        add_t = self._new_val('int64_t', f"{cast_t} + {sv_cast}")
        self._emit(f"  {t} = ({ot}){add_t};")
        return ot, t

    # ── Collection literal lowering ───────────────────────────────────────

    def _lower_list_literal(self, node: ListExpr) -> tuple[str, str]:
        elem = self._infer_list_elem_type(node.elements)
        suf  = TypeLattice.list_suffix(elem)
        t    = self._new_temp('MojoList *')
        self._elem_types[t] = elem
        self._emit(f"  {t} = mojo_list_new ();")
        # Lower elements first so we can see all their types before choosing how
        # to append. A single list-wide suffix mis-types a genuinely heterogeneous
        # collection — e.g. a tuple ('int', 5) would append the int via
        # mojo_list_append_str. Detect a string/non-string mix and, only then,
        # append each element by its OWN type. Numeric-only lists (incl. promoted
        # [1, 2.0]) keep the promoted list-wide suffix, so this never regresses
        # homogeneous lists.
        lowered = [(el, *self.lower_expr(el)) for el in node.elements]

        def _is_spread(el, et):
            # Only treat as spread if it's an explicit spread operator (*seq)
            # Don't treat nested list literals [[...]] as spreads - those should append the list pointer
            return isinstance(el, UnaryOp) and el.op == '*'

        scalar_sufs = {TypeLattice.list_suffix(et)
                       for el, et, _ev in lowered if not _is_spread(el, et)}
        per_element = 'str' in scalar_sufs and scalar_sufs != {'str'}

        for el, et, ev in lowered:
            # Spread element (*seq): extend the list instead of appending
            if _is_spread(el, et):
                self._emit_call('void', '', 'mojo_list_extend', [('MojoList *', t), (et, ev)])
                # Track nested element type if extending with a list that has tracked elements
                # IMPORTANT: Keep _elem_types[t] as 'MojoList *' (what t contains),
                # and set _nested_elem_types[t] to what those lists contain
                if et == 'MojoList *' and ev in self._elem_types:
                    # Don't overwrite _elem_types[t] - it correctly says t contains MojoList*
                    # Instead, track what those lists contain in _nested_elem_types
                    self._nested_elem_types[t] = self._elem_types[ev]
                continue
            use = TypeLattice.list_suffix(et) if per_element else suf
            ev_cast = self._cast_for_list(et, ev, use)
            # GIMPLE: load global string literals into temp before function call
            if use == 'str' and ev_cast.startswith('_slit_'):
                temp = self._new_val('char *', f'{ev_cast}')
                ev_cast = temp
            self._emit(f"  mojo_list_append_{use} ({t}, {ev_cast});")
        return 'MojoList *', t

    def _lower_dict_literal(self, node: DictExpr) -> tuple[str, str]:
        t = self._new_val('MojoDict *', "mojo_dict_new ()")
        # Infer value type from first pair (for subscript / iteration dispatch)
        if node.pairs:
            vt_sample = self._quick_type(node.pairs[0][1])
            if vt_sample in _FLOAT_TYPES:
                self._dict_val_types[t] = 'double'
            elif vt_sample == 'char *':
                self._dict_val_types[t] = 'char *'
            else:
                self._dict_val_types[t] = 'int64_t'
        for key_expr, val_expr in node.pairs:
            kt, kv = self.lower_expr(key_expr)
            vt, vv = self.lower_expr(val_expr)
            # Load global string literals into temps before passing to dict functions
            if kv.startswith('_slit_'):
                kv_tmp = self._new_val('char *', f"{kv}")
                kv = kv_tmp
            elif kt != 'char *':
                # Runtime dict keys are always char *; coerce non-string keys
                # (e.g. Int keys) so GIMPLE doesn't see int→pointer at the call.
                kv_tmp = self._new_temp('char *')
                self._safe_coerce_emit(kt, 'char *', kv, kv_tmp)
                kv = kv_tmp
            if vt in _FLOAT_TYPES:
                self._emit(f"  mojo_dict_set_double ({t}, {kv}, {vv});")
            elif vt == 'char *':
                if vv.startswith('_slit_'):
                    vv_tmp = self._new_val('char *', f"{vv}")
                    vv = vv_tmp
                self._emit(f"  mojo_dict_set_str ({t}, {kv}, {vv});")
            else:
                vv64 = self._to_int64(vt, vv)
                self._emit(f"  mojo_dict_set_int ({t}, {kv}, {vv64});")
        return 'MojoDict *', t

    def _lower_set_literal(self, node: SetExpr) -> tuple[str, str]:
        t = self._new_val('MojoSet *', "mojo_set_new ()")
        for el in node.elements:
            et, ev = self.lower_expr(el)
            if et == 'char *':
                self._emit_call('void', '', 'mojo_set_add_str', [('MojoSet *', t), ('char *', ev)])
            else:
                ev64 = self._to_int64(et, ev)
                self._emit_call('void', '', 'mojo_set_add_int', [('MojoSet *', t), ('int64_t', ev64)])
        return 'MojoSet *', t

    def _lower_tuple_literal(self, node: TupleExpr) -> tuple[str, str]:
        # Tuples lowered as MojoList (immutable semantics not enforced at C level).
        # Tuples are heterogeneous by nature — e.g. ('int', 5) — so a single
        # list-wide append suffix would mis-type elements (append_str on an int).
        # Append each element by its own type when the tuple mixes string and
        # non-string elements; otherwise keep the list-wide suffix (same logic as
        # _lower_list_literal).
        elem = self._infer_list_elem_type(node.elements)
        suf  = TypeLattice.list_suffix(elem)
        t    = self._new_temp('MojoList *')
        self._elem_types[t] = elem
        self._emit(f"  {t} = mojo_list_new ();")
        lowered = [(el, *self.lower_expr(el)) for el in node.elements]
        scalar_sufs = {TypeLattice.list_suffix(et) for _el, et, _ev in lowered}
        per_element = 'str' in scalar_sufs and scalar_sufs != {'str'}
        for _el, et, ev in lowered:
            use = TypeLattice.list_suffix(et) if per_element else suf
            ev_cast = self._cast_for_list(et, ev, use)
            # GIMPLE: load global string literals into temp before function call
            if use == 'str' and ev_cast.startswith('_slit_'):
                temp = self._new_val('char *', f'{ev_cast}')
                ev_cast = temp
            self._emit(f"  mojo_list_append_{use} ({t}, {ev_cast});")
        return 'MojoList *', t

    # ── Comprehension lowering ────────────────────────────────────────────

    def _lower_comprehension(self, node: Comprehension) -> tuple[str, str]:
        if not node.generators:
            t = self._new_temp('int')
            # Skip emitting comment to avoid GIMPLE global-passing issues
            self._emit(f"  {t} = 0;")
            return 'int', t

        gen0 = node.generators[0]

        if node.kind == 'list':
            res_type, res_new = 'MojoList *', 'mojo_list_new'
        elif node.kind == 'set':
            res_type, res_new = 'MojoSet *', 'mojo_set_new'
        elif node.kind == 'dict':
            res_type, res_new = 'MojoDict *', 'mojo_dict_new'
        elif node.kind == 'generator':
            # Generator expressions: convert to list for simplicity
            # (In a full implementation, these would be lazily evaluated)
            res_type, res_new = 'MojoList *', 'mojo_list_new'
        else:
            t = self._new_temp('int')
            self._emit(f"  /* TODO: comprehension kind {node.kind!r} */")
            self._emit(f"  {t} = 0;")
            return 'int', t

        res = self._new_val(res_type, f"{res_new} ()")

        is_range = (isinstance(gen0.iterable, CallExpr) and
                    isinstance(gen0.iterable.func, IdentExpr) and
                    gen0.iterable.func.name == 'range')

        it_type = ''
        if not is_range:
            it_type, it_val = self.lower_expr(gen0.iterable)

        if is_range:
            self._compr_range_loop(node, gen0, res, res_type)
        elif it_type == 'MojoList *':
            self._compr_list_loop(node, gen0, res, res_type, it_val)
        elif it_type == 'MojoStr *':
            self._compr_str_loop(node, gen0, res, res_type, it_val)
        elif it_type == 'MojoDict *':
            self._compr_dict_loop(node, gen0, res, res_type, it_val)
        elif it_type == 'MojoSet *':
            self._compr_set_loop(node, gen0, res, res_type, it_val)
        else:
            self._emit(f"  /* TODO: comprehension over {it_type} */")

        return res_type, res

    def _compr_range_loop(self, node, gen0, res, res_type):
        self._declare_var(gen0.target, 'int64_t')
        args = gen0.iterable.args
        dynamic_step = False
        if len(args) == 1:
            start_v, step_v, cond_op = '0', '1', '<'
            _, stop_v = self.lower_expr(args[0])
        elif len(args) == 2:
            _, start_v = self.lower_expr(args[0])
            _, stop_v  = self.lower_expr(args[1])
            step_v, cond_op = '1', '<'
        elif len(args) == 3:
            _, start_v = self.lower_expr(args[0])
            _, stop_v  = self.lower_expr(args[1])
            se = args[2]
            if isinstance(se, IntLiteral) and se.value < 0:
                cond_op = '>'
            elif isinstance(se, UnaryOp) and se.op == '-':
                cond_op = '>'
            elif isinstance(se, IntLiteral):
                cond_op = '<'
            else:
                cond_op = '<'; dynamic_step = True
            _, step_v = self.lower_expr(se)
        else:
            return

        self._emit(f"  {gen0.target} = {start_v};")
        bb_cond = self._new_bb(); bb_body = self._new_bb()
        bb_post = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        if dynamic_step:
            t_lt = self._new_temp('_Bool'); t_gt = self._new_temp('_Bool')
            t_sp = self._new_temp('_Bool'); cond_t = self._new_temp('_Bool')
            self._emit(f"  {t_lt} = {gen0.target} < {stop_v};")
            self._emit(f"  {t_gt} = {gen0.target} > {stop_v};")
            self._emit(f"  {t_sp} = {step_v} > 0;")
            self._emit(f"  {cond_t} = {t_sp} ? {t_lt} : {t_gt};")
        else:
            cond_t = self._new_val('_Bool', f"{gen0.target} {cond_op} {stop_v}")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        st = self._new_val('int', f"{gen0.target} + {step_v}")
        self._emit(f"  {gen0.target} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _compr_list_loop(self, node, gen0, res, res_type, it_val):
        # Detect tuple unpacking target: "_, av" or "(_, av)"
        target_str = gen0.target.strip()
        inner_str = target_str[1:-1].strip() if (target_str.startswith('(') and target_str.endswith(')')) else target_str
        if ',' in inner_str:
            # Tuple target: each element of the outer list is a sub-list (tuple)
            var_names = [v.strip() for v in inner_str.split(',')]
            for vn in var_names:
                self._declare_var(vn, 'int64_t')
            len64 = self._new_val('int64_t', f'mojo_list_len ({it_val})')
            idx64 = self._new_val('int64_t', '(int64_t)0')
            bb_cond = self._new_bb(); bb_body = self._new_bb()
            bb_post = self._new_bb(); bb_after = self._new_bb()
            self._emit(f"  goto {bb_cond};")
            self._emit_label(bb_cond)
            cond_t = self._new_val('_Bool', f"{idx64} < {len64}")
            self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
            self._emit_label(bb_body)
            raw_elem = self._new_val('int64_t', f"mojo_list_get_int ({it_val}, {idx64})")
            sub_list = self._new_val('MojoList *', f"(MojoList *){raw_elem}")
            for i, vn in enumerate(var_names):
                i64 = self._new_val('int64_t', f"(int64_t){i}")
                sub_str = self._new_val('char *', f"mojo_list_get_str ({sub_list}, {i64})")
                sub_val = self._new_val('int64_t', f"(int64_t){sub_str}")
                self._emit(f"  {vn} = {sub_val};")
            self._gen_compr_append(node, gen0, res, res_type, bb_after)
            self._emit(f"  goto {bb_post};")
            self._emit_label(bb_post)
            one64 = self._new_val('int64_t', "(int64_t)1")
            st = self._new_val('int64_t', f"{idx64} + {one64}")
            self._emit(f"  {idx64} = {st};")
            self._emit(f"  goto {bb_cond};")
            self._emit_label(bb_after)
            return
        elem = self._elem_of(it_val)
        self._declare_var(gen0.target, elem)
        len64 = self._new_val('int64_t', f'mojo_list_len ({it_val})')
        idx64 = self._new_val('int64_t', '(int64_t)0')
        bb_cond = self._new_bb(); bb_body = self._new_bb()
        bb_post = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_val('_Bool', f"{idx64} < {len64}")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        suf = TypeLattice.list_suffix(elem)
        if suf == 'double':
            self._emit(f"  {gen0.target} = mojo_list_get_double ({it_val}, {idx64});")
        elif suf == 'str':
            # mojo_list_get_str returns char*, handle type mismatch with target variable
            temp_str = self._new_val('char *', f"mojo_list_get_str ({it_val}, {idx64})")
            target_type = self._type_of(gen0.target)
            if target_type == 'char *':
                self._emit(f"  {gen0.target} = {temp_str};")
            else:
                # Cast to int64_t if target is opaque
                int_ptr = self._new_val('int64_t', f"(int64_t){temp_str}")
                self._emit(f"  {gen0.target} = {int_ptr};")
        else:
            raw64 = self._new_val('int64_t', f"mojo_list_get_int ({it_val}, {idx64})")
            self._emit(f"  {gen0.target} = ({elem}) {raw64};")
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        one64 = self._new_val('int64_t', "(int64_t)1")
        st = self._new_val('int64_t', f"{idx64} + {one64}")
        self._emit(f"  {idx64} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _compr_str_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'char')
        len64 = self._new_val('int64_t', f'mojo_str_len ({it_val})')
        idx64 = self._new_val('int64_t', '(int64_t)0')
        bb_cond = self._new_bb(); bb_body = self._new_bb()
        bb_post = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_val('_Bool', f"{idx64} < {len64}")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        self._emit(f"  {gen0.target} = mojo_str_char_at ({it_val}, {idx64});")
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        one64 = self._new_val('int64_t', "(int64_t)1")
        st = self._new_val('int64_t', f"{idx64} + {one64}")
        self._emit(f"  {idx64} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _compr_dict_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'char *')
        iter_t = self._new_temp('MojoDictIter *')
        more_t = self._new_temp('int')
        self._emit(f"  {iter_t} = mojo_dict_iter_new ({it_val});")
        bb_cond = self._new_bb(); bb_body = self._new_bb()
        bb_post = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        self._emit(f"  {more_t} = mojo_dict_iter_next ({iter_t});")
        cond_t = self._new_val('_Bool', f"{more_t} != 0")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        key_tmp = self._new_val('const char *', f"mojo_dict_iter_key ({iter_t})")
        tgt = gen0.target
        vt = self.var_types.get(tgt, 'char *')
        if vt in ('int64_t', 'int', 'int32_t'):
            self._emit(f"  {tgt} = (int64_t)(uintptr_t) {key_tmp};")
        else:
            self._emit(f"  {tgt} = (char *) {key_tmp};")
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)
        self._emit(f"  mojo_dict_iter_free ({iter_t});")

    def _compr_set_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'int64_t')
        iter_t = self._new_temp('MojoSetIter *')
        more_t = self._new_temp('int')
        self._emit(f"  {iter_t} = mojo_set_iter_new ({it_val});")
        bb_cond = self._new_bb(); bb_body = self._new_bb()
        bb_post = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        self._emit(f"  {more_t} = mojo_set_iter_next ({iter_t});")
        cond_t = self._new_val('_Bool', f"{more_t} != 0")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        self._emit(f"  {gen0.target} = mojo_set_iter_val_int ({iter_t});")
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)
        self._emit(f"  mojo_set_iter_free ({iter_t});")

    def _gen_compr_append(self, node: Comprehension, gen0, res: str,
                          res_type: str, bb_skip: str):
        if gen0.conditions:
            bb_append = self._new_bb()
            for cond_expr in gen0.conditions:
                _, cv = self.lower_expr(cond_expr)
                bb_next = self._new_bb()
                self._emit(f"  if ({cv}) goto {bb_next}; else goto {bb_skip};")
                self._emit_label(bb_next)
            self._emit_label(bb_append)

        if node.kind == 'list':
            et, ev = self.lower_expr(node.element)
            suf = TypeLattice.list_suffix(et)
            ev_cast = self._cast_for_list(et, ev, suf)
            # GIMPLE: load global string literals into temp before function call
            if suf == 'str' and ev_cast.startswith('_slit_'):
                temp = self._new_val('char *', f'{ev_cast}')
                ev_cast = temp
            self._emit(f"  mojo_list_append_{suf} ({res}, {ev_cast});")
            # Track element type so downstream for-loops use the right accessor
            self._elem_types[res] = et
        elif node.kind == 'set':
            et, ev = self.lower_expr(node.element)
            if et == 'char *':
                self._emit_call('void', '', 'mojo_set_add_str', [('MojoSet *', res), ('char *', ev)])
            else:
                ev64 = self._to_int64(et, ev)
                self._emit_call('void', '', 'mojo_set_add_int', [('MojoSet *', res), ('int64_t', ev64)])
        elif node.kind == 'dict':
            kt, kv = self.lower_expr(node.element)   # element = key expression in dict compr
            vt, vv = self.lower_expr(node.key)        # key field holds the value expression
            # parser stores dict comprehension as: element=key_expr, key=val_expr
            # Dict keys are char* in the runtime: coerce the key to a char* local
            # (handles a non-char* key, e.g. one boxed as int64_t, and loads
            # global string literals into locals first).
            if kt != 'char *':
                kv_tmp = self._new_temp('char *')
                self._safe_coerce_emit(kt, 'char *', kv, kv_tmp)
                kv = kv_tmp
            elif kv.startswith('_slit_'):
                kv_tmp = self._new_val('char *', f"{kv}")
                kv = kv_tmp
            if vt in _FLOAT_TYPES:
                self._emit(f"  mojo_dict_set_double ({res}, {kv}, {vv});")
            elif vt == 'char *':
                if vv.startswith('_slit_'):
                    vv_tmp = self._new_val('char *', f"{vv}")
                    vv = vv_tmp
                self._emit(f"  mojo_dict_set_str ({res}, {kv}, {vv});")
            else:
                vv64 = self._to_int64(vt, vv)
                self._emit(f"  mojo_dict_set_int ({res}, {kv}, {vv64});")

    # ── Print helper ───────────────────────────────────────────────────────

    def _gen_print(self, args: list):
        if not args:
            self._emit('  mojo_print ("");')
            return
        parts = [self.lower_expr(a) for a in args]
        for i, (atype, aval) in enumerate(parts):
            if atype == 'char *':
                self._emit(f'  mojo_print ({aval});')
            else:
                t = self._new_temp('char *')
                vp = self._new_temp('void *')
                fmt = TypeLattice.printf_fmt(atype)
                self._emit(f'  {vp} = malloc (256);')
                self._emit(f'  {t} = (char *) {vp};')
                self._emit(f'  sprintf ({t}, "{fmt}", {aval});')
                self._emit(f'  mojo_print ({t});')
                self._emit(f'  free ({t});')
            if i < len(parts) - 1:
                self._emit('  mojo_print (" ");')
        self._emit('  mojo_print ("\\n");')

    # ── Compile-time constant evaluators (for comptime) ───────────────────

    def _eval_const_int(self, node) -> int | None:
        """Evaluate an expression as a compile-time integer, or return None."""
        if isinstance(node, IntLiteral):  return node.value
        if isinstance(node, BoolLiteral): return int(node.value)
        if isinstance(node, UnaryOp) and node.op == '-':
            v = self._eval_const_int(node.operand)
            return -v if v is not None else None
        if isinstance(node, BinaryOp):
            l = self._eval_const_int(node.left)
            r = self._eval_const_int(node.right)
            if l is None or r is None: return None
            ops = {'+': l+r, '-': l-r, '*': l*r, '//': l//r if r else None,
                   '%': l%r if r else None, '**': l**r}
            return ops.get(node.op)
        # comptime call to an imported function with constant args (slice 3):
        # run it at compile time as cached machine code via comptime.evaluate.
        if isinstance(node, CallExpr) and isinstance(node.func, IdentExpr):
            src_path = self._imported_fn_sources.get(node.func.name)
            if src_path:
                argvals = [self._eval_const_int(a) for a in node.args]
                if argvals and all(v is not None for v in argvals):
                    try:
                        import elaborate, comptime
                        module_src = open(src_path).read()
                        fn_src = elaborate.extract_fn_source(module_src, node.func.name)
                        if fn_src:
                            return int(comptime.evaluate(fn_src, node.func.name, argvals))
                    except Exception as e:
                        _debug_note(f'comptime evaluation of {node.func.name!r} failed', e)
        return None

    def _eval_const_bool(self, node) -> bool | None:
        """Evaluate an expression as a compile-time bool, or return None."""
        if isinstance(node, BoolLiteral): return node.value
        if isinstance(node, IntLiteral):  return bool(node.value)
        if isinstance(node, UnaryOp) and node.op == 'not':
            v = self._eval_const_bool(node.operand)
            return not v if v is not None else None
        if isinstance(node, BinaryOp):
            if node.op in ('and', 'or'):
                l = self._eval_const_bool(node.left)
                r = self._eval_const_bool(node.right)
                if l is None or r is None: return None
                return (l and r) if node.op == 'and' else (l or r)
            l = self._eval_const_int(node.left)
            r = self._eval_const_int(node.right)
            if l is None or r is None: return None
            ops = {'==': l==r, '!=': l!=r, '<': l<r, '<=': l<=r, '>': l>r, '>=': l>=r}
            return ops.get(node.op)
        return None

    # ── Statement generation ───────────────────────────────────────────────

    def gen_stmt(self, node):
        # Emit #line directive to track source location. Critical for debugging:
        # optimizations intermix and reorder code from different lines and files.
        # Only emit if we haven't emitted this exact (filename, line) pair before.
        if hasattr(node, 'line') and node.line and node.line > 0:
            filename = getattr(self, '_current_filename', '')
            emitted_pairs = getattr(self, '_emitted_line_pairs', set())

            # Create unique key for this (filename, line) combination
            pair_key = (filename, node.line)

            # Emit #line only if we haven't emitted this exact pair before
            if pair_key not in emitted_pairs:
                if filename:
                    self._emit(f"#line {node.line} \"{filename}\"")
                else:
                    self._emit(f"#line {node.line}")
                emitted_pairs.add(pair_key)
                self._emitted_line_pairs = emitted_pairs

        handler_name = _STMT_DISPATCH.get(type(node).__name__)
        if handler_name:
            getattr(self, handler_name)(node)
        else:
            _debug_note('unknown statement dropped', type(node).__name__)
            self._emit(f"  /* TODO: {type(node).__name__} */")

    # ── Statement handlers (one per AST node type) ────────────────────────

    def _gen_stmt_PassStmt(self, node):
        return

    def _gen_stmt_VarDecl(self, node):
        # Tuple VarDecl: parser sets name='a,b' for `a, b = expr`. Lower as individual
        # assignments to avoid GIMPLE's implicit multi-value decl which causes
        # "redeclaration with no linkage" when the names were already declared.
        if isinstance(node.name, str) and ',' in node.name and node.value is not None:
            names = [n.strip() for n in node.name.split(',')]
            vtype, v = self.lower_expr(node.value)
            for i, n in enumerate(names):
                if n == '_':
                    continue
                self._declare_var(n, 'int64_t')
                ip = self._new_val('int64_t', f"(int64_t){i}")
                ti = self._new_temp('int64_t')
                iv = self._new_val('int64_t', f"(int64_t){v}")
                lp_cast = self._new_val('MojoList *', f"(MojoList *){iv}")
                self._emit(f"  {ti} = mojo_list_get_int ({lp_cast}, {ip});")
                # Use the C name (a target like `char` is renamed to `_char`).
                self._emit(f"  {self._write_dest(n)} = {ti};")
            return
        if node.type_ann in self.struct_field_types and node.value is not None:
            layout = self._struct_layout.get(node.name, LayoutSolver.HEAP)
            self._layout_hint = layout
        if node.value is not None:
            vtype, v = self.lower_expr(node.value)
            # Type inference: if no annotation, use the value's type instead of 'int'
            if node.type_ann is None:
                ctype = vtype
            else:
                ctype = self._resolve_type(node.type_ann)
            self._declare_var(node.name, ctype)
            # Use the actual declared type (may differ if variable was already declared
            # in an earlier branch with a different inferred type)
            actual_dst = self.var_types.get(node.name, ctype)
            if ctype in ('MojoList *', 'MojoSet *') and v in self._elem_types:
                self._elem_types[node.name] = self._elem_types[v]
            if ctype == 'MojoDict *':
                if v in self._elem_types:
                    self._elem_types[node.name] = self._elem_types[v]
                if v in self._dict_val_types:
                    self._dict_val_types[node.name] = self._dict_val_types[v]
            # If value has element type tracking (e.g. split result), propagate to inferred var
            if node.type_ann is None and v in self._elem_types:
                self._elem_types[node.name] = self._elem_types[v]
            self._safe_coerce_emit(vtype, actual_dst, v, self._write_dest(node.name))
        else:
            ctype = self._resolve_type(node.type_ann)
            self._declare_var(node.name, ctype)
        self._layout_hint = LayoutSolver.HEAP

    def _assign_target(self, tgt, et, ev):
        """Assign a lowered value (et, ev) to one unpack target, which may be a
        plain name or a nested tuple (e.g. (a, b), (c, d) = ...). Recurses for
        nested tuples by indexing the inner iterable."""
        if isinstance(tgt, IdentExpr):
            if tgt.name not in self.var_types:
                hint = self._inferred_var_types.get(self.current_func_name, {}).get(tgt.name) \
                    if hasattr(self, '_inferred_var_types') else None
                self._declare_var(tgt.name, hint or et)
            self._safe_coerce_emit(et, self.var_types[tgt.name], ev, self._write_dest(tgt.name))
        elif isinstance(tgt, TupleExpr):
            # ev is itself an iterable; view it as a MojoList* and unpack by index.
            lp = ev if et == 'MojoList *' else self._new_temp('MojoList *')
            if et != 'MojoList *':
                self._emit(f"  {lp} = (MojoList *){ev};")
            for i, sub in enumerate(tgt.elements):
                idx64 = self._new_val('int64_t', f"(int64_t){i}")
                elem_type = self._elem_of(lp)
                suf = TypeLattice.list_suffix(elem_type)
                set_et = elem_type if elem_type != 'unknown' else 'int64_t'
                sev = self._new_val(set_et, f"mojo_list_get_{suf} ({lp}, {idx64})")
                self._assign_target(sub, set_et, sev)

    def _gen_stmt_AssignStmt(self, node):
        # Tuple unpacking: a, b, c = x, y, z  (targets may nest: (a,b),(c,d) = ...)
        if isinstance(node.target, TupleExpr):
            targets = node.target.elements
            if isinstance(node.value, TupleExpr) and len(node.value.elements) == len(targets):
                # RHS is a tuple literal — lower and assign each element individually
                for tgt, rhs_expr in zip(targets, node.value.elements):
                    et, ev = self.lower_expr(rhs_expr)
                    self._assign_target(tgt, et, ev)
            else:
                # RHS is a single iterable — lower it, then index each element
                vtype, v = self.lower_expr(node.value)
                for i, tgt in enumerate(targets):
                    idx64 = self._new_val('int64_t', f"(int64_t){i}")
                    if vtype == 'MojoList *':
                        elem_type = self._elem_of(v)
                        suf = TypeLattice.list_suffix(elem_type)
                        et = elem_type if elem_type != 'unknown' else 'int64_t'
                        # mojo_list_get_int returns int64_t; for pointer elem types we must
                        # store in int64_t first, then cast — GIMPLE rejects direct ptr assignment.
                        if suf == 'int' and et not in ('int64_t', 'int', '_Bool'):
                            raw = self._new_val('int64_t', f"mojo_list_get_int ({v}, {idx64})")
                            ev = self._new_val(et, f"({et}){raw}")
                        else:
                            ev = self._new_val(et, f"mojo_list_get_{suf} ({v}, {idx64})")
                    else:
                        et = 'int64_t'
                        ev = self._new_temp(et)
                        ip = self._new_val('int64_t', f"(int64_t){v}")
                        self._emit(f"  {ev} = {ip};")
                    self._assign_target(tgt, et, ev)
            return
        vtype, v = self.lower_expr(node.value)
        if isinstance(node.target, IdentExpr):
            tname = node.target.name
            # Write to module struct when `global x` was declared in this function
            if tname in self._func_declared_globals and tname in self._global_var_types:
                global_module = getattr(self, '_global_to_module', {}).get(tname, self._current_module_ctx or "root")
                safe_module = _c_field_name(global_module) if global_module else "root"
                field_ref = f"_{safe_module}_globals.{_c_field_name(tname)}"
                gtype = self._global_var_types[tname]
                self._safe_coerce_emit(vtype, gtype, v, field_ref)
                return
            # Check if target is a module-level global (module-scope init path)
            if tname in self._global_var_types and tname not in self.var_types:
                # Skip: module globals are initialized in struct definition, not in _toplevel
                # Complex initialization will need runtime support in future
                return
            # Regular local variable assignment
            if tname not in self.var_types:
                # Check for inferred variable type (from analysis of all assignments)
                func_key = self.current_func_name
                if func_key and hasattr(self, '_inferred_var_types'):
                    if func_key in self._inferred_var_types and tname in self._inferred_var_types[func_key]:
                        ctype = self._inferred_var_types[func_key][tname]
                    else:
                        ctype = vtype
                else:
                    ctype = vtype
                # The pre-pass cannot always see a nested subscript's element type
                # (it runs before the cross-call element contract), so it can hint
                # an integer for what is really a double read. A local assigned a
                # double value is a double — don't silently truncate it.
                if ctype in ('int', 'int64_t') and vtype == 'double':
                    ctype = 'double'
                # 'int' (bare) is the hallucination marker — no real answer. If the
                # value is actually a container pointer (e.g. a dict read whose value
                # type is a dict/list/set), trust ground truth so a later
                # .get()/subscript dispatches on the right container.
                if ctype == 'int' and vtype in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                    ctype = vtype
                self._declare_var(tname, ctype)
            dst = self.var_types[tname]

            if dst in ('MojoList *', 'MojoSet *') and v in self._elem_types:
                self._elem_types[tname] = self._elem_types[v]
                # Also propagate nested element types (for lists of lists)
                if v in self._nested_elem_types:
                    self._nested_elem_types[tname] = self._nested_elem_types[v]
            if dst == 'MojoDict *':
                if v in self._elem_types:
                    self._elem_types[tname] = self._elem_types[v]
                if v in self._dict_val_types:
                    self._dict_val_types[tname] = self._dict_val_types[v]
            # Track actual type if storing a pointer as int64_t
            if dst == 'int64_t':
                # If source has tracked actual type, copy it
                if v in self._actual_types:
                    actual_type = self._actual_types[v]
                    self._actual_types[tname] = actual_type
                # If value type itself is a pointer, track it as the actual type
                elif vtype in ('char *', 'MojoList *', 'MojoDict *', 'MojoSet *'):
                    self._actual_types[tname] = vtype
                    # Also copy element/value type tracking
                    if v in self._elem_types:
                        self._elem_types[tname] = self._elem_types[v]
                    if v in self._dict_val_types:
                        self._dict_val_types[tname] = self._dict_val_types[v]
                # If actual type is a container, track element types
                if tname in self._actual_types:
                    actual_type = self._actual_types[tname]
                    if actual_type == 'MojoList *' and v in self._elem_types:
                        self._elem_types[tname] = self._elem_types[v]
                        # Also propagate nested element types
                        if v in self._nested_elem_types:
                            self._nested_elem_types[tname] = self._nested_elem_types[v]
                    elif actual_type == 'MojoDict *':
                        if v in self._elem_types:
                            self._elem_types[tname] = self._elem_types[v]
                        if v in self._dict_val_types:
                            self._dict_val_types[tname] = self._dict_val_types[v]
            self._safe_coerce_emit(vtype, dst, v, self._write_dest(tname))
        elif isinstance(node.target, MemberExpr):
            ot, ov = self.lower_expr(node.target.obj)
            if ot in ('int', 'int64_t'):
                # Opaque Python object: use mojo_setattr for attribute assignment
                member_str = node.target.member
                key_slit = self._intern_string(_c_escape(member_str))
                key_tmp = self._new_val('char *', f"{key_slit}")
                v64 = self._new_temp('int64_t')
                self._safe_coerce_emit(vtype, 'int64_t', v, v64)
                obj64 = self._to_int64(ot, ov)
                vp_tmp = self._new_val('void *', f"(void *){obj64}")
                self._emit_call('void', '', 'mojo_setattr',
                                [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
            else:
                op = '->' if '*' in ot else '.'
                struct_name = _struct_name_of(ot)
                field_type = self.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
                self._safe_coerce_emit(vtype, field_type, v, f"{ov}{op}{_safe_field(node.target.member)}")
        elif isinstance(node.target, SubscriptExpr):
            ot, obj_v = self.lower_expr(node.target.obj)
            it, idx_v  = self.lower_expr(node.target.index)
            if ot == 'MojoList *':
                elem = self._elem_of(obj_v)
                suf  = TypeLattice.list_suffix(elem)
                idx64 = self._new_val('int64_t', f"(int64_t) {idx_v}")
                ev_cast = self._cast_for_list(vtype, v, suf)
                self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
            elif ot == 'MojoDict *':
                # Record the dict's value type so later reads recover it (esp.
                # pointer values: dict-of-dicts/lists/sets). Homogeneous assumption,
                # matching list element-type tracking.
                if vtype in ('char *', 'double', 'MojoDict *', 'MojoList *', 'MojoSet *'):
                    self._dict_val_types[obj_v] = vtype
                # dict[key] = val → mojo_dict_set_str_*
                key_tmp = self._new_temp('char *')
                self._safe_coerce_emit(it, 'char *', idx_v, key_tmp)
                if vtype == 'char *':
                    self._emit_call('void', '', 'mojo_dict_set_str',
                                    [('MojoDict *', obj_v), ('char *', key_tmp), ('char *', v)])
                else:
                    # Pass actual vtype so _emit_call can coerce pointers to int64_t
                    self._emit_call('void', '', 'mojo_dict_set_int',
                                    [('MojoDict *', obj_v), ('char *', key_tmp), (vtype, v)])
            else:
                # Opaque int-typed container: check if it's a list or dict
                if ot in ('int', 'int64_t'):
                    # Check if this is actually a list (from nested access) or dict
                    actual_type = self._get_actual_type(ot, obj_v)
                    if actual_type == 'MojoList *':
                        # It's a list - cast to MojoList* and set element
                        ip = self._new_temp('int64_t')
                        lp = self._new_temp('MojoList *')
                        self._emit(f"  {ip} = (int64_t){obj_v};")
                        self._emit(f"  {lp} = (MojoList *){ip};")
                        idx64 = self._new_val('int64_t', f"(int64_t){idx_v}")
                        # Get element type from the nested list
                        # First try _elem_of, then check _nested_elem_types, then default to int64_t
                        elem = self._elem_of(obj_v)
                        if not elem or elem == 'int64_t':
                            if obj_v in self._elem_types:
                                elem = self._elem_types[obj_v]
                            elif obj_v in self._nested_elem_types:
                                elem = self._nested_elem_types[obj_v]
                        elem = elem or 'int64_t'
                        suf = TypeLattice.list_suffix(elem)
                        ev_cast = self._cast_for_list(vtype, v, suf)
                        self._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {ev_cast});")
                    else:
                        # Default to dict (original behavior)
                        ip = self._new_temp('int64_t')
                        dp = self._new_temp('MojoDict *')
                        self._emit(f"  {ip} = (int64_t){obj_v};")
                        self._emit(f"  {dp} = (MojoDict *){ip};")
                        key_tmp2 = self._new_temp('char *')
                        self._safe_coerce_emit(it, 'char *', idx_v, key_tmp2)
                        # Pass actual vtype so _emit_call can coerce pointers to int64_t
                        self._emit_call('void', '', 'mojo_dict_set_int',
                                        [('MojoDict *', dp), ('char *', key_tmp2), (vtype, v)])
                else:
                    if not self._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                        # GIMPLE strict: raw pointer subscript write needs address in a register.
                        # e.g. int64_t *ptr; ptr[i] = 0  must use _mojo_at_int64_t helper.
                        if ot.endswith(' *'):
                            elem_t = ot[:-2].rstrip()  # e.g. 'int64_t' from 'int64_t *'
                            if elem_t in self.struct_field_types:
                                # Struct values can't be in GIMPLE registers — emit no-op
                                self._emit(f"  /* TODO: struct subscript write [{elem_t}] skipped */")
                            else:
                                self._ptr_helpers_needed.add(elem_t)
                                idx64 = self._new_val('int64_t', f"(int64_t){idx_v}")
                                # Cast obj_v to the pointer type (it may be stored as integer)
                                ptr_typed = self._new_val(ot, f"({ot}){obj_v}")
                                addr = self._new_val(ot, f"_mojo_at_{_c_id(elem_t)} ({ptr_typed}, {idx64})")
                                v_cast = self._new_temp(elem_t)
                                self._safe_coerce_emit(vtype, elem_t, v, v_cast)
                                self._emit(f"  *{addr} = {v_cast};")
                        else:
                            self._emit(f"  {obj_v}[{idx_v}] = {v};")
        else:
            pass

    def _gen_stmt_AugAssignStmt(self, node):
        base_op = node.op[:-1]
        # For augmented assignments, use lower_expr with a fake BinaryOp to get proper type handling
        # This includes string concatenation, list concatenation, etc.
        if base_op in ('//', '**', '+', '-', '*', '/', '%', '|', '&', '^', '<<', '>>'):
            fake  = BinaryOp(op=base_op, left=node.target, right=node.value)
            vtype, v = self.lower_expr(fake)
        else:
            c_op = _BIN_OPS.get(base_op, base_op)
            rtype, rv = self.lower_expr(node.value)
            if isinstance(node.target, IdentExpr):
                tname  = node.target.name
                ttype  = self._type_of(tname)
                arith  = TypeLattice.join(ttype, rtype)
                lv_a   = self._cname(tname)
                rv_a   = rv
                if ttype != arith:
                    ct = self._new_val(arith, f"({arith}){self._cname(tname)}")
                    lv_a = ct
                if rtype != arith:
                    ct = self._new_val(arith, f"({arith}){rv}")
                    rv_a = ct
                tmp = self._new_val(arith, f"{lv_a} {c_op} {rv_a}")
                vtype, v = arith, tmp
            else:
                # Skip emitting comment to avoid GIMPLE global-passing issues
                return
        if isinstance(node.target, IdentExpr):
            tname = node.target.name
            dst   = self._type_of(tname)
            self._safe_coerce_emit(vtype, dst, v, self._write_dest(tname))
        elif isinstance(node.target, MemberExpr):
            ot, ov = self.lower_expr(node.target.obj)
            if ot in ('int', 'int64_t'):
                member_str = node.target.member
                key_slit = self._intern_string(_c_escape(member_str))
                key_tmp = self._new_val('char *', f"{key_slit}")
                v64 = self._new_temp('int64_t')
                self._safe_coerce_emit(vtype, 'int64_t', v, v64)
                vp_tmp = self._new_val('void *', f"(void *){ov}")
                self._emit_call('void', '', 'mojo_setattr',
                                [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
            else:
                op = '->' if '*' in ot else '.'
                self._emit(f"  {ov}{op}{_safe_field(node.target.member)} = {v};")
        elif isinstance(node.target, SubscriptExpr):
            ot, obj_v = self.lower_expr(node.target.obj)
            _, idx_v  = self.lower_expr(node.target.index)
            if ot == 'MojoList *':
                elem = self._elem_of(obj_v)
                suf  = TypeLattice.list_suffix(elem)
                idx64 = self._new_val('int64_t', f"(int64_t) {idx_v}")
                self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {v});")
            elif ot in ('int', 'int64_t'):
                # Opaque int/int64_t used as subscript target — treat as MojoList write
                ip = self._new_val('int64_t', f"(int64_t){obj_v}")
                lp = self._new_val('MojoList *', f"(MojoList *){ip}")
                elem = self._elem_of(obj_v)
                suf = TypeLattice.list_suffix(elem)
                idx64 = self._new_val('int64_t', f"(int64_t) {idx_v}")
                self._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {v});")
            elif ot.endswith(' *') and _struct_name_of(ot) not in self.struct_field_types:
                # Raw C pointer: use _mojo_at_ helper (GIMPLE doesn't allow ptr arithmetic)
                if not self._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                    elem_t = _elem_type(ot)
                    cn = _c_id(elem_t)
                    self._ptr_helpers_needed.add(elem_t)
                    idx64 = self._new_val('int64_t', f"(int64_t) {idx_v}")
                    ptr_t = self._new_val(ot, f"({ot}){obj_v}")
                    addr = self._new_val(ot, f"_mojo_at_{cn} ({ptr_t}, {idx64})")
                    v_cast = self._new_temp(elem_t)
                    self._safe_coerce_emit(vtype, elem_t, v, v_cast)
                    self._emit(f"  *{addr} = {v_cast};")
            else:
                if not self._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                    self._emit(f"  {obj_v}[{idx_v}] = {v};")
        else:
            pass  # complex aug-assign target: no-op

    def _gen_stmt_ReturnStmt(self, node):
        if node.value is None:
            # If function returns non-void, return default value
            if self.func_ret_type and self.func_ret_type != 'void':
                self._emit(f"  return 0;")
            else:
                self._emit(_RETURN)
        else:
            vtype, v = self.lower_expr(node.value)
            ret = self.func_ret_type
            if ret == 'void':
                self._emit(_RETURN)
            elif ret and ret != 'void' and vtype != ret:
                tmp = self._new_temp(ret)
                self._safe_coerce_emit(vtype, ret, v, tmp)
                self._emit(f"  return {tmp};")
            else:
                self._emit(f"  return {v};")

    def _ensure_bool_cond(self, ctype: str, val: str) -> str:
        """Convert val to a GIMPLE-safe _Bool for use in if/while conditions."""
        if ctype == '_Bool':
            return val
        if ctype in ('char *', 'void *') or (ctype.endswith(' *') and ctype != '_Bool'):
            ip   = self._new_temp('int64_t')
            zero = self._new_temp('int64_t')
            b    = self._new_temp('_Bool')
            self._emit(f"  {ip} = (int64_t){val};")
            self._emit(f"  {zero} = (int64_t)0;")
            self._emit(f"  {b} = {ip} != {zero};")
            return b
        if ctype == 'int64_t':
            zero = self._new_temp('int64_t')
            b    = self._new_temp('_Bool')
            self._emit(f"  {zero} = (int64_t)0;")
            self._emit(f"  {b} = {val} != {zero};")
            return b
        # int and other integer types: avoid GIMPLE type-mismatch by going through int64_t
        if ctype not in ('_Bool',):
            b = self._new_temp('_Bool')
            v64 = self._new_temp('int64_t')
            z64 = self._new_temp('int64_t')
            self._emit(f"  {v64} = (int64_t){val};")
            self._emit(f"  {z64} = (int64_t)0;")
            self._emit(f"  {b} = {v64} != {z64};")
            return b
        return val

    def _gen_stmt_IfStmt(self, node):
        cond_type, cond_v = self.lower_expr(node.condition)
        cond_v  = self._ensure_bool_cond(cond_type, cond_v)
        bb_true     = self._new_bb()
        bb_merge    = self._new_bb()
        has_else    = bool(node.elifs or node.else_body)
        bb_false    = self._new_bb() if has_else else bb_merge

        self._emit(f"  if ({cond_v}) goto {bb_true}; else goto {bb_false};")
        self._emit_label(bb_true)
        for s in node.then_body:
            self.gen_stmt(s)
        self._emit(f"  goto {bb_merge};")

        current_false = bb_false
        elifs = list(node.elifs)
        while elifs:
            ec, eb = elifs.pop(0)
            self._emit_label(current_false)
            has_more   = bool(elifs or node.else_body)
            next_false = self._new_bb() if has_more else bb_merge
            next_true  = self._new_bb()
            _, ev = self.lower_expr(ec)
            self._emit(f"  if ({ev}) goto {next_true}; else goto {next_false};")
            self._emit_label(next_true)
            for s in eb:
                self.gen_stmt(s)
            self._emit(f"  goto {bb_merge};")
            current_false = next_false

        if node.else_body:
            self._emit_label(current_false)
            for s in node.else_body:
                self.gen_stmt(s)
            self._emit(f"  goto {bb_merge};")

        self._emit_label(bb_merge)

    def _gen_stmt_WhileStmt(self, node):
        bb_cond  = self._new_bb()
        bb_body  = self._new_bb()
        bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_type, cond_v = self.lower_expr(node.condition)
        cond_v = self._ensure_bool_cond(cond_type, cond_v)
        self._emit(f"  if ({cond_v}) goto {bb_body}; else goto {bb_after};")
        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        self.loop_stack.append((bb_cond, bb_after))
        for s in node.body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _gen_stmt_MultiAssignStmt(self, node):
        vtype, v = self.lower_expr(node.value)
        for target in node.targets:
            if isinstance(target, IdentExpr):
                tname = target.name
                if tname not in self.var_types:
                    self._declare_var(tname, vtype)
                dst = self.var_types[tname]
                self._safe_coerce_emit(vtype, dst, v, self._write_dest(tname))
            elif isinstance(target, MemberExpr):
                ot, ov = self.lower_expr(target.obj)
                op = '->' if '*' in ot else '.'
                self._emit(f"  {ov}{op}{_safe_field(target.member)} = {v};")
            elif isinstance(target, SubscriptExpr):
                ot, obj_v = self.lower_expr(target.obj)
                it2, idx_v = self.lower_expr(target.index)
                if ot == 'MojoList *':
                    elem = self._elem_of(obj_v)
                    suf  = TypeLattice.list_suffix(elem)
                    idx64 = self._new_val('int64_t', f"(int64_t) {idx_v}")
                    ev_cast = self._cast_for_list(vtype, v, suf)
                    self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
                elif ot == 'MojoDict *':
                    key_tmp = self._new_temp('char *')
                    self._safe_coerce_emit(it2, 'char *', idx_v, key_tmp)
                    self._emit_call('void', '', 'mojo_dict_set_int',
                                    [('MojoDict *', obj_v), ('char *', key_tmp), (vtype, v)])
                elif ot in ('int', 'int64_t'):
                    actual_type = self._get_actual_type(ot, obj_v)
                    if actual_type == 'MojoList *':
                        ip = self._new_temp('int64_t')
                        lp = self._new_temp('MojoList *')
                        self._emit(f"  {ip} = (int64_t){obj_v};")
                        self._emit(f"  {lp} = (MojoList *){ip};")
                        idx64 = self._new_val('int64_t', f"(int64_t){idx_v}")
                        elem = self._elem_of(obj_v) or 'int64_t'
                        suf = TypeLattice.list_suffix(elem)
                        ev_cast = self._cast_for_list(vtype, v, suf)
                        self._emit(f"  mojo_list_set_{suf} ({lp}, {idx64}, {ev_cast});")
                    else:
                        ip = self._new_temp('int64_t')
                        dp = self._new_temp('MojoDict *')
                        self._emit(f"  {ip} = (int64_t){obj_v};")
                        self._emit(f"  {dp} = (MojoDict *){ip};")
                        key_tmp2 = self._new_temp('char *')
                        self._safe_coerce_emit(it2, 'char *', idx_v, key_tmp2)
                        self._emit_call('void', '', 'mojo_dict_set_int',
                                        [('MojoDict *', dp), ('char *', key_tmp2), (vtype, v)])
                elif not self._emit_struct_subscript_write(obj_v, ot, idx_v, v, vtype):
                    self._emit(f"  {obj_v}[{idx_v}] = {v};")
            else:
                pass  # complex multi-assign target: no-op

    def _gen_stmt_ForStmt(self, node):
        if (isinstance(node.iterable, CallExpr) and
                isinstance(node.iterable.func, IdentExpr) and
                node.iterable.func.name == 'range'):
            self._gen_for_range(node)
        elif (isinstance(node.iterable, CallExpr) and
                isinstance(node.iterable.func, IdentExpr) and
                node.iterable.func.name == 'enumerate'):
            self._gen_for_enumerate(node)
        else:
            self._gen_for_iter(node)

    def _gen_stmt_BreakStmt(self, node):
        if self.loop_stack:
            self._emit(f"  goto {self.loop_stack[-1][1]};")
        else:
            # Skip emitting comment to avoid GIMPLE global-passing issues
            pass

    def _gen_stmt_ContinueStmt(self, node):
        if self.loop_stack:
            self._emit(f"  goto {self.loop_stack[-1][0]};")
        else:
            # Skip emitting comment to avoid GIMPLE global-passing issues
            pass

    def _gen_stmt_ExprStmt(self, node):
        if isinstance(node.value, CallExpr) and isinstance(node.value.func, IdentExpr):
            raw_name = node.value.func.name
            if raw_name == 'print':
                self._gen_print(node.value.args)
                return
            if raw_name in ('strided_load', 'strided_store') and node.value.args:
                self._lower_strided(node.value, store=(raw_name == 'strided_store'))
                return
            # Recursive call from inner function to itself
            if raw_name == self._inner_func_name and self._env_param:
                lifted   = self.current_func_name
                env_var  = self._env_param
                arg_vals = [self.lower_expr(a)[1] for a in node.value.args]
                all_args = ', '.join([env_var] + arg_vals)
                fname_c  = _safe_name(lifted)
                self._emit(f"  {fname_c} ({all_args});")
                return
            # Check closure call (nested function defined in this scope)
            if raw_name in self._closure_envs:
                lifted   = f"{self.current_func_name}_{raw_name}"
                env_var  = self._closure_envs[raw_name]
                arg_pairs = [self.lower_expr(a) for a in node.value.args]
                # Handle kwargs for closure calls
                kwargs = getattr(node.value, 'kwargs', []) or []
                kwarg_dict = {kname: self.lower_expr(kexpr) for kname, kexpr in kwargs}
                # Pad kwargs to expected arity
                # Note: expected_params[0] is the env pointer, which gets prepended separately
                expected_params = self.func_param_types.get(lifted, [])
                # Subtract 1 for the env pointer that will be prepended
                user_param_count = len(expected_params) - (1 if env_var and expected_params else 0)
                if expected_params and len(arg_pairs) < user_param_count:
                    kwarg_values = list(kwarg_dict.values())
                    while len(arg_pairs) < user_param_count:
                        if kwarg_values:
                            arg_pairs.append(kwarg_values.pop(0))
                        else:
                            arg_pairs.append(('int', '0'))
                fname_c  = _safe_name(lifted)
                if env_var:
                    env_type = self.func_param_types.get(lifted, ['void *'])[0]
                    full_arg_pairs = [(env_type, env_var)] + arg_pairs
                else:
                    full_arg_pairs = arg_pairs
                self._emit_call('void', '', fname_c, full_arg_pairs)
                return
            # Redirect calls to user's main() to its renamed symbol (root ->
            # _gimple_main; sub-module -> _{module}_main), matching gen_func.
            # If raw_name is a local variable holding a function value (e.g., a
            # Mojo function-type parameter stored as int64_t), calling it directly
            # in GIMPLE is invalid. Stub it out here — same guard as _lower_CallExpr.
            _var_ctype = self.var_types.get(raw_name, '')
            if _var_ctype in ('int', 'int64_t', 'void *', '_Bool'):
                for a in node.value.args: self.lower_expr(a)
                return
            if raw_name == 'main' and self.current_func_name != 'main':
                if self.emit_entry_points:
                    fname = _safe_name('_gimple_main')
                else:
                    _mod_id = self.module_name.replace('.', '_').replace('-', '_') if self.module_name else ''
                    fname = _safe_name(f"_{_mod_id}_main" if _mod_id else '_lib_main')
            else:
                # Mirror the rename logic in _lower_call: only rename _C_RESERVED_FUNCS
                # names when they are locally defined OR imported — otherwise keep the
                # C stdlib name (e.g. abort() from a monomorphized template that has no
                # import statement should stay as abort(), not become mojo_abort()).
                if (raw_name in _C_RESERVED_FUNCS
                        and raw_name not in self.func_return_types
                        and raw_name not in _FORCE_RENAME_RESERVED
                        and raw_name not in self.imported_symbols):
                    fname = self.BUILTIN_VALUE_MAP.get(raw_name, raw_name)
                else:
                    # _func_csym applies the overload suffix to match the definition.
                    fname = self.BUILTIN_VALUE_MAP.get(raw_name, self._func_csym(raw_name))
            arg_pairs = [self.lower_expr(a) for a in node.value.args]

            # Handle keyword arguments for regular function calls
            kwargs = getattr(node.value, 'kwargs', []) or []
            kwarg_dict = {kname: self.lower_expr(kexpr) for kname, kexpr in kwargs}

            # For compile_to_gimple: pad with do_imports and filename kwargs
            if raw_name == 'compile_to_gimple':
                if 'do_imports' in kwarg_dict:
                    arg_pairs.append(kwarg_dict['do_imports'])
                elif len(arg_pairs) < 2:
                    arg_pairs.append(('int', '0'))
                if 'filename' in kwarg_dict:
                    arg_pairs.append(kwarg_dict['filename'])
                elif len(arg_pairs) < 3:
                    arg_pairs.append(('char *', '0'))

            # For interpret_and_execute: pad with filename kwarg
            if raw_name == 'interpret_and_execute':
                if 'filename' in kwarg_dict:
                    arg_pairs.append(kwarg_dict['filename'])
                elif len(arg_pairs) < 2:
                    arg_pairs.append(('int', '0'))

            # General: pad missing args with kwargs when expected param count is known
            expected_params = self.func_param_types.get(raw_name, [])
            if expected_params and len(arg_pairs) < len(expected_params):
                kwarg_values = list(kwarg_dict.values()) if kwarg_dict else []
                while len(arg_pairs) < len(expected_params):
                    if kwarg_values:
                        arg_pairs.append(kwarg_values.pop(0))
                    else:
                        arg_pairs.append(('int', '0'))

            if fname in self._KNOWN_SIGS:
                ret_type = self._KNOWN_SIGS[fname][0]
                self._emit_call(ret_type, '', fname, arg_pairs)
            else:
                # Auto-stub completely unknown names (bracket params, implicit fnptrs)
                _is_unknown_stmt = (raw_name not in self.func_return_types
                                    and raw_name not in self.imported_symbols
                                    and fname not in self._KNOWN_SIGS
                                    and raw_name not in self.BUILTIN_VALUE_MAP
                                    and raw_name not in _C_RESERVED_FUNCS)
                if _is_unknown_stmt and fname not in self._auto_stubbed:
                    _stub_guard = f'_MOJO_STUB_{fname.upper()}'
                    _stub = f'#ifndef {_stub_guard}\n#define {_stub_guard}\nint64_t {fname} (...);\n#endif'
                    if _stub not in self._elaborated_externs:
                        self._elaborated_externs.append(_stub)
                    self._auto_stubbed.add(fname)
                # For user-defined functions, still use _emit_call to handle type coercion
                ret_type = self.func_return_types.get(raw_name, 'void')
                self._emit_call(ret_type, '', fname, arg_pairs)
        else:
            self.lower_expr(node.value)

    def _gen_stmt_AssertStmt(self, node):
        _, v = self.lower_expr(node.value)
        bb_trap = self._new_bb()
        bb_ok   = self._new_bb()
        self._emit(f"  if ({v}) goto {bb_ok}; else goto {bb_trap};")
        self._emit_label(bb_trap)
        if node.msg is not None:
            mt, mv = self.lower_expr(node.msg)
            if mt == 'char *':
                self._emit(f'  puts ({mv});')
            else:
                self._emit(f'  printf ("{TypeLattice.printf_fmt(mt)}\\n", {mv});')
        self._emit("  __builtin_trap ();")
        self._emit(f"  goto {bb_ok};")
        self._emit_label(bb_ok)

    def _gen_stmt_RaiseStmt(self, node):
        # For raise statements with exception constructors like NameError(...),
        # we can't compile them directly to GIMPLE. Just emit mojo_raise().
        # If there's a simple string value, we could set it as the message, but
        # CallExpr nodes (exception constructors) can't be safely lowered.
        self._emit("  mojo_raise ();")

    def _gen_stmt_TryStmt(self, node):
        sj_ret = self._new_temp('int')
        cond_t = self._new_temp('_Bool')
        bb_try   = self._new_bb()
        bb_exc   = self._new_bb()
        bb_else  = self._new_bb() if node.else_body else None
        bb_after = self._new_bb()

        self._emit(f"  {sj_ret} = mojo_try_push ();")
        self._emit(f"  {cond_t} = {sj_ret} != 0;")
        self._emit(f"  if ({cond_t}) goto {bb_exc}; else goto {bb_try};")

        self._emit_label(bb_try)
        for s in node.body:
            self.gen_stmt(s)
        # Only emit mojo_exc_pop and goto if the try body didn't end with a return
        if not self._last_was_terminal:
            self._emit("  mojo_exc_pop ();")
            self._emit(f"  goto {bb_else if bb_else else bb_after};")

        self._emit_label(bb_exc)
        self._emit("  mojo_exc_pop ();")
        for handler in node.handlers:
            if handler.name:
                # Exception handlers are typed as pointers to exception objects
                # Use the exception type from the handler (e.g., ReturnValue, Exception)
                exc_type_name = None
                if handler.exc_type:
                    # Extract the type name from the exception type annotation
                    if hasattr(handler.exc_type, 'name'):
                        exc_type_name = handler.exc_type.name
                    elif isinstance(handler.exc_type, str):
                        exc_type_name = handler.exc_type

                # Determine the C type for the exception
                if exc_type_name and exc_type_name in self.struct_field_types:
                    exc_ctype = f"{exc_type_name} *"
                else:
                    exc_ctype = 'void *'

                self._declare_var(handler.name, exc_ctype)
                # Retrieve the exception object from the runtime
                # Use a temp to avoid casting function call results in GIMPLE
                temp_var = self._new_temp('void *')
                self._declare_var(temp_var, 'void *')
                self._emit(f"  {temp_var} = mojo_exc_obj_get ();")
                self._emit(f"  {handler.name} = ({exc_ctype}) {temp_var};")
            for s in handler.body:
                self.gen_stmt(s)
        if node.finally_body:
            for s in node.finally_body:
                self.gen_stmt(s)
        # Only emit goto if the exception handler didn't end with a return
        if not self._last_was_terminal:
            self._emit(f"  goto {bb_after};")

        if bb_else:
            self._emit_label(bb_else)
            for s in node.else_body:
                self.gen_stmt(s)
            if node.finally_body:
                for s in node.finally_body:
                    self.gen_stmt(s)
            # Only emit goto if the else block didn't end with a return
            if not self._last_was_terminal:
                self._emit(f"  goto {bb_after};")

        self._emit_label(bb_after)

    def _gen_stmt_WithStmt(self, node):
        aliases = []
        for item in node.items:
            et, ev = self.lower_expr(item.expr)
            alias  = None
            if item.alias is not None:
                alias = item.alias if isinstance(item.alias, str) else item.alias.name
                if alias not in self.var_types:
                    self._declare_var(alias, et)
                self._emit(f"  {alias} = {ev};")
            else:
                tmp = self._new_val(et, f"{ev}")
                alias = tmp
            struct_name = _struct_name_of(et)
            enter_fn    = f"{struct_name}___enter__"
            if enter_fn in self.func_return_types:
                self._emit(f"  {enter_fn} ({alias});")
            else:
                self._emit(f"  /* with: __enter__ ({struct_name}) */")
            aliases.append((alias, struct_name))

        def _emit_exits():
            for al, sn in aliases:
                exit_fn = f"{sn}___exit__"
                if exit_fn in self.func_return_types:
                    self._emit(f"  {exit_fn} ({al});")
                else:
                    self._emit(f"  /* with: __exit__ ({sn}) */")

        has_exit = any(f"{sn}___exit__" in self.func_return_types
                       for _, sn in aliases)

        if has_exit:
            sj_ret = self._new_temp('int')
            cond_t = self._new_temp('_Bool')
            bb_try   = self._new_bb()
            bb_exc   = self._new_bb()
            bb_after = self._new_bb()
            self._emit(f"  {sj_ret} = mojo_try_push ();")
            self._emit(f"  {cond_t} = {sj_ret} != 0;")
            self._emit(f"  if ({cond_t}) goto {bb_exc}; else goto {bb_try};")

            self._emit_label(bb_try)
            for s in node.body:
                self.gen_stmt(s)
            # Only emit cleanup and goto if the with body didn't end with a return
            if not self._last_was_terminal:
                self._emit("  mojo_exc_pop ();")
                _emit_exits()
                self._emit(f"  goto {bb_after};")
            else:
                _emit_exits()

            self._emit_label(bb_exc)
            self._emit("  mojo_exc_pop ();")
            _emit_exits()
            self._emit("  mojo_raise ();")
            # Only emit goto if the exception handler didn't end with a return
            if not self._last_was_terminal:
                self._emit(f"  goto {bb_after};")

            self._emit_label(bb_after)
        else:
            for s in node.body:
                self.gen_stmt(s)
            _emit_exits()

    def _gen_stmt_FunctionDef(self, node):
        outer_closures = getattr(self, '_all_closures', {}).get(
            self.current_func_name, {})
        ci = outer_closures.get(node.name)
        if ci is None:
            self._emit(f"  /* TODO: closure '{node.name}' (no pre-pass info) */")
            return
        if ci.captures:
            env_var  = f"_env_{node.name}"
            alloc_fn = f"_alloc_{ci.env_struct}"
            self._declare_var(env_var, f"{ci.env_struct} *")
            self._emit(f"  {env_var} = {alloc_fn} ();")
            for vname, vtype in ci.captures:
                # If vname is captured in the current function's own env, read from _env->vname.
                if vname in self._captures and self._env_param:
                    # GIMPLE: cannot use component_ref directly as RHS of struct store;
                    # load into a temp first.
                    tmp = self._new_val(vtype, f"{self._env_param}->{vname}")
                    self._emit(f"  {env_var}->{vname} = {tmp};")
                else:
                    # Use _safe_coerce_emit to handle int→int64_t and other conversions.
                    local_type = self.var_types.get(vname, vtype)
                    cname = self._write_dest(vname)  # resolve capture path if nested
                    self._safe_coerce_emit(local_type, vtype, cname, f"{env_var}->{vname}")
            self._closure_envs[node.name] = env_var
        else:
            self._closure_envs[node.name] = ''

    def _gen_stmt_ImportStmt(self, node):
        # import module [as alias][, module2 [as alias2], ...] — handle every
        # target in a comma-separated list (node.extra), not just the first.
        targets = [(node.module, node.alias)] + list(getattr(node, 'extra', None) or [])
        for module, alias in targets:
            local_name = alias if alias else module
            self.imported_symbols[local_name] = {
                'module': module,
                'return_type': 'unknown',
            }
            # Declare the module as an int marker for attribute access
            # This allows code like os.path.basename() to work
            if local_name not in self.var_types:
                self._declare_var(local_name, 'int64_t')
                # GIMPLE: an int64_t lvalue needs an int64_t-typed constant, not a
                # bare `0` (which is `int`) — that is a non-trivial integer_cst.
                self._emit(f"  {local_name} = (int64_t)0;  /* module marker */")


    def _gen_stmt_FromImportStmt(self, node):
        # from module import name1, name2, ...
        for name, alias in node.names:
            symbol_name = alias if alias else name
            # Use known signature if available
            sig = self._KNOWN_SIGS.get(symbol_name)
            ret = sig[0] if sig else 'int'
            self.imported_symbols[symbol_name] = {
                'module': node.module,
                'return_type': ret,
            }
            # Track in func_return_types so calls know the return type
            if symbol_name not in self.func_return_types:
                self.func_return_types[symbol_name] = ret

    def _gen_stmt_ComptimeIfStmt(self, node):
        val = self._eval_const_bool(node.condition)
        if val is True:
            for s in node.then_body:
                self.gen_stmt(s)
            return
        if val is False:
            # Try each elif branch before falling to else
            for elif_cond, elif_body in (getattr(node, 'elifs', None) or []):
                elif_val = self._eval_const_bool(elif_cond)
                if elif_val is True:
                    for s in elif_body:
                        self.gen_stmt(s)
                    return
                if elif_val is False:
                    continue
                # Unknown at compile time: emit as runtime branch
                _, cv = self.lower_expr(elif_cond)
                bb_t = self._new_bb(); bb_m = self._new_bb()
                self._emit(f"  if ({cv}) goto {bb_t}; else goto {bb_m};")
                self._emit_label(bb_t)
                for s in elif_body:
                    self.gen_stmt(s)
                self._emit(f"  goto {bb_m};")
                self._emit_label(bb_m)
                return
            if node.else_body:
                for s in node.else_body:
                    self.gen_stmt(s)
            return
        # Condition unknown at compile time: emit full runtime if-elif-else chain
        _, cond_v = self.lower_expr(node.condition)
        bb_merge = self._new_bb()
        elifs = getattr(node, 'elifs', None) or []
        has_else = bool(node.else_body)
        # First branch
        if elifs or has_else:
            bb_false = self._new_bb()
        else:
            bb_false = bb_merge
        bb_true = self._new_bb()
        self._emit(f"  if ({cond_v}) goto {bb_true}; else goto {bb_false};")
        self._emit_label(bb_true)
        for s in node.then_body:
            self.gen_stmt(s)
        self._emit(f"  goto {bb_merge};")
        # elif chains
        for elif_cond, elif_body in elifs:
            self._emit_label(bb_false)
            _, elif_cv = self.lower_expr(elif_cond)
            bb_elif_true = self._new_bb()
            if elifs.index((elif_cond, elif_body)) < len(elifs) - 1 or has_else:
                bb_false = self._new_bb()
            else:
                bb_false = bb_merge
            self._emit(f"  if ({elif_cv}) goto {bb_elif_true}; else goto {bb_false};")
            self._emit_label(bb_elif_true)
            for s in elif_body:
                self.gen_stmt(s)
            self._emit(f"  goto {bb_merge};")
        if has_else:
            self._emit_label(bb_false)
            for s in node.else_body:
                self.gen_stmt(s)
            self._emit(f"  goto {bb_merge};")
        self._emit_label(bb_merge)

    def _gen_stmt_ComptimeVarStmt(self, node):
        # Comptime variables are compile-time only and don't generate runtime code
        return

    def _gen_stmt_GlobalStmt(self, node):
        # Mark each listed name as a module-level global so reads/writes in this
        # function route to the module struct (_modname_globals.x) rather than a local.
        for name in node.names:
            self._func_declared_globals.add(name)
            # Also seed var_types with the global's type for type-inference purposes,
            # but do NOT let it shadow the global-access path: _func_declared_globals
            # is checked before var_types in the IdentExpr read/write paths.
            if name in self._global_var_types and name not in self.var_types:
                self.var_types[name] = self._global_var_types[name]

    def _gen_stmt_ComptimeForStmt(self, node):
        unrolled = False
        if (isinstance(node.iterable, CallExpr) and
                isinstance(node.iterable.func, IdentExpr) and
                node.iterable.func.name == 'range'):
            args = node.iterable.args
            ivals = [self._eval_const_int(a) for a in args]
            if len(ivals) == 1 and ivals[0] is not None:
                start, stop, step = 0, ivals[0], 1
                unrolled = True
            elif len(ivals) == 2 and all(v is not None for v in ivals):
                start, stop, step = ivals[0], ivals[1], 1
                unrolled = True
            elif len(ivals) == 3 and all(v is not None for v in ivals):
                start, stop, step = ivals[0], ivals[1], ivals[2]
                unrolled = True
            if unrolled and step != 0:
                if node.target not in self.var_types:
                    self._declare_var(node.target, 'int64_t')
                i = start
                while (step > 0 and i < stop) or (step < 0 and i > stop):
                    self._emit(f"  {node.target} = {i};")
                    for s in node.body:
                        self.gen_stmt(s)
                    i += step
                return
        if not unrolled:
            # Skip emitting comment to avoid GIMPLE global-passing issues
            pass

    # ── for-range lowering ────────────────────────────────────────────────

    def _gen_for_range(self, node: ForStmt):
        args = node.iterable.args
        var  = node.target

        dynamic_step = False
        if len(args) == 1:
            start_expr, stop_expr, step_expr = IntLiteral(0), args[0], IntLiteral(1)
            cond_op = '<'
        elif len(args) == 2:
            start_expr, stop_expr, step_expr = args[0], args[1], IntLiteral(1)
            cond_op = '<'
        elif len(args) == 3:
            start_expr, stop_expr, step_expr = args[0], args[1], args[2]
            if isinstance(step_expr, IntLiteral) and step_expr.value < 0:
                cond_op = '>'
            elif (isinstance(step_expr, UnaryOp) and step_expr.op == '-' and
                  isinstance(step_expr.operand, IntLiteral)):
                cond_op = '>'
            elif isinstance(step_expr, IntLiteral):
                cond_op = '<'
            else:
                cond_op = '<'; dynamic_step = True
        else:
            # Skip emitting comment to avoid GIMPLE global-passing issues
            return

        self._declare_var(var, 'int64_t')
        start_t, start_v = self.lower_expr(start_expr)
        stop_t, stop_v  = self.lower_expr(stop_expr)
        step_t, step_v  = self.lower_expr(step_expr)
        # Coerce start/stop/step to int64_t — GIMPLE requires same types in binary ops
        self._safe_coerce_emit(start_t, 'int64_t', start_v, var)
        if stop_t != 'int64_t':
            stop_tmp = self._new_temp('int64_t')
            self._safe_coerce_emit(stop_t, 'int64_t', stop_v, stop_tmp)
            stop_v = stop_tmp
        if step_t != 'int64_t':
            step_tmp = self._new_temp('int64_t')
            self._safe_coerce_emit(step_t, 'int64_t', step_v, step_tmp)
            step_v = step_tmp

        bb_cond  = self._new_bb()
        bb_body  = self._new_bb()
        bb_post  = self._new_bb()
        bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")

        self._emit_label(bb_cond)
        if dynamic_step:
            t_lt   = self._new_temp('_Bool')
            t_gt   = self._new_temp('_Bool')
            t_spos = self._new_temp('_Bool')
            cond_t = self._new_temp('_Bool')
            self._emit(f"  {t_lt}   = {var} < {stop_v};")
            self._emit(f"  {t_gt}   = {var} > {stop_v};")
            t_zero = self._new_val('int64_t', "(int64_t)0")
            self._emit(f"  {t_spos} = {step_v} > {t_zero};")
            self._emit(f"  {cond_t} = {t_spos} ? {t_lt} : {t_gt};")
        else:
            cond_t = self._new_val('_Bool', f"{var} {cond_op} {stop_v}")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        self.loop_stack.append((bb_post, bb_after))
        for s in node.body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")

        self._emit_label(bb_post)
        step_t = self._new_val('int64_t', f"{var} + {step_v}")
        self._emit(f"  {var} = {step_t};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    # ── for-iter lowering (non-range) ─────────────────────────────────────

    def _get_actual_type(self, ctype: str, val: str) -> str:
        """Get actual type, checking _actual_types for int64_t-stored pointers."""
        if ctype == 'int64_t' and val in self._actual_types:
            return self._actual_types[val]
        if val in self.var_types and self.var_types[val] == 'int64_t' and val in self._actual_types:
            return self._actual_types[val]
        return ctype

    def _gen_for_iter(self, node: ForStmt):
        it_type, it_val = self.lower_expr(node.iterable)
        var = node.target if isinstance(node.target, str) else node.target.name

        # Check if this is an int64_t-stored pointer (from method call returning pointer)
        it_type = self._get_actual_type(it_type, it_val)

        if it_type == 'MojoList *':
            self._gen_for_list(var, it_val, node.body)
        elif it_type == 'MojoStr *':
            self._gen_for_str(var, it_val, node.body)
        elif it_type == 'MojoDict *':
            self._gen_for_dict(var, it_val, node.body)
        elif it_type == 'MojoSet *':
            self._gen_for_set(var, it_val, node.body)
        elif it_type.endswith(' *') or it_type.endswith('*'):
            # User-defined struct: try __iter__ / __has_next__ / __next__ protocol
            base = _struct_name_of(it_type)
            has_next = f"{base}___has_next__"
            nxt      = f"{base}___next__"
            if has_next in self.func_return_types or nxt in self.func_return_types:
                self._gen_for_struct_iter(var, it_type, it_val, node.body)
            else:
                _debug_note('for loop dropped (no iterator protocol)', it_type)
                self._emit(f"  /* TODO: for loop over {it_type} (no iterator protocol) */")
        else:
            _debug_note('for loop dropped (unsupported iterable)', it_type)
            self._emit(f"  /* TODO: for loop over {it_type} */")

    @staticmethod
    def _split_top_level_comma(s: str) -> list[str]:
        """Split s by top-level commas only (bracket-aware)."""
        parts, depth, start = [], 0, 0
        for i, c in enumerate(s):
            if c in '([': depth += 1
            elif c in ')]': depth -= 1
            elif c == ',' and depth == 0:
                parts.append(s[start:i].strip())
                start = i + 1
        parts.append(s[start:].strip())
        return parts

    def _gen_for_enumerate(self, node):
        """Handle: for (idx, val) in enumerate(lst): ..."""
        lst_arg = node.iterable.args[0]
        lst_type, lst_val = self.lower_expr(lst_arg)
        lst_type = self._get_actual_type(lst_type, lst_val)

        target = node.target
        if isinstance(target, str) and target.startswith('(') and target.endswith(')'):
            # Use bracket-aware split to handle nested tuples like (i, (a, b, c))
            parts = self._split_top_level_comma(target[1:-1])
        elif isinstance(target, str):
            parts = [target, '_enum_val']
        else:
            self._emit(f"  /* TODO: enumerate non-string target */")
            return

        idx_var = parts[0] if len(parts) >= 1 else '_enum_i'
        raw_val = parts[1] if len(parts) >= 2 else '_enum_val'

        # If the value part is itself a tuple like (a, b, c), use a temp for the element
        val_is_tuple = (isinstance(raw_val, str) and
                        raw_val.startswith('(') and raw_val.endswith(')'))
        val_var = self._new_temp('int64_t') if val_is_tuple else raw_val

        # Ensure underlying list
        if lst_type == 'MojoList *':
            list_ptr = lst_val
            if lst_val in self.var_types and self.var_types[lst_val] == 'int64_t':
                list_ptr = self._new_val('MojoList *', f"(MojoList *){lst_val}")
        else:
            list_ptr = self._new_val('MojoList *', f"(MojoList *){lst_val}")

        elem = self._elem_of(list_ptr)
        self._declare_var(idx_var, 'int64_t')
        if not val_is_tuple:
            self._declare_var(val_var, elem if elem else 'int64_t')

        len64 = self._new_temp('int64_t')
        len_t = self._new_temp('int64_t')
        idx_t = self._new_temp('int64_t')
        self._emit(f"  {len64} = mojo_list_len ({list_ptr});")
        self._emit(f"  {len_t} = {len64};")
        self._emit(f"  {idx_t} = (int64_t)0;")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_val('_Bool', f"{idx_t} < {len_t}")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        self.loop_stack.append((bb_post, bb_after))

        self._emit(f"  {idx_var} = {idx_t};")

        suf = TypeLattice.list_suffix(elem) if elem else 'int'
        if val_is_tuple:
            # Get element as opaque int64_t for tuple unpacking below
            elem64 = self._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
            self._emit(f"  {val_var} = {elem64};")
            # Emit tuple unpacking: (a, b, c) = val_var
            inner = raw_val[1:-1].strip()
            tuple_vars = self._split_top_level_comma(inner)
            tuple_ptr = self._new_val('MojoList *', f"(MojoList *){val_var}")
            for vi, vname in enumerate(tuple_vars):
                if vname == '_':
                    continue
                self._declare_var(vname, 'int64_t')
                ti = self._new_val('int64_t', f"mojo_list_get_int ({tuple_ptr}, {vi})")
                self._emit(f"  {vname} = {ti};")
        elif suf == 'double':
            self._emit(f"  {val_var} = mojo_list_get_double ({list_ptr}, {idx_t});")
        elif suf == 'str':
            temp_str = self._new_val('char *', f"mojo_list_get_str ({list_ptr}, {idx_t})")
            if self._type_of(val_var) == 'char *':
                self._emit(f"  {val_var} = {temp_str};")
            else:
                int_ptr = self._new_val('int64_t', f"(int64_t){temp_str}")
                self._emit(f"  {val_var} = {int_ptr};")
        else:
            elem64 = self._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
            vt = self._type_of(val_var)
            if vt and vt != 'int64_t':
                self._safe_coerce_emit('int64_t', vt, elem64, val_var)
            else:
                self._emit(f"  {val_var} = {elem64};")

        for s in node.body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1

        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        one = self._new_val('int64_t', "(int64_t)1")
        st = self._new_val('int64_t', f"{idx_t} + {one}")
        self._emit(f"  {idx_t} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _gen_for_list(self, var: str, it_val: str, body: list):
        # Handle tuple unpacking: for (a, b) in list_of_tuples:
        is_tuple = var.startswith('(') and var.endswith(')')
        elem = None if is_tuple else self._elem_of(it_val)
        if is_tuple:
            inner = var[1:-1].strip()
            var_names = [v.strip() for v in inner.split(',')]
            for vn in var_names:
                self._declare_var(vn, 'int64_t')
        else:
            var_names = None
            self._declare_var(var, elem)
        len64 = self._new_temp('int64_t')
        len_t = self._new_temp('int64_t')
        idx_t = self._new_temp('int64_t')
        # Cast it_val back to MojoList* if it's stored as int64_t (from method call)
        list_ptr = it_val
        if it_val in self.var_types and self.var_types[it_val] == 'int64_t':
            list_ptr = self._new_val('MojoList *', f"(MojoList *){it_val}")
        self._emit(f"  {len64} = mojo_list_len ({list_ptr});")
        self._emit(f"  {len_t} = {len64};")
        self._emit(f"  {idx_t} = (int64_t)0;")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_val('_Bool', f"{idx_t} < {len_t}")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        if is_tuple:
            elem64 = self._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
            tuple_ptr = self._new_val('MojoList *', f"(MojoList *){elem64}")
            for i, vn in enumerate(var_names):
                # mojo_list_get_str returns char*, but var is int64_t
                temp_str = self._new_val('char *', f"mojo_list_get_str ({tuple_ptr}, {i})")
                int_ptr = self._new_val('int64_t', f"(int64_t){temp_str}")
                self._emit(f"  {vn} = {int_ptr};")
        else:
            suf = TypeLattice.list_suffix(elem)
            if suf == 'double':
                self._emit(f"  {var} = mojo_list_get_double ({list_ptr}, {idx_t});")
            elif suf == 'str':
                # mojo_list_get_str returns char*, but var might be int64_t
                # Use a temp to handle the conversion
                temp_str = self._new_val('char *', f"mojo_list_get_str ({list_ptr}, {idx_t})")
                # If var is int64_t, cast the char* to it; otherwise assign directly
                if self._type_of(var) == 'char *':
                    self._emit(f"  {var} = {temp_str};")
                else:
                    # Cast char* to int64_t (opaque pointer storage)
                    int_ptr = self._new_val('int64_t', f"(int64_t){temp_str}")
                    self._emit(f"  {var} = {int_ptr};")
            else:
                elem64 = self._new_val('int64_t', f"mojo_list_get_int ({list_ptr}, {idx_t})")
                var_type = self._type_of(var)
                if var_type != 'int64_t':
                    self._safe_coerce_emit('int64_t', var_type, elem64, var)
                else:
                    self._emit(f"  {var} = ({elem}) {elem64};")
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        one = self._new_val('int64_t', "(int64_t)1")
        st = self._new_val('int64_t', f"{idx_t} + {one}")
        self._emit(f"  {idx_t} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _gen_for_str(self, var: str, it_val: str, body: list):
        self._declare_var(var, 'char')
        len64 = self._new_temp('int64_t')
        len_t = self._new_temp('int64_t')
        idx_t = self._new_temp('int64_t')
        self._emit(f"  {len64} = mojo_str_len ({it_val});")
        self._emit(f"  {len_t} = {len64};")
        self._emit(f"  {idx_t} = (int64_t)0;")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_val('_Bool', f"{idx_t} < {len_t}")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        self._emit(f"  {var} = mojo_str_char_at ({it_val}, {idx_t});")
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        one = self._new_val('int64_t', "(int64_t)1")
        st = self._new_val('int64_t', f"{idx_t} + {one}")
        self._emit(f"  {idx_t} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _gen_for_dict(self, var: str, it_val: str, body: list):
        """for k in dict — iterates over keys as char *."""
        # Handle tuple target like '(name, alias)' — declare each name separately
        is_tuple = var.startswith('(') and var.endswith(')')
        if is_tuple:
            inner = var[1:-1].strip()
            var_names = [v.strip() for v in inner.split(',')]
            for vn in var_names:
                self._declare_var(vn, 'char *')
        else:
            self._declare_var(var, 'char *')
        # If it_val is int64_t (boxed pointer), cast to MojoDict *
        if it_val in self.var_types and self.var_types[it_val] == 'int64_t':
            dict_ptr = self._new_val('MojoDict *', f"(MojoDict *){it_val}")
            it_val = dict_ptr
        iter_t = self._new_temp('MojoDictIter *')
        more_t = self._new_temp('int')
        self._emit(f"  {iter_t} = mojo_dict_iter_new ({it_val});")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        self._emit(f"  {more_t} = mojo_dict_iter_next ({iter_t});")
        cond_t = self._new_val('_Bool', f"{more_t} != 0")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        key_tmp = self._new_val('const char *', f"mojo_dict_iter_key ({iter_t})")
        if is_tuple:
            # Assign key to first name, NULL (zero) to remaining names
            vn0 = var_names[0]
            vt0 = self.var_types.get(vn0, 'char *')
            if vt0 in ('int64_t', 'int', 'int32_t'):
                self._emit(f"  {vn0} = (int64_t)(uintptr_t) {key_tmp};")
            else:
                self._emit(f"  {vn0} = (char *) {key_tmp};")
            for vn in var_names[1:]:
                vt = self.var_types.get(vn, 'char *')
                if vt in ('int64_t', 'int', 'int32_t'):
                    self._emit(f"  {vn} = (int64_t)0;")
                else:
                    self._emit(f"  {vn} = (char *)0;")
        else:
            vt = self.var_types.get(var, 'char *')
            if vt in ('int64_t', 'int', 'int32_t'):
                self._emit(f"  {var} = (int64_t)(uintptr_t) {key_tmp};")
            else:
                self._emit(f"  {var} = (char *) {key_tmp};")
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)
        self._emit(f"  mojo_dict_iter_free ({iter_t});")

    def _gen_for_set(self, var: str, it_val: str, body: list):
        """for x in set — iterates over int64_t values (int set assumed)."""
        self._declare_var(var, 'int64_t')
        # If it_val is int64_t (boxed pointer), cast to MojoSet * (matches dict path)
        if it_val in self.var_types and self.var_types[it_val] == 'int64_t':
            set_ptr = self._new_val('MojoSet *', f"(MojoSet *){it_val}")
            it_val = set_ptr
        iter_t = self._new_temp('MojoSetIter *')
        more_t = self._new_temp('int')
        self._emit(f"  {iter_t} = mojo_set_iter_new ({it_val});")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        self._emit(f"  {more_t} = mojo_set_iter_next ({iter_t});")
        cond_t = self._new_val('_Bool', f"{more_t} != 0")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        self._emit(f"  {var} = mojo_set_iter_val_int ({iter_t});")
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)
        self._emit(f"  mojo_set_iter_free ({iter_t});")

    # ── Function generation ───────────────────────────────────────────────

    # ── Closure lifting ───────────────────────────────────────────────────

    def _gen_lifted_closure(self, ci: ClosureInfo) -> str:
        """Generate a top-level C function for a nested (closure) function."""
        self._reset_func()
        self.current_func_name = ci.lifted_name
        self._captures  = dict(ci.captures)
        self._env_param = '_env' if ci.env_struct else ''
        self._inner_func_name = ci.inner_def.name  # original name for recursive call detection

        node = ci.inner_def
        # Infer parameter types from usage before seeding var_types
        inferred_params = self._infer_param_types(node)
        for pname, ptype in node.params:
            if ptype is None and pname in inferred_params:
                self.var_types[pname] = inferred_params[pname]
            else:
                self.var_types[pname] = self._resolve_type(ptype)

        # Seed captured variables into var_types so that calls to captured
        # function-pointer parameters (e.g. cmp_fn captured from outer scope)
        # are recognised by the indirect-call guard in _lower_call.  The
        # actual value is read via _env->name in _lower_IdentExpr, but the
        # type must be visible here so the call-site path is taken.
        for cap_name, cap_type in ci.captures:
            if cap_name not in self.var_types:
                self.var_types[cap_name] = cap_type

        # re.sub callbacks: force match param to char * and return type to char *
        if ci.is_re_sub_callback and node.params:
            match_param = node.params[0][0]
            self.var_types[match_param] = 'char *'

        if node.return_type is not None:
            ret_type = self._resolve_type(node.return_type)
        else:
            ret_type = self._infer_return_type(node.body)
        if ci.is_re_sub_callback:
            ret_type = 'char *'
        self.func_ret_type = ret_type

        # Build parameter list (env pointer first, then actual params)
        param_strs = []
        if ci.env_struct:
            param_strs.append(f"{ci.env_struct} * _env")
        ci.inferred_params = {}
        seen_varargs = False
        for i, (pname, ptype) in enumerate(node.params):
            # Strip Mojo parameter modifiers (inout, borrowed, etc.)
            bare = _strip_mojo_param_modifiers(pname.lstrip('*'))
            if pname.startswith('**'):
                # **kwargs -> a real MojoDict* param (forwarding pattern)
                ctype = 'MojoDict *'
                self.var_types[bare] = ctype
                ci.inferred_params[pname] = ctype
                param_strs.append(f"{ctype} {bare}")
                continue
            if pname.startswith('*'):
                # *args -> one MojoList* param; callers pack the loose args into it
                if seen_varargs:
                    continue
                seen_varargs = True
                ctype = 'MojoList *'
                self.var_types[bare] = ctype
                ci.inferred_params[pname] = ctype
                param_strs.append(f"{ctype} {bare}")
                continue
            if ci.is_re_sub_callback and i == 0:
                # First (match) param is always char * for re.sub callbacks
                ctype = 'char *'
            elif ptype is None and pname in inferred_params:
                ctype = inferred_params[pname]
            else:
                ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype
            ci.inferred_params[pname] = ctype   # cache for forward decl in Phase 2b
            # Rename C keywords used as parameter names (e.g. 'default', 'asm')
            safe_bare = self._cname(bare)
            if bare in _C_KEYWORDS or bare in _C_PARAM_EXTRA_KEYWORDS:
                safe_bare = f'_kw_{bare}'
                self._c_names[bare] = safe_bare
                self.var_types[bare] = ctype
            param_strs.append(f"{ctype} {safe_bare}")
        ci.inferred_ret = ret_type               # cache for forward decl in Phase 2b
        # Update func_return_types so callers generated after this closure see the right type
        self.func_return_types[ci.lifted_name] = ret_type
        # Register param types so _emit_call can coerce/pack arguments at closure call
        # sites. Keep the usage-inferred type for normal params; for *args use the '...'
        # packing sentinel (or a concrete MojoList* when **kwargs is also present), and
        # **kwargs -> MojoDict*, matching the emitted params above.
        closure_param_ctypes = []
        if ci.env_struct:
            closure_param_ctypes.append(f"{ci.env_struct} *")
        _has_kw = any(pn.startswith('**') for pn, _ in node.params)
        for pname, _ in node.params:
            if pname.startswith('**'):
                closure_param_ctypes.append('MojoDict *')
            elif pname.startswith('*'):
                closure_param_ctypes.append('MojoList *' if _has_kw else '...')
                if not _has_kw:
                    break
            else:
                closure_param_ctypes.append(ci.inferred_params.get(pname, 'int64_t'))
        self.func_param_types[ci.lifted_name] = closure_param_ctypes
        params_str = ', '.join(param_strs) if param_strs else 'void'

        self._emit_label("bb_2")
        for stmt in node.body:
            self.gen_stmt(stmt)

        lines = [
            f"{ret_type} __GIMPLE {ci.lifted_name} ({params_str})",
            "{",
            *self.decls,
            *self.body_lines,
            "}",
        ]
        self._captures  = {}
        self._env_param = ''
        return '\n'.join(lines)

    # ── Struct iterator protocol (for x in obj where obj has __iter__) ────

    def _gen_for_struct_iter(self, var: str, struct_type: str,
                              obj_val: str, body: list):
        """for x in obj — dispatches via StructName___iter__ / __has_next__ / __next__."""
        base = _struct_name_of(struct_type)

        # Determine iterator type (may be the same struct or a separate iter type)
        iter_fn = f"{base}___iter__"
        if iter_fn in self.func_return_types:
            iter_type = self.func_return_types[iter_fn]
            iter_var  = self._new_temp(iter_type)
            self._emit(f"  {iter_var} = {iter_fn} ({obj_val});")
            iter_base = _struct_name_of(iter_type)
        else:
            iter_type = struct_type
            iter_var  = obj_val
            iter_base = base

        has_next_fn = f"{iter_base}___has_next__"
        next_fn     = f"{iter_base}___next__"
        elem_type   = self.func_return_types.get(next_fn, 'int64_t')
        self._declare_var(var, elem_type)

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")

        self._emit_label(bb_cond)
        if has_next_fn in self.func_return_types:
            hn_t   = self._new_temp('int')
            cond_t = self._new_temp('_Bool')
            self._emit(f"  {hn_t} = {has_next_fn} ({iter_var});")
            self._emit(f"  {cond_t} = {hn_t} != 0;")
        else:
            _debug_note('iterator loop emitted with false condition (no __has_next__)', iter_base)
            cond_t = self._new_temp('_Bool')
            self._emit(f"  {cond_t} = 0;  /* TODO: no __has_next__ on {iter_base} */")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        if next_fn in self.func_return_types:
            nxt = self._new_val(elem_type, f"{next_fn} ({iter_var})")
            self._emit(f"  {var} = {nxt};")
        else:
            _debug_note('iterator loop body has no __next__', iter_base)
            self._emit(f"  /* TODO: no __next__ on {iter_base} */")
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _signature_ctypes(self, params, node, self_struct=None, sentinel='...') -> list:
        """C param-type list for a function/method.
        - **kwargs -> 'MojoDict *' (a real trailing parameter).
        - *args     -> 'MojoList *' when the function ALSO has **kwargs (the
          forwarding pattern f(self, *args, **kwargs): the parser flattens the
          call's spreads, so the caller passes the list/dict directly -> concrete
          params, no packing). Otherwise the packing `sentinel` ('...' for
          func_param_types, 'MojoList *' for emitted declarations), and the rest
          collapse into it.
        """
        has_kw = any(pn.startswith('**') for pn, _ in (params or []))
        out = []
        seen_vararg = False
        for i, (pn, pt) in enumerate(params or []):
            if pn.startswith('**'):
                out.append('MojoDict *')
            elif pn.startswith('*'):
                if has_kw:
                    out.append('MojoList *')      # pass-through: concrete list param
                elif not seen_vararg:
                    out.append(sentinel)          # packing convention
                    seen_vararg = True
                # After *args, continue to catch any trailing `out` params that also
                # appear in the definition and must match the forward declaration.
            elif i == 0 and pn == 'self' and self_struct:
                out.append(f"{self_struct} *")
            else:
                out.append(self._param_ctype(pn, pt, node))
        return out

    def _fixed_param_ctypes(self, params, node, self_struct=None) -> list:
        """C types of the parameters that precede the first *-param, for a
        function with *args. The varargs are packed into a single trailing
        MojoList* by the caller; **kwargs is not a positional parameter. Callers
        append the '...' sentinel (func_param_types) or 'MojoList *' (signatures).
        Including these fixed params is essential: e.g. __call__(self, interpreter,
        *args) must keep `interpreter`, or the forward decl and definition disagree
        on arity."""
        out = []
        for i, (pn, pt) in enumerate(params or []):
            if pn.startswith('*'):
                break
            if i == 0 and pn == 'self' and self_struct:
                out.append(f"{self_struct} *")
            else:
                out.append(self._param_ctype(pn, pt, node))
        return out

    def _param_ctype(self, pname: str, ptype, node: FunctionDef,
                     is_self: bool = False) -> str:
        """Resolve parameter C type, applying argument convention qualifiers."""
        if is_self:
            return f"{node.name} *"
        # Check inferred parameter types first (for unannotated parameters)
        if ptype is None and hasattr(self, '_inferred_param_types'):
            func_key: str
            func_key = node.name
            if func_key in self._inferred_param_types and pname in self._inferred_param_types[func_key]:
                ctype = self._inferred_param_types[func_key][pname]
            else:
                ctype = self._resolve_type(ptype)
        else:
            ctype = self._resolve_type(ptype)
        conv  = (getattr(node, 'param_convs', {}) or {}).get(pname)
        if conv in ('read', 'ref') and TypeLattice.is_pointer(ctype):
            # Immutable borrow of a pointer arg → const T *
            # Only add const if not already present
            if not ctype.startswith('const '):
                ctype = 'const ' + ctype
        return ctype

    # Entry points, the toplevel initializer, and the bootstrap/self-host ABI
    # functions keep fixed C names (they are referenced by fixed name from
    # hardcoded preamble decls and external harnesses).
    _NO_OVERLOAD_MANGLE = frozenset({
        'main', '_toplevel', '_gimple_main', '_lib_main',
        'compile_to_gimple', 'gimple_codegen_compile_to_gimple', 'tokenize',
        'int_write', 'int_parse_module', 'jit_compile_and_execute', 'mojo_print',
    })

    @staticmethod
    def overload_suffix_for(c_param_types) -> str:
        """A short stable suffix from a function's C parameter-type list. Shared by
        the codegen and reflect (reflect.func_overload_suffix) so both agree."""
        if not c_param_types or any('...' in p for p in c_param_types):
            return ''
        h = hashlib.md5(','.join(c_param_types).encode(), usedforsecurity=False).hexdigest()[:6]
        return f'_{h}'

    def _overload_suffix(self, bare_name: str) -> str:
        return self.overload_suffix_for(self.func_param_types.get(bare_name))

    def _func_mangleable(self, name: str) -> bool:
        """Whether a free function's C symbol is overload-mangled. True for a local
        user def (in _mangled_funcs) or an imported Mojo function (a concrete
        function export with a signature). False for entry points, struct types,
        and C stdlib symbols, whose names are fixed."""
        if (name in self._NO_OVERLOAD_MANGLE
                or name in self._extra_no_mangle
                or name in self.struct_field_types):
            return False
        # A local user def is authoritative — mangle it even if it shares a name
        # with a libc symbol (e.g. `abs` overloaded in math vs complex: both rename
        # to mojo_abs and would otherwise collide at link).
        if name in self._mangled_funcs:
            return True
        if name in self._LIBC_DECLARED:
            return False
        info = self.imported_symbols.get(name)
        return bool(info and 'signature' in info and info.get('kind') != 3)

    def _func_csym(self, bare_name: str) -> str:
        """The C symbol for a free function: _safe_name + overload suffix when the
        function is a user/imported Mojo function eligible for mangling. Used at the
        definition, every forward declaration, and every call site so they agree."""
        base = _safe_name(bare_name)
        if not self._func_mangleable(bare_name):
            return base
        mangled = base + self._overload_suffix(bare_name)
        # Mirror the param/return types under the mangled key so _emit_call's
        # argument coercion and return typing (keyed by the emitted name) still
        # work — func_param_types/func_return_types are keyed by the bare name.
        if mangled != base:
            if bare_name in self.func_param_types:
                self.func_param_types.setdefault(mangled, self.func_param_types[bare_name])
            if bare_name in self.func_return_types:
                self.func_return_types.setdefault(mangled, self.func_return_types[bare_name])
        return mangled

    def gen_func(self, node: FunctionDef) -> str:
        self._reset_func()
        # Set module context for global field access
        self._current_module_ctx = self.module_name or "root"
        self.current_func_name = node.name

        # Seed param types into var_types BEFORE return-type inference so
        # _quick_type can resolve param names during the pre-pass. Unannotated
        # params use the inferred type (incl. cross-call scalar contract, e.g. a
        # double param), not the int64_t default, so return inference is right.
        for pname, ptype in node.params:
            bare = pname.lstrip('*')
            if pname.startswith('*'):
                ctype = 'MojoList *'
            elif ptype is None:
                ctype = (self._inferred_param_types.get(node.name, {}).get(pname)
                         or self._resolve_type(ptype))
            else:
                ctype = self._resolve_type(ptype)
            self.var_types[bare] = ctype

        # Seed the cross-call element-type contract for container params, so
        # param[i][j] reads the inner element with the right getter and return
        # inference sees the real scalar (must precede return-type inference).
        # (Iterate keys + index, not `for k, (e, ne) in .items()`: a nested tuple
        # for-target over .items() isn't lowered correctly when self-compiled.)
        _pe = getattr(self, '_param_elem_types', {}).get(node.name, {})
        for bare in _pe:
            e, ne = _pe[bare]
            if e:
                self._elem_types[bare] = e
                if ne:
                    self._nested_elem_types[bare] = ne
        # Seed local container element types too, so return inference can see
        # through nested subscripts on locals (e.g. `return bodies[0][0]` where
        # bodies is a local list-of-double-lists). Lowering re-derives the same.
        _loc_elem, _loc_nested = self._scan_container_elems(node.body)
        for v, e in _loc_elem.items():
            self._elem_types.setdefault(v, e)
        for v, ne in _loc_nested.items():
            self._nested_elem_types.setdefault(v, ne)

        # Determine return type: annotation takes priority; infer if absent.
        if node.return_type is not None:
            ret_type = self._resolve_type(node.return_type)
        else:
            ret_type = self._infer_return_type(node.body)
            # Special case: main() should return int, not void
            if node.name == 'main' and ret_type == 'void':
                ret_type = 'int64_t'

        self.func_ret_type = ret_type
        # Sync so forward declarations (Phase 2b) match Phase 2a inference
        self.func_return_types[node.name] = ret_type

        # Run layout solver for struct locals
        solver = LayoutSolver(self.struct_field_types)
        self._struct_layout = solver.solve(node.params, node.body)

        param_strs = []
        has_varargs = any(pname.startswith('*') for pname, _ in (node.params or []))
        seen_varargs = False
        for pname, ptype in node.params:
            bare = pname.lstrip('*')
            if pname.startswith('**'):
                # **kwargs: a real MojoDict* parameter (the forwarding pattern; the
                # caller passes the dict directly since the parser flattens **spreads)
                self.var_types[bare] = 'MojoDict *'
                param_strs.append(f"MojoDict * {bare}")
                continue
            if pname.startswith('*'):
                if seen_varargs:
                    continue  # only one MojoList* for all *args
                seen_varargs = True
                ctype = 'MojoList *'
            else:
                ctype = self._param_ctype(pname, ptype, node)
            safe_bare = f'_kw_{bare}' if bare in _C_KEYWORDS or bare in _C_PARAM_EXTRA_KEYWORDS else bare
            self.var_types[bare] = ctype
            if safe_bare != bare:
                self.var_types[safe_bare] = ctype
                self._c_names[bare] = safe_bare
            param_strs.append(f"{ctype} {safe_bare}")

        params_str = ', '.join(param_strs) if param_strs else 'void'
        # Record that this function takes varargs so call sites can pack args
        if has_varargs:
            self.func_param_types[node.name] = self._signature_ctypes(node.params, node)
        safe = self._func_csym(node.name)

        # For main (in main module only), call class-attr initializer first
        if node.name == 'main' and self.emit_struct_defs:
            self._emit('  _mojo_classattr_init ();')

        # Don't emit bb_2 label at function start - let statements flow directly
        for stmt in node.body:
            self.gen_stmt(stmt)

        # Add implicit return 0 for main if it returns int but has no explicit return
        if node.name == 'main' and ret_type == 'int' and not self.body_lines[-1:] == ['  return 0;']:
            # Check if last statement is a return
            if not (self.body_lines and self.body_lines[-1].strip().startswith('return')):
                self._emit('  return 0;')

        # For main function in root module, rename to _gimple_main and create wrapper
        # For main function in library module, rename to _{module}_main to avoid collision
        if node.name == 'main':
            if self.emit_entry_points:
                safe = '_gimple_main'
            else:
                # Sub-module's main: rename to avoid collision with root main()
                # Module name may contain dots (e.g. "test.builtin.foo") — replace with underscores
                _mod_id = self.module_name.replace('.', '_').replace('-', '_') if self.module_name else ''
                safe = f"_{_mod_id}_main" if _mod_id else '_lib_main'

        lines = [
            f"{ret_type} {safe} ({params_str})",
            "{",
            *self.decls,
            *self.body_lines,
            "}",
        ]

        # Generate C wrapper for main that optionally initializes Python (root module only)
        if node.name == 'main' and self.emit_entry_points:
            lines.append("")
            lines.append(f"int main (int argc, const char **argv) {{")
            lines.append(f"  mojo_set_argv(argc, argv);")
            lines.append(f"#if USE_PYTHON")
            lines.append(f"  Py_Initialize ();")
            lines.append(f"#endif")
            # Call sub-module toplevels first, then root's own _toplevel (if present)
            for sub_fn in self._sub_toplevels:
                lines.append(f"  {sub_fn} ();")
            # Only call root's _toplevel if root actually has top-level statements;
            # pre-scanned into _has_toplevel_code so we trim the call when empty.
            if getattr(self, '_has_toplevel_code', False):
                lines.append(f"  _toplevel ();")
            lines.append(f"  {ret_type} result = {safe} ();")
            lines.append(f"#if USE_PYTHON")
            lines.append(f"  Py_Finalize ();")
            lines.append(f"#endif")
            lines.append(f"  return result;")
            lines.append(f"}}")

        return '\n'.join(lines)

    def _gen_toplevel(self, toplevel_stmts: list) -> str:
        """Generate _toplevel() or _{module}_toplevel() function for top-level statements."""
        self._reset_func()
        # Set module context for global field access
        self._current_module_ctx = self.module_name or "root"
        # Choose function name based on whether this is the root module or a library module
        if self.emit_entry_points:
            fn_name = '_toplevel'
        else:
            fn_name = _module_toplevel_name(self.module_name)
        self.current_func_name = fn_name
        self.func_ret_type = 'void'
        self.func_return_types[fn_name] = 'void'

        # Generate code for each top-level statement
        for stmt in toplevel_stmts:
            self.gen_stmt(stmt)

        lines = [
            f"void {fn_name} (void)",
            "{",
            *self.decls,
            *self.body_lines,
            "}",
        ]

        return '\n'.join(lines)

    # ── Struct method generation ──────────────────────────────────────────

    def _imported_field_ctype(self, type_ann: str) -> str:
        """Resolve an imported struct field's type to C. Compile-time string types
        are char* here (they back string fields like emission_kind) even though the
        general resolver keeps them as opaque int64_t handles elsewhere."""
        if type_ann in ('StaticString', 'StringLiteral', 'StringSlice', 'StringRef', 'String'):
            return 'char *'
        return self._resolve_type(type_ann) if type_ann else 'int64_t'

    def _register_imported_structs(self, stmts) -> None:
        """dylib mode: register a concrete imported struct's field layout + queue
        its typedef, but ONLY for structs used as a parameter type AND whose field
        is actually accessed here (so e.g. `info: CompiledFunctionInfo` +
        `info.emission_kind` works). Tightly scoped to avoid disturbing the many
        imported structs a module merely passes through."""
        if self.do_imports or not getattr(self, '_current_filename', None):
            return
        try:
            src = open(self._current_filename).read()
        except Exception as e:
            _debug_note(f'cannot read {self._current_filename!r} for self-assign scan', e)
            return
        # struct base name -> set of parameter names with that type (so the field /
        # method checks below are specific to values actually of this struct, not a
        # coincidental `.field`/`.method(` on some other object).
        params_by_struct: dict = {}

        def _base(ann):
            return ann.split('[', 1)[0].split('.')[0].strip() if isinstance(ann, str) else ''

        def _collect(fn):
            for _pn, _pt in (getattr(fn, 'params', None) or []):
                b = _base(_pt)
                if b:
                    params_by_struct.setdefault(b, set()).add(
                        _strip_mojo_param_modifiers(_pn.lstrip('*')))
        for st in stmts:
            if isinstance(st, FunctionDef):
                _collect(st)
            elif isinstance(st, StructDef):
                for m in st.methods:
                    _collect(m)
        param_type_names = set(params_by_struct)

        for st in stmts:
            if not (isinstance(st, FromImportStmt) and not getattr(st, 'wildcard', False)):
                continue
            for nm, alias in st.names:
                local = alias or nm
                if (nm.startswith('_') or local in self.struct_field_types
                        or local in self._imported_generic_structs
                        or local not in param_type_names
                        # Collection-like types have a runtime representation
                        # (MojoDict*/MojoList*/…) and special method handling —
                        # registering them as plain structs breaks that.
                        or any(w in nm for w in ('Dict', 'List', 'Set', 'Array',
                                                 'Map', 'Kwargs', 'Tuple', 'Span',
                                                 'Optional', 'Pointer'))):
                    continue
                sdef = self._find_imported_struct(st.module, nm)
                if sdef is None:
                    continue
                fields = {f.name: self._imported_field_ctype(f.type_ann)
                          for f in sdef.fields if isinstance(f, VarDecl)}
                pnames = params_by_struct.get(nm, set())
                if not fields or not any(f"{pn}.{fn}" in src
                                         for pn in pnames for fn in fields):
                    continue  # no field of this struct is accessed on its params
                # Skip if a (non-trivial) method is CALLED on this struct anywhere —
                # typedef-only registration supplies no method body, so the
                # Struct_method symbol would be undefined. Common trait/dunder
                # methods are excluded: their names collide with calls on unrelated
                # objects, and they have generic handling rather than a hard symbol.
                _uncommon = [m.name for m in sdef.methods
                             if m.name not in _COMMON_METHOD_NAMES]
                if any(f".{mn}(" in src for mn in _uncommon):
                    continue
                self.struct_field_types[local] = fields
                self._imported_struct_names.add(local)
                self._imported_typedef_structs.append(
                    StructDef(name=local, fields=sdef.fields, methods=[]))

    def _find_imported_struct(self, module: str, name: str):
        """The StructDef for `name` defined directly in `module`'s source, or None."""
        _path, _src, mod = self._parsed_import(module)
        if mod is None:
            return None
        for s in mod:
            if isinstance(s, StructDef) and s.name == name:
                return s
        return None

    def _parsed_import(self, module: str):
        """(path, source_text, stmts) for an imported module, parsed once and
        cached. (None, '', None) on failure."""
        cache = self._imported_src_cache
        if module not in cache:
            try:
                import imports as _imp
                path = _imp.resolve_source(module)
                src = open(path).read() if path else ''
                cache[module] = (path, src,
                                 Parser(tokenize(src)).parse_module() if src else None)
            except Exception as e:
                _debug_note(f'cannot resolve/parse module {module!r}', e)
                cache[module] = (None, '', None)
        return cache[module]

    @staticmethod
    def _abs_module(ref: str, base: str) -> str:
        """Resolve a possibly-relative import ref against the base package:
        `.os` from `std.os` -> `std.os.os`; `..fstat` from `std.os.path` ->
        `std.os.fstat`. Absolute refs unchanged."""
        if not ref.startswith('.'):
            return ref
        dots = len(ref) - len(ref.lstrip('.'))
        leaf = ref[dots:]
        parts = base.split('.')
        keep = parts[:len(parts) - (dots - 1)] if dots > 1 else parts
        return '.'.join(keep + ([leaf] if leaf else []))

    def _find_generic_source(self, module: str, name: str, depth: int = 0):
        """Source path of the module that DEFINES generic free function `name`,
        reachable from `module` by following `from X import (...)` re-export hops
        (e.g. std.os re-exports listdir from .os = os.mojo). None if not generic."""
        if depth > 5 or not module:
            return None
        path, src, mod = self._parsed_import(module)
        if not src:
            return None
        if re.search(rf'\b(?:fn|def)\s+{re.escape(name)}\s*\[', src):
            return path
        nm = re.escape(name)
        for mm in re.finditer(r'from\s+([.\w]+)\s+import\s*\(([^)]*)\)', src):
            if re.search(rf'(?:^|[\s,(]){nm}(?:[\s,)]|$)', mm.group(2)):
                r = self._find_generic_source(self._abs_module(mm.group(1), module), name, depth + 1)
                if r:
                    return r
        for mm in re.finditer(r'from\s+([.\w]+)\s+import\s+([^\n(]+)', src):
            if re.search(rf'(?:^|[\s,]){nm}(?:[\s,]|$)', mm.group(2)):
                r = self._find_generic_source(self._abs_module(mm.group(1), module), name, depth + 1)
                if r:
                    return r
        return None

    def _register_imported_generics(self, stmts) -> None:
        """dylib mode: register `from M import gen` where gen is a generic free
        function (following re-export chains) so its call sites elaborate a
        concrete CAS-cached instantiation."""
        if self.do_imports:
            return
        for st in stmts:
            if not (isinstance(st, FromImportStmt) and not getattr(st, 'wildcard', False)):
                continue
            for nm, alias in st.names:
                local = alias or nm
                if (local in self._imported_generics or local in self.struct_field_types
                        or nm != local):   # aliased: elaborator looks up the source name
                    continue
                src = self._find_generic_source(st.module, nm)
                if src:
                    self._imported_generics.setdefault(local, src)

    def _struct_method_overload_ids(self, stmt) -> list:
        """Overload-id per method, aligned with stmt.methods. Must match the
        emission loop in gen_module so the method's C symbol, its closure-lookup
        key (current_func_name), and the pre-pass closure registration all agree.
        Empty string for a non-overloaded method."""
        counts = {}
        for m in stmt.methods:
            counts[m.name] = counts.get(m.name, 0) + 1
        used: dict = {}
        ids = []
        for m in stmt.methods:
            oid = ''
            if counts[m.name] > 1:
                oid = _method_overload_id(tuple(m.params or []), stmt.name, m.name)
                seen = used.setdefault(m.name, {})
                c = seen.get(oid, 0)
                seen[oid] = c + 1
                if c > 0:
                    oid = f"{oid}_{c + 1}"
            ids.append(oid)
        return ids

    def _gen_struct_method(self, struct_name: str, node: FunctionDef, overload_id: str = '') -> str:
        self._reset_func()
        # Key by overload so overloaded methods don't share closure state (each
        # overload's lifted closures + capture env are distinct).
        self.current_func_name = f"{struct_name}_{node.name}{overload_id}"
        self._current_struct_name = struct_name  # for Self() constructor call lowering

        # Seed param types for pre-pass inference
        for i, (pname, ptype) in enumerate(node.params):
            # Strip Mojo parameter modifiers (inout, borrowed, etc.)
            bare = _strip_mojo_param_modifiers(pname.lstrip('*'))
            if i == 0 and pname == 'self':
                self.var_types['self'] = f"{struct_name} *"
            elif pname.startswith('*'):
                self.var_types[bare] = 'MojoList *'
            else:
                self.var_types[bare] = self._resolve_type(ptype)

        if node.return_type is not None:
            ret_type = self._resolve_type(node.return_type)
        else:
            ret_type = self._infer_return_type(node.body)
            if ret_type == 'void':
                ret_type = 'void'

        self.func_ret_type = ret_type
        # Sync so forward declarations (Phase 2b) match Phase 2a inference.
        # Store BOTH the base name (for single-overload lookups) and the
        # per-overload keyed name (so multi-overload methods don't clobber each other).
        self.func_return_types[f"{struct_name}_{node.name}"] = ret_type
        if overload_id:
            self.func_return_types[f"{struct_name}_{node.name}{overload_id}"] = ret_type

        solver = LayoutSolver(self.struct_field_types)
        self._struct_layout = solver.solve(node.params, node.body)

        method_full_name = f"{struct_name}_{node.name}"
        has_varargs = any(pn.startswith('*') for pn, _ in (node.params or []))
        param_strs = []
        if has_varargs:
            # Keep self + any fixed params before *args, then pack the rest; e.g.
            # __call__(self, interpreter, *args) must keep `interpreter`.
            self.func_param_types[method_full_name] = self._signature_ctypes(node.params, node, struct_name)
        hardcoded_params = self.func_param_types.get(method_full_name, [])
        seen_varargs = False
        for i, (pname, ptype) in enumerate(node.params):
            # Strip Mojo parameter modifiers (inout, borrowed, etc.)
            bare = _strip_mojo_param_modifiers(pname.lstrip('*'))
            if i == 0 and pname == 'self':
                ctype = f"{struct_name} *"
            elif pname.startswith('**'):
                # **kwargs: a real MojoDict* parameter (forwarding pattern)
                self.var_types[bare] = 'MojoDict *'
                param_strs.append(f"MojoDict * {bare}")
                continue
            elif pname.startswith('*'):
                if seen_varargs:
                    continue
                seen_varargs = True
                ctype = 'MojoList *'
            elif ptype == 'Self':
                # A non-self parameter typed `Self` (e.g. the keyword copy ctor
                # `__init__(out self, *, copy: Self)`) is a pointer to this struct.
                ctype = f"{struct_name} *"
            elif ptype and ptype.split('[', 1)[0].split('.')[0].strip() in self._imported_struct_names:
                # An explicit imported-struct parameter (info: CompiledFunctionInfo)
                # is authoritative — use the struct pointer, not a type a sibling
                # overload clobbered onto the shared base key.
                ctype = f"{ptype.split('[', 1)[0].split('.')[0].strip()} *"
            elif (hardcoded_params and '...' not in hardcoded_params and i < len(hardcoded_params)
                  and not (i == 0 and pname != 'self'
                           and hardcoded_params[i] == f"{struct_name} *")):
                # The guard skips a self-pointer leaked onto a non-self first param
                # from a sibling instance overload sharing this method's base key
                # (e.g. static fetch_add(ptr) vs instance fetch_add(self) on Atomic).
                ctype = hardcoded_params[i]
            else:
                if ptype is None and hasattr(self, '_inferred_param_types'):
                    if method_full_name in self._inferred_param_types and bare in self._inferred_param_types[method_full_name]:
                        ctype = self._inferred_param_types[method_full_name][bare]
                    else:
                        ctype = self._resolve_type(ptype)
                else:
                    ctype = self._param_ctype(pname, ptype, node)
            self.var_types[bare] = ctype
            safe_bare = f'_kw_{bare}' if bare in _C_KEYWORDS or bare in _C_PARAM_EXTRA_KEYWORDS else bare
            if safe_bare != bare:
                self._c_names[bare] = safe_bare
                self.var_types[safe_bare] = ctype
            param_strs.append(f"{ctype} {safe_bare}")

        params_str = ', '.join(param_strs) if param_strs else 'void'
        mangled    = f"{struct_name}_{_safe_name(node.name)}{overload_id}"

        self._emit_label("bb_2")
        for stmt in node.body:
            self.gen_stmt(stmt)

        # Store per-overload param types so forward declarations can match definitions exactly
        param_ctypes_only = [s.rsplit(' ', 1)[0].strip() for s in param_strs]
        self.func_param_types[mangled] = param_ctypes_only

        lines = [
            f"{ret_type} __GIMPLE {mangled} ({params_str})",
            "{",
            *self.decls,
            *self.body_lines,
            "}",
        ]
        return '\n'.join(lines)

    # ── Module generation ─────────────────────────────────────────────────

    def gen_module(self, stmts: list) -> str:
        # Overloaded top-level functions (same name, multiple defs) can't be
        # emitted as distinct C symbols. Drop them here — the elaborator selects
        # and instantiates the right overload per call site (slice 4). One filter
        # at the top keeps every downstream loop collision-free. No-op otherwise.
        _fn_counts = {}
        for _s in stmts:
            if isinstance(_s, FunctionDef):
                _fn_counts[_s.name] = _fn_counts.get(_s.name, 0) + 1
        _overloaded = {n for n, c in _fn_counts.items() if c > 1}
        if _overloaded:
            stmts = [s for s in stmts
                     if not (isinstance(s, FunctionDef) and s.name in _overloaded)]

        # Local generic free functions: the parser drops the `[T]` type params, so
        # detect them from the source text. Register each (with this module's own
        # source) so call sites elaborate a concrete CAS-cached instantiation
        # (id[Int64] → id_Int64), and drop the erased template so it is neither
        # emitted as a type-erased body nor collides across modules.
        _gsrc = ''
        if getattr(self, '_current_filename', None):
            try:
                _gsrc = open(self._current_filename).read()
            except Exception as e:
                _debug_note(f'cannot read {self._current_filename!r} for generics scan', e)
                _gsrc = ''
        if _gsrc:
            _local_generics = {
                s.name for s in stmts
                if isinstance(s, FunctionDef)
                and s.name not in self._NO_OVERLOAD_MANGLE
                and re.search(rf'\b(?:fn|def)\s+{re.escape(s.name)}\s*\[', _gsrc)
            }
            for _gn in _local_generics:
                self._imported_generics.setdefault(_gn, self._current_filename)
            if _local_generics:
                stmts = [s for s in stmts
                         if not (isinstance(s, FunctionDef) and s.name in _local_generics)]

        # Structs with a __call__ method: a variable of such a type invoked like a
        # function (obj(args)) routes to Struct___call__(obj, args).
        self._callable_structs = {
            s.name for s in stmts
            if isinstance(s, StructDef) and any(m.name == '__call__' for m in s.methods)
        }

        # Register concrete imported structs used (with field access) as param types.
        self._register_imported_structs(stmts)
        # Register imported generic free functions (via re-export chains) so their
        # calls elaborate a concrete CAS-cached instantiation.
        self._register_imported_generics(stmts)

        # Pre-register current module's own function names into _global_inline_defs
        # BEFORE Phase 0 so that recursive sub-module compilations see them.
        for _s in stmts:
            if isinstance(_s, FunctionDef):
                self._global_inline_defs.add(_s.name)
            elif isinstance(_s, StructDef):
                for _m in _s.methods:
                    self._global_inline_defs.add(_m.name)
                    self._global_inline_defs.add(f"{_s.name}_{_m.name}")
                # Struct-level comptime aliases (e.g. BitSet._words_size) expand
                # to their expression at member-access sites, not physical fields.
                _al = getattr(_s, 'comptime_aliases', None)
                if _al:
                    self._struct_comptime_aliases[_s.name] = _al

        # Link mode: register imported symbol signatures (return/param types) from
        # module_loader so call sites lower correctly; decls emitted in preamble.
        # No body inlining — bodies come from the linked artifact (ABI.md).
        self._link_import_decl_list = []
        if self.link_imports:
            self._link_import_decl_list = self._register_link_imports(stmts)

        # Lightweight stdlib import extern pass: scan from-imports and emit extern
        # declarations for concrete functions found via load_module (simple text
        # parser, no dylib builds). This resolves "implicit declaration" errors for
        # functions like `is_occupied` imported from other stdlib modules.
        self._link_import_decl_list = list(self._link_import_decl_list)
        self._emit_stdlib_import_externs(stmts)

        # ── Phase 0: Compile imported modules and extract their type info ────
        # Do this FIRST so imported function types are available for everything
        imported_code = []
        imported_stmts = []
        if self.do_imports:
            modules_to_compile = set()
            # Recursively scan for all imports (including in function bodies)
            def find_imports(node_list):
                for stmt in node_list:
                    if isinstance(stmt, FromImportStmt):
                        modules_to_compile.add(stmt.module)
                    elif isinstance(stmt, ImportStmt):
                        for _m, _a in ([(stmt.module, stmt.alias)]
                                       + list(getattr(stmt, 'extra', None) or [])):
                            modules_to_compile.add(_m)
                    elif isinstance(stmt, FunctionDef):
                        find_imports(stmt.body)
                    elif isinstance(stmt, IfStmt):
                        find_imports(stmt.then_body)
                        for _, elif_body in stmt.elifs:
                            find_imports(elif_body)
                        if stmt.else_body:
                            find_imports(stmt.else_body)
                    elif isinstance(stmt, (WhileStmt, ForStmt, TryStmt)):
                        find_imports(stmt.body)

            find_imports(stmts)

            # Compile imported modules to extract type information
            for module_name in sorted(modules_to_compile):
                if module_name not in self._compiled_modules:
                    self._compiled_modules.add(module_name)
                    code, module_stmts = self._compile_imported_module(module_name)
                    if code:
                        imported_code.append(f"/* ─── Imported module: {module_name} ───────────────────── */")
                        imported_code.append(code)
                        imported_code.append('')
                        imported_stmts.extend(module_stmts)
                        # Record all function names defined inline to suppress extern stubs
                        for _ms in module_stmts:
                            if isinstance(_ms, FunctionDef):
                                self._global_inline_defs.add(_ms.name)
                            elif isinstance(_ms, StructDef):
                                for _m in _ms.methods:
                                    self._global_inline_defs.add(_m.name)
                                    self._global_inline_defs.add(f"{_ms.name}_{_m.name}")
                    self._compiled_modules.add(module_name)

            # Also collect stmts from transitively compiled modules (compiled by sub-temp-gens).
            # These may not be in imported_stmts if a sub-gen compiled them first (e.g. mojo_compiler
            # compiled via gimple_codegen before the outer gen could compile it directly).
            already_in_stmts = set(id(s) for s in imported_stmts)
            for mod_name, mod_stmts in self._module_stmts.items():
                for s in mod_stmts:
                    if id(s) not in already_in_stmts:
                        imported_stmts.append(s)
                        already_in_stmts.add(id(s))

            # Imported types are now in self._imported_func_types and struct_field_types

        # ── Phase 1: build complete type tables (pre-pass) ────────────────

        # Register struct field types first so _resolve_type works for funcs
        # Include both current module and imported module structs
        # NOTE: do NOT clear struct_field_types here — it was already populated
        # by temp_gens during Phase 0 import compilation.  Clearing it would
        # lose structs from transitive imports (ModuleLoader, Layout, etc.)
        # that were added to the shared dict by nested temp_gens.

        # Span / StringSlice — fat pointer {data, len}. Seeded so .unsafe_ptr()
        # and .__len__()/len() lower to field reads even without walking span.mojo.
        self.struct_field_types['Span'] = {
            '_data': 'char *',
            '_len': 'int64_t',
        }
        # Pre-populate known interpreter structs with their field types
        # This handles cases where field type inference from method bodies fails
        self.struct_field_types['Scope'] = {
            'parent': 'Scope *',
            'vars': 'MojoDict *',
        }
        self.struct_field_types['Token'] = {
            'kind':  'char *',
            'value': 'char *',
            'line':  'int64_t',
            'col':   'int64_t',
        }
        self.struct_field_types['ReturnValue'] = {
            'value': 'int64_t',
        }
        self.struct_field_types['BreakException'] = {}
        self.struct_field_types['ContinueException'] = {}
        self.struct_field_types['MojoFunction'] = {
            'name': 'char *',
            'params': 'MojoList *',
            'body': 'MojoList *',
            'closure_scope': 'Scope *',
        }
        self.struct_field_types['MojoClass'] = {
            'name': 'char *',
            'body': 'MojoList *',
            'methods': 'MojoDict *',
        }
        self.struct_field_types['Interpreter'] = {
            'scope': 'Scope *',
            'filename': 'char *',
        }
        self.struct_field_types['Parser'] = {
            '_tok': 'MojoList *',
            '_pos': 'int64_t',
            '_pending_decs': 'MojoList *',
        }
        self.struct_field_types['Scope'] = {
            'parent': 'Scope *',
            'vars': 'MojoDict *',
        }

        # Hardcode Scope method param types so 'name' is char* not int
        self.func_param_types['Scope_define'] = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope_get']    = ['Scope *', 'char *']
        self.func_param_types['Scope_set']    = ['Scope *', 'char *', 'int']
        self.func_param_types['Scope___init__'] = ['Scope *', 'Scope *']

        # Pre-populate AST node struct fields
        self.struct_field_types['CallExpr'] = {
            'func': 'int64_t',
            'args': 'MojoList *',
        }
        self.struct_field_types['BinaryOp'] = {
            'op': 'char *',
            'left': 'int64_t',
            'right': 'int64_t',
        }
        self.struct_field_types['UnaryOp'] = {
            'op': 'char *',
            'operand': 'int64_t',
        }
        self.struct_field_types['TernaryExpr'] = {
            'condition': 'int64_t',
            'then_val': 'int64_t',
            'else_val': 'int64_t',
        }
        self.struct_field_types['MemberExpr'] = {
            'obj': 'int64_t',
            'member': 'char *',
        }
        self.struct_field_types['SubscriptExpr'] = {
            'obj': 'int64_t',
            'index': 'int64_t',
        }

        all_struct_defs = stmts + (imported_stmts if self.do_imports else [])
        # Pre-register all struct names so cross-references in _collect_self_assigns work
        # regardless of definition order (e.g. DispatchSolver before FunctionCompilability).
        for _s in all_struct_defs:
            if isinstance(_s, StructDef) and _s.name not in self.struct_field_types:
                self.struct_field_types[_s.name] = {}
        for s in all_struct_defs:
            if isinstance(s, StructDef):
                if s.name not in self.struct_field_types:
                    self.struct_field_types[s.name] = {}
                # For now, assume all struct fields on unknown types are pointers to the same struct
                # (e.g. Scope.parent is Scope*, Interpreter.scope is Scope*, etc.)
                # This is a heuristic to handle incomplete type information from imports
                for field in (s.fields if hasattr(s, 'fields') else []):
                    if isinstance(field, VarDecl) and field.name and field.name != 'self':
                        # For untyped fields, assume they're pointers to the containing struct
                        if not field.type_ann and field.name not in self.struct_field_types[s.name]:
                            self.struct_field_types[s.name][field.name] = s.name + ' *'
                # Collect class-level attributes (non-self, non-method assignments at class body)
                if not hasattr(self, '_class_attrs'):
                    self._class_attrs = {}  # class_name -> {attr -> value_str}
                self._class_attrs[s.name] = {}
                for field in s.fields:
                    if isinstance(field, AssignStmt):
                        if isinstance(field.target, IdentExpr):
                            aname = field.target.name
                            # Store a C-safe mangled name for this class attribute
                            mangled = f"_classattr_{s.name}__{aname}"
                            self._class_attrs[s.name][aname] = mangled
                            # Pre-populate _global_var_types so Phase 2a sees the correct type
                            v = field.value
                            if isinstance(v, SetExpr):
                                self._global_var_types[mangled] = 'MojoSet *'
                            elif isinstance(v, DictExpr):
                                self._global_var_types[mangled] = 'MojoDict *'
                            elif isinstance(v, (ListExpr, TupleExpr)):
                                self._global_var_types[mangled] = 'MojoList *'
                            elif isinstance(v, StringLiteral):
                                self._global_var_types[mangled] = 'char *'
                            elif isinstance(v, (IntLiteral, BoolLiteral)):
                                self._global_var_types[mangled] = 'int64_t'
                            else:
                                self._global_var_types[mangled] = 'int64_t'
                # Explicit field declarations
                for field in s.fields:
                    if isinstance(field, VarDecl):
                        # Don't overwrite hardcoded entries (e.g. BinaryOp.op)
                        if field.name not in self.struct_field_types[s.name]:
                            ft = _mojo_type(field.type_ann)
                            if field.name == 'value' and s.name == 'Generator':
                                ft = 'int'  # boxed object field
                            # If the type resolved to a generic container pointer (MojoList *,
                            # MojoDict *, MojoSet *, or double-pointer like MojoDict * *)
                            # but there is a locally-defined struct, prefer the local struct.
                            # Also handle Pointer[LocalStruct[...]] → LocalStruct *.
                            if field.type_ann:
                                _ann_str = str(field.type_ann)
                                # Extract the outermost base name (e.g. 'Pointer', 'Dict', 'List')
                                _outer_base = _ann_str.split('[')[0].strip()
                                _ptr_wrappers = ('UnsafePointer', 'OwnedPointer',
                                                 'ArcPointer', 'Pointer', 'Reference')
                                if _outer_base in _ptr_wrappers and '[' in _ann_str:
                                    # Pointer[InnerType[...], origin] — grab InnerType base
                                    _inner = _ann_str.split('[', 1)[1]
                                    _inner_base = _inner.split('[')[0].strip()
                                    if _inner_base in self.struct_field_types:
                                        # Pointer[LocalStruct[...]] → LocalStruct *
                                        ft = f'{_inner_base} *'
                                elif ft.endswith(' *') and _outer_base in self.struct_field_types:
                                    # Direct: List[T] → List * (override MojoList *)
                                    ft = f'{_outer_base} *'
                            self.struct_field_types[s.name][field.name] = ft

                # Always scan ALL methods for self.x = ... to build complete field list
                def _collect_self_assigns(body, param_types, found):
                    for stmt in body:
                        if isinstance(stmt, AssignStmt) and isinstance(stmt.target, MemberExpr):
                            t = stmt.target
                            if isinstance(t.obj, IdentExpr) and t.obj.name == 'self':
                                fn = t.member
                                if fn not in found:
                                    v = stmt.value
                                    if isinstance(v, IdentExpr):
                                        ft = param_types.get(v.name, 'int64_t')
                                    elif isinstance(v, IntLiteral):
                                        ft = 'int64_t'
                                    elif isinstance(v, StringLiteral):
                                        ft = 'char *'
                                    elif isinstance(v, BoolLiteral):
                                        ft = '_Bool'
                                    elif isinstance(v, DictExpr):
                                        ft = 'MojoDict *'
                                    elif isinstance(v, (ListExpr, TupleExpr)):
                                        ft = 'MojoList *'
                                    elif isinstance(v, SetExpr):
                                        ft = 'MojoSet *'
                                    elif isinstance(v, CallExpr):
                                        cfn = v.func
                                        cn = cfn.name if isinstance(cfn, IdentExpr) else ''
                                        if cn in ('list', 'DynamicVector', 'mojo_list_new'):
                                            ft = 'MojoList *'
                                        elif cn in ('dict', 'Dict', 'mojo_dict_new'):
                                            ft = 'MojoDict *'
                                        elif cn in ('set', 'Set', 'frozenset', 'mojo_set_new'):
                                            ft = 'MojoSet *'
                                        elif cn.startswith('_alloc_'):
                                            # _alloc_StructName() returns StructName *
                                            sname = cn[len('_alloc_'):]
                                            ft = sname + ' *'
                                        elif cn in self.struct_field_types:
                                            ft = cn + ' *'
                                        else:
                                            ft = 'int'
                                    else:
                                        ft = 'int'
                                    found[fn] = ft
                        for attr in ('then_body', 'body', 'else_body'):
                            sub = getattr(stmt, attr, None)
                            if isinstance(sub, list):
                                _collect_self_assigns(sub, param_types, found)

                already = set(self.struct_field_types[s.name].keys())
                for method in s.methods:
                    pm = {}
                    for pname, ptype in method.params:
                        if pname != 'self':
                            # Unannotated params hold object handles (pointer-width);
                            # default to int64_t so a field assigned from one isn't
                            # truncated to 32-bit int (size-mismatch cast on read).
                            pm[pname] = self._resolve_type(ptype) if ptype else 'int64_t'
                    new_fields = {}
                    _collect_self_assigns(method.body, pm, new_fields)
                    for fn, ft in new_fields.items():
                        # Don't overwrite annotation-based / hardcoded field types,
                        # annotations are the source of truth for struct field types.
                        # However, allow overriding 'int' (from = None / = 0) with a more
                        # specific pointer type discovered in a later method assignment.
                        existing_ft = self.struct_field_types[s.name].get(fn)
                        can_override = (existing_ft == 'int' and ft.endswith(' *'))
                        if fn not in self.struct_field_types[s.name] or can_override:
                            if ft == 'char *':
                                ft = 'int'  # struct fields use boxed runtime representation
                            self.struct_field_types[s.name][fn] = ft
                            if fn not in already:
                                s.fields.append(VarDecl(name=fn, type_ann=None, value=None))
                                already.add(fn)

        # Register struct constructors as functions returning T *
        # Include both current module and imported module structs
        # Preserve types registered by _emit_stdlib_import_externs (Phase 0 pre-pass) so
        # they survive the Phase 1 reset. _RUNTIME_FUNCS forms the base; Phase 0 types win.
        _phase0_func_types = dict(self.func_return_types)   # save Phase 0 registrations
        _phase0_imported   = dict(getattr(self, 'imported_symbols', {}))  # save Phase 0 imported_symbols
        self.func_return_types = dict(_RUNTIME_FUNCS)
        self.func_return_types.update(_phase0_func_types)   # Phase 0 types win over defaults
        all_struct_defs_for_types = stmts + (imported_stmts if self.do_imports else [])
        for s in all_struct_defs_for_types:
            if isinstance(s, StructDef):
                self.func_return_types[s.name] = f"{s.name} *"

        # Process imports: load modules and register imported symbols
        self.imported_symbols = dict(_phase0_imported)   # restore Phase 0 imported_symbols
        for s in stmts:
            if isinstance(s, FromImportStmt):
                try:
                    exports = load_module(s.module)
                    def _register_sym(sym_name, orig_name, sym_info):
                        if sym_name in self.struct_field_types:
                            return
                        if isinstance(sym_info, str):
                            self.imported_symbols[sym_name] = {
                                'module': s.module, 'original_name': orig_name,
                                'return_type': sym_info, 'parameters': [],
                                'signature': f"{sym_info} {sym_name} (void)"
                            }
                            self.func_return_types[sym_name] = sym_info
                        elif isinstance(sym_info, dict):
                            sym_info['module'] = s.module
                            sym_info['original_name'] = orig_name
                            self.imported_symbols[sym_name] = sym_info
                            if 'c_return_type' in sym_info:
                                self.func_return_types[sym_name] = sym_info['c_return_type']
                    if not s.names:
                        # Wildcard import: register all exported symbols
                        for _wc_key, _wc_info in exports.items():
                            _register_sym(_wc_key, _wc_key, _wc_info)
                    else:
                        for name, alias in s.names:
                            sym_name = alias if alias else name
                            sym_info = exports.get(name, {})
                            _register_sym(sym_name, name, sym_info)
                except Exception as e:
                    # Gracefully ignore module load errors
                    _debug_note('module load failed while registering imports', e)

        # Register user function return types (from current + imported modules)
        #   Pass 1: annotated return types (authoritative)
        all_functions = stmts + (imported_stmts if self.do_imports else [])
        for s in all_functions:
            if isinstance(s, FunctionDef) and s.return_type is not None:
                self.func_return_types[s.name] = self._resolve_type(s.return_type)
            # Register parameter types (for call-site coercion via _emit_call)
            if isinstance(s, FunctionDef) and s.params:
                if any(pn.startswith('*') for pn, _ in s.params):
                    self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                else:
                    self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params]
            # A genuine user free function (FunctionDef node, not a libc extern):
            # eligible for overload-mangling its C symbol by parameter types.
            if isinstance(s, FunctionDef) and s.name not in self._NO_OVERLOAD_MANGLE:
                self._mangled_funcs.add(s.name)
        #   Pass 1b: struct method annotated return types + param types (from current + imported modules)
        all_structs_for_methods = stmts + (imported_stmts if self.do_imports else [])
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    mangled = f"{s.name}_{m.name}"
                    if m.return_type is not None:
                        self.func_return_types[mangled] = self._resolve_type(m.return_type)
                    # Track @staticmethod methods so call sites don't pass cls arg
                    if hasattr(m, 'decorators') and 'staticmethod' in (m.decorators or []):
                        self._static_methods.add(mangled)
                    # Also store method param types using the mangled name (for call-site arg padding)
                    if m.params:
                        ctypes = []
                        for i, (pn, pt) in enumerate(m.params):
                            if i == 0 and pn == 'self':
                                ctypes.append(f"{s.name} *")
                            else:
                                ctypes.append(self._param_ctype(pn, pt, m))
                        # Don't overwrite hardcoded entries (e.g. Scope_define uses char* for name)
                        if mangled not in self.func_param_types:
                            self.func_param_types[mangled] = ctypes

        #   Pass 2: infer return types for unannotated functions using
        #           already-seeded func_return_types for callee types
        for s in all_functions:
            if isinstance(s, FunctionDef) and s.return_type is None:
                # Seed param types so _quick_type works for param names
                for pname, ptype in s.params:
                    self.var_types[pname] = self._resolve_type(ptype)
                inferred = self._infer_return_type(s.body)
                # Special case: main() should return int, not void
                if s.name == 'main' and inferred == 'void':
                    inferred = 'int64_t'
                self.func_return_types[s.name] = inferred
                self.var_types.clear()

        #   Pass 2b: infer return types for unannotated struct methods
        # Run to fixpoint: callee return types discovered in one round improve
        # inference for callers in the next round (handles forward calls like
        # Parser._parse_stmt calling Parser._parse_comptime).
        for _pass2b_iter in range(4):
            _changed = False
            for s in all_structs_for_methods:
                if isinstance(s, StructDef):
                    for m in s.methods:
                        if m.name == '__init__':
                            self._struct_has_init.add(s.name)
                            # Record __init__ param names (excl self) so a
                            # keyword-arg constructor call (Counter(start=...))
                            # binds kwargs to the right __init__ parameters.
                            self._struct_init_params[s.name] = [
                                pn for pn, _pt in m.params if pn != 'self']
                        if m.return_type is None:
                            for i, (pname, ptype) in enumerate(m.params):
                                if i == 0 and pname == 'self':
                                    self.var_types[pname] = f"{s.name} *"
                                else:
                                    self.var_types[pname] = self._resolve_type(ptype)
                            inferred = self._infer_return_type(m.body)
                            key = f"{s.name}_{m.name}"
                            if self.func_return_types.get(key) != inferred:
                                self.func_return_types[key] = inferred
                                _changed = True
                            self.var_types.clear()
            if not _changed:
                break

        # ── Pass 1.3: Infer parameter types from usage ─────────────────────
        # For parameters without type annotations, infer from member accesses
        self._inferred_param_types: dict[str, dict[str, str]] = {}  # func_name -> {param_name -> type}
        for s in all_functions:
            if isinstance(s, FunctionDef):
                self._inferred_param_types[s.name] = self._infer_param_types(s)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    key = f"{s.name}_{m.name}"
                    self._inferred_param_types[key] = self._infer_param_types(m)

        # ── Pass 1.3b: Infer local variable types from assignments ──────────
        # Scan all assignments to determine variable types; use int64_t for
        # variables that receive 64-bit values (list elements, arithmetic results)
        self._inferred_var_types: dict[str, dict[str, str]] = {}  # func_name -> {var_name -> type}
        for s in all_functions:
            if isinstance(s, FunctionDef):
                self._inferred_var_types[s.name] = self._infer_local_var_types(s)
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    key = f"{s.name}_{m.name}"
                    self._inferred_var_types[key] = self._infer_local_var_types(m)

        # ── Pass 1.3c: Populate func_param_types for all user functions ────────
        # CRITICAL: Must happen before Phase 2a (code generation) so that call-site
        # argument coercion has the correct expected parameter types. Otherwise,
        # _emit_call defaults to converting pointers to int64_t, losing type info.
        for s in all_functions:
            if isinstance(s, FunctionDef):
                if s.params and any(pn.startswith('*') for pn, _ in s.params):
                    self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                else:
                    self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    method_full_name = f"{s.name}_{m.name}"
                    if m.params and any(pn.startswith('*') for pn, _ in m.params):
                        self.func_param_types[method_full_name] = self._signature_ctypes(m.params, m, s.name)
                    else:
                        param_ctypes = []
                        for i, (pname, ptype) in enumerate(m.params):
                            if pname.startswith('**'):
                                continue  # skip **kwargs
                            if i == 0 and pname == 'self':
                                param_ctypes.append(f"{s.name} *")
                            else:
                                param_ctypes.append(self._param_ctype(pname, ptype, m))
                        self.func_param_types[method_full_name] = param_ctypes

        # ── Pass 1.3d: cross-call element-type contract ────────────────────
        # A container's element type lives in side-tables keyed by SSA name and
        # does not survive a call boundary, so a callee that indexes a passed-in
        # container falls back to int getters and silently corrupts non-int
        # payloads. Propagate it: where a caller passes a container whose element
        # types we can derive, record them onto the callee's parameter. Free
        # functions only for now (methods carry a `self` and are handled via
        # struct fields). Conflicting call sites collapse to unknown.
        self._param_elem_types: dict[str, dict[str, tuple]] = {}
        _free_params = {s.name: [pn for pn, _ in (s.params or []) if not pn.startswith('*')]
                        for s in all_functions if isinstance(s, FunctionDef)}

        def _record_param_elem(callee, pname, e, ne):
            d = self._param_elem_types.setdefault(callee, {})
            if pname in d and d[pname] != (e, ne):
                d[pname] = (None, None)   # conflicting call sites → unknown
            else:
                d[pname] = (e, ne)

        # Cross-call scalar contract: an unannotated scalar param defaults to the
        # int64_t machine word, so passing a double silently truncates (bnbody's
        # dt=0.01 -> 0 froze the sim). Observe each call argument's scalar type and
        # propagate a unanimous concrete one (double) onto the callee's param. A
        # function name -> def map lets us skip annotated params.
        _fn_by_name = {s.name: s for s in all_functions if isinstance(s, FunctionDef)}
        _scalar_obs: dict[str, dict[str, set]] = {}   # callee -> {pname -> {types}}

        def _arg_scalar_type(caller_name, a):
            if isinstance(a, FloatLiteral):
                return 'double'
            if isinstance(a, IdentExpr):
                t = (self._inferred_var_types.get(caller_name, {}).get(a.name)
                     or self._inferred_param_types.get(caller_name, {}).get(a.name))
                return t
            return None

        for s in all_functions:
            if not isinstance(s, FunctionDef):
                continue
            elem, nested = self._scan_container_elems(s.body)
            calls = []
            self._calls_in_stmts(s.body, calls)
            for call in calls:
                if not isinstance(call.func, IdentExpr):
                    continue
                callee = call.func.name
                pnames = _free_params.get(callee)
                if not pnames:
                    continue
                for i, a in enumerate(call.args):
                    if i >= len(pnames):
                        break
                    if isinstance(a, IdentExpr) and a.name in elem:
                        _record_param_elem(callee, pnames[i],
                                            elem[a.name], nested.get(a.name))
                    st = _arg_scalar_type(s.name, a)
                    if st:
                        _scalar_obs.setdefault(callee, {}).setdefault(pnames[i], set()).add(st)

        # Apply: a unanimous concrete double observed across all call sites of an
        # unannotated, weakly-defaulted param becomes that param's type.
        for callee, pmap in _scalar_obs.items():
            fn = _fn_by_name.get(callee)
            if not fn:
                continue
            ann = {pn: pt for pn, pt in (fn.params or [])}
            for pname, types in pmap.items():
                if types != {'double'}:
                    continue                         # not unanimous double
                if ann.get(pname) is not None:
                    continue                         # respect explicit annotation
                cur = self._inferred_param_types.get(callee, {}).get(pname)
                if cur in (None, 'int', 'int64_t'):
                    self._inferred_param_types.setdefault(callee, {})[pname] = 'double'

        # Rebuild free-function param-type signatures so call-site coercion sees
        # the propagated scalar types (this must follow the propagation above).
        for s in all_functions:
            if isinstance(s, FunctionDef):
                if s.params and any(pn.startswith('*') for pn, _ in s.params):
                    self.func_param_types[s.name] = self._signature_ctypes(s.params, s)
                else:
                    self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params] if s.params else []

        # ── Phase 1.5: dispatch solving (static dispatch table planning) ───
        # Run DispatchSolver to identify dynamic dispatch patterns and plan
        # virtual method tables before generating code. This enables static
        # dispatch instead of dynamic getattr/dict lookups.
        if self.emit_struct_defs:  # Only main module does dispatch solving
            self._dispatch_solver = DispatchSolver(self.struct_field_types, self.func_return_types)
            all_stmts_for_dispatch = stmts + (imported_stmts if self.do_imports else [])
            self._dispatch_solver.analyze(all_stmts_for_dispatch)
            self._dispatch_tables = self._dispatch_solver.get_dispatch_tables()

        # ── Pass 3: collect closures (nested FunctionDef nodes) ──────────
        self._all_closures: dict = {}  # outer_name → {inner_name → ClosureInfo}

        def _scan_for_closures(outer_name: str, outer_scope: dict, body: list):
            """Scan a function/method body for nested FunctionDefs and register them as closures."""
            def _all_stmts_nonfunc(stmts):
                """Yield statements recursively through control flow, not entering FunctionDef bodies."""
                for s in stmts:
                    yield s
                    if isinstance(s, FunctionDef):
                        continue
                    for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                        sub = getattr(s, attr, None)
                        if isinstance(sub, list):
                            yield from _all_stmts_nonfunc(sub)
                    for _cond, elif_body in getattr(s, 'elifs', []):
                        yield from _all_stmts_nonfunc(elif_body)
                    for handler in getattr(s, 'handlers', []):
                        if hasattr(handler, 'body') and isinstance(handler.body, list):
                            yield from _all_stmts_nonfunc(handler.body)

            # Enrich outer_scope with local variable assignments/declarations for capture detection.
            enriched_scope = dict(outer_scope)
            _saved_vt2 = dict(self.var_types)
            self.var_types.update(outer_scope)
            for bstmt in _all_stmts_nonfunc(body):
                if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                    name = bstmt.target.name
                    if name not in enriched_scope:
                        t = self._quick_type(bstmt.value)
                        enriched_scope[name] = t
                        self.var_types[name] = t
                elif isinstance(bstmt, VarDecl):
                    if bstmt.name not in enriched_scope:
                        t = self._quick_type(bstmt.value) if bstmt.value else 'int64_t'
                        enriched_scope[bstmt.name] = t
                        self.var_types[bstmt.name] = t
            self.var_types = _saved_vt2
            for stmt in _all_stmts_nonfunc(body):
                if not isinstance(stmt, FunctionDef):
                    continue
                inner     = stmt
                lifted    = f"{outer_name}_{inner.name}"
                # Compute free variables: used in inner body minus inner scope
                used      = set()
                for body_node in inner.body:
                    used |= _used_idents_node(body_node)
                # Include AssignStmt targets in declared vars (they're local to inner).
                # Recurse into for/if/while bodies since Python scoping is function-wide.
                inner_assign_targets = set()
                for bstmt in _all_stmts_nonfunc(inner.body):
                    if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                        inner_assign_targets.add(bstmt.target.name)
                    elif isinstance(bstmt, ForStmt):
                        tgt = bstmt.target
                        if isinstance(tgt, str):
                            inner_assign_targets.add(tgt)
                        elif hasattr(tgt, 'name'):
                            inner_assign_targets.add(tgt.name)
                inner_declared = ({pn for pn, _ in inner.params}
                                  | _declared_vars_body(inner.body)
                                  | inner_assign_targets)
                # Exclude known globals/imported functions from capture — but NOT if
                # the outer function has a PARAMETER with the same name (parameter
                # shadows the global and must be captured, not treated as a global ref).
                # We use outer_scope (parameters only) not enriched_scope (which includes
                # local assignments like module imports that should NOT be captured).
                outer_params = set(outer_scope.keys())
                free_globals = set(self.func_return_types.keys()) - outer_params
                free         = used - inner_declared - free_globals
                captures     = [(v, enriched_scope[v]) for v in sorted(free)
                                if v in enriched_scope]
                env_struct   = f"{lifted}_env" if captures else ""
                ci           = ClosureInfo(lifted, env_struct, captures, inner)
                if outer_name not in self._all_closures:
                    self._all_closures[outer_name] = {}
                self._all_closures[outer_name][inner.name] = ci
                # Register lifted name so callers can resolve its return type
                if inner.return_type is not None:
                    self.func_return_types[lifted] = self._resolve_type(inner.return_type)
                else:
                    # Quick inference for unannotated inner
                    for pname, ptype in inner.params:
                        self.var_types[pname] = self._resolve_type(ptype)
                    self.func_return_types[lifted] = self._infer_return_type(inner.body)
                    self.var_types.clear()
                # Also recursively scan inner body for doubly-nested closures.
                # Build inner_scope from enriched_scope + inner params + inner local assignments.
                inner_scope = dict(enriched_scope)
                for pn, pt in inner.params:
                    inner_scope[pn] = self._resolve_type(pt)
                for bstmt in inner.body:
                    if isinstance(bstmt, AssignStmt) and isinstance(bstmt.target, IdentExpr):
                        name = bstmt.target.name
                        if name not in inner_scope:
                            inner_scope[name] = self._quick_type(bstmt.value)
                _scan_for_closures(lifted, inner_scope, inner.body)

            # After registering all closures for this outer function, detect re.sub callbacks.
            # Pattern: re.sub(pattern, callback_name, src) where callback_name is a registered inner.
            def _find_re_sub_callbacks(search_body, context_outer):
                for stmt in search_body:
                    stmts_to_check = []
                    if isinstance(stmt, AssignStmt):
                        stmts_to_check.append(stmt.value)
                    elif isinstance(stmt, ExprStmt):
                        stmts_to_check.append(stmt.value)  # ExprStmt uses .value
                    elif hasattr(stmt, 'body'):
                        _find_re_sub_callbacks(getattr(stmt, 'body', []), context_outer)
                        for clause in ('orelse', 'handlers', 'finalbody'):
                            _find_re_sub_callbacks(getattr(stmt, clause, []), context_outer)
                    for expr in stmts_to_check:
                        if not isinstance(expr, CallExpr):
                            continue
                        func = expr.func
                        # re.sub(pat, callback, src)
                        if (isinstance(func, MemberExpr)
                                and isinstance(func.obj, IdentExpr)
                                and func.obj.name == 're'
                                and func.member == 'sub'
                                and len(expr.args) >= 2):
                            cb_arg = expr.args[1]
                            if isinstance(cb_arg, IdentExpr):
                                inner_map = self._all_closures.get(context_outer, {})
                                if cb_arg.name in inner_map:
                                    inner_map[cb_arg.name].is_re_sub_callback = True
            _find_re_sub_callbacks(body, outer_name)

        for s in stmts:
            if isinstance(s, FunctionDef):
                # Build outer scope: params + VarDecl locals + untyped assignment targets
                outer_scope: dict = {}
                for pname, ptype in s.params:
                    outer_scope[pname] = self._resolve_type(ptype)
                # Seed var_types so _quick_type can resolve calls on typed parameters
                _saved_vt = dict(self.var_types)
                self.var_types.update(outer_scope)
                for stmt in s.body:
                    if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                        t = _mojo_type(stmt.type_ann)
                        outer_scope[stmt.name] = t
                        self.var_types[stmt.name] = t
                    elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                        if stmt.target.name not in outer_scope:
                            t = self._quick_type(stmt.value)
                            outer_scope[stmt.target.name] = t
                            self.var_types[stmt.target.name] = t
                self.var_types = _saved_vt
                _scan_for_closures(s.name, outer_scope, s.body)
            elif isinstance(s, StructDef):
                # Also scan struct methods for nested functions
                _moids = self._struct_method_overload_ids(s)
                for method, _oid in zip(s.methods, _moids):
                    outer_name = f"{s.name}_{method.name}{_oid}"
                    outer_scope = {s.name.lower(): f"{s.name} *"}  # struct instance
                    for pname, ptype in method.params:
                        if pname == 'self':
                            outer_scope['self'] = f"{s.name} *"
                        else:
                            outer_scope[pname] = self._resolve_type(ptype)
                    # Seed var_types so _quick_type can resolve method calls on self/params
                    _saved_vt = dict(self.var_types)
                    self.var_types.update(outer_scope)
                    for stmt in method.body:
                        if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                            t = _mojo_type(stmt.type_ann)
                            outer_scope[stmt.name] = t
                            self.var_types[stmt.name] = t
                        elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                            if stmt.target.name not in outer_scope:
                                t = self._quick_type(stmt.value)
                                outer_scope[stmt.target.name] = t
                                self.var_types[stmt.target.name] = t
                    self.var_types = _saved_vt
                    _scan_for_closures(outer_name, outer_scope, method.body)

        # ── Phase 1.6: propagate transitive captures ─────────────────────
        # If sub-closure S captures variable X from scope that intermediate
        # closure C doesn't directly use, C must also capture X so it can
        # pass it to S's env struct. Repeat until fixpoint.
        _changed = True
        while _changed:
            _changed = False
            for _outer_name, _inner_map in list(self._all_closures.items()):
                for _inner_name, _ci in list(_inner_map.items()):
                    _sub_closures = self._all_closures.get(_ci.lifted_name, {})
                    if not _sub_closures:
                        continue
                    _ci_param_names = {pn for pn, _ in _ci.inner_def.params}
                    _ci_local_assigns = set()
                    for _bstmt in _ci.inner_def.body:
                        if isinstance(_bstmt, AssignStmt) and isinstance(_bstmt.target, IdentExpr):
                            _ci_local_assigns.add(_bstmt.target.name)
                    _ci_own_vars = (_ci_param_names
                                    | _declared_vars_body(_ci.inner_def.body)
                                    | _ci_local_assigns)
                    _ci_captures_dict = dict(_ci.captures)
                    for _sub_ci in _sub_closures.values():
                        for _sv, _st in _sub_ci.captures:
                            if _sv not in _ci_own_vars and _sv not in _ci_captures_dict:
                                _ci.captures.append((_sv, _st))
                                _ci_captures_dict[_sv] = _st
                                if not _ci.env_struct:
                                    _ci.env_struct = f"{_ci.lifted_name}_env"
                                _changed = True

        # ── Phase 1.7: pre-scan global variable declarations ──────────────
        # Must run before Phase 2a so _lower_IdentExpr can find globals.
        _pre_declared_globals = set()
        _phase17_mod = self.module_name or "root"  # module name for _global_to_module mapping
        for _scan_stmt in stmts + (imported_stmts if self.do_imports else []):
            if isinstance(_scan_stmt, AssignStmt) and isinstance(_scan_stmt.target, IdentExpr):
                _gname = _scan_stmt.target.name
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
                if _gname not in self._global_to_module:
                    self._global_to_module[_gname] = _phase17_mod
                if isinstance(_scan_stmt.value, DictExpr):
                    self._global_var_types[_gname] = 'MojoDict *'
                elif isinstance(_scan_stmt.value, (ListExpr, TupleExpr)):
                    self._global_var_types[_gname] = 'MojoList *'
                elif isinstance(_scan_stmt.value, SetExpr):
                    self._global_var_types[_gname] = 'MojoSet *'
                elif isinstance(_scan_stmt.value, (IntLiteral, BoolLiteral)):
                    self._global_var_types[_gname] = 'int'
                elif isinstance(_scan_stmt.value, StringLiteral):
                    self._global_var_types[_gname] = 'char *'
                elif isinstance(_scan_stmt.value, CallExpr):
                    if isinstance(_scan_stmt.value.func, IdentExpr) and _scan_stmt.value.func.name in self.struct_field_types:
                        struct_name = _scan_stmt.value.func.name
                        self._global_var_types[_gname] = f"{struct_name} *"
                    elif isinstance(_scan_stmt.value.func, IdentExpr):
                        ret = self.func_return_types.get(_scan_stmt.value.func.name, '')
                        if ret.endswith(' *'):
                            self._global_var_types[_gname] = ret
                        elif ret == 'char *':
                            self._global_var_types[_gname] = 'char *'
                        else:
                            self._global_var_types[_gname] = 'int64_t'
                    else:
                        self._global_var_types[_gname] = 'int64_t'
                else:
                    self._global_var_types[_gname] = 'int64_t'
            elif isinstance(_scan_stmt, VarDecl) and _scan_stmt.name not in _pre_declared_globals:
                _pre_declared_globals.add(_scan_stmt.name)
                if _scan_stmt.name not in self._global_to_module:
                    self._global_to_module[_scan_stmt.name] = _phase17_mod
                if _scan_stmt.type_ann:
                    self._global_var_types[_scan_stmt.name] = self._resolve_type(_scan_stmt.type_ann)
                else:
                    # Infer type from value if present
                    if hasattr(_scan_stmt, 'value') and _scan_stmt.value:
                        if isinstance(_scan_stmt.value, DictExpr):
                            self._global_var_types[_scan_stmt.name] = 'MojoDict *'
                        elif isinstance(_scan_stmt.value, (ListExpr, TupleExpr)):
                            self._global_var_types[_scan_stmt.name] = 'MojoList *'
                        elif isinstance(_scan_stmt.value, SetExpr):
                            self._global_var_types[_scan_stmt.name] = 'MojoSet *'
                        elif isinstance(_scan_stmt.value, StringLiteral):
                            self._global_var_types[_scan_stmt.name] = 'char *'
                        elif isinstance(_scan_stmt.value, CallExpr):
                            if isinstance(_scan_stmt.value.func, IdentExpr):
                                ret = self.func_return_types.get(_scan_stmt.value.func.name, '')
                                if ret and ret.endswith(' *'):
                                    self._global_var_types[_scan_stmt.name] = ret
                                elif ret == 'char *':
                                    self._global_var_types[_scan_stmt.name] = 'char *'
                                else:
                                    self._global_var_types[_scan_stmt.name] = 'int64_t'
                            else:
                                self._global_var_types[_scan_stmt.name] = 'int64_t'
                        else:
                            self._global_var_types[_scan_stmt.name] = 'int64_t'
                    else:
                        self._global_var_types[_scan_stmt.name] = 'int64_t'

        # Also scan ImportStmts inside TryStmt/IfStmt blocks (e.g., try: import mojo_compiler)
        # These are missed by the flat scan above.
        def _scan_try_imports(stmt_list):
            for _s in stmt_list:
                if isinstance(_s, ImportStmt):
                    _local = _s.alias if _s.alias else _s.module
                    if _local not in self._global_var_types:
                        self._global_var_types[_local] = 'int64_t'
                        self._global_c_decl_types[_local] = 'int64_t'
                        if _local not in self._global_to_module:
                            self._global_to_module[_local] = _phase17_mod
                elif isinstance(_s, TryStmt):
                    _scan_try_imports(_s.body or [])
                    for _h in (_s.handlers or []):
                        _scan_try_imports(getattr(_h, 'body', []) or [])
                elif isinstance(_s, IfStmt):
                    _scan_try_imports(_s.then_body or [])
                    if isinstance(_s.else_body, list):
                        _scan_try_imports(_s.else_body)
        _scan_try_imports(stmts + (imported_stmts if self.do_imports else []))

        # Pre-populate _global_c_decl_types from _global_var_types so Phase 2a
        # generates correct loads for globals whose C type is a pointer (not boxed int64_t).
        _EARLY_DISPATCH_DICTS = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS',
                                 '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
        _EARLY_DISPATCH_SETS = {'_CMP_OPS'}
        for _gn, _gt in list(self._global_var_types.items()):
            if _gn in self._global_c_decl_types:
                continue
            if _gn in _EARLY_DISPATCH_DICTS:
                self._global_c_decl_types[_gn] = 'MojoDict *'
            elif _gn in _EARLY_DISPATCH_SETS:
                self._global_c_decl_types[_gn] = 'MojoSet *'
            elif _gt in ('MojoDict *', 'MojoList *', 'MojoSet *'):
                self._global_c_decl_types[_gn] = 'int64_t'  # boxed by default
            else:
                self._global_c_decl_types[_gn] = _gt

        # ── Phase 2a: generate all function bodies ────────────────────────
        # This pass populates _ptr_helpers_needed and _struct_allocs_needed
        # so the preamble helpers can be emitted before the __GIMPLE bodies.

        func_parts: list[str] = []

        _emitted_closures: set[str] = set()

        def _emit_closure_recursive(ci) -> None:
            """Emit sub-closures first (depth-first), then this closure's allocator + body."""
            # Deduplicate: overloaded methods share the same closure outer_name, so
            # the same lifted closure may be emitted multiple times (once per overload).
            if ci.lifted_name in _emitted_closures:
                return
            _emitted_closures.add(ci.lifted_name)
            for sub_ci in self._all_closures.get(ci.lifted_name, {}).values():
                _emit_closure_recursive(sub_ci)
            if ci.env_struct:
                alloc_fn = f"_alloc_{ci.env_struct}"
                func_parts.append(
                    f"{ci.env_struct} * __GIMPLE {alloc_fn} (void)\n"
                    f"{{\n"
                    f"  {ci.env_struct} * _e;\n"
                    f"  void * _vp;\n"
                    f"\nbb_2:\n"
                    f"  _vp = malloc (sizeof({ci.env_struct}));\n"
                    f"  _e = ({ci.env_struct} *) _vp;\n"
                    f"  return _e;\n"
                    f"}}"
                )
                func_parts.append('')
            func_parts.append(self._gen_lifted_closure(ci))
            func_parts.append('')

        # Collect top-level statements for _toplevel() function
        toplevel_stmts = []

        # Pre-scan so the main() wrapper (emitted by _gen_function below, before
        # has_toplevel_code is known) can decide whether to call _toplevel().
        # If there is no top-level code we trim the call entirely; otherwise the
        # _toplevel() function is emitted and the call links.
        _toplevel_types = (AssignStmt, AugAssignStmt, ExprStmt,
                           IfStmt, WhileStmt, ForStmt,
                           TryStmt, WithStmt, PassStmt,
                           BreakStmt, ContinueStmt, ReturnStmt,
                           RaiseStmt, AssertStmt)
        self._has_toplevel_code = any(isinstance(s, _toplevel_types) for s in stmts)

        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                for ci in self._all_closures.get(stmt.name, {}).values():
                    _emit_closure_recursive(ci)
                self._lambda_parts = []
                func_parts.append(self.gen_func(stmt))
                # Flush any lambdas lifted during gen_func, emitting them
                # immediately before the enclosing function body so forward
                # declarations in the preamble resolve correctly.
                if self._lambda_parts:
                    func_parts.extend(self._lambda_parts)
                    self._lambda_parts = []
                func_parts.append('')
            elif isinstance(stmt, StructDef):
                # Overload IDs aligned with stmt.methods; the closure-emit, the
                # method symbol, and the pre-pass closure registration all key by
                # the same overload-suffixed name (so overloaded methods with
                # nested closures don't share capture state).
                _moids = self._struct_method_overload_ids(stmt)
                for m, overload_id in zip(stmt.methods, _moids):
                    method_outer_name = f"{stmt.name}_{m.name}{overload_id}"
                    # Emit lifted closures for this method (if any), recursively
                    for ci in self._all_closures.get(method_outer_name, {}).values():
                        _emit_closure_recursive(ci)
                    func_parts.append(self._gen_struct_method(stmt.name, m, overload_id))
                    func_parts.append('')
            elif isinstance(stmt, TraitDef):
                lines = [f"typedef struct {stmt.name}_vtable {{"]
                _seen_vtable_members: set = set()
                for m in stmt.methods:
                    safe_mname = _safe_name(m.name)
                    if safe_mname in _seen_vtable_members:
                        continue
                    _seen_vtable_members.add(safe_mname)
                    ret    = self._resolve_type(m.return_type)
                    if m.params and any(pn.startswith('*') for pn, _ in m.params):
                        ptypes = 'MojoList *'
                    else:
                        ptypes = (', '.join(self._resolve_type(pt) for _, pt in m.params)
                                  if m.params else 'void')
                    lines.append(f"  {ret} (*{safe_mname}) ({ptypes});")
                lines.append(f"}} {stmt.name}_vtable;")
                func_parts.extend(lines)
                func_parts.append('')
            elif isinstance(stmt, (ImportStmt, FromImportStmt)):
                pass  # Imports processed in pre-pass; extern declarations generated in preamble
            elif isinstance(stmt, (AssignStmt, AugAssignStmt, ExprStmt,
                                   IfStmt, WhileStmt, ForStmt,
                                   TryStmt, WithStmt, PassStmt,
                                   BreakStmt, ContinueStmt, ReturnStmt,
                                   RaiseStmt, AssertStmt)):
                # Collect all executable statements for _toplevel()
                toplevel_stmts.append(stmt)
            else:
                _debug_note('top-level statement dropped', type(stmt).__name__)
                func_parts.append(f"/* TODO: top-level {type(stmt).__name__} */")

        # Populate func_param_types BEFORE _gen_toplevel so call-site coercion works
        # This must happen before _gen_toplevel since it needs param types for _emit_call
        func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
        for fn in func_defs:
            if fn.name == 'main':
                continue
            if fn.params and any(pn.startswith('*') for pn, _ in fn.params):
                self.func_param_types[fn.name] = self._signature_ctypes(fn.params, fn)
            else:
                inferred_params = self._inferred_param_types.get(fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
                param_ctypes = []
                for pn, pt in (fn.params or []):
                    if pn in inferred_params:
                        param_ctypes.append(inferred_params[pn])
                    else:
                        param_ctypes.append(self._param_ctype(pn, pt, fn))
                self.func_param_types[fn.name] = param_ctypes

        # Only generate _toplevel() if there are actual top-level statements
        has_toplevel_code = len(toplevel_stmts) > 0
        if has_toplevel_code:
            toplevel_func = self._gen_toplevel(toplevel_stmts)
            func_parts.append(toplevel_func)
            func_parts.append('')
            # In library mode, register the sub-module toplevel for the root to call
            if not self.emit_entry_points:
                sub_fn = _module_toplevel_name(self.module_name)
                if sub_fn not in self._sub_toplevels:
                    self._sub_toplevels.append(sub_fn)

        # Only generate entry points (main/_gimple_main) for the root module
        if self.emit_entry_points:
            has_main = any(isinstance(stmt, FunctionDef) and stmt.name == 'main' for stmt in stmts)
            if not has_main:
                func_parts.append("int _gimple_main (void)")
                func_parts.append("{")
                func_parts.append("  return 0;")
                func_parts.append("}")
                func_parts.append("")
                func_parts.append("int main (int argc, const char **argv) {")
                func_parts.append("  mojo_set_argv(argc, argv);")
                func_parts.append("#if USE_PYTHON")
                func_parts.append("  Py_Initialize ();")
                func_parts.append("#endif")
                # Call sub-module toplevels first
                for sub_fn in self._sub_toplevels:
                    func_parts.append(f"  {sub_fn} ();")
                # Then call root's own _toplevel if it has top-level code
                if has_toplevel_code:
                    func_parts.append("  _toplevel ();")
                func_parts.append("#if USE_PYTHON")
                func_parts.append("  Py_Finalize ();")
                func_parts.append("#endif")
                func_parts.append("  return 0;")
                func_parts.append("}")

        # ── Phase 2b: assemble final C output ────────────────────────────

        parts = [
            '/* Generated by gimple_codegen.py */',
            '/* Compile with: gcc -fgimple -fsyntax-only file.c (uses gcc-15 if available) */',
            '#define USE_PYTHON 0',
            '#include <stdint.h>',
            '#include <stdlib.h>',
            '#include <string.h>',
            '#include <math.h>',
            '#include <stdio.h>',
            '#include <setjmp.h>',
            '#include <dlfcn.h>',
            '#if USE_PYTHON',
            '#include <Python.h>',
            '#endif',
            '#include <mojo_runtime.h>',
            '/* Disable security wrappers: sprintf/snprintf macros expand to nested',
            '   __builtin___sprintf_chk calls which GIMPLE rejects. */',
            '#ifdef sprintf',
            '#undef sprintf',
            '#endif',
            '#ifdef snprintf',
            '#undef snprintf',
            '#endif',
            '/* Undefine exception-name macros from mojo_runtime.h that clash with',
            '   Mojo struct/class names in generated code. */',
            '#ifdef StopIteration',
            '#undef StopIteration',
            '#endif',
            '#ifdef ValueError',
            '#undef ValueError',
            '#endif',
            '#ifdef TypeError',
            '#undef TypeError',
            '#endif',
            '#ifdef IndexError',
            '#undef IndexError',
            '#endif',
            '#ifdef KeyError',
            '#undef KeyError',
            '#endif',
            '#ifdef NotImplementedError',
            '#undef NotImplementedError',
            '#endif',
            'void mojo_print(char *str);',
        ]
        # Forward declarations for sub-module toplevels and root toplevel
        if self.emit_entry_points:
            # Root module: forward-declare all sub-module toplevels
            for sub_fn in self._sub_toplevels:
                parts.append(f'void {sub_fn}(void);')
            # Forward-declare root's own _toplevel if it has top-level code
            if has_toplevel_code:
                parts.append('void _toplevel(void);')
        else:
            # Library module: forward-declare this module's own toplevel if it has one
            if has_toplevel_code:
                fn_name = _module_toplevel_name(self.module_name)
                parts.append(f'void {fn_name}(void);')
        # Built-in type constructor stubs: only emit for names not defined as
        # structs in this module AND not imported (both would conflict with the
        # function declaration).
        _local_structs = set(self.struct_field_types.keys())
        _imported_names = set(self.imported_symbols.keys())
        _skip_ctors = _local_structs | _imported_names
        _builtin_ctors = [
            # Use (...) so any argument type is accepted — these are stubs for
            # Mojo type constructors whose call signatures vary widely at use sites.
            ('String',   'int64_t String(...);'),
            ('Int',      'int64_t Int(...);'),
            ('UInt',     'int64_t UInt(...);'),
            ('Bool',     'int64_t Bool(...);'),
            ('Int8',     'int64_t Int8(...);'),
            ('Int16',    'int64_t Int16(...);'),
            ('Int32',    'int64_t Int32(...);'),
            ('Int64',    'int64_t Int64(...);'),
            ('UInt8',    'int64_t UInt8(...);'),
            ('UInt16',   'int64_t UInt16(...);'),
            ('UInt32',   'int64_t UInt32(...);'),
            ('UInt64',   'int64_t UInt64(...);'),
            ('Float16',  'int64_t Float16(...);'),
            ('BFloat16', 'int64_t BFloat16(...);'),
            ('Float32',  'int64_t Float32(...);'),
            ('Float64',  'int64_t Float64(...);'),
            ('Error',    'int64_t Error(...);'),
        ]
        def _guarded_ctor(name, decl):
            guard = f'_MOJO_CTOR_{name.upper()}'
            return f'#ifndef {guard}\n#define {guard}\n{decl}\n#endif'
        _ctor_lines = [_guarded_ctor(name, decl) for name, decl in _builtin_ctors if name not in _skip_ctors]
        if _ctor_lines:
            parts.append('/* Mojo built-in type constructors */')
            parts.extend(_ctor_lines)
            parts.append('')
        # Also skip utility stubs for locally-defined functions (they'd conflict).
        # Exclude _C_RESERVED_FUNCS names: those Mojo functions get renamed to mojo_X,
        # so the C function (e.g. getuid) still needs its stub declaration.
        _local_funcs = {s.name for s in stmts
                        if isinstance(s, FunctionDef) and s.name not in _C_RESERVED_FUNCS}
        # Also include struct method names (e.g. Span_unsafe_ptr from fn Span.unsafe_ptr)
        for _s in stmts:
            if isinstance(_s, StructDef):
                for _m in (_s.methods or []):
                    if isinstance(_m, FunctionDef):
                        _local_funcs.add(f'{_s.name}_{_m.name}')
        # Renamed forms of local/imported functions — Phase 2b emits proper forward
        # declarations with real signatures; the variadic preamble stub would conflict.
        _local_funcs_renamed = {_safe_name(s.name) for s in stmts if isinstance(s, FunctionDef)}
        _imported_names_renamed = {_safe_name(n) for n in _imported_names}
        # Also skip stubs for functions defined in any sub-module (do_imports=True monolithic build).
        # Exclude _C_RESERVED_FUNCS: their Mojo wrappers get renamed (e.g. getuid → mojo_getuid)
        # so the underlying C function still needs its util stub.
        _all_defined_funcs = (set(self.func_return_types.keys()) | self._global_inline_defs) - _C_RESERVED_FUNCS
        _skip_util = (_local_structs | _imported_names | _local_funcs | _all_defined_funcs
                      | _local_funcs_renamed | _imported_names_renamed)
        _util_pairs = [
            ('iter',    'int64_t iter(...);'),
            ('next',    'int64_t next(...);'),
            ('swap',    'void swap(...);'),
            ('op',      'int64_t op(...);'),
            ('U128',    'int64_t U128(...);'),
            ('divmod',  'int64_t divmod(...);'),
            # Pointer: guarded so it's suppressed if the struct typedef was already emitted
            ('Pointer', '#ifndef _MOJO_POINTER_STRUCT_DEF\nint64_t Pointer(...);\n#endif'),
            # Commonly used Mojo stdlib types/constructors — forward-declared as variadic
            # so they compile without full type resolution (do_imports=False mode).
            ('UnsafePointer',    'int64_t UnsafePointer(...);'),
            ('StringSlice',      'int64_t StringSlice(...);'),
            ('StaticString',     'int64_t StaticString(...);'),
            ('debug_assert',     'void debug_assert(...);'),
            ('__get_mvalue_as_litref', 'int64_t __get_mvalue_as_litref(...);'),
            ('__get_litref_as_mvalue', 'int64_t __get_litref_as_mvalue(...);'),
            ('MojoList_unsafe_ptr',    'int64_t MojoList_unsafe_ptr(...);'),
            ('MojoList_unsafe_get',    'int64_t MojoList_unsafe_get(...);'),
            ('Span_unsafe_ptr',        'int64_t Span_unsafe_ptr(...);'),
            ('Optional',               'int64_t Optional(...);'),
            ('int64_t_init_pointee_move', 'void int64_t_init_pointee_move(...);'),
            ('conforms_to',            '_Bool conforms_to(int64_t a, int64_t b);'),
            ('Codepoint',              'int64_t Codepoint(...);'),
            ('stat_result',            'int64_t stat_result(...);'),
            ('UInt128',                'int64_t UInt128(...);'),
            ('SIMDSize',               'int64_t SIMDSize(...);'),
            ('List',                   'int64_t List(...);'),
            ('MojoDict__reserved',     'int64_t MojoDict__reserved(...);'),
            ('ord',                    'int64_t ord(...);'),
            ('chr',                    'int64_t chr(...);'),
            ('sort',                   'void sort(...);'),
            ('Span_byte_length',       'int64_t Span_byte_length(...);'),
            ('_stat_macos',            'int64_t _stat_macos(...);'),
            ('_getpw_macos',           'int64_t _getpw_macos(...);'),
            ('Passwd',                 'int64_t Passwd(...);'),
            ('create_test_device_context', 'int64_t create_test_device_context(...);'),
            ('check_write_to',         'void check_write_to(...);'),
            ('_unsupported_mma_op',    'void _unsupported_mma_op(...);'),
            ('IntType',                'int64_t IntType(...);'),
            ('Byte',                   'int64_t Byte(...);'),
            ('hash',                   'int64_t hash(...);'),
            ('MojoList___contains__',  'int64_t MojoList___contains__(...);'),
            ('MojoList_get_loaded_kgen_pack', 'int64_t MojoList_get_loaded_kgen_pack(...);'),
            ('_stat_linux_x86',        'int64_t _stat_linux_x86(...);'),
            ('func',                   'int64_t func(...);'),
            ('mojo_getenv',            'int64_t mojo_getenv(...);'),
            ('Span_as_bytes',          'int64_t Span_as_bytes(...);'),
            ('Span_get_immutable',     'int64_t Span_get_immutable(...);'),
            ('_Bool___mlir_i1__',      'int64_t _Bool___mlir_i1__(...);'),
            ('sync_parallelize',       'void sync_parallelize(...);'),
            ('main_func',              'void main_func(void);'),
            # Mojo SIMD/Scalar type constructors and utilities
            ('scalar',                 'int64_t scalar(...);'),
            ('Scalar',                 'int64_t Scalar(...);'),
            ('type_of',                'int64_t type_of(...);'),
            ('align_up',               'int64_t align_up(...);'),
            ('align_down',             'int64_t align_down(...);'),
            ('clamp',                  'int64_t clamp(...);'),
            ('isdir',                  'int isdir (char * path);'),
            ('serialize',              'void serialize(...);'),
            ('hex',                    'char * hex(...);'),
            ('slice',                  'int64_t slice(...);'),
            ('_getpw_linux',           'int64_t _getpw_linux(...);'),
            ('_lstat_macos',           'int64_t _lstat_macos(...);'),
            # POSIX functions not declared by our minimal header set (<unistd.h> stubs)
            ('getuid',   'unsigned int getuid (void);'),
            ('getgid',   'unsigned int getgid (void);'),
            ('getpid',   'int getpid (void);'),
            ('getppid',  'int getppid (void);'),
            ('isatty',   'int isatty (int fd);'),
            ('sysconf',  'long sysconf (int name);'),
            ('_log2_ceil',             'int64_t _log2_ceil(...);'),
            ('int64_t_unsafe_value',   'int64_t int64_t_unsafe_value(...);'),
            ('MojoDict_unsafe_ptr',    'int64_t MojoDict_unsafe_ptr(...);'),
            ('_Empty_copy',            'void _Empty_copy(...);'),
            ('_get_global_or_null',    'int64_t _get_global_or_null(...);'),
        ]
        def _guarded_stub(name, decl):
            guard = f'_MOJO_STUB_{name.upper()}'
            return f'#ifndef {guard}\n#define {guard}\n{decl}\n#endif'
        _util_stubs = [_guarded_stub(name, decl) for name, decl in _util_pairs if name not in _skip_util]
        parts.extend([
            '/* Mojo iterator and utility functions */',
            *_util_stubs,
            '',
            '/* Struct ___new stubs (for Self(...) call sites) */',
            *[f'int64_t {s}___new(...);' for s in sorted(getattr(self, '_self_ctor_stubs', set()))],
            '',
            '/* Renamed C-reserved builtins called without import (e.g. abs→mojo_abs) */',
            *[f'{rt} {fn}(...);'
              for fn, rt in sorted(getattr(self, '_renamed_builtin_calls', {}).items())
              if fn not in _skip_util and fn not in _imported_names
              and fn not in _local_funcs and fn not in _local_funcs_renamed
              and fn not in _imported_names_renamed],
            '',
            '',
            'char *gimple_codegen_compile_to_gimple(char *src, int do_imports, char *filename);',
            'char *compile_to_gimple(char *mojo_src, int do_imports, char *filename);',
            'int64_t mojo_open_file(char *path);',
            # Suppress mojo_open decl when this module defines or imports 'open'
            # (renamed to mojo_open via _C_RESERVED_FUNCS, causing a conflict)
            *([] if ('open' in self.func_return_types or 'open' in self.imported_symbols) else ['void *mojo_open(char *filename, char *mode);']),
            'int64_t int_write (int64_t, char *);',
            'int64_t int_parse_module (int);',
            # Genuinely-unimplemented dispatch helpers (ctypes Structure.in_dll
            # interop; a mis-dispatched .items()). Define as abort() stubs so the
            # program links, but any real call detonates loudly rather than
            # silently returning garbage. Include-guarded: the preamble is emitted
            # once per module, but these must be defined exactly once.
            # `static` so separately-compiled units (module cache: c1.o + l1.o)
            # don't collide at link; the include guard prevents same-file dup
            # (the preamble repeats per module).
            '#ifndef _MOJO_UNIMPL_STUBS',
            '#define _MOJO_UNIMPL_STUBS',
            'static char * _ReflectTable_in_dll (int64_t a, int64_t b, char * c) { return (char *)dlsym((void *)b, c); }',
            'static MojoList * _Bool_items (int64_t a) { return mojo_list_new(); }',
            'static int64_t id (int64_t x) { return x; }',
            '#endif',
        ])

        # extern prototypes for external_call[...] targets (e.g. write/read/isatty).
        # Skip libc names already declared by our standard includes to avoid clashes.
        for _ecname in sorted(self._external_protos):
            if _ecname in self._LIBC_DECLARED and _ecname not in self._NEEDS_SELF_EXTERN:
                continue
            _eret, _eargs = self._external_protos[_ecname]
            _argstr = ', '.join(_eargs) if _eargs else 'void'
            parts.append(f'extern {_eret} {_ecname} ({_argstr});')

        # Link mode: extern decls for imported symbols (bodies live in the linked
        # artifact / stdlib dylib, per ABI.md). Collected by the Phase-0 pre-pass.
        for _decl in getattr(self, '_link_import_decl_list', []):
            parts.append(_decl)
        # NOTE: extern decls for elaborated instantiations (incl. struct methods,
        # which reference monomorphized struct types) are emitted AFTER the struct
        # typedef section below, so the types they reference are already defined.

        # For all modules, declare extern references to known module globals structs
        # Each module can reference globals from other modules via these externs
        # Determine which module is being compiled from either module_name or filename
        our_mod = self.module_name or "root"
        if not self.module_name and self._current_filename:
            # Infer module name from filename (e.g., "myinterpreter.py" → "myinterpreter")
            import os
            our_mod = os.path.splitext(os.path.basename(self._current_filename))[0]

        all_modules_to_declare = set()

        # If this is not the root module, always declare root's globals (it's special)
        if our_mod != "root":
            all_modules_to_declare.add("root")

        # Add all modules we know about (including successfully compiled ones)
        all_modules_to_declare.update(self._module_globals.keys())

        # Also add all directly imported modules from stmts — even modules that
        # fail to compile need an extern incomplete-struct forward declaration
        # so references like `_build_stdlib_dylib_globals.x` don't get "undeclared".
        # Use the module name (not alias) since generated C accesses _module_globals not _alias_globals.
        all_scan_for_mods = stmts + (imported_stmts if self.do_imports else [])
        for _ms in all_scan_for_mods:
            if isinstance(_ms, ImportStmt):
                _mn = _ms.module  # module name, not alias (globals struct uses module name)
                if _mn and not _mn.startswith('_'):
                    all_modules_to_declare.add(_mn)
            elif isinstance(_ms, FromImportStmt):
                _mn = _ms.module
                if _mn and not _mn.startswith('_') and '.' not in _mn:
                    all_modules_to_declare.add(_mn)

        for mod_name in sorted(all_modules_to_declare):
            # Skip declaring our own module as extern (sorted: deterministic .ci
            # output, required for the bootstrap stage1==stage2==stage3 check)
            if mod_name == our_mod:
                continue
            # Ensure module names are valid C identifiers (replace dots → underscores)
            mod_str = str(mod_name) if mod_name else "root"
            safe_mod = _c_field_name(mod_str) if mod_str else "root"
            struct_name = f"_{safe_mod}_toplev"
            global_var = f"_{safe_mod}_globals"
            # Forward-declare the struct type with gcc attribute to allow incomplete use
            # AND the extern global instance
            parts.append(f'struct {struct_name} __attribute__((incomplete));  /* extern module globals struct */')
            parts.append(f'extern struct {struct_name} {global_var};')

        # Emit initial #line directive at the start if we have a filename
        # This sets the context for all subsequent code
        if self._current_filename:
            parts.append(f'#line 1 "{self._current_filename}"')

        # Emit struct typedefs early, before any functions that use them
        # This includes structs from struct_field_types (like Interpreter, Scope, etc.)
        # Emit in dependency order: structs with no struct dependencies first
        # Self-referential dependencies (e.g. Scope->Scope*) are allowed in C
        if self.emit_struct_defs and hasattr(self, 'struct_field_types') and self.struct_field_types:
            parts.append('')
            emitted = set()
            max_iterations = len(self.struct_field_types) + 1
            iteration = 0
            while emitted != set(self.struct_field_types.keys()) and iteration < max_iterations:
                iteration += 1
                for struct_name in sorted(self.struct_field_types.keys()):
                    if struct_name in emitted:
                        continue
                    fields = self.struct_field_types[struct_name]
                    # Check if all dependencies are emitted (excluding self-references)
                    dependencies_met = True
                    for field_type in fields.values():
                        # Extract struct name from type (e.g., "Scope *" → "Scope")
                        base_type = field_type.rstrip(' *')
                        # Allow self-references: Scope can have a field of type Scope*
                        if base_type == struct_name:
                            continue  # Self-reference is OK
                        if base_type in self.struct_field_types and base_type not in emitted:
                            dependencies_met = False
                            break
                    if not dependencies_met:
                        continue
                    # All dependencies met (or are self-references), emit this struct
                    if struct_name == 'Pointer':
                        parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    parts.append(f"typedef struct {struct_name} {{")
                    if fields:
                        for field_name, field_type in sorted(fields.items()):
                            field_type: str
                            # For self-references in typedef, use 'struct Name *' syntax
                            if field_type == f"{struct_name} *":
                                # Change Scope * to struct Scope * for self-references
                                field_type = f"struct {struct_name} *"
                            safe_fn = f'_kw_{field_name}' if (field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS) else field_name
                            parts.append(f"  {field_type} {safe_fn};")
                    else:
                        # Empty struct - add a dummy field for valid C
                        parts.append(f"  int _dummy;")
                    parts.append(f"}} {struct_name};")
                    parts.append(f"#define _MOJO_STUB_{struct_name.upper()}")  # suppress any later variadic stub
                    emitted.add(struct_name)
                    self._emitted_structs.add(struct_name)  # track for dedup in Section 2
            parts.append('')

        # extern decls for elaborated instantiations (generic functions + struct
        # methods). Emitted here, after the struct typedefs above, so struct-method
        # declarations like `Box_Int64_unbox (Box_Int64 *)` see the type.
        for _decl in getattr(self, '_elaborated_externs', []):
            parts.append(_decl)


        # Include compiled imported modules.
        # Record where imported code begins: imported modules may reference THIS
        # module's globals struct (e.g. myinterpreter reading _root_globals.mojo_compiler),
        # so the complete struct typedef must be inserted *before* this point rather than
        # after, otherwise those functions see an incomplete type. See the globals struct
        # emission below, which inserts at this index.
        _module_globals_insert_idx = len(parts)
        if imported_code:
            parts.append('')
            parts.extend(imported_code)

        # Pointer-at helper functions (plain C — pointer arithmetic forbidden in __GIMPLE)
        new_helpers = self._ptr_helpers_needed - self._emitted_ptr_helpers
        for et in sorted(new_helpers):
            cn = _c_id(et)
            parts.append(
                f"static {et} * _mojo_at_{cn} ({et} * p, int64_t n) {{ return p + n; }}"
            )
            self._emitted_ptr_helpers.add(et)
        if new_helpers:
            parts.append('')

        # Module-level globals (imported modules, dicts, lists, sets, values at module scope)
        global_decls = []  # kept for compatibility, but won't be emitted
        # Initialize module globals tracking for this module
        current_mod_name = self.module_name or "root"
        if current_mod_name not in self._module_globals:
            self._module_globals[current_mod_name] = []
            self._module_global_inits[current_mod_name] = {}
        # Dispatch table globals already forward-declared near top of file
        # Also declare imported dispatch tables as MojoDict/MojoSet globals
        _dispatch_dict_names = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS',
                                '_TYPE_MAP', '_SIGNED', '_UNSIGNED', '_FLOAT'}
        _dispatch_set_names = {'_CMP_OPS'}
        _dispatch_names = _dispatch_dict_names | _dispatch_set_names
        _declared_globals = set()
        all_scan = stmts + (imported_stmts if self.do_imports else [])
        for stmt in all_scan:
            if isinstance(stmt, FromImportStmt):
                for alias in stmt.names:
                    orig_name = alias[0]
                    local_name = alias[1] if len(alias) > 1 and alias[1] else orig_name
                    for check_name in (orig_name, local_name):
                        if check_name in _dispatch_dict_names and check_name not in _declared_globals:
                            global_decls.append(f"MojoDict * {check_name};")
                            _declared_globals.add(check_name)
                            self._global_c_decl_types[check_name] = 'MojoDict *'
                            self._global_var_types[check_name] = 'MojoDict *'
                        elif check_name in _dispatch_set_names and check_name not in _declared_globals:
                            global_decls.append(f"MojoSet * {check_name};")
                            _declared_globals.add(check_name)
                            self._global_c_decl_types[check_name] = 'MojoSet *'
                            self._global_var_types[check_name] = 'MojoSet *'
            elif isinstance(stmt, ImportStmt):
                local_name = stmt.alias if stmt.alias else stmt.module
                if local_name not in _declared_globals:
                    global_decls.append(f"int64_t {local_name};")
                    _declared_globals.add(local_name)
                    self._global_var_types[local_name] = 'int64_t'
                    if local_name not in self._global_to_module:
                        self._global_to_module[local_name] = current_mod_name
        # Scan current module + imported stmts for module-level variable declarations.
        # Also recurse into TryStmt/IfStmt/ForStmt bodies at module level since Python
        # allows module-level assignments inside try/except (e.g. mojo_compiler = None).
        def _collect_global_stmts(stmt_list):
            for _gs in stmt_list:
                yield _gs
                if isinstance(_gs, TryStmt):
                    yield from _collect_global_stmts(_gs.body or [])
                    for _h in (_gs.handlers or []):
                        yield from _collect_global_stmts(getattr(_h, 'body', []) or [])
                    yield from _collect_global_stmts(_gs.else_body or [] if isinstance(_gs.else_body, list) else [])
                    yield from _collect_global_stmts(_gs.finally_body or [] if isinstance(_gs.finally_body, list) else [])
                elif isinstance(_gs, IfStmt):
                    yield from _collect_global_stmts(_gs.then_body or [])
                    yield from _collect_global_stmts(_gs.else_body or [])

        all_global_scan = stmts + (imported_stmts if self.do_imports else [])
        for stmt in _collect_global_stmts(all_global_scan):
            if isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                gname = stmt.target.name
                if gname in _declared_globals:
                    continue
                _declared_globals.add(gname)
                if isinstance(stmt.value, DictExpr):
                    if gname in _dispatch_names:
                        global_decls.append(f"MojoDict * {gname};")
                        self._global_c_decl_types[gname] = 'MojoDict *'
                    else:
                        global_decls.append(f"int64_t {gname};  /* MojoDict * */")
                        self._global_c_decl_types[gname] = 'int64_t'
                    self._global_var_types[gname] = 'MojoDict *'
                elif isinstance(stmt.value, (ListExpr, TupleExpr)):
                    if gname in _dispatch_names:
                        global_decls.append(f"MojoList * {gname};")
                        self._global_c_decl_types[gname] = 'MojoList *'
                    else:
                        global_decls.append(f"int64_t {gname};  /* MojoList * */")
                        self._global_c_decl_types[gname] = 'int64_t'
                    self._global_var_types[gname] = 'MojoList *'
                elif isinstance(stmt.value, SetExpr):
                    if gname in _dispatch_names:
                        global_decls.append(f"MojoSet * {gname};")
                        self._global_c_decl_types[gname] = 'MojoSet *'
                    else:
                        global_decls.append(f"int64_t {gname};  /* MojoSet * */")
                        self._global_c_decl_types[gname] = 'int64_t'
                    self._global_var_types[gname] = 'MojoSet *'
                elif isinstance(stmt.value, (IntLiteral, BoolLiteral)):
                    global_decls.append(f"int {gname};")
                    self._global_var_types[gname] = 'int'
                    self._global_c_decl_types[gname] = 'int'
                elif isinstance(stmt.value, StringLiteral):
                    global_decls.append(f"char * {gname};")
                    self._global_var_types[gname] = 'char *'
                    self._global_c_decl_types[gname] = 'char *'
                elif isinstance(stmt.value, CallExpr):
                    if isinstance(stmt.value.func, IdentExpr) and stmt.value.func.name in self.struct_field_types:
                        struct_name = stmt.value.func.name
                        global_decls.append(f"{struct_name} * {gname};")
                        self._global_var_types[gname] = f"{struct_name} *"
                        self._global_c_decl_types[gname] = f"{struct_name} *"
                    elif isinstance(stmt.value.func, IdentExpr):
                        ret = self.func_return_types.get(stmt.value.func.name, '')
                        if ret.endswith(' *'):
                            global_decls.append(f"{ret} {gname};")
                            self._global_var_types[gname] = ret
                            self._global_c_decl_types[gname] = ret
                        elif ret == 'char *':
                            global_decls.append(f"char * {gname};")
                            self._global_var_types[gname] = 'char *'
                            self._global_c_decl_types[gname] = 'char *'
                        else:
                            global_decls.append(f"int64_t {gname};")
                            self._global_var_types[gname] = 'int64_t'
                            self._global_c_decl_types[gname] = 'int64_t'
                    else:
                        global_decls.append(f"int64_t {gname};")
                        self._global_var_types[gname] = 'int64_t'
                        self._global_c_decl_types[gname] = 'int64_t'
                else:
                    global_decls.append(f"int64_t {gname};")
                    self._global_var_types[gname] = 'int64_t'
                    self._global_c_decl_types[gname] = 'int64_t'
            elif isinstance(stmt, VarDecl) and stmt.name not in _declared_globals:
                _declared_globals.add(stmt.name)
                ctype = self._resolve_type(stmt.type_ann) if stmt.type_ann else 'int64_t'
                global_decls.append(f"{ctype} {stmt.name};")
                self._global_var_types[stmt.name] = ctype
                self._global_c_decl_types[stmt.name] = ctype
        # Skip emitting standalone global declarations — they'll be in module globals structs instead
        # if global_decls:
        #     parts.extend(global_decls)
        #     parts.append('')

        # Populate _module_globals tracking from collected globals
        # Build a map of global name -> module name for later lookup
        self._global_to_module: dict[str, str] = {}
        for gname in sorted(_declared_globals):   # sorted: deterministic field order for bootstrap
            if gname in self._global_var_types:
                g_mtype = self._global_var_types[gname]
                # Use g_mtype as C type; if it ends with *, it's a pointer type
                # Otherwise default to int64_t for numeric types
                if gname in self._global_c_decl_types:
                    c_type = self._global_c_decl_types[gname]
                elif g_mtype and g_mtype.endswith(' *'):
                    c_type = g_mtype
                else:
                    c_type = g_mtype if g_mtype and g_mtype in ('MojoDict *', 'MojoList *', 'MojoSet *', 'char *') else 'int64_t'
                # Find the initialization expression from stmts
                init_code = '0'
                for stmt in _collect_global_stmts(all_global_scan):
                    if isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr) and stmt.target.name == gname:
                        init_code = _extract_init_expr(stmt.value)
                        break
                    elif isinstance(stmt, ImportStmt) and (stmt.alias if stmt.alias else stmt.module) == gname:
                        init_code = '0'
                        break
                if (gname, c_type, g_mtype) not in self._module_globals[current_mod_name]:
                    self._module_globals[current_mod_name].append((gname, c_type, g_mtype))
                    self._module_global_inits[current_mod_name][gname] = init_code
                    self._global_to_module[gname] = current_mod_name

        # Generate per-module struct typedefs and instances for globals.
        # Build into a local list and insert *before* the imported module code so that
        # imported functions referencing this module's globals (e.g. _root_globals.x) see
        # the complete struct type rather than the incomplete forward declaration.
        if self._module_globals.get(current_mod_name):
            globals_list = self._module_globals[current_mod_name]
            # Ensure module names are valid C identifiers (replace dots → underscores)
            current_mod_str = str(current_mod_name) if current_mod_name else "root"
            safe_name = _c_field_name(current_mod_str) if current_mod_str else "root"
            typedef_name = f"_{safe_name}_toplev"

            globals_struct_lines = []
            # Emit struct typedef
            globals_struct_lines.append(f"typedef struct {typedef_name} {{")
            for gname, c_type, _ in globals_list:
                globals_struct_lines.append(f"  {c_type} {_c_field_name(gname)};")
            globals_struct_lines.append(f"}} {typedef_name};")
            globals_struct_lines.append("")

            # Emit struct instance with initializers
            instance_name = f"_{safe_name}_globals"
            globals_struct_lines.append(f"struct {typedef_name} {instance_name} = {{")
            inits = self._module_global_inits.get(current_mod_name, {})

            for gname, c_type, _ in globals_list:
                init_val = inits.get(gname)
                # C struct initializers must be compile-time constants
                # Only use simple values; function calls must be deferred to runtime
                if not init_val or init_val == '0' or 'mojo_' in str(init_val) or 'new' in str(init_val):
                    # Use compile-time constant: NULL for pointers, 0 for integers
                    if c_type.endswith(' *'):
                        init_val = f'({c_type})0'
                    else:
                        init_val = '0'
                elif init_val.startswith('"') or init_val.startswith("'"):
                    # String literals are OK
                    pass
                elif init_val.lstrip('-').isdigit():
                    # Numeric literals are OK
                    pass
                else:
                    # Non-constant expression - use default null
                    if c_type.endswith(' *'):
                        init_val = f'({c_type})0'
                    else:
                        init_val = '0'
                globals_struct_lines.append(f"  .{_c_field_name(gname)} = {init_val},")
            globals_struct_lines.append("};")
            globals_struct_lines.append("")

            insert_idx = _module_globals_insert_idx
            if insert_idx is not None and insert_idx <= len(parts):
                parts[insert_idx:insert_idx] = globals_struct_lines
            else:
                parts.extend(globals_struct_lines)

        # Class-level attribute globals (class body AssignStmt not in __init__)
        class_attr_decls = []
        class_attr_inits = []
        for s in all_struct_defs:
            if isinstance(s, StructDef):
                class_attrs = getattr(self, '_class_attrs', {})
                for aname, mangled in class_attrs.get(s.name, {}).items():
                    # Find the assignment in the class body to determine value type
                    for field in s.fields:
                        if isinstance(field, AssignStmt) and isinstance(field.target, IdentExpr) and field.target.name == aname:
                            v = field.value
                            if isinstance(v, SetExpr):
                                ctype = 'MojoSet *'
                                # Build init code: create set and add elements
                                inits = [f"  {mangled} = mojo_set_new();"]
                                for elt in v.elements:
                                    if isinstance(elt, StringLiteral):
                                        inits.append(f'  mojo_set_add_str ({mangled}, "{elt.value}");')
                                    elif isinstance(elt, IntLiteral):
                                        inits.append(f'  mojo_set_add_int ({mangled}, {elt.value});')
                                class_attr_inits.extend(inits)
                            elif isinstance(v, DictExpr):
                                ctype = 'MojoDict *'
                                class_attr_inits.append(f"  {mangled} = mojo_dict_new();")
                            elif isinstance(v, (ListExpr, TupleExpr)):
                                ctype = 'MojoList *'
                                class_attr_inits.append(f"  {mangled} = mojo_list_new();")
                            elif isinstance(v, StringLiteral):
                                ctype = 'char *'
                                class_attr_inits.append(f'  {mangled} = "{v.value}";')
                            elif isinstance(v, IntLiteral):
                                ctype = 'int64_t'
                                class_attr_inits.append(f'  {mangled} = {v.value};')
                            else:
                                ctype = 'int64_t'
                            class_attr_decls.append(f"{ctype} {mangled};")
                            self._global_var_types[mangled] = ctype
                            break
        if class_attr_decls:
            parts.extend(class_attr_decls)
            parts.append('')
        # Save for use in module init
        self._class_attr_inits = class_attr_inits

        # Struct typedefs (dedup across modules, keep most complete definition)
        if self.emit_struct_defs:
            track_best = {}
            for s in (stmts + self._imported_typedef_structs
                      + (imported_stmts if self.do_imports else [])):
                if isinstance(s, StructDef):
                    field_count = len([f for f in s.fields if isinstance(f, VarDecl)])
                    if s.name not in track_best or field_count > track_best[s.name][1]:
                        track_best[s.name] = (s, field_count)

            for sd, _ in track_best.values():
                if sd.name not in self._emitted_structs:
                    if sd.name == 'Pointer':
                        parts.append('#define _MOJO_POINTER_STRUCT_DEF')
                    parts.append(f"typedef struct {sd.name} {{")
                    emitted_fields = set()
                    for field in sd.fields:
                        if isinstance(field, VarDecl):
                            # Use inferred type from struct_field_types, or resolve from annotation
                            if sd.name in self.struct_field_types and field.name in self.struct_field_types[sd.name]:
                                ft = self.struct_field_types[sd.name][field.name]
                            else:
                                ft = self._resolve_type(field.type_ann) if field.type_ann else 'int'
                            safe_fn = f'_kw_{field.name}' if (field.name in _C_KEYWORDS or field.name in _C_PARAM_EXTRA_KEYWORDS) else field.name
                            parts.append(f"  {ft} {safe_fn};")
                            emitted_fields.add(field.name)
                    # Also emit any fields that are in struct_field_types but not in AST fields
                    if sd.name in self.struct_field_types:
                        for field_name, field_type in self.struct_field_types[sd.name].items():
                            if field_name not in emitted_fields:
                                safe_fn = f'_kw_{field_name}' if (field_name in _C_KEYWORDS or field_name in _C_PARAM_EXTRA_KEYWORDS) else field_name
                                parts.append(f"  {field_type} {safe_fn};")
                    parts.append(f"}} {sd.name};")
                    parts.append('')
                    self._emitted_structs.add(sd.name)

            # Closure env struct typedefs (main module: inside emit_struct_defs block)
            for inner_map in self._all_closures.values():
                for ci in inner_map.values():
                    if ci.env_struct and ci.env_struct not in self._emitted_structs:
                        parts.append(f"typedef struct {ci.env_struct} {{")
                        for vname, vtype in ci.captures:
                            parts.append(f"  {vtype} {vname};")
                        parts.append(f"}} {ci.env_struct};")
                        parts.append('')
                        self._emitted_structs.add(ci.env_struct)

            # ── Phase C: Dispatch table typedefs (from solver) ──────────────
            # Emit vtable struct typedefs for all planned dispatch tables
            if self._dispatch_solver and self._dispatch_tables:
                for callee_set, dispatch_table in self._dispatch_tables.items():
                    if dispatch_table.name not in self._emitted_dispatch_typedefs:
                        typedef = dispatch_table.emit_typedef()
                        if typedef:
                            parts.append(typedef)
                            parts.append('')
                            self._emitted_dispatch_typedefs.add(dispatch_table.name)

        # Struct alloc helpers — __GIMPLE OK because StructName * is the return type
        # Emitted before user-function forward decls so no forward decl needed.
        for sn in sorted(self._struct_allocs_needed):
            if sn in self._emitted_allocs:
                continue  # already emitted by an imported module
            self._emitted_allocs.add(sn)
            parts.append(
                # static: each module that needs it emits its own copy; the
                # monolithic stdlib dylib compiles modules independently, so an
                # externally-linked _alloc_<sn> would collide at link time.
                f"static {sn} * __GIMPLE _alloc_{sn} (void)\n"
                f"{{\n"
                f"  {sn} * _p;\n"
                f"  void * _vp;\n"
                f"\nbb_2:\n"
                f"  _vp = malloc (sizeof({sn}));\n"
                f"  _p = ({sn} *) _vp;\n"
                f"  return _p;\n"
                f"}}"
            )
            parts.append('')

        # Forward declaration for class-attr initializer (main module only)
        if self.emit_struct_defs:
            parts.append("static void _mojo_classattr_init (void);")
            parts.append('')

        # Extern declarations: imported symbols with full parameter information
        # Skip symbols that are already hardcoded in the preamble
        hardcoded = {
            'mojo_print', 'gimple_codegen_compile_to_gimple', 'compile_to_gimple',
            'int_write', 'int_parse_module', 'tokenize', 'Parser', 'Interpreter'
        }
        # When do_imports=True, imported module code is inlined — functions will
        # have actual definitions, so extern stubs would conflict.
        if self.do_imports:
            inline_defined = set()
            for stmt in (imported_stmts or []):
                if isinstance(stmt, FunctionDef):
                    inline_defined.add(stmt.name)
                elif isinstance(stmt, StructDef):
                    for m in stmt.methods:
                        inline_defined.add(f"{stmt.name}_{m.name}")
                        inline_defined.add(m.name)
        else:
            inline_defined = set()

        # Modules that are pure-Python compiler/JIT infrastructure and are deliberately
        # NOT self-compiled (e.g. the ARM64 JIT engine). Symbols imported from them have
        # no native definition, so emit an abort stub instead of an unresolved extern,
        # letting the self-compiled binary link. These paths are never exercised in
        # compiled mode (the JIT engine only runs under the Python interpreter).
        # TODO: this is a hack. Hardcoding a stub-module allowlist and silently
        # replacing every imported symbol with a no-op stub is wrong — it papers over
        # the real gap (no native JIT engine) and will mask genuinely-missing symbols
        # from these modules. Fine for now to get self-compile to link; revisit with a
        # proper mechanism (e.g. explicit @python_only markers or compiling jit.arm64).
        _stub_only_modules = {'jit.arm64', 'jit'}
        for sym_name in sorted(self.imported_symbols.keys()):
            if sym_name in hardcoded:
                continue
            sym_info = self.imported_symbols[sym_name]
            # Skip module-level imports (import os / import re) — those become
            # int64_t global variables, not extern function declarations.
            if sym_info.get('return_type') == 'unknown':
                continue
            # Skip symbols that are defined inline (when do_imports=True)
            if sym_name in inline_defined or sym_name in self._global_inline_defs:
                continue
            # Skip struct names — they're declared as typedefs, not extern functions
            if sym_name in self.struct_field_types:
                continue
            # Skip C stdlib names declared by system headers — but only if the name is used
            # as-is (i.e., not renamed by _C_RESERVED_FUNCS). If the name IS reserved, the
            # call site uses 'mojo_<name>' (a different symbol) so we still need the extern.
            if sym_name in self._LIBC_DECLARED and sym_name not in _C_RESERVED_FUNCS:
                continue

            module = sym_info.get('module', '')
            if module in _stub_only_modules:
                # Provide a defined-but-unusable stub (plain C, like the _mojo_at_ helpers)
                # so the symbol resolves at link time.
                ret_type = sym_info.get('return_type', 'int64_t')
                ret_type = self._resolve_type(ret_type) if ret_type and ret_type != 'unknown' else 'int'
                cname = _safe_name(sym_name)
                if ret_type == 'void':
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); }}'
                else:
                    body = f'{{ mojo_print ((char *)"{sym_name}: unavailable in compiled mode"); return ({ret_type})0; }}'
                parts.append(f"{ret_type} {cname} () {body}  /* stub from {module} */")
                continue

            # _func_csym applies the overload suffix for imported Mojo functions so
            # this extern matches the defining module's mangled symbol and the call
            # sites in this module.
            safe = self._func_csym(sym_name)
            if 'signature' in sym_info:
                # For _C_RESERVED_FUNCS symbols (renamed to mojo_X), the Mojo wrapper may
                # have optional/default parameters that aren't passed at all call sites.
                # Use variadic (...) so any arity is accepted without "too few arguments".
                if sym_name in _C_RESERVED_FUNCS:
                    # Prefer c_return_type (already a C type) over return_type (Mojo type)
                    ret_type = sym_info.get('c_return_type') or sym_info.get('return_type', 'int64_t')
                    if ret_type and ret_type != 'unknown' and not any(
                            c in ret_type for c in ('*', ' ', 'int', 'char', 'void', 'float', 'double')):
                        ret_type = self._resolve_type(ret_type)
                    elif not ret_type or ret_type == 'unknown':
                        ret_type = 'int64_t'
                    parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")
                else:
                    # New format: use full signature with parameters, applying safe name
                    signature = sym_info['signature']
                    orig_name = sym_info.get('original_name', sym_name)
                    if safe != sym_name:
                        # Replace first occurrence of the bare function name with safe name
                        signature = re.sub(r'\b' + re.escape(sym_name) + r'\b', safe, signature, count=1)
                    elif orig_name != sym_name:
                        # Aliased import: signature has original name, but we expose alias name.
                        # Replace original name in signature so the extern matches the call site.
                        signature = re.sub(r'\b' + re.escape(orig_name) + r'\b', safe, signature, count=1)
                    # Strip Mojo parameter modifiers (out, inout, mut, var, etc.) from signature
                    signature = re.sub(
                        r'\b(inout|borrowed|owned|borrow|out|mut|ref|read|copy|var)\s+(?=\w)',
                        '', signature)
                    # Rename C control/storage keywords used as Mojo parameter names.
                    # Only rename non-type keywords: type keywords (void, int, char, etc.)
                    # legitimately appear as C types in extern signatures and must NOT be renamed.
                    for _ckw in ('default', 'register', 'auto', 'static', 'extern',
                                 'volatile', 'inline'):
                        signature = re.sub(r'\b' + _ckw + r'\b(?=\s*[,)])', f'_kw_{_ckw}', signature)
                    # Guard with #ifndef so C preprocessor macros (SEEK_END etc.) aren't
                    # accidentally redeclared (the macro would expand before gcc sees the decl).
                    parts.append(f"#ifndef {safe}\nextern {signature};  /* from {module} */\n#endif")
            else:
                # Legacy format fallback: use pure variadic so callers can pass any args.
                # GIMPLE mode treats () as "no params" (causing "too many args" errors),
                # so we use (...) instead which accepts any number of arguments.
                ret_type = sym_info.get('return_type', 'int64_t')
                ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
                parts.append(f"#ifndef {safe}\nextern {ret_type} {safe} (...);  /* from {module} */\n#endif")

        if self.imported_symbols:
            parts.append('')

        # Note: user-defined functions (_hash, jit_compile_and_execute, etc.) must NOT
        # be pre-registered here with guessed signatures — they get forward declarations
        # generated from their actual definitions below, and pre-registering creates
        # conflicting type errors.

        # Forward declarations: free functions (skip main — handled specially)
        func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
        for fn in func_defs:
            if fn.name == 'main':
                continue
            ret    = self.func_return_types.get(fn.name, 'int64_t')
            # If any param is *args, the call convention uses a packed MojoList*
            has_varargs = any(pn.startswith('*') for pn, _ in (fn.params or []))
            if has_varargs:
                param_ctypes = self._signature_ctypes(fn.params, fn, sentinel='MojoList *')
                self.func_param_types[fn.name] = self._signature_ctypes(fn.params, fn)
            else:
                param_ctypes = []
                inferred_params = self._inferred_param_types.get(fn.name, {}) if hasattr(self, '_inferred_param_types') else {}
                for pn, pt in (fn.params or []):
                    if pn in inferred_params:
                        param_ctypes.append(inferred_params[pn])
                    else:
                        param_ctypes.append(self._param_ctype(pn, pt, fn))
                self.func_param_types[fn.name] = param_ctypes
            ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
            # For _C_RESERVED_FUNCS (e.g. getuid → mojo_getuid), use the renamed
            # C name as the guard so the original C name's util stub is not blocked.
            # _func_csym adds the overload suffix so this forward decl matches the
            # definition and call sites.
            _c_fn_name = self._func_csym(fn.name)
            _guard_name = _c_fn_name if fn.name in _C_RESERVED_FUNCS else fn.name
            stub_guard = f'_MOJO_STUB_{_guard_name.upper()}'
            parts.append(f'#ifndef {stub_guard}')
            parts.append(f"{ret} {_c_fn_name} ({ptypes});")
            parts.append('#endif')

        # Forward declarations: struct methods
        # When do_imports=True, imported code is inlined and already contains its own
        # forward declarations — don't re-emit them with potentially stale types.
        struct_defs = [s for s in stmts if isinstance(s, StructDef)]
        if not self.do_imports:
            struct_defs += [s for s in (imported_stmts or []) if isinstance(s, StructDef)]
        for sd in struct_defs:
            # Track method counts to detect and handle overloads
            method_counts = {}
            for m in sd.methods:
                method_counts[m.name] = method_counts.get(m.name, 0) + 1

            # For each method, assign overload ID if there are multiple with same name
            method_ids = {}
            _seen_ids: dict[str, dict[str, int]] = {}  # method_name -> {id -> count}
            for m in sd.methods:
                if method_counts[m.name] > 1:
                    oid = _method_overload_id(tuple(m.params or []), sd.name, m.name)
                    seen = _seen_ids.setdefault(m.name, {})
                    count = seen.get(oid, 0)
                    seen[oid] = count + 1
                    if count > 0:
                        oid = f"{oid}_{count + 1}"
                    method_ids[id(m)] = oid
                else:
                    method_ids[id(m)] = ''

            for m in sd.methods:
                overload_suffix = method_ids.get(id(m), '')
                mangled_name = f"{sd.name}_{_safe_name(m.name)}{overload_suffix}"
                # Use per-overload key first; fall back to base name, then AST annotation
                ret = (self.func_return_types.get(f"{sd.name}_{m.name}{overload_suffix}")
                       or self.func_return_types.get(f"{sd.name}_{m.name}")
                       or self._resolve_type(m.return_type))
                method_full_name = f"{sd.name}_{m.name}"
                # Prefer param types stored during definition generation (exact match)
                per_overload_params = self.func_param_types.get(mangled_name)
                if per_overload_params is not None:
                    param_ctypes = per_overload_params
                elif any(pn.startswith('*') for pn, _ in (m.params or [])):
                    # *args method: fixed params (+ self) + MojoList*; **kwargs -> MojoDict*
                    param_ctypes = self._signature_ctypes(m.params, m, sd.name, sentinel='MojoList *')
                    self.func_param_types[method_full_name] = self._signature_ctypes(m.params, m, sd.name)
                else:
                    param_ctypes = []
                    for i, (pname, ptype) in enumerate(m.params):
                        if pname.startswith('**'):
                            continue  # skip **kwargs
                        if i == 0 and pname == 'self':
                            ct = f"{sd.name} *"
                        elif ptype is None and hasattr(self, '_inferred_param_types'):
                            if method_full_name in self._inferred_param_types and pname in self._inferred_param_types[method_full_name]:
                                ct = self._inferred_param_types[method_full_name][pname]
                            else:
                                ct = 'int64_t'
                        else:
                            ct = self._resolve_type(ptype)
                        param_ctypes.append(ct)
                ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
                parts.append(f"{ret} {mangled_name} ({ptypes});")

            # For overloaded methods, also emit a catch-all base-name decl so that
            # call sites that use the unmangled name (e.g. Slice___init__) don't fail
            # with "implicit declaration of function".
            _emitted_base: set[str] = set()
            for m in sd.methods:
                if method_ids.get(id(m), ''):  # has an overload suffix
                    base_cname = f"{sd.name}_{_safe_name(m.name)}"
                    if base_cname not in _emitted_base:
                        base_ret = (self.func_return_types.get(f"{sd.name}_{m.name}")
                                    or self._resolve_type(m.return_type))
                        parts.append(f"{base_ret} {base_cname} (...);")
                        _emitted_base.add(base_cname)

        if func_defs or struct_defs:
            parts.append('')

        # Always add forward decls for cross-module struct methods that may be called
        # (e.g. Parser_parse_module from mojo_compiler, Interpreter from myinterpreter)
        parts.append("MojoList * Parser_parse_module (Parser *);")
        parts.append("void Parser___init__ (Parser *, MojoList *);")
        parts.append("void Interpreter___init__ (Interpreter *, char *);")
        parts.append("int64_t Interpreter_execute (Interpreter *, int64_t);")
        parts.append("void jit_compile_and_execute (char *, int64_t, int64_t, int64_t);  /* from mojo.py */")
        parts.append('')

        # Forward declarations for lifted closures + env allocator helpers
        # For imported modules (emit_struct_defs=False), emit closure env struct typedefs here
        # (main module emits them inside the emit_struct_defs block above)
        if not self.emit_struct_defs:
            for inner_map in self._all_closures.values():
                for ci in inner_map.values():
                    if ci.env_struct and ci.env_struct not in self._emitted_structs:
                        parts.append(f"typedef struct {ci.env_struct} {{")
                        for vname, vtype in ci.captures:
                            parts.append(f"  {vtype} {vname};")
                        parts.append(f"}} {ci.env_struct};")
                        parts.append('')
                        self._emitted_structs.add(ci.env_struct)
        for outer_name, inner_map in self._all_closures.items():
            for inner_name, ci in inner_map.items():
                if ci.env_struct:
                    alloc_fn = f"_alloc_{ci.env_struct}"
                    parts.append(f"{ci.env_struct} * {alloc_fn} (void);")
                # Use cached types from Phase 2a if available (more accurate)
                ret  = ci.inferred_ret if ci.inferred_ret else self.func_return_types.get(ci.lifted_name, 'int64_t')
                if ci.is_re_sub_callback:
                    ret = 'char *'
                node = ci.inner_def
                ptypes_list = []
                if ci.env_struct:
                    ptypes_list.append(f"{ci.env_struct} *")
                for i, (pn, pt) in enumerate(node.params):
                    if ci.is_re_sub_callback and i == 0:
                        ptypes_list.append('char *')
                    elif pn in ci.inferred_params:
                        ptypes_list.append(ci.inferred_params[pn])
                    else:
                        ptypes_list.append(self._param_ctype(pn, pt, node))
                ptypes = ', '.join(ptypes_list) if ptypes_list else 'void'
                parts.append(f"{ret} {ci.lifted_name} ({ptypes});")
                # Emit static void* pointer for re.sub callback (avoids &func in GIMPLE)
                if ci.is_re_sub_callback:
                    static_name = f"_mojo_cb_{ci.lifted_name}"
                    # Regular C (not GIMPLE): valid function→void* assignment
                    parts.append(f"static void * {static_name} = (void *){ci.lifted_name};")
        if self._all_closures:
            parts.append('')

        # ── Static function pointer vars for builtins (avoids &func in GIMPLE) ──
        if self._funcptr_builtins_needed:
            for c_name in sorted(self._funcptr_builtins_needed):
                # Sanitize name to be valid C identifier (skip casts like ((int)0))
                if c_name and c_name[0] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_':
                    parts.append(f"static void * _funcptr_{c_name} = (void *){c_name};")
            parts.append('')

        # ── Dispatch table initializations (from Phase C) ──────────────────
        # Emit static const initializations for all planned dispatch tables
        # Only for main module (same as dispatch solving)
        if self.emit_struct_defs and self._dispatch_solver and self._dispatch_tables:
            parts.append("/* Dispatch table initializations (virtual method tables) */")
            for callee_set, dispatch_table in self._dispatch_tables.items():
                if dispatch_table.name not in self._emitted_dispatch_tables:
                    table_init = dispatch_table.emit_table_init()
                    if table_init:
                        parts.append(table_init)
                        self._emitted_dispatch_tables.add(dispatch_table.name)
            parts.append('')

        # Function bodies (generated in Phase 2a)
        # Collect string literals from all GimpleGen instances used in Phase 2a
        # and emit them as true global char arrays (required by GIMPLE strict mode)
        str_pool: dict = {}
        for attr in dir(self):
            pass  # self is the GimpleGenModule-level object, not per-function gen
        # Gather _str_pool from all lowering contexts (stored on the module gen)
        if hasattr(self, '_str_pool') and self._str_pool:
            parts.append("/* String literal globals — array form so address is a compile-time r-value (required by GIMPLE strict mode) */")
            if self.emit_str_pool:
                # String pool symbols are TU-local; static avoids duplicate-symbol
                # errors when multiple modules are compiled into the same dylib.
                # Use char* (pointer) not char[] (array): assigning a char[] to a
                # char* temp inside __GIMPLE functions triggers a GCC ICE in convert_move.
                for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                    parts.append(f'static char * {sname} = "{escaped}";')
            else:
                # Imported module: emit tentative (uninitialised) declarations.
                # C allows multiple `static T foo;` tentative definitions in one TU;
                # the main module's full `static T foo = "..."` definition wins.
                for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                    parts.append(f'static char * {sname};')
            parts.append('')
        # Also collect from func_parts generators (they share self._str_pool via gen_func)
        parts.extend(func_parts)

        # Emit class-level attribute initializer (plain C, not GIMPLE; main module only)
        if self.emit_struct_defs:
            class_attr_inits = getattr(self, '_class_attr_inits', [])
            parts.append("static void _mojo_classattr_init (void)")
            parts.append("{")
            if class_attr_inits:
                parts.extend(class_attr_inits)
            parts.append("}")
            parts.append('')

        return self._dedup_variadic_externs(parts)

    @staticmethod
    def _dedup_variadic_externs(parts: list) -> str:
        """Join the preamble, dropping a variadic `extern T name (...);` import
        declaration when a CONCRETE prototype for the same function is also present
        (e.g. an elaborated instantiation forward-declares `get_defined_int (void)`
        while the import-decl pass emits `(...)`, which GCC reports as conflicting
        types). The concrete prototype wins."""
        concrete = set()
        _decl = re.compile(r'\bextern\s+[^;()]+?\b(\w+)\s*\(([^)]*)\)\s*;')
        for p in parts:
            for mm in _decl.finditer(p):
                if mm.group(2).strip() not in ('...', ''):
                    concrete.add(mm.group(1))
        if not concrete:
            return '\n'.join(parts)
        _vardecl = re.compile(r'\bextern\s+[^;()]+?\b(\w+)\s*\(\s*\.\.\.\s*\)\s*;')
        kept = []
        for p in parts:
            mm = _vardecl.search(p)
            if mm and mm.group(1) in concrete:
                continue  # concrete prototype elsewhere supersedes this variadic
            kept.append(p)
        return '\n'.join(kept)


def compile_to_c(mojo_src: str) -> str:
    """Parse Mojo source and return C code WITHOUT __GIMPLE annotations.

    Useful for execution tests where __GIMPLE restrictions don't apply.
    """
    tokens = tokenize(mojo_src)
    stmts = Parser(tokens).parse_module()
    c_code = GimpleGen().gen_module(stmts)

    # Strip __GIMPLE annotations for executability
    c_code = c_code.replace(' __GIMPLE ', ' ')
    return c_code


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_to_gimple(mojo_src: str, do_imports: bool = False, filename: str = "") -> str:
    """Parse Mojo source and return a C string with __GIMPLE annotations.

    If do_imports=True, recursively compile imported modules and inline their code.
    If do_imports=False, imports are recorded as metadata only.
    If filename is provided, emit #line directives with the filename.

    (Kept at this exact 3-arg signature: the self-hosting bootstrap emits a
    matching forward declaration for it. Link mode is a separate entry point —
    compile_to_gimple_linked — to avoid changing this ABI.)
    """
    tokens = tokenize(mojo_src)
    stmts  = Parser(tokens).parse_module()
    gen = GimpleGen(do_imports=do_imports)
    gen._current_filename = filename
    return gen.gen_module(stmts)


def compile_to_gimple_linked(mojo_src: str, filename: str = "") -> str:
    """Like compile_to_gimple, but in *link mode*: imported symbols become
    `extern` declarations (bodies come from a linked artifact / stdlib dylib;
    see MODULE_CACHE_DESIGN.md and ABI.md) rather than being inlined."""
    return compile_linked(mojo_src, filename)[0]


def compile_linked(mojo_src: str, filename: str = "") -> tuple:
    """Link-mode compile that also returns what the driver must link: the dylibs
    `import` recorded and the object files elaboration produced (generic
    instantiations). Returns (c_code, [dylib, ...], [object, ...])."""
    tokens = tokenize(mojo_src)
    stmts  = Parser(tokens).parse_module()
    gen = GimpleGen(link_imports=True)
    gen._current_filename = filename
    code = gen.gen_module(stmts)
    return (code,
            list(dict.fromkeys(gen._link_dylibs)),
            list(dict.fromkeys(gen._link_objects)))
