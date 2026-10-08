# A `return` inside a `finally` emits the epilogue twice, and arm64 SIGBUSes

**Area:** FORMAL, `try`/`finally` lowering, arm64. Found 2026-10-05 on
`work/formal55-match-statements` while measuring the `finally` machinery next
to `FORMAL_a_second_exit_path_in_a_try_drops_the_finally.md`. **OPEN.** Not
this branch's claim (`project:match-statements`).

## 1. What I ran and what I saw

```sh
cat > /tmp/h.py <<'EOF'
def h():
    try:
        return 1
    finally:
        print('fin')
        return 2          # CPython: SyntaxWarning, and it WINS

def main():
    print(h())
    return 0
EOF
python3 fire.py build --formal --no-prove --backend=arm64   -o /tmp/h.arm64 /tmp/h.py && /tmp/h.arm64; echo "arm64 rc=$?"
python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/h.x86   /tmp/h.py && /tmp/h.x86;   echo "x86 rc=$?"
```

| | answer |
|---|---|
| CPython 3.14 | `fin` then `2` (with a `SyntaxWarning: 'return' in a 'finally' block`) |
| x86-64 | `fin`, `2`, exit 0 — **correct** |
| arm64 | **`Bus error` (SIGBUS), exit 138, nothing printed** |

x86-64 gets it right by luck of ordering, not by design: its `_emit_stmt`
return arm reaches the epilogue through a path the arm64 one does not (§2). The
two architectures disagreeing about one construct is the class
`FORMAL_the_two_backends_refuse_different_constructs_in_the_same_function.md`
is about, except here the disagreement is a crash rather than a message.

## 2. Why

Both emitters' `_flush_pending_finally` emits the pending frames and then
CONTINUES — the `return` statement that triggered the flush still runs the rest
of its own emission:

`formal/arm64_codegen.py::_emit_stmt`, `F.ReturnStmt` arm:

```python
self._emit_expr(stmt.value)          # or _emit_frame_return
if self._recv_ref_receiver is not None:
    self._emit_receiver_writeback()
self._flush_pending_finally()        # <- emits `print('fin')` AND `return 2`
self._emit_epilogue()                # <- and then emits ANOTHER epilogue
```

The nested `return 2` inside the flushed body has already run
`_emit_epilogue()` once. Control comes back and arm64 runs it a second time:
two `LDP`-shaped epilogues for one frame, so `SP` is decremented twice and the
frame pointer is garbage by the time anything is read through it. A SIGBUS is
the expected shape for a load from an address the process no longer maps.

x86-64 does not crash because its return arm emits through `_jmp`/a tail
sequence whose second execution is a jump to an already-returned label rather
than a second frame teardown — the answer is right, but nothing in the code is
*deciding* that, so it is one refactor away from breaking too.

`_emit_try` then emits the `finally` body a THIRD time as its fall-through copy
(that copy is deliberate — see its docstring — and is dead code after a
`return`), so a `print` in the body would run three times on this path if the
frame survived.

## 3. The next step

An emitter-level "this path has already returned" flag, consulted by the
epilogue rather than by the caller:

1. `_emit_epilogue` sets `self._returned = True` (arm64) / the x86-64
   equivalent, and refuses to emit a second time — a build error naming the
   construct is better than a second teardown, and this is the same shape as
   `_emit_try`'s own fall-through decision.
2. `_emit_stmt`'s `ReturnStmt` arm re-checks the flag after
   `_flush_pending_finally()` and returns without emitting, which is what makes
   the nested `return` the one that owns the epilogue.
3. Reset the flag at each `_emit_stmt` entry that is NOT reached by a return —
   i.e. at the label boundaries the emitters already track — so the flag is a
   property of the path and not of the function. `formal/arm64_proof_gen.py`
   reads the block structure, so the flag must not change which blocks exist.

This is the same state question as
`FORMAL_a_second_exit_path_in_a_try_drops_the_finally.md`'s re-entrancy guard,
and the two fixes compose: with the frames still on `_pending_finally` (that
document's fix), the nested `return`'s flush is skipped by identity and the
outer return owns the epilogue.

CPython's answer (`2`, with a warning) is the one to match: a `return` in a
`finally` discards the in-flight exception and the pending return value.

## 4. Where it is pinned

Not yet pinned by a test — `test_formal_exceptions.py` covers the `finally`
rows that pass, and none of them returns from inside the body. The row to add
is the §1 program with `("trapped", None)` replaced by `("value", "fin\n2")`,
alongside the drop-the-cleanup rows in the other document.