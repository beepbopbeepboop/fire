"""Shared middle-end extracted from gimple_gen_funcs.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, NonlocalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, Parser, py_tokenize, _as_str, _as_dict, _pair_key, _as_structdef_node, _as_funcdef_node
import ast_rewriter
import regex_compile
import mlir
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
import gimple_codegen  # constants used by some extracted helpers
from gimple_codegen import _selfhost_impl_py_files
import mojo.middle.types as gimple_ctypes
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

def _from_import_name_is_submodule(gen, module: str, name: str) -> bool:
    """True when `from module import name` binds a real SUBMODULE FILE
    (`module/name.py` or `module/name/__init__.py`), as opposed to an
    ordinary symbol (function/class/global) defined inside `module`'s
    own source — e.g. `from test.support import os_helper`, where
    `os_helper` names the file `test/support/os_helper.py`, not a name
    looked up inside `test/support/__init__.py` (see bugs/CODEGEN_
    generator_function_Lib_test_test_support.md's 2026-08-09 root-
    cause). A real top-level def/class/global-assignment for `name`
    inside `module`'s own parsed body always wins FIRST — mirrors
    CPython, where an attribute `__init__.py` actually sets on the
    package object (a function, class, or plain assignment) shadows
    the submodule-autoimport binding of the same name — so this only
    probes the filesystem once no such symbol is found. Uses
    `_parsed_import` (the same cached parse `_find_imported_struct`/
    `_find_generic_source` already use) and `_submodule_source_path`
    (the same search-path resolution `_compile_imported_module` uses)
    rather than inventing new resolution logic."""
    _path, _src, _stmts = gen._parsed_import(module)
    if _stmts:
        for s in _stmts:
            if isinstance(s, (gimple_ctypes.FunctionDef, gimple_ctypes.StructDef)) and s.name == name:
                return False
            if isinstance(s, gimple_ctypes.VarDecl) and s.name == name:
                return False
            if isinstance(s, gimple_ctypes.AssignStmt) and isinstance(s.target, gimple_ctypes.IdentExpr) \
                    and s.target.name == name:
                return False
            if isinstance(s, gimple_ctypes.MultiAssignStmt):
                for _t in s.targets:
                    if isinstance(_t, gimple_ctypes.IdentExpr) and _t.name == name:
                        return False
            # Real, common idiom: `module`'s own `__init__` RE-EXPORTS
            # `name` by importing it from one of ITS OWN submodules —
            # e.g. `std/memory/__init__.mojo` has `from .alloc import
            # alloc` (the free FUNCTION `alloc`, re-exported under the
            # same bare name as the submodule FILE `std/memory/
            # alloc.mojo` that defines it). Without this check, `from
            # std.memory import alloc` misclassified `alloc` as THE
            # SUBMODULE (the bare filesystem probe below finds `std/
            # memory/alloc.mojo` and, having no other evidence,
            # concludes "submodule") instead of the re-exported
            # function — confirmed via a real regression this exact
            # case caused (`dict.mojo`'s `_ensure_capacity` calling
            # `alloc(...)` as a bare function lost its extern
            # declaration entirely, "implicit declaration of function
            # 'alloc'"). Mirrors real Python: `__init__.py` executing
            # `from .alloc import alloc` REBINDS the package's `alloc`
            # attribute to the function, overwriting whatever the
            # submodule auto-import step bound it to first — an
            # explicit later rebinding always wins, exactly like the
            # def/class/assignment cases above.
            if (isinstance(s, gimple_ctypes.FromImportStmt) and not getattr(s, 'wildcard', False)):
                for _fip0 in (getattr(s, 'name_alias_strs', None) or []):
                    _rn = gimple_ctypes._fi_name(_fip0)
                    _ra = gimple_ctypes._fi_alias(_fip0)
                    if (_ra if _ra else _rn) == name:
                        return False
    return gen._submodule_source_path(
        gimple_ctypes._join_import_member(module, name)) is not None

def _resolve_reexported_closure_func(gen, module: str, name: str, _depth: int = 0):
    """Follow a closure module's own `from SIBLING import (...)` re-exports
    to the top-level FunctionDef that actually defines `name`. Returns
    (FunctionDef, defining_module_name) or (None, None). Bounded recursion;
    parses are `_parsed_import`-cached so this is cheap."""
    if _depth > 4:
        return None, None
    _stmts = None
    try:
        _pi = gen._parsed_import(module)
        _stmts = _pi[2] if _pi else None
    except Exception:
        _stmts = None
    if not _stmts:
        # _parsed_import (imports.resolve_source) can't see a bare repo-local
        # `.py` sibling; resolve it the way _compile_imported_module does and
        # seed the shared cache so this parse is done at most once.
        try:
            _mp = None
            for _c in gen._module_candidate_paths(module):
                if os.path.exists(_c):
                    _mp = _c
                    break
            if _mp:
                with open(_mp) as _mf:
                    _msrc = _mf.read()
                _stmts = gimple_ctypes.ast_rewriter.rewrite(
                    gimple_ctypes.Parser(gimple_ctypes.py_tokenize(_msrc)).parse_module())
                gen._imported_src_cache[module] = (_mp, _msrc, _stmts)
        except Exception:
            _stmts = None
    if not _stmts:
        return None, None
    for _s in _stmts:
        if isinstance(_s, FunctionDef) and _s.name == name:
            return _s, module
    for _s in _stmts:
        if not isinstance(_s, gimple_ctypes.FromImportStmt) or getattr(_s, 'wildcard', False):
            continue
        for _fp in (getattr(_s, 'name_alias_strs', None) or []):
            _rn = gimple_ctypes._fi_name(_fp); _ra = gimple_ctypes._fi_alias(_fp)
            if (_ra if _ra else _rn) == name:
                _fn, _home = _resolve_reexported_closure_func(
                    gen, _s.module, _rn, _depth + 1)
                if _fn is not None:
                    return _fn, _home
    return None, None

def _signature_ctypes(gen, params, node, self_struct=None, sentinel='...') -> list:
    """C param-type list for a function/method.
    - **kwargs -> 'MojoDict *' (a real trailing parameter).
    - *args     -> 'MojoList *' when the function ALSO has **kwargs (the
      forwarding pattern f(self, *args, **kwargs): the parser flattens the
      call's spreads, so the caller passes the list/dict directly -> concrete
      params, no packing). Otherwise the packing `sentinel` ('...' for
      func_param_types, 'MojoList *' for emitted declarations), and the rest
      collapse into it.
    """
    has_kw = False
    for _hk0 in (params or []):
        if _hk0[0].startswith('**'):
            has_kw = True
            break
    out = []
    seen_vararg = False
    for i, (pn, pt) in enumerate(params or []):
        if pn.startswith('**'):
            out.append('MojoDict *')
        elif pn.startswith('*'):
            if has_kw:
                out.append('MojoList *')      # pass-through: concrete list param
            elif not seen_vararg:
                out.append(sentinel)          # packing convention
                seen_vararg = True
            # After *args, continue to catch any trailing `out` params that also
            # appear in the definition and must match the forward declaration.
        elif i == 0 and pn == 'self' and self_struct:
            # `_as_str`: `self_struct` arrives through a parameter that
            # defaults to None, so the self-hosted backend types it int64_t.
            # `f"{self_struct} *"` then formats the struct name's `char *`
            # bits as a DECIMAL and stores `"45740546496 *"` into
            # `func_param_types[method]` — every later `({that}){self}`
            # receiver cast in the generated C is then a raw heap address
            # (`_t34 = (45740546496 *)self;`), invalid and ASLR-unstable.
            out.append(f"{_as_str(self_struct)} *")
        elif i == 0 and _selfhost_gen_self_param_ctype(gen, pn, pt, node):
            out.append('GimpleGen *')
        elif (self_struct and isinstance(pt, str) and pt.split('[', 1)[0].strip() == self_struct
                and self_struct in gen.struct_field_types):
            # A non-self param whose annotation is a bracketed generic
            # instantiation of THIS SAME struct (e.g. List.extend(mut
            # self, var other: List[Self.T, ...])) means "another
            # instance of the struct I'm compiling," not the builtin
            # generic — but _mojo_type's List/Dict/Set/Span bracket
            # handling can't distinguish those and always erases to the
            # runtime's boxed representation (MojoList*/MojoDict*/...).
            # That's correct for every OTHER file merely using List[T]/
            # Dict[K,V]/etc, but wrong here, in the one file that IS
            # List/Dict/Set/Span's own real implementation — `other`
            # needs the real struct pointer so `other->_len` etc. resolve
            # against the actual fields, not the runtime's builtin ones.
            out.append(f"{_as_str(self_struct)} *")
        else:
            # Method context: consult the method's QUALIFIED
            # "Struct_method" inferred-param entry (usage-based inference
            # and the cross-call scalar contract both store there) before
            # falling back to _param_ctype, which can only see BARE
            # function-name keys and so silently missed every method's
            # resolved types — leaving unannotated varargs-method params
            # at the int64_t default in _mangled_signature_ctypes /
            # func_param_types even after the qualified registry held the
            # real type, so pre-definition call sites converted arguments
            # against the stale boxed type ("makes pointer from integer
            # without a cast", self-hosted myinterpreter.py's
            # Interpreter__call_dunder). Mirrors the precedence the
            # gen_module forward-declaration loop applies.
            _msig_ct = None
            if pt is None and self_struct and hasattr(gen, '_inferred_param_types'):
                _msig_ct = gen._inferred_param_types.get(
                    f"{self_struct}_{node.name}", {}).get(pn)
            if _msig_ct is not None:
                out.append(_msig_ct)
            else:
                out.append(gen._param_ctype(pn, pt, node))
    return out


def _note_vararg_trailing_param_types(gen, s) -> None:
    """Called immediately after `self.func_param_types[s.name] =
    self._signature_ctypes(...)` sets a free function's CORRECT,
    fully-inferred signature — copies it into `self._vararg_
    trailing_param_types` when the packing sentinel isn't in the
    LAST position (a `(fixed, *args, trailing_kwonly=default, ...)`
    shape with no `**kwargs`). `func_param_types[name]` itself later
    gets its sentinel overwritten with the concrete signature once
    the function's forward declaration is finalized (see
    `_vararg_trailing_param_types`'s own docstring) — this side
    table is where `_lower_named_call`'s trailing-keyword-only-param
    packing fix reads from instead, so it stays correct regardless
    of how much LATER a given call site is compiled. Deliberately
    NOT computed once at registration time (a first, reverted
    attempt did that — `_param_ctype`'s own type inference for an
    unannotated param isn't fully settled that early, confirmed via
    a real repro where it wrongly produced `int64_t` for a `char *`
    message param). Piggybacking on the SAME already-correct value
    this line just computed avoids re-deriving anything."""
    if not isinstance(s, gimple_ctypes.FunctionDef) or not s.params:
        return
    _has_kw2 = False
    for _hk1 in s.params:
        if _hk1[0].startswith('**'):
            _has_kw2 = True
            break
    if not _has_kw2:
        _last_pn = s.params[-1][0]
        if not _last_pn.startswith('*'):
            _sig = gen.func_param_types.get(s.name)
            if _sig and '...' in _sig and _sig[-1] != '...':
                gen._vararg_trailing_param_types[s.name] = _sig
                try:
                    gen._vararg_trailing_param_types[gen._func_csym(s.name)] = _sig
                except Exception:
                    pass

def _param_ctype(gen, pname: str, ptype, node: gimple_ctypes.FunctionDef,
                 is_self: bool = False) -> str:
    """Resolve parameter C type, applying argument convention qualifiers."""
    if is_self:
        return f"{node.name} *"
    _sh = _selfhost_gen_self_param_ctype(gen, pname, ptype, node)
    if _sh is not None:
        return _sh
    # Check inferred parameter types first (for unannotated parameters).
    # `.get` into a local (typed MojoDict* via the field's declared
    # `dict[str, dict[str, str]]` shape), NOT a double `[fn][pname]`
    # subscript — the latter left the inner dict typed int64_t in the
    # self-hosted backend, so `pname in it` lowered to the `/* TODO: 'in'
    # for int64_t */` no-op and no usage-inferred type was ever found.
    ctype = None
    if ptype is None and hasattr(gen, '_inferred_param_types'):
        func_key: str
        func_key = node.name
        _ipt_fn = gen._inferred_param_types.get(func_key)
        if _ipt_fn is not None and pname in _ipt_fn:
            ctype = _ipt_fn[pname]
    if ctype is None:
        ctype = gen._resolve_type(ptype)
    # An UNANNOTATED parameter whose declared default value is a string
    # literal IS a string parameter. The default expression is type
    # evidence exactly as strong as an annotation for the omitted-
    # argument case: every call site that omits this param gets the
    # literal padded in via _default_expr_to_pair, which lowers a
    # StringLiteral default to a real ('char *', '"..."') C string —
    # previously coerced INTO the int64_t box this resolver produced,
    # so the callee then did int-arithmetic/str-from-int on a genuine
    # char* pointer (`convertdir(dir, dirprefix='', nameprefix='')` in
    # Tools/unicode/gencodec.py printing the pointer's decimal digits
    # instead of the prefix text for `dirprefix + name`). Only fires on
    # the unresolved generic int64_t box: explicit annotations, usage-
    # based inference results, and the cross-call scalar contract all
    # keep their existing precedence. param_defaults is keyed by the
    # bare declared name (the parser stores no star prefixes there),
    # matching how dup_def_signature_key looks the same table up.
    _pdflt = (getattr(node, 'param_defaults', None) or {}).get(pname.lstrip('*'))
    if (ptype is None and ctype == 'int64_t'
            and isinstance(_pdflt, StringLiteral)):
        # A `b'...'` default makes the param a `bytes` param; a plain string
        # default makes it a `str` (char *) param. bytes must NOT be
        # conflated with str — b[i] is an int, not a 1-char string.
        ctype = 'MojoBytes *' if getattr(_pdflt, 'is_bytes', False) else 'char *'
    elif (ptype is None and ctype == 'char *'
          and isinstance(_pdflt, StringLiteral) and getattr(_pdflt, 'is_bytes', False)):
        # A `b'...'` default is unambiguous `bytes` evidence and must win
        # over a weak usage-inferred `char *` — `len(b)` alone (the only
        # body signal for many bytes params) resolves to str, which would
        # then pass a real `MojoBytes *` argument into a `char *` slot and
        # `strlen()` the struct (non-deterministic length). An explicit
        # annotation still takes precedence (ptype is not None there).
        ctype = 'MojoBytes *'
    elif (ptype is None and ctype == 'int64_t'
          and isinstance(_pdflt, (DictExpr, TupleExpr, ListExpr, SetExpr))):
        # The CONTAINER-literal half of the rule the two branches above
        # state for strings: an unannotated parameter whose declared
        # default is a `{}` / `[]` / `set()` literal IS a container
        # parameter, by exactly the same "the default expression is type
        # evidence as strong as an annotation" argument (an omitted
        # argument gets the literal itself padded in, and the literal has
        # an unambiguous C representation).
        #
        # Without it the param stays the generic `int64_t` box and every
        # real container operation on it is either a coercion of a
        # pointer through a scalar (silently wrong) or a hard error --
        # `def updated_env(updates={})` in
        # `Tools/wasm/wasi/__main__.py` fed that box straight into
        # `mojo_dict_union(env_defaults | os.environ | updates)` as
        # argument 2, an `int64_t` where a `MojoDict *` is expected.
        #
        # A tuple/list default is a MojoList, so it must NOT take this
        # branch's MojoDict answer. `('gen', 'self')` is the case that
        # mattered: `_selfhost_fn_reassigns_method(_fn, _pnames=('gen',
        # 'self'))` kept the int64_t box, the call site padded the omitted
        # default as a real `(MojoList *)0`, and gcc rejected the self-host
        # closure with "passing argument 2 ... makes integer from pointer
        # without a cast". `GimpleGen.__init__(..., no_mangle=(), ...)` is
        # the same bug with a worse outcome: the definition inferred
        # `MojoList *` from `set(no_mangle)` while the declaration said
        # `int64_t`, and gcc's "conflicting types" took out
        # bootstrap-stage2-cc, selfhost, mojoc, silentnoop and
        # stdlib-syntax together.
        #
        # Fires ONLY on the unresolved generic box (`ctype ==
        # 'int64_t'`), so an explicit annotation and any usage- or
        # cross-call-inferred type keep their existing precedence --
        # same guard the `StringLiteral` branch above uses.
        _pdflt_name = type(_pdflt).__name__
        if _pdflt_name in ('TupleExpr', 'ListExpr'):
            ctype = 'MojoList *'
        elif _pdflt_name == 'SetExpr':
            ctype = 'MojoSet *'
        else:
            ctype = 'MojoDict *'
    # Compile-time string types (StaticString, StringLiteral, StringRef,
    # StringSlice) are REAL strings in this codegen — a NUL-terminated
    # `char *`. The general resolver boxes them as opaque int64_t handles
    # (the libc-stub `int64_t StaticString(...)`), which breaks a param
    # used as a string: `file_name[byte=0:i]` on a `file_name: StaticString`
    # param then slices an int64_t and lowers to int64_t, and passing it to
    # a String-taking ctor is a `makes pointer from integer` error. Mirror
    # _imported_field_ctype's handling (std/pathlib/path.mojo:90).
    if ptype in ('StaticString', 'StringLiteral', 'StringRef', 'StringSlice'):
        ctype = 'char *'
    if ctype == 'void':
        # _mojo_type('None') correctly maps NoneType -> void for RETURN
        # types, but a named PARAMETER can never be typed void in a
        # multi-argument C signature (only the sole, unnamed `(void)` no-
        # args marker is legal) — e.g. Bool.__init__(out self, value:
        # None). Box it the same generic way every other
        # no-runtime-representation type already is throughout this file.
        ctype = 'int64_t'
    conv  = (getattr(node, 'param_convs', {}) or {}).get(pname)
    if conv in ('read', 'ref') and gimple_ctypes.TypeLattice.is_pointer(ctype):
        # Immutable borrow of a pointer arg → const T *
        # Only add const if not already present
        if not ctype.startswith('const '):
            ctype = 'const ' + ctype
    # Span/StringSlice's `mut` comptime Bool bracket-parameter is erased by
    # _mojo_type/_resolve_type down to the fat-pointer `Span *` above, with
    # no record of what it was bound to — but the literal is still visible
    # in the raw annotation text here (e.g. "StringSlice[mut=True,...]").
    # Recorded so _lower_MemberExpr can answer `b.mut` instead of emitting
    # an invalid field access on the erased struct.
    if isinstance(ptype, str):
        m = gimple_ctypes.re.search(r'\b(?:Span|StringSlice)\[.*\bmut\s*=\s*(True|False)\b', ptype)
        if m:
            gen._span_mut_params[pname] = (m.group(1) == 'True')
    return ctype

def _resolve_import_module_qualifier(gen, mod: str) -> str:
    """Canonical module qualifier for a `from <mod> import ...` statement
    — the string _func_qualifier must use for a name that statement binds,
    so a call site and the defining module's own compile derive the
    identical qualified C symbol. Mirrors _emit_stdlib_import_externs:
    resolve a relative module ref against this file's own package, then
    module_loader.resolve_module_path + module_name_for_path. Returns ''
    when the module can't be resolved (callers then skip scope tracking
    for that import, falling back to the flat dict / existing tiers)."""
    import module_loader as _mlmod
    if gen.do_imports and gen._inline_module_qualifiers:
        inline_path = gen._submodule_source_path(mod)
        if inline_path:
            inline_key = os.path.abspath(inline_path)
            if inline_key in gen._inline_module_qualifiers:
                mod_key = mod.lstrip('.').replace('.', '_').replace('-', '_')
                gen._inline_module_qualifiers[mod_key] = gen._inline_module_qualifiers[inline_key]
    path = None
    if mod.startswith('.'):
        fn = getattr(gen, '_current_filename', '') or ''
        if not fn:
            return ''
        d = gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(fn))
        dots = len(mod) - len(mod.lstrip('.'))
        rest = mod.lstrip('.')
        for _ in range(dots - 1):
            p = gimple_ctypes.os.path.dirname(d)
            if p == d:
                break
            d = p
        if rest:
            cand = gimple_ctypes.os.path.join(d, *rest.split('.'), '__init__.mojo')
            if not gimple_ctypes.os.path.exists(cand):
                cand = gimple_ctypes.os.path.join(d, *rest.split('.')) + '.mojo'
        else:
            cand = gimple_ctypes.os.path.join(d, '__init__.mojo')
        if gimple_ctypes.os.path.exists(cand):
            path = cand
        if path is None:
            return ''
    else:
        # Guard first (compiled try/except is not reliable — see
        # ModuleLoader.can_resolve_module_path's docstring).
        path = None
        if _mlmod.can_resolve_module_path(mod):
            try:
                path = _mlmod._module_loader.resolve_module_path(mod)
            except Exception:
                path = None
        if not path or not gimple_ctypes.os.path.exists(path):
            # Not a stdlib/test module (e.g. a sibling project module,
            # `alpha_module` in a fire.py build test dir) — fall back to
            # the module string itself, matching the do_imports
            # inline-compile loop, which keys its registrations by the
            # module string.
            return mod
    try:
        q = _mlmod.module_name_for_path(path)
    except Exception:
        return mod
    return q or mod

def _imported_field_ctype(gen, type_ann: str) -> str:
    """Resolve an imported struct field's type to C. Compile-time string types
    are char* here (they back string fields like emission_kind) even though the
    general resolver keeps them as opaque int64_t handles elsewhere."""
    if type_ann in ('StaticString', 'StringLiteral', 'StringSlice', 'StringRef', 'String'):
        return 'char *'
    return gen._resolve_type(type_ann) if type_ann else 'int64_t'

def _ris_collect(params_by_struct: dict, fn) -> None:
    """Hoisted out of `_register_imported_structs` (module-level, not a
    nested, RECURSIVE closure mutating a captured dict) — a real
    --dump-full fire.py determinism diff showed `_register_imported_
    structs__collect (_env__collect, _t60);` on one run vs `..., 0);` (an
    extra, spurious trailing argument) on another for the IDENTICAL call
    site — the lifted-closure env for this closure's own recursive self-
    calls carried an inconsistent apparent arity, the same class of bug
    already fixed for `_locally_bound_names`'s `walk` this session (and
    with the same fix: thread the captured mutable dict as an explicit
    parameter instead)."""
    for _pn, _pt in (getattr(fn, 'params', None) or []):
        b = _ris_base(_pt)
        if b:
            params_by_struct.setdefault(b, set()).add(
                gimple_ctypes._strip_mojo_param_modifiers(_pn.lstrip('*')))
    # Nested `def`s (e.g. a raises-helper closure declared inside a
    # test function, typed on an imported struct) live inside the
    # enclosing statement's body/orelse/handler blocks, not at
    # top-level — walk those too (iteratively: a nested generator
    # calling itself doesn't survive self-host closure-lifting) so
    # their typed params count too.
    _worklist = [getattr(fn, 'body', None)]
    while _worklist:
        _blk = _worklist.pop()
        for _st in (_blk or []):
            if isinstance(_st, gimple_ctypes.FunctionDef):
                _ris_collect(params_by_struct, _st)
            for _attr in ('body', 'orelse', 'finally_body'):
                _sub = getattr(_st, _attr, None)
                if isinstance(_sub, list):
                    _worklist.append(_sub)
            _handlers = getattr(_st, 'handlers', None)
            if isinstance(_handlers, list):
                for _h in _handlers:
                    _hb = getattr(_h, 'body', None)
                    if isinstance(_hb, list):
                        _worklist.append(_hb)

def _find_imported_struct(gen, module: str, name: str):
    """The StructDef for `name` defined directly in `module`'s source, or None."""
    _path, _src, mod = gen._parsed_import(module)
    if mod is None:
        return None
    for s in mod:
        if isinstance(s, gimple_ctypes.StructDef) and s.name == name:
            return s
    return None

def _resolve_test_relative_module(gen, module: str) -> str | None:
    """Fallback for local test-only packages (e.g. `test_utils`) that
    `imports.py`'s resolver can't find: it only searches MOJO_PATH/
    PYTHONPATH/the stdlib root, none of which include a plain `test/`
    subtree, so a bare `test_utils` (living at `test/test_utils/`,
    imported test-relatively by sibling files like
    `test/memory/test_span.mojo`) is unresolvable there at any level —
    not a re-export-chain issue, the module itself has no path. Walk
    upward from the currently-compiled file's directory (bounded to
    avoid escaping the stdlib checkout) looking for `<dir>/<module path>/
    __init__.mojo` or `<dir>/<module path>.mojo`. `module` may itself be
    dotted (e.g. `test_utils.types`, produced when following a re-export
    chain via _find_generic_source — not just the bare top-level name)."""
    if not gen._current_filename:
        return None
    rel_parts = module.split('.')
    d = gimple_ctypes.os.path.dirname(gimple_ctypes.os.path.abspath(gen._current_filename))
    for _ in range(6):
        cand_pkg = gimple_ctypes.os.path.join(d, *rel_parts, '__init__.mojo')
        if gimple_ctypes.os.path.isfile(cand_pkg):
            return cand_pkg
        cand_mod = gimple_ctypes.os.path.join(d, *rel_parts[:-1], rel_parts[-1] + '.mojo')
        if gimple_ctypes.os.path.isfile(cand_mod):
            return cand_mod
        parent = gimple_ctypes.os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None

def _parsed_import(gen, module: str):
    """(path, source_text, stmts) for an imported module, parsed once and
    cached. (None, '', None) on failure."""
    # `_as_dict`: the field read is erased to int64_t on the self-hosted path
    # (assignment to 'int64_t' from 'MojoList *'), so view it as the dict it is.
    cache = _as_dict(gen._imported_src_cache)
    closure_module = gen.do_imports and module in gen._compiled_modules
    if module not in cache or (closure_module and not cache[module][0]):
        try:
            import imports as _imp
            path = _imp.resolve_source(module) or gen._resolve_test_relative_module(module)
            # Neither helper above resolves a LOCAL PROJECT SIBLING, which
            # is most of what this compiler is asked to compile:
            #
            #  * `imports.py`'s `resolve_source` only understands
            #    MOJO_PATH-relative dotted names (`_find`'s
            #    `name.replace('.', os.sep)` turns a leading dot into a
            #    leading path separator, which `os.path.join` then treats
            #    as absolute and silently DISCARDS the search directory it
            #    was joined onto — `os.path.join('/foo', '/base.mojo') ==
            #    '/base.mojo'`), and
            #  * `_resolve_test_relative_module` only tries the `.mojo`
            #    extension, so a bare `insp` next to a `insp.py` never
            #    matches, and it mis-splits a leading dot into an empty
            #    path component.
            #
            # Both gaps used to be "harmless everywhere else
            # `_parsed_import` is called from" (struct/generic lookups
            # degrade to "not found" the same as any other unresolvable
            # module). They are not harmless, and the first place they
            # turned into a genuine crash was `_register_link_imports`
            # (link mode's `mojo build`): failing to resolve `.base` meant
            # `triple` never got registered at all, `f = triple` fell
            # through to the generic "undeclared identifier" placeholder
            # (a literal `0`), and calling through that placeholder
            # (`f(14)`) called a NULL function pointer — `Segmentation
            # fault: 11` (see bugs/CODEGEN_link_mode_from_submodule_import_
            # symbol_value_call_segfault.md). The second was SILENT and is
            # why this is no longer restricted to dotted/closure names: a
            # function-scoped `from _colorize2 import can_colorize` in a
            # sibling `.py` (this compiler's own `Lib/argparse.py`'s
            # `from _colorize import can_colorize`, inside a method) made
            # `_exports` return `(exports={}, from_reflection=False,
            # source=None)`, so the `if source:` fallbacks below all
            # short-circuited, NOTHING was registered, and the call bound
            # to the extern-preamble's `weak` "unavailable in compiled
            # mode" stub — printing into the program's own stdout and
            # returning 0, exit 0 (bugs/hard/CODEGEN_function_scoped_
            # import_module_not_inlined.md, row 0). The module was never
            # inlined because this helper could not find it, not because
            # the single-TU path deliberately skips function-scoped
            # imports.
            #
            # Reuse `_submodule_source_path` (i.e.
            # `_module_candidate_paths`), the do_imports=True inline
            # path's OWN resolver — it anchors at the IMPORTING file's
            # directory and its ancestors, honours recorded
            # `sys.path.insert(...)` dirs, handles the
            # dot-count-as-level Python semantics, and tries `.py` before
            # `.mojo`. It was already correct for every one of these
            # shapes, just gated to dotted/closure names here, which left
            # it inconsistent with `_compile_imported_module`, which calls
            # the same function for EVERY module name. Unconditional
            # because the two resolvers must agree: a name this helper
            # cannot resolve is a name `_compile_imported_module` will
            # not inline either, and that divergence is the whole bug.
            if not path:
                path = gen._submodule_source_path(module)
            src = open(path).read() if path else ''
            cache[module] = (path, src,
                             ast_rewriter.rewrite(Parser(py_tokenize(src)).parse_module()) if src else None)
        except Exception:
            gimple_ctypes._debug_note('cannot resolve/parse module', module)
            cache[module] = (None, '', None)
    return cache[module]

def _local_sibling_module_exports(gen, module: str):
    """(exports_dict, qualifier) for a `from module import ...` that
    module_loader.load_module() can't resolve because it isn't a
    tracked stdlib/test module — i.e. a LOCAL project sibling file (see
    bugs/DYLIB_sibling_import_calls_bind_to_weak_stubs.md, box.3d/game
    repo). (None, None) when `module` genuinely can't be found anywhere
    (a real external/unmodeled package, or a bare relative import), in
    which case the caller falls back to the existing weak-stub/
    unresolved-alias behavior.

    `mojo dylib` (driver.compile_dylib -> build_stdlib_dylib.build)
    compiles each module SEPARATELY — one private GimpleGen instance per
    file, do_imports=False, link_imports=False — so neither
    _register_link_imports (link_imports-only) nor the do_imports
    inline-compile loop's _imported_func_home bookkeeping ever runs for
    this shape; the only registration pass that always runs
    (_emit_stdlib_import_externs, and this gen_module's own "Process
    imports" loop) previously just gave up on any non-stdlib module
    name, degrading a same-dylib sibling to the SAME "genuinely
    external, unmodeled package" weak-stub path real third-party C
    packages use — even though the real definition compiles into the
    very same output dylib (driver._expand_dylib_modules already walks
    the same sibling-import closure to include it). The call sites just
    never learned the sibling's module qualifier, so they emitted an
    UNQUALIFIED call that bound to the weak stub instead of the real
    module-qualified symbol sitting right there in the dylib.

    Resolves via `_parsed_import` — the SAME sibling-resolution
    machinery (imports.resolve_source, falling back to
    _resolve_test_relative_module's walk-up-from-this-file directory
    search) `_find_imported_struct`/`_find_generic_source` already use
    for cross-module struct/generic lookups — then extracts real
    fn/def signatures via module_loader.load_module_from_path (the same
    text-scan logic load_module() itself uses for stdlib/test modules,
    just entry-pointed by file path instead of by stdlib-relative
    module name, since resolve_module_path is deliberately restricted
    to STDLIB_PATH/TEST_PATH and cannot see a project's own local
    files)."""
    path, _src, _stmts = gen._parsed_import(module)
    if not path:
        return None, None
    import module_loader as _mlmod
    exports = _mlmod.load_module_from_path(path)
    path_key = os.path.abspath(path)
    if gen.do_imports and path_key in gen._inline_module_qualifiers:
        module_key = module.lstrip('.').replace('.', '_').replace('-', '_')
        gen._inline_module_qualifiers[module_key] = gen._inline_module_qualifiers[path_key]
    if gen.do_imports and module in gen._compiled_modules:
        exports = dict(exports)
        for fn in (_stmts or []):
            if not isinstance(fn, FunctionDef):
                continue
            info = exports.get(fn.name, {})
            if not isinstance(info, dict) or not fn.return_type:
                continue
            info = dict(info)
            ret = _sgfs_resolve_ann(gen, fn.return_type)
            pts = gen._signature_ctypes(fn.params, fn, sentinel='MojoList *')
            c_params = [ct + ' ' + pn.lstrip('*')
                        for ct, (pn, pt) in zip(pts, fn.params)]
            info['c_return_type'] = ret
            info['c_parameters'] = c_params
            info['signature'] = ret + ' ' + fn.name + ' (' + (', '.join(c_params) or 'void') + ')'
            exports[fn.name] = info
    qualifier = _mlmod.module_name_for_path(path)
    return exports, (qualifier or None)

def _find_generic_source(gen, module: str, name: str, kind: str = 'fn', depth: int = 0):
    """Source path of the module that DEFINES generic `name` (a free
    function when kind='fn', a struct when kind='struct'), reachable from
    `module` by following `from X import (...)` re-export hops (e.g.
    std.os re-exports listdir from .os = os.mojo). None if not generic."""
    # String key, NOT a `(module, name, kind)` tuple — a tuple set-key is
    # coerced to a boxed int64_t on the self-hosted path so `key in
    # visited` never hits, forcing a full re-scan on every repeat call.
    key = module + '\x1f' + name + '\x1f' + kind
    if key in gen._find_generic_visited:
        return None
    gen._find_generic_visited.add(key)
    if depth > 3 or not module:
        return None
    path, src, mod = gen._parsed_import(module)
    if not src:
        return None
    head = r'\bstruct\s+' if kind == 'struct' else r'\b(?:fn|def)\s+'
    if gimple_ctypes.re.search(head + rf'{gimple_ctypes.re.escape(name)}\s*\[', src):
        return path
    nm = gimple_ctypes.re.escape(name)
    # Flat [mod0, names0, mod1, names1, ...] scan instead of two
    # `re.finditer(...)` loops with `mm.group(1)/.group(2)` — the
    # self-hosted backend has no lowering for `re.finditer` (emits
    # `mojo_unsupported_iter`, loop body runs zero times) nor for
    # `.group(n)` with an argument, so on the compiled path re-export
    # hop resolution here was silently dead.
    _fi = _scan_from_imports_flat(src)
    _j = 0
    while _j < len(_fi):
        _fmod = _fi[_j]
        _fnames = _fi[_j + 1]
        _j += 2
        if gimple_ctypes.re.search(rf'(?:^|[\s,(]){nm}(?:[\s,)]|$)', _fnames):
            r = gen._find_generic_source(gen._abs_module(_fmod, module), name, kind, depth + 1)
            if r:
                return r
    return None

def _struct_method_overload_ids(stmt: StructDef) -> list:
    """Overload-id per method, aligned with stmt.methods. Must match the
    emission loop in gen_module so the method's C symbol, its closure-lookup
    key (current_func_name), and the pre-pass closure registration all agree.
    Empty string for a non-overloaded method. A @staticmethod (no `self` use)
    so reflect.py's collect_exports can call the exact same logic when
    building each method's exported C symbol — reflect.py previously used a
    bare `Struct_method` name unconditionally, which silently diverged from
    this hash-suffix scheme for any overloaded method and produced a
    reflection-table entry (and forward-declared `extern` in the dylib's
    merged reflect table) pointing at a symbol nothing ever defines.

    `stmt: StructDef` is load-bearing for the self-hosted build, not
    decoration: unannotated, `stmt` compiles to an opaque int64_t, so
    `stmt.methods` resolves through `_known_field_type('methods')` — which
    is AMBIGUOUS (`MojoList *` on StructDef/TraitDef, `MojoDict *` on the
    interpreter's runtime MojoClass) and therefore answers None. The loop
    then fell to the runtime dict-or-list dispatch whose dict branch binds
    the loop variable as `char *`, so `m.name` hit `_lower_MemberExpr`'s
    pathlib `.name`->basename special case and every method collapsed onto
    ONE `counts` key. Compiled mojoc consequently believed every method of
    every struct was overloaded and emitted `Counter___init___0` /
    `Counter_inc_0_2` / `Counter_get_0_3` where the reference emits plain
    `Counter___init__` / `Counter_inc` / `Counter_get`."""
    counts = {}
    for m in stmt.methods:
        # `_as_funcdef_node`: same static-view requirement as the `stmt:
        # StructDef` annotation above — `m` is an untyped list element, so
        # `m.name`/`m.params` otherwise lower through runtime dispatch. When
        # `.params` came back as the miss sentinel, EVERY overload of a name
        # hashed `_param_sig_str(())` to the SAME id (`CStringSlice___
        # init___cbf29c`, then `_cbf29c_2`/`_3` disambiguation) where the
        # reference emits distinct `_d264de`/`_76edc3`/`_10ada0`.
        m = _as_funcdef_node(m)
        counts[m.name] = counts.get(m.name, 0) + 1
    used: dict = {}
    ids = []
    for m in stmt.methods:
        m = _as_funcdef_node(m)
        oid = ''
        if counts[m.name] > 1:
            oid = gimple_ctypes._method_overload_id(tuple(m.params or []), stmt.name, m.name)
            seen = used.setdefault(m.name, {})
            c = seen.get(oid, 0)
            seen[oid] = c + 1
            if c > 0:
                oid = f"{oid}_{c + 1}"
        ids.append(oid)
    return ids

def _struct_method_qualifier(gen, struct_name: str) -> str:
    """Home-module prefix for struct_name's method C symbols, or '' when
    no real module identity should apply.

    struct_name may be either a struct DEFINED in the module currently
    being compiled (self.module_name — already correct and unique per
    stdlib source file, see build_stdlib_dylib.py's use of
    module_loader.module_name_for_path) or one reached via `from X
    import Struct` and registered into _imported_struct_home (see the
    import-registration block that populates _imported_typedef_structs,
    and _register_reflected_struct for the dylib-reflection-only case).
    The imported case is checked first since an imported name is by
    definition not locally defined.

    Self-hosting exemption: gated on the file CURRENTLY being compiled
    being one of this repo's own .py sources, NOT on `self.module_name`
    being empty — module_name is NOT reliably empty for a self-hosted
    file: do_imports=True's _compile_imported_module recursion passes a
    real dotted-module-name-derived module_name for EVERY imported
    module, including when fire.py's own self-hosting bootstrap pulls in
    gimple_codegen.py/monomorphize.py/etc. as sibling imports of ITSELF
    (confirmed regression: those nested compiles got
    module_name='gimple_codegen'/'monomorphize', producing calls like
    `gimple_codegen_Parser___init__` that the hardcoded self-host tables
    — which assume bare names — don't recognize, breaking
    `make check-selfhost`).

    Deliberately narrower than the `_is_selfhost_file` path-only check
    used elsewhere (~13130) for the hardcoded field/method tables: that
    check alone (just "is this file under the repo directory") ALSO
    matches ordinary .mojo test fixtures written into runtime/ by the
    test suite (e.g. test_module_cache.py's rs_cnt.mojo, itself under
    this same repo tree) — confirmed regression: it wrongly suppressed
    qualification for a real user struct (Counter) with no connection to
    the self-hosting bootstrap at all. The self-hosting bootstrap is
    always this compiler's own Python implementation, always .py — no
    .mojo source is ever part of it — so requiring a .py extension here
    (in addition to the directory check) distinguishes the two exactly.

    Synthetic cross-module ABI types exemption: `Span` is unconditionally
    seeded into struct_field_types (gen_module, NOT gated on
    _is_selfhost_file, unlike every other hardcoded entry there — see
    that seed's own comment) as a compiler-synthesized fat-pointer
    convenience type, not a real struct owned by any one module's
    source. Its `.unsafe_ptr()`/`.__len__()` calls fall through to a
    SEPARATE, older "utility stub" fallback-declaration mechanism (the
    `_util_pairs` table, unrelated to this composer) that always
    forward-declares a single, permanently bare `Span_unsafe_ptr(...)`
    shared across every compile — confirmed regression: qualifying the
    CALL SITE only (there's nothing to qualify on the definition side;
    Span has no real source module) produced a call to
    `<qualifier>_Span_unsafe_ptr` with no matching declaration anywhere,
    since the stub table still (correctly, for this shared synthetic
    type) emits the bare name. Exempt it the same way MojoList/MojoDict
    (the other synthetic runtime-representation types) are naturally
    exempt by never going through struct-method mangling at all."""
    if struct_name == 'Span':
        return ''
    # GimpleGen: same shape of exemption as Span just above, for a
    # different reason. GimpleGen genuinely DOES have a real home module
    # (gimple_codegen.py) and a normal per-file compile of THAT file
    # correctly finds it via `_local_struct_names` (tier 1 below),
    # qualifying its `overload_suffix`/`overload_suffix_for`/etc. methods
    # as `gimple_codegen_GimpleGen_*` — but GimpleGen is also registered
    # as a SYNTHETIC struct (`_selfhost_register_gimplegen`) for every
    # OTHER gimple_*.py file's own compile (so `gen`/`self` params can be
    # typed `GimpleGen *`), and those OTHER files never see a real
    # `from gimple_codegen import GimpleGen`-shaped import to populate
    # `_imported_struct_home` with a matching qualifier — they fall
    # through to this function's own trailing bare `return ''` instead.
    # Removing the old blanket "any self-hosting file -> bare" override
    # (see _func_qualifier's matching comment) exposed exactly this:
    # confirmed via `make check-selfhost` linker errors ("_GimpleGen__
    # overload_suffix"/"_GimpleGen_overload_suffix_for" referenced but
    # undefined, the real bodies emitted as `gimple_codegen_GimpleGen_*`
    # only when gimple_codegen.py itself is the file being compiled).
    # GimpleGen's own methods must be bare EVERYWHERE, consistently,
    # regardless of which file references or defines them — the same
    # requirement Span has, just for a different underlying reason.
    if struct_name == 'GimpleGen' and getattr(gen, '_selfhost_gimplegen_registered', False):
        return ''
    # Every source below can hand back a raw module_name — which, for a
    # DOTTED package import (`import pkg.helper as m`, module_name ==
    # "pkg.helper"), contains '.' characters that are not valid in a C
    # identifier. _func_qualifier (the free-function analog of this
    # method) already sanitizes for exactly this reason (BUG-2026-049);
    # this struct-method sibling was missed at the time, so a struct
    # DEFINED in a dotted-package module (e.g. `transpiler.ast_rewrite`)
    # got an unsanitized qualifier like "transpiler.ast_rewrite" here,
    # producing an invalid C function name
    # (`transpiler.ast_rewrite_Rewriter__rewrite_param_list_ids`) that
    # GCC's parser chokes on at the literal '.' — and, once desynced,
    # goes on to misparse unrelated later lines in the same function
    # (BUG-2026-052: the "'transpiler' undeclared" errors reported deep
    # inside a docstring are that parser desync, not a real reference to
    # an undefined symbol). See _func_qualifier's own comment for the
    # same fix applied to the free-function case.
    def _sanitize_qualifier(q):
        # Strip LEADING dots before the '.'->'_' substitution: a raw
        # relative-import spelling (`.base`, from `_link_inline_modules`'
        # link-mode fallback — see `_compile_imported_module`'s temp_gen
        # `module_name=module_name`, which passes `stmt.module` through
        # completely unresolved) would otherwise sanitize to `_base`
        # (leading underscore) here, while `_emit_stdlib_import_externs`'
        # OWN relative-import resolution (`_resolve_relative`, run
        # against the SAME statement) already strips the dots before
        # this function ever sees the name and produces plain `base` —
        # two internally-consistent but MUTUALLY DISAGREEING spellings
        # of the identical module for the identical bare name. A call
        # site resolving one way and the definition resolving the other
        # way emits a reference to an undeclared identifier that (being
        # a bare, non-function name in a `(void *)` cast) silently
        # compiles to a null pointer instead of erroring — see
        # bugs/CODEGEN_link_mode_from_submodule_import_symbol_value_
        # call_segfault.md. Stripping leading dots here makes every
        # qualifier path converge on the same plain-name spelling
        # regardless of which one happened to run first.
        return q.lstrip('.').replace('.', '_').replace('-', '_') if q else q
    # NOT an early self-hosting-file bare short-circuit — see the free-
    # function sibling `_func_qualifier`'s matching comment: unconditionally
    # bare-ifying every struct reference from a self-hosting-flagged file
    # broke a genuine cross-module reference to a struct defined in a
    # DIFFERENT, non-self-hosting submodule (a downstream project's own
    # nested package). Removing it is a no-op for genuine self-hosting-
    # internal references (falls through to this function's own trailing
    # `return ''`) while letting a real `_imported_struct_home` resolution
    # win when one exists.
    # A struct genuinely DECLARED in the file currently being compiled
    # (gen_module's _local_struct_names, set once per GimpleGen instance
    # from that instance's own top-level stmts) always wins THIS
    # instance's own qualifier, checked BEFORE the shared, whole-
    # program `_imported_struct_home` registry below. `_imported_struct_
    # home` is keyed purely on bare struct name and shared across every
    # nested temp_gen in the whole transitive closure — when a locally-
    # defined class happens to share a bare name with an unrelated (or,
    # as here, a genuine base-class) struct some OTHER module in the
    # closure legitimately registered there, checking it first
    # mislabels THIS module's own struct as belonging to that OTHER
    # module, qualifying its methods with the WRONG (foreign) prefix.
    # Concrete real-world repro: `Lib/mailbox.py` defines its own
    # `class Message(email.message.Message):` — both classes are
    # legitimately named "Message" (a genuine subclass relationship,
    # not a coincidence), and `_merge_struct_inheritance` correctly
    # splices the base's own (shared, by-reference) FunctionDef method
    # objects into mailbox.py's derived struct's own `.methods` list so
    # each concrete struct gets its own callable copies (no C++ vtable
    # here). But with the OLD priority order, mailbox.py's own "Message"
    # struct-method-emission loop looked up `_imported_struct_home
    # ['Message'] == 'email.message'` (registered when Phase 0 compiled
    # the REAL imported email.message.Message) and reused THAT
    # qualifier for its own struct too — emitting EVERY one of
    # mailbox.py's own Message methods (both genuinely inherited ones
    # and its own locally-overridden ones like `__init__`) under the
    # exact same C symbols
    # (`email_message_Message___str__`/`___init__`/...) the real
    # email.message.Message module already emits once for itself,
    # producing ~45 GCC "redefinition of ..." errors in the SAME
    # translation unit (see bugs/CODEGEN_generator_function_Lib_
    # mailbox.md / bugs/hard/CODEGEN_same_bare_name_struct_collision_
    # across_modules.md). Reordering only changes behavior for this
    # exact ambiguous case (name present in BOTH _local_struct_names
    # AND _imported_struct_home simultaneously) — the overwhelmingly
    # common case where only one of the two is true is completely
    # unaffected, since a struct's OWN compiling temp_gen registers
    # ITS OWN `module_name` into `_imported_struct_home` under the same
    # value `_local_struct_names`-based qualification would produce
    # anyway (see `_compile_imported_module`'s Phase 0 registration),
    # so the two branches agree whenever there's no real collision.
    if struct_name in getattr(gen, '_local_struct_names', ()):
        return _sanitize_qualifier(gen.module_name) or ''
    # Only apply an IMPORTED module's qualifier to a struct genuinely
    # reached via `from X import Struct` and registered into
    # _imported_struct_home (or the dylib-reflection-only case) — never
    # as a guess for a name this compile doesn't recognize as either
    # local or (registered-)imported. An imported struct _register_
    # imported_structs' narrow registration gate missed must stay
    # unqualified (the historical, safe behavior) rather than get
    # mislabeled as belonging to this module.
    home = getattr(gen, '_imported_struct_home', None)
    if home and struct_name in home:
        return _sanitize_qualifier(home[struct_name])
    return ''


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_funcs.py)
# ---------------------------------------------------------------------------

# --- dependency _selfhost_gen_self_param_ctype (from gimple_gen_funcs.py) ---
def _selfhost_gen_self_param_ctype(gen, pname, ptype, node) -> str | None:
    """Self-hosting bootstrap only: in this compiler's OWN extracted GIMPLE
    backend modules (`gimple_*.py`), the former `GimpleGen` methods now live
    as module-level functions whose first parameter is the `GimpleGen`
    instance, conventionally named `gen` (`gimple_gen_*.py` / `gimple_cpp_*.py`)
    or `self` (`gimple_module_gen.py`'s `gen_module_impl`). Those params carry
    no annotation, so the generic resolver boxes them to opaque `int64_t` —
    and then EVERY `gen.<field>` / `gen.<method>(...)` inside the function
    lowers to a stubbed no-op or a runtime `_mojo_dispatch_getattr`, gutting
    the function body in the self-hosted binary (the compiled `compile_to_gimple`
    silently produced an empty `.ci` for every input; see doc/architecture.html
    §6 "roadmap to remove the shim"). Typing that first param as the real
    `GimpleGen *` struct pointer restores static field/method resolution.

    Narrow by construction: only an UNANNOTATED FIRST parameter named exactly
    `gen`/`self`, only for a function that IS actually one of this
    compiler's own extracted backend helpers, and only when `GimpleGen`
    is actually a registered struct in this compile.

    Originally checked `gen._current_filename`'s basename/directory instead
    of the function-name-index membership below — WRONG: `gen` here is
    WHICHEVER temp_gen happens to currently be compiling SOME file, not
    necessarily the file `node` (the function whose param we're typing) was
    itself defined in. A direct measurement (MOJO_DEBUG_SELFHOST_GEN,
    instrumenting the old file-based check) on a real `--dump-full fire.py`
    run showed every single rejection was `bad_basename` — meaning this
    function gets asked to type a gen/self param belonging to a
    gimple_gen_*.py-defined helper WHILE `gen._current_filename` is set to
    some OTHER, non-"gimple"-prefixed file (fire_compiler.py, module_
    loader.py, myinterpreter.py, fire.py, ...) that merely REFERENCES that
    helper — e.g. during a signature/forward-decl computation triggered
    from that other file's own compile, which then gets cached (`func_
    param_types` etc, shared dicts, first-computation-wins) and never
    recomputed once the helper's OWN home-file compile runs. Measured
    effect: only ~12 of 345 gen/self-first-param functions ended up typed
    `GimpleGen *` in the final output despite `_selfhost_gimplegen_
    registered` being True and the directory check passing on EVERY single
    call (only `bad_basename` ever fired) — confirming the file-identity
    check, not the registration-timing, was the actual gap.
    `_selfhost_extracted_fn_index()` already answers "is this function name
    one of the ones actually found, by a genuine `gimple_*.py` file scan, to
    have an unannotated gen/self first param" — independent of whichever
    gen happens to be asking. Using that instead fixes the false rejections
    without weakening the check at all (a name NOT in that index still
    correctly returns None)."""
    if ptype is not None:
        return None
    bare = pname.lstrip('*')
    if bare not in ('gen', 'self'):
        return None
    ps = getattr(node, 'params', None) or []
    if not ps or ps[0][0].lstrip('*') != bare:
        return None
    # The registration check is FIRST because it is the only CHEAP one, and
    # because the next step is not: `_selfhost_extracted_fn_index()` builds
    # its index by running the full parser + ast_rewriter over every
    # `gimple_*.py` / `mojo/middle` / `mojo/backend_gimple` file. This
    # function is asked about a `gen`/`self` first param on essentially every
    # parameter of every function in EVERY compile, but
    # `_selfhost_gimplegen_registered` is only ever set for an entry point
    # under this compiler's own source dir (see gimple_codegen's own comment
    # where it is set). So on every ordinary user/stdlib compile the old order
    # built that index and then threw the answer away at the guard that used
    # to sit below. Pure reordering of two independent, side-effect-free
    # conditions: both must hold, so the result is unchanged, and the index is
    # now simply never built when it cannot be used. Verified the index really
    # is skipped now (its cache key stays absent after a whole
    # Lib/contextlib.py compile) and that it still builds when it is needed.
    # (Found by a cProfile of Lib/contextlib.py, which attributed 21s of
    # cumtime to this index build — 715 calls with py_tokenize / parse_module
    # / _rewrite_node underneath. cProfile inflates that heavily: timing the
    # build directly gives ~1.5s for 448 entries, so the real win is ~1.5s
    # per process, paid once. Small but free, and a larger fraction of a
    # quick `fire.py build small.mojo` than of a whole-stdlib sweep. See
    # bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_rescan.md.)
    #
    # The flag itself: set once the GimpleGen registry pre-pass has run for
    # this (shared) compile — see _selfhost_register_gimplegen in
    # gimple_codegen.py, which parses `class GimpleGen`, unions in the fields
    # the extracted backend helpers bind (`_selfhost_scan_gimplegen_extra_
    # fields`), routes the synthetic StructDef through
    # `_imported_typedef_structs`, and locks a frozen `GimpleGen_*` signature
    # table via `_selfhost_locked_param_types`. Without that, typing `self` as
    # a struct pointer just trades "silently stubbed" for hard arity /
    # pointer-vs-int errors at every `self.<method>()` call site.
    if not getattr(gen, '_selfhost_gimplegen_registered', False):
        return None
    if getattr(node, 'name', None) not in _selfhost_extracted_fn_index():
        return None
    return 'GimpleGen *'

# --- dependency _sgfs_resolve_ann (from gimple_gen_funcs.py) ---
def _sgfs_resolve_ann(gen, _ann: str) -> str:
    """`gen._resolve_type(_ann)`, but checking the compiler's own FIXED
    AST-node classes (FunctionDef, VarDecl, ...) FIRST — these are real
    Python classes always importable from `gimple_ctypes`/`fire_compiler`,
    unlike an arbitrary user struct, which only becomes a known name once
    something registers it into the (deliberately near-empty, for this
    frozen-sig pass) `gen.struct_field_types`. Without this, an explicitly
    annotated `func: FunctionDef` parameter on one of `class GimpleGen`'s
    own methods (e.g. the `_infer_local_var_types` delegate) resolved to
    plain `int64_t` — `_resolve_type`'s `ann in gen.struct_field_types`
    check is correctly deterministic in general, but FunctionDef hadn't
    been registered into THIS root gen's struct_field_types yet at the
    point this one-time frozen-sig scan runs. That untyped `func` then made
    every `isinstance(node, ...)` check inside `_infer_local_var_types`'s
    own nested node-scanning closure operate on an opaque int64_t instead
    of a real AST-node pointer — for at least one real VarDecl node, the
    isinstance dispatch landed in the wrong elif branch (MultiAssignStmt)
    and read a garbage `.targets` field, SIGSEGV in strcmp on virtually any
    compiled program with at least one local variable, once the unrelated
    `_ensure_bool_cond` fix (see its own docstring) stopped an earlier
    crash from masking this one."""
    _cls = getattr(gimple_ctypes, _ann, None)
    if isinstance(_cls, type):
        return f"{_ann} *"
    return gen._resolve_type(_ann)

# --- dependency _ris_base (from gimple_gen_funcs.py) ---
def _ris_base(ann) -> str:
    """Hoisted out of `_register_imported_structs` — see `_ris_collect`'s
    docstring for why."""
    return ann.split('[', 1)[0].split('.')[0].strip() if isinstance(ann, str) else ''

# --- dependency _scan_from_imports_flat (from gimple_gen_funcs.py) ---
def _scan_from_imports_flat(src: str) -> list:
    """Every `from X import ...` in `src` as a flat list
    [mod0, names0, mod1, names1, ...] — a flat list (not a list of
    2-tuples, not a tuple return) so the self-hosted backend can iterate
    it by index without boxing. A parenthesised, multi-line import list
    (`from X import (\n a,\n b,\n)`) is joined into one names string."""
    out: list = []
    lines = src.split('\n')
    _i = 0
    _n = len(lines)
    while _i < _n:
        _ln = lines[_i].strip()
        _i += 1
        if not _ln.startswith('from '):
            continue
        _rest = _ln[5:]
        _p = _rest.find(' import')
        if _p < 0:
            continue
        _mod = _rest[:_p].strip()
        _names = _rest[_p + 7:].lstrip()
        if _names.startswith('('):
            _names = _names[1:]
            while (')' not in _names) and (_i < _n):
                _names = _names + ' ' + lines[_i].strip()
                _i += 1
            _cut = _names.find(')')
            if _cut >= 0:
                _names = _names[:_cut]
        out.append(_mod)
        out.append(_names)
    return out


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_funcs.py)
# ---------------------------------------------------------------------------


# --- dependency _selfhost_extracted_fn_index (from gimple_gen_funcs.py) ---
def _selfhost_extracted_fn_index() -> dict:
    """`{fn_name: FunctionDef}` for every top-level `def fn(gen|self, ...)`
    across this compiler's implementation sources (root `gimple_*.py` +
    `mojo/middle` + `mojo/backend_gimple`) — the extracted helper that a
    `class GimpleGen` delegate method `return <alias>.<fn>(self, ...)`
    forwards to. Cached with the field scanner's cache key."""
    _hit = _SELFHOST_EXTRA_FIELD_CACHE.get('fnidx')
    _sd = gimple_codegen._SELFHOST_DIR
    _files = sorted(_selfhost_impl_py_files(_sd))
    _key = tuple((f, gimple_ctypes.os.path.getmtime(f)) for f in _files)
    if _hit is not None and _hit[0] == _key:
        return _hit[1]
    _idx: dict = {}
    for _f in _files:
        try:
            _mod: list = ast_rewriter.rewrite(
                Parser(py_tokenize(open(_f).read())).with_filename(_f).parse_module())
        except Exception:
            continue
        for _fn in _mod:
            if (isinstance(_fn, FunctionDef) and _fn.params
                    and _fn.params[0][0].lstrip('*') in ('gen', 'self')
                    and _fn.name not in _idx):
                _idx[_fn.name] = _fn
    _SELFHOST_EXTRA_FIELD_CACHE['fnidx'] = (_key, _idx)
    return _idx



# --- dependency _SELFHOST_EXTRA_FIELD_CACHE (from gimple_gen_funcs.py) ---
_SELFHOST_EXTRA_FIELD_CACHE: dict = {}

