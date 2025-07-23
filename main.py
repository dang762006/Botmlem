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

    threading.Timer(10, send_self_ping).start()
    print("DEBUG: Đã bắt đầu tác vụ tự ping Flask server.")

    app.run(host='0.0.0.0', port=port,
            debug=False)

# --- Cấu hình Bot Discord ---
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

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

async def get_dominant_color(image_bytes, color_count=20): # Tăng số lượng màu để có nhiều lựa chọn hơn
    try:
        f = io.BytesIO(image_bytes)
        img_temp = Image.open(f).convert("RGB")
        f_temp = io.BytesIO()
        img_temp.save(f_temp, format='PNG')
        f_temp.seek(0)

        color_thief = ColorThief(f_temp)
        palette = color_thief.get_palette(color_count=color_count, quality=1)

        # Danh sách để lưu các màu đủ tiêu chuẩn, kèm theo điểm số và thứ tự ưu tiên sắc độ
        qualified_colors = []

        # Định nghĩa ngưỡng và thứ tự ưu tiên sắc độ (Hue)
        # H (0-1): Đỏ(~0), Cam(~0.08), Vàng(~0.16), Lục(~0.33), Cyan(~0.5), Lam(~0.66), Tím(~0.83), Magenta(~0.9)
        HUE_PRIORITY_ORDER = [
            (0.75, 0.95),  # Tím/Magenta
            (0.40, 0.75),  # Xanh Dương/Xanh Da Trời (Blue/Cyan)
            (0.18, 0.40),  # Xanh Lá (Green)
            (0.00, 0.18),  # Đỏ/Cam/Vàng (Warm colors - Red wraps around 0/1)
            (0.95, 1.00)   # Đỏ (phần còn lại của đỏ)
        ]
        
        def get_hue_priority_index(h_value):
            # Hàm này sẽ trả về index ưu tiên sắc độ
            # Index càng nhỏ -> ưu tiên càng cao
            if 0.75 <= h_value < 0.95: return 0  # Tím/Magenta
            if 0.40 <= h_value < 0.75: return 1  # Xanh Dương/Xanh Da Trời
            if 0.18 <= h_value < 0.40: return 2  # Xanh Lá
            
            # Xử lý màu ấm (đỏ, cam, vàng)
            if (0.00 <= h_value < 0.18) or (0.95 <= h_value <= 1.00): return 3 # Đỏ/Cam/Vàng
            
            return 99 # Giá trị lớn cho các màu không thuộc nhóm ưu tiên

        for color_rgb in palette:
            r, g, b = color_rgb
            h, s, l = rgb_to_hsl(r, g, b)

            # --- TIÊU CHÍ LỰA CHỌN MÀU SẮC DỰA TRÊN VÙNG KHOANH ĐỎ TRONG PHOTOSHOP ---
            # Vùng khoanh đỏ: Nửa trên bên phải, tránh trắng tinh và đen/xám tối.
            # 1. Loại bỏ các màu quá tối hoặc quá xám xịt (ngoài vùng mong muốn)
            # Dựa trên hình ảnh, L thấp (dưới 0.5) hoặc S quá thấp (dưới 0.25) thì loại bỏ trừ trường hợp xám sáng
            if l < 0.5 and s < 0.25: # Nếu quá tối và ít bão hòa
                continue

            # 2. Hạn chế màu trắng/rất nhạt (phía trên cùng hình vuông)
            if l > 0.90: # Nếu quá gần trắng tinh (L > 90%)
                continue
            
            # 3. Phân loại màu: Rực rỡ & Sáng (Ưu tiên 1) vs Xám Sáng (Ưu tiên 2)
            is_vibrant_and_bright = (l >= 0.5 and s > 0.4) # Màu trong vùng khoanh đỏ chính
            is_bright_grayish = (l >= 0.6 and s >= 0.25 and s <= 0.4) # Tiêu chí "xám sáng" của bạn

            if is_vibrant_and_bright:
                # Tính điểm: Ưu tiên cả bão hòa và sáng cao
                score = s * l
                qualified_colors.append({
                    'color': color_rgb,
                    'score': score,
                    'type': 'vibrant_bright',
                    'hue_priority': get_hue_priority_index(h)
                })
            elif is_bright_grayish:
                # Điểm thấp hơn cho xám sáng, ưu tiên sáng hơn
                score = l * 0.5 + s * 0.5 # Điểm cân bằng hơn cho xám sáng
                qualified_colors.append({
                    'color': color_rgb,
                    'score': score,
                    'type': 'bright_grayish',
                    'hue_priority': 98 # Ưu tiên thấp hơn màu rực rỡ
                })
            # Các màu còn lại không được thêm vào qualified_colors và sẽ không được chọn trừ khi không còn lựa chọn nào.
        
        # Sắp xếp các màu đủ điều kiện
        # Ưu tiên 1: loại 'vibrant_bright' trước 'bright_grayish'
        # Ưu tiên 2: điểm số (score) từ cao đến thấp
        # Ưu tiên 3: thứ tự sắc độ (hue_priority) từ thấp đến cao (Tím -> Xanh -> Ấm)
        qualified_colors.sort(key=lambda x: (
            0 if x['type'] == 'vibrant_bright' else 1, # Loại màu (0 là rực rỡ, 1 là xám sáng)
            -x['score'], # Điểm số (giảm dần)
            x['hue_priority'] # Thứ tự sắc độ (tăng dần)
        ))

        if qualified_colors:
            return qualified_colors[0]['color'] # Chọn màu ưu tiên nhất
        else:
            # Fallback nếu không tìm thấy màu nào thỏa mãn
            # Trong trường hợp avatar quá tối hoặc quá trắng/xám xịt
            # Vẫn cố gắng tìm màu sáng nhất trong toàn bộ palette
            best_fallback_color = (0, 252, 233) # Default Cyan
            max_l_fallback = -1
            for color in palette:
                _, _, l = rgb_to_hsl(*color)
                # Chỉ loại bỏ màu cực tối hoàn toàn (đen kịt)
                if not (color[0] < 30 and color[1] < 30 and color[2] < 30):
                    if l > max_l_fallback:
                        max_l_fallback = l
                        best_fallback_color = color
            return best_fallback_color

    except Exception as e:
        print(f"LỖI COLORTHIEF: Không thể lấy bảng màu từ avatar: {e}")
        return (0, 252, 233) # Default Cyan (màu mặc định an toàn, sáng)

avatar_cache = {}
CACHE_TTL = 300

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
LINE_LENGTH_FACTOR = 0.75 # Tỷ lệ độ dài của line so với độ dài của tên (80%)

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
        brightness_factor=1.3,  # Tăng độ sáng
        saturation_factor=3.6,  # Tăng độ bão hòa
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
        brightness_factor=0.8, # Tăng nhẹ độ sáng của bóng WELCOME
        saturation_factor=4.2, # Tăng nhẹ độ bão hòa để bóng có màu sắc hơn
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
        brightness_factor=0.7, # Tăng nhẹ độ sáng của bóng tên
        saturation_factor=4.2, # Tăng nhẹ độ bão hòa
        clamp_min_l=0.2,       # Đảm bảo độ sáng tối thiểu cho bóng tên
        clamp_max_l=0.5        # Giới hạn độ sáng tối đa
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

# --- Các tác vụ của bot (đã chỉnh sửa để không sleep ở before_loop) ---
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
    await bot.wait_until_ready() # Đảm bảo bot đã sẵn sàng trước khi chạy loop
    print("DEBUG: activity_heartbeat task chờ bot sẵn sàng.")

# --- Tác vụ gửi tin nhắn định kỳ ---
CHANNEL_ID_FOR_RANDOM_MESSAGES = 1379789952610467971

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
    await bot.wait_until_ready() # Đảm bảo bot đã sẵn sàng trước khi chạy loop
    print("DEBUG: random_message_sender task chờ bot sẵn sàng.")

# --- Các sự kiện của bot ---
@bot.event
async def on_ready():
    """Xử lý sự kiện khi bot sẵn sàng."""
    print(f'{bot.user} đã sẵn sàng! 🎉')
    print('Bot đã online và có thể hoạt động.')
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ {len(synced)} lệnh slash commands toàn cầu.")
    except Exception as e:
        print(
            f"LỖI ĐỒNG BỘ: Lỗi khi đồng bộ slash commands: {e}. Vui lòng kiểm tra quyền 'applications.commands' cho bot trên Discord Developer Portal."
        )

    if not activity_heartbeat.is_running():
        activity_heartbeat.start()
        print("DEBUG: Đã bắt đầu tác vụ thay đổi trạng thái để giữ hoạt động.")

    if not random_message_sender.is_running():
        random_message_sender.start()
        print("DEBUG: Đã bắt đầu tác vụ gửi tin nhắn định kỳ.")


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

# --- Slash Command để TEST tạo ảnh welcome ---
@bot.tree.command(name="testwelcome", description="Tạo và gửi ảnh chào mừng cho người dùng.")
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True)
async def testwelcome_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True)

    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member_to_test.display_name}...")
        image_bytes = await create_welcome_image(member_to_test)
        await interaction.followup.send(file=discord.File(fp=image_bytes, filename='welcome_test.png'))
        print(f"DEBUG: Đã gửi ảnh test chào mừng cho {member_to_test.display_name} thông qua lệnh slash.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test: {e}")
        print(f"LỖI TEST: Có lỗi khi tạo hoặc gửi ảnh test: {e}")

# --- Slash Command mới: /skibidi ---
@bot.tree.command(name="skibidi", description="Dẫn tới Dawn_wibu.")
async def skibidi(interaction: discord.Interaction):
    await interaction.response.send_message(
        " <a:cat2:1323314096040448145>**✦** *** [AN BA TO KOM](https://dawnwibu.carrd.co) *** **✦** <a:cat3:1323314218476372122>" # Đã thêm ✦ vào đây
    )

# --- Khởi chạy Flask và Bot Discord ---
async def start_bot_and_flask():
    """Hàm async để khởi động cả Flask và bot Discord."""
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
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
