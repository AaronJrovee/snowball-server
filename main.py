import pygame
import asyncio
import json
import math
import sys
import time
import random
import importlib
import urllib.request
from settings import *

if sys.platform == "emscripten":
    import platform
    window = platform.window
else:
    ws_name = "web" + "sockets"
    websockets = importlib.import_module(ws_name)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Snowball.io")
clock = pygame.time.Clock()

font_large = pygame.font.SysFont("Arial", 40, bold=True)
font = pygame.font.SysFont("Arial", 20)
font_small = pygame.font.SysFont("Arial", 16, bold=True)

# --- IMAGE ASSET LOADING ---
try:
    snow_sprite = pygame.image.load("snowball.png").convert_alpha()
except Exception:
    try:
        snow_sprite = pygame.image.load("snowball.jpg").convert_alpha()
    except Exception:
        snow_sprite = None

try:
    bg_sprite = pygame.image.load("ice_bg.png").convert()
except Exception:
        bg_sprite = None

# --- SOUND ASSET LOADING ---
pygame.mixer.init()
try:
    menu_music = "menu.ogg"
    lobby_music = "lobby.ogg"
    game_music = "game.ogg"
    
    shoot_sound = pygame.mixer.Sound("shoot.ogg")
    capture_sound = pygame.mixer.Sound("capture.ogg")
    collect_sound = pygame.mixer.Sound("collect.ogg")
except Exception:
    shoot_sound = capture_sound = collect_sound = None
# ---------------------------
# ---------------------------

app_state = "MENU"
server_status = "OK"  
client = None
my_id = None
gamestate = {}
visual_players = {}  # <-- Add this to track smoothed positions
winner_announcement = ""
winner_display_start = 0

msg_queue = [] 
_zombie_proxies = [] # Safeguard to prevent PyProxy GC Wasm crashes

# Menu Animation Variables
menu_snowball = {"x": -100, "y": 50, "angle": 0, "size": 60, "vx": 4, "vy": 1.5}
menu_snowflakes = [[random.randint(0, WIDTH), random.randint(0, HEIGHT), random.uniform(1, 4), random.uniform(1, 3)] for _ in range(100)]


# Joystick & UI Configuration
AIM_JOY_CENTER = (WIDTH - 120, HEIGHT - 120)
MOVE_JOY_CENTER = (120, HEIGHT - 120)
JOY_RADIUS = 70
# Shifted toggle button left to make room for the back button
TOGGLE_BTN_RECT = pygame.Rect(WIDTH - 225, 15, 135, 35)
# Smaller back button placed in the true top-right corner
BACK_BTN_RECT = pygame.Rect(WIDTH - 80, 15, 65, 30)

# Powerups temporarily disabled
# PU_SHIELD_RECT = pygame.Rect(WIDTH - 240, HEIGHT - 320, 50, 50)
# PU_SHOOT_RECT = pygame.Rect(WIDTH - 180, HEIGHT - 320, 50, 50)
# PU_SPEED_RECT = pygame.Rect(WIDTH - 120, HEIGHT - 320, 50, 50)
use_textures = False
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
            "id": 0, "x": 0, "y": 0, "size": START_SIZE, "target_size": START_SIZE, "angle": 0, "alive": True,
            "name": get_name(0), "is_aiming": False, "aim_angle": 0, "kb_dx": 0, "kb_dy": 0, "vx": 0, "vy": 0,
            "last_shoot": 0, "is_moving": False, "is_bot": False, "stun_timer": 0
            # "pu_shield": 1, "pu_shoot": 1, "pu_speed": 1, "shield_time": 0, "shoot_time": 0, "speed_time": 0
        })
        
        # Bots
        for i in range(1, 10):
            a = random.uniform(0, math.pi * 2)
            r = math.sqrt(random.uniform(0, 1)) * (self.ring * 0.8)
            self.players.append({
                "id": i, "x": r * math.cos(a), "y": r * math.sin(a), "size": START_SIZE, "target_size": START_SIZE,
                "angle": 0, "alive": True, "name": get_name(i) + " [BOT]", "is_aiming": False,
                "aim_angle": 0, "kb_dx": 0, "kb_dy": 0, "vx": 0, "vy": 0, "last_shoot": 0, "is_moving": True,
                "is_bot": True, "stun_timer": 0
                # "pu_shield": 0, "pu_shoot": 0, "pu_speed": 0, "shield_time": 0, "shoot_time": 0, "speed_time": 0
            })

    def spawn_burst(self, x, y, total_value, radius):
        num = max(1, int(total_value / 5))
        for _ in range(num):
            a = random.uniform(0, math.pi * 2)
            r = random.uniform(0, radius)
            self.particles.append([x + math.cos(a) * r, y + math.sin(a) * r, 5])

    def update(self, moving, angle, aiming, aim_angle, shoot, use_pu=None):
        # Powerup logic disabled
        # for p in self.players:
        #     if p["shield_time"] > 0: p["shield_time"] -= 1
        #     if p["shoot_time"] > 0: p["shoot_time"] -= 1
        #     if p["speed_time"] > 0: p["speed_time"] -= 1

        me = self.players[0]
        if me["alive"]:
            me["is_moving"] = moving
            me["angle"] = angle
            me["is_aiming"] = aiming
            me["aim_angle"] = aim_angle
            
            # cooldown = 0 if me["shoot_time"] > 0 else 10
            if shoot and me["stun_timer"] <= 0 and time.time() - me["last_shoot"] >= 10 and me["size"] - (me["size"]/8) >= START_SIZE:
                me["last_shoot"] = time.time()
                cost = me["size"] / 8
                me["size"] -= cost
                me["target_size"] -= cost
                psize = (me["size"] + cost) / 4
                dist = me["size"] + psize + 5
                speed = 10 + (psize * 0.2)
                life = int(40 + psize)
                # format: x, y, size, angle, owner_id, life, speed
                self.projectiles.append([
                    me["x"] + math.cos(aim_angle) * dist, 
                    me["y"] + math.sin(aim_angle) * dist, 
                    psize, aim_angle, 0, life, speed
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

            active_vel = 5 # 10 if p["speed_time"] > 0 else 5
            tx = 0
            ty = 0

            if p["stun_timer"] > 0:
                p["stun_timer"] -= 1
            else:
                if p["is_aiming"]:
                    tx = math.cos(p["aim_angle"] + math.pi) * (active_vel * 0.5)
                    ty = math.sin(p["aim_angle"] + math.pi) * (active_vel * 0.5)
                elif p["is_moving"]:
                    tx = math.cos(p["angle"]) * active_vel
                    ty = math.sin(p["angle"]) * active_vel
            
            # Acceleration scales with size: Bigger = takes longer to reach max speed/stop
            accel = max(0.02, START_SIZE / (p["size"] * 2.5))
            
            p["vx"] += (tx - p["vx"]) * accel
            p["vy"] += (ty - p["vy"]) * accel
            
            p["x"] += p["vx"]
            p["y"] += p["vy"]

        self.ring = max(0, self.ring - RING_SHRINK_RATE)

        # Projectile updates
        for proj in self.projectiles[:]:
            proj[0] += math.cos(proj[3]) * proj[6]
            proj[1] += math.sin(proj[3]) * proj[6]
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
                p["size"] -= 0.5  # Reverted from 0.05 back to original faster melt rate
                p["target_size"] = p["size"]
                if p["size"] <= 5: p["alive"] = False

            for part in self.particles[:]:
                if math.hypot(p["x"] - part[0], p["y"] - part[1]) < p["size"] + part[2]:
                    p["target_size"] += part[2] * 0.1
                    self.particles.remove(part)

            for proj in self.projectiles[:]:
                if proj[4] != p["id"] and proj[5] > 0:
                    if math.hypot(p["x"] - proj[0], p["y"] - proj[1]) < p["size"] + proj[2]: # + (15 if p.get("shield_time",0) > 0 else 0):
                        proj[5] = 0
                        # if p.get("shield_time",0) > 0: continue
                        if proj[2] > p["size"]:
                            p["alive"] = False
                            self.spawn_burst(p["x"], p["y"], p["size"], p["size"])
                        else:
                            ratio = proj[2] / p["size"]
                            p["stun_timer"] = min(120, int(ratio * 215)) # 1 sec average
                            p["kb_dx"] = math.cos(proj[3]) * (proj[2] * 6 * max(0.1, ratio))
                            p["kb_dy"] = math.sin(proj[3]) * (proj[2] * 6 * max(0.1, ratio))

            for other_p in self.players:
                if p["id"] != other_p["id"] and other_p["alive"]:
                    dist = math.hypot(p["x"] - other_p["x"], p["y"] - other_p["y"])
                    # min_dist = p["size"] + (15 if p.get("shield_time",0) > 0 else 0) + (15 if other_p.get("shield_time",0) > 0 else 0)
                    # if dist < min_dist and (p.get("shield_time",0) > 0 or other_p.get("shield_time",0) > 0):
                    #     ang = math.atan2(p["y"] - other_p["y"], p["x"] - other_p["x"])
                    #     p["kb_dx"] += math.cos(ang) * 2
                    #     p["kb_dy"] += math.sin(ang) * 2
                    #     continue

                    if dist < p["size"]:
                        if p["size"] >= other_p["size"] * 1.25: # and other_p.get("shield_time",0) <= 0:
                            other_p["alive"] = False
                            p["target_size"] += other_p["size"] * 0.5
                            self.spawn_burst(other_p["x"], other_p["y"], other_p["size"] * 0.5, other_p["size"])

        # Particle ring-cull & respawn
        for part in self.particles[:]:
            if math.hypot(part[0], part[1]) > self.ring:
                self.particles.remove(part)

        while len(self.particles) < MAX_PARTICLES:
            a = random.uniform(0, math.pi * 2)
            r = math.sqrt(random.uniform(0, 1)) * max(1, self.ring)
            self.particles.append([r * math.cos(a), r * math.sin(a), 5])

        # Smooth scaling
        for p in self.players:
            if p["alive"]:
                if p["size"] < p["target_size"]:
                    p["size"] += (p["target_size"] - p["size"]) * 0.1
                elif p["size"] > p["target_size"]:
                    p["size"] = p["target_size"]

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
    
    # --- CLIENT-SIDE BANDWIDTH CHECK ---
    try:
        max_bytes = 4 * 1024 * 1024 * 1024
        is_capped = False
        
        if sys.platform == "emscripten":
            window.eval("""
            window.bw_bytes = -1;
            fetch('https://snowball-server-d1dce-default-rtdb.firebaseio.com/bandwidth.json')
              .then(r => r.json())
              .then(d => { window.bw_bytes = d ? (d.bytes || 0) : 0; })
              .catch(e => { window.bw_bytes = 0; });
            """)
            timeout = 0
            while int(window.eval("window.bw_bytes")) == -1 and timeout < 3:
                await asyncio.sleep(0.1)
                timeout += 0.1
            
            bw = int(window.eval("window.bw_bytes"))
            if bw >= max_bytes:
                is_capped = True
        else:
            loop = asyncio.get_running_loop()
            def fetch_bw():
                try:
                    req = urllib.request.Request("https://snowball-server-d1dce-default-rtdb.firebaseio.com/bandwidth.json")
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        return data.get("bytes", 0) if isinstance(data, dict) else 0
                except:
                    return 0
            bw = await loop.run_in_executor(None, fetch_bw)
            if bw >= max_bytes:
                is_capped = True
                
        if is_capped:
            server_status = "CAPPED"
            app_state = "MENU"
            return
    except Exception as e:
        print(f"Pre-check failed, defaulting to server check: {e}")
    # -----------------------------------

    url = f"wss://{HOST}" if "onrender.com" in HOST else f"ws://{HOST}:{PORT}"
    
    try:
        if sys.platform == "emscripten":
            msg_queue.clear()
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
        if sys.platform == "emscripten" and client is not None:
            _zombie_proxies.append(client) # Prevent timeout crashes
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
            if len(msg_queue) > 0:
                # Grab the absolute latest state and discard any backed-up stale frames
                # This prevents the browser tab from freezing in a WebSocket death spiral!
                latest_msg = msg_queue[-1]
                msg_queue.clear()
                try:
                    process_payload(latest_msg)
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
    # 1. Sky background
    screen.fill((135, 206, 235)) 

    # 2. Update and draw menu snowflakes
    for flake in menu_snowflakes:
        flake[1] += flake[3]  # Move down
        flake[0] += math.sin(flake[1] * 0.05) * 0.5  # Sway
        if flake[1] > HEIGHT:
            flake[1] = random.randint(-50, -10)
            flake[0] = random.randint(0, WIDTH)
        pygame.draw.circle(screen, WHITE, (int(flake[0]), int(flake[1])), int(flake[2]))

    # 3. Draw a snow-covered hill
    hill_start_y = HEIGHT // 3
    hill_end_y = HEIGHT
    pygame.draw.polygon(screen, (240, 250, 255), [(0, hill_start_y), (WIDTH, hill_end_y), (0, HEIGHT)])

    # 4. Update and draw rolling snowball locked to the hill slope
    menu_snowball["x"] += menu_snowball["vx"]
    menu_snowball["angle"] += 0.05
    menu_snowball["size"] += 0.05  # Grows as it rolls down
    
    # Calculate exact Y on the hill slope
    slope = (hill_end_y - hill_start_y) / WIDTH
    # The 0.8 modifier sinks it slightly into the snow so it doesn't float
    menu_snowball["y"] = hill_start_y + (menu_snowball["x"] * slope) - (menu_snowball["size"] * 0.8) 

    if menu_snowball["x"] > WIDTH + 100:
        menu_snowball["x"] = -100
        menu_snowball["size"] = 20 # Start small at the top of the hill

    sb_x, sb_y = int(menu_snowball["x"]), int(menu_snowball["y"])
    sb_size = int(menu_snowball["size"])
    
    if snow_sprite:
        sb_img = pygame.transform.scale(snow_sprite, (sb_size * 2, sb_size * 2))
        sb_img = pygame.transform.rotate(sb_img, math.degrees(-menu_snowball["angle"]))
        screen.blit(sb_img, sb_img.get_rect(center=(sb_x, sb_y)))
    else:
        pygame.draw.circle(screen, WHITE, (sb_x, sb_y), sb_size)

    # 5. Translucent Layer (separates UI from bg)
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 100))
    screen.blit(overlay, (0, 0))

    # 6. Wintery white bubble letters (Title) with a more subtle pulse
    title_pulse = math.sin(pygame.time.get_ticks() * 0.0015) 
    title_size = int(75 + (2 * title_pulse)) # Reduced multiplier for subtlety
    title_font = pygame.font.SysFont("Arial", title_size, bold=True)
    title_text = "SNOWBALL.IO"
    
    # Draw thick light blue outline
    outline_color = (150, 200, 255)
    t_x, t_y = WIDTH // 2 - title_font.size(title_text)[0] // 2, HEIGHT // 4
    for dx, dy in [(-4,-4), (4,-4), (-4,4), (4,4), (-5,0), (5,0), (0,-5), (0,5)]:
        screen.blit(title_font.render(title_text, True, outline_color), (t_x + dx, t_y + dy))
    
    # Draw core text
    screen.blit(title_font.render(title_text, True, WHITE), (t_x, t_y))

    play_btn = None
    offline_btn = None
    btn_y_offset = HEIGHT // 2 + 30

    # Calculate perfectly proportional pulse scaling using a unified multiplier
    btn_scale = 1.0 + (0.04 * math.sin(pygame.time.get_ticks() * 0.002))
    p_width = int(280 * btn_scale)
    p_height = int(60 * btn_scale)
    
    # Dynamically scale the font perfectly in sync with the button dimensions
    active_btn_font = pygame.font.SysFont("Arial", int(40 * btn_scale), bold=True)

    # 7. Rounded UI Buttons
    if server_status == "OK":
        play_btn = pygame.Rect(0, 0, p_width, p_height)
        play_btn.center = (WIDTH // 2, btn_y_offset)
        pygame.draw.rect(screen, (50, 150, 255), play_btn, border_radius=30)
        pygame.draw.rect(screen, WHITE, play_btn, width=3, border_radius=30)
        p_text = active_btn_font.render("PLAY ONLINE", True, WHITE)
        screen.blit(p_text, (play_btn.centerx - p_text.get_width() // 2, play_btn.centery - p_text.get_height() // 2))
        
        offline_btn = pygame.Rect(0, 0, 280, 60)
        offline_btn.center = (WIDTH // 2, btn_y_offset + 80)
        o_text = font.render("OFFLINE MODE", True, WHITE) # standard font
    else:
        # If offline is the main choice, make it pulse instead
        offline_btn = pygame.Rect(0, 0, p_width, p_height) 
        offline_btn.center = (WIDTH // 2, btn_y_offset)
        msg = "Server Unreachable" if server_status == "UNREACHABLE" else "Monthly Bandwidth Capped"
        err_text = font_small.render(msg, True, (255, 100, 100))
        screen.blit(err_text, (WIDTH // 2 - err_text.get_width() // 2, btn_y_offset - 45))
        o_text = active_btn_font.render("OFFLINE MODE", True, WHITE) # pulsing font

    pygame.draw.rect(screen, (120, 130, 140), offline_btn, border_radius=30)
    pygame.draw.rect(screen, WHITE, offline_btn, width=3, border_radius=30)
    screen.blit(o_text, (offline_btn.centerx - o_text.get_width() // 2, offline_btn.centery - o_text.get_height() // 2))

    return play_btn, offline_btn

def draw_connecting():
    screen.fill(BG_COLOR)
    text = font_large.render("Waking up server...", True, BLACK)
    sub = font.render("(This can take up to 50 seconds)", True, (100, 100, 100))
    screen.blit(text, (WIDTH // 2 - text.get_width() // 2, HEIGHT // 2 - 20))
    screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, HEIGHT // 2 + 30))

def draw_winner():
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 150))
    screen.blit(overlay, (0, 0))
    
    w_text = font_large.render(winner_announcement, True, WHITE)
    sub_text = font.render("Returning to menu shortly...", True, (200, 200, 200))
    screen.blit(w_text, (WIDTH // 2 - w_text.get_width() // 2, HEIGHT // 2 - 40))
    screen.blit(sub_text, (WIDTH // 2 - sub_text.get_width() // 2, HEIGHT // 2 + 20))

def draw_game(move_active, move_angle, move_pos, aim_active, aim_angle, aim_pos, can_shoot):
    global use_textures, visual_players

    if not gamestate:
        screen.fill(BG_COLOR)
        text = font.render("Loading...", True, BLACK)
        screen.blit(text, (WIDTH // 2 - text.get_width() // 2, HEIGHT // 2))
        return

    # --- LERP (SMOOTHING) LOGIC ---
    current_server_players = {p['id']: p for p in gamestate.get('players', []) if p['alive']}
    
    # Remove disconnected or dead players from visual state
    
    keys_to_remove = [pid for pid in visual_players if pid not in current_server_players]
    for pid in keys_to_remove:
        if capture_sound:
            capture_sound.play()
        del visual_players[pid]

    # Glide visual positions toward server positions
    lerp_factor = 0.3  # 0.3 means moving 30% of the remaining distance per frame
    for pid, sp in current_server_players.items():
        if pid not in visual_players:
            # Snap immediately if we just saw them
            visual_players[pid] = {'x': sp['x'], 'y': sp['y'], 'angle': sp['angle'], 'size': sp['size'], 'aim_angle': sp.get('aim_angle', 0)}
        else:
            vp = visual_players[pid]
            vp['x'] += (sp['x'] - vp['x']) * lerp_factor
            vp['y'] += (sp['y'] - vp['y']) * lerp_factor
            
            # Smooth angle rotation (accounts for mathematical wraparound)
            diff = (sp['angle'] - vp['angle'] + math.pi) % (2 * math.pi) - math.pi
            vp['angle'] += diff * lerp_factor
            
            # Smooth aim angle rotation
            diff_aim = (sp.get('aim_angle', 0) - vp.get('aim_angle', 0) + math.pi) % (2 * math.pi) - math.pi
            vp['aim_angle'] += diff_aim * lerp_factor
            
            vp['size'] = sp['size']
    # ------------------------------

    # Determine camera target using SMOOTHED coordinates
    me = next((p for p in gamestate.get('players', []) if p['id'] == my_id), None)
    target_x, target_y = 0, 0
    target_size = START_SIZE
    is_spectating = False
    spectated_name = ""
    
    if me and me['alive'] and my_id in visual_players:
        target_x = visual_players[my_id]['x']
        target_y = visual_players[my_id]['y']
        target_size = visual_players[my_id]['size']
    elif gamestate.get('started'):
        alive_players = [p for p in gamestate.get('players', []) if p['alive']]
        if alive_players:
            top_player = max(alive_players, key=lambda p: p['size'])
            if top_player['id'] in visual_players:
                vp_top = visual_players[top_player['id']]
                target_x = vp_top['x']
                target_y = vp_top['y']
                target_size = vp_top['size']
            is_spectating = True
            spectated_name = top_player.get('name', 'Unknown')

    ZOOM_THRESHOLD = 80
    zoom = 1.0
    if target_size > ZOOM_THRESHOLD:
        zoom = ZOOM_THRESHOLD / target_size

    # --- MOVING BACKGROUND LOGIC CONSOLIDATED ---
    if bg_sprite and use_textures:
        scaled_bg_w = max(1, int(bg_sprite.get_width() * zoom))
        scaled_bg_h = max(1, int(bg_sprite.get_height() * zoom))
        scaled_bg = pygame.transform.scale(bg_sprite, (scaled_bg_w, scaled_bg_h))
        
        offset_x = -int(target_x * zoom) % scaled_bg_w
        offset_y = -int(target_y * zoom) % scaled_bg_h
        
        for x in range(offset_x - scaled_bg_w, WIDTH, scaled_bg_w):
            for y in range(offset_y - scaled_bg_h, HEIGHT, scaled_bg_h):
                screen.blit(scaled_bg, (x, y))
                
        filter_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        filter_surf.fill((BG_COLOR[0], BG_COLOR[1], BG_COLOR[2], 120))
        screen.blit(filter_surf, (0, 0))
    else:
        screen.fill(BG_COLOR)

    def to_screen(world_x, world_y):
        return (
            int((world_x - target_x) * zoom + WIDTH // 2),
            int((world_y - target_y) * zoom + HEIGHT // 2)
        )

    ring_r = gamestate.get('ring', 2000)
    center_screen = to_screen(0, 0)
    pygame.draw.circle(screen, ORANGE, center_screen, max(1, int(ring_r * zoom)), max(1, int(5 * zoom)))

    # Render Snow Particles 
    valid_particles = []
    for p in gamestate.get('particles', []):
        eaten = False
        for player in gamestate.get('players', []):
            if player['alive'] and math.hypot(player['x'] - p[0], player['y'] - p[1]) < player['size'] + p[2]:
                eaten = True
                # In offline mode my_id is None, but the human is always id 0
                if (player['id'] == my_id or (app_state == "OFFLINE_GAME" and player['id'] == 0)) and collect_sound:
                    collect_sound.play()
                break
        if not eaten:
            valid_particles.append(p)
            sx, sy = to_screen(p[0], p[1])
            scaled_p_size = max(1, int(p[2] * zoom))
            if snow_sprite and use_textures:
                p_img = pygame.transform.scale(snow_sprite, (scaled_p_size * 2, scaled_p_size * 2))
                screen.blit(p_img, p_img.get_rect(center=(sx, sy)))
            else:
                pygame.draw.circle(screen, WHITE, (sx, sy), scaled_p_size)
    
    gamestate['particles'] = valid_particles

    # Render Projectiles
    for p in gamestate.get('projectiles', []):
        sx, sy = to_screen(p[0], p[1])
        scaled_p_size = max(1, int(p[2] * zoom))
        if snow_sprite and use_textures:
            p_img = pygame.transform.scale(snow_sprite, (scaled_p_size * 2, scaled_p_size * 2))
            screen.blit(p_img, p_img.get_rect(center=(sx, sy)))
        else:
            pygame.draw.circle(screen, (255, 255, 255), (sx, sy), scaled_p_size)

    # Render Players (Using smoothed visual data)
    for p in gamestate.get('players', []):
        if not p['alive'] or p['id'] not in visual_players: continue

        vp = visual_players[p['id']]
        sx, sy = to_screen(vp['x'], vp['y'])
        scaled_size = max(1, int(vp['size'] * zoom))
        
        if snow_sprite and use_textures:
            current_img = pygame.transform.scale(snow_sprite, (scaled_size * 2, scaled_size * 2))
            img_rect = current_img.get_rect(center=(sx, sy))
            screen.blit(current_img, img_rect)
        else:
            color = YELLOWISH_WHITE if p['id'] == my_id else (240, 240, 200)
            pygame.draw.circle(screen, color, (sx, sy), scaled_size)

        # Powerups Disabled
        # if p.get('shoot_time', 0) > 0 or p.get('speed_time', 0) > 0:
        #     glow_radius = scaled_size + int(15 * zoom)
        #     glow_surf = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
        #     if p.get('shoot_time', 0) > 0:
        #         pygame.draw.circle(glow_surf, (255, 0, 0, 80), (glow_radius, glow_radius), glow_radius)
        #     if p.get('speed_time', 0) > 0:
        #         pygame.draw.circle(glow_surf, (150, 0, 255, 80), (glow_radius, glow_radius), glow_radius)
        #     screen.blit(glow_surf, (sx - glow_radius, sy - glow_radius))
        # 
        # if p.get('shield_time', 0) > 0:
        #     shield_radius = scaled_size + int(15 * zoom)
        #     pygame.draw.circle(screen, (50, 255, 50), (sx, sy), shield_radius, max(3, int(4 * zoom)))
        #     pygame.draw.circle(screen, (150, 255, 150), (sx, sy), shield_radius - 2, max(1, int(2 * zoom)))

        if p.get('stun_timer', 0) > 0:
            bar_w = 40
            pygame.draw.rect(screen, RED, (sx - bar_w//2, sy - scaled_size - 25, bar_w, 6))
            pygame.draw.rect(screen, (255, 200, 0), (sx - bar_w//2, sy - scaled_size - 25, bar_w * (p['stun_timer']/120), 6))

        if p.get('is_aiming') and p['id'] == my_id:
            aim_angle = vp.get('aim_angle', p.get('aim_angle', 0))
            ray_length = 2000
            end_x = int(sx + math.cos(aim_angle) * ray_length)
            end_y = int(sy + math.sin(aim_angle) * ray_length)
            
            shared_ray_surf.fill((0, 0, 0, 0))
            p_size = vp['size']
            proj_size = (p_size + (p_size / 8)) / 4
            ray_width = max(2, int((proj_size * 2) * zoom))
            
            pygame.draw.line(shared_ray_surf, (255, 255, 255, 80), (sx, sy), (end_x, end_y), ray_width)
            screen.blit(shared_ray_surf, (0, 0))
        else:
            angle = vp['angle']
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

        human_players = [p for p in gamestate.get('players', []) if not p.get('is_bot', False)]
        
        title_surf = font_small.render(f"LOBBY ({len(human_players)}/10):", True, WHITE)
        screen.blit(title_surf, (15, 15))
        for i, p in enumerate(human_players):
            name_surf = font_small.render(f"- {p.get('name', 'Unknown')}", True, WHITE)
            screen.blit(name_surf, (15, 40 + i * 25))

        if len(human_players) >= 2:
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
        else:
            waiting = font_large.render("Waiting for 2+ players...", True, WHITE)
            screen.blit(waiting, (WIDTH // 2 - waiting.get_width() // 2, HEIGHT // 2 - 30))

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

    # Draw Toggle Button
    pygame.draw.rect(screen, (70, 70, 70), TOGGLE_BTN_RECT, border_radius=5)
    pygame.draw.rect(screen, (200, 200, 200), TOGGLE_BTN_RECT, width=2, border_radius=5)
    btn_text = "Textures: ON" if use_textures else "Textures: OFF"
    t_surf = font_small.render(btn_text, True, WHITE)
    screen.blit(t_surf, (TOGGLE_BTN_RECT.centerx - t_surf.get_width() // 2, TOGGLE_BTN_RECT.centery - t_surf.get_height() // 2))

    if app_state == "OFFLINE_GAME" or (app_state == "GAME" and not gamestate.get('started')):
        pygame.draw.rect(screen, (200, 50, 50), BACK_BTN_RECT, border_radius=5)
        b_text = font_small.render("BACK", True, WHITE)
        screen.blit(b_text, (BACK_BTN_RECT.centerx - b_text.get_width() // 2, BACK_BTN_RECT.centery - b_text.get_height() // 2))

    # Powerup UI Buttons Disabled
    # if me and me['alive'] and gamestate.get('started') and me['size'] >= 50:
    #     if me.get('pu_shield'):
    #         pygame.draw.circle(screen, (50, 200, 50), PU_SHIELD_RECT.center, 25)
    #         pygame.draw.circle(screen, WHITE, PU_SHIELD_RECT.center, 25, 2)
    #         cx, cy = PU_SHIELD_RECT.center
    #         pts = [(cx - 10, cy - 10), (cx + 10, cy - 10), (cx + 10, cy + 5), (cx, cy + 15), (cx - 10, cy + 5)]
    #         pygame.draw.polygon(screen, WHITE, pts)
    #         
    #     if me.get('pu_shoot'):
    #         pygame.draw.circle(screen, (200, 50, 50), PU_SHOOT_RECT.center, 25)
    #         pygame.draw.circle(screen, WHITE, PU_SHOOT_RECT.center, 25, 2)
    #         cx, cy = PU_SHOOT_RECT.center
    #         pygame.draw.circle(screen, WHITE, (cx, cy), 12, 2)
    #         pygame.draw.line(screen, WHITE, (cx - 16, cy), (cx + 16, cy), 2)
    #         pygame.draw.line(screen, WHITE, (cx, cy - 16), (cx, cy + 16), 2)
    #         
    #     if me.get('pu_speed'):
    #         pygame.draw.circle(screen, (150, 50, 200), PU_SPEED_RECT.center, 25)
    #         pygame.draw.circle(screen, WHITE, PU_SPEED_RECT.center, 25, 2)
    #         cx, cy = PU_SPEED_RECT.center
    #         pts = [(cx + 5, cy - 12), (cx - 8, cy + 2), (cx + 2, cy + 2), (cx - 5, cy + 12), (cx + 8, cy - 2), (cx - 2, cy - 2)]
    #         pygame.draw.polygon(screen, WHITE, pts)

    if me and me['alive'] and gamestate.get('started'):
        KNOB_RADIUS = 25
        surf_width = (JOY_RADIUS + KNOB_RADIUS) * 2
        surf_center = surf_width // 2

        # Draw Left Joystick (Movement) - No Crosshairs
        move_surf = pygame.Surface((surf_width, surf_width), pygame.SRCALPHA)
        pygame.draw.circle(move_surf, (0, 0, 0, 80), (surf_center, surf_center), JOY_RADIUS)
        
        if move_active:
            dist = math.hypot(move_pos[0] - MOVE_JOY_CENTER[0], move_pos[1] - MOVE_JOY_CENTER[1])
            dist = min(dist, JOY_RADIUS) # Clamps knob inside the circle
            kx = surf_center + math.cos(move_angle) * dist
            ky = surf_center + math.sin(move_angle) * dist
        else:
            kx, ky = surf_center, surf_center
            
        pygame.draw.circle(move_surf, (255, 255, 255, 150), (int(kx), int(ky)), KNOB_RADIUS)
        screen.blit(move_surf, (MOVE_JOY_CENTER[0] - surf_center, MOVE_JOY_CENTER[1] - surf_center))

        # Draw Right Joystick (Aim/Shoot) - Original White w/ Crosshairs
        if can_shoot:
            aim_surf = pygame.Surface((surf_width, surf_width), pygame.SRCALPHA)
            pygame.draw.circle(aim_surf, (0, 0, 0, 80), (surf_center, surf_center), JOY_RADIUS)
            
            if aim_active:
                dist = math.hypot(aim_pos[0] - AIM_JOY_CENTER[0], aim_pos[1] - AIM_JOY_CENTER[1])
                dist = min(dist, JOY_RADIUS) # Clamps knob inside the circle
                akx = surf_center + math.cos(aim_angle) * dist
                aky = surf_center + math.sin(aim_angle) * dist
            else:
                akx, aky = surf_center, surf_center
                
            pygame.draw.circle(aim_surf, (255, 255, 255, 150), (int(akx), int(aky)), KNOB_RADIUS)
            pygame.draw.line(aim_surf, (0, 0, 0, 150), (int(akx) - 10, int(aky)), (int(akx) + 10, int(aky)), 3)
            pygame.draw.line(aim_surf, (0, 0, 0, 150), (int(akx), int(aky) - 10), (int(akx), int(aky) + 10), 3)
            screen.blit(aim_surf, (AIM_JOY_CENTER[0] - surf_center, AIM_JOY_CENTER[1] - surf_center))

# ==============================================================================
# MAIN LOOP
# ==============================================================================
async def main():
    global app_state, gamestate, my_id, offline_engine, winner_announcement, winner_display_start, use_textures, client
    running = True
    last_angle = 0
    last_moving = False
    
    joystick_active = False
    space_aim_active = False  
    last_aim_angle = 0
    last_is_aiming = False
    last_shoot_time = 0
    pending_shoot_command = False
    
    current_music_state = None
    last_projectile_count = 0
    
    active_touches = {}
    mouse_active = False
    mouse_start = (0, 0)
    
    while running:
        clock.tick(FPS)
        
        # --- MUSIC STATE MACHINE ---
        if app_state == "MENU":
            target_music = "MENU"
        elif app_state in ["GAME", "OFFLINE_GAME"] and not gamestate.get('started'):
            target_music = "LOBBY"
        elif app_state in ["GAME", "OFFLINE_GAME"] and gamestate.get('started'):
            target_music = "GAME"
        else:
            target_music = current_music_state
            
        if current_music_state != target_music:
            current_music_state = target_music
            try:
                if target_music == "MENU":
                    pygame.mixer.music.load(menu_music)
                elif target_music == "LOBBY":
                    pygame.mixer.music.load(lobby_music)
                elif target_music == "GAME":
                    pygame.mixer.music.load(game_music)
                pygame.mixer.music.play(-1)
            except Exception:
                pass
        # ---------------------------

        # --- SHOOT SOUND TRACKER ---
        current_projs = len(gamestate.get('projectiles', []))
        if current_projs > last_projectile_count and shoot_sound:
            shoot_sound.play()
        last_projectile_count = current_projs
        # ---------------------------

        now = pygame.time.get_ticks()

        can_shoot = False
        me = next((p for p in gamestate.get('players', []) if p['id'] == my_id), None)
        if me and me['alive'] and gamestate.get('started'):
            if (me['size'] - (me['size'] / 8)) >= START_SIZE:
                if (now - last_shoot_time) >= 10000:
                    can_shoot = True

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                
            # Track Multi-Touch events (Start vs Current Position)
            if event.type == pygame.FINGERDOWN:
                pos = (event.x * WIDTH, event.y * HEIGHT)
                active_touches[event.finger_id] = {"start": pos, "current": pos}
            elif event.type == pygame.FINGERMOTION:
                if event.finger_id in active_touches:
                    active_touches[event.finger_id]["current"] = (event.x * WIDTH, event.y * HEIGHT)
            elif event.type == pygame.FINGERUP:
                active_touches.pop(event.finger_id, None)

            # Unified UI Clicks (Works for both PC Mouse and Mobile Touch)
            ui_click_pos = None
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                ui_click_pos = event.pos
                mouse_active = True
                mouse_start = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mouse_active = False
            elif event.type == pygame.FINGERDOWN:
                ui_click_pos = (event.x * WIDTH, event.y * HEIGHT)

            if ui_click_pos:
                if app_state == "MENU":
                    play_rect, offline_rect = draw_menu()
                    if play_rect and play_rect.collidepoint(ui_click_pos):
                        app_state = "CONNECTING"
                        asyncio.create_task(connect_to_server())
                    elif offline_rect and offline_rect.collidepoint(ui_click_pos):
                        app_state = "OFFLINE_GAME"
                        offline_engine = OfflineEngine()
                        my_id = 0

                elif app_state in ["GAME", "OFFLINE_GAME"]:
                    if TOGGLE_BTN_RECT.collidepoint(ui_click_pos):
                        use_textures = not use_textures
                    
                    elif (app_state == "OFFLINE_GAME" or not gamestate.get('started')) and BACK_BTN_RECT.collidepoint(ui_click_pos):
                        app_state = "MENU"
                        gamestate = {}
                        visual_players.clear()
                        msg_queue.clear()
                        if client:
                            try:
                                if sys.platform == "emscripten":
                                    window.eval("if(window.ws_client) { window.ws_client.close(); }")
                                    _zombie_proxies.append(client) # Keep Python proxy alive so Wasm doesn't crash on JS async close
                                else:
                                    asyncio.create_task(client.close())
                            except: pass
                            client = None
                    
                    elif not gamestate.get('started') and app_state == "GAME":
                        human_players = [p for p in gamestate.get('players', []) if not p.get('is_bot', False)]
                        if len(human_players) >= 2:
                            btn_ready = pygame.Rect(WIDTH // 2 - 110, HEIGHT // 2 - 30, 220, 60)
                            if btn_ready.collidepoint(ui_click_pos):
                                asyncio.create_task(send({"command": "ready"}))
                                
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                if not gamestate.get('started') and app_state == "GAME":
                    human_players = [p for p in gamestate.get('players', []) if not p.get('is_bot', False)]
                    if len(human_players) >= 2:
                        asyncio.create_task(send({"command": "ready"}))

        # Evaluate Active Touch/Mouse Inputs for Dual Joysticks
        current_inputs = list(active_touches.values())
        if mouse_active:
            current_inputs.append({"start": mouse_start, "current": pygame.mouse.get_pos()})
            
        move_active = False
        aim_active = False
        move_angle = last_angle
        aim_angle = last_aim_angle
        move_pos = (0, 0)
        aim_pos = (0, 0)
        pending_pu_command = None

        if gamestate.get('started') and me and me['alive']:
            for touch in current_inputs:
                sx, sy = touch["start"]
                cx, cy = touch["current"]

                # 1. Check Powerups (Disabled for now)
                # if me and me['size'] >= 50:
                #     if me.get('pu_shield') and PU_SHIELD_RECT.collidepoint(sx, sy):
                #         if app_state == "GAME": asyncio.create_task(send({"command": "use_pu", "pu": "shield"}))
                #         pending_pu_command = "shield"
                #         me['pu_shield'] = 0
                #         continue
                #     if me.get('pu_shoot') and PU_SHOOT_RECT.collidepoint(sx, sy):
                #         if app_state == "GAME": asyncio.create_task(send({"command": "use_pu", "pu": "shoot"}))
                #         pending_pu_command = "shoot"
                #         me['pu_shoot'] = 0
                #         continue
                #     if me.get('pu_speed') and PU_SPEED_RECT.collidepoint(sx, sy):
                #         if app_state == "GAME": asyncio.create_task(send({"command": "use_pu", "pu": "speed"}))
                #         pending_pu_command = "speed"
                #         me['pu_speed'] = 0
                #         continue

                # 2. Left Joystick (Must originate near the joystick center)
                if math.hypot(sx - MOVE_JOY_CENTER[0], sy - MOVE_JOY_CENTER[1]) <= JOY_RADIUS * 2.5:
                    move_active = True
                    move_pos = (cx, cy)
                    move_angle = math.atan2(cy - MOVE_JOY_CENTER[1], cx - MOVE_JOY_CENTER[0])
                
                # 3. Right Joystick (Must originate near the joystick center)
                elif can_shoot and math.hypot(sx - AIM_JOY_CENTER[0], sy - AIM_JOY_CENTER[1]) <= JOY_RADIUS * 2.5:
                    aim_active = True
                    aim_pos = (cx, cy)
                    aim_angle = math.atan2(cy - AIM_JOY_CENTER[1], cx - AIM_JOY_CENTER[0])

            # --- PC KEYBOARD & MOUSE OVERRIDES ---
            keys = pygame.key.get_pressed()
            kb_dx, kb_dy = 0, 0
            # Supports both WASD and Arrow Keys simultaneously!
            if keys[pygame.K_w] or keys[pygame.K_UP]: kb_dy -= 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]: kb_dy += 1
            if keys[pygame.K_a] or keys[pygame.K_LEFT]: kb_dx -= 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]: kb_dx += 1
            
            if kb_dx != 0 or kb_dy != 0:
                move_active = True
                move_angle = math.atan2(kb_dy, kb_dx)
                
            # If the right virtual joystick is NOT currently being dragged, use PC mouse aiming
            is_using_right_joystick = aim_active
            if not is_using_right_joystick and pygame.mouse.get_focused():
                mx, my = pygame.mouse.get_pos()
                
                # Allow Left-Click to shoot IF they didn't click on the left movement joystick or UI
                left_click_shoot = False
                if mouse_active:
                    dist_to_move_joy = math.hypot(mouse_start[0] - MOVE_JOY_CENTER[0], mouse_start[1] - MOVE_JOY_CENTER[1])
                    
                    # Ensure the click didn't start on any UI buttons
                    clicked_ui = BACK_BTN_RECT.collidepoint(mouse_start) or TOGGLE_BTN_RECT.collidepoint(mouse_start)
                    
                    if dist_to_move_joy > JOY_RADIUS * 2.5 and not clicked_ui:
                        left_click_shoot = True

                # Press Spacebar, Right-Click, or Left-Click to charge shot
                if can_shoot and (keys[pygame.K_SPACE] or pygame.mouse.get_pressed()[2] or left_click_shoot):
                    aim_active = True
                    aim_angle = math.atan2(my - HEIGHT // 2, mx - WIDTH // 2)
                else:
                    # Visually track the mouse cursor when just walking around
                    aim_angle = math.atan2(my - HEIGHT // 2, mx - WIDTH // 2)

        if app_state == "MENU":
            draw_menu()
            
        elif app_state == "CONNECTING":
            draw_connecting()
            
        elif app_state == "WINNER":
            draw_game(False, 0, (0, 0), False, 0, (0, 0), False)
            draw_winner()
            if now - winner_display_start > 3000:
                app_state = "MENU"
                gamestate = {}
                
        elif app_state == "OFFLINE_GAME" or app_state == "GAME":
            # Detect aim release to trigger shot
            if last_is_aiming and not aim_active:
                if app_state == "GAME":
                    asyncio.create_task(send({"command": "shoot", "angle": last_aim_angle}))
                    asyncio.create_task(send({"command": "move", "is_aiming": False, "moving": move_active, "angle": move_angle}))
                else:
                    pending_shoot_command = True
                last_shoot_time = now
            
            # Send Network Updates only if state changes
            if app_state == "GAME":
                state_changed = False
                if move_active != last_moving or (move_active and abs(move_angle - last_angle) > 0.01):
                    state_changed = True
                if aim_active != last_is_aiming or (aim_active and abs(aim_angle - last_aim_angle) > 0.01):
                    state_changed = True
                    
                if state_changed:
                    asyncio.create_task(send({
                        "command": "move", 
                        "angle": move_angle, 
                        "moving": move_active, 
                        "is_aiming": aim_active,
                        "aim_angle": aim_angle
                    }))

            last_angle = move_angle
            last_moving = move_active
            last_aim_angle = aim_angle
            last_is_aiming = aim_active

            if app_state == "OFFLINE_GAME":
                gamestate = offline_engine.update(move_active, move_angle, aim_active, aim_angle, pending_shoot_command, pending_pu_command)
                pending_shoot_command = False
                pending_pu_command = None
                
                alive_players = [p for p in gamestate['players'] if p['alive']]
                if len(alive_players) <= 1:
                    winner_name = alive_players[0]['name'] if alive_players else "Nobody"
                    winner_announcement = f"{winner_name} Wins!"
                    winner_display_start = pygame.time.get_ticks()
                    app_state = "WINNER"

            draw_game(move_active, move_angle, move_pos, aim_active, aim_angle, aim_pos, can_shoot)

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