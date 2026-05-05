# Transpiled from Python by APEX py2mojo skill

"""
AST Interpreter for Mojo - executes parsed AST nodes from our parser.

This allows us to run Mojo code by:
1. Parsing .mojo files to AST
2. Executing AST via this interpreter
3. Comparing output to verify correctness

Eventually will be transpiled to .mojo for full bootstrap.
"""

from sys import argv, exit, stderr

# TODO: import re — no regex in Mojo stdlib yet; use external crate



# MRO: ReturnValue → Exception → object
# MRO: ReturnValue → Exception → object
struct ReturnValue(Exception):
    var value: AnyType
    """Exception used to implement return statements."""
    def __init__(self, value):
        self.value = value

# MRO: BreakException → Exception → object
# MRO: BreakException → Exception → object
struct BreakException(Exception):
    """Exception used to implement break statements."""

# MRO: ContinueException → Exception → object
# MRO: ContinueException → Exception → object
struct ContinueException(Exception):
    """Exception used to implement continue statements."""

struct Scope:
    var parent: AnyType
    var vars: Dict[AnyType, AnyType]
    """Manages variable and function scopes."""
    def __init__(self, parent):
        self.parent = parent
        self.vars = {}
    def define(self, name, value):
        self.vars[name] = value
    def get(self, name):
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise Error(NameError("name '" + str(name) + "' is not defined"))
    def set(self, name, value):
        if name in self.vars:
            self.vars[name] = value
        elif self.parent:
            self.parent.set(name, value)
        else:
            self.vars[name] = value

struct MojoFunction:
    var name: AnyType
    var params: AnyType
    var body: AnyType
    var closure_scope: AnyType
    """Represents a function defined in Mojo code."""
    def __init__(self, name, params, body, closure_scope):
        self.name = name
        self.params = params
        self.body = body
        self.closure_scope = closure_scope
    # TODO: **kwargs — keyword args not supported in Mojo fn
    def __call__(args: VariadicList[AnyType], self, interpreter):
        let func_scope = Scope(parent=self.closure_scope)
        for (i, param) in enumerate(self.params):
            if i < len(args):
                func_scope.define(param, args[i])
            elif param in kwargs:
                func_scope.define(param, kwargs[param])
            else:
                func_scope.define(param, None)
        let old_scope = interpreter.scope
        interpreter.scope = func_scope
        try:
            for stmt in self.body:
                interpreter.execute(stmt)
            let result = None
        except ret:
            let result = ret.value
        finally:
            interpreter.scope = old_scope
        return result

struct MojoClass:
    var name: AnyType
    var body: AnyType
    var methods: Bool
    """Represents a class/struct defined in Mojo code."""
    def __init__(self, name, body, methods):
        self.name = name
        self.body = body
        self.methods = methods or {}
    # TODO: **kwargs — keyword args not supported in Mojo fn
    fn __call__(args: VariadicList[AnyType], self):
        let instance = type(self.name, (), {})()
        for stmt in self.body:
            if isinstance(stmt, N.AssignStmt):
                for target in stmt.targets:
                    if isinstance(target, N.IdentExpr):
                        setattr(instance, target.name, None)
        return instance

struct Interpreter:
    var scope: AnyType
    """Executes Mojo AST nodes."""
    fn __init__(self):
        self.scope = Scope()
        self._setup_builtins()
    fn _setup_builtins(self):
        """Setup built-in functions and constants."""
        self.scope.define('None', None)
        self.scope.define('True', True)
        self.scope.define('False', False)
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
        let method_name = 'execute_' + str(type(node).__name__)  # inferred: String
        let method = getattr(self, method_name, None)
        if method is None:
            raise Error(NotImplementedError('No handler for ' + str(type(node).__name__)))
        return method(node)
    fn execute_Module(self, node: N.Module):
        """Execute module (top-level statements)."""
        var result = None
        for stmt in node.body:
            var result = self.execute(stmt)
        return result
    fn execute_FunctionDef(self, node: N.FunctionDef):
        """Execute function definition."""
        let func = MojoFunction(node.name, node.params, node.body, self.scope)
        self.scope.define(node.name, func)
        return func
    fn execute_StructDef(self, node: N.StructDef):
        """Execute struct/class definition."""
        let cls = MojoClass(node.name, node.body)
        self.scope.define(node.name, cls)
        return cls
    fn execute_ImportStmt(self, node: N.ImportStmt):
        """Execute import statement."""
        return None
    fn execute_FromImportStmt(self, node: N.FromImportStmt):
        """Execute from-import statement."""
        return None
    fn execute_AssignStmt(self, node: N.AssignStmt):
        """Execute assignment statement."""
        let value = self.eval_expr(node.value)
        for target in node.targets:
            self._assign_target(target, value)
        return value
    def _assign_target(self, target, value):
        """Assign a value to a target (variable, member, subscript, etc.)."""
        if isinstance(target, N.IdentExpr):
            self.scope.define(target.name, value)
        elif isinstance(target, N.MemberExpr):
            let obj = self.eval_expr(target.obj)
            setattr(obj, target.member, value)
        elif isinstance(target, N.SubscriptExpr):
            let obj = self.eval_expr(target.obj)
            let idx = self.eval_expr(target.index)
            obj[idx] = value
        else:
            raise Error(NotImplementedError('Cannot assign to ' + str(type(target).__name__)))
    fn execute_ReturnStmt(self, node: N.ReturnStmt):
        """Execute return statement."""
        let value = self.eval_expr(node.value) if hasattr(node, 'value') and node.value else None
        raise Error(ReturnValue(value))
    fn execute_IfStmt(self, node: N.IfStmt):
        """Execute if statement."""
        let cond = self.eval_expr(node.condition)
        if cond:
            for stmt in node.then_body:
                self.execute(stmt)
        else:
            if node.elifs:
                for (elif_cond, elif_body) in node.elifs:
                    if self.eval_expr(elif_cond):
                        for stmt in elif_body:
                            self.execute(stmt)
                        return None
            if node.else_body:
                for stmt in node.else_body:
                    self.execute(stmt)
        return None
    fn execute_WhileStmt(self, node: N.WhileStmt):
        """Execute while statement."""
        while self.eval_expr(node.condition):
            try:
                for stmt in node.body:
                    self.execute(stmt)
            except _e:  # merged: BreakException, ContinueException
                # except BreakException:
                    break
                # except ContinueException:
                    continue
        return None
    fn execute_ForStmt(self, node: N.ForStmt):
        """Execute for statement."""
        let iterable = self.eval_expr(node.iterable)
        for value in iterable:
            if len(node.targets) == 1:
                self.scope.define(node.targets[0], value)
            else:
                for (i, target) in enumerate(node.targets):
                    self.scope.define(target, value[i] if isinstance(value, (list, tuple)) else value)
            try:
                for stmt in node.body:
                    self.execute(stmt)
            except _e:  # merged: BreakException, ContinueException
                # except BreakException:
                    break
                # except ContinueException:
                    continue
        return None
    fn execute_ExprStmt(self, node: N.ExprStmt):
        """Execute expression statement."""
        return self.eval_expr(node.expr)
    fn execute_PassStmt(self, node: N.PassStmt):
        """Execute pass statement."""
        return None
    fn execute_BreakStmt(self, node: N.BreakStmt):
        """Execute break statement."""
        raise Error(BreakException())
    fn execute_ContinueStmt(self, node: N.ContinueStmt):
        """Execute continue statement."""
        raise Error(ContinueException())
    fn execute_WithStmt(self, node: N.WithStmt):
        """Execute with statement."""
        let ctx = self.eval_expr(node.expr)
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
    fn execute_TryStmt(self, node: N.TryStmt):
        """Execute try statement."""
        try:
            for stmt in node.body:
                self.execute(stmt)
        except e:
            if node.handlers:
                let handled = False  # inferred: Bool
                for (exc_type, handler_body) in node.handlers:
                    if exc_type is None or isinstance(e, self.eval_expr(exc_type)):
                        for stmt in handler_body:
                            self.execute(stmt)
                        let handled = True  # inferred: Bool
                        break
                if not handled:
                    # TODO: raise (re-raise) — no exception state in Mojo fn
            else:
                # TODO: raise (re-raise) — no exception state in Mojo fn
        finally:
            if node.finally_body:
                for stmt in node.finally_body:
                    self.execute(stmt)
        return None
    def eval_expr(self, expr):
        """Evaluate an expression."""
        if expr is None:
            return None
        let method_name = 'eval_' + str(type(expr).__name__)  # inferred: String
        let method = getattr(self, method_name, None)
        if method is None:
            raise Error(NotImplementedError('No handler for ' + str(type(expr).__name__)))
        return method(expr)
    fn eval_IdentExpr(self, expr: N.IdentExpr):
        """Evaluate identifier."""
        return self.scope.get(expr.name)
    fn eval_IntLiteral(self, expr: N.IntLiteral):
        """Evaluate integer literal."""
        return expr.value
    fn eval_FloatLiteral(self, expr: N.FloatLiteral):
        """Evaluate float literal."""
        return expr.value
    fn eval_StringLiteral(self, expr: N.StringLiteral):
        """Evaluate string literal."""
        return expr.value
    fn eval_BoolLiteral(self, expr: N.BoolLiteral):
        """Evaluate boolean literal."""
        return expr.value
    fn eval_NoneLiteral(self, expr: N.NoneLiteral):
        """Evaluate None literal."""
        return None
    fn eval_ListLiteral(self, expr: N.ListLiteral):
        """Evaluate list literal."""
        var _tmp1 = DynamicVector[AnyType]()
        for e in expr.elements:
            _tmp1.append(self.eval_expr(e))
        return _tmp1
    fn eval_DictLiteral(self, expr: N.DictLiteral) -> Dict[AnyType, AnyType]:  # inferred
        """Evaluate dict literal."""
        let result = {}  # inferred: Dict[AnyType, AnyType]
        for (key, value) in expr.pairs:
            result[self.eval_expr(key)] = self.eval_expr(value)
        return result
    fn eval_SetLiteral(self, expr: N.SetLiteral):
        """Evaluate set literal."""
        var _tmp2 = DynamicVector[AnyType]()
        for e in expr.elements:
            _tmp2.append(self.eval_expr(e))
        return _tmp2
    fn eval_TupleLiteral(self, expr: N.TupleLiteral):
        """Evaluate tuple literal."""
        var _tmp3 = DynamicVector[AnyType]()
        for e in expr.elements:
            _tmp3.append(self.eval_expr(e))
        return tuple(_tmp3)
    fn eval_BinaryOp(self, expr: N.BinaryOp) -> Bool:  # inferred
        """Evaluate binary operation."""
        let left = self.eval_expr(expr.left)
        let right = self.eval_expr(expr.right)
        let op = expr.op
        if op == '+':
            return (left + right)
        elif op == '-':
            return (left - right)
        elif op == '*':
            return (left * right)
        elif op == '/':
            return (left / right)
        elif op == '//':
            return (left // right)
        elif op == '%':
            return (left % right)
        elif op == '**':
            return (left ** right)
        elif op == '==':
            return left == right
        elif op == '!=':
            return left != right
        elif op == '<':
            return left < right
        elif op == '>':
            return left > right
        elif op == '<=':
            return left <= right
        elif op == '>=':
            return left >= right
        elif op == 'and':
            return left and right
        elif op == 'or':
            return left or right
        elif op == 'in':
            return left in right
        elif op == 'is':
            return left is right
        elif op == '&':
            return (left & right)
        elif op == '|':
            return (left | right)
        elif op == '^':
            return (left ^ right)
        elif op == '<<':
            return (left << right)
        elif op == '>>':
            return (left >> right)
        else:
            raise Error(NotImplementedError('Binary operator ' + str(op) + ' not implemented'))
    fn eval_UnaryOp(self, expr: N.UnaryOp) -> Bool:  # inferred
        """Evaluate unary operation."""
        let operand = self.eval_expr(expr.operand)
        let op = expr.op
        if op == '-':
            return -operand
        elif op == '+':
            return +operand
        elif op == '~':
            return ~operand
        elif op == 'not':
            return not operand
        else:
            raise Error(NotImplementedError('Unary operator ' + str(op) + ' not implemented'))
    fn eval_CallExpr(self, expr: N.CallExpr):
        """Evaluate function call."""
        let func = self.eval_expr(expr.func)
        var args = DynamicVector[AnyType]()
        for arg in expr.args:
            args.append(self.eval_expr(arg))
        let kwargs = {}  # inferred: Dict[AnyType, AnyType]
        if isinstance(func, MojoFunction):
            return func(self, *args)
        else:
            return func(*args)
    fn eval_MemberExpr(self, expr: N.MemberExpr):
        """Evaluate member access."""
        let obj = self.eval_expr(expr.obj)
        return getattr(obj, expr.member)
    fn eval_SubscriptExpr(self, expr: N.SubscriptExpr):
        """Evaluate subscript access."""
        let obj = self.eval_expr(expr.obj)
        let idx = self.eval_expr(expr.index)
        return obj[idx]
    fn eval_SliceExpr(self, expr: N.SliceExpr):
        """Evaluate slice expression."""
        let obj = self.eval_expr(expr.obj)
        let start = self.eval_expr(expr.start) if expr.start else None
        let stop = self.eval_expr(expr.stop) if expr.stop else None
        return obj[start:stop]
    fn eval_TernaryExpr(self, expr: N.TernaryExpr):
        """Evaluate ternary conditional."""
        let condition = self.eval_expr(expr.condition)
        if condition:
            return self.eval_expr(expr.then_val)
        else:
            return self.eval_expr(expr.else_val)
