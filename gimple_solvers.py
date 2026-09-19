"""Mechanically extracted from gimple_codegen.py — Wave-1 parallel extraction, agent A4 (region M2).

Contains the escape-analysis helpers and whole-program solvers, copied
verbatim (byte-identical bodies/comments) from their original locations:

  - _find_idents / _scan_for_escaping / _find_escaping (module-level helpers)
  - EscapeAnalyzer   (~gimple_codegen.py:332)
  - LayoutSolver     (~gimple_codegen.py:411)
  - DispatchTable    (~gimple_codegen.py:489)
  - DispatchPattern  (~gimple_codegen.py:642)
  - DispatchSolver   (~gimple_codegen.py:666)
  - FunctionCompilability (~gimple_codegen.py:1388)
  - TypePromotionSolver   (~gimple_codegen.py:1539)
  - ClosureInfo      (~gimple_codegen.py:4081)

These classes intentionally do NOT reference GimpleGen or any mixin.
Names they use that are owned elsewhere are recorded as unresolved in
refactor_manifest.json (e.g. _C_RESERVED_FUNCS).
"""
from __future__ import annotations

# Mirrors gimple_codegen.py's own fire_compiler import block; only the AST
# node types these extracted regions actually reference are listed here.
from fire_compiler import (
    AssignStmt, BinaryOp, CallExpr, CompareChain, DictExpr, ExprStmt,
    ForStmt, FunctionDef, IdentExpr, IfStmt, ListExpr, MemberExpr,
    ReturnStmt, SetExpr, SliceExpr, StringLiteral, StructDef,
    SubscriptExpr, TernaryExpr, TryStmt, TupleExpr, UnaryOp, VarDecl,
    WhileStmt, WithStmt,
)

from gimple_ctypes import _C_RESERVED_FUNCS

# ---------------------------------------------------------------------------
# EscapeAnalyzer — conservative escape analysis for struct locals
# ---------------------------------------------------------------------------

# Standalone functions for escape analysis (to avoid object method transpilation issues)
def _find_idents(node) -> set:
    """Recursively find all identifiers in an AST node."""
    if isinstance(node, IdentExpr):           return {node.name}
    if isinstance(node, BinaryOp):            return _find_idents(node.left) | _find_idents(node.right)
    if isinstance(node, CompareChain):
        r = set()
        for o in node.operands: r |= _find_idents(o)
        return r
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
    # Plain unpack, NOT `{p[0] for p in params}` — subscripting a value
    # obtained by comprehension-iterating a real list[tuple[str, str]]
    # AST field is the established self-hosted trap (working `==` but
    # corrupted `len()`/hashing on the subscripted slot; see
    # bugs/CODEGEN_selfhost_actual_types_identifier_field_key.md), and
    # this feeds the LayoutSolver's stack-vs-heap escape analysis — a
    # wrong `in_scope` here risks stack-allocating something that
    # actually escapes.
    in_scope: set[str] = set()
    for _pn, _pt in params:
        in_scope.add(_pn)
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
        # Plain unpack, NOT `{p[0] for p in params}` — see _find_escaping's
        # identical fix above for why.
        in_scope: set[str] = set()
        for _pn, _pt in params:
            in_scope.add(_pn)
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
        if isinstance(node, CompareChain):
            r = set()
            for o in node.operands: r |= self._idents(o)
            return r
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

    def __init__(self, struct_field_types: dict, func_return_types: dict,
                 allow_assume_all_methods: bool = False,
                 generator_method_api: dict | None = None):
        self.struct_field_types = struct_field_types
        self.func_return_types = func_return_types
        # (struct_name, method_name) -> api dict for every struct method
        # compiled as a real C++20 coroutine generator (GimpleGen's own
        # `self._generator_method_api`, Milestone C step 3 — see that
        # attribute's declaration for the full mechanism). A generator
        # method's only real callable surface is its `<base>_start/_resume/
        # _value/_destroy` coroutine API; there is no ordinary
        # `struct_method_csym`-mangled C function for it at all (gen_module's
        # Phase 2a skips emitting one). `_plan_dispatch_tables` consults this
        # to drop such a callee from a planned FUNC_POINTER dispatch table
        # rather than emitting a struct-initializer field referencing that
        # never-emitted plain symbol — same detection `_lower_bound_method_
        # value` already uses for the analogous bare-value-reference case
        # (`f = self.gen_method`); see that method's own docstring and
        # bugs/CODEGEN_generator_function_Lib_subprocess.md.
        self.generator_method_api = generator_method_api or {}
        # Gate for the "assume all methods might be called" fallback in
        # _analyze_getattr_pattern (see that method's own comment and
        # bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_misfires_on_ordinary_code.md).
        # That fallback exists ONLY to make this compiler's own self-hosted
        # `Interpreter.execute`-style `getattr(self, f'execute_{...}')(node)`
        # dispatch idiom compile — it is a real false-positive magnet on
        # ordinary code (`getattr(self, attr)` for plain attribute
        # delegation, e.g. `__getattribute__`/`__getattr__` overrides are a
        # common Python idiom with nothing to do with a dispatch table).
        # Restrict it to firing only when compiling this repo's own
        # self-hosting source (root file under _SELFHOST_DIR, see
        # `_is_selfhost_file` at this class's call site in gen_module) —
        # every other compile (ordinary stdlib/user files) skips the
        # fallback entirely rather than roping in every method of the
        # enclosing struct as a bogus dispatch-table callee.
        self.allow_assume_all_methods = allow_assume_all_methods
        # Bare callee C name -> (owning struct, real Python method name),
        # for the two struct_methods entries this solver knows about;
        # populated by _plan_dispatch_tables alongside its own local
        # reverse maps so a caller holding only `get_dispatch_tables()`
        # output can still recover WHICH struct/method each table row
        # refers to. gen_module uses it to re-resolve each row's symbol
        # through GimpleGen._struct_method_csym (the one composer every
        # emitted method symbol must go through) — see the "dispatch
        # table callee qualification" fix-up right after analyze()'s call
        # site: rows are registered bare (`f"{stmt.name}_{method.name}"`)
        # but a non-root module's methods are EMITTED under
        # `{home_module}_{Struct}_{method}`, and a table initializer
        # naming the bare spelling is an undeclared-symbol GCC error
        # (bugs/hard/CODEGEN_selfhost_getattr_dispatch_heuristic_
        # misfires_on_ordinary_code.md's residual "option 3" gap).
        self.callee_home: dict = {}
        self.callee_method: dict = {}

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
        """Return a list of all expression nodes in statement list."""
        result = []
        for stmt in stmts:
            if isinstance(stmt, ExprStmt):
                result.extend(self._walk_expr(stmt.value))
            elif isinstance(stmt, ReturnStmt) and stmt.value:
                result.extend(self._walk_expr(stmt.value))
            elif isinstance(stmt, AssignStmt):
                result.extend(self._walk_expr(stmt.value))
            elif isinstance(stmt, IfStmt):
                result.extend(self._walk_expr(stmt.condition))
                result.extend(self._walk_stmts(stmt.then_body))
                for _, elif_body in stmt.elifs:
                    result.extend(self._walk_stmts(elif_body))
                if stmt.else_body:
                    result.extend(self._walk_stmts(stmt.else_body))
            elif isinstance(stmt, (WhileStmt, ForStmt)):
                if isinstance(stmt, WhileStmt):
                    result.extend(self._walk_expr(stmt.condition))
                elif isinstance(stmt, ForStmt):
                    result.extend(self._walk_expr(stmt.iterable))
                result.extend(self._walk_stmts(stmt.body))
            elif isinstance(stmt, TryStmt):
                result.extend(self._walk_stmts(stmt.body))
                for h in stmt.handlers:
                    result.extend(self._walk_stmts(h.body))
                if stmt.else_body:
                    result.extend(self._walk_stmts(stmt.else_body))
                if stmt.finally_body:
                    result.extend(self._walk_stmts(stmt.finally_body))
            elif isinstance(stmt, WithStmt):
                result.extend(self._walk_stmts(stmt.body))
        return result

    def _walk_expr(self, expr):
        """Return a list containing expr and all sub-expressions."""
        if expr is None:
            return []
        result = [expr]
        if isinstance(expr, BinaryOp):
            result.extend(self._walk_expr(expr.left))
            result.extend(self._walk_expr(expr.right))
        elif isinstance(expr, CompareChain):
            for o in expr.operands:
                result.extend(self._walk_expr(o))
        elif isinstance(expr, UnaryOp):
            result.extend(self._walk_expr(expr.operand))
        elif isinstance(expr, CallExpr):
            result.extend(self._walk_expr(expr.func))
            for arg in expr.args:
                result.extend(self._walk_expr(arg))
        elif isinstance(expr, MemberExpr):
            result.extend(self._walk_expr(expr.obj))
        elif isinstance(expr, SubscriptExpr):
            result.extend(self._walk_expr(expr.obj))
            result.extend(self._walk_expr(expr.index))
        elif isinstance(expr, SliceExpr):
            result.extend(self._walk_expr(expr.obj))
            if expr.start:
                result.extend(self._walk_expr(expr.start))
            if expr.stop:
                result.extend(self._walk_expr(expr.stop))
        elif isinstance(expr, TernaryExpr):
            result.extend(self._walk_expr(expr.condition))
            result.extend(self._walk_expr(expr.then_val))
            result.extend(self._walk_expr(expr.else_val))
        elif isinstance(expr, (ListExpr, SetExpr, TupleExpr)):
            for e in expr.elements:
                result.extend(self._walk_expr(e))
        elif isinstance(expr, DictExpr):
            for k, v in expr.pairs:
                result.extend(self._walk_expr(k))
                result.extend(self._walk_expr(v))
        return result

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
            elif self.allow_assume_all_methods:
                # If we can't analyze the pattern, assume all methods might be
                # called. This is conservative but correct ONLY for this
                # compiler's own self-hosted `Interpreter.execute`-style
                # dispatch idiom (see `allow_assume_all_methods`'s own
                # docstring in __init__) — gated off for ordinary code, where
                # `getattr(self, attr)` on a bare parameter is far more often
                # plain attribute delegation than a dispatch table.
                if struct_name in self.struct_methods:
                    for method_name, full_name in self.struct_methods[struct_name].items():
                        # Skip __init__ and the method doing the dispatch itself
                        if method_name not in ('__init__', 'execute'):
                            pattern.add_callee(full_name)
            # else: pattern shape unrecognized and we're not in the
            # self-hosting context this fallback was built for — leave
            # `pattern` with no callees rather than over-broadly assuming
            # every method of the struct could be the dispatch target.

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

        # Reverse lookup: full C callee name -> the struct that actually
        # owns it (self.struct_methods is struct_name -> {method_name:
        # full_c_name}, populated at registration time — see its own
        # declaration). Used below instead of guessing the owning struct
        # by string-splitting the callee name on '_', which silently
        # produces an EMPTY struct name for any struct whose real name
        # itself starts with an underscore (a common Python "private name"
        # convention — e.g. `inspect._ParameterKind`, whose mangled C
        # callee name `_ParameterKind___copy__` splits on '_' to `''` as
        # the first token). An empty struct name here produces malformed
        # C in emit_typedef/emit_table_init (`( *self)` with no type
        # before the pointer), a real GCC "expected declaration
        # specifiers... before '*' token" error — found via Lib/weakref.py
        # (pulls in inspect.py's `Parameter.ParameterKind` transitively)
        # and root-caused in bugs/hard/CODEGEN_selfhost_getattr_dispatch_
        # heuristic_misfires_on_ordinary_code.md's "what a real fix needs"
        # option 3 ("defensively skip/warn rather than emit malformed C
        # when a callee's inferred self type resolves empty") — this is
        # that fix, plus resolving the struct name correctly instead of
        # just skipping known-derivable cases.
        # Same registry, reversed to recover the real (unmangled, exactly as
        # written in the source) Python method name too — needed because
        # `_extract_method_name` below derives its name by naively splitting
        # the callee string on the FIRST underscore, which silently returns
        # the wrong (too-long) suffix whenever the owning struct's own name
        # contains an underscore (e.g. `IMAP4_stream`: splitting
        # "IMAP4_stream_close" on the first '_' yields "stream_close", not
        # "close"). That's harmless for the field's own C name (any unique
        # valid identifier works there), but the `_C_RESERVED_FUNCS` lookup
        # below needs the TRUE bare method name to correctly recognize
        # e.g. `IMAP4_stream.close` as the reserved name `close`.
        _callee_to_struct: dict = {}
        _callee_to_method: dict = {}
        for _sname, _smethods in self.struct_methods.items():
            for _mname, _full in _smethods.items():
                _callee_to_struct[_full] = _sname
                _callee_to_method[_full] = _mname
        self.callee_home = _callee_to_struct
        self.callee_method = _callee_to_method

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

                    # Refuse to add a compiled GENERATOR method to a
                    # FUNC_POINTER dispatch table (see `generator_method_api`'s
                    # own docstring on __init__ for the full mechanism/why).
                    # Emitting it would produce a struct-initializer field
                    # referencing the bare, unmangled `<Struct>_<method>` C
                    # symbol as a function-pointer VALUE — but a generator
                    # method's only real emitted callable surface is its
                    # `<base>_start/_resume/_value/_destroy` coroutine API,
                    # so that symbol is never defined, producing a hard GCC
                    # "'<Struct>_<method>' undeclared here (not in a
                    # function)" failure at `-fgimple` compile time. Same
                    # detection/skip-shape as the `_self_type_unresolved`
                    # continue just below this loop: dropping just this one
                    # callee from the table is safe (this whole dispatch-
                    # table-inference machinery is itself a heuristic, and
                    # this table is never actually consulted at any real
                    # call site — see get_dispatch_tables' callers — so
                    # omitting an entry changes no compiled behavior).
                    _owner_struct = _callee_to_struct.get(callee, '')
                    if (_owner_struct, method_name) in self.generator_method_api:
                        continue

                    # SIBLING skip, same "bare callee string doesn't match the
                    # real emitted symbol" failure mode as the generator skip
                    # just above, but a DIFFERENT mechanism: `callee` here was
                    # built by plain string concatenation
                    # (`f"{struct_name}_{method_name}"`, see
                    # `_analyze_call_graph`'s `self.struct_methods`
                    # population), which never applies `_safe_name`'s
                    # libc/system-symbol-collision mangling. A method whose
                    # bare Python name is one of `_C_RESERVED_FUNCS` (e.g.
                    # `close`/`open`/`read`/`rename` — real libc symbols this
                    # codegen must not let a Mojo function definition shadow)
                    # IS actually compiled to a real, callable, plain C
                    # function — just under `mojo_<name>` (e.g.
                    # `IMAP4_mojo_close`, from `_struct_method_csym`'s own
                    # `_safe_name(method_name)` call), never under the bare
                    # `<Struct>_<method>` name this table would reference.
                    # Emitting `.close = (...)IMAP4_close` therefore hits the
                    # identical "undeclared here (not in a function)" GCC
                    # error as the generator case, for an unrelated reason —
                    # found via Lib/imaplib.py's `IMAP4.close/open/read/
                    # rename` (bugs/CODEGEN_generator_function_Lib_imaplib.md).
                    # Deliberately a SEPARATE check rather than folding into
                    # one "is this symbol really registered" lookup: at this
                    # point in the pipeline (Phase 1.5, before struct method
                    # bodies are ever codegen'd — see this class's own
                    # `analyze()` call site in gen_module) `func_return_types`/
                    # `func_param_types` are NOT yet populated for ordinary
                    # local struct methods, so a registry-membership check
                    # would false-positive-drop nearly every legitimate
                    # ordinary method in the table. `_C_RESERVED_FUNCS`
                    # membership is a pure syntactic property of the method's
                    # own name, decidable with no ordering dependency at all
                    # — same reasoning that keeps this a sibling check next to
                    # the generator one instead of a shared "look it up"
                    # helper.
                    _real_method_name = _callee_to_method.get(callee, method_name)
                    if _real_method_name in _C_RESERVED_FUNCS:
                        continue

                    # Infer C signature from function return type and parameter types
                    return_type = self.func_return_types.get(callee, 'int64_t')

                    # Get parameter types for this function
                    params = self.func_param_types.get(callee, [])

                    # Convert parameter types to C
                    # Skip 'self' for methods (first param)
                    c_params = []
                    _self_type_unresolved = False
                    for pname, ptype in params:
                        if pname == 'self':
                            # For struct methods, infer the struct type.
                            # Prefer the exact reverse lookup (correct
                            # regardless of underscore-prefixed struct
                            # names); fall back to the old name-splitting
                            # heuristic only if the callee isn't in the
                            # registry at all (shouldn't normally happen —
                            # every dispatch-pattern callee comes FROM
                            # struct_methods in the first place — but kept
                            # as a harmless fallback for safety).
                            struct_name = _callee_to_struct.get(callee, '')
                            if not struct_name:
                                struct_name = callee.split('_')[0] if '_' in callee else 'void'
                            if not struct_name:
                                _self_type_unresolved = True
                                break
                            c_params.append(f"{struct_name} *self")
                        elif ptype:
                            # Map Python types to C types, use fallback for unresolved
                            c_type = self._map_to_c_type(ptype)
                            c_params.append(f"{c_type} {pname}")
                        else:
                            # No type annotation, default to int
                            c_params.append(f"int {pname}")

                    # Defensive net: never emit a dispatch-table entry whose
                    # `self` parameter type couldn't be resolved at all —
                    # that's exactly the malformed-C shape this fix exists
                    # to prevent (see the comment on _callee_to_struct
                    # above). Dropping just this one callee from the table
                    # is safe: this whole dispatch-table-inference
                    # machinery is itself a heuristic (see the linked hard-
                    # bug doc) that can over-broadly include callees having
                    # nothing to do with a real dispatch table in the first
                    # place; omitting an unresolvable one never changes
                    # behavior for the genuine self-hosting dispatch
                    # pattern this machinery was built for (every real
                    # callee there resolves its `self` type without issue).
                    if _self_type_unresolved:
                        continue

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
        """Recursively return a list of all AST nodes in statements and expressions."""
        result = []
        for stmt in stmts:
            result.append(stmt)

            # Recurse into expressions in statements
            if isinstance(stmt, AssignStmt):
                result.extend(self._walk_expr_nodes(stmt.value))
            elif isinstance(stmt, ReturnStmt) and stmt.value:
                result.extend(self._walk_expr_nodes(stmt.value))
            elif isinstance(stmt, ExprStmt):
                result.extend(self._walk_expr_nodes(stmt.value))
            elif isinstance(stmt, IfStmt):
                result.extend(self._walk_expr_nodes(stmt.condition))
                result.extend(self._walk_all_nodes(stmt.then_body))
                for _, elif_body in stmt.elifs:
                    result.extend(self._walk_all_nodes(elif_body))
                if stmt.else_body:
                    result.extend(self._walk_all_nodes(stmt.else_body))
            elif isinstance(stmt, (WhileStmt, ForStmt)):
                result.extend(self._walk_all_nodes(stmt.body))
            elif isinstance(stmt, TryStmt):
                result.extend(self._walk_all_nodes(stmt.body))
        return result

    def _walk_expr_nodes(self, expr):
        """Recursively return a list of all nodes in an expression tree."""
        if expr is None:
            return []

        result = [expr]

        if isinstance(expr, CallExpr):
            result.extend(self._walk_expr_nodes(expr.func))
            for arg in expr.args:
                result.extend(self._walk_expr_nodes(arg))
        elif isinstance(expr, BinaryOp):
            result.extend(self._walk_expr_nodes(expr.left))
            result.extend(self._walk_expr_nodes(expr.right))
        elif isinstance(expr, CompareChain):
            for o in expr.operands:
                result.extend(self._walk_expr_nodes(o))
        elif isinstance(expr, TernaryExpr):
            result.extend(self._walk_expr_nodes(expr.condition))
            result.extend(self._walk_expr_nodes(expr.then_val))
            result.extend(self._walk_expr_nodes(expr.else_val))
        elif isinstance(expr, SubscriptExpr):
            result.extend(self._walk_expr_nodes(expr.obj))
            result.extend(self._walk_expr_nodes(expr.index))
        elif isinstance(expr, MemberExpr):
            result.extend(self._walk_expr_nodes(expr.obj))
        return result

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
# ClosureInfo — nested-function lifting record (extracted from gimple_codegen.py)
# ---------------------------------------------------------------------------

class ClosureInfo:
    """Describes a nested function lifted to module scope."""
    def __init__(self, lifted_name: str, env_struct: str,
                 captures: list, inner_def: FunctionDef):
        self.lifted_name        = lifted_name
        self.env_struct         = env_struct
        self.captures           = captures   # [(varname, ctype)]
        self.inner_def          = inner_def  # FunctionDef node
        self.is_re_sub_callback = False      # True if used as re.sub(pat, THIS, src)
        self.inferred_params: dict = {}      # pname → ctype (filled by _gen_lifted_closure)
        self.inferred_ret: str = ''          # filled by _gen_lifted_closure
        # Names in `captures` that this closure's own body REASSIGNS (a
        # plain `{mut}`-capture-spec closure's `counter += 1` idiom — see
        # GimpleGen._mutated_free_names, reused here exactly like the
        # async mutable-capture mechanism reuses it) -- these get a
        # by-REFERENCE capture (env struct field widened to a pointer,
        # populated with `&local` instead of a value copy) instead of the
        # ordinary by-value capture every other entry in `captures` still
        # uses. Filled by gen_module's `_scan_for_closures` pass.
        self.mut_names: frozenset = frozenset()
