from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
import yt_dlp

app = FastAPI(title="Xiaozhi Music API")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Xiaozhi Music API is running"}

@app.get("/get_music")
def get_music(q: str):
    if not q:
        raise HTTPException(status_code=400, detail="Thieu ten bai hat")

    ydl_opts = {
        'format': 'ba/b',
        'default_search': 'ytsearch1:',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{q}", download=False)
            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            return {
                "status": "success",
                "title": info.get("title"),
                "duration": info.get("duration"),
                "url": info.get("url")
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/play")
def play(q: str):
    if not q:
        raise HTTPException(status_code=400, detail="Thieu ten bai hat")

    ydl_opts = {
        'format': 'ba/b',
        'default_search': 'ytsearch1:',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{q}", download=False)
            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            audio_url = info.get("url")
            if not audio_url:
                raise HTTPException(status_code=404, detail="Audio not found")
            return RedirectResponse(url=audio_url, status_code=302)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))