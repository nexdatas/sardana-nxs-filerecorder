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

Download the latest NeXuS Scan Recorder version from

    https://github.com/jkotan/nexdatas/sardanascanrecorders/

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

and

.. code:: bash

	  $ apt-get install python-nxsrecselector nxselector

for Component Selector for Sardana related packages.

-------------------
Setting environment
-------------------

Setting Saradna
"""""""""""""""

If sardana is not yet set up run


.. code:: bash

	  $ Pool

- enter a new instance name
- create the new instance

Then wait a while until Pool is started and in a new terminal run

.. code:: bash

	  $ MacroServer

- enter a new instance name
- create the new instance
- connect pool

Next, run Astor and change start-up levels: for Pool to 2,
for MacroServer to 3 and restart servers.

Alternatively, terminate Pool and MacroServer in the terminals and run

.. code:: bash

          $ nxsetup -s Pool -l2

wait until Pool is started and run

.. code:: bash

          $ nxsetup -s MacroServer -l3


Additionally, one can create dummy devices by running `sar_demo` in

.. code:: bash

	  $ spock


Setting NeXus Servers
"""""""""""""""""""""

To set up  NeXus Servers run

.. code:: bash

	  $ nxsetup -x

or

.. code:: bash

          $ nxsetup -x NXSDataWriter
          $ nxsetup -x NXSConfigServer
	  $ nxsetup -x NXSRecSelector

for specific servers.

If the `RecoderPath` property of MacroServer is not set one can do it by

.. code:: bash

	  $ nxsetup -a /usr/lib/python2.7/dist-packages/sardananxsrecorder

where the path should point the `sardananxsrecorder` package.
