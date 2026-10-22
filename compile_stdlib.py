#!/usr/bin/env python3
"""
Attempts to transpile all (or a specific) Mojo stdlib module(s) through gimple_codegen.

Usage:
  python compile_stdlib.py                 # attempt entire stdlib
  python compile_stdlib.py --module time   # attempt only the time module
"""

import os
import sys
import subprocess
import argparse
import tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from module_loader import STDLIB_PATH
from build_config import find_gcc
from build_stdlib_dylib import compile_module_to_c_cached

import cas

_GCC = find_gcc()
_RUNTIME_INC = str(Path(__file__).parent / 'runtime')
_GCC_FLAGS = ('-fgimple', f'-I{_RUNTIME_INC}', '-fsyntax-only', '-D__MOJO_STDLIB_MODE__')

# In-process L1 cache for GCC syntax-check results (key -> (rc, stderr)).
# Each worker process has its own copy; CAS (L2) is shared.
_gcc_syntax_cache: dict = {}

# Subtrees of the stdlib to attempt, in the order we want maximal coverage:
# benchmarks first (smallest, exercises real client code), then the library
# proper, then the test corpus, then tools.
#
# This is a PREFERENCE ORDER, not an enumeration. It used to be the whole
# story, and that was a silent-coverage hole: a root that does not exist is
# skipped without a word (`if not search_root.exists(): continue`), so any
# top-level directory the stdlib adds later would simply never be compiled —
# while the run still reported "PASSED: 610" over the files it did find. Five
# of the nine entries here (`_core`, `collections`, `io`, `math`, `os`) are
# from the previous stdlib layout and do not exist at all in the current one.
#
# `discover_roots` below now appends every top-level directory the stdlib
# actually has, so a new subcomponent is picked up without editing this list;
# this list only decides the ORDER of what is already known.
DEFAULT_ROOTS = ['benchmarks', 'std', 'test', 'tools']

# Directory names under the stdlib root that are never source to compile even
# though they sit beside the ones that are. Keyed by name so a subcomponent
# appearing here is a deliberate, visible decision.
ROOT_EXCLUDE = {
    # Build/tooling trees: Python and shell, not Mojo modules. `scripts` is in
    # this stdlib today with no .mojo files at all, but it is the exact shape of
    # the hole described above, so it is named rather than left to chance.
    'scripts',
    'docs', 'doc', 'examples', 'proposals', 'bench', 'bazel-*',
}


def discover_roots(base: Path) -> list:
    """Every top-level directory under the stdlib root that holds .mojo files,
    ordered by DEFAULT_ROOTS preference first and then alphabetically.

    The alphabetical tail is the load-bearing part: a subcomponent nobody
    listed still gets compiled, in a deterministic position, instead of being
    silently skipped. `sorted()` rather than directory order, so two runs over
    one tree emit the same order (the failure report and the CAS keys both
    depend on it).
    """
    on_disk = []
    try:
        entries = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return list(DEFAULT_ROOTS)
    for entry in entries:
        name = entry.name
        if name in ROOT_EXCLUDE or name.startswith('.'):
            continue
        if name.startswith('bazel-'):
            continue
        on_disk.append(name)
    preferred = [r for r in DEFAULT_ROOTS if r in on_disk]
    rest = [r for r in on_disk if r not in DEFAULT_ROOTS]
    return preferred + rest


# The `_NEXT_ON_STRUCT` shared reason constant (added 2026-10-01 for the 21
# false-green `next(<struct>)` files) was removed 2026-10-21 with the last of
# its users: by then a growing set of the 21 had left this dict with ladder
# evidence, and the remaining 11 each now carry their own per-file measured
# reason (emitting function, measured receiver type, the shape the current
# machinery cannot lower) — which the one-size description no longer said.
# The class's history lives in
# bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md.

# 2026-10-21 — the `_FACTORY_DATA_PATH` constant (the dependent-return
# factory mechanism's measured REFUSAL for List containers) is removed
# with the refusal it described: the lift landed (in-TU iterator
# protocol in runtime-MojoList terms — see the comment block in
# EXPECTED_FAILURES and bugs/CODEGEN_next_on_a_user_defined_iterator_
# struct_is_unlowered.md, "2026-10-20 (further)"). test_peek/
# test_enumerate/test_take/test_drop left this dict; test_cycle keeps a
# narrowed entry for its 2 user-defined-IterableOwned sites.

EXPECTED_FAILURES = {
    # UPDATE (this session, continued): `create_task`/`create_raising_task`
    # await-composition (`await create_task(<call>) + await create_task(
    # <call>)`, and the `var t = create_task(<call>); ...; await t` shape
    # composed with a SIBLING comptime-bracket-parametrized nested async
    # def) now has real codegen support — see GimpleGen._cpp_expr's
    # AwaitExpr case, `_async_quick_eligible`'s widening, and
    # `_inline_single_use_task_composition`'s widened inner-call-shape
    # check, all in gimple_codegen.py. `_create_task(f(), desired_worker_id
    # =...)` (the affinity-hinted variant) is also now supported — the hint
    # is documented as purely advisory, so it's dropped (an honest,
    # documented simplification; the codegen has no worker-affinity
    # concept). `test_asyncrt.mojo` now compiles cleanly end-to-end
    # (verified via a real compile+link+run, not just this gcc-syntax-only
    # check): `test_runtime_task`/`test_runtime_taskgroup`/
    # `test_create_task_with_affinity_runs_coroutine` all produce their
    # real, correct values (33, 6, 42). `test_runtime_unified_async_
    # memory_result_raises` (its `build_message` -> `create_raising_task`
    # -> `.wait()` path) is NOT included in that verification: `build_message`
    # returns `String`, which this codegen's coroutine-body emitter is
    # deliberately scalar-only throughout (see _gen_cpp_async_unit's own
    # docstring) — so it still can't be compiled to a real coroutine, and
    # its `create_raising_task(build_message())` call site degrades to the
    # existing, pre-existing `_lower_call` stub (a loud runtime abort(),
    # not a silently wrong value — see bugs/CODEGEN_comptime_bracket_
    # parametrized_function_calls_silently_wrong.md's "Update" section for
    # the full writeup and why this is still an honest, non-silent gap
    # rather than a regression this session introduced). Removed from this
    # dict since this gcc-syntax-only check genuinely passes now (matching
    # every other passing file's own "syntax check only" contract this
    # project has used throughout) -- the remaining `build_message`/String-
    # return gap is real but narrower and separately documented, not
    # papered over.
    #
    # `test_tracing.mojo` — FIXED: monomorphize.py now genuinely supports
    # dual C/C++ output for an elaborated fragment (a nested `async def`
    # inside a comptime-bracket-parametrized generic, e.g. `test_tracing_
    # add`/`test_tracing_add_two_of_them` inside `test_tracing[level,
    # enabled]()`) -- `instantiate()` compiles+CAS-caches a companion
    # `.cpp.o` alongside the ordinary `.o` whenever `GimpleGen.generated_
    # cpp` is non-empty, `monomorphize_source`'s substitution gained
    # `_shadowed_spans`/`_sub_outside_spans` to skip a nested function's
    # own re-declared (shadowing) bracket-parameter scope, `_cpp_stmt`
    # gained `ComptimeVarStmt` (a compile-time-only no-op) and a bare
    # `abort(...)` call case, and `Trace` joined `BlockingScopedLock` as a
    # recognized no-op-elidable async guard type (see gimple_codegen.py's
    # `_ASYNC_NOOP_LOCK_GUARD_TYPES`). Also fixed two REAL, separately
    # hand-verified bugs surfaced while landing this: a comptime-bracket-
    # argument/ordinary-argument ORDER swap at three separate composition
    # call sites (masked by every existing test's own commutative
    # arithmetic — `lhs + rhs` gives the same sum either order — until
    # test_tracing.mojo's real, non-commutative-enough 3-parameter shape
    # caught it), and `monomorphize.instantiate()` never setting `gen.
    # _current_filename`, which silently no-opped an entire gen_module
    # pass (nested async-with-comptime-params discovery) for every
    # elaborated fragment. See bugs/CODEGEN_comptime_bracket_parametrized_
    # function_calls_silently_wrong.md's own "dual C/C++ output" update.

    # test_locks.mojo — RESOLVED 2026-07-30: the "mutable capture of a
    # non-scalar struct" blocker was actually two codegen bugs in
    # gimple_codegen.py, now fixed:
    #   1. `_gen_for_range` wrote a loop variable that is ALSO a heap-boxed
    #      mutable capture directly (`var = ctr`) instead of through the
    #      box pointer (`*var = ctr`).
    #   2. `_gen_stmt_AssignStmt` coerced a value to the box POINTER ctype
    #      (`int64_t *`) when writing to a boxed mutable local whose
    #      `_write_dest` lvalue is the deref (`*var`, pointee-typed) --
    #      "assignment to 'int64_t' from 'int64_t *'".
    # The file compiles + passes its gcc syntax check (see test_locks's
    # `_ = time_function(test_atomic)` / `_ = lock^` where `_` is boxed
    # because the nested async `inc()` reassigns it via
    # `_ = counter.fetch_add(1)`).
    #
    # 2026-10-01 — the `next(<user-defined iterator struct>)` family. 21
    # files, all of them `test/` or stdlib iterators, that this check
    # reported PASS while their generated C carried a call to a `next`
    # symbol nothing defines. `_lower_call` now REFUSES an unlowered
    # `next(...)` rather than emitting it, which is what turned a silent
    # wrong artifact into a named failure — so these moved from a false
    # green to a declared red. The refusal is right and stays; the shape
    # behind it is not implemented, because `var iter = peekable(list)`
    # types `iter` as `int64_t` rather than `_PeekableIterator *` and
    # inferring an imported generic function's return type through
    # `Self.<member>` is its own project. `next(<struct>)` DOES lower
    # whenever the receiver's type is resolvable; and the `for` loop over
    # these same objects was already a `mojo_unsupported_iter` no-op for
    # the identical reason. Full analysis, the 3-undefined-`next` +
    # 23-`mojo_unsupported_iter` measurement, and the next step:
    # bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md
    #
    # A dict, not a set: the summary at the bottom prints each entry's
    # REASON beside its path, and a bare set could only ever satisfy the
    # membership tests. It was empty until now, so nothing had ever
    # exercised that.
    # REMOVED 2026-10-03, with the artifact evidence rather than the syntax
    # check: `test/iter/test_empty.mojo`, `test/iter/test_once.mojo` and
    # `test/itertools/test_repeat.mojo` now compile, LINK and run. The
    # iterator structs they need (`_Empty`, `_Once`, `_RepeatIterator`) are
    # instantiated IN this translation unit by
    # `mojo/backend_gimple/elab_intu.py` rather than declared `extern` beside a
    # CAS object, because every one of them overloads `__iter__` on `var self`
    # and on `ref self`, both overloads erase to `(Struct *)`, and so
    # `_register_generic_struct` can register NEITHER and declines the struct —
    # which is what typed the receiver as a boxed `int64_t` and left
    # `next(it)` with nothing to dispatch on. Verified per file, after a real
    # `gcc -c` (`nm -g` on the module's own object):
    #
    #   test_empty  T _empty_1_T_3_Int
    #               T __Empty_1_T_3_Int___iter___0120be / _0120be_2
    #               T __Empty_1_T_3_Int___next__ / T __Empty_1_T_3_Int_bounds
    #   test_once   T _once_1_T_5_Int64
    #               T __Once_1_T_5_Int64___next__, T __Once_1_T_5_Int64_bounds
    #   test_repeat T _repeat_11_ElementType_5_Int64 and _6_String
    #               T __RepeatIterator_11_ElementType_5_Int64___next__
    #
    # and a real `ld` of each module's C against `runtime/fire_runtime.c`
    # leaves no undefined iterator symbol (the only stubs are `std.testing`'s
    # `assert_equal`/`assert_raises`, which this driver does not compile), the
    # binary exits 0. `once(10)` and `repeat(42, times=3)` needed no
    # inference at all — the type argument is the literal's own exact Mojo
    # type. The other 18 stay: they need either overload selection on a trait
    # bound (`peekable`'s `Some[Iterable]` vs `Some[IterableOwned]`), a
    # dependent return type through `Self.IteratorOwnedType`, or an overload
    # OUTSIDE the iteration protocol (`_TakeWhileIterator.__init__`,
    # `List.__getitem__`), which in-TU provably cannot yet carry. See
    # bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md.
    #
    # `test/collections/test_span.mojo` is out of this list as of 2026-10-03,
    # and it is the one removal in this family that needed no inference at
    # all: its receiver was a REAL `Span *`, not a boxed integer, so nothing
    # about the callee's type had to be inferred. Three defects stood between
    # the cursor and that receiver, all now fixed:
    #   * `iter(<span>)` was refused by `_try_bind_iter_cursor` (then
    #     `_try_bind_list_iter`), which gated on `MojoList *` — so a Span,
    #     which IS a sequence with a real length, got no cursor at all and
    #     `next(it)` had no receiver to dispatch on. The gate is now the tree's
    #     own `_struct_data_field` + `_len` test, so `span[i]` and
    #     `iter(span)` agree by construction, and the cursor's accessors all
    #     live in `mojo/middle/itcursor.py` so `next(it)`, `it.__next__()`,
    #     `for x in it:` and `len(it)` cannot drift apart.
    #   * `len(<cursor>)` answered the CONTAINER's total length, unchanged by
    #     every `next()` — wrong for a partially consumed iterator on the list
    #     cursor too, and silently so.
    #   * `Span(<list>)` stored the list POINTER in `_data` and left `_len`
    #     unset, so `len(span)` was whatever the fresh allocation happened to
    #     hold and `span[i]` read the list's own header. Both silent, both
    #     exit 0.
    # 2026-10-21 (further) — REMOVED from this dict:
    #   std/itertools/itertools.mojo and std/collections/string/iterators.mojo
    #   — the two HOME modules: their own GENERIC definition-site methods
    #   (e.g. `_Product2.__next__`) were emitted dead, unlowerable (a type-
    #   param-typed field erases to int64_t in the DEFINITION TU, so
    #   `next(self._a)` there hit the emit_calls hard refusal and the WHOLE
    #   module failed; the instantiating TU is the one that emits the
    #   mangled copy with real field types). Fix (final design, after the
    #   first cut — an UNCONDITIONAL body skip for type-param structs —
    #   measured a real A/B regression: 1,768 definitions dropped, 133 of
    #   them referenced from other TUs, e.g. `Span_count`/`Span_copy_from` —
    #   `Span` is generic but its bodies were lowerable and genuinely
    #   called, undefined at link): module_gen now attempts EVERY body
    #   exactly as master did and catches only the codegen's own honest
    #   `cannot compile module:` RuntimeError — a per-method TRANSACTIONAL
    #   fallback (rollback: func_parts from the mark, the import-scope
    #   stack down to its pre-call depth, body_lines/decls, the annotation-
    #   seeded container maps, the line-source override) that drops exactly
    #   the refusing method to prototype-only with a diagnostic comment;
    #   every lowerable body emits byte-identical to master (the 6 refusing
    #   methods here are the `next(self._x)` family: _Product2/_Cycle/
    #   _TakeWhile/_DropWhile/_Take/_Drop `__next__`). fire_compiler still
    #   records `StructDef.type_param_names` (ALL bracket-block names,
    #   including trait-bound ones — the old capture dropped them); the loop
    #   uses it only to scope the false-green guard below.
    #   The same fallback + a FALSE-GREEN GUARD in
    #   emit_resolve._elaborate_generic_call resolves the sibling measured in
    #   clean master: std/iter/__init__.mojo's C carried 4 calls to the
    #   never-defined mangled `next_12_IteratorType_5_Int64` (1 declaration,
    #   0 definitions anywhere) — an erased `Self.InnerIteratorType` field
    #   argument inferred as a scalar placeholder for a container-bounded
    #   callee. The guard refuses (refusal -> fallback -> prototype-only)
    #   only when BOTH are measured: the argument is a `self`-field whose
    #   annotation names an unbound type parameter of the enclosing struct,
    #   AND the callee's own template treats that parameter as a container
    #   (`<param>.Element/.IteratorType/.IteratorOwnedType` access — the
    #   discriminator, added because the erased-field condition alone broke
    #   `StridedRange._unsigned_count`: its `ceildiv(self.end - self.start,
    #   self.step)` args are the same erased `Scalar[Self.dtype]` fields,
    #   but `ceildiv[T: CeilDivable](a: T, b: T) -> T` has no type-member
    #   access, so `ceildiv[Int64]` is a REAL monomorphization, defined by
    #   other TUs, and master's body linked). Result: all 4 std/iter calls
    #   gone from the generated C (the 4 methods are prototype-only); the
    #   removed-definition A/B check reports 0 undefined-and-referenced
    #   symbols.
    #   The invalid `..., int64_t` prototype regression the first cut hit
    #   (format/logger/test_list) is still fixed by normalizing the pre-
    #   pass's bare `...` packing sentinel to `MojoList *` when typed
    #   params follow (`_emit_struct_method_prototypes`), and the `*`
    #   star-param else branch to the same sentinel (it fires for the
    #   fallback's prototype-only entries, which no longer write per-
    #   overload `func_param_types`). Measured: all affected files gate
    #   rc=0; the CONCRETE `_CountIterator` methods (Int fields) still emit
    #   with their real start/step arithmetic.
    #   test/itertools/test_count.mojo — LADDER PASS 2/2 (checked values
    #   0,1 and 10,30; nm: module-own `_CountIterator___next__` + both
    #   `__iter__` overloads T in the module's own object; link rc=0; the
    #   only non-runtime undefined is the documented assert_equal stub).
    #   The lift: the zero-positional-arg / direct-struct-return factory
    #   subpath — `def count(start: Int = 0, step: Int = 1) ->
    #   _CountIterator:` returns a CONCRETE struct that IS the value.
    #   iter_factory.parse_return gained the bare-struct-name arm (kind
    #   'direct' — seeded only for calls with NO POSITIONAL args, which
    #   includes the measured kwarg form `count(start=10, step=2)`; on the
    #   positional-arg path `_factory_return_for`'s owned/borrowed pick
    #   can never select it, so it is inert there);
    #   elab_intu._seed_direct_factory gates it narrow (exactly ONE direct
    #   overload; wrapper declared `struct <name>(` in the home — a `[` is
    #   out of scope; wrapper FIELD order == factory PARAMETER order: count:
    #   start,step == start,step) and materializes it in-TU at its PLAIN name
    #   (no bracket block: `monomorphize_source`'s head match requires one —
    #   measured ValueError — so the template IS the concrete source and
    #   `mangle`'s zero-arg contract returns the name unchanged; the registry
    #   write bypasses `_register_named` deliberately, whose `[\[:]` regex
    #   matches generic/bare heads but not concrete-with-bases); the emit
    #   side (emit_calls._lower_factory_call, kind 'direct') constructs the
    #   wrapper from the factory's own parameters in order — call
    #   positionals/kwargs first, then the factory's own parameter DEFAULTS
    #   (0,1 — captured in the record as parsed literals), so `count()` and
    #   `count(start=10, step=20)` are distinct factory_call_key entries
    #   carrying exactly the values the factory body `return {start, step}`
    #   would build. `next(it)` then dispatches on the in-TU
    #   `_CountIterator.__next__` via the existing struct-protocol branch.
    #   A/B corollary (measured against the Part 1 tree, baffbcb4): the same
    #   subpath lifts test/iter/test_nth.mojo's kwarg-form call —
    #   `count(start=10, step=2).nth(5)` becomes in-TU `_CountIterator`
    #   construction + the (inherited-trait, weak-stub) `_CountIterator_nth`
    #   — where the Part 1 tree called `std_itertools___init___count_2dbb98`
    #   as a bare extern with 0 definitions anywhere (its home C was never
    #   generated, the `next()` refusal of this same family) — a link
    #   hazard the -fsyntax-only gate could not see.
    'test/collections/string/test_iterators.mojo': (
        "2026-10-21 measured: `test_bytes_iter_empty` — `var bytes = s.bytes()` "
        "on a local `StringSlice`: the iterator arrives from a METHOD call, "
        "and the dependent-return factory subpath (elab_intu._seed_factories) "
        "seeds FREE-function factory calls only — a method-call dependent "
        "return (`StringSlice.bytes() -> BytesIter[...]`) erases to a boxed "
        "`int64_t` on the .o route, so `next(bytes)` (measured receiver "
        "`int64_t`, hard refusal, in function `test_bytes_iter_empty`) has "
        "nothing to dispatch on. Seeding the method-call shape needs the "
        "dependent return resolved through the receiver's static type — the "
        "same machinery applied to a MemberExpr callee. See "
        "bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md"),
     # 2026-10-21 (further) — REMOVED from this dict: test/collections/
     # test_set.mojo no longer FAILS THE SWEEP — the Part 2 blocker
     # (enumerate(my_set) over the set LITERAL `{4, 5, 6}`: resolve_container
     # refused the set-literal container, `next(it)` hit the hard refusal in
     # `test_iter`) is closed, so C-gen completes (11086 lines, 35 tests)
     # and gcc -c passes. This is a FLOOR-GREEN, not a value-green — the
     # full-file ladder stays RED on five independent measured gaps, each
     # measured in the 20-31 test scratch (11 PASS / 9 FAIL), and the full
     # file does not LINK (check_write_to + conforms_to undefined):
     #   (A) check_write_to — cross-module test_utils import + Some[Writable]
     #       trait-protocol dispatch, unavailable to the single-module link
     #       (link fails on it, as on (C));
     #   (B) write_repr_to / write_to — protocol methods lower to the
     #       constant 0 (in-TU weak stub);
     #   (C) conforms_to — the comptime builtin is emitted DECLARATION-ONLY
     #       (no definition; undefined at link — needs static trait
     #       resolution of Set's conditional conformances, a feature);
     #   (D) the Set element methods _lower_set_method does not handle —
     #       .remove/.pop (no-op, and no raise on missing/empty),
     #       .insert/.deinit_with/.clear_with (closure-argument methods),
     #       iterator .bounds() — while .add/.discard/.copy/.clear/.update
     #       DO lower (ladder-verified in the 11-test scratch, PASS 11/11);
     #   (E) the empty {} literal convention is an empty DICT (mojo_dict_new)
     #       — `set == {}` takes the erased mojo_value_eq path (kind mismatch
     #       -> 0), and `set > {}` / `set < {}` hit the container-ordering
     #       refusal, which raises a TypeError the codegen then exits on
     #       (rc=1, kills the whole ladder run — those 2 tests are excluded
     #       from continue-mode maps);
     #   (F) cross-module hash(<set>) is not content-derived (measured:
     #       equal content, different words).
     # Ladder evidence: the reduced-file scratch (11 tests: construction/
     # move/copy/len/in/equal/bool/iter/add/comprehension/iter_owned) is
     # LADDER PASS 11/11 with real values, incl. test_iter's full
     # next()/tuple-subscript/`it.__next__()`-exhaustion flow — the
     # enumerate(set) path proven end to end. The set-constructor fix
     # (Set[T](x, y, ...) previously evaluated its args and DROPPED them —
     # silent empty set; bare Set(<MojoSet *>) now mojo_set_copy) is a
     # genuine improvement kept in the codegen. Full measurement record:
     # bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md,
     # "2026-10-21 (further)".
    'test/iter/test_map.mojo': (
        "2026-10-21 (further) measured — the Part 2 blocker (thin-FUNCTION "
        "value type argument) is CLOSED: map now seeds its positional "
        "`_MapIterator[function]` return — parse_return's positional arm "
        "(the bare identifier is the FUNCTION VALUE the call passes as its "
        "explicit type arg, gated so it must resolve to an actual def in "
        "scope — a bare type arg can never bind the function slot), the "
        "wrapper header's parameters classified by annotation (`Iterator` "
        "-> inner, `def(...)` -> function, other -> derived, where derived "
        "binds from the function value's OWN return annotation — `def "
        "add_one(x: Int) -> Int` supplies OutputType=Int, `def to_str` "
        "supplies String), and `map` joins the no-import builtin factory "
        "table (test_map calls it without an import line, like enumerate/"
        "iter). The reduced-file scratch ladder (2 tests: test_map + "
        "test_map_owned) is LADDER PASS 2/2 with real values — Int output "
        "(next(m) = 2, 3, 4), String output (next(m2) = \"1\", \"2\", "
        "\"3\"), exhaustion raising StopIteration via `m.__next__()` in "
        "both. The ONE remaining test (test_map_function_can_take_owned_"
        "value) is blocked by an independent cross-module gap: CopyCounter "
        "from test_utils (`CopyCounter[NoneType](None)` + `.copy_count`) — "
        "the single-module ladder link cannot supply test_utils (the same "
        "family as test_set's check_write_to); its container argument "
        "(`var list = [CopyCounter[NoneType](None)]`) is also refused by "
        "the seed's container gate (measured note: `map(...): container "
        "argument is not a statically resolvable local List / range / "
        "nested factory`). See "
        "bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md"),
    # 2026-10-22 (part 4) — REMOVED from this dict: all three now pass the
    # syntax gate (the pre-shape-fix part-4 sweep reported each as STALE;
    # the final sweep is 605 PASSED / 5 FAILED, 0 unexpected, 0 stale).
    # The lifts are part-4 seed mechanisms, not the typedef safety net
    # (their part-3 blockers were codegen `next()` hard refusals —
    # measured receivers `int64_t`/`void *`/`MojoList *` — not gcc errors);
    # the value ladders were re-run this session with parity to 2026-10-21:
    #   test/iter/test_chain.mojo — the part-4 variadic + out-parameter
    #     factory seed subpath (out-res seed: `*iterables: *Ts, out res:
    #     _ChainedIterator[*inners]`); ladder re-measured PASS 4/4.
    #   test/iter/test_zip.mojo — the same out-res subpath for
    #     `_ZipIterator[*inners]`; ladder re-measured 11/12 (test_zip_
    #     bounds FAIL-REAL parity — a real runtime value assert, not a
    #     gate regression).
    #   test/python/test_python_object.mojo — the part-4 pyobj-list seed
    #     arm (a `PythonObject.__iter__()` call as the loop's container
    #     argument; the box unboxed to the MojoList * it is, measured).
    #
    # 2026-10-21 — REMOVED from this dict, with the value ladder (real
    # gcc -c + nm + link + run with value-checking asserts, never the
    # syntax gate) rather than the syntax check:
    #   test/iter/test_peek.mojo         6/6 PASS (6 inner/wrapper symbols
    #                                     asserted defined in the module's
    #                                     own object)
    #   test/iter/test_enumerate.mojo    6/6 PASS (incl. test_enumerate_
    #                                     bounds — the bare `iter(list)`
    #                                     form; 9 symbols asserted)
    #   test/itertools/test_take.mojo    13/13 PASS
    #   test/itertools/test_drop.mojo    14/14 PASS (incl. the function-
    #                                     level `from std.itertools import
    #                                     take` composition test)
    #   test/itertools/test_take_while.mojo  14/14 PASS (the thin-FUNCTION
    #                                     `predicate` type argument: the
    #                                     seed binds the wrapper's function
    #                                     type parameter from the call's
    #                                     explicit type arg — kwarg form
    #                                     `predicate=predicate`; module-
    #                                     level AND nested non-capturing
    #                                     predicate defs both verified)
    #   test/itertools/test_drop_while.mojo  14/14 PASS (incl. the nested
    #                                     `is_zero` predicate)
    # The lift: elab_intu no longer refuses List-container factories —
    # the in-TU iterator protocol materializes in RUNTIME-MojoList terms
    # (mojo_list_len/mojo_list_get_* over a `MojoList *` `_list` field),
    # with the spliced wrapper bodies rewritten to lowerable expressions
    # (elab_intu._rewrite_inner_bodies). Verification + every measured
    # hole closed on the way (peek() static-view, unsafe_take consume,
    # bare-iter factory, assert_raises setjmp frame, setjmp raise-
    # exhaustion for-loops, wrapper bounds slot semantics, .copy()
    # protocol copies, comptime-assert no-op, function-level import
    # factory homes): bugs/CODEGEN_next_on_a_user_defined_iterator_
    # struct_is_unlowered.md, "2026-10-20 (further)".
    # The Part 3 lift (2026-10-21 (further)) for the two take_while/
    # drop_while files: the thin-FUNCTION type argument — iter_factory's
    # kwarg-form parse_return arm reads `Wrapper[kw=..., predicate=predicate]`,
    # elab_intu._seed_one_factory classifies the wrapper header's
    # parameters by annotation (Iterator -> inner, def -> function) and
    # binds the function parameter from the call's explicit type arg
    # (nested non-capturing defs to their lifted C name, closure_lifted_
    # name; capturing closures refused; module-level bare names via
    # _func_csym), and the spliced `Self.predicate(elem)` body
    # monomorphizes (the Self.<param> unit pass) to a direct call of the
    # lifted function. The same classification, extended with the
    # positional arm + the DERIVED parameter (bound from the function
    # value's own return annotation), is what lifted map's mechanism —
    # see test/iter/test_map's entry above for its one remaining blocker.
    'test/itertools/test_cycle.mojo': (
        "2026-10-21 (further) measured — 15 of 17 `cycle(...)` call sites "
        "compile, LINK and run with real values (Int/String/Bool lists, "
        "`List[Int]()`, `range(...)`, the copyable/iterator-protocol/for-"
        "loop/composition forms — ladder PASS 15/15 on a copy of the file "
        "without the 2 user-owned tests). The 2 remaining sites "
        "(`cycle(_owned3(1, 2, 3))` line 283 in test_cycle_owned, "
        "`cycle(_owned1(42))` line 302 in test_cycle_owned_single) are "
        "refused at the SEED's container gate (measured notes, x2: `cycle"
        "(...): container argument is not a statically resolvable local "
        "List / range / nested factory`): the container argument is a "
        "LOCAL FUNCTION CALL (`_owned3(1, 2, 3)`) whose bracketed return "
        "type requires local generic elaboration, and its value is a "
        "USER-DEFINED `IterableOwned` struct (`_CopyableOwned[3]` — module-"
        "local, comptime-parameterized, in-TU `_CopyableOwnedIter[3]` over "
        "`Array[Int, 3]`) — neither a List/Set local nor a nested factory, "
        "so no record can be filed. The boxed `it` local then hits next()'s "
        "hard refusal — `cannot compile module: next(...) on next(IdentExpr) "
        "(receiver typed int64_t) has no lowering` — not a stub. Landing "
        "needs the local-generic-elaboration gap (R2 sibling: a local fn's "
        "bracketed return boxes to int64_t) and the in-TU user-struct "
        "iterator (`next-on-a-user-defined-iterator-struct` family). See "
        "bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md"),
    'test/itertools/test_product.mojo': (
        "2026-10-22 (part 4) remeasured — the part-4 two-container factory "
        "seed lifts the NON-OWNED shapes: `test_product2` / `_param` / "
        "`_unequal` / `_copies` (products of two List locals) now lower — the "
        "module compiles through them. The refusal relocated to "
        "`test_product2_owned`: `product(_owned3(1, 2, 3), _owned2(10, 20))` — "
        "the container arguments are LOCAL FUNCTION CALLS returning owned "
        "values (the same R2 local-generic-elaboration + owned family as "
        "test_cycle's user-owned sites); the seed cannot file records for "
        "them, the boxed `it` stays `int64_t`, and `next(it)` hits the hard "
        "refusal (measured 2026-10-22: receiver `int64_t`, in function "
        "`test_product2_owned`). 2026-10-21 measured (history): `test_product2` "
        "— `product(l1, l2)`: the return type depends on TWO containers "
        "(`_Product2[IterableTypeA.IteratorType[origin_of(iterable_a)], "
        "IterableTypeB.IteratorType[origin_of(iterable_b)]]`) — the factory "
        "seed resolved a SINGLE container argument (args[0]) and modeled one "
        "inner iterator in the wrapper; a two-iterable dependent return was "
        "not representable in that record shape. See "
        "bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md"),
    # 2026-10-01 — added by the merge of the formal5 batch, and the class is the
    # `explicit-failed` half of the census, not the `next(...)` half above.
    # `std/os/path/path.mojo`'s `getsize` is a bracket template, and once the
    # elaborator started instantiating it its own translation unit was compiled
    # for the first time — and failed. The emitted body shows this is NOT a
    # missing prototype, which is what it looks like from the error:
    #
    #   _t2 = 0;  /* TODO: char*.__fspath__ */
    #   _t3 = stat (_t2);
    #   _t4 = (void *)_t3;
    #   _t5 = _mojo_dispatch_getattr (_t4, "st_size");
    #
    # Three defects in five lines. The argument is a stubbed NULL because
    # `path.__fspath__()` has no lowering. `stat` is unprototyped. And the
    # result is modelled as a struct POINTER with `.st_size` fetched by dynamic
    # getattr on it, where the real signature is `int stat(const char *,
    # struct stat *)` — an out-param that fills a caller-owned struct and
    # returns 0/-1, not a pointer at all. So a correct prototype would NOT fix
    # this: it would assign an int error code to a pointer temp and getattr on
    # that. Lowering `stat` means teaching its out-param shape, which is a
    # feature, not a declaration.
    #
    # A declaration is also not available: `#include <sys/stat.h>` in
    # fire_runtime.h breaks every TU, because std/os/_macos.mojo:137 reaches
    # the same symbol through `external_call["stat", Int32]` and emits its own
    # declaration — the identical `conflicting types` failure
    # runtime/fire_runtime.h:1581-1596 documents for `<time.h>`. A hand-written
    # prototype in that shared header has the same conflict.
    #
    # Declared rather than left as an UNEXPECTED red, because the codegen did
    # the correct thing here: it refused to emit a call it cannot lower instead
    # of emitting the above. That is the same situation as the 21 entries
    # above, which is why the summary line reads 22 expected / 0 unexpected.
    'test/os/path/test_getsize.mojo': (
        "`getsize`'s `stat(path.__fspath__()).st_size` has no lowering. "
        "UPDATE 2026-10-20: the first of the three defects is closed — "
        "`__fspath__()` on a String receiver is now lowered as the identity "
        "(stdlib's `String.__fspath__` returns self, and this codegen's "
        "String IS its char* buffer): the monomorphized TU's call is "
        "`stat(path)`, passing the real path, where it was `stat(0)` from "
        "the 0-stub (measured before/after in the generated C). TWO defects "
        "remain, both value-level, and the TU still fails gcc -c on the "
        "first: (1) bare `stat` — a CROSS-STDLIB call to the generic "
        "`stat[PathLike: stdPathLike]` (std/os/fstat.mojo) that the isolated "
        "monomorphized TU has no prototype for (`implicit declaration of "
        "function 'stat'`); it needs transitive elaboration of the callee "
        "with PathLike=String and a call rewrite to the mangled symbol + "
        "linked object; (2) the result is modelled as int64_t, reinterpreted "
        "as `void *`, with `.st_size` fetched by dynamic "
        "`_mojo_dispatch_getattr` — the real signature is "
        "`int stat(const char *, struct stat *)`, an out-param filling a "
        "caller-owned struct, so a prototype alone would not fix it. Not "
        "fixable by `#include <sys/stat.h>` either: every TU includes "
        "fire_runtime.h and std/os/_macos.mojo:137 declares `stat` itself "
        "via `external_call[\"stat\", Int32]`. Reachable only once the "
        "codegen models the out-param. See "
        "bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md"),
}

def get_stdlib_path():
    """Return the path to the stdlib root directory (parent of std/, test/, ...)."""
    return Path(STDLIB_PATH).resolve()

def find_mojo_files(base_path, roots=None, module=None):
    """
    Find all .mojo files in the stdlib subtrees named in `roots`.

    If `roots` is None the roots are DISCOVERED from the stdlib tree (see
    `discover_roots`) rather than taken from DEFAULT_ROOTS, so a subcomponent
    added later is compiled without editing this file.

    If `module` is specified, only search that module's subdirectory under std/.
    Paths are yielded relative to the stdlib root so display shows e.g.
    "benchmarks/...", "std/...", "test/...".
    Yields (relative_path, absolute_path) tuples.
    """
    base = Path(base_path)
    if not base.exists():
        print(f"Error: stdlib path not found: {base}", file=sys.stderr)
        return

    if module:
        module_path = base / "std" / module
        if not module_path.exists():
            print(f"Error: module path not found: {module_path}", file=sys.stderr)
            return
        for mojo_file in sorted(module_path.rglob("*.mojo")):
            yield (mojo_file.relative_to(base), mojo_file)
        return

    # `roots` given explicitly means the caller asked for exactly those (the
    # `--module` path above, and any direct caller); otherwise discover what
    # the stdlib actually has. See DEFAULT_ROOTS for why that is not the same
    # thing as the preference list.
    for root in (roots if roots is not None else discover_roots(base)):
        search_root = base / root
        if not search_root.exists():
            continue
        for mojo_file in sorted(search_root.rglob("*.mojo")):
            yield (mojo_file.relative_to(base), mojo_file)


def excluded_mojo_files(base: Path) -> list:
    """.mojo files under the stdlib root that this sweep deliberately does NOT
    attempt, as (relative_path, excluding_directory_name) pairs.

    This is the honest form of the coverage cross-check. An earlier version
    compared the attempted count against a raw `rglob('*.mojo')` total and
    warned on any shortfall, which fires spuriously the moment `ROOT_EXCLUDE`
    excludes a directory that actually has Mojo files in it — i.e. exactly
    when the exclusion is doing its job. What is worth surfacing is not "the
    numbers differ" but WHICH files are not being compiled and WHY, so a
    subcomponent that acquires real source cannot sit in `scripts` (or any
    other excluded name) quietly.

    Returns [] when nothing is excluded, which is the normal case.
    """
    try:
        entries = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return []
    out = []
    for entry in entries:
        name = entry.name
        if name in ROOT_EXCLUDE or name.startswith('.') or name.startswith('bazel-'):
            for f in sorted(entry.rglob('*.mojo')):
                out.append((f.relative_to(base), name))
    return out

def _gcc_syntax_cached(c_src: str) -> tuple:
    """CAS-cached gcc -fsyntax-only check.  Returns (returncode, stderr);
    (None, "timeout") on a gcc timeout, which is transient and never cached.

    The key folds in the toolchain fingerprint (gcc version, platform, flags)
    and the C source — so a gcc upgrade or runtime-header edit invalidates
    stale results, and a codegen change produces a new key automatically.
    The command is built from the same _GCC_FLAGS the key hashes, so the two
    cannot drift apart."""
    key = cas.gcc_syntax_key(_GCC, _GCC_FLAGS, c_src)
    if key in _gcc_syntax_cache:
        return _gcc_syntax_cache[key]
    p = cas.lookup(key, '.result')
    if p is not None:
        cas.stats['hits'] += 1
        with open(p) as f:
            rc_line, _, err = f.read().partition('\n')
        result = (int(rc_line), err)
        _gcc_syntax_cache[key] = result
        return result
    cas.stats['misses'] += 1

    with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as tf:
        tf.write(c_src)
        cpath = tf.name
    try:
        r = subprocess.run(
            [_GCC, *_GCC_FLAGS, '-x', 'c', cpath],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return (None, "timeout")
    finally:
        os.unlink(cpath)

    cas.publish(key, '.result', f"{r.returncode}\n{r.stderr}".encode('utf-8'))
    _gcc_syntax_cache[key] = (r.returncode, r.stderr)
    return (r.returncode, r.stderr)


def transpile_file(mojo_file):
    """Compile a .mojo file through cached codegen + cached GCC syntax check.

    Returns (success, msg, cg_was_hit, gcc_was_hit).
    cg_was_hit / gcc_was_hit are True/False indicating whether each stage was a CAS
    cache hit. Both True ⇒ the file was fully cached. Worker processes return these
    so the parent can aggregate cas.stats across processes (the same pattern as
    build_stdlib_dylib._compile_module_job).

    `auto_gpu` defaults OFF here, which is `--no-gpu`. This sweep is a
    syntax/coverage instrument, not a GPU target, and automatic offload costs
    it real work for output it cannot check: `gen_module`'s synthesis pass
    recognises parallel loop nests, appends a `@gpu` kernel for each and
    rewrites the host loop into a call to it, for every one of the 610 modules
    here. That is the "automaticalization" this step does not want. Explicitly
    `@gpu`-marked functions are unaffected — `--no-gpu` suppresses INFERENCE,
    not device codegen for a function that asked for it (module_gen.py's own
    note). `--gpu` on the command line turns it back on."""
    try:
        src = open(mojo_file).read()
        rel = os.path.relpath(mojo_file, STDLIB_PATH)
        name = os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')

        # Pre-check codegen CAS key so we can report hit-or-miss (the
        # pre-check stat call is ~1 ms; the actual function reads/writes
        # the same key, so the cost is negligible compared to codegen).
        codegen_key = cas.stdlib_compile_key(src, str(mojo_file), name)
        cg_was_hit = cas.lookup(codegen_key, '.ci') is not None

        # Stage 1: Python codegen (CAS-cached)
        try:
            c_src = compile_module_to_c_cached(src, str(mojo_file), name,
                                               linkable=False)
        except Exception as e:
            return False, f"codegen: {str(e)[:120]}", False, False

        if not c_src.strip():
            return True, None, cg_was_hit, True  # empty file, no gcc step needed

        # Stage 2: GCC syntax check (CAS-cached)
        # Pre-check so we can report hit-or-miss independently of the
        # in-process L1 state.
        gcc_key = cas.gcc_syntax_key(_GCC, _GCC_FLAGS, c_src)
        gcc_was_hit = cas.lookup(gcc_key, '.result') is not None

        rc, stderr = _gcc_syntax_cached(c_src)
        if rc is None:  # timeout
            return False, "timeout in gcc (>10s)", cg_was_hit, False

        if rc != 0:
            first_err = next((l for l in stderr.splitlines()
                              if ': error:' in l), stderr.splitlines()[0] if stderr else '')
            return False, f"gcc: {first_err[:120]}", cg_was_hit, gcc_was_hit

        return True, None, cg_was_hit, gcc_was_hit

    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}", False, False

def main():
    parser = argparse.ArgumentParser(description="Attempt to transpile Mojo stdlib")
    parser.add_argument('--module', default=None, help='Restrict to a specific module under std/ (e.g., time)')
    parser.add_argument('--roots', default=None,
                        help='Comma-separated subtrees to scan (default: %s)' % ','.join(DEFAULT_ROOTS))
    parser.add_argument('-j', '--jobs', type=int, default=os.cpu_count(),
                        help='Parallel workers (each file is independent: its own codegen '
                             'instance + gcc subprocess). Default: os.cpu_count(). Use -j1 '
                             'for sequential (deterministic ordering, easier to read failures '
                             'as they happen).')
    args = parser.parse_args()

    # `--roots` overrides discovery (an explicit ask for a subset); with no
    # flag, compile everything the stdlib root actually contains.
    roots = ([r.strip() for r in args.roots.split(',')] if args.roots
             else None)

    stdlib_root = get_stdlib_path()
    print(f"Stdlib path: {stdlib_root}")
    if not args.module:
        print(f"Scanning roots: {', '.join(roots if roots is not None else discover_roots(stdlib_root))}")

    if not stdlib_root.exists():
        print(f"ERROR: stdlib path does not exist", file=sys.stderr)
        print(f"Expected: {stdlib_root}", file=sys.stderr)
        sys.exit(1)

    # Find .mojo files
    mojo_files = list(find_mojo_files(stdlib_root, roots=roots, module=args.module))
    if not mojo_files:
        print(f"No .mojo files found")
        if args.module:
            print(f"  (checked module: {args.module})")
        sys.exit(0)

    print(f"Found {len(mojo_files)} .mojo files\n")

    # Coverage cross-check, in the only form that is accurate: report the
    # .mojo files this sweep is NOT attempting and which directory excluded
    # them. Silent under-reporting was the original hazard here (a hardcoded
    # root list meant a new subcomponent was never compiled while the run still
    # said PASSED); `discover_roots` fixes the cause, and this makes any
    # remaining exclusion a stated decision rather than a gap.
    if roots is None and not args.module:
        excluded = excluded_mojo_files(stdlib_root)
        if excluded:
            by_dir = {}
            for _rel, dirname in excluded:
                by_dir[dirname] = by_dir.get(dirname, 0) + 1
            print(f"NOTE: {len(excluded)} .mojo file(s) are NOT being attempted, "
                  f"excluded by ROOT_EXCLUDE: "
                  + ', '.join(f'{d}/ ({n} file(s))' for d, n in sorted(by_dir.items()))
                  + "\n      If any of that is real Mojo source, move the name "
                    "from ROOT_EXCLUDE to DEFAULT_ROOTS.\n")

    # Transpile each file. Each file is fully independent (own codegen
    # instance + its own gcc subprocess), so this parallelizes cleanly across
    # processes — no shared state between files.
    passed = []
    failed = []
    done = 0
    # CAS hit counts aggregated from the per-file results (see transpile_file's
    # docstring on why worker-process cas.stats don't propagate on their own).
    cg_hits = 0
    gcc_hits = 0

    def _results():
        """Yield (rel_path, transpile_file result) — parallel or serial."""
        if args.jobs > 1:
            with ProcessPoolExecutor(max_workers=args.jobs) as pool:
                futures = {pool.submit(transpile_file, abs_path): rel_path
                           for rel_path, abs_path in mojo_files}
                for fut in as_completed(futures):
                    yield futures[fut], fut.result()
        else:
            for rel_path, abs_path in mojo_files:
                yield rel_path, transpile_file(abs_path)

    for rel_path, (success, error, cg_hit, gcc_hit) in _results():
        cg_hits += cg_hit
        gcc_hits += gcc_hit
        done += 1
        if success:
            passed.append(rel_path)
        else:
            print(f"  {rel_path}...FAIL")
            failed.append((rel_path, error))
        if done % 50 == 0 or done == len(mojo_files):
            print(f"\r  Progress: {len(passed)} passed, {len(failed)} failed", end="", flush=True)

    # Sort for deterministic, reviewable output regardless of completion order
    passed.sort()
    failed.sort(key=lambda pe: pe[0])

    # Split failures into expected (documented, see EXPECTED_FAILURES above)
    # and unexpected — a file only counts as a real regression if it's
    # unexpected. A file listed in EXPECTED_FAILURES that unexpectedly
    # starts PASSING is also flagged (stale entry — remove it) rather than
    # silently ignored, so this list can't quietly drift from reality.
    expected_failed = [(rp, err) for rp, err in failed if str(rp) in EXPECTED_FAILURES]
    unexpected_failed = [(rp, err) for rp, err in failed if str(rp) not in EXPECTED_FAILURES]
    stale_expected = sorted((set(EXPECTED_FAILURES) - {str(rp) for rp, _ in failed})
                             & {str(rp) for rp in passed})
    # An entry whose FILE NO LONGER EXISTS is the same rot as one that now
    # passes, and it is worse: a passing entry is at least re-checked by every
    # run and reported the moment it goes green, whereas a vanished file is
    # never attempted, so its entry can never be observed doing anything —
    # it just sits in the dict forever and inflates the "N expected" count
    # with a red that no longer describes anything real. Two were sitting
    # there (`test/itertools/test_chain.mojo`, `test/itertools/test_peek.mojo`
    # — both renamed/moved under `test/iter/`) before this check existed, and
    # nothing in the summary said so.
    #
    # Only decidable on a FULL sweep: `--module`/`--roots` attempt a subset, so
    # under those every entry outside the subset would look absent. Same
    # condition as the ROOT_EXCLUDE coverage cross-check above.
    _gone_expected = []
    if roots is None and not args.module:
        _swept = {str(rel) for rel, _ in mojo_files}
        _gone_expected = sorted(set(EXPECTED_FAILURES) - _swept)

    # Print summary
    print("\n" + "="*70)
    print(f"PASSED: {len(passed)}")
    print(f"FAILED: {len(failed)} ({len(expected_failed)} expected, "
          f"{len(unexpected_failed)} unexpected)")
    if done:
        print(f"Codegen  CAS: {cg_hits}/{done} hits  ({100 * cg_hits // done}%)")
        print(f"GCC      CAS: {gcc_hits}/{done} hits  ({100 * gcc_hits // done}%)")
    print("="*70)

    if expected_failed:
        print("\nExpected (documented) failures:")
        for rel_path, error in expected_failed:
            # Wrapped, and deduped to one line per reason: all 21 entries
            # share one reason string, and printing it 21 times buries the
            # paths this section exists to show. The reason is still printed
            # in full — once — and the paths are the point.
            print(f"  {rel_path}")
        _seen_reasons = []
        for rel_path, _error in expected_failed:
            _r = EXPECTED_FAILURES[str(rel_path)]
            if _r not in _seen_reasons:
                _seen_reasons.append(_r)
        print(f"  ({len(expected_failed)} file(s), "
              f"{len(_seen_reasons)} distinct reason(s)):")
        for _r in _seen_reasons:
            print(f"    - {_r}")

    if unexpected_failed:
        print("\nUNEXPECTED failed files:")
        for rel_path, error in unexpected_failed:
            print(f"  {rel_path}")
            if error:
                print(f"    → {error}")

    if stale_expected:
        print("\nSTALE EXPECTED_FAILURES entries (now passing — remove from the dict):")
        for rel_path in stale_expected:
            print(f"  {rel_path}")

    if _gone_expected:
        print("\nGONE EXPECTED_FAILURES entries (the file is no longer in the "
              "sweep — the entry describes nothing):")
        for rel_path in _gone_expected:
            print(f"  {rel_path}")
        print("      Each was renamed or removed without its entry being "
              "updated. Fix the path, or drop the entry.")

    if passed and len(passed) <= 10:
        print(f"\nPassed files:")
        for rel_path in passed:
            print(f"  {rel_path}")

    sys.exit(0 if not unexpected_failed and not stale_expected
             and not _gone_expected else 1)

if __name__ == '__main__':
    main()
