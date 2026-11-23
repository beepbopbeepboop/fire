"""Instructions of the gimple IR.

Deliberately few classes, no inheritance: `Ex` is every operand/expression
shape, `Instr` is every statement shape, distinguished by `kind`.

Ex.kind
  'var'    name                       a local, parameter, global or function
  'int'    text, ival, suffix         integer literal
  'float'  text                       floating literal
  'str'    text                       string literal
  'field'  a, name, arrow             a.name  /  a->name
  'index'  a, b                       a[b]
  'addr'   a                          &a
  'deref'  a                          *a
  'un'     op, a                      - ~ !
  'cast'   ty, a                      (ty) a
  'call'   a (callee), args
  'bin'    op, a, b
  'cond'   a ? b : c
  'comma'  a, b                       `a, b` inside a parenthesized comma expression
  'lambda' text (return C type), body   `[&]() -> text { body }()`; body is Instr
  'opaque' ty                         something the reader does not model

Instr.kind
  'assign' lhs, rhs
  'expr'   rhs                        a call for effect
  'goto'   label
  'cgoto'  rhs (condition), label, label2   label2 '' = one-armed
  'return' rhs (kind 'none' Ex when there is no value)
  'label'  label
  'comment' text                      a `/* ... */` line; never a statement
  'if'     rhs (condition)            `if (c) {` -- opens a block
  'else'                              `else {`
  'elseif' rhs (condition)            `else if (c) {`
  'end'                               `}` -- closes a block
  'ifbody' rhs (condition), body      `if (c) <body>` -- one-statement body
  'opaque' text                       not three-address; not checked
"""
from __future__ import annotations

from mojo.ir.types import Type, VOID


class Ex:
    def __init__(self, kind: str):
        self.kind: str = kind
        self.name: str = ''
        self.text: str = ''
        self.op: str = ''
        self.ival: int = 0
        self.suffix: str = ''
        self.arrow: bool = False
        self.tight: bool = False    # `f(...)` rather than `f (...)`
        self.ty: Type = VOID
        self.a: Ex = self          # self = "absent"; keeps the field typed
        self.b: Ex = self
        self.c: Ex = self
        self.args: list[Ex] = []
        self.body: list = []        # 'lambda': the statements (Instr) of its body

    def show(self) -> str:
        k = self.kind
        if k == 'var':
            return self.name
        if k == 'int' or k == 'float' or k == 'str':
            return self.text
        if k == 'field':
            return self.a.show() + ('->' if self.arrow else '.') + self.name
        if k == 'index':
            return self.a.show() + '[' + self.b.show() + ']'
        if k == 'addr':
            return '&' + self.a.show()
        if k == 'deref':
            return '*' + self.a.show()
        if k == 'un':
            return self.op + self.a.show()
        if k == 'coawait':
            # A C++ `co_await <expr>` (an awaited expression).
            return 'co_await ' + self.a.show()
        if k == 'comma':
            return self.a.show() + ', ' + self.b.show()
        if k == 'paren':
            # A parenthesized operand: `(a)`.
            return '(' + self.a.show() + ')'
        if k == 'cast':
            return '(' + self.ty.name + ')' + self.a.show()
        if k == 'call':
            parts: list[str] = []
            for x in self.args:
                parts.append(x.show())
            gap = '' if self.tight else ' '
            return self.a.show() + gap + '(' + ', '.join(parts) + ')'
        if k == 'bin':
            return self.a.show() + ' ' + self.op + ' ' + self.b.show()
        if k == 'cond':
            return self.a.show() + ' ? ' + self.b.show() + ' : ' + self.c.show()
        if k == 'lambda':
            # `[&]() -> T { stmt stmt }()`: a call-once lambda; `text` is T's C spelling,
            # or '' for a lambda with no return type (`[&]() { ... }()`). An empty
            # statement (an opaque block that came out empty) takes no separator.
            head = '[&]() -> ' + self.text if self.text else '[&]()'
            parts = [st.show() for st in self.body]
            return head + ' { ' + ' '.join(p for p in parts if p != '') + ' }()'
        if k == 'none':
            return ''
        return '<opaque>'


def ex_var(name: str) -> Ex:
    e = Ex('var')
    e.name = name
    return e


def ex_none() -> Ex:
    return Ex('none')


def ex_text(text: str) -> Ex:
    """An operand already spelled as C/C++ text (a lowered sub-expression)."""
    e = Ex('str')
    e.text = text
    return e


def ex_bin(a: Ex, op: str, b: Ex) -> Ex:
    e = Ex('bin')
    e.op = op
    e.a = a
    e.b = b
    return e


def ex_deref(a: Ex) -> Ex:
    e = Ex('deref')
    e.a = a
    return e


class Instr:
    def __init__(self, kind: str):
        self.kind: str = kind
        self.lhs: Ex = ex_none()
        self.rhs: Ex = ex_none()
        self.body: Instr = self     # self = "absent"; keeps the field typed
        self.label: str = ''
        self.label2: str = ''
        self.text: str = ''
        self.note: str = ''         # trailing comment, `  /* ... */`
        # Statement indent.  A block's body is still a flat list of
        # instructions here (an emitting site opens it and closes it), so the
        # one thing a nested statement needs from the IR is its depth.
        self.indent: int = 2
        self.src_line: int = 0      # source (#line) line
        self.out_line: int = 0      # physical line in the .ci

    def show(self) -> str:
        k = self.kind
        if k == 'assign':
            return self.lhs.show() + ' = ' + self.rhs.show() + ';' + self.note
        if k == 'expr':
            return self.rhs.show() + ';' + self.note
        if k == 'goto':
            return 'goto ' + self.label + ';'
        if k == 'cgoto':
            if self.label2:
                return ('if (' + self.rhs.show() + ') goto ' + self.label
                        + '; else goto ' + self.label2 + ';')
            return 'if (' + self.rhs.show() + ') goto ' + self.label + ';'
        if k == 'return':
            if self.rhs.kind == 'none':
                return 'return;'
            return 'return ' + self.rhs.show() + ';'
        if k == 'while':
            return 'while (' + self.rhs.show() + ') {'
        if k == 'decl':
            # A declaration `<type> <name>;` with no initialiser.
            return self.rhs.show() + ';'
        if k == 'throw':
            # A C++ `throw <expr>;` (the raise printer).
            return 'throw ' + self.rhs.show() + ';'
        if k == 'block':
            # A bare `{` opening a C block with no header of its own.
            return '{'
        if k == 'for':
            # A C `for (<header>) {`; the header is one expression, as for `while`.
            return 'for (' + self.rhs.show() + ') {'
        if k == 'break':
            return 'break;'
        if k == 'coyield':
            # A C++ coroutine's `co_yield <expr>;` (the generator printer).
            return 'co_yield ' + self.rhs.show() + ';'
        if k == 'coreturn':
            # A C++ coroutine's `co_return` (the generator and async printers).
            if self.rhs.kind == 'none':
                return 'co_return;'
            return 'co_return ' + self.rhs.show() + ';'
        if k == 'label':
            return self.label + ':'
        if k == 'comment':
            return self.text
        if k == 'if':
            return 'if (' + self.rhs.show() + ') {'
        if k == 'else':
            return 'else {'
        if k == 'elseif':
            return 'else if (' + self.rhs.show() + ') {'
        if k == 'end':
            return '}'
        if k == 'ifbody':
            return 'if (' + self.rhs.show() + ') ' + self.body.show()
        return self.text

    def line(self) -> str:
        """The statement as the gimple backend prints it (doc/GIR.md, stage 3c).

        `show()` renders the statement itself; this adds what a C body needs
        around it, so the function-assembly sites print a body with one rule
        instead of one rule per statement kind:

          - a modelled statement is indented `indent` spaces (two for a
            statement at the body's own depth), the statement indentation of
            every `__GIMPLE` body this backend writes;
          - 'opaque' text is printed verbatim (it carries its own indentation
            and may be anything a statement lowers to);
          - a label is at column 0 and starts its own block, which is why the
            backend writes a blank line in front of it."""
        if self.kind == 'opaque':
            return self.text
        if self.kind == 'label':
            return '\n' + self.show() + self.text
        return ' ' * self.indent + self.show()


class Sig:
    """A function signature."""

    def __init__(self, name: str, ret: Type):
        self.name: str = name
        self.ret: Type = ret
        self.params: list[Type] = []
        self.variadic: bool = False
        self.unchecked: bool = False    # `f(...)`: nothing is known
        self.origin: str = ''


class Function:
    def __init__(self, name: str, sig: Sig):
        self.name: str = name
        self.sig: Sig = sig
        self.param_names: list[str] = []
        self.locals: dict[str, Type] = {}
        self.body: list[Instr] = []
        self.tagged: bool = False       # carries __GIMPLE: GCC verifies it
        self.opaque: int = 0            # statements the reader could not model
        self.src_file: str = ''
        self.out_line: int = 0


class Module:
    def __init__(self, path: str):
        self.path: str = path
        self.structs: dict[str, dict[str, Type]] = {}
        self.globals: dict[str, Type] = {}
        self.sigs: dict[str, Sig] = {}
        self.consts: dict[str, bool] = {}     # macro / enumerator names
        self.functions: list[Function] = []
        self.skipped: int = 0                 # top-level items not modelled
