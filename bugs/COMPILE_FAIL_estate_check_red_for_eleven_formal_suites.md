# COMPILE_FAIL_estate_check_red_for_eleven_formal_suites: `test_suite.py`'s estate check was red for eleven files, and is fifteen now

Not a compiler bug and not a codegen gap: a **registration** gap, and the
mechanism for closing it is already in the file. Recorded because
`test_suite.py` is in the everyday regression set and it is red for a reason
that has nothing to do with whatever you just changed, which is the most
expensive kind of red to read.

## Status, after the merge

**The fifteen are now declared; the gap is closed by an excuse, not by a
registration.** `test_suite.py`'s `UNREGISTERED` gained fifteen entries, one per
file, all sharing `_FORMAL_SUITE_REASON` — so `python3 test_suite.py` is
`273 passed, 0 failed` on the merged tree where it was `200 passed, 1 failed`.

The count grew from eleven to fifteen while the doc sat, because four more
per-construct suites landed from other branches (`test_formal_cross_module.py`,
`test_formal_eval_eq_mojo_bridge.py`, `test_formal_platform.py`,
`test_formal_specialized_method_call.py`, `test_formal_trait_module.py`,
`test_formal_type_application.py`, `test_formal_recursion_contract.py` among
them). That is the shape of the problem and the reason a hand-kept excuse list
is the wrong instrument: the inventory is the set of `test_*.py` on disk, so
every new suite is a new obligation and the list has to be edited by whoever
adds the file.

**What is still open is the registration itself**, and it is deliberately not
done here. Each of these is a `cmd` step that builds and runs N programs on two
architectures; a `formal` bucket entry for the group is a `cmd` with a memclass
and a timeout, and the honest version of that is one `Fanout` per suite over its
programs, which is what makes it a real change to `tools/suite.py` rather than a
line in a dict. That is `construct:estate-registration`'s row and it needs the
integration gate to measure; an excuse that says WHY is what the check accepts,
and that is now what it has.

## What it says

```
$ python3 test_suite.py
Results: 200 passed, 1 failed
  - the estate: every test file is run by something, or says why not:
    not run by any registered spec and not in UNREGISTERED:
    test_formal_argparse.py, test_formal_frame_len.py,
    test_formal_hashlib.py, test_formal_module_attr.py,
    test_formal_os.py, test_formal_os_backing.py, test_formal_sys.py,
    test_formal_time.py, test_formal_toplevel.py,
    test_llm/test_llm.py, test_struct_formal.py
```

Measured on `53f89ae7` (master) as well as on a tree carrying only this change,
so it is not caused by anything recent.

## Why it is a real gap rather than noise

`UNREGISTERED` in `test_suite.py:2029` is the file's own answer to "this test is
deliberately not in the gate": a dict from a `test_*.py` to **a sentence saying
why**. The estate check accepts either half — a registered spec or a sentence —
and these eleven have neither. Eleven suites that build and execute real
Mach-O images (`test_formal_os.py`, `test_struct_formal.py`,
`test_formal_frame_len.py`, …) are therefore invisible to every gate, to the
tally, and to the coverage number, and nothing in the tree says that is a
decision.

That is the failure mode `bugs/FORMAL_frame_receiver_handoff.md` §7 records from
the other direction: `coro` sat in the gate naming `mojo_*` runtime files after
they were renamed to `fire_*`, all twenty of its cases had been failing to
compile, and the suite had been reporting 0/20 the whole time. Here nothing fails
at all, which is quieter and the same class.

## The next step

One dict entry per file, each with a sentence. There is no analysis to do and no
risk: `UNREGISTERED` entries are checked for being non-empty strings
(`test_suite.py:2144`), and an entry changes no test's behaviour. A reasonable
sentence for most of them is the one used for
`test_formal_returned_frame.py` in `FORMAL_returned_frame_caller_owned_block.md`:
they build and execute images on both architectures and compare against CPython,
so a gate that ran them all would be minutes per job — which is a reason to run
them by hand and say so, not a reason to leave them undeclared.

**Owner: `construct:estate-registration`**, which holds `tools/suite.py`. Not
filed as a duplicate of that work; this is the measurement the entry needs.
