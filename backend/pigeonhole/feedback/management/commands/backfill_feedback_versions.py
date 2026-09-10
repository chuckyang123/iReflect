"""
@changelog
| Version | Description                          | Reference                                   |
| v1.0.0  | Initial implementation: backfill FeedbackInitialResponse history | REQ: 20260818-feedback-modification-tracking |
|         | Create version 1 snapshots for each student/question | TECH: 04_design_tech-design.md §3.4          |
/@changelog

@author chuckyang123
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from ...models import FeedbackAnswerVersion, FeedbackInitialResponse


class Command(BaseCommand):
    """Backfill FeedbackInitialResponse history into version 1 of FeedbackAnswerVersion
    for each student/question.

    Idempotent design: students/questions that already have version 1 are skipped,
    so the command can be safely re-run.
    """

    help = "Backfill FeedbackInitialResponse history as version 1 of FeedbackAnswerVersion."

    def handle(self, *args, **options):
        backfilled = 0
        skipped = 0

        initial_responses = FeedbackInitialResponse.objects.select_related(
            "course", "milestone", "template", "creator"
        ).order_by("course", "milestone", "template", "creator", "question")

        for initial_response in initial_responses:
            version_exists = FeedbackAnswerVersion.objects.filter(
                course=initial_response.course,
                milestone=initial_response.milestone,
                template=initial_response.template,
                creator=initial_response.creator,
                question=initial_response.question,
                version_number=1,
            ).exists()

            if version_exists:
                skipped += 1
                continue

            with transaction.atomic():
                FeedbackAnswerVersion.objects.create(
                    course=initial_response.course,
                    milestone=initial_response.milestone,
                    template=initial_response.template,
                    creator=initial_response.creator,
                    name=initial_response.name,
                    question=initial_response.question,
                    answer_content=initial_response.initial_response,
                    version_number=1,
                    genre=initial_response.genre,
                    mechanic=initial_response.mechanic,
                )
            backfilled += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill complete: {backfilled} created, {skipped} skipped (already exist)."
            )
        )
