Welcome to sardananxsrecorder's documentation!
==============================================

NeXus scan recorder for Sardana which stores experimenal data in NeXus/HDF5 file with use of
NeXDatas Tango Server or packages, i.e. NXSDataWriter, NXSConfigServer, NXSRecSelector.

| Source code: https://github.com/nexdatas/sardanascanrecorders
| Web page: http://www.desy.de/~jkotan/nxsrecorder

------------
Installation
------------

Install the dependencies:

    sardana, sphinx, NXSDataWriter, NXSConfigServer, NXSRecSelector

From sources
""""""""""""

Download the latest NXS Tools version from

    https://github.com/jkotan/nexdatas.tools/

Extract sources and run

.. code:: bash

	  $ python setup.py install

and add an *RecorderPath* property of *MacroServer* with its value
defining the package location, e.g.

    /usr/lib/python2.7/dist-packages/sardananxsrecorder

	  
Debian packages
"""""""""""""""

Debian Jessie (and Wheezy) packages can be found in the HDRI repository.

To install the debian packages, add the PGP repository key

.. code:: bash

	  $ sudo su
	  $ wget -q -O - http://repos.pni-hdri.de/debian_repo.pub.gpg | apt-key add -

and then download the corresponding source list

.. code:: bash

	  $ cd /etc/apt/sources.list.d
	  $ wget http://repos.pni-hdri.de/jessie-pni-hdri.list

Finally,

.. code:: bash

	  $ apt-get update
	  $ apt-get install python-sardana-nxsrecorder

To instal other NexDaTaS packages

.. code:: bash

	  $ apt-get install python-nxswriter nxsconfigserver-db python-nxsconfigserver nxsconfigtool python-nxstools

and for Sardana related packages

.. code:: bash

	  $ apt-get install python-nxsrecselector nxselector

for component selector.
