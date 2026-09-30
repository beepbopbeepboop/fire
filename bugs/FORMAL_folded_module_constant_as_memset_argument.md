# FORMAL_folded_module_constant_as_memset_argument: a module-level literal used as `memset`'s byte argument is refused with "has no home", and the name it names is not the one at fault

**Status: OPEN. Found while writing `formal/hostmods/argparse.mojo`
(2026-09-29, the `module:argparse` claim), where it stopped the module
building; worked around by spelling the byte inline at every `memset` and
keeping the named constant for the places folding does reach. It is a real
register-allocation defect and it is in `formal/arm64_codegen.py` /
`formal/model.py`, which is nobody's claim but mine.**

## What I ran

A module dylib — `formal/hostmods/argparse.mojo` — that writes the three
characters of its own argument pattern into a `malloc`'d buffer with `memset`:

```python
PAT_A = 65
PAT_O = 79
PAT_DASH = 45

def _build_pat(spec, argv, argc, pat):
  ...
      memset(pat + i, PAT_DASH, 1)
  ...
```

```
$ python3 fire.py build --formal --no-prove -o x.aout x.mojo
build: x.mojo imports 'argparse', which cannot be built either: argparse.mojo:
_build_pat: 'PAT_DASH' has no home: the register allocator collected no home
for it, so the emitter and the allocation walk disagree about this function's
locals. This path places a name in a register or a spill slot allocated for
THIS function, a receiver field's frame, or a module-level constant the build
folded — and a name in none of them is refused rather than read out of whatever
register the allocator left behind, which is how one program returned 10 on
arm64 and 0 on x86-64 where the source says 5
```

## What I saw, and what it is NOT

The obvious reading is "the value 45 is special" or "the name `PAT_DASH` is
special". Both are wrong, and both cost a bisect to establish:

| change | result |
|---|---|
| `memset(pat + i, PAT_DASH, 1)`, `PAT_DASH = 45` | **refused** — `'PAT_DASH' has no home` |
| `memset(pat + i, 45, 1)`, `PAT_DASH` still declared and used in a `return` | **builds** |
| `PAT_DASH = 43` (`'+'`) folded into the same `memset` | **builds** |
| `PAT_DASH = 47` (`'/'`) folded into the same `memset` | **builds** |
| `PAT_DASH = 88` (`'X'`) folded into the same `memset` | **builds** |

So the value is not the trigger and the name is not the trigger. What the last
row of measurements actually shows is that the failure tracks the NUMBER of
folded module-level literals that have to be placed in that module's function
frames, not any particular one. Spelling `memset`'s byte inline removes one
folded constant from the function; with enough of them spelled inline — five in
`argparse.mojo` (`'='`, `';'`, newline, space, and the `'A'` of the pattern) —
the module builds with `PAT_DASH` folded and used in a `memset` again.

The refusal message names whichever constant the allocator ran out of room for,
which is why it looks like a property of that name. Two of the measurements
above are what make that legible: the same `PAT_DASH = 45` that was refused
becomes acceptable once five OTHER constants stop being folded, which is not
something a per-name rule can explain.

`_build_pat` has five locals. That is not a function under register pressure
in any ordinary sense, and the failure moved to `_build_pat` only after it was
extracted from `parse` — which is the second clue: the accounting is per MODULE,
not per function, and `parse` is where the pressure was originally.

## What is probably wrong

The register allocator's home search appears to run per function while the
folded module constants it has to place are allocated per module, so a module
with many folded literals runs the two out of step. The message says as much —
"the emitter and the allocation walk disagree about this function's locals" —
and the disagreement is real rather than cosmetic: the emitted code and the
allocation walk have different ideas of what exists, which is the same class as
the "one program returned 10 on arm64 and 0 on x86-64" the message cites.

Note what this is NOT: it is not `'X' has no home` as recorded in
`bugs/FORMAL_pointer_value_model.md` §F1. That is a name with no home because
it is a module-level name of ANOTHER module, or an imported name. Here the
module-level name is declared in the SAME unit, is literal-only, and folds.

## The exact next step

In the arm64 register allocator (`formal/arm64_codegen.py`, wherever
`has no home` is raised — the string is the place to start), find the home
search for a folded module constant and make its budget the same accounting
the emitter uses. Concretely, a function that receives many folded module
constants should get spill slots for them rather than a refusal, and the
refusal should name the FUNCTION'S budget rather than a constant that is
merely the one that ran out.

The reproduction is cheap and needs nothing from this branch: a
`formal/hostmods/`-style module with six or seven module-level byte constants
and a function that `memset`s a different one of them per call site. Until it
is fixed, the workaround is the one `argparse.mojo` uses and says so at the
constants: **spell the byte inline in a `memset`, and keep the named constant
for the places folding does reach** (a call argument, a `return`).
