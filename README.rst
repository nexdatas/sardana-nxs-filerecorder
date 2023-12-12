Welcome to sardananxsrecorder's documentation!
==============================================
|github workflow|
|docs|
|Pypi Version|
|Python Versions|

.. |github workflow| image:: https://github.com/nexdatas/sardana-nxs-filerecorder/actions/workflows/tests.yml/badge.svg
   :target: https://github.com/nexdatas/sardana-nxs-filerecorder/actions
   :alt:

.. |docs| image:: https://img.shields.io/badge/Documentation-webpages-ADD8E6.svg
   :target: https://nexdatas.github.io/sardana-nxs-filerecorder/index.html
   :alt:

.. |Pypi Version| image:: https://img.shields.io/pypi/v/sardana-nxsrecorder.svg
                  :target: https://pypi.python.org/pypi/sardana-nxsrecorder
                  :alt:

.. |Python Versions| image:: https://img.shields.io/pypi/pyversions/sardana-nxsrecorder.svg
                     :target: https://pypi.python.org/pypi/sardana-nxsrecorder/
                     :alt:


NeXus scan recorder for Sardana which stores experimenal data in NeXus/HDF5 file with use of
NeXDatas Tango Server or packages, i.e. NXSDataWriter, NXSConfigServer, NXSRecSelector.

| Source code: https://github.com/nexdatas/sardana-nxs-filerecorder
| Web page: https://nexdatas.github.io/sardana-nxs-filerecorder
| NexDaTaS Web page: https://nexdatas.github.io


------------
Installation
------------

Install the dependencies:

|    sardana, sphinx, NXSDataWriter, NXSConfigServer, NXSRecSelector

From sources
""""""""""""

Download the latest NeXuS Scan Recorder version from

|    https://github.com/nexdatas/sardana-nxs-filerecorder

Extract sources and run

.. code-block:: console

	  $ python setup.py install

and add an *RecorderPath* property of *MacroServer* with its value
defining the package location, e.g.

|    /usr/lib/python2.7/dist-packages/sardananxsrecorder


Debian packages
"""""""""""""""

Debian Bookworm, Bullseye, Buster and Ubuntu Lunar, Jammy and Focal packages can be found in the HDRI repository.

To install the debian packages, add the PGP repository key

.. code-block:: console

	  $ sudo su
	  $ wget -q -O - http://repos.pni-hdri.de/debian_repo.pub.gpg | apt-key add -

and then download the corresponding source list

.. code-block:: console

	  $ cd /etc/apt/sources.list.d
	  $ wget http://repos.pni-hdri.de/bookworm-pni-hdri.list


Finally, for python2.7

.. code-block:: console

	  $ apt-get update
	  $ apt-get install python-sardana-nxsrecorder

and set the RecoderPath property of MacroServer with

.. code-block:: console

	  $ apt-get install sardana-nxsrecorder

For python3

.. code-block:: console

	  $ apt-get update
	  $ apt-get install python3-sardana-nxsrecorder
	  $ apt-get install sardana-nxsrecorder3

To instal other NexDaTaS packages

.. code-block:: console

	  $ apt-get install python-nxswriter nxsconfigserver-db python-nxsconfigserver nxsconfigtool python-nxstools nxswriter nxsconfigserver nxsrecselector

or for python 3

.. code-block:: console

	  $ apt-get install python3-nxswriter nxsconfigserver-db python3-nxsconfigserver nxsconfigtool3 python3-nxstools nxswriter3 nxsconfigserver3

and

.. code-block:: console

	  $ apt-get install python-nxsrecselector nxsrecselector nxselector

or for python3

.. code-block:: console

	  $ apt-get install python3-nxsrecselector nxsrecselector3 nxselector3

for Component Selector for Sardana related packages.

-------------------
Setting environment
-------------------

Setting Saradna
"""""""""""""""

If sardana is not yet set up run


.. code-block:: console

	  $ Pool

- enter a new instance name
- create the new instance

Then wait a while until Pool is started and in a new terminal run

.. code-block:: console

	  $ MacroServer

- enter a new instance name
- create the new instance
- connect pool

Next, run Astor and change start-up levels: for Pool to 2,
for MacroServer to 3 and restart servers.

Alternatively, terminate Pool and MacroServer in the terminals and run

.. code-block:: console

          $ nxsetup start Pool -l2

wait until Pool is started and run

.. code-block:: console

          $ nxsetup start MacroServer -l3


Additionally, one can create dummy devices by running `sar_demo` in

.. code-block:: console

	  $ spock


Setting NeXus Servers
"""""""""""""""""""""

To set up  NeXus Servers run

.. code-block:: console

	  $ nxsetup set

or

.. code-block:: console

          $ nxsetup set NXSDataWriter
          $ nxsetup set NXSConfigServer
	  $ nxsetup set NXSRecSelector

for specific servers.

If the `RecoderPath` property of MacroServer is not set one can do it by

.. code-block:: console

	  $ nxsetup add-recorder-path /usr/lib/python2.7/dist-packages/sardananxsrecorder

where the path should point the `sardananxsrecorder` package.

-----------------
Sardana Variables
-----------------

The NeXus file recorder uses the following sardana environment variables

* **ActiveMntGrp** *(str)* - active measurement group
* **ScanID** *(int)* - the last scan identifier number, default: ``-1``
* **NeXusSelectorDevice** *(str)* - NXSRecSelector tango device if more installed, otherwise first one found

* **NXSAppendSciCatDataset** *(bool)* - append scan name to scicat dataset list file, default: ``False``
* **BeamtimeFilePath** *(str)* - beamtime file path to search beamtime metadata file, default: ``"/gpfs/current"``
* **BeamtimeFilePrefix** *(str)* - beamtime metadata file prefix, default: ``"beamtime-metadata-"``
* **BeamtimeFileExt** *(str)* - beamtime metadata file extension, default: ``".json"``
* **SciCatDatasetListFilePrefix** *(str)* - scicat dataset list file prefix, default: ``"scicat-datasets-"``
* **SciCatDatasetListFileExt** *(str)* - scicat dataset list file extension, default: ``".lst"``
* **SciCatDatasetListFileLocal** *(bool)* - add the hostname to the scicat dataset list file extension, default: ``False``
* **MetadataScript** or **FioAdditions** *(str)* - a python module file name containing ``main()``  which provides a dictionary with user metadata stored in the INIT mode, default: ``""``
