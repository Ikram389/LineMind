"""Tidying a model's answer before it is checked and stored.

Models cite sources in their own formats: "【1】", "【1†L1-L3】", or even "⟦1⟧" (copying the
delimiters LineMind puts around user-written text). Everything becomes "[1]", and ⟦ ⟧ never
reaches a stored answer. The number check runs on the cleaned text, so a source number is
never mistaken for a figure.
"""

from __future__ import annotations

import re

FULLWIDTH_CITATION = re.compile(r"【\s*(\d+)\s*(?:†[^】]*)?】")
DELIMITED_NUMBER = re.compile(r"⟦\s*(\d+)\s*⟧")
DELIMITED_TEXT = re.compile(r"⟦([^⟧]*)⟧")


def clean_answer(text: str) -> str:
    text = FULLWIDTH_CITATION.sub(r"[\1]", text)
    text = DELIMITED_NUMBER.sub(r"[\1]", text)
    text = DELIMITED_TEXT.sub(r"\1", text)
    return text.replace("⟦", "").replace("⟧", "").strip()
