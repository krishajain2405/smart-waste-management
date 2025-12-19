import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETUP ---
st.set_page_config(page_title="Evergreen Smart Waste AI", layout="wide")

GARAGES = {
    "Truck 1 (Worli)": (19.0178, 72.8478),
    "Truck 2 (Bandra)": (19.0596, 72.8295),
    "Truck 3 (Andheri)": (19.1136, 72.8697),
    "Truck 4 (Kurla)": (19.0726, 72.8844),
    "Truck 5 (Borivali)": (19.2307, 72.8567)
}
DEONAR_DUMPING = (19.0550, 72.9250)

@st.cache_data
def load_and_clean_data():
    # MENTOR TIP: This loop searches for your file regardless of the name!
    target = None
    all_files = [f for f in os.listdir('.') if f.endswith('.csv')]
    if 'data.csv' in all_files:
        target = 'data.csv'
    elif all_files:
        target = all_files[0] # Just take the first CSV it finds
    
    if target is None:
        return None

    try:
        df = pd.read_csv(target)
        # Force clean column names to prevent 'timestamp' errors
        df.columns = df.columns.str.strip().str.lower()
        
        # Check if the column exists under lower case
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        
        # Ensure lat/lon columns are found even if named slightly differently
        df = df.rename(columns={
            'bin_location_lat': 'lat', 
            'bin_location_lon': 'lon',
            'bin_fill_percent': 'fill'
        })
        return df.dropna(subset=['timestamp'])
    except Exception as e:
        st.error(f"Critical Data Error: {e}")
        return None

def get_dist(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5

@st.cache_resource
def get_road_network():
    return ox.graph_from_point((19.0760, 72.8777), dist=8000, network_type='drive')

# --- 2. RUN APP ---
df = load_and_clean_data()

if df is not None:
    page = st.sidebar.selectbox("Menu", ["Home", "Mission Control"])

    if page == "Home":
        st.title("🚛 Smart Waste AI Dispatch")
        st.write("Data successfully loaded!")
        st.dataframe(df.head())

    elif page == "Mission Control":
        st.title("🚛 AI Fleet Dispatcher")
        
        selected_truck = st.sidebar.selectbox("Truck", list(GARAGES.keys()))
        threshold = st.sidebar.slider("Threshold %", 0, 100, 75)
        
        # Simulation Time Slider
        times = sorted(df['timestamp'].unique())
        sim_time = st.sidebar.select_slider("Time", options=times, value=times[int(len(times)*0.8)])
        
        df_snap = df[df['timestamp'] == sim_time].copy()
        
        # Assignment Logic
        def assign(row):
            loc = (row['lat'], row['lon'])
            dists = {name: get_dist(loc, c) for name, c in GARAGES.items()}
            return min(dists, key=dists.get)

        df_snap['truck'] = df_snap.apply(assign, axis=1)
        my_bins = df_snap[(df_snap['truck'] == selected_truck) & (df_snap['fill'] >= threshold)]

        # Map Rendering
        try:
            G = get_road_network()
            m = folium.Map(location=[19.0760, 72.8777], zoom_start=12, tiles="CartoDB positron")

            for _, row in df_snap.iterrows():
                is_mine = (row['truck'] == selected_truck)
                is_full = (row['fill'] >= threshold)
                color = 'red' if (is_full and is_mine) else ('orange' if is_full else 'green')
                
                folium.Marker([row['lat'], row['lon']], icon=folium.Icon(color=color, icon='trash', prefix='fa')).add_to(m)

            # Route calculation
            g_coords = GARAGES[selected_truck]
            if not my_bins.empty:
                targets = my_bins.sort_values('fill', ascending=False).head(8)
                pts = [g_coords] + list(zip(targets['lat'], targets['lon'])) + [DEONAR_DUMPING]
                
                path_coords = []
                for i in range(len(pts)-1):
                    try:
                        n1 = ox.nearest_nodes(G, pts[i][1], pts[i][0])
                        n2 = ox.nearest_nodes(G, pts[i+1][1], pts[i+1][0])
                        path = nx.shortest_path(G, n1, n2, weight='length')
                        path_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in path])
                    except:
                        path_coords.append([pts[i][0], pts[i][1]])
                        path_coords.append([pts[i+1][0], pts[i+1][1]])
                
                if path_coords:
                    folium.PolyLine(path_coords, color="blue", weight=5).add_to(m)

            st_folium(m, width=1200, height=550)
            
            # QR Code
            if not my_bins.empty:
                st.subheader("📲 Driver Navigation")
                url = f"https://www.google.com/maps/dir/?api=1&origin={g_coords[0]},{g_coords[1]}&destination={DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}"
                st.image(qrcode.make(url).get_image(), width=200)

        except Exception as e:
            st.error(f"Map Error: {e}")

else:
    st.error("❌ Still can't find your CSV. Check the Replit sidebar and make sure the file is uploaded there!")
