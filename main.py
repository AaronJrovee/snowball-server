# main.py
import pygame
import asyncio
import websockets
import json
import math
from settings import *

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

async def send(data):
    global client
    if client:
        try:
            msg = json.dumps(data)
            await client.send(msg)
        except:
            pass

async def connect_to_server():
    global client, my_id, app_state
    
    try:
        # Connect dynamically based on deployment
        if "onrender.com" in HOST:
            client = await websockets.connect(f"wss://{HOST}")
        else:
            client = await websockets.connect(f"ws://{HOST}:{PORT}")
        
        raw_id = await client.recv()
        my_id = int(raw_id)

        app_state = "GAME"
        # Start the background listener loop asynchronously
        asyncio.create_task(receive_data())
    except Exception as e:
        print(f"Could not connect to server: {e}")
        client = None
        app_state = "MENU"

async def receive_data():
    global gamestate, app_state, winner_announcement, winner_display_start, client
    try:
        async for data in client:
            if app_state not in ["GAME", "WINNER"]:
                break
            
            payload = json.loads(data)
            if payload.get("command") == "game_over":
                winner_name = payload.get("winner_name", "Nobody")
                winner_announcement = f"{winner_name} Wins!"
                winner_display_start = pygame.time.get_ticks()
                app_state = "WINNER"
            else:
                gamestate = payload
    except Exception:
        pass
    finally:
        if client:
            await client.close()
            client = None

def draw_menu():
    screen.fill(BG_COLOR)
    title = font_large.render("Snowball.io", True, BLACK)
    screen.blit(title, (WIDTH // 2 - title.get_width() // 2, HEIGHT // 3))

    btn_rect = pygame.Rect(WIDTH // 2 - 100, HEIGHT // 2, 200, 60)
    pygame.draw.rect(screen, (50, 150, 255), btn_rect, border_radius=10)
    btn_text = font_large.render("PLAY", True, WHITE)
    screen.blit(btn_text, (btn_rect.centerx - btn_text.get_width() // 2, btn_rect.centery - btn_text.get_height() // 2))
    return btn_rect

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
    cam_x, cam_y = 0, 0
    
    if me and me['alive']:
        cam_x = me['x'] - WIDTH // 2
        cam_y = me['y'] - HEIGHT // 2
    elif gamestate.get('started'):
        alive_players = [p for p in gamestate.get('players', []) if p['alive']]
        if alive_players:
            top_player = max(alive_players, key=lambda p: p['size'])
            cam_x = top_player['x'] - WIDTH // 2
            cam_y = top_player['y'] - HEIGHT // 2
            
            spec_txt = font_large.render(f"SPECTATING: {top_player.get('name', 'Unknown')}", True, RED)
            screen.blit(spec_txt, (WIDTH // 2 - spec_txt.get_width() // 2, HEIGHT - 60))

    ring_r = gamestate.get('ring', 2000)
    pygame.draw.circle(screen, ORANGE, (-cam_x, -cam_y), ring_r, 5)

    for p in gamestate.get('particles', []):
        pygame.draw.circle(screen, WHITE, (p[0] - cam_x, p[1] - cam_y), p[2])

    for p in gamestate.get('projectiles', []):
        pygame.draw.circle(screen, (255, 255, 255), (p[0] - cam_x, p[1] - cam_y), p[2])

    for p in gamestate.get('players', []):
        if not p['alive']:
            continue

        px, py = p['x'] - cam_x, p['y'] - cam_y
        color = YELLOWISH_WHITE if p['id'] == my_id else (240, 240, 200)
        pygame.draw.circle(screen, color, (px, py), p['size'])

        angle = p['angle']
        tip_x = px + math.cos(angle) * (p['size'] + 25)
        tip_y = py + math.sin(angle) * (p['size'] + 25)
        base_left_x = px + math.cos(angle - 0.5) * (p['size'] + 15)
        base_left_y = py + math.sin(angle - 0.5) * (p['size'] + 15)
        base_right_x = px + math.cos(angle + 0.5) * (p['size'] + 15)
        base_right_y = py + math.sin(angle + 0.5) * (p['size'] + 15)
        pygame.draw.polygon(screen, BLACK, [(tip_x, tip_y), (base_left_x, base_left_y), (base_right_x, base_right_y)])

        name_text = p.get('name', 'Unknown')
        name_surface = font_small.render(name_text, True, BLACK)
        text_rect = name_surface.get_rect(center=(px, py - p['size'] - 15))
        screen.blit(name_surface, text_rect)

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
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    btn_rect = pygame.Rect(WIDTH // 2 - 100, HEIGHT // 2, 200, 60)
                    if btn_rect.collidepoint(event.pos):
                        # Use create_task for background networking
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

        if app_state == "MENU":
            draw_menu()

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
        
        # --- CRITICAL PYGBAG REQUIREMENT ---
        # Yields control to the web browser so it has time to render
        await asyncio.sleep(0)

    if client:
        await client.close()
    pygame.quit()

if __name__ == "__main__":
    asyncio.run(main())