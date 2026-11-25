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
# \file nxsrecorderapi_test.py
# API tests of NXS_FileRecorder with an in-process writer
#
import datetime
import json
import os
import shutil
import tempfile
import unittest

import numpy

try:
    import h5py
except Exception:
    h5py = None

try:
    from sardananxsrecorder import nxsrecorder
    from h5mapbuilder_test import (
        FakeMacro, FakeRecordList, FakeSelector, DATADESC)
    RECORDER = True
except Exception:
    RECORDER = False

try:
    from nxswriter import TangoDataWriter
    NXSWRITER = True
    H5MAP = "h5map" in TangoDataWriter.WRITERS
except Exception:
    NXSWRITER = False
    H5MAP = False

try:
    from sardananxsrecorder.h5mapbuilder import StreamResolver
except Exception:
    StreamResolver = None


ENTRY = "scan_00012"

XML = """<definition>
 <group type="NXentry" name="%s">
  <group type="NXinstrument" name="instrument">
   <group type="NXdetector" name="det">
    <field units="m" type="NX_FLOAT64" name="counter">
     <strategy mode="STEP"/>
     <datasource type="CLIENT" name="exp_c01"><record name="exp_c01"/>
     </datasource>
    </field>
   </group>
  </group>
  <group type="NXsample" name="sample">
   <field type="NX_CHAR" name="name">
    <strategy mode="INIT" canfail="true"/>
    <datasource type="CLIENT" name="sample_name">
     <record name="sample_name"/></datasource>
   </field>
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
  <group type="NXdata" name="data">
   <link name="counter" target="/%s/instrument/det/counter"/>
  </group>
 </group>
</definition>""" % (ENTRY, ENTRY)


class Record(object):
    """ sardana record stand-in
    """

    def __init__(self, data):
        self.data = data


class Selector(FakeSelector if RECORDER else object):
    """ NXSRecSelector stand-in with a configurable profile
    """

    def __init__(self, appendentry=True):
        FakeSelector.__init__(self)
        self.profileConfiguration = json.dumps(
            {"AppendEntry": appendentry, "MntGrpConfiguration": "{}"})


@unittest.skipUnless(RECORDER, "sardananxsrecorder is not available")
class NXSRecorderClassAPITest(unittest.TestCase):

    def test_formats(self):
        rec = nxsrecorder.NXS_FileRecorder
        self.assertEqual(
            rec.formats,
            {"nxs": ".nxs", "nx": ".nx", "h5": ".h5", "ndf": ".ndf"})

    def test_end_reasons(self):
        self.assertEqual(
            nxsrecorder.END_REASON_BY_END_STATUS,
            {"Normal": "SUCCESS", "Stop": "USER_ABORT",
             "Abort": "USER_ABORT", "Exception": "FAILURE"})

    def test_numpy_encoder(self):
        enc = nxsrecorder.NXS_FileRecorder.numpyEncoder
        data = {
            "i": numpy.int32(3), "f": numpy.float32(1.5),
            "a": numpy.array([[1, 2], [3, 4]]), "b": numpy.bool_(True),
            "s": "text"}
        self.assertEqual(
            json.loads(json.dumps(data, cls=enc)),
            {"i": 3, "f": 1.5, "a": [[1, 2], [3, 4]], "b": True,
             "s": "text"})
        with self.assertRaises(TypeError):
            json.dumps({"o": object()}, cls=enc)


@unittest.skipUnless(RECORDER and NXSWRITER,
                     "sardananxsrecorder or nxswriter is not available")
class NXSRecorderAPITest(unittest.TestCase):
    """ API tests with an in-process selector and writer
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.selector = Selector()
        import nxsrecconfig.Settings as settings
        self._orig_settings = settings.Settings
        settings.Settings = lambda: self.selector
        self._orig_create = getattr(
            nxsrecorder.NXS_FileRecorder,
            "_NXS_FileRecorder__createConfiguration")
        self.userdata = []

        def create(rec, userdata):
            self.userdata.append(dict(userdata))
            return XML
        nxsrecorder.NXS_FileRecorder.\
            _NXS_FileRecorder__createConfiguration = create
        self.env = {
            "ScanDir": self.tmpdir,
            "ScanFile": ["test.nxs"],
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

    def recorder(self, fname="test.nxs"):
        return nxsrecorder.NXS_FileRecorder(
            os.path.join(self.tmpdir, fname), macro=self.macro)

    def scan(self, rec, values=(1.5, 2.5)):
        """ runs the record list as the scan data handler does
        """
        rec.startRecordList(self.recordlist)
        for value in values:
            rec.writeRecord(Record({"exp_c01": value}))
        rec.endRecordList(self.recordlist)

    # file names

    def test_filename_append_entry(self):
        rec = self.recorder()
        self.assertEqual(
            rec.getFileName(), os.path.join(self.tmpdir, "test.nxs"))
        self.assertEqual(rec.getFormat(), "nxs")

    def assertScanFile(self, rec, fname):
        """ checks the file name set from the scan serial number
        """
        self.scan(rec, values=())
        fname = os.path.join(self.tmpdir, fname)
        self.assertEqual(rec.getFileName(), fname)
        self.assertTrue(os.path.isfile(fname))

    def test_filename_new_file(self):
        self.selector = Selector(appendentry=False)
        self.assertScanFile(self.recorder(), "test_00012.nxs")

    def test_filename_percent_pattern(self):
        self.env["ScanFile"] = ["scan_%05d.nxs"]
        self.assertScanFile(self.recorder("scan_%05d.nxs"), "scan_00012.nxs")

    def test_filename_scanid_pattern(self):
        self.env["ScanFile"] = ["scan_{ScanID}.nxs"]
        self.assertScanFile(self.recorder("scan_{ScanID}.nxs"), "scan_12.nxs")

    def test_filename_creates_directory(self):
        subdir = os.path.join(self.tmpdir, "sub", "dir")
        self.env["ScanDir"] = subdir
        rec = nxsrecorder.NXS_FileRecorder(
            os.path.join(subdir, "test.nxs"), macro=self.macro)
        self.assertTrue(os.path.isdir(subdir))
        self.assertEqual(rec.getFileName(), os.path.join(subdir, "test.nxs"))

    # beamtime

    def test_beamtime_id(self):
        rec = self.recorder()
        with open(os.path.join(
                self.tmpdir, "beamtime-metadata-12345678.json"), "w") as fl:
            fl.write("{}")
        self.assertEqual(
            rec.beamtime_id(self.tmpdir, "beamtime-metadata-", ".json"),
            "12345678")
        self.assertEqual(
            rec.beamtime_id("/gpfs/current", "beamtime-metadata-", ".json"),
            "")
        self.assertEqual(
            rec.beamtime_id(self.tmpdir, "other-", ".json"), "")

    def test_beamtimeid_env(self):
        with open(os.path.join(
                self.tmpdir, "beamtime-metadata-87654321.json"), "w") as fl:
            fl.write("{}")
        self.env["BeamtimeFilePath"] = self.tmpdir
        rec = self.recorder()
        self.assertEqual(rec.beamtimeid(), "87654321")
        self.env["BeamtimeFilePath"] = "/gpfs/current"
        rec = self.recorder()
        self.assertEqual(rec.beamtimeid(), "00000000")

    # classic mode, i.e. the recorder writes the file

    @unittest.skipUnless(h5py, "h5py is not available")
    def test_classic_scan(self):
        rec = self.recorder()
        rec._addCustomData("water", "sample_name")
        self.scan(rec)
        fname = os.path.join(self.tmpdir, "test.nxs")
        self.assertTrue(os.path.isfile(fname))
        with h5py.File(fname, "r") as fl:
            entry = fl[ENTRY]
            self.assertEqual(entry.attrs["NX_class"], "NXentry")
            self.assertEqual(
                list(entry["instrument/det/counter"][...]), [1.5, 2.5])
            self.assertEqual(
                list(entry["data/counter"][...]), [1.5, 2.5])
            self.assertEqual(
                entry["sample/name"][()].decode()
                if isinstance(entry["sample/name"][()], bytes)
                else entry["sample/name"][()], "water")
            self.assertEqual(
                _str(entry["start_time"][()]),
                "2026-11-25T10:00:00.000000+0100")
            self.assertEqual(
                _str(entry["end_time"][()]),
                "2026-11-25T10:00:05.000000+0100")
            self.assertEqual(_str(entry["end_reason"][()]), "SUCCESS")
        self.assertFalse(rec.h5map_mode)
        self.assertEqual(rec.h5maps(), {})
        self.assertEqual(self.userdata[0]["sample_name"], "water")

    @unittest.skipUnless(h5py, "h5py is not available")
    def test_classic_custom_data_removed(self):
        rec = self.recorder()
        rec._addCustomData("water", "sample_name")
        rec._addCustomData(None, "sample_name", remove=True)
        rec._addCustomData(7, "custom", group="vars")
        rec._addCustomData(8, "other", group=None)
        rec._addCustomData(None, "other", group=None, remove=True)
        self.scan(rec, values=())
        self.assertTrue("sample_name" not in self.userdata[0])
        with h5py.File(os.path.join(self.tmpdir, "test.nxs"), "r") as fl:
            self.assertEqual(
                _str(fl[ENTRY]["sample/name"].attrs["nexdatas_canfail"]),
                "FAILED")

    @unittest.skipUnless(h5py, "h5py is not available")
    def test_classic_end_reasons(self):
        if nxsrecorder.ScanEndStatus is None:
            self.skipTest("sardana ScanEndStatus is not available")
        status = nxsrecorder.ScanEndStatus
        fname = os.path.join(self.tmpdir, "test.nxs")
        for name, reason in nxsrecorder.END_REASON_BY_END_STATUS.items():
            if os.path.exists(fname):
                os.remove(fname)
            self.recordlist.env["endstatus"] = getattr(status, name)
            self.scan(self.recorder(), values=(1.0,))
            with h5py.File(fname, "r") as fl:
                self.assertEqual(
                    _str(fl[ENTRY]["end_reason"][()]), reason, name)

    @unittest.skipUnless(h5py, "h5py is not available")
    def test_classic_nostep(self):
        self.env["NeXusWriterModes"] = ["NOSTEP"]
        self.scan(self.recorder())
        with h5py.File(os.path.join(self.tmpdir, "test.nxs"), "r") as fl:
            self.assertEqual(
                fl[ENTRY]["instrument/det/counter"].shape[0], 0)
            self.assertEqual(_str(fl[ENTRY]["end_reason"][()]), "SUCCESS")

    @unittest.skipUnless(h5py, "h5py is not available")
    def test_classic_noinit_nofinal(self):
        self.env["NeXusWriterModes"] = ["NOINIT", "NOFINAL"]
        rec = self.recorder()
        rec._addCustomData("water", "sample_name")
        self.scan(rec)
        with h5py.File(os.path.join(self.tmpdir, "test.nxs"), "r") as fl:
            entry = fl[ENTRY]
            self.assertEqual(_str(entry["start_time"][()]), "")
            self.assertEqual(_str(entry["end_time"][()]), "")
            self.assertEqual(
                list(entry["instrument/det/counter"][...]), [1.5, 2.5])

    def test_scicat_dataset_list(self):
        self.env["NXSAppendSciCatDataset"] = True
        self.scan(self.recorder(), values=(1.0,))
        lst = os.path.join(self.tmpdir, "scicat-datasets-00000000.lst")
        with open(lst) as fl:
            self.assertEqual(
                fl.read(), "\ntest::/scan_00012;test_00012")

    def test_scicat_dataset_list_new_file(self):
        self.selector = Selector(appendentry=False)
        self.env["NXSAppendSciCatDataset"] = True
        self.scan(self.recorder(), values=(1.0,))
        lst = os.path.join(self.tmpdir, "scicat-datasets-00000000.lst")
        with open(lst) as fl:
            self.assertEqual(fl.read(), "\ntest_00012")

    # h5map mode

    @unittest.skipUnless(H5MAP, "the h5map writer is not available")
    def test_h5map_mode_switch(self):
        rec = self.recorder()
        self.assertFalse(rec.h5map_mode)
        self.assertEqual(rec.h5maps(), {})
        rec.enable_h5map()
        self.assertTrue(rec.h5map_mode)
        self.assertEqual(rec.h5maps(), {})
        rec.disable_h5map()
        self.assertFalse(rec.h5map_mode)

    @unittest.skipUnless(H5MAP, "the h5map writer is not available")
    def test_h5map_scan(self):
        rec = self.recorder()
        rec._addCustomData("water", "sample_name")
        rec.enable_h5map()
        streams = StreamResolver(DATADESC)
        rec.startRecordList(self.recordlist)
        fname = os.path.join(self.tmpdir, "test.nxs")
        start = rec.h5maps(streams, skip=["FINAL"])
        self.assertEqual(list(start.keys()), [fname])
        entry = start[fname]["children"][ENTRY]["children"]
        self.assertEqual(
            sorted(entry.keys()),
            ["data", "instrument", "sample", "start_time"])
        self.assertEqual(
            entry["sample"]["children"]["name"]["value"], "water")

        # the scan data handler: second start and records are ignored
        rec.startRecordList(self.recordlist)
        rec.writeRecord(Record({"exp_c01": 1.5}))
        self.assertEqual(len(self.userdata), 1)
        rec.endRecordList(self.recordlist)
        self.assertFalse(os.path.exists(fname))

        end = rec.h5maps(streams)[fname]["children"][ENTRY]["children"]
        self.assertEqual(end["end_time"]["value"],
                         "2026-11-25T10:00:05.000000+0100")
        self.assertEqual(end["end_reason"]["value"], "SUCCESS")
        self.assertEqual(
            end["instrument"]["children"]["det"]["children"]["counter"][
                "value"], {"type": "stream", "stream": "exp_c01"})
        self.assertEqual(
            end["data"]["children"]["counter"],
            {"type": "soft_link",
             "target_path": "/%s/instrument/det/counter" % ENTRY})
        json.dumps(rec.h5maps(streams), allow_nan=False)

    @unittest.skipUnless(H5MAP, "the h5map writer is not available")
    def test_h5map_disable_after_start(self):
        rec = self.recorder()
        rec.enable_h5map()
        rec.startRecordList(self.recordlist)
        self.assertTrue(rec.h5maps())
        ncommands = self.selector.commands.count("removeDynamicComponent")
        rec.disable_h5map()
        self.assertFalse(rec.h5map_mode)
        self.assertEqual(rec.h5maps(), {})
        self.assertEqual(
            self.selector.commands.count("removeDynamicComponent"),
            ncommands + 1)

    @unittest.skipUnless(H5MAP and h5py,
                         "the h5map writer or h5py is not available")
    def test_h5map_same_as_classic(self):
        # the classic file
        self.scan(self.recorder(), values=())
        fname = os.path.join(self.tmpdir, "test.nxs")
        with h5py.File(fname, "r") as fl:
            classic = _tree(fl[ENTRY])
        os.remove(fname)

        # the h5map of the same scan
        rec = self.recorder()
        rec.enable_h5map()
        self.scan(rec, values=())
        h5map = rec.h5maps()[fname]["children"][ENTRY]
        self.assertEqual(_maptree(h5map), classic)


def _str(value):
    """ converts an h5py string value to str
    """
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, numpy.ndarray) and value.shape == (1,):
        return _str(value[0])
    return str(value)


def _tree(grp):
    """ provides group, field and link names with NX_class of a h5py group
    """
    items = {}
    for name in grp.keys():
        lnk = grp.get(name, getlink=True)
        if isinstance(lnk, h5py.SoftLink):
            items[name] = "link:" + lnk.path
        elif isinstance(grp[name], h5py.Group):
            items[name] = (_str(grp[name].attrs.get("NX_class", "")),
                           _tree(grp[name]))
        else:
            items[name] = "field"
    return items


def _maptree(item):
    """ provides group, field and link names with NX_class of a h5map group
    """
    items = {}
    for name, child in item.get("children", {}).items():
        if child.get("type") == "soft_link":
            items[name] = "link:" + child["target_path"]
        elif child.get("type") == "group":
            items[name] = (child.get("attributes", {}).get("NX_class", ""),
                           _maptree(child))
        else:
            items[name] = "field"
    return items


if __name__ == '__main__':
    unittest.main()
