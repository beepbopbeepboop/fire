"""Recursive-descent parser for Formal English source code.

Consumes a token stream from lexer.py and produces an AST (ast_nodes.py).

Grammar summary
---------------
module          := stmt* EOF
stmt            := simple_stmt | compound_stmt
simple_stmt     := one_stmt (';' one_stmt)* NEWLINE
one_stmt        := import_stmt | from_import_stmt | declare_stmt | assign_stmt
                 | aug_assign_stmt | return_stmt | raise_stmt | break_stmt
                 | continue_stmt | pass_stmt | print_stmt | assert_stmt
                 | expr_stmt | field_decl
compound_stmt   := if_stmt | while_stmt | for_stmt | try_stmt | with_stmt
                 | func_def | struct_def | trait_def
block           := NEWLINE INDENT stmt+ DEDENT
"""
from __future__ import annotations
from typing import Optional
from lexer import Token, TT, tokenize
import ast_nodes as N


# ---------------------------------------------------------------------------
# Token stream wrapper
# ---------------------------------------------------------------------------

class TokenStream:
    def __init__(self, tokens: list[Token], filename: str = ""):
        self._tokens = tokens
        self._pos = 0
        self.filename = filename

    def peek(self, offset: int = 0) -> Token:
        pos = self._pos + offset
        if pos < len(self._tokens):
            return self._tokens[pos]
        return self._tokens[-1]  # EOF

    def advance(self) -> Token:
        t = self._tokens[self._pos]
        if self._pos < len(self._tokens) - 1:
            self._pos += 1
        return t

    def eat(self, tt: TT, value: str = None) -> Token:
        t = self.peek()
        if t.type != tt:
            raise SyntaxError(
                f"Expected {tt.name} but got {t.type.name} ({t.value!r}) at {t.line}:{t.col}")
        if value is not None and t.value != value:
            raise SyntaxError(
                f"Expected {value!r} but got {t.value!r} at {t.line}:{t.col}")
        return self.advance()

    def eat_name(self, name: str) -> Token:
        return self.eat(TT.NAME, name)

    def match(self, tt: TT, value: str = None) -> bool:
        t = self.peek()
        if t.type != tt:
            return False
        if value is not None and t.value != value:
            return False
        return True

    def match_name(self, *names: str) -> bool:
        t = self.peek()
        return t.type == TT.NAME and t.value in names

    def skip_newlines(self):
        while self.match(TT.NEWLINE):
            self.advance()

    def line(self) -> int:
        return self.peek().line


# ---------------------------------------------------------------------------
# Helper: look-ahead for multi-word phrases
# ---------------------------------------------------------------------------

def _peek_words(ts: TokenStream, n: int) -> list[str]:
    """Return up to n upcoming NAME token values (skipping nothing else)."""
    words = []
    offset = 0
    while len(words) < n:
        t = ts.peek(offset)
        if t.type == TT.NAME:
            words.append(t.value)
            offset += 1
        else:
            break
    return words


# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------

def parse(source: str, filename: str = "") -> N.Module:
    tokens = tokenize(source)
    ts = TokenStream(tokens, filename=filename)
    body = parse_stmts(ts, top_level=True)
    ts.eat(TT.EOF)
    t = ts.peek()
    return N.Module(body=body, filename=filename, line=t.line, col=t.col)


def parse_stmts(ts: TokenStream, top_level: bool = False) -> list:
    stmts = []
    ts.skip_newlines()
    while not ts.match(TT.EOF) and not ts.match(TT.DEDENT):
        stmts.extend(parse_stmt(ts))
        ts.skip_newlines()
    return stmts


def parse_block(ts: TokenStream) -> list:
    """Parse an indented block: NEWLINE INDENT stmts DEDENT."""
    ts.eat(TT.NEWLINE)
    ts.skip_newlines()
    ts.eat(TT.INDENT)
    stmts = []
    ts.skip_newlines()
    while not ts.match(TT.DEDENT) and not ts.match(TT.EOF):
        stmts.extend(parse_stmt(ts))
        ts.skip_newlines()
    ts.eat(TT.DEDENT)
    return stmts


def parse_stmt(ts: TokenStream) -> list:
    """Return a list of statements (semicolons can produce multiple)."""
    t = ts.peek()

    # Compound statements
    if t.type == TT.NAME:
        v = t.value
        if v == 'If':
            return [parse_if(ts)]
        if v == 'While':
            return [parse_while(ts)]
        if v in ('For',):
            return [parse_for(ts)]
        if v == 'Try':
            return [parse_try(ts)]
        if v == 'Using':
            return [parse_with(ts)]
        if v == 'Define':
            return [parse_define(ts)]

    # Simple statements (may be semicolon-separated on one line)
    stmts = []
    stmts.append(parse_simple_one(ts))
    while ts.match(TT.SEMICOLON):
        ts.advance()
        stmts.append(parse_simple_one(ts))
    if ts.match(TT.NEWLINE):
        ts.advance()
    return stmts


def parse_simple_one(ts: TokenStream):
    t = ts.peek()
    if t.type != TT.NAME:
        return N.ExprStmt(parse_expr(ts))

    v = t.value

    if v == 'Import':
        return parse_import(ts)
    if v == 'From':
        return parse_from_import(ts)
    if v == 'Declare':
        return parse_declare(ts)
    if v == 'Set':
        return parse_set(ts)
    if v in ('Increase', 'Decrease', 'Multiply', 'Divide', 'Modulo'):
        return parse_aug_assign(ts)
    if v == 'Return':
        return parse_return(ts)
    if v == 'Raise':
        return parse_raise(ts)
    if v == 'Break':
        ts.advance()
        return N.BreakStmt()
    if v == 'Continue':
        ts.advance()
        return N.ContinueStmt()
    if v == 'Pass':
        ts.advance()
        return N.PassStmt()
    if v == 'Print':
        return parse_print(ts)
    if v == 'Assert':
        return parse_assert(ts)
    if v == 'Field':
        return parse_field(ts)

    # Default: expression statement (may be assignment)
    expr = parse_expr(ts)
    if ts.match(TT.EQUALS):
        ts.advance()
        val = parse_expr(ts)
        return N.AssignStmt(targets=[expr], value=val)
    return N.ExprStmt(expr)


# ---------------------------------------------------------------------------
# Simple statement parsers
# ---------------------------------------------------------------------------

def parse_import(ts: TokenStream):
    t = ts.peek()
    line, col = t.line, t.col
    ts.eat_name('Import')
    parts = [ts.eat(TT.NAME).value]
    while ts.match(TT.DOT):
        ts.advance()
        parts.append(ts.eat(TT.NAME).value)
    module = '.'.join(parts)
    alias = None
    if ts.match_name('as'):
        ts.advance()
        alias = ts.eat(TT.NAME).value
    return N.ImportStmt(module=module, alias=alias, line=line, col=col)


def parse_from_import(ts: TokenStream):
    ts.eat_name('From')
    parts = [ts.eat(TT.NAME).value]
    while ts.match(TT.DOT):
        ts.advance()
        parts.append(ts.eat(TT.NAME).value)
    module = '.'.join(parts)
    ts.eat_name('import')
    if ts.match_name('all'):
        ts.advance()
        return N.FromImportStmt(module=module, wildcard=True)
    names = []
    name = ts.eat(TT.NAME).value
    alias = None
    if ts.match_name('as'):
        ts.advance()
        alias = ts.eat(TT.NAME).value
    names.append((name, alias))
    while ts.match(TT.COMMA):
        ts.advance()
        name = ts.eat(TT.NAME).value
        alias = None
        if ts.match_name('as'):
            ts.advance()
            alias = ts.eat(TT.NAME).value
        names.append((name, alias))
    return N.FromImportStmt(module=module, names=names)


def parse_declare(ts: TokenStream):
    t = ts.peek()
    line, col = t.line, t.col
    ts.eat_name('Declare')
    name = ts.eat(TT.NAME).value
    type_ann = None
    value = None
    if ts.match_name('of'):
        ts.advance()
        ts.eat_name('type')
        type_ann = parse_type_expr(ts)
    if ts.match_name('as') or ts.match_name('with'):
        ts.advance()
        if ts.match_name('value'):
            ts.advance()
        value = parse_expr(ts)
    return N.DeclareStmt(name=name, type_ann=type_ann, value=value, line=line, col=col)


def parse_set(ts: TokenStream):
    """Set <target> to <expr>  |  Set <target>'s <field> to <expr>"""
    t = ts.peek()
    line, col = t.line, t.col
    ts.eat_name('Set')
    target = parse_expr(ts)
    ts.eat_name('to')
    value = parse_expr(ts)
    return N.AssignStmt(targets=[target], value=value, line=line, col=col)


def parse_aug_assign(ts: TokenStream):
    op_map = {
        'Increase': '+=',
        'Decrease': '-=',
        'Multiply': '*=',
        'Divide': '/=',
        'Modulo': '%=',
    }
    word = ts.advance().value
    op = op_map[word]
    target = parse_primary(ts)
    # "by" keyword
    if ts.match_name('by'):
        ts.advance()
    value = parse_expr(ts)
    py_op = op[0]  # '+', '-', etc.
    return N.AugAssignStmt(target=target, op=py_op, value=value)


def parse_return(ts: TokenStream):
    t = ts.peek()
    line, col = t.line, t.col
    ts.eat_name('Return')
    if ts.match(TT.NEWLINE) or ts.match(TT.SEMICOLON) or ts.match(TT.EOF):
        return N.ReturnStmt(line=line, col=col)
    return N.ReturnStmt(value=parse_expr(ts), line=line, col=col)


def parse_raise(ts: TokenStream):
    ts.eat_name('Raise')
    if ts.match(TT.NEWLINE) or ts.match(TT.SEMICOLON) or ts.match(TT.EOF):
        return N.RaiseStmt()
    return N.RaiseStmt(value=parse_expr(ts))


def parse_print(ts: TokenStream):
    ts.eat_name('Print')
    args = [parse_expr_no_and(ts)]
    while ts.match_name('and'):
        ts.advance()
        args.append(parse_expr_no_and(ts))
    return N.PrintStmt(args=args)


def parse_assert(ts: TokenStream):
    ts.eat_name('Assert')
    cond = parse_expr(ts)
    msg = None
    if ts.match(TT.COMMA):
        ts.advance()
        msg = parse_expr(ts)
    return N.AssertStmt(condition=cond, message=msg)


def parse_field(ts: TokenStream):
    ts.eat_name('Field')
    name = ts.eat(TT.NAME).value
    ts.eat_name('of')
    ts.eat_name('type')
    type_ann = parse_type_expr(ts)
    return N.FieldDecl(name=name, type_ann=type_ann)


# ---------------------------------------------------------------------------
# Compound statement parsers
# ---------------------------------------------------------------------------

def parse_if(ts: TokenStream):
    t = ts.peek()
    line, col = t.line, t.col
    ts.eat_name('If')
    cond = parse_expr(ts)
    ts.eat(TT.COLON)
    body = parse_block(ts)
    elifs = []
    else_body = None
    while True:
        ts.skip_newlines()
        if ts.match_name('Otherwise'):
            ts.advance()
            if ts.match_name('if'):
                ts.advance()
                elif_cond = parse_expr(ts)
                ts.eat(TT.COLON)
                elif_body = parse_block(ts)
                elifs.append((elif_cond, elif_body))
            else:
                ts.eat(TT.COLON)
                else_body = parse_block(ts)
                break
        else:
            break
    return N.IfStmt(condition=cond, then_body=body, elifs=elifs, else_body=else_body, line=line, col=col)


def parse_while(ts: TokenStream):
    ts.eat_name('While')
    cond = parse_expr(ts)
    ts.eat(TT.COLON)
    body = parse_block(ts)
    else_body = None
    ts.skip_newlines()
    if ts.match_name('Otherwise'):
        ts.advance()
        ts.eat(TT.COLON)
        else_body = parse_block(ts)
    return N.WhileStmt(condition=cond, body=body, else_body=else_body)


def parse_for(ts: TokenStream):
    ts.eat_name('For')
    # "each" is optional
    if ts.match_name('each'):
        ts.advance()
    # targets: single name or comma-separated names
    targets = [ts.eat(TT.NAME).value]
    while ts.match(TT.COMMA):
        ts.advance()
        targets.append(ts.eat(TT.NAME).value)
    ts.eat_name('in')
    iterable = parse_expr(ts)
    ts.eat(TT.COLON)
    body = parse_block(ts)
    else_body = None
    ts.skip_newlines()
    if ts.match_name('Otherwise'):
        ts.advance()
        ts.eat(TT.COLON)
        else_body = parse_block(ts)
    return N.ForStmt(targets=targets, iterable=iterable, body=body, else_body=else_body)


def parse_try(ts: TokenStream):
    ts.eat_name('Try')
    ts.eat(TT.COLON)
    body = parse_block(ts)
    handlers = []
    else_body = None
    finally_body = None
    ts.skip_newlines()
    while ts.match_name('Except'):
        ts.advance()
        exc_type = None
        exc_name = None
        if not ts.match(TT.COLON):
            exc_type = parse_type_expr(ts)
            if ts.match_name('as'):
                ts.advance()
                exc_name = ts.eat(TT.NAME).value
        ts.eat(TT.COLON)
        h_body = parse_block(ts)
        handlers.append(N.ExceptHandler(exc_type=exc_type, name=exc_name, body=h_body))
        ts.skip_newlines()
    if ts.match_name('Else'):
        ts.advance()
        ts.eat(TT.COLON)
        else_body = parse_block(ts)
        ts.skip_newlines()
    if ts.match_name('Finally'):
        ts.advance()
        ts.eat(TT.COLON)
        finally_body = parse_block(ts)
    return N.TryStmt(body=body, handlers=handlers, else_body=else_body, finally_body=finally_body)


def parse_with(ts: TokenStream):
    ts.eat_name('Using')
    items = []
    expr = parse_expr(ts)
    alias = None
    if ts.match_name('as'):
        ts.advance()
        alias = ts.eat(TT.NAME).value
    items.append(N.WithItem(expr=expr, name=alias))
    while ts.match(TT.COMMA):
        ts.advance()
        expr = parse_expr(ts)
        alias = None
        if ts.match_name('as'):
            ts.advance()
            alias = ts.eat(TT.NAME).value
        items.append(N.WithItem(expr=expr, name=alias))
    ts.eat(TT.COLON)
    body = parse_block(ts)
    return N.WithStmt(items=items, body=body)


# ---------------------------------------------------------------------------
# Define: function / struct / trait
# ---------------------------------------------------------------------------

def parse_define(ts: TokenStream):
    ts.eat_name('Define')
    t = ts.peek()
    if t.type != TT.NAME:
        raise SyntaxError(f"Expected 'function', 'method', 'struct', or 'trait' after 'Define' at {t.line}")
    kind = t.value
    if kind in ('function', 'method'):
        return parse_func_def(ts)
    if kind == 'struct':
        return parse_struct_def(ts)
    if kind == 'trait':
        return parse_trait_def(ts)
    raise SyntaxError(f"Unknown define kind: {kind!r} at {t.line}")


def parse_func_def(ts: TokenStream):
    t = ts.peek()
    line, col = t.line, t.col
    kind = ts.advance().value  # 'function' or 'method'
    name = ts.eat(TT.NAME).value
    params = []
    if ts.match(TT.LPAREN):
        ts.advance()
        params = parse_params(ts)
        ts.eat(TT.RPAREN)
    return_type = None
    if ts.match_name('returning'):
        ts.advance()
        return_type = parse_type_expr(ts)
    ts.eat(TT.COLON)
    body = parse_block(ts)
    return N.FunctionDef(name=name, params=params, return_type=return_type, body=body, line=line, col=col)


def parse_params(ts: TokenStream) -> list:
    params = []
    if ts.match(TT.RPAREN):
        return params
    params.append(parse_one_param(ts))
    while ts.match(TT.COMMA):
        ts.advance()
        if ts.match(TT.RPAREN):
            break
        params.append(parse_one_param(ts))
    return params


def parse_one_param(ts: TokenStream) -> N.Param:
    convention = ''
    if ts.match_name('mut', 'var', 'ref', 'out', 'deinit'):
        convention = ts.advance().value
    name = ts.eat(TT.NAME).value
    type_ann = None
    default = None
    if ts.match_name('of'):
        ts.advance()
        ts.eat_name('type')
        type_ann = parse_type_expr(ts)
    if ts.match_name('defaulting') or (ts.match_name('with') and ts.peek(1).value == 'default'):
        # "defaulting to <expr>" or "with default <expr>"
        ts.advance()
        if ts.match_name('default'):
            ts.advance()
        if ts.match_name('to'):
            ts.advance()
        default = parse_expr(ts)
    return N.Param(name=name, type_ann=type_ann, default=default, convention=convention)


def parse_struct_def(ts: TokenStream):
    ts.eat_name('struct')
    name = ts.eat(TT.NAME).value
    bases = []
    if ts.match_name('implementing'):
        ts.advance()
        bases.append(ts.eat(TT.NAME).value)
        while ts.match_name('and'):
            ts.advance()
            bases.append(ts.eat(TT.NAME).value)
    ts.eat(TT.COLON)
    body = parse_block(ts)
    return N.StructDef(name=name, bases=bases, body=body)


def parse_trait_def(ts: TokenStream):
    ts.eat_name('trait')
    name = ts.eat(TT.NAME).value
    ts.eat(TT.COLON)
    body = parse_block(ts)
    return N.TraitDef(name=name, body=body)


# ---------------------------------------------------------------------------
# Type expression parser (simplified — handles Name, Name[Type,...], dotted)
# ---------------------------------------------------------------------------

def parse_type_expr(ts: TokenStream):
    """Parse a type annotation: Name, dotted.Name, Name[T, ...], list of T, etc."""
    # Handle English compound types: "list of T", "dict of K to V"
    if ts.match_name('list'):
        ts.advance()
        if ts.match_name('of'):
            ts.advance()
            inner = parse_type_expr(ts)
            return N.SubscriptExpr(obj=N.IdentExpr('list'), index=inner)
        return N.IdentExpr('list')
    if ts.match_name('dict'):
        ts.advance()
        if ts.match_name('of'):
            ts.advance()
            key_t = parse_type_expr(ts)
            if ts.match_name('to'):
                ts.advance()
                val_t = parse_type_expr(ts)
                return N.SubscriptExpr(obj=N.IdentExpr('dict'),
                                       index=N.TupleLiteral([key_t, val_t]))
        return N.IdentExpr('dict')
    if ts.match_name('set'):
        ts.advance()
        if ts.match_name('of'):
            ts.advance()
            inner = parse_type_expr(ts)
            return N.SubscriptExpr(obj=N.IdentExpr('set'), index=inner)
        return N.IdentExpr('set')
    if ts.match_name('tuple'):
        ts.advance()
        if ts.match_name('of'):
            ts.advance()
            inner = parse_type_expr(ts)
            return N.SubscriptExpr(obj=N.IdentExpr('tuple'), index=inner)
        return N.IdentExpr('tuple')

    # Regular type: Name (possibly dotted), possibly subscripted with []
    if ts.peek().type != TT.NAME:
        raise SyntaxError(f"Expected type name at {ts.line()}")
    name = ts.eat(TT.NAME).value
    expr = N.IdentExpr(name)
    while ts.match(TT.DOT):
        ts.advance()
        member = ts.eat(TT.NAME).value
        expr = N.MemberExpr(obj=expr, member=member)
    if ts.match(TT.LBRACKET):
        ts.advance()
        args = [parse_type_expr(ts)]
        while ts.match(TT.COMMA):
            ts.advance()
            args.append(parse_type_expr(ts))
        ts.eat(TT.RBRACKET)
        if len(args) == 1:
            expr = N.SubscriptExpr(obj=expr, index=args[0])
        else:
            expr = N.SubscriptExpr(obj=expr, index=N.TupleLiteral(args))
    return expr


# ---------------------------------------------------------------------------
# Expression parser (Pratt precedence climbing)
# ---------------------------------------------------------------------------

# Map from multi-word English phrases to (Python op string, precedence, assoc)
# Lower number = lower precedence (binds looser)
# assoc: 'left' or 'right'

_BINARY_OPS = {
    # Boolean
    'or':  ('or', 1, 'left'),
    'and': ('and', 2, 'left'),
    # Comparison (precedence 3, non-associative but we allow chaining)
    'equals':     ('==', 3, 'left'),
    # multi-word comparisons handled in parse_binary
    'in':         ('in', 3, 'left'),
    'is':         ('is', 3, 'left'),
    # Additive
    'plus':   ('+', 5, 'left'),
    'minus':  ('-', 5, 'left'),
    # Multiplicative
    'times':  ('*', 6, 'left'),
    # Power
    # 'to' handled specially (to the power of)
}

_COMPARISON_PHRASES = {
    ('equals',):                        '==',
    ('does', 'not', 'equal'):           '!=',
    ('is', 'less', 'than', 'or', 'equal', 'to'): '<=',
    ('is', 'greater', 'than', 'or', 'equal', 'to'): '>=',
    ('is', 'less', 'than'):             '<',
    ('is', 'greater', 'than'):          '>',
    ('is', 'not'):                      'is not',
    ('not', 'in'):                      'not in',
}

def _try_match_phrase(ts: TokenStream) -> tuple[str, int] | None:
    """Try to match a comparison phrase or binary operator.
    Returns (python_op, num_tokens_consumed) or None."""
    # Try longest first
    for phrase, py_op in sorted(_COMPARISON_PHRASES.items(), key=lambda x: -len(x[0])):
        words = _peek_words(ts, len(phrase))
        if tuple(words) == phrase:
            return py_op, len(phrase)
    # Single-word
    t = ts.peek()
    if t.type == TT.NAME and t.value in _BINARY_OPS:
        info = _BINARY_OPS[t.value]
        return info[0], 1
    # "divided by"
    if t.type == TT.NAME and t.value == 'divided':
        w2 = ts.peek(1)
        if w2.type == TT.NAME and w2.value == 'by':
            return '/', 2
    # "floor divided by"
    if t.type == TT.NAME and t.value == 'floor':
        w2, w3, w4 = ts.peek(1), ts.peek(2), ts.peek(3)
        if (w2.type == TT.NAME and w2.value == 'divided' and
                w3.type == TT.NAME and w3.value == 'by'):
            return '//', 3
    # "modulo"
    if t.type == TT.NAME and t.value == 'modulo':
        return '%', 1
    # "to the power of"
    if t.type == TT.NAME and t.value == 'to':
        w2, w3, w4 = ts.peek(1), ts.peek(2), ts.peek(3)
        if (w2.type == TT.NAME and w2.value == 'the' and
                w3.type == TT.NAME and w3.value == 'power' and
                w4.type == TT.NAME and w4.value == 'of'):
            return '**', 4
    return None


_OP_PRECEDENCE = {
    'or': 1, 'and': 2,
    '==': 3, '!=': 3, '<': 3, '<=': 3, '>': 3, '>=': 3,
    'is': 3, 'is not': 3, 'in': 3, 'not in': 3,
    '+': 5, '-': 5,
    '*': 6, '/': 6, '//': 6, '%': 6, '@': 6,
    '**': 7,
}


def parse_expr(ts: TokenStream) -> object:
    """Parse a full expression including 'and' as a binary operator."""
    return parse_binary(ts, min_prec=0)


def parse_expr_no_and(ts: TokenStream) -> object:
    """Parse an expression where 'and' is NOT a binary op (used in Print)."""
    return parse_binary(ts, min_prec=0, stop_at_and=True)


def parse_binary(ts: TokenStream, min_prec: int = 0, stop_at_and: bool = False) -> object:
    left = parse_unary(ts)

    while True:
        # Special: ternary "X if COND otherwise Y"
        if ts.match_name('if') and min_prec <= 0:
            t = ts.peek()
            line, col = t.line, t.col
            ts.advance()
            cond = parse_binary(ts, min_prec=1)
            ts.eat_name('otherwise')
            right = parse_binary(ts, min_prec=0)
            left = N.TernaryExpr(condition=cond, then_val=left, else_val=right, line=line, col=col)
            continue

        if stop_at_and and ts.match_name('and'):
            break

        result = _try_match_phrase(ts)
        if result is None:
            break
        py_op, n_tokens = result
        t = ts.peek()
        line, col = t.line, t.col
        prec = _OP_PRECEDENCE.get(py_op, 3)
        if prec < min_prec:
            break
        # Consume the operator tokens
        for _ in range(n_tokens):
            ts.advance()
        # Right side
        next_prec = prec + 1  # left-associative; use prec for right-assoc (**)
        if py_op == '**':
            next_prec = prec  # right-associative
        right = parse_binary(ts, min_prec=next_prec, stop_at_and=stop_at_and)
        left = N.BinaryOp(left=left, op=py_op, right=right, line=line, col=col)

    return left


def parse_unary(ts: TokenStream) -> object:
    t = ts.peek()
    line, col = t.line, t.col
    if ts.match_name('not'):
        ts.advance()
        return N.UnaryOp(op='not', operand=parse_unary(ts), line=line, col=col)
    if ts.match_name('negative'):
        ts.advance()
        return N.UnaryOp(op='-', operand=parse_unary(ts), line=line, col=col)
    if ts.match_name('bitwise') and ts.peek(1).value == 'not':
        ts.advance(); ts.advance()
        return N.UnaryOp(op='~', operand=parse_unary(ts), line=line, col=col)
    return parse_postfix(ts)


def parse_postfix(ts: TokenStream) -> object:
    expr = parse_primary(ts)
    while True:
        if ts.match(TT.DOT):
            ts.advance()
            member = ts.eat(TT.NAME).value
            expr = N.MemberExpr(obj=expr, member=member)
        elif ts.match(TT.APOSTROPHE_S):
            ts.advance()
            member = ts.eat(TT.NAME).value
            expr = N.MemberExpr(obj=expr, member=member)
        elif ts.match(TT.LBRACKET):
            ts.advance()
            idx = parse_expr(ts)
            # Slice?
            if ts.match(TT.COLON):
                ts.advance()
                stop = parse_expr(ts) if not ts.match(TT.RBRACKET) else None
                expr = N.SliceExpr(obj=expr, start=idx, stop=stop)
            else:
                expr = N.SubscriptExpr(obj=expr, index=idx)
            ts.eat(TT.RBRACKET)
        elif ts.match(TT.LPAREN):
            ts.advance()
            args, kwargs = parse_call_args(ts)
            ts.eat(TT.RPAREN)
            expr = N.CallExpr(func=expr, args=args, kwargs=kwargs)
        elif ts.match_name('at') and ts.peek(1).value == 'index':
            ts.advance(); ts.advance()
            idx = parse_expr(ts)
            expr = N.SubscriptExpr(obj=expr, index=idx)
        elif ts.match_name('at') and ts.peek(1).value == 'indices':
            ts.advance(); ts.advance()
            start = parse_expr(ts)
            ts.eat_name('to')
            stop = parse_expr(ts)
            expr = N.SliceExpr(obj=expr, start=start, stop=stop)
        else:
            break
    return expr


def parse_primary(ts: TokenStream) -> object:
    t = ts.peek()
    line, col = t.line, t.col

    # call expression
    if t.type == TT.NAME and t.value == 'call':
        return parse_call_expr(ts)

    # Literals
    if t.type == TT.INT:
        ts.advance()
        return N.IntLiteral(value=int(t.value, 0), line=line, col=col)
    if t.type == TT.FLOAT:
        ts.advance()
        return N.FloatLiteral(value=float(t.value), line=line, col=col)
    if t.type == TT.STRING:
        ts.advance()
        return N.StringLiteral(value=t.value, line=line, col=col)
    if t.type == TT.NAME and t.value == 'True':
        ts.advance()
        return N.BoolLiteral(value=True, line=line, col=col)
    if t.type == TT.NAME and t.value == 'False':
        ts.advance()
        return N.BoolLiteral(value=False, line=line, col=col)
    if t.type == TT.NAME and t.value == 'None':
        ts.advance()
        return N.NoneLiteral(line=line, col=col)
    if t.type == TT.NAME and t.value == 'Self':
        ts.advance()
        return N.SelfExpr(line=line, col=col)

    # Parenthesized or tuple
    if t.type == TT.LPAREN:
        ts.advance()
        if ts.match(TT.RPAREN):
            ts.advance()
            return N.TupleLiteral([], line=line, col=col)
        expr = parse_expr(ts)
        if ts.match(TT.COMMA):
            # Tuple
            elements = [expr]
            while ts.match(TT.COMMA):
                ts.advance()
                if ts.match(TT.RPAREN):
                    break
                elements.append(parse_expr(ts))
            ts.eat(TT.RPAREN)
            return N.TupleLiteral(elements, line=line, col=col)
        ts.eat(TT.RPAREN)
        return expr

    # List
    if t.type == TT.LBRACKET:
        return parse_list_or_comprehension(ts)

    # Dict or Set
    if t.type == TT.LBRACE:
        return parse_dict_or_set(ts)

    # Identifier
    if t.type == TT.NAME:
        ts.advance()
        return N.IdentExpr(name=t.value, line=line, col=col)

    raise SyntaxError(f"Unexpected token {t.type.name} ({t.value!r}) at {t.line}:{t.col}")


def parse_call_expr(ts: TokenStream) -> object:
    """call <func_expr> [with <args>]"""
    ts.eat_name('call')
    # Parse a dotted name (could be obj.method)
    name = ts.eat(TT.NAME).value
    func: object = N.IdentExpr(name)
    while ts.match(TT.DOT):
        ts.advance()
        member = ts.eat(TT.NAME).value
        func = N.MemberExpr(obj=func, member=member)
    # optional postfix subscript/attribute before 'with'
    args = []
    kwargs = []
    if ts.match_name('with'):
        ts.advance()
        # "a and b" style or comma-separated
        args.append(parse_expr_no_and(ts))
        while ts.match_name('and') or ts.match(TT.COMMA):
            ts.advance()
            args.append(parse_expr_no_and(ts))
    return N.CallExpr(func=func, args=args, kwargs=kwargs)


def parse_call_args(ts: TokenStream) -> tuple[list, list]:
    """Parse argument list inside parentheses (already consumed '(')."""
    args = []
    kwargs = []
    if ts.match(TT.RPAREN):
        return args, kwargs
    # Check for keyword arg: NAME '=' expr
    while True:
        # Peek for keyword arg pattern
        if ts.peek().type == TT.NAME and ts.peek(1).type == TT.EQUALS:
            kw_name = ts.advance().value
            ts.advance()  # eat '='
            val = parse_expr(ts)
            kwargs.append((kw_name, val))
        else:
            args.append(parse_expr(ts))
        if ts.match(TT.COMMA):
            ts.advance()
        else:
            break
    return args, kwargs


def parse_list_or_comprehension(ts: TokenStream) -> object:
    ts.eat(TT.LBRACKET)
    if ts.match(TT.RBRACKET):
        ts.advance()
        return N.ListLiteral([])
    first = parse_expr(ts)
    # Comprehension?
    if ts.match_name('for'):
        gen = parse_generator(ts)
        ts.eat(TT.RBRACKET)
        return N.Comprehension(kind='list', element=first, generators=[gen])
    # Regular list
    elements = [first]
    while ts.match(TT.COMMA):
        ts.advance()
        if ts.match(TT.RBRACKET):
            break
        elements.append(parse_expr(ts))
    ts.eat(TT.RBRACKET)
    return N.ListLiteral(elements)


def parse_dict_or_set(ts: TokenStream) -> object:
    ts.eat(TT.LBRACE)
    if ts.match(TT.RBRACE):
        ts.advance()
        return N.DictLiteral([])
    first = parse_expr(ts)
    if ts.match(TT.COLON):
        # Dict or dict comprehension
        ts.advance()
        val = parse_expr(ts)
        if ts.match_name('for'):
            gen = parse_generator(ts)
            ts.eat(TT.RBRACE)
            return N.Comprehension(kind='dict', element=first, value_expr=val, generators=[gen])
        pairs = [(first, val)]
        while ts.match(TT.COMMA):
            ts.advance()
            if ts.match(TT.RBRACE):
                break
            k = parse_expr(ts)
            ts.eat(TT.COLON)
            v = parse_expr(ts)
            pairs.append((k, v))
        ts.eat(TT.RBRACE)
        return N.DictLiteral(pairs)
    else:
        # Set or set comprehension
        if ts.match_name('for'):
            gen = parse_generator(ts)
            ts.eat(TT.RBRACE)
            return N.Comprehension(kind='set', element=first, generators=[gen])
        elements = [first]
        while ts.match(TT.COMMA):
            ts.advance()
            if ts.match(TT.RBRACE):
                break
            elements.append(parse_expr(ts))
        ts.eat(TT.RBRACE)
        return N.SetLiteral(elements)


def parse_generator(ts: TokenStream) -> N.Generator:
    """Parse: for <target> in <iterable> [if <cond>]*"""
    ts.eat_name('for')
    target = ts.eat(TT.NAME).value
    while ts.match(TT.COMMA):
        ts.advance()
        ts.eat(TT.NAME).value  # consume but we handle single target for now
    ts.eat_name('in')
    iterable = parse_expr(ts)
    conditions = []
    while ts.match_name('if'):
        ts.advance()
        conditions.append(parse_expr(ts))
    return N.Generator(target=target, iterable=iterable, conditions=conditions)
