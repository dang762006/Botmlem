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
        f"DEBUG: Lập lịch tự ping tiếp theo sau {next_ping_interval / 60:.1f} phút."
    )

def run_flask():
    """Chạy Flask app."""
    # Khởi tạo self-ping khi Flask bắt đầu chạy
    threading.Timer(10, send_self_ping).start()  # Bắt đầu ping sau 10 giây
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# --- Cấu hình Bot Discord ---
INTENTS = discord.Intents.default()
INTENTS.members = True  # Bật intent để nhận sự kiện thành viên
INTENTS.message_content = True  # Bật intent để đọc tin nhắn nếu cần (cho lệnh bot)

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# Lấy TOKEN từ biến môi trường
TOKEN = os.environ.get("DISCORD_BOT_TOKEN") or os.environ.get("TOKEN")

# --- Đường dẫn và Hằng số Cố định ---
BACKGROUND_IMAGE_PATH = "image_a44343.png"  # Đảm bảo đường dẫn đúng tới ảnh nền
AVATAR_MASK_IMAGE_PATH = "avatar.png"  # File mask hình tròn (trắng trên nền trong suốt, mượt mà)
STROKE_OVERLAY_IMAGE_PATH = "stroke.png" # File ảnh viền (trắng trên nền trong suốt)

FONT_PATH_NAME = "arial.ttf"  # Đảm bảo đường dẫn đúng tới font
FONT_PATH_WELCOME = "arial.ttf" # Có thể dùng font khác nếu muốn

AVATAR_SIZE = 210
AVATAR_POSITION = (40, 137) # Vị trí X, Y của avatar

WELCOME_TEXT_COLOR = (255, 255, 255) # Màu chữ WELCOME mặc định
NAME_TEXT_MAX_WIDTH = 500 # Chiều rộng tối đa cho tên người dùng
FONT_SIZE_WELCOME = 75
FONT_SIZE_NAME_BASE = 50

# Biến toàn cục để lưu trữ ảnh được tải một lần
GLOBAL_BACKGROUND_IMAGE = None
GLOBAL_AVATAR_MASK_IMAGE = None
GLOBAL_STROKE_OVERLAY_IMAGE = None

# Cache để lưu avatar đã xử lý
GLOBAL_AVATAR_CACHE = {} # {user_id: processed_avatar_image}
CACHE_CLEANUP_INTERVAL = 3600 # Thời gian dọn dẹp cache (giây), ví dụ 1 giờ

# --- Hàm tiện ích cho xử lý ảnh ---
def adjust_color_brightness_saturation(rgb_color, brightness_factor, saturation_factor, clamp_min_l=0.0, clamp_max_l=1.0):
    """
    Điều chỉnh độ sáng và độ bão hòa của màu RGB và giới hạn độ sáng trong khoảng nhất định.
    Args:
        rgb_color (tuple): Màu RGB gốc (R, G, B).
        brightness_factor (float): Hệ số điều chỉnh độ sáng (ví dụ: 1.2 để sáng hơn, 0.8 để tối hơn).
        saturation_factor (float): Hệ số điều chỉnh độ bão hòa (ví dụ: 1.5 để bão hòa hơn, 0.5 để nhạt hơn).
        clamp_min_l (float): Giới hạn độ sáng tối thiểu trong khoảng [0.0, 1.0].
        clamp_max_l (float): Giới hạn độ sáng tối đa trong khoảng [0.0, 1.0].
    Returns:
        tuple: Màu RGB đã điều chỉnh (R, G, B).
    """
    if not (0.0 <= clamp_min_l <= 1.0 and 0.0 <= clamp_max_l <= 1.0 and clamp_min_l <= clamp_max_l):
        raise ValueError("clamp_min_l và clamp_max_l phải nằm trong khoảng [0.0, 1.0] và clamp_min_l <= clamp_max_l.")

    # Chuyển RGB sang HSL (Hue, Saturation, Lightness) để dễ điều chỉnh độ sáng và bão hòa
    r, g, b = [x / 255.0 for x in rgb_color]
    max_val = max(r, g, b)
    min_val = min(r, g, b)
    
    h = s = l = (max_val + min_val) / 2

    if max_val == min_val: # Màu xám hoặc đen/trắng
        h = 0
        s = 0
    else:
        d = max_val - min_val
        s = d / (2 - max_val - min_val) if l > 0.5 else d / (max_val + min_val)
        
        if max_val == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif max_val == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6

    # Điều chỉnh độ sáng và độ bão hòa
    l = max(0.0, min(1.0, l * brightness_factor))
    s = max(0.0, min(1.0, s * saturation_factor))

    # Áp dụng giới hạn độ sáng
    l = max(clamp_min_l, min(clamp_max_l, l))

    # Chuyển lại HSL sang RGB
    def hue_to_rgb(p, q, t):
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q

    r = hue_to_rgb(p, q, h + 1/3)
    g = hue_to_rgb(p, q, h)
    b = hue_to_rgb(p, q, h - 1/3)

    return (int(r * 255), int(g * 255), int(b * 255))

def get_dominant_color(image_bytes):
    """Lấy màu chủ đạo từ ảnh."""
    try:
        color_thief = ColorThief(io.BytesIO(image_bytes))
        palette = color_thief.get_palette(color_count=10) # Lấy 10 màu để có sự lựa chọn đa dạng
        
        qualified_colors = []
        for color_rgb in palette:
            # Chuyển đổi sang HSL để dễ đánh giá
            r, g, b = [x / 255.0 for x in color_rgb]
            # Công thức chuyển đổi RGB sang HSL đơn giản
            max_val = max(r, g, b)
            min_val = min(r, g, b)
            l = (max_val + min_val) / 2 # Lightness
            
            s = 0 # Saturation
            if max_val != min_val:
                d = max_val - min_val
                s = d / (2 - max_val - min_val) if l > 0.5 else d / (max_val + min_val)
            
            # Tính Hue (chỉ cần nếu muốn ưu tiên màu nào đó, tạm bỏ qua để đơn giản)
            h = 0
            if max_val != min_val:
                d = max_val - min_val
                if max_val == r:
                    h = (g - b) / d + (6 if g < b else 0)
                elif max_val == g:
                    h = (b - r) / d + 2
                else:
                    h = (r - g) / d + 4
                h /= 6
            
            is_dark_color = l < 0.25 # Quá tối
            is_bright_color = l > 0.90 # Quá sáng (gần trắng)
            is_grayish = s < 0.15 # Quá ít bão hòa (gần xám)

            # Ưu tiên màu: 0=tối_rực, 1=tối_vừa, 2=sáng_vừa, 3=sáng_rực, 4=xám, 5=quá_tối/quá_sáng
            color_type_score = 0
            if is_dark_color:
                color_type_score = 4 # Coi là màu tối nhưng vẫn có thể dùng
                if l < 0.1: # Quá tối, tránh dùng
                    color_type_score = 5
            elif is_bright_color:
                color_type_score = 3 # Coi là màu sáng nhưng vẫn có thể dùng
                if l > 0.95 or is_grayish: # Quá sáng hoặc quá xám, tránh dùng
                    color_type_score = 5
            elif is_grayish:
                color_type_score = 4 # Xám
            else:
                color_type_score = 1 # Mặc định là màu tốt

            # Điểm số để ưu tiên màu sắc:
            # Ưu tiên màu tươi sáng, không quá tối, không quá xám.
            # Điểm số càng thấp càng tốt.
            score = l * (1 - s) # Tạm tính, có thể điều chỉnh thêm

            qualified_colors.append({
                'rgb': color_rgb,
                'l': l,
                's': s,
                'h': h,
                'type': color_type_score,
                'score': score
            })
        
        # Sắp xếp các màu đủ điều kiện:
        # 1. Ưu tiên loại màu (type) tốt hơn (điểm type thấp hơn)
        # 2. Sau đó ưu tiên màu có score thấp hơn (sáng và ít bão hòa hơn, hoặc tùy chỉnh)
        # 3. Cuối cùng, có thể ưu tiên theo hue để có sự đa dạng
        qualified_colors.sort(key=lambda c: (c['type'], c['s'], c['l'])) # Ưu tiên màu có độ bão hòa cao hơn, độ sáng vừa phải

        if qualified_colors:
            return qualified_colors[0]['rgb']
        
    except Exception as e:
        print(f"Lỗi khi lấy màu chủ đạo: {e}")
    
    # Màu mặc định nếu không tìm được màu chủ đạo hoặc lỗi
    return (0, 252, 233) # Default Cyan

async def _get_user_avatar_bytes(member: discord.Member):
    """Tải avatar của người dùng."""
    try:
        avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
        async with aiohttp.ClientSession() as session:
            async with session.get(str(avatar_url)) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    print(f"Không thể tải avatar từ URL: {avatar_url}, Status: {resp.status}")
                    return None
    except Exception as e:
        print(f"Lỗi khi tải avatar: {e}")
        return None

def _get_and_process_avatar(user_avatar_bytes):
    """Tải, cắt tròn và xử lý avatar."""
    if GLOBAL_AVATAR_MASK_IMAGE is None:
        print("LỖI: GLOBAL_AVATAR_MASK_IMAGE chưa được tải.")
        return None

    if user_avatar_bytes:
        try:
            downloaded_avatar = Image.open(io.BytesIO(user_avatar_bytes)).convert("RGBA")
            downloaded_avatar = downloaded_avatar.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
            
            # Áp dụng mask hình tròn cho avatar
            # GLOBAL_AVATAR_MASK_IMAGE phải là ảnh grayscale (L mode) hoặc 1 bit (1 mode)
            # để putalpha hoạt động như một kênh alpha
            downloaded_avatar.putalpha(GLOBAL_AVATAR_MASK_IMAGE.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS))

            return downloaded_avatar
        except Exception as e:
            print(f"Lỗi khi xử lý avatar: {e}")
            return None
    return None

def _draw_text_with_shadow(draw_obj, text, font, x, y, fill_color, shadow_color, shadow_offset_x, shadow_offset_y):
    """Vẽ chữ có đổ bóng."""
    draw_obj.text((x + shadow_offset_x, y + shadow_offset_y), text, font=font, fill=shadow_color)
    draw_obj.text((x, y), text, font=font, fill=fill_color)

def get_font(path, size):
    """Tải và trả về đối tượng Font."""
    try:
        return ImageFont.truetype(path, size)
    except IOError:
        print(f"Lỗi: Không tìm thấy font {path}. Vui lòng kiểm tra đường dẫn.")
        return ImageFont.load_default() # Fallback font

def _load_static_assets():
    """Tải tất cả các ảnh dùng chung một lần khi bot khởi động."""
    global GLOBAL_BACKGROUND_IMAGE, GLOBAL_AVATAR_MASK_IMAGE, GLOBAL_STROKE_OVERLAY_IMAGE
    
    # Tải ảnh nền
    try:
        GLOBAL_BACKGROUND_IMAGE = Image.open(BACKGROUND_IMAGE_PATH).convert("RGBA")
        print(f"DEBUG: Đã tải ảnh nền: {BACKGROUND_IMAGE_PATH}")
    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy file ảnh nền: {BACKGROUND_IMAGE_PATH}")
        return False

    # Tải mask avatar (quan trọng: convert sang "L" mode cho putalpha)
    try:
        GLOBAL_AVATAR_MASK_IMAGE = Image.open(AVATAR_MASK_IMAGE_PATH).convert("L")
        print(f"DEBUG: Đã tải mask avatar: {AVATAR_MASK_IMAGE_PATH}")
    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy file mask avatar: {AVATAR_MASK_IMAGE_PATH}")
        return False
    
    # Tải ảnh stroke (cũng cần RGBA để có kênh alpha cho viền)
    try:
        GLOBAL_STROKE_OVERLAY_IMAGE = Image.open(STROKE_OVERLAY_IMAGE_PATH).convert("RGBA")
        print(f"DEBUG: Đã tải stroke overlay: {STROKE_OVERLAY_IMAGE_PATH}")
    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy file stroke overlay: {STROKE_OVERLAY_IMAGE_PATH}")
        return False
    
    return True

# --- Hàm chính để tạo ảnh chào mừng ---
async def create_welcome_image(member: discord.Member):
    if GLOBAL_BACKGROUND_IMAGE is None or GLOBAL_AVATAR_MASK_IMAGE is None or GLOBAL_STROKE_OVERLAY_IMAGE is None:
        print("LỖI: Các ảnh toàn cục chưa được tải. Đang thử tải lại...")
        if not _load_static_assets():
            print("Không thể tải các ảnh cần thiết. Không thể tạo ảnh chào mừng.")
            return None

    img = Image.new('RGBA', GLOBAL_BACKGROUND_IMAGE.size, (0, 0, 0, 0)) # Tạo ảnh trống base

    # Lấy avatar của người dùng
    user_avatar_bytes = await _get_user_avatar_bytes(member)
    avatar_img = None
    if user_avatar_bytes:
        avatar_img = _get_and_process_avatar(user_avatar_bytes)
    
    # Xử lý nếu không lấy được avatar
    if avatar_img is None:
        print(f"Không thể xử lý avatar của {member.display_name}. Sẽ bỏ qua dán avatar này.")
        # Hoặc bạn có thể dán một avatar placeholder tại đây
        return None # Trả về None nếu không có avatar để làm việc

    # Tính toán vị trí avatar và các thành phần khác
    avatar_x, avatar_y = AVATAR_POSITION
    
    # Lấy màu chủ đạo từ avatar gốc (trước khi cắt tròn)
    dominant_color_from_avatar = get_dominant_color(user_avatar_bytes)

    # Điều chỉnh màu sắc cho viền và chữ dựa trên màu chủ đạo được chọn
    stroke_color_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=1.1, # Đã điều chỉnh cho màu sắc rực rỡ hơn
        saturation_factor=3.0,
        clamp_min_l=0.3,       # Rất quan trọng: Giảm đáng kể giới hạn dưới độ sáng
        clamp_max_l=0.85
    )
    stroke_color_for_name = (*stroke_color_rgb, 255) # Màu của chữ tên (luôn đục)

    # Điều chỉnh màu sắc cho bóng của chữ WELCOME
    shadow_color_welcome_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=1.2,
        saturation_factor=3.2,
        clamp_min_l=0.25,
        clamp_max_l=0.55
    )
    shadow_color_welcome = (*shadow_color_welcome_rgb, 255)

    # Điều chỉnh màu sắc cho bóng của tên người dùng
    shadow_color_name_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=1.2,
        saturation_factor=3.2,
        clamp_min_l=0.25,
        clamp_max_l=0.55
    )
    shadow_color_name = (*shadow_color_name_rgb, 255) # Màu của bóng tên (luôn đục)

    # --- DÁN CÁC LỚP ẢNH LÊN NỀN THEO ĐÚNG THỨ TỰ ---

    # 1. Dán ảnh nền chính (đảm bảo nó đã được tải thành công)
    img.paste(GLOBAL_BACKGROUND_IMAGE, (0, 0))

    # 2. TẠO VÀ DÁN LỚP NỀN TRÒN TRONG SUỐT PHÍA SAU AVATAR
    # Lớp này sẽ lấp đầy các vùng trong suốt của avatar PNG
    inner_circle_color_rgb = adjust_color_brightness_saturation(
        dominant_color_from_avatar,
        brightness_factor=1.8, # Làm rất sáng để tạo hiệu ứng nền nhạt
        saturation_factor=1.5, # Giữ độ bão hòa vừa phải
        clamp_min_l=0.7,       # Đảm bảo nền luôn sáng
        clamp_max_l=0.98       # Giới hạn độ sáng tối đa
    )
    inner_circle_alpha = 128 # 50% opacity (128 = 255 * 0.5)
    inner_circle_color_rgba = (*inner_circle_color_rgb, inner_circle_alpha)

    # Tạo một ảnh màu với kích thước của avatar (AVATAR_SIZE x AVATAR_SIZE)
    inner_circle_layer = Image.new('RGBA', (AVATAR_SIZE, AVATAR_SIZE), inner_circle_color_rgba)
    
    # Resize mask về kích thước AVATAR_SIZE và áp dụng làm kênh alpha cho lớp nền tròn
    current_mask_for_inner_circle = GLOBAL_AVATAR_MASK_IMAGE.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    inner_circle_layer.putalpha(current_mask_for_inner_circle)
    
    # Dán lớp nền tròn trong suốt này lên ảnh chính tại vị trí của avatar
    # Quan trọng: DÁN LỚP NÀY TRƯỚC KHI DÁN AVATAR
    img.paste(inner_circle_layer, (avatar_x, avatar_y), inner_circle_layer)

    # 3. Dán Avatar (đã được cắt tròn bởi _get_and_process_avatar và giữ nguyên độ trong suốt gốc)
    img.paste(avatar_img, (avatar_x, avatar_y), avatar_img) # Dán avatar với kênh alpha của nó

    # 4. Dán ảnh stroke PNG đã tô màu (Sẽ là viền đậm)
    # GLOBAL_STROKE_OVERLAY_IMAGE phải là ảnh viền trắng trên nền trong suốt.
    tint_layer_stroke = Image.new('RGBA', GLOBAL_STROKE_OVERLAY_IMAGE.size, (*stroke_color_rgb, 255))
    final_stroke_layer = Image.composite(tint_layer_stroke, Image.new('RGBA', GLOBAL_STROKE_OVERLAY_IMAGE.size, (0,0,0,0)), GLOBAL_STROKE_OVERLAY_IMAGE)
    img.paste(final_stroke_layer, (0, 0), final_stroke_layer)

    # --- VẼ CHỮ WELCOME ---
    font_welcome = get_font(FONT_PATH_WELCOME, FONT_SIZE_WELCOME)
    welcome_text = "WELCOME" # Có thể thay đổi
    welcome_text_x = 350 # Vị trí X của chữ WELCOME
    welcome_text_y_pos = 145 # Vị trí Y của chữ WELCOME
    
    draw = ImageDraw.Draw(img)
    shadow_offset_x = 5
    shadow_offset_y = 5

    _draw_text_with_shadow(
        draw, welcome_text, font_welcome, welcome_text_x, welcome_text_y_pos,
        WELCOME_TEXT_COLOR, shadow_color_welcome, shadow_offset_x, shadow_offset_y
    )

    # --- VẼ TÊN NGƯỜI DÙNG ---
    # Lấy và điều chỉnh tên người dùng
    display_name = member.display_name
    
    # Cắt tên nếu quá dài
    font_name_base = get_font(FONT_PATH_NAME, FONT_SIZE_NAME_BASE)
    if draw.textlength(display_name, font=font_name_base) > NAME_TEXT_MAX_WIDTH:
        while draw.textlength(display_name + "...", font=font_name_base) > NAME_TEXT_MAX_WIDTH and len(display_name) > 0:
            display_name = display_name[:-1]
        display_name += "..."

    name_text_x = welcome_text_x # Bắt đầu tên từ cùng vị trí X với WELCOME
    name_text_y = welcome_text_y_pos + FONT_SIZE_WELCOME + 10 # Dưới chữ WELCOME một khoảng

    # Xử lý tên có dấu (ví dụ: tiếng Việt) để đảm bảo font hiển thị đúng
    # Thường không cần chia nhỏ nếu font hỗ trợ Unicode đầy đủ.
    # Tuy nhiên, nếu bạn thấy lỗi hiển thị ký tự đặc biệt, có thể cần font phức tạp hơn
    # hoặc xử lý từng phần. Tạm thời giữ nguyên cách vẽ thông thường.
    processed_name_parts = [(display_name, font_name_base)] # Giả định font hỗ trợ đầy đủ Unicode

    current_x = float(name_text_x)
    for char, font_to_use in processed_name_parts:
        # Vẽ bóng trước
        draw.text((int(current_x + shadow_offset_x), int(name_text_y + shadow_offset_y)), char, font=font_to_use, fill=shadow_color_name)
        # Vẽ chữ chính
        draw.text((int(current_x), int(name_text_y)), char, font=font_to_use, fill=stroke_color_for_name)
        
        current_x += draw.textlength(char, font=font_to_use)

    # --- VẼ DẤU GẠCH NGA ---
    line_start_x = name_text_x
    line_end_x = name_text_x + 100 # Chiều dài của dấu gạch
    line_y = name_text_y + FONT_SIZE_NAME_BASE + 5 # Dưới tên một khoảng
    line_color = stroke_color_for_name # Màu của dấu gạch theo màu stroke

    draw.line([(line_start_x, line_y), (line_end_x, line_y)], fill=line_color, width=5)

    # --- VẼ CHỮ ID ---
    id_text = f"ID: {member.id}"
    font_id = get_font(FONT_PATH_NAME, 20)
    id_text_x = line_end_x + 10 # Bên phải dấu gạch
    id_text_y = line_y - (font_id.getbbox(id_text)[3] / 2) - 2 # Canh giữa theo chiều dọc với dấu gạch
    id_color = (150, 150, 150) # Màu xám cho ID

    _draw_text_with_shadow(
        draw, id_text, font_id, id_text_x, id_text_y,
        id_color, (50, 50, 50), 2, 2 # Bóng tối hơn một chút
    )

    # --- VẼ CHỮ THÀNH VIÊN THỨ ... ---
    member_count_text = f"Thành viên thứ {member.guild.member_count} ✦" # Đã thêm ✦ vào đây
    font_member_count = get_font(FONT_PATH_NAME, 20)
    member_count_x = img.width - draw.textlength(member_count_text, font=font_member_count) - 20 # Canh phải
    member_count_y = img.height - font_member_count.getbbox(member_count_text)[3] - 20 # Canh dưới
    member_count_color = (150, 150, 150) # Màu xám

    _draw_text_with_shadow(
        draw, member_count_text, font_member_count, member_count_x, member_count_y,
        member_count_color, (50, 50, 50), 2, 2
    )

    # Lưu ảnh vào buffer và gửi
    byte_io = io.BytesIO()
    img.save(byte_io, format='PNG')
    byte_io.seek(0)
    return byte_io

# --- Các tác vụ của bot ---
@tasks.loop(minutes=1) # Tần suất kiểm tra trạng thái (có thể thay đổi)
async def activity_heartbeat():
    sleep_duration = random.randint(1 * 60, 3 * 60) # Ngủ ngẫu nhiên 1-3 phút
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

@tasks.loop(minutes=1) # Tần suất kiểm tra để gửi tin nhắn
async def random_message_sender():
    send_interval = random.randint(2 * 60, 5 * 60) # Ngủ ngẫu nhiên 2-5 phút
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
@app_commands.checks.has_permissions(administrator=True) # Chỉ quản trị viên mới dùng được lệnh này
async def testwelcome_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True) # Bot sẽ "đang nghĩ" để tránh timeout

    try:
        print(f"DEBUG: Đang tạo ảnh chào mừng cho {member_to_test.display_name}...")
        image_bytes = await create_welcome_image(member_to_test)
        await interaction.followup.send(file=discord.File(fp=image_bytes, filename='welcome_test.png'))
        print(f"DEBUG: Đã gửi ảnh test chào mừng cho {member_to_test.display_name} thông qua lệnh slash.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test: {e}")
        print(f"LỖỖI TEST: Có lỗi khi tạo hoặc gửi ảnh test: {e}")

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
        # Sử dụng await bot.start(TOKEN) thay vì bot.run(TOKEN)
        # để cho phép nó chạy trong một asyncio event loop đã tồn tại
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
