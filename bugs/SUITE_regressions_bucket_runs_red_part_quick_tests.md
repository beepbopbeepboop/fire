# `reg-codegen-erased-container-values` runs red part probes, so the regressions bucket is red

**Status:** OPEN (measured 2026-11-13).

## What I ran

The job's exact argv, from `tools/suite.py:4228`:

    python3 test_codegen_erased_container_values.py

## What I saw

Exit 1. The bare invocation runs **every** `test_*` in the file, and that file
is a per-part harness whose red tests are the Done-when gates of still-open
bugs:

    AssertionError: annotation -> (got, want):
    {'Scalar[Float32]': ('int64_t', 'float'),
     'Scalar[DType.float32]': ('int64_t', 'float'),
     'Scalar[Float64]': ('int64_t', 'double'),
     'Scalar[DType.float64]': ('int64_t', 'double')}

from `test_part5_scalar_annotation_resolves_to_scalar_ctype`, the gate of
`bugs/mid/CODEGEN_simd_and_array_values_erase_to_int64-part5.md` (open; its
attempts were reverted twice, see that doc's Status). The same bare run also
now fails the two part-4 replan gates
(`test_p4_alias_simd_param_return_keep_ctype`,
`test_p4_comptime_dtype_keeps_ctype`), which are red by construction until
their parts land.

So the job is red on master **before** the part-4 replan: part 5 alone fails
it. A "per-bug regression pin" that is red cannot pin anything, and the
suite's own rule (`CLAUDE.md`, "Known-failing tests: recorded, not hidden")
says a registered red is either fixed or declared with `expect=`/`disabled=`,
never silently rolled into a green-looking bucket.

## What I expected

`regressions` is not in `check`, but it is a bucket and is expected to run
green; the file's *landed* parts (`part1`, `part2`, `part3`, `part4`,
`part4_part1`) do run green, and its own docstring says a `test_partN_*` is
red until part N lands.

## Exact next step

Do not skip the red tests (that would hide the open parts). Separate the
harness from the pin: either

- register the job with a prefix that names the landed parts only — e.g.
  `python3 test_codegen_erased_container_values.py part1` cannot cover them
  all, so prefer a second file that contains just the green regression pins,
  and leave this file as the per-part red/green harness; or
- if the suite wants the whole harness registered, give it `expect='<why>'`
  with a count of the open part tests and drop the marker as each part lands.

The first is the production-quality split: a red Done-when probe belongs to
its bug doc's command, not to a green regression pin.
