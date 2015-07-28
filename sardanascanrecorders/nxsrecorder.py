#!/usr/bin/env python
#   This file is part of nexdatas - Tango Server for NeXus data writer
#
#    Copyright (C) 2012-2015 DESY, Jan Kotanski <jkotan@mail.desy.de>
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
## \package sardanascanrecorders nexdatas
## \file nxsrecorder.py
# package constructor

"""This is the macro server scan data NeXus recorder module"""

__docformat__ = 'restructuredtext'

import os
import re

import numpy
import json
import pytz 

import PyTango

from sardana.macroserver.scan.recorder.storage import BaseFileRecorder



class NXS_FileRecorder(BaseFileRecorder):
    """ This recorder saves data to a NeXus file making use of NexDaTaS Writer

        Copyright (C) 2012-2015 DESY, Jan Kotanski <jkotan@mail.desy.de>

        you can redistribute it and/or modify it under the terms 
        of the GNU Lesser General Public License as published by
        the Free Software Foundation, either version 3 of the License, or
        (at your option) any later version.
    """ 

    formats = {"DataFormats.nxs": '.nxs'}

    class numpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, numpy.ndarray) and obj.ndim > 0:
                return obj.tolist()
            return json.JSONEncoder.default(self, obj)

    def __init__(self, filename=None, macro=None, **pars):
        print "INIT NXSREC", self, pars
#        super(NXS_FileRecorder, self).__init__(*pars)
        BaseFileRecorder.__init__(self)
        ## base filename
        self.__base_filename = filename
        if macro:
            self.macro = macro
        ## tango database
        self.__db = PyTango.Database()

        ## NXS data writer device
        self.__nexuswriter_device = None

        ## NXS settings server device
        self.__nexussettings_device = None

        ## device proxy timeout
        self.__timeout = 100000
        ## Custom variables
        self.__vars = {"data": {},
                       "datasources": {},
                       "decoders": {},
                       "vars": {},
                       "triggers": []}

        ## device aliases
        self.__deviceAliases = {}
        ## dynamic datasources
        self.__dynamicDataSources = {}

        ## dynamic components
        self.__dynamicCP = "__dynamic_component__"

        ## environment
        self.__env = self.macro.getAllEnv() if self.macro else {}

        ## available components
        self.__availableComps = []

        ## default timezone
        self.__timezone = "Europe/Berlin"

        ## default NeXus configuration env variable
        self.__defaultenv = "NeXusConfiguration"

        ## module lable
        self.__moduleLabel = 'module'

        ## NeXus configuration
        self.__conf = {}

        self.__oddmntgrp = False

        self.__clientSources = []

        self.__setNexusDevices(onlyconfig=True)

        appendentry = self.__getConfVar("AppendEntry", True)
        scanID = self.__env["ScanID"] \
            if "ScanID" in self.__env.keys() else -1
        appendentry = not self.__setFileName(
            self.__base_filename, not appendentry, scanID)

    def __command(self, server, command, *args):
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
            self.macro.warning(
                "%s.%s cannot be found" % (server, command))

    def __getConfVar(self, var, default, decode=False, pass_default=False):
        if pass_default:
            return default
        if var in self.__conf.keys():
            res = self.__conf[var]
            if decode:
                try:
                    dec = json.loads(res)
                    return dec
                except:
                    self.warning("%s = '%s' cannot be decoded" % (var, res))
                    self.macro.warning(
                        "%s = '%s' cannot be decoded" % (var, res))
                    return default
            else:
                return res
        else:
            self.warning("%s cannot be found" % (var))
            self.macro.warning(
                "%s cannot be found" % (var))
            return default

    def __getServerVar(self, attr, default, decode=False, pass_default=False):
        if pass_default:
            return default
        if self.__nexussettings_device and attr:
            res = getattr(self.__nexussettings_device, attr)
            if decode:
                try:
                    dec = json.loads(res)
                    return dec
                except:
                    self.warning("%s = '%s' cannot be decoded" % (attr, res))
                    self.macro.warning(
                        "%s = '%s' cannot be decoded" % (attr, res))
                    return default
            else:
                return res
        else:
            self.warning("%s cannot be found" % (attr))
            self.macro.warning(
                "%s  cannot be found" % (attr))
            return default

    def __getEnvVar(self, var, default, pass_default=False):
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

    def __setFileName(self, filename, number=True, scanID=None):
        if scanID is not None and scanID < 0:
            return number
        if self.fd is not None:
            self.fd.close()

        dirname = os.path.dirname(filename)
        if not dirname:
            self.warning(
                "Missing file directory. "
                "File will be saved in the local writer directory.")
            self.macro.warning(
                "Missing file directory. "
                "File will be saved in the local writer directory.")
            dirname = '/'

        if not os.path.isdir(dirname):
            try:
                os.makedirs(dirname)
                os.chmod(dirname, 0o777)
            except Exception as e:
                self.macro.warning(str(e))
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
                self.filename = filename % serial
            except:
                subs = False

        if not subs:
            if number:
                tpl = filename.rpartition('.')
                self.filename = "%s_%05d.%s" % (tpl[0], serial, tpl[2])
            else:
                self.filename = filename

        return number or subs

    def getFormat(self):
        return 'nxs'

    def __setNexusDevices(self, onlyconfig=False):
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
            except Exception:
                self.__nexussettings_device = None
                self.warning("Cannot connect to '%s' " % servers[0])
                self.macro.warning("Cannot connect to '%s'" % servers[0])
        else:
            self.__nexussettings_device = None
        if self.__nexussettings_device is None:
            from nxsrecconfig import Settings
            self.__nexussettings_device = Settings.Settings()
            self.__nexussettings_device.importAllEnv()

        mntgrp = self.__getServerVar("mntGrp", None)
        amntgrp = self.__getEnvVar("ActiveMntGrp", None)
        if mntgrp and amntgrp != mntgrp:
            self.__nexussettings_device.mntgrp = amntgrp
        if amntgrp not in self.__command(
            self.__nexussettings_device, "availableSelections"):
            self.warning(
                ("Active Measurement Group '%s'" % amntgrp)
                + (" differs from NeXusMntGrp '%s'." % mntgrp))
            self.warning(
                "Some metadata may not be stored into the NeXus file.")
            self.warning(
                "To fix it please apply your settings by Component Selector."
                )
            self.macro.warning(
                ("Active Measurement Group '%s'" % amntgrp)
                + (" differs from NeXusMntGrp '%s'." % mntgrp))
            self.macro.warning(
                "Some metadata may not be stored into the NeXus file.")
            self.macro.warning(
                "To fix it please apply your settings by Component Selector."
                )
            self.__oddmntgrp = True
        else:
            self.__command(self.__nexussettings_device, "fetchConfiguration")

        self.__conf = self.__getServerVar("configuration", {}, True)
        if not self.__oddmntgrp and not onlyconfig:
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
                except Exception:
                    self.__nexuswriter_device = None
                    self.warning("Cannot connect to '%s' " % servers[0])
                    self.macro.warning("Cannot connect to '%s'" % servers[0])
            else:
                self.__nexuswriter_device = None

            if self.__nexuswriter_device is None:
                from nxswriter import TangoDataWriter
                self.__nexuswriter_device = TangoDataWriter.TangoDataWriter()

    ## provides a device alias
    # \param name device name
    # \return device alias
    def __get_alias(self, name):
        # if name does not contain a "/" it's probably an alias
        if name.find("/") == -1:
            return name

        # haso107klx:10000/expchan/hasysis3820ctrl/1
        if name.find(':') >= 0:
            lst = name.split("/")
            name = "/".join(lst[1:])
        try:
            alias = self.__db.get_alias(name)
        except:
            alias = None
        return alias

    def __collectAliases(self, envRec):

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

    def __createDynamicComponent(self, dss, keys):
        self.debug("DSS: %s" % dss)
        envRec = self.recordlist.getEnviron()
        lddict = []
        tdss = [ds for ds in dss if not ds.startswith("tango://")]
        for dd in envRec['datadesc']:
            alias = self.__get_alias(str(dd.name))
            if alias in tdss:
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
        self.__command(self.__nexussettings_device,
                       "removeDynamicComponent",
                       str(self.__dynamicCP))

    def __availableComponents(self):
        cmps = self.__command(self.__nexussettings_device,
                              "availableComponents")
        if self.__availableComps:
            return list(set(cmps) & set(self.__availableComps))
        else:
            return cmps

    def __searchDataSources(self, nexuscomponents, cfm, dyncp, userkeys):
        dsFound = {}
        dsNotFound = []
        cpReq = {}
        keyFound = set()

        ## check datasources / get require components with give datasources
        if cfm:
            cmps = list(set(nexuscomponents) |
                        set(self.__availableComponents()))
        else:
            cmps = list(set(nexuscomponents) &
                        set(self.__availableComponents()))
        self.__clientSources = []
        nds = self.__getServerVar("dataSources", [], False,
                            pass_default=self.__oddmntgrp)
        nds = nds if nds else []
        datasources = list(set(nds) | set(self.__deviceAliases.keys()))
        for cp in cmps:
            try:
                cpdss = json.loads(
                    self.__command(self.__nexussettings_device,
                                   "clientSources",
                                   [cp]))
                self.__clientSources.extend(cpdss)
                dss = [ds["dsname"]
                       for ds in cpdss if ds["strategy"] == 'STEP']
                keyFound.update(set([ds["record"] for ds in cpdss]))
            except Exception as e:
                if cp in nexuscomponents:
                    self.warning("Component '%s' wrongly defined in DB!" % cp)
                    self.warning("Error: '%s'" % str(e))
                    self.macro.warning(
                        "Component '%s' wrongly defined in DB!" % cp)
                #                self.macro.warning("Error: '%s'" % str(e))
                else:
                    self.debug("Component '%s' wrongly defined in DB!" % cp)
                    self.warning("Error: '%s'" % str(e))
                    self.macro.debug(
                        "Component '%s' wrongly defined in DB!" % cp)
                    self.macro.debug("Error: '%s'" % str(e))
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
        ## get not found datasources
        for ds in datasources:
            if ds not in dsFound.keys():
                dsNotFound.append(ds)
                if not dyncp:
                    self.warning(
                        "Warning: '%s' will not be stored. " % ds
                        + "It was not found in Components!"
                        + " Consider setting: NeXusDynamicComponents=True")
                    self.macro.warning(
                        "Warning: '%s' will not be stored. " % ds
                        + "It was not found in Components!"
                        + " Consider setting: NeXusDynamicComponents=True")
            elif not cfm:
                if not (set(dsFound[ds]) & set(nexuscomponents)):
                    dsNotFound.append(ds)
                    if not dyncp:
                        self.warning(
                            "Warning: '%s' will not be stored. " % ds
                            + "It was not found in User Components!"
                            + " Consider setting: NeXusDynamicComponents=True")
                        self.macro.warning(
                            "Warning: '%s' will not be stored. " % ds
                            + "It was not found in User Components!"
                            + " Consider setting: NeXusDynamicComponents=True")
        return (nds, dsNotFound, cpReq, list(missingKeys))

    def __createConfiguration(self, userdata):
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

        ## add updateControllers
        lst = self.__getServerVar("automaticComponents",
                                  None, False, pass_default=self.__oddmntgrp)
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
        ids = self.__getConfVar("InitDataSources",
                            None, True, pass_default=self.__oddmntgrp)
        if ids:
            missingKeys.extend(list(ids))
        self.__createDynamicComponent(dsNotFound if dyncp else [], missingKeys)
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
            self.__nexussettings_device.configVariables = json.dumps(
                dict(self.__vars["vars"], **nexusvariables),
                cls=NXS_FileRecorder.numpyEncoder)
            self.__command(self.__nexussettings_device,
                           "updateConfigVariables")

            self.info("Components %s" % list(
                    set(nexuscomponents) | set(mandatory)))
            toswitch = set()
            for dd in envRec['datadesc']:
                alias = self.__get_alias(str(dd.name))
                if alias:
                    toswitch.add(alias)
            toswitch.update(set(nds))
            self.debug("Switching to STEP mode: %s" % toswitch)
            oldtoswitch = self.__getServerVar("stepdatasources", [], False)
            self.__nexussettings_device.stepdatasources = list(toswitch)
            cnfxml = self.__command(
                        self.__nexussettings_device, "createConfiguration",
                        nexuscomponents)
        finally:
            self.__nexussettings_device.configVariables = json.dumps(
                nexusvariables)
            if oldtoswitch is not None:
                self.__nexussettings_device.stepdatasources = oldtoswitch

        return cnfxml

    def _startRecordList(self, recordlist):
        try:
            self.__env = self.macro.getAllEnv() if self.macro else {}
            if self.__base_filename is None:
                return

            self.__setNexusDevices()

            appendentry = self.__getConfVar("AppendEntry",
                                        True)

            appendentry = not self.__setFileName(
                self.__base_filename, not appendentry)
            envRec = self.recordlist.getEnviron()
            if appendentry:
                self.__vars["vars"]["serialno"] = envRec["serialno"]
            self.__vars["vars"]["scan_title"] = envRec["title"]

            tzone = self.__getConfVar("TimeZone", self.__timezone)
            self.__vars["data"]["start_time"] = \
                self.__timeToString(envRec['starttime'], tzone)

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
        except:
            self.__removeDynamicComponent()
            raise

    def __appendRecord(self, var, mode=None):
        nexusrecord = {}
        dct = self.__getConfVar("DataRecord", None, True)
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
        try:
            if self.filename is None:
                return
            self.__env = self.macro.getAllEnv() if self.macro else {}
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
            self.debug("JSON!!: %s" % jsonString)
            self.__command(self.__nexuswriter_device, "record",
                        jsonString)
        except:
            self.__removeDynamicComponent()
            raise

    def __timeToString(self, mtime, tzone):
        try:
            tz = pytz.timezone(tzone)
        except:
            self.warning(
                "Wrong TimeZone. "
                + "The time zone set to `%s`" % self.__timezone)
            self.macro.warning(
                "Wrong TimeZone. "
                + "The time zone set to `%s`" % self.__timezone)
            tz = pytz.timezone(self.__timezone)

        fmt = '%Y-%m-%dT%H:%M:%S.%f%z'
        starttime = tz.localize(mtime)
        return str(starttime.strftime(fmt))

    def _endRecordList(self, recordlist):
        try:
            if self.filename is None:
                return

            self.__env = self.macro.getAllEnv() if self.macro else {}
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

        finally:
            self.__removeDynamicComponent()

    def _addCustomData(self, value, name, group="data", remove=False,
                       **kwargs):
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


