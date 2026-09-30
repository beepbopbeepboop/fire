# Dangling `build/mojo` references in docs, and a dead `runtime/compiler_main.c`

**Area:** docs. **Status:** open, partial. The two docs that describe the
system as it is *now* were fixed on `work/runner-stale-mojo`; the rest are
listed here with why each was not, and one dead C file is called out.

## What was fixed in the same branch

| file | what changed |
|---|---|
| `doc/architecture.html` | 6 × `build/mojo` → `mojoc`. This doc already called the compiled binary `mojoc` at lines 196 and 215, so the old name was inconsistent with its own convention. Line 215 listed two distinct artifacts (`mojoc` / `build/mojo`) and needed `build/fire` for the second, not a second `mojoc`. |
| `doc/IMPL.md` | "The Mojo CLI (`build/mojo`)" → `fire.py`, and the "**Implementation**" line rewritten: it stated as present fact that `build_mojo_cli.py` generates the CLI, which nothing does any more. A dated **Stale:** note now points at the bug doc for the generator. |
| `Makefile` | the `build/fire` link rule echoed `build/mojo linked successfully`. |

Both fixes are in the "describes the current system" class. Neither is
cosmetic: a reader following `doc/IMPL.md` to find the CLI was sent to a
generator with no callers, and `build_mojo_cli.py` is exactly what writes the
`build/mojo` whose stale copy made the `runner` job green by accident.

## Not fixed: dated bootstrap narratives

These describe a bootstrap approach that no longer exists in that form —
`make transpile` / `apex py2mojo` writing `mojo/*.mojo` from the Python
compiler. There is no `transpile:` rule in the Makefile, and
`mojo/mojo_main.mojo` (which most of them name) does not exist. So this is not
a rename left behind by the `mojo`→`fire` commit; it is an older pipeline,
abandoned wholesale, that the rename passed over because nothing in it was
being maintained.

| file | hits | reads as |
|---|---|---|
| `doc/BOOTSTRAP_COMPLETE.md` | 7 | "Status: ✅ COMPLETE" for the py2mojo pipeline |
| `doc/BOOTSTRAP.md` | 6 | "Current Achievement: Symbolic Two-Stage Bootstrap ✓" |
| `doc/BOOTSTRAP_COMPLETE_REAL.md` | 3 | "Complete and Working" |
| `doc/BOOT.md` | 3 | a build plan keyed on `make transpile` |
| `doc/REAL_IMPLEMENTATION.md` | 4 | walkthrough of the abandoned stage-1 build |
| `doc/BOOTSTRAP_NEXT_STEPS.md` | 1 | next steps for the abandoned pipeline |
| `doc/PROJECT_SUMMARY.md` | 1 | phase log, "Built build/mojo CLI tool" |

**Why not fixed here:** a truthful edit means deciding, per document, whether
it is a historical record (leave the names, add a date banner saying the
pipeline is abandoned) or a live description (rewrite against
`fire.py`/`mojoc`). That is a documentation decision, not a mechanical rename,
and `sed`-ing `build/mojo` → `mojoc` through them would produce documents that
*read* as current while describing a pipeline with no Makefile rule — strictly
worse than the honest stale ones, because the failure mode stops being
obvious.

**Exact next step:** triage into "archive with a banner" vs "rewrite", one
file per commit, starting with `doc/BOOTSTRAP_COMPLETE.md` (7 hits, and the
"✅ COMPLETE" claim is the most misleading thing in `doc/`). A mechanical
pre-pass worth doing first: `rg -l 'mojo_main\.mojo|make transpile|apex py2mojo' doc/`
to bound the set to documents that actually describe the dead pipeline, as
opposed to the ones that merely use an old binary name.

## Not fixed: `runtime/compiler_main.c` is entirely dead

`runtime/compiler_main.c` is not compiled by any Makefile rule and is not
referenced from any source file — `rg -n compiler_main` finds only its own
header. Its 17-line header comment carries 4 of the `build/mojo` references:

```c
 *   build/mojo --dump-gimple mojo/mojo_main.mojo > build/mojo_logic.c
 *   gcc -fgimple -I runtime -o stage1/mojo build/mojo_logic.c runtime/compiler_main.c ...
```

and it names `mojo/mojo_main.mojo`, which does not exist, plus four
`mojo_*` symbols (`mojo_gimple`, `mojo_pyir`, `mojo_tokens`, `mojo_ast`) that
no C source declares — only the abandoned `doc/BOOTSTRAP*` files still
mention them. Renaming the two `build/mojo` occurrences would make the
header look maintained while the build instructions it gives still cannot
work, so the choice is delete-or-rewrite, not rename.

**Exact next step:** establish whether anything still wants a C-side CLI
entry point. The `build/fire` link rule links `build/system.o` (generated
from `fire.ci`) with the runtime and coroutine objects, and does not include
`compiler_main.o` — so the answer looks like "no". If confirmed, `git rm
runtime/compiler_main.c`; if something does want it, rewrite the header
against the current pipeline (`fire.py` → `fire.ci` → `build/fire`) in the
same commit.
