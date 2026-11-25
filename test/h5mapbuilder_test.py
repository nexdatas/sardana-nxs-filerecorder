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
# \file h5mapbuilder_test.py
# unittests for the NXS h5map builder
#
import datetime
import json
import os
import shutil
import tempfile
import unittest

try:
    from sardananxsrecorder import nxsrecorder
    from sardananxsrecorder.h5mapbuilder import (
        NXSH5MapBuilder, StreamResolver)
    RECORDER = True
except Exception:
    RECORDER = False

try:
    from blissdata.h5map import HDF5Item
except Exception:
    HDF5Item = None

try:
    from nxstools import h5mapwriter  # noqa: F401
    from nxswriter import TangoDataWriter
    H5MAP = "h5map" in TangoDataWriter.WRITERS
except Exception:
    H5MAP = False


XML = """<definition>
 <group type="NXentry" name="scan_00012">
  <group type="NXinstrument" name="instrument">
   <group type="NXdetector" name="det">
    <field units="m" type="NX_FLOAT32" name="counter">
     <strategy mode="STEP"/>
     <datasource type="CLIENT" name="exp_c01"><record name="exp_c01"/>
     </datasource>
    </field>
   </group>
  </group>
  <field type="NX_CHAR" name="start_time">
   <strategy mode="INIT"/>
   <datasource type="CLIENT" name="start_time">
    <record name="start_time"/></datasource>
  </field>
  <field type="NX_CHAR" name="end_time">
   <strategy mode="FINAL"/>
   <datasource type="CLIENT" name="end_time">
    <record name="end_time"/></datasource>
  </field>
  <field type="NX_CHAR" name="end_reason">
   <strategy mode="FINAL"/>
   <datasource type="CLIENT" name="end_reason">
    <record name="end_reason"/></datasource>
  </field>
 </group>
</definition>"""

DATADESC = {
    "exp_c01": {"label": "exp_c01",
                "name": "tango://haso:10000/expchan/ctctrl01/1"},
    "mot01": {"label": "mot01", "name": "motor/motctrl01/1"},
}


class FakeMacro(object):

    def __init__(self, env):
        self.env = env
        self.messages = []
        self._gScan = None

    def getAllEnv(self):
        return dict(self.env)

    def getEnv(self, name, default=None):
        if name in self.env:
            return self.env[name]
        if default is not None:
            return default
        raise Exception("Unknown env %s" % name)

    def warning(self, *args):
        self.messages.append(("warning", args))

    def info(self, *args):
        self.messages.append(("info", args))

    def debug(self, *args):
        pass

    def error(self, *args):
        self.messages.append(("error", args))


class FakeRecordList(object):

    def __init__(self, env):
        self.env = env

    def getEnviron(self):
        return self.env

    def getEnvironValue(self, name):
        return self.env[name]


class FakeSelector(object):
    """ in-process NXSRecSelector stand-in
    """
    version = "3.0.0"
    mntgrp = "mg1"
    mntGrp = "mg1"
    profileConfiguration = json.dumps({"AppendEntry": True,
                                       "MntGrpConfiguration": "{}"})
    cachecomponent = ""

    def __init__(self):
        self.commands = []

    def importEnvProfile(self):
        self.commands.append("importEnvProfile")

    def availableProfiles(self):
        return ["mg1"]

    def fetchProfile(self):
        self.commands.append("fetchProfile")

    def mntGrpConfiguration(self):
        return "{}"

    def removeDynamicComponent(self, name):
        self.commands.append("removeDynamicComponent")


class FakeGScan(object):

    def __init__(self, recordlist, recorders):
        self.data = recordlist

        class Handler(object):
            pass

        self._data_handler = Handler()
        self._data_handler.recorders = recorders


@unittest.skipUnless(RECORDER, "sardananxsrecorder is not available")
class StreamResolverTest(unittest.TestCase):

    def test_resolver(self):
        res = StreamResolver(DATADESC)
        self.assertEqual(res("/p", "exp_c01", "", "STEP"), "exp_c01")
        self.assertEqual(res("/p", "", "EXP_C01", "STEP"), "exp_c01")
        self.assertEqual(
            res("/p", "c1", "tango://haso:10000/expchan/ctctrl01/1",
                "STEP"), "exp_c01")
        self.assertEqual(
            res("/p", "c1", "haso:10000/expchan/ctctrl01/1", "STEP"),
            "exp_c01")
        self.assertEqual(
            res("/p", "c1", "expchan/ctctrl01/1", "STEP"), "exp_c01")
        self.assertEqual(
            res("/p", "", "motor/motctrl01/1", "STEP"), "mot01")
        self.assertEqual(res("/p", "other", "other", "STEP"), None)
        self.assertEqual(StreamResolver(None)("/p", "a", "b", "STEP"), None)


@unittest.skipUnless(RECORDER and H5MAP,
                     "sardananxsrecorder or the h5map writer not available")
class NXSH5MapBuilderTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.selector = FakeSelector()
        self._settings = nxsrecorder.__dict__.get("Settings")
        import nxsrecconfig.Settings as settings
        self._orig_settings = settings.Settings
        settings.Settings = lambda: self.selector
        self._orig_create = getattr(
            nxsrecorder.NXS_FileRecorder,
            "_NXS_FileRecorder__createConfiguration")
        nxsrecorder.NXS_FileRecorder.\
            _NXS_FileRecorder__createConfiguration = \
            lambda rec, userdata: XML
        self.env = {
            "ScanDir": self.tmpdir,
            "ScanFile": ["test.nxs", "test.dat"],
            "ScanID": 12,
            "NeXusSelectorDevice": "module",
            "ActiveMntGrp": "mg1",
            "NeXusConfiguration": {},
        }
        start = datetime.datetime(2026, 11, 25, 10, 0, 0)
        self.recordlist = FakeRecordList({
            "serialno": 12, "title": "ascan mot01 0 1 2 0.1",
            "starttime": start,
            "endtime": start + datetime.timedelta(seconds=5),
            "endstatus": None,
        })
        self.macro = FakeMacro(self.env)

    def tearDown(self):
        import nxsrecconfig.Settings as settings
        settings.Settings = self._orig_settings
        nxsrecorder.NXS_FileRecorder.\
            _NXS_FileRecorder__createConfiguration = self._orig_create
        shutil.rmtree(self.tmpdir)

    def recorder(self):
        return nxsrecorder.NXS_FileRecorder(
            os.path.join(self.tmpdir, "test.nxs"), macro=self.macro)

    def scan_info(self):
        return {"datadesc": DATADESC}

    def entry(self, h5maps):
        json.dumps(h5maps, allow_nan=False)
        if HDF5Item is not None:
            for h5map in h5maps.values():
                HDF5Item.validate_python(h5map)
        # AppendEntry: one file, the entry name with the scan number
        fname = os.path.join(self.tmpdir, "test.nxs")
        self.assertEqual(list(h5maps.keys()), [fname])
        # nexus_logs: the configuration log of NXSDataWriter
        self.assertEqual(
            sorted(h5maps[fname]["children"].keys()),
            ["nexus_logs", "scan_00012"])
        return h5maps[fname]["children"]["scan_00012"]["children"]

    def test_scan_recorders(self):
        rec = self.recorder()
        self.macro._gScan = FakeGScan(self.recordlist, [object(), rec])
        builder = NXSH5MapBuilder(self.macro)

        start = builder.start(self.scan_info(), [])
        self.assertTrue(rec.h5map_mode)
        self.assertEqual(builder.owned, [])
        entry = self.entry(start)
        self.assertEqual(
            sorted(entry.keys()), ["instrument", "start_time"])
        self.assertEqual(entry["start_time"]["value"],
                         "2026-11-25T10:00:00.000000+0100")
        counter = entry["instrument"]["children"]["det"]["children"][
            "counter"]
        self.assertEqual(counter["value"],
                         {"type": "stream", "stream": "exp_c01"})

        # the scan data handler: second start, records and the end
        rec.startRecordList(self.recordlist)

        class Record(object):
            data = {"exp_c01": 1.5}
        rec.writeRecord(Record())
        rec.endRecordList(self.recordlist)

        end = builder.end(self.scan_info())
        entry = self.entry(end)
        self.assertEqual(
            sorted(entry.keys()),
            ["end_reason", "end_time", "instrument", "start_time"])
        self.assertEqual(entry["end_time"]["value"],
                         "2026-11-25T10:00:05.000000+0100")
        self.assertEqual(
            entry["instrument"]["children"]["det"]["children"][
                "counter"]["value"],
            {"type": "stream", "stream": "exp_c01"})
        self.assertFalse(os.path.exists(
            os.path.join(self.tmpdir, "test.nxs")))

    def test_owned_recorders(self):
        self.macro._gScan = FakeGScan(self.recordlist, [])
        builder = NXSH5MapBuilder(self.macro)
        start = builder.start(self.scan_info(), [])
        self.assertEqual(len(builder.owned), 1)
        self.assertEqual(sorted(self.entry(start).keys()),
                         ["instrument", "start_time"])
        end = builder.end(self.scan_info())
        self.assertEqual(builder.owned, [])
        self.assertTrue("end_time" in self.entry(end))

    def test_rollback(self):
        rec = self.recorder()
        self.macro._gScan = FakeGScan(self.recordlist, [rec])
        builder = NXSH5MapBuilder(self.macro)

        def fail(*args):
            raise Exception("export failed")
        builder._h5maps = fail
        with self.assertRaises(Exception):
            builder.start(self.scan_info(), [])
        self.assertFalse(rec.h5map_mode)
        self.assertEqual(rec.h5maps(), {})
        self.assertEqual(builder.recorders, [])

    def test_no_nexus_file(self):
        self.env["ScanFile"] = ["test.dat"]
        self.macro._gScan = FakeGScan(self.recordlist, [])
        with self.assertRaises(Exception):
            NXSH5MapBuilder(self.macro).start(self.scan_info(), [])


if __name__ == '__main__':
    unittest.main()
