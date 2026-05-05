"""Dispatch tables for codegen - extracted from Mojo transpilation."""

# Type rank tables for numeric promotion
_SIGNED = {'int8_t': 1, 'int16_t': 2, 'int32_t': 3, 'int': 3, 'int64_t': 4}
_UNSIGNED = {'uint8_t': 1, 'uint16_t': 2, 'uint32_t': 3, 'unsigned int': 3, 'uint64_t': 4}
_FLOAT = {'__fp16': 1, 'float': 2, 'double': 3}

# Operator dispatch tables
_BIN_OPS = {
    '+': '+', '-': '-', '*': '*', '/': '/', '%': '%',
    '&': '&', '|': '|', '^': '^',
    '<<': '<<', '>>': '>>',
    '==': '==', '!=': '!=',
    '<': '<', '<=': '<=', '>': '>', '>=': '>=',
    'and': '&&', 'or': '||',
    'is': '==', 'is not': '!='
}

_CMP_OPS = {'!=', '<', '<=', '==', '>', '>=', 'and', 'is', 'is not', 'or'}

# Statement dispatch - maps AST type to handler method name
_STMT_DISPATCH = {
    'PassStmt': '_gen_stmt_PassStmt',
    'VarDecl': '_gen_stmt_VarDecl',
    'AssignStmt': '_gen_stmt_AssignStmt',
    'AugAssignStmt': '_gen_stmt_AugAssignStmt',
    'MultiAssignStmt': '_gen_stmt_MultiAssignStmt',
    'ReturnStmt': '_gen_stmt_ReturnStmt',
    'IfStmt': '_gen_stmt_IfStmt',
    'WhileStmt': '_gen_stmt_WhileStmt',
    'ForStmt': '_gen_stmt_ForStmt',
    'BreakStmt': '_gen_stmt_BreakStmt',
    'ContinueStmt': '_gen_stmt_ContinueStmt',
    'ExprStmt': '_gen_stmt_ExprStmt',
    'AssertStmt': '_gen_stmt_AssertStmt',
    'RaiseStmt': '_gen_stmt_RaiseStmt',
    'TryStmt': '_gen_stmt_TryStmt',
    'WithStmt': '_gen_stmt_WithStmt',
    'FunctionDef': '_gen_stmt_FunctionDef',
    'ImportStmt': '_gen_stmt_ImportStmt',
    'FromImportStmt': '_gen_stmt_FromImportStmt',
    'ComptimeIfStmt': '_gen_stmt_ComptimeIfStmt',
    'ComptimeForStmt': '_gen_stmt_ComptimeForStmt',
}

# Expression dispatch - maps AST type to handler method name
_EXPR_DISPATCH = {
    'IntLiteral': '_lower_IntLiteral',
    'FloatLiteral': '_lower_FloatLiteral',
    'BoolLiteral': '_lower_BoolLiteral',
    'EllipsisLiteral': '_lower_EllipsisLiteral',
    'StringLiteral': '_lower_StringLiteral',
    'IdentExpr': '_lower_IdentExpr',
    'WalrusExpr': '_lower_WalrusExpr',
    'BinaryOp': '_lower_binary',
    'UnaryOp': '_lower_UnaryOp',
    'CallExpr': '_lower_call',
    'TernaryExpr': '_lower_TernaryExpr',
    'MemberExpr': '_lower_MemberExpr',
    'SubscriptExpr': '_lower_subscript',
    'SliceExpr': '_lower_slice',
    'ListExpr': '_lower_list_literal',
    'DictExpr': '_lower_dict_literal',
    'SetExpr': '_lower_set_literal',
    'TupleExpr': '_lower_tuple_literal',
    'Comprehension': '_lower_comprehension',
}
