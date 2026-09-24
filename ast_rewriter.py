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

from fire_compiler import (
    IdentExpr, BinaryOp, CallExpr, MemberExpr, SubscriptExpr, TernaryExpr,
    AssignStmt, ExprStmt, IntLiteral, UnaryOp, _as_str, _as_list, _as_dict,
)

# Position metadata every AST node carries; never part of a pattern's shape.
_SKIP_FIELDS = frozenset({'line', 'col'})


# ─── Pattern primitives ────────────────────────────────────────────────────

class Var:
    """Binds whatever subtree is here to `name`. A repeated name elsewhere in
    the same pattern requires the two subtrees to be structurally equal
    (non-linear pattern, checked in match_pattern)."""
    def __init__(self, name):
        # `_as_str`: same fix as `Node.type` (see its own comment) for the
        # same reason -- `Var` is a plain class, not a `@dataclass`, and
        # `self.name` (used later as a `bindings` DICT KEY in
        # match_pattern) kept the erased int64_t ctype otherwise. A
        # mistyped key there meant `bindings['key']`/`'default' not in
        # bindings` in the RULE BUILD functions (_build_environ_get, ...)
        # never found what match_pattern had actually stored, silently
        # failing the whole rewrite for a rule that had JUST matched.
        self.name = _as_str(name)


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
        # `_as_str` — same reason as `Var.__init__`/`Node.type` above.
        self.name = _as_str(name)


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
    def __init__(self, node_type: str, fields: list):
        # Explicit `: str` on the parameter, not decoration: unannotated,
        # the self-hosted backend inferred `node_type`'s (hence `self.
        # type`'s) ctype from usage alone -- the only use in this body is
        # a plain `self.type = node_type` store, no string operation to
        # reveal it -- and defaulted it to int64_t. Every `Node('CallExpr',
        # ...)`/`Node('MemberExpr', ...)` construction site then stored its
        # literal type-name STRING through that int64_t field (the pointer
        # value reinterpreted as a plain integer), so every later read of
        # `pat.type` (_collect_discriminators building the trie,
        # _node_type_name's equality checks) saw a decimal address instead
        # of "CallExpr"/"MemberExpr" -- corrupting every trie edge key
        # build_trie ever built, so `candidate_rules` matched zero rules
        # for any real term and EVERY registered rewrite (os.environ.get(
        # ...), sys.stdin.read(), subprocess.run(...), ...) silently
        # never fired once self-hosted. Root-caused via a --dump-full
        # fire.py sibling-import module drop (gimple_gen_coro.py's own
        # `os.environ.get(_ENV, _MODE)` left un-rewritten, raising an
        # uncaught AttributeError once codegen tried to treat the bare
        # `os` identifier as a real object) and reproduced standalone with
        # a 2-line `import os` + `os.environ.get('X')`.
        #
        # `fields: list` of `[name, pattern]` pairs, not a dict (and not
        # `**fields`): BOTH variadic-kwargs collection AND a plain 2+-key
        # dict LITERAL silently kept only the FIRST entry once self-
        # hosted (a separate, deeper bug from the dict-KEY-typing issues
        # elsewhere in this file — this one lost entries outright,
        # confirmed by iterating a `{'obj': X, 'member': Y}` literal and
        # seeing only 'obj' ever visited). `match_pattern`'s `for fname
        # in pat.fields:` loop then never even attempted to check the
        # second-and-later fields (`member`, `args`, ...) of any 2+-field
        # pattern (MemberExpr, CallExpr-with-args, BinaryOp), so a rule
        # matching correctly on just its FIRST field looked like a full
        # match without ever verifying the rest — silently wrong, not a
        # visible failure. A plain list of pairs, indexed by position
        # instead of dict key, sidesteps whichever container-literal
        # mechanism was losing entries. Every `P.*` constructor below now
        # builds this list explicitly.
        self.type = _NODE_TYPE_CODES.get(node_type, 0)
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
        return Node('IdentExpr', [['name', _as_pattern(name)]])

    @staticmethod
    def member(obj, member):
        return Node('MemberExpr', [['obj', _as_pattern(obj)], ['member', _as_pattern(member)]])

    @staticmethod
    def call(func, args=None):
        if args is None:
            return Node('CallExpr', [['func', _as_pattern(func)]])
        return Node('CallExpr', [['func', _as_pattern(func)], ['args', args]])

    @staticmethod
    def subscript(obj, index):
        return Node('SubscriptExpr', [['obj', _as_pattern(obj)], ['index', _as_pattern(index)]])

    @staticmethod
    def binop(op, left, right):
        return Node('BinaryOp', [['op', _as_pattern(op)], ['left', _as_pattern(left)], ['right', _as_pattern(right)]])

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
# the same idiom fire_compiler.py/gimple_codegen.py already use for AST
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


# Small int codes, not the type-name strings themselves: `Node` (below) is
# a plain class, not a `@dataclass`, and this compiler's self-hosted
# struct-field-type tracking is geared toward dataclass fields -- a plain
# class's own string-typed instance attribute (`Node.type`) kept reading
# back as an erased int64_t (a decimal address) no amount of `_as_str()`/
# annotation at the write OR read site recovered, corrupting every trie
# edge key built from it. A small int survives the same self-hosted
# machinery just fine (this codebase relies on int64_t comparisons
# constantly), so `Node.type`/`_node_type_code` deal in these instead of
# real strings, sidestepping the problem rather than fixing the
# underlying field-read.
_NODE_TYPE_IDENT = 1
_NODE_TYPE_MEMBER = 2
_NODE_TYPE_CALL = 3
_NODE_TYPE_SUBSCRIPT = 4
_NODE_TYPE_BINOP = 5
_NODE_TYPE_CODES = {
    'IdentExpr': _NODE_TYPE_IDENT,
    'MemberExpr': _NODE_TYPE_MEMBER,
    'CallExpr': _NODE_TYPE_CALL,
    'SubscriptExpr': _NODE_TYPE_SUBSCRIPT,
    'BinaryOp': _NODE_TYPE_BINOP,
}


def _node_type_code(node):
    if isinstance(node, IdentExpr):
        return _NODE_TYPE_IDENT
    if isinstance(node, MemberExpr):
        return _NODE_TYPE_MEMBER
    if isinstance(node, CallExpr):
        return _NODE_TYPE_CALL
    if isinstance(node, SubscriptExpr):
        return _NODE_TYPE_SUBSCRIPT
    if isinstance(node, BinaryOp):
        return _NODE_TYPE_BINOP
    return 0


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


def _match_one_field(field, term, bindings):
    """Verify a single (fname, fpat) pair against `term`, recursing into
    `match_pattern`."""
    fname = _as_str(field[0])
    fpat = field[1]
    if not hasattr(term, fname):
        return None
    fval = getattr(term, fname)
    # `isinstance(fval, str)` + `_as_str`, same recovery as
    # `_term_discriminator`'s own path-walk: a LEAF field access
    # (IdentExpr.name, MemberExpr.member, ...) goes through the same
    # generic/dynamic `getattr` dispatch as everywhere else in this
    # file, so a real string field value arrives with the erased
    # int64_t ctype -- `match_pattern`'s `Lit` branch's `term ==
    # pat.value` then compared a decimal address against the real
    # literal string and never matched, even though the discriminator-
    # level check (which has this same recovery) confirmed the value
    # WAS genuinely e.g. "os". Non-string field values (sub-nodes,
    # lists) are untouched.
    if isinstance(fval, str):
        fval = _as_str(fval)
    elif isinstance(fpat, Seq):
        # Same recovery, keyed off the PATTERN's own type rather than
        # `isinstance(fval, list)`: a list-typed field (`args`) arrives
        # through the identical generic/dynamic `getattr` as a string
        # one, and `isinstance(fval, list)` on that erased value was
        # JUST as unreliable as `isinstance(fval, str)` would have been
        # (confirmed by direct instrumentation: `term_is_list=False` for
        # a genuinely-real one-element args list). Only a `Seq` pattern
        # ever matches against a list-shaped field in this rule set, so
        # the pattern's own type is a reliable signal here instead.
        fval = _as_list(fval)
    return match_pattern(fpat, fval, bindings)


def _match_node_fields(fields, term, bindings):
    """Verify every (fname, fpat) pair in a Node pattern's `fields` list
    against `term`'s corresponding attributes.

    Deliberately unrolled (no `for`/`while` loop over `fields`), not a
    style choice: a loop here whose body (transitively, through
    `_match_one_field`) calls back into `match_pattern` -- which can
    itself re-enter this exact function for a nested Node field -- only
    ever ran its FIRST iteration once self-hosted, silently. No error:
    `range(len(fields))`'s length check, `fname`, `hasattr` were all
    individually confirmed correct by direct instrumentation, and the
    recursive `match_pattern` call for field 0 even succeeded -- the
    loop simply never reached `_fi=1` for any 2-field pattern
    (MemberExpr, CallExpr-with-args, BinaryOp), no matter which function
    the loop lived in (tried both inlined directly in `match_pattern`'s
    own Node branch and split into this dedicated helper -- identical
    failure either way). Every pattern in this file's actual RULES has
    at most 3 fields (see P.ident/member/call/subscript/binop), so a
    bounded, loop-free unroll sidesteps the self-hosted loop+mutual-
    recursion interaction entirely rather than chasing it further."""
    n = len(fields)
    if n >= 1:
        bindings = _match_one_field(fields[0], term, bindings)
        if bindings is None:
            return None
    if n >= 2:
        bindings = _match_one_field(fields[1], term, bindings)
        if bindings is None:
            return None
    if n >= 3:
        bindings = _match_one_field(fields[2], term, bindings)
        if bindings is None:
            return None
    return bindings


def match_pattern(pat, term, bindings):
    if bindings is None:
        return None
    if isinstance(pat, Var):
        # `_as_str` at the read, not just at Var.__init__'s write — same
        # lesson as `Node.type`/`discs[_di][n]` elsewhere in this file:
        # a plain class's own field read needs the re-assert at BOTH
        # ends, an assignment-time cast alone does not survive.
        _vn = _as_str(pat.name)
        if _vn in bindings:
            if _ast_eq(bindings[_vn], term):
                return bindings
            return None
        bindings[_vn] = term
        return bindings
    if isinstance(pat, AnyType):
        return bindings
    if isinstance(pat, Lit):
        if term == pat.value:
            return bindings
        return None
    if isinstance(pat, Node):
        if not dataclasses.is_dataclass(term) or _node_type_code(term) != pat.type:
            return None
        return _match_node_fields(pat.fields, term, bindings)
    if isinstance(pat, Seq):
        # NOTE (still open, see selfhost-dump-full-module-drop.md):
        # `match_pattern`'s own `term` parameter is shared across every
        # call site in this file (dataclass nodes, strings, ints, None,
        # lists, ...), and self-hosted whole-program parameter-type
        # unification pulled its declared ctype down to the common
        # int64_t -- so `isinstance(term, list)` here reads false even
        # for a genuinely-real list argument (confirmed: a one-element
        # `args` list). Forcing it with `_as_list(term)` instead of
        # checking crashed with a real Bus error (SIGBUS) rather than
        # just mismatching -- the erased int64_t bits are apparently NOT
        # a valid MojoList* to begin with, so this needs the real
        # underlying `getattr`/list-field dispatch fixed, not just a
        # static-view cast at this point of use. Left as a safe,
        # non-matching `isinstance` check (falls through to the pattern
        # not matching, same as before) rather than risk a crash.
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
                # `_as_str` at the read — same lesson as the `Var` branch
                # above.
                bindings[_as_str(pat.tail.name)] = rest[0]
                return bindings
            return None
        bindings[_as_str(pat.tail)] = rest
        return bindings
    return None


# ─── Discrimination trie (shared-prefix indexing over the ruleset) ────────
# Trie edges are keyed by a plain string (not a tuple) so this stays inside
# the self-hostable dict-key subset: "<path>|<TYPE-or-LIT>:<value>".

class TrieNode:
    def __init__(self):
        # Explicit `dict[str, ...]` annotations, not bare `{}`: the
        # self-hosted backend infers an unannotated dict/set's key type
        # from usage, and without a pin here it defaulted `edges`'/
        # `edge_paths`' keys to int64_t (the same class of bug as
        # `_compiled_modules: set[str]`/`modules_to_compile: dict`
        # elsewhere in this codebase) -- `node.edges[key] = TrieNode()`
        # in build_trie and `node.edges[key]`/`node.edge_paths[key]` in
        # candidate_rules then disagreed on the STORAGE representation of
        # the same string `key`, so every lookup missed and
        # `candidate_rules` silently returned zero matching rules for
        # every real term, making every registered rewrite rule dead
        # once self-hosted (os.environ.get(...), sys.stdin.read(), ...).
        self.edges: dict[str, object] = {}      # str key -> TrieNode (see _edge_key)
        self.edge_paths: dict[str, object] = {} # str key -> path (list of field names), to re-check against a term
        self.wild = None     # TrieNode, if any rule has a wildcard at this position
        self.rules = []


def _path_str(path):
    return '.'.join(path)


# `_token_str`/`_edge_key` used to live here as shared helpers building
# "<path>|<kind>:<value>" trie edge keys. Removed: passing `kind`/`value`
# through a SEPARATE function's own unannotated parameters re-triggered
# self-hosted whole-program parameter-type unification across every OTHER
# call site of those helpers (including ones passing a non-string
# `value`), pulling the parameter's ctype back down to int64_t and
# truncating the bits no `_as_str()` wrap inside the function body could
# recover. Both call sites (build_trie, candidate_rules) now inline the
# same "<path>|<kind>:<value>" construction directly instead, removing
# the cross-call-site unification entirely. Root-caused via a --dump-full
# fire.py sibling-import module drop (gimple_gen_coro.py's own
# `os.environ.get(_ENV, _MODE)` left un-rewritten because this trie
# never matched a single rule once self-hosted) and reproduced standalone
# with a 2-line `import os` + `os.environ.get('X')`.


def _collect_discriminators(pat, path, out):
    """Append (path, kind, value_str) triples for the literal/structural
    prefix of a pattern — stops descending at a Var/Any/Seq boundary; that
    content is only checked later, in match_pattern, against a concrete
    candidate.

    `value_str` is ALWAYS a string (stringified here, at the point where
    it's still a properly-typed local, not left as an `object`): the
    (path, kind, value) triples used to store `value` heterogeneously
    (a real str for TYPE/most LIT entries, an int/None for others), which
    boxed it as int64_t on the self-hosted path — and no downstream
    `isinstance(value, str)`/`str(value)` recovery on a value already
    read back out of that heterogeneous list reliably un-boxed it (both
    dispatch off the STATIC int64_t ctype the list gave the element, not
    a true runtime check, for a value that was never a real tagged Mojo
    object in the first place — a plain string/int has no `__mojo_type_id`
    to check). Stringifying here, before the value goes anywhere
    heterogeneous, sidesteps the whole problem: `discs` (and every
    `_term_discriminator` result) is now uniformly `[list, str, str]`."""
    if isinstance(pat, Node):
        out.append((path, 'TYPE', str(pat.type)))
        for _fi in range(len(pat.fields)):
            fname = _as_str(pat.fields[_fi][0])
            fpat = pat.fields[_fi][1]
            _collect_discriminators(fpat, path + [fname], out)
    elif isinstance(pat, Lit):
        out.append((path, 'LIT', str(pat.value)))
    elif isinstance(pat, Var) or isinstance(pat, AnyType) or isinstance(pat, Seq):
        out.append((path, 'WILD', ''))
    else:
        out.append((path, 'LIT', str(pat)))


def _term_discriminator(term, path) -> list:
    """The same-shaped [kind, value] for a concrete AST node at an absolute
    field path from the match root (every path a rule indexes on is fixed at
    compile time, so this never inspects fields no rule cares about).

    A LIST, not a tuple: this function has multiple return statements
    shaped differently ('MISS'/None, 'TYPE'/str, 'LIT'/anything), and the
    self-hosted backend's whole-function return-type inference erased the
    tuple return itself to a single opaque int64_t instead of a real
    2-element product type -- every caller's `kind, value = ...` (and even
    `result[0]`/`result[1]` indexing into it) then read garbage off that
    erased value, so `_edge_key` built garbage trie edges and
    `candidate_rules` matched zero rules for any real term once
    self-hosted, permanently disabling every registered rewrite rule
    (os.environ.get(...), sys.stdin.read(), subprocess.run(...), ...).
    A list return, like this codebase's other `_as_X`-cast fixes for
    multi-return-path functions, keeps element types intact."""
    node = term
    _last_i = len(path) - 1
    for _pi in range(len(path)):
        fname = path[_pi]
        if not dataclasses.is_dataclass(node):
            return ['MISS', '']
        if not hasattr(node, fname):
            return ['MISS', '']
        # `_as_str` on ONLY the final hop's result, not every hop: an
        # intermediate hop's result must stay a real (dataclass-checkable)
        # struct pointer for the NEXT loop iteration's `dataclasses.
        # is_dataclass(node)` test, but the LAST hop, when it lands on a
        # scalar field (IdentExpr.name, MemberExpr.member, ...), goes
        # through the same generic/dynamic `getattr` dispatch as every
        # other boxed field read in this codebase — its result needs the
        # explicit static-view cast right here, at the point of the
        # `getattr` call itself, the same way `discs[_di][n]`-style
        # element extraction needed it (a later `isinstance(node, str)`
        # check on the ALREADY-erased value did not recover it: e.g.
        # IdentExpr.name == "os" printed as a decimal address even after
        # that isinstance guard).
        if _pi == _last_i:
            node = _as_str(getattr(node, fname))
        else:
            node = getattr(node, fname)
    if dataclasses.is_dataclass(node):
        return ['TYPE', str(_node_type_code(node))]
    if isinstance(node, str):
        return ['LIT', node]
    return ['LIT', str(node)]


def build_trie(rules: list):
    root = TrieNode()
    for rule in rules:
        discs = []
        _collect_discriminators(rule.pattern, [], discs)
        node = root
        # Index, don't unpack: `for path, kind, value in discs:` boxes the
        # 3-tuple elements to int64_t on the self-hosted path even though
        # `discs` itself is a properly-typed list (the established boxing
        # bug this codebase works around everywhere else — see e.g. the
        # AssignStmt-target zip comment in gimple_gen_resolve.py). A
        # mistyped `kind` made `kind == 'WILD'` always false (string
        # compare against an erased int64_t), so EVERY discriminator
        # -- including plain LIT/TYPE ones -- fell through to the
        # `_edge_key(path, kind, value)` branch with a garbage `kind`,
        # building a trie whose edge keys never matched any real term's
        # discriminator at lookup time (`candidate_rules`) -- silently
        # dropping EVERY registered rewrite rule (os.environ.get(...),
        # sys.stdin.read(), subprocess.run(...), ...) once self-hosted,
        # with no error: `try_rewrite` just always returned None. Found
        # via a --dump-full fire.py sibling-import module drop
        # (gimple_gen_coro.py's own `os.environ.get(_ENV, _MODE)` at line
        # 72 raising an uncaught AttributeError once un-rewritten, since
        # there is no real `os` runtime object for `mojo_obj_getattr` to
        # resolve `.environ` on) and reproduced standalone with a 2-line
        # `import os` + `os.environ.get('X')`.
        for _di in range(len(discs)):
            path = discs[_di][0]
            # `_as_str` directly on the extraction, not just on downstream
            # uses: `kind = discs[_di][1]` alone declared `kind`'s own C
            # local as int64_t (the erased element ctype), and no later
            # `_as_str()` wrap on an EXPRESSION using `kind` can retroactively
            # fix that already-wrong declaration -- `kind == 'WILD'` (an
            # int64_t-vs-char* compare) then always read false, printing a
            # stable, real value each run (the interned literal string's own
            # address, decimal-stringified) instead of "TYPE"/"WILD"/"LIT".
            kind = _as_str(discs[_di][1])
            value = _as_str(discs[_di][2])
            if kind == 'WILD':
                if node.wild is None:
                    node.wild = TrieNode()
                node = node.wild
            else:
                # Inlined `_edge_key`/`_token_str`, not a call: passing
                # `kind`/`value` through those functions' OWN unannotated
                # parameters re-triggers the exact same self-hosted
                # erasure this loop's `discs[_di][n]` indexing fix was
                # for -- whole-program parameter-type unification across
                # every OTHER call site of `_edge_key`/`_token_str`
                # (including ones passing a non-string `value`) pulled
                # the parameter's ctype back down to int64_t, and no
                # `_as_str()` wrap inside those functions' bodies can
                # recover bits already truncated at the call boundary.
                # Inlining removes the shared function (and its
                # cross-call-site unification) entirely.
                # `value` is now always a real string (_collect_
                # discriminators stringifies it before it ever goes into
                # the heterogeneous `discs` list — see that function's
                # docstring), so no `str(value)`/isinstance recovery is
                # needed here at all, just the same `_as_str` re-assert
                # on the extracted element `kind` gets above.
                key = _as_str(_path_str(path) + '|' + kind + ':' + value)
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
                # Index, don't unpack: `kind, value = _term_discriminator(...)`
                # boxes both elements to int64_t on the self-hosted path even
                # though `_term_discriminator` itself is a plain 2-tuple
                # return (the same class of erasure this codebase works
                # around everywhere else for list/dict element unpacking,
                # apparently also hitting a direct function-return tuple
                # unpack here) — a mistyped `kind`/`value` made `_edge_key`
                # build garbage keys, so `candidate_rules` matched zero
                # rules for every real term once self-hosted.
                _td = _term_discriminator(term, path)
                kind = _as_str(_td[0])
                value = _as_str(_td[1])
                # Inlined, not a call to `_edge_key` — see the identical
                # inlining + comment in build_trie above. `value` is
                # always a real string here too (_term_discriminator's
                # own docstring) — no str(value)/isinstance recovery
                # needed.
                _computed = _as_str(_path_str(path) + '|' + kind + ':' + value)
                if _computed == key:
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
        # NOTE (still open, see selfhost-dump-full-module-drop.md): this
        # exact statement (`os.environ['PATH'] = ...`, fire.py's own
        # line 27) is the ONLY real call site in this whole transitive
        # closure that ever reaches this branch with `bindings is not
        # None`, and `bindings['key']` crashes with a real SIGBUS inside
        # `mojo_list_get_int` (a huge garbage "index" derived from
        # hashing the string 'key') AFTER --dump-full's output is
        # already fully and correctly written -- the same opaque-
        # container-type-ambiguity bug this codebase already works
        # around for `self.var_types` elsewhere, but neither `_as_dict`
        # at this read site nor switching to `.get('key')` fixed it (the
        # latter actively regressed the output's byte-identity, so it's
        # reverted). Left as the plain, ORIGINAL `bindings['key']`
        # subscript: it still crashes on this one statement, but crashes
        # AFTER a byte-identical .ci is on disk, so the file itself is
        # correct even though the process's exit code is not.
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


def rewrite_module(stmts, trie) -> list:
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
# mojo_re_sub_fn, runtime/fire_runtime.c) hardcodes REG_EXTENDED and doesn't
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


def rewrite(stmts) -> list:
    """Entry point: run the full registered ruleset over a parsed module."""
    return rewrite_module(stmts, TRIE)


def rewrite_node(node) -> object:
    """Entry point for rewriting a single expression/statement node, not a
    whole module — needed for f-string interpolations, which gimple_codegen.py
    parses lazily at codegen time (from raw source text still embedded in a
    StringLiteral node) rather than upfront alongside the rest of the module,
    so they never pass through rewrite() otherwise."""
    return _rewrite_node(node, TRIE)
