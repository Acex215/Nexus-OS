from setuptools import setup, find_packages

setup(
    name='libnexus',
    version='0.2.0',
    description='NEXUS OS Kernel System Call Library',
    packages=['libnexus'],
    package_dir={'libnexus': '.'},
    install_requires=[
        'web3>=6.0.0',
    ],
    python_requires='>=3.9',
)
