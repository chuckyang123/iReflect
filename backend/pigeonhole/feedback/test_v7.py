"""No-network v7 integration contracts; run with python -m unittest feedback.test_v7."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from . import v7


def fixture(missing=False):
    q = "State a feeling and a plan."
    c = "I was nervous." if missing else "I was nervous. I will practise with a partner."
    rows = []
    for i, (requirement, phrase) in enumerate([("a feeling", "nervous"), ("a plan", "practise with a partner")], 1):
        absent = missing and i == 2
        rid = f"R{i}"
        rows.append(dict(requirementId=rid, questionEvidenceIds=["Q1"], taskQuote=requirement,
                         requirement=requirement, condition="", status="absent" if absent else "satisfied",
                         currentEvidence=[] if absent else [{"id": "C1", "quote": phrase}],
                         remainingGap=requirement if absent else "", limit="",
                         contentChecks=[dict(checkId=rid+".1", locate=requirement,
                             sourceValue="" if absent else phrase,
                             support="not_stated" if absent else "supported",
                             evidenceIds=[] if absent else ["C1"])]))
    table = dict(requirements=rows, contextLimits=[], scopeNote="Current task only.",
                 closureCheck=dict(openRequirementIds=["R2"] if missing else [], limitedRequirementIds=[],
                                   decision="material_gaps_present" if missing else "assessable_requirements_met"))
    ledger = [dict(requirementId=r["requirementId"], questionEvidenceIds=["Q1"],
                   currentEvidenceIds=[] if r["status"] == "absent" else ["C1"],
                   disposition="action" if r["status"] == "absent" else "already_satisfied",
                   finding="The plan is not stated." if r["status"] == "absent" else "Current content: "+r["currentEvidence"][0]["quote"],
                   suggestionSlot="1" if r["status"] == "absent" else "none",
                   actionQuote="State your next step" if r["status"] == "absent" else "") for r in rows]
    feedback = dict(summary="Your feeling is stated.", strengths=[
        dict(currentEvidenceIds=["C1"], comment="Naming nervousness directly addresses the requested feeling.")],
        suggestions=[dict(questionEvidenceIds=["Q1"],currentEvidenceIds=[],acknowledges="",gap="",
                          nextStep="State your next step; if undecided, say so.")] if missing else [],
        contextLimits=[], historyAudit=[], newOrMissedGaps=[],
        completion="revision_suggested" if missing else "no_material_gap")
    envelope = dict(coverageLedger=ledger, actionGroups=[
        dict(suggestionSlot="1", sharedPurpose="State a plan", requirementIds=["R2"])] if missing else [],
        feedback=feedback)
    return q, c, table, envelope


def response(payload, finish="stop", refusal=None):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
        message=SimpleNamespace(content=json.dumps(payload), refusal=refusal))],
        usage=SimpleNamespace(prompt_tokens=100,completion_tokens=20,total_tokens=120))


class V7Contracts(unittest.TestCase):
    def run_mock(self, missing=False, mutate=None):
        q, c, table, out = fixture(missing)
        if mutate:
            mutate(out)
        client = MagicMock()
        client.chat.completions.create.side_effect = [response(table), response(out)]
        with patch.object(v7, "OpenAI", return_value=client):
            result = v7.generate_feedback(q, c)
        return result, client

    def test_sufficient_answer_stops_without_followup(self):
        (text, usage, _), client = self.run_mock()
        self.assertIn("No further material revision", text)
        self.assertNotIn("?", text)
        self.assertEqual(len(usage), 2)
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_real_gap_gets_small_concrete_action(self):
        (text, _, _), _ = self.run_mock(missing=True)
        self.assertIn("State your next step", text)
        self.assertNotIn("No further material revision", text)
        self.assertLessEqual(len(text.split()), 180)

    def test_scoring_and_history_are_not_feedback_evidence(self):
        _, client = self.run_mock()
        calls = client.chat.completions.create.call_args_list
        first = json.loads(calls[0].kwargs["messages"][1]["content"])
        second = json.loads(calls[1].kwargs["messages"][1]["content"])
        self.assertEqual(set(first), {"task", "current"})
        self.assertIsNone(second["previousAnswer"])
        self.assertIsNone(second["previousFeedback"])
        self.assertNotIn("score", second)
        for call in calls:
            self.assertEqual(call.kwargs["model"], "gpt-4o-2024-08-06")
            self.assertEqual(call.kwargs["temperature"], .1)

    def test_cannot_hide_a_table_row(self):
        with self.assertRaises(v7.V7FeedbackError):
            self.run_mock(mutate=lambda e:e["coverageLedger"].pop())

    def test_gap_must_map_to_actual_next_step(self):
        with self.assertRaises(v7.V7FeedbackError):
            self.run_mock(True, lambda e:e["coverageLedger"][1].update(actionQuote="not in actual action"))

    def test_false_closure_with_actions_is_rejected(self):
        with self.assertRaises(v7.V7FeedbackError):
            self.run_mock(True, lambda e:e["feedback"].update(completion="no_material_gap"))

    def test_oversized_feedback_is_rejected_not_truncated(self):
        with self.assertRaises(v7.V7FeedbackError):
            self.run_mock(mutate=lambda e:e["feedback"].update(summary="word "*181))

    def test_fabricated_strength_evidence_is_rejected(self):
        with self.assertRaises(v7.V7FeedbackError):
            self.run_mock(mutate=lambda e:e["feedback"]["strengths"][0].update(currentEvidenceIds=["C99"]))

    def test_unknown_schema_fields_are_rejected(self):
        with self.assertRaises(v7.V7FeedbackError):
            self.run_mock(mutate=lambda e:e.update(score=100))

    def test_refusal_is_not_an_old_prompt_fallback(self):
        q,c,table,_=fixture()
        client=MagicMock()
        client.chat.completions.create.return_value=response(table,refusal="refused")
        with patch.object(v7,"OpenAI",return_value=client), self.assertRaises(v7.V7FeedbackError):
            v7.generate_feedback(q,c)
        self.assertEqual(client.chat.completions.create.call_count,1)

    def test_missing_task_does_not_call_api(self):
        with patch.object(v7,"OpenAI") as client, self.assertRaises(v7.V7FeedbackError):
            v7.generate_feedback(None,"some answer")
        client.assert_not_called()

    def test_t1_bad_quote_is_flagged_for_t2_source_recheck(self):
        q,c,table,_=fixture()
        table["requirements"][0]["currentEvidence"][0]["quote"]="not in this answer"
        user={"task":{"evidence":v7.evidence(q,"Q")},"current":{"evidence":v7.evidence(c,"C")}}
        self.assertIn("R1:invalid_current_quote",v7._table_source_errors(table,user))

    def test_limited_assessment_does_not_claim_all_requirements_met(self):
        _,_,_,out=fixture()
        out["feedback"].update(completion="assessment_limited", contextLimits=["The external comparison is unavailable."])
        out["coverageLedger"][1].update(disposition="unverifiable",currentEvidenceIds=[])
        user={"task":{"evidence":[{"id":"Q1","text":"task"}]},"current":{"evidence":[{"id":"C1","text":"answer"}]},
              "currentAssessment":{"table":{"requirements":[{"requirementId":"R1"},{"requirementId":"R2"}]}}}
        v7._validate_result(out,user)
        self.assertIn("unverified",v7.render_feedback(out["feedback"]))

    def test_legacy_playtest_score_and_rationale_prefix_is_unchanged(self):
        prefix="**Score: [79/100]**\n\n**Breakdown of Key Ingredients:**\n\n- **Specificity:** [4/10] – a quoted event.\n\n**Genre & Mechanic Evaluation (Knowledge Graph Score):**\n\n- **[18/50]** – movement."
        old=prefix+"\n\n**Professor Feedback:**\n\nAsk more questions.\n\n**Final Summary:**\n\nOld guidance."
        new=v7.replace_playtest_advice(old,"Specific praise. No further revision.")
        self.assertEqual(new.split("\n\n**Professor Feedback:**")[0],prefix)
        self.assertNotIn("Ask more questions",new)
        self.assertNotIn("Old guidance",new)

    def test_unrecognised_grading_format_is_not_silently_lost(self):
        with self.assertRaises(v7.V7FeedbackError):
            v7.replace_playtest_advice("unexpected output","new advice")
        with self.assertRaises(v7.V7FeedbackError):
            v7.reflection_score_block("no score supplied")

    def test_reflection_scores_are_copied_not_recomputed(self):
        text="\n".join(f"**Stage {i}. Stage name: {x} / 2**\n- **Improvement:** Invent a feeling?"
                       for i,x in enumerate(["1","1.33","2","1.67","2"],1))
        text+="\n**Additional Stage. Readability and Accuracy: 2 / 2**\n**Total Score: 9.99 / 12**\n**Summary:** Ask again."
        new=v7.reflection_score_block(text)
        self.assertIn("Total Score: 9.99 / 12",new)
        self.assertIn("1.33 / 2",new)
        self.assertNotIn("Invent",new)
        self.assertNotIn("Ask again",new)


class ReflectionAIntegration(unittest.TestCase):
    def test_original_grade_call_and_feedback_usage_are_preserved(self):
        # Execute only the small wrapper; importing the app/database is unnecessary.
        source=(Path(__file__).parent/"logic.py").read_text(encoding="utf-8")
        fn=next(x for x in ast.parse(source).body if isinstance(x,ast.FunctionDef) and x.name=="askChatGPTOriginal")
        legacy=MagicMock(return_value=("old numeric grades",None,{"total_tokens":9},15))
        merge=MagicMock(return_value={"total_tokens":19,"call_count":3})
        scope={"__package__":"feedback","__name__":"feedback.logic","os":__import__("os"),
               "_askChatGPTOriginalScored":legacy,"_merge_usage_dicts":merge,"FeedbackNotConfiguredError":RuntimeError}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),"logic_wrapper","exec"),scope)
        with patch.dict("os.environ",{"OPENAI_API_KEY":"offline-test-only"}), \
             patch.object(v7,"reflection_score_block",return_value="scores retained"), \
             patch.object(v7,"generate_feedback",return_value=("v7 feedback",[{"total_tokens":5},{"total_tokens":5}],20)) as fb:
            text,score,usage,latency=scope["askChatGPTOriginal"]("answer",question="task")
        legacy.assert_called_once_with("answer")
        fb.assert_called_once_with("task","answer")
        self.assertEqual(score["original_grading_response"],"old numeric grades")
        self.assertEqual(score["grading_method"],"basic_original")
        self.assertEqual(latency,35)
        self.assertEqual(usage["call_count"],3)
        self.assertIn("v7 feedback",text)


class PlaytestProxyIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from django.conf import settings
        if not settings.configured:
            settings.configure(SECRET_KEY="offline-test-only",DEBUG=False,ALLOWED_HOSTS=["testserver"],
                               REST_FRAMEWORK={"UNAUTHENTICATED_USER":None})
        from rest_framework.test import APIRequestFactory
        from .playtest import PlaytestFeedbackView
        cls.factory=APIRequestFactory()
        cls.view=staticmethod(PlaytestFeedbackView.as_view())

    def post(self,payload):
        return self.view(self.factory.post("/api/playtest/",payload,format="json"))

    def test_grade_query_is_unchanged_and_v7_replaces_only_advice(self):
        grade="**Score: [79/100]**\n\n**Professor Feedback:**\n\nOld question?"
        remote=MagicMock();remote.json.return_value={"response":grade}
        with patch.dict("os.environ",{"LIGHTRAG_URL":"http://offline.invalid"}), \
             patch("feedback.playtest.requests.post",return_value=remote) as grading, \
             patch("feedback.playtest.generate_feedback",return_value=("v7 praise. No further revision.",[],2)) as fb:
            res=self.post({"query":"original unmodified grading query","mode":"hybrid",
                           "question":"actual task","answer":"actual answer"})
        self.assertEqual(res.status_code,200)
        self.assertEqual(grading.call_args.kwargs["json"],
                         {"query":"original unmodified grading query","mode":"hybrid"})
        fb.assert_called_once_with("actual task","actual answer")
        self.assertIn("79/100",res.data["response"])
        self.assertIn("v7 praise",res.data["response"])
        self.assertNotIn("Old question",res.data["response"])
        self.assertEqual(res.data["feedback_prompt_version"],v7.VERSION)

    def test_invalid_feedback_fails_instead_of_serving_legacy_advice(self):
        remote=MagicMock();remote.json.return_value={"response":"**Professor Feedback:**\nOld advice"}
        with patch.dict("os.environ",{"LIGHTRAG_URL":"http://offline.invalid"}), \
             patch("feedback.playtest.requests.post",return_value=remote), \
             patch("feedback.playtest.generate_feedback",side_effect=v7.V7FeedbackError("invalid")):
            res=self.post({"query":"query","question":"task","answer":"answer"})
        self.assertEqual(res.status_code,503)
        self.assertNotIn("response",res.data)

    def test_unreachable_lightrag_is_not_reported_as_missing_config(self):
        import requests as _requests
        with patch.dict("os.environ",{"LIGHTRAG_URL":"http://offline.invalid"}), \
             patch("feedback.playtest.requests.post",
                   side_effect=_requests.ConnectionError("refused")):
            res=self.post({"query":"query","question":"task","answer":"answer"})
        self.assertEqual(res.status_code,503)
        # LIGHTRAG_URL is set here, so blaming the configuration hides the
        # real fault (a LightRAG service that cannot be reached).
        self.assertNotIn("not configured",res.data["detail"])
        self.assertIn("LightRAG",res.data["detail"])

    def test_empty_knowledge_graph_is_reported_as_no_context(self):
        # An empty LightRAG graph answers 200 with a canned reply. It carries no
        # score block, so without this check it surfaces as a misleading
        # "score block could not be separated" instead of the real cause.
        remote=MagicMock()
        remote.json.return_value={"response":"Sorry, I'm not able to provide an answer to that question.[no-context]"}
        with patch.dict("os.environ",{"LIGHTRAG_URL":"http://offline.invalid"}), \
             patch("feedback.playtest.requests.post",return_value=remote), \
             patch("feedback.playtest.generate_feedback") as fb:
            res=self.post({"query":"query","question":"task","answer":"answer"})
        self.assertEqual(res.status_code,503)
        self.assertIn("no context",res.data["detail"])
        self.assertNotIn("separated",res.data["detail"])
        fb.assert_not_called()

    def test_missing_url_config_is_reported_as_missing_config(self):
        env={"LIGHTRAG_URL":""}
        with patch.dict("os.environ",env):
            res=self.post({"query":"query","question":"task","answer":"answer"})
        self.assertEqual(res.status_code,503)
        self.assertIn("not configured",res.data["detail"])

    def test_configured_provider_requires_separate_task_and_answer(self):
        with patch.dict("os.environ",{"LIGHTRAG_URL":"http://offline.invalid"}), \
             patch("feedback.playtest.requests.post") as remote:
            res=self.post({"query":"query"})
        self.assertEqual(res.status_code,400)
        remote.assert_not_called()


if __name__=="__main__":
    unittest.main()
