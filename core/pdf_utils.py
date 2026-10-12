"""
=============================================================================
MODULE: core/pdf_utils.py
CHỨC NĂNG:
- Trích xuất văn bản kỹ thuật số từ file PDF đề thi (extract_text_from_pdf).
- Tự động nhận diện Mã Đề và Năm Thi từ nội dung tiêu đề hoặc tên file PDF.
=============================================================================
"""

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
    Tự động nhận diện Mã Đề và Năm Thi từ nội dung văn bản trang đầu hoặc từ tên file PDF.
    Ví dụ: 'ĐỀ THI TỐT NGHIỆP THPT NĂM 2026 - Mã đề 0504' -> Mã: '0504', Năm: '2026'.
    """
    file_name = pdf_file.name if hasattr(pdf_file, 'name') else str(pdf_file)
    
    # 1. Nhận diện năm thi (mặc định 2025 nếu không tìm thấy)
    detected_year = "2025"
    m_year = re.search(r'NĂM\s+(202[4-9]|203\d)', text, re.IGNORECASE) or re.search(r'\b(202[4-9]|203\d)\b', file_name)
    if m_year:
        detected_year = str(m_year.group(1))
        
    # 2. Nhận diện mã đề thi
    detected_code = ""
    m_code = re.search(r'Mã\s+đề(?:\s+thi)?\s*[:\.]?\s*(\d{3,4})', text, re.IGNORECASE) or re.search(r'(\d{3,4})', file_name)
    if m_code:
        detected_code = normalize_ma_de(m_code.group(1))
    else:
        detected_code = normalize_ma_de(file_name.split('.')[0])
        
    return detected_code, detected_year
