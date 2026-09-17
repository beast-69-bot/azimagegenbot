import io
import os
import time
import logging
import threading
from pathlib import Path
from telebot import TeleBot, types

import config
import database
import pollinations_client
import horde_client
import faceswap

logger = logging.getLogger("azimagegenbot.handlers")

# Concurrency lock to serialize heavy generation tasks
generation_lock = threading.Lock()

# User in-memory session states for multi-step Face Swap
# user_states[user_id] = { "step": "awaiting_target" | "awaiting_prompt", "source_photo": bytes, "time": timestamp }
user_states = {}

def get_settings_keyboard(user_id: int) -> types.InlineKeyboardMarkup:
    """Builds inline keyboard reflecting user's current settings."""
    settings = database.get_user_settings(user_id)
    cur_engine = settings.get("engine", config.DEFAULT_ENGINE)
    cur_model = settings["model"]
    cur_ratio = settings["ratio"]

    kb = types.InlineKeyboardMarkup(row_width=2)
    
    # Engine buttons
    engine_btns = []
    engine_labels = {
        "auto": "⚡ Auto-Fallback",
        "pollinations": "🎨 Pollinations",
        "aihorde": "🔞 AI Horde (NSFW)"
    }
    for eng_key, short_label in engine_labels.items():
        is_active = (eng_key == cur_engine)
        btn_text = f"✅ {short_label}" if is_active else short_label
        engine_btns.append(types.InlineKeyboardButton(text=btn_text, callback_data=f"set_engine|{eng_key}"))
    kb.row(*engine_btns[:2])
    kb.row(engine_btns[2])

    # Model buttons
    model_buttons = []
    for model_key, label in config.AVAILABLE_MODELS.items():
        is_active = (model_key == cur_model)
        btn_text = f"✅ {model_key.upper()}" if is_active else model_key.upper()
        model_buttons.append(types.InlineKeyboardButton(text=btn_text, callback_data=f"set_model|{model_key}"))
    kb.add(*model_buttons)

    # Ratio buttons
    ratio_buttons = []
    for ratio_key, info in config.AVAILABLE_RATIOS.items():
        is_active = (ratio_key == cur_ratio)
        btn_text = f"✅ {ratio_key}" if is_active else ratio_key
        ratio_buttons.append(types.InlineKeyboardButton(text=btn_text, callback_data=f"set_ratio|{ratio_key}"))
    kb.add(*ratio_buttons)

    # Help & Close
    kb.row(
        types.InlineKeyboardButton("❓ Help", callback_data="open_help"),
        types.InlineKeyboardButton("❌ Close", callback_data="close_settings")
    )
    return kb


def format_settings_text(user_id: int) -> str:
    settings = database.get_user_settings(user_id)
    engine = settings.get("engine", config.DEFAULT_ENGINE)
    model = settings["model"]
    ratio = settings["ratio"]
    ratio_info = config.AVAILABLE_RATIOS.get(ratio, {})
    dim = f"{ratio_info.get('width', 1024)}x{ratio_info.get('height', 1024)}"

    engine_name = config.AVAILABLE_ENGINES.get(engine, engine)

    return (
        f"⚙️ *AI Generator Settings*\n\n"
        f"⚡ *Engine:* `{engine_name}`\n"
        f"🤖 *Model:* `{model.upper()}` ({config.AVAILABLE_MODELS.get(model, model)})\n"
        f"📐 *Aspect Ratio:* `{ratio}` ({dim} px)\n\n"
        f"Tap the buttons below to change engine, model or resolution:"
    )


def register_handlers(bot: TeleBot):

    # -----------------------------------------------------------------------
    # /start
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['start'])
    def handle_start(message: types.Message):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name or "User"
        database.add_or_update_user(user_id, username)

        welcome_text = (
            f"👋 *Welcome to AI Image Generator & Face Swap Bot!*, {username}\n\n"
            f"⚡ *Features Available:*\n"
            f"1. 🎨 *Text-to-Image*: Send any prompt to generate realistic & artistic AI images.\n"
            f"2. 🎭 *Face Swap*: Swap any face into a target photo or generate custom scenes with your face!\n"
            f"3. 🔞 *Dual Engine*: Fast Pollinations + Uncensored AI Horde support.\n\n"
            f"🚀 *Quick Ways to Use:*\n"
            f"• Send **any prompt text** to generate an image.\n"
            f"• Send a **Photo with a Caption** (e.g. `superhero in armor`) to generate with your face!\n"
            f"• Use `/faceswap` for step-by-step photo swapping.\n\n"
            f"⚙️ *Commands:*\n"
            f"/faceswap - Open Face Swap Menu\n"
            f"/engine - Choose generation engine\n"
            f"/model - Choose AI model (Flux, Turbo, Sana)\n"
            f"/ratio - Change aspect ratio\n"
            f"/settings - Configure preferences\n"
            f"/cancel - Cancel any ongoing swap\n"
            f"/help - Complete guide"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(
            types.InlineKeyboardButton("🎭 Face Swap", callback_data="menu_faceswap"),
            types.InlineKeyboardButton("⚡ Engine", callback_data="menu_engine")
        )
        kb.row(
            types.InlineKeyboardButton("🤖 Model", callback_data="menu_model"),
            types.InlineKeyboardButton("📐 Ratio", callback_data="menu_ratio")
        )
        kb.row(
            types.InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
            types.InlineKeyboardButton("❓ Help", callback_data="open_help")
        )
        bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=kb)

    # -----------------------------------------------------------------------
    # /faceswap or /swap
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['faceswap', 'swap'])
    def handle_faceswap_command(message: types.Message):
        user_id = message.from_user.id
        # Clear previous state if any
        if user_id in user_states:
            del user_states[user_id]

        text = (
            f"🎭 *Face Swap Menu*\n\n"
            f"Aap 2 alag tareeko se Face Swap kar sakte hain:\n\n"
            f"1️⃣ *Photo-to-Photo Swap:*\n"
            f"Apna chehra kisi doosri photo (body/dress/template) par lagayein.\n\n"
            f"2️⃣ *Face + Prompt Generation:*\n"
            f"Apna chehra dekar prompt likhein (jaise _in king armor_), AI nayi photo banakar aapka chehra uspar laga dega!\n\n"
            f"👉 *Neeche diye gaye buttons me se ek chunein:*"
        )

        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🖼 1. Photo-to-Photo Swap", callback_data="start_photo_swap"),
            types.InlineKeyboardButton("✍️ 2. Face + Prompt Generation", callback_data="start_prompt_swap"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_swap")
        )
        bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

    # -----------------------------------------------------------------------
    # /cancel
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['cancel'])
    def handle_cancel(message: types.Message):
        user_id = message.from_user.id
        if user_id in user_states:
            del user_states[user_id]
            bot.reply_to(message, "✅ Face swap operation cancel kar di gayi hai. Aap normal prompts bhej sakte hain.")
        else:
            bot.reply_to(message, "Koi active face swap operation nahi chal rahi thi.")

    # -----------------------------------------------------------------------
    # /help
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['help'])
    def handle_help(message: types.Message):
        help_text = (
            "📖 *AZ Image Gen & Face Swap Bot — Complete Guide*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎨 *1. AI Image Generation (Prompt se Photo)*\n"
            "• *Purpose:* Nayi AI art ya photorealistic images generate karna.\n"
            "• *Kaise karein:* Koi command zaroori nahi hai! Bas seedha chat me apna prompt likhein.\n"
            "  _Example:_ `cyberpunk warrior girl in neon street, 8k hyperrealistic`\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎭 *2. Face Swapping (/faceswap)*\n"
            "• *Purpose:* Chehra badalna ya kisi nayi AI photo me lagana.\n\n"
            "🔹 *Mode A: Photo-to-Photo Swap*\n"
            "  1. `/faceswap` send karein aur *'1. Photo-to-Photo'* chunein.\n"
            "  2. Pehle apni *Face Photo* bhejein (jiska chehra lagana hai).\n"
            "  3. Fir *Target Photo* bhejein (jisme chehra lagana hai, e.g. model/suit).\n\n"
            "🔹 *Mode B: Face + Prompt AI Swap*\n"
            "  1. `/faceswap` send karein aur *'2. Face + Prompt'* chunein.\n"
            "  2. Apni Face Photo bhejein, fir prompt likhein (jaise `in royal golden armour`).\n"
            "  ⚡ *Direct Shortcut:* Apni photo bhejte waqt caption me prompt likh dein, bot turant nayi image me aapka chehra fit kar dega!\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ *3. Commands & Settings*\n"
            "• `/faceswap` — Face swap menu aur modes open karein.\n"
            "• `/engine` — Generation engine chunein (Auto / Pollinations / AI Horde NSFW).\n"
            "• `/model` — Model badlein (`FLUX` for best quality, `TURBO` for speed, `SANA` for artistic).\n"
            "• `/ratio` — Aspect Ratio set karein (`1:1` Square, `9:16` Story/Reel, `16:9` Wallpaper, `4:5` Portrait).\n"
            "• `/settings` — Saari settings ek sath interactive panel me manage karein.\n"
            "• `/history` — Apni pichli 5 generated images aur unke prompts dekhein.\n"
            "• `/stats` — Total bot usage statistics dekhein.\n"
            "• `/cancel` — Kisi bhi ongoing face swap session ko cancel karein.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, help_text, parse_mode="Markdown")

    # -----------------------------------------------------------------------
    # /engine
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['engine'])
    def handle_engine(message: types.Message):
        user_id = message.from_user.id
        settings = database.get_user_settings(user_id)
        cur_engine = settings.get("engine", config.DEFAULT_ENGINE)

        kb = types.InlineKeyboardMarkup(row_width=1)
        for key, name in config.AVAILABLE_ENGINES.items():
            is_active = (key == cur_engine)
            kb.add(types.InlineKeyboardButton(
                text=f"{'✅ ' if is_active else ''}{name}",
                callback_data=f"set_engine|{key}"
            ))
        bot.reply_to(message, "⚡ *Select your generation engine:*", parse_mode="Markdown", reply_markup=kb)

    # -----------------------------------------------------------------------
    # /model
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['model'])
    def handle_model(message: types.Message):
        user_id = message.from_user.id
        settings = database.get_user_settings(user_id)
        cur_model = settings["model"]

        kb = types.InlineKeyboardMarkup(row_width=1)
        for key, name in config.AVAILABLE_MODELS.items():
            is_active = (key == cur_model)
            kb.add(types.InlineKeyboardButton(
                text=f"{'✅ ' if is_active else ''}{name}",
                callback_data=f"set_model|{key}"
            ))
        bot.reply_to(message, "🤖 *Select your preferred AI Image Model:*", parse_mode="Markdown", reply_markup=kb)

    # -----------------------------------------------------------------------
    # /ratio or /size
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['ratio', 'size'])
    def handle_ratio(message: types.Message):
        user_id = message.from_user.id
        settings = database.get_user_settings(user_id)
        cur_ratio = settings["ratio"]

        kb = types.InlineKeyboardMarkup(row_width=1)
        for key, info in config.AVAILABLE_RATIOS.items():
            is_active = (key == cur_ratio)
            kb.add(types.InlineKeyboardButton(
                text=f"{'✅ ' if is_active else ''}{info['label']} ({info['width']}x{info['height']})",
                callback_data=f"set_ratio|{key}"
            ))
        bot.reply_to(message, "📐 *Select your preferred Aspect Ratio:*", parse_mode="Markdown", reply_markup=kb)

    # -----------------------------------------------------------------------
    # /settings
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['settings'])
    def handle_settings(message: types.Message):
        user_id = message.from_user.id
        text = format_settings_text(user_id)
        kb = get_settings_keyboard(user_id)
        bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

    # -----------------------------------------------------------------------
    # /stats
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['stats'])
    def handle_stats(message: types.Message):
        stats = database.get_global_stats()
        text = (
            f"📊 *Bot Generation Statistics*\n\n"
            f"👥 *Total Users:* {stats['total_users']}\n"
            f"✅ *Successful Generations:* {stats['total_success']}\n"
            f"⚠️ *Failed Requests:* {stats['total_failed']}\n"
        )
        bot.reply_to(message, text, parse_mode="Markdown")

    # -----------------------------------------------------------------------
    # /history
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['history'])
    def handle_history(message: types.Message):
        user_id = message.from_user.id
        rows = database.get_user_history(user_id, limit=5)
        if not rows:
            bot.reply_to(message, "📜 You have not generated any images yet! Send any prompt to begin.")
            return

        text = "📜 *Your Recent Generations:*\n\n"
        for i, row in enumerate(rows, 1):
            p = row["prompt"]
            if len(p) > 60:
                p = p[:57] + "..."
            text += f"*{i}.* `{p}`\n   Model: {row['model']} | {row['width']}x{row['height']} | Seed: {row['seed']}\n\n"

        bot.reply_to(message, text, parse_mode="Markdown")

    # -----------------------------------------------------------------------
    # Photo Message Handler (Handles Face Swapping & Face+Caption shortcuts)
    # -----------------------------------------------------------------------
    @bot.message_handler(content_types=['photo'])
    def handle_photo_message(message: types.Message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        username = message.from_user.username or message.from_user.first_name or "User"
        database.add_or_update_user(user_id, username)

        # Download photo bytes (largest size)
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            photo_bytes = bot.download_file(file_info.file_path)
        except Exception as e:
            bot.reply_to(message, f"❌ Photo download karne me error aaya: {e}")
            return

        state = user_states.get(user_id)

        # 1. User was waiting for Target Photo (Photo-to-Photo Swap)
        if state and state.get("step") == "awaiting_target":
            source_bytes = state.get("source_photo")
            del user_states[user_id]
            process_photo_swap(bot, chat_id, user_id, source_bytes, photo_bytes, reply_to_id=message.message_id)
            return

        # 2. User has a caption on the photo -> Direct Shortcut for Face + Prompt!
        caption = (message.caption or "").strip()
        if caption:
            if user_id in user_states:
                del user_states[user_id]
            process_face_prompt_swap(bot, chat_id, user_id, photo_bytes, caption, reply_to_id=message.message_id)
            return

        # 3. User was in awaiting_prompt mode but sent another photo
        if state and state.get("step") == "awaiting_prompt":
            user_states[user_id]["source_photo"] = photo_bytes
            bot.reply_to(
                message,
                "📸 *New Face Photo Saved!*\n\nAb apna **Prompt text** likhkar bhejiye (e.g. `A wealthy prince in palace, 8k portrait`):",
                parse_mode="Markdown"
            )
            return

        # 4. Standalone photo with NO caption and NO active mode:
        # Save as potential source photo and present interactive choice
        user_states[user_id] = {
            "source_photo": photo_bytes,
            "step": "photo_received",
            "time": time.time()
        }

        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🖼 1. Doosri Photo par Lagao (Target Swap)", callback_data="state_to_target"),
            types.InlineKeyboardButton("✍️ 2. Prompt se Scene Banao (Face + Prompt)", callback_data="state_to_prompt"),
            types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_swap")
        )
        bot.reply_to(
            message,
            "📸 *Face Photo Receive Ho Gayi!*\n\nAb aap is photo ke sath kya karna chahte hain?",
            parse_mode="Markdown",
            reply_markup=kb
        )

    # -----------------------------------------------------------------------
    # Direct text prompt generation (/gen or plain text message)
    # -----------------------------------------------------------------------
    @bot.message_handler(func=lambda msg: msg.text and not msg.text.startswith('/'))
    @bot.message_handler(commands=['gen', 'generate', 'draw'])
    def handle_text_message(message: types.Message):
        user_id = message.from_user.id
        chat_id = message.chat.id
        username = message.from_user.username or message.from_user.first_name or "User"
        database.add_or_update_user(user_id, username)

        text = message.text.strip()
        if text.startswith('/'):
            parts = text.split(' ', 1)
            if len(parts) < 2 or not parts[1].strip():
                bot.reply_to(message, "⚠️ Please provide a prompt after the command, e.g.:\n`/gen a neon cybernetic tiger`", parse_mode="Markdown")
                return
            prompt = parts[1].strip()
        else:
            prompt = text

        state = user_states.get(user_id)

        # Check if user was in awaiting_prompt state for Face + Prompt swap
        if state and state.get("step") == "awaiting_prompt":
            source_bytes = state.get("source_photo")
            del user_states[user_id]
            process_face_prompt_swap(bot, chat_id, user_id, source_bytes, prompt, reply_to_id=message.message_id)
            return

        # Normal text-to-image generation
        process_text_generation(bot, chat_id, user_id, prompt, reply_to_message_id=message.message_id)

    # -----------------------------------------------------------------------
    # Core Method 1: Photo-to-Photo Face Swapping Worker
    # -----------------------------------------------------------------------
    def process_photo_swap(bot: TeleBot, chat_id: int, user_id: int, source_bytes: bytes, target_bytes: bytes, reply_to_id: int = None):
        status_msg = bot.send_message(
            chat_id,
            "🎭 *Face Swapping in progress...*\n\nDetecting facial features and blending face into target photo...\n⏳ _1-3 seconds..._",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_id
        )

        def worker():
            nonlocal status_msg
            start_t = time.time()
            try:
                bot.send_chat_action(chat_id, 'upload_photo')
                swapped_bytes = faceswap.swap_face(source_bytes, target_bytes)
                elapsed = round(time.time() - start_t, 1)

                safe_name = f"faceswap_{user_id}_{int(time.time())}.jpg"
                file_path = config.TEMP_PATH / safe_name
                file_path.write_bytes(swapped_bytes)

                caption = (
                    f"🎭 *Face Swap Completed!*\n\n"
                    f"✨ *Mode:* `Photo-to-Photo Swap`\n"
                    f"⏱ *Completed in:* `{elapsed}s`"
                )

                kb = types.InlineKeyboardMarkup(row_width=2)
                kb.row(
                    types.InlineKeyboardButton("📁 High-Res File", callback_data=f"doc|{safe_name}"),
                    types.InlineKeyboardButton("🎭 Swap Another", callback_data="start_photo_swap")
                )

                try:
                    bot.delete_message(chat_id, status_msg.message_id)
                except Exception:
                    pass

                bot.send_photo(
                    chat_id,
                    photo=swapped_bytes,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=kb,
                    reply_to_message_id=reply_to_id
                )
            except Exception as e:
                logger.error(f"Face swap error: {e}", exc_info=True)
                err_text = f"❌ *Face Swap Failed*\n\nError: `{str(e)}`\n\n💡 _Dono photos me chehra clearly visible hona chahiye._"
                try:
                    bot.edit_message_text(err_text, chat_id, status_msg.message_id, parse_mode="Markdown")
                except Exception:
                    bot.send_message(chat_id, err_text, parse_mode="Markdown")

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------------
    # Core Method 2: Face + Prompt Generation Worker
    # -----------------------------------------------------------------------
    def process_face_prompt_swap(bot: TeleBot, chat_id: int, user_id: int, source_bytes: bytes, prompt: str, reply_to_id: int = None):
        settings = database.get_user_settings(user_id)
        engine = settings.get("engine", config.DEFAULT_ENGINE)
        model = settings["model"]
        ratio = settings["ratio"]
        ratio_info = config.AVAILABLE_RATIOS.get(ratio, {"width": 1024, "height": 1024})

        status_msg = bot.send_message(
            chat_id,
            f"🎨 *Generating Scene with Your Face...*\n\n"
            f"📝 *Prompt:* `{prompt[:100]}`\n"
            f"1️⃣ Generating scene...\n"
            f"2️⃣ Seamlessly mapping your face onto the character...\n\n"
            f"⏳ _Please wait 15-30 seconds..._",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_id
        )

        def worker():
            nonlocal status_msg
            start_t = time.time()
            try:
                bot.send_chat_action(chat_id, 'upload_photo')
                swapped_bytes, orig_bytes = faceswap.swap_face_with_prompt(
                    source_bytes=source_bytes,
                    prompt=prompt,
                    engine=engine,
                    model=model,
                    width=ratio_info["width"],
                    height=ratio_info["height"]
                )
                elapsed = round(time.time() - start_t, 1)

                safe_name = f"faceprompt_{user_id}_{int(time.time())}.jpg"
                file_path = config.TEMP_PATH / safe_name
                file_path.write_bytes(swapped_bytes)

                caption = (
                    f"✨ *Prompt:* {prompt}\n\n"
                    f"🎭 *Mode:* `Face + Prompt Generation`\n"
                    f"⏱ *Generated & Swapped in:* `{elapsed}s`"
                )

                kb = types.InlineKeyboardMarkup(row_width=2)
                kb.row(
                    types.InlineKeyboardButton("📁 High-Res File", callback_data=f"doc|{safe_name}"),
                    types.InlineKeyboardButton("✍️ Try Another Prompt", callback_data="start_prompt_swap")
                )

                try:
                    bot.delete_message(chat_id, status_msg.message_id)
                except Exception:
                    pass

                bot.send_photo(
                    chat_id,
                    photo=swapped_bytes,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=kb,
                    reply_to_message_id=reply_to_id
                )
            except Exception as e:
                logger.error(f"Face+Prompt swap error: {e}", exc_info=True)
                err_text = f"❌ *Face+Prompt Generation Failed*\n\nError: `{str(e)}`"
                try:
                    bot.edit_message_text(err_text, chat_id, status_msg.message_id, parse_mode="Markdown")
                except Exception:
                    bot.send_message(chat_id, err_text, parse_mode="Markdown")

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------------
    # Core Method 3: Standard Text-to-Image Generation
    # -----------------------------------------------------------------------
    def process_text_generation(bot: TeleBot, chat_id: int, user_id: int, prompt: str, seed: int = None, reply_to_message_id: int = None):
        settings = database.get_user_settings(user_id)
        engine = settings.get("engine", config.DEFAULT_ENGINE)
        model = settings["model"]
        ratio = settings["ratio"]
        ratio_info = config.AVAILABLE_RATIOS.get(ratio, {"width": 1024, "height": 1024})
        width = ratio_info["width"]
        height = ratio_info["height"]

        engine_display = "⚡ Pollinations" if engine in ["pollinations", "auto"] else "🔞 AI Horde (Uncensored)"
        status_msg = bot.send_message(
            chat_id,
            f"🎨 *Generating your image...*\n\n"
            f"📝 *Prompt:* `{prompt[:120]}{'...' if len(prompt) > 120 else ''}`\n"
            f"⚙️ *Engine:* `{engine_display}` | 📐 *Size:* `{width}x{height}`\n\n"
            f"⏳ _Please wait..._",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id
        )

        def worker():
            nonlocal status_msg
            with generation_lock:
                start_time = time.time()
                image_bytes = None
                used_engine = "pollinations"
                error_msg = None

                if engine in ["pollinations", "auto"]:
                    try:
                        bot.send_chat_action(chat_id, 'upload_photo')
                        image_bytes = pollinations_client.generate_image(
                            prompt=prompt,
                            model=model,
                            width=width,
                            height=height,
                            seed=seed
                        )
                        used_engine = "pollinations"
                    except Exception as pe:
                        logger.warning(f"Pollinations attempt failed: {pe}")
                        error_msg = str(pe)
                        if engine == "auto":
                            try:
                                bot.edit_message_text(
                                    f"🎨 *Generating your image...*\n\n"
                                    f"📝 *Prompt:* `{prompt[:120]}...`\n"
                                    f"🔄 _Switching to Uncensored AI Horde..._",
                                    chat_id,
                                    status_msg.message_id,
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass

                if image_bytes is None and (engine == "aihorde" or engine == "auto"):
                    try:
                        bot.send_chat_action(chat_id, 'upload_photo')
                        image_bytes = horde_client.generate_horde_image(
                            prompt=prompt,
                            width=width,
                            height=height,
                            seed=seed,
                            api_key=config.AI_HORDE_KEY,
                            timeout=90
                        )
                        used_engine = "aihorde"
                        error_msg = None
                    except Exception as he:
                        logger.error(f"AI Horde attempt failed: {he}")
                        error_msg = str(he)

                elapsed = round(time.time() - start_time, 1)

                if image_bytes:
                    file_seed = seed if seed is not None else int(time.time())
                    safe_name = f"image_{user_id}_{file_seed}.jpg"
                    file_path = config.TEMP_PATH / safe_name
                    file_path.write_bytes(image_bytes)

                    database.log_generation(
                        user_id=user_id,
                        prompt=prompt,
                        model=model if used_engine == "pollinations" else "horde-uncensored",
                        width=width,
                        height=height,
                        seed=file_seed,
                        size=len(image_bytes),
                        status="success"
                    )

                    display_prompt = prompt if len(prompt) <= 700 else prompt[:697] + "..."
                    engine_tag = "⚡ Pollinations" if used_engine == "pollinations" else "🔞 AI Horde (Uncensored)"
                    caption = (
                        f"✨ *Prompt:* {display_prompt}\n\n"
                        f"⚙️ *Engine:* `{engine_tag}`\n"
                        f"🤖 *Model:* `{model.upper() if used_engine == 'pollinations' else 'Uncensored SD'}` | 📐 *Size:* `{width}x{height}`\n"
                        f"⏱ *Generated in:* `{elapsed}s`"
                    )

                    kb = types.InlineKeyboardMarkup(row_width=2)
                    kb.row(
                        types.InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen|{file_seed}"),
                        types.InlineKeyboardButton("📁 High-Res File", callback_data=f"doc|{safe_name}")
                    )
                    kb.row(
                        types.InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")
                    )

                    try:
                        bot.delete_message(chat_id, status_msg.message_id)
                    except Exception:
                        pass

                    bot.send_photo(
                        chat_id=chat_id,
                        photo=image_bytes,
                        caption=caption,
                        parse_mode="Markdown",
                        reply_markup=kb,
                        reply_to_message_id=reply_to_message_id
                    )
                else:
                    database.log_generation(
                        user_id=user_id,
                        prompt=prompt,
                        model=model,
                        width=width,
                        height=height,
                        seed=0,
                        size=0,
                        status="failed"
                    )
                    fail_text = (
                        f"❌ *Generation Failed*\n\n"
                        f"Error: `{error_msg[:160] if error_msg else 'Unknown'}`\n\n"
                        f"💡 *Suggestions:*\n"
                        f"• Try again in 10-15 seconds.\n"
                        f"• Switch engine via /engine."
                    )
                    try:
                        bot.edit_message_text(fail_text, chat_id, status_msg.message_id, parse_mode="Markdown")
                    except Exception:
                        bot.send_message(chat_id, fail_text, parse_mode="Markdown")

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------------
    # Callback Query Handlers (Inline Buttons)
    # -----------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback_queries(call: types.CallbackQuery):
        user_id = call.from_user.id
        data = call.data

        if data == "menu_faceswap":
            bot.answer_callback_query(call.id)
            handle_faceswap_command(call.message)

        elif data == "start_photo_swap":
            bot.answer_callback_query(call.id)
            user_states[user_id] = {"step": "awaiting_source_for_photo_swap"}
            bot.send_message(
                call.message.chat.id,
                "📸 *Step 1:* Apni **Face Photo** bhejiye (jiska chehra aap doosri photo par lagana chahte hain):",
                parse_mode="Markdown"
            )

        elif data == "start_prompt_swap":
            bot.answer_callback_query(call.id)
            user_states[user_id] = {"step": "awaiting_prompt"}
            bot.send_message(
                call.message.chat.id,
                "📸 *Step 1:* Apni **Face Photo** bhejiye:",
                parse_mode="Markdown"
            )

        elif data == "state_to_target":
            bot.answer_callback_query(call.id)
            if user_id in user_states:
                user_states[user_id]["step"] = "awaiting_target"
                bot.send_message(
                    call.message.chat.id,
                    "🎯 *Step 2:* Ab wo **Target Photo** bhejiye jiski body/dress par ye chehra lagana hai:",
                    parse_mode="Markdown"
                )

        elif data == "state_to_prompt":
            bot.answer_callback_query(call.id)
            if user_id in user_states:
                user_states[user_id]["step"] = "awaiting_prompt"
                bot.send_message(
                    call.message.chat.id,
                    "✍️ *Step 2:* Ab apna **Prompt text** likhkar bhejiye (e.g. `A wealthy prince in gold palace, 8k portrait`):",
                    parse_mode="Markdown"
                )

        elif data == "cancel_swap":
            bot.answer_callback_query(call.id, "Cancelled")
            if user_id in user_states:
                del user_states[user_id]
            try:
                bot.edit_message_text("❌ Operation cancel ho gayi hai.", call.message.chat.id, call.message.message_id)
            except Exception:
                bot.send_message(call.message.chat.id, "❌ Operation cancel ho gayi hai.")

        elif data.startswith("set_engine|"):
            engine = data.split("|")[1]
            database.set_user_engine(user_id, engine)
            bot.answer_callback_query(call.id, f"Engine set to {engine.upper()}!")
            try:
                bot.edit_message_text(
                    format_settings_text(user_id),
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode="Markdown",
                    reply_markup=get_settings_keyboard(user_id)
                )
            except Exception:
                pass

        elif data.startswith("set_model|"):
            model = data.split("|")[1]
            database.set_user_model(user_id, model)
            bot.answer_callback_query(call.id, f"Model set to {model.upper()}!")
            try:
                bot.edit_message_text(
                    format_settings_text(user_id),
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode="Markdown",
                    reply_markup=get_settings_keyboard(user_id)
                )
            except Exception:
                pass

        elif data.startswith("set_ratio|"):
            ratio = data.split("|")[1]
            database.set_user_ratio(user_id, ratio)
            bot.answer_callback_query(call.id, f"Aspect ratio set to {ratio}!")
            try:
                bot.edit_message_text(
                    format_settings_text(user_id),
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode="Markdown",
                    reply_markup=get_settings_keyboard(user_id)
                )
            except Exception:
                pass

        elif data == "menu_engine":
            bot.answer_callback_query(call.id)
            settings = database.get_user_settings(user_id)
            cur_engine = settings.get("engine", config.DEFAULT_ENGINE)
            kb = types.InlineKeyboardMarkup(row_width=1)
            for key, name in config.AVAILABLE_ENGINES.items():
                is_active = (key == cur_engine)
                kb.add(types.InlineKeyboardButton(
                    text=f"{'✅ ' if is_active else ''}{name}",
                    callback_data=f"set_engine|{key}"
                ))
            bot.send_message(call.message.chat.id, "⚡ *Select your generation engine:*", parse_mode="Markdown", reply_markup=kb)

        elif data == "menu_settings":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                format_settings_text(user_id),
                parse_mode="Markdown",
                reply_markup=get_settings_keyboard(user_id)
            )

        elif data == "menu_model":
            bot.answer_callback_query(call.id)
            settings = database.get_user_settings(user_id)
            cur_model = settings["model"]
            kb = types.InlineKeyboardMarkup(row_width=1)
            for key, name in config.AVAILABLE_MODELS.items():
                is_active = (key == cur_model)
                kb.add(types.InlineKeyboardButton(
                    text=f"{'✅ ' if is_active else ''}{name}",
                    callback_data=f"set_model|{key}"
                ))
            bot.send_message(call.message.chat.id, "🤖 *Select your preferred AI Image Model:*", parse_mode="Markdown", reply_markup=kb)

        elif data == "menu_ratio":
            bot.answer_callback_query(call.id)
            settings = database.get_user_settings(user_id)
            cur_ratio = settings["ratio"]
            kb = types.InlineKeyboardMarkup(row_width=1)
            for key, info in config.AVAILABLE_RATIOS.items():
                is_active = (key == cur_ratio)
                kb.add(types.InlineKeyboardButton(
                    text=f"{'✅ ' if is_active else ''}{info['label']} ({info['width']}x{info['height']})",
                    callback_data=f"set_ratio|{key}"
                ))
            bot.send_message(call.message.chat.id, "📐 *Select your preferred Aspect Ratio:*", parse_mode="Markdown", reply_markup=kb)

        elif data == "open_help":
            bot.answer_callback_query(call.id)
            handle_help(call.message)

        elif data == "close_settings":
            bot.answer_callback_query(call.id)
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass

        elif data.startswith("doc|"):
            safe_name = data.split("|")[1]
            file_path = config.TEMP_PATH / safe_name
            if file_path.exists():
                bot.answer_callback_query(call.id, "Sending high-res file...")
                with open(file_path, "rb") as doc:
                    bot.send_document(
                        call.message.chat.id,
                        doc,
                        caption="📁 *Full Quality Image (Uncompressed)*",
                        parse_mode="Markdown"
                    )
            else:
                bot.answer_callback_query(call.id, "File expired or not found on server.", show_alert=True)

        elif data.startswith("regen|"):
            bot.answer_callback_query(call.id, "Regenerating with new seed...")
            caption = call.message.caption or ""
            prompt = ""
            if "✨ *Prompt:* " in caption:
                try:
                    p_start = caption.index("✨ *Prompt:* ") + len("✨ *Prompt:* ")
                    p_end = caption.index("\n\n⚙️ *Engine:*")
                    prompt = caption[p_start:p_end].strip()
                except Exception:
                    try:
                        p_start = caption.index("✨ *Prompt:* ") + len("✨ *Prompt:* ")
                        p_end = caption.index("\n\n🤖 *Model:*")
                        prompt = caption[p_start:p_end].strip()
                    except Exception:
                        prompt = ""
            
            if not prompt:
                history = database.get_user_history(user_id, limit=1)
                if history:
                    prompt = history[0]["prompt"]

            if prompt:
                process_text_generation(bot, call.message.chat.id, user_id, prompt)
            else:
                bot.send_message(call.message.chat.id, "⚠️ Could not find prompt to regenerate. Please send the prompt again.")
