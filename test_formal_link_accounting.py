#!/usr/bin/env python3
"""test_formal_link_accounting.py -- agent [4]'s coverage for the formal
import/link layer.

Four things are pinned here, and the first three are the ones that would
silently change verdicts if they broke:

1. **Relative import resolution.** `from .. import X` in a module used to
   resolve to the importer's OWN package, because `module_name.replace(".",
   os.sep)` turned `".."` into `"/"` and the candidate list degenerated to two
   filesystem-root paths. Recorded in `bugs/FORMAL_known_limits.md` 1.3.

2. **The host-module tier split is a partition of what it replaced.**
   `formal/imports.py`'s `HOST_MODULES` was one 77-name list; it is now
   `HOST_UNREACHABLE | HOST_MODELLED` over the SAME 77 names. The union is
   asserted equal, because a name that quietly migrated between tiers, or one
   that was added to one tier and forgotten in the other, changes a verdict in
   the coverage report with no diff anyone reads.

3. **The C-library provider is the real library, not a 19-name list.** And not
   the global namespace either: `CDLL(None)` answers questions about the
   *building* process, and measured on this machine it reports `sqlite3_open`
   as available because this python has libsqlite3 loaded. The audit that uses
   this must not inherit that.

4. **One bind audit, both paths.** It used to run on the dylib path only; the
   executable path -- `build --formal`, the one the suites drive -- had no
   check at all. They share one function now, and it is the failure case that
   matters: an image that binds a symbol nothing provides builds cleanly and
   then cannot be loaded.

No Lean, no proofs, no gate: this is a fast unit file, and it is meant to be.
The one build it performs is a two-line program, to prove the audit does not
fire on a sound image (an audit that fires on everything is an audit people
learn to ignore).
"""
import os
import sys
import tempfile

# This file lives IN the repository root, so HERE is already the root. An
# earlier version did `dirname(HERE)`, which resolved every path in the file
# one level up -- into a directory that is not a checkout -- and produced a
# dozen confident failures about code that was working.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = HERE
sys.path.insert(0, REPO)

import formal.build as B
import formal.imports as I

RESULTS = []


def check(ok, what, detail=''):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f': {detail}' if detail else ''), flush=True)
    return bool(ok)


# ── 1. relative imports ──────────────────────────────────────────────────────

def _tree():
    """A synthetic package tree: a.b.c, with a/b/__init__, a/sib, a/b/leaf."""
    d = tempfile.mkdtemp(prefix='relimp_')
    for rel in ('a', 'a/b', 'a/b/c', 'py_pkg', 'py_pkg/sub'):
        os.makedirs(os.path.join(d, rel), exist_ok=True)
    for rel in ('a/__init__.mojo', 'a/sib.mojo', 'a/b/__init__.mojo',
                'a/b/leaf.mojo', 'a/b/c/__init__.mojo', 'a/b/c/inner.mojo',
                'a/b/c/leaf.mojo',
                'py_pkg/__init__.py', 'py_pkg/sub/__init__.py',
                'py_pkg/mod.py'):
        open(os.path.join(d, rel), 'w').close()
    return d


def test_relative_imports():
    d = _tree()
    leaf = os.path.join(d, 'a/b/c/inner.mojo')
    r = lambda rel: os.path.relpath(
        I.resolve_module_path(rel, relative_to=leaf, project_root=leaf) or '-', d)
    try:
        # The bug: `..` is the package's PARENT. Before the fix this returned
        # a/b/c/__init__.mojo -- the importer's own package -- because the
        # candidate list degenerated to `//.mojo` and `//__init__.mojo`.
        check(r('..') == os.path.join('a', 'b', '__init__.mojo'),
              '".." from a/b/c/inner.mojo is a/b', r('..'))
        check(r('.') == os.path.join('a', 'b', 'c', '__init__.mojo'),
              '"." is the containing package', r('.'))
        check(r('...') == os.path.join('a', '__init__.mojo'),
              '"..." ascends two levels', r('...'))
        # The shapes that already worked, and must keep working: the leaf
        # fallback is what real stdlib `from .sibling import` statements rely
        # on, so this is a regression guard, not a new capability.
        # The sibling OF inner.mojo, which is a/b/c/leaf.mojo -- not a/b's.
        check(r('.leaf') == os.path.join('a', 'b', 'c', 'leaf.mojo'),
              '".leaf" is the sibling of the importing file', r('.leaf'))
        check(r('..leaf') == os.path.join('a', 'b', 'leaf.mojo'),
              '"..leaf" is the same file via the parent', r('..leaf'))
        check(r('...sib') == os.path.join('a', 'sib.mojo'),
              '"...sib" reaches a/sib.mojo', r('...sib'))
        check(r('..c.leaf') == os.path.join('a', 'b', 'c', 'leaf.mojo'),
              'a dotted tail is appended to the ascended dir', r('..c.leaf'))
        check(r('...') == os.path.join('a', '__init__.mojo'),
              '"..." still ascends exactly two levels', r('...'))
        # A genuine miss must be a MISS, not a wrong answer: a/b has no `b`
        # inside it, so `..b` has nothing to find.
        check(I.resolve_module_path('..b', relative_to=leaf,
                                    project_root=leaf) is None,
              '"..b" is a miss rather than the wrong file')
        # A `.py` package resolves through the same relative path.
        pyinit = os.path.join(d, 'py_pkg/sub/__init__.py')
        got = I.resolve_module_path('..mod', relative_to=pyinit,
                                    project_root=pyinit)
        check(got == os.path.join(d, 'py_pkg', 'mod.py'),
              'a relative .py sibling resolves too', str(got))
        # Ascending past the root must terminate, not spin.
        check(I.resolve_module_path('..........', relative_to=leaf,
                                    project_root=leaf) is None,
              'ascending past the root is a miss, not a hang')
        # And an absolute name must be entirely unaffected by any of this.
        check(I.resolve_module_path('gimple_codegen',
                                    relative_to=os.path.join(REPO, 'fire.py'),
                                    project_root=os.path.join(REPO, 'fire.py'))
              == os.path.join(REPO, 'gimple_codegen.py'),
              'an absolute sibling name is unchanged')
        # A host module with NO source still resolves to nothing, whatever the
        # relative-import machinery does — this is the property the pass-1-first
        # ordering exists to protect, and `os` used to be the example for it.
        # `math` is the example now, because `os` has source: a name with a file
        # beside the project resolves from ANY directory, since the repository
        # root is one of the search roots, and that is the behaviour worth
        # pinning in its place.
        check(I.resolve_module_path('math', relative_to=leaf,
                                    project_root=leaf) is None,
              'a host module still resolves to nothing (pass 2 unaffected)')
        check(I.resolve_module_path('os', relative_to=leaf,
                                    project_root=leaf)
              == os.path.join(REPO, 'os', '__init__.mojo'),
              'a module with real source resolves from an unrelated directory, '
              'because the repository root is a search root')
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


# ── 2. the host-module split ────────────────────────────────────────────────

# The list as it stood BEFORE the split, pinned here as the specification.
#
# It was read out of `git show HEAD:formal/imports.py` first, which is wrong in a
# way worth recording: HEAD moves. The moment the split was committed, HEAD *was*
# the split, the regex stopped matching, and the check failed while asserting
# something still true. An oracle has to be pinned, because its whole job is to
# be the thing that does not move. (A pinned list in a TEST is not the duplicate
# source of truth the conventions warn about — that is about production code
# keeping two lists; here the second list is the expected value, and a
# deliberate change to the host set is supposed to fail until someone updates
# the specification on purpose.)
PRE_SPLIT_HOST_MODULES = frozenset((
    "os", "sys", "ast", "json", "re", "argparse", "dataclasses", "typing",
    "collections", "itertools", "functools", "math", "random", "time",
    "pathlib", "subprocess", "shutil", "textwrap", "inspect", "abc", "enum",
    "io", "csv", "copy", "pickle", "struct", "threading", "socket", "glob",
    "hashlib", "base64", "urllib", "http", "unittest", "logging", "warnings",
    "importlib", "importlib.util", "importlib.machinery", "contextlib",
    "traceback", "gc", "atexit", "signal", "errno", "stat", "platform",
    "tempfile", "uuid", "zlib", "gzip", "codecs", "locale", "getpass",
    "webbrowser", "unittest.mock", "difflib", "fnmatch", "operator",
    "heapq", "bisect", "array", "numbers", "decimal", "fractions", "secrets",
    "select", "queue", "weakref", "types", "dis", "pprint", "reprlib",
    "asyncio", "ctypes", "concurrent", "concurrent.futures",
))


def _original_host_modules():
    return set(PRE_SPLIT_HOST_MODULES)


def Written_modules():
    """The host-set names that have been WRITTEN, and so have left the set.

    A name belongs here when `resolve_module_path` finds real source for it in
    this tree. That is the whole test: the host set exists to say "there is
    nothing here to compile", and a module with a file is not in that
    condition however much of CPython it covers. `os` is the first entry —
    87 files of the arm64 sweep stopped on it — and the entry is derived rather
    than typed, so writing the next module updates this by being written.
    """
    found = set()
    for name in sorted(PRE_SPLIT_HOST_MODULES):
        if name in I.HOST_MODULES:
            continue
        try:
            path = I.resolve_module_path(name, project_root=HERE)
        except Exception:
            path = None
        if path and os.path.isfile(path):
            found.add(name)
    return found


def test_host_tiers():
    check(I._host_tier_conflicts() == [],
          'no host module is in both tiers', str(I._host_tier_conflicts()))
    union = set(I.HOST_UNREACHABLE) | set(I.HOST_MODELLED)
    check(union == set(I.HOST_MODULES),
          'HOST_MODULES is exactly the union of the two tiers',
          f"sym-diff {sorted(union ^ set(I.HOST_MODULES))}")
    orig = _original_host_modules()
    if orig is not None:
        # The union was the ORIGINAL list plus nothing, because splitting it in
        # two was a classification change and not a behaviour change. It is now
        # the original list MINUS the modules that have been WRITTEN, which is
        # a behaviour change and a deliberate one: a name leaves this set when
        # there is real source for it, and stays while there is not. So the
        # check is a SUBSET relation plus an exact account of what left, rather
        # than equality — equality would make writing a module a test failure,
        # and a name that comes BACK would pass unnoticed.
        check(union <= orig,
              'nothing has been ADDED to the host set: a name enters it when a '
              'module is unreachable, never because one is hard to write',
              f'added {sorted(union - orig)}')
        check(Written_modules() <= (orig - union),
              'every name that left the host set is one with real source '
              'behind it',
              f'left without source {sorted((orig - union) - Written_modules())}')
        check(set(orig) - union == Written_modules(),
              'the account of what left the host set is exact',
              f'unaccounted {sorted((orig - union) ^ Written_modules())}')
    else:
        check(False, 'the pre-split HOST_MODULES list could be read from git',
              'git show HEAD:formal/imports.py did not yield it')
    # The claim the split exists to make true: these are reachable, so calling
    # them "not fixable" was false. `os` is no longer in the set at all — it is
    # WRITTEN (os/__init__.mojo, os/path/__init__.mojo, os/_syscalls.mojo, with
    # test_formal_os.py building and running all of it) — so it is checked as
    # the other kind of fact: not a host module, and a real file.
    check(not I._is_host_module('os') and I.host_module_tier('os') == '',
          'os is no longer a host module: it has source now')
    check(not I._is_host_module('os.path') and I.host_module_tier('os.path') == '',
          'the dotted form os.path is not a host module either')
    for name in ('os', 'os.path'):
        got = I.resolve_module_path(name, project_root=HERE)
        check(got is not None and os.path.isfile(got),
              f'{name} resolves to a real source file',
              f'resolved to {got!r}')
    for m in ('sys', 'math', 'struct', 'time', 'json', 're'):
        check(I.host_module_tier(m) == 'modelled',
              f'{m} is modelled (reachable in principle, not implemented)')
    for m in ('subprocess', 'ctypes', 'asyncio', 'threading', 'socket',
              'tempfile', 'shutil', 'concurrent.futures', 'zlib', 'traceback'):
        check(I.host_module_tier(m) == 'unreachable',
              f'{m} is unreachable (needs an object the target does not have)')
    for m in ('unittest.mock', 'importlib.util'):
        check(I.host_module_tier(m) != '',
              f'the dotted form {m} still classifies')
    check(I.host_module_tier('json') == I.host_module_tier('json.decoder'),
          'a dotted form follows its top-level component')
    for m in ('__future__', 'sys', 'nosuchmodule'):
        if m == 'sys':
            continue
        check(I.host_module_tier(m) == '',
              f'{m} is not a host module')
    check(I._is_inert_module('__future__') and '__future__' not in I.HOST_MODULES,
          '__future__ stays inert and out of both tiers')


# ── 3. the C-library provider ───────────────────────────────────────────────

def test_libsystem_provider():
    if B._libsystem_handle() is False:
        print('SKIP  the C library could not be opened on this host; the '
              'fallback path is exercised instead', flush=True)
        check(B._is_libsystem('printf'),
              'fallback still answers the names it always did')
        return
    # Genuinely in libSystem, and four of these are what `os` and `re` are in the
    # MODELLED tier FOR: the old 19-name list reported all four as unprovided.
    for s in ('printf', 'malloc', 'exit', 'strlen', 'stat', 'clock_gettime',
              'regcomp', 'arc4random_buf', 'CC_SHA256'):
        check(B._is_libsystem(s), f'libSystem provides {s}')
    # Genuinely NOT in libSystem. Each is a real library this target does not
    # link, and waving any of them through is the false pass.
    for s in ('SSL_new', 'deflate', 'sqlite3_open', 'mojo_list_len',
              'no_such_symbol_at_all'):
        check(not B._is_libsystem(s), f'libSystem does NOT provide {s}')
    check(B._is_libsystem('_printf'),
          'the Mach-O spelling (leading underscore) is handled')
    # Memoisation must not change an answer, including a False one.
    check(B._is_libsystem('sqlite3_open') is False,
          'a memoised negative answer is still correct')


# ── 4. one bind audit, both paths ───────────────────────────────────────────

def test_bind_audit():
    dylib_syms = {'helper': '_pkg_helper', 'Other': '_pkg_Other'}
    # Accounted for: by a linked dependency, in either spelling.
    check(B._audit_bound_symbols(['helper', 'Other'], dylib_syms, 'image') == [],
          'a name a dependency exports is accounted for')
    check(B._audit_bound_symbols(['_pkg_helper'], dylib_syms, 'image') == [],
          "a manifest's exported spelling is accounted for too")
    # Accounted for: by the C library.
    check(B._audit_bound_symbols(['printf', 'stat'], dylib_syms, 'image') == [],
          'a C library name is accounted for')
    # Accounted for by NOTHING -- the case the audit exists for.
    left = B._audit_bound_symbols(['helper', 'element_copy', 'rebind_var'],
                                  dylib_syms, 'image')
    check(left == ['element_copy', 'rebind_var'],
          'a name nothing provides is reported, sorted and by bare name',
          str(left))
    check(B._audit_bound_symbols([], dylib_syms, 'image') == [],
          'an image with no externs is trivially sound')
    check(B._audit_bound_symbols(None, None, 'image') == [],
          'no externs and no dylibs is sound')
    # The message names the symbol, the count, and how the provider was asked.
    rep = B._unaccounted_report('/x/prog.mojo', ['a', 'b'], 'image')
    for frag in ('prog.mojo', 'the image would bind 2 symbol(s)',
                 'nothing provides', 'a, b'):
        check(frag in rep, f'the report contains {frag!r}', rep)
    check('dlsym' in rep or 'FALLBACK' in rep,
          'the report says how the provider question was answered', rep)
    rep_lib = B._unaccounted_report('/x/mod.mojo', ['a'], 'library')
    check('the library would bind' in rep_lib,
          'the dylib path says "library", not "image"', rep_lib)
    # And the executable path really does call it: the dylib path always did,
    # the executable path did not, and that is the whole point of the change.
    src = inspect_src('_codegen_and_link')
    # Two CALLS: the ELF branch and the Mach-O branch. The definition is a
    # separate function, so it is not in this source at all -- which is the
    # point, there is one rule and two call sites rather than three rules.
    check(src.count('_audit_bound_symbols(') == 2,
          'the audit is called on both the ELF and the Mach-O branch',
          f'{src.count("_audit_bound_symbols(")} occurrences in _codegen_and_link')
    dylib_src = inspect_src('compile_formal_dylib')
    check('_audit_bound_symbols(' in dylib_src,
          'the dylib path calls the shared audit rather than its own copy')


def inspect_src(fn_name):
    import inspect
    return inspect.getsource(getattr(B, fn_name))


def test_audit_fires_on_a_real_build():
    """The audit must FIRE, not merely exist. An audit nobody has seen fire is
    not an audit -- and one that fires on everything is one people learn to
    ignore. Both halves, and the sound half is a real two-line build."""
    import subprocess
    d = tempfile.mkdtemp(prefix='linkacct_')
    try:
        sound = os.path.join(d, 'sound.mojo')
        open(sound, 'w').write('fn main():\n    var n = 21\n    n = n * 2\n'
                               '    print(n)\n')
        r = subprocess.run(
            [sys.executable, os.path.join(REPO, 'fire.py'), 'build', '--formal',
             '--no-prove', '--backend=arm64', '-o', os.path.join(d, 'sound'),
             sound],
            capture_output=True, text=True, timeout=600, cwd=REPO)
        check(r.returncode == 0, 'a sound program still builds',
              (r.stdout + r.stderr)[-300:])
        check('nothing provides' not in (r.stdout + r.stderr),
              'the audit is silent on a sound image')

        bad = os.path.join(d, 'bad.mojo')
        open(bad, 'w').write('def helper(x):\n    return x + 1\n\n'
                             'fn main():\n'
                             '    print(no_such_function_xyz(7))\n')
        r2 = subprocess.run(
            [sys.executable, os.path.join(REPO, 'fire.py'), 'build', '--formal',
             '--no-prove', '--backend=arm64', '-o', os.path.join(d, 'bad'), bad],
            capture_output=True, text=True, timeout=600, cwd=REPO)
        out = r2.stdout + r2.stderr
        check(r2.returncode != 0,
              'an image binding an unprovided symbol is REFUSED, not built', out)
        check('nothing provides' in out,
              'the refusal says the symbol is provided by nothing', out)
        check('no_such_function_xyz' in out,
              'the refusal names the symbol', out)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_sorry_note():
    """The census has to be READ to be worth computing.

    `formal/build.py` puts `proof_sorries` in the result dict and, before this,
    nothing read it: two references tree-wide, both the assignment. A proof with
    a thousand admitted sorries printed exactly what a clean one printed, and
    "the proof checked" read as though it meant "the proof is sound". Checked at
    unit level because `fire.py build --formal` cannot currently generate a proof
    for even a trivial program on this tree (a pre-existing failure in
    arm64_proof_gen.py's recursion handling, reproduced with these files
    stashed), so an end-to-end demonstration is not available today.
    """
    sys.path.insert(0, REPO)
    import fire
    check(fire._sorry_note({}) == "",
          'no proof_sorries key means nothing to say')
    check(fire._sorry_note({'proof_sorries': 0}) == "",
          'zero sorries prints nothing (a zero on every line is noise)')
    check(fire._sorry_note({'proof_sorries': None}) == "",
          'a None count prints nothing')
    note = fire._sorry_note({'proof_sorries': 13})
    check('13' in note, 'a non-zero count is reported', note)
    check('ADMITTED' in note and 'not a proof' in note,
          'the wording says the file typechecks but is not a proof', note)
    # And it is wired to both places that already print the sibling field.
    import inspect
    src = inspect.getsource(fire)
    # Three textual matches: the `def` line and the two call sites. Asserting
    # the call SITES by locating the lines that print the sibling field is less
    # ambiguous than counting a substring that also matches the definition.
    call_sites = [ln for ln in src.splitlines()
                  if '_sorry_note(result)' in ln
                  and not ln.lstrip().startswith('def ')]
    check(len(call_sites) == 2,
          'both places that print `Proof:` carry the note', str(call_sites))
    lines = src.splitlines()
    near_proof_path = [
        any('proof_path' in lines[j] for j in range(max(0, i - 3), i))
        for i, ln in enumerate(lines) if '_sorry_note(result)' in ln
        and not ln.lstrip().startswith('def ')]
    check(near_proof_path == [True, True],
          'both sites are the ones that print a proof path', str(near_proof_path))
    check(inspect.signature(fire._sorry_note).return_annotation is str,
          'the helper is annotated, so a caller can see it returns text')


def main():
    test_relative_imports()
    test_host_tiers()
    test_libsystem_provider()
    test_bind_audit()
    test_audit_fires_on_a_real_build()
    test_sorry_note()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(RESULTS)} checks")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
