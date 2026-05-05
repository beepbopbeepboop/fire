"""
AST Interpreter for Mojo - executes parsed AST nodes from our parser.

This allows us to run Mojo code by:
1. Parsing .mojo files to AST
2. Executing AST via this interpreter
3. Comparing output to verify correctness

Eventually will be transpiled to .mojo for full bootstrap.
"""

import sys
import re
from dataclasses import dataclass
import ast_nodes as N


class ReturnValue(Exception):
    """Exception used to implement return statements."""
    def __init__(self, value=None):
        self.value = value


class BreakException(Exception):
    """Exception used to implement break statements."""
    pass


class ContinueException(Exception):
    """Exception used to implement continue statements."""
    pass


class Scope:
    """Manages variable and function scopes."""
    def __init__(self, parent=None):
        self.parent = parent
        self.vars = {}

    def define(self, name, value):
        self.vars[name] = value

    def get(self, name):
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"name '{name}' is not defined")

    def set(self, name, value):
        if name in self.vars:
            self.vars[name] = value
        elif self.parent:
            self.parent.set(name, value)
        else:
            self.vars[name] = value


class MojoFunction:
    """Represents a function defined in Mojo code."""
    def __init__(self, name, params, body, closure_scope):
        self.name = name
        self.params = params
        self.body = body
        self.closure_scope = closure_scope

    def __call__(self, interpreter, *args, **kwargs):
        # Create new scope for function execution
        func_scope = Scope(parent=self.closure_scope)

        # Bind parameters to arguments
        for i, param in enumerate(self.params):
            if i < len(args):
                func_scope.define(param, args[i])
            elif param in kwargs:
                func_scope.define(param, kwargs[param])
            else:
                func_scope.define(param, None)

        # Execute function body
        old_scope = interpreter.scope
        interpreter.scope = func_scope
        try:
            for stmt in self.body:
                interpreter.execute(stmt)
            result = None
        except ReturnValue as ret:
            result = ret.value
        finally:
            interpreter.scope = old_scope

        return result


class MojoClass:
    """Represents a class/struct defined in Mojo code."""
    def __init__(self, name, body, methods=None):
        self.name = name
        self.body = body
        self.methods = methods or {}

    def __call__(self, *args, **kwargs):
        instance = type(self.name, (), {})()
        # Set attributes from body or initialization
        for stmt in self.body:
            if isinstance(stmt, N.AssignStmt):
                for target in stmt.targets:
                    if isinstance(target, N.IdentExpr):
                        setattr(instance, target.name, None)
        return instance


class Interpreter:
    """Executes Mojo AST nodes."""

    def __init__(self):
        self.scope = Scope()
        self._setup_builtins()

    def _setup_builtins(self):
        """Setup built-in functions and constants."""
        self.scope.define('None', None)
        self.scope.define('True', True)
        self.scope.define('False', False)

        # Built-in functions
        self.scope.define('len', len)
        self.scope.define('print', print)
        self.scope.define('range', range)
        self.scope.define('str', str)
        self.scope.define('int', int)
        self.scope.define('float', float)
        self.scope.define('bool', bool)
        self.scope.define('list', list)
        self.scope.define('dict', dict)
        self.scope.define('set', set)
        self.scope.define('tuple', tuple)
        self.scope.define('open', open)
        self.scope.define('isinstance', isinstance)
        self.scope.define('hasattr', hasattr)
        self.scope.define('getattr', getattr)
        self.scope.define('setattr', setattr)
        self.scope.define('type', type)
        self.scope.define('enumerate', enumerate)
        self.scope.define('zip', zip)
        self.scope.define('max', max)
        self.scope.define('min', min)
        self.scope.define('sum', sum)
        self.scope.define('sorted', sorted)
        self.scope.define('reversed', reversed)
        self.scope.define('map', map)
        self.scope.define('filter', filter)
        self.scope.define('Exception', Exception)

    def execute(self, node):
        """Execute an AST node."""
        if node is None:
            return None

        method_name = f'execute_{type(node).__name__}'
        method = getattr(self, method_name, None)

        if method is None:
            raise NotImplementedError(f"No handler for {type(node).__name__}")

        return method(node)

    def execute_Module(self, node: N.Module):
        """Execute module (top-level statements)."""
        result = None
        for stmt in node.body:
            result = self.execute(stmt)
        return result

    def execute_FunctionDef(self, node: N.FunctionDef):
        """Execute function definition."""
        func = MojoFunction(node.name, node.params, node.body, self.scope)
        self.scope.define(node.name, func)
        return func

    def execute_StructDef(self, node: N.StructDef):
        """Execute struct/class definition."""
        cls = MojoClass(node.name, node.body)
        self.scope.define(node.name, cls)
        return cls

    def execute_ImportStmt(self, node: N.ImportStmt):
        """Execute import statement."""
        # For now, just skip imports - modules are pre-loaded
        return None

    def execute_FromImportStmt(self, node: N.FromImportStmt):
        """Execute from-import statement."""
        # For now, just skip imports - modules are pre-loaded
        return None

    def execute_AssignStmt(self, node: N.AssignStmt):
        """Execute assignment statement."""
        value = self.eval_expr(node.value)
        for target in node.targets:
            self._assign_target(target, value)
        return value

    def _assign_target(self, target, value):
        """Assign a value to a target (variable, member, subscript, etc.)."""
        if isinstance(target, N.IdentExpr):
            self.scope.define(target.name, value)
        elif isinstance(target, N.MemberExpr):
            obj = self.eval_expr(target.obj)
            setattr(obj, target.member, value)
        elif isinstance(target, N.SubscriptExpr):
            obj = self.eval_expr(target.obj)
            idx = self.eval_expr(target.index)
            obj[idx] = value
        else:
            raise NotImplementedError(f"Cannot assign to {type(target).__name__}")

    def execute_ReturnStmt(self, node: N.ReturnStmt):
        """Execute return statement."""
        value = self.eval_expr(node.value) if hasattr(node, 'value') and node.value else None
        raise ReturnValue(value)

    def execute_IfStmt(self, node: N.IfStmt):
        """Execute if statement."""
        cond = self.eval_expr(node.condition)
        if cond:
            for stmt in node.then_body:
                self.execute(stmt)
        else:
            if node.elifs:
                for elif_cond, elif_body in node.elifs:
                    if self.eval_expr(elif_cond):
                        for stmt in elif_body:
                            self.execute(stmt)
                        return None
            if node.else_body:
                for stmt in node.else_body:
                    self.execute(stmt)
        return None

    def execute_WhileStmt(self, node: N.WhileStmt):
        """Execute while statement."""
        while self.eval_expr(node.condition):
            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ForStmt(self, node: N.ForStmt):
        """Execute for statement."""
        iterable = self.eval_expr(node.iterable)
        for value in iterable:
            # Bind loop variable(s)
            if len(node.targets) == 1:
                self.scope.define(node.targets[0], value)
            else:
                # Unpacking
                for i, target in enumerate(node.targets):
                    self.scope.define(target, value[i] if isinstance(value, (list, tuple)) else value)

            try:
                for stmt in node.body:
                    self.execute(stmt)
            except BreakException:
                break
            except ContinueException:
                continue
        return None

    def execute_ExprStmt(self, node: N.ExprStmt):
        """Execute expression statement."""
        return self.eval_expr(node.value)

    def execute_PassStmt(self, node: N.PassStmt):
        """Execute pass statement."""
        return None

    def execute_BreakStmt(self, node: N.BreakStmt):
        """Execute break statement."""
        raise BreakException()

    def execute_ContinueStmt(self, node: N.ContinueStmt):
        """Execute continue statement."""
        raise ContinueException()

    def execute_WithStmt(self, node: N.WithStmt):
        """Execute with statement."""
        # For now, simple implementation without context manager protocol
        ctx = self.eval_expr(node.expr)
        if hasattr(ctx, '__enter__'):
            ctx.__enter__()
        self.scope.define(node.var, ctx)
        try:
            for stmt in node.body:
                self.execute(stmt)
        finally:
            if hasattr(ctx, '__exit__'):
                ctx.__exit__(None, None, None)
        return None

    def execute_TryStmt(self, node: N.TryStmt):
        """Execute try statement."""
        try:
            for stmt in node.body:
                self.execute(stmt)
        except Exception as e:
            if node.handlers:
                handled = False
                for exc_type, handler_body in node.handlers:
                    if exc_type is None or isinstance(e, self.eval_expr(exc_type)):
                        for stmt in handler_body:
                            self.execute(stmt)
                        handled = True
                        break
                if not handled:
                    raise
            else:
                raise
        finally:
            if node.finally_body:
                for stmt in node.finally_body:
                    self.execute(stmt)
        return None

    # Expression evaluation

    def eval_expr(self, expr):
        """Evaluate an expression."""
        if expr is None:
            return None

        method_name = f'eval_{type(expr).__name__}'
        method = getattr(self, method_name, None)

        if method is None:
            raise NotImplementedError(f"No handler for {type(expr).__name__}")

        return method(expr)

    def eval_IdentExpr(self, expr: N.IdentExpr):
        """Evaluate identifier."""
        return self.scope.get(expr.name)

    def eval_IntLiteral(self, expr: N.IntLiteral):
        """Evaluate integer literal."""
        return expr.value

    def eval_FloatLiteral(self, expr: N.FloatLiteral):
        """Evaluate float literal."""
        return expr.value

    def eval_StringLiteral(self, expr: N.StringLiteral):
        """Evaluate string literal."""
        return expr.value

    def eval_BoolLiteral(self, expr: N.BoolLiteral):
        """Evaluate boolean literal."""
        return expr.value

    def eval_NoneLiteral(self, expr: N.NoneLiteral):
        """Evaluate None literal."""
        return None

    def eval_ListLiteral(self, expr: N.ListLiteral):
        """Evaluate list literal."""
        return [self.eval_expr(e) for e in expr.elements]

    def eval_DictLiteral(self, expr: N.DictLiteral):
        """Evaluate dict literal."""
        result = {}
        for key, value in expr.pairs:
            result[self.eval_expr(key)] = self.eval_expr(value)
        return result

    def eval_SetLiteral(self, expr: N.SetLiteral):
        """Evaluate set literal."""
        return {self.eval_expr(e) for e in expr.elements}

    def eval_TupleLiteral(self, expr: N.TupleLiteral):
        """Evaluate tuple literal."""
        return tuple(self.eval_expr(e) for e in expr.elements)

    def eval_BinaryOp(self, expr: N.BinaryOp):
        """Evaluate binary operation."""
        left = self.eval_expr(expr.left)
        right = self.eval_expr(expr.right)

        op = expr.op
        if op == '+': return left + right
        elif op == '-': return left - right
        elif op == '*': return left * right
        elif op == '/': return left / right
        elif op == '//': return left // right
        elif op == '%': return left % right
        elif op == '**': return left ** right
        elif op == '==': return left == right
        elif op == '!=': return left != right
        elif op == '<': return left < right
        elif op == '>': return left > right
        elif op == '<=': return left <= right
        elif op == '>=': return left >= right
        elif op == 'and': return left and right
        elif op == 'or': return left or right
        elif op == 'in': return left in right
        elif op == 'is': return left is right
        elif op == '&': return left & right
        elif op == '|': return left | right
        elif op == '^': return left ^ right
        elif op == '<<': return left << right
        elif op == '>>': return left >> right
        else:
            raise NotImplementedError(f"Binary operator {op} not implemented")

    def eval_UnaryOp(self, expr: N.UnaryOp):
        """Evaluate unary operation."""
        operand = self.eval_expr(expr.operand)
        op = expr.op

        if op == '-': return -operand
        elif op == '+': return +operand
        elif op == '~': return ~operand
        elif op == 'not': return not operand
        else:
            raise NotImplementedError(f"Unary operator {op} not implemented")

    def eval_CallExpr(self, expr: N.CallExpr):
        """Evaluate function call."""
        func = self.eval_expr(expr.func)
        args = [self.eval_expr(arg) for arg in expr.args]
        kwargs = {}

        if isinstance(func, MojoFunction):
            return func(self, *args, **kwargs)
        else:
            return func(*args, **kwargs)

    def eval_MemberExpr(self, expr: N.MemberExpr):
        """Evaluate member access."""
        obj = self.eval_expr(expr.obj)
        return getattr(obj, expr.member)

    def eval_SubscriptExpr(self, expr: N.SubscriptExpr):
        """Evaluate subscript access."""
        obj = self.eval_expr(expr.obj)
        idx = self.eval_expr(expr.index)
        return obj[idx]

    def eval_SliceExpr(self, expr: N.SliceExpr):
        """Evaluate slice expression."""
        obj = self.eval_expr(expr.obj)
        start = self.eval_expr(expr.start) if expr.start else None
        stop = self.eval_expr(expr.stop) if expr.stop else None
        return obj[start:stop]

    def eval_TernaryExpr(self, expr: N.TernaryExpr):
        """Evaluate ternary conditional."""
        condition = self.eval_expr(expr.condition)
        if condition:
            return self.eval_expr(expr.then_val)
        else:
            return self.eval_expr(expr.else_val)
