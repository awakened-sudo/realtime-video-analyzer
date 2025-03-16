import base64
import os
import cv2
import re
import numpy as np
import httpx
import asyncio
from quart import Quart, request, jsonify, render_template, Response, send_from_directory
from pathlib import Path
from dotenv import load_dotenv
import json
import logging
from telegram import Bot
from PIL import Image
import io

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

app = Quart(__name__)
app.config['EXPLAIN_TEMPLATE_LOADING'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

API_URL = "https://api.openai.com/v1/chat/completions"
API_KEY = os.getenv("OPENAI_API_KEY")
PEACESIGN_BOT_TOKEN = os.getenv('PEACESIGN_BOT_TOKEN')
PEACESIGN_CHAT_ID = "-4731527361"  # Group chat ID
WEAPON_BOT_TOKEN = os.getenv('WEAPON_BOT_TOKEN', PEACESIGN_BOT_TOKEN)  # Fallback to peace sign bot if not specified
WEAPON_CHAT_ID = PEACESIGN_CHAT_ID  # Use the same chat ID as peace sign detection

# Initialize Telegram bots
peacesign_bot = None
weapon_bot = None

if not API_KEY:
    logger.warning("OPENAI_API_KEY environment variable is not set")

def preprocess_image(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

def encode_image_to_base64(image: np.ndarray) -> str:
    success, buffer = cv2.imencode('.jpg', image)
    if not success:
        raise ValueError("Could not encode image to JPEG format.")
    encoded_image = base64.b64encode(buffer).decode('utf-8')
    return encoded_image

def compose_payload(image_base64: str, prompt: str) -> dict:
    return {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"You are an expert in analyzing visual content. Please analyze the provided image for the following details:\n"
                            f"1. Identify any text present in the image and provide a summary.\n"
                            f"2. Describe the main objects and their arrangement.\n"
                            f"3. Identify the context of the video frame (e.g., work environment, outdoor scene).\n"
                            f"4. Provide any notable observations about lighting, colors, and overall composition.\n"
                            f"5. Format using markdown.\n"
                            f"Here is the Video Frame still:\n{prompt}"
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 100
    }

def compose_headers(api_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

async def prompt_image(image_base64, prompt, api_key):
    try:
        messages = [
            {
                "role": "system",
                "content": "You are a computer vision assistant analyzing video frames. Be precise and concise in your analysis."
            },
            {
                "role": "user",
                "content": f"{prompt}\n\nAnalyze this image and provide your observations:"
            }
        ]
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "max_tokens": 500
        }
        
        # Add the image to the last message
        data["messages"][-1]["content"] = [
            {
                "type": "text",
                "text": prompt
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}"
                }
            }
        ]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, json=data, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            if "choices" in result and len(result["choices"]) > 0:
                analysis = result["choices"][0]["message"]["content"]
                print("Analysis received:", analysis)  # Debug log
                return analysis
            else:
                raise ValueError("No analysis received from API")
                
    except Exception as e:
        print(f"Error in prompt_image: {e}")
        raise

async def init_telegram():
    global peacesign_bot, weapon_bot
    
    # Initialize peace sign bot
    try:
        if PEACESIGN_BOT_TOKEN:
            logger.info(f"Initializing Peace Sign Telegram bot with token: {PEACESIGN_BOT_TOKEN[:5]}...")
            peacesign_bot = Bot(token=PEACESIGN_BOT_TOKEN)
            
            # Get bot info to verify connection
            bot_info = await peacesign_bot.get_me()
            logger.info(f"Peace Sign Bot info: {bot_info.first_name} (@{bot_info.username})")
            
            # Test connection by sending a startup message
            await peacesign_bot.send_message(
                chat_id=PEACESIGN_CHAT_ID,
                text="🤖 Peace Sign Detection Bot is now connected and running!"
            )
            logger.info(f"Successfully connected Peace Sign bot to Telegram group {PEACESIGN_CHAT_ID}")
        else:
            logger.warning("PEACESIGN_BOT_TOKEN not found in environment variables")
    except Exception as e:
        logger.error(f"Error initializing Peace Sign Telegram bot: {e}")
        peacesign_bot = None
    
    # Initialize weapon detection bot
    try:
        if WEAPON_BOT_TOKEN:
            # If using the same bot for both, don't initialize twice
            if WEAPON_BOT_TOKEN == PEACESIGN_BOT_TOKEN and peacesign_bot:
                logger.info("Using Peace Sign bot for Weapon detection as well")
                weapon_bot = peacesign_bot
            else:
                logger.info(f"Initializing Weapon Detection Telegram bot with token: {WEAPON_BOT_TOKEN[:5]}...")
                weapon_bot = Bot(token=WEAPON_BOT_TOKEN)
                
                # Get bot info to verify connection
                bot_info = await weapon_bot.get_me()
                logger.info(f"Weapon Detection Bot info: {bot_info.first_name} (@{bot_info.username})")
                
                # Test connection by sending a startup message
                await weapon_bot.send_message(
                    chat_id=WEAPON_CHAT_ID,
                    text="🔫 Weapon Detection Bot is now connected and running!"
                )
                logger.info(f"Successfully connected Weapon Detection bot to Telegram group {WEAPON_CHAT_ID}")
        else:
            logger.warning("WEAPON_BOT_TOKEN not found in environment variables, using Peace Sign bot if available")
            weapon_bot = peacesign_bot
    except Exception as e:
        logger.error(f"Error initializing Weapon Detection Telegram bot: {e}")
        weapon_bot = None

async def send_to_telegram_peacesign(image_data, analysis_text):
    global peacesign_bot
    
    if not peacesign_bot:
        logger.error("Peace Sign Telegram bot not initialized")
        # Try to initialize the bot again
        try:
            peacesign_bot = Bot(token=PEACESIGN_BOT_TOKEN)
            logger.info("Re-initialized Peace Sign Telegram bot")
        except Exception as e:
            logger.error(f"Failed to re-initialize Peace Sign Telegram bot: {e}")
            return False
    
    try:
        logger.info(f"Preparing to send peace sign detection to group {PEACESIGN_CHAT_ID}")
        
        # Convert base64 to image
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        logger.info("Decoding image data")
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Save to temporary buffer
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='JPEG')
        img_buffer.seek(0)
        
        logger.info("Sending photo to Telegram")
        
        # First try sending a text message to verify connection
        await peacesign_bot.send_message(
            chat_id=PEACESIGN_CHAT_ID,
            text="✌️ Peace Sign Detected! Sending image..."
        )
        
        # Then send the image
        await peacesign_bot.send_photo(
            chat_id=PEACESIGN_CHAT_ID,
            photo=img_buffer,
            caption=f"Analysis: {analysis_text[:1000]}"  # Telegram caption limit
        )
        
        logger.info("Successfully sent peace sign detection to group")
        return True
    except Exception as e:
        logger.error(f"Error sending to Peace Sign Telegram group: {e}")
        # Try with a simplified approach - just send text
        try:
            await peacesign_bot.send_message(
                chat_id=PEACESIGN_CHAT_ID,
                text=f"✌️ Peace Sign Detected!\n\nAnalysis: {analysis_text[:1000]}"
            )
            logger.info("Sent text-only notification to Peace Sign Telegram group")
            return True
        except Exception as e2:
            logger.error(f"Failed to send even text message to Peace Sign group: {e2}")
            return False

async def send_to_telegram_weapon(image_data, analysis_text):
    global weapon_bot
    
    if not weapon_bot:
        logger.error("Weapon Detection Telegram bot not initialized")
        # Try to initialize the bot again
        try:
            weapon_bot = Bot(token=WEAPON_BOT_TOKEN)
            logger.info("Re-initialized Weapon Detection Telegram bot")
        except Exception as e:
            logger.error(f"Failed to re-initialize Weapon Detection Telegram bot: {e}")
            return False
    
    try:
        logger.info(f"Preparing to send weapon detection to group {WEAPON_CHAT_ID}")
        
        # Convert base64 to image
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        logger.info("Decoding image data")
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Save to temporary buffer
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='JPEG')
        img_buffer.seek(0)
        
        # Determine if it's a toy/replica or real weapon
        response_lower = analysis_text.lower()
        is_toy = "toy" in response_lower or "replica" in response_lower or "prop" in response_lower
        
        alert_emoji = "⚠️" if is_toy else "🚨"
        alert_prefix = "TOY/REPLICA WEAPON ALERT" if is_toy else "WEAPON ALERT"
        
        logger.info("Sending photo to Telegram")
        
        # First try sending a text message to verify connection
        await weapon_bot.send_message(
            chat_id=WEAPON_CHAT_ID,
            text=f"{alert_emoji} {alert_prefix}! Sending image..."
        )
        
        # Then send the image
        await weapon_bot.send_photo(
            chat_id=WEAPON_CHAT_ID,
            photo=img_buffer,
            caption=f"{alert_emoji} {alert_prefix} {alert_emoji}\n\nAnalysis: {analysis_text[:1000]}"  # Telegram caption limit
        )
        
        logger.info("Successfully sent weapon detection to group")
        return True
    except Exception as e:
        logger.error(f"Error sending to Weapon Detection Telegram group: {e}")
        # Try with a simplified approach - just send text
        try:
            # Determine if it's a toy/replica or real weapon
            response_lower = analysis_text.lower()
            is_toy = "toy" in response_lower or "replica" in response_lower or "prop" in response_lower
            
            alert_emoji = "⚠️" if is_toy else "🚨"
            alert_prefix = "TOY/REPLICA WEAPON ALERT" if is_toy else "WEAPON ALERT"
            
            await weapon_bot.send_message(
                chat_id=WEAPON_CHAT_ID,
                text=f"{alert_emoji} {alert_prefix}!\n\nAnalysis: {analysis_text[:1000]}"
            )
            logger.info("Sent text-only notification to Weapon Detection Telegram group")
            return True
        except Exception as e2:
            logger.error(f"Failed to send even text message to Weapon Detection group: {e2}")
            return False

def add_cors_headers(response):
    """Add CORS headers to the response"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response

@app.before_serving
async def startup():
    await init_telegram()
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule.methods} - {rule}")
    app.api_key = os.getenv("OPENAI_API_KEY")

@app.after_request
async def after_request(response):
    return add_cors_headers(response)

@app.route('/')
async def index():
    return await render_template('index.html')

@app.route('/static/<path:path>')
async def send_static(path):
    return await send_from_directory('static', path)

@app.route('/process_frame', methods=['POST', 'OPTIONS'])
async def process_frame():
    if request.method == 'OPTIONS':
        return await handle_preflight()

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    try:
        data = await request.get_json()
        image = data.get('image', '')
        prompt = data.get('prompt', '')
        
        # Check if user provided API key in request
        user_api_key = data.get('api_key', '')
        api_key_to_use = user_api_key if user_api_key else API_KEY
        
        if not api_key_to_use:
            return jsonify({"error": "No API key available. Please provide an API key or set OPENAI_API_KEY in .env file."}), 400
        
        if not image or not prompt:
            return jsonify({"error": "Image and prompt are required"}), 400
        
        try:
            # Extract base64 image data
            image_base64 = image.split(',')[1] if ',' in image else image
            
            # Get analysis from OpenAI
            response = await prompt_image(image_base64, prompt, api_key_to_use)
            logger.info(f"Received analysis response: {response[:100]}...")
            
            # Check for detections based on prompt type
            response_lower = response.lower()
            
            # Check for peace sign detection
            if ("hand sign" in prompt.lower() or "gesture" in prompt.lower()):
                response_lower = response.lower()
                
                # Check for explicit statements that no peace sign is detected
                no_peace_sign_indicators = [
                    "no peace sign" in response_lower,
                    "no clear gestures" in response_lower,
                    "no specific gestures are detected" in response_lower,
                    "no identifiable hand gestures" in response_lower,
                    "no hand signs" in response_lower,
                    "no gestures" in response_lower
                ]
                
                # Check for positive peace sign indicators
                peace_sign_indicators = [
                    "peace sign detected" in response_lower,
                    "✌️" in response,
                    ("peace" in response_lower and "sign" in response_lower and "v" in response_lower),
                    ("victory" in response_lower and "sign" in response_lower)
                ]
                
                # Only send alert if we have positive indicators and no negative indicators
                if any(peace_sign_indicators) and not any(no_peace_sign_indicators):
                    logger.info("Peace sign detected in the analysis")
                    # Run in a separate task to avoid blocking the response
                    asyncio.create_task(send_to_telegram_peacesign(image, response))
                else:
                    logger.info("No peace sign detected in the analysis")
            
            # Check for weapon detection
            if "weapon" in prompt.lower():
                # First check if the analysis explicitly states no weapons
                no_weapon_indicators = [
                    "no weapons detected" in response_lower and "toy" not in response_lower and "replica" not in response_lower,
                    "no weapon" in response_lower and "toy" not in response_lower and "replica" not in response_lower
                ]
                
                # Check for positive weapon indicators - including toys and replicas
                weapon_indicators = [
                    "weapon detected:" in response_lower,
                    "weapon detected" in response_lower,
                    "firearm" in response_lower,
                    "gun" in response_lower,
                    "pistol" in response_lower,
                    "rifle" in response_lower,
                    "knife" in response_lower,
                    "blade" in response_lower,
                    "explosive" in response_lower,
                    "toy gun" in response_lower,
                    "replica" in response_lower,
                    "toy weapon" in response_lower
                ]
                
                # Only send alert if we have positive indicators and no clear negative indicators
                if any(weapon_indicators) and not any(no_weapon_indicators):
                    logger.info("Weapon or weapon-like object detected in the analysis")
                    # Run in a separate task to avoid blocking the response
                    asyncio.create_task(send_to_telegram_weapon(image, response))
                else:
                    logger.info("No weapons or weapon-like objects detected in the analysis")
            
            return jsonify({'response': response})
            
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
            
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
