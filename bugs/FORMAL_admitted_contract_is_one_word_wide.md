# An admitted host contract is one WORD wide, because `MojoExpr.call` is

**Status: OPEN, and it is a limit of the ADMITTED-CONTRACT mechanism rather than a
bug in it.** `FORMAL.md` §7a states the rule; this is what it costs and what closing
it needs.

## What I ran

    python3 tools/memslot.py --gb 8 --label t -- \
        python3 fire.py build --formal --backend=arm64 -o out.mojo.tmp x.mojo

on a program whose whole body is

    import subprocess
    def main() -> int:
        return subprocess.run("ls -l", 1)

## What I saw

    build: call subprocess.run(): too many positional arguments
      (2 for 1 parameter(s); the parameters are ['request'])

and, with the two arguments reduced to one so the model accepts the call, the
proof *generates* and typechecks with 13 admitted `sorry`s — 7 of them the
contracts and 6 of them the theorems whose value now rests on them. So the
mechanism works; what it cannot do is carry a call with more than one argument.

## Why

    lib/ProofLib.lean
      | MojoExpr.call name arg          -- ONE UInt64

`evalExpr` passes that single argument to `callFunc : String → UInt64 → UInt64`,
so the AST layer of a generated proof can only *evaluate* a one-argument call.
The source-semantics layer (`formal/arm64_proof_gen.py`'s `_call_go`) has no such
restriction — it renders every argument — so an admission applied to two arguments
there and one in the AST layer makes

    theorem eval_eq_mojo (n : UInt64) :
      evalFunc ast (fun name arg => ...) n = mojo n

**false**, not merely unproved: `mojo` mentions `admitted_f a b` and `evalExpr`
evaluates `admitted_f a`. A `sorry` would be hiding a contradiction, which is the
one thing a trust boundary must never be used for.

Hence `formal/arm64_proof_gen.py`'s `_call_go` refuses an admitted call with any
arity but one, naming the call and the arity. Measured refusals:

    model: `subprocess.run` is an ADMITTED contract and is declared over ONE
    word — the argument is the request, and a value on this path is one 64-bit
    word — but this call passes 2. Split the call so the admitted operation
    takes the request alone; the contract cannot be applied to a shape the
    model cannot carry, and applying it to the first argument alone would
    silently drop the rest.

## What it costs, measured

The five modules written so far avoid it by construction — every admitted
operation takes ONE parameter, the "request":

| operation | parameters | CPython's own signature |
|---|---|---|
| `subprocess.run` | 1 (`request`) | `run(*popenargs, input=None, capture_output=False, timeout=None, check=False, **kwargs)` |
| `subprocess.call`, `check_call`, `check_output`, `getoutput`, `getstatusoutput`, `popen_wait` | 1 | each takes a command *and* keywords |
| `ctypes.cdll_open` | 1 | `CDLL(name, mode=RTLD_LOCAL, handle=None, use_errno=False, use_last_error=False, winmode=None)` |
| `ctypes.cdll_call` | 1 (the handle) | `lib.func(*args)` — the symbol name is not carried |
| `fcntl.flock` | **2** (`fd`, `operation`) | `flock(fd, operation)` |
| `threading.lock_acquire` | **1** (the fd) | `Lock.acquire(blocking=True, timeout=-1)` |

So `fcntl.flock` is the honest casualty: its signature is CPython's, it is
**declared** over one word in practice, and a call to it in a proof is refused.
Two files in the tree call it (`build_stdlib_dylib.py`, `formal/lean.py`), and
neither of them builds here for other reasons.

## What closing it needs

`MojoExpr.call` gains a second field and `evalExpr` passes both:

```lean
| MojoExpr.call name arg          => callFunc name arg
| MojoExpr.call2 name a b         => callFunc2 name a b
```

with `callFunc2 : String → UInt64 → UInt64 → UInt64` threaded through
`evalFunc`, `evalBody`, `evalBodyEnv` and every `simp` set in the generated
proofs, and `_expr_ast` (`formal/arm64_proof_gen.py:1541`) taught to render
`args[0..1]` rather than `args[0]` alone. `lib/ProofLib.lean` is 6496 lines and
`lib/Refine.lean`'s `Refine.Prog` consumers are downstream of every one of those
signatures, so this is a library change with a full `ProofLib` rebuild (measured
27 MB / ~80 s) — not a generator change.

**Why it is worth doing anyway.** It is the same change that closes
`bugs/FORMAL_lean_model_call_semantics.md` for the decidable half: the AST model
carrying two arguments is what a *computable* two-argument call needs too, and
today a call to a two-argument `formal/hostmods/` function whose value is used is
refused by `_call_go` for exactly the same reason — there is no model for it
either. So this one library change unblocks both.

## What NOT to do

Do not widen the contract to two words and drop the second argument. That is the
fabrication this project treats as its worst outcome
(`bugs/FORMAL_known_limits.md`: "a **false PASS**, the worst outcome this project
has"): the proof would typecheck, the census would count the hole, and the
`trust:` line would name a contract that does not describe what the model did.
