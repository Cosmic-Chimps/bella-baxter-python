from django.urls import path
from myapp import views

urlpatterns = [
    path("", views.index),
    path("health", views.health),
    path("secrets", views.secrets),
]
