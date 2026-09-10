"""
@changelog
| Version | Description                                      | Reference                                   |
| v1.0.0  | Initial implementation: ChatGPT feedback generation and initial response collection |                                             |
| v1.1.0  | Added create_feedback_version_and_record:       | REQ: 20260818-feedback-modification-tracking |
|         | transactional answer version snapshot + AI feedback record + idempotent dedup | TECH: 04_design_tech-design.md §3.3          |
| v1.2.0  | ai_feedback_record_to_json gains include_score parameter | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.6 |
| v1.3.0  | FeedbackAnswerVersion links to submission; JSON output includes submission | REQ: 20260818-feedback-modification-tracking TECH: tech-design §3.3 |
| v1.4.0  | askChatGPT/askChatGPTOriginal fall back to mock feedback without OPENAI_API_KEY for local demo & testing | DEV: local demo without paid AI key |
| v1.5.0  | Production (DEBUG=False) without OPENAI_API_KEY raises FeedbackNotConfiguredError instead of emitting fake scores | PRD: production must fail loudly, mock is DEV-only |
| v1.6.0  | Added strip_scores_from_feedback_text + resolve_show_ai_score so reflection feedback sent to students can be score-stripped server-side | REQ: 20260824-playtest-score-visibility TECH: tech-design §3.6 |
| v1.6.1  | strip_scores_from_feedback_text now also strips the "Additional Stage. Readability and Accuracy: x / 2" heading (was leaking the score) | REQ: 20260824-playtest-score-visibility |
/@changelog

@author chuckyang123
"""
import logging
import os
import re
import time

from courses.models import (Course, CourseMembership, CourseMilestone,
                            CourseMilestoneTemplate, CourseSubmission)
from django.db import transaction
from django.db.models import Max
from django.conf import settings
from openai import OpenAI
import pandas as pd
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

from pigeonhole.common.constants import COURSE, CREATOR, ID, INITIAL_RESPONSE, MILESTONE, NAME, QUESTION, GENRE, MECHANIC
from pigeonhole.common.parsers import to_base_json
from users.logic import user_to_json
from users.models import User

from .models import AIFeedbackRecord, FeedbackAnswerVersion, FeedbackInitialResponse

logger = logging.getLogger("main")


class FeedbackNotConfiguredError(RuntimeError):
    """Raised when an AI provider (OpenAI / LightRAG) is required in a
    non-debug environment but its credentials or endpoint are not configured.
    The API layer converts this into a 503 so production fails loudly instead
    of serving simulated (score-less) feedback that could mislead students."""


## TODO: this is only a temporary implemention. Should not rely on webscraping in the long run.
def answer_reflection(driver, element_class, reflection):
    text_questions = driver.find_element(By.CLASS_NAME, element_class)
    text_questions.clear()
    text_questions.send_keys(reflection)

    return driver


def submit(driver, element_class):
    driver.find_element(By.CLASS_NAME, element_class).click()
    return driver


def get_result(driver, element_class):
    result = driver.find_element(By.CLASS_NAME, element_class).get_attribute("value")
    return result


# Returns a two element array of string containing HTML code
# First element contains the HTML of inline annotated reflection
# Segments of text to be highlighted are enclosed by <span> tags with the type of highlight found within the span's class.
# Classes of highlights include context, challenge, affect, modall, epistemic, link2me, change, metrics

# Second element contains the HTML of feedback for the student, provided in a two panel view


def analyse(text):

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    text_question_element_class = "ql-editor"
    submit_element_class = "btn-lg"

    url = "https://acawriter-demo.utscic.edu.au/demo"
    coreDriver = webdriver.Chrome(options=chrome_options)
    coreDriver.get(url)

    select_element = coreDriver.find_element(By.ID, "grammar")
    select_object = Select(select_element)
    select_object.select_by_visible_text("Pharmacy")
    driver = answer_reflection(coreDriver, text_question_element_class, text)
    driver = submit(driver, submit_element_class)
    element = WebDriverWait(driver=driver, timeout=60).until(
        EC.invisibility_of_element((By.CLASS_NAME, "nprogress-busy"))
    )

    element = driver.find_element(
        By.XPATH, "//div[contains(@class, 'col-md-12 wrapper')]"
    )
    results = []
    inlineFeedback = element.get_attribute("innerHTML")

    results.append(inlineFeedback)  # Inline text feedback

    element = driver.find_element(By.ID, "feedback")
    panelFeedback = element.get_attribute("innerHTML")

    # Changing name of analyser
    panelFeedback = panelFeedback.replace("AcaWriter", "Reflection Analyser")

    # Removing ineffective feedback
    panelFeedback = panelFeedback.replace(
        """<li class="col-md-12 p-2"><span class="text-danger"> While it appears that you’ve reported on how you would change/prepare for the future, you don’t seem to have reported first on what you found challenging. Perhaps you’ve reflected only on the positive aspects in your report?. </span></li>""",
        "",
    )
    results.append(panelFeedback)  # Panel text feedback

    coreDriver.close()
    return results


def _usage_to_dict(query_usage) -> dict:
    """Convert the usage object returned by OpenAI into a serializable dictionary."""
    if query_usage is None:
        return None
    return {
        "prompt_tokens": query_usage.prompt_tokens,
        "completion_tokens": query_usage.completion_tokens,
        "total_tokens": query_usage.total_tokens,
    }


def _merge_usage_dicts(usage_list) -> dict:
    """Aggregate token usage across multiple calls (single call in Basic mode, multiple in Advanced mode)."""
    merged = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "call_count": 0,
    }
    for usage in usage_list:
        if usage is None:
            continue
        merged["prompt_tokens"] += usage.get("prompt_tokens", 0)
        merged["completion_tokens"] += usage.get("completion_tokens", 0)
        merged["total_tokens"] += usage.get("total_tokens", 0)
        merged["call_count"] += 1
    return merged


def _feedback_to_score_json(response: "Feedback", averaged_scores: list) -> dict:
    """Extract the 6-stage score breakdown from the structured Feedback response for research analysis."""
    total_score = (
        response.stage_1.score
        + response.stage_2.score
        + response.stage_3.score
        + response.stage_4.score
        + response.stage_5.score
        + response.additional_stage.score
    )
    return {
        "stage_1_score": response.stage_1.score,
        "stage_2_score": response.stage_2.score,
        "stage_3_score": response.stage_3.score,
        "stage_4_score": response.stage_4.score,
        "stage_5_score": response.stage_5.score,
        "additional_stage_score": response.additional_stage.score,
        "total_score": total_score,
        "averaged_stage_scores": averaged_scores,
    }


def resolve_show_ai_score(submission_id: int) -> bool | None:
    """Resolve the course's ``show_ai_score`` setting through one of its submissions.

    Returns None when the submission (and thus its course) cannot be resolved;
    callers keep scores visible in that case rather than guessing.
    """
    try:
        submission = CourseSubmission.objects.select_related(
            "course__coursesettings"
        ).get(id=submission_id)
    except CourseSubmission.DoesNotExist:
        return None

    course_settings = getattr(submission.course, "coursesettings", None)
    if course_settings is None:
        return None
    return bool(course_settings.show_ai_score)


def strip_scores_from_feedback_text(feedback: str) -> str:
    """Remove numeric scoring markers from educator-grade reflection feedback.

    The Advanced ChatGPT flow formats each stage as
    ``**Stage N. <title>: x / 2**`` and closes with ``**Total Score: xx / 12**``.
    Hiding scores (PRD 20260824-playtest-score-visibility) keeps the stage
    headings and the qualitative "done well / improvement" comments but drops
    the numbers, so students never see a score when the course disables
    ``show_ai_score``.

    The Basic flow returns free-form text; only reliably-formatted standalone
    score lines are removed there. Applied server-side so students cannot get
    the scores by calling the API directly.
    """
    if not feedback:
        return feedback

    stage_header = re.compile(
        r"^(\*\*(?:Stage \d+|Additional Stage)[^*]*?):\s*\d+(?:\.\d+)?\s*/\s*\d+\s*\*\*$"
    )
    score_line = re.compile(
        r"^\*\*(?:Total\s+Score|Score|Overall\s+Score)\b[^*]*?:\s*\d"
    )

    lines = []
    for line in feedback.splitlines():
        trimmed = line.strip()
        match = stage_header.match(trimmed)
        if match:
            # Keep the stage heading text, drop its "x / 2" suffix
            lines.append(match.group(1) + "**")
            continue
        if score_line.match(trimmed):
            # Standalone total/score lines carry no qualitative content
            continue
        lines.append(line)

    return "\n".join(lines).strip()


def _mock_openai_feedback(text: str) -> str:
    """Simulated feedback used when OPENAI_API_KEY is not configured, so the
    full feedback + version-history flow can still be exercised locally.

    Deliberately contains NO numeric scores: the mock is also what students
    see, and a score-carrying mock would bypass the show_ai_score hiding
    (PRD 20260824-playtest-score-visibility). Real OpenAI output still carries
    scores and is stripped student-side by stripScoresFromMarkdown."""
    preview = " ".join(text.split())[:200]
    return (
        "**Professor Feedback:** "
        f"(Local mock mode – OPENAI_API_KEY not set) Simulated feedback for: "
        f"\"{preview}\""
    )


# Returns response from ChatGPT in a single string, which might contain newlines.
# Uses a basic prompt
def askChatGPTOriginal(text):
    if not os.getenv("OPENAI_API_KEY"):
        if settings.DEBUG:
            logger.warning(
                "OPENAI_API_KEY is not set; falling back to mock feedback (DEBUG only)."
            )
            return _mock_openai_feedback(text), None, None, 0
        raise FeedbackNotConfiguredError(
            "OPENAI_API_KEY is not configured. AI feedback generation is unavailable in this environment."
        )
    start_time = time.time()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Text prompt to generate feedback for the given reflection text
    prompt = "You are an educator with 30 years of education experience in guiding students through reflective learning." + \
            "Use the following step-by-step instructions to grade the given reflection and give feedback directed to the student:" +\
            "Step 1) Analyse and grade the reflection by each stage of reflection using the following reflective writing assessment rubrics. Each section is worth up to 2 marks. A score of 2 should only be given with sufficient details and elaboration from the student." + \
            "<Rubrics Start>" + \
            "Rubrics:" + \
            "Stage 1. Returning to Experience: Statement provides description of the task chronologically and is clear of any judgements" + \
            "Stage 2. Attending to Feelings: Statement conveys personal feelings, thoughts (positive and or negative) of the experience and relates to future personal learning" + \
            "Stage 3. Integration: Statement clearly provides evidence of integration of prior knowledge, feelings, or attitudes with new knowledge, feelings, or attitudes, thus arriving at new perspectives." + \
            "Stage 4. Appropriation: Statement clearly shows evidence that inferences have been made using their own prior knowledge and previous experience throughout the task" + \
            "Stage 5. Outcomes of Reflection: Statement clearly shows evidence of reflection and clearly states: (1) a change in behaviour or development of new perspectives as a result of the task; (2) ability to reflect on own task, apply new knowledge feelings, thoughts, opinions to enhance new future experiences; and (3) examples" + \
            "Additional Stage. Readability and Accuracy: Clear, engaging, accurate and comprehensive text." + \
            "<Rubrics End>" + \
            "Step 2) Display the results by each grading category. For each category, briefly explain what was done well, and if a full score of 2 was not obtained, add some suggestions on how to improve to get a better score." + \
            "Step 3) Tally the overall grade and give an overall summary."

    query = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system", 
                "content": prompt
            },
            {
                "role": "user", 
                "content": text
            }],
        temperature=0.1
    )
  
    response = query.choices[0].message.content 

    # Log usage
    logger.info(query.usage) 

    usage = _usage_to_dict(query.usage)
    latency_ms = (time.time() - start_time) * 1000

    return response, None, usage, latency_ms


# Returns response from ChatGPT in a single string, which might contain newlines.
# Uses advanced prompt engineering techniques
def askChatGPT(text):
    if not os.getenv("OPENAI_API_KEY"):
        if settings.DEBUG:
            logger.warning(
                "OPENAI_API_KEY is not set; falling back to mock feedback (DEBUG only)."
            )
            return _mock_openai_feedback(text), None, None, 0
        raise FeedbackNotConfiguredError(
            "OPENAI_API_KEY is not configured. AI feedback generation is unavailable in this environment."
        )
    start_time = time.time()
    scores, score_usages = askChatGPTForScore(text)
    response, feedback_usage = askChatGPTForFeedback(text, scores)
    formatted_response = formatResponse(response)

    score_json = _feedback_to_score_json(response, scores)
    usage = _merge_usage_dicts([*score_usages, feedback_usage])
    latency_ms = (time.time() - start_time) * 1000

    return formatted_response, score_json, usage, latency_ms

class Grade(BaseModel):
    stage_1_score: int
    stage_2_score: int
    stage_3_score: int
    stage_4_score: int
    stage_5_score: int
    additional_stage_score: int

def askChatGPTForScore(text):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Text prompt to generate scores for the given reflection text
    file_path = os.path.join(settings.BASE_DIR, "feedback/prompts/prompt_for_scores.txt")
    f = open(file_path, "r")
    prompt = f.read()
    f.close()

    df = pd.DataFrame(columns=['Stage 1', 'Stage 2', 'Stage 3', 'Stage 4', 'Stage 5', 'Additional Stage'])
    usages = []

    for i in range(3):
        query = client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": prompt
                },
                {
                    "role": "user", 
                    "content": text
                }],
            temperature=1,
            response_format=Grade
        )
        response = query.choices[0].message.parsed
        new_row = {'Stage 1': response.stage_1_score, 
                    'Stage 2': response.stage_2_score, 
                    'Stage 3': response.stage_3_score, 
                    'Stage 4': response.stage_4_score,
                    'Stage 5': response.stage_5_score,
                    'Additional Stage': response.additional_stage_score}
        df = df._append(new_row, ignore_index=True)

        # Log usage
        logger.info(query.usage)
        usages.append(_usage_to_dict(query.usage))

    return df.mean(axis=0).tolist(), usages

class Stage(BaseModel):
    score: float
    what_was_done_well: str
    improvement: str

class Feedback(BaseModel):
    stage_1: Stage
    stage_2: Stage
    stage_3: Stage
    stage_4: Stage
    stage_5: Stage
    additional_stage: Stage
    overall_feedback: str

def askChatGPTForFeedback(text, scores):
    scores = [int(val) if val.is_integer() else round(val, 2) for val in scores]
    scores_string = 'Stage 1: {}, Stage 2: {}, Stage 3: {}, Stage 4: {}, Stage 5: {}, Additional Stage {}'
    full_text = text + '\n\n' + scores_string.format(*scores)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Text prompt to generate feedback for the given reflection text
    file_path = os.path.join(settings.BASE_DIR, "feedback/prompts/prompt_for_feedback.txt")
    f = open(file_path, "r")
    prompt = f.read()
    f.close()

    query = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {
                "role": "system", 
                "content": prompt
            },
            {
                "role": "user", 
                "content": full_text
            }],
        temperature=1,
        response_format=Feedback
    )
  
    response = query.choices[0].message.parsed

    # Log usage
    logger.info(query.usage)
    usage = _usage_to_dict(query.usage)

    return response, usage

def formatResponse(response):
    total_score = response.stage_1.score + response.stage_2.score + response.stage_3.score +\
                    response.stage_4.score + response.stage_5.score + response.additional_stage.score
    if total_score.is_integer():
        total_score = int(total_score)
    cleaned_response = cleanUpResponse(response)

    return "**Stage 1. Returning to Experience: {} / 2** \n".format(cleaned_response.stage_1.score) +\
            "- **What was done well:** {} \n".format(cleaned_response.stage_1.what_was_done_well) +\
            "- **Improvement:** {} \n".format(cleaned_response.stage_1.improvement) +\
            " \n" +\
            "**Stage 2. Attending to Feelings: {} / 2** \n".format(cleaned_response.stage_2.score) +\
            "- **What was done well:** {} \n".format(cleaned_response.stage_2.what_was_done_well) +\
            "- **Improvement:** {} \n".format(cleaned_response.stage_2.improvement) +\
            " \n" +\
            "**Stage 3. Integration: {} / 2** \n".format(cleaned_response.stage_3.score) +\
            "- **What was done well:** {} \n".format(cleaned_response.stage_3.what_was_done_well) +\
            "- **Improvement:** {} \n".format(cleaned_response.stage_3.improvement) +\
            " \n" +\
            "**Stage 4. Appropriation: {} / 2** \n".format(cleaned_response.stage_4.score) +\
            "- **What was done well:** {} \n".format(cleaned_response.stage_4.what_was_done_well) +\
            "- **Improvement:** {} \n".format(cleaned_response.stage_4.improvement) +\
            " \n" +\
            "**Stage 5. Outcomes of Reflection: {} / 2** \n".format(cleaned_response.stage_5.score) +\
            "- **What was done well:** {} \n".format(cleaned_response.stage_5.what_was_done_well) +\
            "- **Improvement:** {} \n".format(cleaned_response.stage_5.improvement) +\
            " \n" +\
            "**Additional Stage. Readability and Accuracy: {} / 2** \n".format(cleaned_response.additional_stage.score) +\
            "- **What was done well:** {} \n".format(cleaned_response.additional_stage.what_was_done_well) +\
            "- **Improvement:** {} \n".format(cleaned_response.additional_stage.improvement) +\
            " \n" +\
            "**Total Score: {} / 12** \n".format(total_score) +\
            "**Summary:** {} \n".format(cleaned_response.overall_feedback)

def cleanUpStage(stage):
    if stage.score.is_integer():
        stage.score = int(stage.score) 
    if stage.score == 2:
        stage.improvement = "No improvement needed. You've done a great job!"
    return stage

def cleanUpResponse(response):
    response.stage_1 = cleanUpStage(response.stage_1)
    response.stage_2 = cleanUpStage(response.stage_2)
    response.stage_3 = cleanUpStage(response.stage_3)
    response.stage_4 = cleanUpStage(response.stage_4)
    response.stage_5 = cleanUpStage(response.stage_5)
    response.additional_stage = cleanUpStage(response.additional_stage)
    return response

@transaction.atomic
def createFeedbackInitialResponseIfNotExists(
    submission_id: int,
    requester: User,
    question: str,
    initial_response: str,
    genre: str | None = None,
    mechanic: str | None = None,
) -> tuple[FeedbackInitialResponse, bool]:
    
    try:
        submission = CourseSubmission.objects.select_related(
            "course",
            "milestone",
            "template"
        ).get(id=submission_id)

    except CourseSubmission.DoesNotExist as e:
        logger.warning(e)
        raise ValueError(f"No such submission found.")
    
    try:
        requester_membership = submission.course.coursemembership_set.get(user=requester)

    except CourseMembership.DoesNotExist as e:
        logger.warning(e)
        raise ValueError(f"No such user found in given course.")

    # Create new record only if none exists already
    new_initial_response, created = FeedbackInitialResponse.objects.get_or_create(
        course=submission.course,
        milestone=submission.milestone,
        template=submission.template,
        creator=requester_membership,
        question=question,
        defaults={
            "name": submission.template.__str__(), 
            "initial_response":initial_response,
            "genre":genre,
            "mechanic":mechanic,
        }
    )

    return new_initial_response, created

def feedback_initial_response_to_json(response: FeedbackInitialResponse) -> dict:
    data = to_base_json(response)

    data |= {
        NAME: response.name,
        QUESTION: response.question,
        INITIAL_RESPONSE: response.initial_response,
        GENRE: response.genre,
        MECHANIC: response.mechanic,
        CREATOR: user_to_json(response.creator.user)
        if response.creator is not None
        else None,
        MILESTONE: {ID: response.milestone.id, NAME: response.milestone.name}
        if response.milestone is not None
        else None,
        COURSE: {ID: response.course.id, NAME: response.course.name}
        if response.course is not None
        else None,
    }

    return data


def feedback_answer_version_to_json(version: FeedbackAnswerVersion) -> dict:
    data = to_base_json(version)

    data |= {
        NAME: version.name,
        QUESTION: version.question,
        "answer_content": version.answer_content,
        "version_number": version.version_number,
        GENRE: version.genre,
        MECHANIC: version.mechanic,
        CREATOR: user_to_json(version.creator.user)
        if version.creator is not None
        else None,
        MILESTONE: {ID: version.milestone.id, NAME: version.milestone.name}
        if version.milestone is not None
        else None,
        COURSE: {ID: version.course.id, NAME: version.course.name}
        if version.course is not None
        else None,
        "submission": {ID: version.submission.id, NAME: version.submission.name}
        if version.submission is not None
        else None,
    }

    return data


def ai_feedback_record_to_json(
    record: AIFeedbackRecord, include_score: bool = True
) -> dict:
    """Serialize an AI feedback record to JSON.

    `include_score` (default True) controls whether `score_json` is exposed.
    Set to False in student-facing endpoints so numeric scores stay hidden
    when a course disables `show_ai_score` (PRD 20260824-playtest-score-visibility).
    Teachers always keep the score (include_score=True).
    """
    data = to_base_json(record)

    data |= {
        "version": feedback_answer_version_to_json(record.version),
        "feedback_type": record.feedback_type,
        "strategy": record.strategy,
        "score_json": record.score_json if include_score else None,
        "feedback_content": record.feedback_content,
        "model_version": record.model_version,
        "token_usage_json": record.token_usage_json,
        "latency_ms": record.latency_ms,
    }

    return data


@transaction.atomic
def create_feedback_version_and_record(
    submission_id: int,
    requester: User,
    question: str,
    answer_content: str,
    feedback_type: str,
    strategy: str,
    feedback_content: str,
    idempotency_key: str | None = None,
    score_json: dict | None = None,
    model_version: str = "",
    token_usage_json: dict | None = None,
    latency_ms: float | None = None,
    genre: str | None = None,
    mechanic: str | None = None,
) -> AIFeedbackRecord:
    """Create an answer version snapshot and an AI feedback record within a transaction.

    - Returns the existing record when an idempotency key is provided (RISK-DA006, prevents duplicate writes on network retries)
    - Version number increments by Max+1 per student/question dimension
    - The whole operation runs in a single transaction; any failure rolls everything back
    """
    # Idempotent dedup: repeated submissions with the same idempotency_key return the existing record
    if idempotency_key:
        existing = AIFeedbackRecord.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            logger.info("Idempotent feedback record hit for key=%s", idempotency_key)
            return existing

    try:
        submission = CourseSubmission.objects.select_related(
            "course", "milestone", "template"
        ).get(id=submission_id)
    except CourseSubmission.DoesNotExist as e:
        logger.warning(e)
        raise ValueError("No such submission found.")

    try:
        requester_membership = submission.course.coursemembership_set.get(user=requester)
    except CourseMembership.DoesNotExist as e:
        logger.warning(e)
        raise ValueError("No such user found in given course.")

    # Version increment: Max+1 within the same (course, milestone, template, creator, question)
    max_version = FeedbackAnswerVersion.objects.filter(
        course=submission.course,
        milestone=submission.milestone,
        template=submission.template,
        creator=requester_membership,
        question=question,
    ).aggregate(max_version=Max("version_number"))["max_version"]
    version_number = (max_version or 0) + 1

    version = FeedbackAnswerVersion.objects.create(
        course=submission.course,
        milestone=submission.milestone,
        template=submission.template,
        submission=submission,
        creator=requester_membership,
        name=submission.template.__str__(),
        question=question,
        answer_content=answer_content,
        version_number=version_number,
        genre=genre,
        mechanic=mechanic,
    )

    record = AIFeedbackRecord.objects.create(
        version=version,
        feedback_type=feedback_type,
        strategy=strategy,
        score_json=score_json,
        feedback_content=feedback_content,
        model_version=model_version,
        token_usage_json=token_usage_json,
        latency_ms=latency_ms,
        idempotency_key=idempotency_key,
    )

    return record