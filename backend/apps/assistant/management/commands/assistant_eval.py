"""Evaluate the assistant against known data with one or more models.

    python manage.py assistant_eval
    python manage.py assistant_eval --models openai/gpt-oss-120b,openai/gpt-oss-20b
    python manage.py assistant_eval --only q1,fr1 --pause 6
    python manage.py assistant_eval --resume reports/assistant_eval/<stamp>.json

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
        parser.add_argument(
            "--resume",
            default="",
            help="A previous report .json: keep its answers, run only what is missing or not run.",
        )
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
        previous: dict[str, dict[str, runner.Score]] = {}
        if options["resume"]:
            path = Path(options["resume"])
            if not path.exists():
                raise CommandError(f"No report at {path}.")
            raw = json.loads(path.read_text(encoding="utf-8"))
            previous = {
                m: {row["question"]: runner.from_dict(row) for row in rows}
                for m, rows in raw.items()
            }
            models = list(dict.fromkeys([*previous, *models])) if not options["models"] else models

        self.stdout.write("Preparing the evaluation data (idempotent)…")
        world = data.build(sorted({q.line for q in questions}))
        started = datetime.now(UTC)
        scores: dict[str, list[runner.Score]] = {}
        for model in models:
            provider = providers.current_override() or providers.build_provider(
                model=model, temperature=options["temperature"]
            )
            done = previous.get(provider.model, {})
            kept = sum(1 for s in done.values() if s.status != runner.NOT_RUN)
            self.stdout.write(
                f"Model {provider.model}: {len(questions)} questions ({kept} kept from --resume)"
            )
            scores[provider.model] = runner.run(
                questions, world, provider, options["pause"], progress=self.stdout.write, done=done
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
