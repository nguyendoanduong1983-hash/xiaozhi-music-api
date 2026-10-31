from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
import yt_dlp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xiaozhi-music-api")

app = FastAPI(
    title="Xiaozhi Music API",
    description="API tìm kiếm và bóc tách luồng HTTP Progressive Stream (MP3/AAC) cho ESP32",
    version="2.0.0"
)

# Cấu hình yt-dlp: Yêu cầu lấy luồng HTTP/HTTPS trực tiếp, bài trừ hoàn toàn HLS (m3u8)
YDL_OPTS_YT = {
    # Ưu tiên audio http/https trực tiếp, loại bỏ protocol chứa m3u8
    "format": "bestaudio[protocol^=http][protocol!*=m3u8]/best[protocol^=http][protocol!*=m3u8]",
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
    # Với SoundCloud: ép lấy http_mp3_128, loại bỏ hoàn toàn hls_opus / hls_aac / m3u8
    "format": "http_mp3/bestaudio[protocol^=http][protocol!*=m3u8]/best[protocol^=http][protocol!*=m3u8]",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}

def find_best_progressive_audio(formats: list) -> dict:
    """
    Duyệt danh sách 'formats' để lọc ra URL HTTP Progressive Stream đơn lẻ:
    1. Loại bỏ 100% các định dạng playlist HLS (m3u8, m3u8_native), DASH (mpd).
    2. Ưu tiên tuyệt đối: MP3 > AAC/M4A > WebM/Opus.
    3. Ưu tiên bitrate nhẹ (64kbps - 160kbps) tối ưu cho ESP32 không bị tràn RAM.
    """
    if not formats:
        return None

    candidates = []
    for f in formats:
        url = f.get("url", "")
        proto = (f.get("protocol") or "").lower()
        ext = (f.get("ext") or "").lower()
        fmt_id = (f.get("format_id") or "").lower()
        abr = f.get("abr") or f.get("tbr") or 128
        acodec = (f.get("acodec") or "").lower()
        vcodec = (f.get("vcodec") or "none").lower()

        # Bỏ qua nếu không có URL hoặc không phải HTTP/HTTPS
        if not url or not url.startswith("http"):
            continue

        # LOẠI BỎ TRIỆT ĐỂ: m3u8, hls, dash manifest
        if any(h in proto for h in ["m3u8", "hls", "dash", "f4m", "rtmp"]):
            continue
        if ".m3u8" in url or "playlist" in url or ".mpd" in url:
            continue

        # Bỏ qua format không có audio
        if acodec == "none":
            continue

        # Chấm điểm ưu tiên định dạng
        score = 0

        # Ưu tiên số 1: MP3 nguyên bản (ESP32 giải mã mượt mà nhất)
        if ext == "mp3" or "mp3" in fmt_id or "mp3" in acodec:
            score += 100
        # Ưu tiên số 2: M4A / AAC
        elif ext in ["m4a", "aac"] or "aac" in acodec or "mp4a" in acodec:
            score += 80
        # Ưu tiên số 3: WebM / Opus
        elif ext in ["webm", "ogg"] or "opus" in acodec:
            score += 40
        else:
            score += 20

        # Ưu tiên luồng thuần Audio (không kèm video để tiết kiệm băng thông)
        if vcodec == "none":
            score += 30

        # Ưu tiên bitrate nhẹ 64kbps - 160kbps (rất vừa vặn cho RAM ESP32)
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

    # Sắp xếp candidate điểm cao nhất lên đầu
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best_fmt = candidates[0][2]
    return best_fmt

def extract_music(query: str):
    """
    Tìm kiếm và bóc tách luồng Progressive Stream (MP3/AAC):
    Thử YouTube (client iOS/TV), nếu không có progressive stream thì fallback sang SoundCloud.
    """
    # 1. Thử YouTube
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_YT) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                v = info["entries"][0]
                formats = v.get("formats", [])
                
                # Lọc format progressive
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
                        "url": best_fmt.get("url")
                    }
    except Exception as e:
        logger.warning(f"YouTube extract failed: {e}")

    # 2. Fallback sang SoundCloud (Nổi tiếng với luồng http_mp3_128 progressive chuẩn)
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_SC) as ydl:
            info = ydl.extract_info(f"scsearch1:{query}", download=False)
            if info and "entries" in info and len(info["entries"]) > 0:
                v = info["entries"][0]
                formats = v.get("formats", [])
                
                # Lọc format progressive (đặc biệt là http_mp3_128)
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
                        "url": best_fmt.get("url")
                    }
    except Exception as e:
        logger.error(f"SoundCloud extract failed: {e}")

    return None

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Xiaozhi Music API",
        "version": "2.0.0",
        "stream_type": "HTTP Progressive Stream (No HLS / No m3u8)",
        "endpoints": {
            "play_json": "/play?q=tên_bài_hát",
            "play_stream_redirect": "/redirect?q=tên_bài_hát"
        }
    }

@app.get("/play")
def play_json(q: str = Query(..., description="Tên bài hát cần tìm")):
    """Trả về thông tin bài hát và direct progressive stream URL dưới dạng JSON"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên bài hát")
    
    result = extract_music(q)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát có luồng HTTP liên tục phù hợp")
    
    return {
        "status": "success",
        "data": result
    }

@app.get("/redirect")
def play_redirect(q: str = Query(..., description="Tên bài hát cần tìm")):
    """Redirect thẳng 302 sang stream MP3/AAC liên tục - Dành cho ESP32 connecttohost"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên bài hát")
    
    result = extract_music(q)
    if not result or not result.get("url"):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài hát có luồng HTTP liên tục phù hợp")
    
    # 302 redirect thẳng sang direct progressive stream
    return RedirectResponse(url=result["url"], status_code=302)

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)

@app.get('/inspect')
def inspect_formats(q: str):
    results = {}
    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
        try:
            info = ydl.extract_info(f'scsearch1:{q}', download=False)
            if info and 'entries' in info and len(info['entries']) > 0:
                fmts = info['entries'][0].get('formats', [])
                results['soundcloud'] = [
                    {'id': f.get('format_id'), 'proto': f.get('protocol'), 'ext': f.get('ext'), 'abr': f.get('abr'), 'url': f.get('url')[:60]}
                    for f in fmts
                ]
        except Exception as e:
            results['soundcloud_err'] = str(e)
    return results

@app.get('/test_yt')
def test_yt_clients(q: str):
    res = {}
    clients = ['mweb', 'android_music', 'web_creator', 'tv_embedded']
    for c in clients:
        opts = {
            'quiet': True,
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': [c]}}
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f'ytsearch1:{q}', download=False)
                if info and 'entries' in info and len(info['entries']) > 0:
                    v = info['entries'][0]
                    res[c] = {
                        'title': v.get('title'),
                        'formats': len(v.get('formats', [])),
                        'progressive': [
                            {'id': f.get('format_id'), 'ext': f.get('ext'), 'proto': f.get('protocol'), 'abr': f.get('abr'), 'url': f.get('url')[:60]}
                            for f in v.get('formats', [])
                            if f.get('protocol') in ['http', 'https'] and 'm3u8' not in (f.get('protocol') or '') and '.m3u8' not in (f.get('url') or '')
                        ]
                    }
        except Exception as e:
            res[c] = {'error': str(e)}
    return res
