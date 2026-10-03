# `test_gimple_runner.py` is RED on the merged bug-batch tree on seven cases, and `silentnoop` TIMES OUT, and nobody has filed either

**Area:** CODEGEN / TESTS. Found 2026-10-02 on `work/bugs4-2` while fixing
five other docs, when narrow runs of `gimplerunner` and `silentnoop` failed and
the failures turned out to have nothing to do with the changes under test. **NOT mine — this is a
measurement artefact of my own run, recorded so the next person does not spend
an hour on it.** Every failure below is reproduced on a pristine
`git archive HEAD~1` copy of the tree (and `silentnoop` on `HEAD~2`), so none
of them is a regression from any commit on my branch.

## What I ran and what it showed

```
$ git archive HEAD~1 | tar -x -C .tmp/base        # a pristine copy, no git metadata
$ cd .tmp/base && python3 test_gimple_runner.py
...
Results: 71 passed, 2 failed          # the whole corpus, on the PRISTINE tree
```

and, over the subset I actually needed:

```
$ python3 sel.py gimple_bytes_membership_in_containers gimple_bytes_dict_key_domain \
                gimple_int_dict_keys_word_lookup_all_operations
FAIL  gimple_char_scan_allocates_nothing_per_character: stdout '4800000\n' (want '4800000\n'), peak RSS 246.7 MB (limit 60)
FAIL  gimple_bytes_membership_in_containers: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
FAIL  gimple_bytes_dict_key_domain: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'
Results: 72 passed, 3 failed
```

**So `gimplerunner` is red on the merged tree, and `make gate` does not say
so** — the job is registered without an `expect=` marker, which means either
the gate is not run on this state or nobody read its screen. Seven distinct
causes, three of which are one-liners:

| case | the failure |
|---|---|
| `gimple_bytes_membership_in_containers`, `gimple_bytes_membership_across_domains`, `gimple_bytes_dict_key_domain`, `gimple_bytes_dict_get_pop_bytes_key` | `AttributeError: 'GimpleGen' object has no attribute '_emit_dict_int_value_store'` |
| `gimple_dict_of_bool_values` | `gcc -fgimple`: `implicit declaration of function 'mojo_mark_dict_bool_values'` |
| `gimple_bool_annotated_struct_field` | every `True`/`False` prints as `1`/`0`, `{'k': True}` as `{'k': 1}`, `[True, False]` as `[1, None]`; plus a `gcc -fgimple` failure |
| `gimple_tuple_dict_key_is_content_keyed` | `lit2` answers `2` where the case expects `1` |
| `gimple_sorted_string_key_runtime_built` | `sorted()` over runtime-built strings gives `['ccc', 'a', 'bb']` |
| `gimple_char_scan_allocates_nothing_per_character` | stdout correct, peak RSS 246.7 MB against a 60 MB limit |

## The three that look like merge accidents rather than open design questions

**1. `_emit_dict_int_value_store` does not exist on `GimpleGen`.**
`mojo/backend_gimple/emit_stmts.py:1513` calls `gen._emit_dict_int_value_store(...)`
and there is no such method anywhere in the tree — the module-level function
is `emit_dict_int_value_store` (`emit_infra.py:4545`), with NO underscore, and
`gimple_codegen.py` has no delegation for it. Every other `emit_*` helper in
that family has one (`_infer_return_type`, `_quick_container_elem`,
`_infer_list_elem_type`, …), so this reads as a delegation that was never
added, not as a design choice. **The fix is one line beside its siblings**, and
it un-reds four cases at once.

**2. `mojo_mark_dict_bool_values` is CALLED but not DECLARED.** The runtime has
`mojo_dict_set_bool` / `mojo_dict_set_bytes_bool` (which REPLACED the
whole-dict `mojo_is_bool_dict` / `mojo_mark_dict_bool_values` pair — see
`test_runtime_header_scan.py`'s `+2/-2, net zero` ledger line), and
`emit_methods.py` / `emit_resolve.py` still emit calls to the removed one. This
is the same class of mistake: a per-SLOT tag replaced a whole-DICT flag and one
call site kept the old spelling.

**3. `gimple_bool_annotated_struct_field` failing in BOTH directions** (wrong
output AND a `gcc -fgimple` failure) is the same shape as the one above seen
through the other caller.

## The rest are real open questions, not accidents

`gimple_tuple_dict_key_is_content_keyed`'s `lit2` row and
`gimple_sorted_string_key_runtime_built` are both in the same
"a container's element type is not recorded" family as
`CODEGEN_dict_content_key_aliases_a_string_key.md` and
`bugs4-5`'s `CODEGEN_sorted_key_of_runtime_built_strings_sorts_by_address.md`
(the latter's claim is `s = sorted(x, key=...)` sorting by address; this case
is `sorted()` with no key at all, printing `['ccc', 'a', 'bb']` — a DIFFERENT
defect from the same family, so it is not covered by that doc).
`gimple_char_scan_allocates_nothing_per_character` is a MEMORY result, and
`bugs4-9` holds `PERF_char_scan_leak_residual_21_bytes_per_char` and
`PERF_char_scan_peak_rss_over_its_ceiling`; whether this case's 246.7 MB is the
same measurement as that doc's ceiling question, I did not check.

## And `silentnoop` TIMES OUT on the same tree, at 900 s against a 1125 s baseline

`tools/suite.py` gives `silentnoop` a 900 s TIMEOUT, and
`test_silent_noop_iter.py` takes **18m45s (1125 s)** on a pristine
`git archive HEAD~2` copy of this tree, measured ALONE and with nothing else
running. So the job is over its own timeout before any of my changes, and under
a parallel suite load (12 jobs, `-j18`) it is worse.

```
$ cd .tmp/base            # git archive HEAD~2, i.e. the merged batch state
$ time python3 test_silent_noop_iter.py
23 passed, 0 failed
real  18m45.547s
```

and on my own tree, alone, at the end of the branch:

```
$ time python3 test_silent_noop_iter.py
23 passed, 0 failed
real  18m42.649s
```

**1125 s vs 1123 s — my changes cost nothing measurable here** (the work is 23
compile-and-run cases and the CPU figures are 4m36s user / 2m20s sys against
5m05s / 2m27s, i.e. it is a WAITING-bound job either way). So the timeout is
purely pre-existing, and 900 s is simply the wrong number for it.

The content passes; only the clock fails, and per CLAUDE.md a hang "is a
failure in its own class" — so this is a real red that the merged batch carries,
in the same shape as the seven `gimplerunner` cases above.

The two next steps for it, both a decision rather than an implementation:
either the TIMEOUT is wrong for a 19-minute job (and should be raised, with the
measured 1125 s recorded at its registration — the same rule the memclass
ledger follows), or the test is doing work it does not need. `23 passed` with
4m36s of user CPU inside 18m45s of wall says it is almost entirely WAITING, not
computing: that is 24% of one core, so the time is in subprocesses (gcc, the
compiled binaries) or in sleep, and which one is the question to answer before
raising anything. **If it is gcc, `checked_run.py`'s content-addressed cache
may simply not be covering this test** — worth checking first, because a cached
replay would take seconds and the measured numbers say it never gets one.

## The exact next step

1. Add the `_emit_dict_int_value_store` delegation to `GimpleGen` beside its
   siblings. Measure: the four `gimple_bytes_*` cases above.
2. Grep the whole tree for `mojo_mark_dict_bool_values` (and for the other
   removed runtime name, `mojo_is_bool_dict`) and delete every call site; the
   replacement is `mojo_dict_set_bool`, which the store lowering already has
   (see `emit_stmts.py`'s `is_python_bool_expr` branch). Measure:
   `gimple_dict_of_bool_values`.
3. `gimple_bool_annotated_struct_field`: read the `gcc -fgimple` error first —
   a compile failure in the same case that also misprints is two problems, and
   fixing the output alone will not make it green.

**NOT measured:** whether these are the gate's real state (I am a light worker
and did not run `make gate`; the baseline above is the honest substitute), and
whether any of them is `expect=`-marked somewhere I did not look — they are not
marked in `tools/suite.py`, since `gimplerunner` runs unmarked and red.
