import io
import os
import time
import logging
import threading
from pathlib import Path
from telebot import TeleBot, types

import config
import database
from pollinations_client import generate_image

logger = logging.getLogger("azimagegenbot.handlers")

# Concurrency lock to serialize requests (Pollinations enforces 1 in-flight req per IP)
generation_lock = threading.Lock()

def get_settings_keyboard(user_id: int) -> types.InlineKeyboardMarkup:
    """Builds inline keyboard reflecting user's current settings."""
    settings = database.get_user_settings(user_id)
    cur_model = settings["model"]
    cur_ratio = settings["ratio"]

    kb = types.InlineKeyboardMarkup(row_width=2)
    
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
    model = settings["model"]
    ratio = settings["ratio"]
    ratio_info = config.AVAILABLE_RATIOS.get(ratio, {})
    dim = f"{ratio_info.get('width', 1024)}x{ratio_info.get('height', 1024)}"

    return (
        f"⚙️ *AI Generator Settings*\n\n"
        f"🤖 *Active Model:* `{model.upper()}` ({config.AVAILABLE_MODELS.get(model, model)})\n"
        f"📐 *Aspect Ratio:* `{ratio}` ({dim} px)\n\n"
        f"Tap the buttons below to change model or resolution:"
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
            f"👋 *Welcome to AI Image Generator Bot!*, {username}\n\n"
            f"I can generate high-quality AI images **for free, with no API key and no limits!**\n\n"
            f"🚀 *How to use:*\n"
            f"Simply **send me any text prompt** directly in this chat, e.g.:\n"
            f"`A cute red panda drinking coffee in rainfall, highly detailed 8k`\n\n"
            f"⚙️ *Commands:*\n"
            f"/model - Choose AI model (Flux, Turbo, Sana)\n"
            f"/ratio - Change aspect ratio (Square, Story, Wallpaper)\n"
            f"/settings - Configure your preferences\n"
            f"/history - View recent generation prompts\n"
            f"/stats - Check bot generation stats\n"
            f"/help - Prompt writing tips & guide"
        )

        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.row(
            types.InlineKeyboardButton("🤖 Change Model", callback_data="menu_model"),
            types.InlineKeyboardButton("📐 Aspect Ratio", callback_data="menu_ratio")
        )
        kb.row(
            types.InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
            types.InlineKeyboardButton("📊 Bot Stats", callback_data="menu_stats")
        )
        bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=kb)

    # -----------------------------------------------------------------------
    # /help
    # -----------------------------------------------------------------------
    @bot.message_handler(commands=['help'])
    def handle_help(message: types.Message):
        help_text = (
            f"💡 *Pollinations AI Help & Prompting Guide*\n\n"
            f"1. **Just Type Anything**: Send any message and I will create an image from it.\n"
            f"2. **Models Available:**\n"
            f"   • *Flux*: Best for photorealism, fine details & textures.\n"
            f"   • *Turbo*: Fastest generation, great for quick tests.\n"
            f"   • *Sana*: Alibaba's lightweight model, artistic & stylized.\n\n"
            f"3. **Aspect Ratios:**\n"
            f"   • `1:1` - Square (1024x1024)\n"
            f"   • `9:16` - Portrait / Mobile Wallpaper / Reel (768x1024)\n"
            f"   • `16:9` - Landscape / Desktop Wallpaper (1024x768)\n"
            f"   • `4:5` - Social Media Post (816x1020)\n\n"
            f"4. **Prompt Tips:** Include styles like _cinematic lighting, photorealistic, 8k, cyberpunk, watercolor, octane render_ for even better results!"
        )
        bot.reply_to(message, help_text, parse_mode="Markdown")

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
    # Direct prompt generation (/gen or any text message)
    # -----------------------------------------------------------------------
    @bot.message_handler(func=lambda msg: msg.text and not msg.text.startswith('/'))
    @bot.message_handler(commands=['gen', 'generate', 'draw'])
    def handle_prompt_message(message: types.Message):
        user_id = message.from_user.id
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

        process_generation(bot, message.chat.id, user_id, prompt, reply_to_message_id=message.message_id)

    # -----------------------------------------------------------------------
    # Core Image Generation Function (Thread-safe queued)
    # -----------------------------------------------------------------------
    def process_generation(bot: TeleBot, chat_id: int, user_id: int, prompt: str, seed: int = None, reply_to_message_id: int = None):
        settings = database.get_user_settings(user_id)
        model = settings["model"]
        ratio = settings["ratio"]
        ratio_info = config.AVAILABLE_RATIOS.get(ratio, {"width": 1024, "height": 1024})
        width = ratio_info["width"]
        height = ratio_info["height"]

        # Send processing status message
        status_msg = bot.send_message(
            chat_id,
            f"🎨 *Generating your image...*\n\n"
            f"📝 *Prompt:* `{prompt[:120]}{'...' if len(prompt) > 120 else ''}`\n"
            f"🤖 *Model:* `{model.upper()}` | 📐 *Size:* `{width}x{height}`\n\n"
            f"⏳ _Please wait 15-40 seconds..._",
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id
        )

        def worker():
            nonlocal status_msg
            with generation_lock:
                start_time = time.time()
                try:
                    bot.send_chat_action(chat_id, 'upload_photo')
                    image_bytes = generate_image(
                        prompt=prompt,
                        model=model,
                        width=width,
                        height=height,
                        seed=seed
                    )
                    elapsed = round(time.time() - start_time, 1)

                    file_seed = seed if seed is not None else int(time.time())
                    safe_name = f"image_{user_id}_{file_seed}.jpg"
                    file_path = config.TEMP_PATH / safe_name
                    file_path.write_bytes(image_bytes)

                    database.log_generation(
                        user_id=user_id,
                        prompt=prompt,
                        model=model,
                        width=width,
                        height=height,
                        seed=file_seed,
                        size=len(image_bytes),
                        status="success"
                    )

                    display_prompt = prompt if len(prompt) <= 700 else prompt[:697] + "..."
                    caption = (
                        f"✨ *Prompt:* {display_prompt}\n\n"
                        f"🤖 *Model:* `{model.upper()}` | 📐 *Size:* `{width}x{height}`\n"
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

                except Exception as e:
                    logger.error(f"Generation error for user {user_id}: {e}", exc_info=True)
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
                    error_text = (
                        f"❌ *Generation Failed*\n\n"
                        f"The generator encountered an error: `{str(e)[:150]}`\n\n"
                        f"💡 *Suggestions:*\n"
                        f"• Pollinations might be temporarily busy. Please retry in 10-15 seconds.\n"
                        f"• Try switching model with /model."
                    )
                    try:
                        bot.edit_message_text(error_text, chat_id, status_msg.message_id, parse_mode="Markdown")
                    except Exception:
                        bot.send_message(chat_id, error_text, parse_mode="Markdown")

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------------
    # Callback Query Handlers (Inline Buttons)
    # -----------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback_queries(call: types.CallbackQuery):
        user_id = call.from_user.id
        data = call.data

        if data.startswith("set_model|"):
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

        elif data == "menu_stats":
            bot.answer_callback_query(call.id)
            stats = database.get_global_stats()
            text = (
                f"📊 *Bot Generation Statistics*\n\n"
                f"👥 *Total Users:* {stats['total_users']}\n"
                f"✅ *Successful Generations:* {stats['total_success']}\n"
                f"⚠️ *Failed Requests:* {stats['total_failed']}\n"
            )
            bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

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
                    p_end = caption.index("\n\n🤖 *Model:*")
                    prompt = caption[p_start:p_end].strip()
                except Exception:
                    prompt = ""
            
            if not prompt:
                history = database.get_user_history(user_id, limit=1)
                if history:
                    prompt = history[0]["prompt"]

            if prompt:
                process_generation(bot, call.message.chat.id, user_id, prompt)
            else:
                bot.send_message(call.message.chat.id, "⚠️ Could not find prompt to regenerate. Please send the prompt again.")
