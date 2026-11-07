"""
=============================================================================
MODULE: core/excel_utils.py
CHỨC NĂNG:
- Xử lý chuẩn hóa mã đề thi Bộ GD&ĐT (normalize_ma_de).
- Bóc tách đáp án Đúng/Sai Phần II (parse_p2_val).
- Thuật toán Smart Header Row & Year Detection bóc tách Excel/CSV (parse_answer_excel_or_csv).
- Chuyển đổi qua lại giữa DataFrame dọc và Ma trận ngang (bảng tổng hợp đáp án).
- Xuất dữ liệu ra file Excel nhị phân siêu tốc với bộ đệm Streamlit Cache.
=============================================================================
"""

import io
import re
import pandas as pd
import streamlit as st


def normalize_ma_de(code):
    """
    Chuẩn hóa mã đề thi về định dạng 4 chữ số chuẩn Bộ GD&ĐT (vd: 101 -> 0101, 501 -> 0501).
    Đảm bảo việc truy vấn và đối khớp trong MongoDB không bị lệch giữa '501' và '0501'.
    """
    if not code:
        return "0000"
    code_str = str(code).strip()
    m = re.search(r'\d+', code_str)
    if m:
        num_str = m.group(0)
        return num_str.zfill(4)
    return code_str.zfill(4)


def parse_p2_val(raw_val):
    """
    Phân tích ô chứa 4 ý Phần II (vd: 'S,D,S,D', 'D,D,D,S', 'Đ, S, Đ, S', 'SDSD', 'a) Đ, b) S...').
    Trả về danh sách 4 giá trị chuẩn ['Đúng', 'Sai', 'Đúng', 'Sai'] hoặc None nếu không hợp lệ.
    """
    if raw_val is None or pd.isna(raw_val) or not str(raw_val).strip() or str(raw_val).strip().lower() == 'nan':
        return None
    s = str(raw_val).strip()
    
    # 1. Hỗ trợ dạng có tiền tố nhãn từng ý (vd: 'a) Đ, b) S, c) Đ, d) S' hoặc 'a. Đúng; b. Sai...')
    m_labeled = re.findall(r'[a-d]\s*[:\)\-\.]\s*([^\s,;]+)', s, re.I)
    if len(m_labeled) == 4:
        ans = []
        for p in m_labeled:
            p_up = p.upper()
            if p_up in ('Đ', 'D', 'ĐÚNG', 'DUNG', 'TRUE', 'T', '1'):
                ans.append('Đúng')
            elif p_up in ('S', 'SAI', 'FALSE', 'F', '0'):
                ans.append('Sai')
            else:
                return None
        return ans

    # 2. Tách theo dấu phẩy, chấm phẩy, gạch ngang, khoảng trắng, gạch chéo
    parts = [p.strip().upper() for p in re.split(r'[,;\s\-_/]+', s) if p.strip()]
    if len(parts) == 4:
        ans = []
        for p in parts:
            if p in ('Đ', 'D', 'ĐÚNG', 'DUNG', 'TRUE', 'T', '1'):
                ans.append('Đúng')
            elif p in ('S', 'SAI', 'FALSE', 'F', '0'):
                ans.append('Sai')
            else:
                return None
        return ans
        
    # 3. Dạng viết liền không dấu ngăn cách (vd: 'DSDS', 'ĐSĐS', '1010')
    s_clean = re.sub(r'[^A-ZĐa-zđ01]', '', s).upper()
    if len(s_clean) == 4:
        ans = []
        for p in s_clean:
            if p in ('Đ', 'D', 'T', '1'):
                ans.append('Đúng')
            elif p in ('S', 'F', '0'):
                ans.append('Sai')
            else:
                return None
        return ans
    return None


def parse_answer_excel_or_csv(file):
    """
    Tự động phát hiện và bóc tách dữ liệu từ file Excel / CSV:
    Hỗ trợ toàn diện các định dạng:
    1. Thuật toán Smart Header Row Detection: Tự động bỏ qua các dòng banner/tiêu đề đầu file 
       (vd: 'ĐÁP ÁN TIN HỌC 2026', 'Kỳ thi tốt nghiệp...'), định vị chính xác dòng tiêu đề thật chứa Mã Đề (0501, 0502...).
    2. Smart Year Detection: Tự động nhận diện năm thi (vd: 2026, 2025) từ banner hoặc tên file.
    3. Dạng Ma trận Bộ GD&ĐT (User upload): Hàng 1..24 (P1), Hàng 25..30 (P2 có giá trị 'S,D,S,D' hoặc 'D,D,D,S').
    4. Dạng Ma trận bung lẻ: Hàng là 'P1 - Câu 01'...'P2 - Câu 6d' (tổng 48 hàng).
    5. Dạng Danh sách dọc chuẩn DB: Cột 'Mã Đề', 'Phần', 'Câu', 'Đáp Án'.
    Trả về: (DataFrame_đáp_án, detected_year)
    """
    if file is None:
        return pd.DataFrame(), None

    if isinstance(file, pd.DataFrame):
        df_raw = file.copy()
        f_name = ""
    else:
        if hasattr(file, 'seek'):
            file.seek(0)
        f_name = file.name if hasattr(file, 'name') else str(file)
        f_name_lower = f_name.lower()
        try:
            if f_name_lower.endswith('.csv'):
                try:
                    df_raw = pd.read_csv(file, header=None, dtype=str, encoding='utf-8')
                except UnicodeDecodeError:
                    if hasattr(file, 'seek'): file.seek(0)
                    df_raw = pd.read_csv(file, header=None, dtype=str, encoding='utf-8-sig')
                except Exception:
                    if hasattr(file, 'seek'): file.seek(0)
                    df_raw = pd.read_csv(file, header=None, dtype=str, encoding='latin1')
            else:
                df_raw = pd.read_excel(file, header=None, dtype=str)
        except Exception:
            return pd.DataFrame(), None

    if df_raw is None or df_raw.empty:
        return pd.DataFrame(), None

    # --- BƯỚC 1: TỰ ĐỘNG PHÁT HIỆN NĂM THI ---
    detected_year = None
    m_name = re.search(r'\b(202[4-9]|203\d)\b', str(f_name))
    if m_name:
        detected_year = m_name.group(0)

    for r_idx in range(min(10, len(df_raw))):
        row_str = ' '.join(df_raw.iloc[r_idx].dropna().astype(str).tolist())
        m_row = re.search(r'\b(202[4-9]|203\d)\b', row_str)
        if m_row:
            detected_year = m_row.group(0)
            break

    # --- BƯỚC 2: QUÉT TÌM DÒNG HEADER THẬT (BỎ QUA CÁC DÒNG BANNER TIÊU ĐỀ) ---
    best_row = 0
    best_score = -1
    for r_idx in range(min(15, len(df_raw))):
        score = 0
        row_vals = [str(x).strip() for x in df_raw.iloc[r_idx].tolist() if pd.notna(x) and str(x).strip() != '']
        lower_vals = [v.lower() for v in row_vals]

        # Kiểm tra layout dọc DB
        if any('mã đề' in v or 'ma de' in v for v in lower_vals) and any('phần' in v or 'phan' in v or 'đáp án' in v or 'dap an' in v for v in lower_vals):
            best_row = r_idx
            best_score = 999
            break

        has_label = any(any(k in v for k in ['câu', 'cau', 'stt', 'vị trí', 'vi tri', 'phần', 'phan']) for v in lower_vals)
        if has_label:
            score += 5

        code_count = 0
        for v in row_vals:
            if re.match(r'^\d{3,4}$', v):
                code_count += 1
        score += code_count * 2

        if score > best_score:
            best_score = score
            best_row = r_idx

    # Tái cấu trúc DataFrame từ dòng header chuẩn
    raw_headers = [str(x).strip() if pd.notna(x) else '' for x in df_raw.iloc[best_row]]
    headers = []
    seen = {}
    for i, h in enumerate(raw_headers):
        if not h:
            h = f'Unnamed_{i}'
        elif h in seen:
            seen[h] += 1
            h = f'{h}_{seen[h]}'
        else:
            seen[h] = 0
        headers.append(h)

    df = df_raw.iloc[best_row + 1:].copy()
    df.columns = headers
    df.reset_index(drop=True, inplace=True)
    df.dropna(how='all', inplace=True)

    # --- BƯỚC 3: XỬ LÝ THEO 3 ĐỊNH DẠNG ---
    # Trường hợp 1: File đã là dạng danh sách dọc chuẩn DB
    if any('mã đề' in str(c).lower() or 'ma de' in str(c).lower() for c in df.columns) and any('phần' in str(c).lower() or 'phan' in str(c).lower() for c in df.columns):
        col_map = {}
        for c in df.columns:
            cl = str(c).strip().lower()
            if 'mã đề' in cl or 'ma de' in cl: col_map[c] = 'Mã Đề'
            elif 'phần' in cl or 'phan' in cl: col_map[c] = 'Phần'
            elif 'câu' in cl or 'cau' in cl: col_map[c] = 'Câu'
            elif 'ý' in cl or 'y' in cl: col_map[c] = 'Ý'
            elif 'đáp án' in cl or 'dap an' in cl: col_map[c] = 'Đáp Án'
        df_db = df.rename(columns=col_map)
        return df_db, detected_year

    # Xác định các cột mã đề (0501, 0502...) và cột nhãn (Câu, Phần, Vị Trí)
    code_cols = []
    meta_cols = []
    for c in df.columns:
        c_str = str(c).strip()
        m = re.search(r'\b\d{3,4}\b', c_str) or re.search(r'^\d{3,4}$', c_str)
        if m:
            code_cols.append((c, normalize_ma_de(m.group(0))))
        else:
            meta_cols.append(c)

    if not code_cols:
        return pd.DataFrame(), detected_year

    col_cau = None
    col_phan = None
    for c in meta_cols:
        cl = str(c).strip().lower()
        if any(k in cl for k in ['câu', 'cau', 'stt', 'vị trí', 'vi tri']):
            col_cau = c
        elif any(k in cl for k in ['phần', 'phan']):
            col_phan = c

    if not col_cau and meta_cols:
        col_cau = meta_cols[0]
        if len(meta_cols) > 1 and not col_phan:
            col_phan = meta_cols[1]

    rows = []
    current_section = 1
    current_p2_cau = 1

    for idx_row, r_data in df.iterrows():
        raw_cau = str(r_data[col_cau]).strip() if col_cau else str(idx_row)
        raw_phan = str(r_data[col_phan]).strip().upper() if col_phan else ''
        
        # Cập nhật section từ cột Phần nếu có
        if 'II' in raw_phan or '2' in raw_phan:
            current_section = 2
        elif 'I' in raw_phan or '1' in raw_phan:
            current_section = 1

        # Nhận diện dòng chuyển phần xen kẽ đứng độc lập (không có số câu)
        m_has_num = re.search(r'\d+', raw_cau)
        if not m_has_num:
            if any(k in raw_cau.upper() for k in ['PHẦN II', 'PHAN II', 'PHẦN 2', 'ĐÚNG SAI', 'DUNG SAI']):
                current_section = 2
                continue
            elif any(k in raw_cau.upper() for k in ['PHẦN I', 'PHAN I', 'PHẦN 1']):
                current_section = 1
                continue

        if raw_cau.lower() in ('', 'nan', 'none'):
            continue

        # 1. ƯU TIÊN 1: Kiểm tra Phần 2 dạng tách lẻ từng ý (vd: P2 - Câu 1a, Câu 1a, 1a, 1.a)
        m2_single = re.search(r'P2\s*-\s*Câu\s*(\d)\s*([a-d])', raw_cau, re.I) or re.search(r'Câu\s*(\d)\s*[\.\-_/:]?\s*([a-d])', raw_cau, re.I) or re.search(r'^([1-6])\s*[\.\-_/:]?\s*([a-d])$', raw_cau, re.I)
        if m2_single:
            c_p2 = int(m2_single.group(1))
            y_p2 = m2_single.group(2).upper()
            for orig_col, c_code in code_cols:
                v = str(r_data[orig_col]).strip().upper()
                if v in ('Đ', 'D', 'ĐÚNG', 'DUNG', 'TRUE', 'T', '1'):
                    dv = 'Đúng'
                elif v in ('S', 'SAI', 'FALSE', 'F', '0'):
                    dv = 'Sai'
                else:
                    continue
                rows.append({
                    'Mã Đề': c_code,
                    'Phần': 2,
                    'Câu': c_p2,
                    'Ý': y_p2,
                    'Đáp Án': dv
                })
            continue

        # Trường hợp đang ở Phần 2 và cột Câu chỉ chứa ký tự ý 'a', 'b', 'c', 'd'
        m_only_y = re.search(r'^[a-d]$', raw_cau, re.I)
        if m_only_y and current_section == 2:
            y_p2 = m_only_y.group(0).upper()
            for orig_col, c_code in code_cols:
                v = str(r_data[orig_col]).strip().upper()
                if v in ('Đ', 'D', 'ĐÚNG', 'DUNG', 'TRUE', 'T', '1'):
                    dv = 'Đúng'
                elif v in ('S', 'SAI', 'FALSE', 'F', '0'):
                    dv = 'Sai'
                else:
                    continue
                rows.append({
                    'Mã Đề': c_code,
                    'Phần': 2,
                    'Câu': current_p2_cau,
                    'Ý': y_p2,
                    'Đáp Án': dv
                })
            if y_p2 == 'D':
                current_p2_cau += 1
            continue

        # 2. ƯU TIÊN 2: Kiểm tra Phần 2 dạng gộp 4 ý (vd: Câu 25..30 hoặc Câu 1..6 của Phần II có S,D,S,D)
        m_num = re.search(r'\d+', raw_cau)
        num_val = int(m_num.group(0)) if m_num else (idx_row + 1)
        
        is_p2_combined = False
        p2_cau_num = None
        
        if num_val in range(25, 31):
            is_p2_combined = True
            p2_cau_num = num_val - 24 # 25 -> 1, ..., 30 -> 6
        elif ('II' in raw_phan or '2' in raw_phan or current_section == 2) and (num_val in range(1, 7)):
            is_p2_combined = True
            p2_cau_num = num_val
        else:
            sample_val = str(r_data[code_cols[0][0]])
            if parse_p2_val(sample_val) and num_val in range(1, 7):
                is_p2_combined = True
                p2_cau_num = num_val
            
        if is_p2_combined and p2_cau_num:
            current_p2_cau = p2_cau_num
            for orig_col, c_code in code_cols:
                cell_val = r_data[orig_col]
                p2_ans = parse_p2_val(cell_val)
                if p2_ans:
                    for y_idx, y_char in enumerate(['A', 'B', 'C', 'D']):
                        rows.append({
                            'Mã Đề': c_code,
                            'Phần': 2,
                            'Câu': p2_cau_num,
                            'Ý': y_char,
                            'Đáp Án': p2_ans[y_idx]
                        })
            continue

        # 3. ƯU TIÊN 3: Kiểm tra Phần 1 (Câu 1 đến 24)
        if num_val in range(1, 25) and current_section == 1 and not ('II' in raw_phan or '2' in raw_phan):
            for orig_col, c_code in code_cols:
                v = str(r_data[orig_col]).strip().upper()
                if v in ('A', 'B', 'C', 'D'):
                    rows.append({
                        'Mã Đề': c_code,
                        'Phần': 1,
                        'Câu': num_val,
                        'Ý': '',
                        'Đáp Án': v
                    })
            continue

    if rows:
        return pd.DataFrame(rows), detected_year
    return pd.DataFrame(), detected_year


def answer_df_to_matrix(df_all):
    """
    Chuyển DataFrame đáp án dạng danh sách dọc sang ma trận ngang giống bảng của Bộ GD&ĐT:
    - Hàng: Vị trí câu hỏi (P1 - Câu 01..24, P2 - Câu 1a..6d)
    - Cột: Các mã đề thi (0501, 0502...)
    Giúp xem toàn cảnh và chỉnh sửa trực tiếp trên giao diện Streamlit Data Editor.
    """
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
    """
    Chuyển 1 cột trong bảng Ma Trận (tương ứng 1 mã đề) về định dạng danh sách đáp án chuẩn DB:
    Trả về: (DataFrame_chi_tiết, danh_sách_lỗi)
    """
    rows, errors = [], []
    for vi_tri, val in col_series.items():
        if pd.isna(val) or str(val).strip() == "":
            continue
        v = str(val).strip().upper()
        s_pos = str(vi_tri).strip()
        
        # Nhận diện Phần 1: P1 - Câu X, Câu X, hoặc số nguyên 1-24
        m1 = re.search(r'P1\s*-\s*Câu\s*(\d+)', s_pos, re.IGNORECASE) or re.search(r'^Câu\s*([1-9]|1\d|2[0-4])$', s_pos, re.IGNORECASE) or re.search(r'^([1-9]|1\d|2[0-4])$', s_pos)
        # Nhận diện Phần 2: P2 - Câu Xy, Câu Xy, hoặc Xy (1a-6d)
        m2 = re.search(r'P2\s*-\s*Câu\s*(\d)\s*([a-d])', s_pos, re.IGNORECASE) or re.search(r'Câu\s*(\d)\s*([a-d])', s_pos, re.IGNORECASE) or re.search(r'^([1-6])\s*([a-d])$', s_pos, re.IGNORECASE)
        
        if m1:
            cau_num = int(m1.group(1))
            if v not in ("A", "B", "C", "D"):
                errors.append(f"{vi_tri}='{val}'")
                continue
            rows.append({"Phần": 1, "Câu": cau_num, "Ý": "", "Đáp Án": v})
        elif m2:
            cau_num = int(m2.group(1))
            y_char = m2.group(2).upper()
            if v in ("Đ", "D", "ĐÚNG", "DUNG", "TRUE", "T"):
                dv = "Đúng"
            elif v in ("S", "SAI", "FALSE", "F"):
                dv = "Sai"
            else:
                errors.append(f"{vi_tri}='{val}'")
                continue
            rows.append({"Phần": 2, "Câu": cau_num, "Ý": y_char, "Đáp Án": dv})
    return pd.DataFrame(rows), errors


@st.cache_data(show_spinner=False)
def df_to_excel_bytes(df, sheet_name="Sheet1", index=False, index_label=None):
    """
    Xuất DataFrame ra bytes Excel cực nhanh có bộ đệm Cache của Streamlit, loại bỏ độ trễ render lại.
    """
    if df is None or df.empty:
        return b""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=str(sheet_name)[:31], index=index, index_label=index_label)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def dict_to_multisheet_excel_bytes(sheet_dict):
    """
    Xuất nhiều DataFrame ra 1 file Excel đa Sheet có Cache.
    """
    if not sheet_dict:
        return b""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        for sname, df in sheet_dict.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=str(sname)[:31], index=False)
    return buf.getvalue()
