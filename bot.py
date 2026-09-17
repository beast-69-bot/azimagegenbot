import logging
import sys
from telebot import TeleBot
import config
import handlers

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOGS_PATH / "bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("azimagegenbot")

def main():
    token = config.POLLINATIONS_BOT_TOKEN
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.error("POLLINATIONS_BOT_TOKEN is not set in the .env file!")
        print("\n[!] ERROR: POLLINATIONS_BOT_TOKEN is missing or empty in .env")
        return

    logger.info("Initializing AZ Image Gen Telegram Bot...")
    try:
        bot = TeleBot(token)
        handlers.register_handlers(bot)
        
        bot_info = bot.get_me()
        logger.info(f"Bot connected successfully as @{bot_info.username} (ID: {bot_info.id})")
        print(f"\n✅ AZ Image Gen Bot is online as @{bot_info.username}!")
        
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        logger.critical(f"Bot polling encountered fatal error: {e}", exc_info=True)
        print(f"\n[!] Fatal Error: {e}")

if __name__ == "__main__":
    main()
