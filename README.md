# 🎨 AZ Image Gen Telegram Bot (`@azimagegenbot`)

A production-ready Telegram Bot powered by **Pollinations.ai** that offers free, unlimited AI image generation without requiring an API key.

## ✨ Features

- **Direct Prompt Generation**: Send any text message in chat to generate an AI image.
- **Multiple Models**:
  - `flux`: Ultra-realistic photography and details (Default)
  - `turbo`: Ultra-fast generation
  - `sana`: Creative and stylized art
- **Multiple Aspect Ratios**:
  - `1:1` Square (1024x1024)
  - `9:16` Story / Reel / Mobile Wallpaper (768x1024)
  - `16:9` Landscape / Desktop Wallpaper (1024x768)
  - `4:5` Instagram / Social Media Post (816x1020)
- **Interactive Buttons**:
  - 🔄 **Regenerate**: Instantly rolls a new random seed with the same prompt.
  - 📁 **High-Res File**: Sends the uncompressed high-resolution file as a Telegram document.
  - ⚙️ **Settings**: Quick inline menu to switch active model and resolution.
- **Queue Serializer**: Built-in thread-safe lock respects Pollinations' 1-request-at-a-time per IP limit to avoid rate limits.
- **SQLite Database**: Tracks user preferences and generation history.

## 🛠 Setup & Installation

### 1. Clone & Environment Setup
```bash
git clone https://github.com/beast-69-bot/azimagegenbot.git
cd azimagegenbot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` and insert your Telegram bot token:
```env
POLLINATIONS_BOT_TOKEN="your_bot_token_from_botfather"
```

### 3. Run Locally
```bash
python bot.py
```

### 4. Deploy with PM2 (Production)
```bash
pm2 start .venv/bin/python3 --name "azimagegenbot" -- bot.py
pm2 save
```
