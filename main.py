import pygame
import asyncio
import json
import math
import sys
import time
import random
import importlib
from settings import *

if sys.platform == "emscripten":
    import platform
    window = platform.window
else:
    ws_name = "web" + "sockets"
    websockets = importlib.import_module(ws_name)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Snowball.io Clone")
clock = pygame.time.Clock()

font_large = pygame.font.SysFont("Arial", 40, bold=True)
font = pygame.font.SysFont("Arial", 20)
font_small = pygame.font.SysFont("Arial", 16, bold=True)

app_state = "MENU"
server_status = "OK"  
client = None
my_id = None
gamestate = {}
winner_announcement = ""
winner_display_start = 0

msg_queue = [] 

# Joystick Configuration
JOY_CENTER = (WIDTH - 120, HEIGHT - 120)
JOY_RADIUS = 70

shared_ray_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
offline_engine = None

# ==============================================================================
# OFFLINE ENGINE (1:1 Exact Server Mirror)
# ==============================================================================
PREFIXES = ["Cool", "Frozen", "Ice", "Snow", "Brawl", "Rolling", "Winter", "Cold", "Awesome", "Amazing", "Throwing", "Super", "New"]
SUFFIXES = ["Master", "Expert", "Addict", "Sphere", "Gamer", "Gobbler", "Dude"]

class OfflineEngine:
    def __init__(self):
        self.ring = MAP_SIZE * 1.5
        self.particles = []
        for _ in range(MAX_PARTICLES):
            a = random.uniform(0, math.pi * 2)
            r = math.sqrt(random.uniform(0, 1)) * self.ring
            self.particles.append([r * math.cos(a), r * math.sin(a), 5])
            
        self.projectiles = []
        self.players = []
        
        existing_names = set()
        def get_name(p_id):
            for _ in range(100):
                n = f"{random.choice(PREFIXES)}{random.choice(SUFFIXES)}"
                if n not in existing_names:
                    existing_names.add(n)
                    return n
            return f"Player{p_id}"

        # Human Player
        self.players.append({
            "id": 0, "x": 0, "y": 0, "size": START_SIZE, "angle": 0, "alive": True,
            "name": get_name(0), "is_aiming": False, "aim_angle": 0, "kb_dx": 0, "kb_dy": 0,
            "last_shoot": 0, "is_moving": False, "is_bot": False, "stun_timer": 0
        })
        
        # Bots
        for i in range(1, 10):
            a = random.uniform(0, math.pi * 2)
            r = math.sqrt(random.uniform(0, 1)) * (self.ring * 0.8)
            self.players.append({
                "id": i, "x": r * math.cos(a), "y": r * math.sin(a), "size": START_SIZE,
                "angle": 0, "alive": True, "name": get_name(i) + " [BOT]", "is_aiming": False,
                "aim_angle": 0, "kb_dx": 0, "kb_dy": 0, "last_shoot": 0, "is_moving": True,
                "is_bot": True, "stun_timer": 0
            })

    def spawn_burst(self, x, y, total_value, radius):
        num = max(1, int(total_value / 5))
        for _ in range(num):
            a = random.uniform(0, math.pi * 2)
            r = random.uniform(0, radius)
            self.particles.append([x + math.cos(a) * r, y + math.sin(a) * r, 5])

    def update(self, moving, angle, aiming, aim_angle, shoot):
        me = self.players[0]
        if me["alive"]:
            me["is_moving"] = moving
            me["angle"] = angle
            me["is_aiming"] = aiming
            me["aim_angle"] = aim_angle
            
            if shoot and time.time() - me["last_shoot"] >= 10 and me["size"] - (me["size"]/8) >= START_SIZE:
                me["last_shoot"] = time.time()
                cost = me["size"] / 8
                me["size"] -= cost
                psize = (me["size"] + cost) / 4
                dist = me["size"] + psize + 5
                # format: x, y, size, angle, owner_id, life
                self.projectiles.append([
                    me["x"] + math.cos(aim_angle) * dist, 
                    me["y"] + math.sin(aim_angle) * dist, 
                    psize, aim_angle, 0, 60
                ])

        # Exact server Bot AI
        for p in self.players:
            if p["is_bot"] and p["alive"]:
                closest_p = None
                min_p_dist = float('inf')
                for other_p in self.players:
                    if other_p["id"] != p["id"] and other_p["alive"]:
                        dist = math.hypot(p["x"] - other_p["x"], p["y"] - other_p["y"])
                        if dist < min_p_dist:
                            min_p_dist = dist
                            closest_p = other_p
                
                action_taken = False
                target_angle = p["angle"]
                if closest_p:
                    if p["size"] >= closest_p["size"] * 1.25:
                        target_angle = math.atan2(closest_p["y"] - p["y"], closest_p["x"] - p["x"])
                        action_taken = True
                    elif closest_p["size"] >= p["size"] * 1.25:
                        target_angle = math.atan2(p["y"] - closest_p["y"], p["x"] - closest_p["x"])
                        action_taken = True

                if not action_taken and self.particles:
                    closest_part = None
                    min_part_dist = float('inf')
                    for part in self.particles:
                        dist = math.hypot(p["x"] - part[0], p["y"] - part[1])
                        if dist < min_part_dist:
                            min_part_dist = dist
                            closest_part = part
                    if closest_part:
                        target_angle = math.atan2(closest_part[1] - p["y"], closest_part[0] - p["x"])
                
                dist_to_center = math.hypot(p["x"], p["y"])
                if dist_to_center > self.ring - p["size"] - 30:
                    target_angle = math.atan2(-p["y"], -p["x"]) 

                if random.random() < 0.05:  
                    target_angle += random.uniform(-0.5, 0.5)

                diff = (target_angle - p["angle"] + math.pi) % (2 * math.pi) - math.pi
                p["angle"] += max(-0.08, min(0.08, diff))

        # Position updates
        for p in self.players:
            if not p["alive"]: continue
            
            p["x"] += p["kb_dx"]
            p["y"] += p["kb_dy"]
            p["kb_dx"] *= 0.85
            p["kb_dy"] *= 0.85

            speed_modifier = max(0.2, START_SIZE / max(START_SIZE, p["size"]))
            active_vel = 5 * speed_modifier

            if p["stun_timer"] > 0:
                p["stun_timer"] -= 1
            else:
                if p["is_aiming"]:
                    p["x"] += math.cos(p["aim_angle"] + math.pi) * (active_vel * 0.5)
                    p["y"] += math.sin(p["aim_angle"] + math.pi) * (active_vel * 0.5)
                elif p["is_moving"]:
                    p["x"] += math.cos(p["angle"]) * active_vel
                    p["y"] += math.sin(p["angle"]) * active_vel

        self.ring = max(0, self.ring - RING_SHRINK_RATE)

        # Projectile updates
        for proj in self.projectiles[:]:
            proj[0] += math.cos(proj[3]) * 10
            proj[1] += math.sin(proj[3]) * 10
            proj[5] -= 1
            if proj[5] <= 0:
                self.projectiles.remove(proj)
                self.spawn_burst(proj[0], proj[1], proj[2], proj[2] / 2)
                continue

        # Projectile-Projectile Collisions
        for i, p1 in enumerate(self.projectiles):
            if p1[5] <= 0: continue
            for p2 in self.projectiles[i+1:]:
                if p2[5] <= 0: continue
                if math.hypot(p1[0] - p2[0], p1[1] - p2[1]) < p1[2] + p2[2]:
                    if p1[2] >= p2[2] * 1.25:
                        p1[2] -= p2[2] * 0.25
                        p2[5] = 0
                        self.spawn_burst(p2[0], p2[1], p2[2], p2[2])
                    elif p2[2] >= p1[2] * 1.25:
                        p2[2] -= p1[2] * 0.25
                        p1[5] = 0
                        self.spawn_burst(p1[0], p1[1], p1[2], p1[2])
                    else:
                        p1[5] = 0
                        p2[5] = 0
                        self.spawn_burst(p1[0], p1[1], p1[2], p1[2])
                        self.spawn_burst(p2[0], p2[1], p2[2], p2[2])

        # Player Collisions (Eating, Projectiles, Ring, Particles)
        for p in self.players:
            if not p["alive"]: continue

            if math.hypot(p["x"], p["y"]) > self.ring:
                p["size"] -= 0.5
                if p["size"] <= 5: p["alive"] = False

            for part in self.particles[:]:
                if math.hypot(p["x"] - part[0], p["y"] - part[1]) < p["size"] + part[2]:
                    p["size"] += part[2] * 0.1
                    self.particles.remove(part)

            for proj in self.projectiles[:]:
                if proj[4] != p["id"] and proj[5] > 0:
                    if math.hypot(p["x"] - proj[0], p["y"] - proj[1]) < p["size"] + proj[2]:
                        proj[5] = 0
                        if proj[2] > p["size"]:
                            p["alive"] = False
                            self.spawn_burst(p["x"], p["y"], p["size"], p["size"])
                        else:
                            ratio = max(0.1, proj[2] / p["size"])
                            p["stun_timer"] = int(proj[2] * STUN_MULTIPLIER * ratio)
                            p["kb_dx"] = math.cos(proj[3]) * (proj[2] * 1.5 * ratio)
                            p["kb_dy"] = math.sin(proj[3]) * (proj[2] * 1.5 * ratio)

            for other_p in self.players:
                if p["id"] != other_p["id"] and other_p["alive"]:
                    if math.hypot(p["x"] - other_p["x"], p["y"] - other_p["y"]) < p["size"]:
                        if p["size"] >= other_p["size"] * 1.25:
                            other_p["alive"] = False
                            self.spawn_burst(other_p["x"], other_p["y"], other_p["size"] * 0.5, other_p["size"])

        # Particle ring-cull & respawn
        for part in self.particles[:]:
            if math.hypot(part[0], part[1]) > self.ring:
                self.particles.remove(part)

        while len(self.particles) < MAX_PARTICLES:
            a = random.uniform(0, math.pi * 2)
            r = math.sqrt(random.uniform(0, 1)) * max(1, self.ring)
            self.particles.append([r * math.cos(a), r * math.sin(a), 5])

        return {
            "players": self.players,
            "projectiles": [[int(pr[0]), int(pr[1]), int(pr[2])] for pr in self.projectiles],
            "particles": [[int(pt[0]), int(pt[1]), int(pt[2])] for pt in self.particles],
            "ring": int(self.ring),
            "started": True,
            "lobby_time": 0
        }

# ==============================================================================
# NETWORK & DRAWING
# ==============================================================================
def on_message(event):
    msg_queue.append(str(event.data))

async def send(data):
    global client, app_state, server_status
    if client is not None:
        try:
            msg = json.dumps(data)
            if sys.platform == "emscripten":
                window.send_ws(str(msg))
            else:
                await client.send(msg)
        except Exception:
            client = None
            server_status = "UNREACHABLE"
            app_state = "MENU"
            
async def connect_to_server():
    global client, my_id, app_state, server_status
    
    url = f"wss://{HOST}" if "onrender.com" in HOST else f"ws://{HOST}:{PORT}"
    
    try:
        if sys.platform == "emscripten":
            client = window.eval(f"new WebSocket('{url}')")
            window.ws_client = client
            window.ws_on_message = on_message
            client.onmessage = window.ws_on_message
            
            window.eval("""
            window.send_ws = function(msg) {
                if (window.ws_client && window.ws_client.readyState === 1) {
                    window.ws_client.send(msg);
                }
            }
            """)
            
            while client.readyState == 0:
                await asyncio.sleep(0.1)
                
            if client.readyState != 1:
                raise Exception("Server is offline or unreachable.")
                
            timeout = 0
            while len(msg_queue) == 0:
                if client.readyState != 1:
                    raise Exception("Connection closed unexpectedly.")
                await asyncio.sleep(0.1)
                timeout += 0.1
                if timeout > 10: 
                    raise Exception("Timed out waiting for server response.")
            
            first_msg = str(msg_queue.pop(0))
            if first_msg == "CAP_REACHED":
                server_status = "CAPPED"
                app_state = "MENU"
                return
            my_id = int(first_msg)
        else:
            client = await websockets.connect(url)
            first_msg = await client.recv()
            if first_msg == "CAP_REACHED":
                server_status = "CAPPED"
                app_state = "MENU"
                if client:
                    await client.close()
                return
            my_id = int(first_msg)

        server_status = "OK"
        app_state = "GAME"
        asyncio.create_task(receive_data())
    except Exception as e:
        print(f"Could not connect: {e}")
        server_status = "UNREACHABLE"
        client = None
        app_state = "MENU"

def process_payload(data):
    global gamestate, app_state, winner_announcement, winner_display_start
    try:
        payload = json.loads(data)
        if payload.get("command") == "game_over":
            winner_name = payload.get("winner_name", "Nobody")
            winner_announcement = f"{winner_name} Wins!"
            winner_display_start = pygame.time.get_ticks()
            app_state = "WINNER"
        else:
            if "particles" in payload:
                gamestate["particles"] = payload["particles"]
                
            gamestate["players"] = payload.get("players", [])
            gamestate["projectiles"] = payload.get("projectiles", [])
            gamestate["ring"] = payload.get("ring", 2000)
            gamestate["started"] = payload.get("started", False)
            gamestate["lobby_time"] = payload.get("lobby_time", 60)
    except Exception as e:
        print(f"Failed to parse payload: {e}")

async def receive_data():
    global app_state, client
    if sys.platform == "emscripten":
        while app_state in ["GAME", "WINNER"]:
            while len(msg_queue) > 0:
                try:
                    process_payload(msg_queue.pop(0))
                except Exception:
                    pass
            await asyncio.sleep(0.01)
    else:
        try:
            async for data in client:
                if app_state not in ["GAME", "WINNER"]:
                    break
                process_payload(data)
        except Exception:
            pass

def draw_menu():
    screen.fill(BG_COLOR)
    title = font_large.render("Snowball.io", True, BLACK)
    screen.blit(title, (WIDTH // 2 - title.get_width() // 2, HEIGHT // 3))

    play_btn = None
    offline_btn = None

    if server_status == "OK":
        # Widened to 280 to prevent PLAY ONLINE text overflow
        play_btn = pygame.Rect(WIDTH // 2 - 140, HEIGHT // 2, 280, 60)
        pygame.draw.rect(screen, (50, 150, 255), play_btn, border_radius=10)
        p_text = font_large.render("PLAY ONLINE", True, WHITE)
        screen.blit(p_text, (play_btn.centerx - p_text.get_width() // 2, play_btn.centery - p_text.get_height() // 2))
        
        offline_btn = pygame.Rect(WIDTH // 2 - 140, HEIGHT // 2 + 80, 280, 60)
    else:
        offline_btn = pygame.Rect(WIDTH // 2 - 140, HEIGHT // 2, 280, 60)
        msg = "Server Unreachable" if server_status == "UNREACHABLE" else "Monthly Bandwidth Capped"
        err_text = font_small.render(msg, True, RED)
        screen.blit(err_text, (WIDTH // 2 - err_text.get_width() // 2, HEIGHT // 2 - 35))

    pygame.draw.rect(screen, (100, 100, 100), offline_btn, border_radius=10)
    o_text = font.render("OFFLINE MODE", True, WHITE)
    screen.blit(o_text, (offline_btn.centerx - o_text.get_width() // 2, offline_btn.centery - o_text.get_height() // 2))

    return play_btn, offline_btn

def draw_connecting():
    screen.fill(BG_COLOR)
    text = font_large.render("Waking up server...", True, BLACK)
    sub = font.render("(This can take up to 50 seconds)", True, (100, 100, 100))
    screen.blit(text, (WIDTH // 2 - text.get_width() // 2, HEIGHT // 2 - 20))
    screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, HEIGHT // 2 + 30))

def draw_winner():
    screen.fill(BG_COLOR)
    w_text = font_large.render(winner_announcement, True, BLACK)
    sub_text = font.render("Returning to menu shortly...", True, (80, 80, 80))
    screen.blit(w_text, (WIDTH // 2 - w_text.get_width() // 2, HEIGHT // 2 - 40))
    screen.blit(sub_text, (WIDTH // 2 - sub_text.get_width() // 2, HEIGHT // 2 + 20))

def draw_game(joystick_active, mx, my, can_shoot, space_held):
    screen.fill(BG_COLOR)
    if not gamestate:
        text = font.render("Loading...", True, BLACK)
        screen.blit(text, (WIDTH // 2 - text.get_width() // 2, HEIGHT // 2))
        return

    me = next((p for p in gamestate.get('players', []) if p['id'] == my_id), None)
    target_x, target_y = 0, 0
    target_size = START_SIZE
    is_spectating = False
    spectated_name = ""
    
    if me and me['alive']:
        target_x = me['x']
        target_y = me['y']
        target_size = me['size']
    elif gamestate.get('started'):
        alive_players = [p for p in gamestate.get('players', []) if p['alive']]
        if alive_players:
            top_player = max(alive_players, key=lambda p: p['size'])
            target_x = top_player['x']
            target_y = top_player['y']
            target_size = top_player['size']
            is_spectating = True
            spectated_name = top_player.get('name', 'Unknown')

    ZOOM_THRESHOLD = 80
    zoom = 1.0
    if target_size > ZOOM_THRESHOLD:
        zoom = ZOOM_THRESHOLD / target_size

    def to_screen(world_x, world_y):
        return (
            int((world_x - target_x) * zoom + WIDTH // 2),
            int((world_y - target_y) * zoom + HEIGHT // 2)
        )

    ring_r = gamestate.get('ring', 2000)
    center_screen = to_screen(0, 0)
    pygame.draw.circle(screen, ORANGE, center_screen, max(1, int(ring_r * zoom)), max(1, int(5 * zoom)))

    for p in gamestate.get('particles', []):
        sx, sy = to_screen(p[0], p[1])
        pygame.draw.circle(screen, WHITE, (sx, sy), max(1, int(p[2] * zoom)))

    for p in gamestate.get('projectiles', []):
        sx, sy = to_screen(p[0], p[1])
        pygame.draw.circle(screen, (255, 255, 255), (sx, sy), max(1, int(p[2] * zoom)))

    for p in gamestate.get('players', []):
        if not p['alive']: continue

        sx, sy = to_screen(p['x'], p['y'])
        scaled_size = max(1, int(p['size'] * zoom))
        
        color = YELLOWISH_WHITE if p['id'] == my_id else (240, 240, 200)
        pygame.draw.circle(screen, color, (sx, sy), scaled_size)

        if p.get('is_aiming'):
            aim_angle = p.get('aim_angle', 0)
            ray_length = 2000
            end_x = int(sx + math.cos(aim_angle) * ray_length)
            end_y = int(sy + math.sin(aim_angle) * ray_length)
            
            shared_ray_surf.fill((0, 0, 0, 0))
            pygame.draw.line(shared_ray_surf, (255, 255, 255, 80), (sx, sy), (end_x, end_y), max(2, int(8 * zoom)))
            screen.blit(shared_ray_surf, (0, 0))
        else:
            angle = p['angle']
            tip_x = sx + math.cos(angle) * (scaled_size + 25 * zoom)
            tip_y = sy + math.sin(angle) * (scaled_size + 25 * zoom)
            base_left_x = sx + math.cos(angle - 0.5) * (scaled_size + 15 * zoom)
            base_left_y = sy + math.sin(angle - 0.5) * (scaled_size + 15 * zoom)
            base_right_x = sx + math.cos(angle + 0.5) * (scaled_size + 15 * zoom)
            base_right_y = sy + math.sin(angle + 0.5) * (scaled_size + 15 * zoom)
            pygame.draw.polygon(screen, BLACK, [(tip_x, tip_y), (base_left_x, base_left_y), (base_right_x, base_right_y)])

        name_text = p.get('name', 'Unknown')
        name_surface = font_small.render(name_text, True, BLACK)
        text_rect = name_surface.get_rect(center=(sx, sy - scaled_size - 15))
        screen.blit(name_surface, text_rect)

    if is_spectating:
        spec_txt = font_large.render(f"SPECTATING: {spectated_name}", True, RED)
        screen.blit(spec_txt, (WIDTH // 2 - spec_txt.get_width() // 2, HEIGHT - 60))

    if not gamestate.get('started'):
        s = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        s.fill((0, 0, 0, 150))
        screen.blit(s, (0, 0))

        lobby_time = gamestate.get('lobby_time', 60)
        timer_text = font_large.render(f"Starts in: {lobby_time}s", True, WHITE)
        screen.blit(timer_text, (WIDTH // 2 - timer_text.get_width() // 2, HEIGHT // 2 - 100))

        status = "READY" if me and me.get('ready') else "NOT READY"
        btn_color = (40, 180, 40) if status == "READY" else (220, 50, 50)
        
        btn_rect = pygame.Rect(WIDTH // 2 - 110, HEIGHT // 2 - 30, 220, 60)
        pygame.draw.rect(screen, btn_color, btn_rect, border_radius=10)
        pygame.draw.rect(screen, WHITE, btn_rect, width=2, border_radius=10)

        label = font.render(f"Status: {status}", True, WHITE)
        screen.blit(label, (btn_rect.centerx - label.get_width() // 2, btn_rect.centery - label.get_height() // 2))

    if gamestate.get('started'):
        sorted_players = sorted(gamestate.get('players', []), key=lambda x: x['size'], reverse=True)
        y_offset = 15
        current_rank = 1
        previous_size = None
        
        lb_title = font_small.render("LEADERBOARD", True, BLACK)
        screen.blit(lb_title, (15, y_offset))
        y_offset += 25
        
        for i, p in enumerate(sorted_players):
            if previous_size is not None and p['size'] < previous_size:
                current_rank = i + 1
            previous_size = p['size']
            
            text_color = RED if p['id'] == my_id else BLACK
            status_marker = "" if p['alive'] else " (DEAD)"
            entry_text = f"{current_rank}. {p.get('name', 'Unknown')} - {int(p['size'])}{status_marker}"
            
            txt_surface = font_small.render(entry_text, True, text_color)
            bg_rect = pygame.Rect(10, y_offset - 2, txt_surface.get_width() + 10, txt_surface.get_height() + 4)
            s = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
            s.fill((255, 255, 255, 180))
            screen.blit(s, (bg_rect.x, bg_rect.y))
            
            screen.blit(txt_surface, (15, y_offset))
            y_offset += 22

    if me and me['alive'] and gamestate.get('started') and can_shoot and not space_held:
        KNOB_RADIUS = 25
        surf_width = (JOY_RADIUS + KNOB_RADIUS) * 2
        j_surf = pygame.Surface((surf_width, surf_width), pygame.SRCALPHA)
        surf_center = surf_width // 2
        
        pygame.draw.circle(j_surf, (0, 0, 0, 80), (surf_center, surf_center), JOY_RADIUS)
        
        if joystick_active:
            dist = math.hypot(mx - JOY_CENTER[0], my - JOY_CENTER[1])
            angle = math.atan2(my - JOY_CENTER[1], mx - JOY_CENTER[0])
            dist = min(dist, JOY_RADIUS)
            knob_x = surf_center + math.cos(angle) * dist
            knob_y = surf_center + math.sin(angle) * dist
        else:
            knob_x, knob_y = surf_center, surf_center
            
        kx, ky = int(knob_x), int(knob_y)
        pygame.draw.circle(j_surf, (255, 255, 255, 150), (kx, ky), KNOB_RADIUS)
        pygame.draw.line(j_surf, (0, 0, 0, 150), (kx - 10, ky), (kx + 10, ky), 3)
        pygame.draw.line(j_surf, (0, 0, 0, 150), (kx, ky - 10), (kx, ky + 10), 3)
        
        screen.blit(j_surf, (JOY_CENTER[0] - surf_center, JOY_CENTER[1] - surf_center))

# ==============================================================================
# MAIN LOOP
# ==============================================================================
async def main():
    global app_state, gamestate, my_id, offline_engine, winner_announcement, winner_display_start
    running = True
    last_angle = 0
    last_moving = False
    
    joystick_active = False
    space_aim_active = False  
    last_aim_angle = 0
    last_is_aiming = False
    last_shoot_time = 0
    pending_shoot_command = False
    
    while running:
        clock.tick(FPS)
        mx, my = pygame.mouse.get_pos()
        now = pygame.time.get_ticks()
        keys = pygame.key.get_pressed()
        space_held = keys[pygame.K_SPACE]

        can_shoot = False
        me = next((p for p in gamestate.get('players', []) if p['id'] == my_id), None)
        if me and me['alive'] and gamestate.get('started'):
            if (me['size'] - (me['size'] / 8)) >= START_SIZE:
                can_shoot = True

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if app_state == "MENU":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    play_rect, offline_rect = draw_menu()
                    if play_rect and play_rect.collidepoint(event.pos):
                        app_state = "CONNECTING"
                        asyncio.create_task(connect_to_server())
                    elif offline_rect and offline_rect.collidepoint(event.pos):
                        app_state = "OFFLINE_GAME"
                        offline_engine = OfflineEngine()
                        my_id = 0

            elif app_state in ["GAME", "OFFLINE_GAME"]:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    if not gamestate.get('started') and app_state == "GAME":
                        asyncio.create_task(send({"command": "ready"}))
                    elif can_shoot and pygame.mouse.get_pressed()[0]:
                        space_aim_active = True

                if event.type == pygame.KEYUP and event.key == pygame.K_SPACE:
                    if space_aim_active:
                        space_aim_active = False
                        aim_angle = math.atan2(my - HEIGHT // 2, mx - WIDTH // 2)
                        if app_state == "GAME":
                            asyncio.create_task(send({"command": "shoot", "angle": aim_angle}))
                            asyncio.create_task(send({"command": "move", "is_aiming": False, "moving": False}))
                        else:
                            pending_shoot_command = True
                        last_is_aiming = False

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if not gamestate.get('started') and app_state == "GAME":
                        btn_ready = pygame.Rect(WIDTH // 2 - 110, HEIGHT // 2 - 30, 220, 60)
                        if btn_ready.collidepoint(event.pos):
                            asyncio.create_task(send({"command": "ready"}))
                            continue 
                            
                    if gamestate.get('started') and can_shoot:
                        if space_held:
                            space_aim_active = True
                        elif math.hypot(event.pos[0] - JOY_CENTER[0], event.pos[1] - JOY_CENTER[1]) <= JOY_RADIUS:
                            joystick_active = True
                
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if joystick_active or space_aim_active:
                        if joystick_active:
                            aim_angle = math.atan2(my - JOY_CENTER[1], mx - JOY_CENTER[0])
                        else:
                            aim_angle = math.atan2(my - HEIGHT // 2, mx - WIDTH // 2)
                            
                        joystick_active = False
                        space_aim_active = False
                        
                        if app_state == "GAME":
                            asyncio.create_task(send({"command": "shoot", "angle": aim_angle}))
                            asyncio.create_task(send({"command": "move", "is_aiming": False, "moving": False}))
                        else:
                            pending_shoot_command = True
                        last_is_aiming = False

        if app_state == "MENU":
            draw_menu()
            
        elif app_state == "CONNECTING":
            draw_connecting()
            
        elif app_state == "WINNER":
            draw_winner()
            if now - winner_display_start > 3000:
                app_state = "MENU"
                gamestate = {}
                
        elif app_state == "OFFLINE_GAME" or app_state == "GAME":
            is_aiming_now = False
            moving = False
            aim_angle = last_aim_angle
            angle = last_angle
            
            if gamestate.get('started'):
                if (joystick_active or space_aim_active) and can_shoot:
                    is_aiming_now = True
                    moving = False
                    if joystick_active:
                        aim_angle = math.atan2(my - JOY_CENTER[1], mx - JOY_CENTER[0])
                    else:
                        aim_angle = math.atan2(my - HEIGHT // 2, mx - WIDTH // 2)
                        
                    if app_state == "GAME" and (abs(aim_angle - last_aim_angle) > 0.05 or not last_is_aiming):
                        asyncio.create_task(send({"command": "move", "is_aiming": True, "aim_angle": aim_angle, "moving": False}))
                        
                    last_aim_angle = aim_angle
                    last_is_aiming = True
                else:
                    if joystick_active or space_aim_active: 
                        joystick_active = False
                        space_aim_active = False
                        
                    center_x, center_y = WIDTH // 2, HEIGHT // 2
                    angle = math.atan2(my - center_y, mx - center_x)
                    moving = pygame.mouse.get_pressed()[0]
                    
                    if app_state == "GAME" and (moving != last_moving or abs(angle - last_angle) > 0.05 or last_is_aiming):
                        asyncio.create_task(send({"command": "move", "angle": angle, "moving": moving, "is_aiming": False}))
                        
                    last_angle = angle
                    last_moving = moving
                    last_is_aiming = False

            if app_state == "OFFLINE_GAME":
                gamestate = offline_engine.update(moving, angle, is_aiming_now, aim_angle, pending_shoot_command)
                pending_shoot_command = False
                
                alive_players = [p for p in gamestate['players'] if p['alive']]
                if len(alive_players) <= 1:
                    winner_name = alive_players[0]['name'] if alive_players else "Nobody"
                    winner_announcement = f"{winner_name} Wins!"
                    winner_display_start = pygame.time.get_ticks()
                    app_state = "WINNER"

            draw_game(joystick_active, mx, my, can_shoot, space_held)

        pygame.display.flip()
        await asyncio.sleep(0)

    if client:
        try:
            await client.close()
        except:
            pass
    pygame.quit()

if __name__ == "__main__":
    asyncio.run(main())