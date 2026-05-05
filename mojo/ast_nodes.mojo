"""AST node definitions for Mojo parser."""

from dataclasses import dataclass

@dataclass
struct Module:
    body: list

@dataclass
struct IdentExpr:
    name: str

@dataclass
struct IntLiteral:
    value: int

@dataclass
struct FloatLiteral:
    value: float

@dataclass
struct StringLiteral:
    value: str

@dataclass
struct BoolLiteral:
    value: bool

@dataclass
struct NoneLiteral:
    pass

@dataclass
struct ListLiteral:
    elements: list

@dataclass
struct DictLiteral:
    pairs: list

@dataclass
struct SetLiteral:
    elements: list

@dataclass
struct TupleLiteral:
    elements: list

@dataclass
struct BinaryOp:
    left: object
    op: str
    right: object

@dataclass
struct UnaryOp:
    op: str
    operand: object

@dataclass
struct CallExpr:
    func: object
    args: list
    kwargs: list = None

@dataclass
struct MemberExpr:
    obj: object
    member: str

@dataclass
struct SubscriptExpr:
    obj: object
    index: object

@dataclass
struct SliceExpr:
    obj: object
    start: object
    stop: object = None

@dataclass
struct TernaryExpr:
    condition: object
    then_val: object
    else_val: object

@dataclass
struct AssignStmt:
    targets: list
    value: object

@dataclass
struct AugAssignStmt:
    target: object
    op: str
    value: object

@dataclass
struct ReturnStmt:
    value: object = None

@dataclass
struct RaiseStmt:
    value: object = None

@dataclass
struct BreakStmt:
    pass

@dataclass
struct ContinueStmt:
    pass

@dataclass
struct PassStmt:
    pass

@dataclass
struct ExprStmt:
    expr: object

@dataclass
struct ImportStmt:
    module: str
    alias: str = None

@dataclass
struct FromImportStmt:
    module: str
    names: list = None
    wildcard: bool = False

@dataclass
struct IfStmt:
    condition: object
    then_body: list
    elifs: list = None
    else_body: list = None

@dataclass
struct WhileStmt:
    condition: object
    body: list
    else_body: list = None

@dataclass
struct ForStmt:
    targets: list
    iterable: object
    body: list
    else_body: list = None

@dataclass
struct FunctionDef:
    name: str
    params: list
    body: list
    return_type: object = None

@dataclass
struct StructDef:
    name: str
    body: list
    bases: list = None

@dataclass
struct TraitDef:
    name: str
    body: list

@dataclass
struct Param:
    name: str
    type_ann: object = None
    default: object = None
    convention: str = ""

@dataclass
struct SelfExpr:
    pass
