import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETTINGS & MUNICIPAL HUBS ---
st.set_page_config(page_title="Smart Waste AI: Mission Pipeline", layout="wide")

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
        # Detects commas vs semicolons automatically
        df = pd.read_csv(target, sep=None, engine='python', encoding='utf-8-sig')
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.rename(columns={
            'bin_location_lat': 'lat', 'bin_location_lon': 'lon',
            'bin_fill_percent': 'fill', 'timestamp': 'timestamp'
        })
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        return df.dropna(subset=['timestamp'])
    except: return None

def get_dist(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5

@st.cache_resource
def get_map():
    # Cache Mumbai Road Network
    return ox.graph_from_point((19.0760, 72.8777), dist=9000, network_type='drive')

# --- 2. EXECUTION ---
st.title("🚛 AI Fleet Mission Control: Multi-Trip Dispatcher")
df = load_data()

if df is not None:
    # --- SIDEBAR CONTROLS ---
    st.sidebar.header("🕹️ Dispatch Controls")
    selected_truck = st.sidebar.selectbox("Select Active Truck", list(GARAGES.keys()))
    threshold = st.sidebar.slider("Urgency Threshold (Fill %)", 0, 100, 75)
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Simulation Clock")
    times = sorted(df['timestamp'].unique())
    default_time = times[int(len(times)*0.85)]
    sim_time = st.sidebar.select_slider("Select Time", options=times, value=default_time)
    
    # 1. Filter Data for selected time
    df_snap = df[df['timestamp'] == sim_time].copy()

    # 2. ASSIGNMENT LOGIC (Decision Engine)
    def assign_to_nearest(row):
        loc = (row['lat'], row['lon'])
        dists = {name: get_dist(loc, coords) for name, coords in GARAGES.items()}
        return min(dists, key=dists.get)

    df_snap['assigned_truck'] = df_snap.apply(assign_to_nearest, axis=1)
    
    # All bins assigned to the selected truck that are full
    all_my_bins = df_snap[(df_snap['assigned_truck'] == selected_truck) & (df_snap['fill'] >= threshold)]
    all_my_bins = all_my_bins.sort_values('fill', ascending=False)

    # --- THE PIPELINE LOGIC (NEW FEATURE) ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("📦 Trip Pipeline")
    bins_per_trip = 8
    total_bins = len(all_my_bins)
    num_trips = (total_bins // bins_per_trip) + (1 if total_bins % bins_per_trip > 0 else 0)
    
    if num_trips > 0:
        trip_num = st.sidebar.selectbox(f"Select Trip (Total: {num_trips})", 
                                        range(1, num_trips + 1), 
                                        format_func=lambda x: f"Trip {x}")
        
        # Select the slice of bins for this trip
        start_idx = (trip_num - 1) * bins_per_trip
        end_idx = start_idx + bins_per_trip
        current_mission_bins = all_my_bins.iloc[start_idx:end_idx]
    else:
        current_mission_bins = pd.DataFrame()
        st.sidebar.info("No trips needed.")

    # Dashboard Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Active Vehicle", selected_truck)
    c2.metric("Total Pending Bins", total_bins)
    c3.metric("Current Trip Pickups", len(current_mission_bins))

    # --- 3. MAP ---
    try:
        G = get_map()
        m = folium.Map(location=[19.0760, 72.8777], zoom_start=12, tiles="CartoDB positron")

        # Plot all bins (Visual Logic)
        for _, row in df_snap.iterrows():
            is_full = row['fill'] >= threshold
            is_mine = row['assigned_truck'] == selected_truck
            is_in_current_trip = row['bin_id'] in current_mission_bins['bin_id'].values
            
            # RED: My current trip pickups
            # BLUE: My future trip pickups
            # ORANGE: Other truck's pickups
            # GREEN: Safe
            if is_full and is_mine and is_in_current_trip: color = 'red'
            elif is_full and is_mine and not is_in_current_trip: color = 'blue'
            elif is_full and not is_mine: color = 'orange'
            else: color = 'green'
            
            folium.Marker([row['lat'], row['lon']], 
                          popup=f"Bin {row['bin_id']}: {row['fill']}%",
                          icon=folium.Icon(color=color, icon='trash', prefix='fa')).add_to(m)

        # Draw the Route for the CURRENT TRIP ONLY
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

        # Fixed Markers
        folium.Marker(garage_loc, popup="Active Garage", icon=folium.Icon(color='blue', icon='truck', prefix='fa')).add_to(m)
        folium.Marker(DEONAR_DUMPING, popup="Deonar Disposal", icon=folium.Icon(color='black', icon='home', prefix='fa')).add_to(m)

        st_folium(m, width=1200, height=550, key="mission_map")

        # --- 4. QR CODE ---
        if not current_mission_bins.empty:
            st.subheader(f"📲 Driver manifest for {selected_truck} - Trip {trip_num}")
            
            google_url = f"https://www.google.com/maps/dir/?api=1&origin={garage_loc[0]},{garage_loc[1]}&destination={DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}&waypoints=" + "|".join([f"{lat},{lon}" for lat, lon in zip(current_mission_bins['lat'], current_mission_bins['lon'])])
            
            q_col, t_col = st.columns([1, 4])
            with q_col:
                qr = qrcode.make(google_url)
                buf = BytesIO()
                qr.save(buf)
                st.image(buf, width=200)
            with t_col:
                st.success(f"Trip {trip_num} calculated. Optimized for vehicle capacity.")
                st.info("💡 **Demo Secret:** Move the 'Trip' selector in the sidebar to show how the driver receives their next assignment after emptying at Deonar!")

    except Exception as e:
        st.error(f"Mapping System Error: {e}")
else:
    st.error("Missing Data: Please upload 'data.csv'.")
