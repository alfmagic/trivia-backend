import threading

TRIVIA_API_URL = "https://opentdb.com/api.php"
games_lock = threading.Lock( )
