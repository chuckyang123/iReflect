"""
@changelog
| Version | Description                          | Reference                                   |
| v1.0.0  | Initial implementation: feedback routes |                                             |
| v1.1.0  | Added records/ route (report + query) | REQ: 20260818-feedback-modification-tracking |
/@changelog

@author chuckyang123
"""
from django.urls import path

from .views import (
    FeedbackInitialResponseView,
    FeedbackRecordView,
    FeedbackView,
)

urlpatterns = [
    path("", FeedbackView.as_view(), name="feedback"),
    path("initial-response/", FeedbackInitialResponseView.as_view(), name="initial_response"),
    path("records/", FeedbackRecordView.as_view(), name="feedback_records"),
]
