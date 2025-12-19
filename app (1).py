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
    # Step A: Find the file robustly
    target = None
    all_files = os.listdir('.')
    csv_files = [f for f in all_files if f.lower().endswith('.csv')]
    
    if 'data.csv' in csv_files:
        target = 'data.csv'
    elif csv_files:
        target = csv_files[0] # Take the first CSV available
    
    if not target:
        return None

    try:
        # encoding='utf-8-sig' removes the hidden "BOM" character from Excel
        df = pd.read_csv(target, encoding='utf-8-sig')
        
        # Clean column names: remove spaces and lowercase everything
        df.columns = [c.strip().lower() for c in df.columns]
        
        # Mapping common variations to standard names
        mapping = {
            'bin_location_lat': 'lat',
            'bin_location_lon': 'lon',
            'bin_fill_percent': 'fill',
            'timestamp': 'timestamp'
        }
        
        # Check and rename columns if they exist
        for old, new in mapping.items():
            if old in df.columns:
                df = df.rename(columns={old: new})
            else:
                # Try to find a partial match (e.g. 'bin_location_lat' vs 'lat')
                for col in df.columns:
                    if old in col:
                        df = df.rename(columns={col: new})
                        break
        
        if 'timestamp' not in df.columns:
            st.error(f"🚨 Missing 'timestamp' column! Found: {list(df.columns)}")
            return None
            
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        return df.dropna(subset=['timestamp'])
    except Exception as e:
        st.error(f"❌ Critical Data Error: {e}")
        return None

def get_dist(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5

@st.cache_resource
def get_road_network():
    # Cache the road map to stop it from blinking/reloading
    return ox.graph_from_point((19.0760, 72.8777), dist=8000, network_type='drive')

# --- 2. RUN APP ---
df = load_and_clean_data()

if df is not None:
    page = st.sidebar.selectbox("Dashboard Menu", ["Home", "Mission Control"])

    if page == "Home":
        st.title("🏡 Evergreen Smart Waste AI")
        st.success("✅ Data.csv loaded successfully!")
        st.write("### Data Overview (Latest Readings)")
        st.dataframe(df.head())

    elif page == "Mission Control":
        st.title("🚛 AI Fleet Dispatcher")
        
        # Sidebar Controls
        st.sidebar.header("Mission Settings")
        selected_truck = st.sidebar.selectbox("Select Truck", list(GARAGES.keys()))
        threshold = st.sidebar.slider("Fill Threshold (%)", 0, 100, 75)
        
        # Simulation Time Slider (to see the map in action)
        times = sorted(df['timestamp'].unique())
        default_idx = int(len(times) * 0.8) # 80% through the day
        sim_time = st.sidebar.select_slider("Select Simulation Time", options=times, value=times[default_idx])
        
        df_snap = df[df['timestamp'] == sim_time].copy()
        
        # Assignment Logic (Nearest Truck)
        def assign_truck(row):
            loc = (row['lat'], row['lon'])
            dists = {name: get_dist(loc, c) for name, c in GARAGES.items()}
            return min(dists, key=dists.get)

        df_snap['truck'] = df_snap.apply(assign_truck, axis=1)
        
        # Filter bins for the selected truck mission
        my_bins = df_snap[(df_snap['truck'] == selected_truck) & (df_snap['fill'] >= threshold)]

        # Map Visualization
        try:
            G = get_road_network()
            m = folium.Map(location=[19.0760, 72.8777], zoom_start=12, tiles="CartoDB positron")

            # Plot Bins
            for _, row in df_snap.iterrows():
                is_mine = (row['truck'] == selected_truck)
                is_full = (row['fill'] >= threshold)
                
                if is_full and is_mine: color = 'red'
                elif is_full and not is_mine: color = 'orange'
                else: color = 'green'
                
                folium.Marker([row['lat'], row['lon']], 
                              popup=f"Bin {row['bin_id']}: {row['fill']}%",
                              icon=folium.Icon(color=color, icon='trash', prefix='fa')).add_to(m)

            # Calculate and Draw Route
            garage_coords = GARAGES[selected_truck]
            if not my_bins.empty:
                targets = my_bins.sort_values('fill', ascending=False).head(8)
                pts = [garage_coords] + list(zip(targets['lat'], targets['lon'])) + [DEONAR_DUMPING]
                
                path_coords = []
                for i in range(len(pts)-1):
                    try:
                        n1 = ox.nearest_nodes(G, pts[i][1], pts[i][0])
                        n2 = ox.nearest_nodes(G, pts[i+1][1], pts[i+1][0])
                        path = nx.shortest_path(G, n1, n2, weight='length')
                        path_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in route])
                    except:
                        path_coords.append([pts[i][0], pts[i][1]])
                        path_coords.append([pts[i+1][0], pts[i+1][1]])
                
                if path_coords:
                    folium.PolyLine(path_coords, color="#3498db", weight=6, opacity=0.8).add_to(m)

            # Add Garage & Disposal Markers
            folium.Marker(garage_coords, popup="Active Garage", icon=folium.Icon(color='blue', icon='truck', prefix='fa')).add_to(m)
            folium.Marker(DEONAR_DUMPING, popup="Deonar Disposal", icon=folium.Icon(color='black', icon='home', prefix='fa')).add_to(m)

            # Render Map
            st_folium(m, width=1200, height=550, key="mission_map")
            
            # QR Code Generation
            if not my_bins.empty:
                st.subheader("📲 Driver Navigation Route")
                # Format URL for Google Maps
                url = f"https://www.google.com/maps/dir/?api=1&origin={garage_coords[0]},{garage_coords[1]}&destination={DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}"
                
                qr = qrcode.make(url)
                buf = BytesIO()
                qr.save(buf)
                st.image(buf, width=200)

        except Exception as e:
            st.error(f"Mapping Engine Initializing... {e}")

else:
    st.error("❌ File 'data.csv' not found. Please upload your CSV to the Replit sidebar (Files tab) and name it exactly 'data.csv'.")
