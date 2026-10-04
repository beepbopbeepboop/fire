# FORMAL_arm64_exit_trap_does_not_flush_so_a_program_that_prints_then_exits_1_prints_nothing

**Status: open, filed 2026-10-03 by `work/formal19-fuzz-3`, while probing tuple
unpacking.** NOT fixed there: it is an arch-parity defect on an error path with
21 call sites in one emitter, which is a bigger change than a fuzz sweep should
make on its way past. Both measurements, both reproductions, and the exact next
step are below.

## What I ran

    $ cat .tmp/pb2/oob2.mojo
    def main() -> Int32:
        print("before")
        xs = [1, 2, 3]
        print(xs[7])
        return 0

    $ python3 fire.py build --formal --no-prove --backend=x86_64 -o oob2.x86 oob2.mojo && ./oob2.x86; echo "exit=$?"
    before
    exit=1

    $ python3 fire.py build --formal --no-prove --backend=arm64 -o oob2.arm64 oob2.mojo && ./oob2.arm64; echo "exit=$?"
    exit=1                      # ← "before" is MISSING

CPython raises `IndexError`, so this is not a differential case the fuzzer can
reach — see "Why the corpus cannot see it" below. It is a disagreement BETWEEN
the two architectures, which is the other half of what `test_formal_x86_64_parity.py`
exists to keep closed.

The same shape with a tuple unpack's runtime arity check, to show it is the
exit path and not the subscript — and with a **blob** right-hand side, because
the LITERAL arity mismatch is caught at build time on arm64 and never reaches the
trap at all:

    def main() -> Int32:
        print("before")
        t = (1,)
        a = 0
        b = 0
        a, b = t
        return 0

→ x86-64 prints `before`, arm64 prints nothing, both exit 1. (The literal
spelling, `a, b = (1,)`, is REFUSED on arm64 with "tuple assignment length
mismatch: 2 targets, 1 values" and runs to the same exit on x86-64 — a
divergence of a different kind, and a correct one: a build-time check beats a
run-time one, and the two backends answering differently about which is a
separate question from this document.)

## Why

x86-64's exit is a call to the C library's `exit(status)`
(`formal/x86_64_codegen.py::_emit_call_exit`), and `exit` FLUSHES every open
stream. arm64's exit is the raw Darwin trap — `movz x0, #status; movz x16, #1;
svc #0x80` (`formal/arm64_codegen.py::_emit_diverge` and ~20 other sites) — and
a raw `SYS_exit` does not touch stdio. stdout is block-buffered whenever it is
not a terminal, which is every case a sweep or a test harness creates
(`subprocess.run(capture_output=True)`), so on arm64 the output of a program that
prints and then takes an error exit is LOST, while x86-64 keeps it.

The arm64 emitter already knows how to say `fflush(NULL)` — `print(…, flush=True)`
emits exactly that call (`_emit_print`'s own comment says the flush is "a missing
line rather than a wrong one"). Nothing in the exit path uses it.

This is not the same defect as a lost line on a SUCCESSFUL exit: a program that
returns normally gets its buffer flushed at the `return` from `main` (both
architectures), so the class is narrow — it is exactly "printed, then exited
through one of the 21 trap sites".

## Exact next step

One helper, and route every trap site through it. `formal/model.py` is not
involved: the decision is an emitter's, and both emitters should MAKE it rather
than one of them.

1. In `formal/arm64_codegen.py`, add `_emit_exit(self, status)` next to
   `_emit_diverge`: emit `fflush(NULL)` through the same
   `_emit_call(F.CallExpr(func=IdentExpr("fflush"), [IntLiteral(0)]))` the
   `flush=True` path already uses, then the three-instruction trap. Give it the
   `_emit_diverge` docstring's reasoning (two copies of the trap is how the two
   call sites came to differ), and note that the flush is what makes the two
   architectures answer the same about what a program left on stdout.
2. Replace all 21 `encode_svc(0x80)` exit sequences with it. **The
   stack-floor trap (`_emit_stack_floor_guard`, `arm64_codegen.py:1685`) is the
   one site that must NOT flush** — it can fire before any user output exists,
   it is the trap the proof generator decodes (`lib/ProofLib.lean` reads the
   address in `info["compiler_traps"]`), and changing its instruction stream
   would move the decoded trap. Leave it raw and say why in its own comment.
3. `x86_64_codegen.py` needs no change: `exit` already flushes. That asymmetry is
   the whole defect, so the fix is to make arm64 match rather than to change
   x86-64.
4. Pin it in `test_formal_x86_64_parity.py` (the file that exists for
   one-architecture divergences): a case that prints a line and then takes an
   out-of-range subscript, asserted as **the same stdout on both**. `oob2.mojo`
   above is the case; the blob-unpack arity variant is the second, because it
   shows the exit is the cause and not the subscript.

## Why the corpus cannot see it, stated so nobody re-searches for it

`tools/formal_fuzz.py` compares against CPython, and every program that reaches
one of these exit sites **raises in CPython** (`IndexError`, `ValueError`), so
`cpython_answer` returns its error tuple and `check_one` records a
`generator-error` — the program never reaches an image. That is the correct
verdict for the oracle and it means this class is invisible to the differential
fuzzer by construction; it is the x86-64/arm64 pair that disagree, and only a
parity suite compares those two directly.

So this is a coverage statement about the TOOL, not a gap in the backend's
coverage, and it is worth knowing next to `test_formal_x86_64_parity.py`'s
existence: **a differential-against-CPython fuzzer cannot find a bug the two
backends share's opposite — one that is only a divergence between them, on a
program CPython refuses.** Everything else in that file's remit is reachable;
this is not.