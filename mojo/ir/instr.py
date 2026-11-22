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
  'opaque' ty                         something the reader does not model

Instr.kind
  'assign' lhs, rhs
  'expr'   rhs                        a call for effect
  'goto'   label
  'cgoto'  rhs (condition), label, label2
  'return' rhs (kind 'none' Ex when there is no value)
  'label'  label
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
        self.ty: Type = VOID
        self.a: Ex = self          # self = "absent"; keeps the field typed
        self.b: Ex = self
        self.c: Ex = self
        self.args: list[Ex] = []

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
        if k == 'cast':
            return '(' + self.ty.name + ')' + self.a.show()
        if k == 'call':
            parts: list[str] = []
            for x in self.args:
                parts.append(x.show())
            return self.a.show() + ' (' + ', '.join(parts) + ')'
        if k == 'bin':
            return self.a.show() + ' ' + self.op + ' ' + self.b.show()
        if k == 'cond':
            return self.a.show() + ' ? ' + self.b.show() + ' : ' + self.c.show()
        if k == 'none':
            return ''
        return '<opaque>'


def ex_var(name: str) -> Ex:
    e = Ex('var')
    e.name = name
    return e


def ex_none() -> Ex:
    return Ex('none')


class Instr:
    def __init__(self, kind: str):
        self.kind: str = kind
        self.lhs: Ex = ex_none()
        self.rhs: Ex = ex_none()
        self.label: str = ''
        self.label2: str = ''
        self.text: str = ''
        self.src_line: int = 0      # source (#line) line
        self.out_line: int = 0      # physical line in the .ci

    def show(self) -> str:
        k = self.kind
        if k == 'assign':
            return self.lhs.show() + ' = ' + self.rhs.show() + ';'
        if k == 'expr':
            return self.rhs.show() + ';'
        if k == 'goto':
            return 'goto ' + self.label + ';'
        if k == 'cgoto':
            return ('if (' + self.rhs.show() + ') goto ' + self.label
                    + '; else goto ' + self.label2 + ';')
        if k == 'return':
            if self.rhs.kind == 'none':
                return 'return;'
            return 'return ' + self.rhs.show() + ';'
        if k == 'label':
            return self.label + ':'
        return self.text


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
