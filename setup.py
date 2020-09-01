# Always prefer setuptools over distutils
from setuptools import setup

from src.__init__ import __version__

with open('requirements.txt') as fp:
    reqs = fp.read()

setup(
    name='gradescope-web',
    author='',
    url='',
    version=__version__,
    package_dir={'gradescope_web': 'src'},
    packages=['gradescope_web'],
    description="Scaffolding for Noah Mendelsohn's Testing Framework",
    install_requires=reqs,
)
