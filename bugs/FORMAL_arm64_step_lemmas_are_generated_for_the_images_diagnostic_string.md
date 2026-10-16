# FORMAL_arm64_step_lemmas_are_generated_for_the_images_diagnostic_string:
# `_gen_step_lemmas` walks the whole code buffer, so `bfeec991`'s embedded
# stack-trap message gets false `sr`/`step_ok` lemmas and `bitops` no longer
# proves

**Area:** FORMAL / arm64 proof generation — `formal/arm64_proof_gen.py`'s
`_gen_step_lemmas` / `_gen_step_result_lemmas` / `_step_result_plan`, over the
`code` buffer `formal/arm64_codegen.py` builds. **Status: OPEN, measured,
NOT FIXED.** Found 2026-10-08 (`work/formal217-docs`) while checking
`bugs/FORMAL_the_arm64_proof_time_floor_is_one_composition_theorem.md`'s pin,
whose subject (`bitops` proving) is now false.

## What I ran

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label tfb -- python3 test_formal.py -j 1 bitops
  [1/1] FAIL  bitops  (build/proof failed: 0 &&& 4292901888 = 2604694528
hb : ¬909189220 >>> 5 &&& 16383 &&& 8192 = 0
hp : s.x4 >>> 6 &&& 1 = 0
⊢ False
bitops_proof.lean:3419:60: error: maximum recursion depth has been reached)
Results for arm64 formal proofs: PASS=0 KNOWN-GAP=0 FAIL=1 TOO-LARGE=0
```

`bitops` is not in `test_formal.py`'s `EXPECTED_FAILURES`, so this is an
unexpected failure — a red `formal` job, not a declared gap. The same verdict
comes from `formal.lean.check_proof_cached` on the generated file directly
(`ok=False`), so it is the proof and not the harness.

## What I saw, and where the word comes from

The failing obligation is a step-RESULT lemma for an instruction that is **not
in `bitops`'s code at all**:

* `bitops`'s entry is `0x1000003d4`, its own last `RET` is `0x100000530`, and
  the walk (`_walk_range`) correctly ends there; the CFG blocks it emits are
  `0x1000003d4 … 0x1000004b8`.
* `bitops_sr_240` (generated proof) is the step-RESULT lemma for
  `pc = 0x100000780`, a TBZ — `arm64_read_insn bitops_code 4294969216 =
  909189220` (`0x36312064`, `tbz x4, #6`) — and `hb : ¬ (909189220 >>> 5 &&&
  16383 &&& 8192 = 0) := by native_decide` is **false**, which is the error.
* The code buffer's tail is a STRING. `formal/model.py::stack_trap_message`
  (`bfeec991`, "derive the stack guard's budget from the process's real
  RLIMIT_STACK, and say so") is emitted into `__TEXT` by
  `formal/arm64_codegen.py::_emit_stack_trap_message`, and measured on this
  image it occupies `[0x100000534, 0x10000087b)` — the `str_0` label is exactly
  its first byte. `0x100000780` is inside it, and `0x36312064` is one of the
  string's words ("d 16" read as little-endian bytes) that happens to decode as
  a TBZ.

**So the word is DATA and the lemma is about it.** `_gen_step_lemmas(name,
code, base)` (`formal/arm64_proof_gen.py:9437`) iterates `for i, w in
enumerate(words)` over the WHOLE `code` buffer, and `_step_result_plan(code)`
(`:9530`, which `_gen_step_result_lemmas` also reads) does the same. Nothing
bounds either to the function. `formal/arm64_codegen.py:1047` ("Append string
literal data") is what puts rodata in `code` in the first place, so this is a
long-standing shape that `bfeec991` newly armed: before it, an arm64 image with
no string literals had no data words to misread, and `bitops` is one of those —
it has no `printf` and no literal. The recursion diagnostic is now in EVERY
arm64 image (the guard's trap arm emits it once per image), so any program whose
message happens to contain a word that decodes as a modelled branch now gets a
false step lemma.

## Why it is not the `getrlimit` regression, and not this document's to fix

`bugs/FORMAL_the_stack_guards_getrlimit_is_counted_as_a_program_call.md` owns
the OTHER half of `bfeec991`: the guard's `getrlimit` is a call the CFG walk
cannot step, so `bitops`'s universal theorem is now
`bitops_reaches_call_at_0x10000041c` rather than a value theorem. **That fix
(move the `RLIMIT_STACK` read into the startup stub) does not touch this one** —
the stack-trap MESSAGE stays in the image either way, and `bitops` would still
be rejected on `bitops_sr_240`. The two are independent consequences of the same
commit and both need their own repair.

## The exact next step

**Bound the step-lemma and step-result walks to the function's code range,
exactly as `_cfg_blocks`/`_gen_universal_e2e_cfg` already are** (`_walk_range`,
`[func_entry, func_end)`; `formal/arm64_proof_gen.py:6888-6894`). Thread
`func_entry` (and the same `func_end`) into `_step_result_plan`,
`_gen_step_result_lemmas` and `_gen_step_lemmas`, whose three callers already
hold it: `:11019` (`generate_arm64_proof`, `func_entry_addr`), `:12161`, and
`:13174` (the dylib generator). **This cannot lose a lemma a proof needs**: every
`{name}_sr_{i}` a certificate references is emitted for a pc inside the walk
(`:5076`, `:5690`, `:6213`), which is by construction within `[func_entry,
func_end)`. A word outside the range is not executed by any certificate, so no
lemma about it is owed.

The anti-rot is the one measurement that fails today: `python3 test_formal.py -j
1 bitops` returns `PASS=1 FAIL=0`. A generation-only assertion beside
`TestBitTestBranches` — that every `{name}_sr_{i}` / `{name}_step_ok_{i}` pc is
within `[entry, last RET]` — pins the bound without a Lean run, so the next
image with a string in its `__TEXT` cannot silently reintroduce this.

## Reproducing

```console
$ export PATH=/opt/homebrew/bin:$PATH
$ python3 tools/memslot.py --gb 8 --label tfb -- \
    python3 test_formal.py -j 1 bitops
$ python3 tools/memslot.py --gb 8 --label tfb -- python3 - <<'PY'
import sys, os, tempfile, shutil
sys.path.insert(0, os.getcwd())
import formal.build as fb, formal.model as M
tmp = tempfile.mkdtemp()
try:
    r = fb.compile_formal("formal/examples/bitops.mojo", arch="arm64",
                          output=os.path.join(tmp, "b.aout"), prove=False)
    code, base = r["code"], r["info"]["base_addr"]
    off = code.find(b"RecursionError: this program")
    print("stack_trap_message at", hex(base + off), "len", len(M.stack_trap_message()))
    o = 0x100000780 - base
    print("word at 0x100000780:", hex(int.from_bytes(code[o:o+4], "little")),
          "inside the message:", off <= o < off + len(M.stack_trap_message()))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
PY
# stack_trap_message at 0x100000534 len 839
# word at 0x100000780: 0x36312064 inside the message: True
```
