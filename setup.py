#!/usr/bin/env python

from setuptools import setup

setup(
        name='python3-discogs-alerts',
        version='1.0.0',
        description='Get notification from Discogs',
        long_description='Tols for tracking specifics release and get notifications',
        url='https://github.com/beudbeud/discogs_alerts',
        author='beudbeud',
        author_email='beudbeud@gmail.com',
        install_requires=open("./requirements.txt", "r").read().split(),
        scripts=[],
        entry_points={"console_scripts": ["discoger = discoger.discoger:main"]},
        packages=['discoger'],
        package_dir={"discoger": "discoger"},
        include_package_data=True,
        )
