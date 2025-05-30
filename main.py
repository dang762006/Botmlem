import discord
from discord.ext import commands
from discord import app_commands
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import io
import aiohttp
import asyncio
from colorthief import ColorThief

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
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q

    r_new = hsl_to_rgb_component(p, q, h + 1/3)
    g_new = hsl_to_rgb_component(p, q, h)
    b_new = hsl_to_rgb_component(p, q, h - 1/3)

    return (int(r_new * 255), int(g_new * 255), int(b_new * 255))

def adjust_color_brightness_saturation(rgb_color, brightness_factor=1.0, saturation_factor=1.0, clamp_min_l=0.0, clamp_max_l=1.0):
    h, s, l = rgb_to_hsl(*rgb_color)

    # Áp dụng brightness_factor trước
    l = l * brightness_factor

    # Sau đó mới kẹp giá trị L vào phạm vi mong muốn (chỉ áp dụng nếu có giới hạn)
    if clamp_min_l != 0.0 or clamp_max_l != 1.0:
        l = min(clamp_max_l, max(clamp_min_l, l))

    s = min(1.0, max(0.0, s * saturation_factor))

    return hsl_to_rgb(h, s, l)

async def get_dominant_color(image_bytes):
    try:
        f = io.BytesIO(image_bytes)
        img_temp = Image.open(f).convert("RGB")
        f_temp = io.BytesIO()
        img_temp.save(f_temp, format='PNG')
        f_temp.seek(0)

        color_thief = ColorThief(f_temp)
        dominant_color_rgb = color_thief.get_color(quality=1)
        return dominant_color_rgb
    except Exception as e:
        print(f"LỖI COLORTHIEF: Không thể lấy màu chủ đạo từ avatar: {e}")
        return None

TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)


async def create_welcome_image(member):
    font_path_preferred = "1FTV-Designer.otf"

    font_welcome = None
    font_name = None

    try:
        font_welcome = ImageFont.truetype(font_path_preferred, 60)
        font_name = ImageFont.truetype(font_path_preferred, 34)
        print(f"DEBUG: Đã tải font thành công: {font_path_preferred}")
    except Exception as e:
        print(f"LỖI FONT: Không thể tải font '{font_path_preferred}'. Sử dụng font mặc định với kích thước cố định. Chi tiết: {e}")
        try:
            font_welcome = ImageFont.truetype("arial.ttf", 60)
            font_name = ImageFont.truetype("arial.ttf", 34)
            print("DEBUG: Đã sử dụng font Arial.ttf (thay thế cho 1FTV-Designer.otf).")
        except Exception:
            font_welcome = ImageFont.load_default().font_variant(size=60)
            font_name = ImageFont.load_default().font_variant(size=34)
            print("DEBUG: Đã sử dụng font mặc định của Pillow và ép kích thước (thay thế cho 1FTV-Designer.otf).")

    shadow_offset = 3

    background_image_path = "welcome.png"
    try:
        img = Image.open(background_image_path).convert("RGBA")
        img_width, img_height = img.size
        print(f"DEBUG: Đã tải ảnh nền: {background_image_path} với kích thước {img_width}x{img_height}")
    except FileNotFoundError:
        print(f"LỖI ẢNH NỀN: Không tìm thấy ảnh nền '{background_image_path}'. Sử dụng nền màu mặc định.")
        img_width, img_height = 872, 430
        img = Image.new('RGBA', (img_width, img_height), color=(0, 0, 0, 255))
    except Exception as e:
        print(f"LỖI ẢNH NỀN: Lỗi khi mở ảnh nền: {e}. Sử dụng nền màu mặc định.")
        img_width, img_height = 872, 430
        img = Image.new('RGBA', (img_width, img_height), color=(0, 0, 0, 255))

    draw = ImageDraw.Draw(img)

    # --- Xử lý Avatar người dùng ---
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    print(f"DEBUG: Đang tải avatar từ URL: {avatar_url}")
    avatar_bytes = None
    async with aiohttp.ClientSession() as session:
        async with session.get(str(avatar_url)) as resp:
            if resp.status != 200:
                print(f"LỖI AVATAR: Không thể tải avatar cho {member.name}. Trạng thái: {resp.status}. Sử dụng avatar màu xám mặc định.")
                default_avatar_size = 210
                avatar_img = Image.new('RGBA', (default_avatar_size, default_avatar_size), color=(100, 100, 100, 255))
            else:
                avatar_bytes = await resp.read()
                data = io.BytesIO(avatar_bytes)
                avatar_img = Image.open(data).convert("RGBA")
                print(f"DEBUG: Đã tải avatar cho {member.name}.")

    avatar_size = 210
    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

    avatar_x = img_width // 2 - avatar_size // 2
    avatar_y = int(img_height * 0.36) - avatar_size // 2

    dominant_color_from_avatar = None
    if avatar_bytes:
        dominant_color_from_avatar = await get_dominant_color(avatar_bytes)

    if dominant_color_from_avatar is None:
        dominant_color_from_avatar = (0, 252, 233) # Default Cyan

    _, _, initial_l = rgb_to_hsl(*dominant_color_from_avatar)

    if initial_l < 0.35:
        stroke_color_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=2.2, saturation_factor=1.8, clamp_min_l=0.5)
    else:
        stroke_color_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=1.15, saturation_factor=1.3)

    stroke_color = (*stroke_color_rgb, 255)

    # --- KHOẢNG CÁCH GIỮA AVATAR VÀ STROKE (Tạo khoảng trống) ---
    padding_between_avatar_and_stroke = 5 # Điều chỉnh giá trị này để thay đổi khoảng cách

    # --- KÍCH THƯỚC VÀ VỊ TRÍ CHO STROKE ---
    stroke_width = 6
    # Stroke_outer_size bao gồm avatar + 2 lần padding + 2 lần stroke_width
    stroke_outer_size = avatar_size + (padding_between_avatar_and_stroke * 2) + (stroke_width * 2)
    stroke_x = avatar_x - padding_between_avatar_and_stroke - stroke_width
    stroke_y = avatar_y - padding_between_avatar_and_stroke - stroke_width

    # --- 1. VẼ HIỆU ỨNG GLOW (LỚP DƯỚI CÙNG) ---
    glow_outer_size = stroke_outer_size + 40 # Glow sẽ lớn hơn stroke
    glow_x = stroke_x - (glow_outer_size - stroke_outer_size) // 2
    glow_y = stroke_y - (glow_outer_size - stroke_outer_size) // 2

    glow_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw_glow = ImageDraw.Draw(glow_layer)

    _, _, stroke_l = rgb_to_hsl(*stroke_color_rgb)
    calculated_alpha = int(max(50, min(200, 255 - (stroke_l * 150))))
    glow_color_with_alpha = (*stroke_color_rgb, calculated_alpha)

    draw_glow.ellipse((glow_x, glow_y, glow_x + glow_outer_size, glow_y + glow_outer_size), fill=glow_color_with_alpha)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=10))
    img.paste(glow_layer, (0, 0), glow_layer)


    # --- 2. VẼ VIỀN STROKE (VIỀN MÀU) ---
    stroke_temp_img = Image.new('RGBA', (stroke_outer_size, stroke_outer_size), (0, 0, 0, 0))
    draw_stroke_temp = ImageDraw.Draw(stroke_temp_img)
    draw_stroke_temp.ellipse((0, 0, stroke_outer_size, stroke_outer_size), fill=stroke_color)

    # Đục lỗ bên trong để tạo thành viền (lỗ này bao gồm avatar và khoảng trống)
    inner_hole_size_stroke = avatar_size + (padding_between_avatar_and_stroke * 2)
    inner_hole_x_stroke = (stroke_outer_size - inner_hole_size_stroke) // 2
    inner_hole_y_stroke = (stroke_outer_size - inner_hole_size_stroke) // 2

    draw_stroke_temp.ellipse(
        (inner_hole_x_stroke, inner_hole_y_stroke,
         inner_hole_x_stroke + inner_hole_size_stroke, inner_hole_y_stroke + inner_hole_size_stroke),
        fill=(0, 0, 0, 0)
    )
    img.paste(stroke_temp_img, (stroke_x, stroke_y), stroke_temp_img)


    # --- 3. VẼ LỚP NỀN MỜ DƯỚI AVATAR (LỚP TRONG XUỐT MÀ BẠN KHOANH TRÒN) ---
    # Lớp này nằm ngay dưới avatar, có kích thước tương đương với avatar, hoặc lớn hơn một chút
    avatar_background_blur_size = avatar_size # Có thể tăng thêm 5-10 pixel nếu muốn nó rộng hơn avatar một chút
    avatar_background_blur_x = avatar_x - (avatar_background_blur_size - avatar_size) // 2
    avatar_background_blur_y = avatar_y - (avatar_background_blur_size - avatar_size) // 2

    avatar_background_blur_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw_blur_bg = ImageDraw.Draw(avatar_background_blur_layer)

    # Vẽ hình tròn màu đen với độ trong suốt nhất định
    draw_blur_bg.ellipse((avatar_background_blur_x, avatar_background_blur_y,
                          avatar_background_blur_x + avatar_background_blur_size,
                          avatar_background_blur_y + avatar_background_blur_size),
                         fill=(0, 0, 0, 100)) # Màu đen với độ trong suốt 100 (điều chỉnh cho phù hợp)

    # Áp dụng blur cho lớp nền mờ
    avatar_background_blur_layer = avatar_background_blur_layer.filter(ImageFilter.GaussianBlur(radius=5)) # Độ mờ có thể điều chỉnh
    img.paste(avatar_background_blur_layer, (0, 0), avatar_background_blur_layer)


    # --- 4. DÁN AVATAR CHÍNH (LỚP TRÊN CÙNG) ---
    avatar_circular_mask = Image.new('L', (avatar_size, avatar_size), 0)
    draw_avatar_circular_mask = ImageDraw.Draw(avatar_circular_mask)
    draw_avatar_circular_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)

    try:
        original_alpha = avatar_img.split()[3]
    except ValueError:
        original_alpha = Image.new('L', avatar_img.size, 255)

    combined_alpha_mask = Image.composite(avatar_circular_mask, Image.new('L', avatar_circular_mask.size, 0), original_alpha)
    img.paste(avatar_img, (avatar_x, avatar_y), combined_alpha_mask)


    y_offset_from_avatar = 20
    welcome_text_y_pos = avatar_y + avatar_size + y_offset_from_avatar

    # --- VẼ CHỮ WELCOME ---
    welcome_text = "WELCOME"
    welcome_text_width = draw.textlength(welcome_text, font=font_welcome)
    welcome_text_x = (img_width - welcome_text_width) / 2

    shadow_color_welcome_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=0.6, saturation_factor=1.0, clamp_min_l=0.15, clamp_max_l=0.45)
    shadow_color_welcome = (*shadow_color_welcome_rgb, 255)

    draw.text((welcome_text_x + shadow_offset, welcome_text_y_pos + shadow_offset),
              welcome_text, font=font_welcome, fill=shadow_color_welcome)
    draw.text((welcome_text_x, welcome_text_y_pos),
              welcome_text, font=font_welcome, fill=(255, 255, 255))

    # --- VẼ TÊN NGƯỜI DÙNG ---
    name_text = member.display_name
    name_text_width = draw.textlength(name_text, font=font_name)
    name_text_x = (img_width - name_text_width) / 2

    welcome_bbox_for_height = draw.textbbox((0,0), welcome_text, font=font_welcome)
    welcome_actual_height = welcome_bbox_for_height[3] - welcome_bbox_for_height[1]
    name_text_y = welcome_text_y_pos + welcome_actual_height + 10

    shadow_color_name_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=0.5, saturation_factor=1.0, clamp_min_l=0.1, clamp_max_l=0.4)
    shadow_color_name = (*shadow_color_name_rgb, 255)
    draw.text((name_text_x + shadow_offset, name_text_y + shadow_offset),
              name_text, font=font_name, fill=shadow_color_name)
    draw.text((name_text_x, name_text_y),
              name_text, font=font_name, fill=stroke_color)

    # --- THÊM ĐƯỜNG KẺ TRANG TRÍ DƯỚI TÊN ---
    line_color = stroke_color_rgb
    line_thickness = 3
    line_length = 150

    line_x1 = img_width // 2 - line_length // 2
    line_x2 = img_width // 2 + line_length // 2

    name_bbox_for_height = draw.textbbox((0,0), name_text, font=font_name)
    name_actual_height = name_bbox_for_height[3] - name_bbox_for_height[1]
    line_y = name_text_y + name_actual_height + 10

    draw.line([(line_x1, line_y), (line_x2, line_y)], fill=line_color, width=line_thickness)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# --- Các sự kiện của bot ---
@bot.event
async def on_ready():
    print(f'{bot.user} đã sẵn sàng!')
    print('Bot đã online và có thể hoạt động.')
    if os.getenv('SYNC_SLASH_COMMANDS') == 'True':
        try:
            synced = await bot.tree.sync()
            print(f"Đã đồng bộ {len(synced)} lệnh slash commands toàn cầu.")
            print("LƯU Ý: Hãy nhớ xóa biến môi trường SYNC_SLASH_COMMANDS trên Render HOẶC đặt lại thành 'False' sau khi các lệnh đã được đồng bộ để tránh bị rate limit.")
        except Exception as e:
            print(f"LỖI ĐỒNG BỘ: Lỗi khi đồng bộ slash commands: {e}. Vui lòng kiểm tra quyền 'applications.commands' cho bot trên Discord Developer Portal.")
    else:
        print("Bỏ qua việc đồng bộ slash commands. Để đồng bộ lại, hãy đặt biến môi trường SYNC_SLASH_COMMANDS = 'True' và khởi động lại bot.")

@bot.event
async def on_member_join(member):
    channel_id = 1322848542758277202
    channel = bot.get_channel(channel_id)

    if channel is None:
        print(f"LỖI KÊNH: Không tìm thấy kênh với ID {channel_id}.")
        return

    if not channel.permissions_for(member.guild.me).send_messages or \
       not channel.permissions_for(member.guild.me).attach_files:
        print(f"LỖI QUYỀN: Bot không có quyền gửi tin nhắn hoặc đính kèm file trong kênh {channel.name} (ID: {channel_id}).")
        return

    try:
        image_bytes = await create_welcome_image(member)
        await channel.send(f"**<a:cat2:1323314096040448145>** **Chào mừng {member.mention} đã đến {member.guild.name}**",
                           file=discord.File(fp=image_bytes, filename='welcome.png'))
        print("Đã gửi ảnh chào mừng thành công!")
    except Exception as e:
        print(f"LỖỖI CHÀO MỪNG: Lỗi khi tạo hoặc gửi ảnh chào mừng: {e}")
        await channel.send(f"Chào mừng {member.mention} đã đến với {member.guild.name}!")

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
        print("DEBUG: Đã gửi ảnh test chào mừng thành công!")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test: {e}")
        print(f"LỖI TEST: Có lỗi khi tạo hoặc gửi ảnh test: {e}")

# --- Để bot luôn online trên Replit (Bạn có thể xóa phần này nếu chỉ dùng Render) ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

bot.run(TOKEN)
