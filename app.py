import streamlit as st
import pandas as pd
import pdfplumber
import google.generativeai as genai
from pymongo import MongoClient
import os
import json
import time
import re
import io
from datetime import datetime
from dotenv import load_dotenv
import typing_extensions as typing

# Tải biến môi trường
load_dotenv()

# --- CẤU HÌNH TRANG ---
st.set_page_config(
    page_title="AI Chấm Thi Tin Học 2025",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- SYSTEM PROMPT ---
SYSTEM_PROMPT = """Bạn là chuyên gia giáo dục môn Tin học THPT. Nhiệm vụ của bạn là giải chính xác toàn bộ các câu hỏi trong đề thi Tốt nghiệp THPT môn Tin học chuẩn Bộ GD&ĐT 2025.

CẤU TRÚC ĐỀ THI TIN HỌC 2025:
1. PHẦN I (Câu 1 đến 24): Trắc nghiệm 4 phương án, chọn 1 đáp án đúng (A, B, C hoặc D). Kèm lời giải thích súc tích (1-2 câu, dưới 25 từ) nêu rõ căn cứ lý thuyết/cú pháp chọn đáp án.
2. PHẦN II (Gồm 6 câu hỏi Đúng/Sai, mỗi câu có 4 ý a, b, c, d):
   - A. Phần chung (cho tất cả thí sinh):
     + Câu 1: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai', kèm giải thích ngắn gọn dưới 25 từ cho từng ý)
     + Câu 2: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai', kèm giải thích ngắn gọn dưới 25 từ cho từng ý)
   - B. Phần riêng:
     + B1. Khoa học máy tính:
       * Câu 3: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai', kèm giải thích ngắn gọn dưới 25 từ cho từng ý)
       * Câu 4: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai', kèm giải thích ngắn gọn dưới 25 từ cho từng ý)
     + B2. Tin học ứng dụng:
       * Câu 5: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai', kèm giải thích ngắn gọn dưới 25 từ cho từng ý)
       * Câu 6: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai', kèm giải thích ngắn gọn dưới 25 từ cho từng ý)
*(Lưu ý: Môn Tin học KHÔNG CÓ Phần III).*

QUY TẮC BẮT BUỘC:
- Hãy giải đầy đủ cả 24 câu Phần I và toàn bộ 6 câu Phần II (gồm cả Câu 1, 2 chung và Câu 3, 4 KHMT, Câu 5, 6 THUD).
- Phần I: dap_an chỉ là 1 ký tự duy nhất ('A', 'B', 'C' hoặc 'D'). giai_thich chứa lời giải thích ngắn gọn dưới 25 từ.
- Phần II: Các trường y_a, y_b, y_c, y_d BẮT BUỘC CHỈ CHỨA DUY NHẤT 1 từ là 'Đúng' hoặc 'Sai' (TUYỆT ĐỐI KHÔNG mở ngoặc, không ghi kèm lý do vào trường này). Toàn bộ lời giải thích BẮT BUỘC phải điền riêng vào các trường giai_thich_a, giai_thich_b, giai_thich_c, giai_thich_d (dưới 25 từ mỗi ý).
- Trả về JSON thuần tuân thủ đúng Schema. Lời giải thích phải súc tích, ngắn gọn, chuẩn xác kiến thức Tin học, không viết dông dài để tối ưu tốc độ xử lý."""

# --- SCHEMA JSON ĐẦU RA ---
class Phan1(typing.TypedDict):
    cau_hoi: int
    dap_an: str
    giai_thich: str

class Phan2CauHoi(typing.TypedDict):
    cau_hoi: int  # 1 đến 6
    y_a: str  # 'Đúng' hoặc 'Sai'
    y_b: str  # 'Đúng' hoặc 'Sai'
    y_c: str  # 'Đúng' hoặc 'Sai'
    y_d: str  # 'Đúng' hoặc 'Sai'
    giai_thich_a: str
    giai_thich_b: str
    giai_thich_c: str
    giai_thich_d: str

class DeThiResponse(typing.TypedDict):
    nam_thi: int  # Tự động đọc từ tiêu đề đề thi (vd: 2025 hoặc 2026)
    ma_de: str    # Tự động đọc từ mã đề trên đề thi (vd: "0504")
    phan_1: list[Phan1]
    phan_2: list[Phan2CauHoi]

# --- CÁC HÀM XỬ LÝ CHÍNH ---

def extract_text_from_pdf(pdf_file):
    """Trích xuất nội dung văn bản đề thi từ PDF bằng pdfplumber nếu có digital text layer."""
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
    """Tự động nhận diện Mã Đề và Năm Thi từ nội dung văn bản hoặc tên file PDF."""
    file_name = pdf_file.name if hasattr(pdf_file, 'name') else str(pdf_file)
    detected_year = "2025"
    m_year = re.search(r'NĂM\s+(202[4-9]|203\d)', text, re.IGNORECASE) or re.search(r'\b(202[4-9]|203\d)\b', file_name)
    if m_year:
        detected_year = str(m_year.group(1))
        
    detected_code = ""
    m_code = re.search(r'Mã\s+đề(?:\s+thi)?\s*[:\.]?\s*(\d{3,4})', text, re.IGNORECASE) or re.search(r'\b(\d{3,4})\b', file_name)
    if m_code:
        detected_code = str(m_code.group(1))
    else:
        detected_code = file_name.split('.')[0]
        
    return detected_code, detected_year

def robust_exam_json_parser(resp_text):
    """Phân tích JSON bài giải đề thi với cơ chế tự phục hồi bằng Regex."""
    resp_text = re.sub(r'^```(?:json)?\s*', '', resp_text.strip(), flags=re.MULTILINE)
    resp_text = re.sub(r'\s*```$', '', resp_text, flags=re.MULTILINE)
    resp_text = re.sub(r'//.*', '', resp_text)
    resp_text = re.sub(r'/\*.*?\*/', '', resp_text, flags=re.DOTALL)
    resp_text = re.sub(r',\s*([\]}])', r'\1', resp_text)
    
    try:
        return json.loads(resp_text.strip(), strict=False)
    except Exception as e:
        # Regex phục hồi linh hoạt nếu JSON bị dính ký tự lạ
        phan_1 = []
        for m in re.finditer(r'\{[^{}]*?"cau_hoi"\s*:\s*(\d+)[^{}]*?"dap_an"\s*:\s*"([A-Da-d])"(?:[^{}]*?"giai_thich"\s*:\s*"([^"]*)")?[^{}]*?\}', resp_text):
            phan_1.append({
                "cau_hoi": int(m.group(1)),
                "dap_an": m.group(2).upper(),
                "giai_thich": m.group(3).strip() if m.group(3) else ""
            })
            
        phan_2 = []
        for m in re.finditer(
            r'\{[^{}]*?"cau_hoi"\s*:\s*(\d+)[^{}]*?"y_a"\s*:\s*"([^"]+)"[^{}]*?"y_b"\s*:\s*"([^"]+)"[^{}]*?"y_c"\s*:\s*"([^"]+)"[^{}]*?"y_d"\s*:\s*"([^"]+)"[^{}]*?\}',
            resp_text, re.DOTALL
        ):
            m_text = m.group(0)
            ga = re.search(r'"giai_thich_a"\s*:\s*"([^"]*)"', m_text)
            gb = re.search(r'"giai_thich_b"\s*:\s*"([^"]*)"', m_text)
            gc = re.search(r'"giai_thich_c"\s*:\s*"([^"]*)"', m_text)
            gd = re.search(r'"giai_thich_d"\s*:\s*"([^"]*)"', m_text)
            phan_2.append({
                "cau_hoi": int(m.group(1)),
                "y_a": m.group(2).strip(),
                "y_b": m.group(3).strip(),
                "y_c": m.group(4).strip(),
                "y_d": m.group(5).strip(),
                "giai_thich_a": ga.group(1).strip() if ga else "",
                "giai_thich_b": gb.group(1).strip() if gb else "",
                "giai_thich_c": gc.group(1).strip() if gc else "",
                "giai_thich_d": gd.group(1).strip() if gd else ""
            })
            
        res = {"phan_1": phan_1, "phan_2": phan_2}
        m_y = re.search(r'"nam_thi"\s*:\s*(\d{4})', resp_text)
        if m_y:
            res["nam_thi"] = int(m_y.group(1))
        m_c = re.search(r'"ma_de"\s*:\s*"([^"]+)"', resp_text)
        if m_c:
            res["ma_de"] = str(m_c.group(1))
            
        if phan_1 or phan_2:
            return res
        raise e

def call_gemini_api(api_key, text, ma_de, nam_thi="2025", pdf_bytes=None, model_name="gemini-3.1-pro-preview"):
    """Gửi nội dung đề thi sang Gemini để giải đề tự động và trả về cấu trúc JSON.
    AI tự động đọc tiêu đề để nhận diện Năm Thi và Mã Đề chính xác."""
    genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=DeThiResponse,
            temperature=0.1,
            max_output_tokens=8192
        )
    )
    
    contents = []
    # Nếu file PDF là dạng scan/ảnh (text rỗng) hoặc có pdf_bytes, gửi PDF trực tiếp cho AI nhìn bằng Vision
    if pdf_bytes and len(text.strip()) < 50:
        contents.append({
            "mime_type": "application/pdf",
            "data": pdf_bytes
        })
        user_prompt = f"""Đính kèm là tài liệu PDF toàn bộ đề thi (Mã dự kiến: {ma_de}).
Hãy đọc kỹ trang đầu đề thi để xác định chính xác NĂM THI (vd: 2025 hoặc 2026) và MÃ ĐỀ THI, đồng thời giải ĐẦY ĐỦ 24 câu Phần I (từ câu 1 đến 24) và 6 câu Phần II theo đúng JSON Schema."""
    else:
        user_prompt = f"""Dưới đây là nội dung đề thi (Mã dự kiến: {ma_de}).
Hãy đọc tiêu đề để xác định chính xác NĂM THI (vd: 2025 hoặc 2026) và MÃ ĐỀ THI, đồng thời giải ĐẦY ĐỦ 24 câu Phần I và 6 câu Phần II, trả về JSON chuẩn:\n\n--- NỘI DUNG ĐỀ THI ---\n{text}"""
        
    contents.append(user_prompt)
    response = model.generate_content(contents)
    return robust_exam_json_parser(response.text)

def parse_answer_key_pdf(api_key, pdf_file, target_codes=None, model_name="gemini-3.1-pro-preview"):
    """Dùng Gemini Multimodal Vision để đọc bảng đáp án in ngang và có con dấu với định dạng nén siêu gọn."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=32768
        )
    )
    
    pdf_bytes = pdf_file.getvalue() if hasattr(pdf_file, 'getvalue') else None
    if not pdf_bytes and isinstance(pdf_file, str):
        with open(pdf_file, 'rb') as f:
            pdf_bytes = f.read()
            
    if not pdf_bytes:
        return pd.DataFrame(), "2025"

    pdf_part = {
        "mime_type": "application/pdf",
        "data": pdf_bytes
    }
    
    code_filter_instruction = ""
    if target_codes:
        code_filter_instruction = f"""
YÊU CẦU QUAN TRỌNG VỀ DANH SÁCH MÃ ĐỀ:
- BẮT BUỘC BÓC TÁCH ĐẦY ĐỦ TẤT CẢ CÁC MÃ ĐỀ: {', '.join(target_codes)}.
- Trả về JSON chứa TẤT CẢ từng mã đề trong danh sách trên (mỗi mã đề là 1 key tương ứng).
- CHỈ trả về đúng các mã đề trong danh sách trên, KHÔNG trả về các mã đề khác (các mã khác sẽ được đọc ở lượt riêng).
- Gióng đúng CỘT của từng mã đề, tuyệt đối không lấy nhầm cột bên cạnh."""
    
    prompt = f"""Bạn là chuyên gia thị giác máy tính và OCR siêu chính xác chuyên bóc tách bảng ma trận đáp án kỳ thi THPT Quốc gia môn Tin học của Bộ GD&ĐT.
Hãy đọc toàn bộ bảng ma trận đáp án từ file PDF đính kèm.

LƯU Ý ĐẶC BIỆT VỀ CON DẤU MỘC ĐỎ VÀ CƠ CHẾ TÁCH LỚP MÀU:
1. TÁCH LỚP MÀU THỊ GIÁC (COLOR SEPARATION):
   - Bảng đáp án, số câu và các chữ cái đáp án gốc ĐỀU ĐƯỢC IN BẰNG MỰC ĐEN (BLACK INK) sắc nét.
   - Con mộc tròn và chữ trong con dấu của Bộ GD&ĐT là MỰC ĐỎ/HỒNG (RED/MAGENTA INK) đóng đè lên trên.
   - HÃY BỎ QUA HOÀN TOÀN LỚP MỰC ĐỎ (các vòng tròn mộc đỏ, chữ đỏ, vết mực đỏ lem). Chỉ nhìn xuyên qua và bóc tách các nét ký tự MỰC ĐEN nguyên thủy nằm bên dưới.

2. PHÂN BIỆT HÌNH HỌC KÝ TỰ BỊ MỘC ĐỎ ĐÈ (Rất quan trọng ở các cột 0501, 0502, 0503, 0504 và 0525, 0526, 0527, 0528 từ câu 1 đến câu 10):
   - Chữ 'B': Luôn có 1 nét thẳng đứng mực đen bên trái + 2 bụng cong mực đen bên phải. TUYỆT ĐỐI không đọc nhầm thành 'D' do viền mộc đỏ làm mờ khe giữa 2 bụng.
   - Chữ 'C': Luôn là nét cong HỞ RỘNG BÊN PHẢI bằng mực đen. Đường viền cong của mộc đỏ có thể đi qua mép phải tạo cảm giác khép kín, TUYỆT ĐỐI KHÔNG đọc thành 'D' hay 'O' khi nét mực đen vốn hở.
   - Chữ 'D': Có 1 nét thẳng đứng mực đen bên trái + 1 bụng cong duy nhất mở rộng.
   - Chữ 'A': Có đỉnh nhọn 2 nét xiên mực đen chụm lại phía trên + gạch ngang ở giữa.
   - TẤT CẢ các ô Phần 1 (từ câu 1 đến 24) BẮT BUỘC chỉ là một trong 4 ký tự: A, B, C, D. Không có ký tự nào là O, 8, S hay 0.

3. GIÓNG HÀNG VÀ CỘT:
   - Dù con dấu làm mờ một số đường kẻ ô, hãy gióng hàng ngang (câu 1 đến câu 30) và cột dọc (mã đề) theo đúng vị trí lưới ma trận để không bị lệch hàng.
{code_filter_instruction}

QUY CÁCH DỮ LIỆU:
- Cột: Các Mã đề (ví dụ 0501 đến 0548).
- Hàng 1 đến 24: là Phần 1 (trắc nghiệm: 1 ký tự A, B, C hoặc D).
- Hàng 25 đến 30: là Phần 2 (Đúng/Sai gồm 4 ý A,B,C,D; ký hiệu D=Đúng, S=Sai):
  + Hàng 25: Câu 1
  + Hàng 26: Câu 2
  + Hàng 27: Câu 3 (Khoa học máy tính)
  + Hàng 28: Câu 4 (Khoa học máy tính)
  + Hàng 29: Câu 5 (Tin học ứng dụng)
  + Hàng 30: Câu 6 (Tin học ứng dụng)

ĐỊNH DẠNG ĐẦU RA (JSON BẮT BUỘC, TUYỆT ĐỐI KHÔNG CHÈN DẤU // HOẶC COMMENT):
{{
  "0501": {{
    "p1": ["D", "B", "A", "C", "D", "C", "B", "C", "A", "B", "A", "D", "D", "D", "B", "D", "C", "C", "C", "B", "B", "B", "C", "C"],
    "p2": [
      ["S", "D", "S", "D"],
      ["S", "D", "S", "D"],
      ["D", "S", "D", "S"],
      ["S", "S", "D", "D"],
      ["D", "D", "S", "S"],
      ["D", "S", "S", "D"]
    ]
  }},
  "0502": {{
    "p1": ["A", "C", "D", "B", "C", "D", "B", "A", "C", "D", "B", "A", "C", "D", "B", "A", "C", "D", "B", "A", "C", "D", "B", "A"],
    "p2": [
      ["D", "S", "D", "S"],
      ["S", "D", "S", "D"],
      ["D", "D", "S", "S"],
      ["S", "S", "D", "D"],
      ["D", "S", "D", "S"],
      ["S", "D", "S", "D"]
    ]
  }}
}}
Chỉ trả về JSON thuần hợp lệ, không chứa bất kỳ giải thích hay ký tự comment nào."""

    response = model.generate_content([pdf_part, prompt])
    resp_text = response.text.strip()
    
    # Dọn sạch định dạng code fences
    resp_text = re.sub(r'^```(?:json)?\s*', '', resp_text, flags=re.MULTILINE)
    resp_text = re.sub(r'\s*```$', '', resp_text, flags=re.MULTILINE)
    resp_text = re.sub(r'//.*', '', resp_text)
    resp_text = re.sub(r'/\*.*?\*/', '', resp_text, flags=re.DOTALL)
    resp_text = re.sub(r',\s*([\]}])', r'\1', resp_text)
    
    json_match = re.search(r'\{.*\}', resp_text, re.DOTALL)
    if json_match:
        resp_text = json_match.group()
        
    try:
        data = json.loads(resp_text, strict=False)
    except Exception:
        # Regex fallback nếu có unescaped token trong map đáp án
        data = {}
        for m in re.finditer(r'"(\d{3,4})"\s*:\s*\{([^{}]+(?:\{[^{}]*\}[^{}]*)*)\}', resp_text):
            code = m.group(1)
            block = m.group(2)
            p1_m = re.search(r'"p1"\s*:\s*\[(.*?)\]', block)
            p1_vals = re.findall(r'"([A-Da-d])"', p1_m.group(1)) if p1_m else []
            p2_m = re.search(r'"p2"\s*:\s*\[(.*)\]', block, re.DOTALL)
            p2_groups = []
            if p2_m:
                for sub in re.findall(r'\[(.*?)\]', p2_m.group(1)):
                    p2_groups.append(re.findall(r'"([^"]+)"', sub))
            data[code] = {"p1": p1_vals, "p2": p2_groups}
    
    # Mở phẳng dữ liệu (unwrap) nếu Gemini bọc ngoài bằng object cha
    unwrapped_data = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict) and ("p1" in v or "p2" in v):
                m_code = re.search(r'\d{3,4}', str(k))
                clean_k = m_code.group(0) if m_code else str(k).strip()
                unwrapped_data[clean_k] = v
            elif isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    if isinstance(sub_v, dict) and ("p1" in sub_v or "p2" in sub_v):
                        m_code = re.search(r'\d{3,4}', str(sub_k))
                        clean_sub_k = m_code.group(0) if m_code else str(sub_k).strip()
                        unwrapped_data[clean_sub_k] = sub_v
    if unwrapped_data:
        data = unwrapped_data

    rows_data = []
    y_labels = ['A', 'B', 'C', 'D']
    
    for ma_de, content in data.items():
        ma_de_str = str(ma_de).strip()
        # Chuẩn hóa về đúng mã đề 4 chữ số (ví dụ: '510' -> '0510')
        if ma_de_str.isdigit() and len(ma_de_str) == 3:
            canonical_code = f"0{ma_de_str}"
        else:
            canonical_code = ma_de_str
            
        p1 = content.get("p1", [])
        p2 = content.get("p2", [])
        
        for idx, ans in enumerate(p1):
            rows_data.append({
                "Mã Đề": canonical_code,
                "Phần": 1,
                "Câu": idx + 1,
                "Ý": "",
                "Đáp Án": str(ans).strip().upper()
            })
        for cau_idx, y_group in enumerate(p2):
            if isinstance(y_group, str):
                vals = [c for c in y_group if c.upper() in ['D', 'S', 'Đ']]
            else:
                vals = list(y_group)
                
            for y_idx, val in enumerate(vals[:4]):
                val_str = str(val).strip().upper()
                final_val = "Đúng" if val_str in ['D', 'Đ', 'ĐÚNG'] else "Sai"
                rows_data.append({
                    "Mã Đề": canonical_code,
                    "Phần": 2,
                    "Câu": cau_idx + 1,
                    "Ý": y_labels[y_idx],
                    "Đáp Án": final_val
                })
                    
    detected_key_year = "2025"
    m_ky = re.search(r'202[4-9]', resp_text)
    if m_ky:
        detected_key_year = m_ky.group(0)
    elif hasattr(pdf_file, 'name'):
        m_fn = re.search(r'202[4-9]', pdf_file.name)
        if m_fn:
            detected_key_year = m_fn.group(0)
            
    return pd.DataFrame(rows_data), detected_key_year

def normalize_ma_de(code):
    """Chuẩn hóa mã đề về dạng 4 chữ số (vd: '510' -> '0510')."""
    c = str(code).strip()
    m = re.search(r'\d{3,4}', c)
    if m:
        c = m.group(0)
    return c.zfill(4) if c.isdigit() and len(c) == 3 else c

def detect_answer_key_codes(api_key, pdf_bytes, model_name="gemini-3.1-pro-preview"):
    """Lượt gọi nhẹ: liệt kê toàn bộ mã đề (tiêu đề cột) và năm thi có trong file PDF đáp án."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=8192
        )
    )
    prompt = """Đây là file PDF bảng ma trận đáp án môn Tin học kỳ thi Tốt nghiệp THPT.
Hãy liệt kê TẤT CẢ các mã đề (tiêu đề cột, thường dạng 4 chữ số như 0501, 0502...) xuất hiện trong toàn bộ file (mọi trang), và năm thi ghi trên tài liệu.
Chỉ trả về JSON dạng: {"nam_thi": 2025, "danh_sach_ma_de": ["0501", "0502"]}"""
    response = model.generate_content([{"mime_type": "application/pdf", "data": pdf_bytes}, prompt])
    txt = response.text.strip()
    m = re.search(r'\{.*\}', txt, re.DOTALL)
    data = {}
    try:
        data = json.loads(m.group(0) if m else txt)
    except Exception:
        pass
    codes = data.get("danh_sach_ma_de") or re.findall(r'"(\d{3,4})"', txt)
    codes = sorted({normalize_ma_de(c) for c in codes if re.search(r'\d{3,4}', str(c))})
    year = str(data.get("nam_thi", "")) if data.get("nam_thi") else ""
    return codes, year

def parse_full_answer_key_pdf(api_key, pdf_file, model_name="gemini-3.1-pro-preview", chunk_size=12, progress_cb=None):
    """Đọc 1 lần TOÀN BỘ file PDF đáp án (vd: 48 mã đề).
    Chia mã đề thành từng nhóm nhỏ để mỗi lượt gọi không bị cắt cụt đầu ra, sau đó gộp lại và thử lại các mã bị thiếu.
    Trả về (DataFrame, năm thi, danh sách mã đề, danh sách mã thiếu/không đủ 48 câu-ý)."""
    pdf_bytes = pdf_file.getvalue() if hasattr(pdf_file, 'getvalue') else None
    if not pdf_bytes:
        return pd.DataFrame(), "2025", [], []

    if progress_cb:
        progress_cb(0.05, "Đang liệt kê toàn bộ mã đề trong file đáp án...")
    codes, year = detect_answer_key_codes(api_key, pdf_bytes, model_name=model_name)
    m_fn = re.search(r'202[4-9]', getattr(pdf_file, 'name', ''))
    if m_fn:
        year = m_fn.group(0)
    year = year or "2025"
    if not codes:
        df, y2 = parse_answer_key_pdf(api_key, pdf_file, model_name=model_name)
        return df, year or y2, sorted(df['Mã Đề'].unique().tolist()) if not df.empty else [], []

    def _complete_codes(df):
        if df.empty:
            return set()
        cnt = df.groupby('Mã Đề').size()
        return {c for c, n in cnt.items() if n >= 48}

    frames = []
    chunks = [codes[i:i + chunk_size] for i in range(0, len(codes), chunk_size)]
    for i, chunk in enumerate(chunks):
        if progress_cb:
            progress_cb(0.1 + 0.75 * i / len(chunks), f"Đang bóc tách nhóm {i + 1}/{len(chunks)}: {', '.join(chunk)}")
        df_c, _ = parse_answer_key_pdf(api_key, pdf_file, target_codes=chunk, model_name=model_name)
        if not df_c.empty:
            df_c['Mã Đề'] = df_c['Mã Đề'].map(normalize_ma_de)
            frames.append(df_c[df_c['Mã Đề'].isin(chunk)])
        if i < len(chunks) - 1:
            time.sleep(2)  # Giãn nhịp tránh lỗi 429

    df_all = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df_all.empty:
        df_all = df_all.drop_duplicates(subset=['Mã Đề', 'Phần', 'Câu', 'Ý'], keep='first')

    # Thử lại 1 lần cho các mã bị thiếu hoặc không đủ 48 câu/ý
    missing = [c for c in codes if c not in _complete_codes(df_all)]
    if missing:
        if progress_cb:
            progress_cb(0.9, f"Thử đọc lại {len(missing)} mã còn thiếu: {', '.join(missing)}")
        df_r, _ = parse_answer_key_pdf(api_key, pdf_file, target_codes=missing, model_name=model_name)
        if not df_r.empty:
            df_r['Mã Đề'] = df_r['Mã Đề'].map(normalize_ma_de)
            df_r = df_r[df_r['Mã Đề'].isin(missing)]
            if not df_all.empty:
                df_all = df_all[~df_all['Mã Đề'].isin(df_r['Mã Đề'].unique())]
            df_all = pd.concat([df_all, df_r], ignore_index=True)
        missing = [c for c in codes if c not in _complete_codes(df_all)]

    if progress_cb:
        progress_cb(1.0, "Hoàn tất bóc tách đáp án.")
    return df_all, year, codes, missing

# --- MA TRẬN ĐÁP ÁN (Hàng = Câu/Ý, Cột = Mã đề) ---
def answer_df_to_matrix(df_all):
    """Chuyển DataFrame đáp án dạng dọc sang ma trận giống bảng của Bộ để xem/sửa toàn bộ 1 lần."""
    if df_all is None or df_all.empty:
        return pd.DataFrame()
    df = df_all.copy()
    df['Mã Đề'] = df['Mã Đề'].map(normalize_ma_de)

    def _label(r):
        if int(r['Phần']) == 1:
            return f"P1 - Câu {int(r['Câu']):02d}"
        return f"P2 - Câu {int(r['Câu'])}{str(r['Ý']).strip().lower()}"

    def _short(r):
        v = str(r['Đáp Án']).strip()
        if int(r['Phần']) == 2:
            return "Đ" if v.upper() in ("ĐÚNG", "DUNG", "Đ", "D", "TRUE") else "S"
        return v.upper()

    df['Vị Trí'] = df.apply(_label, axis=1)
    df['Giá Trị'] = df.apply(_short, axis=1)
    mat = df.pivot_table(index='Vị Trí', columns='Mã Đề', values='Giá Trị', aggfunc='first')
    mat = mat.reindex(sorted(mat.columns, key=str), axis=1).sort_index()
    mat.columns.name = None
    return mat.fillna("")

def matrix_column_to_items(col_series):
    """Chuyển 1 cột ma trận (1 mã đề) về danh sách đáp án chuẩn. Trả về (DataFrame, danh sách lỗi)."""
    rows, errors = [], []
    for vi_tri, val in col_series.items():
        v = str(val).strip().upper()
        m1 = re.match(r'P1 - Câu (\d+)', str(vi_tri))
        m2 = re.match(r'P2 - Câu (\d)([a-d])', str(vi_tri))
        if m1:
            if v not in ("A", "B", "C", "D"):
                errors.append(f"{vi_tri}='{val}'")
                continue
            rows.append({"Phần": 1, "Câu": int(m1.group(1)), "Ý": "", "Đáp Án": v})
        elif m2:
            if v in ("Đ", "D", "ĐÚNG", "DUNG"):
                dv = "Đúng"
            elif v in ("S", "SAI"):
                dv = "Sai"
            else:
                errors.append(f"{vi_tri}='{val}'")
                continue
            rows.append({"Phần": 2, "Câu": int(m2.group(1)), "Ý": m2.group(2).upper(), "Đáp Án": dv})
    return pd.DataFrame(rows), errors

# ==============================================================================
# HỆ THỐNG QUẢN LÝ CƠ SỞ DỮ LIỆU MONGODB (4 COLLECTIONS CHUẨN ĐỒ ÁN)
# 1. answer_keys: Ngân hàng đáp án chuẩn của Bộ GD&ĐT
# 2. solved_exams: Bộ nhớ đệm (Cache) bài giải của AI để tiết kiệm Token
# 3. grading_batches: Quản lý theo từng Đợt thi / Ca chấm thi hàng loạt
# 4. exam_results: Kết quả chi tiết từng bài thi & đối sánh điểm
# ==============================================================================

@st.cache_resource(show_spinner=False)
def get_mongo_client(mongo_uri):
    """Khởi tạo connection pool duy nhất cho toàn ứng dụng, tái sử dụng kết nối TLS vĩnh viễn (loại bỏ độ trễ 8s)."""
    if not mongo_uri:
        return None
    try:
        return MongoClient(
            mongo_uri,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=50,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000
        )
    except Exception:
        return None

def get_mongo_db(mongo_uri):
    """Lấy database từ client đã được cache sẵn (truy xuất tức thì < 0.001s thay vì 8-9s tạo mới)."""
    if not mongo_uri:
        return None
    try:
        client = get_mongo_client(mongo_uri)
        if client is None:
            return None
        return client['ai_exam_grader']
    except Exception:
        return None

# --- COLLECTION 1: answer_keys ---
def save_answer_keys_to_db(mongo_uri, df_answers, nam_thi="2025", source_name="", allow_overwrite_verified=False):
    """Lưu bảng đáp án chuẩn bóc tách được vào collection 'answer_keys'.
    Tự động BẢO VỆ các mã đề đã được con người duyệt (trang_thai == 'da_xac_thuc'), không bị ghi đè ngẫu nhiên!"""
    if not mongo_uri or df_answers is None or df_answers.empty:
        return False, "Không có dữ liệu đáp án để lưu"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        count = 0
        protected_list = []
        for ma_de, group in df_answers.groupby("Mã Đề"):
            ma_de_str = str(ma_de).strip()
            # Kiểm tra xem mã đề này trong DB đã được duyệt thủ công hay chưa
            existing = col.find_one({"ma_de": ma_de_str, "nam_thi": str(nam_thi)})
            if not existing:
                existing = col.find_one({"ma_de": ma_de_str.lstrip('0'), "nam_thi": str(nam_thi)})
                
            if existing and existing.get("trang_thai") == "da_xac_thuc" and not allow_overwrite_verified:
                protected_list.append(ma_de_str)
                continue
                
            items = group[['Phần', 'Câu', 'Ý', 'Đáp Án']].to_dict(orient='records')
            col.update_one(
                {"ma_de": ma_de_str, "nam_thi": str(nam_thi)},
                {"$set": {
                    "ma_de": ma_de_str,
                    "nam_thi": str(nam_thi),
                    "nguon_file": str(source_name),
                    "so_cau_hoi": len(items),
                    "thoi_gian_luu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "trang_thai": "tu_dong_ai",
                    "danh_sach_dap_an": items
                }},
                upsert=True
            )
            count += 1
            
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        msg = f"Đã đồng bộ {count} mã đề vào ngân hàng đáp án."
        if protected_list:
            msg += f" 🛡️ Đã bảo vệ {len(protected_list)} mã đề đã duyệt ({', '.join(protected_list)}) không bị ghi đè!"
        return True, msg
    except Exception as e:
        return False, str(e)

def get_answer_keys_from_db(mongo_uri, nam_thi="2025", target_codes=None):
    """Lấy đáp án chuẩn từ collection 'answer_keys' tái cấu trúc thành DataFrame."""
    if not mongo_uri:
        return pd.DataFrame()
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return pd.DataFrame()
        col = db['answer_keys']
        docs = list(col.find({"nam_thi": str(nam_thi)}))
        rows = []
        for doc in docs:
            ma_de = str(doc.get("ma_de", "")).strip()
            if target_codes:
                clean_target = [str(c).strip() for c in target_codes]
                clean_target_nozero = [c.lstrip('0') for c in clean_target]
                if ma_de not in clean_target and ma_de.lstrip('0') not in clean_target_nozero:
                    continue
            for item in doc.get("danh_sach_dap_an", []):
                rows.append({
                    "Mã Đề": ma_de,
                    "Phần": item.get("Phần"),
                    "Câu": item.get("Câu"),
                    "Ý": item.get("Ý", ""),
                    "Đáp Án": item.get("Đáp Án")
                })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

def check_verified_answer_key(mongo_uri, ma_de, nam_thi):
    """Kiểm tra xem mã đề này trong MongoDB đã có bản đã xác thực thủ công hay chưa để ưu tiên sử dụng."""
    if not mongo_uri or not ma_de:
        return None
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return None
        col = db['answer_keys']
        doc = col.find_one({"ma_de": str(ma_de), "nam_thi": str(nam_thi)})
        if not doc:
            doc = col.find_one({"ma_de": str(ma_de).lstrip('0'), "nam_thi": str(nam_thi)})
        if not doc and len(str(ma_de)) == 3:
            doc = col.find_one({"ma_de": f"0{str(ma_de)}", "nam_thi": str(nam_thi)})
        if doc and doc.get("trang_thai") == "da_xac_thuc":
            rows = []
            for item in doc.get("danh_sach_dap_an", []):
                rows.append({
                    "Mã Đề": str(ma_de),
                    "Phần": item.get("Phần"),
                    "Câu": item.get("Câu"),
                    "Ý": item.get("Ý", ""),
                    "Đáp Án": item.get("Đáp Án")
                })
            return pd.DataFrame(rows)
    except Exception:
        pass
    return None

@st.cache_data(ttl=120, show_spinner=False)
def get_all_answer_keys_summary(mongo_uri, nam_thi=None):
    """Lấy danh sách tóm tắt tất cả các mã đề đáp án đang có trong ngân hàng (có Cache trong RAM)."""
    if not mongo_uri:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['answer_keys']
        query = {"nam_thi": str(nam_thi)} if (nam_thi and nam_thi != "Tất cả") else {}
        docs = list(col.find(query, {"ma_de": 1, "nam_thi": 1, "so_cau_hoi": 1, "thoi_gian_luu": 1, "nguon_file": 1, "trang_thai": 1}))
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []

def get_single_answer_key_detail(mongo_uri, ma_de, nam_thi):
    """Lấy chi tiết bảng đáp án của 1 mã đề cụ thể từ collection 'answer_keys'."""
    if not mongo_uri or not ma_de:
        return pd.DataFrame(), None
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return pd.DataFrame(), None
        col = db['answer_keys']
        doc = col.find_one({"ma_de": str(ma_de), "nam_thi": str(nam_thi)})
        if not doc:
            doc = col.find_one({"ma_de": str(ma_de).lstrip('0'), "nam_thi": str(nam_thi)})
        if doc and "danh_sach_dap_an" in doc:
            return pd.DataFrame(doc["danh_sach_dap_an"]), doc.get("trang_thai", "tu_dong_ai")
    except Exception:
        pass
    return pd.DataFrame(), None

def update_single_answer_key(mongo_uri, ma_de, nam_thi, df_items):
    """Cập nhật lại danh sách đáp án sau khi người dùng sửa trên st.data_editor.
    Tự động gắn cờ 'da_xac_thuc' để KHÓA BẢO VỆ vĩnh viễn không bị file mới ghi đè!"""
    if not mongo_uri or df_items is None or df_items.empty:
        return False, "Không có dữ liệu hợp lệ"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        items = df_items[['Phần', 'Câu', 'Ý', 'Đáp Án']].to_dict(orient='records')
        col.update_one(
            {"ma_de": str(ma_de), "nam_thi": str(nam_thi)},
            {"$set": {
                "danh_sach_dap_an": items,
                "so_cau_hoi": len(items),
                "trang_thai": "da_xac_thuc",
                "thoi_gian_luu": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }},
            upsert=True
        )
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"🛡️ Đã KHÓA BẢO VỆ & cập nhật đáp án chuẩn cho Mã đề {ma_de} (Năm {nam_thi}) thành công!"
    except Exception as e:
        return False, str(e)

def delete_answer_key_from_db(mongo_uri, ma_de, nam_thi):
    """Xóa một mã đề đáp án khỏi collection 'answer_keys'."""
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        col.delete_one({"ma_de": str(ma_de), "nam_thi": str(nam_thi)})
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"Đã xóa mã đề {ma_de} (Năm {nam_thi}) khỏi Ngân Hàng Đáp Án"
    except Exception as e:
        return False, str(e)

def cleanup_duplicate_answer_keys(mongo_uri, nam_thi=None):
    """Tự động dọn dẹp các mã đề 3 chữ số dư thừa (501, 510) gộp về chuẩn 4 chữ số (0501, 0510)."""
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        query = {"nam_thi": str(nam_thi)} if (nam_thi and nam_thi != "Tất cả") else {}
        all_docs = list(col.find(query))
        
        cleaned_count = 0
        for doc in all_docs:
            code = str(doc.get("ma_de", "")).strip()
            y = str(doc.get("nam_thi", "2025"))
            if code.isdigit() and len(code) == 3:
                four_code = f"0{code}"
                # Kiểm tra xem đã có bản chuẩn 4 chữ số trong DB chưa
                existing_4 = col.find_one({"ma_de": four_code, "nam_thi": y})
                if existing_4:
                    # Đã có bản 4 chữ số -> Xóa bản 3 chữ số thừa này đi
                    col.delete_one({"_id": doc["_id"]})
                    cleaned_count += 1
                else:
                    # Chưa có bản 4 chữ số -> Cập nhật mã đề này thành 4 chữ số chuẩn
                    col.update_one({"_id": doc["_id"]}, {"$set": {"ma_de": four_code}})
                    cleaned_count += 1
                    
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"🧹 Đã dọn dẹp và chuẩn hóa {cleaned_count} mã đề trùng lặp về định dạng 4 chữ số chuẩn!"
    except Exception as e:
        return False, str(e)

def verify_all_answer_keys_in_year(mongo_uri, nam_thi):
    """Đánh dấu toàn bộ mã đề của năm thi này sang trạng thái 'da_xac_thuc' (🟢 ĐÃ DUYỆT / KHÓA BẢO VỆ)."""
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        res = col.update_many(
            {"nam_thi": str(nam_thi)},
            {"$set": {
                "trang_thai": "da_xac_thuc",
                "thoi_gian_duyet": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }}
        )
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"🛡️ Đã phê duyệt và khóa bảo vệ toàn bộ {res.modified_count} mã đề (Năm {nam_thi})!"
    except Exception as e:
        return False, str(e)

def delete_all_answer_keys_in_year(mongo_uri, nam_thi):
    """Xóa toàn bộ mã đề của năm thi này khỏi collection 'answer_keys'."""
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        res = col.delete_many({"nam_thi": str(nam_thi)})
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"Đã xóa {res.deleted_count} mã đề của năm {nam_thi} khỏi Ngân Hàng."
    except Exception as e:
        return False, str(e)

def delete_batch_from_db(mongo_uri, batch_id):
    """Xóa một đợt chấm khỏi 'grading_batches' và 'exam_results'."""
    if not mongo_uri or not batch_id:
        return False, "Thiếu thông tin"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        db['grading_batches'].delete_one({"batch_id": str(batch_id)})
        db['exam_results'].delete_many({"batch_id": str(batch_id)})
        get_all_batches_from_db.clear()
        get_batch_exam_results.clear()
        return True, f"Đã xóa hoàn toàn đợt chấm {batch_id}"
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=60, show_spinner=False)
def get_all_answer_keys_dataframe(mongo_uri, nam_thi=None):
    """Lấy toàn bộ đáp án của tất cả mã đề thành 1 DataFrame (có Cache trong 60s)."""
    if not mongo_uri:
        return pd.DataFrame()
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return pd.DataFrame()
        col = db['answer_keys']
        query = {"nam_thi": str(nam_thi)} if (nam_thi and nam_thi != "Tất cả") else {}
        docs = list(col.find(query))
        rows = []
        for doc in docs:
            m = doc.get("ma_de")
            y = doc.get("nam_thi")
            for it in doc.get("danh_sach_dap_an", []):
                rows.append({
                    "Mã Đề": m,
                    "Năm Thi": y,
                    "Phần": it.get("Phần"),
                    "Câu": it.get("Câu"),
                    "Ý": it.get("Ý", ""),
                    "Đáp Án": it.get("Đáp Án")
                })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def df_to_excel_bytes(df, sheet_name="Sheet1", index=False, index_label=None):
    """Xuất DataFrame ra bytes Excel cực nhanh có bộ đệm Cache của Streamlit, loại bỏ hoàn toàn độ trễ chạy lại."""
    if df is None or df.empty:
        return b""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=str(sheet_name)[:31], index=index, index_label=index_label)
    return buf.getvalue()

@st.cache_data(show_spinner=False)
def dict_to_multisheet_excel_bytes(sheet_dict):
    """Xuất nhiều Sheet ra bytes Excel cực nhanh có Cache."""
    if not sheet_dict:
        return b""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        for sname, df in sheet_dict.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=str(sname)[:31], index=False)
    return buf.getvalue()

# --- COLLECTION 2: solved_exams (Cache bài giải AI) ---
def get_solved_exam_cache(mongo_uri, ma_de, nam_thi, model_name):
    """Kiểm tra xem mã đề này đã được model AI giải trước đó chưa để tiết kiệm Token."""
    if not mongo_uri:
        return None
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return None
        col = db['solved_exams']
        doc = col.find_one({
            "ma_de": str(ma_de),
            "nam_thi": str(nam_thi),
            "model_ai": str(model_name)
        })
        if doc and "bai_lam_ai" in doc:
            return doc["bai_lam_ai"]
    except Exception:
        pass
    return None

def save_solved_exam_cache(mongo_uri, ma_de, nam_thi, model_name, ai_result, loai_tai_lieu="scan_image"):
    """Lưu bài giải của AI vào collection 'solved_exams' làm Cache."""
    if not mongo_uri or not ai_result:
        return
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return
        col = db['solved_exams']
        col.update_one(
            {"ma_de": str(ma_de), "nam_thi": str(nam_thi), "model_ai": str(model_name)},
            {"$set": {
                "ma_de": str(ma_de),
                "nam_thi": str(nam_thi),
                "model_ai": str(model_name),
                "loai_tai_lieu": loai_tai_lieu,
                "thoi_gian_giai": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "bai_lam_ai": ai_result
            }},
            upsert=True
        )
    except Exception:
        pass

def delete_solved_exam_cache(mongo_uri, ma_de=None, nam_thi=None):
    """Xóa bài giải trong collection 'solved_exams' để làm mới cache."""
    if not mongo_uri:
        return False, "Chưa cấu hình MONGODB_URI"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['solved_exams']
        query = {}
        if ma_de:
            query["ma_de"] = str(ma_de)
        if nam_thi:
            query["nam_thi"] = str(nam_thi)
        res = col.delete_many(query)
        return True, f"Đã làm mới Cache (đã xóa {res.deleted_count} bản ghi bài giải cũ)."
    except Exception as e:
        return False, str(e)

# --- COLLECTION 3: grading_batches (Đợt chấm thi) ---
def save_grading_batch(mongo_uri, batch_id, ten_dot_thi, nam_thi, model_name, summary_list):
    """Lưu thông tin đợt chấm thi hàng loạt vào collection 'grading_batches'."""
    if not mongo_uri or not summary_list:
        return False, "Không có dữ liệu đợt chấm"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['grading_batches']
        
        scores = []
        for item in summary_list:
            d = item.get("Điểm (Hệ 10)")
            if isinstance(d, (int, float)):
                scores.append(float(d))
                
        diem_tb = round(sum(scores) / len(scores), 2) if scores else None
        
        batch_doc = {
            "batch_id": str(batch_id),
            "ten_dot_thi": str(ten_dot_thi),
            "nam_thi": str(nam_thi),
            "model_ai": str(model_name),
            "tong_so_de": len(summary_list),
            "diem_trung_binh": diem_tb,
            "thoi_gian_cham": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "danh_sach_de": summary_list
        }
        col.insert_one(batch_doc)
        get_all_batches_from_db.clear()
        return True, "Đã lưu đợt chấm thi thành công"
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=120, show_spinner=False)
def get_all_batches_from_db(mongo_uri):
    """Lấy danh sách các đợt chấm thi đã lưu (có Cache trong RAM)."""
    if not mongo_uri:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['grading_batches']
        docs = list(col.find().sort("timestamp", -1))
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []

# --- COLLECTION 4: exam_results (Chi tiết từng bài thi theo batch) ---
def save_to_mongodb(mongo_uri, data, ma_de, nam_thi, ten_file="", batch_id="", loai_tai_lieu="scan_image", score=None, correct_count=0, total_count=0, p1_correct=0, p1_total=24, p2_correct=0, p2_total=24, comparison_data=None, model_name=""):
    """Lưu kết quả chi tiết từng bài thi vào collection 'exam_results'."""
    if not mongo_uri:
        return False, "Chưa cấu hình MONGODB_URI"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        collection = db['exam_results']
        
        chi_tiet = []
        if comparison_data is not None:
            if isinstance(comparison_data, pd.DataFrame):
                chi_tiet = comparison_data.to_dict(orient='records')
            elif isinstance(comparison_data, list):
                chi_tiet = comparison_data

        record = {
            "batch_id": str(batch_id),
            "ma_de": str(ma_de),
            "ten_file": str(ten_file),
            "nam_thi": str(nam_thi),
            "model_ai": str(model_name),
            "loai_tai_lieu": str(loai_tai_lieu),
            "trang_thai_doi_sanh": "da_doi_sanh" if (score is not None and total_count > 0) else "chua_doi_sanh",
            "diem_so": round(float(score), 2) if score is not None else None,
            "so_cau_dung": int(correct_count) if score is not None else None,
            "tong_so_cau": int(total_count),
            "ty_le_dung_phan_tram": round((correct_count / total_count * 100), 2) if (score is not None and total_count > 0) else None,
            "thong_ke_phan_1": {
                "so_cau_dung": int(p1_correct) if score is not None else None,
                "tong_so_cau": int(p1_total)
            },
            "thong_ke_phan_2": {
                "so_y_dung": int(p2_correct) if score is not None else None,
                "tong_so_y": int(p2_total)
            },
            "thoi_gian_cham": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "bai_lam_ai": data,
            "chi_tiet_doi_sanh": chi_tiet
        }
        
        result = collection.insert_one(record)
        get_batch_exam_results.clear()
        return True, str(result.inserted_id)
    except Exception as e:
        err_msg = str(e)
        if "TLSV1_ALERT_INTERNAL_ERROR" in err_msg or "ServerSelectionTimeoutError" in err_msg:
            return False, "Lỗi kết nối Atlas: IP hiện tại chưa được Whitelist trong 'Network Access' của MongoDB Atlas."
        return False, err_msg

@st.cache_data(ttl=120, show_spinner=False)
def get_batch_exam_results(mongo_uri, batch_id):
    """Lấy danh sách kết quả chi tiết của tất cả bài thi trong một batch (có Cache trong RAM)."""
    if not mongo_uri or not batch_id:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['exam_results']
        docs = list(col.find({"batch_id": str(batch_id)}))
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []

# --- HÀM TRÍCH XUẤT TOÀN DIỆN BÀI GIẢI VÀ ĐỐI SÁNH ---
def build_comparison_and_detail_df(ai_data, answer_key_df=None, ma_de_hien_tai="", file_name=""):
    """Trích xuất toàn bộ tất cả câu trả lời của AI và đối sánh với đáp án chuẩn (nếu có).
    Đảm bảo xuất đầy đủ từng câu hỏi và ý con ra file Excel."""
    results = []
    has_key = False
    df_filtered = pd.DataFrame()
    
    if answer_key_df is not None and not answer_key_df.empty:
        ma_de_str = str(ma_de_hien_tai).strip()
        ma_de_clean = ma_de_str.lstrip('0')
        answer_key_df['Mã Đề'] = answer_key_df['Mã Đề'].astype(str).str.strip()
        df_filtered = answer_key_df[
            (answer_key_df['Mã Đề'] == ma_de_str) | 
            (answer_key_df['Mã Đề'] == ma_de_clean)
        ]
        if not df_filtered.empty:
            has_key = True

    # 1. Trích xuất Phần 1 (24 câu Trắc nghiệm)
    p1_items = ai_data.get("phan_1", [])
    for item in p1_items:
        cau = item.get("cau_hoi")
        raw_p1 = str(item.get("dap_an", "")).strip().upper()
        # Chuẩn hóa chỉ lấy 1 ký tự A, B, C, D
        m_char = re.search(r'[A-D]', raw_p1)
        dap_an_ai = m_char.group(0) if m_char else raw_p1
        
        giai_thich = str(item.get("giai_thich", "")).strip()
        
        dap_an_chuan = "-"
        ket_qua = "Chưa đối sánh"
        if has_key:
            match = df_filtered[(df_filtered['Phần'] == 1) & (df_filtered['Câu'] == cau)]
            if not match.empty:
                raw_chuan = str(match.iloc[0]['Đáp Án']).strip().upper()
                m_chuan = re.search(r'[A-D]', raw_chuan)
                dap_an_chuan = m_chuan.group(0) if m_chuan else raw_chuan
                ket_qua = "✅ Đúng" if (dap_an_ai == dap_an_chuan) else "❌ Sai"
                
        results.append({
            "Mã Đề": ma_de_hien_tai,
            "Tên File": file_name,
            "Phần": "Phần I (Trắc nghiệm)",
            "Câu": f"Câu {cau}",
            "Ý": "",
            "AI Chọn": dap_an_ai,
            "Đáp Án Chuẩn": dap_an_chuan,
            "Kết Quả": ket_qua,
            "Giải Thích AI": giai_thich
        })

    # 2. Trích xuất Phần 2 (6 câu Đúng/Sai, mỗi câu 4 ý a, b, c, d)
    phan_2_names = {
        1: "Phần II.A (Chung) - Câu 1",
        2: "Phần II.A (Chung) - Câu 2",
        3: "Phần II.B1 (KHMT) - Câu 3",
        4: "Phần II.B1 (KHMT) - Câu 4",
        5: "Phần II.B2 (THUD) - Câu 5",
        6: "Phần II.B2 (THUD) - Câu 6"
    }
    p2_items = ai_data.get("phan_2", [])
    for item in p2_items:
        cau = item.get("cau_hoi")
        label_prefix = phan_2_names.get(cau, f"Phần II - Câu {cau}")
        for i, y in enumerate(['y_a', 'y_b', 'y_c', 'y_d']):
            raw_ai = str(item.get(y, "")).strip()
            y_label = chr(65 + i) # A, B, C, D
            giai_thich_y = str(item.get(f"giai_thich_{chr(97 + i)}", "")).strip()
            
            # Tự động tách nếu giá trị AI có chứa nội dung ngoặc đơn vd: "Sai (các máy tính...)"
            extracted_reason = ""
            m_paren = re.search(r'\((.*?)\)', raw_ai)
            if m_paren:
                extracted_reason = m_paren.group(1).strip()
                clean_ai = re.sub(r'\(.*?\)', '', raw_ai).strip()
            else:
                clean_ai = raw_ai
                
            clean_upper = clean_ai.upper()
            if any(kw in clean_upper for kw in ['ĐÚNG', 'DUNG', 'TRUE']) or clean_upper in ['D', 'Đ']:
                dap_an_ai = "Đúng"
            elif any(kw in clean_upper for kw in ['SAI', 'FALSE']) or clean_upper == 'S':
                dap_an_ai = "Sai"
            else:
                dap_an_ai = clean_ai.capitalize()
                
            # Cứu lời giải thích nếu giai_thich_y bị trống nhưng trong raw_ai có lý do
            if not giai_thich_y and extracted_reason:
                giai_thich_y = extracted_reason
                
            dap_an_chuan = "-"
            ket_qua = "Chưa đối sánh"
            if has_key:
                match = df_filtered[(df_filtered['Phần'] == 2) & (df_filtered['Câu'] == cau) & (df_filtered['Ý'] == y_label)]
                if not match.empty:
                    val_chuan = str(match.iloc[0]['Đáp Án']).strip().upper()
                    if any(kw in val_chuan for kw in ['ĐÚNG', 'DUNG', 'TRUE']) or val_chuan in ['D', 'Đ']:
                        dap_an_chuan = "Đúng"
                    elif any(kw in val_chuan for kw in ['SAI', 'FALSE']) or val_chuan == 'S':
                        dap_an_chuan = "Sai"
                    else:
                        dap_an_chuan = val_chuan.capitalize()
                        
                    ket_qua = "✅ Đúng" if (dap_an_ai == dap_an_chuan) else "❌ Sai"
                    
            results.append({
                "Mã Đề": ma_de_hien_tai,
                "Tên File": file_name,
                "Phần": label_prefix.split(" - ")[0],
                "Câu": label_prefix,
                "Ý": y_label,
                "AI Chọn": dap_an_ai,
                "Đáp Án Chuẩn": dap_an_chuan,
                "Kết Quả": ket_qua,
                "Giải Thích AI": giai_thich_y
            })

    df_res = pd.DataFrame(results)
    if not df_res.empty:
        df_res.index = range(1, len(df_res) + 1)
    return df_res, has_key

# --- GIAO DIỆN CHÍNH STREAMLIT ---
def main():
    st.title("🤖 Trợ Lý AI Chấm Thi Tin Học THPT 2025")
    st.caption("Hệ thống Generative AI tự động đọc đề thi scan/ảnh, giải đề độc lập, đối sánh đáp án và quản lý dữ liệu MongoDB.")
    st.markdown("---")
    
    # Đọc cấu hình bảo mật trực tiếp từ biến môi trường (.env)
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    mongo_uri = os.getenv("MONGODB_URI", "").strip()
    
    # Sidebar cấu hình thân thiện & an toàn (không lộ Key trên UI)
    with st.sidebar:
        st.header("⚙️ Cấu Hình Hệ Thống")
        
        if not gemini_api_key:
            st.error("⚠️ Chưa cấu hình GEMINI_API_KEY trong file .env!")
            
        st.markdown("---")
        st.subheader("🧠 Model AI")
        model_choice = st.selectbox(
            "Chọn Model Gemini",
            options=["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-3.7-flash", "gemini-3.5-flash"],
            index=0,
            help="Bản Pro có khả năng lập luận thuật toán và đọc đề scan tốt nhất; bản Flash có tốc độ nhanh hơn."
        )
        
        st.markdown("---")
        st.subheader("⚡ Tối Ưu Hệ Thống")
        use_cache = st.checkbox(
            "Sử dụng Cache bài giải (Tiết kiệm Token)", 
            value=True, 
            help="Nếu đề thi đã được AI giải trước đó, hệ thống sẽ lấy ngay từ MongoDB để không tốn chi phí gọi lại API."
        )
        if st.button("🧹 Làm Mới Cache Bài Giải", help="Xóa cache bài giải cũ trong MongoDB để ép AI giải lại và cập nhật đầy đủ lời giải thích mới nhất", use_container_width=True):
            if mongo_uri:
                ok_del, msg_del = delete_solved_exam_cache(mongo_uri)
                if ok_del:
                    st.success(msg_del)
                else:
                    st.error(msg_del)
        st.info("🤖 **100% Tự Động Hóa**:\nAI tự động đọc **Năm Thi** (2025, 2026...) & **Mã Đề** trực tiếp từ trang tiêu đề PDF đề thi và đáp án.")

    # TẠO TABS GIAO DIỆN CHUẨN ĐỒ ÁN
    tab_grad, tab_history, tab_keys = st.tabs([
        "🚀 Chấm Thi Tự Động (Batch Grader)",
        "📜 Lịch Sử Đợt Chấm Thi (MongoDB)",
        "🗄️ Ngân Hàng Đáp Án Chuẩn (Answer Keys)"
    ])

    # -------------------------------------------------------------------------
    # TAB 1: CHẤM THI TỰ ĐỘNG
    # -------------------------------------------------------------------------
    with tab_grad:
        st.subheader("📄 Tải Lên Đề Thi (PDF)")
        st.caption("💡 Hệ thống tự động nhận diện Mã Đề & Năm Thi từ đề thi, sau đó đối soát trực tiếp với **Ngân Hàng Đáp Án Chuẩn** trong MongoDB (quản lý tại Tab 3) mà không cần tải kèm file đáp án.")
        pdf_files = st.file_uploader(
            "Kéo thả 1 hoặc nhiều file PDF đề thi để bắt đầu chấm:", 
            type=['pdf'], 
            accept_multiple_files=True
        )

        if st.button("🚀 Bắt Đầu Chấm Thi Hàng Loạt", use_container_width=True, type="primary"):
            if not gemini_api_key:
                st.error("⚠️ Vui lòng cấu hình GEMINI_API_KEY trong file .env trước khi chấm thi!")
                return
                
            if not pdf_files:
                st.warning("⚠️ Vui lòng tải lên ít nhất 1 file PDF đề thi!")
                return
                
            now_dt = datetime.now()
            batch_id = f"BATCH_{now_dt.strftime('%Y%m%d_%H%M%S')}"
            ten_dot_thi = f"Đợt Chấm Ngày {now_dt.strftime('%d/%m/%Y - %H:%M')}"
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            total_files = len(pdf_files)
            all_results_summary = []
            all_details_records = []
            detected_batch_years = set()

            # Xử lý từng đề thi theo lô (Batch Processing)
            for idx, pdf_file in enumerate(pdf_files):
                try:
                    status_text.info(f"[{idx+1}/{total_files}] Đang chuẩn bị dữ liệu đề thi `{pdf_file.name}`...")
                    exam_text = extract_text_from_pdf(pdf_file)
                    pdf_file.seek(0)
                    pdf_bytes = pdf_file.getvalue() if hasattr(pdf_file, 'getvalue') else None
                    
                    # Bước 1: Tự động nhận diện Mã Đề và Năm Thi từ PDF
                    current_ma_de, current_nam_thi = detect_metadata_from_file_and_text(pdf_file, exam_text)
                    
                    st.markdown(f"### 📝 Đang xử lý: Mã đề **{current_ma_de}** | Năm thi: **{current_nam_thi}** (`{pdf_file.name}`)")
                    
                    if exam_text:
                        with st.expander(f"📄 Xem văn bản trích xuất từ PDF - Đề {current_ma_de}"):
                            st.text_area("Văn bản đọc từ file:", value=exam_text, height=180, disabled=True, key=f"raw_text_{idx}")
                    else:
                        st.info(f"📸 Đề thi `{pdf_file.name}` là tài liệu scan/ảnh. Đang dùng **AI Vision** đọc trực tiếp trang ảnh!")

                    # Bước 2: Kiểm tra Cache bài giải theo đúng Mã Đề và Năm Thi
                    ai_result = None
                    if use_cache and mongo_uri:
                        cached_ai = get_solved_exam_cache(mongo_uri, current_ma_de, current_nam_thi, model_choice)
                        if cached_ai:
                            # Kiểm tra độ đầy đủ của Cache: Phải có giải thích ở cả P1 và P2, không dính ngoặc đơn ở P2
                            p1_has_exp = any(bool(it.get("giai_thich")) for it in cached_ai.get("phan_1", []))
                            p2_has_exp = any(bool(it.get("giai_thich_a") or it.get("giai_thich_b")) for it in cached_ai.get("phan_2", []))
                            has_paren_leak = any(
                                '(' in str(it.get('y_a', '')) or '(' in str(it.get('y_b', '')) or '(' in str(it.get('y_c', '')) or '(' in str(it.get('y_d', ''))
                                for it in cached_ai.get("phan_2", [])
                            )
                            if p1_has_exp and p2_has_exp and not has_paren_leak:
                                ai_result = cached_ai
                                st.success(f"⚡ Đã lấy bài giải kèm Lời Giải Thích từ MongoDB Cache cho Đề {current_ma_de} (Năm {current_nam_thi})!")
                            else:
                                st.info(f"🔄 Bài giải trong Cache của Đề {current_ma_de} chưa chuẩn hóa (thiếu giải thích Phần II hoặc dính ký tự). Đang kích hoạt AI ({model_choice}) giải lại và làm mới Cache...")

                    # Nếu chưa có trong cache, gọi Gemini API
                    if ai_result is None:
                        status_text.info(f"[{idx+1}/{total_files}] AI ({model_choice}) đang đọc và giải đề thi mã {current_ma_de}...")
                        ai_result = call_gemini_api(gemini_api_key, exam_text, current_ma_de, current_nam_thi, pdf_bytes=pdf_bytes, model_name=model_choice)
                        
                        # Cập nhật lại năm thi và mã đề nếu AI phát hiện chính xác hơn từ hình ảnh scan
                        if isinstance(ai_result, dict):
                            if ai_result.get("nam_thi"):
                                current_nam_thi = str(ai_result["nam_thi"])
                            if ai_result.get("ma_de"):
                                current_ma_de = str(ai_result["ma_de"])
                                
                        # Lưu bài giải vào Cache MongoDB
                        if mongo_uri:
                            save_solved_exam_cache(mongo_uri, current_ma_de, current_nam_thi, model_choice, ai_result, loai_tai_lieu="scan_image" if not exam_text else "digital_text")
                    
                    detected_batch_years.add(current_nam_thi)

                    # Hiển thị JSON bài giải
                    with st.expander(f"🤖 Xem bài giải JSON của AI - Đề {current_ma_de} (Năm {current_nam_thi})"):
                        st.json(ai_result)
                        json_str = json.dumps(ai_result, ensure_ascii=False, indent=2)
                        st.download_button(
                            label=f"📥 Tải File JSON Bài Giải Đề {current_ma_de} (.json)",
                            data=json_str,
                            file_name=f"bai_giai_ai_{current_ma_de}_{current_nam_thi}.json",
                            mime="application/json",
                            key=f"dl_json_{current_ma_de}_{idx}"
                        )

                    # Bước 3: Tìm bảng đáp án tương ứng đúng Năm Thi này cho Đề hiện tại
                    current_key_df = pd.DataFrame()
                    key_source_note = ""

                    # 1. Khóa An Toàn: Kiểm tra bản ĐÃ DUYỆT trong MongoDB (Ưu tiên cao nhất)
                    if mongo_uri:
                        v_df = check_verified_answer_key(mongo_uri, current_ma_de, current_nam_thi)
                        if v_df is not None and not v_df.empty:
                            current_key_df = v_df
                            key_source_note = "🛡️ **Khóa An Toàn:** Đã ưu tiên đáp án chuẩn **ĐÃ DUYỆT** từ Ngân Hàng MongoDB"

                    # 2. Nếu chưa duyệt, lấy bản trong Ngân Hàng Đáp Án MongoDB
                    if current_key_df.empty and mongo_uri:
                        db_key = get_answer_keys_from_db(mongo_uri, nam_thi=current_nam_thi, target_codes=[current_ma_de])
                        if not db_key.empty:
                            current_key_df = db_key
                            key_source_note = "💡 Đã tự động lấy đáp án chuẩn từ Ngân Hàng MongoDB"

                    # 3. Hiển thị thông báo trạng thái tìm đáp án
                    if not current_key_df.empty:
                        st.success(f"{key_source_note} cho Đề {current_ma_de} (Năm {current_nam_thi})!")
                    else:
                        st.warning(f"⚠️ **Chưa có đáp án chuẩn cho Mã đề {current_ma_de} (Năm {current_nam_thi}) trong Ngân Hàng!**\n\n👉 Vui lòng vào **Tab 3 ('Ngân Hàng Đáp Án Chuẩn')** để nạp file đáp án.")

                    # Trích xuất toàn diện bài giải & Đối sánh
                    detail_df, has_key = build_comparison_and_detail_df(
                        ai_data=ai_result,
                        answer_key_df=current_key_df,
                        ma_de_hien_tai=current_ma_de,
                        file_name=pdf_file.name
                    )
                    
                    score = None
                    correct_count = 0
                    total_count = len(detail_df)
                    p1_correct, p1_total = 0, 24
                    p2_correct, p2_total = 0, 24
                    
                    if has_key and not detail_df.empty:
                        p1_df = detail_df[detail_df['Phần'] == "Phần I (Trắc nghiệm)"]
                        p2_df = detail_df[detail_df['Phần'] != "Phần I (Trắc nghiệm)"]
                        
                        p1_total = len(p1_df)
                        p1_correct = len(p1_df[p1_df['Kết Quả'] == '✅ Đúng'])
                        
                        p2_total = len(p2_df)
                        p2_correct = len(p2_df[p2_df['Kết Quả'] == '✅ Đúng'])
                        
                        correct_count = len(detail_df[detail_df['Kết Quả'] == '✅ Đúng'])
                        score = (correct_count / total_count) * 10 if total_count > 0 else 0
                        
                        st.success(f"🎯 Điểm số Đề {current_ma_de} (Năm {current_nam_thi}): **{score:.2f} / 10** (Đúng {correct_count}/{total_count} câu/ý)")
                    else:
                        st.success(f"✅ Đã giải xong toàn bộ câu hỏi Đề {current_ma_de} (Chưa đối sánh đáp án)")
                    
                    # Luôn ghi nhận vào bảng tổng kết (có cột Năm Thi tự động)
                    all_results_summary.append({
                        "Mã Đề": current_ma_de,
                        "Năm Thi": current_nam_thi,
                        "Tên File": pdf_file.name,
                        "Điểm (Hệ 10)": round(score, 2) if score is not None else "Chưa đối sánh",
                        "Số câu đúng": correct_count if score is not None else "-",
                        "Tổng số câu": total_count,
                        "Tỷ lệ đúng (%)": round((correct_count / total_count * 100), 2) if score is not None else "-",
                        "P1 Trắc nghiệm": f"{p1_correct}/{p1_total}" if score is not None else f"{p1_total} câu đã giải",
                        "P2 Đúng/Sai": f"{p2_correct}/{p2_total}" if score is not None else f"{p2_total} ý đã giải",
                        "Model AI": model_choice,
                        "Thời Gian Chấm": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    all_details_records.append(detail_df)
                    
                    # Hiển thị bảng chi tiết trên UI
                    with st.expander(f"🔍 Xem bảng chi tiết tất cả câu hỏi AI đã làm - Đề {current_ma_de}", expanded=True):
                        if has_key:
                            style_func = lambda val: 'color: green; font-weight: bold' if val == '✅ Đúng' else ('color: red; font-weight: bold' if val == '❌ Sai' else '')
                            if hasattr(detail_df.style, 'map'):
                                styled_df = detail_df.style.map(style_func, subset=['Kết Quả'])
                            else:
                                styled_df = detail_df.style.applymap(style_func, subset=['Kết Quả'])
                            st.dataframe(styled_df, use_container_width=True)
                        else:
                            st.dataframe(detail_df, use_container_width=True)

                        # Nút tải riêng cho đề thi này (Dùng Cache siêu tốc)
                        st.download_button(
                            label=f"📊 Tải Chi Tiết Đề {current_ma_de} (Excel .xlsx)",
                            data=df_to_excel_bytes(detail_df, sheet_name=f'Chi Tiết Đề {current_ma_de}', index=True, index_label='STT'),
                            file_name=f"chi_tiet_de_{current_ma_de}_{current_nam_thi}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_excel_single_{current_ma_de}_{idx}",
                            use_container_width=True
                        )

                    # Bước 4: Lưu trữ MongoDB theo đúng năm thi phát hiện
                    if mongo_uri:
                        saved, msg = save_to_mongodb(
                            mongo_uri=mongo_uri,
                            data=ai_result,
                            ma_de=current_ma_de,
                            nam_thi=current_nam_thi,
                            ten_file=pdf_file.name,
                            batch_id=batch_id,
                            loai_tai_lieu="scan_image" if not exam_text else "digital_text",
                            score=score,
                            correct_count=correct_count,
                            total_count=total_count,
                            p1_correct=p1_correct,
                            p1_total=p1_total,
                            p2_correct=p2_correct,
                            p2_total=p2_total,
                            comparison_data=detail_df,
                            model_name=model_choice
                        )
                        if saved:
                            st.caption(f"🍃 Đã lưu Đề {current_ma_de} (Năm {current_nam_thi}) vào MongoDB (ID: `{msg}`)!")
                        else:
                            st.warning(f"ℹ️ MongoDB: {msg}")

                    # Nghỉ giữa các đề nếu xử lý nhiều đề để đảm bảo an toàn Rate Limit
                    if idx < total_files - 1 and ai_result is None:
                        status_text.info("⏳ Nghỉ 10 giây trước khi sang đề tiếp theo...")
                        time.sleep(10)
                    
                    progress_bar.progress((idx + 1) / total_files)
                    
                except Exception as e:
                    st.error(f"❌ Lỗi khi xử lý đề {pdf_file.name}: {str(e)}")

            status_text.empty()
            
            # Lưu Đợt Chấm Thi vào Collection 'grading_batches'
            batch_year_label = ", ".join(sorted(list(detected_batch_years))) if detected_batch_years else "2025"
            if mongo_uri and all_results_summary:
                save_grading_batch(mongo_uri, batch_id=batch_id, ten_dot_thi=f"Đợt Chấm Năm {batch_year_label} ({now_dt.strftime('%d/%m/%Y %H:%M')})", nam_thi=batch_year_label, model_name=model_choice, summary_list=all_results_summary)

            # Bảng tổng kết và xuất báo cáo toàn diện ra file Excel đa Sheet
            if all_results_summary:
                st.markdown("---")
                st.header(f"🏆 KẾT QUẢ ĐỢT CHẤM: {ten_dot_thi}")
                st.caption(f"Mã đợt thi (Batch ID): `{batch_id}`")
                summary_df = pd.DataFrame(all_results_summary)
                st.dataframe(summary_df, use_container_width=True)
                
                # Tạo file Excel đa Sheet (.xlsx) với Sheet 1 'Chi Tiết Từng Câu Hỏi' đặt lên ĐẦU TIÊN
                output_excel = io.BytesIO()
                with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                    if all_details_records:
                        full_details_df = pd.concat(all_details_records, ignore_index=True)
                        full_details_df.index = range(1, len(full_details_df) + 1)
                        full_details_df.to_excel(writer, sheet_name='Chi Tiết Từng Câu Hỏi', index=True, index_label='STT')
                    summary_df.to_excel(writer, sheet_name='Tổng Hợp Điểm Số', index=False)
                        
                excel_bytes = output_excel.getvalue()
                
                st.download_button(
                    label="📥 Tải Toàn Bộ Báo Cáo Đợt Chấm (Excel .xlsx)",
                    data=excel_bytes,
                    file_name=f'bao_cao_cham_thi_{batch_id}.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    use_container_width=True,
                    type="primary"
                )

            st.balloons()
            st.success(f"🎉 Hoàn tất quy trình chấm {total_files} đề thi thành công!")

    # -------------------------------------------------------------------------
    # TAB 2: LỊCH SỬ ĐỢT CHẤM THI (COLLECTION: grading_batches & exam_results)
    # -------------------------------------------------------------------------
    with tab_history:
        st.subheader("📜 Quản Lý & Xem Lại Các Đợt Chấm Thi Trong MongoDB")
        st.caption("Xem lại lịch sử các đợt thi đã chấm, phân tích phổ điểm và tải lại báo cáo Excel cũ mà không tốn token.")
        
        if not mongo_uri:
            st.warning("⚠️ Chưa cấu hình MONGODB_URI trong file .env!")
        else:
            batches = get_all_batches_from_db(mongo_uri)
            if not batches:
                st.info("ℹ️ Chưa có đợt chấm thi nào được lưu trong cơ sở dữ liệu MongoDB.")
            else:
                # Hiển thị metrics tổng quan
                m1, m2, m3 = st.columns(3)
                m1.metric("Tổng Số Đợt Chấm", len(batches))
                tong_so_bai = sum(b.get("tong_so_de", 0) for b in batches)
                m2.metric("Tổng Số Bài Thi Đã Chấm", tong_so_bai)
                all_avg = [b.get("diem_trung_binh") for b in batches if b.get("diem_trung_binh") is not None]
                avg_val = round(sum(all_avg) / len(all_avg), 2) if all_avg else 0
                m3.metric("Điểm Trung Bình Toàn Hệ Thống", f"{avg_val} / 10")
                
                # Bảng tóm tắt các đợt chấm
                batch_rows = []
                for b in batches:
                    batch_rows.append({
                        "Mã Đợt (Batch ID)": b.get("batch_id"),
                        "Tên Đợt Thi": b.get("ten_dot_thi"),
                        "Năm Thi": b.get("nam_thi"),
                        "Model AI": b.get("model_ai"),
                        "Số Đề Thi": b.get("tong_so_de"),
                        "Điểm TB": b.get("diem_trung_binh") if b.get("diem_trung_binh") is not None else "N/A",
                        "Thời Gian Chấm": b.get("thoi_gian_cham")
                    })
                st.dataframe(pd.DataFrame(batch_rows), use_container_width=True)
                
                st.markdown("---")
                st.subheader("🔍 Chi Tiết Một Đợt Chấm & Tải Lại Báo Cáo")
                selected_batch_id = st.selectbox(
                    "Chọn Đợt Chấm Cần Xem Lại:",
                    options=[b.get("batch_id") for b in batches],
                    format_func=lambda x: f"{x} - {next((b.get('ten_dot_thi') for b in batches if b.get('batch_id') == x), '')}"
                )
                
                if selected_batch_id:
                    exam_docs = get_batch_exam_results(mongo_uri, selected_batch_id)
                    if exam_docs:
                        st.markdown(f"#### 📊 Tổng Hợp Điểm Số ({len(exam_docs)} bài thi):")
                        
                        hist_summaries = []
                        hist_details = []
                        for edoc in exam_docs:
                            hist_summaries.append({
                                "Mã Đề": edoc.get("ma_de"),
                                "Tên File": edoc.get("ten_file"),
                                "Điểm (Hệ 10)": edoc.get("diem_so"),
                                "Số câu đúng": edoc.get("so_cau_dung"),
                                "Tổng số câu": edoc.get("tong_so_cau"),
                                "Tỷ lệ đúng (%)": edoc.get("ty_le_dung_phan_tram"),
                                "P1 Trắc nghiệm": f"{edoc.get('thong_ke_phan_1', {}).get('so_cau_dung')}/{edoc.get('thong_ke_phan_1', {}).get('tong_so_cau')}",
                                "P2 Đúng/Sai": f"{edoc.get('thong_ke_phan_2', {}).get('so_y_dung')}/{edoc.get('thong_ke_phan_2', {}).get('tong_so_y')}",
                                "Thời Gian Chấm": edoc.get("thoi_gian_cham")
                            })
                            for row in edoc.get("chi_tiet_doi_sanh", []):
                                hist_details.append(row)
                                
                        hist_sum_df = pd.DataFrame(hist_summaries)
                        st.dataframe(hist_sum_df, use_container_width=True)
                        
                        sheet_dict = {}
                        if hist_details:
                            sheet_dict['Chi Tiết Từng Câu Hỏi'] = pd.DataFrame(hist_details)
                        sheet_dict['Tổng Hợp Điểm Số'] = hist_sum_df
                        
                        c_h1, c_h2 = st.columns([3, 1])
                        with c_h1:
                            st.download_button(
                                label=f"📥 Tải Toàn Bộ Báo Cáo Đợt Chấm (Excel .xlsx)",
                                data=dict_to_multisheet_excel_bytes(sheet_dict),
                                file_name=f'bao_cao_lich_su_{selected_batch_id}.xlsx',
                                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                type="primary",
                                use_container_width=True
                            )
                        with c_h2:
                            if st.button(f"🗑️ Xóa Đợt Chấm {selected_batch_id}", type="secondary", use_container_width=True):
                                ok_del, msg_del = delete_batch_from_db(mongo_uri, selected_batch_id)
                                if ok_del:
                                    st.success(msg_del)
                                    st.rerun()
                                else:
                                    st.error(msg_del)

                        st.markdown("---")
                        st.subheader(f"📝 Chi Tiết Từng Bài Thi & Bài Giải AI Trong Đợt `{selected_batch_id}`")
                        
                        if len(exam_docs) > 1:
                            exam_labels = [f"Đề {e.get('ma_de', 'N/A')} ({e.get('ten_file', '')}) — {e.get('diem_so', 0)}/10 điểm" for e in exam_docs]
                            view_mode = st.radio(
                                "Chế độ hiển thị bài thi:",
                                ["⚡ Từng bài thi (Khuyên dùng - Cực nhanh & nhẹ)", "📄 Tất cả bài thi cùng lúc"],
                                horizontal=True,
                                key=f"view_mode_{selected_batch_id}"
                            )
                            if view_mode.startswith("⚡"):
                                sel_idx = st.selectbox("Chọn bài thi cần xem chi tiết & giải thích:", range(len(exam_docs)), format_func=lambda i: exam_labels[i])
                                selected_docs = [(sel_idx, exam_docs[sel_idx])]
                            else:
                                selected_docs = list(enumerate(exam_docs))
                        else:
                            selected_docs = list(enumerate(exam_docs))

                        for idx_e, edoc in selected_docs:
                            e_ma_de = edoc.get("ma_de")
                            e_file = edoc.get("ten_file")
                            e_score = edoc.get("diem_so")
                            e_dung = edoc.get("so_cau_dung")
                            e_tong = edoc.get("tong_so_cau")
                            
                            with st.expander(f"📄 Đề {e_ma_de} (Tệp: {e_file}) — Điểm: {e_score}/10 (Đúng {e_dung}/{e_tong} câu/ý)", expanded=True):
                                chi_tiet_list = edoc.get("chi_tiet_doi_sanh", [])
                                if chi_tiet_list:
                                    df_e_detail = pd.DataFrame(chi_tiet_list)
                                    if not df_e_detail.empty:
                                        df_e_detail.index = range(1, len(df_e_detail) + 1)
                                    style_func = lambda val: 'color: green; font-weight: bold' if val == '✅ Đúng' else ('color: red; font-weight: bold' if val == '❌ Sai' else '')
                                    if hasattr(df_e_detail.style, 'map'):
                                        st.dataframe(df_e_detail.style.map(style_func, subset=['Kết Quả']), use_container_width=True)
                                    else:
                                        st.dataframe(df_e_detail.style.applymap(style_func, subset=['Kết Quả']), use_container_width=True)
                                    
                                    st.download_button(
                                        label=f"📊 Tải Chi Tiết Đề {e_ma_de} (Excel .xlsx)",
                                        data=df_to_excel_bytes(df_e_detail, sheet_name=f'Đề {e_ma_de}', index=True, index_label='STT'),
                                        file_name=f"chi_tiet_de_{e_ma_de}_{selected_batch_id}.xlsx",
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                        key=f"dl_hist_detail_{e_ma_de}_{idx_e}",
                                        use_container_width=True
                                    )

                                bai_lam_ai = edoc.get("bai_lam_ai")
                                if bai_lam_ai:
                                    st.markdown(f"**🤖 Bài Giải Gốc Của AI Đề {e_ma_de}:**")
                                    st.json(bai_lam_ai)
                                    json_ai_str = json.dumps(bai_lam_ai, ensure_ascii=False, indent=2)
                                    st.download_button(
                                        label=f"📥 Tải File JSON Bài Giải Đề {e_ma_de}",
                                        data=json_ai_str,
                                        file_name=f"bai_giai_ai_{e_ma_de}.json",
                                        mime="application/json",
                                        key=f"dl_hist_json_{e_ma_de}_{idx_e}"
                                    )

    # -------------------------------------------------------------------------
    # TAB 3: NGÂN HÀNG ĐÁP ÁN CHUẨN (COLLECTION: answer_keys)
    # -------------------------------------------------------------------------
    with tab_keys:
        st.subheader("🗄️ Ngân Hàng Đáp Án Chuẩn Của Bộ GD&ĐT")
        st.caption("Quản lý toàn bộ 48 mã đề theo định dạng Ma trận giống đề gốc của Bộ GD&ĐT. Dữ liệu được lưu vĩnh viễn trên MongoDB, hỗ trợ rà soát nhanh các câu bị mộc đỏ che và khóa bảo vệ 100%.")
        
        if not mongo_uri:
            st.warning("⚠️ Chưa cấu hình MONGODB_URI trong file .env!")
        else:
            all_keys_summary_check = get_all_answer_keys_summary(mongo_uri)
            has_existing_keys = len(all_keys_summary_check) > 0

            # ---------------------------------------------------------------
            # BƯỚC 1: NẠP FILE ĐÁP ÁN GỐC (PDF / EXCEL / CSV) - CHỈ LÀM 1 LẦN
            # ---------------------------------------------------------------
            with st.expander("📤 Nạp File Đáp Án Gốc Vào Ngân Hàng (PDF / Excel / CSV) — Chỉ Cần Làm 1 Lần", expanded=not has_existing_keys):
                st.caption("💡 Hệ thống tự liệt kê TẤT CẢ mã đề có trong file PDF (vd: 48 mã), bóc tách song song theo từng đợt để không bị cắt cụt, rồi lưu hết vào MongoDB. Các lần chấm sau không cần nạp lại file đáp án.")
                col_u1, col_u2 = st.columns([3, 1])
                with col_u1:
                    extra_key_file = st.file_uploader(
                        "Tải lên file Đáp án (PDF/Excel/CSV) để lưu vào ngân hàng:",
                        type=['pdf', 'csv', 'xlsx'],
                        key="extra_key_uploader"
                    )
                with col_u2:
                    custom_year = st.selectbox("Năm Thi Của File:", ["2025", "2026", "2027", "2028"], index=0)
                    allow_force = st.checkbox("Ghi đè cả mã đã duyệt", value=False, help="Chỉ tích nếu bạn muốn hủy khóa bảo vệ và ghi đè lại toàn bộ bằng file mới.")
                    
                if extra_key_file and st.button("🚀 Quét Toàn Bộ & Lưu Vào Ngân Hàng", type="primary"):
                    try:
                        df_ext = None
                        detected_year = custom_year
                        missing_codes = []
                        if extra_key_file.name.endswith('.csv'):
                            df_ext = pd.read_csv(extra_key_file, dtype={'Mã Đề': str})
                        elif extra_key_file.name.endswith('.xlsx'):
                            df_ext = pd.read_excel(extra_key_file, dtype={'Mã Đề': str})
                        elif extra_key_file.name.endswith('.pdf'):
                            if not gemini_api_key:
                                st.error("⚠️ Chưa cấu hình GEMINI_API_KEY!")
                                st.stop()
                            prog = st.progress(0.0)
                            prog_txt = st.empty()
                            def _cb(p, msg):
                                prog.progress(min(max(p, 0.0), 1.0))
                                prog_txt.info(msg)
                            df_ext, y_found, all_codes, missing_codes = parse_full_answer_key_pdf(
                                gemini_api_key, extra_key_file, model_name=model_choice, progress_cb=_cb
                            )
                            detected_year = custom_year if custom_year != "2025" else (y_found or custom_year)
                            st.info(f"📑 Phát hiện **{len(all_codes)} mã đề** trong file: {', '.join(all_codes)}")

                        if df_ext is None or df_ext.empty:
                            st.error("❌ Không bóc tách được dữ liệu đáp án từ file.")
                        else:
                            df_ext['Mã Đề'] = df_ext['Mã Đề'].map(normalize_ma_de)
                            ok, msg = save_answer_keys_to_db(mongo_uri, df_ext, nam_thi=detected_year, source_name=extra_key_file.name, allow_overwrite_verified=allow_force)
                            if ok:
                                get_all_answer_keys_dataframe.clear()
                                df_to_excel_bytes.clear()
                                st.success(f"🎉 {msg} (Năm {detected_year})")
                                if missing_codes:
                                    st.warning(f"⚠️ Các mã chưa đọc đủ 48 câu/ý (cần kiểm tra/sửa tay trong Ma Trận bên dưới): **{', '.join(missing_codes)}**")
                                st.rerun()
                            else:
                                st.error(f"❌ {msg}")
                    except Exception as e:
                        st.error(f"Lỗi: {e}")

            # ---------------------------------------------------------------
            # BƯỚC 2: MA TRẬN ĐÁP ÁN TOÀN BỘ (RÀ SOÁT, SỬA CHỮA & KHÓA BẢO VỆ)
            # ---------------------------------------------------------------
            st.markdown("---")
            c_head1, c_head2 = st.columns([2, 1])
            with c_head1:
                st.subheader("🧮 Ma Trận Đáp Án Toàn Bộ")
                st.caption("Bố cục chuẩn Bộ GD&ĐT: **hàng = câu/ý**, **cột = mã đề**. Phần I nhập A/B/C/D; Phần II nhập **Đ** (Đúng) hoặc **S** (Sai).")
            with c_head2:
                mat_year = st.selectbox("Chọn Năm Thi Cần Quản Lý:", ["2025", "2026", "2027", "2028"], index=0, key="matrix_year")

            df_year_all = get_all_answer_keys_dataframe(mongo_uri, nam_thi=mat_year)
            if df_year_all.empty:
                st.info(f"ℹ️ Chưa có dữ liệu đáp án năm {mat_year} trong MongoDB. Hãy mở rộng phần '📤 Nạp File Đáp Án Gốc' ở trên để nạp file PDF đáp án.")
            else:
                mat_orig = answer_df_to_matrix(df_year_all)
                summary_keys = get_all_answer_keys_summary(mongo_uri, nam_thi=mat_year)
                verified_codes = {normalize_ma_de(k.get("ma_de")) for k in summary_keys if k.get("trang_thai") == "da_xac_thuc"}
                all_matrix_codes = set(mat_orig.columns)
                num_total = len(all_matrix_codes)
                num_verified = len(verified_codes & all_matrix_codes)
                num_unverified = num_total - num_verified
                incomplete = [c for c in mat_orig.columns if (mat_orig[c] == "").sum() > 0 or len(mat_orig) < 48]

                # Metric thống kê trực quan
                m_c1, m_c2, m_c3, m_c4 = st.columns(4)
                m_c1.metric("Tổng Số Mã Đề", f"{num_total} mã")
                m_c2.metric("🟢 Đã Duyệt (Khóa An Toàn)", f"{num_verified} mã")
                m_c3.metric("🟡 Chưa Duyệt (Tự Động)", f"{num_unverified} mã")
                m_c4.metric("⚠️ Cần Rà Soát (Ô trống)", f"{len(incomplete)} mã")

                if incomplete:
                    st.warning(f"⚠️ Các mã đề còn ô trống (do mộc che hoặc trang scan mờ): **{', '.join(incomplete)}**. Vui lòng click trực tiếp vào ô tương ứng trong bảng bên dưới để gõ bổ sung!")

                # Bảng Ma trận st.data_editor hiển thị toàn cảnh 48 mã
                mat_edited = st.data_editor(
                    mat_orig,
                    use_container_width=True,
                    height=580,
                    key=f"matrix_editor_{mat_year}"
                )

                # THANH CÔNG CỤ HÀNH ĐỘNG DUY NHẤT (Action Bar)
                col_btn1, col_btn2 = st.columns([3, 2])
                with col_btn1:
                    if st.button(f"💾 Lưu & Khóa Phê Duyệt Toàn Bộ ({num_total} Mã Đề)", type="primary", use_container_width=True, key="btn_save_and_verify_all", help="Lưu ngay các ô vừa sửa vào MongoDB và chuyển tất cả các mã đề sang trạng thái 🟢 ĐÃ DUYỆT (Khóa an toàn vĩnh viễn chống ghi đè)"):
                        changed_codes = [c for c in mat_orig.columns if not mat_orig[c].astype(str).str.strip().str.upper().equals(mat_edited[c].astype(str).str.strip().str.upper())]
                        all_errors, saved = [], []
                        if changed_codes:
                            for c in changed_codes:
                                items_df, errs = matrix_column_to_items(mat_edited[c])
                                if errs:
                                    all_errors.append(f"{c}: {', '.join(errs[:5])}")
                                    continue
                                ok_u, _ = update_single_answer_key(mongo_uri, c, mat_year, items_df)
                                if ok_u:
                                    saved.append(c)

                        # Tự động phê duyệt & khóa toàn bộ các mã còn lại của năm thi
                        ok_v, msg_v = verify_all_answer_keys_in_year(mongo_uri, mat_year)
                        get_all_answer_keys_dataframe.clear()
                        df_to_excel_bytes.clear()

                        if all_errors:
                            st.error("❌ Một số ô có giá trị không hợp lệ: " + " | ".join(all_errors))
                        else:
                            if saved:
                                st.success(f"🛡️ Đã lưu {len(saved)} mã vừa sửa ({', '.join(saved)}) và Khóa Bảo Vệ toàn bộ {num_total} mã đề năm {mat_year} thành công!")
                            else:
                                st.success(f"🛡️ Đã Khóa Bảo Vệ & Phê Duyệt toàn bộ {num_total} mã đề năm {mat_year} thành công (100% ĐÃ DUYỆT)!")
                            st.rerun()

                with col_btn2:
                    st.download_button(
                        label="📊 Xuất Ma Trận (Excel)",
                        data=df_to_excel_bytes(mat_edited, sheet_name=f'MaTran_{mat_year}', index=True, index_label='Câu/Ý'),
                        file_name=f"ma_tran_dap_an_{mat_year}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="dl_matrix_xlsx"
                    )

                # CÔNG CỤ QUẢN TRỊ NÂNG CAO (Gọn gàng - Không chứa bảng thừa)
                with st.expander("⚙️ Tùy Chọn Quản Trị Nâng Cao (Xóa Trắng Dữ Liệu Năm / Dọn Mã Trùng)"):
                    c_sub1, c_sub2 = st.columns([1, 1])
                    with c_sub1:
                        if st.button("🧹 Dọn Dẹp Mã Trùng Lặp (Gộp 3 số về 4 số)", use_container_width=True):
                            ok_clean, msg_clean = cleanup_duplicate_answer_keys(mongo_uri, nam_thi=mat_year)
                            if ok_clean:
                                get_all_answer_keys_dataframe.clear()
                                df_to_excel_bytes.clear()
                                st.success(msg_clean)
                                st.rerun()
                            else:
                                st.error(msg_clean)
                    with c_sub2:
                        chk_confirm_del = st.checkbox(f"Xác nhận muốn xóa trắng toàn bộ đáp án năm {mat_year}", key="chk_del_all")
                        if chk_confirm_del:
                            if st.button(f"🗑️ Xóa Toàn Bộ Đáp Án Năm {mat_year}", type="secondary", use_container_width=True):
                                ok_d, msg_d = delete_all_answer_keys_in_year(mongo_uri, mat_year)
                                if ok_d:
                                    get_all_answer_keys_dataframe.clear()
                                    df_to_excel_bytes.clear()
                                    st.success(msg_d)
                                    st.rerun()
                                else:
                                    st.error(msg_d)

if __name__ == "__main__":
    main()

