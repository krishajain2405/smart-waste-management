import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

st.set_page_config(page_title="Smart Waste Optimizer", layout="wide")

# --- 1. SMART & SAFE DATA LOADING ---
@st.cache_data
def load_custom_data():
    # We will try to find your file
    target_file = 'data.csv'
    
    if not os.path.exists(target_file):
        # If data.csv isn't there, let's look for ANY csv file in the folder
        all_files = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_files:
            target_file = all_files[0]
        else:
            st.error("❌ No CSV files found! Please upload your data to GitHub.")
            return None

    # Check if the file is empty before reading
    if os.path.getsize(target_file) == 0:
        st.error(f"❌ The file '{target_file}' is empty! Please paste your data into it on GitHub.")
        return None

    try:
        st.info(f"Reading data from: {target_file}")
        df = pd.read_csv(target_file)
        # Get the latest status for each bin
        latest = df.sort_values('timestamp').groupby('bin_id').tail(1)
        return latest
    except Exception as e:
        st.error(f"❌ Error reading the file: {e}")
        return None

# --- 2. THE DASHBOARD ---
df_latest = load_custom_data()

if df_latest is not None:
    # Filter for bins that are more than 75% full
    full_bins = df_latest[df_latest['bin_fill_percent'] > 75].copy()

    st.title("🚛 Smart Waste Management Optimizer")
    
    if full_bins.empty:
        st.warning("✅ Great news! No bins currently need collection (all below 75%).")
    else:
        st.success(f"Action Required: Found {len(full_bins)} full bins.")

        # --- 3. MAP ---
        @st.cache_resource
        def get_mumbai_map():
            # Centers on your data points
            return ox.graph_from_point((19.04, 72.86), dist=3000, network_type='drive')

        with st.spinner("Calculating shortest path for the garbage truck..."):
            G = get_mumbai_map()
            nodes = [ox.nearest_nodes(G, row['bin_location_lon'], row['bin_location_lat']) 
                     for idx, row in full_bins.iterrows()]
            
            full_route = []
            for i in range(len(nodes)-1):
                try:
                    path = nx.shortest_path(G, nodes[i], nodes[i+1], weight='length')
                    full_route.extend(path[:-1] if i < len(nodes)-2 else path)
                except: continue

            # Create Map
            m = folium.Map(location=[19.04, 72.86], zoom_start=14)
            if full_route:
                route_coords = [[G.nodes[n]['y'], G.nodes[n]['x']] for n in full_route]
                folium.PolyLine(route_coords, color="green", weight=5).add_to(m)

            for idx, row in full_bins.iterrows():
                folium.Marker([row['bin_location_lat'], row['bin_location_lon']], 
                              popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%").add_to(m)

            st_folium(m, width=1000)

        # --- 4. QR CODE ---
        st.subheader("📲 Driver QR Route")
        nav_url = "https://www.google.com/maps/dir/" + "/".join([f"{r['bin_location_lat']},{r['bin_location_lon']}" for i, r in full_bins.iterrows()])
        qr = qrcode.make(nav_url)
        buf = BytesIO()
        qr.save(buf)
        st.image(buf, width=200, caption="Scan to open in Google Maps")
