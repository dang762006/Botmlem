import discord
from discord.ext import commands, tasks # THÊM tasks VÀO ĐÂY
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
    except Exception as e:
        print(f"LỖI COLORTHIEF: Không thể lấy màu chủ đạo từ avatar: {e}")
        return None

TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)


# --- Định nghĩa hàm tạo ảnh chào mừng ---
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

    # --- TẠO LỚP NỀN HÌNH TRÒN PHÍA SAU AVATAR (CHỈ OPACITY, KHÔNG BLUR) ---
    blur_bg_size = avatar_size 
    blur_bg_x = avatar_x
    blur_bg_y = avatar_y

    # Màu nền với alpha 50% (128/255)
    blur_color_with_alpha = (*stroke_color_rgb, 128) 

    # Tạo một layer tạm thời chỉ chứa hình tròn màu với độ trong suốt
    blur_bg_raw_circle = Image.new('RGBA', (blur_bg_size, blur_bg_size), (0, 0, 0, 0))
    draw_blur_bg_raw = ImageDraw.Draw(blur_bg_raw_circle)
    draw_blur_bg_raw.ellipse((0, 0, blur_bg_size, blur_bg_size), fill=blur_color_with_alpha)
    
    # Dán lớp nền (hình tròn với độ trong suốt) vào ảnh chính.
    # KHÔNG ÁP DỤNG GAUSSIAN BLUR
    img.paste(blur_bg_raw_circle, (blur_bg_x, blur_bg_y), blur_bg_raw_circle)


    # --- VẼ STROKE (VIỀN) CÓ KHOẢNG TRỐNG TRONG SUỐT VỚI AVATAR ---
    stroke_thickness = 6 # Độ dày của viền stroke
    gap_size = 5         # Khoảng trống trong suốt giữa stroke và avatar (giá trị đã điều chỉnh)

    # Kích thước của vòng tròn ngoài cùng của stroke
    outer_stroke_diameter = avatar_size + (gap_size * 2) + (stroke_thickness * 2) 
    
    # Kích thước của vòng tròn bên trong của stroke (tạo khoảng trống trong suốt)
    inner_stroke_diameter = avatar_size + (gap_size * 2) 

    supersample_factor = 4
    
    # Tạo một layer tạm thời lớn hơn để vẽ stroke với anti-aliasing
    temp_stroke_layer_supersampled = Image.new('RGBA', 
                                                (outer_stroke_diameter * supersample_factor, outer_stroke_diameter * supersample_factor), 
                                                (0, 0, 0, 0))
    draw_temp_stroke = ImageDraw.Draw(temp_stroke_layer_supersampled)

    # Vẽ vòng tròn ngoài cùng (màu của stroke)
    draw_temp_stroke.ellipse(
        (0, 0, 
         outer_stroke_diameter * supersample_factor, outer_stroke_diameter * supersample_factor),
        fill=stroke_color
    )

    # Vẽ vòng tròn bên trong (trong suốt) để tạo ra khoảng trống
    inner_offset_x = (outer_stroke_diameter * supersample_factor - inner_stroke_diameter * supersample_factor) // 2
    inner_offset_y = (outer_stroke_diameter * supersample_factor - inner_stroke_diameter * supersample_factor) // 2

    draw_temp_stroke.ellipse(
        (inner_offset_x, inner_offset_y,
         inner_offset_x + inner_stroke_diameter * supersample_factor, inner_offset_y + inner_stroke_diameter * supersample_factor),
        fill=(0, 0, 0, 0) # Màu trong suốt
    )

    # Resize layer stroke về kích thước thực tế để áp dụng anti-aliasing
    stroke_final_image = temp_stroke_layer_supersampled.resize(
        (outer_stroke_diameter, outer_stroke_diameter), Image.LANCZOS
    )

    # Tính toán vị trí dán stroke lên ảnh chính
    stroke_paste_x = avatar_x - gap_size - stroke_thickness
    stroke_paste_y = avatar_y - gap_size - stroke_thickness

    img.paste(stroke_final_image, (stroke_paste_x, stroke_paste_y), stroke_final_image)


    # --- DÁN AVATAR CHÍNH VÀ ĐẢM BẢO NÓ TRÒN ĐÚNG KÍCH THƯỚC (210x210) ---
    # Tạo một layer tạm thời để vẽ avatar lên đó và áp dụng mask
    avatar_layer = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
    avatar_layer.paste(avatar_img, (0, 0)) 

    # Tạo mask hình tròn cho avatar với kích thước chính xác 210x210
    mask_supersample_factor = 4
    mask_raw_size = avatar_size * mask_supersample_factor
    circular_mask_raw = Image.new('L', (mask_raw_size, mask_raw_size), 0)
    draw_circular_mask_raw = ImageDraw.Draw(circular_mask_raw)
    draw_circular_mask_raw.ellipse((0, 0, mask_raw_size, mask_raw_size), fill=255)
    
    circular_mask_smoothed = circular_mask_raw.resize((avatar_size, avatar_size), Image.LANCZOS)

    try:
        original_alpha = avatar_layer.split()[3]
    except ValueError: 
        original_alpha = Image.new('L', circular_mask_smoothed.size, 255) # Use circular_mask_smoothed.size here

    final_alpha_mask = Image.composite(circular_mask_smoothed, Image.new('L', circular_mask_smoothed.size, 0), original_alpha)

    img.paste(avatar_layer, (avatar_x, avatar_y), final_alpha_mask)


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

# --- CÁC PHẦN MỚI THÊM VÀO ĐÂY ---

# ID kênh mới: 1379721599749591101
CHANNEL_ID_TO_SEND = 1379721599749591101 

@tasks.loop(seconds=60 * 60) # Lặp lại mỗi 15 phút (15 * 60 giây)
async def send_periodic_message():
    channel = bot.get_channel(CHANNEL_ID_TO_SEND)
    if channel:
        try:
            # Mở file nuoc.gif và gửi
            with open("nuoc.gif", "rb") as f:
                picture = discord.File(f)
                await channel.send(" **Uống nước đi người ae** 💦", file=picture)
            print(f"DEBUG: Đã gửi tin nhắn 'Uống nước đi ae' và ảnh nuoc.gif đến kênh {channel.name} (ID: {CHANNEL_ID_TO_SEND})")
        except FileNotFoundError:
            print(f"LỖI: Không tìm thấy file nuoc.gif trong cùng thư mục với main.py.")
            await channel.send("Uống nước đi ae (Lỗi: Không tìm thấy ảnh nuoc.gif).") # Gửi tin nhắn không có ảnh
        except discord.Forbidden:
            print(f"LỖI: Bot không có quyền gửi tin nhắn hoặc đính kèm file vào kênh {channel.name} (ID: {CHANNEL_ID_TO_SEND}).")
        except Exception as e:
            print(f"LỖI khi gửi tin nhắn tự động: {e}")
    else:
        print(f"LỖI: Không tìm thấy kênh với ID {CHANNEL_ID_TO_SEND} để gửi tin nhắn tự động.")


# --- Các sự kiện của bot ---
@bot.event
async def on_ready():
    print(f'{bot.user} đã sẵn sàng!')
    print('Bot đã online và có thể hoạt động.')
    try:
        if os.getenv('SYNC_SLASH_COMMANDS') == 'True':
            synced = await bot.tree.sync()  
            print(f"Đã đồng bộ {len(synced)} lệnh slash commands toàn cầu.")
        else:
            print("Bỏ qua đồng bộ lệnh slash. Đặt SYNC_SLASH_COMMANDS = True trên Render để đồng bộ nếu cần.")
    except Exception as e:
        print(f"LỖI ĐỒNG BỘ: Lỗi khi đồng bộ slash commands: {e}. Vui lòng kiểm tra quyền 'applications.commands' cho bot trên Discord Developer Portal.")
    
    # BẮT ĐẦU TÁC VỤ GỬI TIN NHẮN TỰ ĐỘNG KHI BOT ĐÃ SẴN SÀNG
    send_periodic_message.start()


@bot.event
async def on_member_join(member):
    channel_id = 1322848542758277202  # Kênh chào mừng bạn đã thiết lập trước đó
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

# --- Để bot luôn online trên Render ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=os.getenv('PORT', 8080))

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

bot.run(TOKEN)
