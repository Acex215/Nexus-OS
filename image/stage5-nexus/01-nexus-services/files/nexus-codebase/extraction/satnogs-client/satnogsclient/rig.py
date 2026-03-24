import logging

import Hamlib

LOGGER = logging.getLogger(__name__)


class Rig(object):
    """Communicate and interface with rigs

    :param model: Model of Hamlib rig
    :type mode: int, optional
    :param path: Path or address to Hamlib rig device
    :type path: str, optional
    :param debug: Hamlib rig debug level
    :type debug: int, optional
    """

    def __init__(self, model=Hamlib.RIG_MODEL_DUMMY, path='', debug=Hamlib.RIG_DEBUG_WARN):
        """Class constructor"""
        Hamlib.rig_set_debug(debug)
        self.rig = Hamlib.Rig(model)
        self.rig.set_conf('rig_pathname', path)

    def open(self):
        """Open Hamlib rig device"""
        self.rig.open()

    @property
    def frequency(self):
        """Get rig frequency

        :return: Rig frequency
        :rtype: float
        """
        return self.rig.get_freq()

    @frequency.setter
    def frequency(self, frequency):
        """Set rig frequency

        :param frequency: Rig frequency
        :type frequency: float
        """
        self.rig.set_freq(self.vfo, frequency)

    @property
    def vfo(self):
        """Get active VFO

        :return: Active VFO
        :rtype: int
        """
        return self.rig.get_vfo()

    @vfo.setter
    def vfo(self, vfo):
        """Set active VFO

        :param vfo: VFO
        :type vfo: int
        """
        return self.rig.set_vfo(vfo)

    def close(self):
        """Close Hamlib rig device"""
        self.rig.close()
