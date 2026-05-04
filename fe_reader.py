"""Formal English Reader — mines .md prose into LanguageSpec AST nodes."""
from __future__ import annotations
import re
from lang_spec import (IntForm, FloatForm, BoolForm, LiteralDef,
                        OperatorDef, ControlFlowDef, FunctionSpec,
                        SimpleStmtDef, ImportDef, AssignmentDef,
                        ExpressionDef, TryStmtDef, WithStmtDef,
                        ComptimeDef, LanguageSpec,
                        LayoutDef,
                        ArgConventionDef, StructSpec, TraitSpec, LifecycleDef,
                        ParameterDef, PointerDef, PythonInteropDef, GPUDef,
                        TestingDef, CollectionTypeDef)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_SECTION_RE        = re.compile(r'^#{1,3}\s+(.+?)\s*$', re.MULTILINE)
_BACKTICK_RE       = re.compile(r'`([^`]+)`')
_QUOTED_RULE_RE    = re.compile(r'"([^"]+)"')
_LITERAL_BULLET_RE = re.compile(
    r'^\s*-\s+(\w[\w\s-]*):\s+`([^`]+)`(?:\s+\(([^)]*)\))?', re.MULTILINE)
_PREC_ENTRY_RE     = re.compile(
    r'^(\d+)\.\s+\*\*([^*]+)\*\*\s+\(([^)]+)\)(.*)', re.MULTILINE)
_SIMPLE_STMT_RE    = re.compile(r'^\s*[-*]\s+`(\w+)`:\s+(.+)', re.MULTILINE)
_PREFIX_RE         = re.compile(r'(0[a-zA-Z])')
_BOOL_BULLET_RE    = re.compile(r'\*\*Boolean\*\*.*`True`.*`False`', re.IGNORECASE)

_BASE_DIGIT_RE   = {16: r'[0-9a-fA-F]+', 8: r'[0-7]+', 2: r'[01]+',
                    10: r'(?:0|[1-9][0-9]*)'}
_PREFIX_TO_BASE  = {'0x':16,'0X':16,'0o':8,'0O':8,'0b':2,'0B':2}
_CONTROL_KWS     = {'if','elif','else','while','for','break','continue','pass'}
_SIMPLE_KWS      = {'return','raise','break','continue','pass','assert'}
_HAS_VALUE       = {'return','raise','assert'}
_OPTIONAL_V      = {'return', 'raise'}

# Augmented assignment operators (sorted longest-first for regex)
_AUG_OPS_DEFAULT = ['**=','//=','<<=','>>=','+=','-=','*=','/=','%=',
                    '@=','&=','|=','^=']

# Expression kinds mapped from prose clues
_EXPR_CLUES = [
    (r'\[.*for.*in', 'comprehension_list'),
    (r'\{.*for.*in', 'comprehension_set'),
    (r'\[1,\s*2', 'list'),
    (r'\{.*:.*\}', 'dict'),
    (r'\{2,\s*3', 'set'),
    (r'`\w+\.\w+', 'member_access'),
    (r'`\w+\[', 'subscript'),
    (r'if.*else', 'ternary'),
    (r':=', 'walrus'),
    (r'\(1,\)', 'tuple'),
]


class FormalEnglishReader:
    def __init__(self):
        self.spec = LanguageSpec()

    def read(self, path: str) -> 'FormalEnglishReader':
        with open(path) as fh:
            text = fh.read()
        self._parse(text)
        return self

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _parse(self, text: str):
        positions = [(m.start(), m.group(1)) for m in _SECTION_RE.finditer(text)]
        positions.append((len(text), None))
        for i, (start, heading) in enumerate(positions[:-1]):
            body = text[start: positions[i+1][0]]
            self._dispatch(heading, body)

    def _dispatch(self, heading: str, body: str):
        h = heading.lower()

        # ── Literals ──────────────────────────────────────────────────
        if 'literal' in h and 'overview' not in h:
            if 'other' in h:
                self._extract_other_literals(body)
            elif 'floating' in h or 'float' in h:
                self._extract_float_literal(body)
            elif 'literal' in h:
                kind = (h.replace('literals','').replace('literal','')
                         .replace('-','').strip().replace(' ','_').strip('_')
                         or 'unknown')
                lit = self._extract_int_literal_def(kind, body)
                if lit:
                    self.spec.literals.append(lit)

        # ── Operators ─────────────────────────────────────────────────
        elif 'operator precedence' in h:
            self.spec.operators.extend(self._extract_operators(body))

        # ── Control flow ──────────────────────────────────────────────
        elif 'if statement' in h:
            self.spec.control_flow.append(self._extract_cf('if', body))
        elif 'while loop' in h:
            self.spec.control_flow.append(self._extract_cf('while', body))
        elif 'for loop' in h:
            self.spec.control_flow.append(self._extract_cf('for', body))
        elif 'loop else' in h:
            self._add_loop_else()

        # ── Error handling / context managers / comptime ───────────────
        elif 'error handling' in h:
            ts = self._extract_try_def(body)
            if ts: self.spec.try_stmts.append(ts)
        elif 'context manager' in h:
            ws = self._extract_with_def(body)
            if ws: self.spec.with_stmts.append(ws)
        elif 'compile-time control' in h:
            cd = self._extract_comptime_def(body)
            if cd: self.spec.comptime.append(cd)

        # ── Import statements ─────────────────────────────────────────
        elif 'import statement' in h:
            imp = self._extract_import_def(body)
            if imp and not self.spec.imports:
                self.spec.imports.append(imp)

        # ── Assignment statements ─────────────────────────────────────
        elif 'assignment statement' in h:
            asgn = self._extract_assignment_def(body)
            if asgn and not self.spec.assignments:
                self.spec.assignments.append(asgn)

        # ── Simple statements ─────────────────────────────────────────
        elif ('simple statement' in h and 'reference' not in h) or 'key statement' in h:
            self.spec.simple_stmts.extend(self._extract_simple_stmts(body))
            # Mine bold subsections within same body for imports/assignments
            if not self.spec.imports:
                imp = self._extract_import_def(body)
                if imp: self.spec.imports.append(imp)
            if not self.spec.assignments:
                asgn = self._extract_assignment_def(body)
                if asgn: self.spec.assignments.append(asgn)

        # ── Keywords by category (mojo-keywords.md) ───────────────────
        elif 'keywords by category' in h:
            self._extract_kws_by_category(body)

        # ── Layout rules (also caught by global scan below) ────────────
        # (no elif — handled in the unconditional scan at end of dispatch)

        # ── Argument conventions / ownership ──────────────────────────
        elif ('argument convention' in h
              or ('ownership' in h and 'argument' in h)
              or 'value ownership' in h
              or ('convention' in h and 'pass' in h)):
            ac = self._extract_arg_conventions(body)
            if ac:
                self._merge_arg_conventions(ac)

        # ── Struct spec ────────────────────────────────────────────────
        elif (('struct' in h or 'fieldwise' in h)
              and 'lifecycle' not in h and 'python' not in h
              and 'test' not in h
              and 'copy constructor' not in h and 'move constructor' not in h
              and 'destructor' not in h):
            ss = self._extract_struct_spec(body)
            if ss:
                self._merge_struct_spec(ss)

        # ── Traits ─────────────────────────────────────────────────────
        elif ('trait' in h or 'built-in trait' in h
              or 'conformance' in h):
            ts = self._extract_trait_spec(body)
            if ts:
                self._merge_trait_spec(ts)

        # ── Lifecycle ──────────────────────────────────────────────────
        elif ('lifecycle' in h or 'value creation' in h
              or 'value destruction' in h or 'copy constructor' in h
              or 'constructors' in h or 'destructor' in h
              or 'constructor' in h or 'transfer argument' in h
              or ('transfer' in h and 'sigil' in h)):
            lc = self._extract_lifecycle_def(body)
            if lc is None:
                lc = LifecycleDef(False, False, False, False)
            # Supplement from heading text (code-block `#` cuts section bodies)
            if 'copy constructor' in h or ('copy' in h and 'constructor' in h):
                lc.has_copy_constructor = True
            if 'move constructor' in h or ('move' in h and 'constructor' in h):
                lc.has_move_constructor = True
            if 'destructor' in h or 'deinit' in h:
                lc.has_destructor = True
            if '^' in h or 'transfer' in h:
                lc.has_transfer_sigil = True
            self._merge_lifecycle_def(lc)

        # ── Compile-time parameters ────────────────────────────────────
        elif (h == 'parameters (compile-time values)'
              or ('parameter' in h and ('compile' in h or 'parameteriz' in h
                  or 'keyword' in h or 'optional' in h or 'variadic' in h
                  or 'infer' in h or 'default' in h))):
            pd = self._extract_parameter_def(body)
            if pd:
                self._merge_parameter_def(pd)

        # ── Pointer types ──────────────────────────────────────────────
        elif 'pointer' in h:
            ptr = self._extract_pointer_def(body)
            if ptr:
                self._merge_pointer_def(ptr)

        # ── Python interop ─────────────────────────────────────────────
        elif ('calling python' in h or 'python interop' in h
              or 'python types' in h or 'python from mojo' in h
              or 'importing python' in h or 'local python' in h
              or ('python' in h and 'mojo' in h)):
            pi = self._extract_python_interop(body)
            if pi:
                self._merge_python_interop(pi)

        # ── GPU programming ────────────────────────────────────────────
        elif ('gpu' in h or 'devicecontext' in h or 'kernel' in h
              or 'device context' in h or 'accelerator' in h
              or 'block and warp' in h or 'devicebuffer' in h
              or 'hostbuffer' in h or 'thread index' in h
              or 'devicpassable' in h or 'devicepassable' in h
              or ('device' in h and 'buffer' in h)):
            gd = self._extract_gpu_def(body)
            if gd:
                self._merge_gpu_def(gd)

        # ── Testing ────────────────────────────────────────────────────
        elif 'testing' in h or 'assertion function' in h or 'test function' in h:
            td = self._extract_testing_def(body)
            if td:
                self._merge_testing_def(td)

        # ── Expressions ───────────────────────────────────────────────
        # Any section in the expressions file
        if 'core expression' in h or 'collection' in h or 'operation' in h or 'advanced' in h:
            self._extract_expression_defs(body)

        # ── Collection types (scan broadly — code-block # cuts sections short)
        if ('type' in h or 'collection' in h or 'optional' in h
                or 'tuple' in h or 'dict' in h or 'list' in h
                or 'iteration' in h or 'variant' in h):
            ct = self._extract_collection_types(body)
            if ct:
                self._merge_collection_types(ct)

        # ── Layout rules (scan every section, merge contributions) ───────
        ld = self._extract_layout_def(body)
        if ld:
            self._merge_layout_def(ld)

        # ── Functions (any section mentioning `def` or @staticmethod) ─
        if not self.spec.functions:
            fs = self._extract_function_spec(body)
            if fs: self.spec.functions.append(fs)
        elif '@staticmethod' in body:
            for fs in self.spec.functions:
                if 'staticmethod' not in fs.decorators:
                    fs.decorators.append('staticmethod')

    # ------------------------------------------------------------------
    # Integer literal extraction
    # ------------------------------------------------------------------

    def _extract_int_literal_def(self, kind: str, body: str) -> LiteralDef | None:
        forms = []
        for m in _LITERAL_BULLET_RE.finditer(body):
            name, example, paren = m.group(1).strip(), m.group(2), m.group(3) or ''
            form = self._infer_int_form(name, example, paren)
            if form: forms.append(form)
        constraints = [m.group(1) for m in _QUOTED_RULE_RE.finditer(body)]
        if not forms and not constraints:
            return None
        return LiteralDef(kind=kind, forms=forms, constraints=constraints)

    def _infer_int_form(self, name, example, paren) -> IntForm | None:
        prefixes = _PREFIX_RE.findall(paren)
        if prefixes:
            base = _PREFIX_TO_BASE.get(prefixes[0][:2].lower(), None)
            prefixes = list(dict.fromkeys(prefixes))
        else:
            base, prefixes = 10, []
        if base is None:
            return None
        return IntForm(name=name.lower(), base=base, prefixes=prefixes,
                       digit_re=_BASE_DIGIT_RE[base])

    # ------------------------------------------------------------------
    # Float literal
    # ------------------------------------------------------------------

    def _extract_float_literal(self, body: str):
        constraints = [m.group(1) for m in _QUOTED_RULE_RE.finditer(body)]
        self.spec.literals.append(
            LiteralDef(kind='float', forms=[FloatForm()], constraints=constraints))

    # ------------------------------------------------------------------
    # Other literals (bool, None, Self, …)
    # ------------------------------------------------------------------

    def _extract_other_literals(self, body: str):
        if _BOOL_BULLET_RE.search(body):
            self.spec.literals.append(
                LiteralDef(kind='bool', forms=[BoolForm()], constraints=[]))
        if '`None`' in body:
            self.spec.literals.append(
                LiteralDef(kind='none', forms=[], constraints=[]))
        if '`Self`' in body:
            self.spec.literals.append(
                LiteralDef(kind='self', forms=[], constraints=[]))

    # ------------------------------------------------------------------
    # Operators
    # ------------------------------------------------------------------

    def _extract_operators(self, body: str) -> list[OperatorDef]:
        ops = []
        for m in _PREC_ENTRY_RE.finditer(body):
            position  = int(m.group(1))
            category  = m.group(2).strip().lower()
            sym_text  = m.group(3)
            remainder = m.group(4)
            symbols   = [s.group(1) for s in _BACKTICK_RE.finditer(sym_text)]
            assoc     = 'right' if 'right-associative' in remainder else 'left'
            ops.append(OperatorDef(symbols=symbols, category=category,
                                   precedence=position, assoc=assoc))
        return ops

    # ------------------------------------------------------------------
    # Control flow
    # ------------------------------------------------------------------

    def _extract_cf(self, kind: str, body: str) -> ControlFlowDef:
        kws_found = [t for t in _BACKTICK_RE.findall(body) if t in _CONTROL_KWS]
        alt_kws   = list(dict.fromkeys(k for k in kws_found if k != kind))
        snippet   = body.split('\n')[1][:120].strip() if '\n' in body else body[:120]
        return ControlFlowDef(kind=kind, primary_kw=kind, alt_kws=alt_kws,
                              has_condition=kind in ('if','while'),
                              description=snippet)

    def _add_loop_else(self):
        for cf in self.spec.control_flow:
            if cf.kind in ('while','for') and 'else' not in cf.alt_kws:
                cf.alt_kws.append('else')

    # ------------------------------------------------------------------
    # Error handling / with / comptime
    # ------------------------------------------------------------------

    def _extract_try_def(self, body: str) -> TryStmtDef | None:
        kws = _BACKTICK_RE.findall(body)
        try_kws = list(dict.fromkeys(k for k in kws
                                     if k in ('try','except','else','finally')))
        return TryStmtDef(keywords=try_kws, binding_kw='as') if 'try' in try_kws else None

    def _extract_with_def(self, body: str) -> WithStmtDef | None:
        return WithStmtDef() if '`with`' in body else None

    def _extract_comptime_def(self, body: str) -> ComptimeDef | None:
        kinds = []
        for m in re.finditer(r'\*\*comptime\s+(\w+)\*\*', body):
            k = m.group(1)
            if k in ('if','for') and k not in kinds:
                kinds.append(k)
        return ComptimeDef(prefix='comptime', kinds=kinds) if kinds else None

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def _extract_import_def(self, body: str) -> ImportDef | None:
        if 'import' not in body:
            return None
        return ImportDef(
            keyword='import',
            from_keyword='from',
            alias_kw='as',
            has_wildcard='*' in body,
        )

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def _extract_assignment_def(self, body: str) -> AssignmentDef | None:
        kws  = _BACKTICK_RE.findall(body)
        decl = 'var' if 'var' in body else ''
        # Augmented ops: backtick tokens that end with = and len > 1
        aug_ops = [k for k in kws if k.endswith('=') and len(k) > 1]
        # If none found in prose, use the canonical default list
        if not aug_ops:
            aug_ops = _AUG_OPS_DEFAULT
        # Sort longest-first for the lexer regex
        aug_ops.sort(key=len, reverse=True)
        has_dest = 'destructuring' in body.lower() or 'a, b' in body
        return AssignmentDef(declaration_kw=decl, aug_ops=aug_ops,
                             has_destructuring=has_dest)

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------

    def _extract_expression_defs(self, body: str):
        seen = {ed.kind for ed in self.spec.expressions}
        for pattern, kind in _EXPR_CLUES:
            if kind not in seen and re.search(pattern, body):
                self.spec.expressions.append(ExpressionDef(kind=kind))
                seen.add(kind)

    # ------------------------------------------------------------------
    # Functions
    # ------------------------------------------------------------------

    def _extract_function_spec(self, body: str) -> FunctionSpec | None:
        kws = _BACKTICK_RE.findall(body)
        if 'def' not in kws:
            return None
        decorators = []
        if '@staticmethod' in body or 'staticmethod' in body:
            decorators.append('staticmethod')
        if 'raises' in body:
            decorators.append('raises')
        return FunctionSpec(keyword='def', return_arrow='->' if '->' in body else '',
                            decorators=decorators)

    # ------------------------------------------------------------------
    # Keywords by category
    # ------------------------------------------------------------------

    def _extract_kws_by_category(self, body: str):
        # Mine Error Handling line for `assert`
        seen = {s.kind for s in self.spec.simple_stmts}
        for m in re.finditer(r'\*\*Error Handling\*\*[^:\n]*:(.*)', body):
            for kw_m in _BACKTICK_RE.finditer(m.group(1)):
                kw = kw_m.group(1)
                if kw in _SIMPLE_KWS and kw not in seen:
                    seen.add(kw)
                    self.spec.simple_stmts.append(
                        SimpleStmtDef(kind=kw, keyword=kw,
                                      has_value=kw in _HAS_VALUE,
                                      optional=kw in _OPTIONAL_V))

    # ------------------------------------------------------------------
    # Simple statements
    # ------------------------------------------------------------------

    def _extract_simple_stmts(self, body: str) -> list[SimpleStmtDef]:
        stmts, seen = [], set()
        for m in _SIMPLE_STMT_RE.finditer(body):
            kw = m.group(1)
            if kw not in _SIMPLE_KWS or kw in seen:
                continue
            seen.add(kw)
            stmts.append(SimpleStmtDef(kind=kw, keyword=kw,
                                        has_value=kw in _HAS_VALUE,
                                        optional=kw in _OPTIONAL_V))
        # Handle  `break`/`continue`: Loop control  (slash-separated)
        slash_match = re.search(r'`(break)`/`(continue)`', body)
        if slash_match:
            for kw in ('break', 'continue'):
                if kw not in seen:
                    seen.add(kw)
                    stmts.append(SimpleStmtDef(kind=kw, keyword=kw,
                                               has_value=False, optional=False))
        return stmts

    # ------------------------------------------------------------------
    # Layout rules
    # ------------------------------------------------------------------

    def _extract_layout_def(self, body: str) -> LayoutDef | None:
        bl = body.lower()
        toks = _BACKTICK_RE.findall(body)

        # indentation
        has_indent = ('indented' in bl or 'indentation' in bl or 'block scope' in bl)
        indent_size = 4
        if has_indent:
            m = re.search(r'(\d+)\s+spaces', body)
            if m:
                indent_size = int(m.group(1))

        # Mojo has no backslash line-continuation; multi-line uses indentation
        continuation = ''

        # separator: backtick `;` or prose "semicolons"
        separator = next((t for t in toks if t == ';'), '')
        if not separator and 'semicolon' in bl:
            separator = ';'

        # comment char: backtick `#`
        comment = next((t for t in toks if t == '#'), '')

        if not has_indent and not separator and not comment:
            return None
        return LayoutDef(
            has_indentation   = has_indent,
            indent_size       = indent_size,
            continuation_char = continuation,
            stmt_separator    = separator,
            comment_char      = comment,
        )

    def _merge_layout_def(self, ld: LayoutDef):
        if not self.spec.layout:
            self.spec.layout.append(ld)
        else:
            e = self.spec.layout[0]
            if ld.has_indentation:
                e.has_indentation = True
                e.indent_size = ld.indent_size
            if ld.stmt_separator:
                e.stmt_separator = ld.stmt_separator
            if ld.comment_char:
                e.comment_char = ld.comment_char

    # ------------------------------------------------------------------
    # Merge helpers (accumulate across sub-sections)
    # ------------------------------------------------------------------

    def _merge_arg_conventions(self, ac: ArgConventionDef):
        if not self.spec.arg_conventions:
            self.spec.arg_conventions.append(ac)
        else:
            existing = self.spec.arg_conventions[0]
            for c in ac.conventions:
                if c not in existing.conventions:
                    existing.conventions.append(c)

    def _merge_struct_spec(self, ss: StructSpec):
        if not self.spec.structs:
            self.spec.structs.append(ss)
        else:
            existing = self.spec.structs[0]
            for d in ss.decorators:
                if d not in existing.decorators:
                    existing.decorators.append(d)
            for t in ss.traits:
                if t not in existing.traits:
                    existing.traits.append(t)
            if ss.has_fields:
                existing.has_fields = True

    def _merge_trait_spec(self, ts: TraitSpec):
        if not self.spec.traits:
            self.spec.traits.append(ts)
        else:
            existing = self.spec.traits[0]
            if ts.has_where_clause:
                existing.has_where_clause = True
            for t in ts.builtin_traits:
                if t not in existing.builtin_traits:
                    existing.builtin_traits.append(t)

    def _merge_lifecycle_def(self, lc: LifecycleDef):
        if not self.spec.lifecycle:
            self.spec.lifecycle.append(lc)
        else:
            existing = self.spec.lifecycle[0]
            existing.has_transfer_sigil    = existing.has_transfer_sigil    or lc.has_transfer_sigil
            existing.has_copy_constructor  = existing.has_copy_constructor  or lc.has_copy_constructor
            existing.has_move_constructor  = existing.has_move_constructor  or lc.has_move_constructor
            existing.has_destructor        = existing.has_destructor        or lc.has_destructor

    def _merge_pointer_def(self, ptr: PointerDef):
        if not self.spec.pointers:
            self.spec.pointers.append(ptr)
        else:
            existing = self.spec.pointers[0]
            for t in ptr.types:
                if t not in existing.types:
                    existing.types.append(t)

    def _merge_python_interop(self, pi: PythonInteropDef):
        if not self.spec.python_interop:
            self.spec.python_interop.append(pi)
        else:
            existing = self.spec.python_interop[0]
            if pi.import_fn:     existing.import_fn     = pi.import_fn
            if pi.wrapper_type:  existing.wrapper_type  = pi.wrapper_type
            if pi.add_to_path_fn: existing.add_to_path_fn = pi.add_to_path_fn

    def _merge_gpu_def(self, gd: GPUDef):
        if not self.spec.gpu:
            self.spec.gpu.append(gd)
        else:
            existing = self.spec.gpu[0]
            if gd.device_type:
                existing.device_type = gd.device_type
            for t in gd.buffer_types:
                if t not in existing.buffer_types:
                    existing.buffer_types.append(t)
            for v in gd.index_vars:
                if v not in existing.index_vars:
                    existing.index_vars.append(v)

    def _merge_testing_def(self, td: TestingDef):
        if not self.spec.testing:
            self.spec.testing.append(td)
        else:
            existing = self.spec.testing[0]
            if td.suite_type:
                existing.suite_type = td.suite_type
            for f in td.assertion_fns:
                if f not in existing.assertion_fns:
                    existing.assertion_fns.append(f)

    def _merge_parameter_def(self, pd: ParameterDef):
        if not self.spec.parameters:
            self.spec.parameters.append(pd)
        else:
            existing = self.spec.parameters[0]
            if pd.has_infer_only:
                existing.has_infer_only = True
            if pd.has_default:
                existing.has_default = True

    def _merge_collection_types(self, ct: CollectionTypeDef):
        if not self.spec.collection_types:
            self.spec.collection_types.append(ct)
        else:
            existing = self.spec.collection_types[0]
            for t in ct.types:
                if t not in existing.types:
                    existing.types.append(t)

    # ------------------------------------------------------------------
    # Argument conventions
    # ------------------------------------------------------------------

    def _extract_arg_conventions(self, body: str) -> ArgConventionDef | None:
        _CONV_KWS = {'read', 'mut', 'var', 'ref', 'out', 'deinit'}
        found = list(dict.fromkeys(
            t for t in _BACKTICK_RE.findall(body) if t in _CONV_KWS))
        return ArgConventionDef(conventions=found) if found else None

    # ------------------------------------------------------------------
    # Struct spec
    # ------------------------------------------------------------------

    _STRUCT_TRAITS = [
        'Copyable', 'Movable', 'ImplicitlyCopyable', 'ImplicitlyDestructible',
        'Writable', 'Hashable', 'Comparable', 'Equatable', 'Boolable',
        'Intable', 'KeyElement', 'Sized', 'AnyType',
    ]

    def _extract_struct_spec(self, body: str) -> StructSpec | None:
        if 'struct' not in body.lower():
            return None
        decorators = ['fieldwise_init'] if '@fieldwise_init' in body else []
        traits = [t for t in self._STRUCT_TRAITS if t in body]
        return StructSpec(decorators=decorators, traits=traits,
                          has_fields='var ' in body)

    # ------------------------------------------------------------------
    # Trait spec
    # ------------------------------------------------------------------

    _BUILTIN_TRAITS = [
        'Copyable', 'Movable', 'ImplicitlyCopyable', 'ImplicitlyDestructible',
        'Sized', 'Writable', 'Hashable', 'Comparable', 'Equatable',
        'Boolable', 'Intable', 'KeyElement', 'AnyType',
    ]

    def _extract_trait_spec(self, body: str) -> TraitSpec | None:
        if 'trait' not in body.lower():
            return None
        builtin = [t for t in self._BUILTIN_TRAITS if t in body]
        return TraitSpec(has_where_clause='where' in body,
                         builtin_traits=builtin)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _extract_lifecycle_def(self, body: str) -> LifecycleDef | None:
        bl = body.lower()
        return LifecycleDef(
            has_transfer_sigil='^' in body,
            has_copy_constructor='copy' in bl and '__init__' in body,
            has_move_constructor='move' in bl and '__init__' in body,
            has_destructor='__del__' in body,
        )

    # ------------------------------------------------------------------
    # Parameter def
    # ------------------------------------------------------------------

    def _extract_parameter_def(self, body: str) -> ParameterDef | None:
        if '[' not in body:
            return None
        has_default = ('default' in body.lower()
                       or bool(re.search(r'\[\w[^\]]*=\s*\w', body)))
        return ParameterDef(
            syntax='[]',
            has_infer_only='//' in body,
            has_default=has_default,
        )

    # ------------------------------------------------------------------
    # Pointer def
    # ------------------------------------------------------------------

    _PTR_TYPES = ['Pointer', 'OwnedPointer', 'ArcPointer', 'UnsafePointer']

    def _extract_pointer_def(self, body: str) -> PointerDef | None:
        found = list(dict.fromkeys(t for t in self._PTR_TYPES if t in body))
        return PointerDef(types=found) if found else None

    # ------------------------------------------------------------------
    # Python interop
    # ------------------------------------------------------------------

    def _extract_python_interop(self, body: str) -> PythonInteropDef | None:
        if 'Python' not in body:
            return None
        return PythonInteropDef(
            import_fn='Python.import_module' if 'import_module' in body else '',
            wrapper_type='PythonObject' if 'PythonObject' in body else '',
            add_to_path_fn='Python.add_to_path' if 'add_to_path' in body else '',
        )

    # ------------------------------------------------------------------
    # GPU def
    # ------------------------------------------------------------------

    _GPU_IDX_VARS = ['block_idx', 'thread_idx', 'global_idx',
                     'block_dim', 'grid_dim']
    _GPU_BUFFERS  = ['DeviceBuffer', 'HostBuffer']

    def _extract_gpu_def(self, body: str) -> GPUDef | None:
        buffers  = [t for t in self._GPU_BUFFERS  if t in body]
        idx_vars = [t for t in self._GPU_IDX_VARS if t in body]
        device   = 'DeviceContext' if 'DeviceContext' in body else ''
        if not device and not buffers and not idx_vars and 'GPU' not in body:
            return None
        return GPUDef(device_type=device, buffer_types=buffers, index_vars=idx_vars)

    # ------------------------------------------------------------------
    # Testing def
    # ------------------------------------------------------------------

    _ASSERT_FNS = ['assert_equal', 'assert_true', 'assert_false',
                   'assert_not_equal', 'assert_almost_equal', 'assert_raises']

    def _extract_testing_def(self, body: str) -> TestingDef | None:
        fns = list(dict.fromkeys(f for f in self._ASSERT_FNS if f in body))
        if not fns and 'TestSuite' not in body:
            return None
        return TestingDef(
            suite_type='TestSuite' if 'TestSuite' in body else '',
            assertion_fns=fns,
        )

    # ------------------------------------------------------------------
    # Collection types
    # ------------------------------------------------------------------

    _COLLECTION_TYPES = ['List', 'Dict', 'Set', 'Optional', 'Tuple', 'Variant']

    def _extract_collection_types(self, body: str) -> CollectionTypeDef | None:
        found = list(dict.fromkeys(t for t in self._COLLECTION_TYPES if t in body))
        return CollectionTypeDef(types=found) if found else None
