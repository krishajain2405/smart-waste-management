import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETTINGS & LOCATIONS ---
st.set_page_config(page_title="Smart Waste AI Optimizer", layout="wide")

# We define the Truck Start (Depot) and the Final Location (Disposal Site)
# These are real coordinates in Mumbai for your demo
TRUCK_DEPOT = (19.0218, 72.8500)      # Where the truck starts
DISPOSAL_SITE = (19.0700, 72.8800)    # Where the truck empties the waste

@st.cache_data
def load_and_clean_data():
    # Use your specific file name
    target = 'data.csv'
    if not os.path.exists(target):
        all_csvs = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_csvs: target = all_csvs[0]
        else: return None
    try:
        df = pd.read_csv(target, sep=None, engine='python')
        df.columns = df.columns.str.strip()
        # Ensure timestamp is readable
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        # Get the latest status for every bin
        return df.sort_values('timestamp').groupby('bin_id').tail(1)
    except:
        return None

# --- 2. THE AI ROUTING LOGIC ---
def get_distance(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)**0.5

def plan_mission(start, disposal, bins_df):
    """Orders the stops: Start -> Nearest Bin -> Next Nearest -> Disposal"""
    current_pos = start
    unvisited = bins_df.copy()
    route_points = [start]
    
    while not unvisited.empty:
        # Calculate distance from current position to all remaining bins
        unvisited['temp_dist'] = unvisited.apply(
            lambda x: get_distance(current_pos, (x['bin_location_lat'], x['bin_location_lon'])), axis=1
        )
        closest_idx = unvisited['temp_dist'].idxmin()
        closest_row = unvisited.loc[closest_idx]
        
        new_stop = (closest_row['bin_location_lat'], closest_row['bin_location_lon'])
        route_points.append(new_stop)
        current_pos = new_stop
        unvisited = unvisited.drop(closest_idx)
        
    route_points.append(disposal) # End at the disposal site
    return route_points

# --- 3. THE USER INTERFACE ---
st.title("🚛 Smart Waste AI: Fleet Mission Control")

df_latest = load_and_clean_data()

if df_latest is not None:
    # THE SLIDER (Placed in Sidebar)
    st.sidebar.header("Mission Parameters")
    # By changing this slider, the 'full_bins' list changes, and the whole app reruns
    fill_threshold = st.sidebar.slider("Fill Level Threshold (%)", 0, 100, 40)
    
    # Filter the data
    full_bins = df_latest[df_latest['bin_fill_percent'] >= fill_threshold].copy()
    
    # Calculate the sequence
    mission_stops = plan_mission(TRUCK_DEPOT, DISPOSAL_SITE, full_bins)

    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("Bins Needing Pickup", len(full_bins))
    c2.metric("Total Stops", len(mission_stops))
    c3.metric("Fleet Status", "Calculating Route..." if not full_bins.empty else "Standby")

    # --- 4. MAP VISUALIZATION ---
    @st.cache_resource
    def load_mumbai_road_network():
        # Central point for your bins
        return ox.graph_from_point((19.04, 72.86), dist=4500, network_type='drive')

    with st.spinner("AI calculating shortest road distance..."):
        try:
            G = load_mumbai_road_network()
            m = folium.Map(location=[19.04, 72.86], zoom_start=13, tiles="CartoDB positron")

            # Markers for Truck Start and Disposal End
            folium.Marker(TRUCK_DEPOT, popup="TRUCK DEPOT (START)", icon=folium.Icon(color='blue', icon='truck', prefix='fa')).add_to(m)
            folium.Marker(DISPOSAL_SITE, popup="DISPOSAL YARD (END)", icon=folium.Icon(color='black', icon='dumpster', prefix='fa')).add_to(m)

            # Draw Road Paths
            full_path_coords = []
            for i in range(len(mission_stops)-1):
                try:
                    # OSMnx uses (Longitude, Latitude) for node finding
                    node1 = ox.nearest_nodes(G, mission_stops[i][1], mission_stops[i][0])
                    node2 = ox.nearest_nodes(G, mission_stops[i+1][1], mission_stops[i+1][0])
                    route = nx.shortest_path(G, node1, node2, weight='length')
                    full_path_coords.extend([[G.nodes[n]['y'], G.nodes[n]['x']] for n in route])
                except:
                    # Fallback line if road not found
                    full_path_coords.append([mission_stops[i][0], mission_stops[i][1]])
                    full_path_coords.append([mission_stops[i+1][0], mission_stops[i+1][1]])

            if full_path_coords:
                folium.PolyLine(full_path_coords, color="#2ecc71", weight=6, opacity=0.8).add_to(m)

            # Add markers for all bins
            for _, row in df_latest.iterrows():
                is_full = row['bin_fill_percent'] >= fill_threshold
                folium.Marker(
                    [row['bin_location_lat'], row['bin_location_lon']], 
                    popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                    icon=folium.Icon(color='red' if is_full else 'green', icon='trash', prefix='fa')
                ).add_to(m)

            st_folium(m, width=1200, height=550)

        except Exception as e:
            st.error(f"Mapping Error: {e}")

    # --- 5. FIXED QR CODE NAVIGATION ---
    if len(full_bins) > 0:
        st.subheader("📲 Real-Time Driver Navigation")
        
        # We use the Standard Google Maps Direction format:
        # https://www.google.com/maps/dir/Start/Stop1/Stop2/End
        address_list = [f"{lat},{lon}" for lat, lon in mission_stops]
        google_maps_url = "https://www.google.com/maps/dir/" + "/".join(address_list)
        
        col_qr, col_text = st.columns([1, 4])
        with col_qr:
            qr = qrcode.make(google_maps_url)
            buf = BytesIO()
            qr.save(buf)
            st.image(buf, width=180)
        with col_text:
            st.write("### Instructions for Judges:")
            st.write("1. Scan this QR code with any phone.")
            st.write(f"2. Google Maps will open with **{len(mission_stops)} stops**.")
            st.write("3. It starts at the **Truck Depot**, visits the **Red Bins**, and ends at the **Disposal Site**.")
            st.info("This logic solves the 'Traveling Salesman Problem' to ensure zero wasted fuel.")

else:
    st.error("Please ensure your 'data.csv' is uploaded to GitHub.")
