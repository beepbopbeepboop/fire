.PHONY: run demo check check-gimple check-runner check-gimple-runner check-modcache \
        check-selfhost check-stdlib check-stdlib-interp check-stdlib-jit check-abshim \
        check-coro \
        clean clean-bootstrap stdlib bootstrap preflight \
        stage1 stage2 stage3 verify validate-all dump-all-stage1 dump-all-stage2 dump-all-stage3

# ── Paths ────────────────────────────────────────────────────────────────────
RUNTIME_SRC  = runtime/mojo_runtime.c
RUNTIME_HDR  = runtime/mojo_runtime.h
STDLIB_DYLIB = build/libmojostdlib.dylib
MOJO_CLI     = build/mojo
# The canonical source that all three stages compile
MOJO_MAIN    = mojo.py

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
PY_FILES   := mojo.py mojo_compiler.py myinterpreter.py \
              module_loader.py mojo_main.py generated_dispatch.py

# ── Dev targets ──────────────────────────────────────────────────────────────
# DEAD: we no longer generate mojo_compiler.py from .md specs via run.py /
# compiler_gen.py. The compiler is hand-edited directly now. Do not use.
#run:
#	python3 run.py   # DEAD — would clobber the hand-written mojo_compiler.py

demo:
	echo "3 + 42 + 0xFF" | python3 mojo_compiler.py

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
check: check-gimple check-runner check-modcache check-selfhost check-runtimediff check-linkmode
	@echo ""
	@echo "✓ check complete (gimple + runner + module-cache + self-host + runtime-diff + link-mode)"

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
                  gimple_solvers.py gimple_exprtypes.py

check-gimple: $(GIMPLE_SOURCES) test_gimple.py
	python3 checked_run.py check-gimple --extra test_gimple.py -- python3 test_gimple.py

# test_runner.py only existence-checks the prebuilt `build/mojo`, doesn't require it
# to be up-to-date. We build it here to ensure it exists for the test.
check-runner: build/mojo test_runner.py myinterpreter.py mojo.py mojo_main.py $(RUNTIME_SRC) $(RUNTIME_HDR)
	python3 checked_run.py check-runner \
		--extra test_runner.py --extra myinterpreter.py --extra mojo.py --extra mojo_main.py \
		--extra $(RUNTIME_SRC) --extra $(RUNTIME_HDR) \
		-- python3 test_runner.py

check-modcache: $(GIMPLE_SOURCES) test_module_cache.py myinterpreter.py mojo.py mojo_main.py
	python3 checked_run.py check-modcache \
		--extra test_module_cache.py --extra myinterpreter.py --extra mojo.py --extra mojo_main.py \
		-- python3 test_module_cache.py

# Self-host compile guard: mojo.py must compile itself to a linked binary with
# zero GCC errors / ICEs / undefined symbols (the --jit mojo.py path, minus
# execution — the runtime still SIGSEGVs, a separate frontier). Locks compile+
# link cleanliness so it can't silently regress.
check-selfhost: $(GIMPLE_SOURCES) mojo_compiler.py myinterpreter.py mojo.py mojo_main.py test_selfhost.py
	python3 checked_run.py check-selfhost \
		$(foreach s,$(GIMPLE_SOURCES),--extra $(s)) \
		--extra mojo_compiler.py --extra myinterpreter.py --extra mojo.py --extra mojo_main.py \
		--extra test_selfhost.py \
		-- python3 test_selfhost.py

# Interpreter-vs-JIT runtime parity: every program in the corpus must produce
# identical stdout + exit code via `python3 mojo.py run` (interpreter) and
# `python3 mojo.py --jit` (compiled). A JIT-COMPILE-FAILED is reported
# distinctly (the compiled path falls back to the interpreter, which would
# otherwise mask a divergence). Currently 23 pass, 1 JIT-COMPILE-FAILED
# (generator_simple — the C++ coroutine frontier).
check-runtimediff: $(GIMPLE_SOURCES) mojo_compiler.py myinterpreter.py mojo.py test_runtime_diff.py
	python3 checked_run.py check-runtimediff \
		$(foreach s,$(GIMPLE_SOURCES),--extra $(s)) \
		--extra mojo_compiler.py --extra myinterpreter.py --extra mojo.py \
		--extra test_runtime_diff.py \
		-- python3 test_runtime_diff.py

# Link-mode compile guard: builds real multi-file packages through
# `driver.compile_program` (the actual pipeline `mojo.py build` uses by
# default), not the `do_imports=False` single-translation-unit inline path
# every OTHER check-* target here (plus compile_stdlib.py/
# build_stdlib_dylib.py) uses instead — a link-mode-only bug in import/
# module-value registration is invisible to all of them. See
# test_link_mode.py's own module docstring.
check-linkmode: $(GIMPLE_SOURCES) mojo_compiler.py myinterpreter.py mojo.py driver.py test_link_mode.py
	python3 checked_run.py check-linkmode \
		$(foreach s,$(GIMPLE_SOURCES),--extra $(s)) \
		--extra mojo_compiler.py --extra myinterpreter.py --extra mojo.py --extra driver.py \
		--extra test_link_mode.py \
		-- python3 test_link_mode.py

# ── check-coro: the A3 stack-switch coroutine runtime (doc/COROUTINE.html) ───
# Standalone C unit tests for Layer 3 (context switch) and Layer 2 (coroutine
# runtime), each run against every Layer 3 backend at -O0 and -O2.
check-coro: runtime/mojo_coro.c runtime/mojo_coro.h runtime/mojo_coro_ctx.h \
            runtime/mojo_coro_ctx_aarch64.S runtime/mojo_coro_ctx_generic.c \
            runtime/test_mojo_coro.c runtime/test_mojo_coro_ctx.c \
            runtime/test_mojo_coro_exc_stub.c test_coro_runtime.py
	python3 checked_run.py check-coro --extra test_coro_runtime.py \
		--extra runtime/mojo_coro.c --extra runtime/mojo_coro_ctx_aarch64.S \
		--extra runtime/mojo_coro_ctx_generic.c \
		-- python3 test_coro_runtime.py

# Run all stdlib test and benchmark files through both the interpreter
# (mojo.py run) and the JIT compiler (mojo.py --jit).
check-stdlib: mojo_compiler.py
	python3 test_stdlib.py

# Run stdlib tests/benchmarks through interpreter only (mojo.py run).
check-stdlib-interp: mojo_compiler.py
	python3 test_stdlib.py --mode interp

# Run stdlib tests/benchmarks through JIT compiler only (mojo.py --jit).
check-stdlib-jit: mojo_compiler.py
	python3 test_stdlib.py --mode jit

check-gimple-runner:
	python3 test_gimple_runner.py

# Parse and validate entire stdlib (all .mojo files)
stdlib:
	python3 compile_stdlib.py

# ── Bootstrap stages ─────────────────────────────────────────────────────────
#
# Three-stage self-hosting verification with transitive-closure compilation:
#
#  Stage 1  Python mojo.py --dump-full mojo.py (single pass, all imports inline)
#             → stage1/mojo.ci  (clean, no deduplication needed)
#  stage2/mojo  GCC -fgimple compiles stage1/mojo.ci + runtime → compiled binary
#  Stage 2  stage2/mojo --dump mojo.py (single-file for individual validation)
#             → stage2/mojo.ci  (+ .tok .ast .pyi for all source files)
#  Stage 3  stage2/mojo --dump mojo.py  (idempotency: same binary, same output)
#             → stage3/mojo.ci  (+ .tok .ast .pyi for all source files)
#  verify   stage1 == stage2 == stage3  for all generated files

# ── Stage 1: Python drives the compiler ──────────────────────────────────────
# The --dump-full step is load-bearing: it's the single transitive-closure
# mojo.ci that stage2/mojo gets compiled from below, and must stay exactly as
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
	    out=$$(cd stage1 && PYTHONPATH=.. python3 ../mojo.py --dump "../$$1" 2>&1); \
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
	cd stage1 && PYTHONPATH=.. python3 ../mojo.py --dump-full ../$(MOJO_MAIN)

# ── mojoc: one-step self-host build (equivalent to stage2/mojo, no staging needed) ──
mojoc: $(MOJO_MAIN) $(RUNTIME_SRC) $(RUNTIME_HDR)
	@echo "=== Building mojoc from mojo.py ==="
	python3 mojo.py build mojo.py -o mojoc
	@echo "✓ mojoc ready"

# ── stage2/mojo: compile stage1 output into a real binary ────────────────────
# -ftrivial-auto-var-init=zero: the generated .ci reads some `char *`
# locals before every codegen path has assigned them (a real gap in the
# self-hosted metadata-dict/AST-field type inference, tracked separately
# — see bugs list / selfhost-shimless-progress memory). Without this
# flag GCC leaves such a read as classic uninitialized-stack garbage,
# which under MOJO_NO_SHIM=1 (this binary's OWN compiled codegen
# running, not the python3 shim) was a flaky SIGSEGV in
# `_declare_var`'s `mojo_str_cat` (strlen on a garbage pointer). Zero-
# init makes the read well-defined (NULL), which the codegen's own
# `_ptr_slot_in_range` guard already treats as "no known type" and
# falls back on safely. Inert for the STOCK (shimmed) bootstrap path —
# stage2/mojo's own compiled functions never run there at all, only
# under MOJO_NO_SHIM=1.
stage2/mojo: stage1 $(RUNTIME_SRC) $(RUNTIME_HDR)
	@mkdir -p stage2
	@echo "=== Compiling stage2/mojo from stage1/mojo.ci ==="
	$(BOOTSTRAP_CC) -fgimple -ftrivial-auto-var-init=zero -I runtime -x c \
	    $(BIG_STACK_LDFLAGS) \
	    -o stage2/mojo \
	    stage1/mojo.ci \
	    $(RUNTIME_SRC)
	@chmod +x stage2/mojo
	@echo "✓ stage2/mojo ready"

# ── Stage 2: compiled binary drives itself ────────────────────────────────────
# Runs every file's --dump (collect-all), but a per-file failure — a nonzero
# exit from `mojo --dump`, or the runtime's `mojo_unsupported_iter` warning
# (a real codegen gap that just doesn't SIGABRT the whole compiler, see
# runtime/mojo_runtime.c) — is tracked and fails the target at the end, so
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
	# ordering: the --dump loop above also writes mojo.ci (single-module,
	# do_imports=False, from `run_dump $(MOJO_MAIN)`), which would otherwise
	# clobber this transitive-closure .ci and leave `verify` comparing a full
	# closure (stage1/mojo.ci) against a single-module skeleton
	# (stage2/mojo.ci) — a real, permanent mismatch, not a codegen bug: this
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

# ── check-abshim: compiled compile_to_gimple vs Python, byte-for-byte ─────────
# `test_ab_shim.py` diffs `python3 mojo.py --dump X` against
# `MOJO_NO_SHIM=1 ./mojoc --dump X` for a 27-case corpus of small programs,
# both run from the repo root, compared byte-for-byte. All 27 are now
# byte-identical — this is the regression guard for that parity, and the
# green light for eventually removing the `python3 -c` subprocess shim
# from a self-hosted `mojoc` (runtime/mojo_runtime.c). The full `mojo.py`
# self-compile is not yet shimless (AttributeError: __file__), so
# `make bootstrap` itself still uses the shim.
check-abshim: mojoc $(GIMPLE_SOURCES) test_ab_shim.py
	python3 checked_run.py check-abshim --extra test_ab_shim.py -- python3 test_ab_shim.py

# ── Preflight checks ──────────────────────────────────────────────────────────
preflight:
	@test -f mojo_compiler.py || \
	    { echo "FAIL preflight: mojo_compiler.py missing"; exit 1; }
	@test -f gimple_codegen.py || \
	    { echo "FAIL preflight: gimple_codegen.py missing"; exit 1; }
	@test -f $(MOJO_MAIN) || \
	    { echo "FAIL preflight: $(MOJO_MAIN) missing"; exit 1; }
	@python3 -c "from mojo_compiler import tokenize, Parser; print('parser OK')"
	@python3 -c "import gimple_codegen; print('codegen OK')"
	@echo "✓ Preflight passed"

# ── Dev build (non-bootstrap quick compile) ───────────────────────────────────
# FORCE (empty recipe, always-out-of-date) rather than an explicit file list:
# mojo.ci is do_imports=True whole-program output of mojo.py's entire transitive
# closure (gimple_codegen.py, module_loader.py, mojo_compiler.py, ...) — any of
# those can change without mojo.py itself changing, and a stale mojo.ci built
# before such a change silently gets reused otherwise (confirmed: caused a
# bare-vs-qualified symbol mismatch after an unrelated codegen.py edit).
.PHONY: FORCE
FORCE:

mojo.ci: $(MOJO_MAIN) FORCE
	PYTHONPATH=. python3 mojo.py --dump-full $(MOJO_MAIN) 2>/dev/null

build/system.o: mojo.ci
	@mkdir -p build
	$(BOOTSTRAP_CC) -fgimple -I runtime -c -o $@ -x c mojo.ci

build/mojo_runtime.o: $(RUNTIME_SRC) $(RUNTIME_HDR)
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $(RUNTIME_SRC)

build/mojo: build/system.o build/mojo_runtime.o
	@mkdir -p build
	$(BOOTSTRAP_CC) $(BIG_STACK_LDFLAGS) -o $@ build/system.o build/mojo_runtime.o
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
