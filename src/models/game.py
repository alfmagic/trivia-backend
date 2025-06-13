from flask import Blueprint, request, jsonify
from src.models.user import db
from src.models.game import Room, Player
import random
import string
import requests
import json
from datetime import datetime, timedelta

game_bp = Blueprint('game', __name__)

def generate_room_code():
    """Genera un código único de 6 caracteres para la sala"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Room.query.filter_by(code=code).first():
            return code

def decode_html(text):
    """Decodifica entidades HTML"""
    return text.replace('&quot;', '"').replace('&#039;', "'").replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')

def fetch_trivia_question(difficulty='', category=''):
    """Obtiene una pregunta de trivia de la API con configuraciones opcionales"""
    try:
        url = 'https://opentdb.com/api.php?amount=1&type=multiple'
        if difficulty:
            url += f'&difficulty={difficulty}'
        if category:
            url += f'&category={category}'
            
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data['response_code'] == 0 and data['results']:
            question_data = data['results'][0]
            
            # Formatear la pregunta
            question = {
                'question': decode_html(question_data['question']),
                'options': [
                    decode_html(question_data['correct_answer']),
                    *[decode_html(ans) for ans in question_data['incorrect_answers']]
                ],
                'category': question_data['category'],
                'difficulty': question_data['difficulty']
            }
            
            # Mezclar las opciones y encontrar el índice correcto
            correct_answer = question['options'][0]
            random.shuffle(question['options'])
            question['correct_answer'] = question['options'].index(correct_answer)
            
            return question
    except Exception as e:
        print(f"Error fetching question: {e}")
    
    return None

def cleanup_inactive_rooms():
    """Limpia salas inactivas (más de 1 hora sin actividad)"""
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        inactive_rooms = Room.query.filter(Room.created_at < cutoff_time).all()
        for room in inactive_rooms:
            # Eliminar jugadores de la sala
            Player.query.filter_by(room_id=room.id).delete()
            # Eliminar la sala
            db.session.delete(room)
        db.session.commit()
    except Exception as e:
        print(f"Error cleaning up rooms: {e}")
        db.session.rollback()

@game_bp.route('/create-room', methods=['POST'])
def create_room():
    """Crea una nueva sala de juego"""
    try:
        # Limpiar salas inactivas primero
        cleanup_inactive_rooms()
        
        data = request.get_json()
        player_name = data.get('player_name', '').strip()
        settings = data.get('settings', {})
        
        if not player_name:
            return jsonify({'error': 'Player name is required'}), 400
        
        # Crear nueva sala con configuraciones
        room_code = generate_room_code()
        room = Room(
            code=room_code,
            is_active=True,
            created_at=datetime.utcnow(),
            # Guardar configuraciones como JSON en un campo de texto
            current_question=json.dumps({
                'settings': {
                    'difficulty': settings.get('difficulty', ''),
                    'category': settings.get('category', ''),
                    'amount': settings.get('amount', 10)
                }
            })
        )
        db.session.add(room)
        db.session.flush()  # Para obtener el ID de la sala
        
        # Crear el jugador creador
        player = Player(
            name=player_name, 
            room_id=room.id,
            last_seen=datetime.utcnow()
        )
        db.session.add(player)
        db.session.commit()
        
        return jsonify({
            'room_code': room_code,
            'room_id': room.id,
            'player_id': player.id,
            'player_name': player_name
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creating room: {e}")
        return jsonify({'error': 'Failed to create room. Please try again.'}), 500

@game_bp.route('/join-room', methods=['POST'])
def join_room():
    """Se une a una sala existente"""
    try:
        data = request.get_json()
        room_code = data.get('room_code', '').strip().upper()
        player_name = data.get('player_name', '').strip()
        
        if not room_code or not player_name:
            return jsonify({'error': 'Room code and player name are required'}), 400
        
        # Buscar la sala
        room = Room.query.filter_by(code=room_code, is_active=True).first()
        if not room:
            return jsonify({'error': 'Room not found or inactive'}), 404
        
        # Verificar si ya hay un jugador con ese nombre en la sala
        existing_player = Player.query.filter_by(room_id=room.id, name=player_name).first()
        if existing_player:
            # Si el jugador ya existe, actualizar su last_seen y devolver sus datos
            existing_player.last_seen = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'room_code': room_code,
                'room_id': room.id,
                'player_id': existing_player.id,
                'player_name': player_name
            })
        
        # Crear el nuevo jugador
        player = Player(
            name=player_name, 
            room_id=room.id,
            last_seen=datetime.utcnow()
        )
        db.session.add(player)
        db.session.commit()
        
        return jsonify({
            'room_code': room_code,
            'room_id': room.id,
            'player_id': player.id,
            'player_name': player_name
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error joining room: {e}")
        return jsonify({'error': 'Failed to join room. Please try again.'}), 500

@game_bp.route('/room/<room_id>/status', methods=['GET'])
def get_room_status(room_id):
    """Obtiene el estado actual de la sala"""
    try:
        room = Room.query.filter_by(id=room_id, is_active=True).first()
        if not room:
            return jsonify({'error': 'Room not found or inactive'}), 404
        
        # Actualizar last_seen del jugador que hace la consulta
        player_id = request.args.get('player_id')
        if player_id:
            player = Player.query.get(player_id)
            if player and player.room_id == int(room_id):
                player.last_seen = datetime.utcnow()
                db.session.commit()
        
        players = Player.query.filter_by(room_id=room_id).all()
        
        # Parsear la pregunta actual o configuraciones
        current_data = json.loads(room.current_question) if room.current_question else {}
        current_question = current_data if 'question' in current_data else None
        
        return jsonify({
            'room_code': room.code,
            'question_number': room.question_number,
            'current_question': current_question,
            'is_active': room.is_active,
            'players': [{
                'id': player.id,
                'name': player.name,
                'score': player.score,
                'has_answered': player.has_answered
            } for player in players]
        })
        
    except Exception as e:
        print(f"Error getting room status: {e}")
        return jsonify({'error': 'Failed to get room status'}), 500

@game_bp.route('/room/<room_id>/next-question', methods=['POST'])
def next_question(room_id):
    """Carga la siguiente pregunta para la sala"""
    try:
        room = Room.query.filter_by(id=room_id, is_active=True).first()
        if not room:
            return jsonify({'error': 'Room not found or inactive'}), 404
        
        # Obtener configuraciones de la sala
        room_data = json.loads(room.current_question) if room.current_question else {}
        settings = room_data.get('settings', {})
        
        # Verificar si se ha alcanzado el límite de preguntas
        max_questions = settings.get('amount', 10)
        if room.question_number >= max_questions:
            return jsonify({'error': 'Game completed', 'game_finished': True}), 400
        
        # Obtener nueva pregunta con configuraciones
        question = fetch_trivia_question(
            difficulty=settings.get('difficulty', ''),
            category=settings.get('category', '')
        )
        if not question:
            return jsonify({'error': 'Failed to fetch question'}), 500
        
        # Actualizar la sala
        room.current_question = json.dumps(question)
        room.question_number += 1
        
        # Resetear respuestas de todos los jugadores
        Player.query.filter_by(room_id=room_id).update({
            'current_answer': None,
            'has_answered': False
        })
        
        db.session.commit()
        
        return jsonify({
            'question': question,
            'question_number': room.question_number,
            'total_questions': max_questions
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error loading next question: {e}")
        return jsonify({'error': 'Failed to load next question'}), 500

@game_bp.route('/player/<player_id>/answer', methods=['POST'])
def submit_answer(player_id):
    """Envía la respuesta de un jugador"""
    try:
        data = request.get_json()
        answer = data.get('answer')
        
        if answer is None:
            return jsonify({'error': 'Answer is required'}), 400
        
        player = Player.query.get(player_id)
        if not player:
            return jsonify({'error': 'Player not found'}), 404
        
        room = Room.query.filter_by(id=player.room_id, is_active=True).first()
        if not room or not room.current_question:
            return jsonify({'error': 'No active question'}), 400
        
        # Actualizar respuesta del jugador
        player.current_answer = answer
        player.has_answered = True
        player.last_seen = datetime.utcnow()
        
        # Verificar si la respuesta es correcta
        question_data = json.loads(room.current_question)
        is_correct = False
        if 'question' in question_data and answer == question_data['correct_answer']:
            player.score += 1
            is_correct = True
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'is_correct': is_correct,
            'correct_answer': question_data.get('correct_answer', -1)
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error submitting answer: {e}")
        return jsonify({'error': 'Failed to submit answer'}), 500

@game_bp.route('/room/<room_id>/close', methods=['POST'])
def close_room(room_id):
    """Cierra una sala de juego"""
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': 'Room not found'}), 404
        
        room.is_active = False
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        print(f"Error closing room: {e}")
        return jsonify({'error': 'Failed to close room'}), 500
