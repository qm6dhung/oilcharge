import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import datetime, date

st.set_page_config(page_title="汽車換油保養雲端紀錄", page_icon="🚗", layout="centered")

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
# 🔍 車牌、Invoice 單號及日期搜索區域
# ==========================================
st.subheader("🔍 搜索及篩選紀錄")

# 第一行：車牌搜索 ＋ 下拉快選 ＋ Invoice 單號搜索
s_col1, s_col2, s_col3 = st.columns([1.2, 1, 1.2])
with s_col1:
    search_input = st.text_input(
        "🚘 輸入車牌號碼",
        placeholder="如: AB1234..."
    ).strip().upper().replace(" ", "")
with s_col2:
    quick_select = st.selectbox("或揀選車牌", ["全部車牌"] + existing_plates)
with s_col3:
    inv_search = st.text_input(
        "🧾 輸入 Invoice 單號",
        placeholder="如: INV-2026..."
    ).strip().upper()

# 第二行：日期搜索
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

# 1. 根據車牌過濾紀錄
filtered_records = oil_records
if search_input:
    filtered_records = [r for r in filtered_records if search_input in (r.get("license_plate") or "").upper()]
elif quick_select != "全部車牌":
    filtered_records = [r for r in filtered_records if r.get("license_plate") == quick_select]

# 2. 根據 Invoice 單號關鍵字過濾紀錄
if inv_search:
    filtered_records = [r for r in filtered_records if inv_search in (r.get("invoice_no") or "").upper()]

# 3. 根據日期過濾紀錄
date_tag = ""
if date_mode == "指定單一日期":
    target_date_str = str(target_date)
    filtered_records = [r for r in filtered_records if r.get("service_date") == target_date_str]
    date_tag = f"_{target_date_str}"
elif date_mode == "日期範圍 (由...至...)":
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_str, end_str = str(date_range[0]), str(date_range[1])
        filtered_records = [r for r in filtered_records if start_str <= r.get("service_date", "") <= end_str]
        date_tag = f"_{start_str}_to_{end_str}"
    else:
        st.caption("⚠️ 請喺日曆點選埋「結束日期」以完成範圍篩選。")

# 當鎖定某個車牌時，置頂顯示該車嘅最新換油狀態及總保養次數
if (search_input or quick_select != "全部車牌") and filtered_records:
    latest = filtered_records[0]
    target_plate = latest["license_plate"]
    plate_count = len([r for r in filtered_records if r["license_plate"] == target_plate])
    st.info(
        f"🚘 **車牌：`{target_plate}`** （符合篩選共 `{plate_count}` 次紀錄）\n\n"
        f"📌 **最近一次保養**：{latest['service_date']} ｜ 單號：`{latest['invoice_no']}` ｜ 當時里數：`{latest['current_km']:,} km`\n\n"
        f"🔔 **下次換油目標**：**`{latest['next_km']:,} km`**"
    )
elif (search_input or inv_search or date_mode != "不限日期") and not filtered_records:
    st.warning("⚠️ 搵唔到符合目前「車牌 / 單號 / 日期」條件嘅保養紀錄。")

# ==========================================
# 1. 新增換油 / 保養紀錄 (含防撞單號及防同日重複檢查)
# ==========================================
with st.expander("➕ 新增換油 / 保養紀錄", expanded=not bool(oil_records)):
    with st.form("add_oil_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            default_plate = search_input if search_input else (quick_select if quick_select != "全部車牌" else "")
            plate_raw = st.text_input("車牌號碼 *", value=default_plate, placeholder="如: AB1234")
            inv_raw = st.text_input("Invoice 單據編號 *", placeholder="如: INV-20261023-01")
            s_date = st.date_input("保養日期 *", datetime.today())
            c_km = st.number_input("目前里數 (km) *", min_value=0, step=500)
        with col2:
            interval = st.selectbox("下次換油間距 (km)", [5000, 7500, 8000, 10000], index=0)
            oil_spec = st.text_input("機油牌子及黏度", placeholder="如: 5W-30 全合成 (4.3L)")
            cost = st.number_input("費用 ($ HKD)", min_value=0, step=50)
            o_filter = st.checkbox("已更換機油隔 (Oil Filter)", value=True)

        notes = st.text_area("其他順便保養項目 (如：洗蝴蝶掩、換火咀、波箱油、冷氣隔)")

        if st.form_submit_button("💾 儲存保養紀錄", use_container_width=True):
            clean_plate = plate_raw.strip().upper().replace(" ", "")
            clean_inv = inv_raw.strip().upper()
            date_str = str(s_date)

            # 檢查必填欄位及重複規則
            if not clean_plate or not clean_inv:
                st.error("⚠️ 請必須填寫「車牌號碼」同埋「Invoice 單據編號」！")
            elif any(r["invoice_no"].upper() == clean_inv for r in oil_records):
                st.error(f"❌ 儲存失敗：Invoice 單號 `{clean_inv}` 已經存在，單號唔可以重複！")
            elif any(r["license_plate"].upper() == clean_plate and r["service_date"] == date_str for r in oil_records):
                st.error(f"❌ 儲存失敗：車牌 `{clean_plate}` 喺 `{date_str}` 已經有一筆保養紀錄，同車同日唔可以重複！")
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
                st.success(f"✅ 已成功儲存車牌 `{clean_plate}` (單號: `{clean_inv}`) 嘅保養紀錄！")
                st.rerun()

# ==========================================
# 2. 顯示歷史保養紀錄 ＋ 總費用統計 ＋ 匯出 CSV 備份
# ==========================================
st.subheader("📋 保養紀錄列表及統計")
if filtered_records:
    # 💰 自動計算目前篩選結果嘅總費用及平均消費
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

    # 📥 匯出 CSV 備份按鈕 (連同車牌、單號與日期範圍自動命名檔案)
    csv_data = display_oil.to_csv(index=False).encode("utf-8-sig")
    plate_tag = search_input or (quick_select if quick_select != "全部車牌" else "ALL")
    inv_tag = f"_{inv_search}" if inv_search else ""
    file_tag = f"{plate_tag}{inv_tag}{date_tag}"
    st.download_button(
        label=f"📥 匯出目前篩選列表 ({file_tag}) 為 CSV 備份 (Excel 適用)",
        data=csv_data,
        file_name=f"oil_records_{file_tag}_{datetime.today().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )

    # ==========================================
    # 3. 修改或刪除過往保養紀錄 (同樣支援防撞檢查)
    # ==========================================
    with st.expander("✏️ 修改或刪除過往保養紀錄"):
        record_options = {
            r["id"]: f"[{r['license_plate']}] {r['service_date']} | 單號: {r['invoice_no']} ($ {int(r.get('cost') or 0):,})"
            for r in filtered_records
        }
        selected_id = st.selectbox(
            "選擇要處理嘅紀錄",
            options=list(record_options.keys()),
            format_func=lambda x: record_options[x]
        )
        target_rec = next(r for r in filtered_records if r["id"] == selected_id)

        with st.form("edit_oil_form"):
            e_col1, e_col2 = st.columns(2)
            with e_col1:
                edit_plate = st.text_input("車牌號碼 *", value=target_rec["license_plate"])
                edit_inv = st.text_input("Invoice 單據編號 *", value=target_rec["invoice_no"])
                edit_date = st.date_input("保養日期 *", datetime.strptime(target_rec["service_date"], "%Y-%m-%d"))
                edit_ckm = st.number_input("當時里數 (km)", min_value=0, value=int(target_rec["current_km"]), step=500)
            with e_col2:
                edit_nkm = st.number_input("下次換油里數 (km)", min_value=0, value=int(target_rec["next_km"]), step=500)
                edit_spec = st.text_input("機油牌子及黏度", value=target_rec["oil_spec"] or "")
                edit_cost = st.number_input("費用 ($ HKD)", min_value=0, value=int(target_rec["cost"] or 0), step=50)
                edit_filter = st.checkbox("已更換機油隔", value=bool(target_rec["oil_filter"]))

            edit_notes = st.text_area("備註", value=target_rec["notes"] or "")

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                update_btn = st.form_submit_button("💾 儲存修改", use_container_width=True)
            with btn_col2:
                delete_btn = st.form_submit_button("🗑️ 刪除此紀錄", type="primary", use_container_width=True)

            if update_btn:
                c_plate = edit_plate.strip().upper().replace(" ", "")
                c_inv = edit_inv.strip().upper()
                c_date = str(edit_date)

                other_records = [r for r in oil_records if r["id"] != selected_id]
                if not c_plate or not c_inv:
                    st.error("⚠️ 車牌號碼同埋 Invoice 單據編號唔可以留空！")
                elif any(r["invoice_no"].upper() == c_inv for r in other_records):
                    st.error(f"❌ 修改失敗：Invoice 單號 `{c_inv}` 已經被其他紀錄使用！")
                elif any(r["license_plate"].upper() == c_plate and r["service_date"] == c_date for r in other_records):
                    st.error(f"❌ 修改失敗：車牌 `{c_plate}` 喺 `{c_date}` 已經有另一筆紀錄！")
                else:
                    updated_data = {
                        "license_plate": c_plate,
                        "invoice_no": c_inv,
                        "service_date": c_date,
                        "current_km": edit_ckm,
                        "next_km": edit_nkm,
                        "oil_spec": edit_spec,
                        "oil_filter": edit_filter,
                        "cost": edit_cost,
                        "notes": edit_notes
                    }
                    supabase.table("oil_records").update(updated_data).eq("id", selected_id).execute()
                    st.success(f"✅ 已成功更新單號 `{c_inv}` 嘅紀錄！")
                    st.rerun()

            if delete_btn:
                supabase.table("oil_records").delete().eq("id", selected_id).execute()
                st.warning(f"🗑️ 已刪除單號 `{target_rec['invoice_no']}` 嘅紀錄！")
                st.rerun()
else:
    st.write("暫時未有符合條件嘅換油紀錄。")
