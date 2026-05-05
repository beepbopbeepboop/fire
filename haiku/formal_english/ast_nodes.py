from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    line: int = 0


@dataclass
class Module(Node):
    body: list["Node"] = field(default_factory=list)


@dataclass
class Block(Node):
    stmts: list["Node"] = field(default_factory=list)


# Imports
@dataclass
class ImportModule(Node):
    module: str = ""
    alias: Optional[str] = None


@dataclass
class ImportFrom(Node):
    module: str = ""
    names: list[tuple[str, Optional[str]]] = field(default_factory=list)
    star: bool = False


# Declarations and Assignment
@dataclass
class VarDecl(Node):
    name: str = ""
    type_annotation: Optional["TypeExpr"] = None
    value: Optional["Node"] = None


@dataclass
class Assign(Node):
    target: Optional["Node"] = None
    value: Optional["Node"] = None


@dataclass
class AugAssign(Node):
    target: Optional["Node"] = None
    op: str = ""
    value: Optional["Node"] = None


# Control Flow
@dataclass
class If(Node):
    condition: Optional["Node"] = None
    body: Optional["Block"] = None
    elifs: list[tuple["Node", "Block"]] = field(default_factory=list)
    else_body: Optional["Block"] = None


@dataclass
class While(Node):
    condition: Optional["Node"] = None
    body: Optional["Block"] = None
    else_body: Optional["Block"] = None


@dataclass
class For(Node):
    target: Optional["Node"] = None
    iterable: Optional["Node"] = None
    body: Optional["Block"] = None
    else_body: Optional["Block"] = None


@dataclass
class ExceptHandler(Node):
    exc_type: Optional["Node"] = None
    name: Optional[str] = None
    body: Optional["Block"] = None


@dataclass
class Try(Node):
    body: Optional["Block"] = None
    handlers: list["ExceptHandler"] = field(default_factory=list)
    else_body: Optional["Block"] = None
    finally_body: Optional["Block"] = None


@dataclass
class With(Node):
    context: Optional["Node"] = None
    alias: Optional[str] = None
    body: Optional["Block"] = None


# Functions and Structs
@dataclass
class Param(Node):
    name: str = ""
    type_annotation: Optional["TypeExpr"] = None
    default: Optional["Node"] = None


@dataclass
class FuncDef(Node):
    name: str = ""
    params: list["Param"] = field(default_factory=list)
    return_type: Optional["TypeExpr"] = None
    body: Optional["Block"] = None
    is_method: bool = False


@dataclass
class FieldDecl(Node):
    name: str = ""
    type_annotation: Optional["TypeExpr"] = None


@dataclass
class StructBody(Node):
    fields: list["FieldDecl"] = field(default_factory=list)
    methods: list["FuncDef"] = field(default_factory=list)


@dataclass
class StructDef(Node):
    name: str = ""
    body: Optional["StructBody"] = None


# Simple Statements
@dataclass
class Return(Node):
    value: Optional["Node"] = None


@dataclass
class Print(Node):
    values: list["Node"] = field(default_factory=list)


@dataclass
class Raise(Node):
    exc: Optional["Node"] = None


@dataclass
class Pass(Node):
    pass


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass


@dataclass
class ExprStmt(Node):
    expr: Optional["Node"] = None


# Expressions
@dataclass
class Name(Node):
    id: str = ""


@dataclass
class Literal(Node):
    raw: str = ""
    kind: str = ""


@dataclass
class BinOp(Node):
    left: Optional["Node"] = None
    op: str = ""
    right: Optional["Node"] = None


@dataclass
class UnaryOp(Node):
    op: str = ""
    operand: Optional["Node"] = None


@dataclass
class BoolOp(Node):
    op: str = ""
    values: list["Node"] = field(default_factory=list)


@dataclass
class Compare(Node):
    left: Optional["Node"] = None
    ops: list[str] = field(default_factory=list)
    comparators: list["Node"] = field(default_factory=list)


@dataclass
class Call(Node):
    func: Optional["Node"] = None
    args: list["Node"] = field(default_factory=list)
    kwargs: list[tuple[str, "Node"]] = field(default_factory=list)


@dataclass
class Attribute(Node):
    obj: Optional["Node"] = None
    attr: str = ""


@dataclass
class Subscript(Node):
    obj: Optional["Node"] = None
    index: Optional["Node"] = None


@dataclass
class Slice(Node):
    lower: Optional["Node"] = None
    upper: Optional["Node"] = None
    step: Optional["Node"] = None


@dataclass
class Tuple(Node):
    elts: list["Node"] = field(default_factory=list)


@dataclass
class List(Node):
    elts: list["Node"] = field(default_factory=list)


@dataclass
class Dict(Node):
    pairs: list[tuple["Node", "Node"]] = field(default_factory=list)


@dataclass
class Set(Node):
    elts: list["Node"] = field(default_factory=list)


@dataclass
class Comprehension(Node):
    kind: str = ""
    elt: Optional["Node"] = None
    target: Optional["Node"] = None
    iter: Optional["Node"] = None
    condition: Optional["Node"] = None
    value_elt: Optional["Node"] = None


@dataclass
class Ternary(Node):
    test: Optional["Node"] = None
    body: Optional["Node"] = None
    orelse: Optional["Node"] = None


@dataclass
class Walrus(Node):
    target: Optional["Node"] = None
    value: Optional["Node"] = None


# Type Expression
@dataclass
class TypeExpr(Node):
    kind: str = ""
    name: Optional[str] = None
    elem: Optional["TypeExpr"] = None
    key: Optional["TypeExpr"] = None
    val: Optional["TypeExpr"] = None
