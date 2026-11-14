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
# TỰ ĐỘNG NẠP LẠI MÃ NGUỒN MỚI NHẤT KHI CHẠY TRONG TIẾN TRÌNH STREAMLIT
# =============================================================================
import sys
import importlib

for _mod_name in [
    'core.excel_utils',
    'core.pdf_utils',
    'core.ai_grader',
    'core.database',
    'core.grading_logic',
    'core.mock_data',
    'views.tab_grading',
    'views.tab_history',
    'views.tab_keys'
]:
    if _mod_name in sys.modules:
        try:
            importlib.reload(sys.modules[_mod_name])
        except Exception:
            pass

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
    page_title="AI Chấm Thi Tin Học THPT",
    page_icon=":material/smart_toy:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# ẨN CÁC THÀNH PHẦN MẶC ĐỊNH (NÚT DEPLOY, MENU 3 CHẤM, STATUS WIDGET / LOADER)
# =============================================================================
st.markdown("""
<style>
    /* 1. Ẩn nút Deploy góc trên bên phải */
    .stDeployButton, [data-testid="stDeployButton"] {
        display: none !important;
    }
    /* 2. Ẩn menu 3 chấm (MainMenu) góc trên bên phải */
    #MainMenu {
        visibility: hidden !important;
        display: none !important;
    }
    /* 3. Ẩn widget trạng thái running / loader / stop button */
    [data-testid="stStatusWidget"], [data-testid="stRunningMan"] {
        visibility: hidden !important;
        display: none !important;
    }
    /* 4. Ẩn thanh trang trí trên đỉnh trang */
    [data-testid="stDecoration"] {
        display: none !important;
    }
    /* 5. Ẩn footer Streamlit */
    footer {
        visibility: hidden !important;
        display: none !important;
    }

    /* 6. ĐẢM BẢO NÚT MỞ LẠI SIDEBAR (CHEVRON >) LUÔN HIỂN THỊ RÕ RÀNG KHI ĐÓNG */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"],
    section[data-testid="stSidebar"] + div button,
    header button[data-testid="stSidebarCollapseButton"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        z-index: 1000000 !important;
    }

    /* 7. MỞ RỘNG TỐI ĐA KHUNG NỘI DUNG CHÍNH ĐỂ BẢNG HIỂN THỊ TRỌN VẸN KHÔNG CẦN KÉO NGANG */
    .block-container,
    [data-testid="stMainBlockContainer"],
    .main .block-container {
        max-width: 100% !important;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        padding-top: 1.5rem !important;
    }
    section[data-testid="stSidebar"] {
        width: 245px !important;
        min-width: 245px !important;
    }
    [data-testid="stExpanderDetails"] {
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Hàm khởi chạy và điều phối toàn bộ ứng dụng."""
    st.title(":material/smart_toy: Trợ Lý AI Chấm Thi Tin Học THPT")
    st.caption("Hệ thống Generative AI tự động đọc đề thi scan/ảnh, giải đề độc lập, đối sánh đáp án và quản lý dữ liệu MongoDB Atlas.")
    st.markdown("---")

    # Đọc cấu hình bảo mật từ biến môi trường (.env)
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    mongo_uri = os.getenv("MONGODB_URI", "").strip()

    # =========================================================================
    # SIDEBAR: CẤU HÌNH HỆ THỐNG & MODEL AI
    # =========================================================================
    with st.sidebar:
        st.header(":material/tune: Cấu Hình Hệ Thống")

        if not gemini_api_key:
            st.error("Chưa cấu hình GEMINI_API_KEY trong file .env!")

        st.markdown("---")
        st.subheader(":material/psychology: Mô Hình AI")
        model_choice = st.selectbox(
            "Chọn Model Gemini",
            options=["gemini-3.8-flash", "gemini-3.1-pro-preview"],
            format_func=lambda x: "gemini-3.1-pro" if "pro" in x else "gemini-3.8-flash",
            index=0,
            help="Cả hai mô hình (Flash và Pro) đều chạy qua Kiến trúc 2 Pha tối ưu: Pha 1 đọc 24 câu P1, Pha 2 dồn 100% suy luận giải 6 câu P2 Đúng/Sai, Pha 3 điền giải thích lý thuyết súc tích."
        )

        st.markdown("---")
        st.subheader(":material/speed: Bộ Nhớ Đệm & Tối Ưu")
        use_cache = st.checkbox(
            "Sử dụng Cache bài giải (Tiết kiệm Token)",
            value=True,
            help="Nếu bật: Lấy bài giải cũ từ MongoDB để tiết kiệm chi phí và tăng tốc độ. Nếu tắt: Ép AI đọc lại PDF và giải mới 100%."
        )
        if st.button("Làm Mới Cache Bài Giải", icon=":material/refresh:", help="Xóa sạch cache bài giải cũ trong MongoDB để ép AI giải lại", use_container_width=True):
            if mongo_uri:
                ok_del, msg_del = delete_solved_exam_cache(mongo_uri)
                if ok_del:
                    st.success(msg_del)
                else:
                    st.error(msg_del)

        st.markdown("---")
        st.subheader(":material/science: Chế Độ Kiểm Thử")
        mock_mode = st.checkbox(
            "Chế độ Mô Phỏng (0 Token API)",
            value=False,
            help="Chạy thử nghiệm toàn bộ giao diện chấm thi và lịch sử mà KHÔNG gọi Gemini API và KHÔNG tốn token."
        )
        if mock_mode:
            st.warning("Chế độ Mô phỏng đang BẬT (0 token).")

        st.markdown("---")
       

    # =========================================================================
    # CÁC TAB ĐIỀU HƯỚNG GIAO DIỆN
    # =========================================================================
    tab_grad, tab_history, tab_keys = st.tabs([
        ":material/fact_check: Chấm Thi Tự Động",
        ":material/history: Lịch Sử Đợt Chấm",
        ":material/database: Ngân Hàng Đáp Án Chuẩn"
    ])

    with tab_grad:
        render_tab_grading(
            gemini_api_key=gemini_api_key,
            mongo_uri=mongo_uri,
            model_choice=model_choice,
            use_cache=use_cache,
            mock_mode=mock_mode
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
