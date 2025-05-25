from flask import Flask, render_template
from flask_sock import Sock
import json
import threading
import time

app = Flask(__name__)
sock = Sock(app)

# store connected clients and their data
clients = {}
positions = {}  # store positions of all players
sprites = {}    # store sprite data (image or letter) for all players
names = {}      # store chat names for all players

def cleanup_disconnected_clients():
    while True:
        time.sleep(10)  # clean up every 10 seconds
        disconnected_clients = []
        for client_id, ws in clients.items():
            try:
                # ping
                ws.send(json.dumps({"type": "ping"}))
            except:
                # disconnect if error
                disconnected_clients.append(client_id)

        # get rid of disconnected client
        for client_id in disconnected_clients:
            if client_id in clients:
                del clients[client_id]
            if client_id in positions:
                del positions[client_id]
            if client_id in sprites:
                del sprites[client_id]
            if client_id in names:
                del names[client_id]
            print(f"Removed disconnected client: {client_id}")

# start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_disconnected_clients, daemon=True)
cleanup_thread.start()

@app.route('/')
def home():
    return render_template('page.html')

@sock.route('/ws')
def websocket(ws):
    # make id for clients
    client_id = id(ws)
    clients[client_id] = ws
    positions[client_id] = {'x': 100, 'y': 100}  # Default position for new players
    sprites[client_id] = 'new player'  # Default sprite (letter 'A')
    names[client_id] = f'Player {client_id}'  # Default name

    # lets previous clients know about new client
    for other_id, other_ws in clients.items():
        if other_id != client_id:
            try:
                other_ws.send(json.dumps({
                    'type': 'new_player',
                    'id': client_id,
                    'x': positions[client_id]['x'],
                    'y': positions[client_id]['y'],
                    'sprite': sprites[client_id],
                    'name': names[client_id]
                }))
            except:
                pass

    # lets new clients know about previous clients
    try:
        for other_id, position in positions.items():
            if other_id != client_id:
                ws.send(json.dumps({
                    'type': 'new_player',
                    'id': other_id,
                    'x': position['x'],
                    'y': position['y'],
                    'sprite': sprites[other_id],
                    'name': names[other_id]
                }))
    except:
        pass

    try:
        while True:
            data = json.loads(ws.receive())
            if data['type'] == 'move':
                # updates positions in local client
                positions[client_id] = {'x': data['x'], 'y': data['y']}
                # tells other clients position
                for other_id, other_ws in clients.items():
                    if other_id != client_id:
                        try:
                            other_ws.send(json.dumps({
                                'type': 'move',
                                'id': client_id,
                                'x': data['x'],
                                'y': data['y']
                            }))
                        except:
                            pass
            elif data['type'] == 'chat':
                # send message in chat with styles
                for other_id, other_ws in clients.items():
                    try:
                        other_ws.send(json.dumps({
                            'type': 'chat',
                            'id': client_id,
                            'name': names[client_id],
                            'message': data['message'],
                            'style': data.get('style', {})  # Include style if provided
                        }))
                    except:
                        pass
            elif data['type'] == 'update_sprite':
                # new sprite for new client
                sprites[client_id] = data['sprite']
                # lets clients know
                for other_id, other_ws in clients.items():
                    if other_id != client_id:
                        try:
                            other_ws.send(json.dumps({
                                'type': 'update_sprite',
                                'id': client_id,
                                'sprite': data['sprite']
                            }))
                        except:
                            pass
            elif data['type'] == 'update_name':
                # name for new client
                names[client_id] = data['name']
                # lets clients know
                for other_id, other_ws in clients.items():
                    if other_id != client_id:
                        try:
                            other_ws.send(json.dumps({
                                'type': 'update_name',
                                'id': client_id,
                                'name': data['name']
                            }))
                        except:
                            pass
    except:
        pass
    finally:
        # remove client thumbup
        if client_id in clients:
            del clients[client_id]
        if client_id in positions:
            del positions[client_id]
        if client_id in sprites:
            del sprites[client_id]
        if client_id in names:
            del names[client_id]

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=53724, debug=True)