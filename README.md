# overpass-geojson-to-csv
A Python script that takes Overpass Turbo geoJSON exports and converts them into csv files with coordinates and hyperlinks to both Google Maps and Google Street View.

How to use - run the overpass_geojson_to_csv.python file and select the Overpass Turbo geoJSON file you wish to convert. The new csv that is created will be saved to wherever the original geoJSON was selected from.

For example:
- GeoJSON on Desktop → CSV saved to Desktop.
- GeoJSON in Downloads → CSV saved to Downloads.
- GeoJSON in Documents → CSV saved to Documents.

from there you can simply import the csv into google sheets and you will have all osm nodes with both latitude, longitude and both the google maps and street view links all ready to go.
