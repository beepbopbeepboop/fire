#!/usr/bin/env python3
"""fire.py --dump-full reports a weak "unavailable in compiled mode" stub
in the artifact it writes.

A bootstrap gate (`bootstrap-stage1-transitive`) requires every function that
`fire.py` to carry no `unavailable in compiled mode` stub, and
`bootstrap_stage2_compiles()` in `tools/suite.py` fails on the pattern
`reject=CLOSURE_INCOMPLETE`. But that regex reads the CHILD'S OUTPUT, and
`dump_full` wrote the offending `.ci` to disk and exited 0 while printing
only `✓ Generated prog.ci` to stderr — the stub lived in the file, nowhere in
the output, so the job could pass while the closure was not clean. The dump
itself must say so.

Two cases, each running a real `--dump-full` into a throwaway build dir:

  - a source whose call lowers to nothing the GIMPLE path can emit (here
    `locals()`) dumps a `.ci` that DOES carry the stub, and the dump MUST
    report it — the very signal the job reads.
  - a plain, fully-lowered source dumps a `.ci` with no such stub, and the
    dump must say nothing of the kind.

Run: python3 test_dump_full_reports_closure_stubs.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')
sys.path.insert(0, HERE)
from fire import closure_has_stub_definition  # noqa: E402
PHASE = 'unavailable in compiled mode'

# `locals()` is one of the builtins the GIMPLE path cannot lower at all, so a
# call to it always degrades to the weak stub the gate is meant to catch.
STUBBY = (
    'def f(x):\n'
    '    d = locals()\n'
    '    return x\n'
    '\n'
    'print(f(1))\n'
)
CLEAN = (
    'def f(x):\n'
    '    y = x + 1\n'
    '    return y\n'
    '\n'
    'print(f(1))\n'
)
# The phrase as DATA, not as a stub: it lands in the artifact's string pool
# (`_slit_N`), not in a stub definition, and nothing calls a stub here. This is
# the shape of the compiler's own fire.py, which spells the phrase out to test
# for it, so a closure that contains that file must not be reported.
LITERAL = (
    'MSG = "unavailable in compiled mode"\n'
    '\n'
    'print(len(MSG))\n'
)


def _dump(root: str, src: str):
    td = tempfile.mkdtemp(dir=root)
    path = os.path.join(td, 'prog.mojo')
    with open(path, 'w') as f:
        f.write(src)
    r = subprocess.run(
        [sys.executable, FIRE, '--dump-full', path],
        cwd=td, capture_output=True, text=True, timeout=120)
    out = (r.stdout or '') + (r.stderr or '')
    ci = os.path.join(td, 'prog.ci')
    with open(ci) as f:
        body = f.read()
    return r, out, body, td


def test_stub_in_artifact_is_reported():
    root = os.path.join(HERE, 'build', 'test_dump_full_reports_closure_stubs')
    os.makedirs(root, exist_ok=True)
    r, out, ci, td = _dump(root, STUBBY)
    try:
        assert r.returncode == 0, (
            f'--dump-full failed ({r.returncode}); output:\n{out}')
        assert PHASE in ci, (
            'the fixture did not emit the weak stub this test is about, so '
            'the case would pass vacuously; artifact:\n' + ci[-2000:])
        assert PHASE in out, (
            '--dump-full wrote a .ci carrying an unavailable stub and said '
            'nothing about it, so the job\'s reject=CLOSURE_INCOMPLETE cannot '
            'see it; output was:\n' + out)
        assert 'prog.ci' in out, (
            'the report does not name the artifact it is about; output was:\n'
            + out)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_clean_artifact_is_quiet():
    root = os.path.join(HERE, 'build', 'test_dump_full_reports_closure_stubs')
    os.makedirs(root, exist_ok=True)
    r, out, ci, td = _dump(root, CLEAN)
    try:
        assert r.returncode == 0, (
            f'--dump-full failed ({r.returncode}); output:\n{out}')
        # The phrase may appear as TEXT in a closure (fire.py's own literals
        # land in its string pool), so the guard is on a stub DEFINITION: the
        # clean fixture must not emit one, or the quiet run is not a quiet run.
        assert not closure_has_stub_definition(ci), (
            'the clean fixture emitted a stub, which would make the quiet run '
            'indistinguishable from the reported one; artifact:\n' + ci[-2000:])
        assert PHASE not in out, (
            '--dump-full reported a stub for a closure that has none; output '
            'was:\n' + out)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_detector_matches_each_stub_shape():
    # Every stub shape an emitter writes is one `__attribute__((weak))` line
    # whose body is `mojo_print ((char *)"<name>: unavailable ...`. The plain
    # shape and the `(void)_self;` method shape are both real stubs.
    plain = ('__attribute__((weak)) int64_t items (...) { mojo_print ((char *)'
             '"items: ' + PHASE + '"); return (int64_t)0; }')
    method = ('__attribute__((weak)) int64_t Foo_bar (Foo *_self, ...) '
              '{ (void)_self; mojo_print ((char *)"Foo.bar: ' + PHASE + ' '
              '(inherited from an unmodeled base class)"); return (int64_t)0; }')
    assert closure_has_stub_definition(plain + '\n')
    assert closure_has_stub_definition('#ifndef G\n' + method + '\n#endif\n')


def test_detector_ignores_text_that_is_not_a_stub():
    # The phrase as a string-pool entry (`_slit_N`, how this file's own
    # literals reach a closure) and inside a docstring is text, not a stub.
    slit = 'static char * _slit_14828 = ": ' + PHASE + ' (imported ...";'
    doc = '    `__attribute__((weak)) \\"' + PHASE + '\\"` stub for it'
    assert not closure_has_stub_definition(slit + '\n' + doc + '\n')
    assert not closure_has_stub_definition('')


def test_phrase_as_string_literal_is_quiet():
    root = os.path.join(HERE, 'build', 'test_dump_full_reports_closure_stubs')
    os.makedirs(root, exist_ok=True)
    r, out, ci, td = _dump(root, LITERAL)
    try:
        assert r.returncode == 0, (
            f'--dump-full failed ({r.returncode}); output:\n{out}')
        assert PHASE in ci, (
            'the fixture did not put the phrase in the artifact, so the case '
            'would pass vacuously; artifact:\n' + ci[-2000:])
        assert PHASE not in out, (
            '--dump-full reported a stub for a string literal that is not a '
            'stub; output was:\n' + out)
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    test_stub_in_artifact_is_reported()
    test_clean_artifact_is_quiet()
    test_detector_matches_each_stub_shape()
    test_detector_ignores_text_that_is_not_a_stub()
    test_phrase_as_string_literal_is_quiet()
    print('PASS')
