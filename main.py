from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
import yt_dlp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xiaozhi-music-api")

app = FastAPI(
    title="Xiaozhi Music API",
    description="API tìm kiếm và bóc tách stream âm thanh YouTube cho ESP32 Xiaozhi Robot",
    version="1.0.0"
)

# Cấu hình yt-dlp tối ưu cho bóc tách audio nhanh
YDL_OPTS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "skip_download": True,
}

def extract_youtube_audio(query: str):
    """Tìm kiếm YouTube và trích xuất direct stream audio URL"""
    search_query = f"ytsearch1:{query}"
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if not info or "entries" not in info or len(info["entries"]) == 0:
                return None
            
            video = info["entries"][0]
            audio_url = video.get("url")
            
            # Nếu format chưa có direct url, tìm trong formats
            if not audio_url and "formats" in video:
                for fmt in reversed(video["formats"]):
                    if fmt.get("acodec") != "none" and fmt.get("url"):
                        audio_url = fmt["url"]
                        break
            
            return {
                "id": video.get("id"),
                "title": video.get("title"),
                "duration": video.get("duration"),
                "uploader": video.get("uploader"),
                "url": audio_url
            }
    except Exception as e:
        logger.error(f"Error extracting audio for '{query}': {e}")
        return None

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Xiaozhi Music API",
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
    
    # 302 redirect trực tiếp đến luồng audio googlevideo
    return RedirectResponse(url=result["url"], status_code=302)

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
