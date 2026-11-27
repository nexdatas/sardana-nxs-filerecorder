#!/usr/bin/env python
#   This file is part of nexdatas - Tango Server for NeXus data writer
#
#    Copyright (C) 2026 DESY, Jan Kotanski <jkotan@mail.desy.de>
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
# \file createconfiguration_test.py
# tests of the writer configuration created by NXS_FileRecorder
#
import json
import os
import shutil
import tempfile
import unittest

try:
    from sardananxsrecorder import nxsrecorder
    from h5mapbuilder_test import FakeMacro, FakeRecordList, FakeSelector
    RECORDER = True
except Exception:
    RECORDER = False

try:
    from nxsrecconfig.WriterConfiguration import WriterConfiguration
    WCONF = bool(WriterConfiguration)
except Exception:
    WCONF = False


class Desc(object):
    """ sardana channel description stand-in """

    def __init__(self, name, shape=(), dtype="float64", stream=None):
        self.name = name
        self.label = name
        self.shape = list(shape)
        self.dtype = dtype
        # Sardana before the blissdata publisher has no external_stream
        if stream is not None:
            self.external_stream = stream


class Writer(object):
    """ NXSDataWriter stand-in collecting records """

    def __init__(self):
        self.jsonrecord = "{}"
        self.records = []

    def record(self, jsonstring):
        self.records.append(json.loads(jsonstring))


class Rec(object):
    """ sardana record stand-in """

    def __init__(self, data):
        self.data = data


class Pool(object):
    """ pool stand-in with motors """

    MotorList = [json.dumps({"name": "mot01"}),
                 json.dumps({"name": "mot02"})]


def source(name, strategy="STEP", dstype="CLIENT", record=None):
    return {"dsname": name, "strategy": strategy, "dstype": dstype,
            "record": record or name, "parentobj": "field"}


SOURCES = {
    "det": [source("exp_c01"), source("det_init", "INIT")],
    "slit": [source("slit_gap", "INIT", "TANGO")],
    "default": [source("start_time", "INIT")],
    "opt1": [source("exp_c02")],
    "__configuration_mg1": [source("exp_c01"), source("mot01"),
                            source("mot03")],
}


class ConfSelector(FakeSelector if RECORDER else object):
    """ in-process NXSRecSelector stand-in with a profile
    """

    components = ["slit", "det", "broken"]

    def __init__(self, dyncp=True, cache="", optional=None):
        FakeSelector.__init__(self)
        self.calls = []
        self.configVariables = json.dumps({"keep": "me"})
        self.stepdatasources = '["old"]'
        self.linkdatasources = '[]'
        self.cachecomponent = cache
        self.profileConfiguration = json.dumps({
            "AppendEntry": True, "MntGrpConfiguration": "{}",
            "ComponentsFromMntGrp": False, "DynamicComponents": dyncp,
            "OptionalComponents": json.dumps(optional or []),
            "DataSourcePreselection": json.dumps(
                {"ds_init": True, "ds_off": False}),
            "ConfigVariables": json.dumps({"entryname": "scan"}),
            "OrderedChannels": json.dumps(
                ["exp_c02", "exp_c01", "mot01", "det"])})

    def fetchProfile(self):
        FakeSelector.fetchProfile(self)

    def availableComponents(self):
        return list(SOURCES.keys()) + ["broken"]

    def selectedDataSources(self):
        return ["exp_c01", "ds_sel"]

    def mandatoryComponents(self):
        return ["default"]

    def componentSources(self, cps):
        if cps[0] == "broken":
            raise Exception("broken component")
        return json.dumps(SOURCES.get(cps[0], []))

    def availableTimers(self):
        return ["exp_t01"]

    def createDynamicComponent(self, params):
        self.calls.append(("createDynamicComponent", params))
        return "__dynamic_component__7"

    def removeDynamicComponent(self, name):
        self.calls.append(("removeDynamicComponent", name))

    def updateConfigVariables(self):
        self.calls.append("updateConfigVariables")

    def createWriterConfiguration(self, cps):
        self.calls.append((
            "createWriterConfiguration", sorted(cps),
            json.loads(self.configVariables),
            sorted(json.loads(self.stepdatasources)),
            sorted(json.loads(self.linkdatasources))))
        return "<definition/>"


@unittest.skipUnless(RECORDER and WCONF,
                     "sardananxsrecorder or nxsrecconfig >= 4.15.0 "
                     "is not available")
class CreateConfigurationTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        import nxsrecconfig.Settings as settings
        self._orig_settings = settings.Settings

    def tearDown(self):
        import nxsrecconfig.Settings as settings
        settings.Settings = self._orig_settings
        shutil.rmtree(self.tmpdir)

    def create(self, selector, userdata, datadesc=None):
        import nxsrecconfig.Settings as settings
        settings.Settings = lambda: selector
        env = {"ScanDir": self.tmpdir, "ScanFile": ["t.nxs"], "ScanID": 12,
               "NeXusSelectorDevice": "module", "ActiveMntGrp": "mg1",
               "NeXusConfiguration": {}}
        self.macro = FakeMacro(env)
        self.macro.getPools = lambda: [Pool()]
        rec = nxsrecorder.NXS_FileRecorder(
            os.path.join(self.tmpdir, "t.nxs"), macro=self.macro)
        rec.recordlist = FakeRecordList({
            "serialno": 12, "title": "ascan",
            "datadesc": datadesc or [
                Desc("exp_c01"), Desc("exp_c02", (2,)),
                Desc("mot01"), Desc("dyn_ch")],
            "ref_moveables": ["mot01"], "counters": ["exp_c01", "exp_c02"],
            "column_desc": [{"name": "col1"}, {"label": "x"}]})
        rec._NXS_FileRecorder__conf.update(
            json.loads(selector.profileConfiguration))
        xml = rec._NXS_FileRecorder__createConfiguration(userdata)
        return rec, xml

    def test_create(self):
        selector = ConfSelector()
        userdata = {"sample name": "water", "start_time": "t0",
                    "temp@units": "K", "temp": 3.5}
        rec, xml = self.create(selector, userdata)
        self.assertEqual(xml, "<definition/>")

        dcp = [c[1] for c in selector.calls
               if c[0] == "createDynamicComponent"][0]
        # exp_c01 is found in the det component
        self.assertEqual(
            sorted(json.loads(dcp[0])),
            ["col1", "ds_sel", "dyn_ch", "exp_c02", "mot01"])
        fields = {f["name"]: f for f in json.loads(dcp[1])}
        self.assertEqual(fields["exp_c02"]["shape"], [2])
        self.assertEqual(fields["exp_c02"]["strategy"], "STEP")
        self.assertEqual(fields["temp"]["units"], "K")
        self.assertEqual(fields["temp"]["strategy"], "INIT")
        self.assertEqual(fields["sample_name"]["dtype"], "str")
        self.assertEqual(json.loads(dcp[2]), ["ds_init"])
        # missing user data with sanitized names
        self.assertEqual(userdata["sample_name"], "water")

        wconf = [c for c in selector.calls
                 if c[0] == "createWriterConfiguration"][0]
        self.assertEqual(wconf[1], sorted(
            ["slit", "det", "broken", "__dynamic_component__7"]))
        cvars = wconf[2]
        self.assertEqual(cvars["entryname"], "scan")
        self.assertEqual(cvars["mgchannels"].split(),
                         ["exp_c02", "exp_c01", "mot01", "det"])
        self.assertEqual(cvars["timers"], "exp_t01")
        self.assertEqual(cvars["nexus_step_datasources"].split()[0],
                         "mot01")
        self.assertEqual(wconf[3], sorted(
            ["ds_sel", "dyn_ch", "exp_c01", "exp_c02", "mot01"]))
        self.assertEqual(wconf[4], wconf[3])
        # the selector settings are restored
        self.assertEqual(json.loads(selector.configVariables),
                         {"entryname": "scan"})
        self.assertEqual(selector.stepdatasources, '["old"]')
        # recorder variables are extended
        rvars = rec._NXS_FileRecorder__vars["vars"]
        self.assertEqual(rvars["nexus_components"], cvars["nexus_components"])
        # start_time is a record of the default component
        self.assertEqual(sorted(rvars["nexus_init_datasources"].split()),
                         ["ds_init", "name", "sample",
                          "temp", "temp@units"])
        self.assertTrue("start_time" not in fields)
        # the dynamic component of the scan is removed
        rec._NXS_FileRecorder__removeDynamicComponent()
        self.assertEqual(selector.calls[-1],
                         ("removeDynamicComponent", "__dynamic_component__7"))
        # a broken user component is reported in the macro
        warnings = [m[1][0] for m in self.macro.messages
                    if m[0] == "warning"]
        self.assertTrue(
            "Component 'broken' wrongly defined in DB!" in warnings)

    def test_streamed_channels(self):
        selector = ConfSelector()
        datadesc = [Desc("exp_c01", stream=False), Desc("mot01"),
                    Desc("lima", (10, 20), "uint16", stream=True)]
        rec, xml = self.create(selector, {}, datadesc)
        dcp = [c[1] for c in selector.calls
               if c[0] == "createDynamicComponent"][0]
        fields = {f["name"]: f for f in json.loads(dcp[1])}
        # stream references are stored as strings
        self.assertEqual(fields["lima"]["dtype"], "string")
        self.assertEqual(fields["lima"]["shape"], [])
        self.assertEqual(fields["mot01"]["dtype"], "float64")
        # the scan environment is not changed
        self.assertEqual(rec.recordlist.getEnviron()["datadesc"][2].shape,
                         [10, 20])

        self.assertEqual(rec.streamedChannels({"datadesc": datadesc}),
                         {"lima"})
        rec._NXS_FileRecorder__streamed = {"lima"}
        writer = Writer()
        rec._NXS_FileRecorder__nexuswriter_device = writer
        rec._writeRecord(Rec({"lima": "esrf:stream:lima:3", "mot01": 1.0}))
        rec._writeRecord(Rec({"lima": float("nan"), "mot01": 2.0}))
        self.assertEqual(writer.records[0]["data"],
                         {"lima": "esrf:stream:lima:3", "mot01": 1.0})
        # placeholders of streamed channels are skipped
        self.assertEqual(writer.records[1]["data"], {"mot01": 2.0})

    def test_older_sardana(self):
        datadesc = [Desc("exp_c01"), Desc("lima", (10, 20), "uint16")]
        env = {"datadesc": datadesc}
        self.assertEqual(
            nxsrecorder.NXS_FileRecorder.streamedChannels(env), set())
        self.assertTrue(
            nxsrecorder.NXS_FileRecorder.streamedEnviron(env) is env)
        selector = ConfSelector()
        rec, xml = self.create(selector, {}, datadesc)
        dcp = [c[1] for c in selector.calls
               if c[0] == "createDynamicComponent"][0]
        fields = {f["name"]: f for f in json.loads(dcp[1])}
        self.assertEqual(fields["lima"]["dtype"], "uint16")
        self.assertEqual(fields["lima"]["shape"], [10, 20])
        writer = Writer()
        rec._NXS_FileRecorder__nexuswriter_device = writer
        rec._writeRecord(Rec({"lima": [[1, 2]], "exp_c01": 1.0}))
        self.assertEqual(writer.records[0]["data"],
                         {"lima": [[1, 2]], "exp_c01": 1.0})

    def test_cache_component(self):
        selector = ConfSelector(cache="__configuration_mg1")
        rec, xml = self.create(selector, {})
        dcp = [c[1] for c in selector.calls
               if c[0] == "createDynamicComponent"][0]
        # motors of cache components from the macro server pools
        self.assertEqual(sorted(json.loads(dcp[2])), ["ds_init", "mot01"])
        self.assertEqual(sorted(json.loads(dcp[0])),
                         ["col1", "ds_sel", "dyn_ch", "exp_c02"])
        wconf = [c for c in selector.calls
                 if c[0] == "createWriterConfiguration"][0]
        self.assertEqual(wconf[1], ["__configuration_mg1",
                                    "__dynamic_component__7"])

    def test_no_dynamic_components(self):
        selector = ConfSelector(dyncp=False)
        rec, xml = self.create(selector, {})
        dcp = [c[1] for c in selector.calls
               if c[0] == "createDynamicComponent"][0]
        self.assertEqual(json.loads(dcp[0]), [])
        warnings = [m[1][0] for m in self.macro.messages
                    if m[0] == "warning"]
        self.assertTrue(any("'dyn_ch' will not be stored" in w
                            for w in warnings))


if __name__ == '__main__':
    unittest.main()
