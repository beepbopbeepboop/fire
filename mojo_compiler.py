"""Generated Mojo compiler — produced by compiler_gen.py from .md spec."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# ── Mojo pointer type shims ────────────────────────────────────────
class _MojoPointerBase:
    def __init__(self, value=None): self._value = value
    def __getitem__(self, _): return self._value
    def __setitem__(self, _, v): self._value = v

class Pointer(_MojoPointerBase): pass
class OwnedPointer(_MojoPointerBase): pass
class ArcPointer(_MojoPointerBase): pass
class UnsafePointer(_MojoPointerBase): pass

# ── Mojo Python interop helpers ────────────────────────────────────
import importlib as _importlib
def _python_import(name): return _importlib.import_module(name)

# ── Mojo testing helpers ───────────────────────────────────────────
def assert_equal(a, b, msg=""): assert a == b, msg or f"{a!r} != {b!r}"
def assert_true(v, msg=""): assert v, msg
def assert_false(v, msg=""): assert not v, msg
def assert_not_equal(a, b, msg=""): assert a != b, msg or f"{a!r} == {b!r}"
def assert_almost_equal(a, b, atol=1e-6, msg=""): assert abs(a - b) <= atol, msg or f"|{a!r}-{b!r}| > {atol}"
def assert_raises(contains=""):
    import contextlib
    class _AR:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, tb):
            if exc_type is None: raise AssertionError("Expected an exception")
            if contains and contains not in str(exc_val): raise AssertionError(f"Exception missing {contains!r}")
            return True
    return _AR()

# ── TestSuite helper ───────────────────────────────────────────────
class TestSuite:
    @staticmethod
    def discover_tests(fns=()):
        class _Suite:
            def __init__(self, fns): self._fns = fns
            def run(self):
                passed = failed = 0
                for name, fn in self._fns:
                    try: fn(); passed += 1; print(f"PASS {name}")
                    except Exception as e: failed += 1; print(f"FAIL {name}: {e}")
                print(f"{passed} passed, {failed} failed")
        return _Suite([(fn.__name__, fn) for fn in fns if callable(fn)])

from abc import abstractmethod

# ── Mojo reflection shims ──────────────────────────────────────────
def struct_field_count(T): return 0
def struct_field_names(T): return []
def struct_field_types(T): return []
def __struct_field_ref(idx, instance): return None
def conforms_to(T, Trait): return True
def trait_downcast(Trait, value): return value

# ── Mojo LayoutTensor / Layout shims ───────────────────────────────
class Layout:
    def __init__(self, *a, **kw): pass
    @staticmethod
    def row_major(r, c): return Layout()
    @staticmethod
    def col_major(r, c): return Layout()

class LayoutTensor:
    def __init__(self, *a, **kw): self._data = []
    def __getitem__(self, idx): return self._data[idx] if self._data else 0
    def __setitem__(self, idx, v):
        while len(self._data) <= (idx if isinstance(idx, int) else 0): self._data.append(0)
        self._data[idx if isinstance(idx, int) else 0] = v
    def tile(self, *a, **kw): return self

# ── Additional UnsafePointer methods ──────────────────────────────
def _mojo_alloc(T, n): return [None] * n  # alloc[T](n)

# ── TODO: Mojo GPU (full codegen) ─────────────────────────────────
# TODO: Full GPU codegen not implemented
class DeviceContext:
    def __init__(self, device_id=0, api=""): pass
    @staticmethod
    def number_of_devices(): return 0
    def synchronize(self): pass
    def enqueue_create_buffer(self, *a, **kw): return None  # TODO
    def enqueue_create_host_buffer(self, *a, **kw): return None  # TODO
    def enqueue_copy(self, **kw): pass  # TODO
    def compile_function(self, *a, **kw): return None  # TODO
    def enqueue_function(self, *a, **kw): pass  # TODO

class DeviceBuffer:
    pass  # TODO: full DeviceBuffer impl

class HostBuffer:
    pass  # TODO: full HostBuffer impl


# ── AST nodes ──────────────────────────────────────────────────────
@dataclass
class IntLiteral:
    value: int

@dataclass
class FloatLiteral:
    value: float

@dataclass
class StringLiteral:
    value: str

@dataclass
class TstringLiteral:
    value: str

@dataclass
class BoolLiteral:
    value: bool

@dataclass
class StringLiteral:
    value: str

@dataclass
class EllipsisLiteral:
    pass

@dataclass
class IdentExpr:
    name: str

@dataclass
class CallExpr:
    func: object
    args: list

@dataclass
class BinaryOp:
    op: str
    left: object
    right: object

@dataclass
class UnaryOp:
    op: str
    operand: object

@dataclass
class TernaryExpr:
    condition: object
    then_val: object
    else_val: object

@dataclass
class WalrusExpr:
    name: str
    value: object

@dataclass
class MemberExpr:
    obj: object
    member: str

@dataclass
class SubscriptExpr:
    obj: object
    index: object

@dataclass
class SliceExpr:
    obj: object
    start: object
    stop: object
    step: object = None

@dataclass
class ListExpr:
    elements: list

@dataclass
class DictExpr:
    pairs: list  # [(key_expr, val_expr), ...]

@dataclass
class SetExpr:
    elements: list

@dataclass
class TupleExpr:
    elements: list

@dataclass
class Comprehension:
    kind: str     # list / set / dict
    element: object
    key: object = None     # dict key
    generators: list = field(default_factory=list)

@dataclass
class Generator:
    target: str
    iterable: object
    conditions: list = field(default_factory=list)

@dataclass
class ExprStmt:
    value: object

@dataclass
class AssignStmt:
    target: object
    value: object

@dataclass
class AugAssignStmt:
    target: object
    op: str
    value: object

@dataclass
class VarDecl:
    name: str
    type_ann: object
    value: object

@dataclass
class MultiAssignStmt:
    targets: list
    value: object

@dataclass
class ImportStmt:
    module: str
    alias: object  # str|None

@dataclass
class FromImportStmt:
    module: str
    names: list      # [(name, alias|None), ...]
    wildcard: bool = False

@dataclass
class IfStmt:
    condition: object
    then_body: list
    elifs: list
    else_body: object

@dataclass
class WhileStmt:
    condition: object
    body: list
    else_body: object = None

@dataclass
class ForStmt:
    target: object
    iterable: object
    body: list
    else_body: object = None

@dataclass
class FunctionDef:
    name: str
    params: list      # [(name, type|None), ...]
    return_type: object
    body: list
    decorators: list = field(default_factory=list)
    param_convs: dict = field(default_factory=dict)  # name -> convention str|None

@dataclass
class PassStmt:
    pass

@dataclass
class ReturnStmt:
    value: object  # None if bare

@dataclass
class RaiseStmt:
    value: object  # None if bare

@dataclass
class BreakStmt:
    pass

@dataclass
class ContinueStmt:
    pass

@dataclass
class AssertStmt:
    value: object  # None if bare
    msg: object = None

@dataclass
class StructDef:
    name: str
    fields: list
    methods: list
    decorators: list = field(default_factory=list)

@dataclass
class TraitDef:
    name: str
    methods: list
    decorators: list = field(default_factory=list)

@dataclass
class ExceptHandler:
    exc_type: object
    name: object
    body: list

@dataclass
class TryStmt:
    body: list
    handlers: list
    else_body: object
    finally_body: object

@dataclass
class WithItem:
    expr: object
    alias: object

@dataclass
class WithStmt:
    items: list
    body: list

@dataclass
class ComptimeIfStmt:
    condition: object
    then_body: list
    elifs: list
    else_body: object

@dataclass
class ComptimeForStmt:
    target: str
    iterable: object
    body: list


# ── Lexer ──────────────────────────────────────────────────────────
_KEYWORDS = {'if', 'with', 'read', 'ref', 'fn', 'from', 'def', 'finally', 'for', 'raise', 'while', 'break', 'True', 'comptime', 'or', 'in', 'and', 'let', 'continue', 'try', 'except', 'not', 'elif', 'raises', 'out', 'is', 'assert', 'mut', 'struct', 'trait', 'class', 'pass', 'deinit', 'else', 'as', 'False', 'import', 'var', 'return'}

_TOKEN_RE = re.compile(r'(?P<FLOAT>\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)|(?:0x|0X)[0-9a-fA-F]+|(?:0o|0O)[0-7]+|(?:0b|0B)[01]+|(?P<INT>(?:0|[1-9][0-9]*))|(?P<AUGASSIGN>\*\*=|//=|<<=|>>=|\+=|\-=|\*=|/=|%=|@=|\&=|\|=|\^=)|(?P<ARROW>->)|(?P<OP>\*\*|//|<<|>>|==|!=|<=|>=|:=|\*|@|/|%|\+|\-|\&|\^|\||<|>)|(?P<ASSIGN>=)|(?P<XFER>\^)|(?P<STRING>\"\"\"[\s\S]*?\"\"\"|\'\'\'[\s\S]*?\'\'\'|\"(?:[^\"\\]|\\.)*\"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`)|(?P<DOT>\.)|(?P<COLON>:)|(?P<LPAREN>\()|(?P<RPAREN>\))|(?P<LBRACKET>\[)|(?P<RBRACKET>\])|(?P<LBRACE>\{)|(?P<RBRACE>\})|(?P<COMMA>,)|(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)|(?P<WS>[^\S\n]+)|(?P<UNK>.)')
_INDENT_SIZE    = 4
_SEP_CHAR       = ';'
_CMT_CHAR       = '#'
_HAS_INDENT     = True

@dataclass
class Token:
    kind: str
    value: str

# ── Layout helpers ──────────────────────────────────────────────────
def _strip_inline_comment(s: str) -> str:
    """Remove trailing # comment, respecting quoted strings."""
    in_str = None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\" : i += 2; continue
            if c == in_str: in_str = None
        elif c in ('"', "'"):
            in_str = c
        elif c == _CMT_CHAR:
            return s[:i]
        i += 1
    return s

def _split_on_separators(s: str) -> list[str]:
    """Split on ';' statement separator, respecting quoted strings."""
    parts, buf, in_str = [], [], None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            buf.append(c)
            if c == "\\" and i + 1 < len(s):
                i += 1; buf.append(s[i])
            elif c == in_str:
                in_str = None
        elif c in ('"', "'"):
            in_str = c; buf.append(c)
        elif c == _SEP_CHAR:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts

def tokenize(src: str) -> list[Token]:
    """Tokenize with layout rules derived from the .md spec:
        - Indentation (4 spaces) → INDENT/DEDENT
        - ';' → statement separator
        - '#' → end-of-line comment
        - Multi-line statements use indentation (no backslash continuation)"""
    import re
    string_cache = {}
    string_idx = [0]
    def replace_multiline_strings(src):
        def repl(m):
            placeholder = f"__MOJO_STR_{string_idx[0]}__"
            string_cache[placeholder] = m.group(0)
            string_idx[0] += 1
            return placeholder
        # Match triple-quoted strings (both """ and ''')
        src = re.sub(r'"""[\s\S]*?"""', repl, src)
        src = re.sub(r"'''[\s\S]*?'''", repl, src)
        return src
    src = replace_multiline_strings(src)
    joined = src.splitlines()
    # Phase 2: lex line by line
    out: list[Token] = []
    stack = [0]
    paren_depth = 0  # Track (), [], {} nesting to suppress INDENT/DEDENT inside
    for line in joined:
        expanded = line.expandtabs(_INDENT_SIZE)
        raw_content = expanded.lstrip()
        if not raw_content or raw_content.startswith(_CMT_CHAR): continue
        content = _strip_inline_comment(raw_content).rstrip()
        if not content: continue
        indent = len(expanded) - len(raw_content)
        sub_stmts = _split_on_separators(content)
        for stmt_idx, stmt in enumerate(sub_stmts):
            stmt = stmt.strip()
            if not stmt: continue
            # Only emit INDENT/DEDENT when at paren depth 0
            if stmt_idx == 0 and paren_depth == 0:
                if indent > stack[-1]:
                    stack.append(indent)
                    out.append(Token("INDENT", ""))
                else:
                    while indent < stack[-1]:
                        stack.pop()
                        out.append(Token("DEDENT", ""))
            for m in _TOKEN_RE.finditer(stmt):
                kind = m.lastgroup or "INT"
                val  = m.group()
                if kind in ("WS", "UNK", "XFER"): continue
                if kind == "NAME" and val in _KEYWORDS: kind = "KW"
                # Restore multi-line strings from cache
                if kind == "NAME" and val in string_cache:
                    val = string_cache[val]
                    kind = "STRING"
                # Track paren/bracket/brace depth to suppress INDENT/NEWLINE inside
                if kind in ("LPAREN", "LBRACKET", "LBRACE") or val in ("(", "[", "{"): paren_depth += 1
                elif kind in ("RPAREN", "RBRACKET", "RBRACE") or val in (")", "]", "}"): paren_depth = max(0, paren_depth - 1)
                out.append(Token(kind, val))
            # Only emit NEWLINE when paren depth is 0 (not inside brackets/parens)
            if paren_depth == 0:
                out.append(Token("NEWLINE", ""))
    while len(stack) > 1:
        stack.pop()
        out.append(Token("DEDENT", ""))
    out.append(Token("EOF", ""))
    return out

# ── Parser ─────────────────────────────────────────────────────────
_PREC    = {
    '**': 2,
    '*': 4,
    '@': 4,
    '/': 4,
    '//': 4,
    '%': 4,
    '+': 5,
    '-': 5,
    '<<': 6,
    '>>': 6,
    '&': 7,
    '^': 8,
    '|': 9,
    '==': 10,
    '!=': 10,
    '<': 10,
    '<=': 10,
    '>': 10,
    '>=': 10,
    ':=': 15,
}
_KW_PREC = {
    'in': 10,
    'is': 10,
    'not': 11,
    'and': 12,
    'or': 13,
}

class Parser:
    def __init__(self, tokens: list[Token]):
        self._tok = tokens
        self._pos = 0
        self._pending_decs = []  # decorators awaiting next struct/trait

    def _peek(self, offset: int = 0) -> Token:
        i = self._pos + offset
        return self._tok[i] if i < len(self._tok) else Token("EOF", "")

    def _advance(self) -> Token:
        t = self._tok[self._pos]
        if self._pos < len(self._tok) - 1: self._pos += 1
        return t

    def _expect(self, kind: str, value: str = None) -> Token:
        t = self._peek()
        if t.kind != kind:
            raise SyntaxError(f"Expected {kind} got {t.kind}({t.value!r})")
        if value and t.value != value:
            raise SyntaxError(f"Expected {value!r} got {t.value!r}")
        return self._advance()

    def _skip_newlines(self):
        while self._peek().kind == "NEWLINE": self._advance()

    def _at_end(self) -> bool: return self._peek().kind == "EOF"
    def _is_kw(self, *w) -> bool:
        t = self._peek(); return t.kind == "KW" and t.value in w

    def parse_module(self) -> list:
        stmts = []
        self._skip_newlines()
        while not self._at_end():
            stmts.append(self._parse_stmt())
            self._skip_newlines()
        return stmts

    def _parse_block(self) -> list:
        self._expect("NEWLINE")
        self._skip_newlines()
        self._expect("INDENT")
        stmts = []
        self._skip_newlines()
        while self._peek().kind not in ("DEDENT", "EOF"):
            stmts.append(self._parse_stmt())
            self._skip_newlines()
        self._expect("DEDENT")
        return stmts

    def _parse_stmt(self):
        t = self._peek()
        if t.kind == "KW":
            if t.value == "import": return self._parse_import()
            if t.value == "from":   return self._parse_from_import()
            if t.value == 'var': return self._parse_var_decl()
            if t.value == 'if': return self._parse_if()
            if t.value == 'while': return self._parse_while()
            if t.value == 'for': return self._parse_for()
            if t.value in ("def", "fn"):
                # fn(  →  variable named "fn" being called; treat as expression
                if t.value == "fn" and self._peek(1).kind == "LPAREN":
                    pass  # fall through to expression statement
                else:
                    self._advance(); return self._parse_funcdef([])
            if t.value in ("struct", "class"): return self._parse_struct()
            if t.value == "trait": return self._parse_trait()
            if t.value == "try": return self._parse_try()
            if t.value == "with": return self._parse_with()
            if t.value == "comptime": return self._parse_comptime()
            if t.value == 'pass': return self._parse_pass()
            if t.value == 'return': return self._parse_return()
            if t.value == 'raise': return self._parse_raise()
            if t.value == 'break': return self._parse_break()
            if t.value == 'continue': return self._parse_continue()
            if t.value == 'assert': return self._parse_assert()
        # Handle __mlir_op, __mlir_attr and other MLIR/special forms
        if t.kind == "NAME" and t.value.startswith("__mlir"):
            self._advance()  # skip __mlir_op/__mlir_attr/etc
            # Skip string literal if present
            if self._peek().kind == "LPAREN":
                self._advance()  # skip (
                if self._peek().kind == "STRING":
                    self._advance()  # skip string
                self._advance()  # skip )
            # Skip the rest of the line (result type annotation, etc)
            while self._peek().kind not in ("NEWLINE", "DEDENT", "EOF"):
                self._advance()
            return PassStmt()
        # Handle __extension Type: methods and __mlir_region name(...): body
        if t.kind == "NAME" and t.value in ("__extension", "__mlir_region"):
            self._advance()  # skip __extension or __mlir_region
            name = self._expect("NAME").value
            # Skip any function call arguments if present
            if self._peek().kind == "LPAREN":
                self._advance()  # (
                depth = 1
                while depth > 0:
                    t_inner = self._advance()
                    if t_inner.kind == "LPAREN": depth += 1
                    elif t_inner.kind == "RPAREN": depth -= 1
            self._expect("COLON")
            # Check if there is a body on this line or on following lines
            if self._peek().kind == "NEWLINE":
                # Indented block follows
                body = self._parse_block()
            else:
                # Body on same line, skip until newline
                while self._peek().kind not in ("NEWLINE", "DEDENT", "EOF"):
                    self._advance()
            # Treat as a pass statement
            return PassStmt()
        if t.kind == "OP" and t.value == "@":
            decs = []
            while self._peek().kind == "OP" and self._peek().value == "@":
                self._advance()
                dec_name = self._expect("NAME").value
                # Handle decorator with arguments: @decorator(args)
                if self._peek().kind == "LPAREN":
                    self._advance()  # skip LPAREN
                    depth = 1
                    while depth > 0:
                        t = self._peek()
                        if t.kind == "LPAREN": depth += 1
                        elif t.kind == "RPAREN": depth -= 1
                        self._advance()
                decs.append(dec_name)
                self._skip_newlines()
            kw = self._peek()
            if kw.kind == "KW" and kw.value == "struct":
                self._pending_decs = decs
                return self._parse_struct()
            if kw.kind == "KW" and kw.value in ("def", "fn"):
                self._advance()
                return self._parse_funcdef(decs)
            self._expect("KW", "def or fn")
            return self._parse_funcdef(decs)
        expr = self._parse_expr(0)
        # Check for tuple unpacking in assignment (a, b = ...)
        if self._peek().kind == "COMMA":
            targets = [expr]
            while self._peek().kind == "COMMA":
                self._advance()
                if self._peek().kind == "ASSIGN": break
                targets.append(self._parse_expr(0))
            # Check if this is actually an assignment
            if self._peek().kind == "ASSIGN":
                self._advance()
                val = self._parse_expr(0)
                tuple_target = TupleExpr(elements=targets)
                return AssignStmt(target=tuple_target, value=val)
            # Not an assignment, treat as expression statement with comma operator
            return ExprStmt(TupleExpr(elements=targets))
        # Assignment / augmented assignment
        if self._peek().kind == "ASSIGN":
            self._advance()
            val = self._parse_expr(0)
            if self._peek().kind == "ASSIGN":
                targets = [expr]
                while True:
                    if self._peek().kind != "ASSIGN": break
                    targets.append(val)
                    self._advance()
                    val = self._parse_expr(0)
                return MultiAssignStmt(targets=targets, value=val)
            return AssignStmt(target=expr, value=val)
        if self._peek().kind == "AUGASSIGN":
            op = self._advance().value
            val = self._parse_expr(0)
            return AugAssignStmt(target=expr, op=op, value=val)
        self._skip_newlines()
        return ExprStmt(expr)

    def _parse_import(self):
        self._expect("KW", "import")
        module = self._expect("NAME").value
        while self._peek().kind == "DOT":
            self._advance()
            module += "." + self._expect("NAME").value
        alias = None
        if self._is_kw("as"):
            self._advance(); alias = self._expect("NAME").value
        return ImportStmt(module=module, alias=alias)

    def _parse_from_import(self):
        self._expect("KW", "from")
        # Handle relative imports: from . or from .. or from .module
        module = ""
        while self._peek().kind == "DOT":
            self._advance()
            module += "."
        # If not just dots, parse the module name
        if self._peek().kind == "NAME":
            module += self._advance().value
            while self._peek().kind == "DOT":
                self._advance()
                module += "." + self._expect("NAME").value
        elif not module:
            # No dots and no name: error
            self._expect("NAME")  # Will raise error
        self._expect("KW", "import")
        if self._peek().kind == "OP" and self._peek().value == "*":
            self._advance()
            return FromImportStmt(module=module, names=[], wildcard=True)
        # Handle parenthesized multi-line imports: from x import (a, b, c)
        paren_import = False
        if self._peek().kind == "LPAREN":
            self._advance()
            paren_import = True
        names = []
        # Parse first name, skipping any leading newlines in parenthesized imports
        if paren_import:
            while self._peek().kind == "NEWLINE": self._advance()
        if self._peek().kind == "RPAREN":
            # Empty parens: from x import ()
            self._advance()
            return FromImportStmt(module=module, names=names, wildcard=False)
        name = self._expect("NAME").value
        alias = None
        if self._is_kw("as"):
            self._advance(); alias = self._expect("NAME").value
        names.append((name, alias))
        # Parse remaining names
        while True:
            if paren_import:
                while self._peek().kind == "NEWLINE": self._advance()
            if self._peek().kind == "RPAREN":
                self._advance()
                break
            if self._peek().kind != "COMMA":
                break
            self._advance()
            if paren_import:
                while self._peek().kind == "NEWLINE": self._advance()
            if self._peek().kind == "RPAREN":
                self._advance()
                break
            name = self._expect("NAME").value
            alias = None
            if self._is_kw("as"):
                self._advance(); alias = self._expect("NAME").value
            names.append((name, alias))
        return FromImportStmt(module=module, names=names, wildcard=False)

    def _parse_var_decl(self):
        self._expect("KW", 'var')
        # Allow KW tokens as variable names (e.g., "out", "fn", "class")
        t = self._peek()
        if t.kind == "NAME": name = self._advance().value
        elif t.kind == "KW": name = self._advance().value
        else: raise SyntaxError(f"Expected NAME or KW got {t.kind}({t.value!r})")
        # Check for tuple unpacking (var a, b, c = ...)
        if self._peek().kind == "COMMA":
            names = [name]
            while self._peek().kind == "COMMA":
                self._advance()
                t = self._peek()
                if t.kind == "NAME": names.append(self._advance().value)
                elif t.kind == "KW": names.append(self._advance().value)
                elif self._peek().kind == "ASSIGN": break
                else: break
            # Tuple unpacking: create as single VarDecl with tuple name
            if self._peek().kind == "ASSIGN":
                self._advance()
                value = self._parse_expr(0)
                return VarDecl(name=",".join(names), type_ann=None, value=value)
            else:
                # No assignment, treat as error or incomplete
                return VarDecl(name=",".join(names), type_ann=None, value=None)
        type_ann = None
        if self._peek().kind == "COLON":
            self._advance()
            type_ann = self._parse_type_ann()
        value = None
        if self._peek().kind == "ASSIGN":
            self._advance(); value = self._parse_expr(0)
        return VarDecl(name=name, type_ann=type_ann, value=value)

    def _parse_if(self):
        self._expect("KW", "if")
        cond = self._parse_expr(0)
        self._expect("COLON")
        body = self._parse_block()
        elifs, else_body = [], None
        while self._is_kw("elif"):
            self._advance(); ec = self._parse_expr(0)
            self._expect("COLON"); eb = self._parse_block()
            elifs.append((ec, eb))
        if self._is_kw("else"):
            self._advance(); self._expect("COLON")
            else_body = self._parse_block()
        return IfStmt(condition=cond, then_body=body, elifs=elifs, else_body=else_body)

    def _parse_while(self):
        self._expect("KW", "while")
        cond = self._parse_expr(0)
        self._expect("COLON")
        body = self._parse_block()
        else_body = None
        if self._is_kw("else"):
            self._advance(); self._expect("COLON")
            else_body = self._parse_block()
        return WhileStmt(condition=cond, body=body, else_body=else_body)

    def _parse_for(self):
        self._expect("KW", "for")
        # Skip optional convention keyword (var, ref, mut, etc.)
        if self._is_kw(*self._CONV_KWS):
            self._advance()
        # Handle tuple unpacking: for (a, b) in ... or for a, b in ...
        if self._peek().kind == "LPAREN":
            self._advance()
            names = []
            while self._peek().kind != "RPAREN":
                if self._peek().kind in ("NAME", "KW"):
                    names.append(self._advance().value)
                elif self._peek().kind == "COMMA":
                    self._advance()
                else:
                    break
            self._expect("RPAREN")
            target = "(" + ", ".join(names) + ")"
        else:
            # Accept KW tokens (e.g. "fn", "var") as variable names
            tok = self._advance()
            target = tok.value
            # Handle bare tuple: for a, b in ...
            if self._peek().kind == "COMMA":
                names = [target]
                while self._peek().kind == "COMMA":
                    self._advance()
                    tok2 = self._advance()
                    names.append(tok2.value)
                target = "(" + ", ".join(names) + ")"
        self._expect("KW", "in")
        iterable = self._parse_expr(0)
        self._expect("COLON")
        body = self._parse_block()
        else_body = None
        if self._is_kw("else"):
            self._advance(); self._expect("COLON")
            else_body = self._parse_block()
        return ForStmt(target=target, iterable=iterable, body=body, else_body=else_body)

    # Ownership/convention keywords preserved in param_convs
    _CONV_KWS = {'var', 'read', 'ref', 'out', 'deinit', 'mut'}
    def _parse_funcdef(self, decorators=None):
        if decorators is None: decorators = []
        name = self._expect("NAME").value
        # Skip generic type-param block [T: Trait, count: Int, //]
        if self._peek().kind == "LBRACKET": self._skip_bracketed()
        self._expect("LPAREN")
        params = []
        param_convs = {}
        while self._peek().kind != "RPAREN":
            # Skip newlines and indentation within parameter list
            while self._peek().kind in ("NEWLINE", "INDENT", "DEDENT"):
                self._advance()
            if self._peek().kind == "RPAREN": break
            # Capture last argument-convention prefix (read/mut/var/ref/out/deinit)
            conv = None
            while self._peek().kind == "KW" and self._peek().value in self._CONV_KWS:
                conv = self._advance().value
            # Skip positional-only parameter separator /
            if self._peek().kind == "OP" and self._peek().value == "/":
                self._advance()
                if self._peek().kind == "COMMA": self._advance()
                if self._peek().kind == "RPAREN": break
            # Handle * (keyword-only separator or variadic parameter)
            if self._peek().kind == "OP" and self._peek().value == "*":
                self._advance()
                # Skip lifetime parameters if present after *
                if self._peek().kind == "LBRACKET": self._skip_bracketed()
                # Handle convention keywords after * (e.g., *, var x: Int)
                while self._peek().kind == "KW" and self._peek().value in self._CONV_KWS:
                    conv = self._advance().value
                # If followed by NAME/KW, it's a variadic parameter (*args) or keyword-only param
                t = self._peek()
                if t.kind in ("NAME", "KW"):
                    if t.kind == "NAME": pname = self._advance().value
                    else: pname = self._advance().value
                    ptype = None
                    if self._peek().kind == "COLON":
                        self._advance(); ptype = self._parse_type_ann()
                    if self._peek().kind == "ASSIGN":
                        self._advance(); self._parse_expr(0)
                    params.append((pname, ptype))
                    if conv is not None: param_convs[pname] = conv
                    if self._peek().kind == "COMMA": self._advance()
                    while self._peek().kind in ("NEWLINE", "INDENT", "DEDENT"):
                        self._advance()
                    continue
                # Otherwise it's a separator: skip following comma and check for end
                elif self._peek().kind == "COMMA": self._advance()
                if self._peek().kind == "RPAREN": break
                # Continue to next parameter (convention keywords might follow)
                continue
            if self._peek().kind == "RPAREN": break
            # Skip lifetime parameters in brackets: ref[origin] param_name
            if self._peek().kind == "LBRACKET": self._skip_bracketed()
            # Allow KW tokens as parameter names (e.g., "if", "out")
            t = self._peek()
            if t.kind == "NAME": pname = self._advance().value
            elif t.kind == "KW": pname = self._advance().value
            else: raise SyntaxError(f"Expected NAME or KW got {t.kind}({t.value!r})")
            ptype = None
            if self._peek().kind == "COLON":
                self._advance(); ptype = self._parse_type_ann()
            # skip default value =expr
            if self._peek().kind == "ASSIGN":
                self._advance(); self._parse_expr(0)
            params.append((pname, ptype))
            if conv is not None: param_convs[pname] = conv
            # Skip trailing comma and newlines
            if self._peek().kind == "COMMA": self._advance()
            while self._peek().kind in ("NEWLINE", "INDENT", "DEDENT"):
                self._advance()
        self._expect("RPAREN")
        # Skip optional `raises` keyword and exception types (must come before return type)
        if self._is_kw("raises"):
            self._advance()  # skip raises
            # Skip exception type list: Type1, Type2, ... until we see -> or : or where
            while self._peek().kind not in ("COLON", "NEWLINE", "EOF", "ARROW"):
                if self._peek().kind in ("NAME", "DOT", "STRING", "COMMA"):
                    self._advance()
                elif self._peek().kind == "LBRACKET":
                    self._skip_bracketed()  # Skip subscripted exception types like ExcType[Param]
                else:
                    break
        # Skip function qualifiers (unified, register_passable, capturing, raises, etc.)
        while self._peek().kind == "NAME" and self._peek().value in ("unified", "register_passable", "capturing", "raises"):
            self._advance()
        ret = None
        if self._peek().kind == "ARROW":
            self._advance()
            # Drop `ref` lifetime prefix on return type and skip lifetime parameters
            if self._is_kw("ref"):
                self._advance()
                # Skip lifetime parameters in brackets: ref[Origin]
                if self._peek().kind == "LBRACKET":
                    self._skip_bracketed()
            ret = self._parse_type_ann()
            # Skip additional qualifiers after return type
            while self._peek().kind == "NAME" and self._peek().value in ("unified", "register_passable", "capturing", "raises"):
                self._advance()
        # Skip optional `where conforms_to(...)` clause
        if self._peek().kind == "NAME" and self._peek().value == "where":
            self._advance()  # where
            while self._peek().kind not in ("COLON", "NEWLINE", "EOF"):
                self._advance()
        # Skip capture lists in curly braces (for closures/lambdas)
        if self._peek().kind == "LBRACE":
            self._advance()  # {
            depth = 1
            while depth > 0:
                t = self._advance()
                if t.kind == "LBRACE": depth += 1
                elif t.kind == "RBRACE": depth -= 1
                elif t.kind == "EOF": break
        self._expect("COLON")
        body = self._parse_block()
        return FunctionDef(name=name, params=params, return_type=ret,
                           body=body, decorators=decorators,
                           param_convs=param_convs)

    def _parse_struct(self):
        # Accept both "struct" and "class" keywords
        kw = self._peek()
        if kw.kind == "KW" and kw.value in ("struct", "class"):
            self._advance()
        else:
            self._expect("KW", "struct")
        name = self._expect("NAME").value
        # Skip generic type-param block [T: Trait, ...]
        if self._peek().kind == "LBRACKET": self._skip_bracketed()
        if self._peek().kind == "LPAREN":
            self._advance()
            # Skip balanced parentheses in trait list
            depth = 1
            while depth > 0:
                t = self._advance()
                if t.kind == "LPAREN": depth += 1
                elif t.kind == "RPAREN": depth -= 1
                elif t.kind == "EOF": break
        self._expect("COLON")
        body = self._parse_block()
        fields  = [s for s in body if isinstance(s, VarDecl)]
        methods = [s for s in body if isinstance(s, FunctionDef)]
        decs    = getattr(self, "_pending_decs", [])
        self._pending_decs = []
        return StructDef(name=name, fields=fields, methods=methods, decorators=decs)

    def _parse_trait(self):
        self._expect("KW", "trait")
        name = self._expect("NAME").value
        # Skip generic type-param block [T: Trait, ...]
        if self._peek().kind == "LBRACKET": self._skip_bracketed()
        if self._peek().kind == "LPAREN":
            self._advance()
            # Skip balanced parentheses in trait list
            depth = 1
            while depth > 0:
                t = self._advance()
                if t.kind == "LPAREN": depth += 1
                elif t.kind == "RPAREN": depth -= 1
                elif t.kind == "EOF": break
        self._expect("COLON")
        body = self._parse_block()
        methods = [s for s in body if isinstance(s, FunctionDef)]
        return TraitDef(name=name, methods=methods)

    def _parse_try(self):
        self._expect("KW", "try"); self._expect("COLON")
        body = self._parse_block()
        handlers = []
        while self._is_kw("except"):
            self._advance()
            exc_type, exc_name = None, None
            if self._peek().kind == "NAME":
                exc_type = self._advance().value
                if self._is_kw("as"):
                    self._advance(); exc_name = self._expect("NAME").value
            self._expect("COLON")
            handlers.append(ExceptHandler(exc_type=exc_type, name=exc_name,
                                           body=self._parse_block()))
        else_body = None
        if self._is_kw("else"):
            self._advance(); self._expect("COLON"); else_body = self._parse_block()
        finally_body = None
        if self._is_kw("finally"):
            self._advance(); self._expect("COLON"); finally_body = self._parse_block()
        return TryStmt(body=body, handlers=handlers,
                       else_body=else_body, finally_body=finally_body)

    def _parse_with(self):
        self._expect("KW", "with")
        items = []
        expr = self._parse_expr(0)
        alias = None
        if self._is_kw("as"):
            self._advance(); alias = self._expect("NAME").value
        items.append(WithItem(expr=expr, alias=alias))
        while self._peek().kind == "COMMA":
            self._advance(); expr = self._parse_expr(0); alias = None
            if self._is_kw("as"):
                self._advance(); alias = self._expect("NAME").value
            items.append(WithItem(expr=expr, alias=alias))
        self._expect("COLON")
        return WithStmt(items=items, body=self._parse_block())

    def _parse_comptime(self):
        self._expect("KW", "comptime")
        t = self._peek()
        if t.value == "if":  return self._parse_comptime_if()
        if t.value == "for": return self._parse_comptime_for()
        # comptime assert expr[, msg]
        if t.value == "assert": return self._parse_assert()
        # comptime NAME [TypeParams] [: Type] = expr
        if t.kind == "NAME":
            lhs = IdentExpr(self._advance().value)
            # Skip optional type parameters: comptime Alias[T, U]: Type = ...
            if self._peek().kind == "LBRACKET": self._skip_bracketed()
            # Skip optional type annotation: comptime MIN: Bool = False
            if self._peek().kind == "COLON":
                self._advance()  # skip colon
                self._parse_type_ann()  # parse and discard type annotation
            if self._peek().kind == "ASSIGN":
                self._advance()
                return AssignStmt(target=lhs, value=self._parse_expr(0))
            return ExprStmt(lhs)
        raise SyntaxError(f"Unexpected token after comptime: {t.value!r}")

    def _parse_comptime_if(self):
        self._expect("KW","if"); cond=self._parse_expr(0)
        self._expect("COLON"); body=self._parse_block()
        elifs, else_body = [], None
        while self._is_kw("elif"):
            self._advance(); ec = self._parse_expr(0)
            self._expect("COLON"); eb = self._parse_block()
            elifs.append((ec, eb))
        if self._is_kw("else"):
            self._advance();self._expect("COLON");else_body=self._parse_block()
        return ComptimeIfStmt(condition=cond,then_body=body,elifs=elifs,else_body=else_body)

    def _parse_comptime_for(self):
        self._expect("KW","for"); target=self._expect("NAME").value
        self._expect("KW","in"); iterable=self._parse_expr(0)
        self._expect("COLON")
        return ComptimeForStmt(target=target,iterable=iterable,body=self._parse_block())

    def _parse_pass(self):
        self._expect("KW", 'pass')
        return PassStmt()

    def _parse_return(self):
        self._expect("KW", 'return')
        if self._peek().kind in ("NEWLINE","EOF","DEDENT"):
            return ReturnStmt(value=None)
        return ReturnStmt(value=self._parse_expr(0))

    def _parse_raise(self):
        self._expect("KW", 'raise')
        if self._peek().kind in ("NEWLINE","EOF","DEDENT"):
            return RaiseStmt(value=None)
        return RaiseStmt(value=self._parse_expr(0))

    def _parse_break(self):
        self._expect("KW", 'break')
        return BreakStmt()

    def _parse_continue(self):
        self._expect("KW", 'continue')
        return ContinueStmt()

    def _parse_assert(self):
        self._expect("KW", 'assert')
        value = self._parse_expr(0)
        msg = None
        if self._peek().kind == "COMMA":
            self._advance(); msg = self._parse_expr(0)
        return AssertStmt(value=value, msg=msg)

    # ── Expressions ──────────────────────────────────────────────────
    def _parse_expr(self, min_prec: int):
        left = self._parse_unary()
        while True:
            t = self._peek()
            if t.kind == "OP":
                prec = _PREC.get(t.value, -1)
                if prec < min_prec: break
                op = self._advance().value
                right = self._parse_expr(prec + 1)
                if op == ":=" and isinstance(left, IdentExpr):
                    left = WalrusExpr(name=left.name, value=right)
                else:
                    left = BinaryOp(op=op, left=left, right=right)
            elif t.kind == "KW" and t.value in _KW_PREC:
                prec = _KW_PREC[t.value]
                if prec < min_prec: break
                op = self._advance().value
                if op == "not" and self._is_kw("in"):
                    self._advance(); op = "not in"
                elif op == "is" and self._is_kw("not"):
                    self._advance(); op = "is not"
                right = self._parse_expr(prec + 1)
                left = BinaryOp(op=op, left=left, right=right)
            elif t.kind == "KW" and t.value == "if" and min_prec == 0:
                self._advance()
                cond = self._parse_expr(1)
                self._expect("KW", "else")
                els = self._parse_expr(0)
                left = TernaryExpr(condition=cond, then_val=left, else_val=els)
            else:
                break
        return left

    def _parse_unary(self):
        t = self._peek()
        if t.kind == "OP" and t.value in ("-", "+", "~"):
            self._advance()
            return UnaryOp(op=t.value, operand=self._parse_unary())
        if t.kind == "KW" and t.value == "not":
            self._advance()
            return UnaryOp(op="not", operand=self._parse_unary())
        return self._parse_postfix()

    def _parse_postfix(self):
        expr = self._parse_primary()
        while True:
            t = self._peek()
            if t.kind == "DOT":
                self._advance()
                # Member can be a NAME (including KW like mut, ref) or a backtick-quoted type
                if self._peek().kind == "STRING" and self._peek().value.startswith("`"):
                    member = self._advance().value
                elif self._peek().kind in ("NAME", "KW"):
                    member = self._advance().value
                else:
                    member = self._expect("NAME").value  # error for invalid syntax
                expr = MemberExpr(obj=expr, member=member)
            elif t.kind == "LBRACKET":
                self._advance()
                # Check for empty subscript [] (dereference/special case)
                if self._peek().kind == "RBRACKET":
                    idx = IntLiteral(value="0")  # dummy index for empty subscript
                    self._advance()  # consume RBRACKET
                    expr = SubscriptExpr(obj=expr, index=idx)
                else:
                    # Parse first index/argument
                    # Check for unpacking: *expr
                    if self._peek().kind == "OP" and self._peek().value == "*":
                        self._advance()  # skip *
                        self._parse_expr(0)  # parse and discard unpacked value
                        # Continue parsing remaining arguments
                        while self._peek().kind == "COMMA":
                            self._advance()
                            if self._peek().kind == "RBRACKET": break
                            # Skip remaining arguments/keywords
                            if self._peek().kind == "OP" and self._peek().value == "*":
                                self._advance()
                                self._parse_expr(0)
                            elif self._peek().kind in ("NAME", "KW") and self._peek(1).kind == "ASSIGN":
                                self._advance()  # skip name
                                self._advance()  # skip =
                                self._parse_expr(0)
                            else:
                                self._parse_expr(0)
                            if self._peek().kind != "COMMA" and self._peek().kind != "RBRACKET": break
                        self._expect("RBRACKET")
                        expr = SubscriptExpr(obj=expr, index=IntLiteral(value="0"))
                    # Check if this is a keyword-style bracket (func=value, attr=value)
                    elif self._peek().kind in ("NAME", "KW") and self._peek(1).kind == "ASSIGN":
                        # Keyword arguments only
                        while self._peek().kind != "RBRACKET" and self._peek().kind != "EOF":
                            if self._peek().kind in ("NAME", "KW"):
                                self._advance()  # skip name
                                if self._peek().kind == "ASSIGN": self._advance()  # skip =
                                self._parse_expr(0)  # parse and discard value
                            if self._peek().kind == "COMMA": self._advance()
                            elif self._peek().kind != "RBRACKET": break
                        self._expect("RBRACKET")
                        expr = SubscriptExpr(obj=expr, index=IntLiteral(value="0"))
                    else:
                        # Check for slice with empty start (e.g., [:10] or [:-2])
                        if self._peek().kind == "COLON":
                            self._advance()
                            stop = None if self._peek().kind == "RBRACKET" else self._parse_expr(0)
                            expr = SliceExpr(obj=expr, start=None, stop=stop)
                            self._expect("RBRACKET")
                        else:
                            # Parse positional index
                            idx = self._parse_expr(0)
                            # Check for multiple indices or keywords
                            if self._peek().kind == "COMMA":
                                indices = [idx]
                                while self._peek().kind == "COMMA":
                                    self._advance()
                                    if self._peek().kind == "RBRACKET": break
                                    # Check if next element is keyword argument (NAME = ...)
                                    # Check for unpacking (*expr)
                                    if self._peek().kind == "OP" and self._peek().value == "*":
                                        self._advance()
                                        indices.append(self._parse_expr(0))
                                    # Check if keyword argument
                                    elif self._peek().kind in ("NAME", "KW") and self._peek(1).kind == "ASSIGN":
                                        # Skip remaining keyword arguments
                                        while self._peek().kind != "RBRACKET" and self._peek().kind != "EOF":
                                            if self._peek().kind in ("NAME", "KW"):
                                                self._advance()  # skip name
                                                if self._peek().kind == "ASSIGN": self._advance()  # skip =
                                                self._parse_expr(0)  # parse and discard value
                                            if self._peek().kind == "COMMA": self._advance()
                                            elif self._peek().kind != "RBRACKET": break
                                        break
                                    else:
                                        indices.append(self._parse_expr(0))
                                idx = TupleExpr(elements=indices)
                            # Check for slice notation
                            if self._peek().kind == "COLON":
                                self._advance()
                                stop = None if self._peek().kind == "RBRACKET" else self._parse_expr(0)
                                expr = SliceExpr(obj=expr, start=idx, stop=stop)
                            else:
                                expr = SubscriptExpr(obj=expr, index=idx)
                            self._expect("RBRACKET")
            elif t.kind == "LPAREN":
                self._advance()
                args = []
                while self._peek().kind != "RPAREN":
                    # Handle dictionary unpacking (**expr)
                    if self._peek().kind == "OP" and self._peek().value == "**":
                        self._advance()  # skip **
                        args.append(self._parse_expr(0))  # parse unpacked kwargs
                    # Handle unpacking (*expr)
                    elif self._peek().kind == "OP" and self._peek().value == "*":
                        self._advance()  # skip *
                        args.append(self._parse_expr(0))  # parse unpacked value
                    # Handle keyword arguments (name=value)
                    elif self._peek().kind == "NAME" and self._peek(1).kind == "ASSIGN":
                        self._advance()  # skip keyword name
                        self._advance()  # skip =
                        args.append(self._parse_expr(0))  # parse and keep value
                    else:
                        args.append(self._parse_expr(0))
                    if self._peek().kind == "COMMA": self._advance()
                self._expect("RPAREN")
                expr = CallExpr(func=expr, args=args)
            elif t.kind == "OP" and t.value == "^":
                # Check if ^ is postfix (ownership transfer) or binary (XOR)
                # Postfix: followed by statement-ending token
                # Binary: followed by expression start token
                next_t = self._peek(1)
                is_postfix = next_t.kind in ("NEWLINE", "DEDENT", "EOF", "COMMA", "RPAREN", "RBRACKET", "COLON", "SEMICOLON")
                if is_postfix:
                    self._advance()
                    expr = UnaryOp(op="^", operand=expr)
                else:
                    break  # Let binary operator precedence handle it
            else:
                break
        return expr

    def _parse_primary(self):
        t = self._peek()
        if t.kind == "INT":
            self._advance(); return IntLiteral(int(t.value, 0))
        if t.kind == "FLOAT":
            self._advance(); return FloatLiteral(float(t.value))
        if t.kind == "KW" and t.value in ("True","False"):
            self._advance()
            return BoolLiteral(t.value == "True")
        if t.kind == "STRING":
            val = self._advance().value
            # Handle implicit string concatenation (adjacent strings)
            while self._peek().kind == "STRING":
                val += self._advance().value
            return StringLiteral(val)
        if t.kind == "LBRACKET": return self._parse_list_or_compr()
        if t.kind == "LBRACE": return self._parse_dict_or_set()
        if t.kind == "LPAREN":
            self._advance()
            if self._peek().kind == "RPAREN":
                self._advance(); return TupleExpr(elements=[])
            first = self._parse_expr(0)
            if self._peek().kind == "COMMA":
                elems = [first]
                while self._peek().kind == "COMMA":
                    self._advance()
                    if self._peek().kind == "RPAREN": break
                    elems.append(self._parse_expr(0))
                self._expect("RPAREN")
                return TupleExpr(elements=elems)
            self._expect("RPAREN")
            return first
        if t.kind in ("NAME", "KW"):
            self._advance()
            return IdentExpr(t.value)
        if t.kind == "DOT" and self._peek(1).kind == "DOT" and self._peek(2).kind == "DOT":
            self._advance(); self._advance(); self._advance()
            return EllipsisLiteral()
        raise SyntaxError(f"Unexpected {t.kind}({t.value!r})")

    def _parse_list_or_compr(self):
        self._expect("LBRACKET")
        if self._peek().kind == "RBRACKET":
            self._advance(); return ListExpr(elements=[])
        first = self._parse_expr(0)
        if self._is_kw("for"):
            gen = self._parse_generator()
            self._expect("RBRACKET")
            return Comprehension(kind="list", element=first, generators=[gen])
        elems = [first]
        while self._peek().kind == "COMMA":
            self._advance()
            if self._peek().kind == "RBRACKET": break
            elems.append(self._parse_expr(0))
        self._expect("RBRACKET")
        return ListExpr(elements=elems)

    def _parse_dict_or_set(self):
        self._expect("LBRACE")
        if self._peek().kind == "RBRACE":
            self._advance(); return DictExpr(pairs=[])
        first = self._parse_expr(0)
        # Check for struct initializer syntax: {field = value, ...}
        if self._peek().kind == "ASSIGN":
            # This is a struct initializer with named fields
            self._advance()  # skip =
            self._parse_expr(0)  # parse and discard field value
            # Skip any remaining fields
            while self._peek().kind == "COMMA":
                self._advance()
                if self._peek().kind == "RBRACE": break
                self._parse_expr(0)  # skip field name
                if self._peek().kind == "ASSIGN": self._advance()
                self._parse_expr(0)  # skip field value
            self._expect("RBRACE")
            # Return as dict for now (struct init not semantically tracked)
            return DictExpr(pairs=[])
        if self._peek().kind == "COLON":
            self._advance(); val = self._parse_expr(0)
            if self._is_kw("for"):
                gen = self._parse_generator()
                self._expect("RBRACE")
                return Comprehension(kind="dict", element=first, key=val, generators=[gen])
            pairs = [(first, val)]
            while self._peek().kind == "COMMA":
                self._advance()
                if self._peek().kind == "RBRACE": break
                k = self._parse_expr(0); self._expect("COLON"); v = self._parse_expr(0)
                pairs.append((k, v))
            self._expect("RBRACE")
            return DictExpr(pairs=pairs)
        if self._is_kw("for"):
            gen = self._parse_generator()
            self._expect("RBRACE")
            return Comprehension(kind="set", element=first, generators=[gen])
        elems = [first]
        while self._peek().kind == "COMMA":
            self._advance()
            if self._peek().kind == "RBRACE": break
            elems.append(self._parse_expr(0))
        self._expect("RBRACE")
        return SetExpr(elements=elems)

    def _parse_generator(self):
        self._expect("KW", "for")
        target = self._expect("NAME").value
        self._expect("KW", "in")
        iterable = self._parse_expr(1)
        conditions = []
        while self._is_kw("if"):
            self._advance(); conditions.append(self._parse_expr(1))
        return Generator(target=target, iterable=iterable, conditions=conditions)

    def _skip_bracketed(self):
        """Consume a balanced [...] block."""
        self._expect("LBRACKET")
        depth = 1
        while depth > 0:
            t = self._advance()
            if t.kind == "LBRACKET": depth += 1
            elif t.kind == "RBRACKET": depth -= 1
            elif t.kind == "EOF": break

    def _parse_type_ann(self) -> str:
        """Parse a type annotation: Name or Name[TypeArgs] or Name.Member.Type[Args] or `backtick_type`."""
        # Handle * prefix for variadic/unpacking types (*Ts)
        prefix = ""
        if self._peek().kind == "OP" and self._peek().value == "*":
            prefix = "*"
            self._advance()
        # Handle `ref` or `mut` keyword prefix on type (lifetime annotation)
        if self._is_kw("ref") or self._is_kw("mut"):
            self._advance()  # drop ref/mut prefix
            # Skip lifetime parameters in brackets: ref[Origin]
            if self._peek().kind == "LBRACKET":
                self._skip_bracketed()
        # Handle backtick-quoted MLIR types (e.g., `!pop.scalar<bool>`)
        if self._peek().kind == "STRING" and self._peek().value.startswith("`"):
            return prefix + self._advance().value  # return the backtick string as-is
        # Handle parenthesized types like () for unit type
        if self._peek().kind == "LPAREN":
            name = prefix + "("
            self._advance()
            depth = 1
            while depth > 0:
                t = self._advance()
                if t.kind == "LPAREN": depth += 1; name += "("
                elif t.kind == "RPAREN":
                    depth -= 1
                    if depth > 0: name += ")"
                elif t.kind == "EOF": break
                else: name += t.value
            name += ")"
            return name
        # Allow KW tokens as type names (e.g., "let", "var", "if")
        t = self._peek()
        if t.kind == "NAME": name = prefix + self._advance().value
        elif t.kind == "KW": name = prefix + self._advance().value
        else: raise SyntaxError(f"Expected NAME or KW got {t.kind}({t.value!r})")
        # Support dotted type names like __mlir_type.i1 or __mlir_type.`backtick_type`
        while self._peek().kind == "DOT":
            self._advance()  # consume dot
            # Next part can be a NAME (including KW like mut, ref) or a backtick-quoted type
            if self._peek().kind == "STRING" and self._peek().value.startswith("`"):
                name += "." + self._advance().value
            elif self._peek().kind in ("NAME", "KW"):
                name += "." + self._advance().value
            else:
                name += "." + self._expect("NAME").value  # error for invalid syntax
        # Handle function call types like type_of(x)
        if self._peek().kind == "LPAREN":
            self._advance()  # (
            name += "("
            depth = 1
            while depth > 0:
                t = self._advance()
                if t.kind == "LPAREN": depth += 1; name += "("
                elif t.kind == "RPAREN":
                    depth -= 1
                    if depth > 0: name += ")"
                elif t.kind == "EOF": break
                else: name += t.value
            name += ")"
            # Do NOT return here; check for dotted names and subscripts after the call
            # Second dotted-name loop after function call
            while self._peek().kind == "DOT":
                self._advance()  # consume dot
                # Next part can be a NAME or a backtick-quoted type
                if self._peek().kind == "STRING" and self._peek().value.startswith("`"):
                    name += "." + self._advance().value
                else:
                    name += "." + self._expect("NAME").value
        if self._peek().kind != "LBRACKET": return name
        # Consume [TypeArgs] and any chained subscripts — build a string representation
        parts = [name]
        while self._peek().kind == "LBRACKET":
            self._advance()  # [
            parts.append("[")
            depth = 1
            while depth > 0:
                t = self._advance()
                if t.kind == "LBRACKET": depth += 1; parts.append("[")
                elif t.kind == "RBRACKET":
                    depth -= 1
                    if depth > 0: parts.append("]")
                elif t.kind == "EOF": break
                else: parts.append(t.value)
            parts.append("]")
        return "".join(parts)

# ── Code generator ─────────────────────────────────────────────────
def emit_module(stmts: list, indent: int = 0) -> str:
    return "\n".join(emit(s, indent) for s in stmts)

def emit(node, indent: int = 0) -> str:
    pad = "    " * indent
    if isinstance(node,IntLiteral): return str(node.value)
    if isinstance(node,FloatLiteral): return repr(node.value)
    if isinstance(node,BoolLiteral): return str(node.value)
    if isinstance(node,StringLiteral): return node.value
    if isinstance(node,EllipsisLiteral): return "..."
    if isinstance(node,IdentExpr): return node.name
    if isinstance(node,CallExpr):
        f = emit(node.func) if not isinstance(node.func,str) else node.func
        args = ", ".join(emit(a) for a in node.args)
        return f"{f}({args})"
    if isinstance(node,BinaryOp): return f"({emit(node.left)} {node.op} {emit(node.right)})"
    if isinstance(node,UnaryOp):  return f"({node.op} {emit(node.operand)})"
    if isinstance(node,TernaryExpr): return f"({emit(node.then_val)} if {emit(node.condition)} else {emit(node.else_val)})"
    if isinstance(node,MemberExpr): return f"{emit(node.obj)}.{node.member}"
    if isinstance(node,SubscriptExpr): return f"{emit(node.obj)}[{emit(node.index)}]"
    if isinstance(node,SliceExpr):
        start = emit(node.start) if node.start is not None else ""
        stop  = emit(node.stop)  if node.stop  is not None else ""
        return f"{emit(node.obj)}[{start}:{stop}]"
    if isinstance(node,ListExpr): return "[" + ", ".join(emit(e) for e in node.elements) + "]"
    if isinstance(node,DictExpr): return "{" + ", ".join(f"{emit(k)}: {emit(v)}" for k,v in node.pairs) + "}"
    if isinstance(node,SetExpr): return "{" + ", ".join(emit(e) for e in node.elements) + "}"
    if isinstance(node,TupleExpr):
        if not node.elements: return "()"
        return "(" + ", ".join(emit(e) for e in node.elements) + ("," if len(node.elements)==1 else "") + ")"
    if isinstance(node,Comprehension):
        gens = " ".join(f"for {g.target} in {emit(g.iterable)}" + "".join(f" if {emit(c)}" for c in g.conditions) for g in node.generators)
        if node.kind == "list": return f"[{emit(node.element)} {gens}]"
        if node.kind == "set":  return "{" + f"{emit(node.element)} {gens}" + "}"
        if node.kind == "dict": return "{" + f"{emit(node.element)}: {emit(node.key)} {gens}" + "}"
        return f"({emit(node.element)} {gens})"
    if isinstance(node,ExprStmt): return f"{pad}{emit(node.value)}"
    if isinstance(node,AssignStmt): return f"{pad}{emit(node.target)} = {emit(node.value)}"
    if isinstance(node,AugAssignStmt): return f"{pad}{emit(node.target)} {node.op} {emit(node.value)}"
    if isinstance(node,VarDecl):
        ann = f": {node.type_ann}" if node.type_ann else ""
        val = f" = {emit(node.value)}" if node.value is not None else ""
        return f"{pad}{node.name}{ann}{val}"
    if isinstance(node,MultiAssignStmt):
        return f"{pad}" + " = ".join(emit(t) for t in node.targets) + " = " + emit(node.value)
    if isinstance(node,ImportStmt):
        alias = f" as {node.alias}" if node.alias else ""
        return f"{pad}import {node.module}{alias}"
    if isinstance(node,FromImportStmt):
        if node.wildcard: return f"{pad}from {node.module} import *"
        names = ", ".join(n + (f" as {a}" if a else "") for n,a in node.names)
        return f"{pad}from {node.module} import {names}"
    if isinstance(node,IfStmt):
        out = [f"{pad}if {emit(node.condition)}:"]
        out += [emit(s,indent+1) for s in node.then_body]
        for (ec,eb) in node.elifs:
            out.append(f"{pad}elif {emit(ec)}:"); out += [emit(s,indent+1) for s in eb]
        if node.else_body is not None:
            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]
        return "\n".join(out)
    if isinstance(node,WhileStmt):
        out = [f"{pad}while {emit(node.condition)}:"]
        out += [emit(s,indent+1) for s in node.body]
        if node.else_body is not None:
            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]
        return "\n".join(out)
    if isinstance(node,ForStmt):
        out = [f"{pad}for {emit(node.target) if not isinstance(node.target,str) else node.target} in {emit(node.iterable)}:"]
        out += [emit(s,indent+1) for s in node.body]
        if node.else_body is not None:
            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]
        return "\n".join(out)
    if isinstance(node,FunctionDef):
        def _fmt_param(n,t):
            ann = f": {t}" if t else ""
            return f"{n}{ann}"  # strip Mojo arg-convention prefix for Python
        params = ", ".join(_fmt_param(n,t) for n,t in node.params)
        ret = f" -> {node.return_type}" if node.return_type else ""
        out = [f"{pad}@{d}" for d in node.decorators]
        out.append(f"{pad}def {node.name}({params}){ret}:")
        out += [emit(s,indent+1) for s in node.body]
        return "\n".join(out)
    if isinstance(node,PassStmt): return f"{pad}pass"
    if isinstance(node,ReturnStmt):
        val = f" {emit(node.value)}" if node.value is not None else ""
        return f"{pad}return{val}"
    if isinstance(node,RaiseStmt):
        val = f" {emit(node.value)}" if node.value is not None else ""
        return f"{pad}raise{val}"
    if isinstance(node,BreakStmt): return f"{pad}break"
    if isinstance(node,ContinueStmt): return f"{pad}continue"
    if isinstance(node,AssertStmt):
        val = f" {emit(node.value)}" if node.value is not None else ""
        msg_s = f", {emit(node.msg)}" if node.msg is not None else ""
        return f"{pad}assert{val}{msg_s}"
    if isinstance(node,TryStmt):
        out = [f"{pad}try:"]
        out += [emit(s,indent+1) for s in node.body]
        for h in node.handlers:
            exc  = f" {h.exc_type}" if h.exc_type else ""
            name = f" as {h.name}"  if h.name    else ""
            out.append(f"{pad}except{exc}{name}:")
            out += [emit(s,indent+1) for s in h.body]
        if node.else_body:
            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]
        if node.finally_body:
            out.append(f"{pad}finally:"); out += [emit(s,indent+1) for s in node.finally_body]
        return "\n".join(out)
    if isinstance(node,WithStmt):
        items_str = ", ".join(f"{emit(i.expr)} as {i.alias}" if i.alias else emit(i.expr) for i in node.items)
        out = [f"{pad}with {items_str}:"]
        out += [emit(s,indent+1) for s in node.body]
        return "\n".join(out)
    if isinstance(node,ComptimeIfStmt):
        out = [f"{pad}if {emit(node.condition)}:  # comptime"]
        out += [emit(s,indent+1) for s in node.then_body]
        for (ec,eb) in node.elifs:
            out.append(f"{pad}elif {emit(ec)}:"); out += [emit(s,indent+1) for s in eb]
        if node.else_body is not None:
            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]
        return "\n".join(out)
    if isinstance(node,ComptimeForStmt):
        out = [f"{pad}for {node.target} in {emit(node.iterable)}:  # comptime"]
        out += [emit(s,indent+1) for s in node.body]
        return "\n".join(out)
    if isinstance(node,StructDef):
        _OWN_DECS = {"Copyable","Movable","ImplicitlyCopyable","ExplicitlyCopyable",
                     "Writable","Sized","Boolable","Stringable","Hashable","AnyType"}
        has_init = any(d == "fieldwise_init" for d in node.decorators)
        ext_decs = [d for d in node.decorators if d not in _OWN_DECS and d != "fieldwise_init"]
        out = [f"{pad}@{d}" for d in ext_decs]
        out.append(f"{pad}class {node.name}:")
        body = []
        if has_init and node.fields:
            ps = ", ".join(f.name for f in node.fields)
            body.append(f"{pad}    def __init__(self, {ps}):")
            for f in node.fields:
                body.append(f"{pad}        self.{f.name} = {f.name}")
        elif node.fields:
            for f in node.fields:
                ann = f": {f.type_ann}" if f.type_ann else ""
                val = f" = {emit(f.value)}" if f.value is not None else " = None"
                body.append(f"{pad}    {f.name}{ann}{val}")
        for m in node.methods:
            body.append(emit(m,indent+1))
        out += body if body else [f"{pad}    pass"]
        return "\n".join(out)
    if isinstance(node,TraitDef):
        out = [f"{pad}class {node.name}:  # trait"]
        body = []
        for m in node.methods:
            is_abs = (not m.body or
                      (len(m.body)==1 and isinstance(m.body[0],PassStmt)) or
                      (len(m.body)==1 and isinstance(m.body[0],ExprStmt)
                       and isinstance(m.body[0].value,EllipsisLiteral)))
            if is_abs: body.append(f"{pad}    @abstractmethod")
            body.append(emit(m,indent+1))
        out += body if body else [f"{pad}    pass"]
        return "\n".join(out)
    # Transfer sigil ^ is stripped by the tokenizer (XFER ignored)
    raise TypeError(f"Cannot emit {type(node).__name__}")

# ── AST Interpreter ────────────────────────────────────────────────────
class Interpreter:
    """Execute Mojo AST."""

    def __init__(self):
        self.globals = {}
        self.locals_stack = [{}]  # Stack of local scopes
        self._init_builtins()

    def _init_builtins(self):
        """Register built-in functions."""
        builtins = {
            'print': lambda *args, **kw: print(*args),
            'len': len,
            'range': range,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'set': set,
            'tuple': tuple,
            'type': type,
            'isinstance': isinstance,
            'abs': abs,
            'min': min,
            'max': max,
            'sum': sum,
            'any': any,
            'all': all,
            'enumerate': enumerate,
            'zip': zip,
            'reversed': reversed,
            'sorted': sorted,
            'repr': repr,
        }
        self.globals.update(builtins)

    def _get_var(self, name: str):
        """Look up variable in local then global scope."""
        for scope in reversed(self.locals_stack):
            if name in scope:
                return scope[name]
        if name in self.globals:
            return self.globals[name]
        raise NameError(f"name '{name}' is not defined")

    def _set_var(self, name: str, value):
        """Set variable in current local scope."""
        self.locals_stack[-1][name] = value

    def eval_expr(self, node):
        """Evaluate an expression node."""
        if node is None:
            return None

        if isinstance(node, IntLiteral):
            return int(node.value)
        if isinstance(node, FloatLiteral):
            return float(node.value)
        if isinstance(node, StringLiteral):
            return node.value
        if isinstance(node, BoolLiteral):
            return node.value
        if isinstance(node, IdentExpr):
            return self._get_var(node.name)

        if isinstance(node, ListExpr):
            return [self.eval_expr(e) for e in node.elements]
        if isinstance(node, DictExpr):
            return {self.eval_expr(k): self.eval_expr(v) for k, v in node.pairs}
        if isinstance(node, SetExpr):
            return {self.eval_expr(e) for e in node.elements}
        if isinstance(node, TupleExpr):
            return tuple(self.eval_expr(e) for e in node.elements)

        if isinstance(node, BinaryOp):
            left = self.eval_expr(node.left)
            right = self.eval_expr(node.right)
            ops = {
                '+': lambda a, b: a + b,
                '-': lambda a, b: a - b,
                '*': lambda a, b: a * b,
                '/': lambda a, b: a / b,
                '//': lambda a, b: a // b,
                '%': lambda a, b: a % b,
                '**': lambda a, b: a ** b,
                '==': lambda a, b: a == b,
                '!=': lambda a, b: a != b,
                '<': lambda a, b: a < b,
                '<=': lambda a, b: a <= b,
                '>': lambda a, b: a > b,
                '>=': lambda a, b: a >= b,
                'and': lambda a, b: a and b,
                'or': lambda a, b: a or b,
                '&': lambda a, b: a & b,
                '|': lambda a, b: a | b,
                '^': lambda a, b: a ^ b,
                '<<': lambda a, b: a << b,
                '>>': lambda a, b: a >> b,
            }
            if node.op in ops:
                return ops[node.op](left, right)
            raise ValueError(f"Unknown binary op: {node.op}")

        if isinstance(node, UnaryOp):
            operand = self.eval_expr(node.operand)
            ops = {
                '-': lambda a: -a,
                '+': lambda a: +a,
                '~': lambda a: ~a,
                'not': lambda a: not a,
            }
            if node.op in ops:
                return ops[node.op](operand)
            raise ValueError(f"Unknown unary op: {node.op}")

        if isinstance(node, CallExpr):
            func = self.eval_expr(node.func)
            args = [self.eval_expr(arg) for arg in node.args]
            return func(*args)

        if isinstance(node, MemberExpr):
            obj = self.eval_expr(node.obj)
            return getattr(obj, node.member)

        if isinstance(node, SubscriptExpr):
            obj = self.eval_expr(node.obj)
            idx = self.eval_expr(node.index)
            return obj[idx]

        if isinstance(node, TernaryExpr):
            cond = self.eval_expr(node.condition)
            if cond:
                return self.eval_expr(node.then_val)
            else:
                return self.eval_expr(node.else_val)

        raise NotImplementedError(f"Cannot evaluate {type(node).__name__}")

    def exec_stmt(self, node):
        """Execute a statement node."""
        if node is None:
            return

        if isinstance(node, PassStmt):
            return

        if isinstance(node, ExprStmt):
            self.eval_expr(node.value)
            return

        if isinstance(node, AssignStmt):
            value = self.eval_expr(node.value)
            if isinstance(node.target, IdentExpr):
                self._set_var(node.target.name, value)
            elif isinstance(node.target, TupleExpr):
                for i, t in enumerate(node.target.elements):
                    if isinstance(t, IdentExpr):
                        self._set_var(t.name, value[i])
            else:
                raise NotImplementedError(f"Assignment to {type(node.target).__name__}")
            return

        if isinstance(node, VarDecl):
            value = self.eval_expr(node.value) if node.value else None
            self._set_var(node.name, value)
            return

        if isinstance(node, IfStmt):
            cond = self.eval_expr(node.condition)
            if cond:
                for stmt in node.then_body:
                    self.exec_stmt(stmt)
            else:
                for elif_cond, elif_body in node.elifs:
                    cond = self.eval_expr(elif_cond)
                    if cond:
                        for stmt in elif_body:
                            self.exec_stmt(stmt)
                        return
                if node.else_body:
                    for stmt in node.else_body:
                        self.exec_stmt(stmt)
            return

        if isinstance(node, WhileStmt):
            while self.eval_expr(node.condition):
                for stmt in node.body:
                    self.exec_stmt(stmt)
            return

        if isinstance(node, ForStmt):
            iterable = self.eval_expr(node.iterable)
            for item in iterable:
                if isinstance(node.target, IdentExpr):
                    self._set_var(node.target, item)
                elif isinstance(node.target, str):  # tuple unpacking
                    names = node.target.split(',')
                    for i, name in enumerate(names):
                        self._set_var(name.strip(), item[i])
                for stmt in node.body:
                    self.exec_stmt(stmt)
            return

        if isinstance(node, FunctionDef):
            def mojo_func(*args, **kwargs):
                self.locals_stack.append({})
                for i, (pname, _) in enumerate(node.params):
                    if i < len(args):
                        self._set_var(pname, args[i])
                for k, v in kwargs.items():
                    self._set_var(k, v)
                result = None
                for stmt in node.body:
                    if isinstance(stmt, ReturnStmt):
                        result = self.eval_expr(stmt.value)
                        break
                    self.exec_stmt(stmt)
                self.locals_stack.pop()
                return result
            self._set_var(node.name, mojo_func)
            return

        if isinstance(node, ReturnStmt):
            # Handled in FunctionDef
            return

        if isinstance(node, ImportStmt):
            # TODO: Handle imports properly
            return

        raise NotImplementedError(f"Cannot execute {type(node).__name__}")

    def execute(self, stmts):
        """Execute a list of statements."""
        for stmt in stmts:
            self.exec_stmt(stmt)

# ── Driver ──────────────────────────────────────────────────────────
def compile(src: str) -> str:
    tokens = tokenize(src)
    stmts  = Parser(tokens).parse_module()
    return emit_module(stmts)

def interpret(src: str):
    """Parse and interpret Mojo code (for REPL, testing, bootstrap)."""
    tokens = tokenize(src)
    stmts = Parser(tokens).parse_module()
    interp = Interpreter()
    interp.execute(stmts)
    return interp

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--interpret':
        # Interpret mode: python mojo_compiler.py --interpret <file.mojo>
        src = sys.stdin.read() if len(sys.argv) < 3 else open(sys.argv[2]).read()
        interpret(src)
    else:
        # Compile mode: python mojo_compiler.py [file.mojo]
        src = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1]).read()
        print(compile(src))
