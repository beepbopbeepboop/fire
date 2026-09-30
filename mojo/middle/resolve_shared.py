"""Shared middle-end extracted from gimple_gen_resolve.py.

These helpers perform AST analysis / name+type resolution with no
C/GIMPLE emission. The original module keeps the emission paths and
imports this module for the shared pieces.
"""
from __future__ import annotations

from __future__ import annotations
import os
import re
import determinism_trace as _dtrace
from fire_compiler import IntLiteral, FloatLiteral, StringLiteral, TstringLiteral, BoolLiteral, EllipsisLiteral, NoneLiteral, IdentExpr, BinaryOp, CompareChain, UnaryOp, CallExpr, MemberExpr, SubscriptExpr, SliceExpr, TernaryExpr, WalrusExpr, LambdaExpr, ListExpr, DictExpr, SetExpr, TupleExpr, Comprehension, VarDecl, AssignStmt, AugAssignStmt, MultiAssignStmt, ReturnStmt, RaiseStmt, BreakStmt, ContinueStmt, PassStmt, AssertStmt, ExprStmt, ImportStmt, FromImportStmt, IfStmt, WhileStmt, ForStmt, FunctionDef, TryStmt, WithStmt, ComptimeIfStmt, ComptimeForStmt, ComptimeVarStmt, GlobalStmt, NonlocalStmt, DelStmt, MatchStmt, StructDef, TraitDef, YieldExpr, YieldFromExpr, AwaitExpr, _as_str, _sms_key, _as_assignstmt_node, _as_vardecl_node, _as_multiassignstmt_node
import regex_compile
import mlir
from mojo.middle.types import *  # noqa: F401,F403
from mojo.middle.exprtypes import *  # noqa: F401,F403
from mojo.middle.solvers import *  # noqa: F401,F403
import gimple_codegen  # constants used by some extracted helpers
import mojo.middle.types as gimple_ctypes
import mojo.middle.comptime as comptime_eval
import mojo.middle.solvers as gimple_solvers
import mojo.middle.exprtypes as gimple_exprtypes

# Bound-name walk lives in the light mojo.middle.boundnames module (formal
# imports that directly; this file re-exports so emit_resolve's
# `from mojo.middle.resolve_shared import _lbn_walk` keeps working).
from mojo.middle.boundnames import _lbn_target_names, _lbn_walk

def _closure_value_locals(gen, body: list) -> dict:
    """Map local name → 'MojoBoundMethod *'/'void *' for the locals of a
    function body that are assigned a nested-function (closure) VALUE
    (`var f = inner`, `f = inner`), resolved from the closure's capture
    shape (a capturing closure is a MojoBoundMethod*, a non-capturing
    one a bare function pointer — see _lower_IdentExpr's closure-value
    materialization). Used to seed return-type inference so it can see
    through a local alias (`def make_both(): var f = inner; return f`),
    which `_infer_local_var_types` can't (that pass never scans VarDecl
    and runs before `_all_closures` is populated)."""
    result: dict = {}

    def _walk(stmts: list):
        for st in stmts:
            # NB: keep the target-name / value pair off local vars that get
            # a `None` initializer — the self-hosted backend types those
            # `int`, which truncates the char*/AST-node pointer and makes
            # the `isinstance(val, IdentExpr)` tag read segfault. Route
            # straight through a helper whose params usage-infer to pointers.
            if isinstance(st, gimple_ctypes.AssignStmt) and isinstance(st.target, gimple_ctypes.IdentExpr):
                _record_closure_alias(gen, result, st.target.name, st.value)
            elif (isinstance(st, gimple_ctypes.VarDecl) and isinstance(st.name, str)
                    and ',' not in st.name and st.value is not None):
                _record_closure_alias(gen, result, st.name, st.value)
            if isinstance(st, gimple_ctypes.FunctionDef):
                continue
            for attr in ('then_body', 'else_body', 'body', 'finally_body'):
                sub = getattr(st, attr, None)
                if isinstance(sub, list):
                    _walk(sub)
            for _eb_cond, _eb_body in (getattr(st, 'elifs', None) or []):
                _walk(_eb_body)
            for _h in (getattr(st, 'handlers', None) or []):
                hb = getattr(_h, 'body', None)
                if isinstance(hb, list):
                    _walk(hb)

    _walk(body)
    return result

def _quick_type(gen, node) -> str:
    """Estimate C type of an expression without emitting code."""
    if isinstance(node, gimple_ctypes.IntLiteral):    return 'int64_t'
    if isinstance(node, gimple_ctypes.FloatLiteral):  return 'double'
    if isinstance(node, gimple_ctypes.BoolLiteral):   return '_Bool'
    if isinstance(node, gimple_ctypes.StringLiteral):
        return 'MojoBytes *' if getattr(node, 'is_bytes', False) else 'char *'
    if isinstance(node, gimple_ctypes.IdentExpr):
        if node.name in gen.var_types:
            return gen.var_types[node.name]
        if node.name == '__file__':
            # Mirrors _lower_IdentExpr's own '__file__' case, which always
            # yields a char* interned literal ("<bootstrap>") — without
            # this, the estimator guessed int64_t and mis-typed consumers
            # that consult it BEFORE lowering (e.g.
            # _lower_opaque_ctor's single-char*-arg identity passthrough).
            return 'char *'
        # A nested-function (closure) name referenced as a VALUE
        # (`return add`, `var f = add`, `foo(add)`) — a capturing
        # closure bundles its env with the lifted function pointer as a
        # `MojoBoundMethod *` (see _lower_IdentExpr's closure-value
        # materialization); a non-capturing one is a bare function
        # pointer. Recognized here so return-type inference
        # (`def make_adder(...): return add`) and call-site var typing
        # (`var add5 = make_adder(5)`) see the real value shape instead
        # of the int64_t default (which made `return add` return NULL).
        _ci = gen._closure_info_for_ident(node.name)
        if _ci is not None:
            return 'MojoBoundMethod *' if _ci.env_struct else 'void *'
        return 'int64_t'
    if isinstance(node, gimple_ctypes.BinaryOp):
        # 'in'/'not in' are missing from _CMP_OPS (generated_dispatch.py) —
        # real, pre-existing gap: falling through to
        # TypeLattice.join(type(left), type(right)) for e.g.
        # `dump = '--dump' in sys.argv` joins 'char *' (the string
        # literal) with whatever sys.argv itself quick-types to, giving
        # 'char *' instead of '_Bool'. The variable then gets declared
        # char* while every value stored in it is really a 0/1 _Bool bit
        # pattern; `if dump:`'s char*-truthiness coercion
        # (_ensure_bool_cond -> mojo_truthy_cstr) dereferences that
        # bit pattern as a pointer — a real crash for `dump = True`
        # (address 0x1). Found chasing self-hosted fire.py evaluating
        # its own `dump = '--dump' in sys.argv`.
        # _CMP_OPS (generated_dispatch.py) also contains 'and'/'or' —
        # correct for the STATEMENT-condition dispatch table it's really
        # meant for, wrong here: real Python `and`/`or` return whichever
        # OPERAND was selected (see the _lower_BinaryOp fix), never a bare
        # bool. Treating them as _Bool here mis-typed cas.py's own
        # `GMOJO_HOME = os.environ.get(...) or os.path.expanduser(...)`
        # global as `_Bool`: the real string value computed at runtime then
        # got cast down to a 0/1 bit pattern when stored into that
        # (wrongly-typed) global, and the next read (os.path.join(GMOJO_HOME,
        # 'cas')) dereferenced it as a pointer — a real crash at address 0x1.
        if node.op in ('and', 'or'):
            lt = gen._quick_type(node.left)
            rt = gen._quick_type(node.right)
            return gimple_ctypes.TypeLattice.join(lt, rt)
        if node.op in gimple_ctypes._CMP_OPS or node.op in ('in', 'not in'): return '_Bool'
        lt = gen._quick_type(node.left)
        rt = gen._quick_type(node.right)
        return gimple_ctypes.TypeLattice.join(lt, rt)
    if isinstance(node, gimple_ctypes.CompareChain):
        # Same as any single comparison above: a chained comparison
        # (`a < b < c`) always yields a bool, regardless of the operand
        # types being compared.
        return '_Bool'
    if isinstance(node, gimple_ctypes.UnaryOp):
        if node.op == 'not': return '_Bool'
        return gen._quick_type(node.operand)
    if isinstance(node, gimple_ctypes.TernaryExpr):
        return gimple_ctypes.TypeLattice.join(gen._quick_type(node.then_val),
                                gen._quick_type(node.else_val))
    if isinstance(node, gimple_ctypes.CallExpr) and isinstance(node.func, gimple_ctypes.IdentExpr):
        fname: str
        fname = node.func.name
        # Builtins whose VALUE is a real container. Every one of these
        # materialises a MojoList*/MojoSet*/MojoDict* at runtime, which is
        # what makes a module-level `z = sorted(...)` / `enumerate(...)` /
        # `reversed(...)` / `zip(...)` / `range(...)` / `tuple(...)` need the
        # row: the global's C type comes from here, and with no row it
        # defaulted to int64_t and the list printed as its ADDRESS (the value
        # was right, the declaration was not).
        #
        _BUILTIN_CTORS = {'set': 'MojoSet *', 'dict': 'MojoDict *', 'list': 'MojoList *',
                          # sorted()/reversed() both materialise a MojoList*
                          # (see _lower_builtin_sorted / _lower_builtin_reversed).
                          'sorted': 'MojoList *', 'reversed': 'MojoList *',
                          # enumerate() in VALUE position builds a list of
                          # (index, value) pair-lists; as a `for` target it is
                          # an iterator instead, but that path dispatches on
                          # the call's own shape, not on this type.
                          'enumerate': 'MojoList *',
                          # zip() chains mojo_zip, which walks MojoLists and
                          # returns a new one of pair-lists.
                          'zip': 'MojoList *',
                          # mojo_range/mojo_range3 return a MojoList*.
                          'range': 'MojoList *',
                          # tuple(x) lowers to the same MojoList as list(x).
                          'tuple': 'MojoList *',
                          # map(f, xs) / filter(f, xs) build their result in
                          # the CODEGEN (_build_per_element_list), not in the
                          # runtime: mojo_map/mojo_filter are identity stubs
                          # because a char* function pointer cannot call back
                          # into a GIMPLE-compiled body. Both really do
                          # produce a MojoList of results / kept elements.
                          'map': 'MojoList *', 'filter': 'MojoList *'}
        # Same `_locally_binds_name` gate as `_BUILTIN_SCALARS` just
        # below — `set`/`dict`/`list` are ordinary identifiers a module
        # could shadow with its own top-level def/import.
        if fname in _BUILTIN_CTORS and not gen._locally_binds_name(fname):
            return _BUILTIN_CTORS[fname]
        # Scalar builtins, matching the lowering (float()->double, etc.). Without
        # these, [float(i), ...] infers an int element type and nested float
        # lists silently read/return as int.
        _BUILTIN_SCALARS = {'float': 'double', 'int': 'int64_t', 'str': 'char *',
                            'len': 'int64_t', 'ord': 'int64_t', 'chr': 'char *',
                            'bool': '_Bool', 'repr': 'char *',
                            # isinstance()/all()/any() always return a plain
                            # Python bool regardless of their arguments' types
                            # (same "no argument-type inspection needed"
                            # reasoning as len/ord above) — without this,
                            # `return isinstance(...)`/`return all(...)`/
                            # `return any(...)` fell through to the int64_t
                            # default below. Real emission (_lower_builtin_
                            # isinstance/_lower_builtin_all_any) actually
                            # produces a C `int`, but declaring the more
                            # precise `_Bool` here still matches every other
                            # boolean-producing case above (BinaryOp compare/
                            # 'in', CompareChain, UnaryOp 'not', BoolLiteral)
                            # and avoids joining as an opaque int64_t/pointer
                            # against a sibling return path of a real pointer
                            # type (see bugs/hard/CODEGEN_comprehension_
                            # return_type_defaults_int64.md's follow-up note).
                            'isinstance': '_Bool', 'all': '_Bool', 'any': '_Bool'}
        # `all`/`any`/`isinstance` (and in principle any other name in
        # this table) are ordinary identifiers a module can legally
        # shadow with its own top-level def — e.g. tokenize.py's own
        # `def any(*choices): return group(*choices) + '*'`, called as
        # `any(pattern)` inside `Ignore = Whitespace + any(...) +
        # maybe(...)`. Without this gate, a call to the LOCAL `any`
        # quick-typed to `_Bool` (the builtin's return type) instead of
        # the real `char *`, so the surrounding `+` joined 'char *' with
        # '_Bool' and produced a bogus type ("invalid use of void
        # expression" downstream) instead of the correct 'char *'.
        # Mirrors the `open` builtin-shadowing gate at this class's
        # `_lower_builtin_all_any` call site — same `_locally_binds_name`
        # mechanism, see its docstring.
        if fname in _BUILTIN_SCALARS and not gen._locally_binds_name(fname):
            return _BUILTIN_SCALARS[fname]
        if fname in gen.struct_field_types:
            return f'{fname} *'
        # A bare call to a KNOWN COMPILED GENERATOR function (Milestone
        # B/C, self._generator_api) returns an opaque MojoGenerator* —
        # calling the generator function only CONSTRUCTS the coroutine,
        # it doesn't run the body (real Python/Mojo "calling a generator
        # function returns a generator object" semantics), so this must
        # be checked before the generic func_return_types fallback below
        # (a generator function was never given an ordinary return type
        # entry there — see bugs/CODEGEN_compiled_generator_not_first_
        # class_value.md). This dict is only fully populated after
        # gen_module's Pass 1.3d-gen eligibility loop runs (deliberately
        # AFTER Pass 1.3b/1.3d, per that loop's own ordering note) —
        # Pass 1.3b's FIRST call into this method (for a generator call
        # site) still sees it empty and falls through to the int64_t
        # default below, same as any other call to a not-yet-registered
        # callee; Pass 1.3f's unconditional full rerun of local-variable-
        # type inference (after the eligibility loop has populated
        # _generator_api) is what actually corrects `g = counter(3)`'s
        # inferred type, mirroring the exact same "corrective rerun"
        # pattern Pass 1.3e/1.3f already use for a plain unannotated-
        # callee return-type correction.
        if fname in gen._generator_api:
            return 'MojoGenerator *'
        # Same construction-shape rule for a generator reached through an
        # ALIASED/qualified cross-module import (`from a import walk as
        # walk_a`): the binding table records exactly the names THIS module
        # imported as compiled generators, so `var g = walk_a("x")` quick-
        # types to the same opaque MojoGenerator* a local definition would.
        if fname in getattr(gen, '_imported_generator_bindings', ()):
            return 'MojoGenerator *'
        # Scalar type constructors (Float64(x), Int8(x), etc.) — checked
        # BEFORE the opaque single-char*-arg passthrough just below, which
        # would otherwise wrongly claim a call like `Float64("not a
        # float")` (same shape: one char*-typed arg, uppercase name) as an
        # opaque-class passthrough and infer `char *` instead of the real
        # `double` — mis-declaring the assignment target and producing an
        # invalid `(char *)<double value>` cast downstream. Mirrors
        # gimple_gen_calls.py's `_lower_scalar_ctor` dispatch exactly (same
        # shared table + same not-shadowed gate), since that's what the
        # actual lowering does for this shape.
        if (fname in gimple_ctypes._SCALAR_CTORS and fname not in gen.func_return_types
                and fname not in gen.imported_symbols):
            return gimple_ctypes._SCALAR_CTORS[fname]
        # Single-char*-argument OPAQUE-constructor passthrough (`Path(x)`
        # where `Path` is an imported class this compile never inlined):
        # _lower_opaque_ctor returns its single string argument UNCHANGED
        # for this exact shape (the strings-as-path-values convention `/`
        # on a char* receiver already relies on), so the estimator must
        # mirror that or every consumer of this pre-pass (global/local
        # variable typing, return-type inference) mis-declares the result
        # int64_t against a body that produces a real char*.
        if (fname[:1].isupper() and fname not in gen.func_return_types
                and fname not in gen.imported_symbols
                and not gen._locally_binds_name(fname)
                and len(node.args) == 1 and not getattr(node, 'kwargs', None)
                and gen._quick_type(node.args[0]) == 'char *'):
            return 'char *'
        return gen.func_return_types.get(fname, 'int64_t')
    if isinstance(node, gimple_ctypes.CallExpr) and isinstance(node.func, gimple_ctypes.MemberExpr):
        # A receiver this codegen KNOWS is a registered user struct resolves
        # through its own mangled method symbol, and it has to be checked
        # BEFORE every name-keyed row below.
        #
        # Those rows are keyed on the method's NAME alone, because at this
        # point the receiver's type is usually still unknown (this pre-pass
        # runs before a function's own local types exist — the blind spot
        # `.read()`'s own comment documents). But a user class is free to
        # define a method called `items`, `keys`, `values`, `split`, `read`
        # or `decode`, and when the receiver IS known, the name is no longer
        # evidence of anything. Leaving the order as it was, `Box.items(...)`
        # quick-typed `MojoList *` and the enclosing `def use(b): return
        # b.items(1)` was DECLARED `MojoList *` while its body dispatched the
        # real `Box_items` returning an int64_t — a wrong prototype against a
        # correct body, which is the same value-identity failure this row
        # exists to prevent, one level below the parameter it fixed.
        #
        # Gated on `var_types` actually naming a registered struct, so every
        # still-unknown receiver keeps exactly the old behaviour and only a
        # provable one changes.
        if isinstance(node.func.obj, gimple_ctypes.IdentExpr):
            _sot = gen.var_types.get(node.func.obj.name, '')
            if _sot.endswith(' *'):
                _ssn = gimple_exprtypes._struct_name_of(_sot)
                if _ssn in gen.struct_field_types:
                    _smeth = node.func.member
                    if (_ssn, _smeth) in gen._generator_method_api:
                        return 'MojoGenerator *'
                    _srt = gen.func_return_types.get(f"{_ssn}_{_smeth}")
                    if _srt:
                        return _srt
        # .read()/.readline()/.readlines() on ANY receiver shape (not just
        # a plain IdentExpr file handle) — e.g. `sys.stdin.read()` (obj is
        # itself a MemberExpr) or `open(path).read()` (obj is a CallExpr).
        # The IdentExpr-only checks below never match these chained
        # shapes, so this must come first and be receiver-shape-agnostic.
        if node.func.member in ('read', 'readline') and not node.args:
            return 'char *'
        if node.func.member == 'readlines':
            return 'MojoList *'
        # Container-returning METHODS, receiver-shape-agnostic for the same
        # reason as read/readline/readlines above: the receiver may be a
        # MemberExpr (`cfg.keys()`) or a CallExpr (`open(p).read()` /
        # `dict(a=b).items()`), and an IdentExpr-only check misses both.
        # Each of these lowers to a runtime helper that returns a real
        # MojoList*: mojo_dict_keys / mojo_dict_values / mojo_dict_items and
        # mojo_str_split / mojo_str_rsplit / mojo_str_splitlines. Without a
        # row the estimator said int64_t, so a module-level
        # `z = d.keys()` or `z = s.split(",")` declared the global as an
        # integer and printed the list's ADDRESS — the same shape of gap as
        # the builtin rows above, and the value was right either way.
        #
        # `copy` is deliberately absent: its result type depends on the
        # receiver (list.copy -> MojoList, dict.copy -> MojoDict, set.copy ->
        # MojoSet), so a single row would be wrong for two of the three.
        if node.func.member in ('keys', 'values', 'items', 'split', 'rsplit',
                                'splitlines', 'rsplitlines'):
            return 'MojoList *'
        # `Path(x).resolve()` (no-arg) on a path-shaped char* receiver —
        # real char* result (POSIX realpath via int64_t_realpath, see
        # _lower_str_method's 'resolve' case); quick-type mirrors it so
        # chained shapes like `Path(f).resolve().parent` type the whole
        # chain correctly.
        if (node.func.member == 'resolve' and not node.args
                and gen._quick_type(node.func.obj) == 'char *'):
            return 'char *'
        # Module method calls: re.sub → char *, str.join → char *, etc.
        if isinstance(node.func.obj, gimple_ctypes.IdentExpr):
            mod: str
            mod = node.func.obj.name
            meth: str
            meth = node.func.member
            # file_handle.read()/.readline(): this pre-pass runs before
            # any real var_types are populated (it's the upfront scan
            # that *produces* them), so `ot = self.var_types.get(mod, '')`
            # below is always empty for a `with open(...) as f:` handle
            # at this point — falls through to the int64_t default,
            # regardless of what `mod` actually is. Real bug found via
            # `with open(input_file) as f: src = f.read()` in fire.py's
            # own main(): `src` got declared int64_t while every value
            # written to it was really a char* pointer to the file
            # content, so len(src) and print(src) both read it as a
            # raw integer instead of the string.
            if meth in ('read', 'readline') and not node.args:
                return 'char *'
            if meth == 'readlines':
                return 'MojoList *'
            # Unambiguous string-only methods: in this codebase's Python
            # subset, these are only ever called on real strings — return
            # char* regardless of whether the receiver's own type is known
            # yet (this pre-pass runs before var_types is populated, so
            # `ot` below is empty here for a not-yet-declared local, same
            # blind spot as the .read()/.readline() case above). Missing
            # this made e.g. `expanded = line.expandtabs(N)` infer
            # `expanded` as int64_t; a later `len(expanded)` then treated
            # the real char* as a boxed MojoList* pointer, reading garbage
            # struct fields as the string's "length" — the real source of
            # `_strip_inline_comment`-style tokenizer stack corruption
            # (a huge garbage `indent` value). Found via py_tokenize's own
            # `expanded = line.expandtabs(_INDENT_SIZE)`.
            if meth in ('expandtabs', 'lstrip', 'rstrip', 'strip', 'lower',
                        'upper', 'title', 'capitalize', 'swapcase',
                        'replace', 'format', 'zfill', 'center', 'ljust', 'rjust',
                        'encode', 'decode', 'join', 'group'):
                return 'char *'
            if mod == 're' and meth == 'sub':    return 'char *'
            if mod == 're' and meth == 'match':  return 'int'
            if mod == 're' and meth == 'search': return 'int'
            if mod == 'os' and meth in ('getcwd', 'path'): return 'char *'
            if mod == 'os' and meth == 'listdir': return 'MojoList *'
            if mod == 'sysconfig' and meth == 'get_config_var': return 'char *'
            if mod == 'sys': return 'int'
            # `struct.Struct(...)` / `struct.pack(...)` / `struct.unpack(...)`:
            # the module-level runtime constructors whose results are NAMED,
            # non-container handle types with their own attribute reads
            # (`MojoStructFmt *`'s `format`/`size` and its five pack/unpack
            # methods), which is what makes the erasure VISIBLE for them —
            # unlike a returned `MojoBytes *`, whose contents still read fine
            # through a wrongly-boxed int64_t on this runtime.
            #
            # This is the table `_lower_struct_module_call` (the authoritative
            # lowering) is itself driven by, read here so the two cannot
            # disagree; the guards mirror that branch's exactly — a known
            # local/param named `struct` is not the module, and a call with
            # keyword arguments is not one it lowers. Without this row a
            # function whose only `return` is `struct.Struct("<HH")` was
            # declared `int64_t`, so its body boxed the real handle through
            # `void *` to satisfy the prototype, and the consumer's `s.size`
            # degraded to `_mojo_dispatch_getattr` on an untyped value —
            # `AttributeError: size` from a program CPython runs cleanly.
            if (mod == 'struct' and meth in gimple_ctypes._STRUCT_MODULE_FN_RETVALS
                    and mod not in gen.var_types
                    and not getattr(node, 'kwargs', None)):
                return gimple_ctypes._STRUCT_MODULE_FN_RETVALS[meth]
            # dict.keys()/.values()/.items(): _lower_dict_method (below)
            # lowers all three to a real `MojoList *` (mojo_dict_keys/
            # _values/_items) — but this pre-pass had no case for them at
            # all. Unlike the string-only methods just above, gating this
            # on `self.var_types.get(mod)` doesn't work: this pre-pass
            # (_collect_return_types/_infer_return_type, Pass 2b) runs
            # BEFORE a function's own LOCAL variable types are known —
            # `modules = {}` earlier in the SAME function body being
            # scanned hasn't been recorded into var_types yet at this
            # point (same blind spot the .read()/.readline() note above
            # already documents for `with open(...) as f:`). Treated the
            # same way as the "Unambiguous string-only methods" block
            # just above instead: `.keys`/`.values`/`.items` are
            # dict-view-only method NAMES in this codebase's supported
            # subset (no other builtin container type has them), so
            # unconditionally returning MojoList* here is safe by the
            # same reasoning that block already uses. Real:
            # Lib/modulefinder.py's `find_all_submodules` has an early
            # bare `return` (None) followed by `return modules.keys()`;
            # the wrong int64_t forward-declaration against a body that
            # actually returns a MojoList* pointer produced GCC's honest
            # `-fgimple` refusal ("invalid conversion in return
            # statement"). See CODEGEN_generator_function_Lib_
            # modulefinder.md.
            if meth in ('keys', 'values', 'items') and not node.args:
                return 'MojoList *'
            # A receiver that IS a registered user struct was already resolved
            # through its mangled method symbol at the TOP of this branch —
            # see that block's comment for why the name-keyed rows above must
            # not be allowed to answer first. Nothing left to do here.
        # os.path.basename(...)/.splitext(...)/etc.: node.func.obj here is
        # itself a MemberExpr (os.path), not a plain IdentExpr, so the
        # `mod == 'os'` branch above never matches this chained shape at
        # all — this pre-pass had no case for it whatsoever. Mirrors the
        # real lowering (the os.path.* block in lower_expr): basename/
        # expanduser return char*, splitext returns a 2-element char*
        # list. Real bug found via
        # `os.path.splitext(os.path.basename(input_file))[0]` in fire.py's
        # build_executable: the parameter fix above still left this local
        # variable declared int64_t (a real char* pointer value shown as
        # a raw address by print()).
        elif (isinstance(node.func.obj, gimple_ctypes.MemberExpr)
                and isinstance(node.func.obj.obj, gimple_ctypes.IdentExpr)
                and node.func.obj.obj.name == 'os' and node.func.obj.member == 'path'):
            if node.func.member in ('basename', 'expanduser'):
                return 'char *'
            if node.func.member in ('splitext', 'split', 'splitdrive', 'splitroot'):
                # All string-tuple results in this codegen's model —
                # splitext -> [root, ext] (int64_t_splitext + a built list),
                # split -> [head, tail] (int64_t_path_split),
                # splitdrive -> [drive, tail], splitroot -> [drive, root, tail].
                return 'MojoList *'
        # Chained string methods, e.g. `s.replace(a, b).replace(c, d)` —
        # the receiver here is itself a CallExpr (the inner .replace()),
        # not a plain IdentExpr, so the `isinstance(node.func.obj,
        # IdentExpr)` branch above never matches this shape at all. Same
        # class of gap as the os.path.* chained case just above: without
        # this, format_token()'s `tok.value.replace(...).replace(...)`
        # (fire_compiler.py's own tokenizer dump helper) declared its
        # result int64_t, corrupting the pointer on every read.
        if (node.func.member in ('expandtabs', 'lstrip', 'rstrip', 'strip', 'lower',
                    'upper', 'title', 'capitalize', 'swapcase',
                    'replace', 'format', 'zfill', 'center', 'ljust', 'rjust',
                    'encode', 'decode', 'join')
                and gen._quick_type(node.func.obj) == 'char *'):
            return 'char *'
    if isinstance(node, gimple_ctypes.MemberExpr):
        # A modelled module attribute (see _MODULE_ATTR_CTYPES's docstring
        # for why this lookup is shared with the lowering) has a settled
        # ctype. Checked BEFORE the generic struct-field path: the
        # receiver is a module marker, so `sn` is empty, `_fields` is
        # empty, and the fallthrough would report the scalar `int64_t`
        # while the lowering produced a real `MojoDict *` / `MojoList *`.
        _mat = gimple_ctypes._module_attr_ctype(
            gimple_ctypes._as_str(node.obj.name)
            if isinstance(node.obj, gimple_ctypes.IdentExpr) else '',
            _as_str(node.member))
        if _mat:
            return _mat
        ot: str
        ot = gen._quick_type(node.obj)
        sn: str
        sn = gimple_exprtypes._struct_name_of(ot)
        _fields = gen.struct_field_types.get(sn, {})
        if node.member in _fields:
            return _fields[node.member]
        # `node.member` isn't a real FIELD on this struct — it may be a
        # bound METHOD/`@property` read without call syntax (`self.
        # filename.parent`, `filename` a 0-arg method/property). Real
        # codegen (_lower_MemberExpr's object-lowering path) auto-
        # invokes such a value before doing the outer member lookup —
        # this static type-guessing pre-pass (used by _infer_return_
        # type/_collect_return_types to pick a function's own C return
        # type from its `return` statements) must mirror that or a
        # `return self.prop.attr`-shaped return silently defaulted to
        # int64_t against a body that actually returns a real pointer:
        # the compiled function's OWN declared C return type disagreed
        # with what its body computed (the `.attr` field read itself
        # was already correct — only the enclosing function's
        # signature was wrong). Same struct-method detection
        # `_lower_MemberExpr` itself already uses to recognize "this
        # member is a bound-method value, not a field" (see that
        # method's `_lower_bound_method_value` call site). See bugs/
        # COMPILE_FAIL_zipfile__path___init__.md.
        if sn and (f"{sn}_{node.member}" in gen.func_return_types
                   or _sms_key(sn, node.member) in gen._struct_method_signatures):
            candidates = gen._struct_method_signatures.get(_sms_key(sn, node.member))
            overload_id = ''
            if candidates and len(candidates) == 1:
                overload_id = candidates[0].get('overload_id', '') or ''
            mangled = gen._struct_method_csym(sn, node.member, overload_id)
            return gen.func_return_types.get(
                mangled, gen.func_return_types.get(f"{sn}_{node.member}", 'int64_t'))
        # pathlib.Path attribute reads on a path-shaped char* value —
        # `.name` is basename and `.parent` is dirname, both real char*
        # results (see _lower_MemberExpr's matching char*-receiver case).
        if ot == 'char *' and node.member in ('name', 'parent'):
            return 'char *'
        # Receiver's struct type unresolved (sn not in struct_field_types —
        # e.g. a free function's `self` param typed int64_t, so ot is
        # int64_t and _fields is empty). Fall back to the same
        # unambiguous-member search _lower_MemberExpr uses for opaque
        # receivers (_known_field_type) so this estimator and actual
        # lowering agree on the field's C type. Without this they
        # diverge: _quick_type says int64_t while lower_expr returns the
        # real field type, and any consumer that precomputes a merge type
        # from _quick_type — notably the and/or short-circuit lowering's
        # `_rq = _quick_type(right); res_type = join(ltype, _rq)` — picks
        # the WRONG container kind for the result temp and then fails to
        # coerce the real value into it (concretely: module_gen's
        # `dict or set or set or set` chain, join(Dict*, int64_t)=Dict*
        # vs actual Set*, "cannot coerce MojoSet * to MojoDict *").
        if not _fields:
            _kt = gen._known_field_type(node.member)
            if _kt is not None:
                return _kt
        return 'int64_t'
    if isinstance(node, gimple_ctypes.ListExpr):  return 'MojoList *'
    if isinstance(node, gimple_ctypes.DictExpr):  return 'MojoDict *'
    if isinstance(node, gimple_ctypes.SetExpr):   return 'MojoSet *'
    if isinstance(node, gimple_ctypes.TupleExpr): return 'MojoList *'
    if isinstance(node, gimple_ctypes.Comprehension):
        # `[x for x in y]`/`{k: v for ...}`/`{x for x in y}`/a
        # generator-expression — a distinct AST node from the literal
        # ListExpr/DictExpr/SetExpr cases just above (fire_compiler.py),
        # which this method had NO case for at all: falling through to
        # the int64_t default at the bottom of this method while the
        # REAL emission (_lower_comprehension, below) constructs and
        # returns a real MojoList*/MojoDict*/MojoSet* pointer. For a
        # function whose SOLE `return` is a bare comprehension (real:
        # Lib/calendar.py's Calendar.monthdatescalendar and 5 sibling
        # methods), this method is what populates the function's
        # forward-declared return type (_collect_return_types) — a
        # wrong int64_t declaration there, against a body that actually
        # constructs/returns a pointer, produces GCC's honest
        # `-fgimple` refusal ("non-trivial conversion in
        # 'integer_cst'"/"type mismatch in binary expression"). Mirrors
        # _lower_comprehension's own kind->type mapping exactly (a
        # generator-expression is converted to a MojoList* there too,
        # per that method's own "convert to list for simplicity"
        # comment) rather than inventing a second, possibly-diverging
        # mapping — an unrecognized kind falls to the SAME int64_t
        # default this method already used for every other
        # unmatched/unsupported node shape (matching
        # _lower_comprehension's own TODO-kind fallback, which emits a
        # plain scalar 0, not a pointer). See
        # CODEGEN_comprehension_return_type_defaults_int64.md.
        if node.kind == 'dict':
            return 'MojoDict *'
        if node.kind == 'set':
            return 'MojoSet *'
        if node.kind in ('list', 'generator'):
            return 'MojoList *'
        return 'int64_t'
    # A slice's type is the type of the object being sliced (mirrors _lower_slice:
    # list slice -> list, str slice -> str, plain pointer -> same pointer).
    if isinstance(node, gimple_ctypes.SliceExpr): return gen._quick_type(node.obj)
    if isinstance(node, gimple_ctypes.SubscriptExpr):
        # container[idx]: result is the container's element type, read from the
        # same side-tables the subscript lowering uses. Covers nested reads
        # (outer[i][j]) via the container's nested element type.
        obj = node.obj
        # sys.argv[i]: a real MojoList * of strings (mojo_get_argv(), see
        # the `sys`/`argv` MemberExpr lowering), but `obj` here is a
        # MemberExpr, not a tracked IdentExpr — this pre-pass had no case
        # for it at all, so it fell through to the int64_t default below.
        # Real bug found via `input_file = sys.argv[1]` in fire.py's own
        # build command handling: the variable got declared int64_t while
        # every value stored in it was actually a char* pointer (same
        # bit pattern, so no crash — just wrong for any later use, e.g.
        # print() showing a raw address instead of the string).
        if (isinstance(obj, gimple_ctypes.MemberExpr) and isinstance(obj.obj, gimple_ctypes.IdentExpr)
                and obj.obj.name == 'sys' and obj.member == 'argv'):
            return 'char *'
        # os.path.splitext(...)[0]: the CallExpr case above returns
        # 'MojoList *' for splitext's own type, but this needs the
        # *element* type for the subscript — always char* (root, ext),
        # for any index. Same os.path.* blind spot as above.
        if (isinstance(obj, gimple_ctypes.CallExpr) and isinstance(obj.func, gimple_ctypes.MemberExpr)
                and isinstance(obj.func.obj, gimple_ctypes.MemberExpr)
                and isinstance(obj.func.obj.obj, gimple_ctypes.IdentExpr)
                and obj.func.obj.obj.name == 'os' and obj.func.obj.member == 'path'
                and obj.func.member in ('splitext', 'split', 'splitdrive', 'splitroot')):
            return 'char *'
        if isinstance(obj, gimple_ctypes.IdentExpr):
            e = gen._elem_types.get(obj.name)
            if e:
                return e
        elif isinstance(obj, gimple_ctypes.SubscriptExpr) and isinstance(obj.obj, gimple_ctypes.IdentExpr):
            ne = gen._nested_elem_types.get(obj.obj.name)
            if ne:
                return ne
    return 'int64_t'

def _infer_list_elem_type(gen, elements: list) -> str:
    """Determine element C type for a list/set/tuple literal."""
    if not elements:
        return 'int64_t'
    # Explicit loop (NOT a comprehension): the self-hosted compiler has no
    # lowering for `[f(x) for x in lst]` over a runtime MojoList (the
    # comprehension emits a no-op, leaving `types` NULL -> join_all(NULL)
    # segfault). List comprehension lowering only works for a small
    # hardcoded set of shapes.
    types = []
    for _e in elements:
        types.append(gen._quick_type(_e))
    return gimple_ctypes.TypeLattice.join_all(types) if types else 'int64_t'

def _prepass_callee_key(gen, node) -> str | None:
    """Symbol key of a CallExpr's callee for the pre-pass's
    _return_elem_types lookup — mirrors the bare {struct}_{method}
    mangling the call sites and _gen_struct_method's current_func_name
    both use ('self' resolves to the struct being pre-passed)."""
    f = node.func
    if isinstance(f, gimple_ctypes.IdentExpr):
        return f.name
    if isinstance(f, gimple_ctypes.MemberExpr) and isinstance(f.obj, gimple_ctypes.IdentExpr) and f.obj.name == 'self':
        if gen._prepass_struct:
            return f"{gen._prepass_struct}_{f.member}"
    return None

def _collect_local_container_elems(gen, stmts) -> None:
    """Populate self._prepass_local_elems from a function's assignments:
    a named local holding a container literal / container-returning call,
    or both halves of a `xt, xv = <container-returning call>` unpack."""
    for node in stmts:
        if isinstance(node, gimple_ctypes.AssignStmt):
            t, v = node.target, node.value
            if isinstance(t, gimple_ctypes.IdentExpr):
                e = gen._quick_container_elem(v)
                if e is not None:
                    gen._prepass_local_elems[t.name] = e
            elif isinstance(t, gimple_ctypes.TupleExpr):
                # `xt, xv = <container-returning call>` — a tuple is
                # homogeneous at the C level, so both targets get the
                # container's element type. A literal RHS assigns each
                # element with its own type (skip).
                if not isinstance(v, (gimple_ctypes.ListExpr, gimple_ctypes.TupleExpr, gimple_ctypes.SetExpr)):
                    e = gen._quick_container_elem(v)
                    if e is not None:
                        for sub in t.elements:
                            if isinstance(sub, gimple_ctypes.IdentExpr):
                                gen._prepass_local_elems[sub.name] = e
        elif isinstance(node, gimple_ctypes.VarDecl):
            if (isinstance(node.name, str) and ',' not in node.name
                    and node.value is not None):
                e = gen._quick_container_elem(node.value)
                if e is not None:
                    gen._prepass_local_elems[node.name] = e
        elif isinstance(node, gimple_ctypes.IfStmt):
            gen._collect_local_container_elems(node.then_body)
            for _, eb in node.elifs:
                gen._collect_local_container_elems(eb)
            if node.else_body:
                gen._collect_local_container_elems(node.else_body)
        elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
            gen._collect_local_container_elems(node.body)
        elif isinstance(node, gimple_ctypes.TryStmt):
            gen._collect_local_container_elems(node.body)
            for h in node.handlers:
                gen._collect_local_container_elems(h.body)
            if node.else_body:
                gen._collect_local_container_elems(node.else_body)
            if node.finally_body:
                gen._collect_local_container_elems(node.finally_body)
        elif isinstance(node, gimple_ctypes.WithStmt):
            gen._collect_local_container_elems(node.body)

def _collect_return_elems(gen, stmts, acc) -> None:
    """Collect container element types of return values (structural walk
    mirroring _collect_return_types)."""
    for node in stmts:
        if isinstance(node, gimple_ctypes.ReturnStmt):
            if node.value is not None:
                e = gen._quick_container_elem(node.value)
                if e is not None:
                    acc.append(e)
        elif isinstance(node, gimple_ctypes.IfStmt):
            gen._collect_return_elems(node.then_body, acc)
            for _, eb in node.elifs:
                gen._collect_return_elems(eb, acc)
            if node.else_body:
                gen._collect_return_elems(node.else_body, acc)
        elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
            gen._collect_return_elems(node.body, acc)
        elif isinstance(node, gimple_ctypes.TryStmt):
            gen._collect_return_elems(node.body, acc)
            for h in node.handlers:
                gen._collect_return_elems(h.body, acc)
            if node.else_body:
                gen._collect_return_elems(node.else_body, acc)
            if node.finally_body:
                gen._collect_return_elems(node.finally_body, acc)
        elif isinstance(node, gimple_ctypes.WithStmt):
            gen._collect_return_elems(node.body, acc)

def _infer_return_elem_type(gen, body, func_def=None,
                            _base_var_types=None) -> str | None:
    """Infer the container ELEMENT type a function returns, or None when it
    returns no statically-identifiable container. See _quick_container_elem.

    HERMETIC: runs against a snapshot of the shared type-scratch maps
    (var_types/_elem_types/_dict_val_types/_actual_types) so scanning one
    function's body can neither poison nor be poisoned by the scratch left
    behind by the previously-scanned function in Pass 2c's whole-program
    loop. Before this was hermetic, whatever function happened to be
    scanned just before (module processing order varies with the closure
    import graph) leaked its var_types into this scan and mis-typed unrelated
    callees' tuple returns as int64_t (comptime.py's `ret, params =
    _signature(...)` unpacked params as int64_t -> mojo_strlen(int))."""
    # CLEAN-SLATE scan: derive every fact from THIS body alone. Ambient
    # var_types/_elem_types carry other functions' locals (often common
    # names like 'params'/'ret' typed int64_t), which poisoned tuple-return
    # element inference depending on module processing order.
    _saved = (gen.var_types, gen._elem_types, gen._dict_val_types,
              gen._actual_types, getattr(gen, '_prepass_struct', None))
    # Phase 4 (bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
    # rescan.md): the per-call seed used to be built by iterating the
    # ENTIRE tree-shared `func_return_types` dict one setdefault at a
    # time — O(|func_return_types|) interpreted work on EVERY call, and
    # Pass 2c calls this once per function per fixpoint iteration per
    # nesting level (275k calls × ~1800 entries ≈ 500M setdefaults for
    # Lib/contextlib.py). `func_return_types` is provably frozen for the
    # duration of one Pass 2c run (its loop touches only bodies via this
    # scan and writes only `self._return_elem_types`; nothing reachable
    # from here registers return types), so the caller may hoist ONE
    # snapshot of it per run and hand it in as `_base_var_types` — each
    # call then copies that snapshot at C speed instead of re-seeding
    # entry-by-entry. Content is identical either way; when no snapshot
    # is supplied the legacy path below still seeds from
    # gen.func_return_types directly.
    gen.var_types = dict(_base_var_types) if _base_var_types is not None else {}
    # Seed with facts that are TRUE regardless of processing order: this
    # function's own annotated params, every registered cross-function
    # return type (imported externs + Pass-2a inferred), and the fixed
    # return types of leaf helpers exported by gimple_ctypes.
    if func_def is not None:
        for pname, ptype in (func_def.params or []):
            gen.var_types[pname] = (gimple_ctypes._mojo_type(ptype)
                                    if ptype else 'int64_t')
    if _base_var_types is None:
        for k, v in gen.func_return_types.items():
            gen.var_types.setdefault(k, v)
    for k, v in KNOWN_LEAF_RETS.items():
        gen.var_types.setdefault(k, v)
    gen._elem_types = dict(_saved[1])   # container elem types stay visible
    gen._dict_val_types = {}
    gen._actual_types = dict(_saved[3])
    gen._prepass_local_elems = {}
    # Scalar assignment seeding: `ret = _mojo_type(...)` — record the
    # callee's registered return type for simple Ident targets so the
    # ReturnStmt element walk can type non-container locals. Container
    # locals are handled by _collect_local_container_elems above.
    def _seed_scalar_assigns(nodes):
        for nd in nodes:
            if isinstance(nd, gimple_ctypes.AssignStmt) \
                    and isinstance(nd.target, gimple_ctypes.IdentExpr) \
                    and isinstance(nd.value, gimple_ctypes.CallExpr):
                callee = getattr(nd.value.func, 'name', None)
                if callee and nd.target.name not in gen.var_types:
                    rt = gen.func_return_types.get(callee)
                    if rt is None and callee in ('_mojo_type', '_c_escape', '_safe_name'):
                        rt = 'char *'
                    if rt:
                        gen.var_types[nd.target.name] = rt
            elif isinstance(nd, gimple_ctypes.IfStmt):
                _seed_scalar_assigns(nd.then_body)
                for _, eb in (getattr(nd, 'elifs', None) or []):
                    _seed_scalar_assigns(eb)
                if nd.else_body:
                    _seed_scalar_assigns(nd.else_body)
            elif isinstance(nd, (gimple_ctypes.ForStmt, gimple_ctypes.WhileStmt)):
                _seed_scalar_assigns(nd.body)
            elif isinstance(nd, gimple_ctypes.TryStmt):
                _seed_scalar_assigns(nd.body)
                for h in nd.handlers:
                    _seed_scalar_assigns(h.body)
            elif isinstance(nd, gimple_ctypes.WithStmt):
                _seed_scalar_assigns(nd.body)

    try:
        _seed_scalar_assigns(body)
        gen._collect_local_container_elems(body)
        acc = []
        gen._collect_return_elems(body, acc)
        if not acc:
            return None
        return gimple_ctypes.TypeLattice.join_all(acc)
    finally:
        gen.var_types, gen._elem_types, gen._dict_val_types, \
            gen._actual_types, _ps = _saved
        gen._prepass_struct = _ps

def _local_value_type(gen, value) -> str:
    """The C type an unannotated local takes from one assigned VALUE, for the
    local-variable pre-pass.

    An integer LITERAL contributes `int64_t`, not the `int` `_quick_type` reports
    for a small literal. `int` is what a literal's own type is (right for an
    argument or an operand, where it is converted at the use), but as the
    storage type of a LOCAL it is 32 bits: `var a = 0` followed by `a += 2000000000`
    three times printed 1705032704 where Mojo's 64-bit `Int` and CPython both give
    6000000000, while `var b: Int = 0` was correct. The type lattice already
    widens `int` to `int64_t` when any other assignment to the local is 64-bit, so
    only a local whose every assignment is a small literal or 32-bit arithmetic
    stayed `int`; those accumulators are exactly the ones that overflow.
    Bool literals and everything else keep `_quick_type`'s answer."""
    if isinstance(value, gimple_ctypes.IntLiteral):
        return 'int64_t'
    return gen._quick_type(value)


def _infer_local_var_types(gen, func: gimple_ctypes.FunctionDef) -> dict[str, str]:
    """Infer local variable types from all assignments in function body.

    Scans all assignments to determine the variable's actual type needs.
    Returns dict mapping var_name → inferred_ctype.
    """
    # Annotated as a real dict: `inferred` is captured by the nested
    # `collect_assigned_types` closure (passed through its lifted env
    # struct), and an unannotated `{}` left that env field / the closure's
    # writes typed int64_t on the self-hosted path, corrupting the dict so
    # the later `for vname in inferred:` SIGSEGV'd in
    # `mojo_dict_iter_key` (`it->dict->slots[it->order[...]]`) while
    # compiling `./mojoc fire.py --dump-full`.
    inferred: dict[str, list] = {}

    # This pre-pass runs before self.var_types is populated for this
    # function, so _quick_type(IdentExpr(param_name)) falls through to its
    # int64_t default for every parameter reference — e.g. `prefix, rest =
    # raw[:prefix_len], raw[prefix_len:]` (Parser._strip_string_prefix_and_
    # quotes) inferred `rest` as int64_t instead of `char *` even though
    # `raw: str` is explicitly annotated, because `_quick_type(SliceExpr)`
    # resolves through `_quick_type(node.obj)` = `_quick_type(IdentExpr
    # ('raw'))`, which found no var_types entry. `rest` then got compiled
    # as a plain int64_t, so `rest[1:-1]` fell into _lower_slice's
    # generic "raw pointer, no bounds check" fallback instead of calling
    # mojo_cstr_slice — silently keeping every extra byte past the
    # (ignored) stop bound. Seed the annotated parameter types into
    # var_types just for this scan (saved/restored below) so identifier
    # lookups inside it resolve correctly.
    _saved_var_types = gen.var_types
    gen.var_types = dict(_saved_var_types)
    for pname, ptype in (func.params or []):
        if pname not in gen.var_types and ptype:
            gen.var_types[pname] = gimple_ctypes._mojo_type(ptype)

    def collect_assigned_types(nodes: list):
        """Recursively scan statements and collect types assigned to variables."""
        for node in nodes:
            if isinstance(node, gimple_ctypes.AssignStmt):
                # A FRESH local (`_as_node`), not a reassignment of `node`
                # itself: `node` is the shared `for node in nodes:` loop
                # variable, whole-function-unified to whatever ambient type
                # its OTHER uses across every branch settle on (opaque
                # int64_t, since `nodes` is a heterogeneous statement list)
                # — rebinding the SAME name here does not give it a fresh,
                # independent static type. A brand-new name bound only to
                # `_as_assignstmt_node(node)`'s annotated return type gets
                # its own real `AssignStmt *` typing.
                _as_node = _as_assignstmt_node(node)
                # Use _quick_type instead of lower_expr to avoid incomplete var_types
                if isinstance(_as_node.target, gimple_ctypes.TupleExpr):
                    targets = _as_node.target.elements
                    # Type each unpack target by its own value, never by the
                    # whole RHS: _quick_type(a_tuple) is 'MojoList *', which would
                    # wrongly poison scalar unpack targets (e.g. start, stop, step
                    # = ivals[0], ivals[1], ivals[2]).
                    if (isinstance(_as_node.value, gimple_ctypes.TupleExpr)
                            and len(_as_node.value.elements) == len(targets)):
                        elem_types = [_local_value_type(gen, e) for e in _as_node.value.elements]
                    else:
                        # Unpacking a single iterable: per-element type is
                        # unknown here; use the int64_t storage default.
                        # EXCEPT `text, is_fstring = ..._decode_str_literal_
                        # text(...)`, which returns `(char*, char*)` — the
                        # `is_fstring` slot is genuinely a "" / "1" STRING
                        # (see that helper's own docstring). Pre-typing it
                        # int64_t here re-boxed the per-slot get_str result
                        # into an int64_t local, so `if not is_fstring:`
                        # tested pointer-non-null and an empty-string ""
                        # pointer (non-null) read as truthy → every plain
                        # literal took the f-string path and lost its text.
                        _cv = _as_node.value
                        _is_decode = (
                            isinstance(_cv, gimple_ctypes.CallExpr)
                            and isinstance(_cv.func, gimple_ctypes.MemberExpr)
                            and _cv.func.member == '_decode_str_literal_text')
                        elem_types = [('char *' if _is_decode else 'int64_t')] * len(targets)
                else:
                    targets = [_as_node.target]
                    elem_types = [_local_value_type(gen, _as_node.value)]
                # Index both lists in parallel — `for target, vtype in
                # zip(targets, elem_types)` unpacks a zip 2-tuple, the
                # established boxing bug.
                for _zi in range(min(len(targets), len(elem_types))):
                    target = targets[_zi]
                    vtype = _as_str(elem_types[_zi])
                    if isinstance(target, gimple_ctypes.IdentExpr):
                        vname = _as_str(target.name)
                        if vname not in inferred:
                            inferred[vname] = []
                        inferred[vname].append(vtype)
            elif (isinstance(node, gimple_ctypes.VarDecl) and isinstance(node.name, str)
                    and ',' not in node.name):
                # Fresh local, not a `node` reassignment — see the
                # AssignStmt branch's identical comment above.
                _vd_node = _as_vardecl_node(node)
                # `var out = self._buf[a:]` — a VarDecl, not an AssignStmt.
                # Historically this pass "never scans VarDecl" (see
                # _closure_value_locals' docstring), so a `var`-declared
                # local's type fell to the int64_t default, breaking
                # `return out` return-type inference and the local's own
                # declared C type when the initializer is a pointer value
                # (bytes accumulator, sliced field, ...).
                vname = _as_str(_vd_node.name)
                # Empty-string sentinel, NOT `None`: an explicit `_vt: str |
                # None = None` annotation here was NOT enough — this local
                # lives inside a doubly-nested closure (collect_assigned_
                # types nested inside _infer_local_var_types), and that
                # scope's own C-type inference does not honor a local
                # variable's annotation the way parameter annotations are
                # honored elsewhere in this file; it still settled on plain
                # `int` (from the `= None` assignments), and every real
                # `_mojo_type(...)`/`_quick_type(...)` char* result then got
                # TRUNCATED to 32 bits storing into that narrower slot —
                # corrupting the pointer. The later `_vt == 'int64_t'`
                # string compare then read the truncated address and
                # SIGSEGV'd in strcmp, on virtually any VarDecl with a type
                # annotation (i.e. almost any compiled program). Using ''
                # instead of `None` for "unset" keeps every assignment to
                # `_vt` a genuine `char *` literal/result, so there is no
                # int-vs-pointer ambiguity left for the inferencer to get
                # wrong.
                _vt = ''
                if getattr(_vd_node, 'type_ann', None):
                    try:
                        _vt = gimple_ctypes._mojo_type(_vd_node.type_ann)
                    except Exception:
                        _vt = ''
                if (not _vt or _vt == 'int64_t') and _vd_node.value is not None:
                    _vt = _local_value_type(gen, _vd_node.value)
                if _vt:
                    inferred.setdefault(vname, []).append(_vt)
            elif isinstance(node, gimple_ctypes.MultiAssignStmt):
                # Fresh local, not a `node` reassignment — see the
                # AssignStmt branch's identical comment above.
                _ma_node = _as_multiassignstmt_node(node)
                # `a = b = ... = expr` (chained assignment): every target
                # receives the SAME value/type (real Python chained-
                # assignment semantics), unlike AssignStmt's TupleExpr
                # unpack case above. Was entirely unhandled here — every
                # target of a chained assignment fell through to this
                # scan's int64_t default regardless of the RHS's real
                # type. See bugs/hard/CODEGEN_multi_assign_local_var_
                # type_not_inferred.md.
                vtype = _local_value_type(gen, _ma_node.value)
                for target in _ma_node.targets:
                    if isinstance(target, gimple_ctypes.IdentExpr):
                        vname = _as_str(target.name)
                        if vname not in inferred:
                            inferred[vname] = []
                        inferred[vname].append(vtype)
            elif isinstance(node, gimple_ctypes.IfStmt):
                collect_assigned_types(node.then_body)
                if node.else_body:
                    collect_assigned_types(node.else_body)
                for _elif in node.elifs:  # index, not unpack — tuple-boxing bug
                    collect_assigned_types(_elif[1])
            elif isinstance(node, (gimple_ctypes.WhileStmt, gimple_ctypes.ForStmt)):
                collect_assigned_types(node.body)
                if node.else_body:
                    collect_assigned_types(node.else_body)
            elif isinstance(node, gimple_ctypes.TryStmt):
                collect_assigned_types(node.body)
                for h in node.handlers:
                    collect_assigned_types(h.body)
                if node.else_body:
                    collect_assigned_types(node.else_body)
                if node.finally_body:
                    collect_assigned_types(node.finally_body)
            elif isinstance(node, gimple_ctypes.WithStmt):
                collect_assigned_types(node.body)
            elif isinstance(node, gimple_ctypes.ExprStmt) and isinstance(node.value, gimple_ctypes.WalrusExpr):
                # `name := expr` used as a bare statement (e.g. `r :=
                # ShapedRecipe()`) parses as an ExprStmt wrapping a
                # WalrusExpr, NOT an AssignStmt -- unlike a walrus used
                # inside a larger expression, this shape was invisible
                # to this scan entirely, so a local first bound only via
                # a statement-level `:=` (never a plain `=`) never got an
                # inferred type here. See box.3d/game/bugs/DYLIB_struct_
                # list_index_reads_first_field_only_wrong_craft_results.md.
                vname = _as_str(node.value.name)
                if vname not in inferred:
                    inferred[vname] = []
                inferred[vname].append(gen._quick_type(node.value.value))

    try:
        collect_assigned_types(func.body)
    finally:
        gen.var_types = _saved_var_types

    # Join all types for each variable using TypeLattice
    result: dict[str, str] = {}
    for vname in inferred:
        types = inferred[vname]
        if types:
            result[_as_str(vname)] = gimple_ctypes.TypeLattice.join_all(types)

    return result

def _calls_in_stmts(gen, stmts, out):
    """Collect every CallExpr reachable from a statement list.

    Phase 4 (bugs/hard/PERF_nested_module_compile_walk_ast_quadratic_
    rescan.md): the traversal is a pure function of each top-level
    statement's subtree (`_collect_calls` reads no mutable gen state —
    its only gen call, `_fstring_sub_exprs`, re-parses the literal's own
    text from scratch), and every consumer of the collected list only
    READS the yielded CallExpr nodes (isinstance/`.func.name`/`.args`
    inspection; none mutates them or compares identity). So each top-
    level statement's contribution is memoized by id(stmt) in the
    tree-wide shared `gen._calls_in_stmts_cache`, exactly like Phase 2's
    field-scan caches: a statement already walked by any earlier level /
    fixpoint round contributes its cached calls verbatim instead of
    being re-walked O(levels × rounds) times as `imported_stmts` and the
    Pass 1.3d/2c caller-body lists grow."""
    cache = gen._calls_in_stmts_cache
    for n in stmts:
        cached = cache.get(id(n))
        if cached is None:
            sub = []
            _collect_calls_in_stmt(gen, n, sub)
            cached = tuple(sub)
            cache[id(n)] = cached
        out.extend(cached)

def _parse_fstring_parts(gen, inner: str) -> list[tuple[str, str, str, str]]:
    """Parse f-string body into `(kind, text, spec, conv)` 4-tuples, kind
    being 'lit' or 'expr'.

    The `-> list[tuple[str, str, str, str]]` return annotation is
    load-bearing for the self-hosted compiler: without it every slot but
    the first was typed int64_t, so the consumer (`_lower_StringLiteral`'s
    f-string branch) read each part's TEXT as a boxed pointer, ran
    `_c_escape` on the integer bits, and interned an empty string — every
    compiled-codegen f-string collapsed to `""`."""
    parts: list = []
    i = 0
    buf = []
    while i < len(inner):
        c = inner[i]
        if c == '{':
            if i + 1 < len(inner) and inner[i+1] == '{':
                buf.append('{'); i += 2; continue
            if buf:
                parts.append(('lit', ''.join(buf), '', '')); buf = []
            i += 1
            depth = 1
            expr_chars = []
            while i < len(inner) and depth > 0:
                ch = inner[i]
                if ch == '{': depth += 1
                elif ch == '}': depth -= 1
                if depth > 0:
                    expr_chars.append(ch)
                i += 1
            expr_src = ''.join(expr_chars)
            # Split the expression from its optional format spec /
            # conversion (`{x:04d}` -> expr "x", spec "04d").
            _spec = ''
            _conv = ''
            _depth = 0
            for _k, _ch in enumerate(expr_src):
                if _ch in '([{':
                    _depth += 1
                elif _ch in ')]}':
                    _depth -= 1
                elif _ch == ':' and _depth == 0:
                    _spec = expr_src[_k + 1:]
                    expr_src = expr_src[:_k]
                    break
                elif _ch == '!' and _depth == 0:
                    _conv = expr_src[_k + 1:]
                    expr_src = expr_src[:_k]
                    break
            parts.append(('expr', expr_src.strip(), _spec, _conv))
        elif c == '}' and i + 1 < len(inner) and inner[i+1] == '}':
            buf.append('}'); i += 2
        else:
            buf.append(c); i += 1
    if buf:
        parts.append(('lit', ''.join(buf), '', ''))
    return parts

def _decode_str_literal_text(gen, val: str) -> tuple[str, str]:
    """Strip a raw StringLiteral.value's f/r/b/u/t prefix and outer quotes,
    returning (text, is_fstring). Shared by plain-string lowering, f-string
    interpolation, and `%`-style string-formatting (which needs the format
    string's literal text at codegen time, before any quoting/escaping)."""
    # Detect and strip f/r/b/u/t prefix — only if followed by a quote character
    # Regular strings have their quotes already stripped by the parser; f-strings
    # and t-strings (template strings — same `{expr}` interpolation syntax,
    # treated identically here) keep prefix+quotes.
    is_fstring = False
    # Index-based prefix walk (was `while val: ... val = val[1:]`). Once
    # self-hosted, a `while` loop that reslices `val = val[1:]` every
    # iteration to shrink it never terminated for an f/r/b-prefixed string
    # (`f"..."`) — the compiled reslice-in-condition-loop didn't make
    # progress, `val[0]` stayed `'f'`, and `_parse_fstring_parts` then spun
    # on a mangled `inner` allocating forever. A single positive slice at
    # the end has no such issue.
    _pfx_end = 0
    while _pfx_end < len(val) and val[_pfx_end] in 'fFrRbBuUtT':
        _pfx_end += 1
    prefix = val[:_pfx_end]
    val = val[_pfx_end:]
    # fire_compiler.py's Parser already strips the outer quotes from a plain
    # (non-f/t-string) StringLiteral's value at tokenize time. So if what's
    # left after the prefix walk does NOT start with a quote, it is a plain
    # string whose content is final — return it verbatim (plus any
    # prefix-like leading chars that turned out to be content, not a
    # prefix). Do NOT re-run the quote strip below: a plain string whose
    # CONTENT happens to start and end with a quote — this file's own
    # `'"'` / `"'"` / `'"""'` / `"'''"` literals, and every user string
    # like `"a "` — would otherwise be mangled ( `'"""'` → `''`, so once
    # self-hosted `"anything".startswith(<that literal>)` matched and every
    # user StringLiteral's text was stripped to "" in the emitted pool ).
    if not val or val[0] not in ('"', "'"):
        return prefix + val, ''
    # A value that is ENTIRELY quote characters (this file's own `'"'` /
    # `"'"` / `'"""'` / `"'''"` literals — content, not delimiters) has no
    # inner text to strip. Return it verbatim. Critical once self-hosted:
    # otherwise `'"""'` -> `'"'` (a single `"`), and since this function's
    # own `val.startswith('"""')` argument then IS just `"`,
    # `"anything".startswith('"')` matched and every user `"..."` /
    # `f"..."` literal got its "triple quotes" stripped
    # (`'"vv={x}"'[3:len-3]` == `'={'`), mangling every f-string body ->
    # `_parse_fstring_parts` spun forever.
    _all_quote = True
    for _c in val:
        if _c != '"' and _c != "'":
            _all_quote = False
            break
    if _all_quote:
        return prefix + val, ('1' if any(c in 'fFtT' for c in prefix) else '')
    # val still carries quotes: an f/t-string (prefix has f/F/t/T) or a
    # triple-quoted value handed back from the placeholder cache.
    is_fstring = any(c in 'fFtT' for c in prefix)
    # `len(val) >= 6` / `>= 2`: a value that IS just quote characters (`"""`,
    # `"`, this file's own such literals) starts and ends with the quote but
    # carries no delimited content — a real `"""x"""` is >= 7 chars (>= 6
    # empty), a real `"x"` is >= 3 (>= 2 empty).
    # `val[1:len(val)-1]` not `val[1:-1]`: a negative slice stop, once
    # self-hosted, resolved wrong on the compiled path (`'"AB={x}"'[1:-1]`
    # came back as a single middle char), which mangled every f-string
    # body.
    _vl = len(val)
    if _vl >= 6 and val.startswith('"""') and val.endswith('"""'):
        val = val[3:_vl - 3]
    elif _vl >= 6 and val.startswith("'''") and val.endswith("'''"):
        val = val[3:_vl - 3]
    elif _vl >= 2 and ((val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'"))):
        val = val[1:_vl - 1]
    # Return the is_fstring flag as an EMPTY/non-empty STRING ("", "1")
    # rather than a bool, so the (text, is_fstring) tuple is homogeneous
    # [char*, char*] — the caller unpacks both slots via get_str (the
    # tuple elem type), and a heterogeneous (str, bool) tuple would make
    # Pass 2c infer elem 'int64_t' (it can't type the local `val` as
    # char* with var_types empty), so the caller read val's pointer as an
    # int and the string pool stored its address. All consumers treat
    # is_fstring as truthiness, which "" vs "1" preserves exactly.
    return val, ('1' if is_fstring else '')

def _str_literal_to_slit(gen, str_literal: str) -> str:
    """Convert a raw C string literal to a _slit_ name from the string pool.
    
    Args:
        str_literal: A raw C string literal like '"hello world"' or "'test'"
        
    Returns:
        The corresponding _slit_ name like '_slit_10000'
    """
    # Strip the outer quotes
    if (str_literal.startswith('"') and str_literal.endswith('"')) or \
       (str_literal.startswith("'") and str_literal.endswith("'")):
        val = str_literal[1:-1]
    else:
        val = str_literal
    
    # Escape the string content
    escaped = gimple_ctypes._c_escape(val)

    return gen._intern_string(escaped)

def _subst_idents(gen, expr, mapping: dict):
    """Return a copy of an AST expression with any IdentExpr whose name is in
    `mapping` replaced by the mapped node. Used to rebind `Self`/struct-name
    to a concrete object expression when expanding a struct comptime alias."""
    if isinstance(expr, gimple_ctypes.IdentExpr) and expr.name in mapping:
        return mapping[expr.name]
    if gimple_ctypes.dataclasses.is_dataclass(expr) and not isinstance(expr, type):
        changes = {}
        for f in gimple_ctypes.dataclasses.fields(expr):
            v = getattr(expr, f.name)
            nv = gen._subst_in_value(v, mapping)
            if nv is not v:
                changes[f.name] = nv
        return gimple_ctypes.dataclasses.replace(expr, **changes) if changes else expr
    return expr

def _type_expr_to_ann(gen, node) -> str:
    """Reconstruct a type-annotation string from a type expression node, so
    parametric types in external_call/MLIR positions resolve via _mojo_type.
    e.g. UnsafePointer[Int8] -> 'UnsafePointer[Int8]', c_ssize_t -> 'c_ssize_t'.

    Also doubles as the textual rendering of a COMPTIME VALUE bracket
    argument (`f[1]`, `f[True]`, `f[-1]`) for a comptime-bracket-
    parametrized call (`f[N: Int](...)`, not a type-parametrized generic)
    — see bugs/CODEGEN_comptime_bracket_parametrized_function_calls_
    silently_wrong.md. monomorphize.py's substitution is purely textual
    (`re.sub(r'\\bTP\\b', str(concrete), src)`), so a literal's Python
    repr substitutes into the callee body exactly like a type name does;
    no separate value-vs-type code path is needed downstream, only this
    node-to-string step, which previously returned '' for every literal
    (IntLiteral/BoolLiteral/negative-int UnaryOp), making
    _is_concrete_type_arg reject it and silently falling back to the
    placeholder-0 codegen instead of ever binding/invoking the callee."""
    if isinstance(node, gimple_ctypes.IdentExpr):
        return node.name
    if isinstance(node, gimple_ctypes.SubscriptExpr):
        base = gen._type_expr_to_ann(node.obj)
        idx = node.index
        parts = idx.elements if isinstance(idx, gimple_ctypes.TupleExpr) else [idx]
        inner = ', '.join(gen._type_expr_to_ann(p) for p in parts)
        return f"{base}[{inner}]"
    if isinstance(node, gimple_ctypes.MemberExpr):
        return f"{gen._type_expr_to_ann(node.obj)}.{node.member}"
    if isinstance(node, gimple_ctypes.IntLiteral):
        return str(node.value)
    if isinstance(node, gimple_ctypes.BoolLiteral):
        return 'True' if node.value else 'False'
    if isinstance(node, gimple_ctypes.UnaryOp) and node.op == '-' and isinstance(node.operand, gimple_ctypes.IntLiteral):
        return str(-node.operand.value)
    return ''

def _refine_generic_return_type(gen, info: dict, module_src: str, g: str,
                                 mangled_type_args: list, arg_count: int) -> None:
    """elaborate.py's _signature() resolves a generic's return type via the
    bare, stateless _mojo_type(), which has no notion of a struct newly
    monomorphized by _ensure_generic_struct just above (e.g. "MoveOnly_Int")
    — it only matches _TYPE_MAP's builtin names, so it silently falls back
    to int64_t/int64_t* whenever a type argument is such a struct. Recompute
    the return type here using this instance's own struct-aware
    _resolve_type (which DOES know about struct_field_types) over the
    template's own return annotation, substituted with the mangled type
    args — and only override info['ret'] when that yields something more
    specific than the generic int64_t default, so ordinary (non-struct)
    generics are unaffected."""
    import elaborate
    tmpl = elaborate.extract_fn_source(module_src, g, arg_count=arg_count)
    if not tmpl:
        return
    params = elaborate.type_param_names(tmpl)
    if not params:
        return
    for s in gimple_ctypes.Parser(gimple_ctypes.py_tokenize(tmpl)).parse_module():
        if isinstance(s, gimple_ctypes.FunctionDef) and s.name == g and s.return_type:
            ret_ann = s.return_type
            for tp, concrete in zip(params, mangled_type_args):
                ret_ann = gimple_ctypes.re.sub(rf'\b{gimple_ctypes.re.escape(tp)}\b', concrete, ret_ann)
            better_ret = gen._resolve_type(ret_ann)
            if better_ret != 'int64_t':
                info['ret'] = better_ret
            break

def _is_none_literal(el) -> bool:
    """`None` is parsed as a bare `IdentExpr(name='None')`, not a
    dedicated literal node (see `_lower_IdentExpr`'s/`_quick_type`'s own
    `name == 'None'` checks — this file has no case that ever
    constructs `NoneLiteral`, despite fire_compiler.py defining the
    class). Centralized here so every None-in-a-literal check in this
    file recognizes the same shape."""
    return isinstance(el, gimple_ctypes.IdentExpr) and el.name == 'None'

def _is_sys_stderr(expr) -> bool:
    """Structural check for `sys.stderr` — deliberately not lowered as a
    runtime value at all (see mojo_print_stderr's doc comment: a bare
    FILE* isn't safely passable through -fgimple's restricted subset)."""
    return (isinstance(expr, gimple_ctypes.MemberExpr) and isinstance(expr.obj, gimple_ctypes.IdentExpr)
            and expr.obj.name == 'sys' and expr.member == 'stderr')

def _module_const_int(gen, name: str, stmts: list, imported_stmts: list | None) -> int | None:
    """Resolve a bare NAME to a compile-time int, by looking for a
    module-level `comptime NAME: T = <expr>` (or plain `NAME = <expr>`)
    binding in `stmts`/`imported_stmts` whose value folds to an int via
    `_eval_const_int`. Used by the fixed-size-array struct-field
    annotation (`[ElemType; N]`) to resolve a named size like box.3d/
    game's `comptime MAX_BLOCKS: Int = 4096`, since that array shape's
    size is very commonly a named constant rather than a bare literal.
    Cached (per-name) since struct field registration can look up the
    same name repeatedly across many fields/structs in one compile."""
    cache = getattr(gen, '_module_int_consts_cache', None)
    if cache is None:
        cache = gen._module_int_consts_cache = {}
    if name in cache:
        return cache[name]
    val = None
    for src in (stmts, imported_stmts or []):
        for st in src:
            if isinstance(st, gimple_ctypes.ComptimeVarStmt) and st.target == name:
                val = gen._eval_const_int(st.value)
            elif isinstance(st, gimple_ctypes.VarDecl) and st.name == name and st.value is not None:
                val = gen._eval_const_int(st.value)
            elif (isinstance(st, gimple_ctypes.AssignStmt) and isinstance(st.target, gimple_ctypes.IdentExpr)
                  and st.target.name == name):
                val = gen._eval_const_int(st.value)
            if val is not None:
                break
        if val is not None:
            break
    cache[name] = val
    return val

def _eval_const(gen, node):
    """Evaluate an expression as any compile-time constant (int, bool,
    str, or a `comptime NAME: T = value` alias previously recorded by
    _gen_stmt_ComptimeVarStmt into self._comptime_vals) — or None if it
    isn't foldable. A superset of _eval_const_int/_eval_const_bool used
    where the comptime value's own type (not just int/bool) matters,
    e.g. a comptime `if` testing a comptime string alias.

    The folding RULES live in mojo/middle/comptime.py, shared with
    the formal arm64 backend so both compiled backends resolve `comptime`
    the same way; this wrapper supplies the gimple path's binding table and
    its `sys.platform`."""
    # `sys.platform` — a genuinely compile-time-constant value for THIS host
    # is folded by comptime_eval.eval_const, which takes the platform as a
    # parameter so this path keeps resolving it exactly as it did before
    # (gimple_ctypes.sys.platform). The reason it matters at all: gen_module's
    # "conditional toplevel def" promotion needs a statically resolvable guard,
    # and without this `_MS_WINDOWS = (sys.platform == 'win32')` folds to None
    # (unresolvable) on every host, so the promotion's "first-branch-wins"
    # fallback silently picks the WINDOWS-only branch's body even when
    # compiling on macOS/Linux — found via Lib/importlib
    # /_bootstrap_external.py's `if _MS_WINDOWS: def _path_join(...): ...
    # else: def _path_join(...): ...`.
    return comptime_eval.eval_const(node, gen._comptime_vals)


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_resolve.py)
# ---------------------------------------------------------------------------

# --- dependency _record_closure_alias (from gimple_gen_resolve.py) ---
def _record_closure_alias(gen, result: dict, tgt: str, val):
    """Record `tgt`'s C type when `val` is a bare reference to a nested
    (closure) function. Kept as a top-level helper so `val` usage-infers to
    a pointer instead of the `int` a `None`-initialized local would get."""
    if tgt in result or not isinstance(val, gimple_ctypes.IdentExpr):
        return
    _ci = gen._closure_info_for_ident(val.name)
    if _ci is not None:
        result[tgt] = 'MojoBoundMethod *' if _ci.env_struct else 'void *'

# --- dependency KNOWN_LEAF_RETS (from gimple_gen_resolve.py) ---
KNOWN_LEAF_RETS = {'_mojo_type': 'char *'}

# --- dependency _collect_calls_in_stmt (from gimple_gen_resolve.py) ---
def _collect_calls_in_stmt(gen, n, out):
    """Walk ONE statement, appending every reachable CallExpr to out.

    A FAITHFUL translation of the old `for attr in ('value','condition',
    'iterable'): ... / for attr in ('body','then_body','else_body',
    'finally_body'): if isinstance(sub, list): ...` loop into explicit
    per-node-type branches — same node coverage, same recursion, NOTHING
    added (in particular NOT `WithStmt.items`). The old form used
    `getattr(n, <runtime-attr-name>)` + `isinstance(sub, list)`, and on
    the self-hosted path a dynamic getattr yields int64_t while
    `isinstance(<int64_t>, list)` is the always-false runtime stub — so it
    never recursed into ANY control flow and the cross-call scalar
    contract missed every call site nested inside an `if`/`try`."""
    # ── the `value`/`condition`/`iterable` expression sweep ──
    if isinstance(n, (ExprStmt, ReturnStmt, AssignStmt,
                      AugAssignStmt, MultiAssignStmt, RaiseStmt, AssertStmt,
                      VarDecl, ComptimeVarStmt)):
        _v = getattr(n, 'value', None)
        if _v is not None:
            gen._collect_calls(_v, out)
    if isinstance(n, (IfStmt, WhileStmt)):
        gen._collect_calls(n.condition, out)
    elif isinstance(n, ForStmt):
        gen._collect_calls(n.iterable, out)
    # ── the body-list recursion sweep ──
    if isinstance(n, IfStmt):
        gen._calls_in_stmts(n.then_body, out)
        if isinstance(n.else_body, list):
            gen._calls_in_stmts(n.else_body, out)
        for _cond, _eb in (n.elifs or []):
            gen._calls_in_stmts(_eb, out)
    elif isinstance(n, TryStmt):
        gen._calls_in_stmts(n.body, out)
        for _h in (n.handlers or []):
            _hb = getattr(_h, 'body', None)
            if isinstance(_hb, list):
                gen._calls_in_stmts(_hb, out)
        if isinstance(n.else_body, list):
            gen._calls_in_stmts(n.else_body, out)
        if isinstance(n.finally_body, list):
            gen._calls_in_stmts(n.finally_body, out)
    elif isinstance(n, (WhileStmt, ForStmt, WithStmt, FunctionDef)):
        _b = getattr(n, 'body', None)
        if isinstance(_b, list):
            gen._calls_in_stmts(_b, out)
        _eb2 = getattr(n, 'else_body', None)
        if isinstance(_eb2, list):
            gen._calls_in_stmts(_eb2, out)


# ---------------------------------------------------------------------------
# Dependencies extracted with the shared API (originally gimple_gen_resolve.py)
# ---------------------------------------------------------------------------

# --- dependency KNOWN_LEAF_RETS (from gimple_gen_resolve.py) ---
KNOWN_LEAF_RETS = {'_mojo_type': 'char *'}

