# CODEGEN: closure environments and boxed mutable locals are never freed

## Status (2026-10-02 — OPEN 1 is CLOSED. OPEN 2, the mutable-capture box, is
## still open and is the only thing left in this document)

Landed: a nested `def`'s environment is now owned by the function it is a
statement of and freed at that function's scope exits. `tools/mem_slope.py` on
the same probe that measured `+16.1 B/iter` reports **flat** (`+0.00 MB` over
300,000 iterations, 1.56 MB at both 100k and 400k), with stdout unchanged.

**The shape of the fix, which is smaller than this document's earlier "Next
step" said and does NOT use a bound method at all.** There is no
`MojoBoundMethod`, no `mojo_bound_method_new`, and no `_reg_bound_method` entry
in this shape — the nested `def`'s call sites are DIRECT:

```c
int64_t __GIMPLE helper (int64_t n) {
  helper_inner_env * _env_inner;
  _env_inner = _alloc_helper_inner_env ();
  ...
  _t2 = helper_inner (_env_inner, _t3);      /* direct, not through a value */
  _t5 = helper_inner (_env_inner, _t6);      /* one env, two calls */
  return _t5;                                 /* freed here now */
}
```

So the earlier next step — "a `gen._closure_vals` entry survives into the CALL,
so `mojo_fnptr_call_N`'s emission site can free a closure it was handed as a
callee" — targets a symbol this program never emits, and the earlier
diagnosis that a `MojoBoundMethod` is involved was simply wrong. What is
needed is a plain `free(_env_inner)`, because there is no registry entry to
drop, and `mojo_closure_free` (the capturing-lambda case's kind) would be
actively wrong: it would read two words of a `helper_inner_env *` as a bound
method. The unwind entry that does apply is the one already in the runtime,
`MOJO_CLEANUP_PTR` / `mojo_cleanup_push_ptr`, documented in `fire_runtime.c`
as "a plain malloc/calloc block: a struct instance" — which is exactly what a
bare env with no bound method is.

**Where it landed, and why that placement.** The three things the analysis
needed already existed, so nothing new was invented:

1. the ownership question is `ownership_destruct._lambda_uses_ok(body, name)`
   — "is every mention of this name the CALLEE of a call?" — which answers
   True for `return inner(1) + inner(2)` and False for every shape that can
   outlive the scope. It is now named for what it owns
   (`ownership_destruct.nested_def_env_owned`), because the question is the
   same as `lambda_value_owned`'s and the TEARDOWN is the difference; a nested
   `def` binds no local, so there is no callable value to own.
2. the wiring is the capturing-lambda case's wiring —
   `ginf.register_nested_env_free` registers the name, emits the
   `mojo_cleanup_push_ptr` thunk at the declaration, and lets
   `emit_return_frees`/`emit_fallthrough_frees` free and cancel it. The env var
   is function-scoped (`gen._declare_var` at the nested-`def` STATEMENT) and
   one env legitimately backs several calls, so the free has to be at the
   enclosing function's scope exit, not after a call. It is deliberately NOT
   `_scope_register`ed: there is no loop body to register against, so the
   `break`/`continue` half of the block machinery does not apply.
3. `mojo_cleanup_cancel_n` at the free cancels the thunk, so an exception
   raised between the declaration and the return frees it exactly once.

**Two traps this hit on the way, both of which are the SAME trap item 2 below
names, and both of which had to be fixed for the free to be safe rather than
merely effective.** They are recorded here because neither is visible in the
generated C for the OPEN 1 shape — you only find them by running the suite:

- **A lifted closure lowered inside another function's body.** Lifting `mid`
  lowers `inner`'s environment statement while the ownership code is still
  reasoning about `outer`. `outer`'s body never mentions `inner`, so the
  question "can `outer` hold `inner` past its own scope?" answers "yes, safe",
  and

  ```python
  def outer():
      total = 0
      def mid():
          def inner(k):
              nonlocal total
              total = total + k
          return inner          # a real escape
      f = mid(); f(3); f(4)
  ```

  emitted `free (_env_inner)` in `mid` immediately after handing that same
  pointer back as its return value. The caller's first `f(3)` then dereferenced
  freed memory — SIGSEGV, `test_nonlocal.py`'s "two closure levels deep" pair.
  `mid`'s own body does mention `inner` as a returned value, so the same rule
  asked of the right body declines to free it. Fixed by reading the owning body
  once, at the top of `_gen_stmt_FunctionDef`, where `_cur_func_body` is
  provably the body being lowered; this needed no save/restore, because that
  statement is the only thing that can be lowering it.
- **The owning body was thrown away inside a struct method.**
  `_gen_struct_method` calls `_reset_func(node.body, ...)` and then
  `reset_no_candidates`, which cleared the body, so every "how is this name is
  USED?" question was answered about an empty body — which reads as "no
  mention, so nothing can hold it, free it", the opposite of fail-closed. The
  body is not per-candidate-set state and no longer resets there.

**A third finding, deliberately NOT fixed here and filed separately:**
`bugs/CODEGEN_calling_a_nested_def_fetched_from_a_container_answers_zero.md` —
`kept.append(inner)` compiles and stores correctly, but `kept[0](5)` answers
`0` instead of `base + 5`. The environment never reaches the container slot, so
a call through it has nothing to dispatch on. That is the boxed/boxed-read half
of this document's family, and it is not the free.

**Regression:** `gimple_nested_def_env_is_freed`
(`test_gimple_runner.py`, `test_gimple_bounded_memory`, 4,000,000 iterations,
40 MB ceiling). It carries all four consumers in one program: the shared
two-call body, the same inside a STRUCT METHOD, a nested `def` raised past by
an exception, and a nested `def` RETURNED to its caller and then called — the
last one is the fail-closed half, and calling it after `maker` returned is a
use-after-free if the rule is not fail-closed. Measured: **1.5 MB** after,
**63.1 MB** with the rule disabled (verified by stubbing
`nested_def_env_owned` to False, not by reverting), same stdout both ways —
so it is a real tripwire, not a limit nothing could ever reach. 4M iterations
is the size doc/MEMORY.html §8 asks for: the leak's own 16 B/iter is 64 MB
against a 40 MB ceiling.

## Status (2026-10-01 — the CLOSURE half is closed and regression-tested; the nested-`def` half has since closed too, above; the boxed-local half is OPEN, with measurements)

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

### CLOSED (was OPEN 1): a nested `def` whose closure is created and called without ever being bound to a local — was 16 B/iter

**What this section claimed, and where each claim went.** Kept because the
error is the useful part: a reader sent here by the old text would build the
bound-method machinery and free nothing.

```mojo
def helper(n: Int) -> Int:
    def inner(x: Int) -> Int:
        return x + n
    return inner(1)
```

Peak RSS 3.05 MB at 100,000 iterations, 7.64 MB at 400,000 — the leak, real.
Then: *"the environment AND THE BOUND METHOD are built where the nested `def`
is lowered ... this is a CLASS C temporary whose consumer is a call through the
closure."* **Wrong on the second half.** There is no bound method: the call is
DIRECT (`helper_inner (_env_inner, _t3)`), so there is nothing for a
call-site "create and consume in one lowering" rule to consume, and treating it
as a CLASS C temporary sends you to `is_fresh_container_operand`, which cannot
help because the value is not a container at all. It is a plain `malloc` block
whose owner is the function the nested `def` is a statement of — which is what
the fixed version records.

*Next step* (the `mojo_fnptr_call_N` dispatch, keyed on the local the `def` was
bound to, "and a nested `def` statement binds no local, which is the actual
reason this is a separate piece of work rather than a special case"): the
conclusion was right for the wrong reason. A nested `def` binds no local, so
there was never a local to key anything on — and the piece of work was not a
new mechanism but the ownership machinery's own scope exits, applied to the env
var. See the 2026-10-02 Status at the top of this file.

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

Both leaks in the loops above are flat between 100k and 400k iterations, output
unchanged, each with a runner test that fails when its rule is disabled
(`gimple_owned_closure_env_is_freed` for the lambda, and
`gimple_nested_def_env_is_freed` for the nested `def`). `lambda k: d[k]` with
`d` a local container still needs to demonstrably keep `d` alive. `make gate`
green.

**Remaining after all that: OPEN 2, the mutable-capture box, and trap 2's first
bullet.** Both are the same unfinished analysis — `_is_free_eligible_function`
still refuses to look at a function containing a nested `def`/`lambda`, so such
a function still gets no container freeing, and a `{mut}` box's lifetime is the
CLOSURE's, which means it cannot be freed until "does any closure built here
escape?" can be answered. That is the whole of what is left here, and it is one
piece of work, not two.
