from .tokens import Token, TT
from .ast_nodes import *
from .type_map import parse_type_expr
from .errors import ParseError


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> Module:
        body = []
        while not self.match(TT.EOF):
            if self.match(TT.NEWLINE):
                self.advance()
                continue
            stmt = self.parse_statement()
            if stmt:
                body.append(stmt)
        return Module(body=body, line=1)

    def current(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]

    def peek(self, offset: int = 1) -> Token:
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]

    def advance(self) -> Token:
        token = self.current()
        if self.pos < len(self.tokens):
            self.pos += 1
        return token

    def match(self, *types: TT) -> bool:
        return self.current().type in types

    def match_name(self, *values: str) -> bool:
        return self.current().type == TT.NAME and self.current().value in values

    def expect(self, tt: TT) -> Token:
        if not self.match(tt):
            raise ParseError(f"expected {tt.name}, got {self.current().type.name}", self.current().line)
        return self.advance()

    def expect_name(self, value: str) -> Token:
        if not self.match_name(value):
            raise ParseError(f"expected '{value}', got '{self.current().value}'", self.current().line)
        return self.advance()

    def consume_newline(self) -> None:
        while self.match(TT.NEWLINE):
            self.advance()

    def parse_statement(self) -> Optional[Node]:
        self.consume_newline()

        if self.match(TT.EOF):
            return None

        # Dispatch based on leading NAME
        if self.match_name("Define"):
            return self.parse_define()
        elif self.match_name("Declare"):
            return self.parse_var_decl()
        elif self.match_name("Set"):
            return self.parse_assign()
        elif self.match_name("Increase"):
            return self.parse_aug_assign("+=")
        elif self.match_name("Decrease"):
            return self.parse_aug_assign("-=")
        elif self.match_name("Multiply"):
            return self.parse_aug_assign("*=")
        elif self.match_name("Divide"):
            return self.parse_aug_assign("/=")
        elif self.match_name("If"):
            return self.parse_if()
        elif self.match_name("While"):
            return self.parse_while()
        elif self.match_name("For"):
            return self.parse_for()
        elif self.match_name("Try"):
            return self.parse_try()
        elif self.match_name("With"):
            return self.parse_with()
        elif self.match_name("Return"):
            return self.parse_return()
        elif self.match_name("Print"):
            return self.parse_print()
        elif self.match_name("Import"):
            return self.parse_import()
        elif self.match_name("From"):
            return self.parse_from_import()
        elif self.match_name("Raise"):
            return self.parse_raise()
        elif self.match_name("Pass"):
            self.advance()
            self.expect(TT.NEWLINE)
            return Pass(line=self.current().line)
        elif self.match_name("Break"):
            self.advance()
            self.expect(TT.NEWLINE)
            return Break(line=self.current().line)
        elif self.match_name("Continue"):
            self.advance()
            self.expect(TT.NEWLINE)
            return Continue(line=self.current().line)
        elif self.match_name("Call"):
            return self.parse_call_stmt()
        else:
            return self.parse_expr_stmt()

    def parse_define(self) -> Node:
        self.expect_name("Define")
        line = self.current().line

        if self.match_name("function"):
            self.advance()
            return self.parse_func_def(line, is_method=False)
        elif self.match_name("method"):
            self.advance()
            return self.parse_func_def(line, is_method=True)
        elif self.match_name("struct"):
            self.advance()
            return self.parse_struct_def(line)
        else:
            raise ParseError("expected 'function', 'method', or 'struct'", self.current().line)

    def parse_func_def(self, line: int, is_method: bool) -> FuncDef:
        name_token = self.expect(TT.NAME)
        name = name_token.value
        self.expect(TT.LPAREN)

        params = []
        while not self.match(TT.RPAREN):
            param_name = self.expect(TT.NAME).value
            type_anno = None
            default = None

            if self.match_name("of"):
                self.advance()
                self.expect_name("type")
                type_anno, self.pos = parse_type_expr(self.tokens, self.pos)

            if self.match_name("with"):
                self.advance()
                self.expect_name("default")
                default = self.parse_expr()

            params.append(Param(name=param_name, type_annotation=type_anno, default=default, line=line))

            if self.match(TT.COMMA):
                self.advance()
            elif not self.match(TT.RPAREN):
                raise ParseError("expected ',' or ')'", self.current().line)

        self.expect(TT.RPAREN)

        return_type = None
        if self.match(TT.ARROW):
            self.advance()
            return_type, _ = parse_type_expr(self.tokens, self.pos)
            self.pos += 1
        elif self.match_name("returning"):
            self.advance()
            return_type, _ = parse_type_expr(self.tokens, self.pos)
            self.pos += 1

        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        body = self.parse_block()

        return FuncDef(name=name, params=params, return_type=return_type, body=body, is_method=is_method, line=line)

    def parse_struct_def(self, line: int) -> StructDef:
        name_token = self.expect(TT.NAME)
        name = name_token.value
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        self.expect(TT.INDENT)

        fields = []
        methods = []

        while not self.match(TT.DEDENT) and not self.match(TT.EOF):
            self.consume_newline()
            if self.match(TT.DEDENT):
                break

            if self.match_name("Field"):
                self.advance()
                field_name = self.expect(TT.NAME).value
                self.expect_name("of")
                self.expect_name("type")
                field_type, self.pos = parse_type_expr(self.tokens, self.pos)
                self.expect(TT.NEWLINE)
                fields.append(FieldDecl(name=field_name, type_annotation=field_type, line=self.current().line))
            elif self.match_name("Define"):
                methods.append(self.parse_statement())
            else:
                raise ParseError("expected 'Field' or 'Define'", self.current().line)

        self.expect(TT.DEDENT)
        body = StructBody(fields=fields, methods=methods, line=line)
        return StructDef(name=name, body=body, line=line)

    def parse_var_decl(self) -> VarDecl:
        line = self.current().line
        self.expect_name("Declare")
        self.expect_name("variable")
        name = self.expect(TT.NAME).value

        type_annotation = None
        value = None

        if self.match_name("of"):
            self.advance()
            self.expect_name("type")
            type_annotation, self.pos = parse_type_expr(self.tokens, self.pos)

        if self.match_name("with"):
            self.advance()
            self.expect_name("value")
            value = self.parse_expr()

        self.expect(TT.NEWLINE)
        return VarDecl(name=name, type_annotation=type_annotation, value=value, line=line)

    def parse_assign(self) -> Assign:
        line = self.current().line
        self.expect_name("Set")
        target = self.parse_expr()
        self.expect_name("to")
        value = self.parse_expr()
        self.expect(TT.NEWLINE)
        return Assign(target=target, value=value, line=line)

    def parse_aug_assign(self, op: str) -> AugAssign:
        line = self.current().line
        verb = self.advance().value
        target_name = self.expect(TT.NAME).value
        self.expect_name("by")
        value = self.parse_expr()
        self.expect(TT.NEWLINE)
        return AugAssign(target=Name(id=target_name, line=line), op=op, value=value, line=line)

    def parse_if(self) -> If:
        line = self.current().line
        self.expect_name("If")
        condition = self.parse_expr()
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        body = self.parse_block()

        elifs = []
        else_body = None

        while True:
            self.consume_newline()
            if self.match_name("Otherwise"):
                self.advance()
                if self.match_name("if"):
                    self.advance()
                    elif_cond = self.parse_expr()
                    self.expect(TT.COLON)
                    self.expect(TT.NEWLINE)
                    elif_body = self.parse_block()
                    elifs.append((elif_cond, elif_body))
                elif self.match(TT.COLON):
                    self.advance()
                    self.expect(TT.NEWLINE)
                    else_body = self.parse_block()
                    break
                else:
                    raise ParseError("expected 'if' or ':'", self.current().line)
            else:
                break

        return If(condition=condition, body=body, elifs=elifs, else_body=else_body, line=line)

    def parse_while(self) -> While:
        line = self.current().line
        self.expect_name("While")
        condition = self.parse_expr()
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        body = self.parse_block()
        return While(condition=condition, body=body, line=line)

    def parse_for(self) -> For:
        line = self.current().line
        self.expect_name("For")
        self.expect_name("each")
        target = self.parse_primary()
        self.expect_name("in")
        iterable = self.parse_expr()
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        body = self.parse_block()
        return For(target=target, iterable=iterable, body=body, line=line)

    def parse_try(self) -> Try:
        line = self.current().line
        self.expect_name("Try")
        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        body = self.parse_block()

        handlers = []
        else_body = None
        finally_body = None

        while True:
            self.consume_newline()
            if self.match_name("Except"):
                self.advance()
                exc_type = None
                exc_name = None

                if self.match(TT.NAME) and not self.match_name("as"):
                    exc_type = Name(id=self.advance().value, line=self.current().line)
                    if self.match_name("as"):
                        self.advance()
                        exc_name = self.expect(TT.NAME).value

                self.expect(TT.COLON)
                self.expect(TT.NEWLINE)
                handler_body = self.parse_block()
                handlers.append(ExceptHandler(exc_type=exc_type, name=exc_name, body=handler_body, line=line))
            elif self.match_name("Otherwise"):
                self.advance()
                self.expect(TT.COLON)
                self.expect(TT.NEWLINE)
                else_body = self.parse_block()
            elif self.match_name("Finally"):
                self.advance()
                self.expect(TT.COLON)
                self.expect(TT.NEWLINE)
                finally_body = self.parse_block()
                break
            else:
                break

        return Try(body=body, handlers=handlers, else_body=else_body, finally_body=finally_body, line=line)

    def parse_with(self) -> With:
        line = self.current().line
        self.expect_name("With")
        context = self.parse_expr()
        alias = None

        if self.match_name("as"):
            self.advance()
            alias = self.expect(TT.NAME).value

        self.expect(TT.COLON)
        self.expect(TT.NEWLINE)
        body = self.parse_block()
        return With(context=context, alias=alias, body=body, line=line)

    def parse_return(self) -> Return:
        line = self.current().line
        self.expect_name("Return")

        if self.match_name("nothing"):
            self.advance()
            self.expect(TT.NEWLINE)
            return Return(value=None, line=line)

        value = self.parse_expr()
        self.expect(TT.NEWLINE)
        return Return(value=value, line=line)

    def parse_print(self) -> Print:
        line = self.current().line
        self.expect_name("Print")
        values = [self.parse_print_value()]

        while self.match_name("and"):
            self.advance()
            values.append(self.parse_print_value())

        self.expect(TT.NEWLINE)
        return Print(values=values, line=line)

    def parse_print_value(self) -> Node:
        """Parse a value for Print, stopping at 'and'."""
        return self.parse_compare()

    def parse_import(self) -> ImportModule:
        line = self.current().line
        self.expect_name("Import")
        module = self.expect(TT.NAME).value
        alias = None

        if self.match_name("as"):
            self.advance()
            alias = self.expect(TT.NAME).value

        self.expect(TT.NEWLINE)
        return ImportModule(module=module, alias=alias, line=line)

    def parse_from_import(self) -> ImportFrom:
        line = self.current().line
        self.expect_name("From")
        module = self.expect(TT.NAME).value
        self.expect_name("import")

        if self.match_name("everything"):
            self.advance()
            self.expect(TT.NEWLINE)
            return ImportFrom(module=module, names=[], star=True, line=line)

        names = []
        names.append((self.expect(TT.NAME).value, None))

        while self.match_name("and"):
            self.advance()
            names.append((self.expect(TT.NAME).value, None))

        self.expect(TT.NEWLINE)
        return ImportFrom(module=module, names=names, star=False, line=line)

    def parse_raise(self) -> Raise:
        line = self.current().line
        self.expect_name("Raise")
        exc = self.parse_expr()
        self.expect(TT.NEWLINE)
        return Raise(exc=exc, line=line)

    def parse_call_stmt(self) -> ExprStmt:
        line = self.current().line
        self.expect_name("Call")
        func = self.parse_primary()

        args = []
        if self.match_name("with"):
            self.advance()
            args = self.parse_arg_list()

        self.expect(TT.NEWLINE)
        return ExprStmt(expr=Call(func=func, args=args, line=line), line=line)

    def parse_expr_stmt(self) -> ExprStmt:
        line = self.current().line
        expr = self.parse_expr()
        self.expect(TT.NEWLINE)
        return ExprStmt(expr=expr, line=line)

    def parse_block(self) -> Block:
        self.expect(TT.INDENT)
        stmts = []
        while not self.match(TT.DEDENT) and not self.match(TT.EOF):
            self.consume_newline()
            if self.match(TT.DEDENT):
                break
            stmt = self.parse_statement()
            if stmt:
                stmts.append(stmt)
        self.expect(TT.DEDENT)
        return Block(stmts=stmts, line=self.current().line)

    # Expression parsing
    def parse_expr(self) -> Node:
        return self.parse_walrus()

    def parse_walrus(self) -> Node:
        left = self.parse_ternary()
        if self.match(TT.WALRUS):
            self.advance()
            right = self.parse_ternary()
            return Walrus(target=left, value=right, line=left.line)
        return left

    def parse_ternary(self) -> Node:
        expr = self.parse_or()
        if self.match_name("if"):
            self.advance()
            test = self.parse_or()
            self.expect_name("else")
            orelse = self.parse_ternary()
            return Ternary(test=test, body=expr, orelse=orelse, line=expr.line)
        return expr

    def parse_or(self) -> Node:
        left = self.parse_and()
        while self.match_name("or"):
            self.advance()
            right = self.parse_and()
            left = BoolOp(op="or", values=[left, right], line=left.line)
        return left

    def parse_and(self) -> Node:
        left = self.parse_not()
        while self.match_name("and"):
            self.advance()
            right = self.parse_not()
            left = BoolOp(op="and", values=[left, right], line=left.line)
        return left

    def parse_not(self) -> Node:
        if self.match_name("not"):
            self.advance()
            return UnaryOp(op="not", operand=self.parse_not(), line=self.current().line)
        return self.parse_compare()

    def parse_compare(self) -> Node:
        left = self.parse_bitor()
        ops = []
        comparators = []

        while True:
            op = self._try_parse_compare_op()
            if not op:
                break
            ops.append(op)
            comparators.append(self.parse_bitor())

        if ops:
            return Compare(left=left, ops=ops, comparators=comparators, line=left.line)
        return left

    def _try_parse_compare_op(self) -> Optional[str]:
        compare_map = {
            ("does", "not", "equal"): "!=",
            ("is", "less", "than"): "<",
            ("is", "greater", "than"): ">",
            ("is", "at", "most"): "<=",
            ("is", "at", "least"): ">=",
            ("is", "not"): "is not",
            ("not", "in"): "not in",
            ("equals",): "==",
            ("is",): "is",
            ("in",): "in",
        }

        # Try longest match first
        for length in [3, 2, 1]:
            if self.current().type == TT.NAME:
                window = tuple(self.tokens[self.pos + i].value if self.pos + i < len(self.tokens) and self.tokens[self.pos + i].type == TT.NAME else None for i in range(length))
                if window in compare_map:
                    for _ in range(length):
                        self.advance()
                    return compare_map[window]

        # Symbol versions
        symbol_map = {TT.EQ: "==", TT.NEQ: "!=", TT.LT: "<", TT.GT: ">", TT.LTE: "<=", TT.GTE: ">="}
        if self.current().type in symbol_map:
            op = symbol_map[self.current().type]
            self.advance()
            return op

        return None

    def parse_bitor(self) -> Node:
        left = self.parse_bitxor()
        while self.match(TT.PIPE):
            self.advance()
            right = self.parse_bitxor()
            left = BinOp(left=left, op="|", right=right, line=left.line)
        return left

    def parse_bitxor(self) -> Node:
        left = self.parse_bitand()
        while self.match(TT.CARET):
            self.advance()
            right = self.parse_bitand()
            left = BinOp(left=left, op="^", right=right, line=left.line)
        return left

    def parse_bitand(self) -> Node:
        left = self.parse_shift()
        while self.match(TT.AMP):
            self.advance()
            right = self.parse_shift()
            left = BinOp(left=left, op="&", right=right, line=left.line)
        return left

    def parse_shift(self) -> Node:
        left = self.parse_add()
        while self.match(TT.LSHIFT, TT.RSHIFT):
            op = self.advance().value
            right = self.parse_add()
            left = BinOp(left=left, op=op, right=right, line=left.line)
        return left

    def parse_add(self) -> Node:
        left = self.parse_mul()
        while True:
            op = None
            if self.match_name("plus"):
                self.advance()
                op = "+"
            elif self.match_name("minus"):
                self.advance()
                op = "-"
            elif self.match(TT.PLUS, TT.MINUS):
                op = self.advance().value
            else:
                break
            right = self.parse_mul()
            left = BinOp(left=left, op=op, right=right, line=left.line)
        return left

    def parse_mul(self) -> Node:
        left = self.parse_power()
        while True:
            op = None
            if self.match_name("times"):
                self.advance()
                op = "*"
            elif self.match_name("divided"):
                if self.peek().value == "by":
                    self.advance()
                    self.advance()
                    op = "/"
                else:
                    break
            elif self.match_name("modulo"):
                self.advance()
                op = "%"
            elif self.match(TT.STAR, TT.SLASH, TT.DSLASH, TT.PERCENT):
                op = self.advance().value
            else:
                break
            right = self.parse_power()
            left = BinOp(left=left, op=op, right=right, line=left.line)
        return left

    def parse_power(self) -> Node:
        left = self.parse_unary()
        if self.match_name("to"):
            if self.peek().value == "the" and self.peek(2).value == "power" and self.peek(3).value == "of":
                self.advance()  # to
                self.advance()  # the
                self.advance()  # power
                self.advance()  # of
                right = self.parse_unary()
                return BinOp(left=left, op="**", right=right, line=left.line)
        elif self.match(TT.DSTAR):
            self.advance()
            right = self.parse_unary()
            return BinOp(left=left, op="**", right=right, line=left.line)
        return left

    def parse_unary(self) -> Node:
        if self.match_name("not"):
            self.advance()
            return UnaryOp(op="not", operand=self.parse_unary(), line=self.current().line)
        elif self.match(TT.MINUS, TT.PLUS, TT.TILDE):
            op = self.advance().value
            return UnaryOp(op=op, operand=self.parse_unary(), line=self.current().line)
        return self.parse_primary()

    def parse_primary(self) -> Node:
        atom = self.parse_atom()
        while True:
            if self.match(TT.DOT):
                self.advance()
                attr = self.expect(TT.NAME).value
                atom = Attribute(obj=atom, attr=attr, line=atom.line)
            elif self.match(TT.LBRACKET):
                self.advance()
                index = self.parse_expr()
                self.expect(TT.RBRACKET)
                atom = Subscript(obj=atom, index=index, line=atom.line)
            elif self.match(TT.LPAREN):
                self.advance()
                args = []
                kwargs = []
                if not self.match(TT.RPAREN):
                    args, kwargs = self.parse_arg_list_full()
                self.expect(TT.RPAREN)
                atom = Call(func=atom, args=args, kwargs=kwargs, line=atom.line)
            elif self.match(TT.APOSTROPHE_S):
                self.advance()
                attr = self.expect(TT.NAME).value
                atom = Attribute(obj=atom, attr=attr, line=atom.line)
            else:
                break
        return atom

    def parse_atom(self) -> Node:
        if self.match_name("call"):
            line = self.current().line
            self.advance()
            func = self.parse_primary()
            args = []
            if self.match_name("with"):
                self.advance()
                args = self.parse_arg_list()
            return Call(func=func, args=args, line=line)

        if self.match(TT.NAME):
            line = self.current().line
            return Name(id=self.advance().value, line=line)

        if self.match(TT.INTEGER):
            line = self.current().line
            return Literal(raw=self.advance().value, kind="int", line=line)

        if self.match(TT.FLOAT):
            line = self.current().line
            return Literal(raw=self.advance().value, kind="float", line=line)

        if self.match(TT.STRING):
            line = self.current().line
            return Literal(raw=self.advance().value, kind="str", line=line)

        if self.match(TT.BOOL):
            line = self.current().line
            return Literal(raw=self.advance().value, kind="bool", line=line)

        if self.match(TT.NONE):
            line = self.current().line
            self.advance()
            return Literal(raw="None", kind="None", line=line)

        if self.match(TT.SELF):
            line = self.current().line
            self.advance()
            return Literal(raw="Self", kind="Self", line=line)

        if self.match(TT.DISCARD):
            line = self.current().line
            self.advance()
            return Literal(raw="_", kind="discard", line=line)

        if self.match(TT.ELLIPSIS):
            line = self.current().line
            self.advance()
            return Literal(raw="...", kind="ellipsis", line=line)

        if self.match(TT.LPAREN):
            line = self.current().line
            self.advance()
            expr = self.parse_expr()
            if self.match(TT.COMMA):
                # It's a tuple
                elts = [expr]
                while self.match(TT.COMMA):
                    self.advance()
                    if self.match(TT.RPAREN):
                        break
                    elts.append(self.parse_expr())
                self.expect(TT.RPAREN)
                return Tuple(elts=elts, line=line)
            else:
                self.expect(TT.RPAREN)
                return expr

        if self.match(TT.LBRACKET):
            line = self.current().line
            self.advance()
            if self.match(TT.RBRACKET):
                self.advance()
                return List(elts=[], line=line)

            elts = [self.parse_compare()]

            # Check for comprehension
            if self.match_name("for"):
                elt_expr = elts[0]
                self.advance()
                target = self.parse_primary()
                self.expect_name("in")
                iter_expr = self.parse_compare()
                condition = None
                if self.match_name("if"):
                    self.advance()
                    condition = self.parse_compare()
                self.expect(TT.RBRACKET)
                return Comprehension(kind="list", elt=elt_expr, target=target, iter=iter_expr, condition=condition, line=line)

            while self.match(TT.COMMA):
                self.advance()
                if self.match(TT.RBRACKET):
                    break
                elts.append(self.parse_expr())

            self.expect(TT.RBRACKET)
            return List(elts=elts, line=line)

        if self.match(TT.LBRACE):
            line = self.current().line
            self.advance()
            if self.match(TT.RBRACE):
                self.advance()
                return Dict(pairs=[], line=line)

            first = self.parse_expr()

            # Dict or set?
            if self.match(TT.COLON):
                self.advance()
                value = self.parse_expr()
                pairs = [(first, value)]
                while self.match(TT.COMMA):
                    self.advance()
                    if self.match(TT.RBRACE):
                        break
                    key = self.parse_expr()
                    self.expect(TT.COLON)
                    val = self.parse_expr()
                    pairs.append((key, val))
                self.expect(TT.RBRACE)
                return Dict(pairs=pairs, line=line)
            else:
                elts = [first]
                while self.match(TT.COMMA):
                    self.advance()
                    if self.match(TT.RBRACE):
                        break
                    elts.append(self.parse_expr())
                self.expect(TT.RBRACE)
                return Set(elts=elts, line=line)

        raise ParseError(f"unexpected token {self.current().type.name}", self.current().line)

    def parse_arg_list(self) -> list[Node]:
        args = [self.parse_expr()]
        while self.match(TT.COMMA):
            self.advance()
            args.append(self.parse_expr())
        return args

    def parse_arg_list_full(self) -> tuple[list[Node], list[tuple[str, Node]]]:
        args = []
        kwargs = []

        first = self.parse_expr()

        if self.match(TT.COLON):
            # It's a keyword argument
            if isinstance(first, Name):
                self.advance()
                value = self.parse_expr()
                kwargs.append((first.id, value))
            else:
                raise ParseError("keyword argument name must be identifier", first.line)
        else:
            args.append(first)

        while self.match(TT.COMMA):
            self.advance()
            if self.match(TT.RPAREN):
                break

            elem = self.parse_expr()
            if self.match(TT.COLON):
                if isinstance(elem, Name):
                    self.advance()
                    value = self.parse_expr()
                    kwargs.append((elem.id, value))
                else:
                    raise ParseError("keyword argument name must be identifier", elem.line)
            else:
                args.append(elem)

        return args, kwargs
