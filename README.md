# PyChat - Advanced Python Chat Application

A real-time multi-user chat application with a Tkinter GUI, TCP sockets, threaded server, room-based messaging, SQLite history, and account registration/login.

## Features
- Separate server and GUI client
- Multiple users can connect at the same time
- Register and log in with username/password
- Multiple chat rooms (for example: general, study, projects)
- Real-time messages using TCP sockets and threads
- SQLite message history per room
- Last 50 messages loaded when entering a room
- Passwords stored as PBKDF2-HMAC-SHA256 hashes with random salts
- No third-party Python packages required

## Requirements
- Python 3.10+
- Tkinter support in your Python installation
- Both server and clients on the same network for LAN use

## Run locally on one computer
1. Extract the ZIP and open the folder in VS Code.
2. Open Terminal 1 and start the server:

   ```bash
   python server.py
   ```

3. Open Terminal 2 and start a client:

   ```bash
   python client.py
   ```

4. Start `client.py` again in another terminal/window to test multiple users.
5. Register different usernames, log in, and join the same room to chat.

## Run across computers on a local network
1. Start `server.py` on the host computer.
2. Find the host computer's LAN IP address.
3. In `client.py`, change `SERVER_HOST = "127.0.0.1"` to the host computer's LAN IP.
4. Allow Python through the host firewall for the private network.
5. Run `client.py` on other computers connected to the same trusted LAN.

Do not expose this basic educational server directly to the public internet. It does not include TLS encryption, rate limiting, account lockout, email verification, or production-grade session management. For public deployment, use TLS, stronger operational controls, and security review.

## Database
The server creates `chat_history.db` automatically. It stores user account hashes and room messages. Back up this file to preserve chat history. Treat it as private user data.

## Protocol
The client and server exchange one JSON object per newline over TCP. Passwords are sent over the network during login/registration, so only use this demo on localhost or a trusted network. Add TLS before using it across untrusted networks.
