import osmnx as ox
import networkx as nx
import qrcode
from io import BytesIO

# --- 1. ROAD NETWORK CACHING (The "Blink-Free" Secret) ---
# We cache the actual map of Mumbai so it never has to reload
@st.cache_resource
def get_road_network():
    # Covers a 10km radius around Mumbai center
    return ox.graph_from_point((19.0760, 72.8777), dist=10000, network_type='drive')

# --- Route Optimization Page ---
elif page == "Route Optimization":
    st.title("🚛 AI Multi-Fleet Dispatcher & Navigation")
    
    # Define Garages (From your stable code)
    GARAGES = {
        "Truck 1 (Worli)": (19.0178, 72.8478),
        "Truck 2 (Bandra)": (19.0596, 72.8295),
        "Truck 3 (Andheri)": (19.1136, 72.8697),
        "Truck 4 (Kurla)": (19.0726, 72.8844),
        "Truck 5 (Borivali)": (19.2307, 72.8567)
    }
    DEONAR_DUMPING = (19.0550, 72.9250)

    # Sidebar Controls
    st.sidebar.header("Fleet Control Panel")
    selected_truck = st.sidebar.selectbox("Active Truck", list(GARAGES.keys()))
    threshold = st.sidebar.slider("Urgency Threshold (Fill %)", 0, 100, 75)

    # Logic: Assign bins to the nearest truck (Assignment Problem)
    def assign_nearest(row):
        bin_loc = (row['bin_location_lat'], row['bin_location_lon'])
        distances = {name: ((bin_loc[0]-g[0])*2 + (bin_loc[1]-g[1])2)*0.5 for name, g in GARAGES.items()}
        return min(distances, key=distances.get)

    df['assigned_truck'] = df.apply(assign_nearest, axis=1)
    
    # Filter bins for the selected truck that are over the threshold
    my_bins = df[(df['assigned_truck'] == selected_truck) & (df['bin_fill_percent'] >= threshold)]
    
    # Stats
    c1, c2, c3 = st.columns(3)
    c1.metric("Selected Vehicle", selected_truck)
    c2.metric("Assigned Pickups", len(my_bins))
    c3.metric("Final Depot", "Deonar")

    # --- MAP RENDERING ---
    try:
        G = get_road_network() # Loads from cache (Zero Blink)
        m = folium.Map(location=[19.0760, 72.8777], zoom_start=12, tiles="CartoDB positron")

        # 1. Plot Bins
        for _, row in df.iterrows():
            is_mine = (row['assigned_truck'] == selected_truck)
            is_full = (row['bin_fill_percent'] >= threshold)
            
            if is_full and is_mine: color = 'red'
            elif is_full and not is_mine: color = 'orange'
            else: color = 'green'
            
            folium.Marker(
                [row['bin_location_lat'], row['bin_location_lon']],
                popup=f"Bin {row['bin_id']}: {row['bin_fill_percent']}%",
                icon=folium.Icon(color=color, icon='trash', prefix='fa')
            ).add_to(m)

        # 2. Draw Optimized Route (Real Road Paths)
        garage_loc = GARAGES[selected_truck]
        # Simple mission sequence: Garage -> Bins -> Deonar
        mission_points = [garage_loc] + list(zip(my_bins['bin_location_lat'], my_bins['bin_location_lon'])) + [DEONAR_DUMPING]
        
        path_coords = []
        for i in range(len(mission_points)-1):
            n1 = ox.nearest_nodes(G, mission_points[i][1], mission_points[i][0])
            n2 = ox.nearest_nodes(G, mission_points[i+1][1], mission_points[i+1][0])
            route = nx.shortest_path(G, n1, n2, weight='length')
            path_coords.extend([[G.nodes[node]['y'], G.nodes[node]['x']] for node in route])
        
        if path_coords:
            folium.PolyLine(path_coords, color="#e74c3c", weight=6, opacity=0.8).add_to(m)

        # Display Map
        st_folium(m, width=1100, height=600, key="optimized_map")

        # --- QR CODE GENERATION ---
        if not my_bins.empty:
            st.subheader(f"📲 Driver Navigation: {selected_truck}")
            # Generate Google Maps URL
            origin = f"{garage_loc[0]},{garage_loc[1]}"
            dest = f"{DEONAR_DUMPING[0]},{DEONAR_DUMPING[1]}"
            waypoints = "|".join([f"{lat},{lon}" for lat, lon in zip(my_bins['bin_location_lat'], my_bins['bin_location_lon'])])
            google_url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={dest}&waypoints={waypoints}&travelmode=driving"
            
            qr = qrcode.make(google_url)
            buf = BytesIO()
            qr.save(buf)
            st.image(buf, width=200, caption="Scan to start Mission")

    except Exception as e:
        st.error(f"Waiting for Map Network: {e}")
