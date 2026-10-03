# FORMAL_x86_64_a_field_of_a_returned_frame_in_an_argument_position_segfaults: the same field read that computes correctly is handed to a callee as a wild pointer

**Status: OPEN, not fixed, and NOT caused by the `merge:formal12` work that
measured it — it is byte-identical on `master`.** Found 2026-10-03 while merging
`work/formal10-3`, `work/formal12-hostmods-rank` and
`work/formal12-ctor-self-and-singles-a`, running the narrow test files those
merges touched. Thirteen cases of `test_formal_returned_frame.py` are red, all of
them `--backend=x86_64`, and the failure SET is identical on `master` and on the
merged branch (diffed, below), so this is pre-existing and filed rather than
fixed here.

## What I ran

    $ python3 tools/memslot.py --gb 8 --label t -- python3 test_formal_returned_frame.py
    formal returned-frame: PASS=23 FAIL=13          # the merged branch
    $ …the same file in a `git archive master` tree…
    formal returned-frame: PASS=22 FAIL=13          # master, 1 fewer case
    $ diff <master's 13 FAIL names> <merged's 13 FAIL names>   # IDENTICAL

`PASS` is 22 on master and 23 here because `work/formal10-3`'s `687fb363` moved
`refuse_a_specialized_parameter_returned` into this file as
`received_frame_handed_back_through_a_specialized_parameter`; that case passes.
Nothing here made anything worse and nothing here made anything better.

## The thirteen, and what they have in common

Every one is a `--backend=x86_64` failure and every one of the thirteen is a
**differential** case (build, run, compare against CPython), not a refusal case:

    returned_frame_outlives_its_creator                    exit -11 where CPython gives 155
    returned_frame_carries_its_nested_frame                exit -11 where the source gives 94
    returned_frame_nested_calls_two_blocks                 exit 104 where CPython gives 100
    method_on_a_returned_frame                             exit -11 where CPython gives 115
    returned_frame_is_the_object_the_caller_asked_for      exit -11, CPython 0
    two_returned_frames_in_one_function_are_two_blocks     exit -11, CPython 0
    returned_frame_outlives_the_callees_activation         exit -11, CPython 0
    forwarded_through_three_activations                    exit -11, CPython 0
    positional_init_and_copy_constructions_all_land_in_the_block  exit -11, CPython 0
    a_nested_frame_inside_the_returned_block_is_reachable  exit -11, CPython 0
    a_method_can_return_a_frame_it_builds                  exit -11, CPython 0
    the_returned_object_is_then_an_ordinary_receiver       exit -11, CPython 0
    a_function_that_returns_no_frame_is_unchanged          exit -11, CPython 0

`exit -11` is the harness reporting SIGSEGV and `139` is the shell reporting it;
`returned_frame_nested_calls_two_blocks` is the odd one out at `104`, which is a
WRONG ANSWER rather than a crash and may or may not be the same defect.

**Not one arm64 case fails**, and the whole refusal half of the file (thirteen
`refuse_*` cases) passes on both. So this is the x86-64 backend's half of the
returned-frame convention, not a shared modelling gap.

## The reproducer, and the narrowing that makes it a bug doc

`.tmp/rf/a.mojo` — twelve lines, no imports, no host module, one struct:

    struct Point:
        var x: Int
        var y: Int

    def make(a, b):
        var p = Point()
        p.x = a
        p.y = b
        return p

    def main(n):
        var q = make(1, 2)
        printf("x=%d", q.x)
        return 0

    $ python3 tools/memslot.py --gb 8 --label t -- \
        python3 fire.py build --formal --no-prove --backend=x86_64 -o a.x86 a.mojo
    Built: a.x86  [x86_64/macho]
    $ ./a.x86 ; echo $?
    Segmentation fault: 11
    139

    $ … --backend=arm64 -o a.arm a.mojo && ./a.arm ; echo $?
    x=1
    0

What I expected: `x=1` on both, exit 0 on both. What arm64 does: exactly that.

Five variants, each one a fact rather than a guess about which layer is wrong:

| program | x86-64 |
|---|---|
| `a`: returned struct, `printf("%d", q.x)` | **SIGSEGV** |
| `b`: returned struct, never read (`var q = make(1,2); return 0`) | exit 0 — so the construction and the return are fine |
| `e`: returned struct, `return q.x + q.y` | exit 3 — **correct**, so the field READ is fine |
| `i`: struct built IN `main`, `printf("x=%d y=%d", q.x, q.y)` | `x=1 y=2`, exit 0 — **so it is not `printf`, and not variadic** |
| `k`: returned struct, field passed to a plain typed callee `show(v: Int)` | **SIGSEGV** — **so it is not the C runtime** |

`b`, `e` and `i` together are the whole narrowing: the returned-frame
convention's *storage* is right (`b`), its *field read* is right (`e`), and a
struct's field read in an argument position is right (`i`). What is broken is the
**one composition**: a field read through a returned frame, in an ARGUMENT
position. `k` rules out the C runtime and the variadic path — `show` is a Mojo
function in the same unit taking one `Int`.

`g`/`h`/`j` add that it does not matter what the OTHER arguments are — one
returned field alone, one returned field after a literal, one literal after a
returned field: all three SIGSEGV.

## The fault itself

    $ lldb -b -o run -o "bt" ./.tmp/rf/a.x86
    Process stopped
    * thread #1, …, stop reason = EXC_BAD_ACCESS (code=1, address=0x1)
           frame #0: libsystem_c.dylib`__findenv_locked + 86
        ->  0x7ff80a556dc0 <+86>: movb   (%rax,%r14), %r15b

Two things worth recording. **The faulting address is `0x1`**, i.e. a NULL plus a
small displacement — a wild pointer, not an out-of-range frame address, which
says the word reaching the call was never a frame address at all. And
`thread backtrace` prints **exactly one frame**: the frame-pointer chain out of
the generated code does not reach the faulting function, so the generated image
is not walkable either. Neither observation needs the fix to be worth acting on.

## Why nobody has seen this

`test_formal_returned_frame.py` is in `UNREGISTERED` in `test_suite.py`
(line 2928) with `_FORMAL_SUITE_REASON` — "builds and executes images on both
architectures and compares against CPython, so a gate that ran them would be
minutes per job". That reason is the right call for a suite that is GREEN. This
suite is not green, and it is red on one whole architecture, so the registration
that keeps it out of the gate is also what keeps a 13-case SIGSEGV cluster out of
every report. `bugs/COMPILE_FAIL_estate_check_red_for_eleven_formal_suites.md`
already records that the eleven formal per-construct suites are unregistered; it
frames the missing thing as registration, not as a red one, because when it was
written the arithmetic was different.

## Exact next step

1. **Read the x86-64 argument-slot computation for a frame argument whose base
   is a returned frame.** `formal/x86_64_codegen.py`'s argument lowering, next to
   arm64's, is where the two must differ: arm64 computes `q.x + q.y` correctly
   (`e`), so its frame-receiver resolution is right and only the ARGUMENT path
   differs. `formal/model.py`'s `struct_frame_slot` / `struct_frame_slots` and
   the per-parameter contract the returned-frame convention publishes
   (`_export_frame_contract`) are the shared facts; the question is which of them
   the x86-64 call site consults.
2. **The cheapest confirmation is the reproducer, not the suite.** `.tmp/rf/a.mojo`
   is twelve lines and one `fire.py build`; `k.mojo` is the same defect with no C
   runtime in it, so a fix that makes `a` pass and `k` still crash is a fix to
   the variadic path and not to this one.
3. **`returned_frame_nested_calls_two_blocks` exits 104 and is not a crash.**
   Check it against `a` first: if the fix makes `a` exit 0 it may make this one
   print the right number, and if it does not, that is a second defect wearing
   the same program.
4. Then re-run the whole file and expect 36/36. Anything less is a partial fix
   and the file's own thirteen `refuse_*` cases are the guard against a "fix"
   that widens a refusal instead of lowering the argument.
