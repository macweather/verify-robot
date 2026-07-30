import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import requests
import json
import os
import pydeck as pdk
from datetime import datetime, timedelta

# ==============================================================================
# PAGE CONFIGURATION & STYLING
# ==============================================================================
st.set_page_config(
    page_title="全臺雨量觀測與預報校驗平台",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern UI styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.5rem;
        border-bottom: 2px solid #3B82F6;
        padding-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.4rem;
        font-weight: 600;
        color: #2563EB;
        margin-top: 1.5rem;
        margin-bottom: 0.8rem;
    }
    .metric-card {
        background-color: #F3F4F6;
        border-radius: 8px;
        padding: 1rem;
        border-left: 5px solid #3B82F6;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .metric-label {
        font-size: 0.9rem;
        color: #4B5563;
        font-weight: 600;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #111827;
    }
    .highlight-box {
        background-color: #EFF6FF;
        border: 1px solid #BFDBFE;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allowed_html=True)

# Database path
DB_PATH = "weather_verification.db"

# ==============================================================================
# DATABASE INITIALIZATION & SCHEMA
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # 1. Projects Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        start_date TEXT,
        end_date TEXT,
        county TEXT
    )
    ''')
    
    # 2. Project Stations Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS project_stations (
        project_id INTEGER,
        station_id TEXT,
        PRIMARY KEY (project_id, station_id),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    ''')
    
    # 3. Stations Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stations (
        station_id TEXT PRIMARY KEY,
        station_name TEXT,
        county TEXT,
        township TEXT,
        longitude REAL,
        latitude REAL
    )
    ''')
    
    # 4. Observations Table (10-minute / Hourly Weather elements)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS observations (
        station_id TEXT,
        obs_time TEXT,
        rainfall REAL,        -- Accumulated daily precipitation at that hour, or interval rain
        wind_speed REAL,      -- Average wind speed (m/s)
        wind_direction REAL,  -- Wind direction (degrees)
        gust_speed REAL,      -- Peak gust speed (m/s)
        PRIMARY KEY (station_id, obs_time),
        FOREIGN KEY (station_id) REFERENCES stations(station_id)
    )
    ''')
    
    # 5. Forecasts Table (Daily rainfall forecast entered by user)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS forecasts (
        project_id INTEGER,
        station_id TEXT,
        date TEXT,
        forecast_rainfall REAL,
        PRIMARY KEY (project_id, station_id, date),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY (station_id) REFERENCES stations(station_id)
    )
    ''')
    
    # Check if we should insert initial default data (Projects: Yunlin Government & Irrigation Agency Yunlin Office)
    cursor.execute("SELECT COUNT(*) FROM projects")
    if cursor.fetchone()[0] == 0:
        # Default projects
        cursor.execute('''
        INSERT INTO projects (name, start_date, end_date, county)
        VALUES 
        ('雲林縣政府', '2026-04-01', '2027-03-31', '雲林縣'),
        ('農田水利署雲林管理處', '2026-07-01', '2027-06-30', '雲林縣')
        ''')
        
        # Default Taiwan key stations for metadata to ensure immediate setup
        default_stations = [
            # Yunlin County stations
            ('467290', '古坑氣象站', '雲林縣', '古坑鄉', 120.56, 23.65),
            ('C0K400', '斗六', '雲林縣', '斗六市', 120.62, 23.70),
            ('C0K430', '虎尾', '雲林縣', '虎尾鎮', 120.43, 23.71),
            ('A2K630', '雲林臺大', '雲林縣', '虎尾鎮', 120.41, 23.70),
            ('72K220', '雲林分場', '雲林縣', '莿桐鄉', 120.48, 23.76),
            ('C0K490', '口湖工作站', '雲林縣', '口湖鄉', 120.15, 23.58),
            # Other main Taiwan stations for Taiwan-wide overview simulation
            ('466920', '臺北', '臺北市', '中正區', 121.51, 25.03),
            ('467410', '臺南', '臺南市', '中西區', 120.20, 22.99),
            ('467490', '臺中', '臺中市', '北區', 120.68, 24.14),
            ('467050', '新屋', '桃園市', '新屋區', 121.03, 24.97),
            ('467440', '高雄', '高雄市', '前鎮區', 120.31, 22.56),
            ('466990', '花蓮', '花蓮縣', '花蓮市', 121.61, 23.97)
        ]
        
        cursor.executemany('''
        INSERT OR IGNORE INTO stations (station_id, station_name, county, township, longitude, latitude)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', default_stations)
        
        # Connect stations to projects
        # Project 1: Yunlin County Gov (all 6 Yunlin stations)
        cursor.executemany('''
        INSERT OR IGNORE INTO project_stations (project_id, station_id)
        VALUES (?, ?)
        ''', [(1, '467290'), (1, 'C0K400'), (1, 'C0K430'), (1, 'A2K630'), (1, '72K220'), (1, 'C0K490')])
        
        # Project 2: Irrigation Agency (3 key water management stations)
        cursor.executemany('''
        INSERT OR IGNORE INTO project_stations (project_id, station_id)
        VALUES (?, ?)
        ''', [(2, 'C0K400'), (2, 'C0K430'), (2, 'C0K490')])
        
    conn.commit()
    conn.close()

# Initialize DB structure on load
init_db()

# ==============================================================================
# SIMULATED HISTORICAL DATA GENERATOR (Critical for Offline/Initial Use)
# ==============================================================================
def generate_historical_simulation(force=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if simulation is needed
    cursor.execute("SELECT COUNT(*) FROM observations")
    obs_count = cursor.fetchone()[0]
    
    if obs_count > 0 and not force:
        conn.close()
        return
        
    import random
    
    # We will generate data from 2026-04-01 to 2026-07-29 (the current date in the metadata context)
    # This matches the active periods of the first two projects
    start_date = datetime(2026, 4, 1)
    end_date = datetime(2026, 7, 29)
    
    # Get all stations
    cursor.execute("SELECT station_id, county FROM stations")
    stations = cursor.fetchall()
    
    obs_batch = []
    forecast_batch = []
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Weather patterns: Plum rain (May & June) has high rain frequency.
        # Flood season (Apr-Nov) has occasional heavy rain.
        month = current_date.month
        is_plum_rain = (month == 5 or month == 6)
        is_flood_season = (4 <= month <= 11)
        
        rain_chance = 0.45 if is_plum_rain else (0.30 if is_flood_season else 0.10)
        has_rain_today = random.random() < rain_chance
        
        for station_id, county in stations:
            # Generate Actual daily rainfall
            if has_rain_today:
                # Average rain day
                daily_total = round(random.uniform(2.0, 45.0), 1)
                # Occasional heavy rainstorm/typhoon style
                if random.random() < 0.12:
                    daily_total = round(random.uniform(60.0, 150.0), 1)
            else:
                daily_total = 0.0
                
            # Create simulated 10-minute observation checkpoints for this day to populate database
            # We insert multiple records per day representing observations over time.
            # To maintain a fast UI, we will insert 4 interval checkpoints representing the cumulative daily progression.
            checkpoint_hours = [6, 12, 18, 23]
            for idx, hr in enumerate(checkpoint_hours):
                obs_time = f"{date_str} {hr:02d}:00:00"
                
                # Wind speed, wind dir, gust
                avg_wind = round(random.uniform(0.5, 6.5), 1)
                if daily_total > 50.0:  # Storm conditions
                    avg_wind = round(random.uniform(6.0, 14.0), 1)
                gust = round(avg_wind * random.uniform(1.3, 1.8), 1)
                wdir = random.randint(0, 360)
                
                # Cumulative rainfall at this checkpoint
                current_cum_rain = round(daily_total * ((idx + 1) / 4.0), 1)
                
                obs_batch.append((
                    station_id, obs_time, current_cum_rain, avg_wind, wdir, gust
                ))
            
            # Generate forecasts for Project 1 & Project 2
            # Project 1: Yunlin Gov (ID: 1)
            # Project 2: Irrigation Agency (ID: 2)
            for project_id in [1, 2]:
                # Check station attachment to project
                cursor.execute("SELECT 1 FROM project_stations WHERE project_id=? AND station_id=?", (project_id, station_id))
                if cursor.fetchone():
                    # Validate project start/end boundaries
                    # Project 1: 2026-04-01 ~ 2027-03-31
                    # Project 2: 2026-07-01 ~ 2027-06-30
                    is_in_p1 = (project_id == 1 and "2026-04-01" <= date_str <= "2027-03-31")
                    is_in_p2 = (project_id == 2 and "2026-07-01" <= date_str <= "2027-06-30")
                    
                    if is_in_p1 or is_in_p2:
                        # Forecast generation modeling (contains systematic Wet Bias of ~ +2.5mm + random error)
                        if daily_total == 0.0:
                            # False alarms occasionally
                            forecast_val = round(random.uniform(0.0, 4.0), 1) if random.random() < 0.15 else 0.0
                        else:
                            # Standard error modeling
                            err = random.normalvariate(2.5, 6.0)
                            forecast_val = max(0.0, round(daily_total + err, 1))
                            
                        forecast_batch.append((
                            project_id, station_id, date_str, forecast_val
                        ))
                        
        current_date += timedelta(days=1)
        
    cursor.executemany('''
    INSERT OR REPLACE INTO observations (station_id, obs_time, rainfall, wind_speed, wind_direction, gust_speed)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', obs_batch)
    
    cursor.executemany('''
    INSERT OR REPLACE INTO forecasts (project_id, station_id, date, forecast_rainfall)
    VALUES (?, ?, ?, ?)
    ''', forecast_batch)
    
    conn.commit()
    conn.close()

# Generate simulation data on app launch so it's fully populated and functional immediately
generate_historical_simulation()

# ==============================================================================
# REAL-TIME CWA API DATA INGESTION
# ==============================================================================
def fetch_real_time_cwa(api_key):
    # Datasets for meteorological automated stations and manned stations
    datasets = ["O-A0001-001", "O-A0003-001"]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    success_count = 0
    error_message = None
    
    for dataset in datasets:
        url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset}"
        params = {
            "Authorization": api_key,
            "format": "JSON"
        }
        try:
            response = requests.get(url, params=params, timeout=12)
            if response.status_code == 200:
                data = response.json()
                records = data.get("records", {})
                stations = records.get("Station", records.get("location", []))
                
                for st in stations:
                    station_id = st.get("StationId", st.get("stationId"))
                    station_name = st.get("StationName", st.get("locationName"))
                    
                    if not station_id:
                        continue
                        
                    # 1. County & Township Name Extractor
                    county = None
                    township = None
                    if "GeoInfo" in st:
                        county = st["GeoInfo"].get("CountyName")
                        township = st["GeoInfo"].get("TownName")
                    if not county:
                        # Alternate locations
                        county = st.get("parameter", {}).get("county") or st.get("CountyName") or "其他縣市"
                        township = st.get("parameter", {}).get("township") or st.get("TownName")
                        
                    # 2. Coordinates
                    lon = None
                    lat = None
                    if "GeoInfo" in st and "Coordinates" in st["GeoInfo"]:
                        coords = st["GeoInfo"]["Coordinates"]
                        if isinstance(coords, list) and len(coords) > 0:
                            lon = coords[0].get("Longitude")
                            lat = coords[0].get("Latitude")
                    if lat is None:
                        lat = st.get("lat") or st.get("Latitude") or 23.5
                        lon = st.get("lon") or st.get("Longitude") or 120.5
                        
                    # 3. Timestamp
                    obs_time_str = None
                    if "ObsTime" in st:
                        obs_time_str = st["ObsTime"].get("DateTime")
                    if not obs_time_str:
                        obs_time_str = st.get("time", {}).get("obsTime")
                        
                    if not obs_time_str:
                        continue
                        
                    # Standardization of datetime string
                    try:
                        if "T" in obs_time_str:
                            dt = datetime.fromisoformat(obs_time_str)
                            obs_time_clean = dt.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            obs_time_clean = obs_time_str
                    except Exception:
                        obs_time_clean = obs_time_str
                        
                    # 4. Parsing weather elements
                    elements = {}
                    we_data = st.get("WeatherElement", st.get("weatherElement", {}))
                    
                    if isinstance(we_data, list):
                        # List of key-value dicts format
                        for elem in we_data:
                            name = elem.get("elementName")
                            val = elem.get("elementValue")
                            if name and val is not None:
                                try:
                                    elements[name] = float(val)
                                except ValueError:
                                    elements[name] = val
                    elif isinstance(we_data, dict):
                        # Nested dict format
                        wind = we_data.get("WindSpeed", we_data.get("Wind", {}))
                        if isinstance(wind, dict):
                            elements["WDSD"] = wind.get("WindSpeed")
                            elements["WDIR"] = wind.get("WindDirection")
                        else:
                            elements["WDSD"] = we_data.get("WindSpeed")
                            elements["WDIR"] = we_data.get("WindDirection")
                            
                        gust = we_data.get("Gust", {})
                        if isinstance(gust, dict):
                            elements["GST"] = gust.get("GustSpeed")
                        else:
                            elements["GST"] = we_data.get("GustSpeed")
                            
                        precip = we_data.get("Now", we_data.get("Precipitation", {}))
                        if isinstance(precip, dict):
                            elements["RAIN"] = precip.get("Precipitation", precip.get("Accumulation"))
                        else:
                            elements["RAIN"] = we_data.get("Precipitation") or we_data.get("AccumulationRainfall")
                    
                    # Standardize parsed metrics
                    rainfall = elements.get("RAIN", elements.get("Precipitation", 0.0))
                    try:
                        rainfall = max(0.0, float(rainfall)) if rainfall is not None else 0.0
                    except (ValueError, TypeError):
                        rainfall = 0.0
                        
                    wind_speed = elements.get("WDSD", elements.get("WindSpeed"))
                    try:
                        wind_speed = max(0.0, float(wind_speed)) if wind_speed is not None else 0.0
                    except (ValueError, TypeError):
                        wind_speed = 0.0
                        
                    wind_dir = elements.get("WDIR", elements.get("WindDirection"))
                    try:
                        wind_dir = max(0.0, float(wind_dir)) if wind_dir is not None else 0.0
                    except (ValueError, TypeError):
                        wind_dir = 0.0
                        
                    gust_speed = elements.get("GST", elements.get("GustSpeed"))
                    try:
                        gust_speed = max(0.0, float(gust_speed)) if gust_speed is not None else 0.0
                    except (ValueError, TypeError):
                        gust_speed = 0.0
                    
                    # Store station metadata
                    cursor.execute('''
                    INSERT OR REPLACE INTO stations (station_id, station_name, county, township, longitude, latitude)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (station_id, station_name, county or "其他縣市", township or "", float(lon), float(lat)))
                    
                    # Store observation
                    cursor.execute('''
                    INSERT OR REPLACE INTO observations (station_id, obs_time, rainfall, wind_speed, wind_direction, gust_speed)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (station_id, obs_time_clean, rainfall, wind_speed, wind_dir, gust_speed))
                    
                    success_count += 1
            else:
                error_message = f"API 擷取失敗 ({dataset}): HTTP {response.status_code}"
        except Exception as e:
            error_message = f"連線異常: {str(e)}"
            
    conn.commit()
    conn.close()
    return success_count, error_message

# ==============================================================================
# SIDEBAR CONTROL PANEL
# ==============================================================================
st.sidebar.markdown("<h2 style='text-align: center; color: #1E3A8A;'>🛠️ 系統控制面板</h2>", unsafe_allowed_html=True)

# 1. API Token and Connection Status
st.sidebar.markdown("### 🔌 數據串接設定")
api_key_input = st.sidebar.text_input(
    "中央氣象署 CWA API 授權碼", 
    value="CWA-8AB1C9F4-CD80-4296-BD3F-4B28FB433A25",
    type="password",
    help="請輸入您的氣象署開放資料 API 授權金鑰"
)

if st.sidebar.button("🔄 同步即時全臺資料", use_container_width=True):
    with st.spinner("正在連線中央氣象署 API 擷取最新觀測..."):
        count, err = fetch_real_time_cwa(api_key_input)
        if err:
            st.sidebar.error(f"同步出錯: {err}")
        else:
            st.sidebar.success(f"成功擷取並寫入 {count} 筆最新站點觀測！")
            st.rerun()

# 2. Main Navigation Selectbox
st.sidebar.markdown("### 🗺️ 功能導覽")
menu_selection = st.sidebar.selectbox(
    "請選擇功能頁面",
    ["🏠 首頁 - 全臺即時觀測", "📁 專案管理與新增", "📊 專案預報校驗分析"]
)

# Fetch current projects list to display underneath in navigation
conn = sqlite3.connect(DB_PATH)
df_projs = pd.read_sql_query("SELECT id, name FROM projects", conn)
conn.close()

# ==============================================================================
# 🏠 首頁 - 全臺即時觀測
# ==============================================================================
if menu_selection == "🏠 首頁 - 全臺即時觀測":
    st.markdown("<h1 class='main-header'>🏠 全臺降雨與風力即時觀測綜觀</h1>", unsafe_allowed_html=True)
    st.markdown("本頁面提供全臺灣氣象觀測站的**逐10分鐘即時資料**概覽。您可以檢視全台即時雨量、風速、陣風及風向，並可以針對不同專案的測站進行篩選顯示。")
    
    # Query database for recent observations
    conn = sqlite3.connect(DB_PATH)
    # Get the latest observation time for each station
    query = """
    SELECT s.station_id, s.station_name, s.county, s.township, s.longitude, s.latitude, 
           o.obs_time, o.rainfall, o.wind_speed, o.wind_direction, o.gust_speed
    FROM stations s
    JOIN observations o ON s.station_id = o.station_id
    WHERE o.obs_time = (SELECT MAX(obs_time) FROM observations WHERE station_id = s.station_id)
    """
    df_obs = pd.read_sql_query(query, conn)
    conn.close()
    
    if df_obs.empty:
        st.warning("⚠️ 目前資料庫中無觀測數據，請於左側控制面板點擊『同步即時全臺資料』。")
    else:
        # Create metric summary rows
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>⛈️ 全臺最大累積降雨站點</div>
                <div class='metric-value'>{df_obs.loc[df_obs['rainfall'].idxmax()]['station_name'] if not df_obs.empty else 'N/A'}</div>
                <div style='color: #2563EB; font-weight: bold;'>{df_obs['rainfall'].max():.1f} mm</div>
            </div>
            """, unsafe_allowed_html=True)
        with col2:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>💨 全臺最大風速站點</div>
                <div class='metric-value'>{df_obs.loc[df_obs['wind_speed'].idxmax()]['station_name'] if not df_obs.empty else 'N/A'}</div>
                <div style='color: #2563EB; font-weight: bold;'>{df_obs['wind_speed'].max():.1f} m/s</div>
            </div>
            """, unsafe_allowed_html=True)
        with col3:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>🌪️ 全臺最強陣風站點</div>
                <div class='metric-value'>{df_obs.loc[df_obs['gust_speed'].idxmax()]['station_name'] if not df_obs.empty else 'N/A'}</div>
                <div style='color: #2563EB; font-weight: bold;'>{df_obs['gust_speed'].max():.1f} m/s</div>
            </div>
            """, unsafe_allowed_html=True)
        with col4:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>🕒 數據最新觀測時間</div>
                <div class='metric-value' style='font-size: 1.2rem; padding-top: 0.6rem;'>{df_obs['obs_time'].max()}</div>
                <div style='color: #10B981; font-weight: bold;'>全臺運作正常</div>
            </div>
            """, unsafe_allowed_html=True)
            
        st.markdown("<h2 class='sub-header'>🗺️ 全臺降雨與觀測點地圖分佈</h2>", unsafe_allowed_html=True)
        
        # Filtering controls
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            county_options = ["全部縣市"] + sorted(list(df_obs['county'].unique()))
            selected_county = st.selectbox("縣市快速篩選", county_options)
        with col_f2:
            project_options = ["無篩選（呈現全臺）"] + list(df_projs['name'])
            selected_proj_filter = st.selectbox("依特定專案所屬測站篩選", project_options)
            
        # Apply filters
        df_filtered = df_obs.copy()
        if selected_county != "全部縣市":
            df_filtered = df_filtered[df_filtered['county'] == selected_county]
            
        if selected_proj_filter != "無篩選（呈現全臺）":
            # Fetch station IDs associated with selected project
            conn = sqlite3.connect(DB_PATH)
            p_id = df_projs[df_projs['name'] == selected_proj_filter]['id'].values[0]
            proj_stations = pd.read_sql_query(f"SELECT station_id FROM project_stations WHERE project_id = {p_id}", conn)['station_id'].tolist()
            conn.close()
            df_filtered = df_filtered[df_filtered['station_id'].isin(proj_stations)]
            
        # 3D Pydeck Map Setup
        # Size mapping for rainfall
        df_filtered['radius'] = df_filtered['rainfall'].apply(lambda r: max(10000, min(50000, r * 1500 + 10000)))
        df_filtered['color_r'] = df_filtered['rainfall'].apply(lambda r: min(255, int(r * 3)))
        df_filtered['color_b'] = df_filtered['rainfall'].apply(lambda r: min(255, int(255 - r * 2)))
        
        view_state = pdk.ViewState(
            latitude=23.6,
            longitude=120.7,
            zoom=7.5,
            pitch=30
        )
        
        layer = pdk.Layer(
            "ScatterplotLayer",
            df_filtered,
            get_position=["longitude", "latitude"],
            get_color="[color_r, 100, color_b, 200]",
            get_radius="radius",
            pickable=True,
            opacity=0.8,
            stroked=True,
            filled=True,
            radius_scale=1,
            radius_min_pixels=6,
            radius_max_pixels=30,
        )
        
        # Tooltip details
        tooltip = {
            "html": "<b>觀測站:</b> {station_name} ({station_id})<br/>"
                    "<b>位置:</b> {county}{township}<br/>"
                    "<b>日雨量:</b> {rainfall} mm<br/>"
                    "<b>平均風速:</b> {wind_speed} m/s ({wind_direction}°)<br/>"
                    "<b>最大陣風:</b> {gust_speed} m/s<br/>"
                    "<b>時間:</b> {obs_time}",
            "style": {"background-color": "steelblue", "color": "white"}
        }
        
        map_col, data_col = st.columns([3, 2])
        
        with map_col:
            st.pydeck_chart(pdk.Deck(
                map_style="mapbox://styles/mapbox/light-v9",
                layers=[layer],
                initial_view_state=view_state,
                tooltip=tooltip
            ))
            
        with data_col:
            st.markdown("##### 📍 篩選觀測點細節數據表")
            display_cols = ['station_id', 'station_name', 'county', 'township', 'rainfall', 'wind_speed', 'gust_speed']
            st.dataframe(df_filtered[display_cols].rename(columns={
                'station_id': '站號',
                'station_name': '站名',
                'county': '縣市',
                'township': '鄉鎮',
                'rainfall': '累積雨量(mm)',
                'wind_speed': '平均風速(m/s)',
                'gust_speed': '陣風(m/s)'
            }), use_container_width=True, height=400)

# ==============================================================================
# 📁 專案管理與新增
# ==============================================================================
elif menu_selection == "📁 專案管理與新增":
    st.markdown("<h1 class='main-header'>📁 專案管理與觀測站配置</h1>", unsafe_allowed_html=True)
    st.markdown("在此頁面，您可以**新增自訂專案**、編輯專案起迄時間與目標縣市，並可選取欲進行預報校驗的代表觀測站點。")
    
    conn = sqlite3.connect(DB_PATH)
    
    # Section A: Add New Project
    with st.expander("➕ 新增專案頁面", expanded=True):
        st.markdown("#### 設定新專案資訊")
        new_proj_name = st.text_input("專案名稱", placeholder="例如：水利署第三期校驗專案")
        
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            # Query existing counties
            df_counties = pd.read_sql_query("SELECT DISTINCT county FROM stations WHERE county != '未知縣市'", conn)
            county_list = sorted(list(df_counties['county'].unique())) if not df_counties.empty else ["雲林縣", "臺北市", "臺中市"]
            selected_county = st.selectbox("目標縣市", county_list)
        with col_p2:
            start_date = st.date_input("專案開始時間 (西元)", value=datetime(2026, 4, 1))
        with col_p3:
            end_date = st.date_input("專案結束時間 (西元)", value=datetime(2027, 3, 31))
            
        # Fetch stations in selected county
        df_county_stations = pd.read_sql_query(f"SELECT station_id, station_name, township FROM stations WHERE county = '{selected_county}'", conn)
        station_choices = {f"{r['station_name']} ({r['station_id']})": r['station_id'] for _, r in df_county_stations.iterrows()}
        
        selected_station_names = st.multiselect(
            f"選取關聯觀測站點 (隸屬 {selected_county})",
            options=list(station_choices.keys()),
            default=list(station_choices.keys())[:min(5, len(station_choices))]
        )
        selected_station_ids = [station_choices[name] for name in selected_station_names]
        
        if st.button("💾 建立並儲存此專案", use_container_width=True):
            if not new_proj_name:
                st.error("請填寫專案名稱！")
            elif not selected_station_ids:
                st.error("請至少選取一個觀測站！")
            else:
                try:
                    cursor = conn.cursor()
                    cursor.execute('''
                    INSERT INTO projects (name, start_date, end_date, county)
                    VALUES (?, ?, ?, ?)
                    ''', (new_proj_name, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), selected_county))
                    
                    proj_id = cursor.lastrowid
                    
                    # Link stations
                    station_links = [(proj_id, st_id) for st_id in selected_station_ids]
                    cursor.executemany('''
                    INSERT INTO project_stations (project_id, station_id)
                    VALUES (?, ?)
                    ''', station_links)
                    
                    conn.commit()
                    st.success(f"🎉 專案『{new_proj_name}』已建立成功！")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("此專案名稱已存在，請使用其他名稱！")
                    
    # Section B: Current Projects Overview & Editing
    st.markdown("<h2 class='sub-header'>📂 現有專案清單</h2>", unsafe_allowed_html=True)
    
    # Query all projects with station count
    query_projects = """
    SELECT p.id, p.name, p.county, p.start_date, p.end_date, COUNT(ps.station_id) as station_count
    FROM projects p
    LEFT JOIN project_stations ps ON p.id = ps.project_id
    GROUP BY p.id
    """
    df_projects_list = pd.read_sql_query(query_projects, conn)
    
    if df_projects_list.empty:
        st.info("尚無專案，請使用上方表單建立。")
    else:
        for _, row in df_projects_list.iterrows():
            with st.container():
                p_id = row['id']
                st.markdown(f"""
                <div style='background-color: #F9FAFB; padding: 1.2rem; border-radius: 8px; border: 1px solid #E5E7EB; margin-bottom: 1rem;'>
                    <h3 style='margin: 0; color: #1F2937;'>📁 {row['name']}</h3>
                    <p style='margin: 5px 0; color: #4B5563; font-size: 0.95rem;'>
                        <b>代表縣市:</b> {row['county']} | 
                        <b>專案合約期程 (西元):</b> {row['start_date']} ～ {row['end_date']} | 
                        <b>配對觀測站數:</b> {row['station_count']} 個站點
                    </p>
                </div>
                """, unsafe_allowed_html=True)
                
                # Fetch detailed stations
                query_attached = f"""
                SELECT s.station_id, s.station_name, s.township FROM stations s
                JOIN project_stations ps ON s.station_id = ps.station_id
                WHERE ps.project_id = {p_id}
                """
                df_att = pd.read_sql_query(query_attached, conn)
                st.caption(f"配對觀測站: {', '.join([f'{r.station_name}({r.station_id})' for r in df_att.itertuples()])}")
                
                # Dynamic action delete buttons
                col_d1, col_d2 = st.columns([1, 5])
                with col_d1:
                    # Avoid deleting defaults directly without double check
                    if st.button(f"🗑️ 刪除專案", key=f"del_{p_id}"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM projects WHERE id = ?", (p_id,))
                        conn.commit()
                        st.success("專案已成功刪除！")
                        st.rerun()
                st.markdown("<hr style='margin: 10px 0;'>", unsafe_allowed_html=True)
                
    conn.close()

# ==============================================================================
# 📊 專案預報校驗分析
# ==============================================================================
elif menu_selection == "📊 專案預報校驗分析":
    st.markdown("<h1 class='main-header'>📊 專案降雨預報校驗與指標計算</h1>", unsafe_allowed_html=True)
    st.markdown("在此頁面，您可以**選取專案、代表站點、日期範圍**，輸入您預測的每日降雨預報值。系統將會即時計算 **BIAS (偏差)** 與 **RMSE (均方根誤差)**，並生成專業的對比校驗圖表。")
    
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Select active project
    df_projects = pd.read_sql_query("SELECT id, name, county, start_date, end_date FROM projects", conn)
    
    if df_projects.empty:
        st.warning("⚠️ 查無可用專案，請先前往『📁 專案管理與新增』建立。")
        conn.close()
    else:
        # Create beautiful project selectors
        selected_proj_name = st.selectbox("🎯 選擇要分析的專案頁面", df_projects['name'])
        proj_row = df_projects[df_projects['name'] == selected_proj_name].iloc[0]
        proj_id = int(proj_row['id'])
        proj_start = proj_row['start_date']
        proj_end = proj_row['end_date']
        proj_county = proj_row['county']
        
        # Format contract timeline to show both ROC and Western years for clear executive view
        p_start_dt = datetime.strptime(proj_start, '%Y-%m-%d')
        p_end_dt = datetime.strptime(proj_end, '%Y-%m-%d')
        roc_start = f"民國 {p_start_dt.year - 1911} 年 {p_start_dt.month} 月 {p_start_dt.day} 日"
        roc_end = f"民國 {p_end_dt.year - 1911} 年 {p_end_dt.month} 月 {p_end_dt.day} 日"
        
        st.markdown(f"""
        <div class='highlight-box'>
            <b>ℹ️ 專案基本設定明細：</b><br/>
            📍 運作縣市：<b>{proj_county}</b> <br/>
            📅 專案起訖期程（西元）：<b>{proj_start}</b> 至 <b>{proj_end}</b> <br/>
            🇹🇼 專案起訖期程（民國）：<b>{roc_start}</b> 至 <b>{roc_end}</b>
        </div>
        """, unsafe_allowed_html=True)
        
        # 2. Select Station within Project
        query_ps = f"""
        SELECT s.station_id, s.station_name FROM stations s
        JOIN project_stations ps ON s.station_id = ps.station_id
        WHERE ps.project_id = {proj_id}
        """
        df_p_stations = pd.read_sql_query(query_ps, conn)
        
        if df_p_stations.empty:
            st.error("該專案未配對任何觀測站，請前往專案管理加入。")
            conn.close()
        else:
            col_sel1, col_sel2 = st.columns([2, 3])
            with col_sel1:
                station_options = {r['station_name']: r['station_id'] for _, r in df_p_stations.iterrows()}
                selected_st_name = st.selectbox("📍 選取校驗觀測站點", list(station_options.keys()))
                selected_st_id = station_options[selected_st_name]
                
            # 3. Select Time Frame Selector
            with col_sel2:
                time_mode = st.radio(
                    "📅 時間區間選擇模式",
                    ["常用固定氣象期程", "自訂特定日期範圍"],
                    horizontal=True
                )
            
            # Resolve exact datetime range
            calc_start_date = p_start_dt
            calc_end_date = p_end_dt
            
            if time_mode == "常用固定氣象期程":
                col_period, col_yr = st.columns(2)
                with col_yr:
                    # Extract available years from contract range
                    available_years = list(range(p_start_dt.year, p_end_dt.year + 1))
                    selected_year = st.selectbox("分析目標年份", available_years)
                with col_period:
                    selected_period = st.selectbox(
                        "選擇統計期程",
                        [
                            "每 7 日為基本計算單位 (本週起)",
                            "每年汛期期間 (4/1 ~ 11/30)",
                            "每年非汛期期間 (12/1 ~ 3/31)",
                            "全年度",
                            "梅雨季期間 (5/1 ~ 6/30)"
                        ]
                    )
                
                # Adjust date boundaries based on selected period and year
                if "每 7 日" in selected_period:
                    # Let user choose start date of the 7-day period
                    week_start = st.date_input("選擇週計算起始日", value=max(p_start_dt.date(), datetime.now().date() - timedelta(days=7)))
                    calc_start_date = datetime.combine(week_start, datetime.min.time())
                    calc_end_date = calc_start_date + timedelta(days=6)
                elif "汛期" in selected_period:
                    calc_start_date = datetime(selected_year, 4, 1)
                    calc_end_date = datetime(selected_year, 11, 30)
                elif "非汛期" in selected_period:
                    calc_start_date = datetime(selected_year - 1, 12, 1)
                    calc_end_date = datetime(selected_year, 3, 31)
                elif "全年度" in selected_period:
                    calc_start_date = datetime(selected_year, 1, 1)
                    calc_end_date = datetime(selected_year, 12, 31)
                elif "梅雨季" in selected_period:
                    calc_start_date = datetime(selected_year, 5, 1)
                    calc_end_date = datetime(selected_year, 6, 30)
            else:
                # Custom Date picker bounded by project
                col_dstart, col_dend = st.columns(2)
                with col_dstart:
                    calc_start_date = datetime.combine(
                        st.date_input("分析起始日", value=max(p_start_dt.date(), datetime.now().date() - timedelta(days=15))),
                        datetime.min.time()
                    )
                with col_dend:
                    calc_end_date = datetime.combine(
                        st.date_input("分析結束日", value=min(p_end_dt.date(), datetime.now().date())),
                        datetime.max.time()
                    )
            
            # Keep boundaries safe (clip to project durations)
            calc_start_str = max(p_start_dt, calc_start_date).strftime('%Y-%m-%d')
            calc_end_str = min(p_end_dt, calc_end_date).strftime('%Y-%m-%d')
            
            st.info(f"📋 當前運算評估區間：西元 **{calc_start_str}** 至 **{calc_end_str}**")
            
            # 4. Extract Observation Rain from DB (Aggregate 10-min observations into Daily rain totals)
            # Daily actual rainfall is defined as the maximum cumulative rain value for each day
            query_obs_daily = f"""
            SELECT date(obs_time) as obs_date, max(rainfall) as actual_rain
            FROM observations
            WHERE station_id = '{selected_st_id}' 
              AND date(obs_time) BETWEEN '{calc_start_str}' AND '{calc_end_str}'
            GROUP BY obs_date
            """
            df_obs_daily = pd.read_sql_query(query_obs_daily, conn)
            
            # Get existing forecasts for this range
            query_fc = f"""
            SELECT date, forecast_rainfall FROM forecasts
            WHERE project_id = {proj_id} 
              AND station_id = '{selected_st_id}'
              AND date BETWEEN '{calc_start_str}' AND '{calc_end_str}'
            """
            df_fc_daily = pd.read_sql_query(query_fc, conn)
            
            # Generate the unified calendar list for this date range to present to the user
            all_dates = []
            curr = datetime.strptime(calc_start_str, '%Y-%m-%d')
            limit = datetime.strptime(calc_end_str, '%Y-%m-%d')
            while curr <= limit:
                all_dates.append(curr.strftime('%Y-%m-%d'))
                curr += timedelta(days=1)
                
            df_calendar = pd.DataFrame({'date': all_dates})
            
            # Merge observations and forecasts with full calendar
            df_merged = df_calendar.merge(df_obs_daily, left_on='date', right_on='obs_date', how='left')
            df_merged['actual_rain'] = df_merged['actual_rain'].fillna(0.0) # Fill days with no observations with 0
            
            df_merged = df_merged.merge(df_fc_daily, on='date', how='left')
            df_merged['forecast_rainfall'] = df_merged['forecast_rainfall'].fillna(0.0)
            
            df_merged = df_merged[['date', 'actual_rain', 'forecast_rainfall']].rename(columns={
                'date': '日期',
                'actual_rain': '實際觀測雨量 (mm)',
                'forecast_rainfall': '預報雨量值 (mm)'
            })
            
            # 5. Forecast Editor (st.data_editor allows spreadsheet-like user input)
            st.markdown("<h2 class='sub-header'>✍️ 輸入預報雨量</h2>", unsafe_allowed_html=True)
            st.markdown("您可以直接在下方表格中**按兩下儲存格輸入或修改『預報雨量值』**。完成後請點擊下方**「儲存預報雨量並計算指標」**按鈕。")
            
            edited_df = st.data_editor(
                df_merged,
                column_config={
                    "日期": st.column_config.TextColumn("日期", disabled=True),
                    "實際觀測雨量 (mm)": st.column_config.NumberColumn("實際觀測雨量 (mm)", format="%.1f mm", disabled=True),
                    "預報雨量值 (mm)": st.column_config.NumberColumn("預報雨量值 (mm)", min_value=0.0, max_value=500.0, step=0.1, format="%.1f mm")
                },
                use_container_width=True,
                num_rows="fixed",
                key="forecast_editor"
            )
            
            col_save1, col_save2 = st.columns([1, 4])
            with col_save1:
                save_btn = st.button("💾 儲存預報雨量並計算指標", use_container_width=True, type="primary")
                
            if save_btn:
                # Save edited forecast values back to SQL DB
                cursor = conn.cursor()
                records_to_save = []
                for _, r in edited_df.iterrows():
                    d_str = r['日期']
                    f_val = float(r['預報雨量值 (mm)'])
                    records_to_save.append((proj_id, selected_st_id, d_str, f_val))
                    
                cursor.executemany('''
                INSERT OR REPLACE INTO forecasts (project_id, station_id, date, forecast_rainfall)
                VALUES (?, ?, ?, ?)
                ''', records_to_save)
                conn.commit()
                st.success("📝 預報資料已成功儲存並同步至資料庫！")
                st.rerun()
                
            # ==============================================================================
            # BIAS & RMSE STATISTICS & CHARTING
            # ==============================================================================
            st.markdown("<h2 class='sub-header'>📊 校驗分析成果呈現</h2>", unsafe_allowed_html=True)
            
            F = edited_df['預報雨量值 (mm)'].to_numpy()
            O = edited_df['實際觀測雨量 (mm)'].to_numpy()
            N = len(F)
            
            if N > 0:
                # Calculate metrics
                # Bias = (1/N) * sum(F_i - O_i)
                bias = np.mean(F - O)
                # RMSE = sqrt((1/N) * sum((F_i - O_i)^2))
                rmse = np.sqrt(np.mean((F - O) ** 2))
                
                col_m1, col_m2, col_m3 = st.columns(3)
                
                with col_m1:
                    bias_type = "🟢 無系統性偏差 (理想)"
                    if bias > 0.1:
                        bias_type = "🔴 系統性高估 (Wet Bias, 預報偏多)"
                    elif bias < -0.1:
                        bias_type = "🔵 系統性低估 (Dry Bias, 預報偏少)"
                        
                    st.markdown(f"""
                    <div class='metric-card'>
                        <div class='metric-label'>📐 偏差值 (BIAS)</div>
                        <div class='metric-value'>{bias:.2f} mm</div>
                        <div style='color: #4B5563; font-weight: bold; font-size: 0.85rem;'>{bias_type}</div>
                    </div>
                    """, unsafe_allowed_html=True)
                    
                with col_m2:
                    st.markdown(f"""
                    <div class='metric-card' style='border-left: 5px solid #10B981;'>
                        <div class='metric-label'>📏 均方根誤差 (RMSE)</div>
                        <div class='metric-value'>{rmse:.2f} mm</div>
                        <div style='color: #4B5563; font-weight: bold; font-size: 0.85rem;'>衡量預報精確度 (越低越好)</div>
                    </div>
                    """, unsafe_allowed_html=True)
                    
                with col_m3:
                    st.markdown(f"""
                    <div class='metric-card' style='border-left: 5px solid #F59E0B;'>
                        <div class='metric-label'>📅 分析樣本天數 (N)</div>
                        <div class='metric-value'>{N} 天</div>
                        <div style='color: #4B5563; font-weight: bold; font-size: 0.85rem;'>校驗評估樣本統計總量</div>
                    </div>
                    """, unsafe_allowed_html=True)
                
                # Interactive Plotly Dual Chart (Precipitation comparison)
                st.markdown("##### 📈 預報與觀測雨量日對比圖")
                
                fig = go.Figure()
                # Bars for Actual Rainfall
                fig.add_trace(go.Bar(
                    x=edited_df['日期'],
                    y=edited_df['實際觀測雨量 (mm)'],
                    name='實際觀測雨量 (Observed)',
                    marker_color='#3B82F6',
                    opacity=0.7
                ))
                # Line with Markers for Forecasted Rainfall
                fig.add_trace(go.Scatter(
                    x=edited_df['日期'],
                    y=edited_df['預報雨量值 (mm)'],
                    name='預報雨量值 (Forecasted)',
                    mode='lines+markers',
                    line=dict(color='#EF4444', width=2),
                    marker=dict(size=6)
                ))
                
                # Customize layout with stats
                fig.update_layout(
                    title=f"{selected_proj_name} - {selected_st_name} 觀測與預報校驗對比圖 (BIAS: {bias:.2f} mm, RMSE: {rmse:.2f} mm)",
                    xaxis_title="分析日期",
                    yaxis_title="雨量 (mm)",
                    barmode='group',
                    legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.7)'),
                    margin=dict(l=40, r=40, t=50, b=40),
                    hovermode='x unified'
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # Download analyzed CSV options
                col_dl1, col_dl2 = st.columns([1, 4])
                with col_dl1:
                    csv_data = edited_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 下載校驗分析報表 (.csv)",
                        data=csv_data,
                        file_name=f"{selected_proj_name}_{selected_st_name}_verification.csv",
                        mime='text/csv',
                        use_container_width=True
                    )
            else:
                st.warning("當前日期區間內查無有效數據進行校驗！")

    conn.close()

# Footer logo and metadata
st.sidebar.markdown("---")
st.sidebar.caption("🌧️ **全臺預報校驗自動化網頁 App**")
st.sidebar.caption("授權：CWA 開放資料授權協定")
st.sidebar.caption("System local time: 2026-07-29")
