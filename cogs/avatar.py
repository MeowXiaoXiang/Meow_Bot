import asyncio
from io import BytesIO
from typing import Optional, Union

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageStat, UnidentifiedImageError


class Avatar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_average_color(self, avatar_url: str) -> tuple[int, int, int]:
        """非同步獲取圖片並計算平均顏色"""
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(avatar_url) as response:
                response.raise_for_status()
                image_data = await response.read()

        return await asyncio.to_thread(self._calculate_average_color, image_data)

    @staticmethod
    def _calculate_average_color(image_data: bytes) -> tuple[int, int, int]:
        with Image.open(BytesIO(image_data)) as source:
            image = source.convert("RGB")
            mean = ImageStat.Stat(image).mean
        return tuple(round(channel) for channel in mean)

    @discord.app_commands.command(name="查看成員頭貼", description="顯示目標成員的頭貼，可擇一使用選擇用戶或輸入用戶id")
    @discord.app_commands.describe(
        member="選擇你想查看的成員",
        user_id="輸入用戶id"
    )
    @discord.app_commands.rename(member="成員", user_id="用戶id")
    async def avatar(
        self, 
        interaction: discord.Interaction, 
        member: Optional[Union[discord.Member, discord.User]] = None, 
        user_id: Optional[str] = None
    ):
        # 預設為自己
        if not member and not user_id:
            member = interaction.user

        # 不能同時指定
        if member and user_id:
            await interaction.response.send_message(
                embed=discord.Embed(title="錯誤", description="請勿同時輸入成員和用戶id", color=0xff0000), 
                ephemeral=True
            )
            return

        # 透過 ID 查找用戶
        if user_id:
            try:
                parsed_user_id = int(user_id)
                user = self.bot.get_user(parsed_user_id)
                if user is None:
                    user = await self.bot.fetch_user(parsed_user_id)
                member = user
            except ValueError:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="錯誤",
                        description="請輸入正確的用戶id\n可透過打開discord設定內的開發者模式，使用滑鼠右鍵選單來對用戶複製id",
                        color=0xff0000
                    ),
                    ephemeral=True
                )
                return
            except discord.NotFound:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="錯誤",
                        description="無法找到指定的用戶",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True,
                )
                return
            except discord.HTTPException:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="錯誤",
                        description="Discord 暫時無法查詢該用戶，請稍後再試。",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True,
                )
                return

        # 延遲回應（圖片處理需要時間）
        await interaction.response.defer()

        avatar = member.display_avatar
        avatar_url = avatar.url
        color_source_url = avatar.replace(size=128, static_format="png").url
        try:
            avg_color = await self._get_average_color(color_source_url)
        except (aiohttp.ClientError, asyncio.TimeoutError, UnidentifiedImageError, OSError):
            await interaction.followup.send(
                "無法讀取頭貼圖片，請稍後再試。",
                ephemeral=True,
            )
            return
        
        embed = discord.Embed(
            title=f"{member.name} 的頭貼", 
            description=f"[ :link: [完整大圖連結]]({avatar_url})\n", 
            color=discord.Color.from_rgb(*avg_color)
        )
        embed.set_image(url=avatar_url)

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Avatar(bot))
