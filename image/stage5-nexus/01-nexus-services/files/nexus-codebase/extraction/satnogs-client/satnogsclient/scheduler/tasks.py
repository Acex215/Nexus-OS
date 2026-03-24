import base64
import json
import logging
import os
import threading
from datetime import datetime, timedelta
from urllib.parse import urljoin

import pytz
import requests
from dateutil import parser

from satnogsclient import settings
from satnogsclient.locator import locator
from satnogsclient.observer.observer import Observer
from satnogsclient.scheduler import SCHEDULER

LOGGER = logging.getLogger(__name__)
OBSERVER_LOCK = threading.Lock()

# Human-readable names for "SatNOGS observation data" data types
DATA_TYPE_MAP = {
    'payload': 'audio recording',
    'waterfall': 'waterfall image',
    'demoddata': 'data',
}


def spawn_observer(**kwargs):
    """
    Run an observation.

    :param kwargs: Keyword arguments containing 'obj' dict with observation parameters

    Example::

        kwargs['obj'] = {
            'id': 38215,
            'start': '2025-07-31T16:30:02Z',
            'end': '2025-07-31T16:33:50Z',
            'ground_station': 338,
            'tle0': 'FOX-1A (AO-85)',
            'tle1': '1 40967U 15058D   25212.20879382  .00001969  00000+0  18605-3 0  9993',
            'tle2': '2 40967  64.7744 194.6401 0153690 178.4861 181.6749 14.88342386 65750',
            'frequency': 145978500,
            'mode': 'DUV',
            'transmitter': 'ZyjKNJ9KqnTHBCUzAPN5G5',
            'baud': 200.0,
            'max_altitude': 19.0,
            'norad_cat_id': 40967
        }
    """
    obj = kwargs.pop('obj')
    tle = {'tle0': obj['tle0'], 'tle1': obj['tle1'], 'tle2': obj['tle2']}
    end = parser.parse(obj['end'])

    observer = Observer()

    # Get the baudrate. In case of CW baudrate equals the WPM
    baud = 0
    if 'baud' in obj:
        baud = obj['baud']

    setup_kwargs = {
        'observation_id': obj['id'],
        'tle': tle,
        'observation_end': end,
        'frequency': obj['frequency'],
        'mode': obj['mode'],
        'baud': baud
    }

    LOGGER.debug('Observer args: %s', setup_kwargs)

    if observer.setup(**setup_kwargs):
        LOGGER.debug('Spawning observer worker.')
        timeout_timedelta = end - datetime.now(pytz.utc)
        if timeout_timedelta.total_seconds() <= 0:
            timeout_timedelta = timedelta()
        if not OBSERVER_LOCK.acquire(timeout=timeout_timedelta.total_seconds()):
            LOGGER.error('Observer job lock acquiring timed out.')
            return
        try:
            observer.observe()
        except Exception as ex:  # pylint: disable=broad-except
            LOGGER.error('Observation aborted due to an unhandled exception %s', ex, exc_info=True)
        finally:
            OBSERVER_LOCK.release()
    else:
        raise RuntimeError('Error in observer setup.')


def keep_or_remove_file(filename):
    # If set, move uploaded file to `SATNOGS_COMPLETE_OUTPUT_PATH`,
    # otherwise delete it
    if settings.SATNOGS_COMPLETE_OUTPUT_PATH:
        os.rename(os.path.join(settings.SATNOGS_OUTPUT_PATH, filename),
                  os.path.join(settings.SATNOGS_COMPLETE_OUTPUT_PATH, filename))
    else:
        os.remove(os.path.join(settings.SATNOGS_OUTPUT_PATH, filename))


def post_data():
    """PUT observation data back to Network API."""
    LOGGER.debug('Post data started')

    for fil in next(os.walk(settings.SATNOGS_OUTPUT_PATH))[2]:
        file_path = os.path.join(*[settings.SATNOGS_OUTPUT_PATH, fil])
        if (fil.startswith('receiving_satnogs') or fil.startswith('receiving_waterfall')
                or fil.startswith('receiving_data') or not os.stat(file_path).st_size):
            continue
        if fil.startswith('satnogs'):
            # This file is an audio file
            if not settings.SATNOGS_UPLOAD_AUDIO_FILES:
                keep_or_remove_file(fil)
                continue
            observation = {'payload': open(file_path, 'rb')}
        elif fil.startswith('waterfall'):
            # This file is a waterfall image
            if not settings.SATNOGS_UPLOAD_WATERFALL_FILES:
                keep_or_remove_file(fil)
                continue
            observation = {'waterfall': open(file_path, 'rb')}
        elif fil.startswith('data'):
            # This file is a data frame
            # Check if it is serialized using json OR raw data
            try:
                with open(file_path, 'r', encoding='utf-8') as json_string:
                    data = json.load(json_string)
                if not isinstance(data, dict) or 'pdu' not in data.keys():
                    # File can accidentally be parsed as json, but is missing the expected fields.
                    # Thus we assume it is a raw data frame
                    raise ValueError

                # This file is a json-encoded data frame
                observation = {'demoddata': (fil, base64.b64decode(data['pdu']))}
            except ValueError:
                # This file is a raw data frame
                observation = {'demoddata': open(file_path, 'rb')}
        else:
            # This file is of unknown type
            LOGGER.debug('Ignore file: %s', fil)
            continue
        if '_' not in fil:
            continue
        observation_id = fil.split('_')[1]
        upload_observation_data(observation_id, observation, fil)


def upload_observation_data(observation_id, observation, fil):
    """Upload observation data to SatNOGS Network API."""
    base_url = urljoin(settings.SATNOGS_NETWORK_API_URL, 'observations/')
    headers = {'Authorization': 'Token {0}'.format(settings.SATNOGS_API_TOKEN)}

    LOGGER.debug('Trying to PUT observation data for id: %s', observation_id)
    url = urljoin(base_url, observation_id)
    if not url.endswith('/'):
        url += '/'
    LOGGER.debug('PUT file %s to network API', fil)
    LOGGER.debug('URL: %s', url)
    LOGGER.debug('Headers: %s', headers)
    LOGGER.debug('Observation file: %s', observation)
    try:
        response = requests.put(url,
                                headers=headers,
                                files=observation,
                                verify=settings.SATNOGS_VERIFY_SSL,
                                stream=True,
                                timeout=settings.SATNOGS_NETWORK_API_TIMEOUT)
        response.raise_for_status()

        data_type = DATA_TYPE_MAP[list(observation.keys())[0]]
        LOGGER.info('Upload of %s for observation %s successful.', data_type, observation_id)

        keep_or_remove_file(fil)
    except requests.exceptions.Timeout:
        LOGGER.error('Upload of %s for observation %s failed '
                     'due to timeout.', fil, observation_id)
    except requests.exceptions.HTTPError:
        if response.status_code == 404:
            LOGGER.error(
                "Upload of %s for observation %s failed, %s doesn't exist (404)."
                'Probably the observation was deleted.', fil, observation_id, url)

            # Move file to `SATNOGS_INCOMPLETE_OUTPUT_PATH`
            os.rename(os.path.join(settings.SATNOGS_OUTPUT_PATH, fil),
                      os.path.join(settings.SATNOGS_INCOMPLETE_OUTPUT_PATH, fil))
        if response.status_code == 403 and 'has already been uploaded' in response.text:
            LOGGER.error('Upload of %s for observation %s is forbidden, %s\n URL: %s', fil,
                         observation_id, response.text, url)
            keep_or_remove_file(fil)
        else:
            LOGGER.error('Upload of %s for observation %s failed, '
                         'response status code: %s', fil, observation_id, response.status_code)


def get_jobs():
    """Query SatNOGS Network API to GET jobs."""
    gps_locator = locator.Locator()
    gps_locator.update_location()

    url = urljoin(settings.SATNOGS_NETWORK_API_URL, 'jobs/')

    # SatNOGS Network stores the station altitude in an IntegerField, thus
    # ensure query_param.alt is an integer number.
    params = {
        'ground_station': settings.SATNOGS_STATION_ID,
        'lat': settings.SATNOGS_STATION_LAT,
        'lon': settings.SATNOGS_STATION_LON,
        'alt': int(settings.SATNOGS_STATION_ELEV)
    }
    headers = {'Authorization': 'Token {0}'.format(settings.SATNOGS_API_TOKEN)}

    LOGGER.debug('Fetching jobs from network...')
    try:
        response = requests.get(url,
                                params=params,
                                headers=headers,
                                verify=settings.SATNOGS_VERIFY_SSL,
                                timeout=45)
        response.raise_for_status()
    except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as err:
        LOGGER.error('%s', err)
        LOGGER.error('Fetching jobs from network failed.')
        return

    requested_jobs = {job['id']: job for job in response.json()}
    scheduled_jobs = {
        int(job.id): job
        for job in SCHEDULER.get_jobs() if job.name == spawn_observer.__name__
    }

    # dropped - scheduled locally, deleted in Network since then
    # common  - scheduled locally, potentially updated in Network since then
    # new     - not scheduled locally yet
    dropped_job_ids = set(scheduled_jobs) - set(requested_jobs)
    common_job_ids = set(scheduled_jobs) & set(requested_jobs)
    new_job_ids = set(requested_jobs) - set(scheduled_jobs)

    LOGGER.debug('Fetched jobs from network, received %d future observations.',
                 len(requested_jobs))

    for observation_id in dropped_job_ids:
        LOGGER.info('Drop planned observation %s (reason: deleted in network).', observation_id)
        scheduled_jobs[observation_id].remove()

    for observation_id in common_job_ids:
        old_job_params = scheduled_jobs[observation_id].kwargs['obj']
        obj = requested_jobs[observation_id]
        if old_job_params == obj:
            continue

        start = parser.parse(obj['start'])
        job_id = str(obj['id'])
        kwargs = {'obj': obj}

        LOGGER.info('Received updated job for observation %s, starting at %s', job_id,
                    start.isoformat())
        LOGGER.debug('Observation obj: %s', obj)
        SCHEDULER.add_job(spawn_observer,
                          'date',
                          run_date=start,
                          id='{0}'.format(job_id),
                          kwargs=kwargs,
                          replace_existing=True)

    for observation_id in new_job_ids:
        obj = requested_jobs[observation_id]
        start = parser.parse(obj['start'])
        job_id = str(obj['id'])
        kwargs = {'obj': obj}

        LOGGER.info('Received job for observation %s, starting at %s', job_id, start.isoformat())
        LOGGER.debug('Observation obj: %s', obj)
        SCHEDULER.add_job(spawn_observer,
                          'date',
                          run_date=start,
                          id='{0}'.format(job_id),
                          kwargs=kwargs,
                          replace_existing=True)


def status_listener():
    LOGGER.debug('Starting scheduler...')
    SCHEDULER.start()
    SCHEDULER.remove_all_jobs()
    LOGGER.info('Registering `get_jobs` periodic task (%d sec. interval)',
                settings.SATNOGS_NETWORK_API_QUERY_INTERVAL)
    SCHEDULER.add_job(get_jobs,
                      'interval',
                      seconds=settings.SATNOGS_NETWORK_API_QUERY_INTERVAL,
                      next_run_time=datetime.now(pytz.utc))
    LOGGER.info('Registering `post_data` periodic task (%d sec. interval)',
                settings.SATNOGS_NETWORK_API_POST_INTERVAL)
    SCHEDULER.add_job(post_data, 'interval', seconds=settings.SATNOGS_NETWORK_API_POST_INTERVAL)
