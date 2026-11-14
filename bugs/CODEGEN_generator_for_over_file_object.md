# CODEGEN: `for <line> in <file object>` in a compiled generator iterates zero times (A3) / raises TypeError (cpp)

## Status 2026-11-14 — measured, not fixed

Found while fixing the c-analyzer `c_common/tables.py` consumer link failure
(the imported module's generated C++ was typed `char *` for a path-word
parameter; fixed in the same commit as this doc): the consumer of
`c_common/tables.py` now builds and links, but still cannot print its rows
because the file-object `for` loop inside a compiled generator does not
iterate.

### What was run (A3 stack-switch path, single module)

```sh
mkdir -p .tmp/t1 && printf 'a\nb\n' > .tmp/t1/data.txt
cat > .tmp/t1/g.py <<'EOF'
def gen(p):
    with open(p) as f:
        for line in f:
            yield line.strip()

def main():
    for x in gen(r'''<worktree>/.tmp/t1/data.txt'''):
        print(repr(x))

main()
EOF
python3 tools/memslot.py --gb 8 --label t1 -- \
  python3 fire.py build -o .tmp/t1/g .tmp/t1/g.py
.tmp/t1/g
```

### What was seen

The build exits 0 and the binary exits 0, but prints **no lines** (CPython
prints `'a'` / `'b'`) and warns on stderr:

```
mojo_unsupported_iter: 'for' loop over unsupported iterable type
  .tmp/t1/g.py:3: int64_t (codegen has no lowering for this
  container/iterator shape; the loop body runs zero times)
```

The cpp C++20 path refuses differently: a cpp-path generator
(`def gen(path, *, _open=open)`) doing `for line in path:` with `path`
rebound by `with _open(path) as path:` compiles, and the binary then raises

```
Unhandled exception: TypeError: object is not iterable
```

at the loop (exit 1). Both are the same missing lowering: a `for` over the
runtime's open-file word.

### Why it matters

This is the last thing keeping a consumer of `c_common/tables.py` from
producing output. `read_table` does `lines = strutil._iter_significant_lines(infile)`,
and `_iter_significant_lines` is literally `for line in lines:` — the body
never runs, so the first `next(lines)` raises `StopIteration`, `actualheader`
stays `''`, and the consumer dies with:

```sh
cd .tmp/ca && python3 ../../fire.py build -o _check_rt _check_rt.py  # exits 0 now
./_check_rt
Unhandled exception: bad header ''
```

(`.tmp/ca` = `/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/` copied in; the
`_check_rt.py` fixture is the one in the consumer-link doc.)

### What was expected

The two rows, exactly as CPython:

```
('1', '2')
('3', '4')
```

### Exact next step

Add a line iterator over the `mojo_open_file_ex` word to the runtime (a
`mojo_file_lines_start/_resume/_value/_destroy` family in
`runtime/fire_runtime.c`, or normalise through the existing Python-file
object ABI if one is reachable from C) and a `for` lowering arm for an
iterable whose ctype is that word, in BOTH backends:

- `mojo/backend_gimple/emit_loops.py` (`_gen_for_generator_iter` /
  `_gen_stmt_ForStmt`'s iterable switch) for A3, which is the path
  `_iter_significant_lines` takes; its `_start(int64_t)` parameter is
  ALREADY the word, so only iteration is missing;
- `mojo/backend_gimple/cpp_core.py` `_cpp_for_stmt` for the cpp path, whose
  current fallback raises `TypeError: object is not iterable` at run time.

Do NOT "fix" this by typing the parameter `char *` or `MojoList *`: the
value is the `mojo_open_file_ex` handle that `mojo_close` and the
`with`-arm's assignment both treat as an int64 word.

Quick test once implemented: a generator that opens a file and yields
`line.strip()` for each line, compiled and run against CPython on the same
file (the `.tmp/t1/g.py` shape above). The pinning test can live beside
`_regression_with_tabled_open_in_generator` in
`test_gimple_generator_runner.py`.
