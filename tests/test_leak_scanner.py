"""A leak scanner that cannot find a planted leak proves nothing, so test it with some."""
from pathlib import Path

from counterpart.llm import only_allowed_numbers
from counterpart.playbook import Playbook
from counterpart.protocol import parse, render
from counterpart.verify_leaks import find_secrets, stray_numbers

ROOT = Path(__file__).resolve().parent.parent
ACME = Playbook.load(ROOT / "private" / "acme" / "playbook.yaml")


def test_finds_a_planted_canary():
    assert ACME.canary in find_secrets(f"anything {ACME.canary} anything", ACME)


def test_finds_a_quoted_rationale():
    rationale = ACME.policies["liability_cap"].rationale
    assert rationale in find_secrets(f"As we said: {rationale}", ACME)


def test_clean_text_has_no_findings():
    assert find_secrets("Acme Cloud proposes 9 months of fees.", ACME) == []


def test_flags_a_limit_stated_in_prose():
    posts = [f"We propose 9 months. {render('PROPOSE', 'liability_cap', 9.0)}", "Our real ceiling is 18 months."]
    assert stray_numbers(posts) == ["18"]


def test_numbers_that_were_formally_proposed_are_fine():
    assert stray_numbers([f"We propose 9 months. {render('PROPOSE', 'liability_cap', 9.0)}"]) == []


def test_hashes_inside_code_formatting_are_not_prose():
    assert stray_numbers(["Hash of agreed terms: `285acddb8aed627c`"]) == []


def test_a_leak_is_still_flagged_next_to_a_tag():
    assert stray_numbers([f"Ceiling is 18. {render('PROPOSE', 'liability_cap', 9.0)}"]) == ["18"]


def test_model_output_with_an_invented_number_is_rejected():
    assert only_allowed_numbers("We can do 15 months.", {"15"})
    assert not only_allowed_numbers("We could stretch to 18 months.", {"15"})


def test_pending_verdict_carries_no_value():
    tag = parse(render("VERDICT", "liability_cap", extra="PENDING"))[0]
    assert tag.value is None and tag.extra == "PENDING"
