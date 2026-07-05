"""AST-to-AST rewrite pass, run once between parsing and gimple_codegen.py.

Purpose: gimple_codegen.py's expression lowering has accumulated a growing
pile of `if isinstance(...) and name == '...':` blocks that recognize one
specific Python idiom (e.g. `os.path.basename(x)`) and emit the concrete
runtime call it really means. That's the right *strategy* for a target with
no runtime reflection (see BACKLOG-CODEGEN.md and mojo_obj_getattr's stub —
there is genuinely no dynamic module/attribute object to look this up in at
runtime), but doing it inline in the lowering pass means the rewrite logic
and the C-emission logic are the same code, and every new idiom is another
manually-placed elif deep in a 10,000-line file.

This module gives that strategy a proper home: a declarative rule table
(pattern -> replacement) matched against the AST *before* codegen ever sees
it. Codegen then only has to handle the rewritten (already-native) shape.

This file is itself part of the self-hosted compiler pipeline (it's imported
by gimple_codegen.py, which gets compiled along with everything else during
`make bootstrap`), so it deliberately sticks to the subset of Python already
proven to self-host elsewhere in this codebase: no generators, no tuple-keyed
dicts, no annotated `self.` attributes, no `__slots__`.

Matching performance: rules are compiled once into a shared discrimination
trie (see build_trie), so testing a node against N rules costs roughly
O(depth of the deepest pattern that shares a prefix with this node), not
O(N). Two rules with a common head shape (e.g. every `os.environ.*` rule)
share that shape's trie nodes; an unrelated rule added later costs the walk
nothing until they diverge. This is the same idea as a term/discrimination
index in a rewriting engine (as in `matchpy`, or first-order term indexing
in resolution provers): index the literal, structural prefix of each
pattern; anything under a wildcard is deferred to a final per-candidate
verification (`match_pattern`), which also handles variable bindings,
non-linear repeated variables, and variadic argument lists.
"""
import dataclasses

from mojo_compiler import (
    IdentExpr, BinaryOp, CallExpr, MemberExpr, SubscriptExpr, TernaryExpr,
    AssignStmt, ExprStmt, IntLiteral, UnaryOp,
)

# Position metadata every AST node carries; never part of a pattern's shape.
_SKIP_FIELDS = frozenset({'line', 'col'})


# ─── Pattern primitives ────────────────────────────────────────────────────

class Var:
    """Binds whatever subtree is here to `name`. A repeated name elsewhere in
    the same pattern requires the two subtrees to be structurally equal
    (non-linear pattern, checked in match_pattern)."""
    def __init__(self, name):
        self.name = name


class Lit:
    """Exact-value match (e.g. a member name that must literally be 'environ')."""
    def __init__(self, value):
        self.value = value


class AnyType:
    """Matches any subtree, binds nothing."""
    def __init__(self):
        pass

ANY = AnyType()


class Optional_:
    """Seq tail marker: zero or one trailing element, bound to `name` if present."""
    def __init__(self, name):
        self.name = name


class Seq:
    """Pattern for a list-typed field: fixed leading item patterns, plus an
    optional tail (Optional_(name) for 0-or-1, or a bare str for "bind the
    rest, however many, as a list")."""
    def __init__(self, *items, tail=None):
        self.items = items
        self.tail = tail


class Node:
    """Pattern for a dataclass AST node: its type name plus a pattern per
    field. Fields not mentioned are unconstrained (not checked at all)."""
    def __init__(self, node_type, **fields):
        self.type = node_type
        self.fields = fields


def _as_pattern(x):
    """Bare Python literals (str/int/bool/None) are shorthand for Lit(x)."""
    if isinstance(x, Var) or isinstance(x, Lit) or isinstance(x, AnyType) \
            or isinstance(x, Node) or isinstance(x, Seq):
        return x
    return Lit(x)


class P:
    """Convenience constructors mirroring the real AST node types."""
    var = Var
    lit = Lit
    any = ANY
    seq = Seq
    optional = Optional_

    @staticmethod
    def ident(name):
        return Node('IdentExpr', name=_as_pattern(name))

    @staticmethod
    def member(obj, member):
        return Node('MemberExpr', obj=_as_pattern(obj), member=_as_pattern(member))

    @staticmethod
    def call(func, args=None):
        if args is None:
            return Node('CallExpr', func=_as_pattern(func))
        return Node('CallExpr', func=_as_pattern(func), args=args)

    @staticmethod
    def subscript(obj, index):
        return Node('SubscriptExpr', obj=_as_pattern(obj), index=_as_pattern(index))

    @staticmethod
    def binop(op, left, right):
        return Node('BinaryOp', op=_as_pattern(op), left=_as_pattern(left), right=_as_pattern(right))

    @staticmethod
    def in_(left, right):
        return P.binop('in', left, right)


# ─── Rules ─────────────────────────────────────────────────────────────────

class RewriteRule:
    def __init__(self, name, pattern, build, guard=None):
        self.name = name
        self.pattern = pattern
        self.build = build          # bindings(dict) -> replacement AST node
        self.guard = guard          # optional bindings(dict) -> bool


# ─── Structural match (full verification of a candidate rule) ────────────

# type(x).__name__ has no real backing at runtime here (mojo_type() is a
# stub, same situation as mojo_obj_getattr — see the module docstring and
# the os.environ bug hunt this rewriter grew out of). Every place that needs
# "which AST node class is this" uses this literal isinstance chain instead,
# the same idiom mojo_compiler.py/gimple_codegen.py already use for AST
# dispatch. Only covers the node classes any *pattern* actually references
# today (P.ident/member/call/subscript/binop) — extend this list when a new
# pattern constructor needs to match on a node type not listed here.
def _node_type_name(node):
    if isinstance(node, IdentExpr):
        return 'IdentExpr'
    if isinstance(node, MemberExpr):
        return 'MemberExpr'
    if isinstance(node, CallExpr):
        return 'CallExpr'
    if isinstance(node, SubscriptExpr):
        return 'SubscriptExpr'
    if isinstance(node, BinaryOp):
        return 'BinaryOp'
    return None


def _ast_eq(a, b):
    if dataclasses.is_dataclass(a) and dataclasses.is_dataclass(b):
        if _node_type_name(a) != _node_type_name(b):
            return False
        for f in dataclasses.fields(a):
            if f.name in _SKIP_FIELDS:
                continue
            if not _ast_eq(getattr(a, f.name), getattr(b, f.name)):
                return False
        return True
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        for i in range(len(a)):
            if not _ast_eq(a[i], b[i]):
                return False
        return True
    return a == b


def match_pattern(pat, term, bindings):
    if bindings is None:
        return None
    if isinstance(pat, Var):
        if pat.name in bindings:
            if _ast_eq(bindings[pat.name], term):
                return bindings
            return None
        bindings[pat.name] = term
        return bindings
    if isinstance(pat, AnyType):
        return bindings
    if isinstance(pat, Lit):
        if term == pat.value:
            return bindings
        return None
    if isinstance(pat, Node):
        if not dataclasses.is_dataclass(term) or _node_type_name(term) != pat.type:
            return None
        for fname in pat.fields:
            if not hasattr(term, fname):
                return None
            bindings = match_pattern(pat.fields[fname], getattr(term, fname), bindings)
            if bindings is None:
                return None
        return bindings
    if isinstance(pat, Seq):
        if not isinstance(term, list) or len(term) < len(pat.items):
            return None
        for i in range(len(pat.items)):
            bindings = match_pattern(pat.items[i], term[i], bindings)
            if bindings is None:
                return None
        rest = term[len(pat.items):]
        if pat.tail is None:
            if len(rest) == 0:
                return bindings
            return None
        if isinstance(pat.tail, Optional_):
            if len(rest) == 0:
                return bindings
            if len(rest) == 1:
                bindings[pat.tail.name] = rest[0]
                return bindings
            return None
        bindings[pat.tail] = rest
        return bindings
    return None


# ─── Discrimination trie (shared-prefix indexing over the ruleset) ────────
# Trie edges are keyed by a plain string (not a tuple) so this stays inside
# the self-hostable dict-key subset: "<path>|<TYPE-or-LIT>:<value>".

class TrieNode:
    def __init__(self):
        self.edges = {}      # str key -> TrieNode (see _edge_key)
        self.edge_paths = {} # str key -> path (list of field names), to re-check against a term
        self.wild = None     # TrieNode, if any rule has a wildcard at this position
        self.rules = []


def _path_str(path):
    return '.'.join(path)


def _token_str(kind, value):
    return kind + ':' + str(value)


def _edge_key(path, kind, value):
    return _path_str(path) + '|' + _token_str(kind, value)


def _collect_discriminators(pat, path, out):
    """Append (path, kind, value) triples for the literal/structural prefix of
    a pattern — stops descending at a Var/Any/Seq boundary; that content is
    only checked later, in match_pattern, against a concrete candidate."""
    if isinstance(pat, Node):
        out.append((path, 'TYPE', pat.type))
        for fname in pat.fields:
            _collect_discriminators(pat.fields[fname], path + [fname], out)
    elif isinstance(pat, Lit):
        out.append((path, 'LIT', pat.value))
    elif isinstance(pat, Var) or isinstance(pat, AnyType) or isinstance(pat, Seq):
        out.append((path, 'WILD', None))
    else:
        out.append((path, 'LIT', pat))


def _term_discriminator(term, path):
    """The same-shaped (kind, value) for a concrete AST node at an absolute
    field path from the match root (every path a rule indexes on is fixed at
    compile time, so this never inspects fields no rule cares about)."""
    node = term
    for fname in path:
        if not dataclasses.is_dataclass(node):
            return ('MISS', None)
        if not hasattr(node, fname):
            return ('MISS', None)
        node = getattr(node, fname)
    if dataclasses.is_dataclass(node):
        return ('TYPE', _node_type_name(node))
    return ('LIT', node)


def build_trie(rules):
    root = TrieNode()
    for rule in rules:
        discs = []
        _collect_discriminators(rule.pattern, [], discs)
        node = root
        for path, kind, value in discs:
            if kind == 'WILD':
                if node.wild is None:
                    node.wild = TrieNode()
                node = node.wild
            else:
                key = _edge_key(path, kind, value)
                if key not in node.edges:
                    node.edges[key] = TrieNode()
                    node.edge_paths[key] = path
                node = node.edges[key]
        node.rules.append(rule)
    return root


def candidate_rules(term, trie):
    """One pass over the trie, guided by `term`: at each frontier node, follow
    every literal edge whose path/token the term actually satisfies, plus the
    wildcard edge unconditionally. Cost is bounded by the trie's shape, not
    by how many rules were registered."""
    frontier = [trie]
    found = list(trie.rules)
    while len(frontier) > 0:
        nxt = []
        for node in frontier:
            for key in node.edges:
                path = node.edge_paths[key]
                child = node.edges[key]
                kind, value = _term_discriminator(term, path)
                if _edge_key(path, kind, value) == key:
                    nxt.append(child)
                    found = found + child.rules
            if node.wild is not None:
                nxt.append(node.wild)
                found = found + node.wild.rules
        frontier = nxt
    return found


# ─── Driver ────────────────────────────────────────────────────────────────

_MAX_REWRITES_PER_NODE = 4


def try_rewrite(term, trie):
    """Return a replacement node if some rule fully matches `term`, else None."""
    for rule in candidate_rules(term, trie):
        bindings = match_pattern(rule.pattern, term, {})
        if bindings is None:
            continue
        if rule.guard is not None and not rule.guard(bindings):
            continue
        return rule.build(bindings)
    return None


def _rewrite_assign_stmt(node, trie):
    """AssignStmt.target is an lvalue — the ordinary expression rules (which
    only make sense for value positions) must never run on it directly. The
    one lvalue pattern this ruleset needs, `os.environ[key] = value`, is
    handled here as its own statement-level rewrite instead of being folded
    into the generic per-node walk below."""
    bindings = match_pattern(_OS_ENVIRON_ASSIGN_TARGET, node.target, {})
    if bindings is not None:
        value = _rewrite_node(node.value, trie)
        return ExprStmt(value=CallExpr(
            func=IdentExpr(name='setenv'),
            args=[bindings['key'], value, IntLiteral(value=1)],
        ))
    node.value = _rewrite_node(node.value, trie)
    return node


def _rewrite_node(node, trie):
    if not dataclasses.is_dataclass(node):
        return node
    if isinstance(node, AssignStmt):
        return _rewrite_assign_stmt(node, trie)
    for f in dataclasses.fields(node):
        if f.name in _SKIP_FIELDS:
            continue
        val = getattr(node, f.name)
        if dataclasses.is_dataclass(val):
            setattr(node, f.name, _rewrite_node(val, trie))
        elif isinstance(val, list):
            for i in range(len(val)):
                if dataclasses.is_dataclass(val[i]):
                    val[i] = _rewrite_node(val[i], trie)
    count = 0
    while count < _MAX_REWRITES_PER_NODE:
        replacement = try_rewrite(node, trie)
        if replacement is None or replacement is node:
            break
        node = replacement
        if not dataclasses.is_dataclass(node):
            break
        count += 1
    return node


def rewrite_module(stmts, trie):
    """Bottom-up rewrite of every statement in a parsed module, in place."""
    for i in range(len(stmts)):
        stmts[i] = _rewrite_node(stmts[i], trie)
    return stmts


# ─── Registered rules ──────────────────────────────────────────────────────
# `os.environ` has no runtime object behind it (real Mojo's stdlib has no
# such thing either — see std/os/env.mojo: only free functions getenv/
# setenv/unsetenv). These rules lower the Python idiom to what it actually
# is on this target: a direct call to mojo_c_getenv/setenv. (mojo_c_getenv,
# not mojo_getenv/bare getenv: the stdlib's own `getenv` function — a real
# `def getenv(...)` in env.mojo — is itself renamed to `mojo_getenv` by the
# existing reserved-name convention, so calling by that name here would
# collide with the stdlib's own compiled definition.)

_OS_ENVIRON = P.member(obj=P.ident('os'), member=Lit('environ'))
_OS_ENVIRON_ASSIGN_TARGET = P.subscript(obj=_OS_ENVIRON, index=Var('key'))


def _not_null(expr):
    """True iff `expr` (a char *) is non-NULL. Deliberately *not*
    `BinaryOp('!=', expr, IdentExpr('None'))`: codegen's `==`/`!=` lowering
    treats any comparison with a char* operand as a string-equality check
    and routes it through strcmp() unconditionally (gimple_codegen.py's
    `uses_str` in the BinaryOp lowering) — strcmp on a NULL getenv() result
    (the common case: the variable isn't set) segfaults. `not`/truthiness on
    a pointer type instead goes through the real, correct null-check path
    (`_lower_UnaryOp`/`_ensure_bool_cond`: `(int64_t)ptr == 0`), so double
    negation gets a real not-null test without ever emitting that `!=`."""
    return UnaryOp(op='not', operand=UnaryOp(op='not', operand=expr))


def _build_environ_get(b):
    if 'default' not in b:
        return CallExpr(func=IdentExpr(name='mojo_c_getenv'), args=[b['key']])
    return TernaryExpr(
        condition=_not_null(CallExpr(func=IdentExpr(name='mojo_c_getenv'), args=[b['key']])),
        then_val=CallExpr(func=IdentExpr(name='mojo_c_getenv'), args=[b['key']]),
        else_val=b['default'],
    )


def _build_environ_subscript(b):
    return CallExpr(func=IdentExpr(name='mojo_c_getenv'), args=[b['key']])


def _build_platform_system(b):
    return CallExpr(func=IdentExpr(name='mojo_platform_system'), args=[])


def _build_platform_machine(b):
    return CallExpr(func=IdentExpr(name='mojo_platform_machine'), args=[])


def _build_environ_contains(b):
    return _not_null(CallExpr(func=IdentExpr(name='mojo_c_getenv'), args=[b['key']]))


def _build_subprocess_run(b):
    # capture_output/text/check/timeout kwargs are accepted syntactically
    # (the pattern below doesn't constrain `kwargs`, so it matches regardless
    # of what's passed) but not distinguished — every call site in this
    # codebase passes capture_output=True, text=True, and `check` is only
    # ever used inside a try/except that already tolerates a non-raising
    # failure. See BACKLOG-CODEGEN.md for the real gap (no CalledProcessError).
    return CallExpr(func=IdentExpr(name='mojo_subprocess_run'),
                     args=[b['cmd'], IntLiteral(value=1)])


def _build_subprocess_returncode(b):
    return CallExpr(func=IdentExpr(name='mojo_subprocess_returncode'), args=[b['x']])


def _build_subprocess_stdout(b):
    return CallExpr(func=IdentExpr(name='mojo_subprocess_stdout'), args=[b['x']])


def _build_subprocess_stderr(b):
    return CallExpr(func=IdentExpr(name='mojo_subprocess_stderr'), args=[b['x']])


def _build_sys_stdin_read(b):
    return CallExpr(func=IdentExpr(name='mojo_stdin_read'), args=[])


# re.MULTILINE etc. are plain integer flag constants in real Python (values
# per cpython's re module: I=2, M=8, S=16, X=64). `import re` binds `re` to
# a bare marker (see _gen_stmt_ImportStmt), so `re.MULTILINE` has no runtime
# object to look the flag up on — these rules give the constants their real
# values directly. NOTE: the regex engine backing this runtime (see
# mojo_re_sub_fn, runtime/mojo_runtime.c) hardcodes REG_EXTENDED and doesn't
# actually consume a flags argument yet, so a pattern compiled `re.MULTILINE`
# won't behave differently at runtime — this only fixes the crash evaluating
# the constant itself. See BACKLOG-CODEGEN.md.
def _build_re_ignorecase(b): return IntLiteral(value=2)
def _build_re_multiline(b):  return IntLiteral(value=8)
def _build_re_dotall(b):     return IntLiteral(value=16)
def _build_re_verbose(b):    return IntLiteral(value=64)


def _not_sys_stream(b):
    """Guard for the .stdout/.stderr rules: `sys.stdout`/`sys.stderr` (real
    Python file objects, used throughout this codebase as `file=sys.stderr`)
    must not be reinterpreted as a subprocess result's captured output."""
    obj = b['x']
    return not (isinstance(obj, IdentExpr) and obj.name == 'sys')


RULES = [
    RewriteRule(
        name='os_environ_get',
        pattern=P.call(func=P.member(obj=_OS_ENVIRON, member=Lit('get')),
                       args=Seq(Var('key'), tail=Optional_('default'))),
        build=_build_environ_get,
    ),
    RewriteRule(
        name='os_environ_subscript',
        pattern=P.subscript(obj=_OS_ENVIRON, index=Var('key')),
        build=_build_environ_subscript,
    ),
    RewriteRule(
        name='os_environ_contains',
        pattern=P.in_(left=Var('key'), right=_OS_ENVIRON),
        build=_build_environ_contains,
    ),
    RewriteRule(
        name='subprocess_run',
        pattern=P.call(func=P.member(obj=P.ident('subprocess'), member=Lit('run')),
                       args=Seq(Var('cmd'))),
        build=_build_subprocess_run,
    ),
    RewriteRule(
        name='subprocess_returncode',
        pattern=P.member(obj=Var('x'), member=Lit('returncode')),
        build=_build_subprocess_returncode,
    ),
    RewriteRule(
        name='subprocess_stdout',
        pattern=P.member(obj=Var('x'), member=Lit('stdout')),
        build=_build_subprocess_stdout,
        guard=_not_sys_stream,
    ),
    RewriteRule(
        name='subprocess_stderr',
        pattern=P.member(obj=Var('x'), member=Lit('stderr')),
        build=_build_subprocess_stderr,
        guard=_not_sys_stream,
    ),
    RewriteRule(
        name='sys_stdin_read',
        pattern=P.call(func=P.member(obj=P.member(obj=P.ident('sys'), member=Lit('stdin')),
                                      member=Lit('read'))),
        build=_build_sys_stdin_read,
    ),
    RewriteRule(name='re_ignorecase', pattern=P.member(obj=P.ident('re'), member=Lit('IGNORECASE')),
                build=_build_re_ignorecase),
    RewriteRule(name='re_i',          pattern=P.member(obj=P.ident('re'), member=Lit('I')),
                build=_build_re_ignorecase),
    RewriteRule(name='re_multiline',  pattern=P.member(obj=P.ident('re'), member=Lit('MULTILINE')),
                build=_build_re_multiline),
    RewriteRule(name='re_m',          pattern=P.member(obj=P.ident('re'), member=Lit('M')),
                build=_build_re_multiline),
    RewriteRule(name='re_dotall',     pattern=P.member(obj=P.ident('re'), member=Lit('DOTALL')),
                build=_build_re_dotall),
    RewriteRule(name='re_s',          pattern=P.member(obj=P.ident('re'), member=Lit('S')),
                build=_build_re_dotall),
    RewriteRule(name='re_verbose',    pattern=P.member(obj=P.ident('re'), member=Lit('VERBOSE')),
                build=_build_re_verbose),
    RewriteRule(name='re_x',          pattern=P.member(obj=P.ident('re'), member=Lit('X')),
                build=_build_re_verbose),
    RewriteRule(
        name='platform_system',
        pattern=P.call(func=P.member(obj=P.ident('platform'), member=Lit('system'))),
        build=_build_platform_system,
    ),
    RewriteRule(
        name='platform_machine',
        pattern=P.call(func=P.member(obj=P.ident('platform'), member=Lit('machine'))),
        build=_build_platform_machine,
    ),
]

TRIE = build_trie(RULES)


def rewrite(stmts):
    """Entry point: run the full registered ruleset over a parsed module."""
    return rewrite_module(stmts, TRIE)
