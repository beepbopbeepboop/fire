# Transpiled from Python by APEX py2mojo skill
# CAPABILITY: eval_transitive  # tainted: module-level

"""Generated Mojo compiler — produced by compiler_gen.py from .md spec."""


# TODO: import re — no regex in Mojo stdlib yet; use external crate


struct _MojoPointerBase:
    var _value: AnyType
    def __init__(self, value):
        self._value = value
    def __getitem__(self, _):
        return self._value
    def __setitem__(self, _, v):
        self._value = v

# MRO: Pointer → _MojoPointerBase → object
# MRO: Pointer → _MojoPointerBase → object
struct Pointer(_MojoPointerBase):
    pass

# MRO: OwnedPointer → _MojoPointerBase → object
# MRO: OwnedPointer → _MojoPointerBase → object
struct OwnedPointer(_MojoPointerBase):
    pass

# MRO: ArcPointer → _MojoPointerBase → object
# MRO: ArcPointer → _MojoPointerBase → object
struct ArcPointer(_MojoPointerBase):
    pass

# MRO: UnsafePointer → _MojoPointerBase → object
# MRO: UnsafePointer → _MojoPointerBase → object
struct UnsafePointer(_MojoPointerBase):
    pass


def _python_import(name):
    return _importlib.import_module(name)

def assert_equal(a, b, msg):
    debug_assert(a == b, msg or repr(a) + ' != ' + repr(b))

def assert_true(v, msg):
    debug_assert(v, msg)

def assert_false(v, msg):
    debug_assert(not v, msg)

def assert_not_equal(a, b, msg):
    debug_assert(a != b, msg or repr(a) + ' == ' + repr(b))

def assert_almost_equal(a, b, atol, msg):
    debug_assert(abs((a - b)) <= atol, msg or '|' + repr(a) + '-' + repr(b) + '| > ' + str(atol))

def assert_raises(contains):
    struct _AR:
        fn __enter__(self):
            return self
        fn __exit__(self, exc_type, exc_val, tb) -> Bool capturing:  # inferred
            if exc_type is None:
                raise Error(AssertionError('Expected an exception'))
            if contains and contains not in str(exc_val):
                raise Error(AssertionError('Exception missing ' + repr(contains)))
            return True
    return _AR()

struct TestSuite:
    @staticmethod
    fn discover_tests(fns):
        struct _Suite:
            var _fns: AnyType
            def __init__(self, fns):
                self._fns = fns
            fn run(self):
                passed = failed = 0
                for (name, fn) in self._fns:
                    try:
                        fn()
                        passed += 1
                        print('PASS ' + str(name))
                    except e:
                        failed += 1
                        print('FAIL ' + str(name) + ': ' + str(e))
                print(str(passed) + ' passed, ' + str(failed) + ' failed')
        var _tmp1 = DynamicVector[AnyType]()
        for fn in fns:
            if callable(fn):
                _tmp1.append((fn.__name__, fn))
        return _Suite(_tmp1)


fn struct_field_count(T) -> Int:  # inferred
    return 0

fn struct_field_names(T) -> DynamicVector[?]:  # inferred
    return []

fn struct_field_types(T) -> DynamicVector[?]:  # inferred
    return []

def __struct_field_ref(idx, instance):
    return None

fn conforms_to(T, Trait) -> Bool:  # inferred
    return True

def trait_downcast(Trait, value):
    return value

struct Layout:
    # TODO: **kw — keyword args not supported in Mojo fn
    fn __init__(a: VariadicList[AnyType], self):
        pass
    @staticmethod
    fn row_major(r, c):
        return Layout()
    @staticmethod
    fn col_major(r, c):
        return Layout()

struct LayoutTensor:
    var _data: DynamicVector[?]
    # TODO: **kw — keyword args not supported in Mojo fn
    fn __init__(a: VariadicList[AnyType], self):
        self._data = []
    def __getitem__(self, idx):
        return self._data[idx] if self._data else 0
    def __setitem__(self, idx, v):
        while len(self._data) <= idx if isinstance(idx, int) else 0:
            self._data.append(0)
        self._data[idx if isinstance(idx, int) else 0] = v
    # TODO: **kw — keyword args not supported in Mojo fn
    fn tile(a: VariadicList[AnyType], self):
        return self

def _mojo_alloc(T, n):
    return ([None] * n)

struct DeviceContext:
    def __init__(self, device_id, api):
        pass
    @staticmethod
    fn number_of_devices() -> Int:  # inferred
        return 0
    fn synchronize(self):
        pass
    # TODO: **kw — keyword args not supported in Mojo fn
    fn enqueue_create_buffer(a: VariadicList[AnyType], self):
        return None
    # TODO: **kw — keyword args not supported in Mojo fn
    fn enqueue_create_host_buffer(a: VariadicList[AnyType], self):
        return None
    # TODO: **kw — keyword args not supported in Mojo fn
    fn enqueue_copy(self):
        pass
    # TODO: **kw — keyword args not supported in Mojo fn
    fn compile_function(a: VariadicList[AnyType], self):
        return None
    # TODO: **kw — keyword args not supported in Mojo fn
    fn enqueue_function(a: VariadicList[AnyType], self):
        pass

struct DeviceBuffer:
    pass

struct HostBuffer:
    pass

struct IntLiteral:
    var value: Int

struct FloatLiteral:
    var value: Float64

struct StringLiteral:
    var value: String

struct TstringLiteral:
    var value: String

struct BoolLiteral:
    var value: Bool

struct StringLiteral:
    var value: String

struct EllipsisLiteral:
    pass

struct IdentExpr:
    var name: String

struct CallExpr:
    var func: AnyType
    var args: list

struct BinaryOp:
    var op: String
    var left: AnyType
    var right: AnyType

struct UnaryOp:
    var op: String
    var operand: AnyType

struct TernaryExpr:
    var condition: AnyType
    var then_val: AnyType
    var else_val: AnyType

struct WalrusExpr:
    var name: String
    var value: AnyType

struct MemberExpr:
    var obj: AnyType
    var member: String

struct SubscriptExpr:
    var obj: AnyType
    var index: AnyType

struct SliceExpr:
    var obj: AnyType
    var start: AnyType
    var stop: AnyType
    var step: AnyType

struct ListExpr:
    var elements: list

struct DictExpr:
    var pairs: list

struct SetExpr:
    var elements: list

struct TupleExpr:
    var elements: list

struct Comprehension:
    var kind: String
    var element: AnyType
    var key: AnyType
    var generators: list

struct Generator:
    var target: String
    var iterable: AnyType
    var conditions: list

struct ExprStmt:
    var value: AnyType

struct AssignStmt:
    var target: AnyType
    var value: AnyType

struct AugAssignStmt:
    var target: AnyType
    var op: String
    var value: AnyType

struct VarDecl:
    var name: String
    var type_ann: AnyType
    var value: AnyType

struct MultiAssignStmt:
    var targets: list
    var value: AnyType

struct ImportStmt:
    var module: String
    var alias: AnyType

struct FromImportStmt:
    var module: String
    var names: list
    var wildcard: Bool

struct IfStmt:
    var condition: AnyType
    var then_body: list
    var elifs: list
    var else_body: AnyType

struct WhileStmt:
    var condition: AnyType
    var body: list
    var else_body: AnyType

struct ForStmt:
    var target: AnyType
    var iterable: AnyType
    var body: list
    var else_body: AnyType

struct FunctionDef:
    var name: String
    var params: list
    var return_type: AnyType
    var body: list
    var decorators: list
    var param_convs: dict

struct PassStmt:
    pass

struct ReturnStmt:
    var value: AnyType

struct RaiseStmt:
    var value: AnyType

struct BreakStmt:
    pass

struct ContinueStmt:
    pass

struct AssertStmt:
    var value: AnyType
    var msg: AnyType

struct StructDef:
    var name: String
    var fields: list
    var methods: list
    var decorators: list

struct TraitDef:
    var name: String
    var methods: list
    var decorators: list

struct ExceptHandler:
    var exc_type: AnyType
    var name: AnyType
    var body: list

struct TryStmt:
    var body: list
    var handlers: list
    var else_body: AnyType
    var finally_body: AnyType

struct WithItem:
    var expr: AnyType
    var alias: AnyType

struct WithStmt:
    var items: list
    var body: list

struct ComptimeIfStmt:
    var condition: AnyType
    var then_body: list
    var elifs: list
    var else_body: AnyType

struct ComptimeForStmt:
    var target: String
    var iterable: AnyType
    var body: list

let _KEYWORDS = ['continue', 'assert', 'import', 'except', 'pass', 'True', 'var', 'not', 'read', 'raises', 'or', 'for', 'if', 'return', 'as', 'comptime', 'and', 'out', 'in', 'with', 'deinit', 'finally', 'ref', 'def', 'is', 'mut', 'False', 'struct', 'class', 'fn', 'trait', 'try', 'else', 'raise', 'from', 'elif', 'while', 'break']  # Set → List

let _TOKEN_RE = re.compile('(?P<FLOAT>\\d+\\.\\d*(?:[eE][+-]?\\d+)?|\\.\\d+(?:[eE][+-]?\\d+)?|\\d+[eE][+-]?\\d+)|(?:0x|0X)[0-9a-fA-F]+|(?:0o|0O)[0-7]+|(?:0b|0B)[01]+|(?P<INT>(?:0|[1-9][0-9]*))|(?P<AUGASSIGN>\\*\\*=|//=|<<=|>>=|\\+=|\\-=|\\*=|/=|%=|@=|\\&=|\\|=|\\^=)|(?P<ARROW>->)|(?P<OP>\\*\\*|//|<<|>>|==|!=|<=|>=|:=|\\*|@|/|%|\\+|\\-|\\&|\\^|\\||<|>)|(?P<ASSIGN>=)|(?P<XFER>\\^)|(?P<STRING>\\"\\"\\"[\\s\\S]*?\\"\\"\\"|\\\'\\\'\\\'[\\s\\S]*?\\\'\\\'\\\'|\\"(?:[^\\"\\\\]|\\\\.)*\\"|\\\'(?:[^\\\'\\\\]|\\\\.)*\\\'|`[^`]*`)|(?P<DOT>\\.)|(?P<COLON>:)|(?P<LPAREN>\\()|(?P<RPAREN>\\))|(?P<LBRACKET>\\[)|(?P<RBRACKET>\\])|(?P<LBRACE>\\{)|(?P<RBRACE>\\})|(?P<COMMA>,)|(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)|(?P<WS>[^\\S\\n]+)|(?P<UNK>.)')

let _INDENT_SIZE = 4  # inferred: Int

let _SEP_CHAR = ';'  # inferred: String

let _CMT_CHAR = '#'  # inferred: String

let _HAS_INDENT = True  # inferred: Bool

struct Token:
    var kind: String
    var value: String

fn _strip_inline_comment(s: String) -> String:
    """Remove trailing # comment, respecting quoted strings."""
    var in_str = None
    var i = 0  # inferred: Int
    while i < len(s):
        let c = s[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == in_str:
                let in_str = None
        elif c in ('"', "'"):
            let in_str = c
        elif c == _CMT_CHAR:
            return s[:i]
        i += 1
    return s

fn _split_on_separators(s: String) -> DynamicVector[String]:
    """Split on ';' statement separator, respecting quoted strings."""
    var _tmp2 = ([], [], None)
    let parts = _tmp2[0]
    let buf = _tmp2[1]
    var in_str = _tmp2[2]
    var i = 0  # inferred: Int
    while i < len(s):
        let c = s[i]
        if in_str:
            buf.append(c)
            if c == '\\' and (i + 1) < len(s):
                i += 1
                buf.append(s[i])
            elif c == in_str:
                let in_str = None
        elif c in ('"', "'"):
            let in_str = c
            buf.append(c)
        elif c == _SEP_CHAR:
            parts.append(''.join(buf))
            let buf = []  # inferred: DynamicVector[?]
        else:
            buf.append(c)
        i += 1
    parts.append(''.join(buf))
    return parts

fn tokenize(src: String) -> DynamicVector[Token]:
    """Tokenize with layout rules derived from the .md spec:
        - Indentation (4 spaces) → INDENT/DEDENT
        - ';' → statement separator
        - '#' → end-of-line comment
        - Multi-line statements use indentation (no backslash continuation)"""
    # TODO: import re — no regex in Mojo stdlib yet; use external crate
    let string_cache = {}  # inferred: Dict[?, ?]
    let string_idx = [0]  # inferred: DynamicVector[?]
    def replace_multiline_strings(src) capturing:
        fn repl(m) -> String capturing:  # inferred
            let placeholder = '__MOJO_STR_' + str(string_idx[0]) + '__'  # inferred: String
            string_cache[placeholder] = m.group(0)
            string_idx[0] += 1
            return placeholder
        var src = re.sub('"""[\\s\\S]*?"""', repl, src)
        var src = re.sub("'''[\\s\\S]*?'''", repl, src)
        return src
    var src = replace_multiline_strings(src)
    let joined = src.splitlines()
    let out: DynamicVector[Token] = []
    let stack = [0]  # inferred: DynamicVector[?]
    var paren_depth = 0  # inferred: Int
    for line in joined:
        let expanded = line.expandtabs(_INDENT_SIZE)
        let raw_content = expanded.lstrip()
        if not raw_content or raw_content.startswith(_CMT_CHAR):
            continue
        let content = _strip_inline_comment(raw_content).rstrip()
        if not content:
            continue
        let indent = (len(expanded) - len(raw_content))  # inferred: Int
        let sub_stmts = _split_on_separators(content)
        for (stmt_idx, stmt) in enumerate(sub_stmts):
            let stmt = stmt.strip()
            if not stmt:
                continue
            if stmt_idx == 0 and paren_depth == 0:
                if indent > stack[-1]:
                    stack.append(indent)
                    out.append(Token('INDENT', ''))
                else:
                    while indent < stack[-1]:
                        stack.pop()
                        out.append(Token('DEDENT', ''))
            for m in _TOKEN_RE.finditer(stmt):
                var kind = m.lastgroup or 'INT'  # inferred: Bool
                var val = m.group()
                if kind in ('WS', 'UNK', 'XFER'):
                    continue
                if kind == 'NAME' and val in _KEYWORDS:
                    let kind = 'KW'  # inferred: String
                if kind == 'NAME' and val in string_cache:
                    let val = string_cache[val]
                    let kind = 'STRING'  # inferred: String
                if kind in ('LPAREN', 'LBRACKET', 'LBRACE') or val in ('(', '[', '{'):
                    paren_depth += 1
                elif kind in ('RPAREN', 'RBRACKET', 'RBRACE') or val in (')', ']', '}'):
                    let paren_depth = max(0, (paren_depth - 1))
                out.append(Token(kind, val))
            if paren_depth == 0:
                out.append(Token('NEWLINE', ''))
    while len(stack) > 1:
        stack.pop()
        out.append(Token('DEDENT', ''))
    out.append(Token('EOF', ''))
    return out

let _PREC = {'**': 2, '*': 4, '@': 4, '/': 4, '//': 4, '%': 4, '+': 5, '-': 5, '<<': 6, '>>': 6, '&': 7, '^': 8, '|': 9, '==': 10, '!=': 10, '<': 10, '<=': 10, '>': 10, '>=': 10, ':=': 15}  # inferred: Dict[?, ?]

let _KW_PREC = {'in': 10, 'is': 10, 'not': 11, 'and': 12, 'or': 13}  # inferred: Dict[?, ?]

struct Parser:
    var _tok: DynamicVector[Token]
    var _pos: Int
    var _pending_decs: DynamicVector[?]
    fn __init__(self, tokens: DynamicVector[Token]):
        self._tok = tokens
        self._pos = 0
        self._pending_decs = []
    fn _peek(self, offset: Int) -> Token:
        let i = (self._pos + offset)
        return self._tok[i] if i < len(self._tok) else Token('EOF', '')
    fn _advance(self) -> Token:
        let t = self._tok[self._pos]
        if self._pos < (len(self._tok) - 1):
            self._pos += 1
        return t
    fn _expect(self, kind: String, value: String) -> Token:
        let t = self._peek()
        if t.kind != kind:
            raise Error(SyntaxError('Expected ' + str(kind) + ' got ' + str(t.kind) + '(' + repr(t.value) + ')'))
        if value and t.value != value:
            raise Error(SyntaxError('Expected ' + repr(value) + ' got ' + repr(t.value)))
        return self._advance()
    fn _skip_newlines(self):
        while self._peek().kind == 'NEWLINE':
            self._advance()
    fn _at_end(self) -> Bool:
        return self._peek().kind == 'EOF'
    fn _is_kw(w: VariadicList[AnyType], self) -> Bool:
        let t = self._peek()
        return t.kind == 'KW' and t.value in w
    fn parse_module(self) -> list:
        let stmts = []  # inferred: DynamicVector[?]
        self._skip_newlines()
        while not self._at_end():
            stmts.append(self._parse_stmt())
            self._skip_newlines()
        return stmts
    fn _parse_block(self) -> list:
        self._expect('NEWLINE')
        self._skip_newlines()
        self._expect('INDENT')
        let stmts = []  # inferred: DynamicVector[?]
        self._skip_newlines()
        while self._peek().kind not in ('DEDENT', 'EOF'):
            stmts.append(self._parse_stmt())
            self._skip_newlines()
        self._expect('DEDENT')
        return stmts
    fn _parse_stmt(self):
        var t = self._peek()
        if t.kind == 'KW':
            if t.value == 'import':
                return self._parse_import()
            if t.value == 'from':
                return self._parse_from_import()
            if t.value == 'var':
                return self._parse_var_decl()
            if t.value == 'if':
                return self._parse_if()
            if t.value == 'while':
                return self._parse_while()
            if t.value == 'for':
                return self._parse_for()
            if t.value in ('def', 'fn'):
                self._advance()
                return self._parse_funcdef([])
            if t.value in ('struct', 'class'):
                return self._parse_struct()
            if t.value == 'trait':
                return self._parse_trait()
            if t.value == 'try':
                return self._parse_try()
            if t.value == 'with':
                return self._parse_with()
            if t.value == 'comptime':
                return self._parse_comptime()
            if t.value == 'pass':
                return self._parse_pass()
            if t.value == 'return':
                return self._parse_return()
            if t.value == 'raise':
                return self._parse_raise()
            if t.value == 'break':
                return self._parse_break()
            if t.value == 'continue':
                return self._parse_continue()
            if t.value == 'assert':
                return self._parse_assert()
        if t.kind == 'NAME' and t.value.startswith('__mlir'):
            self._advance()
            if self._peek().kind == 'LPAREN':
                self._advance()
                if self._peek().kind == 'STRING':
                    self._advance()
                self._advance()
            while self._peek().kind not in ('NEWLINE', 'DEDENT', 'EOF'):
                self._advance()
            return PassStmt()
        if t.kind == 'NAME' and t.value in ('__extension', '__mlir_region'):
            self._advance()
            let name = self._expect('NAME').value
            if self._peek().kind == 'LPAREN':
                self._advance()
                let depth = 1  # inferred: Int
                while depth > 0:
                    let t_inner = self._advance()
                    if t_inner.kind == 'LPAREN':
                        depth += 1
                    elif t_inner.kind == 'RPAREN':
                        depth -= 1
            self._expect('COLON')
            if self._peek().kind == 'NEWLINE':
                let body = self._parse_block()
            else:
                while self._peek().kind not in ('NEWLINE', 'DEDENT', 'EOF'):
                    self._advance()
            return PassStmt()
        if t.kind == 'OP' and t.value == '@':
            let decs = []  # inferred: DynamicVector[?]
            while self._peek().kind == 'OP' and self._peek().value == '@':
                self._advance()
                let dec_name = self._expect('NAME').value
                if self._peek().kind == 'LPAREN':
                    self._advance()
                    let depth = 1  # inferred: Int
                    while depth > 0:
                        let t = self._peek()
                        if t.kind == 'LPAREN':
                            depth += 1
                        elif t.kind == 'RPAREN':
                            depth -= 1
                        self._advance()
                decs.append(dec_name)
                self._skip_newlines()
            let kw = self._peek()
            if kw.kind == 'KW' and kw.value == 'struct':
                self._pending_decs = decs
                return self._parse_struct()
            if kw.kind == 'KW' and kw.value in ('def', 'fn'):
                self._advance()
                return self._parse_funcdef(decs)
            self._expect('KW', 'def or fn')
            return self._parse_funcdef(decs)
        let expr = self._parse_expr(0)
        if self._peek().kind == 'COMMA':
            let targets = [expr]  # inferred: DynamicVector[?]
            while self._peek().kind == 'COMMA':
                self._advance()
                if self._peek().kind == 'ASSIGN':
                    break
                targets.append(self._parse_expr(0))
            if self._peek().kind == 'ASSIGN':
                self._advance()
                let val = self._parse_expr(0)
                let tuple_target = TupleExpr(elements=targets)
                return AssignStmt(target=tuple_target, value=val)
            return ExprStmt(TupleExpr(elements=targets))
        if self._peek().kind == 'ASSIGN':
            self._advance()
            let val = self._parse_expr(0)
            if self._peek().kind == 'ASSIGN':
                let targets = [expr]  # inferred: DynamicVector[?]
                while True:
                    if self._peek().kind != 'ASSIGN':
                        break
                    targets.append(val)
                    self._advance()
                    let val = self._parse_expr(0)
                return MultiAssignStmt(targets=targets, value=val)
            return AssignStmt(target=expr, value=val)
        if self._peek().kind == 'AUGASSIGN':
            let op = self._advance().value
            let val = self._parse_expr(0)
            return AugAssignStmt(target=expr, op=op, value=val)
        self._skip_newlines()
        return ExprStmt(expr)
    fn _parse_import(self):
        self._expect('KW', 'import')
        var module = self._expect('NAME').value
        while self._peek().kind == 'DOT':
            self._advance()
            module += ('.' + self._expect('NAME').value)
        var alias = None
        if self._is_kw('as'):
            self._advance()
            let alias = self._expect('NAME').value
        return ImportStmt(module=module, alias=alias)
    fn _parse_from_import(self):
        self._expect('KW', 'from')
        var module = ''  # inferred: String
        while self._peek().kind == 'DOT':
            self._advance()
            module += '.'
        if self._peek().kind == 'NAME':
            module += self._advance().value
            while self._peek().kind == 'DOT':
                self._advance()
                module += ('.' + self._expect('NAME').value)
        elif not module:
            self._expect('NAME')
        self._expect('KW', 'import')
        if self._peek().kind == 'OP' and self._peek().value == '*':
            self._advance()
            return FromImportStmt(module=module, names=[], wildcard=True)
        var paren_import = False  # inferred: Bool
        if self._peek().kind == 'LPAREN':
            self._advance()
            let paren_import = True  # inferred: Bool
        let names = []  # inferred: DynamicVector[?]
        if paren_import:
            while self._peek().kind == 'NEWLINE':
                self._advance()
        if self._peek().kind == 'RPAREN':
            self._advance()
            return FromImportStmt(module=module, names=names, wildcard=False)
        var name = self._expect('NAME').value
        var alias = None
        if self._is_kw('as'):
            self._advance()
            let alias = self._expect('NAME').value
        names.append((name, alias))
        while True:
            if paren_import:
                while self._peek().kind == 'NEWLINE':
                    self._advance()
            if self._peek().kind == 'RPAREN':
                self._advance()
                break
            if self._peek().kind != 'COMMA':
                break
            self._advance()
            if paren_import:
                while self._peek().kind == 'NEWLINE':
                    self._advance()
            if self._peek().kind == 'RPAREN':
                self._advance()
                break
            let name = self._expect('NAME').value
            let alias = None
            if self._is_kw('as'):
                self._advance()
                let alias = self._expect('NAME').value
            names.append((name, alias))
        return FromImportStmt(module=module, names=names, wildcard=False)
    fn _parse_var_decl(self):
        self._expect('KW', 'var')
        let name = self._expect('NAME').value
        if self._peek().kind == 'COMMA':
            let names = [name]  # inferred: DynamicVector[?]
            while self._peek().kind == 'COMMA':
                self._advance()
                if self._peek().kind == 'NAME':
                    names.append(self._expect('NAME').value)
                elif self._peek().kind == 'ASSIGN':
                    break
                else:
                    break
            if self._peek().kind == 'ASSIGN':
                self._advance()
                let value = self._parse_expr(0)
                return VarDecl(name=','.join(names), type_ann=None, value=value)
            else:
                return VarDecl(name=','.join(names), type_ann=None, value=None)
        var type_ann = None
        if self._peek().kind == 'COLON':
            self._advance()
            let type_ann = self._parse_type_ann()
        var value = None
        if self._peek().kind == 'ASSIGN':
            self._advance()
            let value = self._parse_expr(0)
        return VarDecl(name=name, type_ann=type_ann, value=value)
    fn _parse_if(self):
        self._expect('KW', 'if')
        let cond = self._parse_expr(0)
        self._expect('COLON')
        let body = self._parse_block()
        var _tmp3 = ([], None)
        let elifs = _tmp3[0]
        let else_body = _tmp3[1]
        while self._is_kw('elif'):
            self._advance()
            let ec = self._parse_expr(0)
            self._expect('COLON')
            let eb = self._parse_block()
            elifs.append((ec, eb))
        if self._is_kw('else'):
            self._advance()
            self._expect('COLON')
            let else_body = self._parse_block()
        return IfStmt(condition=cond, then_body=body, elifs=elifs, else_body=else_body)
    fn _parse_while(self):
        self._expect('KW', 'while')
        let cond = self._parse_expr(0)
        self._expect('COLON')
        let body = self._parse_block()
        var else_body = None
        if self._is_kw('else'):
            self._advance()
            self._expect('COLON')
            let else_body = self._parse_block()
        return WhileStmt(condition=cond, body=body, else_body=else_body)
    fn _parse_for(self):
        self._expect('KW', 'for')
        if self._is_kw(*self._CONV_KWS):
            self._advance()
        let target = self._expect('NAME').value
        self._expect('KW', 'in')
        let iterable = self._parse_expr(0)
        self._expect('COLON')
        let body = self._parse_block()
        var else_body = None
        if self._is_kw('else'):
            self._advance()
            self._expect('COLON')
            let else_body = self._parse_block()
        return ForStmt(target=target, iterable=iterable, body=body, else_body=else_body)
    let _CONV_KWS = ['mut', 'var', 'read', 'deinit', 'out', 'ref']  # Set → List
    fn _parse_funcdef(self, decorators: DynamicVector[?]  # inferred):  # inferred
        if decorators is None:
            let decorators = []  # inferred: DynamicVector[?]
        let name = self._expect('NAME').value
        if self._peek().kind == 'LBRACKET':
            self._skip_bracketed()
        self._expect('LPAREN')
        let params = []  # inferred: DynamicVector[?]
        let param_convs = {}  # inferred: Dict[?, ?]
        while self._peek().kind != 'RPAREN':
            while self._peek().kind in ('NEWLINE', 'INDENT', 'DEDENT'):
                self._advance()
            if self._peek().kind == 'RPAREN':
                break
            let conv = None
            while self._peek().kind == 'KW' and self._peek().value in self._CONV_KWS:
                let conv = self._advance().value
            if self._peek().kind == 'OP' and self._peek().value == '/':
                self._advance()
                if self._peek().kind == 'COMMA':
                    self._advance()
                if self._peek().kind == 'RPAREN':
                    break
            if self._peek().kind == 'OP' and self._peek().value == '*':
                self._advance()
                if self._peek().kind == 'LBRACKET':
                    self._skip_bracketed()
                while self._peek().kind == 'KW' and self._peek().value in self._CONV_KWS:
                    let conv = self._advance().value
                if self._peek().kind == 'NAME':
                    let pname = self._expect('NAME').value
                    let ptype = None
                    if self._peek().kind == 'COLON':
                        self._advance()
                        let ptype = self._parse_type_ann()
                    if self._peek().kind == 'ASSIGN':
                        self._advance()
                        self._parse_expr(0)
                    params.append((pname, ptype))
                    if conv is not None:
                        param_convs[pname] = conv
                    if self._peek().kind == 'COMMA':
                        self._advance()
                    while self._peek().kind in ('NEWLINE', 'INDENT', 'DEDENT'):
                        self._advance()
                    continue
                elif self._peek().kind == 'COMMA':
                    self._advance()
                if self._peek().kind == 'RPAREN':
                    break
                continue
            if self._peek().kind == 'RPAREN':
                break
            if self._peek().kind == 'LBRACKET':
                self._skip_bracketed()
            let pname = self._expect('NAME').value
            let ptype = None
            if self._peek().kind == 'COLON':
                self._advance()
                let ptype = self._parse_type_ann()
            if self._peek().kind == 'ASSIGN':
                self._advance()
                self._parse_expr(0)
            params.append((pname, ptype))
            if conv is not None:
                param_convs[pname] = conv
            if self._peek().kind == 'COMMA':
                self._advance()
            while self._peek().kind in ('NEWLINE', 'INDENT', 'DEDENT'):
                self._advance()
        self._expect('RPAREN')
        if self._is_kw('raises'):
            self._advance()
            while self._peek().kind not in ('COLON', 'NEWLINE', 'EOF', 'ARROW'):
                if self._peek().kind in ('NAME', 'DOT', 'STRING', 'COMMA'):
                    self._advance()
                elif self._peek().kind == 'LBRACKET':
                    self._skip_bracketed()
                else:
                    break
        while self._peek().kind == 'NAME' and self._peek().value in ('unified', 'register_passable'):
            self._advance()
        var ret = None
        if self._peek().kind == 'ARROW':
            self._advance()
            if self._is_kw('ref'):
                self._advance()
                if self._peek().kind == 'LBRACKET':
                    self._skip_bracketed()
            let ret = self._parse_type_ann()
            while self._peek().kind == 'NAME' and self._peek().value in ('unified', 'register_passable'):
                self._advance()
        if self._peek().kind == 'NAME' and self._peek().value == 'where':
            self._advance()
            while self._peek().kind not in ('COLON', 'NEWLINE', 'EOF'):
                self._advance()
        if self._peek().kind == 'LBRACE':
            self._advance()
            let depth = 1  # inferred: Int
            while depth > 0:
                let t = self._advance()
                if t.kind == 'LBRACE':
                    depth += 1
                elif t.kind == 'RBRACE':
                    depth -= 1
                elif t.kind == 'EOF':
                    break
        self._expect('COLON')
        let body = self._parse_block()
        return FunctionDef(name=name, params=params, return_type=ret, body=body, decorators=decorators, param_convs=param_convs)
    fn _parse_struct(self):
        let kw = self._peek()
        if kw.kind == 'KW' and kw.value in ('struct', 'class'):
            self._advance()
        else:
            self._expect('KW', 'struct')
        let name = self._expect('NAME').value
        if self._peek().kind == 'LBRACKET':
            self._skip_bracketed()
        if self._peek().kind == 'LPAREN':
            self._advance()
            let depth = 1  # inferred: Int
            while depth > 0:
                let t = self._advance()
                if t.kind == 'LPAREN':
                    depth += 1
                elif t.kind == 'RPAREN':
                    depth -= 1
                elif t.kind == 'EOF':
                    break
        self._expect('COLON')
        let body = self._parse_block()
        var fields = DynamicVector[AnyType]()
        for s in body:
            if isinstance(s, VarDecl):
                fields.append(s)
        var methods = DynamicVector[AnyType]()
        for s in body:
            if isinstance(s, FunctionDef):
                methods.append(s)
        let decs = getattr(self, '_pending_decs', [])
        self._pending_decs = []
        return StructDef(name=name, fields=fields, methods=methods, decorators=decs)
    fn _parse_trait(self):
        self._expect('KW', 'trait')
        let name = self._expect('NAME').value
        if self._peek().kind == 'LBRACKET':
            self._skip_bracketed()
        if self._peek().kind == 'LPAREN':
            self._advance()
            let depth = 1  # inferred: Int
            while depth > 0:
                let t = self._advance()
                if t.kind == 'LPAREN':
                    depth += 1
                elif t.kind == 'RPAREN':
                    depth -= 1
                elif t.kind == 'EOF':
                    break
        self._expect('COLON')
        let body = self._parse_block()
        var methods = DynamicVector[AnyType]()
        for s in body:
            if isinstance(s, FunctionDef):
                methods.append(s)
        return TraitDef(name=name, methods=methods)
    fn _parse_try(self):
        self._expect('KW', 'try')
        self._expect('COLON')
        let body = self._parse_block()
        let handlers = []  # inferred: DynamicVector[?]
        while self._is_kw('except'):
            self._advance()
            var _tmp4 = (None, None)
            let exc_type = _tmp4[0]
            let exc_name = _tmp4[1]
            if self._peek().kind == 'NAME':
                let exc_type = self._advance().value
                if self._is_kw('as'):
                    self._advance()
                    let exc_name = self._expect('NAME').value
            self._expect('COLON')
            handlers.append(ExceptHandler(exc_type=exc_type, name=exc_name, body=self._parse_block()))
        var else_body = None
        if self._is_kw('else'):
            self._advance()
            self._expect('COLON')
            let else_body = self._parse_block()
        var finally_body = None
        if self._is_kw('finally'):
            self._advance()
            self._expect('COLON')
            let finally_body = self._parse_block()
        return TryStmt(body=body, handlers=handlers, else_body=else_body, finally_body=finally_body)
    fn _parse_with(self):
        self._expect('KW', 'with')
        let items = []  # inferred: DynamicVector[?]
        var expr = self._parse_expr(0)
        var alias = None
        if self._is_kw('as'):
            self._advance()
            let alias = self._expect('NAME').value
        items.append(WithItem(expr=expr, alias=alias))
        while self._peek().kind == 'COMMA':
            self._advance()
            let expr = self._parse_expr(0)
            let alias = None
            if self._is_kw('as'):
                self._advance()
                let alias = self._expect('NAME').value
            items.append(WithItem(expr=expr, alias=alias))
        self._expect('COLON')
        return WithStmt(items=items, body=self._parse_block())
    fn _parse_comptime(self):
        self._expect('KW', 'comptime')
        let t = self._peek()
        if t.value == 'if':
            return self._parse_comptime_if()
        if t.value == 'for':
            return self._parse_comptime_for()
        if t.value == 'assert':
            return self._parse_assert()
        if t.kind == 'NAME':
            let lhs = IdentExpr(self._advance().value)
            if self._peek().kind == 'LBRACKET':
                self._skip_bracketed()
            if self._peek().kind == 'COLON':
                self._advance()
                self._parse_type_ann()
            if self._peek().kind == 'ASSIGN':
                self._advance()
                return AssignStmt(target=lhs, value=self._parse_expr(0))
            return ExprStmt(lhs)
        raise Error(SyntaxError('Unexpected token after comptime: ' + repr(t.value)))
    fn _parse_comptime_if(self):
        self._expect('KW', 'if')
        let cond = self._parse_expr(0)
        self._expect('COLON')
        let body = self._parse_block()
        var _tmp5 = ([], None)
        let elifs = _tmp5[0]
        let else_body = _tmp5[1]
        while self._is_kw('elif'):
            self._advance()
            let ec = self._parse_expr(0)
            self._expect('COLON')
            let eb = self._parse_block()
            elifs.append((ec, eb))
        if self._is_kw('else'):
            self._advance()
            self._expect('COLON')
            let else_body = self._parse_block()
        return ComptimeIfStmt(condition=cond, then_body=body, elifs=elifs, else_body=else_body)
    fn _parse_comptime_for(self):
        self._expect('KW', 'for')
        let target = self._expect('NAME').value
        self._expect('KW', 'in')
        let iterable = self._parse_expr(0)
        self._expect('COLON')
        return ComptimeForStmt(target=target, iterable=iterable, body=self._parse_block())
    fn _parse_pass(self):
        self._expect('KW', 'pass')
        return PassStmt()
    fn _parse_return(self):
        self._expect('KW', 'return')
        if self._peek().kind in ('NEWLINE', 'EOF', 'DEDENT'):
            return ReturnStmt(value=None)
        return ReturnStmt(value=self._parse_expr(0))
    fn _parse_raise(self):
        self._expect('KW', 'raise')
        if self._peek().kind in ('NEWLINE', 'EOF', 'DEDENT'):
            return RaiseStmt(value=None)
        return RaiseStmt(value=self._parse_expr(0))
    fn _parse_break(self):
        self._expect('KW', 'break')
        return BreakStmt()
    fn _parse_continue(self):
        self._expect('KW', 'continue')
        return ContinueStmt()
    fn _parse_assert(self):
        self._expect('KW', 'assert')
        let value = self._parse_expr(0)
        var msg = None
        if self._peek().kind == 'COMMA':
            self._advance()
            let msg = self._parse_expr(0)
        return AssertStmt(value=value, msg=msg)
    fn _parse_expr(self, min_prec: Int):
        var left = self._parse_unary()
        while True:
            let t = self._peek()
            if t.kind == 'OP':
                let prec = _PREC.get(t.value, -1)
                if prec < min_prec:
                    break
                let op = self._advance().value
                let right = self._parse_expr((prec + 1))
                if op == ':=' and isinstance(left, IdentExpr):
                    let left = WalrusExpr(name=left.name, value=right)
                else:
                    let left = BinaryOp(op=op, left=left, right=right)
            elif t.kind == 'KW' and t.value in _KW_PREC:
                let prec = _KW_PREC[t.value]
                if prec < min_prec:
                    break
                let op = self._advance().value
                if op == 'not' and self._is_kw('in'):
                    self._advance()
                    let op = 'not in'  # inferred: String
                elif op == 'is' and self._is_kw('not'):
                    self._advance()
                    let op = 'is not'  # inferred: String
                let right = self._parse_expr((prec + 1))
                let left = BinaryOp(op=op, left=left, right=right)
            elif t.kind == 'KW' and t.value == 'if' and min_prec == 0:
                self._advance()
                let cond = self._parse_expr(1)
                self._expect('KW', 'else')
                let els = self._parse_expr(0)
                let left = TernaryExpr(condition=cond, then_val=left, else_val=els)
            else:
                break
        return left
    fn _parse_unary(self):
        let t = self._peek()
        if t.kind == 'OP' and t.value in ('-', '+', '~'):
            self._advance()
            return UnaryOp(op=t.value, operand=self._parse_unary())
        if t.kind == 'KW' and t.value == 'not':
            self._advance()
            return UnaryOp(op='not', operand=self._parse_unary())
        return self._parse_postfix()
    fn _parse_postfix(self):
        var expr = self._parse_primary()
        while True:
            let t = self._peek()
            if t.kind == 'DOT':
                self._advance()
                if self._peek().kind == 'STRING' and self._peek().value.startswith('`'):
                    let member = self._advance().value
                elif self._peek().kind in ('NAME', 'KW'):
                    let member = self._advance().value
                else:
                    let member = self._expect('NAME').value
                let expr = MemberExpr(obj=expr, member=member)
            elif t.kind == 'LBRACKET':
                self._advance()
                if self._peek().kind == 'RBRACKET':
                    let idx = IntLiteral(value='0')
                    self._advance()
                    let expr = SubscriptExpr(obj=expr, index=idx)
                elif self._peek().kind == 'OP' and self._peek().value == '*':
                    self._advance()
                    self._parse_expr(0)
                    while self._peek().kind == 'COMMA':
                        self._advance()
                        if self._peek().kind == 'RBRACKET':
                            break
                        if self._peek().kind == 'OP' and self._peek().value == '*':
                            self._advance()
                            self._parse_expr(0)
                        elif self._peek().kind in ('NAME', 'KW') and self._peek(1).kind == 'ASSIGN':
                            self._advance()
                            self._advance()
                            self._parse_expr(0)
                        else:
                            self._parse_expr(0)
                        if self._peek().kind != 'COMMA' and self._peek().kind != 'RBRACKET':
                            break
                    self._expect('RBRACKET')
                    let expr = SubscriptExpr(obj=expr, index=IntLiteral(value='0'))
                elif self._peek().kind in ('NAME', 'KW') and self._peek(1).kind == 'ASSIGN':
                    while self._peek().kind != 'RBRACKET' and self._peek().kind != 'EOF':
                        if self._peek().kind in ('NAME', 'KW'):
                            self._advance()
                            if self._peek().kind == 'ASSIGN':
                                self._advance()
                            self._parse_expr(0)
                        if self._peek().kind == 'COMMA':
                            self._advance()
                        elif self._peek().kind != 'RBRACKET':
                            break
                    self._expect('RBRACKET')
                    let expr = SubscriptExpr(obj=expr, index=IntLiteral(value='0'))
                else:
                    let idx = self._parse_expr(0)
                    if self._peek().kind == 'COMMA':
                        let indices = [idx]  # inferred: DynamicVector[?]
                        while self._peek().kind == 'COMMA':
                            self._advance()
                            if self._peek().kind == 'RBRACKET':
                                break
                            if self._peek().kind == 'OP' and self._peek().value == '*':
                                self._advance()
                                indices.append(self._parse_expr(0))
                            elif self._peek().kind in ('NAME', 'KW') and self._peek(1).kind == 'ASSIGN':
                                while self._peek().kind != 'RBRACKET' and self._peek().kind != 'EOF':
                                    if self._peek().kind in ('NAME', 'KW'):
                                        self._advance()
                                        if self._peek().kind == 'ASSIGN':
                                            self._advance()
                                        self._parse_expr(0)
                                    if self._peek().kind == 'COMMA':
                                        self._advance()
                                    elif self._peek().kind != 'RBRACKET':
                                        break
                                break
                            else:
                                indices.append(self._parse_expr(0))
                        let idx = TupleExpr(elements=indices)
                    if self._peek().kind == 'COLON':
                        self._advance()
                        let stop = None if self._peek().kind == 'RBRACKET' else self._parse_expr(0)
                        let expr = SliceExpr(obj=expr, start=idx, stop=stop)
                    else:
                        let expr = SubscriptExpr(obj=expr, index=idx)
                    self._expect('RBRACKET')
            elif t.kind == 'LPAREN':
                self._advance()
                let args = []  # inferred: DynamicVector[?]
                while self._peek().kind != 'RPAREN':
                    if self._peek().kind == 'OP' and self._peek().value == '**':
                        self._advance()
                        args.append(self._parse_expr(0))
                    elif self._peek().kind == 'OP' and self._peek().value == '*':
                        self._advance()
                        args.append(self._parse_expr(0))
                    elif self._peek().kind == 'NAME' and self._peek(1).kind == 'ASSIGN':
                        self._advance()
                        self._advance()
                        args.append(self._parse_expr(0))
                    else:
                        args.append(self._parse_expr(0))
                    if self._peek().kind == 'COMMA':
                        self._advance()
                self._expect('RPAREN')
                let expr = CallExpr(func=expr, args=args)
            elif t.kind == 'OP' and t.value == '^':
                let next_t = self._peek(1)
                let is_postfix = next_t.kind in ('NEWLINE', 'DEDENT', 'EOF', 'COMMA', 'RPAREN', 'RBRACKET', 'COLON', 'SEMICOLON')  # inferred: Bool
                if is_postfix:
                    self._advance()
                    let expr = UnaryOp(op='^', operand=expr)
                else:
                    break
            else:
                break
        return expr
    fn _parse_primary(self):
        let t = self._peek()
        if t.kind == 'INT':
            self._advance()
            return IntLiteral(int(t.value, 0))
        if t.kind == 'FLOAT':
            self._advance()
            return FloatLiteral(float(t.value))
        if t.kind == 'KW' and t.value in ('True', 'False'):
            self._advance()
            return BoolLiteral(t.value == 'True')
        if t.kind == 'STRING':
            let val = self._advance().value
            while self._peek().kind == 'STRING':
                val += self._advance().value
            return StringLiteral(val)
        if t.kind == 'LBRACKET':
            return self._parse_list_or_compr()
        if t.kind == 'LBRACE':
            return self._parse_dict_or_set()
        if t.kind == 'LPAREN':
            self._advance()
            if self._peek().kind == 'RPAREN':
                self._advance()
                return TupleExpr(elements=[])
            let first = self._parse_expr(0)
            if self._peek().kind == 'COMMA':
                let elems = [first]  # inferred: DynamicVector[?]
                while self._peek().kind == 'COMMA':
                    self._advance()
                    if self._peek().kind == 'RPAREN':
                        break
                    elems.append(self._parse_expr(0))
                self._expect('RPAREN')
                return TupleExpr(elements=elems)
            self._expect('RPAREN')
            return first
        if t.kind in ('NAME', 'KW'):
            self._advance()
            return IdentExpr(t.value)
        if t.kind == 'DOT' and self._peek(1).kind == 'DOT' and self._peek(2).kind == 'DOT':
            self._advance()
            self._advance()
            self._advance()
            return EllipsisLiteral()
        raise Error(SyntaxError('Unexpected ' + str(t.kind) + '(' + repr(t.value) + ')'))
    fn _parse_list_or_compr(self):
        self._expect('LBRACKET')
        if self._peek().kind == 'RBRACKET':
            self._advance()
            return ListExpr(elements=[])
        let first = self._parse_expr(0)
        if self._is_kw('for'):
            let gen = self._parse_generator()
            self._expect('RBRACKET')
            return Comprehension(kind='list', element=first, generators=[gen])
        let elems = [first]  # inferred: DynamicVector[?]
        while self._peek().kind == 'COMMA':
            self._advance()
            if self._peek().kind == 'RBRACKET':
                break
            elems.append(self._parse_expr(0))
        self._expect('RBRACKET')
        return ListExpr(elements=elems)
    fn _parse_dict_or_set(self):
        self._expect('LBRACE')
        if self._peek().kind == 'RBRACE':
            self._advance()
            return DictExpr(pairs=[])
        let first = self._parse_expr(0)
        if self._peek().kind == 'ASSIGN':
            self._advance()
            self._parse_expr(0)
            while self._peek().kind == 'COMMA':
                self._advance()
                if self._peek().kind == 'RBRACE':
                    break
                self._parse_expr(0)
                if self._peek().kind == 'ASSIGN':
                    self._advance()
                self._parse_expr(0)
            self._expect('RBRACE')
            return DictExpr(pairs=[])
        if self._peek().kind == 'COLON':
            self._advance()
            let val = self._parse_expr(0)
            if self._is_kw('for'):
                let gen = self._parse_generator()
                self._expect('RBRACE')
                return Comprehension(kind='dict', element=first, key=val, generators=[gen])
            let pairs = [(first, val)]  # inferred: DynamicVector[?]
            while self._peek().kind == 'COMMA':
                self._advance()
                if self._peek().kind == 'RBRACE':
                    break
                let k = self._parse_expr(0)
                self._expect('COLON')
                let v = self._parse_expr(0)
                pairs.append((k, v))
            self._expect('RBRACE')
            return DictExpr(pairs=pairs)
        if self._is_kw('for'):
            let gen = self._parse_generator()
            self._expect('RBRACE')
            return Comprehension(kind='set', element=first, generators=[gen])
        let elems = [first]  # inferred: DynamicVector[?]
        while self._peek().kind == 'COMMA':
            self._advance()
            if self._peek().kind == 'RBRACE':
                break
            elems.append(self._parse_expr(0))
        self._expect('RBRACE')
        return SetExpr(elements=elems)
    fn _parse_generator(self):
        self._expect('KW', 'for')
        let target = self._expect('NAME').value
        self._expect('KW', 'in')
        let iterable = self._parse_expr(1)
        let conditions = []  # inferred: DynamicVector[?]
        while self._is_kw('if'):
            self._advance()
            conditions.append(self._parse_expr(1))
        return Generator(target=target, iterable=iterable, conditions=conditions)
    fn _skip_bracketed(self):
        """Consume a balanced [...] block."""
        self._expect('LBRACKET')
        var depth = 1  # inferred: Int
        while depth > 0:
            let t = self._advance()
            if t.kind == 'LBRACKET':
                depth += 1
            elif t.kind == 'RBRACKET':
                depth -= 1
            elif t.kind == 'EOF':
                break
    fn _parse_type_ann(self) -> String:
        """Parse a type annotation: Name or Name[TypeArgs] or Name.Member.Type[Args] or `backtick_type`."""
        var prefix = ''  # inferred: String
        if self._peek().kind == 'OP' and self._peek().value == '*':
            let prefix = '*'  # inferred: String
            self._advance()
        if self._is_kw('ref') or self._is_kw('mut'):
            self._advance()
            if self._peek().kind == 'LBRACKET':
                self._skip_bracketed()
        if self._peek().kind == 'STRING' and self._peek().value.startswith('`'):
            return (prefix + self._advance().value)
        if self._peek().kind == 'LPAREN':
            let name = (prefix + '(')
            self._advance()
            let depth = 1  # inferred: Int
            while depth > 0:
                let t = self._advance()
                if t.kind == 'LPAREN':
                    depth += 1
                    name += '('
                elif t.kind == 'RPAREN':
                    depth -= 1
                    if depth > 0:
                        name += ')'
                elif t.kind == 'EOF':
                    break
                else:
                    name += t.value
            name += ')'
            return name
        var name = (prefix + self._expect('NAME').value)
        while self._peek().kind == 'DOT':
            self._advance()
            if self._peek().kind == 'STRING' and self._peek().value.startswith('`'):
                name += ('.' + self._advance().value)
            elif self._peek().kind in ('NAME', 'KW'):
                name += ('.' + self._advance().value)
            else:
                name += ('.' + self._expect('NAME').value)
        if self._peek().kind == 'LPAREN':
            self._advance()
            name += '('
            let depth = 1  # inferred: Int
            while depth > 0:
                let t = self._advance()
                if t.kind == 'LPAREN':
                    depth += 1
                    name += '('
                elif t.kind == 'RPAREN':
                    depth -= 1
                    if depth > 0:
                        name += ')'
                elif t.kind == 'EOF':
                    break
                else:
                    name += t.value
            name += ')'
            while self._peek().kind == 'DOT':
                self._advance()
                if self._peek().kind == 'STRING' and self._peek().value.startswith('`'):
                    name += ('.' + self._advance().value)
                else:
                    name += ('.' + self._expect('NAME').value)
        if self._peek().kind != 'LBRACKET':
            return name
        let parts = [name]  # inferred: DynamicVector[?]
        while self._peek().kind == 'LBRACKET':
            self._advance()
            parts.append('[')
            let depth = 1  # inferred: Int
            while depth > 0:
                let t = self._advance()
                if t.kind == 'LBRACKET':
                    depth += 1
                    parts.append('[')
                elif t.kind == 'RBRACKET':
                    depth -= 1
                    if depth > 0:
                        parts.append(']')
                elif t.kind == 'EOF':
                    break
                else:
                    parts.append(t.value)
            parts.append(']')
        return ''.join(parts)

fn emit_module(stmts: list, indent: Int) -> String:
    var _tmp6 = DynamicVector[AnyType]()
    for s in stmts:
        _tmp6.append(emit(s, indent))
    return '\n'.join(_tmp6)

def emit(node, indent: Int) -> String:
    let pad = ('    ' * indent)
    if isinstance(node, IntLiteral):
        return str(node.value)
    if isinstance(node, FloatLiteral):
        return repr(node.value)
    if isinstance(node, BoolLiteral):
        return str(node.value)
    if isinstance(node, StringLiteral):
        return node.value
    if isinstance(node, EllipsisLiteral):
        return '...'
    if isinstance(node, IdentExpr):
        return node.name
    if isinstance(node, CallExpr):
        let f = emit(node.func) if not isinstance(node.func, str) else node.func
        var _tmp7 = DynamicVector[AnyType]()
        for a in node.args:
            _tmp7.append(emit(a))
        let args = ', '.join(_tmp7)
        return str(f) + '(' + str(args) + ')'
    if isinstance(node, BinaryOp):
        return '(' + str(emit(node.left)) + ' ' + str(node.op) + ' ' + str(emit(node.right)) + ')'
    if isinstance(node, UnaryOp):
        return '(' + str(node.op) + ' ' + str(emit(node.operand)) + ')'
    if isinstance(node, TernaryExpr):
        return '(' + str(emit(node.then_val)) + ' if ' + str(emit(node.condition)) + ' else ' + str(emit(node.else_val)) + ')'
    if isinstance(node, MemberExpr):
        return str(emit(node.obj)) + '.' + str(node.member)
    if isinstance(node, SubscriptExpr):
        return str(emit(node.obj)) + '[' + str(emit(node.index)) + ']'
    if isinstance(node, SliceExpr):
        let start = emit(node.start) if node.start is not None else ''
        let stop = emit(node.stop) if node.stop is not None else ''
        return str(emit(node.obj)) + '[' + str(start) + ':' + str(stop) + ']'
    if isinstance(node, ListExpr):
        var _tmp8 = DynamicVector[AnyType]()
        for e in node.elements:
            _tmp8.append(emit(e))
        return (('[' + ', '.join(_tmp8)) + ']')
    if isinstance(node, DictExpr):
        var _tmp9 = DynamicVector[AnyType]()
        for (k, v) in node.pairs:
            _tmp9.append(str(emit(k)) + ': ' + str(emit(v)))
        return (('{' + ', '.join(_tmp9)) + '}')
    if isinstance(node, SetExpr):
        var _tmp10 = DynamicVector[AnyType]()
        for e in node.elements:
            _tmp10.append(emit(e))
        return (('{' + ', '.join(_tmp10)) + '}')
    if isinstance(node, TupleExpr):
        if not node.elements:
            return '()'
        var _tmp11 = DynamicVector[AnyType]()
        for e in node.elements:
            _tmp11.append(emit(e))
        return ((('(' + ', '.join(_tmp11)) + ',' if len(node.elements) == 1 else '') + ')')
    if isinstance(node, Comprehension):
        var _tmp12 = DynamicVector[AnyType]()
        var _tmp13 = DynamicVector[AnyType]()
        for c in g.conditions:
            _tmp13.append(' if ' + str(emit(c)))
        for g in node.generators:
            _tmp12.append(('for ' + str(g.target) + ' in ' + str(emit(g.iterable)) + ''.join(_tmp13)))
        let gens = ' '.join(_tmp12)
        if node.kind == 'list':
            return '[' + str(emit(node.element)) + ' ' + str(gens) + ']'
        if node.kind == 'set':
            return (('{' + str(emit(node.element)) + ' ' + str(gens)) + '}')
        if node.kind == 'dict':
            return (('{' + str(emit(node.element)) + ': ' + str(emit(node.key)) + ' ' + str(gens)) + '}')
        return '(' + str(emit(node.element)) + ' ' + str(gens) + ')'
    if isinstance(node, ExprStmt):
        return str(pad) + str(emit(node.value))
    if isinstance(node, AssignStmt):
        return str(pad) + str(emit(node.target)) + ' = ' + str(emit(node.value))
    if isinstance(node, AugAssignStmt):
        return str(pad) + str(emit(node.target)) + ' ' + str(node.op) + ' ' + str(emit(node.value))
    if isinstance(node, VarDecl):
        let ann = ': ' + str(node.type_ann) if node.type_ann else ''
        let val = ' = ' + str(emit(node.value)) if node.value is not None else ''
        return str(pad) + str(node.name) + str(ann) + str(val)
    if isinstance(node, MultiAssignStmt):
        var _tmp14 = DynamicVector[AnyType]()
        for t in node.targets:
            _tmp14.append(emit(t))
        return (((str(pad) + ' = '.join(_tmp14)) + ' = ') + emit(node.value))
    if isinstance(node, ImportStmt):
        let alias = ' as ' + str(node.alias) if node.alias else ''
        return str(pad) + 'import ' + str(node.module) + str(alias)
    if isinstance(node, FromImportStmt):
        if node.wildcard:
            return str(pad) + 'from ' + str(node.module) + ' import *'
        var _tmp15 = DynamicVector[AnyType]()
        for (n, a) in node.names:
            _tmp15.append((n + ' as ' + str(a) if a else ''))
        let names = ', '.join(_tmp15)
        return str(pad) + 'from ' + str(node.module) + ' import ' + str(names)
    if isinstance(node, IfStmt):
        let out = [str(pad) + 'if ' + str(emit(node.condition)) + ':']  # inferred: DynamicVector[?]
        var _tmp16 = DynamicVector[AnyType]()
        for s in node.then_body:
            _tmp16.append(emit(s, (indent + 1)))
        out += _tmp16
        for (ec, eb) in node.elifs:
            out.append(str(pad) + 'elif ' + str(emit(ec)) + ':')
            var _tmp17 = DynamicVector[AnyType]()
            for s in eb:
                _tmp17.append(emit(s, (indent + 1)))
            out += _tmp17
        if node.else_body is not None:
            out.append(str(pad) + 'else:')
            var _tmp18 = DynamicVector[AnyType]()
            for s in node.else_body:
                _tmp18.append(emit(s, (indent + 1)))
            out += _tmp18
        return '\n'.join(out)
    if isinstance(node, WhileStmt):
        let out = [str(pad) + 'while ' + str(emit(node.condition)) + ':']  # inferred: DynamicVector[?]
        var _tmp19 = DynamicVector[AnyType]()
        for s in node.body:
            _tmp19.append(emit(s, (indent + 1)))
        out += _tmp19
        if node.else_body is not None:
            out.append(str(pad) + 'else:')
            var _tmp20 = DynamicVector[AnyType]()
            for s in node.else_body:
                _tmp20.append(emit(s, (indent + 1)))
            out += _tmp20
        return '\n'.join(out)
    if isinstance(node, ForStmt):
        let out = [str(pad) + 'for ' + str(emit(node.target) if not isinstance(node.target, str) else node.target) + ' in ' + str(emit(node.iterable)) + ':']  # inferred: DynamicVector[?]
        var _tmp21 = DynamicVector[AnyType]()
        for s in node.body:
            _tmp21.append(emit(s, (indent + 1)))
        out += _tmp21
        if node.else_body is not None:
            out.append(str(pad) + 'else:')
            var _tmp22 = DynamicVector[AnyType]()
            for s in node.else_body:
                _tmp22.append(emit(s, (indent + 1)))
            out += _tmp22
        return '\n'.join(out)
    if isinstance(node, FunctionDef):
        fn _fmt_param(n, t) -> String:  # inferred
            let ann = ': ' + str(t) if t else ''
            return str(n) + str(ann)
        var _tmp23 = DynamicVector[AnyType]()
        for (n, t) in node.params:
            _tmp23.append(_fmt_param(n, t))
        let params = ', '.join(_tmp23)
        let ret = ' -> ' + str(node.return_type) if node.return_type else ''
        var out = DynamicVector[AnyType]()
        for d in node.decorators:
            out.append(str(pad) + '@' + str(d))
        out.append(str(pad) + 'def ' + str(node.name) + '(' + str(params) + ')' + str(ret) + ':')
        var _tmp24 = DynamicVector[AnyType]()
        for s in node.body:
            _tmp24.append(emit(s, (indent + 1)))
        out += _tmp24
        return '\n'.join(out)
    if isinstance(node, PassStmt):
        return str(pad) + 'pass'
    if isinstance(node, ReturnStmt):
        let val = ' ' + str(emit(node.value)) if node.value is not None else ''
        return str(pad) + 'return' + str(val)
    if isinstance(node, RaiseStmt):
        let val = ' ' + str(emit(node.value)) if node.value is not None else ''
        return str(pad) + 'raise' + str(val)
    if isinstance(node, BreakStmt):
        return str(pad) + 'break'
    if isinstance(node, ContinueStmt):
        return str(pad) + 'continue'
    if isinstance(node, AssertStmt):
        let val = ' ' + str(emit(node.value)) if node.value is not None else ''
        let msg_s = ', ' + str(emit(node.msg)) if node.msg is not None else ''
        return str(pad) + 'assert' + str(val) + str(msg_s)
    if isinstance(node, TryStmt):
        let out = [str(pad) + 'try:']  # inferred: DynamicVector[?]
        var _tmp25 = DynamicVector[AnyType]()
        for s in node.body:
            _tmp25.append(emit(s, (indent + 1)))
        out += _tmp25
        for h in node.handlers:
            let exc = ' ' + str(h.exc_type) if h.exc_type else ''
            let name = ' as ' + str(h.name) if h.name else ''
            out.append(str(pad) + 'except' + str(exc) + str(name) + ':')
            var _tmp26 = DynamicVector[AnyType]()
            for s in h.body:
                _tmp26.append(emit(s, (indent + 1)))
            out += _tmp26
        if node.else_body:
            out.append(str(pad) + 'else:')
            var _tmp27 = DynamicVector[AnyType]()
            for s in node.else_body:
                _tmp27.append(emit(s, (indent + 1)))
            out += _tmp27
        if node.finally_body:
            out.append(str(pad) + 'finally:')
            var _tmp28 = DynamicVector[AnyType]()
            for s in node.finally_body:
                _tmp28.append(emit(s, (indent + 1)))
            out += _tmp28
        return '\n'.join(out)
    if isinstance(node, WithStmt):
        var _tmp29 = DynamicVector[AnyType]()
        for i in node.items:
            _tmp29.append(str(emit(i.expr)) + ' as ' + str(i.alias) if i.alias else emit(i.expr))
        let items_str = ', '.join(_tmp29)
        let out = [str(pad) + 'with ' + str(items_str) + ':']  # inferred: DynamicVector[?]
        var _tmp30 = DynamicVector[AnyType]()
        for s in node.body:
            _tmp30.append(emit(s, (indent + 1)))
        out += _tmp30
        return '\n'.join(out)
    if isinstance(node, ComptimeIfStmt):
        let out = [str(pad) + 'if ' + str(emit(node.condition)) + ':  # comptime']  # inferred: DynamicVector[?]
        var _tmp31 = DynamicVector[AnyType]()
        for s in node.then_body:
            _tmp31.append(emit(s, (indent + 1)))
        out += _tmp31
        for (ec, eb) in node.elifs:
            out.append(str(pad) + 'elif ' + str(emit(ec)) + ':')
            var _tmp32 = DynamicVector[AnyType]()
            for s in eb:
                _tmp32.append(emit(s, (indent + 1)))
            out += _tmp32
        if node.else_body is not None:
            out.append(str(pad) + 'else:')
            var _tmp33 = DynamicVector[AnyType]()
            for s in node.else_body:
                _tmp33.append(emit(s, (indent + 1)))
            out += _tmp33
        return '\n'.join(out)
    if isinstance(node, ComptimeForStmt):
        let out = [str(pad) + 'for ' + str(node.target) + ' in ' + str(emit(node.iterable)) + ':  # comptime']  # inferred: DynamicVector[?]
        var _tmp34 = DynamicVector[AnyType]()
        for s in node.body:
            _tmp34.append(emit(s, (indent + 1)))
        out += _tmp34
        return '\n'.join(out)
    if isinstance(node, StructDef):
        let _OWN_DECS = ['Copyable', 'Movable', 'ImplicitlyCopyable', 'ExplicitlyCopyable', 'Writable', 'Sized', 'Boolable', 'Stringable', 'Hashable', 'AnyType']  # Set → List
        var _tmp35 = DynamicVector[AnyType]()
        for d in node.decorators:
            _tmp35.append(d == 'fieldwise_init')
        let has_init = any(_tmp35)
        var ext_decs = DynamicVector[AnyType]()
        for d in node.decorators:
            if d not in _OWN_DECS and d != 'fieldwise_init':
                ext_decs.append(d)
        var out = DynamicVector[AnyType]()
        for d in ext_decs:
            out.append(str(pad) + '@' + str(d))
        out.append(str(pad) + 'class ' + str(node.name) + ':')
        let body = []  # inferred: DynamicVector[?]
        if has_init and node.fields:
            var _tmp36 = DynamicVector[AnyType]()
            for f in node.fields:
                _tmp36.append(f.name)
            let ps = ', '.join(_tmp36)
            body.append(str(pad) + '    def __init__(self, ' + str(ps) + '):')
            for f in node.fields:
                body.append(str(pad) + '        self.' + str(f.name) + ' = ' + str(f.name))
        elif node.fields:
            for f in node.fields:
                let ann = ': ' + str(f.type_ann) if f.type_ann else ''
                let val = ' = ' + str(emit(f.value)) if f.value is not None else ' = None'
                body.append(str(pad) + '    ' + str(f.name) + str(ann) + str(val))
        for m in node.methods:
            body.append(emit(m, (indent + 1)))
        out += body if body else [str(pad) + '    pass']
        return '\n'.join(out)
    if isinstance(node, TraitDef):
        let out = [str(pad) + 'class ' + str(node.name) + ':  # trait']  # inferred: DynamicVector[?]
        let body = []  # inferred: DynamicVector[?]
        for m in node.methods:
            let is_abs = not m.body or len(m.body) == 1 and isinstance(m.body[0], PassStmt) or len(m.body) == 1 and isinstance(m.body[0], ExprStmt) and isinstance(m.body[0].value, EllipsisLiteral)  # inferred: Bool
            if is_abs:
                body.append(str(pad) + '    @abstractmethod')
            body.append(emit(m, (indent + 1)))
        out += body if body else [str(pad) + '    pass']
        return '\n'.join(out)
    raise Error(TypeError('Cannot emit ' + str(type(node).__name__)))

fn compile(src: String) -> String:
    let tokens = tokenize(src)
    let stmts = Parser(tokens).parse_module()
    return emit_module(stmts)

if __name__ == '__main__':
    from sys import argv, exit, stderr
    let src = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1]).read()
    print(compile(src))
