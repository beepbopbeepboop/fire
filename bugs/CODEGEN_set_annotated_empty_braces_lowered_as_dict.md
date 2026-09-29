# CODEGEN: `var s: Set[Int] = {}` is lowered as a dict and refused at coercion

## Status (2026-09-28 — OPEN, reproduced at HEAD, cause not investigated)

```mojo
def main():
    var s: Set[Int] = {}
    var acc = 0
    for i in range(10):
        s.add(i % 5)
    for i in range(10):
        if (i % 7) in s:
            acc += 1
    print(acc)
```

fails to compile: `cannot coerce MojoDict * to MojoSet * (incompatible
container kinds) ... value='_t1' dest='s'` (the R2 refusal in
`_safe_coerce_emit`). The same program with `var s = Set[Int]()` builds and
runs. A smaller program that only calls `s.add(1)` and `len(s)` compiles, so the
failure needs the membership test or the loops on the set. Reproduced identically
on a clean checkout of master, so it is not new.

The empty `{}` is a dict display; in Mojo the annotation should decide it is a set.
Whether the fault is in the display lowering ignoring the annotation, or in the
declaration's stack-allocation path picking a container kind from the display
alone (`emit_infra._empty_ctor_ctype` answers `MojoDict *` for any `{}`), is not
established.

## Done when

`var s: Set[Int] = {}` builds and behaves like `Set[Int]()`; add the repro as a
`test_gimple_runner.py` case.
