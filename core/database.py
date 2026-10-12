"""
=============================================================================
MODULE: core/database.py
CHỨC NĂNG:
- Quản lý kết nối MongoDB Atlas (Connection Pool tái sử dụng vĩnh viễn, loại bỏ độ trễ TLS 8s).
- Quản lý 4 Collections chuẩn đồ án chuyên ngành:
  1. answer_keys: Ngân hàng đáp án chuẩn của Bộ GD&ĐT (có cơ chế Khóa Bảo Vệ).
  2. solved_exams: Bộ nhớ đệm (Cache) bài giải của AI để tiết kiệm Token.
  3. grading_batches: Quản lý theo từng Đợt thi / Ca chấm thi hàng loạt.
  4. exam_results: Kết quả chi tiết từng bài thi & đối sánh điểm.
=============================================================================
"""

import time
from datetime import datetime
import pandas as pd
from pymongo import MongoClient
import streamlit as st
from core.excel_utils import df_to_excel_bytes


@st.cache_resource(show_spinner=False)
def get_mongo_client(mongo_uri):
    """
    Khởi tạo connection pool duy nhất cho toàn ứng dụng, tái sử dụng kết nối TLS vĩnh viễn (loại bỏ độ trễ 8s).
    """
    if not mongo_uri:
        return None
    try:
        return MongoClient(
            mongo_uri,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=5000,
            maxPoolSize=50,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000
        )
    except Exception:
        return None


def get_mongo_db(mongo_uri):
    """
    Lấy database 'ai_exam_grader' từ client đã được cache sẵn (truy xuất tức thì < 0.001s thay vì 8-9s tạo mới).
    """
    if not mongo_uri:
        return None
    try:
        client = get_mongo_client(mongo_uri)
        if client is None:
            return None
        return client['ai_exam_grader']
    except Exception:
        return None


# ==============================================================================
# COLLECTION 1: answer_keys (Ngân Hàng Đáp Án Chuẩn)
# ==============================================================================

def save_answer_keys_to_db(mongo_uri, df_answers, nam_thi="2025", source_name="", allow_overwrite_verified=False):
    """
    Lưu bảng đáp án chuẩn bóc tách được vào collection 'answer_keys'.
    Tự động BẢO VỆ các mã đề đã được con người duyệt (trang_thai == 'da_xac_thuc'), không bị ghi đè ngẫu nhiên!
    """
    if not mongo_uri or df_answers is None or df_answers.empty:
        return False, "Không có dữ liệu đáp án để lưu"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        count = 0
        protected_list = []
        for ma_de, group in df_answers.groupby("Mã Đề"):
            ma_de_str = str(ma_de).strip()
            # Kiểm tra xem mã đề này trong DB đã được duyệt thủ công hay chưa
            existing = col.find_one({"ma_de": ma_de_str, "nam_thi": str(nam_thi)})
            if not existing:
                existing = col.find_one({"ma_de": ma_de_str.lstrip('0'), "nam_thi": str(nam_thi)})
                
            if existing and existing.get("trang_thai") == "da_xac_thuc" and not allow_overwrite_verified:
                protected_list.append(ma_de_str)
                continue
                
            items = group[['Phần', 'Câu', 'Ý', 'Đáp Án']].to_dict(orient='records')
            col.update_one(
                {"ma_de": ma_de_str, "nam_thi": str(nam_thi)},
                {"$set": {
                    "ma_de": ma_de_str,
                    "nam_thi": str(nam_thi),
                    "nguon_file": str(source_name),
                    "so_cau_hoi": len(items),
                    "thoi_gian_luu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "trang_thai": "tu_dong_ai",
                    "danh_sach_dap_an": items
                }},
                upsert=True
            )
            count += 1
            
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        msg = f"Đã đồng bộ {count} mã đề vào ngân hàng đáp án."
        if protected_list:
            msg += f" 🛡️ Đã bảo vệ {len(protected_list)} mã đề đã duyệt ({', '.join(protected_list)}) không bị ghi đè!"
        return True, msg
    except Exception as e:
        return False, str(e)


def get_answer_keys_from_db(mongo_uri, nam_thi="2025", target_codes=None):
    """
    Lấy đáp án chuẩn từ collection 'answer_keys' tái cấu trúc thành DataFrame.
    """
    if not mongo_uri:
        return pd.DataFrame()
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return pd.DataFrame()
        col = db['answer_keys']
        docs = list(col.find({"nam_thi": str(nam_thi)}))
        rows = []
        for doc in docs:
            ma_de = str(doc.get("ma_de", "")).strip()
            if target_codes:
                clean_target = [str(c).strip() for c in target_codes]
                clean_target_nozero = [c.lstrip('0') for c in clean_target]
                if ma_de not in clean_target and ma_de.lstrip('0') not in clean_target_nozero:
                    continue
            for item in doc.get("danh_sach_dap_an", []):
                rows.append({
                    "Mã Đề": ma_de,
                    "Phần": item.get("Phần"),
                    "Câu": item.get("Câu"),
                    "Ý": item.get("Ý", ""),
                    "Đáp Án": item.get("Đáp Án")
                })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


def check_verified_answer_key(mongo_uri, ma_de, nam_thi):
    """
    Kiểm tra xem mã đề này trong MongoDB đã có bản đã xác thực thủ công hay chưa để ưu tiên sử dụng (Khóa An Toàn).
    """
    if not mongo_uri or not ma_de:
        return None
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return None
        col = db['answer_keys']
        doc = col.find_one({"ma_de": str(ma_de), "nam_thi": str(nam_thi)})
        if not doc:
            doc = col.find_one({"ma_de": str(ma_de).lstrip('0'), "nam_thi": str(nam_thi)})
        if not doc and len(str(ma_de)) == 3:
            doc = col.find_one({"ma_de": f"0{str(ma_de)}", "nam_thi": str(nam_thi)})
        if doc and doc.get("trang_thai") == "da_xac_thuc":
            rows = []
            for item in doc.get("danh_sach_dap_an", []):
                rows.append({
                    "Mã Đề": str(ma_de),
                    "Phần": item.get("Phần"),
                    "Câu": item.get("Câu"),
                    "Ý": item.get("Ý", ""),
                    "Đáp Án": item.get("Đáp Án")
                })
            return pd.DataFrame(rows)
    except Exception:
        pass
    return None


@st.cache_data(ttl=120, show_spinner=False)
def get_all_answer_keys_summary(mongo_uri, nam_thi=None):
    """
    Lấy danh sách tóm tắt tất cả các mã đề đáp án đang có trong ngân hàng (có Cache RAM).
    """
    if not mongo_uri:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['answer_keys']
        query = {"nam_thi": str(nam_thi)} if (nam_thi and nam_thi != "Tất cả") else {}
        docs = list(col.find(query, {"ma_de": 1, "nam_thi": 1, "so_cau_hoi": 1, "thoi_gian_luu": 1, "nguon_file": 1, "trang_thai": 1}))
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []


def get_single_answer_key_detail(mongo_uri, ma_de, nam_thi):
    """
    Lấy chi tiết bảng đáp án của 1 mã đề cụ thể từ collection 'answer_keys'.
    """
    if not mongo_uri or not ma_de:
        return pd.DataFrame(), None
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return pd.DataFrame(), None
        col = db['answer_keys']
        doc = col.find_one({"ma_de": str(ma_de), "nam_thi": str(nam_thi)})
        if not doc:
            doc = col.find_one({"ma_de": str(ma_de).lstrip('0'), "nam_thi": str(nam_thi)})
        if doc and "danh_sach_dap_an" in doc:
            return pd.DataFrame(doc["danh_sach_dap_an"]), doc.get("trang_thai", "tu_dong_ai")
    except Exception:
        pass
    return pd.DataFrame(), None


def update_single_answer_key(mongo_uri, ma_de, nam_thi, df_items):
    """
    Cập nhật lại danh sách đáp án sau khi người dùng sửa trên st.data_editor.
    Tự động gắn cờ 'da_xac_thuc' để KHÓA BẢO VỆ vĩnh viễn không bị file mới ghi đè!
    """
    if not mongo_uri or df_items is None or df_items.empty:
        return False, "Không có dữ liệu hợp lệ"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        items = df_items[['Phần', 'Câu', 'Ý', 'Đáp Án']].to_dict(orient='records')
        col.update_one(
            {"ma_de": str(ma_de), "nam_thi": str(nam_thi)},
            {"$set": {
                "danh_sach_dap_an": items,
                "so_cau_hoi": len(items),
                "trang_thai": "da_xac_thuc",
                "thoi_gian_luu": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }},
            upsert=True
        )
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"🛡️ Đã KHÓA BẢO VỆ & cập nhật đáp án chuẩn cho Mã đề {ma_de} (Năm {nam_thi}) thành công!"
    except Exception as e:
        return False, str(e)


def delete_answer_key_from_db(mongo_uri, ma_de, nam_thi):
    """
    Xóa một mã đề đáp án khỏi collection 'answer_keys'.
    """
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        col.delete_one({"ma_de": str(ma_de), "nam_thi": str(nam_thi)})
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"Đã xóa mã đề {ma_de} (Năm {nam_thi}) khỏi Ngân Hàng Đáp Án"
    except Exception as e:
        return False, str(e)


def cleanup_duplicate_answer_keys(mongo_uri, nam_thi=None):
    """
    Tự động dọn dẹp các mã đề 3 chữ số dư thừa (501, 510) gộp về chuẩn 4 chữ số (0501, 0510).
    """
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        query = {"nam_thi": str(nam_thi)} if (nam_thi and nam_thi != "Tất cả") else {}
        all_docs = list(col.find(query))
        
        cleaned_count = 0
        for doc in all_docs:
            code = str(doc.get("ma_de", "")).strip()
            y = str(doc.get("nam_thi", "2025"))
            if code.isdigit() and len(code) == 3:
                four_code = f"0{code}"
                existing_4 = col.find_one({"ma_de": four_code, "nam_thi": y})
                if existing_4:
                    col.delete_one({"_id": doc["_id"]})
                    cleaned_count += 1
                else:
                    col.update_one({"_id": doc["_id"]}, {"$set": {"ma_de": four_code}})
                    cleaned_count += 1
                    
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"🧹 Đã dọn dẹp và chuẩn hóa {cleaned_count} mã đề trùng lặp về định dạng 4 chữ số chuẩn!"
    except Exception as e:
        return False, str(e)


def verify_all_answer_keys_in_year(mongo_uri, nam_thi):
    """
    Đánh dấu toàn bộ mã đề của năm thi này sang trạng thái 'da_xac_thuc' (🟢 ĐÃ DUYỆT / KHÓA BẢO VỆ).
    """
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        res = col.update_many(
            {"nam_thi": str(nam_thi)},
            {"$set": {
                "trang_thai": "da_xac_thuc",
                "thoi_gian_duyet": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }}
        )
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"🛡️ Đã phê duyệt và khóa bảo vệ toàn bộ {res.modified_count} mã đề (Năm {nam_thi})!"
    except Exception as e:
        return False, str(e)


def delete_all_answer_keys_in_year(mongo_uri, nam_thi):
    """
    Xóa toàn bộ mã đề của năm thi này khỏi collection 'answer_keys'.
    """
    if not mongo_uri:
        return False, "Chưa kết nối DB"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['answer_keys']
        res = col.delete_many({"nam_thi": str(nam_thi)})
        get_all_answer_keys_summary.clear()
        get_all_answer_keys_dataframe.clear()
        df_to_excel_bytes.clear()
        return True, f"Đã xóa {res.deleted_count} mã đề của năm {nam_thi} khỏi Ngân Hàng."
    except Exception as e:
        return False, str(e)


@st.cache_data(ttl=60, show_spinner=False)
def get_all_answer_keys_dataframe(mongo_uri, nam_thi=None):
    """
    Lấy toàn bộ đáp án của tất cả mã đề thành 1 DataFrame (có Cache trong 60s).
    """
    if not mongo_uri:
        return pd.DataFrame()
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return pd.DataFrame()
        col = db['answer_keys']
        query = {"nam_thi": str(nam_thi)} if (nam_thi and nam_thi != "Tất cả") else {}
        docs = list(col.find(query))
        rows = []
        for doc in docs:
            m = doc.get("ma_de")
            y = doc.get("nam_thi")
            for it in doc.get("danh_sach_dap_an", []):
                rows.append({
                    "Mã Đề": m,
                    "Năm Thi": y,
                    "Phần": it.get("Phần"),
                    "Câu": it.get("Câu"),
                    "Ý": it.get("Ý", ""),
                    "Đáp Án": it.get("Đáp Án")
                })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


# ==============================================================================
# COLLECTION 2: solved_exams (Cache Bài Giải AI)
# ==============================================================================

def get_solved_exam_cache(mongo_uri, ma_de, nam_thi, model_name):
    """
    Kiểm tra xem mã đề này đã được model AI giải trước đó chưa để tiết kiệm Token.
    """
    if not mongo_uri:
        return None
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return None
        col = db['solved_exams']
        doc = col.find_one({
            "ma_de": str(ma_de),
            "nam_thi": str(nam_thi),
            "model_ai": str(model_name)
        })
        if doc and "bai_lam_ai" in doc:
            return doc["bai_lam_ai"]
    except Exception:
        pass
    return None


def save_solved_exam_cache(mongo_uri, ma_de, nam_thi, model_name, ai_result, loai_tai_lieu="scan_image"):
    """
    Lưu bài giải của AI vào collection 'solved_exams' làm Cache.
    """
    if not mongo_uri or not ai_result:
        return
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return
        col = db['solved_exams']
        col.update_one(
            {"ma_de": str(ma_de), "nam_thi": str(nam_thi), "model_ai": str(model_name)},
            {"$set": {
                "ma_de": str(ma_de),
                "nam_thi": str(nam_thi),
                "model_ai": str(model_name),
                "loai_tai_lieu": loai_tai_lieu,
                "thoi_gian_giai": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "bai_lam_ai": ai_result
            }},
            upsert=True
        )
    except Exception:
        pass


def delete_solved_exam_cache(mongo_uri, ma_de=None, nam_thi=None):
    """
    Xóa bài giải trong collection 'solved_exams' để làm mới cache.
    """
    if not mongo_uri:
        return False, "Chưa cấu hình MONGODB_URI"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['solved_exams']
        query = {}
        if ma_de:
            query["ma_de"] = str(ma_de)
        if nam_thi:
            query["nam_thi"] = str(nam_thi)
        res = col.delete_many(query)
        return True, f"Đã làm mới Cache (đã xóa {res.deleted_count} bản ghi bài giải cũ)."
    except Exception as e:
        return False, str(e)


# ==============================================================================
# COLLECTION 3: grading_batches (Quản Lý Đợt Chấm Thi Hàng Loạt)
# ==============================================================================

def save_grading_batch(mongo_uri, batch_id, ten_dot_thi, nam_thi, model_name, summary_list):
    """
    Lưu thông tin đợt chấm thi hàng loạt vào collection 'grading_batches'.
    """
    if not mongo_uri or not summary_list:
        return False, "Không có dữ liệu đợt chấm"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        col = db['grading_batches']
        
        scores = []
        for item in summary_list:
            d = item.get("Điểm (Hệ 10)")
            if isinstance(d, (int, float)):
                scores.append(float(d))
                
        diem_tb = round(sum(scores) / len(scores), 2) if scores else None
        
        batch_doc = {
            "batch_id": str(batch_id),
            "ten_dot_thi": str(ten_dot_thi),
            "nam_thi": str(nam_thi),
            "model_ai": str(model_name),
            "tong_so_de": len(summary_list),
            "diem_trung_binh": diem_tb,
            "thoi_gian_cham": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "danh_sach_de": summary_list
        }
        col.insert_one(batch_doc)
        get_all_batches_from_db.clear()
        return True, "Đã lưu đợt chấm thi thành công"
    except Exception as e:
        return False, str(e)


@st.cache_data(ttl=120, show_spinner=False)
def get_all_batches_from_db(mongo_uri):
    """
    Lấy danh sách các đợt chấm thi đã lưu (có Cache trong RAM).
    """
    if not mongo_uri:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['grading_batches']
        docs = list(col.find().sort("timestamp", -1))
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []


def delete_batch_from_db(mongo_uri, batch_id):
    """
    Xóa một đợt chấm khỏi 'grading_batches' và 'exam_results'.
    """
    if not mongo_uri or not batch_id:
        return False, "Thiếu thông tin"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        db['grading_batches'].delete_one({"batch_id": str(batch_id)})
        db['exam_results'].delete_many({"batch_id": str(batch_id)})
        get_all_batches_from_db.clear()
        get_batch_exam_results.clear()
        return True, f"Đã xóa hoàn toàn đợt chấm {batch_id}"
    except Exception as e:
        return False, str(e)


# ==============================================================================
# COLLECTION 4: exam_results (Kết Quả Chi Tiết Từng Bài Thi)
# ==============================================================================

def save_to_mongodb(mongo_uri, data, ma_de, nam_thi, ten_file="", batch_id="", loai_tai_lieu="scan_image", score=None, correct_count=0, total_count=0, p1_correct=0, p1_total=24, p2_correct=0, p2_total=24, comparison_data=None, model_name=""):
    """
    Lưu kết quả chi tiết từng bài thi vào collection 'exam_results'.
    """
    if not mongo_uri:
        return False, "Chưa cấu hình MONGODB_URI"
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return False, "Không thể kết nối MongoDB"
        collection = db['exam_results']
        
        chi_tiet = []
        if comparison_data is not None:
            if isinstance(comparison_data, pd.DataFrame):
                chi_tiet = comparison_data.to_dict(orient='records')
            elif isinstance(comparison_data, list):
                chi_tiet = comparison_data

        record = {
            "batch_id": str(batch_id),
            "ma_de": str(ma_de),
            "ten_file": str(ten_file),
            "nam_thi": str(nam_thi),
            "model_ai": str(model_name),
            "loai_tai_lieu": str(loai_tai_lieu),
            "trang_thai_doi_sanh": "da_doi_sanh" if (score is not None and total_count > 0) else "chua_doi_sanh",
            "diem_so": round(float(score), 2) if score is not None else None,
            "so_cau_dung": int(correct_count) if score is not None else None,
            "tong_so_cau": int(total_count),
            "ty_le_dung_phan_tram": round((correct_count / total_count * 100), 2) if (score is not None and total_count > 0) else None,
            "thong_ke_phan_1": {
                "so_cau_dung": int(p1_correct) if score is not None else None,
                "tong_so_cau": int(p1_total)
            },
            "thong_ke_phan_2": {
                "so_y_dung": int(p2_correct) if score is not None else None,
                "tong_so_y": int(p2_total)
            },
            "thoi_gian_cham": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": time.time(),
            "bai_lam_ai": data,
            "chi_tiet_doi_sanh": chi_tiet
        }
        
        result = collection.insert_one(record)
        get_batch_exam_results.clear()
        return True, str(result.inserted_id)
    except Exception as e:
        err_msg = str(e)
        if "TLSV1_ALERT_INTERNAL_ERROR" in err_msg or "ServerSelectionTimeoutError" in err_msg:
            return False, "Lỗi kết nối Atlas: IP hiện tại chưa được Whitelist trong 'Network Access' của MongoDB Atlas."
        return False, err_msg


@st.cache_data(ttl=120, show_spinner=False)
def get_batch_exam_results(mongo_uri, batch_id):
    """
    Lấy danh sách kết quả chi tiết của tất cả bài thi trong một batch (có Cache trong RAM).
    """
    if not mongo_uri or not batch_id:
        return []
    try:
        db = get_mongo_db(mongo_uri)
        if db is None:
            return []
        col = db['exam_results']
        docs = list(col.find({"batch_id": str(batch_id)}))
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return docs
    except Exception:
        return []
