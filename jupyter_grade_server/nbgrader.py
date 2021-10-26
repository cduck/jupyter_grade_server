import base64
import re
from path import Path

import nbformat
import ansi2html

from nbgrader.apps.autogradeapp import AutogradeApp
from nbgrader.converters import Autograde
from nbgrader.api import Gradebook


def autograde(lab_name):
    grader = AutogradeApp()
    # Override methods with unwanted side effects
    grader.init_syspath = lambda:None
    grader.fail = grader.log.error
    # Run
    grader.initialize([lab_name])
    super(AutogradeApp, grader).start()
    if len(grader.extra_args) == 1:
        grader.coursedir.assignment_id = grader.extra_args[0]
    converter = Autograde(coursedir=grader.coursedir, parent=grader)
    converter.start()

def get_feedback(lab_name):
    nb = nbformat.read(Path() / 'autograded' / 'student' / lab_name / f'{lab_name}.ipynb', as_version=4)
    release_nb = nbformat.read(Path() / 'release' / lab_name / f'{lab_name}.ipynb', as_version=4)

    color_converter=ansi2html.Ansi2HTMLConverter(inline=True)

    def formatted_error_output(cell, whole_traceback=True):
        out_html = ''
        for output in reversed(cell.get('outputs', [])):
            if output.get('output_type') == 'error':
                if whole_traceback:
                    out_str = '\n'.join(output.get('traceback', ['Unknown error']))
                else:
                    out_str = output.get('traceback', ['Unknown error'])[-1]
                colored = color_converter.convert(out_str, full=False)
                out_html = f'''<pre>{colored}</pre>'''
                break
        return out_html

    def formatted_test_output(cell, whole_traceback=False):
        max_points = cell['metadata']['nbgrader'].get('points', 0)
        points = 0
        pnumber = cell['metadata']['nbgrader'].get('grade_id', ''
                    ).replace('-test', '').replace('test', '').replace('-', '.')

        out_html = '''<pre><span style="font-weight: bold">Not Graded</span></pre>'''
        for output in reversed(cell['outputs']):
            if output.get('output_type') == 'error':
                if whole_traceback:
                    out_str = '\n'.join(output.get('traceback', ['Unknown error']))
                else:
                    out_str = output.get('traceback', ['Unknown error'])[-1]
                colored = color_converter.convert(out_str, full=False)
                out_html = f'''<pre>{colored}</pre>'''
                break
        else:
            # No error output
            if (not cell['metadata']['nbgrader'].get('solution')
                and not cell['metadata']['nbgrader'].get('task')):
                points = max_points
            out_html = '''<pre><span style="font-weight: bold; color: #00aa00">Correct</span></pre>'''

        return f'''
        <h4>Test {pnumber} (score: {points}/{max_points})</h4>
        {out_html}
        <hr>
        '''

    # Find the correct set of tests from the original release document
    test_id_map = {}
    missing_msg = '''
<h4>Test {} (MISSING!)</h4>
<pre style="color: #aa0000">
You probably deleted the cell containing this test.
To fix this, download a fresh copy of the notebook file
and copy your solutions into the fresh notebook.
</pre>
<hr>
'''
    for cell in release_nb['cells']:
        if (cell.get('metadata', {}).get('nbgrader', {}).get('grade', False)
                and cell['metadata']['nbgrader'].get('points', 0) > 0):
            test_id = cell['metadata']['nbgrader'].get('grade_id')
            if test_id:
                pnumber = cell['metadata']['nbgrader'].get('grade_id', ''
                            ).replace('-test', '').replace('test', '').replace('-', '.')
                test_id_map[test_id] = missing_msg.format(pnumber)

    others_out = []
    pre_output = ''
    for cell in nb['cells']:
        if (cell.get('metadata', {}).get('nbgrader', {}).get('grade', False)
                and cell['metadata']['nbgrader'].get('points', 0) > 0):
            test_id = cell['metadata']['nbgrader'].get('grade_id', 'unknown')
            if pre_output:
                pre_output = '<h4>Other Errors</h4>\n' + pre_output
            test_out = pre_output + formatted_test_output(cell)
            pre_output = ''
            if test_id in test_id_map:
                test_id_map[test_id] = test_out
            else:
                others_out.append(test_out)
        else:
            is_test = cell.get('metadata', {}).get('nbgrader', {}).get(
                    'grade', False)
            pre_output += formatted_error_output(cell, not is_test)
    # Ignoring trailing pre_output value

    all_html = (
        ''.join(test_id_map.values())
        #+ ''.join(others_out)  # Ignore tests that aren't supposed to be here
    )
    return all_html

def get_grade(lab_name):
    '''Returns the code score, excluding any manually graded problems.

    Returns a tuple (code_score, max_code_score)
    '''
    with Gradebook('sqlite:///gradebook.db') as gb:
        asgn = gb.find_submission(lab_name, 'student')
        return asgn.code_score, asgn.max_code_score
