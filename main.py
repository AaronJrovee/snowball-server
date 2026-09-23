import pygame
import asyncio
import json
import math
import sys
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
client = None
my_id = None
gamestate = {}
winner_announcement = ""
winner_display_start = 0

last_click_time = 0
click_count = 0
CLICK_WINDOW = 250

msg_queue = [] 

def on_message(event):
    # Force the JavaScript payload into a native Python string immediately
    msg_queue.append(str(event.data))

async def send(data):
    global client
    # 1. Safely check the JavaScript proxy
    if client is not None:
        try:
            msg = json.dumps(data)
            if sys.platform == "emscripten":
                # 2. Use the injected pure JS helper to cross the language barrier
                window.send_ws(str(msg))
            else:
                await client.send(msg)
        except Exception as e:
            print(f"Send error: {e}")
            
async def connect_to_server():
    global client, my_id, app_state
    
    url = f"wss://{HOST}" if "onrender.com" in HOST else f"ws://{HOST}:{PORT}"
    
    try:
        if sys.platform == "emscripten":
            client = window.eval(f"new WebSocket('{url}')")
            
            # 1. Store the socket globally so JS doesn't delete it
            window.ws_client = client
            window.ws_on_message = on_message
            client.onmessage = window.ws_on_message
            
            # 2. Inject a pure JavaScript function to handle sending safely
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
            
            my_id = int(msg_queue.pop(0))
        else:
            client = await websockets.connect(url)
            my_id = int(await client.recv())

        app_state = "GAME"
        asyncio.create_task(receive_data())
    except Exception as e:
        print(f"Could not connect: {e}")
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
            gamestate = payload
    except Exception as e:
        print(f"Failed to parse payload: {e}")

async def receive_data():
    global app_state, client
    if sys.platform == "emscripten":
        while app_state in ["GAME", "WINNER"]:
            while len(msg_queue) > 0:
                try:
                    # Process packets safely so one error doesn't kill the background loop
                    process_payload(msg_queue.pop(0))
                except Exception as e:
                    print(f"Queue error: {e}")
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

    btn_rect = pygame.Rect(WIDTH // 2 - 100, HEIGHT // 2, 200, 60)
    pygame.draw.rect(screen, (50, 150, 255), btn_rect, border_radius=10)
    btn_text = font_large.render("PLAY", True, WHITE)
    screen.blit(btn_text, (btn_rect.centerx - btn_text.get_width() // 2, btn_rect.centery - btn_text.get_height() // 2))
    return btn_rect

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

def draw_game():
    screen.fill(BG_COLOR)
    if not gamestate:
        text = font.render("Connecting to lobby...", True, BLACK)
        screen.blit(text, (WIDTH // 2 - text.get_width() // 2, HEIGHT // 2))
        return

    me = next((p for p in gamestate.get('players', []) if p['id'] == my_id), None)
    target_x, target_y = 0, 0
    target_size = START_SIZE
    is_spectating = False
    spectated_name = ""
    
    # 1. Determine who the camera is following
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

    # 2. Calculate dynamic zoom factor (starts zooming out when size > 80)
    ZOOM_THRESHOLD = 80
    zoom = 1.0
    if target_size > ZOOM_THRESHOLD:
        zoom = ZOOM_THRESHOLD / target_size

    # Helper function to convert map coordinates to scaled screen coordinates
    def to_screen(world_x, world_y):
        return (
            int((world_x - target_x) * zoom + WIDTH // 2),
            int((world_y - target_y) * zoom + HEIGHT // 2)
        )

    # 3. Draw game objects using the zoom multiplier
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
        if not p['alive']:
            continue

        sx, sy = to_screen(p['x'], p['y'])
        scaled_size = max(1, int(p['size'] * zoom))
        
        color = YELLOWISH_WHITE if p['id'] == my_id else (240, 240, 200)
        pygame.draw.circle(screen, color, (sx, sy), scaled_size)

        # Scale the directional pointer triangle
        angle = p['angle']
        tip_x = sx + math.cos(angle) * (scaled_size + 25 * zoom)
        tip_y = sy + math.sin(angle) * (scaled_size + 25 * zoom)
        base_left_x = sx + math.cos(angle - 0.5) * (scaled_size + 15 * zoom)
        base_left_y = sy + math.sin(angle - 0.5) * (scaled_size + 15 * zoom)
        base_right_x = sx + math.cos(angle + 0.5) * (scaled_size + 15 * zoom)
        base_right_y = sy + math.sin(angle + 0.5) * (scaled_size + 15 * zoom)
        pygame.draw.polygon(screen, BLACK, [(tip_x, tip_y), (base_left_x, base_left_y), (base_right_x, base_right_y)])

        # Draw names (kept at a constant font size for readability)
        name_text = p.get('name', 'Unknown')
        name_surface = font_small.render(name_text, True, BLACK)
        text_rect = name_surface.get_rect(center=(sx, sy - scaled_size - 15))
        screen.blit(name_surface, text_rect)

    # 4. Draw fixed UI Overlays (Unscaled)
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

        status = "READY" if me and me['ready'] else "NOT READY"
        btn_color = (40, 180, 40) if status == "READY" else (220, 50, 50)
        
        btn_rect = pygame.Rect(WIDTH // 2 - 110, HEIGHT // 2 - 30, 220, 60)
        pygame.draw.rect(screen, btn_color, btn_rect, border_radius=10)
        pygame.draw.rect(screen, WHITE, btn_rect, width=2, border_radius=10)

        label = font.render(f"Status: {status}", True, WHITE)
        screen.blit(label, (btn_rect.centerx - label.get_width() // 2, btn_rect.centery - label.get_height() // 2))

        hint = font_small.render("Click button or press SPACE", True, (200, 200, 200))
        screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT // 2 + 45))

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

async def main():
    global last_click_time, click_count, app_state
    running = True
    last_angle = 0
    last_moving = False
    
    while running:
        clock.tick(FPS)
        mx, my = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if app_state == "MENU":
                # Allow Spacebar OR clicking anywhere to start
                is_click = (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1)
                is_space = (event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE)
                
                if is_click or is_space:
                    app_state = "CONNECTING"
                    asyncio.create_task(connect_to_server())

            
            elif app_state == "GAME":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    asyncio.create_task(send({"command": "ready"}))

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if not gamestate.get('started'):
                        btn_ready_rect = pygame.Rect(WIDTH // 2 - 110, HEIGHT // 2 - 30, 220, 60)
                        if btn_ready_rect.collidepoint(event.pos):
                            asyncio.create_task(send({"command": "ready"}))
                            continue 

                    now = pygame.time.get_ticks()
                    if now - last_click_time < CLICK_WINDOW:
                        click_count += 1
                    else:
                        click_count = 1
                    last_click_time = now

        # Update rendering block to handle the new state
        if app_state == "MENU":
            draw_menu()
        elif app_state == "CONNECTING":
            draw_connecting()
        elif app_state == "GAME":
            now = pygame.time.get_ticks()
            if click_count > 0 and (now - last_click_time >= CLICK_WINDOW):
                if click_count >= 4:
                    asyncio.create_task(send({"command": "shoot", "type": 2}))
                elif click_count >= 2:
                    asyncio.create_task(send({"command": "shoot", "type": 1}))
                click_count = 0

            center_x, center_y = WIDTH // 2, HEIGHT // 2
            angle = math.atan2(my - center_y, mx - center_x)
            moving = pygame.mouse.get_pressed()[0]

            if gamestate.get('started'):
                if moving != last_moving or abs(angle - last_angle) > 0.05:
                    asyncio.create_task(send({"command": "move", "angle": angle, "moving": moving}))
                    last_angle = angle
                    last_moving = moving

            draw_game()

        elif app_state == "WINNER":
            draw_winner()
            if pygame.time.get_ticks() - winner_display_start > 4000:
                app_state = "MENU"

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