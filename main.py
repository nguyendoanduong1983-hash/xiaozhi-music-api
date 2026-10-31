from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
import yt_dlp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xiaozhi-music-api")

app = FastAPI(
    title="Xiaozhi Music API",
    description="API tìm kiếm và bóc tách stream âm thanh YouTube cho ESP32 Xiaozhi Robot",
    version="1.2.0"
)

# Cấu hình yt-dlp dùng client ios / tv_embedded để bypass bot-detection trên datacenter
YDL_OPTS_YT = {
    "format": "bestaudio/best",
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

YDL_OPTS_SC = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}

def extract_music(query: str):
    """Tìm kiếm YouTube (client iOS/TV), nếu lỗi thì fallback sang SoundCloud"""
    # 1. Thử YouTube qua client iOS / TV embedded
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_YT) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                v = info["entries"][0]
                url = v.get("url")
                if not url and "formats" in v:
                    for f in reversed(v["formats"]):
                        if f.get("acodec") != "none" and f.get("url"):
                            url = f["url"]
                            break
                if url:
                    return {
                        "source": "youtube",
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "duration": v.get("duration"),
                        "url": url
                    }
    except Exception as e:
        logger.warning(f"YouTube extract failed: {e}")

    # 2. Fallback sang SoundCloud (100% không bị chặn IP datacenter)
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_SC) as ydl:
            info = ydl.extract_info(f"scsearch1:{query}", download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                v = info["entries"][0]
                url = v.get("url")
                if url:
                    return {
                        "source": "soundcloud",
                        "id": v.get("id"),
                        "title": v.get("title"),
                        "duration": v.get("duration"),
                        "url": url
                    }
    except Exception as e:
        logger.error(f"SoundCloud extract failed: {e}")

    return None

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Xiaozhi Music API",
        "version": "1.2.0",
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
    
    result = extract_music(q)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát")
    
    return {
        "status": "success",
        "data": result
    }

@app.get("/redirect")
def play_redirect(q: str = Query(..., description="Tên bài hát cần tìm")):
    """Redirect thẳng 302 sang stream audio - Dành cho ESP32 connecttohost"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên bài hát")
    
    result = extract_music(q)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát")
    
    return RedirectResponse(url=result["url"], status_code=302)

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
