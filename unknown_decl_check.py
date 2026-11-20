"""Unknown-declaration check: a bare name read in a module that nothing binds.

Modular's compiler rejects a read of a name no declaration can supply, at the
use site, before any code is generated:

    kgen_lsp_check_parse_error.mojo:35:13: error: use of unknown declaration 'this_name_does_not_exist'
        var x = this_name_does_not_exist
                ^~~~~~~~~~~~~~~~~~~~~~~~

Without this pass the codegen's own fallback answers the read instead: an
unresolved identifier lowers to `(int64_t)0  /* ct param or undeclared: NAME */`,
a silent zero, and a build of a file that does not compile succeeds.

The check is deliberately conservative, so that it can only reject names that
are bound NOWHERE a valid program could bind them:

  * a name is bound if any declaration, import, parameter, loop/with/except/
    walrus/comprehension target, global/nonlocal or keyword name in the module
    spells it (every string field of every node counts, identifiers inside a
    dotted or comma-separated string included);
  * a name the stdlib declares at top level (the implicit prelude: `Int`,
    `String`, `UnsafePointer`, ...) is not reported, because this pass does
    not model the prelude's exact export list;
  * Python builtins and the runtime's own implicit names are not reported;
  * a module with a wildcard import (`from m import *`) is not checked, since
    its names are unknown here.

Only loads are checked. A name in a binding position (assignment, `for`,
`with ... as`, the target of `del`, a match capture) is a declaration.
"""

import builtins as _py_builtins
import dataclasses
import functools
import os
import re

import fire_compiler as N
from fire_compiler import _COMPTIME_TYPE_FUNCS

# Fields whose IdentExpr (directly, or inside a tuple/list target) is a
# declaration rather than a read.
_BINDING_FIELDS = frozenset({'target', 'targets', 'alias', 'pattern', 'patterns'})

# Nodes whose string fields are data (string contents, dotted paths), not names.
_NON_NAME_NODES = (N.StringLiteral, N.TstringLiteral, N.DottedLiteral)

# Fields that hold an attribute name, not a binding.
_NON_BINDING_STR_FIELDS = frozenset({'member'})

# A backtick-escaped identifier (`var `!` = 1`) is one identifier spelling, not
# two punctuations: the parser keeps the backticks in the name, so a binding
# walk that only knew `[A-Za-z_]\w*` bound NOTHING for it and then reported the
# read of the same spelling as undeclared.
_IDENT_RE = re.compile(r'`[^`\n]+`|[A-Za-z_]\w*')

# Fields whose reads are not checked here. A decorator's or `@align(...)`'s
# arguments are compile-time arguments that elaborate.py resolves and reports
# with its own `use of unknown declaration` diagnostic, after the module's
# output is built (the LSP recovery contract); their bindings still count.
_UNCHECKED_READ_FIELDS = frozenset({'decorators', 'align_expr'})

# Declaration keywords. The parser surfaces some of them as identifiers (a
# bare `alias X = ...` is an expression statement reading `alias`), and a
# keyword is never an undeclared name.
_KEYWORDS = frozenset({
    'var', 'let', 'alias', 'comptime', 'def', 'fn', 'struct', 'trait', 'class',
    'ref', 'raise', 'return', 'import', 'from', 'with', 'as', 'in', 'not',
    'and', 'or', 'is', 'if', 'elif', 'else', 'while', 'for', 'try', 'except',
    'finally', 'pass', 'break', 'continue', 'yield', 'await', 'async', 'del',
    'global', 'nonlocal', 'assert', 'lambda', 'match', 'case', 'mut', 'owned',
    'read', 'out', 'inout', 'borrowed', 'where',
})

# Names the runtime supplies in every scope without a declaration.
# Compile-time intrinsics the compiler lowers by name, with no declaration in
# any source file. `constrained` is handled in myinterpreter.py and in
# mojo/backend_gimple/emit_calls.py (the `name == 'constrained'` sites).
# `conforms_to` is NOT listed here: it is
# in GimpleGen._KNOWN_SIGS, read by _compiler_runtime_names().
# `__mlir_op` / `__mlir_attr` / `__mlir_type` are Mojo's own MLIR escape
# hatches (`__mlir_op.`index.add`(a, b)`); the stdlib is written in them.
# `create_future` is the event loop's future constructor, lowered by name in
# mojo/backend_gimple/emit_calls.py and mojo/middle/coro.py. `Event` and
# `Future` are the same Awaitable protocol's other two no-arg constructors,
# lowered by name at the same sites to the `__mojo_event_new` /
# `__mojo_future_new` shims (emit_calls.py, emit_methods.py, module_shared.py,
# coro.py); no source file declares them either. The unknown-decl pass landed
# in 0d277236a whitelisting only `create_future`, and refused the gate's
# coro-future-await job's bare `Event()` as "use of unknown declaration".
# `type_of` / `__type_of` are the compile-time type builtins, whose canonical
# set is `fire_compiler._COMPTIME_TYPE_FUNCS` (shared with ownership_check):
# their argument's STATIC TYPE is the result, so no runtime symbol exists.
_COMPILE_TIME_INTRINSICS = frozenset({
    'constrained', '__mlir_op', '__mlir_attr', '__mlir_type', 'create_future',
    'Event', 'Future',
}) | _COMPTIME_TYPE_FUNCS

_RUNTIME_NAMES = frozenset({
    'self', 'Self', '__file__', '__name__', '__init__', '__class__',
}) | _KEYWORDS | _COMPILE_TIME_INTRINSICS | frozenset(getattr(N, '_BUILTIN_NAMES', ()))

_STDLIB_DECL_RE = re.compile(
    r'^(?:def|fn|struct|trait|class|alias|comptime|var)\s+([A-Za-z_]\w*)'
    r'|^(?:from\s+\S+\s+)?import\s+(\([^)]*\)|[^\n]*)'
    r'|^([A-Za-z_]\w*)\s*[:=]',
    re.M)


@functools.lru_cache(maxsize=None)
def _stdlib_declared_names(stdlib_root: str) -> frozenset:
    """Every name the stdlib declares at column 0 (the prelude's candidates)."""
    names: set = set()
    std = os.path.join(stdlib_root, 'std')
    if not os.path.isdir(std):
        return frozenset()
    for root, _dirs, files in os.walk(std):
        for fname in files:
            if not fname.endswith('.mojo'):
                continue
            try:
                with open(os.path.join(root, fname), encoding='utf-8',
                          errors='replace') as fh:
                    text = fh.read()
            except OSError:
                continue
            for m in _STDLIB_DECL_RE.finditer(text):
                if m.group(1):
                    names.add(m.group(1))
                elif m.group(2) is not None:
                    names.update(_IDENT_RE.findall(m.group(2)))
                elif m.group(3):
                    names.add(m.group(3))
    return frozenset(names)


def _compiler_runtime_names() -> frozenset:
    """Every function the compiler provides to a program at run time.

    Three tables. `RT_SIGS` (mojo/middle/rt_sigs.py) is generated from the
    runtime headers and names every C function the runtime exports; a program
    may call any of them by name. `GimpleGen._KNOWN_SIGS` is hand-written and
    covers fewer of those, but also holds the compile-time builtins such as
    `conforms_to`, which the compiler lowers specially and no header declares.
    `gimple_codegen._RUNTIME_FUNCS` is the table a call resolves against: it
    holds functions whose definition is emitted by the compiler itself rather
    than exported by a header, e.g. the GPU sidecar's `_mojo_gpu_*`
    introspection entry points (mojo/backend_gimple/device_glue.py), so
    omitting it rejected a program calling them with "use of unknown
    declaration". Read lazily because gimple_codegen imports this module at
    load time.
    """
    import gimple_codegen
    from mojo.middle.rt_sigs import RT_SIGS
    return (frozenset(gimple_codegen.GimpleGen._KNOWN_SIGS) | frozenset(RT_SIGS)
            | frozenset(gimple_codegen._RUNTIME_FUNCS))


def _known_names() -> frozenset:
    import module_loader
    return (frozenset(dir(_py_builtins)) | _RUNTIME_NAMES
            | _compiler_runtime_names()
            | _stdlib_declared_names(module_loader.STDLIB_PATH))


class _Scan:
    """One walk of the module AST: the names it binds, and every read."""

    def __init__(self):
        self.bound: set = set()
        self.reads: list = []   # IdentExpr nodes in read position
        self.wildcard = False
        self._unchecked = 0     # >0 while inside an _UNCHECKED_READ_FIELDS subtree

    def _strs(self, s: str):
        # A string field may hold a dotted module path (`import a.b`), or a
        # target list (`a, b`): every identifier it spells is bound.
        self.bound.update(_IDENT_RE.findall(s))

    def _value(self, v, binding: bool, strs: bool):
        if isinstance(v, str):
            if strs:
                self._strs(v)
        elif isinstance(v, (list, tuple)):
            for x in v:
                self._value(x, binding, strs)
        elif isinstance(v, dict):
            for k, x in v.items():
                if strs and isinstance(k, str):
                    self._strs(k)
                self._value(x, False, strs)
        elif dataclasses.is_dataclass(v):
            self._node(v, binding)

    def _node(self, node, binding: bool = False):
        if isinstance(node, N.IdentExpr):
            if binding:
                self.bound.add(node.name)
            elif not self._unchecked and node.line > 0:
                # line 0 is a synthesized node, not a source read.
                self.reads.append(node)
            return
        if binding and isinstance(node, (N.TupleExpr, N.ListExpr,
                                         N.TupleLiteral, N.ListLiteral)):
            self._value(node.elements, True, False)
            return
        if binding and isinstance(node, N.CallExpr):
            # `var (p, q) = ...` parses as a call target: its arguments are
            # the declared names, the callee is the `var` keyword.
            self._value(node.args, True, False)
            return
        if isinstance(node, N.FromImportStmt) and node.wildcard:
            self.wildcard = True
        strs = not isinstance(node, _NON_NAME_NODES)
        for f in dataclasses.fields(node):
            child = getattr(node, f.name)
            if f.name in _NON_BINDING_STR_FIELDS:
                # An attribute name is neither a read nor a declaration.
                if isinstance(child, str):
                    continue
            unchecked = f.name in _UNCHECKED_READ_FIELDS
            self._unchecked += unchecked
            try:
                self._value(child, f.name in _BINDING_FIELDS, strs)
            finally:
                self._unchecked -= unchecked


def unknown_reads(stmts: list) -> list:
    """The IdentExpr reads in `stmts` that no name in scope can supply, in
    source order. An empty list for a module with a wildcard import."""
    scan = _Scan()
    scan._value(list(stmts or []), False, True)
    if scan.wildcard:
        return []
    known = scan.bound | _known_names()
    return sorted((n for n in scan.reads if n.name not in known),
                  key=lambda n: (n.line, n.col))


def format_diagnostic(filename: str, src: str, node) -> str:
    """One error in the modular layout: location, message, the source line,
    and a caret run under the name."""
    name = node.name
    lines = src.split('\n')
    text = lines[node.line - 1] if 0 < node.line <= len(lines) else ''
    label = filename or '<source>'
    return (f"{label}:{node.line}:{node.col}: error: "
            f"use of unknown declaration '{name}'\n"
            f"{text}\n"
            f"{' ' * max(node.col - 1, 0)}^{'~' * (len(name) - 1)}")


def check_module(stmts: list, src: str, filename: str = "") -> None:
    """Raise SyntaxError listing every unknown-declaration read in `stmts`.

    This is Modular's MOJO diagnostic. A Python source (`.py`) resolves names
    lazily: a read of an unbound name is a runtime NameError, and a function
    that never runs it (dead code after a `raise`, a branch never taken) is a
    valid program. Real: CPython's Tools/c-analyzer/c_common/tables.py reads
    the undefined `_resolve_column` after an unconditional `raise`, and the
    check turned that file's build into a compile error. Python sources are
    therefore not checked.
    """
    if filename.endswith('.py'):
        return
    reads = unknown_reads(stmts)
    if not reads:
        return
    raise SyntaxError("\n".join(format_diagnostic(filename, src, n)
                                for n in reads))
