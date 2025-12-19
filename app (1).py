import streamlit as st
import pandas as pd
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium
import qrcode
from io import BytesIO
import os

# --- 1. SETUP & MULTI-TRUCK GARAGES ---
st.set_page_config(page_title="AI Fleet Optimizer: Mumbai Waste", layout="wide")

# We define 5 strategic Municipal Garages across Mumbai
GARAGES = {
    "Truck 1 (Worli)": (19.0178, 72.8478),
    "Truck 2 (Bandra)": (19.0596, 72.8295),
    "Truck 3 (Andheri)": (19.1136, 72.8697),
    "Truck 4 (Kurla)": (19.0726, 72.8844),
    "Truck 5 (Borivali)": (19.2307, 72.8567)
}
DEONAR_DUMPING = (19.0550, 72.9250) # Final Disposal Point

@st.cache_data
def load_and_clean_data():
    target = 'data.csv'
    if not os.path.exists(target):
        all_csvs = [f for f in os.listdir('.') if f.endswith('.csv')]
        if all_csvs: target = all_csvs[0]
        else: return None
    try:
        df = pd.read_csv(target, sep=None, engine='python')
        df.columns = df.columns.str.strip()
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True, errors='coerce')
        # Get latest status for 50 unique bins
        return df.sort_values('timestamp').groupby('bin_id').tail(1)
    except: return None

def get_dist(p1, p2):
    return ((p1[0]-p2[0])*2 + (p1[1]-p2[1])2)*0.5

# --- 2. ASSIGNMENT & ROUTING ENGINE ---
def assign_bins_to_trucks(bins_df, garages):
    """The Assignment Problem: Link each bin to the nearest garage."""
    bins = bins_df.copy()
    def find_nearest_truck(row):
        bin_loc = (row['bin_location_lat'], row['bin_location_lon'])
        # Find distance to all 5 garages
        distances = {name: get_dist(bin_loc, coords) for name, coords in garages.items()}
        return min(distances, key=distances.get) # Returns the name of the nearest truck
    
    bins['assigned_truck'] = bins.apply(find_nearest_truck, axis=1)
    return bins

def calculate_truck_route(start_coords, end_coords, assigned_bins):
    """Greedy Route for a specific truck: Garage -> Bins -> Deonar"""
    current_pos = start_coords
    unvisited = assigned_bins.copy()
    route_points = [start_coords]
    
    # Limit to top 8 bins per truck to keep QR code stable (Google Maps limit)
    unvisited = unvisited.sort_values('bin_fill_percent', ascending=False).head(8)
    
    while not unvisited.empty:
        unvisited['d'] = unvisited.apply(lambda x: get_dist(current_pos, (x['bin_location_lat'], x['bin_location_lon'])), axis=1)
        closest_idx = unvisited['d'].idxmin()
        target = (unvisited.loc[closest_idx, 'bin_location_lat'], unvisited.loc[closest_idx, 'bin_location_lon'])
        route_points.append(target)
        current_pos = target
        unvisited = unvisited.drop(closest_idx)
    
    route_points.append(end_coords)
    return route_points

# --- 3. UI DASHBOARD ---
st.title("🚛 Smart Waste Management: AI Multi-Fleet Dispatcher")

df_latest = load_and_clean_data()

if df_latest is not None:
    # --- SIDEBAR CONTROLS ---
    st.sidebar.header("Fleet Control Panel")
    selected_truck = st.sidebar.selectbox("Select Active Truck to View Mission", list(GARAGES.keys()))
    threshold = st.sidebar.slider("Urgency Threshold (Fill %)", 0, 100, 75)
    
    # Run the Assignment Logic
    assigned_df = assign_bins_to_trucks(df_latest, GARAGES)
    
    # Filter for full bins assigned to the SELECTED TRUCK
    truck_specific_bins = assigned_df[(assigned_df['assigned_truck'] == selected_truck) & 
                                     (assigned_df['bin_fill_percent'] >= threshold)]
    
    # Calculate Mission Sequence
    garage_loc = GARAGES[selected_truck]
    mission_sequence = calculate_truck_route(garage_loc, DEONAR_DUMPING, truck_specific_bins)

    # Dashboard Stats
    c1, c2, c3 = st.columns(3)
    c1.metric("Active Mission", selected_truck)
    c2.metric("Pickups Assigned", len(truck_specific_bins))
    c3.metric("Goal", "Deonar Disposal Yard")

    # --- 4. MAP VISUALIZATION ---
    @st.cache_resource
    def load_road_network():
        # Large area covering all garages to Deonar
        return ox.graph_from_point((19.04, 72.88), dist=8000, network_type='drive')

    with st.spinner(f"AI is calculating the path for {selected_truck}..."):
        try:
            G = load_road_network()
            m = folium.Map(location=[19.04, 72.88], zoom_start=12, tiles="CartoDB positron")

            # 1. Plot all Garages
            for name, coords in GARAGES.items():
                is_selected = (name == selected_truck)
                folium.Marker(coords, popup=name, 
                              icon=folium.Icon(color='blue' if is_selected else 'gray', icon='truck', prefix='fa')).add_to(m)
            
            # 2. Plot Deonar
            folium.Marker(DEONAR_DUMPING, popup="DEONAR DUMPING GROUND", 
                          icon=folium.Icon(color='black', icon='home', prefix='fa')).add_to(m)

            # 3. Draw Selected Truck Route
            path_coords = []
            for i in range(len(mission_sequence)-1):
                try:
                    n1 = ox.nearest_nodes(G, mission_sequence[i][1], mission_sequence[i][0])
                    n2 = ox.nearest_nodes(G, mission_sequence[i+1][1], mission_sequence[i+1][0])
                    route = nx.shortest_path(G, n1, n2, weight='length')
                    path_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in route])
                except:
                    path_coords.append([mission_sequence[i][0], mission_sequence[i][1]])
                    path_coords.append([mission_sequence[i+1][0], mission_sequence[i+1][1]])

            if path_coords:
                folium.PolyLine(path_coords, color="#e74c3c", weight=6, opacity=0.8).add_to(m)

            # 4. Plot all Bins with Logic
            for _, row in assigned_df.iterrows():
                # Logic: Red if >= threshold AND assigned to the CURRENT TRUCK
                # Green otherwise (or Orange if >= threshold but assigned to someone else)
                is_full = row['bin_fill_percent'] >= threshold
                is_mine = row['assigned_truck'] == selected_truck
                
                if is_full and is_mine: color = 'red' # My pickup
                elif is_full and not is_mine: color = 'orange' # Other truck's pickup
                else: color = 'green' # Not full
                
                folium.Marker(
                    [row['bin_location_lat'], row['bin_location_lon']], 
                    popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}% (Truck: {row['assigned_truck']})",
                    icon=folium.Icon(color=color, icon='trash', prefix='fa')
                ).add_to(m)

            st_folium(m, width=1200, height=550)

        except Exception as e:
            st.error(f"Map Error: {e}")

    # --- 5. DRIVER NAVIGATION QR ---
    if not truck_specific_bins.empty:
        st.subheader(f"📲 Driver Navigation for {selected_truck}")
        
        origin = f"{garage_loc[0]},{garage_loc[1]}"
        dest = f"{DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}"
        # Waypoints are the bins specifically for this truck
        waypoints = "|".join([f"{lat},{lon}" for lat, lon in mission_sequence[1:-1]])
        
        google_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={dest}&waypoints={waypoints}&travelmode=driving"
        
        c_qr, c_txt = st.columns([1, 4])
        with c_qr:
            qr = qrcode.make(google_url)
            buf = BytesIO()
            qr.save(buf)
            st.image(buf, width=180)
        with c_txt:
            st.success(f"Mission Ready: This route visits {len(truck_specific_bins)} bins assigned to you.")
            st.info("*Presentation Tip:* Show the judges how the route only includes the *Red Bins. Notice how the **Orange Bins* are also full, but are assigned to a different truck to save fuel.")
else:
    st.error("Please upload your 'data.csv' to GitHub.")
