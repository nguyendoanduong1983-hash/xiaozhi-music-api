from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
import yt_dlp
import urllib.request
import urllib.parse
import json
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xiaozhi-music-api")

app = FastAPI(
    title="Xiaozhi Music API",
    description="API bóc tách và cung cấp luồng âm thanh liên tục (HTTP Progressive Stream) cho ESP32",
    version="2.1.0"
)

# Cấu hình yt-dlp cho YouTube: Ưu tiên HTTP/HTTPS trực tiếp, bài trừ hoàn toàn m3u8/HLS
YDL_OPTS_YT = {
    "format": "bestaudio[protocol^=http][protocol!*=m3u8][protocol!*=dash]/best[protocol^=http][protocol!*=m3u8]",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extractor_args": {
        "youtube": {
            "player_client": ["ios", "tv_embedded", "mweb"]
        }
    }
}

# Cấu hình yt-dlp cho SoundCloud: Ưu tiên progressive http_mp3, loại trừ m3u8
YDL_OPTS_SC = {
    "format": "http_mp3/bestaudio[protocol^=http][protocol!*=m3u8]/best[protocol^=http][protocol!*=m3u8]",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}

def is_hls_or_manifest(url: str, proto: str) -> bool:
    """Kiểm tra xem URL hoặc protocol có phải là HLS/m3u8/DASH hay không"""
    u = (url or "").lower()
    p = (proto or "").lower()
    if any(k in p for k in ["m3u8", "hls", "dash", "f4m", "rtmp"]):
        return True
    if ".m3u8" in u or "playlist" in u or ".mpd" in u or ".f4m" in u:
        return True
    return False

def find_best_progressive_audio(formats: list) -> dict:
    """
    Duyệt danh sách 'formats' để lọc ra URL luồng HTTP Progressive Stream đơn lẻ:
    1. LOẠI BỎ HOÀN TOÀN các định dạng HLS (m3u8, m3u8_native) và DASH (mpd).
    2. Ưu tiên tuyệt đối: MP3 > AAC/M4A > WebM/Opus.
    3. Ưu tiên bitrate nhẹ (64kbps - 160kbps) để ESP32 phát mượt, không nghẽn RAM.
    """
    if not formats:
        return None

    candidates = []
    for f in formats:
        url = f.get("url", "")
        proto = f.get("protocol") or ""
        ext = (f.get("ext") or "").lower()
        fmt_id = (f.get("format_id") or "").lower()
        abr = f.get("abr") or f.get("tbr") or 128
        acodec = (f.get("acodec") or "").lower()
        vcodec = (f.get("vcodec") or "none").lower()

        # Bỏ qua nếu không có URL hoặc không phải HTTP/HTTPS
        if not url or not url.startswith("http"):
            continue

        # LOẠI TRỪ 100%: m3u8, hls, dash manifest
        if is_hls_or_manifest(url, proto):
            continue

        # Bỏ qua nếu không có track âm thanh
        if acodec == "none":
            continue

        # Tính điểm ưu tiên
        score = 0

        # Ưu tiên 1: MP3 nguyên bản (ESP32 giải mã chuẩn nhất)
        if ext == "mp3" or "mp3" in fmt_id or "mp3" in acodec:
            score += 100
        # Ưu tiên 2: AAC / M4A
        elif ext in ["m4a", "aac"] or "aac" in acodec or "mp4a" in acodec:
            score += 80
        # Ưu tiên 3: WebM / Opus
        elif ext in ["webm", "ogg"] or "opus" in acodec:
            score += 40
        else:
            score += 20

        # Ưu tiên audio-only (không tốn băng thông video)
        if vcodec == "none":
            score += 30

        # Ưu tiên bitrate nhẹ 64k - 160k
        try:
            abr_val = float(abr)
            if 64 <= abr_val <= 160:
                score += 30
            elif abr_val < 64:
                score += 15
            elif abr_val > 160:
                score += 5
        except (ValueError, TypeError):
            score += 10

        candidates.append((score, abr, f))

    if not candidates:
        return None

    # Sắp xếp candidate điểm cao nhất
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2]

def get_hls_fallback_url(formats: list) -> str:
    """Tìm luồng HLS m3u8 tốt nhất để làm nguồn cho bộ chuyển đổi stream proxy nếu không có progressive direct link"""
    for f in formats:
        url = f.get("url", "")
        if url and (".m3u8" in url or "m3u8" in (f.get("protocol") or "")):
            return url
    return None

def stream_hls_to_progressive(m3u8_url: str):
    """
    Bộ chuyển đổi tự động (Server-side Stream Concatenator):
    Nếu bài hát chỉ có HLS (m3u8), Server sẽ tự động tải các chunk âm thanh tuần tự
    và bơm dòng byte âm thanh liên tục (chunked progressive stream) về ESP32.
    ESP32 chỉ việc nhận dòng byte âm thanh đơn lẻ và phát ngay, hoàn toàn không cần tải m3u8!
    """
    try:
        # Tải nội dung file m3u8 playlist
        req = urllib.request.Request(m3u8_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            playlist_content = resp.read().decode("utf-8", errors="ignore")

        # Bóc tách các URL chunk rời rạc
        base_url = m3u8_url.rsplit("/", 1)[0] + "/"
        chunk_urls = []
        for line in playlist_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith("http"):
                    chunk_urls.append(line)
                else:
                    chunk_urls.append(base_url + line)

        # Truyền liên tục từng chunk audio về cho ESP32
        for chunk_url in chunk_urls:
            try:
                c_req = urllib.request.Request(chunk_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(c_req, timeout=10) as c_resp:
                    while True:
                        data = c_resp.read(16384)
                        if not data:
                            break
                        yield data
            except Exception as ce:
                logger.warning(f"Error streaming chunk: {ce}")
    except Exception as e:
        logger.error(f"Error in stream_hls_to_progressive: {e}")

def extract_music(query: str, request: Request = None):
    """
    Trích xuất âm thanh không chứa m3u8:
    1. Thử YouTube lọc progressive format.
    2. Fallback sang SoundCloud lọc progressive format.
    3. Nếu chỉ có HLS m3u8: tự động tạo link /stream proxy của server để ESP32 nghe mượt mà không dính m3u8.
    """
    base_host = str(request.base_url).rstrip("/") if request else "https://xiaozhi-music-api.onrender.com"

    # 1. Thử YouTube
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_YT) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                v = info["entries"][0]
                formats = v.get("formats", [])
                
                # Duyệt tìm format progressive HTTP/HTTPS
                best_fmt = find_best_progressive_audio(formats)
                if best_fmt and best_fmt.get("url"):
                    return {
                        "source": "youtube",
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "duration": v.get("duration"),
                        "format_id": best_fmt.get("format_id"),
                        "ext": best_fmt.get("ext"),
                        "bitrate": best_fmt.get("abr") or best_fmt.get("tbr"),
                        "protocol": best_fmt.get("protocol"),
                        "stream_type": "direct_progressive",
                        "url": best_fmt.get("url")
                    }
    except Exception as e:
        logger.warning(f"YouTube extract failed: {e}")

    # 2. Thử SoundCloud
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_SC) as ydl:
            info = ydl.extract_info(f"scsearch1:{query}", download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                v = info["entries"][0]
                formats = v.get("formats", [])

                # 2.1 Tìm format progressive (ví dụ http_mp3_128)
                best_fmt = find_best_progressive_audio(formats)
                if best_fmt and best_fmt.get("url"):
                    return {
                        "source": "soundcloud",
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "duration": v.get("duration"),
                        "format_id": best_fmt.get("format_id"),
                        "ext": best_fmt.get("ext"),
                        "bitrate": best_fmt.get("abr") or best_fmt.get("tbr") or 128,
                        "protocol": best_fmt.get("protocol"),
                        "stream_type": "direct_progressive",
                        "url": best_fmt.get("url")
                    }

                # 2.2 Nếu SoundCloud chỉ có HLS (m3u8), tự động định tuyến qua server stream proxy
                # ESP32 sẽ gọi proxy và nhận dòng byte liên tục (không bao giờ thấy file .m3u8)
                hls_url = get_hls_fallback_url(formats)
                if hls_url:
                    encoded_hls = urllib.parse.quote(hls_url, safe="")
                    proxy_stream_url = f"{base_host}/stream?m3u8={encoded_hls}"
                    return {
                        "source": "soundcloud_hls_proxied",
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "duration": v.get("duration"),
                        "format_id": "progressive_stream_proxy",
                        "ext": "aac",
                        "bitrate": 128,
                        "protocol": "https_continuous_chunked",
                        "stream_type": "server_progressive_stream",
                        "url": proxy_stream_url
                    }
    except Exception as e:
        logger.error(f"SoundCloud extract failed: {e}")

    return None

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Xiaozhi Music API",
        "version": "2.1.0",
        "stream_type": "HTTP Progressive Stream (No HLS / No m3u8 for ESP32)",
        "endpoints": {
            "play_json": "/play?q=tên_bài_hát",
            "play_stream_redirect": "/redirect?q=tên_bài_hát",
            "continuous_stream": "/stream?m3u8=..."
        }
    }

@app.get("/play")
def play_json(request: Request, q: str = Query(..., description="Tên bài hát cần tìm")):
    """
    Trả về thông tin bài hát và URL stream âm thanh liên tục (JSON).
    Đảm bảo 100% không trả về link file .m3u8 cho ESP32.
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên bài hát")
    
    result = extract_music(q, request)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát có luồng âm thanh liên tục phù hợp")
    
    return {
        "status": "success",
        "data": result
    }

@app.get("/redirect")
def play_redirect(request: Request, q: str = Query(..., description="Tên bài hát cần tìm")):
    """
    Redirect 302 trực tiếp sang luồng âm thanh liên tục (MP3/AAC).
    ESP32 chỉ cần gọi connecttohost() vào link này là phát mượt mà từ đầu đến cuối.
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên bài hát")
    
    result = extract_music(q, request)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát có luồng âm thanh liên tục phù hợp")
    
    return RedirectResponse(url=result["url"], status_code=302)

@app.get("/stream")
def stream_audio(m3u8: str = Query(..., description="URL nguồn HLS")):
    """
    Luồng phát liên tục (Audio Stream Proxy):
    Server kết nối các phân đoạn âm thanh thành 1 luồng byte duy nhất truyền về ESP32.
    ESP32 chỉ cần nhận byte MP3/AAC như nghe một đài Radio thông thường!
    """
    if not m3u8.strip():
        raise HTTPException(status_code=400, detail="Thiếu URL nguồn m3u8")

    return StreamingResponse(
        stream_hls_to_progressive(m3u8),
        media_type="audio/aac",
        headers={
            "Transfer-Encoding": "chunked",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
