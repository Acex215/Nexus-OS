import json
import logging
import os
import shlex
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from time import sleep

import pytz
import requests

import satnogsclient.config
import satnogsclient.radio.flowgraphs as flowgraphs
from satnogsclient import settings
from satnogsclient.artifacts import Artifacts
from satnogsclient.observer.worker import WorkerFreq, WorkerTrack
from satnogsclient.radio.grsat import GrSat, find_sample_rate
from satnogsclient.scheduler import SCHEDULER
from satnogsclient.waterfall import EmptyArrayError, Waterfall

try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin

LOGGER = logging.getLogger(__name__)


def rx_device_for_frequency(rx_device_spec, frequency):
    devices = rx_device_spec.split(' ')
    if len(devices) == 1:
        return devices[0]
    for range_device in devices:
        try:
            freq_range, device = range_device.split(':', 1)
        except ValueError as exc:
            raise ValueError('Invalid device entry in SATNOGS_SOAPY_RX_DEVICE: '
                             'expected format <min. freq.>-<max. freq.>:<driver spec>; got %r' %
                             range_device) from exc
        try:
            f_min_mhz, f_max_mhz = freq_range.split('-')
        except ValueError as exc:
            raise ValueError('Invalid frequency range entry in '
                             'SATNOGS_SOAPY_RX_DEVICE: expected format '
                             '<min. freq.>-<max. freq.>; got %r' % freq_range) from exc
        if float(f_min_mhz) <= (frequency / 10**6) <= float(f_max_mhz):
            return device
    raise LookupError('No device found for %.2f MHz in SATNOGS_SOAPY_RX_DEVICE = %r' %
                      (frequency / 10**6, rx_device_spec))


def post_and_save_artifacts(artifacts_file, observation_id):
    """Accepts a TemporaryFile `artifacts_file` opened at the beginning of the file,
    saves it to disk if enabled, then tries to upload it to satnogs-db.
    Finally closes this file.

    :param artifacts_file: The Artifact file (opened at position 0).
    :type artifacts_file: file
    :param observation_id: The observation id of the associated
                           observation (for enhanced logging).
    :type observation_id: str

    """
    filename = str(uuid.uuid4()) + '.h5'

    if settings.SATNOGS_KEEP_ARTIFACTS:
        save_artifacts(artifacts_file, filename)

    url = urljoin(settings.ARTIFACTS_API_URL, 'artifacts/')
    headers = {'Authorization': 'Token {0}'.format(settings.ARTIFACTS_API_TOKEN)}
    if not url.endswith('/'):
        url += '/'

    try:
        response = requests.post(
            url,
            headers=headers,
            files={'artifact_file': (filename, artifacts_file, 'application/x-hdf5')},
            verify=settings.SATNOGS_VERIFY_SSL,
            stream=True,
            timeout=settings.ARTIFACTS_API_TIMEOUT)
        response.raise_for_status()

        LOGGER.info('Artifacts upload for observation %s successful.', observation_id)
        artifacts_file.close()

    except requests.exceptions.Timeout:
        LOGGER.error('Upload of artifacts for observation %s failed '
                     'due to timeout.', observation_id)
    except requests.exceptions.HTTPError:
        if response.status_code == 404:
            LOGGER.error(
                "Upload of artifacts for observation %s failed, %s doesn't exist (404)."
                'Probably the observation was deleted.', observation_id, url)

        if response.status_code == 403 and 'has already been uploaded' in response.text:
            LOGGER.error('Upload of artifacts for observation %s is forbidden, %s\n URL: %s',
                         observation_id, response.text, url)
        else:
            LOGGER.error(
                'Upload of artifacts for observation %s failed, '
                'response status code: %s', observation_id, response.status_code)


def save_artifacts(artifacts_file, filename):
    """Accepts a TemporaryFile `artifacts_file` opened at the beginning of the file and
    writes this file to disk.
    Finally seeks back to the beginning of the file.

    NOTE: Does NOT close this file.

    :param artifacts_file: TemporaryFile, open at position 0
    :type artifacts_file: file
    :param filename: Filename of artifacts file
    :type filename: str
    """
    with open(os.path.join(settings.SATNOGS_ARTIFACTS_OUTPUT_PATH, filename), 'wb') as f_out:
        f_out.write(artifacts_file.read())

    artifacts_file.seek(0)


class Observer(object):

    # Variables from settings
    # Mainly present so we can support multiple ground stations from the client

    def __init__(self):
        self.location = {
            'lon': settings.SATNOGS_STATION_LON,
            'lat': settings.SATNOGS_STATION_LAT,
            'elev': settings.SATNOGS_STATION_ELEV
        }
        self.rot_port = settings.SATNOGS_ROT_PORT
        self.rig_ip = settings.SATNOGS_RIG_IP
        self.rig_port = settings.SATNOGS_RIG_PORT
        self.observation_id = None
        self.tle = None
        self.timestamp = None
        self.observation_end = None
        self.frequency = None
        self.rx_device = None
        self.mode = None
        self.baud = None
        self.observation_raw_file = None
        self.observation_ogg_file = None
        self.observation_waterfall_file = None
        self.observation_waterfall_png = None
        self.observation_receiving_decoded_data = None  # pylint: disable=C0103
        self.observation_decoded_data = None
        self.observation_done_decoded_data = None
        self.tracker_freq = None
        self.tracker_rot = None
        self.grsat = None

    # pylint: disable-next=too-many-positional-arguments
    def setup(self, observation_id, tle, observation_end, frequency, mode, baud):
        """Sets up required internal variables.
        * returns True if setup is ok
        * returns False if issue is encountered
        """
        # Set attributes
        self.observation_id = observation_id
        self.tle = tle
        self.observation_end = observation_end
        self.frequency = frequency
        self.rx_device = rx_device_for_frequency(settings.SATNOGS_SOAPY_RX_DEVICE, frequency)
        self.baud = baud
        self.mode = mode

        not_completed_prefix = 'receiving_satnogs'
        completed_prefix = 'satnogs'
        receiving_waterfall_prefix = 'receiving_waterfall'
        waterfall_prefix = 'waterfall'
        receiving_decoded_data_prefix = 'receiving_data'
        decoded_data_prefix = 'data'
        self.timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S%z')
        raw_file_extension = 'out'
        encoded_file_extension = 'ogg'
        waterfall_file_extension = 'dat'
        self.observation_raw_file = '{0}/{1}_{2}_{3}.{4}'.format(settings.SATNOGS_OUTPUT_PATH,
                                                                 not_completed_prefix,
                                                                 self.observation_id,
                                                                 self.timestamp,
                                                                 raw_file_extension)
        self.observation_ogg_file = '{0}/{1}_{2}_{3}.{4}'.format(settings.SATNOGS_OUTPUT_PATH,
                                                                 completed_prefix,
                                                                 self.observation_id,
                                                                 self.timestamp,
                                                                 encoded_file_extension)
        self.observation_waterfall_file = '{0}/{1}_{2}_{3}.{4}'.format(
            settings.SATNOGS_OUTPUT_PATH, receiving_waterfall_prefix, self.observation_id,
            self.timestamp, waterfall_file_extension)
        self.observation_waterfall_png = '{0}/{1}_{2}_{3}.{4}'.format(
            settings.SATNOGS_OUTPUT_PATH, waterfall_prefix, self.observation_id, self.timestamp,
            'png')
        self.observation_receiving_decoded_data = '{0}/{1}_{2}_{3}.{4}'.format(
            settings.SATNOGS_OUTPUT_PATH, receiving_decoded_data_prefix, self.observation_id,
            self.timestamp, 'png')
        self.observation_done_decoded_data = '{0}/{1}_{2}_{3}.{4}'.format(
            settings.SATNOGS_OUTPUT_PATH, decoded_data_prefix, self.observation_id, self.timestamp,
            'png')
        self.observation_decoded_data = '{0}/{1}_{2}'.format(settings.SATNOGS_OUTPUT_PATH,
                                                             decoded_data_prefix,
                                                             self.observation_id)
        return all([
            self.observation_id, self.tle, self.timestamp, self.observation_end, self.frequency,
            self.observation_raw_file, self.observation_ogg_file, self.observation_waterfall_file,
            self.observation_waterfall_png, self.observation_decoded_data
        ])

    def observe(self):  # pylint: disable=R0915
        """Starts threads for rotcrl and rigctl."""
        if settings.SATNOGS_PRE_OBSERVATION_SCRIPT is not None:
            LOGGER.info('Executing pre-observation script.')

            replacements = [
                ('{{FREQ}}', str(self.frequency)),
                ('{{TLE}}', json.dumps(self.tle)),
                ('{{TIMESTAMP}}', self.timestamp),
                ('{{ID}}', str(self.observation_id)),
                ('{{BAUD}}', str(self.baud)),
                ('{{SCRIPT_NAME}}', self.get_script_name()),
            ]
            pre_script = []
            for arg in shlex.split(settings.SATNOGS_PRE_OBSERVATION_SCRIPT):
                repl_arg = arg
                for key, val in replacements:
                    repl_arg = repl_arg.replace(key, val)
                pre_script.append(repl_arg)
            try:
                subprocess.call(pre_script)
            except (subprocess.CalledProcessError, FileNotFoundError, PermissionError,
                    OSError) as err:
                LOGGER.error('pre-observation script: %s', err)

        LOGGER.info('Begin observation %s ...', self.observation_id)
        # if it is APT we want to save with a prefix until the observation
        # is complete, then rename.
        if self.mode == 'APT':
            self.observation_decoded_data =\
                self.observation_receiving_decoded_data

        if settings.GR_SATELLITES_ENABLED:
            try:
                self.run_gr_satellites()
            # Calling gr-satellites might fail for anything. To allow the observation continuing
            # anyways, just catch and log them.
            # pylint: disable=W0718
            except Exception as e:
                LOGGER.error('Failed to start gr-satellites. Exception was thrown:\n%s', e)

        if settings.SATNOGS_ROT_ENABLED:
            LOGGER.debug('Start rotctrl thread.')
            self.run_rot()

        # start thread for rigctl
        LOGGER.debug('Start rigctrl thread.')
        self.run_rig()
        sleep(1)
        LOGGER.info('Start gnuradio thread.')
        flowgraph = satnogsclient.radio.flowgraphs.Flowgraph(
            self.rx_device, settings.SATNOGS_RX_SAMP_RATE, self.frequency, self.mode, self.baud, {
                'audio': self.observation_raw_file,
                'waterfall': self.observation_waterfall_file,
                'decoded': self.observation_decoded_data
            })
        flowgraph.enabled = True
        # Polling gnuradio process status
        self.poll_gnu_proc_status(flowgraph)

        # Rename files and create waterfall
        self.rename_ogg_file()
        self.rename_data_file()
        LOGGER.debug('Creating waterfall plot.')
        waterfall = None
        try:
            waterfall = Waterfall(self.observation_waterfall_file)
            self.plot_waterfall(waterfall)
            if settings.SATNOGS_REMOVE_RAW_FILES:
                self.remove_waterfall_file()
        except FileNotFoundError:
            LOGGER.error('No waterfall data file found')
        except EmptyArrayError:
            LOGGER.error('Waterfall data array is empty')
        except IndexError:
            LOGGER.error('Waterfall data array is invalid')

        # PUT client version and metadata
        base_url = urljoin(settings.SATNOGS_NETWORK_API_URL, 'observations/')
        headers = {'Authorization': 'Token {0}'.format(settings.SATNOGS_API_TOKEN)}
        url = urljoin(base_url, str(self.observation_id))
        if not url.endswith('/'):
            url += '/'
        client_metadata = flowgraph.info
        client_metadata['latitude'] = settings.SATNOGS_STATION_LAT
        client_metadata['longitude'] = settings.SATNOGS_STATION_LON
        client_metadata['elevation'] = settings.SATNOGS_STATION_ELEV
        client_metadata['frequency'] = self.frequency

        try:
            resp = requests.put(url,
                                headers=headers,
                                data={
                                    'client_version': satnogsclient.config.VERSION,
                                    'client_metadata': json.dumps(client_metadata)
                                },
                                verify=settings.SATNOGS_VERIFY_SSL,
                                stream=True,
                                timeout=45)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            LOGGER.error('%s: Connection Refused', url)
        except requests.exceptions.Timeout:
            LOGGER.error('%s: Connection Timeout - no metadata uploaded', url)
        except requests.exceptions.HTTPError as http_error:
            LOGGER.error(http_error)
        except requests.exceptions.RequestException as err:
            LOGGER.error('%s: Unexpected error: %s', url, err)

        if settings.ARTIFACTS_ENABLED and waterfall is not None:
            if settings.ARTIFACTS_API_TOKEN is not None:
                metadata = {
                    'observation_id': self.observation_id,
                    'frequency': str(self.frequency),
                    'tle': '{}\n{}\n{}\n'.format(self.tle['tle0'], self.tle['tle1'],
                                                 self.tle['tle2']),
                    'location': {
                        'latitude': self.location['lat'],
                        'longitude': self.location['lon'],
                        'altitude': self.location['elev']
                    }
                }
                artifact = Artifacts(waterfall, metadata)
                artifact.create()
                SCHEDULER.add_job(post_and_save_artifacts,
                                  args=(artifact.artifacts_file, str(self.observation_id)))
            else:
                LOGGER.warning(
                    'The ARTIFACTS_API_TOKEN setting is not set. The artifacts cannot be uploaded')

    def run_rot(self):
        self.tracker_rot = WorkerTrack(port=self.rot_port,
                                       time_to_stop=self.observation_end,
                                       sleep_time=3)
        LOGGER.debug('TLE: %s', self.tle)
        LOGGER.debug('Observation end: %s', self.observation_end)
        self.tracker_rot.trackobject(self.location, self.tle)
        self.tracker_rot.trackstart()

    def run_rig(self):
        self.tracker_freq = WorkerFreq(ip=self.rig_ip,
                                       port=self.rig_port,
                                       time_to_stop=self.observation_end)
        LOGGER.debug('Rig Frequency %s', self.frequency)
        LOGGER.debug('Observation end: %s', self.observation_end)
        self.tracker_freq.trackobject(self.frequency, self.location, self.tle)
        self.tracker_freq.trackstart()

    def get_script_name(self):
        if self.mode in flowgraphs.SATNOGS_FLOWGRAPH_MODES:
            return flowgraphs.SATNOGS_FLOWGRAPH_MODES[self.mode]['script_name']

        return flowgraphs.SATNOGS_FLOWGRAPH_MODES[
            flowgraphs.SATNOGS_FLOWGRAPH_MODE_DEFAULT]['script_name']

    def poll_gnu_proc_status(self, flowgraph):
        while flowgraph.enabled and datetime.now(pytz.utc) <= self.observation_end:
            sleep(1)
        flowgraph.enabled = False

        if self.tracker_freq:
            self.tracker_freq.trackstop()

        if self.tracker_rot:
            self.tracker_rot.trackstop()

        if self.grsat:
            self.grsat.stop_gr_satellites()

        LOGGER.info('Observation %s finished.', self.observation_id)
        if settings.SATNOGS_POST_OBSERVATION_SCRIPT is not None:
            LOGGER.info('Executing post-observation script.')

            replacements = [
                ('{{FREQ}}', str(self.frequency)),
                ('{{TLE}}', json.dumps(self.tle)),
                ('{{TIMESTAMP}}', self.timestamp),
                ('{{ID}}', str(self.observation_id)),
                ('{{BAUD}}', str(self.baud)),
                ('{{SCRIPT_NAME}}', self.get_script_name()),
            ]
            post_script = []
            for arg in shlex.split(settings.SATNOGS_POST_OBSERVATION_SCRIPT):
                repl_arg = arg
                for key, val in replacements:
                    repl_arg = repl_arg.replace(key, val)
                post_script.append(repl_arg)
            try:
                subprocess.call(post_script)
            except (subprocess.CalledProcessError, FileNotFoundError, PermissionError,
                    OSError) as err:
                LOGGER.error('post-observation script: %s', err)

    def run_gr_satellites(self):
        norad_cat_id = int(self.tle['tle2'].split()[1])
        sample_rate = find_sample_rate(str(self.baud), self.get_script_name())
        self.grsat = GrSat(
            int(self.observation_id),
            norad_cat_id,
            datetime.strptime(self.timestamp, '%Y-%m-%dT%H-%M-%S'),
            sample_rate,
        )
        self.grsat.start_gr_satellites()

    def rename_ogg_file(self):
        observation_raw_file_path = Path(self.observation_raw_file)
        if observation_raw_file_path.exists():
            observation_raw_file_path.rename(Path(self.observation_ogg_file))
            LOGGER.debug('Rename encoded file for uploading finished')

    def rename_data_file(self):
        observation_receiving_decoded_data_path = Path(self.observation_receiving_decoded_data)
        if observation_receiving_decoded_data_path.exists():
            observation_receiving_decoded_data_path.rename(Path(
                self.observation_done_decoded_data))
            LOGGER.debug('Rename data file for uploading finished')

    def plot_waterfall(self, waterfall):
        vmin = None
        vmax = None
        if not settings.SATNOGS_WATERFALL_AUTORANGE:
            vmin = settings.SATNOGS_WATERFALL_MIN_VALUE
            vmax = settings.SATNOGS_WATERFALL_MAX_VALUE
        waterfall.plot(self.observation_waterfall_png, vmin, vmax)

    def remove_waterfall_file(self):
        try:
            Path(self.observation_waterfall_file).unlink()
        except FileNotFoundError:
            LOGGER.error('Failed to remove waterfall file')
