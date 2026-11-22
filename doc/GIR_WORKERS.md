# Driving the GIR plan with Sonnet and Haiku workers

`doc/GIR.md` is WHAT to build. This file is HOW the remaining stages get built by
worker agents (Haiku and Sonnet), with one orchestrator (Opus) doing design,
review and landing. Read `doc/GIR.md` first.

## 1. Where the plan stands (measured 2026-11-21)

| stage | state | what is left |
|---|---|---|
| 0, 1, 2a, 3a, 3b, 5a | landed | — |
| 2b builder | landed 2026-11-21: `mojo/ir/build.py`; `gen._emit( text` 0, `build.raw(` 1 | the 41 cast expressions become `gen._cast`; `_emit_cf` taking an `Instr` for `br`/`ret` |
| 3c `Instr` body | landed 2026-11-21: `gen.body_lines` holds `Instr` | — |
| 4 Type objects | predicates landed (`is_cstr`, `is_list`, `is_bool`, `is_double`, `is_word`, `ends_in_star`, `is_int_word`) | 294 `in (..'int64_t'..)` tuples, 65 `== 'int64_t'`, 75 `== 'char *'`, 37 `endswith(' *')`, 32 `== 'MojoList *'`, 11 `== '_Bool'`, 10 `== 'double'`; then `var_types` holding `Type` |
| 5b ValueInfo | steps 1-3 landed (`WordFacts`, `gen._word_*`) | step 4: one record per temp, `Int / Erased / DynWord / Box` |
| 5c optional values | slices landed (param `= None`, `dict.get`, all-None locals) | needs the owner's None decision (§6); then the slices in `doc/GIR.md` 5c "Next" |
| 6 shape | loops 16+7 converted; 61 arms and 18+ passes extracted | cursor loops; 29 nested functions with captured locals; passes that bind a name |
| 7 printers | not started | needs 2b/3c |

Work docs for each open stage: `bugs/GIR_*.md`.

## 2. The two oracles every worker uses

A worker is only as good as the check it runs. Two checks, and a worker never
reports success without them.

1. **Byte-identical C** (behaviour-preserving work: codemods, extractions,
   builder migration). Hash the generated C of `tools/pydiff_corpus` at the base
   commit and on the worker's tree; every hash must match. Today this is the
   scratch script used on 2026-11-20/21; step W0.1 below turns it into
   `tools/c_oracle.py`, which caches the base hashes per commit so a worker runs
   only its own side.
2. **CPython agreement** (behaviour-changing work: stage 5c, bug fixes).
   `python3 tools/pydiff.py <repro>` prints `OK`, and `python3
   test_pydiff_ratchet.py` keeps every listed program OK.

Plus the cheap gates every change runs: `python3 test_gimple_lint.py`,
`python3 test_type_string_ratchet.py`, `python3 tools/dangling_doc_refs.py
--ratchet`, and `python3 -c "import ast; ..."` over every touched file (a
regex codemod once turned `x not in (...)` into `x is_int_word(not)`).

**The blind spot.** Both oracles run the Python reference compiler. Neither can
see a self-host failure: stage 5b steps 1-3 passed both and still broke
`make bootstrap` (the self-hosted compile stubbed every `WordFacts` method).
A per-module `python3 fire.py --dump <module>.py` does NOT see it either
(measured 2026-11-21 at `ef53815a1`: 0 stubs in `loops_shared.ci`, where the
closure had ten). Only the whole-closure dump does, so the self-host check is

    python3 tools/c_oracle.py check --base <sha> --closure

which runs `fire.py --dump-full fire.py` (what `bootstrap-stage1-transitive`
runs) for both sides and fails on any NEW weak stub. It costs 5-8 minutes and
about 6 GB, so the orchestrator runs it once per wave on the merged tree, not
each worker. Any change that adds a module, a class, or a method called across
modules gets it. The full check is still `make bootstrap` (owner-run; see §6).

## 3. Who does what

| role | model | does | never does |
|---|---|---|---|
| orchestrator | Opus | designs each stage's interface, writes packets, reviews diffs, merges and lands, runs the per-wave gates | hand a design decision to a worker |
| mechanical worker | Haiku | one packet: a codemod or a hand rewrite of up to ~30 sites in ONE file, verified byte-identical | change generated C, raise a ratchet baseline, edit `mojo/middle/types.py` or `gimple_codegen.py`'s class body |
| slice worker | Sonnet | one behaviour slice with a CPython repro (a 5c slice, a pydiff cluster, a stage-6 extraction that needs typed parameters) | land, change representation decisions, touch more than the slice names |

Rules for every packet:

- **One packet, one file, one commit.** Packets in the same wave never share a
  file, so they merge without conflicts. Shared definitions (a new
  `TypeLattice` predicate, a new `GimpleGen._word_*` wrapper, a builder
  function) are added by the orchestrator BEFORE the wave starts.
- **Stop on a surprise.** If the oracle shows any difference in a
  byte-identical packet, the worker reverts the site that caused it, lists it
  in its report, and moves on. It does not "fix" the difference.
- **Report in a fixed shape**: files touched, sites changed, sites skipped
  (with the reason), oracle result, gate results.
- Workers run in their own git worktree (`isolation: "worktree"`), never in
  the main checkout, and do not run `make bootstrap`, `make gate` or the full
  runner.

## 4. Waves

Each wave is: orchestrator prep, then up to six workers in parallel, then one
merge and one gate run. A wave lands before the next one starts.

### W0 — tooling and decisions (orchestrator, before any worker)

Status 2026-11-21: items 1, 2 and 4 landed. `tools/c_oracle.py` (corpus hashing takes about 4 s for 285
programs with `-j 6`, so every worker can afford it); nine tuple predicates in `TypeLattice` and the tuple
table in `tools/type_string_codemod.py` (294 -> 115 tuple tests, C byte-identical on 285 programs); the
ratchet no longer counts `mojo/middle/types.py`, where the predicates are defined; eight W1 packets
(`bugs/GIR_W1_*.md`, 322 sites). Item 3 (the None decision) is the owner's.


1. `tools/c_oracle.py`: `--base <commit>` hashes `tools/pydiff_corpus` (and
   the stub count of a fixed list of compiler modules) at that commit in a
   scratch worktree and caches the result under `build/c_oracle/<sha>.json`;
   with no flag it hashes the working tree and prints every program whose C
   differs. `--closure` adds the whole-closure stub check.
2. Extend `tools/type_string_codemod.py` with a tuple table
   (`('int', 'int64_t', '_Bool')` -> `is_int_word_or_bool`, ...) and add those
   predicates to `TypeLattice`, each with exactly the tuple's membership.
3. Get the owner's decision on the None representation (§6).
4. Write the packet docs for W1 (`bugs/GIR_W1_*.md`, easy class, one per file).

### W1 — stage 4 tail (Haiku x up to 6)

The 322 type-string tests the codemod cannot match (a left side it does not
accept, or a tuple with no predicate), in eight packets that never share a
file: `bugs/GIR_W1_{cpp_core,exprtypes,emit_loops,emit_calls,emit_exprs,
emit_stmts,module_gen,emit_methods}.md`. `gimple_codegen.py` (6 sites) stays
with the orchestrator. Acceptance: oracle byte-identical, the file's counts
fall; the orchestrator lowers the baselines at merge and runs the closure check
once on the merged tree.

### W2 — stage 2b builder (LANDED 2026-11-21, not as a wave)

Status: landed in two rounds by one worker instead of six packets; every
`gen._emit(` site is gone and `build.raw` is down to its adapter. What is
left of the stage (the 41 cast expressions, `_emit_cf` taking an `Instr` for
`br`/`ret`) is in `doc/GIR.md`'s stage 2b paragraph. The plan as written:

1. Opus: `mojo/ir/build.py` per `doc/GIR.md` 2b, self-hostable (rule 2), each
   function emitting exactly the text `gen._emit` emits today for that shape,
   so migrating a site is byte-identical. Pin any cross-module method it adds
   in `_SELFHOST_SIGS` and run the stub count.
2. Haiku packets: the 41 text casts (`_new_val(T, f"(T2){x}")` ->
   `gen._cast`), then the 270 `gen._emit(` sites grouped by statement shape and
   by file. A shape whose builder is NOT text-identical (for example `_copy`,
   which also carries value facts) is excluded from the packet.

### W3 — stage 5c slices (Sonnet x up to 4, after the §6 decision)

One packet per slice in `doc/GIR.md` 5c "Next": (1) widen the local-int proof
to arithmetic on proven ints, `len(..)` and comparisons; (2) a tagged word
stored into and read back from a list/tuple/dict slot; (3) `dict.get` on the
double/str domains; (4) a `None` argument to an unannotated parameter not
declared `= None`. Each packet starts from a failing program in
`tools/pydiff_corpus` (the 32 None-related WRONG programs are the pool), ends
with it in `tools/pydiff_ok.txt` and a `test_gimple_runner.py` case. Generated
C changes by design: the orchestrator reviews the diff per function.

### W4 — stage 6 remainder (Haiku for moves, Sonnet for typed lifts)

`tools/extract_arm.py --list` / `--phase` moves are Haiku packets (byte-identical).
The 29 nested functions that capture a local of `gen_module_impl` need a typed
parameter per captured local: Sonnet packets, one function each.

### W5 — stage 5b step 4, 3c, 4 (Type objects), 7 (Opus)

Single-author changes, each landed alone with its own diff review: the
`ValueInfo` record (allowed to change C; the ~1,200 box/repr calls measured on
2026-11-14 are reviewed, not accepted blind); `body_lines` holding `Instr`;
`var_types` holding `Type`; the C++ printer over GIR. After each interface
lands, its migration is split into Haiku packets as in W1/W2.

## 5. Running a wave (orchestrator checklist)

1. `git fetch origin && git merge origin/master`; record the base sha.
2. `python3 tools/c_oracle.py --base <sha>` (once).
3. Add the shared definitions the wave needs; commit them; this is the base.
4. Launch the workers: `Agent(model="haiku"|"sonnet", isolation="worktree",
   prompt=<packet doc path + the rules in §3 + the oracle command>)`. At most
   six at a time (the oracle compiles 285 programs per run).
5. As each returns: read its report and its diff, reject anything that
   changed C in a byte-identical packet or touched a file outside the packet.
6. Merge the accepted worktrees in order; rerun the oracle and the cheap
   gates ONCE on the merged tree; lower the ratchet baselines; land with the
   usual routine. Update the stage's status in `doc/GIR.md` and delete or
   update its `bugs/GIR_*.md`.
7. Per stage, not per wave: `test_gimple.py`, `test_pydiff_ratchet.py`,
   `tools/suite.py stdlib-syntax`, and ask the owner for `make bootstrap`.

The same packet docs also run on the swarm (`tools/swarm.py`): a packet in
`bugs/` is easy class, `bugs/mid/` mid, so the fleet can take them when the
Claude workers are not running.

## 6. What only the owner can unblock

1. **The None representation (stage 5c).** Recommended: a literal `None`
   passed to an unannotated parameter is the shared box `mojo_box_none()`
   (as a `= None` default already is), and `is None` on such a parameter
   reads the box. Today `pick(0)` answers `x is None` True.
   `bugs/GIR_stage5c_none_representation.md` has the repros.
2. **Bootstrap visibility.** `bootstrap-stage1-transitive` and
   `bootstrap-stage2-cc` are disabled by `bugs/gate-bootstrap-stage1-transitive.md`
   and `bugs/gate-bootstrap-stage2-cc.md`. While they are off, self-host breakage
   is only caught by the per-module stub count. Re-enabling them (fixing those
   docs) is the first thing that makes every later wave safe.
3. **Budget.** A wave of six Haiku packets plus one Opus merge is the unit to
   approve; Sonnet slices are fewer and larger.
