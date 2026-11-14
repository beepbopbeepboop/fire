"""TRANSITIONAL: build a `Module` from emitted `.ci` text (and from the
runtime headers it includes).

This exists so `verify.py` can check the output of today's backend, which
emits text.  It is a tool-side module: it uses `re`, and the compiler must
never import it.  When the backend builds `Instr` objects directly this file
is only needed for the headers.

It is a tolerant reader, not a C front end.  Anything it cannot model is
counted (`Module.skipped`, `Function.opaque`) and left unchecked; it never
guesses a type.
"""
from __future__ import annotations

import os
import re

from mojo.ir.types import (Type, VOID, INT, I64, U64, FN, FNP, BASE_TYPES,
                           BASE_WORDS, ptr_to, struct_named)
from mojo.ir.instr import Ex, Instr, Function, Module, Sig, ex_var, ex_none

_TOK = re.compile(r'''
    (?P<ws>[ \t\r\f\v]+|\\\n)
  | (?P<nl>\n)
  | (?P<com>//[^\n]*|/\*.*?\*/)
  | (?P<pp>\#(?:[^\n/\\]|/(?!\*)|\\\n|\\.|/\*.*?\*/)*)
  | (?P<id>[A-Za-z_$][A-Za-z_0-9$]*)
  | (?P<num>(?:0[xX][0-9a-fA-F]+|[0-9]+\.[0-9]*(?:[eE][-+]?[0-9]+)?|\.[0-9]+(?:[eE][-+]?[0-9]+)?|[0-9]+[eE][-+]?[0-9]+|[0-9]+)[uUlLfF]*)
  | (?P<str>"(?:\\.|[^"\\\n])*")
  | (?P<chr>'(?:\\.|[^'\\\n])*')
  | (?P<op>->|\+\+|--|<<=|>>=|<<|>>|<=|>=|==|!=|&&|\|\||\.\.\.|[-+*/%&|^]=|[{}()\[\];,.:?~!<>=+\-*/%&|^@])
''', re.S | re.X)

_LINE_RE = re.compile(r'#\s*(?:line\s+)?(\d+)\s+"([^"]*)"')
_DEFINE_RE = re.compile(r'#\s*define\s+([A-Za-z_]\w*)(\()?')
_INCLUDE_RE = re.compile(r'#\s*include\s*[<"]([^>"]+)[>"]')

_QUALS = frozenset(('const', 'volatile', 'restrict', '__restrict', 'static', 'extern',
                    'inline', '__inline', '__inline__', 'register', '_Noreturn',
                    '__extension__', '__GIMPLE', '_Thread_local', '__thread',
                    '_Nullable', '_Nonnull', '__unused'))
_ATTRS = frozenset(('__attribute__', '__attribute', '__asm', '__asm__', '_Alignas',
                    '__declspec'))
_STMT_KEYWORDS = frozenset(('for', 'while', 'do', 'switch', 'case', 'default', 'break',
                            'continue', 'else', 'try', 'catch', 'finally', 'asm'))
_BINPREC = {'||': 1, '&&': 2, '|': 3, '^': 4, '&': 5, '==': 6, '!=': 6,
            '<': 7, '>': 7, '<=': 7, '>=': 7, '<<': 8, '>>': 8,
            '+': 9, '-': 9, '*': 10, '/': 10, '%': 10}


class ParseError(Exception):
    pass


class Reader:
    def __init__(self, mod: Module, include_dirs: list[str]):
        self.mod = mod
        self.include_dirs = include_dirs
        self.typedefs: dict[str, Type] = dict(BASE_TYPES)
        self.seen_includes: set[str] = set()
        self.kinds: list[str] = []
        self.vals: list[str] = []
        self.plines: list[int] = []      # physical line of each token
        self.slines: list[int] = []      # source (#line) line of each token
        self.i = 0
        self.fn: Function | None = None
        self.header_mode = False
        self.anon = 0

    # ---- lexing -----------------------------------------------------------
    def lex(self, text: str, path: str) -> None:
        kinds, vals, plines, slines = [], [], [], []
        pline = 1
        sline = 0
        for m in _TOK.finditer(text):
            k = m.lastgroup
            if k == 'ws':
                continue
            v = m.group()
            if k == 'nl':
                pline += 1
                continue
            if k == 'com':
                pline += v.count('\n')
                continue
            if k == 'pp':
                lm = _LINE_RE.match(v)
                if lm:
                    sline = int(lm.group(1))
                else:
                    dm = _DEFINE_RE.match(v)
                    if dm:
                        self.mod.consts[dm.group(1)] = True
                    else:
                        im = _INCLUDE_RE.match(v)
                        if im:
                            self.include(im.group(1))
                pline += v.count('\n')
                continue
            kinds.append(k)
            vals.append(v)
            plines.append(pline)
            slines.append(sline)
        kinds.append('eof')
        vals.append('')
        plines.append(pline)
        slines.append(sline)
        self.kinds, self.vals, self.plines, self.slines = kinds, vals, plines, slines
        self.i = 0

    def include(self, name: str) -> None:
        if name in self.seen_includes:
            return
        self.seen_includes.add(name)
        for d in self.include_dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                sub = Reader(self.mod, self.include_dirs)
                sub.typedefs = self.typedefs
                sub.seen_includes = self.seen_includes
                sub.header_mode = True
                with open(p, encoding='utf-8', errors='replace') as f:
                    sub.lex(f.read(), p)
                sub.parse_toplevel()
                return

    # ---- token helpers ----------------------------------------------------
    def peek(self, n: int = 0) -> str:
        j = self.i + n
        return self.vals[j] if j < len(self.vals) else ''

    def pkind(self, n: int = 0) -> str:
        j = self.i + n
        return self.kinds[j] if j < len(self.kinds) else 'eof'

    def eat(self, v: str) -> bool:
        if self.vals[self.i] == v and self.kinds[self.i] != 'str':
            self.i += 1
            return True
        return False

    def expect(self, v: str) -> None:
        if not self.eat(v):
            raise ParseError(f"expected {v!r}, got {self.peek()!r} at line {self.plines[self.i]}")

    def ident(self) -> str:
        if self.kinds[self.i] != 'id':
            raise ParseError(f"expected identifier, got {self.peek()!r}")
        self.i += 1
        return self.vals[self.i - 1]

    def skip_balanced(self, open_: str, close: str) -> None:
        """At `open_`: skip to just past its matching `close`."""
        self.expect(open_)
        depth = 1
        while depth and self.kinds[self.i] != 'eof':
            v = self.vals[self.i]
            if self.kinds[self.i] == 'op':
                if v == open_:
                    depth += 1
                elif v == close:
                    depth -= 1
            self.i += 1

    def skip_attrs(self) -> bool:
        """Skip qualifiers / attributes.  Returns True if __GIMPLE was seen."""
        tagged = False
        while self.kinds[self.i] == 'id':
            v = self.vals[self.i]
            if v in _QUALS:
                if v == '__GIMPLE':
                    tagged = True
                self.i += 1
                if v == '__GIMPLE' and self.peek() == '(':
                    self.skip_balanced('(', ')')
            elif v in _ATTRS:
                self.i += 1
                if self.peek() == '(':
                    self.skip_balanced('(', ')')
            else:
                break
        return tagged

    # ---- types ------------------------------------------------------------
    def at_type(self) -> bool:
        if self.kinds[self.i] != 'id':
            return False
        v = self.vals[self.i]
        return (v in _QUALS or v in BASE_WORDS or v in ('struct', 'union', 'enum')
                or v in self.typedefs or v in _ATTRS)

    def type_spec(self, allow_unknown: bool) -> Type:
        """Declaration specifiers (no pointer stars)."""
        words: list[str] = []
        ty: Type | None = None
        while True:
            self.skip_attrs()
            if self.kinds[self.i] != 'id':
                break
            v = self.vals[self.i]
            if v in ('struct', 'union'):
                self.i += 1
                self.skip_attrs()
                tag = ''
                if self.kinds[self.i] == 'id':
                    tag = self.ident()
                if not tag:
                    self.anon += 1
                    tag = f'<anon{self.anon}>'
                ty = struct_named(tag)
                if self.peek() == '{':
                    self.struct_body(tag)
                continue
            if v == 'enum':
                self.i += 1
                if self.kinds[self.i] == 'id':
                    self.i += 1
                if self.peek() == '{':
                    self.enum_body()
                ty = INT
                continue
            if v in BASE_WORDS and ty is None:
                words.append(v)
                self.i += 1
                continue
            if ty is None and not words and v in self.typedefs:
                ty = self.typedefs[v]
                self.i += 1
                continue
            break
        if words:
            name = ' '.join(words)
            ty = BASE_TYPES.get(name)
            if ty is None:
                # order-insensitive spellings: `long unsigned int`, ...
                ws = sorted(w for w in words if w != 'int')
                key = ' '.join(ws)
                ty = {'long unsigned': U64, 'long long unsigned': U64, 'long': I64,
                      'long long': I64, 'unsigned': BASE_TYPES['unsigned int'],
                      'long signed': I64, 'char unsigned': BASE_TYPES['unsigned char'],
                      'char signed': BASE_TYPES['char'],
                      'short unsigned': BASE_TYPES['unsigned short'],
                      'short': BASE_TYPES['short'], 'double long': BASE_TYPES['long double'],
                      '': INT}.get(key)
                if ty is None:
                    raise ParseError(f"unknown base type {name!r}")
        if ty is None:
            if allow_unknown and self.kinds[self.i] == 'id':
                # an identifier in type position that nobody declared: an
                # opaque named type (a system-header typedef such as FILE)
                ty = struct_named(self.ident())
                self.skip_attrs()
            else:
                raise ParseError(f"expected a type, got {self.peek()!r}")
        return ty

    def stars(self, ty: Type) -> Type:
        while True:
            self.skip_attrs()
            if self.peek() == '*' and self.kinds[self.i] == 'op':
                self.i += 1
                ty = ptr_to(ty)
            else:
                return ty

    def struct_body(self, tag: str) -> None:
        fields: dict[str, Type] = {}
        self.expect('{')
        while self.peek() != '}' and self.kinds[self.i] != 'eof':
            start = self.i
            try:
                base = self.type_spec(True)
                while True:
                    ty, name = self.declarator(base)
                    if name:
                        fields[name] = ty
                    if self.eat(':'):          # bit-field
                        self.i += 1
                    if not self.eat(','):
                        break
                self.expect(';')
            except ParseError:
                self.i = start
                self.skip_to_semicolon()
        self.expect('}')
        self.mod.structs[tag] = fields

    def enum_body(self) -> None:
        self.expect('{')
        while self.peek() != '}' and self.kinds[self.i] != 'eof':
            if self.kinds[self.i] == 'id':
                self.mod.consts[self.vals[self.i]] = True
            self.i += 1
        self.expect('}')

    def declarator(self, base: Type) -> tuple[Type, str]:
        """`* name`, `name[N]`, `(*name)(params)`.  Returns (type, name);
        name is '' for an abstract declarator."""
        ty = self.stars(base)
        name = ''
        if self.peek() == '(' and self.peek(1) in ('*', '^'):
            # function pointer: ( * name ) ( params )
            self.i += 2
            self.skip_attrs()
            if self.kinds[self.i] == 'id':
                name = self.ident()
            while self.peek() == '[':
                self.skip_balanced('[', ']')
            self.expect(')')
            if self.peek() == '(':
                self.skip_balanced('(', ')')
            return FNP, name
        if self.kinds[self.i] == 'id' and self.vals[self.i] not in _QUALS:
            name = self.ident()
        self.skip_attrs()
        while self.peek() == '[':
            self.skip_balanced('[', ']')
            ty = ptr_to(ty)      # an array decays; element access is what we type
        self.skip_attrs()
        return ty, name

    def params(self, sig: Sig) -> list[str]:
        """At `(`.  Fills sig.params / variadic; returns parameter names."""
        names: list[str] = []
        self.expect('(')
        if self.eat(')'):
            sig.unchecked = True     # K&R `f()`: nothing known
            return names
        if self.peek() == 'void' and self.peek(1) == ')':
            self.i += 2
            return names
        if self.peek() == '...' and self.peek(1) == ')':
            self.i += 2
            sig.unchecked = True
            return names
        while True:
            if self.eat('...'):
                sig.variadic = True
                break
            base = self.type_spec(True)
            ty, name = self.declarator(base)
            if self.peek() == '(':          # `T name(params)`: a function parameter
                self.skip_balanced('(', ')')
                ty = FNP
            sig.params.append(ty)
            names.append(name)
            if not self.eat(','):
                break
        self.expect(')')
        return names

    # ---- top level --------------------------------------------------------
    def skip_to_semicolon(self) -> None:
        while self.kinds[self.i] != 'eof':
            if self.kinds[self.i] == 'op':
                v = self.vals[self.i]
                if v == ';':
                    self.i += 1
                    return
                if v == '{':
                    self.skip_balanced('{', '}')
                    # `}` ends a function body; `} name;` continues
                    if self.peek() != ';' and self.kinds[self.i] != 'id' and self.peek() != '*':
                        return
                    continue
                if v == '(':
                    self.skip_balanced('(', ')')
                    continue
                if v == '}':
                    return
            self.i += 1

    def parse_toplevel(self) -> None:
        while self.kinds[self.i] != 'eof':
            start = self.i
            try:
                self.external_decl()
            except ParseError:
                self.i = start
                self.skip_to_semicolon()
                if self.i == start:
                    self.i += 1
                self.mod.skipped += 1

    def external_decl(self) -> None:
        if self.eat(';'):
            return
        if self.peek() == '}' and self.kinds[self.i] == 'op':
            self.i += 1                 # closes an `extern "C" {`
            return
        tagged = self.skip_attrs()
        if self.kinds[self.i] == 'str':
            self.i += 1                 # extern "C"
            if self.eat('{'):
                return
        if self.eat('typedef'):
            base = self.type_spec(True)
            while True:
                ty, name = self.declarator(base)
                if self.peek() == '(':                 # typedef of a function type
                    self.skip_balanced('(', ')')
                    ty = FN
                if name:
                    self.typedefs[name] = ty
                    if (ty.kind == 'struct' and ty.name.startswith('<anon')
                            and ty.name in self.mod.structs):
                        # `typedef struct {...} Name;` -- the name IS the struct
                        named = struct_named(name)
                        self.mod.structs[name] = self.mod.structs[ty.name]
                        self.typedefs[name] = named
                    elif ty.kind == 'struct' and ty.name != name and ty.name in self.mod.structs:
                        self.mod.structs.setdefault(name, self.mod.structs[ty.name])
                if not self.eat(','):
                    break
            self.expect(';')
            return
        base = self.type_spec(True)
        if self.eat(';'):
            return                                  # `struct X {...};`
        while True:
            ty = self.stars(base)
            tagged = self.skip_attrs() or tagged
            if self.peek() == '(' and self.peek(1) in ('*', '^'):
                ty, name = self.declarator(base)
                if name:
                    self.mod.globals[name] = ty
            else:
                name = self.ident()
                self.skip_attrs()
                if self.peek() == '(':
                    self.function(name, ty, tagged)
                    if self.vals[self.i - 1] == '}':
                        return
                else:
                    while self.peek() == '[':
                        self.skip_balanced('[', ']')
                        ty = ptr_to(ty)
                    self.skip_attrs()
                    if not self.header_mode or name not in self.mod.globals:
                        self.mod.globals[name] = ty
            if self.eat('='):
                self.skip_initializer()
            if not self.eat(','):
                break
        self.expect(';')

    def skip_initializer(self) -> None:
        while self.kinds[self.i] != 'eof':
            v = self.vals[self.i]
            if self.kinds[self.i] == 'op':
                if v == '{':
                    self.skip_balanced('{', '}')
                    continue
                if v == '(':
                    self.skip_balanced('(', ')')
                    continue
                if v in (';', ','):
                    return
            self.i += 1

    def function(self, name: str, ret: Type, tagged: bool) -> None:
        sig = Sig(name, ret)
        sig.origin = self.mod.path if not self.header_mode else 'header'
        names = self.params(sig)
        self.skip_attrs()
        old = self.mod.sigs.get(name)
        # a real prototype beats `f(...)`; the .ci's own beats a header's
        if old is None or old.unchecked or not sig.unchecked:
            if not (self.header_mode and old is not None and not old.unchecked):
                self.mod.sigs[name] = sig
        if self.peek() != '{':
            return
        fn = Function(name, sig)
        fn.tagged = tagged
        fn.param_names = names
        fn.out_line = self.plines[self.i]
        k = 0
        while k < len(names):
            if names[k]:
                fn.locals[names[k]] = sig.params[k]
            k += 1
        if self.header_mode:
            self.skip_balanced('{', '}')
            return
        self.fn = fn
        self.body()
        self.fn = None
        self.mod.functions.append(fn)

    # ---- function bodies ---------------------------------------------------
    def body(self) -> None:
        fn = self.fn
        self.expect('{')
        while self.peek() != '}' and self.kinds[self.i] != 'eof':
            start = self.i
            try:
                self.statement()
            except ParseError:
                self.i = start
                ins = Instr('opaque')
                ins.out_line = self.plines[start]
                ins.src_line = self.slines[start]
                self.skip_statement()
                ins.text = ' '.join(self.vals[start:self.i])[:200]
                fn.body.append(ins)
                fn.opaque += 1
        self.expect('}')

    def skip_statement(self) -> None:
        """Skip one C statement of any shape."""
        if self.peek() == '{':
            self.skip_balanced('{', '}')
            return
        if self.peek() == 'if':
            self.i += 1
            if self.peek() == '(':
                self.skip_balanced('(', ')')
            self.skip_statement()
            if self.eat('else'):
                self.skip_statement()
            return
        if self.peek() in ('for', 'while', 'switch'):
            self.i += 1
            if self.peek() == '(':
                self.skip_balanced('(', ')')
            self.skip_statement()
            return
        if self.peek() in ('do', 'else'):
            self.i += 1
            self.skip_statement()
            return
        while self.kinds[self.i] != 'eof':
            v = self.vals[self.i]
            if self.kinds[self.i] == 'op':
                if v == ';':
                    self.i += 1
                    return
                if v == '(':
                    self.skip_balanced('(', ')')
                    continue
                if v == '{':
                    self.skip_balanced('{', '}')
                    continue
                if v == '}':
                    return
            self.i += 1

    def is_local_decl(self) -> bool:
        if self.kinds[self.i] != 'id':
            return False
        v = self.vals[self.i]
        if v in self.fn.locals:
            return False
        if self.at_type():
            return True
        # `Name ident;` / `Name * ident;` with an undeclared type name
        j = self.i + 1
        while self.vals[j] == '*' and self.kinds[j] == 'op':
            j += 1
        return (self.kinds[j] == 'id' and self.vals[j + 1] in (';', '=', ',', '[')
                and v not in self.mod.globals and v not in self.mod.sigs)

    def statement(self) -> None:
        fn = self.fn
        start = self.i
        k = self.kinds[start]
        v = self.vals[start]
        if v == ';' and k == 'op':
            self.i += 1
            return
        ins = Instr('opaque')
        ins.out_line = self.plines[start]
        ins.src_line = self.slines[start]
        if k == 'id':
            if v in _STMT_KEYWORDS:
                raise ParseError('control statement')
            if self.peek(1) == ':' and v not in ('default',):
                self.i += 2
                ins.kind = 'label'
                ins.label = v
                fn.body.append(ins)
                return
            if v == 'goto':
                self.i += 1
                ins.kind = 'goto'
                ins.label = self.ident()
                self.expect(';')
                fn.body.append(ins)
                return
            if v == 'return':
                self.i += 1
                ins.kind = 'return'
                if not self.eat(';'):
                    ins.rhs = self.expr()
                    self.expect(';')
                fn.body.append(ins)
                return
            if v == 'if':
                self.i += 1
                self.expect('(')
                cond = self.expr()
                self.expect(')')
                self.expect('goto')
                l1 = self.ident()
                self.expect(';')
                self.expect('else')
                self.expect('goto')
                l2 = self.ident()
                self.expect(';')
                ins.kind = 'cgoto'
                ins.rhs = cond
                ins.label = l1
                ins.label2 = l2
                fn.body.append(ins)
                return
            if self.is_local_decl():
                base = self.type_spec(True)
                while True:
                    ty, name = self.declarator(base)
                    if not name:
                        raise ParseError('declaration without a name')
                    fn.locals[name] = ty
                    if self.eat('='):
                        init = Instr('assign')
                        init.out_line = ins.out_line
                        init.src_line = ins.src_line
                        init.lhs = ex_var(name)
                        if self.peek() == '{':
                            raise ParseError('aggregate initializer')
                        init.rhs = self.assign_expr()
                        fn.body.append(init)
                    if not self.eat(','):
                        break
                self.expect(';')
                return
        if v == '{' and k == 'op':
            raise ParseError('nested block')
        e = self.expr()
        if self.eat('='):
            ins.kind = 'assign'
            ins.lhs = e
            ins.rhs = self.expr()
        else:
            if self.peek() != ';':
                raise ParseError('not a simple statement')
            ins.kind = 'expr'
            ins.rhs = e
        self.expect(';')
        fn.body.append(ins)

    # ---- expressions -------------------------------------------------------
    def assign_expr(self) -> Ex:
        return self.expr()

    def expr(self) -> Ex:
        c = self.binary(1)
        if self.eat('?'):
            e = Ex('cond')
            e.a = c
            e.b = self.expr()
            self.expect(':')
            e.c = self.expr()
            return e
        return c

    def binary(self, minprec: int) -> Ex:
        left = self.unary()
        while self.kinds[self.i] == 'op':
            op = self.vals[self.i]
            prec = _BINPREC.get(op)
            if prec is None or prec < minprec:
                break
            self.i += 1
            right = self.binary(prec + 1)
            e = Ex('bin')
            e.op = op
            e.a = left
            e.b = right
            left = e
        return left

    def is_cast_ahead(self) -> bool:
        """At `(`: is this `(type)`?"""
        j = self.i + 1
        if self.kinds[j] != 'id':
            return False
        v = self.vals[j]
        if v in _QUALS or v in BASE_WORDS or v in ('struct', 'union', 'enum'):
            return True
        if v in self.typedefs:
            # a local or global may shadow nothing here; typedef names win
            return v not in self.fn.locals if self.fn else True
        # `(Name *)` / `(Name **)` with an undeclared type name
        j += 1
        n = 0
        while self.vals[j] == '*' and self.kinds[j] == 'op':
            j += 1
            n += 1
        return n > 0 and self.vals[j] == ')'

    def unary(self) -> Ex:
        k = self.kinds[self.i]
        v = self.vals[self.i]
        if k == 'op':
            if v == '(':
                if self.is_cast_ahead():
                    self.i += 1
                    ty = self.stars(self.type_spec(True))
                    if self.peek() == '(' and self.peek(1) == '*':
                        # (T (*)(params)) -- a function-pointer cast
                        self.skip_balanced('(', ')')
                        if self.peek() == '(':
                            self.skip_balanced('(', ')')
                        ty = FNP
                    self.expect(')')
                    if self.peek() == '{':
                        raise ParseError('compound literal')
                    e = Ex('cast')
                    e.ty = ty
                    e.a = self.unary()
                    return e
                self.i += 1
                e = self.expr()
                self.expect(')')
                return self.postfix(e)
            if v in ('-', '~', '!', '+'):
                self.i += 1
                e = Ex('un')
                e.op = v
                e.a = self.unary()
                return e
            if v == '&':
                self.i += 1
                e = Ex('addr')
                e.a = self.unary()
                return e
            if v == '*':
                self.i += 1
                e = Ex('deref')
                e.a = self.unary()
                return e
            raise ParseError(f"unexpected {v!r} in expression")
        if k == 'num':
            self.i += 1
            low = v.lower()
            if low.startswith('0x'):
                digits = low.rstrip('ul')
                e = Ex('int')
                e.ival = int(digits, 16)
                e.suffix = low[len(digits):]
            elif any(c in low for c in '.e') or low.endswith('f'):
                e = Ex('float')
            else:
                digits = low.rstrip('ul')
                e = Ex('int')
                e.ival = int(digits)
                e.suffix = low[len(digits):]
            e.text = v
            return e
        if k == 'str':
            self.i += 1
            e = Ex('str')
            e.text = v
            while self.kinds[self.i] == 'str':      # adjacent literals
                self.i += 1
            return e
        if k == 'chr':
            self.i += 1
            e = Ex('int')
            e.text = v
            e.ival = 0
            return e
        if k == 'id':
            if v == 'sizeof' or v == '_Alignof':
                self.i += 1
                if self.peek() == '(':
                    self.skip_balanced('(', ')')
                else:
                    self.unary()
                e = Ex('cast')
                e.ty = U64
                e.a = Ex('opaque')
                o = Ex('int')
                o.text = 'sizeof'
                o.suffix = 'ul'
                return o
            if v == '_Literal':
                self.i += 1
                self.expect('(')
                ty = self.stars(self.type_spec(True))
                self.expect(')')
                e = Ex('cast')
                e.ty = ty
                e.a = self.unary()
                return e
            if v in _STMT_KEYWORDS or v in ('goto', 'return', 'if'):
                raise ParseError('keyword in expression')
            self.i += 1
            return self.postfix(ex_var(v))
        raise ParseError(f"unexpected {v!r} in expression")

    def postfix(self, e: Ex) -> Ex:
        while self.kinds[self.i] == 'op':
            v = self.vals[self.i]
            if v == '->' or v == '.':
                self.i += 1
                f = Ex('field')
                f.a = e
                f.arrow = v == '->'
                f.name = self.ident()
                e = f
            elif v == '[':
                self.i += 1
                x = Ex('index')
                x.a = e
                x.b = self.expr()
                self.expect(']')
                e = x
            elif v == '(':
                self.i += 1
                c = Ex('call')
                c.a = e
                if not self.eat(')'):
                    while True:
                        c.args.append(self.expr())
                        if not self.eat(','):
                            break
                    self.expect(')')
                e = c
            elif v in ('++', '--'):
                raise ParseError('increment')
            else:
                break
        return e


# The system-header functions emitted code calls.  Parsed by this same reader,
# so the table is C, not a second notation.
_LIBC = """
void free(void *); void *malloc(size_t); void *calloc(size_t, size_t);
void *realloc(void *, size_t); void *memset(void *, int, size_t);
void *memcpy(void *, const void *, size_t); void *memmove(void *, const void *, size_t);
int memcmp(const void *, const void *, size_t);
char *strdup(const char *); size_t strlen(const char *);
int strcmp(const char *, const char *); int strncmp(const char *, const char *, size_t);
char *strcpy(char *, const char *); char *strcat(char *, const char *);
char *strchr(const char *, int); char *strstr(const char *, const char *);
int sprintf(char *, const char *, ...); int snprintf(char *, size_t, const char *, ...);
int printf(const char *, ...); int puts(const char *); int putchar(int);
int setenv(const char *, const char *, int); char *getenv(const char *);
void exit(int); void abort(void); int atoi(const char *);
double pow(double, double); double sqrt(double); double fabs(double);
double floor(double); double ceil(double); double fmod(double, double);
double sin(double); double cos(double); double tan(double); double exp(double);
double log(double); double log2(double); double log10(double); double round(double);
void Py_Initialize(void); void Py_Finalize(void);
"""


def read_ci(path: str, include_dirs: list[str]) -> Module:
    mod = Module(path)
    pre = Reader(mod, include_dirs)
    pre.header_mode = True
    pre.lex(_LIBC, '<libc>')
    pre.parse_toplevel()
    rd = Reader(mod, include_dirs)
    rd.typedefs = pre.typedefs
    with open(path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    rd.lex(text, path)
    rd.parse_toplevel()
    return mod
