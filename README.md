# PPE Monitor — Hệ thống nhận diện và cảnh báo vi phạm PPE công trường

Giám sát camera công trường theo thời gian thực, phát hiện người lao động không
đeo đủ trang thiết bị bảo hộ (PPE), lưu bằng chứng và phát cảnh báo đa kênh.

**Model:** YOLOv8s huấn luyện trên **Ultralytics Construction-PPE** (11/2026, CC BY 4.0,
1.000 ảnh · 11.902 hộp · mAP50 **0.811**) — 12 lớp:

`helmet`, `gloves`, `vest`, `boots`, `goggles`, `Person`, `no_helmet`,
`no_goggle`, `no_gloves`, `no_boots`, `forklift`, `no_vest`

Phủ **5 bộ phận** PPE, gồm lớp âm tính cho cả mũ, áo, găng, giày, kính.
Dây đai an toàn, đồng phục, quần phản quang, mặt nạ hàn, mặt nạ phòng độc,
khẩu trang, chụp tai chưa có lớp — hệ thống bỏ qua yêu cầu đó thay vì báo sai.
Xem [Bộ phận nhận diện được](#bộ-phận-nhận-diện-được--và-bộ-phận-chưa) và
`GET /api/coverage`.

Trọng số không nằm trong repo (111 MB). Tải một lần:

```bash
.venv\Scripts\python.exe scripts\download_model.py
```

---

## Chạy thử trong 30 giây

```bash
python install.bat        # hoặc: start.bat
```

Hoặc thủ công:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
uv pip install --python .venv\Scripts\python.exe --reinstall \
   --index-url https://download.pytorch.org/whl/cu126 torch torchvision
.venv\Scripts\python.exe run.py --demo
```

Mở trình duyệt: **http://127.0.0.1:8000**

`--demo` dựng một camera giả lập lái ngang ảnh công trường mẫu để kiểm chứng
toàn bộ pipeline khi chưa có camera thật.

---

## Kiểm tra hệ thống

```bash
.venv\Scripts\python.exe scripts\selftest.py
```

Kiểm Python, gói phụ thuộc, CUDA, trọng số model, tốc độ suy luận.

---

## Thêm camera

### Qua dashboard
Bấm **+ Camera**, nhập mã / tên / nguồn / khu vực.

### Qua config.yaml
```yaml
cameras:
  - id: cam-cong
    name: Cổng công trường
    source: "rtsp://user:pass@192.168.1.50:554/Streaming/Channels/101"
    zone: gate
    enabled: true
```

### Qua dòng lệnh
```bash
python run.py --camera cam1=0 --camera cam2="rtsp://..."
```

### Định dạng nguồn

| Nguồn | Chuỗi |
|---|---|
| Webcam | `0`, `1` |
| RTSP camera IP | `rtsp://user:pass@ip:554/...` |
| HTTP MJPEG | `http://ip:8080/video` |
| Tệp video | `file:assets/video.mp4` |
| Demo | `demo:assets/demo_site.jpg` |

Camera Hikvision: `rtsp://user:pass@ip:554/Streaming/Channels/101`
Camera Dahua: `rtsp://user:pass@ip:554/cam/realmonitor?channel=1&subtype=0`

---

## Khu vực và mức yêu cầu PPE

Khai báo trong `config.yaml` mục `rules.zones`:

```yaml
rules:
  zones:
    gate:
      name: Cổng vào
      required: [helmet, vest]
    high_risk:
      name: Khu nguy hiểm
      required: [helmet, vest, gloves, boots, goggles]
    welding:
      name: Khu hàn cắt
      required: [helmet, vest, gloves, mask, goggles]
```

Yêu cầu nào model không nhận diện được sẽ tự động bỏ qua (ví dụ `harness`).

Camera có thể giới hạn trong một vùng đa giác:

```json
"polygon": [[120, 340], [860, 320], [1180, 700], [60, 720]]
```

---

## Cảnh báo

```yaml
alerts:
  telegram:
    enabled: true
    token: "123456:ABC..."
    chat_id: "-1001234567890"
  webhook:
    enabled: true
    url: "https://your-system/api/ppe-alert"
  mqtt:
    enabled: true
    host: 192.168.1.10
    topic: ppe/alerts
  email:
    enabled: true
    host: smtp.gmail.com
    port: 587
    tls: true
    user: "you@gmail.com"
    password: "app-password"
    from: "you@gmail.com"
    to: ["safety@company.vn"]
```

Mỗi cảnh báo gửi kèm ảnh đã vẽ overlay, thời gian, khu vực, danh sách thiếu.
Webhook nhận JSON:

```json
{
  "id": 42, "cam_id": "cam-cong", "cam_name": "Cổng công trường",
  "track_id": 7, "missing": ["helmet"], "zone": "gate",
  "ts": 1730000000.0, "confidence": 0.71,
  "image_url": "/evidence/cam-cong/20261119/...jpg",
  "text": "⚠️ VI PHẠM PPE\n..."
}
```

### Cảnh báo tại chỗ — loa IP

Ngoài Telegram/webhook/MQTT/email, hệ thống nói trực tiếp qua loa công trường:

```yaml
sounder:
  enabled: true
  mode: http_get                 # http_get | http_post | local_tts | mqtt
  url: "http://192.168.1.60/cgi-bin/audio?action=play"
  method: GET
  payload_key: text
  cooldown_sec: 25
```

Câu phát ra: *"Chú ý. Có người không đeo Mũ bảo hộ, Áo phản quang tại Cổng công
trường. Đề nghị bổ sung ngay."*

| `mode` | Dùng cho |
|---|---|
| `http_get` | loa IP Dahua, Hikvision ISAPI, thiết bị nhận `?text=` |
| `http_post` | loa nhận JSON `{"text": "..."}` |
| `local_tts` | loa gắn vào máy chủ, đọc bằng SAPI Windows (không cần thư viện) |
| `mqtt` | loa trong hệ thống nhà thông minh qua MQTT |

Có `cooldown_sec` riêng để loa không đọc lại liên tục trên cùng một camera.

---

## Báo cáo

Ba định dạng, xuất trực tiếp từ dashboard hoặc gọi API:

| Định dạng | Nội dung |
|---|---|
| CSV | Toàn bộ vi phạm trong kỳ, BOM UTF-8 để Excel đọc đúng tiếng Việt |
| Excel (`.xlsx`) | 4 sheet: Tổng hợp KPI, Chi tiết vi phạm, Theo camera, Theo giờ |
| HTML | Báo cáo một trang, in bằng Ctrl+P — dùng để trình Ban an toàn |

```bash
curl -o baocao.xlsx "http://127.0.0.1:8000/api/reports/summary.xlsx?days=30"
```

---

## API

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/api/health` | Trạng thái hệ thống, model, bộ đếm cảnh báo |
| GET | `/api/cameras` | Danh sách camera + trạng thái trực tiếp |
| POST | `/api/cameras` | Thêm camera |
| PATCH | `/api/cameras/{id}` | Sửa camera |
| DELETE | `/api/cameras/{id}` | Xóa camera |
| GET | `/api/violations` | Danh sách vi phạm (`limit`, `cam`, `hours`, `unack`) |
| POST | `/api/violations/{id}/ack` | Đánh dấu đã xử lý |
| GET | `/api/stats` | Thống kê theo thiết bị / khu vực / camera / giờ |
| GET | `/api/events` | Nhật ký hệ thống |
| GET | `/api/coverage` | **Bộ phận nào model nhận diện được, bộ phận nào bị bỏ qua** |
| GET | `/api/retention` | Dung lượng lưu trữ, số bản ghi, hạn giữ dữ liệu |
| POST | `/api/retention/run` | Chạy dọn dẹp ngay |
| GET | `/api/reports/violations.csv` | Xuất CSV (mở được bằng Excel, có BOM UTF-8) |
| GET | `/api/reports/summary.xlsx` | Excel 4 sheet: tổng hợp, vi phạm, theo camera, theo giờ |
| GET | `/api/reports/report.html` | Báo cáo một trang, in được bằng Ctrl+P |
| POST | `/api/auth/login` | Đăng nhập, trả cookie phiên |
| POST | `/api/auth/logout` | Đăng xuất |
| GET | `/api/auth/me` | User + vai trò hiện tại |
| PUT | `/api/cameras/{id}/polygon` | Gán vùng đa giác cho camera |
| GET | `/api/snapshot/{cam}` | Ảnh JPEG hiện tại |
| GET | `/api/stream/{cam}` | Luồng MJPEG trực tiếp |
| GET | `/api/events/stream` | SSE sự kiện thời gian thực |
| GET | `/api/docs` | Swagger UI |

---

## Bộ phận nhận diện được — và bộ phận chưa

Đây là câu hỏi quan trọng nhất khi vận hành: **model biết những bộ phận nào?**

Model `ppe26.pt` có 12 lớp, phủ **5 bộ phận** PPE:

| Bộ phận | Lớp dương | Lớp âm | Dùng được |
|---|---|---|---|
| Mũ bảo hộ | `helmet` | `no_helmet` | ✅ |
| Áo phản quang | `vest` | `no_vest` | ✅ |
| Găng tay | `gloves` | `no_gloves` | ✅ |
| Giày bảo hộ | `boots` | `no_boots` | ✅ |
| Kính bảo hộ | `goggles` | `no_goggle` | ✅ |

Thiết bị công trường đi kèm: `forklift` → `equipment:forklift` (không phải PPE
cá nhân, không tham gia đánh giá vi phạm).

**Chưa có lớp trong model** (hệ thống tự bỏ qua yêu cầu, không báo sai):

| Bộ phận | Trạng thái |
|---|---|
| Khẩu trang | ❌ chưa có lớp |
| Chụp tai | ❌ chưa có lớp |
| Dây đai an toàn | ❌ chưa có lớp |
| Đồng phục bảo hộ dài tay | ❌ chưa có lớp |
| Quần phản quang | ❌ chưa có lớp |
| Mặt nạ hàn | ❌ chưa có lớp |
| Mặt nạ phòng độc | ❌ chưa có lớp |

Nếu `config.yaml` khai báo `required: [helmet, harness, vest]` cho khu vực làm
việc trên cao, hệ thống chỉ kiểm `helmet` và `vest`. `harness` bị bỏ qua **im lặng**
— đây là thiết kế có chủ đích: báo "thiếu dây đai" khi model không nhìn thấy dây
đai sẽ tạo ra hàng trăm cảnh báo giả mỗi ngày, và người vận hành sẽ tắt hệ thống.

Xem trực tiếp trên dashboard, khối **Bộ phận nhận diện được**, hoặc:

```bash
curl http://127.0.0.1:8000/api/coverage
```

### Vì sao bỏ model 19 lớp cũ

Model `construction-ppe-yolov8` (19 lớp) phủ 7 bộ phận nhưng **không có lớp âm
tính cho áo phản quang ở dữ liệu thật**: trên video công trường thực tế, `no_vest`
chỉ bắn ra 1 lần trong 40 khung, trong khi model mới bắn 38 lần cho cùng cảnh.
Nó cũng mang 4 lớp thiết bị công trường không dùng tới (`Circular_Saw`,
`Fire_Extinguisher`, `Fire_prevention_Net`, `Welding_Equipment`) và chiếm 21.5 MB
thay vì 12 lớp gọn cho đúng bài toán.

Model cũ vẫn dùng được: `python scripts/download_model.py --name old`.

Muốn giám sát đủ 12 bộ phận: gán nhãn dataset và huấn luyện lại — xem mục
[Huấn luyện lại](#huấn-luyện-lại-model-cho-công-trường-của-bạn).

---

## Kiến trúc

```
Camera RTSP/Webcam
      │
      ▼
 OpenCVSource ──► PPEDetector (YOLOv8, GPU)
      │                    │
      │                    ▼
      │            associator.py  (ghép PPE ↔ người theo vùng cơ thể)
      │                    │
      │                    ▼
      │            PersonTracker (IoU + dự đoán tuyến tính)
      │                    │
      │                    ▼
      │            RuleEngine (EMA theo track, xác nhận N khung, cooldown)
      │                    │
      ▼                    ▼
 MJPEG stream      AlertManager ──► Telegram / Webhook / MQTT / Email
                   EvidenceStore ──► ảnh + clip + JSON
                        │
                        ▼
                   SQLite ──► FastAPI ──► Dashboard
```

### Chống báo giả

1. **Ngưỡng kép** — lớp dương tính (`Hard_hat`) và âm tính (`No-Helmet`)
   phải đồng thuận; chỉ cảnh báo khi lớp âm tính vượt trội.
2. **EMA theo track** — làm mượt qua thời gian, không phản ứng với 1 khung nhiễu.
3. **Xác nhận N khung** — mặc định 12 khung liên tiếp (~1 giây) mới tính vi phạm.
4. **Cooldown** — 180 giây cho mỗi cặp (camera, đối tượng, bộ thiếu).
5. **Loại nhiễu biên** — bbox PPE phải có tâm trong bbox người và đúng vùng cơ thể.

Tinh chỉnh: `rules.confirm_frames` (tăng → ít báo giả hơn, phản hồi chậm hơn),
`model.conf_ppe` (tăng → chặt hơn).

---

## Chạy production

```bash
# Windows service qua NSSM
nssm install PPEMonitor "C:\ppe\.venv\Scripts\python.exe" "C:\ppe\run.py" "--host 0.0.0.0 --port 8000"

# Hoặc Task Scheduler: chạy start.bat khi khởi động
```

Truy cập từ máy khác trong LAN: đặt `app.host: 0.0.0.0`.

Hiệu năng tham chiếu (RTX 3060, 640px, YOLOv8s):

| Cấu hình | FPS/GPU | Camera đồng thời |
|---|---|---|
| `imgsz: 640`, `infer_stride: 2` | ~20 | 10–12 |
| `imgsz: 480`, `infer_stride: 3` | ~35 | 20+ |
| `imgsz: 640`, `infer_stride: 1` | ~20 | 6–8 |

---

## Huấn luyện lại model cho công trường của bạn

### Cách 1 — dùng dataset Ultralytics Construction-PPE có sẵn

Dataset công khai 1.000 ảnh, 12 lớp, CC BY 4.0. Script tự tải, giải nén và ghi
`data.yaml` với đường dẫn tuyệt đối:

```bash
# Tải + giải nén dataset (~618 MB, chỉ lần đầu). Tự bỏ qua nếu đã có.
.venv\Scripts\python.exe scripts\fetch_dataset.py

# Huấn luyện trên RTX 3060: ~35 phút cho 120 epoch
.venv\Scripts\python.exe scripts\train_ppe.py ^
   --data dataset-public/construction-ppe/data.yaml ^
   --model yolov8s.pt --epochs 120 --imgsz 640 --batch 16 ^
   --name ppe26 --copy-to weights/ppe26.pt
```

Kết quả tham chiếu (RTX 3060, 120 epoch): **mAP50 0.811 · mAP50-95 0.555**,
epoch tốt nhất là 94. Script in bảng mAP50 từng lớp và cảnh báo nếu lớp nào
dưới 0.60.

Huấn luyện lại trên chính ảnh camera của bạn: chuẩn bị dataset bằng cách 2,
nhưng xuất theo bộ lớp `ultralytics` để giữ tương thích với trọng số đang chạy:

```bash
.venv\Scripts\python.exe scripts\prepare_dataset.py --root dataset --classes ultralytics
```

Huấn luyện lại trên chính ảnh camera của bạn: chuẩn bị dataset bằng cách 2,
nhưng xuất theo bộ lớp `ultralytics` để giữ tương thích với trọng số đang chạy:

```bash
.venv\Scripts\python.exe scripts\prepare_dataset.py --root dataset --classes ultralytics
```

### Cách 2 — bộ lớp đầy đủ 12 bộ phận PPE

```bash
# 1. Tạo cấu trúc dataset + hướng dẫn gán nhãn
.venv\Scripts\python.exe scripts\prepare_dataset.py --root dataset --classes full

# 2. Gán nhãn bằng Label Studio / Roboflow, export định dạng YOLO
#    dataset/images/{train,val}/  dataset/labels/{train,val}/
# 3. Huấn luyện (tự đánh giá + tự chép trọng số khi xong)
.venv\Scripts\python.exe scripts\train_ppe.py --data dataset\data.yaml --epochs 100

# 4. Khởi động lại server để nạp model mới
```

`--classes full` sinh 28 lớp gồm cả lớp âm tính (`No-Harness`, `No-Safety_Suit`,
`No-Respirator`, `No-Welding_Mask`, `No-Hi_Vis_Pants`) và kèm `dataset/README.md`
hướng dẫn cách vẽ hộp cho từng bộ phận. `--classes base` sinh 15 lớp gọn hơn.

Mục tiêu: mAP50 > 0.80 cho `Worker`, `Hard_hat`, `Vest`; > 0.70 cho các lớp còn lại.

### So sánh model trước khi đổi

```bash
.venv\Scripts\python.exe scripts\compare_models.py
```

Chạy cả hai model trên cùng khung hình video thật, in số người phát hiện, số
box theo từng lớp và thời gian suy luận mỗi khung. Dùng khi không chắc model
mới có tốt hơn trên cảnh của mình không.

---

## Cấu trúc thư mục

```
ppe/
├── app/
│   ├── classes.py      ánh xạ lớp model → tên chuẩn nội bộ
│   ├── config.py       đọc config.yaml
│   ├── db.py           SQLite (violations, cameras, events, status)
│   ├── detector.py     wrapper YOLO, thread-safe
│   ├── associator.py   ghép PPE với người theo vùng cơ thể
│   ├── tracker.py      tracker IoU + dự đoán tuyến tính
│   ├── rules.py        rule engine, EMA, xác nhận, cooldown
│   ├── evidence.py     lưu ảnh + clip + JSON
│   ├── alerting.py     Telegram / webhook / MQTT / email
│   ├── sounder.py      loa IP (HTTP GET/POST), MQTT, TTS Windows
│   ├── reports.py      CSV, Excel 4 sheet, báo cáo HTML in được
│   ├── coverage.py     bộ phận nào model nhận diện được
│   ├── auth.py         đăng nhập, 3 vai trò viewer/operator/admin
│   ├── retention.py    dọn dẹp dữ liệu cũ, giới hạn dung lượng
│   ├── pipeline.py     vòng lặp camera, overlay, nguồn hình
│   ├── api.py          FastAPI, SSE, MJPEG, báo cáo
│   └── main.py         điểm vào, CLI
├── static/index.html   dashboard
├── scripts/            selftest, download_model, cleanup, compare_models,
│                       prepare_dataset, train_ppe, install_service.ps1
├── weights/            trọng số YOLO
├── assets/             ảnh/video mẫu
├── evidence/           bằng chứng vi phạm
├── data/               ppe.db, ppe.log
├── config.yaml
├── run.py
├── start.bat
├── install.bat
├── install_service.bat
└── requirements.txt
```

---

## Chạy như dịch vụ Windows

Tự chạy khi khởi động máy, không cần mở terminal:

```bash
install_service.bat          # chuột phải → Run as administrator
```

Tạo Scheduled Task chạy bằng `SYSTEM` lúc boot (nếu không đủ quyền thì chạy lúc
đăng nhập). Lệnh quản lý:

```bash
schtasks /Run  /TN "PPE Monitor"     # chạy
schtasks /End  /TN "PPE Monitor"     # dừng
install_service.bat -Uninstall       # gỡ
```

---

## Bảo mật khi mở ra LAN

Mặc định server chỉ nghe `127.0.0.1`. Mở ra LAN bằng `--host 0.0.0.0` thì **bật
xác thực trước**:

```yaml
auth:
  enabled: true
  allow_localhost: true        # máy chủ không cần đăng nhập
  users:
    admin: "mat-khau-manh-o-day"
    viewer: "chi-xem-thoi"
```

Ba vai trò:

| Vai trò | Quyền |
|---|---|
| `viewer` | chỉ đọc: xem camera, vi phạm, thống kê, báo cáo |
| `operator` | thêm: đánh dấu đã xử lý, chạy dọn dẹp |
| `admin` | thêm: thêm/sửa/xóa camera, đổi cấu hình, đổi mật khẩu |

Mật khẩu lưu dạng băm PBKDF2-SHA256 (240.000 vòng), không lưu thô. Phiên bằng
cookie `httpOnly`, hết hạn sau `session_hours`. Script tích hợp dùng header:

```bash
curl -H "X-API-Key: admin:mat-khau" http://127.0.0.1:8000/api/violations
```

Khi mở ra Internet: đặt sau nginx/Caddy có TLS, đừng mở trực tiếp cổng 8000.

---

## Xử lý sự cố

| Hiện tượng | Nguyên nhân | Xử lý |
|---|---|---|
| `Khong nap duoc model` | thiếu weights | `python scripts/download_model.py` |
| FPS thấp (< 5) | chạy CPU | cài torch CUDA: `--index-url https://download.pytorch.org/whl/cu126` |
| Camera đen / mất kết nối | sai URL RTSP | thử bằng VLC trước; kiểm user/pass |
| Nhiều báo giả | ngưỡng thấp | tăng `confirm_frames` lên 20, `conf_ppe` lên 0.35 |
| Không cảnh báo | thiếu lớp | kiểm `items` trong `/api/health` — model phải có lớp âm tính |
| Không báo thiếu dây đai / mặt nạ hàn | model không có lớp | xem `/api/coverage`; gán nhãn + train lại |
| Dashboard trắng | thiếu static | đảm bảo chạy từ thư mục gốc dự án |
| Box nháy liên tục | bỏ khung nhận diện | đã sửa: overlay vẽ lại mọi khung, track giữ qua 2 khung trượt |
| Ổ đĩa đầy | clip 6 s × nhiều vi phạm | giảm `retention.evidence_days`, đặt `retention.max_gb` |
| `401 Chua dang nhap` | bật auth, chưa login | đăng nhập ở dashboard, hoặc `X-API-Key` |

---

## An toàn dữ liệu

- Ảnh vi phạm lưu cục bộ tại `evidence/`, không gửi đi đâu nếu không bật kênh cảnh báo.
- Tự dọn dẹp: `retention` chạy mỗi 30 phút, xóa bản ghi và tệp quá hạn, giới hạn
  tổng dung lượng. Theo dõi ở `/api/retention` hoặc khối **Lưu trữ & báo cáo**.
- Bản ghi đã xử lý giữ lâu hơn (`ack_days: 365`) để làm bằng chứng pháp lý.
- Đặt sau reverse proxy có TLS khi mở ra ngoài; bật `auth.enabled: true`.
