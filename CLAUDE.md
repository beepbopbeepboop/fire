# Testing

Beyond `make check`, three comprehensive quality gates:
- `make bootstrap` — full self-host bootstrap; *running* the produced binaries has a known pre-existing failure (see BACKLOG-CODEGEN.md §1), ignore that and judge the compile/link stages.
- `python3 compile_stdlib.py --roots _core,collections,io,math,os` — transpiles the standard library and gcc-syntax-checks every module.
- `python3 build_stdlib_dylib.py` — rebuilds `build/libmojostdlib.dylib`; the dylib is a compilation speed hack (comptime/elaboration introspection included) and MUST be rebuilt after codegen changes or it is stale and buggy.
