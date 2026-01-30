import requests
import logging
from django.urls import reverse

logger = logging.getLogger(__name__)

def send_telegram_message(bot_token, chat_id, text, reply_markup=None, bot=None, user=None):
    """
    Sends a message to a Telegram user and logs it if bot/user provided.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Log outbound message
        if bot and user:
            from .models import MessageLog
            MessageLog.objects.create(
                user=user,
                bot=bot,
                content=text,
                direction='outbound'
            )
        return result
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to send Telegram message: {e}"
        if e.response is not None:
             error_msg += f" | Body: {e.response.text}"
        logger.error(error_msg)
        return None

def update_bot_info(bot_instance):
    """
    Checks if bot name/description/short_description match Telegram values.
    Updates them if different.
    """
    token = bot_instance.token
    base_url = f"https://api.telegram.org/bot{token}"
    
    # helper for basic requests
    def call_tg(method, data=None):
        try:
            resp = requests.post(f"{base_url}/{method}", json=data or {}, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"Error calling {method}: {e}")
            return {"ok": False}

    # 1. Name
    # Note: setMyName affects the bot's name in chats.
    current_name_resp = call_tg("getMyName")
    if current_name_resp.get("ok"):
        current_name = current_name_resp.get("result", {}).get("name", "")
        # If DB name is set and different from TG
        if bot_instance.name and bot_instance.name != current_name:
            call_tg("setMyName", {"name": bot_instance.name})
            logger.info(f"Updated Bot Name to: {bot_instance.name}")

    # 2. Description (What can this bot do?)
    current_desc_resp = call_tg("getMyDescription")
    if current_desc_resp.get("ok"):
        current_desc = current_desc_resp.get("result", {}).get("description", "")
        db_desc = bot_instance.description or ""
        # Telegram might treat empty string and None similarly, strip to be safe
        if db_desc.strip() != current_desc.strip():
             call_tg("setMyDescription", {"description": db_desc})
             logger.info(f"Updated Bot Description")

    # 3. Short Description (Chat list / profile)
    current_short_resp = call_tg("getMyShortDescription")
    if current_short_resp.get("ok"):
        current_short = current_short_resp.get("result", {}).get("short_description", "")
        db_short = bot_instance.short_description or ""
        if db_short.strip() != current_short.strip():
             call_tg("setMyShortDescription", {"short_description": db_short})
             logger.info(f"Updated Bot Short Description")

def set_webhook(bot_instance):
    """
    Registers the webhook URL with Telegram based on the bot's webhook_domain.
    """
    domain = bot_instance.webhook_domain.rstrip('/')
    webhook_path = reverse('telegram_webhook', kwargs={'token': bot_instance.token})
    webhook_url = f"{domain}{webhook_path}"
    
    url = f"https://api.telegram.org/bot{bot_instance.token}/setWebhook"
    payload = {"url": webhook_url}
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get("ok"):
            logger.info(f"Successfully set webhook for {bot_instance.username}: {webhook_url}")
        else:
            logger.error(f"Failed to set webhook for {bot_instance.username}: {result.get('description')}")
        return result
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        return {"ok": False}

def process_follow_up(attempt_id):
    """
    Checks if an attempt needs a follow-up and sends it.
    Can be called by Celery, a thread, or a cron job.
    """
    from .models import GiveawayAttempt
    try:
        attempt = GiveawayAttempt.objects.get(id=attempt_id)
        
        # Security/State Checks
        if attempt.status != 'approved':
            return False
            
        if attempt.follow_up_sent:
            return False
            
        if not attempt.giveaway.follow_up_text:
            return False

        # Send the message
        success = send_telegram_message(
            attempt.giveaway.bot.token,
            attempt.user.chat_id,
            attempt.giveaway.follow_up_text,
            bot=attempt.giveaway.bot,
            user=attempt.user
        )

        if success:
            attempt.follow_up_sent = True
            attempt.save()
            logger.info(f"Follow-up sent for attempt {attempt_id}")
            return True
            
    except GiveawayAttempt.DoesNotExist:
        logger.error(f"Attempt {attempt_id} not found for follow-up")
    except Exception as e:
        logger.error(f"Error processing follow-up for {attempt_id}: {e}")
    
    return False

def process_all_pending_follow_ups():
    """
    Finds and processes all giveaway attempts that need a follow-up.
    Useful for task queues or cron jobs.
    """
    from .models import GiveawayAttempt
    from django.utils import timezone
    from datetime import timedelta
    
    pending = GiveawayAttempt.objects.filter(
        status='approved',
        follow_up_sent=False,
        giveaway__follow_up_text__isnull=False
    ).exclude(giveaway__follow_up_text='')

    count = 0
    for attempt in pending:
        # Check if enough time has passed based on the giveaway's specific delay
        delay_seconds = attempt.giveaway.follow_up_delay_seconds
        if timezone.now() > attempt.created_at + timedelta(seconds=delay_seconds):
            if process_follow_up(attempt.id):
                count += 1
    return count

