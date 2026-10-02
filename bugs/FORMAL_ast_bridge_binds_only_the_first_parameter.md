# FORMAL_ast_bridge_binds_only_the_first_parameter: `mojo` and `MojoFunc` are one-input, so a two-parameter entry point has no proof

**Found 2026-10-01 while re-measuring what
`bugs/FORMAL_x86_64_argument_registers.md`'s next step actually costs. NOT
FIXED here beyond a generator guard that stops the ill-typed proof from being
written; the real fix is in `lib/ProofLib.lean`. Status: open, with the
measurement, the generated text, and the exact next step.**

## What I ran

```
$ cat .tmp/tv/main2.mojo
def main(n: Int, m: Int) -> Int:
    return n + m
$ python3 fire.py build --formal --no-prove --backend=arm64   -o .tmp/tv/main2.arm64  .tmp/tv/main2.mojo
Built: .tmp/tv/main2.arm64  [arm64/macho]
$ python3 fire.py build --formal --no-prove --backend=x86_64  -o .tmp/tv/main2.x86_64 .tmp/tv/main2.mojo
Built: .tmp/tv/main2.x86_64  [x86_64/macho]
```

A **two-parameter entry point is a legal program on both architectures.** It is
also what `formal/hostmods/re.mojo` and `hashlib.mojo` are full of (`sub(7)`,
`_subwalk(8)`, `put6(8)`), and what the formal entry convention's one `n` is a
convention rather than a language rule.

## What I saw

Before the guard this change added, the generated proof for
`def f(a0, a1): return a0 + a1` contained:

```lean
def f_go (a0 : UInt64) (a1 : UInt64) : UInt64 := ...
def mojo (n : UInt64) : UInt64 :=
  f_go n                                     -- argument-count error
def ast : MojoFunc := MojoFunc.mk "f" "a0" ([MojoStmt.return ((MojoExpr.binop "+"
  (MojoExpr.var "a0") (MojoExpr.var "a1")))])
```

and `lib/ProofLib.lean:882`:

```lean
def evalFunc (f : MojoFunc) (callFunc : String → UInt64) (arg : UInt64) : UInt64 :=
  match f with
  | MojoFunc.mk _ param body =>
    let env := fun name => if name == param then arg else (0 : UInt64)
```

**Three independent one-parameter assumptions, and they are the same one:**

| where | shape |
|---|---|
| `lib/ProofLib.lean:745` | `inductive MojoFunc \| mk (name) (param : String) (body)` — one `param` |
| `lib/ProofLib.lean:882` | `evalFunc … (arg : UInt64)` and an environment that answers **0** for every name that is not `param` |
| `formal/arm64_proof_gen.py:_go_apply` (via `_model_shape`) | read `binders[0]` and applied ONE argument, whatever the model's arity |

**The consequence is not a wrong theorem — it is a proof file that cannot
elaborate.** `f_go n` where `f_go` takes two arguments is an argument-count
error; Lean does not recover from it as a `sorry` and does not elaborate the
rest of the file, so every theorem in it is lost and the reader is looking at an
elaboration error three definitions away from the line that is wrong. (Compare
`_model_shape`'s own docstring, which records the NULLARY case producing
`ret42_go n` and being silently recovered as a `sorry` — that one was fixed, and
this is the same reader with the same class of mistake one arity up.)

**This is the same defect `_gen_go` was already fixed for**, and its own
docstring says so — `formal/arm64_proof_gen.py:1073`:

> The model's **arity is the source function's arity**. It used to be one
> parameter unconditionally — `param = fn.params[0][0]`, `env = {param: …}` — so
> a two-parameter function got a model with one parameter and the rest of its
> parameters bound to nothing: `fn add2(a, b) = a + b` came out as `add2_go a =
> a + 0`, which is not `add2` but a different function of the same name.

So `_gen_go` was widened and **`mojo`, `MojoFunc` and `evalFunc` beside it were
not.** That is why the two halves disagree: the model is right and everything
that *applies* it is wrong.

## What landed here, and what it is not

`formal/arm64_proof_gen.py`: `_model_shape` now reports the binder **count**, and
`_go_apply` refuses an arity past one, naming the arity, the model and the
one-input apparatus it does not fit. One implementation, read by both
generators (the x86-64 one imports the arm64 `_go_apply`), so the two machines
cannot disagree about it.

```
$ python3 fire.py build --formal --backend=x86_64 -o .tmp/tv/main2p .tmp/tv/main2.mojo
build: model: main_go has 2 parameters, and the surrounding proof is a one-input
theorem: `mojo` is declared `UInt64 -> UInt64`, `eval_eq_mojo` and every run test
quantify over one `n`, and ProofLib's AST bridge binds one parameter (`evalFunc`'s
environment answers 0 for every name that is not it). Emitting `mojo n :=
main_go n` instead is an argument-count error Lean cannot recover from, so the
whole proof file fails to elaborate. Widening `mojo` and the bridge to the
model's arity is a `lib/ProofLib.lean` change
```

Verified: `python3 test_formal_call_proof_gen.py` — 15 tests, OK (the Lean half
skips loudly, no `lib/ProofLib.olean` on this tree). `lib/*.olean` still absent
after the run above, so the guard fires BEFORE any Lean is invoked — which is the
ordering that makes the refusal cheap rather than an 80-second library build.

**That is a refusal, not a proof.** It replaces an ill-typed file with an
accurate message; it does not make `def main(n, m)` provable.

## The exact next step

`lib/ProofLib.lean`, in this order — each step is separately checkable and the
file typechecks throughout:

1. **`MojoFunc` carries the source's parameter NAMES**:
   `| mk (name : String) (params : List String) (body : List MojoStmt)`. The
   names rather than indices, because `evalFunc`'s environment is already keyed
   by name and the generators already have the list (`[p[0] for p in fn.params]`,
   the line `_gen_go` uses).
2. **`evalFunc` takes the model's arity**:
   `evalFunc (f : MojoFunc) (callFunc) (args : List UInt64) : UInt64`, with
   `let env := fun name => match args.get? i with | some v => v | none => 0`
   over `params`. The `none => 0` arm matters: it is what makes an unbound name
   the answer it is today, so nothing that relies on it changes.
3. **Every generated proof's `mojo` becomes n-ary**, and so does everything that
   quantifies over it: `eval_eq_mojo`, the `native_decide` run tests
   (`eval_eq_mojo_0`, `eval_eq_mojo_test`, …), and the universal theorem's entry
   state. `_gen_runs_test` and `_gen_extern_test` both take `test_input` as a
   single `UInt64`; the multi-parameter form needs a *tuple* of inputs, and
   `test_input` is the one thing the driver supplies (`compile_formal`'s
   `test_input=`), so `formal/build.py` has to be able to pass more than one.
   **That is the part most likely to be underestimated** and it is a driver
   change, not a generator change.
4. **`MojoFunc.mk` at both generator sites** (`formal/arm64_proof_gen.py:7002`
   and `formal/x86_64_proof_gen.py:194`) reads `params[0][0]`; both become the
   whole list.
5. **Then lift the guard in `_go_apply`** and delete this file in the same
   commit, with a test that a two-parameter entry point produces a proof file
   Lean accepts — which is the assertion that cannot be written until step 3 is
   done, and is why the guard is a guard rather than a fix.

## Why this doc exists in the argument-registers doc's claim

`bugs/FORMAL_x86_64_argument_registers.md` prices lifting the register limit as
"the same work twice" in the emitters. It is that **and** this: once a
seven-argument function is legal, the proof side has to state something about
seven arguments, and today it cannot state anything about two. The other half of
that doc's step list — step 3, "decide the `RETURNED_FRAME_MAX_ARGS` budget
first" — is one line of it; the `MojoFunc` arity is the other.