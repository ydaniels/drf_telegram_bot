from django.core.management.base import BaseCommand
from giveaway_engine.models import TelegramBot, Giveaway
import requests

class Command(BaseCommand):
    help = 'Diagnoses bot configuration, active giveaways, and webhook status'

    def handle(self, *args, **options):
        bots = TelegramBot.objects.all()
        self.stdout.write(self.style.SUCCESS(f"Found {bots.count()} bots in database."))
        
        for bot in bots:
            self.stdout.write(f"\nBot: {bot.username} (Active: {bot.is_active})")
            self.stdout.write(f"Token: {bot.token[:5]}...{bot.token[-5:]} (Length: {len(bot.token)})")
            
            # Webhook Check
            self.check_webhook(bot)
            
            giveaways = Giveaway.objects.filter(bot=bot)
            active_giveaways = giveaways.filter(is_active=True)
            
            self.stdout.write(f"Total Giveaways: {giveaways.count()}")
            self.stdout.write(f"Active Giveaways: {active_giveaways.count()}")
            
            if giveaways.count() > 0 and active_giveaways.count() == 0:
                self.stdout.write(self.style.WARNING("!!! WARNING: You have giveaways for this bot, but NONE are active."))
            
            for g in active_giveaways:
                pre_info = f" (Prereq: Seq <= {g.pre_giveaway})" if g.pre_giveaway else ""
                self.stdout.write(f"  - [{g.sequence}] {g.title} ({g.giveaway_type}){pre_info}")

        if bots.count() == 0:
            self.stdout.write(self.style.ERROR("No bots found. Please create a bot in Django Admin first."))

    def check_webhook(self, bot):
        url = f"https://api.telegram.org/bot{bot.token}/getWebhookInfo"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("ok"):
                info = data.get("result", {})
                webhook_url = info.get("url", "")
                if webhook_url:
                    self.stdout.write(self.style.SUCCESS(f"Registered Webhook: {webhook_url}"))
                    if info.get("last_error_message"):
                        self.stdout.write(self.style.ERROR(f"Last Error: {info.get('last_error_message')}"))
                else:
                    self.stdout.write(self.style.WARNING("No webhook registered on Telegram!"))
            else:
                self.stdout.write(self.style.ERROR(f"Could not fetch webhook info: {data.get('description')}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error checking webhook: {e}"))
