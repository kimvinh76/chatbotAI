"""
=============================================================================
MODULE: core/grading_logic.py
CHỨC NĂNG:
- Trích xuất toàn diện bài giải của AI thành bảng đối sánh chi tiết (build_comparison_and_detail_df).
- Đối soát tự động từng câu/ý với Ngân hàng đáp án chuẩn của Bộ GD&ĐT.
- Bóc tách đa dạng trường lời giải thích (giai_thich_a..d, lý do trong ngoặc đơn, sau dấu chấm...).
- Tính toán điểm số hệ 10 chuẩn cấu trúc Bộ GD&ĐT:
  + Phần I (24 câu): Mỗi câu đúng được 0.25 điểm (tối đa 6.0 điểm).
  + Phần II (6 câu Đúng/Sai):
    * Đúng 1 ý: 0.1 điểm
    * Đúng 2 ý: 0.25 điểm
    * Đúng 3 ý: 0.5 điểm
    * Đúng cả 4 ý: 1.0 điểm (tối đa 4.0 điểm).
=============================================================================
"""

import re
import pandas as pd


def build_comparison_and_detail_df(ai_data, answer_key_df=None, ma_de_hien_tai="", file_name=""):
    """
    Trích xuất toàn bộ tất cả câu trả lời của AI và đối sánh với đáp án chuẩn (nếu có).
    Đảm bảo duyệt đủ 24 câu Phần I và 6 câu (24 ý) Phần II ra DataFrame chi tiết.
    Trả về: (DataFrame_chi_tiết, có_đáp_án_đối_sánh_hay_không)
    """
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

    # Chuẩn hóa bài làm của AI thành Map tra cứu (Tự động khử trùng lặp câu hỏi nếu AI sinh 2 lần)
    ai_p1_map = {}
    for item in ai_data.get("phan_1", []):
        c_num = item.get("cau_hoi")
        if c_num and c_num not in ai_p1_map:
            ai_p1_map[c_num] = item

    ai_p2_map = {}
    raw_p2_items = ai_data.get("phan_2", [])
    # Nếu AI sinh đủ 6 câu nhưng bị lặp số câu 1, 2 (do chia Phần Chung, KHMT, THUD): tự động map theo thứ tự 1..6
    p2_c_nums = [it.get("cau_hoi") for it in raw_p2_items if isinstance(it, dict)]
    if len(raw_p2_items) == 6 and len(set(p2_c_nums)) < 6:
        for idx, item in enumerate(raw_p2_items):
            ai_p2_map[idx + 1] = item
    else:
        for item in raw_p2_items:
            c_num = item.get("cau_hoi")
            if c_num and c_num not in ai_p2_map:
                ai_p2_map[c_num] = item

    # 1. Trích xuất Phần 1: BẮT BUỘC DUYỆT ĐỦ 24 CÂU CHUẨN (Từ Câu 1 đến Câu 24)
    for cau in range(1, 25):
        if cau in ai_p1_map:
            item = ai_p1_map[cau]
            raw_p1 = str(item.get("dap_an", "")).strip().upper()
            m_char = re.search(r'[A-D]', raw_p1)
            dap_an_ai = m_char.group(0) if m_char else raw_p1
            giai_thich = str(item.get("giai_thich", "")).strip()
        else:
            dap_an_ai = "Chưa làm / Bỏ sót"
            giai_thich = "AI đọc sót hoặc không giải câu này"
        
        dap_an_chuan = "-"
        ket_qua = "Chưa đối sánh"
        if has_key:
            match = df_filtered[(df_filtered['Phần'] == 1) & (df_filtered['Câu'] == cau)]
            if not match.empty:
                raw_chuan = str(match.iloc[0]['Đáp Án']).strip().upper()
                m_chuan = re.search(r'[A-D]', raw_chuan)
                dap_an_chuan = m_chuan.group(0) if m_chuan else raw_chuan
                ket_qua = "✅ Đúng" if (dap_an_ai == dap_an_chuan) else "❌ Sai"
            else:
                ket_qua = "Chưa có đáp án"
                
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

    # 2. Trích xuất Phần 2: BẮT BUỘC DUYỆT ĐỦ 6 CÂU CHUẨN (Mỗi câu 4 ý A, B, C, D = 24 ý)
    phan_2_names = {
        1: "Phần II.A (Chung) - Câu 1",
        2: "Phần II.A (Chung) - Câu 2",
        3: "Phần II.B1 (KHMT) - Câu 3",
        4: "Phần II.B1 (KHMT) - Câu 4",
        5: "Phần II.B2 (THUD) - Câu 5",
        6: "Phần II.B2 (THUD) - Câu 6"
    }
    
    for cau in range(1, 7):
        label_prefix = phan_2_names.get(cau, f"Phần II - Câu {cau}")
        item = ai_p2_map.get(cau, {})
        has_this_p2 = (cau in ai_p2_map)
        
        for i, y in enumerate(['y_a', 'y_b', 'y_c', 'y_d']):
            y_label = chr(65 + i) # A, B, C, D
            if has_this_p2:
                raw_ai = str(item.get(y, "")).strip()
                giai_thich_y = str(
                    item.get(f"giai_thich_{chr(97 + i)}") or 
                    item.get(f"giai_thich_{chr(65 + i)}") or 
                    item.get(f"giai_thich_{y}") or 
                    item.get(f"gt_{chr(97 + i)}") or 
                    item.get(f"ly_do_{chr(97 + i)}") or 
                    ""
                ).strip()
                
                # Tự động tách nếu giá trị AI có chứa nội dung ngoặc đơn vd: "Sai (các máy tính...)" hoặc sau dấu chấm / gạch ngang
                extracted_reason = ""
                m_paren = re.search(r'\((.*?)\)', raw_ai)
                if m_paren:
                    extracted_reason = m_paren.group(1).strip()
                    clean_ai = re.sub(r'\(.*?\)', '', raw_ai).strip()
                else:
                    m_sep = re.search(r'^(?:Đúng|Sai|True|False|Đ|S)\s*[\.\-:\;]\s*(.+)$', raw_ai, re.IGNORECASE)
                    if m_sep:
                        extracted_reason = m_sep.group(1).strip()
                        clean_ai = re.sub(r'[\.\-:\;].*$', '', raw_ai).strip()
                    else:
                        clean_ai = raw_ai
                        
                clean_upper = clean_ai.upper()
                if any(kw in clean_upper for kw in ['ĐÚNG', 'DUNG', 'TRUE']) or clean_upper in ['D', 'Đ']:
                    dap_an_ai = "Đúng"
                elif any(kw in clean_upper for kw in ['SAI', 'FALSE']) or clean_upper == 'S':
                    dap_an_ai = "Sai"
                else:
                    dap_an_ai = clean_ai.capitalize() if clean_ai else "Chưa làm / Bỏ sót"
                    
                # Cứu lời giải thích nếu giai_thich_y bị trống nhưng trong raw_ai có lý do
                if not giai_thich_y and extracted_reason:
                    giai_thich_y = extracted_reason
                elif not giai_thich_y and dap_an_ai in ("Đúng", "Sai"):
                    giai_thich_y = f"Khẳng định này là {dap_an_ai.lower()} theo kiến thức Tin học chuẩn."
            else:
                dap_an_ai = "Chưa làm / Bỏ sót"
                giai_thich_y = "AI đọc sót hoặc không giải câu này"
                
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
                else:
                    ket_qua = "Chưa có đáp án"
                    
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
