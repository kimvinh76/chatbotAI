# 🤖 Hệ Thống AI Chấm Thi & Đánh Giá Đề Thi Tin Học THPT (Chuẩn Bộ GD&ĐT 2025)

Hệ thống ứng dụng **Generative AI (Google Gemini 3.8 Flash & Gemini 3.1 Pro)** kết hợp thư viện xử lý tài liệu **pdfplumber**, thị giác máy tính tách mộc đỏ và cơ sở dữ liệu **MongoDB Atlas** nhằm tự động hóa quy trình bóc tách đề thi, giải đề độc lập, đối sánh đáp án chuẩn và chấm điểm hàng loạt (Batch Processing) cho các đề thi môn Tin học theo cấu trúc mới nhất của Bộ Giáo dục và Đào tạo.

---

## 🌟 Tính Năng Nổi Bật

- **Kiến trúc Modular Monolith:** Mã nguồn được phân tách rõ ràng thành các tầng `core/` (nghiệp vụ lõi) và `views/` (giao diện Streamlit), dễ dàng bảo trì và phát triển.
- **Chiến lược 2 Pha (Flash Multi-Phase):** Giúp mô hình Flash siêu rẻ (~30 VNĐ/đề) đọc trọn vẹn và giải chính xác 100% cả 24 câu trắc nghiệm Phần I và 6 câu Đúng/Sai (24 ý) Phần II kèm lời giải thích.
- **Tự động nhận diện Đề & Năm thi:** AI tự động đọc Năm thi (2025, 2026...) và Mã đề trực tiếp từ tiêu đề file PDF.
- **Bóc tách Ma trận Đáp án xuyên Mộc Đỏ:** AI Vision phân tách lớp mực đen và mực đỏ để đọc chuẩn xác bảng ma trận in ngang của Bộ GD&ĐT.
- **Ngân hàng Đáp án & Khóa An Toàn:** Quản lý toàn bộ 48 mã đề trên MongoDB dưới dạng Ma trận bảng; hỗ trợ rà soát, sửa trực tiếp và Khóa Phê Duyệt chống ghi đè vĩnh viễn.
- **Cache Bài Giải Thông Minh:** Tự động lưu và kiểm tra chất lượng bài giải cũ trong MongoDB; phát hiện bài cũ thiếu giải thích Phần II để ép giải mới; có nút chủ động "Bắt buộc giải lại đề".
- **Báo cáo Đa Sheet:** Xuất báo cáo điểm tổng hợp và bảng chi tiết từng câu hỏi ra file Excel `.xlsx` với bộ đệm RAM tức thì.

---

## 📁 Cấu Trúc Dự Án (Modular Monolith)

```text
doanchuyennganh/
├── app.py                      # File điều phối chính (Streamlit Entry Point ~150 dòng)
├── core/                       # Tầng xử lý nghiệp vụ lõi (Business Logic & Backend)
│   ├── __init__.py
│   ├── ai_grader.py            # System Prompt, Schemas, Gọi Gemini API (2-Phase Flash & Auto-Rescue)
│   ├── database.py             # MongoDB Connection Pool & Quản lý 4 Collections
│   ├── excel_utils.py          # Bóc tách Excel/CSV, chuyển đổi Ma trận Bộ GD&ĐT, xuất bytes
│   ├── grading_logic.py        # Chuẩn hóa trích xuất P1 & P2, bóc tách giải thích và chấm điểm
│   └── pdf_utils.py            # Trích xuất text PDF và tự động nhận diện Mã đề/Năm thi
├── views/                      # Tầng giao diện người dùng (Streamlit Views)
│   ├── __init__.py
│   ├── tab_grading.py          # Tab 1: Chấm thi tự động hàng loạt (Batch Grader)
│   ├── tab_history.py          # Tab 2: Lịch sử đợt chấm thi & xuất báo cáo đa sheet
│   └── tab_keys.py             # Tab 3: Ngân hàng đáp án chuẩn & Ma trận Bộ GD&ĐT
├── requirements.txt            # Danh sách thư viện Python
├── .env                        # Biến môi trường cấu hình bí mật (GEMINI_API_KEY, MONGODB_URI)
└── README.md                   # Tài liệu hướng dẫn sử dụng
```

---

## ⚙️ Yêu Cầu Hệ Thống

- **Python:** Phiên bản `>= 3.10`
- **Google Gemini API Key:** Lấy tại [Google AI Studio](https://aistudio.google.com/)
- **MongoDB Atlas:** Chuỗi kết nối MongoDB Connection String

---

##  Hướng Dẫn Cài Đặt & Chạy Ứng Dụng

### Bước 1: Môi trường ảo & Cài đặt thư viện
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Bước 2: Cấu hình file `.env`
Tạo file `.env` tại thư mục gốc:
```env
GEMINI_API_KEY=your_gemini_api_key_here
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
```

### Bước 3: Khởi chạy ứng dụng Streamlit

Bạn có thể chạy ứng dụng theo bất kỳ cách nào dưới đây:

**Cách 1 (Nhanh nhất - 1 click):**
- Bấm đúp vào tệp `run_app.bat` (hoặc trong Terminal gõ `.\run` rồi Enter).

**Cách 2 (Dùng lệnh chuẩn):**
Mở một cửa sổ Terminal mới tại `D:\doanchuyennganh` và gõ:
```powershell
streamlit run app.py
```
hoặc:
```powershell
python -m streamlit run app.py
```

> **Lưu ý:** Nếu terminal đang mở sẵn từ trước khi cài đặt, hãy **tắt đi và mở lại tab Terminal mới** (hoặc gõ `.\run`) để Windows nạp lại biến môi trường nhé.

Ứng dụng sẽ tự động khởi chạy tại: `http://localhost:8501`.
