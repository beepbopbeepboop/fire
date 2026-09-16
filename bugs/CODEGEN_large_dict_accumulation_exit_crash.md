# CODEGEN_large_dict_accumulation_exit_crash: exit status 140 after a large list-of-dicts loop

## Status (2026-09-15 — found by accident, not investigated, unrelated to the ownership-model work in progress)

Found while verifying `doc/OWNERSHIP_MODEL.md`'s Phase 3/exception-safety
fixes with a stress-test loop. Minimal repro, no classes/candidates
involved at all:

```mojo
def main():
    i = 0
    junk = []
    while i < 50000:
        junk.append({"pad": i})
        i = i + 1
    print("done")
```

Compiled via `python3 mojo.py build`, the resulting binary prints `done`
(correct output) and then exits with status 140 (128+12 — SIGSYS on
macOS), both inside and outside this session's sandbox (`dangerouslySandbox`
made no difference), both under `lldb` (which reported the process simply
"exited with status = 140" rather than stopping on a caught signal — `bt`
had nothing to show) and standalone. Confirmed independent of every fix
landed in this same session: reproduces with zero struct/class code, zero
Phase-3 candidates, on plain `mojo.py build` output.

Not investigated further — this session's focus was the ownership-model
exception-unwinding fix and a separate stale-candidate correctness bug
(see doc/OWNERSHIP_MODEL.md's TODO history and the `_gen_struct_method`/
`_gen_toplevel` fix in `gimple_gen_infra.py`/`gimple_gen_funcs.py`), and
this crash is unrelated to both. Likely candidates for a future session:
something in cleanup/exit-time teardown of a large `_mojo_dict_registry`/
`_mojo_list_registry` (50,000 dicts registered), or an unbounded-growth
issue in the same family as `bugs/CODEGEN_container_no_deallocation_
unbounded_growth.md`. Needs a real `lldb`-attached run (not `run`+`bt`
after the fact, since lldb isn't catching whatever raises this) to
actually diagnose.
