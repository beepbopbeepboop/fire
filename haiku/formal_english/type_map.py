from .tokens import Token, TT
from .ast_nodes import TypeExpr
from .errors import ParseError

_needs_any = False


def parse_type_expr(tokens: list[Token], pos: int) -> tuple[TypeExpr, int]:
    if pos >= len(tokens):
        raise ParseError("unexpected end of input while parsing type", 0)

    token = tokens[pos]

    if token.type != TT.NAME:
        raise ParseError(f"expected type name, got {token.type.name}", token.line, token.col)

    value = token.value

    # Simple types
    if value == "integer":
        return TypeExpr(kind="simple", name="int", line=token.line), pos + 1
    elif value == "float":
        return TypeExpr(kind="simple", name="float", line=token.line), pos + 1
    elif value == "string":
        return TypeExpr(kind="simple", name="str", line=token.line), pos + 1
    elif value == "boolean":
        return TypeExpr(kind="simple", name="bool", line=token.line), pos + 1
    elif value == "nothing":
        return TypeExpr(kind="simple", name="None", line=token.line), pos + 1
    elif value == "any":
        return TypeExpr(kind="simple", name="Any", line=token.line), pos + 1
    elif value == "list":
        if pos + 1 < len(tokens) and tokens[pos + 1].type == TT.NAME and tokens[pos + 1].value == "of":
            elem_type, new_pos = parse_type_expr(tokens, pos + 2)
            return TypeExpr(kind="list", elem=elem_type, line=token.line), new_pos
        raise ParseError("expected 'list of' syntax", token.line, token.col)
    elif value == "dict":
        if pos + 1 < len(tokens) and tokens[pos + 1].type == TT.NAME and tokens[pos + 1].value == "of":
            key_type, pos = parse_type_expr(tokens, pos + 2)
            if pos < len(tokens) and tokens[pos].type == TT.NAME and tokens[pos].value == "to":
                val_type, pos = parse_type_expr(tokens, pos + 1)
                return TypeExpr(kind="dict", key=key_type, val=val_type, line=token.line), pos
            raise ParseError("expected 'to' in dict type", token.line, token.col)
        raise ParseError("expected 'dict of' syntax", token.line, token.col)
    elif value == "optional":
        elem_type, new_pos = parse_type_expr(tokens, pos + 1)
        return TypeExpr(kind="optional", elem=elem_type, line=token.line), new_pos
    else:
        # Raw passthrough type (custom name)
        return TypeExpr(kind="raw", name=value, line=token.line), pos + 1


def emit_type(t: TypeExpr) -> str:
    global _needs_any

    if t.kind == "simple":
        if t.name == "Any":
            _needs_any = True
        return t.name
    elif t.kind == "raw":
        return t.name
    elif t.kind == "list":
        elem = emit_type(t.elem)
        return f"list[{elem}]"
    elif t.kind == "dict":
        key = emit_type(t.key)
        val = emit_type(t.val)
        return f"dict[{key}, {val}]"
    elif t.kind == "optional":
        elem = emit_type(t.elem)
        return f"{elem} | None"
    else:
        return "Any"
