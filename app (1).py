import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO

# --- 1. SETUP & DATA LOADING ---
st.set_page_config(page_title="Smart Waste Dashboard", layout="wide")

@st.cache_data
def load_custom_data():
    try:
        # This looks for the file 'data.csv' in your GitHub
        df = pd.read_csv('data.csv')
        # Get the latest status for each bin
        latest = df.sort_values('timestamp').groupby('bin_id').tail(1)
        return latest
    except Exception as e:
        st.error("⚠️ File 'data.csv' not found. Please rename your CSV file on GitHub to 'data.csv'")
        return None

# --- 2. LOGIC ---
df_latest = load_custom_data()

if df_latest is not None:
    # We only care about bins that are nearly full
    full_bins = df_latest[df_latest['bin_fill_percent'] > 75].copy()

    st.title("🚛 Smart Waste Management: AI Route Optimizer")
    st.success(f"Dashboard Active: Routing to {len(full_bins)} full bins.")

    # --- 3. MAP CALCULATION ---
    @st.cache_resource
    def get_mumbai_map():
        # Center coordinates for Mumbai area
        return ox.graph_from_point((19.04, 72.86), dist=3000, network_type='drive')

    with st.spinner("Calculating the most fuel-efficient route..."):
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
        # Create a clean map
        m = folium.Map(location=[19.04, 72.86], zoom_start=14, tiles="CartoDB positron")
        
        # Draw the green path for the truck
        if full_route:
            route_coords = [[G.nodes[n]['y'], G.nodes[n]['x']] for n in full_route]
            folium.PolyLine(route_coords, color="#2ecc71", weight=6, opacity=0.8).add_to(m)

        # Draw Red Markers for the bins
        for idx, row in full_bins.iterrows():
            folium.Marker(
                [row['bin_location_lat'], row['bin_location_lon']], 
                popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}% Full",
                icon=folium.Icon(color='red', icon='trash', prefix='fa')
            ).add_to(m)

        st_folium(m, width=1200, height=500)

    # --- 5. DRIVER UTILITY ---
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📲 Driver Navigation")
        st.write("Scan this code to open the optimized route in Google Maps.")
        qr_url = "https://www.google.com/maps/dir/" + "/".join([f"{r['bin_location_lat']},{r['bin_location_lon']}" for i, r in full_bins.iterrows()])
        qr = qrcode.make(qr_url)
        buf = BytesIO()
        qr.save(buf)
        st.image(buf, width=200)

    with col2:
        st.subheader("📊 Collection Summary")
        st.metric("Total Bins to Visit", len(full_bins))
        avg_fill = df_latest['bin_fill_percent'].mean()
        st.metric("Average City Fill Level", f"{int(avg_fill)}%")
