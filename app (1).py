import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. PAGE SETUP ---
st.set_page_config(page_title="Smart Waste AI Optimizer", layout="wide")

@st.cache_data
def load_data():
    # Attempting to find the data file
    target = 'data.csv'
    if not os.path.exists(target):
        all_csvs = [f for f in os.listdir('.') if f.endswith('.csv')]
        if not all_csvs: return None
        target = all_csvs[0]
    try:
        df = pd.read_csv(target, sep=None, engine='python')
        df.columns = df.columns.str.strip()
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        return df.sort_values('timestamp').groupby('bin_id').tail(1)
    except: return None

# --- 2. HEADER & SETTINGS ---
st.title("🚛 Smart Waste AI: Optimization Engine")
df_latest = load_data()

if df_latest is not None:
    # DEMO CONTROLS
    st.sidebar.header("Demo Controls")
    # Set this to 20% or 30% during your demo to show lots of red bins and a long path!
    threshold = st.sidebar.slider("Fill Threshold for Collection (%)", 0, 100, 30)
    
    full_bins = df_latest[df_latest['bin_fill_percent'] >= threshold].copy()
    
    # Sorting bins for a logical route (Simple TSP)
    if not full_bins.empty:
        full_bins = full_bins.sort_values(['bin_location_lat', 'bin_location_lon'])

    # Dashboard Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Bins Monitored", len(df_latest))
    m2.metric("Bins to Collect", len(full_bins))
    m3.metric("System Status", "Optimizing" if not full_bins.empty else "Idle")

    # --- 3. MAP & ROUTING ENGINE ---
    @st.cache_resource
    def get_map_data():
        # Downloads road network for the specific area of your data
        return ox.graph_from_point((19.04, 72.86), dist=5000, network_type='drive')

    with st.spinner("AI is calculating the shortest path..."):
        G = get_map_data()
        m = folium.Map(location=[19.04, 72.86], zoom_start=13, tiles="CartoDB Positron")

        if len(full_bins) >= 2:
            route_nodes = []
            # Convert bin locations to the nearest road nodes
            bin_nodes = [ox.nearest_nodes(G, row['bin_location_lon'], row['bin_location_lat']) for _, row in full_bins.iterrows()]
            
            total_route_coords = []
            for i in range(len(bin_nodes)-1):
                try:
                    # Try to find real road path
                    path = nx.shortest_path(G, bin_nodes[i], bin_nodes[i+1], weight='length')
                    path_coords = [[G.nodes[node]['y'], G.nodes[node]['x']] for node in path]
                    total_route_coords.extend(path_coords)
                except:
                    # FALLBACK: Draw a direct line if road data is missing for that segment
                    total_route_coords.append([full_bins.iloc[i]['bin_location_lat'], full_bins.iloc[i]['bin_location_lon']])
                    total_route_coords.append([full_bins.iloc[i+1]['bin_location_lat'], full_bins.iloc[i+1]['bin_location_lon']])

            # Draw the path on the map
            if total_route_coords:
                folium.PolyLine(total_route_coords, color="#2ecc71", weight=7, opacity=0.8, popup="Optimized Route").add_to(m)

        # --- 4. MARKERS ---
        for _, row in df_latest.iterrows():
            is_full = row['bin_fill_percent'] >= threshold
            folium.Marker(
                [row['bin_location_lat'], row['bin_location_lon']], 
                popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                icon=folium.Icon(color='red' if is_full else 'green', icon='trash', prefix='fa')
            ).add_to(m)

        st_folium(m, width=1100, height=500)

    # --- 5. FIXED QR CODE NAVIGATION ---
    if not full_bins.empty:
        st.subheader("📲 Driver Navigation (Multi-Stop)")
        # This creates a proper Google Maps Directions URL
        # Format: https://www.google.com/maps/dir/lat1,lon1/lat2,lon2/...
        base_nav_url = "https://www.google.com/maps/dir/"
        stops = [f"{row['bin_location_lat']},{row['bin_location_lon']}" for _, row in full_bins.iterrows()]
        final_nav_url = base_nav_url + "/".join(stops)
        
        col1, col2 = st.columns([1, 3])
        with col1:
            qr = qrcode.make(final_nav_url)
            buf = BytesIO()
            qr.save(buf)
            st.image(buf, width=200, caption="Scan for GPS Navigation")
        with col2:
            st.info("💡 **Demo Tip:** Scan this QR code with your phone. It will open Google Maps with all the red bins set as destinations in the perfect order.")
else:
    st.error("Could not find 'data.csv'. Please upload it to GitHub.")
