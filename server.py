import asyncio
import websockets
import json
import random
import math
import time
import os
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
        self.vel = 5  
        self.stun_timer = 0
        self.alive = True
        self.ready = False
        self.name = name
        self.is_moving = False
        self.is_bot = False  
        
        self.is_aiming = False
        self.aim_angle = 0
        self.kb_dx = 0
        self.kb_dy = 0
        self.last_shoot_time = 0 
        
    def set_movement(self, move_data):
        self.is_moving = move_data.get('moving', False)
        if 'angle' in move_data:
            self.angle = move_data['angle']
            
        self.is_aiming = move_data.get('is_aiming', False)
        if 'aim_angle' in move_data:
            self.aim_angle = move_data['aim_angle']

    def update_position(self):
        if not self.alive:
            return

        self.x += self.kb_dx
        self.y += self.kb_dy
        self.kb_dx *= 0.85 
        self.kb_dy *= 0.85

        speed_modifier = max(0.2, START_SIZE / max(START_SIZE, self.size))
        active_vel = self.vel * speed_modifier

        if self.stun_timer > 0:
            self.stun_timer -= 1
        else:
            if self.is_aiming:
                dx = math.cos(self.aim_angle + math.pi) * (active_vel * 0.5)
                dy = math.sin(self.aim_angle + math.pi) * (active_vel * 0.5)
                self.x += dx
                self.y += dy
            elif self.is_moving:
                dx = math.cos(self.angle) * active_vel
                dy = math.sin(self.angle) * active_vel
                self.x += dx
                self.y += dy

    def to_dict(self):
        return {
            "id": self.id,
            "x": int(self.x),
            "y": int(self.y),
            "size": int(self.size),
            "angle": self.angle,
            "alive": self.alive,
            "ready": self.ready,
            "name": self.name,
            "is_aiming": self.is_aiming,
            "aim_angle": self.aim_angle
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
        self.ring_radius = MAP_SIZE * 1.5
        
        self.particles = []
        for _ in range(MAX_PARTICLES):
            angle = random.uniform(0, math.pi * 2)
            r = math.sqrt(random.uniform(0, 1)) * self.ring_radius
            self.particles.append(Particle(r * math.cos(angle), r * math.sin(angle), 5))
            
        self.game_started = False
        self.lobby_timer_start = None
        self.lobby_duration = 60
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
            spawn_limit = int(self.ring_radius * 0.8)
            rx = random.randint(-spawn_limit, spawn_limit)
            ry = random.randint(-spawn_limit, spawn_limit)
            safe = True
            for p in self.players.values():
                if math.hypot(rx - p.x, ry - p.y) < (START_SIZE * 3):
                    safe = False
                    break
            if safe:
                return rx, ry

    def spawn_burst(self, x, y, total_value, radius):
        num_particles = max(1, int(total_value / 5))
        for _ in range(num_particles):
            angle = random.uniform(0, math.pi * 2)
            r = random.uniform(0, radius)
            px = x + math.cos(angle) * r
            py = y + math.sin(angle) * r
            self.particles.append(Particle(px, py, 5))

    async def broadcast(self, data):
        msg = json.dumps(data)
        for ws in list(self.conns.values()):
            try:
                await ws.send(msg)
            except Exception:
                pass

    async def room_loop(self):
        while self.running:
            remaining_time = self.lobby_duration
            if not self.game_started:
                if len(self.players) > 0:  
                    if self.lobby_timer_start is None:
                        self.lobby_timer_start = time.time()
                    
                    elapsed = time.time() - self.lobby_timer_start
                    remaining_time = max(0, int(self.lobby_duration - elapsed))
                    
                    human_players = [p for p in self.players.values() if not p.is_bot]
                    ready_count = sum(1 for p in human_players if p.ready)
                    
                    timer_up = elapsed >= self.lobby_duration
                    ready_up = len(human_players) >= 1 and ready_count == len(human_players)
                    
                    if timer_up or ready_up:
                        self.game_started = True
                        
                        global _id_counter
                        spots_to_fill = 10 - len(self.players)
                        for _ in range(spots_to_fill):
                            bot_id = _id_counter
                            _id_counter += 1
                            spawn_pos = self.get_safe_spawn()
                            bot_name = self.generate_unique_name(bot_id) + " [BOT]"
                            
                            bot = Player(bot_id, spawn_pos, bot_name)
                            bot.is_bot = True
                            bot.is_moving = True  
                            self.players[bot_id] = bot
                else:
                    self.lobby_timer_start = None

            if self.game_started:
                for p in self.players.values():
                    if p.is_bot and p.alive:
                        closest_p = None
                        min_p_dist = float('inf')
                        
                        for other_p in self.players.values():
                            if other_p.id != p.id and other_p.alive:
                                dist = math.hypot(p.x - other_p.x, p.y - other_p.y)
                                if dist < min_p_dist:
                                    min_p_dist = dist
                                    closest_p = other_p
                        
                        action_taken = False
                        target_angle = p.angle  
                        
                        if closest_p:
                            if p.size >= closest_p.size * 1.25:
                                target_angle = math.atan2(closest_p.y - p.y, closest_p.x - p.x)
                                action_taken = True
                            elif closest_p.size >= p.size * 1.25:
                                target_angle = math.atan2(p.y - closest_p.y, p.x - closest_p.x)
                                action_taken = True

                        if not action_taken and self.particles:
                            closest_part = None
                            min_part_dist = float('inf')
                            for part in self.particles:
                                dist = math.hypot(p.x - part.x, p.y - part.y)
                                if dist < min_part_dist:
                                    min_part_dist = dist
                                    closest_part = part
                            if closest_part:
                                target_angle = math.atan2(closest_part.y - p.y, closest_part.x - p.x)
                        
                        dist_to_center = math.hypot(p.x, p.y)
                        if dist_to_center > self.ring_radius - p.size - 30:
                            target_angle = math.atan2(-p.y, -p.x) 

                        if random.random() < 0.05:  
                            target_angle += random.uniform(-0.5, 0.5)

                        diff = (target_angle - p.angle + math.pi) % (2 * math.pi) - math.pi
                        turn_speed = 0.08  
                        p.angle += max(-turn_speed, min(turn_speed, diff))

                for p in self.players.values():
                    p.update_position()

                self.ring_radius -= RING_SHRINK_RATE
                if self.ring_radius < 0:
                    self.ring_radius = 0

                for proj in self.projectiles[:]:
                    proj.update()
                    if proj.life <= 0:
                        self.projectiles.remove(proj)
                        self.spawn_burst(proj.x, proj.y, proj.size, proj.size / 2)

                for i, p1 in enumerate(self.projectiles):
                    if p1.life <= 0: continue
                    for p2 in self.projectiles[i+1:]:
                        if p2.life <= 0: continue
                        if math.hypot(p1.x - p2.x, p1.y - p2.y) < p1.size + p2.size:
                            if p1.size >= p2.size * 1.25:
                                p1.size -= p2.size * 0.25
                                p2.life = 0
                                self.spawn_burst(p2.x, p2.y, p2.size, p2.size)
                            elif p2.size >= p1.size * 1.25:
                                p2.size -= p1.size * 0.25
                                p1.life = 0
                                self.spawn_burst(p1.x, p1.y, p1.size, p1.size)
                            else:
                                p1.life = 0
                                p2.life = 0
                                self.spawn_burst(p1.x, p1.y, p1.size, p1.size)
                                self.spawn_burst(p2.x, p2.y, p2.size, p2.size)

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
                        if proj.owner_id != pid and proj.life > 0:
                            if math.hypot(p.x - proj.x, p.y - proj.y) < p.size + proj.size:
                                proj.life = 0 
                                if proj.size > p.size:
                                    p.alive = False
                                    self.spawn_burst(p.x, p.y, p.size, p.size)
                                else:
                                    size_ratio = max(0.1, proj.size / p.size)
                                    p.stun_timer = int(proj.size * STUN_MULTIPLIER * size_ratio)
                                    p.kb_dx = math.cos(proj.angle) * (proj.size * 1.5 * size_ratio)
                                    p.kb_dy = math.sin(proj.angle) * (proj.size * 1.5 * size_ratio)

                    for other_id, other_p in self.players.items():
                        if pid != other_id and other_p.alive:
                            if math.hypot(p.x - other_p.x, p.y - other_p.y) < p.size:
                                if p.size >= other_p.size * 1.25:
                                    other_p.alive = False
                                    self.spawn_burst(other_p.x, other_p.y, other_p.size * 0.5, other_p.size)

                for part in self.particles[:]:
                    if math.hypot(part.x, part.y) > self.ring_radius:
                        self.particles.remove(part)

                while len(self.particles) < MAX_PARTICLES:
                    angle = random.uniform(0, math.pi * 2)
                    r = math.sqrt(random.uniform(0, 1)) * max(1, self.ring_radius)
                    self.particles.append(Particle(r * math.cos(angle), r * math.sin(angle), 5))

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

            state = {
                "players": [p.to_dict() for p in self.players.values()],
                "particles": [[int(pt.x), int(pt.y), int(pt.size)] for pt in self.particles],
                "projectiles": [[int(pj.x), int(pj.y), int(pj.size)] for pj in self.projectiles],
                "ring": int(self.ring_radius),
                "started": self.game_started,
                "lobby_time": remaining_time
            }
            await self.broadcast(state)
            await asyncio.sleep(1 / 30)

rooms = {}
_room_counter = 1
_id_counter = 1

def find_or_create_room():
    global _room_counter
    for room in rooms.values():
        if not room.game_started and len(room.players) < 10: 
            return room

    new_room = Room(_room_counter)
    rooms[_room_counter] = new_room
    _room_counter += 1
    
    new_room.task = asyncio.create_task(new_room.room_loop())
    return new_room

async def handle_client(websocket):
    global _id_counter
    p_id = _id_counter
    _id_counter += 1

    room = find_or_create_room()
    spawn_pos = room.get_safe_spawn()
    p_name = room.generate_unique_name(p_id)

    await websocket.send(str(p_id))
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
                        current_time = time.time()
                        if current_time - p.last_shoot_time >= 10:
                            cost = p.size / 8
                            if p.size - cost >= START_SIZE:
                                p.last_shoot_time = current_time 
                                p.size -= cost
                                proj_size = (p.size + cost) / 4 
                                
                                spawn_dist = (p.size + proj_size) + 5
                                px = p.x + math.cos(cmd['angle']) * spawn_dist
                                py = p.y + math.sin(cmd['angle']) * spawn_dist
                                
                                proj = Projectile(p_id, px, py, cmd['angle'], proj_size)
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
    cloud_port = int(os.environ.get("PORT", PORT))
    print(f"WebSocket Server waiting for connections on port {cloud_port}...")
    async with websockets.serve(handle_client, "0.0.0.0", cloud_port):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())