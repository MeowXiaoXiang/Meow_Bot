import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.music_cog import MusicPlayerCog
from module.music_player.constants import CACHE_WINDOW_AHEAD, CACHE_WINDOW_BEHIND
from module.music_player.core.player import MusicPlayer
from module.music_player.core.queue import Song
from module.music_player.ui.embeds import EmbedBuilder
from module.music_player.ytdlp import YTDLPBootstrapError, YTDLPClient, YTDLPManager


class YTDLPManagerTests(unittest.IsolatedAsyncioTestCase):
    def test_windows_arm64_uses_official_arm64_asset(self) -> None:
        manager = YTDLPManager("managed-bin")

        with (
            patch("module.music_player.ytdlp.manager.platform.system", return_value="Windows"),
            patch("module.music_player.ytdlp.manager.platform.machine", return_value="ARM64"),
        ):
            asset, destination = manager._target_asset()

        self.assertEqual(asset, "yt-dlp_arm64.exe")
        self.assertEqual(destination, Path("managed-bin") / "yt-dlp.exe")

    def test_linux_musl_uses_official_musl_asset(self) -> None:
        manager = YTDLPManager("managed-bin")

        with (
            patch("module.music_player.ytdlp.manager.platform.system", return_value="Linux"),
            patch("module.music_player.ytdlp.manager.platform.machine", return_value="x86_64"),
            patch.object(manager, "_uses_musl", return_value=True),
        ):
            asset, destination = manager._target_asset()

        self.assertEqual(asset, "yt-dlp_musllinux")
        self.assertEqual(destination, Path("managed-bin") / "yt-dlp")

    def test_checksum_for_unknown_asset_fails(self) -> None:
        with self.assertRaises(ValueError):
            YTDLPManager._checksum_for_asset("abc123  yt-dlp_linux", "yt-dlp.exe")

    async def test_first_download_failure_raises_bootstrap_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = YTDLPManager(temp_dir)
            with (
                patch.object(
                    manager,
                    "_target_asset",
                    return_value=("yt-dlp.exe", Path(temp_dir) / "yt-dlp.exe"),
                ),
                patch.object(manager, "_is_usable", new=AsyncMock(return_value=False)),
                patch.object(
                    manager,
                    "_download_and_install",
                    new=AsyncMock(side_effect=OSError("network unavailable")),
                ),
            ):
                with self.assertRaises(YTDLPBootstrapError):
                    await manager.ensure_ready()

    async def test_existing_binary_survives_failed_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "yt-dlp.exe"
            executable.touch()
            manager = YTDLPManager(temp_dir)

            with patch.object(
                manager,
                "_target_asset",
                return_value=("yt-dlp.exe", executable),
            ), patch.object(
                manager,
                "_run_command",
                new=AsyncMock(
                    side_effect=[
                        (0, "2026.01.01", ""),
                        (1, "", "network unavailable"),
                        (0, "2026.01.01", ""),
                    ]
                ),
            ), patch.object(
                manager, "_download_and_install", new=AsyncMock()
            ) as mocked_download:
                result = await manager.ensure_ready()

        self.assertEqual(result, executable)
        mocked_download.assert_not_awaited()


class YTDLPClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_info_uses_managed_executable_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = YTDLPClient(
                ytdlp_path=Path(temp_dir) / "yt-dlp.exe",
                ffmpeg_path=Path(temp_dir) / "ffmpeg.exe",
                cache_dir=Path(temp_dir) / "cache",
            )
            process = SimpleNamespace(returncode=0)

            with (
                patch.object(client, "_create_process", new=AsyncMock(return_value=process)) as create,
                patch.object(
                    client,
                    "_communicate_with_timeout",
                    new=AsyncMock(return_value=(b'{"id":"id","title":"title","duration":1}', b"")),
                ),
            ):
                await client.extract_info("https://example.invalid/video")

            self.assertEqual(create.await_args.args[0], client.ytdlp_path)

    async def test_download_reuses_provided_info_for_cached_song(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            client = YTDLPClient(
                ytdlp_path=Path(temp_dir) / "yt-dlp.exe",
                ffmpeg_path=Path(temp_dir) / "ffmpeg.exe",
                cache_dir=cache_dir,
            )
            cached_path = cache_dir / "song-id.opus"
            cached_path.write_bytes(b"cached audio")
            info = {"id": "song-id", "title": "Cached song"}

            with patch.object(client, "extract_info", new=AsyncMock()) as extract:
                returned_info, path = await client.download(
                    "https://example.invalid/video",
                    song_id="song-id",
                    info=info,
                )

        self.assertEqual(returned_info, info)
        self.assertEqual(path, cached_path)
        extract.assert_not_awaited()


class EmbedBuilderTests(unittest.TestCase):
    def test_player_embed_uses_one_based_queue_index(self) -> None:
        song = Song(
            id="song-id",
            title="Song title",
            url="https://example.invalid/video",
            duration=60,
            uploader="Uploader",
        )
        player = SimpleNamespace(
            current_song=song,
            is_playing=True,
            loop=False,
            state=SimpleNamespace(current_position=0),
            queue=SimpleNamespace(current_index_one_based=2),
        )

        embed = EmbedBuilder().player_embed(player)

        self.assertEqual(
            embed.description,
            "2. [Song title](https://example.invalid/video)",
        )


class MusicCogPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_path_tool_fails_initialization(self) -> None:
        with patch("cogs.music_cog.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
                await MusicPlayerCog._require_path_executable("ffmpeg", "-version")

    async def test_ffmpeg_without_libopus_fails_initialization(self) -> None:
        process = SimpleNamespace(
            returncode=0,
            communicate=AsyncMock(return_value=(b"Encoders:\\n", b"")),
        )

        with (
            patch("cogs.music_cog.shutil.which", return_value="ffmpeg"),
            patch(
                "cogs.music_cog.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "libopus"):
                await MusicPlayerCog._require_ffmpeg_with_libopus()


class MusicPlayerConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_window_uses_exported_constants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            player = MusicPlayer(
                client=object(),
                ffmpeg_path="ffmpeg",
                cache_dir=temp_dir,
            )

        self.assertEqual(player.cache.window_behind, CACHE_WINDOW_BEHIND)
        self.assertEqual(player.cache.window_ahead, CACHE_WINDOW_AHEAD)


if __name__ == "__main__":
    unittest.main()
