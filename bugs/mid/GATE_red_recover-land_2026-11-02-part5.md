# Turn the three bootstrap gate jobs back on once the closure is stub-free (part 5)

Part 5 of 5 of `bugs/hard/GATE_red_recover-land_2026-11-02.md`. Class: easy —
a config change plus one closure-level verification. It is the activation half
of the parent doc; parts 1–4 are the code that has to be true first.

## State today (2026-11-13)

`python3 tools/control.py gate list` shows the three jobs OFF under TWO
entries:

    OFF  ^(…|bootstrap-stage1-transitive|…)…$   …  doc <the mid GATE doc, deleted; see GATE_off_entry_doc_missing.md>
    OFF  ^(bootstrap\-stage1\-transitive|bootstrap\-stage2\-dumps|bootstrap\-stage3\-dumps)$
         …  doc bugs/hard/GATE_red_recover-land_2026-11-02.md

The first entry's doc no longer exists on disk (`git log` shows it deleted in
`d44f44787`), so that entry can never be discharged by the "remove this report
in the same commit" rule. It matches 23 jobs, including `bootstrap-stage1-transitive`,
`mojoc`, `gimple`, `linkmode` and `selfhost`. That orphan is filed separately
as `bugs/mid/GATE_off_entry_doc_missing.md`; this part must not depend on it being
fixed first, but it must not leave `bootstrap-stage1-transitive` matched by it
either — narrow that entry (drop the bootstrap name) or delete the entry as
part of the same commit, and say which in the commit message.

`mojoc` is NOT in this doc's entry any more (the parent doc's 2026-11-03 status
said it had been re-enabled here); it is still held OFF by the orphaned first
entry, so it is the orphan doc's to re-enable, not this part's.

## Goal

With parts 1–4 landed:

1. `python3 tools/suite.py bootstrap-stage1-transitive` passes: the Python
   `--dump-full` closure of `fire.py` contains no
   `unavailable in compiled mode` and no `# ERROR: compiling imported module`.
2. The chain that job unblocks passes:
   `bootstrap-stage2-cc`, `bootstrap-stage2-dumps`,
   `bootstrap-stage2-transitive`, `bootstrap-stage3-dumps`,
   `bootstrap-stage3-transitive`.
3. `tools/gates.json` no longer turns off
   `bootstrap-stage1-transitive`, `bootstrap-stage2-dumps` or
   `bootstrap-stage3-dumps` by any entry, and the orphaned first entry no
   longer matches `bootstrap-stage1-transitive`.
4. The umbrella doc `bugs/hard/GATE_red_recover-land_2026-11-02.md` is deleted
   in the same commit, and `python3 tools/dangling_doc_refs.py --ratchet`
   passes after fixing anything it names.

If the closure dump still names a weak stub that parts 1–4 do not explain, fix
it here only if it is a one-symbol registration of the shape parts 1–2 already
handle; otherwise file it as a new `bugs/` doc with a minimal probe and leave
this part's jobs OFF, rather than turning the gate back on around a known stub.

## Acceptance

- Steps 1–3 above, each observed in `build/suite.log` (a PASS line per job),
  not inferred from a partial run.
- A fresh landing gate (`python3 tools/control.py gate list`) shows no OFF
  entry matching any of the three names.
- The umbrella doc is gone; its parts remain.
- No job was made green by an `expect=` marker, a skip, or a narrowed reject
  regex — the closure must genuinely be complete (the `reject` regexes in
  `tools/suite.py` stay as they are).

## Done when

File: `tools/suite.py` (the registry entry for the job; the job itself is the
test).

Command: `python3 tools/suite.py bootstrap-stage1-transitive`

It runs the one `tiny` closure job (measured 1.1-1.4 GB in the registry) whose
`reject=CLOSURE_INCOMPLETE` is exactly the parent doc's failure. Red today:
the dump contains the weak stubs / the `exprtypes` `# ERROR`. The rest of the
chain is the same command with each job name in turn.

## Where to start

- `tools/suite.py:2600-2690` — the five job registrations and their `deps`.
- `python3 tools/control.py gate off/on` — the only writer of
  `tools/gates.json`; do not hand-edit the JSON, and put the doc's name in the
  entry while it is still OFF.
- `bootstrap-stage1-transitive` needs `bootstrap-stage1-dumps` first (it is a
  dependency, run automatically by `suite.py`), and `stage2-cc` builds
  `stage2/mojo` from `stage1/fire.ci`.
