# `test_cli_usage_text.py` is registered by nothing, so `suite-self-test` is RED

Found 2026-09-29 while fixing the suite tally (`tools/suite.py`'s dropped
TIMEOUT). Not fixed here: the fix is a registration, and registration is
integrator-owned — see the last section.

## What I ran

    python3 test_suite.py

## What I saw

    FAIL  the estate: every test file is run by something, or says why not:
          not run by any registered spec and not in UNREGISTERED: test_cli_usage_text.py
          the estate: 84 test files, 52 of them run by a registered spec,
          33 declared with a reason, 1 undeclared
    Results: 120 passed, 1 failed

and, as a real run through the runner:

    $ python3 tools/suite.py smoke -j2
      FAIL     suite-self-test  (18s)  exit 1
    suite: 1 passed, 1 failed, 0 skipped  (2 tests, 2 jobs, ...)

`suite-self-test` is a member of `check`, so this is a RED `check` on `master`
— not a hypothetical. The test file itself is fine and fast:

    $ python3 test_cli_usage_text.py
    Results: 7 passed, 0 failed        # 4.4 s

## What I expected

`test_cli_usage_text.py` was added by `851082d` ("test_cli_usage_text.py: the
CLI's self-name, and the split with the language") with a spec registration, or
with an `UNREGISTERED` entry saying why not. The estate check that exists
precisely to notice this is red instead, and the whole point of that check —
CLAUDE.md's "an instrument nothing runs is a claim" — is defeated by it.

Two further consequences worth stating, because they are the same defect seen
from other sides:

- `bugs/DOCS_mojo_command_name_in_comments.md` says, twice, that
  "`test_cli_usage_text.py` already guards the behavioural half". Nothing runs
  it, so that sentence is currently false, and a future `mojo` → `fire`
  regression in a `print()` would be caught by nothing.
- A file that is registered but not in `check`/`gate` would have the same
  effect silently. This one is louder, which is the estate check earning its
  keep, but it is worth knowing the redness is a *symptom*: the registration,
  not the test, is missing.

## Confirmed pre-existing, not caused by the tally work

    $ git show HEAD:test_suite.py | rg -c cli_usage     # no match
    $ git show HEAD:tools/suite.py | rg -c cli_usage    # no match
    $ git log --oneline -1 -- test_cli_usage_text.py
    851082d test_cli_usage_text.py: the CLI's self-name, and the split with the language

The file is committed at `HEAD`, and neither the estate inventory nor the
registry has ever mentioned it.

## Next step

One line in `tools/suite.py`, in `check`:

    test('cli-usage-text', [PY, 'test_cli_usage_text.py'], cache=True,
         extra=['test_cli_usage_text.py', 'fire.py', 'fire_main.py',
                'fire_compiler.py'],
         desc='the tool prints the name it was invoked as, in usage, -v and every error')

`cache=True` is safe and worth it (4.4 s cold, and the spec must hash
`fire.py`/`fire_main.py`, which is where the usage text and the `argv[0]` read
live — `test_cached_spec_names_its_own_test` will check the second half of that
automatically). Or add the file to `UNREGISTERED` in `test_suite.py` with a
reason, if it is genuinely not meant to run — but it passes, it is fast, and it
guards a user-visible rule, so registering it is the honest answer.

Verify:

    python3 test_suite.py | rg 'estate|Results'     # 1 undeclared -> 0, 0 failed
    python3 tools/suite.py smoke -j2                # exit 0
