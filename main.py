import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import io
import aiohttp
import asyncio
import random
import requests
import threading
from flask import Flask
from colorthief import ColorThief

# Dòng kiểm tra này sẽ xuất hiện ngay khi bot bắt đầu chạy
print("--- BOT IS RUNNING NEW CODE! ---")

# --- Khởi tạo Flask app ---
app = Flask(__name__)

@app.route('/')
def home():
    """Endpoint chính cho Flask app. Có thể dùng làm Health Check nếu cần."""
    return "Bot is alive and healthy!"

@app.route('/healthz')
def health_check():
    """Endpoint Health Check riêng biệt cho Render.com hoặc Replit."""
    return "OK", 200

def send_self_ping():
    """Gửi yêu cầu HTTP đến chính Flask server để giữ nó hoạt động."""
    port = int(os.environ.get("PORT", 10000))
    url = f"http://localhost:{port}/healthz"
    try:
        response = requests.get(url, timeout=5)
        print(
            f"DEBUG: Tự ping Flask server: {url} - Status: {response.status_code}"
        )
    except requests.exceptions.RequestException as e:
        print(f"LỖI SELF-PING: Không thể tự ping Flask server: {e}")

    next_ping_interval = random.randint(3 * 60, 10 * 60)
    threading.Timer(next_ping_interval, send_self_ping).start()
    print(
        f"DEBUG: Lập lịch tự ping tiếp theo sau {next_ping_interval // 60} phút."
    )

def run_flask():
    """Chạy Flask app trong một luồng riêng biệt và bắt đầu tự ping."""
    port = int(os.environ.get("PORT", 10000))
    print(f"Flask server đang chạy trên cổng {port} (để Health Check).")

    threading.Timer(10, send_self_ping).start() # Bắt đầu tự ping sau 10 giây khởi động Flask
    print("DEBUG: Đã bắt đầu tác vụ tự ping Flask server.")

    app.run(host='0.0.0.0', port=port,
            debug=False)

# --- Cấu hình Bot Discord ---
TOKEN = os.getenv('DISCORD_BOT_TOKEN') # Hoặc TOKEN = os.getenv('TOKEN') nếu biến môi trường của bạn là 'TOKEN'

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

# --- Các hàm xử lý màu sắc (giữ nguyên logic phức tạp của bạn) ---
def rgb_to_hsl(r, g, b):
    r /= 255.0
    g /= 255.0
    b /= 255.0

    cmax = max(r, g, b)
    cmin = min(r, g, b)
    delta = cmax - cmin

    h, s, l = 0, 0, (cmax + cmin) / 2

    if delta == 0:
        h = 0
        s = 0
    else:
        if l < 0.5:
            s = delta / (cmax + cmin)
        else:
            s = delta / (2 - cmax - cmin)

        if cmax == r:
            h = ((g - b) / delta) % 6
        elif cmax == g:
            h = (b - r) / delta + 2
        else:
            h = (r - g) / delta + 4
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

def is_dark_color(rgb_color, lightness_threshold=0.3):
    """Kiểm tra xem màu RGB có tối không dựa trên độ sáng (L trong HSL)."""
    _, _, l = rgb_to_hsl(*rgb_color)
    return l < lightness_threshold

def adjust_color_brightness_saturation(rgb_color,
                                       brightness_factor=1.0,
                                       saturation_factor=1.0,
                                       clamp_min_l=0.0,
                                       clamp_max_l=1.0):
    h, s, l = rgb_to_hsl(*rgb_color)

    l = l * brightness_factor

    if clamp_min_l != 0.0 or clamp_max_l != 1.0:
        l = min(clamp_max_l, max(clamp_min_l, l))

    s = min(1.0, max(0.0, s * saturation_factor))

    return hsl_to_rgb(h, s, l)

async def get_dominant_color(image_bytes, color_count=20):
    """
    Lấy màu chủ đạo từ image_bytes.
    Trả về màu RGB, chế độ ảnh gốc (RGBA/RGB), và ảnh đã được làm phẳng (dưới dạng BytesIO)
    """
    try:
        f = io.BytesIO(image_bytes)
        img_pil = Image.open(f)

        img_temp_io = io.BytesIO() # Để lưu ảnh đã làm phẳng

        # Xử lý độ trong suốt: Nếu ảnh là RGBA (có kênh alpha), dán lên nền trắng
        if img_pil.mode == 'RGBA':
            background = Image.new('RGB', img_pil.size, (255, 255, 255))
            background.paste(img_pil, (0, 0), img_pil)
            img_temp = background
            img_temp.save(img_temp_io, format='PNG')
        else:
            img_temp = img_pil.convert("RGB")
            img_temp.save(img_temp_io, format='PNG')
        
        img_temp_io.seek(0) # Đặt con trỏ về đầu file để ColorThief đọc

        color_thief = ColorThief(img_temp_io)
        palette = color_thief.get_palette(color_count=color_count, quality=1)
        print(f"DEBUG_COLORTHIEF: Bảng màu thô từ ColorThief: {palette}")

        qualified_colors = []

        def get_hue_priority_index(h_value):
            if 0.75 <= h_value < 0.95: return 0  # Tím/Magenta
            if 0.40 <= h_value < 0.75: return 1  # Xanh Dương/Xanh Da Trời
            if 0.18 <= h_value < 0.40: return 2  # Xanh Lá
            if (0.00 <= h_value < 0.18) or (0.95 <= h_value <= 1.00): return 3 # Đỏ/Cam/Vàng
            return 99

        for color_rgb in palette:
            r, g, b = color_rgb
            h, s, l = rgb_to_hsl(r, g, b)

            if (l < 0.5 and s < 0.25) or (l > 0.90):
                continue
            
            is_vibrant_and_bright = (l >= 0.5 and s > 0.4)
            is_bright_grayish = (l >= 0.6 and s >= 0.25 and s <= 0.4)

            if is_vibrant_and_bright:
                score = s * l
                qualified_colors.append({
                    'color': color_rgb,
                    'score': score,
                    'type': 'vibrant_bright',
                    'hue_priority': get_hue_priority_index(h)
                })
            elif is_bright_grayish:
                score = l * 0.5 + s * 0.5
                qualified_colors.append({
                    'color': color_rgb,
                    'score': score,
                    'type': 'bright_grayish',
                    'hue_priority': 98
                })
            
        qualified_colors.sort(key=lambda x: (
            0 if x['type'] == 'vibrant_bright' else 1,
            -x['score'],
            x['hue_priority']
        ))

        dominant_color = (0, 252, 233) # Default Cyan
        if qualified_colors:
            dominant_color = qualified_colors[0]['color']
        else:
            best_fallback_color = (0, 252, 233)
            max_l_fallback = -1
            for color in palette:
                if not (color[0] < 30 and color[1] < 30 and color[2] < 30):
                    _, _, l = rgb_to_hsl(*color)
                    if l > max_l_fallback:
                        max_l_fallback = l
                        best_fallback_color = color
            dominant_color = best_fallback_color

        return dominant_color, img_pil.mode, img_temp_io

    except Exception as e:
        print(f"LỖI COLORTHIEF: Không thể lấy bảng màu từ avatar: {e}")
        # Trả về default color, mode và một BytesIO trống rỗng nếu lỗi
        return (0, 252, 233), 'UNKNOWN', io.BytesIO()

avatar_cache = {}
CACHE_TTL = 300 # Thời gian sống của cache avatar (giây)

# --- CÁC HẰNG SỐ DÙNG TRONG TẠO ẢNH ---
FONT_MAIN_PATH = "1FTV-Designer.otf"
FONT_SYMBOL_PATH = "subset-DejaVuSans.ttf"
WELCOME_FONT_SIZE = 60
NAME_FONT_SIZE = 34
AVATAR_SIZE = 210 # Kích thước avatar sau khi resize
BACKGROUND_IMAGE_PATH = "welcome.png"
STROKE_IMAGE_PATH = "stroke.png"
DEFAULT_IMAGE_DIMENSIONS = (872, 430) # Kích thước ảnh nền mặc định
LINE_THICKNESS = 3 # Độ dày của line dưới tên
LINE_VERTICAL_OFFSET_FROM_NAME = 13 # Khoảng cách từ tên đến đường line
LINE_LENGTH_FACTOR = 0.70 # Tỷ lệ độ dài của line so với độ dài của tên

# --- GLOBAL VARIABLES FOR PRE-LOADED ASSETS ---
# Sẽ được tải một lần khi bot khởi động
GLOBAL_FONT_WELCOME = None
GLOBAL_FONT_NAME = None
GLOBAL_FONT_SYMBOL = None
GLOBAL_BACKGROUND_IMAGE = None
GLOBAL_STROKE_OVERLAY_IMAGE = None

# --- CÁC HÀM HỖ TRỢ CHO create_welcome_image ---

def _load_static_assets():
    """Tải font, ảnh nền, ảnh stroke một lần duy nhất khi bot khởi động."""
    global GLOBAL_FONT_WELCOME, GLOBAL_FONT_NAME, GLOBAL_FONT_SYMBOL
    global GLOBAL_BACKGROUND_IMAGE, GLOBAL_STROKE_OVERLAY_IMAGE

    print("DEBUG: Đang tải các tài nguyên tĩnh (fonts, ảnh nền, stroke)...")

    # Tải Fonts
    try:
        GLOBAL_FONT_WELCOME = ImageFont.truetype(FONT_MAIN_PATH, WELCOME_FONT_SIZE)
        GLOBAL_FONT_NAME = ImageFont.truetype(FONT_MAIN_PATH, NAME_FONT_SIZE)
        print(f"DEBUG: Đã tải font chính thành công: {FONT_MAIN_PATH}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font chính '{FONT_MAIN_PATH}'. Sử dụng Arial. Chi tiết: {e}")
        try:
            GLOBAL_FONT_WELCOME = ImageFont.truetype("arial.ttf", WELCOME_FONT_SIZE)
            GLOBAL_FONT_NAME = ImageFont.truetype("arial.ttf", NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font Arial.ttf cho văn bản chính.")
        except Exception:
            GLOBAL_FONT_WELCOME = ImageFont.load_default().font_variant(size=WELCOME_FONT_SIZE)
            GLOBAL_FONT_NAME = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font mặc định của Pillow cho văn bản chính.")
    
    try:
        GLOBAL_FONT_SYMBOL = ImageFont.truetype(FONT_SYMBOL_PATH, NAME_FONT_SIZE)
        print(f"DEBUG: Đã tải font biểu tượng thành công: {FONT_SYMBOL_PATH}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font biểu tượng '{FONT_SYMBOL_PATH}'. Sử dụng font mặc định cho biểu tượng. Chi tiết: {e}")
        GLOBAL_FONT_SYMBOL = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
        print("DEBUG: Đã sử dụng font mặc định của Pillow cho biểu tượng.")

    # Tải ảnh nền
    try:
        GLOBAL_BACKGROUND_IMAGE = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
        if GLOBAL_BACKGROUND_IMAGE.size != DEFAULT_IMAGE_DIMENSIONS:
            print(f"CẢNH BÁO: Ảnh nền '{BACKGROUND_IMAGE_PATH}' có kích thước {GLOBAL_BACKGROUND_IMAGE.size} khác với kích thước mặc định {DEFAULT_IMAGE_DIMENSIONS}. Sẽ resize.")
            GLOBAL_BACKGROUND_IMAGE = GLOBAL_BACKGROUND_IMAGE.resize(DEFAULT_IMAGE_DIMENSIONS, Image.LANCZOS)
        print(f"DEBUG: Đã tải ảnh nền: {BACKGROUND_IMAGE_PATH} với kích thước {GLOBAL_BACKGROUND_IMAGE.size[0]}x{GLOBAL_BACKGROUND_IMAGE.size[1]}.")
    except FileNotFoundError:
        print(f"LỖI ẢNH NỀN: Không tìm thấy ảnh nền '{BACKGROUND_IMAGE_PATH}'. Tạo nền màu mặc định.")
        GLOBAL_BACKGROUND_IMAGE = Image.new('RGBA', DEFAULT_IMAGE_DIMENSIONS, color=(0, 0, 0, 255))
    except Exception as e:
        print(f"LỖI ẢNH NỀN: Lỗi khi mở ảnh nền '{BACKGROUND_IMAGE_PATH}': {e}. Tạo nền màu mặc định.")
        GLOBAL_BACKGROUND_IMAGE = Image.new('RGBA', DEFAULT_IMAGE_DIMENSIONS, color=(0, 0, 0, 255))

    # Tải ảnh stroke overlay
    try:
        GLOBAL_STROKE_OVERLAY_IMAGE = Image.open(STROKE_IMAGE_PATH).convert("RGBA")
        if GLOBAL_STROKE_OVERLAY_IMAGE.size != DEFAULT_IMAGE_DIMENSIONS:
            print(f"CẢNH BÁO: Ảnh stroke overlay '{STROKE_IMAGE_PATH}' có kích thước {GLOBAL_STROKE_OVERLAY_IMAGE.size} khác với ảnh nền {DEFAULT_IMAGE_DIMENSIONS}. Sẽ resize ảnh stroke.")
            GLOBAL_STROKE_OVERLAY_IMAGE = GLOBAL_STROKE_OVERLAY_IMAGE.resize(DEFAULT_IMAGE_DIMENSIONS, Image.LANCZOS)
        print(f"DEBUG: Đã tải ảnh stroke overlay: {STROKE_IMAGE_PATH} với kích thước {GLOBAL_STROKE_OVERLAY_IMAGE.size[0]}x{GLOBAL_STROKE_OVERLAY_IMAGE.size[1]}.")
    except FileNotFoundError:
        print(f"LỖI STROKE: Không tìm thấy ảnh stroke overlay '{STROKE_IMAGE_PATH}'. Sẽ bỏ qua stroke này.")
        GLOBAL_STROKE_OVERLAY_IMAGE = None
    except Exception as e:
        print(f"LỖỖI STROKE: Lỗi khi mở ảnh stroke overlay '{STROKE_IMAGE_PATH}': {e}. Sẽ bỏ qua stroke này.")
        GLOBAL_STROKE_OVERLAY_IMAGE = None

    print("DEBUG: Đã hoàn tất tải các tài nguyên tĩnh.")

async def _get_and_process_avatar(member_avatar_url, avatar_size, cache):
    """Tải và xử lý avatar, có dùng cache và áp dụng mask tròn.
       Trả về ảnh avatar đã mask và bytes gốc của avatar.
    """
    avatar_bytes = None
    # Kiểm tra cache
    if member_avatar_url in cache and (asyncio.get_event_loop().time() - cache[member_avatar_url]['timestamp']) < CACHE_TTL:
        avatar_bytes = cache[member_avatar_url]['data']
        print(f"DEBUG: Lấy avatar từ cache cho {member_avatar_url}.")
    else:
        print(f"DEBUG: Đang tải avatar từ URL: {member_avatar_url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(member_avatar_url)) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()
                        cache[member_avatar_url] = {'data': avatar_bytes, 'timestamp': asyncio.get_event_loop().time()}
                        print(f"DEBUG: Đã tải và lưu avatar vào cache.")
                    else:
                        print(f"LỖI AVATAR: Không thể tải avatar. Trạng thái HTTP: {resp.status}. Sử dụng avatar màu xám mặc định.")
        except Exception as e:
            print(f"LỖI AVATAR: Lỗi mạng khi tải avatar: {e}. Sử dụng avatar màu xám mặc định.")

    # Mở ảnh avatar hoặc tạo ảnh mặc định nếu không tải được
    if avatar_bytes:
        data = io.BytesIO(avatar_bytes)
        avatar_img = Image.open(data).convert("RGBA")
    else:
        avatar_img = Image.new('RGBA', (avatar_size, avatar_size), color=(100, 100, 100, 255))

    # Resize avatar về kích thước mong muốn
    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

    # *** Áp dụng mask hình tròn bằng code (sử dụng Image.composite để đảm bảo trong suốt) ***
    transparent_avatar_bg = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
    mask = Image.new('L', (avatar_size, avatar_size), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)
    masked_avatar = Image.composite(avatar_img, transparent_avatar_bg, mask)
    
    print(f"DEBUG: Đã áp dụng mask tròn cho avatar bằng Image.composite.")

    return masked_avatar, avatar_bytes


def _draw_text_with_shadow(draw_obj, text, font, x, y, main_color, shadow_color, offset_x, offset_y):
    """Vẽ văn bản với hiệu ứng đổ bóng đơn giản với offset tùy chỉnh."""
    draw_obj.text((int(x + offset_x), int(y + offset_y)), text, font=font, fill=shadow_color)
    draw_obj.text((int(x), int(y)), text, font=font, fill=main_color)

def _draw_simple_decorative_line(draw_obj, img_width, line_y, line_color_rgb, actual_line_length):
    """Vẽ thanh line đơn giản với độ dài tùy chỉnh, căn giữa."""
    line_x1 = int(img_width / 2 - actual_line_length / 2)
    line_x2 = int(img_width / 2 + actual_line_length / 2)

    draw_obj.line(
        [(line_x1, int(line_y)), (line_x2, int(line_y))],
        fill=line_color_rgb,
        width=LINE_THICKNESS
    )

def _get_text_width(text, font, draw_obj):
    """Tính toán chiều rộng của văn bản."""
    return draw_obj.textlength(text, font=font)

def _get_text_height(text, font, draw_obj):
    """Tính toán chiều cao của văn bản."""
    bbox = draw_obj.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]

def is_basic_char(char):
    """
    Kiểm tra xem một ký tự có phải là chữ cái (Tiếng Việt hoặc Latin), số hoặc dấu câu cơ bản không.
    Bổ sung thêm các ký tự đặc biệt thường dùng.
    """
    if 'a' <= char <= 'z' or 'A' <= char <= 'Z':
        return True
    if '0' <= char <= '9':
        return True
    
    special_chars_to_keep = """.,?!;:'"()[]{}<>+-*/=@_|=~`!^*""" + '\\'
    if char in special_chars_to_keep or char.isspace():
        return True
    
    unicode_ord = ord(char)
    if (0x00C0 <= unicode_ord <= 0x017F) or \
       (0x1EA0 <= unicode_ord <= 0x1EFF):
        return True
    
    return False

def process_text_for_drawing(original_text, main_font, symbol_font, replacement_char='✦', temp_draw_obj=None):
    """
    Xử lý văn bản để vẽ.
    Các ký tự cơ bản dùng main_font. Các ký tự không cơ bản dùng replacement_char với symbol_font.
    Trả về danh sách các (ký tự, font) và chiều rộng tổng cộng.
    """
    processed_parts = []
    total_width = 0
    
    if temp_draw_obj is None:
        temp_draw_obj = ImageDraw.Draw(Image.new('RGBA', (1, 1))) 

    for char in original_text:
        if is_basic_char(char):
            processed_parts.append((char, main_font))
            total_width += temp_draw_obj.textlength(char, font=main_font)
        else:
            processed_parts.append((replacement_char, symbol_font))
            total_width += temp_draw_obj.textlength(replacement_char, font=symbol_font)
    
    return processed_parts, total_width


async def create_welcome_image(member):
    # 1. Sử dụng font đã tải sẵn và kiểm tra lại (chỉ để đảm bảo)
    if not all([GLOBAL_FONT_WELCOME, GLOBAL_FONT_NAME, GLOBAL_FONT_SYMBOL]):
        print("CẢNH BÁO: Font chưa được tải sẵn. Đang cố gắng tải lại. (Điều này không nên xảy ra sau on_ready)")
        _load_static_assets() # Tải lại nếu chưa được tải (fallback)

    font_welcome = GLOBAL_FONT_WELCOME
    font_name = GLOBAL_FONT_NAME
    font_symbol = GLOBAL_FONT_SYMBOL

    # 2. Tạo bản sao của ảnh nền từ đối tượng đã tải trước
    if GLOBAL_BACKGROUND_IMAGE:
        img = GLOBAL_BACKGROUND_IMAGE.copy()
    else:
        print("LỖI: Ảnh nền chưa được tải sẵn. Tạo ảnh nền mặc định.")
        img = Image.new('RGBA', DEFAULT_IMAGE_DIMENSIONS, color=(0, 0, 0, 255))
        
    img_width, img_height = img.size
    draw = ImageDraw.Draw(img)

    # Tính toán offset bóng đổ dựa trên kích thước ảnh (khoảng 0.5% của chiều rộng/chiều cao)
    shadow_offset_x = int(img_width * 0.005)
    shadow_offset_y = int(img_height * 0.005)

    # 3. Lấy và xử lý Avatar (Đã được cắt tròn nhờ mask được tạo trong _get_and_process_avatar)
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    masked_avatar, avatar_bytes = await _get_and_process_avatar(avatar_url, AVATAR_SIZE, avatar_cache)

    # Xác định màu chủ đạo từ avatar
    # Sửa đổi: Hàm get_dominant_color giờ trả về 3 giá trị
    dominant_color_from_avatar, original_image_mode, processed_avatar_io = None, None, None
    if avatar_bytes:
        dominant_color_from_avatar, original_image_mode, processed_avatar_io = await get_dominant_color(avatar_bytes, color_count=20)
    if dominant_color_from_avatar is None:
        dominant_color_from_avatar = (0, 252, 233) # Default Cyan

    # Điều chỉnh màu sắc cho viền và chữ dựa trên màu chủ đạo được chọn
    stroke_color_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=1.1,
        saturation_factor=3.0,
        clamp_min_l=0.2,
        clamp_max_l=0.85
    )
    stroke_color = (*stroke_color_rgb, 255) # Màu của viền avatar và chữ tên (thêm alpha 255)

    # 4. Tính toán vị trí Avatar và các phần tử
    avatar_x = int(img_width / 2 - AVATAR_SIZE / 2)
    avatar_y = int(img_height * 0.36) - AVATAR_SIZE // 2
    y_offset_from_avatar = 20

    # *** VẼ HÌNH TRÒN BÁN TRONG SUỐT PHÍA SAU AVATAR ***
    background_circle_color_rgba = stroke_color_rgb + (128,) # 128 là giá trị alpha cho 50% opacity
    circle_overlay_layer = Image.new('RGBA', img.size, (0,0,0,0))
    draw_circle_overlay = ImageDraw.Draw(circle_overlay_layer)
    draw_circle_overlay.ellipse(
        (avatar_x, avatar_y, avatar_x + AVATAR_SIZE, avatar_y + AVATAR_SIZE), 
        fill=background_circle_color_rgba
    )
    img = Image.alpha_composite(img, circle_overlay_layer)
    print(f"DEBUG: Đã vẽ hình tròn bán trong suốt phía sau avatar.")

    # --- 5. Dán ảnh stroke PNG đã tô màu (sử dụng GLOBAL_STROKE_OVERLAY_IMAGE) ---
    if GLOBAL_STROKE_OVERLAY_IMAGE:
        tint_layer = Image.new('RGBA', GLOBAL_STROKE_OVERLAY_IMAGE.size, (*stroke_color_rgb, 255))
        final_stroke_layer = Image.composite(tint_layer, Image.new('RGBA', GLOBAL_STROKE_OVERLAY_IMAGE.size, (0,0,0,0)), GLOBAL_STROKE_OVERLAY_IMAGE)
        img.paste(final_stroke_layer, (0, 0), final_stroke_layer)
    else:
        print(f"CẢNH BÁO: Không có ảnh stroke overlay được tải trước. Sẽ bỏ qua stroke này.")

    # --- 6. Dán Avatar (đã được cắt tròn bởi mask trong _get_and_process_avatar) ---
    img.paste(masked_avatar, (avatar_x, avatar_y), masked_avatar)

    # 7. Vẽ chữ WELCOME
    welcome_text = "WELCOME"
    welcome_text_width = draw.textlength(welcome_text, font=font_welcome)
    welcome_text_x = int((img_width - welcome_text_width) / 2)
    welcome_text_y_pos = int(avatar_y + AVATAR_SIZE + y_offset_from_avatar) # Vị trí Y cho WELCOME
    
    # Tạo màu đổ bóng cho chữ WELCOME
    shadow_color_welcome_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=0.5,
        saturation_factor=2.5,
        clamp_min_l=0.25,
        clamp_max_l=0.55
    )
    _draw_text_with_shadow(
        draw, welcome_text, font_welcome, welcome_text_x, welcome_text_y_pos,
        (255, 255, 255), (*shadow_color_welcome_rgb, 255), shadow_offset_x, shadow_offset_y
    )

    # 8. Vẽ tên người dùng
    name_text_raw = member.display_name
    temp_draw_for_text_calc = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    processed_name_parts, name_text_width = process_text_for_drawing(
        name_text_raw, font_name, font_symbol, replacement_char='✦', temp_draw_obj=temp_draw_for_text_calc
    )
    
    max_chars_for_name = 25
    if name_text_width > img_width * 0.8:
        avg_char_width = name_text_width / len(processed_name_parts) if processed_name_parts else 1
        chars_to_remove = int((name_text_width - img_width * 0.8) / avg_char_width) + 3
        if len(processed_name_parts) > chars_to_remove and len(processed_name_parts) > 3:
            processed_name_parts = processed_name_parts[:-chars_to_remove]
            processed_name_parts.append(('...', font_name))
            name_text_width = 0
            for char, font_to_use in processed_name_parts:
                name_text_width += temp_draw_for_text_calc.textlength(char, font=font_to_use)


    name_text_x = int((img_width - name_text_width) / 2)
    welcome_bbox_for_height = draw.textbbox((0, 0), welcome_text, font=font_welcome)
    welcome_actual_height = welcome_bbox_for_height[3] - welcome_bbox_for_height[1]
    name_text_y = int(welcome_text_y_pos + welcome_actual_height + 10)

    shadow_color_name_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=0.5,
        saturation_factor=2.5,
        clamp_min_l=0.25,
        clamp_max_l=0.55
    )
    shadow_color_name = (*shadow_color_name_rgb, 255)

    current_x = float(name_text_x)
    for char, font_to_use in processed_name_parts:
        draw.text((int(current_x + shadow_offset_x), int(name_text_y + shadow_offset_y)), char, font=font_to_use, fill=shadow_color_name)
        draw.text((int(current_x), int(name_text_y)), char, font=font_to_use, fill=stroke_color)
        current_x += draw.textlength(char, font=font_to_use)

    # 9. Vẽ thanh line trang trí
    name_actual_height = _get_text_height("M", font_name, draw)
    line_y = int(name_text_y + name_actual_height + LINE_VERTICAL_OFFSET_FROM_NAME)
    line_color_rgb = stroke_color_rgb
    actual_line_length = int(name_text_width * LINE_LENGTH_FACTOR)
    _draw_simple_decorative_line(draw, img_width, line_y, line_color_rgb, actual_line_length)

    # 10. Lưu ảnh và trả về
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    # Trả về cả image_bytes, original_image_mode, và processed_avatar_io
    return img_byte_arr, original_image_mode, processed_avatar_io

# --- Các tác vụ của bot ---
@tasks.loop(minutes=1)
async def activity_heartbeat():
    sleep_duration = random.randint(1 * 60, 3 * 60)
    print(
        f"DEBUG: Tác vụ activity_heartbeat đang ngủ {sleep_duration // 60} phút để chuẩn bị cập nhật trạng thái..."
    )
    await asyncio.sleep(sleep_duration)

    activities = [
        discord.Activity(type=discord.ActivityType.watching,
                         name=f"Dawn_wibu phá đảo tựa game mới "),
        discord.Activity(type=discord.ActivityType.listening,
                         name=f"Bài TRÌNH "),
        discord.Activity(type=discord.ActivityType.playing,
                         name=f"Minecraft cùng Anh Em "),
    ]

    try:
        new_activity = random.choice(activities)
        await bot.change_presence(activity=new_activity)
        print(
            f"DEBUG: Đã cập nhật trạng thái bot thành: {new_activity.name} ({new_activity.type.name})."
        )

    except Exception as e:
        print(
            f"LỖI ACTIVITY_HEARTBEAT: Không thể cập nhật trạng thái bot: {e}")

@activity_heartbeat.before_loop
async def before_activity_heartbeat():
    await bot.wait_until_ready()
    print("DEBUG: activity_heartbeat task chờ bot sẵn sàng.")

CHANNEL_ID_FOR_RANDOM_MESSAGES = 1379789952610467971 # Đảm bảo đây là ID kênh hợp lệ của bạn

RANDOM_MESSAGES = [
    "Chào mọi người! ✨ Chúc một ngày tốt lành!",
    "Đang online đây! Có ai cần gì không? 🤖",
    "Thế giới thật tươi đẹp phải không? 💖",
    "Gửi chút năng lượng tích cực đến tất cả! 💪",
    "Đừng quên thư giãn nhé! 😌",
    "Tôi là bot thông minh nhất quả đất! 💡",
    "Ngày mới năng động nha mọi người! 🚀",
    "Có câu hỏi khó nào cần tôi giải đáp không? 🧠"
]

@tasks.loop(minutes=1)
async def random_message_sender():
    send_interval = random.randint(2 * 60, 5 * 60)
    print(f"DEBUG: Tác vụ random_message_sender sẽ gửi tin nhắn sau {send_interval // 60} phút.")
    await asyncio.sleep(send_interval)

    channel = bot.get_channel(CHANNEL_ID_FOR_RANDOM_MESSAGES)
    if channel:
        if isinstance(channel, discord.TextChannel):
            if channel.permissions_for(channel.guild.me).send_messages:
                message_to_send = random.choice(RANDOM_MESSAGES)
                try:
                    await channel.send(message_to_send)
                    print(f"DEBUG: Đã gửi tin nhắn định kỳ: '{message_to_send}' vào kênh {channel.name} (ID: {CHANNEL_ID_FOR_RANDOM_MESSAGES}).")
                except discord.errors.Forbidden:
                    print(f"LỖI QUYỀN: Bot không có quyền gửi tin nhắn trong kênh {channel.name} (ID: {CHANNEL_ID_FOR_RANDOM_MESSAGES}).")
                except Exception as e:
                    print(f"LỖI GỬI TIN NHẮN: Không thể gửi tin nhắn định kỳ vào kênh {CHANNEL_ID_FOR_RANDOM_MESSAGES}: {e}")
            else:
                print(f"LỖI QUYỀN: Bot không có quyền 'gửi tin nhắn' trong kênh {channel.name} (ID: {CHANNEL_ID_FOR_RANDOM_MESSAGES}).")
        else:
            print(f"LỖI KÊNH: Kênh với ID {CHANNEL_ID_FOR_RANDOM_MESSAGES} không phải là kênh văn bản.")
    else:
        print(f"LỖI KÊNH: Không tìm thấy kênh với ID {CHANNEL_ID_FOR_RANDOM_MESSAGES}. Vui lòng kiểm tra lại ID hoặc bot chưa có quyền truy cập kênh đó.")

@random_message_sender.before_loop
async def before_random_message_sender():
    await bot.wait_until_ready()
    print("DEBUG: random_message_sender task chờ bot sẵn sàng.")

# --- Các sự kiện của bot ---
@bot.event
async def on_ready():
    """Xử lý sự kiện khi bot sẵn sàng."""
    print(f'{bot.user} đã sẵn sàng! 🎉')
    print('Bot đã online và có thể hoạt động.')
    try:
        # Xóa các lệnh cũ trước khi đồng bộ để tránh nhân đôi
        bot.tree.clear_commands(guild=None) # Xóa lệnh toàn cầu hoặc guild cụ thể nếu cần
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh slash commands toàn cầu.")
    except Exception as e:
        print(
            f"LỖI ĐỒNG BỘ: Lỗi khi đồng bộ slash commands: {e}. Vui lòng kiểm tra quyền 'applications.commands' cho bot trên Discord Developer Portal."
        )

    # Tải tất cả các tài nguyên tĩnh khi bot sẵn sàng (chỉ một lần)
    _load_static_assets()
    print("DEBUG: Đã tải tất cả tài nguyên tĩnh khi bot sẵn sàng.")

    if not activity_heartbeat.is_running():
        activity_heartbeat.start()
        print("DEBUG: Đã bắt đầu tác vụ thay đổi trạng thái để giữ hoạt động.")

    if not random_message_sender.is_running():
        random_message_sender.start()
        print("DEBUG: Đã bắt đầu tác vụ gửi tin nhắn định kỳ.")


@bot.event
async def on_member_join(member):
    channel_id = 1322848542758277202 # Đảm bảo đây là ID kênh chào mừng hợp lệ của bạn

    channel = bot.get_channel(channel_id)

    if channel is None:
        print(
            f"LỖI KÊNH: Không tìm thấy kênh với ID {channel_id}. Vui lòng kiểm tra lại ID kênh hoặc bot chưa có quyền truy cập kênh đó."
        )
        return

    if not channel.permissions_for(member.guild.me).send_messages or \
       not channel.permissions_for(member.guild.me).attach_files:
        print(
            f"LỖI QUYỀN: Bot không có quyền gửi tin nhắn hoặc đính kèm file trong kênh {channel.name} (ID: {channel_id}). Vui lòng kiểm tra lại quyền của bot trong Discord."
        )
        return

    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member.display_name}...")
        # Tạo ảnh welcome, nhưng không cần debug chi tiết ở đây nữa
        # Chỉ lấy image_bytes, các giá trị khác có thể bỏ qua
        image_bytes, _, _ = await create_welcome_image(member)
        await channel.send(
            f"**<a:cat2:1323314096040448145>** **Chào mừng {member.mention} đã đến {member.guild.name}**",
            file=discord.File(fp=image_bytes, filename='welcome.png'))
        print(f"Đã gửi ảnh chào mừng thành công cho {member.display_name}!")
    except discord.errors.HTTPException as e:
        print(
            f"LỖI HTTP DISCORD: Lỗi khi gửi ảnh chào mừng (có thể do giới hạn tốc độ hoặc quyền): {e}"
        )
        await channel.send(
            f"Chào mừng {member.mention} đã đến với {member.guild.name}! (Có lỗi khi tạo ảnh chào mừng, xin lỗi!)"
        )
    except Exception as e:
        print(f"LỖỖI CHÀO MỪNG KHÁC: Lỗi khi tạo hoặc gửi ảnh chào mừng: {e}")
        await channel.send(
            f"Chào mừng {member.mention} đã đến với {member.guild.name}!")

# --- Slash Command để TEST tạo ảnh welcome (có debug) ---
@bot.tree.command(name="testwelcome", description="Tạo và gửi ảnh chào mừng cho người dùng (có thông tin debug).")
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True) # Chỉ quản trị viên mới dùng được lệnh này
async def testwelcome_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True) # Bot sẽ "đang nghĩ" để tránh timeout

    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member_to_test.display_name}...")
        # Lấy cả image_bytes, original_image_mode, và processed_avatar_io
        image_bytes, original_image_mode, processed_avatar_io = await create_welcome_image(member_to_test)
        
        # Thêm các dòng print này ngay sau dòng trên
        print(f"DEBUG_TESTWELCOME: original_image_mode = {original_image_mode}")
        print(f"DEBUG_TESTWELCOME: processed_avatar_io.tell() = {processed_avatar_io.tell() if processed_avatar_io else 'None'}")
        
        # Gửi ảnh welcome chính
        files_to_send = [discord.File(fp=image_bytes, filename='welcome_test.png')]
        
        # Chuẩn bị tin nhắn debug
        debug_message = (
            f"**DEBUG INFO for {member_to_test.display_name}'s Avatar:**\n"
            f"**Chế độ màu ảnh gốc bot nhận được:** `{original_image_mode}`\n"
            f"**Link avatar Discord:** <{member_to_test.avatar.url if member_to_test.avatar else member_to_test.default_avatar.url}>\n"
            f"Nếu chế độ màu là `RGB` hoặc `P` (palette), có thể Discord đã chuyển đổi ảnh trong suốt của bạn thành định dạng không trong suốt trước khi bot lấy về. Nếu là `RGBA`, thì bot đã xử lý kênh alpha."
        )

        # Đính kèm debug_avatar.png nếu có
        if processed_avatar_io and processed_avatar_io.tell() > 0: # Check if BytesIO contains data
            processed_avatar_io.seek(0) # Reset con trỏ về đầu
            files_to_send.append(discord.File(fp=processed_avatar_io, filename='debug_avatar_processed_by_colorthief.png'))
            debug_message += "\nĐây là ảnh avatar (đã được làm phẳng lên nền trắng nếu là PNG trong suốt) mà bot dùng để xác định màu sắc:"

        # --- Thêm try-except block cho followup.send ---
        try:
            await interaction.followup.send(content=debug_message, files=files_to_send)
            print(f"DEBUG: Đã gửi ảnh test chào mừng và thông tin debug cho {member_to_test.display_name} thành công trong Discord.")
        except discord.errors.Forbidden:
            print(f"LỖI DISCORD: Bot thiếu quyền 'Gửi tin nhắn' hoặc 'Đính kèm tệp' trong kênh này cho lệnh testwelcome. Vui lòng kiểm tra lại quyền.")
            await interaction.followup.send("Bot không có đủ quyền để gửi tin nhắn debug hoặc tệp đính kèm trong kênh này. Vui lòng kiểm tra quyền hạn của bot.")
        except Exception as send_error:
            print(f"LỖI KHI GỬI FOLLOWUP: {send_error}")
            await interaction.followup.send(f"Có lỗi xảy ra khi gửi thông tin debug: `{send_error}`. Vui lòng kiểm tra console của bot để biết thêm chi tiết.")
        print(f"DEBUG: Đã hoàn tất xử lý lệnh testwelcome cho {member_to_test.display_name}.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test: {e}")
        print(f"LỖỖI TEST: Có lỗi khi tạo hoặc gửi ảnh test: {e}")

# --- Slash Command mới: /welcomepreview (xuất ảnh hoàn chỉnh, không debug) ---
@bot.tree.command(name="welcomepreview", description="Tạo và gửi ảnh chào mừng hoàn chỉnh cho người dùng (không có debug).")
@app_commands.describe(user="Người dùng bạn muốn xem trước (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True) # Chỉ quản trị viên mới dùng được lệnh này
async def welcomepreview_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True) # Bot sẽ "đang nghĩ" để tránh timeout

    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng hoàn chỉnh cho {member_to_test.display_name}...")
        # Chỉ lấy image_bytes, các giá trị debug khác không cần
        image_bytes, _, _ = await create_welcome_image(member_to_test)
        
        # Gửi ảnh welcome chính, không kèm debug
        file_to_send = discord.File(fp=image_bytes, filename='welcome_preview.png')
        
        try:
            await interaction.followup.send(content=f"Đây là ảnh chào mừng cho {member_to_test.mention}:", files=[file_to_send])
            print(f"DEBUG: Đã gửi ảnh chào mừng hoàn chỉnh cho {member_to_test.display_name} thành công trong Discord.")
        except discord.errors.Forbidden:
            print(f"LỖI DISCORD: Bot thiếu quyền 'Gửi tin nhắn' hoặc 'Đính kèm tệp' trong kênh này cho lệnh welcomepreview. Vui lòng kiểm tra lại quyền.")
            await interaction.followup.send("Bot không có đủ quyền để gửi ảnh xem trước trong kênh này. Vui lòng kiểm tra quyền hạn của bot.")
        except Exception as send_error:
            print(f"LỖI KHI GỬI FOLLOWUP (preview): {send_error}")
            await interaction.followup.send(f"Có lỗi xảy ra khi gửi ảnh xem trước: `{send_error}`. Vui lòng kiểm tra console của bot để biết thêm chi tiết.")
        print(f"DEBUG: Đã hoàn tất xử lý lệnh welcomepreview cho {member_to_test.display_name}.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh xem trước: {e}")
        print(f"LỖỖI PREVIEW: Có lỗi khi tạo hoặc gửi ảnh xem trước: {e}")

# --- Slash Command mới: /skibidi ---
@bot.tree.command(name="skibidi", description="Dẫn tới Dawn_wibu.")
async def skibidi(interaction: discord.Interaction):
    await interaction.response.send_message(
        " <a:cat2:1323314096040448145>**✦** *** [AN BA TO KOM](https://dawnwibu.carrd.co) *** **✦** <a:cat3:1323314218476372122>"
    )

# --- Khởi chạy Flask và Bot Discord ---
async def start_bot_and_flask():
    """Hàm async để khởi động cả Flask và bot Discord."""
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True # Đảm bảo luồng Flask tự dừng khi chương trình chính dừng
    flask_thread.start()

    print(
        "Đang đợi 5 giây trước khi khởi động bot Discord để tránh rate limit..."
    )
    await asyncio.sleep(5)
    print("Bắt đầu khởi động bot Discord...")

    try:
        await bot.start(TOKEN)
    except discord.errors.HTTPException as e:
        if e.status == 429:
            print(f"Lỗi 429 Too Many Requests khi đăng nhập: {e.text}")
            print(
                "Có vẻ như Discord đã giới hạn tốc độ đăng nhập của bạn. Vui lòng đợi một thời gian (ví dụ: 5-10 phút) rồi thử lại."
            )
            print(
                "Đảm bảo bạn không khởi động lại bot quá thường xuyên hoặc có nhiều phiên bản bot đang chạy."
            )
        else:
            print(f"Một lỗi HTTP khác đã xảy ra khi đăng nhập: {e}")
            raise
    except Exception as e:
        print(f"Một lỗi không xác định đã xảy ra: {e}")

if __name__ == '__main__':
    if not TOKEN:
        print(
            "Lỗi: TOKEN không được tìm thấy. Vui lòng thiết lập biến môi trường 'DISCORD_BOT_TOKEN' hoặc 'TOKEN'."
        )
    else:
        asyncio.run(start_bot_and_flask())
