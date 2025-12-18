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
st.set_page_config(page_title="Smart Waste AI Optimizer", layout="wide")

@st.cache_data
def load_data_robustly():
    target = 'data.csv'
    if not os.path.exists(target):
        all_csvs = [f for f in os.listdir('.') if f.endswith('.csv')]
        if not all_csvs: return None
        target = all_csvs[0]
    try:
        df = pd.read_csv(target, sep=None, engine='python')
        df.columns = df.columns.str.strip()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['timestamp'])
            return df.sort_values('timestamp').groupby('bin_id').tail(1)
    except: return None
    return None

# --- 2. THE DASHBOARD UI ---
st.title("🗑️ Smart Waste AI: Optimization Engine")

df_latest = load_data_robustly()

if df_latest is not None:
    # --- SIDEBAR CONTROL (The trick for your demo!) ---
    st.sidebar.header("Demo Settings")
    threshold = st.sidebar.slider("Fill Threshold for Pickup (%)", 0, 100, 50)
    
    # Filter bins based on the slider
    full_bins = df_latest[df_latest['bin_fill_percent'] >= threshold].copy()
    
    # Stats row
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Bins Monitored", len(df_latest))
    c2.metric("Bins to Collect", len(full_bins))
    c3.metric("Critical Bins (>90%)", len(df_latest[df_latest['bin_fill_percent'] > 90]))

    # --- 3. MAP ENGINE (Always Runs) ---
    @st.cache_resource
    def build_base_map():
        # Center of Mumbai data
        return ox.graph_from_point((19.04, 72.86), dist=4000, network_type='drive')

    with st.spinner("Loading Map..."):
        G = build_base_map()
        
        # Create Folium Map
        m = folium.Map(location=[19.04, 72.86], zoom_start=13, tiles="CartoDB positron")

        # --- 4. CALCULATE ROUTE (Only if bins are full) ---
        if len(full_bins) >= 2:
            try:
                nodes = [ox.nearest_nodes(G, row['bin_location_lon'], row['bin_location_lat']) for _, row in full_bins.iterrows()]
                full_route = []
                for i in range(len(nodes)-1):
                    try:
                        path = nx.shortest_path(G, nodes[i], nodes[i+1], weight='length')
                        full_route.extend(path[:-1] if i < len(nodes)-2 else path)
                    except: continue
                
                if full_route:
                    coords = [[G.nodes[n]['y'], G.nodes[n]['x']] for n in full_route]
                    folium.PolyLine(coords, color="#2ecc71", weight=6, opacity=0.8).add_to(m)
            except:
                st.write("Route calculation pending...")

        # --- 5. ALWAYS ADD MARKERS ---
        for _, row in df_latest.iterrows():
            # Red if it's above threshold, Green if below
            is_full = row['bin_fill_percent'] >= threshold
            icon_color = 'red' if is_full else 'green'
            
            folium.Marker(
                [row['bin_location_lat'], row['bin_location_lon']], 
                popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                icon=folium.Icon(color=icon_color, icon='trash', prefix='fa')
            ).add_to(m)

        # SHOW THE MAP
        st_folium(m, width=1200, height=550)

    # --- 6. QR CODE ---
    if not full_bins.empty:
        st.subheader("📲 Live Driver Navigation")
        loc_str = "/".join([f"{r['bin_location_lat']},{r['bin_location_lon']}" for _, r in full_bins.iterrows()])
        qr = qrcode.make(f"https://www.google.com/maps/dir/{loc_str}")
        buf = BytesIO()
        qr.save(buf)
        st.image(buf, width=150)
else:
    st.error("Data file not detected. Check GitHub.")
