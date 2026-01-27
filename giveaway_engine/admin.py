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

@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'first_name', 'chat_id', 'bot', 'send_message_link')
    list_filter = ('bot',)
    search_fields = ('username', 'first_name', 'chat_id')
    readonly_fields = ('recent_history',)
    actions = ['send_bulk_message_action']

    def recent_history(self, obj):
        from django.utils.html import format_html
        logs = obj.logs.all().order_by('-timestamp')[:20]
        if not logs:
            return "No messages yet."
        
        html = '<div style="max-height: 300px; overflow-y: auto;"><table style="width: 100%; text-align: left; border-collapse: collapse;">'
        html += '<thead><tr><th>Time</th><th>Dir</th><th>Message</th></tr></thead><tbody>'
        for log in logs:
            color = "#e1f5fe" if log.direction == 'inbound' else "#fff9c4"
            html += f'<tr style="background: {color}; border-bottom: 1px solid #eee;">'
            html += f'<td style="padding: 5px; white-space: nowrap;">{log.timestamp.strftime("%H:%M:%S")}</td>'
            html += f'<td style="padding: 5px;">{"⬅️" if log.direction == "inbound" else "➡️"}</td>'
            html += f'<td style="padding: 5px;">{log.content}</td></tr>'
        html += '</tbody></table></div>'
        return format_html(html)

    recent_history.short_description = "Last 20 Messages"

    def send_message_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        url = reverse('admin:send-message', args=[obj.id])
        return format_html('<a class="button" href="{}">Send Message</a>', url)
    
    send_message_link.short_description = "Messaging"

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:user_id>/send-message/', self.admin_site.admin_view(self.single_message_view), name='send-message'),
        ]
        return custom_urls + urls

    def single_message_view(self, request, user_id):
        from django.shortcuts import get_object_or_404
        queryset = TelegramUser.objects.filter(id=user_id)
        return self.send_bulk_message_action(request, queryset)

    @admin.action(description="Send bulk message to selected users")
    def send_bulk_message_action(self, request, queryset):
        # We'll use a session-based approach to store IDs and redirect to a form
        from django.shortcuts import render, redirect
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        
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
            if queryset.count() == 1:
                return HttpResponseRedirect(reverse('admin:giveaway_engine_telegramuser_change', args=[queryset.first().id]))
            return HttpResponseRedirect(reverse('admin:giveaway_engine_telegramuser_changelist'))

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
