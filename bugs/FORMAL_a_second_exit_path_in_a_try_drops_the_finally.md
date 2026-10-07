# A `try`'s `finally` runs on the FIRST exit path out of its body and on no other

**Area:** FORMAL, `try`/`finally` lowering. Found 2026-10-05 on
`work/formal55-match-statements` by the `match` oracle table
(`test_formal_match.py`'s `arm_return_inside_a_try_runs_the_finally` row), and
it reproduces with **no `match` in the program at all** — see §1. **OPEN.**
Not this branch's claim (`project:match-statements`); the machinery is
`_flush_pending_finally`, shared by both emitters, and a `with` lowered to
`try`/`finally` (`_rewrite_with_statements`) inherits every one of these.

## 1. What I ran and what I saw

`.tmp`-free reproduction, both architectures, `--no-prove`:

```sh
cat > /tmp/f.py <<'EOF'
def two_returns(n):
    try:
        if n == 1:
            return 10
        return 20          # <- second exit out of the SAME try body
    finally:
        print('fin-a')

def main():
    print(two_returns(1))
    print(two_returns(2))
    return 0
EOF
python3 fire.py build --formal --no-prove --backend=arm64   -o /tmp/f.arm64 /tmp/f.py && /tmp/f.arm64
python3 fire.py build --formal --no-prove --backend=x86_64 -o /tmp/f.x86   /tmp/f.py && /tmp/f.x86
python3 /tmp/f.py            # CPython, the oracle
```

| | CPython | arm64 | x86-64 |
|---|---|---|---|
| `two_returns(1)` | `fin-a` then `10` | `fin-a`, `10` | `fin-a`, `10` |
| `two_returns(2)` | `fin-a` then `20` | **`20` — no `fin-a`** | **`20` — no `fin-a`** |

The first exit path flushes the `finally`; the second one does not. Same
program, same answer on both machines, so this is not a two-backend
disagreement — it is the same defect reached twice, which is why it survived:
a parity fuzzer sees two matching wrong answers.

**A larger probe, same shape, both backends byte-identical:**

```sh
cat > /tmp/g.py <<'EOF'
def two_returns(n):
    try:
        if n == 1:
            return 10
        return 20
    finally:
        print('fin-a')

def three(n):
    try:
        if n == 1:
            return 10
        elif n == 2:
            return 15
        return 20
    finally:
        print('fin-b')

def loop_break():
    out = 0
    for i in range(0, 4):
        try:
            if i == 1:
                out = out + 100
                continue
            if i == 2:
                out = out + 1000
                break
            out = out + i
        finally:
            print('fin-c', i)
    return out

def nested(n):
    try:
        try:
            if n == 1:
                return 1
            return 2
        finally:
            print('inner')
    finally:
        print('outer')

def main():
    print(two_returns(1)); print(two_returns(2))
    print(three(1)); print(three(2)); print(three(3))
    print(loop_break())
    print(nested(1)); print(nested(2))
    return 0
EOF
```

CPython prints `fin-a 10 / fin-a 20 / fin-b 10 / fin-b 15 / fin-b 20 /
fin-c 0 / fin-c 1 / fin-c 2 / 1100 / inner outer 1 / inner outer 2`.
**Both backends print** `fin-a 10 / 20 / fin-b 10 / 15 / 20 / fin-c 0 /
fin-c 1 / 1100 / inner outer 1 / 2`.

So every LOST cleanup is an exit that is not the first one emitted:

* `three(2)` and `three(3)` lose `fin-b` — two `return`s after the first;
* `loop_break` loses `fin-c 2` — the **`break`** is the second exit out of that
  `try` body (the `continue` at `i == 1` took the first), and the loop's answer
  `1100` is still right, so nothing else reports it;
* `nested(2)` loses BOTH `inner` and `outer` — the first exit flushed the whole
  stack, so the second found an empty one.

`raise` and `assert` are the same shape by construction (they both call
`_flush_pending_finally` before leaving), and `continue` is the same as `break`
(`depth` differs, the truncation does not).

## 2. Why — the exact mechanism

`formal/arm64_codegen.py::_flush_pending_finally` and
`formal/x86_64_codegen.py::_flush_pending_finally` are the same code:

```python
if len(self._pending_finally) <= depth:
    return
fins = self._pending_finally[depth:]
del self._pending_finally[depth:]      # <- DESTRUCTIVE
...
for fin in reversed(fins):
    for s in fin:
        self._emit_stmt(s)
```

`self._pending_finally` is the EMITTER'S, and it is a compile-time stack of
the `finally` bodies currently being emitted — `_emit_try` pushes
`stmt.finally_body` before the body and pops it after. The `del` exists for a
real reason, and both docstrings say so: *"The list is truncated first so a
return inside a finally does not re-enter the same body."* That is the whole
purpose.

But truncating is not the same as guarding, and the difference is the bug: the
`del` removes the frame for **every later exit site in the same `try` body**,
not only for the nested `return` it was written for. The second `return` in
`two_returns` reaches `_flush_pending_finally` with an EMPTY list, the guard at
the top returns, and no cleanup is emitted on that path at all. The state is
per-COMPILE-TIME, and the emitter visits exit sites in source order, so
"already flushed" means "flushed by a site that is not on this path".

`_emit_try`'s own comment shows the same confusion one level up — it already
knows that "the fall-through path is a different path through the same block"
and emits the fall-through copy even when an exit flushed the frame. The exit
sites do not have that allowance.

## 3. The next step

Replace the destructive truncation with a RE-ENTRANCY GUARD, and keep the
frames:

```python
# both emitters
def _flush_pending_finally(self, depth: int = 0) -> None:
    frames = self._pending_finally[depth:]
    if not frames:
        return
    self.asm.emit(encode_stp_sp_pre(0, 31))          # arm64; _push_slot on x86-64
    for fin in reversed(frames):
        if id(fin) in self._emitting_finally:         # a `return` inside this body
            continue
        self._emitting_finally.add(id(fin))
        try:
            for s in fin:
                self._emit_stmt(s)
        finally:
            self._emitting_finally.discard(id(fin))
    self.asm.emit(encode_ldp_sp_post(0, 31))          # arm64; _pop_slot on x86-64
```

Keying on `id(fin)` (the statement list object `_emit_try` pushed) rather than
on an index is what makes it safe: `_emit_try` pops frames as it unwinds, so
every index-based "in progress" marker shifts underneath a nested `try`, and a
frame's identity does not. `_emit_try`'s own pop (`… [-1] is fin`) needs no
change — it is already identity-based.

Then re-run the §1 probe. Every row should print CPython's line.

**What this does not fix**, and is a separate defect with its own document:
`FORMAL_a_return_inside_a_finally_emits_two_epilogues_on_arm64.md` (a `return`
inside a `finally` SIGBUSes on arm64). The guard above is what makes that bug
*expressible* to fix — with the frames still on the stack, the nested `return`
has something to be skipped past — but the double epilogue is an emitter-state
question of its own.

## 4. Why it matters beyond tidiness

`formal/build.py::_rewrite_with_statements` lowers every `with` to
`try`/`finally` **precisely so the cleanup runs on every way out**, and its own
docstring names the contract: `with TmpDir() as d: … return x` must remove the
directory. A `with` body with two exits loses the cleanup on the second one, so
a `TemporaryDirectory` is left on disk — and the program still exits 0 and
prints the right answers, which is the failure class this repository treats as
worse than a crash.

## 5. Where it is pinned

`test_formal_match.py`'s `arm_return_inside_a_try_runs_the_finally` row asserts
the **current** answer (`one / fin / 10 / 20 / done`) with CPython's in a
comment, so the defect cannot be fixed silently: the row fails when the fix
lands and the row is updated in the same commit.