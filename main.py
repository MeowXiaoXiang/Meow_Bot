import discord
from discord.ext import commands

from loguru import logger
from datetime import datetime
from typing import List

import os
import sys
import traceback
from dotenv import load_dotenv

version = "v1.1"
start_time = datetime.now()

# ─────────────────────────────────────────────────────────
#  初始化 Bot
# ─────────────────────────────────────────────────────────
# Intents 設定：https://discord.com/developers/applications → Bot → Privileged Gateway Intents
intents = discord.Intents.default()
intents.members = True          # 成員列表與加入/退出事件
intents.message_content = True  # 讀取訊息內容（前綴指令必要）

bot = commands.Bot(
    command_prefix=commands.when_mentioned,
    # 其他前綴範例：command_prefix="!" 或 commands.when_mentioned_or("!")
    intents=intents
)

# ─────────────────────────────────────────────────────────
#  自訂 HelpCommand
# ─────────────────────────────────────────────────────────

class CustomHelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="📘 指令總覽", description="以下是目前可用的指令列表", color=discord.Color.blue())
        for cog, commands_list in mapping.items():
            filtered = await self.filter_commands(commands_list, sort=True)
            if not filtered:
                continue
            name = cog.qualified_name if cog else "未分類"
            value = "\n".join(f"`{self.context.clean_prefix}{cmd.name}` - {cmd.short_doc}" for cmd in filtered)
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text=f"輸入 {self.context.clean_prefix}help 指令名稱 查看詳細說明")
        embed.set_author(name=self.context.me.name, icon_url=self.context.me.display_avatar.url)
        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        embed = discord.Embed(
            title=f"❓ 指令說明：{command.name}",
            description=command.help or "（沒有詳細說明）",
            color=discord.Color.green()
        )
        if command.usage:
            embed.add_field(name="用法", value=f"`{self.context.clean_prefix}{command.name} {command.usage}`", inline=False)
        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error):
        embed = discord.Embed(title="🚫 Help 指令錯誤", description=error, color=discord.Color.red())
        await self.get_destination().send(embed=embed)

bot.help_command = CustomHelpCommand()

# ─────────────────────────────────────────────────────────
#  機器人啟動事件
# ─────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    app_info = await bot.application_info()
    bot.owner_id = app_info.owner.id

    logger.info("[初始化] 載入基本指令")
    await bot.add_cog(ManagementCommand(bot))

    await load_all_extensions()

    logger.info("[初始化] 同步斜線指令")
    slash_command = await bot.tree.sync()
    logger.info(f"[初始化] 已同步 {len(slash_command)} 個斜線指令")

    # 設定機器人狀態（可用：Game, Streaming, Activity, CustomActivity）
    activity = discord.Game(name="貓蛋")
    await bot.change_presence(activity=activity)

    logger.info(f"[初始化] {bot.user} | Ready!")


async def load_all_extensions():
    """自動載入 /cogs 資料夾中的所有 .py 模組"""
    cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py'):
            try:
                logger.info(f"[初始化] 載入 Extension: {filename[:-3]}")
                await bot.load_extension(f'cogs.{filename[:-3]}')
            except Exception as exc:
                logger.error(f"[初始化] 載入 Extension 失敗: {exc}\n{traceback.format_exc()}")
    logger.info("[初始化] Extension 載入完畢")

# ─────────────────────────────────────────────────────────
#  錯誤處理：前綴指令 / 斜線指令錯誤回報給擁有者
# ─────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    maintainer = bot.get_user(bot.owner_id)
    embed = discord.Embed(title="前綴指令錯誤", description=str(error))
    embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="訊息內容", value=ctx.message.content)

    if ctx.channel.type == discord.ChannelType.private:
        embed.add_field(name="頻道", value="私人 Private")
        logger.error(f"{ctx.author.name}({ctx.author.id}):{error}\n{traceback.format_exc()}")
    else:
        embed.add_field(name="頻道", value=f"{ctx.guild.name}/{ctx.channel.name}")
        logger.error(f"{ctx.guild.name}/{ctx.channel.name}/{ctx.author.name}({ctx.author.id}):{error}\n{traceback.format_exc()}")

    await maintainer.send(embed=embed)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    maintainer = bot.get_user(bot.owner_id)
    embed = discord.Embed(title="斜線指令錯誤", description=str(error))
    embed.set_author(name=f"{interaction.user.name} ({interaction.user.id})", icon_url=interaction.user.display_avatar.url)
    embed.add_field(name="指令資料", value=str(interaction.data))

    if interaction.channel.type == discord.ChannelType.private:
        embed.add_field(name="頻道", value="私人 Private")
        logger.error(f"{interaction.user.name}({interaction.user.id}):{error}\n{traceback.format_exc()}")
    else:
        embed.add_field(name="頻道", value=f"{interaction.guild.name} - {interaction.channel.name}")
        logger.error(f"{interaction.guild.name}-{interaction.channel.name}-{interaction.user.name}({interaction.user.id}):{error}\n{traceback.format_exc()}")

    await maintainer.send(embed=embed)

# ─────────────────────────────────────────────────────────
#  管理指令：模組載入 / 卸載 / 重載 / 狀態查詢（僅限管理員）
# ─────────────────────────────────────────────────────────

class ManagementCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def extension_autocomplete(self, interaction: discord.Interaction, current: str) -> List[discord.app_commands.Choice[str]]:
        """模組名稱自動補全"""
        cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
        extensions = [f[:-3] for f in os.listdir(cogs_dir) if f.endswith('.py')]
        return [discord.app_commands.Choice(name=e, value=e) for e in extensions if current in e]

    def is_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator if interaction.guild else True

    async def _extension_action(self, interaction: discord.Interaction, action: str, extension: str):
        """統一處理模組操作"""
        if not self.is_admin(interaction):
            await interaction.response.send_message("你沒有足夠的權限使用這個命令", ephemeral=True)
            return

        try:
            full_path = f"cogs.{extension}"
            match action:
                case "load": await self.bot.load_extension(full_path)
                case "unload": await self.bot.unload_extension(full_path)
                case "reload": await self.bot.reload_extension(full_path)
            zh_action = {"load": "載入", "unload": "卸載", "reload": "重新載入"}.get(action, action)
            await interaction.response.send_message(embed=discord.Embed(title=f"✅ 已{zh_action}模組", description=f"`{extension}`", color=0x00ff00), ephemeral=True)
            logger.info(f"[管理指令] {zh_action} 模組成功：{extension}")
        except commands.ExtensionAlreadyLoaded:
            await interaction.response.send_message(embed=discord.Embed(title="⚠ 模組已載入", description=f"`{extension}` 已載入過", color=0xffff00), ephemeral=True)
        except commands.ExtensionNotLoaded:
            await interaction.response.send_message(embed=discord.Embed(title="⚠ 模組尚未載入", description=f"`{extension}` 尚未載入", color=0xff9900), ephemeral=True)
        except commands.ExtensionNotFound:
            await interaction.response.send_message(embed=discord.Embed(title="❌ 模組不存在", description=f"找不到 `{extension}`", color=0xff0000), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(embed=discord.Embed(title="❌ 發生錯誤", description=str(e), color=0xff0000), ephemeral=True)
            logger.error(f"[管理指令] 操作模組錯誤：{e}\n{traceback.format_exc()}")

    @discord.app_commands.command(name="載入模組", description="載入指定的 COG 模組")
    @discord.app_commands.describe(extension="選擇載入的模組")
    @discord.app_commands.rename(extension="模組")
    @discord.app_commands.autocomplete(extension=extension_autocomplete)
    async def load(self, interaction: discord.Interaction, extension: str):
        await self._extension_action(interaction, "load", extension)

    @discord.app_commands.command(name="卸載模組", description="卸載指定的 COG 模組")
    @discord.app_commands.describe(extension="選擇卸載的模組")
    @discord.app_commands.rename(extension="模組")
    @discord.app_commands.autocomplete(extension=extension_autocomplete)
    async def unload(self, interaction: discord.Interaction, extension: str):
        await self._extension_action(interaction, "unload", extension)

    @discord.app_commands.command(name="重新載入模組", description="重新載入指定的 COG 模組")
    @discord.app_commands.describe(extension="選擇重新載入的模組")
    @discord.app_commands.rename(extension="模組")
    @discord.app_commands.autocomplete(extension=extension_autocomplete)
    async def reload(self, interaction: discord.Interaction, extension: str):
        await self._extension_action(interaction, "reload", extension)

    @discord.app_commands.command(name="機器人狀態", description="查看機器人目前狀態")
    async def status(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        color = discord.Color.green() if latency < 100 else discord.Color.yellow() if latency < 200 else discord.Color.red()

        embed = discord.Embed(title="機器人狀態", description="目前狀態如下", color=color)
        embed.add_field(name="延遲", value=f"{latency}ms", inline=True)
        embed.add_field(name="指令數量", value=f"前綴: `{len(self.bot.commands)}`\t斜線: `{len(self.bot.tree.get_commands())}`", inline=True)
        embed.add_field(name="WebSocket", value="已連接" if not self.bot.is_ws_ratelimited() else "受限", inline=True)

        target = interaction.guild.me if interaction.guild else self.bot.user
        perms = [f"- {name}" for name, value in interaction.channel.permissions_for(target) if value]
        embed.add_field(name=f"權限（{interaction.guild.name if interaction.guild else '私訊'}）", value="\n".join(perms[:10]) or "（無）", inline=False)

        cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
        all_exts = [f[:-3] for f in os.listdir(cogs_dir) if f.endswith('.py')]
        active_exts = [e.replace("cogs.", "") for e in self.bot.extensions]
        embed.add_field(name="模組狀態", value="\n".join(f"- {e} {'✅' if e in active_exts else '❌'}" for e in all_exts), inline=False)

        embed.add_field(name="在線時間", value=f"<t:{int(start_time.timestamp())}:R>", inline=False)
        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"Discord Bot 版本：{version}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ─────────────────────────────────────────────────────────
#  重啟機器人指令（僅限擁有者）
# ─────────────────────────────────────────────────────────

@bot.tree.command(name="重啟機器人", description="重新啟動機器人（僅限擁有者）")
async def restart_bot_command(interaction: discord.Interaction):
    if interaction.user.id != bot.owner_id:
        await interaction.response.send_message("❌ 你不是機器人擁有者，無法使用此指令。", ephemeral=True)
        return

    view = RestartConfirmView(bot, interaction)
    await interaction.response.send_message("您確定要重新啟動機器人嗎？", view=view, ephemeral=True)


class RestartConfirmView(discord.ui.View):
    def __init__(self, bot, interaction: discord.Interaction, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.interaction = interaction
        self.has_interacted = False

    def disable_all_buttons(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        if not self.has_interacted:
            self.disable_all_buttons()
            try:
                await self.interaction.edit_original_response(content="⚠️ 重啟操作已過期，請重新執行指令。", view=self)
            except Exception as e:
                logger.warning(f"[重啟按鈕超時失敗] {e}")

    @discord.ui.button(label="✅ 確認重啟", style=discord.ButtonStyle.success, custom_id="restart_confirm", row=0)
    async def confirm_restart(self, interaction: discord.Interaction, _):
        if interaction.user.id != self.bot.owner_id:
            await interaction.response.send_message("❌ 你無權操作此按鈕。", ephemeral=True)
            return
        self.has_interacted = True
        self.disable_all_buttons()
        await interaction.response.edit_message(content="🔁 正在重啟機器人...", view=self)
        logger.info("[重啟指令] Bot 正在重啟...")
        restart_program()

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, custom_id="restart_cancel", row=0, emoji="❌")
    async def cancel_restart(self, interaction: discord.Interaction, _):
        self.has_interacted = True
        self.disable_all_buttons()
        await interaction.response.edit_message(content="✅ 已取消重啟操作。", view=self)
        logger.info("[重啟指令] 已取消")


def restart_program():
    """使用 os.execl 執行進程替換重啟"""
    python = sys.executable
    os.execl(python, python, *sys.argv)

# ─────────────────────────────────────────────────────────
#  Loguru 記錄器設定
# ─────────────────────────────────────────────────────────

def set_logger():
    """設定 Loguru 的輸出行為（終端機 & 檔案）"""
    logger.remove()
    debug_mode = os.getenv('DEBUG', '').lower() in ('true', '1', 'yes')

    # 終端輸出
    logger.add(sys.stdout, level="DEBUG" if debug_mode else "INFO", colorize=True)

    # 檔案輸出（每 7 天輪替，保留 30 天，自動壓縮）
    logger.add(
        "./logs/system.log",
        rotation="7 days",
        retention="30 days",
        encoding="UTF-8",
        compression="zip",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    )

# ─────────────────────────────────────────────────────────
#  程式入口點
# ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    set_logger()
    load_dotenv()

    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        logger.critical("❌ DISCORD_BOT_TOKEN 尚未設定，請檢查 .env 或系統環境變數")
        sys.exit(1)

    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.critical(f"❗ 無法啟動 Discord Bot：{e}")
        sys.exit(1)