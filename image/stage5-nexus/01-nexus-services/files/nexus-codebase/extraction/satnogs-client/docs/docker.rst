Working with Docker
===================

Requirements
------------

- Docker Engine 20.10+
- Docker Compose 1.29+

Building
--------

To build the SatNOGS Client image run::

  $ docker-compose build

To build based on the unstable image of ``librespace/gnuradio`` run::

  $ GNURADIO_IMAGE_TAG=satnogs-unstable docker-compose build

Configuration
-------------

Edit ``docker-compose.yml`` to set SatNOGS Client environment variables.
Check :ref:`configuration` for a list of all configuration variables.

Usage
-----

To bring up SatNOGS Client containers, run::

  $ docker-compose up
