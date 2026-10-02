# FORMAL_prove_semantic_model_drops_a_var_decl: `var a = 1` makes the whole semantic model 0, so every proved program with a `var` local fails

**Status: OPEN, pre-existing on `master` (measured by extracting `master` to a
scratch directory and building there), and it is the reason `--formal` WITH a
proof currently works for almost no real program.** Found 2026-10-01 while
fixing `1 << -1` on the `construct:arm64-silent-wrong-answers` claim, where
verifying a run-time trap needed a proof and there was not one to be had.

This is not a wrong answer that ships. It is a build that refuses — Lean
rejects the file rather than accepting a `sorry`-backed theorem — so nothing is
silently wrong. But the refusal is total for a construct Mojo spells with a
keyword, and it is a two-line omission from the generator's dispatch.

## What I ran

```mojo
def main() -> Int:
    var a = 1
    return a
```

```console
$ python3 fire.py build --formal -o /tmp/b.out /tmp/b.mojo
[proof census: b_proof.lean — 1 declaration(s) admitted a `sorry`, 0 vacuous]
build: proof check failed: ProofLib	Refine	X86	work
b_proof.lean:81:2: error: Tactic `native_decide` evaluated that the proposition
  run_result_exit
      (let __src := Arm64State.init 10 4294967808; { … x0 := __src.x0, … })
      main_code 4294967808 200000 =
    mojo 5
is false
b_proof.lean:86:2: error: … (six of these, one per test input 10/0/1/2/5/…)
b_proof.lean:1341:2: error: Tactic `native_decide` evaluated that the proposition
  (match arm64_exec_go … main_code 100000 with | some s => s.x0 | none => 0) =
    mojo 10
is false
```

Six run tests and one per-instruction test, all saying the same thing: the
machine returns 1 and the model says something else.

## What the generated file says, which is the whole diagnosis

```lean
/-- Mojo semantics: direct Lean model of the source code. -/
def main_go : UInt64 :=
  (0 : UInt64)

/-- The semantic model as a UInt64 -> UInt64 function. -/
def mojo (n : UInt64) : UInt64 :=
  main_go

/- AST for main (mirrors source code). -/
def ast : MojoFunc := MojoFunc.mk "main" "n" ([MojoStmt.return (MojoExpr.var "a")])
```

**`main_go` is the constant 0, and `ast` has lost the declaration entirely.**
The machine is right: the program returns 1. The model is not a model of this
program at all — it is a model of a program that returns nothing.

## The cause, in two places, both the same omission

`var a = 1` parses to `F.VarDecl`, and **`VarDecl` appears nowhere in
`formal/arm64_proof_gen.py`** — `grep -c VarDecl` on that file is 0. It is not
that a `VarDecl` is handled wrongly; it is that it is not a case.

1. **`_stmts_go` (line 583)** dispatches `Return`, `Pass`/`ExprStmt`,
   `Assign`, `AugAssign`, `ForStmt`/`Break`/`Continue`, `IfStmt`, `WhileStmt` —
   and ends with `return "(0 : UInt64)"` at **line 657**. A `VarDecl` matches
   none of the arms, so it takes that line: the declaration is read as a
   statement whose value is 0, and since `_stmts_go` is a fold over the
   statement list that 0 is what the rest of the function is evaluated from.
   `_stmts_go_t` (line 790), the typed twin, ends the same way at line 822 but
   with a `raise NotImplementedError("typed model: while loops not yet
   supported")` — so the typed path at least fails loudly, on the wrong
   reason.
2. **`_stmts_ast` (line 1460)** is the same story with no `return` at all: its
   `elif` chain covers `Return`, `IfStmt`, `Pass`, `Assign`, `AugAssign`,
   `ExprStmt`, `WhileStmt`, and then raises for `ForStmt`/`Break`/`Continue`.
   A `VarDecl` is silently **not appended**, which is why `ast` above has one
   statement where the source has two.

**The third site is the same omission one level up, and it is what makes the
first two reachable rather than a corner case:** `_gen_go` (line 1060) computes
`env = {p: p for p in params}` from the function's **parameters** and nothing
else. Every name the function binds itself — a `var`, and also a bare
`x = 1` if it ever reaches here as something other than an `AssignStmt` — is
absent from `env`, so `_expr_go_t`'s `env.get(e.name, "(0 : UInt64)")`
(line 702) turns a read of it into 0 as well. That is the second half of why
`return a` is 0 even where the declaration itself is not what is being read.

## The boundary is exact, and it is worth stating because it is the diagnostic

Measured on this tree, arm64, `def main() -> Int:` with the body varied, and
reading `def main_go` out of the generated file:

| body | `main_go` | proves? |
|---|---|---|
| `return 1` | `UInt64.ofNat 1` | yes |
| `return 0 - 1` | correct | yes |
| `a = 1; return a` | `UInt64.ofNat 1` | **yes** |
| `var a = 1; return a` | `(0 : UInt64)` | no (6 errors) |
| `var a: Int = 1; return a` | `(0 : UInt64)` | no (6 errors) |
| `var a = 1; return 2` | `(0 : UInt64)` | no (**12** errors) |
| `var a = 1; var b = 2; return a + b` | `(0 : UInt64)` | no (6 errors) |

**`a = 1` is an `AssignStmt` and works; `var a = 1` is a `VarDecl` and does
not.** That one-token difference is the entire bug, and it is also why this
went unnoticed: the generator's other statement forms are all covered, so a
smoke test written with `x = 1` (or with no local at all, which is what
`def main() -> Int: return 0` is) passes.

The `return 2` row is the informative one: the function's answer does not
depend on `a` at all, and it still fails, with **twelve** errors rather than
six. The declaration poisons the model for the whole function, not for the
reads of the name.

## Why it matters beyond the prove

Nothing is silently wrong, which is the one mercy here: Lean rejects the file,
so a program that cannot be proved is a program that does not build. The cost
is coverage, and it is the coverage this backend exists to provide — `var` is
how a Mojo local is spelled, so this is very nearly every program with a local
at all. The measurement that puts a number on it is not in this doc because it
is a sweep and a sweep is the integrator's.

**The blocker for anything else that needs a proof, which is why this is filed
rather than noted:** a run-time trap is verified by a program that *runs*, so
`test_formal_run.py` covers it. Anything whose correctness is a statement about
the machine rather than about an exit status cannot be verified on this tree at
all until this is fixed, and the natural way to verify it — build with
`--formal` and no `--no-prove` — is what fails.

## The next step

One case in each of the two dispatchers, and both should be REFUSALS rather
than model terms, because that is what the rest of this generator does when it
meets a construct it has no model for (`_no_value_model`, line 1185, is the
precedent and its docstring says why: a false model is worse than no model,
because it makes the run tests fail "three theorems away from the statement
that produced it"):

1. **`_stmts_go`**: an arm for `F.VarDecl` that raises
   `NotImplementedError("model: a `var` declaration …")`. While there, the
   bare `return "(0 : UInt64)"` at line 657 is the same silent-zero bug for
   every statement form not yet listed, and `_no_value_model`'s reasoning
   applies to it verbatim — it should be a `raise` naming the type. That is
   worth doing at the same time: it is the difference between "this construct
   is not modelled" and "this construct is modelled as 0", and only the second
   one is a wrong answer.
2. **`_stmts_ast`**: the same arm, raising. `MojoStmt` has no declaration form
   and it should not grow one for this — the AST exists to cross-check the
   model, and a `var` is a binding the AST's `MojoStmt.assign` already
   expresses once the model treats it as one.

**The larger fix, which is not required for the refusal and is where the real
value is:** teach `_stmts_go` to treat a `VarDecl` as the `Assign` it is, by
putting `_target_name(st)` in `env` from `st.value` exactly as the `Assign`
arm at line 802 does, and give `MojoStmt` the declaration as an `assign` in
`_stmts_ast` the way the `AugAssign` arm at line 1477 already desugars. That
turns six-error failures into proofs, and it is the same one-line-shaped change
in both places — which is the strongest argument for doing both rather than
refusing: the desugaring is faithful, and a refusal would be refusing a
construct the model can state exactly.

**Decide which before starting**, because they are opposite answers to the same
question. My recommendation is the desugaring, and the reason is that
`bugs/FORMAL_lean_model_call_semantics.md`'s territory is already the "the model
must be right, not merely present" position; a `var a = 1` the model reads as 0
is exactly the false model that doc's sibling `_no_value_model` was written to
stop.

## Verified, and what is not

* Reproduced on this tree, and reproduced on `master` extracted to
  `.tmp/w/mbase` with `lib/*.olean` copied in — so it is pre-existing and not
  something the shift fix brought in. (The shift fix's own verification is
  `test_formal_run.py`, which builds with `--no-prove` and RUNS the image, so
  it does not touch this path.)
* The seven-row boundary table above, read off the generated `main_go` on this
  tree.
* `grep -c VarDecl formal/arm64_proof_gen.py` is 0, and
  `formal/arm64_codegen.py` / `formal/x86_64_codegen.py` / `formal/model.py`
  all handle it (3 / 3 / 25 hits) — so this is the proof generator alone, and
  the machine half of the pair is the correct one.
* **x86-64 is affected by construction, not by measurement, and that is
  checked rather than assumed**: `formal/x86_64_proof_gen.py` defines no
  statement dispatcher of its own — it calls `AP._go_defs_for` (line 116) for
  the model and `AP._stmts_ast` (line 202) for the AST, where `AP` is
  `formal/arm64_proof_gen`. So both of the sites named above are reached by an
  x86-64 build too, and one fix closes both. The same source on
  `--backend=x86_64` was not itself built, so treat that as following from the
  shared helper rather than as measured.
* **NOT measured: how many stdlib files this blocks**, which is the number that
  decides whether it is a `formal_sweep` away or a whole-pass rewrite. That is
  a sweep and a sweep is not a worker's.
