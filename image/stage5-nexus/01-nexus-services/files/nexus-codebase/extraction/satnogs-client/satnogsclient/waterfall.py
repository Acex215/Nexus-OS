#!/usr/bin/env python3
#
# Notes:
# Plots generated with this script are occasionally used with software that generates
# overlays with additional information [1]. To allows this software to create accurately
# aligned overlays, textual metadata is provided inside the PNG image.
#
# PNG metadata keywords:
#
# | Keyword           | Description                                                            |
# |-------------------|------------------------------------------------------------------------|
# | "satnogs:wf-plot" | JSON-serialized, parameters used for plotting (figsize, gridspec, etc) |
# | "satnogs:wf-dat"  | JSON-serialized, content of the waterfall.dat header                   |
#
# References:
# [1]: https://gitlab.com/adamkalis/ikhnos/

import json
import logging
from argparse import ArgumentParser
from datetime import datetime, timedelta

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.dates import date2num
from matplotlib.gridspec import GridSpec

matplotlib.use('Agg')

LOGGER = logging.getLogger(__name__)

OFFSET_IN_STDS = -2.0
SCALE_IN_STDS = 8.0

FIGSIZE = (8.32, 16.03)
GRIDSPEC = {
    'nrows': 1,
    'ncols': 2,
    'width_ratios': [0.93, 0.03],
    'left': 0.09,
    'right': 0.91,
    'top': 0.995,
    'bottom': 0.03,
}


class EmptyArrayError(Exception):
    """Empty data array exception"""


def _read_waterfall(datafile_path):
    """Read waterfall data file

    :param datafile_path: Path to data file
    :type datafile_path: str
    :raises EmptyArrayError: Empty waterfall data
    :raises IndexError: Invalid waterfall data
    :raises FileNotFoundError: No waterfall data file found
    :raises OSError: Could not open waterfall data file
    :return: Waterfall data and metadata
    :rtype: tuple (dict, dict)
    """
    LOGGER.debug('Reading waterfall file')

    with open(datafile_path, mode='rb') as datafile:
        metadata = {
            'timestamp': np.fromfile(datafile, dtype='|S32', count=1)[0].decode('utf-8'),
            'nchan': np.fromfile(datafile, dtype='>i4', count=1)[0],
            'samp_rate': np.fromfile(datafile, dtype='>i4', count=1)[0],
            'nfft_per_row': np.fromfile(datafile, dtype='>i4', count=1)[0],
            'center_freq': np.fromfile(datafile, dtype='>f4', count=1)[0],
            'endianness': np.fromfile(datafile, dtype='<i4', count=1)[0],
        }
        dtype_prefix = '<' if metadata['endianness'] else '>'
        data_dtypes = np.dtype([('tabs', dtype_prefix + 'i8'),
                                ('spec', dtype_prefix + 'f4', (metadata['nchan'], ))])

        waterfall = {
            'data': np.fromfile(datafile, dtype=data_dtypes),
        }

        if not waterfall['data'].size:
            raise EmptyArrayError

    return waterfall, metadata


def _compress_waterfall(waterfall):
    """Compress spectra of waterfall

    :param waterfall: Watefall data
    :type waterfall: dict
    :return: Compressed spectra
    :rtype: dict
    """
    spec = waterfall['data']['spec']
    std = np.std(spec, axis=0)
    offset = np.mean(spec, axis=0) + OFFSET_IN_STDS * std
    scale = SCALE_IN_STDS * std / 255.0
    values = np.clip((spec - offset) / scale, 0.0, 255.0).astype('uint8')

    return {'offset': offset, 'scale': scale, 'values': values}


def _get_waterfall(datafile_path):
    """Get waterfall data

    :param datafile_path: Path to data file
    :type datafile_path: str_array
    :return: Waterfall data including compressed data
    :rtype: dict
    """
    waterfall, metadata = _read_waterfall(datafile_path)

    nint = waterfall['data']['spec'].shape[0]
    waterfall['trel'] = np.arange(nint) * metadata['nfft_per_row'] * metadata['nchan'] / float(
        metadata['samp_rate'])
    waterfall['freq'] = np.linspace(-0.5 * metadata['samp_rate'],
                                    0.5 * metadata['samp_rate'],
                                    metadata['nchan'],
                                    endpoint=False)
    waterfall['compressed'] = _compress_waterfall(waterfall)

    return waterfall, metadata


class Waterfall():  # pylint: disable=R0903
    """Parse waterfall data file

    :param datafile_path: Path to data file
    :type datafile_path: str_array
    """

    def __init__(self, datafile_path):
        """Class constructor"""
        self.data, self.metadata = _get_waterfall(datafile_path)

    def plot(self, figure_path, vmin=None, vmax=None):
        """Plot waterfall into a figure

        :param figure_path: Path of figure file to save
        :type figure_path: str
        :param vmin: Minimum value range
        :type vmin: int
        :param vmax: Maximum value range
        :type vmax: int
        """
        tmin = np.min(self.data['data']['tabs'] / 1000000.0)
        tmax = np.max(self.data['data']['tabs'] / 1000000.0)
        fmin = np.min(self.data['freq'] / 1000.0)
        fmax = np.max(self.data['freq'] / 1000.0)
        timefmt = '%Y-%m-%dT%H:%M:%S.%fZ'
        t_ref = datetime.strptime(self.metadata['timestamp'], timefmt)
        dt_min = t_ref + timedelta(seconds=tmin)
        dt_max = t_ref + timedelta(seconds=tmax)
        if vmin is None or vmax is None:
            vmin = -100
            vmax = -50
            c_idx = self.data['data']['spec'] > -200.0
            if np.sum(c_idx) > 100:
                data_mean = np.mean(self.data['data']['spec'][c_idx])
                data_std = np.std(self.data['data']['spec'][c_idx])
                vmin = data_mean - 2.0 * data_std
                vmax = data_mean + 6.0 * data_std
        fig = plt.figure(figsize=FIGSIZE)
        gs = GridSpec(**GRIDSPEC)
        axis = fig.add_subplot(gs[0])
        axis_cbar = fig.add_subplot(gs[1])

        im = axis.imshow(self.data['data']['spec'],
                         origin='lower',
                         aspect='auto',
                         interpolation='None',
                         extent=[fmin, fmax, date2num(dt_min),
                                 date2num(dt_max)],
                         vmin=vmin,
                         vmax=vmax,
                         cmap='viridis')
        axis.yaxis_date()
        axis.yaxis.set_major_locator(mdates.MinuteLocator(interval=1))
        axis.yaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        axis2 = axis.twinx()
        axis2.set_ylim(tmin, tmax)
        axis.set_xlabel('Frequency (kHz)')
        axis.set_ylabel('Time (UTC)')
        axis2.set_ylabel('Time (seconds)')
        cbar = plt.colorbar(im, aspect=50, cax=axis_cbar)
        cbar.set_label('Power (dB)')

        # Prepare metadata
        dat_metadata = {key: str(value) for key, value in self.metadata.items()}
        plot_metadata = {
            'figsize': FIGSIZE,
            'gridspec': GRIDSPEC,
            'xlim_kHz': [round(val, 6) for val in axis.get_xlim()],
            'ylim_s': [round(val, 6) for val in axis2.get_ylim()],
            'ylim_num': [round(val, 6) for val in axis.get_ylim()],
        }

        # Serialze with JSON and combine
        metadata = {
            'satnogs:wf-dat': json.dumps(dat_metadata),
            'satnogs:wf-plot': json.dumps(plot_metadata),
        }
        fig.savefig(figure_path, metadata=metadata)
        plt.close()


def main():
    parser = ArgumentParser(description='Make a waterfall plot')
    parser.add_argument('data_path', help='Data path (dat file)')
    parser.add_argument('png_path', help='Output path (png file)')
    args = parser.parse_args()
    waterfall = Waterfall(args.data_path)
    waterfall.plot(args.png_path)


if __name__ == '__main__':
    main()
