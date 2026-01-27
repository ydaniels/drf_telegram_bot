from django.contrib import admin
from django.contrib import messages
from django import db
from .models import TelegramBot, TelegramUser, Giveaway, GiveawayItem, GiveawayAttempt, NewsUpdate, MessageTemplate, Questionnaire, MessageLog
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
                    msg,
                    bot=obj.giveaway.bot,
                    user=obj.user
                )

        super().save_model(request, obj, form, change)

admin.site.register(TelegramBot)

class MessageLogInline(admin.TabularInline):
    model = MessageLog
    extra = 0
    readonly_fields = ('direction', 'content', 'timestamp')
    can_delete = False
    
    def get_queryset(self, request):
        return super().get_queryset(request).order_by('-timestamp')[:20]

@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'first_name', 'chat_id', 'bot', 'send_message_link')
    list_filter = ('bot',)
    search_fields = ('username', 'first_name', 'chat_id')
    inlines = [MessageLogInline]
    actions = ['send_bulk_message_action']

    def send_message_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        url = reverse('admin:giveaway_engine_telegramuser_changelist') + f"?id={obj.id}&action=send_bulk_message_action"
        return format_html('<a class="button" href="{}">Send Message</a>', url)
    
    send_message_link.short_description = "Messaging"

    @admin.action(description="Send bulk message to selected users")
    def send_bulk_message_action(self, request, queryset):
        # We'll use a session-based approach to store IDs and redirect to a form
        from django.shortcuts import render, redirect
        from django.http import HttpResponseRedirect
        
        if 'apply' in request.POST:
            msg_text = request.POST.get('message_text')
            if not msg_text:
                 messages.error(request, "Please enter a message.")
                 return
            
            count = 0
            for user in queryset:
                success = send_telegram_message(
                    user.bot.token, 
                    user.chat_id, 
                    msg_text,
                    bot=user.bot,
                    user=user
                )
                if success:
                    count += 1
            
            messages.success(request, f"Successfully sent message to {count} users.")
            return HttpResponseRedirect(request.get_full_path())

        return render(request, 'admin/send_message_form.html', context={'users': queryset})

class QuestionnaireInline(admin.TabularInline):
    model = Questionnaire
    extra = 1

@admin.register(Giveaway)
class GiveawayAdmin(admin.ModelAdmin):
    inlines = [QuestionnaireInline]
    list_display = ('sequence', 'title', 'bot', 'giveaway_type', 'requirement_type', 'failure_template', 'prompt_template', 'success_template', 'is_active')
    list_display_links = ('title',)
    list_editable = ('sequence', 'is_active')
    list_filter = ('bot', 'giveaway_type', 'requirement_type')

@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'bot', 'direction', 'content_snippet')
    list_filter = ('direction', 'bot', 'timestamp')
    search_fields = ('user__username', 'content')
    readonly_fields = ('user', 'bot', 'direction', 'content', 'timestamp')

    def content_snippet(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content

admin.site.register(GiveawayItem)
admin.site.register(NewsUpdate)
admin.site.register(MessageTemplate)
