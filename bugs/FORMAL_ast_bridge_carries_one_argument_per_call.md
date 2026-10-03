# `MojoExpr.call` carries ONE argument, so a call with two arguments has no faithful AST and `eval_eq_mojo` is false

**Area:** FORMAL (the proof layer's AST bridge). **Status: OPEN, and RE-MEASURED
2026-10-03: the minimal reproduction below is STALE — the program now builds,
runs and omits the AST bridge with an accurate one-line reason instead of
emitting a false theorem — so what is left is a PROVABILITY gap, not a
soundness one. Step 1 below is still blocked on the Lean limitation measured in
"Status: step 1 is blocked".** Found 2026-10-02 while wiring the SysV
stack-argument convention's proof half.

## Status: the reproduction is stale (2026-10-03)

The same source, on this tree, both architectures:

```
$ cat .tmp/tw/two.mojo
def f(a: int, b: int) -> int:
    return a + b

def main() -> int:
    return f(1, 2)

$ python3 fire.py build --formal --backend=x86_64 -o .tmp/tw/two.x86 .tmp/tw/two.mojo
  [proof census: two_proof.lean — 2 declaration(s) admitted a `sorry`, 0 vacuous]
Built: .tmp/tw/two.x86  [x86_64/macho]
Proof: .tmp/tw/two_proof.lean  [2 declaration(s) ADMITTED a sorry …]
$ ./.tmp/tw/two.x86 ; echo $?
3
```

and the file says, in a comment where `eval_eq_mojo` would have been:

```
/- AST bridge omitted: eval_eq_mojo: the AST bridge cannot state this function's
call — `f` with 2 arguments — `MojoExpr.call` carries ONE `MojoExpr` and
`callFunc` is `String → UInt64 → UInt64`, so a call of any other arity has no
faithful AST … Correctness would have to come from the machine value flow alone. -/
```

**So `⊢ False` is gone, and it is gone because of `_ast_bridge_gaps`**, which
post-dates this doc and refuses a call of any arity but one BEFORE `_expr_ast`
can drop arguments silently.  That check is the reason this doc's closing
paragraph — "an emitted proof that cannot hold is worse than a refusal" — no
longer describes the tree: the refusal is what happens.

What the two `sorry`s above are is the pre-existing x86-64 trust boundary
(`compile_correct` and `compiles_correctly`), which every x86-64 proof in the
tree carries and which
`bugs/FORMAL_x86_64_end_to_end_proof.md` owns.  On arm64 the same program is
REFUSED, by a different and larger gap: the CFG walk is per-function, so a call
to a second function in the same image cannot be followed at all
(`universal theorem: the call at … targets … a second function in the same
image`).  So a two-argument call is unprovable for two independent reasons and
neither is this doc's.

**What is left here is therefore exactly step 1 plus step 2, and both are still
the same two pieces of work**: widen `MojoExpr.call` to carry a `List MojoExpr`
(the Lean nested-inductive problem measured below), and make `callFunc` the
model's own function table instead of a stub.  Neither is a soundness fix any
more; they are what makes such a program PROVABLE rather than merely honest
about not proving it.

**One interaction this branch introduced, recorded here because it is the same
limit seen from the other side.**  `formal/arm64_proof_gen.py::_call_func_lean`
now takes the entry's arity, and at arity > 1 it gives the proved function's own
name NO branch: `mojo` is a function of several arguments and `callFunc` is
handed exactly one value, so any rendering would have to invent the rest.  The
name therefore falls to the `else 0`, which is TRUE, and
`_ast_bridge_gaps`' unresolvable-callee gap then REFUSES a program whose AST
calls its own multi-parameter entry by name — the same refusal, reached through
the same mechanism, for a callee that used to be "resolvable".  A one-argument
entry is unchanged, byte for byte.

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

## Status: step 1 is blocked on `MojoExpr` becoming a NESTED inductive (measured
## 2026-10-03)

`MojoExpr.call (name : String) (args : List MojoExpr)` is step 1 and it is four
lines. Making them is not four lines, and the reason is worth more than the
attempt:

**The list of the type's own constructors is what makes the type NESTED, and
`evalExpr` is structural recursion over it.** Lean 4 compiles

```lean
def ev : E → Nat
  | .int v => v
  | .call n args => args.foldl (fun acc a => acc + ev a) 0
```

into a WELL-FOUNDED fixpoint, not a structural one, and says so:

```
failed to infer structural recursion:
Cannot use parameter #1:
  unexpected occurrence of recursive application
    ev
failed to prove termination, possible solutions:
  - Use `termination_by` to specify a different well-founded relation
n : String
args : List E
a✝ : E
⊢ sizeOf a✝ < 1 + sizeOf n + sizeOf args
```

`a✝` is an element of `args`, and the obligation is true, but nothing in
`List.foldl`'s definition hands Lean the membership fact, so it cannot discharge
it. The consequence is not a warning: **`evalExpr` stops reducing**, so all 26 of
its per-node lemmas — every `evalExpr_int`, `evalExpr_var`, `evalExpr_binop …` —
lose `rfl` and fail, including the ones whose statement does not mention a call
at all. Reproduced in isolation (a 16-line file, 0.3 s, no `lib/` involved), so
this is Lean and not this tree.

Three further consequences the attempt surfaced, all of which a fix has to carry:

* **`evalExpr_congr` cannot use `induction e`.** Lean refuses it outright —
  "The `induction` tactic does not support the type `MojoExpr` because it is a
  nested inductive type" (`lib/ProofLib.lean:6490`) — and that theorem is what
  `evalBodyEnv`'s environment-merging proof uses, so it is on the path of every
  generated `eval_eq_mojo`. It needs the recursor with an explicit motive, and
  the `call` case then needs its own list induction to push the element-wise
  hypotheses through `foldl`.
* **`liftMF`'s `.call name a => .call name (liftMF a)`** (`:6266`) has to become
  the list form as well, or it does not elaborate.
* **The admitted-call refusal stays CORRECT but changes its reason.**
  `formal/arm64_proof_gen.py`'s `_call_go` and `formal/admitted.py` both justify
  the one-argument rule by "`MojoExpr.call` carries a single `UInt64` argument",
  which stops being true. It is still right, because the AST layer hands a
  handler the arguments' PRODUCT and a contract is applied to the request — so
  the wording has to move from "the AST can only carry one" to "the AST packs
  them into one", in both files, or the reason points at a fact that is gone.

**What still looks like the cheapest route**, in the order I would try it:

1. A `mutual` block with the argument fold written as an explicit recursion on
   `args` (`| a :: as => …`) instead of `List.foldl`, so the recursive call's
   argument is visibly a subterm. Whether Lean's structural recursion then
   accepts the nested occurrence is a 0.3-second experiment on the isolated file
   above, and it is the FIRST thing to try because it is the only route that
   leaves `evalExpr` reducible and every `rfl` intact.
2. Failing that, `MojoExpr.rec` with an explicit motive for `evalExpr` itself.
   That is a rewrite of the core evaluator plus 26 `rfl`s becoming `simp
   [evalExpr]`, plus `evalExpr_congr` — bigger, and it changes how every
   generated proof's `simp` set reaches `evalExpr`, so it wants the whole
   `formal` suite behind it rather than one example.
3. `termination_by e => sizeOf e` with `decreasing_by` carrying an explicit
   `a ∈ args` induction. Sound, and the most code of the three.

The whole of step 1 is 58 lines across `lib/ProofLib.lean`,
`formal/arm64_proof_gen.py` and `formal/admitted.py`, it was written and
measured, and it is NOT committed: it breaks the library build, and landing it
would put a red `prooflib` in everyone's gate. The three hunks that matter, so
nobody re-derives them:

```lean
-- lib/ProofLib.lean, the inductive
  | call (name : String) (args : List MojoExpr)

-- lib/ProofLib.lean, evalExpr's arm (the fold is what a `String → UInt64 →
-- UInt64` handler can consume; the product is a real loss, and it is why step 2
-- is still the fix)
  | MojoExpr.call name args =>
      callFunc name (args.foldl (fun acc a => acc * evalExpr callFunc a env) 1)

-- formal/arm64_proof_gen.py, _expr_ast's Call arm (it was `e.args[0]` alone)
    args = ", ".join(_expr_ast(a) for a in e.args)
    return f'(MojoExpr.call "{_call_name(e)}" [{args}])'
```

plus `evalExpr_call` re-stated over the list, a new `evalExpr_call_one` that
`1 * v = v` makes the old one-argument statement again (`simp`, not `rfl`), and
the two comment corrections named above. One thing this attempt did establish
that is worth keeping whatever route is taken: **for a ONE-argument call the new
node evaluates to exactly what the old one did**, so every proof that typechecks
today keeps its value and the change cannot move a verdict by itself.

**What is unchanged by all of this: step 2 is still the fix, and step 1 was never
a fix.** The reproduction at the top of this doc still fails the same way, and
the closing paragraph below still holds.

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