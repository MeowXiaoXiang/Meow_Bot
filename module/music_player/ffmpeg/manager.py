"""
FFmpeg 管理器

優先順序：
1. 系統 PATH 中的 ffmpeg（Docker/Linux 已安裝的）
2. 本地快取的 ffmpeg（之前下載過的）
3. 自動下載（從 GitHub BtbN/FFmpeg-Builds）

這樣 Docker 環境零下載，Windows 開發環境自動下載。
"""

import asyncio
import os
import platform
import shutil
import zipfile
import tarfile
from pathlib import Path
from typing import Optional
from loguru import logger

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


class FFmpegManager:
    """
    FFmpeg 管理器
    
    使用方式：
        manager = FFmpegManager()
        path = await manager.ensure_ffmpeg()
        # path 會是 "ffmpeg"（系統PATH）或絕對路徑
    """
    
    # GitHub BtbN/FFmpeg-Builds 下載 URL（穩定來源）
    DOWNLOAD_URLS = {
        "Windows": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "Linux": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    }
    
    def __init__(self, cache_dir: str = None):
        """
        初始化 FFmpeg 管理器
        
        Args:
            cache_dir: 快取目錄，預設為 module/music_player/ffmpeg/bin
        """
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            # 預設在模組目錄下
            self.cache_dir = Path(__file__).parent / "bin"
        
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._ffmpeg_path: Optional[str] = None
    
    @property
    def ffmpeg_path(self) -> Optional[str]:
        """取得 FFmpeg 路徑（如果已確認）"""
        return self._ffmpeg_path
    
    async def ensure_ffmpeg(self) -> Optional[str]:
        """
        確保 FFmpeg 可用，返回可執行路徑
        
        Returns:
            FFmpeg 執行路徑，失敗返回 None
        """
        # 1. 檢查系統 PATH
        system_ffmpeg = self._find_in_path()
        if system_ffmpeg:
            logger.info(f"使用系統 FFmpeg: {system_ffmpeg}")
            self._ffmpeg_path = system_ffmpeg
            return system_ffmpeg
        
        # 2. 檢查本地快取
        cached = self._find_cached()
        if cached:
            logger.info(f"使用快取 FFmpeg: {cached}")
            self._ffmpeg_path = str(cached)
            return str(cached)
        
        # 3. 下載
        logger.info("系統未安裝 FFmpeg，開始下載...")
        downloaded = await self._download_ffmpeg()
        if downloaded:
            logger.info(f"FFmpeg 下載完成: {downloaded}")
            self._ffmpeg_path = str(downloaded)
            return str(downloaded)
        
        logger.error("無法取得 FFmpeg")
        return None
    
    def _find_in_path(self) -> Optional[str]:
        """檢查系統 PATH 中是否有 ffmpeg"""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            # 驗證可執行
            try:
                result = os.popen(f'"{ffmpeg}" -version').read()
                if "ffmpeg version" in result:
                    return ffmpeg
            except Exception:
                pass
        return None
    
    def _find_cached(self) -> Optional[Path]:
        """檢查本地快取中是否有 ffmpeg"""
        system = platform.system()
        
        if system == "Windows":
            cached = self.cache_dir / "ffmpeg.exe"
        else:
            cached = self.cache_dir / "ffmpeg"
        
        if cached.exists():
            # 驗證可執行
            try:
                result = os.popen(f'"{cached}" -version').read()
                if "ffmpeg version" in result:
                    return cached
            except Exception:
                pass
        
        return None
    
    async def _download_ffmpeg(self) -> Optional[Path]:
        """從 GitHub 下載 FFmpeg"""
        if not HAS_AIOHTTP:
            logger.error("需要 aiohttp 來下載 FFmpeg，請執行: pip install aiohttp")
            return None
        
        system = platform.system()
        if system not in self.DOWNLOAD_URLS:
            logger.error(f"不支援的作業系統: {system}")
            return None
        
        url = self.DOWNLOAD_URLS[system]
        
        # 下載檔案
        if system == "Windows":
            archive_path = self.cache_dir / "ffmpeg.zip"
        else:
            archive_path = self.cache_dir / "ffmpeg.tar.xz"
        
        # 下載（帶重試）
        for attempt in range(3):
            try:
                await self._download_file(url, archive_path)
                break
            except Exception as e:
                logger.warning(f"下載失敗 (嘗試 {attempt + 1}/3): {e}")
                if attempt == 2:
                    return None
                await asyncio.sleep(2)
        
        # 解壓
        try:
            ffmpeg_path = await self._extract_ffmpeg(archive_path, system)
            return ffmpeg_path
        except Exception as e:
            logger.error(f"解壓失敗: {e}")
            return None
        finally:
            # 清理壓縮檔
            if archive_path.exists():
                archive_path.unlink()
    
    async def _download_file(self, url: str, dest: Path) -> None:
        """非同步下載檔案"""
        logger.info("正在從 GitHub 下載 FFmpeg（約 80-100MB，請稍候）...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                
                total = int(resp.headers.get('Content-Length', 0))
                downloaded = 0
                last_logged_percent = 0
                
                with open(dest, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # 只在 25%, 50%, 75% 輸出進度
                        if total:
                            percent = int(downloaded / total * 100)
                            if percent >= last_logged_percent + 25:
                                last_logged_percent = (percent // 25) * 25
                                logger.info(f"下載進度: {last_logged_percent}%")
                
                logger.info(f"下載完成: {downloaded / 1024 / 1024:.1f} MB")
    
    async def _extract_ffmpeg(self, archive: Path, system: str) -> Optional[Path]:
        """解壓 FFmpeg"""
        logger.info("正在解壓 FFmpeg...")
        
        extract_dir = self.cache_dir / "extract_temp"
        extract_dir.mkdir(exist_ok=True)
        
        try:
            # 解壓
            if system == "Windows":
                with zipfile.ZipFile(archive, 'r') as zf:
                    zf.extractall(extract_dir)
            else:
                with tarfile.open(archive, 'r:xz') as tf:
                    tf.extractall(extract_dir)
            
            # 找到 ffmpeg 執行檔
            ffmpeg_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
            
            for root, dirs, files in os.walk(extract_dir):
                if ffmpeg_name in files:
                    src = Path(root) / ffmpeg_name
                    dest = self.cache_dir / ffmpeg_name
                    
                    # 移動到快取目錄
                    shutil.move(str(src), str(dest))
                    
                    # Linux 需要設定執行權限
                    if system != "Windows":
                        os.chmod(dest, 0o755)
                    
                    logger.info(f"FFmpeg 已安裝到: {dest}")
                    return dest
            
            logger.error("在壓縮檔中找不到 ffmpeg")
            return None
            
        finally:
            # 清理解壓目錄
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)


# 便利函數
_manager: Optional[FFmpegManager] = None


async def get_ffmpeg_path(cache_dir: str = None) -> Optional[str]:
    """
    便利函數：取得 FFmpeg 路徑
    
    使用方式：
        ffmpeg_path = await get_ffmpeg_path()
    """
    global _manager
    
    if _manager is None:
        _manager = FFmpegManager(cache_dir=cache_dir)
    
    return await _manager.ensure_ffmpeg()
