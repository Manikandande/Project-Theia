"""
Profiler agent — answers deep profiling questions about a specific table.

Examples:
  "Profile the Orders table"
  "What does the Customer table look like statistically?"
  "Are there any null values in the Invoice table?"

Combines stored profiling stats with live row-count verification,
then asks Theia to narrate the findings as a human analyst would.
"""

from __future__ import annotations

from catalog.data_profiler import profile_table
from rag.pipeline import _call_ollama
from security.guardrail import THEIA_SYSTEM_PROMPT


_PROFILE_EXPLAIN_PROMPT = """You are Theia, a data intelligence assistant. A user wants a profile of a database table.

Below is the statistical profile of the table. Narrate it as a thoughtful data analyst would:
- Describe what the table contains and its purpose
- Highlight column distributions, null rates, and value ranges
- Call out anything unusual or worth noting (high null %, skewed distributions, etc.)
- Speak in first person, plain English — no raw numbers dumps, tell the story

Table profile:
{profile_text}

Question: {question}
"""


def answer(question: str, schema: str, table: str) -> str:
    """
    Profile a specific table and return Theia's plain-English narration.

    Args:
        question: the original user question (for context in the prompt)
        schema:   schema alias e.g. "sales"
        table:    table name e.g. "Orders"
    """
    try:
        tp = profile_table(schema, table)
    except Exception as e:
        return (
            f"I wasn't able to profile the `{table}` table in the `{schema}` schema. "
            f"Error: {e}"
        )

    profile_text = tp.as_text()
    prompt = _PROFILE_EXPLAIN_PROMPT.format(
        profile_text=profile_text,
        question=question,
    )
    return _call_ollama(THEIA_SYSTEM_PROMPT, prompt)
