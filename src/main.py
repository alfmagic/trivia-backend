from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import random
import time
import threading
from datetime import datetime, timedelta
from collections import deque # Import deque for efficient queue operations

from src.config import TRIVIA_API_URL, games_lock
from src.routes.game import game_bp
from src.models.game import games, Game, Player

app = Flask(__name__)
CORS(app)

app.register_blueprint(game_bp)

# --- Question Caching Logic ---
question_cache = deque() # Use a deque for efficient appends and pops
CACHE_FILL_THRESHOLD = 5 # If less than this many questions, refill
CACHE_FILL_AMOUNT = 20 # How many questions to fetch at once
last_cache_fill_time = datetime.min # To prevent rapid refilling

def fetch_and_fill_cache(difficulty='any', category='any'):
    global last_cache_fill_time
    # Only fetch if cache is low AND enough time has passed since last fetch
    if len(question_cache) < CACHE_FILL_THRESHOLD and \
       (datetime.now() - last_cache_fill_time) > timedelta(seconds=5): # Add a 5-second cooldown
        print(f"Cache low ({len(question_cache)} questions). Refilling with {CACHE_FILL_AMOUNT} new questions...")
        params = {
            "amount": CACHE_FILL_AMOUNT,
            "type": "multiple"
        }
        if difficulty != 'any':
            params["difficulty"] = difficulty
        if category != 'any':
            params["category"] = category

        try:
            response = requests.get(TRIVIA_API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data['response_code'] == 0 and data['results']:
                for q_data in data['results']:
                    question = {
                        "id": str(random.randint(100000, 999999)),
                        "category": q_data['category'],
                        "type": q_data['type'],
                        "difficulty": q_data['difficulty'],
                        "question": q_data['question'],
                        "correct_answer": q_data['correct_answer'],
                        "incorrect_answers": q_data['incorrect_answers']
                    }
                    question_cache.append(question)
                print(f"Cache refilled. Total questions in cache: {len(question_cache)}")
                last_cache_fill_time = datetime.now()
            else:
                print(f"Could not fetch questions from external API. Response code: {data['response_code']}")
        except requests.exceptions.Timeout:
            print("Request to trivia API timed out during cache fill.")
        except requests.exceptions.RequestException as e:
            print(f"Error fetching questions from external API during cache fill: {e}")
        except Exception as e:
            print(f"An unexpected error occurred during cache fill: {e}")

# Initial cache fill on startup
with app.app_context(): # Use app_context for initial fetch
    fetch_and_fill_cache()

# Schedule cleanup for inactive games (existing logic)
def cleanup_inactive_games():
    with games_lock:
        inactive_threshold = datetime.now() - timedelta(hours=1)
        keys_to_delete = [
            room_id for room_id, game in games.items()
            if game.last_activity < inactive_threshold
        ]
        for room_id in keys_to_delete:
            print(f"Cleaning up inactive room: {room_id}")
            del games[room_id]

def start_cleanup_scheduler():
    cleanup_inactive_games()
    threading.Timer(1800, start_cleanup_scheduler).start()

if not hasattr(app, 'cleanup_scheduler_started'):
    app.cleanup_scheduler_started = True
    start_cleanup_scheduler()

@app.route('/')
def home():
    return "Trivia Multiplayer Backend is running!"

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/question')
def get_question():
    difficulty = request.args.get('difficulty', 'any')
    category = request.args.get('category', 'any')

    # Attempt to refill cache in background if needed
    threading.Thread(target=fetch_and_fill_cache, args=(difficulty, category)).start()

    if question_cache:
        question = question_cache.popleft() # Get question from cache
        return jsonify(question)
    else:
        # If cache is empty, try a direct fetch as a fallback (might still hit 429)
        print("Cache empty, attempting direct fetch for question.")
        params = {
            "amount": 1,
            "type": "multiple"
        }
        if difficulty != 'any':
            params["difficulty"] = difficulty
        if category != 'any':
            params["category"] = category

        try:
            response = requests.get(TRIVIA_API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data['response_code'] == 0 and data['results']:
                question_data = data['results'][0]
                question = {
                    "id": str(random.randint(100000, 999999)),
                    "category": question_data['category'],
                    "type": question_data['type'],
                    "difficulty": question_data['difficulty'],
                    "question": question_data['question'],
                    "correct_answer": question_data['correct_answer'],
                    "incorrect_answers": question_data['incorrect_answers']
                }
                return jsonify(question)
            else:
                return jsonify({"error": "Could not fetch question. Try different parameters or check API response."}), 404
        except requests.exceptions.Timeout:
            return jsonify({"error": "Request to trivia API timed out."}), 504
        except requests.exceptions.RequestException as e:
            return jsonify({"error": f"Error fetching question from external API: {e}"}), 500
        except Exception as e:
            return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
