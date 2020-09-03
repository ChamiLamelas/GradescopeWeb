#!/usr/bin/env python3
import pathlib

import gradescope_web

g = gradescope_web.GradescopeSession()

comp15 = next(x for x in g.classes if x._path == "/courses/81671")
print(comp15.role)
hw = [x for x in comp15.assignments if x.name in ["hw1", "hw2", "hw3"]]
print(hw)

for x in hw:
    pathlib.Path("./hw/" + x.name).mkdir(parents=True, exist_ok=True)
    for s in x.submissions:
        with open("./hw/" + x.name + "/" + s.href.split('/')[-1], 'w') as f:
            s.get_testcases()
            print(s.testcases, file=f)
