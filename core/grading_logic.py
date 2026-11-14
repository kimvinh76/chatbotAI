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
import html
import pandas as pd
import streamlit as st


def build_comparison_and_detail_df(ai_data, answer_key_df=None, ma_de_hien_tai="", file_name=""):
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
    ai_p1_map = {}
    for item in ai_data.get("phan_1", []):
        c_num = item.get("cau_hoi")
        if c_num and c_num not in ai_p1_map:
            ai_p1_map[c_num] = item
    ai_p2_map = {}
    raw_p2_items = ai_data.get("phan_2", [])

    p2_c_nums = [it.get("cau_hoi") for it in raw_p2_items if isinstance(it, dict)]
    if len(raw_p2_items) == 6 and len(set(p2_c_nums)) < 6:
        for idx, item in enumerate(raw_p2_items):
            ai_p2_map[idx + 1] = item
    else:
        for item in raw_p2_items:
            c_num = item.get("cau_hoi")
            if c_num and c_num not in ai_p2_map:
                ai_p2_map[c_num] = item
    # Trích xuất Phần 1:DUYỆT ĐỦ 24 CÂU CHUẨN 
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
          # So khớp trực tiếp với đáp án chuẩn của Bộ GD&ĐT
        if has_key:
            match = df_filtered[(df_filtered['Phần'] == 1) & (df_filtered['Câu'] == cau)]
            if not match.empty:
                raw_chuan = str(match.iloc[0]['Đáp Án']).strip().upper()
                m_chuan = re.search(r'[A-D]', raw_chuan)
                dap_an_chuan = m_chuan.group(0) if m_chuan else raw_chuan
                ket_qua = "Đúng" if (dap_an_ai == dap_an_chuan) else "Sai"
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
                raw_ai_val = item.get(y, "")
                if isinstance(raw_ai_val, dict):
                    raw_ai = str(raw_ai_val.get("dap_an", "")).strip()
                    giai_thich_y = str(raw_ai_val.get("giai_thich", "")).strip()
                else:
                    raw_ai = str(raw_ai_val).strip()
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
                    giai_thich_y = "AI chưa cung cấp giải thích chi tiết cho khẳng định này."
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
                        
                    ket_qua = "Đúng" if (dap_an_ai == dap_an_chuan) else "Sai"
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


def calculate_moet_scores(detail_df):
    """
    Tính điểm chuẩn xác theo Quy chế của Bộ Giáo dục & Đào tạo (Thang điểm 10):
    - Phần I (24 câu): Mỗi câu đúng được 0.25 điểm (tối đa 6.0 điểm).
    - Phần II (Thí sinh chọn 1 trong 2 định hướng, tối đa 4.0 điểm):
      + Câu 1, Câu 2: Phần chung bắt buộc
      + Câu 3, Câu 4: Định hướng Khoa học máy tính (KHMT)
      + Câu 5, Câu 6: Định hướng Tin học ứng dụng (THUD)
      + Quy tắc điểm bậc thang lũy tiến cho từng câu hỏi lớn:
        * Đúng 1 ý: 0.10 điểm
        * Đúng 2 ý: 0.25 điểm
        * Đúng 3 ý: 0.50 điểm
        * Đúng 4 ý: 1.00 điểm
    Trả về:
    - diem_khmt (float): Điểm thí sinh chọn nhánh Khoa học máy tính (tối đa 10.0)
    - diem_thud (float): Điểm thí sinh chọn nhánh Tin học ứng dụng (tối đa 10.0)
    - p1_score (float): Điểm Phần I (tối đa 6.0)
    - p2_scores_dict (dict): Điểm từng câu Phần II (Câu 1 đến Câu 6)
    """
    if detail_df is None or (isinstance(detail_df, pd.DataFrame) and detail_df.empty):
        return 0.0, 0.0, 0.0, {}

    records = detail_df.to_dict(orient='records') if isinstance(detail_df, pd.DataFrame) else list(detail_df)

    # 1. Điểm Phần I
    p1_items = [d for d in records if d.get('Phần') == 'Phần I (Trắc nghiệm)']
    p1_correct = sum(1 for d in p1_items if 'Đúng' in str(d.get('Kết Quả', '')))
    p1_score = round(p1_correct * 0.25, 2)

    # 2. Điểm lũy tiến từng câu Phần II
    def score_single_cau(exact_cau_label):
        items = [d for d in records if d.get('Câu') == exact_cau_label]
        c = sum(1 for it in items if 'Đúng' in str(it.get('Kết Quả', '')))
        if c == 1:
            return 0.10
        elif c == 2:
            return 0.25
        elif c == 3:
            return 0.50
        elif c == 4:
            return 1.00
        return 0.0

    p2_scores = {
        1: score_single_cau("Phần II.A (Chung) - Câu 1"),
        2: score_single_cau("Phần II.A (Chung) - Câu 2"),
        3: score_single_cau("Phần II.B1 (KHMT) - Câu 3"),
        4: score_single_cau("Phần II.B1 (KHMT) - Câu 4"),
        5: score_single_cau("Phần II.B2 (THUD) - Câu 5"),
        6: score_single_cau("Phần II.B2 (THUD) - Câu 6"),
    }

    # Thí sinh chọn KHMT: Phần I + Câu 1 + Câu 2 + Câu 3 + Câu 4
    diem_khmt = round(p1_score + p2_scores[1] + p2_scores[2] + p2_scores[3] + p2_scores[4], 2)
    # Thí sinh chọn THUD: Phần I + Câu 1 + Câu 2 + Câu 5 + Câu 6
    diem_thud = round(p1_score + p2_scores[1] + p2_scores[2] + p2_scores[5] + p2_scores[6], 2)

    return diem_khmt, diem_thud, p1_score, p2_scores


def render_comparison_detail_table(detail_df: pd.DataFrame, key_suffix: str = ""):
    """
    Hiển thị Bảng Lưới (DataGrid) duy nhất, đồng bộ 100% cho cả Tab 1 và Tab 2.
    - Cột Giải Thích AI được đưa lên vị trí trung tâm với độ rộng lớn nhất để không bao giờ bị cắt chữ.
    - Lọc bỏ các cột lặp lại (Mã Đề, Tên File) để giải phóng diện tích màn hình.
    """
    if detail_df is None or detail_df.empty:
        st.info("Chưa có dữ liệu chi tiết câu hỏi.")
        return

    # Chuẩn bị DataFrame hiển thị gọn gàng, tinh tế
    display_rows = []
    for idx, row in detail_df.reset_index(drop=True).iterrows():
        stt = idx + 1
        raw_phan = str(row.get("Phần", ""))
        p_prefix = "P2" if ("Phần II" in raw_phan or raw_phan == "2" or "P2" in raw_phan) else "P1"
        
        raw_cau = str(row.get("Câu", ""))
        m_c = re.search(r'Câu\s*(\d+)', raw_cau, re.IGNORECASE)
        c_num = m_c.group(1) if m_c else raw_cau
        
        y_val = str(row.get("Ý", "")).strip()
        if y_val:
            cau_y = f"{p_prefix} - Câu {c_num} ({y_val})"
        else:
            cau_y = f"{p_prefix} - Câu {c_num}"

        display_rows.append({
            "STT": stt,
            "Câu / Ý": cau_y,
            "Giải Thích Chi Tiết Của AI": str(row.get("Giải Thích AI", "") or ""),
            "AI Chọn": str(row.get("AI Chọn", "")),
            "Đáp Án Đúng": str(row.get("Đáp Án Chuẩn", "")),
            "Kết Quả": str(row.get("Kết Quả", "")),
        })

    grid_df = pd.DataFrame(display_rows)
    grid_df.set_index("STT", inplace=True)

    style_func = lambda val: 'color: #4ade80; font-weight: bold' if 'Đúng' in str(val) else (
        'color: #f87171; font-weight: bold' if 'Sai' in str(val) else ''
    )
    if hasattr(grid_df.style, 'map'):
        styled_df = grid_df.style.map(style_func, subset=['Kết Quả'])
    else:
        styled_df = grid_df.style.applymap(style_func, subset=['Kết Quả'])

    st.dataframe(
        styled_df,
        use_container_width=True,
        height=600,
        key=f"grid_detail_{key_suffix}" if key_suffix else None,
        column_config={
            "Câu / Ý": st.column_config.TextColumn("Câu / Ý", width=105),
            "Giải Thích Chi Tiết Của AI": st.column_config.TextColumn(
                "Giải Thích Chi Tiết Của AI",
                width=740,
                help="Phân tích, lập luận logic và đối soát học thuật của AI",
            ),
            "AI Chọn": st.column_config.TextColumn("AI Chọn", width=70),
            "Đáp Án Đúng": st.column_config.TextColumn("Đáp Án Đúng", width=90),
            "Kết Quả": st.column_config.TextColumn("Kết Quả", width=75),
        }
    )
