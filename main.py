import disnake
from disnake.ext import commands, tasks
import aiosqlite
import uuid
import json
import time
import psutil
import platform
import datetime
import asyncio
import os
import pandas as pd
import shutil
from io import BytesIO
from typing import Union, List, Optional
 ==========================================
# --- CẤU HÌNH CỐ ĐỊNH (REQUIRED) ---
# ==========================================
TOKEN ="DISCORD_TOKEN"
OWNER_IDS = [1376562278488473630]  # Thay bằng ID Discord của bạn
DEFAULT_COLOR = 0x2b2d31
SUCCESS_COLOR = 0x43b581
ERROR_COLOR = 0xf04747
LOGS_COLOR = 0x7289da

# Đường dẫn Database và Backup
DB_PATH = "backup_ultimate_v3.db"
DB_BACKUP_DIR = "./db_backups/"

# --- KHỞI TẠO BOT ---
intents = disnake.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = False

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("b!"),
    intents=intents,
    help_command=None,
    reload=True
)

# ==========================================
# --- HỆ THỐNG DATABASE (SQLITE) ---
# ==========================================

async def init_db():
    """Khởi tạo toàn bộ cấu trúc bảng dữ liệu"""
    if not os.path.exists(DB_BACKUP_DIR):
        os.makedirs(DB_BACKUP_DIR)
        
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Bảng lưu trữ Backup Keys
        await db.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                key_id TEXT PRIMARY KEY,
                user_id INTEGER,
                guild_id INTEGER,
                role_ids TEXT,
                created_at TIMESTAMP,
                uses_left INTEGER DEFAULT 1
            )
        """)
        # 2. Bảng cấu hình chi tiết Server
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                log_channel INTEGER DEFAULT 0,
                confirm_channel INTEGER DEFAULT 0,
                premium_status BOOLEAN DEFAULT 0,
                max_backups INTEGER DEFAULT 5,
                admin_role_id INTEGER DEFAULT 0,
                language TEXT DEFAULT 'vi'
            )
        """)
        # 3. Bảng danh sách Authorized (Phân quyền Admin bot)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS authorized (
                guild_id INTEGER,
                user_id INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        # 4. Bảng Blacklist (Chặn người dùng/server)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                target_id INTEGER PRIMARY KEY,
                type TEXT, -- 'user' or 'guild'
                reason TEXT,
                timestamp TIMESTAMP
            )
        """)
        # 5. Bảng thống kê hệ thống (Analytics)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS analytics (
                date TEXT PRIMARY KEY,
                backups_created INTEGER DEFAULT 0,
                syncs_completed INTEGER DEFAULT 0
            )
        """)
        await db.commit()

# ==========================================
# --- HỆ THỐNG KIỂM TRA QUYỀN & TIỆN ÍCH ---
# ==========================================

async def is_owner(ctx_or_inter):
    return ctx_or_inter.author.id in OWNER_IDS

async def is_blacklisted(target_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM blacklist WHERE target_id = ?", (target_id,)) as cursor:
            return await cursor.fetchone() is not None

async def check_permissions(inter: disnake.ApplicationCommandInteraction):
    """Kiểm tra xem user có quyền Admin hoặc trong danh sách authorized không"""
    if inter.author.guild_permissions.administrator:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM authorized WHERE guild_id = ? AND user_id = ?", 
                            (inter.guild.id, inter.author.id)) as cursor:
            res = await cursor.fetchone()
            return res is not None

async def update_analytics(type: str):
    """Cập nhật thống kê hàng ngày"""
    today = datetime.date.today().isoformat()
    col = "backups_created" if type == "backup" else "syncs_completed"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"""
            INSERT INTO analytics (date, {col}) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET {col} = {col} + 1
        """, (today,))
        await db.commit()

# ==========================================
# --- GIAO DIỆN (UI/UX) NÂNG CAO ---
# ==========================================

class ApprovalView(disnake.ui.View):
    """View dành cho Admin phê duyệt yêu cầu khôi phục role"""
    def __init__(self, key_id: str, member_id: int, roles: list):
        super().__init__(timeout=3600) # Timeout 1 tiếng
        self.key_id = key_id
        self.member_id = member_id
        self.roles = roles

    @disnake.ui.button(label="CHẤP NHẬN", style=disnake.ButtonStyle.green, emoji="✅", custom_id="approve_v3")
    async def accept(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not await check_permissions(inter):
            return await inter.response.send_message("❌ Bạn không có quyền phê duyệt!", ephemeral=True)

        await inter.response.defer()
        member = inter.guild.get_member(self.member_id)
        if not member:
            return await inter.edit_original_message(content="❌ Người dùng không còn trong server.", view=None)

        # Lọc roles hợp lệ (thứ bậc thấp hơn bot)
        to_add = []
        for rid in self.roles:
            role = inter.guild.get_role(int(rid))
            if role and role < inter.guild.me.top_role and not role.is_bot_managed():
                to_add.append(role)

        try:
            await member.add_roles(*to_add, reason=f"Approved by Admin: {inter.author}")
            
            # Cập nhật database: Xóa key
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM backups WHERE key_id = ?", (self.key_id,))
                await db.commit()

            # Update Analytics
            await update_analytics("sync")

            # Update UI
            embed = inter.message.embeds[0]
            embed.color = SUCCESS_COLOR
            embed.title = "🛡️ Yêu cầu đã được phê duyệt"
            embed.add_field(name="Trạng thái", value=f"✅ Đã cấp `{len(to_add)}` roles.\n👤 Admin: {inter.author.mention}", inline=False)
            await inter.edit_original_message(embed=embed, view=None)

            # Log to Channel
            log_embed = disnake.Embed(title="📝 Nhật Ký: Khôi Phục Role", color=SUCCESS_COLOR)
            log_embed.add_field(name="Thành viên", value=member.mention, inline=True)
            log_embed.add_field(name="Người duyệt", value=inter.author.mention, inline=True)
            log_embed.set_footer(text=f"Key: {self.key_id}")
            # (Hàm gửi log sẽ được gọi sau)

        except Exception as e:
            await inter.followup.send(f"Lỗi: {e}", ephemeral=True)

    @disnake.ui.button(label="TỪ CHỐI", style=disnake.ButtonStyle.red, emoji="❌", custom_id="reject_v3")
    async def reject(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not await check_permissions(inter):
            return await inter.response.send_message("❌ Bạn không có quyền!", ephemeral=True)

        embed = inter.message.embeds[0]
        embed.color = ERROR_COLOR
        embed.title = "🛡️ Yêu cầu đã bị từ chối"
        embed.add_field(name="Admin xử lý", value=inter.author.mention, inline=False)
        await inter.response.edit_message(embed=embed, view=None)

class SyncModalV3(disnake.ui.Modal):
    """Bảng nhập Key cho người dùng"""
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Mã Khôi Phục (Key)",
                placeholder="BK-XXXX-XXXX",
                custom_id="key_input",
                min_length=5,
                max_length=50
            )
        ]
        super().__init__(title="Khôi Phục Vai Trò 🔄", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        key = inter.text_values["key_input"].strip().upper()
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id, role_ids, guild_id FROM backups WHERE key_id = ?", (key,)) as cursor:
                data = await cursor.fetchone()

        if not data:
            return await inter.response.send_message("❌ Mã Key không tồn tại hoặc đã bị xóa!", ephemeral=True)

        if data[2] != inter.guild.id:
            return await inter.response.send_message("❌ Key này thuộc về một máy chủ khác!", ephemeral=True)

        if data[0] != inter.author.id:
            return await inter.response.send_message("❌ Bạn không phải chủ nhân của Key này!", ephemeral=True)

        # Kiểm tra config server
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT confirm_channel FROM settings WHERE guild_id = ?", (inter.guild.id,)) as cursor:
                config = await cursor.fetchone()
        
        if not config or not config[0]:
            return await inter.response.send_message("⚠️ Máy chủ này chưa thiết lập kênh Phê Duyệt. Vui lòng liên hệ Admin!", ephemeral=True)

        confirm_channel = inter.guild.get_channel(config[0])
        role_ids = json.loads(data[1])

        embed = disnake.Embed(title="📥 Yêu Cầu Khôi Phục Mới", color=LOGS_COLOR)
        embed.set_thumbnail(url=inter.author.display_avatar.url)
        embed.add_field(name="Thành viên", value=inter.author.mention, inline=True)
        embed.add_field(name="Số lượng Role", value=f"`{len(role_ids)}`", inline=True)
        embed.add_field(name="ID Key", value=f"`{key}`", inline=False)
        embed.set_footer(text="Nhấn nút bên dưới để xử lý yêu cầu này.")

        await confirm_channel.send(embed=embed, view=ApprovalView(key, inter.author.id, role_ids))
        await inter.response.send_message("✅ Yêu cầu của bạn đã được gửi tới Ban Quản Trị!", ephemeral=True)

class PanelViewV3(disnake.ui.View):
    """View cho Panel chính"""
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Backup Roles", style=disnake.ButtonStyle.blurple, emoji="💾", custom_id="btn_bk_v3")
    async def backup(self, button, inter):
        # Kiểm tra Blacklist
        if await is_blacklisted(inter.author.id):
            return await inter.response.send_message("❌ Bạn đã bị chặn khỏi hệ thống!", ephemeral=True)

        # Lấy dữ liệu server
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT max_backups, premium_status FROM settings WHERE guild_id = ?", (inter.guild.id,)) as cursor:
                config = await cursor.fetchone()
                max_bk = config[0] if config else 5

            async with db.execute("SELECT COUNT(*) FROM backups WHERE user_id = ? AND guild_id = ?", (inter.author.id, inter.guild.id)) as cursor:
                current_count = (await cursor.fetchone())[0]

        if current_count >= max_bk:
            return await inter.response.send_message(f"❌ Bạn đã hết lượt backup (Giới hạn: {max_bk}). Hãy xóa bớt key cũ!", ephemeral=True)

        # Lọc role
        roles = [r.id for r in inter.author.roles if r.id != inter.guild.id and not r.is_bot_managed() and r < inter.guild.me.top_role]
        if not roles:
            return await inter.response.send_message("❌ Bạn không có vai trò nào đủ điều kiện để lưu trữ!", ephemeral=True)

        key = f"BK-{str(uuid.uuid4())[:8].upper()}-{str(uuid.uuid4())[:4].upper()}"
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO backups (key_id, user_id, guild_id, role_ids, created_at) VALUES (?,?,?,?,?)",
                (key, inter.author.id, inter.guild.id, json.dumps(roles), datetime.datetime.now())
            )
            await db.commit()

        await update_analytics("backup")

        try:
            embed = disnake.Embed(title="💾 Sao Lưu Thành Công", color=SUCCESS_COLOR)
            embed.description = f"Dữ liệu vai trò của bạn tại **{inter.guild.name}** đã được lưu trữ an toàn."
            embed.add_field(name="🔑 Mã Khôi Phục (Key)", value=f"```\n{key}\n```")
            embed.set_footer(text="CẢNH BÁO: Không chia sẻ Key này cho bất kỳ ai.")
            await inter.author.send(embed=embed)
            await inter.response.send_message("✅ Đã gửi Key vào tin nhắn riêng của bạn!", ephemeral=True)
        except:
            await inter.response.send_message(f"⚠️ Bot không thể gửi DM. Key của bạn là: `{key}`", ephemeral=True)

    @disnake.ui.button(label="Sync Roles", style=disnake.ButtonStyle.green, emoji="🔄", custom_id="btn_sync_v3")
    async def sync(self, button, inter):
        await inter.response.send_modal(modal=SyncModalV3())

    @disnake.ui.button(label="My Keys", style=disnake.ButtonStyle.gray, emoji="🔑", custom_id="btn_keys_v3")
    async def my_keys(self, button, inter):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT key_id, created_at FROM backups WHERE user_id = ? AND guild_id = ?", 
                                (inter.author.id, inter.guild.id)) as cursor:
                keys = await cursor.fetchall()
        
        if not keys:
            return await inter.response.send_message("❌ Bạn không có bản lưu nào tại server này.", ephemeral=True)

        text = "\n".join([f"• `{k[0]}` (Tạo ngày: {k[1][:10]})" for k in keys])
        await inter.response.send_message(f"🗝️ **Danh sách Key của bạn:**\n{text}", ephemeral=True)

# ==========================================
# --- COGS: HỆ THỐNG LỆNH CHÍNH ---
# ==========================================

class UltimateBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        self.db_backup_task.start()

    def cog_unload(self):
        self.db_backup_task.cancel()

    @tasks.loop(hours=24)
    async def db_backup_task(self):
        """Tự động sao lưu database mỗi ngày"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(DB_PATH, f"{DB_BACKUP_DIR}/backup_{timestamp}.db")

    @commands.slash_command(name="grade", description="Lệnh chấm bài thi chuyên nghiệp")
    async def grade_cmd(self, inter: disnake.ApplicationCommandInteraction, candidate: disnake.Member, phase: str = "1/2"):
        await inter.response.send_modal(modal=GradeModal(candidate, phase))

    
    @commands.Cog.listener()
    async def on_ready(self):
        await init_db()
        self.bot.add_view(PanelViewV3())
        print(f"[{datetime.datetime.now()}] >>> SYSTEM READY: {self.bot.user}")

    # --- SLASH COMMANDS: QUẢN TRỊ ---

    @commands.slash_command(name="admin")
    async def admin_group(self, inter): pass

    @admin_group.sub_command(name="send", description="Gửi Panel điều khiển chuyên nghiệp")
    @commands.has_permissions(administrator=True)
    async def send_panel(self, inter):
        embed = disnake.Embed(
            title="👑 ROLE BACKUP ULTIMATE v3",
            description=(
                "**Hệ thống quản lý vai trò tiên tiến bậc nhất.**\n\n"
                "🛡️ **An Toàn Tuyệt Đối**: Mọi bản lưu được mã hóa và lưu trữ độc lập.\n"
                "⚡ **Hiệu Suất Tối Đa**: Khôi phục hàng loạt vai trò chỉ với 1 cú click.\n"
                "💎 **Tính Năng Cao Cấp**: Xuất dữ liệu Excel, Nhật ký chi tiết.\n\n"
                "👇 *Chọn một chức năng bên dưới để bắt đầu*"
            ),
            color=DEFAULT_COLOR
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1054607292311543848/1386261499768471643/standard_3.gif?ex=69d21d21&is=69d0cba1&hm=8f16736b8d1247033c1642b78f76b5896e71c0ce1ebe3c1b5883d6fd1209331f&") # Banner mặc định
        embed.set_footer(text=f"Server ID: {inter.guild.id} • Power by Global Tech", icon_url=self.bot.user.display_avatar.url)
        
        await inter.response.send_message("🚀 Đang khởi tạo Panel...", ephemeral=True)
        await inter.channel.send(embed=embed, view=PanelViewV3())

    @admin_group.sub_command(name="setup", description="Cấu hình hệ thống Server")
    @commands.has_permissions(manage_guild=True)
    async def setup_sys(self, inter, 
                       log_channel: disnake.TextChannel = None, 
                       confirm_channel: disnake.TextChannel = None,
                       max_backups: int = commands.Param(default=5, le=20, ge=1)):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO settings (guild_id, log_channel, confirm_channel, max_backups)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET 
                log_channel = COALESCE(?, log_channel),
                confirm_channel = COALESCE(?, confirm_channel),
                max_backups = ?
            """, (inter.guild.id, 
                  log_channel.id if log_channel else 0, 
                  confirm_channel.id if confirm_channel else 0, 
                  max_backups,
                  log_channel.id if log_channel else None,
                  confirm_channel.id if confirm_channel else None,
                  max_backups))
            await db.commit()
        await inter.response.send_message("✅ Đã cập nhật cấu hình hệ thống thành công!", ephemeral=True)

    @admin_group.sub_command(name="authorized", description="Quản lý danh sách trắng Admin Bot")
    @commands.has_permissions(administrator=True)
    async def auth_user(self, inter, action: str = commands.Param(choices=["Thêm", "Xóa"]), user: disnake.Member = None):
        async with aiosqlite.connect(DB_PATH) as db:
            if action == "Thêm":
                await db.execute("INSERT OR IGNORE INTO authorized (guild_id, user_id, added_by, added_at) VALUES (?,?,?,?)",
                                (inter.guild.id, user.id, inter.author.id, datetime.datetime.now()))
                msg = f"✅ Đã cấp quyền vận hành cho {user.mention}"
            else:
                await db.execute("DELETE FROM authorized WHERE guild_id = ? AND user_id = ?", (inter.guild.id, user.id))
                msg = f"❌ Đã gỡ quyền vận hành của {user.mention}"
            await db.commit()
        await inter.response.send_message(msg, ephemeral=True)

    @admin_group.sub_command(name="export", description="Xuất báo cáo Key ra file Excel")
    @commands.has_permissions(administrator=True)
    async def export_excel(self, inter):
        await inter.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM backups WHERE guild_id = ?", (inter.guild.id,)) as cursor:
                rows = await cursor.fetchall()
        
        if not rows:
            return await inter.edit_original_message(content="❌ Không có dữ liệu để xuất.")

        # Tạo DataFrame
        df = pd.DataFrame(rows, columns=['Mã Key', 'User ID', 'Server ID', 'Data Roles', 'Ngày Tạo', 'Lượt Dùng'])
        
        with BytesIO() as output:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Backups')
            output.seek(0)
            file = disnake.File(fp=output, filename=f"Report_{inter.guild.id}.xlsx")
            await inter.edit_original_message(content="📊 Báo cáo định dạng Excel đã sẵn sàng:", file=file)

    # --- SLASH COMMANDS: CHỦ BOT (OWNER) ---

    @commands.slash_command(name="owner")
    @commands.check(is_owner)
    async def owner_group(self, inter): pass

    @owner_group.sub_command(name="blacklist", description="Chặn User/Server khỏi bot")
    async def blacklist_add(self, inter, target_id: str, reason: str = "Vi phạm điều khoản"):
        tid = int(target_id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO blacklist (target_id, reason, timestamp) VALUES (?,?,?)",
                            (tid, reason, datetime.datetime.now()))
            await db.commit()
        await inter.response.send_message(f"✅ Đã thêm `{tid}` vào danh sách đen.", ephemeral=True)

    @owner_group.sub_command(name="analytics", description="Xem thống kê tổng quát hệ thống")
    async def system_analytics(self, inter):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT SUM(backups_created), SUM(syncs_completed) FROM analytics") as cursor:
                res = await cursor.fetchone()
            async with db.execute("SELECT COUNT(*) FROM backups") as cursor:
                total_keys = (await cursor.fetchone())[0]

        embed = disnake.Embed(title="📊 TOÀN CẢNH HỆ THỐNG", color=SUCCESS_COLOR)
        embed.add_field(name="💾 Tổng Backup", value=f"`{res[0] or 0}`", inline=True)
        embed.add_field(name="🔄 Tổng Sync", value=f"`{res[1] or 0}`", inline=True)
        embed.add_field(name="🗝️ Key Hiện Có", value=f"`{total_keys}`", inline=True)
        
        # Tạo biểu đồ đơn giản bằng text
        history_text = "```\nNgày       | Backup | Sync\n"
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM analytics ORDER BY date DESC LIMIT 5") as cursor:
                async for row in cursor:
                    history_text += f"{row[0]} | {row[1]:<6} | {row[2]}\n"
        history_text += "```"
        
        embed.add_field(name="📅 Lịch sử 5 ngày gần nhất", value=history_text, inline=False)
        await inter.response.send_message(embed=embed)

    # --- SLASH COMMANDS: THÔNG TIN ---

    @commands.slash_command(name="uptime", description="Kiểm tra tình trạng sức khỏe của Bot")
    async def uptime_check(self, inter):
        uptime = datetime.timedelta(seconds=int(time.time() - self.start_time))
        cpu = psutil.cpu_percent()
        ram = psutil.Process().memory_info().rss / 1024 / 1024
        
        embed = disnake.Embed(title="🖥️ BOT PERFORMANCE", color=LOGS_COLOR)
        embed.add_field(name="⏱️ Uptime", value=f"`{uptime}`", inline=True)
        embed.add_field(name="⚡ CPU", value=f"`{cpu}%`", inline=True)
        embed.add_field(name="🧠 RAM", value=f"`{ram:.2f} MB`", inline=True)
        embed.add_field(name="🌐 Servers", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="📡 Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        embed.set_footer(text=f"Node: {platform.node()} | OS: {platform.system()}")
        await inter.response.send_message(embed=embed)

    @commands.slash_command(name="help", description="Trung tâm trợ giúp")
    async def help_center(self, inter):
        embed = disnake.Embed(
            title="❓ TRUNG TÂM TRỢ GIÚP",
            description=(
                "**Dành cho Thành Viên:**\n"
                "• Nhấn **Backup Roles** trên Panel để lưu vai trò.\n"
                "• Nhấn **Sync Roles** và nhập mã Key để khôi phục.\n"
                "• Nhấn **My Keys** để quản lý các mã đã tạo.\n\n"
                "**Dành cho Quản Trị Viên:**\n"
                "`/admin send`: Gửi Panel tương tác.\n"
                "`/admin setup`: Cài đặt kênh Log/Confirm.\n"
                "`/admin authorized`: Cấp quyền duyệt cho nhân viên.\n"
                "`/admin export`: Xuất báo cáo Excel.\n\n"
                "**Hỗ trợ:** Liên hệ [Developer Name]"
            ),
            color=DEFAULT_COLOR
        )
        await inter.response.send_message(embed=embed, ephemeral=True)
# --- CHÈN VÀO KHOẢNG HÀNG 300 (Trước phần khởi chạy Bot) ---

class GradeModal(disnake.ui.Modal):
    def __init__(self, candidate: disnake.Member, phase: str):
        self.candidate = candidate
        self.phase = phase
        
        components = [
            disnake.ui.TextInput(
                label="Điểm tổng kết (%)",
                custom_id="score",
                placeholder="Ví dụ: 55",
                max_length=3
            ),
            disnake.ui.TextInput(
                label="Nhận xét (Feedback)",
                custom_id="feedback",
                placeholder="Nhập nội dung nhận xét...",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000
            )
        ]
        super().__init__(title=f"Chấm bài: {candidate.name}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            score_val = int(inter.text_values["score"])
        except ValueError:
            return await inter.response.send_message("❌ Vui lòng chỉ nhập số cho phần điểm!", ephemeral=True)

        feedback_val = inter.text_values["feedback"]
        status = "PASSED" if score_val >= 50 else "FAILED"
        color = 0x43b581 if status == "PASSED" else 0xf04747
        filled = int(score_val / 10)
        progress_bar = f"[{'█' * filled}{'░' * (10 - filled)}]"

        embed = disnake.Embed(title="🔔 Notification:", color=color, description=f"{self.candidate.mention}")
        embed.set_author(name="PHASE GRADING RESULT")
        
        embed.add_field(name="👤 CANDIDATE INFO", value=f"**Name:** {self.candidate.name}\n**ID:** {self.candidate.id}\n**Discord:** {self.candidate.mention}", inline=False)
        embed.add_field(name="📊 GRADING STATUS", value=f"**Status: [ {status} ]**\n**Phase: Attempt {self.phase}**", inline=False)
        embed.add_field(name="💯 OVERALL SCORE", value=f"**{progress_bar} {score_val}%**", inline=False)
        embed.add_field(name="📝 FEEDBACK", value=f"```\n{feedback_val}\n```", inline=False)
        embed.add_field(name="👮 EXAMINER", value=f"{inter.author.mention} • **Admin Staff**", inline=False)

        embed.set_thumbnail(url=self.candidate.display_avatar.url)
        embed.set_footer(text="Reset: 7 Days • SROVAF System")
        embed.timestamp = datetime.datetime.now()

        await inter.response.send_message("✅ Đã gửi kết quả chấm thi!", ephemeral=True)
        await inter.channel.send(embed=embed)

# ==========================================
# --- KHỞI CHẠY ---
# ==========================================

bot.add_cog(UltimateBackup(bot))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Bạn không có đủ quyền hạn để dùng lệnh này!", delete_after=5)
    elif isinstance(error, commands.NotOwner):
        await ctx.send("❌ Lệnh này chỉ dành cho chủ Bot!", delete_after=5)

if __name__ == "__main__":
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ LỖI: Vui lòng điền Bot Token vào biến TOKEN!")
    else:
        bot.run(TOKEN)