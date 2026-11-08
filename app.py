import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import datetime, date
import streamlit.components.v1 as components
import re

st.set_page_config(page_title="汽車換油保養雲端紀錄", page_icon="🚗", layout="centered")

# ==========================================
# 🎨 CSS：
# 1. 隱藏「Press Enter to apply」提示字
# 2. 強制所有文字輸入框及備註欄視覺上即時顯示為大階 (除密碼框外)
# ==========================================
st.markdown("""
<style>
div[data-testid="InputInstructions"] > span,
div[data-testid="InputInstructions"] {
    display: none !important;
}
input[type="text"], textarea {
    text-transform: uppercase !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔒 私人密碼鎖驗證 (讀取雲端 APP_PASSWORD)
# ==========================================
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 汽車換油保養雲端系統")
        pwd = st.text_input("請輸入私人密碼解鎖", type="password")
        if st.button("🔓 登入", type="primary", use_container_width=True):
            if pwd == st.secrets.get("APP_PASSWORD", ""):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ 密碼錯誤，請重新輸入！")
        st.stop()

check_password()

# ==========================================
# ⚡ 前端 JavaScript：
# 1. 強制所有 input[type="text"] 及 textarea 數值轉為大階並同步去 React 底層
# 2. 支援直接揀下一個選項或撳 Enter 自動跳格，無須額外確認
# ==========================================
components.html("""
<script>
function setNativeValue(element, value) {
    const prototype = Object.getPrototypeOf(element);
    const valueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
    if (valueSetter) {
        valueSetter.call(element, value);
    } else {
        element.value = value;
    }
}

function enhanceInputs() {
    const doc = window.parent.document;
    const textElements = doc.querySelectorAll('input[type="text"], textarea');
    
    textElements.forEach((el) => {
        if (!el.dataset.enhanced) {
            el.setAttribute('autocapitalize', 'characters');
            if (el.tagName === 'INPUT') {
                el.setAttribute('enterkeyhint', 'next');
            }
            
            el.addEventListener('input', function () {
                const start = this.selectionStart;
                const end = this.selectionEnd;
                const upperVal = this.value.toUpperCase();
                if (this.value !== upperVal) {
                    setNativeValue(this, upperVal);
                    this.dispatchEvent(new Event('input', { bubbles: true }));
                    this.setSelectionRange(start, end);
                }
            });

            el.addEventListener('blur', function () {
                const upperVal = this.value.toUpperCase();
                if (this.value !== upperVal) {
                    setNativeValue(this, upperVal);
                    this.dispatchEvent(new Event('input', { bubbles: true }));
                }
                this.dispatchEvent(new Event('change', { bubbles: true }));
            });

            if (el.tagName === 'INPUT') {
                el.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        const allInputs = Array.from(doc.querySelectorAll('input:not([disabled]):not([type="hidden"]), textarea:not([disabled])'));
                        const currentIndex = allInputs.indexOf(this);
                        if (currentIndex > -1 && currentIndex + 1 < allInputs.length) {
                            allInputs[currentIndex + 1].focus();
                        } else {
                            this.blur();
                        }
                    }
                });
            }

            el.dataset.enhanced = "true";
        }
    });
}
enhanceInputs();
const observer = new MutationObserver(enhanceInputs);
observer.observe(window.parent.document.body, { childList: true, subtree: true });
</script>
""", height=0)

# ==========================================
# 🛠️ 保養項目清單定義與打包/拆解輔助函數 (無須改動 Supabase 資料表結構)
# ==========================================
SERVICE_ITEMS = [
    ("oil", "偈油", "🛢️ 偈油 (Engine Oil)", "如: 5W-30 (4L)", True, 50),
    ("oil_lb", "換偈油人工", "👨‍🔧 換偈油人工", "如: 標準換油工時", True, 50),
    ("atf", "自動波箱油", "⚙️ 自動波箱油 (ATF/CVTF)", "如: TOYOTA WS (4L)", False, 50),
    ("mtf", "波箱油", "🕹️ 波箱油 (MTF)", "如: 75W-90 (2L)", False, 50),
    ("diff", "尾牙油", "🔩 尾牙油 (Diff Oil)", "如: 80W-90", False, 50),
    ("flush", "清洗偈油", "🧪 清洗偈油 (Engine Flush)", "如: LIQUI MOLY エンジン洗浄", False, 20),
    ("wash", "洗車/唧油", "🚿 洗車 / 唧油", "如: 洗車 / 底盤唧雪油", False, 20),
    ("of", "油隔", "🔧 油隔 (Oil Filter)", "如: 90915-YZZE1", True, 20),
    ("ff", "油渣/電油格", "⛽ 油渣格 / 電油格 (Fuel Filter)", "如: 23390-0L070", False, 20),
    ("af", "風隔", "🌬️ 風隔 (Air Filter)", "如: 17801-28030", False, 20),
    ("cf", "冷氣隔", "❄️ 冷氣隔 (Cabin Filter)", "如: 87139-0N010", False, 20),
    ("lb", "其他人工", "🛠️ 其他人工 (Labor)", "如: 檢查工時", False, 50),
]

def _clean_model_str(m_str):
    return re.sub(r"[()（）｜【】]", "-", (m_str or "").strip().upper())

def pack_items_dict_to_notes(items_state, user_notes):
    tags = []
    for key, tag_label, _, _, _, _ in SERVICE_ITEMS:
        chk = items_state.get(f"{key}_chk", False)
        mod = items_state.get(f"{key}_m", "")
        prc = items_state.get(f"{key}_p", 0)
        if chk:
            cm = _clean_model_str(mod)
            if cm:
                tags.append(f"{tag_label}({cm}):${int(prc)}")
            else:
                tags.append(f"{tag_label}:${int(prc)}")
    prefix = f"【{'｜'.join(tags)}】" if tags else ""
    clean_u = (user_notes or "").strip().upper()
    return f"{prefix} {clean_u}".strip() if clean_u else prefix

def parse_items_from_record(rec):
    raw_notes = rec.get("notes") or ""
    total_cost = int(rec.get("cost") or 0)
    of_bool = bool(rec.get("oil_filter", True))
    raw_oil_spec = (rec.get("oil_spec") or "").upper()
    
    # 初始化預設狀態 (相容最早期舊紀錄)
    res = {"clean_notes": raw_notes}
    for key, _, _, _, _, _ in SERVICE_ITEMS:
        res[f"{key}_chk"] = False
        res[f"{key}_m"] = ""
        res[f"{key}_p"] = 0
        
    res["oil_chk"] = True
    res["oil_m"] = raw_oil_spec
    res["oil_p"] = total_cost
    res["of_chk"] = of_bool

    match = re.match(r"^【(.*?)】\s*(.*)$", raw_notes, re.DOTALL)
    if match:
        tag_str, rem_notes = match.group(1), match.group(2)
        res["clean_notes"] = rem_notes
        # 先清空預設，按標籤實際內容還原
        for key, _, _, _, _, _ in SERVICE_ITEMS:
            res[f"{key}_chk"] = False
            res[f"{key}_m"] = ""
            res[f"{key}_p"] = 0

        # 支援新版及舊版標籤名稱對應
        label_aliases = {
            "oil": ["偈油", "換機油"],
            "oil_lb": ["換偈油人工"],
            "atf": ["自動波箱油"],
            "mtf": ["波箱油"],
            "diff": ["尾牙油"],
            "flush": ["清洗偈油"],
            "wash": ["洗車/唧油", "洗車/潔油", "洗車", "唧油", "潔油"],
            "of": ["油隔", "機油隔"],
            "ff": ["油渣/電油格", "油渣格", "電油格", "汽油格"],
            "af": ["風隔", "風格"],
            "cf": ["冷氣隔", "冷氣格"],
            "lb": ["其他人工", "人工"],
        }

        segments = [s.strip() for s in tag_str.split("｜") if s.strip()]
        for seg in segments:
            m = re.match(r"^([^(:]+)(?:\((.*?)\))?:\$(\d+)$", seg)
            if m:
                seg_label = m.group(1).strip()
                seg_mod = (m.group(2) or "").strip().upper()
                seg_prc = int(m.group(3))
                for key, aliases in label_aliases.items():
                    if seg_label in aliases:
                        res[f"{key}_chk"] = True
                        if key == "oil" and not seg_mod:
                            seg_mod = raw_oil_spec
                        res[f"{key}_m"] = seg_mod
                        res[f"{key}_p"] = seg_prc
                        break
    return res

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
        st.session_state.edit_unlocked = False
        st.rerun()

# 讀取雲端所有換油紀錄 (按日期由新到舊排列)
res_oil = supabase.table("oil_records").select("*").order("service_date", desc=True).execute()
oil_records = res_oil.data or []

# 整理已有嘅車牌清單
existing_plates = sorted(list(set(r["license_plate"] for r in oil_records if r.get("license_plate"))))

# ==========================================
# 🔘 頂部三按鈕切換模式 (搜尋 vs 新增 vs 修改/刪除)
# ==========================================
if "active_view" not in st.session_state:
    st.session_state.active_view = "search"
if "edit_unlocked" not in st.session_state:
    st.session_state.edit_unlocked = False
if "add_form_key" not in st.session_state:
    st.session_state.add_form_key = 0

btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    if st.button(
        "🔍 搜索紀錄",
        type="primary" if st.session_state.active_view == "search" else "secondary",
        use_container_width=True
    ):
        st.session_state.active_view = "search"
        st.session_state.edit_unlocked = False
        st.rerun()

with btn_col2:
    if st.button(
        "➕ 新增紀錄",
        type="primary" if st.session_state.active_view == "add" else "secondary",
        use_container_width=True
    ):
        st.session_state.active_view = "add"
        st.session_state.edit_unlocked = False
        st.rerun()

with btn_col3:
    if st.button(
        "✏️ 修改 / 刪除",
        type="primary" if st.session_state.active_view == "edit" else "secondary",
        use_container_width=True
    ):
        st.session_state.active_view = "edit"
        st.rerun()

st.divider()

# ==========================================
# 畫面 A：🔍 搜索及篩選紀錄 ＋ 列表統計
# ==========================================
if st.session_state.active_view == "search":
    st.subheader("🔍 搜索及篩選紀錄")

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
        filtered_records = [r for r in filtered_records if search_input in (r.get("license_plate") or "").upper()]
    elif quick_select != "全部車牌":
        filtered_records = [r for r in filtered_records if r.get("license_plate") == quick_select]

    if inv_search:
        filtered_records = [r for r in filtered_records if inv_search in (r.get("invoice_no") or "").upper()]

    if date_mode == "指定單一日期":
        target_date_str = str(target_date)
        filtered_records = [r for r in filtered_records if r.get("service_date") == target_date_str]
    elif date_mode == "日期範圍 (由...至...)":
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_str, end_str = str(date_range[0]), str(date_range[1])
            filtered_records = [r for r in filtered_records if start_str <= (r.get("service_date") or "") <= end_str]

    if (search_input or quick_select != "全部車牌") and filtered_records:
        latest = filtered_records[0]
        target_plate = latest.get("license_plate", "")
        plate_count = len([r for r in filtered_records if r.get("license_plate") == target_plate])
        st.info(
            f"🚘 **車牌：`{target_plate}`** （符合篩選共 `{plate_count}` 次紀錄）\n\n"
            f"📌 **最近一次保養**：{latest.get('service_date', '')} ｜ 單號：`{latest.get('invoice_no', '')}` ｜ 當時里數：`{int(latest.get('current_km') or 0):,} km`\n\n"
            f"🔔 **下次換油目標**：**`{int(latest.get('next_km') or 0):,} km`**\n\n"
            f"🛠️ **上次保養明細**：{latest.get('notes', '無')}"
        )

    # 顯示歷史保養紀錄 ＋ 總費用統計 ＋ 匯出 CSV 備份
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
        display_oil.columns = ["ID", "車牌", "Invoice 單號", "日期", "當時里數", "下次里數", "偈油型號", "油隔", "總費用($)", "保養項目型號及收費明細"]
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

# ==========================================
# 畫面 B：➕ 新增換油 / 保養紀錄 (含 12 項勾選 ＋ 型號 ＋ 價錢)
# ==========================================
elif st.session_state.active_view == "add":
    st.subheader("➕ 新增換油 / 保養紀錄")
    fk = st.session_state.add_form_key

    col1, col2 = st.columns(2)
    with col1:
        plate_raw = st.text_input("車牌號碼 *", placeholder="如: AB1234", key=f"add_plate_{fk}")
        inv_raw = st.text_input("Invoice 單據編號 *", placeholder="如: INV-20261023-01", key=f"add_inv_{fk}")
        s_date = st.date_input("保養日期 *", datetime.today(), key=f"add_date_{fk}")
    with col2:
        c_km = st.number_input("目前里數 (km) *", min_value=0, step=500, key=f"add_ckm_{fk}")
        interval = st.selectbox("下次換油間距 (km)", [5000, 7500, 8000, 10000], index=0, key=f"add_int_{fk}")

    st.markdown("#### 🛠️ 保養項目、型號及收費明細")

    add_items_state = {}
    calc_total = 0

    for key, tag_label, ui_label, ph, def_chk, step_val in SERVICE_ITEMS:
        ic, im, ip = st.columns([1.3, 1.5, 1.2])
        with ic:
            st.write("")
            chk = st.checkbox(ui_label, value=def_chk, key=f"add_chk_{key}_{fk}")
        with im:
            mod = st.text_input(f"{tag_label}型號 / 規格", placeholder=ph, disabled=not chk, key=f"add_m_{key}_{fk}")
        with ip:
            prc = st.number_input(f"{tag_label}價錢 ($)", min_value=0, step=step_val, disabled=not chk, key=f"add_p_{key}_{fk}")
        
        add_items_state[f"{key}_chk"] = chk
        add_items_state[f"{key}_m"] = mod
        add_items_state[f"{key}_p"] = prc if chk else 0
        if chk:
            calc_total += prc

    st.info(f"💰 **本單自動計算總費用：`$ {calc_total:,} HKD`**")

    notes = st.text_area("其他順便保養項目或備註 (如：洗蝴蝶掩、換火咀、迫力皮)", key=f"add_notes_{fk}")

    if st.button("💾 儲存保養紀錄", type="primary", use_container_width=True):
        clean_plate = plate_raw.strip().upper().replace(" ", "")
        clean_inv = inv_raw.strip().upper()
        clean_spec = add_items_state["oil_m"].strip().upper() if add_items_state["oil_chk"] else ""
        date_str = str(s_date)

        if not clean_plate or not clean_inv:
            st.error("⚠️ 請必須填寫「車牌號碼」同埋「Invoice 單據編號」！")
        elif any((r.get("invoice_no") or "").upper() == clean_inv for r in oil_records):
            st.error(f"❌ 儲存失敗：Invoice 單號 `{clean_inv}` 已經存在，單號唔可以重複！")
        elif any((r.get("license_plate") or "").upper() == clean_plate and r.get("service_date") == date_str for r in oil_records):
            st.error(f"❌ 儲存失敗：車牌 `{clean_plate}` 喺 `{date_str}` 已經有一筆紀錄，同車同日唔可以重複！")
        else:
            packed_notes = pack_items_dict_to_notes(add_items_state, notes)
            data = {
                "license_plate": clean_plate,
                "invoice_no": clean_inv,
                "service_date": date_str,
                "current_km": c_km,
                "next_km": c_km + interval,
                "oil_spec": clean_spec,
                "oil_filter": add_items_state["of_chk"],
                "cost": calc_total,
                "notes": packed_notes
            }
            supabase.table("oil_records").insert(data).execute()
            st.session_state.add_form_key += 1  # 自動清空所有欄位方便入下一張單
            st.success(f"✅ 已成功儲存車牌 `{clean_plate}` (單號: `{clean_inv}`，總額: `${calc_total:,}`) 嘅保養紀錄！")
            st.rerun()

# ==========================================
# 畫面 C：✏️ 修改 / 🗑️ 刪除過往保養紀錄 (雙重密碼保護：95251034)
# ==========================================
elif st.session_state.active_view == "edit":
    st.subheader("✏️ 修改或刪除過往保養紀錄")

    EDIT_PASSWORD = st.secrets.get("EDIT_PASSWORD", "95251034")

    if not st.session_state.edit_unlocked:
        st.info("🔐 此區域受管理員密碼保護，請輸入修改專用密碼以繼續。")
        edit_pwd = st.text_input("請輸入修改 / 刪除專用密碼", type="password")
        if st.button("🔓 解鎖修改權限", type="primary", use_container_width=True):
            if edit_pwd == EDIT_PASSWORD:
                st.session_state.edit_unlocked = True
                st.rerun()
            else:
                st.error("❌ 專用密碼錯誤，無法進入修改模式！")
    else:
        lock_col1, lock_col2 = st.columns([3, 1])
        with lock_col1:
            st.success("🔓 已解鎖修改及刪除權限")
        with lock_col2:
            if st.button("🔒 重新上鎖", use_container_width=True):
                st.session_state.edit_unlocked = False
                st.rerun()

        if not oil_records:
            st.write("暫時未有任何保養紀錄可供修改。")
        else:
            f_col1, f_col2 = st.columns(2)
            with f_col1:
                edit_filter_plate = st.text_input("🚘 篩選車牌", placeholder="輸入車牌快速尋找...").strip().upper().replace(" ", "")
            with f_col2:
                edit_filter_inv = st.text_input("🧾 篩選單號", placeholder="輸入單號快速尋找...").strip().upper()

            edit_candidates = oil_records
            if edit_filter_plate:
                edit_candidates = [r for r in edit_candidates if edit_filter_plate in (r.get("license_plate") or "").upper()]
            if edit_filter_inv:
                edit_candidates = [r for r in edit_candidates if edit_filter_inv in (r.get("invoice_no") or "").upper()]

            if not edit_candidates:
                st.warning("⚠️ 搵唔到符合篩選條件嘅紀錄。")
            else:
                record_options = {
                    f"ID:{r['id']} ｜ 🚘 {r.get('license_plate', '')} ｜ 📅 {r.get('service_date', '')} ｜ 🧾 {r.get('invoice_no', '')} ($ {r.get('cost', 0)})": r
                    for r in edit_candidates
                }
                selected_label = st.selectbox("📌 請揀選要修改或刪除嘅保養紀錄", list(record_options.keys()))
                selected_rec = record_options[selected_label]
                rec_id = selected_rec["id"]

                try:
                    orig_date = datetime.strptime(selected_rec.get("service_date", ""), "%Y-%m-%d").date()
                except Exception:
                    orig_date = date.today()

                parsed = parse_items_from_record(selected_rec)

                st.markdown(f"**正在編輯紀錄 ID：`{rec_id}`**")
                e_col1, e_col2 = st.columns(2)
                with e_col1:
                    new_plate = st.text_input("車牌號碼 *", value=(selected_rec.get("license_plate") or "").upper(), key=f"ep_{rec_id}")
                    new_inv = st.text_input("Invoice 單據編號 *", value=(selected_rec.get("invoice_no") or "").upper(), key=f"ei_{rec_id}")
                    new_date = st.date_input("保養日期 *", value=orig_date, key=f"ed_{rec_id}")
                with e_col2:
                    new_ckm = st.number_input("當時里數 (km) *", min_value=0, step=500, value=int(selected_rec.get("current_km") or 0), key=f"eck_{rec_id}")
                    new_nkm = st.number_input("下次換油目標里數 (km) *", min_value=0, step=500, value=int(selected_rec.get("next_km") or 0), key=f"enk_{rec_id}")

                st.markdown("#### 🛠️ 修改保養項目、型號及收費明細")
                edit_items_state = {}
                e_calc_total = 0

                for key, tag_label, ui_label, ph, _, step_val in SERVICE_ITEMS:
                    ec, em, ep = st.columns([1.3, 1.5, 1.2])
                    with ec:
                        st.write("")
                        e_chk = st.checkbox(ui_label, value=parsed[f"{key}_chk"], key=f"echk_{key}_{rec_id}")
                    with em:
                        e_mod = st.text_input(f"{tag_label}型號 / 規格", value=parsed[f"{key}_m"], placeholder=ph, disabled=not e_chk, key=f"em_{key}_{rec_id}")
                    with ep:
                        e_prc = st.number_input(f"{tag_label}價錢 ($)", min_value=0, step=step_val, value=int(parsed[f"{key}_p"]), disabled=not e_chk, key=f"ep_{key}_{rec_id}")
                    
                    edit_items_state[f"{key}_chk"] = e_chk
                    edit_items_state[f"{key}_m"] = e_mod
                    edit_items_state[f"{key}_p"] = e_prc if e_chk else 0
                    if e_chk:
                        e_calc_total += e_prc

                st.info(f"💰 **更新後自動計算總費用：`$ {e_calc_total:,} HKD`**")

                new_notes = st.text_area("其他順便保養項目或備註", value=parsed["clean_notes"].upper(), key=f"eno_{rec_id}")

                if st.button("💾 儲存修改內容", type="primary", use_container_width=True):
                    c_plate = new_plate.strip().upper().replace(" ", "")
                    c_inv = new_inv.strip().upper()
                    c_spec = edit_items_state["oil_m"].strip().upper() if edit_items_state["oil_chk"] else ""
                    c_date_str = str(new_date)

                    if not c_plate or not c_inv:
                        st.error("⚠️ 車牌號碼同埋 Invoice 單據編號唔可以留空！")
                    elif any(r["id"] != rec_id and (r.get("invoice_no") or "").upper() == c_inv for r in oil_records):
                        st.error(f"❌ 修改失敗：Invoice 單號 `{c_inv}` 已經被其他紀錄使用！")
                    elif any(r["id"] != rec_id and (r.get("license_plate") or "").upper() == c_plate and r.get("service_date") == c_date_str for r in oil_records):
                        st.error(f"❌ 修改失敗：車牌 `{c_plate}` 喺 `{c_date_str}` 已經有另一筆紀錄！")
                    else:
                        updated_packed_notes = pack_items_dict_to_notes(edit_items_state, new_notes)
                        update_data = {
                            "license_plate": c_plate,
                            "invoice_no": c_inv,
                            "service_date": c_date_str,
                            "current_km": new_ckm,
                            "next_km": new_nkm,
                            "oil_spec": c_spec,
                            "oil_filter": edit_items_state["of_chk"],
                            "cost": e_calc_total,
                            "notes": updated_packed_notes
                        }
                        supabase.table("oil_records").update(update_data).eq("id", rec_id).execute()
                        st.success(f"✅ 已成功更新車牌 `{c_plate}` (單號: `{c_inv}`) 嘅紀錄！")
                        st.rerun()

                # 🗑️ 刪除紀錄區塊 (附帶二次確認防誤刪)
                st.write("")
                with st.expander("🗑️ 刪除此筆保養紀錄 (危險操作)"):
                    st.warning(f"確定要永久刪除 **車牌 `{selected_rec.get('license_plate')}` (單號: `{selected_rec.get('invoice_no')}`)** 嘅紀錄嗎？刪除後無法復原！")
                    confirm_del = st.checkbox("✅ 我確認要永久刪除呢筆紀錄", key=f"del_confirm_{rec_id}")
                    if st.button("🗑️ 立即永久刪除", type="primary", disabled=not confirm_del, use_container_width=True):
                        supabase.table("oil_records").delete().eq("id", rec_id).execute()
                        st.success("✅ 紀錄已成功刪除！")
                        st.rerun()
