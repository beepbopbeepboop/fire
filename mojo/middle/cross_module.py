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
        'sigs': {m: {k: {'ret': s.get('ret'), 'params': list(s.get('params') or [])}
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
