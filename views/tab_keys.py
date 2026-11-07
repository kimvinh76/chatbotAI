"""
=============================================================================
MODULE: views/tab_keys.py
CHỨC NĂNG:
- Quản lý giao diện Tab 3: Ngân Hàng Đáp Án Chuẩn (Collection: answer_keys).
- Nạp file đáp án gốc (PDF bảng in ngang mộc đỏ, Excel, CSV) - chỉ cần làm 1 lần.
- Đọc phân đợt song song (Chunking) đối với PDF 48 mã đề để không bị giới hạn token/RPM.
- Bóc tách xuyên qua con dấu mộc đỏ bằng AI Multimodal Vision và tách lớp màu.
- Giao diện Ma Trận toàn cảnh: Bố cục giống đề Bộ GD&ĐT (Hàng = Câu/Ý, Cột = Mã đề).
- Cho phép rà soát và chỉnh sửa trực tiếp các ô mộc che bằng st.data_editor.
- Cơ chế 'Khóa An Toàn / Phê Duyệt': Đánh dấu 'da_xac_thuc' để ngăn vĩnh viễn không cho file mới ghi đè.
- Công cụ dọn dẹp mã đề 3 chữ số gộp về 4 chữ số chuẩn.
=============================================================================
"""

import pandas as pd
import streamlit as st

from core.excel_utils import (
    normalize_ma_de,
    parse_answer_excel_or_csv,
    answer_df_to_matrix,
    matrix_column_to_items,
    df_to_excel_bytes,
)
from core.ai_grader import parse_full_answer_key_pdf
from core.database import (
    save_answer_keys_to_db,
    get_all_answer_keys_summary,
    get_all_answer_keys_dataframe,
    update_single_answer_key,
    verify_all_answer_keys_in_year,
)


def render_tab_keys(gemini_api_key: str, mongo_uri: str, model_choice: str):
    """
    Render giao diện và xử lý Ngân Hàng Đáp Án Chuẩn tại Tab 3.
    
    Tham số:
    - gemini_api_key: Khóa API Gemini để bóc tách file PDF đáp án.
    - mongo_uri: Chuỗi kết nối MongoDB Atlas để lưu/truy vấn đáp án.
    - model_choice: Model AI sử dụng để OCR PDF.
    """
    if "pending_matrix_year" in st.session_state:
        st.session_state["matrix_year"] = st.session_state.pop("pending_matrix_year")

    c_head1, c_head2 = st.columns([3, 1])
    with c_head1:
        st.subheader(":material/database: Ngân Hàng Đáp Án Chuẩn")
        st.caption("Quản lý ngân hàng đáp án theo định dạng Ma trận chuẩn Bộ GD&ĐT.")
    with c_head2:
        mat_year = st.selectbox("Năm Thi Quản Lý:", ["2025", "2026", "2027", "2028"], index=0, key="matrix_year")

    if "keys_flash_msg" in st.session_state:
        f_type, f_msg = st.session_state.pop("keys_flash_msg")
        if f_type == "success":
            st.success(f_msg)
        elif f_type == "warning":
            st.warning(f_msg)
        else:
            st.info(f_msg)

    if "keys_flash_missing" in st.session_state:
        m_codes = st.session_state.pop("keys_flash_missing")
        st.warning(f"Các mã chưa hoàn tất dữ liệu (cần kiểm tra/sửa tay trong Ma Trận bên dưới): **{', '.join(m_codes)}**")

    if not mongo_uri:
        st.warning("Chưa cấu hình MONGODB_URI trong file .env!")
        return

    # Truy vấn toàn bộ đáp án của năm đã chọn
    df_year_all = get_all_answer_keys_dataframe(mongo_uri, nam_thi=mat_year)
    has_data_this_year = not df_year_all.empty

    # =========================================================================
    # NẠP FILE ĐÁP ÁN (EXCEL / PDF) - TỰ ĐỘNG THU GỌN KHI ĐÃ CÓ DỮ LIỆU
    # =========================================================================
    with st.expander(
        f":material/upload_file: Nạp File Đáp Án (Excel / PDF) — Năm {mat_year}",
        expanded=not has_data_this_year
    ):
        col_u1, col_u2 = st.columns([3, 1])
        with col_u1:
            extra_key_file = st.file_uploader(
                f"Tải lên file đáp án (.xlsx, .csv, .pdf) cho năm {mat_year}:",
                type=['pdf', 'csv', 'xlsx', 'xls'],
                key=f"extra_key_uploader_{mat_year}"
            )
        with col_u2:
            st.write("")
            st.write("")
            allow_force = st.checkbox(
                "Ghi đè mã đã khóa",
                value=False,
                help="Mặc định hệ thống luôn bảo vệ các mã đã khóa. Chỉ tích chọn nếu bạn muốn nạp đè file mới."
            )

        if extra_key_file and st.button(f"Đọc File & Lưu Vào Năm {mat_year}", icon=":material/save:", type="primary"):
            try:
                df_ext = None
                detected_year = mat_year
                missing_codes = []
                f_name_lower = extra_key_file.name.lower()

                # Trường hợp 1: File bảng tính Excel / CSV (Miễn phí 100% API Token)
                if f_name_lower.endswith(('.csv', '.xlsx', '.xls')):
                    res_parse = parse_answer_excel_or_csv(extra_key_file)
                    if isinstance(res_parse, tuple):
                        df_ext, y_excel = res_parse
                    else:
                        df_ext, y_excel = res_parse, None

                    if y_excel and y_excel != mat_year:
                        detected_year = y_excel

                # Trường hợp 2: File PDF bảng in ngang mộc đỏ (Xử lý qua Gemini AI Vision)
                elif f_name_lower.endswith('.pdf'):
                    if not gemini_api_key:
                        st.error("Chưa cấu hình GEMINI_API_KEY trong file .env!")
                        st.stop()
                    prog = st.progress(0.0)
                    prog_txt = st.empty()

                    def _cb(p, msg):
                        prog.progress(min(max(p, 0.0), 1.0))
                        prog_txt.info(msg)

                    df_ext, y_found, all_codes, missing_codes = parse_full_answer_key_pdf(
                        gemini_api_key, extra_key_file, model_name=model_choice, progress_cb=_cb
                    )
                    if y_found and y_found != mat_year:
                        detected_year = y_found

                if df_ext is None or df_ext.empty:
                    st.error("Không bóc tách được dữ liệu đáp án từ file.")
                else:
                    df_ext['Mã Đề'] = df_ext['Mã Đề'].map(normalize_ma_de)
                    ok, msg = save_answer_keys_to_db(
                        mongo_uri, df_ext, nam_thi=detected_year,
                        source_name=extra_key_file.name, allow_overwrite_verified=allow_force
                    )
                    if ok:
                        get_all_answer_keys_dataframe.clear()
                        df_to_excel_bytes.clear()
                        if str(detected_year) != str(mat_year):
                            st.session_state["pending_matrix_year"] = str(detected_year)
                        st.session_state["keys_flash_msg"] = ("success", f":material/check_circle: {msg}")
                        if missing_codes:
                            st.session_state["keys_flash_missing"] = missing_codes
                        st.rerun()
                    else:
                        st.error(f":material/error: {msg}")
            except Exception as e:
                st.error(f"Lỗi: {e}")

    # =========================================================================
    # BƯỚC 2: MA TRẬN ĐÁP ÁN TOÀN BỘ (RÀ SOÁT, SỬA CHỮA & KHÓA)
    # =========================================================================
    st.markdown("---")
    if df_year_all.empty:
        st.info(f"Chưa có dữ liệu đáp án năm {mat_year} trong MongoDB. Vui lòng mở khung 'Nạp File Đáp Án' ở trên để nạp file Excel hoặc PDF.")
        return

    # Biến đổi thành dạng bảng Ma trận xoay chiều (Pivot Matrix)
    mat_orig = answer_df_to_matrix(df_year_all)

    st.subheader(f":material/grid_on: Ma Trận Đáp Án Năm {mat_year}")
    st.caption("Bố cục chuẩn Bộ GD&ĐT: hàng = câu/ý, cột = mã đề. Phần I: A/B/C/D; Phần II: Đ (Đúng) hoặc S (Sai).")
    
    # Định nghĩa danh sách 4 mã đề thực nghiệm đại diện của từng năm (khớp với Chương 3)
    BENCHMARK_CODES = {
        "2025": ["0501", "0504", "0510", "0511"],
        "2026": ["0501", "0502", "0526", "0541"]
    }

    # BỘ LỌC CHẾ ĐỘ HIỂN THỊ (Giúp bảo vệ báo cáo & demo không bị bắt bẻ số lượng)
    c_flt1, c_flt2 = st.columns([3, 2])
    with c_flt1:
        view_mode = st.radio(
            "Chế độ hiển thị Ma Trận:",
            [
                f":material/target: 4 Mã Đề Thực Nghiệm Đồ Án ({mat_year})",
                f":material/public: Toàn Bộ Ngân Hàng Quốc Gia ({len(mat_orig.columns)} Mã Đề)"
            ],
            horizontal=True,
            key=f"view_mode_mat_{mat_year}"
        )

    # Lọc cột hiển thị theo chế độ
    bm_codes = BENCHMARK_CODES.get(mat_year, [])
    if view_mode.startswith(":material/target:"):
        selected_cols = [c for c in bm_codes if c in mat_orig.columns]
        if not selected_cols:
            selected_cols = list(mat_orig.columns)[:4]
        mat_display = mat_orig[selected_cols]
    else:
        mat_display = mat_orig

    summary_keys = get_all_answer_keys_summary(mongo_uri, nam_thi=mat_year)
    verified_codes = {normalize_ma_de(k.get("ma_de")) for k in summary_keys if k.get("trang_thai") == "da_xac_thuc"}
    all_matrix_codes = set(mat_display.columns)
    num_total = len(all_matrix_codes)
    num_verified = len(verified_codes & all_matrix_codes)
    num_unverified = num_total - num_verified
    incomplete = [c for c in mat_display.columns if (mat_display[c].astype(str).str.strip().isin(["", "nan", "None"])).any()]

    # Tóm tắt thông tin ma trận
    m_c1, m_c2, m_c3 = st.columns(3)
    m_c1.metric("Số Mã Đề", f"{num_total} mã")

    is_all_locked = (num_verified == num_total and num_total > 0)
    m_c2.metric("Trạng Thái", "Đã Khóa" if is_all_locked else "Chưa Khóa")

    has_empty = len(incomplete) > 0
    m_c3.metric("Dữ Liệu", "Còn Ô Trống" if has_empty else "Đầy Đủ")

    if incomplete:
        st.warning(
            f"Các mã đề còn ô trống: **{', '.join(incomplete)}**. "
            f"Vui lòng click trực tiếp vào ô tương ứng trong bảng bên dưới để điền bổ sung!"
        )

    # [QUAN TRỌNG] Hiển thị Ma Trận cho phép người dùng click sửa trực tiếp
    mat_edited = st.data_editor(
        mat_display,
        use_container_width=True,
        height=580,
        key=f"matrix_editor_{mat_year}_{'bm' if view_mode.startswith(':material/target:') else 'all'}"
    )

    # =========================================================================
    # THANH CÔNG CỤ HÀNH ĐỘNG (ACTION BAR)
    # =========================================================================
    col_btn1, col_btn2 = st.columns([3, 2])
    with col_btn1:
        if st.button(
            f"Lưu & Khóa Đáp Án ({num_total} Mã Đề)",
            icon=":material/lock:",
            type="primary",
            use_container_width=True,
            key=f"btn_save_and_verify_{mat_year}",
            help="Lưu các ô vừa sửa vào MongoDB và khóa bảo vệ dữ liệu"
        ):
            changed_codes = [
                c for c in mat_display.columns
                if not mat_display[c].astype(str).str.strip().str.upper().equals(mat_edited[c].astype(str).str.strip().str.upper())
            ]
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
                st.error("Một số ô có giá trị không hợp lệ: " + " | ".join(all_errors))
            else:
                if saved:
                    st.success(f"Đã lưu {len(saved)} mã vừa sửa ({', '.join(saved)}) và khóa thành công!")
                else:
                    st.success(f"Đã lưu và khóa toàn bộ {num_total} mã đề năm {mat_year} thành công!")
                st.rerun()

    with col_btn2:
        st.download_button(
            label=f"Xuất Ma Trận ({num_total} Mã Đề - Excel)",
            icon=":material/download:",
            data=df_to_excel_bytes(mat_edited, sheet_name=f'MaTran_{mat_year}', index=True, index_label='Câu/Ý'),
            file_name=f"ma_tran_dap_an_{mat_year}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"dl_matrix_xlsx_{mat_year}"
        )
