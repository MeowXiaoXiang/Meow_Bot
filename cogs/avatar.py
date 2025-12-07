import discord
from discord.ext import commands
from typing import Optional, Union
import aiohttp
from PIL import Image
from io import BytesIO


class Avatar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_average_color(self, avatar_url: str) -> tuple[int, int, int]:
        """非同步獲取圖片並計算平均顏色"""
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as response:
                image_data = await response.read()
        
        image = Image.open(BytesIO(image_data)).convert("RGB")
        pixels = list(image.getdata())
        num_pixels = len(pixels)
        
        r_total = sum(p[0] for p in pixels)
        g_total = sum(p[1] for p in pixels)
        b_total = sum(p[2] for p in pixels)
        
        return (r_total // num_pixels, g_total // num_pixels, b_total // num_pixels)

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
                user = self.bot.get_user(int(user_id))
                if user is None:
                    await interaction.response.send_message(
                        embed=discord.Embed(title="錯誤", description="無法找到指定的用戶", color=0xff0000), 
                        ephemeral=True
                    )
                    return
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

        # 延遲回應（圖片處理需要時間）
        await interaction.response.defer()

        avatar_url = member.avatar.url
        avg_color = await self._get_average_color(avatar_url)
        
        embed = discord.Embed(
            title=f"{member.name} 的頭貼", 
            description=f"[ :link: [完整大圖連結]]({avatar_url})\n", 
            color=discord.Color.from_rgb(*avg_color)
        )
        embed.set_image(url=avatar_url)

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Avatar(bot))