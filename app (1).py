import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

st.set_page_config(page_title="Smart Waste Dashboard", layout="wide")

# --- 1. SMART DATA LOADING ---
@st.cache_data
def load_custom_data():
    # List of possible names the file might have
    possible_names = [
        'data.csv', 
        'cleaned_data_with_fuel_weight_co2 (1).xlsx - Sheet1.csv',
        'cleaned_data_with_fuel_weight_co2 (1).csv'
    ]
    
    df = None
    for name in possible_names:
        if os.path.exists(name):
            df = pd.read_csv(name)
            break
            
    if df is None:
        # If still not found, list all files to help debug
        files_in_dir = os.listdir('.')
        st.error(f"❌ Could not find the data file. Files present in your GitHub: {files_in_dir}")
        return None
        
    # Get the latest status for each bin
    latest = df.sort_values('timestamp').groupby('bin_id').tail(1)
    return latest

# --- 2. THE REST OF YOUR LOGIC ---
df_latest = load_custom_data()

if df_latest is not None:
    # Filter for full bins
    full_bins = df_latest[df_latest['bin_fill_percent'] > 75].copy()

    st.title("🚛 Smart Waste Management: AI Route Optimizer")
    
    # Check if there are any full bins to show
    if full_bins.empty:
        st.warning("All bins are currently empty or below 75% fill capacity.")
    else:
        st.success(f"Dashboard Active: Routing to {len(full_bins)} full bins.")

        # --- 3. MAP CALCULATION ---
        @st.cache_resource
        def get_mumbai_map():
            return ox.graph_from_point((19.04, 72.86), dist=3500, network_type='drive')

        with st.spinner("Analyzing road network for the best path..."):
            G = get_mumbai_map()
            
            # Find nearest road points for our bins
            nodes = [ox.nearest_nodes(G, row['bin_location_lon'], row['bin_location_lat']) 
                     for idx, row in full_bins.iterrows()]
            
            full_route = []
            for i in range(len(nodes)-1):
                try:
                    path = nx.shortest_path(G, nodes[i], nodes[i+1], weight='length')
                    full_route.extend(path[:-1] if i < len(nodes)-2 else path)
                except:
                    continue

            # --- 4. DISPLAY MAP ---
            m = folium.Map(location=[19.04, 72.86], zoom_start=14, tiles="CartoDB positron")
            
            if full_route:
                route_coords = [[G.nodes[n]['y'], G.nodes[n]['x']] for n in full_route]
                folium.PolyLine(route_coords, color="#2ecc71", weight=6, opacity=0.8).add_to(m)

            for idx, row in full_bins.iterrows():
                folium.Marker(
                    [row['bin_location_lat'], row['bin_location_lon']], 
                    popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}% Full",
                    icon=folium.Icon(color='red', icon='trash', prefix='fa')
                ).add_to(m)

            st_folium(m, width=1200, height=500)

        # --- 5. DRIVER UTILITY ---
        st.subheader("📲 Driver Navigation")
        qr_url = "http://maps.google.com/maps?saddr=" + f"{full_bins.iloc[0]['bin_location_lat']},{full_bins.iloc[0]['bin_location_lon']}" + "&daddr=" + "+to:".join([f"{r['bin_location_lat']},{r['bin_location_lon']}" for i, r in full_bins.iloc[1:].iterrows()])
        
        qr = qrcode.make(qr_url)
        buf = BytesIO()
        qr.save(buf)
        st.image(buf, width=200, caption="Scan to start navigation")
