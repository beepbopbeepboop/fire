# FORMAL/arm64: a slice or a `+` produces a blob every consumer reads as EMPTY, and `with … as y:` is fixed

**Status: item 1 is FIXED and tested. Items 2 and 3 are OPEN, re-measured, and
much better localised than the version below was — the root cause of the crash
is named, and the two survivors turn out to share ONE symptom that is not the
one the original text blamed.**

Measured 2026-10-02 on this tree, arm64 vs x86-64, CPython as the oracle.
`xs = [1, 2, 3, 4, 5, 6]`, summed with a `for`:

| program | CPython | x86-64 | arm64 |
|---|---|---|---|
| `sum(xs[1:3])` | 5 | 5 | **exit 1, no output** |
| `sum(xs[2:6])` | 18 | 18 | **exit 1, no output** |
| `sum(xs[0:6:2])` | 9 | 9 | **exit 1, no output** |
| `sum(xs[0:4])` | 10 | 10 | **exit 1, no output** |
| `sum(xs[2:1])` (empty) | 0 | 0 | **exit 1, no output** |
| `xs[1:]`, `xs[:3]`, `xs[:]`, `xs[-2:]`, `xs[:-2]`, `xs[3:3]`, `xs[0:1]` | — | correct | **exit 1, no output** |
| `xs[0:6:-1]` (empty) | 0 | 0 | exit 0, **0** |
| `xs[5:0:-1]`, `xs[::-1]`, `xs[4:1:-1]` | 20, 21, 12 | correct | exit 0, **21** |
| `len(xs[1:3])` | 2 | 2 | **REFUSED** (`len(SliceExpr)` — no shape) |
| `[1,2] + [3]`, then `len` | 3 | 3 | **3** |
| `[1,2] + [3]`, then summed | 6 | 6 | **0** |
| `[1] + [2]`, then summed | 3 | 3 | **0** |
| `xs = xs + [3]` over five builds | 3 | 3 | 3, 3, 3, 3, 3 — **the non-determinism is gone** |

So the original text's three claims have all moved: item 1 is fixed (below),
item 2 no longer "returns 1" but exits 1 with nothing printed, and item 3's
non-determinism and its SIGBUS are gone while a *silent wrong zero* is not.

---

## 1. `with … as y:` — FIXED

`formal/model.py::read_before_store`'s `WithStmt` arm walked the body and only
THEN added the `as` alias to `stored`, so the body's own read of the alias was
reported as a read before anything stored it. The alias is bound before the
body runs — that is what `with … as y:` means, and both emitters already do it
(`arm64_codegen._emit_with` and its x86-64 twin store the alias to the context
expression's own value, then emit the body).

Measured before: **REFUSED, on both architectures**, with a message about
`UnboundLocalError`. That message was not merely unnecessary, it was false about
a language the reader can run: CPython's own answer for `with 7 as y:` is
`TypeError: 'int' object does not support the context manager protocol`. The
original filing had this arm64-only and credited x86-64 with "counting the
target store"; on this tree both refuse and both are wrong, because the count
happened to be in the shared `formal/model.py` walk — which is the better place
for it to have been, since the emitters were already agreed.

After: both build and return 7. Test: `test_formal_run.py`'s
`with_alias_is_bound_before_the_body`, and the fix is 07b724f2.

## 2. The slice crash: ROOT CAUSE FOUND, fix NOT landed, and why

`formal/arm64_codegen.py::_emit_slice_parts`'s copy-and-fill loop has **no exit
except the blob capacity check**, and that is not a missing detail — it is two
`emit_label_rel` targets pointing at the wrong blocks plus one missing test:

```python
        self.asm.emit(encode_cbnz_xn(0, 8))          # … the step==0 guard
        neg_init = f"{self.func_name}_sln{…}"
        self.asm.emit_label_rel(neg_init, here_offset=-4)
        self._emit_b_to(f"{self.func_name}_slm{…}")     # loop head
        self.asm.label(neg_init)                        # ← the i = stop - 1 code
        … i = stop - 1 …
        self.asm.label(f"{self.func_name}_slm{…}")      # loop head again
```

`cset x0, lt` / `cbz x0` means "**step >= 0** jumps to the label", and the
relocation pointed at `neg_init`, which is placed *after* the `b loop`. So a
FORWARD slice branched over the `i = start` it had just loaded and landed on
`i = stop - 1` instead. The loop head then had the same shape:

```python
        self.asm.emit(encode_cbz_xn(0, 0))             # step >= 0 → positive
        self.asm.emit_label_rel(neg_body, here_offset=-4)   # … pointed at NEGATIVE
        # positive: body if i < stop else done
        self._emit_b_to(body)                          # ← …and branched to body anyway
        self.asm.label(neg_body)
        # negative: body if i >= 0 else done
        … i >= 0 test … b body
```

The positive arm's comment says "body if `i < stop` else done" and the next
instruction is an unconditional `b body`: **the `i < stop` test does not exist.**
With the two crossings, whichever way `step` pointed, the loop appended until
`_compr_append_elem`'s capacity check fired and then `_exit(1)`'d — through
`svc #0x80`, which does not flush stdio, so the program printed **nothing** and
the diagnostic named neither the slice nor the index. That is why the original
text read the shape as "the count the source never wrote": a capacity exit looks
like a count that never advanced.

The whole loop is in `.tmp/arm64_slice_loop_fix.patch` (a `git diff` of the
two corrections: give `step >= 0` the fall-through and `step < 0` the inline
`i = stop - 1`; add the missing signed `i < stop` test on the positive arm, with
`stop` re-read from `[SP+0]`).

### Why the patch is NOT in the tree

Applied, it removes the crash — every forward slice builds and runs — and leaves
the construct **still wrong, silently**:

| after the patch, arm64 | CPython |
|---|---|
| `sum(xs[1:3])` | 0 (want 5) |
| `sum(xs[2:6])` | 0 (want 18) |
| `sum(xs[0:6:2])` | 0 (want 9) |
| `sum(xs[0:1])` | 0 (want 1) |
| `sum(xs[::-1])` | 21 (want 21 — right by luck) |
| `ys[0]` for `ys = xs[1:3]` | **exit 1** |

So there is a SECOND defect, independent of the loop, in whatever makes the
materialised view's blob readable. Turning a loud exit-1 into a silent 0 is the
worst trade this backend makes — `CLAUDE.md`'s "a wrong answer that looks right"
— so the patch is not landed and this section is the record of why.

**What the second defect looks like, for whoever finishes it.** The disassembly
(`otool -tvV` on the built image) says the slice loop is byte-for-byte correct
after the patch — `i = start`, a signed `cmp` against `stop` re-read from
`[SP+0]`, the append, `i += step` — and `ys` is stored from the blob's own
address (`add x21, x0, #0`). What fails is every CONSUMER:

* `ys[0]` exits 1 at the bounds check, so the blob's count word reads 0;
* `for v in ys` sums 0, the same count read;
* `len(ys)` is REFUSED as `len() of a value classified as 'int'`, while
  `len(xs)` on the un-sliced list is 6 — so **the model does not know a
  slice-bound variable holds a list**. `formal/types.py`'s `infer_expr` returns
  `DEFAULT_INT_TYPE` for a `SliceExpr` (line 161), which is the same answer it
  gives a list literal, so the difference is somewhere else in the VarDecl
  inference; that is where to start reading.

One structural observation that may or may not be the cause, recorded because it
was measured and not chased: the slice's own blob and the operand's blob are
**adjacent, and the operand's lies BELOW the frame pointer** in the same window
the four 16-byte pushes occupy — `xs`'s blob resolves to `x29 − 0x40 − 0x20000`
and the slice's to `x29 − 0xfe8 − 0x1f000`, with SP at `x29 − 0x20000`, so the
pushes (SP−64 … SP−1) land on the top word of `xs`'s blob. The slice reads
`count` before the last push, so its own result is unaffected, but anything that
re-reads the operand's header after the pushes would see the pushed value.
`x86_64_codegen._emit_slice` is the reference for what this path should look
like.

## 3. `list + list`: still wrong, and the symptom is now SILENT

`_emit_list_concat` in the arm64 backend. `len` is right (3, stable across five
builds — the non-determinism and the SIGBUS in the original text are gone), and
every CONSUMER of the result reads it as empty:

```
    var xs = [1, 2]
    xs = xs + [3]
    len(xs)   →  3     correct
    sum(xs)   →  0     CPython 6
    [1] + [2] summed → 0  CPython 3
```

**The same signature as §2's second defect**: the count word of a blob this
backend just materialised reads 0 to a consumer while a `len` of the same blob
through the other path reads correctly. That is one bug in two places, not two,
and §2's `infer_expr` lead is where to look first. `x86_64_codegen`'s
`_emit_list_concat` computes all of it correctly and is the reference.

## 4. `len(xs[1:3])` is a refusal in its own right

Both backends refuse `len` of a slice with `model`'s "the source does not say
what this operand holds", which is true — but the construct has an exact answer
and the refusal hides it behind a shape question. `len` of a *bound* slice is
worse: it says the variable is classified as `int`, which is the §2 lead again.

## 5. Blast radius for whoever takes these

`tools/formal_sweep.py` measures which files BUILD per backend, so a change here
is the "type-resolution change that quietly regresses modules" shape
`CLAUDE.md` warns about — compare before/after counts, and the `x86-examples`
differential (45 `formal/examples` through BOTH backends, compared) is the
cheapest regression signal for all three. Nothing here was swept: this was a
light worker with no budget for `formal_sweep.py`.

**Checked and NOT these:** not `FORMAL_string_value_model.md` (a `char *` base
is refused by `model.string_slice_refusal` before any of this runs, and was
measured to SIGSEGV rather than exit 1 — a different symptom and a different
refusal); not `FORMAL_wide_receiver_by_reference.md` (that is what a frame
HOLDING a list is, and none of these programs uses one).
