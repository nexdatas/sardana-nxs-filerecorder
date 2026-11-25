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

""" h5map builder of NeXus files configured by NXSRecSelector

The builder lets blissdata (e.g. blisswriter) write the NeXus files of
:class:`sardananxsrecorder.nxsrecorder.NXS_FileRecorder` with the
structure configured by the selected NXSConfigServer components.

It is registered in the ``sardana.h5maps`` entry point group as ``nxs``
and selected with::

    senv BlissdataH5Map nxs

The NXS recorders of the scan are switched to the h5map mode, so their
NXSDataWriter builds the NeXus tree in memory and the recorders do not
write the files themselves.  INIT data are exported when the scan starts,
STEP fields are exported as blissdata streams of the scan channels and
FINAL data are exported when the scan ends.
"""

import os

try:
    from sardana.data.publishers.blissdata.h5map import H5MapBuilder
except Exception:
    class H5MapBuilder(object):
        """ h5map builder base of sardana without the blissdata publisher
        """

        def __init__(self, macro):
            """ constructor

            :param macro: the scan macro
            :type macro: :class:`sardana.macroserver.macro.Macro`
            """
            self.macro = macro

from .nxsrecorder import NXS_FileRecorder


def _keys(name):
    """ provides lookup keys of a channel name

    :param name: channel name, alias or label
    :type name: :obj:`str`
    :returns: lookup keys
    :rtype: :obj:`list` <:obj:`str`>
    """
    if not name:
        return []
    name = str(name).lower()
    keys = [name]
    if name.startswith("tango://"):
        name = name[len("tango://"):]
        keys.append(name)
    if "/" in name and ":" in name.split("/")[0]:
        # without the tango host
        keys.append(name.split("/", 1)[1])
    return keys


class StreamResolver(object):
    """ resolves stream names of STEP datasources

    Sardana publishes the channel data in blissdata streams named by the
    channel labels.  The datasource names and records of the NeXus
    configuration usually are channel aliases or channel full names.
    """

    def __init__(self, datadesc):
        """ constructor

        :param datadesc: ``datadesc`` of the scan info, i.e.
                         ``{label: {"name": ..., "label": ...}}``
        :type datadesc: :obj:`dict` <:obj:`str`, :obj:`dict`>
        """
        #: (:obj:`dict` <:obj:`str`, :obj:`str`>) stream names by keys
        self.streams = {}
        for label, desc in (datadesc or {}).items():
            desc = desc if isinstance(desc, dict) else {}
            stream = desc.get("label", label)
            for name in [label, desc.get("label"), desc.get("name")]:
                for key in _keys(name):
                    self.streams.setdefault(key, stream)

    def __call__(self, path, dsname, record, strategy):
        """ provides the stream name of a STEP field

        :param path: field path
        :type path: :obj:`str`
        :param dsname: datasource name
        :type dsname: :obj:`str`
        :param record: datasource record
        :type record: :obj:`str`
        :param strategy: field strategy
        :type strategy: :obj:`str`
        :returns: stream name or None
        :rtype: :obj:`str`
        """
        for name in [record, dsname]:
            for key in _keys(name):
                if key in self.streams:
                    return self.streams[key]
        return None


class NXSH5MapBuilder(H5MapBuilder):
    """ builds h5maps of NeXus files configured by NXSRecSelector
    """

    def __init__(self, macro):
        """ constructor

        :param macro: the scan macro
        :type macro: :class:`sardana.macroserver.macro.Macro`
        """
        H5MapBuilder.__init__(self, macro)
        #: (:obj:`list` <:class:`NXS_FileRecorder`>) recorders of the scan
        self.recorders = []
        #: (:obj:`list` <:class:`NXS_FileRecorder`>) recorders
        #:   which are not driven by the scan data handler
        self.owned = []
        #: (:class:`StreamResolver`) stream name resolver
        self.streams = None
        #: (:class:`sardana.macroserver.scan.scandata.ScanData`) record list
        self.recordlist = None

    def _gscan(self):
        """ provides the scan of the macro

        :returns: the scan
        :rtype: :class:`sardana.macroserver.scan.gscan.GScan`
        """
        gscan = getattr(self.macro, "_gScan", None)
        if gscan is None:
            raise Exception("NXSH5MapBuilder: the macro has no scan")
        return gscan

    def _scan_recorders(self, gscan):
        """ provides the NXS recorders added to the scan data handler

        :param gscan: the scan
        :type gscan: :class:`sardana.macroserver.scan.gscan.GScan`
        :returns: NXS recorders
        :rtype: :obj:`list` <:class:`NXS_FileRecorder`>
        """
        handler = getattr(gscan, "_data_handler", None)
        recorders = getattr(handler, "recorders", None) or []
        return [rec for rec in recorders
                if isinstance(rec, NXS_FileRecorder)]

    def _new_recorders(self):
        """ creates NXS recorders for the NeXus files of ScanFile

        It is used when the scan does not run the classic file recorders.

        :returns: NXS recorders
        :rtype: :obj:`list` <:class:`NXS_FileRecorder`>
        """
        try:
            scan_dir = self.macro.getEnv("ScanDir")
            scan_files = self.macro.getEnv("ScanFile")
        except Exception:
            return []
        if isinstance(scan_files, str):
            scan_files = [scan_files]
        exts = set(NXS_FileRecorder.formats.values())
        recorders = []
        for fname in scan_files or []:
            if os.path.splitext(fname)[1].lower() in exts:
                recorders.append(NXS_FileRecorder(
                    os.path.join(scan_dir, fname), macro=self.macro))
        return recorders

    def _h5maps(self, skip=None):
        """ collects the h5maps of all recorders

        :param skip: strategies of fields to be skipped
        :type skip: :obj:`list` <:obj:`str`>
        :returns: ``{file name: h5map}``
        :rtype: :obj:`dict` <:obj:`str`, `any`>
        """
        h5maps = {}
        for rec in self.recorders:
            h5maps.update(rec.h5maps(self.streams, skip))
        return h5maps

    def start(self, scan_info, snapshot):
        """ returns the h5maps of the scan, before the scan is prepared

        It opens the entries of the NXS recorders in the h5map mode,
        i.e. runs their INIT datasources.  FINAL fields are added by
        :meth:`end`.

        :param scan_info: the scan info, without ``h5maps``
        :type scan_info: :obj:`dict` <:obj:`str`, `any`>
        :param snapshot: the pre-scan snapshot
        :type snapshot: :obj:`list` <:obj:`dict` <:obj:`str`, `any`>>
        :returns: ``{file name: h5map}``
        :rtype: :obj:`dict` <:obj:`str`, `any`>
        """
        gscan = self._gscan()
        self.recordlist = gscan.data
        self.streams = StreamResolver(scan_info.get("datadesc", {}))
        self.recorders = self._scan_recorders(gscan)
        if not self.recorders:
            self.recorders = self._new_recorders()
            self.owned = list(self.recorders)
        if not self.recorders:
            raise Exception(
                "NXSH5MapBuilder: no NeXus file in ScanFile")
        try:
            for rec in self.recorders:
                rec.enable_h5map()
                rec.startRecordList(self.recordlist)
            return self._h5maps(skip=["FINAL"])
        except Exception:
            # the recorders write the files themselves
            for rec in self.recorders:
                rec.disable_h5map()
            self.recorders = []
            self.owned = []
            raise

    def end(self, scan_info):
        """ returns the final h5maps before the scan closes

        The scan data handler has already closed the entries of its
        recorders, i.e. run their FINAL datasources.

        :param scan_info: the final scan info
        :type scan_info: :obj:`dict` <:obj:`str`, `any`>
        :returns: ``{file name: h5map}``
        :rtype: :obj:`dict` <:obj:`str`, `any`>
        """
        for rec in self.owned:
            rec.endRecordList(self.recordlist)
        self.owned = []
        return self._h5maps()
