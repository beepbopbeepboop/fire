# test/collections/test_linked_list.mojo is red in the gate, and the red is not the `{mut}` box-free change

## Status

OPEN. The task that filed this asked for the root cause in the branch's own
change. Measured: that change (`47ccf8d1c`, free a `{mut}`-captured local's box
at function exit) is NOT the cause. The gate's failing `test_linked_list` jobs
are red on the parent of that commit as well, and the compiled path's output
for that file is byte-identical in its error set before and after it.

## What was run

Both gate modes of `test_stdlib.py` for this file, the same way the gate runs
them (`fire.py run <file>` and `fire.py --jit <file>`), under
`tools/memslot.py --gb 8`:

1. **JIT, HEAD (`47ccf8d1c`)** — exit 1, `JIT compilation failed: executable
   build failed`, **669** `error:` lines.
2. **JIT, parent (`47ccf8d1c^`, a `git archive` snapshot in `.tmp/`)** — exit 1,
   the same `JIT compilation failed`, **669** `error:` lines.
   `diff` of the two error sets, file:line:column stripped, is empty; with the
   positions kept they are identical too. The box-free change adds no error.
3. **Interpreter, HEAD** — did not finish in 4+ minutes of wall time (the gate
   allows 120 s per run, `test_stdlib.py` `run_one`). Killed; no verdict. The
   interpreter (`fire.py run`) does not import `gimple_codegen`, so the codegen
   change cannot affect it. This is a speed problem, not a regression from the
   change, and it was not measured on the parent.

## What the JIT errors are

The generated C for the stdlib closure the test pulls in does not compile. The
error families, by count (HEAD, same on the parent):

- `base variable or SSA name undeclared before ';' token` — `std/memory/pointer.mojo` (66),
  `std/collections/list.mojo` (54), `std/collections/array.mojo` (38),
  `std/collections/dict.mojo` (18), `std/collections/counter.mojo` (14),
  `std/collections/linked_list.mojo` (13), and more.
- `unexpected RHS for assignment before ';' token` — `string_span.mojo`,
  `Span.mojo`, `linked_list.mojo`, `list.mojo`, `dict.mojo`, `_swisstable.mojo`, ...
- `expected expression before 'FormatStruct'` — `std/ffi/unsafe_union.mojo:293`,
  `std/builtin/variadics.mojo:1029`, `:1317`.
- `implicit declaration of function 'Span___init__'` — `std/builtin/variadics.mojo:711`.
- `'_slit_NNNNN' undeclared` — `std/tempfile/tempfile.mojo`.
- `conflicting types for 'isatty'` — `std/collections/string/string_span.mojo:546`.

`test/test_utils/types.mojo:784` (`return Int(Byte.MAX - 1)` inside
`niche_count`) is one of the `test_utils` dependencies of the test and fails the
same way: the `Byte.MAX` attribute is not lowered.

Each family is a separate codegen gap. None of them is in the box-free path, and
none of them names a `{mut}` box or a free.

## Which parts of the gate this covers

- `stdlib-tests` (`test_stdlib.py`) on `test/collections/test_linked_list.mojo`:
  both modes red, as above.
- `stdlib-syntax` (`compile_stdlib.py`): NOT located by this run. Narrow runs
  all pass: `--module collections` (33/33), `--roots test/collections` (59/59),
  and each of the 17 stdlib/test files that use `{mut}`/`nonlocal` compiled
  alone through `transpile_file` (17/17, `gcc -fsyntax-only`). The full tree is
  the integrator's run. Another worker holds the claim
  `CODEGEN_gate_stdlib_syntax_red` / `gate:stdlib-syntax`.

## Next step

1. Get the attribution right first: diff the gate's failing job list against the
   parent commit, not against master. `master` is not a valid baseline here: it
   is 443 files away from this branch, because the branch was never rebased and
   master has moved on (for example, master has the dead `_no_closure_escapes`
   predicate from `65e0f0775` without the wiring that `47ccf8d1c` adds).
2. The JIT red is the compiled-path stdlib closure. It is owned by the existing
   `CODEGEN_*` docs whose errors match these families, chiefly
   `bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md`
   (96 sites in section 1, 1938 in section 2 of `tools/undef_import_census.py`).
   Fix there, not in the box-free change.
3. The interpreter's wall time for this file is a separate measurement. Time
   `fire.py run` on it with no other load and record the number; if it is
   over the gate's 120 s, the file needs either a faster interpreter path or a
   per-test timeout that is stated, not a silent one.

## Reproduction

    MOJO_STDLIB=<stdlib> python3 tools/memslot.py --gb 8 --label ll -- \
        python3 fire.py --jit <stdlib>/test/collections/test_linked_list.mojo

`<stdlib>` is `/Users/mrs/net/chatgpt/claude/new-modular/Mojo/stdlib` in the
current worktree setup. Expected (per the gate): exit 0 and the test's output.
Observed on HEAD: exit 1, 669 errors, as above.

A small repro of the shape this test uses (a `{mut}` closure passed to a
callee, the box read after the call) runs correctly on both interpreter and
JIT: `.tmp/repro/box_escape.mojo` prints `3`. So the mutable-capture shape that
the box-free change touches is not what fails here.
