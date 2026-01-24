from django.db import models

class TelegramBot(models.Model):
    """Manage multiple bots from one dashboard"""
    name = models.CharField(max_length=100)
    username = models.CharField(max_length=100) # e.g. @socialappfarm_bot
    token = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    
    description = models.TextField(blank=True, null=True, help_text="what the bot can do")
    short_description = models.TextField(blank=True, null=True, help_text="shown in chat info/preview")
    
    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        # We need to import here to avoid circular dependencies with utils
        from .utils import update_bot_info
        
        super().save(*args, **kwargs)
        
        # Check and update Telegram
        try:
           update_bot_info(self)
        except Exception as e:
           # Log error but don't fail the save
           print(f"Failed to update bot info on Telegram: {e}")

class TelegramUser(models.Model):
    """Keep track of your leads"""
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE)
    chat_id = models.CharField(max_length=50)
    username = models.CharField(max_length=100, null=True, blank=True)
    first_name = models.CharField(max_length=100, null=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('bot', 'chat_id')

class MessageTemplate(models.Model):
    """Custom response templates for upsells/branding"""
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE)
    name = models.CharField(max_length=100) # e.g. "Cross-promo for CasinoBot"
    content = models.TextField(help_text="Variables: {content} (the code/link), {name} (user's name)")

    def __str__(self):
        return f"{self.name} ({self.bot.username})"

class Giveaway(models.Model):
    """The Campaign Container"""
    TYPE_CHOICES = (
        ('standard', 'Standard (Same Link for Everyone)'),
        ('unique', 'Unique (One Code Per User)'),
    )
    REQUIREMENT_CHOICES = (
        ('none', 'No Requirement'),
        ('manual_approval', 'Manual Verification (Screenshot/Proof)'),
        ('questionnaire', 'Questionnaire (Answer Questions)'),
    )

    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE)
    title = models.CharField(max_length=200) # e.g. "Free US TikTok Account"
    description = models.TextField()
    
    giveaway_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    requirement_type = models.CharField(max_length=20, choices=REQUIREMENT_CHOICES)
    
    # For Standard Giveaways (e.g. PDF Link)
    static_content = models.TextField(blank=True, null=True)
    
    # Custom Message
    approval_template = models.ForeignKey(MessageTemplate, blank=True, null=True, on_delete=models.SET_NULL)
    
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

class Questionnaire(models.Model):
    """A question to be asked in a giveaway"""
    giveaway = models.ForeignKey(Giveaway, on_delete=models.CASCADE, related_name='questions')
    text = models.CharField(max_length=300) # e.g. "What is your email?"
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.giveaway.title} - Q: {self.text}"

class UserAnswer(models.Model):
    """Stores user answers"""
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    question = models.ForeignKey(Questionnaire, on_delete=models.CASCADE)
    answer = models.TextField()
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.question.id}"

class GiveawayItem(models.Model):
    """The Inventory (For Unique Codes/Accounts)"""
    giveaway = models.ForeignKey(Giveaway, on_delete=models.CASCADE, related_name='items')
    content = models.CharField(max_length=500) # e.g. "User: admin, Pass: 1234"
    is_used = models.BooleanField(default=False)
    claimed_by = models.ForeignKey(TelegramUser, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.giveaway.title} - {self.content[:20]}"

class GiveawayAttempt(models.Model):
    """The Result/Transaction Log"""
    STATUS_CHOICES = (
        ('pending', 'Pending Approval'),
        ('approved', 'Approved & Sent'),
        ('rejected', 'Rejected'),
    )
    
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    giveaway = models.ForeignKey(Giveaway, on_delete=models.CASCADE)
    
    # If manual approval needed
    user_proof = models.TextField(blank=True, null=True) # Text or File ID
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='approved')
    
    created_at = models.DateTimeField(auto_now_add=True)
    admin_notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user} - {self.giveaway}"

class NewsUpdate(models.Model):
    """Broadcast News"""
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
