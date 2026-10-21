"""
@changelog
| Version | Description                                          | Reference                                     |
| v1.0.0  | Initial implementation: LightRAG proxy + mock fallback | DEV: local playtest without LightRAG service |
| v1.1.0  | Mock fallback restricted to DEBUG; production returns 503 instead of simulated scores | PRD: production fails loudly |
| v1.2.0  | Distinguish the two 503 causes: an unset LIGHTRAG_URL and a   | BUG: playtest-503-misleading-detail          |
|         | configured-but-unreachable LightRAG previously returned the   |                                             |
|         | same "LIGHTRAG_URL is not configured" detail, sending whoever |                                             |
|         | was debugging after the wrong setting.                       |                                             |
| v1.3.0  | Detect LightRAG's empty-context fallback: an empty           | BUG: playtest-503-misleading-detail          |
|         | knowledge graph answered 200 with a canned reply, which      |                                             |
|         | only surfaced as a missing score block and sent debugging    |                                             |
|         | after the wrong thing. Reported as its own cause, and v7     |                                             |
|         | is not called at all.                                       |                                             |
/@changelog

@author chuckyang123
"""
import logging
import os

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from .v7 import V7FeedbackError, generate_feedback, replace_playtest_advice

logger = logging.getLogger(__name__)

# LightRAG service URL, e.g. http://localhost:9621. When unset, the endpoint
# falls back to a deterministic mock in DEBUG so the full
# "generate feedback -> version history" flow can still be demonstrated; in
# production it returns 503 instead of simulated feedback.
LIGHTRAG_API_KEY = os.getenv("LIGHTRAG_API_KEY", "your-secure-api-key-here")


def _mock_playtest_feedback(query: str) -> str:
    """Deterministic mock for local demo. Deliberately carries NO numeric
    scores so students never see a score leaking through the mock
    (PRD 20260824-playtest-score-visibility); real LightRAG output is stripped
    student-side by stripScoresFromMarkdown instead."""
    preview = " ".join(query.split())[:200]
    return (
        "**Professor Feedback:** "
        f"(Local mock mode \u2013 LightRAG service not reachable) Simulated "
        f"feedback for: \"{preview}\"\n\n"
        "**Final Summary:** Your reflection was logged; rerun with the "
        "LightRAG service (docker compose) for knowledge-graph feedback."
    )


def _request_reason(exc):
    """Short, non-sensitive reason for a failed LightRAG call. The full
    exception (which can carry the internal service URL) stays in the log."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is not None:
        return f"HTTP {status_code}"
    return exc.__class__.__name__


NO_CONTEXT = "no-context"
# LightRAG answers with this canned text when retrieval finds nothing, i.e. its
# knowledge graph is empty. It is still a 200 response, so without this check
# the empty graph only surfaces further down as a missing score block, which
# sends whoever is debugging after the wrong thing entirely.
NO_CONTEXT_MARKER = "[no-context]"
NO_CONTEXT_REPLY = "Sorry, I'm not able to provide an answer to that question."


class _NoContextError(Exception):
    """Internal signal: LightRAG answered with its empty-context fallback."""


class PlaytestFeedbackView(APIView):
    """Proxies playtest feedback requests to the LightRAG /query endpoint.

    Both production and local requests pass here. LightRAG still determines
    scores; only the student advice is replaced by the frozen v7 pipeline.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        query = request.data.get("query", "")
        mode = request.data.get("mode", "hybrid")
        question = request.data.get("question")
        answer = request.data.get("answer")
        if not isinstance(query, str) or not query.strip():
            return Response({"detail": "query is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        lightrag_url = os.getenv("LIGHTRAG_URL")
        lightrag_failure = None
        if lightrag_url:
            if (not isinstance(question, str) or not question.strip()
                    or not isinstance(answer, str) or not answer.strip()):
                return Response({"detail": "question and answer are required for v7 feedback."},
                                status=status.HTTP_400_BAD_REQUEST)
            try:
                resp = requests.post(
                    f"{lightrag_url}/query",
                    json={"query": query, "mode": mode},
                    headers={"X-API-Key": LIGHTRAG_API_KEY},
                    timeout=60,
                )
                resp.raise_for_status()
                graded = resp.json().get("response", "")
                if (NO_CONTEXT_MARKER in graded
                        or graded.strip().startswith(NO_CONTEXT_REPLY)):
                    raise _NoContextError()
            except _NoContextError:
                logger.warning("LightRAG returned no context for the playtest query.")
                lightrag_failure = NO_CONTEXT
            except requests.RequestException as exc:
                logger.warning("LightRAG unavailable (%s).", exc)
                lightrag_failure = (
                    f"the LightRAG request failed ({_request_reason(exc)})"
                )
            else:
                try:
                    # Do not feed score-driven advice or KG requirements into v7.
                    # A missing provider is not permission to present the old prompt as v7.
                    feedback, _, _ = generate_feedback(question, answer)
                    return Response({"response": replace_playtest_advice(graded, feedback),
                                     "feedback_prompt_version": "T1_v3+T2_v7_guided"})
                except V7FeedbackError as exc:
                    # v7 re-raises validation failures without logging them, so
                    # without this the only trace of a rejected generation is
                    # Django's generic "Service Unavailable: /api/playtest/".
                    # These messages are fixed strings and carry no student text.
                    logger.warning("v7 feedback rejected (%s).", exc)
                    return Response({"detail": str(exc)},
                                    status=status.HTTP_503_SERVICE_UNAVAILABLE)
        else:
            logger.warning("LIGHTRAG_URL is not set.")

        if settings.DEBUG:
            return Response({"response": _mock_playtest_feedback(query)})

        # Production must fail loudly instead of serving simulated feedback.
        # Name the real cause: an unset LIGHTRAG_URL and a LightRAG that is
        # configured but unreachable need different fixes, and reporting the
        # former for both sends whoever is debugging after the wrong setting.
        if lightrag_failure is None:
            detail = ("LIGHTRAG_URL is not configured. Playtest feedback "
                      "generation is unavailable in this environment.")
        elif lightrag_failure == NO_CONTEXT:
            detail = ("LightRAG returned no context for this query: its "
                      "knowledge graph has no indexed content. Playtest "
                      "feedback generation is unavailable until documents are "
                      "ingested into LightRAG.")
        else:
            detail = ("LIGHTRAG_URL is configured but " + lightrag_failure +
                      ". Playtest feedback generation is unavailable while "
                      "that service cannot be reached.")
        return Response(
            data={"detail": detail},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
