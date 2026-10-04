# FORMAL_a_variadic_parameter_read_has_no_abi: the row was unowned, and the refusal in it is CORRECT

**Status: NOT FIXED, and correctly so at the width it is written at.** The
refusal is right and the ABI decision is still unmade — but the CORPUS half is
now done (2026-10-04, `formal21-2`): `tools/formal_fuzz.py` can emit a `*rest`
DEFINITION and a call site for it, so the day the ABI lands, a `--mix limits`
sweep measures it instead of being unable to produce the construct at all. That
was §5 step 5 and it was measured ABSENT; the measurement and what it now shows
are in §5 below. Everything else on this list is untouched, and the reason is
the doc's own: the emitters and `lib/ProofLib.lean` have to move together and
the latter's 27 MB `.olean` peaks at 7.82 GB to rebuild.

**Area:** `formal/build.py::_refuse_variadic_reads` /
`formal/model.py::variadic_read_refusal` (the refusal), and for the fix
`formal/arm64_codegen.py`, `formal/x86_64_codegen.py`, `lib/ProofLib.lean` and both
`formal/*_proof_gen.py`. **Both architectures** — measured below, not inferred.
Filed 2026-10-04 by
`sweep20:sweep-b10` from the b10 sweep, where it is the **7th-largest codegen cause and the
largest one with no document and no claim.**

## Why this was filed

`bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §3 ranks it **7 files, 2 of them in-file**, and
§4.4 records that **no claim existed**. That is the whole reason for the file: an unowned row in
a queue is not a smaller row, it is a row nobody is going to pick up, and this one is the only
row in the top ten that is neither claimed nor documented. `…_b9.md` did not have it (the
`-9` sweep put one file here), and no `bugs/` doc mentions `variadic call has no ABI` at all.

| files | blocked by | what |
|---|---|---|
| 5 | `std/algorithm/backend/tile.mojo` | two `def tile(…)` overloads read their own `*tile_size_list: Int` (line 91) and `*primary_tile_size_list: Int` (line 130) — `for tile_size in tile_size_list:` at 110, and `primary_tile_size_list[i]` at 157. **All 5 name `tile`, so this half is WORK and not closure** |
| 1 | itself | `std/algorithm/backend/tile.mojo`'s own second `def tile(…)`, the binary one |
| 1 | itself | `formal/x86_64_decode.py`, which spreads `**kw` into a construction. **A DIFFERENT refusal** — a spread's KEYS are not knowable at the construction site — but its last sentence is this one: *"a `**`-PARAMETER cannot be the operand here either: a formal value is one 64-bit word and this target has no variadic ABI"*, so the causes table counts it on this row and the doc that says so is this one |

## What I ran, and what I saw

`formal/build.py::_refuse_variadic_reads` refuses a body that **reads** its `*args` /
`**kwargs`, by name, with the reason. One program, both architectures:

```console
$ cat .tmp/probe/varargs.mojo
def f(x, *rest):
    return len(rest)

def main():
    print(f(1, 2, 3))

$ python3 tools/memslot.py --gb 8 --label varargs -- \
      python3 fire.py build --formal --no-prove -o .tmp/probe/varargs .tmp/probe/varargs.mojo
build: f: the body reads 'rest', its *-parameter, and this path has no variadic ABI.
A formal value is one 64-bit word, so the arguments a caller passes past the fixed ones
(this module's call sites pass 3..3 argument(s), against 1 fixed parameter(s)) have
nowhere to be packed — a tuple of them is a container, and a container on this path is a
frame-allocated blob in the frame of the function that built it, which the caller is not.
Passing a variable number of arguments is a change to the calling convention both backends
AND the Lean proof share. …
```

Both backends, byte-identical apart from nothing (`test_formal_run.py::build_formal` with
`backend="arm64"` and `backend="x86_64"`, both `rc=1`, both naming the variadic ABI), and
`…_b10.md` §2.2 measured the same class and the same cause on all 569 classified files of the
710-file sweep, so the row is 7 files on each machine rather than 7 and some other number.

## Why the refusal is RIGHT, and why the cheap-looking fix is a wrong answer

This is the part worth writing down, because the obvious next step is a miscompile.

**The caller side already drops the extra arguments**, and `variadic_read_refusal`'s own
docstring says so: `_bind_call_args` passes the fixed parameters and truncates the rest. So it
is tempting to conclude that a variadic parameter's value is *the empty sequence* — every extra
argument is discarded, therefore the read sees nothing — and to lower it as a constant of length
0. **That is a wrong-but-exit-0 answer, and it is measurably wrong:**

```console
$ python3 -c 'def f(x,*r): return len(r); print(f(1,2,3))'
2
```

CPython answers **2**. An "empty" lowering answers **0**, for every call site that passes
anything, and every such program then runs to completion printing a number that is not the one
Python prints. The same program with `g(1)` does answer 0, which is what makes the mistake
survive a casual test: **the empty answer is right exactly when no extra argument was passed,
and wrong otherwise, and nothing in the program says which case it is.** The arity is knowable
per call site — the refusal message even reports it (`this module's call sites pass 3..3
argument(s)`) — but it is knowable only *per function*, and one function is reached from many
call sites.

So the row is not a missing container and not a missing check. **It is the calling convention.**
A variadic parameter needs somewhere to put a value whose count is not known until the callee is
reached, and a formal value is one 64-bit word with a home in a register, a spill slot, a
receiver's frame or a folded constant — none of which is "a count of words".

## What a fix is, in order

1. **Decide the variadic ABI, in writing, in `doc/ABI.md`, before any emitter moves.** The three
   shapes that fit a one-word value model, and what each costs:
   * **a packed heap block the callee owns** — the callee needs a pointer to a count and a base,
     which is two words and a free/entry discipline at every `return`, and `lib/ProofLib.lean`
     would need the block's layout in the value model (`sdiv64`'s comment about the source model
     and the value flow not drifting apart is the constraint to respect here);
   * **a per-instantiation fixed arity**, i.e. monomorphize on the argument count the way
     `formal/monomorph.py` already monomorphizes on type arguments — this is the shape that fits
     the existing machinery, and it is the one the b10 sweep's biggest row needs anyway
     (`…_b10.md` §3.1: 79 call sites whose only missing thing is an inferred type argument);
   * **refuse `*args` at the DECLARATION and keep the read refusal** — cheapest, loses the 7
     files, and is defensible: `variadic_read_refusal`'s last sentence already tells the reader
     to "take the arguments as named parameters, or read them from a list the caller passes",
     which is the same program with a representation.
2. **arm64's emitter, then x86-64's, then both `formal/*_proof_gen.py`, then
   `lib/ProofLib.lean`.** In that order, in one commit: the model and the emitted code cannot
   drift apart, and a tree where the model says one thing and the machine does another makes
   every proof of a variadic function wrong with no gate able to see it.
3. **`tile.mojo` needs option 1 or 2, not option 3.** Its `tile(…)` iterates
   `*tile_size_list` (line 110) and indexes `*primary_tile_size_list[i]` (line 157), so the
   count is dynamic per launch — a fixed-arity monomorphization on the *call site* would work
   (the launchers pass a known number of tile sizes) and is the shape to try first. Note that
   the parameter is variadic **`Int`**, not a container: the read is a tuple of words, which is
   the ABI question above rather than a `List` question.
4. **The 7 files, re-measured** the way `…_b10.md` §5.2 measures a fix:
   `python3 tools/formal_sweep.py --min 3` over exactly those 7 paths, and the row's ceiling.
   **Expect the 5 `tile.mojo` files to land on `tile.mojo`'s own next row, not on a pass** — the
   row behind this one is `std/algorithm`'s bracketed specialization
   (`FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_value.md`, claimed), which is
   `FILES BLOCKED IS AN UPPER BOUND` doing what §2.4 of the b10 map measured it doing to the
   43-file Optional row.
5. ~~**Add a `*args` DEFINITION and READ to `tools/formal_fuzz.py`'s pools —
   measured absent.**~~ **DONE 2026-10-04 (`formal21-2`).** `variadic_define`
   and `variadic_call` are in the `limits` mix. Three properties, each of which
   the doc's own analysis says the corpus needs and which a sloppier family
   would have got wrong:

   * **the READ is `len(rest)`**, not `rest[0]`, because CPython has to be able
     to ANSWER the program: `len(rest)` is the shape whose wrong-but-exit-0
     answer is measurable (an "empty" lowering prints 0 where CPython prints the
     number of extras), while `rest[0]` on an empty tuple is an `IndexError`,
     and an oracle that errors takes the whole program's verdict with it;
   * **the call site VARIES the count** (0..3 extras) — the doc's sharpest point
     is that "the empty answer is right exactly when no extra argument was
     passed, and wrong otherwise, and nothing in the program says which case it
     is", so a corpus that always passed zero extras could not tell the two
     apart either;
   * **both halves are one feature**: a definition with no call site is dead
     code, and a read with no definition is a `NameError`, so emitting only one
     produces no verdict at all.

   Measured after, six seeds of `--mix limits` on both architectures:

       refusal audit: true=12, unnamed=0, false=0, no-predicate=0

   and the refusal the family reaches is the one above, reporting the two
   numbers the corpus now varies:

       build: var7: the body reads 'rest', its *-parameter, and this path has no
       variadic ABI … (this module's call sites pass 2..5 argument(s), against 2
       fixed parameter(s)) …

   `test_formal_fuzz.py` PASS — 0 failures, with `limits` still 30/30
   audited-true. **So the coverage hole is closed and the ABI decision is not**:
   the family can now notice the day it is landed, which is the whole of what
   step 5 was for.

   Its docstring's "what a mix does NOT generate" list (§ the `--mix` families, the bullet above
   `THE COST OF A MIX`) rules out a variadic `printf` with more than five operands and points at
   `test_formal_run.py`'s `BOTH_ARCH_CASES` ladder for the stack-argument convention; it says
   nothing about a function that *declares* `*args` and reads it, and a grep of the generator for
   `*args` / `variadic` finds only that bullet. So a generator that cannot emit the construct cannot
   notice the day it is fixed — the same anti-rot the `signed` mix's floor division records:
`tools/formal_fuzz.py`'s `floordiv`/`modulo` `KNOWN_DIVERGENCES` rows were deleted when both
backends learned to floor, and what replaced them is `MIX_MUST_GENERATE`, which asserts the mix
still PRODUCES a signed-over-signed division (`test_formal_fuzz.py::_check_generation`) rather
than asserting it still diverges. Deleting the rows without that would have left both rows
UNREACHABLE behind a green run; deleting the mix as well would have left a corpus that no longer
measures the construct at all.

## Why no light worker landed it

The emitters and the Lean model must move together, and `lib/ProofLib.lean` is the source of the
27 MB `ProofLib.olean` every proof-checking path links against: `formal/lean.py`'s own measured
table records that build at **112 s wall and a 7.82 GB peak**, which does not fit the 8 GB a
light worker is given here, and this repository's standing rule is that anything over 3-4 GB is a
bug rather than a fact (`bugs/PERF_memory_over_4gb_is_a_bug.md`). `formal/lean.py::run_lean` is
not to be launched by this class of worker at all. Landing the runtime half alone would leave
every existing proof RED on any variadic function, silently — which is the honest intermediate
state a document should describe and not a state a commit should create.

## Reproducing

```console
$ python3 tools/formal_sweep.py --min 3 bugs/sweeps/sweep-arm-10.txt     # §"Why this was filed", 7 files
$ python3 tools/memslot.py --gb 8 --label varargs -- \
      python3 fire.py build --formal --no-prove -o .tmp/probe/varargs .tmp/probe/varargs.mojo
$ python3 -c 'def f(x,*r): return len(r); print(f(1,2,3))'             # 2, and the empty answer is 0
```

Both arms' logs are committed (`bugs/sweeps/sweep-arm-10.txt`,
`bugs/sweeps/sweep-x86-10.txt`), and the map that ranks the row is
`bugs/FORMAL_sweep_work_map_2026-10-04_b10.md` §3 and §4.4.