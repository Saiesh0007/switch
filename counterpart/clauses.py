"""The public contract: the clauses both sides can see. Holds no positions and no limits."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Clause:
    key: str
    title: str
    unit: str
    kind: str  # "number" or "choice"
    wording: str  # {value} is filled in once agreed
    why_it_matters: str
    choices: tuple[str, ...] = ()


CLAUSES: dict[str, Clause] = {
    clause.key: clause
    for clause in (
        Clause(
            "liability_cap",
            "Limitation of liability",
            "months of fees",
            "number",
            "Each party's total liability is capped at {value} months of fees paid under this Agreement.",
            "Sets how much of a serious failure's cost the vendor carries and the customer absorbs.",
        ),
        Clause(
            "payment_terms",
            "Payment terms",
            "days",
            "number",
            "Customer pays each undisputed invoice within {value} days of receipt.",
            "Moves working capital between the vendor's cash flow and the customer's.",
        ),
        Clause(
            "breach_notice",
            "Data breach notification",
            "hours",
            "number",
            "Vendor notifies Customer of a confirmed personal data breach within {value} hours.",
            "Trades the customer's regulatory clock against the vendor's time to investigate.",
        ),
        Clause(
            "uptime_sla",
            "Uptime commitment",
            "percent",
            "number",
            "Vendor maintains {value}% monthly uptime, with service credits for any shortfall.",
            "Sets the reliability the customer can plan around and the engineering cost behind it.",
        ),
        Clause(
            "governing_law",
            "Governing law",
            "",
            "choice",
            "This Agreement is governed by the laws of {value}.",
            "Decides which courts and body of law resolve a dispute.",
            ("Delaware", "New York", "England"),
        ),
    )
}
AGENDA: tuple[str, ...] = tuple(CLAUSES)


def parse_value(key: str, raw: str) -> float | str:
    """Strictly validate a value. Raises ValueError for anything outside the clause's type."""
    clause = CLAUSES[key]
    if clause.kind == "choice":
        if raw not in clause.choices:
            raise ValueError(f"{raw!r} is not an option for {key}")
        return raw
    value = float(raw)
    if not 0 < value < 100000:
        raise ValueError(f"{raw!r} is out of range for {key}")
    return value


def show(key: str, value: float | str) -> str:
    """Canonical text for a value, identical on every side of the wire."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def describe(key: str, value: float | str) -> str:
    unit = CLAUSES[key].unit
    return f"{show(key, value)} {unit}".strip()
