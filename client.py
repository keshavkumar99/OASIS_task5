import json
import queue
import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5050


class ChatClient:
    def __init__(self, root):
        self.root = root
        self.root.title("Connect | Python Chat")
        self.root.geometry("860x650")
        self.root.minsize(720, 540)
        self.root.configure(bg="#101827")

        self.sock = None
        self.reader = None
        self.send_lock = threading.Lock()
        self.events = queue.Queue()
        self.username = ""
        self.room = "general"
        self.connected = False

        self._style()
        self._build_login()
        self.root.after(100, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=9)
        style.configure("TEntry", padding=8)

    def _build_login(self):
        self.login_frame = tk.Frame(self.root, bg="#1b2940", padx=34, pady=30)
        self.login_frame.place(relx=0.5, rely=0.5, anchor="center", width=390)

        tk.Label(self.login_frame, text="PYCHAT", bg="#1b2940", fg="#70d6f5",
                 font=("Segoe UI", 25, "bold")).pack(anchor="w")
        tk.Label(self.login_frame, text="REAL-TIME MESSAGING",
                 bg="#1b2940", fg="#a7b7cc",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 20))

        tk.Label(self.login_frame, text="Username", bg="#1b2940", fg="#edf4ff").pack(anchor="w")
        self.username_entry = ttk.Entry(self.login_frame, font=("Segoe UI", 11))
        self.username_entry.pack(fill="x", pady=(5, 13))

        tk.Label(self.login_frame, text="Password", bg="#1b2940", fg="#edf4ff").pack(anchor="w")
        self.password_entry = ttk.Entry(self.login_frame, show="*", font=("Segoe UI", 11))
        self.password_entry.pack(fill="x", pady=(5, 16))
        self.password_entry.bind("<Return>", lambda event: self.login())

        buttons = tk.Frame(self.login_frame, bg="#1b2940")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Log in", command=self.login).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(buttons, text="Register", command=self.register).pack(side="left", fill="x", expand=True, padx=(5, 0))

        tk.Label(self.login_frame,
                 text="Create an account first, or log in with an existing account.",
                 bg="#1b2940", fg="#a7b7cc", wraplength=320,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(16, 0))

    def _build_chat(self):
        self.login_frame.destroy()
        header = tk.Frame(self.root, bg="#101827")
        header.pack(fill="x", padx=20, pady=(16, 10))
        tk.Label(header, text="PYCHAT", bg="#101827", fg="#70d6f5",
                 font=("Segoe UI", 21, "bold")).pack(side="left")
        self.user_label = tk.Label(header, text=f"Signed in as {self.username}",
                                   bg="#101827", fg="#a7b7cc",
                                   font=("Segoe UI", 9))
        self.user_label.pack(side="right")

        room_bar = tk.Frame(self.root, bg="#1b2940", padx=12, pady=10)
        room_bar.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(room_bar, text="ROOM", bg="#1b2940", fg="#a7b7cc",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))
        self.room_var = tk.StringVar(value=self.room)
        self.room_entry = ttk.Entry(room_bar, textvariable=self.room_var, width=20)
        self.room_entry.pack(side="left")
        self.room_entry.bind("<Return>", lambda event: self.join_room())
        ttk.Button(room_bar, text="Join room", command=self.join_room).pack(side="left", padx=8)
        ttk.Button(room_bar, text="Refresh history", command=self.request_history).pack(side="left")

        chat_panel = tk.Frame(self.root, bg="#1b2940")
        chat_panel.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.chat_text = tk.Text(chat_panel, state="disabled", wrap="word",
                                 bg="#1b2940", fg="#edf4ff",
                                 insertbackground="white", relief="flat",
                                 font=("Segoe UI", 10), padx=14, pady=12)
        scrollbar = ttk.Scrollbar(chat_panel, command=self.chat_text.yview)
        self.chat_text.configure(yscrollcommand=scrollbar.set)
        self.chat_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.chat_text.tag_configure("meta", foreground="#a7b7cc", font=("Segoe UI", 8))
        self.chat_text.tag_configure("name", foreground="#70d6f5", font=("Segoe UI", 9, "bold"))
        self.chat_text.tag_configure("system", foreground="#62d6a5", font=("Segoe UI", 9, "italic"))
        self.chat_text.tag_configure("body", foreground="#edf4ff")

        composer = tk.Frame(self.root, bg="#101827")
        composer.pack(fill="x", padx=20, pady=(0, 18))
        self.message_entry = ttk.Entry(composer, font=("Segoe UI", 11))
        self.message_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        self.message_entry.bind("<Return>", lambda event: self.send_message())
        ttk.Button(composer, text="Send", command=self.send_message).pack(side="right")

    def connect(self):
        try:
            self.sock = socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=6)
            self.sock.settimeout(None)
            self.reader = self.sock.makefile("r", encoding="utf-8", newline="\n")
            threading.Thread(target=self._receive_loop, daemon=True).start()
            return True
        except OSError as exc:
            messagebox.showerror(
                "Connection failed",
                f"Could not connect to {SERVER_HOST}:{SERVER_PORT}.\n"
                "Start server.py first, then try again.\n\n" + str(exc)
            )
            return False

    def _send(self, payload):
        if not self.sock:
            return
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self.send_lock:
                self.sock.sendall(data)
        except OSError:
            self.events.put({"type": "disconnected", "message": "Connection lost."})

    def register(self):
        if not self._ensure_connection():
            return
        self._send({
            "action": "register",
            "username": self.username_entry.get().strip(),
            "password": self.password_entry.get()
        })

    def login(self):
        if not self._ensure_connection():
            return
        self._send({
            "action": "login",
            "username": self.username_entry.get().strip(),
            "password": self.password_entry.get()
        })

    def _ensure_connection(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        if not username or not password:
            messagebox.showwarning("Missing details", "Enter a username and password.")
            return False
        if not self.sock and not self.connect():
            return False
        return True

    def _receive_loop(self):
        try:
            for line in self.reader:
                try:
                    self.events.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        self.events.put({"type": "disconnected", "message": "Disconnected from server."})

    def _process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("type")
                if kind == "auth":
                    if event.get("ok"):
                        messagebox.showinfo("Account", event.get("message", "Success"))
                    else:
                        messagebox.showerror("Account", event.get("message", "Authentication failed"))
                elif kind == "login_ok":
                    self.username = event["username"]
                    self.room = event.get("room", "general")
                    self.connected = True
                    self._build_chat()
                    self.display_history(event.get("history", []))
                elif kind == "room_joined":
                    self.room = event["room"]
                    self.room_var.set(self.room)
                    self.display_history(event.get("history", []))
                    self.add_system(f"You joined #{self.room}.")
                elif kind == "history":
                    self.display_history(event.get("messages", []))
                elif kind == "message":
                    self.add_message(event)
                elif kind == "system":
                    self.add_system(event.get("message", ""))
                elif kind == "error":
                    messagebox.showwarning("Chat", event.get("message", "An error occurred."))
                elif kind == "disconnected":
                    if self.connected:
                        self.add_system(event.get("message", "Disconnected."))
                    self.connected = False
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def display_history(self, messages):
        if not hasattr(self, "chat_text"):
            return
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.insert("end", f"Recent messages in #{self.room}\n\n", "system")
        self.chat_text.configure(state="disabled")
        for item in messages:
            self.add_message(item)

    def add_message(self, item):
        if not hasattr(self, "chat_text"):
            return
        try:
            stamp = datetime.fromisoformat(item.get("sent_at", "")).astimezone().strftime("%H:%M")
        except (ValueError, TypeError):
            stamp = ""
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", f"{item.get('username', 'User')}  ", "name")
        self.chat_text.insert("end", f"{stamp}\n", "meta")
        self.chat_text.insert("end", item.get("message", "") + "\n\n", "body")
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def add_system(self, message):
        if not hasattr(self, "chat_text"):
            return
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", message + "\n\n", "system")
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def send_message(self):
        if not self.connected:
            messagebox.showwarning("Not connected", "Please log in again.")
            return
        message = self.message_entry.get().strip()
        if not message:
            return
        self._send({"action": "message", "message": message})
        self.message_entry.delete(0, "end")

    def join_room(self):
        room = self.room_var.get().strip()
        if room:
            self._send({"action": "join", "room": room})

    def request_history(self):
        self._send({"action": "history"})

    def close(self):
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
        except OSError:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClient(root)
    root.mainloop()
