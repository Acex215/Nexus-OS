"""SatNOGS Client module initialization"""
import logging
import logging.config
import sys
import time

import sentry_sdk

from satnogsclient import config, settings
from satnogsclient.locator import locator
from satnogsclient.scheduler.tasks import status_listener

__author__ = config.AUTHOR
__email__ = config.EMAIL
__version__ = config.VERSION

logging.basicConfig(format=settings.LOG_FORMAT,
                    level=getattr(logging, settings.LOG_LEVEL),
                    style='{')
LOGGER = logging.getLogger(__name__)

if settings.SENTRY_ENABLED:
    sentry_sdk.init(settings.SENTRY_DSN, release='satnogs-client@{}'.format(__version__))
    with sentry_sdk.configure_scope() as scope:
        scope.user = {'id': settings.SATNOGS_STATION_ID}


def main():
    """Main function"""
    if not settings.validate(LOGGER):
        LOGGER.error('Settings are invalid, exiting...')
        sys.exit(-1)

    LOGGER.info('Starting status listener thread...')
    gps_locator = locator.Locator()
    gps_locator.update_location()
    status_listener()
    LOGGER.info('Configuration valid, satnogs-client for station'
                ' %d started successfully.', settings.SATNOGS_STATION_ID)
    while True:
        time.sleep(10)
