# `fire.py build --formal` on `std/python/bindings.mojo` never terminates

**Status: OPEN, found 2026-10-02, not diagnosed.** A dozen workers' sweep and probe runs were found still running, the
oldest 1 day 15 hours, each burning about 55% of a core:

    fire.py build --formal --no-prove --backend=arm64  -o .../a.out ../new-modular/Mojo/stdlib/std/python/bindings.mojo
    fire.py build --formal --no-prove --backend=x86_64 -o .../a.out ../new-modular/Mojo/stdlib/std/python/bindings.mojo
    .tmp/probe_cycle.py ../new-modular/Mojo/stdlib/std/python/bindings.mojo

(work-127, -141, -144, -148, -157; all seven were killed by hand, and `tools/control.py guard` now kills any
`fire.py build` / `test_*.py` / probe past 120 minutes.) Also two `test_formal_math.py` runs (`combperm` and `-v`) had
been running 9-10 hours.

CPU use plus a never-ending compile is a fixed-point loop in the formal front/middle tier that does not converge on this
file's import closure (compare the memory-leak finding "container == is pointer identity, fixed-point loops never
terminate without GC" in bugs/PERF_memory_over_4gb_is_a_bug.md). Not Lean: these runs were `--no-prove`.

## Next step

Run it once under `python3 tools/memslot.py --gb 8 --label t -- timeout 300 python3 fire.py build --formal --no-prove
../new-modular/Mojo/stdlib/std/python/bindings.mojo -o .tmp/a.out` with a sampling profile (`/usr/bin/sample <pid> 10`)
to find the loop, then bound the pass (an iteration cap that reports a refusal naming the construct, never a silent
pass) and fix what keeps it from converging. A sweep must classify this file as a refusal or a tool timeout in a
bounded time; today it is neither. Also run `test_formal_math.py combperm` the same way: it should take seconds.
