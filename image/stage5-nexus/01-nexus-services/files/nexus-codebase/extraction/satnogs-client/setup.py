from os import getenv

import versioneer
from setuptools import setup

setup_args = {
    'version': versioneer.get_version(),
    'cmdclass': versioneer.get_cmdclass(),
}

if getenv('READTHEDOCS') == 'True':
    setup_args['install_requires'] = ['setuptools']

setup(**setup_args)
