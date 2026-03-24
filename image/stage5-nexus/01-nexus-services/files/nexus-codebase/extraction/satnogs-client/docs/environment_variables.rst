Environment variables
^^^^^^^^^^^^^^^^^^^^^

SATNOGS_API_TOKEN
~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: *None*
:Required: *Yes*
:Description:
   SatNOGS Network API token associated with an account in SatNOGS Network.
   This token is secret.
   It can be found in SatNOGS Network user page.


SATNOGS_PRE_OBSERVATION_SCRIPT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *path*
:Default: *None*
:Required: *No*
:Description:
   A path to an executable to be executed before an observation job is started.
   Execution of this script blocks the observation job.


SATNOGS_POST_OBSERVATION_SCRIPT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *path*
:Default: *None*
:Required: *No*
:Description:
   A path to an executable to be executed after an observation job has finished.
   Execution of this script blocks the completion of an observation job.


SATNOGS_STATION_ID
~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: *None*
:Required: *Yes*
:Description:
   The ID of the SatNOGS Network station this client will act as.
   The station must be owned by the user with the defined API token.


SATNOGS_STATION_LAT
~~~~~~~~~~~~~~~~~~~

:Type: *float*
:Default: *None*
:Required: *Yes*
:Description:
   Latitude of the station location.
   Higher precision of this value increases accuracy of Doppler correction while lower precision increases station location privacy.


SATNOGS_STATION_LON
~~~~~~~~~~~~~~~~~~~

:Type: *float*
:Default: *None*
:Required: *Yes*
:Description:
   Longitude of the station location.
   Higher precision of this value increases accuracy of Doppler correction while lower precision increases station location privacy.


SATNOGS_STATION_ELEV
~~~~~~~~~~~~~~~~~~~~

:Type: *float*
:Default: *None*
:Required: *Yes*
:Description:
   Elevation of the station location.
   Higher precision of this value increases accuracy of Doppler correction while lower precision increases station location privacy.


SATNOGS_GPSD_CLIENT_ENABLED
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *False*
:Required: *No*
:Description:
   Enable SatNOGS Client to connect to a GPSd daemon to pull positional information.
   The position is queried once, during SatNOGS Client startup.


SATNOGS_GPSD_HOST
~~~~~~~~~~~~~~~~~

:Type: *host*
:Default: ``127.0.0.1``
:Required: *No*
:Description:
   Hostname or IP address of GPSd to connect to for pulling positional information.


SATNOGS_GPSD_PORT
~~~~~~~~~~~~~~~~~

:Type: *port*
:Default: ``2947``
:Required: *No*
:Description:
   Port of GPSd to connect to for pulling positional information.


SATNOGS_GPSD_TIMEOUT
~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``0``
:Required: *No*
:Description:
   Time to wait until GPSd returns positional information.
   A value of 0 means to wait indefinitely.


SATNOGS_APP_PATH
~~~~~~~~~~~~~~~~

:Type: *path*
:Default: ``/tmp/.satnogs``
:Required: *No*
:Description:
   Base path for storing output files.


SATNOGS_OUTPUT_PATH
~~~~~~~~~~~~~~~~~~~

:Type: *path*
:Default: ``/tmp/.satnogs/data``
:Required: *No*
:Description:
   Path for storing "output files". Output files are:

     * Audio recordings (``satnogs_{obs_id}_{timestamp}.ogg``)
     * Waterfall Images (``waterfall_{obs_id}_{timestamp}.png``)
     * Decoded frames (``data_{obs_id}``), either raw, json-encoded

       or png image data from the APT demodulator

   Temporary (potentially incomplete) files are:

     * incomplete audio recordings (``receiving_satnogs_{obs_id}_{timestamp}.ogg``)
     * incomplete APT images (``receiving_data_{]obs_id}_{timestamp}.png``)
     * Waterfall data files (``receiving_waterfall_{]obs_id}_{timestamp}.dat``)

   SatNOGS Artifacts are handled seperately.


SATNOGS_COMPLETE_OUTPUT_PATH
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *path*
:Default:
:Required: *No*
:Description:
   Path to move output files once they are completed.
   If set to empty, output files are deleted (default).
   Make sure to have enough storage available as the selected folder will
   continuously grow (about 30MB for a 5 minute observation).


SATNOGS_INCOMPLETE_OUTPUT_PATH
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *path*
:Default: ``/tmp/.satnogs/data/incomplete``
:Required: *No*
:Description:
   Path for moving incomplete output files.


SATNOGS_REMOVE_RAW_FILES
~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *True*
:Required: *No*
:Description:
   Remove raw data files used for generating waterfalls.


SATNOGS_KEEP_ARTIFACTS
~~~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *False*
:Required: *No*
:Description:
   Do not remove artifact files after successfully uploading them.


SATNOGS_ARTIFACTS_OUTPUT_PATH
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *path*
:Default: ``/tmp/.satnogs/artifacts``
:Required: *No*
:Description:
   Path for storing artifact files.


SATNOGS_VERIFY_SSL
~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *True*
:Required: *No*
:Description:
   Verify SSL certificates for HTTPS requests.


SATNOGS_NETWORK_API_URL
~~~~~~~~~~~~~~~~~~~~~~~

:Type: *url*
:Default: ``https://network.satnogs.org/api/``
:Required: *No*
:Description:
   URL pointing to API of SatNOGS Network.


SATNOGS_NETWORK_API_QUERY_INTERVAL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``60``
:Required: *No*
:Description:
   Interval (in seconds) for pulling jobs form SatNOGS Network API.


SATNOGS_NETWORK_API_POST_INTERVAL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``180``
:Required: *No*
:Description:
   Interval (in seconds) for posting observation data to SatNOGS Network API.


SATNOGS_ROT_ENABLED
~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *True*
:Required: *No*
:Description:
   Enable SatNOGS Client to connect to an antenna rotator using the Hamlib library.


SATNOGS_ROT_MODEL
~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: ``ROT_MODEL_DUMMY``
:Required: *No*
:Description:
   Rotator model to control.
   This value must be the model string of a Hamlib rotator.


SATNOGS_ROT_BAUD
~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``19200``
:Required: *No*
:Description:
   Hamlib rotator serial interface baud rate.


SATNOGS_ROT_PORT
~~~~~~~~~~~~~~~~

:Type: *path*
:Default: ``/dev/ttyUSB0``
:Required: *No*
:Description:
   Path to Hamlib rotator serial port device.
   The device must be accessible to the user which SatNOGS Client is running.


SATNOGS_ROT_THRESHOLD
~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``4``
:Required: *No*
:Description:
   Azimuth/elevation threshold for moving the rotator.
   Position changes below this threshold will not cause the rotator to move.


SATNOGS_ROT_FLIP
~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *False*
:Required: *No*
:Description:
   Enable rotator flipping during high elevation passes.


SATNOGS_ROT_FLIP_ANGLE
~~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``75``
:Required: *No*
:Description:
   Elevation angle above which the rotator will flip.


SATNOGS_RIG_IP
~~~~~~~~~~~~~~

:Type: *host*
:Default: ``127.0.0.1``
:Required: *No*
:Description:
   Hostname or IP address of Hamlib rotctld.


SATNOGS_RIG_PORT
~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``4532``
:Required: *No*
:Description:
   Hamlib rigctld TCP port.


SATNOGS_SOAPY_RX_DEVICE
~~~~~~~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: *None*
:Required: *Yes*
:Description:
   SoapySDR device driver to use for RX.
   This setting must be defined in the form ``driver=<name>`` where ``<name>`` is the name of the SoapySDR device driver to use.

   It also allows setting different devices for specific frequency ranges.

   The format for multiple devices is a space delimited list of frequency range -- device pairs:

   ``<min. freq.>-<max. freq>:driver=<name> <min. freq.>-<max. freq.>:driver=<name> ...``

   Where frequencies are in MHz and ``<name>`` is the name of the SoapySDR device driver to use for the specified frequency
   range.

   Example: two RTL-SDR receivers: one for VHF (135..148 MHz), another for UHF (430..470 MHz).

   ``135-148:driver=rtlsdr,serial=1 430-470:driver=rtlsdr,serial=2``


SATNOGS_RX_SAMP_RATE
~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: *None*
:Required: *Yes*
:Description:
   SoapySDR device sample rate.
   Valid sample rates for attached devices can be queried using ``SoapySDRUtil --probe``.


SATNOGS_RX_BANDWIDTH
~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR device RF bandwidth.
   This setting configures the RF filter on devices that support it.


SATNOGS_DOPPLER_CORR_PER_SEC
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   Number of Doppler corrections per second requested by SatNOGS Radio.


SATNOGS_LO_OFFSET
~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR device local oscillator offset to apply.
   This setting is used to shift the carrier away from the DC spike.


SATNOGS_PPM_ERROR
~~~~~~~~~~~~~~~~~

:Type: *float*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR device oscillator frequency error correction to apply.
   This setting is defined in parts per million.


SATNOGS_GAIN_MODE
~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: ``Overall``
:Required: *No*
:Description:
   SoapySDR device gain mode.
   Valid values are: ``Overall``, ``Specific``, ``Settings Field``.


SATNOGS_RF_GAIN
~~~~~~~~~~~~~~~

:Type: *float*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR device overall gain, in dB.
   Device drivers set individual, device specific gains to approximate linearity on the overall gain.


SATNOGS_ANTENNA
~~~~~~~~~~~~~~~

:Type: *string*
:Default: *None*
:Required: *Yes*
:Description:
   SoapySDR device antenna to use for RX.
   Valid antennas for attached devices can be queried using ``SoapySDRUtil --probe``.


SATNOGS_DEV_ARGS
~~~~~~~~~~~~~~~~

:Type: *string*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR device arguments.
   Valid device arguments for attached devices can be queried using ``SoapySDRUtil --probe``.


SATNOGS_STREAM_ARGS
~~~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR stream arguments.
   Valid stream arguments for attached devices can be queried using ``SoapySDRUtil --probe``.


SATNOGS_TUNE_ARGS
~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR channel tune arguments.


SATNOGS_OTHER_SETTINGS
~~~~~~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR channel other settings.


SATNOGS_DC_REMOVAL
~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: *0*
:Required: *No*
:Description:
   Advanced setting for automatic DC offset correction, provided by some SoapySDR devices.
   Set to 1 to enable SoapySDR device automatic DC offset corrections mode.

   Only use if you explicitly know you need this feature, most users should leave this disabled.

   Driver support (checked 2025-02):
   Not supported: SoapyRTLSDR, SoapyPlutoSDR
   Supported: SoapySDRPlay3, SoapyUHD, LimeSuiteNG


SATNOGS_BB_FREQ
~~~~~~~~~~~~~~~

:Type: *string*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   SoapySDR device baseband CORDIC frequency for devices that support it.


ENABLE_IQ_DUMP
~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *False*
:Required: *No*
:Description:
   Create I/Q data dumps for every observation.
   Use this feature with caution.
   Enabling this setting will store large amount of data on the filesystem.


IQ_DUMP_FILENAME
~~~~~~~~~~~~~~~~

:Type: *path*
:Default: *None*
:Required: *No*
:Description:
   Path to file for storing I/Q data dumps.


DISABLE_DECODED_DATA
~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *False*
:Required: *No*
:Description:
   Disable output of decoded data.


UDP_DUMP_HOST
~~~~~~~~~~~~~

:Type: *host*
:Default: *Flowgraph-defined*
:Required: *No*
:Description:
   IP destination of UDP data with Doppler corrected I/Q.


UDP_DUMP_PORT
~~~~~~~~~~~~~

:Type: *port*
:Default: ``57356``
:Required: *No*
:Description:
   Port for UDP data with Doppler corrected I/Q.


SATNOGS_UPLOAD_AUDIO_FILES
~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *True*
:Required: *No*
:Description:
   Enable/Disable uploading audio files to SatNOGS network.


SATNOGS_UPLOAD_WATERFALL_FILES
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *True*
:Required: *No*
:Description:
   Enable/Disable uploading waterfalls to SatNOGS network.


SATNOGS_WATERFALL_AUTORANGE
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *True*
:Required: *No*
:Description:
   Automatically set power level range of waterfall images.


SATNOGS_WATERFALL_MIN_VALUE
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``-100``
:Required: *No*
:Description:
   Minimum power level of waterfall images.


SATNOGS_WATERFALL_MAX_VALUE
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``-50``
:Required: *No*
:Description:
   Maximum power level of waterfall images.


SATNOGS_ARTIFACTS_ENABLED
~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *False*
:Required: *No*
:Description:
   Enable generation and uploading of HDF5 artifacts files to SatNOGS DB.


SATNOGS_ARTIFACTS_API_URL
~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *url*
:Default: ``https://db.satnogs.org/api/``
:Required: *No*
:Description:
   URL pointing to API of SatNOGS DB for uploading artifacts.


SATNOGS_ARTIFACTS_API_POST_INTERVAL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *integer*
:Default: ``180``
:Required: *No*
:Description:
   Interval (in seconds) for posting artifacts to SatNOGS DB.


SATNOGS_ARTIFACTS_API_TOKEN
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: *None*
:Required: *No*
:Description:
   SatNOGS DB API token associated with an account in SatNOGS DB.
   This token is secret.
   It is used to upload artifacts to SatNOGS DB.
   It can be found in SatNOGS DB user page.


SATNOGS_LOG_LEVEL
~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: ``WARNING``
:Required: *No*
:Description:
   SatNOGS Client logging level.
   Valid values are:

     * ``CRITICAL``
     * ``ERROR``
     * ``WARNING``
     * ``INFO``
     * ``DEBUG``


SATNOGS_SCHEDULER_LOG_LEVEL
~~~~~~~~~~~~~~~~~~~~~~~~~~~

:Type: *string*
:Default: ``WARNING``
:Required: *No*
:Description:
   SatNOGS Client scheduler logging level.
   Valid values are:

     * ``CRITICAL``
     * ``ERROR``
     * ``WARNING``
     * ``INFO``
     * ``DEBUG``


SENTRY_DSN
~~~~~~~~~~

:Type: *string*
:Default: ``d50342fb75aa8f3945e2f846b77a0cdb7c7d2275``
:Required: *No*
:Description:
   Sentry Data Source Name used for sending events to application monitoring and error tracking server.


SENTRY_ENABLED
~~~~~~~~~~~~~~

:Type: *boolean*
:Default: *False*
:Required: *No*
:Description:
   Enable sending events to Sentry application monitoring and error tracking server.
