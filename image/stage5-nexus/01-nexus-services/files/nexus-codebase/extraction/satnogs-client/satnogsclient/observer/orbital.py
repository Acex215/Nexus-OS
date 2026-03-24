import logging
import sys
from datetime import datetime

import ephem
import pytz

LOGGER = logging.getLogger(__name__)


def pinpoint(observer_dict, satellite_dict, timestamp=None):
    """Provides azimuth and altitude of tracked object.

    args:
        observer_dict: dictionary with details of observation point.
        satellite_dict: dictionary with details of satellite.
        time: timestamp we want to use for pinpointing the observed object.

        returns:
            Dictionary containing azimuth, altitude and "ok" for error detection.
    """
    # pylint: disable=assigning-non-slot
    # Disable until pylint 2.4 is released, see
    # https://github.com/PyCQA/pylint/issues/2807
    # observer object
    if all(x in observer_dict for x in ('lat', 'lon', 'elev')):
        LOGGER.debug('Observer data: %s', observer_dict)
        observer = ephem.Observer()
        observer.lon = str(observer_dict['lon'])
        observer.lat = str(observer_dict['lat'])
        observer.elevation = float(observer_dict['elev'])
    else:
        LOGGER.error('Something went wrong: %s', observer_dict)
        return {'ok': False}

    # satellite object
    if all(x in satellite_dict for x in ('tle0', 'tle1', 'tle2')):
        LOGGER.debug('Satellite data: %s', satellite_dict)
        tle0 = str(satellite_dict['tle0'])
        tle1 = str(satellite_dict['tle1'])
        tle2 = str(satellite_dict['tle2'])
        try:
            satellite = ephem.readtle(tle0, tle1, tle2)
        except ValueError:
            LOGGER.error('Something went wrong: %s', satellite_dict)
            LOGGER.error(sys.exc_info()[0])
            return {'ok': False}
    else:
        return {'ok': False}

    # time of observation
    if not timestamp:
        timestamp = datetime.now(pytz.utc)

    # observation calculation
    observer.date = timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
    satellite.compute(observer)
    calculated_data = {
        'alt': satellite.alt,
        'az': satellite.az,
        'rng': satellite.range,
        'rng_vlct': satellite.range_velocity,
        'ok': True
    }

    LOGGER.debug('Calculated data: %s', calculated_data)
    return calculated_data
