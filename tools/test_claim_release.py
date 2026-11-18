#!/usr/bin/env python3
"""A finished task whose branch has unmerged commits releases its claim after repeated failed landings.

Run: python3 tools/test_claim_release.py
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import formal_feed as F

MAX_ATTEMPTS = 3


def test_task_with_unlanded_branch_releases_after_max_attempts():
    """A task with exited-ok and unlanded=True is superseded after MAX_ATTEMPTS passes, releasing its claim."""
    with tempfile.TemporaryDirectory() as tmp:
        C.ctl_dir = lambda: tmp
        C.MAIN = tmp

        # Create a minimal task registry (no git needed - just test state transitions)
        task_name = "bug-test-unlanded"
        task = {"state": "exited-ok", "branch": "work/bug-test-unlanded", "claims": ["bug:TEST_unlanded"],
                "worktree": "/tmp", "pid": 0}
        with C.registry() as reg:
            reg[task_name] = task

        # Run release_finished() MAX_ATTEMPTS times
        for i in range(MAX_ATTEMPTS):
            F.release_finished()
            state = json.load(open(os.path.join(tmp, "tasks.json")))[task_name]
            attempts = state.get("landing_attempts", 0)
            assert attempts == i + 1, f"Pass {i}: Expected landing_attempts={i+1}, got {attempts}"
            if i < MAX_ATTEMPTS - 1:
                assert state["state"] == "exited-ok", f"Pass {i}: Expected state=exited-ok, got {state['state']}"
            else:
                assert state["state"] == "superseded", f"Pass {MAX_ATTEMPTS-1}: Expected state=superseded, got {state['state']}"

        # Verify claim is released (holds_claims returns False for superseded)
        final_state = json.load(open(os.path.join(tmp, "tasks.json")))[task_name]
        assert not C.holds_claims(final_state), "Claim should be released after superseding"
        print("PASS: task with unlanded branch releases claim after MAX_LANDING_ATTEMPTS")
        return True


def test_task_with_landed_branch_marks_integrated():
    """A task with exited-ok and _unlanded=False is marked integrated immediately (no attempts)."""
    with tempfile.TemporaryDirectory() as tmp:
        C.ctl_dir = lambda: tmp
        C.MAIN = tmp

        task_name = "bug-test-landed"
        task = {"state": "exited-ok", "branch": "work/bug-test-landed", "claims": ["bug:TEST_landed"],
                "worktree": "/tmp", "pid": 0}
        with C.registry() as reg:
            reg[task_name] = task

        # _unlanded should return False for landed branch
        # We need to set up git repo so _unlanded can check
        import subprocess as sp
        sp.run(["git", "init", "-q"], cwd=tmp)
        sp.run(["git", "checkout", "-b", "work/bug-test-landed"], cwd=tmp)
        sp.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=tmp)
        sp.run(["git", "checkout", "master"], cwd=tmp)

        # Now run release_finished
        F.release_finished()

        final_state = json.load(open(os.path.join(tmp, "tasks.json")))[task_name]
        assert final_state["state"] == "integrated", f"Expected state=integrated, got {final_state['state']}"
        print("PASS: task with landed branch marks integrated immediately")
        return True


def main():
    ok = True
    ok &= test_task_with_unlanded_branch_releases_after_max_attempts()
    ok &= test_task_with_landed_branch_marks_integrated()
    print(f"{'all passed' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())