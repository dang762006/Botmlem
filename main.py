import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import io
import aiohttp
import asyncio
import random
import threading
import traceback
from flask import Flask
from colorthief import ColorThief

# --- Khởi tạo Flask app ---
app = Flask(__name__)

@app.route("/ping/<token>")
def ping_token(token):
    if token != os.getenv("DISCORD_BOT_TOKEN"):
        return "forbidden", 403
    return "OK", 200

@app.route("/ping-r/<int:rnum>")
def ping_random(rnum):
    return f"pong {rnum}", 200

@app.route('/')
def home():
    return "Bot is alive and healthy!"

@app.route('/healthz')
def health_check():
    return "OK", 200

def run_flask():
    """Chạy Flask app trong 1 thread riêng"""
    port = int(os.environ.get("PORT", 10000))
    print(f"Flask server running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

# --- Cấu hình Bot Discord ---
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.members = True
intents.voice_states = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents, reconnect=True)

# --- Khởi tạo biến toàn cục cho tài nguyên
# SỬA LỖI: Load tài nguyên một lần duy nhất
IMAGE_GEN_SEMAPHORE = None
FONT_WELCOME = None
FONT_NAME = None
FONT_SYMBOL = None
WELCOME_BG_IMG = None
avatar_cache = {}
CACHE_TTL = 900

# --- CÁC HẰNG SỐ DÙNG TRONG TẠO ẢNH ---
FONT_MAIN_PATH = "1FTV-Designer.otf"
FONT_SYMBOL_PATH = "subset-DejaVuSans.ttf"
WELCOME_FONT_SIZE = 60
NAME_FONT_SIZE = 34
AVATAR_SIZE = 210
BACKGROUND_IMAGE_PATH = "welcome.png"
DEFAULT_IMAGE_DIMENSIONS = (872, 430)
LINE_THICKNESS = 3
LINE_VERTICAL_OFFSET_FROM_NAME = 13
LINE_LENGTH_FACTOR = 0.70

# --- Các hàm xử lý màu sắc và tạo ảnh ---
def rgb_to_hsl(r, g, b):
    r /= 255.0
    g /= 255.0
    b /= 255.0
    cmax, cmin = max(r, g, b), min(r, g, b)
    delta = cmax - cmin
    h, s, l = 0, 0, (cmax + cmin) / 2
    if delta != 0:
        s = delta / (cmax + cmin) if l < 0.5 else delta / (2 - cmax - cmin)
        if cmax == r: h = ((g - b) / delta) % 6
        elif cmax == g: h = (b - r) / delta + 2
        else: h = (r - g) / delta + 4
        h /= 6
    return h, s, l

def hsl_to_rgb(h, s, l):
    def hsl_to_rgb_component(p, q, t):
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1 / 6: return p + (q - p) * 6 * t
        if t < 1 / 2: return q
        if t < 2 / 3: return p + (q - p) * (2 / 3 - t) * 6
        return p
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r_new = hsl_to_rgb_component(p, q, h + 1 / 3)
    g_new = hsl_to_rgb_component(p, q, h)
    b_new = hsl_to_rgb_component(p, q, h - 1 / 3)
    return (int(r_new * 255), int(g_new * 255), int(b_new * 255))

def adjust_color_brightness_saturation(rgb_color, brightness_factor=1.0, saturation_factor=1.0, clamp_min_l=0.0, clamp_max_l=1.0):
    h, s, l = rgb_to_hsl(*rgb_color)
    l = min(clamp_max_l, max(clamp_min_l, l * brightness_factor))
    s = min(1.0, max(0.0, s * saturation_factor))
    return hsl_to_rgb(h, s, l)

async def get_dominant_color(image_bytes, color_count=20):
    """SỬA LỖI: Dùng asyncio.to_thread để không block event loop."""
    try:
        def blocking_extract_palette(img_bytes, color_count):
            f = io.BytesIO(img_bytes)
            color_thief = ColorThief(f)
            return color_thief.get_palette(color_count=color_count, quality=1)
        palette = await asyncio.to_thread(blocking_extract_palette, image_bytes, color_count)
        qualified_colors = []
        def get_hue_priority_index(h_value):
            if 0.75 <= h_value < 0.95: return 0
            if 0.40 <= h_value < 0.75: return 1
            if 0.18 <= h_value < 0.40: return 2
            if (0.00 <= h_value < 0.18) or (0.95 <= h_value <= 1.00): return 3
            return 99
        for color_rgb in palette:
            r, g, b = color_rgb
            h, s, l = rgb_to_hsl(r, g, b)
            if l < 0.5 and s < 0.25: continue
            if l > 0.80: continue
            is_vibrant_and_bright = (l >= 0.5 and s > 0.4)
            is_bright_grayish = (l >= 0.6 and s >= 0.25 and s <= 0.4)
            if is_vibrant_and_bright:
                score = s * l
                qualified_colors.append({'color': color_rgb, 'score': score, 'type': 'vibrant_bright', 'hue_priority': get_hue_priority_index(h)})
            elif is_bright_grayish:
                score = l * 0.5 + s * 0.5
                qualified_colors.append({'color': color_rgb, 'score': score, 'type': 'bright_grayish', 'hue_priority': 98})
        qualified_colors.sort(key=lambda x: (0 if x['type'] == 'vibrant_bright' else 1, -x['score'], x['hue_priority']))
        if qualified_colors:
            return qualified_colors[0]['color']
        else:
            best_fallback_color = (0, 252, 233)
            max_l_fallback = -1
            for color in palette:
                _, _, l = rgb_to_hsl(*color)
                if not (color[0] < 30 and color[1] < 30 and color[2] < 30):
                    if l > max_l_fallback:
                        max_l_fallback = l
                        best_fallback_color = color
            return best_fallback_color
    except Exception as e:
        print(f"LỖI COLORTHIEF: Không thể lấy bảng màu từ avatar: {e}")
        return (0, 252, 233)

def _load_fonts(main_path, symbol_path):
    # Sửa lỗi: Cải thiện logic tải font
    global FONT_WELCOME, FONT_NAME, FONT_SYMBOL
    try:
        FONT_WELCOME = ImageFont.truetype(main_path, WELCOME_FONT_SIZE)
        FONT_NAME = ImageFont.truetype(main_path, NAME_FONT_SIZE)
        print(f"DEBUG: Đã tải font chính thành công: {main_path}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font chính '{main_path}'. Sử dụng Arial. Chi tiết: {e}")
        try:
            FONT_WELCOME = ImageFont.truetype("arial.ttf", WELCOME_FONT_SIZE)
            FONT_NAME = ImageFont.truetype("arial.ttf", NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font Arial.ttf cho văn bản chính.")
        except Exception:
            FONT_WELCOME = ImageFont.load_default().font_variant(size=WELCOME_FONT_SIZE)
            FONT_NAME = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font mặc định của Pillow cho văn bản chính.")
    try:
        FONT_SYMBOL = ImageFont.truetype(symbol_path, NAME_FONT_SIZE)
        print(f"DEBUG: Đã tải font biểu tượng thành công: {symbol_path}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font biểu tượng '{symbol_path}'. Sử dụng font mặc định cho biểu tượng. Chi tiết: {e}")
        FONT_SYMBOL = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
        print("DEBUG: Đã sử dụng font mặc định của Pillow cho biểu tượng.")
    return FONT_WELCOME, FONT_NAME, FONT_SYMBOL

def _load_background_image(path, default_dims):
    # Sửa lỗi: Cải thiện logic tải ảnh nền
    global WELCOME_BG_IMG
    try:
        WELCOME_BG_IMG = Image.open(path).convert("RGBA")
        print(f"DEBUG: Đã tải ảnh nền: {path} với kích thước {WELCOME_BG_IMG.size[0]}x{WELCOME_BG_IMG.size[1]}")
    except FileNotFoundError:
        print(f"LỖI ẢNH NỀN: Không tìm thấy ảnh nền '{path}'. Sử dụng nền màu mặc định.")
        WELCOME_BG_IMG = Image.new('RGBA', default_dims, color=(0, 0, 0, 255))
    except Exception as e:
        print(f"LỖI ẢNH NỀN: Lỗi khi mở ảnh nền: {e}. Sử dụng nền màu mặc định.")
        WELCOME_BG_IMG = Image.new('RGBA', default_dims, color=(0, 0, 0, 255))
    return WELCOME_BG_IMG

async def _get_and_process_avatar(member_avatar_url, avatar_size, cache):
    avatar_bytes = None
    # Kiểm tra cache
    if member_avatar_url in cache and (asyncio.get_event_loop().time() - cache[member_avatar_url]['timestamp']) < CACHE_TTL:
        avatar_bytes = cache[member_avatar_url]['data']
        print(f"DEBUG: Lấy avatar từ cache.")
    else:
        # Dùng session dùng chung để tải ảnh (Tối ưu ở đây)
        try:
            async with bot.session.get(str(member_avatar_url)) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()
                    cache[member_avatar_url] = {'data': avatar_bytes, 'timestamp': asyncio.get_event_loop().time()}
        except Exception as e:
            print(f"LỖI TẢI AVATAR: {e}")

    if avatar_bytes:
        data = io.BytesIO(avatar_bytes)
        avatar_img = Image.open(data).convert("RGBA")
    else:
        avatar_img = Image.new('RGBA', (avatar_size, avatar_size), color=(100, 100, 100, 255))
    
    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)
    return avatar_img, avatar_bytes

def _draw_circular_avatar_and_stroke(img, avatar_img, avatar_x, avatar_y, avatar_size, stroke_color_rgb):
    draw = ImageDraw.Draw(img)
    blur_color_with_alpha = (*stroke_color_rgb, 128)
    blur_bg_raw_circle = Image.new('RGBA', (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 0))
    draw_blur_bg_raw = ImageDraw.Draw(blur_bg_raw_circle)
    draw_blur_bg_raw.ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=blur_color_with_alpha)
    img.paste(blur_bg_raw_circle, (avatar_x, avatar_y), blur_bg_raw_circle)
    stroke_thickness = 6
    gap_size = 5
    outer_stroke_diameter = AVATAR_SIZE + (gap_size * 2) + (stroke_thickness * 2)
    inner_stroke_diameter = AVATAR_SIZE + (gap_size * 2)
    supersample_factor = 4
    temp_stroke_layer_supersampled = Image.new('RGBA', (outer_stroke_diameter * supersample_factor, outer_stroke_diameter * supersample_factor), (0, 0, 0, 0))
    draw_temp_stroke = ImageDraw.Draw(temp_stroke_layer_supersampled)
    draw_temp_stroke.ellipse((0, 0, outer_stroke_diameter * supersample_factor, outer_stroke_diameter * supersample_factor), fill=(*stroke_color_rgb, 255))
    inner_offset_x = (outer_stroke_diameter * supersample_factor - inner_stroke_diameter * supersample_factor) // 2
    inner_offset_y = (outer_stroke_diameter * supersample_factor - inner_stroke_diameter * supersample_factor) // 2
    draw_temp_stroke.ellipse((inner_offset_x, inner_offset_y, inner_offset_x + inner_stroke_diameter * supersample_factor, inner_offset_y + inner_stroke_diameter * supersample_factor), fill=(0, 0, 0, 0))
    stroke_final_image = temp_stroke_layer_supersampled.resize((outer_stroke_diameter, outer_stroke_diameter), Image.LANCZOS)
    stroke_paste_x = avatar_x - gap_size - stroke_thickness
    stroke_paste_y = avatar_y - gap_size - stroke_thickness
    img.paste(stroke_final_image, (stroke_paste_x, stroke_paste_y), stroke_final_image)
    avatar_layer = Image.new('RGBA', (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 0))
    avatar_layer.paste(avatar_img, (0, 0))
    mask_supersample_factor = 4
    mask_raw_size = AVATAR_SIZE * mask_supersample_factor
    circular_mask_raw = Image.new('L', (mask_raw_size, mask_raw_size), 0)
    draw_circular_mask_raw = ImageDraw.Draw(circular_mask_raw)
    draw_circular_mask_raw.ellipse((0, 0, mask_raw_size, mask_raw_size), fill=255)
    circular_mask_smoothed = circular_mask_raw.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    try:
        original_alpha = avatar_layer.split()[3]
    except ValueError:
        original_alpha = Image.new('L', circular_mask_smoothed.size, 255)
    final_alpha_mask = Image.composite(circular_mask_smoothed, Image.new('L', circular_mask_smoothed.size, 0), original_alpha)
    img.paste(avatar_layer, (avatar_x, avatar_y), final_alpha_mask)

def _draw_text_with_shadow(draw_obj, text, font, x, y, main_color, shadow_color, offset_x, offset_y):
    draw_obj.text((x + offset_x, y + offset_y), text, font=font, fill=shadow_color)
    draw_obj.text((x, y), text, font=font, fill=main_color)

def _draw_simple_decorative_line(draw_obj, img_width, line_y, line_color_rgb, actual_line_length):
    line_x1 = img_width // 2 - actual_line_length // 2
    line_x2 = img_width // 2 + actual_line_length // 2
    draw_obj.line([(line_x1, line_y), (line_x2, line_y)], fill=line_color_rgb, width=LINE_THICKNESS)

def _get_text_width(text, font, draw_obj):
    return draw_obj.textlength(text, font=font)

def _get_text_height(text, font, draw_obj):
    bbox = draw_obj.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]

def is_basic_char(char):
    if 'a' <= char <= 'z' or 'A' <= char <= 'Z': return True
    if '0' <= char <= '9': return True
    special_chars_to_keep = """.,?!;:'"()[]{}<>+-*/=@_|=~`!^*""" + '\\'
    if char in special_chars_to_keep or char.isspace(): return True
    unicode_ord = ord(char)
    if (0x00C0 <= unicode_ord <= 0x017F) or (0x1EA0 <= unicode_ord <= 0x1EFF): return True
    return False

def process_text_for_drawing(original_text, main_font, symbol_font, replacement_char='✦'):
    processed_parts = []
    total_width = 0
    temp_draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    for char in original_text:
        if is_basic_char(char):
            processed_parts.append((char, main_font))
            total_width += temp_draw.textlength(char, font=main_font)
        else:
            processed_parts.append((replacement_char, symbol_font))
            total_width += temp_draw.textlength(replacement_char, font=symbol_font)
    return processed_parts, total_width

async def create_welcome_image(member):
    # SỬA LỖI: Không tải lại tài nguyên. Dùng biến toàn cục đã tải trong on_ready
    global FONT_WELCOME, FONT_NAME, FONT_SYMBOL, WELCOME_BG_IMG
    
    img = WELCOME_BG_IMG.copy()
    img_width, img_height = img.size
    draw = ImageDraw.Draw(img)
    shadow_offset_x = int(img_width * 0.005)
    shadow_offset_y = int(img_height * 0.005)

    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    avatar_img, avatar_bytes = await _get_and_process_avatar(avatar_url, AVATAR_SIZE, avatar_cache)

    dominant_color_from_avatar = None
    if avatar_bytes:
        dominant_color_from_avatar = await get_dominant_color(avatar_bytes, color_count=20)
    if dominant_color_from_avatar is None:
        dominant_color_from_avatar = (0, 252, 233)
    
    stroke_color_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar, brightness_factor=1.1, saturation_factor=4.9, clamp_min_l=0.6, clamp_max_l=0.90)
    stroke_color = (*stroke_color_rgb, 255)

    avatar_x = img_width // 2 - AVATAR_SIZE // 2
    avatar_y = int(img_height * 0.36) - AVATAR_SIZE // 2
    y_offset_from_avatar = 20
    welcome_text_y_pos = avatar_y + AVATAR_SIZE + y_offset_from_avatar

    _draw_circular_avatar_and_stroke(img, avatar_img, avatar_x, avatar_y, AVATAR_SIZE, stroke_color_rgb)

    welcome_text = "WELCOME"
    welcome_text_width = draw.textlength(welcome_text, font=FONT_WELCOME)
    welcome_text_x = (img_width - welcome_text_width) / 2
    shadow_color_welcome_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar, brightness_factor=0.3, saturation_factor=3.0, clamp_min_l=0.25, clamp_max_l=0.55)
    _draw_text_with_shadow(draw, welcome_text, FONT_WELCOME, welcome_text_x, welcome_text_y_pos, (255, 255, 255), (*shadow_color_welcome_rgb, 255), shadow_offset_x, shadow_offset_y)

    name_text_raw = member.display_name
    max_chars_for_name = 25
    if len(name_text_raw) > max_chars_for_name:
        name_text_raw = name_text_raw[:max_chars_for_name - 3] + "..."
    processed_name_parts, name_text_width = process_text_for_drawing(name_text_raw, FONT_NAME, FONT_SYMBOL, replacement_char='✦')
    name_text_x = (img_width - name_text_width) / 2
    welcome_bbox_for_height = draw.textbbox((0, 0), welcome_text, font=FONT_WELCOME)
    welcome_actual_height = welcome_bbox_for_height[3] - welcome_bbox_for_height[1]
    name_text_y = welcome_text_y_pos + welcome_actual_height + 20
    
    shadow_color_name_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar, brightness_factor=0.3, saturation_factor=3.0, clamp_min_l=0.25, clamp_max_l=0.55)
    shadow_color_name = (*shadow_color_name_rgb, 255)

    current_x = name_text_x
    for char, font_to_use in processed_name_parts:
        draw.text((current_x + shadow_offset_x, name_text_y + shadow_offset_y), char, font=font_to_use, fill=shadow_color_name)
        draw.text((current_x, name_text_y), char, font=font_to_use, fill=stroke_color)
        current_x += draw.textlength(char, font=font_to_use)

    name_actual_height = _get_text_height("M", FONT_NAME, draw)
    line_y = name_text_y + name_actual_height + LINE_VERTICAL_OFFSET_FROM_NAME
    line_color_rgb = stroke_color_rgb
    actual_line_length = int(name_text_width * LINE_LENGTH_FACTOR)
    _draw_simple_decorative_line(draw, img_width, line_y, line_color_rgb, actual_line_length)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# --- Các worker và sự kiện Bot ---
async def activity_heartbeat_worker():
    await bot.wait_until_ready()
    activities = [
        discord.Activity(type=discord.ActivityType.watching, name="Dawn_wibu phá đảo game"),
        discord.Activity(type=discord.ActivityType.listening, name="TRÌNH"),
    ]
    while True:
        try:
            await asyncio.sleep(random.randint(60, 180))
            # 1. Đổi trạng thái bot
            await bot.change_presence(activity=random.choice(activities))
            
            # 2. TỐI ƯU: Dọn dẹp bộ nhớ (xóa avatar cũ trong cache)
            now = asyncio.get_event_loop().time()
            expired = [k for k, v in avatar_cache.items() if now - v['timestamp'] > CACHE_TTL]
            for k in expired: del avatar_cache[k]
            
        except Exception as e:
            print(f"LỖI WORKER: {e}")
            await asyncio.sleep(30)

async def random_message_worker():
    await bot.wait_until_ready()
    print("DEBUG: random_message_worker bắt đầu.")
    channel_id = 1379789952610467971
    messages = [
        "Hôm nay trời đẹp ghê 😎", "Anh em nhớ uống nước nha 💧", "Ai đang onl vậy 🙌", "👺", "👾", "🤖", "💖", "💋", "👀", "😎", "🤞", "✨", "🤤",
    ]
    while True:
        try:
            sleep_seconds = random.randint(300, 600)
            await asyncio.sleep(sleep_seconds)
            channel = bot.get_channel(channel_id)
            if channel:
                msg = random.choice(messages)
                await channel.send(msg)
                print(f"DEBUG: Đã gửi tin nhắn: {msg}")
            else:
                print("DEBUG: Không tìm thấy channel để gửi tin.")
        except Exception as e:
            print(f"LỖI RANDOM_MESSAGE_WORKER: {e}")
            await asyncio.sleep(30)

# --- Slash Command: /skibidi ---
@bot.tree.command(name="skibidi", description="Dẫn tới Dawn_wibu.")
@app_commands.checks.has_role(1412820448499990629)
async def skibidi(interaction: discord.Interaction):
    await interaction.response.send_message("<a:cat2:1323314096040448145>**✦** *** [AN BA TO KOM](<https://guns.lol/dawn_wibu>) *** **✦** <a:cat3:1323314218476372122>")

# --- Slash Command: /testwelcome ---
@bot.tree.command(name="testwelcome", description="Tạo và gửi ảnh chào mừng cho người dùng.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True)
async def testwelcome_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True)
    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member_to_test.display_name}...")
        image_bytes = None
        if IMAGE_GEN_SEMAPHORE:
            async with IMAGE_GEN_SEMAPHORE:
                image_bytes = await create_welcome_image(member_to_test)
        else:
            image_bytes = await create_welcome_image(member_to_test)
        await interaction.followup.send(file=discord.File(fp=image_bytes, filename="welcome_test.png"))
        print(f"DEBUG: Đã gửi ảnh test chào mừng cho {member_to_test.display_name}.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test: `{e}`\nKiểm tra lại hàm `create_welcome_image`.")
        print(f"LỖI TEST: {e}")
        
# --- Slash Command: /link ---
@bot.tree.command(name="link", description="Tạo một dòng chữ chứa link rút gọn (Markdown).")
@app_commands.describe(
    url="Dán cái link dài vào đây nè",
    text="Chữ muốn hiển thị (ví dụ: 'Xem tại đây', mặc định là 'Link')"
)
async def create_link(interaction: discord.Interaction, url: str, text: str = "Link"):
    # Kiểm tra xem có đúng là link không (cơ bản)
    if not url.startswith(("http://", "https://")):
        await interaction.response.send_message("⚠️ Link phải bắt đầu bằng http:// hoặc https:// nha!", ephemeral=True)
        return

    # Tạo định dạng [Chữ](Link)
    # Dùng dấu < > bao quanh link để tránh Discord tự hiện preview ảnh/web nếu muốn (tùy ông)
    # Ở đây tui để bình thường để nó hiện preview cho đẹp
    formatted_link = f"[{text}]({url})"
    
    await interaction.response.send_message(f"✨ Đây là link của bạn: {formatted_link}")
# --- Sự kiện on_ready ---
@bot.event
async def on_ready():
    global IMAGE_GEN_SEMAPHORE
    # THÊM DÒNG NÀY: Khởi tạo session để tải ảnh nhanh hơn
    if not hasattr(bot, 'session'):
        bot.session = aiohttp.ClientSession()
        
    if IMAGE_GEN_SEMAPHORE is None:
        IMAGE_GEN_SEMAPHORE = asyncio.Semaphore(2)
    
    _load_fonts(FONT_MAIN_PATH, FONT_SYMBOL_PATH)
    _load_background_image(BACKGROUND_IMAGE_PATH, DEFAULT_IMAGE_DIMENSIONS)
    
    print("===================================")
    print(f"🤖 Bot đã đăng nhập thành công!")
    print(f"👤 Tên bot    : {bot.user} (ID: {bot.user.id})")
    print(f"🌐 Server(s) : {len(bot.guilds)}")
    print("===================================")
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Đã đồng bộ {len(synced)} lệnh slash commands.")
    except Exception as e:
        print(f"❌ Lỗi khi đồng bộ slash command: {e}")
        
    if not getattr(bot, "bg_tasks_started", False):
        bot.bg_tasks_started = True
        bot.loop.create_task(activity_heartbeat_worker())
        bot.loop.create_task(random_message_worker())
        bot.loop.create_task(flask_ping_worker())
        active_developer_maintenance.start()
        print("⚙️ Background workers đã được khởi động.")

# --- Task tự ping Flask để giữ bot active ---
async def flask_ping_worker():
    await bot.wait_until_ready()
    print("DEBUG: flask_ping_worker bắt đầu ping Flask để giữ bot online.")
    flask_url = "https://botmlem.onrender.com/healthz"
    # SỬA LỖI: Sử dụng bot.session đã khởi tạo
    while True:
        try:
            await asyncio.sleep(300)
            if hasattr(bot, 'session'):
                async with bot.session.get(flask_url, timeout=10) as response:
                    print(f"DEBUG: Ping {flask_url}, status_code={response.status}")
        except Exception as e:
            print(f"LỖI PING FLASK: {e}")

@bot.event
async def on_member_join(member):
    channel_id = 1322848542758277202
    channel = bot.get_channel(channel_id)
    if channel is None:
        print(f"LỖI KÊNH: Không tìm thấy kênh với ID {channel_id}.")
        return
    if not channel.permissions_for(member.guild.me).send_messages or not channel.permissions_for(member.guild.me).attach_files:
        print(f"LỖI QUYỀN: Bot không có quyền gửi tin nhắn hoặc đính kèm file trong kênh {channel.name}.")
        return
    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member.display_name}...")
        if IMAGE_GEN_SEMAPHORE:
            async with IMAGE_GEN_SEMAPHORE:
                image_bytes = await create_welcome_image(member)
        else:
            image_bytes = await create_welcome_image(member)
        welcome_messages = [
            f"**<a:cat2:1323314096040448145>** **Chào mừng {member.mention} đã đến với {member.guild.name}!** ✨",
            f"👋 **Xin chào {member.mention}, chúc bạn chơi vui tại {member.guild.name}**! **<a:cat2:1323314096040448145>**",
            f"**<a:cat2:1323314096040448145>** **{member.mention} đã gia nhập băng đẳng {member.guild.name}**! 🥳",
            f"**<a:cat2:1323314096040448145>** **{member.mention} đã join party! Cả team {member.guild.name} ready chưa?**! 🎮",
            f"🌟 **{member.mention} đã mở khóa map {member.guild.name}! Chúc mừng thí chủ ** **<a:cat2:1323314096040448145>**",
        ]
        welcome_text = random.choice(welcome_messages)
        await channel.send(welcome_text, file=discord.File(fp=image_bytes, filename='welcome.png'))
        print(f"Đã gửi ảnh chào mừng thành công cho {member.display_name}!")
    except discord.errors.HTTPException as e:
        print(f"LỖI HTTP DISCORD: Lỗi khi gửi ảnh chào mừng: {e}")
        await channel.send(f"Chào mừng {member.mention} đã đến với {member.guild.name}! (Có lỗi khi tạo ảnh chào mừng, xin lỗi!)")
    except Exception as e:
        print(f"LỖỖI CHÀO MỪNG KHÁC: Lỗi khi tạo hoặc gửi ảnh chào mừng: {e}")
        await channel.send(f"Chào mừng {member.mention} đã đến với {member.guild.name}!")
        
# Danh sách role xếp hạng (cao -> thấp)
RANK_ROLES = [1416629995534811176,
              1368614250603614348,
              1416630670473691260,
              1416630172345565287,
              1368614259595935916, 
              1368614263324934316, 
              1368629255654871251, 
              1322844864760516691]
# Kênh thông báo
NOTIFY_CHANNEL_ID = 1368613831529726137
# Map role -> hiển thị đẹp
ROLE_DISPLAY = {
    1416629995534811176: "🔥 **Nguyên Tôn**",
    1368614250603614348: "🪀 **Thượng Cổ Nhân**", 
    1416630670473691260: "🔮 **Đại Hiền Giả**", 
    1416630172345565287: "🌀 **Hiền Giả**", 
    1368614259595935916: "💠 **Cổ Linh**", 
    1368614263324934316: "🧩 **Tân Hồn**", 
    1368629255654871251: "⚔️ **Lữ Hành Giả**", 
    1322844864760516691: "🐣 **Tân Giả**",
}

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    before_roles = set(before.roles)
    after_roles = set(after.roles)
    new_roles = after_roles - before_roles
    
    if not new_roles: return
    
    for role_id in RANK_ROLES:
        role = after.guild.get_role(role_id)
        if role in new_roles:
            # Gửi thông báo thăng cấp
            channel = after.guild.get_channel(NOTIFY_CHANNEL_ID)
            if channel:
                role_display = ROLE_DISPLAY.get(role.id, role.name)
                embed = discord.Embed(
                    title="⬆ LEVEL UP ⬆",
                    description=(f"Xin chúc mừng {after.mention} đã thăng cấp lên {role_display}!"),
                    color=role.color if role.color.value else discord.Color.gold()
                )
                embed.set_thumbnail(url=after.display_avatar.url)
                await channel.send(embed=embed)

            # TỐI ƯU: Xóa tất cả role thấp hơn trong 1 lần gửi yêu cầu duy nhất
            role_index = RANK_ROLES.index(role_id)
            lower_role_ids = set(RANK_ROLES[role_index + 1:])
            
            # Tạo danh sách role mới (loại bỏ các role thấp)
            final_roles = [r for r in after.roles if r.id not in lower_role_ids]
            
            if len(final_roles) != len(after.roles):
                await after.edit(roles=final_roles)
                print(f"Đã tối ưu: Xóa các role thấp cho {after.display_name}")
            break
# --- Auto Reply theo keyword ---
# 1. Thiết lập Cooldown: cho phép 1 tin nhắn mỗi 5 giây trên mỗi người dùng
# (Bạn có thể chỉnh 1, 5 thành số khác tùy nhu cầu)
_cooldown = commands.CooldownMapping.from_cooldown(1, 5, commands.BucketType.user)

@bot.event
async def on_message(message):
    if message.author.bot: 
        return

    # strip() để loại bỏ khoảng trắng dư thừa ở đầu/cuối
    content = message.content.lower().strip()

    # Danh sách từ khóa khớp 100%
    responses = {
        "ping": "Pong 🏓",
        "hello": f"Chào {message.author.mention} 😎",
        "hi": f"Chào {message.author.mention} <a:2:1387245423185498265>",
        "có ai ko": f"Có tui nè {message.author.mention} 😘"
    }

    # 2. Kiểm tra xem nội dung có khớp TUYỆT ĐỐI trong danh sách không
    if content in responses:
        # 3. Kiểm tra Cooldown (Chống spam)
        bucket = _cooldown.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        
        if retry_after:
            # Nếu đang bị cooldown thì im lặng (hoặc báo lỗi nếu muốn)
            return 

        # Nếu vượt qua cooldown thì mới gửi tin nhắn
        await message.channel.send(responses[content])
        return

    await bot.process_commands(message)

# --- Khởi chạy Flask và Bot Discord ---
async def start_bot_and_flask():
    """Hàm async để khởi động Flask + bot Discord với delay và restart chậm (avoid rate limit)."""
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    delay_before_login = 30
    print(f"DEBUG: Đang đợi {delay_before_login}s trước khi khởi động bot Discord để tránh rate limit...")
    await asyncio.sleep(delay_before_login)
    print("DEBUG: Bắt đầu khởi động bot Discord...")
    while True:
        try:
            await bot.start(TOKEN)
            break
        except discord.errors.HTTPException as e:
            if getattr(e, 'status', None) == 429:
                print(f"Lỗi 429 Too Many Requests khi đăng nhập: {e}")
                print("Có vẻ như Discord đã giới hạn tốc độ đăng nhập. Đợi 5-10 phút trước khi thử lại.")
                await asyncio.sleep(300)
            else:
                print(f"Một lỗi HTTP khác khi đăng nhập: {e}")
                await asyncio.sleep(60)
        except Exception as e:
            print(f"Một lỗi không xác định đã xảy ra: {e}. Restart sau 60s...")
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(start_bot_and_flask())
    except KeyboardInterrupt:
        print("Bot đã bị dừng bằng tay.")
