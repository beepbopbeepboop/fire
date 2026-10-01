# Moved from gimple_solvers.py - shared middle-end (mojo/middle).
# Import rewrite performed via AST; original docstring/comments preserved below.
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
from fire_compiler import AssignStmt, BinaryOp, CallExpr, CompareChain, DictExpr, ExprStmt, ForStmt, FunctionDef, IdentExpr, IfStmt, ListExpr, MemberExpr, ReturnStmt, SetExpr, SliceExpr, StringLiteral, StructDef, SubscriptExpr, TernaryExpr, TryStmt, TupleExpr, UnaryOp, VarDecl, WhileStmt, WithStmt
from mojo.middle.types import _C_RESERVED_FUNCS

def _find_idents(node) -> set:
    """Recursively find all identifiers in an AST node."""
    if isinstance(node, IdentExpr):
        return {node.name}
    if isinstance(node, BinaryOp):
        return _find_idents(node.left) | _find_idents(node.right)
    if isinstance(node, CompareChain):
        r = set()
        for o in node.operands:
            r |= _find_idents(o)
        return r
    if isinstance(node, UnaryOp):
        return _find_idents(node.operand)
    if isinstance(node, CallExpr):
        r = set()
        for a in node.args:
            r |= _find_idents(a)
        return r
    if isinstance(node, MemberExpr):
        return _find_idents(node.obj)
    if isinstance(node, SubscriptExpr):
        return _find_idents(node.obj) | _find_idents(node.index)
    if isinstance(node, TernaryExpr):
        return _find_idents(node.condition) | _find_idents(node.then_val) | _find_idents(node.else_val)
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
        if isinstance(node, IdentExpr):
            return {node.name}
        if isinstance(node, BinaryOp):
            return self._idents(node.left) | self._idents(node.right)
        if isinstance(node, CompareChain):
            r = set()
            for o in node.operands:
                r |= self._idents(o)
            return r
        if isinstance(node, UnaryOp):
            return self._idents(node.operand)
        if isinstance(node, CallExpr):
            r = set()
            for a in node.args:
                r |= self._idents(a)
            return r
        if isinstance(node, MemberExpr):
            return self._idents(node.obj)
        if isinstance(node, SubscriptExpr):
            return self._idents(node.obj) | self._idents(node.index)
        if isinstance(node, TernaryExpr):
            return self._idents(node.condition) | self._idents(node.then_val) | self._idents(node.else_val)
        return set()

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
    HEAP = 'heap'

    def __init__(self, struct_field_types: dict):
        self._struct_types = set(struct_field_types.keys())
        self._ea = EscapeAnalyzer(self._struct_types)

    def solve(self, params: list, body: list) -> dict:
        """Return {var_name: STACK|HEAP} for struct-typed locals in *body*."""
        has_try = self._has_try(body)
        escaped = _find_escaping(params, body, self._struct_types)
        locals_ = self._struct_locals(body)
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
        # Explicit loops, NOT `any((self._has_try(eb) for _, eb in
        # node.elifs))` and careful with `node.else_body` truthiness: a bare
        # generator expression whose body is empty on the compiled path, and
        # a tuple-unpacking genexpr, are both established self-hosted traps
        # (see tools/audit_determinism.py). The genexpr form returned the
        # garbage non-list 1, so the enclosing `mojo_list_len(0x1)` SIGSEGV'd
        # while compiling myinterpreter.py/module_loader.py.
        for node in stmts:
            if isinstance(node, TryStmt):
                return True
            if isinstance(node, IfStmt):
                if self._has_try(node.then_body):
                    return True
                for _eb_i in range(len(node.elifs)):
                    if self._has_try(node.elifs[_eb_i][1]):
                        return True
                if node.else_body:
                    if self._has_try(node.else_body):
                        return True
            if isinstance(node, (WhileStmt, ForStmt)):
                if self._has_try(node.body):
                    return True
        return False

class DispatchTable:
    """Plan for a virtual method table or dispatch array.

    Stores the planned structure of a dispatch table (vtable), with methods
    to emit C code for the typedef, initialization, and dispatch calls.

    Examples:
        - Interpreter's execute dispatch: maps execute_* methods
        - Generic container dispatch: maps operation names to implementations
    """

    def __init__(self, name: str, pattern_id: str, dispatch_type: str):
        self.name = name
        self.pattern_id = pattern_id
        self.dispatch_type = dispatch_type
        self.methods: list = []
        self.struct_fields: dict = {}
        self.dispatch_index_map: dict = {}

    def add_method(self, method_name: str, c_signature: str, full_c_name: str):
        """Add a method to this dispatch table.

        Args:
            method_name: Short name (e.g., 'execute_Module')
            c_signature: Function pointer signature (e.g., 'int (*name)(void *self, void *node)')
            full_c_name: Full C function name (e.g., 'Interpreter_execute_Module')
        """
        self.methods.append((method_name, c_signature, full_c_name))
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
            lines = [f'typedef struct {{']
            for method_name, c_signature in self.struct_fields.items():
                lines.append(f'  {c_signature};')
            lines.append(f'}} {self.name}_t;')
            return '\n'.join(lines)
        elif self.dispatch_type == 'ARRAY_INDEX':
            if self.methods:
                _, sig, _ = self.methods[0]
                lines = [f'typedef int (*{self.name}_fn)(void *, void *);']
                return '\n'.join(lines)
        return f'/* TODO: {self.dispatch_type} dispatch typedef */'

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
            lines = [f'static const {self.name}_t {self.name} = {{']
            for method_name, _, full_c_name in self.methods:
                c_sig = self.struct_fields.get(method_name, '')
                if c_sig:
                    fp_type = c_sig.replace(f'(*{method_name})', '(*)')
                    lines.append(f'  .{method_name} = ({fp_type}){full_c_name},')
                else:
                    lines.append(f'  .{method_name} = {full_c_name},')
            lines.append(f'}};')
            return '\n'.join(lines)
        elif self.dispatch_type == 'ARRAY_INDEX':
            lines = [f'static const {self.name}_fn {self.name}[] = {{']
            for _, _, full_c_name in self.methods:
                lines.append(f'  {full_c_name},')
            lines.append(f'}};')
            return '\n'.join(lines)
        return f'/* TODO: {self.dispatch_type} dispatch init */'

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
                return f'{obj}.{method_name}({args})'
            elif isinstance(method_idx, str):
                return f'{obj}.{method_idx}({args})'
        elif self.dispatch_type == 'ARRAY_INDEX':
            if isinstance(method_idx, int):
                return f'{obj}[{method_idx}]({args})'
            else:
                for i, (method_name, _, _) in enumerate(self.methods):
                    if method_name == method_idx:
                        return f'{obj}[{i}]({args})'
        return f'/* TODO: dispatch call */'

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
            return 'void (*)(void *, void *)'
        return 'void (*)(void)'

class DispatchPattern:
    """Describes a dynamic dispatch pattern found in the code.

    Examples:
        - getattr(self, f'execute_{type}', None) — method lookup on interpreter
        - _STMT_DISPATCH[node_type] — dict-based dispatch
        - node.method() — direct method reference
    """

    def __init__(self, pattern_id: str, pattern_type: str, location: tuple):
        self.pattern_id = pattern_id
        self.pattern_type = pattern_type
        self.location = location
        self.possible_callees: set = set()
        self.call_sites: list = []

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

    def __init__(self, struct_field_types: dict, func_return_types: dict, allow_assume_all_methods: bool=False, generator_method_api: dict | None=None):
        self.struct_field_types = struct_field_types
        self.func_return_types = func_return_types
        self.generator_method_api = generator_method_api or {}
        self.allow_assume_all_methods = allow_assume_all_methods
        self.callee_home: dict = {}
        self.callee_method: dict = {}
        self.call_graph: dict[str, set] = {}
        self.dispatch_patterns: dict[str, DispatchPattern] = {}
        self.callers_of: dict[str, set] = {}
        self.struct_methods: dict[str, dict] = {}
        self._pattern_counter = 0

    def analyze(self, all_stmts: list):
        """Run complete dispatch analysis on entire closure.

        Includes three core dispatch analyses plus new complementary analyses:
        - Call graph and dispatch pattern detection (existing)
        - Function compilability analysis (def→fn promotions)
        - Type promotion across closure (cross-closure type inference)
        """
        self.func_param_types: dict = {}
        self._collect_function_param_types(all_stmts)
        self._build_call_graph(all_stmts)
        self._find_dispatch_patterns(all_stmts)
        self._plan_dispatch_tables()
        self.compilability = FunctionCompilability(self.func_return_types, self.struct_field_types)
        self.compilability.analyze(all_stmts)
        self.type_promoter = TypePromotionSolver(self.call_graph, self.func_return_types)
        self.type_promoter.analyze(all_stmts, {})

    def _collect_function_param_types(self, stmts: list):
        """Collect parameter type information for all functions."""
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                self.func_param_types[stmt.name] = stmt.params
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    method_full_name = f'{stmt.name}_{method.name}'
                    self.func_param_types[method_full_name] = method.params

    def _build_call_graph(self, stmts: list):
        """Traverse all functions and structs, record direct calls.

        Direct calls = those where the callee is statically known.
        Dynamic calls (getattr, dict lookup) are skipped here and handled separately.
        """
        all_functions = set()
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                all_functions.add(stmt.name)
            elif isinstance(stmt, StructDef):
                if stmt.name not in self.struct_methods:
                    self.struct_methods[stmt.name] = {}
                for method in stmt.methods:
                    method_name = f'{stmt.name}_{method.name}'
                    all_functions.add(method_name)
                    self.struct_methods[stmt.name][method.name] = method_name
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                self._scan_for_calls(stmt.name, stmt.body, all_functions)
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    method_full_name = f'{stmt.name}_{method.name}'
                    self._scan_for_calls(method_full_name, method.body, all_functions)

    def _scan_for_calls(self, func_name: str, body: list, all_functions: set):
        """Scan function body for direct calls, build call graph."""
        if func_name not in self.call_graph:
            self.call_graph[func_name] = set()
        for node in self._walk_stmts(body):
            if isinstance(node, CallExpr):
                callee = self._extract_callee_name(node.func)
                if callee and callee in all_functions:
                    self.call_graph[func_name].add(callee)
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
                    method_full_name = f'{stmt.name}_{method.name}'
                    self._find_patterns_in_body(method_full_name, method.body, stmt.name)

    def _find_patterns_in_body(self, func_name: str, body: list, struct_name: str | None):
        """Find dispatch patterns in a function/method body."""
        for node in self._walk_stmts(body):
            if isinstance(node, CallExpr):
                if isinstance(node.func, IdentExpr) and node.func.name == 'getattr' and (len(node.args) >= 2):
                    self._analyze_getattr_pattern(func_name, node, struct_name)
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
        obj_name = None
        if isinstance(obj_expr, IdentExpr):
            obj_name = obj_expr.name
        if obj_name == 'self' and struct_name:
            pattern_key = f"{struct_name}_{func_name.split('_')[-1]}:getattr_self:{id(call_node)}"
            pattern = DispatchPattern(pattern_key, 'getattr', (func_name, 0))
            pattern.add_call_site(call_node)
            if isinstance(name_expr, BinaryOp) and name_expr.op == '+':
                self._infer_getattr_targets(pattern, name_expr, struct_name)
            elif self.allow_assume_all_methods:
                if struct_name in self.struct_methods:
                    for method_name, full_name in self.struct_methods[struct_name].items():
                        if method_name not in ('__init__', 'execute'):
                            pattern.add_callee(full_name)
            self.dispatch_patterns[pattern_key] = pattern

    def _infer_getattr_targets(self, pattern: DispatchPattern, name_expr, struct_name: str):
        """Try to infer which methods could be retrieved by this getattr.

        For patterns like f'execute_{type_name}', find all methods starting with 'execute_'.
        """
        prefix = None
        if isinstance(name_expr, BinaryOp) and name_expr.op == '+':
            if isinstance(name_expr.left, StringLiteral):
                prefix = name_expr.left.value.rstrip('_')
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
        dispatch_tables = {'_STMT_DISPATCH', '_EXPR_DISPATCH', '_BIN_OPS', '_CMP_OPS', 'stmt_dispatch', 'expr_dispatch', 'bin_ops', 'cmp_ops'}
        if dict_name not in dispatch_tables:
            return
        pattern_key = f'{func_name}:subscript:{dict_name}:{id(subscript_expr)}'
        pattern = DispatchPattern(pattern_key, 'subscript', (func_name, 0))
        pattern.add_call_site(subscript_expr)
        self.dispatch_patterns[pattern_key] = pattern

    def _plan_dispatch_tables(self):
        """For each dispatch pattern, plan the vtable structure.

        This phase:
        1. Groups patterns by their callees to identify unique dispatch tables
        2. Creates DispatchTable for each pattern with full vtable planning
        3. Infers parameter types from function return types
        """
        tables_by_callees: dict = {}
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
            callee_key = frozenset(pattern.possible_callees)
            if callee_key not in tables_by_callees:
                table_name = self._generate_table_name(pattern_id, pattern)
                table = DispatchTable(name=table_name, pattern_id=pattern_id, dispatch_type='FUNC_POINTER')
                for callee in sorted(pattern.possible_callees):
                    method_name = self._extract_method_name(callee)
                    _owner_struct = _callee_to_struct.get(callee, '')
                    if (_owner_struct, method_name) in self.generator_method_api:
                        continue
                    _real_method_name = _callee_to_method.get(callee, method_name)
                    if _real_method_name in _C_RESERVED_FUNCS:
                        continue
                    return_type = self.func_return_types.get(callee, 'int64_t')
                    params = self.func_param_types.get(callee, [])
                    c_params = []
                    _self_type_unresolved = False
                    for pname, ptype in params:
                        if pname == 'self':
                            struct_name = _callee_to_struct.get(callee, '')
                            if not struct_name:
                                struct_name = callee.split('_')[0] if '_' in callee else 'void'
                            if not struct_name:
                                _self_type_unresolved = True
                                break
                            c_params.append(f'{struct_name} *self')
                        elif ptype:
                            c_type = self._map_to_c_type(ptype)
                            c_params.append(f'{c_type} {pname}')
                        else:
                            c_params.append(f'int {pname}')
                    if _self_type_unresolved:
                        continue
                    param_str = ', '.join(c_params) if c_params else 'void'
                    c_signature = f'{return_type} (*{method_name})({param_str})'
                    table.add_method(method_name, c_signature, callee)
                tables_by_callees[callee_key] = table
        self.dispatch_tables = tables_by_callees

    def _map_to_c_type(self, ptype: str) -> str:
        """Map Python type annotation to C type.

        Handles both built-in types and AST node types (e.g., N.BinaryOp → int).
        """
        if not ptype:
            return 'int'
        if ptype in self.struct_field_types:
            return f'{ptype} *'
        if '.' in ptype:
            _ast_types = ['Module', 'BinaryOp', 'UnaryOp', 'AssignStmt', 'IfStmt', 'WhileStmt', 'ForStmt', 'ReturnStmt', 'FunctionDef', 'StructDef', 'BreakStmt', 'ContinueStmt', 'PassStmt', 'ImportStmt', 'FromImportStmt', 'ExprStmt', 'TryStmt', 'WithStmt', 'BoolLiteral', 'IntLiteral', 'FloatLiteral', 'StringLiteral', 'NoneLiteral', 'ListLiteral', 'DictLiteral', 'SetLiteral', 'TupleLiteral', 'IdentExpr', 'MemberExpr', 'SubscriptExpr', 'SliceExpr', 'CallExpr', 'TernaryExpr']
            # Explicit loop, NOT `any((ast_type in ptype for ast_type in
            # [...]))` — the genexpr erases to the garbage non-list 1 on the
            # self-hosted path (mojo_list_len(0x1) SIGSEGV).
            _has_ast_type = False
            for _at0 in _ast_types:
                if _at0 in ptype:
                    _has_ast_type = True
                    break
            if _has_ast_type:
                return 'int'
            return 'void *'
        if '|' in ptype:
            parts = [p.strip() for p in ptype.split('|')]
            non_none = [p for p in parts if p not in ('None', 'NoneType')]
            if non_none:
                return self._map_to_c_type(non_none[0])
            return 'void *'
        type_map = {'int': 'int', 'Int': 'int64_t', 'float': 'double', 'Float': 'double', 'Float64': 'double', 'bool': 'int', 'Bool': '_Bool', 'str': 'char *', 'String': 'char *', 'object': 'void *', 'Any': 'void *', 'list': 'MojoList *', 'List': 'MojoList *', 'MojoList': 'MojoList *', 'dict': 'MojoDict *', 'Dict': 'MojoDict *', 'MojoDict': 'MojoDict *', 'set': 'MojoSet *', 'Set': 'MojoSet *', 'MojoSet': 'MojoSet *'}
        return type_map.get(ptype, 'void *')

    def _generate_table_name(self, pattern_id: str, pattern: DispatchPattern) -> str:
        """Generate a C-safe name for a dispatch table."""
        parts = pattern_id.split(':')
        base = parts[0].lower()
        if pattern.pattern_type == 'getattr':
            return f'{base}_dispatch'
        elif pattern.pattern_type == 'subscript':
            return f'{base}_dispatch'
        else:
            return f'dispatch_{self._pattern_counter}'

    def _extract_method_name(self, full_name: str) -> str:
        """Extract method name from mangled C name.

        Examples:
            "Interpreter_execute_Module" → "execute_Module"
            "Scope_set" → "set"
        """
        parts = full_name.split('_', 1)
        if len(parts) == 2:
            return parts[1]
        return full_name

    def get_patterns_for_function(self, func_name: str) -> list[DispatchPattern]:
        """Get all dispatch patterns used in a specific function."""
        _out = []
        for _p0 in self.dispatch_patterns.values():
            _has_cs = False
            for _cs0 in _p0.call_sites:
                _has_cs = True
                break
            if _has_cs:
                _out.append(_p0)
        return _out

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
            return {'compilable_count': self.compilability.get_compilable_count(), 'uncompilable_count': len(self.compilability.uncompilable_funcs), 'compilable_functions': self.compilability.compilable_funcs.copy(), 'uncompilable_with_reasons': self.compilability.uncompilable_funcs.copy()}
        return {'compilable_count': 0, 'uncompilable_count': 0, 'compilable_functions': set(), 'uncompilable_with_reasons': {}}

    def get_promoted_types(self) -> dict:
        """Get all types promoted across the closure."""
        if hasattr(self, 'type_promoter'):
            return self.type_promoter.get_all_promoted_types()
        return {}

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
        self.compilable_funcs: set = set()
        self.uncompilable_funcs: dict = {}

    def analyze(self, stmts: list):
        """Determine which functions are C-compilable."""
        candidates = self._find_candidates(stmts)
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
                if stmt.return_type is not None:
                    _allp = True
                    for _pp0 in stmt.params:
                        if _pp0[1] is None:
                            _allp = False
                            break
                    has_all_params = _allp
                    if has_all_params:
                        candidates.append((stmt.name, stmt, False))
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    if method.return_type is not None:
                        non_self_params = []
                        for _mp0 in method.params:
                            if _mp0[0] != 'self':
                                non_self_params.append((_mp0[0], _mp0[1]))
                        _allp2 = True
                        for _pp1 in non_self_params:
                            if _pp1[1] is None:
                                _allp2 = False
                                break
                        has_all_params = _allp2
                        if has_all_params:
                            full_name = f'{stmt.name}_{method.name}'
                            candidates.append((full_name, method, True))
        return candidates

    def _check_compilability(self, func_name: str, func_def, is_method: bool) -> str | None:
        """Check if a function body is C-compilable.

        Returns None if compilable, otherwise returns reason string.
        """
        for node in self._walk_all_nodes(func_def.body):
            if isinstance(node, CallExpr):
                if isinstance(node.func, IdentExpr):
                    if node.func.name in ('getattr', 'setattr', 'hasattr'):
                        return f'uses {node.func.name}() - dynamic dispatch'
            if isinstance(node, SubscriptExpr):
                if isinstance(node.obj, IdentExpr):
                    if node.obj.name in ('_STMT_DISPATCH', '_EXPR_DISPATCH'):
                        return 'uses dynamic dispatch table'
        return None

    def _walk_all_nodes(self, stmts: list):
        """Recursively return a list of all AST nodes in statements and expressions."""
        result = []
        for stmt in stmts:
            result.append(stmt)
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
        self.call_graph = call_graph
        self.func_return_types = func_return_types
        self.promoted_types: dict = {}
        self.type_conflicts: dict = {}

    def analyze(self, stmts: list, all_funcs: dict):
        """Propagate types across closure.

        Args:
            stmts: All statements in module
            all_funcs: Dict of func_name → FunctionDef for all functions
        """
        signatures = self._collect_signatures(stmts)
        self._propagate_return_types(signatures)
        self._promote_types()

    def _collect_signatures(self, stmts: list) -> dict:
        """Collect function signatures from module."""
        signatures = {}
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                signatures[stmt.name] = {'params': stmt.params, 'return_type': stmt.return_type}
            elif isinstance(stmt, StructDef):
                for method in stmt.methods:
                    full_name = f'{stmt.name}_{method.name}'
                    signatures[full_name] = {'params': method.params, 'return_type': method.return_type}
        return signatures

    def _propagate_return_types(self, signatures: dict):
        """Propagate return types from callees to callers."""
        for func_name, ret_type in self.func_return_types.items():
            if ret_type != 'void':
                key = f'__return__{func_name}'
                self.promoted_types[key] = ret_type

    def _promote_types(self):
        """Promote types to compatible common forms.

        Examples:
            int8, int16, int32 → int64_t (for closure consistency)
            float, float32 → double (wider type)
        """
        int_types = set()
        float_types = set()
        for var_type in self.promoted_types.values():
            if 'int' in var_type.lower():
                int_types.add(var_type)
            elif 'float' in var_type.lower() or 'double' in var_type.lower():
                float_types.add(var_type)
        if int_types:
            _has64 = False
            for _t0 in int_types:
                if '64' in _t0:
                    _has64 = True
                    break
            promoted_int = 'int64_t' if _has64 else 'int'
            for var_name in list(self.promoted_types.keys()):
                if 'int' in self.promoted_types[var_name].lower():
                    self.promoted_types[var_name] = promoted_int
        if float_types:
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

class ClosureInfo:
    """Describes a nested function lifted to module scope."""

    def __init__(self, lifted_name: str, env_struct: str, captures: list, inner_def: FunctionDef):
        self.lifted_name = lifted_name
        self.env_struct = env_struct
        self.captures = captures
        self.inner_def = inner_def
        self.is_re_sub_callback = False
        self.inferred_params: dict = {}
        self.inferred_ret: str = ''
        self.mut_names: frozenset = frozenset()