"""
=============================================================================
MODULE: core/pdf_utils.py
CHỨC NĂNG:
- Trích xuất văn bản kỹ thuật số từ file PDF đề thi (extract_text_from_pdf).
- Tự động nhận diện Mã Đề và Năm Thi từ nội dung tiêu đề hoặc tên file PDF.
=============================================================================
"""

import os
import re
import pdfplumber
from core.excel_utils import normalize_ma_de


def extract_text_from_pdf(pdf_file):
    """
    Trích xuất nội dung văn bản đề thi từ PDF bằng pdfplumber nếu có digital text layer.
    Nếu là PDF dạng scan ảnh thuần túy, hàm trả về chuỗi rỗng để kích hoạt AI Vision.
    """
    text = ""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=1, y_tolerance=1)
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass
    return text.strip()


def detect_metadata_from_file_and_text(pdf_file, text=""):
    """
    Tự động nhận diện Mã Đề và Năm Thi từ nội dung văn bản trang đầu, tên file PDF
    hoặc siêu dữ liệu nội tại (PDF CreationDate/ModDate/Title) khi file scan bị đổi tên.
    Ví dụ: 'ĐỀ THI TỐT NGHIỆP THPT NĂM 2025 - Mã đề 0504' -> Mã: '0504', Năm: '2025'.
    """
    raw_name = pdf_file.name if hasattr(pdf_file, 'name') else str(pdf_file)
    file_name = os.path.basename(raw_name)

    # Đọc nhanh byte PDF để lấy metadata nội tại (0 token, < 1ms) nếu cần
    pdf_meta_bytes = b""
    try:
        if hasattr(pdf_file, 'getvalue'):
            pdf_meta_bytes = pdf_file.getvalue()
        elif hasattr(pdf_file, 'read') and hasattr(pdf_file, 'seek'):
            pos = pdf_file.tell() if hasattr(pdf_file, 'tell') else 0
            pdf_file.seek(0)
            pdf_meta_bytes = pdf_file.read()
            pdf_file.seek(pos)
    except Exception:
        pass

    # 1. Nhận diện năm thi: Văn bản đề -> Tên file -> PDF CreationDate/ModDate -> Mặc định 2025
    detected_year = "2025"
    m_year = (
        re.search(r'NĂM\s+(202[4-9]|203\d)', text, re.IGNORECASE)
        or re.search(r'(202[4-9]|203\d)', file_name)
    )
    if m_year:
        detected_year = str(m_year.group(1))
    elif pdf_meta_bytes:
        m_meta_year = re.search(rb'(?:CreationDate|ModDate)\s*\(D:(202[4-9]|203\d)', pdf_meta_bytes)
        if m_meta_year:
            detected_year = m_meta_year.group(1).decode('ascii', errors='ignore')

    # 2. Nhận diện mã đề: Văn bản đề -> Tên file (đã lọc năm) -> PDF Title metadata
    file_name_no_year = re.sub(r'202[4-9]|203\d', '', file_name)
    detected_code = ""
    m_code = (
        re.search(r'Mã\s+đề(?:\s+thi)?\s*[:\.]?\s*(\d{3,4})', text, re.IGNORECASE)
        or re.search(r'(?<!\d)(0\d{3}|[1-9]\d{2,3})(?!\d)', file_name_no_year)
    )
    if m_code:
        detected_code = normalize_ma_de(m_code.group(1))
    else:
        if pdf_meta_bytes:
            m_title_code = re.search(rb'/Title\s*\([^)]*?(0\d{3})\b', pdf_meta_bytes)
            if m_title_code:
                detected_code = normalize_ma_de(m_title_code.group(1).decode('ascii', errors='ignore'))
        if not detected_code:
            detected_code = normalize_ma_de(file_name_no_year.split('.')[0])

    return detected_code, detected_year
   

   