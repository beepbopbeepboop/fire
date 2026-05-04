"""AST node definitions for the Formal English transpiler."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

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
class BoolLiteral:
    value: bool

@dataclass
class NoneLiteral:
    pass

@dataclass
class SelfExpr:
    pass

@dataclass
class EllipsisExpr:
    pass

@dataclass
class IdentExpr:
    name: str

@dataclass
class MemberExpr:
    obj: object   # Expr
    member: str

@dataclass
class SubscriptExpr:
    obj: object   # Expr
    index: object # Expr

@dataclass
class SliceExpr:
    obj: object           # Expr
    start: object         # Expr | None
    stop: object          # Expr | None
    step: object = None   # Expr | None

@dataclass
class CallExpr:
    func: object          # Expr
    args: list = field(default_factory=list)
    kwargs: list = field(default_factory=list)  # list of (str, Expr)

@dataclass
class BinaryOp:
    left: object   # Expr
    op: str        # Python operator string
    right: object  # Expr

@dataclass
class UnaryOp:
    op: str        # '-', '~', 'not'
    operand: object  # Expr

@dataclass
class TernaryExpr:
    condition: object  # Expr
    then_val: object   # Expr
    else_val: object   # Expr

@dataclass
class WalrusExpr:
    name: str
    value: object  # Expr

@dataclass
class ListLiteral:
    elements: list = field(default_factory=list)

@dataclass
class DictLiteral:
    pairs: list = field(default_factory=list)  # list of (Expr, Expr)

@dataclass
class SetLiteral:
    elements: list = field(default_factory=list)

@dataclass
class TupleLiteral:
    elements: list = field(default_factory=list)

@dataclass
class Generator:
    target: object   # str or TupleLiteral of strs
    iterable: object # Expr
    conditions: list = field(default_factory=list)  # list of Expr

@dataclass
class Comprehension:
    kind: str        # 'list', 'set', 'dict', 'generator'
    element: object  # Expr (value for list/set/generator, key for dict)
    value_expr: object = None  # Expr for dict comprehension values
    generators: list = field(default_factory=list)  # list of Generator


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class Param:
    name: str
    type_ann: object = None  # Expr | None
    default: object = None   # Expr | None
    convention: str = ''     # 'mut', 'var', 'ref', 'out', 'deinit', ''


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

@dataclass
class ImportStmt:
    module: str
    alias: Optional[str] = None

@dataclass
class FromImportStmt:
    module: str
    names: list = field(default_factory=list)  # list of (name, alias|None)
    wildcard: bool = False

@dataclass
class DeclareStmt:
    name: str
    type_ann: object = None  # Expr | None
    value: object = None     # Expr | None

@dataclass
class AssignStmt:
    targets: list = field(default_factory=list)  # list of Expr (for multiple assignment)
    value: object = None   # Expr

@dataclass
class AugAssignStmt:
    target: object  # Expr
    op: str         # '+', '-', '*', '/', '//', '%', '**', etc.
    value: object   # Expr

@dataclass
class ReturnStmt:
    value: object = None  # Expr | None

@dataclass
class RaiseStmt:
    value: object = None  # Expr | None

@dataclass
class BreakStmt:
    pass

@dataclass
class ContinueStmt:
    pass

@dataclass
class PassStmt:
    pass

@dataclass
class PrintStmt:
    args: list = field(default_factory=list)  # list of Expr

@dataclass
class AssertStmt:
    condition: object        # Expr
    message: object = None   # Expr | None

@dataclass
class ExprStmt:
    value: object  # Expr

@dataclass
class FieldDecl:
    name: str
    type_ann: object  # Expr

@dataclass
class FunctionDef:
    name: str
    params: list = field(default_factory=list)   # list of Param
    return_type: object = None  # Expr | None
    body: list = field(default_factory=list)      # list of Stmt
    is_static: bool = False
    decorators: list = field(default_factory=list)

@dataclass
class StructDef:
    name: str
    bases: list = field(default_factory=list)   # trait names
    body: list = field(default_factory=list)    # list of Stmt

@dataclass
class TraitDef:
    name: str
    body: list = field(default_factory=list)    # list of Stmt

@dataclass
class IfStmt:
    condition: object          # Expr
    then_body: list = field(default_factory=list)
    elifs: list = field(default_factory=list)    # list of (Expr, list[Stmt])
    else_body: object = None   # list[Stmt] | None

@dataclass
class WhileStmt:
    condition: object          # Expr
    body: list = field(default_factory=list)
    else_body: object = None   # list[Stmt] | None

@dataclass
class ForStmt:
    targets: list = field(default_factory=list)  # list of str (or nested)
    iterable: object = None    # Expr
    body: list = field(default_factory=list)
    else_body: object = None   # list[Stmt] | None

@dataclass
class ExceptHandler:
    exc_type: object = None    # Expr | None
    name: Optional[str] = None
    body: list = field(default_factory=list)

@dataclass
class TryStmt:
    body: list = field(default_factory=list)
    handlers: list = field(default_factory=list)  # list of ExceptHandler
    else_body: object = None   # list[Stmt] | None
    finally_body: object = None  # list[Stmt] | None

@dataclass
class WithItem:
    expr: object               # Expr
    name: Optional[str] = None

@dataclass
class WithStmt:
    items: list = field(default_factory=list)  # list of WithItem
    body: list = field(default_factory=list)

@dataclass
class Module:
    body: list = field(default_factory=list)  # list of Stmt
