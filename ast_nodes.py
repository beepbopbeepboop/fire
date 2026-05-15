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
    line: int = 0
    col: int = 0

@dataclass
class FloatLiteral:
    value: float
    line: int = 0
    col: int = 0

@dataclass
class StringLiteral:
    value: str
    line: int = 0
    col: int = 0

@dataclass
class BoolLiteral:
    value: bool
    line: int = 0
    col: int = 0

@dataclass
class NoneLiteral:
    line: int = 0
    col: int = 0

@dataclass
class SelfExpr:
    line: int = 0
    col: int = 0

@dataclass
class EllipsisExpr:
    line: int = 0
    col: int = 0

@dataclass
class IdentExpr:
    name: str
    line: int = 0
    col: int = 0

@dataclass
class MemberExpr:
    obj: object   # Expr
    member: str
    line: int = 0
    col: int = 0

@dataclass
class SubscriptExpr:
    obj: object   # Expr
    index: object # Expr
    line: int = 0
    col: int = 0

@dataclass
class SliceExpr:
    obj: object           # Expr
    start: object         # Expr | None
    stop: object          # Expr | None
    step: object = None   # Expr | None
    line: int = 0
    col: int = 0

@dataclass
class CallExpr:
    func: object          # Expr
    args: list = field(default_factory=list)
    kwargs: list = field(default_factory=list)  # list of (str, Expr)
    line: int = 0
    col: int = 0

@dataclass
class BinaryOp:
    left: object   # Expr
    op: str        # Python operator string
    right: object  # Expr
    line: int = 0
    col: int = 0

@dataclass
class UnaryOp:
    op: str        # '-', '~', 'not'
    operand: object  # Expr
    line: int = 0
    col: int = 0

@dataclass
class TernaryExpr:
    condition: object  # Expr
    then_val: object   # Expr
    else_val: object   # Expr
    line: int = 0
    col: int = 0

@dataclass
class LambdaExpr:
    params: list  # list of (name, default) tuples
    body: object  # Expr
    line: int = 0
    col: int = 0

@dataclass
class WalrusExpr:
    name: str
    value: object  # Expr
    line: int = 0
    col: int = 0

@dataclass
class ListLiteral:
    elements: list = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class DictLiteral:
    pairs: list = field(default_factory=list)  # list of (Expr, Expr)
    line: int = 0
    col: int = 0

@dataclass
class SetLiteral:
    elements: list = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class TupleLiteral:
    elements: list = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class Generator:
    target: object   # str or TupleLiteral of strs
    iterable: object # Expr
    conditions: list = field(default_factory=list)  # list of Expr
    line: int = 0
    col: int = 0

@dataclass
class Comprehension:
    kind: str        # 'list', 'set', 'dict', 'generator'
    element: object  # Expr (value for list/set/generator, key for dict)
    value_expr: object = None  # Expr for dict comprehension values
    generators: list = field(default_factory=list)  # list of Generator
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class Param:
    name: str
    type_ann: object = None  # Expr | None
    default: object = None   # Expr | None
    convention: str = ''     # 'mut', 'var', 'ref', 'out', 'deinit', ''
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

@dataclass
class ImportStmt:
    module: str
    alias: Optional[str] = None
    line: int = 0
    col: int = 0

@dataclass
class FromImportStmt:
    module: str
    names: list = field(default_factory=list)  # list of (name, alias|None)
    wildcard: bool = False
    line: int = 0
    col: int = 0

@dataclass
class DeclareStmt:
    name: str
    type_ann: object = None  # Expr | None
    value: object = None     # Expr | None
    line: int = 0
    col: int = 0

@dataclass
class AssignStmt:
    targets: list = field(default_factory=list)  # list of Expr (for multiple assignment)
    value: object = None   # Expr
    line: int = 0
    col: int = 0

@dataclass
class AugAssignStmt:
    target: object  # Expr
    op: str         # '+', '-', '*', '/', '//', '%', '**', etc.
    value: object   # Expr
    line: int = 0
    col: int = 0

@dataclass
class ReturnStmt:
    value: object = None  # Expr | None
    line: int = 0
    col: int = 0

@dataclass
class RaiseStmt:
    value: object = None  # Expr | None
    line: int = 0
    col: int = 0

@dataclass
class BreakStmt:
    line: int = 0
    col: int = 0

@dataclass
class ContinueStmt:
    line: int = 0
    col: int = 0

@dataclass
class PassStmt:
    line: int = 0
    col: int = 0

@dataclass
class PrintStmt:
    args: list = field(default_factory=list)  # list of Expr
    line: int = 0
    col: int = 0

@dataclass
class AssertStmt:
    condition: object        # Expr
    message: object = None   # Expr | None
    line: int = 0
    col: int = 0

@dataclass
class ExprStmt:
    value: object  # Expr
    line: int = 0
    col: int = 0

@dataclass
class FieldDecl:
    name: str
    type_ann: object  # Expr
    line: int = 0
    col: int = 0

@dataclass
class FunctionDef:
    name: str
    params: list = field(default_factory=list)   # list of Param
    return_type: object = None  # Expr | None
    body: list = field(default_factory=list)      # list of Stmt
    is_static: bool = False
    decorators: list = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class StructDef:
    name: str
    bases: list = field(default_factory=list)   # trait names
    body: list = field(default_factory=list)    # list of Stmt
    line: int = 0
    col: int = 0

@dataclass
class TraitDef:
    name: str
    body: list = field(default_factory=list)    # list of Stmt
    line: int = 0
    col: int = 0

@dataclass
class IfStmt:
    condition: object          # Expr
    then_body: list = field(default_factory=list)
    elifs: list = field(default_factory=list)    # list of (Expr, list[Stmt])
    else_body: object = None   # list[Stmt] | None
    line: int = 0
    col: int = 0

@dataclass
class WhileStmt:
    condition: object          # Expr
    body: list = field(default_factory=list)
    else_body: object = None   # list[Stmt] | None
    line: int = 0
    col: int = 0

@dataclass
class ForStmt:
    targets: list = field(default_factory=list)  # list of str (or nested)
    iterable: object = None    # Expr
    body: list = field(default_factory=list)
    else_body: object = None   # list[Stmt] | None
    line: int = 0
    col: int = 0

@dataclass
class ExceptHandler:
    exc_type: object = None    # Expr | None
    name: Optional[str] = None
    body: list = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class TryStmt:
    body: list = field(default_factory=list)
    handlers: list = field(default_factory=list)  # list of ExceptHandler
    else_body: object = None   # list[Stmt] | None
    finally_body: object = None  # list[Stmt] | None
    line: int = 0
    col: int = 0

@dataclass
class WithItem:
    expr: object               # Expr
    name: Optional[str] = None
    line: int = 0
    col: int = 0

@dataclass
class WithStmt:
    items: list = field(default_factory=list)  # list of WithItem
    body: list = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class Module:
    body: list = field(default_factory=list)  # list of Stmt
    filename: str = ""
    line: int = 0
    col: int = 0
