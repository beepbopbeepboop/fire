# FORMAL_backend_raises_on_a_three_element_unpack: four files make the formal backend RAISE `ValueError: too many values to unpack (expected 2, got 3)`

**Claim** `sweep:7` on `work/formal11-sweep`, found by
`bugs/FORMAL_sweep_work_map_2026-10-02_b7.md` §3.2. **Not diagnosed, not fixed.**
A `backend-crash` is a bug in the compiler, not a coverage finding: it is in no
rate, it is never cached, and it re-runs on every sweep until the cause is gone, so
it will keep costing four builds per arm per sweep until someone looks at it.

## What the run printed

Both arms, `master` at `e7fbe6ef`, and **the same four files with the same message**:

```
BACKEND-CRASH: detect_real_type_errors.py   (the backend raised: ValueError: too many values to unpack (expected 2, got 3))
BACKEND-CRASH: formal/x86_64_codegen.py     (the backend raised: ValueError: too many values to unpack (expected 2, got 3))
BACKEND-CRASH: run_type_system_tests.py     (the backend raised: ValueError: too many values to unpack (expected 2, got 3))
BACKEND-CRASH: test_type_system.py          (the backend raised: ValueError: too many values to unpack (expected 2, got 3))
```

The tool's own summary line for it: *"If a sweep suddenly reports many of these,
another agent is mid-edit in `formal/` and the number is an artefact."* Four at
once, all type-system-shaped, is that shape.

## Why this doc does not name a line

The exception carries a `(expected 2, got 3)` tuple-unpack and nothing else — no
file, no line, no expression — and the tool classifies on the class of the raise,
not on its site. **Naming a line needs the traceback**, which means one build with
`fire.py build --formal --no-prove` run directly. That was not done here: the
sweep that found this was still running when the decision was made, and the
remaining budget went to the map and to
`FORMAL_dylib_module_body_has_no_load_time_entry_point.md`, which is a 16-file row
against this one's 4. **This is the next cheapest thing to measure on this machine
and it is one command:**

```sh
export PATH=/opt/homebrew/bin:$PATH
python3 tools/memslot.py --gb 8 --label crash-bisect -- \
  python3 fire.py build --formal --no-prove --backend=arm64 -o .tmp/crash.bin \
  test_type_system.py
```

`test_type_system.py` is the smallest of the four by name and the one a reader
should start with. The traceback's last frame inside `formal/` is the answer, and
`grep -n "expected 2, got 3"`-shaped unpack sites in `formal/` are the candidate
set: a `(k, v)` unpack of something that is now a 3-tuple, which is the kind of
change a type-name-as-value feature makes.

## What is deliberately NOT concluded

* **Not** attributed to `construct:type-name-as-value-2` (`formal-type-value-2`),
  which is a live claim in the type-system area and is the obvious suspect. A
  suspect is not a diagnosis: attributing a compiler crash to another worker's
  in-flight edit without the traceback is how a doc becomes wrong within the hour,
  and the sweep's own note says this number may be an artefact of exactly that.
* **Not** counted as a coverage regression anywhere. It is in no rate on either arm,
  and both arms' `codegen coverage` numbers are unaffected by it (a crash file is
  excluded from the denominator, which is the tool's own policy and is stated in
  the summary).

## Next step, in order

1. Run the command above and paste the traceback's last `formal/` frame here.
2. If the crash is reproducible on a clean `master`, it is a bug in `formal/`
   independent of any claim, and it should be fixed as one — the fix is a
   three-element unpack written for a two-element shape, which is a wrong answer
   waiting to be a refusal.
3. If it is **not** reproducible on a clean `master`, this doc is a record of a
   transient and the sweep note's advice applies: re-run the sweep after that work
   lands and delete the doc if the four rows are gone.

## Reproducing the measurement

```sh
grep "^BACKEND-CRASH" bugs/sweeps/sweep-arm-7.txt bugs/sweeps/sweep-x86-7.txt
```