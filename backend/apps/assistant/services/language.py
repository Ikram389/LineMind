"""Which language a question is in, and the server's own messages in that language.

When the model fails (busy, unreachable, invalid tool calls...), LineMind writes the reply
itself, so it must not depend on the model to pick the language.
"""

from __future__ import annotations

import re

ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
LETTER = re.compile(r"[^\W\d_]")
FRENCH_ACCENTS = re.compile(r"[àâçéèêëîïôûùüÿœæ]", re.IGNORECASE)
FRENCH_WORDS = frozenset(
    """le la les des du une un est sont quel quelle quels quelles combien pourquoi quand
    où comment cette ce ces sur dans avec pour par pendant depuis hier aujourd semaine
    mois arrêt arrêts ligne équipe défauts taux qui que a-t-il y-a-t-il après avant
    moins""".split()
)

LANGUAGES = ("en", "fr", "ar")


def detect(text: str) -> str:
    letters = LETTER.findall(text)
    if letters and sum(1 for c in letters if ARABIC.match(c)) / len(letters) >= 0.3:
        return "ar"
    words = re.findall(r"[a-zà-ÿœæ'-]+", text.lower())
    hits = sum(
        1 for w in words if w.strip("'-") in FRENCH_WORDS or w.startswith(("l'", "d'", "qu'"))
    )
    if hits >= 2 or (hits >= 1 and FRENCH_ACCENTS.search(text)):
        return "fr"
    return "en"


MESSAGES: dict[str, dict[str, str]] = {
    "busy": {
        "en": "The assistant is busy. Please try again in a moment.",
        "fr": "L'assistant est occupé. Réessayez dans un instant.",
        "ar": "المساعد مشغول حاليًا. يُرجى المحاولة مرة أخرى بعد قليل.",
    },
    "unreachable": {
        "en": "The assistant can't reach its language model right now.",
        "fr": "L'assistant ne parvient pas à joindre son modèle de langage pour le moment.",
        "ar": "لا يستطيع المساعد الوصول إلى نموذج اللغة حاليًا.",
    },
    "no_tool_calling": {
        "en": "The configured language model cannot use LineMind's data tools, so the "
        "assistant is unavailable.",
        "fr": "Le modèle de langage configuré ne sait pas utiliser les outils de données de "
        "LineMind : l'assistant est indisponible.",
        "ar": "نموذج اللغة المُعدّ لا يستطيع استخدام أدوات بيانات LineMind، لذا فالمساعد غير متاح.",
    },
    "timeout": {
        "en": "The assistant took too long to answer. Please try again or ask a simpler question.",
        "fr": "L'assistant a mis trop de temps à répondre. Réessayez ou posez une question plus "
        "simple.",
        "ar": "استغرق المساعد وقتًا طويلًا للإجابة. يُرجى المحاولة مرة أخرى أو طرح سؤال أبسط.",
    },
    "tool_limit": {
        "en": "I needed too many steps to answer this. Please ask a narrower question "
        "(one line, one period).",
        "fr": "Il m'a fallu trop d'étapes pour répondre. Posez une question plus précise "
        "(une ligne, une période).",
        "ar": "احتجتُ إلى خطوات كثيرة جدًا للإجابة. يُرجى طرح سؤال أدق (خط واحد وفترة واحدة).",
    },
    "invalid_tool_calls": {
        "en": "Sorry, I couldn't retrieve the data needed to answer this. Please rephrase the "
        "question, for example with the line and the period.",
        "fr": "Désolé, je n'ai pas pu récupérer les données nécessaires pour répondre. "
        "Reformulez la question, par exemple avec la ligne et la période.",
        "ar": "عذرًا، لم أتمكن من جلب البيانات اللازمة للإجابة. يُرجى إعادة صياغة السؤال، "
        "مثلًا بذكر الخط والفترة.",
    },
    "failed": {
        "en": "Sorry, something went wrong while answering. Please try again.",
        "fr": "Désolé, une erreur s'est produite pendant la réponse. Réessayez.",
        "ar": "عذرًا، حدث خطأ أثناء الإجابة. يُرجى المحاولة مرة أخرى.",
    },
}


def message(code: str, language: str) -> str:
    texts = MESSAGES.get(code, MESSAGES["failed"])
    return texts.get(language, texts["en"])
