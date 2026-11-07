"""
=============================================================================
MODULE: views/tab_history.py
CHỨC NĂNG:
- Quản lý giao diện Tab 2: Lịch Sử Đợt Chấm Thi (MongoDB Collections: grading_batches & exam_results).
- Thống kê toàn cảnh hệ thống: tổng số đợt thi, tổng bài đã chấm, phổ điểm trung bình.
- Truy xuất tức thì dữ liệu các đợt thi cũ mà không cần tốn token AI.
- Tải lại báo cáo Excel đa Sheet của bất kỳ đợt chấm nào trong lịch sử.
- Chế độ xem thông minh: 'Từng bài thi' (phân trang nhẹ nhàng, không lag UI) và 'Tất cả bài thi'.
- Xem chi tiết từng câu hỏi, giải thích và JSON gốc bài làm của AI.
- Quản trị xóa đợt chấm lỗi thời khỏi cơ sở dữ liệu.
=============================================================================
"""

import json
import pandas as pd
import streamlit as st

from core.database import (
    get_all_batches_from_db,
    get_batch_exam_results,
    delete_batch_from_db,
)
from core.excel_utils import df_to_excel_bytes, dict_to_multisheet_excel_bytes
from core.grading_logic import render_comparison_detail_table


def render_tab_history(mongo_uri: str):
    """
    Render giao diện và xử lý lịch sử đợt chấm thi tại Tab 2.
    
    Tham số:
    - mongo_uri: Chuỗi kết nối MongoDB Atlas để truy vấn dữ liệu.
    """
    st.subheader(":material/history_edu: Quản Lý & Xem Lại Các Đợt Chấm Thi")
   

    if not mongo_uri:
        st.warning("Chưa cấu hình MONGODB_URI trong file .env!")
        return

    # [QUAN TRỌNG] Lấy danh sách các đợt thi (sử dụng Cache RAM trong core/database.py)
    batches = get_all_batches_from_db(mongo_uri)
    if not batches:
        st.info("Chưa có đợt chấm thi nào được lưu trong cơ sở dữ liệu MongoDB.")
        st.caption("Bạn có thể tạo nhanh một đợt chấm mẫu giả lập (0 token) để xem trước toàn bộ giao diện bảng biểu, thống kê và báo cáo Excel:")
        if st.button("Tạo Đợt Chấm Mẫu Demo Cho Tab 2 (0 Token)", icon=":material/visibility:", type="primary"):
            from core.mock_data import create_demo_batch_in_db
            ok, b_id = create_demo_batch_in_db(mongo_uri, nam_thi="2026")
            if ok:
                st.success(f"Đã tạo thành công đợt chấm mẫu: {b_id}")
                st.rerun()
            else:
                st.error(f"Lỗi: {b_id}")
        return

    # =========================================================================
    # METRICS TỔNG QUAN TOÀN HỆ THỐNG
    # =========================================================================
    m1, m2, m3 = st.columns(3)
    m1.metric("Tổng Số Đợt Chấm", len(batches))
    tong_so_bai = sum(b.get("tong_so_de", 0) for b in batches)
    m2.metric("Tổng Số Bài Thi Đã Chấm", tong_so_bai)
    all_avg = [b.get("diem_trung_binh") for b in batches if b.get("diem_trung_binh") is not None]
    avg_val = round(sum(all_avg) / len(all_avg), 2) if all_avg else 0
    m3.metric("Điểm Trung Bình Toàn Hệ Thống", f"{avg_val} / 10")

    # =========================================================================
    # BẢNG DANH SÁCH CÁC ĐỢT CHẤM THI
    # =========================================================================
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
    st.subheader(":material/manage_search: Chi Tiết Đợt Chấm & Tải Lại Báo Cáo")

    selected_batch_id = st.selectbox(
        "Chọn Đợt Chấm Cần Xem Lại:",
        options=[b.get("batch_id") for b in batches],
        format_func=lambda x: f"{x} - {next((b.get('ten_dot_thi') for b in batches if b.get('batch_id') == x), '')}"
    )

    if not selected_batch_id:
        return

    # [QUAN TRỌNG] Lấy chi tiết các bài thi thuộc đợt thi được chọn
    exam_docs = get_batch_exam_results(mongo_uri, selected_batch_id)
    if not exam_docs:
        st.info("Không tìm thấy chi tiết bài thi nào trong đợt này.")
        return

    st.markdown(f"#### :material/analytics: Tổng Hợp Điểm Số ({len(exam_docs)} bài thi):")

    hist_summaries = []
    hist_details = []
    for edoc in exam_docs:
        lat = edoc.get("thoi_gian_xu_ly_s")
        if lat is None or lat == "":
            lat = edoc.get("latency_sec", "-")

        tin = edoc.get("token_vao")
        if tin is None or tin == "":
            tin = edoc.get("token_in", "-")

        tout = edoc.get("token_ra")
        if tout is None or tout == "":
            tout = edoc.get("token_out", "-")

        tth = edoc.get("token_nghi")
        if tth is None or tth == "":
            tth = edoc.get("token_thought", "-")

        cost = edoc.get("chi_phi_vnd")
        if cost is None or cost == "":
            cost = edoc.get("cost_vnd", "-")

        hist_summaries.append({
            "Mã Đề": edoc.get("ma_de"),
            "Năm Thi": edoc.get("nam_thi", "-"),
            "Tên File": edoc.get("ten_file"),
            "Điểm (Hệ 10)": edoc.get("diem_so"),
            "Số câu đúng": edoc.get("so_cau_dung"),
            "Tổng số câu": edoc.get("tong_so_cau"),
            "Tỷ lệ đúng (%)": edoc.get("ty_le_dung_phan_tram"),
            "P1 Trắc nghiệm": f"{edoc.get('thong_ke_phan_1', {}).get('so_cau_dung')}/{edoc.get('thong_ke_phan_1', {}).get('tong_so_cau')}",
            "P2 Đúng/Sai": f"{edoc.get('thong_ke_phan_2', {}).get('so_y_dung')}/{edoc.get('thong_ke_phan_2', {}).get('tong_so_y')}",
            "Model AI": edoc.get("model_ai", "-"),
            "Thời gian (s)": lat,
            "Token Vào": tin,
            "Token Ra": tout,
            "Token Nghĩ": tth,
            "Chi Phí (VNĐ)": cost,
            "Thời Gian Chấm": edoc.get("thoi_gian_cham")
        })
        for row in edoc.get("chi_tiet_doi_sanh", []):
            hist_details.append(row)

    hist_sum_df = pd.DataFrame(hist_summaries)
    st.dataframe(hist_sum_df, use_container_width=True)

    # Đóng gói xuất file Excel đa Sheet cho đợt thi trong lịch sử
    sheet_dict = {}
    if hist_details:
        sheet_dict['Chi Tiết Từng Câu Hỏi'] = pd.DataFrame(hist_details)
    sheet_dict['Tổng Hợp Điểm Số'] = hist_sum_df

    c_h1, c_h2 = st.columns([3, 1])
    with c_h1:
        st.download_button(
            label="Tải Toàn Bộ Báo Cáo Đợt Chấm (Excel .xlsx)",
            icon=":material/download:",
            data=dict_to_multisheet_excel_bytes(sheet_dict),
            file_name=f'bao_cao_lich_su_{selected_batch_id}.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            type="primary",
            use_container_width=True
        )
    with c_h2:
        if st.button(f"Xóa Đợt Chấm {selected_batch_id}", icon=":material/delete:", type="secondary", use_container_width=True):
            ok_del, msg_del = delete_batch_from_db(mongo_uri, selected_batch_id)
            if ok_del:
                st.success(msg_del)
                st.rerun()
            else:
                st.error(msg_del)

    st.markdown("---")
    st.subheader(f":material/description: Chi Tiết Từng Bài Thi & Bài Giải AI Trong Đợt `{selected_batch_id}`")

    # [QUAN TRỌNG] Tối ưu hóa hiển thị khi đợt có nhiều bài thi (tránh render đồng thời hàng chục bảng gây giật lag trình duyệt)
    if len(exam_docs) > 1:
        exam_labels = []
        for e in exam_docs:
            lat = e.get("thoi_gian_xu_ly_s") if e.get("thoi_gian_xu_ly_s") is not None else e.get("latency_sec", "-")
            cost = e.get("chi_phi_vnd") if e.get("chi_phi_vnd") is not None else e.get("cost_vnd", "-")
            exam_labels.append(f"Đề {e.get('ma_de', 'N/A')} ({e.get('ten_file', '')}) — {e.get('diem_so', 0)}/10 điểm | {lat}s | {cost} VNĐ")

        view_mode = st.radio(
            "Chế độ hiển thị:",
            [":material/description: Từng bài thi", ":material/view_agenda: Tất cả bài thi"],
            horizontal=True,
            key=f"view_mode_{selected_batch_id}"
        )
        if "Từng bài thi" in view_mode:
            sel_idx = st.selectbox(
                "Chọn bài thi:",
                range(len(exam_docs)),
                format_func=lambda i: exam_labels[i]
            )
            selected_docs = [(sel_idx, exam_docs[sel_idx])]
        else:
            selected_docs = list(enumerate(exam_docs))
    else:
        selected_docs = list(enumerate(exam_docs))

    # =========================================================================
    # RENDER CHI TIẾT CÂU TRẢ LỜI & GIẢI THÍCH TỪNG ĐỀ THI
    # =========================================================================
    for idx_e, edoc in selected_docs:
        e_ma_de = edoc.get("ma_de")
        e_file = edoc.get("ten_file")
        e_score = edoc.get("diem_so")
        e_dung = edoc.get("so_cau_dung")
        e_tong = edoc.get("tong_so_cau")
        e_lat = edoc.get("thoi_gian_xu_ly_s") if edoc.get("thoi_gian_xu_ly_s") is not None else edoc.get("latency_sec", "-")
        e_tin = edoc.get("token_vao") if edoc.get("token_vao") is not None else edoc.get("token_in", "-")
        e_tout = edoc.get("token_ra") if edoc.get("token_ra") is not None else edoc.get("token_out", "-")
        e_tth = edoc.get("token_nghi") if edoc.get("token_nghi") is not None else edoc.get("token_thought", "-")
        e_cost = edoc.get("chi_phi_vnd") if edoc.get("chi_phi_vnd") is not None else edoc.get("cost_vnd", "-")

        with st.expander(f":material/assignment: Đề {e_ma_de} (Tệp: {e_file}) — Điểm: {e_score}/10 (Đúng {e_dung}/{e_tong} câu/ý) | {e_lat}s | {e_cost} VNĐ", expanded=True):
            # Thanh hiển thị Metrics hiệu năng của riêng bài thi này
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Thời Gian Xử Lý", f"{e_lat} s" if e_lat != "-" else "-")
            m2.metric("Chi Phí API", f"{e_cost} VNĐ" if e_cost != "-" else "-")
            m3.metric("Token Vào (Prompt)", f"{e_tin:,}" if isinstance(e_tin, (int, float)) else str(e_tin))
            m4.metric("Token Ra (Candidate)", f"{e_tout:,}" if isinstance(e_tout, (int, float)) else str(e_tout))
            m5.metric("Token Nghĩ (Thinking)", f"{e_tth:,}" if isinstance(e_tth, (int, float)) else str(e_tth))
            chi_tiet_list = edoc.get("chi_tiet_doi_sanh", [])
            if chi_tiet_list:
                df_e_detail = pd.DataFrame(chi_tiet_list)
                if not df_e_detail.empty:
                    df_e_detail.index = range(1, len(df_e_detail) + 1)
                render_comparison_detail_table(df_e_detail, key_suffix=f"hist_{e_ma_de}_{idx_e}")

                st.download_button(
                    label=f"Tải Chi Tiết Đề {e_ma_de} (Excel .xlsx)",
                    icon=":material/download:",
                    data=df_to_excel_bytes(df_e_detail, sheet_name=f'Đề {e_ma_de}', index=True, index_label='STT'),
                    file_name=f"chi_tiet_de_{e_ma_de}_{selected_batch_id}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_hist_detail_{e_ma_de}_{idx_e}",
                    use_container_width=True
                )
