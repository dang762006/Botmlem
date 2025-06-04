import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageSequence # Import ImageSequence
import io
import aiohttp
import asyncio      
from colorthief import ColorThief 
import random

# --- Các hàm xử lý màu sắc (giữ nguyên) ---
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

def paste_rotated_image(background_img, foreground_img, paste_center_x, paste_center_y, angle):
    rotated_fg = foreground_img.rotate(angle, expand=True)

    rotated_fg_width, rotated_fg_height = rotated_fg.size
    paste_x = int(paste_center_x - rotated_fg_width / 2)
    paste_y = int(paste_center_y - rotated_fg_height / 2)

    background_img.paste(rotated_fg, (paste_x, paste_y), rotated_fg)
    return background_img

# --- Định nghĩa hàm tạo ảnh chào mừng (giữ nguyên) ---
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
        dominant_color_from_avatar = (0, 252, 233) 

    _, _, initial_l = rgb_to_hsl(*dominant_color_from_avatar)

    if initial_l < 0.35: 
        stroke_color_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=2.2, saturation_factor=1.8, clamp_min_l=0.5) 
    else: 
        stroke_color_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=1.15, saturation_factor=1.3)

    stroke_color = (*stroke_color_rgb, 255) 

    stroke_width = 6
    glow_radius = 5 

    outer_dim = avatar_size + (stroke_width * 2) + (glow_radius * 2)

    supersample_factor = 4 
    supersample_outer_dim = outer_dim * supersample_factor

    temp_stroke_img = Image.new('RGBA', (supersample_outer_dim, supersample_outer_dim), (0, 0, 0, 0))
    draw_temp_stroke = ImageDraw.Draw(temp_stroke_img)

    draw_temp_stroke.ellipse(
        (0, 0, supersample_outer_dim, supersample_outer_dim), 
        fill=stroke_color
    )

    inner_circle_size_px = (avatar_size + glow_radius*2) * supersample_factor
    inner_circle_offset_x = (supersample_outer_dim - inner_circle_size_px) // 2
    inner_circle_offset_y = (supersample_outer_dim - inner_circle_size_px) // 2

    draw_temp_stroke.ellipse(
        (inner_circle_offset_x, inner_circle_offset_y,
         inner_circle_offset_x + inner_circle_size_px, inner_circle_offset_y + inner_circle_size_px),
        fill=(0,0,0,0) 
    )

    stroke_img_final = temp_stroke_img.resize((outer_dim, outer_dim), Image.LANCZOS)

    glow_img = stroke_img_final.filter(ImageFilter.GaussianBlur(radius=glow_radius))

    paste_x = avatar_x - (outer_dim - avatar_size) // 2
    paste_y = avatar_y - (outer_dim - avatar_size) // 2

    img.paste(glow_img, (paste_x, paste_y), glow_img)
    img.paste(stroke_img_final, (paste_x, paste_y), stroke_img_final)

    avatar_circular_mask = Image.new('L', (avatar_size, avatar_size), 0)
    draw_avatar_circular_mask = ImageDraw.Draw(avatar_circular_mask)
    draw_avatar_circular_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)

    try:
        original_alpha = avatar_img.split()[3]
    except ValueError:
        original_alpha = Image.new('L', avatar_img.size, 255)

    combined_alpha_mask = Image.composite(avatar_circular_mask, Image.new('L', avatar_circular_mask.size, 0), original_alpha)

    _, _, stroke_l = rgb_to_hsl(*stroke_color_rgb)

    calculated_alpha = int(max(50, min(200, 255 - (stroke_l * 150))))
    avatar_fill_color = (*stroke_color_rgb, calculated_alpha)


    avatar_bg_layer = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
    draw_avatar_bg = ImageDraw.Draw(avatar_bg_layer)
    draw_avatar_bg.ellipse((0, 0, avatar_size, avatar_size), fill=avatar_fill_color)

    img.paste(avatar_bg_layer, (avatar_x, avatar_y), avatar_bg_layer)

    img.paste(avatar_img, (avatar_x, avatar_y), combined_alpha_mask)

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

CHANNEL_ID_TO_SEND = 1379721599749591101 # ID kênh cho lời nhắc uống nước

async def create_water_reminder_image(guild: discord.Guild):
    print("DEBUG: Bắt đầu tạo ảnh nhắc nhở uống nước.")
    
    try:
        base_img_template = Image.open("1.png").convert("RGBA")
        img_width, img_height = base_img_template.size
        print(f"DEBUG: Đã tải 1.png với kích thước {img_width}x{img_height}.")
    except FileNotFoundError:
        print("LỖI: Không tìm thấy file 1.png. Tạo ảnh nền đen mặc định.")
        img_width, img_height = 800, 450
        base_img_template = Image.new('RGBA', (img_width, img_height), color=(0, 0, 0, 255))
    except Exception as e:
        print(f"LỖI khi tải 1.png: {e}. Tạo ảnh nền đen mặc định.")
        img_width, img_height = 800, 450
        base_img_template = Image.new('RGBA', (img_width, img_height), color=(0, 0, 0, 255))

    # 2. Lấy và xử lý avatar (ưu tiên người online, nếu không có thì lấy bot)
    online_members = [m for m in guild.members if not m.bot and m.status != discord.Status.offline]
    bots_in_guild = [m for m in guild.members if m.bot]

    selected_member_for_avatar = None
    if online_members:
        selected_member_for_avatar = random.choice(online_members)
        print(f"DEBUG: Đã chọn người dùng online: {selected_member_for_avatar.display_name}")
    elif bots_in_guild:
        selected_member_for_avatar = random.choice(bots_in_guild)
        print(f"DEBUG: Không có người dùng online, đã chọn bot: {selected_member_for_avatar.display_name}")
    else:
        print("DEBUG: Không có người dùng online và không có bot. Tạo avatar placeholder.")
        
    avatar_img = None 

    if selected_member_for_avatar:
        avatar_url = selected_member_for_avatar.avatar.url if selected_member_for_avatar.avatar else selected_member_for_avatar.default_avatar.url
        print(f"DEBUG: Đang tải avatar từ URL: {avatar_url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(avatar_url)) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()
                        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                    else:
                        print(f"LỖI AVATAR: Không tải được avatar cho {selected_member_for_avatar.display_name}. Status: {resp.status}")
                        avatar_img = Image.new('RGBA', (210, 210), color=(100, 100, 100, 255))
        except Exception as e:
            print(f"LỖI AVATAR: Exception khi tải avatar cho {selected_member_for_avatar.display_name}: {e}")
            avatar_img = Image.new('RGBA', (210, 210), color=(100, 100, 100, 255))
        
        avatar_size = 210
        avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)
        mask = Image.new('L', avatar_img.size, 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar_img.putalpha(mask)

    avatar_center_x = int(img_width * 0.49) 
    avatar_center_y = int(img_height * 0.38)

    # 3. Load và xử lý nuoc.gif (Lấy frame đầu tiên làm ảnh tĩnh)
    potion_image_path = "nuoc.gif" # Vẫn giữ tên file .gif để dễ dàng chuyển đổi lại
    potion_size = 150
    potion_center_x = int(img_width * 0.72)
    potion_center_y = int(img_height * 0.58)

    final_image = base_img_template.copy() # Bắt đầu với bản sao của ảnh nền

    try:
        with Image.open(potion_image_path) as potion_gif_raw:
            # Lấy frame đầu tiên và chuyển đổi sang RGBA
            potion_frame = potion_gif_raw.seek(0) # Đảm bảo quay về frame đầu tiên
            potion_frame = potion_gif_raw.convert("RGBA").resize((potion_size, potion_size), Image.LANCZOS)
            print(f"DEBUG: Đã tải frame đầu tiên từ {potion_image_path} (GIF) làm ảnh tĩnh.")
            
            if avatar_img: # Dán avatar nếu nó đã được tải/tạo thành công
                paste_rotated_image(final_image, avatar_img, avatar_center_x, avatar_center_y, -15)
            
            paste_rotated_image(final_image, potion_frame, potion_center_x, potion_center_y, 15)

    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy file {potion_image_path}. Tạo ảnh nhắc nhở không có lọ nước.")
        if avatar_img:
            paste_rotated_image(final_image, avatar_img, avatar_center_x, avatar_center_y, -15)
    except Exception as e:
        print(f"LỖI khi xử lý ảnh lọ nước {potion_image_path}: {e}. Tạo ảnh nhắc nhở không có lọ nước.")
        if avatar_img:
            paste_rotated_image(final_image, avatar_img, avatar_center_x, avatar_center_y, -15)

    # 4. Load và dán lớp hiệu ứng ánh sáng 2.png lên ảnh cuối cùng
    try:
        overlay_img = Image.open("2.png").convert("RGBA")
        overlay_img = overlay_img.resize((img_width, img_height), Image.LANCZOS)
        print(f"DEBUG: Đã tải 2.png.")
        final_image.paste(overlay_img, (0, 0), overlay_img) # Dán lên ảnh cuối cùng
    except FileNotFoundError:
        print("LỖI: Không tìm thấy file 2.png. Không thêm hiệu ứng ánh sáng.")
    except Exception as e:
        print(f"LỖI khi xử lý ảnh hiệu ứng 2.png: {e}. Không thêm hiệu ứng ánh sáng.")

    # Lưu ảnh cuối cùng dưới dạng PNG (vì không còn là GIF động)
    img_byte_arr = io.BytesIO()
    final_image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    print("DEBUG: Kết thúc tạo ảnh nhắc nhở uống nước (ảnh tĩnh).")
    return img_byte_arr


@bot.event
async def on_ready():
    print(f'{bot.user} đã sẵn sàng!')
    print('Bot đã online và có thể hoạt động.')
    try:
        synced = await bot.tree.sync()  
        print(f"Đã đồng bộ {len(synced)} lệnh slash commands toàn cầu.")
    except Exception as e:
        print(f"LỖI ĐỒNG BỘ: Lỗi khi đồng bộ slash commands: {e}. Vui lòng kiểm tra quyền 'applications.commands' cho bot trên Discord Developer Portal.")
    
    if not send_periodic_message.is_running():
        send_periodic_message.start()


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

@bot.tree.command(name="testnuoc", description="Tạo và gửi ảnh nhắc nhở uống nước.")
@app_commands.checks.has_permissions(administrator=True)
async def testnuoc_slash(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    channel_to_send = interaction.channel
    guild = interaction.guild

    if guild is None:
        await interaction.followup.send("LỖI: Không thể lấy thông tin server.")
        return

    try:
        print("DEBUG: Đang tạo ảnh nhắc nhở uống nước cho lệnh testnuoc...")
        image_bytes = await create_water_reminder_image(guild)
        # Gửi file là PNG vì giờ là ảnh tĩnh
        await channel_to_send.send(file=discord.File(fp=image_bytes, filename='water_reminder.png')) 
        await interaction.followup.send("Đã gửi ảnh nhắc nhở uống nước thành công!")
        print("DEBUG: Đã gửi ảnh nhắc nhở uống nước thành công qua lệnh testnuoc.")
    except Exception as e:
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh nhắc nhở: {e}")
        print(f"LỖI TESTNUOC: Có lỗi khi tạo hoặc gửi ảnh nhắc nhở: {e}")


@tasks.loop(seconds=60 * 60)
async def send_periodic_message():
    channel = bot.get_channel(CHANNEL_ID_TO_SEND)
    if channel:
        try:
            guild = channel.guild 
            if guild:
                water_reminder_image_bytes = await create_water_reminder_image(guild)
                # Gửi file là PNG vì giờ là ảnh tĩnh
                await channel.send(file=discord.File(fp=water_reminder_image_bytes, filename='water_reminder.png'))
                print(f"DEBUG: Đã gửi ảnh nhắc nhở uống nước định kỳ đến kênh {channel.name} (ID: {CHANNEL_ID_TO_SEND})")
            else:
                print(f"LỖI: Không tìm thấy guild cho kênh {channel.name}. (ID: {CHANNEL_ID_TO_SEND}).")
        except discord.Forbidden:
            print(f"LỖI: Bot không có quyền gửi tin nhắn hoặc đính kèm file vào kênh {channel.name} (ID: {CHANNEL_ID_TO_SEND}).")
        except Exception as e:
            print(f"LỖI khi gửi tin nhắn tự động: {e}")
    else:
        print(f"LỖI: Không tìm thấy kênh với ID {CHANNEL_ID_TO_SEND} để gửi tin nhắn tự động.")


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
