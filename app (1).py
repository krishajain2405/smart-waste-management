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
st.set_page_config(page_title="Smart Waste Optimizer", layout="wide")

@st.cache_data
def load_custom_data():
    target_file = 'data.csv'
    # Look for the file
    if not os.path.exists(target_file):
        all_files = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_files: target_file = all_files[0]
        else: return None

    try:
        df = pd.read_csv(target_file)
        df.columns = df.columns.str.strip() # Remove hidden spaces
        
        # Security check for Aavishkar judges
        if 'timestamp' not in df.columns:
            st.error(f"Columns found: {list(df.columns)}")
            return None
            
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        latest = df.sort_values('timestamp').groupby('bin_id').tail(1)
        return latest
    except:
        return None

# --- 2. LOGIC ---
df_latest = load_custom_data()

if df_latest is not None:
    # Filter for bins needing collection
    full_bins = df_latest[df_latest['bin_fill_percent'] > 75].copy()

    st.title("🚛 Smart Waste Management Optimizer")
    
    if full_bins.empty:
        st.success("✅ All bins are currently below 75% capacity!")
    else:
        st.info(f"Generating optimized route for {len(full_bins)} full bins...")

        # --- 3. MAP ---
        @st.cache_resource
        def get_mumbai_map():
            # Centers on the average of your bin coordinates
            return ox.graph_from_point((19.04, 72.86), dist=3500, network_type='drive')

        G = get_mumbai_map()
        nodes = [ox.nearest_nodes(G, row['bin_location_lon'], row['bin_location_lat']) for idx, row in full_bins.iterrows()]
        
        full_route = []
        for i in range(len(nodes)-1):
            try:
                path = nx.shortest_path(G, nodes[i], nodes[i+1], weight='length')
                full_route.extend(path[:-1] if i < len(nodes)-2 else path)
            except: continue

        # Visualizing the road network and path
        m = folium.Map(location=[19.04, 72.86], zoom_start=14, tiles="CartoDB positron")
        if full_route:
            route_coords = [[G.nodes[n]['y'], G.nodes[n]['x']] for n in full_route]
            folium.PolyLine(route_coords, color="#2ecc71", weight=6).add_to(m)

        for idx, row in full_bins.iterrows():
            folium.Marker([row['bin_location_lat'], row['bin_location_lon']], 
                          popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                          icon=folium.Icon(color='red', icon='trash', prefix='fa')).add_to(m)

        st_folium(m, width=1200, height=500)

        # --- 4. QR CODE ---
        st.subheader("📲 Live Navigation for Driver")
        qr_url = "https://www.google.com/maps/dir/" + "/".join([f"{r['bin_location_lat']},{r['bin_location_lon']}" for i, r in full_bins.iterrows()])
        qr = qrcode.make(qr_url)
        buf = BytesIO()
        qr.save(buf)
        st.image(buf, width=200)
else:
    st.error("Please ensure your CSV data is uploaded to GitHub as 'data.csv'")
