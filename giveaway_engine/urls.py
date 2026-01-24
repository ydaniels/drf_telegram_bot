from django.urls import path
from .views import TelegramWebhookView

urlpatterns = [
    path('webhook/<str:token>/', TelegramWebhookView.as_view(), name='telegram_webhook'),
]
