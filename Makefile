.PHONY: run demo check check-gimple check-runner check-gimple-runner check-modcache \
        check-selfhost check-stdlib check-stdlib-interp check-stdlib-jit check-ab-native \
        check-coro check-formal \
        clean clean-bootstrap stdlib bootstrap preflight \
        stage1 stage2 stage3 verify validate-all dump-all-stage1 dump-all-stage2 dump-all-stage3

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
STDLIB_DYLIB = build/libmojostdlib.dylib
FIRE_CLI     = build/mojo
# The canonical source that all three stages compile
MOJO_MAIN    = fire.py

GCC_MP15     = /opt/local/bin/gcc-mp-15
BOOTSTRAP_CC = $(shell command -v gcc-15 >/dev/null 2>&1 && echo gcc-15 || (test -x $(GCC_MP15) && echo $(GCC_MP15)) || echo gcc)

# 512MB main-thread stack (default 8MB). The self-hosted compiler's regex
# engine and generic AST walkers are deeply CPS-recursive — a re.sub/findall
# over a 200KB module source recurses per input position and blows the
# default stack (only reached on the MOJO_NO_SHIM=1 --dump-full path).
BIG_STACK_LDFLAGS = $(shell test "$$(uname -s)" = "Darwin" && echo "-Wl,-stack_size,0x20000000" || echo "-Wl,-z,stacksize=536870912")

# MacPorts GCC can't find SDK headers without this
SDKROOT := $(shell xcrun --show-sdk-path 2>/dev/null)
export SDKROOT

# All Mojo source files to validate (top-level + mojo/ subdirectory)
MOJO_FILES := $(wildcard *.mojo) $(wildcard mojo/*.mojo)
# Core Python compiler/tool files to validate through the Mojo system
PY_FILES   := fire.py fire_compiler.py myinterpreter.py \
              module_loader.py fire_main.py generated_dispatch.py

# ── Dev targets ──────────────────────────────────────────────────────────────
demo:
	echo "3 + 42 + 0xFF" | python3 fire_compiler.py

# Everyday green gate: the GIMPLE unit suite, the execution runner, the
# module-cache end-to-end stages, the self-host compile guard, and the stdlib
# test/benchmark suite (interpreter + JIT), and the link-mode compile guard
# (the real `driver.compile_program` pipeline `mojo.py build` actually uses —
# distinct from every other check-* target here plus compile_stdlib.py/
# build_stdlib_dylib.py, which all drive codegen through the single-
# translation-unit `do_imports=False` inline path instead; a link-mode-only
# bug is invisible to all of them, see bugs/COMPILE_FAIL_asyncio_futures.md
# and the two bugs/CODEGEN_link_mode_*.md docs, all found this way). The
# self-hosting bootstrap (stage1-3 + validate-all) is a separate,
# aspirational target — `make bootstrap` — because stage 2 has a known
# pre-existing codegen segfault (see IMPL.md); it is not gated into `check`
# so `check` stays a meaningful pass/fail signal.
check: check-gimple check-runner check-modcache check-selfhost check-runtimediff check-linkmode check-native-dumpfull check-no-new-casts
	@echo ""
	@echo "✓ check complete (gimple + runner + module-cache + self-host + runtime-diff + link-mode + native dump-full + no-new-casts)"

# Every check-* target is wrapped in checked_run.py: a check's outcome is a
# pure function of the compiler sources + toolchain + whatever extra files it
# actually exercises (the test script itself, myinterpreter.py, the runtime,
# ...), so once a given input hash has produced a result, replay it instead
# of re-running the check - a hit is exact (same exit code, same stdout/
# stderr), not an approximation. See checked_run.py's docstring.

# All compiler source modules (post-refactor gimple_codegen split). Any edit
# to one of these must re-run the gates that compile the compiler.
GIMPLE_SOURCES := gimple_codegen.py $(wildcard gimple_gen_*.py) \
                  $(wildcard gimple_cpp_*.py) gimple_ctypes.py \
                  gimple_solvers.py gimple_exprtypes.py \
                  $(wildcard mojo/middle/*.py) $(wildcard mojo/backend_gimple/*.py) \
                  ownership_check.py ownership_destruct.py

check-gimple: $(GIMPLE_SOURCES) test_gimple.py
	python3 checked_run.py check-gimple --extra test_gimple.py -- python3 test_gimple.py

# test_runner.py only existence-checks the prebuilt `build/mojo`, doesn't require it
# to be up-to-date. We build it here to ensure it exists for the test.
check-runner: build/mojo test_runner.py myinterpreter.py fire.py fire_main.py $(RUNTIME_SRC) $(RUNTIME_HDR)
	python3 checked_run.py check-runner \
		--extra test_runner.py --extra myinterpreter.py --extra fire.py --extra fire_main.py \
		--extra $(RUNTIME_SRC) --extra $(RUNTIME_HDR) \
		-- python3 test_runner.py

check-modcache: $(GIMPLE_SOURCES) test_module_cache.py myinterpreter.py fire.py fire_main.py
	python3 checked_run.py check-modcache \
		--extra test_module_cache.py --extra myinterpreter.py --extra fire.py --extra fire_main.py \
		-- python3 test_module_cache.py

# Self-host compile guard: mojo.py must compile itself to a linked binary with
# zero GCC errors / ICEs / undefined symbols (the --jit mojo.py path, minus
# execution — the runtime still SIGSEGVs, a separate frontier). Locks compile+
# link cleanliness so it can't silently regress.
check-selfhost: $(GIMPLE_SOURCES) fire_compiler.py myinterpreter.py fire.py fire_main.py test_selfhost.py
	python3 checked_run.py check-selfhost \
		$(foreach s,$(GIMPLE_SOURCES),--extra $(s)) \
		--extra fire_compiler.py --extra myinterpreter.py --extra fire.py --extra fire_main.py \
		--extra test_selfhost.py \
		-- python3 test_selfhost.py

# Interpreter-vs-JIT runtime parity: every program in the corpus must produce
# identical stdout + exit code via `python3 mojo.py run` (interpreter) and
# `python3 mojo.py --jit` (compiled). A JIT-COMPILE-FAILED is reported
# distinctly (the compiled path falls back to the interpreter, which would
# otherwise mask a divergence). Currently 23 pass, 1 JIT-COMPILE-FAILED
# (generator_simple — the C++ coroutine frontier).
check-runtimediff: $(GIMPLE_SOURCES) fire_compiler.py myinterpreter.py fire.py test_runtime_diff.py
	python3 checked_run.py check-runtimediff \
		$(foreach s,$(GIMPLE_SOURCES),--extra $(s)) \
		--extra fire_compiler.py --extra myinterpreter.py --extra fire.py \
		--extra test_runtime_diff.py \
		-- python3 test_runtime_diff.py

# Link-mode compile guard: builds real multi-file packages through
# `driver.compile_program` (the actual pipeline `mojo.py build` uses by
# default), not the `do_imports=False` single-translation-unit inline path
# every OTHER check-* target here (plus compile_stdlib.py/
# build_stdlib_dylib.py) uses instead — a link-mode-only bug in import/
# module-value registration is invisible to all of them. See
# test_link_mode.py's own module docstring.
check-linkmode: $(GIMPLE_SOURCES) fire_compiler.py myinterpreter.py fire.py driver.py test_link_mode.py
	python3 checked_run.py check-linkmode \
		$(foreach s,$(GIMPLE_SOURCES),--extra $(s)) \
		--extra fire_compiler.py --extra myinterpreter.py --extra fire.py --extra driver.py \
		--extra test_link_mode.py \
		-- python3 test_link_mode.py

# ── check-coro: the A3 stack-switch coroutine runtime (doc/COROUTINE.html) ───
# Standalone C unit tests for Layer 3 (context switch) and Layer 2 (coroutine
# runtime), each run against every Layer 3 backend at -O0 and -O2.
check-coro: runtime/fire_coro.c runtime/fire_coro.h runtime/fire_coro_ctx.h \
            runtime/fire_coro_ctx_aarch64.S runtime/fire_coro_ctx_generic.c \
            runtime/test_fire_coro.c runtime/test_fire_coro_ctx.c \
            runtime/test_fire_coro_exc_stub.c test_coro_runtime.py
	python3 checked_run.py check-coro --extra test_coro_runtime.py \
		--extra runtime/fire_coro.c --extra runtime/fire_coro_ctx_aarch64.S \
		--extra runtime/fire_coro_ctx_generic.c \
		-- python3 test_coro_runtime.py

# Run all stdlib test and benchmark files through both the interpreter
# (mojo.py run) and the JIT compiler (mojo.py --jit).
check-stdlib: fire_compiler.py
	python3 test_stdlib.py

# Run stdlib tests/benchmarks through interpreter only (mojo.py run).
check-stdlib-interp: fire_compiler.py
	python3 test_stdlib.py --mode interp

# Run stdlib tests/benchmarks through JIT compiler only (mojo.py --jit).
check-stdlib-jit: fire_compiler.py
	python3 test_stdlib.py --mode jit

check-gimple-runner:
	python3 test_gimple_runner.py

# ── check-formal: formal arm64 + Lean 4 proof typecheck ──────────────────────
# Every formal/examples/*.mojo through formalbuild --prove, then pixi's lean
# typechecks the generated proof statically (no binary execution). Parallel
# by default (min(cpu_count, 20) workers — see test_formal.py). Not gated
# into `check`: lean/pixi (pixi install + pixi run prooflib) is an extra
# dependency beyond the rest of the testsuite. Serial single-stem path:
# tools/proof.sh <stem>.
FORMAL_SOURCES  := $(wildcard formal/*.py)
FORMAL_EXAMPLES := $(wildcard formal/examples/*.mojo)

check-formal: $(FORMAL_SOURCES) $(FORMAL_EXAMPLES) test_formal.py fire.py \
              fire_compiler.py lib/ProofLib.olean
	python3 checked_run.py check-formal \
		$(foreach s,$(FORMAL_SOURCES),--extra $(s)) \
		$(foreach s,$(FORMAL_EXAMPLES),--extra $(s)) \
		--extra test_formal.py --extra fire.py --extra fire_compiler.py \
		--extra lib/ProofLib.olean \
		-- python3 test_formal.py

# ProofLib.olean is required by check-formal / tools/proof.sh; build it here
# if missing so the Make prereq above can be satisfied from a fresh clone.
lib/ProofLib.olean: lib/ProofLib.lean lib/work.lean lib/Refine.lean pixi.toml
	pixi run prooflib

# Parse and validate entire stdlib (all .mojo files)
stdlib:
	python3 compile_stdlib.py

# ── Bootstrap stages ─────────────────────────────────────────────────────────
#
# Three-stage self-hosting verification with transitive-closure compilation:
#
#  Stage 1  Python mojo.py --dump-full mojo.py (single pass, all imports inline)
#             → stage1/fire.ci  (clean, no deduplication needed)
#  stage2/mojo  GCC -fgimple compiles stage1/fire.ci + runtime → compiled binary
#  Stage 2  stage2/mojo --dump mojo.py (single-file for individual validation)
#             → stage2/fire.ci  (+ .tok .ast .pyi for all source files)
#  Stage 3  stage2/mojo --dump mojo.py  (idempotency: same binary, same output)
#             → stage3/fire.ci  (+ .tok .ast .pyi for all source files)
#  verify   stage1 == stage2 == stage3  for all generated files

# ── Stage 1: Python drives the compiler ──────────────────────────────────────
# The --dump-full step is load-bearing: it's the single transitive-closure
# fire.ci that stage2/mojo gets compiled from below, and must stay exactly as
# is. The per-file --dump loop is separate and additional — bootstrap-
# validate.mojo (see validate-all) compares stage1/<file>.{ci,tok,ast,pyi}
# against stage2/stage3 for every source file, but until now stage1 only
# ever produced those 4 outputs for mojo.py itself (and even then, only
# .ci — --dump-full doesn't emit .tok/.ast/.pyi at all), so validate-all's
# "154 mismatches" were never a real regression signal, just this asymmetry.
#
# `clean-bootstrap` prerequisite: `verify`'s stage1-vs-stage2-vs-stage3
# comparison only looks at whatever files happen to be sitting in stage1/,
# stage2/, stage3/ — it never checks those files still correspond to a
# CURRENT *.mojo source. If the top-level *.mojo file set changes between
# bootstrap runs (a scratch file added or removed) without the stage dirs
# being wiped first, a stale generated artifact from the OLD file set is
# still present in one stage dir but missing (or a fresh mismatch) in
# another, and verify reports a false failure on a completely unrelated
# file. `bootstrap` is a from-scratch full recompile regardless (every
# source file is re-dumped every stage), so forcing a clean stage tree
# here costs nothing and removes an entire class of stale-artifact false
# failures for free.
stage1: clean-bootstrap
	@mkdir -p stage1
	@echo "=== Stage 1: Python → stage1/ ==="
	@FAILED=0; \
	run_dump() { \
	    out=$$(cd stage1 && PYTHONPATH=.. python3 ../fire.py --dump "../$$1" 2>&1); \
	    rc=$$?; \
	    [ -n "$$out" ] && echo "$$out"; \
	    if [ $$rc -ne 0 ] || echo "$$out" | grep -q "mojo_unsupported_iter"; then \
	        echo "  FAILED: $$1"; \
	        FAILED=1; \
	    fi; \
	}; \
	echo "--- Dumping all .mojo source files ---"; \
	for f in $(MOJO_FILES); do \
	    echo "  dump $$f"; \
	    run_dump $$f; \
	done; \
	echo "--- Dumping core .py source files ---"; \
	for f in $(PY_FILES); do \
	    echo "  dump $$f"; \
	    run_dump $$f; \
	done; \
	if [ "$$FAILED" = "0" ]; then \
	    echo "✓ Stage 1 dump validation complete"; \
	else \
	    echo "✗ Stage 1 had failures (see FAILED lines above)"; exit 1; \
	fi
	@echo "=== Stage 1: Python → stage1/ (transitive closure) ==="
	# Generate the bootstrap .ci LAST: the --dump validation loop above also
	# writes {basename}.ci for mojo.py (single-module, do_imports=False), which
	# would otherwise clobber this transitive-closure .ci and leave stage2
	# linking a skeleton with undefined symbols (py_tokenize etc.).
	cd stage1 && PYTHONPATH=.. python3 ../fire.py --dump-full ../$(MOJO_MAIN)

# ── mojoc: one-step self-host build (equivalent to stage2/mojo, no staging needed) ──
mojoc: $(MOJO_MAIN) $(RUNTIME_SRC) $(RUNTIME_HDR)
	@echo "=== Building mojoc from fire.py ==="
	python3 fire.py build fire.py -o mojoc
	@echo "✓ mojoc ready"

# ── stage2/mojo: compile stage1 output into a real binary ────────────────────
# -ftrivial-auto-var-init=zero: the generated .ci reads some `char *`
# locals before every codegen path has assigned them (a real gap in the
# self-hosted metadata-dict/AST-field type inference, tracked separately
# — see bugs list / selfhost-shimless-progress memory). Without this
# flag GCC leaves such a read as classic uninitialized-stack garbage,
# which — since stage2/mojo's OWN compiled codegen always runs now (the
# python3-subprocess fallback was removed entirely from gimple_codegen_
# compile_to_gimple, runtime/fire_runtime.c) — was a flaky SIGSEGV in
# `_declare_var`'s `mojo_str_cat` (strlen on a garbage pointer). Zero-
# init makes the read well-defined (NULL), which the codegen's own
# `_ptr_slot_in_range` guard already treats as "no known type" and
# falls back on safely.
stage2/mojo: stage1 $(RUNTIME_SRC) $(RUNTIME_HDR) $(CORO_RUNTIME_SRC)
	@mkdir -p stage2
	@echo "=== Compiling stage2/mojo from stage1/fire.ci ==="
	$(BOOTSTRAP_CC) -fgimple -ftrivial-auto-var-init=zero -I runtime \
	    $(BIG_STACK_LDFLAGS) \
	    -o stage2/mojo \
	    -x c stage1/fire.ci \
	    -x none $(RUNTIME_SRC) \
	    $(CORO_RUNTIME_SRC)
	@chmod +x stage2/mojo
	@echo "✓ stage2/mojo ready"

# ── Stage 2: compiled binary drives itself ────────────────────────────────────
# Runs every file's --dump (collect-all), but a per-file failure — a nonzero
# exit from `mojo --dump`, or the runtime's `mojo_unsupported_iter` warning
# (a real codegen gap that just doesn't SIGABRT the whole compiler, see
# runtime/fire_runtime.c) — is tracked and fails the target at the end, so
# real problems can't silently pass as "✓ Stage 2 complete".
stage2: stage2/mojo
	@mkdir -p stage2
	@echo "=== Stage 2: stage2/mojo → stage2/ ==="
	@FAILED=0; \
	run_dump() { \
	    out=$$(cd stage2 && MOJO_HOME=.. PYTHONPATH=.. ./mojo --dump "../$$1" 2>&1); \
	    rc=$$?; \
	    [ -n "$$out" ] && echo "$$out"; \
	    if [ $$rc -ne 0 ] || echo "$$out" | grep -q "mojo_unsupported_iter"; then \
	        echo "  FAILED: $$1"; \
	        FAILED=1; \
	    fi; \
	}; \
	run_dump $(MOJO_MAIN); \
	echo "--- Dumping all .mojo source files ---"; \
	for f in $(MOJO_FILES); do \
	    echo "  dump $$f"; \
	    run_dump $$f; \
	done; \
	echo "--- Dumping core .py source files ---"; \
	for f in $(PY_FILES); do \
	    echo "  dump $$f"; \
	    run_dump $$f; \
	done; \
	if [ "$$FAILED" = "0" ]; then \
	    echo "✓ Stage 2 complete"; \
	else \
	    echo "✗ Stage 2 had failures (see FAILED lines above)"; exit 1; \
	fi
	@echo "=== Stage 2: stage2/mojo → stage2/ (transitive closure) ==="
	# Generate the bootstrap .ci LAST, mirroring stage1's identical comment/
	# ordering: the --dump loop above also writes fire.ci (single-module,
	# do_imports=False, from `run_dump $(MOJO_MAIN)`), which would otherwise
	# clobber this transitive-closure .ci and leave `verify` comparing a full
	# closure (stage1/fire.ci) against a single-module skeleton
	# (stage2/fire.ci) — a real, permanent mismatch, not a codegen bug: this
	# step was simply missing from stage2/stage3's targets even though
	# stage1's has always had it.
	cd stage2 && MOJO_HOME=.. PYTHONPATH=.. ./mojo --dump-full ../$(MOJO_MAIN)

# ── Stage 3: idempotency check (same binary, fresh output dir) ───────────────
stage3: stage2/mojo stage2
	@mkdir -p stage3
	@echo "=== Stage 3: stage2/mojo → stage3/ (idempotency check) ==="
	@FAILED=0; \
	run_dump() { \
	    out=$$(cd stage3 && MOJO_HOME=.. PYTHONPATH=.. ../stage2/mojo --dump "../$$1" 2>&1); \
	    rc=$$?; \
	    [ -n "$$out" ] && echo "$$out"; \
	    if [ $$rc -ne 0 ] || echo "$$out" | grep -q "mojo_unsupported_iter"; then \
	        echo "  FAILED: $$1"; \
	        FAILED=1; \
	    fi; \
	}; \
	run_dump $(MOJO_MAIN); \
	echo "--- Dumping all .mojo source files ---"; \
	for f in $(MOJO_FILES); do \
	    echo "  dump $$f"; \
	    run_dump $$f; \
	done; \
	echo "--- Dumping core .py source files ---"; \
	for f in $(PY_FILES); do \
	    echo "  dump $$f"; \
	    run_dump $$f; \
	done; \
	if [ "$$FAILED" = "0" ]; then \
	    echo "✓ Stage 3 complete"; \
	else \
	    echo "✗ Stage 3 had failures (see FAILED lines above)"; exit 1; \
	fi
	@echo "=== Stage 3: stage2/mojo → stage3/ (transitive closure) ==="
	# See stage2's identical step: same missing-step bug, same fix.
	cd stage3 && MOJO_HOME=.. PYTHONPATH=.. ../stage2/mojo --dump-full ../$(MOJO_MAIN)

# ── verify: all three stages identical for every generated file ───────────────
verify: stage3
	@echo "=== Verifying stage outputs ==="
	@FAILED=0; \
	for ext in ci tok ast pyi; do \
	    for f in stage1/*.$$ext; do \
	        [ -f "$$f" ] || continue; \
	        base=$$(basename $$f); \
	        if [ -f "stage2/$$base" ] && [ -f "stage3/$$base" ]; then \
	            if ! diff -q "$$f" "stage2/$$base" > /dev/null 2>&1; then \
	                echo "FAIL stage1 vs stage2: $$base"; FAILED=1; \
	            elif ! diff -q "stage2/$$base" "stage3/$$base" > /dev/null 2>&1; then \
	                echo "FAIL stage2 vs stage3: $$base"; FAILED=1; \
	            else \
	                echo "  OK $$base"; \
	            fi; \
	        else \
	            echo "  WARN missing: stage2/$$base or stage3/$$base (skipped)"; \
	        fi; \
	    done; \
	done; \
	if [ "$$FAILED" = "0" ]; then \
	    echo "✓ All stage outputs match"; \
	else \
	    echo "✗ Stage verification FAILED"; exit 1; \
	fi

# ── validate-all: run bootstrap-validate.mojo (Python-executed) ──────────────
validate-all: stage3
	python3 bootstrap-validate.mojo

# ── bootstrap: full end-to-end ────────────────────────────────────────────────
bootstrap: verify validate-all
	@echo ""
	@echo "✓ Bootstrap complete — all stages verified"

# ── check-ab-native: compiled compile_to_gimple vs Python, byte-for-byte ─────
# `test_ab_native.py` diffs `python3 fire.py --dump X` against
# `./mojoc --dump X` for a 27-case corpus of small programs, both run from
# the repo root, compared byte-for-byte. All 27 are byte-identical — this
# is the regression guard for that parity. The self-hosted binary never
# spawns a python3 subprocess at all now (gimple_codegen_compile_to_gimple,
# runtime/fire_runtime.c, always calls its own compiled compile_to_gimple
# directly), so this test simply compares two independent implementations
# (python3-interpreted vs self-hosted-compiled) of the same compiler.
check-ab-native: mojoc $(GIMPLE_SOURCES) test_ab_native.py
	python3 checked_run.py check-ab-native --extra test_ab_native.py -- python3 test_ab_native.py

# ── check-native-dumpfull: self-hosted --dump-full ARTIFACT check (DESIGN.html R6) ──
# Every OTHER check-* target drives codegen through the python3-interpreted
# reference; only this one runs the self-hosted mojoc BINARY's own compiled
# (native) codegen on real work and diffs the actual output byte-for-byte
# against the reference's, not just the exit code. See test_native_
# dumpfull.py's own docstring for why: a native-codegen-only bug can
# produce a wrong-but-exit-0 .ci that every other gate step is structurally
# blind to (this happened for real 2026-09-13 - a fix that silenced a known
# SIGBUS turned out to silently drop two compiled modules instead, and
# every check-* target stayed green).
check-native-dumpfull: mojoc $(GIMPLE_SOURCES) test_native_dumpfull.py
	python3 checked_run.py check-native-dumpfull --extra test_native_dumpfull.py -- python3 test_native_dumpfull.py

# ── aside/bside/compare-a-b: per-file self-host A/B sweep at scale ───────────
# check-native-dumpfull's whole-transitive-closure self-compile is both the
# only test of the self-hosted BINARY's own codegen and, per
# bugs/CODEGEN_noshim_dumpfull_preexisting_divergence.md's 2026-09-15 retry,
# capable of spiking past 230GB RSS on the full mojo.py self-compile — a
# single all-or-nothing process that's both dangerous to run repeatedly and
# uninformative when it fails (one diff offset for the WHOLE program).
#
# This decomposes the same python-vs-native question into one `--dump`
# (do_imports=False, no transitive-closure accumulation — see mojo.py's own
# dump_full-vs-dump branch) per file, for every .py file in this repo's own
# root plus every .mojo file across the stdlib's tracked subtrees (same file
# set compile_stdlib.py already exercises, ~782 files total as of writing).
# Each file's compile is its own bounded, independent process — no O(N²)
# transitive rescan, no unbounded memory growth, and a crash on one file
# can't take down the whole sweep. `ab.mk` (generated) gives each file its
# own real Make target so `-j20` parallelizes at the file level, not just
# inside one Python process.
#
# Usage: `make -j20 aside bside && make compare-a-b` — prints only FAIL:
# lines (see tools/ab_compare.py's own docstring for the failure
# categories) plus a totals line; no PASS output by design, since the
# intended workflow is to sweep once at scale, then work the FAIL list by
# hand, one file at a time. `make ab-clean` before a full re-sweep after any
# compiler-source change (per-rule Make caching only tracks each rule's own
# input file + mojoc, not the whole compiler source graph).
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

# ── check-no-new-casts: grow-only allowlist on ad-hoc container casts (DESIGN.html R3) ──
# Pure text scan, no compile needed - deliberately cheap so it runs on every
# `make check`. See test_no_new_container_casts.py's own docstring.
check-no-new-casts: $(GIMPLE_SOURCES) test_no_new_container_casts.py
	python3 checked_run.py check-no-new-casts --extra test_no_new_container_casts.py -- python3 test_no_new_container_casts.py

# ── Preflight checks ──────────────────────────────────────────────────────────
preflight:
	@test -f fire_compiler.py || \
	    { echo "FAIL preflight: fire_compiler.py missing"; exit 1; }
	@test -f gimple_codegen.py || \
	    { echo "FAIL preflight: gimple_codegen.py missing"; exit 1; }
	@test -f $(MOJO_MAIN) || \
	    { echo "FAIL preflight: $(MOJO_MAIN) missing"; exit 1; }
	@python3 -c "from fire_compiler import tokenize, Parser; print('parser OK')"
	@python3 -c "import gimple_codegen; print('codegen OK')"
	@echo "✓ Preflight passed"

# ── Dev build (non-bootstrap quick compile) ───────────────────────────────────
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

# ── Packaging ─────────────────────────────────────────────────────────────────
tar: mojo.tar.gz
mojo.tar.gz:
	-tar cfz mojo.tar.gz $$(cat files.txt files-rest.txt 2>/dev/null)
	-echo tar done

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf build stage1 stage2 stage3 *.ci *.tok *.pyi *.ast *.o

clean-bootstrap:
	rm -rf stage1 stage2 stage3
	@echo "Note: all *.mojo files preserved (hand-edited source files)"
