# a name bound from one holder and then REBOUND from another keeps the first layout, and the two architectures read different words

**Area:** FORMAL (the holder fixpoint in `formal/build.py::_frame_receivers`).
Found 2026-10-04 on `work/formal23-5-r2`, while landing the pointer-frame
recognition `bugs/FORMAL_pointer_value_model.md` §4 asked for; not that claim's
subject and **not fixed here** — see §5.

**Status: CONFIRMED on `master`, and it is a wrong answer rather than a refusal —
on two architectures that disagree with each other.**

## 1. What was run

```console
$ cat .tmp/p3/ctor_past.mojo
struct Three:
    var a: Int64
    var b: Int64
    var c: Int64
struct Two:
    var x: Int64
    var y: Int64
def pick(o: Two, which: Int) -> Int:
    var q = Three()
    if which > 0:
        q = o
    return Int(q.c)
def main(n: Int) -> Int:
    var o = Two()
    return pick(o, n)

$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove -o out.arm64 ctor_past.mojo
$ python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove --backend x86_64 -o out.x86 ctor_past.mojo
$ ./out.arm64 ; echo "arm64 exit=$?"
$ arch -x86_64 ./out.x86 ; echo "x86-64 exit=$?"
```

```
Built: out.arm64  [arm64/macho]
Built: out.x86    [x86_64/macho]
arm64 exit=0
x86-64 exit=208
```

**Both builds SUCCEED and the two machines answer differently.** `q` is a
`Three` frame on the path where `which <= 0` and a `Two` frame on the other, and
`q.c` is slot 2 — past the end of a two-slot frame. The program never writes
that word, so 0 and 208 are both answers to a question the source does not ask.
This is the exact class `model.struct_frame_slot_candidates` exists to refuse
("one name has two frame layouts, and settling on either computes a slot index
that is wrong on the other path"), reached by a route that table never sees.

Reproduces identically from a `git archive HEAD` export with no diff applied, so
it is on master and predates every change in the branch that found it.

## 2. Why the disagreement is not there

`_frame_receivers`' fixpoint has three edges that make a name a holder, and a
fourth that copies one:

| edge | where | what it does |
|---|---|---|
| constructor binding | the seeding loop, `_constructor_bindings` | `q = Three()` → `{q: [Three]}`. **Enumerates every constructor binding in the body**, so two of them give two candidates |
| declared parameter | the same loop, `parameter_declared_structs` | `o: Two` → `{o: [Two]}` |
| frame-returning call | inside the fixpoint | `q = make()` → `{q: [A]}` |
| the copy edge | inside the fixpoint | `q = o` where `o` is a holder → `{q: [Two]}` |

The copy edge is:

```python
if target and isinstance(value, F.IdentExpr) \
        and value.name in hs and target not in hs:
    hs.add(target)
    hstruct[_fn_key(fn)][target] = list(hstruct[_fn_key(fn)][value.name])
    changed = grew = True
```

**`target not in hs` is the hole.** `q` is already a holder — from its own
constructor binding — so the edge declines, and the second layout is the one that
disappears. The guard is there for a reason (a name already classified keeps its
classification rather than gaining a second opinion, and the two disagree rather
than the one being wrong), but as written it makes the outcome depend on WHICH
edge ran first, and the constructor seeding always runs first.

So the disagreement a reader should expect — the refusal — is missing for the
`rebound from another holder` shape specifically. Two constructor bindings still
refuse correctly; a constructor binding plus a rebind does not:

```mojo
var q = Three(); q = other_three()      # refused: two candidates
var q = Three(); q = o                  # BUILDS, and o's layout is lost
```

## 3. What makes it a wrong answer rather than a rough edge

`q.c` reads slot 2 of whatever `q` addresses. Which of the two frames that is
depends on a runtime value (`which`), so the read is not merely misplaced — it is
a different word on each path, and the slot index was computed from the layout
that lost. When the two layouts happen to agree in width the answer is
*accidentally* right, which is what makes this worth a doc rather than a shrug:
with two three-field structs the same program builds and returns a plausible
number on both machines.

The arm64/x86-64 divergence is the sharpest evidence that no pass is looking at
this: the two emitters reach the slot by different instruction sequences
(`ldr xt, [x17, #8k]` vs `mov r64, [rax + 8k]`), and the frame slots the two
builds lay out are not the same block, so the word past the end of `Two`'s frame
is whatever each machine's scratch held.

## 4. Where it is NOT

* Not the pointer path. `q = p.value()` bound to a frame this module declares
  has the same hole (measured, and identical to the constructor case beside it),
  but that is inheritance rather than a new class — and it is why
  `work/formal23-5-r2`'s new edge in the same fixpoint MERGES its candidate
  into the list instead of replacing it, rather than deciding on its own.
* Not `_check_holder_agreements`. That pass asks whether a PARAMETER is reached
  with a frame address at one call site and something else at another; this is
  one function's local rebinding, which it never sees.
* Not `struct_frame_slot_candidates`. That function is correct and is refusing
  correctly everywhere it is asked; nothing routes a rebind to it.

## 5. The exact next step

Make the copy edge MERGE rather than skip, and let the existing disagreement
machinery decide:

```python
if target and isinstance(value, F.IdentExpr) and value.name in hs:
    known = hstruct[_fn_key(fn)].get(target)
    if known is None:
        hs.add(target)
        hstruct[_fn_key(fn)][target] = list(hstruct[_fn_key(fn)][value.name])
        changed = grew = True
        continue
    for st in hstruct[_fn_key(fn)][value.name]:
        if st not in known:
            known.append(st)          # a second layout, not a second opinion
            changed = grew = True
```

The candidate list is a SET that only grows, so the fixpoint stays monotone and
terminates; and a name whose two layouts agree is unaffected, because
`struct_frame_slot_candidates` is asked about `q.c` and one candidate answers it
exactly as before.

**Do not narrow it to the pointer case.** The constructor rebind above is the
same defect with none of the pointer model's involvement, and a fix that only
touched the new edge would leave the older, simpler reproducer building.

**The cost is a whole-module sweep and it is not small:** `hs` is the holder set
of every function in a unit, so this changes which refusals fire across
`myinterpreter.py` and the stdlib, and the honest measurement is
`python3 tools/formal_sweep.py -j 4 -t 120 --arch both` plus
`tools/formal_sweep_causes.py` over the result — an integrator's run, not a
worker's. Expect some files to move from `codegen` to `codegen/dependency`,
which is the correct direction: a refusal where a wrong answer was.

## 6. Reproducing

```sh
export PATH=/opt/homebrew/bin:$PATH
# the source is in §1; write it to .tmp/ctor_past.mojo
python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove -o .tmp/out.arm64 .tmp/ctor_past.mojo
python3 tools/memslot.py --gb 8 --label t -- \
    python3 fire.py build --formal --no-prove --backend x86_64 -o .tmp/out.x86 .tmp/ctor_past.mojo
./.tmp/out.arm64; echo "arm64 exit=$?"
arch -x86_64 ./.tmp/out.x86; echo "x86-64 exit=$?"
```