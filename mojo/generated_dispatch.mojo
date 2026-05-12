# Transpiled from Python by APEX py2mojo skill

var _SIGNED: dict = {'int8_t': 1, 'int16_t': 2, 'int32_t': 3, 'int': 3, 'int64_t': 4}

var _UNSIGNED: dict = {'uint8_t': 1, 'uint16_t': 2, 'uint32_t': 3, 'unsigned int': 3, 'uint64_t': 4}

var _FLOAT: dict = {'__fp16': 1, 'float': 2, 'double': 3}

var _BIN_OPS: dict = {'+': '+', '-': '-', '*': '*', '/': '/', '%': '%', '&': '&', '|': '|', '^': '^', '<<': '<<', '>>': '>>', '==': '==', '!=': '!=', '<': '<', '<=': '<=', '>': '>', '>=': '>=', 'and': '&&', 'or': '||', 'is': '==', 'is not': '!='}

var _CMP_OPS: set = ['!=', '<', '<=', '==', '>', '>=', 'and', 'is', 'is not', 'or']

# Dispatch tables - declared but not dynamically used in C code due to transpilation limitations
# Code that references these will fall back to error handling paths
var _STMT_DISPATCH: dict = {}
var _EXPR_DISPATCH: dict = {}
