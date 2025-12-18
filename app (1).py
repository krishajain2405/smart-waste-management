import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETUP & MUNICIPAL LOCATIONS ---
st.set_page_config(page_title="Smart Waste AI Optimizer", layout="wide")

TRUCK_DEPOT = (19.0218, 72.8500)      # Garage (Start)
DEONAR_DUMPING = (19.0550, 72.9250)   # Disposal Yard (End)

@st.cache_data
def load_and_clean_data():
    target = 'data.csv'
    if not os.path.exists(target):
        all_csvs = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_csvs: target = all_csvs[0]
        else: return None
    try:
        # sep=None detects Tabs or Commas automatically
        df = pd.read_csv(target, sep=None, engine='python')
        df.columns = df.columns.str.strip()
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        # Get the latest state for each unique bin
        return df.sort_values('timestamp').groupby('bin_id').tail(1)
    except:
        return None

def get_distance(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5

# --- 2. PRIORITY LOGIC ---
def get_mission_route(start, end, bins_df, threshold):
    # STEP A: Filter bins above threshold
    candidates = bins_df[bins_df['bin_fill_percent'] >= threshold].copy()
    
    # STEP B: Take only the TOP 10 most full bins (Priority Queue)
    # This fixes the QR code limit and ensures urgent pickups
    priority_bins = candidates.sort_values(by='bin_fill_percent', ascending=False).head(10)
    
    # STEP C: Greedy Routing (Nearest Neighbor)
    current_pos = start
    ordered_stops = [start]
    unvisited = priority_bins.copy()
    
    while not unvisited.empty:
        unvisited['d'] = unvisited.apply(lambda x: get_distance(current_pos, (x['bin_location_lat'], x['bin_location_lon'])), axis=1)
        closest_idx = unvisited['d'].idxmin()
        closest_row = unvisited.loc[closest_idx]
        target = (closest_row['bin_location_lat'], closest_row['bin_location_lon'])
        ordered_stops.append(target)
        current_pos = target
        unvisited = unvisited.drop(closest_idx)
        
    ordered_stops.append(end) # Final destination is always Deonar
    return ordered_stops, priority_bins

# --- 3. UI DASHBOARD ---
st.title("🚛 Smart Waste AI: Mission Optimization Control")

df_latest = load_and_clean_data()

if df_latest is not None:
    st.sidebar.header("System Parameters")
    # For your demo, start the slider at 5% to see the map populate, then move it to 75%
    threshold = st.sidebar.slider("Urgency Threshold (Fill %)", 0, 100, 5)
    
    # Run the Optimizer
    mission_stops, red_bins = get_mission_route(TRUCK_DEPOT, DEONAR_DUMPING, df_latest, threshold)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Bins in City", len(df_latest))
    c2.metric("Critical Bins (Red)", len(red_bins))
    c3.metric("Goal", "Deonar Disposal")

    # --- 4. MAP ENGINE ---
    @st.cache_resource
    def load_mumbai_map():
        return ox.graph_from_point((19.04, 72.88), dist=5000, network_type='drive')

    with st.spinner("AI is calculating the path to Deonar..."):
        try:
            G = load_mumbai_map()
            m = folium.Map(location=[19.04, 72.88], zoom_start=13, tiles="CartoDB positron")

            # Markers for Depot and Deonar
            folium.Marker(TRUCK_DEPOT, popup="MUNICIPAL DEPOT", icon=folium.Icon(color='blue', icon='truck', prefix='fa')).add_to(m)
            folium.Marker(DEONAR_DUMPING, popup="DEONAR DUMPING GROUND", icon=folium.Icon(color='black', icon='home', prefix='fa')).add_to(m)

            # Draw Road Route
            route_coords = []
            for i in range(len(mission_stops)-1):
                try:
                    n1 = ox.nearest_nodes(G, mission_stops[i][1], mission_stops[i][0])
                    n2 = ox.nearest_nodes(G, mission_stops[i+1][1], mission_stops[i+1][0])
                    path = nx.shortest_path(G, n1, n2, weight='length')
                    route_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in path])
                except:
                    route_coords.append([mission_stops[i][0], mission_stops[i][1]])
                    route_coords.append([mission_stops[i+1][0], mission_stops[i+1][1]])
            
            if route_coords:
                folium.PolyLine(route_coords, color="#2ecc71", weight=7, opacity=0.8).add_to(m)

            # Plot Bins with Color Logic
            red_bin_ids = red_bins['bin_id'].tolist()
            for _, row in df_latest.iterrows():
                # Corrected logic: Red only if in our Priority Top 10 list
                is_red = row['bin_id'] in red_bin_ids
                folium.Marker(
                    [row['bin_location_lat'], row['bin_location_lon']], 
                    popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                    icon=folium.Icon(color='red' if is_red else 'green', icon='trash', prefix='fa')
                ).add_to(m)

            st_folium(m, width=1200, height=550)
        except Exception as e:
            st.error(f"Map Error: {e}")

    # --- 5. GOOGLE MAPS QR CODE ---
    if not red_bins.empty:
        st.subheader("📲 Official Driver Route (Deonar Mission)")
        
        # Build the URL: start at depot, go via waypoints, end at Deonar
        origin = f"{TRUCK_DEPOT[0]},{TRUCK_DEPOT[1]}"
        dest = f"{DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}"
        # Mid-stops (The Red Bins)
        waypoints = "|".join([f"{lat},{lon}" for lat, lon in mission_stops[1:-1]])
        
        google_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={dest}&waypoints={waypoints}&travelmode=driving"
        
        c_qr, c_txt = st.columns([1, 4])
        with c_qr:
            qr = qrcode.make(google_url)
            buf = BytesIO()
            qr.save(buf)
            st.image(buf, width=200)
        with c_txt:
            st.success("✅ Path Optimized: Scan to open in Google Maps.")
            st.info("The QR code includes the Depot, the 10 most critical bins, and the Deonar Disposal Site.")

else:
    st.error("Missing 'data.csv' on GitHub.")
