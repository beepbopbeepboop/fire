#!/usr/bin/env python3
"""
Code generator for gimple_codegen.py from specifications.

Extracts machine-readable tables from spec files and writes generated_dispatch.py,
which gimple_codegen.py imports instead of maintaining duplicate hardcoded dicts.

Sources:
  - GNU-EXTENSIONS.md   → _BIN_OPS, _CMP_OPS  (Operator Tables code block)
  - gimple-type-system.md → _SIGNED, _UNSIGNED, _FLOAT  (rank table code blocks)

Output (generated_dispatch.py):
  _SIGNED, _UNSIGNED, _FLOAT   — TypeLattice rank tables
  _BIN_OPS, _CMP_OPS           — operator lookup tables
  _STMT_DISPATCH               — AST node name → _gen_stmt_* method name
  _EXPR_DISPATCH               — AST node name → _lower_* method name

Usage:
  python gimple_spec_gen.py --output-module generated_dispatch.py
  python gimple_spec_gen.py --show-stats
"""

import re
import sys
from pathlib import Path


class GimpleSpecGenerator:
    """Generates gimple dispatch module from markdown specifications."""

    def __init__(self, spec_file: str = "GNU-EXTENSIONS.md",
                 type_spec_file: str = "gimple-type-system.md"):
        self.spec_file = spec_file
        self.type_spec_file = type_spec_file
        self.spec_content = self._read_file(spec_file)
        self.type_spec_content = self._read_file(type_spec_file)

        self.bin_ops: dict[str, str] = {}
        self.cmp_ops: set[str] = set()
        self.type_ranks: dict[str, dict[str, int]] = {}

        self._extract_bin_ops()
        self._extract_cmp_ops()
        self._extract_type_system()

    def _read_file(self, filename: str) -> str:
        try:
            with open(filename) as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"Specification file not found: {filename}")

    def _extract_bin_ops(self) -> None:
        """Extract _BIN_OPS from the machine-readable code block in GNU-EXTENSIONS.md."""
        match = re.search(
            r'```python\n(.*?_BIN_OPS\s*=\s*\{.*?\})',
            self.spec_content, re.DOTALL
        )
        if not match:
            print("Warning: no _BIN_OPS block found in spec", file=sys.stderr)
            return
        block = match.group(1)
        dict_match = re.search(r'_BIN_OPS\s*=\s*\{(.*?)\}', block, re.DOTALL)
        if not dict_match:
            return
        # Use findall to handle multiple pairs per line
        pairs = re.findall(r"'([^']+)':\s*'([^']*)'", dict_match.group(1))
        for k, v in pairs:
            self.bin_ops[k] = v

    def _extract_cmp_ops(self) -> None:
        """Extract _CMP_OPS from the machine-readable code block in GNU-EXTENSIONS.md."""
        match = re.search(
            r'```python\n.*?_CMP_OPS\s*=\s*\{([^}]*)\}',
            self.spec_content, re.DOTALL
        )
        if not match:
            print("Warning: no _CMP_OPS block found in spec", file=sys.stderr)
            return
        for item in match.group(1).split(','):
            item = item.strip().strip("'")
            if item:
                self.cmp_ops.add(item)

    def _extract_type_system(self) -> None:
        """Extract _SIGNED, _UNSIGNED, _FLOAT rank tables from gimple-type-system.md."""
        for category, pattern in [
            ('signed',   r'_SIGNED\s*=\s*\{(.*?)\}'),
            ('unsigned', r'_UNSIGNED\s*=\s*\{(.*?)\}'),
            ('float',    r'_FLOAT\s*=\s*\{(.*?)\}'),
        ]:
            m = re.search(pattern, self.type_spec_content, re.DOTALL)
            if not m:
                continue
            ranks: dict[str, int] = {}
            for line in m.group(1).split('\n'):
                line = line.strip().rstrip(',')
                if line.startswith('#'):
                    continue
                mm = re.match(r"'([^']+)':\s*(\d+)", line)
                if mm:
                    ranks[mm.group(1)] = int(mm.group(2))
            self.type_ranks[category] = ranks

    # -- Dispatch table definitions ------------------------------------------
    # These map AST node type.__name__ → handler method on GimpleCodegen.
    # The method names are the convention used throughout gimple_codegen.py.

    _STMT_DISPATCH_ENTRIES = [
        ('PassStmt',        '_gen_stmt_PassStmt'),
        ('VarDecl',         '_gen_stmt_VarDecl'),
        ('AssignStmt',      '_gen_stmt_AssignStmt'),
        ('AugAssignStmt',   '_gen_stmt_AugAssignStmt'),
        ('MultiAssignStmt', '_gen_stmt_MultiAssignStmt'),
        ('ReturnStmt',      '_gen_stmt_ReturnStmt'),
        ('IfStmt',          '_gen_stmt_IfStmt'),
        ('WhileStmt',       '_gen_stmt_WhileStmt'),
        ('ForStmt',         '_gen_stmt_ForStmt'),
        ('BreakStmt',       '_gen_stmt_BreakStmt'),
        ('ContinueStmt',    '_gen_stmt_ContinueStmt'),
        ('ExprStmt',        '_gen_stmt_ExprStmt'),
        ('AssertStmt',      '_gen_stmt_AssertStmt'),
        ('RaiseStmt',       '_gen_stmt_RaiseStmt'),
        ('TryStmt',         '_gen_stmt_TryStmt'),
        ('WithStmt',        '_gen_stmt_WithStmt'),
        ('FunctionDef',     '_gen_stmt_FunctionDef'),
        ('ImportStmt',      '_gen_stmt_ImportStmt'),
        ('FromImportStmt',  '_gen_stmt_FromImportStmt'),
        ('ComptimeIfStmt',  '_gen_stmt_ComptimeIfStmt'),
        ('ComptimeForStmt', '_gen_stmt_ComptimeForStmt'),
    ]

    _EXPR_DISPATCH_ENTRIES = [
        ('IntLiteral',      '_lower_IntLiteral'),
        ('FloatLiteral',    '_lower_FloatLiteral'),
        ('BoolLiteral',     '_lower_BoolLiteral'),
        ('EllipsisLiteral', '_lower_EllipsisLiteral'),
        ('StringLiteral',   '_lower_StringLiteral'),
        ('IdentExpr',       '_lower_IdentExpr'),
        ('WalrusExpr',      '_lower_WalrusExpr'),
        ('BinaryOp',        '_lower_binary'),
        ('UnaryOp',         '_lower_UnaryOp'),
        ('CallExpr',        '_lower_call'),
        ('TernaryExpr',     '_lower_TernaryExpr'),
        ('MemberExpr',      '_lower_MemberExpr'),
        ('SubscriptExpr',   '_lower_subscript'),
        ('SliceExpr',       '_lower_slice'),
        ('ListExpr',        '_lower_list_literal'),
        ('DictExpr',        '_lower_dict_literal'),
        ('SetExpr',         '_lower_set_literal'),
        ('TupleExpr',       '_lower_tuple_literal'),
        ('Comprehension',   '_lower_comprehension'),
    ]

    # -- Code generation ------------------------------------------------------

    def generate_dispatch_module(self) -> str:
        lines = [
            '# AUTO-GENERATED by gimple_spec_gen.py — do not edit directly.',
            '# Regenerate with: python gimple_spec_gen.py --output-module generated_dispatch.py',
            '# Sources: GNU-EXTENSIONS.md, gimple-type-system.md',
            '',
            '# ---------------------------------------------------------------------------',
            '# Type lattice rank tables  (source: gimple-type-system.md)',
            '# ---------------------------------------------------------------------------',
            '',
            '_SIGNED: dict = {',
        ]
        for k, v in sorted(self.type_ranks.get('signed', {}).items(), key=lambda x: x[1]):
            lines.append(f'    {k!r}: {v},')
        lines += [
            '}',
            '',
            '_UNSIGNED: dict = {',
        ]
        for k, v in sorted(self.type_ranks.get('unsigned', {}).items(), key=lambda x: x[1]):
            lines.append(f'    {k!r}: {v},')
        lines += [
            '}',
            '',
            '_FLOAT: dict = {',
        ]
        for k, v in sorted(self.type_ranks.get('float', {}).items(), key=lambda x: x[1]):
            lines.append(f'    {k!r}: {v},')
        lines += [
            '}',
            '',
            '# ---------------------------------------------------------------------------',
            '# Operator tables  (source: GNU-EXTENSIONS.md)',
            '# ---------------------------------------------------------------------------',
            '',
            '# Mojo operator → C infix operator.',
            '# ** // @ are absent; they have dedicated lowering routines.',
            '_BIN_OPS: dict = {',
        ]
        for k, v in self.bin_ops.items():
            lines.append(f'    {k!r}: {v!r},')
        lines += [
            '}',
            '',
            '_CMP_OPS: set = {',
        ]
        for op in sorted(self.cmp_ops):
            lines.append(f'    {op!r},')
        lines += [
            '}',
            '',
            '# ---------------------------------------------------------------------------',
            '# Statement dispatch table',
            '# Maps AST node type.__name__ → method name on GimpleCodegen',
            '# ---------------------------------------------------------------------------',
            '',
            '_STMT_DISPATCH: dict = {',
        ]
        for node_name, method_name in self._STMT_DISPATCH_ENTRIES:
            lines.append(f'    {node_name!r}: {method_name!r},')
        lines += [
            '}',
            '',
            '# ---------------------------------------------------------------------------',
            '# Expression dispatch table',
            '# Maps AST node type.__name__ → method name on GimpleCodegen',
            '# ---------------------------------------------------------------------------',
            '',
            '_EXPR_DISPATCH: dict = {',
        ]
        for node_name, method_name in self._EXPR_DISPATCH_ENTRIES:
            lines.append(f'    {node_name!r}: {method_name!r},')
        lines.append('}')
        return '\n'.join(lines) + '\n'

    def show_stats(self) -> str:
        lines = [
            '=' * 70,
            'GIMPLE SPEC EXTRACTION STATISTICS',
            '=' * 70,
            '',
            f'_BIN_OPS  entries : {len(self.bin_ops)}',
            f'_CMP_OPS  entries : {len(self.cmp_ops)}',
            f'_SIGNED   entries : {len(self.type_ranks.get("signed", {}))}',
            f'_UNSIGNED entries : {len(self.type_ranks.get("unsigned", {}))}',
            f'_FLOAT    entries : {len(self.type_ranks.get("float", {}))}',
            f'_STMT_DISPATCH    : {len(self._STMT_DISPATCH_ENTRIES)} handlers',
            f'_EXPR_DISPATCH    : {len(self._EXPR_DISPATCH_ENTRIES)} handlers',
            '',
            'Extraction sources:',
            f'  {self.spec_file}       → _BIN_OPS, _CMP_OPS',
            f'  {self.type_spec_file}  → _SIGNED, _UNSIGNED, _FLOAT',
        ]
        return '\n'.join(lines)


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Generate GIMPLE dispatch module from specs")
    ap.add_argument('--output-module', metavar='PATH',
                    help='Write generated_dispatch.py to this path')
    ap.add_argument('--show-stats', action='store_true',
                    help='Print extraction statistics')
    ap.add_argument('--spec', default='GNU-EXTENSIONS.md',
                    help='Operator/statement spec file')
    ap.add_argument('--type-spec', default='gimple-type-system.md',
                    help='Type system spec file')
    args = ap.parse_args()

    try:
        gen = GimpleSpecGenerator(args.spec, args.type_spec)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.show_stats:
        print(gen.show_stats())

    if args.output_module:
        code = gen.generate_dispatch_module()
        Path(args.output_module).write_text(code)
        print(f"Written to {args.output_module}")
    elif not args.show_stats:
        print(gen.generate_dispatch_module())


if __name__ == '__main__':
    main()
