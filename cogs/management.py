from __future__ import annotations

import os
import sys
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

ExtensionAction = Literal["load", "unload", "reload"]


class ManagementCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _is_admin(interaction: discord.Interaction) -> bool:
        return (
            interaction.guild is not None
            and isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        )

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if self._is_admin(interaction):
            return True

        await interaction.response.send_message(
            "你沒有足夠的權限使用這個命令。",
            ephemeral=True,
        )
        return False

    async def extension_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        return self._extension_choices(current)

    async def unload_extension_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        return self._extension_choices(current, exclude_management=True)

    def _extension_choices(
        self,
        current: str,
        *,
        exclude_management: bool = False,
    ) -> list[app_commands.Choice[str]]:
        current_folded = current.casefold()
        names = (
            name
            for name in self.bot.discover_extension_names()
            if current_folded in name.casefold()
            and (not exclude_management or name != self.bot.management_name)
        )
        return [app_commands.Choice(name=name, value=name) for name in names][:25]

    async def _extension_action(
        self,
        interaction: discord.Interaction,
        action: ExtensionAction,
        extension: str,
    ) -> None:
        if not await self._require_admin(interaction):
            return

        full_path = self.bot.extension_path(extension)
        if full_path is None:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ 模組不存在",
                    description=f"找不到 `{extension}`",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        if action == "unload" and full_path == self.bot.management_extension:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ 無法卸載核心模組",
                    description="`management` 是核心管理模組，不能卸載。",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        zh_action = {
            "load": "載入",
            "unload": "卸載",
            "reload": "重新載入",
        }[action]

        try:
            match action:
                case "load":
                    await self.bot.load_extension(full_path)
                case "unload":
                    await self.bot.unload_extension(full_path)
                case "reload":
                    await self.bot.reload_extension(full_path)

            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"✅ 已{zh_action}模組",
                    description=f"`{extension}`",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )
            logger.info(f"[管理指令] {zh_action}模組成功：{extension}")
        except commands.ExtensionAlreadyLoaded:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠ 模組已載入",
                    description=f"`{extension}` 已載入過",
                    color=discord.Color.yellow(),
                ),
                ephemeral=True,
            )
        except commands.ExtensionNotLoaded:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="⚠ 模組尚未載入",
                    description=f"`{extension}` 尚未載入",
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
        except commands.ExtensionNotFound:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ 模組不存在",
                    description=f"找不到 `{extension}`",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
        except Exception as error:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ 發生錯誤",
                    description=str(error)[:4096],
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            raise

    @app_commands.command(name="載入模組", description="載入指定的 COG 模組")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(extension="選擇載入的模組")
    @app_commands.rename(extension="模組")
    @app_commands.autocomplete(extension=extension_autocomplete)
    async def load(self, interaction: discord.Interaction, extension: str) -> None:
        await self._extension_action(interaction, "load", extension)

    @app_commands.command(name="卸載模組", description="卸載指定的 COG 模組")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(extension="選擇卸載的模組")
    @app_commands.rename(extension="模組")
    @app_commands.autocomplete(extension=unload_extension_autocomplete)
    async def unload(self, interaction: discord.Interaction, extension: str) -> None:
        await self._extension_action(interaction, "unload", extension)

    @app_commands.command(name="重新載入模組", description="重新載入指定的 COG 模組")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(extension="選擇重新載入的模組")
    @app_commands.rename(extension="模組")
    @app_commands.autocomplete(extension=extension_autocomplete)
    async def reload(self, interaction: discord.Interaction, extension: str) -> None:
        await self._extension_action(interaction, "reload", extension)

    @app_commands.command(name="機器人狀態", description="查看機器人目前狀態")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return

        latency = round(self.bot.latency * 1000)
        if latency < 100:
            color = discord.Color.green()
        elif latency < 200:
            color = discord.Color.yellow()
        else:
            color = discord.Color.red()

        embed = discord.Embed(title="機器人狀態", description="目前狀態如下", color=color)
        embed.add_field(name="延遲", value=f"{latency}ms", inline=True)
        embed.add_field(
            name="指令數量",
            value=(
                f"前綴: `{len(self.bot.commands)}`\t"
                f"斜線: `{len(self.bot.tree.get_commands())}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="WebSocket",
            value="已連接" if not self.bot.is_ws_ratelimited() else "受限",
            inline=True,
        )

        guild = interaction.guild
        channel = interaction.channel
        bot_member = guild.me if guild is not None else None
        if channel is not None and bot_member is not None:
            permissions = [
                f"- {name}"
                for name, enabled in channel.permissions_for(bot_member)
                if enabled
            ]
            permission_value = "\n".join(permissions[:10]) or "（無）"
        else:
            permission_value = "（無法取得）"

        embed.add_field(
            name=f"權限（{guild.name if guild is not None else '未知伺服器'}）",
            value=permission_value,
            inline=False,
        )

        active_extensions = set(self.bot.extensions)
        module_status = "\n".join(
            f"- {name} "
            f"{'✅' if self.bot.extension_path(name) in active_extensions else '❌'}"
            for name in self.bot.discover_extension_names()
        )
        embed.add_field(
            name="模組狀態",
            value=module_status[:1024] or "（無）",
            inline=False,
        )

        started_at = getattr(self.bot, "started_at", None)
        if started_at is not None:
            embed.add_field(
                name="在線時間",
                value=f"<t:{int(started_at.timestamp())}:R>",
                inline=False,
            )

        bot_user = self.bot.user
        if bot_user is not None:
            embed.set_author(name=bot_user.name, icon_url=bot_user.display_avatar.url)
        embed.set_footer(text=f"Discord Bot 版本：{getattr(self.bot, 'version', '未知')}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="重啟機器人", description="重新啟動機器人（僅限擁有者）")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def restart(self, interaction: discord.Interaction) -> None:
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "❌ 你不是機器人擁有者，無法使用此指令。",
                ephemeral=True,
            )
            return

        view = RestartConfirmView(self.bot, interaction)
        await interaction.response.send_message(
            "您確定要重新啟動機器人嗎？",
            view=view,
            ephemeral=True,
        )


class RestartConfirmView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        interaction: discord.Interaction,
        timeout: int = 120,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.interaction = interaction
        self.has_interacted = False

    def disable_all_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self) -> None:
        if self.has_interacted:
            return

        self.disable_all_buttons()
        try:
            await self.interaction.edit_original_response(
                content="⚠️ 重啟操作已過期，請重新執行指令。",
                view=self,
            )
        except discord.HTTPException as error:
            logger.warning(f"[重啟按鈕] 更新逾時狀態失敗：{error}")

    @discord.ui.button(
        label="✅ 確認重啟",
        style=discord.ButtonStyle.success,
        custom_id="restart_confirm",
        row=0,
    )
    async def confirm_restart(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "❌ 你無權操作此按鈕。",
                ephemeral=True,
            )
            return

        self.has_interacted = True
        self.disable_all_buttons()
        await interaction.response.edit_message(
            content="🔁 正在重啟機器人...",
            view=self,
        )
        logger.info("[重啟指令] Bot 正在重啟...")
        restart_program()

    @discord.ui.button(
        label="取消",
        style=discord.ButtonStyle.secondary,
        custom_id="restart_cancel",
        row=0,
        emoji="❌",
    )
    async def cancel_restart(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "❌ 你無權操作此按鈕。",
                ephemeral=True,
            )
            return

        self.has_interacted = True
        self.disable_all_buttons()
        await interaction.response.edit_message(
            content="✅ 已取消重啟操作。",
            view=self,
        )
        logger.info("[重啟指令] 已取消")


def restart_program() -> None:
    """Replace the current process with a fresh Python process."""
    python = sys.executable
    os.execl(python, python, *sys.argv)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ManagementCommand(bot))
