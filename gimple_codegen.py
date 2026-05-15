"""GIMPLE backend for the Mojo compiler.

Consumes AST produced by mojo_compiler.py and emits C source with
__GIMPLE-annotated functions for gcc-mp-15 -fgimple.
"""
from __future__ import annotations

from mojo_compiler import (
    IntLiteral, FloatLiteral, StringLiteral, BoolLiteral, EllipsisLiteral,
    IdentExpr, BinaryOp, UnaryOp, CallExpr, MemberExpr,
    SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr,
    ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, Generator,
    VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt,
    ReturnStmt, RaiseStmt,
    BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt,
    ImportStmt, FromImportStmt,
    IfStmt, WhileStmt, ForStmt,
    FunctionDef, TryStmt, WithStmt,
    ComptimeIfStmt, ComptimeForStmt,
    StructDef, TraitDef,
    tokenize, Parser,
)
from module_loader import load_module, get_symbol_type
from generated_dispatch import (
    _SIGNED as _GD_SIGNED, _UNSIGNED as _GD_UNSIGNED, _FLOAT as _GD_FLOAT,
    _BIN_OPS as _GD_BIN_OPS, _CMP_OPS as _GD_CMP_OPS,
    _STMT_DISPATCH, _EXPR_DISPATCH,
)

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
        return 'int'

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
            return f"(int64_t)(void *){val}"
        if src == 'int64_t' and dst.endswith(' *'):
            return f"({dst}){val}"
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
                    return_type = self.func_return_types.get(callee, 'int')

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
            'Int': 'int',
            'float': 'double',
            'Float': 'double',
            'Float64': 'double',
            'bool': 'int',
            'Bool': 'int',
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

_TYPE_MAP: dict[str | None, str] = {
    'Int':    'int',
    'Int8':   'int8_t',
    'Int16':  'int16_t',
    'Int32':  'int32_t',
    'Int64':  'int64_t',
    'UInt':   'unsigned int',
    'UInt8':  'uint8_t',
    'UInt16': 'uint16_t',
    'UInt32': 'uint32_t',
    'UInt64': 'uint64_t',
    'Float16': '__fp16',
    'Float32': 'float',
    'Float64': 'double',
    'Bool':   'int',
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
    None:     'int',
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
        return 'int'
    if isinstance(ann, type):
        ann = ann.__name__
    # Handle Union types: X | Y | ... → resolve to first non-None type
    if ' | ' in ann:
        parts = [p.strip() for p in ann.split(' | ')]
        non_none = [p for p in parts if p != 'None']
        if non_none:
            return _mojo_type(non_none[0])
        return 'int'
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
        if base == 'Optional':
            return _mojo_type(inner)  # simplified: treat as the inner type
        # Unknown parameterized type — fall through to plain lookup
        ann = base
    t = _TYPE_MAP.get(ann)
    return t if t is not None else 'int'

# Keep legacy helper name for backward compat inside this file
def _result_type(t1: str, t2: str) -> str:
    return TypeLattice.join(t1, t2)

def _elem_type(ptr_type: str) -> str:
    """Strip one level of pointer to get element type."""
    if ptr_type.endswith(' *'):
        return ptr_type[:-2]
    if '*' in ptr_type:
        return ptr_type.replace('*', '').strip()
    return 'int'

_C_ID_MAP = {'char *': 'charptr', 'void *': 'voidptr', '_Bool': 'bool'}

def _c_id(ctype: str) -> str:
    """Convert a C type to a valid identifier suffix (for helper function names)."""
    return _C_ID_MAP.get(ctype, ctype.replace(' ', '_').replace('*', 'ptr'))

def _printf_fmt(ctype: str) -> str:
    return TypeLattice.printf_fmt(ctype)

# ---------------------------------------------------------------------------
# Operator tables  (imported from generated_dispatch.py)
# ---------------------------------------------------------------------------

_BIN_OPS  = _GD_BIN_OPS   # Mojo op → C infix op; **, //, @ handled separately
_CMP_OPS  = _GD_CMP_OPS   # operators whose result type is _Bool

# ---------------------------------------------------------------------------
# C keyword avoidance
# ---------------------------------------------------------------------------

_C_KEYWORDS = frozenset({
    'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do',
    'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if',
    'inline', 'int', 'long', 'register', 'restrict', 'return', 'short',
    'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union',
    'unsigned', 'void', 'volatile', 'while',
    '_Bool', '_Complex', '_Imaginary', '_Alignas', '_Alignof', '_Atomic',
    '_Generic', '_Noreturn', '_Static_assert', '_Thread_local',
})

def _safe_name(name: str) -> str:
    return f"mojo_{name}" if name in _C_KEYWORDS else name

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
            result.add(tgt if isinstance(tgt, str) else tgt.name)
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
static int __mojo_floordiv (int a, int b)
{
  int q = a / b;
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
    }

    def __init__(self, do_imports: bool = False, emit_str_pool: bool = True, emit_struct_defs: bool = True):
        self.do_imports = do_imports
        self.emit_str_pool = emit_str_pool      # only main module emits string pool; imported modules skip it
        self.emit_struct_defs = emit_struct_defs  # only main module emits struct typedefs; imported modules skip it
        self.func_return_types: dict[str, str] = {}
        self.struct_field_types: dict[str, dict[str, str]] = {}
        self.imported_symbols: dict[str, tuple] = {}  # symbol_name -> (module, orig_name, type)
        self._all_closures: dict = {}   # populated by gen_module pre-pass
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
        self._actual_types: dict[str, str] = {}      # var_name -> actual type (for int64_t-stored pointers)
        self._global_var_types: dict[str, str] = {}  # module-level global name -> C type (persists across functions)
        self._global_c_decl_types: dict[str, str] = {}  # global name -> actual C declaration type (int64_t or pointer)
        # Phase C: Dispatch solver for static dispatch table planning
        self._dispatch_solver: DispatchSolver | None = None  # Instantiated in gen_module Phase 1.5
        self._dispatch_tables: dict = {}  # dispatch_table_name → DispatchTable (from _dispatch_solver)
        self._emitted_dispatch_typedefs: set[str] = set()  # Track typedef names already emitted
        self._emitted_dispatch_tables: set[str] = set()    # Track table names already emitted
        self._funcptr_builtins_needed: set[str] = set()    # builtin C names needing static void* vars
        self._reset_func()

    def _reset_func(self):
        self.bb_counter   = 2
        self.temp_counter = 0
        self.decls:       list[str]         = []
        self.body_lines:  list[str]         = []
        # Pre-register known module-level global dicts to avoid opaque-int coercion
        self.var_types:   dict[str, str]    = {
            '_BIN_OPS': 'MojoDict *',
            '_GD_BIN_OPS': 'MojoDict *',
        }
        self.loop_stack:  list[tuple[str,str]] = []
        self.exc_depth    = 0
        self.func_ret_type: str             = ''
        self._last_was_terminal: bool       = False
        # Container / layout state
        self._elem_types:      dict[str, str]   = {}  # container var → element C type
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

    def _compile_imported_module(self, module_name: str) -> tuple:
        """Find and compile an imported .mojo module, extracting type information.

        Returns (code: str, stmts: list) where stmts are parsed statements from the module.
        """
        import os
        import sys
        import pathlib
        import re
        import traceback

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

        for path in mojo_paths:
            if os.path.exists(path):
                modules_before = set(self._compiled_modules)
                try:
                    with open(path, 'r') as f:
                        source = f.read()

                    # Compile the module to get both code and type info
                    tokens = tokenize(source)
                    stmts = Parser(tokens).parse_module()

                    # Create a temporary codegen to extract types
                    # Use do_imports=True for transitive closure; share dedup sets and type information
                    # emit_str_pool=False so only main module emits the shared string pool
                    # emit_struct_defs=True but share _emitted_structs to dedup struct definitions
                    temp_gen = GimpleGen(do_imports=True, emit_str_pool=False, emit_struct_defs=False)
                    temp_gen._compiled_modules = self._compiled_modules
                    temp_gen._emitted_structs = self._emitted_structs
                    temp_gen._str_pool = self._str_pool
                    temp_gen.struct_field_types = self.struct_field_types
                    temp_gen._global_var_types = self._global_var_types
                    temp_gen._global_c_decl_types = self._global_c_decl_types
                    temp_gen._emitted_ptr_helpers = self._emitted_ptr_helpers
                    temp_gen._global_inline_defs = self._global_inline_defs
                    temp_gen._emitted_allocs = self._emitted_allocs
                    temp_gen._module_stmts = self._module_stmts  # share: track all transitive stmts
                    temp_gen.func_return_types = self.func_return_types  # share across gens
                    code = temp_gen.gen_module(stmts)

                    # Store parsed stmts for this module so parent gens can access them
                    self._module_stmts[module_name] = stmts

                    # Return both code and parsed statements
                    return (code, stmts)
                except Exception as e:
                    __import__('sys').stderr.write(f"# ERROR: compiling imported module {module_name!r} from {path}: {e}\n")
                    # Rollback: remove any modules that were added during this failed compilation
                    # so the outer module can re-compile them and include their code.
                    for _m in list(self._compiled_modules - modules_before):
                        self._compiled_modules.discard(_m)
                    continue

        # Module not found (e.g. stdlib module like sys, os)
        return (None, [])

    def _new_bb(self) -> str:
        self.bb_counter += 1
        return f"bb_{self.bb_counter}"

    def _new_temp(self, ctype: str) -> str:
        self.temp_counter += 1
        name = f"_t{self.temp_counter}"
        self.decls.append(f"  {ctype} {name};")
        self.var_types[name] = ctype
        return name

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
        return self.var_types.get(name, 'int')

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
        'mojo_str':              ('char *',    ['void *']),
        'mojo_repr':             ('char *',    ['int']),  # expects int, not void*
        'mojo_print':            ('void',      ['char *']),
        'mojo_open_file':        ('int64_t',   ['char *']),  # Added: returns handle, takes path
        'mojo_close':            ('void',      ['void *']),
        'mojo_write':            ('int64_t',   ['void *', 'char *', 'int64_t']),
        'mojo_read':             ('int64_t',   ['void *', 'char *', 'int64_t']),
        'int64_t_basename':      ('char *',    ['char *']),  # os.path.basename(path)
        'int64_t_splitext':      ('char *',    ['char *']),  # os.path.splitext(path)
        'mojo_make_int':         ('int64_t',    ['char *']),
        'mojo_make_float':       ('double',     ['char *']),
        'mojo_list_new':         ('MojoList *', []),
        'mojo_list_append_int':  ('void',      ['MojoList *', 'int64_t']),
        'mojo_list_append_str':  ('void',      ['MojoList *', 'char *']),
        'mojo_list_append_obj':  ('void',      ['MojoList *', 'void *']),
        'mojo_list_get_int':     ('int64_t',   ['MojoList *', 'int64_t']),
        'mojo_list_get_str':     ('char *',    ['MojoList *', 'int64_t']),
        'mojo_list_len':         ('int64_t',   ['MojoList *']),
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
    }

    def _emit_call(self, ret_type: str, result_var: str, fname: str, arg_pairs: list) -> None:
        """Emit a function call with GIMPLE-valid argument coercions.

        arg_pairs: list of (ctype, varname) for each argument.
        For each argument, if the declared parameter type differs from the
        passed type, emit an intermediate temp with the correct cast.
        """
        sig = self._KNOWN_SIGS.get(fname)
        param_types = sig[1] if sig else self.func_param_types.get(fname, [])
        coerced_args = []
        for i, (atype, aval) in enumerate(arg_pairs):
            ptype = param_types[i] if i < len(param_types) else atype
            # GIMPLE: extern globals must be loaded into locals before function calls
            # This includes string literals (_slit_*) and dict globals (_BIN_OPS, etc.)
            if aval.startswith('_slit_') or aval in ('_BIN_OPS', '_GD_BIN_OPS'):
                temp = self._new_temp(atype)
                self._emit(f'  {temp} = {aval};')
                aval = temp
            elif aval.startswith('"') and aval.endswith('"'):
                # Raw C string literal in GIMPLE call — convert to _slit_ variable
                slit_name = self._str_literal_to_slit(aval)
                temp = self._new_temp('char *')
                self._emit(f'  {temp} = {slit_name};')
                aval = temp
            if ptype == atype or ptype == '...':
                coerced_args.append(aval)
            elif ptype == 'void *' and atype in ('int', 'int64_t', '_Bool'):
                ip = self._new_temp('int64_t')
                vp = self._new_temp('void *')
                self._emit(f'  {ip} = (int64_t){aval};')
                self._emit(f'  {vp} = (void *){ip};')
                coerced_args.append(vp)
            elif ptype == 'void *' and atype.endswith(' *'):
                vp = self._new_temp('void *')
                self._emit(f'  {vp} = (void *){aval};')
                coerced_args.append(vp)
            elif ptype == 'int64_t' and (atype in ('int', '_Bool', 'char *', 'void *') or atype.endswith(' *')):
                ct = self._new_temp('int64_t')
                if atype == 'char *':
                    aval_local = self._ensure_local('char *', aval)
                    ip2 = self._new_temp('void *')
                    self._emit(f'  {ip2} = (void *){aval_local};')
                    self._emit(f'  {ct} = (int64_t){ip2};')
                elif atype == 'void *':
                    aval_local = self._ensure_local('void *', aval)
                    self._emit(f'  {ct} = (int64_t){aval_local};')
                elif atype.endswith(' *'):
                    # Any struct pointer → void * → int64_t
                    aval_local = self._ensure_local(atype, aval)
                    vp = self._new_temp('void *')
                    self._emit(f'  {vp} = (void *){aval_local};')
                    self._emit(f'  {ct} = (int64_t){vp};')
                else:
                    self._emit(f'  {ct} = (int64_t){aval};')
                coerced_args.append(ct)
            elif ptype == 'char *' and atype in ('int', 'int64_t', 'char'):
                vp = self._new_temp('void *')
                cp = self._new_temp('char *')
                if atype in ('int', 'char'):
                    ip = self._new_temp('int64_t')
                    self._emit(f'  {ip} = (int64_t){aval};')
                    self._emit(f'  {vp} = (void *){ip};')
                else:
                    self._emit(f'  {vp} = (void *){aval};')
                self._emit(f'  {cp} = (char *){vp};')
                coerced_args.append(cp)
            elif ptype.endswith(' *') and atype in ('int', 'int64_t'):
                ip3 = self._new_temp('int64_t')
                pp = self._new_temp(ptype)
                self._emit(f'  {ip3} = (int64_t){aval};')
                self._emit(f'  {pp} = ({ptype}){ip3};')
                coerced_args.append(pp)
            elif ptype == 'int' and atype in ('int64_t', '_Bool'):
                ct = self._new_temp('int')
                self._emit(f'  {ct} = (int){aval};')
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
                cp = self._new_temp('char *')
                self._emit(f'  {cp} = (char *){aval};')
                coerced_args.append(cp)
            elif ptype == 'void *' and atype == 'char *':
                # char* to void* conversion
                vp = self._new_temp('void *')
                self._emit(f'  {vp} = (void *){aval};')
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
            else:
                coerced_args.append(aval)
        args_str = ', '.join(coerced_args)
        if result_var:
            self._emit(f'  {result_var} = {fname} ({args_str});')
        else:
            self._emit(f'  {fname} ({args_str});')

    def _ensure_local(self, ctype: str, val: str) -> str:
        """If val is a global variable (not a local temp or constant), load it into
        a local temp first.  GIMPLE requires all cast/unary operands to be registers."""
        is_local = (val.startswith('_t') or val.startswith('"') or val.startswith("'")
                    or val.lstrip('-').replace('.', '', 1).isdigit())
        if is_local:
            return val
        t = self._new_temp(ctype)
        self._emit(f'  {t} = {val};')
        return t

    def _safe_coerce_emit(self, src: str, dst: str, val: str, lhs: str) -> None:
        """Emit `lhs = val` coercing src→dst; routes struct-field LHS and literal RHS
        through register temps as required by GIMPLE."""
        is_field = '->' in lhs
        val_is_literal = val.startswith('"') or val.startswith("'") or (
            val.lstrip('-').replace('.','',1).isdigit() and val not in ('0','1','2','3','4','5','6','7','8','9'))
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
                    vp = self._new_temp('void *')
                    self._emit(f'  {vp} = (void *){v};')
                    v = vp
                ip = self._new_temp('int64_t')
                self._emit(f'  {ip} = (int64_t){v};')
                if d == 'int64_t':
                    self._emit(f'  {dest} = {ip};')
                else:
                    self._emit(f'  {dest} = (int){ip};')
            elif d.endswith(' *') and s in ('int', 'int64_t'):
                ip = self._new_temp('int64_t')
                self._emit(f'  {ip} = (int64_t){v};')
                self._emit(f'  {dest} = ({d}){ip};')
            else:
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

            def scan_expr(expr):
                """Recursively scan an expression."""
                if isinstance(expr, MemberExpr):
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
            return accessed_fields, function_calls

        # For each parameter without a type annotation, infer from usage
        for pname, ptype in func.params:
            if ptype is None:
                fields_accessed, function_calls = analyze_param_usage(func.body, pname)

                # If passed to isinstance() as first arg, it's polymorphic → keep as int64_t
                is_polymorphic = any(
                    fn == 'isinstance' and ai == 0
                    for fn, ai in function_calls
                )
                if is_polymorphic:
                    continue  # leave as int64_t (default for unannotated)

                # First, try to infer from function calls
                if function_calls:
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
            # Rename C keywords to avoid conflicts (e.g. 'default' → '_default')
            c_name = f"_{name}" if name in _C_KEYWORDS else name
            if c_name != name:
                self._c_names[name] = c_name
            self.decls.append(f"  {ctype} {c_name};")
            self.var_types[name] = ctype
        if elem is not None:
            self._elem_types[name] = elem

    def _cname(self, name: str) -> str:
        """Translate a Python variable name to its C name (handles C keyword renaming)."""
        return self._c_names.get(name, name)

    def _new_jbp_temp(self) -> str:
        self.temp_counter += 1
        name = f"_jbp{self.temp_counter}"
        self.decls.append(f"  jmp_buf *{name};")
        return name

    # ── Type-inference pre-pass helpers ──────────────────────────────────

    def _quick_type(self, node) -> str:
        """Estimate C type of an expression without emitting code."""
        if isinstance(node, IntLiteral):    return 'int'
        if isinstance(node, FloatLiteral):  return 'double'
        if isinstance(node, BoolLiteral):   return '_Bool'
        if isinstance(node, StringLiteral): return 'char *'
        if isinstance(node, IdentExpr):     return self.var_types.get(node.name, 'int')
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
            fname = node.func.name
            _BUILTIN_CTORS = {'set': 'MojoSet *', 'dict': 'MojoDict *', 'list': 'MojoList *'}
            if fname in _BUILTIN_CTORS:
                return _BUILTIN_CTORS[fname]
            if fname in self.struct_field_types:
                return f'{fname} *'
            return self.func_return_types.get(fname, 'int')
        if isinstance(node, CallExpr) and isinstance(node.func, MemberExpr):
            # Module method calls: re.sub → char *, str.join → char *, etc.
            if isinstance(node.func.obj, IdentExpr):
                mod = node.func.obj.name
                meth = node.func.member
                if mod == 're' and meth == 'sub':    return 'char *'
                if mod == 're' and meth == 'match':  return 'int'
                if mod == 're' and meth == 'search': return 'int'
                if mod == 'os' and meth in ('getcwd', 'path'): return 'char *'
                if mod == 'sys': return 'int'
                # Try as struct instance method call: resolve receiver type then look up mangled name
                ot = self.var_types.get(mod, '')
                if ot and ot.endswith(' *'):
                    sn = ot.replace(' *', '').strip()
                    mangled = f"{sn}_{meth}"
                    rt = self.func_return_types.get(mangled)
                    if rt:
                        return rt
        if isinstance(node, MemberExpr):
            ot = self._quick_type(node.obj)
            sn = ot.replace(' *', '').strip()
            return self.struct_field_types.get(sn, {}).get(node.member, 'int')
        if isinstance(node, ListExpr):  return 'MojoList *'
        if isinstance(node, DictExpr):  return 'MojoDict *'
        if isinstance(node, SetExpr):   return 'MojoSet *'
        if isinstance(node, TupleExpr): return 'MojoList *'
        return 'int'

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

    # ── Expression lowering ───────────────────────────────────────────────

    def lower_expr(self, node) -> tuple[str, str]:
        """Return (ctype, simple_rvalue). May emit temp assignments."""
        handler_name = _EXPR_DISPATCH.get(type(node).__name__)
        if handler_name:
            return getattr(self, handler_name)(node)
        self._emit(f"  /* TODO: unknown expr {type(node).__name__} */")
        t = self._new_temp('int')
        self._emit(f"  {t} = 0;")
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
            escaped = (val.replace('\\', '\\\\')
                           .replace('"', '\\"')
                           .replace('\n', '\\n')
                           .replace('\r', '\\r')
                           .replace('\t', '\\t'))
            # GIMPLE: char[] literal can't directly assign to char* in __GIMPLE functions.
            # Register in the module-level string pool (emitted as C global char arrays).
            if escaped not in self._str_pool:
                # Start at 10000 to avoid collisions with mojo compiler's string numbering
                slit_num = 10000 + len(self._str_pool)
                self._str_pool[escaped] = f'_slit_{slit_num}'
            sname = self._str_pool[escaped]
            return 'char *', sname
        # F-string: for now, just extract literal parts and return as plain string
        # Full f-string formatting with snprintf requires static buffers, which aren't allowed in __GIMPLE
        parts = self._parse_fstring_parts(val)
        if not parts or all(k == 'lit' for k, _ in parts):
            plain = ''.join(v for _, v in parts)
            escaped = plain.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
            # Must go through string pool — inline char[] literals cause GIMPLE errors
            if escaped not in self._str_pool:
                slit_num = 10000 + len(self._str_pool)
                self._str_pool[escaped] = f'_slit_{slit_num}'
            return 'char *', self._str_pool[escaped]

        # For f-strings with expressions: build a concatenation of all parts
        # Lower each expression part and concatenate via mojo_str_cat
        acc_val = None
        for kind, text in parts:
            if kind == 'lit':
                if not text:
                    continue
                esc = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
                if esc not in self._str_pool:
                    self._str_pool[esc] = f'_slit_{10000 + len(self._str_pool)}'
                part_t = self._new_temp('char *')
                self._emit(f'  {part_t} = {self._str_pool[esc]};')
                part_val = part_t
            else:
                # Expression: try to evaluate and convert to char*
                try:
                    from mojo_compiler import Parser as _P, tokenize as _tok
                    expr_node = _P(_tok(text)).parse_expr()
                    et, ev = self.lower_expr(expr_node)
                    if et == 'char *':
                        part_val = ev
                    else:
                        str_t = self._new_temp('char *')
                        self._emit_call('char *', str_t, 'mojo_str', [(et, ev)])
                        part_val = str_t
                except Exception:
                    # If expression fails, skip this part
                    continue
            if acc_val is None:
                acc_val = part_val
            else:
                cat_t = self._new_temp('char *')
                self._emit(f'  {cat_t} = mojo_str_cat ({acc_val}, {part_val});')
                acc_val = cat_t
        if acc_val is None:
            placeholder = '<formatted>'
            if placeholder not in self._str_pool:
                self._str_pool[placeholder] = f'_slit_{10000 + len(self._str_pool)}'
            acc_val_t = self._new_temp('char *')
            self._emit(f'  {acc_val_t} = {self._str_pool[placeholder]};')
            return 'char *', acc_val_t
        return 'char *', acc_val

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
        escaped = (val.replace('\\', '\\\\')
                       .replace('"', '\\"')
                       .replace('\n', '\\n')
                       .replace('\r', '\\r')
                       .replace('\t', '\\t'))
        
        # Register in the module-level string pool if not already present
        if escaped not in self._str_pool:
            slit_num = 10000 + len(self._str_pool)
            self._str_pool[escaped] = f'_slit_{slit_num}'
        
        return self._str_pool[escaped]

    def _lower_IdentExpr(self, node) -> tuple[str, str]:
        name = node.name
        if name == 'None':  return 'int', '0'
        if name == 'True':  return 'int', '1'
        if name == 'False': return 'int', '0'
        if name == '__file__':
            escaped = '<bootstrap>'
            if escaped not in self._str_pool:
                self._str_pool[escaped] = f'_slit_{10000 + len(self._str_pool)}'
            t = self._new_temp('char *')
            self._emit(f'  {t} = {self._str_pool[escaped]};')
            return 'char *', t
        if name == '__name__':
            escaped = '__main__'
            if escaped not in self._str_pool:
                self._str_pool[escaped] = f'_slit_{10000 + len(self._str_pool)}'
            t = self._new_temp('char *')
            self._emit(f'  {t} = {self._str_pool[escaped]};')
            return 'char *', t
        if name in self._captures and self._env_param:
            ctype = self._captures[name]
            t = self._new_temp(ctype)
            self._emit(f'  {t} = {self._env_param}->{name};')
            return ctype, t
        # Struct/class type name used as a value (e.g. cls arg) — return zero placeholder
        if name in self.struct_field_types and name not in self.var_types:
            t = self._new_temp('int')
            self._emit(f'  {t} = 0;  /* class ref {name} as value */')
            return 'int', t
        # Python builtin used as a value (e.g. passed to scope.define) — map to C function pointer
        if name in self.BUILTIN_VALUE_MAP and name not in self.var_types:
            c_name = self.BUILTIN_VALUE_MAP[name]
            # Use a pre-declared static void* (emitted in non-GIMPLE context) to avoid
            # the invalid `&func_name` syntax that GIMPLE strict mode rejects.
            self._funcptr_builtins_needed.add(c_name)
            static_name = f'_funcptr_{c_name}'
            t = self._new_temp('void *')
            self._emit(f'  {t} = {static_name};')
            return 'void *', t
        # C function name used as a value (e.g. tokenize, MojoParser passed to Scope_define).
        # Can't use a function name as rvalue in GIMPLE — use a pre-declared static void*.
        if (name in self.func_return_types and name not in self.var_types
                and name not in self.struct_field_types and name not in self._global_var_types):
            c_name = self._c_names.get(name, _safe_name(name))
            self._funcptr_builtins_needed.add(c_name)
            static_name = f'_funcptr_{c_name}'
            t = self._new_temp('void *')
            self._emit(f'  {t} = {static_name};')
            return 'void *', t
        # Module-level global variable (persistent type known across functions)
        if name not in self.var_types and name in self._global_var_types:
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
            if ctype == 'int64_t' and c_decl_type.endswith(' *'):
                # Global is declared as a pointer type at C level but we box it as int64_t.
                # GIMPLE: must load pointer into matching-type local, then cast via void* → int64_t.
                raw_ptr = self._new_temp(c_decl_type)
                self._emit(f'  {raw_ptr} = {name};')
                vp = self._new_temp('void *')
                self._emit(f'  {vp} = (void *){raw_ptr};')
                self._emit(f'  {t} = (int64_t){vp};')
            else:
                # Global is int64_t or same type as ctype — direct assignment is valid.
                self._emit(f'  {t} = {name};')
            return ctype, t
        return self._type_of(name), self._c_names.get(name, name)

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
                zero = self._new_temp('int64_t')
                self._emit(f"  {zero} = (int64_t)0;")
                self._emit(f"  {t} = {ov} == {zero};")
            elif ot == '_Bool':
                # GIMPLE: both operands of comparison must have same type
                # Cast _Bool to int before comparing with integer 0
                int_t = self._new_temp('int')
                self._emit(f"  {int_t} = (int){ov};")
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
                elem_type = ot[:-2].strip() or 'int'
                t = self._new_temp(elem_type)
                self._emit(f"  {t} = *{ov};")
                return elem_type, t
            else:
                # int typed as pointer — can't safely dereference; return as-is
                return ot, ov
        if node.op == '+':
            return ot, ov
        c_op = {'-': '-', '~': '~'}.get(node.op, node.op)
        t = self._new_temp(ot)
        self._emit(f"  {t} = {c_op}{ov};")
        return ot, t

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
                zero = self._new_temp('int64_t')
                self._emit(f"  {zero} = (int64_t)0;")
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
            tv_tmp = self._new_temp('char *')
            self._emit(f'  {tv_tmp} = {tv};')
            tv = tv_tmp
        if res_type == 'char *' and ev.startswith('_slit_'):
            ev_tmp = self._new_temp('char *')
            self._emit(f'  {ev_tmp} = {ev};')
            ev = ev_tmp
        t = self._new_temp(res_type)
        self._emit(f"  {t} = {cv} ? {tv} : {ev};")
        return res_type, t

    def _lower_MemberExpr(self, node) -> tuple[str, str]:
        # Check if obj is a simple identifier (module access)
        if isinstance(node.obj, IdentExpr):
            module_name = node.obj.name
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

        ot, ov = self.lower_expr(node.obj)

        # If the object lowered to a C type name (class used as cls argument),
        # treat it as NULL — the method shouldn't use cls for value access
        if ov in self.struct_field_types and ot == 'int':
            null_tmp = self._new_temp('int')
            self._emit(f"  {null_tmp} = 0;  /* class ref {ov} as NULL */")
            ov = null_tmp


        # Special handling for .__name__ on type objects
        if node.member == '__name__':
            struct_name_check = ot.replace(' *', '').strip()
            if struct_name_check not in self.struct_field_types:
                t = self._new_temp('char *')
                escaped = '<type>'
                if escaped not in self._str_pool:
                    self._str_pool[escaped] = f'_slit_{10000 + len(self._str_pool)}'
                self._emit(f'  {t} = {self._str_pool[escaped]};  /* {ot}.__name__ stubbed */')
                return 'char *', t

        # Special handling for .__dict__ on int objects (node variable)
        if node.member == '__dict__' and ot == 'int':
            t = self._new_temp('int')
            self._emit(f'  {t} = 0;  /* __dict__ stub */')
            return 'int', t

        op = '->' if '*' in ot else '.'
        struct_name = ot.replace(' *', '').strip()
        field_map = self.struct_field_types.get(struct_name, {})
        if node.member in field_map:
            field_type = field_map[node.member]
            t = self._new_temp(field_type)
            self._emit(f'  {t} = {ov}{op}{node.member};')
            return field_type, t
        # Class-level attribute (not an instance field) — redirect to global variable
        class_attrs = getattr(self, '_class_attrs', {})
        if struct_name in class_attrs and node.member in class_attrs[struct_name]:
            gname = class_attrs[struct_name][node.member]
            # Use the actual declared type of the global (stored in _global_var_types)
            gtype = self._global_var_types.get(gname, 'int64_t')
            t = self._new_temp(gtype)
            self._emit(f'  {t} = {gname};')
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
                cast_t = self._new_temp(f'{alt_struct} *')
                self._emit(f'  {cast_t} = ({alt_struct} *){ov};')
                t = self._new_temp(field_type)
                self._emit(f'  {t} = {cast_t}->{node.member};')
            else:
                # Fall back: assume pointer to same struct type
                field_type = struct_name + ' *'
                t = self._new_temp(field_type)
                self._emit(f'  {t} = {ov}{op}{node.member};')
            return field_type, t
        elif ot in ('int', 'int64_t'):
            # Opaque Python object typed as int — use runtime attribute accessor
            # GIMPLE requires function args to be simple vars, not cast expressions
            t = self._new_temp('int64_t')
            self._emit_call('int64_t', t, 'mojo_obj_getattr',
                            [(ot, ov), ('char *', f'"{node.member}"')])
            return 'int64_t', t
        else:
            # Unknown struct field — fall back
            # If the object is a pointer type, assume the field is also a pointer
            if '*' in ot:
                field_type = struct_name + ' *'
            else:
                field_type = 'int'
            t = self._new_temp(field_type)
            self._emit(f'  {t} = {ov}{op}{node.member};')
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
                sn = ot.replace(' *', '').strip()
                field_type = self.struct_field_types.get(sn, {}).get(node.left.member, vtype)
                self._safe_coerce_emit(vtype, field_type, vv, f"{ov}{op}{node.left.member}")
                return field_type, vv
            if isinstance(node.left, SubscriptExpr):
                ot, obj_v = self.lower_expr(node.left.obj)
                _, idx_v = self.lower_expr(node.left.index)
                if ot == 'MojoList *':
                    elem = self._elem_of(obj_v)
                    suf  = TypeLattice.list_suffix(elem)
                    idx64 = self._new_temp('int64_t')
                    self._emit(f"  {idx64} = (int64_t) {idx_v};")
                    ev_cast = self._cast_for_list(vtype, vv, suf)
                    self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
                else:
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
            lcast = self._new_temp('_Bool')
            if ltype in ('char *', 'void *') or (ltype.endswith(' *') and ltype != '_Bool'):
                _ip = self._new_temp('int64_t'); _z = self._new_temp('int64_t')
                lval_local = self._ensure_local(ltype, lval)
                _vp = self._new_temp('void *')
                self._emit(f'  {_vp} = (void *){lval_local};')
                self._emit(f'  {_ip} = (int64_t){_vp};')
                self._emit(f'  {_z} = (int64_t)0;')
                self._emit(f'  {lcast} = {_ip} != {_z};')
            elif ltype == 'int64_t':
                _z = self._new_temp('int64_t')
                self._emit(f'  {_z} = (int64_t)0;')
                self._emit(f'  {lcast} = {lval} != {_z};')
            elif ltype == '_Bool':
                self._emit(f'  {lcast} = {lval};')
            else:
                # Use int64_t intermediary to avoid GIMPLE type-mismatch errors
                # when the variable's actual C type (int64_t, etc.) differs from 'int'.
                _lv64 = self._new_temp('int64_t')
                _z64 = self._new_temp('int64_t')
                self._emit(f'  {_lv64} = (int64_t){lval};')
                self._emit(f'  {_z64} = (int64_t)0;')
                self._emit(f'  {lcast} = {_lv64} != {_z64};')
            self._emit(f'  {result} = {lcast};')
            if node.op == 'and':
                self._emit(f'  if ({lcast}) goto {bb_right}; else goto {bb_merge};')
            else:
                self._emit(f'  if ({lcast}) goto {bb_merge}; else goto {bb_right};')
            self._emit_label(bb_right)
            rtype, rval = self.lower_expr(node.right)
            rcast = self._new_temp('_Bool')
            if rtype in ('char *', 'void *') or (rtype.endswith(' *') and rtype != '_Bool'):
                _ip = self._new_temp('int64_t'); _z = self._new_temp('int64_t')
                rval_local = self._ensure_local(rtype, rval)
                _vp = self._new_temp('void *')
                self._emit(f'  {_vp} = (void *){rval_local};')
                self._emit(f'  {_ip} = (int64_t){_vp};')
                self._emit(f'  {_z} = (int64_t)0;')
                self._emit(f'  {rcast} = {_ip} != {_z};')
            elif rtype == 'int64_t':
                _z = self._new_temp('int64_t')
                self._emit(f'  {_z} = (int64_t)0;')
                self._emit(f'  {rcast} = {rval} != {_z};')
            elif rtype == '_Bool':
                self._emit(f'  {rcast} = {rval};')
            else:
                _rv64 = self._new_temp('int64_t')
                _z64r = self._new_temp('int64_t')
                self._emit(f'  {_rv64} = (int64_t){rval};')
                self._emit(f'  {_z64r} = (int64_t)0;')
                self._emit(f'  {rcast} = {_rv64} != {_z64r};')
            self._emit(f'  {result} = {rcast};')
            self._emit(f'  goto {bb_merge};')
            self._emit_label(bb_merge)
            return '_Bool', result

        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)

        # MojoList + MojoList → mojo_list_concat
        if node.op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
            t = self._new_temp('MojoList *')
            self._emit(f"  {t} = mojo_list_concat ({lv}, {rv});")
            if lv in self._elem_types:
                self._elem_types[t] = self._elem_types[lv]
            return 'MojoList *', t

        # MojoList * + int/int64_t → identity (DynamicVector not supported; treat as no-op)
        if node.op == '+' and lt == 'MojoList *' and rt in ('int', 'int64_t'):
            return 'MojoList *', lv

        # MojoStr + MojoStr → mojo_str_concat
        if node.op == '+' and lt == 'MojoStr *' and rt == 'MojoStr *':
            t = self._new_temp('MojoStr *')
            self._emit(f"  {t} = mojo_str_concat ({lv}, {rv});")
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
                ip = self._new_temp('int64_t')
                self._emit(f"  {ip} = (int64_t){val};")
                self._emit(f"  {cp} = (char *){ip};")
                return 'char *', cp
            # If one operand is definitely a string literal, treat int as potential string
            if is_string_literal and typ in ('int', 'int64_t') and val.startswith('_slit_'):
                cp = self._new_temp('char *')
                ip = self._new_temp('int64_t')
                self._emit(f"  {ip} = (int64_t){val};")
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
                t = self._new_temp('char *')
                self._emit_call('char *', t, 'mojo_str_cat', [('char *', lv2), ('char *', rv2)])
                return 'char *', t
            # int/int64_t + char* or char* + int/int64_t when one side is a string literal
            # → this is Python string concatenation where one operand is a string stored as int
            if right_is_lit and rt == 'char *' and lt in ('int', 'int64_t'):
                ip = self._new_temp('int64_t')
                cp = self._new_temp('char *')
                self._emit(f'  {ip} = (int64_t){lv};')
                self._emit(f'  {cp} = (char *){ip};')
                t = self._new_temp('char *')
                self._emit_call('char *', t, 'mojo_str_cat', [('char *', cp), ('char *', rv)])
                return 'char *', t
            if left_is_lit and lt == 'char *' and rt in ('int', 'int64_t'):
                ip = self._new_temp('int64_t')
                cp = self._new_temp('char *')
                self._emit(f'  {ip} = (int64_t){rv};')
                self._emit(f'  {cp} = (char *){ip};')
                t = self._new_temp('char *')
                self._emit_call('char *', t, 'mojo_str_cat', [('char *', lv), ('char *', cp)])
                return 'char *', t

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
            cnt = self._new_temp('int64_t')
            self._emit(f"  {cnt} = (int64_t){rv};")
            t = self._new_temp('MojoList *')
            self._emit_call('MojoList *', t, 'mojo_list_repeat', [('MojoList *', lv), ('int64_t', cnt)])
            return 'MojoList *', t

        # MojoStr == / != → mojo_str_eq
        if node.op in ('==', '!=') and lt == 'MojoStr *' and rt == 'MojoStr *':
            eq_t = self._new_temp('int')
            self._emit(f"  {eq_t} = mojo_str_eq ({lv}, {rv});")
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
                    ip = self._new_temp('int64_t'); cp = self._new_temp('char *')
                    self._emit(f'  {ip} = (int64_t){var};')
                    self._emit(f'  {cp} = (char *){ip};')
                    return cp
                ls = _to_char_star(lt, lv)
                rs = _to_char_star(rt, rv)
                eq_t = self._new_temp('int')
                self._emit_call('int', eq_t, 'strcmp', [('char *', ls), ('char *', rs)])
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
            t = self._new_temp('char *')
            self._emit_call('char *', t, 'mojo_str_cat', [('char *', lv), ('char *', rv)])
            return 'char *', t
        # Fallback: catch list concatenation that wasn't handled above
        if node.op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
            t = self._new_temp('MojoList *')
            self._emit(f"  {t} = mojo_list_concat ({lv}, {rv});")
            if lv in self._elem_types:
                self._elem_types[t] = self._elem_types[lv]
            return 'MojoList *', t

        c_op      = _BIN_OPS.get(node.op, node.op)
        res_type  = '_Bool' if node.op in _CMP_OPS else TypeLattice.join(lt, rt)
        # For | on set/list/dict pointer types, use runtime union, not C bitwise |
        if node.op == '|' and (lt.endswith(' *') or rt.endswith(' *')):
            t = self._new_temp('MojoSet *')
            self._emit_call('MojoSet *', t, 'mojo_set_union',
                            [(lt, lv), (rt, rv)])
            return 'MojoSet *', t
        # For - on set types, use runtime difference, not C subtraction
        if node.op == '-' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
            t = self._new_temp('MojoSet *')
            self._emit_call('MojoSet *', t, 'mojo_set_difference',
                            [(lt, lv), (rt, rv)])
            return 'MojoSet *', t
        # For & on set types, use runtime intersection, not C bitwise &
        if node.op == '&' and (lt == 'MojoSet *' or rt == 'MojoSet *'):
            t = self._new_temp('MojoSet *')
            self._emit_call('MojoSet *', t, 'mojo_set_intersection',
                            [('MojoSet *', lv), ('MojoSet *', rv)])
            return 'MojoSet *', t
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
        if node.op in ('==', '!=') and lt.endswith(' *') != rt.endswith(' *'):
            ip_l = self._new_temp('int64_t')
            ip_r = self._new_temp('int64_t')
            self._emit(f'  {ip_l} = (int64_t){lv};')
            self._emit(f'  {ip_r} = (int64_t){rv};')
            lv = ip_l; rv = ip_r
        t = self._new_temp(res_type)
        self._emit(f"  {t} = {lv} {c_op} {rv};")
        return res_type, t

    # ── Operator helpers ──────────────────────────────────────────────────

    def _lower_floordiv(self, node: BinaryOp) -> tuple[str, str]:
        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)
        if lt in _FLOAT_TYPES or rt in _FLOAT_TYPES:
            td = TypeLattice.join(lt, rt)
            t1 = self._new_temp(td)
            self._emit(f"  {t1} = {lv} / {rv};")
            t2 = self._new_temp(td)
            self._emit(f"  {t2} = __builtin_floor ({t1});")
            return td, t2
        t = self._new_temp('int')
        self._emit(f"  {t} = __mojo_floordiv ({lv}, {rv});")
        return 'int', t

    def _lower_pow(self, node: BinaryOp) -> tuple[str, str]:
        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)
        if lt in _FLOAT_TYPES or rt in _FLOAT_TYPES:
            td = TypeLattice.join(lt, rt)
            t = self._new_temp(td)
            self._emit(f"  {t} = pow ({lv}, {rv});")
            return td, t
        t1 = self._new_temp('double')
        t2 = self._new_temp('double')
        self._emit(f"  {t1} = (double) {lv};")
        self._emit(f"  {t2} = (double) {rv};")
        t3 = self._new_temp('double')
        self._emit(f"  {t3} = pow ({t1}, {t2});")
        t4 = self._new_temp('int')
        self._emit(f"  {t4} = (int) {t3};")
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
        struct_name = lt.replace(' *', '').strip()

        # Call __matmul__(self, other) method
        mangled = f"{struct_name}___matmul__"
        result_type = self.func_return_types.get(mangled, 'int')  # Default: assume int result
        t = self._new_temp(result_type)
        self._emit(f"  {t} = {mangled} ({lv}, {rv});")
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
            t3 = self._new_temp('_Bool')
            self._emit(f"  {t3} = 0;")
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
            self._emit_call('int', ti, 'mojo_dict_contains', [('MojoDict *', rv), (xt, xv)])
        elif rt == 'MojoSet *':
            if xt == 'char *':
                self._emit(f"  {ti} = mojo_set_contains_str ({rv}, {xv});")
            else:
                xv64 = self._to_int64(xt, xv)
                self._emit(f"  {ti} = mojo_set_contains_int ({rv}, {xv64});")
        elif rt == 'MojoStr *':
            self._emit(f"  {ti} = mojo_str_contains ({rv}, {xv});")
        else:
            self._emit(f"  /* TODO: 'in' for {rt} */")
            self._emit(f"  {ti} = 0;")

        t = self._new_temp('_Bool')
        self._emit(f"  {t} = {ti} != 0;")

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
            t = self._new_temp('double')
            self._emit(f"  {t} = (double){val};")
            return t
        # str: cast int-cast strings to char*
        if suf == 'str' and elem_type in ('int', 'int64_t', 'char'):
            cp = self._new_temp('char *')
            ip = self._new_temp('int64_t')
            self._emit(f"  {ip} = (int64_t){val};")
            self._emit(f"  {cp} = (char *){ip};")
            return cp
        return val  # already char*

    def _to_int64(self, ctype: str, val: str) -> str:
        """Cast val to int64_t; emits to a temp so the result is always an lvalue."""
        if ctype == 'int64_t':
            return val
        t = self._new_temp('int64_t')
        if ctype.endswith(' *'):
            # Pointer → int64_t requires void* intermediate in GIMPLE
            val_local = self._ensure_local(ctype, val)
            vp = self._new_temp('void *')
            self._emit(f"  {vp} = (void *){val_local};")
            self._emit(f"  {t} = (int64_t){vp};")
        else:
            self._emit(f"  {t} = (int64_t){val};")
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
                base_type = obj_type.replace(' *', '').strip()
                if base_type in self.struct_field_types:
                    field_map = self.struct_field_types[base_type]
                    if node.member in field_map:
                        return field_map[node.member]
            return None
        return None

    def _lower_method_call(self, node: CallExpr) -> tuple[str, str]:
        """Lower obj.method(args) — handles module calls, raw C pointers (UnsafePointer) and structs."""
        func = node.func  # MemberExpr

        # Handle chained attribute calls: os.path.basename(arg) → int64_t_basename(arg)
        if isinstance(func.obj, MemberExpr):
            inner_obj = func.obj.obj
            inner_member = func.obj.member
            outer_member = func.member

            # Handle os.path.* calls
            if isinstance(inner_obj, IdentExpr) and inner_obj.name == 'os' and inner_member == 'path':
                if outer_member == 'basename' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._new_temp('char *')
                    self._emit_call('char *', t, 'int64_t_basename', [(arg_type, arg_val)])
                    return 'char *', t
                elif outer_member == 'splitext' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._new_temp('char *')
                    self._emit_call('char *', t, 'int64_t_splitext', [(arg_type, arg_val)])
                    return 'char *', t
                elif outer_member == 'abspath' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._new_temp('int64_t')
                    self._emit_call('int64_t', t, 'int_abspath', [('int64_t', '0'), (arg_type, arg_val)])
                    return 'int64_t', t
                elif outer_member == 'dirname' and len(node.args) == 1:
                    arg_type, arg_val = self.lower_expr(node.args[0])
                    t = self._new_temp('int64_t')
                    self._emit_call('int64_t', t, 'int_dirname', [('int64_t', '0'), (arg_type, arg_val)])
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
                    t = self._new_temp('int')
                    self._emit_call('int', t, 'int_exists', [('int64_t', '0'), (arg_type, arg_val)])
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
                        fn_ptr_t = self._new_temp('void *')
                        self._emit(f'  {fn_ptr_t} = (void *){cb_val};')
                        env_t = self._new_temp('void *')
                        self._emit(f'  {env_t} = (void *)0;')
                    t = self._new_temp('char *')
                    # Pass fn_ptr_t as void* (matched to mojo_re_sub_fn param type)
                    self._emit(f'  {t} = mojo_re_sub_fn ({pat_val}, {fn_ptr_t}, {env_t}, {src_val});')
                    return 'char *', t

            if module_name == 'gimple_codegen' and method_name == 'compile_to_gimple':
                # gimple_codegen.compile_to_gimple(src, do_imports=True) → returns char*
                # Only src is passed to C function (do_imports is Python-only)
                if len(node.args) >= 1:
                    src_type, src_val = self.lower_expr(node.args[0])
                    # Cast to char* if needed (legacy int-cast strings)
                    if src_type not in ('char *', 'void *'):
                        src_val = f"(char *){src_val}"
                    t = self._new_temp('char *')
                    self._emit(f"  {t} = gimple_codegen_compile_to_gimple ({src_val});")
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
            self_type = self.var_types.get('self', 'int')
            if self_type.endswith(' *'):
                # We're in a method with typed self — try to use that context
                base_self_type = self_type.replace(' *', '').strip()
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
            mangled = _safe_name(f"{struct_name}_{method}")
            ret_type = self.func_return_types.get(f"{struct_name}_{method}", 'char *')
            # Pass the class ref (ov) as 'cls' first arg, then the actual args
            arg_pairs = [(ot, ov)] + [self.lower_expr(a) for a in node.args]
            if ret_type == 'void':
                self._emit_call('void', '', mangled, arg_pairs)
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            t = self._new_temp(ret_type)
            self._emit_call(ret_type, t, mangled, arg_pairs)
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
                dp = self._new_temp('MojoDict *')
                self._emit(f"  {dp} = (MojoDict *){ip};")
                if ov in self._dict_val_types:
                    self._dict_val_types[dp] = self._dict_val_types[ov]
                ot, ov = 'MojoDict *', dp
            elif method in ('append', 'extend', 'sort', 'reverse', 'clear'):
                lp = self._new_temp('MojoList *')
                self._emit(f"  {lp} = (MojoList *){ip};")
                ot, ov = 'MojoList *', lp
            elif method in ('add', 'discard', 'remove'):
                sp = self._new_temp('MojoSet *')
                self._emit(f"  {sp} = (MojoSet *){ip};")
                ot, ov = 'MojoSet *', sp
            else:
                cp = self._new_temp('char *')
                self._emit(f"  {cp} = (char *){ip};")
                ot, ov = 'char *', cp

        # ── MojoDict method dispatch ───────────────────────────────────────
        if ot == 'MojoDict *':
            if method == 'keys':
                t = self._new_temp('MojoList *')
                self._emit(f"  {t} = mojo_dict_keys ({ov});")
                self._elem_types[t] = 'char *'
                return 'MojoList *', t
            if method == 'values':
                t = self._new_temp('MojoList *')
                self._emit(f"  {t} = mojo_dict_values ({ov});")
                return 'MojoList *', t
            if method == 'items':
                t = self._new_temp('MojoList *')
                self._emit(f"  {t} = mojo_dict_items ({ov});")
                return 'MojoList *', t
            if method == 'get' and node.args:
                key_type, key_val = self.lower_expr(node.args[0])
                default_val = '0'
                if len(node.args) > 1:
                    _, default_val = self.lower_expr(node.args[1])
                val_type = self._dict_val_of(ov)
                if val_type == 'char *':
                    t = self._new_temp('char *')
                    self._emit_call('char *', t, 'mojo_dict_get_str', [('MojoDict *', ov), (key_type, key_val)])
                    return 'char *', t
                elif val_type == 'double':
                    t = self._new_temp('double')
                    self._emit_call('double', t, 'mojo_dict_get_double', [('MojoDict *', ov), (key_type, key_val)])
                    return 'double', t
                else:
                    t = self._new_temp('int64_t')
                    self._emit_call('int64_t', t, 'mojo_dict_get_int', [('MojoDict *', ov), (key_type, key_val)])
                    return 'int64_t', t
            if method == 'update' and node.args:
                other_type, other_val = self.lower_expr(node.args[0])
                self._emit(f"  mojo_dict_update ({ov}, {other_val});")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'pop' and node.args:
                key_type, key_val = self.lower_expr(node.args[0])
                t = self._new_temp('int64_t')
                self._emit_call('int64_t', t, 'mojo_dict_pop_int', [('MojoDict *', ov), (key_type, key_val)])
                return 'int64_t', t
            if method in ('copy',):
                t = self._new_temp('MojoDict *')
                self._emit(f"  {t} = mojo_dict_copy ({ov});")
                return 'MojoDict *', t
            if method == 'clear':
                # Clear dict in-place by freeing and reinitializing
                self._emit(f"  mojo_dict_free ({ov});")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'setdefault' and node.args:
                # dict.setdefault(key, default) — use existing get/set
                key_type, key_val = self.lower_expr(node.args[0])
                t = self._new_temp('int64_t')
                self._emit_call('int64_t', t, 'mojo_dict_get_int', [('MojoDict *', ov), (key_type, key_val)])
                return 'int64_t', t

        # ── MojoList method dispatch ──────────────────────────────────────
        if ot == 'MojoList *':
            if method == 'append' and node.args:
                at, av = self.lower_expr(node.args[0])
                if at == 'char *':
                    self._emit_call('void', '', 'mojo_list_append_str', [('MojoList *', ov), ('char *', av)])
                else:
                    # Pass actual type so _emit_call converts pointers via void* → int64_t
                    self._emit_call('void', '', 'mojo_list_append_int', [('MojoList *', ov), (at, av)])
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'extend' and node.args:
                at, av = self.lower_expr(node.args[0])
                self._emit_call('void', '', 'mojo_list_extend', [('MojoList *', ov), (at, av)])
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'pop':
                t = self._new_temp('int64_t')
                self._emit(f"  {t} = mojo_list_pop ({ov});")
                return 'int64_t', t
            if method in ('sort', 'reverse', 'clear'):
                self._emit(f"  mojo_list_{method} ({ov});")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'copy':
                t = self._new_temp('MojoList *')
                self._emit(f"  {t} = mojo_list_copy ({ov});")
                return 'MojoList *', t

        # ── MojoSet method dispatch ───────────────────────────────────────
        if ot == 'MojoSet *':
            if method == 'update' and node.args:
                other_type, other_val = self.lower_expr(node.args[0])
                self._emit_call('void', '', 'mojo_set_update',
                                [('MojoSet *', ov), ('MojoSet *', other_val)])
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'add' and node.args:
                at, av = self.lower_expr(node.args[0])
                if at == 'char *':
                    self._emit_call('void', '', 'mojo_set_add_str', [('MojoSet *', ov), ('char *', av)])
                else:
                    self._emit_call('void', '', 'mojo_set_add_int', [('MojoSet *', ov), ('int64_t', av)])
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'discard' and node.args:
                at, av = self.lower_expr(node.args[0])
                self._emit_call('void', '', 'mojo_set_discard', [('MojoSet *', ov), (at, av)])
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t


        if ot.endswith(' *') and ot not in self._RUNTIME_PTRS:
            elem = _elem_type(ot)
            if method == 'load':
                t = self._new_temp(elem)
                self._emit(f"  {t} = *{ov};")
                return elem, t
            if method == 'store' and node.args:
                _, av = self.lower_expr(node.args[0])
                self._emit(f"  *{ov} = {self._coerce(self._quick_type(node.args[0]), elem, av)};")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method == 'offset' and node.args:
                _, nv = self.lower_expr(node.args[0])
                elem = _elem_type(ot)
                cn   = _c_id(elem)
                self._ptr_helpers_needed.add(elem)
                idx64 = self._new_temp('int64_t')
                self._emit(f"  {idx64} = (int64_t) {nv};")
                t = self._new_temp(ot)
                self._emit(f"  {t} = _mojo_at_{cn} ({ov}, {idx64});")
                return ot, t
            if method == 'free':
                self._emit(f"  free ({ov});")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method in ('bitcast', 'address_of'):
                t = self._new_temp(ot)
                self._emit(f"  {t} = {ov};  /* TODO: {method} */")
                return ot, t
            if method in ('destroy_pointee', 'take_pointee', 'initialize_pointee'):
                if node.args and method == 'initialize_pointee':
                    _, av = self.lower_expr(node.args[0])
                    self._emit(f"  *{ov} = {av};")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
            if method in ('strided_load', 'gather'):
                t = self._new_temp(elem); self._emit(f"  {t} = *{ov};  /* TODO: {method} */"); return elem, t
            if method in ('strided_store', 'scatter'):
                t = self._new_temp('int'); self._emit(f"  {t} = 0;  /* TODO: {method} */"); return 'int', t

        # File handle operations (void * from mojo_open)
        if ot == 'void *':
            if method == 'write' and node.args:
                data_type, data_val = self.lower_expr(node.args[0])
                if data_type == 'char *':
                    # mojo_write will compute length internally if len is -1
                    t = self._new_temp('int64_t')
                    self._emit(f"  {t} = mojo_write ({ov}, {data_val}, -1);")
                    return 'int64_t', t
            if method == 'close':
                self._emit(f"  mojo_close ({ov});")
                t = self._new_temp('int')
                self._emit(f"  {t} = 0;")
                return 'int', t

        # char* string method calls — dispatch to C string utility functions
        if ot == 'char *':
            arg_pairs = [(self.lower_expr(a)[0], self.lower_expr(a)[1]) for a in node.args]
            # GIMPLE: global string literals must be loaded into locals before use
            loaded_args = []
            for at, av in arg_pairs:
                if av.startswith('_slit_') or (av in self._str_pool.values() and av != av):
                    tmp = self._new_temp(at)
                    self._emit(f'  {tmp} = {av};')
                    av = tmp
                elif av.startswith('_slit_'):
                    tmp = self._new_temp(at)
                    self._emit(f'  {tmp} = {av};')
                    av = tmp
                loaded_args.append(av)
            arg_vals = loaded_args
            # Cast ov to char* if it's stored as int64_t (pointer stored as int)
            stored_type = self.var_types.get(ov, ot)
            if stored_type == 'int64_t':
                cstr_ov_temp = self._new_temp('char *')
                self._emit(f"  {cstr_ov_temp} = (char *){ov};")
                cstr_ov = cstr_ov_temp
            else:
                cstr_ov = ov
            # Regex match object methods: in mojo_re_sub_fn callbacks, the match
            # parameter is already the matched string (char *), so m.group(0) = m.
            if method == 'group':
                return 'char *', cstr_ov
            _CSTR_METHODS: dict[str, str] = {
                'lower': 'string_lower', 'upper': 'string_upper',
                'strip': 'string_strip',
            }
            if method in _CSTR_METHODS:
                fn = _CSTR_METHODS[method]
                t = self._new_temp('char *')
                self._emit(f"  {t} = {fn} ({cstr_ov});")
                return 'char *', t
            if method == 'startswith' and arg_vals:
                t = self._new_temp('int')
                arg0_type = arg_pairs[0][0] if arg_pairs else 'char *'
                arg0_val  = arg_vals[0]
                if arg0_type == 'char':
                    self._emit_call('int', t, 'mojo_str_startswith_char', [('char *', cstr_ov), ('char', arg0_val)])
                else:
                    self._emit_call('int', t, 'mojo_str_startswith', [('char *', cstr_ov), (arg0_type, arg0_val)])
                return 'int', t
            if method == 'endswith' and arg_vals:
                t = self._new_temp('int')
                arg0_type = arg_pairs[0][0] if arg_pairs else 'char *'
                arg0_val  = arg_vals[0]
                if arg0_type == 'char':
                    self._emit_call('int', t, 'mojo_str_endswith_char', [('char *', cstr_ov), ('char', arg0_val)])
                else:
                    self._emit_call('int', t, 'mojo_str_endswith', [('char *', cstr_ov), (arg0_type, arg0_val)])
                return 'int', t
            if method == 'find' and arg_vals:
                t = self._new_temp('int64_t')
                self._emit_call('int64_t', t, 'mojo_str_find', [('char *', cstr_ov), ('char *', arg_vals[0])])
                return 'int64_t', t
            if method == 'split' and arg_vals:
                t = self._new_temp('MojoList *')
                self._emit_call('MojoList *', t, 'mojo_str_split', [('char *', cstr_ov), ('char *', arg_vals[0])])
                self._elem_types[t] = 'char *'
                return 'MojoList *', t
            if method in ('encode', 'decode', 'format'):
                t = self._new_temp('char *')
                self._emit(f"  {t} = {cstr_ov};  /* TODO: {method} */")
                return 'char *', t
            # Unknown method on char* — return 0 (stub)
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;  /* TODO: char*.{method} */")
            return 'int', t

        # File handle operations (int64_t handles from mojo_open_file)
        if ot in ('int', 'int64_t'):
            if method == 'read' and not node.args:
                t = self._new_temp('char *')
                self._emit(f"  {t} = int_read ({ov});")
                return 'char *', t
            if method == 'write' and node.args:
                data_type, data_val = self.lower_expr(node.args[0])
                t = self._new_temp('int64_t')
                self._emit(f"  {t} = int_write ({ov}, {data_val});")
                return 'int64_t', t
            if method == 'close':
                self._emit(f"  mojo_close ((void *){ov});")
                t = self._new_temp('int')
                self._emit(f"  {t} = 0;")
                return 'int', t

        # Stub string-type methods when called on wrong receiver types
        if method == 'isdigit':
            t = self._new_temp('int'); self._emit(f"  {t} = 0;  /* {ot}.isdigit() stubbed */"); return 'int', t
        if method == 'endswith' and ot not in ('char *', 'void *') and (not ot.endswith(' *') or ot in ('MojoSet *', 'MojoList *', 'MojoDict *')):
            t = self._new_temp('int'); self._emit(f"  {t} = 0;  /* {ot}.endswith() stubbed */"); return 'int', t
        if method in ('strip', 'lstrip', 'rstrip') and ot not in ('char *', 'void *') and not ot.startswith('Mojo'):
            # strip/lstrip/rstrip on non-string: these already have TODO stubs,
            # but catch cases where they'd generate an invalid method name
            if ot in ('int', 'int64_t', '_Bool', 'double'):
                _es = self._str_pool.setdefault('', f'_slit_{10000 + len(self._str_pool)}')
                t = self._new_temp('char *'); self._emit(f'  {t} = {_es};  /* {ot}.{method}() stubbed */'); return 'char *', t
        if method == 'get' and ot in ('_Bool', 'int', 'int64_t', 'double'):
            for a in node.args: self.lower_expr(a)
            t = self._new_temp('int64_t'); self._emit(f"  {t} = (int64_t)0;  /* {ot}.get() stubbed */"); return 'int64_t', t
        if method in ('strip', 'lstrip', 'rstrip') and ot in ('MojoDict *', 'MojoList *', 'MojoSet *'):
            for a in node.args: self.lower_expr(a)
            t = self._new_temp('int'); self._emit(f"  {t} = 0;  /* {ot}.{method}() stubbed */"); return 'int', t
        # Stub string methods called on Mojo container types (would generate invalid struct method)
        if method in ('replace', 'find', 'lower', 'upper', 'join', 'split', 'format',
                      'startswith', 'encode', 'decode') and ot in ('MojoSet *', 'MojoList *', 'MojoDict *'):
            for a in node.args: self.lower_expr(a)
            _es = self._str_pool.setdefault('', f'_slit_{10000 + len(self._str_pool)}')
            t = self._new_temp('char *'); self._emit(f'  {t} = {_es};  /* {ot}.{method}() stubbed */'); return 'char *', t

        # MojoSet.copy() → mojo_set_copy()
        if method == 'copy' and ot == 'MojoSet *':
            t = self._new_temp('MojoSet *')
            self._emit_call('MojoSet *', t, 'mojo_set_copy', [('MojoSet *', ov)])
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
            t = self._new_temp(ret)
            self._emit_call(ret, t, f'DispatchTable_{method}', [('DispatchTable *', dt)])
            return ret, t

        # Opaque Python object (int-typed): use mojo_obj_call1 for generic method dispatch
        if ot in ('int', 'int64_t') and not (isinstance(func.obj, IdentExpr)
                                               and func.obj.name in self.struct_field_types):
            escaped = method.replace('\\', '\\\\').replace('"', '\\"')
            if escaped not in self._str_pool:
                self._str_pool[escaped] = f'_slit_{10000 + len(self._str_pool)}'
            method_slit = self._str_pool[escaped]
            method_key = self._new_temp('char *')
            self._emit(f"  {method_key} = {method_slit};")
            obj64 = self._new_temp('int64_t')
            self._emit(f"  {obj64} = (int64_t){ov};")
            # Lower the first argument (if any), or pass 0
            if node.args:
                arg_type, arg_val = self.lower_expr(node.args[0])
                arg64 = self._new_temp('int64_t')
                self._safe_coerce_emit(arg_type, 'int64_t', arg_val, arg64)
            else:
                arg64 = self._new_temp('int64_t')
                self._emit(f"  {arg64} = (int64_t)0;")
            t = self._new_temp('int64_t')
            self._emit_call('int64_t', t, 'mojo_obj_call1',
                            [('int64_t', obj64), ('char *', method_key), ('int64_t', arg64)])
            # Lower remaining args (for side effects) even though we can't pass them
            for extra_arg in node.args[1:]:
                self.lower_expr(extra_arg)
            return 'int64_t', t

        # Struct method call: obj.method(args) → StructName_method(self, args)
        # If the object was a class name reference (ot='int', ov='0'), recover the class name
        # from the original AST node rather than using 'int' as the struct name.
        is_class_ref = False
        if isinstance(func.obj, IdentExpr) and func.obj.name in self.struct_field_types:
            struct_name = func.obj.name
            is_class_ref = True
        else:
            struct_name = ot.replace(' *', '').strip()
            # If we couldn't determine struct name but this is a known method call on a known struct,
            # try to infer from the method name (e.g. 'set' is typically called on Scope)
            if struct_name == 'int' and method in ('set', '__call__'):
                # Try to infer struct from method being called
                if isinstance(func.obj, MemberExpr) and isinstance(func.obj.obj, IdentExpr):
                    if func.obj.obj.name == 'self':
                        # self.parent.method() → try Scope if method='set'
                        if method == 'set' and func.obj.member == 'parent':
                            struct_name = 'Scope'
        mangled = _safe_name(f"{struct_name}_{method}")
        ret_type = self.func_return_types.get(f"{struct_name}_{method}", None)
        # Infer return type from common patterns if not found
        if ret_type is None:
            if method in ('get', 'get_symbol_type', 'pop', 'keys', 'values', 'items'):
                ret_type = 'char *' if method in ('get', 'get_symbol_type', 'pop') else 'MojoList *'
            elif method in ('load',):
                ret_type = 'int64_t'
            else:
                ret_type = 'int'  # default fallback
        arg_pairs = [self.lower_expr(a) for a in node.args]
        # Pad missing args with 0 when we know the expected param count from the signature
        # (handles default-argument methods like _peek(offset=0), _expect(kind, value=None))
        full_param_list = self.func_param_types.get(f"{struct_name}_{method}", [])
        # Detect static methods: first param is not the struct pointer → treat as class ref
        if not is_class_ref and full_param_list and full_param_list[0] != f"{struct_name} *":
            is_class_ref = True
        # full_param_list includes self; non-class calls prepend self, so account for it
        expected_non_self = len(full_param_list) - (0 if is_class_ref else 1)
        if full_param_list and len(arg_pairs) < expected_non_self:
            while len(arg_pairs) < expected_non_self:
                arg_pairs.append(('int', '0'))
        # For class method calls (ClassName.method()), don't prepend the fake cls=0 arg
        if is_class_ref:
            all_args = ', '.join(av for _, av in arg_pairs)
        else:
            all_args = ', '.join([ov] + [av for _, av in arg_pairs])

        if ret_type == 'void':
            all_arg_pairs = arg_pairs if is_class_ref else [(ot, ov)] + arg_pairs
            self._emit_call('void', '', mangled, all_arg_pairs)
            t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t

        # Return the actual type directly — no int64_t storage pattern
        # (GIMPLE can handle pointer-typed locals fine; the int64_t pattern caused
        # downstream type-mismatch errors when char* results were used in binary ops)
        t = self._new_temp(ret_type)
        # Use _emit_call for proper argument coercion
        arg_pair_list = [(self._type_of(av) if i < len(arg_pairs) else 'int', av)
                         for i, (_, av) in enumerate(arg_pairs)]
        self._emit_call(ret_type, t, mangled,
                        ([(ot, ov)] + arg_pairs) if not is_class_ref else arg_pairs)
        return ret_type, t

    # ── Call expression lowering ──────────────────────────────────────────

    def _lower_call(self, node: CallExpr) -> tuple[str, str]:
        if isinstance(node.func, MemberExpr):
            return self._lower_method_call(node)
        if not isinstance(node.func, IdentExpr):
            # Skip emitting comment to avoid GIMPLE global-passing issues
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;")
            return 'int', t

        fname_raw = node.func.name

        # dir(obj) — Python built-in, stub to return empty list
        if fname_raw == 'dir':
            for a in node.args: self.lower_expr(a)
            t = self._new_temp('MojoList *')
            self._emit(f"  {t} = mojo_list_new ();  /* dir() stubbed */")
            return 'MojoList *', t

        # sorted(iterable[, key]) — ignore optional key argument
        if fname_raw == 'sorted' and len(node.args) >= 1:
            at, av = self.lower_expr(node.args[0])
            for a in node.args[1:]: self.lower_expr(a)  # evaluate key for side effects, ignore
            t = self._new_temp('MojoList *')
            self._emit_call('MojoList *', t, 'mojo_sorted', [(at, av)])
            return 'MojoList *', t

        # __import__(name) — Python dynamic import, stub to return 0 in bootstrap
        if fname_raw == '__import__':
            for a in node.args:
                self.lower_expr(a)  # evaluate for side effects
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;  /* __import__ stubbed */")
            return 'int', t

        # all(iterable) — Python builtin
        if fname_raw == 'all' and len(node.args) == 1:
            at, av = self.lower_expr(node.args[0])
            t = self._new_temp('int')
            if at in ('MojoList *',) or (at.endswith(' *') and at != 'char *'):
                lv = self._new_temp('MojoList *') if at != 'MojoList *' else av
                if at != 'MojoList *':
                    self._emit(f"  {lv} = (MojoList *){av};")
                self._emit_call('int', t, 'mojo_list_all', [('MojoList *', lv)])
            else:
                self._emit(f"  {t} = 1;  /* all() stubbed */")
            return 'int', t

        # isinstance() built-in
        if fname_raw == 'isinstance' and len(node.args) == 2:
            obj_type, obj_val = self.lower_expr(node.args[0])
            # Handle type argument - could be a type name or a tuple of types
            type_arg = node.args[1]

            t = self._new_temp('int')
            if isinstance(type_arg, IdentExpr):
                type_name = type_arg.name
                # isinstance(x, type) — Python runtime type check, always false in C
                if type_name == 'type':
                    self._emit(f"  {t} = 0;  /* isinstance(x, type) always false in C */")
                else:
                    type_id_map = {'bool': '1', 'int': '2', 'float': '3', 'str': '4', 'list': '5', 'dict': '6', 'set': '7'}
                    type_id = type_id_map.get(type_name, '0')
                    # mojo_isinstance takes int obj — coerce pointer to int64_t first
                    if obj_type in ('char *', 'void *', 'MojoDict *', 'MojoList *', 'MojoSet *') or obj_type.endswith(' *'):
                        iv = self._new_temp('int64_t')
                        self._emit(f"  {iv} = (int64_t){obj_val};")
                        iv2 = self._new_temp('int')
                        self._emit(f"  {iv2} = (int){iv};")
                        self._emit(f"  {t} = mojo_isinstance ({iv2}, {type_id});")
                    else:
                        self._emit(f"  {t} = mojo_isinstance ({obj_val}, {type_id});")
            elif isinstance(type_arg, TupleExpr):
                self._emit(f"  {t} = 0;  /* TODO: isinstance with tuple of types */")
            else:
                self._emit(f"  {t} = 0;  /* TODO: isinstance with complex type arg */")
            return 'int', t

        # str() built-in
        if fname_raw == 'str' and len(node.args) == 1:
            arg_type, arg_val = self.lower_expr(node.args[0])
            t = self._new_temp('char *')
            # Always use _emit_call so void* coercion is handled correctly in GIMPLE
            self._emit_call('char *', t, 'mojo_str', [(arg_type, arg_val)])
            return 'char *', t

        # repr() built-in
        if fname_raw == 'repr' and len(node.args) == 1:
            arg_type, arg_val = self.lower_expr(node.args[0])
            t = self._new_temp('char *')
            self._emit_call('char *', t, 'mojo_repr', [(arg_type, arg_val)])
            return 'char *', t

        # type() built-in
        if fname_raw == 'type' and len(node.args) == 1:
            arg_type, arg_val = self.lower_expr(node.args[0])
            t = self._new_temp('int')
            self._emit(f"  {t} = mojo_type ({arg_val});")
            return 'int', t

        # enumerate() built-in
        if fname_raw == 'enumerate' and len(node.args) >= 1:
            arg_type, arg_val = self.lower_expr(node.args[0])
            t = self._new_temp('void *')
            self._emit_call('void *', t, 'mojo_enumerate', [(arg_type, arg_val)])
            return 'void *', t

        # getattr() built-in
        if fname_raw == 'getattr' and len(node.args) >= 2:
            obj_type, obj_val = self.lower_expr(node.args[0])
            attr_type, attr_val = self.lower_expr(node.args[1])
            t = self._new_temp('int64_t')
            self._emit_call('int64_t', t, 'mojo_obj_getattr', [(obj_type, obj_val), (attr_type, attr_val)])
            return 'int64_t', t

        # setattr() built-in
        if fname_raw == 'setattr' and len(node.args) >= 3:
            obj_type, obj_val = self.lower_expr(node.args[0])
            attr_type, attr_val = self.lower_expr(node.args[1])
            val_type, val_val = self.lower_expr(node.args[2])
            self._emit_call('void', '', 'mojo_setattr', [(obj_type, obj_val), (attr_type, attr_val), (val_type, val_val)])
            t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t

        # hasattr() built-in
        if fname_raw == 'hasattr' and len(node.args) == 2:
            obj_type, obj_val = self.lower_expr(node.args[0])
            attr_type, attr_val = self.lower_expr(node.args[1])
            t = self._new_temp('int')
            self._emit_call('int', t, 'mojo_hasattr', [(obj_type, obj_val), (attr_type, attr_val)])
            return 'int', t

        # len() built-in dispatch
        if fname_raw == 'len' and len(node.args) == 1:
            at, av = self.lower_expr(node.args[0])
            if at == 'MojoStr *':
                t = self._new_temp('int64_t')
                self._emit(f"  {t} = mojo_str_len ({av});")
                return 'int64_t', t
            if at == 'MojoList *':
                t = self._new_temp('int64_t')
                self._emit(f"  {t} = mojo_list_len ({av});")
                return 'int64_t', t
            if at == 'MojoDict *':
                t = self._new_temp('int64_t')
                self._emit(f"  {t} = mojo_dict_len ({av});")
                return 'int64_t', t
            if at == 'MojoSet *':
                t = self._new_temp('int64_t')
                self._emit(f"  {t} = mojo_set_len ({av});")
                return 'int64_t', t
            if at in ('int', 'int64_t'):
                ip = self._new_temp('int64_t')
                lp = self._new_temp('MojoList *')
                t  = self._new_temp('int64_t')
                self._emit(f"  {ip} = (int64_t){av};")
                self._emit(f"  {lp} = (MojoList *){ip};")
                self._emit(f"  {t} = mojo_list_len ({lp});")
                return 'int64_t', t
            # Fallback for other types — explicit int64_t cast required by GIMPLE
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = (int64_t)0;  /* len() on unsupported type {at} */")
            return 'int64_t', t

        # Struct constructor: TypeName(arg1, arg2, ...) or TypeName(field=val, ...)
        if fname_raw in self.struct_field_types:
            return self._lower_struct_constructor(fname_raw, node.args, getattr(node, 'kwargs', None))

        # set() / frozenset() built-in constructors
        if fname_raw in ('set', 'frozenset'):
            t = self._new_temp('MojoSet *')
            self._emit(f"  {t} = mojo_set_new ();")
            for arg in node.args:
                # If arg is an iterable literal, add its elements
                at, av = self.lower_expr(arg)
                # For now just return empty set; runtime can populate if needed
            return 'MojoSet *', t

        # dict() built-in constructor
        if fname_raw == 'dict' and len(node.args) == 0:
            t = self._new_temp('MojoDict *')
            self._emit(f"  {t} = mojo_dict_new ();")
            return 'MojoDict *', t

        # dict(x) — convert list-of-pairs to dict, or copy an existing dict
        if fname_raw == 'dict' and len(node.args) == 1:
            at, av = self.lower_expr(node.args[0])
            t = self._new_temp('MojoDict *')
            if at == 'MojoList *':
                # dict(list_of_pairs) → mojo_dict_from_pairs
                self._emit_call('MojoDict *', t, 'mojo_dict_from_pairs', [('MojoList *', av)])
            elif at in ('int64_t', 'int') or not at.endswith(' *') or at == 'void *':
                raw = self._new_temp('MojoDict *')
                self._emit(f"  {raw} = (MojoDict *){av};")
                self._emit_call('MojoDict *', t, 'mojo_dict_copy', [('MojoDict *', raw)])
            else:
                self._emit_call('MojoDict *', t, 'mojo_dict_copy', [(at, av)])
            return 'MojoDict *', t

        # list() / tuple() constructor
        if fname_raw in ('list', 'tuple') and len(node.args) <= 1:
            t = self._new_temp('MojoList *')
            self._emit(f"  {t} = mojo_list_new ();")
            return 'MojoList *', t


        if fname_raw == 'open' and len(node.args) == 1:
            # open(path) — read mode
            fn_type, fn_val = self.lower_expr(node.args[0])
            t = self._new_temp('int64_t')
            # Use _emit_call for proper type coercion
            self._emit_call('int64_t', t, 'mojo_open_file', [(fn_type, fn_val)])
            return 'int64_t', t

        if fname_raw == 'open' and len(node.args) == 2:
            fn_type, fn_val = self.lower_expr(node.args[0])
            mode_type, mode_val = self.lower_expr(node.args[1])
            # Ensure args are char* (GIMPLE forbids combining call + cast in one statement)
            fn_val = self._ensure_local(fn_type, fn_val)
            mode_val = self._ensure_local(mode_type, mode_val)
            tmp = self._new_temp('void *')
            self._emit(f"  {tmp} = mojo_open ({fn_val}, {mode_val});")
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = (int64_t){tmp};")
            return 'int64_t', t

        # Recursive call to the current lifted closure (e.g. _parse_for_target calling itself)
        inner_name = getattr(self, '_inner_func_name', '')
        if inner_name and fname_raw == inner_name and self._env_param:
            lifted   = self.current_func_name
            env_var  = self._env_param
            ret_type = self.func_ret_type or self.func_return_types.get(lifted, 'int')
            arg_vals = [self.lower_expr(a)[1] for a in node.args]
            all_args = ', '.join([env_var] + arg_vals)
            fname_c  = _safe_name(lifted)
            if ret_type == 'void':
                self._emit(f"  {fname_c} ({all_args});")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;")
                return 'int', t
            t = self._new_temp(ret_type)
            self._emit(f"  {t} = {fname_c} ({all_args});")
            return ret_type, t

        # Closure call: inner function name mapped to a lifted top-level function
        if fname_raw in self._closure_envs:
            lifted   = f"{self.current_func_name}_{fname_raw}"
            env_var  = self._closure_envs[fname_raw]
            ret_type = self.func_return_types.get(lifted, 'int')
            arg_pairs = [self.lower_expr(a) for a in node.args]
            fname_c  = _safe_name(lifted)
            # Build full arg list with env pointer prepended
            if env_var:
                env_type = self.func_param_types.get(lifted, [f"{env_var[1:]} *" if '_env_' in env_var else 'void *'])[0]
                full_arg_pairs = [(env_type, env_var)] + arg_pairs
            else:
                full_arg_pairs = arg_pairs
            if ret_type == 'void':
                self._emit_call('void', '', fname_c, full_arg_pairs)
                t = self._new_temp('int'); self._emit(f"  {t} = 0;")
                return 'int', t
            t = self._new_temp(ret_type)
            self._emit_call(ret_type, t, fname_c, full_arg_pairs)
            return ret_type, t

        # If fname_raw is a local variable holding a function handle (not a real function name),
        # calling it directly in GIMPLE is invalid (can't call int/int64_t as function).
        # Evaluate args for side effects and stub the call out to 0.
        _fname_var_ctype = self.var_types.get(fname_raw, '')
        if _fname_var_ctype in ('int', 'int64_t', 'void *', '_Bool'):
            for a in node.args: self.lower_expr(a)
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;  /* TODO: indirect call via {fname_raw} ({_fname_var_ctype}) */")
            return 'int', t

        # Use builtin mapping first (int→mojo_make_int, float→mojo_make_float, etc.)
        # _safe_name would wrongly rename 'int' to 'mojo_int' (a typedef, not a function)
        fname    = self.BUILTIN_VALUE_MAP.get(fname_raw, _safe_name(fname_raw))
        ret_type = self.func_return_types.get(fname_raw, 'int')
        # If the mapped C function has a known return type, use it (not the Python inferred type)
        if fname in self._KNOWN_SIGS:
            ret_type = self._KNOWN_SIGS[fname][0]
        arg_pairs = [self.lower_expr(a) for a in node.args]

        # Special handling for functions with default parameters
        if fname_raw == 'format_ast' and len(arg_pairs) == 1:
            arg_pairs.append(('int', '0'))
        if fname_raw == 'emit_module' and len(arg_pairs) == 1:
            arg_pairs.append(('int', '0'))
        if fname_raw == 'compile_to_gimple' and len(arg_pairs) == 1:
            arg_pairs.append(('int', '0'))
        # General: pad missing args with 0 when expected param count is known
        expected_params = self.func_param_types.get(fname_raw, [])
        if expected_params and len(arg_pairs) < len(expected_params):
            while len(arg_pairs) < len(expected_params):
                arg_pairs.append(('int', '0'))
        # int(s, base) — mojo_make_int only takes one arg; always drop the base arg
        if fname_raw == 'int' and len(arg_pairs) > 1:
            arg_pairs = arg_pairs[:1]

        if ret_type == 'void':
            self._emit_call('void', '', fname, arg_pairs)
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;")
            return 'int', t

        # String utility functions — store char* result directly
        _DIRECT_CHARPTR = frozenset({
            'input', 'mojo_input',
            'string_lower', 'string_strip', 'string_upper',
        })
        if ret_type == 'char *' and fname_raw in _DIRECT_CHARPTR:
            t = self._new_temp('char *')
            self._emit_call('char *', t, fname, arg_pairs)
            return 'char *', t

        # For pointer types, store as int64_t storage and track actual type
        if ret_type.endswith(' *'):
            # Return pointer directly — GIMPLE is fine with pointer-typed locals
            t = self._new_temp(ret_type)
            self._emit_call(ret_type, t, fname, arg_pairs)
            return ret_type, t
        else:
            storage_type = ret_type

        t = self._new_temp(storage_type)
        self._emit_call(storage_type, t, fname, arg_pairs)

        # Return the storage type that was actually assigned, so variable declarations match
        return storage_type, t

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
            # Pad missing args with 0 when the __init__ has more params than provided
            full_params = self.func_param_types.get(init_fname, [])
            expected = len(full_params) - 1  # -1 for self
            while len(arg_pairs) - 1 < expected:
                arg_pairs.append(('int', '0'))
            self._emit_call('void', '', init_fname, arg_pairs)
        elif kwargs:
            # Keyword args: assign each named field
            fields = self.struct_field_types[struct_name]
            for kname, kexpr in kwargs:
                if kname in fields:
                    ftype = fields[kname]
                    at, av = self.lower_expr(kexpr)
                    self._safe_coerce_emit(at, ftype, av, f"{t}->{kname}")
        else:
            # Positional arguments: assign fields in declaration order
            fields = list(self.struct_field_types[struct_name].items())
            for i, (fname, ftype) in enumerate(fields):
                if i < len(args):
                    at, av = self.lower_expr(args[i])
                    self._safe_coerce_emit(at, ftype, av, f"{t}->{fname}")
        return ctype, t

    # ── Subscript lowering ────────────────────────────────────────────────

    def _lower_subscript(self, node: SubscriptExpr) -> tuple[str, str]:
        ot, ov = self.lower_expr(node.obj)
        idx_type, iv  = self.lower_expr(node.index)

        if ot == 'MojoList *':
            elem = self._elem_of(ov)
            suf  = TypeLattice.list_suffix(elem)
            idx64 = self._new_temp('int64_t')
            self._emit(f"  {idx64} = (int64_t) {iv};")
            if suf == 'double':
                t = self._new_temp('double')
                self._emit(f"  {t} = mojo_list_get_double ({ov}, {idx64});")
                return 'double', t
            if suf == 'str':
                t = self._new_temp('char *')
                self._emit(f"  {t} = mojo_list_get_str ({ov}, {idx64});")
                return 'char *', t
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = mojo_list_get_int ({ov}, {idx64});")
            return 'int64_t', t

        if ot == 'MojoStr *':
            idx64 = self._new_temp('int64_t')
            self._emit(f"  {idx64} = (int64_t) {iv};")
            t = self._new_temp('char')
            self._emit(f"  {t} = mojo_str_char_at ({ov}, {idx64});")
            return 'char', t

        if ot == 'MojoDict *':
            val_ctype = self._dict_val_of(ov)
            if val_ctype == 'double':
                t = self._new_temp('double')
                self._emit_call('double', t, 'mojo_dict_get_double', [('MojoDict *', ov), (idx_type, iv)])
                return 'double', t
            if val_ctype == 'char *':
                t = self._new_temp('char *')
                self._emit_call('char *', t, 'mojo_dict_get_str', [('MojoDict *', ov), (idx_type, iv)])
                return 'char *', t
            t = self._new_temp('int64_t')
            self._emit_call('int64_t', t, 'mojo_dict_get_int', [('MojoDict *', ov), (idx_type, iv)])
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
                idx64 = self._new_temp('int64_t')
                self._emit(f"  {idx64} = (int64_t){iv};")
                val_ctype = self._dict_val_of(dp)
                if val_ctype == 'double':
                    t = self._new_temp('double')
                    self._emit_call('double', t, 'mojo_dict_get_double', [('MojoDict *', dp), (idx_type, iv)])
                    return 'double', t
                if val_ctype == 'char *':
                    t = self._new_temp('char *')
                    self._emit_call('char *', t, 'mojo_dict_get_str', [('MojoDict *', dp), (idx_type, iv)])
                    return 'char *', t
                t = self._new_temp('int64_t')
                self._emit_call('int64_t', t, 'mojo_dict_get_int', [('MojoDict *', dp), (idx_type, iv)])
                return 'int64_t', t
            # Otherwise treat as MojoList* stored as int; cast and subscript
            lp = self._new_temp('MojoList *')
            ip = self._new_temp('int64_t')
            idx64 = self._new_temp('int64_t')
            ov_local = self._ensure_local(ot, ov)
            if ot == 'int64_t':
                self._emit(f"  {ip} = {ov_local};")  # same type, no cast
            else:
                self._emit(f"  {ip} = (int64_t){ov_local};")
            self._emit(f"  {lp} = (MojoList *){ip};")
            self._emit(f"  {idx64} = (int64_t){iv};")
            elem = self._elem_of(ov)
            if elem == 'char *':
                t = self._new_temp('char *')
                self._emit(f"  {t} = mojo_list_get_str ({lp}, {idx64});")
                return 'char *', t
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = mojo_list_get_int ({lp}, {idx64});")
            return 'int64_t', t

        # p[i] via _mojo_at_ helper (ptr arithmetic not allowed in __GIMPLE)
        et = _elem_type(ot)
        cn = _c_id(et)
        self._ptr_helpers_needed.add(et)
        idx64 = self._new_temp('int64_t')
        self._emit(f"  {idx64} = (int64_t) {iv};")
        addr = self._new_temp(ot)
        self._emit(f"  {addr} = _mojo_at_{cn} ({ov}, {idx64});")
        t = self._new_temp(et)
        self._emit(f"  {t} = *{addr};")
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
            t = self._new_temp('MojoStr *')
            self._emit(f"  {t} = mojo_str_slice ({ov}, {start_v}, {stop_v});")
            return 'MojoStr *', t

        if ot == 'MojoList *':
            t = self._new_temp('MojoList *')
            self._emit(f"  {t} = mojo_list_slice ({ov}, {start_v}, {stop_v});")
            # propagate elem type
            if ov in self._elem_types:
                self._elem_types[t] = self._elem_types[ov]
            return 'MojoList *', t

        # Plain pointer: return pointer to start (no bounds check)
        # GIMPLE: no pointer+integer; cast pointer through int64_t; both operands
        # must be plain variables (no cast expressions in binary operands).
        t = self._new_temp(ot)
        cast_t = self._new_temp('int64_t')
        self._emit(f"  {cast_t} = (int64_t){ov};")
        # Cast start to int64_t in a separate statement (GIMPLE binary operands
        # must be variables, not cast expressions)
        if start_v.lstrip('-').isdigit():
            sv_cast = self._new_temp('int64_t')
            self._emit(f"  {sv_cast} = (int64_t){start_v};")
        else:
            # start_v is already a variable; ensure it's int64_t
            sv_cast = self._new_temp('int64_t')
            self._emit(f"  {sv_cast} = (int64_t){start_v};")
        add_t = self._new_temp('int64_t')
        self._emit(f"  {add_t} = {cast_t} + {sv_cast};")
        self._emit(f"  {t} = ({ot}){add_t};")
        return ot, t

    # ── Collection literal lowering ───────────────────────────────────────

    def _lower_list_literal(self, node: ListExpr) -> tuple[str, str]:
        elem = self._infer_list_elem_type(node.elements)
        suf  = TypeLattice.list_suffix(elem)
        t    = self._new_temp('MojoList *')
        self._elem_types[t] = elem
        self._emit(f"  {t} = mojo_list_new ();")
        for el in node.elements:
            et, ev = self.lower_expr(el)
            # Spread element (*seq): extend the list instead of appending
            if et in ('MojoList *', 'MojoSet *') or (isinstance(el, UnaryOp) and el.op == '*'):
                self._emit_call('void', '', 'mojo_list_extend', [('MojoList *', t), (et, ev)])
                continue
            ev_cast = self._cast_for_list(et, ev, suf)
            # GIMPLE: load global string literals into temp before function call
            if suf == 'str' and ev_cast.startswith('_slit_'):
                temp = self._new_temp('char *')
                self._emit(f'  {temp} = {ev_cast};')
                ev_cast = temp
            self._emit(f"  mojo_list_append_{suf} ({t}, {ev_cast});")
        return 'MojoList *', t

    def _lower_dict_literal(self, node: DictExpr) -> tuple[str, str]:
        t = self._new_temp('MojoDict *')
        self._emit(f"  {t} = mojo_dict_new ();")
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
            _, kv  = self.lower_expr(key_expr)
            vt, vv = self.lower_expr(val_expr)
            # Load global string literals into temps before passing to dict functions
            if kv.startswith('_slit_'):
                kv_tmp = self._new_temp('char *')
                self._emit(f"  {kv_tmp} = {kv};")
                kv = kv_tmp
            if vt in _FLOAT_TYPES:
                self._emit(f"  mojo_dict_set_double ({t}, {kv}, {vv});")
            elif vt == 'char *':
                if vv.startswith('_slit_'):
                    vv_tmp = self._new_temp('char *')
                    self._emit(f"  {vv_tmp} = {vv};")
                    vv = vv_tmp
                self._emit(f"  mojo_dict_set_str ({t}, {kv}, {vv});")
            else:
                vv64 = self._to_int64(vt, vv)
                self._emit(f"  mojo_dict_set_int ({t}, {kv}, {vv64});")
        return 'MojoDict *', t

    def _lower_set_literal(self, node: SetExpr) -> tuple[str, str]:
        t = self._new_temp('MojoSet *')
        self._emit(f"  {t} = mojo_set_new ();")
        for el in node.elements:
            et, ev = self.lower_expr(el)
            if et == 'char *':
                self._emit_call('void', '', 'mojo_set_add_str', [('MojoSet *', t), ('char *', ev)])
            else:
                ev64 = self._to_int64(et, ev)
                self._emit_call('void', '', 'mojo_set_add_int', [('MojoSet *', t), ('int64_t', ev64)])
        return 'MojoSet *', t

    def _lower_tuple_literal(self, node: TupleExpr) -> tuple[str, str]:
        # Tuples lowered as MojoList (immutable semantics not enforced at C level)
        elem = self._infer_list_elem_type(node.elements)
        suf  = TypeLattice.list_suffix(elem)
        t    = self._new_temp('MojoList *')
        self._elem_types[t] = elem
        self._emit(f"  {t} = mojo_list_new ();")
        for el in node.elements:
            et, ev = self.lower_expr(el)
            ev_cast = self._cast_for_list(et, ev, suf)
            # GIMPLE: load global string literals into temp before function call
            if suf == 'str' and ev_cast.startswith('_slit_'):
                temp = self._new_temp('char *')
                self._emit(f'  {temp} = {ev_cast};')
                ev_cast = temp
            self._emit(f"  mojo_list_append_{suf} ({t}, {ev_cast});")
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

        res = self._new_temp(res_type)
        self._emit(f"  {res} = {res_new} ();")

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
        self._declare_var(gen0.target, 'int')
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
            cond_t = self._new_temp('_Bool')
            self._emit(f"  {cond_t} = {gen0.target} {cond_op} {stop_v};")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        st = self._new_temp('int')
        self._emit(f"  {st} = {gen0.target} + {step_v};")
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
            len64 = self._new_temp('int64_t'); idx64 = self._new_temp('int64_t')
            self._emit(f"  {len64} = mojo_list_len ({it_val});")
            self._emit(f"  {idx64} = (int64_t)0;")
            bb_cond = self._new_bb(); bb_body = self._new_bb()
            bb_post = self._new_bb(); bb_after = self._new_bb()
            self._emit(f"  goto {bb_cond};")
            self._emit_label(bb_cond)
            cond_t = self._new_temp('_Bool')
            self._emit(f"  {cond_t} = {idx64} < {len64};")
            self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
            self._emit_label(bb_body)
            raw_elem = self._new_temp('int64_t')
            self._emit(f"  {raw_elem} = mojo_list_get_int ({it_val}, {idx64});")
            sub_list = self._new_temp('MojoList *')
            self._emit(f"  {sub_list} = (MojoList *){raw_elem};")
            for i, vn in enumerate(var_names):
                i64 = self._new_temp('int64_t')
                self._emit(f"  {i64} = (int64_t){i};")
                sub_str = self._new_temp('char *')
                self._emit(f"  {sub_str} = mojo_list_get_str ({sub_list}, {i64});")
                sub_val = self._new_temp('int64_t')
                self._emit(f"  {sub_val} = (int64_t){sub_str};")
                self._emit(f"  {vn} = {sub_val};")
            self._gen_compr_append(node, gen0, res, res_type, bb_after)
            self._emit(f"  goto {bb_post};")
            self._emit_label(bb_post)
            one64 = self._new_temp('int64_t')
            self._emit(f"  {one64} = (int64_t)1;")
            st = self._new_temp('int64_t')
            self._emit(f"  {st} = {idx64} + {one64};")
            self._emit(f"  {idx64} = {st};")
            self._emit(f"  goto {bb_cond};")
            self._emit_label(bb_after)
            return
        elem = self._elem_of(it_val)
        self._declare_var(gen0.target, elem)
        len64 = self._new_temp('int64_t'); idx64 = self._new_temp('int64_t')
        self._emit(f"  {len64} = mojo_list_len ({it_val});")
        self._emit(f"  {idx64} = (int64_t)0;")
        bb_cond = self._new_bb(); bb_body = self._new_bb()
        bb_post = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {idx64} < {len64};")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        suf = TypeLattice.list_suffix(elem)
        if suf == 'double':
            self._emit(f"  {gen0.target} = mojo_list_get_double ({it_val}, {idx64});")
        elif suf == 'str':
            # mojo_list_get_str returns char*, handle type mismatch with target variable
            temp_str = self._new_temp('char *')
            self._emit(f"  {temp_str} = mojo_list_get_str ({it_val}, {idx64});")
            target_type = self._type_of(gen0.target)
            if target_type == 'char *':
                self._emit(f"  {gen0.target} = {temp_str};")
            else:
                # Cast to int64_t if target is opaque
                int_ptr = self._new_temp('int64_t')
                self._emit(f"  {int_ptr} = (int64_t){temp_str};")
                self._emit(f"  {gen0.target} = {int_ptr};")
        else:
            raw64 = self._new_temp('int64_t')
            self._emit(f"  {raw64} = mojo_list_get_int ({it_val}, {idx64});")
            self._emit(f"  {gen0.target} = ({elem}) {raw64};")
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        one64 = self._new_temp('int64_t')
        self._emit(f"  {one64} = (int64_t)1;")
        st = self._new_temp('int64_t')
        self._emit(f"  {st} = {idx64} + {one64};")
        self._emit(f"  {idx64} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _compr_str_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'char')
        len64 = self._new_temp('int64_t'); idx64 = self._new_temp('int64_t')
        self._emit(f"  {len64} = mojo_str_len ({it_val});")
        self._emit(f"  {idx64} = (int64_t)0;")
        bb_cond = self._new_bb(); bb_body = self._new_bb()
        bb_post = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {idx64} < {len64};")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        self._emit(f"  {gen0.target} = mojo_str_char_at ({it_val}, {idx64});")
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        one64 = self._new_temp('int64_t')
        self._emit(f"  {one64} = (int64_t)1;")
        st = self._new_temp('int64_t')
        self._emit(f"  {st} = {idx64} + {one64};")
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
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {more_t} != 0;")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")
        self._emit_label(bb_body)
        key_tmp = self._new_temp('const char *')
        self._emit(f"  {key_tmp} = mojo_dict_iter_key ({iter_t});")
        self._emit(f"  {gen0.target} = (char *) {key_tmp};")
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
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {more_t} != 0;")
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
                temp = self._new_temp('char *')
                self._emit(f'  {temp} = {ev_cast};')
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
            _, kv  = self.lower_expr(node.element)   # element = key expression in dict compr
            vt, vv = self.lower_expr(node.key)        # key field holds the value expression
            # parser stores dict comprehension as: element=key_expr, key=val_expr
            # Load global string literals into temps before passing to dict functions
            if kv.startswith('_slit_'):
                kv_tmp = self._new_temp('char *')
                self._emit(f"  {kv_tmp} = {kv};")
                kv = kv_tmp
            if vt in _FLOAT_TYPES:
                self._emit(f"  mojo_dict_set_double ({res}, {kv}, {vv});")
            elif vt == 'char *':
                if vv.startswith('_slit_'):
                    vv_tmp = self._new_temp('char *')
                    self._emit(f"  {vv_tmp} = {vv};")
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
                fmt = TypeLattice.printf_fmt(atype)
                self._emit(f'  {t} = (char *) malloc(256);')
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
        handler_name = _STMT_DISPATCH.get(type(node).__name__)
        if handler_name:
            getattr(self, handler_name)(node)
        else:
            self._emit(f"  /* TODO: {type(node).__name__} */")

    # ── Statement handlers (one per AST node type) ────────────────────────

    def _gen_stmt_PassStmt(self, node):
        return

    def _gen_stmt_VarDecl(self, node):
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
            self._safe_coerce_emit(vtype, ctype, v, self._cname(node.name))
        else:
            ctype = self._resolve_type(node.type_ann)
            self._declare_var(node.name, ctype)
        self._layout_hint = LayoutSolver.HEAP

    def _gen_stmt_AssignStmt(self, node):
        # Tuple unpacking: a, b, c = x, y, z
        if isinstance(node.target, TupleExpr):
            targets = node.target.elements
            if isinstance(node.value, TupleExpr):
                # RHS is a tuple literal — lower each element individually
                for tgt, rhs_expr in zip(targets, node.value.elements):
                    if isinstance(tgt, IdentExpr):
                        et, ev = self.lower_expr(rhs_expr)
                        if tgt.name not in self.var_types:
                            self._declare_var(tgt.name, et)
                        dst = self.var_types[tgt.name]
                        self._safe_coerce_emit(et, dst, ev, self._cname(tgt.name))
            else:
                # RHS is a single iterable — lower it, then index each element
                vtype, v = self.lower_expr(node.value)
                for i, tgt in enumerate(targets):
                    if isinstance(tgt, IdentExpr):
                        idx64 = self._new_temp('int64_t')
                        self._emit(f"  {idx64} = (int64_t){i};")
                        if vtype == 'MojoList *':
                            elem_type = self._elem_of(v)
                            suf = TypeLattice.list_suffix(elem_type)
                            et = elem_type if elem_type != 'unknown' else 'int64_t'
                            ev = self._new_temp(et)
                            self._emit(f"  {ev} = mojo_list_get_{suf} ({v}, {idx64});")
                        else:
                            et = 'int64_t'
                            ev = self._new_temp(et)
                            ip = self._new_temp('int64_t')
                            self._emit(f"  {ip} = (int64_t){v};")
                            self._emit(f"  {ev} = {ip};")
                        if tgt.name not in self.var_types:
                            self._declare_var(tgt.name, et)
                        dst = self.var_types[tgt.name]
                        self._safe_coerce_emit(et, dst, ev, self._cname(tgt.name))
            return
        vtype, v = self.lower_expr(node.value)
        if isinstance(node.target, IdentExpr):
            tname = node.target.name
            if tname not in self.var_types:
                self._declare_var(tname, vtype)
            dst = self.var_types[tname]
            if dst in ('MojoList *', 'MojoSet *') and v in self._elem_types:
                self._elem_types[tname] = self._elem_types[v]
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
                    elif actual_type == 'MojoDict *':
                        if v in self._elem_types:
                            self._elem_types[tname] = self._elem_types[v]
                        if v in self._dict_val_types:
                            self._dict_val_types[tname] = self._dict_val_types[v]
            self._safe_coerce_emit(vtype, dst, v, self._cname(tname))
        elif isinstance(node.target, MemberExpr):
            ot, ov = self.lower_expr(node.target.obj)
            if ot in ('int', 'int64_t'):
                # Opaque Python object: use mojo_setattr for attribute assignment
                member_str = node.target.member
                escaped = member_str.replace('\\', '\\\\').replace('"', '\\"')
                if escaped not in self._str_pool:
                    self._str_pool[escaped] = f'_slit_{10000 + len(self._str_pool)}'
                key_slit = self._str_pool[escaped]
                key_tmp = self._new_temp('char *')
                self._emit(f"  {key_tmp} = {key_slit};")
                v64 = self._new_temp('int64_t')
                self._safe_coerce_emit(vtype, 'int64_t', v, v64)
                obj64 = self._new_temp('int64_t')
                vp_tmp = self._new_temp('void *')
                self._emit(f"  {obj64} = (int64_t){ov};")
                self._emit(f"  {vp_tmp} = (void *){obj64};")
                self._emit_call('void', '', 'mojo_setattr',
                                [('void *', vp_tmp), ('char *', key_tmp), ('int64_t', v64)])
            else:
                op = '->' if '*' in ot else '.'
                struct_name = ot.replace(' *', '').strip()
                field_type = self.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
                self._safe_coerce_emit(vtype, field_type, v, f"{ov}{op}{node.target.member}")
        elif isinstance(node.target, SubscriptExpr):
            ot, obj_v = self.lower_expr(node.target.obj)
            it, idx_v  = self.lower_expr(node.target.index)
            if ot == 'MojoList *':
                elem = self._elem_of(obj_v)
                suf  = TypeLattice.list_suffix(elem)
                idx64 = self._new_temp('int64_t')
                self._emit(f"  {idx64} = (int64_t) {idx_v};")
                ev_cast = self._cast_for_list(vtype, v, suf)
                self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
            elif ot == 'MojoDict *':
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
                # Opaque int-typed dict: cast to MojoDict* and set
                if ot in ('int', 'int64_t'):
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
                    self._emit(f"  {obj_v}[{idx_v}] = {v};")
        else:
            # Skip emitting comment to avoid GIMPLE global-passing issues
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
                    ct = self._new_temp(arith)
                    self._emit(f"  {ct} = ({arith}){self._cname(tname)};")
                    lv_a = ct
                if rtype != arith:
                    ct = self._new_temp(arith)
                    self._emit(f"  {ct} = ({arith}){rv};")
                    rv_a = ct
                tmp = self._new_temp(arith)
                self._emit(f"  {tmp} = {lv_a} {c_op} {rv_a};")
                vtype, v = arith, tmp
            else:
                # Skip emitting comment to avoid GIMPLE global-passing issues
                return
        if isinstance(node.target, IdentExpr):
            tname = node.target.name
            dst   = self._type_of(tname)
            self._safe_coerce_emit(vtype, dst, v, self._cname(tname))
        elif isinstance(node.target, MemberExpr):
            ot, ov = self.lower_expr(node.target.obj)
            op     = '->' if '*' in ot else '.'
            self._emit(f"  {ov}{op}{node.target.member} = {v};")
        elif isinstance(node.target, SubscriptExpr):
            ot, obj_v = self.lower_expr(node.target.obj)
            _, idx_v  = self.lower_expr(node.target.index)
            if ot == 'MojoList *':
                elem = self._elem_of(obj_v)
                suf  = TypeLattice.list_suffix(elem)
                idx64 = self._new_temp('int64_t')
                self._emit(f"  {idx64} = (int64_t) {idx_v};")
                self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {v});")
            else:
                self._emit(f"  {obj_v}[{idx_v}] = {v};")
        else:
            self._emit("  /* TODO: complex aug-assign target */")

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
            if ret and ret != 'void' and vtype != ret:
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
                self._safe_coerce_emit(vtype, dst, v, self._cname(tname))
            elif isinstance(target, MemberExpr):
                ot, ov = self.lower_expr(target.obj)
                op = '->' if '*' in ot else '.'
                self._emit(f"  {ov}{op}{target.member} = {v};")
            elif isinstance(target, SubscriptExpr):
                ot, obj_v = self.lower_expr(target.obj)
                _, idx_v  = self.lower_expr(target.index)
                self._emit(f"  {obj_v}[{idx_v}] = {v};")
            else:
                self._emit("  /* TODO: complex multi-assign target */")

    def _gen_stmt_ForStmt(self, node):
        if (isinstance(node.iterable, CallExpr) and
                isinstance(node.iterable.func, IdentExpr) and
                node.iterable.func.name == 'range'):
            self._gen_for_range(node)
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
                fname_c  = _safe_name(lifted)
                if env_var:
                    env_type = self.func_param_types.get(lifted, ['void *'])[0]
                    full_arg_pairs = [(env_type, env_var)] + arg_pairs
                else:
                    full_arg_pairs = arg_pairs
                self._emit_call('void', '', fname_c, full_arg_pairs)
                return
            fname     = _safe_name(raw_name)
            arg_pairs = [self.lower_expr(a) for a in node.value.args]
            if fname in self._KNOWN_SIGS:
                ret_type = self._KNOWN_SIGS[fname][0]
                self._emit_call(ret_type, '', fname, arg_pairs)
            else:
                arg_vals = [v for _, v in arg_pairs]
                self._emit(f"  {fname} ({', '.join(arg_vals)});")
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
                tmp = self._new_temp(et)
                self._emit(f"  {tmp} = {ev};")
                alias = tmp
            struct_name = et.replace(' *', '').strip()
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
                    tmp = self._new_temp(vtype)
                    self._emit(f"  {tmp} = {self._env_param}->{vname};")
                    self._emit(f"  {env_var}->{vname} = {tmp};")
                else:
                    self._emit(f"  {env_var}->{vname} = {vname};")
            self._closure_envs[node.name] = env_var
        else:
            self._closure_envs[node.name] = ''

    def _gen_stmt_ImportStmt(self, node):
        # import module_name [as alias] - record for extern declarations
        local_name = node.alias if node.alias else node.module
        self.imported_symbols[local_name] = {
            'module': node.module,
            'return_type': 'unknown',
        }
        # Declare the module as an int marker for attribute access
        # This allows code like os.path.basename() to work
        if local_name not in self.var_types:
            self._declare_var(local_name, 'int')
            self._emit(f"  {local_name} = 0;  /* module marker */")


    def _gen_stmt_FromImportStmt(self, node):
        # from module import name1, name2, ...
        for name, alias in node.names:
            symbol_name = alias if alias else name
            self.imported_symbols[symbol_name] = {
                'module': node.module,
                'return_type': 'int',  # Default to int for imported functions
            }
            # Track in func_return_types so calls know the return type
            if symbol_name not in self.func_return_types:
                self.func_return_types[symbol_name] = 'int'

    def _gen_stmt_ComptimeIfStmt(self, node):
        val = self._eval_const_bool(node.condition)
        if val is True:
            for s in node.then_body:
                self.gen_stmt(s)
        elif val is False:
            if node.else_body:
                for s in node.else_body:
                    self.gen_stmt(s)
        else:
            _, cond_v = self.lower_expr(node.condition)
            bb_true  = self._new_bb()
            bb_merge = self._new_bb()
            bb_false = self._new_bb() if node.else_body else bb_merge
            self._emit(f"  if ({cond_v}) goto {bb_true}; else goto {bb_false};")
            self._emit_label(bb_true)
            for s in node.then_body:
                self.gen_stmt(s)
            self._emit(f"  goto {bb_merge};")
            if node.else_body:
                self._emit_label(bb_false)
                for s in node.else_body:
                    self.gen_stmt(s)
                self._emit(f"  goto {bb_merge};")
            self._emit_label(bb_merge)

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
                    self._declare_var(node.target, 'int')
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

        self._declare_var(var, 'int')
        _, start_v = self.lower_expr(start_expr)
        _, stop_v  = self.lower_expr(stop_expr)
        _, step_v  = self.lower_expr(step_expr)
        self._emit(f"  {var} = {self._coerce('int', 'int', start_v)};")

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
            self._emit(f"  {t_spos} = {step_v} > 0;")
            self._emit(f"  {cond_t} = {t_spos} ? {t_lt} : {t_gt};")
        else:
            cond_t = self._new_temp('_Bool')
            self._emit(f"  {cond_t} = {var} {cond_op} {stop_v};")
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
        step_t = self._new_temp('int')
        self._emit(f"  {step_t} = {var} + {step_v};")
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
            base = it_type.replace(' *', '').strip()
            has_next = f"{base}___has_next__"
            nxt      = f"{base}___next__"
            if has_next in self.func_return_types or nxt in self.func_return_types:
                self._gen_for_struct_iter(var, it_type, it_val, node.body)
            else:
                self._emit(f"  /* TODO: for loop over {it_type} (no iterator protocol) */")
        else:
            self._emit(f"  /* TODO: for loop over {it_type} */")

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
        len_t = self._new_temp('int')
        idx_t = self._new_temp('int')
        # Cast it_val back to MojoList* if it's stored as int64_t (from method call)
        list_ptr = it_val
        if it_val in self.var_types and self.var_types[it_val] == 'int64_t':
            list_ptr = self._new_temp('MojoList *')
            self._emit(f"  {list_ptr} = (MojoList *){it_val};")
        self._emit(f"  {len64} = mojo_list_len ({list_ptr});")
        self._emit(f"  {len_t} = (int) {len64};")
        self._emit(f"  {idx_t} = 0;")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {idx_t} < {len_t};")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        idx64  = self._new_temp('int64_t')
        self._emit(f"  {idx64} = (int64_t) {idx_t};")
        if is_tuple:
            elem64 = self._new_temp('int64_t')
            self._emit(f"  {elem64} = mojo_list_get_int ({list_ptr}, {idx64});")
            tuple_ptr = self._new_temp('MojoList *')
            self._emit(f"  {tuple_ptr} = (MojoList *){elem64};")
            for i, vn in enumerate(var_names):
                # mojo_list_get_str returns char*, but var is int64_t
                temp_str = self._new_temp('char *')
                self._emit(f"  {temp_str} = mojo_list_get_str ({tuple_ptr}, {i});")
                int_ptr = self._new_temp('int64_t')
                self._emit(f"  {int_ptr} = (int64_t){temp_str};")
                self._emit(f"  {vn} = {int_ptr};")
        else:
            suf = TypeLattice.list_suffix(elem)
            if suf == 'double':
                self._emit(f"  {var} = mojo_list_get_double ({list_ptr}, {idx64});")
            elif suf == 'str':
                # mojo_list_get_str returns char*, but var might be int64_t
                # Use a temp to handle the conversion
                temp_str = self._new_temp('char *')
                self._emit(f"  {temp_str} = mojo_list_get_str ({list_ptr}, {idx64});")
                # If var is int64_t, cast the char* to it; otherwise assign directly
                if self._type_of(var) == 'char *':
                    self._emit(f"  {var} = {temp_str};")
                else:
                    # Cast char* to int64_t (opaque pointer storage)
                    int_ptr = self._new_temp('int64_t')
                    self._emit(f"  {int_ptr} = (int64_t){temp_str};")
                    self._emit(f"  {var} = {int_ptr};")
            else:
                elem64 = self._new_temp('int64_t')
                self._emit(f"  {elem64} = mojo_list_get_int ({list_ptr}, {idx64});")
                self._emit(f"  {var} = ({elem}) {elem64};")
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        st = self._new_temp('int')
        self._emit(f"  {st} = {idx_t} + 1;")
        self._emit(f"  {idx_t} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _gen_for_str(self, var: str, it_val: str, body: list):
        self._declare_var(var, 'char')
        len64 = self._new_temp('int64_t')
        len_t = self._new_temp('int')
        idx64 = self._new_temp('int64_t')
        idx_t = self._new_temp('int')
        self._emit(f"  {len64} = mojo_str_len ({it_val});")
        self._emit(f"  {len_t} = (int) {len64};")
        self._emit(f"  {idx_t} = 0;")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {idx_t} < {len_t};")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        self._emit(f"  {idx64} = (int64_t) {idx_t};")
        self._emit(f"  {var} = mojo_str_char_at ({it_val}, {idx64});")
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        st = self._new_temp('int')
        self._emit(f"  {st} = {idx_t} + 1;")
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
            dict_ptr = self._new_temp('MojoDict *')
            self._emit(f"  {dict_ptr} = (MojoDict *){it_val};")
            it_val = dict_ptr
        iter_t = self._new_temp('MojoDictIter *')
        more_t = self._new_temp('int')
        self._emit(f"  {iter_t} = mojo_dict_iter_new ({it_val});")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        self._emit(f"  {more_t} = mojo_dict_iter_next ({iter_t});")
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {more_t} != 0;")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        key_tmp = self._new_temp('const char *')
        self._emit(f"  {key_tmp} = mojo_dict_iter_key ({iter_t});")
        if is_tuple:
            # Assign key to first name, NULL (zero) to remaining names
            self._emit(f"  {var_names[0]} = (char *) {key_tmp};")
            for vn in var_names[1:]:
                self._emit(f"  {vn} = (char *)0;")
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
        iter_t = self._new_temp('MojoSetIter *')
        more_t = self._new_temp('int')
        self._emit(f"  {iter_t} = mojo_set_iter_new ({it_val});")

        bb_cond  = self._new_bb(); bb_body  = self._new_bb()
        bb_post  = self._new_bb(); bb_after = self._new_bb()
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_cond)
        self._emit(f"  {more_t} = mojo_set_iter_next ({iter_t});")
        cond_t = self._new_temp('_Bool')
        self._emit(f"  {cond_t} = {more_t} != 0;")
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
        for i, (pname, ptype) in enumerate(node.params):
            if ci.is_re_sub_callback and i == 0:
                # First (match) param is always char * for re.sub callbacks
                ctype = 'char *'
            elif ptype is None and pname in inferred_params:
                ctype = inferred_params[pname]
            else:
                ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype
            ci.inferred_params[pname] = ctype   # cache for forward decl in Phase 2b
            param_strs.append(f"{ctype} {pname}")
        ci.inferred_ret = ret_type               # cache for forward decl in Phase 2b
        # Update func_return_types so callers generated after this closure see the right type
        self.func_return_types[ci.lifted_name] = ret_type
        # Register param types so _emit_call can coerce arguments at closure call sites
        closure_param_ctypes = []
        if ci.env_struct:
            closure_param_ctypes.append(f"{ci.env_struct} *")
        for pname, _ in node.params:
            closure_param_ctypes.append(ci.inferred_params.get(pname, 'int'))
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
        base = struct_type.replace(' *', '').strip()

        # Determine iterator type (may be the same struct or a separate iter type)
        iter_fn = f"{base}___iter__"
        if iter_fn in self.func_return_types:
            iter_type = self.func_return_types[iter_fn]
            iter_var  = self._new_temp(iter_type)
            self._emit(f"  {iter_var} = {iter_fn} ({obj_val});")
            iter_base = iter_type.replace(' *', '').strip()
        else:
            iter_type = struct_type
            iter_var  = obj_val
            iter_base = base

        has_next_fn = f"{iter_base}___has_next__"
        next_fn     = f"{iter_base}___next__"
        elem_type   = self.func_return_types.get(next_fn, 'int')
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
            cond_t = self._new_temp('_Bool')
            self._emit(f"  {cond_t} = 0;  /* TODO: no __has_next__ on {iter_base} */")
        self._emit(f"  if ({cond_t}) goto {bb_body}; else goto {bb_after};")

        self._loop_depth += 1
        self._emit_label(bb_body, f'count(guessed_local({10 ** self._loop_depth}))')
        if next_fn in self.func_return_types:
            nxt = self._new_temp(elem_type)
            self._emit(f"  {nxt} = {next_fn} ({iter_var});")
            self._emit(f"  {var} = {nxt};")
        else:
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

    def _param_ctype(self, pname: str, ptype, node: FunctionDef,
                     is_self: bool = False) -> str:
        """Resolve parameter C type, applying argument convention qualifiers."""
        if is_self:
            return f"{node.name} *"
        # Check inferred parameter types first (for unannotated parameters)
        if ptype is None and hasattr(self, '_inferred_param_types'):
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

    def gen_func(self, node: FunctionDef) -> str:
        self._reset_func()
        self.current_func_name = node.name

        # Seed param types into var_types BEFORE return-type inference so
        # _quick_type can resolve param names during the pre-pass.
        for pname, ptype in node.params:
            self.var_types[pname] = self._resolve_type(ptype)

        # Determine return type: annotation takes priority; infer if absent.
        if node.return_type is not None:
            ret_type = self._resolve_type(node.return_type)
        else:
            ret_type = self._infer_return_type(node.body)
            # Special case: main() should return int, not void
            if node.name == 'main' and ret_type == 'void':
                ret_type = 'int'

        self.func_ret_type = ret_type
        # Sync so forward declarations (Phase 2b) match Phase 2a inference
        self.func_return_types[node.name] = ret_type

        # Run layout solver for struct locals
        solver = LayoutSolver(self.struct_field_types)
        self._struct_layout = solver.solve(node.params, node.body)

        param_strs = []
        for pname, ptype in node.params:
            ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype  # re-register with qualified type
            param_strs.append(f"{ctype} {pname}")

        params_str = ', '.join(param_strs) if param_strs else 'void'
        safe = _safe_name(node.name)

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

        # For main function, rename to _gimple_main and create wrapper
        if node.name == 'main':
            safe = '_gimple_main'

        lines = [
            f"{ret_type} {safe} ({params_str})",
            "{",
            *self.decls,
            *self.body_lines,
            "}",
        ]

        # Generate C wrapper for main that optionally initializes Python
        if node.name == 'main':
            lines.append("")
            lines.append(f"int main (int argc, const char **argv) {{")
            lines.append(f"  mojo_set_argv(argc, argv);")
            lines.append(f"#if USE_PYTHON")
            lines.append(f"  Py_Initialize ();")
            lines.append(f"#endif")
            lines.append(f"  {ret_type} result = {safe} ();")
            lines.append(f"#if USE_PYTHON")
            lines.append(f"  Py_Finalize ();")
            lines.append(f"#endif")
            lines.append(f"  return result;")
            lines.append(f"}}")

        return '\n'.join(lines)

    # ── Struct method generation ──────────────────────────────────────────

    def _gen_struct_method(self, struct_name: str, node: FunctionDef) -> str:
        self._reset_func()
        self.current_func_name = f"{struct_name}_{node.name}"

        # Seed param types for pre-pass inference
        for i, (pname, ptype) in enumerate(node.params):
            if i == 0 and pname == 'self':
                self.var_types[pname] = f"{struct_name} *"
            else:
                self.var_types[pname] = self._resolve_type(ptype)

        if node.return_type is not None:
            ret_type = self._resolve_type(node.return_type)
        else:
            ret_type = self._infer_return_type(node.body)
            if ret_type == 'void':
                ret_type = 'void'

        self.func_ret_type = ret_type
        # Sync so forward declarations (Phase 2b) match Phase 2a inference
        self.func_return_types[f"{struct_name}_{node.name}"] = ret_type

        solver = LayoutSolver(self.struct_field_types)
        self._struct_layout = solver.solve(node.params, node.body)

        method_full_name = f"{struct_name}_{node.name}"
        param_strs = []
        for i, (pname, ptype) in enumerate(node.params):
            if i == 0 and pname == 'self':
                ctype = f"{struct_name} *"
            else:
                # Check inferred parameter types first (for unannotated parameters)
                if ptype is None and hasattr(self, '_inferred_param_types'):
                    if method_full_name in self._inferred_param_types and pname in self._inferred_param_types[method_full_name]:
                        ctype = self._inferred_param_types[method_full_name][pname]
                    else:
                        ctype = self._resolve_type(ptype)
                else:
                    ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype
            param_strs.append(f"{ctype} {pname}")

        params_str = ', '.join(param_strs) if param_strs else 'void'
        mangled    = f"{struct_name}_{_safe_name(node.name)}"

        self._emit_label("bb_2")
        for stmt in node.body:
            self.gen_stmt(stmt)

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
        # Pre-register current module's own function names into _global_inline_defs
        # BEFORE Phase 0 so that recursive sub-module compilations see them.
        for _s in stmts:
            if isinstance(_s, FunctionDef):
                self._global_inline_defs.add(_s.name)
            elif isinstance(_s, StructDef):
                for _m in _s.methods:
                    self._global_inline_defs.add(_m.name)
                    self._global_inline_defs.add(f"{_s.name}_{_m.name}")

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
                        modules_to_compile.add(stmt.module)
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

        # Pre-populate known interpreter structs with their field types
        # This handles cases where field type inference from method bodies fails
        self.struct_field_types['Scope'] = {
            'parent': 'Scope *',
            'vars': 'MojoDict *',
        }
        self.struct_field_types['ReturnValue'] = {
            'value': 'int',
        }
        self.struct_field_types['BreakException'] = {}
        self.struct_field_types['ContinueException'] = {}
        self.struct_field_types['MojoFunction'] = {
            'name': 'int',
            'params': 'MojoList *',
            'body': 'MojoList *',
            'closure_scope': 'Scope *',
        }
        self.struct_field_types['MojoClass'] = {
            'name': 'int',
            'body': 'MojoList *',
            'methods': 'MojoDict *',
        }
        self.struct_field_types['Interpreter'] = {
            'scope': 'Scope *',
        }

        # Pre-populate AST node struct fields
        self.struct_field_types['CallExpr'] = {
            'func': 'int',
            'args': 'MojoList *',
        }
        self.struct_field_types['BinaryOp'] = {
            'op': 'char *',
            'left': 'int',
            'right': 'int',
        }
        self.struct_field_types['UnaryOp'] = {
            'op': 'char *',
            'operand': 'int',
        }
        self.struct_field_types['TernaryExpr'] = {
            'condition': 'int',
            'then_val': 'int',
            'else_val': 'int',
        }
        self.struct_field_types['MemberExpr'] = {
            'obj': 'int',
            'member': 'char *',
        }
        self.struct_field_types['SubscriptExpr'] = {
            'obj': 'int',
            'index': 'int',
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
                                        ft = param_types.get(v.name, 'int')
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
                            pm[pname] = self._resolve_type(ptype) if ptype else 'int'
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
        self.func_return_types = dict(_RUNTIME_FUNCS)
        all_struct_defs_for_types = stmts + (imported_stmts if self.do_imports else [])
        for s in all_struct_defs_for_types:
            if isinstance(s, StructDef):
                self.func_return_types[s.name] = f"{s.name} *"

        # Process imports: load modules and register imported symbols
        self.imported_symbols = {}  # symbol_name -> symbol_info_dict
        for s in stmts:
            if isinstance(s, FromImportStmt):
                try:
                    exports = load_module(s.module)
                    for name, alias in s.names:
                        sym_name = alias if alias else name
                        sym_info = exports.get(name, {})

                        # Handle both old format (string) and new format (dict)
                        if isinstance(sym_info, str):
                            # Legacy format: just return type
                            sym_type = sym_info
                            self.imported_symbols[sym_name] = {
                                'module': s.module,
                                'original_name': name,
                                'return_type': sym_type,
                                'parameters': [],
                                'signature': f"{sym_type} {sym_name} (void)"
                            }
                            self.func_return_types[sym_name] = sym_type
                        else:
                            # New format: full signature info
                            sym_info['module'] = s.module
                            sym_info['original_name'] = name
                            self.imported_symbols[sym_name] = sym_info
                            if 'c_return_type' in sym_info:
                                self.func_return_types[sym_name] = sym_info['c_return_type']
                except Exception:
                    # Gracefully ignore module load errors
                    pass

        # Register user function return types (from current + imported modules)
        #   Pass 1: annotated return types (authoritative)
        all_functions = stmts + (imported_stmts if self.do_imports else [])
        for s in all_functions:
            if isinstance(s, FunctionDef) and s.return_type is not None:
                self.func_return_types[s.name] = self._resolve_type(s.return_type)
            # Register parameter types (for call-site coercion via _emit_call)
            if isinstance(s, FunctionDef) and s.params:
                self.func_param_types[s.name] = [self._param_ctype(pn, pt, s) for pn, pt in s.params]
        #   Pass 1b: struct method annotated return types + param types (from current + imported modules)
        all_structs_for_methods = stmts + (imported_stmts if self.do_imports else [])
        for s in all_structs_for_methods:
            if isinstance(s, StructDef):
                for m in s.methods:
                    mangled = f"{s.name}_{m.name}"
                    if m.return_type is not None:
                        self.func_return_types[mangled] = self._resolve_type(m.return_type)
                    # Also store method param types using the mangled name (for call-site arg padding)
                    if m.params:
                        ctypes = []
                        for i, (pn, pt) in enumerate(m.params):
                            if i == 0 and pn == 'self':
                                ctypes.append(f"{s.name} *")
                            else:
                                ctypes.append(self._param_ctype(pn, pt, m))
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
                    inferred = 'int'
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

            # Enrich outer_scope with untyped local variable assignments for capture detection.
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
                free_globals = set(self.func_return_types.keys())
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
                for method in s.methods:
                    outer_name = f"{s.name}_{method.name}"
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
        for _scan_stmt in stmts + (imported_stmts if self.do_imports else []):
            if isinstance(_scan_stmt, AssignStmt) and isinstance(_scan_stmt.target, IdentExpr):
                _gname = _scan_stmt.target.name
                if _gname in _pre_declared_globals:
                    continue
                _pre_declared_globals.add(_gname)
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
                self._global_var_types[_scan_stmt.name] = self._resolve_type(_scan_stmt.type_ann) if _scan_stmt.type_ann else 'int64_t'

        # Also scan ImportStmts inside TryStmt/IfStmt blocks (e.g., try: import mojo_compiler)
        # These are missed by the flat scan above.
        def _scan_try_imports(stmt_list):
            for _s in stmt_list:
                if isinstance(_s, ImportStmt):
                    _local = _s.alias if _s.alias else _s.module
                    if _local not in self._global_var_types:
                        self._global_var_types[_local] = 'int64_t'
                        self._global_c_decl_types[_local] = 'int64_t'
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

        def _emit_closure_recursive(ci) -> None:
            """Emit sub-closures first (depth-first), then this closure's allocator + body."""
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

        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                for ci in self._all_closures.get(stmt.name, {}).values():
                    _emit_closure_recursive(ci)
                func_parts.append(self.gen_func(stmt))
                func_parts.append('')
            elif isinstance(stmt, StructDef):
                for m in stmt.methods:
                    method_outer_name = f"{stmt.name}_{m.name}"
                    # Emit lifted closures for this method (if any), recursively
                    for ci in self._all_closures.get(method_outer_name, {}).values():
                        _emit_closure_recursive(ci)
                    func_parts.append(self._gen_struct_method(stmt.name, m))
                    func_parts.append('')
            elif isinstance(stmt, TraitDef):
                lines = [f"typedef struct {stmt.name}_vtable {{"]
                for m in stmt.methods:
                    ret    = self._resolve_type(m.return_type)
                    ptypes = (', '.join(self._resolve_type(pt) for _, pt in m.params)
                              if m.params else 'void')
                    lines.append(f"  {ret} (*{m.name}) ({ptypes});")
                lines.append(f"}} {stmt.name}_vtable;")
                func_parts.extend(lines)
                func_parts.append('')
            elif isinstance(stmt, (ImportStmt, FromImportStmt)):
                pass  # Imports processed in pre-pass; extern declarations generated in preamble
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, IdentExpr):
                # Module-level assignment: e.g. _STMT_DISPATCH = {...}
                gname = stmt.target.name
                if isinstance(stmt.value, DictExpr):
                    func_parts.append(f"/* global dict {gname} — declared as MojoDict * */")
                elif isinstance(stmt.value, (ListExpr, TupleExpr)):
                    func_parts.append(f"/* global list {gname} — declared as MojoList * */")
                elif isinstance(stmt.value, SetExpr):
                    func_parts.append(f"/* global set {gname} — declared as MojoSet * */")
                else:
                    func_parts.append(f"/* TODO: global {gname} */")
            else:
                func_parts.append(f"/* TODO: top-level {type(stmt).__name__} */")

        # ── Phase 2b: assemble final C output ────────────────────────────

        parts = [
            '/* Generated by gimple_codegen.py */',
            '/* Compile with: gcc-mp-15 -fgimple -fsyntax-only file.c */',
            '#define USE_PYTHON 0',
            '#include <stdint.h>',
            '#include <stdlib.h>',
            '#include <string.h>',
            '#include <math.h>',
            '#include <stdio.h>',
            '#include <setjmp.h>',
            '#if USE_PYTHON',
            '#include <Python.h>',
            '#endif',
            '#include <mojo_runtime.h>',
            'void mojo_print(char *str);',
            'char *gimple_codegen_compile_to_gimple(char *src);',
            'char *compile_to_gimple(char *mojo_src, int do_imports);',
            'int64_t mojo_open_file(char *path);',
            'void *mojo_open(char *filename, char *mode);',
            'int64_t int_write (int64_t, char *);',
            'int64_t int_parse_module (int);',
        ]

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
                    parts.append(f"typedef struct {struct_name} {{")
                    if fields:
                        for field_name, field_type in sorted(fields.items()):
                            # For self-references in typedef, use 'struct Name *' syntax
                            if field_type == f"{struct_name} *":
                                # Change Scope * to struct Scope * for self-references
                                field_type = f"struct {struct_name} *"
                            parts.append(f"  {field_type} {field_name};")
                    else:
                        # Empty struct - add a dummy field for valid C
                        parts.append(f"  int _dummy;")
                    parts.append(f"}} {struct_name};")
                    emitted.add(struct_name)
                    self._emitted_structs.add(struct_name)  # track for dedup in Section 2
            parts.append('')

        # Include compiled imported modules
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
        global_decls = []
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
        if global_decls:
            parts.extend(global_decls)
            parts.append('')

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
            for s in stmts + (imported_stmts if self.do_imports else []):
                if isinstance(s, StructDef):
                    field_count = len([f for f in s.fields if isinstance(f, VarDecl)])
                    if s.name not in track_best or field_count > track_best[s.name][1]:
                        track_best[s.name] = (s, field_count)

            for sd, _ in track_best.values():
                if sd.name not in self._emitted_structs:
                    parts.append(f"typedef struct {sd.name} {{")
                    emitted_fields = set()
                    for field in sd.fields:
                        if isinstance(field, VarDecl):
                            # Use inferred type from struct_field_types, or resolve from annotation
                            if sd.name in self.struct_field_types and field.name in self.struct_field_types[sd.name]:
                                ft = self.struct_field_types[sd.name][field.name]
                            else:
                                ft = self._resolve_type(field.type_ann) if field.type_ann else 'int'
                            parts.append(f"  {ft} {field.name};")
                            emitted_fields.add(field.name)
                    # Also emit any fields that are in struct_field_types but not in AST fields
                    if sd.name in self.struct_field_types:
                        for field_name, field_type in self.struct_field_types[sd.name].items():
                            if field_name not in emitted_fields:
                                parts.append(f"  {field_type} {field_name};")
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
                f"{sn} * __GIMPLE _alloc_{sn} (void)\n"
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

            if 'signature' in sym_info:
                # New format: use full signature with parameters
                signature = sym_info['signature']
                module = sym_info['module']
                parts.append(f"extern {signature};  /* from {module} */")
            else:
                # Legacy format fallback - use empty parens for flexible signature
                ret_type = sym_info.get('return_type', 'int')
                module = sym_info.get('module', '')
                ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
                parts.append(f"extern {ret_type} {_safe_name(sym_name)} ();  /* from {module} */")

        if self.imported_symbols:
            parts.append('')

        # Forward declarations: free functions (skip main — handled specially)
        func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
        for fn in func_defs:
            if fn.name == 'main':
                continue
            ret    = self.func_return_types.get(fn.name, 'int')
            param_ctypes = [self._param_ctype(pn, pt, fn) for pn, pt in fn.params] if fn.params else []
            ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
            parts.append(f"{ret} {_safe_name(fn.name)} ({ptypes});")
            # Record parameter types for call-site coercion
            self.func_param_types[fn.name] = param_ctypes

        # Forward declarations: struct methods
        # When do_imports=True, imported code is inlined and already contains its own
        # forward declarations — don't re-emit them with potentially stale types.
        struct_defs = [s for s in stmts if isinstance(s, StructDef)]
        if not self.do_imports:
            struct_defs += [s for s in (imported_stmts or []) if isinstance(s, StructDef)]
        for sd in struct_defs:
            for m in sd.methods:
                ret = self.func_return_types.get(f"{sd.name}_{m.name}",
                                                  self._resolve_type(m.return_type))
                param_ctypes = []
                # Use the full func name for parameter type inference
                method_full_name = f"{sd.name}_{m.name}"
                for i, (pname, ptype) in enumerate(m.params):
                    if i == 0 and pname == 'self':
                        ct = f"{sd.name} *"
                    else:
                        # Check inferred parameter types first (for unannotated parameters)
                        if ptype is None and hasattr(self, '_inferred_param_types'):
                            if method_full_name in self._inferred_param_types and pname in self._inferred_param_types[method_full_name]:
                                ct = self._inferred_param_types[method_full_name][pname]
                            else:
                                ct = self._resolve_type(ptype)
                        else:
                            ct = self._resolve_type(ptype)
                    param_ctypes.append(ct)
                ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
                parts.append(f"{ret} {sd.name}_{_safe_name(m.name)} ({ptypes});")

        if func_defs or struct_defs:
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
                ret  = ci.inferred_ret if ci.inferred_ret else self.func_return_types.get(ci.lifted_name, 'int')
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
            parts.append("/* String literal globals (char * to avoid char[]→char* conversion) */")
            if self.emit_str_pool:
                # Main module: emit full definitions
                for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                    parts.append(f'char * {sname} = "{escaped}";')
            else:
                # Imported module: emit extern declarations only
                for escaped, sname in sorted(self._str_pool.items(), key=lambda x: x[1]):
                    parts.append(f'extern char * {sname};')
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

        return '\n'.join(parts)


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

def compile_to_gimple(mojo_src: str, do_imports: bool = False) -> str:
    """Parse Mojo source and return a C string with __GIMPLE annotations.

    If do_imports=True, recursively compile imported modules and inline their code.
    If do_imports=False, generate extern declarations for imports.
    """
    tokens = tokenize(mojo_src)
    stmts  = Parser(tokens).parse_module()
    return GimpleGen(do_imports=do_imports).gen_module(stmts)
