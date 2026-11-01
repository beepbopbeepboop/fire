# CODEGEN: a capturing nested function passed AS A VALUE from inside another nested function reaches its callee with a NULL environment

## Status (2026-11-01, OPEN; reproduced with the ordinary Python-run compiler, no self-host involved)

    def outer(base, items):
        seen = {}
        def visit_main(node, env):
            seen[node] = base
        def collect_from(src, visit):
            for n in src:
                visit(n, None)
        def collect():
            collect_from(items, visit_main)     # visit_main handed on from inside `collect`
        collect()
        return len(seen) + base
    print(outer(10, [1, 2, 3]))                 # CPython 13; compiled: SIGSEGV (exit 139)

`python3 fire.py build cl6.py -o cl6.bin && ./cl6.bin`. It works when `collect_from(items, visit_main)` is written in
`outer` itself (the env variable is in scope), and when `collect` CALLS `visit_main(...)` directly (the transitive-capture
path). The value path is the one that is missing: `emit_exprs._closure_value` builds the `MojoBoundMethod` from
`gen._closure_envs.get(name) or "0"`, and inside `collect` the sibling's env variable is not one of `collect`'s
captures, so the env is `0`; the lifted `visit_main` then loads its captures through a NULL pointer.

Found because the self-hosted compiler (`test_selfhost.build`) crashed (`EXC_BAD_ACCESS address=0x0` at the first
instruction that reads the env) on EVERY program with a module-level call: `coro._scan_callsite_param_kinds` had exactly this
shape (`_collect` passing the capturing `_visit_call` to `_collect_from`). `test_selfhost`'s probe program has no call, so it
could not see it. `coro.py` now calls the visitors by name; the language-level bug remains.

## Next step

Make a nested function that REFERENCES a sibling closure by value capture that sibling's env (or its captures) the way a call
does, then build the bound method from the captured env in `_closure_value`. Test: the repro above in
`test_gimple_runner.py` (stdout vs CPython). Also add a def + module-level call to `test_selfhost.run_produced_binary`'s probe
(and an f-string) so this class is gated.
