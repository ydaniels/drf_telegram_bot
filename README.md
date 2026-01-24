# Telegram Giveaway Engine

A Django-based engine to run multiple Telegram giveaway campaigns (bots) from a single backend.

## Features
- Manage multiple bots
- Standard giveaways (same link for everyone)
- Unique giveaways (one unique code per user)
- Manual approval workflow
- Broadcasting news

## Installation

```bash
pip install git+https://github.com/yourusername/giveaway_engine.git
```

## Setup

1. Add `giveaway_engine` and `rest_framework` to `INSTALLED_APPS`.
2. Run `python manage.py migrate`.
3. Configure your bots in Django Admin.
4. Set up the webhook: `https://your-domain.com/webhook/<bot_token>/`

## Usage

Create a `TelegramBot` in admin, get the token from BotFather, and set up the webhook.
Create `Giveaway` campaigns.
Add `GiveawayItem`s for unique codes.
