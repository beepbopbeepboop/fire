# CODEGEN: `os.path.*` and `len()` treat a BYTES value as a str

Found while working `CODEGEN_glob_bytes_pattern_returns_empty.md` (2026-11-01). The bytes
values are correct when they come straight from the bytes API; the `os.path` functions and
`len()` do not dispatch on the object's kind.

## Measured (compiled, this tree; the same values at HEAD)

    print(len(os.path.split(b'a/b.py')[0]))   # CPython 1   compiled 0
    print(len(os.path.join(b'/tmp', b'x')))   # CPython 6   compiled 11     (the join is b'/tmp/x')
    d = os.path.split(b'*.py')[0]             # empty bytes
    print(len(d or b'xy'))                    # CPython 2   compiled 5

`os.path.split(b'*.py')` gives `(b'', b'*.py')` with the right lengths, and `not d` on that empty
bytes is right, so the bytes is not corrupted by `split`; the length read is.

## Why

- `os.path.split` / `join` / `splitext` / `basename` / `dirname` / `exists` lower to the `char *`
  runtime entries (`int64_t_path_split(char *)`, `mojo_path_join(char *, char *)`, ...). A bytes
  argument is a `MojoBytes *` and is read as text. The word-kinded variants that exist
  (`mojo_os_path_join_w`, `mojo_os_path_basename_w`, `mojo_os_path_dirname_w`, `mojo_os_path_exists_w`)
  are the values-as-callables spelling, not the lowering the direct calls use.
- `len(x)` on a value whose kind is a word is `strlen`, so a bytes word counts to its NUL. The
  `or` of two bytes values returns a word (`'w'`), and `len` of that word is not dispatched.

## Status (2026-11-02)

- Step 1 `len`: FIX LANDED (emit_calls.py routes `'w'`-kinded `len` through `mojo_len_word`; runtime `mojo_len_word` verified; build break fixed).
- Step 2 `os.path.*` (`basename`, `dirname`, `exists`, `isfile`, `isdir`): PARTIAL — lowerings updated to dispatch to `_w` variants for `int64_t`/`MojoBytes *` args (emit_methods.py); runtime `_w` entries for basename/dirname/exists/isfile/isdir need full bytes-aware implementation (currently cast to char*) — not completed.
- Step 3 tests: regression `test_bytes_os_path_regress.py` runs; `test_path_word_runtime.py` PASS (split/join match CPython); `len` on direct split result passes; `len` on `or`-combined word/subscript result still diverges (subscript/retrieval of list elements for bytes words needs separate fix).
- Next (after this branch): complete bytes-aware runtime for basename/dirname/exists/isfile/isdir/splitext; fix bytes-word subscript/retrieval on MojoList elements; full end-to-end regression.

## Next step

1. `len`: dispatch on the value's kind at run time for a word (`mojo_len_word`: a registered
   bytes is `len`, a str is the code-point count, a list is its length). Route the `'w'`-kinded
   `len` lowering through it (`emit_calls.py`'s `len` arm).
2. `os.path.*`: the bytes arm of each function. Either a bytes-aware C entry per function (for
   `split`, `join`, `splitext`, `basename`, `dirname`) or a word entry that dispatches, then the
   lowering picks it when the argument's kind is `'w'` (the same rule `fsencode` uses). Start
   with `split` and `join`, which `glob` needs (`_iglob`'s `os.path.join(dirname, name)`).
3. Tests: extend `test_glob_bytes_regress.py` (or a new `test_bytes_os_path_regress.py`) with the
   three lines above, asserting CPython's output, and make sure they fail before the change.
