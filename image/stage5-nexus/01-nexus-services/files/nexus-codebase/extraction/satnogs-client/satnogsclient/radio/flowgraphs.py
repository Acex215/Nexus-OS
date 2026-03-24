import json
import logging
import signal
import subprocess

import satnogsclient.settings as client_settings

LOGGER = logging.getLogger(__name__)

SATNOGS_FLOWGRAPH_SCRIPTS = {
    'AFSK1K2': 'satnogs_afsk1200_ax25.py',
    'AMSAT_DUV': 'satnogs_amsat_fox_duv_decoder.py',
    'APT': 'satnogs_noaa_apt_decoder.py',
    'ARGOS_BPSK_PMT_A3': 'satnogs_argos_bpsk_ldr.py',
    'BPSK': 'satnogs_bpsk.py',
    'CW': 'satnogs_cw_decoder.py',
    'FM': 'satnogs_fm.py',
    'FSK': 'satnogs_fsk.py',
    'GFSK_RKTR': 'satnogs_reaktor_hello_world_fsk9600_decoder.py',
    'GFSK/BPSK': 'satnogs_qubik_telem.py',
    'SSTV': 'satnogs_sstv_pd120_demod.py'
}

SATNOGS_FLOWGRAPH_MODES = {
    'AFSK': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['AFSK1K2'],
        'has_baudrate': False,
        'has_framing': False
    },
    'APT': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['APT'],
        'has_baudrate': False,
        'has_framing': False,
    },
    'BPSK': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['BPSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax25'
    },
    'BPSK PMT-A3': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['ARGOS_BPSK_PMT_A3'],
        'has_baudrate': True,
        'has_framing': False
    },
    'CW': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['CW'],
        'has_baudrate': True,
        'has_framing': False
    },
    'DUV': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['AMSAT_DUV'],
        'has_baudrate': False,
        'has_framing': False
    },
    'FM': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FM'],
        'has_baudrate': False,
        'has_framing': False
    },
    'FSK': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax25'
    },
    'FSK AX.100 Mode 5': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax100_mode5'
    },
    'FSK AX.100 Mode 6': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax100_mode6'
    },
    'GFSK': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax25'
    },
    'GFSK Rktr': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['GFSK_RKTR'],
        'has_baudrate': True,
        'has_framing': False
    },
    'GFSK/BPSK': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['GFSK/BPSK'],
        'has_baudrate': True,
        'has_framing': False,
    },
    'GMSK': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax25'
    },
    'MSK': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax25'
    },
    'MSK AX.100 Mode 5': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax100_mode5'
    },
    'MSK AX.100 Mode 6': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['FSK'],
        'has_baudrate': True,
        'has_framing': True,
        'framing': 'ax100_mode6'
    },
    'SSTV': {
        'script_name': SATNOGS_FLOWGRAPH_SCRIPTS['SSTV'],
        'has_baudrate': False,
        'has_framing': False
    },
}

SATNOGS_FLOWGRAPH_MODE_DEFAULT = 'FM'
DISPATCHER_SCRIPT_NAME = 'flowgraph_dispatcher'


class Flowgraph():
    """Execute SatNOGS Flowgraphs

    :param device: SoapySDR device
    :type device: str
    :param sampling_rate: Sampling rate
    :type sampling_rate: int
    :param frequency: RX frequency
    :type frequency: int
    :param mode: Mode of operation
    :type mode: str
    :param baud: Baud rate or WPM
    :type baud: int
    :param output_data: Dictionary of output data
    :type output_data: dict
    """

    # pylint: disable-next=too-many-positional-arguments
    def __init__(self, device, sampling_rate, frequency, mode, baud, output_data):
        """Class constructor"""
        self.parameters = {
            'mode': mode,
            'soapy-rx-device': device,
            'samp-rate-rx': str(sampling_rate),
            'rx-freq': str(frequency),
            'file-path': output_data['audio'],
            'waterfall-file-path': output_data['waterfall'],
            'decoded-data-file-path': output_data['decoded'],
            'doppler-correction-per-sec': client_settings.SATNOGS_DOPPLER_CORR_PER_SEC,
            'lo-offset': client_settings.SATNOGS_LO_OFFSET,
            'ppm': client_settings.SATNOGS_PPM_ERROR,
            'rigctl-host': str(client_settings.SATNOGS_RIG_IP),
            'rigctl-port': str(client_settings.SATNOGS_RIG_PORT),
            'gain-mode': client_settings.SATNOGS_GAIN_MODE,
            'gain': client_settings.SATNOGS_RF_GAIN,
            'antenna': client_settings.SATNOGS_ANTENNA,
            'dev-args': client_settings.SATNOGS_DEV_ARGS,
            'stream-args': client_settings.SATNOGS_STREAM_ARGS,
            'tune-args': client_settings.SATNOGS_TUNE_ARGS,
            'other-settings': client_settings.SATNOGS_OTHER_SETTINGS,
            'dc-removal': client_settings.SATNOGS_DC_REMOVAL,
            'bb-freq': client_settings.SATNOGS_BB_FREQ,
            'bw': client_settings.SATNOGS_RX_BANDWIDTH,
            'enable-iq-dump': str(int(client_settings.ENABLE_IQ_DUMP is True)),
            'iq-file-path': client_settings.IQ_DUMP_FILENAME,
            'udp-dump-host': client_settings.UDP_DUMP_HOST,
            'udp-dump-port': client_settings.UDP_DUMP_PORT,
        }
        if baud:
            # Baud rate is passed as {"baud": 9600.0,} from network.
            self.parameters['baud'] = str(int(baud))

        self.script = DISPATCHER_SCRIPT_NAME
        self.process = None

    @property
    def enabled(self):
        """Get flowgraph running status

        :return: Flowgraph running status
        :rtype: bool
        """
        if self.process and self.process.poll() is None:
            return True
        return False

    @enabled.setter
    def enabled(self, status):
        """Start or stop running of flowgraph

        :param status: Running status
        :type status: bool
        """
        if status:
            args = [self.script]
            for parameter, value in self.parameters.items():
                if value is not None:
                    args.append('--{}={}'.format(parameter, value))
            try:
                LOGGER.debug("Invoke '%s \\\n%s'", args[0], ' \\\n'.join(args[1:]))
                self.process = subprocess.Popen(args)
            except OSError:
                LOGGER.exception('Could not start GNURadio python script')
        elif self.process:
            self.process.send_signal(signal.SIGINT)
            _, _ = self.process.communicate()

    @property
    def info(self):
        """Get information and parameters of flowgraph and radio

        :return: Information about flowgraph and radio
        :rtype: dict
        """
        client_metadata = {
            'radio': {
                'name': 'gr-satnogs',
                'version': None,
                'parameters': self.parameters
            }
        }
        process = subprocess.Popen(['python3', '-m', 'satnogs.satnogs_info'],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        gr_satnogs_info, _ = process.communicate()  # pylint: disable=W0612
        if process.returncode == 0:
            try:
                gr_satnogs_info = json.loads(gr_satnogs_info)
            except ValueError:
                client_metadata['radio']['version'] = 'invalid'
            else:
                if 'version' in gr_satnogs_info:
                    client_metadata['radio']['version'] = gr_satnogs_info['version']
                else:
                    client_metadata['radio']['version'] = 'unknown'
        return client_metadata
