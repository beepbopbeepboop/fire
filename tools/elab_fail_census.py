#!/usr/bin/env python3
"""Why does the elaborator decline each imported generic call site?

Wraps `elaborate.Elaborator.elaborate_generic_call_inferred` /
`.elaborate_generic_call` and records, per attempt, which of the four known
declining reasons applied. Run over the files `tools/undef_import_census.py`
flags; the output is the ranked reason list, which is what decides which of
the four mechanisms is worth building first.

Reasons recorded:
  no-template        extract_fn_source returned None (name not a bracket template)
  no-type-params     the template has no bracket type parameters at all
  unbound            infer_type_args could not bind every param from the args
  bogus-binding      every param bound, but through c_to_mojo's SCALAR table, so
                     a non-scalar argument became 'Int' (the silent-wrong case)
  no-overload-match  an overloaded set whose parameters matched no argument
  too-few-targs      an EXPLICIT `f[A]()` call where the template has more type
                     parameters than the call supplied — the second parameter
                     having a DEFAULT (`size_of[type, target = current()]()`).
  instantiate-failed the type args WERE complete, the instantiation TU was
                     really built, and gcc rejected it.

Two measurement bugs were fixed here, and both of them had been making the
number mean something other than what it says:

**1. Real compile failures were never counted at all.**
`monomorphize.instantiate`'s gcc step is `subprocess.run(..., check=True)`,
which RAISES `CalledProcessError`; the exception propagates out of
`Elaborator.elaborate_generic_call` (it does not catch), past the wrapper that
was recording attempts, and is finally swallowed by the call site's blanket
`except Exception` → `info = None`. So `explicit-failed`, the reason this whole
plan was built around, never once described a failed instantiation: it counted
only the paths that RETURN None. `generic()` below therefore records the
exception and re-raises it (the caller still gets its None; the census just
also learns what happened), and `_run` captures the child's stderr so
`instantiate-failed` can print the actual diagnostic per name.

**2. `too-few-targs` was folded into `explicit-failed`.** They are unrelated:
one is a template head with a defaulted parameter, the other is a TU gcc
rejects. Conflated, `size_of` — the largest single name — read as "the numeric
library's codegen is broken" when it is "a default value in a `[...]` head was
treated as required".
"""
import os
import re
import subprocess as _subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import elaborate
from fire_compiler import Parser, py_tokenize

ATTEMPTS: list = []
# Same triple shape as ATTEMPTS, for the attempts that left via an exception
# rather than a `return None`.
_failed: list = []

_real_inferred = elaborate.Elaborator.elaborate_generic_call_inferred
_real_generic = elaborate.Elaborator.elaborate_generic_call
_real_overload = elaborate.Elaborator.elaborate_overload_call

# fn_name -> Counter(first gcc error line), captured across the whole run.
GCC_ERRORS = defaultdict(Counter)
_building_for = []   # stack of the generic currently being instantiated


def _record_gcc_error(err: str) -> None:
    if not _building_for:
        return
    lines = err.splitlines()
    GCC_ERRORS[_building_for[-1]][next(
        (l for l in lines if ': error:' in l),
        (lines or ['<no stderr>'])[0]).strip()] += 1


def _run(cmd, *a, **k):
    """subprocess.run, but capturing stderr ONLY while an instantiation is in
    flight (the only case whose diagnostics this tool reports). Everything else
    passes straight through, so the rest of the pipeline's console behaviour —
    and its speed — is untouched."""
    if not _building_for:
        return _subprocess.run(cmd, *a, **k)
    k.pop('capture_output', None)
    try:
        r = _subprocess.run(cmd, *a, capture_output=True, **k)
    except _subprocess.CalledProcessError as e:
        err = (e.stderr or b'').decode('utf-8', 'replace')
        _record_gcc_error(err)
        # Re-emit, so nothing that used to be visible stops being visible.
        sys.stderr.write(err)
        raise
    if r.returncode != 0:
        err = (r.stderr or b'').decode('utf-8', 'replace')
        _record_gcc_error(err)
        sys.stderr.write(err)
    return r


_subprocess.run = _run


def _why(fn_name, module_src, arg_ctypes, res):
    tmpl = elaborate.extract_fn_source(module_src, fn_name,
                                       arg_count=len(arg_ctypes))
    if tmpl is None:
        return 'no-template'
    params = elaborate.type_param_names(tmpl)
    if not params:
        return 'no-type-params'
    binding = {}
    fn = None
    for s in Parser(py_tokenize(tmpl)).parse_module():
        if s.__class__.__name__ == 'FunctionDef':
            fn = s
            break
    if fn is None:
        return 'no-template'
    # Deliberately the SAME unifier the elaborator uses, not a local
    # re-implementation of `ann in params`. When it was a re-implementation
    # the census reported `unbound` for shapes `_unify_param_ann` actually
    # binds (SIMD[dtype,width]), so the reason split disagreed with the code
    # it was measuring — which is the one thing a census must not do.
    for i, (_pn, ann) in enumerate(getattr(fn, 'params', []) or []):
        if i >= len(arg_ctypes):
            break
        for k, v in elaborate._unify_param_ann(ann, params, arg_ctypes[i]).items():
            binding.setdefault(k, v)
    missing = [p for p in params if p not in binding]
    if missing:
        return f"unbound({','.join(missing)})"
    non_scalar_args = [c for c in arg_ctypes
                       if c not in elaborate._C_TO_MOJO]
    if non_scalar_args:
        scalar = {v for v in binding.values()}
        return f"bogus-binding({','.join(sorted(scalar))})"
    return 'other'


def inferred(self, module_src, fn_name, arg_ctypes):
    res = _real_inferred(self, module_src, fn_name, arg_ctypes)
    if res is None:
        ATTEMPTS.append((fn_name, _why(fn_name, module_src, arg_ctypes, res),
                        tuple(arg_ctypes)))
    return res


def _why_generic(fn_name, module_src, type_args, arg_count):
    """Which of the FOUR distinct ways an explicit `f[A]()` call can be declined.

    Ordered as `elaborate_generic_call` itself orders them, so the label is the
    line that actually returned None rather than a guess from the outside."""
    tmpl = elaborate.extract_fn_source(
        module_src, fn_name,
        arg_count=arg_count if arg_count is not None else len(type_args or ()))
    if tmpl is None:
        return 'no-template'
    params = elaborate.type_param_names(tmpl)
    if not params:
        return 'no-type-params'
    if len(type_args or ()) < len(params):
        return f"too-few-targs({len(type_args or ())}/{len(params)})"
    return 'instantiate-failed'


def generic(self, module_src, fn_name, type_args, arg_count=None):
    _building_for.append(fn_name)
    try:
        res = _real_generic(self, module_src, fn_name, type_args,
                            arg_count=arg_count)
    except Exception as e:
        # `instantiate` compiles the monomorphized fragment as its OWN
        # translation unit and lets gcc's failure RAISE. That exception is the
        # real "instantiate-failed" signal, and it used to sail straight past
        # this recorder — see the module docstring. Record it, then re-raise:
        # the call site's own `except Exception` still gets to turn it into the
        # same `info = None` it always produced.
        _failed.append((fn_name, f'instantiate-failed:{type(e).__name__}',
                        tuple(type_args or ())))
        raise
    finally:
        _building_for.pop()
    if res is None:
        ATTEMPTS.append((fn_name,
                         _why_generic(fn_name, module_src, type_args, arg_count),
                         tuple(type_args or ())))
    return res


def overload(self, module_src, fn_name, arg_ctypes):
    res = _real_overload(self, module_src, fn_name, arg_ctypes)
    if res is None:
        ATTEMPTS.append((fn_name, 'no-overload-match', tuple(arg_ctypes)))
    return res


elaborate.Elaborator.elaborate_generic_call_inferred = inferred
elaborate.Elaborator.elaborate_generic_call = generic
elaborate.Elaborator.elaborate_overload_call = overload


def main():
    from module_loader import STDLIB_PATH
    import compile_stdlib as cs
    import build_stdlib_dylib as b
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "c", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'undef_import_census.py'))
    C = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)

    files = [str(p) for _, p in cs.find_mojo_files(STDLIB_PATH)]
    flagged = set()
    for f in files:
        r = C.check(f)
        if r:
            flagged.update(x[1] for x in r)
    # `sorted`, ALL of them, no cap. This was `list(flagged)[:40]` — taking an
    # arbitrary 40 of a SET, so both the subset AND (across processes, where
    # string hashing is per-process randomised) WHICH 40 changed from run to
    # run: two consecutive runs on an unchanged tree replayed 286 and 399
    # files and reported 653 and 1705 attempts. A census whose denominator
    # moves by 2.6x on an unchanged tree is not a measurement, so the cap is
    # gone — the names are a substring test per file (610 files x 157 short
    # needles), which is nothing next to the compile that follows, and the
    # instrument is now reproducible.
    needles = sorted(flagged)
    targets = [f for f in files
               if any(n in open(f).read() for n in needles)]
    print(f"replaying {len(targets)} files for {len(needles)} flagged names",
          file=sys.stderr)

    for f in targets:
        rel = os.path.relpath(f, STDLIB_PATH)
        nm = os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')
        try:
            b.compile_module_to_c(open(f).read(), f, nm)
        except Exception:
            pass
    print(f"\ndecline reasons over {len(ATTEMPTS) + len(_failed)} attempts:")
    allreasons = ATTEMPTS + _failed
    for reason, k in Counter(a[1].split('(')[0] for a in allreasons).most_common():
        print(f"  {k:5d}  {reason}")
    print("\nby name (top 40):")
    seen = {}
    for name, reason, _ in allreasons:
        seen.setdefault(name, Counter())[reason.split('(')[0]] += 1
    for name, rs in sorted(seen.items(), key=lambda kv: -sum(kv[1].values()))[:40]:
        print(f"  {sum(rs.values()):4d}  {name:34s} {dict(rs)}")
    if GCC_ERRORS:
        print("\ngcc errors per instantiated fragment (the `instantiate-failed` "
              "population):")
        for name, cnt in sorted(GCC_ERRORS.items(),
                                key=lambda kv: -sum(kv[1].values()))[:30]:
            print(f"  {name}")
            for err, k in cnt.most_common(6):
                print(f"    {k:4d}  {err[:180]}")
    # The exception TYPE is only half the story for a non-gcc failure; the
    # arguments that provoked it are the other half, and they are the only
    # handle on a RecursionError or a SyntaxError from deep inside a fragment
    # compile. Top distinct argument tuples per failing name.
    if _failed:
        print("\nnon-gcc instantiate failures, by arguments:")
        byname = defaultdict(Counter)
        for name, reason, targs in _failed:
            byname[name][(reason, tuple(targs))] += 1
        for name, cnt in sorted(byname.items(),
                                key=lambda kv: -sum(kv[1].values()))[:20]:
            print(f"  {name}")
            for (reason, targs), k in cnt.most_common(4):
                print(f"    {k:4d}  {reason}  targs={list(targs)}")


if __name__ == '__main__':
    main()
