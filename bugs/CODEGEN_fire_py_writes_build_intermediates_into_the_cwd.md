# `fire.py build` writes its intermediates into the CURRENT WORKING DIRECTORY, so two concurrent builds of the same module basename collide

## Status

OPEN — found 2026-10-03 while merging `work/merge-bugs3-r4` into master. Not
fixed here: `fire.py` is the compiled path, and CLAUDE.md's rule for a change
touching it is a full `make gate`, which this worker's brief does not permit.
The cheap half — making the artifact impossible to commit — has landed in
`.gitignore`; the collision hazard has not.

Two files this merge was going to bring in were this artifact, committed by
`e98ea1f8` before anyone noticed: `update_file_gen.cpp` and
`generate_sre_constants_gen.cpp`, both at the repository root. They are removed
in the same commit. Nothing reads either of them; `fire.py` writes and compiles
them in one function.

## What is believed

`fire.py`'s `build_executable` derives every intermediate path from
`basename = os.path.splitext(os.path.basename(input_file))[0]` and, **only if
the caller passed `work_dir`**, prefixes it with that directory:

    fire.py:701   if work_dir is not None:
    fire.py:702       basename = os.path.join(work_dir, basename)

Every one of these is then a path relative to the process's CWD:

    fire.py:753   ci_file = f"{basename}.ci"
    fire.py:762   o_file = f"{basename}.o"
    fire.py:769   runtime_o = f"{basename}_runtime.o"
    fire.py:786   cpp_file = f"{basename}_gen.cpp"
    fire.py:790   gen_o = f"{basename}_gen.o"

Of the three in-tree callers, only two pass `work_dir`
(`test_module_cache.py:1265`, `jit/arm64.py:248`). **`fire.py`'s own `build`
command does not** — `fire.py:1228` calls
`build_executable(input_file, src, output=build_output, ...)` with no
`work_dir`, so the `output` argument is honoured and the intermediates are not.

## Why it matters, in two separate ways

**Litter.** Measured: `python3 test_py314_full.py` from the repository root
leaves `grammar_snippet_gen.cpp` there (and, on an earlier run of the same
sweep, `generate_sre_constants_gen.cpp`). `.gitignore` covers `*.ci`, `*.o`
and `*.aout` — the other three intermediates — so this one file was the only
way a build could dirty `git status`, which is how two of them got committed.

**A wrong artifact, which is the part worth a bug doc.** Two concurrent builds
of two different modules that share a basename — `a/gen.py` and `b/gen.py`, or
the same `foo.py` in two temp trees — both write `gen.ci`, `gen.o`,
`gen_gen.cpp` and `gen_gen.o` into the shared CWD, and neither takes a lock.
That is the wrong-artifact class this repository already has a genre of bug docs
for, and `tools/suite.py` runs jobs `-j18` from a common checkout, so the
collision is reachable by the gate rather than only by hand.

The window is not small: `ci_file` is written, then `gcc -c` reads it, and the
`_gen.cpp`/`_gen.o` pair spans a second compiler invocation. A reader that sees
a half-written `.ci` gets whatever gcc makes of it.

## What was run

    $ cd <worktree> && python3 test_py314_full.py          # killed at 50 min
    $ ls grammar_snippet_gen.cpp && git status --short
     grammar_snippet_gen.cpp
     ?? grammar_snippet_gen.cpp

    $ grep -n "_gen.cpp" fire.py
    786:            cpp_file = f"{basename}_gen.cpp"

    $ grep -rn "build_executable(" --include=*.py .
    fire.py:1228            success = build_executable(input_file, src, output=build_output,
    test_module_cache.py:1264  ok = fire.build_executable(..., work_dir=proj, quiet=True)
    jit/arm64.py:245        if build_executable(..., work_dir=build_dir, quiet=True)

## Expected

A build writes its scratch beside the artifact it was asked for. `output` is
honoured; `basename` is not, so the scratch lands wherever the caller happened
to be standing.

## Next step

Put the intermediates in a directory derived from `output`, not from the CWD,
and make the four names unique per build so two of them cannot collide even
inside one directory. Concretely, in `build_executable`:

* derive the scratch directory from `os.path.dirname(os.path.abspath(output))`
  (falling back to the input file's directory when `output` is None), and
  `os.makedirs` it;
* keep the current names inside it, so the `*.ci`/`*.o` `_gen.*` pairing
  cannot be separated;
* clean it up on both the failure and the success return, or accept the
  directory as a build output beside the executable.

Then delete `work_dir` and its two callers, because a parameter with one
meaning in three call sites and a second meaning in the fourth is how the
fourth got this wrong. That is a compiled-path change and owes a full
`make gate` — which is why it is written down here rather than done.