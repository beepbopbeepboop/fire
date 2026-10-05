# FORMAL_printf_of_a_call_result: the call runs, prints nothing, and its return value becomes the process exit status

**Area:** both formal backends' `printf` argument lowering
(`formal/arm64_codegen.py` and `formal/x86_64_codegen.py`'s `printf` rewrite).
**Found 2026-10-04 on `work/formal28-6`** while fixing
`formal/model.py`'s `blob_loop_growth` — the companion fix, landed in
commit `1ec3467d`, which is the change that made a list grown in a loop
reserve for its last iteration.
**NOT fixed** — filed, measured on BOTH architectures, with the exact next step.
Pre-existing: it reproduces with the four production files of that fix reverted.

## What I ran

`printf` with a CALL as one of its `%d` arguments, both backends, no Lean:

```console
$ python3 tools/memslot.py --gb 8 --label t -- python3 .tmp/printf_call.py
[(0 or exit), '', '']
```

```python
src = ("def g(a: Int) -> Int:\n    return 7\n"
       "def main(n):\n    printf(\"v=%d\", g(1))\n    return 0\n")
```

## What I saw

| | arm64 | x86-64 |
|---|---|---|
| exit status | **7** | **7** |
| stdout | **empty** | **empty** |
| stderr | empty | empty |

CPython prints `v=7` and exits 0. So the call *happened* — its return value is
demonstrably the process's exit status, which is `main`'s status by definition,
and `main` returns 0 — and the `printf` produced no output at all.

**This is a two-backend agreement on a wrong answer, which is why it is worth
filing rather than reading as a curiosity.** Both machines print nothing, so no
parity test can see it: the subject is the shared `printf` argument path, and
`test_formal_run.py`'s `both_arch_names` rows all pass on programs whose
`printf` arguments are simple names.

## Why it matters beyond this program

`printf("...", f(x))` is the ordinary way to print something a function
computed, and `main` is required to return 0 in this tree's corpus (every
answered case in `test_formal_run.py` expects exit 0). So the observable
failure is: **a program that prints nothing and reports the callee's return
value as its own exit status** — which is worse than a wrong number, because
the exit status is what a caller and a test harness read.

It also masked a real defect while I was looking for it. The program

```mojo
def g(a: Int) -> Int:
    var s = [0]
    for i in range(70):
        s = s + [1]
    printf("len=%d", len(s))
    return 0
def main(n):
    g(1)
    return 0
```

prints `len=71` on both machines (that is `range(70)` with the fix in the
companion doc), and the same `g` reached as `printf("len=%d", g(1))` printed
**nothing** and exited **71** — the callee's return value. So the first version
of that measurement read "the callee returns 71" as the exit status of a
`printf`-with-a-call, and it took reading the two programs side by side to see
that the `printf` was the thing broken.

## The exact next step

1. Find where a `printf` argument that is a `CallExpr` is lowered. The rewrite
   `print` → `printf` is already shared (`formal/model.py`'s
   `string_method_yields_string`-adjacent call builders are the pattern), and the
   argument list is emitted left to right with each argument's value in the same
   register the general expression path uses — so the first thing to read is
   whether a call in argument position leaves its RESULT where the argument
   loop expects it, or whether the call clobbers the register the loop is
   carrying the already-emitted arguments in.
2. Then decide the fix. Two candidates, and they are not the same size: the call
   result needs a spill slot before the call (a register allocator question) or
   the whole argument list has to be evaluated into the stack first (an emission
   order question). The first is smaller; measure which one the current code
   shape implies before choosing.
3. **Pin it in `test_formal_run.py`'s `BOTH_ARCH_CASES`** with
   `("both_arch_printf_of_a_call_result_prints_the_value_and_exits_zero", …,
   0, "v=7")`. That row fails today on both machines, which is the acceptance
   test; `main` returning 0 while the status is 7 is the load-bearing half,
   because a fix that printed `v=7` and still exited 7 would have fixed the
   symptom.

## Reproducing

    python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_run.py \
        both_arch_printf_of_a_call_result_prints_the_value_and_exits_zero

(the row does not exist yet — step 3 is what adds it, and it fails on this
tree).