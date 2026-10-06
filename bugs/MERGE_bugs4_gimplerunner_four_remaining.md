# MERGE: the merged ten-branch tree leaves four gimplerunner rows red, and each is a branch INTERACTION

Filed while merging the ten `bugs4` branches onto master (branch
`work/merge-bugs4`). **Not a bug in any one branch**: every one of the four
passes on the branch that added it, and three of them are already narrowed to a
specific pair. This is the queue for whoever picks the next batch up.

Measured, one at a time, `python3 tools/memslot.py --gb 8 --label t --`:

| file | master | bugs4-1..10 merged |
|---|---|---|
| `test_gimple.py` | 371 passed / 0 failed | **379 / 0** |
| `test_gimple_runner.py` | 309 / 0 | **372 / 4** |
| `test_link_mode.py` | 16 / 0 | **17 / 0** |
| `test_module_cache.py` | 147 / 0 | **153 / 0** |
| `test_gimple_generator_runner.py` | 202 / 0 | **212 / 0** |
| `test_silent_noop_iter.py` | 23 / 0 | **26 / 0** |

So 65 of the 69 new cases pass and four do not. All four are listed here with
the measurement that narrows each one. Four MORE interactions were found and
FIXED in the merge itself, each with its own commit; this doc is only what is
left.

---

## 1. `own_module_global_beats_the_imported_homonym` — compiled `b-side`, CPython `a-side`

    fgl_b.py:  N = 'b-side'
    fgl_a.py:  from fgl_b import N
               N = 'a-side'
               def main(): print(N)
               main()

Added by `bugs4-3-c` (`6b7241c5`, "a bare read of a `from b import K` global
loads b's field"), together with `_gmi_scan_imported_global_homes` and the two
gates that doc lists.

**What is already fixed.** The precedence I merged put the import record ahead
of "this module declares the name", which is backwards in Python's terms; that
is corrected (`0fb2aa1c`), with the reasoning written down. It was not enough,
and the measurement says why:

    _own_imported_global_home          {}          <- the scan correctly declined
    _own_imported_global_field         {}
    _own_global_var_types              {'N': 'char *'}
    _global_to_module                  {'N': 'fgl_b'}   <- first writer across the closure
    _module_global_field_type('root', 'N')   None
    _module_global_field_type('fgl_b', 'N')  ('char *', 'char *')
    gen._current_module_ctx             'root'

So the read's arm 1 (`_module_global_field_type(_read_mod, name)`) misses,
arm 2 is empty because the scan declined, and arm 3 routes to `fgl_b` through
the shared name-keyed owner map. On `work/bugs4-3-c`'s own tree the same fixture
emits `_t1 = _root_globals.N` and prints `a-side`, so that tree has the `root`
triple at read time.

**Next step.** Find why `_module_globals['root']` has no `N` entry when the body
is emitted although the emitted struct has `.N = "a-side"`. The reset is
`mojo/backend_gimple/module_gen.py:11480`
(`self._module_globals[current_mod_name] = []`, "so the registration loop below
can test"), and the registration loop is the `for gname in sorted(_declared_globals)`
one that appends the `(name, c_type, g_mtype)` triple at ~12167. So either the
reset runs between `N = 'a-side'` being declared and `main`'s body being
emitted, or `N` never reaches `_declared_globals` on this tree and the field
comes from somewhere else. `_gscan_declare_global` and the `ImportStmt` /
`FromImportStmt` arms of that loop are where to read. Bisect point: the failure
appears at the `bugs4-4-c` merge (`d232bd84` builds the single-TU case; every
later merge commit fails it), which is a wider net than "bugs4-3-c vs master"
and is the first thing to narrow.

---

## 2. `imported_module_list_of_structs_reprs_them` — `[P(x='a'), P(x='b')]` where CPython prints `[P<a>, P<b>]`

    # P has a __repr__; the list literal lives in an IMPORTED module
    print([P('a'), P('b')])

The list's own element-repr shim is not recorded, so the runtime's per-slot
reader produces the generated field dump instead of the user's `__repr__`.

**Measured narrowing.** `mojo/backend_gimple/emit_exprs.py`'s
`_lower_list_literal` calls
`gimple_exprtypes.struct_elem_repr_shim(gen, elem)` (after the bugs4-6-c merge
consolidated the backend copy into the middle tier) and then
`ginf.elem_repr_operand(gen, _elem_repr)`. That predicate has two gates:
`getattr(gen, 'emit_struct_defs', False)` and `gen._elem_repr_needed.add(sn)`.
`_emit_reflection_dispatch` was extended (in the same merge) to emit a shim for
every struct in `_elem_repr_needed`, and `_reflect_struct_names` was extended to
include them, so the request and the emission are one answer. Suspect the
IMPORTED-module half: an imported module compiles with `emit_struct_defs`
False, so the gate answers `''` and no shim is named \u2014 but the ROOT's
preamble is supposed to carry the shim, which is what this case needs. Read
`_emit_reflection_fwd_decls`'s position relative to the imported-module splice
first; the merged `_reflect_struct_names` now mutates `_rs_names` for
`_elem_repr_needed` entries, and whether the forward-declaration pass sees that
list depends on ordering.

---

## 3. `gimple_dict_repr_kinds_agree_with_cpython` — FIXED 2026-10-04 (`work/bugs7-1`)

**Status: green.** `test_gimple_runner.py` is 385 passed / 3 failed, and this
row is one of the three that is no longer failing. `tools/suite.py`'s
`gimplerunner` marker moved from `'4 failing:'` to `'3 failing:'` in the same
commit, which is the count-checked half of the change: a marker that still said
4 would have reported a FAILURE for a suite that improved.

What landed, in the order the two faults were:

1. **The operand's kind** — exactly the diagnosis below, and the fix is the
   mirror of what the LHS arm already did. `_lower_percent_dict` coerced the
   template to `char *` and left the mapping as whatever `lower_expr` typed it,
   which for every container global is a boxed `int64_t`. Both operands are now
   coerced to the parameter types the callee declares.
2. **What an unkeyed spec MEANS** — the note below said "decide which" and
   added that the honest end state is not "make it compile". Measured on
   CPython 3.14.7, this doc's "CPython **TypeError**" claim was **wrong**:
   `'%s' % d` prints the dict, because a non-tuple right operand is consumed by
   one spec. The TypeError is `'%s %s' % d` ("not enough arguments for format
   string"). So `mojo_str_format_dict` grew a third parameter — the generated
   per-TU `_mojo_repr_dict` — which is how the unkeyed arm renders the mapping.
   It travels in rather than being re-derived in the runtime because the runtime
   cannot render a dict: each slot's kind and the recorded `val_repr` are only in
   the generated block. That is the same bargain `MojoDict.val_repr` and
   `mojo_list_set_elem_repr` already make, and the reason there is still one
   implementation of "what a dict looks like". A NULL third argument degrades to
   the old copy-the-spec-through behaviour, so a TU with no reflection block is
   not made worse, and a SECOND unkeyed spec raises the real TypeError instead of
   printing `%s` — it used to print the spec through, which was the
   silent-wrong-answer shape.

The original text follows, unchanged, because the reproduction and the narrowing
are what a reader needs and both were right about the cause.

### — original report —

Reproduction, all four lines correct against CPython today:

    d = {}
    d['n'] = None; d['z'] = 0; d['b'] = False; d['f'] = 1.5
    d['s'] = 'v'; d['c'] = [1, 2]; d['d'] = {}
    print(d)                                     # matches
    print({'a': None, 'z': 0, 'b': True, 'f': 2.5, 's': 'q'})   # matches
    print({k: None for k in ['p', 'q']})         # matches
    print({k: 0 for k in ['p', 'q']})            # matches
    print('%s' % d)                              # FAILS TO COMPILE

    dk.py:13:38: error: passing argument 2 of 'mojo_str_format_dict'
             makes pointer from integer without a cast

So every VALUE KIND is right and the failure is the last line: `'%s' % d`
picks the dict-formatting route (`mojo_str_format_dict(fmt, d)`) and lowers `d`
to an `int64_t` \u2014 i.e. the `%` operand's container kind is not resolved, while
`print(d)` right above it is. The same operand as a `print` argument reaches
`_gen_print`; as a `%` right operand it goes through a different dispatch, and
that one has no `_get_actual_type` / `container_kind` step. Compare
`_lower_BinaryOp`'s `%` arm with `_gen_print`'s container arm: the former needs
the same "a module-level `d` reads back as an `int64_t` field" repair
`_gen_print` already has.

Note `'%s' % <a dict>` is a CPython **TypeError** ("not all arguments
converted"), so the honest end state is not "make it compile" \u2014 decide which,
and fix the operand's kind either way, because the current answer is a
build failure rather than either.

---

## 4. `gimple_bound_method_in_a_module_global_keeps_its_convention` — SIGSEGV

`bugs4-1`'s `157715da` ("a callable's return type survives a function RETURN, and
a bound method in a module global keeps its calling convention"). CPython
prints `True\n12\nTrue\n16\n`; the compiled program exits -11 with no output.

Not narrowed further than that here. The relevant code is the
`_ALL_SCALARS` / bound-method receiver dispatch in
`mojo/backend_gimple/emit_exprs.py`'s bare-global read arm and
`emit_methods._lower_bound_method_call` \u2014 the read of a module-global bound
method goes through `gen._captures`/`_global_var_types` there, and bugs4-1
changed exactly that function's name resolution
(`_lower_bound_method_call`'s `fname_raw in gen._captures` /
`elif fname_raw not in gen.var_types and fname_raw in gen._global_var_types`
arms). Start from the generated C: the crash is a call through something that
is not the bound-method handle.

---

## What was found and FIXED in the merge (for the next reader's benefit)

These were the same interaction class and each has its own commit; they are
listed because the pattern recurred and the next merge will hit it again.

1. **`re.compile` stopped working** (`af9bab3d`). bugs4-9-c's raise for a call
   on an uncompiled-module marker fired for `re`, whose value nothing reads.
   One table, `mojo.middle.types._COMPILE_TIME_CALL_MODULES`, read by both the
   recogniser that fills `_regex_patterns` and the predicate that declines to
   raise.
2. **A duplicated `kind == 2` row in `_mojo_repr_dict`** (`a7295090`). The
   auto-merge had already placed master's arm above the conflict and the
   resolution added it again, leaving an `else if` with an empty body followed
   by a bare `if` \u2014 so `_s` reached the closing `cat` unassigned and
   `test_silent_noop_iter.py` segfaulted. Five cases at once.
3. **The surviving copy's `else` was missing** (`cf56ae05`), one level on: a bool
   slot fell out of the chain and printed `1`/`0`. Five more cases.
4. **A defaulted return type overwrote a measured one** (`d2080227`).
   bugs4-1's `register_imported_symbol` propagated `_resolved_export_entry`'s
   `int64_t` fallback for an UNANNOTATED def into `func_return_types`.
5. **One declined argument read as a unanimous call site** (`c5852929`).
   bugs4-4-c's container veto and bugs4-5's `cur is None` arm compose into
   typing a scalar slot as a list pointer.

The lesson for the next merge, stated once: **when both sides changed a
generated-C TEMPLATE or a chain of `if`/`else if` arms, diff the RESULTING C
against both branches' C for one small fixture.** Twice the artefact was a
chain arm that parsed, compiled and ran, and was wrong in a way no
single-branch test could see.