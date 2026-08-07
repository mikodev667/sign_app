from django.urls import path
from django.contrib.auth.views import LogoutView
from .views import profile_view
from .views import AdmissionViceRectorLoginView, UserLoginView, admission_register_view, register_view

app_name = "accounts"

urlpatterns = [
    path("login/", UserLoginView.as_view(), name="login"),
    path("register/", register_view, name="register"),
    path("admissions/login/", AdmissionViceRectorLoginView.as_view(), name="admission_login"),
    path("admissions/register/", admission_register_view, name="admission_register"),
    path("logout/", LogoutView.as_view(next_page="accounts:login"), name="logout"),
    path("profile/", profile_view, name="profile"),
]
