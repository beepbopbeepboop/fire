"""Compiler Generator — produces a Python Mojo compiler from a LanguageSpec."""
from __future__ import annotations
import re
import textwrap
from lang_spec import (LanguageSpec, LiteralDef, IntForm, FloatForm, BoolForm,
                        OperatorDef, ControlFlowDef, FunctionSpec, SimpleStmtDef,
                        ImportDef, AssignmentDef, ExpressionDef,
                        TryStmtDef, WithStmtDef, ComptimeDef,
                        LayoutDef,
                        ArgConventionDef, StructSpec, TraitSpec, LifecycleDef,
                        ParameterDef, PointerDef, PythonInteropDef, GPUDef,
                        TestingDef, CollectionTypeDef)

_IS_PUNCT = re.compile(r'^[^A-Za-z0-9_]+$')


# ---------------------------------------------------------------------------
# Spec AST printer
# ---------------------------------------------------------------------------

def dump_spec(spec: LanguageSpec) -> str:
    lines = ['LanguageSpec(']

    def _sec(name, items, fmt):
        if not items: return
        lines.append(f'  {name}=[')
        for item in items:
            lines.append(f'    {fmt(item)},')
        lines.append('  ],')

    if spec.literals:
        lines.append('  literals=[')
        for lit in spec.literals:
            lines.append(f'    LiteralDef(kind={lit.kind!r}, forms=[')
            for f in lit.forms:
                if isinstance(f, IntForm):
                    lines.append(f'      IntForm(name={f.name!r}, base={f.base}, '
                                 f'prefixes={f.prefixes!r}),')
                elif isinstance(f, FloatForm):
                    lines.append(f'      FloatForm(),')
                elif isinstance(f, BoolForm):
                    lines.append(f'      BoolForm(values={f.values!r}),')
            lines.append(f'    ], constraints={lit.constraints!r}),')
        lines.append('  ],')

    _sec('operators', spec.operators,
         lambda o: f'OperatorDef(symbols={o.symbols!r}, prec={o.precedence}, '
                   f'assoc={o.assoc!r})')
    _sec('control_flow', spec.control_flow,
         lambda c: f'ControlFlowDef(kind={c.kind!r}, alt_kws={c.alt_kws!r})')
    _sec('functions', spec.functions,
         lambda f: f'FunctionSpec(keyword={f.keyword!r})')
    _sec('simple_stmts', spec.simple_stmts,
         lambda s: f'SimpleStmtDef(kind={s.kind!r}, has_value={s.has_value})')
    _sec('imports', spec.imports,
         lambda i: f'ImportDef(keyword={i.keyword!r})')
    _sec('assignments', spec.assignments,
         lambda a: f'AssignmentDef(decl_kw={a.declaration_kw!r}, '
                   f'aug_ops={a.aug_ops!r})')
    _sec('expressions', spec.expressions,
         lambda e: f'ExpressionDef(kind={e.kind!r})')
    _sec('try_stmts', spec.try_stmts,
         lambda t: f'TryStmtDef(keywords={t.keywords!r})')
    _sec('with_stmts', spec.with_stmts,
         lambda w: f'WithStmtDef(keyword={w.keyword!r})')
    _sec('comptime', spec.comptime,
         lambda c: f'ComptimeDef(prefix={c.prefix!r}, kinds={c.kinds!r})')
    _sec('layout', spec.layout,
         lambda l: f'LayoutDef(indent_size={l.indent_size}, '
                   f'separator={l.stmt_separator!r}, '
                   f'comment={l.comment_char!r}, '
                   f'has_indentation={l.has_indentation})')
    _sec('arg_conventions', spec.arg_conventions,
         lambda a: f'ArgConventionDef(conventions={a.conventions!r})')
    _sec('structs', spec.structs,
         lambda s: f'StructSpec(decorators={s.decorators!r}, traits={s.traits!r})')
    _sec('traits', spec.traits,
         lambda t: f'TraitSpec(has_where_clause={t.has_where_clause}, builtin_traits={t.builtin_traits!r})')
    _sec('lifecycle', spec.lifecycle,
         lambda l: f'LifecycleDef(transfer_sigil={l.has_transfer_sigil}, copy={l.has_copy_constructor}, move={l.has_move_constructor}, del={l.has_destructor})')
    _sec('parameters', spec.parameters,
         lambda p: f'ParameterDef(syntax={p.syntax!r}, infer_only={p.has_infer_only}, default={p.has_default})')
    _sec('pointers', spec.pointers,
         lambda p: f'PointerDef(types={p.types!r})')
    _sec('python_interop', spec.python_interop,
         lambda p: f'PythonInteropDef(import_fn={p.import_fn!r}, wrapper={p.wrapper_type!r})')
    _sec('gpu', spec.gpu,
         lambda g: f'GPUDef(device={g.device_type!r}, buffers={g.buffer_types!r}, idx_vars={g.index_vars!r})')
    _sec('testing', spec.testing,
         lambda t: f'TestingDef(suite={t.suite_type!r}, fns={t.assertion_fns!r})')
    _sec('collection_types', spec.collection_types,
         lambda c: f'CollectionTypeDef(types={c.types!r})')
    lines.append(')')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Python compiler generator
# ---------------------------------------------------------------------------

class PythonCompilerGen:

    def __init__(self, spec: LanguageSpec):
        self.spec = spec

        # ── Collect all keywords ──────────────────────────────────────
        self._kws: set[str] = set()
        for cf in spec.control_flow:
            self._kws.add(cf.primary_kw)
            self._kws.update(cf.alt_kws)
            if cf.kind == 'for':
                self._kws.add('in')
        for fs in spec.functions:
            self._kws.add(fs.keyword)
        # Add 'fn' as an alternative to 'def' for function declarations (Mojo keyword)
        if 'def' in self._kws:
            self._kws.add('fn')
        for ss in spec.simple_stmts:
            self._kws.add(ss.keyword)
        for ts in spec.try_stmts:
            self._kws.update(ts.keywords)
            self._kws.add(ts.binding_kw)
        for ws in spec.with_stmts:
            self._kws.add(ws.keyword)
            self._kws.add(ws.alias_kw)
        for cd in spec.comptime:
            self._kws.add(cd.prefix)
        if spec.imports:
            self._kws.update(['import', 'from', 'as'])
        if spec.assignments:
            for asgn in spec.assignments:
                if asgn.declaration_kw:
                    self._kws.add(asgn.declaration_kw)
        # Boolean / None / Self as keywords
        for lit in spec.literals:
            if lit.kind == 'bool':
                self._kws.update(['True', 'False'])
            elif lit.kind == 'none':
                self._kws.add('None')
            elif lit.kind == 'self':
                self._kws.add('Self')
        # Keyword operators (not in OP regex)
        self._kws.update(['not', 'and', 'or', 'is'])
        # Function modifiers
        if spec.functions:
            self._kws.add('raises')
        # Ownership / argument-convention keywords
        if spec.arg_conventions:
            for ac in spec.arg_conventions:
                self._kws.update(ac.conventions)
        # Compile-time keyword (ensure it's present)
        self._kws.add('comptime')
        # Struct / trait keywords
        if spec.structs:
            self._kws.add('struct')
        if spec.traits:
            self._kws.add('trait')
        # Add 'class' as an alternative to 'struct' for class definitions
        if 'struct' in self._kws:
            self._kws.add('class')

        # ── Collect augmented ops ─────────────────────────────────────
        self._aug_ops: list[str] = []
        for asgn in spec.assignments:
            self._aug_ops = asgn.aug_ops
            break

        # ── Collect expression kinds present ─────────────────────────
        self._expr_kinds = {e.kind for e in spec.expressions}

    def generate(self) -> str:
        parts = [
            self._header(),
            self._ast_nodes(),
            self._lexer(),
            self._parser(),
            self._codegen(),
            self._driver(),
        ]
        return '\n\n'.join(parts)

    # ==================================================================
    # 1. Header
    # ==================================================================

    def _header(self) -> str:
        lines = [textwrap.dedent("""\
            \"\"\"Generated Mojo compiler — produced by compiler_gen.py from .md spec.\"\"\"
            from __future__ import annotations
            import re
            from dataclasses import dataclass, field
        """)]

        # ── Pointer type shims ─────────────────────────────────────────
        if self.spec.pointers:
            ptr_types = []
            for pd in self.spec.pointers:
                ptr_types.extend(pd.types)
            ptr_types = list(dict.fromkeys(ptr_types))
            if ptr_types:
                lines.append('# ── Mojo pointer type shims ────────────────────────────────────────')
                lines.append('class _MojoPointerBase:')
                lines.append('    def __init__(self, value=None): self._value = value')
                lines.append('    def __getitem__(self, _): return self._value')
                lines.append('    def __setitem__(self, _, v): self._value = v')
                lines.append('')
                for pt in ptr_types:
                    lines.append(f'class {pt}(_MojoPointerBase): pass')
                lines.append('')

        # ── Python interop helpers ─────────────────────────────────────
        if self.spec.python_interop:
            lines.append('# ── Mojo Python interop helpers ────────────────────────────────────')
            lines.append('import importlib as _importlib')
            lines.append('def _python_import(name): return _importlib.import_module(name)')
            lines.append('')

        # ── Testing helpers ────────────────────────────────────────────
        if self.spec.testing:
            lines.append('# ── Mojo testing helpers ───────────────────────────────────────────')
            lines.append('def assert_equal(a, b, msg=""): assert a == b, msg or f"{a!r} != {b!r}"')
            lines.append('def assert_true(v, msg=""): assert v, msg')
            lines.append('def assert_false(v, msg=""): assert not v, msg')
            lines.append('def assert_not_equal(a, b, msg=""): assert a != b, msg or f"{a!r} == {b!r}"')
            lines.append('def assert_almost_equal(a, b, atol=1e-6, msg=""): assert abs(a - b) <= atol, msg or f"|{a!r}-{b!r}| > {atol}"')
            lines.append('def assert_raises(contains=""):')
            lines.append('    import contextlib')
            lines.append('    class _AR:')
            lines.append('        def __enter__(self): return self')
            lines.append('        def __exit__(self, exc_type, exc_val, tb):')
            lines.append('            if exc_type is None: raise AssertionError("Expected an exception")')
            lines.append('            if contains and contains not in str(exc_val): raise AssertionError(f"Exception missing {contains!r}")')
            lines.append('            return True')
            lines.append('    return _AR()')
            lines.append('')
            for td in self.spec.testing:
                if td.suite_type:
                    lines.append('# ── TestSuite helper ───────────────────────────────────────────────')
                    lines.append('class TestSuite:')
                    lines.append('    @staticmethod')
                    lines.append('    def discover_tests(fns=()):')
                    lines.append('        class _Suite:')
                    lines.append('            def __init__(self, fns): self._fns = fns')
                    lines.append('            def run(self):')
                    lines.append('                passed = failed = 0')
                    lines.append('                for name, fn in self._fns:')
                    lines.append('                    try: fn(); passed += 1; print(f"PASS {name}")')
                    lines.append('                    except Exception as e: failed += 1; print(f"FAIL {name}: {e}")')
                    lines.append('                print(f"{passed} passed, {failed} failed")')
                    lines.append('        return _Suite([(fn.__name__, fn) for fn in fns if callable(fn)])')
                    lines.append('')

        # ── ABC import (needed for trait → ABC emission) ──────────────
        lines.append('from abc import abstractmethod')
        lines.append('')

        # ── Reflection API shims ───────────────────────────────────────
        lines.append('# ── Mojo reflection shims ──────────────────────────────────────────')
        lines.append('def struct_field_count(T): return 0')
        lines.append('def struct_field_names(T): return []')
        lines.append('def struct_field_types(T): return []')
        lines.append('def __struct_field_ref(idx, instance): return None')
        lines.append('def conforms_to(T, Trait): return True')
        lines.append('def trait_downcast(Trait, value): return value')
        lines.append('')

        # ── LayoutTensor / Layout shims ──────────────────────────────
        lines.append('# ── Mojo LayoutTensor / Layout shims ───────────────────────────────')
        lines.append('class Layout:')
        lines.append('    def __init__(self, *a, **kw): pass')
        lines.append('    @staticmethod')
        lines.append('    def row_major(r, c): return Layout()')
        lines.append('    @staticmethod')
        lines.append('    def col_major(r, c): return Layout()')
        lines.append('')
        lines.append('class LayoutTensor:')
        lines.append('    def __init__(self, *a, **kw): self._data = []')
        lines.append('    def __getitem__(self, idx): return self._data[idx] if self._data else 0')
        lines.append('    def __setitem__(self, idx, v):')
        lines.append('        while len(self._data) <= (idx if isinstance(idx, int) else 0): self._data.append(0)')
        lines.append('        self._data[idx if isinstance(idx, int) else 0] = v')
        lines.append('    def tile(self, *a, **kw): return self')
        lines.append('')

        # ── Additional UnsafePointer methods ─────────────────────────
        if self.spec.pointers:
            lines.append('# ── Additional UnsafePointer methods ──────────────────────────────')
            lines.append('def _mojo_alloc(T, n): return [None] * n  # alloc[T](n)')
            lines.append('')

        # ── GPU TODO (codegen deferred) ───────────────────────────────
        if self.spec.gpu:
            lines.append('# ── TODO: Mojo GPU (full codegen) ─────────────────────────────────')
            lines.append('# TODO: Full GPU codegen not implemented')
            lines.append('class DeviceContext:')
            lines.append('    def __init__(self, device_id=0, api=""): pass')
            lines.append('    @staticmethod')
            lines.append('    def number_of_devices(): return 0')
            lines.append('    def synchronize(self): pass')
            lines.append('    def enqueue_create_buffer(self, *a, **kw): return None  # TODO')
            lines.append('    def enqueue_create_host_buffer(self, *a, **kw): return None  # TODO')
            lines.append('    def enqueue_copy(self, **kw): pass  # TODO')
            lines.append('    def compile_function(self, *a, **kw): return None  # TODO')
            lines.append('    def enqueue_function(self, *a, **kw): pass  # TODO')
            lines.append('')
            lines.append('class DeviceBuffer:')
            lines.append('    pass  # TODO: full DeviceBuffer impl')
            lines.append('')
            lines.append('class HostBuffer:')
            lines.append('    pass  # TODO: full HostBuffer impl')
            lines.append('')

        return '\n'.join(lines)

    # ==================================================================
    # 2. AST nodes
    # ==================================================================

    def _ast_nodes(self) -> str:
        L = ['# ── AST nodes ──────────────────────────────────────────────────────']

        def dc(name, *fields):
            L.append('@dataclass')
            L.append(f'class {name}:')
            L.append('    pass' if not fields else '\n'.join(f'    {f}' for f in fields))
            L.append('')

        # Literals
        for lit in self.spec.literals:
            cls = _lit_cls(lit.kind)
            if lit.kind == 'integer':    dc(cls, 'value: int')
            elif lit.kind == 'float':    dc(cls, 'value: float')
            elif lit.kind == 'bool':     dc(cls, 'value: bool')
            elif lit.kind == 'none':     dc(cls)
            elif lit.kind == 'self':     dc(cls)
            elif lit.kind in ('string', 'tstring'):  dc(cls, 'value: str')
        # StringLiteral always needed (even if not in spec as parsed form)
        dc('StringLiteral', 'value: str')
        dc('EllipsisLiteral')

        # Expressions
        dc('IdentExpr', 'name: str')
        dc('CallExpr', 'func: object', 'args: list')
        if self.spec.operators:
            dc('BinaryOp', 'op: str', 'left: object', 'right: object')
            dc('UnaryOp',  'op: str', 'operand: object')
        if 'ternary' in self._expr_kinds:
            dc('TernaryExpr', 'condition: object', 'then_val: object', 'else_val: object')
        if 'walrus' in self._expr_kinds:
            dc('WalrusExpr', 'name: str', 'value: object')
        if 'member_access' in self._expr_kinds:
            dc('MemberExpr', 'obj: object', 'member: str')
        if 'subscript' in self._expr_kinds or 'member_access' in self._expr_kinds:
            dc('SubscriptExpr', 'obj: object', 'index: object')
            dc('SliceExpr', 'obj: object', 'start: object', 'stop: object',
               'step: object = None')
        if 'list' in self._expr_kinds or 'comprehension_list' in self._expr_kinds:
            dc('ListExpr', 'elements: list')
        if 'dict' in self._expr_kinds:
            dc('DictExpr', 'pairs: list  # [(key_expr, val_expr), ...]')
        if 'set' in self._expr_kinds:
            dc('SetExpr', 'elements: list')
        if 'tuple' in self._expr_kinds:
            dc('TupleExpr', 'elements: list')
        if any(k.startswith('comprehension') for k in self._expr_kinds):
            dc('Comprehension',
               'kind: str     # list / set / dict',
               'element: object',
               'key: object = None     # dict key',
               'generators: list = field(default_factory=list)')
            dc('Generator', 'target: str', 'iterable: object',
               'conditions: list = field(default_factory=list)')

        # Statements
        dc('ExprStmt', 'value: object')
        if self.spec.assignments:
            dc('AssignStmt', 'target: object', 'value: object')
            dc('AugAssignStmt', 'target: object', 'op: str', 'value: object')
            dc('VarDecl', 'name: str', 'type_ann: object', 'value: object')
            dc('MultiAssignStmt', 'targets: list', 'value: object')
        if self.spec.imports:
            dc('ImportStmt', 'module: str', 'alias: object  # str|None')
            dc('FromImportStmt', 'module: str',
               'names: list      # [(name, alias|None), ...]',
               'wildcard: bool = False')

        # Control flow
        has_loop_else = any('else' in cf.alt_kws
                            for cf in self.spec.control_flow if cf.kind in ('while','for'))
        for cf in self.spec.control_flow:
            if cf.kind == 'if':
                dc('IfStmt', 'condition: object', 'then_body: list',
                   'elifs: list', 'else_body: object')
            elif cf.kind == 'while':
                fields = ['condition: object', 'body: list']
                if has_loop_else: fields.append('else_body: object = None')
                dc('WhileStmt', *fields)
            elif cf.kind == 'for':
                fields = ['target: object', 'iterable: object', 'body: list']
                if has_loop_else: fields.append('else_body: object = None')
                dc('ForStmt', *fields)

        if self.spec.functions:
            dc('FunctionDef', 'name: str',
               'params: list      # [(name, type|None), ...]',
               'return_type: object', 'body: list',
               'decorators: list = field(default_factory=list)',
               'param_convs: dict = field(default_factory=dict)  # name -> convention str|None')

        for ss in self.spec.simple_stmts:
            cls = ss.kind.title() + 'Stmt'
            if ss.has_value:
                if ss.kind == 'assert':
                    dc(cls, 'value: object  # None if bare', 'msg: object = None')
                else:
                    dc(cls, 'value: object  # None if bare')
            else:
                dc(cls)

        if self.spec.structs:
            dc('StructDef', 'name: str', 'fields: list', 'methods: list',
               'decorators: list = field(default_factory=list)')
        if self.spec.traits:
            dc('TraitDef', 'name: str', 'methods: list',
               'decorators: list = field(default_factory=list)')
        if self.spec.try_stmts:
            dc('ExceptHandler', 'exc_type: object', 'name: object', 'body: list')
            dc('TryStmt', 'body: list', 'handlers: list',
               'else_body: object', 'finally_body: object')
        if self.spec.with_stmts:
            dc('WithItem', 'expr: object', 'alias: object')
            dc('WithStmt', 'items: list', 'body: list')
        for cd in self.spec.comptime:
            if 'if'  in cd.kinds: dc('ComptimeIfStmt',  'condition: object', 'then_body: list', 'elifs: list', 'else_body: object')
            if 'for' in cd.kinds: dc('ComptimeForStmt', 'target: str', 'iterable: object', 'body: list')

        return '\n'.join(L)

    # ==================================================================
    # 3. Lexer
    # ==================================================================

    def _lexer(self) -> str:
        L = ['# ── Lexer ──────────────────────────────────────────────────────────']

        alts = []

        # Float before INT
        for lit in self.spec.literals:
            if lit.kind == 'float':
                for form in lit.forms:
                    alts.append(f'(?P<FLOAT>{form.full_re()})')

        # Prefixed INT forms (hex/octal/binary) before decimal
        for lit in self.spec.literals:
            if lit.kind == 'integer':
                prefixed = [f for f in lit.forms if isinstance(f, IntForm) and f.prefixes]
                decimal  = [f for f in lit.forms if isinstance(f, IntForm) and not f.prefixes]
                for form in prefixed:
                    pfx = '|'.join(re.escape(p) for p in form.prefixes)
                    alts.append(f'(?:{pfx}){form.digit_re}')
                for form in decimal:
                    alts.append(f'(?P<INT>{form.digit_re})')

        # Augmented assignment (before OP so += isn't split as + and =)
        if self._aug_ops:
            aug_re = '|'.join(re.escape(op) for op in self._aug_ops)
            alts.append(f'(?P<AUGASSIGN>{aug_re})')

        # ARROW before OP (so -> isn't split as - and >)
        alts.append(r'(?P<ARROW>->)')

        # Operator symbols — pure punctuation, longest first
        op_syms: list[str] = []
        seen_ops: set[str] = set()
        all_syms = []
        for op in self.spec.operators:
            for sym in op.symbols:
                if _IS_PUNCT.match(sym) and sym not in seen_ops:
                    all_syms.append(sym)
                    seen_ops.add(sym)
        all_syms.sort(key=len, reverse=True)
        for sym in all_syms:
            op_syms.append(re.escape(sym))
        if op_syms:
            alts.append(f'(?P<OP>{"|".join(op_syms)})')

        # ASSIGN after OP (so == is matched before =)
        alts.append(r'(?P<ASSIGN>=)')
        # Transfer sigil ^ (Mojo ownership transfer — stripped in codegen)
        alts.append(r'(?P<XFER>\^)')

        # String literals (including backtick-quoted MLIR types)
        alts.append(r'(?P<STRING>\"\"\"[\s\S]*?\"\"\"|\'\'\'[\s\S]*?\'\'\'|\"(?:[^\"\\]|\\.)*\"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`)')

        # Structural tokens
        alts += [
            r'(?P<DOT>\.)',
            r'(?P<COLON>:)',
            r'(?P<LPAREN>\()',
            r'(?P<RPAREN>\))',
            r'(?P<LBRACKET>\[)',
            r'(?P<RBRACKET>\])',
            r'(?P<LBRACE>\{)',
            r'(?P<RBRACE>\})',
            r'(?P<COMMA>,)',
            r'(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)',
            r'(?P<WS>[^\S\n]+)',
            r'(?P<UNK>.)',
        ]

        master = '|'.join(alts)
        kw_set = repr(self._kws)

        # ── Derive layout parameters from spec (fall back to safe defaults) ──
        layout    = self.spec.layout[0] if self.spec.layout else None
        indent_sz  = layout.indent_size      if layout else 4
        sep_char   = layout.stmt_separator   if layout else ';'
        cmt_char   = layout.comment_char     if layout else '#'
        has_indent = layout.has_indentation  if layout else True

        # Build a human-readable docstring listing the active rules
        rule_lines = ['Tokenize with layout rules derived from the .md spec:']
        if has_indent:
            rule_lines.append(f'    - Indentation ({indent_sz} spaces) → INDENT/DEDENT')
        if sep_char:
            rule_lines.append(f'    - {sep_char!r} → statement separator')
        if cmt_char:
            rule_lines.append(f'    - {cmt_char!r} → end-of-line comment')
        rule_lines.append('    - Multi-line statements use indentation (no backslash continuation)')
        docstring = '\n    '.join(rule_lines)

        L += [
            f'_KEYWORDS = {kw_set}',
            '',
            f'_TOKEN_RE = re.compile(r\'{master}\')',
            f'_INDENT_SIZE    = {indent_sz}',
            f'_SEP_CHAR       = {sep_char!r}',
            f'_CMT_CHAR       = {cmt_char!r}',
            f'_HAS_INDENT     = {has_indent}',
            '',
            '@dataclass',
            'class Token:',
            '    kind: str',
            '    value: str',
            '',
            '# ── Layout helpers ──────────────────────────────────────────────────',
        ]

        if cmt_char:
            cmt = repr(cmt_char)
            L += [
                'def _strip_inline_comment(s: str) -> str:',
                f'    """Remove trailing {cmt_char} comment, respecting quoted strings."""',
                '    in_str = None',
                '    i = 0',
                '    while i < len(s):',
                '        c = s[i]',
                '        if in_str:',
                '            if c == "\\\\" : i += 2; continue',
                '            if c == in_str: in_str = None',
                '        elif c in (\'"\', "\'"):',
                '            in_str = c',
                f'        elif c == _CMT_CHAR:',
                '            return s[:i]',
                '        i += 1',
                '    return s',
                '',
            ]
        else:
            L += [
                'def _strip_inline_comment(s: str) -> str: return s',
                '',
            ]

        if sep_char:
            L += [
                'def _split_on_separators(s: str) -> list[str]:',
                f'    """Split on {sep_char!r} statement separator, respecting quoted strings."""',
                '    parts, buf, in_str = [], [], None',
                '    i = 0',
                '    while i < len(s):',
                '        c = s[i]',
                '        if in_str:',
                '            buf.append(c)',
                '            if c == "\\\\" and i + 1 < len(s):',
                '                i += 1; buf.append(s[i])',
                '            elif c == in_str:',
                '                in_str = None',
                '        elif c in (\'"\', "\'"):',
                '            in_str = c; buf.append(c)',
                f'        elif c == _SEP_CHAR:',
                '            parts.append("".join(buf)); buf = []',
                '        else:',
                '            buf.append(c)',
                '        i += 1',
                '    parts.append("".join(buf))',
                '    return parts',
                '',
            ]
        else:
            L += [
                'def _split_on_separators(s: str) -> list[str]: return [s]',
                '',
            ]

        L += [
            'def tokenize(src: str) -> list[Token]:',
            f'    """{docstring}"""',
        ]

        # Mojo uses indentation for multi-line statements; no backslash continuation
        # Pre-process to extract multi-line strings before line-by-line processing
        L += [
            '    import re',
            '    string_cache = {}',
            '    string_idx = [0]',
            '    def replace_multiline_strings(src):',
            '        def repl(m):',
            '            placeholder = f"__MOJO_STR_{string_idx[0]}__"',
            '            string_cache[placeholder] = m.group(0)',
            '            string_idx[0] += 1',
            '            return placeholder',
            '        # Match triple-quoted strings (both """ and \'\'\')',
            '        src = re.sub(r\'"""[\\s\\S]*?"""\', repl, src)',
            '        src = re.sub(r"\'\'\'[\\s\\S]*?\'\'\'", repl, src)',
            '        return src',
            '    src = replace_multiline_strings(src)',
            '    joined = src.splitlines()',
        ]

        L += [
            '    # Phase 2: lex line by line',
            '    out: list[Token] = []',
            '    stack = [0]',
            '    paren_depth = 0  # Track (), [], {} nesting to suppress INDENT/DEDENT inside',
            '    for line in joined:',
            f'        expanded = line.expandtabs(_INDENT_SIZE)',
            '        raw_content = expanded.lstrip()',
            f'        if not raw_content or raw_content.startswith(_CMT_CHAR): continue'
            if cmt_char else
            '        if not raw_content: continue',
            '        content = _strip_inline_comment(raw_content).rstrip()',
            '        if not content: continue',
        ]

        if has_indent:
            L += [
                '        indent = len(expanded) - len(raw_content)',
            ]

        L += [
            '        sub_stmts = _split_on_separators(content)',
            '        for stmt_idx, stmt in enumerate(sub_stmts):',
            '            stmt = stmt.strip()',
            '            if not stmt: continue',
        ]

        if has_indent:
            L += [
                '            # Only emit INDENT/DEDENT when at paren depth 0',
                '            if stmt_idx == 0 and paren_depth == 0:',
                '                if indent > stack[-1]:',
                '                    stack.append(indent)',
                '                    out.append(Token("INDENT", ""))',
                '                else:',
                '                    while indent < stack[-1]:',
                '                        stack.pop()',
                '                        out.append(Token("DEDENT", ""))',
            ]

        L += [
            '            for m in _TOKEN_RE.finditer(stmt):',
            '                kind = m.lastgroup or "INT"',
            '                val  = m.group()',
            '                if kind in ("WS", "UNK", "XFER"): continue',
            '                if kind == "NAME" and val in _KEYWORDS: kind = "KW"',
            '                # Restore multi-line strings from cache',
            '                if kind == "NAME" and val in string_cache:',
            '                    val = string_cache[val]',
            '                    kind = "STRING"',
            '                # Track paren/bracket/brace depth to suppress INDENT/NEWLINE inside',
            '                if kind in ("LPAREN", "LBRACKET", "LBRACE") or val in ("(", "[", "{"): paren_depth += 1',
            '                elif kind in ("RPAREN", "RBRACKET", "RBRACE") or val in (")", "]", "}"): paren_depth = max(0, paren_depth - 1)',
            '                out.append(Token(kind, val))',
            '            # Only emit NEWLINE when paren depth is 0 (not inside brackets/parens)',
            '            if paren_depth == 0:',
            '                out.append(Token("NEWLINE", ""))',
        ]

        if has_indent:
            L += [
                '    while len(stack) > 1:',
                '        stack.pop()',
                '        out.append(Token("DEDENT", ""))',
            ]

        L += [
            '    out.append(Token("EOF", ""))',
            '    return out',
        ]
        return '\n'.join(L)

    # ==================================================================
    # 4. Parser
    # ==================================================================

    def _parser(self) -> str:
        L = ['# ── Parser ─────────────────────────────────────────────────────────']

        # Precedence tables
        prec_lines = []
        seen: set[str] = set()
        for op in self.spec.operators:
            for sym in op.symbols:
                if _IS_PUNCT.match(sym) and sym not in seen:
                    prec_lines.append(f'    {sym!r}: {op.precedence},')
                    seen.add(sym)

        # Keyword operator precedences (from spec)
        kw_prec = {}
        for op in self.spec.operators:
            for sym in op.symbols:
                if not _IS_PUNCT.match(sym) and sym in ('and','or','not','in','is'):
                    kw_prec[sym] = op.precedence
        kw_prec_lines = [f'    {k!r}: {v},' for k, v in kw_prec.items()]

        L += [
            '_PREC    = {', '\n'.join(prec_lines) or '    # (none)', '}',
            '_KW_PREC = {', '\n'.join(kw_prec_lines) or '    # (none)', '}',
            '',
            'class Parser:',
            '    def __init__(self, tokens: list[Token]):',
            '        self._tok = tokens',
            '        self._pos = 0',
            '        self._pending_decs = []  # decorators awaiting next struct/trait',
            '',
            '    def _peek(self, offset: int = 0) -> Token:',
            '        i = self._pos + offset',
            '        return self._tok[i] if i < len(self._tok) else Token("EOF", "")',
            '',
            '    def _advance(self) -> Token:',
            '        t = self._tok[self._pos]',
            '        if self._pos < len(self._tok) - 1: self._pos += 1',
            '        return t',
            '',
            '    def _expect(self, kind: str, value: str = None) -> Token:',
            '        t = self._peek()',
            '        if t.kind != kind:',
            '            raise SyntaxError(f"Expected {kind} got {t.kind}({t.value!r})")',
            '        if value and t.value != value:',
            '            raise SyntaxError(f"Expected {value!r} got {t.value!r}")',
            '        return self._advance()',
            '',
            '    def _skip_newlines(self):',
            '        while self._peek().kind == "NEWLINE": self._advance()',
            '',
            '    def _at_end(self) -> bool: return self._peek().kind == "EOF"',
            '    def _is_kw(self, *w) -> bool:',
            '        t = self._peek(); return t.kind == "KW" and t.value in w',
            '',
        ]

        # parse_module
        L += [
            '    def parse_module(self) -> list:',
            '        stmts = []',
            '        self._skip_newlines()',
            '        while not self._at_end():',
            '            stmts.append(self._parse_stmt())',
            '            self._skip_newlines()',
            '        return stmts',
            '',
        ]

        # _parse_block
        L += [
            '    def _parse_block(self) -> list:',
            '        self._expect("NEWLINE")',
            '        self._skip_newlines()',
            '        self._expect("INDENT")',
            '        stmts = []',
            '        self._skip_newlines()',
            '        while self._peek().kind not in ("DEDENT", "EOF"):',
            '            stmts.append(self._parse_stmt())',
            '            self._skip_newlines()',
            '        self._expect("DEDENT")',
            '        return stmts',
            '',
        ]

        # _parse_stmt dispatch
        L.append('    def _parse_stmt(self):')
        L.append('        t = self._peek()')
        L.append('        if t.kind == "KW":')
        for imp in self.spec.imports:
            L.append(f'            if t.value == "import": return self._parse_import()')
            L.append(f'            if t.value == "from":   return self._parse_from_import()')
        for asgn in self.spec.assignments:
            if asgn.declaration_kw:
                L.append(f'            if t.value == {asgn.declaration_kw!r}: return self._parse_var_decl()')
        for cf in self.spec.control_flow:
            L.append(f'            if t.value == {cf.primary_kw!r}: return self._parse_{cf.kind}()')
        if self.spec.functions:
            L.append( '            if t.value in ("def", "fn"): self._advance(); return self._parse_funcdef([])')
        if self.spec.structs:
            L.append( '            if t.value in ("struct", "class"): return self._parse_struct()')
        if self.spec.traits:
            L.append( '            if t.value == "trait": return self._parse_trait()')
        for ts in self.spec.try_stmts:
            L.append( '            if t.value == "try": return self._parse_try()')
        for ws in self.spec.with_stmts:
            L.append( '            if t.value == "with": return self._parse_with()')
        for cd in self.spec.comptime:
            L.append( '            if t.value == "comptime": return self._parse_comptime()')
        for ss in self.spec.simple_stmts:
            L.append(f'            if t.value == {ss.keyword!r}: return self._parse_{ss.kind}()')
        # Handle __extension and __mlir_region declarations (special syntax forms)
        L += [
            '        # Handle __mlir_op, __mlir_attr and other MLIR/special forms',
            '        if t.kind == "NAME" and t.value.startswith("__mlir"):',
            '            self._advance()  # skip __mlir_op/__mlir_attr/etc',
            '            # Skip string literal if present',
            '            if self._peek().kind == "LPAREN":',
            '                self._advance()  # skip (',
            '                if self._peek().kind == "STRING":',
            '                    self._advance()  # skip string',
            '                self._advance()  # skip )',
            '            # Skip the rest of the line (result type annotation, etc)',
            '            while self._peek().kind not in ("NEWLINE", "DEDENT", "EOF"):',
            '                self._advance()',
            '            return PassStmt()',
            '        # Handle __extension Type: methods and __mlir_region name(...): body',
            '        if t.kind == "NAME" and t.value in ("__extension", "__mlir_region"):',
            '            self._advance()  # skip __extension or __mlir_region',
            '            name = self._expect("NAME").value',
            '            # Skip any function call arguments if present',
            '            if self._peek().kind == "LPAREN":',
            '                self._advance()  # (',
            '                depth = 1',
            '                while depth > 0:',
            '                    t_inner = self._advance()',
            '                    if t_inner.kind == "LPAREN": depth += 1',
            '                    elif t_inner.kind == "RPAREN": depth -= 1',
            '            self._expect("COLON")',
            '            # Check if there is a body on this line or on following lines',
            '            if self._peek().kind == "NEWLINE":',
            '                # Indented block follows',
            '                body = self._parse_block()',
            '            else:',
            '                # Body on same line, skip until newline',
            '                while self._peek().kind not in ("NEWLINE", "DEDENT", "EOF"):',
            '                    self._advance()',
            '            # Treat as a pass statement',
            '            return PassStmt()',
        ]
        if self.spec.functions:
            L += ['        if t.kind == "OP" and t.value == "@":',
                  '            decs = []',
                  '            while self._peek().kind == "OP" and self._peek().value == "@":',
                  '                self._advance()',
                  '                dec_name = self._expect("NAME").value',
                  '                # Handle decorator with arguments: @decorator(args)',
                  '                if self._peek().kind == "LPAREN":',
                  '                    self._advance()  # skip LPAREN',
                  '                    depth = 1',
                  '                    while depth > 0:',
                  '                        t = self._peek()',
                  '                        if t.kind == "LPAREN": depth += 1',
                  '                        elif t.kind == "RPAREN": depth -= 1',
                  '                        self._advance()',
                  '                decs.append(dec_name)',
                  '                self._skip_newlines()',
                  '            kw = self._peek()',
                  '            if kw.kind == "KW" and kw.value == "struct":',
                  '                self._pending_decs = decs',
                  '                return self._parse_struct()',
                  '            if kw.kind == "KW" and kw.value in ("def", "fn"):',
                  '                self._advance()',
                  '                return self._parse_funcdef(decs)',
                  '            self._expect("KW", "def or fn")',
                  '            return self._parse_funcdef(decs)']
        L += [
            '        expr = self._parse_expr(0)',
            '        # Check for tuple unpacking in assignment (a, b = ...)',
            '        if self._peek().kind == "COMMA":',
            '            targets = [expr]',
            '            while self._peek().kind == "COMMA":',
            '                self._advance()',
            '                if self._peek().kind == "ASSIGN": break',
            '                targets.append(self._parse_expr(0))',
            '            # Check if this is actually an assignment',
            '            if self._peek().kind == "ASSIGN":',
            '                self._advance()',
            '                val = self._parse_expr(0)',
            '                tuple_target = TupleExpr(elements=targets)',
            '                return AssignStmt(target=tuple_target, value=val)',
            '            # Not an assignment, treat as expression statement with comma operator',
            '            return ExprStmt(TupleExpr(elements=targets))',
            '        # Assignment / augmented assignment',
            '        if self._peek().kind == "ASSIGN":',
            '            self._advance()',
            '            val = self._parse_expr(0)',
            '            if self._peek().kind == "ASSIGN":',
            '                targets = [expr]',
            '                while True:',
            '                    if self._peek().kind != "ASSIGN": break',
            '                    targets.append(val)',
            '                    self._advance()',
            '                    val = self._parse_expr(0)',
            '                return MultiAssignStmt(targets=targets, value=val)',
            '            return AssignStmt(target=expr, value=val)',
            '        if self._peek().kind == "AUGASSIGN":',
            '            op = self._advance().value',
            '            val = self._parse_expr(0)',
            '            return AugAssignStmt(target=expr, op=op, value=val)',
            '        self._skip_newlines()',
            '        return ExprStmt(expr)',
            '',
        ]

        # ── Import ───────────────────────────────────────────────────
        if self.spec.imports:
            L += [
                '    def _parse_import(self):',
                '        self._expect("KW", "import")',
                '        module = self._expect("NAME").value',
                '        while self._peek().kind == "DOT":',
                '            self._advance()',
                '            module += "." + self._expect("NAME").value',
                '        alias = None',
                '        if self._is_kw("as"):',
                '            self._advance(); alias = self._expect("NAME").value',
                '        return ImportStmt(module=module, alias=alias)',
                '',
                '    def _parse_from_import(self):',
                '        self._expect("KW", "from")',
                '        # Handle relative imports: from . or from .. or from .module',
                '        module = ""',
                '        while self._peek().kind == "DOT":',
                '            self._advance()',
                '            module += "."',
                '        # If not just dots, parse the module name',
                '        if self._peek().kind == "NAME":',
                '            module += self._advance().value',
                '            while self._peek().kind == "DOT":',
                '                self._advance()',
                '                module += "." + self._expect("NAME").value',
                '        elif not module:',
                '            # No dots and no name: error',
                '            self._expect("NAME")  # Will raise error',
                '        self._expect("KW", "import")',
                '        if self._peek().kind == "OP" and self._peek().value == "*":',
                '            self._advance()',
                '            return FromImportStmt(module=module, names=[], wildcard=True)',
                '        # Handle parenthesized multi-line imports: from x import (a, b, c)',
                '        paren_import = False',
                '        if self._peek().kind == "LPAREN":',
                '            self._advance()',
                '            paren_import = True',
                '        names = []',
                '        # Parse first name, skipping any leading newlines in parenthesized imports',
                '        if paren_import:',
                '            while self._peek().kind == "NEWLINE": self._advance()',
                '        if self._peek().kind == "RPAREN":',
                '            # Empty parens: from x import ()',
                '            self._advance()',
                '            return FromImportStmt(module=module, names=names, wildcard=False)',
                '        name = self._expect("NAME").value',
                '        alias = None',
                '        if self._is_kw("as"):',
                '            self._advance(); alias = self._expect("NAME").value',
                '        names.append((name, alias))',
                '        # Parse remaining names',
                '        while True:',
                '            if paren_import:',
                '                while self._peek().kind == "NEWLINE": self._advance()',
                '            if self._peek().kind == "RPAREN":',
                '                self._advance()',
                '                break',
                '            if self._peek().kind != "COMMA":',
                '                break',
                '            self._advance()',
                '            if paren_import:',
                '                while self._peek().kind == "NEWLINE": self._advance()',
                '            if self._peek().kind == "RPAREN":',
                '                self._advance()',
                '                break',
                '            name = self._expect("NAME").value',
                '            alias = None',
                '            if self._is_kw("as"):',
                '                self._advance(); alias = self._expect("NAME").value',
                '            names.append((name, alias))',
                '        return FromImportStmt(module=module, names=names, wildcard=False)',
                '',
            ]

        # ── Var declaration ──────────────────────────────────────────
        for asgn in self.spec.assignments:
            if asgn.declaration_kw:
                kw = asgn.declaration_kw
                L += [
                    f'    def _parse_var_decl(self):',
                    f'        self._expect("KW", {kw!r})',
                    '        name = self._expect("NAME").value',
                    '        # Check for tuple unpacking (var a, b, c = ...)',
                    '        if self._peek().kind == "COMMA":',
                    '            names = [name]',
                    '            while self._peek().kind == "COMMA":',
                    '                self._advance()',
                    '                if self._peek().kind == "NAME":',
                    '                    names.append(self._expect("NAME").value)',
                    '                elif self._peek().kind == "ASSIGN": break',
                    '                else: break',
                    '            # Tuple unpacking: create as single VarDecl with tuple name',
                    '            if self._peek().kind == "ASSIGN":',
                    '                self._advance()',
                    '                value = self._parse_expr(0)',
                    '                return VarDecl(name=",".join(names), type_ann=None, value=value)',
                    '            else:',
                    '                # No assignment, treat as error or incomplete',
                    '                return VarDecl(name=",".join(names), type_ann=None, value=None)',
                    '        type_ann = None',
                    '        if self._peek().kind == "COLON":',
                    '            self._advance()',
                    '            type_ann = self._parse_type_ann()',
                    '        value = None',
                    '        if self._peek().kind == "ASSIGN":',
                    '            self._advance(); value = self._parse_expr(0)',
                    '        return VarDecl(name=name, type_ann=type_ann, value=value)',
                    '',
                ]
            break

        # ── Control flow ─────────────────────────────────────────────
        for cf in self.spec.control_flow:
            if cf.kind == 'if':    L.extend(self._gen_parse_if(cf))
            elif cf.kind == 'while': L.extend(self._gen_parse_while(cf))
            elif cf.kind == 'for':   L.extend(self._gen_parse_for(cf))

        # ── Function ─────────────────────────────────────────────────
        if self.spec.functions:
            L.extend(self._gen_parse_funcdef())

        # ── Struct / trait ───────────────────────────────────────────
        if self.spec.structs:
            L.extend(self._gen_parse_struct())
        if self.spec.traits:
            L.extend(self._gen_parse_trait())

        # ── Try / with / comptime ────────────────────────────────────
        for ts in self.spec.try_stmts: L.extend(self._gen_parse_try(ts))
        for ws in self.spec.with_stmts: L.extend(self._gen_parse_with(ws))
        for cd in self.spec.comptime:   L.extend(self._gen_parse_comptime(cd))

        # ── Simple stmts ─────────────────────────────────────────────
        for ss in self.spec.simple_stmts:
            L.extend(self._gen_parse_simple(ss))

        # ── Expression parser ─────────────────────────────────────────
        L += [
            '    # ── Expressions ──────────────────────────────────────────────────',
            '    def _parse_expr(self, min_prec: int):',
            '        left = self._parse_unary()',
            '        while True:',
            '            t = self._peek()',
            '            if t.kind == "OP":',
            '                prec = _PREC.get(t.value, -1)',
            '                if prec < min_prec: break',
            '                op = self._advance().value',
            '                right = self._parse_expr(prec + 1)',
        ]
        if 'walrus' in self._expr_kinds:
            L += [
                '                if op == ":=" and isinstance(left, IdentExpr):',
                '                    left = WalrusExpr(name=left.name, value=right)',
                '                else:',
                '                    left = BinaryOp(op=op, left=left, right=right)',
            ]
        else:
            L += [
                '                left = BinaryOp(op=op, left=left, right=right)',
            ]
        L += [
            '            elif t.kind == "KW" and t.value in _KW_PREC:',
            '                prec = _KW_PREC[t.value]',
            '                if prec < min_prec: break',
            '                op = self._advance().value',
            '                if op == "not" and self._is_kw("in"):',
            '                    self._advance(); op = "not in"',
            '                elif op == "is" and self._is_kw("not"):',
            '                    self._advance(); op = "is not"',
            '                right = self._parse_expr(prec + 1)',
            '                left = BinaryOp(op=op, left=left, right=right)',
        ]
        if 'ternary' in self._expr_kinds:
            L += [
                '            elif t.kind == "KW" and t.value == "if" and min_prec == 0:',
                '                self._advance()',
                '                cond = self._parse_expr(1)',
                '                self._expect("KW", "else")',
                '                els = self._parse_expr(0)',
                '                left = TernaryExpr(condition=cond, then_val=left, else_val=els)',
            ]
        L += [
            '            else:',
            '                break',
            '        return left',
            '',
            '    def _parse_unary(self):',
            '        t = self._peek()',
            '        if t.kind == "OP" and t.value in ("-", "+", "~"):',
            '            self._advance()',
            '            return UnaryOp(op=t.value, operand=self._parse_unary())',
            '        if t.kind == "KW" and t.value == "not":',
            '            self._advance()',
            '            return UnaryOp(op="not", operand=self._parse_unary())',
            '        return self._parse_postfix()',
            '',
            '    def _parse_postfix(self):',
            '        expr = self._parse_primary()',
            '        while True:',
            '            t = self._peek()',
            '            if t.kind == "DOT":',
            '                self._advance()',
            '                # Member can be a NAME (including KW like mut, ref) or a backtick-quoted type',
            '                if self._peek().kind == "STRING" and self._peek().value.startswith("`"):',
            '                    member = self._advance().value',
            '                elif self._peek().kind in ("NAME", "KW"):',
            '                    member = self._advance().value',
            '                else:',
            '                    member = self._expect("NAME").value  # error for invalid syntax',
            '                expr = MemberExpr(obj=expr, member=member)',
            '            elif t.kind == "LBRACKET":',
            '                self._advance()',
            '                # Check for empty subscript [] (dereference/special case)',
            '                if self._peek().kind == "RBRACKET":',
            '                    idx = IntLiteral(value="0")  # dummy index for empty subscript',
            '                    self._advance()  # consume RBRACKET',
            '                    expr = SubscriptExpr(obj=expr, index=idx)',
            '                else:',
            '                    # Parse first index/argument',
            '                    # Check for unpacking: *expr',
            '                    if self._peek().kind == "OP" and self._peek().value == "*":',
            '                        self._advance()  # skip *',
            '                        self._parse_expr(0)  # parse and discard unpacked value',
            '                        # Continue parsing remaining arguments',
            '                        while self._peek().kind == "COMMA":',
            '                            self._advance()',
            '                            if self._peek().kind == "RBRACKET": break',
            '                            # Skip remaining arguments/keywords',
            '                            if self._peek().kind == "OP" and self._peek().value == "*":',
            '                                self._advance()',
            '                                self._parse_expr(0)',
            '                            elif self._peek().kind in ("NAME", "KW") and self._peek(1).kind == "ASSIGN":',
            '                                self._advance()  # skip name',
            '                                self._advance()  # skip =',
            '                                self._parse_expr(0)',
            '                            else:',
            '                                self._parse_expr(0)',
            '                            if self._peek().kind != "COMMA" and self._peek().kind != "RBRACKET": break',
            '                        self._expect("RBRACKET")',
            '                        expr = SubscriptExpr(obj=expr, index=IntLiteral(value="0"))',
            '                    # Check if this is a keyword-style bracket (func=value, attr=value)',
            '                    elif self._peek().kind in ("NAME", "KW") and self._peek(1).kind == "ASSIGN":',
            '                        # Keyword arguments only',
            '                        while self._peek().kind != "RBRACKET" and self._peek().kind != "EOF":',
            '                            if self._peek().kind in ("NAME", "KW"):',
            '                                self._advance()  # skip name',
            '                                if self._peek().kind == "ASSIGN": self._advance()  # skip =',
            '                                self._parse_expr(0)  # parse and discard value',
            '                            if self._peek().kind == "COMMA": self._advance()',
            '                            elif self._peek().kind != "RBRACKET": break',
            '                        self._expect("RBRACKET")',
            '                        expr = SubscriptExpr(obj=expr, index=IntLiteral(value="0"))',
            '                    else:',
            '                        # Parse positional index',
            '                        idx = self._parse_expr(0)',
            '                        # Check for multiple indices or keywords',
            '                        if self._peek().kind == "COMMA":',
            '                            indices = [idx]',
            '                            while self._peek().kind == "COMMA":',
            '                                self._advance()',
            '                                if self._peek().kind == "RBRACKET": break',
            '                                # Check if next element is keyword argument (NAME = ...)',
            '                                # Check for unpacking (*expr)',
            '                                if self._peek().kind == "OP" and self._peek().value == "*":',
            '                                    self._advance()',
            '                                    indices.append(self._parse_expr(0))',
            '                                # Check if keyword argument',
            '                                elif self._peek().kind in ("NAME", "KW") and self._peek(1).kind == "ASSIGN":',
            '                                    # Skip remaining keyword arguments',
            '                                    while self._peek().kind != "RBRACKET" and self._peek().kind != "EOF":',
            '                                        if self._peek().kind in ("NAME", "KW"):',
            '                                            self._advance()  # skip name',
            '                                            if self._peek().kind == "ASSIGN": self._advance()  # skip =',
            '                                            self._parse_expr(0)  # parse and discard value',
            '                                        if self._peek().kind == "COMMA": self._advance()',
            '                                        elif self._peek().kind != "RBRACKET": break',
            '                                    break',
            '                                else:',
            '                                    indices.append(self._parse_expr(0))',
            '                            idx = TupleExpr(elements=indices)',
            '                        # Check for slice notation',
            '                        if self._peek().kind == "COLON":',
            '                            self._advance()',
            '                            stop = None if self._peek().kind == "RBRACKET" else self._parse_expr(0)',
            '                            expr = SliceExpr(obj=expr, start=idx, stop=stop)',
            '                        else:',
            '                            expr = SubscriptExpr(obj=expr, index=idx)',
            '                        self._expect("RBRACKET")',
            '            elif t.kind == "LPAREN":',
            '                self._advance()',
            '                args = []',
            '                while self._peek().kind != "RPAREN":',
            '                    # Handle dictionary unpacking (**expr)',
            '                    if self._peek().kind == "OP" and self._peek().value == "**":',
            '                        self._advance()  # skip **',
            '                        args.append(self._parse_expr(0))  # parse unpacked kwargs',
            '                    # Handle unpacking (*expr)',
            '                    elif self._peek().kind == "OP" and self._peek().value == "*":',
            '                        self._advance()  # skip *',
            '                        args.append(self._parse_expr(0))  # parse unpacked value',
            '                    # Handle keyword arguments (name=value)',
            '                    elif self._peek().kind == "NAME" and self._peek(1).kind == "ASSIGN":',
            '                        self._advance()  # skip keyword name',
            '                        self._advance()  # skip =',
            '                        args.append(self._parse_expr(0))  # parse and keep value',
            '                    else:',
            '                        args.append(self._parse_expr(0))',
            '                    if self._peek().kind == "COMMA": self._advance()',
            '                self._expect("RPAREN")',
            '                expr = CallExpr(func=expr, args=args)',
            '            elif t.kind == "OP" and t.value == "^":',
            '                # Check if ^ is postfix (ownership transfer) or binary (XOR)',
            '                # Postfix: followed by statement-ending token',
            '                # Binary: followed by expression start token',
            '                next_t = self._peek(1)',
            '                is_postfix = next_t.kind in ("NEWLINE", "DEDENT", "EOF", "COMMA", "RPAREN", "RBRACKET", "COLON", "SEMICOLON")',
            '                if is_postfix:',
            '                    self._advance()',
            '                    expr = UnaryOp(op="^", operand=expr)',
            '                else:',
            '                    break  # Let binary operator precedence handle it',
            '            else:',
            '                break',
            '        return expr',
            '',
            '    def _parse_primary(self):',
            '        t = self._peek()',
        ]

        # Literal cases
        for lit in self.spec.literals:
            cls = _lit_cls(lit.kind)
            if lit.kind == 'integer':
                L += ['        if t.kind == "INT":',
                      '            self._advance(); return IntLiteral(int(t.value, 0))']
            elif lit.kind == 'float':
                L += ['        if t.kind == "FLOAT":',
                      '            self._advance(); return FloatLiteral(float(t.value))']
            elif lit.kind == 'bool':
                L += ['        if t.kind == "KW" and t.value in ("True","False"):',
                      '            self._advance()',
                      '            return BoolLiteral(t.value == "True")']
            elif lit.kind == 'none':
                L += ['        if t.kind == "KW" and t.value == "None":',
                      '            self._advance(); return NoneLiteral()']
            elif lit.kind == 'self':
                L += ['        if t.kind == "KW" and t.value == "Self":',
                      '            self._advance(); return SelfLiteral()']

        L += ['        if t.kind == "STRING":',
              '            val = self._advance().value',
              '            # Handle implicit string concatenation (adjacent strings)',
              '            while self._peek().kind == "STRING":',
              '                val += self._advance().value',
              '            return StringLiteral(val)']

        # Collection literals
        if 'list' in self._expr_kinds or 'comprehension_list' in self._expr_kinds:
            L += ['        if t.kind == "LBRACKET": return self._parse_list_or_compr()']
        if 'dict' in self._expr_kinds or 'set' in self._expr_kinds:
            L += ['        if t.kind == "LBRACE": return self._parse_dict_or_set()']

        L += [
            '        if t.kind == "LPAREN":',
            '            self._advance()',
            '            if self._peek().kind == "RPAREN":',
            '                self._advance(); return TupleExpr(elements=[])',
            '            first = self._parse_expr(0)',
            '            if self._peek().kind == "COMMA":',
            '                elems = [first]',
            '                while self._peek().kind == "COMMA":',
            '                    self._advance()',
            '                    if self._peek().kind == "RPAREN": break',
            '                    elems.append(self._parse_expr(0))',
            '                self._expect("RPAREN")',
            '                return TupleExpr(elements=elems)',
            '            self._expect("RPAREN")',
            '            return first',
            '        if t.kind in ("NAME", "KW"):',
            '            self._advance()',
            '            return IdentExpr(t.value)',
            '        if t.kind == "DOT" and self._peek(1).kind == "DOT" and self._peek(2).kind == "DOT":',
            '            self._advance(); self._advance(); self._advance()',
            '            return EllipsisLiteral()',
            '        raise SyntaxError(f"Unexpected {t.kind}({t.value!r})")',
        ]

        # Collection parse helpers
        if 'list' in self._expr_kinds or 'comprehension_list' in self._expr_kinds:
            L += [
                '',
                '    def _parse_list_or_compr(self):',
                '        self._expect("LBRACKET")',
                '        if self._peek().kind == "RBRACKET":',
                '            self._advance(); return ListExpr(elements=[])',
                '        first = self._parse_expr(0)',
                '        if self._is_kw("for"):',
                '            gen = self._parse_generator()',
                '            self._expect("RBRACKET")',
                '            return Comprehension(kind="list", element=first, generators=[gen])',
                '        elems = [first]',
                '        while self._peek().kind == "COMMA":',
                '            self._advance()',
                '            if self._peek().kind == "RBRACKET": break',
                '            elems.append(self._parse_expr(0))',
                '        self._expect("RBRACKET")',
                '        return ListExpr(elements=elems)',
            ]

        if 'dict' in self._expr_kinds or 'set' in self._expr_kinds:
            L += [
                '',
                '    def _parse_dict_or_set(self):',
                '        self._expect("LBRACE")',
                '        if self._peek().kind == "RBRACE":',
                '            self._advance(); return DictExpr(pairs=[])',
                '        first = self._parse_expr(0)',
                '        # Check for struct initializer syntax: {field = value, ...}',
                '        if self._peek().kind == "ASSIGN":',
                '            # This is a struct initializer with named fields',
                '            self._advance()  # skip =',
                '            self._parse_expr(0)  # parse and discard field value',
                '            # Skip any remaining fields',
                '            while self._peek().kind == "COMMA":',
                '                self._advance()',
                '                if self._peek().kind == "RBRACE": break',
                '                self._parse_expr(0)  # skip field name',
                '                if self._peek().kind == "ASSIGN": self._advance()',
                '                self._parse_expr(0)  # skip field value',
                '            self._expect("RBRACE")',
                '            # Return as dict for now (struct init not semantically tracked)',
                '            return DictExpr(pairs=[])',
                '        if self._peek().kind == "COLON":',
                '            self._advance(); val = self._parse_expr(0)',
                '            if self._is_kw("for"):',
                '                gen = self._parse_generator()',
                '                self._expect("RBRACE")',
                '                return Comprehension(kind="dict", element=first, key=val, generators=[gen])',
                '            pairs = [(first, val)]',
                '            while self._peek().kind == "COMMA":',
                '                self._advance()',
                '                if self._peek().kind == "RBRACE": break',
                '                k = self._parse_expr(0); self._expect("COLON"); v = self._parse_expr(0)',
                '                pairs.append((k, v))',
                '            self._expect("RBRACE")',
                '            return DictExpr(pairs=pairs)',
                '        if self._is_kw("for"):',
                '            gen = self._parse_generator()',
                '            self._expect("RBRACE")',
                '            return Comprehension(kind="set", element=first, generators=[gen])',
                '        elems = [first]',
                '        while self._peek().kind == "COMMA":',
                '            self._advance()',
                '            if self._peek().kind == "RBRACE": break',
                '            elems.append(self._parse_expr(0))',
                '        self._expect("RBRACE")',
                '        return SetExpr(elements=elems)',
            ]

        if any(k.startswith('comprehension') for k in self._expr_kinds):
            L += [
                '',
                '    def _parse_generator(self):',
                '        self._expect("KW", "for")',
                '        target = self._expect("NAME").value',
                '        self._expect("KW", "in")',
                '        iterable = self._parse_expr(1)',
                '        conditions = []',
                '        while self._is_kw("if"):',
                '            self._advance(); conditions.append(self._parse_expr(1))',
                '        return Generator(target=target, iterable=iterable, conditions=conditions)',
            ]

        # _parse_type_ann and _skip_bracketed helpers
        L += [
            '',
            '    def _skip_bracketed(self):',
            '        """Consume a balanced [...] block."""',
            '        self._expect("LBRACKET")',
            '        depth = 1',
            '        while depth > 0:',
            '            t = self._advance()',
            '            if t.kind == "LBRACKET": depth += 1',
            '            elif t.kind == "RBRACKET": depth -= 1',
            '            elif t.kind == "EOF": break',
            '',
            '    def _parse_type_ann(self) -> str:',
            '        """Parse a type annotation: Name or Name[TypeArgs] or Name.Member.Type[Args] or `backtick_type`."""',
            '        # Handle * prefix for variadic/unpacking types (*Ts)',
            '        prefix = ""',
            '        if self._peek().kind == "OP" and self._peek().value == "*":',
            '            prefix = "*"',
            '            self._advance()',
            '        # Handle `ref` or `mut` keyword prefix on type (lifetime annotation)',
            '        if self._is_kw("ref") or self._is_kw("mut"):',
            '            self._advance()  # drop ref/mut prefix',
            '            # Skip lifetime parameters in brackets: ref[Origin]',
            '            if self._peek().kind == "LBRACKET":',
            '                self._skip_bracketed()',
            '        # Handle backtick-quoted MLIR types (e.g., `!pop.scalar<bool>`)',
            '        if self._peek().kind == "STRING" and self._peek().value.startswith("`"):',
            '            return prefix + self._advance().value  # return the backtick string as-is',
            '        # Handle parenthesized types like () for unit type',
            '        if self._peek().kind == "LPAREN":',
            '            name = prefix + "("',
            '            self._advance()',
            '            depth = 1',
            '            while depth > 0:',
            '                t = self._advance()',
            '                if t.kind == "LPAREN": depth += 1; name += "("',
            '                elif t.kind == "RPAREN":',
            '                    depth -= 1',
            '                    if depth > 0: name += ")"',
            '                elif t.kind == "EOF": break',
            '                else: name += t.value',
            '            name += ")"',
            '            return name',
            '        name = prefix + self._expect("NAME").value',
            '        # Support dotted type names like __mlir_type.i1 or __mlir_type.`backtick_type`',
            '        while self._peek().kind == "DOT":',
            '            self._advance()  # consume dot',
            '            # Next part can be a NAME (including KW like mut, ref) or a backtick-quoted type',
            '            if self._peek().kind == "STRING" and self._peek().value.startswith("`"):',
            '                name += "." + self._advance().value',
            '            elif self._peek().kind in ("NAME", "KW"):',
            '                name += "." + self._advance().value',
            '            else:',
            '                name += "." + self._expect("NAME").value  # error for invalid syntax',
            '        # Handle function call types like type_of(x)',
            '        if self._peek().kind == "LPAREN":',
            '            self._advance()  # (',
            '            name += "("',
            '            depth = 1',
            '            while depth > 0:',
            '                t = self._advance()',
            '                if t.kind == "LPAREN": depth += 1; name += "("',
            '                elif t.kind == "RPAREN":',
            '                    depth -= 1',
            '                    if depth > 0: name += ")"',
            '                elif t.kind == "EOF": break',
            '                else: name += t.value',
            '            name += ")"',
            '            # Do NOT return here; check for dotted names and subscripts after the call',
            '            # Second dotted-name loop after function call',
            '            while self._peek().kind == "DOT":',
            '                self._advance()  # consume dot',
            '                # Next part can be a NAME or a backtick-quoted type',
            '                if self._peek().kind == "STRING" and self._peek().value.startswith("`"):',
            '                    name += "." + self._advance().value',
            '                else:',
            '                    name += "." + self._expect("NAME").value',
            '        if self._peek().kind != "LBRACKET": return name',
            '        # Consume [TypeArgs] and any chained subscripts — build a string representation',
            '        parts = [name]',
            '        while self._peek().kind == "LBRACKET":',
            '            self._advance()  # [',
            '            parts.append("[")',
            '            depth = 1',
            '            while depth > 0:',
            '                t = self._advance()',
            '                if t.kind == "LBRACKET": depth += 1; parts.append("[")',
            '                elif t.kind == "RBRACKET":',
            '                    depth -= 1',
            '                    if depth > 0: parts.append("]")',
            '                elif t.kind == "EOF": break',
            '                else: parts.append(t.value)',
            '            parts.append("]")',
            '        return "".join(parts)',
        ]

        return '\n'.join(L)

    # ------------------------------------------------------------------
    # Parser sub-generators
    # ------------------------------------------------------------------

    def _gen_parse_if(self, cf):
        L = [
            '    def _parse_if(self):',
            '        self._expect("KW", "if")',
            '        cond = self._parse_expr(0)',
            '        self._expect("COLON")',
            '        body = self._parse_block()',
            '        elifs, else_body = [], None',
        ]
        if 'elif' in cf.alt_kws:
            L += ['        while self._is_kw("elif"):',
                  '            self._advance(); ec = self._parse_expr(0)',
                  '            self._expect("COLON"); eb = self._parse_block()',
                  '            elifs.append((ec, eb))']
        if 'else' in cf.alt_kws:
            L += ['        if self._is_kw("else"):',
                  '            self._advance(); self._expect("COLON")',
                  '            else_body = self._parse_block()']
        L += ['        return IfStmt(condition=cond, then_body=body, elifs=elifs, else_body=else_body)', '']
        return L

    def _gen_parse_while(self, cf):
        has_else = 'else' in cf.alt_kws
        L = [
            '    def _parse_while(self):',
            '        self._expect("KW", "while")',
            '        cond = self._parse_expr(0)',
            '        self._expect("COLON")',
            '        body = self._parse_block()',
        ]
        if has_else:
            L += ['        else_body = None',
                  '        if self._is_kw("else"):',
                  '            self._advance(); self._expect("COLON")',
                  '            else_body = self._parse_block()',
                  '        return WhileStmt(condition=cond, body=body, else_body=else_body)']
        else:
            L.append('        return WhileStmt(condition=cond, body=body)')
        L.append('')
        return L

    def _gen_parse_for(self, cf):
        has_else = 'else' in cf.alt_kws
        L = [
            '    def _parse_for(self):',
            '        self._expect("KW", "for")',
            '        # Skip optional convention keyword (var, ref, mut, etc.)',
            '        if self._is_kw(*self._CONV_KWS):',
            '            self._advance()',
            '        target = self._expect("NAME").value',
            '        self._expect("KW", "in")',
            '        iterable = self._parse_expr(0)',
            '        self._expect("COLON")',
            '        body = self._parse_block()',
        ]
        if has_else:
            L += ['        else_body = None',
                  '        if self._is_kw("else"):',
                  '            self._advance(); self._expect("COLON")',
                  '            else_body = self._parse_block()',
                  '        return ForStmt(target=target, iterable=iterable, body=body, else_body=else_body)']
        else:
            L.append('        return ForStmt(target=target, iterable=iterable, body=body)')
        L.append('')
        return L

    def _gen_parse_funcdef(self):
        _CONV_KWS = repr({'read', 'mut', 'var', 'ref', 'out', 'deinit'})
        return [
            '    # Ownership/convention keywords preserved in param_convs',
            f'    _CONV_KWS = {_CONV_KWS}',
            '    def _parse_funcdef(self, decorators=None):',
            '        if decorators is None: decorators = []',
            '        name = self._expect("NAME").value',
            '        # Skip generic type-param block [T: Trait, count: Int, //]',
            '        if self._peek().kind == "LBRACKET": self._skip_bracketed()',
            '        self._expect("LPAREN")',
            '        params = []',
            '        param_convs = {}',
            '        while self._peek().kind != "RPAREN":',
            '            # Skip newlines and indentation within parameter list',
            '            while self._peek().kind in ("NEWLINE", "INDENT", "DEDENT"):',
            '                self._advance()',
            '            if self._peek().kind == "RPAREN": break',
            '            # Capture last argument-convention prefix (read/mut/var/ref/out/deinit)',
            '            conv = None',
            '            while self._peek().kind == "KW" and self._peek().value in self._CONV_KWS:',
            '                conv = self._advance().value',
            '            # Skip positional-only parameter separator /',
            '            if self._peek().kind == "OP" and self._peek().value == "/":',
            '                self._advance()',
            '                if self._peek().kind == "COMMA": self._advance()',
            '                if self._peek().kind == "RPAREN": break',
            '            # Handle * (keyword-only separator or variadic parameter)',
            '            if self._peek().kind == "OP" and self._peek().value == "*":',
            '                self._advance()',
            '                # Skip lifetime parameters if present after *',
            '                if self._peek().kind == "LBRACKET": self._skip_bracketed()',
            '                # Handle convention keywords after * (e.g., *, var x: Int)',
            '                while self._peek().kind == "KW" and self._peek().value in self._CONV_KWS:',
            '                    conv = self._advance().value',
            '                # If followed by NAME, it\'s a variadic parameter (*args) or keyword-only param',
            '                if self._peek().kind == "NAME":',
            '                    pname = self._expect("NAME").value',
            '                    ptype = None',
            '                    if self._peek().kind == "COLON":',
            '                        self._advance(); ptype = self._parse_type_ann()',
            '                    if self._peek().kind == "ASSIGN":',
            '                        self._advance(); self._parse_expr(0)',
            '                    params.append((pname, ptype))',
            '                    if conv is not None: param_convs[pname] = conv',
            '                    if self._peek().kind == "COMMA": self._advance()',
            '                    while self._peek().kind in ("NEWLINE", "INDENT", "DEDENT"):',
            '                        self._advance()',
            '                    continue',
            '                # Otherwise it\'s a separator: skip following comma and check for end',
            '                elif self._peek().kind == "COMMA": self._advance()',
            '                if self._peek().kind == "RPAREN": break',
            '                # Continue to next parameter (convention keywords might follow)',
            '                continue',
            '            if self._peek().kind == "RPAREN": break',
            '            # Skip lifetime parameters in brackets: ref[origin] param_name',
            '            if self._peek().kind == "LBRACKET": self._skip_bracketed()',
            '            pname = self._expect("NAME").value',
            '            ptype = None',
            '            if self._peek().kind == "COLON":',
            '                self._advance(); ptype = self._parse_type_ann()',
            '            # skip default value =expr',
            '            if self._peek().kind == "ASSIGN":',
            '                self._advance(); self._parse_expr(0)',
            '            params.append((pname, ptype))',
            '            if conv is not None: param_convs[pname] = conv',
            '            # Skip trailing comma and newlines',
            '            if self._peek().kind == "COMMA": self._advance()',
            '            while self._peek().kind in ("NEWLINE", "INDENT", "DEDENT"):',
            '                self._advance()',
            '        self._expect("RPAREN")',
            '        # Skip optional `raises` keyword and exception types (must come before return type)',
            '        if self._is_kw("raises"):',
            '            self._advance()  # skip raises',
            '            # Skip exception type list: Type1, Type2, ... until we see -> or : or where',
            '            while self._peek().kind not in ("COLON", "NEWLINE", "EOF", "ARROW"):',
            '                if self._peek().kind in ("NAME", "DOT", "STRING", "COMMA"):',
            '                    self._advance()',
            '                elif self._peek().kind == "LBRACKET":',
            '                    self._skip_bracketed()  # Skip subscripted exception types like ExcType[Param]',
            '                else:',
            '                    break',
            '        # Skip function qualifiers (unified, register_passable, etc.)',
            '        while self._peek().kind == "NAME" and self._peek().value in ("unified", "register_passable"):',
            '            self._advance()',
            '        ret = None',
            '        if self._peek().kind == "ARROW":',
            '            self._advance()',
            '            # Drop `ref` lifetime prefix on return type and skip lifetime parameters',
            '            if self._is_kw("ref"):',
            '                self._advance()',
            '                # Skip lifetime parameters in brackets: ref[Origin]',
            '                if self._peek().kind == "LBRACKET":',
            '                    self._skip_bracketed()',
            '            ret = self._parse_type_ann()',
            '            # Skip additional qualifiers after return type',
            '            while self._peek().kind == "NAME" and self._peek().value in ("unified", "register_passable"):',
            '                self._advance()',
            '        # Skip optional `where conforms_to(...)` clause',
            '        if self._peek().kind == "NAME" and self._peek().value == "where":',
            '            self._advance()  # where',
            '            while self._peek().kind not in ("COLON", "NEWLINE", "EOF"):',
            '                self._advance()',
            '        # Skip capture lists in curly braces (for closures/lambdas)',
            '        if self._peek().kind == "LBRACE":',
            '            self._advance()  # {',
            '            depth = 1',
            '            while depth > 0:',
            '                t = self._advance()',
            '                if t.kind == "LBRACE": depth += 1',
            '                elif t.kind == "RBRACE": depth -= 1',
            '                elif t.kind == "EOF": break',
            '        self._expect("COLON")',
            '        body = self._parse_block()',
            '        return FunctionDef(name=name, params=params, return_type=ret,',
            '                           body=body, decorators=decorators,',
            '                           param_convs=param_convs)',
            '',
        ]

    def _gen_parse_try(self, ts):
        return [
            '    def _parse_try(self):',
            '        self._expect("KW", "try"); self._expect("COLON")',
            '        body = self._parse_block()',
            '        handlers = []',
            '        while self._is_kw("except"):',
            '            self._advance()',
            '            exc_type, exc_name = None, None',
            '            if self._peek().kind == "NAME":',
            '                exc_type = self._advance().value',
            '                if self._is_kw("as"):',
            '                    self._advance(); exc_name = self._expect("NAME").value',
            '            self._expect("COLON")',
            '            handlers.append(ExceptHandler(exc_type=exc_type, name=exc_name,',
            '                                           body=self._parse_block()))',
            '        else_body = None',
            '        if self._is_kw("else"):',
            '            self._advance(); self._expect("COLON"); else_body = self._parse_block()',
            '        finally_body = None',
            '        if self._is_kw("finally"):',
            '            self._advance(); self._expect("COLON"); finally_body = self._parse_block()',
            '        return TryStmt(body=body, handlers=handlers,',
            '                       else_body=else_body, finally_body=finally_body)',
            '',
        ]

    def _gen_parse_with(self, ws):
        return [
            '    def _parse_with(self):',
            '        self._expect("KW", "with")',
            '        items = []',
            '        expr = self._parse_expr(0)',
            '        alias = None',
            '        if self._is_kw("as"):',
            '            self._advance(); alias = self._expect("NAME").value',
            '        items.append(WithItem(expr=expr, alias=alias))',
            '        while self._peek().kind == "COMMA":',
            '            self._advance(); expr = self._parse_expr(0); alias = None',
            '            if self._is_kw("as"):',
            '                self._advance(); alias = self._expect("NAME").value',
            '            items.append(WithItem(expr=expr, alias=alias))',
            '        self._expect("COLON")',
            '        return WithStmt(items=items, body=self._parse_block())',
            '',
        ]

    def _gen_parse_comptime(self, cd):
        L = [
            '    def _parse_comptime(self):',
            '        self._expect("KW", "comptime")',
            '        t = self._peek()',
        ]
        if 'if'  in cd.kinds: L.append('        if t.value == "if":  return self._parse_comptime_if()')
        if 'for' in cd.kinds: L.append('        if t.value == "for": return self._parse_comptime_for()')
        L += [
            '        # comptime assert expr[, msg]',
            '        if t.value == "assert": return self._parse_assert()',
            '        # comptime NAME [TypeParams] [: Type] = expr',
            '        if t.kind == "NAME":',
            '            lhs = IdentExpr(self._advance().value)',
            '            # Skip optional type parameters: comptime Alias[T, U]: Type = ...',
            '            if self._peek().kind == "LBRACKET": self._skip_bracketed()',
            '            # Skip optional type annotation: comptime MIN: Bool = False',
            '            if self._peek().kind == "COLON":',
            '                self._advance()  # skip colon',
            '                self._parse_type_ann()  # parse and discard type annotation',
            '            if self._peek().kind == "ASSIGN":',
            '                self._advance()',
            '                return AssignStmt(target=lhs, value=self._parse_expr(0))',
            '            return ExprStmt(lhs)',
            '        raise SyntaxError(f"Unexpected token after comptime: {t.value!r}")',
            '',
        ]
        if 'if' in cd.kinds:
            L += ['    def _parse_comptime_if(self):',
                  '        self._expect("KW","if"); cond=self._parse_expr(0)',
                  '        self._expect("COLON"); body=self._parse_block()',
                  '        elifs, else_body = [], None',
                  '        while self._is_kw("elif"):',
                  '            self._advance(); ec = self._parse_expr(0)',
                  '            self._expect("COLON"); eb = self._parse_block()',
                  '            elifs.append((ec, eb))',
                  '        if self._is_kw("else"):',
                  '            self._advance();self._expect("COLON");else_body=self._parse_block()',
                  '        return ComptimeIfStmt(condition=cond,then_body=body,elifs=elifs,else_body=else_body)', '']
        if 'for' in cd.kinds:
            L += ['    def _parse_comptime_for(self):',
                  '        self._expect("KW","for"); target=self._expect("NAME").value',
                  '        self._expect("KW","in"); iterable=self._parse_expr(0)',
                  '        self._expect("COLON")',
                  '        return ComptimeForStmt(target=target,iterable=iterable,body=self._parse_block())', '']
        return L

    def _gen_parse_simple(self, ss):
        cls = ss.kind.title() + 'Stmt'
        L = [f'    def _parse_{ss.kind}(self):',
             f'        self._expect("KW", {ss.keyword!r})']
        if ss.has_value and ss.optional:
            L += ['        if self._peek().kind in ("NEWLINE","EOF","DEDENT"):',
                  f'            return {cls}(value=None)',
                  f'        return {cls}(value=self._parse_expr(0))']
        elif ss.has_value:
            if ss.kind == 'assert':
                L += ['        value = self._parse_expr(0)',
                      '        msg = None',
                      '        if self._peek().kind == "COMMA":',
                      '            self._advance(); msg = self._parse_expr(0)',
                      f'        return {cls}(value=value, msg=msg)']
            else:
                L.append(f'        return {cls}(value=self._parse_expr(0))')
        else:
            L.append(f'        return {cls}()')
        L.append('')
        return L

    def _gen_parse_struct(self):
        return [
            '    def _parse_struct(self):',
            '        # Accept both "struct" and "class" keywords',
            '        kw = self._peek()',
            '        if kw.kind == "KW" and kw.value in ("struct", "class"):',
            '            self._advance()',
            '        else:',
            '            self._expect("KW", "struct")',
            '        name = self._expect("NAME").value',
            '        # Skip generic type-param block [T: Trait, ...]',
            '        if self._peek().kind == "LBRACKET": self._skip_bracketed()',
            '        if self._peek().kind == "LPAREN":',
            '            self._advance()',
            '            # Skip balanced parentheses in trait list',
            '            depth = 1',
            '            while depth > 0:',
            '                t = self._advance()',
            '                if t.kind == "LPAREN": depth += 1',
            '                elif t.kind == "RPAREN": depth -= 1',
            '                elif t.kind == "EOF": break',
            '        self._expect("COLON")',
            '        body = self._parse_block()',
            '        fields  = [s for s in body if isinstance(s, VarDecl)]',
            '        methods = [s for s in body if isinstance(s, FunctionDef)]',
            '        decs    = getattr(self, "_pending_decs", [])',
            '        self._pending_decs = []',
            '        return StructDef(name=name, fields=fields, methods=methods, decorators=decs)',
            '',
        ]

    def _gen_parse_trait(self):
        return [
            '    def _parse_trait(self):',
            '        self._expect("KW", "trait")',
            '        name = self._expect("NAME").value',
            '        # Skip generic type-param block [T: Trait, ...]',
            '        if self._peek().kind == "LBRACKET": self._skip_bracketed()',
            '        if self._peek().kind == "LPAREN":',
            '            self._advance()',
            '            # Skip balanced parentheses in trait list',
            '            depth = 1',
            '            while depth > 0:',
            '                t = self._advance()',
            '                if t.kind == "LPAREN": depth += 1',
            '                elif t.kind == "RPAREN": depth -= 1',
            '                elif t.kind == "EOF": break',
            '        self._expect("COLON")',
            '        body = self._parse_block()',
            '        methods = [s for s in body if isinstance(s, FunctionDef)]',
            '        return TraitDef(name=name, methods=methods)',
            '',
        ]

    # ==================================================================
    # 5. Code generator
    # ==================================================================

    def _codegen(self) -> str:
        L = ['# ── Code generator ─────────────────────────────────────────────────']
        L += [
            'def emit_module(stmts: list, indent: int = 0) -> str:',
            '    return "\\n".join(emit(s, indent) for s in stmts)',
            '',
            'def emit(node, indent: int = 0) -> str:',
            '    pad = "    " * indent',
        ]

        # Literals
        for lit in self.spec.literals:
            cls = _lit_cls(lit.kind)
            if   lit.kind == 'integer': L.append(f'    if isinstance(node,{cls}): return str(node.value)')
            elif lit.kind == 'float':   L.append(f'    if isinstance(node,{cls}): return repr(node.value)')
            elif lit.kind == 'bool':    L.append(f'    if isinstance(node,{cls}): return str(node.value)')
            elif lit.kind == 'none':    L.append(f'    if isinstance(node,{cls}): return "None"')
            elif lit.kind == 'self':    L.append(f'    if isinstance(node,{cls}): return "self"')
        L.append('    if isinstance(node,StringLiteral): return node.value')
        L.append('    if isinstance(node,EllipsisLiteral): return "..."')

        # Expressions
        L.append('    if isinstance(node,IdentExpr): return node.name')
        L += ['    if isinstance(node,CallExpr):',
              '        f = emit(node.func) if not isinstance(node.func,str) else node.func',
              '        args = ", ".join(emit(a) for a in node.args)',
              '        return f"{f}({args})"']
        if self.spec.operators:
            L += ['    if isinstance(node,BinaryOp): return f"({emit(node.left)} {node.op} {emit(node.right)})"',
                  '    if isinstance(node,UnaryOp):  return f"({node.op} {emit(node.operand)})"']
        if 'ternary' in self._expr_kinds:
            L.append('    if isinstance(node,TernaryExpr): return f"({emit(node.then_val)} if {emit(node.condition)} else {emit(node.else_val)})"')
        if 'member_access' in self._expr_kinds:
            L.append('    if isinstance(node,MemberExpr): return f"{emit(node.obj)}.{node.member}"')
        if 'subscript' in self._expr_kinds or 'member_access' in self._expr_kinds:
            L += ['    if isinstance(node,SubscriptExpr): return f"{emit(node.obj)}[{emit(node.index)}]"',
                  '    if isinstance(node,SliceExpr):',
                  '        start = emit(node.start) if node.start is not None else ""',
                  '        stop  = emit(node.stop)  if node.stop  is not None else ""',
                  '        return f"{emit(node.obj)}[{start}:{stop}]"']
        if 'list' in self._expr_kinds or 'comprehension_list' in self._expr_kinds:
            L.append('    if isinstance(node,ListExpr): return "[" + ", ".join(emit(e) for e in node.elements) + "]"')
        if 'dict' in self._expr_kinds:
            L.append('    if isinstance(node,DictExpr): return "{" + ", ".join(f"{emit(k)}: {emit(v)}" for k,v in node.pairs) + "}"')
        if 'set' in self._expr_kinds:
            L.append('    if isinstance(node,SetExpr): return "{" + ", ".join(emit(e) for e in node.elements) + "}"')
        if 'tuple' in self._expr_kinds:
            L += ['    if isinstance(node,TupleExpr):',
                  '        if not node.elements: return "()"',
                  '        return "(" + ", ".join(emit(e) for e in node.elements) + ("," if len(node.elements)==1 else "") + ")"']
        if any(k.startswith('comprehension') for k in self._expr_kinds):
            L += ['    if isinstance(node,Comprehension):',
                  '        gens = " ".join(f"for {g.target} in {emit(g.iterable)}" + "".join(f" if {emit(c)}" for c in g.conditions) for g in node.generators)',
                  '        if node.kind == "list": return f"[{emit(node.element)} {gens}]"',
                  '        if node.kind == "set":  return "{" + f"{emit(node.element)} {gens}" + "}"',
                  '        if node.kind == "dict": return "{" + f"{emit(node.element)}: {emit(node.key)} {gens}" + "}"',
                  '        return f"({emit(node.element)} {gens})"']

        # Statements
        L.append('    if isinstance(node,ExprStmt): return f"{pad}{emit(node.value)}"')
        if self.spec.assignments:
            L += ['    if isinstance(node,AssignStmt): return f"{pad}{emit(node.target)} = {emit(node.value)}"',
                  '    if isinstance(node,AugAssignStmt): return f"{pad}{emit(node.target)} {node.op} {emit(node.value)}"',
                  '    if isinstance(node,VarDecl):',
                  '        ann = f": {node.type_ann}" if node.type_ann else ""',
                  '        val = f" = {emit(node.value)}" if node.value is not None else ""',
                  '        return f"{pad}{node.name}{ann}{val}"',
                  '    if isinstance(node,MultiAssignStmt):',
                  '        return f"{pad}" + " = ".join(emit(t) for t in node.targets) + " = " + emit(node.value)']
        if self.spec.imports:
            L += ['    if isinstance(node,ImportStmt):',
                  '        alias = f" as {node.alias}" if node.alias else ""',
                  '        return f"{pad}import {node.module}{alias}"',
                  '    if isinstance(node,FromImportStmt):',
                  '        if node.wildcard: return f"{pad}from {node.module} import *"',
                  '        names = ", ".join(n + (f" as {a}" if a else "") for n,a in node.names)',
                  '        return f"{pad}from {node.module} import {names}"']

        # Control flow
        for cf in self.spec.control_flow:
            if cf.kind == 'if':    L.extend(self._gen_emit_if())
            elif cf.kind == 'while': L.extend(self._gen_emit_while(cf))
            elif cf.kind == 'for':   L.extend(self._gen_emit_for(cf))

        if self.spec.functions:
            L += ['    if isinstance(node,FunctionDef):',
                  '        def _fmt_param(n,t):',
                  '            ann = f": {t}" if t else ""',
                  '            return f"{n}{ann}"  # strip Mojo arg-convention prefix for Python',
                  '        params = ", ".join(_fmt_param(n,t) for n,t in node.params)',
                  '        ret = f" -> {node.return_type}" if node.return_type else ""',
                  '        out = [f"{pad}@{d}" for d in node.decorators]',
                  '        out.append(f"{pad}def {node.name}({params}){ret}:")',
                  '        out += [emit(s,indent+1) for s in node.body]',
                  '        return "\\n".join(out)']

        for ss in self.spec.simple_stmts:
            cls = ss.kind.title() + 'Stmt'
            if ss.has_value:
                if ss.kind == 'assert':
                    L += [f'    if isinstance(node,{cls}):',
                          f'        val = f" {{emit(node.value)}}" if node.value is not None else ""',
                          f'        msg_s = f", {{emit(node.msg)}}" if node.msg is not None else ""',
                          f'        return f"{{pad}}{ss.keyword}{{val}}{{msg_s}}"']
                else:
                    L += [f'    if isinstance(node,{cls}):',
                          f'        val = f" {{emit(node.value)}}" if node.value is not None else ""',
                          f'        return f"{{pad}}{ss.keyword}{{val}}"']
            else:
                L.append(f'    if isinstance(node,{cls}): return f"{{pad}}{ss.keyword}"')

        if self.spec.try_stmts:
            L += ['    if isinstance(node,TryStmt):',
                  '        out = [f"{pad}try:"]',
                  '        out += [emit(s,indent+1) for s in node.body]',
                  '        for h in node.handlers:',
                  '            exc  = f" {h.exc_type}" if h.exc_type else ""',
                  '            name = f" as {h.name}"  if h.name    else ""',
                  '            out.append(f"{pad}except{exc}{name}:")',
                  '            out += [emit(s,indent+1) for s in h.body]',
                  '        if node.else_body:',
                  '            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]',
                  '        if node.finally_body:',
                  '            out.append(f"{pad}finally:"); out += [emit(s,indent+1) for s in node.finally_body]',
                  '        return "\\n".join(out)']

        if self.spec.with_stmts:
            L += ['    if isinstance(node,WithStmt):',
                  '        items_str = ", ".join(f"{emit(i.expr)} as {i.alias}" if i.alias else emit(i.expr) for i in node.items)',
                  '        out = [f"{pad}with {items_str}:"]',
                  '        out += [emit(s,indent+1) for s in node.body]',
                  '        return "\\n".join(out)']

        for cd in self.spec.comptime:
            if 'if' in cd.kinds:
                L += ['    if isinstance(node,ComptimeIfStmt):',
                      '        out = [f"{pad}if {emit(node.condition)}:  # comptime"]',
                      '        out += [emit(s,indent+1) for s in node.then_body]',
                      '        for (ec,eb) in node.elifs:',
                      '            out.append(f"{pad}elif {emit(ec)}:"); out += [emit(s,indent+1) for s in eb]',
                      '        if node.else_body is not None:',
                      '            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]',
                      '        return "\\n".join(out)']
            if 'for' in cd.kinds:
                L += ['    if isinstance(node,ComptimeForStmt):',
                      '        out = [f"{pad}for {node.target} in {emit(node.iterable)}:  # comptime"]',
                      '        out += [emit(s,indent+1) for s in node.body]',
                      '        return "\\n".join(out)']

        if self.spec.structs:
            L += [
                '    if isinstance(node,StructDef):',
                '        _OWN_DECS = {"Copyable","Movable","ImplicitlyCopyable","ExplicitlyCopyable",',
                '                     "Writable","Sized","Boolable","Stringable","Hashable","AnyType"}',
                '        has_init = any(d == "fieldwise_init" for d in node.decorators)',
                '        ext_decs = [d for d in node.decorators if d not in _OWN_DECS and d != "fieldwise_init"]',
                '        out = [f"{pad}@{d}" for d in ext_decs]',
                '        out.append(f"{pad}class {node.name}:")',
                '        body = []',
                '        if has_init and node.fields:',
                '            ps = ", ".join(f.name for f in node.fields)',
                '            body.append(f"{pad}    def __init__(self, {ps}):")',
                '            for f in node.fields:',
                '                body.append(f"{pad}        self.{f.name} = {f.name}")',
                '        elif node.fields:',
                '            for f in node.fields:',
                '                ann = f": {f.type_ann}" if f.type_ann else ""',
                '                val = f" = {emit(f.value)}" if f.value is not None else " = None"',
                '                body.append(f"{pad}    {f.name}{ann}{val}")',
                '        for m in node.methods:',
                '            body.append(emit(m,indent+1))',
                '        out += body if body else [f"{pad}    pass"]',
                '        return "\\n".join(out)',
            ]
        if self.spec.traits:
            L += [
                '    if isinstance(node,TraitDef):',
                '        out = [f"{pad}class {node.name}:  # trait"]',
                '        body = []',
                '        for m in node.methods:',
                '            is_abs = (not m.body or',
                '                      (len(m.body)==1 and isinstance(m.body[0],PassStmt)) or',
                '                      (len(m.body)==1 and isinstance(m.body[0],ExprStmt)',
                '                       and isinstance(m.body[0].value,EllipsisLiteral)))',
                '            if is_abs: body.append(f"{pad}    @abstractmethod")',
                '            body.append(emit(m,indent+1))',
                '        out += body if body else [f"{pad}    pass"]',
                '        return "\\n".join(out)',
            ]

        # Strip transfer sigil — XFER tokens are consumed in parser but
        # if an IdentExpr wraps a caret-suffixed name just pass it through
        L.append('    # Transfer sigil ^ is stripped by the tokenizer (XFER ignored)')

        L.append('    raise TypeError(f"Cannot emit {type(node).__name__}")')
        return '\n'.join(L)

    def _gen_emit_if(self):
        return ['    if isinstance(node,IfStmt):',
                '        out = [f"{pad}if {emit(node.condition)}:"]',
                '        out += [emit(s,indent+1) for s in node.then_body]',
                '        for (ec,eb) in node.elifs:',
                '            out.append(f"{pad}elif {emit(ec)}:"); out += [emit(s,indent+1) for s in eb]',
                '        if node.else_body is not None:',
                '            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]',
                '        return "\\n".join(out)']

    def _gen_emit_while(self, cf):
        has_else = 'else' in cf.alt_kws
        L = ['    if isinstance(node,WhileStmt):',
             '        out = [f"{pad}while {emit(node.condition)}:"]',
             '        out += [emit(s,indent+1) for s in node.body]']
        if has_else:
            L += ['        if node.else_body is not None:',
                  '            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]']
        L.append('        return "\\n".join(out)')
        return L

    def _gen_emit_for(self, cf):
        has_else = 'else' in cf.alt_kws
        L = ['    if isinstance(node,ForStmt):',
             '        out = [f"{pad}for {emit(node.target) if not isinstance(node.target,str) else node.target} in {emit(node.iterable)}:"]',
             '        out += [emit(s,indent+1) for s in node.body]']
        if has_else:
            L += ['        if node.else_body is not None:',
                  '            out.append(f"{pad}else:"); out += [emit(s,indent+1) for s in node.else_body]']
        L.append('        return "\\n".join(out)')
        return L

    # ==================================================================
    # 6. Driver
    # ==================================================================

    def _driver(self) -> str:
        return textwrap.dedent("""\
            # ── Driver ──────────────────────────────────────────────────────────
            def compile(src: str) -> str:
                tokens = tokenize(src)
                stmts  = Parser(tokens).parse_module()
                return emit_module(stmts)

            if __name__ == '__main__':
                import sys
                src = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1]).read()
                print(compile(src))
        """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lit_cls(kind: str) -> str:
    m = {'integer':'IntLiteral','float':'FloatLiteral','bool':'BoolLiteral',
         'none':'NoneLiteral','self':'SelfLiteral',
         'string':'StringLiteral','tstring':'TstringLiteral'}
    return m.get(kind, kind.title().replace('_','')+'Literal')
