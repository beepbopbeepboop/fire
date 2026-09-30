# FORMAL_arm64_ninth_argument_is_silently_dropped: a function with more than 8 parameters reads garbage

**Status: OPEN. Found while writing `hashlib` (2026-09-29, the
`module:hashlib` claim); the fix is in `formal/arm64_codegen.py`, which that
claim does not own, so it is filed rather than applied. Until it lands,
`formal/hostmods/hashlib.mojo` keeps every function it defines at eight
parameters or fewer.**

This is a **wrong answer, not a refusal**, and the failure mode is the worst
one in this family: the value is not garbage-looking, it is **zero**, and
zero is a perfectly good answer to a great many questions.

---

## What I ran

```
$ cat > .tmp/pl2.mojo
def nine(a0: int, a1: int, a2: int, a3: int, a4: int,
         a5: int, a6: int, a7: int, a8: int) -> int:
    return a8 * 10000 + a0

def main() -> int:
    printf("nine=%d@@", nine(1, 2, 3, 4, 5, 6, 7, 8, 9))
    return 0
$ python3 fire.py build --formal --no-prove -o .tmp/pl2 .tmp/pl2.mojo
$ ./.tmp/pl2
nine=1
```

`nine(1, 2, 3, 4, 5, 6, 7, 8, 9)` should print `90001` (`a8` is 9, `a0` is 1).
It printed `1`: **`a8` read as 0**.

## What I saw

Measured across arities, same file, one function per arity, each writing its
own parameters into a buffer and reading them back:

| parameters | result |
|---|---|
| 6 | correct |
| 7 | **parameter 7 reads 0** |
| 8 | **parameters 7 and 8 read 0** |
| 9 | **parameters 7, 8, 9 read 0** |
| 10 | parameters 7-10 read 0 |
| 12 | parameters 7-12 read 0, and some read values from *other* parameters |
| 16 | parameters 7-16 read 0 or unrelated values |

So the boundary is **eight parameters**: 1 through 8 arrive, 9 and onward do
not. `mixed(0, 0, 0, 0, 0, 0, 1, 2, 3, 4)` returning `21` rather than `4321`
is the sharpest form of it — `a6` and `a7` are right and `a8`, `a9` are zero,
with no way for the callee to tell that from a caller who passed zeros.

**x86-64 refuses the same program, and its message is the one this should
produce:**

```
$ python3 fire.py build --formal --no-prove --backend x86_64 -o .tmp/pl2x .tmp/pl2.mojo
build: call eight(): 8 arguments exceeds the 6 the formal x86-64 ABI passes in
registers
```

(The x86-64 limit is 6 argument registers, hence the refusal at 8 rather than
at 9 — two different ceilings, one honest and one silent. The honest one is
the evidence that the author knew this class of problem existed.)

## Why

Two places, and both are visible in the tree.

**The callee stops reading at eight.** `formal/arm64_codegen.py:865`:

```python
        for i, (pname, ptype) in enumerate(incoming):
            if i >= 8:
                break            # AAPCS has no register for argument 8+
```

The comment is right about AAPCS — X0-X7 are the argument registers — and the
`break` is the wrong response to it, because a function with a ninth parameter
is not a function the caller is forbidden to call, it is a function this
backend cannot represent. A `break` makes the parameter's home slot never
written, and the first read of that name in the body loads whatever the slot
held. The very next comment in the same block says the spill path is "NOT
reachable today — the caller only ever passes 8 arguments"; that is the
assumption that is false, because nothing stops a SOURCE file from declaring
nine.

**The caller never passes them.** `_emit_call` places arguments in X0-X7, so
argument 9 is never in a register at all. There is no diagnostic at either
end, which is what makes this a silent wrong value rather than a build
failure.

## What I expect

Either of two things, and which one is a decision rather than a bug fix:

1. **`hashlib`'s `put16` case, the obvious one.** A function that takes 18
   parameters and writes 16 of them is not unusual in ordinary code; a
   backend that cannot represent it should say so, the way x86-64 does.
2. **A real 9th-argument path.** AAPCS does define what happens past X7: the
   stack. The comment at `:879` already describes the spill-slot home for a
   parameter past the callee-saved registers, and the machinery (`_var_spills`,
   `_spill_off`) exists. Wiring the caller to store argument 9+ to the stack
   and the callee to load it is a real change to the calling convention that
   BOTH backends and the Lean proof share, which is why this is filed as a
   decision rather than done here.

Either way the refusal in (1) is the minimum, and it is the same shape as the
existing `FORMAL_variadic_call_has_no_abi` family: an arity the ABI does not
cover should be an error at the call site, not a zero at the read.

## The exact next step

1. **Refuse, at the call site, on arm64 as x86-64 already does.**
   `formal/x86_64_codegen.py:765` has the message and the check; the arm64
   `_emit_call` needs the same comparison against `len(ARG_REGS)` (8), and
   `formal/arm64_codegen.py:865`'s `break` should become a `raise` so a
   direct call that somehow skipped the check cannot silently zero a
   parameter either. The message should name the arity, the limit and the
   callee, as the x86-64 one does.

2. **Then decide on the stack path** (option 2 above) as its own piece of
   work, because it changes the calling convention. Until then the refusal is
   the correct answer, and `bugs/COMPILE_FAIL_collections___init__.md`'s
   neighbourhood of questions — "does a list cross a boundary" — gets a
   second one: "does a ninth argument".

3. **A test for it**, in `test_formal_run.py`'s refusal family: a function of
   nine parameters whose ninth is read, asserting the BUILD FAILS with a
   message naming the arity. Not a runtime assertion — the whole point is that
   today it builds and returns zero, so the only assertion that can catch a
   regression is one on the diagnostic.

**Checked and NOT the same bug**, so nobody re-derives it: this is
unrelated to the variadic refusal, which is about `*args` and has its own doc
(`FORMAL_variadic_call_has_no_abi` family); and unrelated to the default-
argument defect (`FORMAL_default_argument_not_applied_across_a_dylib`, now
fixed, so its doc is deleted), which is about arguments the caller does not
supply rather than ones it supplies and the callee cannot receive.
