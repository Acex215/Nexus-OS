import logging

import Hamlib

LOGGER = logging.getLogger(__name__)


class Rotator(object):
    """Communicate and interface with rotators

    :param model: Model of rotator e.g. "ROT_MODEL_EASYCOMM3" or "ROT_MODEL_DUMMY"
    :type model: str
    :param baud: The baud rate of serial communication, e.g. 19200
    :type baud: int, optional
    :param port: The port of the rotator, e.g. "/dev/ttyUSB0"
    :type port: str
    """

    def __init__(self, model, baud, port):
        """Class constructor"""
        self.rot_port = port
        self.rot_baud = baud
        self.rot_name = getattr(Hamlib, model)
        self.rot = Hamlib.Rot(self.rot_name)
        self.rot.state.rotport.pathname = self.rot_port
        self.rot.state.rotport.parm.serial.rate = self.rot_baud

    def get_info(self):
        """Return information about the rotator

        :return: Information about the rotator
        :rtype: str
        """
        return self.rot.get_info()

    @property
    def position(self):
        """Return the position in degrees of azimuth and elevation

        :return: Position in degrees
        :rtype: list[float, float]
        """
        return self.rot.get_position()

    @position.setter
    def position(self, pos):
        """Set the position in degrees of azimuth and elevation

        :param pos: Position in degrees
        :type pos: list[float, float]
        """
        self.rot.set_position(*pos)

    def get_conf(self, cmd):
        """Return the configuration of a register

        :param cmd: Number of the register
        :type cmd: int
        :return: Value of register
        :rtype: str
        """
        return self.rot.get_conf(cmd)

    def reset(self):
        """Move the rotator to home position and return the current position

        :return: Current position in degrees
        :rtype: None or list[float, float]
        """
        return self.rot.reset(Hamlib.ROT_RESET_ALL)

    def stop(self):
        """Stop the rotator and return the current position

        :return: Current position in degrees
        :rtype: None or list[float, float]
        """
        return self.rot.stop()

    def park(self):
        """Move the rotator to park position and return the current position

        :return: Current position in degrees
        :rtype: None or list[float, float]
        """
        return self.rot.park()

    def move(self, direction, speed):
        """Move the rotator with speed (mdeg/s) to specific direction

        :param direction: The direction of movement, e.g. ROT_MOVE_UP, ROT_MOVE_DOWN,
                          ROT_MOVE_LEFT, ROT_MOVE_RIGHT
        :type direction: str
        :param speed: The velocity set point in mdeg/s
        :type speed: int
        """
        direction = getattr(Hamlib, direction)
        self.rot.move(direction, abs(speed))

    def open(self):
        """Start the communication with rotator"""
        self.rot.open()

    def close(self):
        """End the communication with rotator"""
        self.rot.close()
