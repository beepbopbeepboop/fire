# `q.b += 5` on a base that is an EXPRESSION: arm64 refuses with its own sentence where x86-64 now refuses with the shared one

**Area:** formal backends (`formal/arm64_codegen.py`, the `AugAssignStmt` arm).
**Status: OPEN, measured on this tree, not fixed.** Found 2026-10-04 while merging
`work/formal23-5-r2` into `work/merge-formal27a` and running
`test_formal_run.py`; it is the one row of that branch's pointer-model work that
could not keep its measured words, and the reason is the improvement on master,
not the merge.

## What I ran, what I saw

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_run.py deref_refuse_augmented_through_a_pointer_frame
FAIL  deref_refuse_augmented_through_a_pointer_frame: --backend=x86_64 refused,
but not with any of ['unsupported augmented assignment target on the formal
arm64 path', 'augmented assignment target must be a plain name on the formal
x86-64 path']: rings one when the source it was built from is still readable. Do
not re-declare the struct here — that is a different type with the same name, and
the layout the library's methods use would not be it
```

The program, from `test_formal_run.py`'s `POINTER_DEREF_REFUSALS`:

```python
struct P3:
    var a: Int64
    var b: Int64
    var c: Int64
def bump(p: Pointer[P3]) -> Int:
    p.value().b += 5
    return Int(p.value().b)
def main(n: Int) -> Int:
    var t = P3()
    return bump(t)
```

Measured directly, one backend at a time, through `formal/build.py`:

| backend | what it says |
|---|---|
| arm64 | `unsupported augmented assignment target on the formal arm64 path` |
| x86-64 | `bump: 'p.value(...).b' is a field access through 'p.value(...)', and this path has no way to say what 'p.value(...)' holds. …` |

Both refuse — which is the answer, and it is what
`bugs/FORMAL_pointer_value_model.md`'s §9 records as a limit. **The divergence is
in the WORDS**, and that is what this doc is about.

## Why the two sentences are not two opinions about the same fact

The x86-64 one is `model.member_access_refusal`, the shared model's, reached
through `_refuse_member_target` — which is what the augmented arm raises when
`_frame_member_slot` answers `None`. That is CORRECT and is the improvement: the
old x86-64 sentence, *"augmented assignment target must be a plain name on the
formal x86-64 path (got MemberExpr)"*, is false about the file, because a
`MemberExpr` target **is** lowered here whenever the member is a frame slot
(`self.count += 1` on a by-reference receiver goes through exactly this arm). The
real premise is the BINDING OF THE BASE, which is what the shared sentence says,
and master is the commit that made the arm say it
(`bugs/FORMAL_the_two_backends_refuse_different_constructs_in_the_same_function.md`,
deleted with its fix).

arm64's `AugAssignStmt` arm still raises a literal of its own for the same shape:

```python
if isinstance(stmt.target, F.MemberExpr):
    slot = _member_slot_key(stmt.target)
    if slot is None:
        raise CodegenError(
            "unsupported augmented assignment target on the "
            "formal arm64 path")
```

So the sentence arm64 emits is the pre-fix one — false about the arm64 file for
the same reason it was false about the x86-64 one, since arm64 lowers a
`MemberExpr` target through `slot` whenever the member is a frame slot.

## The exact next step

One arm, two lines, and it is the same call x86-64 makes:

1. In `formal/arm64_codegen.py`'s `AugAssignStmt` arm, replace the literal
   `raise CodegenError("unsupported augmented assignment target on the formal
   arm64 path")` with the shared `raise CodegenError(M.member_access_refusal(
   stmt.target, self.func_name, self._frame_holders))`. arm64 already raises
   `member_access_refusal` at three other sites (`_emit_expr`'s member arm, the
   read arm and the store arm), so this makes four agree instead of three.
2. Then `test_formal_run.py`'s `deref_refuse_augmented_through_a_pointer_frame`
   stops needing `refuse_either:` at all: both machines would emit the same
   needle. That is the honest end state, and it is worth checking for rather than
   assuming — the row exists to record a divergence, and a divergence that is gone
   must not leave a `refuse_either:` behind that would go green either way.
3. The other rows that pin arm64's augmented sentence for a NON-member target
   (`M.aug_assign_target_refusal`, `formal/model.py:38224`) are a different fact
   and should keep their needle; check them separately rather than sweeping the
   string.

**This is a message-only change.** Nothing about what either backend accepts
moves: the same programs are refused on the same two architectures before and
after, so a green run of the formal suites after it is evidence the wording moved
and nothing else did.

## How the merged tree records it meanwhile

`test_formal_run.py`'s `deref_refuse_augmented_through_a_pointer_frame` keeps
`refuse_either:` with the shared x86-64 clause
(`is a field access through 'p.value(...)'`) and arm64's own sentence, and the
row's comment says why each half is what it is. That encoding is honest about
"refused on both, and the two disagree about how they say so" — which is the
state of the tree until step 1 lands.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label t -- \
      python3 test_formal_run.py deref_refuse_augmented_through_a_pointer_frame
```