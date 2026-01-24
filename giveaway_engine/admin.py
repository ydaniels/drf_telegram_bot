from django.contrib import admin
from django.contrib import messages
from django import db
from .models import TelegramBot, TelegramUser, Giveaway, GiveawayItem, GiveawayAttempt, NewsUpdate
from .utils import send_telegram_message

@admin.register(GiveawayAttempt)
class GiveawayAttemptAdmin(admin.ModelAdmin):
    list_display = ('user', 'giveaway', 'status', 'created_at')
    list_filter = ('status', 'giveaway', 'created_at')
    readonly_fields = ('user', 'giveaway', 'user_proof', 'created_at')

    @db.transaction.atomic
    def save_model(self, request, obj, form, change):
        # Check if status changed to approved
        if change and 'status' in form.changed_data and obj.status == 'approved':
            
            # UNIQUE GIVEAWAY
            if obj.giveaway.giveaway_type == 'unique':
                # Lock an item
                item = GiveawayItem.objects.filter(giveaway=obj.giveaway, is_used=False).first()
                if item:
                    item.is_used = True
                    item.claimed_by = obj.user
                    item.save()
                    
                    # Send code
                    send_telegram_message(
                        obj.giveaway.bot.token, 
                        obj.user.chat_id, 
                        f"✅ Congratulations! Your claim has been approved.\nHere is your code:\n{item.content}"
                    )
                    messages.success(request, f"Approved and sent code: {item.content}")
                else:
                    # No items left!
                    messages.error(request, "NO ITEMS LEFT! User was NOT sent a code. Status saved as Approved regardless.")
                    # In a real app we might want to prevent saving, but for this simpler engine we proceed.
            
            # STANDARD GIVEAWAY
            elif obj.giveaway.giveaway_type == 'standard':
                 send_telegram_message(
                    obj.giveaway.bot.token, 
                    obj.user.chat_id, 
                    f"✅ Congratulations! Your claim has been approved.\n{obj.giveaway.static_content}"
                )
                 messages.success(request, "Approved and sent content.")

        super().save_model(request, obj, form, change)

admin.site.register(TelegramBot)
admin.site.register(TelegramUser)
admin.site.register(Giveaway)
admin.site.register(GiveawayItem)
admin.site.register(NewsUpdate)
