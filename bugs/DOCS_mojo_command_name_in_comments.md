# `mojo <command>` still written in comments and docstrings across the tree

**Area:** docs/prose. **Behaviour:** none — nothing here prints, and no test
reads it. **Status:** open, 34 references, all one-line prose edits.

## What

The tool is `fire.py` (it was `mojo.py`). `fire.py --help`, `-v` and every
usage error used to print the old name too, and that half is fixed — see
`a51479c`, which made the printed name follow `sys.argv[0]`, plus the one other
*user-visible* string that named the CLI (`formal/build.py`'s "written next to
the dylib by `mojo dylib --formal`", now `fire`) and `test_cli_usage_text.py`.

What is left is the same stale name in **prose**: comments and docstrings that
tell a reader which command to type, in 15 other files. No user ever sees
these; the cost is a reader who greps for a command that does not exist.

    $ rg -n 'mojo (build|run|repl|dylib|formalbuild|--formal|--dump|--jit|-h|-v|<file)' \
        -g '*.py' -g '!build/**' .

Current counts, after the fix (38 matches, of which 4 in `fire.py` are
correct and 0 elsewhere should be kept):

| file | n | what it says |
|---|---|---|
| `myinterpreter.py` | 5 | `mojo build` / `mojo run` in predicates and history notes |
| `driver.py` | 5 | module docstring (`driver.py — \`mojo build\`/\`run\``) + `mojo dylib` |
| `module_loader.py` | 4 | `mojo dylib`, `mojo build` |
| `build_stdlib_dylib.py` | 3 | `mojo dylib` |
| `mojo/middle/funcs_shared.py`, `mojo/backend_gimple/emit_exprs.py` | 2 each | `mojo dylib` / `mojo run` |
| `gimple_codegen.py`, `fault_tolerance.py`, `test_comptime_bracket_params.py`, `mojo/middle/types.py`, `mojo/backend_gimple/emit_stmts.py`, `emit_infra.py`, `emit_funcs.py`, `emit_calls.py` | 1 each | see below |

The two worth doing first, because they are claims about the tool's own
documentation and are therefore now false, not merely stale:

    fault_tolerance.py:9   "...exactly what `mojo -h` documents as the fallback"
    driver.py:2            """driver.py — `mojo build`/`run`, thin by design"""

## The keep-list — do NOT sweep these

A blind rename is the failure mode here; the language is called Mojo and
several of these names are real:

- `stage2/mojo`, `mojoc` — real artifacts (`mojo/middle/infra_infer.py:277`,
  `mojo/backend_gimple/emit_resolve.py:739`, `tools/suite.py:18`,
  `tools/tu_grind.py:6`, `fire.py:619`). The compiled binaries are still
  *named* `mojo`; only the text they print is derived now.
- `<file.mojo>`, `.mojo` extensions, `mojo_*` runtime symbols, `MOJO_NO_SHIM`,
  `~/.gmojo/cas` — the language and the CAS root, untouched by design.
- Upstream Modular Mojo, quoted as `mojo run` (`fire.py:916`) — that is *their*
  command, not this one.
- `fprintf(stderr, "mojo: .wait() reached on a stub")` in
  `mojo/backend_gimple/emit_methods.py:1298` and `"mojo: abort() called"` in
  `cpp_core.py:4276` — printed by a COMPILED USER PROGRAM's runtime, not by the
  CLI. Different subject, and it is output a program under test may match on.

## Next step

One pass, one line each, `mojo <command>` → `fire <command>`, keeping the
keep-list above. `test_cli_usage_text.py` already guards the behavioural half
and will fail if a future change reintroduces a hardcoded name in a `print`.

Verify:

    rg -c 'mojo (build|run|repl|dylib|formalbuild|--formal|-h|-v)' -g '*.py' \
       -g '!build/**' .        # only the keep-list should remain
    python3 test_cli_usage_text.py

Not done in `a51479c` on purpose: those files are other workers' active
problem areas (`myinterpreter.py`, `driver.py`, `module_loader.py`,
`mojo/backend_gimple/*`), and 34 one-word edits across all of them is a
guaranteed merge conflict for no behaviour.
