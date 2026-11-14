"""
=============================================================================
MODULE: views/tab_grading.py
CHỨC NĂNG:
- Quản lý giao diện Tab 1: Chấm Thi Tự Động (Batch Grader).
- Xử lý tải lên 1 hoặc nhiều file PDF đề thi scan/ảnh hoặc PDF text.
- Nhận diện tự động Mã Đề & Năm Thi trực tiếp từ tài liệu.
- Cơ chế Cache bài giải thông minh: kiểm tra chất lượng giải, phát hiện bài cũ thiếu giải thích Phần II để ép AI giải lại.
- Tùy chọn 'Bắt buộc giải lại đề (Bỏ qua Cache)' cho phép người dùng chủ động ép làm mới.
- Tự động lấy đáp án chuẩn từ MongoDB (ưu tiên bản đã duyệt) để đối sánh và chấm điểm hệ 10.
- Xuất báo cáo điểm tổng hợp & chi tiết đa Sheet ra file Excel (.xlsx).
=============================================================================
"""

import io
import json
import time
from datetime import datetime
import pandas as pd
import streamlit as st

from core.pdf_utils import extract_text_from_pdf, detect_metadata_from_file_and_text
from core.ai_grader import call_gemini_api, _is_valid_exp
from core.mock_data import generate_mock_exam_solution
from core.database import (
    get_solved_exam_cache,
    save_solved_exam_cache,
    check_verified_answer_key,
    get_answer_keys_from_db,
    save_to_mongodb,
    save_grading_batch,
)
from core.grading_logic import (
    build_comparison_and_detail_df,
    render_comparison_detail_table,
    calculate_moet_scores,
)
from core.excel_utils import df_to_excel_bytes, normalize_ma_de


def render_tab_grading(gemini_api_key: str, mongo_uri: str, model_choice: str, use_cache: bool, mock_mode: bool = False):
    """
    Render giao diện và điều phối luồng xử lý của Tab 1: Chấm Thi Tự Động.
    
    Tham số:
    - gemini_api_key: Khóa bí mật gọi Google Gemini API
    - mongo_uri: Chuỗi kết nối MongoDB Atlas
    - model_choice: Model AI đang chọn (Flash 3.8 hoặc Pro 3.1)
    - use_cache: Bật/Tắt tính năng dùng lại bài giải đã lưu
    - mock_mode: Chế độ chạy thử nghiệm giao diện (0 token API)
    """
    if mock_mode:
        st.warning("**Chế độ Mô Phỏng (Dry-Run / 0 Token) đang BẬT:** Hệ thống sẽ sinh bài giải giả lập sát thực tế để kiểm tra giao diện mà KHÔNG gọi Gemini API.", icon=":material/science:")

    st.subheader(":material/upload_file: Tải Lên Đề Thi (PDF)")
    st.caption(
        "Hệ thống tự động nhận diện Mã Đề & Năm Thi từ đề thi, sau đó đối soát trực tiếp "
        "với **Ngân Hàng Đáp Án Chuẩn** trong MongoDB (quản lý tại Tab 3) mà không cần tải kèm file đáp án."
    )

    pdf_files = st.file_uploader(
        "Kéo thả 1 hoặc nhiều file PDF đề thi để bắt đầu chấm:",
        type=['pdf'],
        accept_multiple_files=True
    )

    if st.button("Bắt Đầu Chấm Thi Hàng Loạt", icon=":material/play_circle:", use_container_width=True, type="primary"):
        if not gemini_api_key and not mock_mode:
            st.error("Vui lòng cấu hình GEMINI_API_KEY trong file .env trước khi chấm thi!")
            return

        if not pdf_files:
            st.warning("Vui lòng tải lên ít nhất 1 file PDF đề thi!")
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

        # =====================================================================
        # VÒNG LẶP XỬ LÝ TỪNG ĐỀ THI TRONG ĐỢT (BATCH PROCESSING)
        # =====================================================================
        for idx, pdf_file in enumerate(pdf_files):
            try:
                # 1. Kênh văn bản số: Thử trích xuất text layer
                exam_text = extract_text_from_pdf(pdf_file)
                pdf_file.seek(0)
                # Đọc dữ liệu nhị phân sẵn sàng cho kênh AI Vision
                pdf_bytes = pdf_file.getvalue() if hasattr(pdf_file, 'getvalue') else None

                # Nhận diện Mã Đề & Năm Thi từ văn bản hoặc tên file
                current_ma_de, current_nam_thi = detect_metadata_from_file_and_text(pdf_file, exam_text)

                st.markdown(f"### :material/assignment: Đề {current_ma_de} (Năm {current_nam_thi} — `{pdf_file.name}`)")

                # Phân nhánh hiển thị: PDF văn bản số vs PDF scan/ảnh
                if exam_text:
                    # Nhánh 1: Đề có text số -> mở hộp xem trước
                    with st.expander(f":material/description: Xem văn bản trích xuất từ PDF - Đề {current_ma_de}"):
                        st.text_area("Văn bản đọc từ file:", value=exam_text, height=180, disabled=True, key=f"raw_text_{idx}")
                else:
                    # Nhánh 2: Đề scan/ảnh (exam_text rỗng) -> Bật luồng Multimodal Vision
                    st.caption(f":material/document_scanner: Tài liệu dạng scan/ảnh `{pdf_file.name}` — Đang xử lý qua kênh AI Vision trực tiếp.")

                ai_result = None
                is_from_cache = False
                t_start_exam = time.time()

                # NHÁNH 1: Chế độ Mô phỏng Dry-Run (0 Token API)
                if mock_mode:
                    status_text.info(f"[{idx+1}/{total_files}] [Mô Phỏng 0 Token] Đang sinh bài giải giả lập cho Đề {current_ma_de}...")
                    time.sleep(1.0)
                    ai_result = generate_mock_exam_solution(current_ma_de, current_nam_thi, mongo_uri)
                    is_from_cache = False
                else:
                    # NHÁNH 2: Chế độ Chấm Thật (Kiểm tra Cache MongoDB hoặc gọi Gemini API)
                    if use_cache and mongo_uri:
                        cached_ai = get_solved_exam_cache(mongo_uri, current_ma_de, current_nam_thi, model_choice)
                        if cached_ai:
                            p1_list = cached_ai.get("phan_1", [])
                            p2_list = cached_ai.get("phan_2", [])
                            is_full = (len(p1_list) == 24 and len(p2_list) == 6)
                            # Đếm số câu có lời giải thích hợp lệ ở Phần I (đủ 24/24 câu)
                            p1_exp_count = sum(_is_valid_exp(it.get("giai_thich")) for it in p1_list if isinstance(it, dict))
                            p1_has_exp = (p1_exp_count == 24)
                            # Đếm số ý có lời giải thích hợp lệ ở Phần II (đủ 24/24 ý)
                            p2_exp_count = sum(
                                _is_valid_exp(it.get("giai_thich_a")) + _is_valid_exp(it.get("giai_thich_b")) +
                                _is_valid_exp(it.get("giai_thich_c")) + _is_valid_exp(it.get("giai_thich_d"))
                                for it in p2_list if isinstance(it, dict)
                            )
                            p2_has_exp = (p2_exp_count == 24)
                            # Kiểm tra xem đáp án có bị dính ngoặc đơn chứa lý do làm hỏng định dạng không
                            has_paren_leak = any(
                                '(' in str(it.get('y_a', '')) or '(' in str(it.get('y_b', '')) or
                                '(' in str(it.get('y_c', '')) or '(' in str(it.get('y_d', ''))
                                for it in p2_list if isinstance(it, dict)
                            )
                            if is_full and p1_has_exp and p2_has_exp and not has_paren_leak:
                                ai_result = cached_ai
                                is_from_cache = True
                                st.success(
                                    f"Đã lấy bài giải ĐẦY ĐỦ ({len(p1_list)} câu P1 + {len(p2_list)} câu P2, "
                                    f"có giải thích chi tiết) từ MongoDB Cache cho Đề {current_ma_de} (Năm {current_nam_thi})!"
                                )
                            else:
                                st.info(
                                    f"Bài giải trong Cache của Đề {current_ma_de} chưa đạt chuẩn đầy đủ 24 câu P1 và 24 ý P2 có giải thích. "
                                    f"Đang kích hoạt AI ({model_choice.replace('-preview', '')}) đọc lại đề và giải toàn diện..."
                                )

                    # Nếu chưa có bài giải hoặc cache không hợp lệ, gọi Gemini API
                    if ai_result is None:
                        status_text.info(f"[{idx+1}/{total_files}] AI ({model_choice.replace('-preview', '')}) đang đọc và giải đề thi mã {current_ma_de}...")
                        ai_result = call_gemini_api(
                            gemini_api_key, exam_text, current_ma_de, current_nam_thi,
                            pdf_bytes=pdf_bytes, model_name=model_choice
                        )

                        # Cập nhật lại năm thi và mã đề nếu AI phát hiện chính xác hơn từ hình ảnh scan
                        if isinstance(ai_result, dict):
                            if ai_result.get("nam_thi"):
                                current_nam_thi = str(ai_result["nam_thi"])
                            if ai_result.get("ma_de"):
                                current_ma_de = normalize_ma_de(ai_result["ma_de"])

                        # Lưu bài giải vào Cache MongoDB để tái sử dụng
                        if mongo_uri:
                            save_solved_exam_cache(
                                mongo_uri, current_ma_de, current_nam_thi, model_choice, ai_result,
                                loai_tai_lieu="scan_image" if not exam_text else "digital_text"
                            )

                detected_batch_years.add(current_nam_thi)

                # Cảnh báo nếu sau khi tự vá vẫn còn câu/ý AI chưa giải được
                if isinstance(ai_result, dict) and ai_result.get("canh_bao"):
                    st.warning(f"Đề {current_ma_de}: " + " | ".join(ai_result["canh_bao"]) +
                               ". Bạn có thể tắt 'Sử dụng Cache bài giải' ở thanh bên trái để giải lại hoàn toàn.")

                # Chẩn đoán token: chỉ cảnh báo và hiển thị khi có sự cố cắt cụt (MAX_TOKENS)
                if isinstance(ai_result, dict) and ai_result.get("chan_doan_token"):
                    diag = ai_result["chan_doan_token"]
                    has_max_tokens = any(d.get("finish") == "MAX_TOKENS" for d in diag)
                    if has_max_tokens:
                        if ai_result.get("canh_bao"):
                            st.error("Có lượt gọi bị cắt cụt do hết token (MAX_TOKENS) → dẫn đến thiếu câu hỏi!")
                        else:
                            st.info("Lượt gọi đầu bị chạm trần token, nhưng cơ chế tự phục hồi đã nâng trần và hoàn thành trọn vẹn 100% (STOP)!")
                        with st.expander(f":material/analytics: Chi tiết sự cố token - Đề {current_ma_de}"):
                            st.dataframe(pd.DataFrame(diag), use_container_width=True)

                # =============================================================
                # TÌM ĐÁP ÁN CHUẨN ĐỐI SOÁT (CƠ CHẾ 3 TẦNG - 3-TIER KEY RESOLUTION)
                # =============================================================
                current_key_df = pd.DataFrame()

                # Tầng 1: Ưu tiên cao nhất cho đáp án đã DUYỆT THỦ CÔNG (Khóa An Toàn)
                if mongo_uri:
                    v_df = check_verified_answer_key(mongo_uri, current_ma_de, current_nam_thi)
                    if v_df is not None and not v_df.empty:
                        current_key_df = v_df

                # Tầng 2: Dự phòng dùng đáp án TỰ ĐỘNG BÓC TÁCH trong MongoDB (nếu chưa duyệt tay)
                if current_key_df.empty and mongo_uri:
                    db_key = get_answer_keys_from_db(mongo_uri, nam_thi=current_nam_thi, target_codes=[current_ma_de])
                    if not db_key.empty:
                        current_key_df = db_key

                # Tầng 3: CSDL chưa có đáp án thì mới thông báo nhắc nhở
                if current_key_df.empty:
                    st.warning(
                        f"**Chưa có đáp án chuẩn cho Mã đề {current_ma_de} (Năm {current_nam_thi}) trong Ngân Hàng!**\n\n"
                        f"Vui lòng vào **Tab 'Ngân Hàng Đáp Án Chuẩn'** để nạp file đáp án."
                    )

                # =============================================================
                # BÓC TÁCH CHI TIẾT & CHẤM ĐIỂM ĐỐI SÁNH
                # =============================================================
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
                    p1_correct = len(p1_df[p1_df['Kết Quả'].astype(str).str.contains('Đúng', na=False)])

                    p2_total = len(p2_df)
                    p2_correct = len(p2_df[p2_df['Kết Quả'].astype(str).str.contains('Đúng', na=False)])

                    correct_count = len(detail_df[detail_df['Kết Quả'].astype(str).str.contains('Đúng', na=False)])
                    score = (correct_count / total_count) * 10 if total_count > 0 else 0
                    score_khmt, score_thud, _, _ = calculate_moet_scores(detail_df)

                    st.success(
                        f":material/award_star: **Kết quả Đề {current_ma_de} (Năm {current_nam_thi}):** "
                        f"Điểm Toàn Đề (48 đơn vị): **{score:.2f} / 10** (Đúng {correct_count}/{total_count} câu/ý) | "
                        f"🎯 **Bộ GD (KHMT): {score_khmt:.2f} / 10** | "
                        f"💼 **Bộ GD (THUD): {score_thud:.2f} / 10**"
                    )
                else:
                    score_khmt, score_thud = None, None
                    st.success(f"Đã giải xong toàn bộ câu hỏi Đề {current_ma_de} (Chưa đối sánh đáp án)")

                # Tính toán thời gian thực thi (latency), thống kê Token & Chi phí dự toán
                latency_sec = round(time.time() - t_start_exam, 2)
                diag = ai_result.get("chan_doan_token", []) if isinstance(ai_result, dict) else []
                token_in = sum(int(d.get("token_vao", 0) or 0) for d in diag)
                token_out = sum(int(d.get("token_ra", 0) or 0) for d in diag)
                token_thought = sum(int(d.get("token_nghi", 0) or 0) for d in diag)

                if is_from_cache:
                    cost_vnd = 0.0
                    source_type = "Cache"
                else:
                    source_type = "API"
                    # Gemini API Pricing (Tỷ giá 1 USD = 25.000 VNĐ)
                    # Flash: Input $0.10/1M (~0.0025 đ/tok), Output/Thinking $0.40/1M (~0.010 đ/tok)
                    # Pro:   Input $1.25/1M (~0.03125 đ/tok), Output/Thinking $5.00/1M (~0.125 đ/tok)
                    if "pro" in str(model_choice).lower():
                        cost_vnd = round((token_in * 0.03125) + ((token_out + token_thought) * 0.125), 2)
                    else:
                        cost_vnd = round((token_in * 0.0025) + ((token_out + token_thought) * 0.010), 2)

                # Ghi nhận kết quả vào bảng tổng kết
                all_results_summary.append({
                    "Mã Đề": current_ma_de,
                    "Năm Thi": current_nam_thi,
                    "Tên File": pdf_file.name,
                    "Điểm Toàn Đề (48 đơn vị)": round(score, 2) if score is not None else "Chưa đối sánh",
                    "Điểm Bộ GD (KHMT)": round(score_khmt, 2) if score_khmt is not None else "-",
                    "Điểm Bộ GD (THUD)": round(score_thud, 2) if score_thud is not None else "-",
                    "Số câu đúng": correct_count if score is not None else "-",
                    "Tổng số câu": total_count,
                    "Tỷ lệ đúng (%)": round((correct_count / total_count * 100), 2) if score is not None else "-",
                    "P1 Trắc nghiệm": f"{p1_correct}/{p1_total}" if score is not None else f"{p1_total} câu đã giải",
                    "P2 Đúng/Sai": f"{p2_correct}/{p2_total}" if score is not None else f"{p2_total} ý đã giải",
                    "Model AI": model_choice.replace("-preview", "") if model_choice else "",
                    "Thời gian (s)": latency_sec,
                    "Token Vào": token_in,
                    "Token Ra": token_out,
                    "Token Nghĩ": token_thought,
                    "Chi Phí (VNĐ)": cost_vnd,
                    "Thời Gian Chấm": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                all_details_records.append(detail_df)

                # Hiển thị thẻ tóm tắt hiệu năng của riêng đề thi này
                m_g1, m_g2, m_g3, m_g4, m_g5 = st.columns(5)
                m_g1.metric("Thời Gian Xử Lý", f"{latency_sec} s")
                m_g2.metric("Chi Phí API", f"{cost_vnd} VNĐ")
                m_g3.metric("Token Vào (Prompt)", f"{token_in:,}")
                m_g4.metric("Token Ra (Candidate)", f"{token_out:,}")
                m_g5.metric("Token Nghĩ (Thinking)", f"{token_thought:,}")

                # Hiển thị bảng chi tiết trên UI
                with st.expander(f":material/table_chart: Chi tiết kết quả giải đề - Đề {current_ma_de}", expanded=True):
                    render_comparison_detail_table(detail_df, key_suffix=f"tab1_{current_ma_de}_{idx}")

                    # Nút tải Excel riêng cho đề thi này (Sử dụng Cache RAM tức thì)
                    st.download_button(
                        label=f"Tải Chi Tiết Đề {current_ma_de} (Excel .xlsx)",
                        icon=":material/download:",
                        data=df_to_excel_bytes(detail_df, sheet_name=f'Chi Tiết Đề {current_ma_de}', index=True, index_label='STT'),
                        file_name=f"chi_tiet_de_{current_ma_de}_{current_nam_thi}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_excel_single_{current_ma_de}_{idx}",
                        use_container_width=True
                    )

                # =============================================================
                # LƯU KẾT QUẢ VÀO COLLECTION 'exam_results'
                # =============================================================
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
                        model_name=model_choice,
                        latency_sec=latency_sec,
                        token_in=token_in,
                        token_out=token_out,
                        token_thought=token_thought,
                        cost_vnd=cost_vnd,
                        source=source_type
                    )
                    if saved:
                        st.caption(f":material/database: Đã lưu Đề {current_ma_de} (Năm {current_nam_thi}) vào MongoDB (ID: `{msg}`)")
                    else:
                        st.warning(f"MongoDB: {msg}")

                # Nghỉ giữa các đề nếu xử lý nhiều đề để tránh nghẽn Rate Limit
                if idx < total_files - 1:
                    time.sleep(5)

                progress_bar.progress((idx + 1) / total_files)

            except Exception as e:
                st.error(f"Lỗi khi xử lý đề {pdf_file.name}: {str(e)}")

        status_text.empty()

        # =====================================================================
        # LƯU ĐỢT THI VÀ XUẤT BÁO CÁO TỔNG HỢP
        # =====================================================================
        batch_year_label = ", ".join(sorted(list(detected_batch_years))) if detected_batch_years else "2025"
        if mongo_uri and all_results_summary:
            save_grading_batch(
                mongo_uri,
                batch_id=batch_id,
                ten_dot_thi=f"Đợt Chấm Năm {batch_year_label} ({now_dt.strftime('%d/%m/%Y %H:%M')})",
                nam_thi=batch_year_label,
                model_name=model_choice,
                summary_list=all_results_summary
            )

        if all_results_summary:
            st.markdown("---")
            st.header(f":material/analytics: KẾT QUẢ ĐỢT CHẤM: {ten_dot_thi}")
            st.caption(f"Mã đợt thi (Batch ID): `{batch_id}`")
            summary_df = pd.DataFrame(all_results_summary)
            st.dataframe(summary_df, use_container_width=True)

            # Xuất file Excel đa Sheet với Sheet 1 'Chi Tiết Từng Câu Hỏi' đặt lên đầu
            output_excel = io.BytesIO()
            with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
                if all_details_records:
                    full_details_df = pd.concat(all_details_records, ignore_index=True)
                    full_details_df.index = range(1, len(full_details_df) + 1)
                    full_details_df.to_excel(writer, sheet_name='Chi Tiết Từng Câu Hỏi', index=True, index_label='STT')
                summary_df.to_excel(writer, sheet_name='Tổng Hợp Điểm Số', index=False)

            excel_bytes = output_excel.getvalue()

            st.download_button(
                label="Tải Toàn Bộ Báo Cáo Đợt Chấm (Excel .xlsx)",
                icon=":material/download:",
                data=excel_bytes,
                file_name=f'bao_cao_cham_thi_{batch_id}.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                use_container_width=True,
                type="primary"
            )

        st.success(f":material/check_circle: Hoàn tất quy trình chấm {total_files} đề thi thành công!")
