import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETTING UP THE PAGE ---
st.set_page_config(page_title="Smart Waste Management AI", layout="wide")

@st.cache_data
def load_and_clean_data():
    target_file = 'data.csv'
    # Fallback if the file has a different name
    if not os.path.exists(target_file):
        all_files = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_files: target_file = all_files[0]
        else: return None

    try:
        # THE FIX: sep=None and engine='python' tells pandas to GUESS the separator (comma or tab)
        df = pd.read_csv(target_file, sep=None, engine='python')
        
        # Clean up column names (removes hidden spaces and tabs)
        df.columns = df.columns.str.strip()
        
        # Convert timestamp to actual dates
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            # Get the very latest data for each bin
            latest = df.sort_values('timestamp').groupby('bin_id').tail(1)
            return latest
        else:
            st.error(f"Missing 'timestamp' column. Found: {list(df.columns)}")
            return None
    except Exception as e:
        st.error(f"Critical Data Error: {e}")
        return None

# --- 2. THE BRAIN OF THE APP ---
df_latest = load_and_clean_data()

if df_latest is not None:
    # We only want to visit bins that are > 75% full
    full_bins = df_latest[df_latest['bin_fill_percent'] > 75].copy()

    st.title("🗑️ Smart Waste AI: Route Optimization Dashboard")
    
    if full_bins.empty:
        st.balloons()
        st.success("✅ All bins are currently under control! No pickups needed.")
    else:
        st.warning(f"🚨 Urgent: {len(full_bins)} bins have exceeded 75% capacity.")

        # --- 3. CALCULATING THE MAP ---
        @st.cache_resource
        def get_city_graph():
            # Centers on the heart of your data coordinates (Mumbai area)
            return ox.graph_from_point((19.04, 72.86), dist=4000, network_type='drive')

        with st.spinner("🚀 AI is calculating the most fuel-efficient route..."):
            G = get_city_graph()
            
            # Map bin locations to the nearest road points
            nodes = [ox.nearest_nodes(G, row['bin_location_lon'], row['bin_location_lat']) 
                     for idx, row in full_bins.iterrows()]
            
            full_route = []
            for i in range(len(nodes)-1):
                try:
                    path = nx.shortest_path(G, nodes[i], nodes[i+1], weight='length')
                    full_route.extend(path[:-1] if i < len(nodes)-2 else path)
                except: continue

            # Create the Visual Map
            m = folium.Map(location=[19.04, 72.86], zoom_start=14, tiles="CartoDB positron")
            
            # Draw the Route Path in Green
            if full_route:
                route_coords = [[G.nodes[n]['y'], G.nodes[n]['x']] for n in full_route]
                folium.PolyLine(route_coords, color="#2ecc71", weight=6, opacity=0.8).add_to(m)

            # Mark the Bins
            for idx, row in full_bins.iterrows():
                color = 'red' if row['bin_fill_percent'] > 90 else 'orange'
                folium.Marker(
                    [row['bin_location_lat'], row['bin_location_lon']], 
                    popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}% Full",
                    icon=folium.Icon(color=color, icon='trash', prefix='fa')
                ).add_to(m)

            st_folium(m, width=1200, height=500)

        # --- 4. ANALYTICS & QR ---
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Bins to Visit", len(full_bins))
        with c2:
            st.metric("Avg Fill Level", f"{int(df_latest['bin_fill_percent'].mean())}%")
        with c3:
            # Fun stat for the judges
            fuel_saved = df_latest['fuel_saved'].sum() / 100 
            st.metric("Estimated Fuel Saved", f"{fuel_saved:.1f} L")

        st.subheader("📲 Live Driver Navigation")
        # Generates a dynamic multi-stop Google Maps link
        locs = [f"{r['bin_location_lat']},{r['bin_location_lon']}" for i, r in full_bins.iterrows()]
        gmaps_url = f"https://www.google.com/maps/dir/{'/'.join(locs)}"
        
        qr = qrcode.make(gmaps_url)
        buf = BytesIO()
        qr.save(buf)
        st.image(buf, width=200, caption="Scan this to follow the path on your phone!")
else:
    st.error("Wait! We can't find your data. Make sure 'data.csv' is uploaded to your GitHub repository.")
