# server.py
import asyncio
import websockets
import json
import random
import math
import time
from settings import *

PREFIXES = ["Cool", "Frozen", "Ice", "Snow", "Brawl", "Rolling", "Winter", "Cold", "Awesome", "Amazing", "Throwing", "Super", "New"]
SUFFIXES = ["Master", "Expert", "Addict", "Sphere", "Gamer", "Gobbler", "Dude"]

class Player:
    def __init__(self, player_id, pos, name):
        self.id = player_id
        self.x, self.y = pos
        self.size = START_SIZE
        self.color = YELLOWISH_WHITE
        self.angle = 0
        self.vel = 6
        self.stun_timer = 0
        self.alive = True
        self.ready = False
        self.name = name
        self.is_moving = False  # Tracks if the mouse is held down

    def set_movement(self, move_data):
        # Updates direction and whether the mouse is clicked
        self.is_moving = move_data.get('moving', False)
        if 'angle' in move_data:
            self.angle = move_data['angle']

    def update_position(self):
        # Applies continuous forward motion if the mouse is currently held
        if not self.alive:
            return
        if self.stun_timer > 0:
            self.stun_timer -= 1
            return
        if self.is_moving:
            dx = math.cos(self.angle) * self.vel
            dy = math.sin(self.angle) * self.vel
            self.x = max(-MAP_SIZE, min(MAP_SIZE, self.x + dx))
            self.y = max(-MAP_SIZE, min(MAP_SIZE, self.y + dy))

    # This was missing! The server needs this to send player data to the client.
    def to_dict(self):
        return {
            "id": self.id,
            "x": int(self.x),
            "y": int(self.y),
            "size": int(self.size),
            "angle": self.angle,
            "alive": self.alive,
            "ready": self.ready,
            "name": self.name
        }
class Particle:
    def __init__(self, x, y, size=5):
        self.x = x
        self.y = y
        self.size = size
        self.id = random.randint(0, 1000000)

class Projectile:
    def __init__(self, owner_id, x, y, angle, size):
        self.owner_id = owner_id
        self.x = x
        self.y = y
        self.angle = angle
        self.size = size
        self.speed = 10
        self.life = 60

    def update(self):
        self.x += math.cos(self.angle) * self.speed
        self.y += math.sin(self.angle) * self.speed
        self.life -= 1

class Room:
    def __init__(self, room_id):
        self.room_id = room_id
        self.players = {}
        self.conns = {}
        self.projectiles = []
        self.particles = [
            Particle(random.randint(-MAP_SIZE, MAP_SIZE), random.randint(-MAP_SIZE, MAP_SIZE))
            for _ in range(MAX_PARTICLES)
        ]
        self.game_started = False
        self.lobby_timer_start = None
        self.lobby_duration = 60
        self.ring_radius = MAP_SIZE * 1.5
        self.running = True

    def generate_unique_name(self, p_id):
        max_unique = len(PREFIXES) * len(SUFFIXES)
        if len(self.players) >= max_unique:
            return f"Player{p_id}"

        for _ in range(100):
            new_name = f"{random.choice(PREFIXES)}{random.choice(SUFFIXES)}"
            if not any(p.name == new_name for p in self.players.values()):
                return new_name
        return f"Player{p_id}"

    def get_safe_spawn(self):
        while True:
            rx = random.randint(-MAP_SIZE, MAP_SIZE)
            ry = random.randint(-MAP_SIZE, MAP_SIZE)
            safe = True
            for p in self.players.values():
                if math.hypot(rx - p.x, ry - p.y) < (START_SIZE * 3):
                    safe = False
                    break
            if safe:
                return rx, ry

    async def broadcast(self, data):
        msg = json.dumps(data)
        # Send to each client individually
        for ws in list(self.conns.values()):
            try:
                await ws.send(msg)
            except Exception:
                pass

    async def room_loop(self):
        while self.running:
            start_time = time.time()

            # Check ready status & Timer
            remaining_time = self.lobby_duration
            if not self.game_started:
                if len(self.players) > 1:
                    if self.lobby_timer_start is None:
                        self.lobby_timer_start = time.time()
                    
                    elapsed = time.time() - self.lobby_timer_start
                    remaining_time = max(0, int(self.lobby_duration - elapsed))
                    ready_count = sum(1 for p in self.players.values() if p.ready)
                    
                    if ready_count == len(self.players) or elapsed >= self.lobby_duration:
                        self.game_started = True
                else:
                    self.lobby_timer_start = None

            if self.game_started:
                for p in self.players.values():
                    p.update_position()


                self.ring_radius -= RING_SHRINK_RATE
                if self.ring_radius < 0:
                    self.ring_radius = 0

                for proj in self.projectiles[:]:
                    proj.update()
                    if proj.life <= 0:
                        self.projectiles.remove(proj)
                        for _ in range(3):
                            self.particles.append(Particle(proj.x + random.randint(-10, 10), proj.y + random.randint(-10, 10), proj.size / 3))

                for pid, p in self.players.items():
                    if not p.alive:
                        continue

                    if math.sqrt(p.x**2 + p.y**2) > self.ring_radius:
                        p.size -= 0.5
                        if p.size <= 5:
                            p.alive = False

                    for part in self.particles[:]:
                        if math.hypot(p.x - part.x, p.y - part.y) < p.size + part.size:
                            p.size += part.size * 0.1
                            self.particles.remove(part)

                    for proj in self.projectiles[:]:
                        if proj.owner_id != pid:
                            if math.hypot(p.x - proj.x, p.y - proj.y) < p.size + proj.size:
                                self.projectiles.remove(proj)
                                if proj.size > p.size:
                                    p.alive = False
                                    for _ in range(5):
                                        self.particles.append(Particle(p.x, p.y, p.size / 5))
                                else:
                                    p.stun_timer = int(proj.size * STUN_MULTIPLIER)

                    for other_id, other_p in self.players.items():
                        if pid != other_id and other_p.alive:
                            if math.hypot(p.x - other_p.x, p.y - other_p.y) < p.size and p.size >= other_p.size + 10:
                                other_p.alive = False
                                p.size += other_p.size * 0.5

                if len(self.particles) < MAX_PARTICLES:
                    self.particles.append(Particle(random.randint(-int(self.ring_radius), int(self.ring_radius)), random.randint(-int(self.ring_radius), int(self.ring_radius))))

                alive_players = [p for p in self.players.values() if p.alive]
                if len(alive_players) <= 1:
                    winner_name = alive_players[0].name if alive_players else "Nobody"
                    winner_id = alive_players[0].id if alive_players else None

                    await self.broadcast({"command": "game_over", "winner_id": winner_id, "winner_name": winner_name})
                    await asyncio.sleep(3)
                    
                    for ws in list(self.conns.values()):
                        try:
                            await ws.close()
                        except:
                            pass
                    self.players.clear()
                    self.conns.clear()
                    self.running = False

                    if self.room_id in rooms:
                        del rooms[self.room_id]
                    break

            # COMPRESSED PAYLOAD: Send arrays instead of dicts for particles/projectiles
            state = {
                "players": [p.to_dict() for p in self.players.values()],
                "particles": [[int(pt.x), int(pt.y), int(pt.size)] for pt in self.particles],
                "projectiles": [[int(pj.x), int(pj.y), int(pj.size)] for pj in self.projectiles],
                "ring": int(self.ring_radius),
                "started": self.game_started,
                "lobby_time": remaining_time
            }
            await self.broadcast(state)

            # Drop the server broadcast rate to 30 tick (Client still renders at 60fps)
            await asyncio.sleep(1 / 30)


rooms = {}
_room_counter = 1
_id_counter = 1

def find_or_create_room():
    global _room_counter
    for room in rooms.values():
        if not room.game_started and len(room.players) < 4:
            return room

    new_room = Room(_room_counter)
    rooms[_room_counter] = new_room
    _room_counter += 1
    
    # FIX: Store a strong reference to the task so it isn't garbage collected
    new_room.task = asyncio.create_task(new_room.room_loop())
    return new_room

async def handle_client(websocket):
    global _id_counter
    p_id = _id_counter
    _id_counter += 1

    room = find_or_create_room()
    spawn_pos = room.get_safe_spawn()
    p_name = room.generate_unique_name(p_id)

    # FIX: Send the client ID FIRST
    await websocket.send(str(p_id))

    # THEN add them to the room so the background loop can safely see them
    room.conns[p_id] = websocket
    room.players[p_id] = Player(p_id, spawn_pos, p_name)

    try:
        async for message in websocket:
            cmd = json.loads(message)

            if p_id in room.players:
                p = room.players[p_id]

                if 'command' in cmd:
                    if cmd['command'] == 'ready':
                        p.ready = True
                    elif cmd['command'] == 'shoot' and p.alive:
                        cost_ratio = 0.25 if cmd['type'] == 1 else 0.5
                        if p.size >= 20:
                            shot_size = p.size * cost_ratio
                            p.size -= shot_size
                            proj = Projectile(p_id, p.x, p.y, p.angle, shot_size)
                            room.projectiles.append(proj)
                    elif cmd['command'] == 'move':
                        p.set_movement(cmd)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if p_id in room.players:
            del room.players[p_id]
        if p_id in room.conns:
            del room.conns[p_id]

        if len(room.players) == 0:
            room.running = False
            if room.room_id in rooms:
                del rooms[room.room_id]

async def main():
    print(f"WebSocket Server waiting for connections on port {PORT}...")
    # Bind to 0.0.0.0 to allow external connections
    async with websockets.serve(handle_client, "0.0.0.0", PORT):
        await asyncio.Future()  # run forever



import os

async def main():
    # Cloud hosts pass the port via an environment variable. 
    # If it doesn't exist, fallback to your local PORT.
    cloud_port = int(os.environ.get("PORT", PORT))
    
    print(f"WebSocket Server waiting for connections on port {cloud_port}...")
    async with websockets.serve(handle_client, "0.0.0.0", cloud_port):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())