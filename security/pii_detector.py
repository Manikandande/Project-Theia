"""
PII detector — masks sensitive data before it reaches the LLM.

Uses Microsoft Presidio with spaCy to detect and anonymise:
  PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN,
  IP_ADDRESS, URL, LOCATION, DATE_TIME (optional), NRP

The original question is never stored or sent to Ollama — only the
masked version is. The mapping (what was replaced) is kept in memory
for the duration of the request and then discarded.
"""

from __future__ import annotations

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig


_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "IP_ADDRESS",
    "URL",
    "LOCATION",
    "NRP",           # Nationality, Religion, Political group
]


@lru_cache(maxsize=1)
def _get_engines() -> tuple[AnalyzerEngine, AnonymizerEngine]:
    analyzer = AnalyzerEngine()
    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


def mask(text: str) -> tuple[str, bool]:
    """
    Scan text for PII and replace it with type placeholders.

    Returns:
        masked_text — the text with PII replaced (e.g. "[PERSON]")
        pii_found   — True if any PII was detected
    """
    analyzer, anonymizer = _get_engines()

    results = analyzer.analyze(text=text, entities=_ENTITIES, language="en")
    if not results:
        return text, False

    operators = {
        entity: OperatorConfig("replace", {"new_value": f"[{entity}]"})
        for entity in _ENTITIES
    }
    anonymized = anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=operators,
    )
    return anonymized.text, True


def contains_pii(text: str) -> bool:
    """Quick check — returns True if any PII is detected."""
    analyzer, _ = _get_engines()
    results = analyzer.analyze(text=text, entities=_ENTITIES, language="en")
    return len(results) > 0


if __name__ == "__main__":
    samples = [
        "Who bought something from john.doe@example.com?",
        "Show me orders for customer John Smith in London",
        "What is the average UnitPrice in InvoiceLine?",
        "Find records with SSN 123-45-6789",
    ]
    for s in samples:
        masked, found = mask(s)
        status = "PII FOUND" if found else "clean"
        print(f"[{status}] {masked}")
