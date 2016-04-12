#!/usr/bin/env python
#   This file is part of nexdatas - Tango Server for NeXus data writer
#
#    Copyright (C) 2012-2014 DESY, Jan Kotanski <jkotan@mail.desy.de>
#
#    nexdatas is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    nexdatas is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with nexdatas.  If not, see <http://www.gnu.org/licenses/>.
#

""" setup.py for NXS configuration recorder """

import os
from distutils.core import setup
from sphinx.setup_command import BuildDoc


#: package name
NDTS = "sardananxsrecorder"
#: nxswriter imported package
INDTS = __import__(NDTS)


def read(fname):
    """ reading a file
    """
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

release = INDTS.__version__
version = ".".join(release.split(".")[:2])
name = "Sardana NeXus Recorder"

#: metadata for distutils
SETUPDATA = dict(
    name="nexdatas.sardananxsrecorder",
    version=INDTS.__version__,
    author="Jan Kotanski",
    author_email="jankotan@gmail.com",
    description=("NeXus Sardana Scan Recorder"),
    license="GNU GENERAL PUBLIC LICENSE v3",
    keywords="NeXus sardana scan recorder data",
    url="https://github.com/jkotan/nexdatas.sardanascanrecorders/",
    packages=['sardananxsrecorder'],
    cmdclass={'build_sphinx': BuildDoc},
    command_options={
        'build_sphinx': {
            'project': ('setup.py', name),
            'version': ('setup.py', version),
            'release': ('setup.py', release)}},
    long_description= read('README.rst')
)


def main():
    """ the main function
    """
    setup(**SETUPDATA)


if __name__ == '__main__':
    main()
