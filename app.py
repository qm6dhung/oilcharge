import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import datetime, date
import streamlit.components.v1 as components

# 嘗試引入 OCR 套件 (easyocr)
try:
    import easyocr
    @st.cache_resource
    def load_ocr_reader():
        return easyocr.Reader(['en'], gpu=False)
    has_ocr = True
except ImportError:
    has_ocr = False

st.set_page_config(page_title="汽車換油保養雲端紀錄", page_icon="🚗", layout="centered")

# ==========================================
# ⚡ 前端 JavaScript：強制手機鍵盤輸入自動轉大寫 (Caps Lock 效果)
# ==========================================
components.html("""
<script>
// 監聽網頁入面所有文字輸入框，自動將英文轉為大寫並套用 autocapitalize
const inputs = window.parent.document.querySelectorAll('input[type="text"]');
inputs.forEach(input => {
    input.setAttribute('autocapitalize', 'characters');
    input.addEventListener('input', function (e) {
        let start = this.selectionStart;
        let end = this.selectionEnd;
        this.value = this.value.toUpperCase();
        this.setSelectionRange(start, end);
    });
});
</script>
""", height=0)

# ==========================================
# 🔒 私人密碼鎖驗證 (讀取雲端 APP_PASSWORD)
# ==========================================
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 汽車換油保養雲端系統")
        with st.form("login_form"):
            pwd = st.text_input("請輸入私人密碼解鎖", type="password")
            submitted = st.form_submit_button("🔓 登入", use_container_width=True)
            if submitted:
                if pwd == st.secrets["APP_PASSWORD"]:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤，請重新輸入！")
        st.stop()

check_password()

# ==========================================
# ☁️ 連接 Supabase 雲端資料庫
# ==========================================
@st.cache_resource
def init_db():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_db()

# 頂部標題與「鎖定」按鈕
title_col, logout_col = st.columns([4, 1])
with title_col:
    st.title("🚗 汽車換油及保養紀錄")
with logout_col:
    st.write("")
    if st.button("🔒 鎖定", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

# 讀取雲端所有換油紀錄 (按日期由新到舊排列)
res_oil = supabase.table("oil_records").select("*").order("service_date", desc=True).execute()
oil_records = res_oil.data

# 整理已有嘅車牌清單
existing_plates = sorted(list(set(r["license_plate"] for r in oil_records if r.get("license_plate"))))

# ==========================================
# 🔍 搜索及篩選紀錄 (加入快速 OCR 搜索車牌)
# ==========================================
st.subheader("🔍 搜索及篩選紀錄")

search_ocr_plate = ""
with st.expander("📷 用鏡頭拍照 / 上傳相片來快速搜索車牌"):
    search_cam = st.file_uploader("上傳車牌相片以進行搜索", type=["jpg", "jpeg", "png"], key="search_cam_uploader")
    if search_cam is not None:
        st.image(search_cam, caption="用於搜索的相片", width=250)
        if st.button("🔍 辨識並套用車牌搜索"):
            if not has_ocr:
                st.warning("⚠️ 系統未安裝 easyocr。")
            else:
                with st.spinner("AI 正在辨識車牌中..."):
                    try:
                        reader = load_ocr_reader()
                        results = reader.readtext(search_cam.getvalue())
                        raw_text = "".join([res[1] for res in results]).upper().replace(" ", "")
                        search_ocr_plate = "".join([c for c in raw_text if c.isalnum()])
                        if search_ocr_plate:
                            st.success(f"✅ 成功辨識出車牌：**{search_ocr_plate}**")
                        else:
                            st.warning("⚠️ 辨識唔到車牌文字。")
                    except Exception as e:
                        st.error(f"❌ 錯誤: {e}")

s_col1, s_col2, s_col3 = st.columns([1.2, 1, 1.2])
with s_col1:
    default_search_val = search_ocr_plate if search_ocr_plate else ""
    search_input = st.text_input(
        "🚘 輸入車牌號碼 (自動大階)",
        value=default_search_val,
        placeholder="如: AB1234..."
    ).strip().upper().replace(" ", "")
with s_col2:
    quick_select = st.selectbox("或揀選車牌", ["全部車牌"] + existing_plates)
with s_col3:
    inv_search = st.text_input(
        "🧾 輸入 Invoice 單號 (自動大階)",
        placeholder="如: INV-2026..."
    ).strip().upper()

date_col1, date_col2 = st.columns([1, 2])
with date_col1:
    date_mode = st.selectbox("📅 日期篩選模式", ["不限日期", "指定單一日期", "日期範圍 (由...至...)"])
with date_col2:
    if date_mode == "指定單一日期":
        target_date = st.date_input("選擇保養日期", date.today())
    elif date_mode == "日期範圍 (由...至...)":
        first_day_of_month = date.today().replace(day=1)
        date_range = st.date_input("選擇開始及結束日期", value=(first_day_of_month, date.today()))
    else:
        st.text_input("目前顯示", value="所有日期嘅保養紀錄", disabled=True)

# 篩選邏輯
filtered_records = oil_records
if search_input:
    filtered_records = [r for r in filtered_records if search_input in (r.get("license_plate"] or "").upper()]
elif quick_select != "全部車牌":
    filtered_records = [r for r in filtered_records if r.get("license_plate"] == quick_select]

if inv_search:
    filtered_records = [r for r in filtered_records if inv_search in (r.get("invoice_no"] or "").upper()]

if date_mode == "指定單一日期":
    target_date_str = str(target_date)
    filtered_records = [r for r in filtered_records if r.get("service_date"] == target_date_str]
elif date_mode == "日期範圍 (由...至...)":
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_str, end_str = str(date_range[0]), str(date_range[1])
        filtered_records = [r for r in filtered_records if start_str <= r.get("service_date", "") <= end_str]

if (search_input or quick_select != "全部車牌") and filtered_records:
    latest = filtered_records[0]
    target_plate = latest["license_plate"]
    plate_count = len([r for r in filtered_records if r["license_plate"] == target_plate])
    st.info(
        f"🚘 **車牌：`{target_plate}`** （符合篩選共 `{plate_count}` 次紀錄）\n\n"
        f"📌 **最近一次保養**：{latest['service_date']} ｜ 單號：`{latest['invoice_no']}` ｜ 當時里數：`{latest['current_km']:,} km`\n\n"
        f"🔔 **下次換油目標**：**`{latest['next_km']:,} km`**"
    )

# ==========================================
# 1. 新增換油 / 保養紀錄 (支援 OCR 拍照辨識)
# ==========================================
with st.expander("➕ 新增換油 / 保養紀錄 (支援鏡頭拍照辨識或鍵盤輸入)", expanded=not bool(oil_records)):
    
    st.markdown("### 📷 車牌智能辨識 (新增用)")
    ocr_mode = st.radio("選擇輸入車牌方式", ["⌨️ 傳統鍵盤輸入", "📸 拍照 / 上傳車牌相片 OCR 辨識"], horizontal=True, key="add_ocr_radio")
    
    detected_plate = ""
    if ocr_mode == "📸 拍照 / 上傳車牌相片 OCR 辨識":
        if not has_ocr:
            st.warning("⚠️ 系統尚未安裝 `easyocr` 套件。")
        else:
            cam_file = st.file_uploader("上傳車牌相片或即時拍照", type=["jpg", "jpeg", "png"], key="add_cam_uploader")
            if cam_file is not None:
                st.image(cam_file, caption="已上傳的車牌相片", width=250)
                if st.button("🔍 開始辨識車牌文字", key="btn_add_ocr"):
                    with st.spinner("AI 正在辨識車牌中..."):
                        try:
                            reader = load_ocr_reader()
                            results = reader.readtext(cam_file.getvalue())
                            raw_text = "".join([res[1] for res in results]).upper().replace(" ", "")
                            detected_plate = "".join([c for c in raw_text if c.isalnum()])
                            if detected_plate:
                                st.success(f"✅ 成功辨識車牌：**{detected_plate}**")
                            else:
                                st.warning("⚠️ 辨識唔到車牌文字。")
                        except Exception as e:
                            st.error(f"❌ 失敗: {e}")

    with st.form("add_oil_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            default_plate = detected_plate if detected_plate else (search_input if search_input else (quick_select if quick_select != "全部車牌" else ""))
            plate_raw = st.text_input("車牌號碼 * (自動大階)", value=default_plate, placeholder="如: AB1234")
            inv_raw = st.text_input("Invoice 單據編號 * (自動大階)", placeholder="如: INV-20261023-01")
            s_date = st.date_input("保養日期 *", datetime.today())
            c_km = st.number_input("目前里數 (km) *", min_value=0, step=500)
        with col2:
            interval = st.selectbox("下次換油間距 (km)", [5000, 7500, 8000, 10000], index=0)
            oil_spec = st.text_input("機油牌子及黏度", placeholder="如: 5W-30 全合成 (4.3L)")
            cost = st.number_input("費用 ($ HKD)", min_value=0, step=50)
            o_filter = st.checkbox("已更換機油隔 (Oil Filter)", value=True)

        notes = st.text_area("其他順便保養項目")

        if st.form_submit_button("💾 儲存保養紀錄", use_container_width=True):
            clean_plate = plate_raw.strip().upper().replace(" ", "")
            clean_inv = inv_raw.strip().upper()
            date_str = str(s_date)

            if not clean_plate or not clean_inv:
                st.error("⚠️ 請必須填寫「車牌號碼」同埋「Invoice 單據編號」！")
            elif any(r["invoice_no"].upper() == clean_inv for r in oil_records):
                st.error(f"❌ 儲存失敗：Invoice 單號 `{clean_inv}` 已經存在！")
            elif any(r["license_plate"].upper() == clean_plate and r["service_date"] == date_str for r in oil_records):
                st.error(f"❌ 儲存失敗：車牌 `{clean_plate}` 喺 `{date_str}` 已經有一筆紀錄！")
            else:
                data = {
                    "license_plate": clean_plate,
                    "invoice_no": clean_inv,
                    "service_date": date_str,
                    "current_km": c_km,
                    "next_km": c_km + interval,
                    "oil_spec": oil_spec,
                    "oil_filter": o_filter,
                    "cost": cost,
                    "notes": notes
                }
                supabase.table("oil_records").insert(data).execute()
                st.success(f"✅ 已成功儲存車牌 `{clean_plate}` 嘅紀錄！")
                st.rerun()

# ==========================================
# 2. 顯示歷史保養紀錄 ＋ 總費用統計 ＋ 匯出 CSV 備份
# ==========================================
st.subheader("📋 保養紀錄列表及統計")
if filtered_records:
    total_cost = sum(int(r.get("cost") or 0) for r in filtered_records)
    record_count = len(filtered_records)
    avg_cost = int(total_cost / record_count) if record_count > 0 else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("📋 符合紀錄單數", f"{record_count} 筆")
    m2.metric("💰 篩選結果總費用", f"$ {total_cost:,} HKD")
    m3.metric("📊 平均每單費用", f"$ {avg_cost:,} HKD")

    df_oil = pd.DataFrame(filtered_records)
    df_oil["oil_filter_display"] = df_oil["oil_filter"].apply(lambda x: "✅" if x else "❌")
    
    display_oil = df_oil[["id", "license_plate", "invoice_no", "service_date", "current_km", "next_km", "oil_spec", "oil_filter_display", "cost", "notes"]]
    display_oil.columns = ["ID", "車牌", "Invoice 單號", "日期", "當時里數", "下次里數", "機油規格", "油隔", "費用($)", "備註"]
    st.dataframe(display_oil, use_container_width=True, hide_index=True)

    csv_data = display_oil.to_csv(index=False).encode("utf-8-sig")
    plate_tag = search_input or (quick_select if quick_select != "全部車牌" else "ALL")
    inv_tag = f"_{inv_search}" if inv_search else ""
    file_tag = f"{plate_tag}{inv_tag}"
    st.download_button(
        label=f"📥 匯出目前篩選列表 ({file_tag}) 為 CSV 備份 (Excel 適用)",
        data=csv_data,
        file_name=f"oil_records_{file_tag}_{datetime.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )
else:
    st.write("暫時未有符合條件嘅換油紀錄。")
