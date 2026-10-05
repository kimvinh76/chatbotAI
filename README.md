# 🤖 Hệ Thống AI Chấm Thi & Đánh Giá Đề Thi Tin Học THPT (Chuẩn Bộ GD&ĐT 2025)

Hệ thống ứng dụng **Generative AI (Google Gemini 3.5 Flash)** kết hợp thư viện xử lý tài liệu **pdfplumber** nhằm tự động hóa quy trình bóc tách đề thi, giải đề độc lập, đối sánh đáp án chuẩn và chấm điểm hàng loạt (Batch Processing) cho các đề thi môn Tin học theo cấu trúc mới nhất của Bộ Giáo dục và Đào tạo năm 2025.

---

## 🌟 Tính Năng Nổi Bật

- **Xử lý hàng loạt (Batch Processing):** Hỗ trợ kéo thả và chấm đồng thời từ 30 – 50 file PDF đề thi chỉ trong 1 lần chạy.
- **Bóc tách đề thi chính xác:** Trích xuất văn bản đề thi từ PDF nguyên bản, giữ nguyên định dạng đoạn mã và câu hỏi.
- **Giải đề bằng AI với JSON Schema (Structured Output):**
  - **Phần 1:** Trắc nghiệm nhiều lựa chọn (Câu 1 - 24).
  - **Phần 2:** Trắc nghiệm Đúng/Sai với 4 ý a, b, c, d (Câu 25 - 28).
  - **Phần 3:** Trắc nghiệm trả lời ngắn (Câu 29 - 30).
- **Tự động phân tích Ma trận Đáp án chuẩn:** Đọc trực tiếp bảng ma trận in ngang (Landscape) của Bộ GD&ĐT từ file PDF mà không tốn token AI.
- **Chấm điểm & Đối sánh tự động:** So sánh chi tiết bài làm của AI với đáp án chuẩn, highlight đúng/sai, tính điểm thang 10.
- **Báo cáo & Lưu trữ:**
  - Xuất bảng tổng hợp kết quả chi tiết ra file **CSV**.
  - Lưu trữ lịch sử chấm thi vào cơ sở dữ liệu **MongoDB** (tuỳ chọn).

---

## 📁 Cấu Trúc Dự Án

```text
doanchuyennganh/
├── app.py              # File mã nguồn chính (Giao diện Streamlit & Logic xử lý)
├── requirements.txt    # Danh sách thư viện Python cần thiết
├── .env.example        # File mẫu cấu hình biến môi trường
├── .env                # File cấu hình biến môi trường (không đẩy lên Git)
├── .gitignore          # Cấu hình bỏ qua các file nhạy cảm và tạm thời
└── README.md           # Tài liệu hướng dẫn sử dụng
```

---

## ⚙️ Yêu Cầu Hệ Thống

- **Python:** Phiên bản `>= 3.10`
- **Google Gemini API Key:** Lấy miễn phí tại [Google AI Studio](https://aistudio.google.com/)
- **MongoDB Atlas (Tuỳ chọn):** Để lưu trữ lịch sử chấm thi

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Ứng Dụng

### Bước 1: Mở Terminal tại thư mục dự án
```bash
cd d:\doanchuyennganh
```

### Bước 2: Tạo và kích hoạt môi trường ảo (Khuyến nghị)
- **Trên Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
- **Trên Windows (Command Prompt):**
  ```cmd
  python -m venv .venv
  .\.venv\Scripts\activate.bat
  ```

### Bước 3: Cài đặt các thư viện phụ thuộc
```bash
pip install -r requirements.txt
```

### Bước 4: Cấu hình biến môi trường
Tạo file `.env` (hoặc sao chép từ `.env.example`) và điền API Key:
```env
GEMINI_API_KEY=your_gemini_api_key_here
MONGODB_URI=your_mongodb_connection_string_here
```
*(Lưu ý: Bạn cũng có thể nhập API Key trực tiếp trên giao diện Sidebar của Streamlit khi chạy app).*

### Bước 5: Khởi chạy ứng dụng Streamlit
```bash
python -m streamlit run app.py
```
Ứng dụng sẽ tự động mở trên trình duyệt tại địa chỉ: `http://localhost:8501`.

---

## 📖 Hướng Dẫn Sử Dụng Trên Giao Diện

1. **Cấu hình Sidebar:**
   - Kiểm tra `Gemini API Key` và `Năm Thi` (mặc định: `2025`).
   - (Tuỳ chọn) Nhập `MongoDB URI` nếu muốn lưu trữ lịch sử vào Database.
2. **Quy ước đặt tên file Đề thi (PDF):**
   - Đặt tên file PDF đề thi chứa mã đề gồm 3-4 chữ số để hệ thống tự động nhận diện và tra cứu đáp án (Ví dụ: `De_0503.pdf`, `De_501.pdf`, `502.pdf`...).
3. **Tải dữ liệu:**
   - **Cột trái:** Kéo thả 1 hoặc nhiều file PDF Đề thi cần chấm.
   - **Cột phải:** Kéo thả file Đáp án chuẩn (hỗ trợ file PDF ma trận đáp án của Bộ GD&ĐT, hoặc file CSV / Excel).
4. **Bắt đầu chấm:**
   - Nhấn **🚀 Bắt Đầu Xử Lý Hàng Loạt**.
   - Hệ thống sẽ lần lượt giải từng đề thi, đối sánh đáp án và hiển thị bảng kết quả.
5. **Xuất kết quả:**
   - Sau khi hoàn tất, nhấn **📥 Tải xuống Bảng Kết Quả (CSV)** để lưu báo cáo chấm thi.
