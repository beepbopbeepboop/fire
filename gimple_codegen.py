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
        # Pointer: preserve the pointer type
        if cls.is_pointer(t1) or cls.is_pointer(t2):
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
        """Return `val` cast to `dst` if types differ."""
        if src == dst:
            return val
        # _Bool → numeric: go through int to avoid GIMPLE type-mismatch rejection
        if src == '_Bool' and cls.is_int(dst):
            return f"({dst})(int){val}" if dst != 'int' else f"(int){val}"
        if src == '_Bool':
            return f"(int){val}" if dst == 'int' else f"({dst})(int){val}"
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
        escaped  = self._ea.find_escaping(params, body)
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
    'List':   'MojoList *',
    'Dict':   'MojoDict *',
    'Set':    'MojoSet *',
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
}

_FLOAT_TYPES = {'double', 'float', '__fp16'}

def _mojo_type(ann) -> str:
    if ann is None:
        return 'int'
    if isinstance(ann, str):
        # Handle parameterized types: UnsafePointer[Int], List[Float64], etc.
        if '[' in ann:
            base, rest = ann.split('[', 1)
            inner = rest.rstrip(']').strip()
            if base in ('UnsafePointer', 'OwnedPointer', 'ArcPointer', 'Pointer'):
                elem = _mojo_type(inner)
                return f"{elem} *"
            if base in ('List', 'InlineArray'):
                return 'MojoList *'
            if base == 'Dict':
                return 'MojoDict *'
            if base == 'Set':
                return 'MojoSet *'
            if base == 'Optional':
                return _mojo_type(inner)  # simplified: treat as the inner type
            # Unknown parameterized type — fall through to plain lookup
            ann = base
        t = _TYPE_MAP.get(ann)
        return t if t is not None else 'int'
    return 'int'

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
        r3 = _used_idents_node(node.expr)
        for g in node.generators: r3 |= _used_idents_node(g.iterable)
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
        self.lifted_name = lifted_name
        self.env_struct  = env_struct
        self.captures    = captures   # [(varname, ctype)]
        self.inner_def   = inner_def  # FunctionDef node


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
# GimpleGen
# ---------------------------------------------------------------------------

class GimpleGen:
    def __init__(self):
        self.func_return_types: dict[str, str] = {}
        self.struct_field_types: dict[str, dict[str, str]] = {}
        self.imported_symbols: dict[str, tuple] = {}  # symbol_name -> (module, orig_name, type)
        self._all_closures: dict = {}   # populated by gen_module pre-pass
        self._ptr_helpers_needed: set[str] = set()   # elem C types needing _mojo_at_ helpers
        self._struct_allocs_needed: set[str] = set() # struct names needing _alloc_ helpers
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
        # Container / layout state
        self._elem_types:      dict[str, str]   = {}  # container var → element C type
        self._dict_val_types:  dict[str, str]   = {}  # dict var → value C type
        self._struct_layout:   dict[str, str]   = {}  # var_name → STACK|HEAP
        self._layout_hint:  str             = LayoutSolver.HEAP  # for struct constructors
        self.current_func_name: str         = ''
        self._loop_depth:   int             = 0   # nesting depth for freq annotations
        # Closure state (set when generating a lifted inner function)
        self._captures:   dict[str, str]    = {}  # captured var → ctype
        self._env_param:  str               = ''  # name of env pointer ('_env')
        # Active env pointers for this outer function (inner_name → env_var)
        self._closure_envs: dict[str, str]  = {}

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

    def _emit_label(self, label: str, freq_hint: str = ''):
        ann = f'  /* {freq_hint} */' if freq_hint else ''
        self.body_lines.append(f"\n{label}:{ann}")

    def _type_of(self, name: str) -> str:
        return self.var_types.get(name, 'int')

    def _elem_of(self, name: str) -> str:
        """Element type for a container variable."""
        return self._elem_types.get(name, 'int64_t')

    def _dict_val_of(self, name: str) -> str:
        """Value C type for a dict variable."""
        return self._dict_val_types.get(name, 'int64_t')

    def _coerce(self, src: str, dst: str, val: str) -> str:
        return TypeLattice.coerce(src, dst, val)

    def _resolve_type(self, ann) -> str:
        if ann in self.struct_field_types:
            return f"{ann} *"
        return _mojo_type(ann)

    def _declare_var(self, name: str, ctype: str, elem: str | None = None):
        if name not in self.var_types:
            self.decls.append(f"  {ctype} {name};")
            self.var_types[name] = ctype
        if elem is not None:
            self._elem_types[name] = elem

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
            return self.func_return_types.get(node.func.name, 'int')
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

    def _lower_StringLiteral(self, node) -> tuple[str, str]:
        val = node.value
        # Strip outer quotes (tokenizer includes them)
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        escaped = val.replace('\\', '\\\\').replace('"', '\\"')
        return 'char *', f'"{escaped}"'

    def _lower_IdentExpr(self, node) -> tuple[str, str]:
        name = node.name
        # Special handling for Python built-in constants
        if name == 'None':
            return 'int', '0'
        if name == 'True':
            return 'int', '1'
        if name == 'False':
            return 'int', '0'
        if name in self._captures and self._env_param:
            ctype = self._captures[name]
            t = self._new_temp(ctype)
            self._emit(f"  {t} = {self._env_param}->{name};")
            return ctype, t
        return self._type_of(name), name

    def _lower_WalrusExpr(self, node) -> tuple[str, str]:
        vtype, vv = self.lower_expr(node.value)
        if node.name not in self.var_types:
            self._declare_var(node.name, vtype)
        dst = self.var_types[node.name]
        self._emit(f"  {node.name} = {self._coerce(vtype, dst, vv)};")
        return dst, node.name

    def _lower_UnaryOp(self, node) -> tuple[str, str]:
        ot, ov = self.lower_expr(node.operand)
        if node.op == 'not':
            t = self._new_temp('_Bool')
            self._emit(f"  {t} = {ov} == 0;")
            return '_Bool', t
        c_op = {'-': '-', '~': '~', '+': '+'}.get(node.op, node.op)
        t = self._new_temp(ot)
        self._emit(f"  {t} = {c_op}{ov};")
        return ot, t

    def _lower_TernaryExpr(self, node) -> tuple[str, str]:
        ct, cv = self.lower_expr(node.condition)
        tt, tv = self.lower_expr(node.then_val)
        et, ev = self.lower_expr(node.else_val)
        res_type = TypeLattice.join(tt, et)
        t = self._new_temp(res_type)
        self._emit(f"  {t} = {cv} ? {tv} : {ev};")
        return res_type, t

    def _lower_MemberExpr(self, node) -> tuple[str, str]:
        ot, ov = self.lower_expr(node.obj)

        # Special handling for .__name__ on type objects (which are ints)
        if node.member == '__name__' and ot == 'int':
            t = self._new_temp('char *')
            type_names = {
                '0': '"NoneType"',
                '1': '"bool"',
                '2': '"int"',
                '3': '"float"',
                '4': '"str"',
                '5': '"list"',
                '6': '"dict"',
                '7': '"set"'
            }
            # For now, return a default name
            self._emit(f"  {t} = \"UnknownType\";  /* TODO: map type ID {ov} to __name__ */")
            return 'char *', t

        op = '->' if '*' in ot else '.'
        struct_name = ot.replace(' *', '').strip()
        field_type = (self.struct_field_types.get(struct_name, {})
                      .get(node.member, 'int'))
        t = self._new_temp(field_type)
        self._emit(f"  {t} = {ov}{op}{node.member};")
        return field_type, t

    # ── Binary operator lowering ──────────────────────────────────────────

    def _lower_binary(self, node: BinaryOp) -> tuple[str, str]:
        if node.op == ':=':
            vtype, vv = self.lower_expr(node.right)
            if isinstance(node.left, IdentExpr):
                nm = node.left.name
                if nm not in self.var_types:
                    self._declare_var(nm, vtype)
                dst = self.var_types[nm]
                self._emit(f"  {nm} = {self._coerce(vtype, dst, vv)};")
                return dst, nm
            if isinstance(node.left, MemberExpr):
                ot, ov = self.lower_expr(node.left.obj)
                op = '->' if '*' in ot else '.'
                sn = ot.replace(' *', '').strip()
                field_type = self.struct_field_types.get(sn, {}).get(node.left.member, vtype)
                self._emit(f"  {ov}{op}{node.left.member} = {self._coerce(vtype, field_type, vv)};")
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
            self._emit("  /* walrus: unsupported LHS */")
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

        lt, lv = self.lower_expr(node.left)
        rt, rv = self.lower_expr(node.right)

        # MojoList + MojoList → mojo_list_concat
        if node.op == '+' and lt == 'MojoList *' and rt == 'MojoList *':
            t = self._new_temp('MojoList *')
            self._emit(f"  {t} = mojo_list_concat ({lv}, {rv});")
            if lv in self._elem_types:
                self._elem_types[t] = self._elem_types[lv]
            return 'MojoList *', t

        # MojoStr + MojoStr → mojo_str_concat
        if node.op == '+' and lt == 'MojoStr *' and rt == 'MojoStr *':
            t = self._new_temp('MojoStr *')
            self._emit(f"  {t} = mojo_str_concat ({lv}, {rv});")
            return 'MojoStr *', t

        # char * + char * → mojo_str_cat (C string concatenation)
        if node.op == '+' and lt == 'char *' and rt == 'char *':
            t = self._new_temp('char *')
            self._emit(f"  {t} = mojo_str_cat ({lv}, {rv});")
            return 'char *', t

        # char * * int → string repetition (e.g., "  " * 3)
        if node.op == '*' and lt == 'char *' and rt in ('int', 'int64_t', 'uint64_t'):
            t = self._new_temp('char *')
            self._emit(f"  {t} = mojo_cstr_repeat ({lv}, {rv});")
            return 'char *', t

        # int * char * → string repetition (flipped order)
        if node.op == '*' and lt in ('int', 'int64_t', 'uint64_t') and rt == 'char *':
            t = self._new_temp('char *')
            self._emit(f"  {t} = mojo_cstr_repeat ({rt}, {lv});")
            return 'char *', t

        # MojoStr == / != → mojo_str_eq
        if node.op in ('==', '!=') and lt == 'MojoStr *' and rt == 'MojoStr *':
            eq_t = self._new_temp('int')
            self._emit(f"  {eq_t} = mojo_str_eq ({lv}, {rv});")
            t = self._new_temp('_Bool')
            cmp = '!= 0' if node.op == '==' else '== 0'
            self._emit(f"  {t} = {eq_t} {cmp};")
            return '_Bool', t

        # is / is not → pointer identity
        if node.op in ('is', 'is not'):
            c_op = '==' if node.op == 'is' else '!='
            t = self._new_temp('_Bool')
            if '*' in lt or '*' in rt:
                p1 = self._new_temp('void *')
                p2 = self._new_temp('void *')
                self._emit(f"  {p1} = (void *) {lv};")
                self._emit(f"  {p2} = (void *) {rv};")
                self._emit(f"  {t} = {p1} {c_op} {p2};")
            else:
                self._emit(f"  {t} = {lv} {c_op} {rv};")
            return '_Bool', t

        c_op      = _BIN_OPS.get(node.op, node.op)
        res_type  = '_Bool' if node.op in _CMP_OPS else TypeLattice.join(lt, rt)
        # Cast operands to result type to satisfy GIMPLE strict type checking
        arith_type = TypeLattice.join(lt, rt)  # common type for arithmetic
        if lt != arith_type and arith_type not in ('_Bool',):
            ct = self._new_temp(arith_type)
            self._emit(f"  {ct} = ({arith_type}){lv};")
            lv = ct
        if rt != arith_type and arith_type not in ('_Bool',):
            ct = self._new_temp(arith_type)
            self._emit(f"  {ct} = ({arith_type}){rv};")
            rv = ct
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
            self._emit("  /* TODO: in range(a, b, step) */")
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
            suf = TypeLattice.list_suffix(xt)
            xv_cast = self._cast_for_list(xt, xv, suf)
            self._emit(f"  {ti} = mojo_list_contains_{suf} ({rv}, {xv_cast});")
        elif rt == 'MojoDict *':
            self._emit(f"  {ti} = mojo_dict_contains ({rv}, {xv});")
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
        return val  # str

    def _to_int64(self, ctype: str, val: str) -> str:
        """Cast val to int64_t; emits to a temp so the result is always an lvalue."""
        if ctype == 'int64_t':
            return val
        t = self._new_temp('int64_t')
        self._emit(f"  {t} = (int64_t){val};")
        return t

    # ── Method call lowering ──────────────────────────────────────────────

    _RUNTIME_PTRS = frozenset({'MojoList *', 'MojoStr *', 'MojoDict *', 'MojoSet *',
                                'MojoDictIter *', 'MojoSetIter *'})

    def _lower_method_call(self, node: CallExpr) -> tuple[str, str]:
        """Lower obj.method(args) — handles raw C pointers (UnsafePointer) and structs."""
        func = node.func  # MemberExpr
        ot, ov = self.lower_expr(func.obj)
        method = func.member

        # Raw C pointer operations (UnsafePointer[T] lowers to T *)
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

        # Struct method call: obj.method(args) → StructName_method(self, args)
        struct_name = ot.replace(' *', '').strip()
        mangled = _safe_name(f"{struct_name}_{method}")
        ret_type = self.func_return_types.get(f"{struct_name}_{method}", 'int')
        arg_vals = [self.lower_expr(a)[1] for a in node.args]
        all_args = ', '.join([ov] + arg_vals)

        if ret_type == 'void':
            self._emit(f"  {mangled} ({all_args});")
            t = self._new_temp('int'); self._emit(f"  {t} = 0;"); return 'int', t
        t = self._new_temp(ret_type)
        self._emit(f"  {t} = {mangled} ({all_args});")
        return ret_type, t

    # ── Call expression lowering ──────────────────────────────────────────

    def _lower_call(self, node: CallExpr) -> tuple[str, str]:
        if isinstance(node.func, MemberExpr):
            return self._lower_method_call(node)
        if not isinstance(node.func, IdentExpr):
            self._emit("  /* TODO: complex call expression */")
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;")
            return 'int', t

        fname_raw = node.func.name

        # isinstance() built-in
        if fname_raw == 'isinstance' and len(node.args) == 2:
            obj_type, obj_val = self.lower_expr(node.args[0])
            # Handle type argument - could be a type name or a tuple of types
            type_arg = node.args[1]

            # For now, emit a simplified version that always returns 0
            # This allows code to compile even if logic isn't perfect
            t = self._new_temp('int')
            if isinstance(type_arg, IdentExpr):
                # Single type: isinstance(obj, TypeName)
                type_name = type_arg.name
                type_id_map = {'bool': '1', 'int': '2', 'float': '3', 'str': '4', 'list': '5', 'dict': '6', 'set': '7'}
                type_id = type_id_map.get(type_name, '0')
                self._emit(f"  {t} = mojo_isinstance ({obj_val}, {type_id});")
            elif isinstance(type_arg, TupleExpr):
                # Tuple of types: isinstance(obj, (Type1, Type2, ...))
                # For now, just return 0 (false)
                self._emit(f"  {t} = 0;  /* TODO: isinstance with tuple of types */")
            else:
                # Complex expression
                self._emit(f"  {t} = 0;  /* TODO: isinstance with complex type arg */")
            return 'int', t

        # str() built-in
        if fname_raw == 'str' and len(node.args) == 1:
            arg_type, arg_val = self.lower_expr(node.args[0])
            t = self._new_temp('char *')
            self._emit(f"  {t} = mojo_str ({arg_val});")
            return 'char *', t

        # repr() built-in
        if fname_raw == 'repr' and len(node.args) == 1:
            arg_type, arg_val = self.lower_expr(node.args[0])
            t = self._new_temp('char *')
            self._emit(f"  {t} = mojo_repr ({arg_val});")
            return 'char *', t

        # type() built-in
        if fname_raw == 'type' and len(node.args) == 1:
            arg_type, arg_val = self.lower_expr(node.args[0])
            t = self._new_temp('int')
            self._emit(f"  {t} = mojo_type ({arg_val});")
            return 'int', t

        # hasattr() built-in
        if fname_raw == 'hasattr' and len(node.args) == 2:
            obj_type, obj_val = self.lower_expr(node.args[0])
            attr_type, attr_val = self.lower_expr(node.args[1])
            t = self._new_temp('int')
            self._emit(f"  {t} = mojo_hasattr ({obj_val}, {attr_val});")
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

        # Struct constructor: TypeName(arg1, arg2, ...)
        if fname_raw in self.struct_field_types:
            return self._lower_struct_constructor(fname_raw, node.args)

        # open() built-in → mojo_open()
        if fname_raw == 'open' and len(node.args) == 2:
            fn_type, fn_val = self.lower_expr(node.args[0])
            mode_type, mode_val = self.lower_expr(node.args[1])
            t = self._new_temp('void *')
            self._emit(f"  {t} = mojo_open ({fn_val}, {mode_val});")
            return 'void *', t

        # Closure call: inner function name mapped to a lifted top-level function
        if fname_raw in self._closure_envs:
            lifted   = f"{self.current_func_name}_{fname_raw}"
            env_var  = self._closure_envs[fname_raw]
            ret_type = self.func_return_types.get(lifted, 'int')
            arg_vals = [self.lower_expr(a)[1] for a in node.args]
            all_args = ', '.join([env_var] + arg_vals) if env_var else ', '.join(arg_vals)
            fname_c  = _safe_name(lifted)
            if ret_type == 'void':
                self._emit(f"  {fname_c} ({all_args});")
                t = self._new_temp('int'); self._emit(f"  {t} = 0;")
                return 'int', t
            t = self._new_temp(ret_type)
            self._emit(f"  {t} = {fname_c} ({all_args});")
            return ret_type, t

        fname    = _safe_name(fname_raw)
        ret_type = self.func_return_types.get(fname_raw, 'int')
        arg_vals = [self.lower_expr(a)[1] for a in node.args]
        args_str = ', '.join(arg_vals)

        if ret_type == 'void':
            self._emit(f"  {fname} ({args_str});")
            t = self._new_temp('int')
            self._emit(f"  {t} = 0;")
            return 'int', t

        t = self._new_temp(ret_type)
        self._emit(f"  {t} = {fname} ({args_str});")
        return ret_type, t

    # ── Struct constructor lowering (data layout solver decision) ─────────

    def _lower_struct_constructor(self, struct_name: str,
                                  args: list) -> tuple[str, str]:
        """
        Lower TypeName(field1, field2, ...) to allocation + field init.

        Uses _alloc_StructName() helper (emitted in preamble) because
        sizeof(T) is invalid in __GIMPLE body when T is not in the signature.
        """
        ctype  = f"{struct_name} *"
        t      = self._new_temp(ctype)
        self._struct_allocs_needed.add(struct_name)
        self._emit(f"  {t} = _alloc_{struct_name} ();")

        fields = list(self.struct_field_types[struct_name].items())
        for i, (fname, ftype) in enumerate(fields):
            if i < len(args):
                at, av = self.lower_expr(args[i])
                self._emit(f"  {t}->{fname} = {self._coerce(at, ftype, av)};")
        return ctype, t

    # ── Subscript lowering ────────────────────────────────────────────────

    def _lower_subscript(self, node: SubscriptExpr) -> tuple[str, str]:
        ot, ov = self.lower_expr(node.obj)
        _, iv  = self.lower_expr(node.index)

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
                self._emit(f"  {t} = mojo_dict_get_double ({ov}, {iv});")
                return 'double', t
            if val_ctype == 'char *':
                t = self._new_temp('char *')
                self._emit(f"  {t} = mojo_dict_get_str ({ov}, {iv});")
                return 'char *', t
            t = self._new_temp('int64_t')
            self._emit(f"  {t} = mojo_dict_get_int ({ov}, {iv});")
            return 'int64_t', t

        # p[i] is invalid GIMPLE — use _mojo_at_ helper (ptr arithmetic not allowed in __GIMPLE)
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
        t = self._new_temp(ot)
        self._emit(f"  {t} = {ov} + {start_v};")
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
            ev_cast = self._cast_for_list(et, ev, suf)
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
            if vt in _FLOAT_TYPES:
                self._emit(f"  mojo_dict_set_double ({t}, {kv}, {vv});")
            elif vt == 'char *':
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
                self._emit(f"  mojo_set_add_str ({t}, {ev});")
            else:
                ev64 = self._to_int64(et, ev)
                self._emit(f"  mojo_set_add_int ({t}, {ev64});")
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
            self._emit(f"  mojo_list_append_{suf} ({t}, {ev_cast});")
        return 'MojoList *', t

    # ── Comprehension lowering ────────────────────────────────────────────

    def _lower_comprehension(self, node: Comprehension) -> tuple[str, str]:
        if not node.generators:
            t = self._new_temp('int')
            self._emit("  /* TODO: Comprehension with no generators */")
            self._emit(f"  {t} = 0;")
            return 'int', t

        gen0 = node.generators[0]

        if node.kind == 'list':
            res_type, res_new = 'MojoList *', 'mojo_list_new'
        elif node.kind == 'set':
            res_type, res_new = 'MojoSet *', 'mojo_set_new'
        elif node.kind == 'dict':
            res_type, res_new = 'MojoDict *', 'mojo_dict_new'
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
            self._emit("  /* TODO: range() unexpected arg count */"); return

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
        elem = self._elem_of(it_val)
        self._declare_var(gen0.target, elem)
        len64 = self._new_temp('int64_t'); idx64 = self._new_temp('int64_t')
        self._emit(f"  {len64} = mojo_list_len ({it_val});")
        self._emit(f"  {idx64} = 0;")
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
            self._emit(f"  {gen0.target} = mojo_list_get_str ({it_val}, {idx64});")
        else:
            raw64 = self._new_temp('int64_t')
            self._emit(f"  {raw64} = mojo_list_get_int ({it_val}, {idx64});")
            self._emit(f"  {gen0.target} = ({elem}) {raw64};")
        self._gen_compr_append(node, gen0, res, res_type, bb_after)
        self._emit(f"  goto {bb_post};")
        self._emit_label(bb_post)
        st = self._new_temp('int64_t')
        self._emit(f"  {st} = {idx64} + 1;")
        self._emit(f"  {idx64} = {st};")
        self._emit(f"  goto {bb_cond};")
        self._emit_label(bb_after)

    def _compr_str_loop(self, node, gen0, res, res_type, it_val):
        self._declare_var(gen0.target, 'char')
        len64 = self._new_temp('int64_t'); idx64 = self._new_temp('int64_t')
        self._emit(f"  {len64} = mojo_str_len ({it_val});")
        self._emit(f"  {idx64} = 0;")
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
        st = self._new_temp('int64_t')
        self._emit(f"  {st} = {idx64} + 1;")
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
            self._emit(f"  mojo_list_append_{suf} ({res}, {ev_cast});")
        elif node.kind == 'set':
            et, ev = self.lower_expr(node.element)
            if et == 'char *':
                self._emit(f"  mojo_set_add_str ({res}, {ev});")
            else:
                ev64 = self._to_int64(et, ev)
                self._emit(f"  mojo_set_add_int ({res}, {ev64});")
        elif node.kind == 'dict':
            _, kv  = self.lower_expr(node.element)   # element = key expression in dict compr
            vt, vv = self.lower_expr(node.key)        # key field holds the value expression
            # parser stores dict comprehension as: element=key_expr, key=val_expr
            if vt in _FLOAT_TYPES:
                self._emit(f"  mojo_dict_set_double ({res}, {kv}, {vv});")
            elif vt == 'char *':
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
        ctype = self._resolve_type(node.type_ann)
        if node.type_ann in self.struct_field_types and node.value is not None:
            layout = self._struct_layout.get(node.name, LayoutSolver.HEAP)
            self._layout_hint = layout
        self._declare_var(node.name, ctype)
        if node.value is not None:
            vtype, v = self.lower_expr(node.value)
            if ctype in ('MojoList *', 'MojoSet *') and v in self._elem_types:
                self._elem_types[node.name] = self._elem_types[v]
            if ctype == 'MojoDict *':
                if v in self._elem_types:
                    self._elem_types[node.name] = self._elem_types[v]
                if v in self._dict_val_types:
                    self._dict_val_types[node.name] = self._dict_val_types[v]
            self._emit(f"  {node.name} = {self._coerce(vtype, ctype, v)};")
        self._layout_hint = LayoutSolver.HEAP

    def _gen_stmt_AssignStmt(self, node):
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
            self._emit(f"  {tname} = {self._coerce(vtype, dst, v)};")
        elif isinstance(node.target, MemberExpr):
            ot, ov = self.lower_expr(node.target.obj)
            op = '->' if '*' in ot else '.'
            struct_name = ot.replace(' *', '').strip()
            field_type = self.struct_field_types.get(struct_name, {}).get(node.target.member, vtype)
            self._emit(f"  {ov}{op}{node.target.member} = {self._coerce(vtype, field_type, v)};")
        elif isinstance(node.target, SubscriptExpr):
            ot, obj_v = self.lower_expr(node.target.obj)
            _, idx_v  = self.lower_expr(node.target.index)
            if ot == 'MojoList *':
                elem = self._elem_of(obj_v)
                suf  = TypeLattice.list_suffix(elem)
                idx64 = self._new_temp('int64_t')
                self._emit(f"  {idx64} = (int64_t) {idx_v};")
                ev_cast = self._cast_for_list(vtype, v, suf)
                self._emit(f"  mojo_list_set_{suf} ({obj_v}, {idx64}, {ev_cast});")
            else:
                self._emit(f"  {obj_v}[{idx_v}] = {v};")
        else:
            self._emit("  /* TODO: complex assignment target */")

    def _gen_stmt_AugAssignStmt(self, node):
        base_op = node.op[:-1]
        if base_op in ('//', '**'):
            fake  = BinaryOp(op=base_op, left=node.target, right=node.value)
            vtype, v = self.lower_expr(fake)
        else:
            c_op = _BIN_OPS.get(base_op, base_op)
            rtype, rv = self.lower_expr(node.value)
            if isinstance(node.target, IdentExpr):
                tname  = node.target.name
                ttype  = self._type_of(tname)
                arith  = TypeLattice.join(ttype, rtype)
                lv_a   = tname
                rv_a   = rv
                if ttype != arith:
                    ct = self._new_temp(arith)
                    self._emit(f"  {ct} = ({arith}){tname};")
                    lv_a = ct
                if rtype != arith:
                    ct = self._new_temp(arith)
                    self._emit(f"  {ct} = ({arith}){rv};")
                    rv_a = ct
                tmp = self._new_temp(arith)
                self._emit(f"  {tmp} = {lv_a} {c_op} {rv_a};")
                vtype, v = arith, tmp
            else:
                self._emit("  /* TODO: complex aug-assign target */")
                return
        if isinstance(node.target, IdentExpr):
            tname = node.target.name
            dst   = self._type_of(tname)
            self._emit(f"  {tname} = {self._coerce(vtype, dst, v)};")
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
            self._emit("  return;")
        else:
            vtype, v = self.lower_expr(node.value)
            ret = self.func_ret_type
            if ret and ret != 'void' and vtype != ret:
                tmp = self._new_temp(ret)
                self._emit(f"  {tmp} = ({ret}){v};")
                self._emit(f"  return {tmp};")
            else:
                self._emit(f"  return {v};")

    def _gen_stmt_IfStmt(self, node):
        _, cond_v   = self.lower_expr(node.condition)
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
        _, cond_v = self.lower_expr(node.condition)
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
                self._emit(f"  {tname} = {self._coerce(vtype, dst, v)};")
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
            self._emit("  /* TODO: break outside loop */")

    def _gen_stmt_ContinueStmt(self, node):
        if self.loop_stack:
            self._emit(f"  goto {self.loop_stack[-1][0]};")
        else:
            self._emit("  /* TODO: continue outside loop */")

    def _gen_stmt_ExprStmt(self, node):
        if isinstance(node.value, CallExpr) and isinstance(node.value.func, IdentExpr):
            raw_name = node.value.func.name
            if raw_name == 'print':
                self._gen_print(node.value.args)
                return
            fname    = _safe_name(raw_name)
            arg_vals = [self.lower_expr(a)[1] for a in node.value.args]
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
        if node.value is not None:
            vt, vv = self.lower_expr(node.value)
            if vt == 'char *':
                self._emit(f"  mojo_exc_msg_set ({vv});")
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
        self._emit("  mojo_exc_pop ();")
        self._emit(f"  goto {bb_else if bb_else else bb_after};")

        self._emit_label(bb_exc)
        self._emit("  mojo_exc_pop ();")
        for handler in node.handlers:
            if handler.name:
                self._declare_var(handler.name, 'char *')
                self._emit(f"  {handler.name} = (char *) mojo_exc_msg_get ();")
            for s in handler.body:
                self.gen_stmt(s)
        if node.finally_body:
            for s in node.finally_body:
                self.gen_stmt(s)
        self._emit(f"  goto {bb_after};")

        if bb_else:
            self._emit_label(bb_else)
            for s in node.else_body:
                self.gen_stmt(s)
            if node.finally_body:
                for s in node.finally_body:
                    self.gen_stmt(s)
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
            self._emit("  mojo_exc_pop ();")
            _emit_exits()
            self._emit(f"  goto {bb_after};")

            self._emit_label(bb_exc)
            self._emit("  mojo_exc_pop ();")
            _emit_exits()
            self._emit("  mojo_raise ();")
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
            for vname, _ in ci.captures:
                self._emit(f"  {env_var}->{vname} = {vname};")
            self._closure_envs[node.name] = env_var
        else:
            self._closure_envs[node.name] = ''

    def _gen_stmt_ImportStmt(self, node):
        self._emit("  /* TODO: import */")

    def _gen_stmt_FromImportStmt(self, node):
        self._emit("  /* TODO: from import */")

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
            self._emit("  /* comptime for: iterable not constant — skipped */")

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
            self._emit("  /* TODO: range() with unexpected argument count */")
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

    def _gen_for_iter(self, node: ForStmt):
        it_type, it_val = self.lower_expr(node.iterable)
        var = node.target if isinstance(node.target, str) else node.target.name

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
        elem = self._elem_of(it_val)
        self._declare_var(var, elem)
        len64 = self._new_temp('int64_t')
        len_t = self._new_temp('int')
        idx_t = self._new_temp('int')
        self._emit(f"  {len64} = mojo_list_len ({it_val});")
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
        suf = TypeLattice.list_suffix(elem)
        if suf == 'double':
            self._emit(f"  {var} = mojo_list_get_double ({it_val}, {idx64});")
        elif suf == 'str':
            self._emit(f"  {var} = mojo_list_get_str ({it_val}, {idx64});")
        else:
            elem64 = self._new_temp('int64_t')
            self._emit(f"  {elem64} = mojo_list_get_int ({it_val}, {idx64});")
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
        self._declare_var(var, 'char *')
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

        node = ci.inner_def
        for pname, ptype in node.params:
            self.var_types[pname] = self._resolve_type(ptype)

        if node.return_type is not None:
            ret_type = self._resolve_type(node.return_type)
        else:
            ret_type = self._infer_return_type(node.body)
        self.func_ret_type = ret_type

        # Build parameter list (env pointer first, then actual params)
        param_strs = []
        if ci.env_struct:
            param_strs.append(f"{ci.env_struct} * _env")
        for pname, ptype in node.params:
            ctype = self._param_ctype(pname, ptype, node)
            self.var_types[pname] = ctype
            param_strs.append(f"{ctype} {pname}")
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

        # Generate C wrapper for main that initializes Python
        if node.name == 'main':
            lines.append("")
            lines.append(f"int main (void) {{")
            lines.append(f"  Py_Initialize ();")
            lines.append(f"  {ret_type} result = {safe} ();")
            lines.append(f"  Py_Finalize ();")
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

        solver = LayoutSolver(self.struct_field_types)
        self._struct_layout = solver.solve(node.params, node.body)

        param_strs = []
        for i, (pname, ptype) in enumerate(node.params):
            if i == 0 and pname == 'self':
                ctype = f"{struct_name} *"
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
        # ── Phase 1: build complete type tables (pre-pass) ────────────────

        # Register struct field types first so _resolve_type works for funcs
        self.struct_field_types = {}
        for s in stmts:
            if isinstance(s, StructDef):
                self.struct_field_types[s.name] = {}
                for field in s.fields:
                    if isinstance(field, VarDecl):
                        self.struct_field_types[s.name][field.name] = _mojo_type(field.type_ann)

        # Register struct constructors as functions returning T *
        self.func_return_types = dict(_RUNTIME_FUNCS)
        for s in stmts:
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

        # Register user function return types
        #   Pass 1: annotated return types (authoritative)
        for s in stmts:
            if isinstance(s, FunctionDef) and s.return_type is not None:
                self.func_return_types[s.name] = self._resolve_type(s.return_type)
        #   Pass 1b: struct method annotated return types
        for s in stmts:
            if isinstance(s, StructDef):
                for m in s.methods:
                    if m.return_type is not None:
                        self.func_return_types[f"{s.name}_{m.name}"] = \
                            self._resolve_type(m.return_type)

        #   Pass 2: infer return types for unannotated functions using
        #           already-seeded func_return_types for callee types
        for s in stmts:
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

        # ── Pass 3: collect closures (nested FunctionDef nodes) ──────────
        self._all_closures: dict = {}  # outer_name → {inner_name → ClosureInfo}
        for s in stmts:
            if not isinstance(s, FunctionDef):
                continue
            # Build outer scope: params + explicitly annotated VarDecl locals
            outer_scope: dict = {}
            for pname, ptype in s.params:
                outer_scope[pname] = self._resolve_type(ptype)
            for stmt in s.body:
                if isinstance(stmt, VarDecl) and stmt.type_ann is not None:
                    outer_scope[stmt.name] = _mojo_type(stmt.type_ann)

            for stmt in s.body:
                if not isinstance(stmt, FunctionDef):
                    continue
                inner     = stmt
                lifted    = f"{s.name}_{inner.name}"
                # Compute free variables: used in inner body minus inner scope
                used      = set()
                for body_node in inner.body:
                    used |= _used_idents_node(body_node)
                inner_declared = ({pn for pn, _ in inner.params}
                                  | _declared_vars_body(inner.body))
                free_globals = set(self.func_return_types.keys())
                free         = used - inner_declared - free_globals
                captures     = [(v, outer_scope[v]) for v in sorted(free)
                                if v in outer_scope]
                env_struct   = f"{lifted}_env" if captures else ""
                ci           = ClosureInfo(lifted, env_struct, captures, inner)
                if s.name not in self._all_closures:
                    self._all_closures[s.name] = {}
                self._all_closures[s.name][inner.name] = ci
                # Register lifted name so callers can resolve its return type
                if inner.return_type is not None:
                    self.func_return_types[lifted] = self._resolve_type(inner.return_type)
                else:
                    # Quick inference for unannotated inner
                    for pname, ptype in inner.params:
                        self.var_types[pname] = self._resolve_type(ptype)
                    self.func_return_types[lifted] = self._infer_return_type(inner.body)
                    self.var_types.clear()

        # ── Phase 2a: generate all function bodies ────────────────────────
        # This pass populates _ptr_helpers_needed and _struct_allocs_needed
        # so the preamble helpers can be emitted before the __GIMPLE bodies.

        func_parts: list[str] = []
        for stmt in stmts:
            if isinstance(stmt, FunctionDef):
                for ci in self._all_closures.get(stmt.name, {}).values():
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
                func_parts.append(self.gen_func(stmt))
                func_parts.append('')
            elif isinstance(stmt, StructDef):
                for m in stmt.methods:
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
            else:
                func_parts.append(f"/* TODO: top-level {type(stmt).__name__} */")

        # ── Phase 2b: assemble final C output ────────────────────────────

        parts = [
            '/* Generated by gimple_codegen.py */',
            '/* Compile with: gcc-mp-15 -fgimple -fsyntax-only file.c */',
            '#include <stdint.h>',
            '#include <stdlib.h>',
            '#include <math.h>',
            '#include <stdio.h>',
            '#include <setjmp.h>',
            '#include <Python.h>',
            '#include "mojo_runtime.h"',
            'void mojo_print(const char *str);',
            'typedef void* MojoFileHandle;',
            'MojoFileHandle mojo_open(const char *filename, const char *mode);',
            'void mojo_close(MojoFileHandle fh);',
            'int64_t mojo_write(MojoFileHandle fh, const char *data, int64_t len);',
            'int64_t mojo_read(MojoFileHandle fh, char *buffer, int64_t len);',
        ]

        # Pointer-at helper functions (plain C — pointer arithmetic forbidden in __GIMPLE)
        for et in sorted(self._ptr_helpers_needed):
            cn = _c_id(et)
            parts.append(
                f"static {et} * _mojo_at_{cn} ({et} * p, int64_t n) {{ return p + n; }}"
            )
        if self._ptr_helpers_needed:
            parts.append('')

        # Struct typedefs
        struct_defs = [s for s in stmts if isinstance(s, StructDef)]
        for sd in struct_defs:
            parts.append(f"typedef struct {sd.name} {{")
            for field in sd.fields:
                if isinstance(field, VarDecl):
                    ft = _mojo_type(field.type_ann)
                    parts.append(f"  {ft} {field.name};")
            parts.append(f"}} {sd.name};")
            parts.append('')

        # Closure env struct typedefs (must precede forward declarations)
        for inner_map in self._all_closures.values():
            for ci in inner_map.values():
                if ci.env_struct:
                    parts.append(f"typedef struct {ci.env_struct} {{")
                    for vname, vtype in ci.captures:
                        parts.append(f"  {vtype} {vname};")
                    parts.append(f"}} {ci.env_struct};")
                    parts.append('')

        # Struct alloc helpers — __GIMPLE OK because StructName * is the return type
        # Emitted before user-function forward decls so no forward decl needed.
        for sn in sorted(self._struct_allocs_needed):
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

        # Extern declarations: imported symbols with full parameter information
        for sym_name in sorted(self.imported_symbols.keys()):
            sym_info = self.imported_symbols[sym_name]

            if 'signature' in sym_info:
                # New format: use full signature with parameters
                signature = sym_info['signature']
                module = sym_info['module']
                parts.append(f"extern {signature};  /* from {module} */")
            else:
                # Legacy format fallback
                ret_type = sym_info.get('return_type', 'int')
                module = sym_info.get('module', '')
                ret_type = self._resolve_type(ret_type) if ret_type != 'unknown' else 'int'
                parts.append(f"extern {ret_type} {_safe_name(sym_name)} (void);  /* from {module} */")

        if self.imported_symbols:
            parts.append('')

        # Forward declarations: free functions
        func_defs = [s for s in stmts if isinstance(s, FunctionDef)]
        for fn in func_defs:
            ret    = self.func_return_types.get(fn.name, 'int')
            ptypes = (', '.join(self._param_ctype(pn, pt, fn) for pn, pt in fn.params)
                      if fn.params else 'void')
            parts.append(f"{ret} {_safe_name(fn.name)} ({ptypes});")

        # Forward declarations: struct methods
        for sd in struct_defs:
            for m in sd.methods:
                ret = self.func_return_types.get(f"{sd.name}_{m.name}",
                                                  self._resolve_type(m.return_type))
                param_ctypes = []
                for i, (pname, ptype) in enumerate(m.params):
                    ct = f"{sd.name} *" if (i == 0 and pname == 'self') else self._resolve_type(ptype)
                    param_ctypes.append(ct)
                ptypes = ', '.join(param_ctypes) if param_ctypes else 'void'
                parts.append(f"{ret} {sd.name}_{_safe_name(m.name)} ({ptypes});")

        if func_defs or struct_defs:
            parts.append('')

        # Forward declarations for lifted closures + env allocator helpers
        for outer_name, inner_map in self._all_closures.items():
            for inner_name, ci in inner_map.items():
                if ci.env_struct:
                    alloc_fn = f"_alloc_{ci.env_struct}"
                    parts.append(f"{ci.env_struct} * {alloc_fn} (void);")
                ret  = self.func_return_types.get(ci.lifted_name, 'int')
                node = ci.inner_def
                ptypes_list = []
                if ci.env_struct:
                    ptypes_list.append(f"{ci.env_struct} *")
                for pn, pt in node.params:
                    ptypes_list.append(self._param_ctype(pn, pt, node))
                ptypes = ', '.join(ptypes_list) if ptypes_list else 'void'
                parts.append(f"{ret} {ci.lifted_name} ({ptypes});")
        if self._all_closures:
            parts.append('')

        # Function bodies (generated in Phase 2a)
        parts.extend(func_parts)

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

def compile_to_gimple(mojo_src: str) -> str:
    """Parse Mojo source and return a C string with __GIMPLE annotations."""
    tokens = tokenize(mojo_src)
    stmts  = Parser(tokens).parse_module()
    return GimpleGen().gen_module(stmts)
