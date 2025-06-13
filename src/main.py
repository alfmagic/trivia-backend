from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import random
import time
import threading
from datetime import datetime, timedelta

# Import from config (NUEVA LÍNEA)
from src.config import TRIVIA_API_URL, games_lock

# Import routes and models
from src.routes.game import game_bp
from src.models.game import games, Game, Player

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# Register blueprints
app.register_blueprint(game_bp)

# Configuration for trivia API (ELIMINA ESTAS LÍNEAS)
# TRIVIA_API_URL = "https://opentdb.com/api.php"

# Global lock for thread-safe operations on 'games' dictionary (ELIMINA ESTAS LÍNEAS )
# games_lock = threading.Lock()

# Function to clean up inactive games
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

# Schedule cleanup to run periodically
def start_cleanup_scheduler():
    cleanup_inactive_games()
    # Run every 30 minutes
    threading.Timer(1800, start_cleanup_scheduler).start()

# Start the cleanup scheduler when the app starts
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
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        data = response.json()

        if data['response_code'] == 0 and data['results']:
            question_data = data['results'][0]
            question = {
                "id": str(random.randint(100000, 999999)), # Unique ID for the question
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
