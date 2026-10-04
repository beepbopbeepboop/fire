#!/usr/bin/env python3
"""test_formal_doc_truth.py -- every CHECKABLE number in FORMAL.md, doc/ABI.md
and OPUS.md is read out of the document and compared with the tree.

    python3 test_formal_doc_truth.py [-v] [group ...]

## Why this file exists

FORMAL.md, `doc/ABI.md` and `OPUS.md` describe the formal backend, and ~250
merges have changed it since they were written. The drift is not evenly
distributed: the prose arguments are still broadly right, and what has rotted is
almost entirely the **checkable** half -- a count, a function name, a limit, a
refusal message, an ABI signature, a tool flag. Those are exactly the claims a
reader acts on, and none of them had an instrument.

The project already has two doc instruments and neither reaches these files'
figures:

* `test_suite.py`'s `a_doc_that_states_a_tests_status_agrees_with_the_registry`
  reads STATUS (`expect=` / `disabled=`) out of table rows, and only for tests
  that carry a marker.
* `test_formal_admitted.py` reads two published figures out of FORMAL.md -- the
  admitted-contract inventory (§7a) and the decide-site census (§7 row 10) -- and
  checks both directions.
* `test_formal_monomorph.py` reads every `doc/` and `bugs/` file for a mangled
  spelling and fails on one `monomorphize.mangle` does not produce.

So the census in FORMAL.md §2.2 -- which is the number the whole phase-2 argument
rests on -- was free to be wrong, and was: it published 540 entry points and 219
word-shaped where the tree has 668 and 262, it claimed 18 of 22 sqlite entry
points are word-shaped where 16 are, and it called all 15 `fire_python.h` entry
points word-shaped where 6 are. Three wrong numbers in the paragraph a reader
would consult before planning the next phase, none of them flagged.

The three rules this file follows, each learned from one of those:

1. **The DOCUMENT is the single copy.** Every figure below is parsed out of the
   Markdown and compared with the instrument, so the fix is to edit the prose and
   not to keep a second table here that can drift from it. `test_formal_admitted
   .py`'s `_published_inventory` is the model.
2. **Both directions.** A doc that publishes fewer than the tree has is a stale
   doc; a doc that publishes MORE is a doc describing something that is not
   there. A one-directional check only catches the first.
3. **A citation is a NAME with a line number attached**, which is the policy
   FORMAL.md's own header states ("each citation names the function or construct
   first and the line second"). So a citation is checked for the thing that
   matters -- the name resolves in the named file -- and the line number is
   checked only for *drift*, with a generous window, because ~250 merges have
   moved every line in this tree and a window tight enough to catch a one-line
   edit would fire on every unrelated commit.

No Lean, no proof, no compile, no image. The whole file is import-and-compare,
which is what makes it cheap enough to belong in `check`.

## Groups

  census     FORMAL.md §2.2's runtime-ABI census, read out of the document
  constants  the limits and budgets FORMAL.md and OPUS.md publish
  closed     the holes FORMAL.md §7 struck, and the ones it must not re-publish
  citations  every named claim in FORMAL.md / doc/ABI.md / OPUS.md resolves
  abi        doc/ABI.md's boundary rows against runtime/fire_runtime.h
  opus       OPUS.md's two claims about the library and the fuel
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RESULTS = []


def check(ok, what, detail=''):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f': {detail}' if detail else ''), flush=True)


def doc(name):
    """One of the three documents, read once per process."""
    return open(os.path.join(HERE, name), encoding='utf-8').read()


def flat(text):
    """`text` with its hard line breaks collapsed.

    All three documents wrap at 80 columns, so a prose-fragment test over the
    raw text fails on a REFLOW and not on a claim — the first version of this
    file's OPUS.md check could not see a sentence whose "it said" and its quote
    landed on different lines, and reported a present-tense claim that had been
    corrected. Markdown structure (tables, code fences) is not preserved here,
    so this is for prose fragments only; the table and code checks above use the
    raw text and their own anchors.
    """
    return ' '.join(text.split())


def read_int(text, pattern, what):
    """`(n, ok)` for the first integer `pattern` finds in `text`.

    `ok` is False when the document no longer says what this file reads, which
    is a FAILURE and not a skip: a renamed heading or a reworded row is exactly
    how the previous version of a figure rots, and a check that went quiet when
    its own anchor moved is a check that reports green forever.
    """
    m = re.search(pattern, text)
    return (int(m.group(1)), True) if m else (0, False)


# ── 1. FORMAL.md §2.2's runtime-ABI census ──────────────────────────────────

def group_census():
    """The number the phase-2 argument rests on, in both directions.

    `runtime_abi()` reads every header in `runtime/` through the scanner that
    already exists (`reflect.collect_runtime_exports_h`), so this group never
    needs a name added by hand -- which is the whole reason §2.2 cites it as the
    authority rather than carrying a hand-kept table.
    """
    text = doc('FORMAL.md')
    import formal.model as M
    import reflect

    abi = M.runtime_abi()
    total = len(abi)
    word = sum(1 for e in abi.values() if e['word'])

    got_headers, ok = read_int(
        text, r'entry points across \*\*(\d+)\*\* headers', 'header count')
    got_total, ok2 = read_int(
        text, r'entry points across \*\*\d+\*\* headers \| \*\*(\d+)\*\*', 'total')
    nheaders = len(glob.glob(os.path.join(HERE, 'runtime', '*.h')))
    check(ok, 'FORMAL.md §2.2 still states how many headers it counted over')
    check(ok2, 'FORMAL.md §2.2 still states a total entry-point figure')
    check(got_headers == nheaders,
          f'FORMAL.md §2.2 counts {got_headers} runtime headers, there are {nheaders}')
    check(got_total == total,
          f'FORMAL.md §2.2 publishes {got_total} entry points, runtime_abi() has {total}')

    got_word, ok3 = read_int(
        text, r'\*\*word in, word out\*\* \| \*\*(\d+)\*\*', 'word count')
    got_box, ok4 = read_int(
        text, r'not word-shaped \| \*\*(\d+)\*\*', 'non-word count')
    check(ok3, 'FORMAL.md §2.2 still states a word-shaped count')
    check(ok4, 'FORMAL.md §2.2 still states a non-word count')
    check(got_word == word,
          f'FORMAL.md §2.2 publishes {got_word} word-shaped entry points, '
          f'runtime_abi() says {word}')
    check(got_box == total - word,
          f'FORMAL.md §2.2 publishes {got_box} non-word entry points, '
          f'runtime_abi() says {total - word}')

    # The per-header breakdown, which is the part a reader uses to find the file
    # to go read. Checked one row at a time so a wrong row names itself.
    row = re.search(r'\| entry points across.*?\n', text)
    check(row is not None, 'FORMAL.md §2.2 has its census table row')
    if row is not None:
        note = row.group(0)
        counted = 0
        for path in sorted(glob.glob(os.path.join(HERE, 'runtime', '*.h'))):
            base = os.path.basename(path)
            real = len(reflect.collect_runtime_exports_h(path))
            counted += real
            m = re.search(re.escape(f'`{base}`') + r'\s+(\d+)', note)
            if m is None:
                # `fire_wd.h` is published as "scans to zero" rather than as a
                # count, which is the same claim in words.
                check(base == 'fire_wd.h' and real == 0,
                      f'FORMAL.md §2.2 names {base} in its header breakdown',
                      f'{base} has {real} entry points and the row does not say so')
                continue
            check(int(m.group(1)) == real,
                  f'FORMAL.md §2.2 says {base} declares {m.group(1)} entry points, '
                  f'the header declares {real}')
        check(counted == total,
              f'the per-header rows sum to {counted} and runtime_abi() has {total}')

    # §2.2's two worked examples. Both were wrong, in opposite directions from
    # what a reader would assume: sqlite was OVER-counted (a `double` is one
    # 64-bit slot and is not a value on this path) and fire_python was called
    # wholly word-shaped when 9 of its 15 return a `void *`.
    got_sq, ok5 = read_int(
        text, r'\*\*(\d+) of 22 are pure word-in/word-out\*\*', 'sqlite word count')
    check(ok5, 'FORMAL.md §2.2 still states the sqlite word count')
    sq = {n: e for n, e in abi.items() if n.startswith('mojo_sqlite3')}
    real_sq = sum(1 for e in sq.values() if e['word'])
    check(got_sq == real_sq,
          f'FORMAL.md §2.2 says {got_sq} of {len(sq)} sqlite entry points are '
          f'word-shaped, runtime_abi() says {real_sq}')
    # …and every exception is NAMED, because a count a reader cannot act on is a
    # number and a list is a census. Both directions: named and not an exception,
    # and a real exception left unnamed.
    #
    # "Named" means named IN THE EXCEPTIONS BLOCK, not anywhere in the file. The
    # first version of this check tested the whole document and reported
    # `mojo_sqlite3_step` as wrongly listed, because §6 phase 2 mentions it by
    # name in an entirely different argument -- which is what a substring test
    # over a 1400-line document means by "mentioned".
    block = re.search(r'\*\*The six exceptions.*?(?=\n`runtime/fire_python)',
                      text, re.S)
    check(block is not None,
          'FORMAL.md §2.2 still has a block naming the sqlite exceptions')
    block = block.group(0) if block is not None else ''
    for n, e in sorted(sq.items()):
        named = f'`{n}`' in block
        if e['word']:
            check(not named or n == 'mojo_sqlite3_close',
                  f'FORMAL.md §2.2 does not list word-shaped {n} as an exception')
        else:
            check(named,
                  f'FORMAL.md §2.2 names the sqlite exception {n}')

    got_py, ok6 = read_int(
        text, r'`runtime/fire_python\.c` — 15 functions, \*\*(\d+) of them '
              r'word-shaped\*\*', 'fire_python word count')
    check(ok6, 'FORMAL.md §2.2 still states the fire_python word count')
    py = {e['name'] for e in
          reflect.collect_runtime_exports_h(os.path.join(HERE, 'runtime',
                                                        'fire_python.h'))}
    real_py = sum(1 for n in py if abi.get(n, {}).get('word'))
    check(got_py == real_py,
          f'FORMAL.md §2.2 says {got_py} of {len(py)} fire_python entry points '
          f'are word-shaped, runtime_abi() says {real_py}')

    # §3.2 and §5 both restate the non-word figure. A restatement is a second
    # copy, and this is the one that was wrong twice.
    for m in re.finditer(r'(?:the )?(\d+)\s+(?:box-crossing|non-word)', text):
        check(int(m.group(1)) == total - word,
              f'FORMAL.md restates the non-word count as {m.group(1)} and '
              f'runtime_abi() says {total - word}')


# ── 2. the limits and budgets the documents publish ─────────────────────────

def group_constants():
    """A number that sizes a policy is a number that has to be right.

    Each of these is a limit somebody would rely on without re-deriving it: a
    scratch region a program can exhaust, a `-M` a build fails under, a count of
    admission sites a reader uses to decide how much of the model is trusted.
    """
    text = doc('FORMAL.md')
    import formal.model as M
    import formal.lean as L
    import formal.arm64_proof_gen as AP

    # FORMAL.md §3.2: the blob layout, and both architectures' budgets.
    check(M.BLOB_HEADER_BYTES == 8,
          f'BLOB_HEADER_BYTES is {M.BLOB_HEADER_BYTES}, the ABI §3.2 states is 8')
    check(M.ARM64_CONTAINER_BUDGET == 131072,
          f'ARM64_CONTAINER_BUDGET is {M.ARM64_CONTAINER_BUDGET}, FORMAL.md §3.2 '
          f'states 131072')
    check(M.X86_64_CONTAINER_BUDGET == 16384,
          f'X86_64_CONTAINER_BUDGET is {M.X86_64_CONTAINER_BUDGET}, FORMAL.md '
          f'§3.2 states 16384')
    check('_SCRATCH = ARM64_CONTAINER_BUDGET' in
          open(os.path.join(HERE, 'formal', 'arm64_codegen.py')).read().replace(
              'M.', ''),
          'arm64 _SCRATCH is the named budget, not a second literal')
    check('_BLOB_BYTES = X86_64_CONTAINER_BUDGET' in
          open(os.path.join(HERE, 'formal', 'x86_64_codegen.py')).read().replace(
              'M.', ''),
          'x86-64 _BLOB_BYTES is the named budget, not a second literal')
    check('131072' in text and '16384' in text,
          "FORMAL.md §3.2 publishes both budgets' values")

    # FORMAL.md §12: the launch policy. These four ARE the policy, and a
    # document that publishes a stale bound is worse than one that publishes
    # none -- an operator sizing a decision against it reads the wrong number.
    for name, want in (('PROOF_WALL_S', 1500), ('PROOF_CPU_S', 1500),
                       ('LIBRARY_WALL_S', 1800), ('LIBRARY_CPU_S', 1800)):
        got = getattr(L, name)
        check(got == want,
              f'formal/lean.py::{name} is {got}, FORMAL.md §12 publishes {want}')
        check(str(int(want)) in text,
              f'FORMAL.md §12 publishes {name} = {want}')
    check(L.LEAN_MEMORY_MB == 6144 and L.LIBRARY_MEMORY_MB == 12288,
          f'the Lean memory ceilings are {L.LEAN_MEMORY_MB} / '
          f'{L.LIBRARY_MEMORY_MB}, FORMAL.md §12 publishes 6144 / 12288')
    check('`-M 6144`' in text and '`-M 12288`' in text,
          'FORMAL.md §12 publishes both -M ceilings')
    check(L.LEAN_THREADS == 4 and '`-j 4`' in text,
          f'Lean runs with -j {L.LEAN_THREADS}, FORMAL.md §12 publishes -j 4')

    # §7 row 7: the CFG leaves that admit. Named in the document, and the
    # document says fifteen; the generator stamps each name into the Lean, so a
    # site added here is a site a reader is told about.
    check(len(AP.CFG_LEAF_SITES) == 15,
          f'CFG_LEAF_SITES has {len(AP.CFG_LEAF_SITES)} sites, FORMAL.md §7 row 7 '
          f'publishes fifteen')
    check('**fifteen named sites**' in text,
          "FORMAL.md §7 row 7 states the CFG_LEAF_SITES count as 'fifteen'")

    # §1: the runtime translation unit's size, which is the one figure in the
    # thesis paragraph and was 299 KB when written.
    size = os.path.getsize(os.path.join(HERE, 'runtime', 'fire_runtime.c'))
    kb = round(size / 1024)
    m = re.search(r'`runtime/fire_runtime\.c` \((\d+) KB\)', text)
    check(m is not None, 'FORMAL.md §1 publishes runtime/fire_runtime.c\'s size')
    check(m is not None and int(m.group(1)) == kb,
          f"FORMAL.md §1 says fire_runtime.c is {m and m.group(1)} KB, it is {kb} KB")

    # §12: the corpus the per-unit costs were measured over. It grows, and the
    # number a reader re-derives from `ls formal/examples/*.mojo` must match.
    n_examples = len(glob.glob(os.path.join(HERE, 'formal', 'examples', '*.mojo')))
    m = re.search(r'\*?\*?(\d+)\*?\*? `formal/examples/\*\.mojo`', text)
    check(m is not None, 'FORMAL.md §12 publishes the examples corpus size')
    check(m is not None and int(m.group(1)) == n_examples,
          f'FORMAL.md §12 says {m and m.group(1)} examples, there are {n_examples}')


# ── 3. the holes FORMAL.md struck, and the ones it must not re-publish ──────

def group_closed():
    """A row that names a trust boundary must name one that EXISTS.

    §7 is a table of what a proof currently rests on. Its first three rows named
    `lib/` holes that were closed in round 1 and had been for a week, which made
    the inventory -- the document's whole reason for existing -- assert three
    trusts the library does not have. The check is the inverse of a
    `test_suite.py` `expect=` anti-rot: a row that describes a hole with no hole
    under it is a reader being told something false in the same direction.

    The other direction matters too: a row that describes a hole which IS there
    must still be published, or the fix would be to delete inconvenient facts.
    So each row is checked against the tree, not against the document.
    """
    text = doc('FORMAL.md')
    lib = {f: open(os.path.join(HERE, 'lib', f), encoding='utf-8').read()
           for f in os.listdir(os.path.join(HERE, 'lib')) if f.endswith('.lean')}

    # A `sorry` in lib/ that is NOT inside a comment. The naive grep is what
    # made this hard to check: every mention of `sorry` in these files is prose
    # about `sorry`, so a text count reports 18 holes where there are none.
    def live_holes(src):
        out, in_block = [], False
        for i, line in enumerate(src.splitlines(), 1):
            code, rest = line, line
            if in_block:
                j = code.find('-/')
                if j < 0:
                    continue
                code, rest = '', code[j + 2:]
                in_block = False
            while True:
                a = code.find('/-')
                b = code.find('--')
                if a < 0 and b < 0:
                    break
                if a >= 0 and (b < 0 or a < b):
                    j = code.find('-/', a)
                    if j < 0:
                        in_block = True
                        code = ''
                        break
                    code = code[:a] + code[j + 2:]
                else:
                    code = code[:b] + code[b + 2:]
            if re.search(r'\bsorry\b|\badmit\b', code):
                out.append(i)
        return out

    holes = {f: live_holes(s) for f, s in sorted(lib.items())}
    total = sum(len(v) for v in holes.values())
    check(total == 0,
          f'lib/ has {total} live sorry/admit outside comments ({holes}), and '
          f"FORMAL.md §5 and §7 both rest on it having none")

    # The three rows §7 struck, by name. A struck row that stops being struck is
    # a hole re-published as live; a name that leaves the document entirely is
    # the row deleted rather than corrected, which is the same lie.
    for name, replacement in (
            ('in_image_stub', 'in_image_decide'),
            ('semantics_stub', 'Total'),
            ('dylib_export_contract_stub', 'export_result_spec')):
        m = re.search(r'^\|\s*\d+\s*\|\s*~~[^~]*`' + re.escape(name) + r'`[^~]*~~',
                      text, re.M)
        check(m is not None,
              f"FORMAL.md §7 keeps a STRUCK row for {name} rather than dropping it")
        check(replacement in text,
              f'FORMAL.md says what replaced {name} ({replacement})')

    # …and the extern step theorem. §3.1 and §7 row 6 both used to publish
    # `True := by trivial` as a live trust; it is a real obligation now, and the
    # premise that replaced it is named rather than silent.
    gen = open(os.path.join(HERE, 'formal', 'arm64_proof_gen.py'),
               encoding='utf-8').read()
    check('theorem extern_{sym}_step' in gen and 'by trivial' not in
          gen[gen.index('theorem extern_{sym}_step'):
              gen.index('theorem extern_{sym}_step') + 400],
          'the extern step theorem is not `True := by trivial` any more')
    check('_post_extern_given_callee_returns' in gen,
          "the post-extern premise is still emitted under its own name")
    check('**CLOSED**' in text,
          'FORMAL.md §7 row 6 records the extern step theorem as CLOSED')
    check('True := by trivial' in text,
          'FORMAL.md still names `True := by trivial` -- as what the theorem '
          'USED to be, which is the one context in which it is worth saying')

    # The observable list. `[]` made `Functional` vacuous again, which is the
    # defect `vacuous_declarations` cannot see because the definition is no
    # longer the vacuous one.
    check(re.search(r'def dylib_observables[^=]*:=\s*\[id\]', gen) is not None,
          'dylib_observables is `[id]`, not the empty list that made the clause '
          'vacuous')

    # The x86-64 side has NOT moved, so §3.1 must keep saying so. This is the
    # other direction, and it is the one that stops a "fix the doc" pass from
    # quietly deleting the two `sorry`s that are still there.
    x86 = open(os.path.join(HERE, 'formal', 'x86_64_proof_gen.py'),
               encoding='utf-8').read()
    check(len(re.findall(r'f"  sorry', x86)) >= 2,
          'the x86-64 generator still emits its two trust boundaries as `sorry`')
    check('unconditional `sorry`' in text,
          'FORMAL.md §3.1 still says the x86-64 side has not moved')

    # Phase 2's first coverage figure, the one that is CHEAP: how many entry
    # points are word-shaped. The other two of the triple -- how many the
    # runtime dylib exports, and how many of those need no heap handle -- need
    # the built library, and this file must not build it: a cold
    # `runtime_dylib()` compiles six translation units, so a file that looks
    # like import-and-compare would turn into a compile. They are checked where
    # the library is already built and already computed:
    # `test_formal_runtime_link.py`, which reports the same triple on every run.
    import formal.model as M
    word = {n for n, e in M.runtime_abi().items() if e['word']}
    check(len(word) == 262,
          f'{len(word)} word-shaped entry points, FORMAL.md §6 phase 2 publishes 262')
    m = re.search(r'\*\*(\d+) word-shaped calls are callable', text)
    check(m is not None,
          'FORMAL.md still publishes the callable-surface figure')
    check(int(m.group(1)) <= len(word),
          f"FORMAL.md publishes {m.group(1)} callable word-shaped calls out of "
          f'{len(word)} word-shaped')
    check('0 of the word-shaped calls are callable' not in flat(text),
          'FORMAL.md no longer publishes "0 of the word-shaped calls are callable"')

    # §3.4's count of link-accounting checks is not published: the number is
    # only knowable by running the audit, and a figure no test can check is a
    # figure that rots silently.
    check('83 checks' not in text,
          "FORMAL.md does not publish test_formal_link_accounting.py's check count")


# ── 4. every named claim resolves ──────────────────────────────────────────

#: `(document, the symbol the document names, the file it must be in)`.
#:
#: The line is deliberately NOT here. A citation that names a file and a symbol
#: is checkable; a citation that names a line is a claim about the tree's shape
#: at one instant, and ~250 merges have moved every line in it. `CITATION_LINES`
#: below carries the handful whose line number a reader would use to navigate,
#: with a window wide enough to survive an unrelated commit.
CITATIONS = [
    # FORMAL.md §2.1 -- the call machinery
    ('FORMAL.md', 'emit_extern_bl', 'formal/arm64.py'),
    ('FORMAL.md', 'resolve_extern', 'formal/arm64.py'),
    ('FORMAL.md', 'LIBSYSTEM_PATH', 'formal/macho_linker.py'),
    ('FORMAL.md', '_bind_info', 'formal/macho_linker.py'),
    ('FORMAL.md', 'build_macho_executable_extern', 'formal/macho_linker.py'),
    ('FORMAL.md', 'load_dylib_manifests', 'formal/build.py'),
    # §2.2 / §2.5 / §3.2 -- the ABI table and the refusal
    ('FORMAL.md', 'runtime_abi', 'formal/model.py'),
    ('FORMAL.md', 'runtime_abi_entry', 'formal/model.py'),
    ('FORMAL.md', 'gimple_runtime_refusal', 'formal/model.py'),
    ('FORMAL.md', 'gimple_runtime_callable', 'formal/model.py'),
    ('FORMAL.md', 'is_gimple_runtime_builtin', 'formal/model.py'),
    ('FORMAL.md', 'GIMPLE_RUNTIME_PREFIX', 'formal/model.py'),
    ('FORMAL.md', '_box_why', 'formal/model.py'),
    ('FORMAL.md', 'BLOB_HEADER_BYTES', 'formal/model.py'),
    ('FORMAL.md', 'ARM64_CONTAINER_BUDGET', 'formal/model.py'),
    ('FORMAL.md', 'X86_64_CONTAINER_BUDGET', 'formal/model.py'),
    ('FORMAL.md', 'collect_runtime_exports_h', 'reflect.py'),
    ('FORMAL.md', 'runtime_dylib', 'build_stdlib_dylib.py'),
    ('FORMAL.md', 'arch_flags', 'build_stdlib_dylib.py'),
    # §3.1 -- the proof side
    ('FORMAL.md', '_gen_extern_test', 'formal/arm64_proof_gen.py'),
    ('FORMAL.md', 'generate_dylib_proof', 'formal/arm64_proof_gen.py'),
    ('FORMAL.md', 'dylib_observables', 'formal/arm64_proof_gen.py'),
    ('FORMAL.md', 'total_of_halts', 'lib/ProofLib.lean'),
    ('FORMAL.md', 'arm64_step', 'lib/ProofLib.lean'),
    ('FORMAL.md', 'DylibExport', 'lib/ProofLib.lean'),
    ('FORMAL.md', 'x86_step_call_rel32', 'lib/X86.lean'),
    ('FORMAL.md', '_compile_correct_section', 'formal/x86_64_proof_gen.py'),
    # §3.3 / §3.4 -- the gimple premise and the provider registry
    ('FORMAL.md', '_OPTIONAL_RUNTIME_UNITS', 'build_config.py'),
    ('FORMAL.md', '_KNOWN_SIGS', 'gimple_codegen.py'),
    ('FORMAL.md', '_is_libsystem', 'formal/build.py'),
    ('FORMAL.md', '_unaccounted_report', 'formal/build.py'),
    # §4 -- the decisions
    ('FORMAL.md', 'shift_signedness', 'formal/model.py'),
    ('FORMAL.md', '_rewrite_with_statements', 'formal/build.py'),
    ('FORMAL.md', 'struct_is_context_manager', 'formal/model.py'),
    ('FORMAL.md', '_emit_try', 'formal/arm64_codegen.py'),
    ('FORMAL.md', '_emit_try', 'formal/x86_64_codegen.py'),
    # §7 / §7a -- the trust inventory and the admitted host contracts
    ('FORMAL.md', 'CFG_LEAF_SITES', 'formal/arm64_proof_gen.py'),
    ('FORMAL.md', 'contract_text_is_scoped', 'formal/admitted.py'),
    ('FORMAL.md', '_call_go', 'formal/arm64_proof_gen.py'),
    ('FORMAL.md', 'dylib_observables', 'formal/arm64_proof_gen.py'),
    # §11 / §12 -- the operating contract and the launch policy
    ('FORMAL.md', '_dylib_contract_proof', 'formal/arm64_proof_gen.py'),
    ('FORMAL.md', 'run_lean', 'formal/lean.py'),
    ('FORMAL.md', 'proof_census', 'formal/lean.py'),
    ('FORMAL.md', 'vacuous_declarations', 'formal/lean.py'),
    ('FORMAL.md', 'GENERATED_AXIOM_RE', 'formal/lean.py'),
    ('FORMAL.md', 'ensure_library', 'formal/lean.py'),
    # doc/ABI.md
    ('doc/ABI.md', 'optional_none_word', 'formal/model.py'),
    ('doc/ABI.md', 'optionalNoneWord', 'lib/ProofLib.lean'),
    ('doc/ABI.md', 'receiver_writeback_name', 'formal/model.py'),
    ('doc/ABI.md', '_allocation_split', 'formal/arm64_codegen.py'),
    ('doc/ABI.md', '_rewrite_self_fields', 'formal/build.py'),
    ('doc/ABI.md', 'mangle', 'monomorphize.py'),
    ('doc/ABI.md', 'library_free_edges', 'formal/imports.py'),
    ('doc/ABI.md', '_func_csym', 'gimple_codegen.py'),
    ('doc/ABI.md', 'overload_suffix_for', 'gimple_codegen.py'),
    ('doc/ABI.md', '_method_overload_id', 'gimple_codegen.py'),
    ('doc/ABI.md', 'module_name_for_path', 'module_loader.py'),
    ('doc/ABI.md', 'collect_exports', 'reflect.py'),
    ('doc/ABI.md', '_struct_method_qualifier', 'gimple_codegen.py'),
    ('doc/ABI.md', 'library_free_edges', 'formal/imports.py'),
    ('doc/ABI.md', 'imported_callee_refusal', 'formal/model.py'),
    ('doc/ABI.md', 'no_public_api_reason', 'formal/build.py'),
    ('doc/ABI.md', 'library_free_edges', 'formal/imports.py'),
    # OPUS.md
    ('OPUS.md', 'total_of_halts', 'lib/ProofLib.lean'),
    ('OPUS.md', 'exportFuel', 'lib/ProofLib.lean'),
    ('OPUS.md', '_gen_universal_e2e_cfg', 'formal/arm64_proof_gen.py'),
    ('OPUS.md', '_dylib_total_proof', 'formal/arm64_proof_gen.py'),
    ('OPUS.md', '_dylib_spec_lean', 'formal/arm64_proof_gen.py'),
    ('OPUS.md', '_tw_defs', 'formal/arm64_proof_gen.py'),
    ('OPUS.md', 'LIBRARY_MODULES', 'formal/lean.py'),
    ('OPUS.md', 'frameBound_descend', 'lib/Refine.lean'),
]

#: Citations whose LINE number a reader would use to navigate. Each entry is
#: `(document, the citation exactly as the document spells it, the file it is in,
#: the symbol the line is cited FOR)`.
#:
#: The symbol is per citation rather than per file on purpose. The first version
#: of this check paired a document with a file and a symbol and then searched for
#: the FIRST `file:line` in the document -- so `runtime/fire_runtime.h:164-165`
#: (the `setjmp` note) was checked against `mojo_raise`, which is at line 520, and
#: five rows failed for one reason: the pairing was wrong, not the document.
#:
#: The window is 8 lines, not 60. These are citations a reader is expected to
#: navigate to, and the reason the broader `CITATIONS` list tolerates a large
#: window is that most of its entries carry no line at all.
CITATION_LINES = [
    ('FORMAL.md', 'runtime/fire_python.c:7', 'runtime/fire_python.c', 'USE_PYTHON'),
    ('FORMAL.md', 'runtime/fire_sqlite3.c:156-157', 'runtime/fire_sqlite3.c',
     'int64_t'),
    ('doc/ABI.md', 'runtime/fire_runtime.h:512', 'runtime/fire_runtime.h',
     'setjmp is emitted directly'),
    ('doc/ABI.md', 'runtime/fire_runtime.h:513', 'runtime/fire_runtime.h',
     'no setjmp, safe to wrap'),
    ('doc/ABI.md', 'runtime/fire_runtime.h:520', 'runtime/fire_runtime.h',
     'void mojo_raise'),
    ('doc/ABI.md', 'runtime/fire_runtime.h:532-534', 'runtime/fire_runtime.h',
     'mojo_exc_type_get'),
    ('doc/ABI.md', 'runtime/fire_runtime.h:606-608', 'runtime/fire_runtime.h',
     'mojo_exc_pending_get'),
    ('doc/ABI.md', 'runtime/fire_runtime.h:579-604', 'runtime/fire_runtime.h',
     '_mojo_exc_pending'),
]


def _lines_of(path):
    return open(os.path.join(HERE, path), encoding='utf-8',
                errors='replace').read().splitlines()


def group_citations():
    """Every name these three documents publish must still resolve.

    This is the check that would have caught FORMAL.md §2.5 naming a
    `GIMPLE_LIST_PREFIX` that was deleted in the very change that generalised it,
    and §2.3 saying the formal linker "is not told about" a library it now links.
    Both were true sentences about a tree that no longer existed, and neither
    had an instrument.
    """
    docs = {n: doc(n) for n in ('FORMAL.md', 'doc/ABI.md', 'OPUS.md')}
    cache = {}

    def src(path):
        if path not in cache:
            cache[path] = _lines_of(path)
        return cache[path]

    for document, symbol, path in CITATIONS:
        check(os.path.exists(os.path.join(HERE, path)),
              f'{document} names {path}, which exists')
        if f'`{symbol}`' not in docs[document] and symbol not in docs[document]:
            check(False, f'{document} still names `{symbol}`',
                  'the claim was dropped rather than corrected')
            continue
        check(any(symbol in ln for ln in src(path)),
              f'{document} names `{symbol}`, which is in {path}')

    # Line numbers, with a small window, paired per citation.
    for document, citation, path, symbol in CITATION_LINES:
        check(citation in docs[document],
              f'{document} still cites {citation}',
              'the citation was rewritten rather than re-pointed')
        first = int(re.search(r':(\d+)', citation).group(1))
        last = first
        m = re.search(r'-(\d+)$', citation)
        if m:
            last = int(m.group(1))
        hits = [i for i, ln in enumerate(src(path), 1) if symbol in ln]
        check(bool(hits), f'{citation} names `{symbol}`, which {path} has')
        near = [h for h in hits if first - 2 <= h <= last + 2]
        check(bool(near),
              f'{document}:{citation} — `{symbol}` is inside the cited range in '
              f'{path}', f'it is at {hits[:4]}')

    # The names these documents promise are GONE must not be presented as live.
    # `GIMPLE_LIST_PREFIX` is the standing case.
    check('GIMPLE_LIST_PREFIX' in docs['FORMAL.md'],
          'FORMAL.md still explains what GIMPLE_LIST_PREFIX was')
    model = '\n'.join(src('formal/model.py'))
    check('GIMPLE_LIST_PREFIX' not in model.replace(
              '# This is the generalisation of the `GIMPLE_LIST_PREFIX` special '
              'case that\n# stood here before, and that constant is gone', ''),
          'GIMPLE_LIST_PREFIX is not a live constant in formal/model.py')

    # §10's "the duplication is closed" claim, in both directions: one `def` per
    # name in both files. This is the rule, not the one-off cleanup, and a copy
    # re-introduced by a merge is the exact failure §10 described.
    for path in ('formal/model.py', 'formal/arm64_proof_gen.py'):
        names = [ln.split('def ', 1)[1].split('(')[0].strip()
                 for ln in src(path) if ln.startswith('def ')]
        dups = sorted({n for n in names if names.count(n) > 1})
        check(not dups, f'{path} defines every top-level function once',
              f'duplicated: {dups}')
    check('~~**A duplicated block in `formal/arm64_proof_gen.py`.**~~' in
          docs['FORMAL.md'],
          'FORMAL.md §10 keeps the duplication bullet STRUCK rather than '
          'deleting it')


# ── 5. doc/ABI.md's boundary rows ──────────────────────────────────────────

#: `(name, return type as doc/ABI.md states it)`, from the exception-handling
#: and cleanup-thunk sections. A C client writes its declaration against these,
#: so a row that names a symbol the header does not declare sends it looking for
#: something that does not exist -- which is the failure mode this file's own
#: header says about the `mojo_try_push` macro it removed.
ABI_ENTRY_POINTS = {
    'mojo_exc_pop': 'void',
    'mojo_raise': 'void',
    'mojo_exc_msg_set': 'void',
    'mojo_exc_msg_get': 'char *',
    'mojo_exc_obj_set': 'void',
    'mojo_exc_obj_get': 'void *',
    'mojo_exc_type_set': 'void',
    'mojo_exc_type_get': 'int64_t',
    'mojo_cleanup_push_dict': 'void',
    'mojo_cleanup_push_list': 'void',
    'mojo_cleanup_push_set': 'void',
    'mojo_cleanup_push_dict_stack': 'void',
    'mojo_cleanup_push_list_stack': 'void',
    'mojo_cleanup_push_set_stack': 'void',
    'mojo_cleanup_push_ptr': 'void',
    'mojo_cleanup_push_list_strs': 'void',
    'mojo_cleanup_push_closure': 'void',
    'mojo_cleanup_cancel_n': 'void',
    'mojo_cleanup_checkpoint_save': 'void',
    'mojo_exc_pending_set': 'void',
    'mojo_exc_pending_get': 'int',
}

#: The `Optional[T]` niche table, from doc/ABI.md's own rows. `(payload,
#: expected)` where `expected` is the niche word or `None` for a refusal. This is
#: the one part of ABI.md that is a *computation* rather than a layout, so it is
#: the part that can be wrong without anybody noticing until a program takes the
#: empty branch on `Some(0)`.
ABI_OPTIONAL_NICHES = [
    ('String', 0), ('str', 0), ('Pointer[Int]', 0), ('List[Int]', 0),
    ('Dict[str, Int]', 0),
    ('Bool', 2),
    ('Int8', 256), ('Int16', 65536), ('Int32', 4294967296),
    ('UInt8', 256), ('UInt16', 65536), ('UInt32', 4294967296),
    ('Int', None), ('Int64', None), ('UInt', None), ('UInt64', None),
    ('Float64', None), ('Float32', None), ('DType', None),
    ('MyStruct', None),
]


def group_abi():
    """doc/ABI.md's rows against the header they describe."""
    import formal.model as M
    text = doc('doc/ABI.md')
    hdr = '\n'.join(_lines_of('runtime/fire_runtime.h'))
    exports = {e['name'] for e in
               __import__('reflect').collect_runtime_exports_h(
                   os.path.join(HERE, 'runtime', 'fire_runtime.h'))}

    for name, ret in sorted(ABI_ENTRY_POINTS.items()):
        m = re.search(r'^[A-Za-z_][\w \*]*\b' + re.escape(name) + r'\s*\(',
                      hdr, re.M)
        check(m is not None,
              f'doc/ABI.md names {name}, which runtime/fire_runtime.h declares')
        if m is not None:
            decl = m.group(0).rstrip('(').strip()
            actual = ' '.join(decl[:decl.index(name)].split())
            check(actual == ret,
                  f'{name} returns {ret} as doc/ABI.md states',
                  f'the header says {actual!r}')
        check(name in exports,
              f'{name} is an exported symbol, not a static inline helper')
        # …and it is DOCUMENTED. Without this the ABI group passed a document
        # that had renamed a symbol out from under it: the header and this file's
        # table still agreed, so every other row was green.
        check(re.search(r'`' + re.escape(name) + r'(?![A-Za-z_0-9])', text)
              is not None,
              f'doc/ABI.md still documents {name} by name')

    # Both directions on the registry: a push family added to the runtime must
    # fail here rather than going undocumented.
    #
    # `documents` expands the document's OWN shorthand -- `doc/ABI.md` writes a
    # family as `` `mojo_cleanup_push_dict` / `_list` / `_set` `` -- because a
    # substring test passes the first member of every family and fails the rest,
    # which would report four undocumented entry points that are documented.
    # A backticked span is a SIGNATURE as often as a bare name -- the document
    # writes `mojo_cleanup_push_ptr(void *p)` as readily as `mojo_cleanup_push_n`
    # -- so "written" is a backticked span that STARTS with the name.
    #
    # And a family is written as a slash-list of SEPARATE backticked spans,
    # `head` / `_tail` / `_tail`, so the expansion has to run over the raw text
    # rather than over one span: splitting a single span on `/` finds
    # `formal`/`model.py` and nothing else, because each member of the list is its
    # own span. Expanding by the first item's own prefix-up-to-last-underscore is
    # also what makes `mojo_cleanup_push_list_stack` documented -- the list is
    # `mojo_cleanup_push_dict_stack` / `_list_stack` / `_set_stack`, whose shared
    # prefix is `mojo_cleanup_push_`. A per-item tail test reports that family
    # undocumented, because the head it compares against is the non-stack one.
    written = re.compile(r'`' + r'([A-Za-z_]\w*)' + r'`(?:\s*/\s*`_\w+`)+')

    def documents(name):
        if re.search(r'`' + re.escape(name) + r'(?![A-Za-z_0-9])', text):
            return True
        # `findall` would return only the HEAD (the pattern has one group), so
        # the tails would be invisible and every family below it undocumented --
        # which is what the first version of this helper did.
        for m in written.finditer(text):
            parts = [part.strip('`') for part in
                     re.split(r'\s*/\s*', m.group(0))]
            head, tails = parts[0], parts[1:]
            # `strip('`')` and not a `split` on the raw text: the head arrives as
            # `` `mojo_cleanup_push_dict` `` WITH its backticks, so an unstripped
            # `rpartition` takes `` `mojo_cleanup_push `` as the shared prefix and
            # nothing below it can match.
            prefix = head.rpartition('_')[0]
            if not prefix:
                continue
            for tail in tails:
                if prefix + '_' + tail.lstrip('_') == name:
                    return True
        return False

    declared = set(re.findall(r'^[A-Za-z_][\w \*]*\b(mojo_cleanup_\w+)\s*\(',
                              hdr, re.M))
    check(declared <= set(ABI_ENTRY_POINTS),
          'every cleanup entry point in the header is one this file checks',
          f'unlisted: {sorted(declared - set(ABI_ENTRY_POINTS))}')
    for name in sorted(declared):
        check(documents(name),
              f'doc/ABI.md documents the cleanup entry point {name}')

    # The library container types.
    for mojo, ctype in (('String', 'char *'), ('List', 'MojoList *'),
                        ('Dict', 'MojoDict *'), ('Set', 'MojoSet *'),
                        ('Str', 'MojoStr *')):
        check(f'`{ctype}`' in text,
              f"doc/ABI.md's container table still maps a Mojo type to {ctype}")
    for struct in ('MojoList', 'MojoStr', 'MojoDict', 'MojoSet'):
        check(re.search(r'^\}\s*' + struct + r';', hdr, re.M) is not None,
              f'{struct} is a struct in runtime/fire_runtime.h, as the table says')

    # The Optional niche table, computed.
    for payload, want in ABI_OPTIONAL_NICHES:
        got, why = M.optional_none_word(payload, {})
        check(got == want,
              f'doc/ABI.md: the `None` word for Optional[{payload}] is {want}',
              f'model says {got!r} ({why and why[:60]})')
    check('optional_none_word' in text and 'optionalNoneWord' in text,
          'doc/ABI.md names both halves of the niche, python and Lean')
    check('optionalNoneWord' in '\n'.join(_lines_of('lib/ProofLib.lean')),
          'lib/ProofLib.lean really does mirror it as optionalNoneWord')

    # `Span` is still a hardcoded model in the lowering and NOT a header struct.
    # If that ever becomes true, this document's caveat must go with it -- which
    # is why the direction that matters here is the header.
    check('struct Span' not in hdr,
          'doc/ABI.md still says `Span` is not a `struct Span` in the runtime '
          'header (it is not)')
    check('Span *' in text,
          "doc/ABI.md still has the `Span *` row, flagged as not yet usable")


# ── 6. OPUS.md's two claims about the library and the fuel ──────────────────

def group_opus():
    """OPUS.md is a hand-off document, and two of its claims are load-bearing.

    It is a narrative of one agent's work, so most of it is history and history
    is not this file's business. What IS this file's business is the handful of
    present-tense claims about the tree: the fuel's arithmetic, and the library
    registration that was a blocker and then was not.
    """
    text = doc('OPUS.md')
    import formal.lean as L
    lib = '\n'.join(_lines_of('lib/ProofLib.lean'))
    gen = '\n'.join(_lines_of('formal/arm64_proof_gen.py'))

    check('Contracts' in L.LIBRARY_MODULES,
          "OPUS.md says lib/Contracts.lean is registered in LIBRARY_MODULES",
          f'LIBRARY_MODULES is {L.LIBRARY_MODULES}')
    check('`lib/Contracts.lean`' in text
          and '**The blocker that was here is gone.**' in text,
          'OPUS.md §5.2 states the registration blocker as CLOSED')
    check('LIBRARY_MODULES` is still' not in text,
          "OPUS.md §5.2 no longer says LIBRARY_MODULES 'is still' missing the "
          'module it says is registered two sentences later')

    # The fuel. `exportFuel` is the definition `Total` is stated over, so its
    # shape is a contract, and §5.7's whole lesson is that hiding it behind a
    # function is what broke the walk.
    check(re.search(r'def exportFuel[\s\S]{0,80}?:\s*Nat\s*:=\s*\n\s*200000 \+ '
                    r'\(image\.codeSize / 4\) \* n\.toNat', lib) is not None,
          "OPUS.md's `exportFuel` is the library's")
    check(re.search(r'_EXPORT_FUEL_BASE = 200000', gen) is not None,
          "the generator's fuel base is 200000, as OPUS.md §5.7 records")
    check('never fires in practice — `exportFuel` is 100000' not in flat(text),
          "OPUS.md §5.0 no longer states exportFuel's size in the present tense")
    check('it said "`exportFuel` is 100000"' in flat(text),
          'OPUS.md §5.0 records the stale sentence it corrected, as history')

    # §1's four conditions on the walk, since §1 published two and two of the
    # four are silent.
    body = gen[gen.index('def _gen_universal_e2e_cfg'):]
    body = body[:body.index('\ndef ')]
    for clause, snippet, said in (
            ('recursive', 'if (recursive or not _acyclic',
             '**not recursive**'),
            ('acyclic', '_acyclic = all(', '**acyclic**'),
            ('no `bl`', 'b["kind"] == "bl"', 'no `bl` block'),
            ('a `fuel` at or above the instruction count', 'fuel < _TOTAL',
             'a `fuel` at or above the instruction count')):
        check(snippet in body,
              f"the walk's `{clause}` exclusion is in the generator, as OPUS.md §1 says")
        check(said in text, f'OPUS.md §1 names the `{clause}` exclusion')


GROUPS = {
    'census': group_census,
    'constants': group_constants,
    'closed': group_closed,
    'citations': group_citations,
    'abi': group_abi,
    'opus': group_opus,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('-v', '--verbose', action='store_true')
    ap.add_argument('groups', nargs='*', choices=[*GROUPS, []], default=[])
    args = ap.parse_args()
    todo = args.groups or list(GROUPS)
    for name in todo:
        before = len(RESULTS)
        try:
            GROUPS[name]()
        except Exception as e:                      # report, do not mask
            check(False, f'group {name} raised',
                  f'{type(e).__name__}: {e}')
            if args.verbose:
                import traceback
                traceback.print_exc()
        print(f"  {name}: {len(RESULTS) - before} checks")

    npass = sum(1 for ok, _w in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\ndoc truth: PASS={npass} FAIL={nfail}")
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())