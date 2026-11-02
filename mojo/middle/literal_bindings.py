"""Single-literal-binder resolution for identifier call arguments.

A call `f(s)` passes a value whose type the callee can rely on only when `s`
has exactly ONE binding in scope and that binding is a literal (`s = "r"`).
Both call-site consumers need that answer, each in its own vocabulary:

  * `mojo/middle/coro.py` (generator / async call-site yield kinds) reads the
    literal's KIND (`'p'`, `'i'`, ...), and
  * `mojo/backend_gimple/module_gen.py` (ordinary-def and cross-module
    parameter ctypes) reads the literal's CTYPE (`'char *'`, ...).

So this module answers the one structural question -- which node is the sole
binding of this name, if it is a literal -- and leaves the vocabulary to the
caller. It is the single binder census; do not re-derive one per consumer.

Scope rule, which is the whole soundness argument:

  * `binding_index(stmts)` is the MODULE-WIDE census: every binder anywhere in
    the module, nested functions included. It is a superset of every binder
    that could reach a module-level name, so using it as the fallback is
    conservative.
  * `scope_index(fd)` is the census of ONE function's own scope: its params
    and the binders in its body, with nested `def`/`class` bodies NOT
    descended into (their own bindings belong to them, and counting them here
    let a nested `s = "r"` answer for an enclosing function's `s = 1` -- a
    silently wrong literal type).
  * `unique_literal_value(name, enc_idx, mod_index)` answers from the
    enclosing function's scope when that scope binds the name at all (a local
    shadows a global), otherwise from the module-wide census.

Any second binder, a non-literal binder, a parameter, a `global`/`nonlocal`,
a comprehension or lambda target, or a wildcard import makes the answer None.
"""
from __future__ import annotations

import dataclasses

from fire_compiler import (
    AssignStmt, AugAssignStmt, ComptimeForStmt, ComptimeVarStmt, DelStmt,
    ExceptHandler, ForStmt, FromImportStmt, FunctionDef, Generator, GlobalStmt,
    ImportStmt, LambdaExpr, ListExpr, MultiAssignStmt, NonlocalStmt, StructDef,
    TraitDef, TupleExpr, VarDecl, WalrusExpr, WithItem, IdentExpr, Comprehension,
    CallExpr,
)
import mojo.middle.types as _types
from mojo.middle.exprtypes import _walk_ast


def _target_names(target, out) -> None:
    """Append to `out` every bare name an assignment target binds: an
    identifier, or an identifier inside a tuple/list target. Attribute and
    subscript targets bind no name. A plain str (a `with ... as name` alias
    spelled as a string) binds itself."""
    if isinstance(target, str):
        if target:
            out.append(target)
        return
    if isinstance(target, IdentExpr):
        out.append(target.name)
        return
    if isinstance(target, (TupleExpr, ListExpr)):
        for el in target.elements:
            _target_names(el, out)


def bound_names(nd) -> list:
    """Every name the single AST node `nd` binds in the scope that contains
    it, as a list (empty for nodes that bind nothing). A wildcard
    `from m import *` binds an unknown set and reports `'*'`.

    A FunctionDef reports its name AND its params, which is right for the
    module-wide census (over-inclusive, so conservative). `scope_index` reads
    only the name of a nested def, because the params belong to that def's
    own scope.
    """
    out: list = []
    if isinstance(nd, (AssignStmt, AugAssignStmt, ForStmt)):
        _target_names(nd.target, out)
    elif isinstance(nd, MultiAssignStmt):
        for t in nd.targets:
            _target_names(t, out)
    elif isinstance(nd, WithItem):
        if nd.alias is not None:
            _target_names(nd.alias, out)
    elif isinstance(nd, DelStmt):
        for t in nd.targets:
            _target_names(t, out)
    elif isinstance(nd, (GlobalStmt, NonlocalStmt)):
        for n in nd.names:
            out.append(n)
    elif isinstance(nd, FunctionDef):
        out.append(nd.name)
        for pn in _types._param_names_stripped(nd.params):
            out.append(pn)
    elif isinstance(nd, LambdaExpr):
        # A lambda's params shadow within the lambda body, which is walked as
        # part of the enclosing scope. Counting them here is over-inclusive,
        # and the over-count only makes the answer None.
        for p in nd.params:
            out.append(p[0] if isinstance(p, (tuple, list)) else p)
    elif isinstance(nd, Comprehension):
        # A comprehension's targets are local to it, so counting them in the
        # enclosing scope over-includes; that is conservative for the same
        # reason as the lambda params above.
        for g in nd.generators:
            _target_names(g.target, out)
    elif isinstance(nd, (StructDef, TraitDef, VarDecl, WalrusExpr,
                         ExceptHandler)):
        if nd.name:
            out.append(nd.name)
    elif isinstance(nd, (Generator, ComptimeForStmt, ComptimeVarStmt)):
        if nd.target:
            out.append(nd.target)
    elif isinstance(nd, ImportStmt):
        if nd.alias:
            out.append(nd.alias)
        else:
            out.append(nd.module.split('.')[0])
        for ent in nd.extra or []:
            mod_e, al_e = ent
            out.append(al_e if al_e else mod_e.split('.')[0])
    elif isinstance(nd, FromImportStmt):
        if nd.wildcard:
            out.append('*')
        for s in nd.name_alias_strs:
            al = _types._fi_alias(s)
            out.append(al if al else _types._fi_name(s))
    return out


def _add_binders(idx: dict, nd, names) -> None:
    for nm in names:
        if nm in idx:
            idx[nm].append(nd)
        else:
            idx[nm] = [nd]


def binding_index(stmts) -> dict:
    """MODULE-WIDE census: name -> list of the nodes anywhere in `stmts`
    (nested functions included) that bind it. One walk."""
    idx: dict = {}
    for nd in _walk_ast(stmts):
        _add_binders(idx, nd, bound_names(nd))
    return idx


def _scope_nodes(body) -> list:
    """Every node of ONE scope: `body` and its descendants, except that a
    nested FunctionDef or StructDef is reported but not descended into. Its
    own body is a different scope, reached through `scoped_calls`.

    Generic over the dataclass fields, like `exprtypes._walk_ast_into`, but
    unmemoized and pruned. Recursive, which is fine: an AST is shallow
    compared to Python's recursion limit."""
    out: list = []
    _scope_walk(body, out)
    return out


def _scope_walk(node, out) -> None:
    if node is None:
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _scope_walk(item, out)
        return
    if isinstance(node, type):
        return
    if not dataclasses.is_dataclass(node):
        return
    out.append(node)
    if isinstance(node, (FunctionDef, StructDef)):
        return
    for f in dataclasses.fields(node):
        child = getattr(node, f.name, None)
        if child is node:
            continue
        _scope_walk(child, out)


def scope_index(fd) -> dict:
    """The census of ONE function's own scope: its params (bound to `fd`
    itself, which is never a literal, so a parameter always answers None) and
    every binder in its body that is not inside a nested def or class body."""
    idx: dict = {}
    for pn in _types._param_names_stripped(fd.params):
        _add_binders(idx, fd, [pn])
    for nd in _scope_nodes(fd.body):
        if isinstance(nd, (FunctionDef, StructDef)):
            # The nested def's NAME binds here; its params and body do not.
            _add_binders(idx, nd, [nd.name])
        else:
            _add_binders(idx, nd, bound_names(nd))
    return idx


def scoped_calls(stmts) -> list:
    """Every CallExpr in `stmts` as a list of `(call, enc)` pairs, where
    `enc` is the INNERMOST FunctionDef whose own scope contains the call, or
    None for a call at module scope. A method's calls are attributed to the
    method. Nested defs are their own scopes, so a call inside one is not
    attributed to the function that defines it."""
    out: list = []
    scopes: list = [(stmts, None)]
    while scopes:
        body, enc = scopes.pop()
        for nd in _scope_nodes(body):
            if isinstance(nd, CallExpr):
                out.append((nd, enc))
            elif isinstance(nd, FunctionDef):
                scopes.append((nd.body, nd))
            elif isinstance(nd, StructDef):
                for m in nd.methods:
                    if isinstance(m, FunctionDef):
                        scopes.append((m.body, m))
    return out


def unique_literal_value(name, enc_idx: dict, mod_index: dict):
    """The literal VALUE node bound to identifier `name`, when its one binder
    in scope is `name = <value>` or `var name = <value>`; otherwise None.

    `enc_idx` is `scope_index` of the enclosing function (empty for a
    module-level call) and `mod_index` is `binding_index` of the module. The
    caller decides what a literal means: this returns the node, not a ctype
    or a kind.
    """
    sites: list = []
    if len(enc_idx) > 0:
        sites = list(enc_idx.get(name, [])) + list(enc_idx.get('*', []))
    if not sites:
        sites = list(mod_index.get(name, [])) + list(mod_index.get('*', []))
    if len(sites) != 1:
        return None
    site = sites[0]
    if isinstance(site, AssignStmt) and isinstance(site.target, IdentExpr):
        return site.value
    if isinstance(site, VarDecl) and site.value is not None:
        return site.value
    return None
