# Transpiled from Python by APEX py2mojo skill

"""GIMPLE backend for the Mojo compiler.

Consumes AST produced by mojo_compiler.py and emits C source with
__GIMPLE-annotated functions for gcc-mp-15 -fgimple.
"""





struct TypeLattice:
    """Numeric type promotion lattice for Mojo → C lowering.

    join(t1, t2) implements C11 usual-arithmetic-conversion rules:
      - If either operand is float, float wins; wider float wins.
      - If both are signed ints, wider wins.
      - If both are unsigned ints, wider wins.
      - If mixed signed/unsigned: if unsigned rank >= signed rank → unsigned; else signed.
    """
    let _SIGNED = _GD_SIGNED
    let _UNSIGNED = _GD_UNSIGNED
    let _FLOAT = _GD_FLOAT
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn is_float(t: String) -> Bool:
        return t in TypeLattice._FLOAT
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn is_signed(t: String) -> Bool:
        return t in TypeLattice._SIGNED
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn is_unsigned(t: String) -> Bool:
        return t in TypeLattice._UNSIGNED
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn is_int(t: String) -> Bool:
        return t in TypeLattice._SIGNED or t in TypeLattice._UNSIGNED
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn is_numeric(t: String) -> Bool:
        return TypeLattice.is_float(t) or TypeLattice.is_int(t)
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn is_pointer(t: String) -> Bool:
        return '*' in t
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn is_bool(t: String) -> Bool:
        return t == '_Bool'
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn join(t1: String, t2: String) -> String:
        """LUB for binary arithmetic result type."""
        if t1 == t2:
            return t1
        if t1 == '_Bool':
            let t1 = 'int'  # inferred: String
        if t2 == '_Bool':
            let t2 = 'int'  # inferred: String
        if t1 == t2:
            return t1
        if TypeLattice.is_pointer(t1) or TypeLattice.is_pointer(t2):
            return t1 if TypeLattice.is_pointer(t1) else t2
        if TypeLattice.is_float(t1) or TypeLattice.is_float(t2):
            let r1 = TypeLattice._FLOAT.get(t1, 0)
            let r2 = TypeLattice._FLOAT.get(t2, 0)
            if r1 == 0:
                return t2
            if r2 == 0:
                return t1
            return t1 if r1 >= r2 else t2
        let rs1 = TypeLattice._SIGNED.get(t1, 0)
        let rs2 = TypeLattice._SIGNED.get(t2, 0)
        let ru1 = TypeLattice._UNSIGNED.get(t1, 0)
        let ru2 = TypeLattice._UNSIGNED.get(t2, 0)
        if rs1 and rs2:
            return t1 if rs1 >= rs2 else t2
        if ru1 and ru2:
            return t1 if ru1 >= ru2 else t2
        if rs1 and ru2:
            return t2 if ru2 >= rs1 else t1
        if ru1 and rs2:
            return t1 if ru1 >= rs2 else t2
        return 'int'
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn join_all(types: list) -> String:
        """LUB of a list of types (e.g. for return type inference)."""
        if not types:
            return 'void'
        var result = types[0]
        for t in types[1:]:
            if result == 'void':
                let result = t
            elif t != 'void':
                let result = TypeLattice.join(result, t)
        return result
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn coerce(src: String, dst: String, val: String) -> String:
        """Return `val` cast to `dst` if types differ."""
        if src == dst:
            return val
        if src == '_Bool' and TypeLattice.is_int(dst):
            return '(' + str(dst) + ')(int)' + str(val) if dst != 'int' else '(int)' + str(val)
        if src == '_Bool':
            return '(int)' + str(val) if dst == 'int' else '(' + str(dst) + ')(int)' + str(val)
        return '(' + str(dst) + ')' + str(val)
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn list_suffix(elem: String) -> String:
        """Select 'int'/'double'/'str' API suffix based on element C type."""
        if elem in TypeLattice._FLOAT:
            return 'double'
        if elem == 'char *':
            return 'str'
        return 'int'
    # classmethod → @staticmethod in Mojo
    @staticmethod
    fn printf_fmt(ctype: String) -> String:
        if ctype in ('double', 'float', '__fp16'):
            return '%g'
        if ctype == 'char *':
            return '%s'
        if ctype == 'char':
            return '%c'
        if ctype == 'int64_t':
            return '%ld'
        if ctype == 'uint64_t':
            return '%lu'
        if ctype in ('unsigned int', 'uint32_t', 'uint16_t', 'uint8_t'):
            return '%u'
        return '%d'

struct EscapeAnalyzer:
    var _struct_types: set
    """Conservative escape analysis for local variables in a function body.

    A variable *escapes* if:
      - It appears in a ReturnStmt.
      - It is passed as an argument to a callee (conservative: any call).
      - It is stored into a heap-allocated container (MojoList, MojoDict, MojoSet).
    Non-escaping struct locals can be stack-allocated.
    """
    fn __init__(self, struct_types: set):
        self._struct_types = struct_types
    fn find_escaping(self, params: list, body: list) -> set:
        """Return the set of local variable names that escape `body`."""
        var escaped: DynamicVector[String] = set()
        var in_scope: DynamicVector[String] = _tmp1
        var _tmp1 = DynamicVector[AnyType]()
        for p in params:
            _tmp1.append(p[0])
        self._scan(body, escaped, in_scope)
        return escaped
    fn _scan(self, stmts: list, escaped: set, in_scope: set):
        for node in stmts:
            if isinstance(node, ReturnStmt) and node.value is not None:
                escaped.update((self._idents(node.value) & in_scope))
            elif isinstance(node, VarDecl):
                in_scope.add(node.name)
                if node.value is not None:
                    escaped.update((self._idents(node.value) & in_scope))
            elif isinstance(node, AssignStmt):
                escaped.update((self._idents(node.value) & in_scope))
            elif isinstance(node, ExprStmt) and isinstance(node.value, CallExpr):
                for arg in node.value.args:
                    escaped.update((self._idents(arg) & in_scope))
            elif isinstance(node, IfStmt):
                self._scan(node.then_body, escaped, in_scope)
                for (_, eb) in node.elifs:
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
            return [node.name]  # Set → List
        if isinstance(node, BinaryOp):
            return (self._idents(node.left) | self._idents(node.right))
        if isinstance(node, UnaryOp):
            return self._idents(node.operand)
        if isinstance(node, CallExpr):
            let r = set()
            for a in node.args:
                r |= self._idents(a)
            return r
        if isinstance(node, MemberExpr):
            return self._idents(node.obj)
        if isinstance(node, SubscriptExpr):
            return (self._idents(node.obj) | self._idents(node.index))
        if isinstance(node, TernaryExpr):
            return ((self._idents(node.condition) | self._idents(node.then_val)) | self._idents(node.else_val))
        return set()

struct LayoutSolver:
    var _struct_types: AnyType
    var _ea: AnyType
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
    let STACK = 'stack'  # inferred: String
    let HEAP = 'heap'  # inferred: String
    fn __init__(self, struct_field_types: dict):
        self._struct_types = set(struct_field_types.keys())
        self._ea = EscapeAnalyzer(self._struct_types)
    fn solve(self, params: list, body: list) -> dict:
        """Return {var_name: STACK|HEAP} for struct-typed locals in *body*."""
        let has_try = self._has_try(body)
        let escaped = self._ea.find_escaping(params, body)
        let locals_ = self._struct_locals(body)
        let result = {}  # inferred: Dict[AnyType, AnyType]
        for name in locals_:
            if has_try or name in escaped:
                result[name] = self.HEAP
            else:
                result[name] = self.STACK
        return result
    fn _struct_locals(self, stmts: list) -> set:
        var result: DynamicVector[String] = set()
        for node in stmts:
            if isinstance(node, VarDecl) and node.type_ann in self._struct_types:
                result.add(node.name)
            elif isinstance(node, IfStmt):
                result |= self._struct_locals(node.then_body)
                for (_, eb) in node.elifs:
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
    fn _has_try(self, stmts: list) -> Bool:
        for node in stmts:
            if isinstance(node, TryStmt):
                return True
            if isinstance(node, IfStmt):
                var _tmp2 = DynamicVector[AnyType]()
                for (_, eb) in node.elifs:
                    _tmp2.append(self._has_try(eb))
                if self._has_try(node.then_body) or any(_tmp2) or node.else_body and self._has_try(node.else_body):
                    return True
            if isinstance(node, (WhileStmt, ForStmt)) and self._has_try(node.body):
                return True
        return False

var _TYPE_MAP: Dict[AnyType, String] = {'Int': 'int', 'Int8': 'int8_t', 'Int16': 'int16_t', 'Int32': 'int32_t', 'Int64': 'int64_t', 'UInt': 'unsigned int', 'UInt8': 'uint8_t', 'UInt16': 'uint16_t', 'UInt32': 'uint32_t', 'UInt64': 'uint64_t', 'Float16': '__fp16', 'Float32': 'float', 'Float64': 'double', 'Bool': 'int', 'String': 'char *', 'List': 'MojoList *', 'Dict': 'MojoDict *', 'Set': 'MojoSet *', 'Str': 'MojoStr *', 'None': 'void', None: 'int'}

var _RUNTIME_FUNCS: Dict[String, String] = {'mojo_try_push': 'int', 'mojo_exc_pop': 'void', 'mojo_raise': 'void', 'mojo_exc_msg_set': 'void', 'mojo_exc_msg_get': 'char *', 'mojo_list_new': 'MojoList *', 'mojo_list_len': 'int64_t', 'mojo_list_get_int': 'int64_t', 'mojo_list_get_double': 'double', 'mojo_list_get_str': 'char *', 'mojo_list_contains_int': 'int', 'mojo_list_contains_double': 'int', 'mojo_list_contains_str': 'int', 'mojo_list_set_int': 'void', 'mojo_list_set_double': 'void', 'mojo_list_set_str': 'void', 'mojo_list_slice': 'MojoList *', 'mojo_list_concat': 'MojoList *', 'mojo_dict_new': 'MojoDict *', 'mojo_dict_get_int': 'int64_t', 'mojo_dict_get_double': 'double', 'mojo_dict_get_str': 'char *', 'mojo_dict_contains': 'int', 'mojo_dict_len': 'int64_t', 'mojo_dict_iter_new': 'MojoDictIter *', 'mojo_dict_iter_next': 'int', 'mojo_dict_iter_key': 'char *', 'mojo_dict_iter_val_int': 'int64_t', 'mojo_dict_iter_val_double': 'double', 'mojo_dict_iter_val_str': 'char *', 'mojo_dict_iter_free': 'void', 'mojo_set_new': 'MojoSet *', 'mojo_set_contains_int': 'int', 'mojo_set_contains_str': 'int', 'mojo_set_len': 'int64_t', 'mojo_set_iter_new': 'MojoSetIter *', 'mojo_set_iter_next': 'int', 'mojo_set_iter_val_int': 'int64_t', 'mojo_set_iter_val_str': 'char *', 'mojo_set_iter_free': 'void', 'mojo_str_new': 'MojoStr *', 'mojo_str_concat': 'MojoStr *', 'mojo_str_len': 'int64_t', 'mojo_str_data': 'char *', 'mojo_str_char_at': 'char', 'mojo_str_eq': 'int', 'mojo_str_contains': 'int', 'mojo_str_slice': 'MojoStr *', 'mojo_str_from_char': 'MojoStr *', 'mojo_str_repeat': 'MojoStr *', 'mojo_str_to_int': 'int64_t', 'mojo_str_to_float': 'double'}

let _FLOAT_TYPES = ['double', 'float', '__fp16']  # Set → List

def _mojo_type(ann) -> String:
    if ann is None:
        return 'int'
    if isinstance(ann, str):
        if '[' in ann:
            var _tmp3 = ann.split('[', 1)
            let base = _tmp3[0]
            let rest = _tmp3[1]
            let inner = rest.rstrip(']').strip()
            if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
                let elem = _mojo_type(inner)
                return str(elem) + ' *'
            if base in ('List', 'InlineArray'):
                return 'MojoList *'
            if base == 'Dict':
                return 'MojoDict *'
            if base == 'Set':
                return 'MojoSet *'
            if base == 'Optional':
                return _mojo_type(inner)
            let ann = base
        let t = _TYPE_MAP.get(ann)
        return t if t is not None else 'int'
    return 'int'

fn _result_type(t1: String, t2: String) -> String:
    return TypeLattice.join(t1, t2)

fn _elem_type(ptr_type: String) -> String:
    """Strip one level of pointer to get element type."""
    if ptr_type.endswith(' *'):
        return ptr_type[:-2]
    if '*' in ptr_type:
        return ptr_type.replace('*', '').strip()
    return 'int'

let _C_ID_MAP = {'char *': 'charptr', 'void *': 'voidptr', '_Bool': 'bool'}  # inferred: Dict[AnyType, AnyType]

fn _c_id(ctype: String) -> String:
    """Convert a C type to a valid identifier suffix (for helper function names)."""
    return _C_ID_MAP.get(ctype, ctype.replace(' ', '_').replace('*', 'ptr'))

fn _printf_fmt(ctype: String) -> String:
    return TypeLattice.printf_fmt(ctype)

let _BIN_OPS = _GD_BIN_OPS

let _CMP_OPS = _GD_CMP_OPS

let _C_KEYWORDS = frozenset(['auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do', 'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if', 'inline', 'int', 'long', 'register', 'restrict', 'return', 'short', 'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef', 'union', 'unsigned', 'void', 'volatile', 'while', '_Bool', '_Complex', '_Imaginary', '_Alignas', '_Alignof', '_Atomic', '_Generic', '_Noreturn', '_Static_assert', '_Thread_local'])  # Set → List

fn _safe_name(name: String) -> String:
    return 'mojo_' + str(name) if name in _C_KEYWORDS else name

def _used_idents_node(node) -> set:
    """All IdentExpr names referenced in node; does NOT cross FunctionDef boundaries."""
    if node is None:
        return set()
    if isinstance(node, IdentExpr):
        return [node.name]  # Set → List
    if isinstance(node, FunctionDef):
        return set()
    if isinstance(node, BinaryOp):
        return (_used_idents_node(node.left) | _used_idents_node(node.right))
    if isinstance(node, UnaryOp):
        return _used_idents_node(node.operand)
    if isinstance(node, CallExpr):
        let r = _used_idents_node(node.func)
        for a in node.args:
            r |= _used_idents_node(a)
        return r
    if isinstance(node, MemberExpr):
        return _used_idents_node(node.obj)
    if isinstance(node, SubscriptExpr):
        return (_used_idents_node(node.obj) | _used_idents_node(node.index))
    if isinstance(node, SliceExpr):
        let r = _used_idents_node(node.obj)
        if node.start:
            r |= _used_idents_node(node.start)
        if node.stop:
            r |= _used_idents_node(node.stop)
        return r
    if isinstance(node, TernaryExpr):
        return ((_used_idents_node(node.condition) | _used_idents_node(node.then_val)) | _used_idents_node(node.else_val))
    if isinstance(node, WalrusExpr):
        return ([node.name] | _used_idents_node(node.value))  # Set → List
    if isinstance(node, (ListExpr, SetExpr, TupleExpr)):
        var r: set = set()
        for e in node.elements:
            r |= _used_idents_node(e)
        return r
    if isinstance(node, DictExpr):
        var r2: set = set()
        for (k, v) in node.pairs:
            r2 |= (_used_idents_node(k) | _used_idents_node(v))
        return r2
    if isinstance(node, Comprehension):
        let r3 = _used_idents_node(node.expr)
        for g in node.generators:
            r3 |= _used_idents_node(g.iterable)
        return r3
    if isinstance(node, (PassStmt, BreakStmt, ContinueStmt)):
        return set()
    if isinstance(node, ReturnStmt):
        return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, RaiseStmt):
        return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, ExprStmt):
        return _used_idents_node(node.value)
    if isinstance(node, AssertStmt):
        return _used_idents_node(node.value)
    if isinstance(node, VarDecl):
        return _used_idents_node(node.value) if node.value else set()
    if isinstance(node, AssignStmt):
        return (_used_idents_node(node.target) | _used_idents_node(node.value))
    if isinstance(node, AugAssignStmt):
        return (_used_idents_node(node.target) | _used_idents_node(node.value))
    if isinstance(node, MultiAssignStmt):
        let r4 = _used_idents_node(node.value)
        for t in node.targets:
            r4 |= _used_idents_node(t)
        return r4
    if isinstance(node, IfStmt):
        let r5 = _used_idents_node(node.condition)
        for s in node.then_body:
            r5 |= _used_idents_node(s)
        for (_, eb) in node.elifs:
            for s in eb:
                r5 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body:
                r5 |= _used_idents_node(s)
        return r5
    if isinstance(node, WhileStmt):
        let r6 = _used_idents_node(node.condition)
        for s in node.body:
            r6 |= _used_idents_node(s)
        return r6
    if isinstance(node, ForStmt):
        let r7 = _used_idents_node(node.iterable)
        for s in node.body:
            r7 |= _used_idents_node(s)
        return r7
    if isinstance(node, TryStmt):
        var r8: set = set()
        for s in node.body:
            r8 |= _used_idents_node(s)
        for h in node.handlers:
            for s in h.body:
                r8 |= _used_idents_node(s)
        if node.else_body:
            for s in node.else_body:
                r8 |= _used_idents_node(s)
        if node.finally_body:
            for s in node.finally_body:
                r8 |= _used_idents_node(s)
        return r8
    if isinstance(node, WithStmt):
        var r9: set = set()
        for item in node.items:
            r9 |= _used_idents_node(item.expr)
        for s in node.body:
            r9 |= _used_idents_node(s)
        return r9
    return set()

def _declared_vars_body(stmts) -> set:
    """Variables declared in a statement list (does not cross FunctionDef boundaries)."""
    var result: set = set()
    for node in stmts:
        if isinstance(node, VarDecl):
            result.add(node.name)
        elif isinstance(node, ForStmt):
            let tgt = node.target
            result.add(tgt if isinstance(tgt, str) else tgt.name)
            result |= _declared_vars_body(node.body)
        elif isinstance(node, IfStmt):
            result |= _declared_vars_body(node.then_body)
            for (_, eb) in node.elifs:
                result |= _declared_vars_body(eb)
            if node.else_body:
                result |= _declared_vars_body(node.else_body)
        elif isinstance(node, (WhileStmt, WithStmt)):
            result |= _declared_vars_body(node.body)
        elif isinstance(node, TryStmt):
            result |= _declared_vars_body(node.body)
            for h in node.handlers:
                if h.name:
                    result.add(h.name)
                result |= _declared_vars_body(h.body)
            if node.else_body:
                result |= _declared_vars_body(node.else_body)
            if node.finally_body:
                result |= _declared_vars_body(node.finally_body)
    return result

struct ClosureInfo:
    var lifted_name: String
    var env_struct: String
    var captures: list
    var inner_def: AnyType
    """Describes a nested function lifted to module scope."""
    def __init__(self, lifted_name: String, env_struct: String, captures: list, inner_def):
        self.lifted_name = lifted_name
        self.env_struct = env_struct
        self.captures = captures
        self.inner_def = inner_def

let _HELPERS = 'static int __mojo_floordiv (int a, int b)\n{\n  int q = a / b;\n  return q - (a % b != 0 && (a ^ b) < 0);\n}\n'  # inferred: String

struct GimpleGen:
    var func_return_types: Dict[String, String]
    var struct_field_types: Dict[String, Dict[String, String]]
    var imported_symbols: Dict[String, tuple]
    var _all_closures: dict
    var _ptr_helpers_needed: DynamicVector[String]
    var _struct_allocs_needed: DynamicVector[String]
    fn __init__(self):
        self.func_return_types = {}
        self.struct_field_types = {}
        self.imported_symbols = {}
        self._all_closures = {}
        self._ptr_helpers_needed = set()
        self._struct_allocs_needed = set()
        self._reset_func()
    fn _reset_func(self):
        self.bb_counter = 2
        self.temp_counter = 0
        self.decls = []
        self.body_lines = []
        self.var_types = {}
        self.loop_stack = []
        self.exc_depth = 0
        self.func_ret_type = ''
        self._elem_types = {}
        self._dict_val_types = {}
        self._struct_layout = {}
        self._layout_hint = LayoutSolver.HEAP
        self.current_func_name = ''
        self._loop_depth = 0
        self._captures = {}
        self._env_param = ''
        self._closure_envs = {}
    fn _new_bb(self) -> String:
        self.bb_counter += 1
        return 'bb_' + str(self.bb_counter)
    fn _new_temp(self, ctype: String) -> String:
        self.temp_counter += 1
        let name = '_t' + str(self.temp_counter)  # inferred: String
        self.decls.append('  ' + str(ctype) + ' ' + str(name) + ';')
        self.var_types[name] = ctype
        return name
    fn _emit(self, line: String):
        self.body_lines.append(line)
    fn _emit_label(self, label: String, freq_hint: String):
        let ann = '  /* ' + str(freq_hint) + ' */' if freq_hint else ''
        self.body_lines.append('\n' + str(label) + ':' + str(ann))
    fn _type_of(self, name: String) -> String:
        return self.var_types.get(name, 'int')
    fn _elem_of(self, name: String) -> String:
        """Element type for a container variable."""
        return self._elem_types.get(name, 'int64_t')
    fn _dict_val_of(self, name: String) -> String:
        """Value C type for a dict variable."""
        return self._dict_val_types.get(name, 'int64_t')
    fn _coerce(self, src: String, dst: String, val: String) -> String:
        return TypeLattice.coerce(src, dst, val)
    def _resolve_type(self, ann) -> String:
        if ann in self.struct_field_types:
            return str(ann) + ' *'
        return _mojo_type(ann)
    # TODO: map param type str | None for 'elem'
    def _declare_var(self, name: String, ctype: String, elem: AnyType):
        if name not in self.var_types:
            self.decls.append('  ' + str(ctype) + ' ' + str(name) + ';')
            self.var_types[name] = ctype
        if elem is not None:
            self._elem_types[name] = elem
    fn _new_jbp_temp(self) -> String:
        self.temp_counter += 1
        let name = '_jbp' + str(self.temp_counter)  # inferred: String
        self.decls.append('  jmp_buf *' + str(name) + ';')
        return name
    def _quick_type(self, node) -> String:
        """Estimate C type of an expression without emitting code."""
        if isinstance(node, IntLiteral):
            return 'int'
        if isinstance(node, FloatLiteral):
            return 'double'
        if isinstance(node, BoolLiteral):
            return '_Bool'
        if isinstance(node, StringLiteral):
            return 'char *'
        if isinstance(node, IdentExpr):
            return self.var_types.get(node.name, 'int')
        if isinstance(node, BinaryOp):
            if node.op in _CMP_OPS:
                return '_Bool'
            let lt = self._quick_type(node.left)
            let rt = self._quick_type(node.right)
            return TypeLattice.join(lt, rt)
        if isinstance(node, UnaryOp):
            if node.op == 'not':
                return '_Bool'
            return self._quick_type(node.operand)
        if isinstance(node, TernaryExpr):
            return TypeLattice.join(self._quick_type(node.then_val), self._quick_type(node.else_val))
        if isinstance(node, CallExpr) and isinstance(node.func, IdentExpr):
            return self.func_return_types.get(node.func.name, 'int')
        if isinstance(node, MemberExpr):
            let ot = self._quick_type(node.obj)
            let sn = ot.replace(' *', '').strip()
            return self.struct_field_types.get(sn, {}).get(node.member, 'int')
        if isinstance(node, ListExpr):
            return 'MojoList *'
        if isinstance(node, DictExpr):
            return 'MojoDict *'
        if isinstance(node, SetExpr):
            return 'MojoSet *'
        if isinstance(node, TupleExpr):
            return 'MojoList *'
        return 'int'
    fn _collect_return_types(self, stmts: list, acc: list):
        """Collect return-expression C types from all ReturnStmt nodes."""
        for node in stmts:
            if isinstance(node, ReturnStmt):
                acc.append('void' if node.value is None else self._quick_type(node.value))
            elif isinstance(node, IfStmt):
                self._collect_return_types(node.then_body, acc)
                for (_, eb) in node.elifs:
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
    fn _infer_return_type(self, body: list) -> String:
        """Infer return type by scanning body for ReturnStmt nodes."""
        var acc: DynamicVector[String] = []
        self._collect_return_types(body, acc)
        return TypeLattice.join_all(acc) if acc else 'void'
    fn _infer_list_elem_type(self, elements: list) -> String:
        """Determine element C type for a list/set/tuple literal."""
        if not elements:
            return 'int64_t'
        var types = DynamicVector[AnyType]()
        for e in elements:
            types.append(self._quick_type(e))
        return TypeLattice.join_all(types) if types else 'int64_t'
    def lower_expr(self, node) -> StaticTuple[String, 2]:
        """Return (ctype, simple_rvalue). May emit temp assignments."""
        let handler_name = _EXPR_DISPATCH.get(type(node).__name__)
        if handler_name:
            return getattr(self, handler_name)(node)
        self._emit('  /* TODO: unknown expr ' + str(type(node).__name__) + ' */')
        let t = self._new_temp('int')
        self._emit('  ' + str(t) + ' = 0;')
        return ('int', t)
    def _lower_IntLiteral(self, node) -> StaticTuple[String, 2]:
        return ('int', str(node.value))
    def _lower_FloatLiteral(self, node) -> StaticTuple[String, 2]:
        var s = repr(node.value)
        if '.' not in s and 'e' not in s.lower():
            s += '.0'
        return ('double', s)
    def _lower_BoolLiteral(self, node) -> StaticTuple[String, 2]:
        return ('int', '1' if node.value else '0')
    def _lower_EllipsisLiteral(self, node) -> StaticTuple[String, 2]:
        let t = self._new_temp('int')
        self._emit('  ' + str(t) + ' = 0;  /* ... */')
        return ('int', t)
    def _lower_StringLiteral(self, node) -> StaticTuple[String, 2]:
        let escaped = node.value.replace('\\', '\\\\').replace('"', '\\"')
        return ('char *', '"' + str(escaped) + '"')
    def _lower_IdentExpr(self, node) -> StaticTuple[String, 2]:
        let name = node.name
        if name in self._captures and self._env_param:
            let ctype = self._captures[name]
            let t = self._new_temp(ctype)
            self._emit('  ' + str(t) + ' = ' + str(self._env_param) + '->' + str(name) + ';')
            return (ctype, t)
        return (self._type_of(name), name)
    def _lower_WalrusExpr(self, node) -> StaticTuple[String, 2]:
        var _tmp4 = self.lower_expr(node.value)
        let vtype = _tmp4[0]
        let vv = _tmp4[1]
        if node.name not in self.var_types:
            self._declare_var(node.name, vtype)
        let dst = self.var_types[node.name]
        self._emit('  ' + str(node.name) + ' = ' + str(self._coerce(vtype, dst, vv)) + ';')
        return (dst, node.name)
    def _lower_UnaryOp(self, node) -> StaticTuple[String, 2]:
        var _tmp5 = self.lower_expr(node.operand)
        let ot = _tmp5[0]
        let ov = _tmp5[1]
        if node.op == 'not':
            let t = self._new_temp('_Bool')
            self._emit('  ' + str(t) + ' = ' + str(ov) + ' == 0;')
            return ('_Bool', t)
        let c_op = {'-': '-', '~': '~', '+': '+'}.get(node.op, node.op)
        var t = self._new_temp(ot)
        self._emit('  ' + str(t) + ' = ' + str(c_op) + str(ov) + ';')
        return (ot, t)
    def _lower_TernaryExpr(self, node) -> StaticTuple[String, 2]:
        var _tmp6 = self.lower_expr(node.condition)
        let ct = _tmp6[0]
        let cv = _tmp6[1]
        var _tmp7 = self.lower_expr(node.then_val)
        let tt = _tmp7[0]
        let tv = _tmp7[1]
        var _tmp8 = self.lower_expr(node.else_val)
        let et = _tmp8[0]
        let ev = _tmp8[1]
        let res_type = TypeLattice.join(tt, et)
        let t = self._new_temp(res_type)
        self._emit('  ' + str(t) + ' = ' + str(cv) + ' ? ' + str(tv) + ' : ' + str(ev) + ';')
        return (res_type, t)
    def _lower_MemberExpr(self, node) -> StaticTuple[String, 2]:
        var _tmp9 = self.lower_expr(node.obj)
        let ot = _tmp9[0]
        let ov = _tmp9[1]
        let op = '->' if '*' in ot else '.'
        let struct_name = ot.replace(' *', '').strip()
        let field_type = self.struct_field_types.get(struct_name, {}).get(node.member, 'int')
        let t = self._new_temp(field_type)
        self._emit('  ' + str(t) + ' = ' + str(ov) + str(op) + str(node.member) + ';')
        return (field_type, t)
    fn _lower_binary(self, node: BinaryOp) -> StaticTuple[String, 2]:
        if node.op == ':=':
            var _tmp10 = self.lower_expr(node.right)
            let vtype = _tmp10[0]
            let vv = _tmp10[1]
            if isinstance(node.left, IdentExpr):
                let nm = node.left.name
                if nm not in self.var_types:
                    self._declare_var(nm, vtype)
                let dst = self.var_types[nm]
                self._emit('  ' + str(nm) + ' = ' + str(self._coerce(vtype, dst, vv)) + ';')
                return (dst, nm)
            if isinstance(node.left, MemberExpr):
                var _tmp11 = self.lower_expr(node.left.obj)
                let ot = _tmp11[0]
                let ov = _tmp11[1]
                let op = '->' if '*' in ot else '.'
                let sn = ot.replace(' *', '').strip()
                let field_type = self.struct_field_types.get(sn, {}).get(node.left.member, vtype)
                self._emit('  ' + str(ov) + str(op) + str(node.left.member) + ' = ' + str(self._coerce(vtype, field_type, vv)) + ';')
                return (field_type, vv)
            if isinstance(node.left, SubscriptExpr):
                var _tmp12 = self.lower_expr(node.left.obj)
                let ot = _tmp12[0]
                let obj_v = _tmp12[1]
                var _tmp13 = self.lower_expr(node.left.index)
                let _ = _tmp13[0]
                let idx_v = _tmp13[1]
                if ot == 'MojoList *':
                    let elem = self._elem_of(obj_v)
                    let suf = TypeLattice.list_suffix(elem)
                    let idx64 = self._new_temp('int64_t')
                    self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(idx_v) + ';')
                    let ev_cast = self._cast_for_list(vtype, vv, suf)
                    self._emit('  mojo_list_set_' + str(suf) + ' (' + str(obj_v) + ', ' + str(idx64) + ', ' + str(ev_cast) + ');')
                else:
                    self._emit('  ' + str(obj_v) + '[' + str(idx_v) + '] = ' + str(vv) + ';')
                return (vtype, vv)
            self._emit('  /* walrus: unsupported LHS */')
            return (vtype, vv)
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
        var _tmp14 = self.lower_expr(node.left)
        let lt = _tmp14[0]
        let lv = _tmp14[1]
        var _tmp15 = self.lower_expr(node.right)
        let rt = _tmp15[0]
        let rv = _tmp15[1]
        if node.op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
            let t = self._new_temp('MojoList *')
            self._emit('  ' + str(t) + ' = mojo_list_concat (' + str(lv) + ', ' + str(rv) + ');')
            if lv in self._elem_types:
                self._elem_types[t] = self._elem_types[lv]
            return ('MojoList *', t)
        if node.op == '+' and lt == 'MojoStr *' and rt == 'MojoStr *':
            let t = self._new_temp('MojoStr *')
            self._emit('  ' + str(t) + ' = mojo_str_concat (' + str(lv) + ', ' + str(rv) + ');')
            return ('MojoStr *', t)
        if node.op in ('==', '!=') and lt == 'MojoStr *' and rt == 'MojoStr *':
            let eq_t = self._new_temp('int')
            self._emit('  ' + str(eq_t) + ' = mojo_str_eq (' + str(lv) + ', ' + str(rv) + ');')
            let t = self._new_temp('_Bool')
            let cmp = '!= 0' if node.op == '==' else '== 0'
            self._emit('  ' + str(t) + ' = ' + str(eq_t) + ' ' + str(cmp) + ';')
            return ('_Bool', t)
        if node.op in ('is', 'is not'):
            let c_op = '==' if node.op == 'is' else '!='
            let t = self._new_temp('_Bool')
            if '*' in lt or '*' in rt:
                let p1 = self._new_temp('void *')
                let p2 = self._new_temp('void *')
                self._emit('  ' + str(p1) + ' = (void *) ' + str(lv) + ';')
                self._emit('  ' + str(p2) + ' = (void *) ' + str(rv) + ';')
                self._emit('  ' + str(t) + ' = ' + str(p1) + ' ' + str(c_op) + ' ' + str(p2) + ';')
            else:
                self._emit('  ' + str(t) + ' = ' + str(lv) + ' ' + str(c_op) + ' ' + str(rv) + ';')
            return ('_Bool', t)
        var c_op = _BIN_OPS.get(node.op, node.op)
        let res_type = '_Bool' if node.op in _CMP_OPS else TypeLattice.join(lt, rt)
        let arith_type = TypeLattice.join(lt, rt)
        if lt != arith_type and arith_type not in ('_Bool',):
            let ct = self._new_temp(arith_type)
            self._emit('  ' + str(ct) + ' = (' + str(arith_type) + ')' + str(lv) + ';')
            let lv = ct
        if rt != arith_type and arith_type not in ('_Bool',):
            let ct = self._new_temp(arith_type)
            self._emit('  ' + str(ct) + ' = (' + str(arith_type) + ')' + str(rv) + ';')
            let rv = ct
        var t = self._new_temp(res_type)
        self._emit('  ' + str(t) + ' = ' + str(lv) + ' ' + str(c_op) + ' ' + str(rv) + ';')
        return (res_type, t)
    fn _lower_floordiv(self, node: BinaryOp) -> StaticTuple[String, 2]:
        var _tmp16 = self.lower_expr(node.left)
        let lt = _tmp16[0]
        let lv = _tmp16[1]
        var _tmp17 = self.lower_expr(node.right)
        let rt = _tmp17[0]
        let rv = _tmp17[1]
        if lt in _FLOAT_TYPES or rt in _FLOAT_TYPES:
            let td = TypeLattice.join(lt, rt)
            let t1 = self._new_temp(td)
            self._emit('  ' + str(t1) + ' = ' + str(lv) + ' / ' + str(rv) + ';')
            let t2 = self._new_temp(td)
            self._emit('  ' + str(t2) + ' = __builtin_floor (' + str(t1) + ');')
            return (td, t2)
        let t = self._new_temp('int')
        self._emit('  ' + str(t) + ' = __mojo_floordiv (' + str(lv) + ', ' + str(rv) + ');')
        return ('int', t)
    fn _lower_pow(self, node: BinaryOp) -> StaticTuple[String, 2]:
        var _tmp18 = self.lower_expr(node.left)
        let lt = _tmp18[0]
        let lv = _tmp18[1]
        var _tmp19 = self.lower_expr(node.right)
        let rt = _tmp19[0]
        let rv = _tmp19[1]
        if lt in _FLOAT_TYPES or rt in _FLOAT_TYPES:
            let td = TypeLattice.join(lt, rt)
            let t = self._new_temp(td)
            self._emit('  ' + str(t) + ' = pow (' + str(lv) + ', ' + str(rv) + ');')
            return (td, t)
        let t1 = self._new_temp('double')
        let t2 = self._new_temp('double')
        self._emit('  ' + str(t1) + ' = (double) ' + str(lv) + ';')
        self._emit('  ' + str(t2) + ' = (double) ' + str(rv) + ';')
        let t3 = self._new_temp('double')
        self._emit('  ' + str(t3) + ' = pow (' + str(t1) + ', ' + str(t2) + ');')
        let t4 = self._new_temp('int')
        self._emit('  ' + str(t4) + ' = (int) ' + str(t3) + ';')
        return ('int', t4)
    fn _lower_matmul(self, node: BinaryOp) -> StaticTuple[String, 2]:
        """Lower matrix multiply: a @ b → a.__matmul__(b)

        Calls the __matmul__ method on the left operand.
        TODO: Implement high-performance matrix multiplication using BLAS (e.g., dgemm)
        or SIMD intrinsics for larger matrices. For now, delegates to user-defined
        __matmul__ implementations on matrix types.
        """
        var _tmp20 = self.lower_expr(node.left)
        let lt = _tmp20[0]
        let lv = _tmp20[1]
        var _tmp21 = self.lower_expr(node.right)
        let rt = _tmp21[0]
        let rv = _tmp21[1]
        let struct_name = lt.replace(' *', '').strip()
        let mangled = str(struct_name) + '___matmul__'  # inferred: String
        let result_type = self.func_return_types.get(mangled, 'int')
        let t = self._new_temp(result_type)
        self._emit('  ' + str(t) + ' = ' + str(mangled) + ' (' + str(lv) + ', ' + str(rv) + ');')
        return (result_type, t)
    fn _lower_in_range(self, x_val: String, range_args: list, negate: Bool) -> StaticTuple[String, 2]:
        if len(range_args) == 1:
            var _tmp22 = self.lower_expr(range_args[0])
            let _ = _tmp22[0]
            let n_val = _tmp22[1]
            let t1 = self._new_temp('_Bool')
            let t2 = self._new_temp('_Bool')
            let t3 = self._new_temp('_Bool')
            self._emit('  ' + str(t1) + ' = ' + str(x_val) + ' >= 0;')
            self._emit('  ' + str(t2) + ' = ' + str(x_val) + ' < ' + str(n_val) + ';')
            self._emit('  ' + str(t3) + ' = ' + str(t1) + ' & ' + str(t2) + ';')
        elif len(range_args) == 2:
            var _tmp23 = self.lower_expr(range_args[0])
            let _ = _tmp23[0]
            let a_val = _tmp23[1]
            var _tmp24 = self.lower_expr(range_args[1])
            let _ = _tmp24[0]
            let b_val = _tmp24[1]
            let t1 = self._new_temp('_Bool')
            let t2 = self._new_temp('_Bool')
            let t3 = self._new_temp('_Bool')
            self._emit('  ' + str(t1) + ' = ' + str(x_val) + ' >= ' + str(a_val) + ';')
            self._emit('  ' + str(t2) + ' = ' + str(x_val) + ' < ' + str(b_val) + ';')
            self._emit('  ' + str(t3) + ' = ' + str(t1) + ' & ' + str(t2) + ';')
        else:
            self._emit('  /* TODO: in range(a, b, step) */')
            let t3 = self._new_temp('_Bool')
            self._emit('  ' + str(t3) + ' = 0;')
        if negate:
            let ti = self._new_temp('int')
            let tn = self._new_temp('_Bool')
            self._emit('  ' + str(ti) + ' = (int) ' + str(t3) + ';')
            self._emit('  ' + str(tn) + ' = ' + str(ti) + ' == 0;')
            return ('_Bool', tn)
        return ('_Bool', t3)
    fn _lower_in_impl(self, node: BinaryOp, negate: Bool) -> StaticTuple[String, 2]:
        var _tmp25 = self.lower_expr(node.left)
        let xt = _tmp25[0]
        let xv = _tmp25[1]
        if isinstance(node.right, CallExpr) and isinstance(node.right.func, IdentExpr) and node.right.func.name == 'range':
            return self._lower_in_range(xv, node.right.args, negate=negate)
        var _tmp26 = self.lower_expr(node.right)
        let rt = _tmp26[0]
        let rv = _tmp26[1]
        let ti = self._new_temp('int')
        if rt == 'MojoList *':
            let suf = TypeLattice.list_suffix(xt)
            let xv_cast = self._cast_for_list(xt, xv, suf)
            self._emit('  ' + str(ti) + ' = mojo_list_contains_' + str(suf) + ' (' + str(rv) + ', ' + str(xv_cast) + ');')
        elif rt == 'MojoDict *':
            self._emit('  ' + str(ti) + ' = mojo_dict_contains (' + str(rv) + ', ' + str(xv) + ');')
        elif rt == 'MojoSet *':
            if xt == 'char *':
                self._emit('  ' + str(ti) + ' = mojo_set_contains_str (' + str(rv) + ', ' + str(xv) + ');')
            else:
                let xv64 = self._to_int64(xt, xv)
                self._emit('  ' + str(ti) + ' = mojo_set_contains_int (' + str(rv) + ', ' + str(xv64) + ');')
        elif rt == 'MojoStr *':
            self._emit('  ' + str(ti) + ' = mojo_str_contains (' + str(rv) + ', ' + str(xv) + ');')
        else:
            self._emit("  /* TODO: 'in' for " + str(rt) + ' */')
            self._emit('  ' + str(ti) + ' = 0;')
        let t = self._new_temp('_Bool')
        self._emit('  ' + str(t) + ' = ' + str(ti) + ' != 0;')
        if negate:
            let ti2 = self._new_temp('int')
            let tn = self._new_temp('_Bool')
            self._emit('  ' + str(ti2) + ' = (int) ' + str(t) + ';')
            self._emit('  ' + str(tn) + ' = ' + str(ti2) + ' == 0;')
            return ('_Bool', tn)
        return ('_Bool', t)
    fn _cast_for_list(self, elem_type: String, val: String, suf: String) -> String:
        """Coerce a value to the API's expected type; always returns an lvalue (temp if cast needed)."""
        if suf == 'int':
            return self._to_int64(elem_type, val)
        if suf == 'double':
            if elem_type == 'double':
                return val
            let t = self._new_temp('double')
            self._emit('  ' + str(t) + ' = (double)' + str(val) + ';')
            return t
        return val
    fn _to_int64(self, ctype: String, val: String) -> String:
        """Cast val to int64_t; emits to a temp so the result is always an lvalue."""
        if ctype == 'int64_t':
            return val
        let t = self._new_temp('int64_t')
        self._emit('  ' + str(t) + ' = (int64_t)' + str(val) + ';')
        return t
    let _RUNTIME_PTRS = frozenset(['MojoList *', 'MojoStr *', 'MojoDict *', 'MojoSet *', 'MojoDictIter *', 'MojoSetIter *'])  # Set → List
    fn _lower_method_call(self, node: CallExpr) -> StaticTuple[String, 2]:
        """Lower obj.method(args) — handles raw C pointers (UnsafePointer) and structs."""
        let func = node.func
        var _tmp27 = self.lower_expr(func.obj)
        let ot = _tmp27[0]
        let ov = _tmp27[1]
        let method = func.member
        if ot.endswith(' *') and ot not in self._RUNTIME_PTRS:
            let elem = _elem_type(ot)
            if method == 'load':
                let t = self._new_temp(elem)
                self._emit('  ' + str(t) + ' = *' + str(ov) + ';')
                return (elem, t)
            if method == 'store' and node.args:
                var _tmp28 = self.lower_expr(node.args[0])
                let _ = _tmp28[0]
                let av = _tmp28[1]
                self._emit('  *' + str(ov) + ' = ' + str(self._coerce(self._quick_type(node.args[0]), elem, av)) + ';')
                let t = self._new_temp('int')
                self._emit('  ' + str(t) + ' = 0;')
                return ('int', t)
            if method == 'offset' and node.args:
                var _tmp29 = self.lower_expr(node.args[0])
                let _ = _tmp29[0]
                let nv = _tmp29[1]
                let elem = _elem_type(ot)
                let cn = _c_id(elem)
                self._ptr_helpers_needed.add(elem)
                let idx64 = self._new_temp('int64_t')
                self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(nv) + ';')
                let t = self._new_temp(ot)
                self._emit('  ' + str(t) + ' = _mojo_at_' + str(cn) + ' (' + str(ov) + ', ' + str(idx64) + ');')
                return (ot, t)
            if method == 'free':
                self._emit('  free (' + str(ov) + ');')
                let t = self._new_temp('int')
                self._emit('  ' + str(t) + ' = 0;')
                return ('int', t)
            if method in ('bitcast', 'address_of'):
                let t = self._new_temp(ot)
                self._emit('  ' + str(t) + ' = ' + str(ov) + ';  /* TODO: ' + str(method) + ' */')
                return (ot, t)
            if method in ('destroy_pointee', 'take_pointee', 'initialize_pointee'):
                if node.args and method == 'initialize_pointee':
                    var _tmp30 = self.lower_expr(node.args[0])
                    let _ = _tmp30[0]
                    let av = _tmp30[1]
                    self._emit('  *' + str(ov) + ' = ' + str(av) + ';')
                let t = self._new_temp('int')
                self._emit('  ' + str(t) + ' = 0;')
                return ('int', t)
            if method in ('strided_load', 'gather'):
                let t = self._new_temp(elem)
                self._emit('  ' + str(t) + ' = *' + str(ov) + ';  /* TODO: ' + str(method) + ' */')
                return (elem, t)
            if method in ('strided_store', 'scatter'):
                let t = self._new_temp('int')
                self._emit('  ' + str(t) + ' = 0;  /* TODO: ' + str(method) + ' */')
                return ('int', t)
        let struct_name = ot.replace(' *', '').strip()
        let mangled = _safe_name(str(struct_name) + '_' + str(method))
        let ret_type = self.func_return_types.get(str(struct_name) + '_' + str(method), 'int')
        var arg_vals = DynamicVector[AnyType]()
        for a in node.args:
            arg_vals.append(self.lower_expr(a)[1])
        let all_args = ', '.join(([ov] + arg_vals))
        if ret_type == 'void':
            self._emit('  ' + str(mangled) + ' (' + str(all_args) + ');')
            let t = self._new_temp('int')
            self._emit('  ' + str(t) + ' = 0;')
            return ('int', t)
        var t = self._new_temp(ret_type)
        self._emit('  ' + str(t) + ' = ' + str(mangled) + ' (' + str(all_args) + ');')
        return (ret_type, t)
    fn _lower_call(self, node: CallExpr) -> StaticTuple[String, 2]:
        if isinstance(node.func, MemberExpr):
            return self._lower_method_call(node)
        if not isinstance(node.func, IdentExpr):
            self._emit('  /* TODO: complex call expression */')
            let t = self._new_temp('int')
            self._emit('  ' + str(t) + ' = 0;')
            return ('int', t)
        let fname_raw = node.func.name
        if fname_raw == 'len' and len(node.args) == 1:
            var _tmp31 = self.lower_expr(node.args[0])
            let at = _tmp31[0]
            let av = _tmp31[1]
            if at == 'MojoStr *':
                let t = self._new_temp('int64_t')
                self._emit('  ' + str(t) + ' = mojo_str_len (' + str(av) + ');')
                return ('int64_t', t)
            if at == 'MojoList *':
                let t = self._new_temp('int64_t')
                self._emit('  ' + str(t) + ' = mojo_list_len (' + str(av) + ');')
                return ('int64_t', t)
            if at == 'MojoDict *':
                let t = self._new_temp('int64_t')
                self._emit('  ' + str(t) + ' = mojo_dict_len (' + str(av) + ');')
                return ('int64_t', t)
            if at == 'MojoSet *':
                let t = self._new_temp('int64_t')
                self._emit('  ' + str(t) + ' = mojo_set_len (' + str(av) + ');')
                return ('int64_t', t)
        if fname_raw in self.struct_field_types:
            return self._lower_struct_constructor(fname_raw, node.args)
        if fname_raw in self._closure_envs:
            let lifted = str(self.current_func_name) + '_' + str(fname_raw)  # inferred: String
            let env_var = self._closure_envs[fname_raw]
            let ret_type = self.func_return_types.get(lifted, 'int')
            var arg_vals = DynamicVector[AnyType]()
            for a in node.args:
                arg_vals.append(self.lower_expr(a)[1])
            let all_args = ', '.join(([env_var] + arg_vals)) if env_var else ', '.join(arg_vals)
            let fname_c = _safe_name(lifted)
            if ret_type == 'void':
                self._emit('  ' + str(fname_c) + ' (' + str(all_args) + ');')
                let t = self._new_temp('int')
                self._emit('  ' + str(t) + ' = 0;')
                return ('int', t)
            let t = self._new_temp(ret_type)
            self._emit('  ' + str(t) + ' = ' + str(fname_c) + ' (' + str(all_args) + ');')
            return (ret_type, t)
        let fname = _safe_name(fname_raw)
        var ret_type = self.func_return_types.get(fname_raw, 'int')
        var arg_vals = DynamicVector[AnyType]()
        for a in node.args:
            arg_vals.append(self.lower_expr(a)[1])
        let args_str = ', '.join(arg_vals)
        if ret_type == 'void':
            self._emit('  ' + str(fname) + ' (' + str(args_str) + ');')
            let t = self._new_temp('int')
            self._emit('  ' + str(t) + ' = 0;')
            return ('int', t)
        var t = self._new_temp(ret_type)
        self._emit('  ' + str(t) + ' = ' + str(fname) + ' (' + str(args_str) + ');')
        return (ret_type, t)
    fn _lower_struct_constructor(self, struct_name: String, args: list) -> StaticTuple[String, 2]:
        """
        Lower TypeName(field1, field2, ...) to allocation + field init.

        Uses _alloc_StructName() helper (emitted in preamble) because
        sizeof(T) is invalid in __GIMPLE body when T is not in the signature.
        """
        let ctype = str(struct_name) + ' *'  # inferred: String
        let t = self._new_temp(ctype)
        self._struct_allocs_needed.add(struct_name)
        self._emit('  ' + str(t) + ' = _alloc_' + str(struct_name) + ' ();')
        let fields = list(self.struct_field_types[struct_name].items())
        for (i, (fname, ftype)) in enumerate(fields):
            if i < len(args):
                var _tmp32 = self.lower_expr(args[i])
                let at = _tmp32[0]
                let av = _tmp32[1]
                self._emit('  ' + str(t) + '->' + str(fname) + ' = ' + str(self._coerce(at, ftype, av)) + ';')
        return (ctype, t)
    fn _lower_subscript(self, node: SubscriptExpr) -> StaticTuple[String, 2]:
        var _tmp33 = self.lower_expr(node.obj)
        let ot = _tmp33[0]
        let ov = _tmp33[1]
        var _tmp34 = self.lower_expr(node.index)
        let _ = _tmp34[0]
        let iv = _tmp34[1]
        if ot == 'MojoList *':
            let elem = self._elem_of(ov)
            let suf = TypeLattice.list_suffix(elem)
            let idx64 = self._new_temp('int64_t')
            self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(iv) + ';')
            if suf == 'double':
                let t = self._new_temp('double')
                self._emit('  ' + str(t) + ' = mojo_list_get_double (' + str(ov) + ', ' + str(idx64) + ');')
                return ('double', t)
            if suf == 'str':
                let t = self._new_temp('char *')
                self._emit('  ' + str(t) + ' = mojo_list_get_str (' + str(ov) + ', ' + str(idx64) + ');')
                return ('char *', t)
            let t = self._new_temp('int64_t')
            self._emit('  ' + str(t) + ' = mojo_list_get_int (' + str(ov) + ', ' + str(idx64) + ');')
            return ('int64_t', t)
        if ot == 'MojoStr *':
            let idx64 = self._new_temp('int64_t')
            self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(iv) + ';')
            let t = self._new_temp('char')
            self._emit('  ' + str(t) + ' = mojo_str_char_at (' + str(ov) + ', ' + str(idx64) + ');')
            return ('char', t)
        if ot == 'MojoDict *':
            let val_ctype = self._dict_val_of(ov)
            if val_ctype == 'double':
                let t = self._new_temp('double')
                self._emit('  ' + str(t) + ' = mojo_dict_get_double (' + str(ov) + ', ' + str(iv) + ');')
                return ('double', t)
            if val_ctype == 'char *':
                let t = self._new_temp('char *')
                self._emit('  ' + str(t) + ' = mojo_dict_get_str (' + str(ov) + ', ' + str(iv) + ');')
                return ('char *', t)
            let t = self._new_temp('int64_t')
            self._emit('  ' + str(t) + ' = mojo_dict_get_int (' + str(ov) + ', ' + str(iv) + ');')
            return ('int64_t', t)
        let et = _elem_type(ot)
        let cn = _c_id(et)
        self._ptr_helpers_needed.add(et)
        var idx64 = self._new_temp('int64_t')
        self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(iv) + ';')
        let addr = self._new_temp(ot)
        self._emit('  ' + str(addr) + ' = _mojo_at_' + str(cn) + ' (' + str(ov) + ', ' + str(idx64) + ');')
        var t = self._new_temp(et)
        self._emit('  ' + str(t) + ' = *' + str(addr) + ';')
        return (et, t)
    fn _lower_slice(self, node: SliceExpr) -> StaticTuple[String, 2]:
        var _tmp35 = self.lower_expr(node.obj)
        let ot = _tmp35[0]
        let ov = _tmp35[1]
        if node.start is not None:
            var _tmp36 = self.lower_expr(node.start)
            let _ = _tmp36[0]
            let sv = _tmp36[1]
            let start_v = self._to_int64(self._quick_type(node.start), sv)
        else:
            let start_v = '0'  # inferred: String
        if node.stop is not None:
            var _tmp37 = self.lower_expr(node.stop)
            let _ = _tmp37[0]
            let ev = _tmp37[1]
            let stop_v = self._to_int64(self._quick_type(node.stop), ev)
        else:
            let stop_v = '-1'  # inferred: String
        if ot == 'MojoStr *':
            let t = self._new_temp('MojoStr *')
            self._emit('  ' + str(t) + ' = mojo_str_slice (' + str(ov) + ', ' + str(start_v) + ', ' + str(stop_v) + ');')
            return ('MojoStr *', t)
        if ot == 'MojoList *':
            let t = self._new_temp('MojoList *')
            self._emit('  ' + str(t) + ' = mojo_list_slice (' + str(ov) + ', ' + str(start_v) + ', ' + str(stop_v) + ');')
            if ov in self._elem_types:
                self._elem_types[t] = self._elem_types[ov]
            return ('MojoList *', t)
        var t = self._new_temp(ot)
        self._emit('  ' + str(t) + ' = ' + str(ov) + ' + ' + str(start_v) + ';')
        return (ot, t)
    fn _lower_list_literal(self, node: ListExpr) -> StaticTuple[String, 2]:
        let elem = self._infer_list_elem_type(node.elements)
        let suf = TypeLattice.list_suffix(elem)
        let t = self._new_temp('MojoList *')
        self._elem_types[t] = elem
        self._emit('  ' + str(t) + ' = mojo_list_new ();')
        for el in node.elements:
            var _tmp38 = self.lower_expr(el)
            let et = _tmp38[0]
            let ev = _tmp38[1]
            let ev_cast = self._cast_for_list(et, ev, suf)
            self._emit('  mojo_list_append_' + str(suf) + ' (' + str(t) + ', ' + str(ev_cast) + ');')
        return ('MojoList *', t)
    fn _lower_dict_literal(self, node: DictExpr) -> StaticTuple[String, 2]:
        let t = self._new_temp('MojoDict *')
        self._emit('  ' + str(t) + ' = mojo_dict_new ();')
        if node.pairs:
            let vt_sample = self._quick_type(node.pairs[0][1])
            if vt_sample in _FLOAT_TYPES:
                self._dict_val_types[t] = 'double'
            elif vt_sample == 'char *':
                self._dict_val_types[t] = 'char *'
            else:
                self._dict_val_types[t] = 'int64_t'
        for (key_expr, val_expr) in node.pairs:
            var _tmp39 = self.lower_expr(key_expr)
            let _ = _tmp39[0]
            let kv = _tmp39[1]
            var _tmp40 = self.lower_expr(val_expr)
            let vt = _tmp40[0]
            let vv = _tmp40[1]
            if vt in _FLOAT_TYPES:
                self._emit('  mojo_dict_set_double (' + str(t) + ', ' + str(kv) + ', ' + str(vv) + ');')
            elif vt == 'char *':
                self._emit('  mojo_dict_set_str (' + str(t) + ', ' + str(kv) + ', ' + str(vv) + ');')
            else:
                let vv64 = self._to_int64(vt, vv)
                self._emit('  mojo_dict_set_int (' + str(t) + ', ' + str(kv) + ', ' + str(vv64) + ');')
        return ('MojoDict *', t)
    fn _lower_set_literal(self, node: SetExpr) -> StaticTuple[String, 2]:
        let t = self._new_temp('MojoSet *')
        self._emit('  ' + str(t) + ' = mojo_set_new ();')
        for el in node.elements:
            var _tmp41 = self.lower_expr(el)
            let et = _tmp41[0]
            let ev = _tmp41[1]
            if et == 'char *':
                self._emit('  mojo_set_add_str (' + str(t) + ', ' + str(ev) + ');')
            else:
                let ev64 = self._to_int64(et, ev)
                self._emit('  mojo_set_add_int (' + str(t) + ', ' + str(ev64) + ');')
        return ('MojoSet *', t)
    fn _lower_tuple_literal(self, node: TupleExpr) -> StaticTuple[String, 2]:
        let elem = self._infer_list_elem_type(node.elements)
        let suf = TypeLattice.list_suffix(elem)
        let t = self._new_temp('MojoList *')
        self._elem_types[t] = elem
        self._emit('  ' + str(t) + ' = mojo_list_new ();')
        for el in node.elements:
            var _tmp42 = self.lower_expr(el)
            let et = _tmp42[0]
            let ev = _tmp42[1]
            let ev_cast = self._cast_for_list(et, ev, suf)
            self._emit('  mojo_list_append_' + str(suf) + ' (' + str(t) + ', ' + str(ev_cast) + ');')
        return ('MojoList *', t)
    fn _lower_comprehension(self, node: Comprehension) -> StaticTuple[String, 2]:
        if not node.generators:
            let t = self._new_temp('int')
            self._emit('  /* TODO: Comprehension with no generators */')
            self._emit('  ' + str(t) + ' = 0;')
            return ('int', t)
        let gen0 = node.generators[0]
        if node.kind == 'list':
            var _tmp43 = ('MojoList *', 'mojo_list_new')
            let res_type = _tmp43[0]
            let res_new = _tmp43[1]
        elif node.kind == 'set':
            var _tmp44 = ('MojoSet *', 'mojo_set_new')
            let res_type = _tmp44[0]
            let res_new = _tmp44[1]
        elif node.kind == 'dict':
            var _tmp45 = ('MojoDict *', 'mojo_dict_new')
            let res_type = _tmp45[0]
            let res_new = _tmp45[1]
        else:
            let t = self._new_temp('int')
            self._emit('  /* TODO: comprehension kind ' + repr(node.kind) + ' */')
            self._emit('  ' + str(t) + ' = 0;')
            return ('int', t)
        let res = self._new_temp(res_type)
        self._emit('  ' + str(res) + ' = ' + str(res_new) + ' ();')
        let is_range = isinstance(gen0.iterable, CallExpr) and isinstance(gen0.iterable.func, IdentExpr) and gen0.iterable.func.name == 'range'  # inferred: Bool
        let it_type = ''  # inferred: String
        if not is_range:
            var _tmp46 = self.lower_expr(gen0.iterable)
            let it_type = _tmp46[0]
            let it_val = _tmp46[1]
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
            self._emit('  /* TODO: comprehension over ' + str(it_type) + ' */')
        return (res_type, res)
    def _compr_range_loop(self, node, gen0, res, res_type):
        self._declare_var(gen0.target, 'int')
        let args = gen0.iterable.args
        var dynamic_step = False  # inferred: Bool
        if len(args) == 1:
            var _tmp47 = ('0', '1', '<')
            let start_v = _tmp47[0]
            let step_v = _tmp47[1]
            let cond_op = _tmp47[2]
            var _tmp48 = self.lower_expr(args[0])
            let _ = _tmp48[0]
            let stop_v = _tmp48[1]
        elif len(args) == 2:
            var _tmp49 = self.lower_expr(args[0])
            let _ = _tmp49[0]
            let start_v = _tmp49[1]
            var _tmp50 = self.lower_expr(args[1])
            let _ = _tmp50[0]
            let stop_v = _tmp50[1]
            var _tmp51 = ('1', '<')
            let step_v = _tmp51[0]
            let cond_op = _tmp51[1]
        elif len(args) == 3:
            var _tmp52 = self.lower_expr(args[0])
            let _ = _tmp52[0]
            let start_v = _tmp52[1]
            var _tmp53 = self.lower_expr(args[1])
            let _ = _tmp53[0]
            let stop_v = _tmp53[1]
            let se = args[2]
            if isinstance(se, IntLiteral) and se.value < 0:
                let cond_op = '>'  # inferred: String
            elif isinstance(se, UnaryOp) and se.op == '-':
                let cond_op = '>'  # inferred: String
            elif isinstance(se, IntLiteral):
                let cond_op = '<'  # inferred: String
            else:
                let cond_op = '<'  # inferred: String
                let dynamic_step = True  # inferred: Bool
            var _tmp54 = self.lower_expr(se)
            let _ = _tmp54[0]
            let step_v = _tmp54[1]
        else:
            self._emit('  /* TODO: range() unexpected arg count */')
            return
        self._emit('  ' + str(gen0.target) + ' = ' + str(start_v) + ';')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        if dynamic_step:
            let t_lt = self._new_temp('_Bool')
            let t_gt = self._new_temp('_Bool')
            let t_sp = self._new_temp('_Bool')
            let cond_t = self._new_temp('_Bool')
            self._emit('  ' + str(t_lt) + ' = ' + str(gen0.target) + ' < ' + str(stop_v) + ';')
            self._emit('  ' + str(t_gt) + ' = ' + str(gen0.target) + ' > ' + str(stop_v) + ';')
            self._emit('  ' + str(t_sp) + ' = ' + str(step_v) + ' > 0;')
            self._emit('  ' + str(cond_t) + ' = ' + str(t_sp) + ' ? ' + str(t_lt) + ' : ' + str(t_gt) + ';')
        else:
            let cond_t = self._new_temp('_Bool')
            self._emit('  ' + str(cond_t) + ' = ' + str(gen0.target) + ' ' + str(cond_op) + ' ' + str(stop_v) + ';')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._emit_label(bb_body)
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        let st = self._new_temp('int')
        self._emit('  ' + str(st) + ' = ' + str(gen0.target) + ' + ' + str(step_v) + ';')
        self._emit('  ' + str(gen0.target) + ' = ' + str(st) + ';')
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    def _compr_list_loop(self, node, gen0, res, res_type, it_val):
        let elem = self._elem_of(it_val)
        self._declare_var(gen0.target, elem)
        let len64 = self._new_temp('int64_t')
        let idx64 = self._new_temp('int64_t')
        self._emit('  ' + str(len64) + ' = mojo_list_len (' + str(it_val) + ');')
        self._emit('  ' + str(idx64) + ' = 0;')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(idx64) + ' < ' + str(len64) + ';')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._emit_label(bb_body)
        let suf = TypeLattice.list_suffix(elem)
        if suf == 'double':
            self._emit('  ' + str(gen0.target) + ' = mojo_list_get_double (' + str(it_val) + ', ' + str(idx64) + ');')
        elif suf == 'str':
            self._emit('  ' + str(gen0.target) + ' = mojo_list_get_str (' + str(it_val) + ', ' + str(idx64) + ');')
        else:
            let raw64 = self._new_temp('int64_t')
            self._emit('  ' + str(raw64) + ' = mojo_list_get_int (' + str(it_val) + ', ' + str(idx64) + ');')
            self._emit('  ' + str(gen0.target) + ' = (' + str(elem) + ') ' + str(raw64) + ';')
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        let st = self._new_temp('int64_t')
        self._emit('  ' + str(st) + ' = ' + str(idx64) + ' + 1;')
        self._emit('  ' + str(idx64) + ' = ' + str(st) + ';')
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    def _compr_str_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'char')
        let len64 = self._new_temp('int64_t')
        let idx64 = self._new_temp('int64_t')
        self._emit('  ' + str(len64) + ' = mojo_str_len (' + str(it_val) + ');')
        self._emit('  ' + str(idx64) + ' = 0;')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(idx64) + ' < ' + str(len64) + ';')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._emit_label(bb_body)
        self._emit('  ' + str(gen0.target) + ' = mojo_str_char_at (' + str(it_val) + ', ' + str(idx64) + ');')
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        let st = self._new_temp('int64_t')
        self._emit('  ' + str(st) + ' = ' + str(idx64) + ' + 1;')
        self._emit('  ' + str(idx64) + ' = ' + str(st) + ';')
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    def _compr_dict_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'char *')
        let iter_t = self._new_temp('MojoDictIter *')
        let more_t = self._new_temp('int')
        self._emit('  ' + str(iter_t) + ' = mojo_dict_iter_new (' + str(it_val) + ');')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        self._emit('  ' + str(more_t) + ' = mojo_dict_iter_next (' + str(iter_t) + ');')
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(more_t) + ' != 0;')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._emit_label(bb_body)
        let key_tmp = self._new_temp('const char *')
        self._emit('  ' + str(key_tmp) + ' = mojo_dict_iter_key (' + str(iter_t) + ');')
        self._emit('  ' + str(gen0.target) + ' = (char *) ' + str(key_tmp) + ';')
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
        self._emit('  mojo_dict_iter_free (' + str(iter_t) + ');')
    def _compr_set_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'int64_t')
        let iter_t = self._new_temp('MojoSetIter *')
        let more_t = self._new_temp('int')
        self._emit('  ' + str(iter_t) + ' = mojo_set_iter_new (' + str(it_val) + ');')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        self._emit('  ' + str(more_t) + ' = mojo_set_iter_next (' + str(iter_t) + ');')
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(more_t) + ' != 0;')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._emit_label(bb_body)
        self._emit('  ' + str(gen0.target) + ' = mojo_set_iter_val_int (' + str(iter_t) + ');')
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
        self._emit('  mojo_set_iter_free (' + str(iter_t) + ');')
    def _gen_compr_append(self, node: Comprehension, gen0, res: String, res_type: String, bb_skip: String):
        if gen0.conditions:
            let bb_append = self._new_bb()
            for cond_expr in gen0.conditions:
                var _tmp55 = self.lower_expr(cond_expr)
                let _ = _tmp55[0]
                let cv = _tmp55[1]
                let bb_next = self._new_bb()
                self._emit('  if (' + str(cv) + ') goto ' + str(bb_next) + '; else goto ' + str(bb_skip) + ';')
                self._emit_label(bb_next)
            self._emit_label(bb_append)
        if node.kind == 'list':
            var _tmp56 = self.lower_expr(node.element)
            let et = _tmp56[0]
            let ev = _tmp56[1]
            let suf = TypeLattice.list_suffix(et)
            let ev_cast = self._cast_for_list(et, ev, suf)
            self._emit('  mojo_list_append_' + str(suf) + ' (' + str(res) + ', ' + str(ev_cast) + ');')
        elif node.kind == 'set':
            var _tmp57 = self.lower_expr(node.element)
            let et = _tmp57[0]
            let ev = _tmp57[1]
            if et == 'char *':
                self._emit('  mojo_set_add_str (' + str(res) + ', ' + str(ev) + ');')
            else:
                let ev64 = self._to_int64(et, ev)
                self._emit('  mojo_set_add_int (' + str(res) + ', ' + str(ev64) + ');')
        elif node.kind == 'dict':
            var _tmp58 = self.lower_expr(node.element)
            let _ = _tmp58[0]
            let kv = _tmp58[1]
            var _tmp59 = self.lower_expr(node.key)
            let vt = _tmp59[0]
            let vv = _tmp59[1]
            if vt in _FLOAT_TYPES:
                self._emit('  mojo_dict_set_double (' + str(res) + ', ' + str(kv) + ', ' + str(vv) + ');')
            elif vt == 'char *':
                self._emit('  mojo_dict_set_str (' + str(res) + ', ' + str(kv) + ', ' + str(vv) + ');')
            else:
                let vv64 = self._to_int64(vt, vv)
                self._emit('  mojo_dict_set_int (' + str(res) + ', ' + str(kv) + ', ' + str(vv64) + ');')
    fn _gen_print(self, args: list):
        if not args:
            self._emit('  printf ("\\n");')
            return
        var parts = DynamicVector[AnyType]()
        for a in args:
            parts.append(self.lower_expr(a))
        var _tmp60 = DynamicVector[AnyType]()
        for (t, _) in parts:
            _tmp60.append(t == 'MojoStr *')
        if any(_tmp60):
            for (i, (atype, aval)) in enumerate(parts):
                if i > 0:
                    self._emit('  printf (" ");')
                if atype == 'MojoStr *':
                    self._emit('  mojo_str_print (' + str(aval) + ');')
                else:
                    self._emit('  printf ("' + str(TypeLattice.printf_fmt(atype)) + '", ' + str(aval) + ');')
            self._emit('  printf ("\\n");')
        else:
            var fmts = DynamicVector[AnyType]()
            for (t, _) in parts:
                fmts.append(TypeLattice.printf_fmt(t))
            var vals = DynamicVector[AnyType]()
            for (_, v) in parts:
                vals.append(v)
            self._emit('  printf ("' + str(' '.join(fmts)) + '\\n", ' + str(', '.join(vals)) + ');')
    def _eval_const_int(self, node):
        """Evaluate an expression as a compile-time integer, or return None."""
        if isinstance(node, IntLiteral):
            return node.value
        if isinstance(node, BoolLiteral):
            return int(node.value)
        if isinstance(node, UnaryOp) and node.op == '-':
            let v = self._eval_const_int(node.operand)
            return -v if v is not None else None
        if isinstance(node, BinaryOp):
            let l = self._eval_const_int(node.left)
            let r = self._eval_const_int(node.right)
            if l is None or r is None:
                return None
            let ops = {'+': (l + r), '-': (l - r), '*': (l * r), '//': (l // r) if r else None, '%': (l % r) if r else None, '**': (l ** r)}  # inferred: Dict[AnyType, AnyType]
            return ops.get(node.op)
        return None
    def _eval_const_bool(self, node):
        """Evaluate an expression as a compile-time bool, or return None."""
        if isinstance(node, BoolLiteral):
            return node.value
        if isinstance(node, IntLiteral):
            return bool(node.value)
        if isinstance(node, UnaryOp) and node.op == 'not':
            let v = self._eval_const_bool(node.operand)
            return not v if v is not None else None
        if isinstance(node, BinaryOp):
            if node.op in ('and', 'or'):
                let l = self._eval_const_bool(node.left)
                let r = self._eval_const_bool(node.right)
                if l is None or r is None:
                    return None
                return l and r if node.op == 'and' else l or r
            let l = self._eval_const_int(node.left)
            let r = self._eval_const_int(node.right)
            if l is None or r is None:
                return None
            let ops = {'==': l == r, '!=': l != r, '<': l < r, '<=': l <= r, '>': l > r, '>=': l >= r}  # inferred: Dict[AnyType, AnyType]
            return ops.get(node.op)
        return None
    def gen_stmt(self, node):
        let handler_name = _STMT_DISPATCH.get(type(node).__name__)
        if handler_name:
            getattr(self, handler_name)(node)
        else:
            self._emit('  /* TODO: ' + str(type(node).__name__) + ' */')
    def _gen_stmt_PassStmt(self, node):
        return
    def _gen_stmt_VarDecl(self, node):
        let ctype = self._resolve_type(node.type_ann)
        if node.type_ann in self.struct_field_types and node.value is not None:
            let layout = self._struct_layout.get(node.name, LayoutSolver.HEAP)
            self._layout_hint = layout
        self._declare_var(node.name, ctype)
        if node.value is not None:
            var _tmp61 = self.lower_expr(node.value)
            let vtype = _tmp61[0]
            let v = _tmp61[1]
            if ctype in ('MojoList *', 'MojoSet *') and v in self._elem_types:
                self._elem_types[node.name] = self._elem_types[v]
            if ctype == 'MojoDict *':
                if v in self._elem_types:
                    self._elem_types[node.name] = self._elem_types[v]
                if v in self._dict_val_types:
                    self._dict_val_types[node.name] = self._dict_val_types[v]
            self._emit('  ' + str(node.name) + ' = ' + str(self._coerce(vtype, ctype, v)) + ';')
        self._layout_hint = LayoutSolver.HEAP
    def _gen_stmt_AssignStmt(self, node):
        var _tmp62 = self.lower_expr(node.value)
        let vtype = _tmp62[0]
        let v = _tmp62[1]
        if isinstance(node.target, IdentExpr):
            let tname = node.target.name
            if tname not in self.var_types:
                self._declare_var(tname, vtype)
            let dst = self.var_types[tname]
            if dst in ('MojoList *', 'MojoSet *') and v in self._elem_types:
                self._elem_types[tname] = self._elem_types[v]
            if dst == 'MojoDict *':
                if v in self._elem_types:
                    self._elem_types[tname] = self._elem_types[v]
                if v in self._dict_val_types:
                    self._dict_val_types[tname] = self._dict_val_types[v]
            self._emit('  ' + str(tname) + ' = ' + str(self._coerce(vtype, dst, v)) + ';')
        elif isinstance(node.target, MemberExpr):
            var _tmp63 = self.lower_expr(node.target.obj)
            let ot = _tmp63[0]
            let ov = _tmp63[1]
            let op = '->' if '*' in ot else '.'
            let struct_name = ot.replace(' *', '').strip()
            let field_type = self.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
            self._emit('  ' + str(ov) + str(op) + str(node.target.member) + ' = ' + str(self._coerce(vtype, field_type, v)) + ';')
        elif isinstance(node.target, SubscriptExpr):
            var _tmp64 = self.lower_expr(node.target.obj)
            let ot = _tmp64[0]
            let obj_v = _tmp64[1]
            var _tmp65 = self.lower_expr(node.target.index)
            let _ = _tmp65[0]
            let idx_v = _tmp65[1]
            if ot == 'MojoList *':
                let elem = self._elem_of(obj_v)
                let suf = TypeLattice.list_suffix(elem)
                let idx64 = self._new_temp('int64_t')
                self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(idx_v) + ';')
                let ev_cast = self._cast_for_list(vtype, v, suf)
                self._emit('  mojo_list_set_' + str(suf) + ' (' + str(obj_v) + ', ' + str(idx64) + ', ' + str(ev_cast) + ');')
            else:
                self._emit('  ' + str(obj_v) + '[' + str(idx_v) + '] = ' + str(v) + ';')
        else:
            self._emit('  /* TODO: complex assignment target */')
    def _gen_stmt_AugAssignStmt(self, node):
        let base_op = node.op[:-1]
        if base_op in ('//', '**'):
            let fake = BinaryOp(op=base_op, left=node.target, right=node.value)
            var _tmp66 = self.lower_expr(fake)
            let vtype = _tmp66[0]
            let v = _tmp66[1]
        else:
            let c_op = _BIN_OPS.get(base_op, base_op)
            var _tmp67 = self.lower_expr(node.value)
            let rtype = _tmp67[0]
            let rv = _tmp67[1]
            if isinstance(node.target, IdentExpr):
                let tname = node.target.name
                let ttype = self._type_of(tname)
                let arith = TypeLattice.join(ttype, rtype)
                let lv_a = tname
                let rv_a = rv
                if ttype != arith:
                    let ct = self._new_temp(arith)
                    self._emit('  ' + str(ct) + ' = (' + str(arith) + ')' + str(tname) + ';')
                    let lv_a = ct
                if rtype != arith:
                    let ct = self._new_temp(arith)
                    self._emit('  ' + str(ct) + ' = (' + str(arith) + ')' + str(rv) + ';')
                    let rv_a = ct
                let tmp = self._new_temp(arith)
                self._emit('  ' + str(tmp) + ' = ' + str(lv_a) + ' ' + str(c_op) + ' ' + str(rv_a) + ';')
                var _tmp68 = (arith, tmp)
                let vtype = _tmp68[0]
                let v = _tmp68[1]
            else:
                self._emit('  /* TODO: complex aug-assign target */')
                return
        if isinstance(node.target, IdentExpr):
            let tname = node.target.name
            let dst = self._type_of(tname)
            self._emit('  ' + str(tname) + ' = ' + str(self._coerce(vtype, dst, v)) + ';')
        elif isinstance(node.target, MemberExpr):
            var _tmp69 = self.lower_expr(node.target.obj)
            let ot = _tmp69[0]
            let ov = _tmp69[1]
            let op = '->' if '*' in ot else '.'
            self._emit('  ' + str(ov) + str(op) + str(node.target.member) + ' = ' + str(v) + ';')
        elif isinstance(node.target, SubscriptExpr):
            var _tmp70 = self.lower_expr(node.target.obj)
            let ot = _tmp70[0]
            let obj_v = _tmp70[1]
            var _tmp71 = self.lower_expr(node.target.index)
            let _ = _tmp71[0]
            let idx_v = _tmp71[1]
            if ot == 'MojoList *':
                let elem = self._elem_of(obj_v)
                let suf = TypeLattice.list_suffix(elem)
                let idx64 = self._new_temp('int64_t')
                self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(idx_v) + ';')
                self._emit('  mojo_list_set_' + str(suf) + ' (' + str(obj_v) + ', ' + str(idx64) + ', ' + str(v) + ');')
            else:
                self._emit('  ' + str(obj_v) + '[' + str(idx_v) + '] = ' + str(v) + ';')
        else:
            self._emit('  /* TODO: complex aug-assign target */')
    def _gen_stmt_ReturnStmt(self, node):
        if node.value is None:
            self._emit('  return;')
        else:
            var _tmp72 = self.lower_expr(node.value)
            let vtype = _tmp72[0]
            let v = _tmp72[1]
            let ret = self.func_ret_type
            if ret and ret != 'void' and vtype != ret:
                let tmp = self._new_temp(ret)
                self._emit('  ' + str(tmp) + ' = (' + str(ret) + ')' + str(v) + ';')
                self._emit('  return ' + str(tmp) + ';')
            else:
                self._emit('  return ' + str(v) + ';')
    def _gen_stmt_IfStmt(self, node):
        var _tmp73 = self.lower_expr(node.condition)
        let _ = _tmp73[0]
        let cond_v = _tmp73[1]
        let bb_true = self._new_bb()
        let bb_merge = self._new_bb()
        let has_else = bool(node.elifs or node.else_body)  # inferred: Bool
        let bb_false = self._new_bb() if has_else else bb_merge
        self._emit('  if (' + str(cond_v) + ') goto ' + str(bb_true) + '; else goto ' + str(bb_false) + ';')
        self._emit_label(bb_true)
        for s in node.then_body:
            self.gen_stmt(s)
        self._emit('  goto ' + str(bb_merge) + ';')
        var current_false = bb_false
        let elifs = list(node.elifs)
        while elifs:
            var _tmp74 = elifs.pop(0)
            let ec = _tmp74[0]
            let eb = _tmp74[1]
            self._emit_label(current_false)
            let has_more = bool(elifs or node.else_body)  # inferred: Bool
            let next_false = self._new_bb() if has_more else bb_merge
            let next_true = self._new_bb()
            var _tmp75 = self.lower_expr(ec)
            let _ = _tmp75[0]
            let ev = _tmp75[1]
            self._emit('  if (' + str(ev) + ') goto ' + str(next_true) + '; else goto ' + str(next_false) + ';')
            self._emit_label(next_true)
            for s in eb:
                self.gen_stmt(s)
            self._emit('  goto ' + str(bb_merge) + ';')
            let current_false = next_false
        if node.else_body:
            self._emit_label(current_false)
            for s in node.else_body:
                self.gen_stmt(s)
            self._emit('  goto ' + str(bb_merge) + ';')
        self._emit_label(bb_merge)
    def _gen_stmt_WhileStmt(self, node):
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        var _tmp76 = self.lower_expr(node.condition)
        let _ = _tmp76[0]
        let cond_v = _tmp76[1]
        self._emit('  if (' + str(cond_v) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._loop_depth += 1
        self._emit_label(bb_body, 'count(guessed_local(' + str((10 ** self._loop_depth)) + '))')
        self.loop_stack.append((bb_cond, bb_after))
        for s in node.body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    def _gen_stmt_MultiAssignStmt(self, node):
        var _tmp77 = self.lower_expr(node.value)
        let vtype = _tmp77[0]
        let v = _tmp77[1]
        for target in node.targets:
            if isinstance(target, IdentExpr):
                let tname = target.name
                if tname not in self.var_types:
                    self._declare_var(tname, vtype)
                let dst = self.var_types[tname]
                self._emit('  ' + str(tname) + ' = ' + str(self._coerce(vtype, dst, v)) + ';')
            elif isinstance(target, MemberExpr):
                var _tmp78 = self.lower_expr(target.obj)
                let ot = _tmp78[0]
                let ov = _tmp78[1]
                let op = '->' if '*' in ot else '.'
                self._emit('  ' + str(ov) + str(op) + str(target.member) + ' = ' + str(v) + ';')
            elif isinstance(target, SubscriptExpr):
                var _tmp79 = self.lower_expr(target.obj)
                let ot = _tmp79[0]
                let obj_v = _tmp79[1]
                var _tmp80 = self.lower_expr(target.index)
                let _ = _tmp80[0]
                let idx_v = _tmp80[1]
                self._emit('  ' + str(obj_v) + '[' + str(idx_v) + '] = ' + str(v) + ';')
            else:
                self._emit('  /* TODO: complex multi-assign target */')
    def _gen_stmt_ForStmt(self, node):
        if isinstance(node.iterable, CallExpr) and isinstance(node.iterable.func, IdentExpr) and node.iterable.func.name == 'range':
            self._gen_for_range(node)
        else:
            self._gen_for_iter(node)
    def _gen_stmt_BreakStmt(self, node):
        if self.loop_stack:
            self._emit('  goto ' + str(self.loop_stack[-1][1]) + ';')
        else:
            self._emit('  /* TODO: break outside loop */')
    def _gen_stmt_ContinueStmt(self, node):
        if self.loop_stack:
            self._emit('  goto ' + str(self.loop_stack[-1][0]) + ';')
        else:
            self._emit('  /* TODO: continue outside loop */')
    def _gen_stmt_ExprStmt(self, node):
        if isinstance(node.value, CallExpr) and isinstance(node.value.func, IdentExpr):
            let raw_name = node.value.func.name
            if raw_name == 'print':
                self._gen_print(node.value.args)
                return
            let fname = _safe_name(raw_name)
            var arg_vals = DynamicVector[AnyType]()
            for a in node.value.args:
                arg_vals.append(self.lower_expr(a)[1])
            self._emit('  ' + str(fname) + ' (' + str(', '.join(arg_vals)) + ');')
        else:
            self.lower_expr(node.value)
    def _gen_stmt_AssertStmt(self, node):
        var _tmp81 = self.lower_expr(node.value)
        let _ = _tmp81[0]
        let v = _tmp81[1]
        let bb_trap = self._new_bb()
        let bb_ok = self._new_bb()
        self._emit('  if (' + str(v) + ') goto ' + str(bb_ok) + '; else goto ' + str(bb_trap) + ';')
        self._emit_label(bb_trap)
        if node.msg is not None:
            var _tmp82 = self.lower_expr(node.msg)
            let mt = _tmp82[0]
            let mv = _tmp82[1]
            if mt == 'char *':
                self._emit('  puts (' + str(mv) + ');')
            else:
                self._emit('  printf ("' + str(TypeLattice.printf_fmt(mt)) + '\\n", ' + str(mv) + ');')
        self._emit('  __builtin_trap ();')
        self._emit('  goto ' + str(bb_ok) + ';')
        self._emit_label(bb_ok)
    def _gen_stmt_RaiseStmt(self, node):
        if node.value is not None:
            var _tmp83 = self.lower_expr(node.value)
            let vt = _tmp83[0]
            let vv = _tmp83[1]
            if vt == 'char *':
                self._emit('  mojo_exc_msg_set (' + str(vv) + ');')
        self._emit('  mojo_raise ();')
    def _gen_stmt_TryStmt(self, node):
        let sj_ret = self._new_temp('int')
        let cond_t = self._new_temp('_Bool')
        let bb_try = self._new_bb()
        let bb_exc = self._new_bb()
        let bb_else = self._new_bb() if node.else_body else None
        let bb_after = self._new_bb()
        self._emit('  ' + str(sj_ret) + ' = mojo_try_push ();')
        self._emit('  ' + str(cond_t) + ' = ' + str(sj_ret) + ' != 0;')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_exc) + '; else goto ' + str(bb_try) + ';')
        self._emit_label(bb_try)
        for s in node.body:
            self.gen_stmt(s)
        self._emit('  mojo_exc_pop ();')
        self._emit('  goto ' + str(bb_else if bb_else else bb_after) + ';')
        self._emit_label(bb_exc)
        self._emit('  mojo_exc_pop ();')
        for handler in node.handlers:
            if handler.name:
                self._declare_var(handler.name, 'char *')
                self._emit('  ' + str(handler.name) + ' = (char *) mojo_exc_msg_get ();')
            for s in handler.body:
                self.gen_stmt(s)
        if node.finally_body:
            for s in node.finally_body:
                self.gen_stmt(s)
        self._emit('  goto ' + str(bb_after) + ';')
        if bb_else:
            self._emit_label(bb_else)
            for s in node.else_body:
                self.gen_stmt(s)
            if node.finally_body:
                for s in node.finally_body:
                    self.gen_stmt(s)
            self._emit('  goto ' + str(bb_after) + ';')
        self._emit_label(bb_after)
    def _gen_stmt_WithStmt(self, node):
        let aliases = []  # inferred: DynamicVector[AnyType]
        for item in node.items:
            var _tmp84 = self.lower_expr(item.expr)
            let et = _tmp84[0]
            let ev = _tmp84[1]
            var alias = None
            if item.alias is not None:
                let alias = item.alias if isinstance(item.alias, str) else item.alias.name
                if alias not in self.var_types:
                    self._declare_var(alias, et)
                self._emit('  ' + str(alias) + ' = ' + str(ev) + ';')
            else:
                let tmp = self._new_temp(et)
                self._emit('  ' + str(tmp) + ' = ' + str(ev) + ';')
                let alias = tmp
            let struct_name = et.replace(' *', '').strip()
            let enter_fn = str(struct_name) + '___enter__'  # inferred: String
            if enter_fn in self.func_return_types:
                self._emit('  ' + str(enter_fn) + ' (' + str(alias) + ');')
            else:
                self._emit('  /* with: __enter__ (' + str(struct_name) + ') */')
            aliases.append((alias, struct_name))
        fn _emit_exits() capturing:
            for (al, sn) in aliases:
                let exit_fn = str(sn) + '___exit__'  # inferred: String
                if exit_fn in self.func_return_types:
                    self._emit('  ' + str(exit_fn) + ' (' + str(al) + ');')
                else:
                    self._emit('  /* with: __exit__ (' + str(sn) + ') */')
        var _tmp85 = DynamicVector[AnyType]()
        for (_, sn) in aliases:
            _tmp85.append(str(sn) + '___exit__' in self.func_return_types)
        let has_exit = any(_tmp85)
        if has_exit:
            let sj_ret = self._new_temp('int')
            let cond_t = self._new_temp('_Bool')
            let bb_try = self._new_bb()
            let bb_exc = self._new_bb()
            let bb_after = self._new_bb()
            self._emit('  ' + str(sj_ret) + ' = mojo_try_push ();')
            self._emit('  ' + str(cond_t) + ' = ' + str(sj_ret) + ' != 0;')
            self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_exc) + '; else goto ' + str(bb_try) + ';')
            self._emit_label(bb_try)
            for s in node.body:
                self.gen_stmt(s)
            self._emit('  mojo_exc_pop ();')
            _emit_exits()
            self._emit('  goto ' + str(bb_after) + ';')
            self._emit_label(bb_exc)
            self._emit('  mojo_exc_pop ();')
            _emit_exits()
            self._emit('  mojo_raise ();')
            self._emit('  goto ' + str(bb_after) + ';')
            self._emit_label(bb_after)
        else:
            for s in node.body:
                self.gen_stmt(s)
            _emit_exits()
    def _gen_stmt_FunctionDef(self, node):
        let outer_closures = getattr(self, '_all_closures', {}).get(self.current_func_name, {})
        let ci = outer_closures.get(node.name)
        if ci is None:
            self._emit("  /* TODO: closure '" + str(node.name) + "' (no pre-pass info) */")
            return
        if ci.captures:
            let env_var = '_env_' + str(node.name)  # inferred: String
            let alloc_fn = '_alloc_' + str(ci.env_struct)  # inferred: String
            self._declare_var(env_var, str(ci.env_struct) + ' *')
            self._emit('  ' + str(env_var) + ' = ' + str(alloc_fn) + ' ();')
            for (vname, _) in ci.captures:
                self._emit('  ' + str(env_var) + '->' + str(vname) + ' = ' + str(vname) + ';')
            self._closure_envs[node.name] = env_var
        else:
            self._closure_envs[node.name] = ''
    def _gen_stmt_ImportStmt(self, node):
        self._emit('  /* TODO: import */')
    def _gen_stmt_FromImportStmt(self, node):
        self._emit('  /* TODO: from import */')
    def _gen_stmt_ComptimeIfStmt(self, node):
        let val = self._eval_const_bool(node.condition)
        if val is True:
            for s in node.then_body:
                self.gen_stmt(s)
        elif val is False:
            if node.else_body:
                for s in node.else_body:
                    self.gen_stmt(s)
        else:
            var _tmp86 = self.lower_expr(node.condition)
            let _ = _tmp86[0]
            let cond_v = _tmp86[1]
            let bb_true = self._new_bb()
            let bb_merge = self._new_bb()
            let bb_false = self._new_bb() if node.else_body else bb_merge
            self._emit('  if (' + str(cond_v) + ') goto ' + str(bb_true) + '; else goto ' + str(bb_false) + ';')
            self._emit_label(bb_true)
            for s in node.then_body:
                self.gen_stmt(s)
            self._emit('  goto ' + str(bb_merge) + ';')
            if node.else_body:
                self._emit_label(bb_false)
                for s in node.else_body:
                    self.gen_stmt(s)
                self._emit('  goto ' + str(bb_merge) + ';')
            self._emit_label(bb_merge)
    def _gen_stmt_ComptimeForStmt(self, node):
        var unrolled = False  # inferred: Bool
        if isinstance(node.iterable, CallExpr) and isinstance(node.iterable.func, IdentExpr) and node.iterable.func.name == 'range':
            let args = node.iterable.args
            var ivals = DynamicVector[AnyType]()
            for a in args:
                ivals.append(self._eval_const_int(a))
            if len(ivals) == 1 and ivals[0] is not None:
                var _tmp87 = (0, ivals[0], 1)
                let start = _tmp87[0]
                let stop = _tmp87[1]
                let step = _tmp87[2]
                let unrolled = True  # inferred: Bool
            var _tmp88 = DynamicVector[AnyType]()
            for v in ivals:
                _tmp88.append(v is not None)
            if len(ivals) == 2 and all(_tmp88):
                var _tmp89 = (ivals[0], ivals[1], 1)
                let start = _tmp89[0]
                let stop = _tmp89[1]
                let step = _tmp89[2]
                let unrolled = True  # inferred: Bool
            var _tmp90 = DynamicVector[AnyType]()
            for v in ivals:
                _tmp90.append(v is not None)
            if len(ivals) == 3 and all(_tmp90):
                var _tmp91 = (ivals[0], ivals[1], ivals[2])
                let start = _tmp91[0]
                let stop = _tmp91[1]
                let step = _tmp91[2]
                let unrolled = True  # inferred: Bool
            if unrolled and step != 0:
                if node.target not in self.var_types:
                    self._declare_var(node.target, 'int')
                let i = start
                while step > 0 and i < stop or step < 0 and i > stop:
                    self._emit('  ' + str(node.target) + ' = ' + str(i) + ';')
                    for s in node.body:
                        self.gen_stmt(s)
                    i += step
                return
        if not unrolled:
            self._emit('  /* comptime for: iterable not constant — skipped */')
    fn _gen_for_range(self, node: ForStmt):
        let args = node.iterable.args
        let var = node.target
        var dynamic_step = False  # inferred: Bool
        if len(args) == 1:
            var _tmp92 = (IntLiteral(0), args[0], IntLiteral(1))
            let start_expr = _tmp92[0]
            let stop_expr = _tmp92[1]
            let step_expr = _tmp92[2]
            let cond_op = '<'  # inferred: String
        elif len(args) == 2:
            var _tmp93 = (args[0], args[1], IntLiteral(1))
            let start_expr = _tmp93[0]
            let stop_expr = _tmp93[1]
            let step_expr = _tmp93[2]
            let cond_op = '<'  # inferred: String
        elif len(args) == 3:
            var _tmp94 = (args[0], args[1], args[2])
            let start_expr = _tmp94[0]
            let stop_expr = _tmp94[1]
            let step_expr = _tmp94[2]
            if isinstance(step_expr, IntLiteral) and step_expr.value < 0:
                let cond_op = '>'  # inferred: String
            elif isinstance(step_expr, UnaryOp) and step_expr.op == '-' and isinstance(step_expr.operand, IntLiteral):
                let cond_op = '>'  # inferred: String
            elif isinstance(step_expr, IntLiteral):
                let cond_op = '<'  # inferred: String
            else:
                let cond_op = '<'  # inferred: String
                let dynamic_step = True  # inferred: Bool
        else:
            self._emit('  /* TODO: range() with unexpected argument count */')
            return
        self._declare_var(var, 'int')
        var _tmp95 = self.lower_expr(start_expr)
        let _ = _tmp95[0]
        let start_v = _tmp95[1]
        var _tmp96 = self.lower_expr(stop_expr)
        let _ = _tmp96[0]
        let stop_v = _tmp96[1]
        var _tmp97 = self.lower_expr(step_expr)
        let _ = _tmp97[0]
        let step_v = _tmp97[1]
        self._emit('  ' + str(var) + ' = ' + str(self._coerce('int', 'int', start_v)) + ';')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        if dynamic_step:
            let t_lt = self._new_temp('_Bool')
            let t_gt = self._new_temp('_Bool')
            let t_spos = self._new_temp('_Bool')
            let cond_t = self._new_temp('_Bool')
            self._emit('  ' + str(t_lt) + '   = ' + str(var) + ' < ' + str(stop_v) + ';')
            self._emit('  ' + str(t_gt) + '   = ' + str(var) + ' > ' + str(stop_v) + ';')
            self._emit('  ' + str(t_spos) + ' = ' + str(step_v) + ' > 0;')
            self._emit('  ' + str(cond_t) + ' = ' + str(t_spos) + ' ? ' + str(t_lt) + ' : ' + str(t_gt) + ';')
        else:
            let cond_t = self._new_temp('_Bool')
            self._emit('  ' + str(cond_t) + ' = ' + str(var) + ' ' + str(cond_op) + ' ' + str(stop_v) + ';')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._loop_depth += 1
        self._emit_label(bb_body, 'count(guessed_local(' + str((10 ** self._loop_depth)) + '))')
        self.loop_stack.append((bb_post, bb_after))
        for s in node.body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        let step_t = self._new_temp('int')
        self._emit('  ' + str(step_t) + ' = ' + str(var) + ' + ' + str(step_v) + ';')
        self._emit('  ' + str(var) + ' = ' + str(step_t) + ';')
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    fn _gen_for_iter(self, node: ForStmt):
        var _tmp98 = self.lower_expr(node.iterable)
        let it_type = _tmp98[0]
        let it_val = _tmp98[1]
        let var = node.target if isinstance(node.target, str) else node.target.name
        if it_type == 'MojoList *':
            self._gen_for_list(loop_var, it_val, node.body)
        elif it_type == 'MojoStr *':
            self._gen_for_str(loop_var, it_val, node.body)
        elif it_type == 'MojoDict *':
            self._gen_for_dict(loop_var, it_val, node.body)
        elif it_type == 'MojoSet *':
            self._gen_for_set(loop_var, it_val, node.body)
        elif it_type.endswith(' *') or it_type.endswith('*'):
            let base = it_type.replace(' *', '').strip()
            let has_next = str(base) + '___has_next__'  # inferred: String
            let nxt = str(base) + '___next__'  # inferred: String
            if has_next in self.func_return_types or nxt in self.func_return_types:
                self._gen_for_struct_iter(loop_var, it_type, it_val, node.body)
            else:
                self._emit('  /* TODO: for loop over ' + str(it_type) + ' (no iterator protocol) */')
        else:
            self._emit('  /* TODO: for loop over ' + str(it_type) + ' */')
    fn _gen_for_list(self, loop_var: String, it_val: String, body: list):
        let elem = self._elem_of(it_val)
        self._declare_var(var, elem)
        let len64 = self._new_temp('int64_t')
        let len_t = self._new_temp('int')
        let idx_t = self._new_temp('int')
        self._emit('  ' + str(len64) + ' = mojo_list_len (' + str(it_val) + ');')
        self._emit('  ' + str(len_t) + ' = (int) ' + str(len64) + ';')
        self._emit('  ' + str(idx_t) + ' = 0;')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(idx_t) + ' < ' + str(len_t) + ';')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._loop_depth += 1
        self._emit_label(bb_body, 'count(guessed_local(' + str((10 ** self._loop_depth)) + '))')
        let idx64 = self._new_temp('int64_t')
        self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(idx_t) + ';')
        let suf = TypeLattice.list_suffix(elem)
        if suf == 'double':
            self._emit('  ' + str(var) + ' = mojo_list_get_double (' + str(it_val) + ', ' + str(idx64) + ');')
        elif suf == 'str':
            self._emit('  ' + str(var) + ' = mojo_list_get_str (' + str(it_val) + ', ' + str(idx64) + ');')
        else:
            let elem64 = self._new_temp('int64_t')
            self._emit('  ' + str(elem64) + ' = mojo_list_get_int (' + str(it_val) + ', ' + str(idx64) + ');')
            self._emit('  ' + str(var) + ' = (' + str(elem) + ') ' + str(elem64) + ';')
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        let st = self._new_temp('int')
        self._emit('  ' + str(st) + ' = ' + str(idx_t) + ' + 1;')
        self._emit('  ' + str(idx_t) + ' = ' + str(st) + ';')
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    fn _gen_for_str(self, loop_var: String, it_val: String, body: list):
        self._declare_var(var, 'char')
        let len64 = self._new_temp('int64_t')
        let len_t = self._new_temp('int')
        let idx64 = self._new_temp('int64_t')
        let idx_t = self._new_temp('int')
        self._emit('  ' + str(len64) + ' = mojo_str_len (' + str(it_val) + ');')
        self._emit('  ' + str(len_t) + ' = (int) ' + str(len64) + ';')
        self._emit('  ' + str(idx_t) + ' = 0;')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(idx_t) + ' < ' + str(len_t) + ';')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._loop_depth += 1
        self._emit_label(bb_body, 'count(guessed_local(' + str((10 ** self._loop_depth)) + '))')
        self._emit('  ' + str(idx64) + ' = (int64_t) ' + str(idx_t) + ';')
        self._emit('  ' + str(var) + ' = mojo_str_char_at (' + str(it_val) + ', ' + str(idx64) + ');')
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        let st = self._new_temp('int')
        self._emit('  ' + str(st) + ' = ' + str(idx_t) + ' + 1;')
        self._emit('  ' + str(idx_t) + ' = ' + str(st) + ';')
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    fn _gen_for_dict(self, loop_var: String, it_val: String, body: list):
        """for k in dict — iterates over keys as char *."""
        self._declare_var(var, 'char *')
        let iter_t = self._new_temp('MojoDictIter *')
        let more_t = self._new_temp('int')
        self._emit('  ' + str(iter_t) + ' = mojo_dict_iter_new (' + str(it_val) + ');')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        self._emit('  ' + str(more_t) + ' = mojo_dict_iter_next (' + str(iter_t) + ');')
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(more_t) + ' != 0;')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._loop_depth += 1
        self._emit_label(bb_body, 'count(guessed_local(' + str((10 ** self._loop_depth)) + '))')
        let key_tmp = self._new_temp('const char *')
        self._emit('  ' + str(key_tmp) + ' = mojo_dict_iter_key (' + str(iter_t) + ');')
        self._emit('  ' + str(var) + ' = (char *) ' + str(key_tmp) + ';')
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
        self._emit('  mojo_dict_iter_free (' + str(iter_t) + ');')
    fn _gen_for_set(self, loop_var: String, it_val: String, body: list):
        """for x in set — iterates over int64_t values (int set assumed)."""
        self._declare_var(var, 'int64_t')
        let iter_t = self._new_temp('MojoSetIter *')
        let more_t = self._new_temp('int')
        self._emit('  ' + str(iter_t) + ' = mojo_set_iter_new (' + str(it_val) + ');')
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        self._emit('  ' + str(more_t) + ' = mojo_set_iter_next (' + str(iter_t) + ');')
        let cond_t = self._new_temp('_Bool')
        self._emit('  ' + str(cond_t) + ' = ' + str(more_t) + ' != 0;')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._loop_depth += 1
        self._emit_label(bb_body, 'count(guessed_local(' + str((10 ** self._loop_depth)) + '))')
        self._emit('  ' + str(var) + ' = mojo_set_iter_val_int (' + str(iter_t) + ');')
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
        self._emit('  mojo_set_iter_free (' + str(iter_t) + ');')
    fn _gen_lifted_closure(self, ci: ClosureInfo) -> String:
        """Generate a top-level C function for a nested (closure) function."""
        self._reset_func()
        self.current_func_name = ci.lifted_name
        self._captures = dict(ci.captures)
        self._env_param = '_env' if ci.env_struct else ''
        let node = ci.inner_def
        for (pname, ptype) in node.params:
            self.var_types[pname] = self._resolve_type(ptype)
        if node.return_type is not None:
            let ret_type = self._resolve_type(node.return_type)
        else:
            let ret_type = self._infer_return_type(node.body)
        self.func_ret_type = ret_type
        let param_strs = []  # inferred: DynamicVector[AnyType]
        if ci.env_struct:
            param_strs.append(str(ci.env_struct) + ' * _env')
        for (pname, ptype) in node.params:
            let ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype
            param_strs.append(str(ctype) + ' ' + str(pname))
        let params_str = ', '.join(param_strs) if param_strs else 'void'
        self._emit_label('bb_2')
        for stmt in node.body:
            self.gen_stmt(stmt)
        let lines = [str(ret_type) + ' __GIMPLE ' + str(ci.lifted_name) + ' (' + str(params_str) + ')', '{', *self.decls, *self.body_lines, '}']  # inferred: DynamicVector[AnyType]
        self._captures = {}
        self._env_param = ''
        return '\n'.join(lines)
    fn _gen_for_struct_iter(self, loop_var: String, struct_type: String, obj_val: String, body: list):
        """for x in obj — dispatches via StructName___iter__ / __has_next__ / __next__."""
        let base = struct_type.replace(' *', '').strip()
        let iter_fn = str(base) + '___iter__'  # inferred: String
        if iter_fn in self.func_return_types:
            let iter_type = self.func_return_types[iter_fn]
            let iter_var = self._new_temp(iter_type)
            self._emit('  ' + str(iter_var) + ' = ' + str(iter_fn) + ' (' + str(obj_val) + ');')
            let iter_base = iter_type.replace(' *', '').strip()
        else:
            let iter_type = struct_type  # inferred: String
            let iter_var = obj_val  # inferred: String
            let iter_base = base
        let has_next_fn = str(iter_base) + '___has_next__'  # inferred: String
        let next_fn = str(iter_base) + '___next__'  # inferred: String
        let elem_type = self.func_return_types.get(next_fn, 'int')
        self._declare_var(var, elem_type)
        let bb_cond = self._new_bb()
        let bb_body = self._new_bb()
        let bb_post = self._new_bb()
        let bb_after = self._new_bb()
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_cond)
        if has_next_fn in self.func_return_types:
            let hn_t = self._new_temp('int')
            let cond_t = self._new_temp('_Bool')
            self._emit('  ' + str(hn_t) + ' = ' + str(has_next_fn) + ' (' + str(iter_var) + ');')
            self._emit('  ' + str(cond_t) + ' = ' + str(hn_t) + ' != 0;')
        else:
            let cond_t = self._new_temp('_Bool')
            self._emit('  ' + str(cond_t) + ' = 0;  /* TODO: no __has_next__ on ' + str(iter_base) + ' */')
        self._emit('  if (' + str(cond_t) + ') goto ' + str(bb_body) + '; else goto ' + str(bb_after) + ';')
        self._loop_depth += 1
        self._emit_label(bb_body, 'count(guessed_local(' + str((10 ** self._loop_depth)) + '))')
        if next_fn in self.func_return_types:
            let nxt = self._new_temp(elem_type)
            self._emit('  ' + str(nxt) + ' = ' + str(next_fn) + ' (' + str(iter_var) + ');')
            self._emit('  ' + str(var) + ' = ' + str(nxt) + ';')
        else:
            self._emit('  /* TODO: no __next__ on ' + str(iter_base) + ' */')
        self.loop_stack.append((bb_post, bb_after))
        for s in body:
            self.gen_stmt(s)
        self.loop_stack.pop()
        self._loop_depth -= 1
        self._emit('  goto ' + str(bb_post) + ';')
        self._emit_label(bb_post)
        self._emit('  goto ' + str(bb_cond) + ';')
        self._emit_label(bb_after)
    def _param_ctype(self, pname: String, ptype, node: FunctionDef, is_self: Bool) -> String:
        """Resolve parameter C type, applying argument convention qualifiers."""
        if is_self:
            return str(node.name) + ' *'
        var ctype = self._resolve_type(ptype)
        let conv = getattr(node, 'param_convs', {}) or {}.get(pname)
        if conv in ('read', 'ref') and TypeLattice.is_pointer(ctype):
            if not ctype.startswith('const '):
                let ctype = ('const ' + ctype)
        return ctype
    fn gen_func(self, node: FunctionDef) -> String:
        self._reset_func()
        self.current_func_name = node.name
        for (pname, ptype) in node.params:
            self.var_types[pname] = self._resolve_type(ptype)
        if node.return_type is not None:
            let ret_type = self._resolve_type(node.return_type)
        else:
            let ret_type = self._infer_return_type(node.body)
            if node.name == 'main' and ret_type == 'void':
                let ret_type = 'int'  # inferred: String
        self.func_ret_type = ret_type
        let solver = LayoutSolver(self.struct_field_types)
        self._struct_layout = solver.solve(node.params, node.body)
        let param_strs = []  # inferred: DynamicVector[AnyType]
        for (pname, ptype) in node.params:
            let ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype
            param_strs.append(str(ctype) + ' ' + str(pname))
        let params_str = ', '.join(param_strs) if param_strs else 'void'
        let safe = _safe_name(node.name)
        self._emit_label('bb_2')
        for stmt in node.body:
            self.gen_stmt(stmt)
        if node.name == 'main' and ret_type == 'int' and not self.body_lines[-1:] == ['  return 0;']:
            if not self.body_lines and self.body_lines[-1].strip().startswith('return'):
                self._emit('  return 0;')
        let lines = [str(ret_type) + ' __GIMPLE ' + str(safe) + ' (' + str(params_str) + ')', '{', *self.decls, *self.body_lines, '}']  # inferred: DynamicVector[AnyType]
        return '\n'.join(lines)
    fn _gen_struct_method(self, struct_name: String, node: FunctionDef) -> String:
        self._reset_func()
        self.current_func_name = str(struct_name) + '_' + str(node.name)
        for (i, (pname, ptype)) in enumerate(node.params):
            if i == 0 and pname == 'self':
                self.var_types[pname] = str(struct_name) + ' *'
            else:
                self.var_types[pname] = self._resolve_type(ptype)
        if node.return_type is not None:
            let ret_type = self._resolve_type(node.return_type)
        else:
            let ret_type = self._infer_return_type(node.body)
            if ret_type == 'void':
                let ret_type = 'void'  # inferred: String
        self.func_ret_type = ret_type
        let solver = LayoutSolver(self.struct_field_types)
        self._struct_layout = solver.solve(node.params, node.body)
        let param_strs = []  # inferred: DynamicVector[AnyType]
        for (i, (pname, ptype)) in enumerate(node.params):
            if i == 0 and pname == 'self':
                let ctype = str(struct_name) + ' *'  # inferred: String
            else:
                let ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype
            param_strs.append(str(ctype) + ' ' + str(pname))
        let params_str = ', '.join(param_strs) if param_strs else 'void'
        let mangled = str(struct_name) + '_' + str(_safe_name(node.name))  # inferred: String
        self._emit_label('bb_2')
        for stmt in node.body:
            self.gen_stmt(stmt)
        let lines = [str(ret_type) + ' __GIMPLE ' + str(mangled) + ' (' + str(params_str) + ')', '{', *self.decls, *self.body_lines, '}']  # inferred: DynamicVector[AnyType]
        return '\n'.join(lines)
    fn gen_module(self, stmts: list) -> String:
        self.struct_field_types = {}
        for s in stmts:
            if isinstance(s, StructDef):
                self.struct_field_types[s.name] = {}
                for field in s.fields:
                    if isinstance(field, VarDecl):
                        self.struct_field_types[s.name][field.name] = _mojo_type(field.type_ann)
        self.func_return_types = dict(_RUNTIME_FUNCS)
        for s in stmts:
            if isinstance(s, StructDef):
                self.func_return_types[s.name] = str(s.name) + ' *'
        self.imported_symbols = {}
        for s in stmts:
            if isinstance(s, FromImportStmt):
                try:
                    let exports = load_module(s.module)
                    for (name, alias) in s.names:
                        let sym_name = alias if alias else name
                        let sym_info = exports.get(name, {})
                        if isinstance(sym_info, str):
                            let sym_type = sym_info
                            self.imported_symbols[sym_name] = {'module': s.module, 'original_name': name, 'return_type': sym_type, 'parameters': [], 'signature': str(sym_type) + ' ' + str(sym_name) + ' (void)'}
                            self.func_return_types[sym_name] = sym_type
                        else:
                            sym_info['module'] = s.module
                            sym_info['original_name'] = name
                            self.imported_symbols[sym_name] = sym_info
                            if 'c_return_type' in sym_info:
                                self.func_return_types[sym_name] = sym_info['c_return_type']
                except _e:
                    pass
        for s in stmts:
            if isinstance(s, FunctionDef) and s.return_type is not None:
                self.func_return_types[s.name] = self._resolve_type(s.return_type)
        for s in stmts:
            if isinstance(s, StructDef):
                for m in s.methods:
                    if m.return_type is not None:
                        self.func_return_types[str(s.name) + '_' + str(m.name)] = self._resolve_type(m.return_type)
        for s in stmts:
            if isinstance(s, FunctionDef) and s.return_type is None:
                for (pname, ptype) in s.params:
                    self.var_types[pname] = self._resolve_type(ptype)
                let inferred = self._infer_return_type(s.body)
                if s.name == 'main' and inferred == 'void':
                    let inferred = 'int'  # inferred: String
                self.func_return_types[s.name] = inferred
                self.var_types.clear()
        self._all_closures = {}
        for s in stmts:
            if not isinstance(s, FunctionDef):
                continue
            var outer_scope: dict = {}
            for (pname, ptype) in s.params:
                outer_scope[pname] = self._resolve_type(ptype)
            for stmt in s.body:
                if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                    outer_scope[stmt.name] = _mojo_type(stmt.type_ann)
            for stmt in s.body:
                if not isinstance(stmt, FunctionDef):
                    continue
                let inner = stmt
                let lifted = str(s.name) + '_' + str(inner.name)  # inferred: String
                var used = set()
                for body_node in inner.body:
                    used |= _used_idents_node(body_node)
                var _tmp99 = DynamicVector[AnyType]()
                for (pn, _) in inner.params:
                    _tmp99.append(pn)
                let inner_declared = (_tmp99 | _declared_vars_body(inner.body))
                let free_globals = set(self.func_return_types.keys())
                let free = ((used - inner_declared) - free_globals)
                var captures = DynamicVector[AnyType]()
                for v in sorted(free):
                    if v in outer_scope:
                        captures.append((v, outer_scope[v]))
                let env_struct = str(lifted) + '_env' if captures else ''
                let ci = ClosureInfo(lifted, env_struct, captures, inner)
                if s.name not in self._all_closures:
                    self._all_closures[s.name] = {}
                self._all_closures[s.name][inner.name] = ci
                if inner.return_type is not None:
                    self.func_return_types[lifted] = self._resolve_type(inner.return_type)
                else:
                    for (pname, ptype) in inner.params:
                        self.var_types[pname] = self._resolve_type(ptype)
                    self.func_return_types[lifted] = self._infer_return_type(inner.body)
                    self.var_types.clear()
        var func_parts: DynamicVector[String] = []
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                for ci in self._all_closures.get(stmt.name, {}).values():
                    if ci.env_struct:
                        let alloc_fn = '_alloc_' + str(ci.env_struct)  # inferred: String
                        func_parts.append(str(ci.env_struct) + ' * __GIMPLE ' + str(alloc_fn) + ' (void)\n{\n  ' + str(ci.env_struct) + ' * _e;\n  void * _vp;\n\nbb_2:\n  _vp = malloc (sizeof(' + str(ci.env_struct) + '));\n  _e = (' + str(ci.env_struct) + ' *) _vp;\n  return _e;\n}')
                        func_parts.append('')
                    func_parts.append(self._gen_lifted_closure(ci))
                    func_parts.append('')
                func_parts.append(self.gen_func(stmt))
                func_parts.append('')
            elif isinstance(stmt, StructDef):
                for m in stmt.methods:
                    func_parts.append(self._gen_struct_method(stmt.name, m))
                    func_parts.append('')
            elif isinstance(stmt, TraitDef):
                let lines = ['typedef struct ' + str(stmt.name) + '_vtable {']  # inferred: DynamicVector[AnyType]
                for m in stmt.methods:
                    let ret = self._resolve_type(m.return_type)
                    var _tmp100 = DynamicVector[AnyType]()
                    for (_, pt) in m.params:
                        _tmp100.append(self._resolve_type(pt))
                    let ptypes = ', '.join(_tmp100) if m.params else 'void'
                    lines.append('  ' + str(ret) + ' (*' + str(m.name) + ') (' + str(ptypes) + ');')
                lines.append('} ' + str(stmt.name) + '_vtable;')
                func_parts.extend(lines)
                func_parts.append('')
            elif isinstance(stmt, (ImportStmt, FromImportStmt)):
                pass
            else:
                func_parts.append('/* TODO: top-level ' + str(type(stmt).__name__) + ' */')
        let parts = ['/* Generated by gimple_codegen.py */', '/* Compile with: gcc-mp-15 -fgimple -fsyntax-only file.c */', '#include <stdint.h>', '#include <stdlib.h>', '#include <math.h>', '#include <stdio.h>', '#include <setjmp.h>', '#include "mojo_runtime.h"', '', _HELPERS]  # inferred: DynamicVector[AnyType]
        for et in sorted(self._ptr_helpers_needed):
            let cn = _c_id(et)
            parts.append('static ' + str(et) + ' * _mojo_at_' + str(cn) + ' (' + str(et) + ' * p, int64_t n) { return p + n; }')
        if self._ptr_helpers_needed:
            parts.append('')
        var struct_defs = DynamicVector[AnyType]()
        for s in stmts:
            if isinstance(s, StructDef):
                struct_defs.append(s)
        for sd in struct_defs:
            parts.append('typedef struct ' + str(sd.name) + ' {')
            for field in sd.fields:
                if isinstance(field, VarDecl):
                    let ft = _mojo_type(field.type_ann)
                    parts.append('  ' + str(ft) + ' ' + str(field.name) + ';')
            parts.append('} ' + str(sd.name) + ';')
            parts.append('')
        for inner_map in self._all_closures.values():
            for ci in inner_map.values():
                if ci.env_struct:
                    parts.append('typedef struct ' + str(ci.env_struct) + ' {')
                    for (vname, vtype) in ci.captures:
                        parts.append('  ' + str(vtype) + ' ' + str(vname) + ';')
                    parts.append('} ' + str(ci.env_struct) + ';')
                    parts.append('')
        for sn in sorted(self._struct_allocs_needed):
            parts.append(str(sn) + ' * __GIMPLE _alloc_' + str(sn) + ' (void)\n{\n  ' + str(sn) + ' * _p;\n  void * _vp;\n\nbb_2:\n  _vp = malloc (sizeof(' + str(sn) + '));\n  _p = (' + str(sn) + ' *) _vp;\n  return _p;\n}')
            parts.append('')
        for sym_name in sorted(self.imported_symbols.keys()):
            var sym_info = self.imported_symbols[sym_name]
            if 'signature' in sym_info:
                let signature = sym_info['signature']
                let module = sym_info['module']
                parts.append('extern ' + str(signature) + ';  /* from ' + str(module) + ' */')
            else:
                let ret_type = sym_info.get('return_type', 'int')
                let module = sym_info.get('module', '')
                let ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
                parts.append('extern ' + str(ret_type) + ' ' + str(_safe_name(sym_name)) + ' (void);  /* from ' + str(module) + ' */')
        if self.imported_symbols:
            parts.append('')
        var func_defs = DynamicVector[AnyType]()
        for s in stmts:
            if isinstance(s, FunctionDef):
                func_defs.append(s)
        for fn in func_defs:
            var ret = self.func_return_types.get(fn.name, 'int')
            var _tmp101 = DynamicVector[AnyType]()
            for (pn, pt) in fn.params:
                _tmp101.append(self._param_ctype(pn, pt, fn))
            var ptypes = ', '.join(_tmp101) if fn.params else 'void'
            parts.append(str(ret) + ' ' + str(_safe_name(fn.name)) + ' (' + str(ptypes) + ');')
        for sd in struct_defs:
            for m in sd.methods:
                var ret = self.func_return_types.get(str(sd.name) + '_' + str(m.name), self._resolve_type(m.return_type))
                let param_ctypes = []  # inferred: DynamicVector[AnyType]
                for (i, (pname, ptype)) in enumerate(m.params):
                    let ct = str(sd.name) + ' *' if i == 0 and pname == 'self' else self._resolve_type(ptype)
                    param_ctypes.append(ct)
                var ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
                parts.append(str(ret) + ' ' + str(sd.name) + '_' + str(_safe_name(m.name)) + ' (' + str(ptypes) + ');')
        if func_defs or struct_defs:
            parts.append('')
        for (outer_name, inner_map) in self._all_closures.items():
            for (inner_name, ci) in inner_map.items():
                if ci.env_struct:
                    let alloc_fn = '_alloc_' + str(ci.env_struct)  # inferred: String
                    parts.append(str(ci.env_struct) + ' * ' + str(alloc_fn) + ' (void);')
                var ret = self.func_return_types.get(ci.lifted_name, 'int')
                let node = ci.inner_def
                let ptypes_list = []  # inferred: DynamicVector[AnyType]
                if ci.env_struct:
                    ptypes_list.append(str(ci.env_struct) + ' *')
                for (pn, pt) in node.params:
                    ptypes_list.append(self._param_ctype(pn, pt, node))
                var ptypes = ', '.join(ptypes_list) if ptypes_list else 'void'
                parts.append(str(ret) + ' ' + str(ci.lifted_name) + ' (' + str(ptypes) + ');')
        if self._all_closures:
            parts.append('')
        parts.extend(func_parts)
        return '\n'.join(parts)

fn compile_to_c(mojo_src: String) -> String:
    """Parse Mojo source and return C code WITHOUT __GIMPLE annotations.

    Useful for execution tests where __GIMPLE restrictions don't apply.
    """
    let tokens = tokenize(mojo_src)
    let stmts = Parser(tokens).parse_module()
    var c_code = GimpleGen().gen_module(stmts)
    var c_code = c_code.replace(' __GIMPLE ', ' ')
    return c_code

fn compile_to_gimple(mojo_src: String) -> String:
    """Parse Mojo source and return a C string with __GIMPLE annotations."""
    let tokens = tokenize(mojo_src)
    let stmts = Parser(tokens).parse_module()
    return GimpleGen().gen_module(stmts)
