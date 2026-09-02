"""yt-dlp standalone executable lifecycle management."""

import asyncio
import hashlib
import os
import platform
from pathlib import Path

import aiohttp
from loguru import logger


class YTDLPBootstrapError(RuntimeError):
    """Raised when no usable managed yt-dlp executable can be prepared."""


class YTDLPManager:
    """Prepare and update the project-managed nightly yt-dlp executable."""

    RELEASE_BASE_URL = (
        "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download"
    )
    CHECKSUM_ASSET = "SHA2-256SUMS"
    DOWNLOAD_TIMEOUT_SECONDS = 300
    UPDATE_TIMEOUT_SECONDS = 300
    PROBE_TIMEOUT_SECONDS = 15

    def __init__(self, binary_dir: str | Path | None = None):
        self.binary_dir = (
            Path(binary_dir)
            if binary_dir is not None
            else Path(__file__).parent / "bin"
        )
        self._executable_path: Path | None = None
        self._lock = asyncio.Lock()

    @property
    def executable_path(self) -> Path | None:
        """Return the managed executable after it has been prepared."""
        return self._executable_path

    async def ensure_ready(self) -> Path:
        """Return a verified managed binary, downloading it when necessary."""
        async with self._lock:
            asset_name, executable_path = self._target_asset()

            if await self._is_usable(executable_path):
                await self._update_existing(executable_path)
                if await self._is_usable(executable_path):
                    self._executable_path = executable_path
                    return executable_path

                logger.warning(
                    "[YT-DLP] 更新後 binary 無法使用，嘗試重新取得 nightly binary"
                )

            try:
                await self._download_and_install(asset_name, executable_path)
            except Exception as error:
                message = f"無法準備 yt-dlp binary: {type(error).__name__}: {error}"
                logger.error(f"[YT-DLP] {message}")
                raise YTDLPBootstrapError(message) from error

            if not await self._is_usable(executable_path):
                message = f"下載後的 yt-dlp binary 無法執行: {executable_path}"
                logger.error(f"[YT-DLP] {message}")
                raise YTDLPBootstrapError(message)

            self._executable_path = executable_path
            logger.info(f"[YT-DLP] binary 已準備完成: {executable_path}")
            return executable_path

    def _target_asset(self) -> tuple[str, Path]:
        system = platform.system()
        machine = platform.machine().lower()

        if system == "Windows":
            assets = {
                "amd64": "yt-dlp.exe",
                "x86_64": "yt-dlp.exe",
                "arm64": "yt-dlp_arm64.exe",
                "aarch64": "yt-dlp_arm64.exe",
            }
            asset_name = assets.get(machine)
            executable_name = "yt-dlp.exe"
        elif system == "Linux":
            if self._uses_musl():
                assets = {
                    "amd64": "yt-dlp_musllinux",
                    "x86_64": "yt-dlp_musllinux",
                    "arm64": "yt-dlp_musllinux_aarch64",
                    "aarch64": "yt-dlp_musllinux_aarch64",
                }
            else:
                assets = {
                    "amd64": "yt-dlp_linux",
                    "x86_64": "yt-dlp_linux",
                    "arm64": "yt-dlp_linux_aarch64",
                    "aarch64": "yt-dlp_linux_aarch64",
                }
            asset_name = assets.get(machine)
            executable_name = "yt-dlp"
        else:
            raise YTDLPBootstrapError(f"不支援的 yt-dlp 作業系統: {system}")

        if asset_name is None:
            raise YTDLPBootstrapError(
                f"不支援的 yt-dlp CPU 架構: {system} {machine}"
            )

        return asset_name, self.binary_dir / executable_name

    @staticmethod
    def _uses_musl() -> bool:
        libc_name = platform.libc_ver()[0].lower()
        if "musl" in libc_name:
            return True

        try:
            return b"musl" in Path("/usr/bin/ldd").read_bytes()[:4096].lower()
        except OSError:
            return False

    async def _update_existing(self, executable_path: Path) -> None:
        result = await self._run_command(
            executable_path,
            "--update-to",
            "nightly",
            timeout=self.UPDATE_TIMEOUT_SECONDS,
        )
        if result is None:
            logger.warning("[YT-DLP] nightly 更新無法啟動，保留既有 binary")
            return

        returncode, stdout, stderr = result
        if returncode == 0:
            logger.info("[YT-DLP] nightly 更新檢查完成")
            if stdout:
                logger.debug(f"[YT-DLP] update stdout: {stdout}")
            return

        details = stderr or stdout or f"returncode={returncode}"
        logger.warning(f"[YT-DLP] nightly 更新失敗，保留既有 binary: {details}")

    async def _download_and_install(
        self,
        asset_name: str,
        executable_path: Path,
    ) -> None:
        self.binary_dir.mkdir(parents=True, exist_ok=True)
        part_path = executable_path.with_name(f"{executable_path.name}.part")

        try:
            timeout = aiohttp.ClientTimeout(total=self.DOWNLOAD_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                checksums = await self._download_bytes(
                    session, f"{self.RELEASE_BASE_URL}/{self.CHECKSUM_ASSET}"
                )
                expected_hash = self._checksum_for_asset(checksums.decode("utf-8"), asset_name)
                actual_hash = await self._download_file(
                    session,
                    f"{self.RELEASE_BASE_URL}/{asset_name}",
                    part_path,
                )

            if actual_hash.lower() != expected_hash.lower():
                raise ValueError(f"{asset_name} 的 SHA-256 驗證失敗")

            if platform.system() != "Windows":
                os.chmod(part_path, 0o755)
            os.replace(part_path, executable_path)
        finally:
            part_path.unlink(missing_ok=True)

    @staticmethod
    def _checksum_for_asset(checksums: str, asset_name: str) -> str:
        for line in checksums.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1].lstrip("*") == asset_name:
                return fields[0]
        raise ValueError(f"checksum 清單中找不到 {asset_name}")

    @staticmethod
    async def _download_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()

    @staticmethod
    async def _download_file(
        session: aiohttp.ClientSession,
        url: str,
        destination: Path,
    ) -> str:
        digest = hashlib.sha256()
        async with session.get(url) as response:
            response.raise_for_status()
            with destination.open("wb") as file:
                async for chunk in response.content.iter_chunked(64 * 1024):
                    file.write(chunk)
                    digest.update(chunk)
        return digest.hexdigest()

    async def _is_usable(self, executable_path: Path) -> bool:
        if not executable_path.is_file():
            return False

        result = await self._run_command(
            executable_path,
            "--version",
            timeout=self.PROBE_TIMEOUT_SECONDS,
        )
        return result is not None and result[0] == 0

    @staticmethod
    async def _run_command(
        executable_path: Path,
        *args: str,
        timeout: int,
    ) -> tuple[int, str, str] | None:
        try:
            process = await asyncio.create_subprocess_exec(
                str(executable_path),
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            logger.debug(f"[YT-DLP] 無法啟動 {executable_path}: {error}")
            return None

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            if isinstance(error, asyncio.TimeoutError):
                logger.warning(
                    f"[YT-DLP] 指令逾時，終止中: {executable_path} {' '.join(args)}"
                )
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            return None

        return (
            process.returncode or 0,
            stdout.decode(errors="replace").strip(),
            stderr.decode(errors="replace").strip(),
        )
