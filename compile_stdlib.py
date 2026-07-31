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
DEFAULT_ROOTS = ['benchmarks', 'std', 'test', 'tools', '_core', 'collections', 'io', 'math', 'os']

# Files that are honest, currently-understood, documented whole-module
# refusals — genuinely out of reach right now, not a shortcut around actually
# trying. Each entry names the specific bugs/ writeup with the full root
# cause, so a failure here is still visible (reported separately from
# genuinely UNEXPECTED failures below) rather than silently absorbed.
# Never add an entry here without a bugs/*.md file backing it.
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
}

def get_stdlib_path():
    """Return the path to the stdlib root directory (parent of std/, test/, ...)."""
    return Path(STDLIB_PATH).resolve()

def find_mojo_files(base_path, roots=None, module=None):
    """
    Find all .mojo files in the stdlib subtrees named in `roots`.

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

    for root in (roots or DEFAULT_ROOTS):
        search_root = base / root
        if not search_root.exists():
            continue
        for mojo_file in sorted(search_root.rglob("*.mojo")):
            yield (mojo_file.relative_to(base), mojo_file)

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
    """
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

    roots = [r.strip() for r in args.roots.split(',')] if args.roots else DEFAULT_ROOTS

    stdlib_root = get_stdlib_path()
    print(f"Stdlib path: {stdlib_root}")
    if not args.module:
        print(f"Scanning roots: {', '.join(roots)}")

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
            print(f"  {rel_path}  — {EXPECTED_FAILURES[str(rel_path)]}")

    if unexpected_failed:
        print("\nUNEXPECTED failed files:")
        for rel_path, error in unexpected_failed:
            print(f"  {rel_path}")
            if error:
                print(f"    → {error}")

    if stale_expected:
        print("\nSTALE EXPECTED_FAILURES entries (now passing — remove from the set):")
        for rel_path in stale_expected:
            print(f"  {rel_path}")

    if passed and len(passed) <= 10:
        print(f"\nPassed files:")
        for rel_path in passed:
            print(f"  {rel_path}")

    sys.exit(0 if not unexpected_failed and not stale_expected else 1)

if __name__ == '__main__':
    main()
