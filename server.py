import hashlib
import json
import secrets
import socket
import sqlite3
import threading
from datetime import datetime, timezone

HOST = "127.0.0.1"
PORT = 5050
DB_PATH = "chat_history.db"
MAX_LINE = 64 * 1024


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return salt.hex(), digest.hex()


class ChatServer:
    def __init__(self, host=HOST, port=PORT, db_path=DB_PATH):
        self.host = host
        self.port = port
        self.db_path = db_path
        self.clients = {}  # socket -> {"username": str, "room": str, "send_lock": Lock}
        self.clients_lock = threading.Lock()
        self.server_socket = None
        self.running = False
        self.init_db()

    def db(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY COLLATE NOCASE,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    room TEXT NOT NULL,
                    message TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_room_id ON messages(room, id)")

    @staticmethod
    def send_json(sock, lock, payload):
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with lock:
            sock.sendall(data)

    def safe_send(self, sock, payload):
        with self.clients_lock:
            info = self.clients.get(sock)
        if info:
            try:
                self.send_json(sock, info["send_lock"], payload)
            except OSError:
                self.remove_client(sock)

    def register(self, username, password):
        username = username.strip()
        if not 3 <= len(username) <= 20 or not username.replace("_", "").isalnum():
            return False, "Username must be 3-20 characters (letters, numbers, underscore)."
        if not 8 <= len(password) <= 128:
            return False, "Password must be at least 8 characters."
        salt, digest = hash_password(password)
        try:
            with self.db() as conn:
                conn.execute(
                    "INSERT INTO users(username, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (username, salt, digest, datetime.now(timezone.utc).isoformat())
                )
            return True, "Account created. You can now log in."
        except sqlite3.IntegrityError:
            return False, "That username is already registered."

    def authenticate(self, username, password):
        with self.db() as conn:
            row = conn.execute(
                "SELECT salt, password_hash FROM users WHERE username = ?",
                (username,)
            ).fetchone()
        if not row:
            # Perform a dummy hash to reduce obvious username timing differences.
            hash_password(password, bytes(16))
            return False
        _, digest = hash_password(password, bytes.fromhex(row["salt"]))
        return secrets.compare_digest(digest, row["password_hash"])

    def save_message(self, username, room, message):
        sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.db() as conn:
            cur = conn.execute(
                "INSERT INTO messages(username, room, message, sent_at) VALUES (?, ?, ?, ?)",
                (username, room, message, sent_at)
            )
            message_id = cur.lastrowid
        return {"type": "message", "id": message_id, "username": username,
                "room": room, "message": message, "sent_at": sent_at}

    def get_history(self, room, limit=50):
        with self.db() as conn:
            rows = conn.execute(
                """SELECT id, username, room, message, sent_at
                   FROM messages WHERE room = ?
                   ORDER BY id DESC LIMIT ?""",
                (room, limit)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def broadcast(self, room, payload, exclude=None):
        with self.clients_lock:
            recipients = [
                (sock, info["send_lock"])
                for sock, info in self.clients.items()
                if info["room"] == room and sock is not exclude
            ]
        dead = []
        for sock, lock in recipients:
            try:
                self.send_json(sock, lock, payload)
            except OSError:
                dead.append(sock)
        for sock in dead:
            self.remove_client(sock)

    def remove_client(self, sock):
        with self.clients_lock:
            info = self.clients.pop(sock, None)
        if info:
            try:
                sock.close()
            except OSError:
                pass
            self.broadcast(info["room"], {
                "type": "system",
                "message": f"{info['username']} left #{info['room']}."
            })

    def handle_client(self, sock, address):
        file = sock.makefile("r", encoding="utf-8", newline="\n")
        authenticated = False
        username = None
        current_room = "general"
        send_lock = threading.Lock()
        try:
            self.send_json(sock, send_lock, {
                "type": "info",
                "message": "Connected to the chat server. Register or log in to continue."
            })
            for line in file:
                if len(line) > MAX_LINE:
                    self.send_json(sock, send_lock, {"type": "error", "message": "Request too large."})
                    break
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    self.send_json(sock, send_lock, {"type": "error", "message": "Invalid request format."})
                    continue

                action = request.get("action")

                if action == "register" and not authenticated:
                    ok, message = self.register(str(request.get("username", "")),
                                                str(request.get("password", "")))
                    self.send_json(sock, send_lock, {"type": "auth", "ok": ok, "message": message})
                elif action == "login" and not authenticated:
                    candidate = str(request.get("username", "")).strip()
                    password = str(request.get("password", ""))
                    if self.authenticate(candidate, password):
                        username = candidate
                        authenticated = True
                        with self.clients_lock:
                            self.clients[sock] = {
                                "username": username, "room": current_room,
                                "send_lock": send_lock
                            }
                        self.send_json(sock, send_lock, {
                            "type": "login_ok", "username": username,
                            "room": current_room, "history": self.get_history(current_room)
                        })
                        self.broadcast(current_room, {
                            "type": "system", "message": f"{username} joined #{current_room}."
                        }, exclude=sock)
                    else:
                        self.send_json(sock, send_lock, {
                            "type": "auth", "ok": False, "message": "Invalid username or password."
                        })
                elif not authenticated:
                    self.send_json(sock, send_lock, {
                        "type": "error", "message": "Please log in first."
                    })
                elif action == "join":
                    room = str(request.get("room", "")).strip().lower()
                    if not 1 <= len(room) <= 24 or not room.replace("_", "").isalnum():
                        self.safe_send(sock, {"type": "error", "message": "Room must be 1-24 letters, numbers, or underscores."})
                        continue
                    old_room = current_room
                    self.broadcast(old_room, {
                        "type": "system", "message": f"{username} left #{old_room}."
                    }, exclude=sock)
                    current_room = room
                    with self.clients_lock:
                        if sock in self.clients:
                            self.clients[sock]["room"] = current_room
                    self.safe_send(sock, {
                        "type": "room_joined", "room": room,
                        "history": self.get_history(room)
                    })
                    self.broadcast(room, {
                        "type": "system", "message": f"{username} joined #{room}."
                    }, exclude=sock)
                elif action == "message":
                    message = str(request.get("message", "")).strip()
                    if not message:
                        continue
                    if len(message) > 2000:
                        self.safe_send(sock, {"type": "error", "message": "Messages must be 2,000 characters or fewer."})
                        continue
                    payload = self.save_message(username, current_room, message)
                    self.broadcast(current_room, payload)
                elif action == "history":
                    self.safe_send(sock, {
                        "type": "history", "room": current_room,
                        "messages": self.get_history(current_room)
                    })
                else:
                    self.safe_send(sock, {"type": "error", "message": "Unknown action."})
        except (OSError, ConnectionError):
            pass
        finally:
            try:
                file.close()
            except OSError:
                pass
            self.remove_client(sock)

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen()
        self.running = True
        print(f"Chat server listening on {self.host}:{self.port}")
        print("Press Ctrl+C to stop.")
        try:
            while self.running:
                client, address = self.server_socket.accept()
                print(f"Connection from {address}")
                threading.Thread(target=self.handle_client,
                                 args=(client, address), daemon=True).start()
        except KeyboardInterrupt:
            print("\nShutting down server...")
        finally:
            self.running = False
            self.server_socket.close()
            with self.clients_lock:
                sockets = list(self.clients.keys())
            for client in sockets:
                self.remove_client(client)


if __name__ == "__main__":
    ChatServer().start()
