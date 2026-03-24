SatNOGS Client
==============

SatNOGS Client is the software responsible for automating satellite signal reception for SatNOGS.
The main functions of SatNOGS Client is to pull observation jobs from SatNOGS Network and execute them on the a station host (usually a Raspberry Pi).
These observation jobs create locally scheduled task which spawn SatNOGS Radio scripts for decoding and demodulating the signals.
In addition to that, SatNOGS Client can optionally control a Hamlib compatible rotator to track the satellite.
During the execution of an observation task, orbital calculations are performed to compensate for doppler shift and point the rotator to the correct direction.
After the completion of an observation, the client gathers the observation artifacts and uploads them to SatNOGS Network.

Table of Contents
=================

.. toctree::
   :maxdepth: 3

   userguide
   devguide
   docker
   modules

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
