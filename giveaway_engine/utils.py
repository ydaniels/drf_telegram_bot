import requests
import logging

logger = logging.getLogger(__name__)

def send_telegram_message(bot_token, chat_id, text, reply_markup=None):
    """
    Sends a message to a Telegram user.
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
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
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
