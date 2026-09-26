# Everything this Makefile *tests* lives in tools/suite.py: the buckets, the
# per-test drivers, the memory ceilings, the dependency order, and the single
# pass/fail tally. What is left here is (a) one-line targets so the old names
# still work, (b) the real build rules, and (c) the A/B sweep, whose
# parallelism genuinely is GNU Make's job server.
#
# `python3 tools/suite.py --list` prints the whole registry: which bucket each
# test is in, which driver runs it, which memory ceiling applies, and what it
# depends on. `python3 tools/suite.py --dry-run <bucket>` prints the plan.

.PHONY: run demo check gate check-gimple check-runner check-gimple-runner \
        check-modcache check-selfhost check-runtimediff check-linkmode \
        check-no-new-casts check-coro check-stdlib check-stdlib-interp \
        check-stdlib-jit check-ab-native check-native-dumpfull \
        check-formal check-formal-dylib check-formal-run check-formal-x86 \
        check-formal-x86-model check-formal-x86-endtoend check-formal-imports \
        check-formal-sweep check-suite check-list check-plan \
        wholeprogram-help \
        clean clean-bootstrap stdlib bootstrap preflight suite-help \
        stage1 stage2 stage3 verify validate-all dump-all-stage1 \
        dump-all-stage2 dump-all-stage3

# ── Paths ────────────────────────────────────────────────────────────────────
RUNTIME_SRC  = runtime/fire_runtime.c
RUNTIME_HDR  = runtime/fire_runtime.h
# A3 stack-switch coroutine runtime (doc/COROUTINE.html §5.5: the default
# generator/async backend now, gimple_gen_coro.py) — needed by stage2/mojo's
# own hardcoded link recipe below whenever the self-hosted compiler's OWN
# source (fire_compiler.py/myinterpreter.py/...) contains a generator/async
# function, exactly like driver.py's compile_program / build_stdlib_dylib.py
# already needed the identical fix (both `-undefined dynamic_lookup`-style
# paths only surface a missing symbol as a runtime dyld crash, never a link
# error — this one DOES fail at link time since stage2/mojo's link is a
# plain static executable, no dynamic lookup fallback). Plain C, no
# -fgimple needed (mirrors fire_runtime.c's own presence in this same list
# — gcc's -fgimple only forces the strict frontend for a `.ci`-shaped
# translation unit, not for ordinary C sources compiled alongside it).
CORO_ARCH_SRC = $(shell test "$$(uname -m)" = "arm64" -o "$$(uname -m)" = "aarch64" \
                  && echo runtime/fire_coro_ctx_aarch64.S || echo runtime/fire_coro_ctx_generic.c)
CORO_RUNTIME_SRC = runtime/fire_coro.c runtime/fire_coro_gen.c runtime/fire_async_sched.c $(CORO_ARCH_SRC)
# The canonical source that all three stages compile
MOJO_MAIN    = fire.py

GCC_MP15     = /opt/local/bin/gcc-mp-15
BOOTSTRAP_CC = $(shell command -v gcc-15 >/dev/null 2>&1 && echo gcc-15 || (test -x $(GCC_MP15) && echo $(GCC_MP15)) || echo gcc)
BOOTSTRAP_OPT ?= -O0
MOJO_OPT ?= -O2 -g0

# 512MB main-thread stack (default 8MB). The self-hosted compiler's regex
# engine and generic AST walkers are deeply CPS-recursive — a re.sub/findall
# over a 200KB module source recurses per input position and blows the
# default stack (only reached on the MOJO_NO_SHIM=1 --dump-full path).
BIG_STACK_LDFLAGS = $(shell test "$$(uname -s)" = "Darwin" && echo "-Wl,-stack_size,0x20000000" || echo "-Wl,-z,stacksize=536870912")

# MacPorts GCC can't find SDK headers without this
SDKROOT := $(shell xcrun --show-sdk-path 2>/dev/null)
export SDKROOT

# ── Driving the test runner ─────────────────────────────────────────────────
# The runner is parallel by default, at the machine's CPU count, and `-j1`
# makes it strictly serial with every job's output streamed live:
#
#     make check                # -j ncpu
#     gmake -j8 check           # -j8, propagated
#     gmake -j1 check           # one at a time, slow, output live
#     make check J=4            # 4 at a time, whichever make you are using
#
# `J` is a variable as well as a `make -jN`, because the two makes on this
# machine disagree: Apple ships GNU Make 3.81, whose MAKEFLAGS holds a bare
# `-j` with no count, so `make -j1` and `make -j8` are indistinguishable from
# inside a recipe — and -j1 is exactly the one that has to be honoured. The
# Homebrew `make` 4.4.1 (as `gmake`) does record the count, so with it the
# `-jN` above works directly. The runner's own flag is the authority either
# way: `python3 tools/suite.py -j1 check` does the same thing with no Make
# involved.
#
# MEMLIMIT_GB still means what its documentation always meant — an ABSOLUTE
# ceiling in GB for every memory-capped job, or 0 for none of them:
#
#     make check MEMLIMIT_GB=96
#     make gate  MEMLIMIT_GB=0     # no ceiling anywhere; watch the machine
#
# The per-test defaults (which job gets which ceiling, and why) are the
# MEMCLASS table in tools/suite.py, not here — the ceilings are a fact about
# the workloads, and a fact that lives in two places is a fact that rots.
ifneq ($(strip $(MEMLIMIT_GB)),)
export MEMLIMIT_GB
endif
# `make -jN` → J=N, where the make in use records a count (GNU Make 4.x).
MAKE_JOBS := $(patsubst -j%,%,$(filter -j%,$(MAKEFLAGS)))
J         ?= $(strip $(MAKE_JOBS))
SUITE      = python3 tools/suite.py
SUITE_J    = $(if $(strip $(J)),-j$(J),)

# One test, or one bucket, by name. `$(call suite,check-gimple)` is the whole
# recipe of every check-* target, which is the point: the recipe used to be a
# copy of the test's input-file list, and those copies drifted.
define suite
	@$(SUITE) $(SUITE_J) $(1)
endef

# ── Dev targets ──────────────────────────────────────────────────────────────
demo:
	echo "3 + 42 + 0xFF" | python3 fire_compiler.py

suite-help:
	@$(SUITE) --list

# Kept because bugs/CODEGEN_bootstrap_resource_blowup.md points here for the
# memory-containment story. The numbers now live in one place — MEMCLASS in
# tools/suite.py, printed by `make check-list` — instead of in a macro here
# that only one target used.
wholeprogram-help:
	@echo "A WHOLE-PROGRAM self-compile (one process, whole transitive closure)"
	@echo "is bounded by a memory ceiling applied by tools/memcap.py, which"
	@echo "SIGKILLs the process tree on breach and exits 125. A ceiling rather"
	@echo "than an opt-in, because macOS will not reliably pick what to kill"
	@echo "when memory runs out, and ulimit gives no usable cap — the kill has"
	@echo "to be aimed by us at a process we own."
	@echo ""
	@echo "  which ceiling, and why:   make check-list    (MEMCLASS)"
	@echo "  which jobs are capped:    make check-list    (the mem= column)"
	@echo ""
	@echo "      make check MEMLIMIT_GB=96              # raise every ceiling"
	@echo "      make gate  MEMLIMIT_GB=0               # no cap; watch it"
	@echo ""
	@echo "The program/stage classes are also EXCLUSIVE: the runner starts"
	@echo "nothing else while one runs, so a 55 GB job is safe to leave"
	@echo "unattended on a 128 GB box."
	@echo ""
	@echo "Bounded per-file alternative, safe to run unattended:"
	@echo "    gmake -j20 aside bside && make compare-a-b"

check-plan:
	@$(SUITE) --dry-run $(or $(BUCKET),check)

check-list:
	@$(SUITE) --list

# The everyday green gate: the GIMPLE unit suite, the execution runner, the
# module-cache end-to-end stages, the self-host compile guard, interpreter-vs-
# JIT runtime parity, the link-mode compile guard (the real
# `driver.compile_program` pipeline `mojo.py build` actually uses — distinct
# from every other check here, which drives codegen through the single-
# translation-unit `do_imports=False` inline path; a link-mode-only bug is
# invisible to all of them, see bugs/COMPILE_FAIL_asyncio_futures.md and the
# two bugs/CODEGEN_link_mode_*.md docs, all found this way), and the
# no-new-container-casts allowlist. All parallel, none memory-hungry, minutes.
#
# `make gate` is the wider one: this plus the coro runtime, both stdlib build
# gates, the self-hosted binary's own codegen, and the whole 3-stage
# bootstrap. `native-dumpfull` and the bootstrap stages touch tens of GB, so
# the runner holds the machine still for them rather than trusting the reader
# to know not to run two at once.
check:
	@$(SUITE) $(SUITE_J) check

gate:
	@$(SUITE) $(SUITE_J) gate

# Every individual check, still one `make` target each, now a one-line recipe.
# (The old recipes each carried their own copy of the list of files that
# affects the outcome; that list is now one entry per test in the runner's
# registry, and it is what feeds checked_run.py's cache key.)
check-gimple:         ; $(call suite,gimple)
check-runner:         ; $(call suite,runner)
check-modcache:       ; $(call suite,modcache)
check-selfhost:       ; $(call suite,selfhost)
check-runtimediff:    ; $(call suite,runtimediff)
check-linkmode:       ; $(call suite,linkmode)
check-no-new-casts:   ; $(call suite,no-new-casts)
check-coro:           ; $(call suite,coro)
# The two self-hosted-binary checks name `mojoc` too: the old recipes had it
# as a Make prerequisite, and dropping it would have turned `make
# check-native-dumpfull` into "dependency not selected" instead of a build.
# select() de-duplicates, so it is still built once.
check-ab-native:      ; $(call suite,mojoc ab-native)
check-native-dumpfull:; $(call suite,mojoc native-dumpfull)
check-stdlib:         ; $(call suite,stdlib-corpus)
check-formal:         ; $(call suite,formal)
check-formal-run:     ; $(call suite,formal-run)
check-formal-dylib:   ; $(call suite,formal-dylib)
check-formal-imports: ; $(call suite,formal-imports)
check-formal-sweep:   ; $(call suite,formal-sweep)
check-formal-x86:     ; $(call suite,formal-x86)
check-formal-x86-model: ; $(call suite,formal-x86-model)
check-formal-x86-endtoend: ; $(call suite,formal-x86-endtoend)

# `check-gimple-runner` was a stray alias for test_gimple_runner.py, which no
# other target referenced and no gate ran; it stays, running what it always ran.
check-gimple-runner:
	python3 test_gimple_runner.py

# The two halves of check-stdlib, kept for the people who use them.
check-stdlib-interp:
	python3 test_stdlib.py --mode interp
check-stdlib-jit:
	python3 test_stdlib.py --mode jit

# Parse and validate the entire stdlib (all .mojo files) — the runner's
# `stdlib-syntax`, which forwards -j so this is the same parallel sweep.
stdlib:
	@$(SUITE) $(SUITE_J) stdlib-syntax

preflight:            ; $(call suite,preflight)

# The test runner's own test. Cheap (synthetic specs, no toolchain), and worth
# running first whenever tools/suite.py itself is what changed: it is the thing
# every other check in this repo is now dispatched through.
check-suite:          ; $(call suite,suite-self-test)

# ── Bootstrap ────────────────────────────────────────────────────────────────
#
# Three-stage self-hosting verification with transitive-closure compilation:
#
#  Stage 1  Python fire.py --dump-full fire.py (single pass, all imports inline)
#             → stage1/fire.ci  (clean, no deduplication needed)
#  stage2/mojo  GCC -fgimple compiles stage1/fire.ci + runtime → compiled binary
#  Stage 2  stage2/mojo --dump fire.py (single-file for individual validation)
#             → stage2/fire.ci  (+ .tok .ast .pyi for all source files)
#  Stage 3  stage2/mojo --dump fire.py  (idempotency: same binary, same output)
#             → stage3/fire.ci  (+ .tok .ast .pyi for all source files)
#  verify   stage1 == stage2 == stage3  for all generated files
#
# The steps, their order, and their memory ceilings are in tools/suite.py's
# `bootstrap` bucket. Two things that used to live here and are worth keeping
# in the reader's head:
#
#  * The transitive `--dump-full` step runs AFTER that stage's per-file dump
#    loop, not before. The loop writes fire.ci for fire.py as a single module,
#    and the closure dump has to be the last writer of that name or stage2
#    links a skeleton with undefined symbols (and `verify` compares a full
#    closure against a skeleton, which is a permanent mismatch rather than a
#    codegen bug — that step was simply missing from stage2/stage3).
#  * `bootstrap-clean` wipes the stage trees first, because `verify` only
#    compares whatever files happen to be sitting in stage1/, stage2/,
#    stage3/ — it never checks that those files correspond to a CURRENT *.mojo
#    source. A stale artifact from an old file set is still present in one
#    stage dir and missing in another, and verify reports a false failure on
#    an unrelated file. A bootstrap is a from-scratch recompile regardless
#    (every source is re-dumped every stage), so this costs nothing.
#
# The heavy steps are memory-capped (MEMCLASS `program`/`stage` in
# tools/suite.py) and hold the machine to themselves. That is new: this used
# to run the same workload as check-native-dumpfull — measured at 55 GB healthy
# and 192 GB when it ran away — three more times with no ceiling at all.
bootstrap:
	@$(SUITE) $(SUITE_J) bootstrap

stage1:
	@$(SUITE) $(SUITE_J) bootstrap-clean \
	    bootstrap-stage1-dumps bootstrap-stage1-transitive

stage2:
	@$(SUITE) $(SUITE_J) bootstrap-stage2-dumps \
	    bootstrap-stage2-transitive

stage3:
	@$(SUITE) $(SUITE_J) bootstrap-stage3-dumps \
	    bootstrap-stage3-transitive

verify:
	@$(SUITE) $(SUITE_J) bootstrap-verify

validate-all:
	@$(SUITE) $(SUITE_J) bootstrap-validate

dump-all-stage1:
	@$(SUITE) $(SUITE_J) bootstrap-stage1-dumps
dump-all-stage2:
	@$(SUITE) $(SUITE_J) bootstrap-stage2-dumps
dump-all-stage3:
	@$(SUITE) $(SUITE_J) bootstrap-stage3-dumps

# ── Build rules ──────────────────────────────────────────────────────────────
# One-step self-host build: `mojoc` is stage2/mojo without the staging, and is
# the binary the `native` bucket's tests run.
mojoc: $(MOJO_MAIN) $(RUNTIME_SRC) $(RUNTIME_HDR)
	@echo "=== Building mojoc from $(MOJO_MAIN) ($(MOJO_OPT)) ==="
	python3 fire.py build fire.py $(MOJO_OPT) -o mojoc
	@echo "✓ mojoc ready"

# stage1/fire.ci is written by the runner's stage1 steps (a whole-closure
# python dump: minutes, memory-capped, and the one thing in the chain that
# cannot be cached or skipped). This is not a real rule — it exists so that
# `make stage2/mojo` on a clean tree does the right thing instead of failing
# with "no rule to make target".
stage1/fire.ci:
	@$(SUITE) $(SUITE_J) bootstrap-stage1-transitive

# -ftrivial-auto-var-init=zero: the generated .ci reads some `char *` locals
# before every codegen path has assigned them (a real gap in the self-hosted
# metadata-dict/AST-field type inference, tracked separately — see the bugs
# list / selfhost-shimless-progress memory). Without this flag GCC leaves such
# a read as classic uninitialized-stack garbage, which — since stage2/mojo's
# OWN compiled codegen always runs now (the python3-subprocess fallback was
# removed entirely from gimple_codegen_compile_to_gimple,
# runtime/fire_runtime.c) — was a flaky SIGSEGV in `_declare_var`'s
# `mojo_str_cat` (strlen on a garbage pointer). Zero-init makes the read
# well-defined (NULL), which the codegen's own `_ptr_slot_in_range` guard
# already treats as "no known type" and falls back on safely.
stage2/mojo: stage1/fire.ci $(RUNTIME_SRC) $(RUNTIME_HDR) $(CORO_RUNTIME_SRC)
	@mkdir -p stage2
	@echo "=== Compiling stage2/mojo from stage1/fire.ci ==="
	$(BOOTSTRAP_CC) $(BOOTSTRAP_OPT) -fgimple -ftrivial-auto-var-init=zero -I runtime \
	    $(BIG_STACK_LDFLAGS) \
	    -o stage2/mojo \
	    -x c stage1/fire.ci \
	    -x none $(RUNTIME_SRC) \
	    $(CORO_RUNTIME_SRC)
	@chmod +x stage2/mojo
	@echo "✓ stage2/mojo ready"

# Dev build (non-bootstrap quick compile) ─────────────────────────────────────
# FORCE (empty recipe, always-out-of-date) rather than an explicit file list:
# fire.ci is do_imports=True whole-program output of mojo.py's entire transitive
# closure (gimple_codegen.py, module_loader.py, fire_compiler.py, ...) — any of
# those can change without mojo.py itself changing, and a stale fire.ci built
# before such a change silently gets reused otherwise (confirmed: caused a
# bare-vs-qualified symbol mismatch after an unrelated codegen.py edit).
.PHONY: FORCE
FORCE:

fire.ci: $(MOJO_MAIN) FORCE
	PYTHONPATH=. python3 fire.py --dump-full $(MOJO_MAIN) 2>/dev/null

build/system.o: fire.ci
	@mkdir -p build
	$(BOOTSTRAP_CC) -fgimple -I runtime -c -o $@ -x c fire.ci

build/fire_runtime.o: $(RUNTIME_SRC) $(RUNTIME_HDR)
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $(RUNTIME_SRC)

# A3 stack-switch coroutine runtime (doc/COROUTINE.html §5.5: the default
# generator/async backend now) — this dev build has the identical gap
# stage2/mojo's own recipe had (see CORO_RUNTIME_SRC's own comment above):
# mojo.py's own source has a generator (e.g. gimple_gen_coro.py's `_walk`),
# so `build/system.o` genuinely references __fire_coro_yield_i/__firegco_*
# once compiled, with nothing on this link line to satisfy it.
build/fire_coro.o: runtime/fire_coro.c
	@mkdir -p build
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $<

build/fire_coro_gen.o: runtime/fire_coro_gen.c
	@mkdir -p build
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $<

build/fire_async_sched.o: runtime/fire_async_sched.c
	@mkdir -p build
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $<

build/fire_coro_ctx.o: $(CORO_ARCH_SRC)
	@mkdir -p build
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $<

CORO_RUNTIME_OBJS = build/fire_coro.o build/fire_coro_gen.o build/fire_async_sched.o build/fire_coro_ctx.o

build/fire: build/system.o build/fire_runtime.o $(CORO_RUNTIME_OBJS)
	@mkdir -p build
	$(BOOTSTRAP_CC) $(BIG_STACK_LDFLAGS) -o $@ build/system.o build/fire_runtime.o $(CORO_RUNTIME_OBJS)
	@chmod +x $@
	@echo "build/mojo linked successfully"

# ── aside/bside/compare-a-b: per-file self-host A/B sweep at scale ───────────
# This one really is Make's job, and the reason is worth keeping: each file
# needs its own real target so `-j` parallelizes at the file level rather than
# inside one Python process, and the two sides are ~780 independent compiles
# that must all finish before the comparison means anything. It is also why
# the runner's `ab` bucket uses driver='make' for these three steps.
#
# check-native-dumpfull's whole-transitive-closure self-compile is the only
# other test of the self-hosted BINARY's own codegen, and it is a single
# all-or-nothing process: dangerous to run repeatedly (see
# bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md's 2026-09-15 retry,
# 230 GB RSS) and uninformative when it fails — one diff offset for the WHOLE
# program. This decomposes the same python-vs-native question into one
# `--dump` (do_imports=False, no transitive-closure accumulation) per file, so
# each compile is a bounded, independent process and a crash on one file
# cannot take down the sweep.
#
# Usage: `make -j20 aside bside && make compare-a-b` — prints only FAIL: lines
# (see tools/ab_compare.py's own docstring for the failure categories) plus a
# totals line; no PASS output by design, since the intended workflow is to
# sweep once at scale, then work the FAIL list by hand, one file at a time.
# `make ab-clean` before a full re-sweep after any compiler-source change
# (per-rule Make caching only tracks each rule's own input file + mojoc, not
# the whole compiler source graph).
ab.mk: tools/gen_ab_makefile.py tools/ab_filelist.py
	python3 tools/gen_ab_makefile.py > ab.mk

-include ab.mk

.PHONY: aside bside compare-a-b ab-clean
aside: ab.mk $(ASIDE_TARGETS)
bside: ab.mk mojoc $(BSIDE_TARGETS)
compare-a-b:
	python3 tools/ab_compare.py
ab-clean:
	rm -rf aside bside ab.mk .ab_locks

# ── Packaging ────────────────────────────────────────────────────────────────
tar: mojo.tar.gz
mojo.tar.gz:
	-tar cfz mojo.tar.gz $$(cat files.txt files-rest.txt 2>/dev/null)
	-echo tar done

# ── Clean ────────────────────────────────────────────────────────────────────
clean:
	rm -rf build stage1 stage2 stage3 *.ci *.tok *.pyi *.ast *.o

clean-bootstrap:
	rm -rf stage1 stage2 stage3
	@echo "Note: all *.mojo files preserved (hand-edited source files)"
