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

import numpy
import json
import pytz
import time
import PyTango
import weakref

from sardana.macroserver.scan.recorder.storage import BaseFileRecorder

__docformat__ = 'restructuredtext'


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
            elif isinstance(obj, numpy.ndarray) and obj.ndim > 0:
                return obj.tolist()
            return json.JSONEncoder.default(self, obj)

    def __init__(self, filename=None, macro=None, **pars):
        """ constructor

        :param filename: ScanFile name
        :type filename: :obj:`str`
        :param macro: macro object
        :type macro: :class:`sardana.macroserver.macro.Macro`
        """
        BaseFileRecorder.__init__(self)
        #: (:obj:`str`) base filename
        self.__base_filename = filename
        self.__macro = weakref.ref(macro) if macro else None
        #: (:class:`PyTango.Database`) tango database
        self.__db = PyTango.Database()

        #: (:class:`PyTango.DeviceProxy`)
        #:      NXS data writer device
        self.__nexuswriter_device = None

        #: (:class:`PyTango.DeviceProxy`)
        #:     NXS settings server device
        self.__nexussettings_device = None

        #: (:obj:`int`) device proxy timeout
        self.__timeout = 100000
        #: (:obj:`dict` <:obj:`str`, :obj:`list` <:obj:`str`>
        #:     or :obj:`dict` <:obj:`str` , `any`> > ) Custom variables
        self.__vars = {"data": {},
                       "datasources": {},
                       "decoders": {},
                       "vars": {},
                       "triggers": []}

        #: (:obj:`dict` <:obj:`str` , :obj:`str`>) device aliases
        self.__deviceAliases = {}
        #: (:obj:`dict` <:obj:`str` , `None`>) dynamic datasources
        self.__dynamicDataSources = {}

        #: (:obj:`str`) dynamic components
        self.__dynamicCP = "__dynamic_component__"

        #: (:obj:`dict` <:obj:`str` , `any`> ) environment
        self.__env = macro.getAllEnv() if macro else {}

        #: (:obj:`list` <:obj:`str`>) available components
        self.__availableComps = []

        #: (:obj:`list` <:obj:`str`>) ordered aliases
        self.__aliases = []

        #: (:obj:`str`) default timezone
        self.__timezone = "Europe/Berlin"

        #: (:obj:`str`) default NeXus configuration env variable
        self.__defaultenv = "NeXusConfiguration"

        #: (:obj:`str`) module lable
        self.__moduleLabel = 'module'

        #: (:obj:`dict` <:obj:`str` , :obj:`str`>) NeXus configuration
        self.__conf = {}

        #: (:obj:`bool`) external measurement group
        self.__oddmntgrp = False

        self.__setNexusDevices(onlyconfig=True)

        appendentry = self.__getConfVar("AppendEntry", True)
        scanID = self.__env["ScanID"] \
            if "ScanID" in self.__env.keys() else -1
        appendentry = not self.__setFileName(
            self.__base_filename, not appendentry, scanID)

    def __command(self, server, command, *args):
        """ execute tango server (or python object) command

        :param server: server name (or python object)
        :type server: :class:`PyTango.DeviceProxy`
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
        :type proxy: :class:`PyTango.DeviceProxy`
        :param counter: command timeout in 0.01s units
        :type counter: :obj:`int`
        """
        found = False
        cnt = 0
        while not found and cnt < counter:
            if cnt > 1:
                time.sleep(0.01)
            try:
                if proxy.state() != PyTango.DevState.RUNNING:
                    found = True
            except PyTango.DevFailed:
                time.sleep(0.01)
                found = False
                if cnt == counter - 1:
                    raise
            cnt += 1

    def __asynchcommand(self, server, command, *args):
        """ execute tango server (or python object) command asynchronously

        :param server: server proxy (or python object)
        :type server: :class:`PyTango.DeviceProxy`
        :param command: command name
        :type command: :obj:`str`
        :param *args: command arguments
        :type *args: :obj:`list` <`any`>
        """
        try:
            self.__command(server, command, *args)
        except PyTango.CommunicationFailed as e:
            if e[-1].reason == "API_DeviceTimedOut":
                self.__wait(server)
            else:
                raise

    def __setFileName(self, filename, number=True, scanID=None):
        """ sets the file names w/o scanID

        :param filename: sardana scanfile name
        :type filename: :obj:`str`
        :param numer: True if append scanID
        :param numer: :obj:`bool`
        :param scanID: scanID to append
        :type scanID: :obj:`int`
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
        if subs or number:
            if scanID is None:
                serial = self.recordlist.getEnvironValue('serialno')
            elif scanID >= 0:
                serial = scanID + 1
        if subs:
            try:
                #: output file name
                self.filename = filename % serial
            except Exception:
                subs = False

        if not subs:
            if number:
                tpl = filename.rpartition('.')
                self.filename = "%s_%05d.%s" % (tpl[0], serial, tpl[2])
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
        vl = self.__getEnvVar("NeXusSelectorDevice", None)
        if vl is None:
            servers = self.__db.get_device_exported_for_class(
                "NXSRecSelector").value_string
        else:
            servers = [str(vl)]
        if len(servers) > 0 and len(servers[0]) > 0 \
                and servers[0] != self.__moduleLabel:
            try:
                self.__nexussettings_device = PyTango.DeviceProxy(servers[0])
                self.__nexussettings_device.set_timeout_millis(self.__timeout)
                self.__nexussettings_device.ping()
                self.__nexussettings_device.set_source(PyTango.DevSource.DEV)
            except Exception:
                self.__nexussettings_device = None
                self.warning("Cannot connect to '%s' " % servers[0])
                if self.__macro:
                    self.__macro().warning(
                        "Cannot connect to '%s'" % servers[0])
        else:
            self.__nexussettings_device = None
        if self.__nexussettings_device is None:
            from nxsrecconfig import Settings
            self.__nexussettings_device = Settings.Settings()
            self.__nexussettings_device.importEnvProfile()
        if not hasattr(self.__nexussettings_device, "version") or \
           int(str(self.__nexussettings_device.version).split(".")[0]) < 2:
            raise Exception("NXSRecSelector (%s) version below 2.0.0" %
                            (servers[0] if servers else "module"))

        mntgrp = self.__getServerVar("mntGrp", None)
        amntgrp = self.__getEnvVar("ActiveMntGrp", None)
        if mntgrp and amntgrp != mntgrp:
            self.__nexussettings_device.mntgrp = amntgrp
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
                self.__command(self.__nexussettings_device, "fetchProfile")
                self.__asynchcommand(self.__nexussettings_device,
                                     "resetPreselectedComponents")
            self.__oddmntgrp = True
        else:
            self.__command(self.__nexussettings_device, "fetchProfile")

        self.__conf = self.__getServerVar("profileConfiguration", {}, True)
        if not self.__oddmntgrp and not onlyconfig:
            if "MntGrpConfiguration" in self.__conf.keys():
                poolmg = self.__command(
                    self.__nexussettings_device, "mntGrpConfiguration")
                profmg = self.__getConfVar("MntGrpConfiguration", None, False)
            else:
                poolmg = None
                profmg = None
            if not poolmg or not profmg or poolmg != profmg:
                self.debug(
                    "ActiveMntGrp created outside NXSRecSelector v3. "
                    "Updating ActiveMntGrp")
                if self.__macro:
                    self.__macro().debug(
                        "ActiveMntGrp created outside NXSRecSelector v3. "
                        "Updating ActiveMntGrp")
                self.__command(self.__nexussettings_device, "importMntGrp")
                self.__command(self.__nexussettings_device, "updateMntGrp")

        if not onlyconfig:
            vl = self.__getConfVar("WriterDevice", None)
            if not vl:
                servers = self.__db.get_device_exported_for_class(
                    "NXSDataWriter").value_string
            else:
                servers = [str(vl)]

            if len(servers) > 0 and len(servers[0]) > 0 \
                    and servers[0] != self.__moduleLabel:
                try:
                    self.__nexuswriter_device = PyTango.DeviceProxy(servers[0])
                    self.__nexuswriter_device.set_timeout_millis(
                        self.__timeout)
                    self.__nexuswriter_device.ping()
                    self.__nexuswriter_device.set_source(PyTango.DevSource.DEV)
                except Exception:
                    self.__nexuswriter_device = None
                    self.warning("Cannot connect to '%s' " % servers[0])
                    if self.__macro:
                        self.__macro().warning(
                            "Cannot connect to '%s'" % servers[0])
            else:
                self.__nexuswriter_device = None

            if self.__nexuswriter_device is None:
                from nxswriter import TangoDataWriter
                self.__nexuswriter_device = TangoDataWriter.TangoDataWriter()

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

    def __collectAliases(self, envRec):
        """ sets deviceAlaises and dynamicDataSources from env record

        :param envRec: environment record
        :type envRec: :obj:`dict` <:obj:`str` , `any`>
        """

        if 'counters' in envRec:
            for elm in envRec['counters']:
                alias = self.__get_alias(str(elm))
                if alias:
                    self.__deviceAliases[alias] = str(elm)
                else:
                    self.__dynamicDataSources[(str(elm))] = None
        if 'ref_moveables' in envRec:
            for elm in envRec['ref_moveables']:
                alias = self.__get_alias(str(elm))
                if alias:
                    self.__deviceAliases[alias] = str(elm)
                else:
                    self.__dynamicDataSources[(str(elm))] = None
        if 'column_desc' in envRec:
            for elm in envRec['column_desc']:
                if "name" in elm.keys():
                    alias = self.__get_alias(str(elm["name"]))
                    if alias:
                        self.__deviceAliases[alias] = str(elm["name"])
                    else:
                        self.__dynamicDataSources[(str(elm["name"]))] = None
        if 'datadesc' in envRec:
            for elm in envRec['datadesc']:
                alias = self.__get_alias(str(elm.name))
                if alias:
                    self.__deviceAliases[alias] = str(elm.name)
                else:
                    self.__dynamicDataSources[(str(elm.name))] = None

    def __createDynamicComponent(self, dss, keys, nexuscomponents):
        """ creates a dynamic component

        :param dss: datasource list
        :type dss: :obj:`list` <:obj:`str`>
        :param keys: keys without datasources
        :type keys: :obj:`list` <:obj:`str`>
        :param nexuscomponents: nexus component list
        :type nexuscomponents: :obj:`list` <:obj:`str`>
        """
        self.debug("DSS: %s" % dss)
        envRec = self.recordlist.getEnviron()
        lddict = []
        tdss = [ds for ds in dss if not ds.startswith("tango://")
                and ds not in nexuscomponents]
        for dd in envRec['datadesc']:
            alias = self.__get_alias(str(dd.name))
            if alias in tdss and alias not in nexuscomponents:
                mdd = {}
                mdd["name"] = dd.name
                mdd["shape"] = dd.shape
                mdd["dtype"] = dd.dtype
                lddict.append(mdd)
        jddict = json.dumps(lddict, cls=NXS_FileRecorder.numpyEncoder)
        jdss = json.dumps(tdss, cls=NXS_FileRecorder.numpyEncoder)
        jkeys = json.dumps(keys, cls=NXS_FileRecorder.numpyEncoder)
        self.debug("JDD: %s" % jddict)
        self.__dynamicCP = \
            self.__command(self.__nexussettings_device,
                           "createDynamicComponent",
                           [jdss, jddict, jkeys])

    def __removeDynamicComponent(self):
        """ removes the dynamic component
        """
        self.__command(self.__nexussettings_device,
                       "removeDynamicComponent",
                       str(self.__dynamicCP))

    def __availableComponents(self):
        """ provides a list of available components

        :returns: a list of available components
        :rtype: :obj:`list` <:obj:`str`>
        """
        cmps = self.__command(self.__nexussettings_device,
                              "availableComponents")
        if self.__availableComps:
            return list(set(cmps) & set(self.__availableComps))
        else:
            return cmps

    def __searchDataSources(self, nexuscomponents, cfm, dyncp, userkeys):
        """ checks if datasources and missing record keys are define in
            the components or in the configuration server

        :param nexuscomponents: nexus components
        :type nexuscomponents: :obj:`list` <:obj:`str`>
        :param cfm: componentsFromMntGrp flag
        :type cfm: :obj:`bool`
        :param dyncp: dynamicComponent flag
        :type dyncp: :obj:`bool`
        :param userkeys: user data names
        :type userkeys: :obj:`list` <:obj:`str`>

        :returns: tuple with (step_datasources, not_found_datasources,
                              required_components,  missing_user_data)
        :rtype: (`list` <:obj:`str`>, `list` <:obj:`str`>,
                 `list` <:obj:`str`>, `list` <:obj:`str`>)
        """
        dsFound = {}
        dsNotFound = []

        # (:obj:`list` <:obj:`str`>) all component source names
        allcpdss = []
        cpReq = {}
        keyFound = set()

        #: check datasources / get require components with give datasources
        if cfm:
            cmps = list(set(nexuscomponents) |
                        set(self.__availableComponents()))
        else:
            cmps = list(set(nexuscomponents) &
                        set(self.__availableComponents()))
        if self.__oddmntgrp:
            nds = []
        else:
            nds = self.__command(self.__nexussettings_device,
                                 "selectedDataSources")
        nds = nds if nds else []
        datasources = list(set(nds) | set(self.__deviceAliases.keys()))
        hascpsrcs = hasattr(self.__nexussettings_device, 'componentSources')
        for cp in cmps:
            try:
                if hascpsrcs:
                    cpdss = json.loads(
                        self.__command(self.__nexussettings_device,
                                       "componentSources",
                                       [cp]))
                    allcpdss.extend([ds["dsname"] for ds in cpdss])

                else:
                    cpdss = json.loads(
                        self.__command(self.__nexussettings_device,
                                       "componentClientSources",
                                       [cp]))
                dss = [ds["dsname"]
                       for ds in cpdss if ds["strategy"] == 'STEP'
                       and ds["dstype"] == 'CLIENT']
                reckeys = [
                    ds["record"] for ds in cpdss if ds["dstype"] == 'CLIENT']
                keyFound.update(set(reckeys))
            except Exception as e:
                if cp in nexuscomponents:
                    self.warning("Component '%s' wrongly defined in DB!" % cp)
                    self.warning("Error: '%s'" % str(e))
                    if self.__macro:
                        self.__macro().warning(
                            "Component '%s' wrongly defined in DB!" % cp)
                        # self.__macro().warning("Error: '%s'" % str(e))
                else:
                    self.debug("Component '%s' wrongly defined in DB!" % cp)
                    self.warning("Error: '%s'" % str(e))
                    if self.__macro:
                        self.__macro().debug(
                            "Component '%s' wrongly defined in DB!" % cp)
                    self.__macro.debug("Error: '%s'" % str(e))
                dss = []
            if dss:
                cdss = list(set(dss) & set(datasources))
                for ds in cdss:
                    self.debug("'%s' found in '%s'" % (ds, cp))
                    if ds not in dsFound.keys():
                        dsFound[ds] = []
                    dsFound[ds].append(cp)
                    if cp not in cpReq.keys():
                        cpReq[cp] = []
                    cpReq[cp].append(ds)
        missingKeys = set(userkeys) - keyFound

        datasources.extend(self.__dynamicDataSources.keys())
        #: get not found datasources
        for ds in datasources:
            if ds not in dsFound.keys() and ds not in allcpdss:
                dsNotFound.append(ds)
                if not dyncp:
                    self.warning(
                        "Warning: '%s' will not be stored. "
                        "It was not found in Components!"
                        " Consider setting: NeXusDynamicComponents=True" % ds)
                    if self.__macro:
                        self.__macro().warning(
                            "Warning: '%s' will not be stored. "
                            "It was not found in Components!"
                            " Consider setting: NeXusDynamicComponents=True"
                            % ds)
            elif not cfm and ds not in allcpdss:
                if not (set(dsFound[ds]) & set(nexuscomponents)):
                    dsNotFound.append(ds)
                    if not dyncp:
                        self.warning(
                            "Warning: '%s' will not be stored. "
                            "It was not found in User Components!"
                            " Consider setting: NeXusDynamicComponents=True"
                            % ds)
                        if self.__macro:
                            self.__macro().warning(
                                "Warning: '%s' will not be stored. "
                                "It was not found in User Components!"
                                " Consider setting: "
                                "NeXusDynamicComponents=True" % ds)
        return (nds, dsNotFound, cpReq, list(missingKeys))

    def __createConfiguration(self, userdata):
        """ create NeXus configuration

        :param userdata: user data dictionary
        :type userdata: :obj:`dict` <:obj:`str` , `any`>
        :returns: configuration xml string
        :rtype: :obj:`str`
        """
        cfm = self.__getConfVar("ComponentsFromMntGrp",
                                False, pass_default=self.__oddmntgrp)
        dyncp = self.__getConfVar("DynamicComponents",
                                  True, pass_default=self.__oddmntgrp)

        envRec = self.recordlist.getEnviron()
        self.__collectAliases(envRec)

        mandatory = self.__command(self.__nexussettings_device,
                                   "mandatoryComponents")
        self.info("Default Components %s" % str(mandatory))

        nexuscomponents = []
        lst = self.__getServerVar("components", None, False,
                                  pass_default=self.__oddmntgrp)
        if isinstance(lst, (tuple, list)):
            nexuscomponents.extend(lst)
        self.info("User Components %s" % str(nexuscomponents))

        self.__availableComps = []
        lst = self.__getConfVar("OptionalComponents",
                                None, True, pass_default=self.__oddmntgrp)
        if isinstance(lst, (tuple, list)):
            self.__availableComps.extend(lst)
        self.__availableComps = list(set(
            self.__availableComps))
        self.info("Available Components %s" % str(
            self.__availableComponents()))

        nds, dsNotFound, cpReq, missingKeys = self.__searchDataSources(
            list(set(nexuscomponents) | set(mandatory)),
            cfm, dyncp, userdata.keys())

        self.debug("DataSources Not Found : %s" % dsNotFound)
        self.debug("Components required : %s" % cpReq)
        self.debug("Missing User Data : %s" % missingKeys)
        if "InitDataSources" in self.__conf.keys():
            # compatibility with version 2
            ids = self.__getConfVar(
                "InitDataSources",
                None, True, pass_default=self.__oddmntgrp)
        else:
            idsdct = self.__getConfVar(
                "DataSourcePreselection",
                None, True, pass_default=self.__oddmntgrp)
            ids = [k for (k, vl) in idsdct.items() if vl] if idsdct else None
        if ids:
            missingKeys.extend(list(ids))
        self.__createDynamicComponent(
            dsNotFound if dyncp else [], missingKeys, nexuscomponents)
        nexuscomponents.append(str(self.__dynamicCP))

        if cfm:
            self.info("Sardana Components %s" % cpReq.keys())
            nexuscomponents.extend(cpReq.keys())
        nexuscomponents = list(set(nexuscomponents))

        nexusvariables = {}
        dct = self.__getConfVar("ConfigVariables", None, True)
        if isinstance(dct, dict):
            nexusvariables = dct
        oldtoswitch = None
        try:

            self.info("Components %s" % list(
                set(nexuscomponents) | set(mandatory)))
            toswitch = set()
            for dd in envRec['datadesc']:
                alias = self.__get_alias(str(dd.name))
                if alias:
                    toswitch.add(alias)
            toswitch.update(set(nds))
            och = self.__getConfVar("OrderedChannels",
                                    None, True, pass_default=self.__oddmntgrp)
            allcp = list(nexuscomponents)
            allcp.extend(list(toswitch))
            och = och or []
            self.__aliases = [ch for ch in och if ch in allcp]
            if self.__aliases:
                self.__vars["vars"]["mgchannels"] = " ".join(self.__aliases)
            self.__nexussettings_device.configVariables = json.dumps(
                dict(nexusvariables, **self.__vars["vars"]),
                cls=NXS_FileRecorder.numpyEncoder)
            if self.__macro:
                self.__macro().debug(
                    "VAR %s" % self.__nexussettings_device.configVariables)
            self.__command(self.__nexussettings_device,
                           "updateConfigVariables")

            self.debug("Aliases: %s" % str(self.__aliases))
            self.debug("Switching to STEP mode: %s" % toswitch)
            oldtoswitch = self.__getServerVar("stepdatasources", "[]", False)
            stepdss = str(json.dumps(list(toswitch)))
            self.__nexussettings_device.stepdatasources = stepdss
            if hasattr(self.__nexussettings_device, "linkdatasources"):
                self.__nexussettings_device.linkdatasources = stepdss
            cnfxml = self.__command(
                self.__nexussettings_device, "createWriterConfiguration",
                nexuscomponents)
        finally:
            self.__nexussettings_device.configVariables = json.dumps(
                nexusvariables)
            if oldtoswitch is not None:
                self.__nexussettings_device.stepdatasources = oldtoswitch

        return cnfxml

    def _startRecordList(self, recordlist):
        """ starts record process: creates configuration
            and records in INIT mode

        :param recordlist: sardana record list
        :type recordlist: :class:`sardana.macroserver.scan.scandata.RecordList`
        """
        try:
            self.__env = self.__macro().getAllEnv() if self.__macro else {}
            if self.__base_filename is None:
                return

            self.__setNexusDevices()

            appendentry = self.__getConfVar("AppendEntry", True)

            appendentry = not self.__setFileName(
                self.__base_filename, not appendentry)
            envRec = self.recordlist.getEnviron()
            self.__vars["vars"]["serialno"] = envRec["serialno"] \
                if appendentry else ""
            self.__vars["vars"]["scan_id"] = envRec["serialno"]
            self.__vars["vars"]["scan_title"] = envRec["title"]

            tzone = self.__getConfVar("TimeZone", self.__timezone)
            self.__vars["data"]["start_time"] = \
                self.__timeToString(envRec['starttime'], tzone)
            self.__vars["vars"]["filename"] = str(self.filename)

            envrecord = self.__appendRecord(self.__vars, 'INIT')
            rec = json.dumps(
                envrecord, cls=NXS_FileRecorder.numpyEncoder)
            cnfxml = self.__createConfiguration(envrecord["data"])
            self.debug('XML: %s' % str(cnfxml))
            self.__removeDynamicComponent()

            self.__vars["data"]["serialno"] = envRec["serialno"]
            self.__vars["data"]["scan_title"] = envRec["title"]

            if hasattr(self.__nexuswriter_device, 'Init'):
                self.__command(self.__nexuswriter_device, "Init")
            self.__nexuswriter_device.fileName = str(self.filename)
            self.__command(self.__nexuswriter_device, "openFile")
            self.__nexuswriter_device.xmlsettings = cnfxml

            self.debug('START_DATA: %s' % str(envRec))

            self.__nexuswriter_device.jsonrecord = rec
            self.__command(self.__nexuswriter_device, "openEntry")
        except Exception:
            self.__removeDynamicComponent()
            raise

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
            self.__env = self.__macro().getAllEnv() if self.__macro else {}
            envrecord = self.__appendRecord(self.__vars, 'STEP')
            rec = json.dumps(
                envrecord, cls=NXS_FileRecorder.numpyEncoder)
            self.__nexuswriter_device.jsonrecord = rec

            self.debug('DATA: {"data":%s}' % json.dumps(
                record.data,
                cls=NXS_FileRecorder.numpyEncoder))

            jsonString = '{"data":%s}' % json.dumps(
                record.data,
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
        try:
            tz = pytz.timezone(tzone)
        except Exception:
            self.warning(
                "Wrong TimeZone. "
                "The time zone set to `%s`" % self.__timezone)
            if self.__macro:
                self.__macro().warning(
                    "Wrong TimeZone. "
                    "The time zone set to `%s`" % self.__timezone)
            tz = pytz.timezone(self.__timezone)

        fmt = '%Y-%m-%dT%H:%M:%S.%f%z'
        starttime = tz.localize(mtime)
        return str(starttime.strftime(fmt))

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

            self.debug('END_DATA: %s ' % str(envRec))

            tzone = self.__getConfVar("TimeZone", self.__timezone)
            self.__vars["data"]["end_time"] = \
                self.__timeToString(envRec['endtime'], tzone)

            envrecord = self.__appendRecord(self.__vars, 'FINAL')

            rec = json.dumps(
                envrecord, cls=NXS_FileRecorder.numpyEncoder)
            self.__nexuswriter_device.jsonrecord = rec
            self.__command(self.__nexuswriter_device, "closeEntry")
            self.__command(self.__nexuswriter_device, "closeFile")
        except Exception:
            self.__command(self.__nexuswriter_device, "closeFile")
        finally:
            self.__removeDynamicComponent()

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
