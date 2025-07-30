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
import traceback # Import thư viện traceback để in chi tiết lỗi

# Dòng kiểm tra này sẽ xuất hiện ngay khi bot bắt đầu chạy
print("--- BOT IS RUNNING NEW CODE! ---")

# --- Khởi tạo Flask app ---
app = Flask(__协name__)

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

# --- BIẾN CẤU HÌNH CỦA BOT ---
DEFAULT_IMAGE_DIMENSIONS = (872, 430)
AVATAR_SIZE = 210
LINE_VERTICAL_OFFSET_FROM_NAME = 10
LINE_LENGTH_FACTOR = 0.65
GUILD_ID = 913046733796311040 # ID của server bạn muốn bot hoạt động

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

            if (l < 0.5 and s < 0.25) or (l > 0.90): # Loại bỏ màu quá tối/xám hoặc quá sáng
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
            # Fallback nếu không có màu phù hợp theo tiêu chí, chọn màu sáng nhất nhưng không phải gần đen
            best_fallback_color = (0, 252, 233) # Vẫn là Cyan mặc định
            max_l_fallback = -1
            for color in palette:
                # Tránh các màu gần như đen hoàn toàn khi fallback
                if not (color[0] < 30 and color[1] < 30 and color[2] < 30):
                    _, _, l = rgb_to_hsl(*color)
                    if l > max_l_fallback:
                        max_l_fallback = l
                        best_fallback_color = color
            dominant_color = best_fallback_color

        return dominant_color, img_pil.mode, img_temp_io

    except Exception as e:
        print(f"LỖI COLORTHIEF: Không thể lấy bảng màu từ avatar: {e}")
        traceback.print_exc() # In chi tiết lỗi
        # Trả về default color, mode và một BytesIO trống rỗng nếu lỗi
        return (0, 252, 233), 'UNKNOWN', io.BytesIO()

avatar_cache = {}
CACHE_TTL = 300 # Thời gian sống của cache avatar (giây)

# --- CÁC HẰNG SỐ DÙNG TRONG TẠO ẢNH ---
FONT_MAIN_PATH = "1FTV-Designer.otf"
FONT_SYMBOL_PATH = "subset-DejaVuSans.ttf"
WELCOME_FONT_SIZE = 60
NAME_FONT_SIZE = 34
BACKGROUND_IMAGE_PATH = "welcome.png"
STROKE_IMAGE_PATH = "stroke.png"
AVATAR_MASK_IMAGE_PATH = "avatar.png"
LINE_THICKNESS = 3 # Độ dày của line dưới tên


# --- GLOBAL VARIABLES FOR PRE-LOADED ASSETS ---
# Sẽ được tải một lần khi bot khởi động
GLOBAL_FONT_WELCOME = None
GLOBAL_FONT_NAME = None
GLOBAL_FONT_SYMBOL = None
GLOBAL_BACKGROUND_IMAGE = None
GLOBAL_STROKE_OVERLAY_IMAGE = None
GLOBAL_AVATAR_MASK_IMAGE = None

# --- CÁC HÀM HỖ TRỢ CHO create_welcome_image ---

def _load_static_assets():
    """Tải font, ảnh nền, ảnh stroke một lần duy nhất khi bot khởi động."""
    global GLOBAL_FONT_WELCOME, GLOBAL_FONT_NAME, GLOBAL_FONT_SYMBOL
    global GLOBAL_BACKGROUND_IMAGE, GLOBAL_STROKE_OVERLAY_IMAGE, GLOBAL_AVATAR_MASK_IMAGE

    print("DEBUG: Đang tải các tài nguyên tĩnh (fonts, ảnh nền, stroke, mask)...")

    # Tải Fonts
    try:
        GLOBAL_FONT_WELCOME = ImageFont.truetype(FONT_MAIN_PATH, WELCOME_FONT_SIZE)
        GLOBAL_FONT_NAME = ImageFont.truetype(FONT_MAIN_PATH, NAME_FONT_SIZE)
        print(f"DEBUG: Đã tải font chính thành công: {FONT_MAIN_PATH}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font chính '{FONT_MAIN_PATH}'. Sử dụng Arial. Chi tiết: {e}")
        traceback.print_exc()
        try:
            GLOBAL_FONT_WELCOME = ImageFont.truetype("arial.ttf", WELCOME_FONT_SIZE)
            GLOBAL_FONT_NAME = ImageFont.truetype("arial.ttf", NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font Arial.ttf cho văn bản chính (fallback).")
        except Exception:
            GLOBAL_FONT_WELCOME = ImageFont.load_default().font_variant(size=WELCOME_FONT_SIZE)
            GLOBAL_FONT_NAME = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font mặc định của Pillow cho văn bản chính (fallback cuối cùng).")
    
    try:
        GLOBAL_FONT_SYMBOL = ImageFont.truetype(FONT_SYMBOL_PATH, NAME_FONT_SIZE)
        print(f"DEBUG: Đã tải font biểu tượng thành công: {FONT_SYMBOL_PATH}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font biểu tượng '{FONT_SYMBOL_PATH}'. Sử dụng font mặc định cho biểu tượng. Chi tiết: {e}")
        traceback.print_exc()
        GLOBAL_FONT_SYMBOL = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
        print("DEBUG: Đã sử dụng font mặc định của Pillow cho biểu tượng (fallback).")

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
        traceback.print_exc()
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
        traceback.print_exc()
        GLOBAL_STROKE_OVERLAY_IMAGE = None

    # Tải mask avatar
    try:
        temp_mask = Image.open(AVATAR_MASK_IMAGE_PATH).convert("L")
        GLOBAL_AVATAR_MASK_IMAGE = temp_mask.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
        print(f"DEBUG: Đã tải và resize mask avatar: {AVATAR_MASK_IMAGE_PATH} với kích thước {GLOBAL_AVATAR_MASK_IMAGE.size[0]}x{GLOBAL_AVATAR_MASK_IMAGE.size[1]}.")
    except FileNotFoundError:
        print(f"LỖI MASK AVATAR: Không tìm thấy ảnh mask '{AVATAR_MASK_IMAGE_PATH}'. Avatar sẽ không được bo tròn.")
        GLOBAL_AVATAR_MASK_IMAGE = None
    except Exception as e:
        print(f"LỖI MASK AVATAR: Lỗi khi mở ảnh mask '{AVATAR_MASK_IMAGE_PATH}': {e}. Avatar sẽ không được bo tròn.")
        traceback.print_exc()
        GLOBAL_AVATAR_MASK_IMAGE = None

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
            traceback.print_exc()

    # Mở ảnh avatar hoặc tạo ảnh mặc định nếu không tải được
    if avatar_bytes:
        data = io.BytesIO(avatar_bytes)
        try:
            avatar_img = Image.open(data).convert("RGBA")
        except Exception as e:
            print(f"LỖI AVATAR: Không thể mở hoặc chuyển đổi định dạng avatar đã tải: {e}. Tạo ảnh xám mặc định.")
            traceback.print_exc()
            avatar_img = Image.new('RGBA', (avatar_size, avatar_size), color=(100, 100, 100, 255))
    else:
        avatar_img = Image.new('RGBA', (avatar_size, avatar_size), color=(100, 100, 100, 255))

    # Resize avatar về kích thước mong muốn
    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

    # Áp dụng mask hình tròn bằng GLOBAL_AVATAR_MASK_IMAGE
    if GLOBAL_AVATAR_MASK_IMAGE:
        # GLOBAL_AVATAR_MASK_IMAGE đã được resize sẵn
        masked_avatar = Image.composite(avatar_img, Image.new('RGBA', avatar_img.size, (0, 0, 0, 0)), GLOBAL_AVATAR_MASK_IMAGE)
        print(f"DEBUG: Đã áp dụng mask tròn cho avatar bằng GLOBAL_AVATAR_MASK_IMAGE.")
    else:
        # Fallback nếu không tải được mask, vẫn trả về avatar đã resize
        masked_avatar = avatar_img
        print(f"CẢNH BÁO: Không có mask avatar được tải sẵn. Trả về avatar không bo tròn.")
    
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
    
    special_chars_to_keep = """.,?!;:'"()[]{}<>+-*/=@_|=~`!^*""" + '\\' # Thêm các dấu câu, ký hiệu thông thường
    if char in special_chars_to_keep or char.isspace():
        return True
    
    # Phạm vi Unicode cho các ký tự Tiếng Việt (Latin-1 Supplement, Latin Extended-A/B, Vietnamese)
    unicode_ord = ord(char)
    if (0x00C0 <= unicode_ord <= 0x017F) or \
       (0x1EA0 <= unicode_ord <= 0x1EFF) or \
       (0x20AB == unicode_ord) : # Thêm ký tự ₫ (đồng) nếu cần
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
            print(f"CẢNH BÁO FONT: Ký tự '{char}' (Unicode: {ord(char)}) không được coi là ký tự cơ bản và sẽ được thay thế bằng '{replacement_char}'.")
            processed_parts.append((replacement_char, symbol_font))
            total_width += temp_draw_obj.textlength(replacement_char, font=symbol_font)
    
    return processed_parts, total_width


async def create_welcome_image(member):
    # 1. Sử dụng font đã tải sẵn và kiểm tra lại (chỉ để đảm bảo)
    if not all([GLOBAL_FONT_WELCOME, GLOBAL_FONT_NAME, GLOBAL_FONT_SYMBOL, GLOBAL_AVATAR_MASK_IMAGE]):
        print("CẢNH BÁO: Một số tài nguyên chưa được tải sẵn. Đang cố gắng tải lại. (Điều này không nên xảy ra sau on_ready)")
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
    
    # --- THÊM CÁC DÒNG DEBUG NÀY ---
    print(f"DEBUG_POS: Kích thước ảnh: {img_width}x{img_height}")
    print(f"DEBUG_POS: Vị trí Avatar: ({avatar_x}, {avatar_y}) Kích thước: {AVATAR_SIZE}x{AVATAR_SIZE}")
    # --- KẾT THÚC CÁC DÒNG DEBUG ---

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
    
    # --- THÊM CÁC DÒNG DEBUG NÀY ---
    print(f"DEBUG_POS: Welcome Text: '{welcome_text}'")
    print(f"DEBUG_POS: Kích thước Welcome Text: {welcome_text_width}x{_get_text_height(welcome_text, font_welcome, draw)}")
    print(f"DEBUG_POS: Vị trí Welcome Text: ({welcome_text_x}, {welcome_text_y_pos})")
    # --- KẾT THÚC CÁC DÒNG DEBUG ---

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
    
    # Kiểm tra và cắt tên nếu quá dài
    # Sử dụng một tỷ lệ phần trăm của chiều rộng ảnh để quyết định giới hạn
    max_name_width_ratio = 0.8 # Tên không vượt quá 80% chiều rộng ảnh
    if name_text_width > img_width * max_name_width_ratio:
        print(f"CẢNH BÁO: Tên người dùng '{name_text_raw}' quá dài ({name_text_width}px), sẽ bị cắt bớt.")
        # Ước tính số ký tự cần giữ để vừa với 80% chiều rộng
        target_width = img_width * max_name_width_ratio
        current_width = 0
        truncated_parts = []
        for char, font_to_use in processed_name_parts:
            char_width = temp_draw_for_text_calc.textlength(char, font=font_to_use)
            # Giữ chỗ cho "..."
            if current_width + char_width < target_width - temp_draw_for_text_calc.textlength('...', font=font_name):
                truncated_parts.append((char, font_to_use))
                current_width += char_width
            else:
                break
        
        if truncated_parts:
            processed_name_parts = truncated_parts
            processed_name_parts.append(('...', font_name)) # Thêm dấu chấm lửng
            name_text_width = current_width + temp_draw_for_text_calc.textlength('...', font=font_name)
        else:
            # Nếu tên quá ngắn mà vẫn quá giới hạn (ví dụ: một ký tự rất dài), vẫn hiển thị "..."
            processed_name_parts = [('...', font_name)]
            name_text_width = temp_draw_for_text_calc.textlength('...', font=font_name)


    name_text_x = int((img_width - name_text_width) / 2)
    
    # Để tính toán vị trí Y chính xác, lấy chiều cao thực của text WELCOME
    welcome_bbox_for_height = draw.textbbox((0, 0), welcome_text, font=font_welcome)
    welcome_actual_height = welcome_bbox_for_height[3] - welcome_bbox_for_height[1]
    
    name_text_y = int(welcome_text_y_pos + welcome_actual_height + 10) # Khoảng cách 10px giữa WELCOME và tên

    # --- THÊM CÁC DÒNG DEBUG NÀY ---
    print(f"DEBUG_POS: Tên người dùng: '{name_text_raw}'")
    print(f"DEBUG_POS: Kích thước Tên người dùng (ước tính): {name_text_width}x{_get_text_height('M', font_name, draw)}") # Dùng 'M' để ước tính chiều cao trung bình
    print(f"DEBUG_POS: Vị trí Tên người dùng: ({name_text_x}, {name_text_y})")
    # --- KẾT THÚC CÁC DÒNG DEBUG ---

    # Tạo màu đổ bóng cho chữ tên
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
        if font_to_use is None: # Fallback an toàn nếu font bị lỗi
            font_to_use = ImageFont.load_default()
            print(f"LỖI FONT: Font cho ký tự '{char}' là None, sử dụng font mặc định.")

        draw.text((int(current_x + shadow_offset_x), int(name_text_y + shadow_offset_y)), char, font=font_to_use, fill=shadow_color_name)
        draw.text((int(current_x), int(name_text_y)), char, font=font_to_use, fill=stroke_color)
        current_x += draw.textlength(char, font=font_to_use)

    # 9. Vẽ thanh line trang trí dưới tên
    name_actual_height = _get_text_height("M", font_name, draw) # Lấy chiều cao của font tên
    line_y = int(name_text_y + name_actual_height + LINE_VERTICAL_OFFSET_FROM_NAME)
    line_color_rgb = stroke_color_rgb # Màu của line sẽ giống màu stroke avatar
    actual_line_length = int(name_text_width * LINE_LENGTH_FACTOR) # Độ dài của line theo tỷ lệ tên
    _draw_simple_decorative_line(draw, img_width, line_y, line_color_rgb, actual_line_length)
    
    # 10. Chuyển đổi ảnh thành bytes và trả về
    final_buffer = io.BytesIO()
    img.save(final_buffer, format='PNG')
    final_buffer.seek(0)
    return final_buffer

# --- Slash Command: /welcomepreview ---
@bot.tree.command(name="welcomepreview", description="Tạo ảnh chào mừng xem trước (chỉ admin).")
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True) # Chỉ quản trị viên mới dùng được lệnh này
async def welcomepreview_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True) # Bot sẽ "đang nghĩ" để tránh timeout

    try:
        image_buffer = await create_welcome_image(member_to_test)
        await interaction.followup.send(file=discord.File(fp=image_buffer, filename='welcome_preview.png'))
    except discord.errors.Forbidden:
        print(f"LỖI DISCORD: Bot thiếu quyền 'Gửi tin nhắn' hoặc 'Đính kèm tệp' trong kênh này cho lệnh welcomepreview. Vui lòng kiểm tra lại quyền.")
        await interaction.followup.send("Bot không có đủ quyền để gửi ảnh chào mừng. Vui lòng kiểm tra quyền hạn của bot.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi xảy ra khi tạo ảnh chào mừng: `{e}`")
        print(f"LỖI TỔNG QUAN WELCOMEPREVIEW: Có lỗi xảy ra: {e}")
        traceback.print_exc()

# --- Slash Command: /testwelcome ---
@bot.tree.command(name="testwelcome", description="Kiểm tra chức năng tạo ảnh chào mừng.")
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là bạn).")
@app_commands.checks.has_permissions(administrator=True)
async def testwelcome_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True) # Bot sẽ "đang nghĩ" để tránh timeout

    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member_to_test.display_name}...")
        image_buffer = await create_welcome_image(member_to_test)
        
        # Kiểm tra xem image_buffer có dữ liệu không
        if image_buffer is None or image_buffer.tell() == 0:
            raise ValueError("Ảnh chào mừng không được tạo thành công hoặc rỗng.")

        # Thử gửi ảnh
        await interaction.followup.send(content=f"Đây là ảnh chào mừng cho {member_to_test.display_name}:", file=discord.File(fp=image_buffer, filename='welcome.png'))
        print(f"DEBUG: Đã gửi ảnh chào mừng thành công cho {member_to_test.display_name}.")

    except discord.errors.Forbidden:
        print(f"LỖI DISCORD TESTWELCOME: Bot thiếu quyền 'Gửi tin nhắn' hoặc 'Đính kèm tệp' trong kênh này cho lệnh testwelcome. Vui lòng kiểm tra lại quyền.")
        await interaction.followup.send("Bot không có đủ quyền để gửi ảnh chào mừng. Vui lòng kiểm tra quyền hạn của bot.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi xảy ra khi tạo ảnh chào mừng: `{e}`. Vui lòng kiểm tra console của bot để biết thêm chi tiết.")
        print(f"LỖI TỔNG QUAN TESTWELCOME: Có lỗi xảy ra: {e}")
        traceback.print_exc()

# --- Slash Command mới: /debugimage ---
@bot.tree.command(name="debugimage", description="Tạo ảnh chào mừng theo từng bước để debug (chỉ admin).")
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True) # Chỉ quản trị viên mới dùng được lệnh này
async def debugimage_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True) # Bot sẽ "đang nghĩ" để tránh timeout

    try:
        print(f"DEBUG: Bắt đầu quá trình debug ảnh cho {member_to_test.display_name}...")

        # 1. Tải tài nguyên tĩnh nếu chưa có (fallback)
        if not all([GLOBAL_FONT_WELCOME, GLOBAL_FONT_NAME, GLOBAL_FONT_SYMBOL, GLOBAL_AVATAR_MASK_IMAGE, GLOBAL_BACKGROUND_IMAGE, GLOBAL_STROKE_OVERLAY_IMAGE]):
            print("CẢNH BÁO: Một số tài nguyên chưa được tải sẵn trước lệnh debugimage. Đang cố gắng tải lại.")
            _load_static_assets() # Tải lại nếu chưa được tải

        font_welcome = GLOBAL_FONT_WELCOME
        font_name = GLOBAL_FONT_NAME
        font_symbol = GLOBAL_FONT_SYMBOL

        # Khởi tạo ảnh nền
        if GLOBAL_BACKGROUND_IMAGE:
            current_img = GLOBAL_BACKGROUND_IMAGE.copy()
            print(f"DEBUG_STEP: Đã tạo ảnh nền ban đầu từ '{BACKGROUND_IMAGE_PATH}'. Kích thước: {current_img.size}")
        else:
            print(f"LỖI DEBUG_STEP: Ảnh nền '{BACKGROUND_IMAGE_PATH}' không tải được. Tạo ảnh nền mặc định.")
            current_img = Image.new('RGBA', DEFAULT_IMAGE_DIMENSIONS, color=(0, 0, 0, 255))
        
        # Gửi ảnh bước 1: Ảnh nền ban đầu
        buffer_step1 = io.BytesIO()
        current_img.save(buffer_step1, format='PNG')
        buffer_step1.seek(0)
        await interaction.followup.send(content="**Bước 1: Ảnh nền ban đầu**", file=discord.File(fp=buffer_step1, filename='step1_background.png'))
        print(f"DEBUG_STEP: Đã gửi ảnh nền ban đầu.")

        img_width, img_height = current_img.size
        draw = ImageDraw.Draw(current_img)
        shadow_offset_x = int(img_width * 0.005)
        shadow_offset_y = int(img_height * 0.005)

        # Lấy và xử lý Avatar
        avatar_url = member_to_test.avatar.url if member_to_test.avatar else member_to_test.default_avatar.url
        masked_avatar, avatar_bytes = await _get_and_process_avatar(avatar_url, AVATAR_SIZE, avatar_cache)

        # Xác định màu chủ đạo từ avatar
        dominant_color_from_avatar = (0, 252, 233) # Default Cyan
        if avatar_bytes:
            temp_dominant_color, _, _ = await get_dominant_color(avatar_bytes, color_count=20)
            if temp_dominant_color:
                dominant_color_from_avatar = temp_dominant_color
        
        stroke_color_rgb = adjust_color_brightness_saturation(
            dominant_color_from_avatar, brightness_factor=1.1, saturation_factor=3.0, clamp_min_l=0.2, clamp_max_l=0.85
        )
        stroke_color = (*stroke_color_rgb, 255)

        avatar_x = int(img_width / 2 - AVATAR_SIZE / 2)
        avatar_y = int(img_height * 0.36) - AVATAR_SIZE // 2
        y_offset_from_avatar = 20

        # Bước 2: Vẽ hình tròn bán trong suốt phía sau Avatar
        background_circle_color_rgba = stroke_color_rgb + (128,)
        circle_overlay_layer = Image.new('RGBA', current_img.size, (0,0,0,0))
        draw_circle_overlay = ImageDraw.Draw(circle_overlay_layer)
        draw_circle_overlay.ellipse(
            (avatar_x, avatar_y, avatar_x + AVATAR_SIZE, avatar_y + AVATAR_SIZE), 
            fill=background_circle_color_rgba
        )
        current_img = Image.alpha_composite(current_img, circle_overlay_layer)
        buffer_step2 = io.BytesIO()
        current_img.save(buffer_step2, format='PNG')
        buffer_step2.seek(0)
        await interaction.followup.send(content="**Bước 2: Sau khi vẽ vòng tròn bán trong suốt sau avatar**", file=discord.File(fp=buffer_step2, filename='step2_circle_overlay.png'))
        print(f"DEBUG_STEP: Đã gửi ảnh sau khi vẽ vòng tròn bán trong suốt.")

        # Bước 3: Dán ảnh stroke PNG đã tô màu
        if GLOBAL_STROKE_OVERLAY_IMAGE:
            tint_layer = Image.new('RGBA', GLOBAL_STROKE_OVERLAY_IMAGE.size, (*stroke_color_rgb, 255))
            final_stroke_layer = Image.composite(tint_layer, Image.new('RGBA', GLOBAL_STROKE_OVERLAY_IMAGE.size, (0,0,0,0)), GLOBAL_STROKE_OVERLAY_IMAGE)
            current_img.paste(final_stroke_layer, (0, 0), final_stroke_layer)
            print(f"DEBUG_STEP: Đã dán ảnh stroke overlay.")
        else:
            print(f"CẢNH BÁO DEBUG_STEP: Không có ảnh stroke overlay được tải trước. Bỏ qua bước này.")
        buffer_step3 = io.BytesIO()
        current_img.save(buffer_step3, format='PNG')
        buffer_step3.seek(0)
        await interaction.followup.send(content="**Bước 3: Sau khi dán stroke overlay**", file=discord.File(fp=buffer_step3, filename='step3_stroke_overlay.png'))
        print(f"DEBUG_STEP: Đã gửi ảnh sau khi dán stroke.")

        # Bước 4: Dán Avatar
        current_img.paste(masked_avatar, (avatar_x, avatar_y), masked_avatar)
        buffer_step4 = io.BytesIO()
        current_img.save(buffer_step4, format='PNG')
        buffer_step4.seek(0)
        await interaction.followup.send(content="**Bước 4: Sau khi dán Avatar**", file=discord.File(fp=buffer_step4, filename='step4_avatar.png'))
        print(f"DEBUG_STEP: Đã gửi ảnh sau khi dán avatar.")

        # Bước 5: Vẽ chữ WELCOME
        welcome_text = "WELCOME"
        welcome_text_width = draw.textlength(welcome_text, font=font_welcome)
        welcome_text_x = int((img_width - welcome_text_width) / 2)
        welcome_text_y_pos = int(avatar_y + AVATAR_SIZE + y_offset_from_avatar)
        
        shadow_color_welcome_rgb = adjust_color_brightness_saturation(
            dominant_color_from_avatar, brightness_factor=0.5, saturation_factor=2.5, clamp_min_l=0.25, clamp_max_l=0.55
        )
        _draw_text_with_shadow(
            draw, welcome_text, font_welcome, welcome_text_x, welcome_text_y_pos,
            (255, 255, 255), (*shadow_color_welcome_rgb, 255), shadow_offset_x, shadow_offset_y
        )
        buffer_step5 = io.BytesIO()
        current_img.save(buffer_step5, format='PNG')
        buffer_step5.seek(0)
        await interaction.followup.send(content="**Bước 5: Sau khi vẽ chữ WELCOME**", file=discord.File(fp=buffer_step5, filename='step5_welcome_text.png'))
        print(f"DEBUG_STEP: Đã gửi ảnh sau khi vẽ WELCOME.")

        # Bước 6: Vẽ tên người dùng
        name_text_raw = member_to_test.display_name
        temp_draw_for_text_calc = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        processed_name_parts, name_text_width = process_text_for_drawing(
            name_text_raw, font_name, font_symbol, replacement_char='✦', temp_draw_obj=temp_draw_for_text_calc
        )
        
        # Kiểm tra và cắt tên nếu quá dài (logic này giữ nguyên từ code của bạn)
        max_name_width_ratio = 0.8
        if name_text_width > img_width * max_name_width_ratio:
            target_width = img_width * max_name_width_ratio
            current_width = 0
            truncated_parts = []
            for char, font_to_use in processed_name_parts:
                char_width = temp_draw_for_text_calc.textlength(char, font=font_to_use)
                if current_width + char_width < target_width - temp_draw_for_text_calc.textlength('...', font=font_name):
                    truncated_parts.append((char, font_to_use))
                    current_width += char_width
                else:
                    break
            if truncated_parts:
                processed_name_parts = truncated_parts
                processed_name_parts.append(('...', font_name))
                name_text_width = current_width + temp_draw_for_text_calc.textlength('...', font=font_name)
            else:
                processed_name_parts = [('...', font_name)]
                name_text_width = temp_draw_for_text_calc.textlength('...', font=font_name)

        name_text_x = int((img_width - name_text_width) / 2)
        welcome_bbox_for_height = draw.textbbox((0, 0), welcome_text, font=font_welcome)
        welcome_actual_height = welcome_bbox_for_height[3] - welcome_bbox_for_height[1]
        name_text_y = int(welcome_text_y_pos + welcome_actual_height + 10)

        shadow_color_name_rgb = adjust_color_brightness_saturation(
            dominant_color_from_avatar, brightness_factor=0.5, saturation_factor=2.5, clamp_min_l=0.25, clamp_max_l=0.55
        )
        shadow_color_name = (*shadow_color_name_rgb, 255)

        current_x = float(name_text_x)
        for char, font_to_use in processed_name_parts:
            # Kiểm tra xem font_to_use có phải là None không
            if font_to_use is None:
                print(f"LỖI FONT DEBUG_STEP: Font là None khi vẽ ký tự '{char}'.")
                # Fallback về font mặc định của Pillow nếu cần thiết
                font_to_use = ImageFont.load_default()
            
            draw.text((int(current_x + shadow_offset_x), int(name_text_y + shadow_offset_y)), char, font=font_to_use, fill=shadow_color_name)
            draw.text((int(current_x), int(name_text_y)), char, font=font_to_use, fill=stroke_color)
            current_x += draw.textlength(char, font=font_to_use)

        buffer_step6 = io.BytesIO()
        current_img.save(buffer_step6, format='PNG')
        buffer_step6.seek(0)
        await interaction.followup.send(content="**Bước 6: Sau khi vẽ tên người dùng**", file=discord.File(fp=buffer_step6, filename='step6_username_text.png'))
        print(f"DEBUG_STEP: Đã gửi ảnh sau khi vẽ tên người dùng.")

        # Bước 7: Vẽ thanh line trang trí
        name_actual_height = _get_text_height("M", font_name, draw)
        line_y = int(name_text_y + name_actual_height + LINE_VERTICAL_OFFSET_FROM_NAME)
        line_color_rgb = stroke_color_rgb
        actual_line_length = int(name_text_width * LINE_LENGTH_FACTOR)
        _draw_simple_decorative_line(draw, img_width, line_y, line_color_rgb, actual_line_length)

        buffer_step7 = io.BytesIO()
        current_img.save(buffer_step7, format='PNG')
        buffer_step7.seek(0)
        await interaction.followup.send(content="**Bước 7: Sau khi vẽ thanh line ngang (Ảnh cuối cùng)**", file=discord.File(fp=buffer_step7, filename='step7_final_with_line.png'))
        print(f"DEBUG_STEP: Đã gửi ảnh sau khi vẽ line ngang (ảnh cuối cùng).")

        await interaction.followup.send("Quá trình debug ảnh đã hoàn tất. Vui lòng kiểm tra các ảnh để xác định bước gây lỗi.")

    except discord.errors.Forbidden:
        print(f"LỖI DISCORD DEBUGIMAGE: Bot thiếu quyền 'Gửi tin nhắn' hoặc 'Đính kèm tệp' trong kênh này cho lệnh debugimage. Vui lòng kiểm tra lại quyền.")
        await interaction.followup.send("Bot không có đủ quyền để gửi các ảnh debug. Vui lòng kiểm tra quyền hạn của bot.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi xảy ra trong quá trình debug ảnh: `{e}`. Vui lòng kiểm tra console của bot để biết thêm chi tiết.")
        print(f"LỖI TỔNG QUAN DEBUGIMAGE: Có lỗi xảy ra: {e}")
        traceback.print_exc()

# --- Slash Command: /skibidi (Nếu có) ---
# Ví dụ về một lệnh đơn giản để đảm bảo bot hoạt động
@bot.tree.command(name="skibidi", description="Skibidi bop bop yes yes!")
async def skibidi_slash(interaction: discord.Interaction):
    await interaction.response.send_message("Skibidi bop bop yes yes! 🚽")

# --- Xử lý sự kiện bot online ---
@bot.event
async def on_ready():
    print(f'{bot.user} đã online và sẵn sàng hoạt động!')
    _load_static_assets() # Đảm bảo hàm này được gọi để tải tài nguyên

    # Đây là phần đã được sửa đổi: Bỏ dòng 'bot.tree.copy_global_commands'
    try:
        guild_obj = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild_obj) # Chỉ giữ lại dòng này để đồng bộ cho server cụ thể
        print(f"Đã đồng bộ lệnh slash cho server ID {GUILD_ID} thành công.")
    except Exception as e:
        print(f"LỖI KHI ĐỒNG BỘ LỆNH SLASH CHO GUILD {GUILD_ID}: {e}")
        traceback.print_exc()

    random_message_sender.start()
    activity_heartbeat.start()
    flask_ping_task.start()

# --- Nhiệm vụ định kỳ để gửi tin nhắn ngẫu nhiên vào một kênh cụ thể ---
@tasks.loop(minutes=random.randint(2, 5))
async def random_message_sender():
    messages = [
        "Chào mọi người! ✨ Chúc một ngày tốt lành!",
        "Đang online đây! Có ai cần gì không? 🤖",
        "Gửi chút năng lượng tích cực đến tất cả! 💪",
        "Thật tuyệt khi có mặt ở đây! 😊",
        "Có câu hỏi nào cho bot không? 😉",
        "Hãy cùng xây dựng một cộng đồng tuyệt vời! 💖"
    ]
    channel_id = 1379789952610467971 # ID kênh bot-mlem
    channel = bot.get_channel(channel_id)
    if channel:
        try:
            await channel.send(random.choice(messages))
            print(f"DEBUG: Đã gửi tin nhắn định kỳ: '{random.choice(messages)}' vào kênh {channel.name} (ID: {channel_id}).")
        except discord.errors.Forbidden:
            print(f"LỖI KÊNH: Bot thiếu quyền gửi tin nhắn vào kênh {channel.name} (ID: {channel_id}).")
        except Exception as e:
            print(f"LỖI KHI GỬI TIN NHẮN ĐỊNH KỲ: {e}")
            traceback.print_exc()
    else:
        print(f"LỖI KÊNH: Không tìm thấy kênh với ID {channel_id}. Vui lòng kiểm tra lại ID hoặc bot chưa có quyền truy cập kênh đó.")
    
    # Lập lịch cho lần gửi tin nhắn tiếp theo
    random_message_sender.change_interval(minutes=random.randint(2, 5))
    print(f"DEBUG: Tác vụ random_message_sender sẽ gửi tin nhắn sau {random_message_sender.interval.seconds // 60} phút.")


# --- Nhiệm vụ định kỳ để thay đổi trạng thái hoạt động của bot ---
@tasks.loop(minutes=random.randint(1, 2))
async def activity_heartbeat():
    activities = [
        discord.Activity(type=discord.ActivityType.listening, name="Bài TRÌNH"),
        discord.Activity(type=discord.ActivityType.watching, name="Dawn_wibu phá đảo tựa game mới "),
        discord.Activity(type=discord.ActivityType.playing, name="Minecraft cùng Anh Em ")
    ]
    selected_activity = random.choice(activities)
    try:
        await bot.change_presence(activity=selected_activity)
        print(f"DEBUG: Đã cập nhật trạng thái bot thành: {selected_activity.name} ({selected_activity.type.name}).")
    except Exception as e:
        print(f"LỖI KHI CẬP NHẬT TRẠNG THÁI BOT: {e}")
        traceback.print_exc()

    activity_heartbeat.change_interval(minutes=random.randint(1, 2))
    print(f"DEBUG: Tác vụ activity_heartbeat đang ngủ {activity_heartbeat.interval.seconds // 60} phút để chuẩn bị cập nhật trạng thái...")

# --- Nhiệm vụ định kỳ để tự ping Flask server ---
@tasks.loop(minutes=random.randint(5, 10))
async def flask_ping_task():
    port = int(os.environ.get("PORT", 10000))
    url = f"http://localhost:{port}/healthz"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                print(f"DEBUG: Tự ping Flask server: {url} - Status: {resp.status}")
    except aiohttp.ClientError as e:
        print(f"LỖI SELF-PING (async): Không thể tự ping Flask server: {e}")
    except asyncio.TimeoutError:
        print("LỖI SELF-PING (async): Yêu cầu ping Flask server đã hết thời gian.")
    except Exception as e:
        print(f"LỖI SELF-PING (async) KHÔNG XÁC ĐỊNH: {e}")
        traceback.print_exc()
    
    flask_ping_task.change_interval(minutes=random.randint(5, 10))
    print(f"DEBUG: Lập lịch tự ping tiếp theo sau {flask_ping_task.interval.seconds // 60} phút.")

# --- Khởi chạy Bot Discord và Flask app ---
async def start_bot_and_flask():
    """Khởi chạy Flask app và Discord bot."""
    # Chạy Flask app trong một luồng riêng
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True # Đặt luồng là daemon để nó tự kết thúc khi chương trình chính kết thúc
    flask_thread.start()
    print("DEBUG: Đã khởi động luồng Flask.")

    # Chạy Discord bot
    try:
        if TOKEN:
            await bot.start(TOKEN)
        else:
            print("LỖI: Biến môi trường DISCORD_BOT_TOKEN không được tìm thấy. Vui lòng thiết lập TOKEN của bot.")
    except discord.errors.LoginFailure:
        print("LỖI ĐĂNG NHẬP: TOKEN bot không hợp lệ. Vui lòng kiểm tra lại TOKEN.")
    except Exception as e:
        print(f"LỖI KHI KHỞI CHẠY BOT: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(start_bot_and_flask())
