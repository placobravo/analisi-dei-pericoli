from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

from portal.admin import administration
from portal.forms import LoginForm

urlpatterns = [
    path("accedi/", auth_views.LoginView.as_view(
        authentication_form=LoginForm, template_name="portal/login.html"
    ), name="login"),
    path("esci/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", auth_views.PasswordChangeView.as_view(
        template_name="portal/password.html", success_url=reverse_lazy("home")
    ), name="password_change"),
    path("amministrazione/", administration.urls),
    path("", include("portal.urls")),
]
