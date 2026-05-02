import discord
from discord import app_commands, ui
from discord.ext import commands
import datetime
import json
import os
import uuid
from flask import Flask
from threading import Thread

# ==========================================
# 🌐 HỆ THỐNG GIỮ BOT ONLINE (KEEP ALIVE)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "HQ System is Online!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ==========================================
# ⚙️ CẤU HÌNH VÀ DỮ LIỆU (DATABASE)
# ==========================================
TOKEN = "DISCORD_TOKEN" 
DATA_FILE = "vpoas_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"blacklist": {}, "warns": {}, "diplomacy": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Bảo đảm không thiếu mục nào khi nâng cấp
            if "blacklist" not in data: data["blacklist"] = {}
            if "warns" not in data: data["warns"] = {}
            if "diplomacy" not in data: data["diplomacy"] = {}
            return data
    except:
        return {"blacklist": {}, "warns": {}, "diplomacy": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ==========================================
# 💻 GIAO DIỆN ĐIỂM DANH (ACTIVITY UI)
# ==========================================
class ActivityView(ui.View):
    def __init__(self, target_role: discord.Role, note: str, message_content: str):
        super().__init__(timeout=None)
        self.target_role = target_role
        self.note = note
        self.message_content = message_content
        self.verified_users = set()
        self.start_time = datetime.datetime.now()

    def create_progress_bar(self, current, total):
        if total == 0: return "[..........] 0%"
        percent = (current / total) * 100
        filled = int(percent / 10)
        bar = "❚" * filled + " " * (10 - filled)
        return f"[{bar}]\n-> {percent:.1f}%"

    def build_embed(self):
        real_members = [m for m in self.target_role.members if not m.bot]
        total = len(real_members)
        verified = len(self.verified_users)
        unverified = total - verified
        
        # UI Hiện đại với màu sắc trạng thái
        color = 0x43b581 if unverified == 0 else 0xdd2e44
        
        embed = discord.Embed(
            title=f"Activity Check #{int(self.start_time.timestamp()) % 1000}", 
            color=color,
            description=f"Unit: {self.target_role.mention}"
        )
        embed.add_field(name="Time Started:", value=self.start_time.strftime("%H:%M:%S"), inline=False)
        embed.add_field(name="Note:", value=self.note, inline=False)
        embed.add_field(name="Verified:", value=f"{verified}/{total} members", inline=True)
        embed.add_field(name="Unverified:", value=f"{unverified} members", inline=True)
        embed.add_field(name="Progress:", value=f"```\n{self.create_progress_bar(verified, total)}\n```", inline=False)
        
        status = "MISSION ACCOMPLISHED" if unverified == 0 else "STATUS: IN PROGRESS"
        embed.add_field(name="System Status", value=status, inline=False)
        
        if self.message_content:
             embed.add_field(name="Command Message:", value=self.message_content, inline=False)
             
        embed.set_footer(text="HQ Activity Tracking System")
        return embed

    @ui.button(label="CONFIRM PRESENCE", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, itn: discord.Interaction, button: ui.Button):
        if self.target_role not in itn.user.roles:
            return await itn.response.send_message("❌ Error: You don't have the required Role!", ephemeral=True)
        if itn.user.id in self.verified_users:
            return await itn.response.send_message("⚠️ Notice: You are already marked as Present.", ephemeral=True)
            
        self.verified_users.add(itn.user.id)
        await itn.response.edit_message(embed=self.build_embed(), view=self)

# ==========================================
# 🤖 KHỞI TẠO HỆ THỐNG BOT
# ==========================================
class VPACBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        
    async def setup_hook(self):
        await self.tree.sync()
        print(f"--- HQ SYSTEM ONLINE ---")
        print(f"Logged in as: {self.user.name}")
        print(f"ID: {self.user.id}")
        print(f"------------------------")

bot = VPACBot()

@bot.event
async def on_member_join(member):
    data = load_data()
    if str(member.id) in data["blacklist"]:
        try: 
            await member.ban(reason="System Security: Blacklisted User")
        except: 
            pass

# ==========================================
# 🛡️ CÁC LỆNH QUẢN TRỊ (MODERATION)
# ==========================================

@bot.tree.command(name="blacklist", description="Blacklist user and create evidence thread")
@app_commands.checks.has_permissions(administrator=True)
async def blacklist(itn: discord.Interaction, user_id: str, roblox_name: str, roblox_url: str, violation: str, game_url: str, note: str = "ok"):
    data = load_data()
    uid_str, incident_uuid = str(user_id), str(uuid.uuid4())[:15]
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    data["blacklist"][uid_str] = {
        "uuid": incident_uuid, 
        "roblox_name": roblox_name, 
        "roblox_url": roblox_url, 
        "violation": violation, 
        "game_url": game_url, 
        "note": note, 
        "date": current_time, 
        "staff": itn.user.name
    }
    save_data(data)
    
    user_name, avatar_url = "User", "https://i.imgur.com/8Nba9ft.png"
    try:
        u = await bot.fetch_user(int(user_id))
        user_name, avatar_url = u.name, u.display_avatar.url
    except: 
        pass
        
    embed = discord.Embed(title="PERSONNEL BLACKLISTED", color=0xff0000)
    embed.set_author(name=f"{user_name} has been flagged", icon_url=avatar_url)
    embed.set_thumbnail(url=avatar_url)
    embed.add_field(name="Commanding Staff:", value=itn.user.mention, inline=False)
    embed.add_field(name="Date Recorded:", value=current_time, inline=False)
    embed.add_field(name="Case UUID:", value=f"`{incident_uuid}`", inline=False)
    
    target_info = (
        f"**Roblox Name:** {roblox_name}\n"
        f"**Roblox URL:** {roblox_url}\n"
        f"**Violation:** {violation}\n"
        f"**Discord ID:** {user_id}\n"
        f"**Game Link:** {game_url}\n"
        f"**Note:** {note}"
    )
    embed.add_field(name="Target Information", value=target_info, inline=False)
    
    try: 
        await itn.guild.ban(discord.Object(id=int(user_id)), reason="Blacklisted from HQ")
    except: 
        pass
        
    await itn.response.send_message(embed=embed)
    msg = await itn.original_response()
    
    try:
        thread = await msg.create_thread(name=f"Evidence-{roblox_name}", auto_archive_duration=1440)
        await thread.send(f"⚠️ **Evidence File for {roblox_name}**. Please upload all proofs here.")
    except: 
        pass

@bot.tree.command(name="activity_check", description="Start unit roll call")
async def activity_check(itn: discord.Interaction, role: discord.Role, note: str, message_content: str = "Acknowledge the order!"):
    view = ActivityView(target_role=role, note=note, message_content=message_content)
    await itn.response.send_message(embed=view.build_embed(), view=view)

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(itn: discord.Interaction, member: discord.Member, reason: str = "Violation"):
    await member.ban(reason=reason)
    await itn.response.send_message(f"✅ Banned: {member.name}")

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(itn: discord.Interaction, member: discord.Member):
    await member.kick()
    await itn.response.send_message(f"✅ Kicked: {member.name}")

@bot.tree.command(name="mute", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(itn: discord.Interaction, member: discord.Member, minutes: int):
    await member.timeout(datetime.timedelta(minutes=minutes))
    await itn.response.send_message(f"✅ Muted {member.name} for {minutes} minutes")

@bot.tree.command(name="warn", description="Issue a warning")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(itn: discord.Interaction, member: discord.Member, reason: str):
    data = load_data()
    uid = str(member.id)
    if uid not in data["warns"]: data["warns"][uid] = []
    
    data["warns"][uid].append({
        "reason": reason, 
        "date": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"), 
        "by": itn.user.name
    })
    save_data(data)
    await itn.response.send_message(f"⚠️ Warning issued to {member.name}. Reason: {reason}")

@bot.tree.command(name="check_warns", description="View warning history")
async def check_warns(itn: discord.Interaction, member: discord.Member):
    data = load_data()
    uid = str(member.id)
    if uid not in data["warns"] or not data["warns"][uid]: 
        return await itn.response.send_message(f"Clean record for {member.name}.")
        
    history = "\n".join([f"📅 {w['date']} - {w['reason']} (by {w['by']})" for w in data["warns"][uid]])
    embed = discord.Embed(title=f"Warning Logs: {member.name}", description=history, color=0xFEE75C)
    await itn.response.send_message(embed=embed)

# ==========================================
# 🌐 HỆ THỐNG NGOẠI GIAO (DIPLOMACY SYSTEM)
# ==========================================

@bot.tree.command(name="diplomacy_add", description="Add a group to diplomatic registry")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(status=[
    app_commands.Choice(name="Allied (Đồng minh)", value="Allied"),
    app_commands.Choice(name="Neutral (Trung lập)", value="Neutral"),
    app_commands.Choice(name="Hostile (Thù địch)", value="Hostile")
])
async def diplomacy_add(itn: discord.Interaction, group_name: str, status: str, link: str = "No Link"):
    data = load_data()
    data["diplomacy"][group_name] = {
        "status": status,
        "link": link,
        "date": datetime.datetime.now().strftime("%d/%m/%Y"),
        "staff": itn.user.name
    }
    save_data(data)
    
    color = 0x57F287 if status == "Allied" else (0xFEE75C if status == "Neutral" else 0xED4245)
    embed = discord.Embed(title="Diplomatic Registry Updated", color=color)
    embed.add_field(name="Group:", value=group_name, inline=True)
    embed.add_field(name="Status:", value=f"`{status}`", inline=True)
    embed.add_field(name="Link:", value=link, inline=False)
    embed.set_footer(text=f"Updated by {itn.user.name}")
    
    await itn.response.send_message(embed=embed)

@bot.tree.command(name="diplomacy_list", description="Show all diplomatic relations")
async def diplomacy_list(itn: discord.Interaction):
    data = load_data()
    if not data["diplomacy"]:
        return await itn.response.send_message("No diplomatic data found.")
        
    embed = discord.Embed(title="Global Diplomatic Relations", color=0x3498db)
    
    allied_list = ""
    hostile_list = ""
    neutral_list = ""
    
    for group, info in data["diplomacy"].items():
        text = f"• **{group}** - [Link]({info['link']})\n"
        if info["status"] == "Allied": allied_list += text
        elif info["status"] == "Hostile": hostile_list += text
        else: neutral_list += text
            
    if allied_list: embed.add_field(name="🟢 ALLIES", value=allied_list, inline=False)
    if neutral_list: embed.add_field(name="🟡 NEUTRALS", value=neutral_list, inline=False)
    if hostile_list: embed.add_field(name="🔴 HOSTILES", value=hostile_list, inline=False)
    
    await itn.response.send_message(embed=embed)

# ==========================================
# 🚀 KHỞI CHẠY HỆ THỐNG
# ==========================================
if __name__ == "__main__":
    keep_alive() # Chạy web server ngầm
    bot.run(TOKEN)
