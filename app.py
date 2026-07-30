import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import requests
import pydeck as pdk
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

# --- 設定頁面網頁配置 ---
st.set_page_config(
    page_title="全臺雨量觀測與降雨預報校驗自動化網頁 App",
    page_icon="⛈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 自訂 CSS 美化介面 (修正為 st.markdown 使用 unsafe_allow_html=True) ---
st.markdown("""
<style>
    /* 全域字體與背景美化 */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    h1, h2, h3 {
        font-family: "Helvetica Neue", Helvetica, Arial, "PingFang TC", "Heiti TC", "Microsoft JhengHei", sans-serif;
        color: #1E3A8A;
    }
    .metric-card {
        background-color: #F8FAFC;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        border-left: 5px solid #3B82F6;
        margin-bottom: 1rem;
    }
    .metric-card-title {
        font-size: 0.9rem;
        color: #64748B;
        font-weight: 600;
        text-transform: uppercase;
    }
    .metric-card-value {
        font-size: 1.8rem;
        color: #0F172A;
        font-weight: 700;
        margin-top: 0.25rem;
    }
    .metric-card-delta {
        font-size: 0.85rem;
        margin-top: 0.5rem;
    }
    /* 調整側邊欄樣式 */
    .sidebar .sidebar-content {
        background-color: #0F172A;
    }
    /* 專業徽章 */
    .badge {
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 600;
        display: inline-block;
    }
    .badge-success { background-color: #DCFCE7; color: #15803D; }
    .badge-warning { background-color: #FEF9C3; color: #A16207; }
    .badge-danger { background-color: #FEE2E2; color: #B91C1C; }
    .badge-info { background-color: #E0F2FE; color: #0369A1; }
</style>
""", unsafe_allow_html=True)

DB_PATH = "weather_verification.db"

# --- 資料庫初始化與工具函數 ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 建立專案表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        county TEXT NOT NULL,
        stations TEXT NOT NULL -- 逗號分隔的測站 ID
    )
    """)
    
    # 建立觀測資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS observations (
        station_id TEXT NOT NULL,
        station_name TEXT NOT NULL,
        county TEXT NOT NULL,
        datetime TEXT NOT NULL,
        precipitation REAL DEFAULT 0.0,
        wind_speed REAL DEFAULT 0.0,
        gust_speed REAL DEFAULT 0.0,
        wind_direction REAL DEFAULT 0.0,
        latitude REAL,
        longitude REAL,
        PRIMARY KEY (station_id, datetime)
    )
    """)
    
    # 建立預報資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS forecasts (
        project_id INTEGER NOT NULL,
        station_id TEXT NOT NULL,
        date TEXT NOT NULL,
        forecast_precipitation REAL NOT NULL,
        PRIMARY KEY (project_id, station_id, date)
    )
    """)
    
    conn.commit()
    
    # 插入預設專案
    # 1. 雲林縣政府（115/4/1~116/3/31 -> 西元 2026/04/01 ~ 2027/03/31）
    # 2. 農田水利署雲林管理處（115/7/1~116/6/30 -> 西元 2026/07/01 ~ 2027/06/30）
    cursor.execute("SELECT COUNT(*) FROM projects")
    if cursor.fetchone()[0] == 0:
        # 預設觀測站
        # 古坑 (467290), 斗六 (C0K400), 虎尾 (C0K430), 雲林臺大 (A2K630), 雲林分場 (72K220), 口湖工作站 (C0K490)
        default_yunlin_stations = "467290,C0K400,C0K430,A2K630,72K220,C0K490"
        default_water_stations = "C0K400,C0K430,C0K490"
        
        cursor.execute("""
        INSERT INTO projects (name, start_date, end_date, county, stations)
        VALUES (?, ?, ?, ?, ?)
        """, ("雲林縣政府", "2026-04-01", "2027-03-31", "雲林縣", default_yunlin_stations))
        
        cursor.execute("""
        INSERT INTO projects (name, start_date, end_date, county, stations)
        VALUES (?, ?, ?, ?, ?)
        """, ("農田水利署雲林管理處", "2026-07-01", "2027-06-30", "雲林縣", default_water_stations))
        
        conn.commit()
        
        # 產生豐富的歷史模擬數據，讓系統一上線就完美呈現
        generate_mock_historical_data(conn)
        
    conn.close()

def generate_mock_historical_data(conn):
    cursor = conn.cursor()
    # 定義模擬觀測站資訊
    stations_info = {
        "467290": {"name": "古坑氣象站", "lat": 23.626, "lon": 120.559, "county": "雲林縣"},
        "C0K400": {"name": "斗六", "lat": 23.696, "lon": 120.525, "county": "雲林縣"},
        "C0K430": {"name": "虎尾", "lat": 23.712, "lon": 120.432, "county": "雲林縣"},
        "A2K630": {"name": "雲林臺大", "lat": 23.708, "lon": 120.428, "county": "雲林縣"},
        "72K220": {"name": "雲林分場", "lat": 23.729, "lon": 120.485, "county": "雲林縣"},
        "C0K490": {"name": "口湖工作站", "lat": 23.578, "lon": 120.158, "county": "雲林縣"},
        "466920": {"name": "臺北", "lat": 25.037, "lon": 121.514, "county": "臺北市"},
        "467410": {"name": "臺南", "lat": 22.993, "lon": 120.204, "county": "臺南市"},
        "467440": {"name": "高雄", "lat": 22.566, "lon": 120.315, "county": "高雄市"},
        "466990": {"name": "花蓮", "lat": 23.975, "lon": 121.613, "county": "花蓮縣"},
        "467490": {"name": "臺中", "lat": 24.145, "lon": 120.684, "county": "臺中市"}
    }
    
    # 模擬從 2026-04-01 到今天 2026-07-29 的歷史數據
    start_date = datetime(2026, 4, 1)
    end_date = datetime(2026, 7, 29)
    current_date = start_date
    
    obs_batch = []
    fc_batch = []
    
    # 讀取剛才存入的專案ID
    cursor.execute("SELECT id, name FROM projects")
    projects_dict = {row["name"]: row["id"] for row in cursor.fetchall()}
    
    np.random.seed(42) # 固定隨機種子以確保重現性
    
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        dt_str = f"{date_str} 18:00:00"
        month = current_date.month
        
        # 依季節定義降雨機率與雨量
        if month in [5, 6]: # 梅雨季：降雨機率高，雨量中等
            rain_prob = 0.5
            rain_scale = 25.0
        elif month == 7: # 汛期/颱風季：降雨機率一般，但若下雨則可能偏大
            rain_prob = 0.35
            rain_scale = 45.0
        else: # 4月：春雨/乾季過渡
            rain_prob = 0.2
            rain_scale = 10.0
            
        for sid, info in stations_info.items():
            # 1. 產生觀測數據
            is_rainy = np.random.rand() < rain_prob
            if is_rainy:
                # 採用指數分佈模擬真實降雨量特徵（小雨多、豪雨少）
                obs_rain = np.round(np.random.exponential(scale=rain_scale), 1)
            else:
                obs_rain = 0.0
                
            wind_speed = np.round(np.random.uniform(0.5, 6.0), 1)
            gust_speed = np.round(wind_speed * np.random.uniform(1.2, 2.5), 1)
            wind_dir = np.random.randint(0, 360)
            
            obs_batch.append((
                sid, info["name"], info["county"], dt_str,
                obs_rain, wind_speed, gust_speed, wind_dir,
                info["lat"], info["lon"]
            ))
            
            # 2. 產生各專案的預報雨量 (對應雲林縣的測站)
            if info["county"] == "雲林縣":
                # 雲林縣政府專案 (ID = 1)
                if current_date >= datetime(2026, 4, 1):
                    # 預報雨量模擬：在實際雨量附近加點隨機誤差（模擬有準有不準）
                    forecast_error = np.random.normal(loc=0.0, scale=max(3.0, obs_rain * 0.25))
                    fc_rain = max(0.0, np.round(obs_rain + forecast_error, 1))
                    fc_batch.append((1, sid, date_str, fc_rain))
                    
                # 農田水利署專案 (ID = 2) - 7/1起
                if current_date >= datetime(2026, 7, 1):
                    # 另一種預報模型，稍微傾向高估 (Wet Bias)
                    forecast_error = np.random.normal(loc=1.5, scale=max(4.0, obs_rain * 0.3))
                    fc_rain = max(0.0, np.round(obs_rain + forecast_error, 1))
                    fc_batch.append((2, sid, date_str, fc_rain))
                    
        current_date += timedelta(days=1)
        
    # 大量寫入資料庫
    cursor.executemany("""
    INSERT OR REPLACE INTO observations (
        station_id, station_name, county, datetime,
        precipitation, wind_speed, gust_speed, wind_direction, latitude, longitude
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, obs_batch)
    
    cursor.executemany("""
    INSERT OR REPLACE INTO forecasts (project_id, station_id, date, forecast_precipitation)
    VALUES (?, ?, ?, ?)
    """, fc_batch)
    
    conn.commit()

# 初始化資料庫
init_db()

# --- 側邊欄設計 ---
st.sidebar.image("https://img.icons8.com/clouds/200/stormy-weather.png", width=120)
st.sidebar.title("☔ 降雨校驗與監測系統")
st.sidebar.markdown("---")

# 氣象署授權碼設定
st.sidebar.subheader("🔑 氣象署 OpenData 設定")
cwa_api_key = st.sidebar.text_input(
    "API 授權碼", 
    value="CWA-8AB1C9F4-CD80-4296-BD3F-4B28FB433A25", 
    type="password",
    help="可在氣象署開放資料平台取得"
)

# 導覽選單
menu_selection = st.sidebar.radio(
    "🗺️ 功能導覽",
    ["📊 全台觀測綜觀", "📁 專案管理與新增", "📈 專案預報校驗"]
)

st.sidebar.markdown("---")
st.sidebar.info(
    "💡 **提示**：系統已自動填入您的 API 授權碼，並建立雲林縣政府與農田水利署專案！同時自動產生了 2026/04/01 起的歷史模擬數據，供您立即體驗校驗功能。"
)

# --- 氣象署 API 資料獲取邏輯 ---
def fetch_and_store_cwa_data(api_key):
    urls = [
        "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001", # 局屬站
        "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001"  # 自動站
    ]
    
    success_count = 0
    total_parsed = 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for url in urls:
        params = {"Authorization": api_key, "format": "JSON"}
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                stations = data.get("records", {}).get("Station", [])
                
                for st_data in stations:
                    sid = st_data.get("StationId")
                    sname = st_data.get("StationName")
                    county = st_data.get("GeoInfo", {}).get("CountyName", "未知")
                    
                    # 取得經緯度
                    lat = None
                    lon = None
                    coords = st_data.get("GeoInfo", {}).get("Coordinates", [])
                    for coord in coords:
                        if coord.get("CoordinateName") == "WGS84":
                            lat = coord.get("StationLatitude")
                            lon = coord.get("StationLongitude")
                    
                    if lat is None:
                        lat = st_data.get("GeoInfo", {}).get("StationLatitude")
                        lon = st_data.get("GeoInfo", {}).get("StationLongitude")
                    
                    # 時間解析
                    obs_time = st_data.get("ObsTime", {}).get("DateTime", current_time_str)
                    # 格式轉換為 SQLite 友善的字串
                    try:
                        # 處理 ISO 格式如 2026-07-29T18:00:00+08:00
                        dt = datetime.fromisoformat(obs_time)
                        obs_time_formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        obs_time_formatted = obs_time
                    
                    # 解析氣象要素 (採用極為防守、相容雙結構的解法)
                    precip = 0.0
                    wind_speed = 0.0
                    gust_speed = 0.0
                    wind_dir = 0.0
                    
                    we = st_data.get("WeatherElement", {})
                    if isinstance(we, dict):
                        # 降雨
                        now_rain = we.get("Now", {})
                        if isinstance(now_rain, dict):
                            precip = now_rain.get("Precipitation", 0.0)
                        else:
                            precip = we.get("Precipitation", 0.0)
                            
                        wind_speed = we.get("WindSpeed", 0.0)
                        gust_speed = we.get("GustSpeed", 0.0)
                        wind_dir = we.get("WindDirection", 0.0)
                    elif isinstance(we, list):
                        for elem in we:
                            name = elem.get("ElementName")
                            val = elem.get("ElementValue")
                            if val is None or val == "None" or val == "" or val == "-99" or val == "-999":
                                val = 0.0
                            try:
                                val_f = float(val)
                            except ValueError:
                                val_f = 0.0
                                
                            if name in ["Precipitation", "Now", "Min10"]:
                                precip = val_f
                            elif name == "WindSpeed":
                                wind_speed = val_f
                            elif name == "GustSpeed":
                                gust_speed = val_f
                            elif name == "WindDirection":
                                wind_dir = val_f
                    
                    # 排除異常缺測值 (-99, -999 等)
                    precip = max(0.0, float(precip)) if float(precip) >= 0 else 0.0
                    wind_speed = max(0.0, float(wind_speed)) if float(wind_speed) >= 0 else 0.0
                    gust_speed = max(0.0, float(gust_speed)) if float(gust_speed) >= 0 else 0.0
                    wind_dir = max(0.0, float(wind_dir)) if float(wind_dir) >= 0 else 0.0
                    
                    cursor.execute("""
                    INSERT OR REPLACE INTO observations (
                        station_id, station_name, county, datetime,
                        precipitation, wind_speed, gust_speed, wind_direction, latitude, longitude
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (sid, sname, county, obs_time_formatted, precip, wind_speed, gust_speed, wind_dir, lat, lon))
                    total_parsed += 1
                
                success_count += 1
        except Exception as e:
            st.error(f"連線至 API 時發生異常: {e}")
            
    conn.commit()
    conn.close()
    return success_count > 0, total_parsed


# ==========================================
# 📊 功能頁面 1：全台觀測綜觀
# ==========================================
if menu_selection == "📊 全台觀測綜觀":
    st.title("📊 全臺即時氣象觀測綜觀")
    st.markdown("自動獲取氣象署全臺測站即時 10 分鐘雨量與風速風向，可切換查看全臺或聚焦特定專案測站。")
    
    # 手動更新按鈕
    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 立即同步最新觀測資料", use_container_width=True):
            with st.spinner("正在與中央氣象署同步最新觀測資料..."):
                success, count = fetch_and_store_cwa_data(cwa_api_key)
                if success:
                    st.success(f"同步成功！共更新 {count} 筆觀測站數據。")
                else:
                    st.warning("同步完成，但未能成功取得外部資料。已為您載入本地資料庫。")
    
    # 讀取當前最新的所有測站觀測
    conn = get_db_connection()
    df_obs = pd.read_sql_query("""
    SELECT o1.* FROM observations o1
    INNER JOIN (
        SELECT station_id, MAX(datetime) as max_dt FROM observations GROUP BY station_id
    ) o2 ON o1.station_id = o2.station_id AND o1.datetime = o2.max_dt
    """, conn)
    
    # 讀取專案清單
    df_projects = pd.read_sql_query("SELECT * FROM projects", conn)
    conn.close()
    
    # 篩選控制
    st.markdown("### 🔍 地圖與數據篩選")
    filter_mode = st.radio("篩選方式", ["依專案篩選", "依縣市篩選", "呈現全臺測站"], horizontal=True)
    
    filtered_df = df_obs.copy()
    
    if filter_mode == "依專案篩選":
        if not df_projects.empty:
            proj_choice = st.selectbox("選擇專案", df_projects["name"].tolist())
            proj_row = df_projects[df_projects["name"] == proj_choice].iloc[0]
            proj_stations = [s.strip() for s in proj_row["stations"].split(",") if s.strip()]
            filtered_df = df_obs[df_obs["station_id"].isin(proj_stations)]
            st.write(f"📌 **專案時程**：{proj_row['start_date']} 至 {proj_row['end_date']} | **管轄縣市**：{proj_row['county']}")
        else:
            st.info("目前尚無專案，請先前往 📁 專案管理與新增 建立專案。")
            
    elif filter_mode == "依縣市篩選":
        counties = sorted(df_obs["county"].unique().tolist())
        county_choice = st.selectbox("選擇縣市", counties, index=counties.index("雲林縣") if "雲林縣" in counties else 0)
        filtered_df = df_obs[df_obs["county"] == county_choice]
        
    # 如果資料為空，給予防禦性提示
    if filtered_df.empty:
        st.warning("查無符合篩選條件的測站觀測資料，呈現預設全臺測站。")
        filtered_df = df_obs
        
    # 地圖與摘要看板
    col_map, col_metrics = st.columns([3, 1])
    
    with col_map:
        # 地圖圖層設定：以雨量 precipitation 為半徑與顏色深淺
        # 去除 NaN 經緯度
        map_df = filtered_df.dropna(subset=['latitude', 'longitude'])
        
        # 設計 3D 柱狀與圓點圖層
        layer = pdk.Layer(
            "ScatterplotLayer",
            map_df,
            pickable=True,
            opacity=0.8,
            stroked=True,
            filled=True,
            radius_scale=15,
            radius_min_pixels=10,
            radius_max_pixels=100,
            line_width_min_pixels=1,
            get_position="[longitude, latitude]",
            get_radius="precipitation * 50 + 100", # 雨量越大，半徑越大
            get_fill_color="[precipitation * 15, 100 + precipitation * 5, 255 - precipitation * 20, 180]", # 雨量大偏紅，小偏藍
            get_line_color=[255, 255, 255],
        )
        
        view_state = pdk.ViewState(
            latitude=map_df["latitude"].mean() if not map_df.empty else 23.6,
            longitude=map_df["longitude"].mean() if not map_df.empty else 120.5,
            zoom=9.5 if filter_mode != "呈現全臺測站" else 7.5,
            pitch=30,
        )
        
        r = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip={"text": "測站: {station_name} ({station_id})\n縣市: {county}\n觀測時間: {datetime}\n雨量: {precipitation} mm\n平均風速: {wind_speed} m/s\n陣風: {gust_speed} m/s\n風向: {wind_direction}°"}
        )
        
        st.pydeck_chart(r)
        
    with col_metrics:
        # 指標卡呈現
        avg_rain = filtered_df["precipitation"].mean() if not filtered_df.empty else 0
        max_rain = filtered_df["precipitation"].max() if not filtered_df.empty else 0
        max_rain_st = filtered_df.loc[filtered_df["precipitation"].idxmax()]["station_name"] if not filtered_df.empty and filtered_df["precipitation"].max() > 0 else "無"
        max_wind = filtered_df["gust_speed"].max() if not filtered_df.empty else 0
        max_wind_st = filtered_df.loc[filtered_df["gust_speed"].idxmax()]["station_name"] if not filtered_df.empty and filtered_df["gust_speed"].max() > 0 else "無"
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-card-title">☔ 篩選區域平均降雨量</div>
            <div class="metric-card-value">{avg_rain:.2f} <span style="font-size:1rem;color:#64748B;">mm</span></div>
        </div>
        <div class="metric-card" style="border-left-color: #EF4444;">
            <div class="metric-card-title">🚨 當前最大降雨觀測站</div>
            <div class="metric-card-value">{max_rain:.1f} <span style="font-size:1rem;color:#64748B;">mm</span></div>
            <div class="metric-card-delta" style="color: #EF4444;">站點：{max_rain_st}</div>
        </div>
        <div class="metric-card" style="border-left-color: #F59E0B;">
            <div class="metric-card-title">💨 當前全臺最大瞬間陣風</div>
            <div class="metric-card-value">{max_wind:.1f} <span style="font-size:1rem;color:#64748B;">m/s</span></div>
            <div class="metric-card-delta" style="color: #F59E0B;">站點：{max_wind_st}</div>
        </div>
        """, unsafe_allow_html=True)
        
    # 資料表檢視
    st.markdown("### 📋 詳細即時觀測數據表")
    display_df = filtered_df[["station_id", "station_name", "county", "datetime", "precipitation", "wind_speed", "gust_speed", "wind_direction"]].copy()
    display_df.columns = ["測站編號", "觀測站名稱", "縣市", "最後觀測時間", "降雨量 (mm)", "平均風 (m/s)", "陣風 (m/s)", "風向 (度)"]
    st.dataframe(display_df, use_container_width=True, hide_index=True)


# ==========================================
# 📁 功能頁面 2：專案管理與新增
# ==========================================
elif menu_selection == "📁 專案管理與新增":
    st.title("📁 專案設定與管理頁面")
    st.markdown("在本頁面中，您可以隨時新增全新的專案合約（例如新增其他縣市、不同期程的專案），並手動指派要校驗的觀測站群組。")
    
    # 讀取全台所有可用的測站與縣市關係
    conn = get_db_connection()
    all_stations_df = pd.read_sql_query("SELECT DISTINCT station_id, station_name, county FROM observations", conn)
    
    # 如果資料庫完全沒資料，採用預置的雲林縣測站清單作保底
    if all_stations_df.empty:
        all_stations_df = pd.DataFrame([
            {"station_id": "467290", "station_name": "古坑氣象站", "county": "雲林縣"},
            {"station_id": "C0K400", "station_name": "斗六", "county": "雲林縣"},
            {"station_id": "C0K430", "station_name": "虎尾", "county": "雲林縣"},
            {"station_id": "A2K630", "station_name": "雲林臺大", "county": "雲林縣"},
            {"station_id": "72K220", "station_name": "雲林分場", "county": "雲林縣"},
            {"station_id": "C0K490", "station_name": "口湖工作站", "county": "雲林縣"}
        ])
    
    # 左：新增專案，右：現有專案列表
    col_add, col_list = st.columns([1, 1])
    
    with col_add:
        st.subheader("➕ 新增專案頁面")
        with st.form("new_project_form"):
            new_proj_name = st.text_input("專案名稱", placeholder="例如：雲林縣政府 / 水利署雲林管處")
            
            # 專案起迄日期
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                new_start_date = st.date_input("合約啟始日期", value=datetime(2026, 4, 1))
            with col_d2:
                new_end_date = st.date_input("合約結束日期", value=datetime(2027, 3, 31))
                
            # 選擇專案主轄區縣市
            counties_list = sorted(all_stations_df["county"].unique().tolist())
            if not counties_list:
                counties_list = ["雲林縣"]
            selected_county = st.selectbox("專案管轄縣市", counties_list, index=counties_list.index("雲林縣") if "雲林縣" in counties_list else 0)
            
            # 動態載入該縣市所擁有的觀測站供使用者自由挑選
            county_stations = all_stations_df[all_stations_df["county"] == selected_county]
            station_options = {f"{row['station_name']} ({row['station_id']})": row['station_id'] for _, row in county_stations.iterrows()}
            
            selected_stations_labels = st.multiselect(
                "指派觀測站 (可多選)",
                options=list(station_options.keys()),
                default=list(station_options.keys())[:3] if len(station_options) >= 3 else list(station_options.keys())
            )
            
            submit_btn = st.form_submit_with_id(
                id="submit_new_project",
                label="💾 儲存並建立專案頁面"
            )
            
            if submit_btn:
                if not new_proj_name.strip():
                    st.error("請輸入專案名稱！")
                elif new_start_date > new_end_date:
                    st.error("啟始日期不能大於結束日期！")
                elif not selected_stations_labels:
                    st.error("請至少指派一個觀測站點！")
                else:
                    station_ids_str = ",".join([station_options[lbl] for lbl in selected_stations_labels])
                    try:
                        cursor = conn.cursor()
                        cursor.execute("""
                        INSERT INTO projects (name, start_date, end_date, county, stations)
                        VALUES (?, ?, ?, ?, ?)
                        """, (new_proj_name, new_start_date.strftime("%Y-%m-%d"), new_end_date.strftime("%Y-%m-%d"), selected_county, station_ids_str))
                        conn.commit()
                        st.success(f"🎉 專案『{new_proj_name}』建置成功！")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("該專案名稱已存在，請使用不同的名稱。")
                    except Exception as e:
                        st.error(f"建立專案失敗: {e}")
                        
    with col_list:
        st.subheader("📂 系統現有專案頁面清單")
        
        # 讀取並顯示所有專案
        df_proj_show = pd.read_sql_query("SELECT * FROM projects", conn)
        
        if df_proj_show.empty:
            st.info("目前尚無建立的專案。")
        else:
            for _, row in df_proj_show.iterrows():
                # 取得測站代號清單，轉換為人易讀的中文站名
                st_ids = [s.strip() for s in row["stations"].split(",") if s.strip()]
                names_list = []
                for sid in st_ids:
                    match = all_stations_df[all_stations_df["station_id"] == sid]
                    if not match.empty:
                        names_list.append(match.iloc[0]["station_name"])
                    else:
                        names_list.append(sid)
                
                with st.expander(f"📁 {row['name']} ({row['county']})", expanded=True):
                    st.write(f"📅 **合約期程**：`{row['start_date']}` 至 `{row['end_date']}`")
                    st.write(f"🗺️ **關聯觀測站**：{', '.join(names_list)}")
                    
                    # 刪除功能
                    if st.button(f"🗑️ 移除此專案", key=f"del_{row['id']}"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM projects WHERE id = ?", (row['id'],))
                        # 同時刪除對應的預報資料
                        cursor.execute("DELETE FROM forecasts WHERE project_id = ?", (row['id'],))
                        conn.commit()
                        st.warning(f"專案『{row['name']}』已移除")
                        st.rerun()
                        
    conn.close()


# ==========================================
# 📈 功能頁面 3：專案預報校驗
# ==========================================
elif menu_selection == "📈 專案預報校驗":
    st.title("📈 降雨預報校驗與統計圖表")
    st.markdown("在此頁面，您可以自由點選您所新增的專案，輸入該專案觀測站的預報雨量值，系統將自動為您統計計算 BIAS 及 RMSE 並產出高水準圖表。")
    
    conn = get_db_connection()
    df_projects = pd.read_sql_query("SELECT * FROM projects", conn)
    
    if df_projects.empty:
        st.warning("⚠️ 目前資料庫內無任何專案。請先切換至「📁 專案管理與新增」建立專案！")
        conn.close()
    else:
        # 1. 選擇專案
        proj_list = df_projects["name"].tolist()
        selected_proj_name = st.selectbox("📁 第一步：選擇校驗專案", proj_list)
        
        proj_info = df_projects[df_projects["name"] == selected_proj_name].iloc[0]
        proj_id = int(proj_info["id"])
        proj_start_dt = datetime.strptime(proj_info["start_date"], "%Y-%m-%d")
        proj_end_dt = datetime.strptime(proj_info["end_date"], "%Y-%m-%d")
        
        # 取得專案內綁定的觀測站
        st_ids = [s.strip() for s in proj_info["stations"].split(",") if s.strip()]
        
        # 讀取對應的中文測站名稱對照
        st_placeholders = ",".join(["?"] * len(st_ids))
        df_proj_stations = pd.read_sql_query(f"""
            SELECT DISTINCT station_id, station_name FROM observations 
            WHERE station_id IN ({st_placeholders})
        """, conn, params=st_ids)
        
        # 保底
        if df_proj_stations.empty:
            df_proj_stations = pd.DataFrame([
                {"station_id": sid, "station_name": f"觀測站 {sid}"} for sid in st_ids
            ])
            
        station_mapping = {row["station_name"]: row["station_id"] for _, row in df_proj_stations.iterrows()}
        
        col_st_sel, col_date_sel = st.columns([1, 2])
        
        with col_st_sel:
            # 2. 選擇校驗觀測站
            selected_st_name = st.selectbox("⛈️ 第二步：選擇要校驗的觀測站", list(station_mapping.keys()))
            selected_st_id = station_mapping[selected_st_name]
            
        with col_date_sel:
            # 3. 選擇期程模式（滿足五大時間區間需求）
            date_mode = st.radio(
                "📅 第三步：選擇時間區間模式",
                ["每7日基本計算單位", "梅雨季期間 (5/1~6/30)", "每年汛期期間 (4/1~11/30)", "每年非汛期期間 (12/1~3/31)", "全年度", "自訂特定日期範圍"],
                horizontal=True
            )
            
        # 計算實際的日期起迄
        # 由於合約期間可能橫跨西元 2026 ~ 2027
        # 我們會根據選取專案的 start_date 和 end_date 的年份，去截取對應的季度
        proj_years = list(range(proj_start_dt.year, proj_end_dt.year + 1))
        
        cal_start = proj_start_dt
        cal_end = proj_end_dt
        
        if date_mode == "每7日基本計算單位":
            # 讓使用者自訂週起點
            week_start = st.date_input("選擇 7 日起始日期", value=proj_start_dt, min_value=proj_start_dt, max_value=proj_end_dt)
            cal_start = datetime.combine(week_start, datetime.min.time())
            cal_end = cal_start + timedelta(days=6)
            
        elif date_mode == "梅雨季期間 (5/1~6/30)":
            # 如果專案起迄橫跨複數年，讓使用者選取年份
            target_year = st.selectbox("選擇年份", proj_years)
            cal_start = datetime(target_year, 5, 1)
            cal_end = datetime(target_year, 6, 30)
            
        elif date_mode == "每年汛期期間 (4/1~11/30)":
            target_year = st.selectbox("選擇年份", proj_years)
            cal_start = datetime(target_year, 4, 1)
            cal_end = datetime(target_year, 11, 30)
            
        elif date_mode == "每年非汛期期間 (12/1~3/31)":
            # 非汛期跨年，例如 115/12/1~116/3/31，即 2026-12-01 ~ 2027-03-31
            target_start_year = st.selectbox("選擇非汛期起始年份", proj_years[:-1] if len(proj_years) > 1 else proj_years)
            cal_start = datetime(target_start_year, 12, 1)
            cal_end = datetime(target_start_year + 1, 3, 31)
            
        elif date_mode == "全年度":
            target_year = st.selectbox("選擇年份", proj_years)
            cal_start = datetime(target_year, 1, 1)
            cal_end = datetime(target_year, 12, 31)
            
        elif date_mode == "自訂特定日期範圍":
            custom_range = st.date_input(
                "請選取起迄日期", 
                value=(proj_start_dt, proj_start_dt + timedelta(days=14)),
                min_value=proj_start_dt,
                max_value=proj_end_dt
            )
            if isinstance(custom_range, tuple) and len(custom_range) == 2:
                cal_start = datetime.combine(custom_range[0], datetime.min.time())
                cal_end = datetime.combine(custom_range[1], datetime.min.time())
            elif isinstance(custom_range, datetime) or isinstance(custom_range, timedelta):
                cal_start = datetime.combine(custom_range, datetime.min.time())
                cal_end = cal_start
                
        # 限制計算區間不超過專案合約本身
        cal_start = max(cal_start, proj_start_dt)
        cal_end = min(cal_end, proj_end_dt)
        
        st.markdown(f"💡 目前計算區間：**`{cal_start.strftime('%Y-%m-%d')}` 至 `{cal_end.strftime('%Y-%m-%d')}`**")
        st.markdown("---")
        
        # 讀取此區間內所有「每日實際降雨觀測總和」(以每日18:00或日累積雨量代表)
        start_str = cal_start.strftime("%Y-%m-%d")
        end_str = cal_end.strftime("%Y-%m-%d")
        
        # 查詢觀測數據與預報數據
        # 我們將觀測資料轉換為以「天」為單位的統計 (使用 SUBSTR 擷取日 yyyy-mm-dd)
        df_actual = pd.read_sql_query("""
            SELECT SUBSTR(datetime, 1, 10) as date, SUM(precipitation) as actual_precip
            FROM observations
            WHERE station_id = ? AND SUBSTR(datetime, 1, 10) BETWEEN ? AND ?
            GROUP BY SUBSTR(datetime, 1, 10)
        """, conn, params=(selected_st_id, start_str, end_str))
        
        # 讀取此專案此測站在該期間內的預設預報值
        df_forecast = pd.read_sql_query("""
            SELECT date, forecast_precipitation FROM forecasts
            WHERE project_id = ? AND station_id = ? AND date BETWEEN ? AND ?
        """, conn, params=(proj_id, selected_st_id, start_str, end_str))
        
        # 合併產生連續行事曆 DataFrame
        date_list = []
        curr = cal_start
        while curr <= cal_end:
            date_list.append(curr.strftime("%Y-%m-%d"))
            curr += timedelta(days=1)
            
        base_df = pd.DataFrame({"日期": date_list})
        
        # 結合觀測值
        if not df_actual.empty:
            df_actual.columns = ["日期", "實際觀測雨量 (mm)"]
            base_df = pd.merge(base_df, df_actual, on="日期", how="left")
        else:
            base_df["實際觀測雨量 (mm)"] = 0.0
            
        # 結合預報值
        if not df_forecast.empty:
            df_forecast.columns = ["日期", "預報雨量 (mm)"]
            base_df = pd.merge(base_df, df_forecast, on="日期", how="left")
        else:
            base_df["預報雨量 (mm)"] = 0.0
            
        base_df = base_df.fillna(0.0)
        
        # 4. 線上編輯預報值與數據儲存
        st.subheader("✍️ 第四步：請輸入或修改預報雨量")
        st.markdown("可在下方直接點擊『預報雨量 (mm)』欄位的儲存格修改數據，修改完成後點擊表格下方的**「💾 儲存並計算校驗指標」**。")
        
        # 為了 st.data_editor 呈現，建立一個編輯專用的 DataFrame
        edit_df = base_df.copy()
        
        edited_df = st.data_editor(
            edit_df,
            column_config={
                "日期": st.column_config.TextColumn(disabled=True),
                "實際觀測雨量 (mm)": st.column_config.NumberColumn(format="%.1f mm", disabled=True),
                "預報雨量 (mm)": st.column_config.NumberColumn(format="%.1f", min_value=0.0, step=0.1)
            },
            use_container_width=True,
            hide_index=True
        )
        
        # 儲存預報資料回資料庫
        if st.button("💾 儲存並計算校驗指標"):
            cursor = conn.cursor()
            save_count = 0
            for _, row in edited_df.iterrows():
                dt_str = row["日期"]
                fc_val = float(row["預報雨量 (mm)"])
                
                cursor.execute("""
                INSERT OR REPLACE INTO forecasts (project_id, station_id, date, forecast_precipitation)
                VALUES (?, ?, ?, ?)
                """, (proj_id, selected_st_id, dt_str, fc_val))
                save_count += 1
                
            conn.commit()
            st.success(f"成功儲存 {save_count} 天的預報降雨量，校驗指標已同步更新！")
            base_df = edited_df # 將編輯後的資料作為最新的計算基準
            
        # 5. 計算 BIAS & RMSE
        # 計算公式：
        # BIAS = (1/N) * sum(F_i - O_i)
        # RMSE = sqrt( (1/N) * sum( (F_i - O_i)^2 ) )
        obs_vals = base_df["實際觀測雨量 (mm)"].values
        fc_vals = base_df["預報雨量 (mm)"].values
        n = len(base_df)
        
        if n > 0:
            diff = fc_vals - obs_vals
            bias_val = np.mean(diff)
            rmse_val = np.sqrt(np.mean(diff ** 2))
            
            # 解讀分析
            if bias_val > 0.5:
                bias_status = '<span class="badge badge-danger">🔴 系統性高估 (Wet Bias)</span>'
                bias_desc = "預報模式偏向濕，預報降水量普遍高於實際觀測量。"
            elif bias_val < -0.5:
                bias_status = '<span class="badge badge-warning">🟡 系統性低估 (Dry Bias)</span>'
                bias_desc = "預報模式偏向乾，預報降水量普遍低於實際觀測量，注意漏報風險。"
            else:
                bias_status = '<span class="badge badge-success">🟢 準確無系統性偏差 (No Bias)</span>'
                bias_desc = "預報分佈極其優異，與實際降水總量吻合度極高。"
                
            # 三大指標看板
            col_b, col_r, col_a = st.columns(3)
            with col_b:
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #3B82F6;">
                    <div class="metric-card-title">📉 預報偏差 (Mean Bias)</div>
                    <div class="metric-card-value">{bias_val:+.2f} <span style="font-size:1rem;color:#64748B;">mm</span></div>
                    <div class="metric-card-delta">{bias_status}</div>
                </div>
                """, unsafe_allow_html=True)
            with col_r:
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #EF4444;">
                    <div class="metric-card-title">📏 均方根誤差 (RMSE)</div>
                    <div class="metric-card-value">{rmse_val:.2f} <span style="font-size:1rem;color:#64748B;">mm</span></div>
                    <div class="metric-card-delta" style="color: #64748B; font-weight:600;">(數值越低越精準)</div>
                </div>
                """, unsafe_allow_html=True)
            with col_a:
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: #10B981;">
                    <div class="metric-card-title">📆 總校驗天數</div>
                    <div class="metric-card-value">{n} <span style="font-size:1rem;color:#64748B;">天</span></div>
                    <div class="metric-card-delta" style="color:#10B981; font-weight:600;">{cal_start.strftime('%m/%d')} ~ {cal_end.strftime('%m/%d')}</div>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown(f"**💡 專業分析解讀**：{bias_desc}")
            
            # 6. 自動產出圖表 (Plotly 雙軌圖表)
            st.subheader("📊 實際降雨量 vs 預報雨量 對比折線/柱狀圖")
            
            fig = go.Figure()
            
            # 實際雨量（藍色長條圖）
            fig.add_trace(go.Bar(
                x=base_df["日期"],
                y=base_df["實際觀測雨量 (mm)"],
                name="實際觀測雨量 (Observed)",
                marker_color="#3B82F6",
                opacity=0.85
            ))
            
            # 預報雨量（紅色折線圖）
            fig.add_trace(go.Scatter(
                x=base_df["日期"],
                y=base_df["預報雨量 (mm)"],
                name="我輸入的預報雨量 (Forecasted)",
                mode="lines+markers",
                line=dict(color="#EF4444", width=3),
                marker=dict(size=8)
            ))
            
            fig.update_layout(
                title=f"【{selected_proj_name}】{selected_st_name}站 降雨校驗統計 (BIAS: {bias_val:+.2f} mm | RMSE: {rmse_val:.2f} mm)",
                xaxis_title="日期",
                yaxis_title="累積降雨量 (mm)",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=40, r=40, t=80, b=40),
                height=500,
                plot_bgcolor="rgba(255, 255, 255, 0.9)",
                paper_bgcolor="rgba(240, 242, 246, 0.5)"
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # 數據導出
            csv_data = base_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 匯出當前校驗數據 (.csv)",
                data=csv_data,
                file_name=f"{selected_proj_name}_{selected_st_name}_降雨校驗.csv",
                mime="text/csv"
            )
        else:
            st.error("此區間内無有效的日期數據進行統計計算。")
            
    conn.close()

st.sidebar.markdown("---")
st.sidebar.caption("© 2026 全臺雨量智慧預報校驗小幫手 - 降雨校驗與監測系統")
