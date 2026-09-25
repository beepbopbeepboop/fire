# CODEGEN: compiled-path dict/list/set are never freed — unbounded memory growth

## Status (2026-09-24 — RESOLVED, verified empirically)

Codegen now emits the container cleanup calls this doc's "Where the fix
goes" section asked for (the ownership model's Phase 6): `gimple_gen_*.py`'s
scope-exit / ownership machinery routes a `MojoDict *`/`MojoList *`/
`MojoSet *` local through `mojo_cleanup_push_{dict,list,set}` (see
`mojo/backend_gimple/emit_infra.py`'s cleanup-function tables) and the
runtime tears them down via `mojo_*_free` at scope exit.

Verified with this doc's own repro shape (`for i in range(n): d = {}; ...;
s = {..}; l = [..]`) built via `python3 fire.py build`, run at 200,000 and
1,000,000 iterations: `maximum resident set size` is IDENTICAL (9,355,264
bytes) at both counts — flat memory, not growth. Before the Phase 6 fix
this doc measured ~267 MB for the 200,000-iteration form.

The companion `CODEGEN_container_free_registry_dangling_entries.md` (which
this doc's fix would otherwise have made live) is also fixed — the
`_destroy` helpers discard their registry entries.

## Original text (2026-09-15) follows

Found 2026-09-15 while checking the compiled path for leaks with macOS `leaks`.

## What the bug is

`gimple_gen_*.py` never emits a call to `mojo_dict_free` / `mojo_list_free` /
`mojo_set_free` for any container, ever — confirmed via:

```
grep -n "mojo_list_free\|mojo_dict_free\|mojo_set_free" gimple_gen_*.py gimple_codegen.py
gimple_codegen.py:2384:        'mojo_dict_free':        ('void',      ['MojoDict *']),
```

That one hit is just the function's entry in the runtime-signature table
(`RUNTIME_FUNCS`) used to typecheck/emit *calls* to runtime functions — no
lowering path (`gimple_gen_stmts.py`'s scope/block exit, function-return
teardown, `del` statement, loop-body end, etc.) ever actually calls it.
Every `{}`/`[]`/`set()` a compiled Mojo program creates lives until process
exit, no matter how small its lexical scope is.

This is not reported as a "leak" by `leaks` because the containers stay
*reachable* the whole time — see the docs below for why — but it is
unbounded memory growth for any loop or long-running program that creates
containers, which is the practically-visible symptom.

Two things independently keep every container procedurally alive:

1. No `free()`-equivalent call is ever emitted at scope/lifetime end
   (this doc).
2. `runtime/mojo_runtime.c` keeps a permanent global registry
   (`_mojo_list_registry` / `_mojo_dict_registry` / `_mojo_set_registry`)
   that every `mojo_list_new()`/`mojo_dict_new()`/`mojo_set_new()` call
   registers itself into for the container's entire process lifetime, used
   by `mojo_is_registered_list`/`_dict`/`_set` to runtime-discriminate an
   ambiguous boxed pointer. See the companion doc
   `CODEGEN_container_free_registry_dangling_entries.md` for the related
   (currently latent) bug in those registries' `free` paths — fixing
   *this* doc's issue (making codegen actually call `mojo_*_free`) is what
   will make that companion bug's dangling-registry-entry hazard live.

## Where the fix goes

- `gimple_gen_stmts.py` (or wherever block/scope exit is lowered) needs a
  real lifetime-tracking pass: every local variable whose static type is
  `MojoDict *` / `MojoList *` / `MojoSet *` and that is not returned or
  captured/escaped (assigned to a field, appended to an outer container,
  captured by a closure, returned) should get a `mojo_*_free()` call
  emitted at the end of its owning scope.
- This is genuinely lifetime/escape-analysis work, not a one-line fix —
  ownership must be tracked through: return statements, closure captures
  (`gimple_gen_funcs.py`'s closure lowering), container-of-container
  nesting (a list holding lists/dicts — do the inner containers get freed
  too, or does ownership transfer to the outer container?), and aliasing
  (`x = d; y = x` — freeing through `x` must not double-free `y`, and
  `mojo_dict_clear`'s own comment at `runtime/mojo_runtime.c:2441-2449`
  already documents a real SIGABRT this compiler hit before from exactly
  this double-free class of bug when `.clear()` was wrongly lowered to
  `mojo_dict_free`).
- Given the aliasing/escape hazards, a conservative first cut (free only
  containers whose address provably never escapes their own straight-line
  function body — no assignment to any wider-lifetime location) is safer
  than attempting whole-program ownership tracking in one pass.

## This also affects self-hosted `myinterpreter.py`, not just user programs

`myinterpreter.py` is itself one of the files `make check-selfhost` compiles
through this exact codegen path (`Makefile:108`:
`check-selfhost: ... myinterpreter.py ...`) — there is no separate
allocator for "the interpreter's own containers" vs. a user program's, so
every `{}`/`[]`/`set()` inside myinterpreter.py's own source (environments,
scopes, AST-node caches, etc.) leaks identically once self-hosted. This is
a much stronger stress test than the synthetic loop below: a compiled
interpreter is long-running and heavy on the exact aliasing/escape cases
(closures capturing environments, dicts nested in dicts, AST nodes stored
in outer containers) flagged above as the hard part of the fix — worth
running a self-hosted `myinterpreter.py` under `leaks --atExit` on a
representative workload (e.g. `compile_stdlib.py`) as a real-world
validation target once a fix is attempted, not just the minimal repro
below.

## Test case

```mojo
# leak_check.mojo
def main():
    for i in range(200000):
        d = {}
        d["a"] = i
        d["b"] = i * 2
        s = {1, 2, 3, i}
        l = [1, 2, 3, i]
        l.append(i)
        total = d["a"] + d["b"] + len(s) + len(l)
        if total < 0:
            print(total)
    print("done")
```

```
python3 fire.py build -o leak_check leak_check.mojo
codesign -s - -f --entitlements entitlements.plist leak_check   # get-task-allow, so `leaks` can inspect the process at all
leaks --atExit -- ./leak_check
```

(`entitlements.plist` needs `com.apple.security.get-task-allow` = true —
without it `leaks` refuses with "Process is not debuggable" and cannot
inspect the target at all, even to correctly report zero leaks.)

Observed:
```
Process NNNN: 1600274 nodes malloced for 221354 KB
Process NNNN: 0 leaks for 0 total leaked bytes.
Physical footprint:         267.2M
Physical footprint (peak):  267.2M
```

0 leaks (everything is reachable, per above) but 267MB resident for a loop
that, if containers were freed at end-of-iteration scope, should run in
near-constant memory. Expected fix result: physical footprint for this
same repro should stay flat (not grow with iteration count) once
end-of-scope container deallocation is implemented; re-run this exact
`leaks --atExit` invocation before/after and compare `Physical footprint`.
