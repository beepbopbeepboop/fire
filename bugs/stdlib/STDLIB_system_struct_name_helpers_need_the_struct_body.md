# STDLIB_system_struct_name_helpers_need_the_struct_body

**Found while closing** `STDLIB_std_sys__libc_mojo_416_unknown_type_name_timespec`
(the `unknown type name 'timespec'` symptom is fixed; this is a different error on the
same codegen path).

**Where**: `mojo/backend_gimple/module_gen.py`, `_gmp_emit_struct_definitions`. A struct
whose name is in `_system_structs` (`timespec`, `stat`, `tm`, ...) gets only
`typedef struct NAME NAME;` in the TU, with no body, so the system header's layout is
the only definition. The per-struct helpers the codegen emits for every struct
(`_init_NAME`, `_mojo_getattr_NAME`, `_mojo_repr_NAME`, ...) still read Mojo-level
fields and internal members as if the body were ours.

**Repro** (standalone module, not the stdlib):

    comptime time_t = Int64

    @fieldwise_init
    struct timespec(TrivialRegisterPassable, Writable):
        var tv_sec: time_t
        var tv_nsec: Int64

    def make_ts(sec: Int64) -> timespec:
        return timespec(sec, 0)

Through `build_stdlib_dylib.compile_module_to_c` then `compile_stdlib._gcc_syntax_cached`:

    error: 'timespec' has no member named '__mojo_type_id'   (in _init_timespec)

**Expected**: the generated C for a user struct whose name collides with a C system
struct compiles, with its helpers reading the fields the codegen itself declares.

## Status

- 2026-11-20: measured on HEAD (`typedef struct timespec timespec;` present, so the
  doc's `unknown type name` symptom is gone). The remaining error is the one above.
  Not yet checked: whether the stdlib `_libc.mojo` avoids it only because its helper
  path is never emitted there, or whether other `_system_structs` names
  (`stat`, `tm`, `timeval`) hit it too. Next step: emit the helpers for a system
  struct against its real header layout (or skip them and call the system header
  directly), then re-run the repro above, which must compile with gcc.
