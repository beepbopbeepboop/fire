# CODEGEN: a tuple used as a dict key (or compared with ==) is keyed by its ADDRESS self-hosted

Found 2026-09-30 by the leak hunt (bugs/PERF_selfhost_memory_leak_hunt.md): it was the cause of ~16 of
the 19 GB live on `mojoc --dump-full fire.py`.

Repro (python3 says `0 1 1 / 1`, the compiled program says `0 0 0 / 3`):

    import os
    _C: dict = {}
    def look(p: str) -> int:
        k = (p, os.path.getmtime(p))
        if k in _C: return 1
        _C[k] = 2
        return 0
    def main():
        print(look("x.py"), look("x.py"), look("x.py"))
        print(len(_C))
    main()

`fire.py build` it: the dict layer keys on `mojo_cstr_or_int_str(word)`, a tuple is neither a boxed
string nor an int, so the key is the tuple object's address. Equal tuples never hit; a reused address can
hit spuriously. `==` between two tuples is the same pointer comparison.

Fixed only at the call sites that mattered (`funcs_shared._selfhost_parsed_source`, `_selfhost_files_key`:
string keys, the `_pair_key` convention already in fire_compiler.py). NOT fixed in general. Known tuple-keyed
compiler dicts still exposed: `_async_closure_api` / `_generator_method_api` /
`_method_threaded_comptime_params` lookups in cpp_async.py, cpp_core.py, emit_methods.py, emit_funcs.py
(`get((struct_name, member))`), i.e. the async/generator paths.

Next step: give `mojo_cstr_or_int_str` (and the `_kw` dict twins) a content key for a registered tuple
(`_reg_tuple`), with an ownership story for the key string (`mojo_cstr_or_int_release` assumes a pool block);
or make the codegen reject a tuple dict key. Either changes which lookups hit, so it needs the gate.
