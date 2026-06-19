from flask import Flask, render_template, jsonify
import folium
import requests
from geopy.geocoders import Nominatim
from propagation import calculate_muf_map, get_solar_indices
import threading
import time

app = Flask(__name__)

# Configuration
STATION_ADDRESS = "19390 Red Feather Court, Apple Valley, CA, USA"
INTERVAL = 900  # Refresh interval in seconds (15 minutes)
last_update_time = None

# Geocode the station location
geolocator = Nominatim(user_agent="hf_propagation")
location = geolocator.geocode(STATION_ADDRESS)
station_lat, station_lon = location.latitude, location.longitude

def refresh_map():
    global last_update_time
    while True:
        try:
            solar_indices = get_solar_indices()
            muf_20m = calculate_muf_map(station_lat, station_lon, 14.000, 14.350)
            muf_40m = calculate_muf_map(station_lat, station_lon, 7.000, 7.300)
            last_update_time = time.time()
        except Exception as e:
            print(f"Error refreshing map: {e}")
        time.sleep(INTERVAL)

@app.route('/')
def index():
    return render_template('index.html', solar_indices=get_solar_indices(), last_update_time=last_update_time)

@app.route('/muf_map/<band>')
def muf_map(band):
    if band == '20m':
        muf_data = calculate_muf_map(station_lat, station_lon, 14.000, 14.350)
    elif band == '40m':
        muf_data = calculate_muf_map(station_lat, station_lon, 7.000, 7.300)
    else:
        return jsonify({'error': 'Invalid band'}), 400
    return jsonify(muf_data)

if __name__ == '__main__':
    threading.Thread(target=refresh_map).start()
    app.run(debug=True)
