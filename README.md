# Hệ Thống AI Giải Đề & Chấm Đối Soát Đề Thi Tin Học THPT (2025 – 2026)

Hệ thống ứng dụng **Mô hình ngôn ngữ lớn đa phương thức (Google Gemini 3.8 Flash & Gemini 3.1 Pro)** kết hợp thư viện xử lý tài liệu **pdfplumber** và cơ sở dữ liệu đám mây **MongoDB Atlas** nhằm tự động hóa quy trình tiếp nhận đề thi PDF, điều phối suy luận 2 pha, đối soát đáp án chuẩn và đánh giá hàng loạt (*Batch Processing*) cho đề thi môn Tin học tốt nghiệp THPT theo Chương trình GDPT 2018.

---

## Tính Năng Chính

- **Kiến trúc phân tầng (Modular 3-Tier):** Mã nguồn được phân tách rõ ràng thành tầng giao diện (`views/`), tầng xử lý nghiệp vụ & điều phối suy luận (`core/`) và tầng lưu trữ dữ liệu (`MongoDB Atlas`).
- **Chiến lược điều phối suy luận 2 Pha & Tự phục hồi có mục tiêu:** Phân tách quá trình giải 24 câu trắc nghiệm nhiều lựa chọn (Phần I) và 6 câu trắc nghiệm Đúng/Sai – 24 ý khẳng định (Phần II), kết hợp cơ chế cưỡng chế lược đồ JSON (`TypedDict Schema`) và truy vấn bù tự động (*Targeted Recovery*).
- **Trí tuệ nhân tạo có thể giải thích (Explainable AI – XAI):** Bắt buộc mô hình trích xuất căn cứ giải thích ngắn gọn đi kèm từng câu hỏi và từng ý khẳng định để phục vụ kiểm chứng học thuật.
- **Đường ống tiền xử lý PDF đa phương thức:** Tự động trích xuất văn bản số bảo toàn tọa độ thụt lề mã nguồn (`pdfplumber`) hoặc kích hoạt kênh thị giác máy tính (*AI Vision*) đối với đề thi dạng ảnh quét; tự động nhận diện `Mã đề` và `Năm thi` bằng biểu thức chính quy (*Regex*).
- **Quản trị Ngân hàng Đáp án chuẩn (*Ground Truth*):** Lưu trữ, rà soát và khóa xác thực ma trận đáp án chuẩn trên MongoDB Atlas chống ghi đè ngoài ý muốn.
- **Đối soát đa thang điểm & Xuất báo cáo Excel (`.xlsx`):** Tự động tính điểm theo cả thang quy chuẩn hệ thống và thang điểm lũy tiến quy chế Bộ GD&ĐT, thống kê thời gian phản hồi, lượng token tiêu thụ, chi phí vận hành và kết xuất báo cáo đa trang tính.

---

## Cấu Trúc Thư Mục Dự Án

```text
chatbotAI/
├── app.py                      # Điểm khởi chạy ứng dụng (Streamlit Entry Point)
├── core/                       # Tầng xử lý nghiệp vụ lõi (Business Logic & Backend)
│   ├── __init__.py
│   ├── ai_grader.py            # Lược đồ TypedDict, System Prompt & điều phối Gemini API 2 pha
│   ├── database.py             # Kết nối MongoDB Atlas & quản lý 4 bộ sưu tập dữ liệu
│   ├── excel_utils.py          # Bóc tách đáp án Excel/CSV & xuất báo cáo đối soát (.xlsx)
│   ├── grading_logic.py        # Chuẩn hóa dữ liệu phản hồi P1/P2, đối soát & tính điểm
│   ├── mock_data.py            # Dữ liệu mẫu phục vụ kiểm thử luồng giao diện (Dry-Run)
│   └── pdf_utils.py            # Trích xuất văn bản PDF và nhận diện Mã đề / Năm thi
├── views/                      # Tầng giao diện người dùng (Streamlit Views)
│   ├── __init__.py
│   ├── tab_grading.py          # Tab 1: Chấm thi tự động hàng loạt & đối soát chi tiết XAI
│   ├── tab_history.py          # Tab 2: Lịch sử đợt chấm thực nghiệm & thống kê Token/Chi phí
│   └── tab_keys.py             # Tab 3: Quản trị ngân hàng ma trận đáp án chuẩn Bộ GD&ĐT
├── requirements.txt            # Danh sách thư viện Python phụ thuộc
├── .env.example                # Tệp mẫu cấu hình biến môi trường
├── run_app.bat                 # Kịch bản khởi chạy nhanh ứng dụng trên Windows
└── README.md                   # Tài liệu hướng dẫn cài đặt và vận hành hệ thống
```

---

## Yêu Cầu Môi Trường

- **Python:** Phiên bản `>= 3.10`
- **Google Gemini API Key:** Cấp từ [Google AI Studio](https://aistudio.google.com/)
- **MongoDB Atlas:** Chuỗi kết nối cơ sở dữ liệu `MONGODB_URI`

---

## Hướng Dẫn Cài Đặt & Chạy Ứng Dụng

### Bước 1: Khởi tạo môi trường ảo & cài đặt thư viện

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Bước 2: Thiết lập biến môi trường (`.env`)

Tạo tệp `.env` tại thư mục gốc của dự án (dựa theo tệp `.env.example`):

```env
GEMINI_API_KEY=your_gemini_api_key_here
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
```

### Bước 3: Khởi chạy ứng dụng Streamlit

**Cách 1 (Khởi chạy nhanh trên Windows):**

- Chạy tệp `run_app.bat` (hoặc gõ `.\run` trong cửa sổ Terminal).

**Cách 2 (Sử dụng lệnh chuẩn):**

```powershell
streamlit run app.py
```

hoặc:

```powershell
python -m streamlit run app.py
```

Ứng dụng sẽ khởi chạy tại địa chỉ: `http://localhost:8501`.
