"""Run all stdlib test and benchmark files through interpreter and JIT compiler
in parallel (20 workers by default).

Invoked via `make check-stdlib` or directly: `python3 test_stdlib.py`.
"""
import os, sys, subprocess, concurrent.futures

HERE = os.path.dirname(os.path.abspath(__file__))
STDLIB = "/Users/mrs/net/chatgpt/claude/modular/mojo/stdlib"
MOJO = os.path.join(HERE, "fire.py")
MAX_WORKERS = 20


def find_files():
    files = []
    for root in [os.path.join(STDLIB, "test"), os.path.join(STDLIB, "benchmarks")]:
        for dirpath, _, filenames in os.walk(root):
            for f in filenames:
                if f.endswith(".mojo") and not f.endswith("_utils.mojo"):
                    if f.startswith("test_") or f.startswith("bench_"):
                        files.append(os.path.join(dirpath, f))
    return sorted(files)


def run_one(mode, fpath):
    cmd = [sys.executable, MOJO, "run" if mode == "interp" else "--jit", fpath]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=120, cwd=HERE)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            return True, ""
        elif "AssertionError" in out or "test(s) failed" in out:
            return False, "test assertions failed"
        else:
            return False, (r.stderr or "").strip()[-200:]
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


def run_mode(mode, files, label):
    total = len(files)
    print(f"\n{'=' * 60}")
    print(f"Running {total} files with {label} ({MAX_WORKERS} workers)...")
    print(f"{'=' * 60}")

    ok = fail = 0
    completed = 0
    results = [None] * total

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        fut_map = {ex.submit(run_one, mode, fpath): i for i, (fpath,) in enumerate(zip(files))}
        for fut in concurrent.futures.as_completed(fut_map):
            i = fut_map[fut]
            passed, detail = fut.result()
            results[i] = (passed, detail)
            completed += 1
            if passed:
                ok += 1
            else:
                fail += 1
            if completed % 50 == 0 or completed == total:
                print(f"  [{completed}/{total}] checkpoint: P={ok} F={fail}")

    for i, (fpath, (passed, detail)) in enumerate(zip(files, results)):
        relpath = os.path.relpath(fpath, STDLIB)
        tag = "PASS" if passed else "FAIL"
        if passed:
            print(f"  [{i+1}/{total}] {tag}  {relpath}")
        else:
            suffix = "" if not detail else f"  ({detail})"
            print(f"  [{i+1}/{total}] {tag}  {relpath}{suffix}")

    print(f"\nResults for {label}: PASS={ok} FAIL={fail}")
    return ok, fail


def main():
    if not os.path.exists(STDLIB):
        print(f"ERROR: stdlib not found at {STDLIB}", file=sys.stderr)
        sys.exit(1)

    files = find_files()
    if not files:
        print("ERROR: no test/benchmark files found", file=sys.stderr)
        sys.exit(1)

    modes = []
    if len(sys.argv) > 1 and sys.argv[1].startswith("--mode="):
        m = sys.argv[1].split("=", 1)[1]
        if m == "interp":
            modes = [("interp", "interpreter (fire.py run)")]
        elif m == "jit":
            modes = [("jit", "JIT compiler (fire.py --jit)")]
        else:
            print(f"ERROR: unknown mode {m!r}", file=sys.stderr)
            sys.exit(1)
    else:
        modes = [("interp", "interpreter (fire.py run)"),
                 ("jit", "JIT compiler (fire.py --jit)")]

    print(f"Found {len(files)} test/benchmark files in stdlib")
    print(f"Stdlib root: {STDLIB}")

    total_pass = total_fail = 0
    for mode_id, label in modes:
        ok, fail = run_mode(mode_id, files, label)
        total_pass += ok
        total_fail += fail

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {total_pass} passed, {total_fail} failed")
    print(f"{'=' * 60}")
    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()
