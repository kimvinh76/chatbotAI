"""
=============================================================================
MODULE: core/mock_data.py
CHỨC NĂNG:
- Sinh dữ liệu bài giải giả lập (Dry-Run / Mock) để chạy thử nghiệm giao diện.
- Cho phép người dùng kiểm tra toàn diện Tab 1 và Tab 2 mà tiêu tốn 0 token Gemini.
- Tự động tạo đợt thi mẫu (Demo Batch) trong MongoDB để xem giao diện Lịch Sử.
=============================================================================
"""

import time
import random
from datetime import datetime
import pandas as pd

from core.database import (
    get_answer_keys_from_db,
    save_to_mongodb,
    save_grading_batch,
    get_mongo_db
)
from core.grading_logic import build_comparison_and_detail_df


def generate_mock_exam_solution(ma_de: str, nam_thi: str = "2026", mongo_uri: str = None) -> dict:
    """
    Sinh bài giải JSON mô phỏng của AI cho 1 mã đề (0 token Gemini API).
    Sử dụng đáp án chuẩn từ MongoDB làm nền tảng và cố ý làm sai 2-3 câu/ý
    để người dùng quan sát được cả dòng Đúng (xanh lá) và Sai (đỏ) trên bảng chi tiết.
    """
    ma_de_str = str(ma_de).strip()
    nam_thi_str = str(nam_thi).strip()
    
    # 1. Thử lấy đáp án chuẩn từ MongoDB
    key_df = pd.DataFrame()
    if mongo_uri:
        key_df = get_answer_keys_from_db(mongo_uri, nam_thi=nam_thi_str, target_codes=[ma_de_str])
    
    # Chuẩn bị Phần I (24 câu trắc nghiệm)
    phan_1 = []
    p1_keys = {}
    if not key_df.empty:
        df_p1 = key_df[key_df['Phần'].astype(str).str.contains('I', na=False)]
        for _, r in df_p1.iterrows():
            try:
                c_num = int(r['Câu'])
                p1_keys[c_num] = str(r['Đáp Án']).strip().upper()
            except Exception:
                pass
                
    # Ngân hàng giải thích chuyên môn mô phỏng sát chuẩn đề thi Tin học 12
    p1_exps = {
        1: "Thiết bị định tuyến (Router) chuyển tiếp các gói tin giữa các mạng khác nhau dựa trên bảng định tuyến IP.",
        2: "Giao thức TCP hoạt động ở tầng Giao vận (Transport layer), cung cấp kết nối tin cậy và có kiểm soát luồng.",
        3: "Bộ nhớ RAM là bộ nhớ khả biến, toàn bộ dữ liệu lưu trữ sẽ bị xóa sạch khi máy tính ngắt nguồn điện.",
        4: "Địa chỉ IPv4 gồm 32 bit, được chia thành 4 octet biểu diễn dưới dạng số thập phân cách nhau bởi dấu chấm.",
        5: "Mô hình nhận định nhầm lẫn giữa chức năng chuyển mạch của Switch (tầng 2) và thiết bị Hub (tầng 1).",
        6: "Mạng cục bộ (LAN) kết nối các máy tính trong phạm vi địa lý hẹp như văn phòng, trường học với độ trễ thấp.",
        7: "Dịch vụ phân giải tên miền (DNS) có vai trò biên dịch tên miền dạng chữ sang địa chỉ IP dạng số của máy chủ.",
        8: "Trí tuệ nhân tạo (AI) học máy (Machine Learning) tự động phát hiện mẫu và trích xuất quy luật từ tập dữ liệu.",
        9: "Chuẩn giao tiếp không dây Wi-Fi (IEEE 802.11) truyền dữ liệu bằng sóng vô tuyến qua các băng tần 2.4GHz và 5GHz.",
        10: "Hệ điều hành mã nguồn mở Linux cho phép người dùng tự do xem, chỉnh sửa và phân phối lại mã nguồn.",
        11: "Tường lửa (Firewall) lọc và kiểm soát các gói tin mạng vào/ra dựa trên các tập quy tắc bảo mật xác định trước.",
        12: "Giao thức HTTPS kết hợp mã hóa TLS/SSL để bảo vệ tính bảo mật và toàn vẹn của dữ liệu truyền trên web.",
        13: "Điện toán đám mây (Cloud Computing) cung cấp năng lực tính toán và không gian lưu trữ qua mạng Internet theo nhu cầu.",
        14: "Mô hình suy luận nhầm lẫn: phương thức mã hóa khóa đối xứng (AES) dùng chung một khóa chứ không dùng cặp khóa.",
        15: "Chữ ký số xác thực danh tính người gửi và đảm bảo tính toàn vẹn của văn bản điện tử bằng mật mã bất đối xứng.",
        16: "Cáp quang ứng dụng hiện tượng phản xạ toàn phần của tia sáng trong lõi thủy tinh để truyền dẫn dữ liệu tốc độ cao.",
        17: "Kiến trúc mạng Transformer sử dụng cơ chế Self-Attention để mô hình hóa mối tương quan ngữ cảnh giữa các từ.",
        18: "HTML là ngôn ngữ đánh dấu siêu văn bản, dùng để xây dựng cấu trúc và định hình nội dung của trang web.",
        19: "Chuẩn bảo mật mạng không dây WPA3 trang bị thuật toán mã hóa SAE giúp chống lại các cuộc tấn công từ điển.",
        20: "Cơ sở dữ liệu quan hệ lưu trữ dữ liệu dưới dạng các bảng 2 chiều có liên kết thông qua khóa chính và khóa ngoại.",
        21: "Địa chỉ MAC là định danh vật lý duy nhất 48 bit được nhà sản xuất ghi cố định vào card mạng (NIC).",
        22: "Hành vi sử dụng, sao chép phần mềm không có bản quyền thương mại là vi phạm quyền tác giả và Luật Sở hữu trí tuệ.",
        23: "Mạng hình sao (Star Topology) kết nối tất cả các máy trạm độc lập về một thiết bị trung tâm (Switch/Hub).",
        24: "Mã độc tống tiền (Ransomware) chiếm quyền kiểm soát, mã hóa dữ liệu máy nạn nhân và yêu cầu tiền chuộc để giải mã."
    }

    for c in range(1, 25):
        ans_std = p1_keys.get(c, random.choice(['A', 'B', 'C', 'D']))
        # Cố ý làm sai câu 5 và câu 14 để có mẫu câu sai kiểm tra màu đỏ và phân tích ca lỗi
        if c in [5, 14]:
            wrong_choices = [x for x in ['A', 'B', 'C', 'D'] if x != ans_std]
            ans_chosen = wrong_choices[0] if wrong_choices else 'B'
            exp = p1_exps.get(c, f"Mô hình nhầm lẫn khái niệm chuyên môn câu {c}.")
        else:
            ans_chosen = ans_std
            exp = p1_exps.get(c, f"Căn cứ lý thuyết Tin học chuẩn cho nội dung câu {c}.")
            
        phan_1.append({
            "cau_hoi": c,
            "dap_an": ans_chosen,
            "giai_thich": exp
        })

    # Chuẩn bị Phần II (6 câu Đúng/Sai)
    phan_2 = []
    p2_keys = {}
    if not key_df.empty:
        df_p2 = key_df[~key_df['Phần'].astype(str).str.contains('I', na=False)]
        for _, r in df_p2.iterrows():
            try:
                c_num = int(r['Câu'])
                y_lbl = str(r['Ý']).strip().lower()
                val = str(r['Đáp Án']).strip()
                if val.upper() in ['Đ', 'D', 'ĐÚNG', 'TRUE']:
                    val_str = 'Đúng'
                else:
                    val_str = 'Sai'
                p2_keys[(c_num, y_lbl)] = val_str
            except Exception:
                pass

    p2_exps = {
        1: {
            'a': "Vòng lặp for duyệt tuần tự từng phần tử trong danh sách với độ phức tạp thời gian O(n).",
            'b': "Lệnh if-else kiểm tra chia hết: nếu n chia hết cho d thì lập tức trả về False (không phải số nguyên tố).",
            'c': "Lỗi suy luận: range(2, int(n**0.5) + 1) cần lấy cận trên căn bậc hai của n để kiểm tra đủ ước số.",
            'd': "Hàm trả về danh sách các số nguyên tố thỏa mãn điều kiện bài toán một cách chính xác."
        },
        2: {
            'a': "Phương thức split() phân tách chuỗi thành mảng các từ con dựa trên ký tự khoảng trắng mặc định.",
            'b': "Cấu trúc từ điển (dict) lưu tần suất xuất hiện với độ phức tạp tra cứu trung bình O(1).",
            'c': "Lỗi suy luận: hàm sort() sắp xếp tại chỗ (in-place) và trả về None, không gán lại được cho biến.",
            'd': "Biểu thức lambda kết hợp hàm sorted() sắp xếp danh sách giảm dần theo số lần xuất hiện chuẩn cú pháp."
        },
        3: {
            'a': "Hàm đệ quy tính số Fibonacci có điều kiện dừng cơ sở n <= 1 trả về chính giá trị n.",
            'b': "Độ phức tạp thời gian của thuật toán đệ quy ngây thơ là O(2^n) do lặp lại các bài toán con trùng lặp.",
            'c': "Kỹ thuật ghi nhớ (Memoization) lưu trữ kết quả bài toán con giúp giảm thời gian chạy xuống O(n).",
            'd': "Thuật toán quy hoạch động sử dụng mảng phụ 1 chiều tối ưu không gian bộ nhớ thành O(1)."
        },
        4: {
            'a': "Thuật toán tìm kiếm nhị phân (Binary Search) yêu cầu mảng đầu vào bắt buộc phải được sắp xếp trước.",
            'b': "Mỗi bước so sánh chia đôi không gian tìm kiếm, độ phức tạp thời gian đạt O(log n).",
            'c': "Lỗi suy luận: khi mảng tại vị trí mid bằng khóa tìm kiếm thì thuật toán dừng ngay và trả về chỉ số mid.",
            'd': "Vòng lặp while kết thúc khi left > right biểu thị giá trị cần tìm không xuất hiện trong mảng."
        },
        5: {
            'a': "Khóa chính (Primary Key) định danh duy nhất mỗi bản ghi trong bảng và không được phép chứa giá trị NULL.",
            'b': "Khóa ngoại (Foreign Key) tạo mối liên kết tham chiếu toàn vẹn đến khóa chính của bảng quan hệ khác.",
            'c': "Câu lệnh SELECT kết hợp INNER JOIN liên kết đúng các bản ghi có khóa trùng khớp ở hai bảng.",
            'd': "Mệnh đề GROUP BY bắt buộc mọi cột không nằm trong hàm tổng hợp (SUM, COUNT) phải xuất hiện trong GROUP BY."
        },
        6: {
            'a': "Mệnh đề WHERE thực hiện lọc các bản ghi trước khi bảng thực hiện phép gom nhóm dữ liệu.",
            'b': "Mệnh đề HAVING dùng để lọc các nhóm sau khi đã gom nhóm và tính toán hàm tổng hợp (như COUNT(*) >= 2).",
            'c': "Mệnh đề ORDER BY ... DESC sắp xếp kết quả trả về theo thứ tự giảm dần của cột điểm chuẩn xác.",
            'd': "Hàm COUNT(DISTINCT MaHS) đếm số lượng học sinh duy nhất tham gia kỳ thi mà không tính trùng lặp."
        }
    }

    for c in range(1, 7):
        ans_a = p2_keys.get((c, 'a'), 'Đúng')
        ans_b = p2_keys.get((c, 'b'), 'Sai')
        ans_c = p2_keys.get((c, 'c'), 'Đúng')
        ans_d = p2_keys.get((c, 'd'), 'Sai')

        # Cố ý làm sai ý c của câu 2 và ý c của câu 4
        if c == 2:
            ans_c = 'Sai' if ans_c == 'Đúng' else 'Đúng'
        if c == 4:
            ans_c = 'Sai' if ans_c == 'Đúng' else 'Đúng'

        exp_c = p2_exps.get(c, {})
        phan_2.append({
            "cau_hoi": c,
            "y_a": ans_a,
            "y_b": ans_b,
            "y_c": ans_c,
            "y_d": ans_d,
            "giai_thich_a": exp_c.get('a', f"Câu {c} ý a: Vòng lặp duyệt tuần tự mảng với độ phức tạp O(n)."),
            "giai_thich_b": exp_c.get('b', f"Câu {c} ý b: Cấu trúc điều kiện rẽ nhánh if-else đáp ứng tiêu chí thuật toán."),
            "giai_thich_c": exp_c.get('c', f"Câu {c} ý c: Biểu thức logic và phép gán biến thỏa mãn điều kiện bài toán."),
            "giai_thich_d": exp_c.get('d', f"Câu {c} ý d: Phép truy vấn cơ sở dữ liệu quan hệ SQL SELECT kết hợp GROUP BY cho kết quả chuẩn.")
        })

    # Chẩn đoán token giả lập
    mock_diag = [
        {"buoc": "Pha 1 (Bóc tách & 24 câu P1)", "finish": "STOP", "token_vao": 2180, "token_ra": 640, "token_nghi": 380},
        {"buoc": "Pha 2 (6 câu Đúng/Sai P2)", "finish": "STOP", "token_vao": 3450, "token_ra": 1520, "token_nghi": 960}
    ]

    return {
        "nam_thi": nam_thi_str,
        "ma_de": ma_de_str,
        "phan_1": phan_1,
        "phan_2": phan_2,
        "chan_doan_token": mock_diag
    }


def create_demo_batch_in_db(mongo_uri: str, nam_thi: str = "2026") -> tuple[bool, str]:
    """
    Tạo nhanh 1 đợt chấm thi mẫu gồm 2 bài thi (Đề 0501 và Đề 0502) nạp vào MongoDB Atlas.
    Giúp người dùng trải nghiệm ngay 100% giao diện Tab 2 (Lịch Sử) mà tiêu tốn 0 token.
    """
    if not mongo_uri:
        return False, "Chưa cấu hình MONGODB_URI"

    try:
        now_dt = datetime.now()
        batch_id = f"BATCH_DEMO_{now_dt.strftime('%Y%m%d_%H%M%S')}"
        ten_dot = f"Đợt Chấm Mẫu Demo ({now_dt.strftime('%d/%m/%Y %H:%M')})"
        
        sample_codes = ["0501", "0502"] if nam_thi == "2026" else ["0501", "0504"]
        summary_list = []

        for code in sample_codes:
            ai_data = generate_mock_exam_solution(code, nam_thi, mongo_uri)
            key_df = get_answer_keys_from_db(mongo_uri, nam_thi=nam_thi, target_codes=[code])
            
            detail_df, has_key = build_comparison_and_detail_df(
                ai_data=ai_data,
                answer_key_df=key_df,
                ma_de_hien_tai=code,
                file_name=f"De_Thi_Mau_{code}.pdf"
            )

            total_count = len(detail_df) if not detail_df.empty else 48
            p1_df = detail_df[detail_df['Phần'] == "Phần I (Trắc nghiệm)"] if not detail_df.empty else pd.DataFrame()
            p2_df = detail_df[detail_df['Phần'] != "Phần I (Trắc nghiệm)"] if not detail_df.empty else pd.DataFrame()
            
            p1_total = len(p1_df) if not p1_df.empty else 24
            p1_correct = len(p1_df[p1_df['Kết Quả'].astype(str).str.contains('Đúng', na=False)]) if not p1_df.empty else 22
            p2_total = len(p2_df) if not p2_df.empty else 24
            p2_correct = len(p2_df[p2_df['Kết Quả'].astype(str).str.contains('Đúng', na=False)]) if not p2_df.empty else 22
            
            correct_count = p1_correct + p2_correct
            score = round((correct_count / total_count) * 10, 2)
            
            # Thời gian phản hồi giả lập
            latency = 1.85 if code == sample_codes[0] else 2.15
            token_in = 5630
            token_out = 2160
            token_thought = 1340
            cost_vnd = 35.5

            summary_item = {
                "Mã Đề": code,
                "Năm Thi": nam_thi,
                "Tên File": f"De_Thi_Mau_{code}.pdf",
                "Điểm (Hệ 10)": score,
                "Số câu đúng": correct_count,
                "Tổng số câu": total_count,
                "Tỷ lệ đúng (%)": round((correct_count / total_count * 100), 2),
                "P1 Trắc nghiệm": f"{p1_correct}/{p1_total}",
                "P2 Đúng/Sai": f"{p2_correct}/{p2_total}",
                "Model AI": "gemini-3.8-flash (Demo Mode)",
                "Thời gian (s)": latency,
                "Token Vào": token_in,
                "Token Ra": token_out,
                "Token Nghĩ": token_thought,
                "Chi Phí (VNĐ)": cost_vnd,
                "Thời Gian Chấm": now_dt.strftime("%Y-%m-%d %H:%M:%S")
            }
            summary_list.append(summary_item)

            save_to_mongodb(
                mongo_uri=mongo_uri,
                data=ai_data,
                ma_de=code,
                nam_thi=nam_thi,
                ten_file=f"De_Thi_Mau_{code}.pdf",
                batch_id=batch_id,
                loai_tai_lieu="digital_text",
                score=score,
                correct_count=correct_count,
                total_count=total_count,
                p1_correct=p1_correct,
                p1_total=p1_total,
                p2_correct=p2_correct,
                p2_total=p2_total,
                comparison_data=detail_df,
                model_name="gemini-3.8-flash (Demo Mode)",
                latency_sec=latency,
                token_in=token_in,
                token_out=token_out,
                token_thought=token_thought,
                cost_vnd=cost_vnd,
                source="Demo"
            )

        save_grading_batch(
            mongo_uri=mongo_uri,
            batch_id=batch_id,
            ten_dot_thi=ten_dot,
            nam_thi=nam_thi,
            model_name="gemini-3.8-flash (Demo Mode)",
            summary_list=summary_list
        )

        return True, batch_id
    except Exception as e:
        return False, str(e)

