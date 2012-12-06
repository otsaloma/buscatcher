#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
 Copyright (C) Henri Bergius 2010 <henri.bergius@iki.fi>
 Copyright (C) Osmo Salomaa 2012 <otsaloma@iki.fi>
 Based on adventure_tablet by:
 Copyright (C) Susanna Huhtanen 2010 <ihmis.suski@gmail.com>

 buscatcher.py is free software: you can redistribute it and/or modify it
 under the terms of the GNU General Public License as published by the
 Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 buscatcher.py is distributed in the hope that it will be useful, but
 WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 See the GNU General Public License for more details.

 You should have received a copy of the GNU General Public License along
 with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import gtk, gobject
import point
import urllib, urllib2
import os
import socket
import optparse

gobject.threads_init()
gtk.gdk.threads_init()
import osmgpsmap

location = None
Geoclue = None
options = None
try:
    import Geoclue
except ImportError:
    try:
        import location
    except ImportError:
        print "No location service found"

osso = None
try:
    import osso
except ImportError:
    pass

conic = None
try:
    import conic
except ImportError:
    pass

class buscatcher(gtk.Window):

    def __init__(self, repo_uri, initial_zoom):
        gtk.Window.__init__(self)
        self.location = None
        self.csvfetch = None
        self.buses = {}
        self.stop_fetching = False
        self.initial_zoom = initial_zoom
        self.times_location_found = 0
        self.missing_icons = set()
        self.build_ui(repo_uri)
        self.get_location()

        self.icondir = os.path.expanduser('~/.cache/buscatcher')
        if not os.path.exists(self.icondir):
            os.makedirs(self.icondir)

        # Set a default timeout for our HTTP requests so they don't hang when cell connection is bad
        socket.setdefaulttimeout(10)

    def build_ui(self, repo_uri):
        self.set_default_size(800, 480)
        self.connect('destroy', gtk.main_quit, None)
        self.set_title('Helsinki Bus Catcher')

        self.osm = osmgpsmap.GpsMap(repo_uri=repo_uri)
        self.osm.layer_add(osmgpsmap.GpsMapOsd(show_zoom=True))

        #connect keyboard shortcuts
        self.osm.set_keyboard_shortcut(osmgpsmap.KEY_FULLSCREEN, gtk.gdk.keyval_from_name("F11"))
        self.osm.set_keyboard_shortcut(osmgpsmap.KEY_UP, gtk.gdk.keyval_from_name("Up"))
        self.osm.set_keyboard_shortcut(osmgpsmap.KEY_DOWN, gtk.gdk.keyval_from_name("Down"))
        self.osm.set_keyboard_shortcut(osmgpsmap.KEY_LEFT, gtk.gdk.keyval_from_name("Left"))
        self.osm.set_keyboard_shortcut(osmgpsmap.KEY_RIGHT, gtk.gdk.keyval_from_name("Right"))

        self.add(self.osm)

    def update_bus(self, bus):
        busid = bus['id']
        if busid not in self.buses:
            # First time we see this bus
            self.buses[busid] = bus
        else:
            self.buses[busid].update(bus)
        bus = self.buses[busid]
        try:
            self.osm.remove_image(bus["type_icon"])
        except Exception:
            pass
        try:
            self.osm.remove_image(bus["route_icon"])
        except Exception:
            pass
        _pixbuf = gtk.gdk.pixbuf_new_from_file
        try:
            bus["type_icon"] = _pixbuf(bus["type_icon_path"])
            self.osm.add_image(bus["lat"], bus["lon"], bus["type_icon"])
        except Exception:
            print "Failed to add image for %s" % repr(busid)
        try:
            bus["route_icon"] = _pixbuf(bus["route_icon_path"])
            self.osm.add_image(bus["lat"], bus["lon"], bus["route_icon"])
        except Exception:
            pass

    def remove_bus(self, busid):
        bus = self.buses[busid]
        try:
            self.osm.remove_image(bus["type_icon"])
        except Exception:
            pass
        try:
            self.osm.remove_image(bus["route_icon"])
        except Exception:
            pass
        self.buses.pop(busid)

    def get_location(self):
        # if options.no_update_position:
        #     return
        if Geoclue:
            self.get_location_geoclue()
        elif location:
            self.get_location_liblocation()

    def set_location(self, location):
        # It seems that about the third location data is correct.
        # (Previous ones are cached or rough values?)
        if (self.times_location_found > 3 and
            options.no_update_position): return
        # Avoid jumps to weird places outside Uusimaa.
        if not 59.82 < location.lat < 61.08: return
        if not 22.54 < location.lon < 26.77: return
        self.location = location
        self.times_location_found += 1
        self.osm.set_mapcenter(self.location.lat,
                               self.location.lon,
                               self.initial_zoom)

        if self.csvfetch is None:
            self.csvfetch = gobject.timeout_add(options.update_interval, self.fetch_csv)

    def get_location_liblocation(self):
        self.control = location.GPSDControl.get_default()
        self.device = location.GPSDevice()
        self.control.set_properties(preferred_method=location.METHOD_USER_SELECTED,
            preferred_interval=location.INTERVAL_10S)

        self.device.connect("changed", self.location_changed_liblocation, self.control)
        self.control.start()
        if self.device.fix:
            if self.device.fix[1] & location.GPS_DEVICE_LATLONG_SET:
                # We have a "hot" fix
                self.set_location(point.point(self.device.fix[4], self.device.fix[5]))

    def get_location_geoclue(self):
        self.geoclue = Geoclue.DiscoverLocation()
        self.geoclue.init()
        providers = self.geoclue.get_available_providers()
        selected_provider = None
        lat_accuracy = 0
        for provider in providers:
            if not provider['position']:
                continue
            if provider['service'] == 'org.freedesktop.Geoclue.Providers.Example':
                continue
            self.geoclue.set_position_provider(provider['name'])
            coordinates = self.geoclue.get_location_info()
            # Ugly hack for determining most accurate provider as python-geoclue doesn't pass this info
            lat_accuracy_provider = len(str(coordinates['latitude']))
            if lat_accuracy_provider > lat_accuracy:
                lat_accuracy = lat_accuracy_provider
                selected_provider = provider['name']

        self.geoclue.set_position_provider(selected_provider)
        self.geoclue.position.connect_to_signal("PositionChanged", self.location_changed_geoclue)

        try:
            self.set_location(point.point(coordinates['latitude'], coordinates['longitude']))
        except KeyError, e:
            #TODO: Define exception for no location
            pass

    def location_changed_liblocation(self, device, control):
        if not self.device:
            return
        if self.device.fix:
            if self.device.fix[1] & location.GPS_DEVICE_LATLONG_SET:
                self.set_location(point.point(self.device.fix[4], self.device.fix[5]))

    def location_changed_geoclue(self, fields, timestamp, latitude, longitude, altitude, accuracy):
        self.set_location(point.point(latitude, longitude))

    def tracking_start(self):
        self.stop_fetching = False
        if self.csvfetch is None:
            self.csvfetch = gobject.timeout_add(options.update_interval, self.fetch_csv)
        if Geoclue:
            pass
        elif location:
            self.control.start()

    def tracking_stop(self):
        self.stop_fetching = True
        if Geoclue:
            pass
        elif location:
            self.control.stop()

    def build_csv_url(self):
        # See HSL Live 1.6 documentation.
        # http://developer.reittiopas.fi/pages/en/other-apis.php
        bbox = self.osm.get_bbox()
        lat = osmgpsmap.point_new_radians(bbox[0], bbox[2]).get_degrees()
        lon = osmgpsmap.point_new_radians(bbox[1], bbox[3]).get_degrees()
        return ("http://83.145.232.209:10001/?type=vehicles"
                "&lng1=%.6f&lat1=%.6f&lng2=%.6f&lat2=%.6f" %
                (min(lon), min(lat), max(lon), max(lat)))

    def fetch_csv(self):
        if self.stop_fetching:
            self.csvfetch = None
            return False

        url = self.build_csv_url()
        opener = urllib2.build_opener()
        opener.addheaders = [('User-agent', 'buscatcher/0.1')]
        try:
            req = opener.open(url)
            csv = req.read(100000)
        except urllib2.HTTPError, e:
            print('CSV HTTP error %s' % (e.code))
            return True
        except urllib2.URLError, e:
            print("CSV Connection failed, error %s" % (e.message))
            return True
        except IOError, e:
            print "CSV Connection failed"
            return True

        self.parse_csv(csv)

        return True

    def parse_csv(self, csv):
        # See HSL Live 1.6 documentation.
        # http://developer.reittiopas.fi/pages/en/other-apis.php
        csv = csv.splitlines()
        prev_ids = self.buses.keys()
        for line in csv:
            items = line.split(";")
            try:
                bus = {"id": items[0],
                       "route": items[1],
                       "lon": float(items[2]),
                       "lat": float(items[3]),
                       "bearing": float(items[4])}

            except Exception:
                continue
            icons = self.download_icons(bus)
            bus["type_icon_path"] = icons[0]
            bus["route_icon_path"] = icons[1]
            self.update_bus(bus)
            if bus["id"] in prev_ids:
                prev_ids.remove(bus["id"])
        for busid in prev_ids:
            self.remove_bus(busid)

    def download_icons(self, bus):
        # Let's borrow icons from the official web interface.
        # http://transport.wspgroup.fi/hklkartta/
        if bus["id"].startswith("RHKL"):
            type_name = "tram"
        elif bus["id"].startswith("metro"):
            type_name = "metro"
        else:
            # TODO: Add trains.
            type_name = "bus"
        bearing = round(bus["bearing"]/45.0)*45
        if bearing > 315: bearing = 0
        type_url = ("http://transport.wspgroup.fi/"
                    "hklkartta/images/vehicles/%s%.0f.png"
                    % (type_name, bearing))

        route_url = ("http://transport.wspgroup.fi/"
                     "hklkartta/images/vehicles/%s.png"
                     % bus["route"])

        type_basename = type_url.split("/")[-1]
        route_basename = route_url.split("/")[-1]
        type_path = os.path.join(self.icondir, type_basename)
        route_path = os.path.join(self.icondir, route_basename)
        if (not type_basename in self.missing_icons and
            not os.path.exists(type_path)):
            print "Downloading " + type_url
            web = urllib.urlopen(type_url)
            # Avoid downloading 404-page HTML.
            if web.info().gettype() == "image/png":
                local = open(type_path, 'w')
                local.write(web.read(10000))
                local.close()
            else:
                # Avoid trying the same icon again.
                self.missing_icons.add(type_basename)
            web.close()
        if (not route_basename in self.missing_icons and
            not os.path.exists(route_path)):
            print "Downloading " + route_url
            web = urllib.urlopen(route_url)
            # Avoid downloading 404-page HTML.
            if web.info().gettype() == "image/png":
                local = open(route_path, 'w')
                local.write(web.read(10000))
                local.close()
            else:
                # Avoid trying the same icon again.
                self.missing_icons.add(route_basename)
            web.close()
        return (type_path, route_path)


if __name__ == "__main__":
    parser = optparse.OptionParser("buscatcher OPTIONS")
    parser.add_option("--update-interval", type="int", default=3000)
    parser.add_option("--initial-lat", type="float", default=60.170424)
    parser.add_option("--initial-lon", type="float", default=24.94070)
    parser.add_option("--initial-zoom", type="int", default=15)
    parser.add_option("--repo-uri", type="str",default="http://tile.openstreetmap.org/#Z/#X/#Y.png")
    parser.add_option("--no-update-position", action="store_true", default=True)
    (options, args) = parser.parse_args()

    if conic:
        # Request Maemo to start an internet connection, as buscatcher doesn't really make sense without one
        connection = conic.Connection()

    u = buscatcher(options.repo_uri, options.initial_zoom)
    initial_location = point.point(options.initial_lat, options.initial_lon)
    u.set_location(initial_location)
    u.show_all()

    if osso:
        import devicemonitor
        osso_c = osso.Context("buscatcher", "0.0.1", False)
        device_monitor = devicemonitor.device_monitor(osso_c)
        device_monitor.set_display_off_cb(u.tracking_stop)
        device_monitor.set_display_on_cb(u.tracking_start)

    gtk.main()
