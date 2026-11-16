#!/usr/bin/env python3
"""Tests for tools/procrun.py and tools/memcap.py (bug:UNTESTED §5).

procrun owns the RSS measurement and the kill — the two things memcap exists to
get right — and had no test at all. These pin the pure parts against injected
process tables (no `ps` dependence), and the kill / ceiling paths against real
short-lived processes.
"""
import os
import signal
import subprocess
import sys
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
import procrun  # noqa: E402

GB = 1024 ** 3


# ── ps_time ──────────────────────────────────────────────────────────────────
def test_ps_time_shapes():
    assert procrun.ps_time("0:05") == 5.0                  # mm:ss
    assert procrun.ps_time("1:02:03") == 3723.0            # hh:mm:ss
    assert procrun.ps_time("2-01:00:00") == 2 * 86400 + 3600   # dd-hh:mm:ss
    assert abs(procrun.ps_time("0:01.50") - 1.5) < 1e-9    # fractional seconds


def test_ps_time_garbage_is_zero_not_raise():
    assert procrun.ps_time("x:y") == 0.0
    assert procrun.ps_time("zz-01:00:00") == 0.0


# ── ps_snapshot parsing ─────────────────────────────────────────────────────
def test_ps_snapshot_parses_and_skips_malformed():
    fake = ("  10     1   2048  0:03.00  10\n"
            "  11    10   4096  1:00:00  10\n"
            "garbage line\n"
            "  12    10   notanumber 0:01 12\n")

    class R:
        stdout = fake

    with mock.patch.object(procrun.subprocess, "run", return_value=R()):
        ppid, rss, cpu, pgid = procrun.ps_snapshot()
    assert set(ppid) == {10, 11}
    assert ppid[11] == 10 and rss[11] == 4096
    assert cpu[11] == 3600.0 and pgid[10] == 10


def test_ps_snapshot_unavailable_is_empty_not_zero():
    with mock.patch.object(procrun.subprocess, "run",
                           side_effect=OSError("no ps")):
        assert procrun.ps_snapshot() == ({}, {}, {}, {})


# ── tree accounting over an injected table ──────────────────────────────────
# 1 -> 2 -> 3 is the tree under test; 4 is an unrelated process; RSS in KB.
PPID = {1: 0, 2: 1, 3: 2, 4: 0}
RSS = {1: 1000, 2: 2000, 3: 3000, 4: 9999}
CPU = {1: 1.0, 2: 2.0, 3: 4.0, 4: 100.0}
PGID = {1: 1, 2: 1, 3: 1, 4: 4}


def test_tree_pids_is_root_and_descendants_only():
    assert sorted(procrun.tree_pids(1, PPID)) == [1, 2, 3]
    assert procrun.tree_pids(99, PPID) == []


def test_tree_usage_sums_cpu_and_rss_over_the_subtree():
    spent, total, count = procrun.tree_usage(1, PPID, RSS, CPU)
    assert count == 3
    assert abs(spent - 7.0) < 1e-9                  # 1+2+4, not the unrelated 100
    assert total == (1000 + 2000 + 3000) * 1024     # KB -> bytes, subtree only


def test_tree_usage_unique_is_max_rss_not_sum():
    spent, peak, count = procrun.tree_usage_unique(1, PPID, RSS, CPU)
    assert count == 3
    assert abs(spent - 7.0) < 1e-9
    assert peak == 3000 * 1024                      # the largest single process


def test_tree_usage_missing_root_is_zero():
    assert procrun.tree_usage(99, PPID, RSS, CPU) == (0.0, 0, 0)
    assert procrun.tree_usage_unique(99, PPID, RSS, CPU) == (0.0, 0, 0)


def test_tree_usage_without_cpu_table_reports_zero_cpu():
    # Documented: passing ppid/rss but not cpu gives 0.0 CPU, not an error.
    spent, _total, count = procrun.tree_usage(1, PPID, RSS, None)
    assert spent == 0.0 and count == 3


def test_group_pids_selects_group_and_honours_skip():
    tables = (PPID, RSS, CPU, PGID)
    assert sorted(procrun.group_pids(1, skip=(2,), tables=tables)) == [1, 3]
    assert procrun.group_pids(4, tables=tables) == [4]


# ── memcap's printed verdict ────────────────────────────────────────────────
BREACH_OUT = ("memcap: x -- ceiling 2.0 GB across the process tree\n"
              "\nmemcap: BREACH  2.6 GB > 2.0 GB ceiling (130%), 3 procs -- killing x\n"
              "memcap: peak observed before the kill: 2.4 GB\n")
DONE_OUT = ("memcap: x -- ceiling 2.0 GB across the process tree\n"
            "memcap: done, peak 0.5 GB across up to 2 procs (ceiling 2.0 GB), "
            "child exit 0\n")


def test_memcap_verdict_reads_breach_and_last_peak():
    assert procrun.memcap_verdict(BREACH_OUT) == (True, 2.4)


def test_memcap_verdict_done_is_not_a_breach():
    assert procrun.memcap_verdict(DONE_OUT) == (False, 0.5)


def test_memcap_verdict_workload_exit_125_is_not_a_breach():
    # A workload that exits 125 by itself printed no memcap line; it must not
    # be filed as a memory cap.
    assert procrun.memcap_verdict("error: something\n") == (False, None)
    assert procrun.memcap_verdict("") == (False, None)


def test_memcap_accounted_and_wrapper_died():
    assert procrun.memcap_accounted(DONE_OUT)
    assert not procrun.memcap_wrapper_died(DONE_OUT)
    banner_only = "memcap: x -- ceiling 2.0 GB across the process tree\n"
    assert procrun.memcap_wrapper_died(banner_only)
    assert not procrun.memcap_accounted(banner_only)
    assert not procrun.memcap_wrapper_died("")


# ── kill paths against real processes ───────────────────────────────────────
def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); reap check via ps state.
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                        capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


def test_kill_tree_takes_down_grandchildren():
    # sh -> sleep: the grandchild must die with the root, and the root is reaped.
    p = subprocess.Popen(["sh", "-c", "sleep 60 & echo $!; wait"],
                         stdout=subprocess.PIPE, start_new_session=True, text=True)
    child = int(p.stdout.readline().strip())
    time.sleep(0.2)
    assert _alive(child)
    procrun.kill_tree(p.pid)
    deadline = time.time() + 5
    while _alive(child) and time.time() < deadline:
        time.sleep(0.05)
    assert not _alive(child), "grandchild survived kill_tree"


def test_spawn_timeout_kills_the_whole_tree():
    run = procrun.spawn(["sh", "-c", "sleep 60 & wait"], timeout=1)
    assert run.timed_out and run.rc is None


def test_spawn_reports_exit_code_and_output():
    run = procrun.spawn([sys.executable, "-c", "print('hi'); raise SystemExit(3)"])
    assert not run.timed_out and run.rc == 3
    assert "hi" in run.out


# ── memcap end to end ───────────────────────────────────────────────────────
MEMCAP = os.path.join(HERE, "tools", "memcap.py")


def test_memcap_under_ceiling_passes_child_exit_through():
    run = procrun.spawn([sys.executable, MEMCAP, "--limit-gb", "100", "--label", "ok",
                         "--", sys.executable, "-c", "raise SystemExit(7)"])
    assert run.rc == 7
    assert memcap_done(run.out)
    assert procrun.memcap_verdict(run.out)[0] is False


def test_memcap_breach_kills_and_reports_resource_failure():
    # A ceiling far below a bare interpreter's RSS must trip on the first poll.
    run = procrun.spawn([sys.executable, MEMCAP, "--limit-gb", "0.0001", "--label", "hog",
                         "--", sys.executable, "-c", "import time; time.sleep(30)"],
                        timeout=60)
    assert run.rc == 125 and not run.timed_out
    breached, peak = procrun.memcap_verdict(run.out)
    assert breached is True and peak is not None
    assert "RESOURCE failure" in run.out


def memcap_done(out):
    return "memcap: done" in out


TESTS = [v for k, v in sorted(globals().items())
         if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"PASS procrun/memcap: {len(TESTS)} tests" if not failed
          else f"{failed} of {len(TESTS)} procrun/memcap test(s) failed")
    sys.exit(1 if failed else 0)
