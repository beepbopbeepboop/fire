"""Cross-module call-site evidence and method signatures (stage 5c, H2).

A per-file (`do_imports=False`) compile sees only its own module's call sites,
so an unannotated parameter that is only ever passed a string by an IMPORTER
is "no evidence" (rule 3) in the defining unit: the field it is stored into
keeps the bare `int64_t` word, and a `None` stored there prints `0` instead of
`None`. The importer cannot fix the definer's already-built object either.

This module is the missing channel: a SEPARATE, serializable registry of

  * call-site argument kinds, keyed `<module>.<Class>.<method>` (or
    `<module>.<func>`), parameter keyed `#<position>` or `<name>` for a
    keyword, in `mojo.middle.coro`'s kind alphabet (`'i'` int, `'d'` float,
    `'b'` bool, `'p'` str/bytes, `'w'` unknown pointer word);
  * per-module method/function signatures (`ret` C type + `params`) that the
    defining unit actually emitted, so an importer's extern can agree with the
    definition instead of re-guessing it from source text.

The evidence half is produced by a pre-pass over the whole build's sources
(`scan_module_calls`) and consumed where the defining module classifies its
parameters (`emit_infra.collect_param_value_obs`); the signature half is
published after a module compiles and consumed by the imported-method extern
path. Both are best-effort: a module with no published row behaves exactly as
before (today's rule-3 fallback).

Snapshot/seed exist because `build_stdlib_dylib.build` compiles modules in
WORKER PROCESSES: the parent's pre-pass publishes, a JSON-able snapshot is
handed to each job, and the job seeds its own process before compiling.
"""

from __future__ import annotations

# `<module>.<Class>.<method>` / `<module>.<func>` -> param key -> sorted kinds
CALL_KINDS: dict = {}
# module -> { "<Class>.<method>" / "<func>": {"ret": ctype, "params": [ctype]} }
SIGNATURES: dict = {}


def reset() -> None:
    CALL_KINDS.clear()
    SIGNATURES.clear()


def snapshot() -> dict:
    """A JSON-able copy for a worker process (no sets, no live objects)."""
    return {
        'kinds': {k: {p: list(v) for p, v in d.items()} for k, d in CALL_KINDS.items()},
        'sigs': {m: {k: {'ret': s.get('ret'),
                         'params': list(s.get('params') or []),
                         'ret_class': s.get('ret_class')}
                     for k, s in d.items()} for m, d in SIGNATURES.items()},
    }


def seed(snap) -> None:
    """Merge a `snapshot()` produced in another process. Idempotent."""
    if not isinstance(snap, dict):
        return
    for k, d in (snap.get('kinds') or {}).items():
        slot = CALL_KINDS.setdefault(k, {})
        for p, ks in (d or {}).items():
            slot.setdefault(p, [])
            for kind in (ks or []):
                if kind not in slot[p]:
                    slot[p].append(kind)
    for m, d in (snap.get('sigs') or {}).items():
        SIGNATURES.setdefault(m, {}).update(d or {})


def publish_call_kinds(entries) -> None:
    for key, pkey, kind in entries or ():
        slot = CALL_KINDS.setdefault(key, {})
        ks = slot.setdefault(pkey, [])
        if kind not in ks:
            ks.append(kind)


def call_kinds(key):
    """The published param-key -> kind-list map for one callee (a fresh dict)."""
    d = CALL_KINDS.get(key) or {}
    return {p: list(v) for p, v in d.items()}


def publish_signatures(module: str, sigs: dict) -> None:
    if module:
        SIGNATURES.setdefault(module, {}).update(sigs or {})


def signatures(module: str) -> dict:
    return dict(SIGNATURES.get(module) or {})


# ── the evidence pre-pass ────────────────────────────────────────────────────

def _name(x) -> str:
    return x if isinstance(x, str) else ('' if x is None else str(x))


def _module_name_for(path: str) -> str:
    import os
    base = os.path.splitext(os.path.basename(path))[0]
    return base


def _imports(stmts):
    """(from_imports: local -> (home module, original), module_aliases)."""
    from_imports: dict = {}
    aliases: dict = {}
    for s in stmts:
        cls = type(s).__name__
        if cls == 'FromImportStmt' and not getattr(s, 'wildcard', False):
            home = _name(getattr(s, 'module', ''))
            for pair in (getattr(s, 'names', None) or []):
                try:
                    nm, al = pair[0], pair[1]
                except Exception:
                    continue
                nm = _name(nm)
                local = _name(al) if al else nm
                if nm and home:
                    from_imports[local] = (home, nm)
        elif cls == 'ImportStmt':
            home = _name(getattr(s, 'module', ''))
            al = _name(getattr(s, 'alias', '')) or home.split('.')[-1]
            if home:
                aliases[al] = home
            for pair in (getattr(s, 'extra', None) or []):
                try:
                    m2, a2 = _name(pair[0]), pair[1]
                except Exception:
                    continue
                if m2:
                    aliases[_name(a2) if a2 else m2.split('.')[-1]] = m2
    return from_imports, aliases


def _class_bindings(stmts) -> dict:
    """A conservative `local name -> class name` map for method calls.

    Only the shapes that name a class unambiguously: `x = Cls(...)` with a bare
    class name, and a parameter annotated `x: Cls`. A name bound to more than
    one class, or anywhere associated with another shape, is left out — the
    published row is evidence for a DEFINING unit, so a guess here would be a
    wrong type over there. False rows for a non-class name are harmless (the
    consumer only reads keys of its own classes).
    """
    import mojo.middle.exprtypes as _ex
    import mojo.middle.types as N

    out: dict = {}
    ambiguous: set = set()

    def _add(name, cls):
        if not name or not cls:
            return
        cur = out.get(name)
        if cur is not None and cur != cls:
            ambiguous.add(name)
        else:
            out[name] = cls

    for n in _ex._walk_ast(stmts):
        if isinstance(n, N.AssignStmt) and isinstance(n.target, N.IdentExpr):
            v = n.value
            if isinstance(v, N.CallExpr) and isinstance(v.func, N.IdentExpr):
                _add(_name(n.target.name), _name(v.func.name))
            elif isinstance(v, N.IdentExpr):
                _add(_name(n.target.name), _name(v.name))
        elif isinstance(n, N.FunctionDef):
            for p in (getattr(n, 'params', None) or []):
                try:
                    pn, pa = p[0], p[1]
                except Exception:
                    continue
                if isinstance(pa, str) and pa and pa[:1].isupper():
                    _add(_name(pn), pa)
    for nm in ambiguous:
        out.pop(nm, None)
    return out


def _kinds_of(arg, env) -> str:
    """One argument's kind in coro's alphabet, or '' when it cannot be typed."""
    import mojo.middle.coro as _coro
    try:
        k = _coro._argkind(arg, env)
    except Exception:
        return ''
    # A container answer is a tuple; container call-site kinds are the
    # container table's business, not a plain parameter kind.
    return k if isinstance(k, str) else ''


def scan_module_calls(src: str, module_name: str, publish: bool = True) -> list:
    """Publish this module's calls to OTHER modules' callees, by param kind.

    Returns the entries as `[(key, param_key, kind)]`. Every failure path is
    silent: this is an evidence pre-pass, and a module it cannot parse simply
    contributes none (its own compile reports the real error).
    """
    entries: list = []
    try:
        from fire_compiler import Parser, py_tokenize
        import mojo.middle.coro as _coro
        import mojo.middle.types as N
        stmts = Parser(py_tokenize(src)).parse_module()
    except Exception:
        return entries
    try:
        from_imports, aliases = _imports(stmts)
        bindings = _class_bindings(stmts)

        def _method_key(obj_name):
            """(home module, class name) for a receiver name, or None."""
            if obj_name in bindings:
                cls = bindings[obj_name]
                if cls in from_imports:
                    home, orig = from_imports[cls]
                    return home, orig
                return None  # class defined in THIS module: local evidence
            if obj_name in from_imports:
                home, orig = from_imports[obj_name]
                return home, orig
            return None

        def _visit_call(call, env):
            fn = call.func
            key = None
            if isinstance(fn, N.IdentExpr):
                nm = _name(fn.name)
                if nm in from_imports:
                    home, orig = from_imports[nm]
                    key = home + '.' + orig
            elif isinstance(fn, N.MemberExpr):
                obj = fn.obj
                if isinstance(obj, N.IdentExpr):
                    on = _name(obj.name)
                    if on in aliases:
                        key = aliases[on] + '.' + _name(fn.member)
                    else:
                        mc = _method_key(on)
                        if mc is not None:
                            key = mc[0] + '.' + mc[1] + '.' + _name(fn.member)
            if key is None:
                return
            for i, a in enumerate(call.args or []):
                if isinstance(a, N.UnaryOp) and a.op in ('*', '**'):
                    continue
                k = _kinds_of(a, env)
                if k:
                    entries.append((key, '#%d' % i, k))
            for pname, a in (getattr(call, 'kwargs', None) or []):
                k = _kinds_of(a, env)
                if k:
                    entries.append((key, _name(pname), k))

        for s in stmts:
            if isinstance(s, N.FunctionDef):
                env = None
                try:
                    env = _coro._static_env(s, None)
                except Exception:
                    env = None
                for n in _coro._walk(s, True):
                    if isinstance(n, N.CallExpr):
                        _visit_call(n, env)
            elif isinstance(s, N.StructDef):
                for m in (s.methods or []):
                    try:
                        env = _coro._static_env(m, s)
                    except Exception:
                        env = None
                    for n in _coro._walk(m, True):
                        if isinstance(n, N.CallExpr):
                            _visit_call(n, env)
            else:
                # module-level statements (rare): type literals only.
                for n in _coro._walk(s):
                    if isinstance(n, N.CallExpr):
                        _visit_call(n, None)
    except Exception:
        return entries
    if publish:
        publish_call_kinds(entries)
    return entries


# ── provisional signatures: the parent-side half of a parallel build ────────

def _store_class(node, stmts, params, key) -> str:
    """The value class of one `self.<f> = <value>` store: 'none' | 'refs' |
    'scalar' | 'unknown'. `params` is the method's parameter list (self
    included); `key` the callee's qualified registry key (for an
    importer-published argument kind)."""
    import mojo.middle.types as N
    if node is None:
        return 'unknown'
    if isinstance(node, N.NoneLiteral) or (
            isinstance(node, N.IdentExpr) and _name(node.name) == 'None'):
        return 'none'
    if isinstance(node, (N.IntLiteral, N.FloatLiteral, N.BoolLiteral)):
        return 'scalar'
    if isinstance(node, N.StringLiteral):
        return 'refs'          # str or bytes: a pointer either way
    if isinstance(node, (N.ListExpr, N.DictExpr, N.SetExpr, N.TupleExpr)):
        return 'refs'
    if isinstance(node, N.IdentExpr):
        # A parameter stored into a field: the call sites' kinds are the
        # evidence (the pre-pass published them for THIS module's callees).
        nm = _name(node.name)
        pos = -1
        seen_self = False
        for p in (params or []):
            try:
                pn = _name(p[0])
            except Exception:
                continue
            if pn in ('self', 'cls') and not seen_self:
                seen_self = True
                continue
            if pn.startswith('*'):
                continue
            pos += 1
            if pn == nm:
                break
            if pos >= 64:
                break
        if pos < 0:
            return 'unknown'
        kinds = call_kinds(key).get('#%d' % pos) or call_kinds(key).get(nm) or []
        if not kinds:
            return 'unknown'
        if any(k in ('p', 'w') for k in kinds):
            return 'refs'
        if any(k in ('i', 'b', 'd') for k in kinds):
            return 'scalar'
    return 'unknown'


def _field_classes(stmts, module_name: str) -> dict:
    """{(struct, field): 'refs'|'mixed'|'unknown'} from the module's stores.

    'refs' means the field holds `None` AND references and no scalar (stage
    5c rule 1: its bare 0 IS None). 'mixed' is a scalar beside a reference
    (the box). A field with no informative store is 'unknown' and is not
    published."""
    import mojo.middle.types as N
    import mojo.middle.exprtypes as _ex
    bits: dict = {}   # key -> int (1 none, 2 refs, 4 scalar)
    for s in stmts or []:
        if not isinstance(s, N.StructDef):
            continue
        sname = _name(s.name)
        for m in (s.methods or []):
            if not isinstance(m, N.FunctionDef):
                continue
            key = module_name + '.' + sname + '.' + _name(m.name)
            for n in _ex._walk_ast(m.body or []):
                if not (isinstance(n, N.AssignStmt)
                        and isinstance(n.target, N.MemberExpr)
                        and isinstance(n.target.obj, N.IdentExpr)
                        and _name(n.target.obj.name) == 'self'):
                    continue
                fname = _name(n.target.member)
                cls = _store_class(n.value, stmts, m.params, key)
                b = 0
                if cls == 'none':
                    b = 1
                elif cls == 'refs':
                    b = 2
                elif cls == 'scalar':
                    b = 4
                if b:
                    k = sname + '\x1f' + fname
                    bits[k] = bits.get(k, 0) | b
    out: dict = {}
    for k in bits:
        b = bits[k]
        sname, fname = k.split('\x1f', 1)
        if (b & 2) and (b & 4):
            out[(sname, fname)] = 'mixed'
        elif (b & 1) and (b & 2):
            out[(sname, fname)] = 'refs'
        elif (b & 2) and not (b & 1):
            # References only, no `None` store: the bare 0 is not a None
            # spelling here (nothing says the slot can hold None), so it is
            # not the rule-1 shape this pass publishes.
            out[(sname, fname)] = 'unknown'
        else:
            out[(sname, fname)] = 'unknown'
    return out


def _return_class(stmts, module_name: str, classes: dict, owner, fn) -> str:
    """'refs' / 'mixed' / '' for one function/method's return slot."""
    import mojo.middle.types as N
    import mojo.middle.exprtypes as _ex
    out = ''
    for n in _ex._walk_ast(getattr(fn, 'body', None) or []):
        if not isinstance(n, N.ReturnStmt):
            continue
        v = getattr(n, 'value', None)
        if v is None:
            continue
        if (owner and isinstance(v, N.MemberExpr)
                and isinstance(v.obj, N.IdentExpr)
                and _name(v.obj.name) == 'self'):
            cls = classes.get((owner, _name(v.member)))
            if cls == 'refs':
                return 'refs'
            if cls == 'mixed':
                out = 'mixed'
        elif isinstance(v, N.MemberExpr):
            # A field of another object is not this module's decision.
            continue
        elif isinstance(v, N.NoneLiteral):
            continue
    return out


def publish_source_signatures(sources) -> None:
    """Publish a PROVISIONAL `ret_class` per method/function of each source.

    The parent of a multi-process build cannot see a worker's compiled
    signatures. This pass gives it the one fact an importer needs and cannot
    re-derive from the text scan: `ret_class='refs'` (a return arm reads a
    refs-only field). The C `ret`/`params` are deliberately NOT published
    here — the importer's text scan already has them, and a provisional C
    type that disagreed with the definition would be an ABI claim, while
    `ret_class` only changes the caller's spelling. `sources` is
    `[(path, src)]`; failures are silent (the module's real compile reports
    them)."""
    for path, src in sources or ():
        mod = _module_name_for(path)
        try:
            from fire_compiler import Parser, py_tokenize
            import mojo.middle.types as N
            stmts = Parser(py_tokenize(src)).parse_module()
        except Exception:
            continue
        try:
            classes = _field_classes(stmts, mod)
            sigs: dict = {}
            for s in stmts or []:
                if isinstance(s, N.StructDef):
                    sname = _name(s.name)
                    for m in (s.methods or []):
                        if not isinstance(m, N.FunctionDef):
                            continue
                        cls = _return_class(stmts, mod, classes, sname, m)
                        if cls:
                            sigs[sname + '.' + _name(m.name)] = {'ret_class': cls}
                elif isinstance(s, N.FunctionDef):
                    cls = _return_class(stmts, mod, classes, None, s)
                    if cls:
                        sigs[_name(s.name)] = {'ret_class': cls}
            if sigs:
                publish_signatures(mod, sigs)
        except Exception:
            continue
