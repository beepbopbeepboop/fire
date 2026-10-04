# The self-hosted binary runs, and dies iterating something that is not a container

`selfhost` (`test_selfhost.py`) is the only row of `make check` this tree
leaves red. The binary is BUILT and LINKED, it starts, and it dies inside its
own two-line `--dump-full`:

    $ ./mojo_selfhost --dump-full probe.mojo        # probe.mojo is `x = 1` / `print(x)`
    Error generating --dump-full: TypeError: object is not iterable
    Unhandled exception: NotImplementedError: traceback.print_exc: module 'traceback' is not compiled into this binary
    exit=1

The message is `runtime/fire_runtime.c`'s `mojo_iter_boxed_list`, which raises
it for any value that is neither a string nor a container. So a `for` loop
reached the runtime with a non-iterable in the register — the codegen asked to
iterate something the self-hosted model believes is an `int64_t`.

Unchanged by `MOJO_SKIP_OWNERSHIP_CHECK=1`, so it is downstream of
`gimple_codegen._check_ownership` (which is where the previous failure in this
chain was, and which is now fixed).

## What is NOT the cause, each measured

Four defects were in front of this one and all four are fixed (commits
`0e4b99a9` and the merge `09819b1a`), so this is a fifth, distinct failure and
not the same one rediscovered:

| was | now |
|---|---|
| `'int'` reaching a C declaration (`non-trivial conversion in 'var_decl'`) | `int64_t`, via `_dict_val_of` |
| `glob.glob` at `cas.py` module scope → import-time `NotImplementedError` | `os.listdir`, both source lists verified identical to master's |
| `shutil.which` in `build_config.find_gcc` → `NotImplementedError` | `_which`, matches `shutil.which` on 6 probes |
| `ownership_check` treated as an uncompiled marker → raise inside `_check_ownership` | gated on `gen._compiled_modules` |

Reproduce the build once (4.4 GB, ~10 min, and `tools/memslot.py --gb 8` for
the machine-wide ledger):

    python3 -c "import sys,os; sys.path.insert(0,'.'); import fire; \
      os.chdir('.tmp/sh'); print(fire.build_executable(os.path.abspath('fire.py'), \
      open('../fire.py').read(), output='mojo_selfhost'))"

Then run the binary directly: the test's own temp dir is deleted on the way
out, so a one-off `build_executable` into a directory you keep is what makes
this debuggable at all.

## Where to look next

The raise names no symbol, and the self-hosted binary cannot print one —
`traceback` is not compiled in, which is the second line of the failure and
independently worth fixing, since it is what makes this class expensive to
diagnose. Three narrowing moves, cheapest first:

1. **Print the offending loop.** `mojo_iter_boxed_list` is the only caller of
   `mojo_raise_type_error` with that message, so instrumenting it to dump the
   `v` it was handed, plus the enclosing `__GIMPLE__` function name if the
   symbol table can be walked at that point, names the loop directly. Cheaper
   than any amount of reading.
2. **Bisect the merge.** `selfhost` is red on the merge base `86d60026`
   identically to master, so the tree was never green here; the merge of master
   (`da80b19a`, 177 commits) is what made it this branch's problem. The
   suspect set is the four conflict resolutions in `09819b1a` plus the ten
   branches' middle-tier changes, and the narrowest question is whether
   `module_gen.py`'s new whole-program `_multi_kind_return_funcs` pre-pass (kept
   from HEAD in that resolution, iterating `self._all_closures`, `self._all_closures[_outer_name]`,
   and `.values()`) is reached with a field the self-hosted binary types wrong.
   `_selfhost_scan_gimplegen_extra_fields` has no seed for `_all_closures`,
   `_multi_kind_return_funcs` or `_compiled_modules` — all three read as absent
   from that scan, which is evidence, not proof: the class-body scan and the
   frozen table can still cover them.
3. **Check the interpreter, not the binary.** `fire.py run` on the same probe
   through the same tree is the reference this bug has to be judged against;
   if it passes, the divergence is in codegen, not in the compiler's logic.

## Why it is filed rather than marked

`selfhost` costs 650 s and 4.4 GB, so `expect=` (the marker for a known
failure whose job still has questions to answer) is the right shape by cost and
the wrong shape by honesty: unlike the four `gimplerunner` rows, this one has
no reproduction that isolates the defect, and a count-checked marker with
nothing behind it would absorb the next failure silently. The honest state is
one red row with a doc, which is what this is.