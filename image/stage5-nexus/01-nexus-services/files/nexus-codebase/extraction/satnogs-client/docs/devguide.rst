Developer guide
===============

Installation
------------

To install the required dependencies in Debian Bullseye run::

  $ xargs -r -a packages.debian apt-get install


It is recommended to install the client in a virtualenv.
The virtualenv needs to have access to system Python bindings.
To create the virtualenv, you can use ``virtualenvwrapper``.
On the first time, create the virtualenv by running::

  $ mkvirtualenv --system-site-packages -a . satnogs-client

To activate the virtualenv after it is created run::

  $ workon satnogs-client

To install SatNOGS Client for development run in the project root directory::

  $ pip install -e .[dev]


Configuration
-------------

This project uses ``python-dotenv``.
Configuration of ``satnogsclient/settings.py`` can be overridden by setting the respective environment variables or an ``.env`` file placed on the project root directory.
Check :ref:`configuration` for a list of all configuration variables.

Code Quality Assurance
----------------------

The following code quality assurance tools are used in this project:

  * ``flake8``
  * ``isort``
  * ``yapf``
  * ``pylint``
  * ``robotframework``

Testing
-------

System testing
^^^^^^^^^^^^^^

Robot Framework is used for system testing.
``robot/testsuites`` contain Robot test cases and suites.


Automation
----------

``tox`` is used to automate development tasks.
To execute the default list of tasks run::

  $ tox


Environments
^^^^^^^^^^^^

The following ``tox`` environments are available:

  * ``flake8`` - Check code for common errors, coding style and complexity
  * ``isort`` - Check code for correct imports order
  * ``isort-apply`` - Sort imports
  * ``yapf`` - Check code for correct formatting
  * ``yapf-apply`` - Reformat source code
  * ``pylint`` - Execute static code analysis
  * ``build`` - Build source and binary distributions
  * ``upload`` - Upload source and binary distributions to PyPI
  * ``docs`` - Build documentation
  * ``deps`` - Check for broken dependencies
  * ``pytest`` - Execute application tests
  * ``robot-lint`` - Lint system test cases and suites
  * ``robot-tidy`` - Reformat system test cases and suites
  * ``robot`` - Execute system testing

To execute a single environment run::

  $ tox -e <environment>


Dependency Management
---------------------

Dependencies of the package are defined in the ``setup.cfg`` file.
Only top-level dependencies shall be defined, with the exception of overrides needed to workaround dependency incompatibilities.
Each dependency is defined using the appropriate compatible version specifier.
The compatible version specifiers shall be such that any newer compatible version can be installed, taking into account the versioning schema followed by each dependency.
The ``dev`` extra contains packages and tools required for development, testing and packaging.
When a dependency has been added, removed or updated in ``setup.cfg``, the requirement files must be manually regenerated.
To regenerate these files run::

  $ .scm-ci-helpers/refresh-requirements-docker.sh

The script will update the following files:

  * ``requirements.txt`` - List of resolved dependencies for the package
  * ``requirements-dev.txt`` - List of resolved dependencies for the development tools
  * ``constraints.txt`` - List of resolved dependency constraints for both the package and development tools

Changes on the above files shall be committed together with the changes in ``setup.cfg``.
