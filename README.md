# 🎨 AZ Image Gen Telegram Bot (`@azimagegenbot`)

A production-ready Telegram Bot offering **free, unlimited AI image generation** powered by a **Dual-Engine architecture**:
1. **⚡ Pollinations.ai**: Ultra-fast (Flux, Turbo, Sana) with relaxed content filters (`safe=false`).
2. **🔞 AI Horde (aihorde.net)**: 100% Uncensored, NSFW-allowed image generation powered by crowdsourced volunteer GPUs.

## ✨ Features

- **Dual-Engine Support**:
  - **⚡ Auto-Fallback (Default)**: Uses fast Pollinations; if a prompt is blocked or errors out, seamlessly switches to AI Horde.
  - **🎨 Pollinations Mode**: High-speed photorealistic generations.
  - **🔞 AI Horde Mode**: Truly uncensored generations with zero corporate filters.
- **Multiple Models**:
  - `flux`: Ultra-realistic photography and fine details.
  - `turbo`: Ultra-fast generation.
  - `sana`: Creative and stylized art.
  - `Uncensored SD Checkpoints`: via AI Horde.
- **Multiple Aspect Ratios**:
  - `1:1` Square (1024x1024)
  - `9:16` Story / Reel / Mobile Wallpaper (768x1024)
  - `16:9` Landscape / Desktop Wallpaper (1024x768)
  - `4:5` Instagram / Social Media Post (816x1020)
- **Interactive Action Buttons**:
  - 🔄 **Regenerate**: Instantly rolls a new random seed with the same prompt.
  - 📁 **High-Res File**: Sends the uncompressed high-resolution file as a Telegram document.
  - ⚙️ **Settings**: Inline menu to switch active engine, model, and resolution.
- **Database Tracking**: SQLite database tracks user preferences and generation history.

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
Create `.env`:
```env
POLLINATIONS_BOT_TOKEN="your_bot_token_from_botfather"
AI_HORDE_KEY="0000000000"
LOG_LEVEL="INFO"
```

### 3. Deploy with PM2 (Production)
```bash
pm2 start .venv/bin/python3 --name "azimagegenbot" -- bot.py
pm2 save
```
