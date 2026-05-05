"""Recursive-descent parser for Mojo source code.

Consumes a token stream from tokenizer.mojo and produces an AST.
"""

from tokenizer import Token, tokenize
import ast_nodes as N

def parse(source: str) -> N.Module:
    """Parse Mojo source code into an AST."""
    tokens = tokenize(source)
    ts = TokenStream(tokens)
    body = parse_stmts(ts, top_level=True)
    return N.Module(body=body)

class TokenStream:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0

    def peek(self, offset: int = 0) -> Token:
        pos = self._pos + offset
        if pos < len(self._tokens):
            return self._tokens[pos]
        return self._tokens[-1]

    def advance(self) -> Token:
        t = self._tokens[self._pos]
        if self._pos < len(self._tokens) - 1:
            self._pos += 1
        return t

    def eat(self, kind: str) -> Token:
        t = self.peek()
        if t.kind != kind:
            raise Exception(f"Expected {kind} but got {t.kind}")
        return self.advance()

    def match(self, kind: str) -> bool:
        return self.peek().kind == kind

    def match_value(self, kind: str, value: str) -> bool:
        t = self.peek()
        return t.kind == kind and t.value == value

    def skip_newlines(self):
        while self.match("NEWLINE"):
            self.advance()

def parse_stmts(ts: TokenStream, top_level: bool = False) -> list:
    stmts = []
    ts.skip_newlines()
    while not ts.match("EOF") and not ts.match("DEDENT"):
        stmts.extend(parse_stmt(ts))
        ts.skip_newlines()
    return stmts

def parse_block(ts: TokenStream) -> list:
    """Parse an indented block: NEWLINE INDENT stmts DEDENT."""
    ts.eat("NEWLINE")
    ts.skip_newlines()
    ts.eat("INDENT")
    stmts = []
    ts.skip_newlines()
    while not ts.match("DEDENT") and not ts.match("EOF"):
        stmts.extend(parse_stmt(ts))
        ts.skip_newlines()
    ts.eat("DEDENT")
    return stmts

def parse_stmt(ts: TokenStream) -> list:
    """Parse a statement, handling semicolon-separated statements."""
    stmts = []
    t = ts.peek()

    # Compound statements
    if t.kind == "KW":
        if t.value == "if":
            return [parse_if(ts)]
        if t.value == "while":
            return [parse_while(ts)]
        if t.value == "for":
            return [parse_for(ts)]
        if t.value == "def":
            return [parse_func_def(ts)]
        if t.value == "fn":
            return [parse_func_def(ts)]
        if t.value == "struct":
            return [parse_struct_def(ts)]
        if t.value == "class":
            return [parse_struct_def(ts)]

    # Simple statement
    stmts.append(parse_simple_one(ts))
    while ts.match("COMMA"):
        ts.advance()
        stmts.append(parse_simple_one(ts))
    if ts.match("NEWLINE"):
        ts.advance()
    return stmts

def parse_simple_one(ts: TokenStream) -> object:
    t = ts.peek()

    if t.kind == "KW":
        if t.value == "return":
            return parse_return(ts)
        if t.value == "break":
            ts.advance()
            return N.BreakStmt()
        if t.value == "continue":
            ts.advance()
            return N.ContinueStmt()
        if t.value == "pass":
            ts.advance()
            return N.PassStmt()

    expr = parse_expr(ts)
    if ts.match("ASSIGN"):
        ts.advance()
        val = parse_expr(ts)
        return N.AssignStmt(targets=[expr], value=val)
    return N.ExprStmt(expr)

def parse_return(ts: TokenStream) -> N.ReturnStmt:
    ts.eat("KW")
    if ts.match("NEWLINE") or ts.match("EOF"):
        return N.ReturnStmt()
    return N.ReturnStmt(value=parse_expr(ts))

def parse_if(ts: TokenStream) -> N.IfStmt:
    ts.eat("KW")
    cond = parse_expr(ts)
    ts.eat("COLON")
    body = parse_block(ts)
    elifs = []
    else_body = None
    ts.skip_newlines()
    while ts.match_value("KW", "elif"):
        ts.advance()
        elif_cond = parse_expr(ts)
        ts.eat("COLON")
        elif_body = parse_block(ts)
        elifs.append((elif_cond, elif_body))
        ts.skip_newlines()
    if ts.match_value("KW", "else"):
        ts.advance()
        ts.eat("COLON")
        else_body = parse_block(ts)
    return N.IfStmt(condition=cond, then_body=body, elifs=elifs, else_body=else_body)

def parse_while(ts: TokenStream) -> N.WhileStmt:
    ts.eat("KW")
    cond = parse_expr(ts)
    ts.eat("COLON")
    body = parse_block(ts)
    return N.WhileStmt(condition=cond, body=body)

def parse_for(ts: TokenStream) -> N.ForStmt:
    ts.eat("KW")
    target = ts.eat("NAME").value
    ts.eat("KW")
    iterable = parse_expr(ts)
    ts.eat("COLON")
    body = parse_block(ts)
    return N.ForStmt(targets=[target], iterable=iterable, body=body)

def parse_func_def(ts: TokenStream) -> N.FunctionDef:
    ts.advance()
    name = ts.eat("NAME").value
    params = []
    if ts.match("LPAREN"):
        ts.advance()
        if not ts.match("RPAREN"):
            params = parse_params(ts)
        ts.eat("RPAREN")
    ts.eat("COLON")
    body = parse_block(ts)
    return N.FunctionDef(name=name, params=params, body=body)

def parse_params(ts: TokenStream) -> list:
    params = []
    params.append(ts.eat("NAME").value)
    while ts.match("COMMA"):
        ts.advance()
        if ts.match("RPAREN"):
            break
        params.append(ts.eat("NAME").value)
    return params

def parse_struct_def(ts: TokenStream) -> N.StructDef:
    ts.advance()
    name = ts.eat("NAME").value
    ts.eat("COLON")
    body = parse_block(ts)
    return N.StructDef(name=name, body=body)

def parse_expr(ts: TokenStream) -> object:
    """Parse a full expression."""
    return parse_binary(ts, min_prec=0)

def parse_binary(ts: TokenStream, min_prec: int = 0) -> object:
    left = parse_unary(ts)

    while True:
        t = ts.peek()
        if t.kind == "OP":
            op = t.value
            prec = get_precedence(op)
            if prec < min_prec:
                break
            ts.advance()
            next_prec = prec + 1
            right = parse_binary(ts, min_prec=next_prec)
            left = N.BinaryOp(left=left, op=op, right=right)
        elif t.kind == "KW" and t.value in ("and", "or"):
            op = t.value
            prec = 2 if op == "or" else 3
            if prec < min_prec:
                break
            ts.advance()
            right = parse_binary(ts, min_prec=prec + 1)
            left = N.BinaryOp(left=left, op=op, right=right)
        else:
            break

    return left

def get_precedence(op: str) -> int:
    if op == "or":
        return 1
    if op == "and":
        return 2
    if op in ("==", "!=", "<", "<=", ">", ">=", "is", "in"):
        return 3
    if op in ("+", "-"):
        return 5
    if op in ("*", "/", "//", "%"):
        return 6
    if op == "**":
        return 7
    return 0

def parse_unary(ts: TokenStream) -> object:
    t = ts.peek()
    if t.kind == "KW" and t.value == "not":
        ts.advance()
        return N.UnaryOp(op="not", operand=parse_unary(ts))
    if t.kind == "OP" and t.value == "-":
        ts.advance()
        return N.UnaryOp(op="-", operand=parse_unary(ts))
    return parse_postfix(ts)

def parse_postfix(ts: TokenStream) -> object:
    expr = parse_primary(ts)
    while True:
        if ts.match("DOT"):
            ts.advance()
            member = ts.eat("NAME").value
            expr = N.MemberExpr(obj=expr, member=member)
        elif ts.match("LBRACKET"):
            ts.advance()
            idx = parse_expr(ts)
            ts.eat("RBRACKET")
            expr = N.SubscriptExpr(obj=expr, index=idx)
        elif ts.match("LPAREN"):
            ts.advance()
            args = []
            if not ts.match("RPAREN"):
                args.append(parse_expr(ts))
                while ts.match("COMMA"):
                    ts.advance()
                    if ts.match("RPAREN"):
                        break
                    args.append(parse_expr(ts))
            ts.eat("RPAREN")
            expr = N.CallExpr(func=expr, args=args, kwargs=[])
        else:
            break
    return expr

def parse_primary(ts: TokenStream) -> object:
    t = ts.peek()

    if t.kind == "INT":
        ts.advance()
        return N.IntLiteral(value=int(t.value))
    if t.kind == "FLOAT":
        ts.advance()
        return N.FloatLiteral(value=float(t.value))
    if t.kind == "STRING":
        ts.advance()
        return N.StringLiteral(value=t.value)
    if t.kind == "KW":
        if t.value == "True":
            ts.advance()
            return N.BoolLiteral(value=True)
        if t.value == "False":
            ts.advance()
            return N.BoolLiteral(value=False)
        if t.value == "None":
            ts.advance()
            return N.NoneLiteral()

    if t.kind == "NAME":
        ts.advance()
        return N.IdentExpr(name=t.value)

    if t.kind == "LPAREN":
        ts.advance()
        if ts.match("RPAREN"):
            ts.advance()
            return N.TupleLiteral([])
        expr = parse_expr(ts)
        if ts.match("COMMA"):
            elements = [expr]
            while ts.match("COMMA"):
                ts.advance()
                if ts.match("RPAREN"):
                    break
                elements.append(parse_expr(ts))
            ts.eat("RPAREN")
            return N.TupleLiteral(elements)
        ts.eat("RPAREN")
        return expr

    if t.kind == "LBRACKET":
        ts.advance()
        if ts.match("RBRACKET"):
            ts.advance()
            return N.ListLiteral([])
        elements = [parse_expr(ts)]
        while ts.match("COMMA"):
            ts.advance()
            if ts.match("RBRACKET"):
                break
            elements.append(parse_expr(ts))
        ts.eat("RBRACKET")
        return N.ListLiteral(elements)

    if t.kind == "LBRACE":
        ts.advance()
        if ts.match("RBRACE"):
            ts.advance()
            return N.DictLiteral([])
        pairs = []
        k = parse_expr(ts)
        ts.eat("COLON")
        v = parse_expr(ts)
        pairs.append((k, v))
        while ts.match("COMMA"):
            ts.advance()
            if ts.match("RBRACE"):
                break
            k = parse_expr(ts)
            ts.eat("COLON")
            v = parse_expr(ts)
            pairs.append((k, v))
        ts.eat("RBRACE")
        return N.DictLiteral(pairs)

    raise Exception(f"Unexpected token: {t.kind} {t.value}")
