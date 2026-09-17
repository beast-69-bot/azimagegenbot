import logging
import sys
import socket
from telebot import TeleBot

# Force IPv4 resolution to prevent 'Network is unreachable' on cloud VMs without IPv6 routing
try:
    import urllib3.util.connection as urllib3_cn
    urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

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
