import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. PAGE CONFIG ---
st.set_page_config(page_title="Smart Waste AI Dashboard", layout="wide")

@st.cache_data
def load_data_robustly():
    # Find the file
    target = 'data.csv'
    if not os.path.exists(target):
        all_csvs = [f for f in os.listdir('.') if f.endswith('.csv')]
        if not all_csvs: return None
        target = all_csvs[0]

    try:
        # STEP 1: Try reading with auto-separator
        df = pd.read_csv(target, sep=None, engine='python')
        df.columns = df.columns.str.strip()

        # STEP 2: If it's still stuck in one column, force Tab-separation
        if len(df.columns) <= 1:
            df = pd.read_csv(target, sep='\t')
            df.columns = df.columns.str.strip()

        # STEP 3: THE DATE FIX - Use 'dayfirst' to handle 13-08-2025
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['timestamp']) # Remove errors
            
            # Get latest snapshot per bin
            latest = df.sort_values('timestamp').groupby('bin_id').tail(1)
            return latest
        else:
            st.error(f"Columns found: {list(df.columns)}")
            return None
    except Exception as e:
        st.error(f"Detailed Error: {e}")
        return None

# --- 2. THE DASHBOARD ---
df_latest = load_data_robustly()

if df_latest is not None:
    # Filter for full bins (>75%)
    full_bins = df_latest[df_latest['bin_fill_percent'] > 75].copy()

    st.title("🗑️ Smart Waste AI: Optimization Engine")
    
    if full_bins.empty:
        st.success("✅ System Status: All bins are clear. No pickups required.")
    else:
        st.warning(f"🚨 Logistics Alert: {len(full_bins)} bins require immediate collection.")

        # --- 3. MAP ENGINE ---
        @st.cache_resource
        def build_map():
            # Focused on your bin area in Mumbai
            return ox.graph_from_point((19.04, 72.86), dist=3500, network_type='drive')

        with st.spinner("AI calculating fuel-efficient route..."):
            G = build_map()
            
            # Map GPS points to road nodes
            nodes = [ox.nearest_nodes(G, row['bin_location_lon'], row['bin_location_lat']) 
                     for _, row in full_bins.iterrows()]
            
            # Calculate path
            full_route = []
            for i in range(len(nodes)-1):
                try:
                    path = nx.shortest_path(G, nodes[i], nodes[i+1], weight='length')
                    full_route.extend(path[:-1] if i < len(nodes)-2 else path)
                except: continue

            # Visual Map
            m = folium.Map(location=[19.04, 72.86], zoom_start=14, tiles="CartoDB positron")
            if full_route:
                coords = [[G.nodes[n]['y'], G.nodes[n]['x']] for n in full_route]
                folium.PolyLine(coords, color="#2ecc71", weight=6).add_to(m)

            for _, row in full_bins.iterrows():
                folium.Marker(
                    [row['bin_location_lat'], row['bin_location_lon']], 
                    popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                    icon=folium.Icon(color='red', icon='trash', prefix='fa')
                ).add_to(m)

            st_folium(m, width=1200, height=500)

        # --- 4. NAVIGATION QR ---
        st.subheader("📲 Real-Time Navigation for Truck Driver")
        loc_str = "/".join([f"{r['bin_location_lat']},{r['bin_location_lon']}" for _, r in full_bins.iterrows()])
        gmaps_url = f"https://www.google.com/maps/dir/{loc_str}"
        
        qr = qrcode.make(gmaps_url)
        buf = BytesIO()
        qr.save(buf)
        st.image(buf, width=200, caption="Scan to open in Google Maps")
else:
    st.error("SYSTEM ERROR: Data file not found or corrupted on GitHub.")
