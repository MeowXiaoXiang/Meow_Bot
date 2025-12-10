"""
yt-dlp 非同步下載器

使用 asyncio.create_subprocess_exec 實現純 async 操作：
- 完全不阻塞事件循環
- 不佔用 ThreadPoolExecutor 線程
- 無併發限制

支援功能：
- 提取單曲資訊
- 提取播放清單資訊
- 下載並轉換為 opus 格式
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Tuple, List, Callable
from loguru import logger


class YTDLPDownloader:
    """
    yt-dlp 非同步下載器
    
    使用方式：
        downloader = YTDLPDownloader(cache_dir="./cache", ffmpeg_path="/path/to/ffmpeg")
        
        # 提取單曲資訊
        info = await downloader.extract_info("https://www.youtube.com/watch?v=xxx")
        
        # 下載
        info, path = await downloader.download("https://www.youtube.com/watch?v=xxx")
    """
    
    # 錯誤模式對應表
    ERROR_PATTERNS = {
        "age_restricted": [
            "sign in to confirm your age",
            "age-restricted",
            "inappropriate for some users"
        ],
        "copyright": [
            "copyright grounds",
            "blocked it",
            "content owner",
            "has blocked"
        ],
        "region_blocked": [
            "not available in your country"
        ],
        "private": [
            "private video",
            "sign in if you've been granted access"
        ],
        "unavailable": [
            "video unavailable",
            "this video is unavailable",
            "no longer available",
            "has been removed",
            "account has been terminated"
        ]
    }
    
    # 無效標題模式
    INVALID_TITLE_PATTERNS = [
        "deleted video", "private video", "video unavailable",
        "track not found", "private track", "removed track",
        "track unavailable", "not available",
        "not found", "removed by artist",
        "content not available", "no longer exists"
    ]
    
    def __init__(
        self,
        download_dir: str = None,
        cache_dir: str = None,
        ffmpeg_path: str = None,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ):
        """
        初始化下載器
        
        Args:
            download_dir: 下載目錄路徑（與 cache_dir 互為別名）
            cache_dir: 快取目錄路徑（與 download_dir 互為別名）
            ffmpeg_path: FFmpeg 執行檔路徑
            progress_callback: 可選的進度回調函數 (song_id, percentage)
        """
        # 支援兩種參數名稱
        dir_path = download_dir or cache_dir or "./temp/music"
        self.cache_dir = Path(dir_path)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.ffmpeg_path = ffmpeg_path
        self.progress_callback = progress_callback
        
        logger.debug(f"YTDLPDownloader 初始化: cache_dir={dir_path}")
    
    # === 公開方法 ===
    
    async def extract_info(self, url: str, timeout: int = 30) -> Optional[dict]:
        """
        提取單曲資訊
        
        Args:
            url: 影片 URL
            timeout: 超時時間（秒）
        
        Returns:
            歌曲資訊字典，失敗返回 None 或錯誤字典
        """
        args = [
            "yt-dlp",
            "--dump-json",
            "--quiet",
            "--no-warnings",
            "--no-playlist",  # 單曲模式
            url
        ]
        
        logger.debug(f"[yt-dlp] extract_info 執行指令: {' '.join(args)}")
        
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                ),
                timeout=5  # 建立進程的超時
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )
            
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            
            logger.debug(f"[yt-dlp] extract_info returncode={proc.returncode}")
            if stderr_str:
                logger.debug(f"[yt-dlp] extract_info stderr: {stderr_str[:500]}")
            
            if proc.returncode != 0:
                error_msg = stderr_str or stdout_str or f"未知錯誤 (returncode={proc.returncode})"
                logger.error(f"yt-dlp extract_info 失敗: {error_msg}")
                return self._create_error_response(error_msg, url)
            
            data = json.loads(stdout_str)
            return self._parse_video_data(data)
            
        except asyncio.TimeoutError:
            logger.error(f"extract_info 超時 ({timeout}s): {url}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失敗: {e}")
            return None
        except Exception as e:
            logger.error(f"extract_info 錯誤: {type(e).__name__}: {e}")
            return None
    
    async def extract_playlist(self, url: str, timeout: int = 120) -> Optional[List[dict]]:
        """
        提取播放清單資訊
        
        Args:
            url: 播放清單 URL
            timeout: 超時時間（秒）
        
        Returns:
            歌曲資訊列表，失敗返回 None
        """
        args = [
            "yt-dlp",
            "--flat-playlist",
            "--dump-json",
            "--quiet",
            "--no-warnings",
            url
        ]
        
        logger.debug(f"[yt-dlp] extract_playlist 執行指令: {' '.join(args)}")
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )
            
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            
            logger.debug(f"[yt-dlp] extract_playlist returncode={proc.returncode}, stdout_len={len(stdout_str)}, stderr_len={len(stderr_str)}")
            if stderr_str:
                logger.debug(f"[yt-dlp] extract_playlist stderr: {stderr_str[:500]}")
            
            if proc.returncode != 0:
                error_msg = stderr_str or stdout_str or f"未知錯誤 (returncode={proc.returncode})"
                logger.error(f"yt-dlp extract_playlist 失敗 (returncode={proc.returncode}): {error_msg}")
                return None
            
            entries = []
            for line in stdout_str.split('\n'):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    info = self._parse_video_data(data)
                    if info:
                        entries.append(info)
                except json.JSONDecodeError:
                    continue
            
            logger.debug(f"播放清單提取完成: 共 {len(entries)} 首")
            return entries if entries else None
            
        except asyncio.TimeoutError:
            logger.error(f"extract_playlist 超時 ({timeout}s): {url}")
            return None
        except Exception as e:
            logger.error(f"extract_playlist 錯誤: {type(e).__name__}: {e}")
            return None
    
    async def download(
        self,
        url: str,
        song_id: Optional[str] = None,
        timeout: int = 180
    ) -> Tuple[Optional[dict], Optional[Path]]:
        """
        下載影片並轉換為 opus 格式
        
        Args:
            url: 影片 URL
            song_id: 可選的歌曲 ID（用於快取檢查，若不提供會先提取資訊）
            timeout: 下載超時時間（秒）
        
        Returns:
            (歌曲資訊, 檔案路徑) 或 (錯誤資訊, None)
        """
        # 如果沒有提供 song_id，先提取資訊
        if song_id is None:
            info = await self.extract_info(url)
            if not info:
                return None, None
            if info.get("success") is False:
                return info, None
            song_id = info["id"]
        else:
            info = None
        
        opus_path = self.cache_dir / f"{song_id}.opus"
        
        # 已有快取，直接回傳
        if opus_path.exists():
            logger.debug(f"快取已存在: {song_id}")
            # 如果還沒有 info，需要提取
            if info is None:
                info = await self.extract_info(url)
            return info, opus_path
        
        # 如果還沒有 info，提取它
        if info is None:
            info = await self.extract_info(url)
            if not info or info.get("success") is False:
                return info, None
        
        # 下載
        output_template = str(self.cache_dir / f"{song_id}.%(ext)s")
        args = [
            "yt-dlp",
            "--format", "bestaudio/best",
            "--output", output_template,
            "--no-playlist",
            "--quiet",              # 抑制大部分輸出
            "--no-warnings",        # 抑制警告
            "--progress",           # 但仍顯示進度（給回調用）
            "--newline",            # 進度每行輸出（方便解析）
            url
        ]
        
        logger.debug(f"[yt-dlp] download 執行指令: {' '.join(args)}")
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # 非同步讀取進度（只在有回調時處理，否則靜默）
            async for line in proc.stdout:
                line_str = line.decode().strip()
                if self.progress_callback and "[download]" in line_str:
                    progress = self._parse_progress(line_str)
                    if progress is not None:
                        self.progress_callback(song_id, progress)
            
            await asyncio.wait_for(proc.wait(), timeout=timeout)
            
            if proc.returncode != 0:
                stderr_content = await proc.stderr.read()
                error_msg = stderr_content.decode().strip()
                logger.error(f"下載失敗: {error_msg}")
                return self._create_error_response(error_msg, url), None
            
            # 找到下載的檔案
            downloaded = self._find_downloaded_file(song_id)
            if not downloaded:
                logger.error("找不到下載的檔案")
                return None, None
            
            # 轉換為 opus
            opus_path = await self._convert_to_opus(downloaded, song_id)
            if not opus_path:
                return None, None
            
            logger.debug(f"下載完成: {info.get('title', song_id)}")
            return info, opus_path
            
        except asyncio.TimeoutError:
            logger.error(f"下載超時: {url}")
            return None, None
        except Exception as e:
            logger.error(f"下載錯誤: {e}")
            return None, None
    
    def get_cached_path(self, song_id: str) -> Optional[Path]:
        """
        取得快取檔案路徑（如果存在）
        
        Args:
            song_id: 歌曲 ID
        
        Returns:
            快取路徑，不存在則返回 None
        """
        path = self.cache_dir / f"{song_id}.opus"
        return path if path.exists() else None
    
    def exists(self, song_id: str) -> bool:
        """
        檢查快取是否存在
        """
        return (self.cache_dir / f"{song_id}.opus").exists()
    
    # === 私有方法 ===
    
    async def _convert_to_opus(self, input_file: Path, song_id: str) -> Optional[Path]:
        """
        將下載的檔案轉換為 opus 格式
        """
        output_file = self.cache_dir / f"{song_id}.opus"
        
        args = [
            self.ffmpeg_path,
            "-i", str(input_file),
            "-c:a", "libopus",
            "-b:a", "128k",
            "-vbr", "on",
            "-application", "audio",
            "-ar", "48000",
            "-ac", "2",
            "-loglevel", "error",   # 只顯示錯誤，減少輸出
            "-y",
            str(output_file)
        ]
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            _, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error(f"FFmpeg 轉換失敗: {stderr.decode()}")
                # 轉換失敗也要刪除原始檔
                self._safe_delete(input_file)
                return None
            
            # 刪除原始檔
            self._safe_delete(input_file)
            
            logger.debug(f"轉換完成: {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"轉換錯誤: {e}")
            # 異常時也要清理原始檔
            self._safe_delete(input_file)
            return None
    
    def _safe_delete(self, file: Path) -> bool:
        """安全刪除檔案，失敗時僅記錄警告"""
        try:
            if file.exists():
                file.unlink()
                return True
        except Exception as e:
            logger.warning(f"刪除檔案失敗: {file} - {e}")
        return False
    
    def _find_downloaded_file(self, song_id: str) -> Optional[Path]:
        """
        找到下載的原始檔案（非 opus）
        """
        for file in self.cache_dir.iterdir():
            if file.stem == song_id and file.suffix != ".opus":
                return file
        return None
    
    def _parse_video_data(self, data: dict) -> Optional[dict]:
        """
        解析 yt-dlp 輸出的資料為標準格式
        """
        # 檢查影片是否有效
        if not self._is_valid_video(data):
            logger.warning(f"跳過無效影片: {data.get('title', 'Unknown')}")
            return None
        
        # 取得最佳縮圖
        thumb = self._pick_best_thumbnail(data)
        
        # 取得 uploader URL（多平台適配）
        uploader_url = (
            data.get("channel_url") or
            data.get("uploader_url") or
            data.get("artist_url") or
            data.get("creator_url") or
            ""
        )
        
        # 取得影片 URL
        page_url = data.get("webpage_url") or data.get("url") or ""
        
        # 如果沒有 URL，嘗試建構
        if not page_url and data.get("id"):
            extractor = (data.get("extractor") or "").lower()
            if "youtube" in extractor or not extractor:
                page_url = f"https://www.youtube.com/watch?v={data.get('id')}"
        
        # 處理 duration（確保轉為 int，某些平台如 Dailymotion 會回傳 float）
        duration = data.get("duration") or 0
        try:
            duration = int(float(duration)) if duration else 0
        except (ValueError, TypeError, OverflowError):
            # ValueError: 無效字串, TypeError: 無法轉換, OverflowError: inf/nan
            duration = 0
        
        return {
            "id": data.get("id"),
            "title": data.get("title") or "未知標題",
            "uploader": data.get("uploader") or data.get("artist") or "未知上傳者",
            "uploader_url": uploader_url,
            "duration": duration,
            "url": page_url,
            "thumbnail": thumb,
        }
    
    def _is_valid_video(self, data: dict) -> bool:
        """
        檢查影片是否有效
        """
        title = (data.get("title") or "").lower()
        uploader = (data.get("uploader") or "").lower()
        
        # 檢查無效標題
        for pattern in self.INVALID_TITLE_PATTERNS:
            if pattern in title:
                return False
        
        # 檢查空標題
        if not title or title in ["unknown title", "未知標題", "untitled"]:
            return False
        
        # 檢查時長（轉換為整數處理）
        duration = data.get("duration")
        if duration is not None:
            try:
                duration = int(float(duration))  # 處理 float 類型
                if duration <= 0:
                    return False
            except (ValueError, TypeError, OverflowError):
                # ValueError: 無效字串, TypeError: 無法轉換, OverflowError: inf/nan
                return False
        
        return True
    
    def _pick_best_thumbnail(self, data: dict) -> str:
        """
        選取最佳縮圖
        """
        thumb = data.get("thumbnail")
        if not thumb and data.get("thumbnails"):
            thumbnails = data["thumbnails"]
            if thumbnails:
                # 選最大尺寸
                thumb = max(
                    thumbnails,
                    key=lambda t: t.get("width", 0) * t.get("height", 0)
                ).get("url", "")
        return thumb or ""
    
    def _create_error_response(self, error_msg: str, url: str) -> dict:
        """
        根據錯誤訊息建立標準化的錯誤回應
        """
        error_type = self._detect_error_type(error_msg)
        
        return {
            "success": False,
            "error_type": error_type,
            "error_message": error_msg,
            "display_message": self._get_user_friendly_message(error_type),
            "url": url,
            "timestamp": time.time()
        }
    
    def _detect_error_type(self, error_msg: str) -> str:
        """
        根據錯誤訊息檢測錯誤類型
        """
        error_lower = error_msg.lower()
        
        for error_type, patterns in self.ERROR_PATTERNS.items():
            for pattern in patterns:
                if pattern in error_lower:
                    return error_type
        
        return "unknown"
    
    def _get_user_friendly_message(self, error_type: str) -> str:
        """
        取得使用者友善的錯誤訊息
        """
        messages = {
            "age_restricted": "此影片有年齡限制，無法播放",
            "copyright": "此影片因版權問題被阻擋",
            "region_blocked": "此影片在您的地區無法觀看",
            "private": "此影片為私人或不公開",
            "unavailable": "此影片已不可用",
            "unknown": "無法取得影片資訊"
        }
        return messages.get(error_type, messages["unknown"])
    
    def _parse_progress(self, line: str) -> Optional[float]:
        """
        從 yt-dlp 輸出解析下載進度
        
        例如：[download]  45.2% of 5.23MiB at 2.34MiB/s ETA 00:02
        """
        try:
            if "%" in line:
                # 找到百分比
                parts = line.split("%")[0].split()
                if parts:
                    percent_str = parts[-1]
                    return float(percent_str)
        except (ValueError, IndexError):
            pass
        return None
    
    # === URL 判斷 ===
    
    @staticmethod
    def is_playlist(url: str) -> bool:
        """
        判斷 URL 是否為播放清單
        
        Args:
            url: 影片或播放清單 URL
        
        Returns:
            是否為播放清單
        """
        url_lower = url.lower()
        
        # YouTube 播放清單
        if "list=" in url_lower:
            return True
        
        # YouTube Music 專輯
        if "music.youtube.com" in url_lower and "/playlist" in url_lower:
            return True
        
        # Spotify 播放清單或專輯
        if "spotify.com" in url_lower:
            if "/playlist/" in url_lower or "/album/" in url_lower:
                return True
        
        # SoundCloud 播放清單
        if "soundcloud.com" in url_lower and "/sets/" in url_lower:
            return True
        
        return False
