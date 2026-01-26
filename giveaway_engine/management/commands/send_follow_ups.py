from django.core.management.base import BaseCommand
from giveaway_engine.models import GiveawayAttempt
from giveaway_engine.utils import process_follow_up
from django.utils import timezone
from datetime import timedelta

class Command(BaseCommand):
    help = 'Sends pending follow-up messages for approved giveaway attempts'

    def handle(self, *args, **options):
        self.stdout.write("Checking for pending follow-ups...")
        count = process_all_pending_follow_ups()
        if count > 0:
            self.stdout.write(self.style.SUCCESS(f"Successfully processed {count} follow-up(s)."))
        else:
            self.stdout.write("No pending follow-ups were ready for processing.")
