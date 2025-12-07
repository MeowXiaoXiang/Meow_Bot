import discord
from discord.ext import commands
import asyncio

class TicTacToe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.locks = {}  # {message_id: asyncio.Lock}
        self.games = {}  # {message_id: game_state}
        self.players = {}  # {message_id: [player1, player2]}
        self.last_move = {}  # {message_id: player_id} 新增一個字典來追蹤每個遊戲的最後一個動作
        self.current_turn = {}  # {message_id: player_id}
        self.in_game = set()  # 設定 playerid
        self.emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '👊', '❌']

    @discord.app_commands.command(name="小遊戲-ooxx", description="啟動小遊戲-ooxx")
    async def ooxx(self, interaction: discord.Interaction):
        if interaction.user.id in self.in_game:
            await interaction.response.send_message("你已經在遊戲中了!", ephemeral=True)
            return

        embed = discord.Embed(title="遊戲 [OOXX]", description=f"{interaction.user.display_name} ⭕ vs 等待其他玩家加入...\n\n按下 [👊] 接受並開始遊戲\n按下 [❌] 放棄遊戲", color=0x00ff00)
        await interaction.response.send_message(embed=embed, ephemeral=False) # 這條不會有回傳只能用original_response來取得訊息原本資料

        # Fetch the original response message
        msg = await interaction.original_response()

        self.games[msg.id] = self.emojis[:-2].copy()  # 使用self.emojis中的表情符號
        self.players[msg.id] = [interaction.user.id]
        self.last_move[msg.id] = interaction.user.id
        self.current_turn[msg.id] = interaction.user.id
        self.in_game.add(interaction.user.id)

        # 當遊戲被創建時，創建一個新的鎖並將其添加到 self.locks 字典中
        self.locks[msg.id] = asyncio.Lock()

        await msg.add_reaction('👊')
        await msg.add_reaction('❌')

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.id == self.bot.user.id:
            return

        if reaction.message.id in self.games:
            async with self.locks[reaction.message.id]:
                if len(self.players[reaction.message.id]) == 2 and user.id != self.current_turn[reaction.message.id] and str(reaction.emoji) in self.emojis[:-2]:
                    await reaction.message.remove_reaction(str(reaction.emoji), user)
                if reaction.message.id in self.games and user.id not in self.in_game and str(reaction.emoji) == '👊':
                    self.players[reaction.message.id].append(user.id)
                    self.in_game.add(user.id)
                    embed = discord.Embed(title="遊戲 [OOXX]", description=f"{self.bot.get_user(self.players[reaction.message.id][0]).display_name} ⭕ vs {user.display_name} ❌\n按下 ❌ 放棄遊戲", color=0x00ff00)
                    await reaction.message.edit(content=self.format_game(self.games[reaction.message.id]), embed=embed)
                    await reaction.message.clear_reactions()

                    for emoji in self.emojis[:-2]:
                        await reaction.message.add_reaction(emoji)
                    await reaction.message.add_reaction('❌')

                    self.current_turn[reaction.message.id] = self.players[reaction.message.id][0]
                    self.last_move[reaction.message.id] = None  # 初始化這個遊戲的最後一個動作
                    return

                if reaction.message.id in self.games and user.id == self.current_turn[reaction.message.id] and str(reaction.emoji) in self.emojis[:-2]:
                    # 檢查這個玩家是否已經在這個回合中進行過動作
                    if self.last_move.get(reaction.message.id) == user.id:
                        return

                    # 玩家進行動作後，立即更新 last_move 字典
                    self.last_move[reaction.message.id] = user.id
                    game = self.games[reaction.message.id]
                    player_num = self.players[reaction.message.id].index(user.id)
                    move = self.emojis.index(str(reaction.emoji))

                    if game[move] == self.emojis[move]:
                        game[move] = "⭕" if player_num == 0 else "❌"
                        embed = discord.Embed(title="遊戲 [OOXX]", description=f"{self.bot.get_user(self.players[reaction.message.id][0]).display_name} ⭕ vs {self.bot.get_user(self.players[reaction.message.id][1]).display_name} ❌\n按下 ❌ 放棄遊戲", color=0x00ff00)
                        await reaction.message.edit(content=self.format_game(game), embed=embed)
                        await reaction.message.clear_reaction(str(reaction.emoji))

                        if self.check_win(game):
                            winner_name = self.bot.get_user(self.players[reaction.message.id][player_num]).display_name
                            winner_emoji = "⭕" if player_num == 0 else "❌"
                            embed = discord.Embed(title="遊戲 [OOXX]", description=f"{self.bot.get_user(self.players[reaction.message.id][0]).display_name} ⭕ vs {self.bot.get_user(self.players[reaction.message.id][1]).display_name} ❌\n{winner_name} {winner_emoji} 勝利!", color=0x00ff00)
                            await reaction.message.edit(content=self.format_game(game), embed=embed)
                            await reaction.message.clear_reactions()
                            del self.games[reaction.message.id]
                            self.in_game.remove(self.players[reaction.message.id][0])
                            self.in_game.remove(self.players[reaction.message.id][1])
                            del self.players[reaction.message.id]
                            del self.last_move[reaction.message.id]  # 遊戲結束時，刪除這個遊戲的最後一個動作
                        elif not any(cell in self.emojis[:-2] for cell in game):  # 檢查
                            player1_name = self.bot.get_user(self.players[reaction.message.id][0]).display_name
                            player2_name = self.bot.get_user(self.players[reaction.message.id][1]).display_name
                            embed = discord.Embed(title="遊戲 [OOXX]", description=f"{player1_name} ⭕ vs {player2_name} ❌\n遊戲結果為平手!", color=0x00ff00)
                            await reaction.message.edit(content=self.format_game(game), embed=embed)
                            await reaction.message.clear_reactions()
                            del self.games[reaction.message.id]
                            self.in_game.remove(self.players[reaction.message.id][0])
                            self.in_game.remove(self.players[reaction.message.id][1])
                            del self.players[reaction.message.id]
                            del self.last_move[reaction.message.id]  # 遊戲結束時，刪除這個遊戲的最後一個動作

                        # 切換回合
                        if reaction.message.id in self.players:
                            self.current_turn[reaction.message.id] = self.players[reaction.message.id][1 if player_num == 0 else 0]
                            self.last_move[reaction.message.id] = user.id

                if reaction.message.id in self.games and user.id in self.players[reaction.message.id] and str(reaction.emoji) == '❌':
                    game = self.games[reaction.message.id]
                    if len(self.players[reaction.message.id]) == 1:  #剩下一位玩家自己打算放棄遊戲沒配對到人的情況
                        embed = discord.Embed(title="遊戲 [OOXX]", description=f"{user.display_name} 放棄遊戲!", color=0x00ff00)
                        await reaction.message.edit(embed=embed)
                        await reaction.message.clear_reactions()
                        del self.games[reaction.message.id]
                        self.in_game.remove(self.players[reaction.message.id][0])
                        del self.players[reaction.message.id]
                    else:  # 正在遊玩中，但是有一方放棄遊戲的情況
                        player_num = self.players[reaction.message.id].index(user.id)
                        winner_num = 0 if player_num == 1 else 1
                        winner_name = self.bot.get_user(self.players[reaction.message.id][winner_num]).display_name
                        winner_emoji = "⭕" if winner_num == 0 else "❌"
                        embed = discord.Embed(title="遊戲 [OOXX]", description=f"{self.bot.get_user(self.players[reaction.message.id][0]).display_name} ⭕ vs {self.bot.get_user(self.players[reaction.message.id][1]).display_name} ❌\n{winner_name} {winner_emoji} 勝利! {user.display_name} 放棄遊戲!", color=0x00ff00)
                        await reaction.message.edit(content=self.format_game(game), embed=embed)
                        await reaction.message.clear_reactions()
                        del self.games[reaction.message.id]
                        self.in_game.remove(self.players[reaction.message.id][0])
                        self.in_game.remove(self.players[reaction.message.id][1])
                        del self.players[reaction.message.id]

    def format_game(self, game):
        return "\n".join("".join(str(cell) for cell in game[i*3:i*3+3]) for i in range(3))

    def check_win(self, game):
        for i in range(3):
            if game[i*3] == game[i*3+1] == game[i*3+2] or game[i] == game[i+3] == game[i+6]:
                return True
        if game[0] == game[4] == game[8] or game[2] == game[4] == game[6]:
            return True
        return False

async def setup(bot):
    await bot.add_cog(TicTacToe(bot))