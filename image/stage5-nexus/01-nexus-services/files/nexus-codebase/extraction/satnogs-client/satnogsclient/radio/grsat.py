# Original source: https://github.com/kng/satnogs-client-docker/blob/main/addons/scripts/grsat.py
# Copyright 2024-2025 Daniel Ekman <knegge@gmail.com>
#
# License: AGPLv3
import logging
import signal
from base64 import b64encode
from datetime import datetime, timedelta
from json import dump
from os import kill, path, unlink
from struct import unpack
from subprocess import DEVNULL, Popen

from satnogsclient import settings

try:
    from imagedecode import ImageDecode
    HAS_IMAGEDECODE = True
except ImportError:
    HAS_IMAGEDECODE = False

LOGGER = logging.getLogger(__name__)


def parse_kiss_file(infile):
    """
    Read and return an iterator of frames from a KISS file.

    # from satnogs-open-flowgraph/satnogs_wrapper.py
    """
    ts = datetime.now()  # MUST be overwritten by timestamps in file
    for row in infile.read().split(b'\xC0'):
        if len(row) == 9 and row[0] == 9:  # timestamp frame
            ts = datetime(1970, 1, 1) + timedelta(seconds=unpack('>Q', row[1:])[0] / 1000)
        if len(row) > 0 and row[0] == 0:  # data frame
            yield ts, row[1:].replace(b'\xdb\xdc', b'\xc0').replace(b'\xdb\xdd', b'\xdb')


def kiss_to_json(kiss_file, output_path, filename_template):
    """
    Extract individual frames from a single KISS file into the
    specified output directory.

    Output files are JSON-encapsulated telemetry frames.

    Input: <kiss_file>
    Output: <output_path>/<filename_template>

    The reception timestamp for each frame is available to be used in
    the filename via python templating, e.g. with "frame_{timestamp}".
    """
    with open(kiss_file, 'rb') as kf:
        LOGGER.info('Processing kiss file')
        num_frames = 0
        for ts, frame in parse_kiss_file(kf):
            if len(frame) == 0:
                continue
            filename = filename_template.format(timestamp=ts)
            datafile = f'{output_path}/{filename}'
            ext = 0
            while True:
                if path.isfile(f'{datafile}{ext}'):
                    ext += 1
                else:
                    datafile += str(ext)
                    break
            data = {
                'decoder_name': 'gr-satellites',
                'pdu': b64encode(frame).decode(),
            }
            with open(datafile, 'w', encoding='utf-8') as df:
                dump(data, df, default=str)
            num_frames += 1
            LOGGER.debug('%s len %d', datafile, len(frame))
        LOGGER.info('Total frames: %d', num_frames)


def find_decimation(baudrate, min_decimation=4, audio_samp_rate=48e3, multiple=2):
    """
    from gr-satnogs/python/utils.py
    """
    while min_decimation * baudrate < audio_samp_rate:
        min_decimation = min_decimation + 1
    if min_decimation % multiple:
        min_decimation = min_decimation + multiple - min_decimation % multiple
    return min_decimation


def find_sample_rate(baudrate, script='', sps=4, audio_samp_rate=48000):
    """
    from satnogs_gr-satellites/find_samp_rate.py
    """
    # pylint: disable=too-many-return-statements
    try:
        baudrate = int(float(baudrate))
    except ValueError:
        baudrate = 9600
    if baudrate < 1:
        baudrate = 9600

    if '_bpsk' in script:
        return find_decimation(baudrate, 2, audio_samp_rate, sps) * baudrate
    if '_fsk' in script:
        return max(4, find_decimation(baudrate, 2, audio_samp_rate)) * baudrate
    if '_sstv' in script:
        return 4 * 4160 * 4
    if '_qubik' in script:
        return max(4, find_decimation(baudrate, 2, audio_samp_rate)) * baudrate
    if '_apt' in script:
        return 4 * 4160 * 4
    if '_ssb' in script:
        return find_decimation(baudrate, 2, audio_samp_rate, sps) * baudrate

    # cw, fm, afsk, etc...
    return audio_samp_rate


class GrSat:

    def __init__(
        self,
        obs_id,
        norad_cat_id,
        start_time,
        sample_rate,
    ):
        """
        Arguments:
        obs_id: int
        norad_cat_id: int
        start_time: timezone-naive datetime.datetime
        sample_rate: int
        """
        self.obs_id = obs_id
        self.norad_cat_id = norad_cat_id
        self.start_time = start_time
        self.sample_rate = sample_rate

        self.kiss_file = f'{settings.SATNOGS_APP_PATH}/grsat_{self.obs_id}.kiss'
        self.log_file = f'{settings.SATNOGS_APP_PATH}/grsat_{self.obs_id}.log'
        self.pid_file = f'{settings.SATNOGS_APP_PATH}/grsat_{settings.SATNOGS_STATION_ID}.pid'

    def start_gr_satellites(self):
        LOGGER.info('Starting gr_satellites for observation %d at %d sps', self.obs_id,
                    self.sample_rate)
        gr_app = [
            settings.GR_SATELLITES_APP,
            str(self.norad_cat_id),
            '--samp_rate',
            str(self.sample_rate),
            '--iq',
            '--udp',
            '--udp_raw',
            '--udp_port',
            str(settings.UDP_DUMP_PORT),
            '--start_time',
            self.start_time.strftime('%Y-%m-%dT%H:%M:%S'),
            '--kiss_out',
            self.kiss_file,
            '--ignore_unknown_args',
            '--satcfg',
        ]
        if 0 < settings.GR_SATELLITES_ZMQ_PORT <= 65535:
            gr_app.extend(['--zmq_pub', f'tcp://0.0.0.0:{str(settings.GR_SATELLITES_ZMQ_PORT)}'])

        LOGGER.debug(' '.join(gr_app))
        try:
            if settings.GR_SATELLITES_KEEPLOGS:
                logfile = open(self.log_file, 'w', encoding='utf-8')
            else:
                logfile = DEVNULL
            s = Popen(gr_app, stdout=logfile, stderr=logfile)
            with open(self.pid_file, 'w', encoding='utf-8') as pf:
                pf.write(str(s.pid))
        except (FileNotFoundError, TypeError, OSError) as e:
            LOGGER.warning('Unable to launch %s: %s', settings.GR_SATELLITES_APP, str(e))

    def stop_gr_satellites(self):
        try:
            with open(self.pid_file, 'r', encoding='utf-8') as pf:
                kill(int(pf.readline()), signal.SIGKILL)
            unlink(self.pid_file)
            LOGGER.info('Stopped gr_satellites')
        except (FileNotFoundError, ProcessLookupError, OSError):
            LOGGER.info('No gr_satellites running')

        if path.isfile(self.kiss_file):
            filename_template = f'data_{self.obs_id}_{{timestamp:%Y-%m-%dT%H-%M-%S}}_g'
            kiss_to_json(self.kiss_file, settings.SATNOGS_OUTPUT_PATH, filename_template)
            if HAS_IMAGEDECODE:
                filename = f'{settings.SATNOGS_OUTPUT_PATH}/data_{self.obs_id}_'
                ImageDecode(self.kiss_file, self.norad_cat_id, filename)
            # run other scripts here
            if not settings.GR_SATELLITES_KEEPLOGS or path.getsize(self.kiss_file) == 0:
                unlink(self.kiss_file)

        if path.isfile(self.log_file) and (not settings.GR_SATELLITES_KEEPLOGS
                                           or path.getsize(self.log_file) == 0):
            unlink(self.log_file)
