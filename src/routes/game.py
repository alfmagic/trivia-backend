from flask import Blueprint, request, jsonify
import requests
import random
import uuid # For generating unique IDs
from datetime import datetime

from src.models.game import games, Game, Player
from src.config import TRIVIA_API_URL, games_lock # CAMBIA ESTA LÍNEA

game_bp = Blueprint('game_bp', __name__)

@game_bp.route('/create_room', methods=['POST'])
def create_room():
    data = request.get_json()
    player_name = data.get('player_name')
    difficulty = data.get('difficulty', 'any')
    category = data.get('category', 'any')
    num_questions = data.get('num_questions', 10) # Default to 10 questions for multiplayer

    if not player_name:
        return jsonify({"error": "Player name is required"}), 400

    room_id = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))
    player_id = str(uuid.uuid4()) # Unique ID for the player

    with games_lock:
        game = Game(room_id, player_id, player_name, difficulty, category, num_questions)
        games[room_id] = game
        game.last_activity = datetime.now() # Update activity on creation

    return jsonify({
        "room_id": room_id,
        "player_id": player_id,
        "players": game.get_players_list()
    }), 201

@game_bp.route('/join_room', methods=['POST'])
def join_room():
    data = request.get_json()
    room_id = data.get('room_id')
    player_name = data.get('player_name')

    if not room_id or not player_name:
        return jsonify({"error": "Room ID and player name are required"}), 400

    with games_lock:
        game = games.get(room_id)
        if not game:
            return jsonify({"error": "Room not found"}), 404

        player_id = str(uuid.uuid4()) # Unique ID for the player
        if not game.add_player(player_name, player_id):
            return jsonify({"error": "Failed to add player to room"}), 500
        game.last_activity = datetime.now() # Update activity on join

    return jsonify({
        "room_id": room_id,
        "player_id": player_id,
        "players": game.get_players_list(),
        "game_started": game.game_started,
        "current_question_index": game.current_question_index,
        "total_questions": game.num_questions,
        "player_scores": game.get_player_scores(),
        "player_answered": {p.name: p.answered_current_question for p in game.players.values()}
    }), 200

@game_bp.route('/room_state/<room_id>', methods=['GET'])
def get_room_state(room_id):
    player_name = request.args.get('player_name') # Get player_name from query params

    with games_lock:
        game = games.get(room_id)
        if not game:
            return jsonify({"error": "Room not found"}), 404

        # Update last activity for the room if a player is actively polling
        game.last_activity = datetime.now()

        # Check if the polling player is still in the game
        if player_name and not any(p.name == player_name for p in game.players.values()):
            return jsonify({"error": "Player not found in room"}), 404

        return jsonify({
            "room_id": game.room_id,
            "players": game.get_players_list(),
            "game_started": game.game_started,
            "current_question": game.current_question,
            "current_question_index": game.current_question_index,
            "total_questions": game.num_questions,
            "player_scores": game.get_player_scores(),
            "player_answered": {p.name: p.answered_current_question for p in game.players.values()},
            "game_ended": game.game_ended
        }), 200

@game_bp.route('/start_game', methods=['POST'])
def start_game():
    data = request.get_json()
    room_id = data.get('room_id')

    with games_lock:
        game = games.get(room_id)
        if not game:
            return jsonify({"error": "Room not found"}), 404
        if game.game_started:
            return jsonify({"error": "Game already started"}), 400

        game.start_game()
        game.last_activity = datetime.now()

        # Fetch first question
        try:
            params = {
                "amount": 1,
                "type": "multiple"
            }
            if game.difficulty != 'any':
                params["difficulty"] = game.difficulty
            if game.category != 'any':
                params["category"] = game.category

            response = requests.get(TRIVIA_API_URL, params=params, timeout=10)
            response.raise_for_status()
            question_data = response.json()

            if question_data['response_code'] == 0 and question_data['results']:
                q = question_data['results'][0]
                question_obj = {
                    "id": str(uuid.uuid4()), # Unique ID for this specific question instance
                    "category": q['category'],
                    "type": q['type'],
                    "difficulty": q['difficulty'],
                    "question": q['question'],
                    "correct_answer": q['correct_answer'],
                    "incorrect_answers": q['incorrect_answers']
                }
                game.set_current_question(question_obj)
            else:
                game.end_game() # End game if no question can be fetched
                return jsonify({"error": "Could not fetch initial question"}), 500
        except requests.exceptions.RequestException as e:
            game.end_game() # End game if API call fails
            return jsonify({"error": f"Error fetching initial question from external API: {e}"}), 500

    return jsonify({
        "message": "Game started",
        "question": game.current_question,
        "total_questions": game.num_questions,
        "player_scores": game.get_player_scores()
    }), 200

@game_bp.route('/submit_answer', methods=['POST'])
def submit_answer():
    data = request.get_json()
    room_id = data.get('room_id')
    player_name = data.get('player_name')
    question_id = data.get('question_id')
    answer = data.get('answer')

    if not room_id or not player_name or not question_id or answer is None:
        return jsonify({"error": "Missing required fields"}), 400

    with games_lock:
        game = games.get(room_id)
        if not game:
            return jsonify({"error": "Room not found"}), 404
        if not game.game_started:
            return jsonify({"error": "Game has not started"}), 400

        # Find the player by name (assuming names are unique for simplicity in this context)
        # In a real app, you'd use player_id passed from frontend
        player_obj = next((p for p in game.players.values() if p.name == player_name), None)
        if not player_obj:
            return jsonify({"error": "Player not found in room"}), 404

        if game.submit_answer(player_obj.player_id, question_id, answer):
            game.last_activity = datetime.now()
            # Check if all players have answered
            if game.all_players_answered():
                # If it's the last question, end the game
                if game.current_question_index >= game.num_questions:
                    game.end_game()
                    return jsonify({"message": "Answer submitted, game ended"}), 200
                else:
                    # Fetch next question
                    try:
                        params = {
                            "amount": 1,
                            "type": "multiple"
                        }
                        if game.difficulty != 'any':
                            params["difficulty"] = game.difficulty
                        if game.category != 'any':
                            params["category"] = game.category

                        response = requests.get(TRIVIA_API_URL, params=params, timeout=10)
                        response.raise_for_status()
                        question_data = response.json()

                        if question_data['response_code'] == 0 and question_data['results']:
                            q = question_data['results'][0]
                            question_obj = {
                                "id": str(uuid.uuid4()), # Unique ID for this specific question instance
                                "category": q['category'],
                                "type": q['type'],
                                "difficulty": q['difficulty'],
                                "question": q['question'],
                                "correct_answer": q['correct_answer'],
                                "incorrect_answers": q['incorrect_answers']
                            }
                            game.set_current_question(question_obj)
                        else:
                            game.end_game() # End game if no question can be fetched
                            return jsonify({"error": "Could not fetch next question"}), 500
                    except requests.exceptions.RequestException as e:
                        game.end_game() # End game if API call fails
                        return jsonify({"error": f"Error fetching next question from external API: {e}"}), 500
            return jsonify({"message": "Answer submitted"}), 200
        else:
            return jsonify({"error": "Invalid submission or already answered"}), 400
