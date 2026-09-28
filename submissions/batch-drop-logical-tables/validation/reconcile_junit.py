# Copyright 2023 Greptime Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Reconciles a JUnit report with the nextest Summary line of the same run."""
import re, sys, xml.etree.ElementTree as E
xml_path, log_path = sys.argv[1], sys.argv[2]
root = E.parse(xml_path).getroot()
cases = list(root.iter('testcase'))
failed = [c for c in cases if c.find('failure') is not None or c.find('error') is not None]
summ = [l for l in open(log_path, errors='replace') if 'Summary [' in l]
m = re.search(r'(\d+) tests? run: (\d+) passed(?:, (\d+) failed)?', summ[-1]) if summ else None
run, passed, nfail = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else (None, None, None)
print(f"junit: {len(cases)} testcases, {len(failed)} failed | root tests={root.get('tests')} failures={root.get('failures')} errors={root.get('errors')}")
print(f"nextest summary: run={run} passed={passed} failed={nfail}")
ok = (len(cases) == run and len(failed) == nfail and int(root.get('tests')) == run and int(root.get('failures')) + int(root.get('errors') or 0) == nfail)
print("RECONCILED" if ok else "MISMATCH")
fb = [c for c in cases if c.get('name','').endswith(('::build', '::run', '::discovery'))]
print("fallback junit used:", bool(fb))
for c in failed:
    f = c.find('failure') if c.find('failure') is not None else c.find('error')
    text = (f.text or '') + ' ' + (f.get('message') or '')
    cause = re.search(r"panicked at ([^\n]+)\n([^\n]*)", text)
    print("  FAIL", c.get('name').split('::')[-1], "->", (cause.group(1) + " | " + cause.group(2)[:110]) if cause else text.strip()[:140])
