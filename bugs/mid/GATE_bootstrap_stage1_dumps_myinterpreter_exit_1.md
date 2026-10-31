# GATE: `make bootstrap` fails `bootstrap-stage1-dumps:myinterpreter.py` (exit 1, 5 s)

## Status (2026-10-31, OPEN, cause found, fix not started)

Reported from a run of `make bootstrap` on `up-laptop:mojo-reference2`. The run
printed the memslot queue for the stage1 dump items, then:

```
suite: 10 tests, -j18, parallel, 96 GB memory budget
memslot: bootstrap-stage1-dumps:bootstrap_test_edge_cases.mojo wants 4.0 GB; 4.0 of 96.0 in use, 2 ahead in line: waiting
... (the same for bootstrap_test_expressions, _loops, _stress, class_jit, hello, mojo, t_arith)
  FAIL     bootstrap-stage1-dumps:myinterpreter.py  (5s)  exit 1
```

What the report shows:

- The `memslot: ... waiting` lines are queueing, not the failure. Eight items
  wait for 4 GB each against a 96 GB budget (`t_arith` alone holds 28 GB).
  Nothing in them is an error.
- The only failure is `bootstrap-stage1-dumps:myinterpreter.py`, exit 1 after
  5 s. The job's own output (why it exited 1) is not in the pasted text.
- 5 s is short for a whole-file dump, so the job probably died early (a
  compile or import error), not during the compile itself.

Exit reason, from `../mojo-reference2/build/suite.log` (the job's own output):

```
compile_to_gimple failed: cannot compile module: function(s)
_mojo_struct_iter_steps (generator function(s), contain a `yield`/`yield from`)
— this codegen compiles every function into a single straight-line C function
and has no suspend/resume state-machine ...
RuntimeError: cannot compile module ... (module_gen.py gen_module_impl)
```

Cause: `myinterpreter.py` line 2522 defines `_mojo_struct_iter_steps`, a
generator (`yield` values from `__next__`). It was added by 422ab8a9
(2026-10-30, "interpreter: next()/iter()/for/comprehension drive a user iterator
struct"). The stage1 `--dump` of `myinterpreter.py` then goes through the
straight-line codegen, which refuses any module containing a generator. So the
job is not a runner or memory problem: the source introduced a generator that
the dump path cannot compile. It passed before 422ab8a9.

Not known yet: whether the stage1 dump should compile generators (the
coroutine backend) or the source should avoid one, whether it reproduces on
master, and whether it
is caused by the memslot wait (a timeout that counts the queue, which the
runner is supposed to avoid: a job's TIMEOUT starts after admission).

## Next step

1. Decide: the dump must compile `myinterpreter.py`'s generator through the coroutine path, or the source must stop using one in a module the dump compiles (422ab8a9 is the change to look at).
   Reproduce: `make bootstrap` (or `python3 tools/suite.py bootstrap`) on a
   clean master tree.
2. Read the failing job's full output in `build/suite.log` (the FAIL block
   names the job's argv and its complete output). Record the first error line
   here.
3. If the failure is a compile or runtime error in `myinterpreter.py`'s dump,
   fix its root cause and add a regression test. If it is the runner (a
   timeout started during the memslot queue wait), fix the runner and say so.
4. Gate the change with `make gate` once at the end of the batch.

## Related

- `bugs/CODEGEN_bootstrap_resource_blowup.md`: the bootstrap memory/time cost
  (the stage2/stage3 whole-closure compiles), a different job.
- `bugs/CODEGEN_gate_bootstrap_stage1_transitive_red.md`: the
  `bootstrap-stage1-transitive` job going red, a different job.
