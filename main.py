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
    if clamp_min_l != 0.0 or clamp_max_l != 1.0: # Chỉ kẹp nếu có giới hạn cụ thể
        l = min(clamp_max_l, max(clamp_min_l, l)) 

    s = min(1.0, max(0.0, s * saturation_factor))

    return hsl_to_rgb(h, s, l)

# Hàm để lấy màu chủ đạo từ hình ảnh (chỉ lấy màu gốc, không điều chỉnh độ sáng ở đây)
async def get_dominant_color(image_bytes):
    try:
        f = io.BytesIO(image_bytes)
        # Colorthief có thể gặp vấn đề với hình ảnh trong suốt,
        # tạm thời chuyển đổi sang RGB để colorthief hoạt động,
        # nhưng vẫn giữ bytes gốc để xử lý avatar sau này.
        img_temp = Image.open(f).convert("RGB")
        f_temp = io.BytesIO()
        img_temp.save(f_temp, format='PNG') # Lưu lại dưới dạng PNG để colorthief đọc
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
        img = Image.open(background_image_path).convert("RGBA") # Đảm bảo ảnh nền cũng là RGBA
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

    # --- Xử lý Avatar người dùng và viền stroke ---
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    print(f"DEBUG: Đang tải avatar từ URL: {avatar_url}")
    avatar_bytes = None 
    async with aiohttp.ClientSession() as session:
        async with session.get(str(avatar_url)) as resp:
            if resp.status != 200:
                print(f"LỖI AVATAR: Không thể tải avatar cho {member.name}. Trạng thái: {resp.status}. Sử dụng avatar màu xám mặc định.")
                default_avatar_size = 210
                # Tạo avatar mặc định với kênh alpha đầy đủ (màu xám và hoàn toàn đục)
                avatar_img = Image.new('RGBA', (default_avatar_size, default_avatar_size), color=(100, 100, 100, 255))
            else:
                avatar_bytes = await resp.read() 
                data = io.BytesIO(avatar_bytes)
                # QUAN TRỌNG: Mở avatar ở chế độ "RGBA" để giữ kênh alpha
                avatar_img = Image.open(data).convert("RGBA") 
                print(f"DEBUG: Đã tải avatar cho {member.name}.")

    avatar_size = 210 # Kích thước avatar mong muốn là 210x210
    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

    avatar_x = img_width // 2 - avatar_size // 2
    avatar_y = int(img_height * 0.36) - avatar_size // 2

    # Lấy màu chủ đạo gốc từ avatar
    dominant_color_from_avatar = None
    if avatar_bytes: 
        dominant_color_from_avatar = await get_dominant_color(avatar_bytes)

    if dominant_color_from_avatar is None: 
        dominant_color_from_avatar = (0, 252, 233) # Default Cyan

    # CHUYỂN ĐỔI MÀU GỐC SANG HSL ĐỂ ĐÁNH GIÁ ĐỘ SÁNG BAN ĐẦU
    _, _, initial_l = rgb_to_hsl(*dominant_color_from_avatar)

    # Điều chỉnh màu gốc để làm màu stroke/tên: Tùy theo độ sáng của avatar
    if initial_l < 0.35: # Nếu màu avatar gốc quá tối (ngưỡng này có thể điều chỉnh)
        # Làm sáng nhiều và rực hơn để dễ đọc, đồng thời giới hạn độ sáng tối thiểu để đảm bảo nó luôn đủ sáng
        stroke_color_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=2.2, saturation_factor=1.8, clamp_min_l=0.5) 
    else: # Nếu màu avatar gốc đã đủ sáng hoặc sáng
        # Giữ tông màu gốc, chỉ làm rực và sáng hơn một chút để nổi bật
        stroke_color_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=1.15, saturation_factor=1.3)

    stroke_color = (*stroke_color_rgb, 255) 

    # --- 1. TẠO LỚP NỀN TRÒN CÙNG KÍCH THƯỚC AVATAR, GIẢM ĐỘ TRONG SUỐT ---
    # Kích thước lớp nền bằng kích thước avatar
    background_circle_size = avatar_size 
    
    # Tạo hình tròn màu sắc giống stroke với độ trong suốt
    # Độ trong suốt 100 (từ 0-255). Có thể điều chỉnh giá trị này.
    background_circle_color = (*stroke_color_rgb, 100) 
    background_circle_layer = Image.new('RGBA', (background_circle_size, background_circle_size), (0, 0, 0, 0))
    draw_background_circle = ImageDraw.Draw(background_circle_layer)
    draw_background_circle.ellipse((0, 0, background_circle_size, background_circle_size), fill=background_circle_color)
    
    # Vị trí lớp nền: trùng với vị trí của avatar
    img.paste(background_circle_layer, (avatar_x, avatar_y), background_circle_layer)


    # --- 2. VẼ VIỀN STROKE CHO AVATAR (Không thay đổi từ bản trước đó vì nó đã mượt) ---
    stroke_width = 6
    glow_radius = 5 

    # Tính toán kích thước tổng thể của vùng bao gồm avatar, viền và hiệu ứng glow
    outer_dim = avatar_size + (stroke_width * 2) + (glow_radius * 2)

    # Sử dụng supersampling để làm mượt đường tròn
    supersample_factor = 4 
    supersample_outer_dim = outer_dim * supersample_factor

    temp_stroke_img = Image.new('RGBA', (supersample_outer_dim, supersample_outer_dim), (0, 0, 0, 0))
    draw_temp_stroke = ImageDraw.Draw(temp_stroke_img)

    # Vẽ hình elip lớn nhất cho viền stroke
    draw_temp_stroke.ellipse(
        (0, 0, supersample_outer_dim, supersample_outer_dim), 
        fill=stroke_color
    )

    # Tạo mask cho phần bên trong để stroke chỉ là viền
    # Kích thước vòng tròn bên trong là kích thước avatar + 2 * glow_radius (để phần glow không bị che)
    inner_circle_size_px = (avatar_size + glow_radius*2) * supersample_factor
    inner_circle_offset_x = (supersample_outer_dim - inner_circle_size_px) // 2
    inner_circle_offset_y = (supersample_outer_dim - inner_circle_size_px) // 2

    draw_temp_stroke.ellipse(
        (inner_circle_offset_x, inner_circle_offset_y,
         inner_circle_offset_x + inner_circle_size_px, inner_circle_offset_y + inner_circle_size_px),
        fill=(0,0,0,0) # Phần này sẽ trong suốt
    )

    # Resize xuống kích thước thực tế để có hiệu ứng anti-aliasing mượt mà
    stroke_img_final = temp_stroke_img.resize((outer_dim, outer_dim), Image.LANCZOS)

    # Áp dụng hiệu ứng glow (làm mờ viền)
    glow_img = stroke_img_final.filter(ImageFilter.GaussianBlur(radius=glow_radius))

    # Tính toán vị trí dán cho viền và glow (phải nằm giữa avatar)
    paste_x = avatar_x - (outer_dim - avatar_size) // 2
    paste_y = avatar_y - (outer_dim - avatar_size) // 2

    # Dán hiệu ứng glow trước, sau đó là viền chính
    img.paste(glow_img, (paste_x, paste_y), glow_img)
    img.paste(stroke_img_final, (paste_x, paste_y), stroke_img_final)

    # --- 3. DÁN AVATAR CHÍNH (Đảm bảo đúng kích thước và cắt tròn đơn giản) ---
    # Tạo một mask hình tròn đơn giản, không cần supersampling quá phức tạp
    # vì yêu cầu là "không cần mask cho hình tròn mượt nữa" (ngụ ý cắt thẳng)
    avatar_mask = Image.new('L', (avatar_size, avatar_size), 0)
    draw_mask = ImageDraw.Draw(avatar_mask)
    draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255) # Vẽ hình tròn trực tiếp

    # Áp dụng mask cho avatar
    # Lấy kênh alpha của avatar gốc (nếu có)
    try:
        original_alpha = avatar_img.split()[3]
    except ValueError: # Nếu avatar không có kênh alpha (ví dụ: JPG), tạo kênh alpha hoàn toàn đục
        original_alpha = Image.new('L', avatar_img.size, 255)

    # Kết hợp mask hình tròn với kênh alpha gốc của avatar
    # Sử dụng Image.composite để đảm bảo độ trong suốt ban đầu của avatar (nếu có)
    combined_alpha_mask = Image.composite(avatar_mask, Image.new('L', avatar_mask.size, 0), original_alpha)

    # Dán avatar lên trên ảnh chính, sử dụng mask kết hợp để giữ hình tròn và độ trong suốt gốc
    img.paste(avatar_img, (avatar_x, avatar_y), combined_alpha_mask)


    y_offset_from_avatar = 20 
    welcome_text_y_pos = avatar_y + avatar_size + y_offset_from_avatar

    # --- VẼ CHỮ WELCOME ---
    welcome_text = "WELCOME"
    welcome_text_width = draw.textlength(welcome_text, font=font_welcome)
    welcome_text_x = (img_width - welcome_text_width) / 2

    # Đổ bóng cho chữ WELCOME: phải đậm và tối hơn
    shadow_color_welcome_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=0.6, saturation_factor=1.0, clamp_min_l=0.15, clamp_max_l=0.45) 
    shadow_color_welcome = (*shadow_color_welcome_rgb, 255) 

    draw.text((welcome_text_x + shadow_offset, welcome_text_y_pos + shadow_offset),
              welcome_text, font=font_welcome, fill=shadow_color_welcome)
    # Vẽ chữ WELCOME chính
    draw.text((welcome_text_x, welcome_text_y_pos),
              welcome_text, font=font_welcome, fill=(255, 255, 255)) 

    # --- VẼ TÊN NGƯỜI DÙNG ---
    name_text = member.display_name
    name_text_width = draw.textlength(name_text, font=font_name)
    name_text_x = (img_width - name_text_width) / 2

    welcome_bbox_for_height = draw.textbbox((0,0), welcome_text, font=font_welcome)
    welcome_actual_height = welcome_bbox_for_height[3] - welcome_bbox_for_height[1]
    name_text_y = welcome_text_y_pos + welcome_actual_height + 10  

    # Đổ bóng cho tên người dùng: phải đậm và tối hơn nữa
    shadow_color_name_rgb = adjust_color_brightness_saturation(dominant_color_from_avatar, brightness_factor=0.5, saturation_factor=1.0, clamp_min_l=0.1, clamp_max_l=0.4) 
    shadow_color_name = (*shadow_color_name_rgb, 255) 
    draw.text((name_text_x + shadow_offset, name_text_y + shadow_offset),
              name_text, font=font_name, fill=shadow_color_name)
    # Vẽ tên người dùng chính
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
    # Đồng bộ lệnh slash chỉ khi biến môi trường SYNC_SLASH_COMMANDS được đặt là 'True'
    # Điều này giúp tránh lỗi "Too Many Requests" khi bot khởi động lại nhiều lần
    if os.getenv('SYNC_SLASH_COMMANDS') == 'True':
        try:
            await bot.tree.sync()  
            print(f"Đã đồng bộ {len(bot.tree.get_commands())} lệnh slash commands toàn cầu.")
            # Sau khi đồng bộ, bạn NÊN thay đổi SYNC_SLASH_COMMANDS thành False trên Render
            # để tránh đồng bộ lại không cần thiết
        except Exception as e:
            print(f"LỖI ĐỒNG BỘ: Lỗi khi đồng bộ slash commands: {e}. Vui lòng kiểm tra quyền 'applications.commands' cho bot trên Discord Developer Portal.")
    else:
        print("Bỏ qua đồng bộ lệnh slash. Đặt SYNC_SLASH_COMMANDS = True trên Render để đồng bộ nếu cần.")


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
        print(f"Đã gửi ảnh chào mừng thành công cho {member.display_name}!")
    except Exception as e:
        print(f"LỖỖI CHÀO MỪNG: Lỗi khi tạo hoặc gửi ảnh chào mừng cho {member.display_name}: {e}")
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
        await interaction.followup.send(f"Có lỗi khi tạo hoặc gửi ảnh test. Vui lòng kiểm tra log bot.")
        print(f"LỖI TEST: Có lỗi khi tạo hoặc gửi ảnh test: {e}")

# --- Để bot luôn online trên Render (thay thế Replit) ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    # Sử dụng 0.0.0.0 để lắng nghe trên tất cả các interface,
    # phù hợp với môi trường triển khai như Render.
    app.run(host='0.0.0.0', port=os.getenv('PORT', 8080))

def keep_alive():
    t = Thread(target=run)
    t.start()

# Chạy webserver để giữ bot online
keep_alive()

# Chạy bot Discord
bot.run(TOKEN)
