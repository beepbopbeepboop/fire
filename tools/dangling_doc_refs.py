#!/usr/bin/env python3
"""dangling_doc_refs.py -- every `bugs/<name>.md` this tree cites that is not
in `bugs/`.

CLAUDE.md deletes a bug doc when the bug is fixed, rather than leaving it
behind with a Status history: a fixed bug still listed is indistinguishable
from an open one to whoever reads the queue next. That is the right rule and
it has a cost this tool exists to measure — every citation of a deleted doc
becomes a reference to nothing, in a file that exists to be believed. The
first instance found (`bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md`)
was a test file's module docstring, which is documentation a reader trusts
sending them to a file that is not there.

The walk is over `.md` and `.py`, and it reuses `checked_run.is_derived_dir`
rather than keeping a second list of "not part of the repo", for the reason
that function's docstring gives: two lists are two answers to "what is a file
in this repo", and they eventually disagree.

    python3 tools/dangling_doc_refs.py            # the census, by doc name
    python3 tools/dangling_doc_refs.py --by-file  # by citing file
    python3 tools/dangling_doc_refs.py --json     # machine-readable
    python3 tools/dangling_doc_refs.py --ratchet  # only REGRESSIONS vs the baseline
    python3 tools/dangling_doc_refs.py --write-baseline   # regenerate it

Exit code is 1 when anything dangles, 0 when nothing does, so this can become
a hook without being edited first. It is NOT wired into any bucket, and the
reason is the measurement rather than taste: on 2026-10-01 it found 335
citations across 126 deleted names, and two thirds of them are inside
`fire_compiler.py`, `gimple_codegen.py`, `formal/` and `mojo/` — files that
belong to whichever worker owns that area, not to whoever fixes the prose. A
`check()` over the whole corpus would go red on every one of those branches for
something it did not do, and a red check is indistinguishable from a real
regression. The census is a CAMPAIGN, so it is reported as one.

THE RATCHET is what that reasoning left missing, and it is the one shape that
works over a corpus nobody can clear in one commit: `--ratchet` compares each
file against a per-file ceiling in `tools/dangling_refs_baseline.py` and fails
only when a file GAINS citations. That is green on arrival (every entry is the
observed count), so it is a check a developer runs and a gate can hold; it goes
red when someone deletes a bug doc whose name thirty files still cite, or adds
a citation of one, and the fix is the one-line prose rewrite; and it can never
go red for a branch that only fixed citations, because a file that lost them is
below its ceiling. `--write-baseline` regenerates the ceilings after a sweep
and prints what moved, so the ledger is regenerated rather than hand-edited.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import checked_run  # noqa: E402  — after the sys.path line that finds it

# A `bugs/` path, with the optional subdirectory the tree uses (`hard/`, and
# one `consolidated/`). The character class is deliberately narrow — no spaces,
# no shell metacharacters — because a wider one starts matching prose that
# merely mentions the directory.
REF = re.compile(r'bugs/((?:hard/|consolidated/)?[A-Za-z0-9_][A-Za-z0-9_./+-]*'
                 r'\.md)')
SUFFIXES = ('.md', '.py')

# A BARE citation: a bug-doc stem with no `bugs/` in front of it. This is the
# second spelling of the same reference and the ratchet above could not see it,
# which is why a whole class of dangling citations survived: the tool's `REF`
# requires the `bugs/` prefix, so a comment that wrote
# `FORMAL_dataclass_partial_construction` with no directory — which is how all
# eleven sites in `formal/` and its tests were written, and how the survey at
# `bugs/FORMAL_arm64_instruction_coverage.md` still cites its deleted bit-test
# doc — was invisible to a census whose entire job is to find those.
#
# It is a SEPARATE class rather than a second regex over one list, because the
# two cannot be told apart by the reader: a bare stem is only a citation if no
# file of that name exists ANYWHERE in the tree, and `doc/ELABORATION.md` and
# `doc/MODULE_CACHE_DESIGN.md` are cited bare by four files each and are real.
# So the resolution is by EXISTENCE, not by spelling: the name counts as a
# citation when `bugs/<stem>.md` is absent AND no `.md` of that basename exists
# anywhere in the repository.
#
# Reported, and deliberately NOT in the ratchet. The ratchet is a per-file
# ceiling, and a bare-name citation has no convention that separates the ~20
# historical "was X, deleted" sentences from a new one — a ledger for it would
# have to bless every existing sentence, and this tree is worked from dozens of
# worktrees at once, so any branch that fixes prose in a file another branch is
# editing would move a number the ledger owns. Making it visible is the part
# that pays; a verdict on it is a decision for whoever owns the tool.
BARE_REF = re.compile(r'(?<![/\w.-])([A-Z][A-Za-z0-9_]{4,})\.md\b')

# The ratchet's ledger. A `.py` and not a JSON so that the two entries which
# need a WHY — the deliberate self-referential fixtures in `test_suite.py` —
# can carry it next to the number.
BASELINE_PATH = os.path.join(HERE, 'dangling_refs_baseline.py')


def existing_docs():
    """Every `bugs/**.md` path, relative to the repo root."""
    out = set()
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, 'bugs')):
        dirnames[:] = sorted(d for d in dirnames
                             if not checked_run.is_derived_dir(d))
        for name in sorted(filenames):
            if name.endswith('.md'):
                rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
                out.add(rel.replace(os.sep, '/'))
    return out


def candidates():
    """Every `.md`/`.py` in the repo that could cite a doc, as root-relative
    paths, with the derived directories dropped.

    TRACKED files, which is `git ls-files` rather than a directory walk, and the
    reason is portability of the ratchet below. This tree is worked in from
    several dozen git worktrees at once and each carries scaffolding of its own
    — this worktree alone has an untracked `TASK.md` that names two bug docs and
    a `work.log`. A ledger generated from a filesystem walk would carry those
    numbers, the same branch checked out in a worktree without them would go
    red, and a check that answers differently for two checkouts of one commit
    is not a check. `checked_run.is_derived_dir` still drops `build/` and the
    dot-directories, because `git ls-files` lists a tracked file under
    `__pycache__/` like any other and those are not inputs either.

    Falls back to the directory walk, with a warning, if git cannot answer —
    the census is still true, it just cannot distinguish this worktree's
    scaffolding from the repository's files.
    """
    import subprocess
    try:
        ls = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT,
                            capture_output=True, text=True, timeout=60,
                            errors='replace')
        if ls.returncode == 0 and ls.stdout:
            names = [n for n in ls.stdout.split('\0') if n.endswith(SUFFIXES)]
            return [n.replace(os.sep, '/') for n in sorted(names)
                    if n.replace(os.sep, '/') != SELF_PATH
                    and not any(checked_run.is_derived_dir(part)
                                for part in n.replace(os.sep, '/').split('/'))]
        print(f'warning: `git ls-files` exited {ls.returncode}; walking the '
              f'filesystem instead, so this run also sees untracked files',
              file=sys.stderr)
    except (OSError, subprocess.SubprocessError) as e:
        print(f'warning: `git ls-files` unavailable ({type(e).__name__}: {e}); '
              f'walking the filesystem instead, so this run also sees untracked '
              f'files', file=sys.stderr)
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames
                             if not checked_run.is_derived_dir(d))
        for name in sorted(filenames):
            if name.endswith(SUFFIXES):
                rel = os.path.relpath(os.path.join(dirpath, name), ROOT)
                out.append(rel.replace(os.sep, '/'))
    return out


def all_markdown_basenames():
    """Every `.md` basename anywhere in the repository, for the bare check.

    One walk rather than a per-candidate `os.path.exists`, because a candidate
    that resolves is the common case on a tree with `doc/` full of design notes
    and this is the instrument that has to stay cheap enough to run in the
    census. Derived directories are dropped by the same rule as everything else
    here (`checked_run.is_derived_dir`).
    """
    out = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames
                             if not checked_run.is_derived_dir(d) and d != '.git')
        for name in filenames:
            if name.endswith('.md'):
                out.add(name)
    return out


def bare_find(skip=()):
    """(by_doc, by_file) for every BARE reference to a doc that is nowhere.

    Skip a candidate when the name exists in `bugs/`, when a `.md` of that name
    exists anywhere in the tree (`doc/`, the repo root, or beside the citing
    file), and when the citing line already says the doc was deleted — the three
    historical conventions `bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md`
    §2 established, which are what keeps a sentence that is *about* a deleted
    doc from being counted as one that *needs* it.
    """
    have = existing_docs()
    names = all_markdown_basenames() - {n.rsplit('/', 1)[-1] for n in have}
    deleted_convention = re.compile(
        r'\b(deleted|git rm|now closed|no longer|used to (?:give|cite|carry))',
        re.I)
    by_doc, by_file = {}, {}
    for rel in candidates():
        if rel in skip:
            continue
        try:
            text = open(os.path.join(ROOT, rel), encoding='utf-8',
                        errors='replace').read()
        except OSError:
            continue
        beside = os.path.basename(rel)
        for lineno, line in enumerate(text.splitlines(), 1):
            if deleted_convention.search(line):
                continue
            for stem in BARE_REF.findall(line):
                name = stem + '.md'
                if name in names or os.path.exists(
                        os.path.join(ROOT, os.path.dirname(rel), name)):
                    continue
                by_doc.setdefault(name, []).append((rel, lineno))
                by_file.setdefault(rel, []).append((name, lineno))
    return by_doc, by_file


def find(skip=()):
    """(cited, by_doc, by_file) for every reference to a doc that is gone.

    `skip` is a set of repo-relative paths to leave out — used by
    test_suite.py to exclude its own synthetic fixture names, which are
    deliberately non-existent and are what proves the walk works.
    """
    have = existing_docs()
    by_doc, by_file = {}, {}
    for rel in candidates():
        if rel in skip:
            continue
        try:
            text = open(os.path.join(ROOT, rel), encoding='utf-8',
                        errors='replace').read()
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name in REF.findall(line):
                if f'bugs/{name}' in have:
                    continue
                by_doc.setdefault(name, []).append((rel, lineno))
                by_file.setdefault(rel, []).append((name, lineno))
    return have, by_doc, by_file


# ── the ratchet ────────────────────────────────────────────────────────────
# Per-file ceilings, so the corpus can only shrink and a NEW citation of a
# deleted doc is a failure rather than a line in a census nobody diffs.
#
# The ledger is a generated file (see `--write-baseline`), because a ceiling
# that is hand-maintained across 165 files is a second copy of the census and
# the two would disagree. Regenerating it after a sweep is one command, and it
# prints the delta so a rewrite cannot quietly raise its own ceiling.

_BASELINE_HEADER = '''"""Per-file ceilings for `tools/dangling_doc_refs.py --ratchet`.

GENERATED by `python3 tools/dangling_doc_refs.py --write-baseline`. Do not
hand-edit: a file listed here is one whose citations of DELETED bug docs this
tree still carries, and the number is what it carried when the ledger was last
regenerated. The ratchet fails when a file EXCEEDS its number, so a file that
fixes its citations needs no entry change, and an entry may be removed once the
file has none.

Two entries are deliberate rather than unfixed, and are the reason this ledger
is a `.py` and not a JSON:

`test_suite.py` names documents that do not exist (`NEVER_WRITTEN.md`,
`NO_SUCH_DOC_ANYWHERE.md`, `DELETED_ONCE.md`, `SOME.md`) to PROVE the marker
checks can fail. A walk for missing files is guaranteed to find one there. That
also makes them the one thing in this tree a citation SWEEP must not rewrite:
they are the negative controls, so "this name does not resolve" is the property
under test, and a sweep that turned them into prose would silently delete the
proof while leaving the check green. `tools/suite.py` cites a `.md` path as a
fixture for the same reason.

THE LEDGER ITSELF (`tools/dangling_refs_baseline.py`) is EXCLUDED from the
walk, and it is excluded rather than entered because an entry for it cannot
mean anything. Its whole content is the set of doc names other files still
cite, so its own dangling-citation count is a function of what every OTHER
file has been cleaned up to — it moves when a sweep lands, it moves when the
compiler changes which docs exist, and `--write-baseline` would have to record
its own pre-write number. That is not a ceiling, it is a snapshot of the
ledger in the ledger. `test_suite.py` and `tools/suite.py` stay IN, because
their fixtures are a fixed, small, intentional number that a ceiling can
honestly bound.
"""'''
SELF_PATH = os.path.relpath(BASELINE_PATH, os.path.dirname(HERE)).replace(
    os.sep, '/')


def load_baseline():
    """The per-file ceilings, or {} when the ledger is absent.

    Read with `ast` and not by importing it. The ledger is generated, so the
    failure this guards is a half-written one (an interrupted `--write-baseline`
    leaves a file with an unterminated docstring), and a census tool that cannot
    print its own census is worse than useless: the walk still runs and the
    ratchet reports what it can.
    """
    if not os.path.exists(BASELINE_PATH):
        return {}
    import ast
    try:
        tree = ast.parse(open(BASELINE_PATH, encoding='utf-8').read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    getattr(t, 'id', None) == 'BASELINE' for t in node.targets):
                return dict(ast.literal_eval(node.value))
    except (SyntaxError, ValueError) as e:
        print(f'warning: {os.path.relpath(BASELINE_PATH, ROOT)} is unreadable '
              f'({type(e).__name__}: {e}); every file is allowed its observed '
              f'count, so --ratchet cannot fail and the census below is still '
              f'true. Regenerate it with --write-baseline.',
              file=sys.stderr)
    return {}


def ledger_verdicts(by_file, baseline=None):
    """{rel: (observed, ceiling)} for every file that still cites a deleted doc.

    **THE floor, in one place, because two mechanisms need it and they had two
    answers.** `ratchet_regressions` reads it to decide which files GAINED
    citations; `test_suite.py`'s corpus check reads it to decide which citations
    the ledger has already accounted for. Those are the same question asked twice
    and implemented twice — one as a per-file ceiling and one as "zero, outside
    this file's five deliberate fixtures" — and two floors over one corpus is how
    a sanctioned `--write-baseline` raise came to leave `doc-refs` green and
    `suite-self-test` red about a citation that was not new, was raised on
    purpose, and had a document explaining it. The fix is the join, not deleting
    either check: the strict one is a property of the SWEEP ("nothing outside
    the controls that the ledger does not already account for", proved against a
    guaranteed corpus so it cannot pass vacuously) and the ratchet is a property
    of the WALK ("no ceiling rises without `--write-baseline`").

    A file with no entry is allowed 0, which is the strict default and the one
    that catches a brand-new file citing a deleted doc.
    """
    if baseline is None:
        baseline = load_baseline()
    return {rel: (len(cites), baseline.get(rel, 0))
            for rel, cites in by_file.items()}


def sanctioned(by_file, baseline=None):
    """{rel} for every file whose citations the ledger already accounts for.

    The other half of `ledger_verdicts`, and the reading a strict "the corpus is
    empty outside the controls" check needs: a citation in one of these files is
    inside the ceiling the ledger recorded, so it is a KNOWN leftover rather than
    a regression, and subtracting it is what lets the sweep's property be stated
    without denying a raise `CLAUDE.md` sanctions.
    """
    return {rel for rel, (observed, ceiling)
            in ledger_verdicts(by_file, baseline).items()
            if observed <= ceiling}


def stale_baseline_entries(by_file, baseline=None):
    """{rel: (observed, ceiling)} for ledger entries the corpus has outgrown.

    The ledger is a CEILING, so a file that fixed its citations does not need an
    entry change to stay green — which is what lets a worker fix a file and merge
    without touching it. The cost is that a stale entry is invisible: the number
    is a ceiling, not a measurement, so an entry left behind by a fix is
    indistinguishable from one that is still needed. This is that distinction, and
    a caller that wants the ledger to describe the corpus rather than bound it
    reads it here.
    """
    return {rel: (observed, ceiling) for rel, (observed, ceiling)
            in ledger_verdicts(by_file, baseline).items()
            if observed < ceiling}


def ratchet_regressions(by_file, baseline=None):
    """[(rel, observed, allowed)] for every file that GAINED citations.

    A file whose observed count has fallen below its ceiling is not a regression
    and not reported, which is what lets a worker fix a file and merge without
    touching the ledger at all. The floor itself is `ledger_verdicts`, shared
    with `sanctioned` so the two mechanisms cannot drift into disagreeing about
    what the ledger records.
    """
    return sorted(((rel, observed, ceiling)
                   for rel, (observed, ceiling)
                   in ledger_verdicts(by_file, baseline).items()
                   if observed > ceiling),
                  key=lambda t: (-t[1], t[0]))


def write_baseline(by_file, skip=(), baseline=None):
    """Regenerate the ledger, and report what moved."""
    have = load_baseline() if baseline is None else dict(baseline)
    now = {rel: len(cites) for rel, cites in by_file.items() if cites}
    lines = [_BASELINE_HEADER, 'BASELINE = {']
    for rel in sorted(now):
        lines.append(f'    {rel!r}: {now[rel]},')
    lines.append('}\n')
    with open(BASELINE_PATH, 'w') as f:
        f.write('\n'.join(lines))
    fixed = sorted(r for r in have if r not in now)
    raised = sorted(r for r in now if now[r] > have.get(r, 0))
    print(f'{len(now)} files, {sum(now.values())} citations of deleted docs; '
          f'ledger written to {os.path.relpath(BASELINE_PATH, ROOT)}')
    for rel in fixed:
        print(f'  DROPPED  {rel}: {have[rel]} -> 0 (entry removed)')
    for rel in raised:
        print(f'  RAISED   {rel}: {have.get(rel, 0)} -> {now[rel]}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--by-file', action='store_true',
                    help='group the census by citing file instead of by '
                         'deleted doc name (this is the landing order: it is '
                         'sorted by count)')
    ap.add_argument('--json', action='store_true', help='machine-readable')
    ap.add_argument('--ratchet', action='store_true',
                    help='fail only when a file GAINS citations of a deleted '
                         'doc, against tools/dangling_refs_baseline.py')
    ap.add_argument('--write-baseline', action='store_true',
                    help='regenerate that ledger from the census and report '
                         'what moved')
    ap.add_argument('--skip', action='append', default=(),
                    help='a repo-relative path to leave out of the walk '
                         '(repeatable)')
    args = ap.parse_args()

    _have, by_doc, by_file = find(skip=set(args.skip))
    n_cites = sum(len(v) for v in by_doc.values())

    if args.write_baseline:
        return write_baseline(by_file, skip=set(args.skip))

    if args.ratchet:
        regressions = ratchet_regressions(by_file)
        total = sum(len(v) for v in by_file.values())
        if not regressions:
            print(f'ratchet: no file gained a citation of a deleted doc '
                  f'({total} citations remain across {len(by_file)} files, '
                  f'all at or below their baseline)')
            return 0
        print(f'ratchet: {len(regressions)} file(s) cite MORE deleted docs '
              f'than tools/dangling_refs_baseline.py allows:')
        for rel, observed, allowed in regressions:
            print(f'  {rel}: {observed} (baseline {allowed}) — '
                  + ', '.join(sorted({d for d, _n in by_file[rel]}))[:200])
        print('\nThe fix for one of these is to name the BUG rather than the '
              'doc — the\nsymptom, or the commit that fixed it — which is what '
              'test_arm64_encoders.py says\nat its shift sweep. If the '
              'citation is deliberate, say so in a comment\non the same line, '
              'or raise the ceiling on purpose with\n'
              '`--write-baseline` after reading the diff.')
        return 1

    if args.json:
        bare_by_doc, bare_by_file = bare_find(skip=set(args.skip))
        print(json.dumps({
            'deleted_names': len(by_doc),
            'citations': n_cites,
            'bare_deleted_names': len(bare_by_doc),
            'bare_citations': sum(len(v) for v in bare_by_doc.values()),
            'bare_by_doc': {k: [f'{f}:{n}' for f, n in v]
                            for k, v in sorted(bare_by_doc.items())},
            'by_doc': {k: [f'{f}:{n}' for f, n in v]
                       for k, v in sorted(by_doc.items())},
            'by_file': {k: [f'{d}@{n}' for d, n in v]
                        for k, v in sorted(by_file.items())},
        }, indent=2, sort_keys=True))
        return 1 if by_doc else 0

    bare_by_doc, bare_by_file = bare_find(skip=set(args.skip))
    n_bare = sum(len(v) for v in bare_by_doc.values())
    print(f'{n_cites} citations of {len(by_doc)} bugs/ docs that are not there, '
          f'across {len(by_file)} files')
    print(f'{n_bare} BARE citations (no `bugs/` prefix) of {len(bare_by_doc)} '
          f'doc names that are nowhere in the tree, across '
          f'{len(bare_by_file)} files — the spelling the count above cannot see, '
          f'and the reason a whole class of them survived it. NOT in --ratchet; '
          f'see BARE_REF\'s comment for why, and for the decision that would '
          f'have to be made to put it there.')
    if args.by_file:
        for rel, cites in sorted(by_file.items(), key=lambda kv: -len(kv[1])):
            names = sorted({d for d, _n in cites})
            shown = ', '.join(names[:3]) + (' …' if len(names) > 3 else '')
            print(f'  {len(cites):4}  {rel}\n         {shown}')
    else:
        for name, cites in sorted(by_doc.items(), key=lambda kv: -len(kv[1])):
            print(f'  {len(cites):4}  bugs/{name}')
            for rel, lineno in cites[:3]:
                print(f'         {rel}:{lineno}')
            if len(cites) > 3:
                print(f'         … and {len(cites) - 3} more')
    print('\nThe fix for one of these is to name the BUG rather than the doc — '
          'the\nsymptom, or the commit that fixed it — which is what '
          'test_arm64_encoders.py\nsays at its shift sweep. See '
          'bugs/DOCS_deleted_bug_doc_still_cited_in_three_places.md.')
    return 1 if by_doc else 0


if __name__ == '__main__':
    sys.exit(main())
