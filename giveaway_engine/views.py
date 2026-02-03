import logging
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from .models import TelegramBot, TelegramUser, Giveaway, GiveawayItem, GiveawayAttempt, NewsUpdate
from .utils import send_telegram_message

logger = logging.getLogger(__name__)

class TelegramWebhookView(APIView):
    """
    Main webhook handler for Telegram updates.
    """
    permission_classes = [] # Public endpoint for Telegram to call

    def post(self, request, token):
        # Identify the bot by token
        bot = get_object_or_404(TelegramBot, token=token, is_active=True)
        
        data = request.data
        message = data.get('message', {})
        
        if not message:
            return Response(status=status.HTTP_200_OK)

        chat_data = message.get('chat', {})
        chat_id = str(chat_data.get('id'))
        user_data = message.get('from', {})
        username = user_data.get('username')
        first_name = user_data.get('first_name')
        text = message.get('text', '').strip()
        parts = text.split()
        photo = message.get('photo')

        contact = message.get('contact')

        # 1. Get or Create TelegramUser
        user, created = TelegramUser.objects.get_or_create(
            bot=bot,
            chat_id=chat_id,
            defaults={
                'username': username,
                'first_name': first_name
            }
        )
        # Update user details if changed
        if not created:
            if user.username != username or user.first_name != first_name:
                user.username = username
                user.first_name = first_name
                user.save()
        
                user.save()
 
        # Check for Resume Choice State
        resume_giveaway_id = cache.get(f"waiting_for_resume_choice_{chat_id}")
        if resume_giveaway_id and text:
            # Clear state
            cache.delete(f"waiting_for_resume_choice_{chat_id}")
            
            try:
                giveaway = Giveaway.objects.get(id=resume_giveaway_id)
                if text.lower() == 'yes':
                    # Delete answers and restart
                    from .models import UserAnswer
                    UserAnswer.objects.filter(user=user, question__giveaway=giveaway).delete()
                    # Clear any other state
                    cache.delete(f"current_q_{chat_id}")
                    # Restart flow
                    self.handle_claim(bot, user, chat_id, str(giveaway.sequence))
                else:
                    # Proceed with existing answers
                    # Send success message if configured (as per previous logic)
                    if giveaway.success_template:
                         try:
                            msg = giveaway.success_template.content.format(name=user.first_name or "Friend")
                            send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
                         except Exception as e:
                            logger.error(f"Error sending success template: {e}")
                            
                    self.fulfill_giveaway(bot, user, chat_id, giveaway)
                
                return Response(status=status.HTTP_200_OK)
            except Giveaway.DoesNotExist:
                pass
                
        if contact:
            phone_number = contact.get('phone_number')
            if phone_number:
                user.phone_number = phone_number
                user.save()
                self.handle_contact_update(bot, user, chat_id)
                # Return immediately after handling contact to avoid double processing
                return Response(status=status.HTTP_200_OK)

        # 2. Log Inbound Message
        if text:
            from .models import MessageLog
            MessageLog.objects.create(
                user=user,
                bot=bot,
                content=text,
                direction='inbound'
            )

        # 3. Logic Flow
        
        # Scenario A: /start
        if text == '/start':
            self.handle_start(bot, user, chat_id, first_name)
            
        # Commands like /claim_123 OR just 123 OR 123 something
        elif text.startswith('/claim_') or (parts and parts[0].isdigit()):
            self.handle_claim(bot, user, chat_id, text)
            
        # Scenario C (Part 2): Receiving Proof (Photo or Text)
        elif photo or (text and not text.startswith('/')):
            self.handle_proof(bot, user, chat_id, message)
            
        else:
            # Unknown command or interaction
            pass

        return Response(status=status.HTTP_200_OK)

    def find_target_giveaway(self, bot, user):
        """
        Identify the next logical giveaway (by sequence) that the user hasn't successfully completed.
        """
        active_giveaways = Giveaway.objects.filter(bot=bot, is_active=True).order_by('sequence')
        for g in active_giveaways:
            # Check if already has approved/pending attempt
            if GiveawayAttempt.objects.filter(user=user, giveaway=g, status__in=['approved', 'pending']).exists():
                continue
            
            # This is the next logical target (prereqs will be checked by handle_claim/handle_proof)
            return g
        return None

    def handle_start(self, bot, user, chat_id, name):
        # Fetch Active Giveaways with a sequence
        giveaways = Giveaway.objects.filter(bot=bot, is_active=True, sequence__isnull=False)
        logger.info(f"Bot {bot.username} handling /start for user {name}. Found {giveaways.count()} active giveaways.")
        
        # Fetch Latest News
        news = NewsUpdate.objects.filter(bot=bot).order_by('-sent_at').first()
        
        # Build Message
        msg = f"👋 Welcome {name}!\n\n"
        
        if news:
            msg += f"📰 Latest News: {news.title}\n{news.body}\n\n"
            
        if giveaways.exists():
            msg += f"{bot.start_message_header}\n\n"
            for g in giveaways:
                msg += f"{g.title} - Reply {g.sequence}\n\n"
        else:
            logger.warning(f"No active giveaways found for bot {bot.username}")
            msg += "No active giveaways at the moment."
            
        send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)

    def handle_claim(self, bot, user, chat_id, text):
        parts = text.split()
        giveaway_seq = None
        user_proof = ""

        if text.startswith('/claim_'):
            try:
                giveaway_seq = int(text.split('_')[1])
            except (IndexError, ValueError):
                pass
        elif parts and parts[0].isdigit():
            giveaway_seq = int(parts[0])
            user_proof = " ".join(parts[1:]).strip()

        try:
            giveaway = Giveaway.objects.get(sequence=giveaway_seq, bot=bot, is_active=True)
        except (Giveaway.DoesNotExist):
            send_telegram_message(bot.token, chat_id, "Giveaway not found or inactive.", bot=bot, user=user)
            return

        # Prerequisite check
        if giveaway.pre_giveaway:
            # Must have approved attempts for all active giveaways with sequence <= giveaway.pre_giveaway
            prereqs = Giveaway.objects.filter(bot=bot, is_active=True, sequence__lte=giveaway.pre_giveaway)
            missing_titles = []
            missing_sequences = []
            
            for pr in prereqs:
                if not GiveawayAttempt.objects.filter(user=user, giveaway=pr, status='approved').exists():
                    missing_titles.append(f"[{pr.title}]")
                    missing_sequences.append(str(pr.sequence))
            
            if missing_sequences:
                if giveaway.failure_template:
                    msg = giveaway.failure_template.content.format(
                        name=user.first_name or "Friend"
                    )
                else:
                    seq_str = " and ".join([", ".join(missing_sequences[:-1]), missing_sequences[-1]] if len(missing_sequences) > 1 else missing_sequences)
                    msg = f"⚠️ Please start with {seq_str} first!"
                
                send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
                return

        # Check for Retake Logic
        # If user has already claimed (approved/pending), check if retake is allowed.
        if GiveawayAttempt.objects.filter(user=user, giveaway=giveaway, status__in=['approved', 'pending']).exists():
            if not giveaway.allow_retake:
                send_telegram_message(bot.token, chat_id, "✅ You have already claimed this giveaway.", bot=bot, user=user)
                return
            # If allow_retake is True, we proceed. 
            # The logic below will detect existing answers and Prompt "Update Answers?" logic we added earlier.

        # Handle Manual Approval Flow
        if giveaway.requirement_type == 'manual_approval':
            if not user_proof:
                # Store intent
                cache_key = f"claim_intent_{chat_id}"
                cache.set(cache_key, giveaway.id, timeout=600)
                
                if giveaway.prompt_template:
                    msg = giveaway.prompt_template.content.format(name=user.first_name or "Friend")
                else:
                    msg = "Please send your proof (screenshot/text) now."
                send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
                return
            else:
                # Process proof
                GiveawayAttempt.objects.create(
                    user=user,
                    giveaway=giveaway,
                    status='pending',
                    user_proof=user_proof
                )
                if giveaway.success_template:
                    msg = giveaway.success_template.content.format(name=user.first_name or "Friend")
                else:
                    msg = "Proof received! An admin will verify shortly."
                send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
                return


        # Check Questionnaire Requirement
        if giveaway.requirement_type == 'questionnaire':
             # Check if all questions are answered
             questions = giveaway.questions.all().order_by('order')
             if not questions.exists():
                 # No questions? Fulfill immediately.
                 self.fulfill_giveaway(bot, user, chat_id, giveaway)
                 return

             # Find first unanswered user question
             from .models import UserAnswer # Import here to avoid circular
             
             # Get all answer texts for this user + giveaway
             # We can't filter UserAnswer by giveaway directly easily unless we join through Question.
             answered_q_ids = UserAnswer.objects.filter(
                 user=user, 
                 question__giveaway=giveaway
             ).values_list('question_id', flat=True)

             next_q = None
             for q in questions:
                 if q.id not in answered_q_ids:
                     next_q = q
                     break
            
             if next_q:
                 # Ask this question
                 cache_key = f"claim_intent_{chat_id}"
                 cache.set(cache_key, giveaway.id, timeout=3600)  # 1 hour to answer
                 # Also store which question we are asking
                 cache.set(f"current_q_{chat_id}", next_q.id, timeout=3600)
                 # NEW: Set flag that we are actively answering
                 cache.set(f"user_is_answering_{chat_id}", True, timeout=3600)
                 
                 send_telegram_message(bot.token, chat_id, f"📝 Question: {next_q.text}", bot=bot, user=user)
                 return
             else:
                 # All answered
                 # CHECK: Do we have answers already? (Resume Logic)
                 # We must verify if we just finished answering OR if this is a retake
                 # If we just answered the last question, current_q might still be set or cleared?
                 # Actually, handle_claim calls recursively after saving answer.
                 # So we need to distinguish "Just finished last Q" vs "Started fresh with all Qs answered"
                 
                 # Simplest heuristic: Check if we are in "waiting_for_resume_choice" - handled in post
                 # Check if we just answered a question (cache might help? or passing a flag? handle_claim signature doesn't support it well)
                 
                 # BETTER APPROACH:
                 # If we are here, it means NO unanswered questions exist.
                 # IF we *just* answered a question, `handle_proof` called `handle_claim`.
                 
                 # Let's check if the USER initiated this claim command primarily (text starts with /claim or is a number)
                 # VS coming from handle_proof logic.
                 # Actually, existing logic:
                 # handle_proof saves answer -> calls handle_claim.
                 
                 # If we want to prompt "Do you want to update?", we should only do it if the user explicit invoked the claim
                 # AND all answers already existed.
                 
                 # But handle_claim is called recursively.
                 
                 # Let's add a cached flag "user_is_answering_{chat_id}" that is set when we ask a question.
                 # If that flag is set, it means we are in the middle of a flow, so don't prompt.
                 # If that flag is NOT set, and all answers exist, Prompt.
                 
                 is_answering = cache.get(f"user_is_answering_{chat_id}")
                 
                 # If we are NOT in the middle of answering (flag missing) AND we have answers:
                 if not is_answering and UserAnswer.objects.filter(user=user, question__giveaway=giveaway).exists():
                     # **RACE CONDITION FIX**: Check if the last answer was just submitted (e.g. < 10 seconds ago)
                     last_answer = UserAnswer.objects.filter(user=user, question__giveaway=giveaway).order_by('-answered_at').first()
                     if last_answer:
                         from django.utils import timezone
                         from datetime import timedelta
                         # If answered less than 10 seconds ago, this is likely a race condition of the final answer request.
                         # Treat it as 'Just Finished' -> Proceed to success, do NOT prompt.
                         if timezone.now() - last_answer.answered_at < timedelta(seconds=10):
                             # Proceed to normal flow below
                             pass
                         else:
                             # Truly old answers, so Prompt.
                             cache.set(f"waiting_for_resume_choice_{chat_id}", giveaway.id, timeout=600)
                             
                             keyboard = {
                                "keyboard": [[{"text": "Yes"}, {"text": "No"}]],
                                "one_time_keyboard": True,
                                "resize_keyboard": True
                             }
                             send_telegram_message(
                                 bot.token, 
                                 chat_id, 
                                 "📝 We found previous answers. Do you want to update them?", 
                                 reply_markup=keyboard,
                                 bot=bot, 
                                 user=user
                             )
                             return
                     else:
                        # Should not happen given exists() check but safe fallback
                        pass

                 # Normal Finish Flow
                 cache.delete(f"user_is_answering_{chat_id}") # Clear flag if exists
                 
                 # Check for success template
                 if giveaway.success_template:
                     try:
                        msg = giveaway.success_template.content.format(name=user.first_name or "Friend")
                        send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
                     except Exception as e:
                        logger.error(f"Error sending success template: {e}")

                 self.fulfill_giveaway(bot, user, chat_id, giveaway)
                 return

        # Check Phone Number Requirement First
        if giveaway.requirement_type == 'phone_number':
            if not user.phone_number:
                # Store intent
                cache_key = f"claim_intent_{chat_id}"
                cache.set(cache_key, giveaway.id, timeout=600)
                
                # Ask for phone
                keyboard = {
                    "keyboard": [[{
                        "text": "📱 Share Phone Number",
                        "request_contact": True
                    }]],
                    "one_time_keyboard": True,
                    "resize_keyboard": True
                }
                send_telegram_message(
                    bot.token, 
                    chat_id, 
                    f"⚠️ This giveaway requires a mobile number to minimize spam.\nPlease tap the button below to verify your number.",
                    reply_markup=keyboard,
                    bot=bot,
                    user=user
                )
                return
            # If phone exists, proceed to fulfillment (Scenario B logic mostly)
        
        # FULFILLMENT Logic (Refactored)
        self.fulfill_giveaway(bot, user, chat_id, giveaway)

    def fulfill_giveaway(self, bot, user, chat_id, giveaway):
        # Scenario B (Standard + None/Phone/Questionnaire)
        if giveaway.giveaway_type == 'standard':
             send_telegram_message(bot.token, chat_id, giveaway.static_content, bot=bot, user=user)
             GiveawayAttempt.objects.create(
                user=user,
                giveaway=giveaway,
                status='approved'
             )

        # Scenario C (Manual Proof)
        elif giveaway.requirement_type == 'manual_approval':
            # Store intent in cache for 10 minutes
            cache_key = f"claim_intent_{chat_id}"
            cache.set(cache_key, giveaway.id, timeout=600)
            
            send_telegram_message(bot.token, chat_id, "Please send your proof (screenshot/text) now.", bot=bot, user=user)
            
        # Unique + Automated (Phone or Questionnaire or None)
        elif giveaway.giveaway_type == 'unique':
                 item = GiveawayItem.objects.filter(giveaway=giveaway, is_used=False).first()
                 if item:
                    item.is_used = True
                    item.claimed_by = user
                    item.save()
                    
                    msg = f"✅ Verified! Here is your code:\n{item.content}"
                    
                    # Check for template
                    if giveaway.approval_template:
                        try:
                            msg = giveaway.approval_template.content.format(
                                content=item.content,
                                name=user.first_name or "Friend"
                            )
                        except:
                            pass

                    send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
                    
                    GiveawayAttempt.objects.create(
                        user=user,
                        giveaway=giveaway,
                        status='approved'
                    )
                 else:
                     send_telegram_message(bot.token, chat_id, "⚠️ Sorry, we are out of stock right now!", bot=bot, user=user)

        else:
            send_telegram_message(bot.token, chat_id, "This giveaway configuration is not fully supported yet.", bot=bot, user=user)

    def handle_contact_update(self, bot, user, chat_id):
        # Remove keyboard
        remove_kb = {"remove_keyboard": True}
        send_telegram_message(bot.token, chat_id, "✅ Phone Number Verified!", reply_markup=remove_kb, bot=bot, user=user)
        
        # Check for pending claim
        cache_key = f"claim_intent_{chat_id}"
        giveaway_id = cache.get(cache_key)
        
        if giveaway_id:
            try:
                giveaway = Giveaway.objects.get(id=giveaway_id)
                # Verify requirement is actually phone number (security check)
                if giveaway.requirement_type == 'phone_number':
                    self.fulfill_giveaway(bot, user, chat_id, giveaway)
                    cache.delete(cache_key)
            except Giveaway.DoesNotExist:
                pass

    def handle_proof(self, bot, user, chat_id, message):
        cache_key = f"claim_intent_{chat_id}"
        giveaway_id = cache.get(cache_key)
        
        giveaway = None
        if giveaway_id:
            try:
                giveaway = Giveaway.objects.get(id=giveaway_id)
            except Giveaway.DoesNotExist:
                pass
        
        if not giveaway:
            # Auto-detect target for "loose" proof
            giveaway = self.find_target_giveaway(bot, user)
            
        if not giveaway:
             # Could not find a target for floating proof
             send_telegram_message(bot.token, chat_id, "We've received your message, but it doesn't seem to be for a specific giveaway.", bot=bot, user=user)
             return

        # Prerequisite check (Crucial for auto-detection safety)
        if giveaway.pre_giveaway:
            prereqs = Giveaway.objects.filter(bot=bot, is_active=True, sequence__lte=giveaway.pre_giveaway)
            missing = []
            for pr in prereqs:
                if not GiveawayAttempt.objects.filter(user=user, giveaway=pr, status='approved').exists():
                    missing.append(str(pr.sequence))
            
            if missing:
                if giveaway.failure_template:
                    msg = giveaway.failure_template.content.format(name=user.first_name or "Friend")
                else:
                    seq_str = " and ".join([", ".join(missing[:-1]), missing[-1]] if len(missing) > 1 else missing)
                    msg = f"⚠️ Please start with {seq_str} first!"
                send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
                return

        # Verify this giveaway actually accepts this kind of input
        if giveaway.requirement_type != 'manual_approval' and giveaway.requirement_type != 'questionnaire':
             send_telegram_message(bot.token, chat_id, f"⚠️ Giveaway '{giveaway.title}' requires a different claim method ({giveaway.requirement_type}).", bot=bot, user=user)
             return
            
        # QUESTIONNAIRE LOGIC
        if giveaway.requirement_type == 'questionnaire':
             # We are expecting an answer
             current_q_id = cache.get(f"current_q_{chat_id}")
             if current_q_id and 'text' in message:
                 from .models import Questionnaire, UserAnswer
                 try:
                     question = Questionnaire.objects.get(id=current_q_id)
                     # Save Answer
                     UserAnswer.objects.create(
                         user=user, 
                         question=question,
                         answer=message['text']
                     )
                     # Loop back to check for next question
                     self.handle_claim(bot, user, chat_id, str(giveaway.sequence))
                     return 
                 except Questionnaire.DoesNotExist:
                     pass
        
        # Extract Proof (Manual Approval)
        proof = ""
        if 'photo' in message:
            # Get the largest photo file_id
            proof = message['photo'][-1]['file_id']
        elif 'text' in message:
            proof = message['text']
            
        # Create Attempt for Manual Approval
        if giveaway.requirement_type == 'manual_approval':
            GiveawayAttempt.objects.create(
                user=user,
                giveaway=giveaway,
                status='pending',
                user_proof=proof
            )
            
            # Clear cache
            cache.delete(cache_key)
            
            if giveaway.success_template:
                msg = giveaway.success_template.content.format(name=user.first_name or "Friend")
            else:
                msg = "Proof received! An admin will verify shortly."
            send_telegram_message(bot.token, chat_id, msg, bot=bot, user=user)
