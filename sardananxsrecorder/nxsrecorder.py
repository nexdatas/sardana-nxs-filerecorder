#!/usr/bin/env python
#   This file is part of nexdatas - Tango Server for NeXus data writer
#
#    Copyright (C) 2012-2018 DESY, Jan Kotanski <jkotan@mail.desy.de>
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

"""This is the macro server scan data NeXus recorder module"""


import os
import re
import sys

import numpy
import json
import time
import weakref
import socket

try:
    import tango
except Exception:
    import PyTango as tango

try:
    NXSWRITER = True
    try:
        from nxstools import h5cppwriter as h5writer
    except Exception:
        from nxstools import h5pywriter as h5writer
except Exception:
    NXSWRITER = False


from sardana.macroserver.scan.recorder.storage import BaseFileRecorder
from sardana.macroserver.macro import StopException

try:
    from sardana.macroserver.scan.gscan import ScanEndStatus
except Exception:
    ScanEndStatus = None


try:
    from sardana import __version__
    lv = list(map(int, __version__.split(".")))[:2]
    isarver = lv[0] * 100 + lv[1]
except Exception:
    isarver = 300


__docformat__ = 'restructuredtext'


#: (:obj:`dict` <:obj:`str`, :obj:`str`>) maps a Sardana scan end status to
#:    the blissdata "end_reason" convention. Consumers such as daiquiri map
#:    SUCCESS -> FINISHED, USER_ABORT -> ABORTED and FAILURE/DELETION ->
#:    FAILED. A stopped or aborted scan is user driven, so both map to
#:    USER_ABORT; an exception is reported as a failure.
END_REASON_BY_END_STATUS = {
    "Normal": "SUCCESS",
    "Stop": "USER_ABORT",
    "Abort": "USER_ABORT",
    "Exception": "FAILURE",
}


class MacroLog(object):

    """ logger of the recorder which shows warnings also in the macro
    """

    def __init__(self, recorder, macro=None):
        """ constructor

        :param recorder: recorder
        :type recorder: :class:`NXS_FileRecorder`
        :param macro: weak reference to the macro
        :type macro: :class:`weakref.ref`
        """
        #: (:class:`NXS_FileRecorder`) recorder
        self.recorder = recorder
        #: (:class:`weakref.ref`) weak reference to the macro
        self.macro = macro

    def debug(self, msg):
        """ logs a debug message

        :param msg: message
        :type msg: :obj:`str`
        """
        self.recorder.debug(msg)

    def info(self, msg):
        """ logs an info message

        :param msg: message
        :type msg: :obj:`str`
        """
        self.recorder.info(msg)

    def warning(self, msg):
        """ logs a warning message and shows it in the macro

        :param msg: message
        :type msg: :obj:`str`
        """
        self.recorder.warning(msg)
        macro = self.macro() if self.macro else None
        if macro is not None:
            macro.warning(msg)


class NXS_FileRecorder(BaseFileRecorder):
    """ This recorder saves data to a NeXus file making use of NexDaTaS Writer
    """

    #: (:obj:`dict` <:obj:`str`, :obj:`str` > ) recoder format
    formats = {
        'nxs': '.nxs',
        'nx': '.nx',
        'h5': '.h5',
        'ndf': '.ndf'
    }

    class numpyEncoder(json.JSONEncoder):
        """ numpy json encoder with list
        """
        def default(self, obj):
            """ default encoder

            :param obj: numpy array object
            :type obj: :obj:`object` or `any`
            """
            if isinstance(obj, numpy.integer):
                return int(obj)
            elif isinstance(obj, numpy.floating):
                return float(obj)
            elif isinstance(obj, numpy.ndarray):
                return obj.tolist()
            elif isinstance(obj, numpy.bool_):
                return bool(obj)
            return json.JSONEncoder.default(self, obj)

    def __init__(self, filename=None, macro=None, **pars):
        """ constructor

        :param filename: ScanFile name
        :type filename: :obj:`str`
        :param macro: macro object
        :type macro: :class:`sardana.macroserver.macro.Macro`
        """
        BaseFileRecorder.__init__(self)
        self.debug('__init__:  Init NXS_FileRecorder: %s' % str(filename))
        #: (:obj:`str`) base filename
        self.__base_filename = filename
        #: (:obj:`str`) raw filename
        self.__raw_filename = ""
        self.__macro = weakref.ref(macro) if macro else None
        #: (:class:`tango.Database`) tango database
        self.__db = tango.Database()

        #: (:class:`tango.DeviceProxy`)
        #:      NXS data writer device
        self.__nexuswriter_device = None

        #: (:class:`tango.DeviceProxy`)
        #:     NXS settings server device
        self.__nexussettings_device = None

        #: (:obj:`int`) device proxy timeout
        # self.__timeout = 100000
        self.__timeout = 10000000
        #: (:obj:`dict` <:obj:`str`, :obj:`list` <:obj:`str`>
        #:     or :obj:`dict` <:obj:`str` , `any`> > ) Custom variables
        self.__vars = {"data": {},
                       "datasources": {},
                       "decoders": {},
                       "vars": {},
                       "triggers": []}

        #: (:obj:`str`) dynamic components
        self.__dynamicCP = "__dynamic_component__"
        #: (:obj:`str`) cache component prefix
        self.__cacheCPPrefix = "__configuration_"

        #: (:obj:`dict` <:obj:`str` , `any`> ) environment
        self.__env = macro.getAllEnv() if macro else {}

        #: (:obj:`str`) default timezone
        self.__timezone = "Europe/Berlin"

        #: (:obj:`str`) default NeXus configuration env variable
        self.__defaultenv = "NeXusConfiguration"

        #: (:obj:`str`) module lable
        self.__moduleLabel = 'module'

        #: (:obj:`int`) serialno
        self.__serial = 0

        #: (:obj:`dict` <:obj:`str` , :obj:`str`>) NeXus configuration
        self.__conf = {}

        #: (:obj:`list` <:obj:`str`>) acquisition Modes
        self.writerModes = self.__variableList(
            "NeXusWriterModes")

        #: (:obj:`dict` <:obj:`str` , `any`>) User data
        self.__udata = None

        #: (:obj:`bool`) external measurement group
        self.__oddmntgrp = False

        #: (:obj:`bool`) h5map mode, see :meth:`enable_h5map`
        self.__h5map = False
        #: (:obj:`set` <:obj:`str`>) names and labels of channels streamed
        #:     by the scan data publisher, i.e. with references in records
        self.__streamed = set()
        #: (:obj:`bool`) entry opened in h5map mode
        self.__h5map_started = False
        #: (:class:`nxstools.h5mapwriter.H5MapFile`) h5map file tree
        self.__h5map_file = None

        self.debug('__init__:  Set NeXus: %s' % str(filename))
        self.__setNexusDevices(onlyconfig=True)

        self.debug('__init__:  Set Append Entry: %s' % str(filename))
        appendentry = self.__getConfVar("AppendEntry", True)
        scanID = self.__env["ScanID"] \
            if "ScanID" in self.__env.keys() else -1
        self.debug('__init__:  Set FileName: %s' % str(filename))
        self.__setFileName(
            self.__base_filename, not appendentry, scanID)
        self.debug('__init__:  Done: %s' % str(filename))

    def _serial(self, scanID):
        serial = None
        if "NOINIT" in self.writerModes and \
           "MESH" in self.writerModes:
            if self.__macro:
                serial = self.__macro().getEnv('NeXusMeshScanID', None)
        if serial is None:
            if scanID is None:
                serial = self.recordlist.getEnvironValue('serialno')
            elif scanID >= 0:
                if isarver >= 304 or isarver == 0:
                    serial = scanID
                else:
                    serial = scanID + 1
        if "MESH" in self.writerModes and \
           "NOINIT" not in self.writerModes:
            if self.__macro:
                self.__macro().setEnv('NeXusMeshScanID', serial)
        return serial

    def __command(self, server, command, *args):
        """ execute tango server (or python object) command

        :param server: server name (or python object)
        :type server: :class:`tango.DeviceProxy`
        :param command: command name
        :type command: :obj:`str`
        :param *args: command arguments
        :type *args: :obj:`list` <`any`>
        :returns: command result
        :rtype: `any`
        """
        if server and command:
            if hasattr(server, 'command_inout'):
                if args:
                    return server.command_inout(command, args[0])
                else:
                    return server.command_inout(command)
            else:
                res = getattr(server, command)
                return res(*args)
        else:
            self.warning("%s.%s cannot be found" % (server, command))
            if self.__macro:
                self.__macro().warning(
                    "%s.%s cannot be found" % (server, command))

    def __getConfVar(self, var, default, decode=False, pass_default=False):
        """ provides configuration variable from fetched profile configuration

        :param var: variable name
        :type var: :obj:'str'
        :param default: default variable value
        :type default: `any`
        :param decode: True if variable should be encode from JSON
        :type decode: :obj:`bool`
        :param pass_default: if True it returns :default:
        :type pass_default: :obj:`bool`
        :returns: configuration variable value
        :rtype: `any`
        """
        if pass_default:
            return default
        if var in self.__conf.keys():
            res = self.__conf[var]
            if decode:
                try:
                    dec = json.loads(res)
                    return dec
                except Exception:
                    self.warning("%s = '%s' cannot be decoded" % (var, res))
                    if self.__macro:
                        self.__macro().warning(
                            "%s = '%s' cannot be decoded" % (var, res))
                    return default
            else:
                return res
        else:
            self.warning("%s cannot be found" % (var))
            if self.__macro:
                self.__macro().warning(
                    "%s cannot be found" % (var))
            return default

    def __getServerVar(self, attr, default, decode=False, pass_default=False):
        """ provides configuration variable from selector server
            or python object

        :param var: variable name
        :type var: :obj:'str'
        :param default: default variable value
        :type default: `any`
        :param decode: True if variable should be encode from JSON
        :type decode: :obj:`bool`
        :param pass_default: if True it returns :default:
        :type pass_default: :obj:`bool`
        :returns: server attribute value
        :rtype: `any`
        """
        if pass_default:
            return default
        if self.__nexussettings_device and attr:
            res = getattr(self.__nexussettings_device, attr)
            if decode:
                try:
                    dec = json.loads(res)
                    return dec
                except Exception:
                    self.warning("%s = '%s' cannot be decoded" % (attr, res))
                    if self.__macro:
                        self.__macro().warning(
                            "%s = '%s' cannot be decoded" % (attr, res))
                    return default
            else:
                return res
        else:
            self.warning("%s cannot be found" % (attr))
            if self.__macro:
                self.__macro().warning(
                    "%s  cannot be found" % (attr))
            return default

    def __getEnvVar(self, var, default, pass_default=False):
        """ provides spock environment variable

        :param var: variable name
        :type var: :obj:'str'
        :param default: default variable value
        :type default: `any`
        :param pass_default: if True it returns :default:
        :type pass_default: :obj:`bool`
        :returns: environment variable value
        :rtype: `any`
        """
        if pass_default:
            return default
        if var in self.__env.keys():
            return self.__env[var]
        elif self.__defaultenv in self.__env.keys():
            nenv = self.__env[self.__defaultenv]
            attr = var.replace("NeXus", "")
            if attr in nenv:
                return nenv[attr]
        return default

    @classmethod
    def __wait(cls, proxy, counter=100):
        """ waits until device is running

        :param proxy: device proxy
        :type proxy: :class:`tango.DeviceProxy`
        :param counter: command timeout in 0.01s units
        :type counter: :obj:`int`
        """
        found = False
        cnt = 0
        while not found and cnt < counter:
            if cnt > 1:
                time.sleep(0.01)
            try:
                if proxy.state() != tango.DevState.RUNNING:
                    found = True
            except tango.DevFailed:
                time.sleep(0.01)
                found = False
                if cnt == counter - 1:
                    raise
            cnt += 1

    def __asynchcommand(self, server, command, *args):
        """ execute tango server (or python object) command asynchronously

        :param server: server proxy (or python object)
        :type server: :class:`tango.DeviceProxy`
        :param command: command name
        :type command: :obj:`str`
        :param *args: command arguments
        :type *args: :obj:`list` <`any`>
        """
        try:
            self.__command(server, command, *args)
        except tango.CommunicationFailed as e:
            if e[-1].reason == "API_DeviceTimedOut":
                self.__wait(server)
            else:
                raise

    def __setFileName(self, filename, number=True, scanID=None):
        """ sets the file names w/o scanID

        :param filename: sardana scanfile name
        :type filename: :obj:`str`
        :param number: True if append scanID
        :param number: :obj:`bool`
        :param scanID: scanID to append
        :type scanID: :obj:`int`
        :returns: True if append scanID
        :rtype: :obj:`bool`
        """
        if scanID is not None and scanID < 0:
            return number

        dirname = os.path.dirname(filename)
        if not dirname:
            self.warning(
                "Missing file directory. "
                "File will be saved in the local writer directory.")
            if self.__macro:
                self.__macro().warning(
                    "Missing file directory. "
                    "File will be saved in the local writer directory.")
            dirname = '/'

        if not os.path.isdir(dirname):
            try:
                os.makedirs(dirname)
                os.chmod(dirname, 0o777)
            except Exception as e:
                if self.__macro:
                    self.__macro().warning(str(e))
                self.warning(str(e))
                self.filename = None
                return number

        subs = (len([None for _ in list(re.finditer('%', filename))]) == 1)
        # construct the filename, e.g. : /dir/subdir/etcdir/prefix_00123.nxs
        self.__serial = self._serial(scanID)

        if subs:
            try:
                #: output file name
                self.filename = filename % self.__serial
            except Exception:
                subs = False
        if not self.__raw_filename:
            self.__raw_filename = self.__rawfilename(self.__serial)
        self.debug('__setFileName:  '
                   'Raw Filename: %s' % str(self.__raw_filename))
        if not subs and self.__raw_filename and \
           "{ScanID" in self.__raw_filename:
            try:
                self.filename = self.__raw_filename.format(
                    ScanID=self.__serial)
                subs = True
            except Exception:
                pass

        if not subs:
            if number:
                if filename.endswith('.tmp') and \
                   filename[-4].rpartition(".")[0] and \
                   filename[-4].rpartition(".")[2] in self.formats.keys():
                    tpl = filename[-4].rpartition(".")
                    self.filename = "%s_%05d.%s.tmp" % (
                        tpl[0], self.__serial, tpl[2])
                else:
                    tpl = filename.rpartition('.')
                    self.filename = "%s_%05d.%s" % (
                        tpl[0], self.__serial, tpl[2])
            else:
                self.filename = filename

        return number or subs

    def getFormat(self):
        """ provides the output file format

        :returns: the output file format
        :rtype: :obj:`str`
        """
        return 'nxs'

    def __setNexusDevices(self, onlyconfig=False):
        """ sets nexus Tango devices

        :param onlyconfig: If True do not set NXSDataWriter and
                           profile configuration of NXSRecSelector
        :type onlyconfig: :obj:`bool`
        """
        self.debug(
            '__setNexusDevices:  NXSRecSelector: %s'
            % str(self.__raw_filename))
        vl = self.__getEnvVar("NeXusSelectorDevice", None)
        if vl is None:
            servers = self.__db.get_device_exported_for_class(
                "NXSRecSelector").value_string
        else:
            servers = [str(vl)]
        if len(servers) > 0 and len(servers[0]) > 0 \
                and servers[0] != self.__moduleLabel:
            try:
                self.__nexussettings_device = tango.DeviceProxy(servers[0])
                self.__nexussettings_device.set_timeout_millis(self.__timeout)
                self.__nexussettings_device.ping()
                self.__nexussettings_device.set_source(tango.DevSource.DEV)
            except Exception:
                self.__nexussettings_device = None
                self.warning("Cannot connect to '%s' " % servers[0])
                if self.__macro:
                    self.__macro().warning(
                        "Cannot connect to '%s'" % servers[0])
        else:
            self.__nexussettings_device = None
        self.debug('__setNexusDevices:  import profile: %s'
                   % str(self.__raw_filename))
        if self.__nexussettings_device is None:
            from nxsrecconfig import Settings
            self.__nexussettings_device = Settings.Settings()
            self.__nexussettings_device.importEnvProfile()
        if not hasattr(self.__nexussettings_device, "version") or \
           int(str(self.__nexussettings_device.version).split(".")[0]) < 2:
            raise Exception("NXSRecSelector (%s) version below 2.0.0" %
                            (servers[0] if servers else "module"))

        self.debug('__setNexusDevices:  set MG: %s' % str(self.__raw_filename))
        mntgrp = self.__getServerVar("mntGrp", None)
        amntgrp = self.__getEnvVar("ActiveMntGrp", None)
        if mntgrp and amntgrp != mntgrp:
            self.__nexussettings_device.mntgrp = amntgrp
        self.debug('__setNexusDevices:  list profile: %s'
                   % str(self.__raw_filename))
        if amntgrp not in self.__command(
                self.__nexussettings_device, "availableProfiles"):
            if onlyconfig:
                self.warning((
                    "NXS_FileRecorer: a profile for '%s' does not exist, "
                    "creating a default profile.\n"
                    "Consider to run 'spock> nxselector' to select "
                    "additional components.") % amntgrp)
                if self.__macro:
                    self.__macro().warning((
                        "NXS_FileRecorer: a profile for '%s' does not exist, "
                        "creating a default profile.\n"
                        "Consider to run 'spock> nxselector' to select "
                        "additional components.") % amntgrp)
                    self.__macro().info(
                        "NXS_FileRecorer: "
                        "descriptive components will be reset")
                self.info(
                    "NXS_FileRecorer: descriptive components will be reset")
            else:
                self.debug('__setNexusDevices:  fetch profile: %s'
                           % str(self.__raw_filename))
                self.__command(self.__nexussettings_device, "fetchProfile")
                self.debug('__setNexusDevices:  reset profile: %s'
                           % str(self.__raw_filename))
                self.__asynchcommand(self.__nexussettings_device,
                                     "resetPreselectedComponents")
                self.debug('__setNexusDevices:  reset profile Done: %s'
                           % str(self.__raw_filename))
            self.__oddmntgrp = True
        else:
            self.debug('__setNexusDevices:  '
                       'fetch profile 2: %s' % str(self.__raw_filename))
            self.__command(self.__nexussettings_device, "fetchProfile")
            self.debug('__setNexusDevices:  fetch profile 2 Done: %s' %
                       str(self.__raw_filename))
        self.__vars["vars"]["measurement_group"] = amntgrp

        self.debug('__setNexusDevices:  '
                   'profile config: %s' % str(self.__raw_filename))
        self.__conf = self.__getServerVar("profileConfiguration", {}, True)
        self.debug('__setNexusDevices:  '
                   'MG config: %s' % str(self.__raw_filename))
        if not self.__oddmntgrp and not onlyconfig:
            if "MntGrpConfiguration" in self.__conf.keys():
                poolmg = self.__command(
                    self.__nexussettings_device, "mntGrpConfiguration")
                profmg = self.__getConfVar("MntGrpConfiguration", None, False)
            else:
                poolmg = None
                profmg = None
            if not poolmg or not profmg or poolmg != profmg:
                self.debug("__setNexusDevices:  "
                           "ActiveMntGrp created outside NXSRecSelector v3. "
                           "Updating ActiveMntGrp")
                if self.__macro:
                    self.__macro().debug(
                        "ActiveMntGrp created outside NXSRecSelector v3. "
                        "Updating ActiveMntGrp")
                self.__command(self.__nexussettings_device, "importMntGrp")
                self.__command(self.__nexussettings_device, "updateMntGrp")
                if hasattr(self.__nexussettings_device, "cachecomponent"):
                    ccomp = self.__nexussettings_device.cachecomponent
                    if ccomp:
                        self.debug('__setNexusDevices: '
                                   'Cache Writer Configuration: %s'
                                   % str(ccomp))
                        self.__command(
                            self.__nexussettings_device,
                            "cacheWriterConfiguration", [])

        self.debug('__setNexusDevices: '
                   'Writer Device: %s' % str(self.__raw_filename))
        if not onlyconfig:
            vl = self.__getConfVar("WriterDevice", None)
            if self.__h5map:
                # the in-process writer exporting the tree to an h5map
                vl = self.__moduleLabel
            if not vl:
                servers = self.__db.get_device_exported_for_class(
                    "NXSDataWriter").value_string
            else:
                servers = [str(vl)]

            if len(servers) > 0 and len(servers[0]) > 0 \
                    and servers[0] != self.__moduleLabel:
                try:
                    self.__nexuswriter_device = tango.DeviceProxy(servers[0])
                    self.__nexuswriter_device.set_timeout_millis(
                        self.__timeout)
                    self.__nexuswriter_device.ping()
                    self.__nexuswriter_device.set_source(tango.DevSource.DEV)
                except Exception:
                    self.__nexuswriter_device = None
                    self.warning("Cannot connect to '%s' " % servers[0])
                    if self.__macro:
                        self.__macro().warning(
                            "Cannot connect to '%s'" % servers[0])
            else:
                self.__nexuswriter_device = None

            self.debug('__setNexusDevices:  Writer Device Properties: %s'
                       % str(self.__raw_filename))
            if self.__nexuswriter_device is None:
                from nxswriter import TangoDataWriter
                self.__nexuswriter_device = TangoDataWriter.TangoDataWriter()
                try:
                    properties = dict(
                        self.__getEnvVar("NeXusWriterProperties", {}))
                except Exception as e:
                    self.warning(
                        "Cannot load NeXusWriterProperties %s" % (str(e)))
                    self.__macro().warning(
                        "Cannot load NeXusWriterProperties %s" % (str(e)))
                    properties = {}
                for ky, vl in properties.items():
                    if hasattr(self.__nexuswriter_device, ky):
                        setattr(self.__nexuswriter_device, ky, vl)
                if self.__h5map:
                    self.__nexuswriter_device.writer = "h5map"
        self.debug('__setNexusDevices:  End: %s' % str(self.__raw_filename))

    def __get_alias(self, name):
        """ provides a device alias

        :param name: device name
        :type name: :obj:`str`
        :returns: device alias
        :rtype: :obj:`str`
        """
        # if name does not contain a "/" it's probably an alias
        if name.startswith("tango://"):
            name = name[8:]
        if name.find("/") == -1:
            return name

        # haso107klx:10000/expchan/hasysis3820ctrl/1
        if name.find(':') >= 0:
            lst = name.split("/")
            name = "/".join(lst[1:])
        try:
            alias = self.__db.get_alias(name)
        except Exception:
            alias = None
        return alias

    def __skipAcquisition(self):
        """ skips the acquisition of the next writer command

        The Tango attribute names of NXSDataWriter are case insensitive,
        while the in-process TangoDataWriter reads ``skipacquisition``.
        """
        if hasattr(self.__nexuswriter_device, 'command_inout'):
            self.__nexuswriter_device.skipAcquisition = True
        else:
            self.__nexuswriter_device.skipacquisition = True

    def __removeDynamicComponent(self):
        """ removes the dynamic component
        """
        self.__command(self.__nexussettings_device,
                       "removeDynamicComponent",
                       str(self.__dynamicCP))

    def __motorNames(self):
        """ provides motor names of the macro server pools

        :returns: motor names
        :rtype: :obj:`list` <:obj:`str`>
        """
        names = []
        for pool in self.__macro().getPools():
            names.extend(json.loads(motor)["name"]
                         for motor in pool.MotorList)
        return names

    @classmethod
    def streamedChannels(cls, envRec):
        """ provides channels streamed by the scan data publisher

        Records of Sardana with a blissdata publisher contain stream
        references of these channels, i.e. of Streamable controllers.
        Older Sardana versions do not mark channels as streamed.

        :param envRec: scan environment with ``datadesc``
        :type envRec: :obj:`dict` <:obj:`str`, `any`>
        :returns: names and labels of the streamed channels
        :rtype: :obj:`set` <:obj:`str`>
        """
        names = set()
        for dd in envRec.get("datadesc") or []:
            if isinstance(dd, dict):
                streamed = dd.get("external_stream", False)
                keys = [dd.get("name"), dd.get("label")]
            else:
                streamed = getattr(dd, "external_stream", False)
                keys = [getattr(dd, "name", None), getattr(dd, "label", None)]
            if streamed:
                names.update(str(key) for key in keys if key)
        return names

    @classmethod
    def streamedEnviron(cls, envRec):
        """ provides the scan environment with streamed channels
            described as string references, as in the Sardana HDF5 recorder

        :param envRec: scan environment with ``datadesc``
        :type envRec: :obj:`dict` <:obj:`str`, `any`>
        :returns: scan environment for the writer configuration
        :rtype: :obj:`dict` <:obj:`str`, `any`>
        """
        streamed = cls.streamedChannels(envRec)
        if not streamed:
            return envRec
        env = dict(envRec)
        datadesc = []
        for dd in envRec.get("datadesc") or []:
            name = dd.get("name") if isinstance(dd, dict) \
                else getattr(dd, "name", None)
            if name is not None and str(name) in streamed:
                label = dd.get("label") if isinstance(dd, dict) \
                    else getattr(dd, "label", None)
                datadesc.append({"name": name, "label": label,
                                 "shape": [], "dtype": "string"})
            else:
                datadesc.append(dd)
        env["datadesc"] = datadesc
        return env

    def __createConfiguration(self, userdata):
        """ create NeXus configuration

        The configuration is created by
        :class:`nxsrecconfig.WriterConfiguration.WriterConfiguration`.

        :param userdata: user data dictionary
        :type userdata: :obj:`dict` <:obj:`str` , `any`>
        :returns: configuration xml string
        :rtype: :obj:`str`
        """
        self.debug("__createConfiguration:  Init: %s" % self.__oddmntgrp)
        try:
            from nxsrecconfig.WriterConfiguration import WriterConfiguration
        except ImportError as e:
            raise Exception(
                "NXS_FileRecorder requires nxsrecconfig >= 4.15.0 "
                "(python3-nxsrecselector): %s" % str(e))
        wconf = WriterConfiguration(
            self.__nexussettings_device,
            conf=self.__conf,
            variables=self.__vars["vars"],
            log=MacroLog(self, self.__macro),
            getalias=self.__get_alias,
            moveables=self.__motorNames if self.__macro else None,
            oddmntgrp=self.__oddmntgrp,
            cacheprefix=self.__cacheCPPrefix,
            dynamiccp=self.__dynamicCP)
        envRec = self.recordlist.getEnviron()
        if not self.__h5map:
            envRec = self.streamedEnviron(envRec)
        try:
            cnfxml = wconf.create(envRec, userdata)
        finally:
            self.__dynamicCP = wconf.dynamicCP
        self.debug("__createConfiguration:  End: %s" % self.__oddmntgrp)
        return cnfxml

    def _startRecordList(self, recordlist):
        """ starts record process: creates configuration
            and records in INIT mode

        :param recordlist: sardana record list
        :type recordlist: :class:`sardana.macroserver.scan.scandata.RecordList`
        """
        if self.__h5map and self.__h5map_started:
            # the entry was already opened by the h5map builder
            return
        try:
            self.debug('_startRecordList:  Start %s' % self.__base_filename)
            self.__env = self.__macro().getAllEnv() if self.__macro else {}
            if self.__base_filename is None:
                return
            self.__udata = None

            self.debug('_startRecordList:  Set NeXus %s'
                       % self.__base_filename)
            self.__setNexusDevices()
            self.debug('_startRecordList:  Set Variables %s'
                       % self.__base_filename)

            appendentry = self.__getConfVar("AppendEntry", True)
            appendscanid = not self.__setFileName(
                self.__base_filename, not appendentry)
            envRec = self.recordlist.getEnviron()
            self.__streamed = set() if self.__h5map \
                else self.streamedChannels(envRec)
            if self.__streamed:
                msg = ("NXS_FileRecorder: %s streamed by the scan data "
                       "publisher, their references are stored. "
                       "Use the 'nxs' h5map builder to store their data"
                       % ", ".join(sorted(self.__streamed)))
                self.info(msg)
                if self.__macro:
                    self.__macro().info(msg)
            self.__vars["vars"]["serialno"] = ("_%05i" % self.__serial) \
                if appendscanid else ""
            self.__vars["vars"]["scan_id"] = envRec["serialno"]
            self.__vars["vars"]["acq_modes"] = \
                ",".join(self.writerModes or [])
            self.__vars["vars"]["scan_title"] = envRec["title"]
            if self.__macro:
                if hasattr(self.__macro(), "integ_time"):
                    self.__vars["vars"]["count_time"] = \
                        self.__macro().integ_time
                npoints = 0
                if hasattr(self.__macro(), "nb_points"):
                    self.__vars["vars"]["nrepetitions"] = 1
                    self.__vars["vars"]["npoints"] = \
                        self.__macro().nb_points
                    npoints = self.__macro().nb_points
                elif hasattr(self.__macro(), "nr_points"):
                    self.__vars["vars"]["nrepetitions"] = 1
                    self.__vars["vars"]["npoints"] = \
                        self.__macro().nr_points
                    npoints = self.__macro().nr_points
                if hasattr(self.__macro(), "nb_repeat"):
                    self.__vars["vars"]["nrepetitions"] = 1
                    self.__vars["vars"]["npoints"] = \
                        npoints * self.__macro().nb_repeat
                    self.__vars["vars"]["nrepetitions"] = \
                        self.__macro().nb_repeat
                if hasattr(self.__macro(), "nb_repetitions"):
                    self.__vars["vars"]["nrepetitions"] = \
                        self.__macro().nb_repetitions
                    self.__vars["vars"]["npoints"] = \
                        npoints * self.__macro().nb_repetitions

                if hasattr(self.__macro(), "param_def"):
                    json_ready_params = []

                    for item in self.__macro().param_def:
                        name, param_type, default, description = item

                        json_ready_params.append({
                            "name": name,
                            "type": str(param_type),
                            "default": default,
                            "description": description
                        })
                    self.__vars["vars"]["scan_param_def"] \
                        = json.dumps(json_ready_params).replace('"', '&quot;')

            if 'ref_moveables' in envRec:
                self.__vars["vars"]["ref_moveables"] = " ".join(
                    envRec['ref_moveables'])

            self.__vars["vars"]["beamtime_id"] = self.beamtimeid()
            tzone = self.__getConfVar("TimeZone", self.__timezone)
            self.__vars["data"]["start_time"] = \
                self.__timeToString(envRec['starttime'], tzone)
            self.__vars["vars"]["filename"] = str(self.filename)

            envrecord = self.__appendRecord(self.__vars, 'INIT')
            self.debug('_startRecordList:  Create Configuration %s'
                       % self.__base_filename)
            cnfxml = self.__createConfiguration(envrecord["data"])
            self.debug('_startRecordList:  Set Remove dynamic components %s'
                       % self.__base_filename)
            rec = json.dumps(
                envrecord, cls=NXS_FileRecorder.numpyEncoder)
            # self.debug('XML: %s' % str(cnfxml))
            self.__removeDynamicComponent()

            self.__vars["data"]["serialno"] = self.__serial
            self.__vars["data"]["scan_title"] = envRec["title"]
            if self.__macro:
                if hasattr(self.__macro(), "integ_time"):
                    self.__vars["data"]["count_time"] = \
                        self.__macro().integ_time
                if hasattr(self.__macro(), "nb_points"):
                    self.__vars["data"]["npoints"] = \
                        self.__macro().nb_points
            self.__vars["data"]["beamtime_id"] = \
                self.__vars["vars"]["beamtime_id"]

            self.debug('_startRecordList:  Init writer %s'
                       % self.__base_filename)
            if hasattr(self.__nexuswriter_device, 'Init'):
                self.__command(self.__nexuswriter_device, "Init")
            self.__nexuswriter_device.fileName = str(self.filename)
            self.__command(self.__nexuswriter_device, "openFile")
            if self.__h5map:
                # closeFile drops the file, the h5maps are exported later
                self.__h5map_file = self.__nexuswriter_device.getFile()
            self.__nexuswriter_device.xmlsettings = cnfxml

            if "DEBUG_INIT_DATA" in self.writerModes:
                self.debug('_startRecordList:  INIT_DATA: %s' % str(envRec))

            self.debug('_startRecordList: Set JSON %s' % self.__base_filename)
            self.__nexuswriter_device.jsonrecord = rec
            self.writerModes = self.__variableList(
                "NeXusWriterModes")
            if "NOINIT" in self.writerModes:
                self.__skipAcquisition()

            self.debug('_startRecordList SE: Open Entry %s' %
                       self.__base_filename)
            self.__command(self.__nexuswriter_device, "openEntry")
            if self.__h5map:
                self.__h5map_started = True
        except Exception:
            self.__removeDynamicComponent()
            raise
        self.debug('_startRecordList SE: END %s' % self.__base_filename)

    def __appendRecord(self, var, mode=None):
        """ merges userdata with variable dictionary

        :param var: variable dictionary
        :type var: { `data`: :obj:`dict` <:obj:`str`, `any`> ,
                     `datasouces`: :obj:`dict` <:obj:`str`, :obj:`str`> ,
                     `decoders`: :obj:`dict` <:obj:`str`, :obj:`str`> ,
                     `triggers`: :obj:`list` <:obj:`str`> }
        :param mode: nexus writer mode: INIT, STEP, FINAL
        :type mode: :obj:`str`
        :returns: merged data dictionary
        :rtype: { `data`: :obj:`dict` <:obj:`str`, `any`> ,
                  `datasouces`: :obj:`dict` <:obj:`str`, :obj:`str`> ,
                  `decoders`: :obj:`dict` <:obj:`str`, :obj:`str`> ,
                  `triggers`: :obj:`list` <:obj:`str`> }
        """
        nexusrecord = {}
        dct = self.__getConfVar("UserData", None, True)
        if isinstance(dct, dict):
            nexusrecord = dct

        ms = None
        msf = None
        if not isinstance(self.__udata, dict):
            if 'MetadataScript' in self.__env.keys():
                msf = self.__env['MetadataScript']
            # elif 'FioAdditions' in self.__env.keys():
            #     msf = self.__env['FioAdditions']
            if msf:
                if not os.path.exists(msf):
                    self.warning("NXS_FileRecorder: %s does not exist" % msf)
                    if self.__macro:
                        self.__macro().warning(
                            "NXS_FileRecorder: %s does not exist" % msf)
                else:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location('', msf)
                    msm = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(msm)
                    ms = msm.main()
                    if not isinstance(ms, dict):
                        self.warning(
                            "NXS_FileRecorder: bad output from %s" % msf)
                        if self.__macro:
                            self.__macro().warning(
                                "NXS_FileRecorder: bad output from %s" % msf)
                        self.__udata = {}
                    else:
                        self.__udata = ms
        if isinstance(self.__udata, dict) and isinstance(ms, dict):
            nexusrecord.update(self.__udata)

        record = dict(var)
        record["data"] = dict(var["data"], **nexusrecord)
        if mode == 'INIT':
            if var["datasources"]:
                record["datasources"] = dict(var["datasources"])
            if var["decoders"]:
                record["decoders"] = dict(var["decoders"])
        elif mode == 'FINAL':
            pass
        else:
            if var["triggers"]:
                record["triggers"] = list(var["triggers"])
        return record

    def _writeRecord(self, record):
        """ performs record process step: creates configuration
            and records in INIT mode

        :param record: sardana record list
        :type record: :class:`sardana.macroserver.scan.scandata.Record`
        """
        try:
            if self.filename is None:
                return
            if self.__h5map:
                # STEP data goes through blissdata streams
                return
            try:
                self.__env = self.__macro().getAllEnv() \
                    if self.__macro else {}
            except StopException as e:
                self.warning(
                    "Environment cannot be read: %s" % (str(e)))
            envrecord = self.__appendRecord(self.__vars, 'STEP')
            rec = json.dumps(
                envrecord, cls=NXS_FileRecorder.numpyEncoder)
            self.__nexuswriter_device.jsonrecord = rec
            if "NOSTEP" in self.writerModes:
                self.__skipAcquisition()

            if "DEBUG_STEP_DATA" in self.writerModes:
                self.debug('_writeRecord DATA: {"data":%s}' % json.dumps(
                    record.data,
                    cls=NXS_FileRecorder.numpyEncoder))

            data = record.data
            if self.__streamed:
                # streamed channels provide string references,
                # placeholders, e.g. NaN, are skipped
                data = {key: value for key, value in data.items()
                        if key not in self.__streamed or
                        isinstance(value, str)}
            jsonString = '{"data":%s}' % json.dumps(
                data,
                cls=NXS_FileRecorder.numpyEncoder)
            # self.debug("JSON!!: %s" % jsonString)
            self.__command(self.__nexuswriter_device, "record", jsonString)
        except Exception:
            self.__removeDynamicComponent()
            raise

    def __timeToString(self, mtime, tzone):
        """ convers time objects to string

        :param mtime: sardana current time
        :type mtime: :obj:`str`
        :param tzone: local time zone
        :type tzone: :obj:`str`
        :returns: formatted time string
        :rtype: :obj:`str`
        """
        fmt = '%Y-%m-%dT%H:%M:%S.%f%z'
        try:
            if sys.version_info >= (3, 9):
                import zoneinfo
                tz = zoneinfo.ZoneInfo(tzone)
                starttime = mtime.replace(tzinfo=tz)
            else:
                import pytz
                tz = pytz.timezone(tzone)
                starttime = tz.localize(mtime)
        except Exception:
            self.warning(
                "Wrong TimeZone. "
                "The time zone set to `%s`" % self.__timezone)
            if self.__macro:
                self.__macro().warning(
                    "Wrong TimeZone. "
                    "The time zone set to `%s`" % self.__timezone)
            if sys.version_info >= (3, 9):
                import zoneinfo
                tz = zoneinfo.ZoneInfo(self.__timezone)
                starttime = mtime.replace(tzinfo=tz)
            else:
                import pytz
                tz = pytz.timezone(self.__timezone)
                starttime = tz.localize(mtime)

        return str(starttime.strftime(fmt))

    def __endReason(self, envRec):
        """ maps the Sardana scan end status to a blissdata end_reason

        :param envRec: record list environment
        :type envRec: :obj:`dict` <:obj:`str`, :obj:`any`>
        :returns: scan end reason, e.g. SUCCESS, USER_ABORT or FAILURE
        :rtype: :obj:`str`
        """
        endstatus = (envRec or {}).get("endstatus")
        if endstatus is None or ScanEndStatus is None:
            return "SUCCESS"
        try:
            name = ScanEndStatus.whatis(endstatus)
        except Exception:
            name = endstatus
        return END_REASON_BY_END_STATUS.get(name, "SUCCESS")

    def _endRecordList(self, recordlist):
        """ ends record process: records in FINAL mode
            and closes the nexus file

        :param recordlist: sardana record list
        :type recordlist: :class:`sardana.macroserver.scan.scandata.RecordList`
        """
        try:
            if self.filename is None:
                return

            self.__env = self.__macro().getAllEnv() if self.__macro else {}
            envRec = recordlist.getEnviron()

            if "DEBUG_FINAL_DATA" in self.writerModes:
                self.debug('_endRecordList:  FINAL_DATA: %s ' % str(envRec))

            tzone = self.__getConfVar("TimeZone", self.__timezone)
            self.__vars["data"]["end_time"] = \
                self.__timeToString(envRec['endtime'], tzone)
            self.__vars["data"]["end_reason"] = self.__endReason(envRec)

            envrecord = self.__appendRecord(self.__vars, 'FINAL')

            rec = json.dumps(
                envrecord, cls=NXS_FileRecorder.numpyEncoder)
            self.__nexuswriter_device.jsonrecord = rec
            if "NOFINAL" in self.writerModes:
                self.__skipAcquisition()
            self.__command(self.__nexuswriter_device, "closeEntry")
            self.__command(self.__nexuswriter_device, "closeFile")
        except Exception:
            self.__command(self.__nexuswriter_device, "closeFile")
        finally:
            self.__h5map_started = False
            self.__removeDynamicComponent()
            vl = self.__getEnvVar("NXSAppendSciCatDataset", None)
            if vl:
                self.__appendSciCatDataset(vl)
            cmf = self.__getEnvVar("CreateMeasurementFile", False)
            if cmf and NXSWRITER:
                self.__createMeasurementFile()

    def enable_h5map(self):
        """ switches the recorder to the h5map mode

        The NeXus tree is built in memory by an in-process NXSDataWriter
        with the ``h5map`` writer of nxstools and exported by :meth:`h5maps`
        to blissdata, which writes the file, e.g. with blisswriter.
        STEP records are not written, as their data goes through
        blissdata streams.  It has to be called before the record list
        is started.
        """
        self.__h5map = True

    def disable_h5map(self):
        """ switches the recorder back to writing the file itself

        The tree built in the h5map mode is dropped.  It has to be called
        before the record list is started by the scan, e.g. when the
        h5map builder fails.
        """
        if self.__h5map_started:
            self.__removeDynamicComponent()
        self.__h5map = False
        self.__h5map_started = False
        self.__h5map_file = None
        self.__nexuswriter_device = None

    @property
    def h5map_mode(self):
        """ h5map mode flag

        :returns: True if the recorder works in the h5map mode
        :rtype: :obj:`bool`
        """
        return self.__h5map

    def h5maps(self, streams=None, skip=None):
        """ exports the NeXus tree to the h5maps of a blissdata scan

        :param streams: stream names of STEP fields or a stream resolver,
                        see :meth:`nxstools.h5mapwriter.H5MapFile.h5map`
        :type streams: :obj:`dict` <:obj:`str`, :obj:`str`> or callable
        :param skip: strategies of fields to be skipped, e.g. ``["FINAL"]``
        :type skip: :obj:`list` <:obj:`str`>
        :returns: ``{file name: h5map}`` or an empty dictionary
        :rtype: :obj:`dict` <:obj:`str`, `any`>
        """
        if self.__h5map_file is None:
            return {}
        return self.__h5map_file.h5maps(streams, skip)

    def beamtime_id(self, bmtfpath, bmtfprefix, bmtfext):
        """ code for beamtimeid  datasource

        :param bmtfpath:  beamtime file directory
        :type bmtfpath: :obj:`str`
        :param bmtfprefix:  beamtime file prefix
        :type bmtfprefix: :obj:`str`
        :param bmtfext:  beamtime file postfix
        :type bmtfext: :obj:`str`
        :returns: beamtime id
        :rtype: :obj:`str`
        """
        result = ""
        fpath = self.filename
        try:
            if fpath.startswith(bmtfpath):
                if os.path.isdir(bmtfpath):
                    btml = [fl for fl in os.listdir(bmtfpath)
                            if (fl.startswith(bmtfprefix)
                                and fl.endswith(bmtfext))]
                    result = btml[0][len(bmtfprefix):-len(bmtfext)]
        except Exception:
            pass
        return result

    def beamtimeid(self):
        bmtfpath = self.__getEnvVar("BeamtimeFilePath", "/gpfs/current")
        bmtfprefix = self.__getEnvVar(
            "BeamtimeFilePrefix", "beamtime-metadata-")
        bmtfext = self.__getEnvVar("BeamtimeFileExt", ".json")
        beamtimeid = self.beamtime_id(bmtfpath, bmtfprefix, bmtfext)
        return beamtimeid or "00000000"

    def __variableList(self, variable='NeXusWriterModes'):
        """ read variable list
        """
        try:
            msvar = self.__macro().getEnv(variable)
        except Exception:
            msvar = []
        if isinstance(msvar, str):
            msvar = re.split(r"[-;,.\s]\s*", msvar)
        if msvar:
            self.debug('__variableList:   %s: %s' % (variable, str(msvar)))
        return msvar

    def __rawfilename(self, serial):
        """ find scan name
        """
        try:
            scan_file = self.__macro().getEnv('ScanFile')
        except Exception:
            scan_file = []
        try:
            scan_dir = self.__macro().getEnv('ScanDir')
        except Exception:
            scan_dir = "/"
        if isinstance(scan_file, str):
            scan_file = [scan_file]
        bfilename = ""

        for sfile in scan_file:
            sfile = os.path.join(scan_dir, sfile)
            try:
                ffile = sfile.format(ScanID=serial)
            except KeyError:
                ffile = sfile
            if ffile == self.__base_filename:
                bfilename = sfile
                break
        bfilename = bfilename or self.__base_filename
        return bfilename

    def __scanname(self, serial, default=None):
        """ find scan name
        """
        if not self.__raw_filename:
            self.__raw_filename = self.__rawfilename(serial)
        if default:
            return default
        bfilename = self.__raw_filename
        _, bfname = os.path.split(bfilename)
        if bfname.endswith(".tmp"):
            bfname = bfname[:-4]
        sname, fext = os.path.splitext(bfname)
        scanname = os.path.commonprefix(
            [sname.format(ScanID=11111111),
             sname.format(ScanID=99999999)])
        if '%' in scanname:
            try:
                scanname = os.path.commonprefix(
                    [scanname % 11111111,
                     scanname % 99999999])
            except Exception:
                pass
        if scanname.endswith("_"):
            scanname = scanname[:-1]
        return scanname

    def __appendSciCatDataset(self, hostname=None):
        """ append dataset to SciCat ingestion list """

        sid = self.__serial
        fdir, fname = os.path.split(self.filename)
        snmode = self.__getEnvVar("ScanNames", None)
        nometa = self.__getEnvVar("ScanNamesNoMetadata", False)
        nogrouping = self.__getEnvVar("ScanNamesNoGrouping", False)
        appendentry = self.__getConfVar("AppendEntry", False)
        pdir = None
        if snmode is not None:
            if bool(snmode):
                fdir = os.path.dirname(os.path.abspath(fdir))
            elif appendentry is False:
                fdir, pdir = os.path.split(os.path.abspath(fdir))
        sname, fext = os.path.splitext(fname)
        beamtimeid = self.beamtimeid()
        defprefix = "scicat-datasets-"
        defaulthost = self.__getEnvVar("SciCatDatasetListFileLocal", None)
        if defaulthost:
            hostname = socket.gethostname()
        if hostname and hostname is not True and hostname.lower() != "true":
            defprefix = "%s%s-" % (defprefix, str(hostname))
        dslprefix = self.__getEnvVar("SciCatDatasetListFilePrefix", defprefix)
        dslext = self.__getEnvVar("SciCatDatasetListFileExt", ".lst")
        dslfile = "%s%s%s" % (dslprefix, beamtimeid, dslext)
        if fdir:
            dslfile = os.path.join(fdir, dslfile)

        entryname = "scan"
        appendentry = self.__getConfVar("AppendEntry", False)
        variables = self.__getConfVar("ConfigVariables", None, True)
        if isinstance(variables, dict) and "entryname" in variables:
            entryname = variables["entryname"]

        scanname = self.__scanname(sid, pdir)
        # _, bfname = os.path.split(self.__base_filename)
        # try:
        #     scanname, _ = os.path.splitext(bfname % "")
        # except Exception:
        #     scanname, _ = os.path.splitext(bfname)

        if appendentry is True and \
                '%' not in self.__raw_filename and \
                "{ScanID" not in self.__raw_filename:
            sid = self.__serial
            sname = "%s::/%s_%05i;%s_%05i" % (
                scanname, entryname, sid, scanname, sid)
        if pdir:
            sname = "%s/%s" % (pdir, sname)
        if "NOINIT" in self.writerModes:
            sname = "%s:%s" % (sname, time.time())

        # auto grouping
        grouping = bool(self.__getEnvVar('SciCatAutoGrouping', False))

        if grouping or pdir:
            commands = []
            try:
                sm = dict(self.__getEnvVar('SciCatMeasurements', {}))
                if not isinstance(sm, dict):
                    sm = {}
            except Exception:
                sm = {}

            if fdir in sm.keys():
                cgrp = sm[fdir]
                if cgrp != scanname:
                    if not nogrouping and not nometa:
                        commands.append("__command__ stop")
                        commands.append("%s:%s" % (cgrp, time.time()))
                        commands.append("__command__ start %s" % scanname)
            else:
                if not nogrouping and not nometa:
                    commands.append("__command__ start %s" % scanname)
            if not nometa:
                commands.append(sname)
            if not nogrouping and not nometa:
                commands.append("__command__ stop")
            if not nogrouping:
                commands.append("%s:%s" % (scanname, time.time()))
            sname = "\n".join(commands)

            if not nogrouping and not nometa:
                sm[fdir] = scanname
            self.__env['SciCatMeasurements'] = sm

        if sname:
            with open(dslfile, "a+") as fl:
                fl.write("\n%s" % sname)

    def __createMeasurementFile(self):
        """ create measurement file """

        sid = self.__serial
        fdir, fname = os.path.split(self.filename)
        pdir = None
        snmode = self.__getEnvVar("ScanNames", None)
        appendentry = self.__getConfVar("AppendEntry", False)
        if snmode is not None:
            if bool(snmode):
                fdir = os.path.dirname(os.path.abspath(fdir))
            elif appendentry is False:
                fdir, pdir = os.path.split(os.path.abspath(fdir))
        sname, fext = os.path.splitext(fname)
        # beamtimeid = self.beamtimeid()

        scanname = self.__scanname(sid, pdir)
        # _, bfname = os.path.split(self.__base_filename)
        # try:
        #     scanname, _ = os.path.splitext(bfname % "")
        # except Exception:
        #     scanname, _ = os.path.splitext(bfname)

        try:
            sm = dict(self.__getEnvVar('SciCatMeasurements', {}))
            if not isinstance(sm, dict):
                sm = {}
        except Exception:
            sm = {}

        entryname = "scan"
        appendentry = self.__getConfVar("AppendEntry", False)
        variables = self.__getConfVar("ConfigVariables", None, True)
        if isinstance(variables, dict) and "entryname" in variables:
            entryname = variables["entryname"]
        if appendentry is True:
            if '%' not in self.__raw_filename and \
               "{ScanID" not in self.__raw_filename:
                sname = sname + ("_%05i" % sid)
                entryname = entryname + ("_%05i" % sid)
        mntname = scanname
        if fdir in sm.keys() and sm[fdir]:
            mntname = sm[fdir]
        if not appendentry or mntname != scanname:
            mntfile = os.path.join(fdir, mntname + fext)

            if not os.path.exists(mntfile):
                fl = h5writer.create_file(mntfile)
                self.info("Measurement file '%s' created " % mntname)
            else:
                fl = h5writer.open_file(mntfile, readonly=False)
            rt = fl.root()
            if sname not in rt.names():
                if pdir:
                    h5writer.link("%s/%s:/%s" %
                                  (pdir, fname, entryname), rt, sname)
                else:
                    h5writer.link("%s:/%s" % (fname, entryname), rt, sname)
                self.debug("__createMeasurementFile:  "
                           "Link  '%s' in '%s' created " % (sname, mntname))
            rt.close()
            fl.close()

    def _addCustomData(self, value, name, group="data", remove=False,
                       **kwargs):
        """ adds custom data to configuration variables, i.e. from macros

        :param value: variable value
        :type value: `any`
        :param name: variable name
        :type name: :obj:`str`
        :param group: variable group inside variable dictionary
        :type group: :obj:`str`
        :param remove: if True variable will be removed
        :type remove: :obj:`bool`
        """
        if group:
            if group not in self.__vars.keys():
                self.__vars[group] = {}
            if not remove:
                self.__vars[group][name] = value
            else:
                self.__vars[group].pop(name, None)
        else:
            if not remove:
                self.__vars[name] = value
            else:
                self.__vars.pop(name, None)
