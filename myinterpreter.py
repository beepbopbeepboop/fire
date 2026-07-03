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
import importlib
from dataclasses import dataclass
import ast_nodes as N
try:
    import mojo_compiler
except ImportError:
    mojo_compiler = None


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

    def __init__(self, filename: str = None):
        # Increase recursion limit for meta-programming (interpreter on itself)
        import sys
        old_limit = sys.getrecursionlimit()
        if old_limit < 50000:
            sys.setrecursionlimit(50000)

        self.scope = Scope()
        self.filename = filename
        self._setup_builtins()

    def _is_instance(self, obj, class_name):
        """Check if obj is an instance of class_name from either ast_nodes or mojo_compiler."""
        if isinstance(obj, getattr(N, class_name, type(None))):
            return True
        if mojo_compiler and hasattr(mojo_compiler, class_name):
            if isinstance(obj, getattr(mojo_compiler, class_name)):
                return True
        return False

    def _setup_builtins(self):
        """Setup built-in functions and constants."""
        self.scope.define('None', None)
        self.scope.define('True', True)
        self.scope.define('False', False)
        self.scope.define('__name__', '__main__')
        self.scope.define('__file__', self.filename or '<input>')

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
        self.scope.define('input', input)
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
        self.scope.define('BaseException', BaseException)
        self.scope.define('KeyboardInterrupt', KeyboardInterrupt)
        self.scope.define('EOFError', EOFError)
        self.scope.define('ValueError', ValueError)
        self.scope.define('TypeError', TypeError)
        self.scope.define('RuntimeError', RuntimeError)
        self.scope.define('StopIteration', StopIteration)

        # Standard library modules
        import os
        import sys
        import subprocess
        import shutil
        import sysconfig
        import platform
        import tempfile
        import traceback
        self.scope.define('os', os)
        self.scope.define('sys', sys)
        self.scope.define('subprocess', subprocess)
        self.scope.define('shutil', shutil)
        self.scope.define('sysconfig', sysconfig)
        self.scope.define('platform', platform)
        self.scope.define('tempfile', tempfile)
        self.scope.define('traceback', traceback)

        # Interpreter itself for bootstrapping
        self.scope.define('Interpreter', Interpreter)

        # Parser and compiler functions
        try:
            from mojo_compiler import py_tokenize, Parser as MojoParser
            self.scope.define('py_tokenize', py_tokenize)
            self.scope.define('Parser', MojoParser)
        except ImportError:
            pass

        # GIMPLE codegen
        try:
            from gimple_codegen import compile_to_gimple
            self.scope.define('compile_to_gimple', compile_to_gimple)
        except ImportError:
            pass

    def execute(self, node: object) -> object:
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
        # Extract parameter names from various formats
        params = []
        if hasattr(node, 'params') and node.params:
            for p in node.params:
                if isinstance(p, str):
                    params.append(p)
                elif isinstance(p, tuple):
                    # Handle (name, type_annotation) tuples
                    params.append(p[0])
                elif hasattr(p, 'name'):
                    params.append(p.name)
                elif isinstance(p, dict) and 'name' in p:
                    params.append(p['name'])
                else:
                    # Fallback: try to extract name from string representation
                    p_str = str(p)
                    if '(' in p_str:
                        # Parse string like "('n', None)" to get 'n'
                        try:
                            import ast
                            parsed = ast.literal_eval(p_str)
                            if isinstance(parsed, tuple):
                                params.append(parsed[0])
                            else:
                                params.append(parsed)
                        except:
                            params.append(p_str)
                    else:
                        params.append(p_str)
        func = MojoFunction(node.name, params, node.body, self.scope)
        self.scope.define(node.name, func)
        return func

    def execute_StructDef(self, node: N.StructDef):
        """Execute struct/class definition."""
        cls = MojoClass(node.name, node.body)
        self.scope.define(node.name, cls)
        return cls

    def execute_ImportStmt(self, node: N.ImportStmt):
        """Execute `import mod` / `import mod as alias`.

        The interpreter runs the AST as Python, so we resolve through Python's
        real import machinery and bind the resulting module object into scope.
        Failing loudly (rather than the old silent skip) is the point: a skipped
        import surfaces later as a baffling "name '...' is not defined".
        """
        try:
            mod = importlib.import_module(node.module)
        except ModuleNotFoundError:
            # Not a Python module — assume a sibling .mojo module the interpreter
            # treats as pre-loaded; skip (the historical behavior).
            return None
        if node.alias:
            self.scope.define(node.alias, mod)
        else:
            # `import a.b` binds the top-level package name `a`.
            top = node.module.split('.')[0]
            self.scope.define(top, importlib.import_module(top))
        return None

    def execute_FromImportStmt(self, node: N.FromImportStmt):
        """Execute `from mod import a, b as c` / `from mod import *`."""
        try:
            mod = importlib.import_module(node.module)
        except ModuleNotFoundError:
            # Not a Python module — sibling .mojo module, treated as pre-loaded; skip.
            return None
        if node.wildcard:
            names = getattr(mod, '__all__', None)
            if names is None:
                names = [n for n in dir(mod) if not n.startswith('_')]
            for name in names:
                self.scope.define(name, getattr(mod, name))
            return None
        for name, alias in node.names:
            try:
                value = getattr(mod, name)
            except AttributeError:
                raise NameError(f"cannot import name '{name}' from '{node.module}'")
            self.scope.define(alias or name, value)
        return None

    def execute_AssignStmt(self, node: N.AssignStmt):
        """Execute assignment statement."""
        value = self.eval_expr(node.value)
        # Handle both 'targets' (list) and 'target' (single) for compatibility
        if hasattr(node, 'targets'):
            targets = node.targets
        else:
            targets = [node.target]
        for target in targets:
            self._assign_target(target, value)
        return value

    def execute_AugAssignStmt(self, node):
        """Execute augmented assignment (+=, -=, etc.)."""
        # Get current value
        current = self.eval_expr(node.target)
        # Get RHS value
        rhs = self.eval_expr(node.value)
        # Apply operator
        op = node.op[:-1]  # Remove '=' from the operator (e.g., '+=' -> '+')
        if op == '+':
            new_value = current + rhs
        elif op == '-':
            new_value = current - rhs
        elif op == '*':
            new_value = current * rhs
        elif op == '/':
            new_value = current / rhs
        elif op == '%':
            new_value = current % rhs
        elif op == '//':
            new_value = current // rhs
        elif op == '**':
            new_value = current ** rhs
        elif op == '&':
            new_value = current & rhs
        elif op == '|':
            new_value = current | rhs
        elif op == '^':
            new_value = current ^ rhs
        elif op == '<<':
            new_value = current << rhs
        elif op == '>>':
            new_value = current >> rhs
        else:
            raise NotImplementedError(f"Augmented operator {node.op} not implemented")
        # Assign new value
        self._assign_target(node.target, new_value)
        return new_value

    def _assign_target(self, target, value):
        """Assign a value to a target (variable, member, subscript, tuple, etc.)."""
        if self._is_instance(target, 'IdentExpr'):
            # Check if this is a global variable
            global_vars = getattr(self, 'global_vars', set())
            if target.name in global_vars:
                # Find and update the global scope
                scope = self.scope
                while scope.parent:
                    scope = scope.parent
                scope.define(target.name, value)
            else:
                self.scope.define(target.name, value)
        elif self._is_instance(target, 'MemberExpr'):
            obj = self.eval_expr(target.obj)
            setattr(obj, target.member, value)
        elif self._is_instance(target, 'SubscriptExpr'):
            obj = self.eval_expr(target.obj)
            idx = self.eval_expr(target.index)
            obj[idx] = value
        elif self._is_instance(target, 'TupleExpr') or self._is_instance(target, 'TupleLiteral'):
            # Tuple unpacking: a, b, c = expr or (a, b, c) = expr
            values = list(value) if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)) else [value]
            elements = target.elements
            if len(values) != len(elements):
                raise ValueError(f"Cannot unpack {len(values)} values into {len(elements)} targets")
            for t, v in zip(elements, values):
                self._assign_target(t, v)
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
        # Handle both 'targets' (list) and 'target' (single) for compatibility
        if hasattr(node, 'targets'):
            targets = node.targets
        else:
            targets = [node.target]

        for value in iterable:
            # Bind loop variable(s)
            if len(targets) == 1:
                # Extract name from target if it's an object
                target_name = targets[0]
                if hasattr(target_name, 'name'):
                    target_name = target_name.name
                elif not isinstance(target_name, str):
                    target_name = str(target_name)
                self.scope.define(target_name, value)
            else:
                # Unpacking
                for i, target in enumerate(targets):
                    target_name = target
                    if hasattr(target_name, 'name'):
                        target_name = target_name.name
                    elif not isinstance(target_name, str):
                        target_name = str(target_name)
                    self.scope.define(target_name, value[i] if isinstance(value, (list, tuple)) else value)

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

    def execute_GlobalStmt(self, node):
        """Execute global statement."""
        if hasattr(node, 'names'):
            if not hasattr(self, 'global_vars'):
                self.global_vars = set()
            self.global_vars.update(node.names)
        return None

    def execute_BreakStmt(self, node: N.BreakStmt):
        """Execute break statement."""
        raise BreakException()

    def execute_ContinueStmt(self, node: N.ContinueStmt):
        """Execute continue statement."""
        raise ContinueException()

    def execute_WithStmt(self, node: N.WithStmt):
        """Execute with statement."""
        # With statement: with expr as var: body
        if not node.items:
            # No items, just execute body
            for stmt in node.body:
                self.execute(stmt)
            return None

        item = node.items[0]  # Support single with item for now
        ctx = self.eval_expr(item.expr)
        if hasattr(ctx, '__enter__'):
            ctx.__enter__()
        if item.alias:
            self.scope.define(item.alias, ctx)
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
                for handler in node.handlers:
                    exc_type = handler.exc_type
                    handler_body = handler.body
                    # exc_type can be None (catch all), a string (exc name), or an expression
                    should_handle = False
                    if exc_type is None:
                        should_handle = True
                    elif isinstance(exc_type, str):
                        # If exc_type is a string, look it up in the scope
                        try:
                            exc_class = self.scope.get(exc_type)
                            should_handle = isinstance(e, exc_class)
                        except:
                            should_handle = False
                    else:
                        # Otherwise evaluate it as an expression
                        try:
                            exc_class = self.eval_expr(exc_type)
                            should_handle = isinstance(e, exc_class)
                        except:
                            should_handle = False

                    if should_handle:
                        # Bind exception to variable if handler has a name
                        if handler.name:
                            old_val = None
                            had_old = handler.name in self.scope.vars
                            if had_old:
                                old_val = self.scope.vars[handler.name]
                            self.scope.define(handler.name, e)

                        for stmt in handler_body:
                            self.execute(stmt)

                        # Restore old value if it existed
                        if handler.name:
                            if had_old:
                                self.scope.vars[handler.name] = old_val
                            else:
                                del self.scope.vars[handler.name]

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
        value = expr.value
        # Handle f-strings: if value starts with f" or f', evaluate it as f-string
        if value.startswith('f"') or value.startswith("f'"):
            try:
                # Convert to Python f-string and evaluate
                # Create a scope with current variables
                local_vars = {}
                # Add all variables from current scope
                scope = self.scope
                while scope:
                    for name in scope.vars:
                        if name not in local_vars:
                            local_vars[name] = scope.vars[name]
                    scope = scope.parent
                # Evaluate the f-string
                return eval(value, {"__builtins__": __builtins__}, local_vars)
            except Exception as e:
                # If f-string evaluation fails, return the literal
                return value
        return value

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
        elif op == 'is not': return left is not right
        elif op == '&': return left & right
        elif op == '|': return left | right
        elif op == '^': return left ^ right
        elif op == '<<': return left << right
        elif op == '>>': return left >> right
        else:
            raise NotImplementedError(f"Binary operator {op!r} not implemented")

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

        # Evaluate keyword arguments
        if hasattr(expr, 'keywords') and expr.keywords:
            kwargs = {k: self.eval_expr(v) for k, v in expr.keywords.items()}

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

    def eval_TupleExpr(self, expr):
        """Evaluate tuple expression."""
        return tuple(self.eval_expr(e) for e in expr.elements)

    # Aliases for mojo_compiler node types (ListExpr, DictExpr, SetExpr)
    def eval_ListExpr(self, expr):
        """Evaluate list expression (mojo_compiler naming)."""
        return self.eval_ListLiteral(expr)

    def eval_DictExpr(self, expr):
        """Evaluate dict expression (mojo_compiler naming)."""
        return self.eval_DictLiteral(expr)

    def eval_SetExpr(self, expr):
        """Evaluate set expression (mojo_compiler naming)."""
        return self.eval_SetLiteral(expr)
