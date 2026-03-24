User guide
==========

Requirements
------------

- Python 3.6+
- Hamlib 4.0+ Python bindings
- GPSD 3.22+ Python bindings
- ATLAS 3.10+ library
- HDF5 1.10+ library


Installation
------------

Debian
^^^^^^

To install the required dependencies in Debian Bullseye run::

  $ xargs -r -a packages.debian apt-get install


SatNOGS Client
^^^^^^^^^^^^^^

To install SatNOGS Client run::

  $ pip install satnogs-client

This will install a console script called ``satnogs-client``.


.. _configuration:

Configuration
-------------

Configuration of SatNOGS Client is done through environment variables.
The environment variables can also be defined in a file called ``.env``, place on the project root directory.
The format of each line in ``.env`` file is ``VARIABLE=VALUE``.

.. include:: environment_variables.rst


Usage
-----

To execute the script, run it on the command line::

  $ satnogs-client


Doppler-corrected I/Q Streaming via UDP
---------------------------------------

For realtime analysis during an observation each SatNOGS flowgraph offers streaming of doppler corrected I/Q data via an UDP sink.
The destination of this sink can be configured by the environment variables `UDP_DUMP_HOST` and `UDP_DUMP_PORT`.
