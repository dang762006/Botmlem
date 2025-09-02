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

def run_flask():
    """Chạy Flask app trong một luồng riêng biệt và bắt đầu tự ping."""
    port = int(os.environ.get("PORT", 10000))
    print(f"Flask server đang chạy trên cổng {port} (để Health Check).")

    # NOTE: Không dùng self-ping nội bộ trên Render — Render tính traffic bên ngoài.
    # Nếu cần giữ alive, sử dụng dịch vụ ngoài như UptimeRobot để ping /healthz mỗi 5 phút.
    print("DEBUG: Flask server ready. Use an external uptime monitor (UptimeRobot) to ping /healthz every 5 min.")


    app.run(host='0.0.0.0', port=port,
            debug=False)

# --- Cấu hình Bot Discord ---
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents, reconnect=True)

# --- Các hàm xử lý màu sắc ---
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
    Phiên bản tối ưu: phần I/O + CPU-bound (Pillow + ColorThief) chạy trong thread để không block event loop.
    """
    try:
        def blocking_extract_palette(img_bytes, color_count):
            # chạy trong thread
            f = io.BytesIO(img_bytes)
            img_temp = Image.open(f).convert("RGB")
            f_temp = io.BytesIO()
            img_temp.save(f_temp, format='PNG')
            f_temp.seek(0)
            color_thief = ColorThief(f_temp)
            palette = color_thief.get_palette(color_count=color_count, quality=1)
            return palette

        # Lấy palette (blocking) trong thread
        palette = await asyncio.to_thread(blocking_extract_palette, image_bytes, color_count)

        # --- Phần chọn màu là nhẹ, chạy trên event loop (async) ---
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
            if l < 0.5 and s < 0.25:
                continue
            if l > 0.80:
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

        if qualified_colors:
            return qualified_colors[0]['color']
        else:
            # fallback: chọn màu sáng nhất
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

avatar_cache = {}
CACHE_TTL = 900  # 15 phút (tăng để giảm số request đến Discord/HTTP)
# Giới hạn số task tạo ảnh cùng lúc (tránh spike CPU / OOM)
IMAGE_GEN_SEMAPHORE = None  # sẽ init trong on_ready

# --- CÁC HẰNG SỐ DÙNG TRONG TẠO ẢNH ---
FONT_MAIN_PATH = "1FTV-Designer.otf" # Font chính cho chữ
FONT_SYMBOL_PATH = "subset-DejaVuSans.ttf" # Font cho các ký tự đặc biệt/biểu tượng
WELCOME_FONT_SIZE = 60
NAME_FONT_SIZE = 34
AVATAR_SIZE = 210
BACKGROUND_IMAGE_PATH = "welcome.png"
DEFAULT_IMAGE_DIMENSIONS = (872, 430)
LINE_THICKNESS = 3 # CẬP NHẬT ĐỘ DÀY LINE
LINE_VERTICAL_OFFSET_FROM_NAME = 13 # Khoảng cách từ tên đến đường line
LINE_LENGTH_FACTOR = 0.70 # Tỷ lệ độ dài của line so với độ dài của tên (70%)

# --- CÁC HÀM HỖ TRỢ CHO create_welcome_image ---

def _load_fonts(main_path, symbol_path):
    """Tải font chính và font biểu tượng, có fallback."""
    font_welcome, font_name, font_symbol = None, None, None

    # Tải font chính
    try:
        font_welcome = ImageFont.truetype(main_path, WELCOME_FONT_SIZE)
        font_name = ImageFont.truetype(main_path, NAME_FONT_SIZE)
        print(f"DEBUG: Đã tải font chính thành công: {main_path}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font chính '{main_path}'. Sử dụng Arial. Chi tiết: {e}")
        try:
            font_welcome = ImageFont.truetype("arial.ttf", WELCOME_FONT_SIZE)
            font_name = ImageFont.truetype("arial.ttf", NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font Arial.ttf cho văn bản chính.")
        except Exception:
            font_welcome = ImageFont.load_default().font_variant(size=WELCOME_FONT_SIZE)
            font_name = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
            print("DEBUG: Đã sử dụng font mặc định của Pillow cho văn bản chính.")
    
    # Tải font biểu tượng
    try:
        font_symbol = ImageFont.truetype(symbol_path, NAME_FONT_SIZE) # Kích thước tương tự font tên
        print(f"DEBUG: Đã tải font biểu tượng thành công: {symbol_path}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font biểu tượng '{symbol_path}'. Sử dụng font mặc định cho biểu tượng. Chi tiết: {e}")
        font_symbol = ImageFont.load_default().font_variant(size=NAME_FONT_SIZE)
        print("DEBUG: Đã sử dụng font mặc định của Pillow cho biểu tượng.")
    
    return font_welcome, font_name, font_symbol

def _load_background_image(path, default_dims):
    """Tải ảnh nền, hoặc tạo ảnh nền mặc định nếu không tìm thấy."""
    try:
        img = Image.open(path).convert("RGBA")
        print(f"DEBUG: Đã tải ảnh nền: {path} với kích thước {img.size[0]}x{img.size[1]}")
    except FileNotFoundError:
        print(f"LỖI ẢNH NỀN: Không tìm thấy ảnh nền '{path}'. Sử dụng nền màu mặc định.")
        img = Image.new('RGBA', default_dims, color=(0, 0, 0, 255))
    except Exception as e:
        print(f"LỖI ẢNH NỀN: Lỗi khi mở ảnh nền: {e}. Sử dụng nền màu mặc định.")
        img = Image.new('RGBA', default_dims, color=(0, 0, 0, 255))
    return img

async def _get_and_process_avatar(member_avatar_url, avatar_size, cache):
    """Tải và xử lý avatar, có dùng cache."""
    avatar_bytes = None
    if member_avatar_url in cache and (asyncio.get_event_loop().time() - cache[member_avatar_url]['timestamp']) < CACHE_TTL:
        avatar_bytes = cache[member_avatar_url]['data']
        print(f"DEBUG: Lấy avatar từ cache cho {member_avatar_url}.")
    else:
        print(f"DEBUG: Đang tải avatar từ URL: {member_avatar_url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(str(member_avatar_url)) as resp:
                if resp.status != 200:
                    print(f"LỖI AVATAR: Không thể tải avatar. Trạng thái: {resp.status}. Sử dụng avatar màu xám mặc định.")
                else:
                    avatar_bytes = await resp.read()
                    cache[member_avatar_url] = {'data': avatar_bytes, 'timestamp': asyncio.get_event_loop().time()}
                    print(f"DEBUG: Đã tải và lưu avatar vào cache.")

    if avatar_bytes:
        data = io.BytesIO(avatar_bytes)
        avatar_img = Image.open(data).convert("RGBA")
    else:
        avatar_img = Image.new('RGBA', (avatar_size, avatar_size), color=(100, 100, 100, 255))

    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)
    return avatar_img, avatar_bytes

def _draw_circular_avatar_and_stroke(img, avatar_img, avatar_x, avatar_y, avatar_size, stroke_color_rgb):
    """Vẽ avatar tròn và viền xung quanh."""
    draw = ImageDraw.Draw(img)

    # Tính toán màu và độ trong suốt cho nền mờ phía sau avatar
    blur_color_with_alpha = (*stroke_color_rgb, 128)
    blur_bg_raw_circle = Image.new('RGBA', (AVATAR_SIZE, AVATAR_SIZE), (0, 0, 0, 0))
    draw_blur_bg_raw = ImageDraw.Draw(blur_bg_raw_circle)
    draw_blur_bg_raw.ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=blur_color_with_alpha)
    img.paste(blur_bg_raw_circle, (avatar_x, avatar_y), blur_bg_raw_circle)

    # Vẽ stroke (viền) có khoảng trống trong suốt
    stroke_thickness = 6
    gap_size = 5
    outer_stroke_diameter = AVATAR_SIZE + (gap_size * 2) + (stroke_thickness * 2)
    inner_stroke_diameter = AVATAR_SIZE + (gap_size * 2)
    supersample_factor = 4 # Để làm mượt đường tròn

    temp_stroke_layer_supersampled = Image.new(
        'RGBA', (outer_stroke_diameter * supersample_factor,
                 outer_stroke_diameter * supersample_factor), (0, 0, 0, 0))
    draw_temp_stroke = ImageDraw.Draw(temp_stroke_layer_supersampled)

    draw_temp_stroke.ellipse((0, 0, outer_stroke_diameter * supersample_factor,
                              outer_stroke_diameter * supersample_factor),
                             fill=(*stroke_color_rgb, 255)) # Màu viền chính

    inner_offset_x = (outer_stroke_diameter * supersample_factor - inner_stroke_diameter * supersample_factor) // 2
    inner_offset_y = (outer_stroke_diameter * supersample_factor - inner_stroke_diameter * supersample_factor) // 2

    draw_temp_stroke.ellipse(
        (inner_offset_x, inner_offset_y,
         inner_offset_x + inner_stroke_diameter * supersample_factor,
         inner_offset_y + inner_stroke_diameter * supersample_factor),
        fill=(0, 0, 0, 0)) # Khoảng trống bên trong

    stroke_final_image = temp_stroke_layer_supersampled.resize(
        (outer_stroke_diameter, outer_stroke_diameter), Image.LANCZOS)

    stroke_paste_x = avatar_x - gap_size - stroke_thickness
    stroke_paste_y = avatar_y - gap_size - stroke_thickness

    img.paste(stroke_final_image, (stroke_paste_x, stroke_paste_y), stroke_final_image)

    # Dán avatar chính và đảm bảo nó tròn
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

    final_alpha_mask = Image.composite(
        circular_mask_smoothed, Image.new('L', circular_mask_smoothed.size, 0), original_alpha)

    img.paste(avatar_layer, (avatar_x, avatar_y), final_alpha_mask)

def _draw_text_with_shadow(draw_obj, text, font, x, y, main_color, shadow_color, offset_x, offset_y):
    """Vẽ văn bản với hiệu ứng đổ bóng đơn giản với offset tùy chỉnh."""
    draw_obj.text((x + offset_x, y + offset_y), text, font=font, fill=shadow_color)
    draw_obj.text((x, y), text, font=font, fill=main_color)

def _draw_simple_decorative_line(draw_obj, img_width, line_y, line_color_rgb, actual_line_length): # Đã thay đổi tham số
    """Vẽ thanh line đơn giản với độ dài tùy chỉnh."""
    line_x1 = img_width // 2 - actual_line_length // 2 # Sử dụng actual_line_length
    line_x2 = img_width // 2 + actual_line_length // 2 # Sử dụng actual_line_length

    draw_obj.line(
        [(line_x1, line_y), (line_x2, line_y)],
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
    Bổ sung thêm các ký tự đặc biệt theo yêu cầu.
    """
    if 'a' <= char <= 'z' or 'A' <= char <= 'Z':
        return True
    if '0' <= char <= '9':
        return True
    # Các dấu câu cơ bản và một số ký tự đặc biệt thường thấy trong văn bản
    # Bổ sung: _-+=<,>.?/:;"'|\~!@#$%^*()
    special_chars_to_keep = """.,?!;:'"()[]{}<>+-*/=@_|=~`!^*""" + '\\' # Thêm dấu cách và dấu \

    if char in special_chars_to_keep or char.isspace(): # Ký tự trắng cũng là basic
        return True
    
    # Hỗ trợ thêm các ký tự tiếng Việt có dấu
    unicode_ord = ord(char)
    if (0x00C0 <= unicode_ord <= 0x017F) or \
       (0x1EA0 <= unicode_ord <= 0x1EFF): # Latin-1 Supplement và Vietnamese Characters
        return True
    
    return False


def process_text_for_drawing(original_text, main_font, symbol_font, replacement_char='✦'):
    """
    Xử lý văn bản để vẽ.
    Các ký tự cơ bản (chữ cái, số, dấu câu, và các ký tự đặc biệt được định nghĩa) dùng main_font.
    Các ký tự còn lại (ký hiệu, emoji, v.v.) dùng replacement_char với symbol_font.
    Trả về danh sách các (ký tự, font) và chiều rộng tổng cộng.
    """
    processed_parts = []
    total_width = 0
    temp_draw = ImageDraw.Draw(Image.new('RGBA', (1, 1))) # Đối tượng draw tạm thời

    for char in original_text:
        if is_basic_char(char):
            processed_parts.append((char, main_font))
            total_width += temp_draw.textlength(char, font=main_font)
        else:
            # Nếu không phải ký tự cơ bản, thay thế bằng replacement_char
            processed_parts.append((replacement_char, symbol_font))
            total_width += temp_draw.textlength(replacement_char, font=symbol_font)
    
    return processed_parts, total_width


async def create_welcome_image(member):
    # 1. Tải Font
    font_welcome, font_name, font_symbol = _load_fonts(FONT_MAIN_PATH, FONT_SYMBOL_PATH)

    # 2. Tải hoặc tạo ảnh nền
    img = _load_background_image(BACKGROUND_IMAGE_PATH, DEFAULT_IMAGE_DIMENSIONS)
    img_width, img_height = img.size
    draw = ImageDraw.Draw(img)

    # Tính toán offset bóng đổ dựa trên kích thước ảnh (khoảng 0.5% của chiều rộng/chiều cao)
    shadow_offset_x = int(img_width * 0.005)
    shadow_offset_y = int(img_height * 0.005)

    # 3. Lấy và xử lý Avatar
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    avatar_img, avatar_bytes = await _get_and_process_avatar(avatar_url, AVATAR_SIZE, avatar_cache)

    # Xác định màu chủ đạo từ avatar (ĐÃ CẬP NHẬT LOGIC TẠI ĐÂY)
    dominant_color_from_avatar = None
    if avatar_bytes:
        dominant_color_from_avatar = await get_dominant_color(avatar_bytes, color_count=20) # Tăng số lượng màu để lựa chọn
    if dominant_color_from_avatar is None:
        dominant_color_from_avatar = (0, 252, 233) # Default Cyan (màu mặc định an toàn, sáng)

    # Điều chỉnh màu sắc cho viền và chữ dựa trên màu chủ đạo được chọn
    # Điều chỉnh mạnh hơn để đảm bảo màu luôn sáng và rực rỡ
    stroke_color_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=1.1,  # Tăng độ sáng
        saturation_factor=4.6,  # Tăng độ bão hòa
        clamp_min_l=0.6,        # Đảm bảo độ sáng tối thiểu 60%
        clamp_max_l=0.90        # Giới hạn độ sáng tối đa để không bị quá trắng
    )
    stroke_color = (*stroke_color_rgb, 255) # Màu của viền avatar và chữ tên

    # 4. Tính toán vị trí Avatar và các phần tử
    avatar_x = img_width // 2 - AVATAR_SIZE // 2
    avatar_y = int(img_height * 0.36) - AVATAR_SIZE // 2
    y_offset_from_avatar = 20
    welcome_text_y_pos = avatar_y + AVATAR_SIZE + y_offset_from_avatar

    # 5. Vẽ Avatar và viền
    _draw_circular_avatar_and_stroke(img, avatar_img, avatar_x, avatar_y, AVATAR_SIZE, stroke_color_rgb)

    # 6. Vẽ chữ WELCOME
    welcome_text = "WELCOME"
    welcome_text_width = draw.textlength(welcome_text, font=font_welcome)
    welcome_text_x = (img_width - welcome_text_width) / 2
    
    # LÀM SÁNG BÓNG CỦA CHỮ WELCOME
    shadow_color_welcome_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=0.3, # Tăng nhẹ độ sáng của bóng WELCOME
        saturation_factor=3.0, # Tăng nhẹ độ bão hòa để bóng có màu sắc hơn
        clamp_min_l=0.25,      # Đảm bảo độ sáng tối thiểu cho bóng
        clamp_max_l=0.55       # Giới hạn độ sáng tối đa, không cho quá sáng
    )
    _draw_text_with_shadow(
        draw, welcome_text, font_welcome, welcome_text_x, welcome_text_y_pos,
        (255, 255, 255), (*shadow_color_welcome_rgb, 255), shadow_offset_x, shadow_offset_y
    )

    # 7. Vẽ tên người dùng
    name_text_raw = member.display_name
    processed_name_parts, name_text_width = process_text_for_drawing(
        name_text_raw, font_name, font_symbol, replacement_char='✦'
    )
    
    # Nếu tên sau khi lọc quá dài, có thể cắt bớt (đơn giản hóa vì đã xử lý từng phần)
    max_chars_for_name = 25 # Ví dụ giới hạn
    if len(name_text_raw) > max_chars_for_name:
        name_text_raw = name_text_raw[:max_chars_for_name - 3] + "..."
        processed_name_parts, name_text_width = process_text_for_drawing(
            name_text_raw, font_name, font_symbol, replacement_char='✦'
        )


    name_text_x = (img_width - name_text_width) / 2
    welcome_bbox_for_height = draw.textbbox((0, 0), welcome_text, font=font_welcome)
    welcome_actual_height = welcome_bbox_for_height[3] - welcome_bbox_for_height[1]
    name_text_y = welcome_text_y_pos + welcome_actual_height + 10 # Khoảng cách ban đầu

    # LÀM SÁNG BÓNG CỦA CHỮ TÊN
    shadow_color_name_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=0.3, # Tăng nhẹ độ sáng của bóng tên
        saturation_factor=3.0, # Tăng nhẹ độ bão hòa
        clamp_min_l=0.25,       # Đảm bảo độ sáng tối thiểu cho bóng tên
        clamp_max_l=0.55        # Giới hạn độ sáng tối đa
    )
    shadow_color_name = (*shadow_color_name_rgb, 255)

    # Vẽ tên người dùng từng phần (từng ký tự với font tương ứng)
    current_x = name_text_x
    for char, font_to_use in processed_name_parts:
        # Vẽ bóng
        draw.text((current_x + shadow_offset_x, name_text_y + shadow_offset_y), char, font=font_to_use, fill=shadow_color_name)
        # Vẽ chữ chính
        draw.text((current_x, name_text_y), char, font=font_to_use, fill=stroke_color)
        current_x += draw.textlength(char, font=font_to_use)

    # 8. Vẽ thanh line trang trí
    name_actual_height = _get_text_height("M", font_name, draw) # Lấy chiều cao của một ký tự mẫu
    
    line_y = name_text_y + name_actual_height + LINE_VERTICAL_OFFSET_FROM_NAME

    line_color_rgb = stroke_color_rgb

    # Tính toán độ dài line thực tế dựa trên độ dài tên và LINE_LENGTH_FACTOR
    actual_line_length = int(name_text_width * LINE_LENGTH_FACTOR)

    _draw_simple_decorative_line(draw, img_width, line_y, line_color_rgb, actual_line_length) # Truyền actual_line_length

    # 9. Lưu ảnh và trả về
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# Worker thay đổi trạng thái hoạt động của bot
async def activity_heartbeat_worker():
    await bot.wait_until_ready()
    print("DEBUG: activity_heartbeat_worker bắt đầu.")

    activities = [
        discord.Activity(type=discord.ActivityType.watching, name="Dawn_wibu phá đảo tựa game mới "),
        discord.Activity(type=discord.ActivityType.listening, name="Bài TRÌNH "),
        discord.Activity(type=discord.ActivityType.playing, name="Minecraft cùng Anh Em "),
    ]

    while True:
        try:
            sleep_seconds = random.randint(60, 180)  # 1–3 phút
            await asyncio.sleep(sleep_seconds)

            new_activity = random.choice(activities)
            await bot.change_presence(activity=new_activity)

            print(f"DEBUG: Đã cập nhật trạng thái bot thành: {new_activity.name} ({new_activity.type.name}).")

        except Exception as e:
            print(f"LỖI ACTIVITY_HEARTBEAT_WORKER: {e}")
            await asyncio.sleep(30)


# Worker gửi tin nhắn ngẫu nhiên
async def random_message_worker():
    await bot.wait_until_ready()
    print("DEBUG: random_message_worker bắt đầu.")

    channel_id = 123456789012345678  # 👉 Thay bằng ID kênh của bạn
    channel = bot.get_channel(channel_id)

    messages = [
        "Hôm nay trời đẹp ghê 😎",
        "Anh em nhớ uống nước nha 💧",
        "Ai đang onl vậy 🙌",
    ]

    while True:
        try:
            sleep_seconds = random.randint(300, 600)  # 5–10 phút
            await asyncio.sleep(sleep_seconds)

            if channel:
                msg = random.choice(messages)
                await channel.send(msg)
                print(f"DEBUG: Đã gửi tin nhắn: {msg}")
            else:
                print("DEBUG: Không tìm thấy channel để gửi tin.")

        except Exception as e:
            print(f"LỖI RANDOM_MESSAGE_WORKER: {e}")
            await asyncio.sleep(30)


async def random_message_sender_worker():
    await bot.wait_until_ready()
    print("DEBUG: random_message_sender_worker bắt đầu.")
    while True:
        try:
            # Gửi tin nhắn ngẫu nhiên mỗi 20-40 phút
            send_interval_minutes = random.randint(20, 40)
            await asyncio.sleep(send_interval_minutes * 60)

            channel = bot.get_channel(CHANNEL_ID_FOR_RANDOM_MESSAGES)
            if not channel:
                print(f"LỖI KÊNH: Không tìm thấy kênh với ID {CHANNEL_ID_FOR_RANDOM_MESSAGES}.")
                continue

            if not isinstance(channel, discord.TextChannel):
                print(f"LỖI KÊNH: ID {CHANNEL_ID_FOR_RANDOM_MESSAGES} không phải TextChannel.")
                continue

            if not channel.permissions_for(channel.guild.me).send_messages:
                print(f"LỖI QUYỀN: Bot không có quyền gửi tin nhắn ở kênh {channel.name}.")
                continue

            message_to_send = random.choice(RANDOM_MESSAGES)
            try:
                await channel.send(message_to_send)
                print(f"DEBUG: Đã gửi tin nhắn định kỳ: '{message_to_send}' vào kênh {channel.name}.")
            except discord.errors.Forbidden:
                print(f"LỖI QUYỀN: Không thể gửi tin nhắn (Forbidden).")
            except Exception as e:
                print(f"LỖI GỬI TIN NHẮN: {e}")
        except Exception as e:
            print(f"LỖI random_message_sender_worker: {e}")
            await asyncio.sleep(60)

# --- Các sự kiện của bot ---
@bot.event
async def on_ready():
    """Xử lý sự kiện khi bot sẵn sàng."""
    print(f'{bot.user} đã sẵn sàng! 🎉')
    print('Bot đã online và có thể hoạt động.')
    try:
        # đồng bộ hóa cho server của bạn (ID: 913046733796311040)
        guild_id = 913046733796311040 # ID server của bạn
        guild = discord.Object(id=guild_id)
        synced = await bot.tree.sync(guild=guild) # <-- ĐÃ SỬA Ở ĐÂY
        print(f"Đã đồng bộ {len(synced)} lệnh slash commands cho server ID: {guild_id}")
    except Exception as e:
        print(
            f"LỖI ĐỒNG BỘ: Lỗi khi đồng bộ slash commands: {e}. Vui lòng kiểm tra quyền 'applications.commands' cho bot trên Discord Developer Portal."
        )

    # --- Init semaphore  và khởi background workers 1 lần ---
    global IMAGE_GEN_SEMAPHORE
    if IMAGE_GEN_SEMAPHORE is None:
        IMAGE_GEN_SEMAPHORE = asyncio.Semaphore(2)  # giữ tối đa 2 tác vụ tạo ảnh chạy đồng thời

    # Start background worker tasks only once
    if not hasattr(bot, 'bg_tasks_started') or not bot.bg_tasks_started:
        bot.bg_tasks_started = True
        asyncio.create_task(activity_heartbeat_worker())
        asyncio.create_task(random_message_sender_worker())
        print("DEBUG: Đã bắt đầu background workers (activity + random messages).")


@bot.event
async def on_member_join(member):
    channel_id = 1322848542758277202

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
        # Giới hạn số tác vụ tạo ảnh cùng lúc
        if IMAGE_GEN_SEMAPHORE:
            async with IMAGE_GEN_SEMAPHORE:
                image_bytes = await create_welcome_image(member)
        else:
            image_bytes = await create_welcome_image(member)

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

# --- Slash Command: /skibidi (Chỉ dành cho những người có vai trò cụ thể) ---
# Dòng này kiểm tra xem người dùng có vai trò với ID 1322844864760516691 hay không.
# Nếu không có, lệnh sẽ không hoạt động.
@bot.tree.command(name="skibidi", description="Dẫn tới Dawn_wibu.")
@app_commands.checks.has_role(913046733796311040)
async def skibidi(interaction: discord.Interaction):
    await interaction.response.send_message(
        "<a:cat2:1323314096040448145>**✦** ***[AN BA TO KOM](https://dawnwibu.carrd.co)*** **✦** <a:cat3:1323314218476372122>"
    )

# --- Slash Command: /testwelcome (Chỉ quản trị viên) ---
@bot.tree.command(name="testwelcome", description="Tạo và gửi ảnh chào mừng cho người dùng.")
@app_commands.default_permissions(administrator=True) # Quyền: Chỉ quản trị viên
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True) # Kiểm tra bổ sung trong code
async def testwelcome_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True)

    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member_to_test.display_name}...")
        if IMAGE_GEN_SEMAPHORE:
            async with IMAGE_GEN_SEMAPHORE:
                image_bytes = await create_welcome_image(member_to_test)
        else:
            image_bytes = await create_welcome_image(member_to_test)

        await interaction.followup.send(file=discord.File(fp=image_bytes, filename='welcome_test.png'))
        print(f"DEBUG: Đã gửi ảnh test chào mừng cho {member_to_test.display_name} thông qua lệnh slash.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test: {e}\nKiểm tra lại hàm `create_welcome_image`.")
        print(f"LỖI TEST: Có lỗi khi tạo hoặc gửi ảnh test: {e}")
        import traceback
        traceback.print_exc()

# --- Khởi chạy Flask và Bot Discord ---
async def start_bot_and_flask():
    """Hàm async để khởi động Flask + bot Discord với delay và restart chậm (avoid rate limit)."""
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Đợi lâu hơn khi process khởi động để tránh login spam nếu Render restart
    delay_before_login = 30  # seconds
    print(f"DEBUG: Đang đợi {delay_before_login}s trước khi khởi động bot Discord để tránh rate limit...")
    await asyncio.sleep(delay_before_login)

    print("DEBUG: Bắt đầu khởi động bot Discord...")

    # Vòng lặp restart chậm: nếu bot crash, đợi 60s trước khi restart lại
    while True:
    try:
        await bot.start(TOKEN)
        # Nếu bot.start() hoàn tất (rút lui), break
        break

    except discord.errors.HTTPException as e:
        if getattr(e, 'status', None) == 429:
            print(f"Lỗi 429 Too Many Requests khi đăng nhập: {e}")
            print("Có vẻ như Discord đã giới hạn tốc độ đăng nhập. Dợi 5-10 phút trước khi thử lại.")
            await asyncio.sleep(300)  # đợi 5 phút
            print(
                "Đảm bảo bạn không khởi động lại bot quá thường xuyên hoặc có nhiều phiên bản bot đang chạy."
            )
        else:
            print(f"Một lỗi HTTP khác khi đăng nhập: {e}")
            await asyncio.sleep(60)

    except Exception as e:
        print(f"Một lỗi không xác định đã xảy ra: {e}. Restart sau 60s...")
        await asyncio.sleep(60)

if __name__ == '__main__':
    if not TOKEN:
        print(
            "Lỗi: TOKEN không được tìm thấy. Vui lòng thiết lập biến môi trường 'DISCORD_BOT_TOKEN' hoặc 'TOKEN'."
        )
    else:
        asyncio.run(start_bot_and_flask())
