import discord
from discord.ext import commands
import random

class Minesweeper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="踩地雷", description="開始一場踩地雷遊戲！")
    @discord.app_commands.describe(
        columns="地圖的列數[直] (1-9)，預設為 7",
        rows="地圖的行數[橫] (1-9)，預設為 7",
        bombs="炸彈數量，預設為 10"
    )
    @discord.app_commands.rename(columns="列數", rows="行數", bombs="炸彈數量")
    async def minesweeper(self, interaction: discord.Interaction, columns: int = 7, rows: int = 7, bombs: int = 10):
        # 驗證行列數範圍
        if not (1 <= columns <= 9 and 1 <= rows <= 9):
            await interaction.response.send_message("列與行數需在 1-9 之間！", ephemeral=True)
            return

        # 驗證炸彈數量是否合理
        if bombs >= columns * rows:
            await interaction.response.send_message("炸彈數量不能超過網格總數！", ephemeral=True)
            return

        # 初始化地圖
        grid = [[0 for _ in range(columns)] for _ in range(rows)]

        # 隨機放置炸彈
        for _ in range(bombs):
            while True:
                x, y = random.randint(0, columns - 1), random.randint(0, rows - 1)
                if grid[y][x] != 'B':  # 防止重複放置炸彈，然後出bug(?
                    grid[y][x] = 'B'
                    break

        # 計算每個格子周圍的炸彈數
        directions = [
            (0, 1), (0, -1), (1, 0), (-1, 0),  # 上、下、左、右
            (1, 1), (-1, -1), (1, -1), (-1, 1)  # 四個對角線
        ]
        for y in range(rows):
            for x in range(columns):
                if grid[y][x] == 'B':  # 如果是炸彈，則跳過
                    continue
                # 計算周圍炸彈數量
                bomb_count = sum(
                    1 for dx, dy in directions
                    if 0 <= x + dx < columns and 0 <= y + dy < rows and grid[y + dy][x + dx] == 'B'
                )
                grid[y][x] = bomb_count

        # 建構地圖字串
        emoji_map = {
            0: '||:zero:||', 1: '||:one:||', 2: '||:two:||', 3: '||:three:||',
            4: '||:four:||', 5: '||:five:||', 6: '||:six:||', 7: '||:seven:||',
            8: '||:eight:||', 'B': '||:bomb:||'
        }
        final_map = '\n'.join(''.join(emoji_map[cell] for cell in row) for row in grid)

        # 計算炸彈比例
        percentage = round((bombs / (columns * rows)) * 100, 2)

        # 回傳嵌入訊息
        embed = discord.Embed(title="💣 踩地雷！", color=discord.Color.orange())
        embed.add_field(name="列數", value=columns, inline=True)
        embed.add_field(name="行數", value=rows, inline=True)
        embed.add_field(name="炸彈數量", value=bombs, inline=True)
        embed.add_field(name="炸彈比例", value=f"{percentage}%", inline=True)
        await interaction.response.send_message(content=final_map, embed=embed)

async def setup(bot):
    await bot.add_cog(Minesweeper(bot))
