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
   Less the names that have since been IMPLEMENTED -- `os` and `sys`, which
   now have Mojo source in this tree (see `written_modules`, which derives
   that subtraction from the filesystem instead of from a list typed here).
   Each of those IS a change in what the build accepts, and it is checked
   against the filesystem in both directions so it cannot rot either way.

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

5. **`formal/hostmods/` is a search root of the formal resolver and of nothing
   else.** The `os`/`sys`/`struct` module sources live there, and the
   repository root — which four other resolvers search — must not contain them.
   The measured failure for getting this wrong is in the gate, not in a test:
   `selfhost` and `bootstrap-stage2-cc` both failed on `os.sep` inside
   `module_loader.py` itself. See
   `test_hostmods_are_invisible_to_every_other_resolver`.

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
import formal.model as M

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
        # ordering exists to protect. `os` used to be the example for it, then
        # `math`, and each stopped being one the day its module was written:
        # **a name with a `.mojo` file beside the project resolves from ANY
        # directory**, because the repository root is one of the search roots,
        # and that is the behaviour worth pinning in its place. `decimal` is the
        # example now — in `HOST_MODELLED`, not written, and with no source
        # anywhere in the tree.
        check(I.resolve_module_path('decimal', relative_to=leaf,
                                    project_root=leaf) is None,
              'a host module still resolves to nothing (pass 2 unaffected)')
        check(I.resolve_module_path('os', relative_to=leaf,
                                    project_root=leaf)
              == os.path.join(REPO, 'formal', 'hostmods', 'os',
                              '__init__.mojo'),
              'a module with real source resolves from an unrelated directory, '
              'because the hostmods root is a search root for every file')
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
#
# Names have LEFT this set since it was pinned — `sys`, `os` and `struct` — and
# each left by being IMPLEMENTED rather than by being reclassified. The set's
# meaning is "CPython standard library with no Mojo source for this backend", so
# a name that now HAS Mojo source does not belong in it however reachable the
# capability is. That subtraction is not written here as a list of the names
# that have left: it is DERIVED from the filesystem by `written_modules()` below,
# so the next module to be written updates this check by being written, and no
# hand-kept list can drift away from the tree.
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


def provided_modules():
    """The host-set names this tree provides by a COMPILE-TIME transform.

    The second way a name can leave the host set, and the reason this function
    exists is that the first one stopped being the only one. The host set says
    "there is nothing here to compile"; a name leaves it when this tree can
    answer for the module, and there are now two answers:

      * real SOURCE — `formal/hostmods/<name>.mojo`, compiled into a dylib the
        image links. That is `written_modules()` below, and it is derived from
        the FILESYSTEM so that writing the next module updates the account by
        being written.
      * a FRONT-END TRANSFORM — `formal/imports.py`'s
        `FRONTEND_PROVIDED_MODULES`, a shape over the source language that the
        front end consumes while the statement list is still AST, so there is
        no symbol for a dylib to export. `dataclasses` is the first: a
        decorator transform, and a decorator applied to a class is dropped by
        both backends before the front end looks at it, so a Mojo module would
        export a symbol nothing calls. `formal/dataclass_transform.py` has the
        measurement.

    This reads PRODUCTION CODE rather than the filesystem, which is the one
    asymmetry, and it is the right way round: the thing being derived is "which
    names does the front end implement", and the front end's own set is the
    authority on that — a hand-typed copy here would be a second list that can
    disagree with the one that decides behaviour, which is the failure this
    whole file exists to prevent. What keeps the derivation honest is the check
    beside it: every name this function returns must appear in
    `IMPLEMENTED_HOST_MODULE_TESTS`, which names a test file, and that file
    must exist. A name added to `FRONTEND_PROVIDED_MODULES` with no test behind
    it fails here.
    """
    return set(I.FRONTEND_PROVIDED_MODULES) & set(PRE_SPLIT_HOST_MODULES)


def _hostmod_names_on_disk():
    """Every module name `formal/hostmods/` has a source for.

    The third pool for `written_modules()`, and the only one that is not a
    hand-kept list: it walks the directory, so a module lands in it by being
    written. `os/_syscalls.mojo` becomes `os._syscalls` and
    `os/path/__init__.mojo` becomes `os.path`, which are the names
    `resolve_module_path` is asked for.

    This exists because of a real miss, not a hypothetical one: `posixpath` was
    classified into `HOST_MODELLED` on 2026-10-03 and then written, which took
    it out of every tier, and a pool built only from tiers could not see it \u2014
    so `test_host_tiers` reported `sym-diff ['posixpath']` for a module that was
    sitting on disk with a test beside it.
    """
    root = os.path.join(HERE, "formal", "hostmods")
    out = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        rel = os.path.relpath(dirpath, root)
        for fn in filenames:
            if not fn.endswith(".mojo"):
                continue
            if rel == ".":
                out.add(fn[:-len(".mojo")])
                continue
            name = os.path.join(rel, fn[:-len(".mojo")])
            name = name.replace(os.sep, ".")
            if name.endswith(".__init__"):
                name = name[:-len(".__init__")]
            out.add(name)
    return out


def written_modules():
    """Every host-set name this tree can now ANSWER for, whatever became of it.

    A name belongs here when this tree can answer for the module — either real
    source that `resolve_module_path` finds, or a front-end transform
    (`provided_modules()` above). That is the whole test: the host set exists to
    say "there is nothing here to compile", and a name something here can answer
    for is not in that condition however much of CPython it covers. `os` was the
    first entry — 87 files of the arm64 sweep stopped on it — and the entry is
    DERIVED rather than typed, so writing the next module updates this by being
    written, and no list in this file can drift away from what is on disk or in
    the tree.

    TWO KINDS NOW, and that is why this walks two pools.  A provided module either
    LEFT the host set (tier `''`: `os`, `sys`, `struct`, `re`, …) or stayed in it
    under `HOST_ADMITTED` (a module this tree answers for, whose host-dependent
    operations are declared contracts).  Both are "provided"; only the first left,
    and `ADMITTED_HOST_MODULE_TESTS` below exists because the second kind makes a
    different claim and is kept honest by a different test.

    **EVERY TIER IS WALKED, not just `HOST_ADMITTED`.** This pool used to be
    `PRE_SPLIT_HOST_MODULES | HOST_ADMITTED`, on the reasoning that a module can
    be in neither and only the union finds it. That missed a THIRD kind, and
    `posixpath` is the instance that found it:

      * a name in `PRE_SPLIT_HOST_MODULES` \u2014 the historical `HOST_MODULES`
        list, frozen in this file;
      * a name in `HOST_ADMITTED` \u2014 a module that answers under a contract;
      * **a name that was CLASSIFIED INTO a tier and then WRITTEN.** The
        2026-10-03 ranking put `posixpath` in `HOST_MODELLED` (it was in no tier
        at all), which is what a module with no source is; writing
        `formal/hostmods/posixpath.mojo` then took it OUT of that tier, and a
        name that has left every tier is in neither the pre-split list nor
        `HOST_ADMITTED` \u2014 so the derivation did not find it and the account
        reported `sym-diff ['posixpath']` for a module sitting on disk.

    That is the failure the account exists to catch, happening to the account.
    **So the pool also carries the hostmod DIRECTORY**, which is where the third
    kind lives: a name that has left every tier is in no tier at all, so no union
    of tiers finds it, and only the files themselves do. Every name that is in
    no tier and is NOT in `PRE_SPLIT_HOST_MODULES` is exactly the set that walk
    adds \u2014 which on this tree is `posixpath` and nothing else, and that is the
    point: the walk is a derivation, so it finds the next such module by being
    written rather than by being listed.
    """
    found = set()
    pool = (set(PRE_SPLIT_HOST_MODULES)
            | set(getattr(I, "HOST_ADMITTED", ()))
            | set(getattr(I, "HOST_MODELLED", ()))
            | set(getattr(I, "HOST_UNREACHABLE", ()))
            | _hostmod_names_on_disk())
    for name in sorted(pool):
        if I.is_frontend_provided(name):
            found.add(name)
            continue
        if name in I.HOST_MODULES and I.host_module_tier(name) != 'admitted':
            continue
        try:
            path = I.resolve_module_path(name, project_root=HERE)
        except Exception:
            path = None
        if path and os.path.isfile(path):
            found.add(name)
    return found


# …and the test that keeps each provided module honest. This carries no
# arithmetic — `written_modules()` above is derived from the filesystem and from
# the front end's own set, and is the only thing the host-set account reads —
# it says WHICH test a removal leans on, so that a module cannot leave the host
# set on the strength of a file or a transform nobody ever runs. Both halves are
# checked: the keys must be exactly the derived set, so a removal without an
# entry here fails, and an entry without a module behind it fails too.
IMPLEMENTED_HOST_MODULE_TESTS = {
    "argparse": "test_formal_argparse.py",
    "ast": "test_ast_formal.py",
    "os": "test_formal_os.py",
    "struct": "test_struct_formal.py",
    "sys": "test_formal_sys.py",
    "time": "test_formal_time.py",
    "hashlib": "test_formal_hashlib.py",
    "re": "test_re_formal.py",
    "dataclasses": "test_dataclasses_formal.py",
    "json": "test_formal_json.py",
    "pathlib": "test_formal_pathlib.py",
    "io": "test_formal_small_hosts.py",
    "typing": "test_formal_small_hosts.py",
    "platform": "test_formal_platform.py",
    "fnmatch": "test_formal_fnmatch.py",
    "enum": "test_formal_core_hostmods.py",
    "contextlib": "test_formal_core_hostmods.py",
    # The four this sweep claim wrote, one of them a REVERSAL of a
    # permanent-fact claim rather than the usual addition: `stat` and `math`
    # left HOST_MODELLED by being written, and `shutil` left HOST_UNREACHABLE,
    # which is a row saying "this needs a filesystem this target does not have"
    # withdrawn by the module that uses one.
    "stat": "test_formal_stat.py",
    "math": "test_formal_math.py",
    "shutil": "test_formal_shutil.py",
    # `tempfile` answered `gettempdir`/`mkdtemp`/`TMP_MAX` without ever needing an
    # object the target lacks (a real directory at mode 448 is a `mkdir(2)`), so it
    # left HOST_UNREACHABLE the way `shutil` did and for the same half of the
    # reason: the object half was false.  It was MISSING from this table for a day,
    # which is what made the `== written_modules()` check below red with
    # `sym-diff ['tempfile']` before `textwrap` was added beside it: the check
    # exists to catch a module written and forgotten, and
    # `formal/hostmods/tempfile.mojo` has been written since 2026-10-03.  What is
    # still true is the other half of its reason — `TemporaryDirectory` needs an
    # `__exit__`, and a FILE OBJECT is more than one 64-bit word.
    "tempfile": "test_formal_tempfile.py",
    # `textwrap` left `HOST_MODELLED` the way `stat` and `math` did, and for the
    # same reason: `dedent` and `indent` are pure string computation over the
    # `str_len`/`str_put`/`str_prefix` that `formal/hostmods/os/_syscalls.mojo`
    # already had, so nothing about them was out of reach and the tier entry said
    # "the work has not been done".  What is still true, and is at the top of the
    # module, is that `wrap`, `fill` and `shorten` are absent — a rendering WIDTH is
    # the subject and no file in this repository asks for one.
    "textwrap": "test_formal_textwrap.py",
}

# A module this tree now provides that was NEVER in the host set, so it cannot
# be part of the account above — that account is a difference between two SETS
# and `fcntl` is in neither.
#
# `fcntl` is the case: the sweep classified `import fcntl` as
# `not-answerable/host-import` because no `fcntl.mojo` existed for the resolver
# to find, and `_is_host_module` returns False for it either way, so the
# refusal a caller got was the resolver's "not a stdlib or sibling module, and
# no such file exists" — the same message any unresolvable import gets. Nothing
# left a set, so putting `fcntl` in `IMPLEMENTED_HOST_MODULE_TESTS` would make
# the `==` above fail with a name that legitimately did not move, and LEAVING it
# out entirely would stop the two assertions below from running on a module that
# needs them. Hence its own table.
PROVIDED_NEVER_A_HOST_MODULE = {
    "fcntl": "test_formal_fcntl.py",
    # `posixpath` \u2014 a SPELLING of `os.path`, which is the same situation as
    # `fcntl` and for the same reason it needed its own table: the 2026-10-03
    # ranking put it in `HOST_MODELLED` and writing the module took it out of every
    # tier, so it never LEFT a set this file can subtract from. Its test
    # (`test_formal_posixpath.py`) checks it against CPython's own `posixpath`
    # AND against `os.path` in the same image, which is the only way to tell a
    # faithful forward from a broken one.
    "posixpath": "test_formal_posixpath.py",
    # `html` left `HOST_MODELLED` the same way — the 2026-10-03 ranking
    # classified it and writing the module took it out of every tier, so it never
    # LEFT a set this file can subtract from either. Its test checks `escape`
    # against CPython's own `html.escape` over a corpus whose four `&`-bearing
    # cases exist to pin the ORDER, plus every byte 1..255.
    "html": "test_formal_html.py",
    # `glob` left `HOST_MODELLED` the same way and for the same reason: it is
    # reachable with nothing missing from the target -- a directory listing is
    # `readdir(3)` and a `malloc`, both of which `os.listdir` and `os.walk`
    # already had -- so the tier entry said "the work has not been done". Its
    # test is `test_formal_glob.py`, which checks whole ordered answers against
    # CPython's own `glob` over a fixture tree with a dotfile, a hidden
    # directory, a symbolic link and a DANGLING one, on both backends, and which
    # is where the 50-file row in the host-import ranking is now accounted for.
    "glob": "test_formal_glob.py",
    # `shlex` left `HOST_MODELLED` the same way and for the same reason: a state
    # machine over a string whose `quote` half is a scan over bytes a value
    # already is, so nothing was missing from the target and the tier entry said
    # "the work has not been done".  Its test is `test_formal_shlex.py`, which
    # checks `quote` against CPython's own over a 61-case corpus and every byte
    # 1..255 alone and after a safe byte, on both backends, and which re-splits
    # every answer with CPython's own `shlex.split` to say the quoting is one
    # shell word -- the only property `tools/suite.py`'s three call sites need of
    # it, since they build a command line out of the answer.  What the module
    # does NOT have (`split`, `join`, the `shlex` reader) is refused there by
    # name, which is what keeps a one-file row from reading as a whole module.
    "shlex": "test_formal_shlex.py",
    # `traceback` and `signal` left `HOST_UNREACHABLE` on 2026-10-04 the way
    # `shutil` and `tempfile` did, and for the same half of the reason: the
    # OBJECT half of their entries is still true — there is no unwinder for
    # `traceback` to format and no disposition table for `signal` to change —
    # and the part a program READS is computed. `traceback` answers CPython's own
    # text for the one state this target can be in, and `signal` answers this
    # platform's `<signal.h>` numbers plus two libc calls. Both are zero-admission
    # for the `fcntl` reason, so they sit in NO tier rather than in
    # `HOST_ADMITTED`, and one test file checks both because they are the same
    # shape (a handful of names whose answers are CPython's to give).
    "traceback": "test_formal_core_hostmods.py",
    "signal": "test_formal_core_hostmods.py",
    # `operator` left `HOST_MODELLED` on 2026-10-04 by being written — the
    # `posixpath`/`html`/`glob` shape, a name that had been classified and then
    # answered. It is the word-arithmetic half of CPython's `operator` and its
    # test is in the same file as `traceback` and `signal` for the reason that
    # file's docstring gives: a handful of names whose answers are CPython's to
    # give.
    "operator": "test_formal_core_hostmods.py",
}

# The two `os` SUBMODULES, which are provided and are named by the file they are
# written in rather than by a test of their own.
#
# `os._syscalls` and `os.path` are not host modules in CPython's sense at all
# \u2014 they are parts of `os`, and CPython spells them `os.path` (a real name) and
# nothing else. Each is checked by `test_formal_os.py` and `test_formal_os_backing.py`,
# which are the tests that OWN `os`, so this file cannot name them in
# `IMPLEMENTED_HOST_MODULE_TESTS` without claiming that `os` left the host set
# twice. They are listed here because `_hostmod_names_on_disk` finds them and
# `written_modules()` must account for every name it finds.
SUBMODULE_HOST_MODULE_TESTS = {
    "os.path": "test_formal_os.py",
    "os._syscalls": "test_formal_os.py",
}

# …and the ADMITTED ones, which left the host set by being written under a
# DECLARED CONTRACT rather than by being computed.  Separate from the table above
# because the claim they make is different: a name there says "this tree answers
# this module, and the answer to its host-dependent operations is a named `sorry`
# in every proof that uses it" — which is a test about the TRUST, not about the
# module's own arithmetic, so one file (`test_formal_admitted.py`) keeps all of
# them honest and it carries the ratchet.
ADMITTED_HOST_MODULE_TESTS = {
    "subprocess": "test_formal_admitted.py",
    "ctypes": "test_formal_admitted.py",
    "concurrent": "test_formal_admitted.py",
    "concurrent.futures": "test_formal_admitted.py",
    "threading": "test_formal_admitted.py",
}


# Names ADDED to the host set after the split, and the tier each one landed in.
#
# This table replaced `HOST_SET_ADDED_WITH_SOURCE`, which was an allow-list of
# additions that had to be accompanied by a `formal/hostmods/<name>.mojo`, and
# which `shlex` failed on 2026-10-03 (see
# `FORMAL_link_accounting_shlex_entered_the_host_set_with_no_source`,
# filed and then fixed here).  It was the wrong SHAPE as well as the wrong
# rule: an allow-list is satisfiable by adding a source-less name to it, so the
# check could only ever fail on a name somebody had not thought about.  What it
# needed was the rule, and the rule is in `formal/imports.py` at the head of
# the three tiers:
#
#     A NAME ENTERS THE HOST SET BECAUSE IT IS A CPYTHON STANDARD-LIBRARY MODULE
#     WITH NO MOJO SOURCE HERE.  WHICH TIER IT LANDS IN SAYS ONLY WHAT THIS TREE
#     CAN DO ABOUT IT: `unreachable` says the object is missing from the target,
#     `modelled` says nothing is missing and the work has not been done, and
#     `admitted` -- the only one whose membership rule is "has a source" -- says
#     this tree ANSWERS.
#
# So a standard-library name with no source is in one of the two CLAIM tiers and
# needs no source to justify being there, and that is the whole answer the
# document asked for.  `fcntl` was the first name to answer the other way (a real
# `formal/hostmods/fcntl.mojo`, so it LEFT the set instead);
# `builtins` and `sysconfig` are the first two instances of the `unreachable`
# answer, `shlex` / `html` / `datetime` / `resource` the first of the `modelled`
# one.  What a table cannot derive, and therefore still carries, is
# the FACT each permanent claim rests on -- an entry here is a sentence about the
# target, so it is written down; the tier assignment is asserted exactly, in both
# directions, so an addition that nobody justified fails and a stale row fails.
#
# There was a THIRD shape once and there is deliberately no table for it any more:
# a name added to a tier after the split and since WRITTEN, of which `posixpath`
# was the first (the 2026-10-03 classification put it in `HOST_MODELLED` with the
# reason written out -- `os/path/__init__.mojo` IS CPython's `posixpath`, so only
# the SPELLING was missing -- and `formal/hostmods/posixpath.mojo` answered every
# public name a day later).  Such a name is in neither `PRE_SPLIT_HOST_MODULES` nor
# any tier, so `test_host_tiers` cannot see it MOVE, and the one-row table that used
# to exist for that (`HOST_SET_ADDED_THEN_WRITTEN`, widened `ever` by hand) is
# retired: `_hostmod_names_on_disk()` finds the shape by WALKING
# `formal/hostmods/`, and `PROVIDED_NEVER_A_HOST_MODULE` names the test for each
# one found.  The hand-kept row had already gone stale once, which is the whole
# argument: `tempfile` sat in `HOST_UNREACHABLE` with a `mkdir` and an `mkdtemp`
# behind it, and missing from `IMPLEMENTED_HOST_MODULE_TESTS`, until the
# `== written_modules()` check below reported `sym-diff ['tempfile']`.
#
# `html` is the second instance of that third shape -- the 2026-10-03 ranking put
# it in `HOST_MODELLED` as "five character replacements over a string", and
# `formal/hostmods/html.mojo` (one function, `escape`) answered it the same way
# `posixpath` did -- so it is NOT a row of the table below, and its absence from
# it is the check working rather than the check being incomplete.
#
# `textwrap` is the first instance of the ORDINARY shape: classified into
# `HOST_MODELLED` on the same day, and written the same week, so it also left.  It
# differs only in that `IMPLEMENTED_HOST_MODULE_TESTS` already had a row for it,
# which is why its departure was caught by that table's own staleness rather than
# by this one.
#
# `glob` is the largest of that ordinary shape -- 50 files blocked in the
# 2026-10-03 sweep's host-import ranking and 15 of them naming it -- and it is
# named here for the same reason `textwrap` is not: it was in `PRE_SPLIT_HOST_MODULES`
# and in a tier, so writing `formal/hostmods/glob.mojo` took it out of both and
# `IMPLEMENTED_HOST_MODULE_TESTS` is where its test belongs.
HOST_SET_ADDED_TIERS = {
    # `set(dir(builtins))` asks the interpreter to enumerate ITSELF.  A formal
    # image is a Mach-O binary with an embedded CPython to compile it and none to
    # run in, so the object is missing and permanently so.
    "builtins": "unreachable",
    # Where an EMBEDDED CPython would be installed -- the same missing object,
    # named from the other side.  `fire.py` imports `sysconfig` and never uses
    # it, so nothing this tree can write would move a file.
    "sysconfig": "unreachable",
    # A clock `formal/hostmods/time.mojo` already reads, plus calendar
    # arithmetic.  The answer is a shaped record, which is
    # `bugs/FORMAL_time_struct_shaped_answers.md`'s to design.
    "datetime": "modelled",
    # `getrusage(2)` is libSystem and `struct rusage` is a fixed layout.
    "resource": "modelled",
}


def test_host_tiers():
    check(I._host_tier_conflicts() == [],
          'no host module is in both tiers', str(I._host_tier_conflicts()))
    # THREE tiers, and the third one is not a bookkeeping convenience.  A name
    # with a Mojo source used to have exactly two fates: it LEFT the host set
    # entirely (tier ''), or it was 'modelled'.  2026-10-02 added the third:
    # `subprocess`, `ctypes`, `concurrent`, `concurrent.futures` and
    # `threading` have a source AND cannot be computed here, so they answer under
    # DECLARED CONTRACTS and sit in `HOST_ADMITTED` — still host modules (the
    # predicate `HOST_MODULES` backs must cover them), but neither 'modelled'
    # (nothing left to write) nor 'unreachable' (they build).
    union = (set(I.HOST_UNREACHABLE) | set(I.HOST_MODELLED)
             | set(I.HOST_ADMITTED))
    check(union == set(I.HOST_MODULES),
          'HOST_MODULES is exactly the union of the three tiers',
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
        # A name enters the host set when it is a CPython standard-library
        # module this backend has no source for, never because one is hard to
        # write.  The rule is SUBSET-with-a-named-exception rather than subset,
        # because `fcntl` is a deliberate addition and the reason is worth
        # stating: `fcntl` was in NEITHER tier before 2026-10-02, so
        # `tools/formal_sweep.py` was classifying every file importing it as
        # `not-answerable/unresolved-import` -- "not a stdlib or sibling module",
        # which is FALSE, since `fcntl` is both a CPython stdlib module and the
        # thing three files in this tree import.  Adding it with its model is a
        # correction of a wrong class, not work dodged: nothing about `fcntl`
        # became easier.
        #
        # **AND A NAME WITH NO SOURCE IS IN ONE OF THE TWO CLAIM TIERS, which is
        # the rule `shlex` exposed on 2026-10-03 and which the measured shape of
        # the tiers settles.**  The requirement above reads as though every name
        # in the host set is one this tree has written, and for the two PERMANENT
        # tiers that is nearly so — but every `HOST_MODELLED` and every
        # `HOST_UNREACHABLE` name has no `formal/hostmods/` source, and each
        # tier's own comment says why: "reachable in principle, not implemented
        # today, and therefore a gap with an owner", and "this needs an object a
        # freestanding image does not have".  Both are CLAIMS, and a claim needs
        # no code behind it: "Modelled" says the work is doable and undone, so
        # requiring a source of it would be requiring the work the tier exists to
        # schedule, and "unreachable" says the object is missing, so no source
        # could exist for it even in principle.  The only tier that answers is
        # `HOST_ADMITTED`, and its membership rule IS the source --
        # `_admitted_tier_conflicts` below asserts that in both directions,
        # against the filesystem rather than against a list.
        #
        # So this is asserted as the RULE and in both directions: a name added to
        # the host set is named in the table above with the tier it was put in
        # (an addition nobody justified fails), and every row of that table is
        # still in the tier it names (a stale row fails).  Nothing here can be
        # satisfied by putting a source-less name on a list, which is the
        # anti-rot weakness the old allow-list had: it failed on a NAME, so
        # re-adding that name to the list with no file passed.
        added = sorted(union - orig)
        check(set(added) == set(HOST_SET_ADDED_TIERS),
              'every name added to the host set since the split is named above '
              'with the tier it was put in: a name in no tier at all is the one '
              'thing this account has no answer for, and it is what '
              '"imports a module that is not a stdlib or sibling module" was',
              f'added {added}, table {sorted(HOST_SET_ADDED_TIERS)}')
        for name, tier in sorted(HOST_SET_ADDED_TIERS.items()):
            check(I.host_module_tier(name) == tier,
                  f'{name} was added to the host set as {tier!r} and is still '
                  f'there; a name that has been written leaves both claim tiers',
                  f'now {I.host_module_tier(name)!r}')
            check(bool(tier in ('modelled', 'unreachable', 'admitted')),
                  f'{name} names a real tier, so the row above is a claim and '
                  f'not a free-text excuse', f'tier {tier!r}')
        # Everything provided that is not an admitted name left the set, so the
        # ORIGINAL list must contain it; an ADMITTED name did not leave, so
        # requiring that of one would be requiring a module that was never in
        # `orig` — `subprocess` and its four siblings — to have been there
        # before, which is the opposite of what admitting it did.
        # `left` is "of the names that WERE in the host set, the ones no longer
        # in it", so it is a subset of `orig` BY CONSTRUCTION and is intersected
        # with it rather than being read straight off `written_modules()`.
        #
        # That intersection is not a weakening, it is what the check means, and
        # it is what the pool widening made necessary: `written_modules()` walks
        # the hostmod directory as well as the tiers, so it returns `fcntl` and
        # `posixpath` — names that were NEVER in `HOST_MODULES` and so never
        # "left" anything.  Before the widening it returned only pre-split names,
        # which made `left` a subset of `orig` by ACCIDENT (the pool was a subset,
        # not the check).  A name can only leave a set it was in, so asking the
        # subtraction about a name that was never there was asking a question with
        # no answer, and it reported both as `unaccounted`.
        #
        # This is also what retires `HOST_SET_ADDED_THEN_WRITTEN`, which was a
        # hand-kept one-row table saying "`posixpath` was added to a tier and then
        # written" so that a widened `ever` could see it move.  A name lands in
        # that shape by being WRITTEN, so the walk finds the next one by being
        # written rather than by being listed, and the one-row table had already
        # gone stale once (`tempfile`, above).
        left = (written_modules() & set(orig)) - set(ADMITTED_HOST_MODULE_TESTS)
        check(not (written_modules() - set(orig) - set(ADMITTED_HOST_MODULE_TESTS)
                   - set(PROVIDED_NEVER_A_HOST_MODULE)
                   - set(SUBMODULE_HOST_MODULE_TESTS)),
              'every provided module is either in the pre-split host set, an '
              'admitted one, one that was never in the set, or an `os` '
              'submodule — a name this file cannot account for is a module '
              'nobody claims')
        check(left <= (orig - union),
              'every name that left the host set is one with real source '
              'behind it',
              f'left without source {sorted((orig - union) - left)}')
        check((orig - union) == left,
              'the account of what left the host set is exact',
              f'unaccounted {sorted((orig - union) ^ left)}')
        all_written = {**IMPLEMENTED_HOST_MODULE_TESTS,
                       **ADMITTED_HOST_MODULE_TESTS,
                       **PROVIDED_NEVER_A_HOST_MODULE,
                       **SUBMODULE_HOST_MODULE_TESTS}
        check(set(all_written) == written_modules(),
              'every written module names the test that keeps it honest, and '
              'no other name claims one',
              f'sym-diff {sorted(set(all_written) ^ written_modules())}')
        # ONE loop over the union, not one per table: the three tables are
        # disjoint and the union above is exactly what `written_modules()` is
        # required to equal, so three loops were three subsets of one check
        # written out three times.
        for name, test_file in sorted(all_written.items()):
            check(os.path.isfile(os.path.join(HERE, test_file)),
                  f'{name} is provided on the strength of {test_file}, and '
                  f'that test exists')
        # The admitted half is checked against the TREE and not only against the
        # table above: a name in `HOST_ADMITTED` with no `formal/hostmods` source
        # would be a claim the table cannot keep true by itself, and a hostmod
        # declaring a contract without its module being in the tier would let a
        # proof rest on a contract the tier does not admit to.
        check(not I._admitted_tier_conflicts(),
              'HOST_ADMITTED and formal/hostmods agree, in both directions',
              '; '.join(I._admitted_tier_conflicts()))
        # …and the OTHER direction of the same rule, which is the one that had
        # nothing checking it: a name in a CLAIM tier (`unreachable` says the
        # object is missing, `modelled` says the work is undone) that HAS a
        # `formal/hostmods/` source.  Such a name is the interesting one to get
        # wrong, because the source is real and the tier is the sentence a
        # reader gets instead: `shutil` sat in `HOST_UNREACHABLE` with a `mkdir`,
        # a `makedirs` and a `chmod` behind it, and `tempfile` sat there for a
        # day with `gettempdir` and `mkdtemp` behind it.  Both were caught here
        # only by a roster someone remembered to shorten.
        claim_with_source = sorted(
            (set(I.HOST_UNREACHABLE) | set(I.HOST_MODELLED))
            & I.hostmod_source_modules())
        check(not claim_with_source,
              'a name in a CLAIM tier has no formal/hostmods source, because a '
              'source means this tree answers for the module and that is '
              'HOST_ADMITTED — writing one is half of leaving the tier',
              f'claims with real source behind them {claim_with_source}')
    else:
        check(False, 'the pre-split HOST_MODULES list could be read from git',
              'git show HEAD:formal/imports.py did not yield it')
    # The written modules are not in either tier at all, and the resolver
    # reaches them instead — checked in both directions, so neither a leftover
    # entry with a source behind it nor a removal without one can pass.
    for m in sorted(ADMITTED_HOST_MODULE_TESTS):
        check(I._is_host_module(m) and I.host_module_tier(m) == 'admitted',
              f'{m} is an ADMITTED host module: still a host module (the '
              f'predicate must cover it), but neither unreachable nor modelled')
    for m in sorted(set(IMPLEMENTED_HOST_MODULE_TESTS)
                    | set(PROVIDED_NEVER_A_HOST_MODULE)):
        check(not I._is_host_module(m) and I.host_module_tier(m) == '',
              f'{m} is not a host module: this tree provides it now')
        check(m not in union,
              f'{m} still classifies as a host module although this tree '
              f'provides it, so the entry is false and the build is reached '
              f'through the front end / the resolver instead')
        if I.is_frontend_provided(m):
            # A front-end-provided module resolves to NOTHING, and that is the
            # correct answer rather than a missing one: there is no source file
            # because there is no symbol for a dylib to export, and the
            # resolver's contract is "the file to compile, or None". Asserting
            # `is None` here is what keeps the distinction from eroding — a
            # `None` that means "the front end has it" and a `None` that means
            # "nothing here can answer for it" are the same value, and only
            # `is_frontend_provided` tells them apart. It is also what proves
            # the import is not going to be resolved to some OTHER tree's file
            # by a later pass.
            check(I.resolve_module_path(m, project_root=HERE) is None,
                  f'{m} is provided by the front end, so there is no source '
                  f'file to compile and the resolver says so',
                  f'resolved to {I.resolve_module_path(m, project_root=HERE)!r}')
            check(not I._is_inert_module(m),
                  f'{m} is front-end-provided, not inert: it BINDS names the '
                  f'program calls, so it must not be excluded from the '
                  f'dependency walk the way `__future__` is')
        else:
            got = I.resolve_module_path(m, project_root=HERE)
            check(got is not None and os.path.isfile(got),
                  f'{m} resolves to a real source file', f'resolved to {got!r}')
    # A package's DOTTED form is a host-module name in its own right, so the
    # top-level half leaving the set is not enough to make `os.path` reach.
    check(not I._is_host_module('os.path')
          and I.host_module_tier('os.path') == '',
          'the dotted form os.path is not a host module either')
    check(I.resolve_module_path('os.path', project_root=HERE)
          == os.path.join(REPO, 'formal', 'hostmods', 'os', 'path',
                          '__init__.mojo'),
          'os.path resolves to a real source file')
    # The claim the split exists to make true: these are reachable, so calling
    # them "not fixable" was false. A name that has been WRITTEN is not in
    # this list because it is implemented rather than unreachable; see
    # `written_modules()` above for the derived account.
    # `json`, `re`, `time`, `math` and `stat` are all out of this list, and for
    # the same reason: each left HOST_MODELLED by being WRITTEN, which is the
    # other half of what the account above checks, and a name with a Mojo source
    # is implemented rather than "reachable in principle". `math` and `stat` are
    # two more of the names this check originally asserted here, and each stopped
    # being 'modelled' when its source was written
    # (`formal/hostmods/math.mojo`, `formal/hostmods/stat.mojo`).
    #
    # **THE LIST BELOW IS NOW THE ONE THAT CARRIES THE CLAIM**, so an entry in it
    # is a statement that a module is still genuinely unreachable. `shutil` left
    # it — which was correct, because `formal/hostmods/os/__init__.mojo` had
    # `mkdir`, `makedirs`, `remove`, `rmdir`, `rename`, `replace` and `chmod` and
    # `test_formal_os.py` runs 75 operations against the real filesystem, so the
    # "a writable filesystem this target does not get" half of that entry was
    # false. What is left of the sentence is the TERMINAL, and
    # `formal/hostmods/shutil.mojo`'s `get_terminal_size` is absent for exactly
    # that reason.
    #
    # `tempfile` left it on 2026-10-03, and it is the second half of the same
    # kind of correction rather than a re-decision: `formal/hostmods/tempfile.mojo`
    # computes `gettempdir`, `gettempprefix`, `TMP_MAX` and `mkdtemp(prefix)` —
    # a real directory at mode 448 with eight characters of CPython's own
    # alphabet from `arc4random_buf` — and `mkdir(2)` is not an object this
    # target lacks, so the entry was a claim about a filesystem the image
    # already had. What survives of it is the half that is still true
    # (`TemporaryDirectory` needs an `__exit__`, `NamedTemporaryFile` is a FILE
    # OBJECT), and both are in the module's own docstring and in
    # `FORMAL_tempfile_context_manager_needs_a_way_out_of_a_with`. A name
    # reaches this list by being written and leaves it by being named, so
    # adding one here is a separate edit from adding the module — and the
    # account above fails if only one of the two is done. Neither gets a
    # bespoke "in neither tier" assertion here: that is exactly what the loop
    # over `IMPLEMENTED_HOST_MODULE_TESTS` above already says about every
    # written name, and a second copy of it would be the duplicate the pair
    # above exists to prevent.
    # `traceback` left this list on 2026-10-04 for the same reason and the same
    # half of it: there is still no unwinder for it to format and no exception
    # object to hand it — `formal/hostmods/traceback.mojo` answers
    # `format_exc`/`print_exc` for the ONE state this target can be in (nothing
    # in flight, which is CPython's own `'NoneType: None\n'`) and every name that
    # needs a live traceback is absent from it. What survives of the entry is the
    # frames, and the module's docstring says so.
    for m in ('asyncio', 'socket', 'zlib',
              'getpass', 'webbrowser', 'logging', 'unittest'):
        check(I.host_module_tier(m) == 'unreachable',
              f'{m} is unreachable (needs an object the target does not have)')
    # The four that were on that roster until 2026-10-02 and are now ADMITTED —
    # named here rather than dropped, because a silently shortened roster is how
    # "unreachable" becomes a set nobody reads.  What is still true of each is
    # that the object is missing; what changed is that the module answers anyway,
    # under a declared contract.  `fcntl` was a fifth and is not here: the real
    # `flock(2)` landed, so it is neither unreachable nor admitted.
    for m in ('subprocess', 'ctypes', 'threading', 'concurrent.futures'):
        check(I.host_module_tier(m) == 'admitted',
              f'{m} needs an object this target does not have, and answers '
              f'under a DECLARED CONTRACT rather than being unreachable')
    for m in ('unittest.mock', 'importlib.util'):
        check(I.host_module_tier(m) != '',
              f'the dotted form {m} still classifies')
    check(I.host_module_tier('json') == I.host_module_tier('json.decoder'),
          'a dotted form follows its top-level component')
    # A name that was a host module and is not any more is deliberately absent
    # from this list: asserting it would pin the removal as permanent rather
    # than as a consequence of a Mojo source existing, and the check that keeps
    # that honest is the per-name pair in `written_modules()` above. `sys` was
    # the first such name, and it is why the phrase is here at all.
    for m in ('__future__', 'nosuchmodule'):
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
    # The Mach-O spelling used to be asserted HERE and is now asserted in
    # `test_bind_audit`, and the move is the point rather than bookkeeping:
    # `_is_libsystem` asks `dlsym` about the name the SOURCE spells (it is the
    # inverse of `model.target_libc_symbol`, which is where this pipeline adds
    # an underscore), so `_printf` as a source spelling means the C function
    # `_printf`, which libSystem does not export, and the honest answer is False.
    # A Mach-O spelling that really does arrive — a linked module's export —
    # never reaches this function: `_audit_bound_symbols`' `provided` set
    # accounts for it against the manifest, on both sides, which is what
    # `test_bind_audit`'s `_pkg_helper` row pins. Measured: the externs an image
    # actually binds are source spellings (`['os_path_join_2dbb98', 'printf']`
    # for a program that calls `os.path.join`).
    # A C IDENTIFIER MAY BEGIN WITH AN UNDERSCORE, and both ends of this
    # pipeline used to eat it: `libc_source_name` asked `dlsym` about a
    # DIFFERENT function (`_NSGetExecutablePath` → `NSGetExecutablePath`, which
    # libSystem does not export), and `_bind_info` dropped one before writing the
    # name dyld looks up. The hazard is not the wrong answer but that `dlsym`
    # and dyld DISAGREE about these names — the shared cache answers
    # `dlsym('_NSGetExecutablePath')` and the loader never looks that name up —
    # so an audit that asks dlsym about a name the loader would reject cannot
    # catch the linker half at all. Three rows, and the middle one is the
    # anti-rot direction: a fix that made the audit accept everything would pass
    # the first and fail this.
    for s in ('_NSGetExecutablePath', '_exit'):
        check(B._is_libsystem(s),
              f'libSystem provides {s} — the leading underscore is part of '
              f'the NAME, not the assembler\'s')
    check(not B._is_libsystem('NSGetExecutablePath'),
          "libSystem does NOT provide NSGetExecutablePath, so the audit is "
          "asking about the name the source spells rather than accepting every "
          "spelling of a symbol it does provide")
    # The `$INODE64` suffix is the only case the strip exists for, in both
    # spellings: `target_libc_symbol` appends it and the Mach-O spelling adds an
    # underscore in front.
    for spelled, want in (('readdir$INODE64', 'readdir'),
                         ('_readdir$INODE64', 'readdir'),
                         ('_NSGetExecutablePath', '_NSGetExecutablePath'),
                         ('printf', 'printf')):
        check(M.libc_source_name(spelled) == want,
              f'libc_source_name({spelled!r}) is {want!r}',
              f'got {M.libc_source_name(spelled)!r}')
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


# ── 5. the hostmods directory is visible to ONE resolver ─────────────────────

# The modules this backend has written for CPython's that a file in this tree
# imports BY THEIR CPython NAME, and the check names of a test rather than the
# modules themselves: what has to hold is that a module NAME with a Mojo source
# somewhere in this tree does not capture the name everywhere else, and the next
# one written is covered by the same loop.
#
# These four and not every file in `formal/hostmods/`, and the difference is
# the point of the list: `argparse`, `ast`, `hashlib`, `json`, `pathlib`, `re`,
# `time` and `typing` are CPython module names too, but no source in this tree
# imports them under that spelling today, so the negative below would be
# vacuous for them — a resolver asked about a name nothing imports still
# answers. A name added here has to be one a swept file really wants, which is
# also why `platform` is on it: thirty swept files import it, so four resolvers
# capturing a Mojo `platform` would be a real regression and not a hypothetical
# one.
HOST_MODULE_NAMES = ('os', 'sys', 'struct', 'platform')


def _short_repr(value, limit=120):
    """`repr` cut to a line, for a failure detail.

    A resolver's "found it" answer is a path from three of the four, but the
    interpreter's is a whole executed module namespace — several hundred
    characters of `repr` that bury the one fact the failure is about.
    """
    text = repr(value)
    return text if len(text) <= limit else text[:limit - 1] + '…'

# The resolvers that share the repository root, each named by the attribute or
# call that answers for it, with a one-line statement of what it is FOR. Read
# the list as the reason the modules are not at the top level: one of these was
# enough to break the compiler, and the gate found it as gcc diagnostics in
# `module_loader.py` and `mojo/middle/methods_shared.py` rather than as
# anything about `os`.
#
# (`imports.Resolver` is the gimple compiled path's authority — MOJO_PATH puts
# the repo root on every build's path. `ModuleLoader.resolve_module_path` is
# the stdlib/test one. `myinterpreter.Interpreter._load_mojo_sibling_module` is
# the interpreter's, and it walks UP from the importing file, so a file in a
# subdirectory reached the root too. `emit_resolve._module_candidate_paths` is
# the gimple backend's, and the repository is its last-resort search dir.)
def _nonformal_resolvers():
    out = []
    import imports
    # `_find` answers `(found, shadowed)`, and the second half is this
    # resolver's "first on MOJO_PATH wins" note — irrelevant here, because a
    # name with NO file is the answer being asserted. The first half is the
    # question: is there a source for it.
    resolver = imports.Resolver()
    out.append(("imports.Resolver (the gimple path's MOJO_PATH authority)",
                lambda name: resolver._find(name)[0]))
    from module_loader import ModuleLoader
    out.append(('module_loader.ModuleLoader.resolve_module_path (stdlib/test)',
                ModuleLoader().resolve_module_path))
    import myinterpreter
    interp = myinterpreter.Interpreter(filename=os.path.join(REPO, 'fire.py'),
                                       argv=['fire.py'])
    out.append(('myinterpreter._load_mojo_sibling_module (the interpreter)',
                interp._load_mojo_sibling_module))
    from mojo.backend_gimple import emit_resolve

    class _Gen:
        _current_filename = os.path.join(REPO, 'fire.py')
        _extra_search_paths = []

    gen = _Gen()
    out.append(('mojo.backend_gimple.emit_resolve._module_candidate_paths',
                lambda name: next((p for p in
                                   emit_resolve._module_candidate_paths(gen, name)
                                   if os.path.isfile(p)), None)))
    return out


def test_hostmods_are_invisible_to_every_other_resolver():
    """`formal/hostmods/` is a search root of `formal/imports.py` and of nothing
    else, and this is what says so.

    **The bug this makes unrepeatable.** `os`, `sys` and `struct` were written
    at the REPOSITORY ROOT, which is a search root for four independent
    resolvers, not only for the formal one. So a Mojo `os` there captured
    `import os` inside `fire.py`, `module_loader.py` and `gimple_codegen.py` —
    the compiler's own source — and the compiled path lowered `os.sep`, a
    `char *` constant with no storage behind it, as a module-level name.
    Measured in the integrator's gate, not inferred: `selfhost` failed, and
    `bootstrap-stage2-cc` failed with

        module_loader.py:305: error: invalid operands to binary +
          (have 'char *' and 'void *')

    where line 305 is `path.startswith(STDLIB_PATH + os.sep)`, and with
    `mojo/middle/methods_shared.py:63` the same error on the same expression.
    `os.sep` in a `+` is the whole story: the Mojo module was answering a name
    the host module answers, and the host module's answer is a real string.

    Nothing in the formal test files would ever have caught it. They ask
    whether the module RESOLVES, and it did — better than before. What broke
    was a different set of resolvers, in a different part of the tree, for a
    program nobody in this file builds.

    **The negative is the whole assertion.** Each resolver is asked the
    question it is asked, from a file in the repository root — the position
    `fire.py` itself imports `os` from — and must come back with the HOST
    module: no file, or the ValueError `ModuleLoader` raises for a name that is
    not `std*` and not a runtime test module, which is exactly what it has
    always said for `os`.
    """
    import formal.imports as I

    # The positive first, so a vacuous pass — a hostmods directory that does
    # not exist, or a resolver loop that silently found nothing because it
    # raised — cannot read as the negative passing.
    for name in HOST_MODULE_NAMES:
        path = I.resolve_module_path(name, relative_to=os.path.join(REPO, 't1.mojo'))
        check(path is not None and os.path.isfile(path),
              f'the formal resolver still finds a source for {name}',
              f'got {path!r} — without this the checks below are vacuous')
        check(path.startswith(I._HOSTMODS_ROOT + os.sep),
              f'{name} resolves inside the hostmods directory and nowhere else',
              f'got {path!r}, outside {I._HOSTMODS_ROOT}')

    # …and the shape on disk, which is the thing a future contributor
    # "tidies". A `struct.mojo` back at the root is a plausible thing to want
    # and is the exact regression, so it is asserted as a path rather than
    # left to the resolvers to notice.
    for rel in ('os', 'os/__init__.mojo', 'os/path', 'os/_syscalls.mojo',
                'sys.mojo', 'struct.mojo'):
        check(not os.path.exists(os.path.join(REPO, rel)),
              f'nothing named {rel} is at the repository root: the root is a '
              f'search root for four other resolvers, and a Mojo module there '
              f'captures the name in the compiler\'s own sources')

    resolvers = _nonformal_resolvers()
    check(len(resolvers) == 4,
          'the estate: every non-formal resolver is exercised, so a fifth '
          'cannot be added without this failing',
          f'found {len(resolvers)}')
    for name in HOST_MODULE_NAMES:
        for label, ask in resolvers:
            try:
                got = ask(name)
            except ValueError as e:
                # `ModuleLoader` refusing a non-`std` name IS its host-module
                # answer, and asserting on the message keeps a change that made
                # it fail for some other reason from reading as a pass.
                check('Only stdlib and test imports supported' in str(e),
                      f'{label}: {name} is refused as a non-stdlib import, '
                      f'which is its host-module answer', str(e))
                continue
            except Exception as e:                       # noqa: BLE001
                check(False, f'{label}: {name} raised instead of answering',
                      f'{type(e).__name__}: {e}')
                continue
            check(got is None,
                  f'{label}: {name} is not a Mojo source in this tree, so the '
                  f'HOST module answers the import',
                  # Bounded: the interpreter's answer to a FOUND module is a
                  # whole namespace object, and a repr of that buries the
                  # one line that matters under a thousand.
                  f'it resolved to {_short_repr(got)}')


def main():
    test_relative_imports()
    test_host_tiers()
    test_libsystem_provider()
    test_bind_audit()
    test_audit_fires_on_a_real_build()
    test_sorry_note()
    test_hostmods_are_invisible_to_every_other_resolver()
    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(RESULTS)} checks")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
