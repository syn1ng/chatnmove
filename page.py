from flask import Flask, render_template, jsonify
from flask_sock import Sock
import json
import threading
import time
import logging
from werkzeug.serving import WSGIRequestHandler

app = Flask(__name__)
sock = Sock(app)

# reduce default access logging (don't show raw IPs)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
app.logger.setLevel(logging.INFO)
# ensure app logger prints to console
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
handler.setFormatter(formatter)
if not app.logger.handlers:
    app.logger.addHandler(handler)


class QuietHandler(WSGIRequestHandler):
    # suppress low-level HTTP error messages (e.g., "Bad request version")
    def log_error(self, format, *args):
        # optionally forward to app logger at debug level
        try:
            app.logger.debug(format % args)
        except Exception:
            pass

# store connected clients and their data
clients = {}
positions = {}  # store positions of all players
sprites = {}    # store sprite data (image or letter) for all players
names = {}      # store chat names for all players
# simple thread-safe counter for short display names (Player1, Player2...)
name_counter = 1
name_lock = threading.Lock()

def assign_display_name():
    global name_counter
    with name_lock:
        name = f"Player{name_counter}"
        name_counter += 1
    return name

def cleanup_disconnected_clients():
    while True:
        time.sleep(10)  # clean up every 10 seconds
        # iterate over a snapshot to allow removing while iterating
        for client_id, ws in list(clients.items()):
            try:
                # ping; if this raises, client is likely disconnected/malformed
                ws.send(json.dumps({"type": "ping"}))
            except Exception:
                # remove immediately (best-effort) and avoid exposing network info
                try:
                    if client_id in clients:
                        del clients[client_id]
                    if client_id in positions:
                        del positions[client_id]
                    if client_id in sprites:
                        del sprites[client_id]
                    if client_id in names:
                        removed_name = names.pop(client_id, None)
                    else:
                        removed_name = None
                except Exception:
                    removed_name = None

                # friendly log only (no IPs)
                app.logger.info(f"Removed disconnected client: {removed_name or client_id}")

                # notify remaining clients of updated user list (names only)
                for other_id, other_ws in list(clients.items()):
                    try:
                        other_ws.send(json.dumps({
                            'type': 'user_names',
                            'users': list(names.values())
                        }))
                    except:
                        pass

# start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_disconnected_clients, daemon=True)

@app.route('/')
def home():
    return render_template('page.html')

@sock.route('/ws')
def websocket(ws):
    # make id for clients
    client_id = id(ws)
    clients[client_id] = ws
    positions[client_id] = {'x': 100, 'y': 100}  # Default position for new players
    sprites[client_id] = 'new player'  # default sprite
    names[client_id] = assign_display_name()  # default shortname
    # use chat name instead of ip address for logging
    app.logger.info(f"Connected: {names[client_id]}")

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
            raw = ws.receive()
            # if receive returns None the socket is closed
            if raw is None:
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                app.logger.warning(f"Bad JSON from {names.get(client_id, client_id)}: {raw!r}")
                # reply with structured error if possible
                try:
                    ws.send(json.dumps({
                        'type': 'error',
                        'message': 'invalid_json',
                        'raw': str(raw)[:200]
                    }))
                except:
                    pass
                continue
            except Exception as e:
                app.logger.exception(f"Error parsing payload from {names.get(client_id, client_id)}")
                try:
                    ws.send(json.dumps({
                        'type': 'error',
                        'message': 'parse_error'
                    }))
                except:
                    pass
                continue
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
                app.logger.info(f"{names.get(client_id, client_id)}: {data['message']}")
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
                app.logger.info(f"{names.get(client_id, client_id)} updated sprite to: {data['sprite']}")
            elif data['type'] == 'update_name':
                # name for new client
                old_name = names.get(client_id, f'Player {client_id}')
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
                app.logger.info(f"{old_name} changed name to {data['name']}")
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
        # notify remaining clients of updated user list (names only)
        for other_id, other_ws in clients.items():
            try:
                other_ws.send(json.dumps({
                    'type': 'user_names',
                    'users': list(names.values())
                }))
            except:
                pass


@app.route('/users')
def users():
    # return only display names — do NOT expose IP addresses or raw connection ids
    return jsonify(list(names.values()))


@app.route('/players')
def players_page():
    # render a simple page that lists connected players (fetches /users)
    return render_template('players.html')

if __name__ == '__main__':
    # start background maintenance thread from the running process
    try:
        cleanup_thread.start()
    except RuntimeError:
        # thread already started
        pass
    # run without the reloader so background threads stay in the same process
    # use a custom request handler to suppress low-level "Bad request version" logs
    app.run(host='0.0.0.0', port=11291, debug=True, use_reloader=False, request_handler=QuietHandler)