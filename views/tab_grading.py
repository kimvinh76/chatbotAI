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
from core.ai_grader import call_gemini_api, enrich_p2_explanations
from core.database import (
    get_solved_exam_cache,
    save_solved_exam_cache,
    check_verified_answer_key,
    get_answer_keys_from_db,
    save_to_mongodb,
    save_grading_batch,
)
from core.grading_logic import build_comparison_and_detail_df
from core.excel_utils import df_to_excel_bytes


def render_tab_grading(gemini_api_key: str, mongo_uri: str, model_choice: str, use_cache: bool):
    """
    Render giao diện và điều phối luồng xử lý của Tab 1: Chấm Thi Tự Động.
    
    Tham số:
    - gemini_api_key: Khóa bí mật gọi Google Gemini API
    - mongo_uri: Chuỗi kết nối MongoDB Atlas
    - model_choice: Model AI đang chọn (Flash 3.8 hoặc Pro 3.1)
    - use_cache: Bật/Tắt tính năng dùng lại bài giải đã lưu
    """
    st.subheader("📄 Tải Lên Đề Thi (PDF)")
    st.caption(
        "💡 Hệ thống tự động nhận diện Mã Đề & Năm Thi từ đề thi, sau đó đối soát trực tiếp "
        "với **Ngân Hàng Đáp Án Chuẩn** trong MongoDB (quản lý tại Tab 3) mà không cần tải kèm file đáp án."
    )

    c_up1, c_up2 = st.columns([3, 2])
    with c_up1:
        pdf_files = st.file_uploader(
            "Kéo thả 1 hoặc nhiều file PDF đề thi để bắt đầu chấm:",
            type=['pdf'],
            accept_multiple_files=True
        )
    with c_up2:
        # [QUAN TRỌNG] Cho phép người dùng chủ động bỏ qua Cache khi cần giải lại bài thi
        force_regrade = st.checkbox(
            "🔄 Bắt buộc giải lại đề (Bỏ qua Cache)",
            value=False,
            help="Tích vào ô này nếu lần trước AI giải sai hoặc thiếu lời giải thích, để ép AI đọc lại PDF và giải mới 100%!"
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

        # =====================================================================
        # VÒNG LẶP XỬ LÝ TỪNG ĐỀ THI TRONG ĐỢT (BATCH PROCESSING)
        # =====================================================================
        for idx, pdf_file in enumerate(pdf_files):
            try:
                status_text.info(f"[{idx+1}/{total_files}] Đang chuẩn bị dữ liệu đề thi `{pdf_file.name}`...")
                exam_text = extract_text_from_pdf(pdf_file)
                pdf_file.seek(0)
                pdf_bytes = pdf_file.getvalue() if hasattr(pdf_file, 'getvalue') else None

                # [QUAN TRỌNG] Nhận diện Mã Đề & Năm Thi từ văn bản hoặc tên file
                current_ma_de, current_nam_thi = detect_metadata_from_file_and_text(pdf_file, exam_text)

                st.markdown(f"### 📝 Đang xử lý: Mã đề **{current_ma_de}** | Năm thi: **{current_nam_thi}** (`{pdf_file.name}`)")

                if exam_text:
                    with st.expander(f"📄 Xem văn bản trích xuất từ PDF - Đề {current_ma_de}"):
                        st.text_area("Văn bản đọc từ file:", value=exam_text, height=180, disabled=True, key=f"raw_text_{idx}")
                else:
                    st.info(f"📸 Đề thi `{pdf_file.name}` là tài liệu scan/ảnh. Đang dùng **AI Vision** đọc trực tiếp trang ảnh!")

                ai_result = None

                # [QUAN TRỌNG] Kiểm tra Cache trong MongoDB & Đánh giá chất lượng bài giải cũ
                if use_cache and not force_regrade and mongo_uri:
                    cached_ai = get_solved_exam_cache(mongo_uri, current_ma_de, current_nam_thi, model_choice)
                    if cached_ai:
                        p1_list = cached_ai.get("phan_1", [])
                        p2_list = cached_ai.get("phan_2", [])
                        is_full = len(p1_list) >= 24 and len(p2_list) >= 6
                        p1_has_exp = any(bool(it.get("giai_thich")) for it in p1_list)

                        # Đếm số ý có lời giải thích ở Phần II (chuẩn phải có ít nhất 18/24 ý)
                        p2_exp_count = sum(
                            bool(it.get("giai_thich_a")) + bool(it.get("giai_thich_b")) +
                            bool(it.get("giai_thich_c")) + bool(it.get("giai_thich_d"))
                            for it in p2_list if isinstance(it, dict)
                        )
                        p2_has_exp = (p2_exp_count >= 18)

                        # Kiểm tra xem đáp án có bị dính ngoặc đơn chứa lý do làm hỏng định dạng không
                        has_paren_leak = any(
                            '(' in str(it.get('y_a', '')) or '(' in str(it.get('y_b', '')) or
                            '(' in str(it.get('y_c', '')) or '(' in str(it.get('y_d', ''))
                            for it in p2_list if isinstance(it, dict)
                        )

                        if is_full and p1_has_exp and p2_has_exp and not has_paren_leak:
                            ai_result = cached_ai
                            st.success(
                                f"⚡ Đã lấy bài giải ĐẦY ĐỦ ({len(p1_list)} câu P1 + {len(p2_list)} câu P2, "
                                f"có giải thích chi tiết) từ MongoDB Cache cho Đề {current_ma_de} (Năm {current_nam_thi})!"
                            )
                        elif is_full and not has_paren_leak:
                            # Đã có đủ đáp án 24 câu P1 và 6 câu P2 Đúng/Sai, chỉ thiếu giải thích
                            # Bổ sung giải thích bằng Text thuần (siêu nhẹ, không tốn token đọc lại PDF scan)
                            st.info(
                                f"💡 Đề {current_ma_de} đã có đủ đáp án trong Cache nhưng thiếu giải thích. "
                                f"Đang tự động bổ sung lời giải thích siêu tốc bằng Text thuần (không tốn token đọc lại PDF)..."
                            )
                            try:
                                p2_list_enriched = enrich_p2_explanations(
                                    gemini_api_key, p2_list, model_name="gemini-3.8-flash"
                                )
                                cached_ai["phan_2"] = p2_list_enriched
                                ai_result = cached_ai
                                if mongo_uri:
                                    save_solved_exam_cache(
                                        mongo_uri, current_ma_de, current_nam_thi, model_choice, ai_result,
                                        loai_tai_lieu="scan_image" if not exam_text else "digital_text"
                                    )
                                st.success(f"⚡ Đã bổ sung giải thích thành công cho Đề {current_ma_de} và cập nhật vào Cache!")
                            except Exception:
                                # Nếu gặp lỗi mạng / quota, vẫn dùng bản cache cũ để chấm điểm bình thường thay vì bị chặn
                                ai_result = cached_ai
                                st.warning(f"⚠️ Chưa thể bổ sung giải thích do hạn mức API. Đang dùng đáp án sẵn có trong Cache để chấm điểm.")
                        else:
                            # Nếu cache cũ bị thiếu câu thật sự
                            reason_invalid = []
                            if not is_full:
                                reason_invalid.append(f"thiếu câu ({len(p1_list)}/24 P1, {len(p2_list)}/6 P2)")
                            if has_paren_leak:
                                reason_invalid.append("dính ngoặc đơn ở đáp án")
                            st.info(
                                f"🔄 Bài giải trong Cache của Đề {current_ma_de} chưa đạt chuẩn ({', '.join(reason_invalid)}). "
                                f"Đang kích hoạt AI ({model_choice}) giải lại toàn diện và cập nhật Cache mới..."
                            )

                # [QUAN TRỌNG] Nếu chưa có bài giải hoặc cache không hợp lệ, gọi Gemini API
                if ai_result is None:
                    status_text.info(f"[{idx+1}/{total_files}] AI ({model_choice}) đang đọc và giải đề thi mã {current_ma_de}...")
                    ai_result = call_gemini_api(
                        gemini_api_key, exam_text, current_ma_de, current_nam_thi,
                        pdf_bytes=pdf_bytes, model_name=model_choice
                    )

                    # Cập nhật lại năm thi và mã đề nếu AI phát hiện chính xác hơn từ hình ảnh scan
                    if isinstance(ai_result, dict):
                        if ai_result.get("nam_thi"):
                            current_nam_thi = str(ai_result["nam_thi"])
                        if ai_result.get("ma_de"):
                            current_ma_de = str(ai_result["ma_de"])

                    # Lưu bài giải vào Cache MongoDB để tái sử dụng
                    if mongo_uri:
                        save_solved_exam_cache(
                            mongo_uri, current_ma_de, current_nam_thi, model_choice, ai_result,
                            loai_tai_lieu="scan_image" if not exam_text else "digital_text"
                        )

                detected_batch_years.add(current_nam_thi)

                # Cảnh báo nếu sau khi tự vá vẫn còn câu/ý AI chưa giải được
                if isinstance(ai_result, dict) and ai_result.get("canh_bao"):
                    st.warning(f"⚠️ Đề {current_ma_de}: " + " | ".join(ai_result["canh_bao"]) +
                               ". Hãy tích 'Bắt buộc giải lại đề' hoặc dùng model Pro cho đề này.")

                # Chẩn đoán token: kiểm tra có lượt nào bị cắt cụt (MAX_TOKENS) và chi phí thực tế
                if isinstance(ai_result, dict) and ai_result.get("chan_doan_token"):
                    diag = ai_result["chan_doan_token"]
                    has_max_tokens = any(d.get("finish") == "MAX_TOKENS" for d in diag)
                    if has_max_tokens:
                        if ai_result.get("canh_bao"):
                            st.error("🔴 Có lượt gọi bị cắt cụt do hết token (MAX_TOKENS) → dẫn đến thiếu câu hỏi!")
                        else:
                            st.info("💡 Lượt gọi đầu bị chạm trần token, nhưng cơ chế tự phục hồi đã nâng trần và hoàn thành trọn vẹn 100% (STOP)!")
                    with st.expander(f"📊 Chẩn đoán token - Đề {current_ma_de}"):
                        st.dataframe(pd.DataFrame(diag), use_container_width=True)

                # Hiển thị kết quả JSON thô của AI
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

                # =============================================================
                # TÌM ĐÁP ÁN CHUẨN TỪ MONGODB ĐỂ ĐỐI SÁNH
                # =============================================================
                current_key_df = pd.DataFrame()
                key_source_note = ""

                # Ưu tiên 1: Bản đã xác thực thủ công (Khóa An Toàn)
                if mongo_uri:
                    v_df = check_verified_answer_key(mongo_uri, current_ma_de, current_nam_thi)
                    if v_df is not None and not v_df.empty:
                        current_key_df = v_df
                        key_source_note = "🛡️ **Khóa An Toàn:** Đã ưu tiên đáp án chuẩn **ĐÃ DUYỆT** từ Ngân Hàng MongoDB"

                # Ưu tiên 2: Bản đáp án tự động trong Ngân Hàng Đáp Án
                if current_key_df.empty and mongo_uri:
                    db_key = get_answer_keys_from_db(mongo_uri, nam_thi=current_nam_thi, target_codes=[current_ma_de])
                    if not db_key.empty:
                        current_key_df = db_key
                        key_source_note = "💡 Đã tự động lấy đáp án chuẩn từ Ngân Hàng MongoDB"

                if not current_key_df.empty:
                    st.success(f"{key_source_note} cho Đề {current_ma_de} (Năm {current_nam_thi})!")
                else:
                    st.warning(
                        f"⚠️ **Chưa có đáp án chuẩn cho Mã đề {current_ma_de} (Năm {current_nam_thi}) trong Ngân Hàng!**\n\n"
                        f"👉 Vui lòng vào **Tab 3 ('Ngân Hàng Đáp Án Chuẩn')** để nạp file đáp án."
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
                    p1_correct = len(p1_df[p1_df['Kết Quả'] == '✅ Đúng'])

                    p2_total = len(p2_df)
                    p2_correct = len(p2_df[p2_df['Kết Quả'] == '✅ Đúng'])

                    correct_count = len(detail_df[detail_df['Kết Quả'] == '✅ Đúng'])
                    score = (correct_count / total_count) * 10 if total_count > 0 else 0

                    st.success(
                        f"🎯 Điểm số Đề {current_ma_de} (Năm {current_nam_thi}): "
                        f"**{score:.2f} / 10** (Đúng {correct_count}/{total_count} câu/ý)"
                    )
                else:
                    st.success(f"✅ Đã giải xong toàn bộ câu hỏi Đề {current_ma_de} (Chưa đối sánh đáp án)")

                # Ghi nhận kết quả vào bảng tổng kết
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
                        style_func = lambda val: 'color: green; font-weight: bold' if val == '✅ Đúng' else (
                            'color: red; font-weight: bold' if val == '❌ Sai' else ''
                        )
                        if hasattr(detail_df.style, 'map'):
                            styled_df = detail_df.style.map(style_func, subset=['Kết Quả'])
                        else:
                            styled_df = detail_df.style.applymap(style_func, subset=['Kết Quả'])
                        st.dataframe(styled_df, use_container_width=True)
                    else:
                        st.dataframe(detail_df, use_container_width=True)

                    # Nút tải Excel riêng cho đề thi này (Sử dụng Cache RAM tức thì)
                    st.download_button(
                        label=f"📊 Tải Chi Tiết Đề {current_ma_de} (Excel .xlsx)",
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
                        model_name=model_choice
                    )
                    if saved:
                        st.caption(f"🍃 Đã lưu Đề {current_ma_de} (Năm {current_nam_thi}) vào MongoDB (ID: `{msg}`)!")
                    else:
                        st.warning(f"ℹ️ MongoDB: {msg}")

                # Nghỉ giữa các đề nếu xử lý nhiều đề để tránh nghẽn Rate Limit
                if idx < total_files - 1:
                    time.sleep(5)

                progress_bar.progress((idx + 1) / total_files)

            except Exception as e:
                st.error(f"❌ Lỗi khi xử lý đề {pdf_file.name}: {str(e)}")

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
            st.header(f"🏆 KẾT QUẢ ĐỢT CHẤM: {ten_dot_thi}")
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
                label="📥 Tải Toàn Bộ Báo Cáo Đợt Chấm (Excel .xlsx)",
                data=excel_bytes,
                file_name=f'bao_cao_cham_thi_{batch_id}.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                use_container_width=True,
                type="primary"
            )

        st.balloons()
        st.success(f"🎉 Hoàn tất quy trình chấm {total_files} đề thi thành công!")
