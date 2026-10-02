# Four more walks stop at an `elif`, and `random.mojo` has two constructs past the ones that are fixed

**Area:** FORMAL (the build pass's rewrites) and the stdlib's
`std/testing/prop/random.mojo`.
Found 2026-10-02 on `work/formal5-slice-env-random`.
**PARTIALLY FIXED on that branch — this is what is left.**

The cause this worker was given is the sweep's `other refusal` row: 12 files,
`builtin_slice.mojo` x8, `random.mojo` x1, `env.mojo` x1,
`bootstrap_test_classes.mojo` x2. All of the reachable part of it is now fixed
on `work/formal5-slice-env-random`; this file records the two things that are
not, both of which are other people's rows.

## Part 1: the `elif` hole, four sites deep, one fixed

`IfStmt.elifs` is a list of TUPLES — the only container in the statement tree
that is not a list — so a walk that recurses on `isinstance(node, list)`
descends every `if` body and every `else` and stops dead at the first `elif`.
`model.iter_nodes` tests `(list, tuple)` and walks all of them, which is why the
READERS and the REWRITERS disagree and the symptom is always a check reporting
something false about a program a rewrite already handled.

**Fixed on that branch:** `formal/build.py`'s `_rewrite_method_calls` and
`_rewrite_one_word_field_method_calls`, both moved onto the new shared
`model.rewrite_tree`. Measured before, arm64 and x86-64 identically:

```
struct Rng:
    def _next(self, max: Int) -> Int: return max
    def rand_scalar[T: Int](self, lo: Int, hi: Int) -> Int:
        if lo > hi: return 0
        elif T == 2:
            var diff = hi - lo if hi > lo else lo - hi
            var uint64 = self._next(diff)      # <-- never lifted
            return uint64 + lo
        else: return hi
```

```
build: Rng_rand_scalar: self._next is not a field of Rng — _next is one of its
METHODS … Call it (`self._next(...)`), which is a receiver and a call and
lowers
```

i.e. refused for not having parentheses it has. Deleting the `elif` (an `if`
with the same body) builds and computes 9, so the arm is the whole of it. Pinned
by `test_formal_run.py`'s `method_call_in_an_elif_arm_is_lifted` next to its
`method_call_in_an_if_body_is_lifted` twin.

**NOT fixed — the same hole, four more sites, each with its own consequence.**
All four are in `formal/build.py` and all four recurse on `isinstance(node,
list)`; the line numbers are from `24068a01` and will move.

| site | line | what it rewrites | what an `elif` arm costs |
|---|---|---|---|
| `_rewrite_self_fields` | 6624 | the one-word field identity `self._inner` -> `self` | **a silently wrong answer.** The identity does not fire in the arm, so a field read there reads a name that is in no register home and no frame slot. On the same source that is the wrong number rather than a refusal, because the arm's field was never collapsed and the emitter's own refusal is what catches it — I did NOT measure the wrong-answer case, only the mechanism. |
| `_rewrite_one_word_nested_field` | 4336 | the frame-slot half of the same identity, `o.in1.a` -> `o.in1` | same shape, same direction. |
| `_apply_receiver_writeback` | 6559 | `c.bump()` -> `c = c.bump()` for a one-field mutator | **a dropped store.** The call site's store is never applied, so the mutator's new value is computed and discarded — which is exactly the defect `_apply_receiver_writeback`'s own docstring records as measured ("the program built, ran, and printed the value the caller had"). |
| `_rewrite_dotted_child` | 7568 | a read of a class-level constant published by another module | a read that was supposed to be folded to a literal stays a name; the module-slot pass then decides its fate. |

**The next step** is mechanical and is one line each: move each onto
`model.rewrite_tree`, keeping the `None`-means-stop discipline that
`_rewrite_method_calls`' conversion needed (two of the four replace a node in
its parent's slot, which is the case `rewrite_tree`'s docstring covers as "any
other value"). Do them ONE AT A TIME with `test_formal_run.py` after each —
`_rewrite_self_fields` and `_apply_receiver_writeback` both have measured
wrong-answer failures behind them, so "the suite is green" is a weaker signal
for these two than it was for the method-call rewrite. That is also why this
worker did not do them in the same commit: three sites with no case of their own
is how a refactor stops being a refactor.

## Part 2: `std/testing/prop/random.mojo`, past the two that are fixed

Fixed on that branch: the `self._next` refusal above, and the `comptime if`
locals (`_lbn_walk` in `mojo/middle/boundnames.py` knew neither
`ComptimeIfStmt` nor `ComptimeForStmt`, so a name bound in a comptime branch got
no register home — `"'a' has no home: the register allocator collected no home
for it, so the emitter and the allocation walk disagree"`, which blames a
disagreement between two passes instead of naming the walk both should share).
`rand_scalar` declares `offset`, `a`, `b`, `diff` and `uint64` in comptime arms,
so that one blocked the file on its own.

**What is left, measured, in the order the build reaches it.** To get past the
file's own `from std.random import random_ui64, seed as seed_fn` I copied
`Rng` verbatim into `.tmp/` and stubbed only the two imported functions — every
other construct is the stdlib's own text.

1. **`Rng(seed: 7)` does not parse.**

   ```
   build: parse error: rng_full.mojo:186:16: Unexpected COLON(':')
   ```

   The constructor is `def __init__(out self, *, seed: Int)` — KEYWORD-ONLY —
   and a call with a keyword argument does not parse. That is a parser gap in
   shared `fire_compiler.py` and it is emphatically not this worker's; whoever
   owns keyword arguments in a call has it.

2. **With the keyword-only marker removed, a no-field struct with a required-arg
   `__init__` cannot be constructed at all.** `Rng()` refuses with "constructing
   Rng with 0 argument(s) is a call to a user-defined `__init__` and none of
   them takes that count … Rng declares 1 `__init__` overload (1 required
   (seed))", and `Rng(7)` refuses with "constructing Rng with 1 argument(s) does
   not match its fields (no fields at all)". The message for the first is TRUE
   and the program is the stdlib's; the gap is that a struct with NO fields and a
   constructor that only calls something else has nothing to inline.

3. **With the constructor reduced to `pass`, the file reaches its real
   remaining gap**, which is NOT this worker's and is a project:

   ```
   build: rebind[…](…) calls a name this unit does not compile, so the brackets
   cannot be bound … If `rebind` is a generic of another module then its
   instantiation is the boundary symbol, one per set of type arguments
   (doc/ABI.md §Generics), and this path does not monomorphize, so there is no
   callee here to pass them to
   ```

   `rand_scalar`'s first arm is `return rebind[Scalar[dtype]](Scalar[.bool](self.rand_bool()))`.
   Generic MONOMORPHIZATION across a module boundary is
   `bugs/FORMAL_known_limits.md` §1.2 "Stage 5" and it is a project, not a patch.

**And the closure, which is not the file's own business at all.** Measured on the
real file, `std/testing/prop/random.mojo`'s build stops one level out:

```
build: prop_random.mojo imports 'std.random', which cannot be built either:
time.mojo: _gettime_as_nsec_unix: 'CompilationTarget' is imported from 'std.sys',
and it is a module-level name of another module …
bugs/FORMAL_module_state_no_storage.md records the design and what would have to
be true to close it
```

That is `bugs/FORMAL_module_state_no_storage.md`, owned by `formal3-5`. The
honest accounting for this file, then: **its own body is two constructs closer to
building (three with the parser fix) and it is behind a documented value-model
limit in a module it only imports.** Reporting it as "random.mojo is fixed" would
be false; reporting it as "0 files gained a PASS" would also be false, because
the two constructs this worker removed were the ones naming `random.mojo`.

## What was NOT measured

* I never got `random.mojo` itself to build, so the claim "its body is two
  constructs closer" rests on the `.tmp/` copy with two functions stubbed, not
  on the real file. The copy is the stdlib's own text everywhere else.
* I did not measure the wrong-answer case for `_rewrite_self_fields` in an `elif`
  arm. The mechanism is the same one its own docstring records and the
  consequence is claimed by analogy, which is weaker than a number.
* x86-64 was measured for every claim here EXCEPT the `elif`/`comptime`
  reproducers' refusals: both were reproduced on arm64 and both were then fixed
  in shared code (`model.rewrite_tree`, `_lbn_walk`) with a both-architecture
  run of the combined program confirming the answer (`v=54` on each). Every
  refusal message in this file is arch-free and comes from shared code, so the
  two architectures cannot have differed — but that is an argument, not a
  measurement of the refusals themselves.
* `bootstrap_test_classes.mojo` (the other two files in the sweep row) was not
  reproduced. Its sweep entry is the returned-frame refusal
  ("create_point returns a frame address … and create_point is this image's
  ENTRY"), which is `bugs/FORMAL_returned_frame_*.md` and `formal3-3-r2`'s.