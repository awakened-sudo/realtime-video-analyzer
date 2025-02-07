import base64
import os
import cv2
import re
import numpy as np
import httpx
import asyncio
from quart import Quart, request, jsonify, render_template, Response, send_from_directory
from pathlib import Path

app = Quart(__name__)
app.config['EXPLAIN_TEMPLATE_LOADING'] = True
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

API_URL = "https://api.openai.com/v1/chat/completions"
API_KEY = os.getenv("OPENAI_API_KEY")

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

async def prompt_image(image_base64: str, prompt: str, api_key: str) -> str:
    headers = compose_headers(api_key=api_key)
    payload = compose_payload(image_base64=image_base64, prompt=prompt)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                response = await client.post(API_URL, headers=headers, json=payload, timeout=30.0)
                response.raise_for_status()  # Raise an error for bad HTTP status codes
                try:
                    response_json = response.json()
                except ValueError:
                    raise ValueError("Failed to parse response as JSON")

                if 'error' in response_json:
                    raise ValueError(response_json['error']['message'])
                return response_json['choices'][0]['message']['content']
            except httpx.HTTPStatusError as http_err:
                if response.status_code == 429:
                    error_message = response.json().get('error', {}).get('message', '')
                    wait_time = parse_wait_time(error_message)
                    if wait_time:
                        print(f"Rate limit exceeded. Waiting for {wait_time} seconds.")
                        await asyncio.sleep(wait_time)
                    else:
                        raise ValueError(f"Rate limit exceeded but could not parse wait time from message: {error_message}")
                else:
                    raise ValueError(f"HTTP error occurred: {http_err}")
            except httpx.RequestError as req_err:
                raise ValueError(f"Request error occurred: {req_err}")
            except httpx.TimeoutException:
                raise ValueError("Request timed out. Please try again later.")

def parse_wait_time(error_message: str) -> int:
    match = re.search(r"try again in (\d+m)?(\d+\.\ds)?", error_message)
    if match:
        minutes = match.group(1)
        seconds = match.group(2)

        total_wait_time = 0
        if minutes:
            total_wait_time += int(minutes[:-1]) * 60  # Convert minutes to seconds
        if seconds:
            total_wait_time += float(seconds[:-1])  # Add seconds

        return int(total_wait_time)
    return None

def add_cors_headers(response):
    """Add CORS headers to the response"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response

@app.before_serving
async def startup():
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
        response = Response()
        return add_cors_headers(response)

    print(f"Received {request.method} request to /process_frame")
    print(f"Request headers: {dict(request.headers)}")
    
    try:
        if not request.is_json:
            return jsonify({'response': 'Request must be JSON'}), 400
            
        data = await request.get_json()
        print(f"Received data keys: {data.keys() if data else None}")
        
        if not data:
            return jsonify({'response': 'No data received'}), 400
            
        image_data = data.get('image', '').split(',')[1] if data.get('image', '').count(',') > 0 else ''
        if not image_data:
            return jsonify({'response': 'Invalid image data'}), 400
            
        try:
            image = np.frombuffer(base64.b64decode(image_data), dtype=np.uint8)
            image = cv2.imdecode(image, cv2.IMREAD_COLOR)
            if image is None:
                return jsonify({'response': 'Failed to decode image'}), 400
                
            processed_image = preprocess_image(image)
            image_base64 = encode_image_to_base64(processed_image)
            prompt = data.get('prompt', "Analyze this frame")
            api_key = data.get('api_key') or API_KEY
            
            if not api_key:
                return jsonify({'response': 'API key is required.'}), 400
                
            try:
                response = await prompt_image(image_base64, prompt, api_key)
                return jsonify({'response': response})
            except ValueError as e:
                return jsonify({'response': str(e)}), 400
                
        except Exception as e:
            print(f"Error processing image: {str(e)}")
            return jsonify({'response': f'Error processing image: {str(e)}'}), 400
                
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        return jsonify({'response': f'Error processing request: {str(e)}'}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
