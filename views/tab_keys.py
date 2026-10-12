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
    cleanup_duplicate_answer_keys,
    delete_all_answer_keys_in_year,
)


def render_tab_keys(gemini_api_key: str, mongo_uri: str, model_choice: str):
    """
    Render giao diện và xử lý Ngân Hàng Đáp Án Chuẩn tại Tab 3.
    
    Tham số:
    - gemini_api_key: Khóa API Gemini để bóc tách file PDF đáp án.
    - mongo_uri: Chuỗi kết nối MongoDB Atlas để lưu/truy vấn đáp án.
    - model_choice: Model AI sử dụng để OCR PDF.
    """
    st.subheader("🗄️ Ngân Hàng Đáp Án Chuẩn Của Bộ GD&ĐT")
    st.caption(
        "Quản lý toàn bộ 48 mã đề theo định dạng Ma trận giống đề gốc của Bộ GD&ĐT. "
        "Dữ liệu được lưu vĩnh viễn trên MongoDB, hỗ trợ rà soát nhanh các câu bị mộc đỏ che và khóa bảo vệ 100%."
    )

    if not mongo_uri:
        st.warning("⚠️ Chưa cấu hình MONGODB_URI trong file .env!")
        return

    all_keys_summary_check = get_all_answer_keys_summary(mongo_uri)
    has_existing_keys = len(all_keys_summary_check) > 0

    # =========================================================================
    # BƯỚC 1: NẠP FILE ĐÁP ÁN GỐC (PDF / EXCEL / CSV) - CHỈ LÀM 1 LẦN
    # =========================================================================
    with st.expander(
        "📤 Nạp File Đáp Án Gốc Vào Ngân Hàng (PDF / Excel / CSV) — Chỉ Cần Làm 1 Lần",
        expanded=not has_existing_keys
    ):
        st.caption(
            "💡 Hệ thống tự liệt kê TẤT CẢ mã đề có trong file PDF (vd: 48 mã), "
            "bóc tách song song theo từng đợt để không bị cắt cụt, rồi lưu hết vào MongoDB. "
            "Các lần chấm sau không cần nạp lại file đáp án."
        )
        col_u1, col_u2 = st.columns([3, 1])
        with col_u1:
            extra_key_file = st.file_uploader(
                "Tải lên file Đáp án (PDF/Excel/CSV) để lưu vào ngân hàng:",
                type=['pdf', 'csv', 'xlsx', 'xls'],
                key="extra_key_uploader"
            )
        with col_u2:
            custom_year = st.selectbox("Năm Thi Của File:", ["2025", "2026", "2027", "2028"], index=0)
            allow_force = st.checkbox(
                "Ghi đè cả mã đã duyệt",
                value=False,
                help="Chỉ tích nếu bạn muốn hủy khóa bảo vệ và ghi đè lại toàn bộ bằng file mới."
            )

        if extra_key_file and st.button("🚀 Quét Toàn Bộ & Lưu Vào Ngân Hàng", type="primary"):
            try:
                df_ext = None
                detected_year = custom_year
                missing_codes = []
                f_name_lower = extra_key_file.name.lower()

                # Trường hợp 1: File bảng tính Excel / CSV
                if f_name_lower.endswith(('.csv', '.xlsx', '.xls')):
                    res_parse = parse_answer_excel_or_csv(extra_key_file)
                    if isinstance(res_parse, tuple):
                        df_ext, y_excel = res_parse
                    else:
                        df_ext, y_excel = res_parse, None

                    detected_year = custom_year if custom_year != "2025" else (y_excel or custom_year)
                    if y_excel and y_excel != custom_year and custom_year == "2025":
                        st.info(f"📅 Tự động nhận diện năm thi: **{detected_year}** từ nội dung/tiêu đề file.")

                    if df_ext is not None and not df_ext.empty and 'Mã Đề' in df_ext.columns:
                        all_codes = sorted(df_ext['Mã Đề'].unique().tolist())
                        st.info(f"📑 Đã đọc thành công **{len(all_codes)} mã đề** từ file Excel/CSV: {', '.join(all_codes)}")

                # Trường hợp 2: File PDF bảng in ngang mộc đỏ
                elif f_name_lower.endswith('.pdf'):
                    if not gemini_api_key:
                        st.error("⚠️ Chưa cấu hình GEMINI_API_KEY trong file .env!")
                        st.stop()
                    prog = st.progress(0.0)
                    prog_txt = st.empty()

                    def _cb(p, msg):
                        prog.progress(min(max(p, 0.0), 1.0))
                        prog_txt.info(msg)

                    # [QUAN TRỌNG] Bóc tách phân mảnh chống nghẽn và đọc xuyên mộc đỏ
                    df_ext, y_found, all_codes, missing_codes = parse_full_answer_key_pdf(
                        gemini_api_key, extra_key_file, model_name=model_choice, progress_cb=_cb
                    )
                    detected_year = custom_year if custom_year != "2025" else (y_found or custom_year)
                    st.info(f"📑 Phát hiện **{len(all_codes)} mã đề** trong file: {', '.join(all_codes)}")

                if df_ext is None or df_ext.empty:
                    st.error("❌ Không bóc tách được dữ liệu đáp án từ file.")
                else:
                    df_ext['Mã Đề'] = df_ext['Mã Đề'].map(normalize_ma_de)
                    # [QUAN TRỌNG] Lưu vào MongoDB kèm bảo vệ mã đề đã duyệt
                    ok, msg = save_answer_keys_to_db(
                        mongo_uri, df_ext, nam_thi=detected_year,
                        source_name=extra_key_file.name, allow_overwrite_verified=allow_force
                    )
                    if ok:
                        get_all_answer_keys_dataframe.clear()
                        df_to_excel_bytes.clear()
                        st.session_state["matrix_year"] = str(detected_year)
                        st.success(f"🎉 {msg} (Năm {detected_year})")
                        if missing_codes:
                            st.warning(
                                f"⚠️ Các mã chưa đọc đủ 48 câu/ý (cần kiểm tra/sửa tay trong Ma Trận bên dưới): "
                                f"**{', '.join(missing_codes)}**"
                            )
                        st.rerun()
                    else:
                        st.error(f"❌ {msg}")
            except Exception as e:
                st.error(f"Lỗi: {e}")

    # =========================================================================
    # BƯỚC 2: MA TRẬN ĐÁP ÁN TOÀN BỘ (RÀ SOÁT, SỬA CHỮA & KHÓA BẢO VỆ)
    # =========================================================================
    st.markdown("---")
    c_head1, c_head2 = st.columns([2, 1])
    with c_head1:
        st.subheader("🧮 Ma Trận Đáp Án Toàn Bộ")
        st.caption(
            "Bố cục chuẩn Bộ GD&ĐT: **hàng = câu/ý**, **cột = mã đề**. "
            "Phần I nhập A/B/C/D; Phần II nhập **Đ** (Đúng) hoặc **S** (Sai)."
        )
    with c_head2:
        mat_year = st.selectbox("Chọn Năm Thi Cần Quản Lý:", ["2025", "2026", "2027", "2028"], index=0, key="matrix_year")

    # Truy vấn toàn bộ đáp án của năm đã chọn
    df_year_all = get_all_answer_keys_dataframe(mongo_uri, nam_thi=mat_year)
    if df_year_all.empty:
        st.info(f"ℹ️ Chưa có dữ liệu đáp án năm {mat_year} trong MongoDB. Hãy mở rộng phần '📤 Nạp File Đáp Án Gốc' ở trên để nạp file PDF đáp án.")
        return

    # Biến đổi thành dạng bảng Ma trận xoay chiều (Pivot Matrix)
    mat_orig = answer_df_to_matrix(df_year_all)
    summary_keys = get_all_answer_keys_summary(mongo_uri, nam_thi=mat_year)
    verified_codes = {normalize_ma_de(k.get("ma_de")) for k in summary_keys if k.get("trang_thai") == "da_xac_thuc"}
    all_matrix_codes = set(mat_orig.columns)
    num_total = len(all_matrix_codes)
    num_verified = len(verified_codes & all_matrix_codes)
    num_unverified = num_total - num_verified
    incomplete = [c for c in mat_orig.columns if (mat_orig[c] == "").sum() > 0 or len(mat_orig) < 48]

    # Metrics trạng thái duyệt và rà soát
    m_c1, m_c2, m_c3, m_c4 = st.columns(4)
    m_c1.metric("Tổng Số Mã Đề", f"{num_total} mã")
    m_c2.metric("🟢 Đã Duyệt (Khóa An Toàn)", f"{num_verified} mã")
    m_c3.metric("🟡 Chưa Duyệt (Tự Động)", f"{num_unverified} mã")
    m_c4.metric("⚠️ Cần Rà Soát (Ô trống)", f"{len(incomplete)} mã")

    if incomplete:
        st.warning(
            f"⚠️ Các mã đề còn ô trống (do mộc che hoặc trang scan mờ): **{', '.join(incomplete)}**. "
            f"Vui lòng click trực tiếp vào ô tương ứng trong bảng bên dưới để gõ bổ sung!"
        )

    # [QUAN TRỌNG] Hiển thị Ma Trận cho phép người dùng click sửa trực tiếp
    mat_edited = st.data_editor(
        mat_orig,
        use_container_width=True,
        height=580,
        key=f"matrix_editor_{mat_year}"
    )

    # =========================================================================
    # THANH CÔNG CỤ HÀNH ĐỘNG (ACTION BAR)
    # =========================================================================
    col_btn1, col_btn2 = st.columns([3, 2])
    with col_btn1:
        if st.button(
            f"💾 Lưu & Khóa Phê Duyệt Toàn Bộ ({num_total} Mã Đề)",
            type="primary",
            use_container_width=True,
            key="btn_save_and_verify_all",
            help="Lưu ngay các ô vừa sửa vào MongoDB và chuyển tất cả các mã đề sang trạng thái 🟢 ĐÃ DUYỆT (Khóa an toàn vĩnh viễn chống ghi đè)"
        ):
            changed_codes = [
                c for c in mat_orig.columns
                if not mat_orig[c].astype(str).str.strip().str.upper().equals(mat_edited[c].astype(str).str.strip().str.upper())
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

    # =========================================================================
    # CÔNG CỤ QUẢN TRỊ NÂNG CAO
    # =========================================================================
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
