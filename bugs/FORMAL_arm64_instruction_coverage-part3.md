# Pin that the emitter emits no non-UXTX extended-register word (part 3)

Part 3 of `bugs/hard/FORMAL_arm64_instruction_coverage.md`.
Class: easy — a test class; no production change.

## Measured (2026-11-14, this tree)

The original doc records the gap as DORMANT: the image of `def plain(a, b):
return a + b` carries zero words of the extended-register class, so the gate
stays green and the gap bites only when the emitter emits one. Re-measured on
this tree with the `TestStepLemmasCoverTheExecutableRegionOnly` fixture (a
dylib whose export prints a literal, compiled with `prove=True`): ZERO words
of the extended-register class in the executable region — not one option=011
word, let alone a refused one. The only producer of these words in the tree is
the platform assembler (clang spellings such as `cmp sp, x16` = `0xeb3063ff`,
which is how the original gap surfaced). Nothing in the tree would NOTICE the
day the emitter grew an encoder for one of them.

## Goal

`test_formal_call_proof_gen.py` gains a `TestExtendOptionsAreDormantIn
EmittedImages` class that compiles that same fixture (`prove=True`) and scans
the executable region word by word, little-endian, for the class's predicate
(`((w >> 21) & 0x7) == 0x1 and ((w >> 24) & 0x1f) == 0x0b` — the same
predicate `_unmodelled_instruction` uses, so the two cannot drift apart
silently): any word found whose `sf` (bit 31) is not 1 or whose `option`
(bits 15-13) is not 3 fails the test with the word, its byte offset and its
option field decoded in the message. 64-bit UXTX words pass — they are rows
86-88 of the step table and the model decodes them.

Do not hard-code "the fixture contains zero words of the class" as the pass
condition: today the assertion is vacuous (the fixture has none at all), which
is the dormant state the original doc measured, and it is also how a pin like
this goes green forever. The pass condition is the option/sf predicate, not
the count.

## Acceptance

- The scan covers `code[:_exec_code_limit(code)]`, word-aligned, little-endian,
  exactly as the existing `test_the_executable_region_stops_before_the_first_
  interned_string` scan in the file does it.
- A word of the class with option ≠ 3 or sf = 0 fails with the word, the
  offset and the decoded option named; option=011, sf=1 words pass.
- The original doc's `def plain(a, b)` dormancy measurement is restated here
  as fact, not re-measured with a second fixture (the emitter shares the same
  encoder paths either way).
- No production change;
  `python3 test_formal_call_proof_gen.py TestRegister31` stays green.

## Done when

File: `test_formal_call_proof_gen.py` (repo root)

Command: `python3 test_formal_call_proof_gen.py TestExtendOptionsAreDormantInEmittedImages`

It runs the new class and passes. The fixture compile is the same one
`TestStepLemmasCoverTheExecutableRegionOnly` already performs in its own
`setUpClass`, so it costs about what that class costs; the scan itself is
instant.

## Where to start

Copy the `setUpClass` of `TestStepLemmasCoverTheExecutableRegionOnly`
(`formal/build.compile_formal_dylib` with `prove=True`, then
`G._exec_code_limit(code)` for the region) and the little-endian word loop
from `test_the_executable_region_stops_before_the_first_interned_string`. All
of the machinery named here lives in `formal/arm64_proof_gen.py`
(`_exec_code_limit` and the `_unmodelled_instruction` arm quoted above). The
class predicate is quoted above; keep it byte-identical to the
`_unmodelled_instruction` arm or the test pins a different instruction than
the one it means to.
