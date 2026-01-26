from django.core.management.base import BaseCommand
from giveaway_engine.models import TelegramBot, Giveaway

class Command(BaseCommand):
    help = 'Assigns unique sequences to existing giveaways for each bot'

    def handle(self, *args, **options):
        bots = TelegramBot.objects.all()
        for bot in bots:
            self.stdout.write(f"Processing bot: {bot.username}")
            giveaways = Giveaway.objects.filter(bot=bot).order_pk() # Original order
            
            # Note: I'll use a safer ordering if order_pk doesn't exist, which it doesn't in default Django.
            # Usually order_by('id') is what people mean.
            giveaways = Giveaway.objects.filter(bot=bot).order_by('id')
            
            for i, giveaway in enumerate(giveaways, start=1):
                giveaway.sequence = i
                giveaway.save()
                self.stdout.write(f"  - [{giveaway.id}] {giveaway.title} -> Sequence: {i}")
        
        self.stdout.write(self.style.SUCCESS("Successfully repaired giveaway sequences."))
