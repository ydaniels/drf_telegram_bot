from django.contrib import admin
from django.contrib import messages
from django import db
from .models import TelegramBot, TelegramUser, Giveaway, GiveawayItem, GiveawayAttempt, NewsUpdate, MessageTemplate, Questionnaire
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
            
            # Prepare Message Content
            msg = ""
            if obj.giveaway.approval_template:
                # Use Template
                template = obj.giveaway.approval_template.content
                # Safe Format
                base_content = ""
                
                # UNIQUE GIVEAWAY
                if obj.giveaway.giveaway_type == 'unique':
                    # Lock an item
                    item = GiveawayItem.objects.filter(giveaway=obj.giveaway, is_used=False).first()
                    if item:
                        item.is_used = True
                        item.claimed_by = obj.user
                        item.save()
                        base_content = item.content
                        messages.success(request, f"Approved and sent code: {item.content}")
                    else:
                        messages.error(request, "NO ITEMS LEFT! User was NOT sent a code. Status saved as Approved regardless.")
                        return # Or handle error appropriately
                else:
                    # STANDARD
                    base_content = obj.giveaway.static_content
                    messages.success(request, "Approved and sent content.")

                try:
                    msg = template.format(
                        content=base_content,
                        name=obj.user.first_name or "Friend"
                    )
                except Exception as e:
                    msg = f"Error formatting template: {e}\nContent: {base_content}"
            
            else:
                # DEFAULT LOGIC (No Template)
                
                # UNIQUE GIVEAWAY
                if obj.giveaway.giveaway_type == 'unique':
                    # Lock an item
                    item = GiveawayItem.objects.filter(giveaway=obj.giveaway, is_used=False).first()
                    if item:
                        item.is_used = True
                        item.claimed_by = obj.user
                        item.save()
                        
                        msg = f"✅ Congratulations! Your claim has been approved.\nHere is your code:\n{item.content}"
                        messages.success(request, f"Approved and sent code: {item.content}")
                    else:
                        messages.error(request, "NO ITEMS LEFT! User was NOT sent a code. Status saved as Approved regardless.")
                        # Proceeding to save anyway as per previous logic, but skipping send
                        super().save_model(request, obj, form, change)
                        return
                
                # STANDARD GIVEAWAY
                elif obj.giveaway.giveaway_type == 'standard':
                     msg = f"✅ Congratulations! Your claim has been approved.\n{obj.giveaway.static_content}"
                     messages.success(request, "Approved and sent content.")

            # Send the final message
            if msg:
                send_telegram_message(
                    obj.giveaway.bot.token, 
                    obj.user.chat_id, 
                    msg
                )

        super().save_model(request, obj, form, change)

admin.site.register(TelegramBot)
admin.site.register(TelegramUser)
class QuestionnaireInline(admin.TabularInline):
    model = Questionnaire
    extra = 1

@admin.register(Giveaway)
class GiveawayAdmin(admin.ModelAdmin):
    inlines = [QuestionnaireInline]
    list_display = ('sequence', 'title', 'bot', 'giveaway_type', 'requirement_type', 'failure_template', 'is_active')
    list_display_links = ('title',)
    list_editable = ('sequence', 'is_active')
    list_filter = ('bot', 'giveaway_type', 'requirement_type')

admin.site.register(GiveawayItem)
admin.site.register(NewsUpdate)
admin.site.register(MessageTemplate)
