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
    l = l * brightness_factor
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
    except Exception:
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
    except Exception:
        try:
            font_welcome = ImageFont.truetype("arial.ttf", 60)
            font_name = ImageFont.truetype("arial.ttf", 34)
        except Exception:
            font_welcome = ImageFont.load_default().font_variant(size=60)
            font_name = ImageFont.load_default().font_variant(size=34)

    shadow_offset = 3

    background_image_path = "welcome.png"
    try:
        img = Image.open(background_image_path).convert("RGBA")
        img_width, img_height = img.size
    except FileNotFoundError:
        img_width, img_height = 872, 430
        img = Image.new('RGBA', (img_width, img_height), color=(0, 0, 0, 255))
    except Exception:
        img_width, img_height = 872, 430
        img = Image.new('RGBA', (img_width, img_height), color=(0, 0, 0, 255))

    draw = ImageDraw.Draw(img)

    # --- Xử lý Avatar người dùng ---
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    avatar_bytes = None
    async with aiohttp.ClientSession() as session:
        async with session.get(str(avatar_url)) as resp:
            if resp.status != 200:
                default_avatar_size = 210
                avatar_img = Image.new('RGBA', (default_avatar_size, default_avatar_size), color=(100, 100, 100, 255))
            else:
                avatar_bytes = await resp.read()
                data = io.BytesIO(avatar_bytes)
                avatar_img = Image.open(data).convert("RGBA")

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

    # --- KHOẢNG CÁCH GIỮA AVATAR VÀ STROKE ---
    padding_between_avatar_and_stroke = 5
    stroke_width = 6

    # --- Kích thước và vị trí của vòng tròn stroke ---
    actual_stroke_outer_diameter = avatar_size + (padding_between_avatar_and_stroke * 2) + (stroke_width * 2)
    stroke_bbox_x = avatar_x - padding_between_avatar_and_stroke - stroke_width
    stroke_bbox_y = avatar_y - padding_between_avatar_and_stroke - stroke_width
    
    # --- 1. LOẠI BỎ HOÀN TOÀN LỚP NỀN MỜ DƯỚI AVATAR (Như bạn yêu cầu) ---
    # Phần này đã được bỏ qua. Avatar sẽ được dán trực tiếp sau stroke.


    # --- 2. VẼ VIỀN STROKE (VIỀN MÀU) - Đảm bảo khoảng trống trong suốt ---
    # Tạo một layer alpha mask cho stroke
    stroke_mask_size_large = actual_stroke_outer_diameter + 20 # Kích thước lớn hơn để anti-aliasing
    stroke_mask_raw = Image.new('L', (stroke_mask_size_large, stroke_mask_size_large), 0)
    draw_stroke_mask_raw = ImageDraw.Draw(stroke_mask_raw)

    # Vẽ vòng tròn ngoài (màu trắng)
    draw_stroke_mask_raw.ellipse((0, 0, stroke_mask_size_large, stroke_mask_size_large), fill=255)

    # Vẽ vòng tròn trong (màu đen) để tạo lỗ, kích thước bằng avatar + 2 lần padding,
    # đặt ở vị trí trung tâm của mask thô
    inner_hole_diameter_raw = avatar_size + (padding_between_avatar_and_stroke * 2) + 20
    inner_hole_x_raw = (stroke_mask_size_large - inner_hole_diameter_raw) // 2
    inner_hole_y_raw = (stroke_mask_size_large - inner_hole_diameter_raw) // 2
    draw_stroke_mask_raw.ellipse((inner_hole_x_raw, inner_hole_y_raw,
                                  inner_hole_x_raw + inner_hole_diameter_raw,
                                  inner_hole_y_raw + inner_hole_diameter_raw), fill=0)

    # Thu nhỏ mask để áp dụng anti-aliasing
    stroke_alpha_mask_smoothed = stroke_mask_raw.resize((actual_stroke_outer_diameter, actual_stroke_outer_diameter), Image.LANCZOS)

    # Tạo layer màu cho stroke và áp dụng alpha mask
    stroke_colored_layer = Image.new('RGBA', (actual_stroke_outer_diameter, actual_stroke_outer_diameter), stroke_color)
    stroke_colored_layer.putalpha(stroke_alpha_mask_smoothed)

    img.paste(stroke_colored_layer, (stroke_bbox_x, stroke_bbox_y), stroke_colored_layer)


    # --- 3. DÁN AVATAR CHÍNH ---
    # Tăng kích thước mask thô của avatar để chống cắt lẹm hiệu quả hơn và giúp tròn hơn
    avatar_mask_buffer = 20 # Buffer thêm để mask rộng hơn avatar gốc nhiều hơn
    avatar_mask_smooth_size = avatar_size + avatar_mask_buffer * 2 # Kích thước lớn hơn cho mask thô
    
    avatar_circular_mask_raw = Image.new('L', (avatar_mask_smooth_size, avatar_mask_smooth_size), 0)
    draw_avatar_circular_mask_raw = ImageDraw.Draw(avatar_circular_mask_raw)
    
    # Vẽ hình elip trên mask thô (vị trí (buffer, buffer) là để hình tròn nằm giữa)
    draw_avatar_circular_mask_raw.ellipse((avatar_mask_buffer, avatar_mask_buffer, 
                                           avatar_size + avatar_mask_buffer, avatar_size + avatar_mask_buffer), fill=255)
    
    # Thu nhỏ mask thô về kích thước avatar thật sự
    avatar_circular_mask_smoothed = avatar_circular_mask_raw.resize((avatar_size, avatar_size), Image.LANCZOS)

    try:
        original_alpha = avatar_img.split()[3]
    except ValueError:
        original_alpha = Image.new('L', avatar_img.size, 255)

    # Kết hợp mask hình tròn mượt mà với kênh alpha gốc của avatar
    combined_alpha_mask = Image.composite(avatar_circular_mask_smoothed, Image.new('L', avatar_circular_mask_smoothed.size, 0), original_alpha)
    img.paste(avatar_img, (avatar_x, avatar_y), combined_alpha_mask)

    # --- VẼ CHỮ VÀ ĐƯỜNG KẺ ---
    y_offset_from_avatar = 20
    welcome_text_y_pos = avatar_y + avatar_size + y_offset_from_avatar

    welcome_text = "WELCOME"
    welcome_text_width = draw.textlength(welcome_text, font=font_welcome)
    welcome_text_x = (img_width - welcome_text_width) / 2

    shadow_color_welcome_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=0.6, saturation_factor=1.0, clamp_min_l=0.15, clamp_max_l=0.45)
    shadow_color_welcome = (*shadow_color_welcome_rgb, 255)

    draw.text((welcome_text_x + shadow_offset, welcome_text_y_pos + shadow_offset),
              welcome_text, font=font_welcome, fill=shadow_color_welcome)
    draw.text((welcome_text_x, welcome_text_y_pos),
              welcome_text, font=font_welcome, fill=(255, 255, 255))

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
    # Chỉ đồng bộ 1 lần khi cần thiết, sau đó đặt SYNC_SLASH_COMMANDS = False trên Render
    if os.getenv('SYNC_SLASH_COMMANDS') == 'True':
        try:
            await bot.tree.sync()
            print("Đã đồng bộ lệnh slash.")
        except Exception as e:
            print(f"Lỗi khi đồng bộ lệnh slash: {e}")
    else:
        print("Bot đã sẵn sàng và không đồng bộ lệnh slash.")

@bot.event
async def on_member_join(member):
    channel_id = 1322848542758277202
    channel = bot.get_channel(channel_id)

    if channel is None:
        return

    if not channel.permissions_for(member.guild.me).send_messages or \
       not channel.permissions_for(member.guild.me).attach_files:
        return

    try:
        image_bytes = await create_welcome_image(member)
        await channel.send(f"**<a:cat2:1323314096040448145>** **Chào mừng {member.mention} đã đến {member.guild.name}**",
                           file=discord.File(fp=image_bytes, filename='welcome.png'))
    except Exception as e:
        print(f"Lỗi khi xử lý thành viên mới {member.display_name}: {e}")
        await channel.send(f"Chào mừng {member.mention} đã đến với {member.guild.name}!")

@bot.tree.command(name="testwelcome", description="Tạo và gửi ảnh chào mừng cho người dùng.")
@app_commands.describe(user="Người dùng bạn muốn test (mặc định là chính bạn).")
@app_commands.checks.has_permissions(administrator=True)
async def testwelcome_slash(interaction: discord.Interaction, user: discord.Member = None):
    member_to_test = user if user else interaction.user
    await interaction.response.defer(thinking=True)

    try:
        image_bytes = await create_welcome_image(member_to_test)
        await interaction.followup.send(file=discord.File(fp=image_bytes, filename='welcome_test.png'))
    except Exception as e:
        print(f"Lỗi khi tạo hoặc gửi ảnh test: {e}")
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test. Vui lòng kiểm tra log bot.")

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
