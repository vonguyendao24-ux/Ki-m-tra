import discord
import os
import json
import uuid
import datetime
from discord import app_commands, ui
from discord.ext import commands
from flask import Flask
from threading import Thread

# ==========================================
# 🌐 KEEP ALIVE SYSTEM
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "HQ System is Online and Running!"

def run_server():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_server)
    t.start()

# ==========================================
# 🗄️ DATABASE MANAGEMENT
# ==========================================
DATA_FILE = "vpoas_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"blacklist": {}, "warns": {}}
    
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Đảm bảo cấu trúc data không bị lỗi
            if "blacklist" not in data:
                data["blacklist"] = {}
            if "warns" not in data:
                data["warns"] = {}
            return data
    except:
        return {"blacklist": {}, "warns": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# ==========================================
# 💻 MODERN ACTIVITY UI (ĐIỂM DANH)
# ==========================================
class ActivityView(ui.View):
    def __init__(self, target_role: discord.Role, note: str, message: str):
        super().__init__(timeout=None)
        self.target_role = target_role
        self.note = note
        self.message = message
        self.verified_users = set()
        self.start_time = datetime.datetime.now()

    def build_embed(self):
        # Tính toán số lượng
        real_members = [m for m in self.target_role.members if not m.bot]
        total = len(real_members)
        verified = len(self.verified_users)
        unverified = total - verified
        
        # Đổi màu xanh nếu đã xong, đỏ nếu chưa xong
        color = 0x57F287 if unverified == 0 else 0xED4245
        
        # Tạo thanh tiến trình hiện đại
        percent = (verified / total) * 100 if total > 0 else 0
        filled_blocks = int(percent / 10)
        progress_bar = "█" * filled_blocks + "░" * (10 - filled_blocks)

        # Xây dựng Embed
        embed = discord.Embed(title="📊 SYSTEM ACTIVITY CHECK", color=color)
        embed.description = f"**TARGET UNIT:** {self.target_role.mention}\n> {self.note}"
        
        start_str = self.start_time.strftime('%H:%M:%S')
        embed.add_field(name="⏱️ Start Time", value=f"`{start_str}`", inline=True)
        embed.add_field(name="🟢 Verified", value=f"`{verified}/{total}` personnel", inline=True)
        embed.add_field(name="🔴 Unverified", value=f"`{unverified}` personnel", inline=True)
        embed.add_field(name="📈 Progress", value=f"`[{progress_bar}] {percent:.1f}%`", inline=False)
        
        if self.message:
            embed.add_field(name="📣 Commander's Message", value=f"```{self.message}```", inline=False)
            
        status_text = "COMPLETED" if unverified == 0 else "IN PROGRESS"
        system_id = int(self.start_time.timestamp())
        embed.set_footer(text=f"System ID: {system_id} • Status: {status_text}")
        
        return embed

    @ui.button(label="VERIFY PRESENCE", style=discord.ButtonStyle.blurple, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        # Kiểm tra xem có đúng Role không
        if self.target_role not in interaction.user.roles:
            return await interaction.response.send_message("❌ Access Denied: You are not assigned to this unit.", ephemeral=True)
        
        # Kiểm tra xem đã điểm danh chưa
        if interaction.user.id in self.verified_users:
            return await interaction.response.send_message("⚠️ Verification already logged.", ephemeral=True)
        
        # Ghi nhận điểm danh và cập nhật tin nhắn
        self.verified_users.add(interaction.user.id)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

# ==========================================
# 🤖 BOT INITIALIZATION
# ==========================================
class ModernBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        
    async def setup_hook(self):
        await self.tree.sync()
        print(f"HQ System is Online: {self.user.name}")

bot = ModernBot()

# Tự động ban nếu phát hiện người nằm trong Blacklist tham gia server
@bot.event
async def on_member_join(member):
    data = load_data()
    if str(member.id) in data["blacklist"]:
        try:
            await member.ban(reason="HQ Auto-Ban: Blacklisted Personnel")
        except:
            pass

# ==========================================
# ⚡ HQ COMMANDS (LỆNH QUẢN TRỊ HIỆN ĐẠI)
# ==========================================

# 1. ANNOUNCE COMMAND (THÔNG BÁO)
@bot.tree.command(name="announce", description="Broadcast a modern system announcement")
@app_commands.checks.has_permissions(administrator=True)
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, title: str, content: str, ping_role: discord.Role = None):
    embed = discord.Embed(title=f"📢 {title.upper()}", description=content, color=0x5865F2)
    embed.timestamp = datetime.datetime.now()
    embed.set_footer(text=f"Authorized by {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
    
    ping_text = ping_role.mention if ping_role else ""
    await channel.send(content=ping_text, embed=embed)
    await interaction.response.send_message("✅ Dispatch successful.", ephemeral=True)

# 2. ACTIVITY CHECK COMMAND (TẠO ĐIỂM DANH)
@bot.tree.command(name="activity_check", description="Initiate a unit roll call")
@app_commands.checks.has_permissions(administrator=True)
async def activity_check(interaction: discord.Interaction, role: discord.Role, note: str, message: str = "Acknowledge immediately."):
    view = ActivityView(target_role=role, note=note, message=message)
    await interaction.response.send_message(embed=view.build_embed(), view=view)

# 3. BLACKLIST COMMAND (CẤM CỬA & TẠO THREAD)
@bot.tree.command(name="blacklist", description="Blacklist user & secure evidence")
@app_commands.checks.has_permissions(administrator=True)
async def blacklist(interaction: discord.Interaction, user_id: str, roblox_name: str, roblox_url: str, violation: str, game_url: str, note: str = "N/A"):
    data = load_data()
    uid_str = str(user_id)
    incident_id = str(uuid.uuid4())[:8].upper()
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Lưu vào database
    data["blacklist"][uid_str] = {
        "uuid": incident_id, 
        "roblox_name": roblox_name, 
        "roblox_url": roblox_url, 
        "violation": violation, 
        "game": game_url, 
        "note": note, 
        "date": current_time, 
        "staff": interaction.user.name
    }
    save_data(data)
    
    # Tạo Embed hiển thị
    embed = discord.Embed(title="🚫 TARGET BLACKLISTED", color=0x2b2d31)
    embed.add_field(name="👤 Roblox Identity", value=f"[{roblox_name}]({roblox_url})", inline=True)
    embed.add_field(name="🆔 Discord ID", value=f"`{user_id}`", inline=True)
    embed.add_field(name="⚠️ Violation Record", value=f"```{violation}```", inline=False)
    embed.add_field(name="📍 Origin Server", value=f"[Server Link]({game_url})", inline=True)
    embed.add_field(name="📝 Intel Note", value=note, inline=True)
    embed.set_footer(text=f"Officer: {interaction.user.name} | Incident ID: {incident_id} | {current_time}")
    
    # Thực hiện Ban
    try:
        await interaction.guild.ban(discord.Object(id=int(user_id)), reason=f"HQ Blacklist: {violation}")
    except:
        pass
        
    await interaction.response.send_message(embed=embed)
    original_msg = await interaction.original_response()
    
    # Tạo Thread chứa bằng chứng
    try:
        thread = await original_msg.create_thread(name=f"EVIDENCE-{roblox_name}", auto_archive_duration=1440)
        await thread.send("`[HQ SYSTEM]` Upload all photographic or video evidence of the violation below.")
    except:
        pass

# 4. BASIC MODERATION (BAN/KICK/MUTE)
@bot.tree.command(name="ban", description="Ban a personnel")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Code of Conduct Violation"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 **{member.name}** has been banned. Reason: `{reason}`")

@bot.tree.command(name="kick", description="Kick a personnel")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Code of Conduct Violation"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 **{member.name}** has been discharged. Reason: `{reason}`")

@bot.tree.command(name="mute", description="Timeout a personnel")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int):
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration)
    await interaction.response.send_message(f"🔇 **{member.name}** communications restricted for `{minutes}` minutes.")

# 5. WARNING SYSTEM (CẢNH CÁO & XEM LỊCH SỬ)
@bot.tree.command(name="warn", description="Issue a formal warning")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    data = load_data()
    uid_str = str(member.id)
    
    if uid_str not in data["warns"]:
        data["warns"][uid_str] = []
        
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    data["warns"][uid_str].append({
        "reason": reason, 
        "date": current_date, 
        "by": interaction.user.name
    })
    save_data(data)
    
    embed = discord.Embed(title="⚠️ FORMAL WARNING", color=0xED4245)
    embed.description = f"**Target:** {member.mention}\n**Offense:** `{reason}`"
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="check_warns", description="Access personnel warning logs")
async def check_warns(interaction: discord.Interaction, member: discord.Member):
    data = load_data()
    uid_str = str(member.id)
    
    if uid_str not in data["warns"] or not data["warns"][uid_str]: 
        embed = discord.Embed(title="📁 PERSONNEL LOGS", description=f"✅ {member.name} maintains a clean record.", color=0x57F287)
        return await interaction.response.send_message(embed=embed)
    
    embed = discord.Embed(title=f"📁 SECURITY LOGS: {member.name}", color=0xED4245)
    for index, warning in enumerate(data["warns"][uid_str], 1):
        embed.add_field(
            name=f"Incident #{index} • {warning['date']}", 
            value=f"**Reason:** {warning['reason']}\n**Officer:** {warning['by']}", 
            inline=False
        )
        
    await interaction.response.send_message(embed=embed)

# ==========================================
# 🚀 KHỞI CHẠY BOT
# ==========================================
if __name__ == "__main__":
    keep_alive()
    # Nhớ đổi "DISCORD_TOKEN" thành Token thật hoặc dùng os.getenv("DISCORD_TOKEN")
    bot.run("DISCORD_TOKEN")
