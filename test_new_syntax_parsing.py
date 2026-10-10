"""Parser-only unit tests for the syntax the new-modular stdlib uses that this
parser did not have before 2026-09-30.

Every case here is one of the nine features that `compile_stdlib.py` went from
356/610 to 610/610 on, and each is written to FAIL if its feature is removed —
asserting a node's existence, its field values, and (where the distinction is
the whole point) a POSITIVE and a NEGATIVE case for the same syntax, so a
parser that simply accepted more without modelling it does not pass.

Parser-only: `Parser(py_tokenize(src)).parse_module()` is constructed directly
and the resulting AST inspected. No interpreter, no codegen, no execution.
"""
import sys

import fire_compiler as N

_PASS = 0
_FAIL = 0


def _parse(src: str):
    return N.Parser(N.py_tokenize(src)).parse_module()


def check(name: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


def check_raises(name: str, src: str, exc_type=SyntaxError):
    """The negative half of a pair: this must STILL be rejected."""
    global _PASS, _FAIL
    try:
        _parse(src)
    except exc_type:
        print(f"PASS  {name}")
        _PASS += 1
        return
    except Exception as e:
        print(f"FAIL  {name}  wrong exception: {type(e).__name__}: {e}")
        _FAIL += 1
        return
    print(f"FAIL  {name}  expected {exc_type.__name__}, parse succeeded")
    _FAIL += 1


def _fns(stmts):
    return [s for s in stmts if isinstance(s, N.FunctionDef)]


def _named(stmts, name):
    for s in stmts:
        if isinstance(s, N.FunctionDef) and s.name == name:
            return s
    return None


def _walk(node, seen=None):
    """Every AST node under `node`, descending into dataclass fields and
    lists. Written here rather than reused from mojo/middle/types.py because
    `_used_idents_node` deliberately stops at FunctionDef boundaries, which is
    the wrong rule for 'did the parser produce a DottedLiteral anywhere'."""
    if seen is None:
        seen = []
    if isinstance(node, (list, tuple)):
        for item in node:
            _walk(item, seen)
        return seen
    if not hasattr(node, '__dataclass_fields__'):
        return seen
    seen.append(node)
    import dataclasses
    for f in dataclasses.fields(node):
        _walk(getattr(node, f.name), seen)
    return seen


# ── 1. Dotted literals ────────────────────────────────────────────────────
def test_dotted_literal():
    src = '@inline(.always)\ndef f():\n    pass\n'
    deco = _parse(src)[0].decorators[0]
    check("dotted_deco_is_a_call", isinstance(deco, N.CallExpr), repr(deco))
    lits = [n for n in _walk(deco) if isinstance(n, N.DottedLiteral)]
    check("dotted_deco_has_one_literal", len(lits) == 1, repr(lits))
    check("dotted_path_has_no_leading_dot",
          lits and lits[0].path == 'always', repr(lits[0].path if lits else None))

    # Expression position: subscript type argument, with postfix chained on.
    src2 = 'def f():\n    var a = SIMD[.uint64, 4](0)\n'
    stmts = _parse(src2)
    lits = [n for n in _walk(stmts) if isinstance(n, N.DottedLiteral)]
    check("dotted_subscript_typearg", len(lits) == 1, repr(lits))
    check("dotted_subscript_path",
          lits and lits[0].path == 'uint64', repr(lits[0].path if lits else None))
    # The postfix must survive: `.of_bytes[128]()` is a CALL on the literal.
    src3 = 'def f():\n    var l = Layout[Int, alignment=.of_bytes[128]()]\n'
    lits = [n for n in _walk(_parse(src3)) if isinstance(n, N.DottedLiteral)]
    calls = [n for n in _walk(_parse(src3)) if isinstance(n, N.CallExpr)]
    check("dotted_with_subscript_and_call", len(lits) == 1 and len(calls) >= 1,
          f"lits={lits} calls={calls}")

    # Dotted chain: `.a.b` keeps both components in one path.
    src4 = 'def f():\n    var x = SIMD[.a.b, 1](0)\n'
    lits = [n for n in _walk(_parse(src4)) if isinstance(n, N.DottedLiteral)]
    check("dotted_chain_in_one_path",
          len(lits) == 1 and lits[0].path == 'a.b',
          repr(lits[0].path if lits else None))

    # NEGATIVE half. A leading DOT is only a dotted literal where an
    # EXPRESSION is expected; these must keep their old meaning, or the rule
    # has merely grown to swallow everything.
    ell = [n for n in _walk(_parse('def f():\n    var x = ...\n'))
           if isinstance(n, N.EllipsisLiteral)]
    check("ellipsis_not_a_dotted_literal", len(ell) == 1 and not [
        n for n in _walk(_parse('def f():\n    var x = ...\n'))
        if isinstance(n, N.DottedLiteral)], repr(ell))
    fl = [n for n in _walk(_parse('def f():\n    var x = .5\n'))
          if isinstance(n, N.FloatLiteral)]
    check("float_literal_not_a_dotted_literal", len(fl) == 1, repr(fl))
    mem = [n for n in _walk(_parse('def f():\n    var x = a.b\n'))
           if isinstance(n, N.MemberExpr)]
    check("attribute_access_not_a_dotted_literal", len(mem) == 1, repr(mem))
    check_raises("bare_dot_still_rejected", 'def f():\n    var x = .\n')


# ── 2. __match, and its two case layouts ──────────────────────────────────
def test_match():
    # Mojo layout: cases at the SAME indent as the keyword.
    src = ('def f(x):\n'
           '    __match x:\n'
           '    case .PASS:\n'
           '        return 1\n'
           '    case _:\n'
           '        return 2\n')
    m = _parse(src)[0].body[0]
    check("flat_match_is_a_matchstmt", isinstance(m, N.MatchStmt), repr(m))
    check("flat_match_case_count", isinstance(m, N.MatchStmt) and len(m.cases) == 2,
          repr(len(m.cases) if isinstance(m, N.MatchStmt) else None))

    # A statement AFTER the match in the same block must not be eaten as a case.
    src2 = ('def f(x):\n'
            '    __match x:\n'
            '    case .A:\n'
            '        return 1\n'
            '    return 2\n')
    body = _parse(src2)[0].body
    check("statement_after_flat_match_survives",
          len(body) == 2 and isinstance(body[1], N.ReturnStmt),
          repr([type(b).__name__ for b in body]))

    # Python layout: cases indented past the keyword. Still accepted.
    src3 = ('def f(x):\n'
            '    match x:\n'
            '        case .A:\n'
            '            return 1\n')
    m3 = _parse(src3)[0].body[0]
    check("indented_match_still_works",
          isinstance(m3, N.MatchStmt) and len(m3.cases) == 1, repr(m3))

    # comptime __match
    src4 = ('fn g(dtype):\n'
            '    comptime __match dtype:\n'
            '    case .int:\n'
            '        return 1\n')
    check("comptime_match_parses", isinstance(_parse(src4)[0], N.FunctionDef))

    # An or-pattern of dotted literals is ONE BinaryOp, not two cases.
    src5 = ('def f(x):\n'
            '    __match x:\n'
            '    case .A | .B:\n'
            '        return 1\n')
    m5 = _parse(src5)[0].body[0]
    check("or_pattern_is_one_case",
          isinstance(m5, N.MatchStmt) and len(m5.cases) == 1, repr(m5))

    # A guard still parses after a dotted pattern.
    src6 = ('def f(x):\n'
            '    __match x:\n'
            '    case .A if x > 0:\n'
            '        return 1\n')
    m6 = _parse(src6)[0].body[0]
    check("guard_after_dotted_pattern",
          isinstance(m6, N.MatchStmt) and m6.cases[0].guard is not None, repr(m6))


# ── 3. Typed lambdas ─────────────────────────────────────────────────────
def test_lambda():
    src = 'g = lambda (i: Int) -> Int: i * i\n'
    lam = _parse(src)[0].value
    check("lambda_is_lambdaexpr", isinstance(lam, N.LambdaExpr), repr(lam))
    check("lambda_param_name", lam.params == [('i', None)], repr(lam.params))
    check("lambda_param_type", lam.param_types == ['Int'], repr(lam.param_types))
    check("lambda_return_type", lam.return_type == 'Int', repr(lam.return_type))

    # `params` must stay 2-tuples: consumers unpack it positionally.
    check("lambda_params_are_2tuples",
          all(isinstance(p, tuple) and len(p) == 2 for p in lam.params),
          repr(lam.params))

    # Empty parameter list, typed return. The annotation is stored with its
    # internal whitespace normalised ('Array[T, size]' -> 'Array[T,size]'), which
    # is what every other annotation in the tree does; assert the normalised
    # form so a change in THAT normalisation is caught here too.
    src2 = 'g = lambda () -> Array[T, size]: {fill = T()}\n'
    lam2 = _parse(src2)[0].value
    check("lambda_empty_params_typed_ret",
          lam2.params == [] and lam2.return_type == 'Array[T,size]',
          repr(lam2.return_type))

    # Capture list between params and `->`.
    src3 = 'g = lambda (k: Key) {imm key} -> Bool: (k == key)\n'
    lam3 = _parse(src3)[0].value
    check("lambda_capture_text", lam3.captures == 'imm key', repr(lam3.captures))
    check("lambda_capture_with_typed_ret",
          lam3.return_type == 'Bool' and lam3.param_types == ['Key'], repr(lam3))

    # Comptime block before the parameter list.
    src4 = 'g = lambda [i: Int]() -> Int: r.field_offset[index=i]()\n'
    lam4 = _parse(src4)[0].value
    check("lambda_comptime_block",
          lam4.comptime_params == [('i', 'Int')], repr(lam4.comptime_params))
    check("lambda_comptime_with_ret", lam4.return_type == 'Int', repr(lam4.return_type))

    # The four pre-existing Python shapes must be untouched.
    for name, s, want in [
            ("py_bare", 'g = lambda x, y: x + y\n', [('x', None), ('y', None)]),
            ("py_default", 'g = lambda e, self=self: e\n', [('e', None), ('self', N.IdentExpr(name='self', line=0, col=0))]),
            ("py_star", 'g = lambda *a, **k: a\n', [('*a', None), ('**k', None)]),
            ("py_empty", 'g = lambda: 1\n', []),
    ]:
        got = _parse(s)[0].value.params
        ok = len(got) == len(want) and all(
            g[0] == w[0] for g, w in zip(got, want))
        check(f"lambda_python_shape_{name}", ok, f"{got} vs {want}")


# ── 4. Explicit capture lists on a nested def ─────────────────────────────
def test_capture_lists():
    src = ('def outer():\n'
           '    var x = 0\n'
           '    var d = [1]\n'
           '    def h(a: Int) {mut x, var d^}:\n'
           '        x += a\n')
    h = _parse(src)[0].body[-1]
    check("capture_list_parsed", h.captures == [('x', 'mut'), ('d', 'owned')],
          repr(h.captures))
    check("capture_list_flag_set", h.has_capture_list is True, repr(h.has_capture_list))

    # `{}` and "no list at all" are DIFFERENT statements and must be told
    # apart by the flag, since both leave `captures == []`.
    empty = _parse('def o():\n    def h() {}:\n        pass\n')[0].body[0]
    absent = _parse('def o():\n    def h():\n        pass\n')[0].body[0]
    check("empty_capture_list_is_empty", empty.captures == [], repr(empty.captures))
    check("empty_capture_list_flag_true", empty.has_capture_list is True)
    check("absent_capture_list_flag_false", absent.has_capture_list is False)

    # `{mut}` with no name: a convention-only entry, recorded with a None NAME
    # so it cannot be confused with a capture of a variable called `mut`.
    bare = _parse('def o():\n    def h() {mut}:\n        pass\n')[0].body[0]
    check("bare_convention_entry_has_none_name",
          bare.captures == [(None, 'mut')], repr(bare.captures))

    # A trailing comma is allowed.
    trail = _parse('def o():\n    def h() {mut c,}:\n        c += 1\n')[0].body[0]
    check("capture_list_trailing_comma", trail.captures == [('c', 'mut')],
          repr(trail.captures))

    # `var`/`inout`/`borrowed` canonicalise; `imm` does not.
    check("capture_var_canon_to_owned",
          _parse('def o():\n    def h() {var v}:\n        pass\n')[0]
          .body[0].captures == [('v', 'owned')])
    check("capture_imm_passes_through",
          _parse('def o():\n    def h() {imm i}:\n        pass\n')[0]
          .body[0].captures == [('i', 'imm')])

    # A lambda's `{...}` is its capture TEXT, not a name list — a different
    # field on a different node, and the two must not be confused.
    lam = _parse('g = lambda () {ref} -> T: 1\n')[0].value
    check("lambda_captures_is_text_not_pairs",
          lam.captures == 'ref' and not isinstance(lam.captures, list),
          repr(lam.captures))


# ── 5. `imm` as a convention keyword ──────────────────────────────────────
def test_imm_convention():
    src = ('struct L:\n'
           '    def __eq__(imm self, imm other: Self) -> Bool:\n'
           '        return self.x == other.x\n')
    m = _parse(src)[0].methods[0]
    check("imm_not_a_parameter_name",
          [p[0] for p in m.params] == ['self', 'other'], repr(m.params))
    check("imm_recorded_as_convention",
          m.param_convs == {'self': 'imm', 'other': 'imm'}, repr(m.param_convs))

    # It is a real KEYWORD now, so it must not survive as an identifier.
    check("imm_is_a_keyword", 'imm' in N._KEYWORDS)

    # ...and it is an immutable borrow, in one shared vocabulary.
    for c in ('read', 'ref', 'imm'):
        check(f"conv_{c}_is_read_only", N.conv_is_read_only(c) is True)
    for c in ('mut', 'out'):
        check(f"conv_{c}_is_exclusive", N.conv_is_exclusive(c) is True)
    check("conv_owned_is_transfer", N.conv_is_transfer('owned') is True)
    # An ABSENT convention must not read as read-only: callers opt in.
    for c in (None, ''):
        check(f"conv_absent_not_read_only_{c!r}", N.conv_is_read_only(c) is False)

    # A convention keyword immediately before a separator is still a NAME.
    named = _parse('def f(imm):\n    pass\n')[0]
    check("imm_as_plain_param_name", named.params == [('imm', None)],
          repr(named.params))


# ── 6. `where` on a struct's base list ────────────────────────────────────
def test_struct_where():
    src = ('struct I[T](\n'
           '    Copyable where conforms_to(T, Copyable),\n'
           '    Iterable,\n'
           ') where conforms_to(T, Deinitable):\n'
           '    pass\n')
    st = _parse(src)[0]
    check("struct_where_parses", isinstance(st, N.StructDef), repr(st))
    check("struct_where_keeps_body", len(st.fields) == 0, repr(st.fields))
    # A plain base list still works.
    plain = _parse('struct S(A, B):\n    pass\n')[0]
    check("struct_plain_bases_unaffected", isinstance(plain, N.StructDef))


# ── 7. Multi-target comptime binding ─────────────────────────────────────
def test_multi_target_comptime():
    src = ('def f():\n'
           '    comptime a, b = g()\n')
    body = _parse(src)[0].body
    check("multi_target_comptime_yields_two_statements", len(body) == 2,
          repr([type(s).__name__ for s in body]))
    check("multi_target_comptime_targets",
          all(isinstance(s, N.ComptimeVarStmt) for s in body)
          and [s.target for s in body] == ['a', 'b'],
          repr([getattr(s, 'target', None) for s in body]))

    # Single-target is unchanged, and a bare `comptime NAME` still works.
    one = _parse('def f():\n    comptime a = g()\n')[0].body
    check("single_target_comptime_unaffected",
          len(one) == 1 and one[0].target == 'a', repr(one))


# ── 8. Function type in subscript (index) position ───────────────────────
def test_fn_type_in_subscript():
    src = ('def f(self):\n'
           '    var p = q.unsafe_bitcast[\n'
           '        def(* a: * T) thin abi("C") -> Int\n'
           '    ]()\n')
    stmts = _parse(src)
    subs = [n for n in _walk(stmts) if isinstance(n, N.SubscriptExpr)]
    check("fn_type_subscript_parses", len(subs) >= 1, repr(subs))
    check("fn_type_in_subscript_not_a_slice",
          not any(isinstance(n, N.SliceExpr) for n in _walk(stmts)),
          "a slice was produced for the function type")

    # Ordinary slices and plain indexes must be unaffected.
    check("plain_slice_still_a_slice",
          any(isinstance(n, N.SliceExpr)
              for n in _walk(_parse('def f():\n    var y = a[1:2]\n'))))
    check("plain_index_not_a_slice",
          not any(isinstance(n, N.SliceExpr)
                  for n in _walk(_parse('def f():\n    var y = a[i]\n'))))


# ── 9. Decorated import ──────────────────────────────────────────────────
def test_decorated_import():
    src = ('@stable(recursive=True)\n'
           'from std.builtin.tuple import Tuple\n')
    st = _parse(src)[0]
    check("decorated_import_parses", isinstance(st, N.FromImportStmt), repr(st))
    check("decorated_import_records_deco",
          len(getattr(st, 'decorators', [])) == 1, repr(getattr(st, 'decorators', None)))
    # A bare `@deco` and `@deco(x)` must stay distinguishable.
    bare = _parse('@stable\nimport os\n')[0]
    check("bare_decorated_import_records_name",
          getattr(bare, 'decorators', []) == ['stable'],
          repr(getattr(bare, 'decorators', None)))
    check("undecorated_import_has_no_deco",
          getattr(_parse('import os\n')[0], 'decorators', []) == [])
    check("undecorated_from_import_has_no_deco",
          getattr(_parse('from a import b\n')[0], 'decorators', []) == [])


# ── 10. One syntactic construct may yield several statements ─────────────
def test_multi_statement_result():
    # `_parse_stmt_into` is what lets `_parse_comptime` return a list; the two
    # collectors must flatten it rather than nest a list into the body.
    src = ('def f():\n'
           '    if True:\n'
           '        comptime a, b = g()\n')
    body = _parse(src)[0].body[0].then_body
    check("nested_block_flattens_multi_statement",
          len(body) == 2 and all(isinstance(s, N.ComptimeVarStmt) for s in body),
          repr(body))


# ── 11. A struct's comptime BOUNDS are not instance storage ───────────────
def test_struct_param_trait_bounds():
    # `struct S[T: A]` means `T` is a comptime type parameter bounded by the
    # trait `A`, and it is NOT per-instance storage.  `_parse_struct_params_as_
    # fields` knows that and does not put such a parameter in
    # `StructDef.fields` — the rule the comment above `_known_traits` gives for
    # `@fieldwise_init`'s synthesized constructor arity.
    #
    # It recognised the bound only when the annotation was a SINGLE bare trait
    # NAME, because the test compared the whole annotation string against a set
    # of names.  So `T: Copyable & Comparable & Deinitable` — a conjunction,
    # which is how fourteen structs in the new-modular stdlib spell a bound —
    # became a real `VarDecl` field.  Two things then went wrong downstream, and
    # both are silent: the struct measured one field more than it has, so
    # `formal/model.py`'s `struct_is_one_field` said no and a one-word value's
    # receiver became a FRAME ADDRESS; and `@fieldwise_init`'s constructor grew a
    # phantom parameter.  `std/collections/binary_heap.mojo`'s `BinaryHeap` has
    # exactly one field and measured two, which is what put `len(self._data)`
    # on the frame-slot path and produced the refusal
    # "this slot's DECLARED type is 'List[Self.T]' … what is missing is the
    # VALUE".

    # The positive case, spelled the stdlib's way.
    conj = _parse('struct Heap[T: Copyable & Comparable & Deinitable]:\n'
                  '    var _data: List[Self.T]\n')[0]
    check("conjunction_bound_is_not_a_field",
          [f.name for f in conj.fields] == ['_data'],
          repr([(f.name, getattr(f, 'type_ann', None))
                for f in conj.fields]))

    # The single bare name is unchanged — this arm is not what regressed.
    bare = _parse('struct E[T: Movable]:\n    var _v: Int\n')[0]
    check("single_trait_bound_is_not_a_field",
          [f.name for f in bare.fields] == ['_v'],
          repr([f.name for f in bare.fields]))

    # …and the NEGATIVE half of the pair: a parameter that is not a bound is
    # still storage, or a comptime value parameter.  `Level` is an enum, not a
    # trait this unit knows, so the conservativeness the rule always had is
    # preserved — and `&` inside a SUBSCRIPT belongs to whatever that subscript
    # spells, so it does not turn a data type into a bound either.
    val = _parse('struct L[level: Int = 3]:\n    var _fd: Int\n')[0]
    check("value_parameter_is_still_a_field",
          [f.name for f in val.fields] == ['level', '_fd'],
          repr([f.name for f in val.fields]))
    enum = _parse('struct S[origin: Origin]:\n    var _it: Int\n')[0]
    check("unknown_single_name_is_still_a_field",
          [f.name for f in enum.fields] == ['origin', '_it'],
          repr([f.name for f in enum.fields]))

    # A conjunction of VALUE parameters is not a thing this grammar spells, so
    # there is no negative case to invent for it.


# ── 12. The middle tier sees the free names in all of it ──────────────────
def test_used_idents_covers_new_syntax():
    # `mojo/middle/types._used_idents_node` is the fallback that
    # `discover_closures` turns into a nested def's capture list
    # (`used - inner_declared`). It used to END in a bare `return set()`, so any
    # node type without an explicit branch reported NO free names at all — an
    # UNDER-approximation, and the dangerous direction: the free names vanish
    # and the closure does not capture what its body reads. 39 of the 67 AST
    # dataclass node types had no branch, including `ComptimeIfStmt`,
    # `ComptimeForStmt`, `MatchStmt` and `AwaitExpr` — every construct this
    # file's other sections added. It now walks an unhandled node's dataclass
    # fields generically.
    from mojo.middle.types import _used_idents_node as U

    def free(src):
        """The free names of the statements in f's body."""
        mod = N.Parser(N.py_tokenize(src)).parse_module()
        out = set()
        for st in mod[0].body:
            out |= U(st)
        return out

    # An unhandled node type is no longer silently empty.
    check("comptime_if_free_names",
          free('def f():\n    comptime if True:\n        y = a + b\n    return 0\n')
          == {'a', 'b', 'y'}, "a comptime if's body must be visible")
    check("comptime_for_free_names",
          free('def f():\n    comptime for i in r:\n        y = a + b\n    return 0\n')
          == {'a', 'b', 'r', 'y'}, "a comptime for's iterable and body")
    check("comptime_var_rhs_is_a_use",
          free('def f():\n    comptime x = a + b\n    return 0\n') == {'a', 'b'},
          "the target is a binding, only the RHS is free")
    check("await_operand_is_a_use",
          free('async def f():\n    y = await g(a, b)\n    return 0\n')
          == {'a', 'b', 'g', 'y'}, "await's operand")
    check("yield_value_is_a_use",
          free('def f():\n    y = yield a + b\n    return 0\n') == {'a', 'b', 'y'},
          "yield's value")
    check("del_target_is_a_use",
          free('def f():\n    del a\n    return 0\n') == {'a'},
          "del reads the name it unbinds")

    # A pattern BINDS; it is not a use of an enclosing name. In `match`
    # semantics a bare name in a pattern is an irrefutable capture, so
    # `case Int(v)` binds both `Int` and `v` and neither may be captured.
    check("match_pattern_binds_type_and_name",
          free('def f(s):\n    match s:\n        case Int(v):\n            return a + v\n'
               '        case _:\n            return 0\n') == {'s', 'a'},
          "neither the type name nor the binding is free")
    check("match_seq_pattern_binds",
          free('def f(s):\n    match s:\n        case [x, y]:\n            return x + a\n'
               '        case _:\n            return 0\n') == {'s', 'a'},
          "sequence-pattern elements bind")
    check("match_dict_pattern_binds",
          free('def f(s):\n    match s:\n        case {"k": z}:\n            return z + a\n'
               '        case _:\n            return 0\n') == {'s', 'a'},
          "dict-pattern values bind, its string key is not a name")
    check("match_or_of_literals_has_no_names",
          free('def f(s):\n    match s:\n        case 1 | 2:\n            return a\n'
               '        case _:\n            return 0\n') == {'s', 'a'},
          "alternation of literals binds nothing")
    check("match_as_binds_both_and_guard_is_a_use",
          free('def f(s):\n    match s:\n        case other as w if w > 3:\n            return w + a\n'
               '        case _:\n            return 0\n') == {'s', 'a'},
          "`as` binds both sides; the guard reads what the pattern bound")
    # The one pattern shape that really DOES read an enclosing name is a dotted
    # value pattern, `case mod.CONST`, and its base must survive.
    check("match_dotted_value_pattern_keeps_base",
          free('def f(s):\n    match s:\n        case mod.CONST:\n            return a\n'
               '        case _:\n            return 0\n') == {'s', 'mod', 'a'},
          "the base of a value pattern is a use, not a binding")

    # Consistency with the pre-existing ForStmt, which also does not report its
    # loop variable: a binding is a binding whichever statement introduced it.
    check("for_loop_var_not_free",
          free('def f():\n    for i in a:\n        y = b\n    return 0\n') == {'a', 'y', 'b'},
          "matches comptime for")

    # And the boundaries still hold: the generic walk must not descend into a
    # nested callable, or the ENCLOSING function would capture what only the
    # inner one needs.
    check("nested_def_is_a_boundary",
          free('def f():\n    def g():\n        return a + b\n    return 0\n') == set(),
          "a nested def's body is not the outer function's free names")
    check("nested_lambda_is_a_boundary",
          free('def f():\n    g = lambda: a + b\n    return 0\n') == {'g'},
          "a lambda's body is not the outer function's free names")

    # A node with no names at all stays empty — the generic walk must not
    # invent uses out of `VarDecl.name` or a str-typed annotation.
    check("no_names_stays_empty",
          free('def f():\n    return 1 + 2\n') == set(), "literals only")
    check("var_decl_name_is_not_a_use",
          free('def f():\n    zz = 5\n    return zz\n') == {'zz'},
          "the assignment target is a use, per AssignStmt's branch")


# ── 11. A bracket that MIXES a keyword element with a later positional ──────
def test_bracket_mixing_keyword_and_positional():
    """`f[T=Int, "O_APPEND", linux=..., macos=...]` must PARSE, and keep both
    elements.

    This is the language's own bracket-call form, not a stdlib quirk: the
    project's `def platform_map[T: DType, operation, *, linux=..., macos=...]`
    (std/sys/info.mojo) puts a positional AFTER a keyword and BEFORE further
    keywords, and `std/io/file.mojo` calls it that way four times. Two defects
    made the shape unparseable, and `_skip_comptime_rhs`'s bare `except:` turned
    the resulting ParseError into the `IdentExpr('_comptime_expr')` placeholder —
    so the alias read as a placeholder at every use, and the file-open flags
    built from it were a wrong answer rather than a refusal
    (bugs/CODEGEN_comptime_function_type_alias_is_erased_by_the_parser.md,
    part 2).

    Both elements must SURVIVE, and in order: the old code parsed a bare
    positional and then discarded it (the comment "else positional arg:
    arg_expr already fully parsed" described no code), so a positional that did
    parse was still lost.
    """
    def _comptime_value(src):
        stmts = _parse(src)
        return stmts[0].value

    # The real stdlib call shape: keyword, then positional, then two keywords.
    v = _comptime_value(
        'comptime O_APPEND = platform_map[\n'
        '    T=Int, "O_APPEND", linux=0x0400, macos=0x0008\n'
        ']()')
    check("mixed_bracket_is_not_the_comptime_placeholder",
          not (isinstance(v, N.IdentExpr) and v.name == '_comptime_expr'),
          repr(v))
    check("mixed_bracket_keeps_its_own_value",
          isinstance(v, N.CallExpr) and isinstance(v.func, N.SubscriptExpr),
          repr(v))
    attrs = list(v.func.attrs or [])
    check("mixed_bracket_keeps_every_element_in_order",
          [n for n, _ in attrs] == ['T', None, 'linux', 'macos'],
          repr([n for n, _ in attrs]))
    check("mixed_bracket_keeps_the_positional_value",
          len(attrs) == 4 and isinstance(attrs[1][1], N.StringLiteral)
          and attrs[1][1].value == 'O_APPEND',
          repr(attrs[1] if len(attrs) > 1 else None))

    # A bare literal directly after a keyword — the minimal form, and the one
    # that used to leave the token unconsumed so `_expect("RBRACKET")` raised.
    v2 = _comptime_value('comptime A = f[T=Int, 1]()')
    check("keyword_then_bare_literal_parses",
          isinstance(v2, N.CallExpr)
          and [n for n, _ in (v2.func.attrs or [])] == ['T', None],
          repr(v2))

    # ... and a bare NAME after a keyword, which parsed BEFORE this fix and was
    # silently dropped. It has to be kept, under its own name.
    v3 = _comptime_value('comptime A = f[T=Int, op]()')
    check("keyword_then_bare_name_is_kept",
          isinstance(v3, N.CallExpr)
          and [n for n, _ in (v3.func.attrs or [])] == ['T', 'op'],
          repr(v3))

    # POSITIONAL-FIRST order was always the working one (it takes a different
    # branch) and must keep working: this is the negative half of the pair, so
    # a parser that simply accepted more without modelling the mix would fail
    # it by changing what `f[T, 1]` puts in `attrs` (it puts a TupleExpr in
    # `index` and leaves `attrs` None).
    v4 = _comptime_value('comptime A = f[T, 1]()')
    check("positional_first_order_is_unchanged",
          isinstance(v4, N.CallExpr) and v4.func.attrs is None
          and isinstance(v4.func.index, N.TupleExpr),
          repr(v4))

    # The all-positional bracket must NOT start producing attrs: it has its own
    # consumers reading `index`.
    v5 = _comptime_value('comptime A = f[1, 2]()')
    check("all_positional_bracket_keeps_its_index_form",
          isinstance(v5, N.CallExpr) and v5.func.attrs is None
          and isinstance(v5.func.index, N.TupleExpr),
          repr(v5))

    # A slice VALUE beside a positional: `x=(-50)::` is a SliceExpr, and the
    # ellipsis arm is the one element that carries no value to keep.
    v6 = _comptime_value('comptime A = f[x=(-50)::, 3]()')
    check("keyword_slice_then_positional_parses",
          isinstance(v6, N.CallExpr)
          and [n for n, _ in (v6.func.attrs or [])] == ['x', None]
          and isinstance(v6.func.attrs[0][1], N.SliceExpr),
          repr(v6))
    v7 = _comptime_value('comptime A = f[T=Int, ...]()')
    check("ellipsis_after_a_keyword_still_parses",
          isinstance(v7, N.CallExpr)
          and [n for n, _ in (v7.func.attrs or [])] == ['T'],
          repr(v7))

    # `byte=:-1` is the keyword-slice SUBSCRIPT (not a call) and is lowered by
    # `_lower_subscript` off `attrs`; the fix must not have moved it.
    sub = _parse('comptime A = f[byte=:-1]')[0].value
    check("keyword_slice_subscript_still_carries_its_attr",
          isinstance(sub, N.SubscriptExpr) and sub.attrs
          and sub.attrs[0][0] == 'byte'
          and isinstance(sub.attrs[0][1], N.SliceExpr),
          repr(sub))


# ── 11b. A declared DEFAULT on a bracketed comptime parameter is kept ──────
def test_bracket_param_default_is_captured():
    """`def f[T, y=0, *, linux=0]()` must record `y`'s and `linux`'s defaults.

    `_parse_generic_params_capture` walked the bracket capturing NAMES only
    and skipped everything else, so `y=0`'s default was thrown away with the
    annotation and the `//` separator. That is invisible until a call site
    omits the parameter: `f[T=Int]()` has exactly one source of truth for
    `y` — the declaration — and with it dropped the interpreter had nothing
    to bind and answered None where the source says 0
    (the interpreter's keyword-bracket call binding, which reads this table).

    Kept in its own field rather than folded into `param_defaults`, because
    that table's LENGTH is the trailing-default offset arithmetic's input
    (`mojo/middle/exprtypes.py`'s `_trailing_default_at`) and a comptime
    default in there would shift every RUNTIME default's slot.
    """
    fd = _named(_parse('def f[T, y=0, *, linux=0]():\n    return y\n'), 'f')
    check("bracket_params_keep_their_names",
          fd.comptime_params == ['T', 'y', 'linux'],
          repr(fd.comptime_params))
    check("bracket_param_defaults_are_captured",
          sorted((fd.comptime_param_defaults or {}).keys()) == ['linux', 'y'],
          repr(getattr(fd, 'comptime_param_defaults', None)))
    y = (fd.comptime_param_defaults or {}).get('y')
    check("bracket_param_default_keeps_its_value",
          isinstance(y, N.IntLiteral) and y.value == 0, repr(y))
    check("bracket_param_default_is_not_in_param_defaults",
          'y' not in (fd.param_defaults or {}), repr(fd.param_defaults))

    # A parameter with no default is absent from the table, not present with
    # a None value — "no default" and "a default of None" must stay
    # distinguishable, because the former is what makes an unsupplied
    # bracketed parameter a refusal.
    fd2 = _named(_parse('def g[T: Int, U](n: Int) -> Int:\n    return n\n'), 'g')
    check("bracket_params_without_defaults_are_absent",
          fd2.comptime_params == ['T', 'U'] and not fd2.comptime_param_defaults,
          repr(getattr(fd2, 'comptime_param_defaults', None)))

    # A default that is itself an expression, and a `//` comptime/runtime
    # separator before one: neither may leak tokens into the name list.
    fd3 = _named(_parse('def h[T: Int, S = [1, 2] //, linux: Int = 7](n):\n'
                        '    return n\n'), 'h')
    check("expression_default_does_not_leak_names",
          fd3.comptime_params == ['T', 'S', 'linux'],
          repr(fd3.comptime_params))
    s = (fd3.comptime_param_defaults or {}).get('S')
    check("expression_default_is_parsed_as_an_expression",
          isinstance(s, N.ListExpr) and len(s.elements or []) == 2, repr(s))

    # A `=` inside a function-typed annotation's OWN parens is not a default:
    # it lives at bracket depth > 1, which the capture loop is counting.
    fd4 = _named(_parse('def w[f_key: def(Int, Int) -> None thin](self):\n'
                        '    pass\n'), 'w')
    check("annotation_parens_do_not_become_a_default",
          fd4.comptime_params == ['f_key'] and not fd4.comptime_param_defaults,
          repr(getattr(fd4, 'comptime_param_defaults', None)))


# ── 12. A MISPARSE is a refusal; a FUNCTION TYPE is still a placeholder ────
def test_comptime_rhs_misparse_is_refused():
    """The two fates of a `comptime` right-hand side must be DISTINGUISHABLE.

    A function type (`comptime F = def[T](Int) -> None`) is deliberately not
    modelled and becomes `IdentExpr('_comptime_expr')`. A bracket call that
    failed to parse became the SAME placeholder, because `_skip_comptime_rhs`'s
    bare `except:` turned the ParseError into a skip-to-newline — so
    "not implemented" and "misparsed" were one value, every consumer read the
    alias as a placeholder, and the stdlib's `O_CREAT`/`O_APPEND`/`O_CLOEXEC`
    file-open flags were built from a placeholder rather than from
    `0x200 | 0x400 | 0x1000`. A wrong answer, invisibly
    (bugs/CODEGEN_comptime_function_type_alias_is_erased_by_the_parser.md,
    parts 1 and 2).

    So a misparse is now a `SyntaxError` naming the line, and the deliberate
    skip stays a placeholder. Both halves are asserted, because asserting only
    the refusal would pass for a parser that refuses everything.
    """
    def _value(src):
        return _parse(src)[0].value

    # The deliberate case, all three spellings. The parenthesized multi-line
    # one is 6 of the 22 function-type aliases in the new-modular stdlib
    # (std/_plugin/_trait.mojo's `_ReduceGeneratorPluginHookFnType`), so it is
    # the case that decides whether a real stdlib module still parses.
    for i, src in enumerate((
            'comptime F = def[T](Int) -> None',
            'comptime F = (\n    def[T](Int) -> None\n)',
            'comptime F = def[T, U](SIMD[T, U], Int) -> SIMD[T, U]')):
        v = _value(src)
        check("function_type_alias_is_still_the_placeholder_%d" % i,
              isinstance(v, N.IdentExpr) and v.name == '_comptime_expr',
              repr(v))

    # The misparse, which is now a refusal naming the offending text.
    for i, src in enumerate((
            'comptime A = f[+](1)',
            'comptime A = f[T=Int, )]()',
            'comptime A = [1, 2')):
        try:
            _parse(src)
            check("misparsed_comptime_rhs_is_refused_%d" % i, False,
                  "no exception")
        except SyntaxError as e:
            msg = str(e)
            check("misparsed_comptime_rhs_is_refused_%d" % i,
                  'comptime' in msg and 'function TYPE' in msg, msg[:160])

    # The exception set is enumerated, not bare: a `TypeError` from a
    # malformed AST node used to be read as "unparseable comptime rhs" and
    # become a placeholder, which is how a real crash in this function could
    # present as a stdlib constant silently reading 0. Only a PARSE failure
    # is a refusal, and these are the shapes that must still parse.
    for i, src in enumerate((
            'comptime A = 0x10',
            'comptime A = "s"',
            'comptime A = [1, 2]',
            'comptime A = {"k": 1}',
            'comptime A = a.b.c',
            'comptime A = f[1,]()',
            'comptime A = f[T=Int]()')):
        try:
            _parse(src)
            check("well_formed_comptime_rhs_still_parses_%d" % i, True)
        except Exception as e:                          # noqa: BLE001
            check("well_formed_comptime_rhs_still_parses_%d" % i, False,
                  "%s: %s" % (type(e).__name__, e))


def run_tests():
    print("=" * 70)
    print("PARSER: new-modular syntax")
    print("=" * 70)
    for fn in (test_dotted_literal, test_match, test_lambda, test_capture_lists,
               test_imm_convention, test_struct_where,
               test_multi_target_comptime, test_fn_type_in_subscript,
               test_decorated_import, test_multi_statement_result,
               # Both sides of this merge appended a case to the same list
               # and neither was a revert of the other: this branch brought
               # the bracket/comptime cases, master brought the struct-param
               # trait bounds. The union, each name once.
               test_struct_param_trait_bounds,
               test_used_idents_covers_new_syntax,
               test_bracket_mixing_keyword_and_positional,
               test_bracket_param_default_is_captured,
               test_comptime_rhs_misparse_is_refused):
        print(f"\n--- {fn.__name__}")
        fn()
    print()
    print("=" * 70)
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    print("=" * 70)
    return _FAIL == 0


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)