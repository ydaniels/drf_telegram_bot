import logging
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from .models import TelegramBot, TelegramUser, Giveaway, GiveawayItem, GiveawayAttempt, NewsUpdate
from .utils import send_telegram_message

logger = logging.getLogger(__name__)

class TelegramWebhookView(APIView):
    """
    Main webhook handler for Telegram updates.
    """
    permission_classes = [] # Public endpoint for Telegram to call

    def post(self, request, token):
        # Identify the bot by token
        bot = get_object_or_404(TelegramBot, token=token, is_active=True)
        
        data = request.data
        message = data.get('message', {})
        
        if not message:
            return Response(status=status.HTTP_200_OK)

        chat_data = message.get('chat', {})
        chat_id = str(chat_data.get('id'))
        user_data = message.get('from', {})
        username = user_data.get('username')
        first_name = user_data.get('first_name')
        text = message.get('text', '').strip()
        photo = message.get('photo')

        # 1. Get or Create TelegramUser
        user, created = TelegramUser.objects.get_or_create(
            bot=bot,
            chat_id=chat_id,
            defaults={
                'username': username,
                'first_name': first_name
            }
        )
        # Update user details if changed
        if not created:
            if user.username != username or user.first_name != first_name:
                user.username = username
                user.first_name = first_name
                user.save()

        # 2. Logic Flow
        
        # Scenario A: /start
        if text == '/start':
            self.handle_start(bot, chat_id, first_name)
            
        # Commands like /claim_123
        elif text.startswith('/claim_'):
            self.handle_claim(bot, user, chat_id, text)
            
        # Scenario C (Part 2): Receiving Proof (Photo or Text)
        elif photo or (text and not text.startswith('/')):
            self.handle_proof(bot, user, chat_id, message)
            
        else:
            # Unknown command or interaction
            pass

        return Response(status=status.HTTP_200_OK)

    def handle_start(self, bot, chat_id, name):
        # Fetch Active Giveaways
        giveaways = Giveaway.objects.filter(bot=bot, is_active=True)
        
        # Fetch Latest News
        news = NewsUpdate.objects.filter(bot=bot).order_by('-sent_at').first()
        
        # Build Message
        msg = f"👋 Welcome {name}!\n\n"
        
        if news:
            msg += f"📰 Latest News: {news.title}\n{news.body}\n\n"
            
        if giveaways.exists():
            msg += "🎁 Active Giveaways:\n\n"
            for g in giveaways:
                msg += f"{g.title}"
                if g.giveaway_type == 'standard':
                    msg += " (Instant)"
                elif g.requirement_type == 'manual_approval':
                    msg += " (Requires Proof)"
                msg += f" - /claim_{g.id}\n\n"
        else:
            msg += "No active giveaways at the moment."
            
        send_telegram_message(bot.token, chat_id, msg)

    def handle_claim(self, bot, user, chat_id, text):
        try:
            giveaway_id = int(text.split('_')[1])
            giveaway = Giveaway.objects.get(id=giveaway_id, bot=bot, is_active=True)
        except (IndexError, ValueError, Giveaway.DoesNotExist):
            send_telegram_message(bot.token, chat_id, "Giveaway not found or inactive.")
            return

        # Scenario B (Standard)
        if giveaway.giveaway_type == 'standard' and giveaway.requirement_type == 'none':
            send_telegram_message(bot.token, chat_id, giveaway.static_content)
            GiveawayAttempt.objects.create(
                user=user,
                giveaway=giveaway,
                status='approved'
            )
        
        # Scenario C (Unique + Manual Approval)
        elif giveaway.requirement_type == 'manual_approval':
            # Store intent in cache for 10 minutes
            cache_key = f"claim_intent_{chat_id}"
            cache.set(cache_key, giveaway.id, timeout=600)
            
            send_telegram_message(bot.token, chat_id, "Please send your proof (screenshot/text) now.")
            
        else:
            # Handle other combinations if needed
            send_telegram_message(bot.token, chat_id, "This giveaway configuration is not fully supported yet.")

    def handle_proof(self, bot, user, chat_id, message):
        cache_key = f"claim_intent_{chat_id}"
        giveaway_id = cache.get(cache_key)
        
        if not giveaway_id:
            # User sent a message/photo but no claim pending
            # Maybe send a generic help? Or ignore.
            return
            
        # Get the giveaway
        try:
            giveaway = Giveaway.objects.get(id=giveaway_id)
        except Giveaway.DoesNotExist:
            return # Should not happen usually

        # Extract Proof
        proof = ""
        if 'photo' in message:
            # Get the largest photo file_id
            proof = message['photo'][-1]['file_id']
        elif 'text' in message:
            proof = message['text']
            
        # Create Attempt
        GiveawayAttempt.objects.create(
            user=user,
            giveaway=giveaway,
            status='pending',
            user_proof=proof
        )
        
        # Clear cache
        cache.delete(cache_key)
        
        send_telegram_message(bot.token, chat_id, "Proof received! An admin will verify shortly.")
