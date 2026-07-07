.PHONY: run demo check check-gimple check-runner check-gimple-runner check-modcache \
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

# Everyday green gate: the GIMPLE unit suite, the execution runner, and the
# module-cache end-to-end stages. The self-hosting bootstrap (stage1-3 +
# validate-all) is a separate, aspirational target — `make bootstrap` — because
# stage 2 has a known pre-existing codegen segfault (see IMPL.md); it is not
# gated into `check` so `check` stays a meaningful pass/fail signal.
check: check-gimple check-runner check-modcache check-selfhost
	@echo ""
	@echo "✓ check complete (gimple + runner + module-cache + self-host)"

check-gimple: gimple_codegen.py
	python3 test_gimple.py

# test_runner.py only existence-checks the prebuilt `build/mojo`, doesn't require it
# to be up-to-date. We build it here to ensure it exists for the test.
check-runner: build/mojo
	python3 test_runner.py

check-modcache:
	python3 test_module_cache.py

# Self-host compile guard: mojo.py must compile itself to a linked binary with
# zero GCC errors / ICEs / undefined symbols (the --jit mojo.py path, minus
# execution — the runtime still SIGSEGVs, a separate frontier). Locks compile+
# link cleanliness so it can't silently regress.
check-selfhost: gimple_codegen.py mojo_compiler.py
	python3 test_selfhost.py

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
stage1:
	@mkdir -p stage1
	@echo "=== Stage 1: Python → stage1/ ==="
	cd stage1 && PYTHONPATH=.. python3 ../mojo.py --dump-full ../$(MOJO_MAIN)
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
	    echo "✓ Stage 1 complete"; \
	else \
	    echo "✗ Stage 1 had failures (see FAILED lines above)"; exit 1; \
	fi

# ── mojoc: one-step self-host build (equivalent to stage2/mojo, no staging needed) ──
mojoc: $(MOJO_MAIN) $(RUNTIME_SRC) $(RUNTIME_HDR)
	@echo "=== Building mojoc from mojo.py ==="
	python3 mojo.py build mojo.py -o mojoc
	@echo "✓ mojoc ready"

# ── stage2/mojo: compile stage1 output into a real binary ────────────────────
stage2/mojo: stage1 $(RUNTIME_SRC) $(RUNTIME_HDR)
	@mkdir -p stage2
	@echo "=== Compiling stage2/mojo from stage1/mojo.ci ==="
	$(BOOTSTRAP_CC) -fgimple -I runtime -x c \
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
mojo.ci: $(MOJO_MAIN)
	PYTHONPATH=. python3 mojo.py --dump $(MOJO_MAIN) 2>/dev/null

build/system.o: mojo.ci
	@mkdir -p build
	$(BOOTSTRAP_CC) -fgimple -I runtime -c -o $@ -x c mojo.ci

build/mojo_runtime.o: $(RUNTIME_SRC) $(RUNTIME_HDR)
	$(BOOTSTRAP_CC) -I runtime -c -o $@ $(RUNTIME_SRC)

build/mojo: build/system.o build/mojo_runtime.o
	@mkdir -p build
	$(BOOTSTRAP_CC) -o $@ build/system.o build/mojo_runtime.o
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
