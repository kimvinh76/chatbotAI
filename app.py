import streamlit as st
import pandas as pd
import pdfplumber
import google.generativeai as genai
from pymongo import MongoClient
import os
import json
import time
from dotenv import load_dotenv
import typing_extensions as typing

# Tải biến môi trường
load_dotenv()

# --- CẤU HÌNH TRANG ---
st.set_page_config(
    page_title="AI Chấm Thi Tin Học",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- SYSTEM PROMPT ---
SYSTEM_PROMPT = """Bạn là một chuyên gia giáo dục môn Tin học và kỹ sư phần mềm. Nhiệm vụ của bạn là giải các câu hỏi trong đề thi Tốt nghiệp THPT môn Tin học một cách chính xác tuyệt đối.

QUY TẮC PHÂN TÍCH (HIDDEN CHAIN-OF-THOUGHT):
- Trước khi chốt đáp án, hãy phân tích logic thuật toán, chạy thử (dry-run) các biến trong mã nguồn, hoặc đánh giá cú pháp SQL.
- Đối chiếu nghiêm ngặt với chuẩn kiến thức sách giáo khoa Tin học định hướng Khoa học máy tính hoặc Tin học ứng dụng.

QUY TẮC ĐẦU RA (JSON SCHEMA):
Bạn chỉ được phép trả về kết quả dưới dạng một đối tượng JSON hợp lệ, tuyệt đối không bao gồm markdown (như ```json) hay văn bản giải thích nằm ngoài JSON. Định dạng bắt buộc:

{
  "phan_1": [
    { "cau_hoi": 1, "dap_an": "A", "giai_thich_ngam": "Khái niệm RAM là bộ nhớ truy cập ngẫu nhiên..." },
    { "cau_hoi": 2, "dap_an": "C", "giai_thich_ngam": "..." }
  ],
  "phan_2": [
    {
      "cau_hoi": 1,
      "y_a": "Đúng", "y_b": "Sai", "y_c": "Đúng", "y_d": "Sai",
      "giai_thich_ngam": "Vòng lặp while điều kiện dừng sai ở ý b..."
    }
  ],
  "phan_3": [
    { "cau_hoi": 1, "dap_an": "15", "giai_thich_ngam": "Vòng lặp chạy 3 lần, biến s tăng 5..." }
  ]
}"""

# --- ĐỊNH NGHĨA CẤU TRÚC JSON (SCHEMA) ---
class Phan1(typing.TypedDict):
    cau_hoi: int
    dap_an: str
    giai_thich_ngam: str

class Phan2(typing.TypedDict):
    cau_hoi: int
    y_a: str
    y_b: str
    y_c: str
    y_d: str
    giai_thich_ngam: str

class Phan3(typing.TypedDict):
    cau_hoi: int
    dap_an: str
    giai_thich_ngam: str

class DeThiResponse(typing.TypedDict):
    phan_1: list[Phan1]
    phan_2: list[Phan2]
    phan_3: list[Phan3]

# --- CÁC HÀM HỖ TRỢ ---
def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # pdfplumber giữ không gian tốt hơn PyPDF2
            page_text = page.extract_text(x_tolerance=1, y_tolerance=1)
            if page_text:
                text += page_text + "\n"
    return text

def call_gemini_api(api_key, text, ma_de, nam_thi):
    genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel(
        model_name="gemini-flash-latest",
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=DeThiResponse,
            temperature=0.1
        )
    )
    
    user_prompt = f"""Dưới đây là nội dung văn bản được bóc tách từ mã đề {ma_de} năm {nam_thi}. Hãy giải quyết toàn bộ đề thi này và trả về JSON theo đúng định dạng.

--- NỘI DUNG ĐỀ THI ---
{text}"""

    response = model.generate_content(user_prompt)
    return json.loads(response.text)

def parse_answer_key_pdf(api_key, text):
    genai.configure(api_key=api_key)
    
    SYSTEM_PROMPT_DAPAN = """Bạn là hệ thống bóc tách đáp án thi trắc nghiệm. 
Trích xuất văn bản từ file Đáp án của Bộ GD&ĐT thành JSON theo cấu trúc quy định. Đặc biệt nếu file là bảng ma trận đáp án cho nhiều mã đề, hãy lặp qua tất cả để bóc tách.
Quy tắc:
- ma_de: chuỗi 3 hoặc 4 chữ số (VD: "101", "0503")
- phan: số nguyên 1, 2, hoặc 3.
- cau: số nguyên (VD: 1, 2, 3...)
- y: áp dụng cho Phần 2 là "A", "B", "C", "D". Phần 1 hoặc 3 thì để "".
- dap_an: Phần 1 ("A", "B", "C", "D"); Phần 2 ("Đúng", "Sai"); Phần 3 (giá trị số)."""

    class AnswerRecord(typing.TypedDict):
        ma_de: str
        phan: int
        cau: int
        y: str
        dap_an: str

    class AnswerKeyResponse(typing.TypedDict):
        danh_sach: list[AnswerRecord]

    model = genai.GenerativeModel(
        model_name="gemini-flash-latest",
        system_instruction=SYSTEM_PROMPT_DAPAN,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=AnswerKeyResponse,
            temperature=0.1
        )
    )
    
    prompt = f"Trích xuất đáp án từ nội dung:\n\n{text}"
    response = model.generate_content(prompt)
    data = json.loads(response.text)
    
    rows = []
    for item in data.get("danh_sach", []):
        rows.append({
            "Mã Đề": str(item.get("ma_de", "")).strip(),
            "Phần": item.get("phan"),
            "Câu": item.get("cau"),
            "Ý": item.get("y", ""),
            "Đáp Án": str(item.get("dap_an", "")).strip()
        })
    return pd.DataFrame(rows)

def save_to_mongodb(mongo_uri, data, ma_de, nam_thi):
    try:
        client = MongoClient(mongo_uri)
        db = client['ai_exam_grader']
        collection = db['exam_results']
        
        record = {
            "ma_de": ma_de,
            "nam_thi": nam_thi,
            "timestamp": time.time(),
            "ket_qua": data
        }
        
        collection.insert_one(record)
        return True
    except Exception as e:
        st.error(f"Lỗi kết nối MongoDB: {e}")
        return False

def compare_results(ai_data, answer_key_df, ma_de_hien_tai=None):
    results = []
    
    # Nếu file đáp án có cột Mã Đề, lọc ra đáp án của mã đề hiện tại
    if 'Mã Đề' in answer_key_df.columns and ma_de_hien_tai:
        answer_key_df['Mã Đề'] = answer_key_df['Mã Đề'].astype(str)
        df_filtered = answer_key_df[answer_key_df['Mã Đề'] == str(ma_de_hien_tai)]
    else:
        df_filtered = answer_key_df

    if df_filtered.empty:
        return pd.DataFrame()

    # Đối sánh Phần 1
    if "phan_1" in ai_data:
        for item in ai_data["phan_1"]:
            cau = item.get("cau_hoi")
            dap_an_ai = item.get("dap_an")
            giai_thich = item.get("giai_thich_ngam", "")
            
            match = df_filtered[(df_filtered['Phần'] == 1) & (df_filtered['Câu'] == cau)]
            if not match.empty:
                dap_an_chuan = str(match.iloc[0]['Đáp Án']).strip().upper()
                is_correct = str(dap_an_ai).strip().upper() == dap_an_chuan
                results.append({
                    "Mã Đề": ma_de_hien_tai,
                    "Phần": 1,
                    "Câu": cau,
                    "AI Chọn": dap_an_ai,
                    "Đáp Án Chuẩn": dap_an_chuan,
                    "Kết Quả": "✅ Đúng" if is_correct else "❌ Sai",
                    "Giải Thích": giai_thich
                })
                
    # Đối sánh Phần 2
    if "phan_2" in ai_data:
        for item in ai_data["phan_2"]:
            cau = item.get("cau_hoi")
            giai_thich = item.get("giai_thich_ngam", "")
            for i, y in enumerate(['y_a', 'y_b', 'y_c', 'y_d']):
                dap_an_ai = item.get(y)
                y_label = chr(65 + i) # A, B, C, D
                match = df_filtered[(df_filtered['Phần'] == 2) & (df_filtered['Câu'] == cau) & (df_filtered['Ý'] == y_label)]
                if not match.empty:
                    dap_an_chuan = str(match.iloc[0]['Đáp Án']).strip().capitalize()
                    is_correct = str(dap_an_ai).strip().capitalize() == dap_an_chuan
                    results.append({
                        "Mã Đề": ma_de_hien_tai,
                        "Phần": 2,
                        "Câu": f"{cau}{y_label}",
                        "AI Chọn": dap_an_ai,
                        "Đáp Án Chuẩn": dap_an_chuan,
                        "Kết Quả": "✅ Đúng" if is_correct else "❌ Sai",
                        "Giải Thích": giai_thich if i == 0 else ""
                    })

    # Đối sánh Phần 3
    if "phan_3" in ai_data:
        for item in ai_data["phan_3"]:
            cau = item.get("cau_hoi")
            dap_an_ai = item.get("dap_an")
            giai_thich = item.get("giai_thich_ngam", "")
            
            match = df_filtered[(df_filtered['Phần'] == 3) & (df_filtered['Câu'] == cau)]
            if not match.empty:
                dap_an_chuan = str(match.iloc[0]['Đáp Án']).strip()
                is_correct = str(dap_an_ai).strip() == dap_an_chuan
                results.append({
                    "Mã Đề": ma_de_hien_tai,
                    "Phần": 3,
                    "Câu": cau,
                    "AI Chọn": dap_an_ai,
                    "Đáp Án Chuẩn": dap_an_chuan,
                    "Kết Quả": "✅ Đúng" if is_correct else "❌ Sai",
                    "Giải Thích": giai_thich
                })

    return pd.DataFrame(results)

# --- GIAO DIỆN CHÍNH ---
def main():
    st.title("🤖 Trợ Lý AI Chấm Thi Tin Học (Hỗ trợ Xử Lý Lô - Batch)")
    st.markdown("Hệ thống bóc tách, giải đề và đối sánh tự động ứng dụng Generative AI.")
    st.markdown("---")
    
    # Sidebar: Cấu hình
    with st.sidebar:
        st.header("⚙️ Cấu Hình Hệ Thống")
        
        gemini_api_key = st.text_input("Gemini API Key", value=os.getenv("GEMINI_API_KEY", ""), type="password")
        mongo_uri = st.text_input("MongoDB URI (Tuỳ chọn)", value=os.getenv("MONGODB_URI", ""), type="password")
        
        st.markdown("---")
        st.markdown("### Cấu Hình Năm Thi")
        nam_thi = st.text_input("Năm Thi", "2024")
        st.caption("Lưu ý: Bạn nên đặt tên file PDF đề thi có chứa 3 số mã đề (vd: 'De_101.pdf', '102.pdf') để ứng dụng tự động nhận diện Mã Đề và tra cứu đáp án.")

    # Layout tải file
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📄 Tải Lên Đề Thi (PDF)")
        pdf_files = st.file_uploader("Kéo thả 1 hoặc NHIỀU file PDF đề thi vào đây", type=['pdf'], accept_multiple_files=True)
        
    with col2:
        st.subheader("📊 Tải Lên Đáp Án Chuẩn (PDF/CSV/Excel)")
        st.caption("Ứng dụng hỗ trợ tự động bóc tách cả file PDF Đáp án của Bộ GD&ĐT!")
        answer_file = st.file_uploader("Kéo thả file Đáp án vào đây (Hỗ trợ PDF, CSV, Excel)", type=['pdf', 'csv', 'xlsx'])

    # Nút xử lý
    if st.button("🚀 Bắt Đầu Xử Lý Hàng Loạt", use_container_width=True, type="primary"):
        if not gemini_api_key:
            st.warning("Vui lòng nhập Gemini API Key trong phần cấu hình!")
            return
            
        if not pdf_files:
            st.warning("Vui lòng tải lên ít nhất 1 file PDF đề thi!")
            return
            
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Đọc file đáp án 1 lần duy nhất
        df_answers = None
        if answer_file:
            if answer_file.name.endswith('.csv'):
                df_answers = pd.read_csv(answer_file)
            elif answer_file.name.endswith('.xlsx'):
                df_answers = pd.read_excel(answer_file)
            elif answer_file.name.endswith('.pdf'):
                status_text.info("Đang dùng AI Gemini để tự động bóc tách và chuẩn hóa file PDF Đáp án Bộ GD&ĐT...")
                answer_text = extract_text_from_pdf(answer_file)
                df_answers = parse_answer_key_pdf(gemini_api_key, answer_text)
                with st.expander("Bảng Đáp án chuẩn (Đã chuẩn hóa bằng AI)"):
                    st.dataframe(df_answers)

        total_files = len(pdf_files)
        all_results_summary = []

        import re

        for idx, pdf_file in enumerate(pdf_files):
            # Cố gắng trích xuất 3 hoặc 4 chữ số làm mã đề từ tên file
            match = re.search(r'\d{3,4}', pdf_file.name)
            current_ma_de = match.group() if match else pdf_file.name.split('.')[0]
            
            st.markdown(f"### Đang xử lý Đề: {current_ma_de} (File: {pdf_file.name})")
            
            try:
                # Bước 1: Trích xuất PDF
                status_text.info(f"[{idx+1}/{total_files}] Đang bóc tách dữ liệu từ PDF...")
                exam_text = extract_text_from_pdf(pdf_file)
                
                # Bước 2: Gọi AI
                status_text.info(f"[{idx+1}/{total_files}] Đang gửi yêu cầu đến Gemini (Vui lòng đợi để tránh quá tải API)...")
                ai_result = call_gemini_api(gemini_api_key, exam_text, current_ma_de, nam_thi)
                
                # Bước 3: Lưu Database
                if mongo_uri:
                    save_to_mongodb(mongo_uri, ai_result, current_ma_de, nam_thi)

                # Bước 4: Đối sánh kết quả
                if df_answers is not None:
                    comparison_df = compare_results(ai_result, df_answers, current_ma_de)
                    
                    if not comparison_df.empty:
                        correct_count = len(comparison_df[comparison_df['Kết Quả'] == '✅ Đúng'])
                        total_count = len(comparison_df)
                        score = (correct_count / total_count) * 10
                        
                        st.success(f"Hoàn thành đối sánh! Điểm: {score:.2f} / 10 ({correct_count}/{total_count})")
                        all_results_summary.append({
                            "Mã Đề": current_ma_de,
                            "File Tên": pdf_file.name,
                            "Điểm (Hệ 10)": round(score, 2),
                            "Số câu đúng": f"{correct_count}/{total_count}"
                        })
                        
                        with st.expander(f"Xem chi tiết đối sánh - Đề {current_ma_de}"):
                            st.dataframe(
                                comparison_df.style.applymap(
                                    lambda val: 'color: green' if val == '✅ Đúng' else 'color: red',
                                    subset=['Kết Quả']
                                ), 
                                use_container_width=True
                            )
                    else:
                        st.warning(f"Không tìm thấy dữ liệu đáp án của Mã đề {current_ma_de} trong file CSV/Excel.")
                else:
                    st.success(f"Giải xong Đề {current_ma_de} (Không đối sánh)")
                    with st.expander(f"Dữ liệu JSON - Đề {current_ma_de}"):
                        st.json(ai_result)

                # Delay 4 giây giữa các đề để tránh bị Google block (Rate Limit API Free)
                if idx < total_files - 1:
                    status_text.info(f"Đang nghỉ 4s trước khi xử lý đề tiếp theo để chống quá tải (Rate Limit)...")
                    time.sleep(4)
                
                progress_bar.progress((idx + 1) / total_files)
                
            except Exception as e:
                st.error(f"Lỗi khi xử lý đề {pdf_file.name}: {str(e)}")

        status_text.empty()
        
        # Hiển thị bảng tổng hợp
        if all_results_summary:
            st.markdown("---")
            st.header("🏆 BẢNG TỔNG HỢP KẾT QUẢ CHẤM THI HÀNG LOẠT")
            summary_df = pd.DataFrame(all_results_summary)
            st.dataframe(summary_df, use_container_width=True)
            
            # Xuất file CSV kết quả
            csv_export = summary_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Tải xuống Bảng Kết Quả (CSV)",
                data=csv_export,
                file_name=f'ket_qua_cham_thi_batch_{nam_thi}.csv',
                mime='text/csv',
            )

        st.balloons()
        st.success(f"Đã hoàn tất quy trình chạy lô {total_files} đề thi!")

if __name__ == "__main__":
    main()
