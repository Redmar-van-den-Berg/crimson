# -*- coding: utf-8 -*-
"""
    crimson.fastqc
    ~~~~~~~~~~~~~~

    FastQC output parsing.

"""
# (c) 2015-2018 Wibowo Arindrarto <bow@bow.web.id>
from io import StringIO
from os import path, walk
from zipfile import ZipFile

import click

from .utils import convert, get_handle


__all__ = ["parse"]


_MAX_LINE_SIZE = 1024
_RESULTS_FNAME = "fastqc_data.txt"


class FastQCModule(object):

    """Class representing a FastQC analysis module."""

    def __init__(self, raw_lines, end_mark='>>END_MODULE'):
        """

        :param raw_lines: list of lines in the module
        :type raw_lines: list of str
        :param end_mark: mark of the end of the module
        :type end_mark: str

        """
        self.extra = {}
        self.raw_lines = raw_lines
        self.end_mark = end_mark
        self.status = None
        self.name = None
        self.contents = self._parse()

    @property
    def dict(self):
        """Module data as a dictionary."""
        payload = {
            "contents": self.contents,
            "status": self.status
        }
        if len(self.extra) > 0:
            for ek, ev in self.extra.items():
                payload[ek] = ev
        return payload

    def _parse(self):
        """Common parser for a FastQC module."""

        # Helper function for converting FastQC values that keeps
        # the "Base" column as strings (since it can be a number
        # or a strin denoting a range)
        def fqc_convert(k, v):
            if k == "Base":
                return v
            return convert(v)

        # check that the last line is a proper end mark
        assert self.raw_lines[-1].startswith(self.end_mark)
        # parse name and status from first line
        tokens = self.raw_lines[0].strip().split('\t')
        name = tokens[0][2:]
        self.name = name
        status = tokens[-1]
        self.status = status
        # the rest of the lines except the last one
        data = []
        if self.name != "Sequence Duplication Levels":
            # and column names from second/third line
            columns = self.raw_lines[1][1:].strip().split("\t")
            self._columns = columns
            for line in self.raw_lines[2:-1]:
                cols = line.strip().split("\t")
                data.append(cols)
        else:
            extra_k, extra_v = self.raw_lines[1][1:].strip().split("\t")
            self.extra[extra_k] = convert(extra_v)
            columns = self.raw_lines[2][1:].strip().split("\t")
            self._columns = columns
            for line in self.raw_lines[3:-1]:
                cols = line.strip().split("\t")
                data.append(cols)

        # optional processing for different modules
        if self.name == 'Basic Statistics':
            data = {k: convert(v) for k, v in data}
        else:
            # zip column names and its values ~ each item in array == one row
            data = [zip(columns, [v for v in d]) for d in data]
            # try to convert numbers appropriately
            # except for "Base" column, since FastQC may output it as range
            data = [{k: fqc_convert(k, v) for k, v in zpd} for zpd in data]

        return data


class FastQC(object):

    """Class representing results from a FastQC run."""

    _mod_names = [
        ">>Basic Statistics",
        ">>Per base sequence quality",
        ">>Per sequence quality scores",
        ">>Per base sequence content",
        ">>Per base GC content",
        ">>Per sequence GC content",
        ">>Per base N content",
        ">>Sequence Length Distribution",
        ">>Sequence Duplication Levels",
        ">>Overrepresented sequences",
        ">>Kmer Content",
    ]

    _mod_map = {k: k.lstrip(">") for k in _mod_names}

    def __init__(self, fp, max_line_size=_MAX_LINE_SIZE):
        """

        :param fp: open file handle pointing to the FastQC data file
        :type fp: file handle
        :param max_line_size: maximum number of bytes read everytime the
                              underlying ``readline`` is called (default: 1024).
        :type max_line_size: int

        """
        self.modules = {}
        self._max_line_size = _MAX_LINE_SIZE

        line = fp.readline(self._max_line_size)
        attr = ""
        while True:

            tokens = line.strip().split('\t')
            # break on EOF
            if not line:
                break
            # parse version
            elif line.startswith('##FastQC'):
                self.version = line.strip().split()[1]
            # parse individual modules
            elif tokens[0] in self._mod_map:
                attr = self._mod_map[tokens[0]]
                raw_lines = self._read_module(fp, line)
                self.modules[attr] = FastQCModule(raw_lines)

            line = fp.readline(self._max_line_size)

    def _read_module(self, fp, line):
        """Returns a list of lines in a module.

        :param fp: open file handle pointing to the FastQC data file
        :type fp: file handle
        :param line: first line in the module
        :type line: str
        :returns: a list of lines in the module
        :rtype: list of str

        """
        raw = [line]
        while not line.startswith('>>END_MODULE'):
            line = fp.readline(self._max_line_size)
            raw.append(line)

            if not line:
                raise ValueError("Unexpected end of file in module %r" % line)

        return raw

    @property
    def dict(self):
        """FastQC data as a dictionary."""
        payload = {k: v.dict for k, v in self.modules.items()}
        payload["version"] = self.version
        return payload


def parse(in_data):
    """Parses FastQC results into a dictionary.

    :param in_data: File handle of a fastqc_data.txt file, or path to a
                    fastqc_data.txt file, or path to a FastQC results
                    directory, or path to a zipped FastQC result.
    :type in_data: str or file handle
    :returns: Parsed FastQC values.
    :rtype: dict

    """
    # Input is FastQC directory.
    if path.isdir(in_data):
        try:
            ori = in_data
            in_data = path.join(ori, next(walk(ori))[1][0], _RESULTS_FNAME)
        except IndexError:
            raise click.BadParameter("Cannot find {0} file in the given"
                                     " directory.".format(_RESULTS_FNAME))
    # Input is zipped FastQC result
    if in_data.endswith(".zip"):
        zf = ZipFile(in_data)
        try:
            data_fname, = [f for f in zf.namelist()
                           if f.endswith(_RESULTS_FNAME)]
        except ValueError:
            raise click.BadParameter("File {0} contains an unexpected number"
                                     " of files named {1}."
                                     "".format(in_data, _RESULTS_FNAME))
        data_contents = zf.read(data_fname).decode("utf-8")
        return FastQC(StringIO(data_contents)).dict

    # Input is a fastqc_data.txt file handle or path to it.
    with get_handle(in_data) as fh:
        return FastQC(fh).dict
