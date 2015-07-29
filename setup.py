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
## \file setup.py
# nxsconfigserver-db installer 

""" setup.py for NXS configuration server """

import os
from distutils.core import setup

## package name
NDTS = "sardanascanrecorders"
## nxswriter imported package
INDTS = __import__(NDTS)


## reading a file
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


## metadata for distutils
SETUPDATA = dict(
    name = "nexdatas.sardanascanrecorders",
    version=INDTS.__version__,
    author = "Jan Kotanski",
    author_email = "jankotan@gmail.com",
    description = ("NeXus Sardana Scan Recorder"),
    license = "GNU GENERAL PUBLIC LICENSE v3",
    keywords = "NeXus sardana scan recorder data",
    url = "https://github.com/jkotan/nexdatas.sardanascanrecorders/",
    packages=['sardanascanrecorders'],
    long_description= read('README')
)


        

## the main function
def main():
    setup(**SETUPDATA)
        

if __name__ == '__main__':
    main()

