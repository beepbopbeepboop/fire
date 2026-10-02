# `MojoExpr.call` carries ONE argument, so a call with two arguments has no faithful AST and `eval_eq_mojo` is false

**Area:** FORMAL (the proof layer's AST bridge). **Status: OPEN — not fixed;
minimal reproduction below, and the smallest possible one is TWO arguments.**
Found 2026-10-02 while wiring the SysV stack-argument convention's proof half.

**Sibling, not duplicate, of `bugs/FORMAL_ast_bridge_binds_only_the_first_parameter.md`.**
That one is about a function's own PARAMETER LIST: `MojoFunc.mk`'s single
`param`, `evalFunc`'s single `arg`, and the generator reading `binders[0]`. This
one is about the arguments of a CALL, which is a different declaration and a
different place in the evaluator, and it is not on that doc's list of steps — so
closing that one does not close this. Both have to be closed before a
seven-argument function is provable, which is why both are here.

## The smallest reproduction

```
$ cat .tmp/two.mojo
def f(a: int, b: int) -> int:
    return a + b

def main() -> int:
    return f(1, 2)

$ python3 fire.py build --formal --backend=x86_64 -o .tmp/p2 .tmp/two.mojo
build: proof check failed: p2_proof.lean:44:57: error: unsolved goals
n : UInt64
⊢ False
```

Two declarations in the file then admit a `sorry` (lines 88 and 505), which is
what the build reports as "2 admitted a sorry" — the chain after the failure is
dead, not proved.

## What the generated file says

```lean
def f_go (a : UInt64) (b : UInt64) : UInt64 := a + b
def main_go : UInt64 := (f_go (UInt64.ofNat 1) (UInt64.ofNat 2))      -- right

def ast : MojoFunc := MojoFunc.mk "main" "" ([MojoStmt.return
  ((MojoExpr.call "f" (MojoExpr.int (UInt64.ofNat 1))))])            -- one argument
```

`lib/ProofLib.lean`:

```lean
| call (name : String) (arg : MojoExpr)                             -- line 735
...
| MojoExpr.call name arg => callFunc name (evalExpr callFunc arg env)   -- line 848
```

So `eval_eq_mojo` — which is stated with the bridge's own stub for `callFunc`
(`fun name arg => if name = "main" then mojo arg else 0`, so a call to a user
function evaluates to **0**) — asks Lean to prove `0 = 3`. That is `⊢ False`, and
no amount of `simp +decide` closes it: the two sides of the statement are about
different functions.

**The model is right and the AST is the copy that is wrong**, which is the shape
to look for: `main_go` was widened by `_gen_go` (the docstring at
`formal/arm64_proof_gen.py:1073` records that it used to be one parameter
unconditionally) and the AST generator was not. The compiler-level arity guard
in `_go_apply` checks the model's arity and the ENTRY POINT's, not a call's.

## Why it is silent about it

A program whose `main` calls a user function and then returns a constant that
happens to agree with the stub proves fine, and there are three such programs in
`formal/examples` (`wide_recv`, `subscript_var` — method calls, which are not
`MojoExpr.call` at all — and any example that discards the result). That is why
nothing caught it: the disagreement only becomes visible when the call's value
REACHES the result, and no example in the corpus does that with more than one
argument. The 24-argument case is the first program here where it is visible
(`⊢ False` at the same line 44, with
`MojoExpr.call "wide24" (MojoExpr.int (UInt64.ofNat 1))` for a 24-argument
call).

## On arm64 the same program fails EARLIER, and differently

```
$ python3 fire.py build --formal --backend=arm64 -o .tmp/p2a .tmp/two.mojo
NotImplementedError: universal theorem: the call at 0x100000244 targets
0x100000258, a second function in the same image.  The machine model follows it
-- every byte is present, and the callee's `ret` returns through `x30` -- but the
CFG walk is per-function, and following the call means entering the callee's
blocks and then dispatching on `x30`, whose value is a property of the call path
rather than of the block.  That is interprocedural walking: a return-address map
in the framework, not a missing case here.
```

So on arm64 a call to a user function is REFUSED (loudly, with the reason), and
on x86-64 it is emitted and its AST bridge is false (quietly, as `⊢ False`).
That difference is itself worth knowing: **the x86-64 side is the one to fix
first**, because an emitted proof that cannot hold is worse than a refusal, and
because the x86-64 path is the one this round is making provable at all.

## The exact next step

1. `lib/ProofLib.lean`: `MojoExpr.call (name : String) (args : List MojoExpr)`,
   and `evalExpr`'s arm becomes
   `callFunc name (foldl (· *· ) 1 (args.map (evalExpr callFunc · env)))` —
   `u64pow`/`u64powGo` are already in the library for a reason, and a product is
   the only shape the stub can consume, since `callFunc` is `String → UInt64 → UInt64`.
   **That is the real obstacle and it is a change of what the bridge CLAIMS:** the
   stub answers 0 for a user function's name, so a correct AST for `f(1, 2)`
   still evaluates to 0 and `eval_eq_mojo` is still false.  So step 1 alone makes
   the generated text honest and the theorem still unprovable.
2. Therefore also: the generated `eval_eq_mojo` cannot be stated for a program
   with a call until `callFunc` is the model's own function table rather than the
   `if name = "main"` stub. `_gen_go` already emits `f_go`; what is missing is
   wiring it into the bridge, and that is the same "the model is right and
   everything that APPLIES it is wrong" that
   `bugs/FORMAL_ast_bridge_binds_only_the_first_parameter.md` is about.
3. Then a test: a program whose `main` returns a two-argument call's value, built
   with `--formal` on both backends, asserting the proof file typechecks. It
   cannot be written before step 2, which is why the fix is a fix and not a
   table edit — and it is the assertion that fails today as `⊢ False`.

Until then the honest statement is: **no program in this tree can have the VALUE
of a two-argument-or-wider call proved**, and the compiler half of that
convention is proved only by execution
(`both_arch_twenty_four_arguments_arrive` in `test_formal_run.py`, which builds
and runs both backends and diffs against 241).