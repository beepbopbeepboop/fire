#!/usr/bin/env python3
"""The tool's own name: what `fire.py` calls itself in usage, version and errors.

Why this file exists
--------------------
`fire.py` was renamed from `mojo.py`, and the rename stopped at the filename.
Every string the tool printed about ITSELF still said `mojo`: `fire.py --help`
advertised `mojo build <file.mojo>`, `fire.py -v` printed `mojo <sha>`, and each
usage error was prefixed `mojo:`/`mojo build:`. A name a user cannot type is
worse than no name, because the help is what they copy from.

The rule under test is one sentence — *the tool prints the name it was invoked
as* — because this one program is three commands: `python3 fire.py` (the
script), `./mojoc` (the one-step self-host build) and `stage2/mojo` (the
bootstrap stage binaries, compiled from this same file). Spelling any single
one of those names into the text makes the other two lie; reading argv[0]
cannot. The tests below therefore check the name tracks the invocation, not
that it equals one particular string.

The companion rule is equally load-bearing and equally easy to break by
accident: this is the CLI's name, NOT the language's. `.mojo` files, the
`mojo` stdlib, `mojo_*` runtime symbols and the word "Mojo" all stay exactly
as they are, and `test_language_names_are_not_renamed` says so out loud.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')
TIMEOUT = 120


def _run(args, argv0=None, timeout=TIMEOUT):
    """Run the CLI; return (ok, stdout, stderr, exit code).

    `argv0` re-spells the invocation without moving the file: it runs
    `python3 -c "import fire; fire.main()"` with sys.argv[0] set, which is the
    only way to ask "what does it print when it is NOT called fire.py?" without
    copying fire.py somewhere its imports stop resolving.
    """
    if argv0 is None:
        argv = [sys.executable, FIRE] + list(args)
    else:
        quoted = ', '.join(repr(a) for a in [argv0] + list(args))
        argv = [sys.executable, '-c',
                f'import sys; sys.argv = [{quoted}]\nimport fire; fire.main()']
    env = dict(os.environ, PYTHONPATH=HERE)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, cwd=HERE,
                           env=env, errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, '', f'TIMEOUT after {timeout}s', None
    return True, r.stdout, r.stderr, r.returncode


def _usage_lines(stdout):
    """The COMMAND lines in the `Usage:` block.

    Only lines indented by exactly two spaces are commands; the deeper
    indentation is a wrapped description continuing the line above it, and
    those never name the tool.
    """
    out, inside = [], False
    for line in stdout.splitlines():
        if not inside:
            inside = line.strip() == 'Usage:'
            continue
        if not line.strip():
            break
        if re.fullmatch(r'  \S.*', line):
            out.append(line)
    return out


def test_help_names_the_invoked_tool():
    """`--help`, `-h` and `help` all name the tool, and name it completely."""
    for flag in ('--help', '-h', 'help'):
        ok, out, err, rc = _run([flag])
        if not ok or rc != 0:
            return False, f'`fire.py {flag}` exited {rc}: {err.strip()[:200]}'
        lines = _usage_lines(out)
        if len(lines) < 15:
            return False, (f'`fire.py {flag}` printed {len(lines)} usage lines, '
                           f'expected the full mode list')
        for line in lines:
            cmd = line.split()[0]
            if cmd != 'fire':
                return False, f'`fire.py {flag}` usage line names {cmd!r}: {line!r}'
    return True, 'every usage line starts with the tool name it was run as'


def test_help_under_another_name_follows_argv():
    """Invoked as something else, the help says that — the rule, not a constant."""
    for alias in ('spark', 'mojoc'):
        ok, out, err, rc = _run(['--help'], argv0=alias)
        if not ok or rc != 0:
            return False, f'alias {alias}: exited {rc}: {err.strip()[:200]}'
        lines = _usage_lines(out)
        if not lines:
            return False, f'alias {alias}: no Usage: block'
        for line in lines:
            cmd = line.split()[0]
            if cmd != alias:
                return False, (f'alias {alias}: usage line names {cmd!r} '
                               f'instead: {line!r}')
    return True, 'usage follows argv[0] (spark, mojoc) — no hardcoded name'


def test_help_still_lists_every_mode():
    """The name fix must not quietly cost a mode: this is the one real list."""
    ok, out, err, rc = _run(['--help'])
    if not ok or rc != 0:
        return False, f'`--help` exited {rc}: {err.strip()[:200]}'
    text = out
    required = [
        'repl', 'run <file.mojo>', 'build <file.mojo>', 'build -o <output>',
        'dylib <file.mojo>', 'dylib -o <out>', 'dylib --formal',
        '--jit', '--formal', '--no-prove', '--backend=arm64', '--backend=gimple',
        '--dump <file.mojo>', '--dump-full <file.mojo>',
        '-v, --version', '-h, --help',
    ]
    missing = [m for m in required if m not in text]
    if missing:
        return False, f'usage text lost: {missing}'
    return True, f'all {len(required)} modes/flags present'


def test_version_names_the_tool():
    """`-v` prints `<tool> <version>`; the version itself is unchanged."""
    for flag in ('-v', '--version', 'version'):
        ok, out, err, rc = _run([flag])
        if not ok or rc != 0:
            return False, f'`fire.py {flag}` exited {rc}: {err.strip()[:200]}'
        first = out.split()[0] if out.split() else ''
        if first != 'fire':
            return False, f'`fire.py {flag}` printed {first!r}, expected it to start with "fire"'
    return True, '-v/--version/version all print "fire <version>"'


def test_error_messages_name_the_tool():
    """Every usage error is prefixed with the tool, on the same exit code."""
    cases = [
        (['build', 'x.mojo', '--link-dylib'], 'fire build:'),
        (['dylib'], 'fire dylib:'),
        (['dylib', '--formal', '-n', '3', 'x.mojo'], 'fire dylib --formal:'),
        (['formalbuild', 'x.mojo'], 'fire formalbuild:'),
        (['-n'], 'fire:'),
        (['--formal', '-n', 'abc', 'x.mojo'], 'fire:'),
    ]
    for args, prefix in cases:
        ok, out, err, rc = _run(args)
        if not ok:
            return False, f'`fire.py {" ".join(args)}`: {err}'
        first = err.strip().splitlines()[0] if err.strip() else ''
        if not first.startswith(prefix):
            return False, (f'`fire.py {" ".join(args)}` stderr starts {first!r}, '
                           f'expected {prefix!r}')
        if rc == 0:
            return False, f'`fire.py {" ".join(args)}` exited 0 on a usage error'
    return True, f'{len(cases)} usage errors all name the tool'


def test_language_names_are_not_renamed():
    """The CLI's name is ours; the language's is not.

    Three places the word "Mojo" legitimately survives, and would be collateral
    damage from a rename that went looking for every occurrence: the `.mojo`
    extension in the usage text and in the dylib error, the REPL banner, and
    the `mojo_*` runtime symbol namespace in fire.py's own source.
    """
    ok, out, err, rc = _run(['--help'])
    if not ok:
        return False, err
    for needed in ('<file.mojo>', '--dump <file.mojo>'):
        if needed not in out:
            return False, f'usage text no longer mentions {needed!r}'
    ok, out, err, rc = _run(['dylib'])
    if not ok or '.mojo file is required' not in err:
        return False, f'dylib error lost the .mojo extension: {err.strip()[:200]!r}'
    # The REPL banner names the language, not the command.
    r = subprocess.run([sys.executable, '-c', 'import fire; fire.run_repl()'],
                       capture_output=True, text=True, cwd=HERE, stdin=subprocess.DEVNULL,
                       env=dict(os.environ, PYTHONPATH=HERE), timeout=TIMEOUT)
    if 'Mojo REPL' not in r.stdout:
        return False, f'REPL banner lost the language name: {r.stdout[:120]!r}'
    with open(FIRE) as f:
        src = f.read()
    if not re.search(r'\bmojo_\w+', src) or 'MOJO_NO_SHIM' not in src:
        return False, 'the mojo_* runtime symbol namespace is gone from fire.py'
    return True, '.mojo extension, Mojo REPL banner and mojo_* symbols all intact'


def test_no_hardcoded_tool_name_left_in_source():
    """Tripwire for the exact regression: a print literal that starts `mojo`.

    Narrow on purpose — it matches only a `print(` whose first argument string
    begins with the bare tool name, so `mojo_sqlite3_open`, `<file.mojo>` and
    `~/.gmojo/...` in unrelated messages cannot trip it.
    """
    with open(FIRE) as f:
        src = f.read()
    bad = re.findall(r'print\(\s*f?"mojo[ :][^"]*"', src)
    if bad:
        return False, f'fire.py still prints a hardcoded tool name: {bad[:3]}'
    return True, 'no print() literal names the tool as mojo'


def main():
    print('=' * 68)
    print('CLI SELF-NAME — fire.py usage/version/error text')
    print('=' * 68)
    tests = [
        test_help_names_the_invoked_tool,
        test_help_under_another_name_follows_argv,
        test_help_still_lists_every_mode,
        test_version_names_the_tool,
        test_error_messages_name_the_tool,
        test_language_names_are_not_renamed,
        test_no_hardcoded_tool_name_left_in_source,
    ]
    npass = nfail = 0
    for t in tests:
        try:
            ok, detail = t()
        except Exception as e:
            ok, detail = False, f'{type(e).__name__}: {e}'
        print(f'{"PASS" if ok else "FAIL"}  {t.__name__}: {detail}')
        npass += ok
        nfail += not ok
    print()
    print(f'Results: {npass} passed, {nfail} failed')
    sys.exit(0 if nfail == 0 else 1)


if __name__ == '__main__':
    main()
