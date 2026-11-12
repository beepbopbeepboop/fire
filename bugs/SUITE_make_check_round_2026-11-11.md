# Round 2026-11-11: `make check` reds fixed on master

**Status:** Historical round report, closed as a tracker. The six jobs below
were fixed on master during this round (see commits). The "still open" list in
the original snapshot is no longer a live work queue in this doc: remaining
issues are tracked by their own bug docs/markers or are green on this tree.

## Fixed in this round

| job | commit | what was wrong |
|---|---|---|
| `no-new-casts` | `bfe9096f2` | `_lower_subscript` spelled the same bytes-slot coercion twice; one `_list_slot_bytes` helper serves both. |
| `formal-bracketed-method-field-set` | `d05a3c8c7` | Six cases declared `out self` with a return type; rewritten to `mut self`. |
| `doc-refs-stale-verdicts` | `99eb78995` | `bugs/hard/README.md` index brought in sync with docs on disk. |
| `gimple` | `1851f24bf` | `Dict[Int, Int]` subscript stringified the key; boxed read now uses `_kw` path preserving slot kind. |
| `runtimediff` | `1851f24bf` | Container stored under dict kind 0 rendered as its address; repr now dispatches by container registry. |
| `suite-self-test` (1 row) | `07131682d` | `emit_stmts` module-level import cycle fixed by using the `ggc` alias. |

## Verified at the time

- `test_gimple.py` 437 passed / 0 failed
- `test_runtime_diff.py` 69/0
- `test_ptr_registry.py` 28/28
- `test_runtime_header_scan.py` 53/53
- `test_dangling_doc_refs.py` 7/7
- `tools/dangling_doc_refs.py --ratchet` green

## Master merges during the round

1. `e8e703447` / `d97ad68c7` — 22 commits merged; `bugs/hard/README.md` conflict resolved with this tree's version.
2. `7f75c96cb` / `73e8057ae` — 83 commits merged; follow-up reds fixed in `ae3f0228a`, `3070c1081`, `7c06a4ffe`.
3. `ea14049db` / `2e3c98267` — 27 commits merged; conflict resolved taking master's wording; ratchet/cast follow-ups in `e638c9447`.

## Disposition of jobs listed as "still open" in the 2026-11-11 snapshot

- Green / passing on this tree now (per `tools/suite.py --list` / recent runs): `gimplegenerators`, `silentnoop`, `modcache`, `bootstrap-stage1-dumps`, `suite-self-test`, `doc-refs`.
- Tracked as expected/known failures in the suite: `gimplerunner` (`bugs/hard/SUITE_gimplerunner_21_failing.md`, expect marker), `async-void-return` (codegen gap, expect marker in `coroutine`).
- Tracked in separate bug docs/claims (not owned by this round doc): `formal-host-import-shapes` (`bugs/gate-formal-host-import-shapes.md`), `formal-link-accounting`.
- Not reproduced in the round and no longer represented here as open without owner: investigate under their respective jobs/docs if they regress.

## Pre-existing, not from this round

Fixtures that declare `out self` on a non-constructor (Modular refuses them)
are fixed and now swept by `test_out_param_return_type_diagnostic.py`'s
`FixtureCorpusValidity`; the remaining invalid-Mojo fixture content is a
separate campaign (the fixture-validity bug beyond the `out` shapes; its harness half is closed, see `test_out_param_return_type_diagnostic.py`'s `ParityBuildFailureIsClassifiedByLayer`).

## Done when

- This doc contains a `## Done when` section and no longer presents the stale
  2026-11-11 "still open" list as the current work queue.
- `python3 tools/dangling_doc_refs.py --ratchet` exits 0.
- Verified: `python3 tools/dangling_doc_refs.py --ratchet` (green, 2026-11-11).
