from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
import yt_dlp
import urllib.request
import urllib.parse
import json
import logging
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xiaozhi-music-api")

app = FastAPI(
    title="Xiaozhi Music API",
    description="API tìm kiếm và bóc tách stream âm thanh YouTube cho ESP32 Xiaozhi Robot",
    version="1.1.0"
)

# Cấu hình yt-dlp dùng Android client để không bị YouTube chặn IP datacenter
YDL_OPTS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "ios", "web"]
        }
    }
}

def extract_via_piped(query: str):
    """Fallback: Tìm kiếm và lấy audio stream qua Piped API nếu YouTube chặn server"""
    instances = [
        "https://api.piped.privacydev.net",
        "https://pipedapi.kavin.rocks",
        "https://piped-api.lunar.icu"
    ]
    for base in instances:
        try:
            # 1. Search
            encoded = urllib.parse.quote(query)
            search_url = f"{base}/search?q={encoded}&filter=music_songs"
            req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                items = data.get("items", [])
                if not items:
                    continue
                first = items[0]
                url_path = first.get("url", "")
                video_id = url_path.split("=")[-1] if "=" in url_path else url_path.replace("/watch?v=", "")
                title = first.get("title")
                uploader = first.get("uploaderName")
                duration = first.get("duration")

            # 2. Get streams
            stream_url = f"{base}/streams/{video_id}"
            req_stream = urllib.request.Request(stream_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_stream, timeout=6) as resp:
                stream_data = json.loads(resp.read().decode())
                audio_streams = stream_data.get("audioStreams", [])
                if audio_streams:
                    # Lấy audio stream tốt nhất
                    best = audio_streams[-1]
                    return {
                        "id": video_id,
                        "title": title or stream_data.get("title"),
                        "duration": duration or stream_data.get("duration"),
                        "uploader": uploader or stream_data.get("uploader"),
                        "url": best.get("url")
                    }
        except Exception as e:
            logger.warning(f"Piped instance {base} failed: {e}")
            continue
    return None

def extract_youtube_audio(query: str):
    """Tìm kiếm YouTube bằng yt-dlp, tự động fallback sang Piped nếu cần"""
    search_query = f"ytsearch1:{query}"
    # Cách 1: yt-dlp với Android/iOS player client
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                video = info["entries"][0]
                audio_url = video.get("url")
                if not audio_url and "formats" in video:
                    for fmt in reversed(video["formats"]):
                        if fmt.get("acodec") != "none" and fmt.get("url"):
                            audio_url = fmt["url"]
                            break
                if audio_url:
                    return {
                        "id": video.get("id"),
                        "title": video.get("title"),
                        "duration": video.get("duration"),
                        "uploader": video.get("uploader"),
                        "url": audio_url
                    }
    except Exception as e:
        logger.error(f"yt-dlp error for '{query}': {e}")
    
    # Cách 2: Fallback Piped API
    logger.info("Falling back to Piped API...")
    return extract_via_piped(query)

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Xiaozhi Music API",
        "version": "1.1.0",
        "endpoints": {
            "play_json": "/play?q=tên_bài_hát",
            "play_stream_redirect": "/redirect?q=tên_bài_hát"
        }
    }

@app.get("/play")
def play_json(q: str = Query(..., description="Tên bài hát cần tìm")):
    """Trả về thông tin bài hát và direct stream URL dưới dạng JSON"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên bài hát")
    
    result = extract_youtube_audio(q)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát trên YouTube")
    
    return {
        "status": "success",
        "data": result
    }

@app.get("/redirect")
def play_redirect(q: str = Query(..., description="Tên bài hát cần tìm")):
    """Redirect thẳng 302 sang stream audio - Dành cho ESP32 connecttohost"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên bài hát")
    
    result = extract_youtube_audio(q)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát trên YouTube")
    
    return RedirectResponse(url=result["url"], status_code=302)

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
