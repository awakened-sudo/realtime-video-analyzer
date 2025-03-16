import asyncio
import logging
from telegram import Bot
import os
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Bot token and chat ID
BOT_TOKEN = os.getenv('PEACESIGN_BOT_TOKEN')
CHAT_ID = "-4731527361"  # Group chat ID

async def test_telegram_connection():
    try:
        logger.info(f"Testing Telegram bot with token: {BOT_TOKEN[:5]}...")
        
        # Initialize bot
        bot = Bot(token=BOT_TOKEN)
        
        # Get bot info
        bot_info = await bot.get_me()
        logger.info(f"Bot info: {bot_info.first_name} (@{bot_info.username})")
        
        # Send test message
        message = await bot.send_message(
            chat_id=CHAT_ID,
            text="🧪 This is a test message from the Peace Sign Detection Bot!"
        )
        
        logger.info(f"Message sent successfully! Message ID: {message.message_id}")
        return True
    except Exception as e:
        logger.error(f"Error testing Telegram bot: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting Telegram bot test...")
    result = asyncio.run(test_telegram_connection())
    if result:
        logger.info("Test completed successfully!")
    else:
        logger.error("Test failed!")
