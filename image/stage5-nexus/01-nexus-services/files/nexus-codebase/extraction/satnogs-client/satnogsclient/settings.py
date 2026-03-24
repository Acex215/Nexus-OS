"""SatNOGS Client settings file"""
import os
from distutils.util import strtobool  # pylint: disable=E0401,E0611
from os import environ

from dotenv import load_dotenv
from validators.url import url


def _cast_or_none(func, value):
    try:
        return func(value)
    except (ValueError, TypeError):
        return None


try:
    load_dotenv()
except EnvironmentError:
    # XXX: Workaround for readthedocs  # pylint: disable=fixme
    pass

# Ground station information
SATNOGS_API_TOKEN = environ.get('SATNOGS_API_TOKEN', None)
SATNOGS_PRE_OBSERVATION_SCRIPT = environ.get('SATNOGS_PRE_OBSERVATION_SCRIPT', None)
SATNOGS_POST_OBSERVATION_SCRIPT = environ.get('SATNOGS_POST_OBSERVATION_SCRIPT', None)
SATNOGS_STATION_ID = _cast_or_none(int, environ.get('SATNOGS_STATION_ID', None))
SATNOGS_STATION_LAT = _cast_or_none(float, environ.get('SATNOGS_STATION_LAT', None))
SATNOGS_STATION_LON = _cast_or_none(float, environ.get('SATNOGS_STATION_LON', None))
SATNOGS_STATION_ELEV = _cast_or_none(float, environ.get('SATNOGS_STATION_ELEV', None))
SATNOGS_GPSD_CLIENT_ENABLED = bool(strtobool(environ.get('SATNOGS_GPSD_CLIENT_ENABLED', 'False')))
SATNOGS_GPSD_HOST = environ.get('SATNOGS_GPSD_HOST', '127.0.0.1')
SATNOGS_GPSD_PORT = _cast_or_none(int, environ.get('SATNOGS_GPSD_PORT', 2947))
SATNOGS_GPSD_TIMEOUT = _cast_or_none(int, environ.get('SATNOGS_GPSD_TIMEOUT', 30))

# Output paths
SATNOGS_APP_PATH = environ.get('SATNOGS_APP_PATH', '/tmp/.satnogs')
SATNOGS_OUTPUT_PATH = environ.get('SATNOGS_OUTPUT_PATH', '/tmp/.satnogs/data')
SATNOGS_COMPLETE_OUTPUT_PATH = environ.get('SATNOGS_COMPLETE_OUTPUT_PATH', '')
SATNOGS_INCOMPLETE_OUTPUT_PATH = environ.get('SATNOGS_INCOMPLETE_OUTPUT_PATH',
                                             '/tmp/.satnogs/data/incomplete')
SATNOGS_ARTIFACTS_OUTPUT_PATH = environ.get('SATNOGS_ARTIFACTS_OUTPUT_PATH',
                                            '/tmp/.satnogs/artifacts')

for p in (SATNOGS_APP_PATH, SATNOGS_OUTPUT_PATH, SATNOGS_COMPLETE_OUTPUT_PATH,
          SATNOGS_INCOMPLETE_OUTPUT_PATH):
    if p and not os.path.exists(p):
        os.mkdir(p)

SATNOGS_REMOVE_RAW_FILES = bool(strtobool(environ.get('SATNOGS_REMOVE_RAW_FILES', 'True')))
SATNOGS_KEEP_ARTIFACTS = bool(strtobool(environ.get('SATNOGS_KEEP_ARTIFACTS', 'False')))

SATNOGS_VERIFY_SSL = bool(strtobool(environ.get('SATNOGS_VERIFY_SSL', 'True')))

SATNOGS_NETWORK_API_URL = environ.get('SATNOGS_NETWORK_API_URL',
                                      'https://network.satnogs.org/api/')
SATNOGS_NETWORK_API_QUERY_INTERVAL = _cast_or_none(int,
                                                   environ.get(
                                                       'SATNOGS_NETWORK_API_QUERY_INTERVAL',
                                                       60))  # In seconds
SATNOGS_NETWORK_API_POST_INTERVAL = _cast_or_none(int,
                                                  environ.get('SATNOGS_NETWORK_API_POST_INTERVAL',
                                                              180))  # In seconds
SATNOGS_NETWORK_API_TIMEOUT = 1800  # In seconds
GNURADIO_UDP_PORT = 16886
GNURADIO_IP = '127.0.0.1'

SATNOGS_ROT_ENABLED = bool(strtobool(environ.get('SATNOGS_ROT_ENABLED', 'True')))
SATNOGS_ROT_MODEL = environ.get('SATNOGS_ROT_MODEL', 'ROT_MODEL_DUMMY')
SATNOGS_ROT_BAUD = int(environ.get('SATNOGS_ROT_BAUD', 19200))
SATNOGS_ROT_PORT = environ.get('SATNOGS_ROT_PORT', '/dev/ttyUSB0')
SATNOGS_RIG_IP = environ.get('SATNOGS_RIG_IP', '127.0.0.1')
SATNOGS_RIG_PORT = int(environ.get('SATNOGS_RIG_PORT', 4532))
SATNOGS_ROT_THRESHOLD = int(environ.get('SATNOGS_ROT_THRESHOLD', 4))
SATNOGS_ROT_FLIP = bool(strtobool(environ.get('SATNOGS_ROT_FLIP', 'False')))
SATNOGS_ROT_FLIP_ANGLE = int(environ.get('SATNOGS_ROT_FLIP_ANGLE', 75))

# Common script parameters
SATNOGS_SOAPY_RX_DEVICE = environ.get('SATNOGS_SOAPY_RX_DEVICE', None)
SATNOGS_RX_SAMP_RATE = environ.get('SATNOGS_RX_SAMP_RATE', None)
SATNOGS_RX_BANDWIDTH = environ.get('SATNOGS_RX_BANDWIDTH', None)
SATNOGS_DOPPLER_CORR_PER_SEC = environ.get('SATNOGS_DOPPLER_CORR_PER_SEC', None)
SATNOGS_LO_OFFSET = environ.get('SATNOGS_LO_OFFSET', None)
SATNOGS_PPM_ERROR = environ.get('SATNOGS_PPM_ERROR', None)
SATNOGS_GAIN_MODE = environ.get('SATNOGS_GAIN_MODE', 'Overall')
SATNOGS_RF_GAIN = environ.get('SATNOGS_RF_GAIN', None)
SATNOGS_ANTENNA = environ.get('SATNOGS_ANTENNA', None)
SATNOGS_DEV_ARGS = environ.get('SATNOGS_DEV_ARGS', None)
SATNOGS_STREAM_ARGS = environ.get('SATNOGS_STREAM_ARGS', None)
SATNOGS_TUNE_ARGS = environ.get('SATNOGS_TUNE_ARGS', None)
SATNOGS_OTHER_SETTINGS = environ.get('SATNOGS_OTHER_SETTINGS', None)
SATNOGS_DC_REMOVAL = environ.get('SATNOGS_DC_REMOVAL', None)
SATNOGS_BB_FREQ = environ.get('SATNOGS_BB_FREQ', None)

ENABLE_IQ_DUMP = bool(strtobool(environ.get('ENABLE_IQ_DUMP', 'False')))
IQ_DUMP_FILENAME = environ.get('IQ_DUMP_FILENAME', None)
DISABLE_DECODED_DATA = bool(strtobool(environ.get('DISABLE_DECODED_DATA', 'False')))
UDP_DUMP_HOST = environ.get('UDP_DUMP_HOST', None)
UDP_DUMP_PORT = int(environ.get('UDP_DUMP_PORT', 57356))

# gr-satellites Integration
GR_SATELLITES_ENABLED = bool(strtobool(environ.get('GR_SATELLITES_ENABLED', 'False')))
GR_SATELLITES_ZMQ_PORT = int(environ.get('GR_SATELLITES_ZMQ_PORT', 0))
GR_SATELLITES_APP = environ.get('GR_SATELLITES_APP', 'gr_satellites')
GR_SATELLITES_KEEPLOGS = bool(strtobool(environ.get('GR_SATELLITES_KEEPLOGS', 'False')))

# Upload settings
SATNOGS_UPLOAD_AUDIO_FILES = bool(strtobool(environ.get('SATNOGS_UPLOAD_AUDIO_FILES', 'True')))
SATNOGS_UPLOAD_WATERFALL_FILES = bool(
    strtobool(environ.get('SATNOGS_UPLOAD_WATERFALL_FILES', 'True')))

# Artifacts settings
ARTIFACTS_ENABLED = bool(strtobool(environ.get('SATNOGS_ARTIFACTS_ENABLED', 'False')))
ARTIFACTS_API_URL = environ.get('SATNOGS_ARTIFACTS_API_URL', 'https://db.satnogs.org/api/')
ARTIFACTS_API_POST_INTERVAL = _cast_or_none(int,
                                            environ.get('SATNOGS_ARTIFACTS_API_POST_INTERVAL',
                                                        180))  # In seconds
ARTIFACTS_API_TIMEOUT = 1800  # In seconds
ARTIFACTS_API_TOKEN = environ.get('SATNOGS_ARTIFACTS_API_TOKEN', None)

# Waterfall settings
SATNOGS_WATERFALL_AUTORANGE = bool(strtobool(environ.get('SATNOGS_WATERFALL_AUTORANGE', 'True')))
SATNOGS_WATERFALL_MIN_VALUE = int(environ.get('SATNOGS_WATERFALL_MIN_VALUE', -100))
SATNOGS_WATERFALL_MAX_VALUE = int(environ.get('SATNOGS_WATERFALL_MAX_VALUE', -50))

# Logging configuration
LOG_FORMAT = '{levelname:<8s} {name:<31s} {message}'
LOG_LEVEL = environ.get('SATNOGS_LOG_LEVEL', 'WARNING')
SCHEDULER_LOG_LEVEL = environ.get('SATNOGS_SCHEDULER_LOG_LEVEL', 'WARNING')

# Sentry
SENTRY_DSN = environ.get('SENTRY_DSN',
                         'https://5e18316a65b1457c99fe81bf869e26d6@sentry.io/2818206')
SENTRY_ENABLED = bool(strtobool(environ.get('SENTRY_ENABLED', 'False')))

REQUIRED_VARIABLES = [
    'SATNOGS_API_TOKEN', 'SATNOGS_STATION_ID', 'SATNOGS_SOAPY_RX_DEVICE', 'SATNOGS_RX_SAMP_RATE',
    'SATNOGS_ANTENNA'
]


def validate(logger):
    """Validate the provided settings:
    - Check for the existance of all required variables
    - Validate format of the provided value for some required variables

    Since this module has to be loaded before the logger has been initialized,
    this method requires a configured logger to be passed.

    Arguments:
    logger -- the output logger
    """
    settings_valid = True

    # Get all variable in global scobe (this includes all global variables from this module)
    settings = globals()

    for variable_name in REQUIRED_VARIABLES:
        # Check the value of the variable defined in settings
        if not settings[variable_name]:
            logger.error('%s not configured but required', variable_name)
            settings_valid = False

    try:
        url(SATNOGS_NETWORK_API_URL)
    except ValueError:
        logger.error('Invalid SATNOGS_NETWORK_API_URL: %s', SATNOGS_NETWORK_API_URL)
        settings_valid = False

    if not SATNOGS_GPSD_CLIENT_ENABLED:
        # Ensure location is configured when not using GPS
        for variable_name in [
                'SATNOGS_STATION_LAT', 'SATNOGS_STATION_LON', 'SATNOGS_STATION_ELEV'
        ]:
            if variable_name not in environ:
                logger.error('%s not configured but required', variable_name)
                settings_valid = False
            elif settings[variable_name] is None:
                logger.error('%s has invalid value "%s"', variable_name, environ[variable_name])
                settings_valid = False

    return settings_valid
