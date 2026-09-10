"""
@changelog
| Version | Description                        | Reference       |
| v1.0.0  | Initial implementation: playtest route | DEV: local playtest |
/@changelog

@author chuckyang123
"""
from django.urls import path

from .playtest import PlaytestFeedbackView

urlpatterns = [
    path("", PlaytestFeedbackView.as_view(), name="playtest"),
]
