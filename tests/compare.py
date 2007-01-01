#!/usr/bin/env python
#
# compare.py -- High-level tests for x.
# Copyright (c) 2006 Brett Smith <brettcsmith@brettcsmith.org>.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, 5th Floor, Boston, MA, 02111.

import os
import re
import subprocess
import syck
import sys
import tempfile

from sets import Set as set

if os.path.exists('scripts/x') and os.path.exists('tests'):
    os.chdir('tests')
elif os.path.exists('../scripts/x') and os.path.exists('../tests'):
    pass
else:
    print "ERROR: Can't run tests in this directory!"
    sys.exit(2)

X_SCRIPT = os.path.realpath('../scripts/x')
ROOT_DIR = os.path.realpath(os.curdir)
OUTCOMES = ['error', 'failed', 'passed']
TESTSCRIPT_NAME = 'testscript.sh'
SCRIPT_PROLOGUE = """#!/bin/sh
set -e
"""

output_buffer = tempfile.TemporaryFile()

class ExtractorTestError(Exception):
    pass


class ExtractorTest(object):
    def __init__(self, **kwargs):
        for key in ('name',):
            setattr(self, key, kwargs[key])
        for key in ('directory', 'prerun', 'posttest', 'baseline', 'error',
                    'grep', 'antigrep'):
            setattr(self, key, kwargs.get(key, None))
        for key in ('options', 'filenames'):
            setattr(self, key, kwargs.get(key, '').split())
        
    def get_results(self, commands):
        print >>output_buffer, "Output from %s:" % (' '.join(commands),)
        output_buffer.flush()
        status = subprocess.call(commands, stdout=output_buffer,
                                 stderr=output_buffer)
        process = subprocess.Popen(['find', '!', '-name', TESTSCRIPT_NAME],
                                   stdout=subprocess.PIPE)
        process.wait()
        output = process.stdout.read(-1)
        process.stdout.close()
        return status, set(output.split('\n'))
        
    def write_script(self, commands):
        script = open(TESTSCRIPT_NAME, 'w')
        script.write("%s%s\n" % (SCRIPT_PROLOGUE, commands))
        script.close()
        subprocess.call(['chmod', 'u+w', TESTSCRIPT_NAME])

    def get_shell_results(self):
        self.write_script(self.baseline)
        return self.get_results(['sh', TESTSCRIPT_NAME] + self.filenames)

    def get_extractor_results(self):
        if self.prerun:
            self.write_script(self.prerun)
            subprocess.call(['sh', TESTSCRIPT_NAME])
        return self.get_results([X_SCRIPT] + self.options + self.filenames)
        
    def get_posttest_result(self):
        if not self.posttest:
            return 0
        self.write_script(self.posttest)
        return subprocess.call(['sh', TESTSCRIPT_NAME])

    def clean(self):
        if self.directory:
            target = os.path.join(ROOT_DIR, self.directory)
            extra_options = ['!', '-name', TESTSCRIPT_NAME]
        else:
            target = ROOT_DIR
            extra_options = ['-type', 'd',
                             '!', '-name', 'CVS',
                             '!', '-name', '.svn']
        status = subprocess.call(['find', target,
                                  '-mindepth', '1', '-maxdepth', '1'] +
                                 extra_options +
                                 ['-exec', 'rm', '-rf', '{}', ';'])
        if status != 0:
            raise ExtractorTestError("cleanup exited with status code %s" %
                                     (status,))

    def show_status(self, status, message=None):
        raw_status = status.lower()
        if raw_status != 'passed':
            output_buffer.seek(0, 0)
            sys.stdout.write(output_buffer.read(-1))
        if message is None:
            last_part = ''
        else:
            last_part = ': %s' % (message,)
        print "%7s: %s%s" % (status, self.name, last_part)
        return raw_status

    def compare_results(self, actual):
        posttest_result = self.get_posttest_result()
        self.clean()
        status, expected = self.get_shell_results()
        self.clean()
        if expected != actual:
            print >>output_buffer, "Only in baseline results:"
            print >>output_buffer, '\n'.join(expected.difference(actual))
            print >>output_buffer, "Only in actual results:"
            print >>output_buffer, '\n'.join(actual.difference(expected))
            return self.show_status('FAILED')
        elif posttest_result != 0:
            print >>output_buffer, "Posttest gave status code", posttest_result
            return self.show_status('FAILED')
        return self.show_status('Passed')
    
    def have_error_mismatch(self, status):
        if self.error and (status == 0):
            return "x did not return expected error"
        elif (not self.error) and (status != 0):
            return "x returned error code %s" % (status,)
        return None

    def grep_output(self):
        output_buffer.seek(0, 0)
        output_buffer.readline()
        output = output_buffer.read(-1)
        if self.grep and (not re.search(self.grep, output)):
            return "output did not match %s" % (self.grep)
        elif self.antigrep and re.search(self.antigrep, output):
            return "output matched antigrep %s" % (self.antigrep)
        return None

    def check_results(self):
        output_buffer.seek(0, 0)
        output_buffer.truncate()
        self.clean()
        status, actual = self.get_extractor_results()
        problem = self.have_error_mismatch(status) or self.grep_output()
        if problem:
            return self.show_status('FAILED', problem)
        return self.compare_results(actual)

    def run(self):
        if self.directory:
            os.mkdir(self.directory)
            os.chdir(self.directory)
        try:
            result = self.check_results()
        except ExtractorTestError, error:
            result = self.show_status('ERROR', error)
        if self.directory:
            os.chdir(ROOT_DIR)
            subprocess.call(['chmod', '-R', '700', self.directory])
            subprocess.call(['rm', '-rf', self.directory])
        return result


test_db = open('tests.yml')
test_data = syck.load(test_db.read(-1))
test_db.close()
tests = [ExtractorTest(**data) for data in test_data]
for original_data in test_data:
    if (original_data.has_key('directory') or
        (not original_data.has_key('baseline'))):
        continue
    data = original_data.copy()
    data['name'] += ' in ..'
    data['directory'] = 'inside-dir'
    data['filenames'] = ' '.join(['../%s' % filename for filename in
                                  data.get('filenames', '').split()])
    tests.append(ExtractorTest(**data))
results = [test.run() for test in tests]
counts = {}
for outcome in OUTCOMES:
    counts[outcome] = 0
for result in results:
    counts[result] += 1
print " Totals:", ', '.join(["%s %s" % (counts[key], key) for key in OUTCOMES])
output_buffer.close()
