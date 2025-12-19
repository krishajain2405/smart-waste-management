import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETTINGS ---
st.set_page_config(page_title="Smart Waste AI Mission Control", layout="wide")

GARAGES = {
    "Truck 1 (Worli)": (19.0178, 72.8478),
    "Truck 2 (Bandra)": (19.0596, 72.8295),
    "Truck 3 (Andheri)": (19.1136, 72.8697),
    "Truck 4 (Kurla)": (19.0726, 72.8844),
    "Truck 5 (Borivali)": (19.2307, 72.8567)
}
DEONAR_DUMPING = (19.0550, 72.9250)

@st.cache_data
def load_data():
    all_files = [f for f in os.listdir('.') if f.endswith('.csv')]
    target = 'data.csv' if 'data.csv' in all_files else (all_files[0] if all_files else None)
    if not target: return None
    try:
        df = pd.read_csv(target, sep=None, engine='python', encoding='utf-8-sig')
        df.columns = [c.strip().lower() for c in df.columns]
        
        # --- THE FIX: Standardize BIN_ID and others ---
        rename_dict = {
            'bin_location_lat': 'lat', 'bin_location_lon': 'lon',
            'bin_fill_percent': 'fill', 'timestamp': 'timestamp',
            'bin_id': 'bin_id', 'bin id': 'bin_id', 'id': 'bin_id'
        }
        for old, new in rename_dict.items():
            for col in df.columns:
                if old == col:
                    df = df.rename(columns={col: new})
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        return df.dropna(subset=['timestamp'])
    except: return None

def get_dist(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5

@st.cache_resource
def get_map():
    return ox.graph_from_point((19.0760, 72.8777), dist=8000, network_type='drive')

# --- 2. EXECUTION ---
st.title("🚛 AI Multi-Fleet Mission Control")
df = load_data()

if df is not None:
    # Sidebar
    st.sidebar.header("🕹️ Dispatch Controls")
    selected_truck = st.sidebar.selectbox("Select Active Truck", list(GARAGES.keys()))
    threshold = st.sidebar.slider("Fill Threshold (%)", 0, 100, 75)
    
    # Simulation Slider
    times = sorted(df['timestamp'].unique())
    default_time = times[int(len(times)*0.85)]
    sim_time = st.sidebar.select_slider("Select Time", options=times, value=default_time)
    
    df_snap = df[df['timestamp'] == sim_time].copy()

    # Assignment logic
    def assign_truck(row):
        loc = (row['lat'], row['lon'])
        dists = {name: get_dist(loc, coords) for name, coords in GARAGES.items()}
        return min(dists, key=dists.get)

    df_snap['assigned_truck'] = df_snap.apply(assign_truck, axis=1)
    
    # Filter bins for selected truck
    all_my_bins = df_snap[(df_snap['assigned_truck'] == selected_truck) & (df_snap['fill'] >= threshold)]
    all_my_bins = all_my_bins.sort_values('fill', ascending=False)

    # Multi-Trip Pipeline
    st.sidebar.markdown("---")
    st.sidebar.subheader("📦 Trip Pipeline")
    bins_per_trip = 8
    total_pending = len(all_my_bins)
    num_trips = (total_pending // bins_per_trip) + (1 if total_pending % bins_per_trip > 0 else 0)
    
    if num_trips > 0:
        trip_num = st.sidebar.selectbox(f"Select Trip (Total: {num_trips})", 
                                        range(1, num_trips + 1), 
                                        format_func=lambda x: f"Trip {x}")
        start_idx = (trip_num - 1) * bins_per_trip
        current_mission_bins = all_my_bins.iloc[start_idx : start_idx + bins_per_trip]
    else:
        current_mission_bins = pd.DataFrame()

    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Vehicle", selected_truck)
    c2.metric("Total Bins for Truck", total_pending)
    c3.metric("Current Trip Stops", len(current_mission_bins))

    # --- 3. MAP ---
    try:
        G = get_map()
        m = folium.Map(location=[19.0760, 72.8777], zoom_start=12, tiles="CartoDB positron")

        # Plot Bins
        for _, row in df_snap.iterrows():
            is_full = row['fill'] >= threshold
            is_mine = row['assigned_truck'] == selected_truck
            
            # Check if this bin is in the current trip (handle missing bin_id gracefully)
            is_in_current = False
            if not current_mission_bins.empty and 'bin_id' in row:
                is_in_current = row['bin_id'] in current_mission_bins['bin_id'].values
            
            if is_full and is_mine and is_in_current: color = 'red'
            elif is_full and is_mine and not is_in_current: color = 'blue'
            elif is_full and not is_mine: color = 'orange'
            else: color = 'green'
            
            folium.Marker([row['lat'], row['lon']], 
                          icon=folium.Icon(color=color, icon='trash', prefix='fa')).add_to(m)

        # Draw Current Route
        garage_loc = GARAGES[selected_truck]
        if not current_mission_bins.empty:
            pts = [garage_loc] + list(zip(current_mission_bins['lat'], current_mission_bins['lon'])) + [DEONAR_DUMPING]
            path_coords = []
            for i in range(len(pts)-1):
                try:
                    n1 = ox.nearest_nodes(G, pts[i][1], pts[i][0])
                    n2 = ox.nearest_nodes(G, pts[i+1][1], pts[i+1][0])
                    route = nx.shortest_path(G, n1, n2, weight='length')
                    path_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in route])
                except:
                    path_coords.append([pts[i][0], pts[i][1]])
                    path_coords.append([pts[i+1][0], pts[i+1][1]])
            
            if path_coords:
                folium.PolyLine(path_coords, color="#3498db", weight=6, opacity=0.8).add_to(m)

        folium.Marker(garage_loc, icon=folium.Icon(color='blue', icon='truck', prefix='fa')).add_to(m)
        folium.Marker(DEONAR_DUMPING, icon=folium.Icon(color='black', icon='home', prefix='fa')).add_to(m)

        st_folium(m, width=1200, height=550, key="mission_map")

        # --- 4. QR CODE ---
        if not current_mission_bins.empty:
            st.subheader(f"📲 Driver QR: Trip {trip_num}")
            google_url = f"https://www.google.com/maps/dir/?api=1&origin={garage_loc[0]},{garage_loc[1]}&destination={DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}&waypoints=" + "|".join([f"{lat},{lon}" for lat, lon in zip(current_mission_bins['lat'], current_mission_bins['lon'])]) + "&travelmode=driving"
            
            q_col, t_col = st.columns([1, 4])
            with q_col:
                qr = qrcode.make(google_url)
                buf = BytesIO()
                qr.save(buf)
                st.image(buf, width=200)
            with t_col:
                st.success(f"Trip {trip_num} ready for Driver Dispatch.")
                st.info("The Blue markers on the map represent the bins queued for the next trip!")

    except Exception as e:
        st.error(f"Mapping Error: {e}")
else:
    st.error("Missing Data: Please ensure 'data.csv' is uploaded.")
