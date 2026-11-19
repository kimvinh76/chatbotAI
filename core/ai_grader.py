"""
=============================================================================
MODULE: core/ai_grader.py
CHỨC NĂNG:
- Định nghĩa System Prompt chuẩn chuyên gia Tin học THPT Bộ GD&ĐT.
- Định nghĩa Schema đầu ra JSON (TypedDict) cho Phần I và Phần II.
- Bộ phân tích JSON tự phục hồi (robust_exam_json_parser).
- Chiến lược giải đề 2 Pha (Divide-and-Conquer) chuẩn hóa cho mọi mô hình (cả Flash và Pro):
  + Pha 1: 24 câu trắc nghiệm Phần I kèm giải thích + trích xuất mã đề, năm thi.
  + Pha 2: 6 câu Đúng/Sai Phần II kèm giải thích ngắn gọn bám sát đề thi.
- Lớp vá câu thiếu (Gap-Fill): Tự động phát hiện và truy vấn lại các câu/ý thiếu hoặc thiếu giải thích kèm ngữ cảnh đề thi.
- Bóc tách file PDF bảng ma trận đáp án gốc của Bộ GD&ĐT (parse_answer_key_pdf, parse_full_answer_key_pdf).
=============================================================================
"""

import json
import re
import time
import typing_extensions as typing
import pandas as pd
import google.generativeai as genai
from core.excel_utils import normalize_ma_de


# --- SYSTEM PROMPT ---
SYSTEM_PROMPT = """Bạn là chuyên gia giáo dục môn Tin học THPT. Nhiệm vụ của bạn là giải chính xác toàn bộ các câu hỏi trong đề thi Tốt nghiệp THPT môn Tin học chuẩn Bộ GD&ĐT.

CẤU TRÚC ĐỀ THI TIN HỌC:
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
- Phần I: dap_an chỉ là 1 ký tự duy nhất ('A', 'B', 'C' hoặc 'D'). giai_thich chứa lời giải thích ngắn gọn dưới 35 từ.
- Phần II: Với mỗi ý (a, b, c, d), trường dap_an BẮT BUỘC là 'Đúng' hoặc 'Sai'. Trường giai_thich BẮT BUỘC điền lời giải thích ngắn gọn (15-30 từ) phân tích bản chất kỹ thuật bám sát nội dung câu hỏi trong đề thi, TUYỆT ĐỐI KHÔNG ĐỂ TRỐNG!
- YÊU CẦU CHẤT LƯỢNG GIẢI THÍCH HỌC THUẬT:
  + TUYỆT ĐỐI KHÔNG giải thích sáo rỗng chung chung (CẤM các câu như: 'Căn cứ kiến thức SGK Tin học 12', 'Theo chuẩn GDPT 2018', 'Đây là đáp án đúng', 'Khẳng định này là đúng theo kiến thức Tin học').
  + Lời giải thích BẮT BUỘC phải đi thẳng vào bản chất kỹ thuật của câu hỏi:
    * Với lý thuyết/mạng/phần cứng: Nêu rõ định nghĩa, vai trò thiết bị, tầng giao thức (TCP, IP, Router, Switch, RAM, ROM, TLS...).
    * Với thuật toán/mã nguồn Python/C++: Mô phỏng từng bước (dry-run) biến số, điều kiện vòng lặp, giá trị trả về của hàm.
    * Với cơ sở dữ liệu SQL: Phân tích cú pháp mệnh đề (SELECT, WHERE, JOIN, GROUP BY, HAVING) hoặc tính chất khóa chính/ngoại.
    * Với các mệnh đề 'Sai': Chỉ rõ điểm sai logic/cú pháp và giải thích vì sao nhận định đó không chính xác.
- Trả về JSON thuần tuân thủ đúng Schema."""


# --- SCHEMA JSON ĐẦU RA (TYPEDDICT CHO GEMINI API) ---

# Cấu trúc 1 câu trắc nghiệm Phần I (Câu 1 đến 24 - bắt buộc đủ số câu, đáp án A/B/C/D và giải thích)
class CauHoiPhan1(typing.TypedDict):
    cau_hoi: int
    dap_an: typing.Literal["A", "B", "C", "D"]
    giai_thich: str

# Cấu trúc từng ý Đúng/Sai Phần II (bắt buộc gồm đáp án Đúng/Sai và lời giải thích kỹ thuật)
class YDungSai(typing.TypedDict):
    dap_an: typing.Literal["Đúng", "Sai"]
    giai_thich: str

# Cấu trúc 1 câu Đúng/Sai Phần II (Câu 1 đến 6, mỗi câu 4 ý a,b,c,d gắn liền giải thích)
class CauHoiPhan2(typing.TypedDict):
    cau_hoi: int       # Số thứ tự câu (1..6)
    y_a: YDungSai
    y_b: YDungSai
    y_c: YDungSai
    y_d: YDungSai

# Cấu trúc câu phẳng (Flat) sau khi chuẩn hóa để lưu DB và hiển thị bảng đối sánh
class CauHoiPhan2Flat(typing.TypedDict, total=False):
    cau_hoi: int
    y_a: str
    y_b: str
    y_c: str
    y_d: str
    giai_thich_a: str
    giai_thich_b: str
    giai_thich_c: str
    giai_thich_d: str

# Schema hợp nhất toàn bài thi (kết quả hoàn chỉnh sau khi ghép Pha 1 + Pha 2)
class BaiGiaiDeThi(typing.TypedDict, total=False):
    nam_thi: int
    ma_de: str
    phan_1: list[CauHoiPhan1]
    phan_2: list[CauHoiPhan2Flat]

# Schema gọi API Pha 1: Bóc tách mã đề, năm thi và giải duy nhất 24 câu Phần I (bắt buộc đầy đủ)
class BaiGiaiPhan1(typing.TypedDict):
    nam_thi: int
    ma_de: str
    phan_1: list[CauHoiPhan1]

# Schema gọi API Pha 2: Giải duy nhất 6 câu Phần II (áp dụng ràng buộc chặt chẽ bắt buộc điền Đúng/Sai và Giải thích)
class BaiGiaiPhan2(typing.TypedDict):
    phan_2: list[CauHoiPhan2]

# Bí danh tương thích ngược
Phan1 = CauHoiPhan1
Phan2CauHoi = CauHoiPhan2
DeThiResponse = BaiGiaiDeThi
Phan1OnlyResponse = BaiGiaiPhan1
Phan2OnlyResponse = BaiGiaiPhan2


def _flatten_p2_item(it):
    """
    Chuẩn hóa 1 câu Phần II:
    Nếu AI trả về dạng cấu trúc cặp:
      y_a = {"dap_an": "Đúng", "giai_thich": "..."}
    thì tự động làm phẳng thành:
      y_a = "Đúng"
      giai_thich_a = "..."
    Đồng thời vẫn tương thích ngược 100% nếu AI trả về dạng phẳng cũ.
    """
    if not isinstance(it, dict):
        return it
    out = dict(it)
    for k in ['a', 'b', 'c', 'd']:
        v = it.get(f'y_{k}')
        if isinstance(v, dict):
            out[f'y_{k}'] = str(v.get('dap_an', '')).strip()
            if v.get('giai_thich'):
                out[f'giai_thich_{k}'] = str(v.get('giai_thich', '')).strip()
    return out


def robust_exam_json_parser(resp_text):
    """
    Phân tích JSON bài giải đề thi với cơ chế tự phục hồi bằng Regex nếu chuỗi JSON bị vỡ hoặc dính markdown code blocks.
    """
    resp_text = re.sub(r'^```(?:json)?\s*', '', resp_text.strip(), flags=re.MULTILINE)
    resp_text = re.sub(r'\s*```$', '', resp_text, flags=re.MULTILINE)
    resp_text = re.sub(r'//.*', '', resp_text)
    resp_text = re.sub(r'/\*.*?\*/', '', resp_text, flags=re.DOTALL)
    resp_text = re.sub(r',\s*([\]}])', r'\1', resp_text)
    
    try:
        data = json.loads(resp_text.strip(), strict=False)
        if isinstance(data, dict) and "phan_2" in data and isinstance(data["phan_2"], list):
            data["phan_2"] = [_flatten_p2_item(it) for it in data["phan_2"]]
        return data
    except Exception as e:
        # Regex phục hồi linh hoạt nếu JSON bị dính ký tự lạ
        phan_1 = []
        for m in re.finditer(r'\{\s*"cau_hoi"\s*:\s*(\d+)\s*,\s*"dap_an"\s*:\s*"([A-Da-d])"(?:\s*,\s*"giai_thich"\s*:\s*"((?:\\.|[^"\\])*)")?\s*\}', resp_text):
            _gt = m.group(3).replace('\\"', '"').replace('\\n', ' ').strip() if m.group(3) else ""
            phan_1.append({
                "cau_hoi": int(m.group(1)),
                "dap_an": m.group(2).upper(),
                "giai_thich": _gt
            })
            
        phan_2 = []
        # 1. Phục hồi cấu trúc lồng YDungSai {"cau_hoi": 1, "y_a": {"dap_an": "...", "giai_thich": "..."}}
        c_matches = list(re.finditer(r'"cau_hoi"\s*:\s*(\d+)', resp_text))
        for idx_m, m_c in enumerate(c_matches):
            start_pos = m_c.start()
            end_pos = c_matches[idx_m + 1].start() if idx_m + 1 < len(c_matches) else len(resp_text)
            chunk = resp_text[start_pos:end_pos]
            if '"y_a"' not in chunk:
                continue
            item_p2 = {"cau_hoi": int(m_c.group(1))}
            found_nested = False
            for k in ['a', 'b', 'c', 'd']:
                m_yk = re.search(
                    rf'"y_{k}"\s*:\s*\{{\s*"dap_an"\s*:\s*"([^"]+)"(?:\s*,\s*"giai_thich"\s*:\s*"((?:\\.|[^"\\])*)")?',
                    chunk, re.DOTALL
                )
                if m_yk:
                    found_nested = True
                    item_p2[f"y_{k}"] = m_yk.group(1).strip()
                    item_p2[f"giai_thich_{k}"] = m_yk.group(2).strip() if m_yk.group(2) else ""
            if found_nested:
                phan_2.append(item_p2)

        # 2. Dự phòng cấu trúc phẳng cũ nếu chưa khớp cấu trúc lồng
        if not phan_2:
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
            res["ma_de"] = normalize_ma_de(str(m_c.group(1)))
            
        if phan_1 or phan_2:
            return res
        raise e


# --- CHẨN ĐOÁN TOKEN: ghi lại mỗi lượt gọi AI (lý do dừng + số token vào/ra/suy nghĩ) ---
_USAGE_LOG = []


def _record(tag, resp):
    """Ghi finish_reason (STOP = bình thường, MAX_TOKENS = bị cắt cụt) và usage_metadata của 1 lượt gọi."""
    if resp is None:
        return
    entry = {"luot": tag}
    try:
        fr = resp.candidates[0].finish_reason
        entry["finish"] = getattr(fr, "name", str(fr))
    except Exception:
        entry["finish"] = "?"
    try:
        u = resp.usage_metadata
        p_cnt = getattr(u, "prompt_token_count", 0) or 0
        c_cnt = getattr(u, "candidates_token_count", 0) or 0
        tot_cnt = getattr(u, "total_token_count", 0) or 0
        th_cnt = getattr(u, "thoughts_token_count", None)
        if th_cnt is None or th_cnt == 0:
            th_cnt = max(0, tot_cnt - p_cnt - c_cnt)
        entry["token_vao"] = p_cnt
        entry["token_ra"] = c_cnt
        entry["token_nghi"] = th_cnt
        entry["token_tong"] = tot_cnt
    except Exception:
        pass
    _USAGE_LOG.append(entry)


def _is_max_tokens(resp):
    """True nếu AI dừng vì hết token (JSON bị cắt cụt)."""
    try:
        fr = resp.candidates[0].finish_reason
        return getattr(fr, "name", str(fr)) == "MAX_TOKENS" or str(fr).endswith("MAX_TOKENS") or str(fr) == "2"
    except Exception:
        return False


def _generate_json(model_name, schema, contents, tag, temperature=0.1, token_steps=(24576, 32768)):
    last_err, fallback = None, None
    for i, mt in enumerate(token_steps):
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
                max_output_tokens=mt
            )
        )
        try:
            resp = model.generate_content(contents, request_options={"timeout": 240})
            _record(f"{tag} [trần {mt}]", resp)
            truncated = _is_max_tokens(resp)
            parsed = robust_exam_json_parser(resp.text)
            if truncated and i < len(token_steps) - 1:
                fallback = parsed  
                continue
            return parsed
        except Exception as e:
            last_err = e
            time.sleep(1.5)
    if fallback is not None:
        return fallback
    raise RuntimeError(f"{tag}: AI trả JSON lỗi/bị cắt ({last_err}). Chẩn đoán: {_USAGE_LOG}")


def _call_gemini_api_base(api_key, text, ma_de, nam_thi="2025", pdf_bytes=None, model_name="gemini-3.8-flash"):
    genai.configure(api_key=api_key)
    tag_prefix = "Pro" if "pro" in model_name.lower() else "Flash"
    # PHA 1: BÓC TÁCH MÃ ĐỀ, NĂM THI VÀ GIẢI DUY NHẤT 24 CÂU TRẮC NGHIỆM PHẦN I
    c1 = []
    if pdf_bytes:
        # Nhánh 1 (Kênh AI Vision): Đóng gói byte nhị phân để mô hình đọc trực quan 4 trang PDF scan
        c1.append({"mime_type": "application/pdf", "data": pdf_bytes})
        prompt_p1 = f"""Tài liệu PDF đính kèm là ĐỀ THI gồm 4 TRANG (Mã dự kiến: {ma_de}).
 YÊU CẦU:
 1. Đọc kỹ phần đầu trang 1 để xác định chính xác NĂM THI (vd: 2025 hoặc 2026) và MÃ ĐỀ THI.
 2. Giải DUY NHẤT PHẦN I gồm ĐẦY ĐỦ TOÀN BỘ 24 CÂU TRẮC NGHIỆM (từ Câu 1 đến Câu 24, trải dài qua trang 1, 2, 3).
 BẮT BUỘC giải đủ cả 24 câu, dap_an chỉ là 1 ký tự A, B, C hoặc D. Lời giải thích súc tích dưới 20 từ mỗi câu."""
    else:
        # Nhánh 2 (Kênh Digital Text): Nạp văn bản số trích xuất từ pdfplumber để tối ưu tốc độ và token
        prompt_p1 = f"""Đọc kỹ tiêu đề để xác định NĂM THI và MÃ ĐỀ THI (dự kiến: {ma_de}).
 Hãy giải DUY NHẤT PHẦN I gồm TOÀN BỘ 24 CÂU TRẮC NGHIỆM (từ Câu 1 đến 24).
 Lời giải thích súc tích dưới 20 từ mỗi câu:\n\n--- NỘI DUNG ĐỀ THI ---\n{text}"""
    c1.append(prompt_p1)
    # Thực thi suy luận Pha 1 áp dụng Logit Masking với Schema BaiGiaiPhan1
    parsed_p1 = _generate_json(model_name, BaiGiaiPhan1, c1, f"{tag_prefix} Pha 1 (24 câu P1)")
    time.sleep(1.2)
    # PHA 2: DỒN TOÀN BỘ SUY LUẬN CHO 6 CÂU ĐÚNG/SAI PHẦN II (KÈM GIẢI THÍCH)
    c2 = []
    if pdf_bytes:
        # Nhánh 1 (Kênh AI Vision): Đọc trực quan trang 3 và trang 4 của đề thi scan
        c2.append({"mime_type": "application/pdf", "data": pdf_bytes})
        prompt_p2 = f"""Tài liệu PDF đính kèm là ĐỀ THI gồm 4 TRANG (Mã dự kiến: {ma_de}).
 HÃY ĐỌC KỸ TRANG 3 VÀ TRANG 4 ĐỂ GIẢI 6 CÂU HỎI CỦA PHẦN II (ĐÚNG/SAI):
 - Câu 1, 2: Phần chung (ở cuối trang 3 và đầu trang 4).
 - Câu 3, 4: Phần riêng Khoa học máy tính (ở trang 4).
 - Câu 5, 6: Phần riêng Tin học ứng dụng (ở trang 4).
 YÊU CẦU BẮT BUỘC:
 1. Giải trọn vẹn cả 6 câu (đánh số cau_hoi từ 1 đến 6).
 2. Với mỗi ý y_a, y_b, y_c, y_d: điền dap_an là 'Đúng' hoặc 'Sai' VÀ BẮT BUỘC điền giai_thich ngắn gọn (dưới 25 từ) nêu rõ lý do kỹ thuật bám sát đề thi, TUYỆT ĐỐI KHÔNG ĐỂ TRỐNG!
 Trả về JSON tuân thủ đúng Schema BaiGiaiPhan2."""
    else:
        # Nhánh 2 (Kênh Digital Text): Suy luận logic dựa trên chuỗi văn bản trích xuất
        prompt_p2 = f"""Hãy giải TOÀN BỘ 6 CÂU HỎI CỦA PHẦN II (từ câu 1 đến 6, mỗi câu đủ 4 ý a, b, c, d) từ đề thi dưới đây.
 Với mỗi ý y_a, y_b, y_c, y_d: điền dap_an là 'Đúng' hoặc 'Sai' VÀ BẮT BUỘC điền giai_thich ngắn gọn (dưới 25 từ) nêu rõ lý do kỹ thuật bám sát đề thi.
 \n--- NỘI DUNG ĐỀ THI ---\n{text}"""
    c2.append(prompt_p2)

    # Thực thi suy luận Pha 2 áp dụng Logit Masking với Schema BaiGiaiPhan2
    parsed_p2 = _generate_json(model_name, BaiGiaiPhan2, c2, f"{tag_prefix} Pha 2 (6 câu P2 Đúng/Sai)")

    # Ghép hợp nhất kết quả hoàn chỉnh từ 2 pha
    p2_raw = parsed_p2.get("phan_2", []) if isinstance(parsed_p2, dict) else []
    p2_flat = [_flatten_p2_item(it) for it in p2_raw]
    raw_md = str(parsed_p1.get("ma_de") or ma_de).strip()
    norm_md = normalize_ma_de(raw_md) if re.search(r'\d', raw_md) else normalize_ma_de(ma_de)
    return {
        "nam_thi": parsed_p1.get("nam_thi") or int(nam_thi),
        "ma_de": norm_md,
        "phan_1": parsed_p1.get("phan_1", []),
        "phan_2": p2_flat
    }


# =============================================================================
# LỚP "VÁ CÂU THIẾU" (GAP-FILL) - CHẶN TÌNH TRẠNG AI BỎ SÓT CÂU / BỎ CẢ PHẦN II
# Sau khi AI giải xong, kiểm đếm chính xác câu/ý nào thiếu (hoặc thiếu giải thích)
# rồi CHỈ hỏi lại đúng các câu đó (ngắn, rẻ, tập trung) - tối đa 3 vòng.
# =============================================================================
def _valid_yn(v):
    s = str(v).strip().upper()
    return s.startswith(("ĐÚNG", "DUNG", "SAI", "TRUE", "FALSE")) or s in ("Đ", "D", "S")


def _is_valid_exp(s):
    txt = str(s or "").strip()
    if not txt:
        return False
    low = txt.lower()
    if "dựa trên phân tích logic câu hỏi" in low or "theo kiến thức tin học chuẩn" in low:
        return False
    return True


def _p2_score(it):
    """Điểm đầy đủ của 1 câu Phần II: tối đa 8 = 4 ý Đúng/Sai hợp lệ + 4 lời giải thích ngắn bám sát đề thi."""
    if not isinstance(it, dict):
        return 0
    it = _flatten_p2_item(it)
    score_yn = sum(_valid_yn(it.get(f"y_{k}", "")) for k in "abcd")
    score_exp = sum(_is_valid_exp(it.get(f"giai_thich_{k}", "")) for k in "abcd")
    return score_yn + score_exp


def _norm_p1(items):
    """Chuẩn hóa Phần I thành {số câu: item}; bỏ câu sai số / đáp án không phải A-D / trùng lặp."""
    out = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            c = int(it.get("cau_hoi"))
        except Exception:
            continue
        m = re.match(r'^\s*([A-Da-d])\b', str(it.get("dap_an", "")))
        if 1 <= c <= 24 and m:
            if c not in out or (not _is_valid_exp(out[c].get("giai_thich")) and _is_valid_exp(it.get("giai_thich"))):
                it = dict(it)
                it["dap_an"] = m.group(1).upper()
                out[c] = it
    return out


def _norm_p2(items):
    """Chuẩn hóa Phần II thành {số câu 1..6: item}. Nếu AI trả đúng 6 câu nhưng đánh số lặp (1,2,1,2,..) thì đánh lại 1..6."""
    items = [_flatten_p2_item(it) for it in (items or []) if isinstance(it, dict)]
    nums = []
    for it in items:
        try:
            nums.append(int(it.get("cau_hoi")))
        except Exception:
            nums.append(None)
    out = {}
    if len(items) == 6 and sorted(n for n in nums if n) != [1, 2, 3, 4, 5, 6]:
        for i, it in enumerate(items):
            it = dict(it)
            it["cau_hoi"] = i + 1
            out[i + 1] = it
        return out
    for it, c in zip(items, nums):
        if c and 1 <= c <= 6 and (c not in out or _p2_score(it) > _p2_score(out[c])):
            out[c] = it
    return out


def _ask_subset(model_name, schema, prompt, text, pdf_bytes, temperature):
    """Gọi AI cho 1 tập con câu hỏi (prompt ngắn, tập trung)."""
    contents = []
    if pdf_bytes:
        contents.append({"mime_type": "application/pdf", "data": pdf_bytes})
    else:
        prompt += f"\n\n--- NỘI DUNG ĐỀ THI ---\n{text}"
    contents.append(prompt)
    return _generate_json(model_name, schema, contents, "Vá câu thiếu", temperature)


def fill_missing_answers(api_key, result, text, pdf_bytes, model_name, max_rounds=2):
    genai.configure(api_key=api_key)
    p1 = _norm_p1(result.get("phan_1"))
    p2 = _norm_p2(result.get("phan_2"))
    temps = [0.1, 0.3, 0.5]
    for rnd in range(max_rounds):
        miss1 = [c for c in range(1, 25) if c not in p1 or not _is_valid_exp(p1[c].get("giai_thich", ""))]
        miss2 = [c for c in range(1, 7) if _p2_score(p2.get(c)) < 8]
        if not miss1 and not miss2:
            break
        temp = temps[min(rnd, len(temps) - 1)]

        if miss1:
            try:
                prompt = (f"Giải các câu PHẦN I sau: {', '.join(map(str, miss1))}. "
                          f"Trả về cau_hoi đúng số gốc, dap_an là A/B/C/D và giải thích dưới 20 từ bám sát đề thi.")
                got = _ask_subset(model_name, BaiGiaiPhan1, prompt, text, pdf_bytes, temp)
                for it in _norm_p1(got.get("phan_1")).items():
                    if it[0] in miss1:
                        p1[it[0]] = it[1]
            except Exception:
                pass
            time.sleep(1.0)

        if miss2:
            try:
                desc = {1: "Câu 1 (Chung)", 2: "Câu 2 (Chung)", 3: "Câu 3 (KHMT)", 4: "Câu 4 (KHMT)", 5: "Câu 5 (THUD)", 6: "Câu 6 (THUD)"}
                targets = "; ".join(f"{desc[c]} -> cau_hoi={c}" for c in miss2)
                prompt = (f"Giải các câu PHẦN II sau: {targets}. Mỗi câu đủ 4 ý a, b, c, d.\n"
                          f"Với mỗi ý y_a, y_b, y_c, y_d: điền dap_an là 'Đúng' hoặc 'Sai' và BẮT BUỘC điền giai_thich dưới 25 từ bám sát đề thi. "
                          f"Trả về Schema BaiGiaiPhan2.")
                got = _ask_subset(model_name, BaiGiaiPhan2, prompt, text, pdf_bytes, temp)
                items = [_flatten_p2_item(it) for it in (got.get("phan_2") or []) if isinstance(it, dict)]
                for i, it in enumerate(items):
                    try:
                        c = int(it.get("cau_hoi"))
                    except Exception:
                        c = None
                    if c not in miss2 and len(items) == len(miss2):
                        c = miss2[i]
                    if c in miss2 and _p2_score(it) > _p2_score(p2.get(c)):
                        it = dict(it)
                        it["cau_hoi"] = c
                        p2[c] = it
            except Exception:
                pass
            time.sleep(1.0)

    result["phan_1"] = [p1[c] for c in sorted(p1)]
    result["phan_2"] = [p2[c] for c in sorted(p2)]

    left1 = [c for c in range(1, 25) if c not in p1 or not _is_valid_exp(p1[c].get("giai_thich", ""))]
    left2 = [c for c in range(1, 7) if _p2_score(p2.get(c)) < 8]
    warns = []
    if left1:
        warns.append(f"Phần I còn thiếu câu hoặc thiếu giải thích: {', '.join(map(str, left1))}")
    if left2:
        warns.append(f"Phần II còn thiếu ý Đúng/Sai hoặc thiếu giải thích: {', '.join(map(str, left2))}")
    if warns:
        result["canh_bao"] = warns
    else:
        result.pop("canh_bao", None)
    return result


def call_gemini_api(api_key, text, ma_de, nam_thi="2025", pdf_bytes=None, model_name="gemini-3.8-flash"):
    """Giải đề theo quy trình 2 Pha (Pha 1: 24 câu P1, Pha 2: 6 câu P2 kèm giải thích) rồi tự động VÁ các câu/ý hoặc giải thích AI bỏ sót bằng các lượt truy vấn mục tiêu kèm ngữ cảnh đề thi."""
    _USAGE_LOG.clear()
    result = _call_gemini_api_base(api_key, text, ma_de, nam_thi, pdf_bytes=pdf_bytes, model_name=model_name)
    if not isinstance(result, dict):
        return result
    try:
        result = fill_missing_answers(api_key, result, text, pdf_bytes, model_name)
    except Exception:
        pass
    result["chan_doan_token"] = list(_USAGE_LOG)
    return result


def parse_answer_key_pdf(api_key, pdf_file, target_codes=None, model_name="gemini-3.8-flash"):
    """
    Dùng Gemini Multimodal Vision để đọc bảng đáp án in ngang và có con dấu với cơ chế tách lớp màu thị giác:
    Bỏ qua mực đỏ mộc tròn, tập trung bóc tách nét chữ mực đen bên dưới.
    """
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


def detect_answer_key_codes(api_key, pdf_bytes, model_name="gemini-3.8-flash"):
    """
    Lượt gọi AI nhẹ: Liệt kê toàn bộ mã đề (tiêu đề cột) và năm thi có trong file PDF đáp án.
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0,
            max_output_tokens=2048
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


def parse_full_answer_key_pdf(api_key, pdf_file, model_name="gemini-3.8-flash", chunk_size=12, progress_cb=None):
    """
    Bóc tách 1 lần TOÀN BỘ file PDF đáp án (vd: 48 mã đề).
    Chia mã đề thành từng nhóm nhỏ (chunks) để mỗi lượt gọi không bị cắt cụt đầu ra, sau đó gộp lại và thử lại các mã bị thiếu.
    Trả về: (DataFrame, năm_thi, danh_sách_mã_đề, danh_sách_mã_thiếu)
    """
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
