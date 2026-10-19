"""Evaluate the assistant against known data with one or more models.

    python manage.py assistant_eval
    python manage.py assistant_eval --models openai/gpt-oss-120b,openai/gpt-oss-20b
    python manage.py assistant_eval --only q1,fr1 --pause 6

Writes reports/assistant_eval/<timestamp>.md (readable) and .json (all scores).
Uses the configured provider (ASSISTANT_* settings); --models switches only the model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.assistant import providers
from apps.assistant.eval import data, report, runner
from apps.assistant.eval.questions import QUESTIONS

PRODUCTION_MODEL = "openai/gpt-oss-20b"
DEVELOPMENT_MODEL = "openai/gpt-oss-120b"


class Command(BaseCommand):
    help = "Run the assistant's question set against the configured model(s) and write a report."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--models", default="", help="Comma-separated model names.")
        parser.add_argument(
            "--only", default="", help="Question ids or tags (en, fr, ar, no_data...)."
        )
        parser.add_argument("--pause", type=float, default=4.0, help="Seconds between questions.")
        parser.add_argument("--temperature", type=float, default=0.0, help="0 = deterministic.")
        parser.add_argument("--production-model", default=PRODUCTION_MODEL)
        parser.add_argument("--development-model", default=DEVELOPMENT_MODEL)
        parser.add_argument(
            "--output", default=str(Path(settings.BASE_DIR) / "reports" / "assistant_eval")
        )

    def handle(self, *args: Any, **options: Any) -> None:
        wanted = {w.strip() for w in options["only"].split(",") if w.strip()}
        questions = [
            q
            for q in QUESTIONS
            if not wanted or q.id in wanted or q.language in wanted or set(q.tags) & wanted
        ]
        if not questions:
            raise CommandError("No question matches --only.")
        models = [m.strip() for m in options["models"].split(",") if m.strip()]
        models = models or [settings.ASSISTANT["MODEL"] or "fake-model"]

        self.stdout.write("Preparing the evaluation data (idempotent)…")
        world = data.build(sorted({q.line for q in questions}))
        started = datetime.now(UTC)
        scores: dict[str, list[runner.Score]] = {}
        for model in models:
            provider = providers.current_override() or providers.build_provider(
                model=model, temperature=options["temperature"]
            )
            self.stdout.write(f"Model {provider.model}: {len(questions)} questions")
            scores[provider.model] = runner.run(
                questions, world, provider, options["pause"], progress=self.stdout.write
            )

        out = Path(options["output"])
        out.mkdir(parents=True, exist_ok=True)
        stem = out / started.strftime("%Y%m%d-%H%M%S")
        text = report.render(
            scores, options["production_model"], options["development_model"], started
        )
        stem.with_suffix(".md").write_text(text, encoding="utf-8")
        stem.with_suffix(".json").write_text(
            json.dumps(
                {m: [s.as_dict() for s in ss] for m, ss in scores.items()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"Report: {stem.with_suffix('.md')}"))
