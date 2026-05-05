from . import type_map
from .ast_nodes import *
from .errors import CodegenError


class CodeGenerator:
    def __init__(self):
        self._lines = []
        self._indent_level = 0

    def generate(self, module: Module) -> str:
        # Check if we need to import Any
        type_map._needs_any = False

        # First pass: collect type usage
        self._collect_types(module)

        # Generate code
        self._lines = []
        self._indent_level = 0

        if type_map._needs_any:
            self._emit("from typing import Any")
            self._emit("")

        self.visit(module)

        return "\n".join(self._lines)

    def _collect_types(self, node):
        if isinstance(node, VarDecl):
            if node.type_annotation:
                type_map.emit_type(node.type_annotation)
        elif isinstance(node, Param):
            if node.type_annotation:
                type_map.emit_type(node.type_annotation)
        elif isinstance(node, FieldDecl):
            if node.type_annotation:
                type_map.emit_type(node.type_annotation)
        elif isinstance(node, FuncDef):
            if node.return_type:
                type_map.emit_type(node.return_type)
            for param in node.params:
                self._collect_types(param)
            if node.body:
                for stmt in node.body.stmts:
                    self._collect_types(stmt)
        elif isinstance(node, Block):
            for stmt in node.stmts:
                self._collect_types(stmt)
        elif isinstance(node, Module):
            for stmt in node.body:
                self._collect_types(stmt)
        elif isinstance(node, StructDef):
            if node.body:
                for field in node.body.fields:
                    self._collect_types(field)
                for method in node.body.methods:
                    self._collect_types(method)
        elif isinstance(node, If):
            if node.body:
                self._collect_types(node.body)
            for _, block in node.elifs:
                self._collect_types(block)
            if node.else_body:
                self._collect_types(node.else_body)
        elif isinstance(node, (While, For, Try, With)):
            if node.body:
                self._collect_types(node.body)

    def _emit(self, line: str) -> None:
        indent = "    " * self._indent_level
        self._lines.append(indent + line if line else "")

    def _indent(self) -> None:
        self._indent_level += 1

    def _dedent(self) -> None:
        self._indent_level -= 1

    def visit(self, node) -> str:
        if node is None:
            return ""

        method_name = f"visit_{node.__class__.__name__}"
        method = getattr(self, method_name, None)
        if method:
            return method(node)
        raise CodegenError(f"no visit method for {node.__class__.__name__}", getattr(node, "line", 0))

    # Statements
    def visit_Module(self, node: Module) -> str:
        for stmt in node.body:
            self.visit(stmt)
        return ""

    def visit_Block(self, node: Block) -> str:
        for stmt in node.stmts:
            self.visit(stmt)
        return ""

    def visit_ImportModule(self, node: ImportModule) -> str:
        if node.alias:
            self._emit(f"import {node.module} as {node.alias}")
        else:
            self._emit(f"import {node.module}")
        return ""

    def visit_ImportFrom(self, node: ImportFrom) -> str:
        if node.star:
            self._emit(f"from {node.module} import *")
        else:
            names = ", ".join(f"{name} as {alias}" if alias else name for name, alias in node.names)
            self._emit(f"from {node.module} import {names}")
        return ""

    def visit_VarDecl(self, node: VarDecl) -> str:
        type_str = type_map.emit_type(node.type_annotation) if node.type_annotation else None
        value_str = self.visit(node.value) if node.value else None

        if type_str and value_str:
            self._emit(f"{node.name}: {type_str} = {value_str}")
        elif type_str:
            self._emit(f"{node.name}: {type_str}")
        elif value_str:
            self._emit(f"{node.name} = {value_str}")
        return ""

    def visit_Assign(self, node: Assign) -> str:
        target_str = self.visit(node.target)
        value_str = self.visit(node.value)
        self._emit(f"{target_str} = {value_str}")
        return ""

    def visit_AugAssign(self, node: AugAssign) -> str:
        target_str = self.visit(node.target)
        value_str = self.visit(node.value)
        self._emit(f"{target_str} {node.op} {value_str}")
        return ""

    def visit_If(self, node: If) -> str:
        cond_str = self.visit(node.condition)
        self._emit(f"if {cond_str}:")
        self._indent()
        self.visit(node.body)
        self._dedent()

        for elif_cond, elif_body in node.elifs:
            elif_str = self.visit(elif_cond)
            self._emit(f"elif {elif_str}:")
            self._indent()
            self.visit(elif_body)
            self._dedent()

        if node.else_body:
            self._emit("else:")
            self._indent()
            self.visit(node.else_body)
            self._dedent()

        return ""

    def visit_While(self, node: While) -> str:
        cond_str = self.visit(node.condition)
        self._emit(f"while {cond_str}:")
        self._indent()
        self.visit(node.body)
        self._dedent()
        return ""

    def visit_For(self, node: For) -> str:
        target_str = self.visit(node.target)
        iter_str = self.visit(node.iterable)
        self._emit(f"for {target_str} in {iter_str}:")
        self._indent()
        self.visit(node.body)
        self._dedent()
        return ""

    def visit_Try(self, node: Try) -> str:
        self._emit("try:")
        self._indent()
        self.visit(node.body)
        self._dedent()

        for handler in node.handlers:
            if handler.exc_type and handler.name:
                exc_str = self.visit(handler.exc_type)
                self._emit(f"except {exc_str} as {handler.name}:")
            elif handler.exc_type:
                exc_str = self.visit(handler.exc_type)
                self._emit(f"except {exc_str}:")
            else:
                self._emit("except:")
            self._indent()
            self.visit(handler.body)
            self._dedent()

        if node.else_body:
            self._emit("else:")
            self._indent()
            self.visit(node.else_body)
            self._dedent()

        if node.finally_body:
            self._emit("finally:")
            self._indent()
            self.visit(node.finally_body)
            self._dedent()

        return ""

    def visit_With(self, node: With) -> str:
        ctx_str = self.visit(node.context)
        if node.alias:
            self._emit(f"with {ctx_str} as {node.alias}:")
        else:
            self._emit(f"with {ctx_str}:")
        self._indent()
        self.visit(node.body)
        self._dedent()
        return ""

    def visit_FuncDef(self, node: FuncDef) -> str:
        params = []
        for param in node.params:
            params.append(self.visit(param))

        params_str = ", ".join(params)

        if node.return_type:
            ret_str = type_map.emit_type(node.return_type)
        else:
            ret_str = "None"

        self._emit(f"def {node.name}({params_str}) -> {ret_str}:")
        self._indent()
        if node.body and node.body.stmts:
            self.visit(node.body)
        else:
            self._emit("pass")
        self._dedent()
        if not node.is_method:
            self._emit("")
        return ""

    def visit_StructDef(self, node: StructDef) -> str:
        self._emit(f"class {node.name}:")
        self._indent()

        if node.body:
            if node.body.fields:
                for field in node.body.fields:
                    type_str = type_map.emit_type(field.type_annotation)
                    self._emit(f"{field.name}: {type_str}")
            else:
                self._emit("pass")

            if node.body.methods:
                if node.body.fields:
                    self._emit("")
                for method in node.body.methods:
                    self.visit(method)
        else:
            self._emit("pass")

        self._dedent()
        self._emit("")
        return ""

    def visit_Return(self, node: Return) -> str:
        if node.value:
            value_str = self.visit(node.value)
            self._emit(f"return {value_str}")
        else:
            self._emit("return")
        return ""

    def visit_Print(self, node: Print) -> str:
        args = ", ".join(self.visit(v) for v in node.values)
        self._emit(f"print({args})")
        return ""

    def visit_Param(self, node: Param) -> str:
        if node.name == "self":
            return "self"
        type_str = None
        if node.type_annotation:
            type_str = type_map.emit_type(node.type_annotation)
            # Quote custom types (raw kind) that are not built-ins
            if node.type_annotation.kind == "raw" and type_str not in ("int", "float", "str", "bool", "None", "Any"):
                type_str = f'"{type_str}"'

        if node.default:
            default_str = self.visit(node.default)
            if type_str:
                return f"{node.name}: {type_str} = {default_str}"
            else:
                return f"{node.name} = {default_str}"
        else:
            if type_str:
                return f"{node.name}: {type_str}"
            else:
                return node.name

    def visit_Raise(self, node: Raise) -> str:
        exc_str = self.visit(node.exc)
        self._emit(f"raise {exc_str}")
        return ""

    def visit_Pass(self, node: Pass) -> str:
        self._emit("pass")
        return ""

    def visit_Break(self, node: Break) -> str:
        self._emit("break")
        return ""

    def visit_Continue(self, node: Continue) -> str:
        self._emit("continue")
        return ""

    def visit_ExprStmt(self, node: ExprStmt) -> str:
        expr_str = self.visit(node.expr)
        self._emit(expr_str)
        return ""

    # Expressions
    def visit_Name(self, node: Name) -> str:
        return node.id

    def visit_Literal(self, node: Literal) -> str:
        if node.kind == "str":
            # Convert t"..." to f"..."
            if node.raw.startswith("t\"") or node.raw.startswith("t'"):
                return "f" + node.raw[1:]
            elif node.raw.startswith("t'''") or node.raw.startswith('t"""'):
                return "f" + node.raw[1:]
            return node.raw
        return node.raw

    def visit_BinOp(self, node: BinOp) -> str:
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Parenthesize if needed
        if isinstance(node.left, BinOp) and self._needs_parens(node.left.op, node.op, "left"):
            left = f"({left})"
        if isinstance(node.right, BinOp) and self._needs_parens(node.right.op, node.op, "right"):
            right = f"({right})"

        return f"{left} {node.op} {right}"

    def _needs_parens(self, inner_op: str, outer_op: str, position: str) -> bool:
        precedence = {
            "**": 14,
            "*": 4, "/": 4, "//": 4, "%": 4,
            "+": 5, "-": 5,
            "<<": 6, ">>": 6,
            "&": 7,
            "^": 8,
            "|": 9,
        }
        inner_prec = precedence.get(inner_op, 0)
        outer_prec = precedence.get(outer_op, 0)
        return inner_prec < outer_prec

    def visit_UnaryOp(self, node: UnaryOp) -> str:
        operand = self.visit(node.operand)
        if isinstance(node.operand, UnaryOp):
            operand = f"({operand})"
        if node.op == "not":
            return f"not {operand}"
        return f"{node.op}{operand}"

    def visit_BoolOp(self, node: BoolOp) -> str:
        values = [self.visit(v) for v in node.values]
        return f" {node.op} ".join(values)

    def visit_Compare(self, node: Compare) -> str:
        left = self.visit(node.left)
        parts = [left]
        for op, comp in zip(node.ops, node.comparators):
            parts.append(op)
            parts.append(self.visit(comp))
        return " ".join(parts)

    def visit_Call(self, node: Call) -> str:
        func_str = self.visit(node.func)
        args = [self.visit(arg) for arg in node.args]
        kwargs = [f"{name}={self.visit(value)}" for name, value in node.kwargs]
        all_args = ", ".join(args + kwargs)
        return f"{func_str}({all_args})"

    def visit_Attribute(self, node: Attribute) -> str:
        obj_str = self.visit(node.obj)
        return f"{obj_str}.{node.attr}"

    def visit_Subscript(self, node: Subscript) -> str:
        obj_str = self.visit(node.obj)
        index_str = self.visit(node.index)
        return f"{obj_str}[{index_str}]"

    def visit_Slice(self, node: Slice) -> str:
        parts = []
        if node.lower:
            parts.append(self.visit(node.lower))
        else:
            parts.append("")
        parts.append(":")
        if node.upper:
            parts.append(self.visit(node.upper))
        if node.step:
            parts.append(":")
            parts.append(self.visit(node.step))
        return "".join(parts)

    def visit_Tuple(self, node: Tuple) -> str:
        elts = [self.visit(e) for e in node.elts]
        if len(elts) == 1:
            return f"({elts[0]},)"
        return f"({', '.join(elts)})"

    def visit_List(self, node: List) -> str:
        elts = [self.visit(e) for e in node.elts]
        return f"[{', '.join(elts)}]"

    def visit_Dict(self, node: Dict) -> str:
        pairs = [f"{self.visit(k)}: {self.visit(v)}" for k, v in node.pairs]
        return f"{{{', '.join(pairs)}}}"

    def visit_Set(self, node: Set) -> str:
        elts = [self.visit(e) for e in node.elts]
        return f"{{{', '.join(elts)}}}"

    def visit_Comprehension(self, node: Comprehension) -> str:
        elt_str = self.visit(node.elt)
        target_str = self.visit(node.target)
        iter_str = self.visit(node.iter)

        result = f"[{elt_str} for {target_str} in {iter_str}"
        if node.condition:
            cond_str = self.visit(node.condition)
            result += f" if {cond_str}"
        result += "]"
        return result

    def visit_Ternary(self, node: Ternary) -> str:
        body_str = self.visit(node.body)
        test_str = self.visit(node.test)
        orelse_str = self.visit(node.orelse)
        return f"{body_str} if {test_str} else {orelse_str}"

    def visit_Walrus(self, node: Walrus) -> str:
        target_str = self.visit(node.target)
        value_str = self.visit(node.value)
        return f"({target_str} := {value_str})"
