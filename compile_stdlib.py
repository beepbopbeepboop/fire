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


_NEXT_ON_STRUCT = (
    "`next(<user-defined iterator struct>)` has no lowering, and the "
    "receiver's type is not inferred. `var it = peekable(list)` types `it` "
    "as `int64_t`, not `_PeekableIterator *`, because `peekable` is never "
    "ELABORATED: it is a generic, so `reflect.export_exclusions` "
    "deliberately keeps it out of `std.iter`'s export table (the elaborator "
    "is supposed to instantiate it on demand), and the on-demand path "
    "declines — the two `peekable` overloads differ only by a trait bound "
    "(`Some[Iterable]` vs `Some[IterableOwned]`), which "
    "`Elaborator.elaborate_overload_call` cannot match against a scalar "
    "parameter type, and the chosen overload's return type "
    "(`_PeekableIterator[type_of(iterable).IteratorOwnedType]`) is "
    "dependent on the argument. Until 2026-10-01 this file PASSED here "
    "while its C carried `extern int64_t peekable (...)` with no definition "
    "anywhere, plus a call to a `next` symbol nothing defines — this check "
    "is `gcc -fgimple -fsyntax-only`, which cannot see that, and nothing "
    "else links the `test/` tree. `next(<struct>)` DOES lower whenever the "
    "receiver's type IS resololvable, and `Self.<type-param>` substitution "
    "inside a monomorphized generic struct is fixed; see "
    "bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md")

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
    'std/collections/string/iterators.mojo': _NEXT_ON_STRUCT,
    'std/itertools/itertools.mojo': _NEXT_ON_STRUCT,
    'test/collections/string/test_iterators.mojo': _NEXT_ON_STRUCT,
    'test/collections/test_set.mojo': _NEXT_ON_STRUCT,
    'test/collections/test_span.mojo': _NEXT_ON_STRUCT,
    'test/iter/test_chain.mojo': _NEXT_ON_STRUCT,
    'test/iter/test_empty.mojo': _NEXT_ON_STRUCT,
    'test/iter/test_enumerate.mojo': _NEXT_ON_STRUCT,
    'test/iter/test_map.mojo': _NEXT_ON_STRUCT,
    'test/iter/test_once.mojo': _NEXT_ON_STRUCT,
    'test/iter/test_peek.mojo': _NEXT_ON_STRUCT,
    'test/iter/test_zip.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_count.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_cycle.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_drop.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_drop_while.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_product.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_repeat.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_take.mojo': _NEXT_ON_STRUCT,
    'test/itertools/test_take_while.mojo': _NEXT_ON_STRUCT,
    'test/python/test_python_object.mojo': _NEXT_ON_STRUCT,
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
            c_src = compile_module_to_c_cached(src, str(mojo_file), name)
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
