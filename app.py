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
1. PHẦN I (Câu 1 đến 24): Trắc nghiệm 4 phương án, chọn 1 đáp án đúng (A, B, C hoặc D).
2. PHẦN II (Gồm 6 câu hỏi Đúng/Sai, mỗi câu có 4 ý a, b, c, d):
   - A. Phần chung (cho tất cả thí sinh):
     + Câu 1: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai')
     + Câu 2: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai')
   - B. Phần riêng:
     + B1. Khoa học máy tính:
       * Câu 3: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai')
       * Câu 4: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai')
     + B2. Tin học ứng dụng:
       * Câu 5: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai')
       * Câu 6: ý a, b, c, d (Đánh giá 'Đúng' hoặc 'Sai')
*(Lưu ý: Môn Tin học KHÔNG CÓ Phần III).*

QUY TẮC:
- Hãy giải đầy đủ cả 24 câu Phần I và toàn bộ 6 câu Phần II (gồm cả Câu 1, 2 chung và Câu 3, 4 KHMT, Câu 5, 6 THUD).
- Chỉ trả về JSON thuần tuân thủ đúng Schema siêu nhẹ (không viết văn bản giải thích dông dài để tối ưu tốc độ và không bao giờ bị tràn token)."""

# --- SCHEMA JSON ĐẦU RA ---
class Phan1(typing.TypedDict):
    cau_hoi: int
    dap_an: str

class Phan2CauHoi(typing.TypedDict):
    cau_hoi: int  # 1 đến 6
    y_a: str  # 'Đúng' hoặc 'Sai'
    y_b: str  # 'Đúng' hoặc 'Sai'
    y_c: str  # 'Đúng' hoặc 'Sai'
    y_d: str  # 'Đúng' hoặc 'Sai'

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
        for m in re.finditer(r'\{[^{}]*?"cau_hoi"\s*:\s*(\d+)[^{}]*?"dap_an"\s*:\s*"([A-Da-d])"[^{}]*?\}', resp_text):
            phan_1.append({
                "cau_hoi": int(m.group(1)),
                "dap_an": m.group(2).upper()
            })
            
        phan_2 = []
        for m in re.finditer(
            r'\{[^{}]*?"cau_hoi"\s*:\s*(\d+)[^{}]*?"y_a"\s*:\s*"([^"]+)"[^{}]*?"y_b"\s*:\s*"([^"]+)"[^{}]*?"y_c"\s*:\s*"([^"]+)"[^{}]*?"y_d"\s*:\s*"([^"]+)"[^{}]*?\}',
            resp_text, re.DOTALL
        ):
            phan_2.append({
                "cau_hoi": int(m.group(1)),
                "y_a": m.group(2).strip(),
                "y_b": m.group(3).strip(),
                "y_c": m.group(4).strip(),
                "y_d": m.group(5).strip()
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
            max_output_tokens=8192
        )
    )
    
    pdf_bytes = pdf_file.getvalue() if hasattr(pdf_file, 'getvalue') else None
    if not pdf_bytes and isinstance(pdf_file, str):
        with open(pdf_file, 'rb') as f:
            pdf_bytes = f.read()
            
    if not pdf_bytes:
        return pd.DataFrame()

    pdf_part = {
        "mime_type": "application/pdf",
        "data": pdf_bytes
    }
    
    code_filter_instruction = ""
    if target_codes:
        code_filter_instruction = f"- Tập trung bóc tách chính xác các mã đề đang chấm: {', '.join(target_codes)} (và các mã đề khác nếu có)."
    
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
  "0503": {{
    "p1": ["D", "B", "A", "C", "D", "C", "B", "C", "A", "B", "A", "D", "D", "D", "B", "D", "C", "C", "C", "B", "B", "B", "C", "C"],
    "p2": [
      ["S", "D", "S", "D"],
      ["S", "D", "S", "D"],
      ["D", "S", "D", "S"],
      ["S", "S", "D", "D"],
      ["D", "D", "S", "S"],
      ["D", "S", "S", "D"]
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
    
    rows_data = []
    y_labels = ['A', 'B', 'C', 'D']
    
    for ma_de, content in data.items():
        ma_de_str = str(ma_de).strip()
        ma_de_variants = [ma_de_str]
        if ma_de_str.startswith('0') and len(ma_de_str) == 4:
            ma_de_variants.append(ma_de_str.lstrip('0'))
            
        p1 = content.get("p1", [])
        p2 = content.get("p2", [])
        
        for variant in ma_de_variants:
            for idx, ans in enumerate(p1):
                rows_data.append({
                    "Mã Đề": variant,
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
                        "Mã Đề": variant,
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

# ==============================================================================
# HỆ THỐNG QUẢN LÝ CƠ SỞ DỮ LIỆU MONGODB (4 COLLECTIONS CHUẨN ĐỒ ÁN)
# 1. answer_keys: Ngân hàng đáp án chuẩn của Bộ GD&ĐT
# 2. solved_exams: Bộ nhớ đệm (Cache) bài giải của AI để tiết kiệm Token
# 3. grading_batches: Quản lý theo từng Đợt thi / Ca chấm thi hàng loạt
# 4. exam_results: Kết quả chi tiết từng bài thi & đối sánh điểm
# ==============================================================================

def get_mongo_db(mongo_uri):
    """Khởi tạo kết nối MongoDB an toàn với timeout ngắn tránh treo UI."""
    if not mongo_uri:
        return None
    try:
        client = MongoClient(
            mongo_uri,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=3000
        )
        return client['ai_exam_grader']
    except Exception:
        return None

# --- COLLECTION 1: answer_keys ---
def save_answer_keys_to_db(mongo_uri, df_answers, nam_thi="2025", source_name=""):
    """Lưu bảng đáp án chuẩn bóc tách được vào collection 'answer_keys'."""
    if not mongo_uri or df_answers is None or df_answers.empty:
        return False, "Không có dữ liệu đáp án để lưu"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        count = 0
        for ma_de, group in df_answers.groupby("Mã Đề"):
            ma_de_str = str(ma_de).strip()
            items = group[['Phần', 'Câu', 'Ý', 'Đáp Án']].to_dict(orient='records')
            col.update_one(
                {"ma_de": ma_de_str, "nam_thi": str(nam_thi)},
                {"$set": {
                    "ma_de": ma_de_str,
                    "nam_thi": str(nam_thi),
                    "nguon_file": str(source_name),
                    "so_cau_hoi": len(items),
                    "thoi_gian_luu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "danh_sach_dap_an": items
                }},
                upsert=True
            )
            count += 1
        return True, f"Đã đồng bộ {count} mã đề vào ngân hàng đáp án 'answer_keys'"
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

def get_all_answer_keys_summary(mongo_uri, nam_thi=None):
    """Lấy danh sách tóm tắt tất cả các mã đề đáp án đang có trong ngân hàng."""
    if not mongo_uri:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['answer_keys']
        query = {"nam_thi": str(nam_thi)} if (nam_thi and nam_thi != "Tất cả") else {}
        return list(col.find(query, {"ma_de": 1, "nam_thi": 1, "so_cau_hoi": 1, "thoi_gian_luu": 1, "nguon_file": 1}))
    except Exception:
        return []

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
        return True, "Đã lưu đợt chấm thi thành công"
    except Exception as e:
        return False, str(e)

def get_all_batches_from_db(mongo_uri):
    """Lấy danh sách các đợt chấm thi đã lưu."""
    if not mongo_uri:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['grading_batches']
        return list(col.find().sort("timestamp", -1))
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
        return True, str(result.inserted_id)
    except Exception as e:
        err_msg = str(e)
        if "TLSV1_ALERT_INTERNAL_ERROR" in err_msg or "ServerSelectionTimeoutError" in err_msg:
            return False, "Lỗi kết nối Atlas: IP hiện tại chưa được Whitelist trong 'Network Access' của MongoDB Atlas."
        return False, err_msg

def get_batch_exam_results(mongo_uri, batch_id):
    """Lấy danh sách kết quả chi tiết của tất cả bài thi trong một batch."""
    if not mongo_uri or not batch_id:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['exam_results']
        return list(col.find({"batch_id": str(batch_id)}))
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
        dap_an_ai = str(item.get("dap_an", "")).strip().upper()
        
        dap_an_chuan = "-"
        ket_qua = "Chưa đối sánh"
        if has_key:
            match = df_filtered[(df_filtered['Phần'] == 1) & (df_filtered['Câu'] == cau)]
            if not match.empty:
                dap_an_chuan = str(match.iloc[0]['Đáp Án']).strip().upper()
                ket_qua = "✅ Đúng" if (dap_an_ai == dap_an_chuan) else "❌ Sai"
                
        results.append({
            "Mã Đề": ma_de_hien_tai,
            "Tên File": file_name,
            "Phần": "Phần I (Trắc nghiệm)",
            "Câu": f"Câu {cau}",
            "Ý": "",
            "AI Chọn": dap_an_ai,
            "Đáp Án Chuẩn": dap_an_chuan,
            "Kết Quả": ket_qua
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
            dap_an_ai = str(item.get(y, "")).strip().capitalize()
            y_label = chr(65 + i) # A, B, C, D
            
            dap_an_chuan = "-"
            ket_qua = "Chưa đối sánh"
            if has_key:
                match = df_filtered[(df_filtered['Phần'] == 2) & (df_filtered['Câu'] == cau) & (df_filtered['Ý'] == y_label)]
                if not match.empty:
                    dap_an_chuan = str(match.iloc[0]['Đáp Án']).strip().capitalize()
                    ket_qua = "✅ Đúng" if (dap_an_ai == dap_an_chuan) else "❌ Sai"
                    
            results.append({
                "Mã Đề": ma_de_hien_tai,
                "Tên File": file_name,
                "Phần": label_prefix.split(" - ")[0],
                "Câu": label_prefix,
                "Ý": y_label,
                "AI Chọn": dap_an_ai,
                "Đáp Án Chuẩn": dap_an_chuan,
                "Kết Quả": ket_qua
            })

    return pd.DataFrame(results), has_key

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
        
        # Trạng thái kết nối bảo mật
        if gemini_api_key:
            st.success("🔒 Gemini API: Đã nạp từ .env")
        else:
            st.error("⚠️ Chưa có GEMINI_API_KEY trong file .env!")
            
        if mongo_uri:
            st.success("🔒 MongoDB: Đã nạp từ .env")
        else:
            st.info("ℹ️ MongoDB: Chưa cấu hình (Tùy chọn)")
            
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
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📄 Tải Lên Đề Thi (PDF)")
            pdf_files = st.file_uploader(
                "Kéo thả 1 hoặc nhiều file PDF đề thi", 
                type=['pdf'], 
                accept_multiple_files=True
            )
            
        with col2:
            st.subheader("📊 Đáp Án Chuẩn Của Bộ")
            answer_file = st.file_uploader(
                "Kéo thả file Đáp án (PDF ma trận, CSV hoặc Excel .xlsx)", 
                type=['pdf', 'csv', 'xlsx'],
                help="Nếu không tải file đáp án, hệ thống sẽ tự động tìm trong Ngân Hàng Đáp Án MongoDB để chấm."
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
            
            # Thu thập các mã đề từ danh sách file đề thi tải lên
            target_codes = []
            for f in pdf_files:
                m = re.search(r'\d{3,4}', f.name)
                if m:
                    target_codes.append(m.group())
            target_codes = sorted(list(set(target_codes)))
            
            # Đọc hoặc nạp đáp án chuẩn
            df_answers = None
            detected_key_year = "2025"
            if answer_file:
                status_text.info("Đang nạp và phân tích dữ liệu Đáp án chuẩn...")
                try:
                    if answer_file.name.endswith('.csv'):
                        df_answers = pd.read_csv(answer_file)
                    elif answer_file.name.endswith('.xlsx'):
                        df_answers = pd.read_excel(answer_file)
                    elif answer_file.name.endswith('.pdf'):
                        df_answers, detected_key_year = parse_answer_key_pdf(gemini_api_key, answer_file, target_codes=target_codes, model_name=model_choice)
                    
                    # Trích xuất năm thi từ tên file nếu có
                    m_y_ans = re.search(r'202[4-9]', answer_file.name)
                    if m_y_ans:
                        detected_key_year = m_y_ans.group(0)

                    if df_answers is not None and not df_answers.empty:
                        with st.expander(f"📋 Xem Bảng Đáp Án Chuẩn (Năm thi phát hiện: {detected_key_year})"):
                            st.dataframe(df_answers, use_container_width=True)
                        # Tự động lưu vào Ngân Hàng Đáp Án MongoDB theo đúng năm thi phát hiện được
                        if mongo_uri:
                            ok_save, msg_save = save_answer_keys_to_db(mongo_uri, df_answers, nam_thi=detected_key_year, source_name=answer_file.name)
                            if ok_save:
                                st.caption(f"🍃 {msg_save} (Năm {detected_key_year})")
                    else:
                        st.warning("Không thể trích xuất được bảng đáp án từ file đã tải lên.")
                except Exception as e:
                    st.error(f"Lỗi khi đọc file đáp án: {e}")

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
                            ai_result = cached_ai
                            st.success(f"⚡ Đã lấy bài giải có sẵn từ MongoDB Cache cho Đề {current_ma_de} (Năm {current_nam_thi})!")

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

                    # Bước 3: Tìm bảng đáp án tương ứng đúng Năm Thi này
                    exam_answers_df = df_answers
                    # Nếu không upload file đáp án, tự tìm trong MongoDB theo đúng Năm Thi phát hiện
                    if (exam_answers_df is None or exam_answers_df.empty) and mongo_uri:
                        exam_answers_df = get_answer_keys_from_db(mongo_uri, nam_thi=current_nam_thi, target_codes=[current_ma_de])
                        if not exam_answers_df.empty:
                            st.info(f"💡 Đã tự động lấy đáp án chuẩn Đề {current_ma_de} Năm {current_nam_thi} từ Ngân Hàng MongoDB!")

                    # Trích xuất toàn diện bài giải & Đối sánh
                    detail_df, has_key = build_comparison_and_detail_df(
                        ai_data=ai_result,
                        answer_key_df=exam_answers_df,
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
                
                # Tạo file Excel đa Sheet (.xlsx)
                output_excel = io.BytesIO()
                with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                    summary_df.to_excel(writer, sheet_name='Tổng Hợp Điểm Số', index=False)
                    if all_details_records:
                        full_details_df = pd.concat(all_details_records, ignore_index=True)
                        full_details_df.to_excel(writer, sheet_name='Chi Tiết Từng Câu Hỏi', index=False)
                        
                excel_bytes = output_excel.getvalue()
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(
                        label="📊 Tải Báo Cáo Toàn Diện (Excel .xlsx - 2 Sheet đầy đủ chi tiết)",
                        data=excel_bytes,
                        file_name=f'bao_cao_cham_thi_{batch_id}.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        use_container_width=True,
                        type="primary"
                    )
                with col_d2:
                    csv_export = summary_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Tải Bảng Điểm Tổng Hợp (CSV)",
                        data=csv_export,
                        file_name=f'bang_diem_{batch_id}.csv',
                        mime='text/csv',
                        use_container_width=True
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
                        st.write(f"Đợt này có **{len(exam_docs)} bài thi** được lưu chi tiết:")
                        
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
                        
                        # Xuất lại file Excel của đợt này
                        out_hist_excel = io.BytesIO()
                        with pd.ExcelWriter(out_hist_excel, engine='openpyxl') as writer:
                            hist_sum_df.to_excel(writer, sheet_name='Tổng Hợp Điểm Số', index=False)
                            if hist_details:
                                pd.DataFrame(hist_details).to_excel(writer, sheet_name='Chi Tiết Từng Câu Hỏi', index=False)
                        
                        st.download_button(
                            label=f"📥 Tải Lại Báo Cáo Excel Đầy Đủ Của Đợt {selected_batch_id}",
                            data=out_hist_excel.getvalue(),
                            file_name=f'bao_cao_lich_su_{selected_batch_id}.xlsx',
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            type="primary"
                        )

    # -------------------------------------------------------------------------
    # TAB 3: NGÂN HÀNG ĐÁP ÁN CHUẨN (COLLECTION: answer_keys)
    # -------------------------------------------------------------------------
    with tab_keys:
        st.subheader("🗄️ Ngân Hàng Đáp Án Chuẩn Của Bộ GD&ĐT")
        st.caption("Quản lý danh mục đáp án chuẩn theo từng năm và mã đề được lưu trữ vĩnh viễn trong MongoDB.")
        
        if not mongo_uri:
            st.warning("⚠️ Chưa cấu hình MONGODB_URI trong file .env!")
        else:
            col_filter, _ = st.columns([1, 2])
            with col_filter:
                filter_year = st.selectbox("Lọc Theo Năm Thi:", ["Tất cả", "2025", "2026", "2027", "2028"], index=0)
            
            keys_list = get_all_answer_keys_summary(mongo_uri, nam_thi=filter_year)
            if keys_list:
                st.success(f"✅ Hiện có **{len(keys_list)} mã đề** trong Ngân Hàng Đáp Án.")
                keys_df = pd.DataFrame([
                    {
                        "Mã Đề": k.get("ma_de"),
                        "Năm Thi": k.get("nam_thi"),
                        "Số Câu/Ý": k.get("so_cau_hoi"),
                        "Nguồn File": k.get("nguon_file"),
                        "Ngày Cập Nhật": k.get("thoi_gian_luu")
                    } for k in keys_list
                ])
                st.dataframe(keys_df, use_container_width=True)
            else:
                st.info("ℹ️ Chưa có mã đề nào trong Ngân Hàng Đáp Án theo bộ lọc.")
                
            st.markdown("---")
            st.subheader("📤 Nạp Thêm / Cập Nhật Bảng Đáp Án Vào Ngân Hàng")
            col_u1, col_u2 = st.columns([2, 1])
            with col_u1:
                extra_key_file = st.file_uploader(
                    "Tải lên file Đáp án (PDF/Excel/CSV) để lưu vào ngân hàng:",
                    type=['pdf', 'csv', 'xlsx'],
                    key="extra_key_uploader"
                )
            with col_u2:
                custom_year = st.selectbox("Năm Thi Của File:", ["2025", "2026", "2027", "2028"], index=0)
                
            if extra_key_file and st.button("Lưu Vào Ngân Hàng Đáp Án"):
                try:
                    df_ext = None
                    detected_year = custom_year
                    if extra_key_file.name.endswith('.csv'):
                        df_ext = pd.read_csv(extra_key_file)
                    elif extra_key_file.name.endswith('.xlsx'):
                        df_ext = pd.read_excel(extra_key_file)
                    elif extra_key_file.name.endswith('.pdf'):
                        df_ext, detected_year = parse_answer_key_pdf(gemini_api_key, extra_key_file, model_name=model_choice)
                    
                    ok, msg = save_answer_keys_to_db(mongo_uri, df_ext, nam_thi=detected_year, source_name=extra_key_file.name)
                    if ok:
                        st.success(f"🎉 {msg} (Năm {detected_year})")
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}")
                except Exception as e:
                    st.error(f"Lỗi: {e}")

if __name__ == "__main__":
    main()

