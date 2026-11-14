"""Quick checks proving SUITE_silentnoop-part1 replan parts are done."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_part1_capture():
    evidence = ROOT / "bugs" / "SUITE_silentnoop-part1-run.txt"
    assert evidence.is_file(), f"missing {evidence}"
    text = evidence.read_text()
    assert "Command:" in text, "evidence must record the command that was run"
    assert "Exit code:" in text, "evidence must record the exit code"
    assert text.strip(), "evidence must not be empty"


def test_part1_classify():
    findings = ROOT / "bugs" / "SUITE_silentnoop-part1-findings.md"
    assert findings.is_file(), f"missing {findings}"
    text = findings.read_text()
    assert "## Classification" in text
    assert "## Cases" in text
    # must name one of the allowed failure modes
    lowered = text.lower()
    assert (
        "timeout" in lowered or "build error" in lowered or "diverg" in lowered
    ), "classification must state timeout, build error, or case divergence"
