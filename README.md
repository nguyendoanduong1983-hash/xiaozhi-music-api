# Xiaozhi Music API 🎵

API tìm kiếm và bóc tách luồng âm thanh trực tiếp (Direct Audio Stream) từ YouTube dành cho Robot / Loa thông minh **ESP32-S3 (Xiaozhi / D-Bot)**.

## 🚀 Cách thức hoạt động

### 1. Gọi lấy dữ liệu JSON
```http
GET /play?q=tên_bài_hát
```
**Trả về:**
```json
{
  "status": "success",
  "data": {
    "title": "999 Đóa Hồng",
    "duration": 302,
    "url": "https://rr2---sn-..."
  }
}
```

### 2. Gọi phát trực tiếp (Tối ưu cho ESP32-audioI2S)
```http
GET /redirect?q=tên_bài_hát
```
* Endpoint này tự động **Redirect (HTTP 302)** thẳng tới luồng audio của YouTube.
* ESP32 chỉ cần gọi:
```cpp
audio.connecttohost("https://your-service.onrender.com/redirect?q=999+doa+hong");
```

## 🛠️ Triển khai (Deploy)
* Tự động triển khai trên [Render.com](https://render.com) miễn phí (Free Tier).
