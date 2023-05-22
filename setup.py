from setuptools import setup, find_packages
from os.path import join, dirname

setup(
    name='pin-dl',
    version='0.0.1',
    packages=find_packages(),
    long_description=open(join(dirname(__file__), 'README.md')).read(),
    entry_points={
        'console_scripts':
            ['pin-dl = src:main']
    },
    install_requires=[
        "lxml==4.3.1",
        "requests==2.31.0",
        "progress==1.5",
    ]
)
