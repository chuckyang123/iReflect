from django.urls import include, path


urlpatterns = [
    path("gateway/", include("authentication.urls")),
    path("users/", include("users.urls")),
    path("courses/", include("courses.urls")),
    path("feedback/", include("feedback.urls")),
    path("playtest/", include("feedback.playtest_urls")),
]
