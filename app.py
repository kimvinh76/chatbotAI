"""
=============================================================================
ĐỒ ÁN CHUYÊN NGÀNH: HỆ THỐNG TRỢ LÝ AI CHẤM THI TIN HỌC THPT QUỐC GIA
=============================================================================
Kiến trúc: Modular Monolith (Cấu trúc phân tầng mô-đun hóa)
- core/:
  + pdf_utils.py: Đọc văn bản, bóc tách trang và tự động nhận diện mã đề & năm thi.
  + ai_grader.py: Prompt chuyên gia, Schemas, xử lý 2 pha cho Flash và Single-shot cho Pro.
  + excel_utils.py: Phân tích file Excel/CSV đáp án, chuyển đổi Ma trận Bộ GD&ĐT, xuất bytes.
  + grading_logic.py: Bóc tách bài giải, trích xuất lý do, đối sánh đáp án và tính điểm.
  + database.py: Quản lý Connection Pool MongoDB và 4 Collections nghiệp vụ.
- views/:
  + tab_grading.py: Tab 1 - Chấm thi tự động hàng loạt (Batch Grader).
  + tab_history.py: Tab 2 - Lịch sử đợt chấm thi & xuất báo cáo đa sheet.
  + tab_keys.py: Tab 3 - Ngân hàng đáp án chuẩn & Ma trận chỉnh sửa trực tiếp.
=============================================================================
"""

import os
import streamlit as st
from dotenv import load_dotenv

# Tải biến môi trường cấu hình bí mật (.env)
load_dotenv()

# =============================================================================
# RE-EXPORT CÁC MODULE LÕI (ĐẢM BẢO TƯƠNG THÍCH NGƯỢC 100% VỚI CÁC SCRIPT TEST)
# =============================================================================
from core.pdf_utils import extract_text_from_pdf, detect_metadata_from_file_and_text
from core.ai_grader import (
    SYSTEM_PROMPT,
    CauHoiPhan1,
    CauHoiPhan2,
    BaiGiaiDeThi,
    BaiGiaiPhan1,
    BaiGiaiPhan2,
    Phan1,
    Phan2CauHoi,
    DeThiResponse,
    Phan1OnlyResponse,
    Phan2OnlyResponse,
    robust_exam_json_parser,
    call_gemini_api,
    parse_answer_key_pdf,
    detect_answer_key_codes,
    parse_full_answer_key_pdf,
)
from core.excel_utils import (
    normalize_ma_de,
    parse_p2_val,
    parse_answer_excel_or_csv,
    answer_df_to_matrix,
    matrix_column_to_items,
    df_to_excel_bytes,
    dict_to_multisheet_excel_bytes,
)
from core.database import (
    get_mongo_client,
    get_mongo_db,
    save_answer_keys_to_db,
    get_answer_keys_from_db,
    check_verified_answer_key,
    get_all_answer_keys_summary,
    get_single_answer_key_detail,
    update_single_answer_key,
    delete_answer_key_from_db,
    cleanup_duplicate_answer_keys,
    verify_all_answer_keys_in_year,
    delete_all_answer_keys_in_year,
    get_all_answer_keys_dataframe,
    get_solved_exam_cache,
    save_solved_exam_cache,
    delete_solved_exam_cache,
    save_grading_batch,
    get_all_batches_from_db,
    delete_batch_from_db,
    save_to_mongodb,
    get_batch_exam_results,
)
from core.grading_logic import build_comparison_and_detail_df

# Import các View Components
from views.tab_grading import render_tab_grading
from views.tab_history import render_tab_history
from views.tab_keys import render_tab_keys


# =============================================================================
# CẤU HÌNH TRANG STREAMLIT
# =============================================================================
st.set_page_config(
    page_title="AI Chấm Thi Tin Học 2025",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)


def main():
    """Hàm khởi chạy và điều phối toàn bộ ứng dụng."""
    st.title("🤖 Trợ Lý AI Chấm Thi Tin Học THPT 2025")
    st.caption("Hệ thống Generative AI tự động đọc đề thi scan/ảnh, giải đề độc lập, đối sánh đáp án và quản lý dữ liệu MongoDB.")
    st.markdown("---")

    # Đọc cấu hình bảo mật từ biến môi trường (.env)
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    mongo_uri = os.getenv("MONGODB_URI", "").strip()

    # =========================================================================
    # SIDEBAR: CẤU HÌNH HỆ THỐNG & MODEL AI
    # =========================================================================
    with st.sidebar:
        st.header("⚙️ Cấu Hình Hệ Thống")

        if not gemini_api_key:
            st.error("⚠️ Chưa cấu hình GEMINI_API_KEY trong file .env!")

        st.markdown("---")
        st.subheader("🧠 Model AI")
        model_choice = st.selectbox(
            "Chọn Model Gemini",
            options=["gemini-3.8-flash", "gemini-3.1-pro-preview"],
            index=0,
            help="Cả hai mô hình (Flash và Pro) đều chạy qua Kiến trúc 2 Pha tối ưu: Pha 1 đọc 24 câu P1, Pha 2 dồn 100% suy luận giải 6 câu P2 Đúng/Sai, Pha 3 điền giải thích lý thuyết súc tích."
        )

        st.markdown("---")
        st.subheader("⚡ Tối Ưu Hệ Thống")
        use_cache = st.checkbox(
            "Sử dụng Cache bài giải (Tiết kiệm Token)",
            value=True,
            help="Nếu đề thi đã được AI giải trước đó, hệ thống sẽ lấy ngay từ MongoDB để không tốn chi phí gọi lại API."
        )
        if st.button("🧹 Làm Mới Cache Bài Giải", help="Xóa cache bài giải cũ trong MongoDB để ép AI giải lại và cập nhật đầy đủ lời giải thích mới nhất", use_container_width=True):
            if mongo_uri:
                ok_del, msg_del = delete_solved_exam_cache(mongo_uri)
                if ok_del:
                    st.success(msg_del)
                else:
                    st.error(msg_del)

        st.info("🤖 **100% Tự Động Hóa**:\nAI tự động đọc **Năm Thi** (2025, 2026...) & **Mã Đề** trực tiếp từ trang tiêu đề PDF đề thi và đáp án.")

    # =========================================================================
    # CÁC TAB ĐIỀU HƯỚNG GIAO DIỆN
    # =========================================================================
    tab_grad, tab_history, tab_keys = st.tabs([
        "🚀 Chấm Thi Tự Động (Batch Grader)",
        "📜 Lịch Sử Đợt Chấm Thi (MongoDB)",
        "🗄️ Ngân Hàng Đáp Án Chuẩn (Answer Keys)"
    ])

    with tab_grad:
        render_tab_grading(
            gemini_api_key=gemini_api_key,
            mongo_uri=mongo_uri,
            model_choice=model_choice,
            use_cache=use_cache
        )

    with tab_history:
        render_tab_history(
            mongo_uri=mongo_uri
        )

    with tab_keys:
        render_tab_keys(
            gemini_api_key=gemini_api_key,
            mongo_uri=mongo_uri,
            model_choice=model_choice
        )


if __name__ == "__main__":
    main()
