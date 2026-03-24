import logging
import logging.config
import time

import gps

from satnogsclient import settings

LOGGER = logging.getLogger(__name__)


class Locator(object):

    def __init__(self):
        self.timeout = settings.SATNOGS_GPSD_TIMEOUT

    @staticmethod
    def show_location(gpsd):
        LOGGER.debug('mode       %d ', gpsd.fix.mode)
        LOGGER.debug('status     %d ', gpsd.status)
        LOGGER.debug('latitude   %f', gpsd.fix.latitude)
        LOGGER.debug('longitude  %f', gpsd.fix.longitude)
        LOGGER.debug('altitude   %f', gpsd.fix.altitude)
        LOGGER.debug('hdop       %d', gpsd.hdop)

    def update_location(self):
        if settings.SATNOGS_GPSD_CLIENT_ENABLED is not True:
            return
        no_timeout = not self.timeout
        if (settings.SATNOGS_STATION_LAT is None or settings.SATNOGS_STATION_LON is None
                or settings.SATNOGS_STATION_ELEV is None):
            no_timeout = True
            LOGGER.warning('No default coordinates, GPS timeout disabled')
        else:
            LOGGER.debug('Last coordinates %f %f %f', settings.SATNOGS_STATION_LAT,
                         settings.SATNOGS_STATION_LON, settings.SATNOGS_STATION_ELEV)
        end_time = time.time() + self.timeout

        try:
            LOGGER.info('Connecting to GPSD %s:%d', settings.SATNOGS_GPSD_HOST,
                        settings.SATNOGS_GPSD_PORT)
            gpsd = gps.gps(mode=gps.WATCH_ENABLE,
                           host=settings.SATNOGS_GPSD_HOST,
                           port=settings.SATNOGS_GPSD_PORT)
            LOGGER.debug('Waiting for GPS (timeout %ds)', self.timeout)
            while gpsd.read() == 0 and gpsd.fix.mode not in [gps.MODE_2D, gps.MODE_3D] \
                    and (time.time() < end_time or no_timeout):
                self.show_location(gpsd)
        except StopIteration:
            LOGGER.error('GPSD connection failed')
            return
        if gpsd.fix.mode in [gps.MODE_2D, gps.MODE_3D]\
                and gps.isfinite(gpsd.fix.latitude) \
                and gps.isfinite(gpsd.fix.longitude) \
                and gps.isfinite(gpsd.fix.altitude):
            settings.SATNOGS_STATION_LAT = gpsd.fix.latitude
            settings.SATNOGS_STATION_LON = gpsd.fix.longitude
            if gpsd.fix.altitude >= 0:
                settings.SATNOGS_STATION_ELEV = gpsd.fix.altitude
            elif settings.SATNOGS_STATION_ELEV is None:
                settings.SATNOGS_STATION_ELEV = 0.0
            LOGGER.debug('Updating coordinates %f %f %f', settings.SATNOGS_STATION_LAT,
                         settings.SATNOGS_STATION_LON, settings.SATNOGS_STATION_ELEV)
        else:
            LOGGER.warning('GPS data invalid, using last known coordinates')
