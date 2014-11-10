#!/usr/bin/python
# -*- coding: utf-8; -*-
# Copyright (c) 2014 The Ostrich | by Itamar O
# pylint: disable=protected-access,bad-indentation,too-few-public-methods,global-statement

"""Utility script to automate style stuff and other nitpickings."""

__author__ = 'Itamar Ostricher'

import argparse
import codecs
import difflib
import os
import re
import sys
from collections import defaultdict

import cpplint
from cpplint import FileInfo
from cpplint import _ClassifyInclude as classify_include

_STYLE_MODULES_DICT = {
    u'sort_includes': (u'Automatically divide includes into sections are sort '
                       'them, according to Google C++ Style Guide'),
}
_STYLE_MODULES = frozenset(_STYLE_MODULES_DICT.keys())
_RE_PATTERN_INCLUDE = re.compile(  # from cpplint + modifications
    r'^\s*#\s*include\s*([<"])\s*([^>"\s]*)\s*[>"](.*$)')
_SECTIONS_ORDER = [
    (cpplint._LIKELY_MY_HEADER, cpplint._POSSIBLE_MY_HEADER),
    (cpplint._C_SYS_HEADER,),
    (cpplint._CPP_SYS_HEADER,),
    (cpplint._LIBS_HEADER,),
    (cpplint._OTHER_HEADER,),
]
_QUIET = False

def stringify(message, *args):
  """Return formatted message by applying args, if any."""
  if args:
    return u'%s\n' % (message % (args))
  else:
    return u'%s\n' % (message)

def err(message, *args):
  """Error message printer."""
  formatted = stringify(message, *args)
  sys.stderr.write(u'ERROR: %s' % (formatted))
  raise RuntimeError(formatted.strip())

def warn(message, *args):
  """Warning message printer."""
  sys.stderr.write(u'WARNING: ' + stringify(message, *args))

def info(message, *args):
  """Info message printer."""
  if not _QUIET:
    sys.stderr.write(u'INFO: ' + stringify(message, *args))

def differ(line):
  """Diff line printer."""
  sys.stderr.write(u'%s\n' % (line))

class HFile(object):
  """Included h-file class."""
  def __init__(self, include_str):
    """Initialize an include file instance from the include string."""
    match = _RE_PATTERN_INCLUDE.match(include_str)
    if not match:
      raise Exception(u'Not an include line: "%s"' % (include_str))
    self.name = match.group(2)
    if match.group(1) == '<':
      self.is_system = True
      self.repr_pattern = u'#include <{hfile}>{post_str}'
    else:
      self.is_system = False
      self.repr_pattern = u'#include "{hfile}"{post_str}'
    self.post_str = match.group(3)

  def __repr__(self):
    """Return a string representation of the included h file."""
    return self.repr_pattern.format(hfile=self.name, post_str=self.post_str)

def is_own_header(src_file, include):
  """Return True if `include` is the 'self'-header-file for `src_file`."""
  inc_pref = os.path.splitext(include)[0]
  src_pref = os.path.splitext(src_file)[0]
  if src_pref.endswith('_test'):
    src_pref = src_pref[:-5]
  return inc_pref == src_pref

def is_project_file(file_path):
  """Return True if `file_path` belongs to the project."""
  file_dir = file_path.split(os.path.sep)[0]
  return os.path.isfile(file_path) or os.path.isdir(file_dir)

def sort_includes_batch(filename, includes):
  """Return a list with the includes, sorted in sections."""
  by_type = defaultdict(list)
  for name in sorted(includes.keys()):
    hfile = includes[name]
    inc_type = classify_include(FileInfo(filename), hfile.name,
                                hfile.is_system)
    if inc_type in (cpplint._LIKELY_MY_HEADER, cpplint._POSSIBLE_MY_HEADER):
      if not is_own_header(filename, name):
        inc_type = cpplint._OTHER_HEADER
    by_type[inc_type].append(repr(hfile))
  sorted_includes = []
  for sections in _SECTIONS_ORDER:
    for inc_type in by_type.keys():
      if inc_type in sections:
        sorted_includes.extend(by_type[inc_type])
    if sorted_includes and sorted_includes[-1]:
      sorted_includes.append(u'')
  return sorted_includes

def sort_includes(filename, lines):
  """Return `lines` with include sections replaced with sorted versions."""
  includes_batches = 0
  in_batch = False
  includes = dict()
  new_lines = []
  for lnum, line in enumerate(lines):
    if line.strip().startswith(u'#include'):
      if not in_batch:
        includes_batches += 1
        in_batch = True
      # Process include line
      hfile = HFile(line)
      hkey = hfile.name.lower()
      if hkey in includes:
        # Include repeats in batch
        if repr(hfile) == repr(includes[hkey]):
          # Occurences are consistent - just a warning then
          warn(u'"%s" included more than once (consistently) in "%s:%d": %s',
               hfile.name, filename, lnum+1, hfile)
        else:
          # Occurences inconsistent! it's an error.
          err(u'"%s" included more than once (inconsistently) in "%s:%d": %s',
              hfile.name, filename, lnum+1, hfile)
      else:
        # Add include to batch
        includes[hkey] = hfile
        # Sanity check system-vs-project include
        if is_project_file(hfile.name):
          if hfile.is_system:
            warn(u'"%s" looks like a project-file, but is included with <> '
                 'in "%s:%d": %s', hfile.name, filename, lnum+1, repr(hfile))
        else:
          if not hfile.is_system:
            warn(u'"%s" looks like a system-file, but is included with "" '
                 'in "%s:%d": %s', hfile.name, filename, lnum+1, repr(hfile))
    else:
      if in_batch:
        # Maybe end of includes batch?
        if line.strip():
          # Yes!
          in_batch = False
          new_lines.extend(sort_includes_batch(filename, includes))
          includes = dict()
        else:
          # No, just a blank line
          continue
      new_lines.append(line)
  if in_batch:
    # In case the source file ends with batch of includes
    new_lines.extend(sort_includes_batch(filename, includes))
  if includes_batches > 1:
    warn(u'More than 1 batch of #include\'s in "%s"', filename)
  return new_lines

def stylify_lines(args, filename, lines):
  """Run stylify modules on `lines` and return styled lines."""
  for mod in args.modules:
    if u'sort_includes' == mod:
      lines = sort_includes(filename, lines)
  return lines

def stylify_file(args, filepath):
  """Stylify `filepath`."""
  if '-' == filepath:
    # Reading from STDIN
    old_content = sys.stdin.read()
    filename = args.filename or '-'
  else:
    # Reading from filepath
    filename = filepath
    with codecs.open(filepath, 'r', 'utf8', 'replace') as src_f:
      old_content = src_f.read()
  cpplint.ProcessConfigOverrides(filename)
  lines = old_content.split(u'\n')
  new_lines = stylify_lines(args, filename, lines)
  new_content = u'\n'.join(new_lines)
  if new_content != old_content:
    if args.show_diff:
      info(u'Modified content of %s. Diff:', filename)
      for diffline in difflib.unified_diff(lines, new_lines,
                                           fromfile='%s (before)' % (filename),
                                           tofile='%s (after)' % (filename)):
        differ(diffline)
    if '-' == filepath:
      sys.stdout.write(new_content)
    elif not args.no_edit:
      info(u'Writing changes back to filepath %s ...', filepath)
      with codecs.open(filepath, 'w', 'utf8', 'replace') as f_out:
        f_out.write(new_content)
  else:
    info(u'No changes for %s ...', filename)

def stylify(args, files):
  """Stylify files."""
  if args.modules:
    args.modules = set(args.modules)
    assert args.modules <= _STYLE_MODULES
  else:
    args.modules = _STYLE_MODULES
  if files:
    for filepath in files:
      filepath = os.path.normpath(filepath)
      info(u'Stylifying file %s ...', filepath)
      try:
        stylify_file(args, filepath)
      except RuntimeError:
        info(u'Skipping file %s ...', filepath)
      else:
        info(u'Done with file %s ...', filepath)
  else:
    stylify_file(args, '-')

def main():
  """Run nitpick command on input(s)."""
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers()
  styler_parser = subparsers.add_parser('style',
                                        help=u'Stylify C++ source code')
  styler_parser.add_argument('--no_edit', action='store_true',
                             help=u'Don\'t overwrite source file with '
                             'stylified output')
  styler_parser.add_argument('--show_diff', action='store_true',
                             help=u'Print diffs between input file and '
                             'stylified file to STDERR')
  styler_parser.add_argument('--quiet', action='store_true',
                             help=u'Don\'t print progress '
                             '(only warnings and errors)')
  modules_help_str = u'\n'.join([u'%s: %s' % (mod, desc) for mod, desc in
                                 _STYLE_MODULES_DICT.iteritems()])
  styler_parser.add_argument('-m', '--modules', action='append', metavar='MOD',
                             help=modules_help_str)
  styler_parser.add_argument('--filename',
                             help=u'When reading source code from STDIN, spec'
                             'ify the filename of the processed source code')
  styler_parser.set_defaults(func=stylify)
  # Change stderr to write with replacement characters so we don't die
  # if we try to print something containing non-ASCII characters.
  sys.stderr = codecs.StreamReaderWriter(sys.stderr,
                                         codecs.getreader('utf8'),
                                         codecs.getwriter('utf8'),
                                         'replace')

  args, files = parser.parse_known_args()
  global _QUIET
  _QUIET = args.quiet
  args.func(args, files)

if __name__ == '__main__':
  main()
