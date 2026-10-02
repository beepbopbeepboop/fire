# CODEGEN: closure environments and boxed mutable locals are never freed

## Status (2026-10-01, later — OPEN 1 re-measured and its stated next step is
## WRONG: there is no bound method in this shape at all)

OPEN 1 still reproduces, at the same rate, and the fix is smaller and differently
shaped than this document's "Next step" says. Both corrections matter, because
the stated next step sends a reader to a file that has no bearing on it.

**Measured** with `tools/mem_slope.py` on
`build/memprobes/nested_def_closure.mojo` (the `helper`/`inner` shape from OPEN
1, looped):

    n=100000    peak 3.06 MB
    n=400000    peak 7.66 MB      ->  +16.1 B/iter

which is OPEN 1's 16 B/iter, unchanged.

**What the generated C actually is.** No `MojoBoundMethod`, no
`mojo_bound_method_new`, no `_reg_bound_method` entry — the nested `def`'s
environment and a DIRECT call to the lifted function:

```c
int64_t __GIMPLE helper (int64_t n) {
  helper_inner_env * _env_inner;
  ...
  _env_inner = _alloc_helper_inner_env ();
  _t1 = n;
  _env_inner->n = _t1;
  _t3 = (int64_t)1;
  _t2 = helper_inner (_env_inner, _t3);      /* direct, not through a value */
  return _t2;                                 /* and no free anywhere */
}
```

So the next step's specific plan — "a `gen._closure_vals` entry survives into
the CALL, so `mojo_fnptr_call_N`'s emission site (`emit_calls`, the
`mojo_is_bound_method` dispatch) can free a closure it was handed as a callee" —
targets a symbol this program never emits. It is not needed and not sufficient:
what is needed is a plain `free(_env_inner)`, because there is no registry entry
to drop.

Three further facts that make the real fix smaller than this document implies:

1. **The record already exists.** No new `gen._closure_vals` entry is wanted:
   `gen._closure_envs[node.name] = env_var` (`emit_funcs.py:169`) is the env var,
   keyed by the nested def's name, and it already survives into the call —
   `_lower_closure_call` reads it at `emit_calls.py:4244`.
2. **The ownership predicate already exists too, modulo one requirement that
   cannot apply.** `ownership_destruct._lambda_uses_ok(body, name)` asks exactly
   the right question — "is every mention of this name the CALLEE of a call?" —
   and answers True for this body. `lambda_value_owned` adds "and the binding
   must be a `lambda` expression, and there must be exactly one", which is about
   a callable bound to a LOCAL. A nested `def` binds no local, so the fix is
   `lambda_value_owned` minus the binding clause, not a new analysis.
3. **No new runtime cleanup kind is needed.** The unwind entry already exists:
   `MOJO_CLEANUP_PTR` / `mojo_cleanup_push_ptr`, documented in
   `fire_runtime.c` as "a plain malloc/calloc block: a struct instance" — which
   is what a bare env with no bound method is. `mojo_closure_free` (the lambda
   case's kind) would be wrong here: it frees a bound method and drops its
   `_reg_bound_method` entry.

**Why it still is not a "free it after the call" change.** The env var is
declared with `gen._declare_var` at the nested-`def` STATEMENT
(`emit_funcs.py:104`), i.e. function-scoped, and the same env legitimately backs
several calls (`return inner(1) + inner(2)`). So the free has to go where the
lambda case's does — the ownership machinery's scope exits
(`_owned_free_candidates` / `_scope_register` / `_emit_scope_frees`, plus the
`mojo_cleanup_push_ptr` thunk at the declaration) — which is also the only place
that gets `break`/`continue`/`return` right. That is a real piece of work in the
one subsystem whose failure mode is a use-after-free, and it is why it wants a
session that can run `gimple_owned_closure_env_is_freed`'s siblings plus the
gate.

### Regression

`test_gimple_bounded_memory` is the right helper for the fixed shape (the
existing `gimple_owned_closure_env_is_freed` is exactly that for the lambda
half), sized so the leak is several times the limit: OPEN 1's own 16 B/iter
needs ~4M iterations to reach a 64 MB ceiling, and `gimple_owned_closure_env_is_freed`
already uses a bounded loop, so the same shape works. Pair it with a
`test_gimple_stdout` case for the multi-call body (`inner(1) + inner(2)`), since
"the free happened after the first call" is the failure a slope alone would not
catch — the second call would read freed memory and print garbage, which the
stdout assertion does catch, and MallocScribble is already on in
`run_executable_stdout`.

## Status (2026-10-01 — the CLOSURE half is closed and regression-tested; the nested-`def` and boxed-local halves are OPEN, with measurements)

### Closed: a capturing lambda bound to a local, and the environment it captured

Measured flat, output unchanged, at 100k and 400k iterations (was ~74 B/iter):

```mojo
def work(n: Int) -> Int:
    var t = 0
    for i in range(n):
        var f = lambda x: x + i
        t += f(1)
        if i == 2:
            continue
        if i == 4:
            break
    return t
```

The value and the `malloc(sizeof env)` its constructor allocated with it are
ONE allocation unit, freed by `mojo_closure_free` at the end of the owning
loop body and before every `break`/`continue`/`return` that leaves it; at
function level the same pair is freed at each return, and an exception raised
between the declaration and the scope exit frees it through the
`mojo_cleanup_push_closure` thunk the declaration pushed. The registry rule
came first, because freeing a bound method without discarding its
`_reg_bound_method` entry is a use-after-free: the address goes straight back
to `malloc` and `mojo_is_bound_method` then reports whatever landed there as
a bound method, so `mojo_fnptr_call_N` dispatches through two words of it.
The free is chosen by `ownership_destruct.lambda_value_owned` — after the
binding, the only acceptable mention of the name is as the CALLEE of a call,
and a mention inside a nested `def`/`lambda` is rejected outright (a capture
into an environment that can outlive the scope).

Tests: `gimple_owned_closure_env_is_freed` (bounded memory; loop body with
break/continue, function level, non-capturing, raised-past) and
`gimple_closure_that_escapes_is_not_freed` (stdout; stored, aliased and
captured closures must survive — the stored one is CALLED after its scope
exited). Both fail when the rule is disabled: 112 MB against a 40 MB limit,
and a SIGSEGV respectively.

### OPEN 1: a nested `def` whose closure is created and called without ever being bound to a local — 16 B/iter

```mojo
def helper(n: Int) -> Int:
    def inner(x: Int) -> Int:
        return x + n
    return inner(1)
```

Peak RSS 3.05 MB at 100,000 iterations, 7.64 MB at 400,000. The environment
and the bound method are built where the nested `def` is lowered and the call
consumes them immediately, so there is no local to own: this is a CLASS C
temporary (doc/MEMORY.html §3.C) whose consumer is a call through the
closure, and class C's freshness test
(`emit_infra.is_fresh_container_operand`) does not recognise a
lambda/`def`-producing value.

Next step: a `gen._closure_vals` entry survives into the CALL, so
`mojo_fnptr_call_N`'s emission site (`emit_calls`, the `mojo_is_bound_method`
dispatch) can free a closure it was handed as a callee — the same
"create and consume in one lowering" shape `claim_loop_iterable_temp` already
handles for `for x in <fresh>`. The value reaching the call is the lifted
function's name, not the `MojoBoundMethod *` (see the generated C:
`_t3 = mojo_fnptr_call_1 (f, _t2)` with `f` the local), so the entry has to
be keyed on the local the `def` was bound to — and a nested `def` statement
binds no local, which is the actual reason this is a separate piece of work
rather than a special case of what landed.

### OPEN 2: the box for a mutable captured local — `malloc(8)` per call, per variable

`_emit_mut_local_box_allocs` (runtime `fire_runtime.c`'s
`mojo_cleanup_*` aside, `mojo/backend_gimple/emit_infra.py`) mallocs one cell
per `{mut}`-captured local in the function PROLOGUE, so the cost is per call
rather than per closure creation.

NOT attempted, and the reason is the same one that keeps the escape rules
narrow above: the box is what the closure's environment holds — the env field
IS the box pointer — so the box's lifetime is the CLOSURE's, not the
function's. Freeing it at the function's return requires proving no closure
built here outlives the call, which is the escape analysis
`ownership_destruct.lambda_value_owned` does not do (it answers the opposite
question: whether a closure can be freed at ITS scope's exit). The two would
have to be answered together, and a `{mut}` box reachable from a returned
closure is a use-after-free.

Next step: extend `lambda_value_owned` to the reverse direction — "no closure
built in this function escapes it" — and free the box at the same exit where
the env is. The same analysis would then let the env itself be freed at
FUNCTION level for a closure stored in a local that never escapes, which is
OPEN 1's other half.

## The original finding (2026-09-28) follows


A loop that creates a capturing lambda and calls a function containing a
capturing nested `def` leaked about 90 B per iteration (peak RSS 13.9 MB at
100,000 iterations, 41.0 MB at 400,000). The pieces: the environment struct
(`malloc(sizeof env)` per closing lambda/nested def), the bound-method object
that wraps it (`mojo_bound_method_new`: a `malloc` plus an entry in
`_reg_bound_method` that is never removed), and the box for a mutable captured
local (`malloc(8)` in the function prologue, once per call).

### Re-measured 2026-09-30, with `tools/mem_slope.py`

`tools/mem_slope.py` is the instrument `doc/MEMORY.html` §8 asks for (two sizes,
peak-RSS slope, plus the stale-binary and output-drift guards §8 warns about).
Probes live in `build/memprobes/`. One shape, `{mut}` capture + nested `def` +
bound method, called once per iteration:

    +32.17 B/iter   (4.62 MB at 100k, 13.83 MB at 400k)

That is one `malloc(8)` box + the env struct + `mojo_bound_method_new` per
call, all class E, all still unfreed. The number is lower than the ~90 B in the
Status line above because that figure was for a shape with BOTH a capturing
lambda and a capturing nested `def`; this is the nested-`def` half.

### What was removed from this leak (2026-09-30)

`ownership_destruct.analyze_returns_fresh` refused to call ANY function
fresh-returning if it contained a nested `def`/`lambda` anywhere, on the theory
that a closure might keep the returned container. The parser now records an
explicit capture list (`FunctionDef.captures` / `has_capture_list`), so the
refusal is decided against the actual capture set: a nested `def` with a
name-only list cannot capture a returned name outside it, and `{}` captures
nothing. Anything less certain (no list, a bare `{mut}`/`{var}`, any `lambda`)
still refuses, as before.

Measured on `build/memprobes/callee_returns_fresh.mojo` — a callee that defines
a callback and returns a fresh container, whose caller binds the result in a
loop — with everything else held constant (the old behaviour reproduced exactly
by forcing the capture set to "unknown"):

    before   +138.50 B/iter   (14.77 MB at 100k, 54.39 MB at 400k)
    after     +32.17 B/iter   ( 4.62 MB at 100k, 13.83 MB at 400k)

106 B/iter of the old figure was the CALLER failing to own the callee's fresh
container, which had nothing to do with the closure machinery this file is
about. What remains is exactly the closure cost above: the control probe with
the nested `def` deleted is flat.

## Why it is not a small change

1. **The closure's own lifetime.** All three die with the creating scope only
   if the closure never escapes: it is bound to a local that is only ever
   *called* (never returned, stored, passed on, or captured by another
   closure). That is a new escape analysis over callables. **CLOSED** — see
   `ownership_destruct.lambda_value_owned`.
2. **Functions containing a nested `def`/`lambda` are excluded from ownership
   analysis entirely** (`_is_free_eligible_function`), so they also get no
   container freeing. Two traps:
   - inside a closure the analysis still treats `d[k]`, `d.x`, `d[a:b]` and
     `for x in d` as safe receivers, so `lambda k: d[k]` would NOT disqualify
     `d`. The receiver rules must be switched off when `in_closure`; **STILL
     OPEN** — the closure work deliberately did NOT lift this exclusion,
     because the rule it guards is about containers and lifting it is a
     separate piece of work. That is why a function with a lambda in it still
     gets no container freeing today.
   - a nested function is lowered in the middle of its parent, and its
     `begin_function` resets every per-function ownership table
     (`_owned_free_candidates`, `_scope_live`, ...). The parent's state would
     be lost or, worse, stale. **DONE for the tables that have to survive it**:
     the per-FUNCTION ownership tables now reset in `_reset_scope_state`
     (reached from `begin_function`/`reset_no_candidates`) rather than in
     `_reset_func`, which a lifted closure also runs — so the parent's entries
     survive the closure's lowering intact. The TEMP tables
     (`_fresh_vals`, `_fresh_str_tmps`) deliberately still reset in
     `_reset_func`, next to the `temp_counter` that makes their reset
     necessary; that loses frees across a lambda, which is the safe direction.
3. `_reg_bound_method` needs a way to drop an entry when the bound method is
   freed (or bound methods need an in-band tag instead of a registry).
   **DONE** — `mojo_bound_method_free` (a method value: the receiver is not
   ours) and `mojo_closure_free` (a capturing lambda: `self` is the env it was
   allocated with), with `mojo_cleanup_push_closure` for the unwind.

### Note on item 2, after the 2026-09-30 work

Item 2 is still exactly true and `_is_free_eligible_function` is deliberately
UNCHANGED — the two traps above are not addressed, and lifting it would risk a
wrong free, which is the one failure mode this analysis is built to have none
of. The capture-set machinery that would make lifting it tractable now exists
(`ownership_destruct._nested_capture_names`, used by
`analyze_returns_fresh`), so item 2 is closer to doable than it was, but it is
not done. `analyze_returns_fresh` and `_is_free_eligible_function` ask the same
question on opposite sides of a call — the callee may now be proven fresh with a
closure in it, while the caller's own body with a closure in it is still
excluded — which is intentional, not an inconsistency to tidy away.

## Done when

The loop above is flat between 100k and 400k iterations, output unchanged, and
`lambda k: d[k]` with `d` a local container demonstrably keeps `d` alive (add
both as runner tests). `make gate` green. **The first two of those three are
done**; the third needs trap 2's first bullet, above, and is a container
question rather than a closure one — so it belongs with that work, not here.
