# CODEGEN: a callable-valued parameter is emitted as `std::function<...>` in the C client (link mode cannot build the consumer)

## Status 2026-11-14 — measured, not fixed

Found while fixing the c-analyzer `c_common/tables.py` consumer link failure
(its imported C++ unit was typed against the wrong module's pointer evidence;
fixed in the same commit as this doc). The imported module's C++ coroutine
unit now compiles, but link mode STILL cannot build the consumer: the client
`.c` itself does not compile, because an imported plain function's
callable-default parameter is spelled with a C++ type.

### What was run

Link mode on the tables consumer (`.tmp/ca/_check_rt.py`, sources copied from
`/Users/mrs/net/Python-3.14.6/Tools/c-analyzer/`):

```sh
python3 tools/memslot.py --gb 8 --label lm -- python3 .tmp/lm_tables.py
```

where `lm_tables.py` calls
`driver.compile_program(entry, src, output=..., run=False)`. It raises inside
`driver._build`'s client compile:

```
subprocess.CalledProcessError: Command ['/opt/local/bin/gcc-mp-15', '-fgimple',
  '-fPIC', '-I<tree>/runtime', '-O0', '-g3', '-c', '-o',
  '<tmp>/mojo_drv_XXXX/client.o', '<tmp>/mojo_drv_XXXX/client.c']
  returned non-zero exit status 1.
```

`driver._build` swallows the compiler's stderr, so compile the left-behind
file by hand:

```sh
gcc-mp-15 -fgimple -fPIC -I runtime -O0 -g3 -c -o /dev/null .tmp/mojo_drv_XXXX/client.c
.../c_common/strutil.py:153:104: error: unknown type name 'std'; did you mean 'stdin'?
.../c_common/tables.py:84:139: error: unknown type name 'std'; did you mean 'stdin'?
```

The offending declarations/definitions in `client.c`:

```
int64_t c_common_tables_write_table_f728c8 (int64_t, MojoList *, MojoList *,
    char *, int64_t, int64_t, std::function<int64_t()>, int64_t);
int64_t c_common_tables_write_table_f728c8 (..., int64_t backup,
    std::function<int64_t()> _open, int64_t _get_writer) { ... }
```

A call-site temp for a generator's callable default is the same shape:

```
std::function<int64_t()> _t2;
_t2 = (std::function<int64_t()>)0;
pkg_helper_gen_bccba8 (_t1, _t2);
```

### What was expected

The C translation unit uses the runtime word for a callable value —
`int64_t` — exactly as the generator entry points already do:

```
extern MojoGenerator *_mojogen_c_common_tables_read_table_start
    (int64_t, int64_t, char *, int64_t, int64_t, int64_t);
```

A callable value is boxed as a word everywhere in the C runtime
(`mojo_dyn_call((int64_t)(intptr_t)(callee), ...)`); `std::function` is only
expressible in cpp coroutine units, where the callable is actually invoked
through C++ syntax.

### Why it matters

`fire.py build` still "succeeds" for such a consumer only because
`driver.compile_program` throws, `fire.py` swallows it
(`except Exception: rc = None`) and rebuilds through the inline fallback
`build_executable`. The DEFAULT link-mode pipeline (per-import dylibs,
reflection, CAS) cannot build any consumer that reaches a plain function with
a callable-valued default — `c_common.tables.write_table`, and the
`_get_reader`-family functions beside it.

### Exact next step

Where an imported function's C-side signature and call-argument temps are
emitted (`mojo/backend_gimple/emit_resolve.py`'s import registration feeding
`func_param_types`, and the arg-temp ctype in `emit_calls.py`), map a
`std::function<...>` ctype to `int64_t`. Keep `std::function` only for the
cpp coroutine unit's own parameters. The ctype originates in
`mojo/middle/infra_infer.py::_infer_param_types`, which binds a known
foreign-callable default (`mojo/middle/types.py::_FOREIGN_CALLABLES`,
`_CPP_CALLABLE_CTYPE*`), so the mapping belongs at the C-emission boundary,
not by dropping the callable typing (the cpp path needs it).

Quick test: `driver.compile_program` (not the `fire.py` fallback) builds and
runs a consumer of a module containing `def w(x, _open=open): ...`; before
the fix it raises `CalledProcessError` on `client.c`, after it returns 0 and
the binary's stdout matches CPython.
