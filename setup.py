#!/usr/bin/env python3
"""NEXUS OS - Blockchain Operating System Package"""

from setuptools import setup, find_packages

setup(
    name='nexus-os',
    version='1.1.0-beta',
    description='Blockchain-native operating system for Raspberry Pi clusters',
    author='Acex215',
    url='https://github.com/Acex215/Nexus-OS',
    packages=find_packages(),
    python_requires='>=3.8',
    install_requires=[
        'web3>=6.0.0',
        'flask>=2.0.0',
        'flask-cors>=3.0.0',
        'requests>=2.28.0',
        'pyyaml>=6.0',
        'click>=8.0.0',
        'colorlog>=6.0.0',
    ],
    extras_require={
        'dev': [
            'pytest>=7.0.0',
            'pytest-cov>=4.0.0',
            'black>=23.0.0',
            'flake8>=6.0.0',
        ],
        'contracts': [
            'py-solc-x>=1.1.0',
        ],
    },
    entry_points={
        'console_scripts': [
            'nexus-cli=scripts.cli.nexus_cli:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: System :: Operating System',
    ],
)
