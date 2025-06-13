import random
from datetime import datetime, timedelta

# In-memory storage for games and players
# In a real-world application, this would be a database (e.g., PostgreSQL, MongoDB)
games = {} # Stores Game objects, keyed by room_id

class Player:
    def __init__(self, name, player_id):
        self.name = name
        self.player_id = player_id
        self.score = 0
        self.answered_current_question = False

    def to_dict(self):
        return {
            "name": self.name,
            "id": self.player_id,
            "score": self.score
        }

class Game:
    def __init__(self, room_id, host_id, host_name, difficulty, category, num_questions):
        self.room_id = room_id
        self.host_id = host_id
        self.players = {host_id: Player(host_name, host_id)}
        self.current_question = None
        self.current_question_index = 0
        self.game_started = False
        self.game_ended = False
        self.difficulty = difficulty
        self.category = category
        self.num_questions = num_questions # Total questions for multiplayer
        self.asked_questions = [] # List of question IDs already asked
        self.last_activity = datetime.now()

    def add_player(self, player_name, player_id):
        if player_id not in self.players:
            self.players[player_id] = Player(player_name, player_id)
            self.last_activity = datetime.now()
            return True
        return False

    def remove_player(self, player_id):
        if player_id in self.players:
            del self.players[player_id]
            self.last_activity = datetime.now()
            return True
        return False

    def get_player(self, player_id):
        return self.players.get(player_id)

    def get_players_list(self):
        players_list = [player.to_dict() for player in self.players.values()]
        # Add host status
        for player_data in players_list:
            player_data['is_host'] = (player_data['id'] == self.host_id)
        return players_list

    def start_game(self):
        self.game_started = True
        self.game_ended = False
        self.current_question_index = 0
        for player in self.players.values():
            player.score = 0
        self.last_activity = datetime.now()

    def set_current_question(self, question_data):
        self.current_question = question_data
        self.asked_questions.append(question_data['id']) # Store question ID
        self.current_question_index += 1
        for player in self.players.values():
            player.answered_current_question = False
        self.last_activity = datetime.now()

    def submit_answer(self, player_id, question_id, answer):
        player = self.get_player(player_id)
        if player and not player.answered_current_question and self.current_question and self.current_question['id'] == question_id:
            player.answered_current_question = True
            if answer == self.current_question['correct_answer']:
                player.score += 1
            self.last_activity = datetime.now()
            return True
        return False

    def all_players_answered(self):
        if not self.players:
            return False
        for player in self.players.values():
            if not player.answered_current_question:
                return False
        return True

    def get_player_scores(self):
        return {player.name: player.score for player in self.players.values()}

    def end_game(self):
        self.game_ended = True
        self.game_started = False
        self.last_activity = datetime.now()

